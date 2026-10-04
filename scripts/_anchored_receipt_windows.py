"""Retained-handle Win32 publication for small immutable receipt bytes."""

from __future__ import annotations

import ctypes
import functools
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, cast

DWORD = ctypes.c_uint32
BOOLEAN = ctypes.c_ubyte
WCHAR = ctypes.c_uint16
USHORT = ctypes.c_uint16
ULONG = ctypes.c_uint32
NTSTATUS = ctypes.c_int32
FILE_INFORMATION_CLASS = ctypes.c_int32
ULONG_PTR = ctypes.c_size_t


DELETE = 0x00010000
SYNCHRONIZE = 0x00100000
FILE_READ_DATA = 0x00000001
FILE_WRITE_DATA = 0x00000002
FILE_READ_ATTRIBUTES = 0x00000080
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_TYPE_UNKNOWN = 0
FILE_TYPE_DISK = 1
FILE_BEGIN = 0
FILE_BASIC_INFO = 0
FILE_STANDARD_INFO = 1
FILE_DISPOSITION_INFO = 4
FILE_ID_INFO = 18
ERROR_FILE_EXISTS = 80
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_INVALID_FUNCTION = 1
ERROR_NOT_SUPPORTED = 50
ERROR_INVALID_PARAMETER = 87
ERROR_CALL_NOT_IMPLEMENTED = 120

OBJ_CASE_INSENSITIVE = 0x00000040
FILE_OPEN = 0x00000001
FILE_CREATE = 0x00000002
FILE_OPEN_IF = 0x00000003
FILE_OPENED = 0x00000001
FILE_CREATED = 0x00000002
FILE_RENAME_INFORMATION = 10
FILE_DIRECTORY_FILE = 0x00000001
FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
FILE_NON_DIRECTORY_FILE = 0x00000040
FILE_OPEN_REPARSE_POINT = 0x00200000
STATUS_OBJECT_NAME_COLLISION = 0xC0000035
STATUS_FILE_IS_A_DIRECTORY = 0xC00000BA
STATUS_PENDING = 0x00000103

_WINDOWS_CLOSE_RESULT_PENDING = object()
_WINDOWS_CLOSE_ERROR_PENDING = object()
_WINDOWS_PUBLICATION_UNAVAILABLE_ERRORS = frozenset(
    {
        ERROR_INVALID_FUNCTION,
        ERROR_NOT_SUPPORTED,
        ERROR_INVALID_PARAMETER,
        ERROR_CALL_NOT_IMPLEMENTED,
    }
)
_WINDOWS_NONREGULAR_OPEN_STATUSES = frozenset({STATUS_FILE_IS_A_DIRECTORY})

_STAGE_ACCESS = FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | DELETE | SYNCHRONIZE
_TARGET_READ_ACCESS = FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE
_DIRECTORY_ACCESS = 0x00000020 | FILE_READ_ATTRIBUTES | SYNCHRONIZE
_FILE_OPEN_OPTIONS = FILE_SYNCHRONOUS_IO_NONALERT | FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT
_DIRECTORY_OPEN_OPTIONS = FILE_SYNCHRONOUS_IO_NONALERT | FILE_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT

_WINDOWS_RESERVED_LEAF_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_DEVICE_BASENAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{suffix}" for suffix in "123456789¹²³"),
        *(f"lpt{suffix}" for suffix in "123456789¹²³"),
    }
)


class _FileId128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_ubyte * 16),)


class _FileIdInfo(ctypes.Structure):
    _fields_ = (("VolumeSerialNumber", ctypes.c_ulonglong), ("FileId", _FileId128))


class _FileBasicInfo(ctypes.Structure):
    _fields_ = (
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("FileAttributes", DWORD),
    )


class _FileStandardInfo(ctypes.Structure):
    _fields_ = (
        ("AllocationSize", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("NumberOfLinks", DWORD),
        ("DeletePending", BOOLEAN),
        ("Directory", BOOLEAN),
    )


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = (("DeleteFile", BOOLEAN),)


class _FileRenameInformation(ctypes.Structure):
    _fields_ = (
        ("ReplaceIfExists", BOOLEAN),
        ("RootDirectory", ctypes.c_void_p),
        ("FileNameLength", DWORD),
        ("FileName", WCHAR * 1),
    )


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("Length", USHORT),
        ("MaximumLength", USHORT),
        ("Buffer", ctypes.c_void_p),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("Length", ULONG),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    )


class _IoStatusValue(ctypes.Union):
    _fields_ = (("Status", NTSTATUS), ("Pointer", ctypes.c_void_p))


class _IoStatusBlock(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = (("value", _IoStatusValue), ("Information", ULONG_PTR))


@dataclass(frozen=True)
class WindowsReceiptResult:
    leaf: str
    volume_serial_number: int
    file_id: bytes
    size: int


@dataclass(frozen=True)
class WindowsReceiptOutcome:
    state: Literal["published", "unknown"]
    receipt: WindowsReceiptResult


@dataclass(frozen=True)
class WindowsDirectoryResult:
    handle: int
    volume_serial_number: int
    file_id: bytes
    created: bool


@dataclass(slots=True)
class _WindowsCloseObservation:
    """One definitive CloseHandle result and its immediate error evidence."""

    status: object
    error: object = _WINDOWS_CLOSE_ERROR_PENDING


@dataclass(slots=True, init=False)
class WindowsHandleLease:
    """Mutable ownership slot visible across Python call-return boundaries."""

    _handle_output: ctypes.c_void_p = field(init=False, repr=False)
    recorded_close_results: list[_WindowsCloseObservation] = field(init=False, repr=False)
    close_retry_blocked: bool = field(init=False, repr=False)
    pending_close_result_count: int | None = field(init=False, repr=False)

    def __init__(
        self,
        handle: int | None = None,
        close_result: object = _WINDOWS_CLOSE_RESULT_PENDING,
    ) -> None:
        # NtCreateFile writes directly into this lease-owned buffer. Every
        # caller can therefore observe ownership through ``handle`` even when
        # control flow is interrupted before the native call returns to its
        # immediate Python frame.
        self._handle_output = ctypes.c_void_p(handle)
        self.recorded_close_results = []
        self.close_retry_blocked = False
        self.pending_close_result_count = None
        if close_result is not _WINDOWS_CLOSE_RESULT_PENDING:
            self.recorded_close_results.append(_WindowsCloseObservation(close_result))

    @property
    def handle(self) -> int | None:
        return self._handle_output.value

    @handle.setter
    def handle(self, value: int | None) -> None:
        self._handle_output.value = value

    @property
    def close_result(self) -> object:
        if not self.recorded_close_results:
            return _WINDOWS_CLOSE_RESULT_PENDING
        return self.recorded_close_results[-1].status

    @close_result.setter
    def close_result(self, value: object) -> None:
        if value is _WINDOWS_CLOSE_RESULT_PENDING:
            self.recorded_close_results.clear()
            self.close_retry_blocked = False
            self.pending_close_result_count = None
        else:
            self.recorded_close_results.append(_WindowsCloseObservation(value))

    def prepare_native_output(self) -> Any:
        """Return an empty PHANDLE whose storage remains owned by this lease."""

        if self.handle is not None:
            raise ValueError("Windows handle lease is already occupied")
        self._handle_output.value = None
        self.recorded_close_results.clear()
        self.close_retry_blocked = False
        self.pending_close_result_count = None
        return ctypes.byref(self._handle_output)


@dataclass(slots=True)
class _WindowsReceiptPublicationLease:
    """Own transient receipt handles outside the helper exception tables."""

    api: Any
    stage: WindowsHandleLease = field(default_factory=WindowsHandleLease)
    transient_handles: list[WindowsHandleLease] = field(default_factory=lambda: list[WindowsHandleLease]())
    phase: Literal["staged", "unknown", "published"] = "staged"
    candidate: WindowsReceiptResult | None = None
    stage_disposition_attempted: bool = False
    _retained_handles: set[int] = field(default_factory=lambda: set[int]())

    def new_transient_handle(self) -> WindowsHandleLease:
        lease = WindowsHandleLease()
        self.transient_handles.append(lease)
        return lease

    @property
    def is_closed(self) -> bool:
        return self.stage.handle is None and all(lease.handle is None for lease in self.transient_handles)

    @property
    def outcome(self) -> WindowsReceiptOutcome | None:
        if self.phase == "staged" or self.candidate is None:
            return None
        return WindowsReceiptOutcome(self.phase, self.candidate)

    def prepare_stage(self) -> WindowsHandleLease:
        if self.stage.handle is not None:
            raise ValueError("Windows receipt staging lease is already occupied")
        self.phase = "staged"
        self.candidate = None
        self.stage_disposition_attempted = False
        return self.stage

    def dispose_stage(self) -> BaseException | None:
        handle = self.stage.handle
        if handle is None or self.phase != "staged" or self.stage_disposition_attempted:
            return None
        cleanup_error = _dispose_staged(self.api, handle)
        self.stage_disposition_attempted = True
        return cleanup_error

    def close(self) -> tuple[BaseException, ...]:
        failures: list[BaseException] = []

        def close_handle(lease: WindowsHandleLease, context: str) -> bool:
            lease_identity = id(lease)
            if lease_identity in self._retained_handles:
                return False
            failure_count = len(failures)
            for _attempt in range(2):
                try:
                    close_error = close_windows_handle_lease(
                        self.api,
                        lease,
                        None,
                        context,
                    )
                except BaseException as close_call_error:
                    failures.append(close_call_error)
                    if lease.handle is not None:
                        continue
                else:
                    if close_error is not None:
                        failures.append(close_error)
                        if lease.handle is not None:
                            self._retained_handles.add(lease_identity)
                    break
                break
            if lease.handle is not None and len(failures) == failure_count:
                failures.append(OSError(f"The {context} remained open after bounded cleanup attempts."))
            return lease.handle is None

        for transient in reversed(self.transient_handles):
            if not close_handle(transient, "receipt verification handle"):
                return tuple(failures)
        if self.stage.handle is not None and self.phase == "staged":
            try:
                cleanup_error = self.dispose_stage()
            except BaseException as cleanup_interruption:
                failures.append(cleanup_interruption)
                return tuple(failures)
            if cleanup_error is not None:
                failures.append(cleanup_error)
        close_handle(self.stage, "receipt staging handle")
        return tuple(failures)


class WindowsReceiptValidationError(ValueError):
    """A retained-handle target violated the identical-receipt contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _translated_windows_validation_error(
    error: BaseException,
    code: str,
    message: str,
) -> WindowsReceiptValidationError:
    """Translate a native contract failure without losing cleanup notes."""

    translated = WindowsReceiptValidationError(code, message)
    for note in getattr(error, "__notes__", ()):
        translated.add_note(note)
    return translated


class _DefiniteRenameError(OSError):
    """NtSetInformationFile returned a definite failure before renaming."""


class _DefiniteRenameCollision(FileExistsError):
    """NtSetInformationFile returned a definite destination collision."""


class _StageNameCollision(FileExistsError):
    """An unpredictable private staging name already existed."""


_INTERNAL_FAILURE_PROVENANCE = object()


def is_windows_publication_unavailable(error: BaseException) -> bool:
    """Return whether Win32 rejected a required retained-handle primitive."""

    return isinstance(error, OSError) and error.errno in _WINDOWS_PUBLICATION_UNAVAILABLE_ERRORS


def _is_windows_nonregular_receipt_open_error(error: BaseException) -> bool:
    return (
        isinstance(error, OSError)
        and getattr(error, "_windows_receipt_nt_status", None) in _WINDOWS_NONREGULAR_OPEN_STATUSES
        and getattr(error, "_windows_receipt_nt_operation", None) == "open receipt"
    )


@dataclass(frozen=True)
class _CleanupFailureRecord:
    provenance: object
    failures: tuple[BaseException, ...]


def _native_api() -> Any:
    if os.name != "nt":
        raise OSError("Win32 retained-handle receipt publication is unavailable")
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    api = win_dll("kernel32", use_last_error=True)
    return _configure_api(api)


def _native_nt_api() -> Any:
    if os.name != "nt":
        raise OSError("NT retained-handle relative opens are unavailable")
    win_dll = cast(Callable[..., Any], getattr(ctypes, "WinDLL"))
    return _configure_nt_api(win_dll("ntdll", use_last_error=True))


def _configure_api(api: Any) -> Any:
    """Declare the public Win32 ABI with fixed-width scalar types."""
    api.WriteFile.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        DWORD,
        ctypes.POINTER(DWORD),
        ctypes.c_void_p,
    )
    api.WriteFile.restype = ctypes.c_int
    api.ReadFile.argtypes = api.WriteFile.argtypes
    api.ReadFile.restype = ctypes.c_int
    api.FlushFileBuffers.argtypes = (ctypes.c_void_p,)
    api.FlushFileBuffers.restype = ctypes.c_int
    api.SetFilePointerEx.argtypes = (
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        DWORD,
    )
    api.SetFilePointerEx.restype = ctypes.c_int
    api.GetFileInformationByHandleEx.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        DWORD,
    )
    api.GetFileInformationByHandleEx.restype = ctypes.c_int
    api.SetFileInformationByHandle.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        DWORD,
    )
    api.SetFileInformationByHandle.restype = ctypes.c_int
    api.GetFileType.argtypes = (ctypes.c_void_p,)
    api.GetFileType.restype = DWORD
    api.CloseHandle.argtypes = (ctypes.c_void_p,)
    api.CloseHandle.restype = ctypes.c_int
    return api


def _configure_nt_api(api: Any) -> Any:
    """Declare the user-mode NT file ABI without host-C-width aliases."""
    api.NtCreateFile.argtypes = (
        ctypes.POINTER(ctypes.c_void_p),
        ULONG,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.POINTER(ctypes.c_int64),
        ULONG,
        ULONG,
        ULONG,
        ULONG,
        ctypes.c_void_p,
        ULONG,
    )
    api.NtCreateFile.restype = NTSTATUS
    api.NtSetInformationFile.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p,
        ULONG,
        FILE_INFORMATION_CLASS,
    )
    api.NtSetInformationFile.restype = NTSTATUS
    api.RtlNtStatusToDosError.argtypes = (NTSTATUS,)
    api.RtlNtStatusToDosError.restype = ULONG
    return api


def _nt_success(status: int) -> bool:
    return ctypes.c_int32(status).value >= 0


def _nt_status_bits(status: int) -> int:
    return ctypes.c_uint32(status).value


def _nt_failure(nt_api: Any, operation: str, status: int, leaf: str) -> OSError:
    code = int(nt_api.RtlNtStatusToDosError(ctypes.c_int32(status).value))
    message = f"NT {operation} failed with status 0x{_nt_status_bits(status):08X}"
    error_type = FileNotFoundError if code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND) else OSError
    error = error_type(code, message, leaf)
    setattr(error, "_windows_receipt_nt_operation", operation)
    setattr(error, "_windows_receipt_nt_status", _nt_status_bits(status))
    return error


@dataclass(frozen=True)
class _RelativeName:
    buffer: ctypes.Array[WCHAR]
    unicode: _UnicodeString
    attributes: _ObjectAttributes


def _validate_windows_relative_leaf(leaf: str) -> None:
    """Reject names that Win32 would reinterpret instead of opening exactly."""

    if not leaf or leaf in {".", ".."}:
        raise ValueError("Windows relative leaf must name one file")
    if leaf.endswith((" ", ".")):
        raise ValueError("Windows relative leaf must not end in an ASCII space or period")
    if any(character in _WINDOWS_RESERVED_LEAF_CHARACTERS or ord(character) < 0x20 for character in leaf):
        raise ValueError("Windows relative leaf contains a reserved character")

    # Win32 recognizes a DOS device before the first extension. It also
    # ignores ASCII spaces immediately before that extension, so reject the
    # cautious ``NUL .txt`` spelling without normalizing any Unicode text.
    device_basename = leaf.partition(".")[0].rstrip(" ").casefold()
    if device_basename in _WINDOWS_RESERVED_DEVICE_BASENAMES:
        raise ValueError("Windows relative leaf uses a reserved DOS device name")

    try:
        encoded = leaf.encode("utf-16-le")
    except UnicodeEncodeError as error:
        raise ValueError("Windows relative leaf must be UTF-16 encodable") from error
    if len(encoded) > 0xFFFC:
        raise ValueError("Windows relative leaf is too long for UNICODE_STRING")


def _native_name(root_handle: int | None, text: str) -> _RelativeName:
    try:
        encoded = text.encode("utf-16-le")
    except UnicodeEncodeError as error:
        raise ValueError("NT object name must be UTF-16 encodable") from error
    if len(encoded) > 0xFFFC:
        raise ValueError("NT object name is too long for UNICODE_STRING")

    storage_type = WCHAR * (len(encoded) // ctypes.sizeof(WCHAR) + 1)
    storage = storage_type()
    if encoded:
        ctypes.memmove(storage, encoded, len(encoded))
    name = _UnicodeString(len(encoded), len(encoded) + ctypes.sizeof(WCHAR), ctypes.addressof(storage))
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        root_handle,
        ctypes.pointer(name),
        OBJ_CASE_INSENSITIVE,
        None,
        None,
    )
    return _RelativeName(storage, name, attributes)


def _relative_name(parent_handle: int, leaf: str) -> _RelativeName:
    _validate_windows_relative_leaf(leaf)
    return _native_name(parent_handle, leaf)


def _nt_anchor_path(path: Path) -> str:
    text = os.fspath(path).replace("/", "\\")
    folded = text.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        suffix = text[8:]
        prefix = "\\??\\UNC\\"
        unc = True
    elif text.startswith("\\\\?\\"):
        suffix = text[4:]
        prefix = "\\??\\"
        unc = False
    elif text.startswith("\\\\"):
        suffix = text[2:]
        prefix = "\\??\\UNC\\"
        unc = True
    elif len(text) >= 3 and text[1] == ":" and text[2] == "\\":
        suffix = text
        prefix = "\\??\\"
        unc = False
    else:
        raise ValueError("Windows directory anchor must be an absolute drive or UNC path")
    if "\x00" in suffix:
        raise ValueError("Windows directory anchor is invalid")
    if unc:
        components = suffix.strip("\\").split("\\")
        if (
            len(components) != 2
            or not all(components)
            or any(component in {".", ".."} or ":" in component for component in components)
        ):
            raise ValueError("Windows UNC anchor must name exactly one server and share")
        suffix = "\\".join(components) + "\\"
    elif len(suffix) != 3 or suffix[1:] != ":\\" or not suffix[0].isascii() or not suffix[0].isalpha():
        raise ValueError("Windows drive anchor must name exactly one drive root")
    return prefix + suffix


def _relative_handle(
    kernel_api: Any,
    nt_api: Any,
    parent_handle: int | None,
    leaf: str,
    lease: WindowsHandleLease,
    *,
    desired_access: int,
    share_access: int,
    disposition: int,
    options: int,
    expected_information: tuple[int, ...],
    operation: str,
    stage_collision: bool = False,
    absolute_name: bool = False,
    retain_rejected_handle: bool = False,
) -> int:
    if not absolute_name:
        _validate_windows_relative_leaf(leaf)
    # A completed close deliberately retires the handle before resetting its
    # result marker. If control flow interrupted that reset, preparing the
    # empty lease normalizes the stale marker before the next native open.
    handle_output = lease.prepare_native_output()
    if not absolute_name and parent_handle is None:
        raise ValueError("Relative NT opens require a retained parent directory handle")
    relative = _native_name(None, leaf) if absolute_name else _relative_name(cast(int, parent_handle), leaf)
    io_status = _IoStatusBlock()
    invalid = ctypes.c_void_p(-1).value
    primary: BaseException | None = None
    result: int | None = None
    try:
        status = int(
            nt_api.NtCreateFile(
                handle_output,
                desired_access,
                ctypes.byref(relative.attributes),
                ctypes.byref(io_status),
                None,
                FILE_ATTRIBUTE_NORMAL,
                share_access,
                disposition,
                options,
                None,
                0,
            )
        )
        if not _nt_success(status):
            error = _nt_failure(nt_api, operation, status, leaf)
            if stage_collision and _nt_status_bits(status) == STATUS_OBJECT_NAME_COLLISION:
                collision = _StageNameCollision(error.errno, error.strerror, leaf)
                setattr(collision, "_windows_receipt_stage_provenance", _INTERNAL_FAILURE_PROVENANCE)
                raise collision from error
            raise error

        handle = lease.handle
        if handle is None or handle == invalid:
            raise OSError(f"NT {operation} returned no usable handle")
        lease.handle = handle
        completion_status = int(io_status.Status)
        if not _nt_success(completion_status):
            raise _nt_failure(nt_api, f"{operation} completion", completion_status, leaf)
        information = int(io_status.Information)
        if information not in expected_information:
            raise OSError(f"NT {operation} returned unexpected IO_STATUS_BLOCK.Information {information}")
        result = information
    except BaseException as error:
        primary = error
    finally:
        if primary is not None:
            acquired = lease.handle
            if acquired is not None and acquired != invalid:
                lease.handle = acquired
                # Cleanup retires the lease before the caller classifies the
                # failure, so preserve authenticated acquisition provenance.
                setattr(
                    primary,
                    "_windows_receipt_handle_acquired",
                    _INTERNAL_FAILURE_PROVENANCE,
                )
                if not retain_rejected_handle:
                    try:
                        close_windows_handle_lease(
                            kernel_api,
                            lease,
                            primary,
                            "rejected NT file handle",
                        )
                    except BaseException as close_interruption:
                        primary.add_note(f"Could not close rejected NT file handle: {close_interruption}")
    if primary is not None:
        raise primary
    assert result is not None
    return result


def _last_error(api: Any) -> int:
    getter: Any = getattr(api, "get_last_error", None)
    if callable(getter):
        return cast(int, getter())
    ctypes_getter = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
    return ctypes_getter()


def _set_last_error(api: Any, value: int) -> None:
    """Set the calling thread's Win32 error slot for native or modeled APIs."""

    setter: Any = getattr(api, "set_last_error", None)
    if callable(setter):
        setter(value)
        return
    ctypes_setter: Any = getattr(ctypes, "set_last_error", None)
    if not callable(ctypes_setter):
        raise OSError("Win32 SetLastError is unavailable")
    ctypes_setter(value)


def _failure(api: Any, operation: str) -> OSError:
    code = _last_error(api)
    return OSError(code, f"Win32 {operation} failed")


def _checked_file_type(api: Any, handle: int) -> int:
    """Return GetFileType while distinguishing valid UNKNOWN from failure."""

    _set_last_error(api, 0)
    file_type = int(api.GetFileType(handle))
    if file_type == FILE_TYPE_UNKNOWN:
        error_number = _last_error(api)
        if error_number:
            raise OSError(error_number, "Win32 GetFileType failed")
    return file_type


def _query_metadata(api: Any, handle: int) -> tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo]:
    values = (_FileBasicInfo(), _FileStandardInfo(), _FileIdInfo())
    for info_class, value in zip((FILE_BASIC_INFO, FILE_STANDARD_INFO, FILE_ID_INFO), values, strict=True):
        if not api.GetFileInformationByHandleEx(handle, info_class, ctypes.byref(value), ctypes.sizeof(value)):
            raise _failure(api, "GetFileInformationByHandleEx")
    return values


def _regular_metadata_is_canonical(
    api: Any,
    handle: int,
    values: tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo],
) -> bool:
    basic, standard, _identity_info = values
    return bool(
        _checked_file_type(api, handle) == FILE_TYPE_DISK
        and not basic.FileAttributes
        & (FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)
        and not standard.Directory
        and not standard.DeletePending
        and standard.NumberOfLinks == 1
    )


def _directory_metadata_is_canonical(
    api: Any,
    handle: int,
    values: tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo],
) -> bool:
    basic, standard, _identity_info = values
    return bool(
        _checked_file_type(api, handle) == FILE_TYPE_DISK
        and basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY
        and not basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT
        and standard.Directory
        and not standard.DeletePending
    )


def _metadata(api: Any, handle: int) -> tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo]:
    values = _query_metadata(api, handle)
    if not _regular_metadata_is_canonical(api, handle, values):
        raise OSError("Receipt handle is not one physical regular file")
    return values


def _identity(value: _FileIdInfo) -> tuple[int, bytes]:
    return int(value.VolumeSerialNumber), bytes(value.FileId.Identifier)


def _same_regular_metadata(
    before: tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo],
    after: tuple[_FileBasicInfo, _FileStandardInfo, _FileIdInfo],
) -> bool:
    return bool(
        _identity(before[2]) == _identity(after[2])
        and before[0].FileAttributes == after[0].FileAttributes
        and before[1].NumberOfLinks == after[1].NumberOfLinks
        and before[1].EndOfFile == after[1].EndOfFile
    )


def _write_all(api: Any, handle: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        chunk = ctypes.create_string_buffer(payload[offset:])
        written = DWORD()
        if not api.WriteFile(handle, chunk, len(payload) - offset, ctypes.byref(written), None):
            raise _failure(api, "WriteFile")
        if written.value <= 0 or written.value > len(payload) - offset:
            raise OSError("Win32 WriteFile made invalid progress")
        offset += written.value


def _read_exact(api: Any, handle: int, size: int) -> bytes:
    if not api.SetFilePointerEx(handle, 0, None, FILE_BEGIN):
        raise _failure(api, "SetFilePointerEx")
    output = bytearray()
    while len(output) < size:
        buffer = ctypes.create_string_buffer(size - len(output))
        read = DWORD()
        if not api.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            raise _failure(api, "ReadFile")
        if read.value > len(buffer):
            raise OSError("Win32 ReadFile returned more bytes than requested")
        if read.value == 0:
            raise OSError("Receipt staging bytes ended early")
        output.extend(buffer.raw[: read.value])
    extra = ctypes.create_string_buffer(1)
    read = DWORD()
    if not api.ReadFile(handle, extra, 1, ctypes.byref(read), None):
        raise _failure(api, "ReadFile EOF check")
    if read.value > 1:
        raise OSError("Win32 ReadFile EOF check returned an invalid byte count")
    if read.value:
        raise OSError("Receipt staging bytes exceed the expected payload")
    return bytes(output)


def _read_candidate(api: Any, handle: int, maximum: int) -> bytes:
    """Read through EOF, bounded one byte beyond the canonical payload."""
    if not api.SetFilePointerEx(handle, 0, None, FILE_BEGIN):
        raise _failure(api, "SetFilePointerEx")
    output = bytearray()
    while len(output) < maximum:
        buffer = ctypes.create_string_buffer(min(64 * 1024, maximum - len(output)))
        read = DWORD()
        if not api.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            raise _failure(api, "ReadFile")
        if read.value > len(buffer):
            raise OSError("Win32 ReadFile returned more bytes than requested")
        if read.value == 0:
            break
        output.extend(buffer.raw[: read.value])
    return bytes(output)


def _prepare_rename(leaf: str) -> tuple[ctypes.Array[ctypes.c_char], int]:
    _validate_windows_relative_leaf(leaf)
    encoded = leaf.encode("utf-16-le")
    # Microsoft requires at least sizeof(FILE_RENAME_INFORMATION) plus the
    # byte length of FileName, even though FileName[1] is part of sizeof.
    allocation_size = ctypes.sizeof(_FileRenameInformation) + len(encoded)
    storage = ctypes.create_string_buffer(allocation_size)
    rename = _FileRenameInformation.from_buffer(storage)
    rename.ReplaceIfExists = 0
    # This is the native FILE_RENAME_INFORMATION contract, not the public
    # FILE_RENAME_INFO wrapper contract. A simple name with a NULL root
    # renames within the open source handle's existing directory, so no
    # process-relative path is resolved during publication.
    rename.RootDirectory = None
    rename.FileNameLength = len(encoded)
    ctypes.memmove(
        ctypes.addressof(storage) + _FileRenameInformation.FileName.offset,
        encoded,
        len(encoded),
    )

    return storage, len(storage)


def _rename(
    nt_api: Any,
    handle: int,
    storage: ctypes.Array[ctypes.c_char],
    allocation_size: int,
    leaf: str,
) -> None:
    """Make one native rename call and authenticate only direct failures."""
    io_status = _IoStatusBlock()
    io_status.Status = ctypes.c_int32(STATUS_PENDING).value
    status = int(
        nt_api.NtSetInformationFile(
            handle,
            ctypes.byref(io_status),
            storage,
            allocation_size,
            FILE_RENAME_INFORMATION,
        )
    )
    if not _nt_success(status):
        error = _nt_failure(nt_api, "FileRenameInformation", status, leaf)
        if _nt_status_bits(status) == STATUS_OBJECT_NAME_COLLISION or error.errno in (
            ERROR_FILE_EXISTS,
            ERROR_ALREADY_EXISTS,
        ):
            collision = _DefiniteRenameCollision(error.errno, error.strerror, leaf)
            setattr(collision, "_windows_receipt_definite_provenance", _INTERNAL_FAILURE_PROVENANCE)
            raise collision from error
        failure = _DefiniteRenameError(error.errno, error.strerror, leaf)
        setattr(failure, "_windows_receipt_definite_provenance", _INTERNAL_FAILURE_PROVENANCE)
        raise failure from error
    if status != 0:
        raise _nt_failure(nt_api, "FileRenameInformation nonfinal return", status, leaf)
    completion_status = int(io_status.Status)
    if completion_status != 0:
        raise _nt_failure(
            nt_api,
            "FileRenameInformation completion",
            completion_status,
            leaf,
        )


def _is_internal_definite_rename_error(error: BaseException) -> bool:
    return isinstance(error, (_DefiniteRenameCollision, _DefiniteRenameError)) and (
        getattr(error, "_windows_receipt_definite_provenance", None) is _INTERNAL_FAILURE_PROVENANCE
    )


def is_internal_stage_name_collision(error: BaseException) -> bool:
    return isinstance(error, _StageNameCollision) and (
        getattr(error, "_windows_receipt_stage_provenance", None) is _INTERNAL_FAILURE_PROVENANCE
    )


def is_internal_definite_rename_collision(error: BaseException) -> bool:
    return isinstance(error, _DefiniteRenameCollision) and _is_internal_definite_rename_error(error)


def _add_cleanup_note(primary: BaseException, message: str, error: BaseException) -> None:
    failures = cleanup_failures_from_error(primary)
    record = _CleanupFailureRecord(_INTERNAL_FAILURE_PROVENANCE, (*failures, error))
    setattr(primary, "_windows_receipt_cleanup_record", record)
    primary.add_note(f"{message}: {error}")


def cleanup_failures_from_error(error: BaseException) -> tuple[BaseException, ...]:
    """Return explicit staging cleanup failures retained on a primary error."""

    value: object = getattr(error, "_windows_receipt_cleanup_record", None)
    if isinstance(value, _CleanupFailureRecord) and value.provenance is _INTERNAL_FAILURE_PROVENANCE:
        return value.failures
    return ()


def _dispose_staged(api: Any, handle: int) -> BaseException | None:
    """Attempt disposition inside a separate frame with an active handler."""
    try:
        disposition = _FileDispositionInfo(1)
        if not api.SetFileInformationByHandle(
            handle,
            FILE_DISPOSITION_INFO,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            raise _failure(api, "FileDispositionInfo")
    except BaseException as error:
        return error
    return None


def outcome_from_error(error: BaseException) -> WindowsReceiptOutcome | None:
    """Return retained namespace evidence attached to an uncertain failure."""
    value: object = getattr(error, "_windows_receipt_outcome", None)
    return value if isinstance(value, WindowsReceiptOutcome) else None


def _select_apis(api: Any | None, nt_api: Any | None) -> tuple[Any, Any]:
    selected_api = _native_api() if api is None else api
    if nt_api is not None:
        selected_nt_api = nt_api
    elif hasattr(selected_api, "NtCreateFile") and hasattr(selected_api, "RtlNtStatusToDosError"):
        # A combined injected API keeps modeled tests platform-independent.
        selected_nt_api = selected_api
    else:
        selected_nt_api = _native_nt_api()
    return selected_api, selected_nt_api


def _native_close_handle_address(api: Any) -> int | None:
    if getattr(ctypes, "WINFUNCTYPE", None) is None:
        return None
    try:
        return ctypes.cast(api.CloseHandle, ctypes.c_void_p).value
    except (TypeError, ValueError):
        return None


def _record_native_close_observation(
    lease: WindowsHandleLease,
    status: object,
) -> None:
    """Capture native result ownership before reading its saved last-error slot."""

    observation = _WindowsCloseObservation(status)
    lease.recorded_close_results.append(observation)
    try:
        getter: Any = getattr(ctypes, "get_last_error")
        observation.error = int(getter())
    except BaseException as error:
        observation.error = error
        raise


def _record_close_handle_result(
    api: Any,
    lease: WindowsHandleLease,
    handle: int,
    native_address: int | None,
) -> None:
    """Record a native close result in ``lease`` before Python resumes."""

    prototype_factory: Any | None = getattr(ctypes, "WINFUNCTYPE", None)
    if native_address is not None and prototype_factory is not None:

        class _CloseHandleResult(ctypes.c_int):
            pass

        setattr(
            _CloseHandleResult,
            "_check_retval_",
            functools.partial(_record_native_close_observation, lease),
        )
        prototype = prototype_factory(
            _CloseHandleResult,
            ctypes.c_void_p,
            use_last_error=True,
        )
        operation = prototype(native_address)
        operation(handle)
        return

    # Modeled APIs are Python callables, so they cannot provide the native
    # result-conversion hook. Ownership remains in the lease until this store.
    status = int(bool(api.CloseHandle(handle)))
    observation = _WindowsCloseObservation(status)
    lease.recorded_close_results.append(observation)
    if not status:
        try:
            observation.error = _last_error(api)
        except BaseException as error:
            observation.error = error
            raise


def close_windows_handle_lease(
    api: Any,
    lease: WindowsHandleLease,
    primary: BaseException | None,
    context: str,
) -> BaseException | None:
    handle = lease.handle
    if handle is None:
        return primary

    def retain_failure(error: BaseException, action: str = "close") -> None:
        nonlocal primary
        if primary is None:
            primary = error
        else:
            primary.add_note(f"Could not {action} {context}: {error}")

    native_address: int | None = None
    address_resolved = False
    address_attempts = 0
    native_call_attempts = 0
    recorded_index = 0
    while lease.handle is not None:
        if recorded_index >= len(lease.recorded_close_results):
            # Each retained handle accepts at most two definitive native
            # results across every caller and finalizer re-entry. Recorded FALSE
            # results remain in the lease so nested cleanup cannot reset that
            # bound and then close an older ancestor while this child is live.
            pending_result_was_recorded = (
                lease.close_retry_blocked
                and lease.pending_close_result_count is not None
                and len(lease.recorded_close_results) > lease.pending_close_result_count
            )
            if (
                (lease.close_retry_blocked and not pending_result_was_recorded)
                or len(lease.recorded_close_results) >= 2
                or native_call_attempts >= 2
            ):
                break
            if not address_resolved:
                while address_attempts < 2:
                    address_attempts += 1
                    try:
                        native_address = _native_close_handle_address(api)
                        address_resolved = True
                        break
                    except BaseException as close_error:
                        retain_failure(close_error, "resolve CloseHandle for")
                if not address_resolved:
                    break

            result_count = len(lease.recorded_close_results)
            native_call_attempts += 1
            # Arm the persistent no-retry state before entering CloseHandle.
            # If the call's result is not recorded, even an interruption at
            # the exception-handler boundary must leave every later owner and
            # finalizer unable to re-enter an operation whose effect is unknown.
            lease.close_retry_blocked = True
            lease.pending_close_result_count = result_count
            try:
                _record_close_handle_result(api, lease, handle, native_address)
            except BaseException as close_error:
                retain_failure(close_error)
                result_was_recorded = len(lease.recorded_close_results) > result_count
                # Once a CloseHandle callable was entered, absence of a recorded
                # result cannot prove whether control flow arrived before the OS
                # call or between its return and the result hook. Retain the
                # handle and prohibit all caller/finalizer re-entry.
                if not result_was_recorded:
                    break
            if len(lease.recorded_close_results) == result_count:
                retain_failure(
                    OSError("CloseHandle returned without recording its result")
                )
                break
            lease.close_retry_blocked = False
            lease.pending_close_result_count = None

        recorded = lease.recorded_close_results[recorded_index]
        raw_status: object = _WINDOWS_CLOSE_RESULT_PENDING
        for _attempt in range(2):
            try:
                candidate_status = getattr(recorded.status, "value", recorded.status)
                if not isinstance(candidate_status, int):
                    raise OSError("CloseHandle returned a non-integer result.")
                raw_status = candidate_status
                break
            except BaseException as close_error:
                retain_failure(close_error)

        if raw_status is _WINDOWS_CLOSE_RESULT_PENDING:
            # CloseHandle returned but its status cannot be interpreted. Keep
            # owning this child and prohibit another native call: either
            # retiring it or retrying could let an ancestor close while a live
            # child remains, or close a recycled handle value twice.
            lease.pending_close_result_count = None
            lease.close_retry_blocked = True
            break
        elif raw_status:
            # TRUE proves the handle is closed. Retire ownership before clearing
            # the result history so a return-boundary interruption can consume
            # the same proof without issuing CloseHandle again.
            for _attempt in range(2):
                try:
                    lease.handle = None
                except BaseException as close_error:
                    retain_failure(close_error)
                if lease.handle is None:
                    break
        else:
            # FALSE proves CloseHandle failed: surface it, keep owning the child,
            # and allow only the second result slot as a safe retry.
            failure_evidence = recorded.error
            if failure_evidence is _WINDOWS_CLOSE_ERROR_PENDING:
                try:
                    failure_evidence = _last_error(api)
                    recorded.error = failure_evidence
                except BaseException as close_error:
                    recorded.error = close_error
                    failure_evidence = close_error
            if isinstance(failure_evidence, BaseException):
                retain_failure(failure_evidence)
            elif isinstance(failure_evidence, int):
                retain_failure(OSError(failure_evidence, "Win32 CloseHandle failed"))
            else:
                retain_failure(OSError("CloseHandle failure evidence is invalid"))
            recorded_index += 1
            continue

        if lease.handle is None:
            for _attempt in range(2):
                try:
                    lease.recorded_close_results.clear()
                except BaseException as close_error:
                    retain_failure(close_error, "finalize")
                if not lease.recorded_close_results:
                    break
        break
    return primary


def read_windows_receipt(
    parent_handle: int,
    leaf: str,
    payload: bytes,
    *,
    api: Any | None = None,
    nt_api: Any | None = None,
    publication_lease: _WindowsReceiptPublicationLease,
) -> WindowsReceiptResult:
    """Read one child below a retained parent using caller-retained ownership."""
    _validate_windows_relative_leaf(leaf)
    if not payload:
        raise ValueError("receipt payload must not be empty")
    selected_api, selected_nt_api = _select_apis(api, nt_api)
    if publication_lease.api is not selected_api:
        raise ValueError("Windows receipt publication lease belongs to another API")
    lease = publication_lease.new_transient_handle()
    handle: int | None = None
    handle_acquired = False
    primary: BaseException | None = None
    result: WindowsReceiptResult | None = None
    try:
        try:
            _information = _relative_handle(
                selected_api,
                selected_nt_api,
                parent_handle,
                leaf,
                lease,
                desired_access=_TARGET_READ_ACCESS,
                share_access=FILE_SHARE_READ,
                disposition=FILE_OPEN,
                options=_FILE_OPEN_OPTIONS,
                expected_information=(FILE_OPENED,),
                operation="open receipt",
            )
            handle = lease.handle
            assert handle is not None
            handle_acquired = True
            before = _query_metadata(selected_api, handle)
            if not _regular_metadata_is_canonical(selected_api, handle, before):
                raise WindowsReceiptValidationError(
                    "output-existing-invalid",
                    f"Receipt output is not one canonical private regular file: {leaf}.",
                )
            observed = _read_candidate(selected_api, handle, len(payload) + 1)
            after = _query_metadata(selected_api, handle)
            if not _regular_metadata_is_canonical(selected_api, handle, after) or not _same_regular_metadata(
                before, after
            ):
                raise WindowsReceiptValidationError(
                    "output-changed",
                    f"Receipt output changed while it was being read: {leaf}.",
                )
            if before[1].EndOfFile != len(payload) or observed != payload:
                raise WindowsReceiptValidationError(
                    "output-different",
                    f"Refusing to replace different existing receipt output: {leaf}.",
                )
            result = WindowsReceiptResult(leaf, *_identity(after[2]), len(payload))
        except OSError as error:
            validation_started = handle_acquired or (
                getattr(error, "_windows_receipt_handle_acquired", None) is _INTERNAL_FAILURE_PROVENANCE
            )
            if not validation_started and isinstance(error, FileNotFoundError):
                raise
            if validation_started and (
                isinstance(error, FileNotFoundError) or error.errno in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}
            ):
                code = "output-changed"
                message = f"Receipt output changed while it was being verified: {leaf}."
            elif is_windows_publication_unavailable(error):
                code = "output-anchor-unavailable"
                message = "Windows retained-handle receipt verification is unavailable."
            elif _is_windows_nonregular_receipt_open_error(error):
                code = "output-existing-invalid"
                message = f"Receipt output is not one canonical private regular file: {leaf}."
            else:
                raise
            translated = _translated_windows_validation_error(error, code, message)
            raise translated from error
    except BaseException as error:
        primary = error
    finally:
        try:
            close_failures = publication_lease.close()
        except BaseException as close_interruption:
            if primary is None:
                primary = close_interruption
            else:
                primary.add_note(f"Could not close receipt verification handle: {close_interruption}")
        else:
            for close_error in close_failures:
                if primary is None:
                    primary = close_error
                else:
                    primary.add_note(f"Could not close receipt verification handle: {close_error}")
    if primary is not None:
        raise primary
    assert result is not None
    return result


def open_windows_directory_anchor(
    path: Path,
    lease: WindowsHandleLease,
    *,
    api: Any | None = None,
    nt_api: Any | None = None,
) -> WindowsDirectoryResult:
    """Open one trusted drive/UNC anchor while retaining async-safe ownership."""
    selected_api, selected_nt_api = _select_apis(api, nt_api)
    native_path = _nt_anchor_path(path)
    handle: int | None = None
    primary: BaseException | None = None
    result: WindowsDirectoryResult | None = None
    try:
        information = _relative_handle(
            selected_api,
            selected_nt_api,
            None,
            native_path,
            lease,
            desired_access=_DIRECTORY_ACCESS,
            share_access=FILE_SHARE_READ | FILE_SHARE_WRITE,
            disposition=FILE_OPEN,
            options=_DIRECTORY_OPEN_OPTIONS,
            expected_information=(FILE_OPENED,),
            operation="open directory anchor",
            absolute_name=True,
        )
        handle = lease.handle
        assert handle is not None
        before = _query_metadata(selected_api, handle)
        after = _query_metadata(selected_api, handle)
        if (
            not _directory_metadata_is_canonical(selected_api, handle, before)
            or not _directory_metadata_is_canonical(selected_api, handle, after)
            or _identity(before[2]) != _identity(after[2])
            or before[0].FileAttributes != after[0].FileAttributes
            or before[1].Directory != after[1].Directory
            or before[1].DeletePending != after[1].DeletePending
        ):
            raise WindowsReceiptValidationError(
                "output-parent-invalid",
                f"Receipt output anchor is not one stable physical directory: {path}.",
            )
        result = WindowsDirectoryResult(handle, *_identity(after[2]), information == FILE_CREATED)
    except BaseException as error:
        primary = error
    if primary is not None:
        try:
            close_windows_handle_lease(
                selected_api,
                lease,
                primary,
                "rejected directory anchor",
            )
        except BaseException as close_interruption:
            primary.add_note(f"Could not close rejected directory anchor: {close_interruption}")
        if is_windows_publication_unavailable(primary):
            translated = _translated_windows_validation_error(
                primary,
                "output-anchor-unavailable",
                "Windows retained-handle receipt directory binding is unavailable.",
            )
            raise translated from primary
        raise primary
    assert result is not None
    return result


def open_or_create_windows_directory(
    parent_handle: int,
    leaf: str,
    lease: WindowsHandleLease,
    *,
    api: Any | None = None,
    nt_api: Any | None = None,
) -> WindowsDirectoryResult:
    """Open or create one physical directory child relative to its retained parent."""
    _validate_windows_relative_leaf(leaf)
    selected_api, selected_nt_api = _select_apis(api, nt_api)
    handle: int | None = None
    primary: BaseException | None = None
    result: WindowsDirectoryResult | None = None
    try:
        information = _relative_handle(
            selected_api,
            selected_nt_api,
            parent_handle,
            leaf,
            lease,
            desired_access=_DIRECTORY_ACCESS,
            share_access=FILE_SHARE_READ | FILE_SHARE_WRITE,
            disposition=FILE_OPEN_IF,
            options=_DIRECTORY_OPEN_OPTIONS,
            expected_information=(FILE_OPENED, FILE_CREATED),
            operation="open or create directory",
        )
        handle = lease.handle
        assert handle is not None
        before = _query_metadata(selected_api, handle)
        after = _query_metadata(selected_api, handle)
        if (
            not _directory_metadata_is_canonical(selected_api, handle, before)
            or not _directory_metadata_is_canonical(selected_api, handle, after)
            or _identity(before[2]) != _identity(after[2])
            or before[0].FileAttributes != after[0].FileAttributes
            or before[1].Directory != after[1].Directory
            or before[1].DeletePending != after[1].DeletePending
        ):
            raise WindowsReceiptValidationError(
                "output-parent-invalid",
                f"Receipt output ancestor is not one stable physical directory: {leaf}.",
            )
        result = WindowsDirectoryResult(handle, *_identity(after[2]), information == FILE_CREATED)
    except BaseException as error:
        primary = error
    if primary is not None:
        try:
            close_windows_handle_lease(
                selected_api,
                lease,
                primary,
                "rejected directory handle",
            )
        except BaseException as close_interruption:
            primary.add_note(f"Could not close rejected directory handle: {close_interruption}")
        if is_windows_publication_unavailable(primary):
            translated = _translated_windows_validation_error(
                primary,
                "output-anchor-unavailable",
                "Windows retained-handle receipt directory binding is unavailable.",
            )
            raise translated from primary
        raise primary
    assert result is not None
    return result


def publish_windows_receipt(
    parent_handle: int,
    leaf: str,
    payload: bytes,
    *,
    api: Any | None = None,
    nt_api: Any | None = None,
    stage_token: str | None = None,
    publication_lease: _WindowsReceiptPublicationLease,
) -> WindowsReceiptResult:
    """Create, verify and rename one receipt using caller-retained ownership."""
    _validate_windows_relative_leaf(leaf)
    if not payload:
        raise ValueError("receipt payload must not be empty")
    rename_storage, rename_size = _prepare_rename(leaf)
    selected_api, selected_nt_api = _select_apis(api, nt_api)
    if publication_lease.api is not selected_api:
        raise ValueError("Windows receipt publication lease belongs to another API")
    token = secrets.token_hex(16) if stage_token is None else stage_token
    if not token or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("receipt staging token must be lowercase hexadecimal")
    stage_leaf = f".{leaf}.{token}.tmp"
    lease = publication_lease.prepare_stage()
    handle: int | None = None
    primary: BaseException | None = None
    result: WindowsReceiptResult | None = None
    candidate: WindowsReceiptResult | None = None
    try:
        try:
            try:
                _information = _relative_handle(
                    selected_api,
                    selected_nt_api,
                    parent_handle,
                    stage_leaf,
                    lease,
                    desired_access=_STAGE_ACCESS,
                    share_access=FILE_SHARE_READ,
                    disposition=FILE_CREATE,
                    options=_FILE_OPEN_OPTIONS,
                    expected_information=(FILE_CREATED,),
                    operation="create receipt staging file",
                    stage_collision=True,
                    retain_rejected_handle=True,
                )
                handle = lease.handle
                assert handle is not None
                before = _metadata(selected_api, handle)
                if before[1].EndOfFile != 0:
                    raise OSError("New receipt staging file was not empty")
                _write_all(selected_api, handle, payload)
                if not selected_api.FlushFileBuffers(handle):
                    raise _failure(selected_api, "FlushFileBuffers")
                if _read_exact(selected_api, handle, len(payload)) != payload:
                    raise OSError("Receipt staging bytes do not match the canonical payload")
                after = _metadata(selected_api, handle)
                if (
                    _identity(before[2]) != _identity(after[2])
                    or before[0].FileAttributes != after[0].FileAttributes
                    or before[1].NumberOfLinks != after[1].NumberOfLinks
                    or after[1].EndOfFile != len(payload)
                ):
                    raise OSError("Receipt staging identity, attributes, links, or size changed")
                candidate = WindowsReceiptResult(leaf, *_identity(after[2]), len(payload))
                publication_lease.candidate = candidate
                # From this point until a directly returned failing NTSTATUS,
                # namespace outcome is unknown and must never be disposed.
                publication_lease.phase = "unknown"
                _rename(selected_nt_api, handle, rename_storage, rename_size, leaf)
                publication_lease.phase = "published"
                if _read_exact(selected_api, handle, len(payload)) != payload:
                    raise OSError("Published receipt bytes do not match the canonical payload")
                published = _metadata(selected_api, handle)
                if (
                    _identity(published[2]) != (candidate.volume_serial_number, candidate.file_id)
                    or published[0].FileAttributes != after[0].FileAttributes
                    or published[1].NumberOfLinks != after[1].NumberOfLinks
                    or published[1].EndOfFile != len(payload)
                ):
                    raise OSError("Published receipt identity, attributes, links, or size changed")
                result = candidate
            except BaseException as error:
                primary = error
                if _is_internal_definite_rename_error(error):
                    publication_lease.phase = "staged"
                if publication_lease.phase != "staged" and outcome_from_error(error) is None and candidate is not None:
                    setattr(
                        error,
                        "_windows_receipt_outcome",
                        WindowsReceiptOutcome(publication_lease.phase, candidate),
                    )

            staged_handle = lease.handle
            if staged_handle is not None and publication_lease.phase == "staged":
                cleanup_error = publication_lease.dispose_stage()
                if cleanup_error is not None:
                    if primary is None:
                        primary = cleanup_error
                    else:
                        _add_cleanup_note(
                            primary,
                            "Could not mark receipt staging file for deletion",
                            cleanup_error,
                        )
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                _add_cleanup_note(primary, "Receipt staging cleanup was interrupted", error)
            if publication_lease.phase != "staged" and outcome_from_error(error) is None and candidate is not None:
                setattr(
                    error,
                    "_windows_receipt_outcome",
                    WindowsReceiptOutcome(publication_lease.phase, candidate),
                )
    finally:
        active_error = sys.exception()
        if active_error is not None and primary is None:
            primary = active_error
        if (
            active_error is not None
            and publication_lease.phase != "staged"
            and outcome_from_error(active_error) is None
            and candidate is not None
        ):
            setattr(
                active_error,
                "_windows_receipt_outcome",
                WindowsReceiptOutcome(publication_lease.phase, candidate),
            )
        try:
            close_failures = publication_lease.close()
        except BaseException as close_interruption:
            if primary is None:
                primary = close_interruption
            else:
                _add_cleanup_note(primary, "Could not close receipt staging handle", close_interruption)
        else:
            for close_error in close_failures:
                if primary is None:
                    primary = close_error
                else:
                    _add_cleanup_note(primary, "Could not close receipt staging handle", close_error)
    if primary is not None:
        if result is not None and outcome_from_error(primary) is None:
            setattr(primary, "_windows_receipt_outcome", WindowsReceiptOutcome("published", result))
        raise primary
    assert result is not None
    return result
