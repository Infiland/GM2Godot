"""Win32 calls and ABI used by Included Files transactions."""
from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from typing import Any, Callable, cast


def lock_file(
    file_descriptor: int,
    mode: int,
) -> None:
    import msvcrt

    locking = msvcrt.locking
    locking(file_descriptor, mode, 1)


GENERIC_READ = 0x80000000


FILE_TRAVERSE = 0x00000020


FILE_READ_ATTRIBUTES = 0x00000080


FILE_SHARE_READ = 0x00000001


FILE_SHARE_WRITE = 0x00000002


FILE_SHARE_DELETE = 0x00000004


OPEN_EXISTING = 3


FILE_ATTRIBUTE_DIRECTORY = 0x00000010


FILE_ATTRIBUTE_NORMAL = 0x00000080


FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000


FILE_TYPE_DISK = 1


FILE_BASIC_INFO_CLASS = 0


FILE_ID_INFO_CLASS = 18


MOVEFILE_WRITE_THROUGH = 0x00000008


class WindowsFileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_uint8 * 16),)


class WindowsFileIdInfo(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", WindowsFileId128),
    )


class WindowsFileBasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )


@lru_cache(maxsize=1)
def file_read_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows Included File read handles are unavailable")
    win_dll = cast(Callable[..., Any], ctypes.WinDLL)
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
def cleanup_parent_api() -> Any:
    """Return the Win32 calls used to pin one cleanup directory parent."""

    if os.name != "nt":
        raise OSError(
            "Windows Included Files cleanup parent handles are unavailable"
        )
    if (
        ctypes.sizeof(WindowsFileId128) != 16
        or ctypes.sizeof(WindowsFileIdInfo) != 24
        or WindowsFileIdInfo.FileId.offset != 8
        or ctypes.sizeof(WindowsFileBasicInfo) != 40
        or WindowsFileBasicInfo.FileAttributes.offset != 32
    ):
        raise OSError("Unsupported Windows Included Files cleanup ABI layout")
    win_dll = cast(Callable[..., Any], ctypes.WinDLL)
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
def transaction_api() -> Any:
    if os.name != "nt":
        raise OSError("Windows Included Files transaction APIs are unavailable")
    win_dll = cast(Callable[..., Any], ctypes.WinDLL)
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    kernel32.MoveFileExW.restype = ctypes.c_int
    return kernel32


def transaction_error(
    operation: str,
    path: str,
) -> OSError:
    get_last_error = ctypes.get_last_error
    format_error = cast(Callable[[int], str], ctypes.FormatError)
    error_number = get_last_error()
    return OSError(
        error_number,
        f"{operation}: {format_error(error_number).strip()}",
        path,
    )


def extended_path(path: str) -> str:
    """Return an absolute Win32 path that does not depend on MAX_PATH policy."""

    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def rename_transaction_entry(source: str, destination: str) -> None:
    if os.name != "nt":
        raise OSError(
            "Unsafe path-based Included Files rename is disabled on POSIX"
        )
    if sys.platform != "win32":
        # Cross-platform unit tests model the Windows fallback by patching
        # os.name; the real Windows runner exercises MoveFileExW below.
        os.rename(source, destination)
        return
    kernel32 = transaction_api()
    if not kernel32.MoveFileExW(
        extended_path(source),
        extended_path(destination),
        MOVEFILE_WRITE_THROUGH,
    ):
        raise transaction_error(
            "Could not durably move Included Files transaction entry",
            destination,
        )
