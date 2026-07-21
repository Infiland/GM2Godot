from __future__ import annotations

import ctypes
import hashlib
import json
import os
import posixpath
import re
import secrets
import stat
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Iterable, Protocol, cast

from src.conversion.anchored_artifacts import (
    PathIdentity,
    VerifiedDirectory,
    modes_match,
)


DESTINATION_LOCK_NAME = ".gm2godot-managed-output.lock"
WORKSPACE_PARENT_NAME = ".gm2godot-managed-output"
WORKSPACE_PARENT_MARKER_NAME = ".gm2godot-workspace-parent.json"
WORKSPACE_STAGE_MARKER_NAME = ".gm2godot-workspace-stage.json"

_LOCK_TEMP_PREFIX = ".gm2godot-managed-output-lock."
_STAGE_PREFIX = "transaction-"
_STAGE_SUFFIX = ".stage"
_STAGE_CLEANUP_PREFIX = ".gm2godot-transaction-"
_STAGE_CLEANUP_SUFFIX = ".cleanup"
_ENTRY_CLEANUP_PREFIX = ".gm2godot-cleanup-"
_LOCK_CONTENT = b"GM2Godot destination-wide managed-output lock v1\n"
_MARKER_MAX_BYTES = 1024
_TRANSACTION_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_COPY_CHUNK_BYTES = 1024 * 1024
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_MOVEFILE_WRITE_THROUGH = 0x00000008
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
    }
    | {f"COM{suffix}" for suffix in "123456789¹²³"}
    | {f"LPT{suffix}" for suffix in "123456789¹²³"}
)


FileFingerprint = tuple[int, int, int, int, int, int]


class _HexDigest(Protocol):
    def hexdigest(self) -> str: ...


@dataclass(frozen=True)
class ManagedFileSnapshot:
    """Immutable receipt for one explicitly requested destination file."""

    relative_path: str
    fingerprint: FileFingerprint
    mode: int
    byte_count: int
    sha256: str

    @property
    def identity(self) -> PathIdentity:
        return self.fingerprint[0], self.fingerprint[1]


@dataclass(frozen=True)
class StagedFileReceipt:
    """Receipt for one allowlisted file copied into the private stage."""

    relative_path: str
    identity: PathIdentity
    mode: int
    byte_count: int
    sha256: str


@dataclass
class _DestinationLock:
    file_descriptor: int
    identity: PathIdentity
    windows: bool
    locked: bool = True

    def verify(self, destination: VerifiedDirectory, expected_device: int) -> None:
        destination.verify_path()
        path_stat = destination.stat(DESTINATION_LOCK_NAME)
        opened_stat = os.fstat(self.file_descriptor)
        if (
            _path_is_redirected(destination.child_path(DESTINATION_LOCK_NAME), path_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(opened_stat.st_mode)
            or path_stat.st_nlink != 1
            or opened_stat.st_nlink != 1
            or (path_stat.st_dev, path_stat.st_ino) != self.identity
            or (opened_stat.st_dev, opened_stat.st_ino) != self.identity
            or path_stat.st_dev != expected_device
        ):
            raise OSError(
                "Destination-wide managed-output lock changed: "
                + destination.child_path(DESTINATION_LOCK_NAME)
            )
        if _read_bounded_descriptor(
            self.file_descriptor,
            len(_LOCK_CONTENT) + 1,
        ) != _LOCK_CONTENT:
            raise OSError(
                "Destination-wide managed-output lock content changed: "
                + destination.child_path(DESTINATION_LOCK_NAME)
            )
        destination.verify_path()

    def close(self) -> None:
        if not self.locked:
            return
        self.locked = False
        try:
            if self.windows:
                os.lseek(self.file_descriptor, 0, os.SEEK_SET)
                _windows_file_locking(self.file_descriptor, 0)
            else:
                import fcntl

                fcntl.flock(self.file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.file_descriptor)


@dataclass
class _CleanupEntry:
    original_name: str
    current_name: str
    cleanup_name: str
    display_path: str
    fingerprint: FileFingerprint
    mode: int
    is_directory: bool
    children: list[_CleanupEntry]
    quarantined: bool = False
    removed: bool = False

    @property
    def identity(self) -> PathIdentity:
        return self.fingerprint[0], self.fingerprint[1]


def _before_workspace_phase(_phase: str, _path: str) -> None:
    """Narrow adversarial-test seam around workspace namespace operations."""


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    file_attributes = cast(int, getattr(path_stat, "st_file_attributes", 0))
    if file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_mode,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_nlink,
    )


def _fingerprints_match(actual: FileFingerprint, expected: FileFingerprint) -> bool:
    return (
        actual[:2] == expected[:2]
        and stat.S_IFMT(actual[2]) == stat.S_IFMT(expected[2])
        and modes_match(stat.S_IMODE(actual[2]), stat.S_IMODE(expected[2]))
        and actual[3:] == expected[3:]
    )


def _sha256_digest(digest: _HexDigest) -> str:
    return "sha256:" + digest.hexdigest()


def _canonical_marker(payload: dict[str, object]) -> bytes:
    content = (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")
    if len(content) > _MARKER_MAX_BYTES:
        raise OSError("Managed-output workspace marker exceeds its bounded format")
    return content


def _identity_payload(identity: PathIdentity) -> list[str]:
    values: list[str] = []
    for value in identity:
        if type(value) is not int or value < 0 or value.bit_length() > 128:
            raise OSError("Managed-output workspace identity is outside uint128")
        values.append(f"{value:032x}")
    return values


def _parent_marker_content(
    destination_identity: PathIdentity,
    parent_identity: PathIdentity,
) -> bytes:
    return _canonical_marker(
        {
            "destination_identity": _identity_payload(destination_identity),
            "format_version": 1,
            "kind": "gm2godot-managed-output-workspace-parent",
            "parent_identity": _identity_payload(parent_identity),
        }
    )


def _stage_marker_content(
    destination_identity: PathIdentity,
    parent_identity: PathIdentity,
    stage_identity: PathIdentity,
    transaction_id: str,
) -> bytes:
    return _canonical_marker(
        {
            "destination_identity": _identity_payload(destination_identity),
            "format_version": 1,
            "kind": "gm2godot-managed-output-workspace-stage",
            "parent_identity": _identity_payload(parent_identity),
            "stage_identity": _identity_payload(stage_identity),
            "transaction_id": transaction_id,
        }
    )


def _validate_transaction_id(transaction_id: str) -> str:
    if not _TRANSACTION_ID_PATTERN.fullmatch(transaction_id):
        raise ValueError(
            "Managed-output transaction identifiers must contain exactly "
            "32 lowercase hexadecimal characters."
        )
    return transaction_id


def _validate_relative_path(path: str | os.PathLike[str]) -> str:
    value = os.fspath(path)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or posixpath.normpath(value) != value
    ):
        raise ValueError(f"Managed-output path is not a normalized relative path: {value!r}")
    components = value.split("/")
    for component in components:
        windows_stem = component.rstrip(" .").split(".", 1)[0].upper()
        if (
            component in {"", ".", ".."}
            or component.endswith((" ", "."))
            or ":" in component
            or any(ord(character) < 32 for character in component)
            or windows_stem in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"Managed-output path component is unsafe: {component!r}")
    if components[0] in {DESTINATION_LOCK_NAME, WORKSPACE_PARENT_NAME}:
        raise ValueError(f"Managed-output path targets reserved workspace state: {value!r}")
    if any(
        component == WORKSPACE_STAGE_MARKER_NAME
        or component.startswith(_ENTRY_CLEANUP_PREFIX)
        for component in components
    ):
        raise ValueError(f"Managed-output path targets reserved stage state: {value!r}")
    return value


def _read_bounded_descriptor(file_descriptor: int, limit: int) -> bytes:
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = os.read(file_descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _windows_file_locking(file_descriptor: int, mode: int) -> None:
    import msvcrt

    locking = cast(
        Callable[[int, int, int], None],
        getattr(msvcrt, "locking"),
    )
    locking(file_descriptor, mode, 1)


def _write_descriptor(file_descriptor: int, content: bytes) -> None:
    pending = memoryview(content)
    while pending:
        written = os.write(file_descriptor, pending)
        if written <= 0:
            raise OSError("Could not write managed-output workspace state")
        pending = pending[written:]


def _linux_mount_id(file_descriptor: int) -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(
            f"/proc/self/fdinfo/{file_descriptor}",
            encoding="ascii",
        ) as descriptor_info:
            values = [
                line.partition(":")[2].strip()
                for line in descriptor_info
                if line.startswith("mnt_id:")
            ]
    except OSError:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
        raise OSError("Could not verify the managed-output Linux mount boundary")
    return int(values[0])


def _binding_stat(binding: VerifiedDirectory) -> os.stat_result:
    if binding.strategy == "posix_dir_fd":
        return os.fstat(binding.descriptor)
    return os.lstat(binding.path)


def _verify_binding_boundary(
    binding: VerifiedDirectory,
    *,
    expected_device: int,
    expected_mount_id: int | None,
    allow_mountpoint: bool = False,
) -> int | None:
    binding.verify_path()
    binding_stat = _binding_stat(binding)
    try:
        is_mountpoint = os.path.ismount(binding.path)
    except OSError as error:
        raise OSError(
            f"Could not verify managed-output mount boundary: {binding.path}"
        ) from error
    current_mount_id = (
        _linux_mount_id(binding.descriptor)
        if binding.strategy == "posix_dir_fd"
        else None
    )
    if (
        not stat.S_ISDIR(binding_stat.st_mode)
        or binding_stat.st_dev != expected_device
        or (is_mountpoint and not allow_mountpoint)
        or (
            expected_mount_id is not None
            and current_mount_id != expected_mount_id
        )
    ):
        raise OSError(
            "Refusing a managed-output path that crosses a filesystem or "
            f"mount boundary: {binding.path}"
        )
    binding.verify_path()
    return current_mount_id


def _verify_file_boundary(
    path: str,
    opened_stat: os.stat_result,
    file_descriptor: int,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> None:
    try:
        is_mountpoint = os.path.ismount(path)
    except OSError as error:
        raise OSError(f"Could not verify managed-output mount boundary: {path}") from error
    current_mount_id = _linux_mount_id(file_descriptor)
    if (
        opened_stat.st_dev != expected_device
        or is_mountpoint
        or (
            expected_mount_id is not None
            and current_mount_id != expected_mount_id
        )
    ):
        raise OSError(
            "Refusing a managed-output file that crosses a filesystem or "
            f"mount boundary: {path}"
        )


def _open_or_create_destination(path: str) -> VerifiedDirectory:
    absolute_path = os.path.abspath(path)
    drive, tail = os.path.splitdrive(absolute_path)
    root_path = drive + os.sep if drive else os.sep
    components = tuple(component for component in tail.split(os.sep) if component)
    if not components:
        return VerifiedDirectory.open(
            root_path,
            description="managed-output destination",
        )
    remaining_components = components
    if (
        sys.platform == "darwin"
        and root_path == os.sep
        and components[0] in {"etc", "tmp", "var"}
    ):
        # macOS exposes these fixed system aliases through /private. Resolve
        # only that reviewed platform alias; every user-selectable component
        # below it remains no-follow.
        platform_anchor = os.path.join(root_path, components[0])
        resolved_anchor = os.path.realpath(platform_anchor)
        expected_anchor = os.path.join(os.sep, "private", components[0])
        if os.path.normcase(resolved_anchor) != os.path.normcase(expected_anchor):
            raise OSError(
                "Unexpected macOS managed-output platform anchor: "
                + platform_anchor
            )
        current = VerifiedDirectory.open(
            resolved_anchor,
            description=(
                "managed-output destination"
                if len(components) == 1
                else "managed-output destination ancestor"
            ),
        )
        remaining_components = components[1:]
        if not remaining_components:
            return current
    else:
        current = VerifiedDirectory.open(
            root_path,
            description="managed-output destination ancestor",
        )
    try:
        for index, component in enumerate(remaining_components):
            child_path = current.child_path(component)
            created = False
            try:
                child_stat = current.stat(component)
            except FileNotFoundError:
                _before_workspace_phase("before_destination_mkdir", child_path)
                current.mkdir(component, 0o755)
                created = True
                child_stat = current.stat(component)
            if _path_is_redirected(child_path, child_stat) or not stat.S_ISDIR(
                child_stat.st_mode
            ):
                raise OSError(
                    "Refusing redirected or non-directory managed-output "
                    f"destination component: {child_path}"
                )
            child_identity = child_stat.st_dev, child_stat.st_ino
            _before_workspace_phase("before_destination_bind", child_path)
            child = current.open_child(
                component,
                expected_identity=child_identity,
                description=(
                    "managed-output destination"
                    if index == len(remaining_components) - 1
                    else "managed-output destination ancestor"
                ),
            )
            try:
                if created:
                    current.sync()
                current.verify_path()
                child.verify_path()
            except BaseException as error:
                try:
                    child.close()
                except BaseException as close_error:
                    error.add_note(
                        "Could not close rejected managed-output destination "
                        f"component: {close_error}"
                    )
                raise
            current.close()
            current = child
        return current
    except BaseException:
        current.close()
        raise


def _read_regular_bytes(
    directory: VerifiedDirectory,
    name: str,
    *,
    expected_device: int,
    expected_mount_id: int | None,
    max_bytes: int,
    expected_identity: PathIdentity | None = None,
    expected_mode: int | None = None,
) -> tuple[PathIdentity, int, bytes]:
    path = directory.child_path(name)
    path_stat = directory.stat(name)
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
        or path_stat.st_size > max_bytes
    ):
        raise OSError(f"Refusing redirected, aliased, or oversized workspace file: {path}")
    file_descriptor = directory.open_file(name, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        opened_stat = os.fstat(file_descriptor)
        identity = opened_stat.st_dev, opened_stat.st_ino
        mode = stat.S_IMODE(opened_stat.st_mode)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or not os.path.samestat(path_stat, opened_stat)
            or (expected_identity is not None and identity != expected_identity)
            or (
                expected_mode is not None
                and not modes_match(mode, expected_mode)
            )
        ):
            raise OSError(f"Workspace file changed while opening: {path}")
        _verify_file_boundary(
            path,
            opened_stat,
            file_descriptor,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        content = _read_bounded_descriptor(file_descriptor, max_bytes + 1)
        if len(content) > max_bytes:
            raise OSError(f"Workspace file exceeds its bounded format: {path}")
        opened_after = os.fstat(file_descriptor)
        path_after = directory.stat(name)
        if (
            not _fingerprints_match(
                _fingerprint(opened_after),
                _fingerprint(opened_stat),
            )
            or not _fingerprints_match(
                _fingerprint(path_after),
                _fingerprint(path_stat),
            )
        ):
            raise OSError(f"Workspace file changed while reading: {path}")
        directory.verify_path()
        return identity, mode, content
    finally:
        os.close(file_descriptor)


def _write_owned_file(
    directory: VerifiedDirectory,
    name: str,
    content: bytes,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> tuple[PathIdentity, int]:
    file_descriptor = directory.open_file(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    identity: PathIdentity | None = None
    try:
        opened_stat = os.fstat(file_descriptor)
        identity = opened_stat.st_dev, opened_stat.st_ino
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or opened_stat.st_dev != expected_device
        ):
            raise OSError(
                "Refusing non-regular, aliased, or cross-device workspace file: "
                + directory.child_path(name)
            )
        _verify_file_boundary(
            directory.child_path(name),
            opened_stat,
            file_descriptor,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        _write_descriptor(file_descriptor, content)
        os.fsync(file_descriptor)
    except BaseException:
        os.close(file_descriptor)
        if identity is not None:
            directory.unlink(name, expected_identity=identity)
        raise
    os.close(file_descriptor)
    directory.sync()
    marker_identity, marker_mode, actual = _read_regular_bytes(
        directory,
        name,
        expected_device=expected_device,
        expected_mount_id=expected_mount_id,
        max_bytes=_MARKER_MAX_BYTES,
        expected_identity=identity,
    )
    if actual != content:
        raise OSError(f"Workspace marker changed after creation: {directory.child_path(name)}")
    return marker_identity, marker_mode


def _native_noreplace_available() -> bool:
    return sys.platform == "darwin" or sys.platform.startswith("linux")


def _rename_noreplace_at(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    if not _native_noreplace_available():
        raise OSError(
            f"Atomic non-replacing workspace rename is unavailable on {sys.platform}"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    function_name = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    raw_function = getattr(libc, function_name, None)
    if raw_function is None:
        raise OSError(
            f"Atomic non-replacing workspace rename is unavailable: {function_name}"
        )
    rename_function = cast(
        Callable[[int, bytes, int, bytes, int], int],
        raw_function,
    )
    exclusive_flag = 0x00000004 if sys.platform == "darwin" else 1
    ctypes.set_errno(0)
    result = rename_function(
        parent_descriptor,
        os.fsencode(source_name),
        parent_descriptor,
        os.fsencode(destination_name),
        exclusive_flag,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )


def _windows_extended_path(path: str) -> str:
    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


@lru_cache(maxsize=1)
def _windows_move_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows managed-output move APIs are unavailable")
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    kernel32.MoveFileExW.restype = ctypes.c_int
    return kernel32


def _windows_api_error(operation: str, path: str) -> OSError:
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    error_number = get_last_error()
    format_error = cast(Callable[[int], str], getattr(ctypes, "FormatError"))
    return OSError(
        error_number,
        f"{operation}: {format_error(error_number).strip()}",
        path,
    )


def _rename_noreplace_windows(source: str, destination: str) -> None:
    if sys.platform != "win32":
        raise OSError("Native Windows managed-output rename is unavailable")
    kernel32 = _windows_move_api()
    if not kernel32.MoveFileExW(
        _windows_extended_path(source),
        _windows_extended_path(destination),
        _WINDOWS_MOVEFILE_WRITE_THROUGH,
    ):
        raise _windows_api_error(
            "Could not durably move managed-output workspace entry",
            destination,
        )


def _restore_unexpected_move(
    parent: VerifiedDirectory,
    source_name: str,
    destination_name: str,
) -> OSError:
    source_path = parent.child_path(source_name)
    destination_path = parent.child_path(destination_name)
    try:
        if parent.strategy == "posix_dir_fd":
            _rename_noreplace_at(
                parent.descriptor,
                destination_name,
                source_name,
            )
        elif parent.strategy == "windows_handle":
            _rename_noreplace_windows(destination_path, source_path)
        else:
            raise OSError("Verified-path workspace rename fallback is intentionally disabled")
    except OSError as restore_error:
        error = OSError(
            "Unexpected workspace replacement was preserved at "
            f"{destination_path!r}; automatic restore to {source_path!r} failed"
        )
        error.add_note(f"Restore error: {restore_error}")
        return error
    return OSError(
        "Unexpected workspace replacement was restored without loss to "
        f"{source_path!r}; refused move to {destination_path!r}"
    )


def _move_entry_exact(
    parent: VerifiedDirectory,
    source_name: str,
    destination_name: str,
    expected_identity: PathIdentity,
    *,
    expect_directory: bool,
) -> None:
    source_path = parent.child_path(source_name)
    destination_path = parent.child_path(destination_name)
    parent.verify_path()
    source_stat = parent.stat(source_name)
    expected_kind = stat.S_ISDIR if expect_directory else stat.S_ISREG
    if (
        _path_is_redirected(source_path, source_stat)
        or not expected_kind(source_stat.st_mode)
        or (source_stat.st_dev, source_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Managed-output workspace entry changed: {source_path}")
    if parent.lexists(destination_name):
        raise OSError(
            "Unknown reserved managed-output cleanup collision was preserved: "
            + destination_path
        )
    _before_workspace_phase("before_workspace_move", source_path)
    if parent.strategy == "posix_dir_fd":
        _rename_noreplace_at(
            parent.descriptor,
            source_name,
            destination_name,
        )
    elif parent.strategy == "windows_handle":
        parent.verify_path()
        _rename_noreplace_windows(source_path, destination_path)
    else:
        raise OSError(
            "Strong non-replacing workspace moves are unavailable on this platform"
        )
    destination_stat = parent.stat(destination_name)
    if (
        _path_is_redirected(destination_path, destination_stat)
        or not expected_kind(destination_stat.st_mode)
        or (destination_stat.st_dev, destination_stat.st_ino) != expected_identity
    ):
        raise _restore_unexpected_move(
            parent,
            source_name,
            destination_name,
        )
    parent.sync()


def _initialize_destination_lock(
    destination: VerifiedDirectory,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> None:
    token = secrets.token_hex(16)
    temporary_name = _LOCK_TEMP_PREFIX + token + ".tmp"
    temporary_identity: PathIdentity | None = None
    temporary_pending = False
    try:
        temporary_identity, _temporary_mode = _write_owned_file(
            destination,
            temporary_name,
            _LOCK_CONTENT,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        temporary_pending = True
        try:
            _move_entry_exact(
                destination,
                temporary_name,
                DESTINATION_LOCK_NAME,
                temporary_identity,
                expect_directory=False,
            )
        except FileExistsError:
            return
        temporary_pending = False
    finally:
        if temporary_pending and temporary_identity is not None:
            try:
                marker_identity, _mode, content = _read_regular_bytes(
                    destination,
                    temporary_name,
                    expected_device=expected_device,
                    expected_mount_id=expected_mount_id,
                    max_bytes=len(_LOCK_CONTENT),
                    expected_identity=temporary_identity,
                )
                if marker_identity == temporary_identity and content == _LOCK_CONTENT:
                    completion_error = destination.unlink(
                        temporary_name,
                        expected_identity=temporary_identity,
                    )
                    if completion_error is not None:
                        raise completion_error
                    destination.sync()
            except OSError:
                # Ambiguous initialization state is preserved for inspection.
                pass


def _acquire_destination_lock(
    destination: VerifiedDirectory,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> _DestinationLock:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        file_descriptor = destination.open_file(DESTINATION_LOCK_NAME, flags)
    except FileNotFoundError:
        _initialize_destination_lock(
            destination,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        file_descriptor = destination.open_file(DESTINATION_LOCK_NAME, flags)
    locked = False
    windows = os.name == "nt"
    try:
        opened_stat = os.fstat(file_descriptor)
        path_stat = destination.stat(DESTINATION_LOCK_NAME)
        lock_path = destination.child_path(DESTINATION_LOCK_NAME)
        if (
            _path_is_redirected(lock_path, path_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or not os.path.samestat(opened_stat, path_stat)
            or opened_stat.st_nlink != 1
            or opened_stat.st_dev != expected_device
        ):
            raise OSError(
                "Refusing redirected, aliased, or cross-device destination-wide "
                f"managed-output lock: {lock_path}"
            )
        _verify_file_boundary(
            lock_path,
            opened_stat,
            file_descriptor,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        try:
            if windows:
                os.lseek(file_descriptor, 0, os.SEEK_SET)
                _windows_file_locking(file_descriptor, 2)
            else:
                import fcntl

                fcntl.flock(
                    file_descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except OSError as error:
            raise OSError(
                "Another GM2Godot managed-output session already holds the "
                f"destination-wide lock for {destination.path}"
            ) from error
        locked = True
        if _read_bounded_descriptor(
            file_descriptor,
            len(_LOCK_CONTENT) + 1,
        ) != _LOCK_CONTENT:
            raise OSError(
                "Refusing unknown or incomplete state at the reserved "
                f"destination-wide lock path: {lock_path}"
            )
        identity = opened_stat.st_dev, opened_stat.st_ino
        project_lock = _DestinationLock(
            file_descriptor=file_descriptor,
            identity=identity,
            windows=windows,
        )
        project_lock.verify(destination, expected_device)
        return project_lock
    except BaseException:
        if locked:
            try:
                if windows:
                    os.lseek(file_descriptor, 0, os.SEEK_SET)
                    _windows_file_locking(file_descriptor, 0)
                else:
                    import fcntl

                    fcntl.flock(file_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(file_descriptor)
        raise


def _open_or_create_workspace_parent(
    destination: VerifiedDirectory,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> tuple[VerifiedDirectory, bytes, PathIdentity, int]:
    parent_path = destination.child_path(WORKSPACE_PARENT_NAME)
    created = False
    try:
        parent_stat = destination.stat(WORKSPACE_PARENT_NAME)
    except FileNotFoundError:
        _before_workspace_phase("before_workspace_parent_mkdir", parent_path)
        destination.mkdir(WORKSPACE_PARENT_NAME, 0o700)
        created = True
        parent_stat = destination.stat(WORKSPACE_PARENT_NAME)
    if (
        _path_is_redirected(parent_path, parent_stat)
        or not stat.S_ISDIR(parent_stat.st_mode)
    ):
        raise OSError(
            "Refusing redirected or non-directory reserved managed-output "
            f"workspace parent: {parent_path}"
        )
    parent_identity = parent_stat.st_dev, parent_stat.st_ino
    parent = destination.open_child(
        WORKSPACE_PARENT_NAME,
        expected_identity=parent_identity,
        description="managed-output staging parent",
    )
    try:
        _verify_binding_boundary(
            parent,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        expected_content = _parent_marker_content(
            destination.identity,
            parent.identity,
        )
        if created:
            marker_identity, marker_mode = _write_owned_file(
                parent,
                WORKSPACE_PARENT_MARKER_NAME,
                expected_content,
                expected_device=expected_device,
                expected_mount_id=expected_mount_id,
            )
            destination.sync()
        else:
            try:
                marker_identity, marker_mode, actual_content = _read_regular_bytes(
                    parent,
                    WORKSPACE_PARENT_MARKER_NAME,
                    expected_device=expected_device,
                    expected_mount_id=expected_mount_id,
                    max_bytes=_MARKER_MAX_BYTES,
                )
            except OSError as error:
                raise OSError(
                    "Unknown reserved managed-output workspace parent was "
                    f"preserved for inspection: {parent_path}"
                ) from error
            if actual_content != expected_content:
                raise OSError(
                    "Unknown or changed managed-output workspace parent marker "
                    f"was preserved for inspection: {parent_path}"
                )
        return parent, expected_content, marker_identity, marker_mode
    except BaseException:
        parent.close()
        raise


def _remove_empty_created_directory(
    parent: VerifiedDirectory,
    name: str,
    identity: PathIdentity,
) -> None:
    path = parent.child_path(name)
    current = parent.stat(name)
    if (
        _path_is_redirected(path, current)
        or not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != identity
    ):
        raise OSError(
            "Refusing to remove changed incomplete managed-output stage: " + path
        )
    child = parent.open_child(
        name,
        expected_identity=identity,
        description="incomplete managed-output stage",
    )
    try:
        if child.list_names():
            raise OSError(
                "Incomplete managed-output stage is not empty and was preserved: "
                + path
            )
    finally:
        child.close()
    _before_workspace_phase("before_incomplete_stage_remove", path)
    final = parent.stat(name)
    if (
        _path_is_redirected(path, final)
        or not stat.S_ISDIR(final.st_mode)
        or (final.st_dev, final.st_ino) != identity
    ):
        raise OSError(
            "Refusing to remove changed incomplete managed-output stage: " + path
        )
    if parent.strategy == "posix_dir_fd":
        os.rmdir(name, dir_fd=parent.descriptor)
    else:
        parent.verify_path()
        os.rmdir(path)
        parent.verify_path()
    parent.sync()


def _create_stage(
    destination: VerifiedDirectory,
    parent: VerifiedDirectory,
    transaction_id: str,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> tuple[VerifiedDirectory, str, bytes, PathIdentity, int]:
    stage_name = _STAGE_PREFIX + transaction_id + _STAGE_SUFFIX
    stage_path = parent.child_path(stage_name)
    if parent.lexists(stage_name):
        raise OSError(
            "Unknown transaction workspace collision was preserved for "
            f"inspection: {stage_path}"
        )
    _before_workspace_phase("before_workspace_stage_mkdir", stage_path)
    parent.mkdir(stage_name, 0o700)
    stage_stat = parent.stat(stage_name)
    if _path_is_redirected(stage_path, stage_stat) or not stat.S_ISDIR(
        stage_stat.st_mode
    ):
        raise OSError(f"Managed-output stage changed after creation: {stage_path}")
    stage_identity = stage_stat.st_dev, stage_stat.st_ino
    stage = parent.open_child(
        stage_name,
        expected_identity=stage_identity,
        description="managed-output stage",
    )
    try:
        _verify_binding_boundary(
            stage,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        marker_content = _stage_marker_content(
            destination.identity,
            parent.identity,
            stage.identity,
            transaction_id,
        )
        marker_identity, marker_mode = _write_owned_file(
            stage,
            WORKSPACE_STAGE_MARKER_NAME,
            marker_content,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        parent.sync()
        return stage, stage_name, marker_content, marker_identity, marker_mode
    except BaseException as error:
        stage.close()
        try:
            _remove_empty_created_directory(
                parent,
                stage_name,
                stage_identity,
            )
        except BaseException as cleanup_error:
            error.add_note(
                "Removing the rejected incomplete workspace stage also failed; "
                f"exact private state was preserved: {cleanup_error}"
            )
        raise


def _open_existing_stage(
    destination: VerifiedDirectory,
    parent: VerifiedDirectory,
    transaction_id: str,
    *,
    expected_device: int,
    expected_mount_id: int | None,
) -> tuple[VerifiedDirectory, str, bytes, PathIdentity, int]:
    stage_name = _STAGE_PREFIX + transaction_id + _STAGE_SUFFIX
    stage_path = parent.child_path(stage_name)
    try:
        stage_stat = parent.stat(stage_name)
    except FileNotFoundError as error:
        raise OSError(
            "Managed-output recovery stage is unavailable for transaction "
            f"{transaction_id}: {stage_path}"
        ) from error
    if (
        _path_is_redirected(stage_path, stage_stat)
        or not stat.S_ISDIR(stage_stat.st_mode)
    ):
        raise OSError(
            "Refusing redirected or non-directory managed-output recovery "
            f"stage: {stage_path}"
        )
    stage_identity = stage_stat.st_dev, stage_stat.st_ino
    stage = parent.open_child(
        stage_name,
        expected_identity=stage_identity,
        description="managed-output recovery stage",
    )
    try:
        _verify_binding_boundary(
            stage,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
        )
        marker_content = _stage_marker_content(
            destination.identity,
            parent.identity,
            stage.identity,
            transaction_id,
        )
        marker_identity, marker_mode, actual_content = _read_regular_bytes(
            stage,
            WORKSPACE_STAGE_MARKER_NAME,
            expected_device=expected_device,
            expected_mount_id=expected_mount_id,
            max_bytes=_MARKER_MAX_BYTES,
        )
        if actual_content != marker_content:
            raise OSError(
                "Managed-output recovery stage marker changed; exact state was "
                f"preserved at {stage_path}"
            )
        parent.verify_path()
        destination.verify_path()
        return stage, stage_name, marker_content, marker_identity, marker_mode
    except BaseException:
        stage.close()
        raise


class ManagedOutputWorkspace(
    AbstractContextManager["ManagedOutputWorkspace"],
):
    """Destination-local, identity-bound private staging session.

    The session deliberately does not publish or recover public managed output.
    Its lock and verified stage are the foundation consumed by later generation
    planning and publication work.
    """

    def __init__(
        self,
        *,
        destination: VerifiedDirectory,
        destination_lock: _DestinationLock,
        staging_parent: VerifiedDirectory,
        staging_parent_marker: bytes,
        staging_parent_marker_identity: PathIdentity,
        staging_parent_marker_mode: int,
        stage: VerifiedDirectory,
        stage_name: str,
        stage_marker: bytes,
        stage_marker_identity: PathIdentity,
        stage_marker_mode: int,
        transaction_id: str,
        destination_device: int,
        destination_mount_id: int | None,
    ) -> None:
        self._destination = destination
        self._destination_lock = destination_lock
        self._staging_parent = staging_parent
        self._staging_parent_marker = staging_parent_marker
        self._staging_parent_marker_identity = staging_parent_marker_identity
        self._staging_parent_marker_mode = staging_parent_marker_mode
        self._stage: VerifiedDirectory | None = stage
        self._stage_name = stage_name
        self._stage_marker = stage_marker
        self._stage_marker_identity = stage_marker_identity
        self._stage_marker_mode = stage_marker_mode
        self._stage_identity = stage.identity
        self._transaction_id = transaction_id
        self._destination_device = destination_device
        self._destination_mount_id = destination_mount_id
        self._cleanup_entries: list[_CleanupEntry] | None = None
        self._stage_quarantined = False
        self._preserve_stage = False
        self._cleaned = False
        self._closed = False

    @classmethod
    def open(
        cls,
        destination_path: str | os.PathLike[str],
        *,
        transaction_id: str | None = None,
        reuse_existing: bool = False,
    ) -> ManagedOutputWorkspace:
        path_value = os.fspath(destination_path)
        if reuse_existing and transaction_id is None:
            raise ValueError(
                "Reopening a managed-output recovery stage requires its "
                "transaction identifier."
            )
        selected_transaction_id = _validate_transaction_id(
            secrets.token_hex(16) if transaction_id is None else transaction_id
        )
        destination = _open_or_create_destination(path_value)
        destination_lock: _DestinationLock | None = None
        staging_parent: VerifiedDirectory | None = None
        workspace: ManagedOutputWorkspace | None = None
        try:
            destination_stat = _binding_stat(destination)
            destination_device = destination_stat.st_dev
            destination_mount_id = _verify_binding_boundary(
                destination,
                expected_device=destination_device,
                expected_mount_id=(
                    _linux_mount_id(destination.descriptor)
                    if destination.strategy == "posix_dir_fd"
                    else None
                ),
                allow_mountpoint=True,
            )
            destination_lock = _acquire_destination_lock(
                destination,
                expected_device=destination_device,
                expected_mount_id=destination_mount_id,
            )
            (
                staging_parent,
                parent_marker,
                parent_marker_identity,
                parent_marker_mode,
            ) = _open_or_create_workspace_parent(
                destination,
                expected_device=destination_device,
                expected_mount_id=destination_mount_id,
            )
            (
                stage,
                stage_name,
                stage_marker,
                stage_marker_identity,
                stage_marker_mode,
            ) = (
                _open_existing_stage(
                    destination,
                    staging_parent,
                    selected_transaction_id,
                    expected_device=destination_device,
                    expected_mount_id=destination_mount_id,
                )
                if reuse_existing
                else _create_stage(
                    destination,
                    staging_parent,
                    selected_transaction_id,
                    expected_device=destination_device,
                    expected_mount_id=destination_mount_id,
                )
            )
            workspace = cls(
                destination=destination,
                destination_lock=destination_lock,
                staging_parent=staging_parent,
                staging_parent_marker=parent_marker,
                staging_parent_marker_identity=parent_marker_identity,
                staging_parent_marker_mode=parent_marker_mode,
                stage=stage,
                stage_name=stage_name,
                stage_marker=stage_marker,
                stage_marker_identity=stage_marker_identity,
                stage_marker_mode=stage_marker_mode,
                transaction_id=selected_transaction_id,
                destination_device=destination_device,
                destination_mount_id=destination_mount_id,
            )
            workspace.verify()
            return workspace
        except BaseException as error:
            if workspace is not None:
                try:
                    workspace.close()
                except BaseException as close_error:
                    error.add_note(
                        "Cleaning the rejected managed-output workspace also "
                        f"failed: {close_error}"
                    )
                raise
            if staging_parent is not None:
                try:
                    staging_parent.close()
                except BaseException as close_error:
                    error.add_note(
                        f"Could not close rejected staging parent: {close_error}"
                    )
            if destination_lock is not None:
                try:
                    destination_lock.close()
                except BaseException as close_error:
                    error.add_note(
                        f"Could not release rejected destination lock: {close_error}"
                    )
            try:
                destination.close()
            except BaseException as close_error:
                error.add_note(
                    f"Could not close rejected managed-output destination: {close_error}"
                )
            raise

    @property
    def transaction_id(self) -> str:
        return self._transaction_id

    @property
    def destination_path(self) -> str:
        return self._destination.path

    @property
    def stage_path(self) -> str:
        stage = self._require_stage()
        return stage.path

    @property
    def destination_device(self) -> int:
        return self._destination_device

    @property
    def stage_device(self) -> int:
        return _binding_stat(self._require_stage()).st_dev

    @property
    def locked(self) -> bool:
        return self._destination_lock.locked

    @property
    def preserved_for_recovery(self) -> bool:
        return self._preserve_stage

    def preserve_for_recovery(self) -> None:
        """Retain exact private state while releasing the destination lock."""

        self._verify_base()
        if self._stage is not None:
            _verify_binding_boundary(
                self._stage,
                expected_device=self._destination_device,
                expected_mount_id=self._destination_mount_id,
            )
        self._preserve_stage = True

    def resume_recovery_cleanup(self) -> None:
        """Allow a verified reopened session to clean its retained stage."""

        self._require_open()
        self._preserve_stage = False

    def _require_open(self) -> None:
        if self._closed:
            raise OSError("Managed-output workspace session is closed")

    def _require_stage(self) -> VerifiedDirectory:
        self._require_open()
        if self._stage is None or self._cleaned:
            raise OSError("Managed-output workspace stage has been cleaned")
        return self._stage

    def _verify_parent_marker(self) -> None:
        marker_identity, marker_mode, content = _read_regular_bytes(
            self._staging_parent,
            WORKSPACE_PARENT_MARKER_NAME,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
            max_bytes=_MARKER_MAX_BYTES,
            expected_identity=self._staging_parent_marker_identity,
            expected_mode=self._staging_parent_marker_mode,
        )
        if (
            marker_identity != self._staging_parent_marker_identity
            or content != self._staging_parent_marker
            or not modes_match(marker_mode, self._staging_parent_marker_mode)
        ):
            raise OSError(
                "Managed-output workspace parent marker changed; reserved state "
                f"was preserved at {self._staging_parent.path}"
            )

    def _verify_stage_marker(self) -> None:
        stage = self._require_stage()
        marker_identity, marker_mode, content = _read_regular_bytes(
            stage,
            WORKSPACE_STAGE_MARKER_NAME,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
            max_bytes=_MARKER_MAX_BYTES,
            expected_identity=self._stage_marker_identity,
            expected_mode=self._stage_marker_mode,
        )
        if (
            marker_identity != self._stage_marker_identity
            or content != self._stage_marker
            or not modes_match(marker_mode, self._stage_marker_mode)
        ):
            raise OSError(
                "Managed-output workspace ownership marker changed; transaction "
                f"{self._transaction_id} was preserved at {stage.path}"
            )

    def _verify_base(self) -> None:
        self._require_open()
        self._destination.verify_path()
        _verify_binding_boundary(
            self._destination,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
            allow_mountpoint=True,
        )
        self._destination_lock.verify(
            self._destination,
            self._destination_device,
        )
        _verify_binding_boundary(
            self._staging_parent,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
        )
        self._verify_parent_marker()

    def verify(self) -> None:
        self._verify_base()
        stage = self._require_stage()
        _verify_binding_boundary(
            stage,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
        )
        if stage.identity[0] != self._destination_device:
            raise OSError(
                "Managed-output stage no longer shares the destination filesystem"
            )
        self._verify_stage_marker()
        self._staging_parent.verify_path()
        self._destination.verify_path()

    def _open_relative_parent(
        self,
        root: VerifiedDirectory,
        relative_path: str,
        *,
        create: bool,
        description: str,
    ) -> tuple[list[VerifiedDirectory], VerifiedDirectory, str]:
        components = relative_path.split("/")
        opened: list[VerifiedDirectory] = []
        current = root
        try:
            for component in components[:-1]:
                child_path = current.child_path(component)
                try:
                    child_stat = current.stat(component)
                except FileNotFoundError:
                    if not create:
                        raise
                    _before_workspace_phase(
                        "before_stage_directory_mkdir",
                        child_path,
                    )
                    current.mkdir(component, 0o700)
                    child_stat = current.stat(component)
                if (
                    _path_is_redirected(child_path, child_stat)
                    or not stat.S_ISDIR(child_stat.st_mode)
                ):
                    raise OSError(
                        f"Refusing redirected or non-directory {description}: "
                        f"{child_path}"
                    )
                child_identity = child_stat.st_dev, child_stat.st_ino
                _before_workspace_phase(
                    "before_relative_directory_bind",
                    child_path,
                )
                child = current.open_child(
                    component,
                    expected_identity=child_identity,
                    description=description,
                )
                opened.append(child)
                _verify_binding_boundary(
                    child,
                    expected_device=self._destination_device,
                    expected_mount_id=self._destination_mount_id,
                )
                current = child
            return opened, current, components[-1]
        except BaseException:
            for binding in reversed(opened):
                binding.close()
            raise

    @staticmethod
    def _close_relative_bindings(bindings: list[VerifiedDirectory]) -> None:
        active_error: BaseException | None = None
        for binding in reversed(bindings):
            try:
                binding.close()
            except BaseException as error:
                if active_error is None:
                    active_error = error
                else:
                    active_error.add_note(
                        f"Another relative-directory close also failed: {error}"
                    )
        if active_error is not None:
            raise active_error

    def _open_source_file(
        self,
        relative_path: str,
        *,
        expected: ManagedFileSnapshot | None,
    ) -> tuple[list[VerifiedDirectory], VerifiedDirectory, str, int, os.stat_result]:
        opened, parent, leaf = self._open_relative_parent(
            self._destination,
            relative_path,
            create=False,
            description="managed-output source directory",
        )
        path = parent.child_path(leaf)
        file_descriptor = -1
        try:
            path_stat = parent.stat(leaf)
            if (
                _path_is_redirected(path, path_stat)
                or not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_nlink != 1
            ):
                raise OSError(
                    "Refusing redirected, non-regular, or multiply-linked "
                    f"managed-output source: {path}"
                )
            if expected is not None and not _fingerprints_match(
                _fingerprint(path_stat),
                expected.fingerprint,
            ):
                raise OSError(f"Managed-output source changed since snapshot: {path}")
            _before_workspace_phase("before_source_file_open", path)
            file_descriptor = parent.open_file(
                leaf,
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            opened_stat = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or not os.path.samestat(path_stat, opened_stat)
                or (
                    expected is not None
                    and not _fingerprints_match(
                        _fingerprint(opened_stat),
                        expected.fingerprint,
                    )
                )
            ):
                raise OSError(f"Managed-output source changed while opening: {path}")
            _verify_file_boundary(
                path,
                opened_stat,
                file_descriptor,
                expected_device=self._destination_device,
                expected_mount_id=self._destination_mount_id,
            )
            return opened, parent, leaf, file_descriptor, opened_stat
        except BaseException:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            self._close_relative_bindings(opened)
            raise

    def snapshot_files(
        self,
        relative_paths: Iterable[str | os.PathLike[str]],
    ) -> tuple[ManagedFileSnapshot, ...]:
        self.verify()
        requested = tuple(_validate_relative_path(path) for path in relative_paths)
        if len(requested) != len(set(requested)):
            raise ValueError("Managed-output snapshot allowlist contains duplicate paths.")
        normalized = tuple(sorted(requested))
        snapshots: list[ManagedFileSnapshot] = []
        for relative_path in normalized:
            opened, parent, leaf, file_descriptor, opened_stat = (
                self._open_source_file(relative_path, expected=None)
            )
            try:
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(file_descriptor, _COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                opened_after = os.fstat(file_descriptor)
                path_after = parent.stat(leaf)
                initial_fingerprint = _fingerprint(opened_stat)
                if (
                    not _fingerprints_match(
                        _fingerprint(opened_after),
                        initial_fingerprint,
                    )
                    or not _fingerprints_match(
                        _fingerprint(path_after),
                        initial_fingerprint,
                    )
                ):
                    raise OSError(
                        "Managed-output source changed while snapshotting: "
                        + parent.child_path(leaf)
                    )
                snapshots.append(
                    ManagedFileSnapshot(
                        relative_path=relative_path,
                        fingerprint=initial_fingerprint,
                        mode=stat.S_IMODE(opened_stat.st_mode),
                        byte_count=opened_stat.st_size,
                        sha256=_sha256_digest(digest),
                    )
                )
            finally:
                os.close(file_descriptor)
                self._close_relative_bindings(opened)
            self.verify()
        return tuple(snapshots)

    @staticmethod
    def _validated_snapshots(
        snapshots: Iterable[ManagedFileSnapshot],
    ) -> tuple[ManagedFileSnapshot, ...]:
        ordered = tuple(sorted(snapshots, key=lambda snapshot: snapshot.relative_path))
        paths: list[str] = []
        for snapshot in ordered:
            path = _validate_relative_path(snapshot.relative_path)
            if path != snapshot.relative_path:
                raise ValueError("Managed-output snapshot path is not canonical.")
            if (
                len(snapshot.fingerprint) != 6
                or snapshot.byte_count < 0
                or snapshot.fingerprint[3] != snapshot.byte_count
                or snapshot.mode != stat.S_IMODE(snapshot.fingerprint[2])
                or not snapshot.sha256.startswith("sha256:")
                or len(snapshot.sha256) != len("sha256:") + 64
                or any(
                    character not in "0123456789abcdef"
                    for character in snapshot.sha256[len("sha256:") :]
                )
            ):
                raise ValueError(
                    f"Managed-output snapshot is malformed: {snapshot.relative_path!r}"
                )
            if paths and (
                path == paths[-1]
                or path.startswith(paths[-1] + "/")
                or paths[-1].startswith(path + "/")
            ):
                raise ValueError(
                    "Managed-output snapshot paths are duplicate or structurally "
                    f"ambiguous: {paths[-1]!r}, {path!r}"
                )
            paths.append(path)
        return ordered

    def copy_snapshots(
        self,
        snapshots: Iterable[ManagedFileSnapshot],
    ) -> tuple[StagedFileReceipt, ...]:
        self.verify()
        ordered = self._validated_snapshots(snapshots)
        receipts: list[StagedFileReceipt] = []
        for snapshot in ordered:
            (
                source_bindings,
                source_parent,
                source_leaf,
                source_descriptor,
                _source_stat,
            ) = self._open_source_file(
                snapshot.relative_path,
                expected=snapshot,
            )
            stage_bindings: list[VerifiedDirectory] = []
            stage_parent: VerifiedDirectory | None = None
            output_descriptor = -1
            try:
                stage_bindings, stage_parent, stage_leaf = (
                    self._open_relative_parent(
                        self._require_stage(),
                        snapshot.relative_path,
                        create=True,
                        description="managed-output stage directory",
                    )
                )
                output_path = stage_parent.child_path(stage_leaf)
                if stage_parent.lexists(stage_leaf):
                    raise OSError(
                        "Managed-output stage path already exists: " + output_path
                    )
                _before_workspace_phase("before_stage_file_create", output_path)
                output_descriptor = stage_parent.open_file(
                    stage_leaf,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                output_initial = os.fstat(output_descriptor)
                output_identity = output_initial.st_dev, output_initial.st_ino
                if (
                    not stat.S_ISREG(output_initial.st_mode)
                    or output_initial.st_nlink != 1
                    or output_initial.st_dev != self._destination_device
                ):
                    raise OSError(
                        "Refusing non-regular, aliased, or cross-device staged "
                        f"output: {output_path}"
                    )
                _verify_file_boundary(
                    output_path,
                    output_initial,
                    output_descriptor,
                    expected_device=self._destination_device,
                    expected_mount_id=self._destination_mount_id,
                )
                digest = hashlib.sha256()
                copied_bytes = 0
                while True:
                    chunk = os.read(source_descriptor, _COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                    copied_bytes += len(chunk)
                    _write_descriptor(output_descriptor, chunk)
                os.fsync(output_descriptor)
                output_after_write = os.fstat(output_descriptor)
                os.close(output_descriptor)
                output_descriptor = -1
                source_after = os.fstat(source_descriptor)
                source_path_after = source_parent.stat(source_leaf)
                if (
                    not _fingerprints_match(
                        _fingerprint(source_after),
                        snapshot.fingerprint,
                    )
                    or not _fingerprints_match(
                        _fingerprint(source_path_after),
                        snapshot.fingerprint,
                    )
                    or copied_bytes != snapshot.byte_count
                    or _sha256_digest(digest) != snapshot.sha256
                ):
                    raise OSError(
                        "Managed-output source changed while copying: "
                        + source_parent.child_path(source_leaf)
                    )
                if (
                    not stat.S_ISREG(output_after_write.st_mode)
                    or output_after_write.st_nlink != 1
                    or (output_after_write.st_dev, output_after_write.st_ino)
                    != output_identity
                    or output_after_write.st_size != snapshot.byte_count
                ):
                    raise OSError(f"Managed-output stage changed while writing: {output_path}")
                stage_parent.chmod_exact(
                    stage_leaf,
                    output_identity,
                    snapshot.mode,
                    require_single_link=True,
                )
                staged_descriptor = stage_parent.open_file(
                    stage_leaf,
                    os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
                try:
                    staged_stat = os.fstat(staged_descriptor)
                    staged_digest = hashlib.sha256()
                    staged_bytes = 0
                    while True:
                        chunk = os.read(staged_descriptor, _COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        staged_digest.update(chunk)
                        staged_bytes += len(chunk)
                    staged_after = os.fstat(staged_descriptor)
                    if (
                        not _fingerprints_match(
                            _fingerprint(staged_after),
                            _fingerprint(staged_stat),
                        )
                        or staged_stat.st_nlink != 1
                        or (staged_stat.st_dev, staged_stat.st_ino)
                        != output_identity
                        or not modes_match(
                            stat.S_IMODE(staged_stat.st_mode),
                            snapshot.mode,
                        )
                        or staged_bytes != snapshot.byte_count
                        or _sha256_digest(staged_digest) != snapshot.sha256
                    ):
                        raise OSError(
                            f"Managed-output staged copy failed verification: {output_path}"
                        )
                finally:
                    os.close(staged_descriptor)
                stage_parent.sync()
                receipts.append(
                    StagedFileReceipt(
                        relative_path=snapshot.relative_path,
                        identity=output_identity,
                        mode=snapshot.mode,
                        byte_count=snapshot.byte_count,
                        sha256=snapshot.sha256,
                    )
                )
            finally:
                if output_descriptor >= 0:
                    os.close(output_descriptor)
                os.close(source_descriptor)
                if stage_bindings:
                    self._close_relative_bindings(stage_bindings)
                self._close_relative_bindings(source_bindings)
            self.verify()
        return tuple(receipts)

    def _capture_cleanup_entries(
        self,
        directory: VerifiedDirectory,
        *,
        counter: list[int],
        require_stage_marker: bool,
    ) -> list[_CleanupEntry]:
        directory.verify_path()
        names = directory.list_names()
        if any(name.startswith(_ENTRY_CLEANUP_PREFIX) for name in names):
            raise OSError(
                "Unknown reserved cleanup entry was preserved in managed-output "
                f"workspace: {directory.path}"
            )
        if require_stage_marker and WORKSPACE_STAGE_MARKER_NAME not in names:
            raise OSError(
                "Managed-output workspace ownership marker is missing; transaction "
                f"{self._transaction_id} was preserved at {directory.path}"
            )
        entries: list[_CleanupEntry] = []
        ordered_names = sorted(
            names,
            key=lambda name: (name == WORKSPACE_STAGE_MARKER_NAME, name),
        )
        for name in ordered_names:
            path = directory.child_path(name)
            path_stat = directory.stat(name)
            if _path_is_redirected(path, path_stat):
                raise OSError(
                    "Refusing redirected managed-output cleanup entry; workspace "
                    f"preserved at {directory.path}"
                )
            counter[0] += 1
            cleanup_name = (
                _ENTRY_CLEANUP_PREFIX
                + self._transaction_id
                + f"-{counter[0]:08x}"
            )
            if cleanup_name in names:
                raise OSError(
                    "Unknown reserved cleanup collision was preserved at "
                    + directory.child_path(cleanup_name)
                )
            if stat.S_ISDIR(path_stat.st_mode):
                identity = path_stat.st_dev, path_stat.st_ino
                child = directory.open_child(
                    name,
                    expected_identity=identity,
                    description="managed-output cleanup directory",
                )
                try:
                    _verify_binding_boundary(
                        child,
                        expected_device=self._destination_device,
                        expected_mount_id=self._destination_mount_id,
                    )
                    children = self._capture_cleanup_entries(
                        child,
                        counter=counter,
                        require_stage_marker=False,
                    )
                finally:
                    child.close()
                entries.append(
                    _CleanupEntry(
                        original_name=name,
                        current_name=name,
                        cleanup_name=cleanup_name,
                        display_path=path,
                        fingerprint=_fingerprint(path_stat),
                        mode=stat.S_IMODE(path_stat.st_mode),
                        is_directory=True,
                        children=children,
                    )
                )
                continue
            if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
                raise OSError(
                    "Refusing non-regular or multiply-linked managed-output "
                    f"cleanup entry; workspace preserved at {directory.path}"
                )
            file_descriptor = directory.open_file(
                name,
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            try:
                opened_stat = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened_stat.st_mode)
                    or opened_stat.st_nlink != 1
                    or not os.path.samestat(path_stat, opened_stat)
                ):
                    raise OSError(
                        f"Managed-output cleanup entry changed while opening: {path}"
                    )
                _verify_file_boundary(
                    path,
                    opened_stat,
                    file_descriptor,
                    expected_device=self._destination_device,
                    expected_mount_id=self._destination_mount_id,
                )
                if name == WORKSPACE_STAGE_MARKER_NAME:
                    content = _read_bounded_descriptor(
                        file_descriptor,
                        _MARKER_MAX_BYTES + 1,
                    )
                    if (
                        (opened_stat.st_dev, opened_stat.st_ino)
                        != self._stage_marker_identity
                        or not modes_match(
                            stat.S_IMODE(opened_stat.st_mode),
                            self._stage_marker_mode,
                        )
                        or content != self._stage_marker
                    ):
                        raise OSError(
                            "Managed-output workspace ownership marker changed; "
                            f"transaction {self._transaction_id} was preserved at "
                            f"{directory.path}"
                        )
            finally:
                os.close(file_descriptor)
            entries.append(
                _CleanupEntry(
                    original_name=name,
                    current_name=name,
                    cleanup_name=cleanup_name,
                    display_path=path,
                    fingerprint=_fingerprint(path_stat),
                    mode=stat.S_IMODE(path_stat.st_mode),
                    is_directory=False,
                    children=[],
                )
            )
        directory.verify_path()
        return entries

    @staticmethod
    def _remaining_names(entries: list[_CleanupEntry]) -> set[str]:
        return {entry.current_name for entry in entries if not entry.removed}

    def _verify_cleanup_names(
        self,
        directory: VerifiedDirectory,
        entries: list[_CleanupEntry],
    ) -> None:
        actual = set(directory.list_names())
        expected = self._remaining_names(entries)
        if actual != expected:
            unexpected = sorted(actual.symmetric_difference(expected))
            raise OSError(
                "Managed-output cleanup namespace changed; preserving transaction "
                f"{self._transaction_id} at {directory.path}. Changed entries: "
                + ", ".join(repr(name) for name in unexpected)
            )

    def _verify_cleanup_entry(
        self,
        directory: VerifiedDirectory,
        entry: _CleanupEntry,
    ) -> os.stat_result:
        path = directory.child_path(entry.current_name)
        current = directory.stat(entry.current_name)
        expected_kind = stat.S_ISDIR if entry.is_directory else stat.S_ISREG
        if (
            _path_is_redirected(path, current)
            or not expected_kind(current.st_mode)
            or (current.st_dev, current.st_ino) != entry.identity
            or (
                not entry.is_directory
                and not _fingerprints_match(
                    _fingerprint(current),
                    entry.fingerprint,
                )
            )
        ):
            raise OSError(
                "Managed-output cleanup entry changed; preserving transaction "
                f"{self._transaction_id} at {directory.path}"
            )
        return current

    def _unlink_cleanup_file(
        self,
        directory: VerifiedDirectory,
        entry: _CleanupEntry,
    ) -> None:
        current = self._verify_cleanup_entry(directory, entry)
        changed_mode = os.name == "nt" and not bool(current.st_mode & stat.S_IWUSR)
        original_fingerprint = entry.fingerprint
        if changed_mode:
            directory.chmod_exact(
                entry.current_name,
                entry.identity,
                entry.mode | stat.S_IWUSR,
                require_single_link=True,
            )
            entry.fingerprint = _fingerprint(directory.stat(entry.current_name))
        try:
            _before_workspace_phase(
                "before_cleanup_file_remove",
                directory.child_path(entry.current_name),
            )
            self._verify_cleanup_entry(directory, entry)
            completion_error = directory.unlink(
                entry.current_name,
                expected_identity=entry.identity,
            )
            if completion_error is not None:
                raise completion_error
        except BaseException as error:
            if changed_mode and directory.lexists(entry.current_name):
                try:
                    directory.chmod_exact(
                        entry.current_name,
                        entry.identity,
                        entry.mode,
                        require_single_link=True,
                    )
                    entry.fingerprint = original_fingerprint
                except BaseException as restore_error:
                    error.add_note(
                        "Restoring the read-only cleanup file also failed: "
                        + str(restore_error)
                    )
            raise
        if directory.lexists(entry.current_name):
            raise OSError(
                "Managed-output cleanup file remained after removal: "
                + directory.child_path(entry.current_name)
            )

    def _chmod_directory_exact(
        self,
        parent: VerifiedDirectory,
        name: str,
        identity: PathIdentity,
        mode: int,
    ) -> None:
        path = parent.child_path(name)
        current = parent.stat(name)
        if (
            _path_is_redirected(path, current)
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != identity
        ):
            raise OSError(f"Managed-output cleanup directory changed: {path}")
        parent.verify_path()
        os.chmod(path, mode)
        parent.verify_path()
        changed = parent.stat(name)
        if (
            _path_is_redirected(path, changed)
            or not stat.S_ISDIR(changed.st_mode)
            or (changed.st_dev, changed.st_ino) != identity
            or not modes_match(stat.S_IMODE(changed.st_mode), mode)
        ):
            raise OSError(f"Managed-output cleanup directory changed during chmod: {path}")

    def _rmdir_exact(
        self,
        parent: VerifiedDirectory,
        name: str,
        identity: PathIdentity,
        mode: int,
    ) -> None:
        path = parent.child_path(name)
        current = parent.stat(name)
        if (
            _path_is_redirected(path, current)
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != identity
        ):
            raise OSError(f"Managed-output cleanup directory changed: {path}")
        child = parent.open_child(
            name,
            expected_identity=identity,
            description="managed-output cleanup directory",
        )
        try:
            _verify_binding_boundary(
                child,
                expected_device=self._destination_device,
                expected_mount_id=self._destination_mount_id,
            )
            if child.list_names():
                raise OSError(
                    "Managed-output cleanup directory contains unknown entries: "
                    + path
                )
        finally:
            child.close()
        changed_mode = os.name == "nt" and not bool(current.st_mode & stat.S_IWUSR)
        if changed_mode:
            self._chmod_directory_exact(
                parent,
                name,
                identity,
                mode | stat.S_IWUSR,
            )
        try:
            _before_workspace_phase("before_cleanup_directory_remove", path)
            final = parent.stat(name)
            if (
                _path_is_redirected(path, final)
                or not stat.S_ISDIR(final.st_mode)
                or (final.st_dev, final.st_ino) != identity
            ):
                raise OSError(f"Managed-output cleanup directory changed: {path}")
            if parent.strategy == "posix_dir_fd":
                os.rmdir(name, dir_fd=parent.descriptor)
            else:
                parent.verify_path()
                os.rmdir(path)
                parent.verify_path()
        except BaseException as error:
            if changed_mode and parent.lexists(name):
                try:
                    self._chmod_directory_exact(
                        parent,
                        name,
                        identity,
                        mode,
                    )
                except BaseException as restore_error:
                    error.add_note(
                        "Restoring the read-only cleanup directory also failed: "
                        + str(restore_error)
                    )
            raise
        if parent.lexists(name):
            raise OSError(f"Managed-output cleanup directory remained: {path}")

    def _remove_cleanup_entries(
        self,
        directory: VerifiedDirectory,
        entries: list[_CleanupEntry],
    ) -> None:
        self._verify_cleanup_names(directory, entries)
        for entry in entries:
            if entry.removed:
                continue
            self._verify_cleanup_names(directory, entries)
            if not entry.quarantined:
                self._verify_cleanup_entry(directory, entry)
                try:
                    _move_entry_exact(
                        directory,
                        entry.current_name,
                        entry.cleanup_name,
                        entry.identity,
                        expect_directory=entry.is_directory,
                    )
                except BaseException:
                    if (
                        not directory.lexists(entry.current_name)
                        and directory.lexists(entry.cleanup_name)
                    ):
                        cleanup_stat = directory.stat(entry.cleanup_name)
                        if (
                            cleanup_stat.st_dev,
                            cleanup_stat.st_ino,
                        ) == entry.identity:
                            entry.current_name = entry.cleanup_name
                            entry.quarantined = True
                    raise
                entry.current_name = entry.cleanup_name
                entry.quarantined = True
            self._verify_cleanup_entry(directory, entry)
            if entry.is_directory:
                child = directory.open_child(
                    entry.current_name,
                    expected_identity=entry.identity,
                    description="managed-output cleanup directory",
                )
                try:
                    _verify_binding_boundary(
                        child,
                        expected_device=self._destination_device,
                        expected_mount_id=self._destination_mount_id,
                    )
                    self._remove_cleanup_entries(child, entry.children)
                finally:
                    child.close()
                self._rmdir_exact(
                    directory,
                    entry.current_name,
                    entry.identity,
                    entry.mode,
                )
            else:
                self._unlink_cleanup_file(directory, entry)
            entry.removed = True
        self._verify_cleanup_names(directory, entries)

    def _reopen_stage(self) -> None:
        stage_stat = self._staging_parent.stat(self._stage_name)
        stage_identity = stage_stat.st_dev, stage_stat.st_ino
        stage = self._staging_parent.open_child(
            self._stage_name,
            expected_identity=stage_identity,
            description="managed-output stage",
        )
        if stage_identity != self._stage_identity:
            stage.close()
            raise OSError(
                "Managed-output stage identity changed while reopening: "
                + self._staging_parent.child_path(self._stage_name)
            )
        _verify_binding_boundary(
            stage,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
        )
        self._stage = stage

    def cleanup(self) -> None:
        self._require_open()
        if self._cleaned:
            return
        if self._preserve_stage:
            raise OSError(
                "Managed-output workspace is preserving exact recovery state for "
                f"transaction {self._transaction_id}"
            )
        self._verify_base()
        stage = self._require_stage()
        _verify_binding_boundary(
            stage,
            expected_device=self._destination_device,
            expected_mount_id=self._destination_mount_id,
        )
        if self._cleanup_entries is None:
            self._verify_stage_marker()
            cleanup_entries = self._capture_cleanup_entries(
                stage,
                counter=[0],
                require_stage_marker=True,
            )
            self._cleanup_entries = cleanup_entries
        else:
            cleanup_entries = self._cleanup_entries
        if not self._stage_quarantined:
            cleanup_name = (
                _STAGE_CLEANUP_PREFIX
                + self._transaction_id
                + _STAGE_CLEANUP_SUFFIX
            )
            _before_workspace_phase(
                "before_stage_cleanup_quarantine",
                stage.path,
            )
            stage_identity = stage.identity
            if stage.strategy == "windows_handle":
                stage.close()
                self._stage = None
            try:
                _move_entry_exact(
                    self._staging_parent,
                    self._stage_name,
                    cleanup_name,
                    stage_identity,
                    expect_directory=True,
                )
            except BaseException:
                if self._stage is None:
                    try:
                        self._reopen_stage()
                    except BaseException:
                        pass
                raise
            self._stage_name = cleanup_name
            self._stage_quarantined = True
            if self._stage is None:
                self._reopen_stage()
            else:
                self._stage.path = self._staging_parent.child_path(cleanup_name)
                self._stage.verify_path()
            stage = self._require_stage()
        self._remove_cleanup_entries(stage, cleanup_entries)
        stage_identity = stage.identity
        stage_mode = stat.S_IMODE(_binding_stat(stage).st_mode)
        stage.close()
        self._stage = None
        try:
            self._rmdir_exact(
                self._staging_parent,
                self._stage_name,
                stage_identity,
                stage_mode,
            )
        except BaseException:
            if self._staging_parent.lexists(self._stage_name):
                try:
                    self._reopen_stage()
                except BaseException:
                    pass
            raise
        self._staging_parent.sync()
        self._cleaned = True

    def close(self) -> None:
        if self._closed:
            return
        active_error: BaseException | None = None
        if not self._preserve_stage:
            try:
                self.cleanup()
            except BaseException as error:
                active_error = error
        if self._stage is not None:
            try:
                self._stage.close()
            except BaseException as error:
                if active_error is None:
                    active_error = error
                else:
                    active_error.add_note(f"Closing the workspace stage also failed: {error}")
            self._stage = None
        try:
            self._staging_parent.close()
        except BaseException as error:
            if active_error is None:
                active_error = error
            else:
                active_error.add_note(f"Closing the staging parent also failed: {error}")
        try:
            self._destination_lock.close()
        except BaseException as error:
            if active_error is None:
                active_error = error
            else:
                active_error.add_note(f"Releasing the destination lock also failed: {error}")
        try:
            self._destination.close()
        except BaseException as error:
            if active_error is None:
                active_error = error
            else:
                active_error.add_note(f"Closing the destination also failed: {error}")
        self._closed = True
        if active_error is not None:
            raise active_error

    def __exit__(
        self,
        _exc_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None:
        try:
            self.close()
        except BaseException as close_error:
            if active_error is None:
                raise
            active_error.add_note(
                "Managed-output workspace cleanup also failed; exact private "
                f"state was preserved: {close_error}"
            )
        return None
__all__ = [
    "DESTINATION_LOCK_NAME",
    "ManagedFileSnapshot",
    "ManagedOutputWorkspace",
    "StagedFileReceipt",
    "WORKSPACE_PARENT_MARKER_NAME",
    "WORKSPACE_PARENT_NAME",
    "WORKSPACE_STAGE_MARKER_NAME",
]
