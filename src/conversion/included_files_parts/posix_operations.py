"""Descriptor-relative Included Files operations with explicit descriptor ownership."""

from __future__ import annotations

import ctypes
import os
import secrets
import stat
import sys
from typing import Callable, cast

from src.conversion.included_files_parts.filesystem_metadata import path_fingerprint
from src.conversion.included_files_parts.models import PathFingerprint, PathIdentity

DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def descriptor_paths_supported() -> bool:
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


def native_noreplace_available() -> bool:
    return sys.platform == "darwin" or sys.platform.startswith("linux")


def open_pinned_directory(path: str) -> int:
    if not descriptor_paths_supported():
        raise OSError("Descriptor-pinned Included Files paths are unavailable")
    absolute_path = os.path.abspath(path)
    components = [
        component for component in absolute_path.split(os.sep) if component
    ]
    if not components:
        return os.open(os.sep, DIRECTORY_OPEN_FLAGS)
    platform_anchor = os.path.join(os.sep, components[0])
    resolved_anchor = os.path.realpath(platform_anchor)
    current_fd = os.open(resolved_anchor, DIRECTORY_OPEN_FLAGS)
    try:
        for component in components[1:]:
            child_fd = os.open(
                component,
                DIRECTORY_OPEN_FLAGS,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def open_pinned_parent(path: str) -> tuple[int, str]:
    absolute_path = os.path.abspath(path)
    parent_path, name = os.path.split(absolute_path)
    if not name:
        raise OSError(f"Included Files path has no movable leaf: {path}")
    return open_pinned_directory(parent_path), name


def directory_identity_from_fd(directory_fd: int) -> PathIdentity:
    directory_stat = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OSError("Pinned Included Files descriptor is not a directory")
    return directory_stat.st_dev, directory_stat.st_ino


def verify_directory_fd(
    directory_fd: int,
    expected_identity: PathIdentity | None,
    display_path: str,
) -> PathIdentity:
    current_identity = directory_identity_from_fd(directory_fd)
    if expected_identity is not None and current_identity != expected_identity:
        raise OSError(f"Included Files directory changed: {display_path}")
    return current_identity


def entry_stat_at(
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


def verify_entry_at(
    parent_fd: int,
    name: str,
    expected_fingerprint: PathFingerprint,
    display_path: str,
) -> None:
    current_stat = entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or path_fingerprint(current_stat) != expected_fingerprint
    ):
        raise OSError(f"Included Files entry changed: {display_path}")


def rename_transaction_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    if not native_noreplace_available():
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


def preserve_or_restore_unexpected_moved_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    source_display_path: str,
    destination_display_path: str,
) -> OSError:
    try:
        rename_transaction_entry_at(
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
            rename_transaction_entry_at(
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


def linux_mount_id_from_fd(file_descriptor: int) -> int | None:
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


def directory_mount_id(
    path: str,
    expected_identity: PathIdentity,
) -> int | None:
    """Read a directory mount ID without following a redirected leaf."""

    if not sys.platform.startswith("linux"):
        return None
    directory_fd = os.open(path, DIRECTORY_OPEN_FLAGS)
    try:
        if directory_identity_from_fd(directory_fd) != expected_identity:
            raise OSError(f"Included Files directory changed: {path}")
        return linux_mount_id_from_fd(directory_fd)
    finally:
        os.close(directory_fd)


def verify_mount_boundary(
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
    current_mount_id = linux_mount_id_from_fd(opened_descriptor)
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


def verify_mount_boundary_path(
    path: str,
    entry_stat: os.stat_result,
    expected_device: int,
    expected_mount_id: int | None,
    *,
    expect_directory: bool,
) -> int | None:
    """Path fallback for mount checks, using an fd on Linux when available."""

    if not sys.platform.startswith("linux"):
        return verify_mount_boundary(
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
        return verify_mount_boundary(
            path,
            opened_stat,
            expected_device,
            expected_mount_id,
            file_descriptor,
        )
    finally:
        os.close(file_descriptor)


def verify_directory_entry_identity_at(
    parent_fd: int,
    name: str,
    expected_identity: PathIdentity,
    display_path: str,
) -> None:
    current_stat = entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files directory changed: {display_path}")


def sync_directory(
    path: str,
    expected_identity: PathIdentity,
) -> None:
    """Make prior namespace changes durable where Python exposes directory fsync."""

    if os.name == "nt":
        # Windows transaction renames use MoveFileExW with
        # MOVEFILE_WRITE_THROUGH instead.
        return
    directory_fd = open_pinned_directory(path)
    try:
        verify_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
        os.fsync(directory_fd)
        verify_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
    finally:
        os.close(directory_fd)
