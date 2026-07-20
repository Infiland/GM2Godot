from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import os
import posixpath
import secrets
import stat
import sys
import tempfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, BinaryIO, Callable, Iterable, TypeVar, cast

from src.localization import get_localized
from src.conversion.atomic_generated_text import (
    atomic_write_confined_generated_text,
)
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_paths import (
    IncludedFilePathAssignment,
    canonical_included_file_lookup_path,
    plan_included_file_paths,
)
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    render_included_file_registry,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath


@dataclass(frozen=True)
class _IncludedFileSource:
    filesystem_path: str
    relative_path: str
    owner_source_path: str


@dataclass(frozen=True)
class _DeclaredIncludedFile:
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str | None


@dataclass(frozen=True)
class _IncludedFileConversionPlan:
    requested_keys: tuple[str, ...]
    available_files: tuple[_IncludedFileSource, ...]
    skipped_keys: tuple[str, ...]


_PathIdentity = tuple[int, int]
_PathFingerprint = tuple[int, int, int, int, int, int]
_PathHandleBinding = tuple[int, int, int, int, int, int]
_HandleState = tuple[int, int, int, int, int, int, int]
_IncludedSourceFingerprint = tuple[int, int, int, int, int, int]
_IncludedSourceDirectoryIdentity = tuple[str, _PathIdentity]
_IncludedCleanupFileState = tuple[int, str, _PathFingerprint]
_INCLUDED_FILES_ROOT_NAME = "included_files"
_INCLUDED_FILES_STAGE_PREFIX = ".gm2godot-included-files-"
_INCLUDED_FILES_LOCK_NAME = ".gm2godot-included-files.lock"
_INCLUDED_FILES_LOCK_TEMP_PREFIX = ".gm2godot-included-files-lock."
_INCLUDED_FILES_LOCK_CLEANUP_PREFIX = ".gm2godot-included-files-lock-cleanup."
_INCLUDED_FILES_JOURNAL_NAME = ".gm2godot-included-files-transaction.json"
_INCLUDED_FILES_COMMIT_NAME = ".gm2godot-included-files-commit.json"
_INCLUDED_FILES_JOURNAL_TEMP_PREFIX = ".gm2godot-included-files-journal."
_INCLUDED_FILES_COMMIT_TEMP_PREFIX = ".gm2godot-included-files-commit."
_INCLUDED_FILES_STAGE_MARKER_NAME = ".gm2godot-included-files-stage.json"
_INCLUDED_FILES_CLEANUP_PREFIX = ".gm2godot-included-cleanup."
_INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION = 1
_INCLUDED_FILES_RECOVERY_FORMAT_VERSION = 2
_INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION = 1
_INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER = 2
# The canonical cap is a parser-memory safety boundary, not a scaling knob.
# Format v2 removes repeated field names and uses fixed-width integer metadata
# so its exact serialized size can be preflighted before payload staging.
_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES = 16 * 1024 * 1024
_INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES = 100_000
_INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS = 16
_INCLUDED_FILES_RECOVERY_INTEGER_MAX = (
    1 << (_INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS * 4)
) - 1
_INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256 = "0" * 64
_INCLUDED_FILES_LOCK_CONTENT = b"GM2Godot Included Files lock v1\n"
_WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES = frozenset(
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

_IncludedWorkerItem = TypeVar("_IncludedWorkerItem")
_IncludedWorkerResult = TypeVar("_IncludedWorkerResult")


def _run_bounded_included_worker_phase(
    items: Iterable[_IncludedWorkerItem],
    *,
    max_workers: int,
    conversion_running: ConversionRunning,
    submit: Callable[
        [ThreadPoolExecutor, _IncludedWorkerItem],
        Future[_IncludedWorkerResult],
    ],
    consume: Callable[
        [_IncludedWorkerItem, Future[_IncludedWorkerResult]],
        bool,
    ],
) -> bool:
    """Run an Included Files phase with concurrency-proportional bookkeeping."""
    if max_workers < 1:
        raise ValueError("Included Files max_workers must be at least one")

    window_size = max_workers * _INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER
    item_iterator = iter(items)
    pending: dict[Future[_IncludedWorkerResult], _IncludedWorkerItem] = {}
    input_exhausted = False
    accepting_work = conversion_running()
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        while accepting_work:
            while not input_exhausted and len(pending) < window_size:
                if not conversion_running():
                    accepting_work = False
                    break
                try:
                    item = next(item_iterator)
                except StopIteration:
                    input_exhausted = True
                    break
                pending[submit(executor, item)] = item

            if not accepting_work or not pending:
                break

            done, _not_done = wait(
                tuple(pending),
                return_when=FIRST_COMPLETED,
            )
            completed = tuple(
                (future, pending[future])
                for future in tuple(pending)
                if future in done
            )
            for future, _item in completed:
                del pending[future]

            for future, item in completed:
                if not consume(item, future):
                    accepting_work = False
                    break
                if not conversion_running():
                    accepting_work = False
                    break

        return accepting_work and input_exhausted and not pending
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


@dataclass(frozen=True)
class _IncludedPayloadReceipt:
    source_fingerprint: _IncludedSourceFingerprint
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class _IncludedCopyReceipt:
    payload: _IncludedPayloadReceipt
    output_fingerprint: _PathFingerprint
    output_ctime_ns: int
    output_handle_state: _HandleState

    @property
    def source_fingerprint(self) -> _IncludedSourceFingerprint:
        return self.payload.source_fingerprint

    @property
    def byte_count(self) -> int:
        return self.payload.byte_count

    @property
    def sha256(self) -> str:
        return self.payload.sha256


@dataclass(frozen=True)
class _IncludedSourceBinding:
    filesystem_path: str
    canonical_path: str
    directory_identities: tuple[_IncludedSourceDirectoryIdentity, ...]
    lexical_state: _HandleState
    path_state: _HandleState
    handle_state: _HandleState


@dataclass(frozen=True)
class _IncludedNoOpSourceReceipt:
    logical_path: str
    assigned_path: str
    binding: _IncludedSourceBinding
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class _IncludedGenerationMatch:
    unchanged: bool
    source_receipts: tuple[_IncludedNoOpSourceReceipt, ...]


@dataclass(frozen=True)
class _IncludedGenerationContentReceipt:
    transaction_id: str
    generation_identity: _PathIdentity
    stage_container_identity: _PathIdentity
    source: _IncludedNoOpSourceReceipt
    staged_output_path: str
    public_output_path: str
    output: _IncludedCopyReceipt


@dataclass(frozen=True)
class _IncludedTreeEntry:
    relative_path: str
    kind: str
    fingerprint: _PathFingerprint
    ctime_ns: int | None
    content_sha256: str | None


@dataclass(frozen=True)
class _IncludedTreeSnapshot:
    root_fingerprint: _PathFingerprint | None
    entries: tuple[_IncludedTreeEntry, ...]

    @property
    def identity(self) -> _PathIdentity | None:
        if self.root_fingerprint is None:
            return None
        return self.root_fingerprint[:2]


@dataclass(frozen=True)
class _IncludedTreeDescriptorBinding:
    parent_fd: int
    name: str
    fingerprint: _PathFingerprint
    display_path: str


@dataclass(frozen=True)
class _IncludedTreePathBinding:
    path: str
    identity: _PathIdentity


@dataclass(frozen=True)
class _IncludedRegistrySnapshot:
    directory_identity: _PathIdentity | None
    file_identity: _PathIdentity | None
    file_mode: int | None
    content: bytes | None


@dataclass(frozen=True)
class _IncludedRecoveryRecordSizes:
    journal_bytes: int
    commit_bytes: int


@dataclass(frozen=True)
class _IncludedOutputSetTransaction:
    project_identity: _PathIdentity
    stage_container_path: str
    stage_container_identity: _PathIdentity
    staged_container_snapshot: _IncludedTreeSnapshot
    staged_root_path: str
    staged_root_snapshot: _IncludedTreeSnapshot
    staged_registry_path: str
    staged_registry_identity: _PathIdentity
    staged_registry_mode: int
    staged_registry_content: bytes
    previous_root_snapshot: _IncludedTreeSnapshot
    previous_registry_snapshot: _IncludedRegistrySnapshot
    recovery_record_sizes: _IncludedRecoveryRecordSizes | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    publication_transaction_id: str | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    content_receipts: tuple[_IncludedGenerationContentReceipt, ...] = field(
        default=(),
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class _IncludedRecoveryJournal:
    format_version: int
    transaction_id: str
    transaction: _IncludedOutputSetTransaction
    root_backup_path: str
    registry_backup_path: str
    registry_directory_path: str
    registry_directory_identity: _PathIdentity
    registry_directory_created: bool


@dataclass(frozen=True)
class _IncludedCommitMarker:
    format_version: int
    transaction_id: str
    project_identity: _PathIdentity
    root_identity: _PathIdentity
    root_snapshot_sha256: str
    registry_directory_identity: _PathIdentity
    registry_identity: _PathIdentity
    registry_content_sha256: str


@dataclass
class _IncludedProjectLock:
    file_descriptor: int
    path: str
    windows: bool


def _windows_included_file_locking(
    file_descriptor: int,
    mode: int,
) -> None:
    import msvcrt

    locking = cast(
        Callable[[int, int, int], None],
        getattr(msvcrt, "locking"),
    )
    locking(file_descriptor, mode, 1)


class _IncludedOutputSetCancelled(Exception):
    """Signal cancellation while a reversible output-set commit is active."""


_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)

_WINDOWS_GENERIC_READ = 0x80000000
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_WINDOWS_MOVEFILE_WRITE_THROUGH = 0x00000008


def _included_descriptor_paths_supported() -> bool:
    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.chmod in os.supports_fd
        and os.listdir in os.supports_fd
        and all(
            operation in os.supports_dir_fd
            for operation in (
                os.mkdir,
                os.open,
                os.rmdir,
                os.stat,
                os.unlink,
            )
        )
    )


def _included_native_noreplace_available() -> bool:
    return sys.platform == "darwin" or sys.platform.startswith("linux")


def _open_pinned_included_directory(path: str) -> int:
    if not _included_descriptor_paths_supported():
        raise OSError("Descriptor-pinned Included Files paths are unavailable")
    absolute_path = os.path.abspath(path)
    components = [
        component for component in absolute_path.split(os.sep) if component
    ]
    if not components:
        return os.open(os.sep, _DIRECTORY_OPEN_FLAGS)
    platform_anchor = os.path.join(os.sep, components[0])
    resolved_anchor = os.path.realpath(platform_anchor)
    current_fd = os.open(resolved_anchor, _DIRECTORY_OPEN_FLAGS)
    try:
        for component in components[1:]:
            child_fd = os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_pinned_included_parent(path: str) -> tuple[int, str]:
    absolute_path = os.path.abspath(path)
    parent_path, name = os.path.split(absolute_path)
    if not name:
        raise OSError(f"Included Files path has no movable leaf: {path}")
    return _open_pinned_included_directory(parent_path), name


def _directory_identity_from_fd(directory_fd: int) -> _PathIdentity:
    directory_stat = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OSError("Pinned Included Files descriptor is not a directory")
    return directory_stat.st_dev, directory_stat.st_ino


def _verify_included_directory_fd(
    directory_fd: int,
    expected_identity: _PathIdentity | None,
    display_path: str,
) -> _PathIdentity:
    current_identity = _directory_identity_from_fd(directory_fd)
    if expected_identity is not None and current_identity != expected_identity:
        raise OSError(f"Included Files directory changed: {display_path}")
    return current_identity


def _included_entry_stat_at(
    parent_fd: int,
    name: str,
) -> os.stat_result | None:
    try:
        return os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None


def _verify_included_entry_at(
    parent_fd: int,
    name: str,
    expected_fingerprint: _PathFingerprint,
    display_path: str,
) -> None:
    current_stat = _included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or _included_path_fingerprint(current_stat) != expected_fingerprint
    ):
        raise OSError(f"Included Files entry changed: {display_path}")


def _rename_included_transaction_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    if not _included_native_noreplace_available():
        raise OSError(
            "Atomic non-replacing Included Files rename is unavailable on "
            f"{sys.platform}"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    function_name = (
        "renameatx_np" if sys.platform == "darwin" else "renameat2"
    )
    raw_function = getattr(libc, function_name, None)
    if raw_function is None:
        raise OSError(
            f"Atomic non-replacing Included Files rename is unavailable: {function_name}"
        )
    rename_function = cast(
        Callable[[int, bytes, int, bytes, int], int],
        raw_function,
    )
    rename_exclusive_flag = 0x00000004 if sys.platform == "darwin" else 1
    ctypes.set_errno(0)
    result = rename_function(
        source_parent_fd,
        os.fsencode(source_name),
        destination_parent_fd,
        os.fsencode(destination_name),
        rename_exclusive_flag,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )


def _before_included_transaction_rename(
    _source_parent_fd: int,
    _source_name: str,
) -> None:
    """Narrow test seam immediately before a namespace mutation."""


def _before_included_transaction_rename_fallback(
    _source: str,
    _destination: str,
) -> None:
    """Narrow fallback test seam immediately before a namespace mutation."""


def _preserve_or_restore_unexpected_moved_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    source_display_path: str,
    destination_display_path: str,
) -> OSError:
    try:
        _rename_included_transaction_entry_at(
            destination_parent_fd,
            destination_name,
            source_parent_fd,
            source_name,
        )
    except OSError as restore_error:
        destination_parent_path = os.path.dirname(destination_display_path)
        quarantine_name = (
            f".{os.path.basename(destination_display_path)}."
            f"{secrets.token_hex(8)}.quarantine"
        )
        quarantine_path = os.path.join(
            destination_parent_path,
            quarantine_name,
        )
        try:
            _rename_included_transaction_entry_at(
                destination_parent_fd,
                destination_name,
                destination_parent_fd,
                quarantine_name,
            )
        except OSError as quarantine_error:
            error = OSError(
                "Unexpected Included Files replacement was preserved at "
                f"{destination_display_path!r}; automatic restore to "
                f"{source_display_path!r} failed"
            )
            error.add_note(f"Restore error: {restore_error}")
            error.add_note(f"Quarantine error: {quarantine_error}")
            return error
        error = OSError(
            "Unexpected Included Files replacement was preserved at "
            f"recoverable quarantine path {quarantine_path!r}; automatic "
            f"restore to {source_display_path!r} failed"
        )
        error.add_note(f"Restore error: {restore_error}")
        return error
    return OSError(
        "Unexpected Included Files replacement was restored without loss to "
        f"{source_display_path!r}; refused transaction move to "
        f"{destination_display_path!r}"
    )


def _preserve_or_restore_unexpected_moved_entry_fallback(
    source: str,
    destination: str,
) -> OSError:
    try:
        _rename_included_transaction_entry(destination, source)
    except OSError as restore_error:
        quarantine_path = (
            destination
            + "."
            + secrets.token_hex(8)
            + ".quarantine"
        )
        try:
            _rename_included_transaction_entry(destination, quarantine_path)
        except OSError as quarantine_error:
            error = OSError(
                "Unexpected Included Files replacement was preserved at "
                f"{destination!r}; automatic restore to {source!r} failed"
            )
            error.add_note(f"Restore error: {restore_error}")
            error.add_note(f"Quarantine error: {quarantine_error}")
            return error
        error = OSError(
            "Unexpected Included Files replacement was preserved at "
            f"recoverable quarantine path {quarantine_path!r}; automatic "
            f"restore to {source!r} failed"
        )
        error.add_note(f"Restore error: {restore_error}")
        return error
    return OSError(
        "Unexpected Included Files replacement was restored without loss to "
        f"{source!r}; refused transaction move to {destination!r}"
    )


def _included_output_path_is_redirected(
    path: str,
    path_stat: os.stat_result,
) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _included_linux_mount_id_from_fd(file_descriptor: int) -> int | None:
    """Return Linux's mount ID for an open path when procfs exposes it."""

    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(
            f"/proc/self/fdinfo/{file_descriptor}",
            encoding="ascii",
        ) as fdinfo:
            mount_id_values = [
                line.partition(":")[2].strip()
                for line in fdinfo
                if line.startswith("mnt_id:")
            ]
    except OSError:
        # Device comparison and ismount remain available on Linux systems that
        # intentionally run without a mounted/readable procfs.
        return None
    if (
        len(mount_id_values) != 1
        or not mount_id_values[0].isascii()
        or not mount_id_values[0].isdigit()
    ):
        raise OSError("Could not verify the Included Files Linux mount boundary")
    return int(mount_id_values[0])


def _included_directory_mount_id(
    path: str,
    expected_identity: _PathIdentity,
) -> int | None:
    """Read a directory mount ID without following a redirected leaf."""

    if not sys.platform.startswith("linux"):
        return None
    directory_fd = os.open(path, _DIRECTORY_OPEN_FLAGS)
    try:
        if _directory_identity_from_fd(directory_fd) != expected_identity:
            raise OSError(f"Included Files directory changed: {path}")
        return _included_linux_mount_id_from_fd(directory_fd)
    finally:
        os.close(directory_fd)


def _verify_included_mount_boundary(
    path: str,
    entry_stat: os.stat_result,
    expected_device: int,
    expected_mount_id: int | None,
    opened_descriptor: int,
) -> int | None:
    """Reject a managed entry that crosses out of its parent's mount."""

    try:
        is_mountpoint = os.path.ismount(path)
    except OSError as error:
        raise OSError(
            f"Could not verify the Included Files mount boundary: {path}"
        ) from error
    current_mount_id = _included_linux_mount_id_from_fd(opened_descriptor)
    if (
        entry_stat.st_dev != expected_device
        or is_mountpoint
        or (
            expected_mount_id is not None
            and current_mount_id != expected_mount_id
        )
    ):
        raise OSError(
            "Refusing an Included Files path that crosses a filesystem or "
            f"mount boundary: {path}"
        )
    return current_mount_id


def _verify_included_mount_boundary_path(
    path: str,
    entry_stat: os.stat_result,
    expected_device: int,
    expected_mount_id: int | None,
    *,
    expect_directory: bool,
) -> int | None:
    """Path fallback for mount checks, using an fd on Linux when available."""

    if not sys.platform.startswith("linux"):
        return _verify_included_mount_boundary(
            path,
            entry_stat,
            expected_device,
            expected_mount_id,
            -1,
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if expect_directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        expected_kind = stat.S_ISDIR if expect_directory else stat.S_ISREG
        if not expected_kind(opened_stat.st_mode) or not os.path.samestat(
            entry_stat,
            opened_stat,
        ):
            raise OSError(
                f"Included Files path changed while checking its mount: {path}"
            )
        return _verify_included_mount_boundary(
            path,
            opened_stat,
            expected_device,
            expected_mount_id,
            file_descriptor,
        )
    finally:
        os.close(file_descriptor)


def _included_path_fingerprint(path_stat: os.stat_result) -> _PathFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_mode,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_nlink,
    )


def _included_path_handle_binding(
    file_stat: os.stat_result,
) -> _PathHandleBinding:
    """Return metadata that is stable across path and handle stat on Windows."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        stat.S_IFMT(file_stat.st_mode),
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_nlink,
    )


def _included_handle_state(file_stat: os.stat_result) -> _HandleState:
    """Return metadata used to detect mutation of one open file handle."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
        file_stat.st_nlink,
    )


def _included_source_fingerprint(
    source_stat: os.stat_result,
) -> _IncludedSourceFingerprint:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        source_stat.st_mode,
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )


def _read_included_validation_chunk(opened_file: BinaryIO) -> bytes:
    """Read one validation chunk through a deterministic accounting seam."""

    return opened_file.read(1024 * 1024)


@lru_cache(maxsize=1)
def _windows_included_file_read_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows Included File read handles are unavailable")
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


@lru_cache(maxsize=1)
def _windows_included_transaction_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows Included Files transaction APIs are unavailable")
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    kernel32.MoveFileExW.restype = ctypes.c_int
    return kernel32


def _windows_included_transaction_error(
    operation: str,
    path: str,
) -> OSError:
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    format_error = cast(Callable[[int], str], getattr(ctypes, "FormatError"))
    error_number = get_last_error()
    return OSError(
        error_number,
        f"{operation}: {format_error(error_number).strip()}",
        path,
    )


def _windows_extended_included_path(path: str) -> str:
    """Return an absolute Win32 path that does not depend on MAX_PATH policy."""

    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _open_included_file_validation_stream(
    path: str,
    *,
    deny_writes: bool,
    no_follow: bool = False,
) -> BinaryIO:
    """Open a validation stream with requested sharing and link semantics."""

    if os.name != "nt":
        if no_follow:
            file_descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                return os.fdopen(file_descriptor, "rb")
            except BaseException:
                os.close(file_descriptor)
                raise
        return open(path, "rb")
    if not deny_writes and not no_follow:
        return open(path, "rb")

    kernel32 = _windows_included_file_read_api()
    handle_value = kernel32.CreateFileW(
        _windows_extended_included_path(path),
        _WINDOWS_GENERIC_READ,
        _WINDOWS_FILE_SHARE_READ,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_ATTRIBUTE_NORMAL
        | (_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT if no_follow else 0)
        | _WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle_value is None or handle_value == invalid_handle:
        get_last_error = cast(
            Callable[[], int],
            getattr(ctypes, "get_last_error"),
        )
        error_number = get_last_error()
        format_error = cast(
            Callable[[int], str],
            getattr(ctypes, "FormatError"),
        )
        raise OSError(
            error_number,
            format_error(error_number).strip(),
            path,
        )

    handle = cast(int, handle_value)
    try:
        import msvcrt

        file_descriptor = msvcrt.open_osfhandle(
            handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
    except BaseException:
        kernel32.CloseHandle(handle)
        raise
    try:
        return os.fdopen(file_descriptor, "rb")
    except BaseException:
        os.close(file_descriptor)
        raise


def _digest_open_included_file(
    opened_file: BinaryIO,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = _read_included_validation_chunk(opened_file)
        if not chunk:
            break
        digest.update(chunk)
        byte_count += len(chunk)
    return byte_count, digest.hexdigest()


def _digest_included_regular_file(
    path: str,
    expected_stat: os.stat_result,
    *,
    expected_device: int | None = None,
    expected_mount_id: int | None = None,
) -> str:
    expected_fingerprint = _included_path_fingerprint(expected_stat)
    expected_binding = _included_path_handle_binding(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    with _open_included_file_validation_stream(
        path,
        deny_writes=True,
        no_follow=True,
    ) as opened_file:
        opened_stat = os.fstat(opened_file.fileno())
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_path_handle_binding(opened_stat) != expected_binding
        ):
            raise OSError(f"Included Files file changed before hashing: {path}")
        if expected_device is not None:
            _verify_included_mount_boundary(
                path,
                opened_stat,
                expected_device,
                expected_mount_id,
                opened_file.fileno(),
            )
        opened_state = _included_handle_state(opened_stat)
        byte_count, content_sha256 = _digest_open_included_file(opened_file)
        current_opened_stat = os.fstat(opened_file.fileno())
        if (
            _included_handle_state(current_opened_stat) != opened_state
            or byte_count != expected_stat.st_size
        ):
            raise OSError(
                f"Included Files file changed while hashing: {path}"
            )

        current_stat = os.lstat(path)
        if (
            _included_output_path_is_redirected(path, current_stat)
            or not stat.S_ISREG(current_stat.st_mode)
            or _included_path_fingerprint(current_stat) != expected_fingerprint
            or current_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files file changed while hashing: {path}"
            )
    return content_sha256


def _capture_fallback_directory_ancestors(
    directory_path: str,
) -> tuple[tuple[str, _PathIdentity], ...]:
    absolute_path = os.path.abspath(directory_path)
    drive, tail = os.path.splitdrive(absolute_path)
    anchor = drive + os.sep
    components = [component for component in tail.split(os.sep) if component]
    if components:
        platform_anchor = os.path.join(anchor, components[0])
        current_path = os.path.realpath(platform_anchor)
        remaining_components = components[1:]
    else:
        current_path = anchor
        remaining_components = []
    identities: list[tuple[str, _PathIdentity]] = []
    for component in (None, *remaining_components):
        if component is not None:
            current_path = os.path.join(current_path, component)
        try:
            current_stat = os.lstat(current_path)
        except OSError as error:
            raise OSError(
                f"Included Files directory ancestor changed: {current_path}"
            ) from error
        if (
            _included_output_path_is_redirected(current_path, current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
        ):
            raise OSError(
                f"Refusing redirected or non-directory Included Files ancestor: "
                f"{current_path}"
            )
        identities.append(
            (current_path, (current_stat.st_dev, current_stat.st_ino))
        )
    return tuple(identities)


def _verify_fallback_directory_ancestors(
    identities: tuple[tuple[str, _PathIdentity], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            current_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Included Files directory ancestor changed: {directory_path}"
            ) from error
        if (
            _included_output_path_is_redirected(directory_path, current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
            or (current_stat.st_dev, current_stat.st_ino) != expected_identity
        ):
            raise OSError(
                f"Included Files directory ancestor changed: {directory_path}"
            )


def _capture_included_source_directory_identities(
    project_root: str,
    source_path: str,
) -> tuple[str, tuple[_IncludedSourceDirectoryIdentity, ...]]:
    canonical_root = os.path.normcase(os.path.realpath(project_root))
    canonical_path = os.path.normcase(os.path.realpath(source_path))
    try:
        contained = (
            os.path.commonpath((canonical_root, canonical_path))
            == canonical_root
        )
    except ValueError:
        contained = False
    if not contained or canonical_path == canonical_root:
        raise OSError(
            "GameMaker Included File source escapes the selected project: "
            f"{source_path}"
        )

    directory_path = canonical_root
    directory_identities: list[_IncludedSourceDirectoryIdentity] = []
    relative_directory = os.path.relpath(
        os.path.dirname(canonical_path),
        canonical_root,
    )
    components = (
        ()
        if relative_directory == os.curdir
        else tuple(relative_directory.split(os.sep))
    )
    for component in (None, *components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
        directory_stat = os.lstat(directory_path)
        if (
            _included_output_path_is_redirected(
                directory_path,
                directory_stat,
            )
            or not stat.S_ISDIR(directory_stat.st_mode)
        ):
            raise OSError(
                "GameMaker Included File source directory is redirected or "
                f"invalid: {directory_path}"
            )
        directory_identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return canonical_path, tuple(directory_identities)


def _included_directory_identity(path: str) -> _PathIdentity | None:
    if _included_descriptor_paths_supported():
        try:
            directory_fd = _open_pinned_included_directory(path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise OSError(
                f"Refusing redirected or non-directory Included Files path: {path}"
            ) from error
        try:
            return _directory_identity_from_fd(directory_fd)
        finally:
            os.close(directory_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_output_path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
    ):
        raise OSError(f"Refusing redirected or non-directory Included Files path: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    return (path_stat.st_dev, path_stat.st_ino)


def _included_regular_file_state_at(
    parent_fd: int,
    name: str,
    display_path: str,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    parent_stat = os.fstat(parent_fd)
    parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
    parent_mount_id = _included_linux_mount_id_from_fd(parent_fd)
    path_stat = _included_entry_stat_at(parent_fd, name)
    if path_stat is None:
        return None
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(
            f"Refusing redirected or non-regular Included Files path: {display_path}"
        )
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(
            f"Included Files path changed before reading: {display_path}"
        )
    expected_fingerprint = _included_path_fingerprint(path_stat)
    expected_ctime_ns = path_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_path_fingerprint(opened_stat) != expected_fingerprint
            or opened_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files path changed while reading: {display_path}"
            )
        _verify_included_mount_boundary(
            display_path,
            opened_stat,
            parent_identity[0],
            parent_mount_id,
            file_descriptor,
        )
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = opened_file.read()
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    current_stat = _included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_path_fingerprint(current_stat) != expected_fingerprint
        or current_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(
            f"Included Files path changed while reading: {display_path}"
        )
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )


def _before_included_fallback_regular_file_open(_path: str) -> None:
    """Narrow test seam before opening a fallback regular-file path."""


def _included_regular_file_state(
    path: str,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    expected_fallback_ancestors: (
        tuple[tuple[str, _PathIdentity], ...] | None
    ) = None,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    if _included_descriptor_paths_supported():
        try:
            parent_fd, name = _open_pinned_included_parent(path)
        except FileNotFoundError:
            return None
        try:
            _verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            return _included_regular_file_state_at(
                parent_fd,
                name,
                path,
                allowed_identities=allowed_identities,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    if expected_fallback_ancestors is None:
        parent_identities = _capture_fallback_directory_ancestors(parent_path)
    else:
        parent_identities = expected_fallback_ancestors
        if (
            not parent_identities
            or os.path.normcase(os.path.abspath(parent_identities[-1][0]))
            != os.path.normcase(parent_path)
        ):
            raise OSError(
                f"Included Files fallback ancestry does not bind parent: {path}"
            )
    if (
        expected_parent_identity is not None
        and parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files file parent changed: {path}")
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
    ):
        raise OSError(f"Refusing redirected or non-regular Included Files path: {path}")
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(f"Included Files path changed before reading: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    parent_mount_id = _included_directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    _verify_fallback_directory_ancestors(parent_identities)
    _before_included_fallback_regular_file_open(path)
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode) or not os.path.samestat(
            path_stat,
            opened_stat,
        ):
            raise OSError(f"Included Files path changed while reading: {path}")
        _verify_included_mount_boundary(
            path,
            opened_stat,
            parent_identities[-1][1][0],
            parent_mount_id,
            file_descriptor,
        )
        _verify_fallback_directory_ancestors(parent_identities)
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = opened_file.read()
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)

    current_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_path_fingerprint(current_stat)
        != _included_path_fingerprint(path_stat)
        or current_stat.st_ctime_ns != path_stat.st_ctime_ns
    ):
        raise OSError(f"Included Files path changed while reading: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )


def _digest_included_regular_file_at(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    display_path: str,
    *,
    expected_device: int | None = None,
    expected_mount_id: int | None = None,
) -> str:
    expected_fingerprint = _included_path_fingerprint(expected_stat)
    expected_binding = _included_path_handle_binding(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_path_handle_binding(opened_stat) != expected_binding
        ):
            raise OSError(
                f"Included Files file changed before hashing: {display_path}"
            )
        if expected_device is not None:
            _verify_included_mount_boundary(
                display_path,
                opened_stat,
                expected_device,
                expected_mount_id,
                file_descriptor,
            )
        opened_state = _included_handle_state(opened_stat)
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            byte_count, content_sha256 = _digest_open_included_file(opened_file)
            current_opened_stat = os.fstat(opened_file.fileno())
            if (
                _included_handle_state(current_opened_stat) != opened_state
                or byte_count != expected_stat.st_size
            ):
                raise OSError(
                    "Included Files file changed while hashing: "
                    f"{display_path}"
                )

            current_stat = _included_entry_stat_at(parent_fd, name)
            if (
                current_stat is None
                or not stat.S_ISREG(current_stat.st_mode)
                or _included_path_fingerprint(current_stat)
                != expected_fingerprint
                or current_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(
                    "Included Files file changed while hashing: "
                    f"{display_path}"
                )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    return content_sha256


def _verify_included_regular_file_mount_boundary_at(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    display_path: str,
    expected_device: int,
    expected_mount_id: int | None,
) -> None:
    expected_fingerprint = _included_path_fingerprint(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_path_fingerprint(opened_stat) != expected_fingerprint
            or opened_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files file changed while checking its mount: {display_path}"
            )
        _verify_included_mount_boundary(
            display_path,
            opened_stat,
            expected_device,
            expected_mount_id,
            file_descriptor,
        )
    finally:
        os.close(file_descriptor)


def _open_included_tree_directory_at(parent_fd: int, name: str) -> int:
    return os.open(
        name,
        _DIRECTORY_OPEN_FLAGS,
        dir_fd=parent_fd,
    )


def _verify_included_tree_descriptor_binding(
    binding: _IncludedTreeDescriptorBinding,
) -> None:
    """Verify one link in a retained descriptor chain."""

    _verify_included_entry_at(
        binding.parent_fd,
        binding.name,
        binding.fingerprint,
        binding.display_path,
    )


def _verify_included_tree_path_binding(
    binding: _IncludedTreePathBinding,
) -> os.stat_result:
    """Verify one fallback directory through its complete current path."""

    try:
        current_stat = os.lstat(binding.path)
    except OSError as error:
        raise OSError(
            f"Included Files directory changed: {binding.path}"
        ) from error
    if (
        _included_output_path_is_redirected(binding.path, current_stat)
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != binding.identity
    ):
        raise OSError(f"Included Files directory changed: {binding.path}")
    return current_stat


def _capture_included_tree_from_fd(
    directory_fd: int,
    relative_directory: str,
    display_path: str,
    binding: _IncludedTreeDescriptorBinding,
    boundary_device: int,
    boundary_mount_id: int | None,
    *,
    include_content: bool,
) -> list[_IncludedTreeEntry]:
    _verify_included_tree_descriptor_binding(binding)
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as error:
        raise OSError(
            f"Could not inspect Included Files directory: {display_path}"
        ) from error
    entries: list[_IncludedTreeEntry] = []
    for name in names:
        _verify_included_tree_descriptor_binding(binding)
        entry_path = os.path.join(display_path, name)
        entry_stat = _included_entry_stat_at(directory_fd, name)
        if entry_stat is None:
            raise OSError(
                f"Included Files tree changed while inspecting: {entry_path}"
            )
        relative_path = posixpath.join(relative_directory, name)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise OSError(
                f"Refusing redirected entry in Included Files tree: {entry_path}"
            )
        entry_fingerprint = _included_path_fingerprint(entry_stat)
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = _open_included_tree_directory_at(directory_fd, name)
            try:
                child_stat = os.fstat(child_fd)
                if (
                    not stat.S_ISDIR(child_stat.st_mode)
                    or _included_path_fingerprint(child_stat)
                    != entry_fingerprint
                ):
                    raise OSError(
                        f"Included Files directory changed: {entry_path}"
                    )
                _verify_included_mount_boundary(
                    entry_path,
                    child_stat,
                    boundary_device,
                    boundary_mount_id,
                    child_fd,
                )
                child_binding = _IncludedTreeDescriptorBinding(
                    parent_fd=directory_fd,
                    name=name,
                    fingerprint=entry_fingerprint,
                    display_path=entry_path,
                )

                entries.extend(
                    _capture_included_tree_from_fd(
                        child_fd,
                        relative_path,
                        entry_path,
                        child_binding,
                        boundary_device,
                        boundary_mount_id,
                        include_content=include_content,
                    )
                )
            finally:
                os.close(child_fd)
            _verify_included_tree_descriptor_binding(binding)
            _verify_included_tree_descriptor_binding(child_binding)
            kind = "directory"
            ctime_ns = None
            content_sha256 = None
        elif stat.S_ISREG(entry_stat.st_mode):
            kind = "file"
            ctime_ns = entry_stat.st_ctime_ns
            if include_content:
                content_sha256 = _digest_included_regular_file_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    expected_device=boundary_device,
                    expected_mount_id=boundary_mount_id,
                )
            else:
                _verify_included_regular_file_mount_boundary_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    boundary_device,
                    boundary_mount_id,
                )
                content_sha256 = None
        else:
            raise OSError(
                f"Refusing non-regular entry in Included Files tree: {entry_path}"
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=entry_fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    _verify_included_tree_descriptor_binding(binding)
    return entries


def _capture_included_tree_descriptor(
    root_path: str,
    expected_parent_identity: _PathIdentity | None,
    *,
    include_content: bool,
) -> _IncludedTreeSnapshot:
    parent_fd, root_name = _open_pinned_included_parent(root_path)
    try:
        parent_stat = os.fstat(parent_fd)
        parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        parent_mount_id = _included_linux_mount_id_from_fd(parent_fd)
        if (
            expected_parent_identity is not None
            and parent_identity != expected_parent_identity
        ):
            raise OSError(f"Included Files root parent changed: {root_path}")
        parent_path = os.path.dirname(os.path.abspath(root_path))
        root_stat = _included_entry_stat_at(parent_fd, root_name)
        if root_stat is None:
            if _included_directory_identity(parent_path) != parent_identity:
                raise OSError(
                    f"Included Files root parent changed: {parent_path}"
                )
            return _IncludedTreeSnapshot(root_fingerprint=None, entries=())
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(
                f"Refusing redirected or non-directory Included Files root: {root_path}"
            )
        root_fingerprint = _included_path_fingerprint(root_stat)
        root_fd = _open_included_tree_directory_at(parent_fd, root_name)
        try:
            opened_root_stat = os.fstat(root_fd)
            if _included_path_fingerprint(opened_root_stat) != root_fingerprint:
                raise OSError(
                    f"Included Files root changed while opening: {root_path}"
                )
            root_mount_id = _verify_included_mount_boundary(
                root_path,
                opened_root_stat,
                parent_stat.st_dev,
                parent_mount_id,
                root_fd,
            )
            root_binding = _IncludedTreeDescriptorBinding(
                parent_fd=parent_fd,
                name=root_name,
                fingerprint=root_fingerprint,
                display_path=root_path,
            )

            entries = _capture_included_tree_from_fd(
                root_fd,
                "",
                root_path,
                root_binding,
                opened_root_stat.st_dev,
                root_mount_id,
                include_content=include_content,
            )
        finally:
            os.close(root_fd)
        _verify_included_tree_descriptor_binding(root_binding)
        if _included_directory_identity(parent_path) != parent_identity:
            raise OSError(f"Included Files root parent changed: {parent_path}")
        return _IncludedTreeSnapshot(
            root_fingerprint=root_fingerprint,
            entries=tuple(
                sorted(
                    entries,
                    key=lambda entry: (entry.relative_path, entry.kind),
                )
            ),
        )
    finally:
        os.close(parent_fd)


def _after_included_fallback_tree_directory_scan(_path: str) -> None:
    """Narrow test seam after a fallback path scan returns its entries."""


def _capture_included_tree_fallback(
    root_path: str,
    expected_parent_identity: _PathIdentity | None,
    *,
    include_content: bool,
) -> _IncludedTreeSnapshot:
    root_parent_path = os.path.dirname(os.path.abspath(root_path))
    root_parent_identities = _capture_fallback_directory_ancestors(
        root_parent_path
    )
    if (
        expected_parent_identity is not None
        and root_parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files root parent changed: {root_path}")
    try:
        root_stat = os.lstat(root_path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(root_parent_identities)
        return _IncludedTreeSnapshot(root_fingerprint=None, entries=())
    if (
        _included_output_path_is_redirected(root_path, root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected or non-directory Included Files root: {root_path}"
        )

    root_fingerprint = _included_path_fingerprint(root_stat)
    parent_mount_id = _included_directory_mount_id(
        root_parent_path,
        root_parent_identities[-1][1],
    )
    root_mount_id = _verify_included_mount_boundary_path(
        root_path,
        root_stat,
        root_parent_identities[-1][1][0],
        parent_mount_id,
        expect_directory=True,
    )
    entries: list[_IncludedTreeEntry] = []
    pending: list[tuple[str, _IncludedTreePathBinding]] = [
        (
            "",
            _IncludedTreePathBinding(
                path=root_path,
                identity=(root_stat.st_dev, root_stat.st_ino),
            ),
        )
    ]
    while pending:
        relative_directory, directory_binding = pending.pop()
        directory_path = directory_binding.path
        directory_stat = _verify_included_tree_path_binding(directory_binding)
        _verify_included_mount_boundary_path(
            directory_path,
            directory_stat,
            root_stat.st_dev,
            root_mount_id,
            expect_directory=True,
        )
        _verify_included_tree_path_binding(directory_binding)
        try:
            directory_entries = sorted(
                os.scandir(directory_path),
                key=lambda entry: entry.name,
            )
        except OSError as error:
            raise OSError(
                f"Could not inspect Included Files directory: {directory_path}"
            ) from error
        _after_included_fallback_tree_directory_scan(directory_path)
        _verify_included_tree_path_binding(directory_binding)
        for directory_entry in directory_entries:
            _verify_included_tree_path_binding(directory_binding)
            entry_path = os.path.join(directory_path, directory_entry.name)
            try:
                entry_stat = os.lstat(entry_path)
            except OSError as error:
                raise OSError(
                    f"Included Files tree changed while inspecting: {entry_path}"
                ) from error
            relative_path = posixpath.join(
                relative_directory,
                directory_entry.name,
            )
            if _included_output_path_is_redirected(entry_path, entry_stat):
                raise OSError(
                    f"Refusing redirected entry in Included Files tree: {entry_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                _verify_included_mount_boundary_path(
                    entry_path,
                    entry_stat,
                    root_stat.st_dev,
                    root_mount_id,
                    expect_directory=True,
                )
                kind = "directory"
                ctime_ns = None
                content_sha256 = None
                pending.append(
                    (
                        relative_path,
                        _IncludedTreePathBinding(
                            path=entry_path,
                            identity=(entry_stat.st_dev, entry_stat.st_ino),
                        ),
                    )
                )
            elif stat.S_ISREG(entry_stat.st_mode):
                kind = "file"
                ctime_ns = entry_stat.st_ctime_ns
                _verify_included_tree_path_binding(directory_binding)
                if include_content:
                    content_sha256 = _digest_included_regular_file(
                        entry_path,
                        entry_stat,
                        expected_device=root_stat.st_dev,
                        expected_mount_id=root_mount_id,
                    )
                else:
                    _verify_included_mount_boundary_path(
                        entry_path,
                        entry_stat,
                        root_stat.st_dev,
                        root_mount_id,
                        expect_directory=False,
                    )
                    content_sha256 = None
            else:
                raise OSError(
                    f"Refusing non-regular entry in Included Files tree: {entry_path}"
                )
            entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=_included_path_fingerprint(entry_stat),
                    ctime_ns=ctime_ns,
                    content_sha256=content_sha256,
                )
            )
            _verify_included_tree_path_binding(directory_binding)
        _verify_included_tree_path_binding(directory_binding)

    _verify_fallback_directory_ancestors(root_parent_identities)
    current_root_stat = os.lstat(root_path)
    if (
        _included_output_path_is_redirected(root_path, current_root_stat)
        or not stat.S_ISDIR(current_root_stat.st_mode)
        or _included_path_fingerprint(current_root_stat) != root_fingerprint
    ):
        raise OSError(f"Included Files root changed while inspecting: {root_path}")
    return _IncludedTreeSnapshot(
        root_fingerprint=root_fingerprint,
        entries=tuple(
            sorted(
                entries,
                key=lambda entry: (entry.relative_path, entry.kind),
            )
        ),
    )


def _capture_included_tree(
    root_path: str,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    include_content: bool = True,
) -> _IncludedTreeSnapshot:
    if _included_descriptor_paths_supported():
        return _capture_included_tree_descriptor(
            root_path,
            expected_parent_identity,
            include_content=include_content,
        )
    return _capture_included_tree_fallback(
        root_path,
        expected_parent_identity,
        include_content=include_content,
    )


def _verify_included_tree_snapshot(
    root_path: str,
    expected: _IncludedTreeSnapshot,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    if (
        _capture_included_tree(
            root_path,
            expected_parent_identity=expected_parent_identity,
        )
        != expected
    ):
        raise OSError(f"Included Files tree changed during conversion: {root_path}")


def _included_tree_without_content(
    snapshot: _IncludedTreeSnapshot,
) -> _IncludedTreeSnapshot:
    return _IncludedTreeSnapshot(
        root_fingerprint=snapshot.root_fingerprint,
        entries=tuple(
            _IncludedTreeEntry(
                relative_path=entry.relative_path,
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=None,
            )
            for entry in snapshot.entries
        ),
    )


def _verify_included_tree_snapshot_metadata(
    root_path: str,
    expected: _IncludedTreeSnapshot,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    current = _capture_included_tree(
        root_path,
        expected_parent_identity=expected_parent_identity,
        include_content=False,
    )
    if current != _included_tree_without_content(expected):
        raise OSError(
            f"Included Files tree metadata changed during conversion: {root_path}"
        )


def _included_tree_matches_planned_paths(
    snapshot: _IncludedTreeSnapshot,
    assigned_paths: set[str],
) -> bool:
    if snapshot.identity is None:
        return False
    expected_directories = {
        "/".join(path.split("/")[:component_count])
        for path in assigned_paths
        for component_count in range(1, len(path.split("/")))
    }
    actual_files = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "directory"
    }
    if actual_files != assigned_paths or actual_directories != expected_directories:
        return False
    return all(
        entry.content_sha256 is not None and entry.fingerprint[5] == 1
        for entry in snapshot.entries
        if entry.kind == "file"
    )


def _included_tree_matches_source_receipts(
    snapshot: _IncludedTreeSnapshot,
    assigned_receipts: dict[str, _IncludedNoOpSourceReceipt],
) -> bool:
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    return all(
        assigned_path in entries_by_path
        and entries_by_path[assigned_path].fingerprint[3]
        == receipt.byte_count
        and entries_by_path[assigned_path].content_sha256 == receipt.sha256
        for assigned_path, receipt in assigned_receipts.items()
    )


def _included_generation_receipts_by_path(
    *,
    transaction_id: str,
    generation_identity: _PathIdentity,
    stage_container_identity: _PathIdentity,
    staged_root_path: str,
    public_root_path: str,
    receipts: tuple[_IncludedGenerationContentReceipt, ...],
) -> dict[str, _IncludedGenerationContentReceipt]:
    if not receipts:
        raise OSError("Included Files generation receipt set is empty")
    receipts_by_path: dict[str, _IncludedGenerationContentReceipt] = {}
    normalized_staged_root = os.path.normcase(os.path.abspath(staged_root_path))
    normalized_public_root = os.path.normcase(os.path.abspath(public_root_path))
    for receipt in receipts:
        assigned_path = receipt.source.assigned_path
        assigned_components = tuple(assigned_path.split("/"))
        if (
            not assigned_path
            or "\\" in assigned_path
            or any(
                component in {"", ".", ".."}
                for component in assigned_components
            )
            or assigned_path in receipts_by_path
        ):
            raise OSError("Invalid Included Files generation receipt path")
        expected_staged_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    normalized_staged_root,
                    *assigned_components,
                )
            )
        )
        expected_public_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    normalized_public_root,
                    *assigned_components,
                )
            )
        )
        output = receipt.output
        output_binding = (
            output.output_handle_state[0],
            output.output_handle_state[1],
            stat.S_IFMT(output.output_handle_state[2]),
            output.output_handle_state[3],
            output.output_handle_state[4],
            output.output_handle_state[6],
        )
        path_binding = (
            output.output_fingerprint[0],
            output.output_fingerprint[1],
            stat.S_IFMT(output.output_fingerprint[2]),
            output.output_fingerprint[3],
            output.output_fingerprint[4],
            output.output_fingerprint[5],
        )
        if (
            receipt.transaction_id != transaction_id
            or receipt.generation_identity != generation_identity
            or receipt.stage_container_identity
            != stage_container_identity
            or receipt.source.logical_path == ""
            or receipt.staged_output_path != expected_staged_path
            or receipt.public_output_path != expected_public_path
            or output.source_fingerprint
            != receipt.source.binding.handle_state[:6]
            or output.byte_count != receipt.source.byte_count
            or output.sha256 != receipt.source.sha256
            or output_binding != path_binding
            or output.output_fingerprint[5] != 1
        ):
            raise OSError(
                "Included Files generation content receipt binding changed"
            )
        receipts_by_path[assigned_path] = receipt
    return receipts_by_path


def _capture_included_tree_from_generation_receipts(
    staged_root_path: str,
    *,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    generation_identity: _PathIdentity,
    stage_container_identity: _PathIdentity,
    receipts: tuple[_IncludedGenerationContentReceipt, ...],
    published: bool = False,
) -> _IncludedTreeSnapshot:
    if not receipts:
        raise OSError("Included Files generation receipt set is empty")
    project_path = os.path.dirname(os.path.dirname(staged_root_path))
    public_root_path = os.path.join(
        project_path,
        _INCLUDED_FILES_ROOT_NAME,
    )
    receipts_by_path = _included_generation_receipts_by_path(
        transaction_id=transaction_id,
        generation_identity=generation_identity,
        stage_container_identity=stage_container_identity,
        staged_root_path=staged_root_path,
        public_root_path=public_root_path,
        receipts=receipts,
    )
    root_path = public_root_path if published else staged_root_path
    metadata = _capture_included_tree(
        root_path,
        expected_parent_identity=expected_parent_identity,
        include_content=False,
    )
    if metadata.identity != generation_identity:
        raise OSError("Included Files generation receipt root changed")
    file_entries = {
        entry.relative_path: entry
        for entry in metadata.entries
        if entry.kind == "file"
    }
    if file_entries.keys() != receipts_by_path.keys():
        raise OSError("Included Files generation receipt inventory changed")

    entries: list[_IncludedTreeEntry] = []
    for entry in metadata.entries:
        if entry.kind != "file":
            entries.append(entry)
            continue
        receipt = receipts_by_path[entry.relative_path]
        expected_output_path = (
            receipt.public_output_path
            if published
            else receipt.staged_output_path
        )
        actual_output_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    root_path,
                    *entry.relative_path.split("/"),
                )
            )
        )
        if (
            actual_output_path != expected_output_path
            or entry.fingerprint != receipt.output.output_fingerprint
            or entry.ctime_ns != receipt.output.output_ctime_ns
        ):
            raise OSError(
                "Included Files generation receipt output identity changed: "
                + entry.relative_path
            )
        entries.append(
            replace(
                entry,
                content_sha256=receipt.output.sha256,
            )
        )
    return _IncludedTreeSnapshot(
        root_fingerprint=metadata.root_fingerprint,
        entries=tuple(entries),
    )


def _verify_included_generation_source_receipt(
    receipt: _IncludedNoOpSourceReceipt,
    *,
    validate_content: bool,
) -> None:
    binding = receipt.binding
    source_path = binding.filesystem_path
    project_root = binding.directory_identities[0][0]
    with _open_included_file_validation_stream(
        source_path,
        deny_writes=validate_content,
    ) as source_file:
        expected_stat = os.fstat(source_file.fileno())

        def capture_binding() -> _IncludedSourceBinding:
            lexical_stat = os.lstat(source_path)
            path_stat = os.stat(source_path)
            handle_stat = os.fstat(source_file.fileno())
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or not stat.S_ISREG(handle_stat.st_mode)
                or not os.path.samestat(path_stat, handle_stat)
                or _included_path_handle_binding(path_stat)
                != _included_path_handle_binding(handle_stat)
                or _included_handle_state(handle_stat)
                != _included_handle_state(expected_stat)
            ):
                raise OSError(
                    "GameMaker Included File source receipt handle changed: "
                    + receipt.logical_path
                )
            canonical_path, directory_identities = (
                _capture_included_source_directory_identities(
                    project_root,
                    source_path,
                )
            )
            _verify_fallback_directory_ancestors(directory_identities)
            return _IncludedSourceBinding(
                filesystem_path=os.path.normcase(
                    os.path.abspath(source_path)
                ),
                canonical_path=canonical_path,
                directory_identities=directory_identities,
                lexical_state=_included_handle_state(lexical_stat),
                path_state=_included_handle_state(path_stat),
                handle_state=_included_handle_state(handle_stat),
            )

        before_binding = capture_binding()
        if before_binding != binding:
            raise OSError(
                "GameMaker Included File source receipt binding changed: "
                + receipt.logical_path
            )
        if validate_content:
            byte_count, sha256 = _digest_open_included_file(source_file)
            if (
                byte_count != receipt.byte_count
                or sha256 != receipt.sha256
            ):
                raise OSError(
                    "GameMaker Included File source receipt content changed: "
                    + receipt.logical_path
                )
        after_binding = capture_binding()
        if after_binding != binding:
            raise OSError(
                "GameMaker Included File source receipt binding changed: "
                + receipt.logical_path
            )


def _included_registry_receipts_from_tree(
    snapshot: _IncludedTreeSnapshot,
    assignments_by_source: dict[str, IncludedFilePathAssignment],
    emitted_logical_paths: set[str],
) -> dict[str, tuple[int, str]] | None:
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    receipts: dict[str, tuple[int, str]] = {}
    for logical_path in emitted_logical_paths:
        assignment = assignments_by_source.get(logical_path)
        if assignment is None:
            return None
        entry = entries_by_path.get(assignment.assigned_output_path)
        if entry is None or entry.content_sha256 is None:
            return None
        receipts[logical_path] = (
            entry.fingerprint[3],
            entry.content_sha256,
        )
    return receipts


def _included_stage_container_snapshot(
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
    staged_root_snapshot: _IncludedTreeSnapshot,
    staged_registry_identity: _PathIdentity,
    staged_registry_content: bytes,
) -> _IncludedTreeSnapshot:
    """Bind the complete staged namespace without re-reading payload bodies."""

    metadata = _capture_included_tree(
        stage_path,
        expected_parent_identity=project_identity,
        include_content=False,
    )
    if metadata.identity != stage_identity:
        raise OSError("Included Files staging container changed")
    marker_path = os.path.join(stage_path, _INCLUDED_FILES_STAGE_MARKER_NAME)
    marker_record = _read_included_recovery_record(
        marker_path,
        stage_identity,
    )
    if marker_record is None or not _included_stage_marker_matches(
        marker_record[1],
        project_identity,
        stage_identity,
    ):
        raise OSError("Included Files staging ownership marker changed")
    marker_content = _included_recovery_record_content(marker_record[1])
    expected_file_hashes = {
        _INCLUDED_FILES_STAGE_MARKER_NAME: hashlib.sha256(
            marker_content
        ).hexdigest(),
        "gml_included_file_registry.gd": hashlib.sha256(
            staged_registry_content
        ).hexdigest(),
        **{
            _INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path:
                entry.content_sha256
            for entry in staged_root_snapshot.entries
            if entry.kind == "file" and entry.content_sha256 is not None
        },
    }
    expected_directories = {
        _INCLUDED_FILES_ROOT_NAME,
        *(
            _INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
            for entry in staged_root_snapshot.entries
            if entry.kind == "directory"
        ),
    }
    actual_files = {
        entry.relative_path
        for entry in metadata.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in metadata.entries
        if entry.kind == "directory"
    }
    if actual_files != set(expected_file_hashes) or actual_directories != expected_directories:
        raise OSError("Included Files staging container inventory changed")
    entries: list[_IncludedTreeEntry] = []
    for entry in metadata.entries:
        if entry.kind == "file" and entry.fingerprint[5] != 1:
            raise OSError(
                "Included Files staging file has multiple hard links: "
                + entry.relative_path
            )
        if (
            entry.relative_path == _INCLUDED_FILES_ROOT_NAME
            and entry.fingerprint[:2] != staged_root_snapshot.identity
        ):
            raise OSError("Included Files staging root identity changed")
        if (
            entry.relative_path == "gml_included_file_registry.gd"
            and entry.fingerprint[:2] != staged_registry_identity
        ):
            raise OSError("Included File staging registry identity changed")
        entries.append(
            _IncludedTreeEntry(
                relative_path=entry.relative_path,
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=(
                    expected_file_hashes[entry.relative_path]
                    if entry.kind == "file"
                    else None
                ),
            )
        )
    return _IncludedTreeSnapshot(
        root_fingerprint=metadata.root_fingerprint,
        entries=tuple(entries),
    )


def _verify_staged_included_inventory(
    snapshot: _IncludedTreeSnapshot,
    assigned_receipts: dict[str, _IncludedCopyReceipt],
) -> None:
    if snapshot.identity is None:
        raise OSError("Included Files staging root disappeared before publication")
    assigned_paths = set(assigned_receipts)
    expected_directories = {
        "/".join(path.split("/")[:component_count])
        for path in assigned_paths
        for component_count in range(1, len(path.split("/")))
    }
    actual_files = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "directory"
    }
    if actual_files != assigned_paths or actual_directories != expected_directories:
        raise OSError(
            "Included Files staging inventory did not match its planned output set"
        )
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    for assigned_path, receipt in assigned_receipts.items():
        staged_entry = entries_by_path[assigned_path]
        if staged_entry.fingerprint[5] != 1:
            raise OSError(
                "Included Files staging payload has multiple hard links: "
                + assigned_path
            )
        if (
            staged_entry.fingerprint[3] != receipt.byte_count
            or staged_entry.content_sha256 != receipt.sha256
        ):
            raise OSError(
                "Included Files staging payload did not match its immutable "
                f"source receipt: {assigned_path}"
            )


def _included_registry_path(project_path: str) -> str:
    return os.path.join(project_path, INCLUDED_FILE_REGISTRY_RELATIVE_PATH)


def _before_included_registry_file_read(
    _project_fd: int,
    _registry_directory_name: str,
) -> None:
    """Narrow test seam after pinning the registry directory for capture."""


def _before_included_registry_directory_binding_check(
    _project_fd: int,
    _registry_directory_name: str,
) -> None:
    """Narrow test seam after securely creating the registry directory."""


def _capture_included_registry(
    project_path: str,
    *,
    expected_project_identity: _PathIdentity | None = None,
    allowed_file_identities: frozenset[_PathIdentity] | None = None,
) -> _IncludedRegistrySnapshot:
    registry_path = _included_registry_path(project_path)
    registry_directory = os.path.dirname(registry_path)
    if _included_descriptor_paths_supported():
        project_fd, registry_directory_name = _open_pinned_included_parent(
            registry_directory
        )
        try:
            project_stat = os.fstat(project_fd)
            project_mount_id = _included_linux_mount_id_from_fd(project_fd)
            _verify_included_directory_fd(
                project_fd,
                expected_project_identity,
                project_path,
            )
            registry_directory_stat = _included_entry_stat_at(
                project_fd,
                registry_directory_name,
            )
            if registry_directory_stat is None:
                if expected_project_identity is not None:
                    _verify_included_project_identity(
                        project_path,
                        expected_project_identity,
                    )
                return _IncludedRegistrySnapshot(
                    directory_identity=None,
                    file_identity=None,
                    file_mode=None,
                    content=None,
                )
            if not stat.S_ISDIR(registry_directory_stat.st_mode):
                raise OSError(
                    "Refusing redirected or non-directory Included File "
                    f"registry path: {registry_directory}"
                )
            directory_identity = (
                registry_directory_stat.st_dev,
                registry_directory_stat.st_ino,
            )
            registry_directory_fd = os.open(
                registry_directory_name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                if (
                    _directory_identity_from_fd(registry_directory_fd)
                    != directory_identity
                ):
                    raise OSError(
                        "Included File registry directory changed while opening"
                    )
                _verify_included_mount_boundary(
                    registry_directory,
                    os.fstat(registry_directory_fd),
                    project_stat.st_dev,
                    project_mount_id,
                    registry_directory_fd,
                )
                _before_included_registry_file_read(
                    project_fd,
                    registry_directory_name,
                )
                file_state = _included_regular_file_state_at(
                    registry_directory_fd,
                    os.path.basename(registry_path),
                    registry_path,
                    allowed_identities=allowed_file_identities,
                )
                _verify_included_directory_entry_identity_at(
                    project_fd,
                    registry_directory_name,
                    directory_identity,
                    registry_directory,
                )
            finally:
                os.close(registry_directory_fd)
            if expected_project_identity is not None:
                _verify_included_project_identity(
                    project_path,
                    expected_project_identity,
                )
            if file_state is None:
                return _IncludedRegistrySnapshot(
                    directory_identity=directory_identity,
                    file_identity=None,
                    file_mode=None,
                    content=None,
                )
            file_identity, file_mode, content = file_state
            return _IncludedRegistrySnapshot(
                directory_identity=directory_identity,
                file_identity=file_identity,
                file_mode=file_mode,
                content=content,
            )
        finally:
            os.close(project_fd)

    project_ancestors = _capture_fallback_directory_ancestors(project_path)
    if (
        expected_project_identity is not None
        and project_ancestors[-1][1] != expected_project_identity
    ):
        raise OSError(f"Included Files directory changed: {project_path}")
    try:
        registry_directory_stat = os.lstat(registry_directory)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(project_ancestors)
        return _IncludedRegistrySnapshot(
            directory_identity=None,
            file_identity=None,
            file_mode=None,
            content=None,
        )
    if (
        _included_output_path_is_redirected(
            registry_directory,
            registry_directory_stat,
        )
        or not stat.S_ISDIR(registry_directory_stat.st_mode)
    ):
        raise OSError(
            "Refusing redirected or non-directory Included File registry path: "
            f"{registry_directory}"
        )
    directory_identity = (
        registry_directory_stat.st_dev,
        registry_directory_stat.st_ino,
    )
    project_mount_id = _included_directory_mount_id(
        project_path,
        project_ancestors[-1][1],
    )
    _verify_included_mount_boundary_path(
        registry_directory,
        registry_directory_stat,
        project_ancestors[-1][1][0],
        project_mount_id,
        expect_directory=True,
    )
    registry_ancestors = (
        *project_ancestors,
        (registry_directory, directory_identity),
    )
    _verify_fallback_directory_ancestors(registry_ancestors)
    file_state = _included_regular_file_state(
        registry_path,
        expected_parent_identity=directory_identity,
        expected_fallback_ancestors=registry_ancestors,
        allowed_identities=allowed_file_identities,
    )
    _verify_fallback_directory_ancestors(registry_ancestors)
    if file_state is None:
        return _IncludedRegistrySnapshot(
            directory_identity=directory_identity,
            file_identity=None,
            file_mode=None,
            content=None,
        )
    file_identity, file_mode, content = file_state
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )


def _verify_included_registry_snapshot(
    project_path: str,
    expected: _IncludedRegistrySnapshot,
    *,
    expected_project_identity: _PathIdentity | None = None,
) -> None:
    if (
        _capture_included_registry(
            project_path,
            expected_project_identity=expected_project_identity,
            allowed_file_identities=(
                frozenset()
                if expected.file_identity is None
                else frozenset({expected.file_identity})
            ),
        )
        != expected
    ):
        raise OSError("Included File registry changed during conversion")


def _verify_included_project_identity(
    project_path: str,
    expected_identity: _PathIdentity,
) -> None:
    if _included_directory_identity(project_path) != expected_identity:
        raise OSError(f"Godot project root changed during Included Files conversion: {project_path}")


def _verify_included_stage_container(
    project_path: str,
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
) -> None:
    _verify_included_project_identity(project_path, project_identity)
    expected_parent = os.path.normcase(os.path.abspath(project_path))
    actual_parent = os.path.normcase(
        os.path.dirname(os.path.abspath(stage_path))
    )
    if actual_parent != expected_parent:
        raise OSError("Included Files staging directory escaped the Godot project")
    try:
        current_stage_identity = _included_directory_identity(stage_path)
    except OSError as error:
        raise OSError(
            "Refusing redirected or non-directory Included Files staging "
            f"path: {stage_path}"
        ) from error
    if current_stage_identity != stage_identity:
        raise OSError("Included Files staging directory changed during conversion")
    _verify_included_project_identity(project_path, project_identity)


def _write_included_stage_marker(
    project_path: str,
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
) -> None:
    marker_path = os.path.join(stage_path, _INCLUDED_FILES_STAGE_MARKER_NAME)
    content = _included_recovery_record_content(
        {
            "format_version": _INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": _included_identity_payload(project_identity),
            "stage_identity": _included_identity_payload(stage_identity),
        }
    )
    file_descriptor = os.open(
        marker_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    marker_stat = os.fstat(file_descriptor)
    marker_identity = (marker_stat.st_dev, marker_stat.st_ino)
    try:
        with os.fdopen(file_descriptor, "wb") as marker_file:
            file_descriptor = -1
            marker_file.write(content)
            marker_file.flush()
            os.fsync(marker_file.fileno())
        marker_state = _included_regular_file_state(
            marker_path,
            expected_parent_identity=stage_identity,
            allowed_identities=frozenset({marker_identity}),
        )
        if marker_state is None or marker_state[2] != content:
            raise OSError("Included Files staging ownership marker changed")
        _sync_included_directory(stage_path, stage_identity)
        _sync_included_directory(project_path, project_identity)
        _verify_included_stage_container(
            project_path,
            project_identity,
            stage_path,
            stage_identity,
        )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _create_included_output_stage(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity]:
    _verify_included_project_identity(project_path, project_identity)
    if _included_descriptor_paths_supported():
        project_fd = _open_pinned_included_directory(project_path)
        stage_name = ""
        stage_identity: _PathIdentity | None = None
        try:
            _verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            for _attempt in range(100):
                candidate = (
                    _INCLUDED_FILES_STAGE_PREFIX
                    + secrets.token_hex(8)
                    + ".stage"
                )
                try:
                    os.mkdir(candidate, 0o700, dir_fd=project_fd)
                except FileExistsError:
                    continue
                stage_name = candidate
                break
            if not stage_name:
                raise OSError("Could not allocate Included Files staging directory")
            stage_fd = os.open(
                stage_name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                stage_identity = _directory_identity_from_fd(stage_fd)
            finally:
                os.close(stage_fd)
            stage_stat = _included_entry_stat_at(project_fd, stage_name)
            if (
                stage_stat is None
                or not stat.S_ISDIR(stage_stat.st_mode)
                or (stage_stat.st_dev, stage_stat.st_ino) != stage_identity
            ):
                raise OSError("Included Files staging directory changed after creation")
            _verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            if _included_directory_identity(project_path) != project_identity:
                raise OSError(
                    "Godot project root changed during Included Files staging"
                )
            stage_path = os.path.join(project_path, stage_name)
            _write_included_stage_marker(
                project_path,
                project_identity,
                stage_path,
                stage_identity,
            )
            return stage_path, stage_identity
        except BaseException:
            if stage_name and stage_identity is not None:
                try:
                    _remove_owned_included_tree(
                        os.path.join(project_path, stage_name),
                        stage_identity,
                        expected_parent_identity=project_identity,
                    )
                except OSError:
                    pass
            raise
        finally:
            os.close(project_fd)

    stage_path = ""
    for _attempt in range(100):
        candidate_path = os.path.join(
            project_path,
            _INCLUDED_FILES_STAGE_PREFIX
            + secrets.token_hex(8)
            + ".stage",
        )
        try:
            os.mkdir(candidate_path, 0o700)
        except FileExistsError:
            continue
        stage_path = candidate_path
        break
    if not stage_path:
        raise OSError("Could not allocate Included Files staging directory")
    stage_identity = _included_directory_identity(stage_path)
    if stage_identity is None:
        raise OSError("Included Files staging directory disappeared")
    try:
        _verify_included_project_identity(project_path, project_identity)
        stage_parent_identity = _included_directory_identity(
            os.path.dirname(stage_path)
        )
        if stage_parent_identity != project_identity:
            raise OSError("Included Files staging directory escaped the Godot project")
        _write_included_stage_marker(
            project_path,
            project_identity,
            stage_path,
            stage_identity,
        )
    except Exception:
        try:
            _remove_owned_included_tree(
                stage_path,
                stage_identity,
                expected_parent_identity=project_identity,
            )
        except OSError:
            pass
        raise
    return stage_path, stage_identity


def _verify_included_directory_entry_identity_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    current_stat = _included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files directory changed: {display_path}")


def _before_included_cleanup_quarantine(
    _parent_fd: int,
    _name: str,
) -> None:
    """Narrow test seam before moving a cleanup candidate to quarantine."""


def _before_included_cleanup_remove(
    _parent_fd: int,
    _name: str,
) -> None:
    """Narrow test seam before removing a verified quarantine entry."""


def _quarantine_included_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
    display_path: str,
) -> tuple[str, str]:
    quarantine_name = (
        f".{name}.{secrets.token_hex(8)}.quarantine"
    )
    quarantine_path = os.path.join(
        os.path.dirname(display_path),
        quarantine_name,
    )
    _before_included_cleanup_quarantine(parent_fd, name)
    _rename_included_transaction_entry_at(
        parent_fd,
        name,
        parent_fd,
        quarantine_name,
    )
    quarantine_stat = _included_entry_stat_at(parent_fd, quarantine_name)
    quarantine_is_expected_kind = (
        quarantine_stat is not None
        and (
            stat.S_ISDIR(quarantine_stat.st_mode)
            if expect_directory
            else not stat.S_ISDIR(quarantine_stat.st_mode)
        )
    )
    if (
        not quarantine_is_expected_kind
        or quarantine_stat is None
        or (quarantine_stat.st_dev, quarantine_stat.st_ino)
        != expected_identity
    ):
        raise _preserve_or_restore_unexpected_moved_entry_at(
            parent_fd,
            name,
            parent_fd,
            quarantine_name,
            display_path,
            quarantine_path,
        )
    return quarantine_name, quarantine_path


def _unlink_exact_quarantined_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    _before_included_cleanup_remove(parent_fd, name)
    current_stat = _included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"entry retained at {display_path!r}"
        )
    os.unlink(name, dir_fd=parent_fd)


def _rmdir_exact_quarantined_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    _before_included_cleanup_remove(parent_fd, name)
    current_stat = _included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"directory retained at {display_path!r}"
        )
    os.rmdir(name, dir_fd=parent_fd)


def _remove_included_tree_contents_at(
    directory_fd: int,
    display_path: str,
    verify_binding: Callable[[], None],
    boundary_device: int,
    boundary_mount_id: int | None,
) -> None:
    verify_binding()
    for name in sorted(os.listdir(directory_fd)):
        verify_binding()
        entry_path = os.path.join(display_path, name)
        entry_stat = _included_entry_stat_at(directory_fd, name)
        if entry_stat is None:
            raise OSError(f"Included Files cleanup entry changed: {entry_path}")
        entry_identity = entry_stat.st_dev, entry_stat.st_ino
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = os.open(
                name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=directory_fd,
            )
            try:
                child_stat = os.fstat(child_fd)
                if (
                    not stat.S_ISDIR(child_stat.st_mode)
                    or (child_stat.st_dev, child_stat.st_ino)
                    != entry_identity
                ):
                    raise OSError(
                        f"Included Files cleanup directory changed: {entry_path}"
                    )
                _verify_included_mount_boundary(
                    entry_path,
                    child_stat,
                    boundary_device,
                    boundary_mount_id,
                    child_fd,
                )
                quarantined_name, quarantined_path = (
                    _quarantine_included_entry_at(
                        directory_fd,
                        name,
                        entry_identity,
                        expect_directory=True,
                        display_path=entry_path,
                    )
                )

                def verify_child_binding() -> None:
                    verify_binding()
                    _verify_included_directory_entry_identity_at(
                        directory_fd,
                        quarantined_name,
                        entry_identity,
                        quarantined_path,
                    )
                    current_child_stat = os.fstat(child_fd)
                    if (
                        not stat.S_ISDIR(current_child_stat.st_mode)
                        or (current_child_stat.st_dev, current_child_stat.st_ino)
                        != entry_identity
                    ):
                        raise OSError(
                            "Included Files cleanup directory changed: "
                            f"{quarantined_path}"
                        )
                    _verify_included_mount_boundary(
                        quarantined_path,
                        current_child_stat,
                        boundary_device,
                        boundary_mount_id,
                        child_fd,
                    )

                _remove_included_tree_contents_at(
                    child_fd,
                    quarantined_path,
                    verify_child_binding,
                    boundary_device,
                    boundary_mount_id,
                )
                verify_child_binding()
                _rmdir_exact_quarantined_entry_at(
                    directory_fd,
                    quarantined_name,
                    entry_identity,
                    quarantined_path,
                )
            finally:
                os.close(child_fd)
        else:
            if stat.S_ISREG(entry_stat.st_mode):
                _verify_included_regular_file_mount_boundary_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    boundary_device,
                    boundary_mount_id,
                )
            quarantined_name, quarantined_path = _quarantine_included_entry_at(
                directory_fd,
                name,
                entry_identity,
                expect_directory=False,
                display_path=entry_path,
            )
            _unlink_exact_quarantined_entry_at(
                directory_fd,
                quarantined_name,
                entry_identity,
                quarantined_path,
            )
    verify_binding()


def _before_included_cleanup_quarantine_fallback(_path: str) -> None:
    """Narrow fallback test seam before quarantining a cleanup candidate."""


def _before_included_cleanup_remove_fallback(_path: str) -> None:
    """Narrow fallback test seam before removing a quarantine candidate."""


def _quarantine_included_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
) -> str:
    quarantine_path = path + "." + secrets.token_hex(8) + ".quarantine"
    _before_included_cleanup_quarantine_fallback(path)
    _rename_included_transaction_entry(path, quarantine_path)
    quarantine_stat = os.lstat(quarantine_path)
    quarantine_is_expected_kind = (
        stat.S_ISDIR(quarantine_stat.st_mode)
        if expect_directory
        else not stat.S_ISDIR(quarantine_stat.st_mode)
    )
    if (
        _included_output_path_is_redirected(quarantine_path, quarantine_stat)
        or not quarantine_is_expected_kind
        or (quarantine_stat.st_dev, quarantine_stat.st_ino)
        != expected_identity
    ):
        raise _preserve_or_restore_unexpected_moved_entry_fallback(
            path,
            quarantine_path,
        )
    return quarantine_path


def _unlink_exact_quarantined_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
) -> None:
    _before_included_cleanup_remove_fallback(path)
    current_stat = os.lstat(path)
    if (
        stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"entry retained at {path!r}"
        )
    original_mode = stat.S_IMODE(current_stat.st_mode)
    windows_read_only = (
        os.name == "nt"
        and not bool(current_stat.st_mode & stat.S_IWRITE)
    )
    if windows_read_only:
        if current_stat.st_nlink != 1:
            raise OSError(
                "Refusing to clear the Windows read-only attribute on an "
                "Included Files cleanup file with multiple hard links; "
                f"recoverable quarantine retained at {path!r}"
            )
        parent_path = os.path.dirname(os.path.abspath(path))
        parent_identities = _capture_fallback_directory_ancestors(parent_path)
        parent_identity = parent_identities[-1][1]
        try:
            _chmod_exact_included_file(
                path,
                expected_identity,
                original_mode | stat.S_IWRITE,
                parent_identity,
            )
        except OSError as error:
            raise OSError(
                "Could not clear the Windows read-only attribute from an "
                "identity-verified Included Files cleanup file; recoverable "
                f"quarantine retained at {path!r}"
            ) from error
        writable_stat = os.lstat(path)
        if (
            _included_output_path_is_redirected(path, writable_stat)
            or not stat.S_ISREG(writable_stat.st_mode)
            or (writable_stat.st_dev, writable_stat.st_ino)
            != expected_identity
            or not bool(writable_stat.st_mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files cleanup file changed while clearing its "
                f"Windows read-only attribute: {path!r}"
            )
        _after_included_transaction_phase("cleanup-readonly-cleared")
    try:
        os.unlink(path)
    except OSError as error:
        if windows_read_only:
            try:
                parent_identity = _capture_fallback_directory_ancestors(
                    os.path.dirname(os.path.abspath(path))
                )[-1][1]
                _chmod_exact_included_file(
                    path,
                    expected_identity,
                    original_mode,
                    parent_identity,
                )
            except OSError as restore_error:
                error.add_note(
                    "Restoring the Windows read-only attribute on the "
                    "recoverable Included Files quarantine also failed: "
                    + str(restore_error)
                )
        raise OSError(
            "Could not remove an identity-verified Included Files cleanup "
            f"file; recoverable quarantine retained at {path!r}"
        ) from error


def _chmod_exact_included_directory_fallback(
    path: str,
    expected_identity: _PathIdentity,
    mode: int,
    expected_parent_identity: _PathIdentity,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if parent_identities[-1][1] != expected_parent_identity:
        raise OSError(
            f"Included Files directory parent changed before chmod: {parent_path}"
        )
    current_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, current_stat)
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino)
        != expected_identity
    ):
        raise OSError(f"Included Files directory changed before chmod: {path}")
    if bool(current_stat.st_mode & stat.S_IWRITE) == bool(
        mode & stat.S_IWRITE
    ):
        return
    if os.name != "nt":
        raise OSError(
            "Path-based Included Files directory chmod is only supported on "
            "Windows"
        )
    _verify_fallback_directory_ancestors(parent_identities)
    quarantined_path = _quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=True,
    )
    try:
        quarantined_stat = os.lstat(quarantined_path)
        if (
            _included_output_path_is_redirected(
                quarantined_path,
                quarantined_stat,
            )
            or not stat.S_ISDIR(quarantined_stat.st_mode)
            or (quarantined_stat.st_dev, quarantined_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                "Included Files directory chmod quarantine changed: "
                f"{quarantined_path}"
            )
        os.chmod(quarantined_path, mode)
        changed_stat = os.lstat(quarantined_path)
        if (
            _included_output_path_is_redirected(
                quarantined_path,
                changed_stat,
            )
            or not stat.S_ISDIR(changed_stat.st_mode)
            or (changed_stat.st_dev, changed_stat.st_ino)
            != expected_identity
            or bool(changed_stat.st_mode & stat.S_IWRITE)
            != bool(mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files directory chmod quarantine changed: "
                f"{quarantined_path}"
            )
    except BaseException as error:
        try:
            _move_exact_included_directory(
                quarantined_path,
                path,
                expected_identity,
                source_parent_identity=expected_parent_identity,
                destination_parent_identity=expected_parent_identity,
            )
        except BaseException as restore_error:
            error.add_note(
                "Included Files directory chmod quarantine restore also "
                "failed: "
                + str(restore_error)
            )
        raise
    _move_exact_included_directory(
        quarantined_path,
        path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
    )
    final_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, final_stat)
        or not stat.S_ISDIR(final_stat.st_mode)
        or (final_stat.st_dev, final_stat.st_ino) != expected_identity
        or bool(final_stat.st_mode & stat.S_IWRITE)
        != bool(mode & stat.S_IWRITE)
    ):
        raise OSError(f"Included Files directory changed after chmod: {path}")
    _verify_fallback_directory_ancestors(parent_identities)


def _rmdir_exact_quarantined_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
) -> None:
    _before_included_cleanup_remove_fallback(path)
    current_stat = os.lstat(path)
    if (
        not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"directory retained at {path!r}"
        )
    original_mode = stat.S_IMODE(current_stat.st_mode)
    windows_read_only = (
        os.name == "nt"
        and not bool(current_stat.st_mode & stat.S_IWRITE)
    )
    if windows_read_only:
        parent_identity = _capture_fallback_directory_ancestors(
            os.path.dirname(os.path.abspath(path))
        )[-1][1]
        try:
            _chmod_exact_included_directory_fallback(
                path,
                expected_identity,
                original_mode | stat.S_IWRITE,
                parent_identity,
            )
        except OSError as error:
            raise OSError(
                "Could not clear the Windows read-only attribute from an "
                "identity-verified Included Files cleanup directory; "
                f"recoverable quarantine retained at {path!r}"
            ) from error
        writable_stat = os.lstat(path)
        if (
            _included_output_path_is_redirected(path, writable_stat)
            or not stat.S_ISDIR(writable_stat.st_mode)
            or (writable_stat.st_dev, writable_stat.st_ino)
            != expected_identity
            or not bool(writable_stat.st_mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files cleanup directory changed while clearing its "
                f"Windows read-only attribute: {path!r}"
            )
    try:
        os.rmdir(path)
    except OSError as error:
        if windows_read_only:
            try:
                parent_identity = _capture_fallback_directory_ancestors(
                    os.path.dirname(os.path.abspath(path))
                )[-1][1]
                _chmod_exact_included_directory_fallback(
                    path,
                    expected_identity,
                    original_mode,
                    parent_identity,
                )
            except OSError as restore_error:
                error.add_note(
                    "Restoring the Windows read-only attribute on the "
                    "recoverable Included Files directory quarantine also "
                    "failed: "
                    + str(restore_error)
                )
        raise OSError(
            "Could not remove an identity-verified Included Files cleanup "
            f"directory; recoverable quarantine retained at {path!r}"
        ) from error


def _remove_owned_included_tree_fallback(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity | None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if (
        expected_parent_identity is not None
        and parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup parent changed: {parent_path}")
    try:
        root_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return
    if (
        _included_output_path_is_redirected(path, root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
        or (root_stat.st_dev, root_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Refusing to remove changed Included Files tree: {path}")
    parent_mount_id = _included_directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    root_mount_id = _verify_included_mount_boundary_path(
        path,
        root_stat,
        parent_identities[-1][1][0],
        parent_mount_id,
        expect_directory=True,
    )
    quarantined_root_path = _quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=True,
    )

    def remove_directory(
        directory_path: str,
        directory_identity: _PathIdentity,
    ) -> None:
        directory_ancestors = _capture_fallback_directory_ancestors(
            directory_path
        )
        if directory_ancestors[-1][1] != directory_identity:
            raise OSError(
                f"Included Files cleanup directory changed: {directory_path}"
            )
        directory_stat = os.lstat(directory_path)
        _verify_included_mount_boundary_path(
            directory_path,
            directory_stat,
            root_stat.st_dev,
            root_mount_id,
            expect_directory=True,
        )
        for name in sorted(os.listdir(directory_path)):
            _verify_fallback_directory_ancestors(directory_ancestors)
            entry_path = os.path.join(directory_path, name)
            entry_stat = os.lstat(entry_path)
            entry_identity = entry_stat.st_dev, entry_stat.st_ino
            if _included_output_path_is_redirected(entry_path, entry_stat):
                raise OSError(
                    f"Refusing redirected Included Files cleanup entry: {entry_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                _verify_included_mount_boundary_path(
                    entry_path,
                    entry_stat,
                    root_stat.st_dev,
                    root_mount_id,
                    expect_directory=True,
                )
                quarantined_entry_path = _quarantine_included_entry_fallback(
                    entry_path,
                    entry_identity,
                    expect_directory=True,
                )
                remove_directory(quarantined_entry_path, entry_identity)
                _verify_fallback_directory_ancestors(directory_ancestors)
                _rmdir_exact_quarantined_entry_fallback(
                    quarantined_entry_path,
                    entry_identity,
                )
            else:
                if stat.S_ISREG(entry_stat.st_mode):
                    _verify_included_mount_boundary_path(
                        entry_path,
                        entry_stat,
                        root_stat.st_dev,
                        root_mount_id,
                        expect_directory=False,
                    )
                _verify_fallback_directory_ancestors(directory_ancestors)
                quarantined_entry_path = _quarantine_included_entry_fallback(
                    entry_path,
                    entry_identity,
                    expect_directory=False,
                )
                _unlink_exact_quarantined_entry_fallback(
                    quarantined_entry_path,
                    entry_identity,
                )
        _verify_fallback_directory_ancestors(directory_ancestors)

    remove_directory(quarantined_root_path, expected_identity)
    _verify_fallback_directory_ancestors(parent_identities)
    _rmdir_exact_quarantined_entry_fallback(
        quarantined_root_path,
        expected_identity,
    )


def _remove_owned_included_tree(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    if not _included_descriptor_paths_supported():
        _remove_owned_included_tree_fallback(
            path,
            expected_identity,
            expected_parent_identity,
        )
        return
    parent_fd, name = _open_pinned_included_parent(path)
    try:
        parent_identity = _verify_included_directory_fd(
            parent_fd,
            expected_parent_identity,
            os.path.dirname(path),
        )
        root_stat = _included_entry_stat_at(parent_fd, name)
        if root_stat is None:
            return
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or (root_stat.st_dev, root_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Refusing to remove changed Included Files tree: {path}")
        root_fd = os.open(
            name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_fd,
        )
        try:
            opened_root_stat = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened_root_stat.st_mode)
                or (opened_root_stat.st_dev, opened_root_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Refusing to remove changed Included Files tree: {path}"
                )
            parent_mount_id = _included_linux_mount_id_from_fd(parent_fd)
            root_mount_id = _verify_included_mount_boundary(
                path,
                opened_root_stat,
                parent_identity[0],
                parent_mount_id,
                root_fd,
            )
            quarantined_name, quarantined_path = _quarantine_included_entry_at(
                parent_fd,
                name,
                expected_identity,
                expect_directory=True,
                display_path=path,
            )

            def verify_root_binding() -> None:
                _verify_included_directory_entry_identity_at(
                    parent_fd,
                    quarantined_name,
                    expected_identity,
                    quarantined_path,
                )
                current_root_stat = os.fstat(root_fd)
                if (
                    not stat.S_ISDIR(current_root_stat.st_mode)
                    or (current_root_stat.st_dev, current_root_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(
                        "Refusing to remove changed Included Files tree: "
                        f"{quarantined_path}"
                    )
                _verify_included_mount_boundary(
                    quarantined_path,
                    current_root_stat,
                    opened_root_stat.st_dev,
                    root_mount_id,
                    root_fd,
                )

            _remove_included_tree_contents_at(
                root_fd,
                quarantined_path,
                verify_root_binding,
                opened_root_stat.st_dev,
                root_mount_id,
            )
            verify_root_binding()
            _rmdir_exact_quarantined_entry_at(
                parent_fd,
                quarantined_name,
                expected_identity,
                quarantined_path,
            )
        finally:
            os.close(root_fd)
    finally:
        os.close(parent_fd)


def _before_included_fallback_chmod_open(_path: str) -> None:
    """Narrow test seam before opening a fallback chmod target."""


def _chmod_exact_included_file(
    path: str,
    expected_identity: _PathIdentity,
    mode: int,
    expected_parent_identity: _PathIdentity,
) -> None:
    if _included_descriptor_paths_supported():
        parent_fd, name = _open_pinned_included_parent(path)
        try:
            _verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            file_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                opened_stat = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened_stat.st_mode)
                    or (opened_stat.st_dev, opened_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(f"Included Files file changed: {path}")
                os.chmod(file_descriptor, mode)
            finally:
                os.close(file_descriptor)
        finally:
            os.close(parent_fd)
        return
    parent_identities = _capture_fallback_directory_ancestors(
        os.path.dirname(os.path.abspath(path))
    )
    if parent_identities[-1][1] != expected_parent_identity:
        raise OSError(f"Included Files file parent changed: {path}")
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError as error:
        raise OSError(f"Included Files file changed: {path}") from error
    if (
        _included_output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files file changed: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    _before_included_fallback_chmod_open(path)
    file_descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    path_chmod_required = False
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Included Files file changed: {path}")
        _verify_fallback_directory_ancestors(parent_identities)
        if os.chmod in os.supports_fd:
            os.chmod(file_descriptor, mode)
        elif os.name == "nt":
            path_chmod_required = bool(opened_stat.st_mode & stat.S_IWRITE) != (
                bool(mode & stat.S_IWRITE)
            )
        else:
            raise OSError(
                "Descriptor-bound Included Files chmod is unavailable on "
                f"{sys.platform}"
            )
    finally:
        os.close(file_descriptor)
    if path_chmod_required:
        quarantined_path = _quarantine_included_entry_fallback(
            path,
            expected_identity,
            expect_directory=False,
        )
        try:
            quarantined_stat = os.lstat(quarantined_path)
            if (
                not stat.S_ISREG(quarantined_stat.st_mode)
                or (quarantined_stat.st_dev, quarantined_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    "Included Files chmod quarantine changed: "
                    f"{quarantined_path}"
                )
            os.chmod(quarantined_path, mode)
            changed_stat = os.lstat(quarantined_path)
            if (
                not stat.S_ISREG(changed_stat.st_mode)
                or (changed_stat.st_dev, changed_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    "Included Files chmod quarantine changed: "
                    f"{quarantined_path}"
                )
        except BaseException as error:
            try:
                _move_exact_included_file(
                    quarantined_path,
                    path,
                    expected_identity,
                    source_parent_identity=expected_parent_identity,
                    destination_parent_identity=expected_parent_identity,
                )
            except OSError as restore_error:
                error.add_note(
                    "Included Files chmod quarantine restore also failed: "
                    + str(restore_error)
                )
            raise
        _move_exact_included_file(
            quarantined_path,
            path,
            expected_identity,
            source_parent_identity=expected_parent_identity,
            destination_parent_identity=expected_parent_identity,
        )
    try:
        current_stat = os.lstat(path)
    except FileNotFoundError as error:
        raise OSError(f"Included Files file changed: {path}") from error
    if (
        _included_output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files file changed: {path}")
    _verify_fallback_directory_ancestors(parent_identities)


def _unique_included_transaction_path(
    directory: str,
    label: str,
) -> str:
    for _attempt in range(100):
        candidate = os.path.join(
            directory,
            f".{label}.{secrets.token_hex(8)}.backup",
        )
        if not os.path.lexists(candidate):
            return candidate
    raise OSError(f"Could not allocate Included Files transaction backup for {label}")


def _rename_included_transaction_entry(source: str, destination: str) -> None:
    if os.name != "nt":
        raise OSError(
            "Unsafe path-based Included Files rename is disabled on POSIX"
        )
    if sys.platform != "win32":
        # Cross-platform unit tests model the Windows fallback by patching
        # os.name; the real Windows runner exercises MoveFileExW below.
        os.rename(source, destination)
        return
    kernel32 = _windows_included_transaction_api()
    if not kernel32.MoveFileExW(
        _windows_extended_included_path(source),
        _windows_extended_included_path(destination),
        _WINDOWS_MOVEFILE_WRITE_THROUGH,
    ):
        raise _windows_included_transaction_error(
            "Could not durably move Included Files transaction entry",
            destination,
        )


def _move_exact_included_entry(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
    source_parent_identity: _PathIdentity | None,
    destination_parent_identity: _PathIdentity | None,
) -> None:
    source_parent_path = os.path.dirname(os.path.abspath(source))
    destination_parent_path = os.path.dirname(os.path.abspath(destination))
    if _included_descriptor_paths_supported():
        source_parent_fd, source_name = _open_pinned_included_parent(source)
        try:
            _verify_included_directory_fd(
                source_parent_fd,
                source_parent_identity,
                source_parent_path,
            )
            destination_parent_fd, destination_name = (
                _open_pinned_included_parent(destination)
            )
            try:
                _verify_included_directory_fd(
                    destination_parent_fd,
                    destination_parent_identity,
                    destination_parent_path,
                )
                source_stat = _included_entry_stat_at(
                    source_parent_fd,
                    source_name,
                )
                if source_stat is None:
                    raise OSError(
                        f"Included Files transaction source disappeared: {source}"
                    )
                source_is_expected_kind = (
                    stat.S_ISDIR(source_stat.st_mode)
                    if expect_directory
                    else stat.S_ISREG(source_stat.st_mode)
                )
                if (
                    not source_is_expected_kind
                    or (source_stat.st_dev, source_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(
                        f"Included Files transaction source changed: {source}"
                    )
                _before_included_transaction_rename(
                    source_parent_fd,
                    source_name,
                )
                _rename_included_transaction_entry_at(
                    source_parent_fd,
                    source_name,
                    destination_parent_fd,
                    destination_name,
                )
                destination_stat = _included_entry_stat_at(
                    destination_parent_fd,
                    destination_name,
                )
                destination_is_expected_kind = (
                    destination_stat is not None
                    and (
                        stat.S_ISDIR(destination_stat.st_mode)
                        if expect_directory
                        else stat.S_ISREG(destination_stat.st_mode)
                    )
                )
                if (
                    not destination_is_expected_kind
                    or destination_stat is None
                    or (destination_stat.st_dev, destination_stat.st_ino)
                    != expected_identity
                ):
                    raise _preserve_or_restore_unexpected_moved_entry_at(
                        source_parent_fd,
                        source_name,
                        destination_parent_fd,
                        destination_name,
                        source,
                        destination,
                    )
            finally:
                os.close(destination_parent_fd)
        finally:
            os.close(source_parent_fd)
        return

    source_parent_ancestors = _capture_fallback_directory_ancestors(
        source_parent_path
    )
    destination_parent_ancestors = _capture_fallback_directory_ancestors(
        destination_parent_path
    )
    if (
        source_parent_identity is not None
        and source_parent_ancestors[-1][1] != source_parent_identity
    ):
        raise OSError(f"Included Files source parent changed: {source_parent_path}")
    if (
        destination_parent_identity is not None
        and destination_parent_ancestors[-1][1]
        != destination_parent_identity
    ):
        raise OSError(
            f"Included Files destination parent changed: {destination_parent_path}"
        )
    source_stat = os.lstat(source)
    source_is_expected_kind = (
        stat.S_ISDIR(source_stat.st_mode)
        if expect_directory
        else stat.S_ISREG(source_stat.st_mode)
    )
    if (
        _included_output_path_is_redirected(source, source_stat)
        or not source_is_expected_kind
        or (source_stat.st_dev, source_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files transaction source changed: {source}")
    if os.path.lexists(destination):
        raise OSError(
            f"Included Files transaction destination already exists: {destination}"
        )
    _verify_fallback_directory_ancestors(source_parent_ancestors)
    _verify_fallback_directory_ancestors(destination_parent_ancestors)
    _before_included_transaction_rename_fallback(source, destination)
    _rename_included_transaction_entry(source, destination)
    _verify_fallback_directory_ancestors(source_parent_ancestors)
    _verify_fallback_directory_ancestors(destination_parent_ancestors)
    destination_stat = os.lstat(destination)
    destination_is_expected_kind = (
        stat.S_ISDIR(destination_stat.st_mode)
        if expect_directory
        else stat.S_ISREG(destination_stat.st_mode)
    )
    if (
        _included_output_path_is_redirected(destination, destination_stat)
        or not destination_is_expected_kind
        or (destination_stat.st_dev, destination_stat.st_ino)
        != expected_identity
    ):
        raise _preserve_or_restore_unexpected_moved_entry_fallback(
            source,
            destination,
        )


def _move_exact_included_directory(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    source_parent_identity: _PathIdentity | None = None,
    destination_parent_identity: _PathIdentity | None = None,
) -> None:
    _move_exact_included_entry(
        source,
        destination,
        expected_identity,
        expect_directory=True,
        source_parent_identity=source_parent_identity,
        destination_parent_identity=destination_parent_identity,
    )


def _move_exact_included_file(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    source_parent_identity: _PathIdentity | None = None,
    destination_parent_identity: _PathIdentity | None = None,
) -> None:
    _move_exact_included_entry(
        source,
        destination,
        expected_identity,
        expect_directory=False,
        source_parent_identity=source_parent_identity,
        destination_parent_identity=destination_parent_identity,
    )


def _sync_included_directory(
    path: str,
    expected_identity: _PathIdentity,
) -> None:
    """Make prior namespace changes durable where Python exposes directory fsync."""

    if os.name == "nt":
        # Windows transaction renames use MoveFileExW with
        # MOVEFILE_WRITE_THROUGH instead.
        return
    directory_fd = _open_pinned_included_directory(path)
    try:
        _verify_included_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
        os.fsync(directory_fd)
        _verify_included_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
    finally:
        os.close(directory_fd)


def _sync_included_tree_directories_bottom_up(
    root_path: str,
    snapshot: _IncludedTreeSnapshot,
    expected_parent_identity: _PathIdentity,
) -> None:
    """Durably bind every recorded tree namespace before committing it."""

    root_identity = snapshot.identity
    if root_identity is None:
        raise OSError("Cannot sync an absent Included Files generation")
    _verify_included_tree_snapshot_metadata(
        root_path,
        snapshot,
        expected_parent_identity=expected_parent_identity,
    )
    directories = sorted(
        (entry for entry in snapshot.entries if entry.kind == "directory"),
        key=lambda entry: (
            entry.relative_path.count("/"),
            entry.relative_path,
        ),
        reverse=True,
    )
    for entry in directories:
        _sync_included_directory(
            _included_recovery_tree_entry_path(
                root_path,
                entry.relative_path,
            ),
            entry.fingerprint[:2],
        )
    _sync_included_directory(root_path, root_identity)
    _verify_included_tree_snapshot_metadata(
        root_path,
        snapshot,
        expected_parent_identity=expected_parent_identity,
    )


def _after_included_transaction_phase(_phase: str) -> None:
    """Narrow subprocess-test seam after one durable publication boundary."""


def _prepare_included_registry_directory(
    project_path: str,
    expected: _IncludedRegistrySnapshot,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity, bool]:
    registry_directory = os.path.dirname(_included_registry_path(project_path))
    current_identity = _included_directory_identity(registry_directory)
    if expected.directory_identity is not None:
        if current_identity != expected.directory_identity:
            raise OSError("Included File registry directory changed during conversion")
        return registry_directory, expected.directory_identity, False
    if current_identity is not None:
        raise OSError("Included File registry directory appeared during conversion")
    if _included_descriptor_paths_supported():
        project_fd = _open_pinned_included_directory(project_path)
        try:
            _verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            registry_name = os.path.basename(registry_directory)
            os.mkdir(registry_name, 0o755, dir_fd=project_fd)
            registry_fd = os.open(
                registry_name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                created_identity = _directory_identity_from_fd(registry_fd)
            finally:
                os.close(registry_fd)
            _before_included_registry_directory_binding_check(
                project_fd,
                registry_name,
            )
            registry_stat = _included_entry_stat_at(project_fd, registry_name)
            if (
                registry_stat is None
                or not stat.S_ISDIR(registry_stat.st_mode)
                or (registry_stat.st_dev, registry_stat.st_ino)
                != created_identity
            ):
                raise OSError(
                    "Included File registry directory changed after creation"
                )
        finally:
            os.close(project_fd)
    else:
        project_ancestors = _capture_fallback_directory_ancestors(project_path)
        if project_ancestors[-1][1] != project_identity:
            raise OSError(
                "Godot project root changed before registry directory creation"
            )
        os.mkdir(registry_directory, 0o755)
        _verify_fallback_directory_ancestors(project_ancestors)
        created_identity = _included_directory_identity(registry_directory)
        if created_identity is None:
            raise OSError(
                "Included File registry directory disappeared after creation"
            )
    visible_identity = _included_directory_identity(registry_directory)
    if visible_identity != created_identity:
        raise OSError(
            "Included File registry directory changed after secure creation"
        )
    if (
        _included_regular_file_state(
            _included_registry_path(project_path),
            expected_parent_identity=created_identity,
            allowed_identities=frozenset(),
        )
        is not None
    ):
        raise OSError("Included File registry appeared during directory creation")
    return registry_directory, created_identity, True


def _after_included_lock_initialization_phase(_phase: str) -> None:
    """Narrow test seam around durable project-lock initialization."""


def _write_included_lock_initialization_temporary(file_descriptor: int) -> None:
    midpoint = len(_INCLUDED_FILES_LOCK_CONTENT) // 2
    chunks = (
        _INCLUDED_FILES_LOCK_CONTENT[:midpoint],
        _INCLUDED_FILES_LOCK_CONTENT[midpoint:],
    )
    for index, chunk in enumerate(chunks):
        pending = memoryview(chunk)
        while pending:
            written = os.write(file_descriptor, pending)
            if written <= 0:
                raise OSError("Could not initialize Included Files transaction lock")
            pending = pending[written:]
        if index == 0:
            _after_included_lock_initialization_phase("temporary-partially-written")
    _after_included_lock_initialization_phase("temporary-written")
    os.fsync(file_descriptor)


def _remove_exact_included_lock_initialization_temporary(
    path: str,
    expected_identity: _PathIdentity,
    project_identity: _PathIdentity,
) -> None:
    state = _included_lock_initialization_record_state(
        path,
        project_identity,
        allowed_identities=frozenset({expected_identity}),
    )
    if state is None:
        return
    current_stat = os.lstat(path)
    if (
        (current_stat.st_dev, current_stat.st_ino) != expected_identity
        or current_stat.st_nlink != 1
        or state[2] != _INCLUDED_FILES_LOCK_CONTENT
    ):
        return

    name = os.path.basename(path)
    initialization_token: str | None = None
    cleanup_token: str | None = None
    try:
        _included_recovery_managed_name(
            name,
            prefix=_INCLUDED_FILES_LOCK_TEMP_PREFIX,
            suffix=".tmp",
            label="lock initialization temporary",
        )
        initialization_token = name[
            len(_INCLUDED_FILES_LOCK_TEMP_PREFIX) : -len(".tmp")
        ]
    except OSError:
        try:
            _included_recovery_managed_name(
                name,
                prefix=_INCLUDED_FILES_LOCK_CLEANUP_PREFIX,
                suffix=".tmp",
                label="lock initialization cleanup tombstone",
            )
            cleanup_token = name[
                len(_INCLUDED_FILES_LOCK_CLEANUP_PREFIX) : -len(".tmp")
            ]
        except OSError:
            return

    parent_path = os.path.dirname(path)
    if cleanup_token is not None:
        initialization_path = os.path.join(
            parent_path,
            _INCLUDED_FILES_LOCK_TEMP_PREFIX + cleanup_token + ".tmp",
        )
        if os.path.lexists(initialization_path):
            return
        tombstone_path = path
    else:
        assert initialization_token is not None
        tombstone_path = os.path.join(
            parent_path,
            _INCLUDED_FILES_LOCK_CLEANUP_PREFIX
            + initialization_token
            + ".tmp",
        )
        if os.path.lexists(tombstone_path):
            return
        _move_exact_included_file(
            path,
            tombstone_path,
            expected_identity,
            source_parent_identity=project_identity,
            destination_parent_identity=project_identity,
        )
        _sync_included_directory(parent_path, project_identity)
        _after_included_lock_initialization_phase("temporary-cleanup-quarantined")

    tombstone_state = _included_lock_initialization_record_state(
        tombstone_path,
        project_identity,
        allowed_identities=frozenset({expected_identity}),
    )
    if (
        tombstone_state is None
        or tombstone_state[2] != _INCLUDED_FILES_LOCK_CONTENT
    ):
        return
    _remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        project_identity,
        expect_directory=False,
    )
    _after_included_lock_initialization_phase("temporary-cleanup-removed")


def _cleanup_included_lock_initialization_temporaries(
    project_path: str,
    project_identity: _PathIdentity,
) -> None:
    for name in sorted(os.listdir(project_path)):
        managed = False
        for prefix, label in (
            (
                _INCLUDED_FILES_LOCK_TEMP_PREFIX,
                "lock initialization temporary",
            ),
            (
                _INCLUDED_FILES_LOCK_CLEANUP_PREFIX,
                "lock initialization cleanup tombstone",
            ),
        ):
            try:
                _included_recovery_managed_name(
                    name,
                    prefix=prefix,
                    suffix=".tmp",
                    label=label,
                )
            except OSError:
                continue
            managed = True
            break
        if not managed:
            continue
        candidate_path = os.path.join(project_path, name)
        try:
            state = _included_lock_initialization_record_state(
                candidate_path,
                project_identity,
            )
            if state is None or state[2] != _INCLUDED_FILES_LOCK_CONTENT:
                continue
            _remove_exact_included_lock_initialization_temporary(
                candidate_path,
                state[0],
                project_identity,
            )
        except OSError:
            # Partial, redirected, aliased, or concurrently changed candidates are
            # not sufficient evidence of converter ownership and stay untouched.
            continue


def _initialize_included_project_lock(
    project_path: str,
    project_identity: _PathIdentity,
    *,
    project_fd: int,
) -> None:
    lock_path = os.path.join(project_path, _INCLUDED_FILES_LOCK_NAME)
    file_descriptor = -1
    temporary_path = ""
    temporary_identity: _PathIdentity | None = None
    for _attempt in range(100):
        temporary_name = (
            _INCLUDED_FILES_LOCK_TEMP_PREFIX + secrets.token_hex(8) + ".tmp"
        )
        candidate_path = os.path.join(project_path, temporary_name)
        try:
            temporary_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            if project_fd >= 0:
                file_descriptor = os.open(
                    temporary_name,
                    temporary_flags,
                    0o600,
                    dir_fd=project_fd,
                )
            else:
                file_descriptor = os.open(
                    candidate_path,
                    temporary_flags,
                    0o600,
                )
        except FileExistsError:
            continue
        temporary_path = candidate_path
        temporary_stat = os.fstat(file_descriptor)
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        break
    if file_descriptor < 0 or not temporary_path or temporary_identity is None:
        raise OSError("Could not allocate Included Files lock initialization record")

    temporary_pending = True
    try:
        try:
            _after_included_lock_initialization_phase("temporary-created")
            _write_included_lock_initialization_temporary(file_descriptor)
            os.close(file_descriptor)
            file_descriptor = -1
            temporary_state = _included_lock_initialization_record_state(
                temporary_path,
                project_identity,
                allowed_identities=frozenset({temporary_identity}),
            )
            if (
                temporary_state is None
                or temporary_state[2] != _INCLUDED_FILES_LOCK_CONTENT
            ):
                raise OSError("Included Files lock initialization record changed")
            _sync_included_directory(project_path, project_identity)
            _after_included_lock_initialization_phase("temporary-synced")
            _move_exact_included_file(
                temporary_path,
                lock_path,
                temporary_identity,
                source_parent_identity=project_identity,
                destination_parent_identity=project_identity,
            )
            temporary_pending = False
            _sync_included_directory(project_path, project_identity)
            _after_included_lock_initialization_phase("temporary-published")
        except OSError:
            # A competing initializer may have atomically published the complete
            # stable record first. The caller opens and validates that winner.
            stable_exists = (
                _included_entry_stat_at(project_fd, _INCLUDED_FILES_LOCK_NAME)
                is not None
                if project_fd >= 0
                else os.path.lexists(lock_path)
            )
            if not stable_exists:
                raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _remove_exact_included_lock_initialization_temporary(
                    temporary_path,
                    temporary_identity,
                    project_identity,
                )
            except OSError:
                pass


def _acquire_included_project_lock(
    project_path: str,
    project_identity: _PathIdentity,
) -> _IncludedProjectLock:
    """Acquire the cooperative lock that serializes recovery and publication."""

    lock_path = os.path.join(project_path, _INCLUDED_FILES_LOCK_NAME)
    flags = (
        os.O_RDWR
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    project_fd = -1
    descriptor_bound = _included_descriptor_paths_supported()
    if descriptor_bound:
        project_fd = _open_pinned_included_directory(project_path)
        try:
            _verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
        except BaseException:
            os.close(project_fd)
            raise

    def open_lock(open_flags: int, mode: int = 0o600) -> int:
        if descriptor_bound:
            return os.open(
                _INCLUDED_FILES_LOCK_NAME,
                open_flags,
                mode,
                dir_fd=project_fd,
            )
        return os.open(lock_path, open_flags, mode)

    def lock_lstat() -> os.stat_result:
        if descriptor_bound:
            return os.stat(
                _INCLUDED_FILES_LOCK_NAME,
                dir_fd=project_fd,
                follow_symlinks=False,
            )
        return os.lstat(lock_path)

    try:
        try:
            file_descriptor = open_lock(flags)
        except FileNotFoundError:
            _initialize_included_project_lock(
                project_path,
                project_identity,
                project_fd=project_fd,
            )
            file_descriptor = open_lock(flags)
    except BaseException:
        if project_fd >= 0:
            os.close(project_fd)
        raise

    windows = os.name == "nt"
    locked = False
    try:
        opened_stat = os.fstat(file_descriptor)
        path_stat = lock_lstat()
        if (
            _included_output_path_is_redirected(lock_path, path_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or not os.path.samestat(opened_stat, path_stat)
            or opened_stat.st_nlink != 1
        ):
            raise OSError(
                "Refusing redirected or aliased Included Files transaction lock: "
                + lock_path
            )
        if windows:
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            try:
                _windows_included_file_locking(file_descriptor, 2)
            except OSError as error:
                raise OSError(
                    "Another GM2Godot conversion is already publishing or "
                    f"recovering Included Files in {project_path}"
                ) from error
            locked = True
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        initial_content = os.read(
            file_descriptor,
            len(_INCLUDED_FILES_LOCK_CONTENT) + 1,
        )
        if initial_content != _INCLUDED_FILES_LOCK_CONTENT:
            raise OSError(
                "Refusing an unknown or incomplete file at the reserved Included "
                f"Files transaction lock path: {lock_path}"
            )
        if not windows:
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            try:
                import fcntl

                fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise OSError(
                    "Another GM2Godot conversion is already publishing or "
                    f"recovering Included Files in {project_path}"
                ) from error
            locked = True

        os.lseek(file_descriptor, 0, os.SEEK_SET)
        current_content = os.read(
            file_descriptor,
            len(_INCLUDED_FILES_LOCK_CONTENT) + 1,
        )
        if current_content != _INCLUDED_FILES_LOCK_CONTENT:
            raise OSError(
                "Included Files transaction lock changed after acquisition: "
                + lock_path
            )
        _verify_included_project_identity(project_path, project_identity)
        if descriptor_bound:
            _verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
        final_stat = lock_lstat()
        if (
            _included_output_path_is_redirected(lock_path, final_stat)
            or not os.path.samestat(os.fstat(file_descriptor), final_stat)
        ):
            raise OSError(f"Included Files transaction lock changed: {lock_path}")
        _cleanup_included_lock_initialization_temporaries(
            project_path,
            project_identity,
        )
        project_lock = _IncludedProjectLock(
            file_descriptor=file_descriptor,
            path=lock_path,
            windows=windows,
        )
        if project_fd >= 0:
            os.close(project_fd)
        return project_lock
    except BaseException:
        if locked:
            try:
                if windows:
                    os.lseek(file_descriptor, 0, os.SEEK_SET)
                    _windows_included_file_locking(file_descriptor, 0)
                else:
                    import fcntl

                    fcntl.flock(file_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(file_descriptor)
        if project_fd >= 0:
            os.close(project_fd)
        raise


def _release_included_project_lock(project_lock: _IncludedProjectLock) -> None:
    try:
        if project_lock.windows:
            os.lseek(project_lock.file_descriptor, 0, os.SEEK_SET)
            _windows_included_file_locking(project_lock.file_descriptor, 0)
        else:
            import fcntl

            fcntl.flock(project_lock.file_descriptor, fcntl.LOCK_UN)
    finally:
        os.close(project_lock.file_descriptor)


def _included_identity_payload(identity: _PathIdentity | None) -> list[int] | None:
    return None if identity is None else [identity[0], identity[1]]


def _included_recovery_compact_integer_payload(
    value: int,
    label: str,
) -> str:
    if (
        type(value) is not int
        or value < 0
        or value > _INCLUDED_FILES_RECOVERY_INTEGER_MAX
    ):
        raise OSError(f"Included Files recovery {label} is outside uint64")
    return f"{value:0{_INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS}x}"


def _included_compact_identity_payload(
    identity: _PathIdentity | None,
) -> list[str] | None:
    if identity is None:
        return None
    return [
        _included_recovery_compact_integer_payload(
            identity[0],
            "identity device",
        ),
        _included_recovery_compact_integer_payload(
            identity[1],
            "identity inode",
        ),
    ]


def _included_compact_fingerprint_payload(
    fingerprint: _PathFingerprint,
) -> list[str]:
    return [
        _included_recovery_compact_integer_payload(
            component,
            "fingerprint component",
        )
        for component in fingerprint
    ]


def _included_tree_snapshot_payload(snapshot: _IncludedTreeSnapshot) -> dict[str, Any]:
    """Serialize the legacy format-v1 tree representation."""

    return {
        "root_fingerprint": (
            None
            if snapshot.root_fingerprint is None
            else list(snapshot.root_fingerprint)
        ),
        "entries": [
            {
                "relative_path": entry.relative_path,
                "kind": entry.kind,
                "fingerprint": list(entry.fingerprint),
                "ctime_ns": entry.ctime_ns,
                "content_sha256": entry.content_sha256,
            }
            for entry in snapshot.entries
        ],
    }


def _included_compact_tree_snapshot_payload(
    snapshot: _IncludedTreeSnapshot,
) -> list[Any]:
    """Serialize a format-v2 tree without per-entry field-name repetition."""

    if len(snapshot.entries) > _INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError("Included Files recovery tree has too many entries")
    return [
        (
            None
            if snapshot.root_fingerprint is None
            else _included_compact_fingerprint_payload(
                snapshot.root_fingerprint
            )
        ),
        [
            [
                entry.relative_path,
                "f" if entry.kind == "file" else "d",
                _included_compact_fingerprint_payload(entry.fingerprint),
                (
                    None
                    if entry.ctime_ns is None
                    else _included_recovery_compact_integer_payload(
                        entry.ctime_ns,
                        "entry ctime",
                    )
                ),
                entry.content_sha256,
            ]
            for entry in snapshot.entries
        ],
    ]


def _included_registry_snapshot_payload(
    snapshot: _IncludedRegistrySnapshot,
) -> dict[str, Any]:
    """Serialize the legacy format-v1 registry representation."""

    return {
        "directory_identity": _included_identity_payload(
            snapshot.directory_identity
        ),
        "file_identity": _included_identity_payload(snapshot.file_identity),
        "file_mode": snapshot.file_mode,
        "content_base64": (
            None
            if snapshot.content is None
            else base64.b64encode(snapshot.content).decode("ascii")
        ),
    }


def _included_compact_registry_snapshot_payload(
    snapshot: _IncludedRegistrySnapshot,
) -> list[Any]:
    return [
        _included_compact_identity_payload(snapshot.directory_identity),
        _included_compact_identity_payload(snapshot.file_identity),
        (
            None
            if snapshot.file_mode is None
            else _included_recovery_compact_integer_payload(
                snapshot.file_mode,
                "registry mode",
            )
        ),
        (
            None
            if snapshot.content is None
            else base64.b64encode(snapshot.content).decode("ascii")
        ),
    ]


def _included_registry_backup_location(
    journal: _IncludedRecoveryJournal,
) -> str:
    transaction = journal.transaction
    project_path = os.path.dirname(transaction.stage_container_path)
    registry_directory = os.path.dirname(_included_registry_path(project_path))
    registry_backup_parent = os.path.dirname(journal.registry_backup_path)
    if os.path.normcase(os.path.abspath(registry_backup_parent)) == os.path.normcase(
        os.path.abspath(project_path)
    ):
        registry_backup_location = "project"
    elif os.path.normcase(os.path.abspath(registry_backup_parent)) == os.path.normcase(
        os.path.abspath(registry_directory)
    ):
        registry_backup_location = "registry"
    else:
        raise OSError("Included File registry backup escaped its managed parents")
    return registry_backup_location


def _included_recovery_journal_payload_v1(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    transaction = journal.transaction
    registry_backup_location = _included_registry_backup_location(journal)
    return {
        "format_version": _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "project_identity": _included_identity_payload(transaction.project_identity),
        "stage_container_name": os.path.basename(transaction.stage_container_path),
        "stage_container_identity": _included_identity_payload(
            transaction.stage_container_identity
        ),
        "staged_container_snapshot": _included_tree_snapshot_payload(
            transaction.staged_container_snapshot
        ),
        "staged_root_snapshot": _included_tree_snapshot_payload(
            transaction.staged_root_snapshot
        ),
        "staged_registry_identity": _included_identity_payload(
            transaction.staged_registry_identity
        ),
        "staged_registry_mode": transaction.staged_registry_mode,
        "staged_registry_content_base64": base64.b64encode(
            transaction.staged_registry_content
        ).decode("ascii"),
        "previous_root_snapshot": _included_tree_snapshot_payload(
            transaction.previous_root_snapshot
        ),
        "previous_registry_snapshot": _included_registry_snapshot_payload(
            transaction.previous_registry_snapshot
        ),
        "root_backup_name": os.path.basename(journal.root_backup_path),
        "registry_backup_name": os.path.basename(journal.registry_backup_path),
        "registry_backup_location": registry_backup_location,
        "registry_directory_identity": _included_identity_payload(
            journal.registry_directory_identity
        ),
        "registry_directory_created": journal.registry_directory_created,
    }


def _included_recovery_journal_payload_v2(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    transaction = journal.transaction
    registry_backup_location = _included_registry_backup_location(journal)
    return {
        "format_version": _INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "project_identity": _included_compact_identity_payload(
            transaction.project_identity
        ),
        "stage_container_name": os.path.basename(
            transaction.stage_container_path
        ),
        "stage_container_identity": _included_compact_identity_payload(
            transaction.stage_container_identity
        ),
        "staged_container_snapshot": _included_compact_tree_snapshot_payload(
            transaction.staged_container_snapshot
        ),
        "staged_root_snapshot": _included_compact_tree_snapshot_payload(
            transaction.staged_root_snapshot
        ),
        "staged_registry_identity": _included_compact_identity_payload(
            transaction.staged_registry_identity
        ),
        "staged_registry_mode": _included_recovery_compact_integer_payload(
            transaction.staged_registry_mode,
            "staged registry mode",
        ),
        "staged_registry_content_base64": base64.b64encode(
            transaction.staged_registry_content
        ).decode("ascii"),
        "previous_root_snapshot": _included_compact_tree_snapshot_payload(
            transaction.previous_root_snapshot
        ),
        "previous_registry_snapshot": _included_compact_registry_snapshot_payload(
            transaction.previous_registry_snapshot
        ),
        "root_backup_name": os.path.basename(journal.root_backup_path),
        "registry_backup_name": os.path.basename(journal.registry_backup_path),
        "registry_backup_location": registry_backup_location,
        "registry_directory_identity": _included_compact_identity_payload(
            journal.registry_directory_identity
        ),
        "registry_directory_created": journal.registry_directory_created,
    }


def _included_recovery_journal_payload(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    if journal.format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return _included_recovery_journal_payload_v1(journal)
    if journal.format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return _included_recovery_journal_payload_v2(journal)
    raise OSError("Unsupported Included Files recovery journal format")


def _included_tree_snapshot_sha256(
    snapshot: _IncludedTreeSnapshot,
    format_version: int,
) -> str:
    if format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        payload: Any = _included_tree_snapshot_payload(snapshot)
        compact = False
    elif format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        payload = _included_compact_tree_snapshot_payload(snapshot)
        compact = True
    else:
        raise OSError("Unsupported Included Files recovery tree digest format")
    return hashlib.sha256(
        _included_serialized_json_content(
            {"tree_snapshot": payload},
            compact=compact,
        )
    ).hexdigest()


def _included_commit_marker_from_journal(
    journal: _IncludedRecoveryJournal,
) -> _IncludedCommitMarker:
    transaction = journal.transaction
    root_identity = transaction.staged_root_snapshot.identity
    if root_identity is None:
        raise AssertionError("A committed Included Files root must be present")
    return _IncludedCommitMarker(
        format_version=journal.format_version,
        transaction_id=journal.transaction_id,
        project_identity=transaction.project_identity,
        root_identity=root_identity,
        root_snapshot_sha256=_included_tree_snapshot_sha256(
            transaction.staged_root_snapshot,
            journal.format_version,
        ),
        registry_directory_identity=journal.registry_directory_identity,
        registry_identity=transaction.staged_registry_identity,
        registry_content_sha256=hashlib.sha256(
            transaction.staged_registry_content
        ).hexdigest(),
    )


def _included_commit_marker_payload_v1(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    versioned_journal = replace(
        journal,
        format_version=_INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
    )
    marker = _included_commit_marker_from_journal(versioned_journal)
    journal_payload = _included_recovery_journal_payload_v1(
        versioned_journal
    )
    return {
        "format_version": _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
        "state": "committed",
        "transaction_id": marker.transaction_id,
        "project_identity": _included_identity_payload(marker.project_identity),
        "root_identity": _included_identity_payload(marker.root_identity),
        "root_snapshot_sha256": marker.root_snapshot_sha256,
        "registry_directory_identity": _included_identity_payload(
            marker.registry_directory_identity
        ),
        "registry_identity": _included_identity_payload(marker.registry_identity),
        "registry_content_sha256": marker.registry_content_sha256,
        "recovery_journal": journal_payload,
        "recovery_journal_sha256": hashlib.sha256(
            _included_recovery_record_content(journal_payload)
        ).hexdigest(),
    }


def _included_commit_marker_payload_v2(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    versioned_journal = replace(
        journal,
        format_version=_INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
    )
    marker = _included_commit_marker_from_journal(versioned_journal)
    journal_payload = _included_recovery_journal_payload_v2(
        versioned_journal
    )
    return {
        "format_version": _INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        "state": "committed",
        "transaction_id": marker.transaction_id,
        "project_identity": _included_compact_identity_payload(
            marker.project_identity
        ),
        "root_identity": _included_compact_identity_payload(
            marker.root_identity
        ),
        "root_snapshot_sha256": marker.root_snapshot_sha256,
        "registry_directory_identity": _included_compact_identity_payload(
            marker.registry_directory_identity
        ),
        "registry_identity": _included_compact_identity_payload(
            marker.registry_identity
        ),
        "registry_content_sha256": marker.registry_content_sha256,
        "recovery_journal": journal_payload,
        "recovery_journal_sha256": hashlib.sha256(
            _included_recovery_record_content(journal_payload)
        ).hexdigest(),
    }


def _included_commit_marker_payload(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    if journal.format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return _included_commit_marker_payload_v1(journal)
    if journal.format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return _included_commit_marker_payload_v2(journal)
    raise OSError("Unsupported Included Files recovery commit format")


def _included_recovery_record_sizes(
    journal: _IncludedRecoveryJournal,
) -> _IncludedRecoveryRecordSizes:
    journal_content = _included_recovery_record_content(
        _included_recovery_journal_payload(journal)
    )
    commit_content = _included_recovery_record_content(
        _included_commit_marker_payload(journal)
    )
    return _IncludedRecoveryRecordSizes(
        journal_bytes=len(journal_content),
        commit_bytes=len(commit_content),
    )


def _included_preflight_placeholder_snapshots(
    project_identity: _PathIdentity,
    assigned_byte_counts: dict[str, int],
    staged_registry_content: bytes,
) -> tuple[
    _PathIdentity,
    _IncludedTreeSnapshot,
    _IncludedTreeSnapshot,
    _PathIdentity,
    int,
]:
    if len(assigned_byte_counts) > _INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError("Included Files recovery tree has too many entries")
    device = project_identity[0]
    used_inodes = {project_identity[1]}
    next_inode = _INCLUDED_FILES_RECOVERY_INTEGER_MAX

    def allocate_identity() -> _PathIdentity:
        nonlocal next_inode
        while next_inode in used_inodes:
            next_inode -= 1
        if next_inode < 0:
            raise OSError("Could not allocate Included Files preflight identity")
        identity = (device, next_inode)
        used_inodes.add(next_inode)
        next_inode -= 1
        return identity

    def fingerprint(
        identity: _PathIdentity,
        mode: int,
        size: int,
    ) -> _PathFingerprint:
        return (identity[0], identity[1], mode, size, 0, 1)

    assigned_paths = sorted(assigned_byte_counts)
    directory_paths = sorted(
        {
            "/".join(path.split("/")[:component_count])
            for path in assigned_paths
            for component_count in range(1, len(path.split("/")))
        }
    )
    if len(assigned_paths) + len(directory_paths) > (
        _INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES
    ):
        raise OSError("Included Files recovery tree has too many entries")
    for relative_path in (*directory_paths, *assigned_paths):
        _included_recovery_relative_path(relative_path)

    staged_root_identity = allocate_identity()
    staged_root_fingerprint = fingerprint(
        staged_root_identity,
        stat.S_IFDIR | 0o755,
        0,
    )
    entry_kinds = {
        **{path: "directory" for path in directory_paths},
        **{path: "file" for path in assigned_paths},
    }
    staged_root_entries: list[_IncludedTreeEntry] = []
    for relative_path in sorted(entry_kinds):
        kind = entry_kinds[relative_path]
        identity = allocate_identity()
        if kind == "directory":
            staged_root_entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=fingerprint(
                        identity,
                        stat.S_IFDIR | 0o755,
                        0,
                    ),
                    ctime_ns=None,
                    content_sha256=None,
                )
            )
        else:
            byte_count = assigned_byte_counts[relative_path]
            staged_root_entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=fingerprint(
                        identity,
                        stat.S_IFREG | 0o600,
                        byte_count,
                    ),
                    ctime_ns=0,
                    content_sha256=(
                        _INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256
                    ),
                )
            )
    staged_root_snapshot = _IncludedTreeSnapshot(
        root_fingerprint=staged_root_fingerprint,
        entries=tuple(staged_root_entries),
    )

    stage_container_identity = allocate_identity()
    stage_marker_identity = allocate_identity()
    staged_registry_identity = allocate_identity()
    staged_registry_mode = 0o600
    stage_marker_content = _included_recovery_record_content(
        {
            "format_version": _INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": _included_identity_payload(project_identity),
            "stage_identity": _included_identity_payload(
                stage_container_identity
            ),
        }
    )
    container_entries = [
        _IncludedTreeEntry(
            relative_path=_INCLUDED_FILES_STAGE_MARKER_NAME,
            kind="file",
            fingerprint=fingerprint(
                stage_marker_identity,
                stat.S_IFREG | 0o600,
                len(stage_marker_content),
            ),
            ctime_ns=0,
            content_sha256=hashlib.sha256(stage_marker_content).hexdigest(),
        ),
        _IncludedTreeEntry(
            relative_path=_INCLUDED_FILES_ROOT_NAME,
            kind="directory",
            fingerprint=staged_root_fingerprint,
            ctime_ns=None,
            content_sha256=None,
        ),
        *(
            _IncludedTreeEntry(
                relative_path=(
                    _INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
                ),
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=entry.content_sha256,
            )
            for entry in staged_root_entries
        ),
        _IncludedTreeEntry(
            relative_path="gml_included_file_registry.gd",
            kind="file",
            fingerprint=fingerprint(
                staged_registry_identity,
                stat.S_IFREG | staged_registry_mode,
                len(staged_registry_content),
            ),
            ctime_ns=0,
            content_sha256=hashlib.sha256(
                staged_registry_content
            ).hexdigest(),
        ),
    ]
    staged_container_snapshot = _IncludedTreeSnapshot(
        root_fingerprint=fingerprint(
            stage_container_identity,
            stat.S_IFDIR | 0o700,
            0,
        ),
        entries=tuple(
            sorted(
                container_entries,
                key=lambda entry: entry.relative_path,
            )
        ),
    )
    return (
        stage_container_identity,
        staged_container_snapshot,
        staged_root_snapshot,
        staged_registry_identity,
        staged_registry_mode,
    )


def _preflight_included_recovery_record_sizes(
    project_path: str,
    project_identity: _PathIdentity,
    assigned_byte_counts: dict[str, int],
    staged_registry_content: bytes,
    previous_root_snapshot: _IncludedTreeSnapshot,
    previous_registry_snapshot: _IncludedRegistrySnapshot,
) -> _IncludedRecoveryRecordSizes:
    """Serialize exact-size format-v2 stand-ins before payload staging."""

    try:
        (
            stage_container_identity,
            staged_container_snapshot,
            staged_root_snapshot,
            staged_registry_identity,
            staged_registry_mode,
        ) = _included_preflight_placeholder_snapshots(
            project_identity,
            assigned_byte_counts,
            staged_registry_content,
        )
        token = "0" * 16
        stage_container_path = os.path.join(
            project_path,
            _INCLUDED_FILES_STAGE_PREFIX + token + ".stage",
        )
        registry_directory_path = os.path.dirname(
            _included_registry_path(project_path)
        )
        registry_directory_created = (
            previous_registry_snapshot.directory_identity is None
        )
        registry_directory_identity = (
            previous_registry_snapshot.directory_identity
            or (
                project_identity[0],
                _INCLUDED_FILES_RECOVERY_INTEGER_MAX - 4,
            )
        )
        registry_backup_parent = (
            registry_directory_path
            if previous_registry_snapshot.file_identity is not None
            else project_path
        )
        transaction = _IncludedOutputSetTransaction(
            project_identity=project_identity,
            stage_container_path=stage_container_path,
            stage_container_identity=stage_container_identity,
            staged_container_snapshot=staged_container_snapshot,
            staged_root_path=os.path.join(
                stage_container_path,
                _INCLUDED_FILES_ROOT_NAME,
            ),
            staged_root_snapshot=staged_root_snapshot,
            staged_registry_path=os.path.join(
                stage_container_path,
                "gml_included_file_registry.gd",
            ),
            staged_registry_identity=staged_registry_identity,
            staged_registry_mode=staged_registry_mode,
            staged_registry_content=staged_registry_content,
            previous_root_snapshot=previous_root_snapshot,
            previous_registry_snapshot=previous_registry_snapshot,
        )
        journal = _IncludedRecoveryJournal(
            format_version=_INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id="0" * 32,
            transaction=transaction,
            root_backup_path=os.path.join(
                project_path,
                f".included_files.{token}.backup",
            ),
            registry_backup_path=os.path.join(
                registry_backup_parent,
                f".gml_included_file_registry.gd.{token}.backup",
            ),
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        return _included_recovery_record_sizes(journal)
    except OSError as error:
        raise OSError(
            "Included Files recovery metadata preflight failed before payload "
            f"staging: {error}"
        ) from error


def _verify_included_recovery_record_sizes(
    expected: _IncludedRecoveryRecordSizes,
    journal: _IncludedRecoveryJournal,
) -> None:
    actual = _included_recovery_record_sizes(journal)
    if actual != expected:
        raise OSError(
            "Included Files recovery metadata changed after its byte-accurate "
            "preflight"
        )


def _included_recovery_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OSError(f"Invalid Included Files recovery {label}")
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(dict[str, Any], mapping)


def _included_recovery_exact_keys(
    payload: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    if payload.keys() != expected:
        raise OSError(f"Invalid Included Files recovery {label} fields")


def _included_recovery_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_compact_int(value: Any, label: str) -> int:
    if (
        not isinstance(value, str)
        or len(value) != _INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return int(value, 16)


def _included_recovery_identity(
    value: Any,
    label: str,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if value is None and optional:
        return None
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    first = _included_recovery_int(components[0], label)
    second = _included_recovery_int(components[1], label)
    if first < 0 or second < 0:
        raise OSError(f"Invalid Included Files recovery {label}")
    return (first, second)


def _included_recovery_compact_identity(
    value: Any,
    label: str,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if value is None and optional:
        return None
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    return (
        _included_recovery_compact_int(components[0], label),
        _included_recovery_compact_int(components[1], label),
    )


def _included_recovery_identity_for_format(
    value: Any,
    label: str,
    format_version: int,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return _included_recovery_identity(
            value,
            label,
            optional=optional,
        )
    if format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return _included_recovery_compact_identity(
            value,
            label,
            optional=optional,
        )
    raise OSError("Unsupported Included Files recovery identity format")


def _included_recovery_fingerprint(value: Any, label: str) -> _PathFingerprint:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 6:
        raise OSError(f"Invalid Included Files recovery {label}")
    fingerprint = tuple(
        _included_recovery_int(component, label) for component in components
    )
    if any(component < 0 for component in fingerprint):
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(_PathFingerprint, fingerprint)


def _included_recovery_compact_fingerprint(
    value: Any,
    label: str,
) -> _PathFingerprint:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 6:
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(
        _PathFingerprint,
        tuple(
            _included_recovery_compact_int(component, label)
            for component in components
        ),
    )


def _included_recovery_sha256(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise OSError(f"Invalid Included Files recovery {label}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OSError(f"Invalid Included Files recovery {label}") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        raise OSError(f"Non-canonical Included Files recovery {label}")
    return decoded


def _included_windows_recovery_component_is_ambiguous(component: str) -> bool:
    if len(component) >= 2 and component[1] == ":":
        # A drive-relative component such as ``D:payload`` can discard every
        # previously joined component when reconstructed with Windows paths.
        return True
    if component.startswith(" ") or component.endswith((" ", ".")):
        return True
    if any(
        ord(character) < 32 or character in '<>:"|?*'
        for character in component
    ):
        # This includes NTFS alternate-data-stream separators.
        return True
    device_stem = component.split(".", 1)[0].rstrip(" ").upper()
    return device_stem in _WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES


def _included_recovery_relative_path(value: Any) -> str:
    if not isinstance(value, str):
        raise OSError("Invalid Included Files recovery tree path")
    components = value.split("/")
    if (
        value == ""
        or value.startswith("/")
        or "\0" in value
        or "\\" in value
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise OSError("Invalid Included Files recovery tree path")
    if os.name == "nt" and any(
        _included_windows_recovery_component_is_ambiguous(component)
        for component in components
    ):
        raise OSError("Windows-ambiguous Included Files recovery tree path")
    return value


def _included_recovery_tree_entry_path(
    root_path: str,
    relative_path: str,
) -> str:
    """Reconstruct one journal path without permitting platform path resets."""

    validated_relative_path = _included_recovery_relative_path(relative_path)
    components = validated_relative_path.split("/")
    absolute_root = os.path.abspath(root_path)
    native_relative_path = os.path.join(*components)
    absolute_entry = os.path.abspath(
        os.path.join(absolute_root, native_relative_path)
    )
    try:
        common_root = os.path.commonpath((absolute_root, absolute_entry))
        round_trip = os.path.relpath(absolute_entry, absolute_root)
    except ValueError as error:
        raise OSError(
            "Included Files recovery tree path escaped its recorded root"
        ) from error
    if (
        os.path.normcase(common_root) != os.path.normcase(absolute_root)
        or os.path.isabs(round_trip)
        or os.path.normcase(round_trip)
        != os.path.normcase(native_relative_path)
    ):
        raise OSError(
            "Included Files recovery tree path escaped its recorded root"
        )
    return absolute_entry


def _included_tree_snapshot_from_payload_v1(
    value: Any,
    label: str,
) -> _IncludedTreeSnapshot:
    payload = _included_recovery_dict(value, label)
    _included_recovery_exact_keys(
        payload,
        frozenset({"root_fingerprint", "entries"}),
        label,
    )
    root_value = payload.get("root_fingerprint")
    root_fingerprint = (
        None
        if root_value is None
        else _included_recovery_fingerprint(
            root_value,
            label + " root fingerprint",
        )
    )
    entries_value = payload.get("entries")
    if not isinstance(entries_value, list):
        raise OSError(f"Invalid Included Files recovery {label} entries")
    raw_entries = cast(list[Any], entries_value)
    if len(raw_entries) > _INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError(f"Included Files recovery {label} has too many entries")
    entries: list[_IncludedTreeEntry] = []
    seen_paths: set[str] = set()
    for raw_entry in raw_entries:
        entry_payload = _included_recovery_dict(raw_entry, label + " entry")
        _included_recovery_exact_keys(
            entry_payload,
            frozenset(
                {
                    "relative_path",
                    "kind",
                    "fingerprint",
                    "ctime_ns",
                    "content_sha256",
                }
            ),
            label + " entry",
        )
        relative_path = _included_recovery_relative_path(
            entry_payload.get("relative_path")
        )
        if relative_path in seen_paths:
            raise OSError(f"Duplicate Included Files recovery tree path: {relative_path}")
        seen_paths.add(relative_path)
        kind = entry_payload.get("kind")
        if not isinstance(kind, str) or kind not in {"file", "directory"}:
            raise OSError(f"Invalid Included Files recovery tree kind: {relative_path}")
        fingerprint = _included_recovery_fingerprint(
            entry_payload.get("fingerprint"),
            label + " entry fingerprint",
        )
        expected_kind = stat.S_IFREG if kind == "file" else stat.S_IFDIR
        if stat.S_IFMT(fingerprint[2]) != expected_kind:
            raise OSError(f"Invalid Included Files recovery tree mode: {relative_path}")
        ctime_value = entry_payload.get("ctime_ns")
        ctime_ns = (
            None
            if ctime_value is None
            else _included_recovery_int(ctime_value, label + " entry ctime")
        )
        content_sha256 = _included_recovery_sha256(
            entry_payload.get("content_sha256"),
            label + " entry content digest",
        )
        if kind == "directory":
            if ctime_ns is not None or content_sha256 is not None:
                raise OSError(
                    "Invalid Included Files recovery directory receipt: "
                    + relative_path
                )
        elif ctime_ns is None or ctime_ns < 0 or content_sha256 is None:
            raise OSError(
                "Incomplete Included Files recovery file receipt: " + relative_path
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    return _validated_included_tree_snapshot(
        root_fingerprint,
        entries,
        label,
    )


def _validated_included_tree_snapshot(
    root_fingerprint: _PathFingerprint | None,
    entries: list[_IncludedTreeEntry],
    label: str,
) -> _IncludedTreeSnapshot:
    if root_fingerprint is None and entries:
        raise OSError(f"Invalid Included Files recovery absent {label}")
    if root_fingerprint is not None and not stat.S_ISDIR(root_fingerprint[2]):
        raise OSError(f"Invalid Included Files recovery {label} root mode")
    if root_fingerprint is not None and root_fingerprint[5] < 1:
        raise OSError(f"Invalid Included Files recovery {label} root link count")
    if any(entry.fingerprint[5] < 1 for entry in entries):
        raise OSError(f"Invalid Included Files recovery {label} link count")
    if root_fingerprint is not None and any(
        entry.fingerprint[0] != root_fingerprint[0] for entry in entries
    ):
        raise OSError(
            f"Invalid cross-device Included Files recovery {label}"
        )
    directory_paths = {
        entry.relative_path for entry in entries if entry.kind == "directory"
    }
    if any(
        (parent := posixpath.dirname(entry.relative_path))
        and parent not in directory_paths
        for entry in entries
    ):
        raise OSError(f"Invalid Included Files recovery {label} topology")
    if entries != sorted(entries, key=lambda entry: entry.relative_path):
        raise OSError(f"Unsorted Included Files recovery {label}")
    return _IncludedTreeSnapshot(
        root_fingerprint=root_fingerprint,
        entries=tuple(entries),
    )


def _included_tree_snapshot_from_payload_v2(
    value: Any,
    label: str,
) -> _IncludedTreeSnapshot:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    root_value, entries_value = components
    root_fingerprint = (
        None
        if root_value is None
        else _included_recovery_compact_fingerprint(
            root_value,
            label + " root fingerprint",
        )
    )
    if not isinstance(entries_value, list):
        raise OSError(f"Invalid Included Files recovery {label} entries")
    raw_entries = cast(list[Any], entries_value)
    if len(raw_entries) > _INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError(f"Included Files recovery {label} has too many entries")

    entries: list[_IncludedTreeEntry] = []
    seen_paths: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, list):
            raise OSError(f"Invalid Included Files recovery {label} entry")
        entry_components = cast(list[Any], raw_entry)
        if len(entry_components) != 5:
            raise OSError(f"Invalid Included Files recovery {label} entry")
        (
            path_value,
            kind_value,
            fingerprint_value,
            ctime_value,
            digest_value,
        ) = entry_components
        relative_path = _included_recovery_relative_path(path_value)
        if relative_path in seen_paths:
            raise OSError(
                f"Duplicate Included Files recovery tree path: {relative_path}"
            )
        seen_paths.add(relative_path)
        if kind_value == "f":
            kind = "file"
        elif kind_value == "d":
            kind = "directory"
        else:
            raise OSError(
                f"Invalid Included Files recovery tree kind: {relative_path}"
            )
        fingerprint = _included_recovery_compact_fingerprint(
            fingerprint_value,
            label + " entry fingerprint",
        )
        expected_kind = stat.S_IFREG if kind == "file" else stat.S_IFDIR
        if stat.S_IFMT(fingerprint[2]) != expected_kind:
            raise OSError(
                f"Invalid Included Files recovery tree mode: {relative_path}"
            )
        ctime_ns = (
            None
            if ctime_value is None
            else _included_recovery_compact_int(
                ctime_value,
                label + " entry ctime",
            )
        )
        content_sha256 = _included_recovery_sha256(
            digest_value,
            label + " entry content digest",
        )
        if kind == "directory":
            if ctime_ns is not None or content_sha256 is not None:
                raise OSError(
                    "Invalid Included Files recovery directory receipt: "
                    + relative_path
                )
        elif ctime_ns is None or content_sha256 is None:
            raise OSError(
                "Incomplete Included Files recovery file receipt: "
                + relative_path
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    return _validated_included_tree_snapshot(
        root_fingerprint,
        entries,
        label,
    )


def _included_tree_snapshot_from_payload(
    value: Any,
    label: str,
    *,
    format_version: int = _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
) -> _IncludedTreeSnapshot:
    if format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return _included_tree_snapshot_from_payload_v1(value, label)
    if format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return _included_tree_snapshot_from_payload_v2(value, label)
    raise OSError("Unsupported Included Files recovery tree format")


def _included_registry_snapshot_from_payload_v1(
    value: Any,
) -> _IncludedRegistrySnapshot:
    payload = _included_recovery_dict(value, "registry snapshot")
    _included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "directory_identity",
                "file_identity",
                "file_mode",
                "content_base64",
            }
        ),
        "registry snapshot",
    )
    directory_identity = _included_recovery_identity(
        payload.get("directory_identity"),
        "registry directory identity",
        optional=True,
    )
    file_identity = _included_recovery_identity(
        payload.get("file_identity"),
        "registry file identity",
        optional=True,
    )
    file_mode_value = payload.get("file_mode")
    file_mode = (
        None
        if file_mode_value is None
        else _included_recovery_int(file_mode_value, "registry file mode")
    )
    if file_mode is not None and (
        file_mode < 0 or stat.S_IMODE(file_mode) != file_mode
    ):
        raise OSError("Invalid Included File registry recovery mode")
    content_value = payload.get("content_base64")
    content = (
        None
        if content_value is None
        else _included_recovery_bytes(content_value, "registry content")
    )
    if file_identity is None:
        if file_mode is not None or content is not None:
            raise OSError("Invalid absent Included File registry recovery state")
    elif directory_identity is None or file_mode is None or content is None:
        raise OSError("Incomplete Included File registry recovery state")
    elif file_identity[0] != directory_identity[0]:
        raise OSError("Invalid cross-device Included File registry recovery state")
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )


def _included_registry_snapshot_from_payload_v2(
    value: Any,
) -> _IncludedRegistrySnapshot:
    if not isinstance(value, list):
        raise OSError("Invalid Included Files recovery registry snapshot")
    components = cast(list[Any], value)
    if len(components) != 4:
        raise OSError("Invalid Included Files recovery registry snapshot")
    (
        directory_identity_value,
        file_identity_value,
        file_mode_value,
        content_value,
    ) = components
    directory_identity = _included_recovery_compact_identity(
        directory_identity_value,
        "registry directory identity",
        optional=True,
    )
    file_identity = _included_recovery_compact_identity(
        file_identity_value,
        "registry file identity",
        optional=True,
    )
    file_mode = (
        None
        if file_mode_value is None
        else _included_recovery_compact_int(
            file_mode_value,
            "registry file mode",
        )
    )
    if file_mode is not None and stat.S_IMODE(file_mode) != file_mode:
        raise OSError("Invalid Included File registry recovery mode")
    content = (
        None
        if content_value is None
        else _included_recovery_bytes(content_value, "registry content")
    )
    if file_identity is None:
        if file_mode is not None or content is not None:
            raise OSError("Invalid absent Included File registry recovery state")
    elif directory_identity is None or file_mode is None or content is None:
        raise OSError("Incomplete Included File registry recovery state")
    elif file_identity[0] != directory_identity[0]:
        raise OSError(
            "Invalid cross-device Included File registry recovery state"
        )
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )


def _included_registry_snapshot_from_payload(
    value: Any,
    *,
    format_version: int = _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
) -> _IncludedRegistrySnapshot:
    if format_version == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return _included_registry_snapshot_from_payload_v1(value)
    if format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return _included_registry_snapshot_from_payload_v2(value)
    raise OSError("Unsupported Included Files recovery registry format")


def _included_recovery_token(value: Any, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_managed_name(
    value: Any,
    *,
    prefix: str,
    suffix: str,
    label: str,
) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or not value.endswith(suffix):
        raise OSError(f"Invalid Included Files recovery {label}")
    token = value[len(prefix):len(value) - len(suffix)]
    _included_recovery_token(token, 16, label + " token")
    return value


def _included_recovery_journal_from_payload(
    project_path: str,
    project_identity: _PathIdentity,
    value: Any,
) -> _IncludedRecoveryJournal:
    payload = _included_recovery_dict(value, "journal")
    _included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "project_identity",
                "stage_container_name",
                "stage_container_identity",
                "staged_container_snapshot",
                "staged_root_snapshot",
                "staged_registry_identity",
                "staged_registry_mode",
                "staged_registry_content_base64",
                "previous_root_snapshot",
                "previous_registry_snapshot",
                "root_backup_name",
                "registry_backup_name",
                "registry_backup_location",
                "registry_directory_identity",
                "registry_directory_created",
            }
        ),
        "journal",
    )
    format_version = _included_recovery_int(
        payload.get("format_version"),
        "journal format version",
    )
    if (
        format_version
        not in {
            _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
            _INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        }
        or payload.get("state") != "prepared"
    ):
        raise OSError("Unsupported Included Files recovery journal")
    transaction_id = _included_recovery_token(
        payload.get("transaction_id"),
        32,
        "transaction id",
    )
    recorded_project_identity = _included_recovery_identity_for_format(
        payload.get("project_identity"),
        "project identity",
        format_version,
    )
    if recorded_project_identity != project_identity:
        raise OSError("Godot project root changed since Included Files interruption")
    stage_container_name = _included_recovery_managed_name(
        payload.get("stage_container_name"),
        prefix=_INCLUDED_FILES_STAGE_PREFIX,
        suffix=".stage",
        label="stage container",
    )
    stage_container_identity = _included_recovery_identity_for_format(
        payload.get("stage_container_identity"),
        "stage container identity",
        format_version,
    )
    if stage_container_identity is None:
        raise OSError("Missing Included Files recovery stage identity")
    staged_container_snapshot = _included_tree_snapshot_from_payload(
        payload.get("staged_container_snapshot"),
        "staged container snapshot",
        format_version=format_version,
    )
    if staged_container_snapshot.identity != stage_container_identity:
        raise OSError("Included Files recovery stage snapshot identity mismatch")
    staged_root_snapshot = _included_tree_snapshot_from_payload(
        payload.get("staged_root_snapshot"),
        "staged root snapshot",
        format_version=format_version,
    )
    if staged_root_snapshot.identity is None:
        raise OSError("Missing Included Files recovery staged root")
    staged_registry_identity = _included_recovery_identity_for_format(
        payload.get("staged_registry_identity"),
        "staged registry identity",
        format_version,
    )
    if staged_registry_identity is None:
        raise OSError("Missing Included Files recovery staged registry")
    staged_registry_mode = (
        _included_recovery_int(
            payload.get("staged_registry_mode"),
            "staged registry mode",
        )
        if format_version
        == _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
        else _included_recovery_compact_int(
            payload.get("staged_registry_mode"),
            "staged registry mode",
        )
    )
    if (
        staged_registry_mode < 0
        or stat.S_IMODE(staged_registry_mode) != staged_registry_mode
    ):
        raise OSError("Invalid Included Files recovery staged registry mode")
    staged_registry_content = _included_recovery_bytes(
        payload.get("staged_registry_content_base64"),
        "staged registry content",
    )
    previous_root_snapshot = _included_tree_snapshot_from_payload(
        payload.get("previous_root_snapshot"),
        "previous root snapshot",
        format_version=format_version,
    )
    previous_registry_snapshot = _included_registry_snapshot_from_payload(
        payload.get("previous_registry_snapshot"),
        format_version=format_version,
    )
    staged_entries = {
        entry.relative_path: entry
        for entry in staged_container_snapshot.entries
    }
    staged_root_entry = staged_entries.get(_INCLUDED_FILES_ROOT_NAME)
    staged_registry_entry = staged_entries.get("gml_included_file_registry.gd")
    staged_marker_entry = staged_entries.get(_INCLUDED_FILES_STAGE_MARKER_NAME)
    expected_stage_marker_content = _included_recovery_record_content(
        {
            "format_version": _INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": _included_identity_payload(project_identity),
            "stage_identity": _included_identity_payload(stage_container_identity),
        }
    )
    expected_staged_paths = {
        _INCLUDED_FILES_STAGE_MARKER_NAME,
        _INCLUDED_FILES_ROOT_NAME,
        "gml_included_file_registry.gd",
        *(
            _INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
            for entry in staged_root_snapshot.entries
        ),
    }
    staged_root_entries = {
        _INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path: entry
        for entry in staged_root_snapshot.entries
    }
    if (
        set(staged_entries) != expected_staged_paths
        or staged_root_entry is None
        or staged_root_entry.kind != "directory"
        or staged_root_entry.fingerprint != staged_root_snapshot.root_fingerprint
        or staged_registry_entry is None
        or staged_registry_entry.kind != "file"
        or staged_registry_entry.fingerprint[:2] != staged_registry_identity
        or stat.S_IMODE(staged_registry_entry.fingerprint[2])
        != staged_registry_mode
        or staged_registry_entry.fingerprint[3] != len(staged_registry_content)
        or staged_registry_entry.content_sha256
        != hashlib.sha256(staged_registry_content).hexdigest()
        or staged_marker_entry is None
        or staged_marker_entry.kind != "file"
        or staged_marker_entry.content_sha256
        != hashlib.sha256(expected_stage_marker_content).hexdigest()
        or staged_marker_entry.fingerprint[3] != len(expected_stage_marker_content)
        or any(
            (
                staged_entries[path].kind != expected_entry.kind
                or staged_entries[path].fingerprint != expected_entry.fingerprint
                or staged_entries[path].ctime_ns != expected_entry.ctime_ns
                or staged_entries[path].content_sha256
                != expected_entry.content_sha256
            )
            for path, expected_entry in staged_root_entries.items()
        )
    ):
        raise OSError("Included Files recovery staged snapshots disagree")
    root_backup_name = _included_recovery_managed_name(
        payload.get("root_backup_name"),
        prefix=".included_files.",
        suffix=".backup",
        label="root backup",
    )
    registry_backup_name = _included_recovery_managed_name(
        payload.get("registry_backup_name"),
        prefix=".gml_included_file_registry.gd.",
        suffix=".backup",
        label="registry backup",
    )
    registry_backup_location = payload.get("registry_backup_location")
    if (
        not isinstance(registry_backup_location, str)
        or registry_backup_location not in {"project", "registry"}
    ):
        raise OSError("Invalid Included File registry recovery backup location")
    expected_registry_backup_location = (
        "registry"
        if previous_registry_snapshot.file_identity is not None
        else "project"
    )
    if registry_backup_location != expected_registry_backup_location:
        raise OSError("Included File registry recovery backup location disagrees")
    registry_directory_identity = _included_recovery_identity_for_format(
        payload.get("registry_directory_identity"),
        "registry directory identity",
        format_version,
    )
    if registry_directory_identity is None:
        raise OSError("Missing Included File registry recovery directory")
    registry_directory_created = payload.get("registry_directory_created")
    if type(registry_directory_created) is not bool:
        raise OSError("Invalid Included File registry recovery directory state")
    previous_directory_identity = previous_registry_snapshot.directory_identity
    if registry_directory_created:
        if previous_directory_identity is not None:
            raise OSError("Invalid created Included File registry recovery directory")
    elif previous_directory_identity != registry_directory_identity:
        raise OSError("Included File registry recovery directory identity mismatch")
    managed_identities = (
        stage_container_identity,
        staged_root_snapshot.identity,
        staged_registry_identity,
        previous_root_snapshot.identity,
        previous_registry_snapshot.directory_identity,
        previous_registry_snapshot.file_identity,
        registry_directory_identity,
    )
    if any(
        identity is not None and identity[0] != project_identity[0]
        for identity in managed_identities
    ):
        raise OSError(
            "Included Files recovery state crosses the Godot project filesystem"
        )
    if (
        staged_root_snapshot.identity == previous_root_snapshot.identity
        and previous_root_snapshot.identity is not None
    ):
        raise OSError("Included Files staged and previous roots alias")
    if (
        staged_registry_identity == previous_registry_snapshot.file_identity
        and previous_registry_snapshot.file_identity is not None
    ):
        raise OSError("Included File staged and previous registries alias")
    if stage_container_identity in {
        project_identity,
        staged_root_snapshot.identity,
        registry_directory_identity,
    }:
        raise OSError("Included Files recovery directories alias")

    project_path = os.path.abspath(project_path)
    stage_container_path = os.path.join(project_path, stage_container_name)
    registry_directory_path = os.path.dirname(_included_registry_path(project_path))
    registry_backup_parent = (
        project_path
        if registry_backup_location == "project"
        else registry_directory_path
    )
    transaction = _IncludedOutputSetTransaction(
        project_identity=project_identity,
        stage_container_path=stage_container_path,
        stage_container_identity=stage_container_identity,
        staged_container_snapshot=staged_container_snapshot,
        staged_root_path=os.path.join(
            stage_container_path,
            _INCLUDED_FILES_ROOT_NAME,
        ),
        staged_root_snapshot=staged_root_snapshot,
        staged_registry_path=os.path.join(
            stage_container_path,
            "gml_included_file_registry.gd",
        ),
        staged_registry_identity=staged_registry_identity,
        staged_registry_mode=staged_registry_mode,
        staged_registry_content=staged_registry_content,
        previous_root_snapshot=previous_root_snapshot,
        previous_registry_snapshot=previous_registry_snapshot,
    )
    return _IncludedRecoveryJournal(
        format_version=format_version,
        transaction_id=transaction_id,
        transaction=transaction,
        root_backup_path=os.path.join(project_path, root_backup_name),
        registry_backup_path=os.path.join(
            registry_backup_parent,
            registry_backup_name,
        ),
        registry_directory_path=registry_directory_path,
        registry_directory_identity=registry_directory_identity,
        registry_directory_created=registry_directory_created,
    )


def _verify_included_bounded_record_size(
    record_stat: os.stat_result,
    path: str,
    maximum_bytes: int,
    record_label: str,
    size_qualifier: str,
) -> None:
    if record_stat.st_size < 0 or record_stat.st_size > maximum_bytes:
        raise OSError(
            f"{record_label} exceeds the {size_qualifier} size limit of "
            f"{maximum_bytes} bytes: {path}"
        )


def _read_included_recovery_record_payload(opened_file: BinaryIO) -> bytes:
    """Narrow test seam for a stat-bounded canonical recovery-record read."""

    return opened_file.read(_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES + 1)


def _read_included_lock_initialization_payload(
    opened_file: BinaryIO,
) -> bytes:
    """Read only enough bytes to distinguish the fixed lock payload."""

    return opened_file.read(len(_INCLUDED_FILES_LOCK_CONTENT) + 1)


def _read_opened_included_bounded_record_payload(
    opened_file: BinaryIO,
    expected_stat: os.stat_result,
    path: str,
    expected_device: int,
    expected_mount_id: int | None,
    maximum_bytes: int,
    payload_reader: Callable[[BinaryIO], bytes],
    record_label: str,
    size_qualifier: str,
) -> bytes:
    opened_stat = os.fstat(opened_file.fileno())
    if (
        not stat.S_ISREG(opened_stat.st_mode)
        or _included_path_handle_binding(opened_stat)
        != _included_path_handle_binding(expected_stat)
    ):
        raise OSError(
            f"{record_label} changed before reading: {path}"
        )
    _verify_included_bounded_record_size(
        opened_stat,
        path,
        maximum_bytes,
        record_label,
        size_qualifier,
    )
    _verify_included_mount_boundary(
        path,
        opened_stat,
        expected_device,
        expected_mount_id,
        opened_file.fileno(),
    )
    opened_state = _included_handle_state(opened_stat)
    content = payload_reader(opened_file)
    current_opened_stat = os.fstat(opened_file.fileno())
    if len(content) > maximum_bytes:
        raise OSError(
            f"{record_label} exceeds the {size_qualifier} size limit of "
            f"{maximum_bytes} bytes: {path}"
        )
    if (
        len(content) != opened_stat.st_size
        or _included_handle_state(current_opened_stat) != opened_state
    ):
        raise OSError(
            f"{record_label} changed while reading: {path}"
        )
    return content


def _included_bounded_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    maximum_bytes: int,
    payload_reader: Callable[[BinaryIO], bytes],
    record_label: str,
    size_qualifier: str,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    if _included_descriptor_paths_supported():
        try:
            parent_fd, name = _open_pinned_included_parent(path)
        except FileNotFoundError:
            return None
        try:
            parent_identity = _verify_included_directory_fd(
                parent_fd,
                project_identity,
                os.path.dirname(path),
            )
            parent_mount_id = _included_linux_mount_id_from_fd(parent_fd)
            path_stat = _included_entry_stat_at(parent_fd, name)
            if path_stat is None:
                return None
            if not stat.S_ISREG(path_stat.st_mode):
                raise OSError(
                    f"Refusing redirected or non-regular {record_label}: {path}"
                )
            path_identity = path_stat.st_dev, path_stat.st_ino
            if (
                allowed_identities is not None
                and path_identity not in allowed_identities
            ):
                raise OSError(
                    f"{record_label} changed before reading: {path}"
                )
            _verify_included_bounded_record_size(
                path_stat,
                path,
                maximum_bytes,
                record_label,
                size_qualifier,
            )
            expected_fingerprint = _included_path_fingerprint(path_stat)
            expected_ctime_ns = path_stat.st_ctime_ns
            file_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                with os.fdopen(file_descriptor, "rb") as opened_file:
                    file_descriptor = -1
                    content = _read_opened_included_bounded_record_payload(
                        opened_file,
                        path_stat,
                        path,
                        parent_identity[0],
                        parent_mount_id,
                        maximum_bytes,
                        payload_reader,
                        record_label,
                        size_qualifier,
                    )
            finally:
                if file_descriptor >= 0:
                    os.close(file_descriptor)
            current_stat = _included_entry_stat_at(parent_fd, name)
            if (
                current_stat is None
                or not stat.S_ISREG(current_stat.st_mode)
                or _included_path_fingerprint(current_stat)
                != expected_fingerprint
                or current_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(
                    f"{record_label} changed while reading: {path}"
                )
            return (
                (current_stat.st_dev, current_stat.st_ino),
                stat.S_IMODE(current_stat.st_mode),
                content,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if parent_identities[-1][1] != project_identity:
        raise OSError(f"{record_label} parent changed: {path}")
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected or non-regular {record_label}: {path}"
        )
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(
            f"{record_label} changed before reading: {path}"
        )
    _verify_included_bounded_record_size(
        path_stat,
        path,
        maximum_bytes,
        record_label,
        size_qualifier,
    )
    expected_fingerprint = _included_path_fingerprint(path_stat)
    expected_ctime_ns = path_stat.st_ctime_ns
    parent_mount_id = _included_directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    _verify_fallback_directory_ancestors(parent_identities)
    _before_included_fallback_regular_file_open(path)
    file_descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = _read_opened_included_bounded_record_payload(
                opened_file,
                path_stat,
                path,
                project_identity[0],
                parent_mount_id,
                maximum_bytes,
                payload_reader,
                record_label,
                size_qualifier,
            )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    current_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_path_fingerprint(current_stat) != expected_fingerprint
        or current_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(
            f"{record_label} changed while reading: {path}"
        )
    _verify_fallback_directory_ancestors(parent_identities)
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )


def _included_recovery_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    return _included_bounded_record_state(
        path,
        project_identity,
        maximum_bytes=_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        payload_reader=_read_included_recovery_record_payload,
        record_label="Included Files recovery record",
        size_qualifier="canonical",
        allowed_identities=allowed_identities,
    )


def _included_lock_initialization_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    return _included_bounded_record_state(
        path,
        project_identity,
        maximum_bytes=len(_INCLUDED_FILES_LOCK_CONTENT),
        payload_reader=_read_included_lock_initialization_payload,
        record_label="Included Files lock initialization record",
        size_qualifier="fixed-content",
        allowed_identities=allowed_identities,
    )


def _included_serialized_json_content(
    payload: Any,
    *,
    compact: bool,
) -> bytes:
    if compact:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    return (rendered + "\n").encode("utf-8")


def _included_recovery_record_content(payload: dict[str, Any]) -> bytes:
    format_version = payload.get("format_version")
    content = _included_serialized_json_content(
        payload,
        compact=(
            type(format_version) is int
            and format_version == _INCLUDED_FILES_RECOVERY_FORMAT_VERSION
        ),
    )
    if len(content) > _INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES:
        raise OSError(
            "Generated Included Files recovery record exceeds the canonical "
            "size limit of "
            f"{_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES} bytes"
        )
    return content


def _publish_included_recovery_record(
    project_path: str,
    project_identity: _PathIdentity,
    *,
    filename: str,
    temporary_prefix: str,
    payload: dict[str, Any],
    staged_phase: str | None = None,
) -> _PathIdentity:
    destination_path = os.path.join(project_path, filename)
    if (
        _included_recovery_record_state(
            destination_path,
            project_identity,
            allowed_identities=frozenset(),
        )
        is not None
    ):
        raise OSError(
            "Included Files recovery record already exists: " + destination_path
        )
    content = _included_recovery_record_content(payload)
    file_descriptor = -1
    temporary_path = ""
    for _attempt in range(100):
        temporary_name = temporary_prefix + secrets.token_hex(8) + ".tmp"
        candidate_path = os.path.join(project_path, temporary_name)
        try:
            file_descriptor = os.open(
                candidate_path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            continue
        temporary_path = candidate_path
        break
    if file_descriptor < 0 or not temporary_path:
        raise OSError("Could not allocate Included Files recovery staging record")
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            file_descriptor = -1
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _verify_included_project_identity(project_path, project_identity)
        temporary_state = _included_recovery_record_state(
            temporary_path,
            project_identity,
            allowed_identities=frozenset({temporary_identity}),
        )
        if (
            temporary_state is None
            or temporary_state[0] != temporary_identity
            or temporary_state[2] != content
        ):
            raise OSError("Included Files recovery staging record changed")
        # The crash-test phase names this temporary "durable". Persist its
        # project-directory entry as well as its already-fsynced contents
        # before exposing that boundary to recovery.
        _sync_included_directory(project_path, project_identity)
        if staged_phase is not None:
            _after_included_transaction_phase(staged_phase)
        _move_exact_included_file(
            temporary_path,
            destination_path,
            temporary_identity,
            source_parent_identity=project_identity,
            destination_parent_identity=project_identity,
        )
        temporary_pending = False
        _sync_included_directory(project_path, project_identity)
        published_state = _included_recovery_record_state(
            destination_path,
            project_identity,
            allowed_identities=frozenset({temporary_identity}),
        )
        if (
            published_state is None
            or published_state[0] != temporary_identity
            or published_state[2] != content
        ):
            raise OSError("Included Files recovery record changed after publication")
        return temporary_identity
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _remove_included_recovery_record(
                    temporary_path,
                    temporary_identity,
                    project_path,
                    project_identity,
                )
            except OSError:
                pass


def _read_included_recovery_record(
    path: str,
    project_identity: _PathIdentity,
) -> tuple[_PathIdentity, dict[str, Any]] | None:
    state = _included_recovery_record_state(path, project_identity)
    if state is None:
        return None
    identity, _mode, content = state
    try:
        decoded = content.decode("utf-8")
        payload = _included_recovery_dict(
            json.loads(decoded),
            "record",
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OSError(f"Invalid Included Files recovery record: {path}") from error
    if content != _included_recovery_record_content(payload):
        raise OSError(f"Non-canonical Included Files recovery record: {path}")
    return identity, payload


def _included_recovery_record_tombstone_path(path: str) -> str:
    return _included_cleanup_tombstone_path(
        path,
        "recovery-record",
        "record",
        os.path.basename(path),
        expect_directory=False,
    )


def _read_included_recovery_record_or_tombstone(
    path: str,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity, dict[str, Any]] | None:
    record = _read_included_recovery_record(path, project_identity)
    tombstone_path = _included_recovery_record_tombstone_path(path)
    tombstone_record = _read_included_recovery_record(
        tombstone_path,
        project_identity,
    )
    if record is not None and tombstone_record is not None:
        raise OSError(
            "Included Files recovery record and cleanup tombstone both exist: "
            + path
        )
    if record is not None:
        return path, record[0], record[1]
    if tombstone_record is not None:
        return tombstone_path, tombstone_record[0], tombstone_record[1]
    return None


def _included_commit_marker_and_journal_from_payload(
    project_path: str,
    payload: dict[str, Any],
    project_identity: _PathIdentity,
) -> tuple[_IncludedCommitMarker, _IncludedRecoveryJournal]:
    _included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "project_identity",
                "root_identity",
                "root_snapshot_sha256",
                "registry_directory_identity",
                "registry_identity",
                "registry_content_sha256",
                "recovery_journal",
                "recovery_journal_sha256",
            }
        ),
        "commit marker",
    )
    format_version = _included_recovery_int(
        payload.get("format_version"),
        "commit marker format version",
    )
    if (
        format_version
        not in {
            _INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
            _INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        }
        or payload.get("state") != "committed"
    ):
        raise OSError("Unsupported Included Files recovery commit marker")
    transaction_id = _included_recovery_token(
        payload.get("transaction_id"),
        32,
        "commit transaction id",
    )
    recorded_project_identity = _included_recovery_identity_for_format(
        payload.get("project_identity"),
        "commit project identity",
        format_version,
    )
    if recorded_project_identity != project_identity:
        raise OSError("Included Files commit marker belongs to another project")
    root_identity = _included_recovery_identity_for_format(
        payload.get("root_identity"),
        "commit root identity",
        format_version,
    )
    registry_directory_identity = _included_recovery_identity_for_format(
        payload.get("registry_directory_identity"),
        "commit registry directory identity",
        format_version,
    )
    registry_identity = _included_recovery_identity_for_format(
        payload.get("registry_identity"),
        "commit registry identity",
        format_version,
    )
    root_snapshot_sha256 = _included_recovery_sha256(
        payload.get("root_snapshot_sha256"),
        "commit root snapshot digest",
    )
    registry_content_sha256 = _included_recovery_sha256(
        payload.get("registry_content_sha256"),
        "commit registry content digest",
    )
    if (
        root_identity is None
        or registry_directory_identity is None
        or registry_identity is None
        or root_snapshot_sha256 is None
        or registry_content_sha256 is None
    ):
        raise OSError("Incomplete Included Files recovery commit marker")
    marker = _IncludedCommitMarker(
        format_version=format_version,
        transaction_id=transaction_id,
        project_identity=project_identity,
        root_identity=root_identity,
        root_snapshot_sha256=root_snapshot_sha256,
        registry_directory_identity=registry_directory_identity,
        registry_identity=registry_identity,
        registry_content_sha256=registry_content_sha256,
    )
    journal_payload = _included_recovery_dict(
        payload.get("recovery_journal"),
        "commit recovery journal",
    )
    journal_sha256 = _included_recovery_sha256(
        payload.get("recovery_journal_sha256"),
        "commit recovery journal digest",
    )
    if (
        journal_sha256 is None
        or hashlib.sha256(
            _included_recovery_record_content(journal_payload)
        ).hexdigest()
        != journal_sha256
    ):
        raise OSError("Included Files commit recovery journal digest mismatch")
    journal = _included_recovery_journal_from_payload(
        project_path,
        project_identity,
        journal_payload,
    )
    if journal.format_version != format_version:
        raise OSError("Included Files commit recovery journal format mismatch")
    if marker != _included_commit_marker_from_journal(journal):
        raise OSError("Included Files commit recovery journal disagrees with marker")
    return marker, journal


def _verify_included_commit_marker_generation(
    project_path: str,
    marker: _IncludedCommitMarker,
) -> None:
    root_snapshot = _capture_included_tree(
        os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME),
        expected_parent_identity=marker.project_identity,
    )
    if (
        root_snapshot.identity != marker.root_identity
        or _included_tree_snapshot_sha256(
            root_snapshot,
            marker.format_version,
        )
        != marker.root_snapshot_sha256
    ):
        raise OSError("Committed Included Files root generation is unavailable")
    registry_snapshot = _capture_included_registry(
        project_path,
        expected_project_identity=marker.project_identity,
        allowed_file_identities=frozenset({marker.registry_identity}),
    )
    if (
        registry_snapshot.directory_identity
        != marker.registry_directory_identity
        or registry_snapshot.file_identity != marker.registry_identity
        or registry_snapshot.content is None
        or hashlib.sha256(registry_snapshot.content).hexdigest()
        != marker.registry_content_sha256
    ):
        raise OSError("Committed Included File registry generation is unavailable")


def _verify_included_published_journal(
    project_path: str,
    project_identity: _PathIdentity,
    expected_journal: _IncludedRecoveryJournal,
    expected_identity: _PathIdentity | None,
) -> _PathIdentity:
    journal_path = os.path.join(project_path, _INCLUDED_FILES_JOURNAL_NAME)
    record = _read_included_recovery_record(journal_path, project_identity)
    if record is None:
        raise OSError("Included Files recovery journal disappeared")
    identity, payload = record
    if expected_identity is not None and identity != expected_identity:
        raise OSError("Included Files recovery journal identity changed")
    journal = _included_recovery_journal_from_payload(
        project_path,
        project_identity,
        payload,
    )
    if journal != expected_journal:
        raise OSError("Included Files recovery journal changed")
    return identity


def _verify_included_published_commit_marker(
    project_path: str,
    project_identity: _PathIdentity,
    expected_journal: _IncludedRecoveryJournal,
    expected_identity: _PathIdentity | None,
    *,
    verify_generation: bool = True,
) -> _PathIdentity:
    commit_path = os.path.join(project_path, _INCLUDED_FILES_COMMIT_NAME)
    record = _read_included_recovery_record(commit_path, project_identity)
    if record is None:
        raise OSError("Included Files commit marker disappeared")
    identity, payload = record
    if expected_identity is not None and identity != expected_identity:
        raise OSError("Included Files commit marker identity changed")
    marker, embedded_journal = _included_commit_marker_and_journal_from_payload(
        project_path,
        payload,
        project_identity,
    )
    if (
        marker != _included_commit_marker_from_journal(expected_journal)
        or embedded_journal != expected_journal
    ):
        raise OSError("Included Files commit marker changed")
    if verify_generation:
        _verify_included_commit_marker_generation(project_path, marker)
    return identity


def _included_cleanup_tombstone_path(
    path: str,
    transaction_id: str,
    role: str,
    relative_path: str,
    *,
    expect_directory: bool,
) -> str:
    digest = hashlib.sha256(
        (transaction_id + "\0" + role + "\0" + relative_path).encode("utf-8")
    ).hexdigest()
    suffix = "dir" if expect_directory else "file"
    return os.path.join(
        os.path.dirname(os.path.abspath(path)),
        _INCLUDED_FILES_CLEANUP_PREFIX + digest + "." + suffix,
    )


def _included_cleanup_file_state(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
) -> _IncludedCleanupFileState | None:
    if _included_descriptor_paths_supported():
        parent_fd, name = _open_pinned_included_parent(path)
        try:
            _verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            current_stat = _included_entry_stat_at(parent_fd, name)
            if current_stat is None:
                return None
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or (current_stat.st_dev, current_stat.st_ino)
                != expected_identity
            ):
                raise OSError(f"Included Files cleanup file changed: {path}")
            expected_fingerprint = _included_path_fingerprint(current_stat)
            expected_ctime_ns = current_stat.st_ctime_ns
            parent_mount_id = _included_linux_mount_id_from_fd(parent_fd)
            content_sha256 = _digest_included_regular_file_at(
                parent_fd,
                name,
                current_stat,
                path,
                expected_device=expected_parent_identity[0],
                expected_mount_id=parent_mount_id,
            )
            final_stat = _included_entry_stat_at(parent_fd, name)
            if (
                final_stat is None
                or not stat.S_ISREG(final_stat.st_mode)
                or (final_stat.st_dev, final_stat.st_ino) != expected_identity
                or _included_path_fingerprint(final_stat)
                != expected_fingerprint
                or final_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(f"Included Files cleanup file changed: {path}")
            return (
                stat.S_IMODE(final_stat.st_mode),
                content_sha256,
                expected_fingerprint,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if parent_identities[-1][1] != expected_parent_identity:
        raise OSError(f"Included Files cleanup parent changed: {path}")
    try:
        current_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files cleanup file changed: {path}")
    expected_fingerprint = _included_path_fingerprint(current_stat)
    expected_ctime_ns = current_stat.st_ctime_ns
    parent_mount_id = _included_directory_mount_id(
        parent_path,
        expected_parent_identity,
    )
    _verify_fallback_directory_ancestors(parent_identities)
    content_sha256 = _digest_included_regular_file(
        path,
        current_stat,
        expected_device=expected_parent_identity[0],
        expected_mount_id=parent_mount_id,
    )
    _verify_fallback_directory_ancestors(parent_identities)
    final_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, final_stat)
        or not stat.S_ISREG(final_stat.st_mode)
        or (final_stat.st_dev, final_stat.st_ino) != expected_identity
        or _included_path_fingerprint(final_stat) != expected_fingerprint
        or final_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(f"Included Files cleanup file changed: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    return (
        stat.S_IMODE(final_stat.st_mode),
        content_sha256,
        expected_fingerprint,
    )


def _included_cleanup_mode_matches(
    current: int,
    expected: int,
    *,
    allow_windows_writable: bool,
) -> bool:
    if current == expected:
        return True
    if not allow_windows_writable or os.name != "nt":
        return False
    write_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    return (
        not bool(expected & stat.S_IWRITE)
        and bool(current & stat.S_IWRITE)
        and current & ~write_mask == expected & ~write_mask
    )


def _included_cleanup_tombstone_fingerprint_matches(
    current: _PathFingerprint,
    expected: _PathFingerprint,
) -> bool:
    if current == expected:
        return True
    return (
        current[:2] == expected[:2]
        and current[3:] == expected[3:]
        and _included_cleanup_mode_matches(
            current[2],
            expected[2],
            allow_windows_writable=True,
        )
    )


def _included_cleanup_file_receipt_matches(
    state: _IncludedCleanupFileState,
    expected_content_sha256: str,
    expected_fingerprint: _PathFingerprint | None,
    expected_mode: int | None,
    *,
    allow_windows_writable: bool,
) -> bool:
    return (
        state[1] == expected_content_sha256
        and (
            expected_fingerprint is None
            or (
                _included_cleanup_tombstone_fingerprint_matches(
                    state[2],
                    expected_fingerprint,
                )
                if allow_windows_writable
                else state[2] == expected_fingerprint
            )
        )
        and (
            expected_mode is None
            or _included_cleanup_mode_matches(
                state[0],
                expected_mode,
                allow_windows_writable=allow_windows_writable,
            )
        )
    )


def _included_cleanup_directory_state(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
) -> bool | None:
    parent_path = os.path.dirname(os.path.abspath(path))
    current_parent_identity = _included_directory_identity(parent_path)
    if current_parent_identity != expected_parent_identity:
        raise OSError(f"Included Files cleanup parent changed: {parent_path}")
    current_identity = _included_directory_identity(path)
    if current_identity is None:
        return None
    if current_identity != expected_identity:
        raise OSError(f"Included Files cleanup directory changed: {path}")
    path_stat = os.lstat(path)
    if (
        _included_output_path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
    ):
        raise OSError(f"Included Files cleanup directory changed: {path}")
    parent_mount_id = _included_directory_mount_id(
        parent_path,
        expected_parent_identity,
    )
    _verify_included_mount_boundary_path(
        path,
        path_stat,
        expected_parent_identity[0],
        parent_mount_id,
        expect_directory=True,
    )
    if (
        _included_directory_identity(path) != expected_identity
        or _included_directory_identity(parent_path) != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup directory changed: {path}")
    return True


def _remove_included_cleanup_tombstone(
    path: str,
    expected_identity: _PathIdentity,
    parent_path: str,
    parent_identity: _PathIdentity,
    *,
    expect_directory: bool,
) -> None:
    # The fallback removers must observe the original Windows READONLY state
    # themselves so they can restore that attribute after a sharing failure.
    if _included_descriptor_paths_supported():
        parent_fd, name = _open_pinned_included_parent(path)
        try:
            _verify_included_directory_fd(
                parent_fd,
                parent_identity,
                parent_path,
            )
            if expect_directory:
                _rmdir_exact_quarantined_entry_at(
                    parent_fd,
                    name,
                    expected_identity,
                    path,
                )
            else:
                _unlink_exact_quarantined_entry_at(
                    parent_fd,
                    name,
                    expected_identity,
                    path,
                )
        finally:
            os.close(parent_fd)
    elif expect_directory:
        _rmdir_exact_quarantined_entry_fallback(path, expected_identity)
    else:
        _unlink_exact_quarantined_entry_fallback(path, expected_identity)
    _sync_included_directory(parent_path, parent_identity)


def _cleanup_recorded_included_file(
    path: str,
    expected_identity: _PathIdentity,
    expected_content_sha256: str,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
    relative_path: str,
    *,
    expected_fingerprint: _PathFingerprint | None = None,
    expected_mode: int | None = None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    parent_path = os.path.dirname(os.path.abspath(path))
    tombstone_path = _included_cleanup_tombstone_path(
        path,
        transaction_id,
        role,
        relative_path,
        expect_directory=False,
    )
    try:
        source_state = _included_cleanup_file_state(
            path,
            expected_identity,
            expected_parent_identity,
        )
    except OSError:
        source_state = None
        if os.path.lexists(path):
            warnings.append(
                f"unknown Included Files cleanup entry was preserved: {path}"
            )
    try:
        tombstone_state = _included_cleanup_file_state(
            tombstone_path,
            expected_identity,
            expected_parent_identity,
        )
    except OSError:
        tombstone_state = None
        if os.path.lexists(tombstone_path):
            warnings.append(
                "unknown Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)

    if source_state is not None and tombstone_state is not None:
        warnings.append(
            f"ambiguous duplicate Included Files cleanup entry was preserved: {path}"
        )
        return tuple(warnings)
    if tombstone_state is not None:
        if not _included_cleanup_file_receipt_matches(
            tombstone_state,
            expected_content_sha256,
            expected_fingerprint,
            expected_mode,
            allow_windows_writable=True,
        ):
            warnings.append(
                "changed Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)
        _remove_included_cleanup_tombstone(
            tombstone_path,
            expected_identity,
            parent_path,
            expected_parent_identity,
            expect_directory=False,
        )
        _after_included_transaction_phase(
            f"cleanup:{role}:{relative_path}:removed"
        )
        return tuple(warnings)
    if source_state is None:
        return tuple(warnings)
    if not _included_cleanup_file_receipt_matches(
        source_state,
        expected_content_sha256,
        expected_fingerprint,
        expected_mode,
        allow_windows_writable=False,
    ):
        warnings.append(f"changed Included Files cleanup entry was preserved: {path}")
        return tuple(warnings)

    _move_exact_included_file(
        path,
        tombstone_path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
    )
    _sync_included_directory(parent_path, expected_parent_identity)
    _after_included_transaction_phase(
        f"cleanup:{role}:{relative_path}:quarantined"
    )
    tombstone_state = _included_cleanup_file_state(
        tombstone_path,
        expected_identity,
        expected_parent_identity,
    )
    if tombstone_state is None or not _included_cleanup_file_receipt_matches(
        tombstone_state,
        expected_content_sha256,
        expected_fingerprint,
        expected_mode,
        allow_windows_writable=True,
    ):
        raise OSError(
            "Included Files cleanup tombstone changed after publication: "
            + tombstone_path
        )
    _remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        expected_parent_identity,
        expect_directory=False,
    )
    _after_included_transaction_phase(f"cleanup:{role}:{relative_path}:removed")
    return tuple(warnings)


def _cleanup_recorded_included_directory(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
    relative_path: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    parent_path = os.path.dirname(os.path.abspath(path))
    tombstone_path = _included_cleanup_tombstone_path(
        path,
        transaction_id,
        role,
        relative_path,
        expect_directory=True,
    )
    try:
        source_state = _included_cleanup_directory_state(
            path,
            expected_identity,
            expected_parent_identity,
        )
    except OSError:
        source_state = None
        if os.path.lexists(path):
            warnings.append(
                f"unknown Included Files cleanup directory was preserved: {path}"
            )
    try:
        tombstone_state = _included_cleanup_directory_state(
            tombstone_path,
            expected_identity,
            expected_parent_identity,
        )
    except OSError:
        tombstone_state = None
        if os.path.lexists(tombstone_path):
            warnings.append(
                "unknown Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)

    if source_state is not None and tombstone_state is not None:
        warnings.append(
            f"ambiguous duplicate Included Files cleanup directory was preserved: {path}"
        )
        return tuple(warnings)
    if tombstone_state is not None:
        if os.listdir(tombstone_path):
            warnings.append(
                "non-empty Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)
        _remove_included_cleanup_tombstone(
            tombstone_path,
            expected_identity,
            parent_path,
            expected_parent_identity,
            expect_directory=True,
        )
        _after_included_transaction_phase(
            f"cleanup:{role}:{relative_path}:removed"
        )
        return tuple(warnings)
    if source_state is None:
        return tuple(warnings)
    if os.listdir(path):
        warnings.append(
            f"non-empty Included Files cleanup directory was preserved: {path}"
        )
        return tuple(warnings)
    if (
        _included_directory_identity(path) != expected_identity
        or _included_directory_identity(parent_path) != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup directory changed: {path}")
    _move_exact_included_directory(
        path,
        tombstone_path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
    )
    _sync_included_directory(parent_path, expected_parent_identity)
    _after_included_transaction_phase(
        f"cleanup:{role}:{relative_path}:quarantined"
    )
    if os.listdir(tombstone_path):
        warnings.append(
            "non-empty Included Files cleanup tombstone was preserved: "
            + tombstone_path
        )
        return tuple(warnings)
    _remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        expected_parent_identity,
        expect_directory=True,
    )
    _after_included_transaction_phase(f"cleanup:{role}:{relative_path}:removed")
    return tuple(warnings)


def _cleanup_recorded_included_tree(
    path: str,
    snapshot: _IncludedTreeSnapshot,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
) -> tuple[str, ...]:
    recorded_entry_paths = {
        entry.relative_path: _included_recovery_tree_entry_path(
            path,
            entry.relative_path,
        )
        for entry in snapshot.entries
    }
    if len(recorded_entry_paths) != len(snapshot.entries):
        raise OSError("Duplicate Included Files cleanup manifest path")
    root_identity = snapshot.identity
    if root_identity is None:
        if os.path.lexists(path):
            return (f"unknown Included Files cleanup tree was preserved: {path}",)
        return ()
    if (
        root_identity[0] != expected_parent_identity[0]
        or any(
            entry.fingerprint[0] != root_identity[0]
            for entry in snapshot.entries
        )
    ):
        return (
            f"cross-mount Included Files cleanup tree was preserved: {path}",
        )
    directory_identities: dict[str, _PathIdentity] = {"": root_identity}
    for entry in snapshot.entries:
        if entry.kind == "directory":
            directory_identities[entry.relative_path] = entry.fingerprint[:2]

    try:
        root_state = _included_cleanup_directory_state(
            path,
            root_identity,
            expected_parent_identity,
        )
    except OSError:
        return (f"unknown or mounted Included Files cleanup tree was preserved: {path}",)
    if root_state is None:
        return _cleanup_recorded_included_directory(
            path,
            root_identity,
            expected_parent_identity,
            transaction_id,
            role,
            ".",
        )

    absent_directories: set[str] = set()
    for entry in sorted(
        (candidate for candidate in snapshot.entries if candidate.kind == "directory"),
        key=lambda candidate: (
            candidate.relative_path.count("/"),
            candidate.relative_path,
        ),
    ):
        entry_path = recorded_entry_paths[entry.relative_path]
        parent_relative = posixpath.dirname(entry.relative_path)
        if parent_relative in absent_directories:
            absent_directories.add(entry.relative_path)
            continue
        try:
            entry_state = _included_cleanup_directory_state(
                entry_path,
                entry.fingerprint[:2],
                directory_identities[parent_relative],
            )
        except OSError:
            return (
                "unknown or mounted Included Files cleanup directory was "
                f"preserved: {entry_path}",
            )
        if entry_state is None:
            absent_directories.add(entry.relative_path)

    warnings: list[str] = []
    for entry in sorted(
        (candidate for candidate in snapshot.entries if candidate.kind == "file"),
        key=lambda candidate: candidate.relative_path,
        reverse=True,
    ):
        parent_relative = posixpath.dirname(entry.relative_path)
        parent_identity = directory_identities[parent_relative]
        if entry.content_sha256 is None:
            warnings.append(
                "Included Files cleanup manifest omitted a file digest: "
                + entry.relative_path
            )
            continue
        warnings.extend(
            _cleanup_recorded_included_file(
                recorded_entry_paths[entry.relative_path],
                entry.fingerprint[:2],
                entry.content_sha256,
                parent_identity,
                transaction_id,
                role,
                entry.relative_path,
                expected_fingerprint=entry.fingerprint,
            )
        )

    directories = sorted(
        (candidate for candidate in snapshot.entries if candidate.kind == "directory"),
        key=lambda candidate: (
            candidate.relative_path.count("/"),
            candidate.relative_path,
        ),
        reverse=True,
    )
    for entry in directories:
        parent_relative = posixpath.dirname(entry.relative_path)
        warnings.extend(
            _cleanup_recorded_included_directory(
                recorded_entry_paths[entry.relative_path],
                entry.fingerprint[:2],
                directory_identities[parent_relative],
                transaction_id,
                role,
                entry.relative_path,
            )
        )
    warnings.extend(
        _cleanup_recorded_included_directory(
            path,
            root_identity,
            expected_parent_identity,
            transaction_id,
            role,
            ".",
        )
    )
    return tuple(warnings)


def _remove_included_recovery_record(
    path: str,
    identity: _PathIdentity,
    project_path: str,
    project_identity: _PathIdentity,
) -> None:
    current_state = _included_recovery_record_state(
        path,
        project_identity,
        allowed_identities=frozenset({identity}),
    )
    if current_state is None:
        return
    if os.path.basename(path).startswith(_INCLUDED_FILES_CLEANUP_PREFIX):
        _remove_included_cleanup_tombstone(
            path,
            identity,
            project_path,
            project_identity,
            expect_directory=False,
        )
        _after_included_transaction_phase(
            f"cleanup:record:{os.path.basename(path)}:removed"
        )
        return
    basename = os.path.basename(path)
    content_sha256 = hashlib.sha256(current_state[2]).hexdigest()
    if basename in {
        _INCLUDED_FILES_JOURNAL_NAME,
        _INCLUDED_FILES_COMMIT_NAME,
    }:
        cleanup_transaction_id = "recovery-record"
        cleanup_role = "record"
        cleanup_relative_path = basename
    elif basename.startswith(_INCLUDED_FILES_JOURNAL_TEMP_PREFIX):
        cleanup_transaction_id = content_sha256[:32]
        cleanup_role = "journal-temporary-record"
        cleanup_relative_path = "journal"
    elif basename.startswith(_INCLUDED_FILES_COMMIT_TEMP_PREFIX):
        cleanup_transaction_id = content_sha256[:32]
        cleanup_role = "commit-temporary-record"
        cleanup_relative_path = "commit"
    else:
        cleanup_transaction_id = "recovery-record"
        cleanup_role = "record"
        cleanup_relative_path = basename
    warnings = _cleanup_recorded_included_file(
        path,
        identity,
        content_sha256,
        project_identity,
        cleanup_transaction_id,
        cleanup_role,
        cleanup_relative_path,
    )
    if warnings:
        raise OSError("; ".join(warnings))


def _included_stage_marker_matches(
    payload: dict[str, Any],
    project_identity: _PathIdentity,
    stage_identity: _PathIdentity,
) -> bool:
    _included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "project_identity",
                "stage_identity",
            }
        ),
        "stage marker",
    )
    return (
        _included_recovery_int(
            payload.get("format_version"),
            "stage marker format version",
        )
        == _INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION
        and payload.get("state") == "staging"
        and _included_recovery_identity(
            payload.get("project_identity"),
            "stage project identity",
        )
        == project_identity
        and _included_recovery_identity(
            payload.get("stage_identity"),
            "stage identity",
        )
        == stage_identity
    )


def _cleanup_orphan_included_recovery_state(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[int, tuple[str, ...]]:
    """Remove exact self-identifying orphans and preserve ambiguous state."""

    _verify_included_project_identity(project_path, project_identity)
    names = sorted(os.listdir(project_path))
    _verify_included_project_identity(project_path, project_identity)
    cleaned = 0
    warnings: list[str] = []
    for name in names:
        if name.startswith(_INCLUDED_FILES_STAGE_PREFIX) and name.endswith(
            ".stage"
        ):
            stage_path = os.path.join(project_path, name)
            try:
                _included_recovery_managed_name(
                    name,
                    prefix=_INCLUDED_FILES_STAGE_PREFIX,
                    suffix=".stage",
                    label="orphan stage",
                )
                stage_identity = _included_directory_identity(stage_path)
            except OSError:
                warnings.append(
                    "ambiguous entry at a reserved Included Files staging path "
                    f"was preserved: {stage_path}"
                )
                continue
            if stage_identity is None:
                continue
            marker_path = os.path.join(
                stage_path,
                _INCLUDED_FILES_STAGE_MARKER_NAME,
            )
            try:
                marker_record = _read_included_recovery_record(
                    marker_path,
                    stage_identity,
                )
                stage_names = sorted(os.listdir(stage_path))
                if _included_directory_identity(stage_path) != stage_identity:
                    raise OSError("Included Files orphan stage changed")
                marker_matches = (
                    marker_record is not None
                    and _included_stage_marker_matches(
                        marker_record[1],
                        project_identity,
                        stage_identity,
                    )
                )
            except OSError:
                marker_record = None
                marker_matches = False
                stage_names = []
            if (
                not marker_matches
                or marker_record is None
                or stage_names != [_INCLUDED_FILES_STAGE_MARKER_NAME]
            ):
                warnings.append(
                    "ambiguous Included Files staging directory was preserved: "
                    + stage_path
                )
                continue
            orphan_snapshot = _capture_included_tree(
                stage_path,
                expected_parent_identity=project_identity,
            )
            orphan_warnings = _cleanup_recorded_included_tree(
                stage_path,
                orphan_snapshot,
                project_identity,
                hashlib.sha256(
                    _included_recovery_record_content(marker_record[1])
                ).hexdigest()[:32],
                "orphan-stage",
            )
            if orphan_warnings:
                warnings.extend(orphan_warnings)
            else:
                cleaned += 1

    names = sorted(os.listdir(project_path))
    _verify_included_project_identity(project_path, project_identity)
    for name in names:
        record_kind: str | None = None
        if name.startswith(_INCLUDED_FILES_JOURNAL_TEMP_PREFIX) and name.endswith(
            ".tmp"
        ):
            record_kind = "journal"
        elif name.startswith(_INCLUDED_FILES_COMMIT_TEMP_PREFIX) and name.endswith(
            ".tmp"
        ):
            record_kind = "commit"
        if record_kind is None:
            continue
        record_path = os.path.join(project_path, name)
        try:
            _included_recovery_managed_name(
                name,
                prefix=(
                    _INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    if record_kind == "journal"
                    else _INCLUDED_FILES_COMMIT_TEMP_PREFIX
                ),
                suffix=".tmp",
                label=record_kind + " temporary record",
            )
            record = _read_included_recovery_record(
                record_path,
                project_identity,
            )
        except OSError:
            warnings.append(
                "ambiguous Included Files recovery temporary record was "
                f"preserved: {record_path}"
            )
            continue
        if record is None:
            continue
        record_identity, payload = record
        try:
            if record_kind == "journal":
                _included_recovery_journal_from_payload(
                    project_path,
                    project_identity,
                    payload,
                )
            else:
                _included_commit_marker_and_journal_from_payload(
                    project_path,
                    payload,
                    project_identity,
                )
        except OSError:
            warnings.append(
                "ambiguous Included Files recovery temporary record was "
                f"preserved: {record_path}"
            )
            continue
        if record_kind == "journal":
            warnings.append(
                "unpromoted Included Files journal temporary was preserved: "
                + record_path
            )
            continue
        _remove_included_recovery_record(
            record_path,
            record_identity,
            project_path,
            project_identity,
        )
        cleaned += 1

    names = sorted(os.listdir(project_path))
    _verify_included_project_identity(project_path, project_identity)
    for name in names:
        if not (
            name.startswith(_INCLUDED_FILES_CLEANUP_PREFIX)
            and name.endswith(".file")
        ):
            continue
        record_path = os.path.join(project_path, name)
        try:
            record = _read_included_recovery_record(
                record_path,
                project_identity,
            )
            if record is None:
                continue
            record_identity, payload = record
            content_sha256 = hashlib.sha256(
                _included_recovery_record_content(payload)
            ).hexdigest()
            state = payload.get("state")
            if state == "prepared":
                _included_recovery_journal_from_payload(
                    project_path,
                    project_identity,
                    payload,
                )
                role = "journal-temporary-record"
                relative_path = "journal"
            elif state == "committed":
                _included_commit_marker_and_journal_from_payload(
                    project_path,
                    payload,
                    project_identity,
                )
                role = "commit-temporary-record"
                relative_path = "commit"
            else:
                raise OSError("Unknown Included Files recovery tombstone state")
            expected_path = _included_cleanup_tombstone_path(
                os.path.join(project_path, "temporary-record"),
                content_sha256[:32],
                role,
                relative_path,
                expect_directory=False,
            )
            if os.path.normcase(record_path) != os.path.normcase(expected_path):
                raise OSError("Included Files recovery tombstone name mismatch")
        except OSError:
            warnings.append(
                "ambiguous Included Files cleanup tombstone was preserved: "
                + record_path
            )
            continue
        _remove_included_recovery_record(
            record_path,
            record_identity,
            project_path,
            project_identity,
        )
        cleaned += 1
    return cleaned, tuple(warnings)


def _rollback_included_output_set(
    transaction: _IncludedOutputSetTransaction,
    *,
    root_backup_path: str,
    registry_backup_path: str,
    registry_directory_path: str,
    registry_directory_identity: _PathIdentity | None,
    registry_directory_created: bool,
) -> tuple[Exception, ...]:
    errors: list[Exception] = []
    final_root_path = os.path.join(
        os.path.dirname(transaction.stage_container_path),
        _INCLUDED_FILES_ROOT_NAME,
    )
    final_registry_path = _included_registry_path(
        os.path.dirname(transaction.stage_container_path)
    )

    try:
        project_path = os.path.dirname(transaction.stage_container_path)
        _verify_included_project_identity(
            project_path,
            transaction.project_identity,
        )
        previous_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
        )
        expected_registry_parent_identity = (
            registry_directory_identity
            if registry_directory_identity is not None
            else previous_registry_directory_identity
        )
        current_registry_directory_identity = _included_directory_identity(
            registry_directory_path
        )
        if current_registry_directory_identity is None:
            if not (
                registry_directory_created
                and previous_registry_directory_identity is None
            ) and expected_registry_parent_identity is not None:
                raise OSError(
                    "Included File registry directory disappeared during rollback"
                )
            final_registry_parent_identity = None
        elif (
            expected_registry_parent_identity is None
            or current_registry_directory_identity
            != expected_registry_parent_identity
        ):
            raise OSError(
                "Included File registry directory changed during rollback"
            )
        else:
            final_registry_parent_identity = current_registry_directory_identity
        previous_registry_identity = (
            transaction.previous_registry_snapshot.file_identity
        )
        allowed_current_registry_identities = {
            transaction.staged_registry_identity
        }
        if previous_registry_identity is not None:
            allowed_current_registry_identities.add(previous_registry_identity)

        if final_registry_parent_identity is None:
            if _included_directory_identity(registry_directory_path) is not None:
                raise OSError(
                    "Refusing to inspect an Included File registry directory "
                    "that appeared during rollback"
                )
            current_registry_state = None
        else:
            current_registry_state = _included_regular_file_state(
                final_registry_path,
                expected_parent_identity=final_registry_parent_identity,
                allowed_identities=frozenset(
                    allowed_current_registry_identities
                ),
            )
        current_registry_identity = (
            current_registry_state[0]
            if current_registry_state is not None
            else None
        )
        if previous_registry_identity is None:
            backup_registry_identity = None
        elif current_registry_identity == previous_registry_identity:
            # The previous public registry is already intact. An entry at the
            # reserved backup path is therefore not ours and must be preserved
            # without preventing rollback of the rest of the transaction.
            backup_registry_identity = None
        else:
            if previous_registry_directory_identity is None:
                raise AssertionError(
                    "A previous Included File registry requires its directory"
                )
            backup_registry_state = _included_regular_file_state(
                registry_backup_path,
                expected_parent_identity=(
                    previous_registry_directory_identity
                ),
                allowed_identities=frozenset({previous_registry_identity}),
            )
            backup_registry_identity = (
                backup_registry_state[0]
                if backup_registry_state is not None
                else None
            )
        if current_registry_identity == transaction.staged_registry_identity:
            if final_registry_parent_identity is None:
                raise AssertionError(
                    "A published Included File registry requires its directory"
                )
            _move_exact_included_file(
                final_registry_path,
                transaction.staged_registry_path,
                transaction.staged_registry_identity,
                source_parent_identity=final_registry_parent_identity,
                destination_parent_identity=transaction.stage_container_identity,
            )
            current_registry_identity = None
        elif current_registry_identity not in {None, previous_registry_identity}:
            raise OSError("Refusing to overwrite an unknown Included File registry during rollback")

        if previous_registry_identity is None:
            if backup_registry_identity is not None or current_registry_identity is not None:
                raise OSError("Could not restore the previously absent Included File registry")
        elif current_registry_identity == previous_registry_identity:
            pass
        elif backup_registry_identity == previous_registry_identity:
            if (
                previous_registry_directory_identity is None
                or final_registry_parent_identity is None
            ):
                raise AssertionError(
                    "A previous Included File registry requires its directory"
                )
            _move_exact_included_file(
                registry_backup_path,
                final_registry_path,
                previous_registry_identity,
                source_parent_identity=(
                    previous_registry_directory_identity
                ),
                destination_parent_identity=final_registry_parent_identity,
            )
        else:
            raise OSError("Previous Included File registry backup is unavailable")
    except Exception as error:
        errors.append(error)

    try:
        current_root_identity = _included_directory_identity(final_root_path)
        previous_root_identity = transaction.previous_root_snapshot.identity
        backup_root_identity = (
            None
            if current_root_identity == previous_root_identity
            else _included_directory_identity(root_backup_path)
        )
        staged_root_identity = transaction.staged_root_snapshot.identity
        if staged_root_identity is None:
            raise AssertionError("A staged Included Files root must be present")
        if current_root_identity == staged_root_identity:
            _move_exact_included_directory(
                final_root_path,
                transaction.staged_root_path,
                staged_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.stage_container_identity,
            )
            current_root_identity = None
        elif current_root_identity not in {None, previous_root_identity}:
            raise OSError("Refusing to overwrite an unknown Included Files root during rollback")

        if previous_root_identity is None:
            if backup_root_identity is not None or current_root_identity is not None:
                raise OSError("Could not restore the previously absent Included Files root")
        elif current_root_identity == previous_root_identity:
            pass
        elif backup_root_identity == previous_root_identity:
            _move_exact_included_directory(
                root_backup_path,
                final_root_path,
                previous_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.project_identity,
            )
        else:
            raise OSError("Previous Included Files root backup is unavailable")
    except Exception as error:
        errors.append(error)

    if registry_directory_created and registry_directory_identity is not None:
        try:
            current_registry_directory_identity = _included_directory_identity(
                registry_directory_path
            )
            if current_registry_directory_identity is None:
                pass
            elif current_registry_directory_identity == registry_directory_identity:
                _cleanup_recorded_included_directory(
                    registry_directory_path,
                    registry_directory_identity,
                    transaction.project_identity,
                    (
                        f"{transaction.project_identity[0]:x}"
                        f"{transaction.project_identity[1]:x}"
                    ),
                    "rollback-registry-directory",
                    "gm2godot",
                )
            else:
                raise OSError(
                    "Included File registry directory changed during rollback"
                )
        except Exception as error:
            errors.append(error)
    return tuple(errors)


def _cleanup_committed_included_output_set(
    journal: _IncludedRecoveryJournal,
    *,
    verify_content: bool = True,
) -> tuple[tuple[Exception, ...], tuple[str, ...]]:
    errors: list[Exception] = []
    warnings: list[str] = []
    transaction = journal.transaction
    project_path = os.path.dirname(transaction.stage_container_path)
    final_root_path = os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME)
    final_registry_path = _included_registry_path(project_path)

    try:
        _verify_included_project_identity(project_path, transaction.project_identity)
        if verify_content:
            _verify_included_tree_snapshot(
                final_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.project_identity,
            )
        else:
            _verify_included_tree_snapshot_metadata(
                final_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.project_identity,
            )
        if (
            _included_directory_identity(journal.registry_directory_path)
            != journal.registry_directory_identity
        ):
            raise OSError(
                "Included File registry directory changed during committed recovery"
            )
        registry_state = _included_regular_file_state(
            final_registry_path,
            expected_parent_identity=journal.registry_directory_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            registry_state is None
            or registry_state[0] != transaction.staged_registry_identity
            or registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError(
                "Committed Included File registry generation is unavailable"
            )
    except Exception as error:
        return (error,), ()

    try:
        warnings.extend(
            _cleanup_recorded_included_tree(
                journal.root_backup_path,
                transaction.previous_root_snapshot,
                transaction.project_identity,
                journal.transaction_id,
                "root-backup",
            )
        )
    except Exception as error:
        errors.append(error)

    previous_registry_identity = (
        transaction.previous_registry_snapshot.file_identity
    )
    try:
        if previous_registry_identity is None:
            if os.path.lexists(journal.registry_backup_path):
                warnings.append(
                    "Unknown replacement at the Included File registry backup "
                    f"path was preserved: {journal.registry_backup_path}"
                )
        else:
            previous_registry_content = (
                transaction.previous_registry_snapshot.content
            )
            if previous_registry_content is None:
                raise AssertionError(
                    "A previous Included File registry requires recorded content"
                )
            warnings.extend(
                _cleanup_recorded_included_file(
                    journal.registry_backup_path,
                    previous_registry_identity,
                    hashlib.sha256(previous_registry_content).hexdigest(),
                    journal.registry_directory_identity,
                    journal.transaction_id,
                    "registry-backup",
                    os.path.basename(journal.registry_backup_path),
                    expected_mode=(
                        transaction.previous_registry_snapshot.file_mode
                    ),
                )
            )
    except Exception as error:
        errors.append(error)

    try:
        warnings.extend(
            _cleanup_recorded_included_tree(
                transaction.stage_container_path,
                transaction.staged_container_snapshot,
                transaction.project_identity,
                journal.transaction_id,
                "stage",
            )
        )
    except Exception as error:
        errors.append(error)
    return tuple(errors), tuple(warnings)


def _promote_included_journal_temporary(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[bool, tuple[str, ...]]:
    journal_path = os.path.join(project_path, _INCLUDED_FILES_JOURNAL_NAME)
    if os.path.lexists(journal_path):
        return False, ()
    candidates: list[tuple[str, _PathIdentity]] = []
    warnings: list[str] = []
    _verify_included_project_identity(project_path, project_identity)
    for name in sorted(os.listdir(project_path)):
        if not (
            name.startswith(_INCLUDED_FILES_JOURNAL_TEMP_PREFIX)
            and name.endswith(".tmp")
        ):
            continue
        candidate_path = os.path.join(project_path, name)
        try:
            _included_recovery_managed_name(
                name,
                prefix=_INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
                suffix=".tmp",
                label="journal temporary record",
            )
            record = _read_included_recovery_record(
                candidate_path,
                project_identity,
            )
            if record is None:
                continue
            candidate_identity, payload = record
            journal = _included_recovery_journal_from_payload(
                project_path,
                project_identity,
                payload,
            )
            transaction = journal.transaction
            _verify_included_tree_snapshot(
                transaction.stage_container_path,
                transaction.staged_container_snapshot,
                expected_parent_identity=project_identity,
            )
            _verify_included_tree_snapshot(
                os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME),
                transaction.previous_root_snapshot,
                expected_parent_identity=project_identity,
            )
            if journal.registry_directory_created:
                if transaction.previous_registry_snapshot != (
                    _IncludedRegistrySnapshot(
                        directory_identity=None,
                        file_identity=None,
                        file_mode=None,
                        content=None,
                    )
                ):
                    raise OSError(
                        "Created Included File registry directory disagrees "
                        "with the previous generation"
                    )
                _verify_included_registry_snapshot(
                    project_path,
                    _IncludedRegistrySnapshot(
                        directory_identity=journal.registry_directory_identity,
                        file_identity=None,
                        file_mode=None,
                        content=None,
                    ),
                    expected_project_identity=project_identity,
                )
            else:
                _verify_included_registry_snapshot(
                    project_path,
                    transaction.previous_registry_snapshot,
                    expected_project_identity=project_identity,
                )
        except OSError:
            warnings.append(
                "ambiguous Included Files journal temporary was preserved: "
                + candidate_path
            )
            continue
        candidates.append((candidate_path, candidate_identity))
    if len(candidates) > 1:
        raise OSError(
            "Multiple valid Included Files journal temporaries require manual "
            "inspection"
        )
    if not candidates:
        return False, tuple(warnings)
    candidate_path, candidate_identity = candidates[0]
    _move_exact_included_file(
        candidate_path,
        journal_path,
        candidate_identity,
        source_parent_identity=project_identity,
        destination_parent_identity=project_identity,
    )
    _sync_included_directory(project_path, project_identity)
    _after_included_transaction_phase("recovery-journal-promoted")
    return True, tuple(warnings)


def _recover_included_output_set(
    project_path: str,
    project_identity: _PathIdentity,
) -> str | None:
    journal_path = os.path.join(project_path, _INCLUDED_FILES_JOURNAL_NAME)
    commit_path = os.path.join(project_path, _INCLUDED_FILES_COMMIT_NAME)
    journal_promoted, promotion_warnings = _promote_included_journal_temporary(
        project_path,
        project_identity,
    )
    journal_record = _read_included_recovery_record_or_tombstone(
        journal_path,
        project_identity,
    )
    commit_record = _read_included_recovery_record_or_tombstone(
        commit_path,
        project_identity,
    )
    if journal_record is None:
        messages: list[str] = list(promotion_warnings)
        if commit_record is not None:
            commit_record_path, commit_identity, commit_payload = commit_record
            marker, embedded_journal = (
                _included_commit_marker_and_journal_from_payload(
                    project_path,
                    commit_payload,
                    project_identity,
                )
            )
            _verify_included_commit_marker_generation(project_path, marker)
            cleanup_errors, cleanup_warnings = (
                _cleanup_committed_included_output_set(embedded_journal)
            )
            if cleanup_errors:
                error = OSError(
                    "Committed Included Files marker-only recovery could not "
                    "finish cleanup"
                )
                for cleanup_error in cleanup_errors:
                    error.add_note(str(cleanup_error))
                raise error
            _remove_included_recovery_record(
                commit_record_path,
                commit_identity,
                project_path,
                project_identity,
            )
            messages.append(
                "finalized an already committed Included Files generation"
            )
            messages.extend(cleanup_warnings)
        orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
            project_path,
            project_identity,
        )
        if orphan_count:
            messages.append(
                f"removed {orphan_count} self-identified orphan transaction entries"
            )
        messages.extend(orphan_warnings)
        return "; ".join(messages) if messages else None

    journal_record_path, journal_identity, journal_payload = journal_record
    journal = _included_recovery_journal_from_payload(
        project_path,
        project_identity,
        journal_payload,
    )
    commit_identity: _PathIdentity | None = None
    commit_record_path = commit_path
    if commit_record is not None:
        commit_record_path, commit_identity, commit_payload = commit_record
        marker, embedded_journal = (
            _included_commit_marker_and_journal_from_payload(
                project_path,
                commit_payload,
                project_identity,
            )
        )
        if (
            marker != _included_commit_marker_from_journal(journal)
            or embedded_journal != journal
        ):
            raise OSError(
                "Included Files recovery journal and commit marker disagree"
            )

    transaction = journal.transaction
    if commit_identity is None:
        rollback_errors = _rollback_included_output_set(
            transaction,
            root_backup_path=journal.root_backup_path,
            registry_backup_path=journal.registry_backup_path,
            registry_directory_path=journal.registry_directory_path,
            registry_directory_identity=journal.registry_directory_identity,
            registry_directory_created=journal.registry_directory_created,
        )
        if rollback_errors:
            error = OSError(
                "Interrupted Included Files generation could not be rolled back"
            )
            for rollback_error in rollback_errors:
                error.add_note(str(rollback_error))
            raise error
        final_root_path = os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME)
        _verify_included_tree_snapshot(
            final_root_path,
            transaction.previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _verify_included_registry_snapshot(
            project_path,
            transaction.previous_registry_snapshot,
            expected_project_identity=project_identity,
        )
        rollback_cleanup_warnings = _cleanup_recorded_included_tree(
            transaction.stage_container_path,
            transaction.staged_container_snapshot,
            project_identity,
            journal.transaction_id,
            "rollback-stage",
        )
        _sync_included_directory(project_path, project_identity)
        previous_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
        )
        if previous_registry_directory_identity is not None:
            _sync_included_directory(
                journal.registry_directory_path,
                previous_registry_directory_identity,
            )
        _remove_included_recovery_record(
            journal_record_path,
            journal_identity,
            project_path,
            project_identity,
        )
        orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
            project_path,
            project_identity,
        )
        _after_included_transaction_phase("recovery-rolled-back")
        message = "rolled back an interrupted Included Files generation"
        if journal_promoted:
            message += " from its durable journal temporary"
        if orphan_count:
            message += f"; removed {orphan_count} orphan transaction entries"
        all_warnings = (
            *promotion_warnings,
            *rollback_cleanup_warnings,
            *orphan_warnings,
        )
        if all_warnings:
            message += "; " + "; ".join(all_warnings)
        return message

    cleanup_errors, cleanup_warnings = _cleanup_committed_included_output_set(
        journal
    )
    if cleanup_errors:
        error = OSError(
            "Committed Included Files generation recovery could not finish cleanup"
        )
        for cleanup_error in cleanup_errors:
            error.add_note(str(cleanup_error))
        raise error
    _remove_included_recovery_record(
        journal_record_path,
        journal_identity,
        project_path,
        project_identity,
    )
    _after_included_transaction_phase("recovery-journal-removed")
    _remove_included_recovery_record(
        commit_record_path,
        commit_identity,
        project_path,
        project_identity,
    )
    orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
        project_path,
        project_identity,
    )
    _after_included_transaction_phase("recovery-committed")
    message = "finalized a committed Included Files generation"
    all_warnings = (*promotion_warnings, *cleanup_warnings, *orphan_warnings)
    if orphan_count:
        message += f"; removed {orphan_count} orphan transaction entries"
    if all_warnings:
        message += "; " + "; ".join(all_warnings)
    return message


def _commit_included_output_set(
    project_path: str,
    transaction: _IncludedOutputSetTransaction,
    conversion_running: ConversionRunning,
) -> tuple[str, ...]:
    """Publish one journaled, recoverable root/registry generation."""
    final_root_path = os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME)
    final_registry_path = _included_registry_path(project_path)
    journal_path = os.path.join(project_path, _INCLUDED_FILES_JOURNAL_NAME)
    commit_path = os.path.join(project_path, _INCLUDED_FILES_COMMIT_NAME)
    root_backup_path = _unique_included_transaction_path(
        project_path,
        "included_files",
    )
    registry_directory_path = os.path.dirname(final_registry_path)
    registry_backup_path = _unique_included_transaction_path(
        registry_directory_path
        if transaction.previous_registry_snapshot.file_identity is not None
        else project_path,
        "gml_included_file_registry.gd",
    )
    registry_directory_identity: _PathIdentity | None = None
    registry_directory_created = False
    journal_identity: _PathIdentity | None = None
    commit_marker_identity: _PathIdentity | None = None
    recovery_journal: _IncludedRecoveryJournal | None = None

    try:
        _verify_included_project_identity(
            project_path,
            transaction.project_identity,
        )
        _verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _verify_included_tree_snapshot(
            final_root_path,
            transaction.previous_root_snapshot,
            expected_parent_identity=transaction.project_identity,
        )
        _verify_included_registry_snapshot(
            project_path,
            transaction.previous_registry_snapshot,
            expected_project_identity=transaction.project_identity,
        )
        if transaction.content_receipts:
            publication_transaction_id = (
                transaction.publication_transaction_id
            )
            staged_generation_identity = (
                transaction.staged_root_snapshot.identity
            )
            if (
                publication_transaction_id is None
                or staged_generation_identity is None
            ):
                raise OSError(
                    "Included Files generation receipts lost their "
                    "transaction binding"
                )
            current_staged_snapshot = (
                _capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=(
                        transaction.stage_container_identity
                    ),
                    transaction_id=publication_transaction_id,
                    generation_identity=staged_generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=transaction.content_receipts,
                )
            )
            if current_staged_snapshot != transaction.staged_root_snapshot:
                raise OSError(
                    "Included Files generation receipt snapshot changed"
                )
            for content_receipt in transaction.content_receipts:
                _verify_included_generation_source_receipt(
                    content_receipt.source,
                    validate_content=False,
                )
        else:
            _verify_included_tree_snapshot(
                transaction.staged_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.stage_container_identity,
            )
        staged_registry_state = _included_regular_file_state(
            transaction.staged_registry_path,
            expected_parent_identity=transaction.stage_container_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            staged_registry_state is None
            or staged_registry_state[0] != transaction.staged_registry_identity
            or staged_registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError("Included File registry staging candidate changed")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        expected_record_sizes = transaction.recovery_record_sizes
        if expected_record_sizes is None:
            raise OSError(
                "Included Files recovery metadata was not preflighted before "
                "payload staging"
            )
        provisional_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
            or (
                transaction.project_identity[0],
                _INCLUDED_FILES_RECOVERY_INTEGER_MAX,
            )
        )
        provisional_journal = _IncludedRecoveryJournal(
            format_version=_INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id="0" * 32,
            transaction=transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=(
                provisional_registry_directory_identity
            ),
            registry_directory_created=(
                transaction.previous_registry_snapshot.directory_identity
                is None
            ),
        )
        _verify_included_recovery_record_sizes(
            expected_record_sizes,
            provisional_journal,
        )

        (
            registry_directory_path,
            registry_directory_identity,
            registry_directory_created,
        ) = _prepare_included_registry_directory(
            project_path,
            transaction.previous_registry_snapshot,
            transaction.project_identity,
        )
        registry_backup_path = _unique_included_transaction_path(
            registry_directory_path
            if transaction.previous_registry_snapshot.file_identity is not None
            else project_path,
            "gml_included_file_registry.gd",
        )
        recovery_journal = _IncludedRecoveryJournal(
            format_version=_INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id=(
                transaction.publication_transaction_id
                or secrets.token_hex(16)
            ),
            transaction=transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        _verify_included_recovery_record_sizes(
            expected_record_sizes,
            recovery_journal,
        )
        journal_identity = _publish_included_recovery_record(
            project_path,
            transaction.project_identity,
            filename=_INCLUDED_FILES_JOURNAL_NAME,
            temporary_prefix=_INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
            payload=_included_recovery_journal_payload(recovery_journal),
            staged_phase="journal-record-staged",
        )
        _after_included_transaction_phase("journal-prepared")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        previous_root_identity = transaction.previous_root_snapshot.identity
        if previous_root_identity is not None:
            _move_exact_included_directory(
                final_root_path,
                root_backup_path,
                previous_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.project_identity,
            )
        _sync_included_directory(project_path, transaction.project_identity)
        _after_included_transaction_phase("previous-root-backed-up")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        staged_root_identity = transaction.staged_root_snapshot.identity
        if staged_root_identity is None:
            raise AssertionError("A staged Included Files root must be present")
        _move_exact_included_directory(
            transaction.staged_root_path,
            final_root_path,
            staged_root_identity,
            source_parent_identity=transaction.stage_container_identity,
            destination_parent_identity=transaction.project_identity,
        )
        _sync_included_directory(
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _sync_included_directory(project_path, transaction.project_identity)
        _verify_included_tree_snapshot_metadata(
            final_root_path,
            transaction.staged_root_snapshot,
            expected_parent_identity=transaction.project_identity,
        )
        _after_included_transaction_phase("new-root-published")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        previous_registry_identity = (
            transaction.previous_registry_snapshot.file_identity
        )
        if previous_registry_identity is not None:
            _move_exact_included_file(
                final_registry_path,
                registry_backup_path,
                previous_registry_identity,
                source_parent_identity=registry_directory_identity,
                destination_parent_identity=registry_directory_identity,
            )
        _sync_included_directory(
            registry_directory_path,
            registry_directory_identity,
        )
        _after_included_transaction_phase("previous-registry-backed-up")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        _move_exact_included_file(
            transaction.staged_registry_path,
            final_registry_path,
            transaction.staged_registry_identity,
            source_parent_identity=transaction.stage_container_identity,
            destination_parent_identity=registry_directory_identity,
        )
        _sync_included_directory(
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _sync_included_directory(
            registry_directory_path,
            registry_directory_identity,
        )
        published_registry_state = _included_regular_file_state(
            final_registry_path,
            expected_parent_identity=registry_directory_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            published_registry_state is None
            or published_registry_state[0] != transaction.staged_registry_identity
            or published_registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError("Included File registry changed after publication")
        _after_included_transaction_phase("new-registry-published")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()
        _sync_included_tree_directories_bottom_up(
            final_root_path,
            transaction.staged_root_snapshot,
            transaction.project_identity,
        )
        journal_identity = _verify_included_published_journal(
            project_path,
            transaction.project_identity,
            recovery_journal,
            journal_identity,
        )
        if transaction.content_receipts:
            publication_transaction_id = (
                transaction.publication_transaction_id
            )
            staged_generation_identity = (
                transaction.staged_root_snapshot.identity
            )
            if (
                publication_transaction_id is None
                or staged_generation_identity is None
                or recovery_journal.transaction_id
                != publication_transaction_id
            ):
                raise OSError(
                    "Included Files generation receipts crossed transaction "
                    "or generation boundaries"
                )
            final_receipt_snapshot = (
                _capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=transaction.project_identity,
                    transaction_id=publication_transaction_id,
                    generation_identity=staged_generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=transaction.content_receipts,
                    published=True,
                )
            )
            if final_receipt_snapshot != transaction.staged_root_snapshot:
                raise OSError(
                    "Published Included Files generation receipt changed"
                )
            _before_included_changed_generation_final_validation()
            for content_receipt in transaction.content_receipts:
                _verify_included_generation_source_receipt(
                    content_receipt.source,
                    validate_content=True,
                )
        _verify_included_commit_marker_generation(
            project_path,
            _included_commit_marker_from_journal(recovery_journal),
        )
        _verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        commit_marker_identity = _publish_included_recovery_record(
            project_path,
            transaction.project_identity,
            filename=_INCLUDED_FILES_COMMIT_NAME,
            temporary_prefix=_INCLUDED_FILES_COMMIT_TEMP_PREFIX,
            payload=_included_commit_marker_payload(recovery_journal),
            staged_phase="commit-record-staged",
        )
        _after_included_transaction_phase("generation-committed")
        commit_marker_identity = _verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
    except BaseException as error:
        if commit_marker_identity is None and recovery_journal is not None:
            try:
                stable_commit_record = _read_included_recovery_record(
                    commit_path,
                    transaction.project_identity,
                )
                if stable_commit_record is not None:
                    commit_marker_identity = (
                        _verify_included_published_commit_marker(
                            project_path,
                            transaction.project_identity,
                            recovery_journal,
                            None,
                            verify_generation=False,
                        )
                    )
            except Exception as marker_error:
                error.add_note(
                    "The Included Files commit path became ambiguous after "
                    "publication; rollback was not attempted: " + str(marker_error)
                )
                raise error from marker_error
        if commit_marker_identity is not None:
            error.add_note(
                "The new Included Files generation was durably committed; "
                "the next conversion will finish cleanup"
            )
            raise
        rollback_errors = _rollback_included_output_set(
            transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        if not rollback_errors:
            try:
                rollback_cleanup_warnings = _cleanup_recorded_included_tree(
                    transaction.stage_container_path,
                    transaction.staged_container_snapshot,
                    transaction.project_identity,
                    (
                        recovery_journal.transaction_id
                        if recovery_journal is not None
                        else "unprepared-stage"
                    ),
                    "rollback-stage",
                )
                for cleanup_warning in rollback_cleanup_warnings:
                    error.add_note(cleanup_warning)
                _sync_included_directory(
                    project_path,
                    transaction.project_identity,
                )
                if (
                    registry_directory_identity is not None
                    and _included_directory_identity(registry_directory_path)
                    == registry_directory_identity
                ):
                    _sync_included_directory(
                        registry_directory_path,
                        registry_directory_identity,
                    )
                stable_journal_record = _read_included_recovery_record(
                    journal_path,
                    transaction.project_identity,
                )
                if recovery_journal is not None and stable_journal_record is not None:
                    journal_identity = _verify_included_published_journal(
                        project_path,
                        transaction.project_identity,
                        recovery_journal,
                        journal_identity,
                    )
                    _remove_included_recovery_record(
                        journal_path,
                        journal_identity,
                        project_path,
                        transaction.project_identity,
                    )
                    journal_identity = None
                _after_included_transaction_phase("rollback-complete")
            except Exception as cleanup_error:
                rollback_errors = (cleanup_error,)
        if rollback_errors:
            error.add_note(
                "Included Files rollback also failed: "
                + "; ".join(str(rollback_error) for rollback_error in rollback_errors)
            )
        raise

    cleanup_errors, cleanup_warnings = _cleanup_committed_included_output_set(
        recovery_journal,
        verify_content=False,
    )
    if cleanup_errors:
        return tuple(str(cleanup_error) for cleanup_error in cleanup_errors)

    try:
        commit_marker_identity = _verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _remove_included_recovery_record(
            journal_path,
            journal_identity,
            project_path,
            transaction.project_identity,
        )
        _after_included_transaction_phase("journal-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))

    try:
        commit_marker_identity = _verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _remove_included_recovery_record(
            commit_path,
            commit_marker_identity,
            project_path,
            transaction.project_identity,
        )
        _after_included_transaction_phase("commit-marker-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))
    return cleanup_warnings


def _included_output_components(
    project_path: str,
    output_path: str,
) -> tuple[str, ...]:
    project_root = os.path.abspath(project_path)
    absolute_output = os.path.abspath(output_path)
    try:
        contained = os.path.normcase(
            os.path.commonpath((project_root, absolute_output))
        ) == os.path.normcase(project_root)
    except ValueError:
        contained = False
    relative_path = (
        os.path.relpath(absolute_output, project_root)
        if contained
        else os.pardir
    )
    components = tuple(relative_path.split(os.sep))
    if (
        not contained
        or os.path.isabs(relative_path)
        or len(components) < 2
        or components[0] != "included_files"
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise ValueError(
            f"Generated Included File output escapes its managed root: {output_path}"
        )
    return components


def _ensure_included_output_project_root(project_path: str) -> tuple[int, int]:
    os.makedirs(project_path, exist_ok=True)
    project_stat = os.lstat(project_path)
    if (
        _included_output_path_is_redirected(project_path, project_stat)
        or not stat.S_ISDIR(project_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected Included File output root: {project_path}"
        )
    return (project_stat.st_dev, project_stat.st_ino)


def _confined_included_output_supported() -> bool:
    return (
        os.name != "nt"
        and os.chmod in os.supports_fd
        and os.utime in os.supports_fd
        and all(
            operation in os.supports_dir_fd
            for operation in (os.open, os.mkdir, os.stat, os.rename, os.unlink)
        )
    )


def _open_or_create_included_output_directory(
    parent_fd: int,
    component: str,
    flags: int,
) -> int:
    try:
        return os.open(component, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(component, 0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            return os.open(component, flags, dir_fd=parent_fd)
        except OSError as error:
            raise OSError(
                "Refusing redirected Included File output directory: "
                f"{component}"
            ) from error
    except OSError as error:
        raise OSError(
            f"Refusing redirected Included File output directory: {component}"
        ) from error


def _verify_open_included_output_directory(
    project_path: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Included File output directory changed: {directory_path}"
        ) from error
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_real = os.path.normcase(os.path.realpath(directory_path))
    try:
        contained = (
            os.path.commonpath((project_real, directory_real))
            == project_real
        )
    except ValueError:
        contained = False
    if (
        _included_output_path_is_redirected(directory_path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected Included File output directory: {directory_path}"
        )


def _included_output_state_at(
    directory_fd: int,
    filename: str,
) -> tuple[int, int] | None:
    try:
        output_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing non-regular Included File output: {filename}"
        )
    return (output_stat.st_dev, output_stat.st_ino)


def _verify_included_output_state_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity = _included_output_state_at(directory_fd, filename)
    if current_identity != expected_identity:
        raise OSError(
            f"Included File output changed during publication: {filename}"
        )


def _apply_included_output_metadata(
    file_descriptor: int,
    source_stat: os.stat_result,
) -> None:
    if os.chmod in os.supports_fd:
        os.chmod(file_descriptor, stat.S_IMODE(source_stat.st_mode))
    if os.utime in os.supports_fd:
        os.utime(
            file_descriptor,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )


def _read_included_payload_chunk(source_file: BinaryIO) -> bytes:
    return source_file.read(1024 * 1024)


def _copy_included_payload(
    source_file: BinaryIO,
    target_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedPayloadReceipt:
    expected_fingerprint = _included_source_fingerprint(source_stat)
    if source_file.tell() != 0:
        raise OSError("GameMaker Included File source did not start at offset zero")
    before_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(before_copy.st_mode)
        or _included_source_fingerprint(before_copy) != expected_fingerprint
    ):
        raise OSError("GameMaker Included File source changed before copying")

    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = _read_included_payload_chunk(source_file)
        if not chunk:
            break
        written = target_file.write(chunk)
        if written != len(chunk):
            raise OSError("Could not write the complete Included File payload")
        digest.update(chunk)
        byte_count += len(chunk)

    after_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(after_copy.st_mode)
        or _included_source_fingerprint(after_copy) != expected_fingerprint
        or byte_count != source_stat.st_size
    ):
        raise OSError("GameMaker Included File source changed while copying")
    streamed_sha256 = digest.hexdigest()
    if expected_receipt is not None:
        if (
            expected_receipt.byte_count != byte_count
            or expected_receipt.sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed after its "
                "planning receipt"
            )
    else:
        source_file.seek(0)
        verified_byte_count, verified_sha256 = _digest_open_included_file(
            source_file
        )
        after_verification = os.fstat(source_file.fileno())
        if (
            _included_source_fingerprint(after_verification)
            != expected_fingerprint
            or verified_byte_count != byte_count
            or verified_sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed while copying"
            )
    return _IncludedPayloadReceipt(
        source_fingerprint=expected_fingerprint,
        byte_count=byte_count,
        sha256=streamed_sha256,
    )


def _stage_included_output_at(
    directory_fd: int,
    filename: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    verify_directory: Callable[[], None],
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    verify_directory()
    output_identity = _included_output_state_at(directory_fd, filename)
    temporary_name = ""
    file_descriptor = -1
    for _attempt in range(100):
        temporary_name = f".gm2godot-{secrets.token_hex(8)}.tmp"
        try:
            file_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileExistsError:
            continue
    if file_descriptor < 0:
        raise OSError(f"Could not stage Included File output: {filename}")

    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    published_pending = False
    try:
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _apply_included_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        staged_stat = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(f"Included File staging output changed: {filename}")
        verify_directory()
        _verify_included_output_state_at(
            directory_fd,
            filename,
            output_identity,
        )
        verify_directory()
        os.rename(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_pending = False
        published_pending = True
        published_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(f"Included File output changed after publication: {filename}")
        verify_directory()
        published_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            opened_stat = os.fstat(published_fd)
            current_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_path_handle_binding(current_stat)
                != _included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {filename}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_handle_state(opened_stat),
            )
        finally:
            os.close(published_fd)
        verify_directory()
        published_pending = False
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending and temporary_name:
            try:
                current_stat = os.stat(
                    temporary_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    current_stat.st_dev,
                    current_stat.st_ino,
                ) == temporary_identity:
                    os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        if published_pending:
            try:
                current_stat = os.stat(
                    filename,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISREG(current_stat.st_mode)
                    and (
                        current_stat.st_dev,
                        current_stat.st_ino,
                    )
                    == temporary_identity
                ):
                    os.unlink(filename, dir_fd=directory_fd)
            except OSError:
                pass


def _publish_included_output_at(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    project_fd = os.open(project_path, directory_flags)
    current_fd = project_fd
    try:
        _verify_open_included_output_directory(
            project_path,
            project_path,
            project_fd,
        )
        for component in components[:-1]:
            child_fd = _open_or_create_included_output_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != project_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(project_path, *components[:-1])
        def verify_output_directory() -> None:
            _verify_open_included_output_directory(
                project_path,
                output_directory,
                current_fd,
            )

        verify_output_directory()
        receipt = _stage_included_output_at(
            current_fd,
            components[-1],
            source_file,
            source_stat,
            verify_output_directory,
            expected_receipt,
        )
        verify_output_directory()
        return receipt
    finally:
        if current_fd != project_fd:
            os.close(current_fd)
        os.close(project_fd)


def _prepare_included_output_directories_fallback(
    project_path: str,
    directory_components: tuple[str, ...],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_path = project_path
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in (None, *directory_components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
            try:
                directory_stat = os.lstat(directory_path)
            except FileNotFoundError:
                try:
                    os.mkdir(directory_path)
                except FileExistsError:
                    pass
                directory_stat = os.lstat(directory_path)
        else:
            directory_stat = os.lstat(directory_path)
        directory_real = os.path.normcase(os.path.realpath(directory_path))
        try:
            contained = (
                os.path.commonpath((project_real, directory_real))
                == project_real
            )
        except ValueError:
            contained = False
        if (
            _included_output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not contained
        ):
            raise OSError(
                "Refusing redirected Included File output directory: "
                f"{directory_path}"
            )
        identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return tuple(identities)


def _verify_included_output_directories_fallback(
    identities: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            directory_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            ) from error
        if (
            _included_output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or (directory_stat.st_dev, directory_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            )


def _verify_included_output_stage_fallback(
    staged_path: str,
    expected_identity: tuple[int, int],
    expected_project_identity: tuple[int, int],
) -> None:
    try:
        staged_stat = os.lstat(staged_path)
        parent_path = os.path.dirname(staged_path) or os.curdir
        parent_stat = os.lstat(parent_path)
    except OSError as error:
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        ) from error
    if (
        _included_output_path_is_redirected(staged_path, staged_stat)
        or not stat.S_ISREG(staged_stat.st_mode)
        or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        or _included_output_path_is_redirected(parent_path, parent_stat)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or (parent_stat.st_dev, parent_stat.st_ino)
        != expected_project_identity
    ):
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        )


def _remove_included_output_stage_fallback(
    staged_paths: tuple[str, ...],
    expected_identity: tuple[int, int],
) -> None:
    checked_paths: set[str] = set()
    for staged_path in staged_paths:
        normalized_path = os.path.normcase(os.path.abspath(staged_path))
        if normalized_path in checked_paths:
            continue
        checked_paths.add(normalized_path)
        try:
            staged_stat = os.lstat(staged_path)
        except OSError:
            continue
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        ):
            continue
        try:
            os.unlink(staged_path)
        except PermissionError:
            if os.name != "nt":
                raise
            os.chmod(staged_path, stat.S_IWRITE)
            writable_stat = os.lstat(staged_path)
            if (
                not stat.S_ISREG(writable_stat.st_mode)
                or (writable_stat.st_dev, writable_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Included File staging output changed: {staged_path}"
                )
            os.unlink(staged_path)
        return


def _included_output_state(
    output_path: str,
) -> tuple[int, int] | None:
    try:
        output_stat = os.lstat(output_path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing non-regular Included File output: {output_path}"
        )
    return (output_stat.st_dev, output_stat.st_ino)


def _verify_included_output_state(
    output_path: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity = _included_output_state(output_path)
    if current_identity != expected_identity:
        raise OSError(
            f"Included File output changed during publication: {output_path}"
        )


def _publish_included_output_fallback(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_identities = _prepare_included_output_directories_fallback(
        project_path,
        components[:-1],
    )
    output_directory = os.path.join(project_path, *components[:-1])
    output_path = os.path.join(output_directory, components[-1])
    output_identity = _included_output_state(output_path)
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=project_path,
        prefix=".gm2godot-",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    resolved_temporary_path = temporary_path
    temporary_pending = True
    try:
        resolved_temporary_path = os.path.realpath(temporary_path)
        _verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        _verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        _verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _apply_included_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        _verify_included_output_directories_fallback(directory_identities)
        _verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        _verify_included_output_state(output_path, output_identity)
        _verify_included_output_directories_fallback(directory_identities)
        os.replace(resolved_temporary_path, output_path)
        temporary_pending = False
        published_stat = os.lstat(output_path)
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(
                f"Included File output changed after publication: {output_path}"
            )
        with _open_included_file_validation_stream(
            output_path,
            deny_writes=False,
            no_follow=True,
        ) as published_file:
            opened_stat = os.fstat(published_file.fileno())
            current_stat = os.lstat(output_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_path_handle_binding(current_stat)
                != _included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {output_path}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_handle_state(opened_stat),
            )
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _remove_included_output_stage_fallback(
                    (resolved_temporary_path, temporary_path),
                    temporary_identity,
                )
            except OSError:
                pass


def _publish_confined_included_output(
    project_path: str,
    output_path: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    components = _included_output_components(project_path, output_path)
    _ensure_included_output_project_root(project_path)
    if _confined_included_output_supported():
        return _publish_included_output_at(
            project_path,
            components,
            source_file,
            source_stat,
            expected_receipt,
        )
    return _publish_included_output_fallback(
        project_path,
        components,
        source_file,
        source_stat,
        expected_receipt,
    )


def _before_included_unchanged_source_revalidation() -> None:
    """Narrow test seam before the second stable source-content pass."""


def _before_included_unchanged_public_revalidation() -> None:
    """Narrow test seam before rehashing the candidate public generation."""


def _before_included_unchanged_final_revalidation() -> None:
    """Narrow test seam before final source and public identity checks."""


def _before_included_changed_generation_final_validation() -> None:
    """Narrow test seam before final receipt-bound content validation."""


class IncludedFilesConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self._active_output_project_path: str | None = None

    def _process_file(
        self,
        gm_file_path: str,
        godot_file_path: str,
        rel_path: str,
        owner_source_path: str = "datafiles",
        planned_receipt: _IncludedNoOpSourceReceipt | None = None,
    ) -> tuple[str, bool, _IncludedCopyReceipt | None] | None:
        if not self.conversion_running():
            return None
        self._resource_requested(rel_path)
        self._resource_started(rel_path)

        try:
            opened_source = self._open_confined_source_file(
                gm_file_path,
                owner_source_path=owner_source_path,
                resource=rel_path,
            )
            if opened_source is None:
                self._resource_failed(rel_path)
                return rel_path, False, None

            source_file, source_stat = opened_source
            with source_file:
                try:
                    if planned_receipt is not None:
                        active_project_path = (
                            self._active_output_project_path
                            or self.godot_project_path
                        )
                        output_components = _included_output_components(
                            active_project_path,
                            godot_file_path,
                        )
                        assigned_path = posixpath.join(
                            *output_components[1:]
                        )
                        if (
                            planned_receipt.logical_path != rel_path
                            or planned_receipt.assigned_path != assigned_path
                            or self._capture_pinned_included_source_binding(
                                _IncludedFileSource(
                                    filesystem_path=gm_file_path,
                                    relative_path=rel_path,
                                    owner_source_path=owner_source_path,
                                ),
                                source_file,
                                source_stat,
                            )
                            != planned_receipt.binding
                        ):
                            raise OSError(
                                "GameMaker Included File planning receipt "
                                f"changed before staging: {rel_path}"
                            )
                    if planned_receipt is None:
                        copy_receipt = _publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                        )
                    else:
                        copy_receipt = _publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                            planned_receipt,
                        )
                    if (
                        planned_receipt is not None
                        and self._capture_pinned_included_source_binding(
                            _IncludedFileSource(
                                filesystem_path=gm_file_path,
                                relative_path=rel_path,
                                owner_source_path=owner_source_path,
                            ),
                            source_file,
                            source_stat,
                        )
                        != planned_receipt.binding
                    ):
                        raise OSError(
                            "GameMaker Included File planning receipt changed "
                            f"while staging: {rel_path}"
                        )
                except (OSError, ValueError) as error:
                    self._resource_failed(rel_path)
                    self._report_included_file_output_rejection(
                        rel_path,
                        godot_file_path,
                        error,
                    )
                    return rel_path, False, None
        except Exception:
            self._resource_failed(rel_path)
            raise
        return rel_path, True, copy_receipt

    def _report_included_file_output_rejection(
        self,
        relative_path: str,
        output_path: str,
        error: BaseException,
    ) -> None:
        message = (
            "Error: Refusing to publish GameMaker Included File "
            f"{relative_path!r} to {output_path!r}: {error}"
        )
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "error",
                    "GM2GD-INCLUDED-FILE-OUTPUT-REJECTED",
                    message,
                    source_path="datafiles/" + relative_path,
                    resource=relative_path,
                    resource_type="included_file",
                    manifest_entry="generated Included File output",
                    workaround=(
                        "Remove redirected or non-regular entries from the "
                        "Godot included_files output tree and retry conversion."
                    ),
                )
            self.log_callback(message)

    def _open_confined_source_file(
        self,
        filesystem_path: str,
        *,
        owner_source_path: str,
        resource: str,
        deny_writes: bool = False,
    ) -> tuple[BinaryIO, os.stat_result] | None:
        """Open a contained regular file and pin it against late path swaps."""
        resolved = self._resolve_discovered_project_source(
            filesystem_path,
            owner_source_path=owner_source_path,
            resource=resource,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            return None

        try:
            source_file = _open_included_file_validation_stream(
                resolved.filesystem_path,
                deny_writes=deny_writes,
            )
        except OSError:
            return None

        try:
            opened_stat = os.fstat(source_file.fileno())
            revalidated = self._resolve_discovered_project_source(
                resolved.filesystem_path,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="included_file",
                field="discovered datafiles file",
            )
            if revalidated is None:
                source_file.close()
                return None
            current_stat = os.stat(revalidated.filesystem_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
            ):
                source_file.close()
                self._report_source_path_rejection(
                    filesystem_path,
                    ProjectSourcePathError(
                        "Discovered GameMaker source file changed after validation"
                    ),
                    owner_source_path=owner_source_path,
                    resource=resource,
                    resource_type="included_file",
                    field="discovered datafiles file",
                )
                return None
        except OSError:
            source_file.close()
            return None
        return source_file, opened_stat

    def _preflight_included_source_byte_counts(
        self,
        sources: tuple[_IncludedFileSource, ...],
    ) -> dict[str, int]:
        """Capture byte counts without reading or staging payload bodies."""

        byte_counts: dict[str, int] = {}
        for source in sources:
            if not self.conversion_running():
                raise _IncludedOutputSetCancelled()
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    "recovery-record preflight: "
                    + source.relative_path
                )
            source_file, source_stat = opened_source
            with source_file:
                _included_recovery_compact_integer_payload(
                    source_stat.st_size,
                    "source byte count",
                )
                byte_counts[source.relative_path] = source_stat.st_size
        return byte_counts

    def _capture_pinned_included_source_binding(
        self,
        source: _IncludedFileSource,
        source_file: BinaryIO,
        expected_stat: os.stat_result,
    ) -> _IncludedSourceBinding:
        resolved = self._resolve_discovered_project_source(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )

        lexical_stat = os.lstat(resolved.filesystem_path)
        path_stat = os.stat(resolved.filesystem_path)
        handle_stat = os.fstat(source_file.fileno())
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(handle_stat.st_mode)
            or not os.path.samestat(expected_stat, path_stat)
            or not os.path.samestat(path_stat, handle_stat)
            or _included_handle_state(handle_stat)
            != _included_handle_state(expected_stat)
            or _included_path_handle_binding(path_stat)
            != _included_path_handle_binding(handle_stat)
        ):
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )
        canonical_path, directory_identities = (
            _capture_included_source_directory_identities(
                self.gm_project_path,
                resolved.filesystem_path,
            )
        )
        _verify_fallback_directory_ancestors(directory_identities)
        return _IncludedSourceBinding(
            filesystem_path=os.path.normcase(
                os.path.abspath(resolved.filesystem_path)
            ),
            canonical_path=canonical_path,
            directory_identities=directory_identities,
            lexical_state=_included_handle_state(lexical_stat),
            path_state=_included_handle_state(path_stat),
            handle_state=_included_handle_state(handle_stat),
        )

    def _capture_unchanged_source_receipt(
        self,
        source: _IncludedFileSource,
        *,
        deny_writes: bool,
    ) -> _IncludedNoOpSourceReceipt:
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        opened_source = self._open_confined_source_file(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            deny_writes=deny_writes,
        )
        if opened_source is None:
            raise OSError(
                "GameMaker Included File source became unavailable during "
                f"unchanged-generation validation: {source.relative_path}"
            )
        source_file, source_stat = opened_source
        with source_file:
            if source_file.tell() != 0:
                raise OSError(
                    "GameMaker Included File validation stream did not start "
                    f"at offset zero: {source.relative_path}"
                )
            before_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            byte_count, sha256 = _digest_open_included_file(source_file)
            after_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            if (
                after_binding != before_binding
                or byte_count != source_stat.st_size
            ):
                raise OSError(
                    "GameMaker Included File source changed while validating "
                    f"an unchanged generation: {source.relative_path}"
                )
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        return _IncludedNoOpSourceReceipt(
            logical_path=source.relative_path,
            assigned_path="",
            binding=before_binding,
            byte_count=byte_count,
            sha256=sha256,
        )

    def _collect_unchanged_source_receipts(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        *,
        deny_writes: bool,
    ) -> dict[str, _IncludedNoOpSourceReceipt]:
        receipts: dict[str, _IncludedNoOpSourceReceipt] = {}

        def submit_receipt(
            executor: ThreadPoolExecutor,
            source: _IncludedFileSource,
        ) -> Future[_IncludedNoOpSourceReceipt]:
            return executor.submit(
                self._capture_unchanged_source_receipt,
                source,
                deny_writes=deny_writes,
            )

        def consume_receipt(
            source: _IncludedFileSource,
            future: Future[_IncludedNoOpSourceReceipt],
        ) -> bool:
            receipts[source.relative_path] = replace(
                future.result(),
                assigned_path=assignments_by_source[
                    source.relative_path
                ].assigned_output_path,
            )
            return True

        phase_completed = _run_bounded_included_worker_phase(
            sources,
            max_workers=self.max_workers,
            conversion_running=self.conversion_running,
            submit=submit_receipt,
            consume=consume_receipt,
        )
        if not phase_completed:
            raise _IncludedOutputSetCancelled()
        return receipts

    def _revalidate_unchanged_source_bindings(
        self,
        sources: tuple[_IncludedFileSource, ...],
        receipts: dict[str, _IncludedNoOpSourceReceipt],
    ) -> None:
        for source in sources:
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
                deny_writes=True,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    f"final unchanged-generation validation: {source.relative_path}"
                )
            source_file, source_stat = opened_source
            with source_file:
                current_binding = self._capture_pinned_included_source_binding(
                    source,
                    source_file,
                    source_stat,
                )
            if current_binding != receipts[source.relative_path].binding:
                raise OSError(
                    "GameMaker Included File source changed during final "
                    f"unchanged-generation validation: {source.relative_path}"
                )

    def _unchanged_included_generation_matches(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        expected_registry_content: bytes,
        previous_root_snapshot: _IncludedTreeSnapshot,
        previous_registry_snapshot: _IncludedRegistrySnapshot,
        project_identity: _PathIdentity,
        public_root_path: str,
    ) -> _IncludedGenerationMatch:
        assigned_paths = {
            assignments_by_source[source.relative_path].assigned_output_path
            for source in sources
        }
        if (
            previous_registry_snapshot.directory_identity is None
            or previous_registry_snapshot.file_identity is None
            or previous_registry_snapshot.content != expected_registry_content
            or not _included_tree_matches_planned_paths(
                previous_root_snapshot,
                assigned_paths,
            )
        ):
            return _IncludedGenerationMatch(
                unchanged=False,
                source_receipts=(),
            )

        first_receipts = self._collect_unchanged_source_receipts(
            sources,
            assignments_by_source,
            deny_writes=False,
        )
        assigned_receipts = {
            assignments_by_source[source.relative_path].assigned_output_path:
                first_receipts[source.relative_path]
            for source in sources
        }
        if not _included_tree_matches_source_receipts(
            previous_root_snapshot,
            assigned_receipts,
        ):
            return _IncludedGenerationMatch(
                unchanged=False,
                source_receipts=tuple(
                    first_receipts[source.relative_path]
                    for source in sources
                ),
            )

        _before_included_unchanged_source_revalidation()
        second_receipts = self._collect_unchanged_source_receipts(
            sources,
            assignments_by_source,
            deny_writes=True,
        )
        if second_receipts != first_receipts:
            raise OSError(
                "GameMaker Included File sources changed during unchanged-"
                "generation validation"
            )

        _before_included_unchanged_public_revalidation()
        _verify_included_tree_snapshot(
            public_root_path,
            previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _verify_included_registry_snapshot(
            self.godot_project_path,
            previous_registry_snapshot,
            expected_project_identity=project_identity,
        )

        _before_included_unchanged_final_revalidation()
        self._revalidate_unchanged_source_bindings(
            sources,
            first_receipts,
        )
        _verify_included_tree_snapshot_metadata(
            public_root_path,
            previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _verify_included_registry_snapshot(
            self.godot_project_path,
            previous_registry_snapshot,
            expected_project_identity=project_identity,
        )
        _verify_included_project_identity(
            self.godot_project_path,
            project_identity,
        )
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        return _IncludedGenerationMatch(
            unchanged=True,
            source_receipts=tuple(
                first_receipts[source.relative_path]
                for source in sources
            ),
        )

    def _list_confined_directory(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> tuple[str, ...] | None:
        """List a contained directory without following a late path swap."""
        revalidated = self._resolve_discovered_project_source(
            directory.filesystem_path,
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )
        if revalidated is None:
            return None

        # On POSIX, list through a validated directory descriptor. If the path
        # is exchanged after validation, the descriptor remains bound to the
        # original contained directory. Other platforms get a before/after
        # identity check around their path-based directory listing.
        if os.listdir in os.supports_fd and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            try:
                directory_fd = os.open(revalidated.filesystem_path, flags)
            except OSError:
                return None
            try:
                opened_stat = os.fstat(directory_fd)
                current = self._resolve_discovered_project_source(
                    revalidated.filesystem_path,
                    owner_source_path=directory.source_path,
                    resource=posixpath.basename(directory.source_path),
                    resource_type="included_file",
                    field="discovered datafiles directory",
                )
                if current is None:
                    return None
                current_stat = os.stat(current.filesystem_path)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or not os.path.samestat(opened_stat, current_stat)
                ):
                    self._report_directory_swap(directory)
                    return None
                return tuple(sorted(os.listdir(directory_fd)))
            except OSError:
                return None
            finally:
                os.close(directory_fd)

        try:
            before_stat = os.stat(revalidated.filesystem_path)
            entries = tuple(sorted(os.listdir(revalidated.filesystem_path)))
            current = self._resolve_discovered_project_source(
                revalidated.filesystem_path,
                owner_source_path=directory.source_path,
                resource=posixpath.basename(directory.source_path),
                resource_type="included_file",
                field="discovered datafiles directory",
            )
            if current is None:
                return None
            after_stat = os.stat(current.filesystem_path)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(before_stat.st_mode)
            or not os.path.samestat(before_stat, after_stat)
        ):
            self._report_directory_swap(directory)
            return None
        return entries

    def _report_directory_swap(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> None:
        self._report_source_path_rejection(
            directory.filesystem_path,
            ProjectSourcePathError(
                "Discovered GameMaker source directory changed after validation"
            ),
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )

    def _collect_included_files(
        self,
        datafiles: ResolvedProjectSourcePath,
    ) -> list[_IncludedFileSource]:
        included_files: list[_IncludedFileSource] = []
        pending_directories = [datafiles]
        visited_directories: set[str] = set()

        while pending_directories:
            directory = pending_directories.pop()
            canonical_directory = os.path.normcase(
                os.path.realpath(directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            entry_names = self._list_confined_directory(directory)
            if entry_names is None:
                continue
            for entry_name in entry_names:
                entry = self._resolve_discovered_project_source(
                    os.path.join(directory.filesystem_path, entry_name),
                    owner_source_path=directory.source_path,
                    resource=entry_name,
                    resource_type="included_file",
                    field="discovered datafiles entry",
                )
                if entry is None:
                    continue
                if os.path.isdir(entry.filesystem_path):
                    # Match os.walk's historical default: contained directory
                    # symlinks are not traversed, while the datafiles root itself
                    # may still be a contained symlink.
                    if not os.path.islink(entry.filesystem_path):
                        pending_directories.append(entry)
                    continue
                if entry_name.endswith(".yy") or not os.path.isfile(
                    entry.filesystem_path
                ):
                    continue
                relative_path = posixpath.relpath(
                    entry.source_path,
                    datafiles.source_path,
                )
                included_files.append(
                    _IncludedFileSource(
                        filesystem_path=entry.filesystem_path,
                        relative_path=relative_path,
                        owner_source_path=directory.source_path,
                    )
                )
        return sorted(included_files, key=lambda item: item.relative_path)

    def _included_file_conversion_plan(self) -> _IncludedFileConversionPlan:
        """Plan logical included files before filtering unavailable sources."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="included_file",
        )
        malformed = any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        )
        manifest_declares_included_files = (
            "IncludedFiles" in manifest.raw_data
            or "includedFiles" in manifest.raw_data
            or any(
                resource.kind.casefold() == "datafiles"
                or resource.resource_type.casefold() == "gmincludedfile"
                for resource in manifest.resources
            )
            or any(
                self._manifest_diagnostic_is_included_file(diagnostic)
                for diagnostic in manifest.diagnostics
            )
        )
        if (
            manifest.yyp_path is not None
            and not malformed
            and manifest_declares_included_files
        ):
            declared_plan = self._plan_manifest_included_files(manifest)
            # Included Files are directory-backed rather than ordinary Asset
            # Browser resources: current GameMaker automatically reflects
            # contained files added under datafiles even before their YYP
            # metadata is refreshed. Preserve those files while still
            # accounting for stale manifest declarations.
            requested_keys = list(declared_plan.requested_keys)
            available_files = list(declared_plan.available_files)
            seen_keys = set(requested_keys)
            for source in self._discovered_included_files():
                if source.relative_path in seen_keys:
                    continue
                seen_keys.add(source.relative_path)
                requested_keys.append(source.relative_path)
                available_files.append(source)
            return _IncludedFileConversionPlan(
                requested_keys=tuple(requested_keys),
                available_files=tuple(available_files),
                skipped_keys=declared_plan.skipped_keys,
            )

        available_files = self._discovered_included_files()
        return _IncludedFileConversionPlan(
            requested_keys=tuple(
                source.relative_path for source in available_files
            ),
            available_files=available_files,
            skipped_keys=(),
        )

    def _discovered_included_files(self) -> tuple[_IncludedFileSource, ...]:
        """Return every contained regular payload under datafiles."""

        datafiles = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource="datafiles",
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles is None or not os.path.isdir(datafiles.filesystem_path):
            return ()
        return tuple(self._collect_included_files(datafiles))

    def _plan_manifest_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _IncludedFileConversionPlan:
        requested_keys: list[str] = []
        available_files: list[_IncludedFileSource] = []
        skipped_keys: list[str] = []
        seen_keys: set[str] = set()

        for declaration in self._declared_included_files(manifest):
            resolved: ResolvedProjectSourcePath | None = None
            unavailable_reason = "its manifest source path was rejected"
            if declaration.source_path is not None:
                resolved = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=declaration.name,
                    resource_type="included_file",
                    field=declaration.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = "its manifest source path was rejected"

            relative_path = self._declared_relative_path(declaration, resolved)
            if relative_path in seen_keys:
                continue
            seen_keys.add(relative_path)
            requested_keys.append(relative_path)

            if resolved is not None:
                source_root, separator, source_relative = (
                    resolved.source_path.partition("/")
                )
                if (
                    not separator
                    or source_root.casefold() != "datafiles"
                    or not source_relative
                ):
                    self._report_source_path_rejection(
                        declaration.source_path or resolved.source_path,
                        ProjectSourcePathError(
                            "Resolved included-file source must remain under "
                            "the GameMaker 'datafiles' directory"
                        ),
                        owner_source_path=declaration.owner_source_path,
                        resource=declaration.name,
                        resource_type="included_file",
                        field=declaration.manifest_field,
                    )
                    resolved = None
                    unavailable_reason = (
                        "its manifest source path was rejected outside the "
                        "datafiles resource family"
                    )
                elif not os.path.isfile(resolved.filesystem_path):
                    unavailable_reason = (
                        f"the source file is missing at {resolved.source_path!r}"
                    )
                    resolved = None

            if resolved is None:
                skipped_keys.append(relative_path)
                self._report_unavailable_declared_included_file(
                    declaration,
                    reason=unavailable_reason,
                )
                continue

            available_files.append(
                _IncludedFileSource(
                    filesystem_path=resolved.filesystem_path,
                    relative_path=relative_path,
                    owner_source_path=declaration.owner_source_path,
                )
            )

        return _IncludedFileConversionPlan(
            requested_keys=tuple(requested_keys),
            available_files=tuple(available_files),
            skipped_keys=tuple(skipped_keys),
        )

    def _declared_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[_DeclaredIncludedFile, ...]:
        """Return unique included-file declarations from a valid YYP."""
        declared: dict[str, _DeclaredIncludedFile] = {}

        def add(resource: _DeclaredIncludedFile, identity: str) -> None:
            normalized_identity = self._normalized_declaration_path(identity)
            if not normalized_identity:
                normalized_identity = resource.name
            if not normalized_identity:
                return
            declared.setdefault(normalized_identity, resource)

        for included_file in manifest.included_files:
            source = included_file.source
            field = source.field_path if source is not None else None
            raw_field = next(
                (
                    key
                    for key in ("path", "filePath", "filename")
                    if key in included_file.raw_data
                ),
                "path",
            )
            manifest_field = f"{field}.{raw_field}" if field else raw_field
            source_path = included_file.path
            if (
                raw_field == "filePath"
                and included_file.name
                and posixpath.basename(source_path) != included_file.name
            ):
                # Current GameMaker YYP files store the containing directory in
                # ``filePath`` and the payload filename separately in ``name``.
                source_path = posixpath.join(source_path, included_file.name)
            add(
                _DeclaredIncludedFile(
                    name=included_file.name or included_file.path,
                    source_path=source_path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=manifest_field,
                ),
                source_path or included_file.name,
            )

        for resource in manifest.resources:
            if (
                resource.kind.casefold() != "datafiles"
                and resource.resource_type.casefold() != "gmincludedfile"
            ):
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredIncludedFile(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=field,
                ),
                resource.path,
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_included_file(diagnostic)
            ):
                continue
            source = diagnostic.source
            field = source.field_path if source is not None else None
            add(
                _DeclaredIncludedFile(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        source.path
                        if source is not None
                        else manifest.yyp_path or ""
                    ),
                    manifest_field=field,
                ),
                f"rejected:{diagnostic.resource}",
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_included_file(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "datafiles"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold()
            in {"included_file", "includedfile", "gmincludedfile"}
        )

    @staticmethod
    def _normalized_declaration_path(path: str) -> str:
        normalized = posixpath.normpath(path.replace("\\", "/").strip())
        return "" if normalized in {"", "."} else normalized

    def _declared_relative_path(
        self,
        declaration: _DeclaredIncludedFile,
        resolved: ResolvedProjectSourcePath | None,
    ) -> str:
        if resolved is not None:
            source_root, separator, source_relative = (
                resolved.source_path.partition("/")
            )
            if (
                separator
                and source_root.casefold() == "datafiles"
                and source_relative
            ):
                return source_relative

        fallback = self._normalized_declaration_path(
            declaration.source_path or declaration.name
        )
        source_root, separator, source_relative = fallback.partition("/")
        if (
            separator
            and source_root.casefold() == "datafiles"
            and source_relative
        ):
            return source_relative
        return fallback or declaration.name

    def _report_unavailable_declared_included_file(
        self,
        declaration: _DeclaredIncludedFile,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker included file "
            f"{declaration.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    declaration.owner_source_path
                ),
                resource=declaration.name,
                resource_type="included_file",
                manifest_entry=declaration.manifest_field,
                workaround=(
                    "Restore the declared included file under the GameMaker "
                    "datafiles directory or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _report_included_file_path_collisions(
        self,
        assignments: tuple[IncludedFilePathAssignment, ...],
    ) -> None:
        reported_paths: set[str] = set()
        assignments_by_source = {
            assignment.original_logical_path: assignment.assigned_output_path
            for assignment in assignments
        }
        for assignment in assignments:
            canonical_path = assignment.canonical_lookup_path
            if not assignment.has_collision or canonical_path in reported_paths:
                continue
            reported_paths.add(canonical_path)
            rendered_assignments = ", ".join(
                f"{source_path!r} -> {assignments_by_source[source_path]!r}"
                for source_path in assignment.collision_group
            )
            message = (
                "Warning: GameMaker Included File paths conflict after "
                f"packaged-name normalization at {canonical_path!r}; "
                "deterministic output paths were assigned: "
                f"{rendered_assignments}."
            )
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "warning",
                    "GM2GD-INCLUDED-FILE-PATH-COLLISION",
                    message,
                    source_path="datafiles",
                    resource=canonical_path,
                    resource_type="included_file",
                    manifest_entry="normalized Included File output path",
                    workaround=(
                        "Rename the conflicting Included Files so their "
                        "lowercase, space-to-underscore packaged paths do not "
                        "collide as files or directories."
                    ),
                )
            self._safe_log(message)

    def convert_included_files(self) -> None:
        plan = self._included_file_conversion_plan()
        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for resource_key in plan.skipped_keys:
            self._resource_skipped(resource_key)

        planned_logical_paths: list[str] = []
        for logical_path in (
            *plan.requested_keys,
            *(source.relative_path for source in plan.available_files),
        ):
            try:
                canonical_included_file_lookup_path(logical_path)
            except ProjectSourcePathError:
                continue
            planned_logical_paths.append(logical_path)
        path_assignments = plan_included_file_paths(planned_logical_paths)
        assignments_by_source = {
            assignment.original_logical_path: assignment
            for assignment in path_assignments
        }

        if not plan.requested_keys:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
        all_files = list(plan.available_files)
        if path_assignments:
            self._report_included_file_path_collisions(path_assignments)
        emitted_logical_paths = {
            source.relative_path for source in all_files
        }

        project_identity = _ensure_included_output_project_root(
            self.godot_project_path
        )
        try:
            project_lock = _acquire_included_project_lock(
                self.godot_project_path,
                project_identity,
            )
        except Exception:
            for source in all_files:
                self._resource_failed(source.relative_path)
            raise
        try:
            recovery_message = _recover_included_output_set(
                self.godot_project_path,
                project_identity,
            )
            if recovery_message is not None:
                self._safe_log("Recovered: " + recovery_message)
        except Exception:
            _release_included_project_lock(project_lock)
            for source in all_files:
                self._resource_failed(source.relative_path)
            raise
        public_root_path = os.path.join(
            self.godot_project_path,
            _INCLUDED_FILES_ROOT_NAME,
        )
        previous_root_snapshot: _IncludedTreeSnapshot
        previous_registry_snapshot: _IncludedRegistrySnapshot
        try:
            previous_root_snapshot = _capture_included_tree(
                public_root_path,
                expected_parent_identity=project_identity,
            )
            previous_registry_snapshot = _capture_included_registry(
                self.godot_project_path,
                expected_project_identity=project_identity,
            )
        except Exception as error:
            _release_included_project_lock(project_lock)
            for source in all_files:
                self._resource_failed(source.relative_path)
                assignment = assignments_by_source[source.relative_path]
                self._report_included_file_output_rejection(
                    source.relative_path,
                    os.path.join(
                        public_root_path,
                        *assignment.assigned_output_path.split("/"),
                    ),
                    error,
                )
            raise

        stage_container_path: str | None = None
        stage_container_identity: _PathIdentity | None = None
        active_error: BaseException | None = None
        transaction_committed = False
        transaction_cleanup_managed = False
        try:
            previous_content_receipts = _included_registry_receipts_from_tree(
                previous_root_snapshot,
                assignments_by_source,
                emitted_logical_paths,
            )
            expected_registry_content = (
                b""
                if previous_content_receipts is None
                else render_included_file_registry(
                    path_assignments,
                    emitted_logical_paths,
                    previous_content_receipts,
                ).encode("utf-8")
            )
            generation_match = self._unchanged_included_generation_matches(
                tuple(all_files),
                assignments_by_source,
                expected_registry_content,
                previous_root_snapshot,
                previous_registry_snapshot,
                project_identity,
                public_root_path,
            )
            if generation_match.unchanged:
                for completed_count, source in enumerate(all_files, start=1):
                    self._resource_started(source.relative_path)
                    self._resource_completed(source.relative_path)
                    if self.compact_logging:
                        self._safe_log_progress(
                            os.path.basename(source.relative_path),
                            completed_count,
                            len(all_files),
                        )
                    else:
                        self._safe_log(
                            get_localized(
                                "Console_Convertor_IncludedFiles_Unchanged"
                            ).format(path=source.relative_path)
                        )
                self._safe_progress(100)
                return
            planned_source_receipts = {
                receipt.logical_path: receipt
                for receipt in generation_match.source_receipts
            }

            source_byte_counts = self._preflight_included_source_byte_counts(
                tuple(all_files)
            )
            preflight_registry_content = render_included_file_registry(
                path_assignments,
                emitted_logical_paths,
                {
                    logical_path: (
                        source_byte_counts[logical_path],
                        _INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256,
                    )
                    for logical_path in emitted_logical_paths
                },
            ).encode("utf-8")
            assigned_byte_counts = {
                assignments_by_source[
                    source.relative_path
                ].assigned_output_path: source_byte_counts[
                    source.relative_path
                ]
                for source in all_files
            }
            recovery_record_sizes = (
                _preflight_included_recovery_record_sizes(
                    self.godot_project_path,
                    project_identity,
                    assigned_byte_counts,
                    preflight_registry_content,
                    previous_root_snapshot,
                    previous_registry_snapshot,
                )
            )
            publication_transaction_id = (
                secrets.token_hex(16)
                if len(planned_source_receipts) == len(all_files)
                and all(
                    source.relative_path in planned_source_receipts
                    for source in all_files
                )
                else None
            )

            (
                stage_container_path,
                stage_container_identity,
            ) = _create_included_output_stage(
                self.godot_project_path,
                project_identity,
            )
            staged_root_path = os.path.join(
                stage_container_path,
                _INCLUDED_FILES_ROOT_NAME,
            )
            os.mkdir(staged_root_path, 0o755)
            staged_root_identity = _included_directory_identity(staged_root_path)
            if staged_root_identity is None:
                raise OSError("Included Files staging root disappeared")

            self._active_output_project_path = stage_container_path
            successful_logical_paths: set[str] = set()
            copy_receipts: dict[str, _IncludedCopyReceipt] = {}
            worker_failed = False
            worker_cancelled = False
            first_worker_error: BaseException | None = None
            processed_files = 0
            total_files = len(all_files)
            try:
                def submit_copy(
                    executor: ThreadPoolExecutor,
                    source: _IncludedFileSource,
                ) -> Future[
                    tuple[str, bool, _IncludedCopyReceipt | None] | None
                ]:
                    assignment = assignments_by_source[source.relative_path]
                    staged_output_path = os.path.join(
                        staged_root_path,
                        *assignment.assigned_output_path.split("/"),
                    )
                    planned_receipt = planned_source_receipts.get(
                        source.relative_path
                    )
                    if planned_receipt is None:
                        return executor.submit(
                            self._process_file,
                            source.filesystem_path,
                            staged_output_path,
                            source.relative_path,
                            source.owner_source_path,
                        )
                    return executor.submit(
                        self._process_file,
                        source.filesystem_path,
                        staged_output_path,
                        source.relative_path,
                        source.owner_source_path,
                        planned_receipt,
                    )

                def consume_copy(
                    _source: _IncludedFileSource,
                    future: Future[
                        tuple[str, bool, _IncludedCopyReceipt | None] | None
                    ],
                ) -> bool:
                    nonlocal worker_failed
                    nonlocal worker_cancelled
                    nonlocal first_worker_error
                    nonlocal processed_files

                    try:
                        result = future.result()
                    except BaseException as error:
                        worker_failed = True
                        if first_worker_error is None:
                            first_worker_error = error
                        return False
                    if result is None:
                        worker_cancelled = True
                        return False

                    processed_files += 1
                    relative_path, copied, copy_receipt = result
                    if copied and copy_receipt is not None:
                        successful_logical_paths.add(relative_path)
                        copy_receipts[relative_path] = copy_receipt
                    else:
                        worker_failed = True
                    if total_files:
                        self._safe_progress(
                            min(
                                99,
                                int((processed_files / total_files) * 99),
                            )
                        )
                    return not worker_failed

                phase_completed = _run_bounded_included_worker_phase(
                    all_files,
                    max_workers=self.max_workers,
                    conversion_running=self.conversion_running,
                    submit=submit_copy,
                    consume=consume_copy,
                )
                if not phase_completed and not worker_failed:
                    worker_cancelled = True
            finally:
                self._active_output_project_path = None

            if worker_failed:
                for source in all_files:
                    self._resource_failed(source.relative_path)
                if first_worker_error is not None:
                    raise first_worker_error
                raise OSError(
                    "Included Files output-set staging failed; the previous "
                    "managed output was preserved"
                )
            if (
                worker_cancelled
                or not self.conversion_running()
                or len(successful_logical_paths) != len(all_files)
            ):
                for source in all_files:
                    self._resource_skipped(source.relative_path)
                self.log_callback(
                    get_localized("Console_Convertor_IncludedFiles_Stopped")
                )
                return

            generation_content_receipts = (
                tuple(
                    _IncludedGenerationContentReceipt(
                        transaction_id=publication_transaction_id,
                        generation_identity=staged_root_identity,
                        stage_container_identity=stage_container_identity,
                        source=planned_source_receipts[
                            source.relative_path
                        ],
                        staged_output_path=os.path.normcase(
                            os.path.abspath(
                                os.path.join(
                                    staged_root_path,
                                    *assignments_by_source[
                                        source.relative_path
                                    ].assigned_output_path.split("/"),
                                )
                            )
                        ),
                        public_output_path=os.path.normcase(
                            os.path.abspath(
                                os.path.join(
                                    public_root_path,
                                    *assignments_by_source[
                                        source.relative_path
                                    ].assigned_output_path.split("/"),
                                )
                            )
                        ),
                        output=copy_receipts[source.relative_path],
                    )
                    for source in all_files
                )
                if publication_transaction_id is not None
                else ()
            )
            if generation_content_receipts:
                if publication_transaction_id is None:
                    raise AssertionError(
                        "Generation receipts require a transaction id"
                    )
                staged_root_snapshot = (
                    _capture_included_tree_from_generation_receipts(
                        staged_root_path,
                        expected_parent_identity=stage_container_identity,
                        transaction_id=publication_transaction_id,
                        generation_identity=staged_root_identity,
                        stage_container_identity=stage_container_identity,
                        receipts=generation_content_receipts,
                    )
                )
            else:
                staged_root_snapshot = _capture_included_tree(
                    staged_root_path,
                    expected_parent_identity=stage_container_identity,
                )
            assigned_receipts = {
                assignments_by_source[source.relative_path].assigned_output_path:
                    copy_receipts[source.relative_path]
                for source in all_files
            }
            _verify_staged_included_inventory(
                staged_root_snapshot,
                assigned_receipts,
            )

            staged_registry_text = render_included_file_registry(
                path_assignments,
                emitted_logical_paths,
                {
                    logical_path: (
                        receipt.byte_count,
                        receipt.sha256,
                    )
                    for logical_path, receipt in copy_receipts.items()
                },
            )
            staged_registry_path = os.path.join(
                stage_container_path,
                "gml_included_file_registry.gd",
            )
            atomic_write_confined_generated_text(
                staged_registry_path,
                staged_registry_text,
                confinement_root=stage_container_path,
            )
            staged_registry_state = _included_regular_file_state(
                staged_registry_path,
                expected_parent_identity=stage_container_identity,
            )
            if staged_registry_state is None:
                raise OSError("Included File registry staging candidate disappeared")
            if previous_registry_snapshot.file_mode is not None:
                _chmod_exact_included_file(
                    staged_registry_path,
                    staged_registry_state[0],
                    previous_registry_snapshot.file_mode,
                    stage_container_identity,
                )
                staged_registry_state = _included_regular_file_state(
                    staged_registry_path,
                    expected_parent_identity=stage_container_identity,
                    allowed_identities=frozenset({staged_registry_state[0]}),
                )
                if staged_registry_state is None:
                    raise OSError(
                        "Included File registry staging candidate disappeared"
                    )
            staged_registry_identity, staged_registry_mode, staged_registry_content = (
                staged_registry_state
            )
            staged_container_snapshot = _included_stage_container_snapshot(
                project_identity,
                stage_container_path,
                stage_container_identity,
                staged_root_snapshot,
                staged_registry_identity,
                staged_registry_content,
            )

            transaction = _IncludedOutputSetTransaction(
                project_identity=project_identity,
                stage_container_path=stage_container_path,
                stage_container_identity=stage_container_identity,
                staged_container_snapshot=staged_container_snapshot,
                staged_root_path=staged_root_path,
                staged_root_snapshot=staged_root_snapshot,
                staged_registry_path=staged_registry_path,
                staged_registry_identity=staged_registry_identity,
                staged_registry_mode=staged_registry_mode,
                staged_registry_content=staged_registry_content,
                previous_root_snapshot=previous_root_snapshot,
                previous_registry_snapshot=previous_registry_snapshot,
                recovery_record_sizes=recovery_record_sizes,
                publication_transaction_id=publication_transaction_id,
                content_receipts=generation_content_receipts,
            )
            # From this handoff onward, only manifest-bound transaction
            # cleanup may remove the stage, including after rollback.
            transaction_cleanup_managed = True
            cleanup_warnings = _commit_included_output_set(
                self.godot_project_path,
                transaction,
                self.conversion_running,
            )
            transaction_committed = True
            for cleanup_warning in cleanup_warnings:
                self._safe_log(
                    "Warning: Included Files transaction cleanup failed: "
                    + cleanup_warning
                )

            for source in all_files:
                self._resource_completed(source.relative_path)
                if self.compact_logging:
                    self._safe_log_progress(
                        os.path.basename(source.relative_path),
                        len(successful_logical_paths),
                        len(all_files),
                    )
                else:
                    self._safe_log(
                        get_localized(
                            "Console_Convertor_IncludedFiles_Copied"
                        ).format(path=source.relative_path)
                    )
            self._safe_progress(100)
        except _IncludedOutputSetCancelled:
            for source in all_files:
                self._resource_skipped(source.relative_path)
            self.log_callback(
                get_localized("Console_Convertor_IncludedFiles_Stopped")
            )
            return
        except BaseException as error:
            active_error = error
            for source in all_files:
                self._resource_failed(source.relative_path)
            raise
        finally:
            self._active_output_project_path = None
            try:
                recovery_pending = os.path.lexists(
                    os.path.join(
                        self.godot_project_path,
                        _INCLUDED_FILES_JOURNAL_NAME,
                    )
                )
                if (
                    not transaction_cleanup_managed
                    and not recovery_pending
                    and stage_container_path is not None
                    and stage_container_identity is not None
                ):
                    try:
                        _remove_owned_included_tree(
                            stage_container_path,
                            stage_container_identity,
                            expected_parent_identity=project_identity,
                        )
                    except OSError as cleanup_error:
                        if active_error is not None:
                            active_error.add_note(
                                "Included Files staging cleanup also failed: "
                                + str(cleanup_error)
                            )
                        elif transaction_committed:
                            self._safe_log(
                                "Warning: Included Files staging cleanup failed: "
                                + str(cleanup_error)
                            )
                elif recovery_pending:
                    message = (
                        "Included Files recovery state was retained; the next "
                        "conversion will resume it"
                    )
                    if active_error is not None:
                        active_error.add_note(message)
                    else:
                        self._safe_log("Warning: " + message)
            finally:
                try:
                    _release_included_project_lock(project_lock)
                except OSError as lock_error:
                    if active_error is not None:
                        active_error.add_note(
                            "Included Files transaction lock release failed: "
                            + str(lock_error)
                        )
                    else:
                        self._safe_log(
                            "Warning: Included Files transaction lock release failed: "
                            + str(lock_error)
                        )

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_included_files()
