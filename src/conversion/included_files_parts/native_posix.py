from __future__ import annotations

import ctypes
import os
import stat
import sys
from typing import Callable, cast

from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity

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
    if not included_descriptor_paths_supported():
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

def _open_pinned_included_parent(path: str) -> tuple[int, str]:
    absolute_path = os.path.abspath(path)
    parent_path, name = os.path.split(absolute_path)
    if not name:
        raise OSError(f"Included Files path has no movable leaf: {path}")
    return open_pinned_included_directory(parent_path), name

def _rename_included_transaction_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    if not included_native_noreplace_available():
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
    directory_fd = os.open(path, DIRECTORY_OPEN_FLAGS)
    try:
        if _included_metadata.directory_identity_from_fd(directory_fd) != expected_identity:
            raise OSError(f"Included Files directory changed: {path}")
        return included_linux_mount_id_from_fd(directory_fd)
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
    current_mount_id = included_linux_mount_id_from_fd(opened_descriptor)
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
        return verify_included_mount_boundary(
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
        return verify_included_mount_boundary(
            path,
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
        DIRECTORY_OPEN_FLAGS,
        dir_fd=parent_fd,
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
    directory_fd = open_pinned_included_directory(path)
    try:
        _included_metadata.verify_included_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
        os.fsync(directory_fd)
        _included_metadata.verify_included_directory_fd(
            directory_fd,
            expected_identity,
            path,
        )
    finally:
        os.close(directory_fd)

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


# Finite live owner exports; one actual native definition each.
DIRECTORY_OPEN_FLAGS = _DIRECTORY_OPEN_FLAGS
included_descriptor_paths_supported = _included_descriptor_paths_supported
included_native_noreplace_available = _included_native_noreplace_available
open_pinned_included_directory = _open_pinned_included_directory
open_pinned_included_parent = _open_pinned_included_parent
rename_included_transaction_entry_at = _rename_included_transaction_entry_at
included_linux_mount_id_from_fd = _included_linux_mount_id_from_fd
included_directory_mount_id = _included_directory_mount_id
verify_included_mount_boundary = _verify_included_mount_boundary
verify_included_mount_boundary_path = _verify_included_mount_boundary_path
open_included_tree_directory_at = _open_included_tree_directory_at
sync_included_directory = _sync_included_directory
confined_included_output_supported = _confined_included_output_supported
open_or_create_included_output_directory = _open_or_create_included_output_directory
apply_included_output_metadata = _apply_included_output_metadata
