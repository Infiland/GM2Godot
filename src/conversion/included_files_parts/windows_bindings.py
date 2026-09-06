"""Verified non-delete-sharing Windows cleanup parent lifetime."""
from __future__ import annotations

import ctypes
import os
import stat
from dataclasses import dataclass
from typing import Any, cast

from src.conversion.included_files_parts.filesystem_metadata import output_path_is_redirected
from src.conversion.included_files_parts.models import PathIdentity
from src.conversion.included_files_parts.windows_operations import (
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_BASIC_INFO_CLASS,
    FILE_FLAG_BACKUP_SEMANTICS,
    FILE_FLAG_OPEN_REPARSE_POINT,
    FILE_ID_INFO_CLASS,
    FILE_READ_ATTRIBUTES,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    FILE_TRAVERSE,
    FILE_TYPE_DISK,
    OPEN_EXISTING,
    WindowsFileBasicInfo,
    WindowsFileIdInfo,
    cleanup_parent_api,
    extended_path,
    transaction_error,
)


def cleanup_parent_identity(
    kernel32: Any,
    handle: int,
    path: str,
) -> PathIdentity:
    identity_info = WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise transaction_error(
            "Could not identify Included Files cleanup parent handle",
            path,
        )
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )


def cleanup_parent_attributes(
    kernel32: Any,
    handle: int,
    path: str,
) -> int:
    basic_info = WindowsFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise transaction_error(
            "Could not inspect Included Files cleanup parent handle",
            path,
        )
    return int(basic_info.FileAttributes)


@dataclass
class WindowsCleanupParentBinding:
    """Keep one verified cleanup parent immovable for path-based operations.

    Windows has no Python ``dir_fd`` equivalent for the cleanup operations in
    this module.  The retained directory handle deliberately omits
    ``FILE_SHARE_DELETE`` so its directory cannot be renamed or deleted while
    the binding is live.  Callers still revalidate the native file ID and path
    before every group of path-based child operations.
    """

    path: str
    identity: PathIdentity
    kernel32: Any
    handle: int | None

    @classmethod
    def open(
        cls,
        path: str,
        expected_identity: PathIdentity,
    ) -> "WindowsCleanupParentBinding":
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
            output_path_is_redirected(absolute_path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
        ):
            raise OSError(
                f"Included Files cleanup parent changed: {absolute_path}"
            )

        kernel32 = cleanup_parent_api()
        handle = kernel32.CreateFileW(
            extended_path(absolute_path),
            FILE_TRAVERSE | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS
            | FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle is None or handle == invalid_handle:
            raise transaction_error(
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

    def __enter__(self) -> "WindowsCleanupParentBinding":
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
        attributes = cleanup_parent_attributes(
            self.kernel32,
            handle,
            self.path,
        )
        if (
            self.kernel32.GetFileType(handle) != FILE_TYPE_DISK
            or output_path_is_redirected(self.path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self.identity
            or cleanup_parent_identity(
                self.kernel32,
                handle,
                self.path,
            )
            != self.identity
            or not attributes & FILE_ATTRIBUTE_DIRECTORY
            or attributes & FILE_ATTRIBUTE_REPARSE_POINT
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
            raise transaction_error(
                "Could not close Included Files cleanup parent handle",
                self.path,
            )


def verify_cleanup_parent_binding(
    binding: WindowsCleanupParentBinding,
    parent_path: str,
    expected_identity: PathIdentity,
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
