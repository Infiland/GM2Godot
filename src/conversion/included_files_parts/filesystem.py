"""Validation streams with explicit descriptor and Windows handle transfer."""
from __future__ import annotations

import ctypes
import os
from typing import BinaryIO, Callable, cast

from src.conversion.included_files_parts.windows_operations import (
    FILE_ATTRIBUTE_NORMAL,
    FILE_FLAG_OPEN_REPARSE_POINT,
    FILE_FLAG_SEQUENTIAL_SCAN,
    FILE_SHARE_READ,
    GENERIC_READ,
    OPEN_EXISTING,
    extended_path,
    file_read_api,
)


def open_validation_stream(
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

    kernel32 = file_read_api()
    handle_value = kernel32.CreateFileW(
        extended_path(path),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL
        | (FILE_FLAG_OPEN_REPARSE_POINT if no_follow else 0)
        | FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle_value is None or handle_value == invalid_handle:
        get_last_error = ctypes.get_last_error
        error_number = get_last_error()
        format_error = cast(
            Callable[[int], str],
            ctypes.FormatError,
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
