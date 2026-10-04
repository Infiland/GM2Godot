from __future__ import annotations

import ctypes
import os
import stat
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, BinaryIO, Callable, cast

from src.conversion.included_files_parts.filesystem_operations import IncludedCleanupParentBinding
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata

_WINDOWS_GENERIC_READ = 0x80000000

_WINDOWS_FILE_TRAVERSE = 0x00000020

_WINDOWS_FILE_READ_ATTRIBUTES = 0x00000080

_WINDOWS_FILE_SHARE_READ = 0x00000001

_WINDOWS_FILE_SHARE_WRITE = 0x00000002

_WINDOWS_FILE_SHARE_DELETE = 0x00000004

_WINDOWS_OPEN_EXISTING = 3

_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010

_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080

_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400

_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

_WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000

_WINDOWS_FILE_TYPE_DISK = 1

_WINDOWS_FILE_BASIC_INFO_CLASS = 0

_WINDOWS_FILE_ID_INFO_CLASS = 18

_WINDOWS_MOVEFILE_WRITE_THROUGH = 0x00000008


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

class _WindowsIncludedFileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_uint8 * 16),)

class _WindowsIncludedFileIdInfo(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", _WindowsIncludedFileId128),
    )

class _WindowsIncludedFileBasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )

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
def _windows_included_cleanup_parent_api() -> Any:
    """Return the Win32 calls used to pin one cleanup directory parent."""

    if os.name != "nt":
        raise OSError(
            "Windows Included Files cleanup parent handles are unavailable"
        )
    if (
        ctypes.sizeof(WindowsIncludedFileId128) != 16
        or ctypes.sizeof(WindowsIncludedFileIdInfo) != 24
        or WindowsIncludedFileIdInfo.FileId.offset != 8
        or ctypes.sizeof(WindowsIncludedFileBasicInfo) != 40
        or WindowsIncludedFileBasicInfo.FileAttributes.offset != 32
    ):
        raise OSError("Unsupported Windows Included Files cleanup ABI layout")
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
    kernel32.GetFileType.argtypes = (ctypes.c_void_p,)
    kernel32.GetFileType.restype = ctypes.c_uint32
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

def _windows_included_cleanup_parent_identity(
    kernel32: Any,
    handle: int,
    path: str,
) -> _PathIdentity:
    identity_info = WindowsIncludedFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        WINDOWS_FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise windows_included_transaction_error(
            "Could not identify Included Files cleanup parent handle",
            path,
        )
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )

def _windows_included_cleanup_parent_attributes(
    kernel32: Any,
    handle: int,
    path: str,
) -> int:
    basic_info = WindowsIncludedFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise windows_included_transaction_error(
            "Could not inspect Included Files cleanup parent handle",
            path,
        )
    return int(basic_info.FileAttributes)

@dataclass
class _WindowsIncludedCleanupParentBinding:
    """Keep one verified cleanup parent immovable for path-based operations.

    Windows has no Python ``dir_fd`` equivalent for the cleanup operations in
    this module.  The retained directory handle deliberately omits
    ``FILE_SHARE_DELETE`` so its directory cannot be renamed or deleted while
    the binding is live.  Callers still revalidate the native file ID and path
    before every group of path-based child operations.
    """

    path: str
    identity: _PathIdentity
    kernel32: Any
    handle: int | None

    @classmethod
    def open(
        cls,
        path: str,
        expected_identity: _PathIdentity,
    ) -> "_WindowsIncludedCleanupParentBinding":
        if os.name != "nt":
            raise OSError(
                "Windows Included Files cleanup parent bindings are unavailable"
            )
        absolute_path = os.path.abspath(path)
        try:
            path_stat = os.lstat(absolute_path)
        except OSError as error:
            raise OSError(
                f"Included Files cleanup parent changed: {absolute_path}"
            ) from error
        if (
            _included_metadata.included_output_path_is_redirected(absolute_path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
        ):
            raise OSError(
                f"Included Files cleanup parent changed: {absolute_path}"
            )

        kernel32 = windows_included_cleanup_parent_api()
        handle = kernel32.CreateFileW(
            _included_paths.windows_extended_included_path(absolute_path),
            WINDOWS_FILE_TRAVERSE | WINDOWS_FILE_READ_ATTRIBUTES,
            WINDOWS_FILE_SHARE_READ | WINDOWS_FILE_SHARE_WRITE,
            None,
            WINDOWS_OPEN_EXISTING,
            WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
            | WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle is None or handle == invalid_handle:
            raise windows_included_transaction_error(
                "Could not bind Included Files cleanup parent",
                absolute_path,
            )
        binding = cls(
            path=absolute_path,
            identity=expected_identity,
            kernel32=kernel32,
            handle=cast(int, handle),
        )
        try:
            binding.verify()
        except BaseException as error:
            try:
                binding.close()
            except BaseException as close_error:
                error.add_note(
                    "Could not close rejected Included Files cleanup parent "
                    f"binding: {close_error}"
                )
            raise
        return binding

    def __enter__(self) -> "_WindowsIncludedCleanupParentBinding":
        self.verify()
        return self

    def __exit__(
        self,
        _exception_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None:
        try:
            self.close()
        except BaseException as close_error:
            if active_error is None:
                raise
            active_error.add_note(
                "Could not close Included Files cleanup parent binding: "
                + str(close_error)
            )
        return None

    def verify(self) -> None:
        handle = self.handle
        if handle is None:
            raise OSError(
                f"Included Files cleanup parent binding is closed: {self.path}"
            )
        try:
            path_stat = os.lstat(self.path)
        except OSError as error:
            raise OSError(
                f"Included Files cleanup parent changed: {self.path}"
            ) from error
        attributes = windows_included_cleanup_parent_attributes(
            self.kernel32,
            handle,
            self.path,
        )
        if (
            self.kernel32.GetFileType(handle) != WINDOWS_FILE_TYPE_DISK
            or _included_metadata.included_output_path_is_redirected(self.path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self.identity
            or windows_included_cleanup_parent_identity(
                self.kernel32,
                handle,
                self.path,
            )
            != self.identity
            or not attributes & WINDOWS_FILE_ATTRIBUTE_DIRECTORY
            or attributes & WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError(
                f"Included Files cleanup parent changed: {self.path}"
            )

    def close(self) -> None:
        handle = self.handle
        if handle is None:
            return
        self.handle = None
        if not self.kernel32.CloseHandle(handle):
            raise windows_included_transaction_error(
                "Could not close Included Files cleanup parent handle",
                self.path,
            )

def _verify_windows_included_cleanup_parent_binding(
    binding: IncludedCleanupParentBinding,
    parent_path: str,
    expected_identity: _PathIdentity,
) -> None:
    """Verify that a retained Windows handle still binds the requested parent."""

    absolute_parent_path = os.path.abspath(parent_path)
    if (
        os.name != "nt"
        or os.path.normcase(binding.path)
        != os.path.normcase(absolute_parent_path)
        or binding.identity != expected_identity
    ):
        raise OSError(
            f"Included Files cleanup parent binding mismatch: {absolute_parent_path}"
        )
    binding.verify()

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

    kernel32 = windows_included_file_read_api()
    handle_value = kernel32.CreateFileW(
        _included_paths.windows_extended_included_path(path),
        WINDOWS_GENERIC_READ,
        WINDOWS_FILE_SHARE_READ,
        None,
        WINDOWS_OPEN_EXISTING,
        WINDOWS_FILE_ATTRIBUTE_NORMAL
        | (WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT if no_follow else 0)
        | WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN,
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
    kernel32 = windows_included_transaction_api()
    if not kernel32.MoveFileExW(
        _included_paths.windows_extended_included_path(source),
        _included_paths.windows_extended_included_path(destination),
        WINDOWS_MOVEFILE_WRITE_THROUGH,
    ):
        raise windows_included_transaction_error(
            "Could not durably move Included Files transaction entry",
            destination,
        )


# Finite live owner exports; one actual native definition each.
WINDOWS_GENERIC_READ = _WINDOWS_GENERIC_READ
WINDOWS_FILE_TRAVERSE = _WINDOWS_FILE_TRAVERSE
WINDOWS_FILE_READ_ATTRIBUTES = _WINDOWS_FILE_READ_ATTRIBUTES
WINDOWS_FILE_SHARE_READ = _WINDOWS_FILE_SHARE_READ
WINDOWS_FILE_SHARE_WRITE = _WINDOWS_FILE_SHARE_WRITE
WINDOWS_FILE_SHARE_DELETE = _WINDOWS_FILE_SHARE_DELETE
WINDOWS_OPEN_EXISTING = _WINDOWS_OPEN_EXISTING
WINDOWS_FILE_ATTRIBUTE_DIRECTORY = _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
WINDOWS_FILE_ATTRIBUTE_NORMAL = _WINDOWS_FILE_ATTRIBUTE_NORMAL
WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN = _WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN
WINDOWS_FILE_TYPE_DISK = _WINDOWS_FILE_TYPE_DISK
WINDOWS_FILE_BASIC_INFO_CLASS = _WINDOWS_FILE_BASIC_INFO_CLASS
WINDOWS_FILE_ID_INFO_CLASS = _WINDOWS_FILE_ID_INFO_CLASS
WINDOWS_MOVEFILE_WRITE_THROUGH = _WINDOWS_MOVEFILE_WRITE_THROUGH
windows_included_file_locking = _windows_included_file_locking
WindowsIncludedFileId128 = _WindowsIncludedFileId128
WindowsIncludedFileIdInfo = _WindowsIncludedFileIdInfo
WindowsIncludedFileBasicInfo = _WindowsIncludedFileBasicInfo
windows_included_file_read_api = _windows_included_file_read_api
windows_included_cleanup_parent_api = _windows_included_cleanup_parent_api
windows_included_transaction_api = _windows_included_transaction_api
windows_included_transaction_error = _windows_included_transaction_error
windows_included_cleanup_parent_identity = _windows_included_cleanup_parent_identity
windows_included_cleanup_parent_attributes = _windows_included_cleanup_parent_attributes
WindowsIncludedCleanupParentBinding = _WindowsIncludedCleanupParentBinding
verify_windows_included_cleanup_parent_binding = _verify_windows_included_cleanup_parent_binding
open_included_file_validation_stream = _open_included_file_validation_stream
rename_included_transaction_entry = _rename_included_transaction_entry
