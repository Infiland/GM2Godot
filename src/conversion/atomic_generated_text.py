from __future__ import annotations

import ctypes
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, TextIO, cast


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    """Return whether a path is a symbolic link or Windows junction."""
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _asset_output_components(root: str, output_path: str) -> tuple[str, ...]:
    try:
        contained = os.path.commonpath((root, output_path)) == root
    except ValueError:
        contained = False
    relative_path = os.path.relpath(output_path, root) if contained else os.pardir
    components = tuple(relative_path.split(os.sep))
    if (
        not contained
        or os.path.isabs(relative_path)
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise ValueError(
            f"Generated asset output escapes its confinement root: {output_path}"
        )
    return components


def _ensure_asset_output_root(root: str) -> tuple[int, int]:
    os.makedirs(root, exist_ok=True)
    root_stat = os.lstat(root)
    if _path_is_redirected(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise OSError(
            f"Refusing redirected asset-registry output directory: {root}"
        )
    return (root_stat.st_dev, root_stat.st_ino)


def _confined_asset_output_supported() -> bool:
    return (
        os.name != "nt"
        and os.chmod in os.supports_fd
        and all(
            operation in os.supports_dir_fd
            for operation in (os.open, os.mkdir, os.stat, os.rename, os.unlink)
        )
    )


def _atomic_write_asset_text_at(
    root: str,
    components: tuple[str, ...],
    content: str,
    publication_validator: Callable[[], None] | None = None,
) -> None:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(root, directory_flags)
    current_fd = root_fd
    try:
        _verify_open_asset_output_directory(root, root, root_fd)
        for component in components[:-1]:
            child_fd = _open_or_create_asset_output_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(root, *components[:-1])
        _verify_open_asset_output_directory(root, output_directory, current_fd)
        _atomic_write_asset_text_in_directory(
            current_fd,
            components[-1],
            content,
            publication_validator,
        )
        _verify_open_asset_output_directory(root, output_directory, current_fd)
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _open_or_create_asset_output_directory(
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
        return os.open(component, flags, dir_fd=parent_fd)
    except OSError as error:
        raise OSError(
            f"Refusing redirected asset-registry output directory: {component}"
        ) from error


def _verify_open_asset_output_directory(
    root: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Asset-registry output directory changed: {directory_path}"
        ) from error
    root_real = os.path.realpath(root)
    directory_real = os.path.realpath(directory_path)
    try:
        contained = os.path.commonpath((directory_real, root_real)) == root_real
    except ValueError:
        contained = False
    if (
        _path_is_redirected(directory_path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected asset-registry output directory: {directory_path}"
        )


def _asset_output_state_at(
    directory_fd: int,
    filename: str,
) -> tuple[tuple[int, int] | None, int | None]:
    try:
        output_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(f"Refusing to replace non-regular asset registry: {filename}")
    return (
        (output_stat.st_dev, output_stat.st_ino),
        stat.S_IMODE(output_stat.st_mode),
    )


def _verify_asset_output_state_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity, _mode = _asset_output_state_at(directory_fd, filename)
    if current_identity != expected_identity:
        raise OSError(f"Asset registry changed during publication: {filename}")


def _sync_generated_asset_stage(staged_file: TextIO) -> None:
    staged_file.flush()
    os.fsync(staged_file.fileno())


_WINDOWS_DELETE_ACCESS = 0x00010000
_WINDOWS_FILE_READ_ATTRIBUTES = 0x00000080
_WINDOWS_FILE_WRITE_ATTRIBUTES = 0x00000100
_WINDOWS_FILE_TRAVERSE = 0x00000020
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_FILE_SHARE_WRITE = 0x00000002
_WINDOWS_FILE_SHARE_DELETE = 0x00000004
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_FILE_ATTRIBUTE_READONLY = 0x00000001
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_FILE_TYPE_DISK = 1
_WINDOWS_FILE_BASIC_INFO_CLASS = 0
_WINDOWS_FILE_STANDARD_INFO_CLASS = 1
_WINDOWS_FILE_RENAME_INFO_CLASS = 3
_WINDOWS_FILE_DISPOSITION_INFO_CLASS = 4
_WINDOWS_FILE_ID_INFO_CLASS = 18
_WINDOWS_FILE_DISPOSITION_INFO_EX_CLASS = 21
_WINDOWS_FILE_DISPOSITION_DELETE = 0x00000001
_WINDOWS_FILE_DISPOSITION_POSIX_SEMANTICS = 0x00000002
_WINDOWS_FILE_DISPOSITION_IGNORE_READONLY = 0x00000010
_WINDOWS_UNSUPPORTED_DISPOSITION_ERRORS = frozenset({1, 50, 87, 120})


class _WindowsFileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_uint8 * 16),)


class _WindowsFileIdInfo(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", _WindowsFileId128),
    )


class _WindowsFileBasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )


class _WindowsFileStandardInfo(ctypes.Structure):
    _fields_ = (
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_uint32),
        ("DeletePending", ctypes.c_uint8),
        ("Directory", ctypes.c_uint8),
    )


class _WindowsFileDispositionInfoEx(ctypes.Structure):
    _fields_ = (("Flags", ctypes.c_uint32),)


class _WindowsFileDispositionInfo(ctypes.Structure):
    _fields_ = (("DeleteFile", ctypes.c_uint8),)


class _WindowsFileRenameUnion(ctypes.Union):
    _fields_ = (
        ("ReplaceIfExists", ctypes.c_uint8),
        ("Flags", ctypes.c_uint32),
    )


class _WindowsFileRenameInfo(ctypes.Structure):
    _fields_ = (
        ("Operation", _WindowsFileRenameUnion),
        ("RootDirectory", ctypes.c_void_p),
        ("FileNameLength", ctypes.c_uint32),
        ("FileName", ctypes.c_uint16 * 1),
    )


@lru_cache(maxsize=1)
def _windows_asset_file_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows generated-asset file APIs are unavailable")
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    expected_rename_offsets = (8, 16, 20) if pointer_size == 8 else (4, 8, 12)
    expected_rename_size = 24 if pointer_size == 8 else 16
    if (
        ctypes.sizeof(_WindowsFileId128) != 16
        or ctypes.sizeof(_WindowsFileIdInfo) != 24
        or _WindowsFileIdInfo.FileId.offset != 8
        or ctypes.sizeof(_WindowsFileBasicInfo) != 40
        or _WindowsFileBasicInfo.FileAttributes.offset != 32
        or ctypes.sizeof(_WindowsFileStandardInfo) != 24
        or _WindowsFileStandardInfo.NumberOfLinks.offset != 16
        or ctypes.sizeof(_WindowsFileDispositionInfo) != 1
        or ctypes.sizeof(_WindowsFileDispositionInfoEx) != 4
        or ctypes.sizeof(_WindowsFileRenameInfo) != expected_rename_size
        or (
            _WindowsFileRenameInfo.RootDirectory.offset,
            _WindowsFileRenameInfo.FileNameLength.offset,
            _WindowsFileRenameInfo.FileName.offset,
        )
        != expected_rename_offsets
    ):
        raise OSError("Unsupported Windows generated-asset ABI layout")
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
    kernel32.GetFileInformationByHandleEx.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    kernel32.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel32.SetFileInformationByHandle.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    kernel32.SetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFileType.argtypes = (ctypes.c_void_p,)
    kernel32.GetFileType.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def _windows_asset_api_error_from_code(
    operation: str,
    path: str,
    error_number: int,
) -> OSError:
    format_error = cast(Callable[[int], str], getattr(ctypes, "FormatError"))
    return OSError(
        error_number,
        f"{operation}: {format_error(error_number).strip()}",
        path,
    )


def _windows_asset_api_error(operation: str, path: str) -> OSError:
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    return _windows_asset_api_error_from_code(
        operation,
        path,
        get_last_error(),
    )


def _windows_asset_handle_identity(
    kernel32: Any,
    handle: int,
    path: str,
) -> tuple[int, int]:
    identity_info = _WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise _windows_asset_api_error(
            "Could not identify generated asset transaction handle",
            path,
        )
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )


def _windows_asset_standard_info(
    kernel32: Any,
    handle: int,
    path: str,
) -> _WindowsFileStandardInfo:
    standard_info = _WindowsFileStandardInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_STANDARD_INFO_CLASS,
        ctypes.byref(standard_info),
        ctypes.sizeof(standard_info),
    ):
        raise _windows_asset_api_error(
            "Could not inspect generated asset link count",
            path,
        )
    return standard_info


def _windows_asset_handle_link_count(
    kernel32: Any,
    handle: int,
    path: str,
) -> int:
    standard_info = _windows_asset_standard_info(kernel32, handle, path)
    link_count = int(standard_info.NumberOfLinks)
    if link_count < 1:
        raise OSError(
            f"Generated asset transaction handle has no links: {path}"
        )
    return link_count


def _open_exact_windows_asset_file(
    path: str,
    expected_identity: tuple[int, int],
    *,
    desired_access: int,
    share_mode: int | None = None,
) -> tuple[Any, int]:
    kernel32 = _windows_asset_file_api()
    path_stat = os.lstat(path)
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Generated asset transaction file changed: {path}")
    if share_mode is None:
        share_mode = (
            _WINDOWS_FILE_SHARE_READ
            | _WINDOWS_FILE_SHARE_WRITE
            | _WINDOWS_FILE_SHARE_DELETE
        )
    handle = kernel32.CreateFileW(
        path,
        desired_access,
        share_mode,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise _windows_asset_api_error(
            "Could not bind generated asset transaction file",
            path,
        )
    handle_value = cast(int, handle)
    try:
        file_attributes = int(
            _windows_asset_basic_info(
                kernel32,
                handle_value,
                path,
            ).FileAttributes
        )
        if (
            kernel32.GetFileType(handle_value) != _WINDOWS_FILE_TYPE_DISK
            or not stat.S_ISREG(path_stat.st_mode)
            or _windows_asset_handle_identity(
                kernel32,
                handle_value,
                path,
            )
            != expected_identity
            or file_attributes
            & (
                _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                | _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
            )
        ):
            raise OSError(
                f"Generated asset transaction file changed: {path}"
            )
        if share_mode & _WINDOWS_FILE_SHARE_DELETE:
            current_stat = os.lstat(path)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or (current_stat.st_dev, current_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Generated asset transaction file changed: {path}"
                )
    except BaseException as error:
        try:
            _close_windows_asset_handle(kernel32, handle_value, path)
        except OSError as close_error:
            error.add_note(
                "Could not close rejected generated asset file handle: "
                f"{close_error}"
            )
        raise
    return kernel32, handle_value


def _open_exact_windows_asset_directory(
    path: str,
    expected_identity: tuple[int, int],
) -> tuple[Any, int]:
    kernel32 = _windows_asset_file_api()
    handle = kernel32.CreateFileW(
        path,
        _WINDOWS_FILE_TRAVERSE | _WINDOWS_FILE_READ_ATTRIBUTES,
        (
            _WINDOWS_FILE_SHARE_READ
            | _WINDOWS_FILE_SHARE_WRITE
        ),
        None,
        _WINDOWS_OPEN_EXISTING,
        (
            _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
            | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
        ),
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise _windows_asset_api_error(
            "Could not bind generated asset transaction directory",
            path,
        )
    handle_value = cast(int, handle)
    try:
        path_stat = os.lstat(path)
        attributes = int(
            _windows_asset_basic_info(
                kernel32,
                handle_value,
                path,
            ).FileAttributes
        )
        if (
            kernel32.GetFileType(handle_value) != _WINDOWS_FILE_TYPE_DISK
            or not stat.S_ISDIR(path_stat.st_mode)
            or _windows_asset_handle_identity(
                kernel32,
                handle_value,
                path,
            )
            != expected_identity
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
            or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
            or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError(
                f"Generated asset transaction directory changed: {path}"
            )
    except BaseException as error:
        try:
            _close_windows_asset_handle(kernel32, handle_value, path)
        except OSError as close_error:
            error.add_note(
                "Could not close rejected generated asset directory handle: "
                f"{close_error}"
            )
        raise
    return kernel32, handle_value


def _close_windows_asset_handle(
    kernel32: Any,
    handle: int,
    path: str,
) -> None:
    if not kernel32.CloseHandle(handle):
        raise _windows_asset_api_error(
            "Could not close generated asset transaction handle",
            path,
        )


def _windows_asset_basic_info(
    kernel32: Any,
    handle: int,
    path: str,
) -> _WindowsFileBasicInfo:
    basic_info = _WindowsFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise _windows_asset_api_error(
            "Could not inspect generated asset attributes",
            path,
        )
    return basic_info


def _set_windows_asset_handle_attributes(
    kernel32: Any,
    handle: int,
    path: str,
    attributes: int,
) -> None:
    normalized_attributes = attributes
    if normalized_attributes & ~_WINDOWS_FILE_ATTRIBUTE_NORMAL:
        normalized_attributes &= ~_WINDOWS_FILE_ATTRIBUTE_NORMAL
    elif normalized_attributes == 0:
        normalized_attributes = _WINDOWS_FILE_ATTRIBUTE_NORMAL
    update = _WindowsFileBasicInfo(
        0,
        0,
        0,
        0,
        normalized_attributes,
    )
    if not kernel32.SetFileInformationByHandle(
        handle,
        _WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(update),
        ctypes.sizeof(update),
    ):
        raise _windows_asset_api_error(
            "Could not update generated asset attributes",
            path,
        )


def _set_windows_asset_handle_readonly(
    kernel32: Any,
    handle: int,
    path: str,
) -> None:
    current_attributes = int(
        _windows_asset_basic_info(kernel32, handle, path).FileAttributes
    )
    _set_windows_asset_handle_attributes(
        kernel32,
        handle,
        path,
        current_attributes | _WINDOWS_FILE_ATTRIBUTE_READONLY,
    )
    if not (
        _windows_asset_basic_info(kernel32, handle, path).FileAttributes
        & _WINDOWS_FILE_ATTRIBUTE_READONLY
    ):
        raise OSError(
            f"Generated asset staging mode update was not retained: {path}"
        )


def _mark_windows_asset_handle_for_deletion(
    kernel32: Any,
    handle: int,
    path: str,
) -> None:
    delete_info = _WindowsFileDispositionInfoEx(
        _WINDOWS_FILE_DISPOSITION_DELETE
        | _WINDOWS_FILE_DISPOSITION_POSIX_SEMANTICS
        | _WINDOWS_FILE_DISPOSITION_IGNORE_READONLY
    )
    if kernel32.SetFileInformationByHandle(
        handle,
        _WINDOWS_FILE_DISPOSITION_INFO_EX_CLASS,
        ctypes.byref(delete_info),
        ctypes.sizeof(delete_info),
    ):
        return
    get_last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    error_number = get_last_error()
    disposition_error = _windows_asset_api_error_from_code(
        "Could not remove generated asset transaction file",
        path,
        error_number,
    )
    if error_number not in _WINDOWS_UNSUPPORTED_DISPOSITION_ERRORS:
        raise disposition_error
    original_attributes = int(
        _windows_asset_basic_info(kernel32, handle, path).FileAttributes
    )
    if original_attributes & _WINDOWS_FILE_ATTRIBUTE_READONLY:
        link_count = _windows_asset_handle_link_count(kernel32, handle, path)
        disposition_error.add_note(
            "Handle-bound read-only deletion is unsupported; refusing the "
            "legacy attribute-changing fallback because another hard-link "
            f"could be created concurrently (observed links: {link_count})"
        )
        raise disposition_error
    legacy_delete = _WindowsFileDispositionInfo(1)
    if not kernel32.SetFileInformationByHandle(
        handle,
        _WINDOWS_FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(legacy_delete),
        ctypes.sizeof(legacy_delete),
    ):
        raise _windows_asset_api_error(
            "Could not remove generated asset transaction file",
            path,
        )


def _delete_exact_windows_asset_file(
    path: str,
    expected_identity: tuple[int, int],
) -> None:
    bound_file = _open_bound_windows_asset_file(
        path,
        expected_identity,
    )
    active_error: BaseException | None = None
    try:
        _delete_bound_windows_asset_file(
            "staging-cleanup",
            bound_file,
        )
    except BaseException as error:
        active_error = error
        raise
    finally:
        close_error = _close_bound_windows_asset_file(bound_file)
        if close_error is not None:
            if active_error is not None:
                active_error.add_note(
                    "Could not close generated asset staging cleanup handle: "
                    f"{close_error}"
                )
            else:
                raise close_error


@dataclass
class _WindowsBoundAssetFile:
    kernel32: Any
    handle: int
    identity: tuple[int, int]
    path: str
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        # CloseHandle failure leaves handle ownership ambiguous. Mark it released
        # before the call so a recycled numeric handle can never be closed twice.
        self.closed = True
        _close_windows_asset_handle(self.kernel32, self.handle, self.path)


def _open_bound_windows_asset_file(
    path: str,
    expected_identity: tuple[int, int],
    *,
    share_mode: int | None = None,
) -> _WindowsBoundAssetFile:
    kernel32, handle = _open_exact_windows_asset_file(
        path,
        expected_identity,
        desired_access=(
            _WINDOWS_DELETE_ACCESS
            | _WINDOWS_FILE_READ_ATTRIBUTES
            | _WINDOWS_FILE_WRITE_ATTRIBUTES
        ),
        share_mode=share_mode,
    )
    return _WindowsBoundAssetFile(
        kernel32=kernel32,
        handle=handle,
        identity=expected_identity,
        path=path,
    )


def _windows_asset_transaction_leaf(path: str) -> str:
    leaf = os.path.basename(path)
    if (
        leaf in {"", ".", ".."}
        or "\x00" in leaf
        or any(separator in leaf for separator in (":", "/", "\\"))
    ):
        raise OSError(f"Unsafe generated asset transaction name: {path}")
    return leaf


def _rename_bound_windows_asset_file(
    operation: str,
    bound_file: _WindowsBoundAssetFile,
    directory_handle: int,
    directory_path: str,
    destination: str,
) -> None:
    if bound_file.closed:
        raise OSError("Generated asset transaction handle is already closed")
    if os.path.normcase(os.path.abspath(os.path.dirname(destination))) != (
        os.path.normcase(os.path.abspath(directory_path))
    ):
        raise OSError(
            f"Generated asset transaction destination changed: {destination}"
        )
    leaf = _windows_asset_transaction_leaf(destination)
    encoded_leaf = leaf.encode("utf-16-le", "strict")
    buffer_size = ctypes.sizeof(_WindowsFileRenameInfo) + len(encoded_leaf) + 2
    rename_buffer = ctypes.create_string_buffer(buffer_size)
    rename_info = ctypes.cast(
        rename_buffer,
        ctypes.POINTER(_WindowsFileRenameInfo),
    ).contents
    rename_info.Operation.Flags = 0
    rename_info.RootDirectory = directory_handle
    rename_info.FileNameLength = len(encoded_leaf)
    ctypes.memmove(
        ctypes.addressof(rename_buffer) + _WindowsFileRenameInfo.FileName.offset,
        encoded_leaf,
        len(encoded_leaf),
    )
    previous_path = bound_file.path
    _before_asset_readonly_transaction_rename(
        operation,
        previous_path,
        destination,
    )
    if bound_file.kernel32.SetFileInformationByHandle(
        bound_file.handle,
        _WINDOWS_FILE_RENAME_INFO_CLASS,
        rename_buffer,
        buffer_size,
    ):
        bound_file.path = destination
    else:
        raise _windows_asset_api_error(
            "Could not move generated asset transaction file",
            destination,
        )
    if _windows_asset_handle_identity(
        bound_file.kernel32,
        bound_file.handle,
        bound_file.path,
    ) != bound_file.identity:
        raise OSError(
            "Generated asset handle identity changed after transaction move: "
            f"{bound_file.path}"
        )


def _delete_bound_windows_asset_file(
    operation: str,
    bound_file: _WindowsBoundAssetFile,
) -> None:
    if bound_file.closed:
        return
    _before_asset_readonly_transaction_delete(operation, bound_file.path)
    if _windows_asset_handle_identity(
        bound_file.kernel32,
        bound_file.handle,
        bound_file.path,
    ) != bound_file.identity:
        raise OSError(
            "Generated asset cleanup handle changed: "
            f"{bound_file.path}"
        )
    path = bound_file.path
    _mark_windows_asset_handle_for_deletion(
        bound_file.kernel32,
        bound_file.handle,
        path,
    )
    bound_file.close()
    try:
        remaining_identity = _asset_transaction_identity(path)
    except OSError:
        remaining_identity = None
    if remaining_identity == bound_file.identity:
        raise OSError(
            "Generated asset transaction file remained after exact cleanup: "
            f"{path}"
        )


def _close_bound_windows_asset_file(
    bound_file: _WindowsBoundAssetFile | None,
) -> OSError | None:
    if bound_file is None or bound_file.closed:
        return None
    try:
        bound_file.close()
    except OSError as close_error:
        return close_error
    return None


def _rollback_bound_windows_asset_transaction(
    output_path: str,
    staged_path: str,
    directory_path: str,
    directory_handle: int,
    previous_file: _WindowsBoundAssetFile,
    staged_file: _WindowsBoundAssetFile,
) -> tuple[BaseException, ...]:
    errors: list[BaseException] = []
    if previous_file.path != output_path:
        if staged_file.path == output_path and not staged_file.closed:
            try:
                recovery_path = _unique_asset_transaction_path(
                    output_path,
                    "rollback",
                )
                _rename_bound_windows_asset_file(
                    "rollback-stage",
                    staged_file,
                    directory_handle,
                    directory_path,
                    recovery_path,
                )
            except BaseException as move_error:
                errors.append(move_error)
                try:
                    _delete_bound_windows_asset_file(
                        "rollback-stage",
                        staged_file,
                    )
                except BaseException as delete_error:
                    errors.append(delete_error)
        try:
            _rename_bound_windows_asset_file(
                "restore",
                previous_file,
                directory_handle,
                directory_path,
                output_path,
            )
        except BaseException as restore_error:
            errors.append(restore_error)
    if not staged_file.closed:
        try:
            _delete_bound_windows_asset_file(
                "rollback-stage",
                staged_file,
            )
        except BaseException as cleanup_error:
            errors.append(cleanup_error)
    if previous_file.path != output_path:
        errors.append(
            OSError(
                "Previous generated asset remains recoverable at "
                f"{previous_file.path!r}; output restoration did not complete"
            )
        )
    else:
        try:
            restored_identity = _asset_transaction_identity(output_path)
        except BaseException as identity_error:
            errors.append(identity_error)
        else:
            if restored_identity != previous_file.identity:
                errors.append(
                    OSError(
                        "Previous generated asset handle was not restored at "
                        f"{output_path!r}"
                    )
                )
    if not staged_file.closed:
        try:
            staged_visible_identity = _asset_transaction_identity(
                staged_file.path
            )
        except BaseException as identity_error:
            errors.append(identity_error)
        else:
            location = (
                staged_file.path
                if staged_visible_identity == staged_file.identity
                else staged_path
            )
            errors.append(
                OSError(
                    "Staged generated asset handle could not be cleaned up; "
                    f"its last known path was {location!r}"
                )
            )
    return tuple(errors)


def _publish_bound_windows_readonly_asset_transaction(
    output_path: str,
    staged_path: str,
    output_identity: tuple[int, int],
    staged_identity: tuple[int, int],
    directory_identities: tuple[tuple[str, tuple[int, int]], ...],
    publication_validator: Callable[[], None] | None,
) -> None:
    directory_path, directory_identity = directory_identities[-1]
    backup_path = _unique_asset_transaction_path(output_path, "backup")
    directory_kernel32: Any | None = None
    directory_handle: int | None = None
    previous_file: _WindowsBoundAssetFile | None = None
    staged_file: _WindowsBoundAssetFile | None = None
    active_error: BaseException | None = None
    transaction_committed = False
    rollback_allowed = True
    cleanup_errors: list[BaseException] = []
    try:
        directory_kernel32, directory_handle = (
            _open_exact_windows_asset_directory(
                directory_path,
                directory_identity,
            )
        )
        previous_file = _open_bound_windows_asset_file(
            output_path,
            output_identity,
            share_mode=_WINDOWS_FILE_SHARE_READ,
        )
        staged_file = _open_bound_windows_asset_file(
            staged_path,
            staged_identity,
            share_mode=_WINDOWS_FILE_SHARE_READ,
        )
        if publication_validator is not None:
            publication_validator()
        _before_asset_readonly_transaction_mode(staged_path)
        if (
            _windows_asset_handle_link_count(
                staged_file.kernel32,
                staged_file.handle,
                staged_file.path,
            )
            != 1
        ):
            raise OSError(
                "Generated asset staging file gained an external hard link: "
                f"{staged_file.path}"
            )
        _set_windows_asset_handle_readonly(
            staged_file.kernel32,
            staged_file.handle,
            staged_file.path,
        )
        _rename_bound_windows_asset_file(
            "quarantine",
            previous_file,
            directory_handle,
            directory_path,
            backup_path,
        )
        _rename_bound_windows_asset_file(
            "publish",
            staged_file,
            directory_handle,
            directory_path,
            output_path,
        )
        if publication_validator is not None:
            publication_validator()
        _before_asset_readonly_transaction_delete(
            "previous-output",
            previous_file.path,
        )
        if _windows_asset_handle_identity(
            previous_file.kernel32,
            previous_file.handle,
            previous_file.path,
        ) != previous_file.identity:
            raise OSError(
                "Previous generated asset handle changed before commit: "
                f"{previous_file.path}"
            )
        if _asset_transaction_identity(
            previous_file.path
        ) != previous_file.identity:
            raise OSError(
                "Previous generated asset namespace changed before commit: "
                f"{previous_file.path}"
            )
        if _asset_transaction_identity(output_path) != staged_file.identity:
            raise OSError(
                "Published generated asset namespace changed before commit: "
                f"{output_path}"
            )
        # A successful disposition is the irreversible commit point. From this
        # call onward, handle-close problems are cleanup diagnostics and must not
        # turn an installed replacement into a reported transaction failure.
        rollback_allowed = False
        try:
            _mark_windows_asset_handle_for_deletion(
                previous_file.kernel32,
                previous_file.handle,
                previous_file.path,
            )
        except BaseException as disposition_error:
            try:
                delete_pending = bool(
                    _windows_asset_standard_info(
                        previous_file.kernel32,
                        previous_file.handle,
                        previous_file.path,
                    ).DeletePending
                )
            except BaseException as inspection_error:
                disposition_error.add_note(
                    "Could not determine whether previous-output deletion "
                    f"committed: {inspection_error}"
                )
                raise
            if not delete_pending:
                rollback_allowed = True
                raise
            cleanup_errors.append(disposition_error)
        transaction_committed = True
        previous_close_error = _close_bound_windows_asset_file(previous_file)
        if previous_close_error is not None:
            cleanup_errors.append(previous_close_error)
    except BaseException as error:
        active_error = error
        if (
            rollback_allowed
            and directory_handle is not None
            and previous_file is not None
            and staged_file is not None
        ):
            rollback_errors = _rollback_bound_windows_asset_transaction(
                output_path,
                staged_path,
                directory_path,
                directory_handle,
                previous_file,
                staged_file,
            )
            for rollback_error in rollback_errors:
                error.add_note(
                    "Generated asset read-only rollback problem: "
                    f"{rollback_error}"
                )
        elif not transaction_committed:
            error.add_note(
                "Previous generated asset deletion may already have committed; "
                "automatic rollback was not safe"
            )
        raise
    finally:
        staged_close_error = _close_bound_windows_asset_file(staged_file)
        if staged_close_error is not None:
            cleanup_errors.append(staged_close_error)
        previous_close_error = _close_bound_windows_asset_file(previous_file)
        if previous_close_error is not None:
            cleanup_errors.append(previous_close_error)
        if directory_kernel32 is not None and directory_handle is not None:
            handle_to_close = directory_handle
            directory_handle = None
            try:
                _close_windows_asset_handle(
                    directory_kernel32,
                    handle_to_close,
                    directory_path,
                )
            except OSError as close_error:
                cleanup_errors.append(close_error)
        if active_error is not None:
            for cleanup_error in cleanup_errors:
                active_error.add_note(
                    "Generated asset transaction cleanup problem: "
                    f"{cleanup_error}"
                )


def _atomic_write_asset_text_in_directory(
    directory_fd: int,
    filename: str,
    content: str,
    publication_validator: Callable[[], None] | None = None,
) -> None:
    output_identity, output_mode = _asset_output_state_at(directory_fd, filename)
    temporary_name = ""
    file_descriptor = -1
    for _attempt in range(100):
        temporary_name = f".{filename}.{secrets.token_hex(8)}.tmp"
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
        raise OSError(f"Could not stage generated asset output: {filename}")

    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    try:
        if output_mode is not None:
            os.chmod(file_descriptor, output_mode)
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as temporary_file:
            file_descriptor = -1
            temporary_file.write(content)
            _sync_generated_asset_stage(temporary_file)
        staged_stat = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(f"Generated asset staging file changed: {filename}")
        if publication_validator is not None:
            publication_validator()
        _verify_asset_output_state_at(directory_fd, filename, output_identity)
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_pending = False
        if publication_validator is not None:
            try:
                publication_validator()
            except BaseException as validation_error:
                try:
                    published_stat = os.stat(
                        filename,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    if (
                        stat.S_ISREG(published_stat.st_mode)
                        and (published_stat.st_dev, published_stat.st_ino)
                        == temporary_identity
                    ):
                        os.unlink(filename, dir_fd=directory_fd)
                except BaseException as cleanup_error:
                    validation_error.add_note(
                        "Failed to remove invalid generated asset registry: "
                        f"{cleanup_error}"
                    )
                raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _uses_windows_readonly_asset_transaction(
    output_mode: int | None,
) -> bool:
    return (
        os.name == "nt"
        and output_mode is not None
        and not output_mode & stat.S_IWRITE
    )


def _before_asset_readonly_transaction_rename(
    _operation: str,
    _source: str,
    _destination: str,
) -> None:
    """Narrow test seam before a read-only transaction rename."""


def _before_asset_readonly_transaction_mode(_path: str) -> None:
    """Narrow test seam before activating the staged read-only mode."""


def _before_asset_readonly_transaction_delete(
    _operation: str,
    _path: str,
) -> None:
    """Narrow test seam before exact transaction cleanup."""


def _unique_asset_transaction_path(output_path: str, label: str) -> str:
    output_directory = os.path.dirname(output_path)
    filename = os.path.basename(output_path)
    for _attempt in range(100):
        candidate = os.path.join(
            output_directory,
            f".{filename}.{secrets.token_hex(8)}.{label}",
        )
        if not os.path.lexists(candidate):
            return candidate
    raise OSError(
        f"Could not allocate generated asset transaction path: {output_path}"
    )


def _asset_transaction_identity(path: str) -> tuple[int, int] | None:
    identity, _mode = _asset_output_state(path)
    return identity


def _publish_windows_readonly_asset_transaction(
    output_path: str,
    staged_path: str,
    output_identity: tuple[int, int],
    staged_identity: tuple[int, int],
    directory_identities: tuple[tuple[str, tuple[int, int]], ...],
    publication_validator: Callable[[], None] | None,
) -> None:
    if os.name != "nt":
        raise OSError("Windows read-only asset transactions are unavailable")
    _publish_bound_windows_readonly_asset_transaction(
        output_path,
        staged_path,
        output_identity,
        staged_identity,
        directory_identities,
        publication_validator,
    )


def _atomic_write_asset_text_fallback(
    root: str,
    components: tuple[str, ...],
    content: str,
    publication_validator: Callable[[], None] | None = None,
) -> None:
    directory_identities = _prepare_asset_output_directories_fallback(
        root,
        components[:-1],
    )
    output_directory = os.path.join(root, *components[:-1])
    output_path = os.path.join(output_directory, components[-1])
    output_identity, output_mode = _asset_output_state(output_path)
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=output_directory,
        prefix=f".{components[-1]}.",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    staged_pending = True
    readonly_transaction = _uses_windows_readonly_asset_transaction(
        output_mode
    )
    try:
        if output_mode is not None and not readonly_transaction:
            os.chmod(staged_path, output_mode)
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as staged_file:
            file_descriptor = -1
            staged_file.write(content)
            _sync_generated_asset_stage(staged_file)
        _verify_asset_output_directories_fallback(directory_identities)
        staged_stat = os.lstat(staged_path)
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(
                f"Generated asset staging file changed: {components[-1]}"
            )
        if readonly_transaction:
            if output_identity is None or output_mode is None:
                raise AssertionError(
                    "A read-only asset transaction requires an existing output"
                )
            _publish_windows_readonly_asset_transaction(
                output_path,
                staged_path,
                output_identity,
                temporary_identity,
                directory_identities,
                publication_validator,
            )
            staged_pending = False
            return
        if publication_validator is not None:
            publication_validator()
        _verify_asset_output_state(output_path, output_identity)
        os.replace(staged_path, output_path)
        staged_pending = False
        if publication_validator is not None:
            try:
                publication_validator()
            except BaseException as validation_error:
                try:
                    published_stat = os.lstat(output_path)
                    if (
                        stat.S_ISREG(published_stat.st_mode)
                        and (published_stat.st_dev, published_stat.st_ino)
                        == temporary_identity
                    ):
                        try:
                            os.unlink(output_path)
                        except PermissionError:
                            if os.name != "nt":
                                raise
                            os.chmod(output_path, stat.S_IWRITE)
                            writable_stat = os.lstat(output_path)
                            if (
                                not stat.S_ISREG(writable_stat.st_mode)
                                or (
                                    writable_stat.st_dev,
                                    writable_stat.st_ino,
                                )
                                != temporary_identity
                            ):
                                raise OSError(
                                    "Generated asset registry changed before "
                                    f"cleanup: {output_path}"
                                )
                            os.unlink(output_path)
                except BaseException as cleanup_error:
                    validation_error.add_note(
                        "Failed to remove invalid generated asset registry: "
                        f"{cleanup_error}"
                    )
                raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if staged_pending:
            try:
                _verify_asset_output_directories_fallback(directory_identities)
                if os.name == "nt":
                    _delete_exact_windows_asset_file(
                        staged_path,
                        temporary_identity,
                    )
                else:
                    current_stage_stat = os.lstat(staged_path)
                    if (
                        current_stage_stat.st_dev,
                        current_stage_stat.st_ino,
                    ) == temporary_identity:
                        os.unlink(staged_path)
            except OSError:
                pass


def _prepare_asset_output_directories_fallback(
    root: str,
    directory_components: tuple[str, ...],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    root_real = os.path.realpath(root)
    directory_path = root
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in (None, *directory_components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
            try:
                directory_stat = os.lstat(directory_path)
            except FileNotFoundError:
                os.mkdir(directory_path)
                directory_stat = os.lstat(directory_path)
        else:
            directory_stat = os.lstat(directory_path)
        directory_real = os.path.realpath(directory_path)
        try:
            contained = os.path.commonpath((directory_real, root_real)) == root_real
        except ValueError:
            contained = False
        if (
            _path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not contained
        ):
            raise OSError(
                "Refusing redirected asset-registry output directory: "
                f"{directory_path}"
            )
        identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return tuple(identities)


def _verify_asset_output_directories_fallback(
    identities: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            directory_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Asset-registry output directory changed: {directory_path}"
            ) from error
        if (
            _path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or (directory_stat.st_dev, directory_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                f"Asset-registry output directory changed: {directory_path}"
            )


def _asset_output_state(
    output_path: str,
) -> tuple[tuple[int, int] | None, int | None]:
    try:
        output_stat = os.lstat(output_path)
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing to replace non-regular asset registry: {output_path}"
        )
    return (
        (output_stat.st_dev, output_stat.st_ino),
        stat.S_IMODE(output_stat.st_mode),
    )


def _verify_asset_output_state(
    output_path: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity, _mode = _asset_output_state(output_path)
    if current_identity != expected_identity:
        raise OSError(f"Asset registry changed during publication: {output_path}")


def atomic_write_confined_generated_text(
    output_path: str,
    content: str,
    *,
    confinement_root: str,
    publication_validator: Callable[[], None] | None = None,
) -> None:
    """Publish UTF-8 generated text through a confined, no-follow path."""

    output_absolute = os.path.abspath(output_path)
    root = os.path.abspath(confinement_root)
    components = _asset_output_components(root, output_absolute)
    _ensure_asset_output_root(root)
    if _confined_asset_output_supported():
        _atomic_write_asset_text_at(
            root,
            components,
            content,
            publication_validator,
        )
        return
    _atomic_write_asset_text_fallback(
        root,
        components,
        content,
        publication_validator,
    )


def generated_path_is_redirected(
    path: str,
    path_stat: os.stat_result,
) -> bool:
    """Return whether a generated-output path is redirected."""
    return _path_is_redirected(path, path_stat)


def generated_output_components(
    root: str,
    output_path: str,
) -> tuple[str, ...]:
    """Return validated output components relative to a confinement root."""
    return _asset_output_components(root, output_path)


def confined_generated_output_supported() -> bool:
    """Return whether descriptor-relative confined publication is available."""
    return _confined_asset_output_supported()


def verify_open_generated_output_directory(
    root: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    """Verify an opened generated-output directory against its path."""
    _verify_open_asset_output_directory(root, directory_path, directory_fd)


__all__ = [
    "atomic_write_confined_generated_text",
    "confined_generated_output_supported",
    "generated_output_components",
    "generated_path_is_redirected",
    "verify_open_generated_output_directory",
]
