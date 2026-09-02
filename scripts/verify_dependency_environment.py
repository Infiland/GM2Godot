#!/usr/bin/env python3
"""Verify that a Python environment is covered by an exact constraint policy."""

from __future__ import annotations

import argparse
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import IO, Literal, Never, cast


RECEIPT_SCHEMA_VERSION = 2
BOOTSTRAP_RECEIPT_SCHEMA_VERSION = 1
INSPECT_SCHEMA_VERSION = "1"
COMMAND_TIMEOUT_SECONDS = 30.0
COMMAND_OUTPUT_POLL_SECONDS = 0.05
MAX_CONSTRAINT_BYTES = 1024 * 1024
MAX_INSPECT_BYTES = 16 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
WINDOWS_STAT_INTERFACES_DIVERGE = os.name == "nt"
NAME_PATTERN = re.compile(
    r"(?:[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])\Z",
    re.ASCII | re.IGNORECASE,
)
PIN_PATTERN = re.compile(
    r"(?P<name>[A-Z0-9](?:[A-Z0-9._-]*[A-Z0-9])?)"
    r"\s*==\s*"
    r"(?P<version>[A-Z0-9][A-Z0-9.!+_-]*)\Z",
    re.ASCII | re.IGNORECASE,
)
BOOTSTRAP_PIN_PATTERN = re.compile(
    r"(?P<name>pip|pip-tools)==(?P<version>[A-Z0-9][A-Z0-9.!+_-]*)\Z",
    re.ASCII,
)
PYTHON_VERSION_PATTERN = re.compile(
    r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<micro>[0-9]+)"
    r"(?:(?:a|b|rc)[0-9]+)?\Z"
)
PLATFORM_EXPECTATIONS: Mapping[str, tuple[str, str]] = {
    "darwin": ("posix", "Darwin"),
    "linux": ("posix", "Linux"),
    "win32": ("nt", "Windows"),
}
BOOTSTRAP_NAMES = ("pip", "pip-tools")
BootstrapPolicyName = Literal["stable", "native-lock-workflow"]
BootstrapStateName = Literal["stable", "source-transition"]
NATIVE_CONSTRAINT_PATHS = (
    Path("constraints/requirements-linux-py312.lock"),
    Path("constraints/requirements-macos-py312.lock"),
    Path("constraints/requirements-windows-py312.lock"),
)


class PolicyError(ValueError):
    """A local policy or pip report did not satisfy the verifier schema."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DuplicateJsonKeyError(ValueError):
    """A JSON object repeated a key and was therefore ambiguous."""


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    message: str
    name: str = ""
    expected: str = ""
    observed: str = ""

    def as_json(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.name:
            result["name"] = self.name
        if self.expected:
            result["expected"] = self.expected
        if self.observed:
            result["observed"] = self.observed
        return result


@dataclass(frozen=True)
class ConstraintPolicy:
    path: Path
    sha256: str
    pins: Mapping[str, str]


@dataclass(frozen=True)
class BootstrapPair:
    pip: str
    pip_tools: str

    def as_pins(self) -> dict[str, str]:
        return {"pip": self.pip, "pip-tools": self.pip_tools}


@dataclass(frozen=True)
class BootstrapPolicy:
    path: Path
    sha256: str
    pair: BootstrapPair


@dataclass(frozen=True)
class BootstrapState:
    policy: BootstrapPolicyName
    state: BootstrapStateName
    source: BootstrapPolicy
    constraints: tuple[ConstraintPolicy, ...]
    current_pair: BootstrapPair
    proposed_pair: BootstrapPair


@dataclass(frozen=True)
class ExpectedEnvironment:
    python_full_version: str
    python_version: str
    sys_platform: str
    platform_machine: str
    pip_version: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    failure: Finding | None = None


@dataclass(frozen=True)
class InspectAnalysis:
    schema_version: str
    pip_version: str
    environment: Mapping[str, str]
    installed: Mapping[str, str]
    findings: tuple[Finding, ...]


def normalize_name(name: str) -> str:
    """Return the PyPA comparison form for a distribution name."""

    if NAME_PATTERN.fullmatch(name) is None:
        raise PolicyError("invalid-distribution-name", f"Invalid distribution name: {name!r}.")
    return re.sub(r"[-_.]+", "-", name).lower()


def _pin_bytes(pins: Mapping[str, str]) -> bytes:
    return "".join(f"{name}=={pins[name]}\n" for name in sorted(pins)).encode("utf-8")


def pin_fingerprint(pins: Mapping[str, str]) -> str:
    return hashlib.sha256(_pin_bytes(pins)).hexdigest()


def paths_alias(first: Path, second: Path) -> bool:
    """Return whether two paths resolve to the same destination or file."""

    try:
        resolved_first = first.resolve(strict=False)
        resolved_second = second.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise PolicyError("path-alias-check-failed", f"Cannot safely compare verifier paths: {error}.") from error
    if os.path.normcase(os.fspath(resolved_first)) == os.path.normcase(os.fspath(resolved_second)):
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False
    except (OSError, RuntimeError, ValueError) as error:
        raise PolicyError("path-alias-check-failed", f"Cannot safely compare verifier paths: {error}.") from error


def _path_is_physical(path: Path) -> bool:
    """Reject a symlink, junction, or non-directory in any policy ancestor."""

    try:
        # Do not collapse parent traversal before inspecting the path. The
        # filesystem resolves ``linked-directory/..`` after following the
        # link, which can reach a different parent than lexical normalization.
        if os.pardir in path.parts:
            return False
        absolute_path = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
        parent = absolute_path.parent
        directories = (*reversed(parent.parents), parent)
        for directory in directories:
            directory_stat = directory.lstat()
            is_junction = getattr(directory, "is_junction", None)
            if (
                stat.S_ISLNK(directory_stat.st_mode)
                or not stat.S_ISDIR(directory_stat.st_mode)
                or (is_junction is not None and cast(bool, is_junction()))
            ):
                return False
    except (OSError, RuntimeError, ValueError) as error:
        raise PolicyError(
            "path-binding-failed",
            f"Cannot bind policy path to one physical file {path}: {error}.",
        ) from error
    return True


def _stat_binding(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _cross_interface_stat_binding(file_stat: os.stat_result) -> tuple[int, ...]:
    """Return metadata that is comparable between path and descriptor stats."""

    if not WINDOWS_STAT_INTERFACES_DIVERGE:
        return _stat_binding(file_stat)
    # On CPython 3.12 for Windows, path stat calls expose the deprecated
    # creation-time meaning of st_ctime while fstat exposes metadata change
    # time. Path stats can also synthesize execute bits from the extension.
    # Descriptor-to-descriptor checks below retain the full metadata binding.
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        stat.S_IFMT(file_stat.st_mode),
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


@dataclass(frozen=True)
class _RegularFileRequest:
    label: str
    path: Path
    maximum_bytes: int
    bootstrap_source: bool = False


@dataclass(frozen=True)
class _BoundRegularFile:
    request: _RegularFileRequest
    descriptor: int
    opened_stat: os.stat_result


def _contextualize_file_error(
    request: _RegularFileRequest,
    error: PolicyError,
) -> PolicyError:
    if not request.bootstrap_source:
        return error
    return PolicyError(
        "bootstrap-source-invalid",
        "Bootstrap source is not one stable, physical regular file: "
        f"{request.path}: {error}",
    )


def _raise_contextual_file_error(
    request: _RegularFileRequest,
    error: PolicyError,
) -> Never:
    contextual_error = _contextualize_file_error(request, error)
    if contextual_error is error:
        raise error
    raise contextual_error from error


def _open_bound_regular_file(
    request: _RegularFileRequest,
) -> _BoundRegularFile:
    path = request.path
    try:
        path_stat_before = path.lstat()
    except (OSError, RuntimeError, ValueError) as error:
        policy_error = PolicyError(
            "constraint-unreadable",
            f"Cannot inspect constraint file {path}: {error}.",
        )
        _raise_contextual_file_error(request, policy_error)
    if stat.S_ISLNK(path_stat_before.st_mode) or not stat.S_ISREG(path_stat_before.st_mode):
        _raise_contextual_file_error(
            request,
            PolicyError(
                "constraint-not-regular",
                f"Constraint path is not a regular file: {path}.",
            ),
        )
    try:
        physical_path = _path_is_physical(path)
    except PolicyError as error:
        policy_error = PolicyError("constraint-unreadable", str(error))
        contextual_error = _contextualize_file_error(request, policy_error)
        raise contextual_error from error
    if not physical_path:
        _raise_contextual_file_error(
            request,
            PolicyError(
                "constraint-not-physical",
                f"Constraint path uses a symlink, junction, or redirected policy directory: {path}.",
            ),
        )
    if path_stat_before.st_size > request.maximum_bytes:
        _raise_contextual_file_error(
            request,
            PolicyError(
                "constraint-too-large",
                f"Constraint file exceeds the {request.maximum_bytes}-byte verifier limit: {path}.",
            ),
        )

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= cast(int, getattr(os, flag_name, 0))
    try:
        descriptor = os.open(path, flags)
    except (OSError, RuntimeError, ValueError) as error:
        policy_error = PolicyError(
            "constraint-unreadable",
            f"Cannot open constraint file {path}: {error}.",
        )
        contextual_error = _contextualize_file_error(request, policy_error)
        raise contextual_error from error
    primary_error: BaseException | None = None
    try:
        opened_stat_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat_before.st_mode)
            or not os.path.samestat(path_stat_before, opened_stat_before)
            or _cross_interface_stat_binding(path_stat_before)
            != _cross_interface_stat_binding(opened_stat_before)
        ):
            _raise_contextual_file_error(
                request,
                PolicyError(
                    "constraint-binding-changed",
                    f"Constraint path changed while it was being opened: {path}.",
                ),
            )
        if opened_stat_before.st_size > request.maximum_bytes:
            _raise_contextual_file_error(
                request,
                PolicyError(
                    "constraint-too-large",
                    f"Constraint file exceeds the {request.maximum_bytes}-byte verifier limit: {path}.",
                ),
            )
        return _BoundRegularFile(
            request=request,
            descriptor=descriptor,
            opened_stat=opened_stat_before,
        )
    except OSError as error:
        policy_error = PolicyError(
            "constraint-unreadable",
            f"Cannot bind constraint file {path}: {error}.",
        )
        primary_error = _contextualize_file_error(request, policy_error)
        raise primary_error from error
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if primary_error is not None:
            try:
                os.close(descriptor)
            except BaseException as cleanup_error:
                primary_error.add_note(
                    f"Could not close constraint descriptor: {cleanup_error}"
                )


def _verify_bound_regular_file(binding: _BoundRegularFile) -> None:
    request = binding.request
    path = request.path
    try:
        opened_stat_after = os.fstat(binding.descriptor)
        path_stat_after = path.lstat()
        physical_path_after = _path_is_physical(path)
    except (OSError, PolicyError, RuntimeError, ValueError) as error:
        policy_error = PolicyError(
            "constraint-binding-changed",
            f"Constraint path changed while it was being read: {path}: {error}.",
        )
        contextual_error = _contextualize_file_error(request, policy_error)
        raise contextual_error from error
    if (
        stat.S_ISLNK(path_stat_after.st_mode)
        or not stat.S_ISREG(path_stat_after.st_mode)
        or not physical_path_after
        or not os.path.samestat(opened_stat_after, path_stat_after)
        or _stat_binding(binding.opened_stat) != _stat_binding(opened_stat_after)
        or _cross_interface_stat_binding(opened_stat_after)
        != _cross_interface_stat_binding(path_stat_after)
    ):
        _raise_contextual_file_error(
            request,
            PolicyError(
                "constraint-binding-changed",
                f"Constraint path changed while it was being read: {path}.",
            ),
        )


def _read_bound_regular_file(binding: _BoundRegularFile) -> bytes:
    request = binding.request
    chunks: list[bytes] = []
    total_bytes = 0
    try:
        while total_bytes <= request.maximum_bytes:
            chunk = os.read(
                binding.descriptor,
                min(64 * 1024, request.maximum_bytes + 1 - total_bytes),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
    except OSError as error:
        policy_error = PolicyError(
            "constraint-unreadable",
            f"Cannot read constraint file {request.path}: {error}.",
        )
        contextual_error = _contextualize_file_error(request, policy_error)
        raise contextual_error from error
    if total_bytes > request.maximum_bytes:
        _raise_contextual_file_error(
            request,
            PolicyError(
                "constraint-too-large",
                f"Constraint file exceeds the {request.maximum_bytes}-byte verifier limit: "
                f"{request.path}.",
            ),
        )
    return b"".join(chunks)


def _reject_bound_file_aliases(bindings: Sequence[_BoundRegularFile]) -> None:
    for index, first in enumerate(bindings):
        for second in bindings[index + 1 :]:
            if os.path.samestat(first.opened_stat, second.opened_stat):
                raise PolicyError(
                    "bootstrap-path-alias",
                    f"Bootstrap policy paths {first.request.label} and "
                    f"{second.request.label} must refer to different files.",
                )


@contextmanager
def _bound_regular_files(
    requests: Sequence[_RegularFileRequest],
) -> Generator[tuple[bytes, ...]]:
    bindings: list[_BoundRegularFile] = []
    primary_error: BaseException | None = None
    try:
        for request in requests:
            binding = _open_bound_regular_file(request)
            try:
                bindings.append(binding)
            except BaseException as error:
                try:
                    os.close(binding.descriptor)
                except BaseException as cleanup_error:
                    error.add_note(
                        "Could not close an untracked constraint descriptor: "
                        f"{cleanup_error}"
                    )
                raise
        _reject_bound_file_aliases(bindings)
        for binding in bindings:
            _verify_bound_regular_file(binding)
        contents = tuple(_read_bound_regular_file(binding) for binding in bindings)
        for binding in bindings:
            _verify_bound_regular_file(binding)
        yield contents
        for binding in bindings:
            _verify_bound_regular_file(binding)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors: list[tuple[Path, BaseException]] = []
        for binding in reversed(bindings):
            try:
                os.close(binding.descriptor)
            except BaseException as cleanup_error:
                cleanup_errors.append((binding.request.path, cleanup_error))
        if primary_error is not None:
            for path, cleanup_error in cleanup_errors:
                primary_error.add_note(
                    f"Could not close constraint descriptor: {cleanup_error} "
                    f"(path: {path})"
                )
        elif cleanup_errors:
            for index, (path, cleanup_error) in enumerate(cleanup_errors):
                if isinstance(cleanup_error, Exception):
                    continue
                for other_index, (other_path, other_error) in enumerate(
                    cleanup_errors
                ):
                    if other_index != index:
                        cleanup_error.add_note(
                            "Could not close constraint descriptor: "
                            f"{other_error} (path: {other_path})"
                        )
                cleanup_error.add_note(
                    f"Constraint descriptor close failed for {path}."
                )
                raise cleanup_error
            first_path, first_cleanup_error = cleanup_errors[0]
            if isinstance(first_cleanup_error, OSError):
                cleanup_policy_error = PolicyError(
                    "constraint-unreadable",
                    "Cannot close constraint descriptor after a successful read: "
                    f"{first_path}: {first_cleanup_error}.",
                )
                for path, cleanup_error in cleanup_errors[1:]:
                    cleanup_policy_error.add_note(
                        f"Could not close constraint descriptor for {path}: {cleanup_error}"
                    )
                raise cleanup_policy_error from first_cleanup_error
            for path, cleanup_error in cleanup_errors[1:]:
                first_cleanup_error.add_note(
                    f"Could not close constraint descriptor for {path}: {cleanup_error}"
                )
            raise first_cleanup_error


def _read_regular_file(path: Path, maximum_bytes: int) -> bytes:
    request = _RegularFileRequest(
        label="constraint",
        path=path,
        maximum_bytes=maximum_bytes,
    )
    with _bound_regular_files((request,)) as contents:
        return contents[0]


def _parse_constraint_content(path: Path, content: bytes) -> ConstraintPolicy:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PolicyError("constraint-not-utf8", f"Constraint file is not valid UTF-8: {path}.") from error

    pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if "\\" in raw_line:
            raise PolicyError(
                "constraint-continuation-forbidden",
                f"Constraint line {line_number} uses a forbidden continuation.",
            )
        content_line = raw_line.split("#", 1)[0].strip()
        if not content_line:
            continue
        match = PIN_PATTERN.fullmatch(content_line)
        if match is None or "*" in content_line:
            raise PolicyError(
                "constraint-non-exact-pin",
                f"Constraint line {line_number} is not one exact name==version pin.",
            )
        raw_name = match.group("name")
        version = match.group("version")
        name = normalize_name(raw_name)
        if name in pins:
            raise PolicyError(
                "constraint-duplicate-name",
                f"Constraint repeats normalized distribution name {name!r} on line {line_number}.",
            )
        pins[name] = version

    if not pins:
        raise PolicyError("constraint-empty", f"Constraint file contains no exact pins: {path}.")
    return ConstraintPolicy(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        pins=pins,
    )


def load_constraint(path: Path) -> ConstraintPolicy:
    return _parse_constraint_content(
        path,
        _read_regular_file(path, MAX_CONSTRAINT_BYTES),
    )


def _read_bootstrap_source(path: Path) -> bytes:
    request = _RegularFileRequest(
        label="bootstrap source",
        path=path,
        maximum_bytes=MAX_CONSTRAINT_BYTES,
        bootstrap_source=True,
    )
    with _bound_regular_files((request,)) as contents:
        return contents[0]


def _parse_bootstrap_content(path: Path, content: bytes) -> BootstrapPolicy:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PolicyError(
            "bootstrap-source-invalid",
            f"Bootstrap source is not valid UTF-8: {path}.",
        ) from error

    parsed: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\\" in raw_line:
            raise PolicyError(
                "bootstrap-source-invalid",
                f"Bootstrap source line {line_number} uses a forbidden continuation.",
            )
        match = BOOTSTRAP_PIN_PATTERN.fullmatch(stripped)
        if match is None or "*" in stripped:
            raise PolicyError(
                "bootstrap-source-invalid",
                f"Bootstrap source line {line_number} is not one exact name==version pin.",
            )
        parsed.append((match.group("name"), match.group("version")))

    names = tuple(name for name, _ in parsed)
    if names != BOOTSTRAP_NAMES:
        raise PolicyError(
            "bootstrap-source-invalid",
            "Bootstrap source must contain exactly pip followed by pip-tools, each once, "
            "with no other requirements.",
        )
    pair = BootstrapPair(pip=parsed[0][1], pip_tools=parsed[1][1])
    return BootstrapPolicy(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        pair=pair,
    )


def load_bootstrap_requirements(path: Path) -> BootstrapPolicy:
    """Load the exact, reviewed pip/pip-tools compatibility pair."""

    return _parse_bootstrap_content(path, _read_bootstrap_source(path))


def bootstrap_pair(pins: Mapping[str, str], *, label: str) -> BootstrapPair:
    missing = [name for name in BOOTSTRAP_NAMES if name not in pins]
    if missing:
        raise PolicyError(
            "bootstrap-pair-missing",
            f"{label} does not exact-pin the complete bootstrap pair: {', '.join(missing)}.",
        )
    return BootstrapPair(pip=pins["pip"], pip_tools=pins["pip-tools"])


def _pair_label(pair: BootstrapPair) -> str:
    return f"pip=={pair.pip}, pip-tools=={pair.pip_tools}"


def _normalized_path(path: Path) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))
    except (OSError, ValueError) as error:
        raise PolicyError(
            "bootstrap-path-alias",
            f"Cannot safely normalize bootstrap policy path {path}: {error}.",
        ) from error


def _reject_path_aliases(paths: Sequence[tuple[str, Path]]) -> None:
    for index, (first_label, first_path) in enumerate(paths):
        for second_label, second_path in paths[index + 1 :]:
            if paths_alias(first_path, second_path):
                raise PolicyError(
                    "bootstrap-path-alias",
                    f"Bootstrap policy paths {first_label} and {second_label} must refer to different files.",
                )


def validate_bootstrap_state(
    source: BootstrapPolicy,
    constraints: Sequence[ConstraintPolicy],
    *,
    policy: BootstrapPolicyName,
) -> BootstrapState:
    if policy == "stable":
        if len(constraints) != 1:
            raise PolicyError(
                "bootstrap-native-path-set-mismatch",
                "Stable bootstrap policy requires exactly one selected constraint.",
            )
        selected_pair = bootstrap_pair(
            constraints[0].pins,
            label=f"Selected constraint {constraints[0].path}",
        )
        if selected_pair != source.pair:
            raise PolicyError(
                "bootstrap-source-lock-mismatch",
                "Bootstrap source and selected constraint disagree: source has "
                f"{_pair_label(source.pair)}; selected constraint has {_pair_label(selected_pair)}. "
                "Run the native Dependency Locks workflow and commit all three reviewed lock artifacts.",
            )
        return BootstrapState(
            policy=policy,
            state="stable",
            source=source,
            constraints=tuple(constraints),
            current_pair=selected_pair,
            proposed_pair=source.pair,
        )

    if policy != "native-lock-workflow":
        raise PolicyError("bootstrap-source-invalid", f"Unsupported bootstrap policy: {policy!r}.")
    if len(constraints) != len(NATIVE_CONSTRAINT_PATHS):
        raise PolicyError(
            "bootstrap-native-path-set-mismatch",
            f"Native lock workflow policy requires exactly {len(NATIVE_CONSTRAINT_PATHS)} constraints.",
        )
    constraint_pairs = tuple(
        bootstrap_pair(constraint.pins, label=f"Native constraint {constraint.path}")
        for constraint in constraints
    )
    current_pair = constraint_pairs[0]
    if any(pair != current_pair for pair in constraint_pairs[1:]):
        details = "; ".join(
            f"{constraint.path}: {_pair_label(pair)}"
            for constraint, pair in zip(constraints, constraint_pairs, strict=True)
        )
        raise PolicyError(
            "bootstrap-native-pair-mismatch",
            "Native constraints contain a mixed or partially updated bootstrap pair: "
            f"{details}. Restore one identical pair across all three native locks before continuing.",
        )
    state: BootstrapStateName = "stable" if current_pair == source.pair else "source-transition"
    return BootstrapState(
        policy=policy,
        state=state,
        source=source,
        constraints=tuple(constraints),
        current_pair=current_pair,
        proposed_pair=source.pair,
    )


def _load_bootstrap_cohort(
    *,
    source_path: Path,
    constraint_paths: Sequence[Path],
    constraint_labels: Sequence[str],
    policy: BootstrapPolicyName,
) -> BootstrapState:
    requests = (
        _RegularFileRequest(
            label="bootstrap source",
            path=source_path,
            maximum_bytes=MAX_CONSTRAINT_BYTES,
            bootstrap_source=True,
        ),
        *(
            _RegularFileRequest(
                label=label,
                path=path,
                maximum_bytes=MAX_CONSTRAINT_BYTES,
            )
            for label, path in zip(
                constraint_labels,
                constraint_paths,
                strict=True,
            )
        ),
    )
    with _bound_regular_files(requests) as contents:
        source = _parse_bootstrap_content(source_path, contents[0])
        constraints = tuple(
            _parse_constraint_content(path, content)
            for path, content in zip(
                constraint_paths,
                contents[1:],
                strict=True,
            )
        )
        return validate_bootstrap_state(source, constraints, policy=policy)


def load_bootstrap_state(
    *,
    source_path: Path,
    selected_constraint_path: Path | None,
    policy: BootstrapPolicyName,
) -> BootstrapState:
    if policy == "stable":
        if selected_constraint_path is None:
            raise PolicyError(
                "bootstrap-native-path-set-mismatch",
                "Stable bootstrap policy requires --constraint.",
            )
        _reject_path_aliases(
            (("bootstrap source", source_path), ("selected constraint", selected_constraint_path))
        )
        return _load_bootstrap_cohort(
            source_path=source_path,
            constraint_paths=(selected_constraint_path,),
            constraint_labels=("selected constraint",),
            policy=policy,
        )

    if policy != "native-lock-workflow":
        raise PolicyError("bootstrap-source-invalid", f"Unsupported bootstrap policy: {policy!r}.")
    native_paths = NATIVE_CONSTRAINT_PATHS
    _reject_path_aliases(
        (("bootstrap source", source_path),)
        + tuple((f"native constraint {index + 1}", path) for index, path in enumerate(native_paths))
    )
    if selected_constraint_path is not None:
        selected_normalized = _normalized_path(selected_constraint_path)
        native_normalized = tuple(_normalized_path(path) for path in native_paths)
        if selected_normalized not in native_normalized:
            raise PolicyError(
                "bootstrap-native-path-set-mismatch",
                "Native lock workflow environment verification requires one canonical native constraint.",
            )
        # Inspect the spelling supplied by the caller too; a symlink or other
        # nonregular alias must not borrow trust from a canonical target.
        load_constraint(selected_constraint_path)
    return _load_bootstrap_cohort(
        source_path=source_path,
        constraint_paths=native_paths,
        constraint_labels=tuple(
            f"native constraint {index + 1}" for index in range(len(native_paths))
        ),
        policy=policy,
    )


def selected_constraint_from_state(state: BootstrapState, path: Path) -> ConstraintPolicy:
    normalized = _normalized_path(path)
    matches = tuple(
        constraint for constraint in state.constraints if _normalized_path(constraint.path) == normalized
    )
    if len(matches) != 1:
        raise PolicyError(
            "bootstrap-native-path-set-mismatch",
            f"Selected constraint is not uniquely represented by bootstrap policy: {path}.",
        )
    return matches[0]


def expected_pip_version(state: BootstrapState, selected_constraint: ConstraintPolicy) -> str:
    selected_pair = bootstrap_pair(
        selected_constraint.pins,
        label=f"Selected constraint {selected_constraint.path}",
    )
    expected_pair = state.current_pair if state.policy == "native-lock-workflow" else state.proposed_pair
    if selected_pair != expected_pair:
        raise PolicyError(
            "bootstrap-source-lock-mismatch",
            "Selected constraint bootstrap pair is inconsistent with the validated bootstrap state.",
        )
    return expected_pair.pip


def parse_expected_environment(
    *,
    python_full_version: str,
    sys_platform: str,
    platform_machine: str,
    pip_version: str,
) -> ExpectedEnvironment:
    match = PYTHON_VERSION_PATTERN.fullmatch(python_full_version)
    if match is None:
        raise PolicyError(
            "invalid-expected-python",
            f"Expected Python must be an exact full version, got {python_full_version!r}.",
        )
    if sys_platform not in PLATFORM_EXPECTATIONS:
        raise PolicyError(
            "invalid-expected-platform",
            f"Expected platform must be one of {sorted(PLATFORM_EXPECTATIONS)}, got {sys_platform!r}.",
        )
    if not platform_machine or platform_machine.strip() != platform_machine:
        raise PolicyError("invalid-expected-machine", "Expected machine must be a nonempty exact value.")
    if not pip_version or pip_version.strip() != pip_version:
        raise PolicyError("invalid-expected-pip", "Expected pip must be a nonempty exact version.")
    return ExpectedEnvironment(
        python_full_version=python_full_version,
        python_version=f"{match.group('major')}.{match.group('minor')}",
        sys_platform=sys_platform,
        platform_machine=platform_machine,
        pip_version=pip_version,
    )


def _duplicate_checked_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Unsupported JSON constant: {value}.")


def parse_inspect_json(text: str) -> object:
    try:
        return cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_duplicate_checked_object,
                parse_constant=_reject_json_constant,
            ),
        )
    except (DuplicateJsonKeyError, json.JSONDecodeError, ValueError) as error:
        raise PolicyError("pip-inspect-invalid-json", f"pip inspect did not emit strict JSON: {error}.") from error


def _required_string(value: Mapping[str, object], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise PolicyError("pip-inspect-invalid-schema", f"{label}.{key} must be a nonempty string.")
    return item


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PolicyError("pip-inspect-invalid-schema", f"{label} must be an object.")
    return cast(dict[str, object], value)


def _string_environment(value: object) -> Mapping[str, str]:
    source = _mapping(value, "pip inspect environment")
    result: dict[str, str] = {}
    for key, item in source.items():
        if not isinstance(item, str):
            raise PolicyError(
                "pip-inspect-invalid-schema",
                "pip inspect environment keys and values must be strings.",
            )
        result[key] = item
    return result


def _mismatch(
    code: str,
    message: str,
    *,
    name: str = "",
    expected: str = "",
    observed: str = "",
) -> Finding:
    return Finding(code=code, message=message, name=name, expected=expected, observed=observed)


def _metadata_location_is_local(location: str) -> bool:
    location_path = Path(location)
    if not location_path.is_absolute() or not location_path.name.endswith(".dist-info"):
        return False
    try:
        resolved_prefix = Path(sys.prefix).resolve(strict=True)
        resolved_location = location_path.resolve(strict=True)
        if not resolved_location.is_dir() or not resolved_location.name.endswith(".dist-info"):
            return False
        normalized_prefix = os.path.normcase(os.fspath(resolved_prefix))
        normalized_location = os.path.normcase(os.fspath(resolved_location))
        return os.path.commonpath((normalized_prefix, normalized_location)) == normalized_prefix
    except (OSError, RuntimeError, ValueError):
        return False


def analyze_inspect_report(
    report_value: object,
    *,
    policy: ConstraintPolicy,
    expected_environment: ExpectedEnvironment,
    mode: str,
    required_names: Sequence[str],
) -> InspectAnalysis:
    report = _mapping(report_value, "pip inspect report")
    schema_version = _required_string(report, "version", "pip inspect report")
    pip_version = _required_string(report, "pip_version", "pip inspect report")
    environment = _string_environment(report.get("environment"))
    installed_value = report.get("installed")
    if not isinstance(installed_value, list):
        raise PolicyError("pip-inspect-invalid-schema", "pip inspect report.installed must be an array.")
    installed_items = cast(list[object], installed_value)

    findings: list[Finding] = []
    if schema_version != INSPECT_SCHEMA_VERSION:
        findings.append(
            _mismatch(
                "pip-inspect-schema-mismatch",
                "pip inspect schema version is unsupported.",
                expected=INSPECT_SCHEMA_VERSION,
                observed=schema_version,
            )
        )
    if pip_version != expected_environment.pip_version:
        findings.append(
            _mismatch(
                "pip-version-mismatch",
                "pip inspect was produced by a different pip version.",
                name="pip",
                expected=expected_environment.pip_version,
                observed=pip_version,
            )
        )

    expected_fields: dict[str, str] = {
        "implementation_name": "cpython",
        "implementation_version": expected_environment.python_full_version,
        "os_name": PLATFORM_EXPECTATIONS[expected_environment.sys_platform][0],
        "platform_machine": expected_environment.platform_machine,
        "platform_python_implementation": "CPython",
        "platform_system": PLATFORM_EXPECTATIONS[expected_environment.sys_platform][1],
        "python_full_version": expected_environment.python_full_version,
        "python_version": expected_environment.python_version,
        "sys_platform": expected_environment.sys_platform,
    }
    for field, expected in expected_fields.items():
        observed = environment.get(field, "")
        if observed != expected:
            findings.append(
                _mismatch(
                    "environment-mismatch",
                    f"pip inspect environment field {field!r} did not match policy.",
                    name=field,
                    expected=expected,
                    observed=observed,
                )
            )

    installed: dict[str, str] = {}
    for index, raw_item in enumerate(installed_items):
        item = _mapping(raw_item, f"pip inspect installed[{index}]")
        metadata = _mapping(item.get("metadata"), f"pip inspect installed[{index}].metadata")
        raw_name = _required_string(metadata, "name", f"pip inspect installed[{index}].metadata")
        version = _required_string(metadata, "version", f"pip inspect installed[{index}].metadata")
        metadata_location = _required_string(item, "metadata_location", f"pip inspect installed[{index}]")
        installer = item.get("installer")
        name = normalize_name(raw_name)
        if name in installed:
            findings.append(
                _mismatch(
                    "installed-duplicate-name",
                    "pip inspect repeated a normalized installed distribution name.",
                    name=name,
                    observed=version,
                )
            )
        else:
            installed[name] = version
        if installer != "pip":
            findings.append(
                _mismatch(
                    "installer-mismatch",
                    "Installed distribution was not recorded as installed by pip.",
                    name=name,
                    expected="pip",
                    observed=installer if isinstance(installer, str) else "<missing>",
                )
            )
        if item.get("direct_url") is not None:
            findings.append(
                _mismatch(
                    "direct-url-forbidden",
                    "Installed distribution used a direct URL outside the index pin policy.",
                    name=name,
                )
            )
        if not _metadata_location_is_local(metadata_location):
            findings.append(
                _mismatch(
                    "metadata-location-outside-environment",
                    "Installed distribution metadata is not a local .dist-info path under the active Python prefix.",
                    name=name,
                    observed=metadata_location,
                )
            )

    expected_pip = policy.pins.get("pip")
    observed_pip = installed.get("pip")
    if expected_pip is None:
        findings.append(_mismatch("pip-pin-missing", "The selected constraint does not exact-pin pip.", name="pip"))
    elif expected_pip != expected_environment.pip_version:
        findings.append(
            _mismatch(
                "pip-constraint-mismatch",
                "The selected constraint's pip pin differs from expected pip.",
                name="pip",
                expected=expected_environment.pip_version,
                observed=expected_pip,
            )
        )
    if observed_pip is None:
        findings.append(_mismatch("pip-not-installed", "pip is absent from the inspected environment.", name="pip"))
    elif observed_pip != expected_environment.pip_version:
        findings.append(
            _mismatch(
                "pip-installed-version-mismatch",
                "Installed pip metadata differs from expected pip.",
                name="pip",
                expected=expected_environment.pip_version,
                observed=observed_pip,
            )
        )

    for name, observed_version in installed.items():
        if name == "pip":
            continue
        expected_version = policy.pins.get(name)
        if expected_version is None:
            findings.append(
                _mismatch(
                    "unexpected-installed-distribution",
                    "Installed non-bootstrap distribution is absent from the selected constraint.",
                    name=name,
                    observed=observed_version,
                )
            )
        elif expected_version != observed_version:
            findings.append(
                _mismatch(
                    "installed-version-mismatch",
                    "Installed distribution version differs from the selected exact pin.",
                    name=name,
                    expected=expected_version,
                    observed=observed_version,
                )
            )

    required: set[str] = set()
    for raw_name in required_names:
        name = normalize_name(raw_name)
        if name in required:
            findings.append(
                _mismatch(
                    "required-duplicate-name",
                    "A required distribution name was repeated after normalization.",
                    name=name,
                )
            )
            continue
        required.add(name)
        if name not in policy.pins:
            findings.append(
                _mismatch(
                    "required-pin-missing",
                    "Required distribution is absent from the selected constraint.",
                    name=name,
                )
            )
        if name not in installed:
            findings.append(
                _mismatch(
                    "required-distribution-missing",
                    "Required distribution is absent from the inspected environment.",
                    name=name,
                )
            )

    if mode == "complete":
        for name, expected_version in policy.pins.items():
            if name == "pip":
                continue
            if name not in installed:
                findings.append(
                    _mismatch(
                        "complete-distribution-missing",
                        "Complete mode requires every non-bootstrap constraint pin to be installed.",
                        name=name,
                        expected=expected_version,
                    )
                )
    elif mode != "subset":
        raise PolicyError("invalid-mode", f"Unsupported verification mode: {mode!r}.")

    return InspectAnalysis(
        schema_version=schema_version,
        pip_version=pip_version,
        environment=environment,
        installed=installed,
        findings=tuple(sorted(findings)),
    )


def _bounded_text(value: str, maximum_bytes: int = MAX_COMMAND_OUTPUT_BYTES) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return value
    marker = b"\n...[truncated by dependency verifier]\n"
    prefix = encoded[: max(0, maximum_bytes - len(marker))]
    return (prefix + marker).decode("utf-8", errors="replace")


def _isolated_pip_environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        normalized_key = key.upper()
        if normalized_key.startswith("PIP_") or normalized_key.startswith("PYTHON"):
            continue
        environment[key] = value
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def _capture_overflow(
    *,
    label: str,
    stdout: IO[bytes],
    stderr: IO[bytes],
    maximum_stdout_bytes: int,
) -> Finding | None:
    limits = (
        ("stdout", stdout, maximum_stdout_bytes),
        ("stderr", stderr, MAX_COMMAND_OUTPUT_BYTES),
    )
    for stream_name, stream, maximum_bytes in limits:
        if os.fstat(stream.fileno()).st_size > maximum_bytes:
            return Finding(
                code=f"{label}-{stream_name}-too-large",
                message=f"{label} {stream_name} exceeded the {maximum_bytes}-byte verifier limit.",
            )
    return None


def _read_bounded_output(stream: IO[bytes], maximum_bytes: int) -> tuple[str, bool]:
    stream.seek(0)
    payload = stream.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        return "", True
    return payload.decode("utf-8", errors="replace"), False


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def _failed_command(label: str, suffix: str, message: str) -> CommandResult:
    return CommandResult(
        returncode=None,
        stdout="",
        stderr="",
        failure=Finding(code=f"{label}-{suffix}", message=message),
    )


def _run_pip(
    arguments: Sequence[str],
    label: str,
    *,
    maximum_stdout_bytes: int,
) -> CommandResult:
    # Python isolated mode protects module resolution; because it ignores
    # PYTHON* settings, the interpreter flag must keep pip's redirected JSON
    # output lossless on Windows regardless of the ANSI code page. Pip isolated
    # mode and the filtered environment independently protect configuration.
    command = [
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
        *arguments,
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        with (
            tempfile.TemporaryFile(mode="w+b") as stdout_file,
            tempfile.TemporaryFile(mode="w+b") as stderr_file,
        ):
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=_isolated_pip_environment(),
                close_fds=True,
                shell=False,
            )
            deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
            returncode = process.poll()
            while returncode is None:
                overflow = _capture_overflow(
                    label=label,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    maximum_stdout_bytes=maximum_stdout_bytes,
                )
                if overflow is not None:
                    _kill_and_reap(process)
                    return CommandResult(returncode=None, stdout="", stderr="", failure=overflow)

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_and_reap(process)
                    return _failed_command(
                        label,
                        "timeout",
                        f"{label} exceeded the {COMMAND_TIMEOUT_SECONDS:g}-second timeout.",
                    )
                try:
                    returncode = process.wait(timeout=min(COMMAND_OUTPUT_POLL_SECONDS, remaining))
                except subprocess.TimeoutExpired:
                    returncode = None

            overflow = _capture_overflow(
                label=label,
                stdout=stdout_file,
                stderr=stderr_file,
                maximum_stdout_bytes=maximum_stdout_bytes,
            )
            if overflow is not None:
                return CommandResult(returncode=None, stdout="", stderr="", failure=overflow)

            stdout, stdout_overflow = _read_bounded_output(stdout_file, maximum_stdout_bytes)
            stderr, stderr_overflow = _read_bounded_output(stderr_file, MAX_COMMAND_OUTPUT_BYTES)
            if stdout_overflow:
                return _failed_command(
                    label,
                    "stdout-too-large",
                    f"{label} stdout exceeded the {maximum_stdout_bytes}-byte verifier limit.",
                )
            if stderr_overflow:
                return _failed_command(
                    label,
                    "stderr-too-large",
                    f"{label} stderr exceeded the {MAX_COMMAND_OUTPUT_BYTES}-byte verifier limit.",
                )
            return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)
    except OSError:
        return _failed_command(label, "execution-failed", f"Cannot safely execute or capture {label}.")
    finally:
        if process is not None and process.poll() is None:
            _kill_and_reap(process)


def _pin_list(pins: Mapping[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "version": pins[name]} for name in sorted(pins)]


def _command_json(result: CommandResult) -> dict[str, object]:
    return {
        "returncode": result.returncode,
        "stderr": _bounded_text(result.stderr),
        "stdout": _bounded_text(result.stdout),
    }


def _inspect_command_json(result: CommandResult) -> dict[str, object]:
    # The full report contains order, paths, and descriptive metadata that are
    # intentionally excluded from the normalized receipt. Its validated,
    # stable projection is recorded separately by ``build_receipt``.
    return {
        "returncode": result.returncode,
        "stderr": _bounded_text(result.stderr),
    }


def _normalized_required_names(required_names: Sequence[str]) -> list[str]:
    normalized: set[str] = set()
    for raw_name in required_names:
        try:
            normalized.add(normalize_name(raw_name))
        except PolicyError:
            normalized.add(raw_name)
    return sorted(normalized)


def _bootstrap_source_json(source: BootstrapPolicy) -> dict[str, object]:
    pins = source.pair.as_pins()
    return {
        "path": str(source.path),
        "sha256": source.sha256,
        "pin_fingerprint": pin_fingerprint(pins),
        "pins": pins,
    }


def _bootstrap_constraint_json(constraint: ConstraintPolicy) -> dict[str, object]:
    pair = bootstrap_pair(constraint.pins, label=f"Constraint {constraint.path}")
    return {
        "path": str(constraint.path),
        "sha256": constraint.sha256,
        "pin_fingerprint": pin_fingerprint(constraint.pins),
        "bootstrap_pins": pair.as_pins(),
    }


def bootstrap_projection(state: BootstrapState) -> dict[str, object]:
    transition_active = state.state == "source-transition"
    return {
        "policy": state.policy,
        "state": state.state,
        "source": _bootstrap_source_json(state.source),
        "constraints": [_bootstrap_constraint_json(constraint) for constraint in state.constraints],
        "source_transition": {
            "active": transition_active,
            "from": state.current_pair.as_pins(),
            "to": state.proposed_pair.as_pins(),
        },
    }


def build_bootstrap_receipt(state: BootstrapState) -> dict[str, object]:
    return {
        "schema_version": BOOTSTRAP_RECEIPT_SCHEMA_VERSION,
        "status": "verified",
        **bootstrap_projection(state),
        "errors": [],
    }


def _bootstrap_failure_receipt(
    *,
    source_path: Path,
    constraint_paths: Sequence[Path],
    policy: BootstrapPolicyName,
    finding: Finding,
) -> dict[str, object]:
    return {
        "schema_version": BOOTSTRAP_RECEIPT_SCHEMA_VERSION,
        "status": "failed",
        "policy": policy,
        "state": "invalid",
        "source": {"path": str(source_path)},
        "constraints": [{"path": str(path)} for path in constraint_paths],
        "source_transition": {"active": False, "from": {}, "to": {}},
        "errors": [finding.as_json()],
    }


def _base_receipt(
    *,
    mode: str,
    constraint_path: Path,
    required_names: Sequence[str],
    expected_environment: ExpectedEnvironment | None,
    bootstrap_state: BootstrapState | None,
) -> dict[str, object]:
    expected_json: dict[str, str] = {}
    if expected_environment is not None:
        expected_json = {
            "implementation_name": "cpython",
            "pip_version": expected_environment.pip_version,
            "platform_machine": expected_environment.platform_machine,
            "python_full_version": expected_environment.python_full_version,
            "python_version": expected_environment.python_version,
            "sys_platform": expected_environment.sys_platform,
        }
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "failed",
        "mode": mode,
        "bootstrap": bootstrap_projection(bootstrap_state) if bootstrap_state is not None else {},
        "constraint": {"path": str(constraint_path)},
        "required": _normalized_required_names(required_names),
        "expected_environment": expected_json,
        "observation": {},
        "errors": [],
    }


def build_receipt(
    *,
    mode: str,
    policy: ConstraintPolicy,
    required_names: Sequence[str],
    expected_environment: ExpectedEnvironment,
    inspect_result: CommandResult,
    check_result: CommandResult,
    analysis: InspectAnalysis | None,
    findings: Sequence[Finding],
    bootstrap_state: BootstrapState,
) -> dict[str, object]:
    receipt = _base_receipt(
        mode=mode,
        constraint_path=policy.path,
        required_names=required_names,
        expected_environment=expected_environment,
        bootstrap_state=bootstrap_state,
    )
    receipt["constraint"] = {
        "fingerprint": pin_fingerprint(policy.pins),
        "path": str(policy.path),
        "pins": _pin_list(policy.pins),
        "sha256": policy.sha256,
    }
    observation: dict[str, object] = {
        "pip_check": _command_json(check_result),
        "pip_inspect": _inspect_command_json(inspect_result),
    }
    if analysis is not None:
        stable_environment_keys = (
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
        observation.update(
            {
                "environment": {key: analysis.environment.get(key, "") for key in stable_environment_keys},
                "installed": _pin_list(analysis.installed),
                "installed_fingerprint": pin_fingerprint(analysis.installed),
                "pip_inspect_schema": analysis.schema_version,
                "pip_version": analysis.pip_version,
            }
        )
    receipt["observation"] = observation
    sorted_findings = sorted(set(findings))
    receipt["errors"] = [finding.as_json() for finding in sorted_findings]
    if not sorted_findings:
        receipt["status"] = "verified"
    return receipt


def atomic_write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            receipt,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        try:
            handle = os.fdopen(descriptor, "wb")
        except BaseException as error:
            try:
                os.close(descriptor)
            except BaseException as cleanup_error:
                error.add_note(
                    f"Could not close receipt temporary descriptor: {cleanup_error}"
                )
            raise
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException as error:
            try:
                handle.close()
            except BaseException as cleanup_error:
                error.add_note(f"Could not close receipt temporary file: {cleanup_error}")
            raise
        else:
            handle.close()
        os.replace(temporary_path, path)
    except BaseException as error:
        try:
            temporary_path.unlink(missing_ok=True)
        except BaseException as cleanup_error:
            error.add_note(f"Could not remove receipt temporary file: {cleanup_error}")
        raise


def _parse_bootstrap_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the reviewed pip/pip-tools bootstrap policy.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--policy", choices=("stable", "native-lock-workflow"), required=True)
    parser.add_argument("--constraint")
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def bootstrap_preflight_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_bootstrap_arguments(argv)
    source_path = Path(cast(str, arguments.source))
    output_path = Path(cast(str, arguments.output))
    policy = cast(BootstrapPolicyName, arguments.policy)
    raw_constraint = cast(str | None, arguments.constraint)
    selected_constraint_path = Path(raw_constraint) if raw_constraint is not None else None
    failure_finding: Finding | None = None

    if policy == "stable" and selected_constraint_path is None:
        print("Stable bootstrap policy requires --constraint.", file=sys.stderr)
        return 2
    if policy == "native-lock-workflow" and selected_constraint_path is not None:
        print("Native lock workflow bootstrap policy loads the canonical constraints itself.", file=sys.stderr)
        return 2

    constraint_paths = (
        (selected_constraint_path,)
        if selected_constraint_path is not None
        else NATIVE_CONSTRAINT_PATHS
    )
    try:
        _reject_path_aliases(
            (("bootstrap source", source_path),)
            + tuple((f"constraint {index + 1}", path) for index, path in enumerate(constraint_paths))
            + (("receipt output", output_path),)
        )
    except PolicyError as error:
        print(f"Cannot validate bootstrap preflight paths: {error}", file=sys.stderr)
        return 2

    try:
        state = load_bootstrap_state(
            source_path=source_path,
            selected_constraint_path=selected_constraint_path,
            policy=policy,
        )
        receipt = build_bootstrap_receipt(state)
    except PolicyError as error:
        failure_finding = Finding(code=error.code, message=str(error))
        receipt = _bootstrap_failure_receipt(
            source_path=source_path,
            constraint_paths=constraint_paths,
            policy=policy,
            finding=failure_finding,
        )

    try:
        atomic_write_receipt(output_path, receipt)
    except OSError as error:
        print(f"Cannot write bootstrap verification receipt {output_path}: {error}", file=sys.stderr)
        return 2

    if receipt["status"] == "verified":
        print(f"Dependency bootstrap policy verified; receipt: {output_path}")
        return 0
    assert failure_finding is not None
    print(
        "Dependency bootstrap policy verification failed "
        f"[{failure_finding.code}]: {failure_finding.message} Receipt: {output_path}",
        file=sys.stderr,
    )
    return 1


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraint", required=True)
    parser.add_argument("--mode", choices=("subset", "complete"), required=True)
    parser.add_argument("--require", action="append", default=[], dest="required")
    parser.add_argument("--expected-python", required=True)
    parser.add_argument("--expected-platform", required=True)
    parser.add_argument("--expected-machine", required=True)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument(
        "--bootstrap-policy",
        choices=("stable", "native-lock-workflow"),
        required=True,
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    constraint_path = Path(cast(str, arguments.constraint))
    bootstrap_path = Path(cast(str, arguments.bootstrap))
    output_path = Path(cast(str, arguments.output))
    mode = cast(str, arguments.mode)
    required_names = tuple(cast(list[str], arguments.required))
    bootstrap_policy_name = cast(BootstrapPolicyName, arguments.bootstrap_policy)
    expected_environment: ExpectedEnvironment | None = None
    policy: ConstraintPolicy | None = None
    bootstrap_state: BootstrapState | None = None
    findings: list[Finding] = []

    try:
        paths_to_check: tuple[tuple[str, Path], ...] = (
            ("bootstrap source", bootstrap_path),
            ("selected constraint", constraint_path),
            ("receipt output", output_path),
        )
        if bootstrap_policy_name == "native-lock-workflow":
            paths_to_check += tuple(
                (f"native constraint {index + 1}", path)
                for index, path in enumerate(NATIVE_CONSTRAINT_PATHS)
                if _normalized_path(path) != _normalized_path(constraint_path)
            )
        _reject_path_aliases(paths_to_check)
    except PolicyError as error:
        print(f"Cannot validate dependency verifier paths: {error}", file=sys.stderr)
        return 2

    try:
        for required_name in required_names:
            normalize_name(required_name)
        if bootstrap_policy_name == "native-lock-workflow":
            normalized_required = tuple(normalize_name(name) for name in required_names)
            if mode != "subset" or normalized_required != BOOTSTRAP_NAMES:
                raise PolicyError(
                    "bootstrap-native-policy-misuse",
                    "Native lock workflow policy is restricted to subset verification requiring "
                    "pip followed by pip-tools.",
                )
        bootstrap_state = load_bootstrap_state(
            source_path=bootstrap_path,
            selected_constraint_path=constraint_path,
            policy=bootstrap_policy_name,
        )
        policy = selected_constraint_from_state(bootstrap_state, constraint_path)
        expected_environment = parse_expected_environment(
            python_full_version=cast(str, arguments.expected_python),
            sys_platform=cast(str, arguments.expected_platform),
            platform_machine=cast(str, arguments.expected_machine),
            pip_version=expected_pip_version(bootstrap_state, policy),
        )
    except PolicyError as error:
        findings.append(Finding(code=error.code, message=str(error)))

    inspect_result = CommandResult(returncode=None, stdout="", stderr="")
    check_result = CommandResult(returncode=None, stdout="", stderr="")
    analysis: InspectAnalysis | None = None
    if policy is not None and expected_environment is not None and not findings:
        inspect_result = _run_pip(
            ("inspect",),
            "pip-inspect",
            maximum_stdout_bytes=MAX_INSPECT_BYTES,
        )
        check_result = _run_pip(
            ("check",),
            "pip-check",
            maximum_stdout_bytes=MAX_COMMAND_OUTPUT_BYTES,
        )
        if inspect_result.failure is not None:
            findings.append(inspect_result.failure)
        elif inspect_result.returncode != 0:
            findings.append(
                Finding(
                    code="pip-inspect-failed",
                    message="pip inspect returned a nonzero exit status.",
                    observed=str(inspect_result.returncode),
                )
            )
        elif len(inspect_result.stdout.encode("utf-8", errors="replace")) > MAX_INSPECT_BYTES:
            findings.append(
                Finding(
                    code="pip-inspect-too-large",
                    message=f"pip inspect exceeded the {MAX_INSPECT_BYTES}-byte verifier limit.",
                )
            )
        else:
            try:
                report = parse_inspect_json(inspect_result.stdout)
                analysis = analyze_inspect_report(
                    report,
                    policy=policy,
                    expected_environment=expected_environment,
                    mode=mode,
                    required_names=required_names,
                )
                findings.extend(analysis.findings)
            except PolicyError as error:
                findings.append(Finding(code=error.code, message=str(error)))

        if check_result.failure is not None:
            findings.append(check_result.failure)
        elif check_result.returncode != 0:
            findings.append(
                Finding(
                    code="pip-check-failed",
                    message="pip check reported an incompatible installed dependency graph.",
                    observed=str(check_result.returncode),
                )
            )

    if policy is not None and expected_environment is not None and bootstrap_state is not None:
        receipt = build_receipt(
            mode=mode,
            policy=policy,
            required_names=required_names,
            expected_environment=expected_environment,
            inspect_result=inspect_result,
            check_result=check_result,
            analysis=analysis,
            findings=findings,
            bootstrap_state=bootstrap_state,
        )
    else:
        receipt = _base_receipt(
            mode=mode,
            constraint_path=constraint_path,
            required_names=required_names,
            expected_environment=expected_environment,
            bootstrap_state=bootstrap_state,
        )
        receipt["errors"] = [finding.as_json() for finding in sorted(set(findings))]

    try:
        atomic_write_receipt(output_path, receipt)
    except OSError as error:
        print(f"Cannot write dependency verification receipt {output_path}: {error}", file=sys.stderr)
        return 2

    if receipt["status"] == "verified":
        print(f"Dependency environment verified; receipt: {output_path}")
        return 0
    print(f"Dependency environment verification failed; receipt: {output_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
