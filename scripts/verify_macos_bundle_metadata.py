from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import cast
import unicodedata
from xml.parsers.expat import ExpatError
import zipfile


POLICY_COMPONENTS = ("packaging", "macos", "bundle_metadata.py")
APP_PLIST_COMPONENTS = ("GM2Godot.app", "Contents", "Info.plist")
ZIP_PLIST_PATH = "/".join(APP_PLIST_COMPONENTS)
POLICY_KEYS = frozenset({"CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion"})
MAX_POLICY_BYTES = 256 * 1024
MAX_PLIST_BYTES = 1024 * 1024
MAX_HDIUTIL_OUTPUT_BYTES = 1024 * 1024
HDIUTIL_TIMEOUT_SECONDS = 120.0
HDIUTIL_PATH = "/usr/bin/hdiutil"

_BUNDLE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){2,}\Z")
_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_DEVICE_PATTERN = re.compile(r"/dev/disk[0-9]+(?:s[0-9]+)*\Z")


class MetadataVerificationError(Exception):
    """A deterministic validation failure suitable for one-line CLI output."""


@dataclass(frozen=True)
class BundleMetadata:
    identifier: str
    short_version: str
    build_version: str
    plist_sha256: str


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _require_absolute_path(raw_path: str, description: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        raise MetadataVerificationError(f"{description} must be an absolute path: {raw_path!r}")
    if Path(os.path.normpath(os.fspath(path))) != path:
        raise MetadataVerificationError(f"{description} must be lexically normalized: {raw_path!r}")
    return path


def _open_flags(*names: str) -> int:
    if os.open not in os.supports_dir_fd:
        raise MetadataVerificationError("descriptor-relative no-follow filesystem operations are unavailable")
    flags = os.O_RDONLY
    for name in names:
        value = getattr(os, name, None)
        if type(value) is not int:
            raise MetadataVerificationError(f"required no-follow filesystem flag {name} is unavailable")
        flags |= value
    return flags


def _read_fd_bounded(fd: int, maximum_bytes: int, description: str) -> bytes:
    content = bytearray()
    try:
        while len(content) <= maximum_bytes:
            remaining = maximum_bytes + 1 - len(content)
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            content.extend(chunk)
    except OSError as error:
        raise MetadataVerificationError(f"unable to read {description}: {error}") from error
    if len(content) > maximum_bytes:
        raise MetadataVerificationError(f"{description} exceeds the {maximum_bytes}-byte verification limit")
    return bytes(content)


def _read_regular_beneath(
    root: Path,
    components: Sequence[str],
    maximum_bytes: int,
    description: str,
) -> bytes:
    """Read one fixed regular file without following its root or path components."""

    if not components or any(not component or component in {".", ".."} or "/" in component for component in components):
        raise MetadataVerificationError(f"invalid fixed path for {description}")

    descriptors: list[int] = []
    try:
        try:
            current = os.open(
                root,
                _open_flags("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"),
            )
            descriptors.append(current)
            if not stat.S_ISDIR(os.fstat(current).st_mode):
                raise MetadataVerificationError(f"{description} root is not a directory: {root}")
            for component in components[:-1]:
                current = os.open(
                    component,
                    _open_flags("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"),
                    dir_fd=current,
                )
                descriptors.append(current)
                if not stat.S_ISDIR(os.fstat(current).st_mode):
                    raise MetadataVerificationError(f"{description} component {component!r} is not a directory")
            file_fd = os.open(
                components[-1],
                _open_flags("O_CLOEXEC", "O_NOFOLLOW"),
                dir_fd=current,
            )
            descriptors.append(file_fd)
            before = os.fstat(file_fd)
        except OSError as error:
            raise MetadataVerificationError(f"unable to open {description} without following links: {error}") from error

        if not stat.S_ISREG(before.st_mode):
            raise MetadataVerificationError(f"{description} is not a regular file")
        if before.st_size > maximum_bytes:
            raise MetadataVerificationError(f"{description} exceeds the {maximum_bytes}-byte verification limit")
        return _read_fd_bounded(file_fd, maximum_bytes, description)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _load_policy(source_root: Path) -> dict[str, str]:
    """Execute only the helper at the canonical path (the CLI itself runs under ``-I``)."""

    policy_path = source_root.joinpath(*POLICY_COMPONENTS)
    source = _read_regular_beneath(
        source_root,
        POLICY_COMPONENTS,
        MAX_POLICY_BYTES,
        "macOS bundle metadata policy helper",
    )
    try:
        code = compile(source, os.fspath(policy_path), "exec", dont_inherit=True)
        module = ModuleType("_gm2godot_macos_bundle_metadata_policy")
        module.__file__ = os.fspath(policy_path)
        module.__package__ = ""
        exec(code, module.__dict__)
        loader = module.__dict__.get("load_bundle_metadata")
        if not callable(loader):
            raise MetadataVerificationError("bundle metadata policy does not define callable load_bundle_metadata")
        raw_value = loader(source_root)
    except MetadataVerificationError:
        raise
    except Exception as error:
        raise MetadataVerificationError(f"bundle metadata policy failed: {error}") from error

    if type(raw_value) is not dict:
        raise MetadataVerificationError("bundle metadata policy must return dict[str, str]")
    raw_policy = cast(dict[object, object], raw_value)
    if any(type(key) is not str for key in raw_policy):
        raise MetadataVerificationError("bundle metadata policy keys must be strings")
    if frozenset(cast(str, key) for key in raw_policy) != POLICY_KEYS:
        raise MetadataVerificationError("bundle metadata policy must return exactly the three required Info.plist keys")
    if any(type(value) is not str for value in raw_policy.values()):
        raise MetadataVerificationError("bundle metadata policy values must be strings")
    policy = cast(dict[str, str], raw_policy)

    identifier = policy["CFBundleIdentifier"]
    if not _BUNDLE_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise MetadataVerificationError("bundle metadata policy has an invalid reverse-DNS identifier")
    folded_identifier = identifier.casefold()
    if folded_identifier == "gm2godot" or "example" in folded_identifier.split("."):
        raise MetadataVerificationError("bundle metadata policy retains a placeholder identifier")
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        value = policy[key]
        if not _VERSION_PATTERN.fullmatch(value):
            raise MetadataVerificationError(f"bundle metadata policy has an invalid {key}")
        if value == "0.0.0":
            raise MetadataVerificationError(f"bundle metadata policy retains placeholder {key}")
    if policy["CFBundleShortVersionString"] != policy["CFBundleVersion"]:
        raise MetadataVerificationError("bundle metadata policy requires matching release and build versions")
    return policy


def _parse_bundle_plist(
    content: bytes,
    expected: Mapping[str, str],
    description: str,
) -> BundleMetadata:
    if len(content) > MAX_PLIST_BYTES:
        raise MetadataVerificationError(f"{description} exceeds the {MAX_PLIST_BYTES}-byte verification limit")
    try:
        value = plistlib.loads(content)
    except (
        plistlib.InvalidFileException,
        ExpatError,
        ValueError,
        TypeError,
        OverflowError,
    ) as error:
        raise MetadataVerificationError(f"unable to parse {description}: {error}") from error
    if type(value) is not dict:
        raise MetadataVerificationError(f"{description} root must be a dictionary")
    plist = cast(dict[object, object], value)
    observed: dict[str, str] = {}
    for key in sorted(POLICY_KEYS):
        if key not in plist:
            raise MetadataVerificationError(f"{description} is missing {key}")
        item = plist[key]
        if type(item) is not str:
            raise MetadataVerificationError(f"{description} {key} must be a string")
        expected_item = expected[key]
        if item != expected_item:
            raise MetadataVerificationError(f"{description} {key} is {item!r}; expected {expected_item!r}")
        observed[key] = item
    return BundleMetadata(
        identifier=observed["CFBundleIdentifier"],
        short_version=observed["CFBundleShortVersionString"],
        build_version=observed["CFBundleVersion"],
        plist_sha256=hashlib.sha256(content).hexdigest(),
    )


def inspect_app(app_path: Path, expected: Mapping[str, str]) -> BundleMetadata:
    if app_path.name != APP_PLIST_COMPONENTS[0]:
        raise MetadataVerificationError(f"direct app must be named {APP_PLIST_COMPONENTS[0]}: {app_path}")
    content = _read_regular_beneath(
        app_path.parent,
        APP_PLIST_COMPONENTS,
        MAX_PLIST_BYTES,
        "direct app Info.plist",
    )
    return _parse_bundle_plist(content, expected, "direct app Info.plist")


def _normalized_component(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _zip_member_type(member: zipfile.ZipInfo) -> int:
    return stat.S_IFMT((member.external_attr >> 16) & 0xFFFF)


def _zip_member_is_directory(member: zipfile.ZipInfo) -> bool:
    member_type = _zip_member_type(member)
    return member_type == stat.S_IFDIR or (member_type == 0 and member.is_dir())


def _select_zip_plist(members: Sequence[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    """Select the exact plist and validate only paths that can alias its ancestors."""

    canonical = APP_PLIST_COMPONENTS
    normalized_canonical = tuple(_normalized_component(item) for item in canonical)
    matches: list[zipfile.ZipInfo] = []
    for member in members:
        name = member.filename
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
            or re.match(r"[A-Za-z]:/", name) is not None
        ):
            raise MetadataVerificationError(f"ZIP contains an unsafe member path: {name!r}")
        stripped = name[:-1] if name.endswith("/") else name
        parts = tuple(stripped.split("/"))
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise MetadataVerificationError(f"ZIP contains an unsafe member path: {name!r}")
        if not parts or _normalized_component(parts[0]) != normalized_canonical[0]:
            continue

        if parts[0] != canonical[0]:
            raise MetadataVerificationError(f"ZIP contains a case or Unicode alias of {canonical[0]}: {name!r}")
        if len(parts) == 1:
            if not _zip_member_is_directory(member):
                raise MetadataVerificationError("ZIP has an explicit non-directory or symlink GM2Godot.app ancestor")
            continue

        if _normalized_component(parts[1]) != normalized_canonical[1]:
            continue
        if parts[1] != canonical[1]:
            raise MetadataVerificationError(f"ZIP contains a case or Unicode alias of GM2Godot.app/Contents: {name!r}")
        if len(parts) == 2:
            if not _zip_member_is_directory(member):
                raise MetadataVerificationError("ZIP has an explicit non-directory or symlink Contents ancestor")
            continue

        if _normalized_component(parts[2]) != normalized_canonical[2]:
            continue
        if len(parts) != 3 or parts != canonical or name != ZIP_PLIST_PATH:
            raise MetadataVerificationError(f"ZIP contains a case or Unicode alias of {ZIP_PLIST_PATH}: {name!r}")
        matches.append(member)

    if len(matches) != 1:
        raise MetadataVerificationError(f"ZIP must contain exactly one {ZIP_PLIST_PATH}; found {len(matches)}")
    target = matches[0]
    target_type = _zip_member_type(target)
    if target.is_dir() or target_type == stat.S_IFLNK or target_type not in {0, stat.S_IFREG}:
        raise MetadataVerificationError("ZIP Info.plist is not a regular file")
    if target.flag_bits & 0x1:
        raise MetadataVerificationError("ZIP Info.plist is encrypted")
    if target.file_size > MAX_PLIST_BYTES:
        raise MetadataVerificationError(f"ZIP Info.plist exceeds the {MAX_PLIST_BYTES}-byte verification limit")
    return target


def inspect_zip(zip_path: Path, expected: Mapping[str, str]) -> BundleMetadata:
    fd: int | None = None
    try:
        try:
            fd = os.open(zip_path, _open_flags("O_CLOEXEC", "O_NOFOLLOW"))
            archive_stat = os.fstat(fd)
        except OSError as error:
            raise MetadataVerificationError(f"unable to open ZIP without following links: {error}") from error
        if not stat.S_ISREG(archive_stat.st_mode):
            raise MetadataVerificationError("ZIP is not a regular file")

        try:
            with os.fdopen(os.dup(fd), "rb") as stream, zipfile.ZipFile(stream) as archive:
                target = _select_zip_plist(archive.infolist())
                with archive.open(target) as plist_stream:
                    content = plist_stream.read(MAX_PLIST_BYTES + 1)
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
            raise MetadataVerificationError(f"unable to read ZIP: {error}") from error
        if len(content) != target.file_size:
            raise MetadataVerificationError("ZIP Info.plist size differs from its central-directory receipt")
        return _parse_bundle_plist(content, expected, "ZIP Info.plist")
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _read_command_output(stream: object, label: str) -> bytes:
    try:
        stream.seek(0)  # type: ignore[attr-defined]
        content = stream.read(MAX_HDIUTIL_OUTPUT_BYTES + 1)  # type: ignore[attr-defined]
    except OSError as error:
        raise MetadataVerificationError(f"unable to read {label} hdiutil output: {error}") from error
    if not isinstance(content, bytes):
        raise MetadataVerificationError(f"{label} hdiutil output was not bytes")
    if len(content) > MAX_HDIUTIL_OUTPUT_BYTES:
        raise MetadataVerificationError(f"{label} hdiutil output exceeds the bounded verification limit")
    return content


def _run_hdiutil_command(command: Sequence[str], label: str) -> _CommandResult:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    list(command),
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env=environment,
                    shell=False,
                    timeout=HDIUTIL_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as error:
                raise MetadataVerificationError(
                    f"{label} hdiutil command timed out after {HDIUTIL_TIMEOUT_SECONDS:g} seconds"
                ) from error
            except OSError as error:
                raise MetadataVerificationError(f"unable to run {label} hdiutil command: {error}") from error
            return _CommandResult(
                returncode=completed.returncode,
                stdout=_read_command_output(stdout, label),
                stderr=_read_command_output(stderr, label),
            )
    except MetadataVerificationError:
        raise
    except OSError as error:
        raise MetadataVerificationError(f"unable to prepare {label} hdiutil output capture: {error}") from error


def _receipt_entities(content: bytes, kind: str) -> list[dict[object, object]]:
    try:
        value = plistlib.loads(content)
    except (
        plistlib.InvalidFileException,
        ExpatError,
        ValueError,
        TypeError,
        OverflowError,
    ) as error:
        raise MetadataVerificationError(f"unable to parse hdiutil {kind} receipt: {error}") from error
    if type(value) is not dict:
        raise MetadataVerificationError(f"hdiutil {kind} receipt root must be a dictionary")
    receipt = cast(dict[object, object], value)
    entity_groups: list[object]
    if kind == "attach":
        entity_groups = [receipt.get("system-entities")]
    elif kind == "info":
        images_value = receipt.get("images")
        if type(images_value) is not list:
            raise MetadataVerificationError("hdiutil info receipt lacks an images list")
        entity_groups = []
        for image_value in cast(list[object], images_value):
            if type(image_value) is not dict:
                raise MetadataVerificationError("hdiutil info receipt contains a non-dictionary image")
            image = cast(dict[object, object], image_value)
            entity_groups.append(image.get("system-entities"))
    else:
        raise AssertionError(f"unsupported hdiutil receipt kind: {kind}")

    entities: list[dict[object, object]] = []
    for group in entity_groups:
        if type(group) is not list:
            raise MetadataVerificationError(f"hdiutil {kind} receipt lacks a system-entities list")
        for entity_value in cast(list[object], group):
            if type(entity_value) is not dict:
                raise MetadataVerificationError(f"hdiutil {kind} receipt contains a non-dictionary entity")
            entities.append(cast(dict[object, object], entity_value))
    return entities


def _receipt_device(content: bytes, kind: str, mountpoint: Path) -> str | None:
    matches: list[str] = []
    expected_mountpoint = os.fspath(mountpoint)
    for entity in _receipt_entities(content, kind):
        if entity.get("mount-point") != expected_mountpoint:
            continue
        device = entity.get("dev-entry")
        if type(device) is not str or not _DEVICE_PATTERN.fullmatch(device):
            raise MetadataVerificationError(f"hdiutil {kind} receipt has an invalid device for the exact mount point")
        matches.append(device)
    if len(matches) > 1:
        raise MetadataVerificationError(f"hdiutil {kind} receipt has multiple devices for the exact mount point")
    return matches[0] if matches else None


def _command_failure(label: str, result: _CommandResult) -> MetadataVerificationError:
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    detail = f": {stderr}" if stderr else ""
    return MetadataVerificationError(f"hdiutil {label} failed with status {result.returncode}{detail}")


def _create_private_mountpoint() -> tuple[Path, Path]:
    try:
        raw_root = Path(tempfile.mkdtemp(prefix="gm2godot-dmg-metadata-"))
    except OSError as error:
        raise MetadataVerificationError(f"unable to create private DMG verification directory: {error}") from error

    mountpoint: Path | None = None
    try:
        raw_stat = raw_root.lstat()
        if not stat.S_ISDIR(raw_stat.st_mode) or stat.S_ISLNK(raw_stat.st_mode):
            raise MetadataVerificationError(f"DMG verification root is not a physical directory: {raw_root}")
        root = raw_root.resolve(strict=True)
        os.chmod(root, 0o700)
        mountpoint = root / "mount"
        mountpoint.mkdir(mode=0o700)
        return root, mountpoint
    except (OSError, MetadataVerificationError) as error:
        cleanup_error: OSError | None = None
        try:
            if mountpoint is not None and mountpoint.exists():
                mountpoint.rmdir()
            raw_root.rmdir()
        except OSError as observed:
            cleanup_error = observed
        if isinstance(error, MetadataVerificationError):
            message = str(error)
        else:
            message = f"unable to prepare private DMG verification directory: {error}"
        if cleanup_error is not None:
            message += f"; retaining {raw_root}: {cleanup_error}"
        raise MetadataVerificationError(message) from error


def _remove_empty_mount_root(root: Path, mountpoint: Path) -> None:
    try:
        mountpoint.rmdir()
        root.rmdir()
    except OSError as error:
        raise MetadataVerificationError(
            f"unable to remove detached DMG verification directory; retaining {root}: {error}"
        ) from error


def _hdiutil_info_device(mountpoint: Path) -> str | None:
    result = _run_hdiutil_command((HDIUTIL_PATH, "info", "-plist"), "info")
    if result.returncode != 0:
        raise _command_failure("info", result)
    return _receipt_device(result.stdout, "info", mountpoint)


def _append_context(primary: MetadataVerificationError | None, cleanup: str) -> MetadataVerificationError:
    if primary is None:
        return MetadataVerificationError(cleanup)
    return MetadataVerificationError(f"{primary}; {cleanup}")


def inspect_dmg(dmg_path: Path, expected: Mapping[str, str]) -> BundleMetadata:
    try:
        fd = os.open(dmg_path, _open_flags("O_CLOEXEC", "O_NOFOLLOW"))
        try:
            dmg_stat = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise MetadataVerificationError(f"unable to open DMG without following links: {error}") from error
    if not stat.S_ISREG(dmg_stat.st_mode):
        raise MetadataVerificationError("DMG is not a regular file")

    root, mountpoint = _create_private_mountpoint()
    device: str | None = None
    known_unmounted = False
    primary_error: MetadataVerificationError | None = None
    metadata: BundleMetadata | None = None
    try:
        try:
            attach = _run_hdiutil_command(
                (
                    HDIUTIL_PATH,
                    "attach",
                    "-readonly",
                    "-nobrowse",
                    "-plist",
                    "-mountpoint",
                    os.fspath(mountpoint),
                    os.fspath(dmg_path),
                ),
                "attach",
            )
            try:
                device = _receipt_device(attach.stdout, "attach", mountpoint)
                if device is None:
                    primary_error = MetadataVerificationError(
                        "hdiutil attach receipt has no device for the exact mount point"
                    )
            except MetadataVerificationError as error:
                primary_error = error
            if attach.returncode != 0:
                primary_error = _command_failure("attach", attach)
        except MetadataVerificationError as error:
            primary_error = error

        # An attach may partially succeed even after a nonzero status, timeout, or
        # malformed receipt. Never infer safety from the command result alone.
        if device is None:
            try:
                device = _hdiutil_info_device(mountpoint)
                known_unmounted = device is None
            except MetadataVerificationError as error:
                primary_error = _append_context(
                    primary_error,
                    f"exact mounted device could not be recovered; retaining {root}: {error}",
                )

        if primary_error is None:
            if device is None:
                primary_error = MetadataVerificationError(
                    "hdiutil reported attach success but the exact mount point is not mounted"
                )
            else:
                content = _read_regular_beneath(
                    mountpoint,
                    APP_PLIST_COMPONENTS,
                    MAX_PLIST_BYTES,
                    "DMG Info.plist",
                )
                metadata = _parse_bundle_plist(content, expected, "DMG Info.plist")
    except MetadataVerificationError as error:
        primary_error = error
    finally:
        safe_to_clean = known_unmounted
        if device is not None:
            try:
                detach = _run_hdiutil_command((HDIUTIL_PATH, "detach", device), "detach")
                if detach.returncode != 0:
                    raise _command_failure("detach", detach)
                remaining_device = _hdiutil_info_device(mountpoint)
                if remaining_device is not None or os.path.ismount(mountpoint):
                    raise MetadataVerificationError(f"mount point remains attached to {remaining_device or device}")
                safe_to_clean = True
            except MetadataVerificationError as error:
                safe_to_clean = False
                primary_error = _append_context(
                    primary_error,
                    f"detach could not be confirmed for {device}; retaining {root}: {error}",
                )

        if safe_to_clean:
            try:
                _remove_empty_mount_root(root, mountpoint)
            except MetadataVerificationError as error:
                primary_error = _append_context(primary_error, str(error))

    if primary_error is not None:
        raise primary_error
    if metadata is None:
        raise MetadataVerificationError("DMG metadata verification produced no result")
    return metadata


def verify_artifacts(
    source_root: Path,
    app_path: Path,
    zip_path: Path,
    dmg_path: Path,
) -> BundleMetadata:
    expected = _load_policy(source_root)
    observations = (
        inspect_app(app_path, expected),
        inspect_zip(zip_path, expected),
        inspect_dmg(dmg_path, expected),
    )
    if len({observation.plist_sha256 for observation in observations}) != 1:
        raise MetadataVerificationError("direct app, ZIP, and DMG Info.plist bytes are not identical")
    return observations[0]


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify exact GM2Godot macOS bundle metadata across release artifacts."
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--dmg", required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _argument_parser().parse_args(arguments)
    try:
        metadata = verify_artifacts(
            _require_absolute_path(parsed.source_root, "source root"),
            _require_absolute_path(parsed.app, "direct app"),
            _require_absolute_path(parsed.zip, "ZIP"),
            _require_absolute_path(parsed.dmg, "DMG"),
        )
        print(
            "Verified identical macOS bundle metadata: "
            f"identifier={metadata.identifier} "
            f"version={metadata.short_version} "
            f"build={metadata.build_version} "
            f"plist_sha256={metadata.plist_sha256}"
        )
    except (MetadataVerificationError, OSError) as error:
        print(
            f"macOS bundle metadata verification failed: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
