from __future__ import annotations

import ctypes
import hashlib
import os
import posixpath
import secrets
import stat
import sys
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import BinaryIO, Callable, cast

from src.localization import get_localized
from src.conversion.asset_registry import atomic_write_confined_generated_text
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
_INCLUDED_FILES_ROOT_NAME = "included_files"
_INCLUDED_FILES_STAGE_PREFIX = ".gm2godot-included-files-"


@dataclass(frozen=True)
class _IncludedCopyReceipt:
    source_fingerprint: _IncludedSourceFingerprint
    byte_count: int
    sha256: str


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
class _IncludedRegistrySnapshot:
    directory_identity: _PathIdentity | None
    file_identity: _PathIdentity | None
    file_mode: int | None
    content: bytes | None


@dataclass(frozen=True)
class _IncludedOutputSetTransaction:
    project_identity: _PathIdentity
    stage_container_path: str
    stage_container_identity: _PathIdentity
    staged_root_path: str
    staged_root_snapshot: _IncludedTreeSnapshot
    staged_registry_path: str
    staged_registry_identity: _PathIdentity
    staged_registry_content: bytes
    previous_root_snapshot: _IncludedTreeSnapshot
    previous_registry_snapshot: _IncludedRegistrySnapshot


class _IncludedOutputSetCancelled(Exception):
    """Signal cancellation while a reversible output-set commit is active."""


_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


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


def _digest_open_included_file(
    opened_file: BinaryIO,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = opened_file.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        byte_count += len(chunk)
    return byte_count, digest.hexdigest()


def _digest_included_regular_file(
    path: str,
    expected_stat: os.stat_result,
) -> str:
    expected_fingerprint = _included_path_fingerprint(expected_stat)
    expected_binding = _included_path_handle_binding(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_path_handle_binding(opened_stat) != expected_binding
        ):
            raise OSError(f"Included Files file changed before hashing: {path}")
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
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
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


def _open_included_tree_directory_at(parent_fd: int, name: str) -> int:
    return os.open(
        name,
        _DIRECTORY_OPEN_FLAGS,
        dir_fd=parent_fd,
    )


def _capture_included_tree_from_fd(
    directory_fd: int,
    relative_directory: str,
    display_path: str,
    verify_binding: Callable[[], None],
) -> list[_IncludedTreeEntry]:
    verify_binding()
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as error:
        raise OSError(
            f"Could not inspect Included Files directory: {display_path}"
        ) from error
    entries: list[_IncludedTreeEntry] = []
    for name in names:
        verify_binding()
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

                def verify_child_binding() -> None:
                    verify_binding()
                    _verify_included_entry_at(
                        directory_fd,
                        name,
                        entry_fingerprint,
                        entry_path,
                    )

                entries.extend(
                    _capture_included_tree_from_fd(
                        child_fd,
                        relative_path,
                        entry_path,
                        verify_child_binding,
                    )
                )
            finally:
                os.close(child_fd)
            verify_binding()
            _verify_included_entry_at(
                directory_fd,
                name,
                entry_fingerprint,
                entry_path,
            )
            kind = "directory"
            ctime_ns = None
            content_sha256 = None
        elif stat.S_ISREG(entry_stat.st_mode):
            kind = "file"
            ctime_ns = entry_stat.st_ctime_ns
            content_sha256 = _digest_included_regular_file_at(
                directory_fd,
                name,
                entry_stat,
                entry_path,
            )
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
    verify_binding()
    return entries


def _capture_included_tree_descriptor(
    root_path: str,
    expected_parent_identity: _PathIdentity | None,
) -> _IncludedTreeSnapshot:
    parent_fd, root_name = _open_pinned_included_parent(root_path)
    parent_identity = _directory_identity_from_fd(parent_fd)
    if (
        expected_parent_identity is not None
        and parent_identity != expected_parent_identity
    ):
        os.close(parent_fd)
        raise OSError(f"Included Files root parent changed: {root_path}")
    parent_path = os.path.dirname(os.path.abspath(root_path))
    try:
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

            def verify_root_binding() -> None:
                _verify_included_entry_at(
                    parent_fd,
                    root_name,
                    root_fingerprint,
                    root_path,
                )

            entries = _capture_included_tree_from_fd(
                root_fd,
                "",
                root_path,
                verify_root_binding,
            )
        finally:
            os.close(root_fd)
        verify_root_binding()
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
) -> _IncludedTreeSnapshot:
    root_parent_identities = _capture_fallback_directory_ancestors(
        os.path.dirname(os.path.abspath(root_path))
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
    entries: list[_IncludedTreeEntry] = []
    pending: list[tuple[str, str]] = [("", root_path)]
    while pending:
        relative_directory, directory_path = pending.pop()
        directory_identities = _capture_fallback_directory_ancestors(
            directory_path
        )
        _verify_fallback_directory_ancestors(directory_identities)
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
        _verify_fallback_directory_ancestors(directory_identities)
        for directory_entry in directory_entries:
            _verify_fallback_directory_ancestors(directory_identities)
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
                kind = "directory"
                ctime_ns = None
                content_sha256 = None
                pending.append((relative_path, entry_path))
            elif stat.S_ISREG(entry_stat.st_mode):
                kind = "file"
                ctime_ns = entry_stat.st_ctime_ns
                _verify_fallback_directory_ancestors(directory_identities)
                content_sha256 = _digest_included_regular_file(
                    entry_path,
                    entry_stat,
                )
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
            _verify_fallback_directory_ancestors(directory_identities)
        _verify_fallback_directory_ancestors(directory_identities)

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
) -> _IncludedTreeSnapshot:
    if _included_descriptor_paths_supported():
        return _capture_included_tree_descriptor(
            root_path,
            expected_parent_identity,
        )
    return _capture_included_tree_fallback(
        root_path,
        expected_parent_identity,
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
    if _included_directory_identity(stage_path) != stage_identity:
        raise OSError("Included Files staging directory changed during conversion")
    _verify_included_project_identity(project_path, project_identity)


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
            return os.path.join(project_path, stage_name), stage_identity
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

    stage_path = tempfile.mkdtemp(
        dir=project_path,
        prefix=_INCLUDED_FILES_STAGE_PREFIX,
        suffix=".stage",
    )
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
            quarantined_name, quarantined_path = _quarantine_included_entry_at(
                directory_fd,
                name,
                entry_identity,
                expect_directory=True,
                display_path=entry_path,
            )
            child_fd = os.open(
                quarantined_name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=directory_fd,
            )
            try:
                if _directory_identity_from_fd(child_fd) != entry_identity:
                    raise OSError(
                        f"Included Files cleanup directory changed: {entry_path}"
                    )

                def verify_child_binding() -> None:
                    verify_binding()
                    _verify_included_directory_entry_identity_at(
                        directory_fd,
                        quarantined_name,
                        entry_identity,
                        quarantined_path,
                    )

                _remove_included_tree_contents_at(
                    child_fd,
                    quarantined_path,
                    verify_child_binding,
                )
            finally:
                os.close(child_fd)
            verify_child_binding()
            _rmdir_exact_quarantined_entry_at(
                directory_fd,
                quarantined_name,
                entry_identity,
                quarantined_path,
            )
        else:
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
    os.unlink(path)


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
    os.rmdir(path)


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
        _verify_included_directory_fd(
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
        quarantined_name, quarantined_path = _quarantine_included_entry_at(
            parent_fd,
            name,
            expected_identity,
            expect_directory=True,
            display_path=path,
        )
        root_fd = os.open(
            quarantined_name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_fd,
        )
        try:
            if _directory_identity_from_fd(root_fd) != expected_identity:
                raise OSError(
                    f"Refusing to remove changed Included Files tree: {path}"
                )

            def verify_root_binding() -> None:
                _verify_included_directory_entry_identity_at(
                    parent_fd,
                    quarantined_name,
                    expected_identity,
                    quarantined_path,
                )

            _remove_included_tree_contents_at(
                root_fd,
                quarantined_path,
                verify_root_binding,
            )
        finally:
            os.close(root_fd)
        verify_root_binding()
        _rmdir_exact_quarantined_entry_at(
            parent_fd,
            quarantined_name,
            expected_identity,
            quarantined_path,
        )
    finally:
        os.close(parent_fd)


def _remove_owned_included_file(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    if _included_descriptor_paths_supported():
        parent_fd, name = _open_pinned_included_parent(path)
        try:
            _verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                parent_path,
            )
            file_stat = _included_entry_stat_at(parent_fd, name)
            if file_stat is None:
                return
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or (file_stat.st_dev, file_stat.st_ino) != expected_identity
            ):
                raise OSError(
                    f"Refusing to remove changed Included Files file: {path}"
                )
            quarantined_name, quarantined_path = _quarantine_included_entry_at(
                parent_fd,
                name,
                expected_identity,
                expect_directory=False,
                display_path=path,
            )
            file_descriptor = os.open(
                quarantined_name,
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
                    raise OSError(
                        f"Refusing to remove changed Included Files file: {path}"
                    )
                current_stat = _included_entry_stat_at(
                    parent_fd,
                    quarantined_name,
                )
                if (
                    current_stat is None
                    or (current_stat.st_dev, current_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(
                        f"Refusing to remove changed Included Files file: {path}"
                    )
                _unlink_exact_quarantined_entry_at(
                    parent_fd,
                    quarantined_name,
                    expected_identity,
                    quarantined_path,
                )
            finally:
                os.close(file_descriptor)
        finally:
            os.close(parent_fd)
        return

    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if (
        expected_parent_identity is not None
        and parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup parent changed: {parent_path}")
    try:
        file_stat = os.lstat(path)
    except FileNotFoundError:
        _verify_fallback_directory_ancestors(parent_identities)
        return
    if (
        _included_output_path_is_redirected(path, file_stat)
        or not stat.S_ISREG(file_stat.st_mode)
        or (file_stat.st_dev, file_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Refusing to remove changed Included Files file: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    quarantined_path = _quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=False,
    )
    _unlink_exact_quarantined_entry_fallback(
        quarantined_path,
        expected_identity,
    )


def _remove_owned_empty_included_directory(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    if _included_descriptor_paths_supported():
        parent_fd, name = _open_pinned_included_parent(path)
        try:
            _verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                parent_path,
            )
            _verify_included_directory_entry_identity_at(
                parent_fd,
                name,
                expected_identity,
                path,
            )
            quarantined_name, quarantined_path = _quarantine_included_entry_at(
                parent_fd,
                name,
                expected_identity,
                expect_directory=True,
                display_path=path,
            )
            _rmdir_exact_quarantined_entry_at(
                parent_fd,
                quarantined_name,
                expected_identity,
                quarantined_path,
            )
        finally:
            os.close(parent_fd)
        return
    parent_identities = _capture_fallback_directory_ancestors(parent_path)
    if parent_identities[-1][1] != expected_parent_identity:
        raise OSError(f"Included Files directory parent changed: {parent_path}")
    current_identity = _included_directory_identity(path)
    if current_identity != expected_identity:
        raise OSError(f"Included Files directory changed: {path}")
    _verify_fallback_directory_ancestors(parent_identities)
    quarantined_path = _quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=True,
    )
    _rmdir_exact_quarantined_entry_fallback(
        quarantined_path,
        expected_identity,
    )


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
    os.rename(source, destination)


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
        final_registry_parent_identity = (
            registry_directory_identity
            if registry_directory_identity is not None
            else previous_registry_directory_identity
        )
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
            if backup_registry_identity is not None:
                raise OSError("Included File registry rollback left a duplicate backup")
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
        backup_root_identity = _included_directory_identity(root_backup_path)
        previous_root_identity = transaction.previous_root_snapshot.identity
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
            if backup_root_identity is not None:
                raise OSError("Included Files rollback left a duplicate root backup")
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
            _remove_owned_empty_included_directory(
                registry_directory_path,
                registry_directory_identity,
                transaction.project_identity,
            )
        except Exception as error:
            errors.append(error)
    return tuple(errors)


def _commit_included_output_set(
    project_path: str,
    transaction: _IncludedOutputSetTransaction,
    conversion_running: ConversionRunning,
) -> tuple[str, ...]:
    """Publish one rollback-protected root/registry generation.

    The two public paths require separate renames, so ordinary conversion is
    not a synchronization mechanism for concurrent readers. A process crash
    between those renames also requires a future persistent recovery journal;
    this transaction only guarantees rollback for failures observed in-process.
    Cleanup and publication also assume no non-cooperating process mutates this
    managed namespace: portable inode-conditional rename/unlink primitives do
    not exist. Issue #727 owns the locking/generation-pointer redesign.
    """
    final_root_path = os.path.join(project_path, _INCLUDED_FILES_ROOT_NAME)
    final_registry_path = _included_registry_path(project_path)
    root_backup_path = _unique_included_transaction_path(
        project_path,
        "included_files",
    )
    registry_directory_path = os.path.dirname(final_registry_path)
    registry_backup_path = _unique_included_transaction_path(
        registry_directory_path
        if transaction.previous_registry_snapshot.directory_identity is not None
        else project_path,
        "gml_included_file_registry.gd",
    )
    registry_directory_identity: _PathIdentity | None = None
    registry_directory_created = False

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

        (
            registry_directory_path,
            registry_directory_identity,
            registry_directory_created,
        ) = _prepare_included_registry_directory(
            project_path,
            transaction.previous_registry_snapshot,
            transaction.project_identity,
        )
        if transaction.previous_registry_snapshot.file_mode is not None:
            _chmod_exact_included_file(
                transaction.staged_registry_path,
                transaction.staged_registry_identity,
                transaction.previous_registry_snapshot.file_mode,
                transaction.stage_container_identity,
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

        previous_root_identity = transaction.previous_root_snapshot.identity
        if previous_root_identity is not None:
            _move_exact_included_directory(
                final_root_path,
                root_backup_path,
                previous_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.project_identity,
            )
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
        _verify_included_tree_snapshot(
            final_root_path,
            transaction.staged_root_snapshot,
            expected_parent_identity=transaction.project_identity,
        )
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        previous_registry_identity = (
            transaction.previous_registry_snapshot.file_identity
        )
        if previous_registry_identity is not None:
            registry_backup_path = _unique_included_transaction_path(
                registry_directory_path,
                "gml_included_file_registry.gd",
            )
            _move_exact_included_file(
                final_registry_path,
                registry_backup_path,
                previous_registry_identity,
                source_parent_identity=registry_directory_identity,
                destination_parent_identity=registry_directory_identity,
            )
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        _move_exact_included_file(
            transaction.staged_registry_path,
            final_registry_path,
            transaction.staged_registry_identity,
            source_parent_identity=transaction.stage_container_identity,
            destination_parent_identity=registry_directory_identity,
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
        if not conversion_running():
            raise _IncludedOutputSetCancelled()
        _verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
    except BaseException as error:
        rollback_errors = _rollback_included_output_set(
            transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        if rollback_errors:
            error.add_note(
                "Included Files rollback also failed: "
                + "; ".join(str(rollback_error) for rollback_error in rollback_errors)
            )
        raise

    cleanup_errors: list[str] = []
    previous_root_identity = transaction.previous_root_snapshot.identity
    if previous_root_identity is not None:
        try:
            _remove_owned_included_tree(
                root_backup_path,
                previous_root_identity,
                expected_parent_identity=transaction.project_identity,
            )
        except OSError as error:
            cleanup_errors.append(str(error))
    previous_registry_identity = transaction.previous_registry_snapshot.file_identity
    if previous_registry_identity is not None:
        try:
            _remove_owned_included_file(
                registry_backup_path,
                previous_registry_identity,
                expected_parent_identity=registry_directory_identity,
            )
        except OSError as error:
            cleanup_errors.append(str(error))
    return tuple(cleanup_errors)


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
) -> _IncludedCopyReceipt:
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
    return _IncludedCopyReceipt(
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
            copy_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
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
            copy_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
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
) -> _IncludedCopyReceipt:
    components = _included_output_components(project_path, output_path)
    _ensure_included_output_project_root(project_path)
    if _confined_included_output_supported():
        return _publish_included_output_at(
            project_path,
            components,
            source_file,
            source_stat,
        )
    return _publish_included_output_fallback(
        project_path,
        components,
        source_file,
        source_stat,
    )


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
                    copy_receipt = _publish_confined_included_output(
                        self._active_output_project_path
                        or self.godot_project_path,
                        godot_file_path,
                        source_file,
                        source_stat,
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
            source_file = open(resolved.filesystem_path, "rb")
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

        project_identity = _ensure_included_output_project_root(
            self.godot_project_path
        )
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
        try:
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
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures_map: dict[
                        Future[
                            tuple[
                                str,
                                bool,
                                _IncludedCopyReceipt | None,
                            ]
                            | None
                        ],
                        str,
                    ] = {}
                    for source in all_files:
                        assignment = assignments_by_source[source.relative_path]
                        staged_output_path = os.path.join(
                            staged_root_path,
                            *assignment.assigned_output_path.split("/"),
                        )
                        future = executor.submit(
                            self._process_file,
                            source.filesystem_path,
                            staged_output_path,
                            source.relative_path,
                            source.owner_source_path,
                        )
                        futures_map[future] = source.relative_path

                    for future in as_completed(futures_map):
                        try:
                            result = future.result()
                        except BaseException as error:
                            worker_failed = True
                            if first_worker_error is None:
                                first_worker_error = error
                            continue
                        if result is None:
                            worker_cancelled = True
                            continue
                        processed_files += 1
                        relative_path, copied, copy_receipt = result
                        if copied:
                            if copy_receipt is None:
                                worker_failed = True
                                continue
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

            emitted_logical_paths = {
                source.relative_path for source in all_files
            }
            staged_registry_text = render_included_file_registry(
                path_assignments,
                emitted_logical_paths,
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
            staged_registry_identity, _staged_mode, staged_registry_content = (
                staged_registry_state
            )

            transaction = _IncludedOutputSetTransaction(
                project_identity=project_identity,
                stage_container_path=stage_container_path,
                stage_container_identity=stage_container_identity,
                staged_root_path=staged_root_path,
                staged_root_snapshot=staged_root_snapshot,
                staged_registry_path=staged_registry_path,
                staged_registry_identity=staged_registry_identity,
                staged_registry_content=staged_registry_content,
                previous_root_snapshot=previous_root_snapshot,
                previous_registry_snapshot=previous_registry_snapshot,
            )
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
            if (
                stage_container_path is not None
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

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_included_files()
