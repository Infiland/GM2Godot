from __future__ import annotations

import argparse
import hashlib
import io
import os
import plistlib
import re
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, TracebackType
from typing import BinaryIO, Literal, Protocol, cast
from xml.parsers.expat import ExpatError

POLICY_COMPONENTS = ("packaging", "macos", "bundle_metadata.py")
APP_PLIST_COMPONENTS = ("GM2Godot.app", "Contents", "Info.plist")
ZIP_PLIST_PATH = "/".join(APP_PLIST_COMPONENTS)
POLICY_KEYS = frozenset(
    {
        "CFBundleIdentifier",
        "CFBundleShortVersionString",
        "CFBundleVersion",
        "LSMinimumSystemVersion",
    }
)
EXPECTED_MINIMUM_SYSTEM_VERSION = "15.0"
SUPPORTED_ARCHITECTURES = frozenset({"arm64", "x86_64"})
MAIN_EXECUTABLE_PATH = "Contents/MacOS/GM2Godot"
MAX_POLICY_BYTES = 256 * 1024
MAX_PLIST_BYTES = 1024 * 1024
MAX_HDIUTIL_OUTPUT_BYTES = 1024 * 1024
MAX_MACHO_LOAD_COMMAND_BYTES = 16 * 1024 * 1024
MAX_MACHO_LOAD_COMMANDS = 65_536
MAX_BUNDLE_ENTRIES = 100_000
MAX_BUNDLE_DEPTH = 128
MAX_SYMLINK_RESOLUTIONS = 256
MAX_SYMLINK_TARGET_BYTES = 16 * 1024
MAX_ZIP_BYTES = 1024 * 1024 * 1024
MAX_DMG_BYTES = 1024 * 1024 * 1024
MAX_ZIP_READ_BYTES = 32 * 1024 * 1024
COPY_READ_BYTES = 1024 * 1024
HDIUTIL_TIMEOUT_SECONDS = 120.0
HDIUTIL_PATH = "/usr/bin/hdiutil"

MH_EXECUTE = 0x2
LC_VERSION_MIN_MACOSX = 0x24
LC_VERSION_MIN_IPHONEOS = 0x25
LC_VERSION_MIN_TVOS = 0x2F
LC_VERSION_MIN_WATCHOS = 0x30
LC_BUILD_VERSION = 0x32
PLATFORM_MACOS = 0x1
VALID_MACHO_FILETYPES = frozenset(range(1, 13))

_MACHO_64_LE_MAGIC = b"\xcf\xfa\xed\xfe"
_UNSUPPORTED_THIN_MACHO_MAGICS = frozenset(
    {
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
    }
)
_FAT_MACHO_MAGICS = frozenset(
    {
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }
)
_CPU_TYPES = {
    0x0100000C: "arm64",
    0x01000007: "x86_64",
}
_CPU_SUBTYPES = {
    "arm64": 0,
    "x86_64": 3,
}
_MACH_HEADER_64 = struct.Struct("<IiiIIIII")
_LOAD_COMMAND_HEADER = struct.Struct("<II")
_VERSION_MIN_COMMAND = struct.Struct("<IIII")
_BUILD_VERSION_COMMAND = struct.Struct("<IIIIII")
_BUILD_TOOL_VERSION = struct.Struct("<II")

_BUNDLE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){2,}\Z")
_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_MINIMUM_SYSTEM_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?\Z")
_DEVICE_PATTERN = re.compile(r"/dev/disk[0-9]+(?:s[0-9]+)*\Z")
_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"[A-Za-z]:/")


class MetadataVerificationError(Exception):
    """A deterministic validation failure suitable for one-line CLI output."""


@dataclass(frozen=True)
class BundleMetadata:
    identifier: str
    short_version: str
    build_version: str
    minimum_system_version: str
    plist_sha256: str


MacOSVersion = tuple[int, int, int]


@dataclass(frozen=True, order=True)
class MachOFile:
    relative_path: str
    architecture: str
    minimum_macos: MacOSVersion
    filetype: int
    mode: int


@dataclass(frozen=True, order=True)
class BundleSymlink:
    relative_path: str
    target: str


@dataclass(frozen=True)
class BundleInventory:
    mach_o_files: tuple[MachOFile, ...]
    symlinks: tuple[BundleSymlink, ...]


@dataclass(frozen=True)
class VerificationReceipt:
    metadata: BundleMetadata
    architecture: str
    macho_count: int
    symlink_count: int
    maximum_macos: MacOSVersion


@dataclass(frozen=True)
class BundleInspection:
    """Metadata and native/link inventory; ordinary resource bytes are excluded."""

    metadata: BundleMetadata
    inventory: BundleInventory


@dataclass(frozen=True)
class _MachOHeader:
    architecture: str
    minimum_macos: MacOSVersion
    filetype: int


class _BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _DirectoryBinding:
    parent_fd: int | None
    name: str
    fd: int
    device: int
    inode: int


@dataclass
class _RetainedDirectories:
    path: Path
    description: str
    bindings: list[_DirectoryBinding]
    private_files: dict[str, os.stat_result]
    private_copy_sha256: str | None = None

    @property
    def fd(self) -> int:
        return self.bindings[-1].fd

    def __enter__(self) -> _RetainedDirectories:
        return self

    def __exit__(
        self, exception_type: type[BaseException] | None, primary: BaseException | None, traceback: TracebackType | None
    ) -> Literal[False]:
        self.close(primary)
        return False

    def close(self, primary: BaseException | None = None) -> None:
        bindings, self.bindings = self.bindings, []
        _close_descriptors(
            tuple((item.fd, f"{self.description} directory {item.name!r}") for item in reversed(bindings)), primary
        )


def _cleanup_note(primary: BaseException, message: str) -> None:
    primary.add_note(message if len(message) <= 512 else message[:509] + "...")


def _close_descriptors(descriptors: Sequence[tuple[int, str]], primary: BaseException | None = None) -> None:
    first = primary
    for descriptor, label in descriptors:
        try:
            os.close(descriptor)
        except BaseException as error:
            if first is None:
                first = error
            else:
                _cleanup_note(first, f"unable to close {label}: {error}")
    if primary is None and first is not None:
        raise first


def _verify_directory_bindings(owner: _RetainedDirectories) -> None:
    if not owner.bindings:
        raise MetadataVerificationError(f"{owner.description} retained directory owner is closed")
    try:
        for item in owner.bindings:
            opened = os.fstat(item.fd)
            named = (
                os.stat(item.name, dir_fd=item.parent_fd, follow_symlinks=False)
                if item.parent_fd is not None
                else opened
            )
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (item.device, item.inode)
                or not os.path.samestat(opened, named)
            ):
                raise MetadataVerificationError(f"{owner.description} directory binding {item.name!r} changed")
    except OSError as error:
        raise MetadataVerificationError(f"unable to recheck {owner.description} retained ancestry: {error}") from error


def _open_retained_directories(path: Path, description: str) -> _RetainedDirectories:
    path = _require_absolute_path(os.fspath(path), description)
    if any("\x00" in part for part in path.parts):
        raise MetadataVerificationError(f"invalid directory path for {description}")
    owner = _RetainedDirectories(path, description, [], {})
    try:
        parent_fd: int | None = None
        for name in (path.anchor, *path.parts[1:]):
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            descriptor = os.open(name, _open_flags("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"), dir_fd=parent_fd)
            try:
                opened = os.fstat(descriptor)
            except BaseException as error:
                _close_descriptors(((descriptor, description),), error)
                raise
            owner.bindings.append(_DirectoryBinding(parent_fd, name, descriptor, opened.st_dev, opened.st_ino))
            if not stat.S_ISDIR(before.st_mode) or not os.path.samestat(before, opened):
                raise MetadataVerificationError(f"{description} directory {name!r} changed or is not physical")
            parent_fd = descriptor
        _verify_directory_bindings(owner)
        return owner
    except OSError as error:
        translated = MetadataVerificationError(
            f"unable to open {description} physical ancestry without following links: {error}"
        )
        owner.close(translated)
        raise translated from error
    except BaseException as error:
        owner.close(error)
        raise


def _verify_regular_binding(
    parent_fd: int, name: str, before: os.stat_result, description: str, *, stable: bool = True
) -> None:
    after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(after.st_mode)
        or not os.path.samestat(before, after)
        or (stable and _stable_stat(before) != _stable_stat(after))
    ):
        raise MetadataVerificationError(f"{description} physical file binding changed")


@dataclass(frozen=True)
class _FdBinaryReader:
    fd: int

    def read(self, size: int = -1, /) -> bytes:
        if size < 0:
            raise MetadataVerificationError("unbounded native binary read is unavailable")
        return os.read(self.fd, min(size, COPY_READ_BYTES))


class _BoundedZipReader(io.RawIOBase):
    """Borrow a descriptor, fix EOF, and reject large reads before allocation."""

    def __init__(self, fd: int, initial_size: int, description: str) -> None:
        super().__init__()
        if not 0 < initial_size <= MAX_ZIP_BYTES:
            raise MetadataVerificationError(f"{description} exceeds its initial-size limit")
        if not hasattr(os, "pread"):
            raise MetadataVerificationError("positioned ZIP reads are unavailable")
        self._fd = fd
        self._size = initial_size
        self._position = 0
        self._description = description

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        if self.closed:
            raise ValueError("I/O operation on closed ZIP view")
        return self._position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self.tell()
        if whence == os.SEEK_SET:
            position = offset
        elif whence == os.SEEK_CUR:
            position = self._position + offset
        elif whence == os.SEEK_END:
            position = self._size + offset
        else:
            raise ValueError("invalid ZIP seek origin")
        if position < 0:
            raise OSError("invalid negative ZIP seek")
        self._position = position
        return position

    def read(self, size: int = -1, /) -> bytes:
        self.tell()
        remaining = max(0, self._size - self._position)
        requested = remaining if size < 0 else size
        if requested > MAX_ZIP_READ_BYTES:
            raise MetadataVerificationError(f"{self._description} ZIP read exceeds the {MAX_ZIP_READ_BYTES}-byte limit")
        expected = min(requested, remaining)
        content = bytearray()
        while len(content) < expected:
            chunk = os.pread(self._fd, min(COPY_READ_BYTES, expected - len(content)), self._position)
            if not chunk:
                raise MetadataVerificationError(f"{self._description} ZIP changed or is truncated")
            self._position += len(chunk)
            content.extend(chunk)
        return bytes(content)


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


def _stable_stat(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_expected_architecture(value: str) -> str:
    if value not in SUPPORTED_ARCHITECTURES:
        supported = ", ".join(sorted(SUPPORTED_ARCHITECTURES))
        raise MetadataVerificationError(f"expected architecture must be one of {supported}; got {value!r}")
    return value


def _parse_macos_version_text(value: str, description: str) -> MacOSVersion:
    if _MINIMUM_SYSTEM_VERSION_PATTERN.fullmatch(value) is None:
        raise MetadataVerificationError(f"{description} is not a canonical macOS version: {value!r}")
    parts = [int(part) for part in value.split(".")]
    if len(parts) == 2:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _unpack_macos_version(value: int) -> MacOSVersion:
    return value >> 16, (value >> 8) & 0xFF, value & 0xFF


def _format_macos_version(value: MacOSVersion) -> str:
    major, minor, patch = value
    if patch:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}"


def _read_exact(stream: _BinaryReader, size: int, description: str) -> bytes:
    content = bytearray()
    try:
        while len(content) < size:
            chunk = stream.read(size - len(content))
            if not chunk:
                break
            content.extend(chunk)
    except MetadataVerificationError:
        raise
    except (OSError, RuntimeError) as error:
        raise MetadataVerificationError(f"unable to read {description}: {error}") from error
    if len(content) != size:
        raise MetadataVerificationError(f"{description} is truncated; expected {size} bytes and read {len(content)}")
    return bytes(content)


def _parse_macho_stream(
    stream: _BinaryReader,
    file_size: int,
    expected_architecture: str,
    description: str,
) -> _MachOHeader | None:
    """Parse only the bounded Mach-O header and load-command table."""

    expected_architecture = _require_expected_architecture(expected_architecture)
    if file_size < 0:
        raise MetadataVerificationError(f"{description} has a negative file size")
    initial_size = min(file_size, 4)
    magic = _read_exact(stream, initial_size, description)
    if len(magic) < 4:
        return None
    if magic in _FAT_MACHO_MAGICS:
        raise MetadataVerificationError(
            f"{description} is a universal/fat Mach-O; expected thin {expected_architecture}"
        )
    if magic in _UNSUPPORTED_THIN_MACHO_MAGICS:
        raise MetadataVerificationError(f"{description} uses an unsupported 32-bit or byte-swapped Mach-O header")
    if magic != _MACHO_64_LE_MAGIC:
        return None
    if file_size < _MACH_HEADER_64.size:
        raise MetadataVerificationError(f"{description} has a truncated 64-bit Mach-O header")

    header_bytes = magic + _read_exact(
        stream,
        _MACH_HEADER_64.size - len(magic),
        f"{description} Mach-O header",
    )
    (
        _magic,
        cpu_type,
        cpu_subtype,
        filetype,
        command_count,
        command_bytes,
        _flags,
        _reserved,
    ) = _MACH_HEADER_64.unpack(header_bytes)
    architecture = _CPU_TYPES.get(cpu_type & 0xFFFFFFFF)
    if architecture is None:
        raise MetadataVerificationError(
            f"{description} has unknown 64-bit Mach-O CPU type 0x{cpu_type & 0xFFFFFFFF:08x}"
        )
    if architecture != expected_architecture:
        raise MetadataVerificationError(f"{description} is {architecture}; expected thin {expected_architecture}")
    expected_subtype = _CPU_SUBTYPES[architecture]
    if cpu_subtype & 0xFFFFFFFF != expected_subtype:
        raise MetadataVerificationError(
            f"{description} has unsupported {architecture} CPU subtype/capability "
            f"0x{cpu_subtype & 0xFFFFFFFF:08x}; expected 0x{expected_subtype:08x}"
        )
    if filetype not in VALID_MACHO_FILETYPES:
        raise MetadataVerificationError(f"{description} has unknown Mach-O filetype {filetype}")
    if command_count > MAX_MACHO_LOAD_COMMANDS:
        raise MetadataVerificationError(
            f"{description} has {command_count} load commands; limit is {MAX_MACHO_LOAD_COMMANDS}"
        )
    if command_bytes > MAX_MACHO_LOAD_COMMAND_BYTES:
        raise MetadataVerificationError(
            f"{description} load-command table exceeds the {MAX_MACHO_LOAD_COMMAND_BYTES}-byte limit"
        )
    if command_count > command_bytes // _LOAD_COMMAND_HEADER.size:
        raise MetadataVerificationError(f"{description} load-command count cannot fit in its declared table")
    if command_bytes > file_size - _MACH_HEADER_64.size:
        raise MetadataVerificationError(f"{description} has a truncated Mach-O load-command table")

    commands = _read_exact(stream, command_bytes, f"{description} Mach-O load-command table")
    offset = 0
    minimum_versions: list[MacOSVersion] = []
    for command_index in range(command_count):
        if len(commands) - offset < _LOAD_COMMAND_HEADER.size:
            raise MetadataVerificationError(f"{description} load command {command_index} has a truncated header")
        command, command_size = _LOAD_COMMAND_HEADER.unpack_from(commands, offset)
        if command_size < _LOAD_COMMAND_HEADER.size or command_size % 8:
            raise MetadataVerificationError(
                f"{description} load command {command_index} has invalid size {command_size}"
            )
        command_end = offset + command_size
        if command_end > len(commands):
            raise MetadataVerificationError(f"{description} load command {command_index} exceeds its declared table")
        command_content = commands[offset:command_end]
        if command == LC_VERSION_MIN_MACOSX:
            if command_size != _VERSION_MIN_COMMAND.size:
                raise MetadataVerificationError(f"{description} has a malformed LC_VERSION_MIN_MACOSX command")
            _command, _size, minimum, _sdk = _VERSION_MIN_COMMAND.unpack(command_content)
            minimum_versions.append(_unpack_macos_version(minimum))
        elif command in {
            LC_VERSION_MIN_IPHONEOS,
            LC_VERSION_MIN_TVOS,
            LC_VERSION_MIN_WATCHOS,
        }:
            raise MetadataVerificationError(f"{description} contains non-macOS legacy deployment command 0x{command:x}")
        elif command == LC_BUILD_VERSION:
            if command_size < _BUILD_VERSION_COMMAND.size:
                raise MetadataVerificationError(f"{description} has a truncated LC_BUILD_VERSION command")
            (
                _command,
                _size,
                platform,
                minimum,
                _sdk,
                tool_count,
            ) = _BUILD_VERSION_COMMAND.unpack_from(command_content)
            expected_command_size = _BUILD_VERSION_COMMAND.size + tool_count * _BUILD_TOOL_VERSION.size
            if command_size != expected_command_size:
                raise MetadataVerificationError(f"{description} has a malformed LC_BUILD_VERSION tool table")
            if platform != PLATFORM_MACOS:
                raise MetadataVerificationError(f"{description} targets Mach-O platform {platform}; expected macOS")
            minimum_versions.append(_unpack_macos_version(minimum))
        offset = command_end

    if offset != len(commands):
        raise MetadataVerificationError(f"{description} load-command table has {len(commands) - offset} trailing bytes")
    if len(minimum_versions) != 1:
        raise MetadataVerificationError(
            f"{description} must contain exactly one macOS deployment command; found {len(minimum_versions)}"
        )
    minimum_macos = minimum_versions[0]
    if minimum_macos == (0, 0, 0):
        raise MetadataVerificationError(f"{description} declares an invalid 0.0 macOS minimum")
    return _MachOHeader(architecture, minimum_macos, filetype)


def _record_bundle_path(
    relative_path: str,
    normalized_paths: dict[tuple[str, ...], str],
    description: str,
) -> None:
    parts = tuple(relative_path.split("/"))
    normalized = tuple(_normalized_component(part) for part in parts)
    for length in range(1, len(parts) + 1):
        normalized_prefix = normalized[:length]
        original_prefix = "/".join(parts[:length])
        previous = normalized_paths.get(normalized_prefix)
        if previous is not None and previous != original_prefix:
            raise MetadataVerificationError(
                f"{description} contains case or Unicode aliases: {previous!r} and {original_prefix!r}"
            )
        normalized_paths[normalized_prefix] = original_prefix


def _symlink_destination(
    relative_path: str,
    target: str,
    description: str,
) -> str:
    if (
        not target
        or "\x00" in target
        or "\\" in target
        or target.startswith("/")
        or _WINDOWS_DRIVE_PATH_PATTERN.match(target) is not None
    ):
        raise MetadataVerificationError(f"{description} symlink {relative_path!r} has unsafe target {target!r}")
    try:
        target_bytes = target.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise MetadataVerificationError(
            f"{description} symlink {relative_path!r} target is not valid Unicode"
        ) from error
    if len(target_bytes) > MAX_SYMLINK_TARGET_BYTES:
        raise MetadataVerificationError(f"{description} symlink {relative_path!r} exceeds the target-size limit")

    resolved = relative_path.split("/")[:-1]
    for component in target.split("/"):
        if not component or component == ".":
            if not component:
                raise MetadataVerificationError(f"{description} symlink {relative_path!r} has unsafe target {target!r}")
            continue
        if component == "..":
            if not resolved:
                raise MetadataVerificationError(f"{description} symlink {relative_path!r} escapes the app bundle")
            resolved.pop()
        else:
            resolved.append(component)
    if not resolved:
        raise MetadataVerificationError(f"{description} symlink {relative_path!r} resolves to the app root")
    return "/".join(resolved)


def _validate_symlinks(
    symlinks: Sequence[BundleSymlink],
    available_paths: set[str],
    description: str,
) -> None:
    targets = {symlink.relative_path: symlink.target for symlink in symlinks}
    for symlink in symlinks:
        destination = _symlink_destination(
            symlink.relative_path,
            symlink.target,
            description,
        )
        visited: set[str] = set()
        while True:
            parts = destination.split("/")
            matched_path: str | None = None
            matched_length = 0
            for index in range(1, len(parts) + 1):
                candidate = "/".join(parts[:index])
                if candidate in targets:
                    matched_path = candidate
                    matched_length = index
                    break
            if matched_path is None:
                break
            if matched_path in visited:
                raise MetadataVerificationError(
                    f"{description} symlink {symlink.relative_path!r} enters a cycle at {matched_path!r}"
                )
            if len(visited) >= MAX_SYMLINK_RESOLUTIONS:
                raise MetadataVerificationError(
                    f"{description} symlink {symlink.relative_path!r} exceeds the "
                    f"{MAX_SYMLINK_RESOLUTIONS}-link resolution limit"
                )
            visited.add(matched_path)
            resolved_prefix = _symlink_destination(
                matched_path,
                targets[matched_path],
                description,
            )
            resolved_parts = [*resolved_prefix.split("/"), *parts[matched_length:]]
            if len(resolved_parts) > MAX_BUNDLE_DEPTH:
                raise MetadataVerificationError(
                    f"{description} symlink {symlink.relative_path!r} exceeds the "
                    f"{MAX_BUNDLE_DEPTH}-component resolution limit"
                )
            destination = "/".join(resolved_parts)
        if destination not in available_paths or destination in targets:
            raise MetadataVerificationError(
                f"{description} symlink {symlink.relative_path!r} has missing target {symlink.target!r}"
            )


def _finalize_bundle_inventory(
    macho_files: Sequence[MachOFile],
    symlinks: Sequence[BundleSymlink],
    available_paths: set[str],
    description: str,
) -> BundleInventory:
    _validate_symlinks(symlinks, available_paths, description)
    ordered_macho = tuple(sorted(macho_files))
    ordered_symlinks = tuple(sorted(symlinks))
    if not ordered_macho:
        raise MetadataVerificationError(f"{description} contains no Mach-O files")
    main_executables = [item for item in ordered_macho if item.relative_path == MAIN_EXECUTABLE_PATH]
    if len(main_executables) != 1:
        raise MetadataVerificationError(
            f"{description} must contain one physical Mach-O main executable at {MAIN_EXECUTABLE_PATH}"
        )
    if main_executables[0].filetype != MH_EXECUTE:
        raise MetadataVerificationError(
            f"{description} main Mach-O has filetype {main_executables[0].filetype}; expected MH_EXECUTE ({MH_EXECUTE})"
        )
    if not main_executables[0].mode & 0o111:
        raise MetadataVerificationError(f"{description} main Mach-O at {MAIN_EXECUTABLE_PATH} is not executable")
    return BundleInventory(ordered_macho, ordered_symlinks)


def _inspect_directory_inventory_at(root_fd: int, expected_architecture: str, description: str) -> BundleInventory:
    expected_architecture = _require_expected_architecture(expected_architecture)
    normalized_paths: dict[tuple[str, ...], str] = {}
    available_paths: set[str] = set()
    macho_files: list[MachOFile] = []
    symlinks: list[BundleSymlink] = []
    entry_count = 0
    before_root = os.fstat(root_fd)
    if not stat.S_ISDIR(before_root.st_mode):
        raise MetadataVerificationError(f"{description} is not a directory")

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal entry_count
        try:
            with os.scandir(directory_fd) as iterator:
                entries: list[os.DirEntry[str]] = []
                for item in iterator:
                    entry_count += 1
                    if entry_count > MAX_BUNDLE_ENTRIES:
                        raise MetadataVerificationError(f"{description} exceeds the {MAX_BUNDLE_ENTRIES}-entry limit")
                    entries.append(item)
                entries.sort(key=lambda item: item.name)
        except OSError as error:
            raise MetadataVerificationError(f"unable to enumerate {description}: {error}") from error
        for entry in entries:
            name = entry.name
            if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                raise MetadataVerificationError(f"{description} has an unsafe entry name: {name!r}")
            parts = (*prefix, name)
            if len(parts) > MAX_BUNDLE_DEPTH:
                raise MetadataVerificationError(f"{description} exceeds the {MAX_BUNDLE_DEPTH}-component depth limit")
            relative_path = "/".join(parts)
            _record_bundle_path(relative_path, normalized_paths, description)
            available_paths.add(relative_path)
            try:
                listed_inode = entry.inode()
                status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise MetadataVerificationError(
                    f"unable to inspect {description} entry {relative_path!r}: {error}"
                ) from error
            if status.st_ino != listed_inode:
                raise MetadataVerificationError(f"{description} entry {relative_path!r} changed after enumeration")
            if stat.S_ISDIR(status.st_mode):
                try:
                    child_fd = os.open(
                        name,
                        _open_flags("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"),
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    raise MetadataVerificationError(
                        f"unable to open {description} directory {relative_path!r}: {error}"
                    ) from error
                directory_error: BaseException | None = None
                try:
                    opened_directory = os.fstat(child_fd)
                    if not stat.S_ISDIR(opened_directory.st_mode) or not os.path.samestat(status, opened_directory):
                        raise MetadataVerificationError(
                            f"{description} directory {relative_path!r} changed while opening"
                        )
                    visit(child_fd, parts)
                    after_directory = os.stat(
                        name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    if _stable_stat(opened_directory) != _stable_stat(os.fstat(child_fd)) or not os.path.samestat(
                        opened_directory, after_directory
                    ):
                        raise MetadataVerificationError(
                            f"{description} directory {relative_path!r} changed during inspection"
                        )
                except BaseException as error:
                    directory_error = error
                    raise
                finally:
                    try:
                        os.close(child_fd)
                    except BaseException as cleanup_error:
                        if directory_error is not None:
                            _cleanup_note(
                                directory_error, f"unable to close directory {relative_path!r}: {cleanup_error}"
                            )
                        else:
                            raise
            elif stat.S_ISREG(status.st_mode):
                try:
                    file_fd = os.open(
                        name,
                        _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"),
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    raise MetadataVerificationError(
                        f"unable to open {description} file {relative_path!r}: {error}"
                    ) from error
                file_error: BaseException | None = None
                try:
                    observed = os.fstat(file_fd)
                    if not stat.S_ISREG(observed.st_mode) or not os.path.samestat(status, observed):
                        raise MetadataVerificationError(
                            f"{description} entry {relative_path!r} changed type during inspection"
                        )
                    parsed = _parse_macho_stream(
                        _FdBinaryReader(file_fd),
                        observed.st_size,
                        expected_architecture,
                        f"{description} file {relative_path!r}",
                    )
                    observed_after = os.fstat(file_fd)
                    path_after = os.stat(
                        name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    if _stable_stat(observed) != _stable_stat(observed_after) or not os.path.samestat(
                        observed_after, path_after
                    ):
                        raise MetadataVerificationError(
                            f"{description} file {relative_path!r} changed during inspection"
                        )
                except BaseException as error:
                    file_error = error
                    raise
                finally:
                    try:
                        os.close(file_fd)
                    except BaseException as cleanup_error:
                        if file_error is not None:
                            _cleanup_note(file_error, f"unable to close file {relative_path!r}: {cleanup_error}")
                        else:
                            raise
                if parsed is not None:
                    macho_files.append(
                        MachOFile(
                            relative_path,
                            parsed.architecture,
                            parsed.minimum_macos,
                            parsed.filetype,
                            stat.S_IMODE(observed.st_mode),
                        )
                    )
            elif stat.S_ISLNK(status.st_mode):
                try:
                    target = os.readlink(name, dir_fd=directory_fd)
                    symlink_after = os.stat(
                        name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise MetadataVerificationError(
                        f"unable to read {description} symlink {relative_path!r}: {error}"
                    ) from error
                if (
                    not stat.S_ISLNK(symlink_after.st_mode)
                    or not os.path.samestat(status, symlink_after)
                    or status.st_mtime_ns != symlink_after.st_mtime_ns
                    or status.st_ctime_ns != symlink_after.st_ctime_ns
                ):
                    raise MetadataVerificationError(
                        f"{description} symlink {relative_path!r} changed during inspection"
                    )
                symlinks.append(BundleSymlink(relative_path, target))
            else:
                raise MetadataVerificationError(
                    f"{description} contains unsupported filesystem entry {relative_path!r}"
                )

    visit(root_fd, ())
    if _stable_stat(before_root) != _stable_stat(os.fstat(root_fd)):
        raise MetadataVerificationError(f"{description} root changed during inspection")
    return _finalize_bundle_inventory(macho_files, symlinks, available_paths, description)


def _inspect_directory_inventory(app_path: Path | int, expected_architecture: str, description: str) -> BundleInventory:
    if isinstance(app_path, int):
        return _inspect_directory_inventory_at(app_path, expected_architecture, description)
    with _open_retained_directories(app_path, description) as owner:
        inventory = _inspect_directory_inventory_at(owner.fd, expected_architecture, description)
        _verify_directory_bindings(owner)
        return inventory


def _inspect_app_at(
    app_fd: int, expected: Mapping[str, str], expected_architecture: str, description: str
) -> tuple[BundleMetadata, BundleInventory]:
    content = _read_regular_at(app_fd, APP_PLIST_COMPONENTS[1:], MAX_PLIST_BYTES, f"{description} Info.plist")
    metadata = _parse_bundle_plist(content, expected, f"{description} Info.plist")
    inventory = _inspect_directory_inventory(app_fd, expected_architecture, description)
    return metadata, inventory


def _read_regular_at(root_fd: int, components: Sequence[str], maximum_bytes: int, description: str) -> bytes:
    if not components or any(not part or part in {".", ".."} or "/" in part or "\x00" in part for part in components):
        raise MetadataVerificationError(f"invalid fixed path for {description}")
    descriptors: list[tuple[int, str]] = []
    root_status = os.fstat(root_fd)
    bindings = [_DirectoryBinding(None, "borrowed root", root_fd, root_status.st_dev, root_status.st_ino)]
    primary: BaseException | None = None
    try:
        current = root_fd
        for name in components[:-1]:
            before_directory = os.stat(name, dir_fd=current, follow_symlinks=False)
            child = os.open(name, _open_flags("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW"), dir_fd=current)
            descriptors.append((child, f"{description} directory {name!r}"))
            observed = os.fstat(child)
            bindings.append(_DirectoryBinding(current, name, child, observed.st_dev, observed.st_ino))
            if not stat.S_ISDIR(before_directory.st_mode) or not os.path.samestat(before_directory, observed):
                raise MetadataVerificationError(f"{description} directory {name!r} changed")
            current = child
        name = components[-1]
        named = os.stat(name, dir_fd=current, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode):
            raise MetadataVerificationError(f"{description} is not a physical regular file")
        file_fd = os.open(name, _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"), dir_fd=current)
        descriptors.append((file_fd, description))
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or not os.path.samestat(named, before):
            raise MetadataVerificationError(f"{description} is not one physical regular file")
        if before.st_size > maximum_bytes:
            raise MetadataVerificationError(f"{description} exceeds the {maximum_bytes}-byte verification limit")
        content = _read_fd_bounded(file_fd, maximum_bytes, description)
        if len(content) != before.st_size or _stable_stat(before) != _stable_stat(os.fstat(file_fd)):
            raise MetadataVerificationError(f"{description} changed while reading")
        _verify_regular_binding(current, name, before, description)
        _verify_directory_bindings(_RetainedDirectories(Path("/"), description, bindings, {}))
        return content
    except OSError as error:
        translated = MetadataVerificationError(f"unable to read {description} without following links: {error}")
        primary = translated
        raise translated from error
    except BaseException as error:
        primary = error
        raise
    finally:
        _close_descriptors(tuple(reversed(descriptors)), primary)


def _read_regular_beneath(root: Path, components: Sequence[str], maximum_bytes: int, description: str) -> bytes:
    with _open_retained_directories(root, description) as owner:
        content = _read_regular_at(owner.fd, components, maximum_bytes, description)
        _verify_directory_bindings(owner)
        return content


def _load_policy_at(source_root: Path) -> dict[str, str]:
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
        raise MetadataVerificationError("bundle metadata policy must return exactly the four required Info.plist keys")
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
    minimum_system_version = policy["LSMinimumSystemVersion"]
    if minimum_system_version != EXPECTED_MINIMUM_SYSTEM_VERSION:
        raise MetadataVerificationError(
            "bundle metadata policy LSMinimumSystemVersion must be the reviewed exact value "
            f"{EXPECTED_MINIMUM_SYSTEM_VERSION!r}; got {minimum_system_version!r}"
        )
    _parse_macos_version_text(
        minimum_system_version,
        "bundle metadata policy LSMinimumSystemVersion",
    )
    return policy


def _load_policy(source_root: Path) -> dict[str, str]:
    with _open_retained_directories(source_root, "source metadata policy") as owner:
        policy = _load_policy_at(source_root)
        _verify_directory_bindings(owner)
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
        minimum_system_version=observed["LSMinimumSystemVersion"],
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
    if member.create_system != 3:
        raise MetadataVerificationError(f"ZIP app member {member.orig_filename!r} lacks reviewed Unix creator metadata")
    return stat.S_IFMT((member.external_attr >> 16) & 0xFFFF)


def _zip_member_is_directory(member: zipfile.ZipInfo) -> bool:
    member_type = _zip_member_type(member)
    return member_type == stat.S_IFDIR or (member_type == 0 and member.is_dir())


def _zip_member_parts(member: zipfile.ZipInfo) -> tuple[str, tuple[str, ...]]:
    name = member.orig_filename
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or _WINDOWS_DRIVE_PATH_PATTERN.match(name) is not None
    ):
        raise MetadataVerificationError(f"ZIP contains an unsafe member path: {name!r}")
    stripped = name[:-1] if name.endswith("/") else name
    parts = tuple(stripped.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise MetadataVerificationError(f"ZIP contains an unsafe member path: {name!r}")
    return name, parts


def _select_zip_plist(members: Sequence[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    """Select the exact plist and validate only paths that can alias its ancestors."""

    canonical = APP_PLIST_COMPONENTS
    normalized_canonical = tuple(_normalized_component(item) for item in canonical)
    matches: list[zipfile.ZipInfo] = []
    for member in members:
        name, parts = _zip_member_parts(member)
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


def _inspect_zip_inventory(
    archive: zipfile.ZipFile,
    members: Sequence[zipfile.ZipInfo],
    expected_architecture: str,
) -> BundleInventory:
    expected_architecture = _require_expected_architecture(expected_architecture)
    if len(members) > MAX_BUNDLE_ENTRIES:
        raise MetadataVerificationError(f"ZIP exceeds the {MAX_BUNDLE_ENTRIES}-member verification limit")

    app_name = APP_PLIST_COMPONENTS[0]
    normalized_app_name = _normalized_component(app_name)
    seen_archive_paths: set[str] = set()
    seen_logical_paths: dict[tuple[str, ...], str] = {}
    normalized_paths: dict[tuple[str, ...], str] = {}
    app_members: list[tuple[zipfile.ZipInfo, str, str]] = []
    entry_types: dict[str, str] = {}
    available_paths: set[str] = set()

    for member in members:
        name, parts = _zip_member_parts(member)
        if name in seen_archive_paths:
            raise MetadataVerificationError(f"ZIP contains duplicate member path {name!r}")
        seen_archive_paths.add(name)
        previous_logical = seen_logical_paths.get(parts)
        if previous_logical is not None:
            raise MetadataVerificationError(
                f"ZIP contains duplicate logical member paths {previous_logical!r} and {name!r}"
            )
        seen_logical_paths[parts] = name
        if _normalized_component(parts[0]) != normalized_app_name:
            continue
        if parts[0] != app_name:
            raise MetadataVerificationError(f"ZIP contains a case or Unicode alias of {app_name}: {name!r}")

        relative_parts = parts[1:]
        if len(relative_parts) > MAX_BUNDLE_DEPTH:
            raise MetadataVerificationError(f"ZIP app exceeds the {MAX_BUNDLE_DEPTH}-component depth limit")
        member_type = _zip_member_type(member)
        if member_type == 0:
            raise MetadataVerificationError(f"ZIP app member {name!r} lacks an explicit Unix file type")
        if _zip_member_is_directory(member):
            kind = "directory"
        elif member_type == stat.S_IFLNK:
            kind = "symlink"
        elif member_type in {0, stat.S_IFREG} and not member.is_dir():
            kind = "regular"
        else:
            raise MetadataVerificationError(f"ZIP app contains unsupported member type at {name!r}")
        if member.flag_bits & 0x1:
            raise MetadataVerificationError(f"ZIP app member {member.orig_filename!r} is encrypted")
        if not relative_parts:
            if kind != "directory":
                raise MetadataVerificationError("ZIP has a non-directory GM2Godot.app root")
            continue

        relative_path = "/".join(relative_parts)
        _record_bundle_path(relative_path, normalized_paths, "ZIP app")
        if relative_path in entry_types:
            raise MetadataVerificationError(f"ZIP app contains duplicate member path {relative_path!r}")
        entry_types[relative_path] = kind
        for index in range(1, len(relative_parts) + 1):
            available_paths.add("/".join(relative_parts[:index]))
        app_members.append((member, relative_path, kind))

    for relative_path in sorted(entry_types):
        parts = relative_path.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            ancestor_type = entry_types.get(ancestor)
            if ancestor_type in {"regular", "symlink"}:
                raise MetadataVerificationError(
                    f"ZIP app member {relative_path!r} descends through {ancestor_type} ancestor {ancestor!r}"
                )

    macho_files: list[MachOFile] = []
    symlinks: list[BundleSymlink] = []
    for member, relative_path, kind in app_members:
        if kind == "directory":
            continue
        if kind == "symlink":
            if member.file_size > MAX_SYMLINK_TARGET_BYTES:
                raise MetadataVerificationError(f"ZIP app symlink {relative_path!r} exceeds the target-size limit")
            with archive.open(member) as target_stream:
                target_bytes = _read_exact(
                    target_stream,
                    member.file_size,
                    f"ZIP app symlink {relative_path!r}",
                )
            try:
                target = target_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise MetadataVerificationError(f"ZIP app symlink {relative_path!r} target is not UTF-8") from error
            symlinks.append(BundleSymlink(relative_path, target))
            continue

        with archive.open(member) as file_stream:
            parsed = _parse_macho_stream(
                file_stream,
                member.file_size,
                expected_architecture,
                f"ZIP app file {relative_path!r}",
            )
        if parsed is not None:
            macho_files.append(
                MachOFile(
                    relative_path,
                    parsed.architecture,
                    parsed.minimum_macos,
                    parsed.filetype,
                    stat.S_IMODE((member.external_attr >> 16) & 0xFFFF),
                )
            )

    return _finalize_bundle_inventory(
        macho_files,
        symlinks,
        available_paths,
        "ZIP app",
    )


def _inspect_zip_contents(
    zip_path: Path, expected: Mapping[str, str], expected_architecture: str | None
) -> tuple[BundleMetadata, BundleInventory | None]:
    with _open_retained_directories(zip_path.parent, "ZIP parent") as owner:
        fd = -1
        primary: BaseException | None = None
        try:
            named = os.stat(zip_path.name, dir_fd=owner.fd, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode):
                raise MetadataVerificationError("ZIP is not a physical regular file")
            fd = os.open(zip_path.name, _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"), dir_fd=owner.fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or not os.path.samestat(named, before):
                raise MetadataVerificationError("ZIP is not one physical regular file")
            with _BoundedZipReader(fd, before.st_size, "ZIP") as stream:
                with zipfile.ZipFile(cast(BinaryIO, stream)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_BUNDLE_ENTRIES:
                        raise MetadataVerificationError("ZIP exceeds the member verification limit")
                    target = _select_zip_plist(members)
                    with archive.open(target) as plist_stream:
                        content = plist_stream.read(MAX_PLIST_BYTES + 1)
                    inventory = (
                        _inspect_zip_inventory(archive, members, expected_architecture)
                        if expected_architecture is not None
                        else None
                    )
            if len(content) != target.file_size:
                raise MetadataVerificationError("ZIP Info.plist size differs from its central-directory receipt")
            if _stable_stat(before) != _stable_stat(os.fstat(fd)):
                raise MetadataVerificationError("ZIP changed while reading")
            _verify_regular_binding(owner.fd, zip_path.name, before, "ZIP")
            _verify_directory_bindings(owner)
            return _parse_bundle_plist(content, expected, "ZIP Info.plist"), inventory
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile, UnicodeError) as error:
            translated = MetadataVerificationError(f"unable to read ZIP: {error}")
            primary = translated
            raise translated from error
        except BaseException as error:
            primary = error
            raise
        finally:
            if fd >= 0:
                _close_descriptors(((fd, "ZIP"),), primary)


def inspect_zip(zip_path: Path, expected: Mapping[str, str]) -> BundleMetadata:
    metadata, _inventory = _inspect_zip_contents(zip_path, expected, None)
    return metadata


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


def _close_streams(streams: Sequence[tuple[BinaryIO, str]], primary: BaseException | None) -> None:
    first = primary
    for stream, label in streams:
        try:
            stream.close()
        except BaseException as error:
            if first is None:
                first = error
            else:
                _cleanup_note(first, f"unable to close {label}: {error}")
    if primary is None and first is not None:
        raise first


def _run_hdiutil_command(command: Sequence[str], label: str) -> _CommandResult:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    stdout: BinaryIO | None = None
    stderr: BinaryIO | None = None
    primary: BaseException | None = None
    try:
        stdout = tempfile.TemporaryFile()
        stderr = tempfile.TemporaryFile()
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
            completed.returncode, _read_command_output(stdout, label), _read_command_output(stderr, label)
        )
    except OSError as error:
        translated = MetadataVerificationError(f"unable to prepare {label} hdiutil output capture: {error}")
        primary = translated
        raise translated from error
    except BaseException as error:
        primary = error
        raise
    finally:
        streams = tuple(
            (stream, name)
            for stream, name in ((stderr, f"{label} stderr"), (stdout, f"{label} stdout"))
            if stream is not None
        )
        _close_streams(streams, primary)


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


def _create_private_mountpoint() -> tuple[_RetainedDirectories, Path]:
    owner: _RetainedDirectories | None = None
    mount_created = False
    root_bound = False
    raw_root: Path | None = None
    try:
        raw_root = Path(tempfile.mkdtemp(prefix="gm2godot-dmg-metadata-"))
        original = raw_root.lstat()
        if not stat.S_ISDIR(original.st_mode):
            raise MetadataVerificationError("DMG verification root is not a physical directory")
        # Resolve only the freshly created owned root's system-temp aliases,
        # then bind its original identity before mutating any resolved path.
        root = raw_root.resolve(strict=True)
        owner = _open_retained_directories(root, "private DMG root")
        if not os.path.samestat(original, os.fstat(owner.fd)):
            raise MetadataVerificationError("DMG verification root changed during physical binding")
        root_bound = True
        os.fchmod(owner.fd, 0o700)
        _verify_directory_bindings(owner)
        os.mkdir("mount", mode=0o700, dir_fd=owner.fd)
        mount_created = True
        owner.private_files["mount"] = os.stat("mount", dir_fd=owner.fd, follow_symlinks=False)
        _verify_directory_bindings(owner)
        return owner, root / "mount"
    except BaseException as error:
        primary: BaseException = error
        if isinstance(error, OSError):
            primary = MetadataVerificationError(f"unable to prepare private DMG verification directory: {error}")
        if owner is not None and root_bound:
            try:
                _verify_directory_bindings(owner)
                if mount_created:
                    expected = owner.private_files.get("mount")
                    current = os.stat("mount", dir_fd=owner.fd, follow_symlinks=False)
                    if expected is None or not stat.S_ISDIR(current.st_mode) or not os.path.samestat(expected, current):
                        raise MetadataVerificationError("DMG setup mountpoint ownership is unconfirmed")
                    os.rmdir("mount", dir_fd=owner.fd)
                _verify_directory_bindings(owner)
                leaf = owner.bindings[-1]
                os.rmdir(leaf.name, dir_fd=leaf.parent_fd)
            except BaseException as cleanup_error:
                _cleanup_note(primary, f"retaining private DMG setup root {raw_root}: {cleanup_error}")
        elif raw_root is not None:
            _cleanup_note(primary, f"retaining unbound private DMG setup root: {raw_root}")
        if owner is not None:
            owner.close(primary)
        if primary is error:
            raise
        raise primary from error


def _remove_private_dmg_root(
    root: Path, mountpoint: Path, private_dmg: Path, *, owner: _RetainedDirectories | None = None
) -> None:
    if mountpoint != root / "mount" or private_dmg != root / "source.dmg":
        raise MetadataVerificationError("private DMG cleanup paths are not canonical")
    if owner is None:
        with _open_retained_directories(root, "private DMG cleanup root") as retained:
            # Standalone cleanup can remove only the observed physical candidate.
            try:
                retained.private_files["source.dmg"] = os.stat("source.dmg", dir_fd=retained.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            retained.private_files["mount"] = os.stat("mount", dir_fd=retained.fd, follow_symlinks=False)
            return _remove_private_dmg_root(root, mountpoint, private_dmg, owner=retained)
    if owner.path != root:
        raise MetadataVerificationError("private DMG cleanup owner does not match its root")
    _verify_directory_bindings(owner)
    failures: list[BaseException] = []
    copy_removed = False
    mount_removed = False
    try:
        expected_copy = owner.private_files.get("source.dmg")
        if expected_copy is not None:
            _verify_regular_binding(owner.fd, "source.dmg", expected_copy, "private DMG cleanup copy", stable=False)
            current_copy = os.stat("source.dmg", dir_fd=owner.fd, follow_symlinks=False)
            if current_copy.st_nlink != 1 or stat.S_IMODE(current_copy.st_mode) != 0o600:
                raise MetadataVerificationError("private DMG cleanup copy lost its owned mode/link state")
            os.unlink("source.dmg", dir_fd=owner.fd)
        else:
            try:
                os.stat("source.dmg", dir_fd=owner.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise MetadataVerificationError("unowned file appeared at private DMG cleanup path")
        copy_removed = True
    except BaseException as error:
        failures.append(error)
    try:
        _verify_directory_bindings(owner)
        expected_mount = owner.private_files["mount"]
        current_mount = os.stat("mount", dir_fd=owner.fd, follow_symlinks=False)
        if not stat.S_ISDIR(current_mount.st_mode) or not os.path.samestat(expected_mount, current_mount):
            raise MetadataVerificationError("private DMG mountpoint binding changed")
        os.rmdir("mount", dir_fd=owner.fd)
        mount_removed = True
    except BaseException as error:
        failures.append(error)
    if copy_removed and mount_removed:
        try:
            _verify_directory_bindings(owner)
            leaf = owner.bindings[-1]
            os.rmdir(leaf.name, dir_fd=leaf.parent_fd)
        except BaseException as error:
            failures.append(error)
    if failures:
        first = failures[0]
        for later in failures[1:]:
            _cleanup_note(first, f"additional private cleanup failure: {later}")
        _cleanup_note(
            first,
            f"private DMG copy {'was already removed' if copy_removed else 'remains'}; cleanup root remains at {root}",
        )
        raise first


def _hdiutil_info_device(mountpoint: Path) -> str | None:
    result = _run_hdiutil_command((HDIUTIL_PATH, "info", "-plist"), "info")
    if result.returncode != 0:
        raise _command_failure("info", result)
    return _receipt_device(result.stdout, "info", mountpoint)


def _copy_bound_dmg(source: Path, root: Path, *, owner: _RetainedDirectories | None = None) -> Path:
    """Copy exactly one initial descriptor size into a retained private directory."""
    if owner is None:
        with _open_retained_directories(root, "private DMG root") as retained:
            return _copy_bound_dmg(source, root, owner=retained)
    if owner.path != root:
        raise MetadataVerificationError("private DMG copy owner does not match its root")
    _verify_directory_bindings(owner)
    owner.private_copy_sha256 = None
    destination = root / "source.dmg"
    with _open_retained_directories(source.parent, "source DMG parent") as source_owner:
        source_fd = -1
        destination_fd = -1
        primary: BaseException | None = None
        try:
            named = os.stat(source.name, dir_fd=source_owner.fd, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode):
                raise MetadataVerificationError("DMG is not a physical regular file")
            source_fd = os.open(
                source.name, _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"), dir_fd=source_owner.fd
            )
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not os.path.samestat(named, before):
                raise MetadataVerificationError("DMG is not one physical regular file")
            if not 0 < before.st_size <= MAX_DMG_BYTES:
                raise MetadataVerificationError(f"DMG exceeds the {MAX_DMG_BYTES}-byte initial-size limit")
            destination_fd = os.open(
                "source.dmg",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"),
                0o600,
                dir_fd=owner.fd,
            )
            owner.private_files["source.dmg"] = os.fstat(destination_fd)
            copied_digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(source_fd, min(COPY_READ_BYTES, remaining))
                if not chunk:
                    raise MetadataVerificationError("DMG shrank during its initial-size copy")
                remaining -= len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_fd, view)
                    if written <= 0:
                        raise OSError("short write while copying bound DMG")
                    view = view[written:]
                copied_digest.update(chunk)
            if os.read(source_fd, 1):
                raise MetadataVerificationError("DMG grew during its initial-size copy")
            os.fchmod(destination_fd, 0o600)
            os.fsync(destination_fd)
            if _stable_stat(before) != _stable_stat(os.fstat(source_fd)):
                raise MetadataVerificationError("DMG changed while its bound descriptor was copied")
            _verify_regular_binding(source_owner.fd, source.name, before, "DMG")
            copied = os.fstat(destination_fd)
            if (
                not stat.S_ISREG(copied.st_mode)
                or copied.st_nlink != 1
                or copied.st_size != before.st_size
                or stat.S_IMODE(copied.st_mode) != 0o600
            ):
                raise MetadataVerificationError("private DMG copy failed its sealed-file checks")
            _verify_regular_binding(owner.fd, "source.dmg", copied, "private DMG copy")
            _verify_directory_bindings(source_owner)
            _verify_directory_bindings(owner)
            owner.private_files["source.dmg"] = copied
            owner.private_copy_sha256 = copied_digest.hexdigest()
            return destination
        except OSError as error:
            translated = MetadataVerificationError(f"unable to create stable private DMG copy: {error}")
            primary = translated
            raise translated from error
        except BaseException as error:
            primary = error
            raise
        finally:
            descriptors = tuple(
                (fd, label)
                for fd, label in ((destination_fd, "private DMG copy"), (source_fd, "source DMG"))
                if fd >= 0
            )
            _close_descriptors(descriptors, primary)


def _verify_attached_private_dmg(owner: _RetainedDirectories) -> None:
    """Allow attach-only ctime drift while reauthenticating the owned snapshot."""
    sealed = owner.private_files.get("source.dmg")
    sealed_digest = owner.private_copy_sha256
    if sealed is None or sealed_digest is None or re.fullmatch(r"[0-9a-f]{64}", sealed_digest) is None:
        raise MetadataVerificationError("private DMG copy has no sealed content digest")
    if (
        not stat.S_ISREG(sealed.st_mode)
        or sealed.st_nlink != 1
        or stat.S_IMODE(sealed.st_mode) != 0o600
        or not 0 < sealed.st_size <= MAX_DMG_BYTES
    ):
        raise MetadataVerificationError("private DMG copy has invalid sealed-file metadata")
    descriptor = -1
    primary: BaseException | None = None
    try:
        _verify_directory_bindings(owner)
        named = os.stat("source.dmg", dir_fd=owner.fd, follow_symlinks=False)
        # A real readonly hdiutil attach can update ctime on its private input.
        # All other sealed fields remain exact, and content is authenticated below.
        if not stat.S_ISREG(named.st_mode) or _stable_stat(sealed)[:-1] != _stable_stat(named)[:-1]:
            raise MetadataVerificationError("private DMG copy physical file binding changed after readonly attach")
        descriptor = os.open("source.dmg", _open_flags("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"), dir_fd=owner.fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _stable_stat(named) != _stable_stat(before):
            raise MetadataVerificationError("private DMG copy changed while reopening after readonly attach")
        current_digest = hashlib.sha256()
        remaining = sealed.st_size
        while remaining:
            chunk = os.read(descriptor, min(COPY_READ_BYTES, remaining))
            if not chunk:
                raise MetadataVerificationError("private DMG copy shrank during its post-attach content check")
            remaining -= len(chunk)
            current_digest.update(chunk)
        if os.read(descriptor, 1):
            raise MetadataVerificationError("private DMG copy grew during its post-attach content check")
        if _stable_stat(before) != _stable_stat(os.fstat(descriptor)):
            raise MetadataVerificationError("private DMG copy changed during its post-attach content check")
        _verify_regular_binding(owner.fd, "source.dmg", before, "private DMG copy after readonly attach")
        _verify_directory_bindings(owner)
        if current_digest.hexdigest() != sealed_digest:
            raise MetadataVerificationError("private DMG copy content changed after readonly attach")
    except OSError as error:
        translated = MetadataVerificationError(f"unable to verify private DMG copy after readonly attach: {error}")
        primary = translated
        raise translated from error
    except BaseException as error:
        primary = error
        raise
    finally:
        if descriptor >= 0:
            _close_descriptors(((descriptor, "private DMG copy after readonly attach"),), primary)


def _inspect_dmg_contents(
    dmg_path: Path,
    expected: Mapping[str, str],
    expected_architecture: str | None,
) -> tuple[BundleMetadata, BundleInventory | None]:
    retained, mountpoint = _create_private_mountpoint()
    root = retained.path
    private_dmg = root / "source.dmg"
    device: str | None = None
    known_unmounted = True
    private_owner = retained
    primary_error: MetadataVerificationError | None = None
    metadata: BundleMetadata | None = None
    inventory: BundleInventory | None = None
    active_error: BaseException | None = None
    cleanup_failure: BaseException | None = None
    try:
        try:
            private_dmg = _copy_bound_dmg(dmg_path, root, owner=private_owner)
            _verify_regular_binding(
                private_owner.fd, "source.dmg", private_owner.private_files["source.dmg"], "private DMG copy"
            )
            _verify_directory_bindings(private_owner)
            known_unmounted = False
            attach = _run_hdiutil_command(
                (
                    HDIUTIL_PATH,
                    "attach",
                    "-readonly",
                    "-nobrowse",
                    "-plist",
                    "-mountpoint",
                    os.fspath(mountpoint),
                    os.fspath(private_dmg),
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
        if device is None and not known_unmounted:
            try:
                device = _hdiutil_info_device(mountpoint)
                known_unmounted = device is None
            except BaseException as error:
                if primary_error is not None:
                    _cleanup_note(
                        primary_error, f"exact mounted device could not be recovered; retaining {root}: {error}"
                    )
                else:
                    raise

        if primary_error is None:
            if device is None:
                primary_error = MetadataVerificationError(
                    "hdiutil reported attach success but the exact mount point is not mounted"
                )
            else:
                with _open_retained_directories(mountpoint / APP_PLIST_COMPONENTS[0], "DMG app") as mounted:
                    if expected_architecture is not None:
                        metadata, inventory = _inspect_app_at(mounted.fd, expected, expected_architecture, "DMG app")
                    else:
                        content = _read_regular_at(
                            mounted.fd, APP_PLIST_COMPONENTS[1:], MAX_PLIST_BYTES, "DMG Info.plist"
                        )
                        metadata = _parse_bundle_plist(content, expected, "DMG Info.plist")
                    _verify_directory_bindings(mounted)
                _verify_directory_bindings(private_owner)
                _verify_attached_private_dmg(private_owner)
    except MetadataVerificationError as error:
        primary_error = error
    except BaseException as error:
        active_error = error
        raise
    finally:
        safe_to_clean = known_unmounted
        if device is not None:
            detach_failures: list[BaseException] = []
            try:
                detach = _run_hdiutil_command((HDIUTIL_PATH, "detach", device), "detach")
                if detach.returncode != 0:
                    raise _command_failure("detach", detach)
            except BaseException as error:
                detach_failures.append(error)
            try:
                remaining_device = _hdiutil_info_device(mountpoint)
                if remaining_device is not None or os.path.ismount(mountpoint):
                    raise MetadataVerificationError(f"mount point remains attached to {remaining_device or device}")
                safe_to_clean = True
            except BaseException as error:
                detach_failures.append(error)
                safe_to_clean = False
            if detach_failures:
                preserved = active_error or primary_error or cleanup_failure
                if preserved is None:
                    cleanup_failure = detach_failures[0]
                    preserved = cleanup_failure
                    later_failures = detach_failures[1:]
                else:
                    later_failures = detach_failures
                for error in later_failures:
                    _cleanup_note(preserved, f"detach/confirmation cleanup failure for {device}: {error}")

        if safe_to_clean:
            try:
                _remove_private_dmg_root(root, mountpoint, private_dmg, owner=private_owner)
            except BaseException as error:
                safe_to_clean = False
                preserved = active_error or primary_error or cleanup_failure
                if preserved is not None:
                    _cleanup_note(preserved, f"private DMG cleanup failed: {error}")
                    for note in getattr(error, "__notes__", ()):
                        _cleanup_note(preserved, note)
                else:
                    cleanup_failure = error

        if not safe_to_clean:
            preserved = active_error or primary_error or cleanup_failure
            if preserved is not None:
                _cleanup_note(
                    preserved, f"retaining private DMG verification root because cleanup is unconfirmed: {root}"
                )
        preserved = active_error or primary_error or cleanup_failure
        try:
            private_owner.close(preserved)
        except BaseException as error:
            cleanup_failure = error

    if cleanup_failure is not None:
        raise cleanup_failure
    if primary_error is not None:
        raise primary_error
    if metadata is None:
        raise MetadataVerificationError("DMG metadata verification produced no result")
    return metadata, inventory


def inspect_dmg(dmg_path: Path, expected: Mapping[str, str]) -> BundleMetadata:
    metadata, _inventory = _inspect_dmg_contents(dmg_path, expected, None)
    return metadata


def load_source_policy(source_root: Path) -> dict[str, str]:
    """Load the existing policy from its retained canonical helper."""
    return _load_policy(source_root)


def _complete_bundle_inspection(metadata: BundleMetadata, inventory: BundleInventory) -> BundleInspection:
    maximum = max(item.minimum_macos for item in inventory.mach_o_files)
    declared = _parse_macos_version_text(metadata.minimum_system_version, "LSMinimumSystemVersion")
    if declared < maximum:
        raise MetadataVerificationError(
            f"LSMinimumSystemVersion {metadata.minimum_system_version} is below native "
            f"Mach-O requirement {_format_macos_version(maximum)}"
        )
    return BundleInspection(metadata, inventory)


def inspect_zip_bundle(
    zip_path: Path, expected: Mapping[str, str], expected_architecture: str
) -> BundleInspection:
    """Inspect a retained ZIP using the existing complete native/link checks."""
    metadata, inventory = _inspect_zip_contents(zip_path, expected, _require_expected_architecture(expected_architecture))
    if inventory is None:
        raise MetadataVerificationError("ZIP native inventory verification produced no result")
    return _complete_bundle_inspection(metadata, inventory)


def inspect_app_bundle(
    app_path: Path, expected: Mapping[str, str], expected_architecture: str
) -> BundleInspection:
    """Inspect a physical extracted App with the existing retained walker."""
    expected_architecture = _require_expected_architecture(expected_architecture)
    if app_path.name != APP_PLIST_COMPONENTS[0]:
        raise MetadataVerificationError(f"direct app must be named {APP_PLIST_COMPONENTS[0]}")
    with _open_retained_directories(app_path, "extracted app") as owner:
        metadata, inventory = _inspect_app_at(owner.fd, expected, expected_architecture, "extracted app")
        _verify_directory_bindings(owner)
        return _complete_bundle_inspection(metadata, inventory)


def verify_artifacts(
    source_root: Path, app_path: Path, zip_path: Path, dmg_path: Path, expected_architecture: str
) -> VerificationReceipt:
    expected_architecture = _require_expected_architecture(expected_architecture)
    expected = _load_policy(source_root)
    if app_path.name != APP_PLIST_COMPONENTS[0]:
        raise MetadataVerificationError(f"direct app must be named {APP_PLIST_COMPONENTS[0]}")
    with _open_retained_directories(app_path, "direct app") as owner:
        direct_metadata, direct_inventory = _inspect_app_at(owner.fd, expected, expected_architecture, "direct app")
        zip_metadata, zip_inventory = _inspect_zip_contents(
            zip_path,
            expected,
            expected_architecture,
        )
        dmg_metadata, dmg_inventory = _inspect_dmg_contents(
            dmg_path,
            expected,
            expected_architecture,
        )
        if zip_inventory is None or dmg_inventory is None:
            raise MetadataVerificationError("artifact inventory verification produced no result")
        observations = (direct_metadata, zip_metadata, dmg_metadata)
        if len({observation.plist_sha256 for observation in observations}) != 1:
            raise MetadataVerificationError("direct app, ZIP, and DMG Info.plist bytes are not identical")
        inventories = (direct_inventory, zip_inventory, dmg_inventory)
        if len({inventory.mach_o_files for inventory in inventories}) != 1:
            raise MetadataVerificationError("direct app, ZIP, and DMG Mach-O inventories are not identical")
        if len({inventory.symlinks for inventory in inventories}) != 1:
            raise MetadataVerificationError("direct app, ZIP, and DMG symlink inventories are not identical")

        maximum_macos = max(item.minimum_macos for item in direct_inventory.mach_o_files)
        declared_minimum = _parse_macos_version_text(
            direct_metadata.minimum_system_version,
            "LSMinimumSystemVersion",
        )
        if declared_minimum < maximum_macos:
            raise MetadataVerificationError(
                f"LSMinimumSystemVersion {direct_metadata.minimum_system_version} is below native "
                f"Mach-O requirement {_format_macos_version(maximum_macos)}"
            )
        _verify_directory_bindings(owner)
        return VerificationReceipt(
            direct_metadata,
            expected_architecture,
            len(direct_inventory.mach_o_files),
            len(direct_inventory.symlinks),
            maximum_macos,
        )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify exact GM2Godot macOS bundle metadata across release artifacts."
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--dmg", required=True)
    parser.add_argument(
        "--expected-architecture",
        required=True,
        choices=sorted(SUPPORTED_ARCHITECTURES),
    )
    return parser


def _report_cli_failure(label: str, error: BaseException) -> None:
    def bounded(text: str) -> str:
        return text if len(text) <= 512 else text[:509] + "..."

    print(f"{label}: {bounded(str(error))}", file=sys.stderr)
    cause = error.__cause__
    if cause is not None:
        print(f"cause: {bounded(str(cause))}", file=sys.stderr)
    notes = getattr(error, "__notes__", ())
    for note in notes[:8]:
        print(f"note: {bounded(note)}", file=sys.stderr)
    if len(notes) > 8:
        print(f"note: {len(notes) - 8} additional diagnostic notes truncated", file=sys.stderr)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _argument_parser().parse_args(arguments)
    try:
        receipt = verify_artifacts(
            _require_absolute_path(parsed.source_root, "source root"),
            _require_absolute_path(parsed.app, "direct app"),
            _require_absolute_path(parsed.zip, "ZIP"),
            _require_absolute_path(parsed.dmg, "DMG"),
            parsed.expected_architecture,
        )
        print(
            "Verified identical macOS bundle policy: "
            f"identifier={receipt.metadata.identifier} "
            f"version={receipt.metadata.short_version} "
            f"build={receipt.metadata.build_version} "
            f"minimum_system={receipt.metadata.minimum_system_version} "
            f"architecture={receipt.architecture} "
            f"macho_count={receipt.macho_count} "
            f"symlink_count={receipt.symlink_count} "
            f"maximum_native_minimum={_format_macos_version(receipt.maximum_macos)} "
            f"plist_sha256={receipt.metadata.plist_sha256}"
        )
    except (KeyboardInterrupt, SystemExit) as error:
        _report_cli_failure(f"macOS bundle verification interrupted ({type(error).__name__})", error)
        return 2
    except (MetadataVerificationError, OSError) as error:
        _report_cli_failure("macOS bundle verification failed", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
