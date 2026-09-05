#!/usr/bin/env python3
"""Build a fail-closed GitHub dependency-submission snapshot for one native lock."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import IO, Literal, Protocol, cast
from urllib.parse import quote

SNAPSHOT_VERSION = 0
RECEIPT_SCHEMA_VERSION = 2
PIP_INSPECT_SCHEMA_VERSION = "1"
DETECTOR_NAME = "gm2godot-native-pip-lock"
DETECTOR_VERSION = "1"
DETECTOR_SOURCE_PATH = "scripts/build_dependency_snapshot.py"
COMMAND_TIMEOUT_SECONDS = 30.0
COMMAND_OUTPUT_POLL_SECONDS = 0.05
MAX_REQUIREMENTS_BYTES = 1024 * 1024
MAX_CONSTRAINT_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_INSPECT_BYTES = 16 * 1024 * 1024
MAX_COMMAND_STDERR_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024

Scope = Literal["runtime", "development"]

SOURCE_POLICIES: tuple[tuple[Path, Scope], ...] = (
    (Path("requirements.txt"), "runtime"),
    (Path("requirements-bootstrap.txt"), "development"),
    (Path("requirements-tooling.txt"), "development"),
)

PLATFORM_POLICIES: Mapping[str, tuple[str, str, str, str, str, str]] = {
    "linux-x64": (
        "linux",
        "posix",
        "Linux",
        "x86_64",
        "3.12.13",
        "constraints/requirements-linux-py312.lock",
    ),
    "macos-arm64": (
        "darwin",
        "posix",
        "Darwin",
        "arm64",
        "3.12.10",
        "constraints/requirements-macos-py312.lock",
    ),
    "windows-x64": (
        "win32",
        "nt",
        "Windows",
        "AMD64",
        "3.12.10",
        "constraints/requirements-windows-py312.lock",
    ),
}

PIN_PATTERN = re.compile(
    r"(?P<name>[A-Z0-9](?:[A-Z0-9._-]*[A-Z0-9])?)"
    r"\s*==\s*"
    r"(?P<version>[A-Z0-9][A-Z0-9.!+_-]*)\Z",
    re.ASCII | re.IGNORECASE,
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}\Z"
)
REF_PATTERN = re.compile(r"refs/[A-Za-z0-9._/-]+\Z")
SCANNED_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
EXTRA_COMPARISON_PATTERN = re.compile(
    r'(?:'
    r'(?<![A-Za-z0-9_\'\"])(?P<left_variable>extra)(?![A-Za-z0-9_\'\"])\s*'
    r'(?P<left_operator>==|!=)\s*"(?P<right_value>[A-Za-z0-9][A-Za-z0-9._-]*)"'
    r'|'
    r'"(?P<left_value>[A-Za-z0-9][A-Za-z0-9._-]*)"\s*'
    r'(?P<right_operator>==|!=)\s*'
    r'(?<![A-Za-z0-9_\'\"])(?P<right_variable>extra)(?![A-Za-z0-9_\'\"])'
    r')',
    re.ASCII,
)
MARKER_ENVIRONMENT_KEYS = (
    "implementation_name",
    "implementation_version",
    "os_name",
    "platform_machine",
    "platform_python_implementation",
    "platform_release",
    "platform_system",
    "platform_version",
    "python_full_version",
    "python_version",
    "sys_platform",
)
RECEIPT_ENVIRONMENT_KEYS = (
    "implementation_name",
    "implementation_version",
    "os_name",
    "platform_machine",
    "platform_python_implementation",
    "platform_system",
    "python_full_version",
    "python_version",
    "sys_platform",
)


class SnapshotError(ValueError):
    """An input or observed dependency graph violated the snapshot policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _load_anchored_output_module() -> ModuleType:
    """Load the exact stdlib-only sibling without changing ``sys.path``."""

    # This caller is isolated-mode safe. The separate bootstrap wrapper retains
    # its pre-existing sibling-name import and is intentionally outside #858.
    module_path = Path(__file__).resolve(strict=True).with_name("_anchored_output.py")
    module_name = "_gm2godot_anchored_output"
    existing = sys.modules.get(module_name)
    if existing is not None:
        existing_path = getattr(existing, "__file__", None)
        if (
            isinstance(existing_path, str)
            and Path(existing_path).resolve(strict=True) == module_path
        ):
            return existing
        raise ImportError(
            f"Refusing conflicting anchored output module {module_name!r}."
        )

    specification = importlib.util.spec_from_file_location(module_name, module_path)
    if specification is None or specification.loader is None:
        raise ImportError(f"Cannot load anchored output helper: {module_path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_ANCHORED_OUTPUT = _load_anchored_output_module()
_ANCHORED_OUTPUT_ERROR = cast(
    type[ValueError],
    getattr(_ANCHORED_OUTPUT, "AnchoredOutputError"),
)
_PUBLISH_NEW_BYTES = cast(
    Callable[[Path, bytes], None],
    getattr(_ANCHORED_OUTPUT, "publish_new_bytes"),
)


class DuplicateJsonKeyError(ValueError):
    """A JSON object repeated a key and was therefore ambiguous."""


class MarkerProtocol(Protocol):
    def evaluate(
        self,
        environment: Mapping[str, str | frozenset[str]] | None = None,
        context: str = "metadata",
    ) -> bool: ...

    def __str__(self) -> str: ...


class SpecifierProtocol(Protocol):
    @property
    def operator(self) -> str: ...

    @property
    def version(self) -> str: ...


class SpecifierSetProtocol(Protocol):
    def __iter__(self) -> Iterator[SpecifierProtocol]: ...

    def __bool__(self) -> bool: ...

    def contains(
        self,
        item: str,
        prereleases: bool | None = None,
        installed: bool | None = None,
    ) -> bool: ...


class RequirementProtocol(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def url(self) -> str | None: ...

    @property
    def extras(self) -> set[str]: ...

    @property
    def marker(self) -> MarkerProtocol | None: ...

    @property
    def specifier(self) -> SpecifierSetProtocol: ...


RequirementFactory = Callable[[str], RequirementProtocol]
MarkerFactory = Callable[[str], MarkerProtocol]
CanonicalizeName = Callable[[str], str]
VersionFactory = Callable[[str], object]


def _packaging_attribute(module_name: str, attribute_name: str) -> object:
    """Load one runtime packaging API without coupling static checks to ambient Python."""

    try:
        module = importlib.import_module(module_name)
        return getattr(module, attribute_name)
    except (ImportError, AttributeError) as error:
        raise SnapshotError(
            "packaging-api-unavailable",
            f"The verified environment does not provide {module_name}.{attribute_name}.",
        ) from error


REQUIREMENT = cast(RequirementFactory, _packaging_attribute("packaging.requirements", "Requirement"))
MARKER = cast(MarkerFactory, _packaging_attribute("packaging.markers", "Marker"))
CANONICALIZE_NAME = cast(CanonicalizeName, _packaging_attribute("packaging.utils", "canonicalize_name"))
VERSION = cast(VersionFactory, _packaging_attribute("packaging.version", "Version"))


@dataclass(frozen=True)
class RegularFile:
    path: Path
    content: bytes
    sha256: str


@dataclass(frozen=True)
class ConstraintPolicy:
    file: RegularFile
    pins: Mapping[str, str]


@dataclass(frozen=True)
class AuthoredRoot:
    name: str
    version: str
    extras: frozenset[str]
    scope: Scope
    sources: tuple[str, ...]


@dataclass(frozen=True)
class AuthoredPolicy:
    files: tuple[RegularFile, ...]
    roots: Mapping[str, AuthoredRoot]
    fingerprint: str


@dataclass(frozen=True)
class InstalledDistribution:
    name: str
    version: str
    requirements: tuple[RequirementProtocol, ...]
    provided_extras: frozenset[str]


@dataclass(frozen=True)
class InspectReport:
    pip_version: str
    environment: Mapping[str, str]
    installed: Mapping[str, InstalledDistribution]


@dataclass(frozen=True)
class DependencyGraph:
    scopes: Mapping[str, Scope]
    direct: frozenset[str]
    edges: Mapping[str, frozenset[str]]


def normalize_name(name: str) -> str:
    normalized = CANONICALIZE_NAME(name)
    if not normalized or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", normalized):
        raise SnapshotError("invalid-distribution-name", f"Invalid distribution name: {name!r}.")
    return normalized


def _canonical_version(
    version: str,
    *,
    label: str,
    invalid_code: str,
    noncanonical_code: str,
) -> str:
    try:
        canonical = str(VERSION(version))
    except Exception as error:
        raise SnapshotError(invalid_code, f"{label.capitalize()} has invalid version {version!r}.") from error
    if version != canonical:
        raise SnapshotError(
            noncanonical_code,
            f"{label.capitalize()} version {version!r} is not canonical PEP 440 spelling {canonical!r}.",
        )
    return canonical


def pin_fingerprint(pins: Mapping[str, str]) -> str:
    payload = "".join(f"{name}=={pins[name]}\n" for name in sorted(pins)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def read_regular_file(path: Path, maximum_bytes: int, *, label: str) -> RegularFile:
    """Read one bounded regular, non-symlink file while detecting path replacement."""

    try:
        before = path.lstat()
    except OSError as error:
        raise SnapshotError("input-unreadable", f"Cannot inspect {label} {path}: {error}.") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise SnapshotError("input-not-regular", f"{label.capitalize()} is not a regular non-symlink file: {path}.")
    if before.st_size > maximum_bytes:
        raise SnapshotError(
            "input-too-large",
            f"{label.capitalize()} exceeds the {maximum_bytes}-byte limit: {path}.",
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        after_open = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(after_open.st_mode)
            or _file_identity(before) != _file_identity(opened)
            or _file_identity(after_open) != _file_identity(opened)
        ):
            raise SnapshotError("input-changed", f"{label.capitalize()} changed while it was being opened: {path}.")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            content = handle.read(maximum_bytes + 1)
            final = os.fstat(handle.fileno())
        after_read = path.lstat()
    except SnapshotError:
        raise
    except OSError as error:
        raise SnapshotError("input-unreadable", f"Cannot safely read {label} {path}: {error}.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if len(content) > maximum_bytes:
        raise SnapshotError(
            "input-too-large",
            f"{label.capitalize()} exceeds the {maximum_bytes}-byte limit: {path}.",
        )
    if (
        stat.S_ISLNK(after_read.st_mode)
        or _file_identity(opened) != _file_identity(final)
        or _file_identity(final) != _file_identity(after_read)
        or len(content) != final.st_size
    ):
        raise SnapshotError("input-changed", f"{label.capitalize()} changed while it was being read: {path}.")
    return RegularFile(path=path, content=content, sha256=hashlib.sha256(content).hexdigest())


def _decode_utf8(source: RegularFile, *, label: str) -> str:
    try:
        return source.content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SnapshotError("input-not-utf8", f"{label.capitalize()} is not valid UTF-8: {source.path}.") from error


def _authored_source_fingerprint(source: RegularFile) -> str:
    """Hash authored text independent of the checkout's ASCII line endings."""

    text = _decode_utf8(source, label="authored requirements")
    canonical_text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def load_constraint(path: Path) -> ConstraintPolicy:
    source = read_regular_file(path, MAX_CONSTRAINT_BYTES, label="constraint")
    pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(_decode_utf8(source, label="constraint").splitlines(), start=1):
        if "\\" in raw_line:
            raise SnapshotError(
                "constraint-continuation-forbidden",
                f"Constraint line {line_number} uses a forbidden continuation.",
            )
        content_line = raw_line.split("#", 1)[0].strip()
        if not content_line:
            continue
        match = PIN_PATTERN.fullmatch(content_line)
        if match is None or "*" in content_line:
            raise SnapshotError(
                "constraint-non-exact-pin",
                f"Constraint line {line_number} is not one exact name==version pin.",
            )
        name = normalize_name(match.group("name"))
        version = match.group("version")
        _canonical_version(
            version,
            label=f"constraint line {line_number} for {name!r}",
            invalid_code="constraint-invalid-version",
            noncanonical_code="constraint-noncanonical-version",
        )
        if name in pins:
            raise SnapshotError(
                "constraint-duplicate-name",
                f"Constraint repeats normalized distribution name {name!r} on line {line_number}.",
            )
        pins[name] = version
    if not pins:
        raise SnapshotError("constraint-empty", f"Constraint contains no exact pins: {path}.")
    return ConstraintPolicy(file=source, pins=pins)


def marker_is_active(
    requirement: RequirementProtocol,
    environment: Mapping[str, str],
    extras: Sequence[str],
) -> bool:
    if requirement.marker is None:
        return True
    try:
        marker_text = str(requirement.marker)
        if not _marker_references_extra(requirement):
            return requirement.marker.evaluate(environment, context="metadata")

        # The dependency-specification standard gives the legacy ``extra``
        # variable set semantics: equality means membership in the complete
        # requested-extra set, and inequality means absence from that set.
        # Express that policy through packaging's public lock-file ``extras``
        # set marker rather than OR-ing independent scalar evaluations.
        extra_positions = set(_unquoted_identifier_positions(marker_text, "extra"))

        def replace_extra_comparison(match: re.Match[str]) -> str:
            variable_group = (
                "left_variable"
                if match.group("left_variable") is not None
                else "right_variable"
            )
            if match.start(variable_group) not in extra_positions:
                return match.group(0)
            left_value = match.group("left_value")
            right_value = match.group("right_value")
            value = left_value if left_value is not None else right_value
            if value is None:
                raise SnapshotError(
                    "marker-extra-comparison-invalid",
                    f"Unsupported extra comparison in marker {marker_text!r}.",
                )
            operator = match.group("left_operator") or match.group("right_operator")
            membership = "in" if operator == "==" else "not in"
            return f'{json.dumps(normalize_name(value))} {membership} extras'

        transformed = EXTRA_COMPARISON_PATTERN.sub(replace_extra_comparison, marker_text)
        if _unquoted_identifier_positions(transformed, "extra"):
            raise SnapshotError(
                "marker-extra-comparison-invalid",
                f"Only extra equality and inequality are supported in marker {marker_text!r}.",
            )
        selected_extras = frozenset(normalize_name(extra) for extra in extras)
        return MARKER(transformed).evaluate(
            {**environment, "extras": selected_extras},
            context="lock_file",
        )
    except Exception as error:
        if isinstance(error, SnapshotError):
            raise
        raise SnapshotError(
            "marker-evaluation-failed",
            f"Cannot safely evaluate dependency marker {requirement.marker!s} for {requirement.name!r}.",
        ) from error


def _marker_references_extra(requirement: RequirementProtocol) -> bool:
    if requirement.marker is None:
        return False
    marker_text = str(requirement.marker)
    return bool(_unquoted_identifier_positions(marker_text, "extra"))


def _has_negative_extra_comparison(requirement: RequirementProtocol) -> bool:
    if requirement.marker is None:
        return False
    marker_text = str(requirement.marker)
    for position in _unquoted_identifier_positions(marker_text, "extra"):
        before = marker_text[:position].rstrip()
        after = marker_text[position + len("extra") :].lstrip()
        if before.endswith("!=") or after.startswith("!="):
            return True
    return False


def _unquoted_identifier_positions(text: str, identifier: str) -> tuple[int, ...]:
    """Return exact identifier starts outside quoted marker string constants."""

    positions: list[int] = []
    quote_character: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote_character is not None:
            if character == "\\" and index + 1 < len(text):
                index += 2
                continue
            if character == quote_character:
                quote_character = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote_character = character
            index += 1
            continue
        if text.startswith(identifier, index):
            before = text[index - 1] if index else ""
            after_index = index + len(identifier)
            after = text[after_index] if after_index < len(text) else ""
            if not (before.isascii() and (before.isalnum() or before == "_")) and not (
                after.isascii() and (after.isalnum() or after == "_")
            ):
                positions.append(index)
                index = after_index
                continue
        index += 1
    return tuple(positions)


def parse_source_requirements(source: RegularFile) -> list[RequirementProtocol]:
    text = _decode_utf8(source, label="authored requirements")
    requirements: list[RequirementProtocol] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\\" in raw_line:
            raise SnapshotError(
                "source-continuation-forbidden",
                f"Authored requirements line {line_number} in {source.path} uses a forbidden continuation.",
            )
        if "#" in stripped:
            raise SnapshotError(
                "source-inline-comment-forbidden",
                f"Authored requirements line {line_number} in {source.path} uses an ambiguous inline comment.",
            )
        try:
            requirement = REQUIREMENT(stripped)
        except Exception as error:
            raise SnapshotError(
                "source-invalid-requirement",
                f"Authored requirements line {line_number} in {source.path} is invalid.",
            ) from error
        name = normalize_name(requirement.name)
        if _marker_references_extra(requirement):
            raise SnapshotError(
                "source-extra-marker-forbidden",
                f"Authored root {name!r} uses extra outside package dependency metadata.",
            )
        if requirement.url is not None:
            raise SnapshotError(
                "source-direct-url-forbidden",
                f"Authored root {name!r} must not use a direct URL.",
            )
        specifiers = tuple(requirement.specifier)
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise SnapshotError(
                "source-non-exact-pin",
                f"Authored root {name!r} must use one exact name==version pin.",
            )
        _canonical_version(
            specifiers[0].version,
            label=f"authored root {name!r}",
            invalid_code="source-invalid-version",
            noncanonical_code="source-noncanonical-version",
        )
        requirements.append(requirement)
    if not requirements:
        raise SnapshotError("source-empty", f"Authored requirements file contains no exact roots: {source.path}.")
    return requirements


def load_authored_policy(
    environment: Mapping[str, str],
    source_policies: Sequence[tuple[Path, Scope]] = SOURCE_POLICIES,
) -> AuthoredPolicy:
    files: list[RegularFile] = []
    merged: dict[str, AuthoredRoot] = {}
    for source_path, scope in source_policies:
        source = read_regular_file(source_path, MAX_REQUIREMENTS_BYTES, label="authored requirements")
        files.append(source)
        parsed = parse_source_requirements(source)
        if source_path.name == "requirements-bootstrap.txt":
            bootstrap_names = tuple(normalize_name(requirement.name) for requirement in parsed)
            if bootstrap_names != ("pip", "pip-tools"):
                raise SnapshotError(
                    "bootstrap-source-invalid",
                    "requirements-bootstrap.txt must contain exactly pip followed by pip-tools.",
                )
        for requirement in parsed:
            if not marker_is_active(requirement, environment, ()):
                continue
            name = normalize_name(requirement.name)
            version = tuple(requirement.specifier)[0].version
            extras = frozenset(normalize_name(extra) for extra in requirement.extras)
            previous = merged.get(name)
            if previous is None:
                merged[name] = AuthoredRoot(
                    name=name,
                    version=version,
                    extras=extras,
                    scope=scope,
                    sources=(source.path.as_posix(),),
                )
                continue
            if previous.version != version:
                raise SnapshotError(
                    "source-pin-conflict",
                    f"Authored roots disagree on the exact version for {name!r}.",
                )
            merged[name] = AuthoredRoot(
                name=name,
                version=version,
                extras=previous.extras | extras,
                scope="runtime" if "runtime" in (previous.scope, scope) else "development",
                sources=tuple(sorted({*previous.sources, source.path.as_posix()})),
            )

    if not merged:
        raise SnapshotError("source-empty", "The authored dependency policy has no active roots.")
    digest = hashlib.sha256()
    for source in files:
        digest.update(source.path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_authored_source_fingerprint(source).encode("ascii"))
        digest.update(b"\n")
    return AuthoredPolicy(files=tuple(files), roots=merged, fingerprint=digest.hexdigest())


def _duplicate_checked_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Non-finite JSON number: {value}.")


def parse_json_bytes(content: bytes, *, label: str) -> object:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SnapshotError("json-not-utf8", f"{label.capitalize()} is not valid UTF-8.") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_reject_json_constant,
        )
    except (DuplicateJsonKeyError, json.JSONDecodeError, ValueError) as error:
        raise SnapshotError("invalid-json", f"{label.capitalize()} is not strict JSON: {error}.") from error


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SnapshotError("invalid-schema", f"{label.capitalize()} must be a JSON object with string keys.")
    untyped_mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in untyped_mapping):
        raise SnapshotError("invalid-schema", f"{label.capitalize()} must be a JSON object with string keys.")
    return cast(Mapping[str, object], untyped_mapping)


def _array(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise SnapshotError("invalid-schema", f"{label.capitalize()} must be a JSON array.")
    return cast(list[object], value)


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SnapshotError("invalid-schema", f"{label.capitalize()} must be a nonempty trimmed string.")
    return value


def _string_mapping(value: object, *, label: str) -> Mapping[str, str]:
    source = _mapping(value, label=label)
    result: dict[str, str] = {}
    for key, raw_value in source.items():
        result[key] = _string(raw_value, label=f"{label}.{key}")
    return result


def parse_inspect_report(value: object) -> InspectReport:
    report = _mapping(value, label="pip inspect report")
    if report.get("version") != PIP_INSPECT_SCHEMA_VERSION:
        raise SnapshotError(
            "inspect-schema-mismatch",
            f"pip inspect schema must be exactly {PIP_INSPECT_SCHEMA_VERSION!r}.",
        )
    pip_version = _string(report.get("pip_version"), label="pip inspect pip_version")
    environment = _string_mapping(report.get("environment"), label="pip inspect environment")
    missing_environment = sorted(set(MARKER_ENVIRONMENT_KEYS) - set(environment))
    if missing_environment:
        raise SnapshotError(
            "inspect-environment-incomplete",
            f"pip inspect environment is missing marker fields: {', '.join(missing_environment)}.",
        )

    installed: dict[str, InstalledDistribution] = {}
    for index, raw_item in enumerate(_array(report.get("installed"), label="pip inspect installed")):
        item = _mapping(raw_item, label=f"pip inspect installed[{index}]")
        metadata = _mapping(item.get("metadata"), label=f"pip inspect installed[{index}].metadata")
        name = normalize_name(_string(metadata.get("name"), label=f"pip inspect installed[{index}].metadata.name"))
        version = _string(metadata.get("version"), label=f"pip inspect installed[{index}].metadata.version")
        _canonical_version(
            version,
            label=f"installed distribution {name!r}",
            invalid_code="inspect-invalid-version",
            noncanonical_code="inspect-noncanonical-version",
        )
        if name in installed:
            raise SnapshotError("inspect-duplicate-name", f"pip inspect repeats installed distribution {name!r}.")
        if item.get("installer") != "pip":
            raise SnapshotError("inspect-installer-mismatch", f"Installed {name!r} was not recorded as installed by pip.")
        if item.get("direct_url") is not None:
            raise SnapshotError("inspect-direct-url-forbidden", f"Installed {name!r} used a direct URL.")
        _string(item.get("metadata_location"), label=f"pip inspect installed[{index}].metadata_location")
        requested = item.get("requested")
        if requested is not None and not isinstance(requested, bool):
            raise SnapshotError("invalid-schema", f"pip inspect requested flag for {name!r} must be boolean.")

        requirements: list[RequirementProtocol] = []
        raw_requirements = metadata.get("requires_dist", [])
        for requirement_index, raw_requirement in enumerate(
            _array(raw_requirements, label=f"pip inspect requirements for {name}")
        ):
            requirement_text = _string(
                raw_requirement,
                label=f"pip inspect requirement {requirement_index} for {name}",
            )
            try:
                requirement = REQUIREMENT(requirement_text)
            except Exception as error:
                raise SnapshotError(
                    "inspect-invalid-requirement",
                    f"Installed {name!r} has invalid dependency metadata.",
                ) from error
            if requirement.url is not None:
                raise SnapshotError(
                    "inspect-direct-url-forbidden",
                    f"Installed {name!r} declares a direct-URL dependency.",
                )
            requirements.append(requirement)

        raw_extras = metadata.get("provides_extra", [])
        provided_extras: set[str] = set()
        for raw_extra in _array(raw_extras, label=f"pip inspect provided extras for {name}"):
            extra = normalize_name(_string(raw_extra, label=f"pip inspect provided extra for {name}"))
            if extra in provided_extras:
                raise SnapshotError("inspect-duplicate-extra", f"Installed {name!r} repeats provided extra {extra!r}.")
            provided_extras.add(extra)

        installed[name] = InstalledDistribution(
            name=name,
            version=version,
            requirements=tuple(requirements),
            provided_extras=frozenset(provided_extras),
        )
    if not installed:
        raise SnapshotError("inspect-empty", "pip inspect reported no installed distributions.")
    return InspectReport(pip_version=pip_version, environment=environment, installed=installed)


def _pins_from_list(value: object, *, label: str) -> Mapping[str, str]:
    pins: dict[str, str] = {}
    for index, raw_pin in enumerate(_array(value, label=label)):
        pin = _mapping(raw_pin, label=f"{label}[{index}]")
        if set(pin) != {"name", "version"}:
            raise SnapshotError("invalid-schema", f"{label}[{index}] must contain only name and version.")
        name = normalize_name(_string(pin.get("name"), label=f"{label}[{index}].name"))
        version = _string(pin.get("version"), label=f"{label}[{index}].version")
        if name in pins:
            raise SnapshotError("receipt-duplicate-name", f"{label} repeats distribution {name!r}.")
        pins[name] = version
    return pins


def _sha256(value: object, *, label: str) -> str:
    digest = _string(value, label=label)
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise SnapshotError("invalid-schema", f"{label.capitalize()} must be one lowercase SHA-256 digest.")
    return digest


def _bootstrap_source_pins(authored: AuthoredPolicy) -> Mapping[str, str]:
    source = next((file for file in authored.files if file.path.name == "requirements-bootstrap.txt"), None)
    if source is None:
        raise SnapshotError("bootstrap-source-invalid", "The canonical bootstrap source was not loaded.")
    parsed = parse_source_requirements(source)
    if tuple(normalize_name(requirement.name) for requirement in parsed) != ("pip", "pip-tools"):
        raise SnapshotError("bootstrap-source-invalid", "The bootstrap source does not contain the exact reviewed pair.")
    return {normalize_name(requirement.name): tuple(requirement.specifier)[0].version for requirement in parsed}


def verify_receipt(
    value: object,
    *,
    receipt_file: RegularFile,
    constraint: ConstraintPolicy,
    authored: AuthoredPolicy,
    inspect: InspectReport,
    platform_label: str,
) -> None:
    receipt = _mapping(value, label="verification receipt")
    if type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise SnapshotError("receipt-schema-mismatch", f"Verification receipt schema must be {RECEIPT_SCHEMA_VERSION}.")
    if receipt.get("status") != "verified" or receipt.get("mode") != "complete" or receipt.get("errors") != []:
        raise SnapshotError("receipt-not-complete", "Verification receipt must be a successful complete-mode receipt.")

    constraint_json = _mapping(receipt.get("constraint"), label="verification receipt constraint")
    if constraint_json.get("path") != str(constraint.file.path):
        raise SnapshotError("receipt-constraint-path-mismatch", "Verification receipt is bound to another constraint path.")
    if _sha256(constraint_json.get("sha256"), label="receipt constraint sha256") != constraint.file.sha256:
        raise SnapshotError("receipt-constraint-sha-mismatch", "Verification receipt constraint SHA-256 does not match.")
    if _sha256(constraint_json.get("fingerprint"), label="receipt constraint fingerprint") != pin_fingerprint(
        constraint.pins
    ):
        raise SnapshotError("receipt-constraint-fingerprint-mismatch", "Verification receipt pin fingerprint does not match.")
    receipt_constraint_pins = _pins_from_list(constraint_json.get("pins"), label="receipt constraint pins")
    if receipt_constraint_pins != constraint.pins:
        raise SnapshotError("receipt-constraint-pins-mismatch", "Verification receipt pins do not match the exact lock.")

    observation = _mapping(receipt.get("observation"), label="verification receipt observation")
    if observation.get("pip_inspect_schema") != PIP_INSPECT_SCHEMA_VERSION:
        raise SnapshotError("receipt-inspect-schema-mismatch", "Verification receipt used another pip inspect schema.")
    observed_pins = _pins_from_list(observation.get("installed"), label="receipt installed pins")
    inspected_pins = {name: distribution.version for name, distribution in inspect.installed.items()}
    if observed_pins != inspected_pins:
        raise SnapshotError("receipt-installed-mismatch", "Installed distributions changed after environment verification.")
    if _sha256(observation.get("installed_fingerprint"), label="receipt installed fingerprint") != pin_fingerprint(
        inspected_pins
    ):
        raise SnapshotError("receipt-installed-fingerprint-mismatch", "Verification receipt installed fingerprint does not match.")

    expected_environment = _string_mapping(
        receipt.get("expected_environment"), label="verification receipt expected environment"
    )
    observed_environment = _string_mapping(
        observation.get("environment"), label="verification receipt observed environment"
    )
    for key in RECEIPT_ENVIRONMENT_KEYS:
        if observed_environment.get(key) != inspect.environment.get(key):
            raise SnapshotError("receipt-environment-mismatch", f"Verification receipt environment field {key!r} changed.")
    expected_projection = {
        "implementation_name": inspect.environment["implementation_name"],
        "pip_version": inspect.pip_version,
        "platform_machine": inspect.environment["platform_machine"],
        "python_full_version": inspect.environment["python_full_version"],
        "python_version": inspect.environment["python_version"],
        "sys_platform": inspect.environment["sys_platform"],
    }
    if expected_environment != expected_projection:
        raise SnapshotError("receipt-environment-mismatch", "Verification receipt expected tuple does not match pip inspect.")
    if observation.get("pip_version") != inspect.pip_version:
        raise SnapshotError("receipt-pip-mismatch", "Verification receipt pip version changed after verification.")

    (
        sys_platform,
        os_name,
        platform_system,
        platform_machine,
        python_full_version,
        _,
    ) = PLATFORM_POLICIES[platform_label]
    platform_projection = {
        "sys_platform": sys_platform,
        "os_name": os_name,
        "platform_system": platform_system,
        "platform_machine": platform_machine,
        "python_full_version": python_full_version,
        "python_version": python_full_version.rpartition(".")[0],
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    }
    for key, expected in platform_projection.items():
        if inspect.environment.get(key) != expected:
            raise SnapshotError(
                "platform-tuple-mismatch",
                f"Selected platform {platform_label!r} disagrees with environment field {key!r}.",
            )
    if inspect.pip_version != constraint.pins.get("pip"):
        raise SnapshotError("pip-lock-mismatch", "pip inspect and the exact lock disagree on pip.")

    bootstrap = _mapping(receipt.get("bootstrap"), label="verification receipt bootstrap")
    policy = bootstrap.get("policy")
    state = bootstrap.get("state")
    if policy != "stable" or state != "stable":
        raise SnapshotError(
            "receipt-bootstrap-invalid",
            "Dependency snapshots require a stable bootstrap receipt bound to the selected lock.",
        )
    source_json = _mapping(bootstrap.get("source"), label="verification receipt bootstrap source")
    bootstrap_file = next(file for file in authored.files if file.path.name == "requirements-bootstrap.txt")
    if source_json.get("path") != str(bootstrap_file.path):
        raise SnapshotError("receipt-bootstrap-mismatch", "Verification receipt is bound to another bootstrap source.")
    if _sha256(source_json.get("sha256"), label="receipt bootstrap source sha256") != bootstrap_file.sha256:
        raise SnapshotError("receipt-bootstrap-mismatch", "Verification receipt bootstrap SHA-256 does not match.")
    bootstrap_pins = _bootstrap_source_pins(authored)
    receipt_bootstrap_pins = _string_mapping(source_json.get("pins"), label="receipt bootstrap source pins")
    if receipt_bootstrap_pins != bootstrap_pins:
        raise SnapshotError("receipt-bootstrap-mismatch", "Verification receipt bootstrap pins do not match.")
    if _sha256(source_json.get("pin_fingerprint"), label="receipt bootstrap fingerprint") != pin_fingerprint(
        bootstrap_pins
    ):
        raise SnapshotError("receipt-bootstrap-mismatch", "Verification receipt bootstrap fingerprint does not match.")
    if any(constraint.pins.get(name) != version for name, version in bootstrap_pins.items()):
        raise SnapshotError("bootstrap-lock-mismatch", "Bootstrap source and selected exact lock disagree.")

    transition = _mapping(bootstrap.get("source_transition"), label="verification receipt source transition")
    active = transition.get("active")
    if active is not False:
        raise SnapshotError("receipt-bootstrap-invalid", "Verification receipt source-transition flag is inconsistent.")
    transition_from = _string_mapping(transition.get("from"), label="verification receipt transition from")
    transition_to = _string_mapping(transition.get("to"), label="verification receipt transition to")
    if transition_to != bootstrap_pins:
        raise SnapshotError("receipt-bootstrap-invalid", "Verification receipt transition target is not the authored pair.")
    constraint_entries = _array(bootstrap.get("constraints"), label="verification receipt bootstrap constraints")
    if len(constraint_entries) != 1:
        raise SnapshotError("receipt-bootstrap-invalid", "Stable verification receipt must bind one selected constraint.")
    entry = _mapping(constraint_entries[0], label="verification receipt bootstrap constraint[0]")
    if entry.get("path") != str(constraint.file.path):
        raise SnapshotError("receipt-bootstrap-invalid", "Bootstrap receipt is bound to another selected constraint.")
    if _sha256(entry.get("sha256"), label="verification receipt bootstrap constraint[0].sha256") != constraint.file.sha256:
        raise SnapshotError("receipt-bootstrap-invalid", "Bootstrap receipt selected-constraint SHA-256 does not match.")
    if _sha256(
        entry.get("pin_fingerprint"),
        label="verification receipt bootstrap constraint[0].pin_fingerprint",
    ) != pin_fingerprint(constraint.pins):
        raise SnapshotError("receipt-bootstrap-invalid", "Bootstrap receipt selected-constraint pins do not match.")
    projected_pair = _string_mapping(
        entry.get("bootstrap_pins"),
        label="verification receipt bootstrap constraint[0].bootstrap_pins",
    )
    if transition_from != projected_pair or transition_from != bootstrap_pins:
        raise SnapshotError("receipt-bootstrap-invalid", "Stable bootstrap receipt does not bind the authored pair.")

    pip_inspect_command = _mapping(observation.get("pip_inspect"), label="verification receipt pip inspect command")
    pip_check_command = _mapping(observation.get("pip_check"), label="verification receipt pip check command")
    inspect_returncode = pip_inspect_command.get("returncode")
    check_returncode = pip_check_command.get("returncode")
    if (
        type(inspect_returncode) is not int
        or inspect_returncode != 0
        or type(check_returncode) is not int
        or check_returncode != 0
    ):
        raise SnapshotError("receipt-command-failed", "Verification receipt did not record successful pip checks.")
    if not SHA256_PATTERN.fullmatch(receipt_file.sha256):
        raise SnapshotError("receipt-sha-invalid", "Verification receipt SHA-256 could not be bound.")


def verify_exact_sets(
    constraint: ConstraintPolicy,
    authored: AuthoredPolicy,
    inspect: InspectReport,
) -> None:
    installed_pins = {name: distribution.version for name, distribution in inspect.installed.items()}
    if installed_pins != constraint.pins:
        missing = sorted(set(constraint.pins) - set(installed_pins))
        unexpected = sorted(set(installed_pins) - set(constraint.pins))
        changed = sorted(
            name
            for name in set(installed_pins) & set(constraint.pins)
            if installed_pins[name] != constraint.pins[name]
        )
        raise SnapshotError(
            "lock-installed-mismatch",
            "Exact lock and installed environment differ: "
            f"missing={missing!r}, unexpected={unexpected!r}, changed={changed!r}.",
        )
    for root in authored.roots.values():
        if constraint.pins.get(root.name) != root.version:
            raise SnapshotError(
                "source-lock-mismatch",
                f"Authored root {root.name!r} does not match the exact lock and installed environment.",
            )


def _validate_requested_extras(distribution: InstalledDistribution, extras: set[str]) -> None:
    missing = sorted(extras - set(distribution.provided_extras))
    if missing:
        raise SnapshotError(
            "missing-requested-extra",
            f"Installed {distribution.name!r} does not provide requested extras: {', '.join(missing)}.",
        )


def _active_requirement_targets(
    distribution: InstalledDistribution,
    inspect: InspectReport,
    extras: set[str],
) -> Iterator[tuple[RequirementProtocol, str, frozenset[str]]]:
    for requirement in distribution.requirements:
        if not marker_is_active(requirement, inspect.environment, tuple(extras)):
            continue
        child_name = normalize_name(requirement.name)
        dependency_extras = frozenset(normalize_name(extra) for extra in requirement.extras)
        yield requirement, child_name, dependency_extras


def _active_dependencies(
    distribution: InstalledDistribution,
    inspect: InspectReport,
    extras: set[str],
) -> Iterator[tuple[str, frozenset[str]]]:
    _validate_requested_extras(distribution, extras)
    for requirement, child_name, dependency_extras in _active_requirement_targets(
        distribution,
        inspect,
        extras,
    ):
        child = inspect.installed.get(child_name)
        if child is None:
            raise SnapshotError(
                "active-dependency-missing",
                f"Installed {distribution.name!r} has active dependency {child_name!r}, which is absent.",
            )
        if requirement.specifier and not requirement.specifier.contains(child.version, prereleases=True):
            raise SnapshotError(
                "active-dependency-version-mismatch",
                f"Installed {child_name!r} does not satisfy metadata declared by {distribution.name!r}.",
            )
        yield child_name, dependency_extras


def _discover_selected_extras(
    authored: AuthoredPolicy,
    inspect: InspectReport,
) -> Mapping[str, frozenset[str]]:
    """Close requested extras monotonically before deriving final graph edges."""

    selected_extras: dict[str, set[str]] = {}
    queue: deque[str] = deque()
    queued: set[str] = set()

    def schedule(name: str) -> None:
        if name not in queued:
            queue.append(name)
            queued.add(name)

    for root in authored.roots.values():
        if root.name not in inspect.installed:
            raise SnapshotError("root-not-installed", f"Authored root {root.name!r} is not installed.")
        first_visit = root.name not in selected_extras
        extras = selected_extras.setdefault(root.name, set())
        changed = not root.extras.issubset(extras)
        extras.update(root.extras)
        if first_visit or changed:
            schedule(root.name)

    while queue:
        name = queue.popleft()
        queued.remove(name)
        distribution = inspect.installed[name]
        extras = selected_extras.setdefault(name, set())
        for _requirement, child_name, dependency_extras in _active_requirement_targets(
            distribution,
            inspect,
            extras,
        ):
            if child_name not in inspect.installed:
                # Dependency validity is reported by the fresh graph pass; the
                # closure phase only propagates extras through installed nodes.
                continue
            first_visit = child_name not in selected_extras
            child_extras = selected_extras.setdefault(child_name, set())
            changed = not dependency_extras.issubset(child_extras)
            child_extras.update(dependency_extras)
            if first_visit or changed:
                schedule(child_name)

    return {name: frozenset(extras) for name, extras in selected_extras.items()}


def _validate_dependency_marker_policy(inspect: InspectReport) -> None:
    for name in sorted(inspect.installed):
        distribution = inspect.installed[name]
        for requirement in distribution.requirements:
            if _has_negative_extra_comparison(requirement):
                raise SnapshotError(
                    "negative-extra-marker-unsupported",
                    f"Installed {distribution.name!r} declares non-monotonic negative "
                    f"extra marker {str(requirement.marker)!r}; snapshot graph construction "
                    "supports only positive equality for extra comparisons.",
                )


def build_dependency_graph(authored: AuthoredPolicy, inspect: InspectReport) -> DependencyGraph:
    _validate_dependency_marker_policy(inspect)
    selected_extras = _discover_selected_extras(authored, inspect)
    scopes: dict[str, Scope] = {}
    queue: deque[str] = deque()
    queued: set[str] = set()

    def schedule(name: str) -> None:
        if name not in queued:
            queue.append(name)
            queued.add(name)

    for root in authored.roots.values():
        previous_scope = scopes.get(root.name)
        if previous_scope is None or root.scope == "runtime":
            scopes[root.name] = root.scope
            schedule(root.name)

    edges: dict[str, set[str]] = {name: set() for name in inspect.installed}
    while queue:
        name = queue.popleft()
        queued.remove(name)
        distribution = inspect.installed[name]
        extras = set(selected_extras.get(name, frozenset()))
        parent_scope = scopes[name]
        for child_name, dependency_extras in _active_dependencies(distribution, inspect, extras):
            closed_child_extras = selected_extras.get(child_name)
            if closed_child_extras is None or not dependency_extras.issubset(closed_child_extras):
                raise SnapshotError(
                    "requested-extra-closure-incomplete",
                    f"Requested extras for installed dependency {child_name!r} were not closed.",
                )
            if child_name == name:
                # Self-referential extras are aliases that request more extras
                # from this distribution, not a package depending on itself.
                continue
            edges[name].add(child_name)
            previous_scope = scopes.get(child_name)
            next_scope: Scope = "runtime" if parent_scope == "runtime" else "development"
            if previous_scope is None or (previous_scope == "development" and next_scope == "runtime"):
                scopes[child_name] = next_scope
                schedule(child_name)

    unreachable = sorted(set(inspect.installed) - set(scopes))
    if unreachable:
        raise SnapshotError(
            "unreachable-locked-dependency",
            f"Exact locked distributions are unreachable from authored roots: {', '.join(unreachable)}.",
        )
    return DependencyGraph(
        scopes=scopes,
        direct=frozenset(authored.roots),
        edges={name: frozenset(children) for name, children in edges.items()},
    )


def package_url(name: str, version: str) -> str:
    canonical_name = normalize_name(name)
    canonical_version = _canonical_version(
        version,
        label=f"PyPI package {canonical_name!r}",
        invalid_code="purl-invalid-version",
        noncanonical_code="purl-noncanonical-version",
    )
    return f"pkg:pypi/{quote(canonical_name, safe='-._~')}@{quote(canonical_version, safe='-._~')}"


def validate_scanned(value: str) -> str:
    if SCANNED_PATTERN.fullmatch(value) is None:
        raise SnapshotError("invalid-scanned-time", "Scanned time must be an exact UTC RFC 3339 second ending in Z.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise SnapshotError("invalid-scanned-time", "Scanned time is not a real UTC timestamp.") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SnapshotError("invalid-scanned-time", "Scanned time is not canonical UTC RFC 3339.")
    return value


def build_snapshot(
    *,
    constraint: ConstraintPolicy,
    receipt_file: RegularFile,
    authored: AuthoredPolicy,
    inspect: InspectReport,
    graph: DependencyGraph,
    platform_label: str,
    repository: str,
    sha: str,
    ref: str,
    run_id: str,
    run_attempt: str,
    scanned: str,
) -> dict[str, object]:
    _, _, _, _, _, manifest_path = PLATFORM_POLICIES[platform_label]
    purls = {name: package_url(name, distribution.version) for name, distribution in inspect.installed.items()}
    resolved: dict[str, object] = {}
    for name in sorted(inspect.installed):
        resolved[purls[name]] = {
            "package_url": purls[name],
            "relationship": "direct" if name in graph.direct else "indirect",
            "scope": graph.scopes[name],
            "dependencies": sorted(purls[child] for child in graph.edges[name]),
        }
    installed_pins = {name: distribution.version for name, distribution in inspect.installed.items()}
    return {
        "version": SNAPSHOT_VERSION,
        "sha": sha,
        "ref": ref,
        "job": {
            "id": f"{run_id}.{run_attempt}.{platform_label}",
            "correlator": f"gm2godot-dependency-locks-{platform_label}",
            "html_url": f"https://github.com/{repository}/actions/runs/{run_id}",
        },
        "detector": {
            "name": DETECTOR_NAME,
            "version": DETECTOR_VERSION,
            "url": f"https://github.com/{repository}/blob/{sha}/{DETECTOR_SOURCE_PATH}",
        },
        "metadata": {
            "platform": platform_label,
            "constraint_sha256": constraint.file.sha256,
            "constraint_fingerprint": pin_fingerprint(constraint.pins),
            "installed_fingerprint": pin_fingerprint(installed_pins),
            "source_fingerprint": authored.fingerprint,
            "verification_receipt_sha256": receipt_file.sha256,
            "python_full_version": inspect.environment["python_full_version"],
            "pip_version": inspect.pip_version,
        },
        "scanned": scanned,
        "manifests": {
            manifest_path: {
                "name": manifest_path,
                "file": {"source_location": manifest_path},
                "resolved": resolved,
            }
        },
    }


def isolated_pip_environment(source: Mapping[str, str]) -> dict[str, str]:
    environment = {
        name: value
        for name, value in source.items()
        if not name.upper().startswith(("PIP_", "PYTHON"))
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def pip_inspect_command() -> list[str]:
    return [
        sys.executable,
        "-X",
        "utf8",
        "-I",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "--no-color",
        "inspect",
        "--local",
    ]


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def _read_bounded(stream: IO[bytes], maximum_bytes: int, *, label: str) -> bytes:
    stream.seek(0)
    content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise SnapshotError("inspect-output-too-large", f"{label.capitalize()} exceeded the {maximum_bytes}-byte limit.")
    return content


def run_pip_inspect() -> object:
    process: subprocess.Popen[bytes] | None = None
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
            process = subprocess.Popen(
                pip_inspect_command(),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=isolated_pip_environment(os.environ),
                close_fds=True,
                shell=False,
            )
            deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
            while process.poll() is None:
                if os.fstat(stdout_file.fileno()).st_size > MAX_INSPECT_BYTES:
                    _kill_and_reap(process)
                    raise SnapshotError("inspect-output-too-large", "pip inspect stdout exceeded the bounded limit.")
                if os.fstat(stderr_file.fileno()).st_size > MAX_COMMAND_STDERR_BYTES:
                    _kill_and_reap(process)
                    raise SnapshotError("inspect-output-too-large", "pip inspect stderr exceeded the bounded limit.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_and_reap(process)
                    raise SnapshotError("inspect-timeout", "pip inspect exceeded the bounded timeout.")
                try:
                    process.wait(timeout=min(COMMAND_OUTPUT_POLL_SECONDS, remaining))
                except subprocess.TimeoutExpired:
                    pass
            stdout = _read_bounded(stdout_file, MAX_INSPECT_BYTES, label="pip inspect stdout")
            stderr = _read_bounded(stderr_file, MAX_COMMAND_STDERR_BYTES, label="pip inspect stderr")
            if process.returncode != 0:
                message = stderr.decode("utf-8", errors="replace").strip()
                raise SnapshotError(
                    "inspect-failed",
                    f"pip inspect returned {process.returncode}: {message[:1000]}",
                )
            return parse_json_bytes(stdout, label="pip inspect output")
    except SnapshotError:
        raise
    except OSError as error:
        raise SnapshotError("inspect-execution-failed", f"Cannot safely execute pip inspect: {error}.") from error
    finally:
        if process is not None and process.poll() is None:
            _kill_and_reap(process)


def _normalized_path(path: Path) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))
    except (OSError, ValueError) as error:
        raise SnapshotError("path-invalid", f"Cannot safely normalize path {path}: {error}.") from error


def validate_checkout_path(path: Path, *, label: str, must_exist: bool) -> None:
    """Keep CLI-controlled reads and writes inside the physical checkout."""

    try:
        checkout = Path.cwd().resolve(strict=True)
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(checkout)
    except (OSError, ValueError) as error:
        raise SnapshotError(
            "path-outside-checkout",
            f"{label.capitalize()} must resolve inside the physical checkout: {path}.",
        ) from error
    if resolved == checkout:
        raise SnapshotError(
            "path-outside-checkout",
            f"{label.capitalize()} must name a file below the physical checkout: {path}.",
        )


def paths_alias(first: Path, second: Path) -> bool:
    if _normalized_path(first) == _normalized_path(second):
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise SnapshotError("path-invalid", f"Cannot safely compare input paths: {error}.") from error


def validate_distinct_inputs(inputs: Sequence[tuple[str, Path]]) -> None:
    for index, (first_label, first_path) in enumerate(inputs):
        for second_label, second_path in inputs[index + 1 :]:
            if paths_alias(first_path, second_path):
                raise SnapshotError(
                    "input-alias",
                    f"Trusted inputs {first_label} and {second_label} must refer to different files.",
                )


def validate_output_path(output: Path, inputs: Sequence[Path]) -> None:
    output_key = _normalized_path(output)
    if any(output_key == _normalized_path(path) for path in inputs):
        raise SnapshotError("output-alias", "Snapshot output must not alias any trusted input.")
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SnapshotError("output-invalid", f"Cannot inspect snapshot output {output}: {error}.") from error
    else:
        raise SnapshotError("output-exists", f"Refusing to overwrite existing snapshot output: {output}.")
    parent = output.parent
    try:
        parent_stat = parent.lstat()
    except OSError as error:
        raise SnapshotError("output-parent-invalid", f"Snapshot output parent must already exist: {parent}.") from error
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise SnapshotError("output-parent-invalid", f"Snapshot output parent is not a regular directory: {parent}.")


def atomic_write_new_json(path: Path, value: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError(
            "snapshot-too-large",
            f"Snapshot exceeds the {MAX_SNAPSHOT_BYTES}-byte limit.",
        )
    try:
        _PUBLISH_NEW_BYTES(path, payload)
    except _ANCHORED_OUTPUT_ERROR as error:
        translated = SnapshotError(
            cast(str, getattr(error, "code")),
            str(error),
        )
        for note in cast(list[str], getattr(error, "__notes__", [])):
            translated.add_note(note)
        raise translated from error


def _positive_decimal(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise SnapshotError("invalid-run-identity", f"{label.capitalize()} must be one positive canonical decimal.")
    return value


def validate_identity(
    *, repository: str, sha: str, ref: str, run_id: str, run_attempt: str
) -> tuple[str, str]:
    if REPOSITORY_PATTERN.fullmatch(repository) is None or repository.endswith(".git"):
        raise SnapshotError("invalid-repository", "Repository must be one canonical GitHub owner/name value.")
    if COMMIT_SHA_PATTERN.fullmatch(sha) is None:
        raise SnapshotError("invalid-commit-sha", "Commit SHA must be exactly 40 lowercase hexadecimal characters.")
    if REF_PATTERN.fullmatch(ref) is None or "//" in ref or ".." in ref:
        raise SnapshotError("invalid-ref", "Git ref must be one canonical refs/... value.")
    return _positive_decimal(run_id, label="run id"), _positive_decimal(run_attempt, label="run attempt")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraint", required=True)
    parser.add_argument("--verification-receipt", required=True)
    parser.add_argument("--platform", choices=tuple(PLATFORM_POLICIES), required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scanned", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    constraint_path = Path(cast(str, arguments.constraint))
    receipt_path = Path(cast(str, arguments.verification_receipt))
    output_path = Path(cast(str, arguments.output))
    platform_label = cast(str, arguments.platform)
    repository = cast(str, arguments.repository)
    sha = cast(str, arguments.sha)
    ref = cast(str, arguments.ref)
    raw_scanned = cast(str | None, arguments.scanned)
    try:
        run_id, run_attempt = validate_identity(
            repository=repository,
            sha=sha,
            ref=ref,
            run_id=cast(str, arguments.run_id),
            run_attempt=cast(str, arguments.run_attempt),
        )
        scanned = validate_scanned(
            raw_scanned
            if raw_scanned is not None
            else datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        source_paths = tuple(path for path, _ in SOURCE_POLICIES)
        for label, path in (
            ("constraint", constraint_path),
            ("verification receipt", receipt_path),
            *((f"authored source {index + 1}", path) for index, path in enumerate(source_paths)),
        ):
            validate_checkout_path(path, label=label, must_exist=True)
        validate_checkout_path(output_path, label="snapshot output", must_exist=False)
        validate_distinct_inputs(
            (
                ("constraint", constraint_path),
                ("verification receipt", receipt_path),
                *((f"authored source {index + 1}", path) for index, path in enumerate(source_paths)),
            )
        )
        validate_output_path(output_path, (constraint_path, receipt_path, *source_paths))
        constraint = load_constraint(constraint_path)
        receipt_file = read_regular_file(receipt_path, MAX_RECEIPT_BYTES, label="verification receipt")
        inspect = parse_inspect_report(run_pip_inspect())
        authored = load_authored_policy(inspect.environment)
        verify_exact_sets(constraint, authored, inspect)
        verify_receipt(
            parse_json_bytes(receipt_file.content, label="verification receipt"),
            receipt_file=receipt_file,
            constraint=constraint,
            authored=authored,
            inspect=inspect,
            platform_label=platform_label,
        )
        graph = build_dependency_graph(authored, inspect)
        snapshot = build_snapshot(
            constraint=constraint,
            receipt_file=receipt_file,
            authored=authored,
            inspect=inspect,
            graph=graph,
            platform_label=platform_label,
            repository=repository,
            sha=sha,
            ref=ref,
            run_id=run_id,
            run_attempt=run_attempt,
            scanned=scanned,
        )
        atomic_write_new_json(output_path, snapshot)
    except SnapshotError as error:
        print(f"Dependency snapshot failed [{error.code}]: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Dependency snapshot failed [filesystem-error]: {error}", file=sys.stderr)
        return 2
    print(f"Dependency submission snapshot written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
