"""Anchored, no-overwrite byte publication for isolated repository scripts.

This private module is deliberately stdlib-only. Callers retain responsibility
for serialization, size limits, and translating stable publication error codes
into their own CLI error taxonomy.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import functools
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Callable, Literal, Protocol, cast
import weakref


class AnchoredOutputError(ValueError):
    """An anchored output path or publication violated the output contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _translated_anchored_output_error(
    error: BaseException,
    code: str,
    message: str,
) -> AnchoredOutputError:
    """Translate a contract-boundary failure without losing cleanup notes."""

    translated = AnchoredOutputError(code, message)
    for note in getattr(error, "__notes__", ()):
        translated.add_note(note)
    return translated


class _PublicationResourceLease(Protocol):
    @property
    def is_closed(self) -> bool: ...

    def close(self) -> tuple[BaseException, ...]: ...


class _LeaseFinalizer(Protocol):
    @property
    def alive(self) -> bool: ...

    def detach(self) -> object | None: ...


_WINDOWS_FILE_READ_ATTRIBUTES = 0x00000080
_WINDOWS_FILE_TRAVERSE = 0x00000020
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_FILE_SHARE_WRITE = 0x00000002
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_FILE_TYPE_DISK = 1
_WINDOWS_FILE_BASIC_INFO_CLASS = 0
_WINDOWS_FILE_ID_INFO_CLASS = 18

_POSIX_NATIVE_RESULT_PENDING = object()
_POSIX_RECEIPT_NAMESPACE_CHANGED_ERRNOS = frozenset({errno.ENOENT, errno.ELOOP})
_DARWIN_ACL_TYPE_EXTENDED = 0x00000100
_DARWIN_ACL_EXTENDED_ALLOW = 1
_DARWIN_ACL_EXTENDED_DENY = 2
_DARWIN_ACL_FIRST_ENTRY = 0
_DARWIN_ACL_NEXT_ENTRY = -1
_DARWIN_ACL_MAX_ENTRIES = 128
_DARWIN_ACL_UNAVAILABLE_ERRNOS = frozenset(
    {
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.ENOSYS),
        getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
    }
)
_posix_libc_cache: Any | None = None


def _posix_libc() -> Any:
    global _posix_libc_cache
    if _posix_libc_cache is None:
        _posix_libc_cache = ctypes.CDLL(None, use_errno=True)
    return _posix_libc_cache


def _native_int_result(value: object) -> int:
    raw = getattr(value, "value", value)
    if not isinstance(raw, int):
        raise OSError("Native descriptor operation returned a non-integer result.")
    return raw


@dataclass(slots=True)
class _DarwinAclQueryState:
    """Record ACL ownership independently of the frame performing the query."""

    free_acl: Any
    acl_result: object = _POSIX_NATIVE_RESULT_PENDING
    acl_errno: int = 0
    free_result: object = _POSIX_NATIVE_RESULT_PENDING
    free_errno: int = 0

    @property
    def pointer(self) -> int | None:
        if self.acl_result is _POSIX_NATIVE_RESULT_PENDING:
            return None
        value = getattr(self.acl_result, "value", self.acl_result)
        if value is None:
            return None
        if not isinstance(value, int):
            raise OSError("Native ACL query returned a non-pointer result.")
        return value


def _close_darwin_acl_query_state(
    state: _DarwinAclQueryState,
) -> BaseException | None:
    """Release one ACL allocation without replaying a recorded native free."""

    pointer = state.pointer
    if pointer is None:
        return None

    free_call_failures: list[BaseException] = []
    for _attempt in range(2):
        if state.free_result is not _POSIX_NATIVE_RESULT_PENDING:
            break
        try:

            class _AclFreeResult(ctypes.c_int):
                pass

            setattr(
                _AclFreeResult,
                "_check_retval_",
                functools.partial(setattr, state, "free_result"),
            )
            free_acl = state.free_acl
            free_acl.argtypes = (ctypes.c_void_p,)
            free_acl.restype = _AclFreeResult
            ctypes.set_errno(0)
            free_acl(ctypes.c_void_p(pointer))
            state.free_errno = ctypes.get_errno()
        except BaseException as free_call_error:
            free_call_failures.append(free_call_error)
            continue

    if state.free_result is _POSIX_NATIVE_RESULT_PENDING:
        if free_call_failures:
            free_error = free_call_failures[0]
            for later_error in free_call_failures[1:]:
                free_error.add_note(f"ACL release retry failure: {later_error}")
            return free_error
        return AnchoredOutputError(
            "output-anchor-unavailable",
            "Native macOS ACL release returned without recording its result.",
        )

    raw_free_result = state.free_result
    free_errno = state.free_errno
    # The native call has completed. Retire the pointer before interpreting or
    # reporting the result so neither an explicit retry nor the finalizer can
    # release the same allocation twice after a return-boundary interruption.
    state.acl_result = _POSIX_NATIVE_RESULT_PENDING
    state.free_result = _POSIX_NATIVE_RESULT_PENDING
    free_status = _native_int_result(raw_free_result)
    native_free_error: BaseException | None = None
    if free_status != 0:
        error_number = free_errno or errno.EIO
        native_free_error = AnchoredOutputError(
            "output-anchor-unavailable",
            "The macOS descriptor ACL query could not be released safely.",
        )
        native_free_error.__cause__ = OSError(error_number, os.strerror(error_number))
    if free_call_failures:
        free_error = free_call_failures[0]
        for later_error in free_call_failures[1:]:
            free_error.add_note(f"ACL release retry failure: {later_error}")
        if native_free_error is not None:
            free_error.add_note(f"Native ACL release failure: {native_free_error}")
        return free_error
    return native_free_error


def _finalize_darwin_acl_query(state: _DarwinAclQueryState) -> None:
    """Best-effort fallback when ACL-query frame cleanup is interrupted."""

    try:
        _close_darwin_acl_query_state(state)
    except BaseException:
        # A finalizer cannot safely replace the exception that abandoned the
        # owning query frame. The cleanup attempt itself remains bounded.
        pass


@dataclass(slots=True, weakref_slot=True, init=False)
class _DarwinAclQueryLease:
    """Weak-referenceable owner for separately retained ACL query state."""

    _state: _DarwinAclQueryState
    _finalizer: _LeaseFinalizer

    def __init__(self, free_acl: Any) -> None:
        state = _DarwinAclQueryState(free_acl=free_acl)
        self._state = state
        # The callback retains only the separate state, never this owner.
        self._finalizer = cast(
            _LeaseFinalizer,
            weakref.finalize(self, _finalize_darwin_acl_query, state),
        )

    @property
    def state(self) -> _DarwinAclQueryState:
        return self._state

    def close(self) -> BaseException | None:
        free_error = _close_darwin_acl_query_state(self._state)
        if self._state.pointer is None:
            self._finalizer.detach()
        return free_error


def _darwin_descriptor_has_extended_acl(
    descriptor: int,
    *,
    error_code: str = "output-anchor-unavailable",
    context: str = "retained macOS descriptor",
    allow_deny_only: bool = False,
) -> bool:
    """Return whether a Darwin descriptor has a disallowed extended ACL."""

    if sys.platform != "darwin":
        return False
    libc = _posix_libc()
    try:
        get_acl: Any = libc["acl_get_fd_np"]
        free_acl: Any = libc["acl_free"]
        valid_acl: Any | None = libc["acl_valid_fd_np"] if allow_deny_only else None
        get_entry: Any | None = libc["acl_get_entry"] if allow_deny_only else None
        get_tag_type: Any | None = libc["acl_get_tag_type"] if allow_deny_only else None
    except (AttributeError, KeyError) as error:
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "macOS descriptor ACL inspection is unavailable.",
        ) from error

    lease = _DarwinAclQueryLease(free_acl)
    state = lease.state

    class _AclResult(ctypes.c_void_p):
        pass

    setattr(
        _AclResult,
        "_check_retval_",
        functools.partial(setattr, state, "acl_result"),
    )
    get_acl.argtypes = (ctypes.c_int, ctypes.c_int)
    get_acl.restype = _AclResult
    ctypes.set_errno(0)
    primary_error: BaseException | None = None
    try:
        get_acl(descriptor, _DARWIN_ACL_TYPE_EXTENDED)
        state.acl_errno = ctypes.get_errno()
        pointer = state.pointer
        if pointer is None:
            if state.acl_result is _POSIX_NATIVE_RESULT_PENDING:
                raise OSError("Native ACL query returned without recording its result.")
            if state.acl_errno == errno.ENOENT:
                return False
            error_number = state.acl_errno or errno.EIO
            if error_number in _DARWIN_ACL_UNAVAILABLE_ERRNOS:
                raise AnchoredOutputError(
                    "output-anchor-unavailable",
                    f"The filesystem does not support extended-ACL inspection for the {context}.",
                ) from OSError(error_number, os.strerror(error_number))
            raise AnchoredOutputError(
                error_code,
                f"Could not inspect the {context} for extended ACLs: "
                f"[Errno {error_number}] {os.strerror(error_number)}.",
            ) from OSError(error_number, os.strerror(error_number))
        if not allow_deny_only:
            return True

        assert valid_acl is not None
        assert get_entry is not None
        assert get_tag_type is not None
        acl_pointer = ctypes.c_void_p(pointer)
        valid_acl.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        valid_acl.restype = ctypes.c_int
        ctypes.set_errno(0)
        validity_status = _native_int_result(
            valid_acl(descriptor, _DARWIN_ACL_TYPE_EXTENDED, acl_pointer)
        )
        validity_errno = ctypes.get_errno()
        if validity_status != 0:
            error_number = validity_errno or errno.EINVAL
            if error_number not in _DARWIN_ACL_UNAVAILABLE_ERRNOS:
                raise AnchoredOutputError(
                    error_code,
                    f"Could not validate the extended ACL for the {context}: "
                    f"[Errno {error_number}] {os.strerror(error_number)}.",
                ) from OSError(error_number, os.strerror(error_number))
            try:
                structurally_valid_acl: Any = libc["acl_valid"]
            except (AttributeError, KeyError) as error:
                raise AnchoredOutputError(
                    "output-anchor-unavailable",
                    "macOS structural ACL validation is unavailable.",
                ) from error
            structurally_valid_acl.argtypes = (ctypes.c_void_p,)
            structurally_valid_acl.restype = ctypes.c_int
            ctypes.set_errno(0)
            structural_status = _native_int_result(
                structurally_valid_acl(acl_pointer)
            )
            structural_errno = ctypes.get_errno()
            if structural_status != 0:
                structural_error_number = structural_errno or errno.EINVAL
                raise AnchoredOutputError(
                    error_code,
                    f"Could not structurally validate the extended ACL for the {context}: "
                    f"[Errno {structural_error_number}] "
                    f"{os.strerror(structural_error_number)}.",
                ) from OSError(
                    structural_error_number,
                    os.strerror(structural_error_number),
                )

        get_entry.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )
        get_entry.restype = ctypes.c_int
        get_tag_type.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        )
        get_tag_type.restype = ctypes.c_int
        selector = _DARWIN_ACL_FIRST_ENTRY
        entries_seen = 0
        while True:
            entry = ctypes.c_void_p()
            ctypes.set_errno(0)
            entry_status = _native_int_result(
                get_entry(
                    acl_pointer,
                    selector,
                    ctypes.byref(entry),
                )
            )
            entry_errno = ctypes.get_errno()
            if entry_status == -1 and entry_errno == errno.EINVAL:
                # acl_get_entry(3) reports end-of-list as -1/EINVAL. A
                # non-null extended ACL that cannot produce even one entry is
                # malformed for this allow-deny classification and is unsafe.
                return entries_seen == 0
            if entry_status != 0 or entry.value is None:
                error_number = entry_errno or errno.EIO
                raise AnchoredOutputError(
                    error_code,
                    f"Could not enumerate the extended ACL for the {context}: "
                    f"[Errno {error_number}] {os.strerror(error_number)}.",
                ) from OSError(error_number, os.strerror(error_number))
            if entries_seen >= _DARWIN_ACL_MAX_ENTRIES:
                raise AnchoredOutputError(
                    error_code,
                    f"The extended ACL for the {context} exceeds the supported entry limit.",
                )
            entries_seen += 1

            tag_type = ctypes.c_int()
            ctypes.set_errno(0)
            tag_status = _native_int_result(
                get_tag_type(entry, ctypes.byref(tag_type))
            )
            tag_errno = ctypes.get_errno()
            if tag_status != 0:
                error_number = tag_errno or errno.EIO
                raise AnchoredOutputError(
                    error_code,
                    f"Could not inspect an extended ACL entry for the {context}: "
                    f"[Errno {error_number}] {os.strerror(error_number)}.",
                ) from OSError(error_number, os.strerror(error_number))
            if tag_type.value == _DARWIN_ACL_EXTENDED_ALLOW:
                return True
            if tag_type.value != _DARWIN_ACL_EXTENDED_DENY:
                return True
            selector = _DARWIN_ACL_NEXT_ENTRY
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            free_error = lease.close()
        except BaseException as close_error:
            free_error = close_error
        if free_error is not None:
            if primary_error is not None:
                primary_error.add_note(f"Could not release a macOS descriptor ACL query: {free_error}")
            else:
                raise free_error


def _validate_safe_posix_directory_descriptor(
    descriptor: int,
    *,
    code: str,
    context: str,
    require_private: bool = False,
    allow_darwin_deny_only_acl: bool = False,
) -> os.stat_result:
    """Validate a retained directory before using its mutable namespace.

    Same-UID processes and root remain outside the enforceable threat model.
    """

    value = os.fstat(descriptor)
    mode = stat.S_IMODE(value.st_mode)
    owner_is_trusted = value.st_uid in {0, os.geteuid()}
    safe_permissions = not bool(mode & 0o022) or (
        bool(mode & stat.S_ISVTX) and owner_is_trusted
    )
    if require_private:
        owner_is_trusted = value.st_uid == os.geteuid()
        safe_permissions = mode == 0o700
    if (
        not stat.S_ISDIR(value.st_mode)
        or not owner_is_trusted
        or not safe_permissions
        or _darwin_descriptor_has_extended_acl(
            descriptor,
            error_code=code,
            context=context,
            allow_deny_only=allow_darwin_deny_only_acl,
        )
    ):
        raise AnchoredOutputError(
            code,
            f"The {context} is not a safely owned directory without unsafe permissions or extended ACLs.",
        )
    return value


@dataclass(slots=True)
class _PosixDescriptorLease:
    """Preallocated ownership slot populated before a native call returns."""

    descriptor_result: object | None = None
    close_result: object = _POSIX_NATIVE_RESULT_PENDING

    @property
    def descriptor(self) -> int | None:
        if self.descriptor_result is None:
            return None
        value = _native_int_result(self.descriptor_result)
        return value if value >= 0 else None

    def close(self) -> None:
        raw_descriptor = self.descriptor_result
        if raw_descriptor is None:
            return
        descriptor = _native_int_result(raw_descriptor)
        if descriptor < 0:
            self.descriptor_result = None
            self.close_result = _POSIX_NATIVE_RESULT_PENDING
            return

        if self.close_result is _POSIX_NATIVE_RESULT_PENDING:

            class _CloseResult(ctypes.c_int):
                pass

            setattr(
                _CloseResult,
                "_check_retval_",
                functools.partial(setattr, self, "close_result"),
            )
            operation: Any = _posix_libc()["close"]
            operation.argtypes = (ctypes.c_int,)
            operation.restype = _CloseResult
            operation(descriptor)

        status = _native_int_result(self.close_result)
        # The native call has completed. Retire the descriptor number before
        # reporting its result so an interrupted caller can never close a
        # subsequently reused descriptor on retry.
        self.descriptor_result = None
        self.close_result = _POSIX_NATIVE_RESULT_PENDING
        if status != 0:
            error_number = ctypes.get_errno() or errno.EIO
            raise OSError(error_number, os.strerror(error_number))


def _open_posix_descriptor(
    lease: _PosixDescriptorLease,
    path: os.PathLike[str] | str,
    flags: int,
    mode: int = 0o777,
    *,
    dir_fd: int | None = None,
) -> int:
    """Open through ``openat`` while transferring the result into ``lease``."""

    if lease.descriptor_result is not None:
        raise ValueError("POSIX descriptor lease is already occupied.")
    # A completed close retires the descriptor before clearing its native
    # result marker. If control flow interrupted between those two stores, the
    # marker is stale but there is no live resource. Normalize it before this
    # lease is reused so the next close cannot mistake the old result for the
    # new descriptor's close result.
    if lease.close_result is not _POSIX_NATIVE_RESULT_PENDING:
        lease.close_result = _POSIX_NATIVE_RESULT_PENDING
    encoded = os.fsencode(path)
    if b"\x00" in encoded:
        raise ValueError("POSIX descriptor path must not contain NUL.")
    directory_descriptor = (-2 if sys.platform == "darwin" else -100) if dir_fd is None else dir_fd
    while True:

        class _OpenResult(ctypes.c_int):
            pass

        setattr(
            _OpenResult,
            "_check_retval_",
            functools.partial(setattr, lease, "descriptor_result"),
        )
        operation: Any = _posix_libc()["openat"]
        # ``mode`` is variadic. Declaring only the three fixed arguments is
        # required by ctypes on Apple arm64; Linux expects an unsigned mode.
        operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
        operation.restype = _OpenResult
        mode_argument = ctypes.c_uint(mode) if sys.platform.startswith("linux") else ctypes.c_int(mode)
        operation(directory_descriptor, encoded, flags, mode_argument)
        raw_result = lease.descriptor_result
        if raw_result is None:
            raise OSError("Native openat returned without recording descriptor ownership.")
        descriptor = _native_int_result(raw_result)
        if descriptor >= 0:
            return descriptor
        error_number = ctypes.get_errno() or errno.EIO
        lease.descriptor_result = None
        if error_number == errno.EINTR:
            continue
        raise OSError(error_number, os.strerror(error_number), os.fsdecode(encoded))


def _close_posix_descriptor_lease(
    lease: _PosixDescriptorLease,
    primary: BaseException | None,
    context: str,
) -> BaseException | None:
    """Close once, retrying only a pre-call control-flow interruption."""

    for _attempt in range(2):
        try:
            if lease.descriptor is None:
                break
            lease.close()
        except BaseException as close_error:
            if primary is None:
                primary = close_error
            else:
                primary.add_note(f"Could not close {context}: {close_error}")
    return primary


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


def descriptor_relative_output_supported() -> bool:
    return (
        os.name != "nt"
        and bool(getattr(os, "O_DIRECTORY", 0))
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and os.stat in os.supports_follow_symlinks
        and all(operation in os.supports_dir_fd for operation in (os.open, os.stat, os.link, os.unlink))
    )


def _path_is_redirected(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(os.fspath(path))


def _windows_extended_path(path: Path) -> str:
    absolute_path = os.path.abspath(path)
    if absolute_path.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute_path
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _windows_file_api() -> Any:
    if os.name != "nt":
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "Win32 output-directory handles are unavailable on this platform.",
        )
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


def _windows_handle_identity(kernel32: Any, handle: int) -> tuple[int, int]:
    identity_info = _WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_ID_INFO_CLASS,
        ctypes.byref(identity_info),
        ctypes.sizeof(identity_info),
    ):
        raise OSError("Could not identify the snapshot output directory handle.")
    return (
        int(identity_info.VolumeSerialNumber),
        int.from_bytes(bytes(identity_info.FileId.Identifier), "little"),
    )


def _windows_directory_attributes(kernel32: Any, handle: int) -> int:
    basic_info = _WindowsFileBasicInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _WINDOWS_FILE_BASIC_INFO_CLASS,
        ctypes.byref(basic_info),
        ctypes.sizeof(basic_info),
    ):
        raise OSError("Could not inspect the snapshot output directory handle.")
    return int(basic_info.FileAttributes)


def _open_windows_directory_handle(
    kernel32: Any,
    path: Path,
    expected_identity: tuple[int, int],
) -> int:
    handle = kernel32.CreateFileW(
        _windows_extended_path(path),
        _WINDOWS_FILE_TRAVERSE | _WINDOWS_FILE_READ_ATTRIBUTES,
        _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise OSError(f"Could not bind snapshot output directory: {path}.")
    handle_value = cast(int, handle)
    try:
        path_stat = path.lstat()
        attributes = _windows_directory_attributes(kernel32, handle_value)
        if (
            kernel32.GetFileType(handle_value) != _WINDOWS_FILE_TYPE_DISK
            or _path_is_redirected(path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
            or _windows_handle_identity(kernel32, handle_value) != expected_identity
            or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
            or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError(f"Snapshot output directory changed: {path}.")
    except BaseException as error:
        try:
            if not kernel32.CloseHandle(handle_value):
                error.add_note("Could not close the rejected snapshot output directory handle.")
        except BaseException as cleanup_error:
            error.add_note(f"Could not close the rejected snapshot output directory handle: {cleanup_error}")
        raise
    return handle_value


@dataclass
class OutputParentBinding:
    checkout: Path
    parent: Path
    leaf: str
    strategy: Literal["posix-dir-fd", "windows-handle"]
    descriptors: list[int] | tuple[int, ...] = ()
    links: list[tuple[int, str, int]] | tuple[tuple[int, str, int], ...] = ()
    windows_api: Any | None = None
    windows_entries: list[tuple[Path, tuple[int, int], int]] | tuple[tuple[Path, tuple[int, int], int], ...] = ()
    descriptor_leases: list[_PosixDescriptorLease] | tuple[_PosixDescriptorLease, ...] = field(
        default=(),
        kw_only=True,
    )
    windows_handle_leases: list[Any] | tuple[Any, ...] = field(
        default=(),
        kw_only=True,
    )
    receipt_parent_policy: bool = field(default=False, kw_only=True)
    private_posix_descriptor_indexes: list[int] | tuple[int, ...] = field(
        default=(),
        kw_only=True,
    )
    _closed: bool = field(default=False, init=False)

    @property
    def is_closed(self) -> bool:
        """Return whether every retained descriptor or handle is retired."""

        return self._closed

    def close(self) -> tuple[BaseException, ...]:
        if self._closed:
            return ()
        failures: list[BaseException] = []
        if self.descriptor_leases:
            for descriptor_lease in reversed(self.descriptor_leases):
                close_call_failures: list[BaseException] = []
                close_error: BaseException | None = None
                for _attempt in range(2):
                    try:
                        close_error = _close_posix_descriptor_lease(
                            descriptor_lease,
                            None,
                            "receipt output directory descriptor",
                        )
                    except BaseException as error:
                        close_call_failures.append(error)
                        if descriptor_lease.descriptor is not None:
                            continue
                    break
                failures.extend(close_call_failures)
                if close_error is not None:
                    failures.append(close_error)
                try:
                    descriptor_closed = descriptor_lease.descriptor is None
                except BaseException as status_error:
                    failures.append(status_error)
                    descriptor_closed = False
                if not descriptor_closed:
                    if not close_call_failures and close_error is None:
                        failures.append(
                            AnchoredOutputError(
                                "output-cleanup-retained",
                                "A receipt output directory descriptor remained open after bounded cleanup attempts.",
                            )
                        )
                    # Preserve strict lifetime order: an ancestor must remain
                    # retained while its newer child descriptor is still live.
                    return tuple(failures)
        else:
            for descriptor in reversed(self.descriptors):
                try:
                    os.close(descriptor)
                except BaseException as error:
                    failures.append(error)
        if self.windows_api is not None and self.windows_handle_leases:
            try:
                windows_receipt = _windows_receipt_module()
            except BaseException as error:
                failures.append(error)
            else:
                for handle_lease in reversed(self.windows_handle_leases):
                    close_call_failures: list[BaseException] = []
                    close_error: BaseException | None = None
                    for _attempt in range(2):
                        try:
                            close_error = windows_receipt.close_windows_handle_lease(
                                self.windows_api,
                                handle_lease,
                                None,
                                "receipt output directory handle",
                            )
                        except BaseException as error:
                            close_call_failures.append(error)
                            if handle_lease.handle is not None:
                                continue
                        break
                    failures.extend(close_call_failures)
                    if close_error is not None:
                        failures.append(close_error)
                    if handle_lease.handle is not None:
                        if not close_call_failures and close_error is None:
                            failures.append(
                                AnchoredOutputError(
                                    "output-cleanup-retained",
                                    "A receipt output directory handle remained open after bounded cleanup attempts.",
                                )
                            )
                        # Preserve strict lifetime order: an ancestor must remain
                        # retained while its newer child handle is still live.
                        return tuple(failures)
        elif self.windows_api is not None:
            for _path, _identity, handle in reversed(self.windows_entries):
                try:
                    if not self.windows_api.CloseHandle(handle):
                        failures.append(OSError("Could not close a snapshot output directory handle."))
                except BaseException as error:
                    failures.append(error)
        if self.receipt_parent_policy or self.descriptor_leases or self.windows_handle_leases:
            self._closed = not any(
                descriptor_lease.descriptor is not None for descriptor_lease in self.descriptor_leases
            ) and not any(handle_lease.handle is not None for handle_lease in self.windows_handle_leases)
        return tuple(failures)

    def verify(self) -> None:
        if self.strategy == "posix-dir-fd":
            if not self.receipt_parent_policy:
                root_stat = self.checkout.lstat()
                opened_root = os.fstat(self.descriptors[0])
                if (
                    _path_is_redirected(self.checkout, root_stat)
                    or not stat.S_ISDIR(root_stat.st_mode)
                    or (root_stat.st_dev, root_stat.st_ino)
                    != (opened_root.st_dev, opened_root.st_ino)
                ):
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Snapshot output checkout changed while bound: {self.checkout}.",
                    )
                for parent_descriptor, component, child_descriptor in self.links:
                    entry = os.stat(
                        component,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                    opened = os.fstat(child_descriptor)
                    if (
                        stat.S_ISLNK(entry.st_mode)
                        or not stat.S_ISDIR(entry.st_mode)
                        or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
                    ):
                        raise AnchoredOutputError(
                            "output-parent-changed",
                            f"Snapshot output ancestor changed while bound: {self.parent}.",
                        )
                return
            try:
                root_stat = self.checkout.lstat()
                opened_root = os.fstat(self.descriptors[0])
                if (
                    _path_is_redirected(self.checkout, root_stat)
                    or not stat.S_ISDIR(root_stat.st_mode)
                    or (root_stat.st_dev, root_stat.st_ino) != (opened_root.st_dev, opened_root.st_ino)
                ):
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Snapshot output checkout changed while bound: {self.checkout}.",
                    )
                private_indexes = frozenset(self.private_posix_descriptor_indexes)
                for descriptor_index, (
                    parent_descriptor,
                    component,
                    child_descriptor,
                ) in enumerate(self.links):
                    parent_is_private = descriptor_index in private_indexes
                    _validate_safe_posix_directory_descriptor(
                        parent_descriptor,
                        code="output-parent-changed",
                        context="bound receipt output intermediate ancestor",
                        require_private=parent_is_private,
                        allow_darwin_deny_only_acl=not parent_is_private,
                    )
                    entry = os.stat(
                        component,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                    opened = os.fstat(child_descriptor)
                    if (
                        stat.S_ISLNK(entry.st_mode)
                        or not stat.S_ISDIR(entry.st_mode)
                        or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
                    ):
                        raise AnchoredOutputError(
                            "output-parent-changed",
                            f"Snapshot output ancestor changed while bound: {self.parent}.",
                        )
                _validate_safe_posix_directory_descriptor(
                    self.descriptors[-1],
                    code="output-parent-changed",
                    context="bound final receipt output parent",
                    require_private=len(self.descriptors) - 1 in private_indexes,
                )
            except OSError as error:
                translated = _translated_anchored_output_error(
                    error,
                    "output-parent-changed",
                    f"Snapshot output ancestor could not be verified while bound: {self.parent}.",
                )
                raise translated from error
            return

        assert self.windows_api is not None
        if not self.receipt_parent_policy:
            for path, identity, handle in self.windows_entries:
                path_stat = path.lstat()
                attributes = _windows_directory_attributes(self.windows_api, handle)
                if (
                    _path_is_redirected(path, path_stat)
                    or not stat.S_ISDIR(path_stat.st_mode)
                    or (path_stat.st_dev, path_stat.st_ino) != identity
                    or _windows_handle_identity(self.windows_api, handle) != identity
                    or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                    or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Snapshot output ancestor changed while bound: {path}.",
                    )
            return
        try:
            for path, identity, handle in self.windows_entries:
                path_stat = path.lstat()
                attributes = _windows_directory_attributes(self.windows_api, handle)
                if (
                    _path_is_redirected(path, path_stat)
                    or not stat.S_ISDIR(path_stat.st_mode)
                    or (path_stat.st_dev, path_stat.st_ino) != identity
                    or _windows_handle_identity(self.windows_api, handle) != identity
                    or not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                    or attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Snapshot output ancestor changed while bound: {path}.",
                    )
        except OSError as error:
            translated = _translated_anchored_output_error(
                error,
                "output-parent-changed",
                f"Snapshot output ancestor could not be verified while bound: {self.parent}.",
            )
            raise translated from error

    def stat(self, name: str) -> os.stat_result:
        if self.strategy == "posix-dir-fd":
            return os.stat(
                name,
                dir_fd=self.descriptors[-1],
                follow_symlinks=False,
            )
        self.verify()
        result = (self.parent / name).lstat()
        self.verify()
        return result

    def open_new(self, name: str) -> int:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        if self.strategy == "posix-dir-fd":
            return os.open(name, flags, 0o600, dir_fd=self.descriptors[-1])
        self.verify()
        return os.open(self.parent / name, flags, 0o600)

    def open_read(self, name: str, lease: _PosixDescriptorLease) -> int:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if self.strategy != "posix-dir-fd":
            raise AnchoredOutputError(
                "output-anchor-unavailable",
                "Windows receipt reads require the retained-handle native helper.",
            )
        return _open_posix_descriptor(
            lease,
            name,
            flags,
            dir_fd=self.descriptors[-1],
        )

    def link(self, source: str, destination: str) -> None:
        if self.strategy == "posix-dir-fd":
            os.link(
                source,
                destination,
                src_dir_fd=self.descriptors[-1],
                dst_dir_fd=self.descriptors[-1],
                follow_symlinks=False,
            )
            return
        self.verify()
        os.link(
            self.parent / source,
            self.parent / destination,
            follow_symlinks=False,
        )

    def unlink(self, name: str) -> None:
        if self.strategy == "posix-dir-fd":
            os.unlink(name, dir_fd=self.descriptors[-1])
            return
        self.verify()
        os.unlink(self.parent / name)
        self.verify()

    def sync(self) -> None:
        if self.strategy != "posix-dir-fd":
            # The hard-link operation still publishes one name atomically on
            # Windows, but Python exposes no portable directory-entry flush
            # for the retained Win32 directory handles used here.
            return
        os.fsync(self.descriptors[-1])


@dataclass(slots=True)
class _OutputParentBindingLeaseState:
    """Mutable ownership state kept alive independently of its public lease."""

    binding: OutputParentBinding | None = None
    publication_resources: list[_PublicationResourceLease] = field(
        default_factory=lambda: list[_PublicationResourceLease]()
    )
    fully_closed: bool = False

    def close(self) -> tuple[BaseException, ...]:
        if self.fully_closed:
            return ()
        binding = self.binding
        failures: list[BaseException] = []
        for resource in reversed(self.publication_resources):
            resource_failure_count = len(failures)
            resource_closed = False
            for _attempt in range(2):
                try:
                    failures.extend(resource.close())
                except BaseException as error:
                    failures.append(error)
                try:
                    resource_closed = resource.is_closed
                except BaseException as status_error:
                    failures.append(status_error)
                    resource_closed = False
                if resource_closed:
                    break
            if not resource_closed:
                if len(failures) == resource_failure_count:
                    failures.append(
                        AnchoredOutputError(
                            "output-cleanup-retained",
                            "A receipt publication resource remained open after bounded cleanup attempts.",
                        )
                    )
                # Do not close an older resource or the parent binding while a
                # newer child still owns a descriptor that may depend on it.
                return tuple(failures)
        if binding is None:
            self.fully_closed = True
            return tuple(failures)
        for _attempt in range(2):
            try:
                failures.extend(binding.close())
            except BaseException as error:
                failures.append(error)
                if binding.is_closed:
                    break
                continue
            if binding.is_closed:
                break
        if binding.is_closed:
            self.fully_closed = True
        elif not failures:
            failures.append(
                AnchoredOutputError(
                    "output-cleanup-retained",
                    "A receipt output parent binding remained open after bounded cleanup attempts.",
                )
            )
        return tuple(failures)


def _finalize_output_parent_binding_lease(state: _OutputParentBindingLeaseState) -> None:
    """Best-effort, bounded fallback when explicit outer cleanup is interrupted.

    CPython normally invokes this when the owning frame releases its final
    lease reference. Other Python implementations may defer it until a later
    garbage collection or interpreter shutdown, so explicit cleanup remains
    the primary path.
    """

    try:
        state.close()
    except BaseException:
        # Finalizers cannot report cleanup failures without replacing or
        # obscuring the exception that caused the owning frame to unwind.
        pass


@dataclass(slots=True, weakref_slot=True, init=False)
class _OutputParentBindingLease:
    """Keep a binding reachable across nested Python call-return boundaries."""

    _state: _OutputParentBindingLeaseState
    _finalizer: _LeaseFinalizer

    def __init__(self, binding: OutputParentBinding | None = None) -> None:
        state = _OutputParentBindingLeaseState(binding=binding)
        self._state = state
        # The callback retains only the separate state, never this lease, so
        # registration does not create a cycle that would delay collection.
        self._finalizer = cast(
            _LeaseFinalizer,
            weakref.finalize(
                self,
                _finalize_output_parent_binding_lease,
                state,
            ),
        )

    @property
    def binding(self) -> OutputParentBinding | None:
        return self._state.binding

    @binding.setter
    def binding(self, binding: OutputParentBinding | None) -> None:
        if self._state.fully_closed:
            raise ValueError("Receipt output binding lease is already closed.")
        self._state.binding = binding

    @property
    def publication_resources(self) -> list[_PublicationResourceLease]:
        return self._state.publication_resources

    def retain_publication_resource(self, resource: _PublicationResourceLease) -> None:
        """Transfer a transient resource owner to the outermost public lease."""

        if self._state.fully_closed:
            raise ValueError("Receipt output binding lease is already closed.")
        self._state.publication_resources.append(resource)

    def close(self) -> tuple[BaseException, ...]:
        failures = self._state.close()
        if self._state.fully_closed:
            self._finalizer.detach()
        return failures


def _checkout_output_parts(path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    leaf = path.name
    if leaf in {"", ".", ".."}:
        raise AnchoredOutputError(
            "path-outside-checkout",
            f"Snapshot output must name a file below the physical checkout: {path}.",
        )
    try:
        checkout = Path.cwd().resolve(strict=True)
        # Normalize dot components without following any caller-controlled
        # output ancestor. Absolute spellings may still use an OS-level alias
        # for the physical cwd (for example macOS /var -> /private/var), so map
        # the outermost lexical ancestor that identifies the checkout and keep
        # every component below it for no-follow traversal from the anchor.
        lexical_parent = Path(os.path.abspath(os.path.normpath(os.fspath(path.parent))))
        try:
            relative_parent_parts = lexical_parent.relative_to(checkout).parts
        except ValueError:
            reversed_suffix: list[str] = []
            current = lexical_parent
            matched_parts: tuple[str, ...] | None = None
            while True:
                try:
                    matches_checkout = current.samefile(checkout)
                except OSError:
                    matches_checkout = False
                if matches_checkout:
                    # Continue toward the filesystem root so a symlink below
                    # the checkout that points back to it cannot become the
                    # trusted prefix.
                    matched_parts = tuple(reversed(reversed_suffix))
                parent = current.parent
                if parent == current:
                    break
                reversed_suffix.append(current.name)
                current = parent
            if matched_parts is None:
                raise ValueError("Output parent is not lexically below the checkout.")
            relative_parent_parts = matched_parts
    except (OSError, ValueError) as error:
        raise AnchoredOutputError(
            "path-outside-checkout",
            f"Snapshot output must resolve below the physical checkout: {path}.",
        ) from error
    absolute = checkout.joinpath(*relative_parent_parts, leaf)
    return checkout, absolute, (*relative_parent_parts, leaf)


def open_output_parent(path: Path) -> OutputParentBinding:
    checkout, absolute, parts = _checkout_output_parts(path)
    parent = absolute.parent
    leaf = parts[-1]
    if descriptor_relative_output_supported():
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors: list[int] = []
        links: list[tuple[int, str, int]] = []
        try:
            root_descriptor = os.open(".", flags)
            descriptors.append(root_descriptor)
            root_path_stat = checkout.lstat()
            opened_root = os.fstat(root_descriptor)
            if (
                _path_is_redirected(checkout, root_path_stat)
                or not stat.S_ISDIR(opened_root.st_mode)
                or (root_path_stat.st_dev, root_path_stat.st_ino) != (opened_root.st_dev, opened_root.st_ino)
            ):
                raise OSError("The physical checkout changed while it was opened.")
            for component in parts[:-1]:
                parent_descriptor = descriptors[-1]
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
                    raise OSError(f"Redirected output ancestor: {component}.")
                child_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=parent_descriptor,
                )
                descriptors.append(child_descriptor)
                opened = os.fstat(child_descriptor)
                if not stat.S_ISDIR(opened.st_mode) or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
                    raise OSError(f"Output ancestor changed: {component}.")
                links.append((parent_descriptor, component, child_descriptor))
            binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="posix-dir-fd",
                descriptors=tuple(descriptors),
                links=tuple(links),
            )
            binding.verify()
            return binding
        except BaseException as error:
            cleanup_binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="posix-dir-fd",
                descriptors=tuple(descriptors),
            )
            for cleanup_error in cleanup_binding.close():
                error.add_note(f"Could not close a snapshot output directory descriptor: {cleanup_error}")
            if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
                raise
            raise AnchoredOutputError(
                "output-parent-invalid",
                f"Cannot bind snapshot output parent inside the checkout: {parent}.",
            ) from error

    if os.name == "nt":
        kernel32 = _windows_file_api()
        entries: list[tuple[Path, tuple[int, int], int]] = []
        try:
            current = checkout
            for component in (None, *parts[:-1]):
                if component is not None:
                    current /= component
                path_stat = current.lstat()
                if _path_is_redirected(current, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
                    raise OSError(f"Redirected output ancestor: {current}.")
                identity = (path_stat.st_dev, path_stat.st_ino)
                handle = _open_windows_directory_handle(kernel32, current, identity)
                entries.append((current, identity, handle))
            binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="windows-handle",
                windows_api=kernel32,
                windows_entries=tuple(entries),
            )
            binding.verify()
            return binding
        except BaseException as error:
            cleanup_binding = OutputParentBinding(
                checkout=checkout,
                parent=parent,
                leaf=leaf,
                strategy="windows-handle",
                windows_api=kernel32,
                windows_entries=tuple(entries),
            )
            for cleanup_error in cleanup_binding.close():
                error.add_note(f"Could not close a snapshot output directory handle: {cleanup_error}")
            if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
                raise
            raise AnchoredOutputError(
                "output-parent-invalid",
                f"Cannot bind snapshot output parent inside the checkout: {parent}.",
            ) from error

    raise AnchoredOutputError(
        "output-anchor-unavailable",
        "This platform cannot bind snapshot output operations to the physical checkout.",
    )


def _rooted_output_parts(path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    leaf = path.name
    invalid_leaf: ValueError | None = None
    windows_receipt: Any | None = None
    if os.name == "nt":
        windows_receipt = _windows_receipt_module()
        try:
            windows_receipt._validate_windows_relative_leaf(leaf)
        except ValueError as error:
            invalid_leaf = error
    elif leaf in {"", ".", ".."} or "\x00" in leaf:
        invalid_leaf = ValueError("Receipt output must name one file")
    if invalid_leaf is not None:
        raise AnchoredOutputError(
            "path-invalid",
            f"Receipt output must name one file: {path}.",
        ) from invalid_leaf
    try:
        absolute = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
        anchor_text = absolute.anchor
        if not anchor_text:
            raise ValueError("The output path has no filesystem anchor.")
        anchor = Path(anchor_text)
        relative_parts = absolute.relative_to(anchor).parts
        if sys.platform == "darwin" and relative_parts and relative_parts[0] in {"tmp", "var"}:
            # macOS exposes trusted root-level aliases such as /var and /tmp.
            # Resolve only that root-owned prefix; every component beneath it
            # remains lexical and is traversed without following redirects.
            first_component = anchor / relative_parts[0]
            try:
                first_stat = first_component.lstat()
            except FileNotFoundError:
                pass
            else:
                if _path_is_redirected(first_component, first_stat):
                    physical_prefix = first_component.resolve(strict=True)
                    expected_prefix = Path("/private") / relative_parts[0]
                    if physical_prefix != expected_prefix:
                        raise ValueError("The trusted macOS root alias does not name its physical prefix.")
                    absolute = physical_prefix.joinpath(*relative_parts[1:])
                    anchor_text = absolute.anchor
                    if not anchor_text:
                        raise ValueError("The physical output path has no filesystem anchor.")
                    anchor = Path(anchor_text)
                    relative_parts = absolute.relative_to(anchor).parts
        if windows_receipt is not None:
            # Reject device namespaces and unsupported Windows roots before the
            # retained-parent opener can acquire or create anything below them.
            windows_receipt._nt_anchor_path(anchor)
    except (OSError, RuntimeError, ValueError) as error:
        translated = AnchoredOutputError(
            "path-invalid",
            f"Cannot anchor receipt output at one physical filesystem root: {path}.",
        )
        for note in getattr(error, "__notes__", ()):
            translated.add_note(note)
        raise translated from error
    if not relative_parts or relative_parts[-1] != leaf:
        raise AnchoredOutputError(
            "path-invalid",
            f"Receipt output must name one canonical file path: {path}.",
        )
    if windows_receipt is not None:
        try:
            for component in relative_parts:
                windows_receipt._validate_windows_relative_leaf(component)
        except ValueError as error:
            raise AnchoredOutputError(
                "path-invalid",
                f"Receipt output must use valid Windows path components: {path}.",
            ) from error
    return anchor, absolute, relative_parts


def _open_rooted_posix_parent(
    anchor: Path,
    absolute: Path,
    parts: tuple[str, ...],
    lease: _OutputParentBindingLease,
) -> OutputParentBinding:
    if lease.binding is not None:
        raise ValueError("Receipt output binding lease is already occupied.")
    if os.mkdir not in os.supports_dir_fd:
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "Descriptor-relative receipt parent creation is unavailable on this platform.",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptors: list[int] = []
    descriptor_leases: list[_PosixDescriptorLease] = []
    links: list[tuple[int, str, int]] = []
    private_descriptor_indexes: list[int] = []
    binding = OutputParentBinding(
        checkout=anchor,
        parent=absolute.parent,
        leaf=parts[-1],
        strategy="posix-dir-fd",
        receipt_parent_policy=True,
        descriptors=descriptors,
        descriptor_leases=descriptor_leases,
        links=links,
        private_posix_descriptor_indexes=private_descriptor_indexes,
    )
    # Install the mutable owner before any openat call can populate one of its
    # pre-registered descriptor slots. The outer finalizer can then recover a
    # descriptor even if control flow is interrupted at a call-return boundary.
    lease.binding = binding
    try:
        root_lease = _PosixDescriptorLease()
        descriptor_leases.append(root_lease)
        root_descriptor = _open_posix_descriptor(root_lease, anchor, flags)
        descriptors.append(root_descriptor)
        root_path_stat = anchor.lstat()
        opened_root = os.fstat(root_descriptor)
        if (
            _path_is_redirected(anchor, root_path_stat)
            or not stat.S_ISDIR(opened_root.st_mode)
            or (root_path_stat.st_dev, root_path_stat.st_ino) != (opened_root.st_dev, opened_root.st_ino)
        ):
            raise OSError("The physical filesystem root changed while it was opened.")
        for component in parts[:-1]:
            parent_descriptor = descriptors[-1]
            parent_index = len(descriptors) - 1
            parent_is_private = parent_index in private_descriptor_indexes
            _validate_safe_posix_directory_descriptor(
                parent_descriptor,
                code="output-parent-invalid",
                context="receipt output intermediate ancestor",
                require_private=parent_is_private,
                allow_darwin_deny_only_acl=not parent_is_private,
            )
            created_component = False
            try:
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                _validate_safe_posix_directory_descriptor(
                    parent_descriptor,
                    code="output-parent-invalid",
                    context="receipt ancestor creation parent",
                    require_private=parent_is_private,
                    allow_darwin_deny_only_acl=not parent_is_private,
                )
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_descriptor)
                except FileExistsError as error:
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"Receipt output ancestor appeared after it was observed missing: {component}.",
                    ) from error
                created_component = True
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                # A restrictive umask may remove owner access. The retained
                # parent was just proven safe against other-UID replacement;
                # same-UID/root interference remains explicitly out of scope.
                created_identity = (entry.st_dev, entry.st_ino)
                os.chmod(
                    component,
                    0o700,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                entry = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (entry.st_dev, entry.st_ino) != created_identity:
                    raise AnchoredOutputError(
                        "output-parent-changed",
                        f"New receipt output ancestor changed while its mode was sealed: {component}.",
                    )
            if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
                raise OSError(f"Redirected receipt output ancestor: {component}.")
            child_lease = _PosixDescriptorLease()
            descriptor_leases.append(child_lease)
            child_descriptor = _open_posix_descriptor(
                child_lease,
                component,
                flags,
                dir_fd=parent_descriptor,
            )
            descriptors.append(child_descriptor)
            opened = os.fstat(child_descriptor)
            if not stat.S_ISDIR(opened.st_mode) or (entry.st_dev, entry.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise OSError(f"Receipt output ancestor changed: {component}.")
            if created_component:
                private_descriptor_indexes.append(len(descriptors) - 1)
                os.fchmod(child_descriptor, 0o700)
                _validate_safe_posix_directory_descriptor(
                    child_descriptor,
                    code="output-parent-invalid",
                    context="newly created receipt output ancestor",
                    require_private=True,
                )
            # Repeat the containing-directory barrier for existing components:
            # a prior invocation may have created the entry and failed here.
            os.fsync(parent_descriptor)
            links.append((parent_descriptor, component, child_descriptor))
        _validate_safe_posix_directory_descriptor(
            descriptors[-1],
            code="output-parent-invalid",
            context="final receipt output parent",
            require_private=len(descriptors) - 1 in private_descriptor_indexes,
        )
        binding.verify()
        return binding
    except BaseException as error:
        try:
            cleanup_failures = lease.close()
        except BaseException as cleanup_error:
            cleanup_failures = (cleanup_error,)
        for cleanup_error in cleanup_failures:
            error.add_note(f"Could not close a receipt output directory descriptor: {cleanup_error}")
        if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
            raise
        translated = AnchoredOutputError(
            "output-parent-invalid",
            f"Cannot bind or create receipt output parent: {absolute.parent}.",
        )
        for note in getattr(error, "__notes__", ()):
            translated.add_note(note)
        raise translated from error


def _open_rooted_windows_parent(
    anchor: Path,
    absolute: Path,
    parts: tuple[str, ...],
    lease: _OutputParentBindingLease,
) -> OutputParentBinding:
    if lease.binding is not None:
        raise ValueError("Receipt output binding lease is already occupied.")
    kernel32 = _windows_file_api()
    entries: list[tuple[Path, tuple[int, int], int]] = []
    handle_leases: list[Any] = []
    loaded_windows_receipt: Any | None = None
    try:
        loaded = _windows_receipt_module()
        loaded_windows_receipt = loaded
        kernel32, nt_api = loaded._select_apis(kernel32, None)
        kernel32 = loaded._configure_api(kernel32)
        nt_api = loaded._configure_nt_api(nt_api)

        binding = OutputParentBinding(
            checkout=anchor,
            parent=absolute.parent,
            leaf=parts[-1],
            strategy="windows-handle",
            receipt_parent_policy=True,
            windows_api=kernel32,
            windows_entries=entries,
            windows_handle_leases=handle_leases,
        )
        # NtCreateFile writes into each WindowsHandleLease. Retain the mutable
        # binding first, then register every empty slot in native-open order so
        # interrupted acquisition is still closed child-to-root by the owner.
        lease.binding = binding

        current = anchor
        root_lease = loaded.WindowsHandleLease()
        handle_leases.append(root_lease)
        root = loaded.open_windows_directory_anchor(
            current,
            root_lease,
            api=kernel32,
            nt_api=nt_api,
        )
        if root_lease.handle != root.handle:
            raise OSError("Windows directory anchor helper returned an unowned handle.")
        root_identity = (
            root.volume_serial_number,
            int.from_bytes(root.file_id, "little"),
        )
        entries.append((current, root_identity, root.handle))

        for component in parts[:-1]:
            current /= component
            child_lease = loaded.WindowsHandleLease()
            handle_leases.append(child_lease)
            directory = loaded.open_or_create_windows_directory(
                entries[-1][2],
                component,
                child_lease,
                api=kernel32,
                nt_api=nt_api,
            )
            if child_lease.handle != directory.handle:
                raise OSError("Relative directory helper returned an unowned handle.")
            identity = (
                directory.volume_serial_number,
                int.from_bytes(directory.file_id, "little"),
            )
            entries.append((current, identity, directory.handle))
        binding.verify()
        return binding
    except BaseException as error:
        try:
            cleanup_failures = lease.close()
        except BaseException as cleanup_error:
            cleanup_failures = (cleanup_error,)
        for cleanup_error in cleanup_failures:
            error.add_note(f"Could not close a receipt output directory handle: {cleanup_error}")
        if isinstance(error, AnchoredOutputError) or not isinstance(error, Exception):
            raise
        if loaded_windows_receipt is not None and isinstance(
            error,
            loaded_windows_receipt.WindowsReceiptValidationError,
        ):
            translated = _translated_anchored_output_error(
                error,
                cast(str, getattr(error, "code")),
                str(error),
            )
            raise translated from error
        translated = AnchoredOutputError(
            "output-parent-invalid",
            f"Cannot bind or create receipt output parent: {absolute.parent}.",
        )
        for note in getattr(error, "__notes__", ()):
            translated.add_note(note)
        raise translated from error


def open_rooted_output_parent(
    path: Path,
    lease: _OutputParentBindingLease,
) -> OutputParentBinding:
    anchor, absolute, parts = _rooted_output_parts(path)
    if descriptor_relative_output_supported():
        return _open_rooted_posix_parent(anchor, absolute, parts, lease)
    if os.name == "nt":
        return _open_rooted_windows_parent(anchor, absolute, parts, lease)
    raise AnchoredOutputError(
        "output-anchor-unavailable",
        "This platform cannot bind receipt output operations to the filesystem root.",
    )


def _same_identity(path_stat: os.stat_result, identity: tuple[int, int]) -> bool:
    return (path_stat.st_dev, path_stat.st_ino) == identity


def _unlink_output_if_identity(
    binding: OutputParentBinding,
    name: str,
    identity: tuple[int, int],
) -> None:
    try:
        current = binding.stat(name)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(current.st_mode) or not _same_identity(current, identity):
        raise AnchoredOutputError(
            "output-cleanup-changed",
            f"Refusing to remove a changed snapshot output artifact: {binding.parent / name}.",
        )
    binding.unlink(name)


def _stable_file_metadata(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _receipt_mode_is_canonical(value: os.stat_result) -> bool:
    return stat.S_IMODE(value.st_mode) == 0o600 and value.st_uid == os.geteuid()


def _receipt_namespace_changed(error: OSError) -> bool:
    return isinstance(error, FileNotFoundError) or error.errno in _POSIX_RECEIPT_NAMESPACE_CHANGED_ERRNOS


def _validate_receipt_file(
    binding: OutputParentBinding,
    name: str,
    value: os.stat_result,
    *,
    code: str,
) -> None:
    if (
        _path_is_redirected(binding.parent / name, value)
        or not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or not _receipt_mode_is_canonical(value)
    ):
        raise AnchoredOutputError(
            code,
            f"Receipt output is not one canonical private regular file: {binding.parent / name}.",
        )


def _read_exact_receipt(
    binding: OutputParentBinding,
    name: str,
    payload: bytes,
    *,
    descriptor_lease: _PosixDescriptorLease,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    try:
        before = binding.stat(name)
    except OSError as error:
        if not _receipt_namespace_changed(error):
            raise
        translated = _translated_anchored_output_error(
            error,
            "output-changed",
            f"Receipt output changed while it was being located: {binding.parent / name}.",
        )
        raise translated from error
    validation_code = "output-changed" if expected_identity is not None else "output-existing-invalid"
    _validate_receipt_file(binding, name, before, code=validation_code)
    identity = (before.st_dev, before.st_ino)
    if expected_identity is not None and identity != expected_identity:
        raise AnchoredOutputError(
            "output-changed",
            f"Receipt output changed while it was being verified: {binding.parent / name}.",
        )

    descriptor: int | None = None
    primary_error: BaseException | None = None
    try:
        descriptor = binding.open_read(name, descriptor_lease)
        opened = os.fstat(descriptor)
        if _darwin_descriptor_has_extended_acl(
            descriptor,
            error_code=validation_code,
            context="receipt output descriptor",
        ):
            raise AnchoredOutputError(
                validation_code,
                f"Receipt output has an extended ACL while it is being opened: {binding.parent / name}.",
            )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not _receipt_mode_is_canonical(opened)
            or (opened.st_dev, opened.st_ino) != identity
            or opened.st_size != before.st_size
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Receipt output changed while it was being opened: {binding.parent / name}.",
            )
        chunks: list[bytes] = []
        remaining = len(payload) + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        observed = b"".join(chunks)
        opened_after = os.fstat(descriptor)
        if _darwin_descriptor_has_extended_acl(
            descriptor,
            error_code="output-changed",
            context="receipt output descriptor after reading",
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Receipt output gained an extended ACL while it was being read: {binding.parent / name}.",
            )
        after = binding.stat(name)
        binding.verify()
        _validate_receipt_file(binding, name, after, code="output-changed")
        if (
            _stable_file_metadata(opened) != _stable_file_metadata(opened_after)
            or _stable_file_metadata(before) != _stable_file_metadata(after)
            or (opened_after.st_dev, opened_after.st_ino) != (after.st_dev, after.st_ino)
            or opened_after.st_size != after.st_size
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Receipt output changed while it was being read: {binding.parent / name}.",
            )
        if observed != payload:
            raise AnchoredOutputError(
                "output-changed" if expected_identity is not None else "output-different",
                (
                    f"Receipt output changed while it was being verified: {binding.parent / name}."
                    if expected_identity is not None
                    else f"Refusing to replace different existing receipt output: {binding.parent / name}."
                ),
            )
        return identity
    except OSError as error:
        if not _receipt_namespace_changed(error):
            primary_error = error
            raise
        translated = _translated_anchored_output_error(
            error,
            "output-changed",
            f"Receipt output changed while it was being verified: {binding.parent / name}.",
        )
        primary_error = translated
        raise translated from error
    except BaseException as error:
        primary_error = error
        raise
    finally:
        close_call_failures: list[BaseException] = []
        close_error: BaseException | None = None
        for _attempt in range(2):
            try:
                close_error = _close_posix_descriptor_lease(
                    descriptor_lease,
                    primary_error,
                    "receipt verification descriptor",
                )
            except BaseException as cleanup_error:
                close_call_failures.append(cleanup_error)
                if descriptor_lease.descriptor is not None:
                    continue
            break
        if primary_error is not None:
            for cleanup_error in close_call_failures:
                primary_error.add_note(f"Could not close receipt verification descriptor: {cleanup_error}")
        elif close_call_failures:
            first_cleanup_error = close_call_failures[0]
            for later_error in close_call_failures[1:]:
                first_cleanup_error.add_note(f"Receipt verification close failure: {later_error}")
            if close_error is not None:
                first_cleanup_error.add_note(f"Receipt verification close failure: {close_error}")
            raise first_cleanup_error
        elif close_error is not None:
            raise close_error


def publish_new_bytes(path: Path, payload: bytes) -> None:
    """Publish bytes below the physical cwd without replacing an existing name."""

    binding = open_output_parent(path)
    temporary_name = ""
    temporary_identity: tuple[int, int] | None = None
    output_identity: tuple[int, int] | None = None
    published = False
    descriptor = -1
    primary_error: BaseException | None = None
    try:
        try:
            binding.stat(binding.leaf)
        except FileNotFoundError:
            pass
        else:
            raise AnchoredOutputError("output-exists", f"Refusing to overwrite existing snapshot output: {path}.")

        for _attempt in range(100):
            temporary_name = f".{binding.leaf}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = binding.open_new(temporary_name)
            except FileExistsError:
                continue
            binding.verify()
            break
        if descriptor < 0:
            raise AnchoredOutputError(
                "output-temporary-unavailable",
                f"Could not create a private temporary snapshot beside {path}.",
            )
        opened = os.fstat(descriptor)
        temporary_identity = (opened.st_dev, opened.st_ino)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise AnchoredOutputError(
                "output-temporary-invalid",
                f"Snapshot temporary file is not one private regular file: {path}.",
            )
        file_handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with file_handle as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        binding.verify()
        try:
            binding.link(temporary_name, binding.leaf)
        except FileExistsError as error:
            raise AnchoredOutputError(
                "output-exists", f"Refusing to overwrite existing snapshot output: {path}."
            ) from error
        published = True
        output_identity = temporary_identity
        output_stat = binding.stat(binding.leaf)
        if not stat.S_ISREG(output_stat.st_mode) or not _same_identity(output_stat, temporary_identity):
            raise AnchoredOutputError(
                "output-changed",
                f"Snapshot output changed while it was published: {path}.",
            )
        binding.verify()
        binding.sync()
        _unlink_output_if_identity(binding, temporary_name, temporary_identity)
        temporary_identity = None
        binding.sync()
        binding.verify()
        output_stat = binding.stat(binding.leaf)
        if (
            not stat.S_ISREG(output_stat.st_mode)
            or output_stat.st_nlink != 1
            or not _same_identity(output_stat, output_identity)
        ):
            raise AnchoredOutputError(
                "output-changed",
                f"Snapshot output changed before publication completed: {path}.",
            )
    except BaseException as error:
        primary_error = error
        if descriptor >= 0:
            if temporary_identity is None:
                try:
                    opened_for_cleanup = os.fstat(descriptor)
                    if stat.S_ISREG(opened_for_cleanup.st_mode):
                        temporary_identity = (
                            opened_for_cleanup.st_dev,
                            opened_for_cleanup.st_ino,
                        )
                    else:
                        error.add_note(
                            "Could not bind the snapshot temporary file for cleanup: "
                            "the opened descriptor is not a regular file."
                        )
                except BaseException as cleanup_error:
                    # Do not unlink by name without proving that the entry is
                    # still the file represented by this descriptor. A writer
                    # with directory access could have replaced it. At this
                    # point publication has not begun, so the fail-closed cost
                    # is at most one unpredictable, newly created empty temp.
                    error.add_note(
                        f"Could not identify the snapshot temporary file for cleanup: "
                        f"{cleanup_error}. The unverified temporary name was "
                        "intentionally left in place rather than risk deleting "
                        "a replaced entry."
                    )
            try:
                os.close(descriptor)
            except BaseException as cleanup_error:
                error.add_note(f"Could not close the snapshot temporary descriptor: {cleanup_error}")
            descriptor = -1
        if published and output_identity is not None:
            try:
                _unlink_output_if_identity(binding, binding.leaf, output_identity)
            except BaseException as cleanup_error:
                error.add_note(f"Could not remove rejected snapshot output: {cleanup_error}")
        if temporary_identity is not None:
            try:
                _unlink_output_if_identity(binding, temporary_name, temporary_identity)
            except BaseException as cleanup_error:
                error.add_note(f"Could not remove snapshot temporary file: {cleanup_error}")
        raise
    finally:
        close_failures = binding.close()
        if close_failures:
            if primary_error is not None:
                for close_error in close_failures:
                    primary_error.add_note(f"Could not close a snapshot output anchor: {close_error}")
            else:
                control_flow_failure = next(
                    (failure for failure in close_failures if not isinstance(failure, Exception)),
                    None,
                )
                if control_flow_failure is not None:
                    for failure in close_failures:
                        if failure is not control_flow_failure:
                            control_flow_failure.add_note(f"Output anchor close failure: {failure}")
                    raise control_flow_failure
                close_error = AnchoredOutputError(
                    "output-anchor-close-failed",
                    "Snapshot publication completed, but one or more output directory anchors could not be closed.",
                )
                for failure in close_failures:
                    close_error.add_note(f"Output anchor close failure: {failure}")
                raise close_error from close_failures[0]


def _load_exact_sibling(module_name: str, filename: str, injected: dict[str, object] | None = None) -> Any:
    """Load one private sibling by its resolved path, never by import search."""

    import importlib.util

    module_path = Path(__file__).resolve(strict=True).with_name(filename)
    existing = sys.modules.get(module_name)
    if existing is not None:
        existing_path = getattr(existing, "__file__", None)
        if isinstance(existing_path, str) and Path(existing_path).resolve(strict=True) == module_path:
            return existing
        raise ImportError(f"Refusing conflicting anchored receipt module {module_name!r}.")
    specification = importlib.util.spec_from_file_location(module_name, module_path)
    if specification is None or specification.loader is None:
        raise ImportError(f"Cannot load anchored receipt helper: {module_path}")
    module = importlib.util.module_from_spec(specification)
    if injected is not None:
        module.__dict__.update(injected)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_posix_receipt_cache: Any | None = None
_windows_receipt_cache: Any | None = None


def _posix_receipt_module() -> Any:
    global _posix_receipt_cache
    if _posix_receipt_cache is None:
        _posix_receipt_cache = _load_exact_sibling(
            f"{__name__}__anchored_receipt_posix",
            "_anchored_receipt_posix.py",
            {
                "AnchoredOutputError": AnchoredOutputError,
                "OutputParentBinding": OutputParentBinding,
                "_PosixDescriptorLease": _PosixDescriptorLease,
                "_close_posix_descriptor_lease": _close_posix_descriptor_lease,
                "_darwin_descriptor_has_extended_acl": _darwin_descriptor_has_extended_acl,
                "_open_posix_descriptor": _open_posix_descriptor,
                "_read_exact_receipt": _read_exact_receipt,
                "_receipt_mode_is_canonical": _receipt_mode_is_canonical,
                "_same_identity": _same_identity,
                "_stable_file_metadata": _stable_file_metadata,
                "_validate_safe_posix_directory_descriptor": _validate_safe_posix_directory_descriptor,
            },
        )
    return _posix_receipt_cache


def _windows_receipt_module() -> Any:
    global _windows_receipt_cache
    if _windows_receipt_cache is None:
        _windows_receipt_cache = _load_exact_sibling(
            f"{__name__}__anchored_receipt_windows",
            "_anchored_receipt_windows.py",
        )
    return _windows_receipt_cache


def _publish_posix_receipt_bytes(
    path: Path,
    payload: bytes,
    binding: OutputParentBinding,
    outer_lease: _OutputParentBindingLease,
) -> None:
    if outer_lease.binding is not binding:
        raise ValueError("POSIX receipt output binding is not retained by its outer owner.")
    try:
        loaded_posix_receipt = _posix_receipt_module()
    except BaseException as error:
        try:
            close_failures = binding.close()
        except BaseException as close_error:
            close_failures = (close_error,)
        for close_error in close_failures:
            error.add_note(f"Could not close a receipt publication resource: {close_error}")
        raise
    publication_lease = loaded_posix_receipt._PosixReceiptPublicationLease(binding)
    outer_lease.retain_publication_resource(publication_lease)
    loaded_posix_receipt._publish_posix_receipt_bytes(
        path,
        payload,
        binding,
        publication_lease,
    )


def _publish_windows_receipt_bytes(
    path: Path,
    payload: bytes,
    binding: OutputParentBinding,
    outer_lease: _OutputParentBindingLease,
) -> None:
    """Publish with the retained-handle helper without rolling back uncertain outcomes."""

    if outer_lease.binding is not binding:
        raise ValueError("Windows receipt output binding is not retained by its outer owner.")
    primary_error: BaseException | None = None
    windows_receipt: Any | None = None
    publication_lease: Any | None = None
    try:
        loaded_windows_receipt = _windows_receipt_module()
        windows_receipt = loaded_windows_receipt
        windows_api, nt_api = loaded_windows_receipt._select_apis(binding.windows_api, None)
        windows_api = loaded_windows_receipt._configure_api(windows_api)
        nt_api = loaded_windows_receipt._configure_nt_api(nt_api)
        publication_lease = loaded_windows_receipt._WindowsReceiptPublicationLease(windows_api)
        outer_lease.retain_publication_resource(cast(_PublicationResourceLease, publication_lease))
        parent_handle = binding.windows_entries[-1][2]

        def observe_exact(expected: Any | None = None, *, missing_ok: bool = False) -> Any | None:
            binding.verify()
            try:
                observed = loaded_windows_receipt.read_windows_receipt(
                    parent_handle,
                    binding.leaf,
                    payload,
                    api=windows_api,
                    nt_api=nt_api,
                    publication_lease=publication_lease,
                )
            except FileNotFoundError as error:
                if missing_ok:
                    binding.verify()
                    return None
                translated = AnchoredOutputError(
                    "output-changed",
                    f"Receipt output disappeared while it was being verified: {path}.",
                )
                for note in getattr(error, "__notes__", ()):
                    translated.add_note(note)
                raise translated from error
            except loaded_windows_receipt.WindowsReceiptValidationError as error:
                code = error.code
                if expected is not None and code in {"output-existing-invalid", "output-different"}:
                    code = "output-changed"
                translated = _translated_anchored_output_error(error, code, str(error))
                raise translated from error
            except ValueError as error:
                translated = AnchoredOutputError(
                    "path-invalid",
                    f"Receipt output must name one valid Windows file: {path}.",
                )
                for note in getattr(error, "__notes__", ()):
                    translated.add_note(note)
                raise translated from error
            if expected is not None and (
                observed.leaf != expected.leaf
                or observed.volume_serial_number != expected.volume_serial_number
                or observed.file_id != expected.file_id
                or observed.size != expected.size
            ):
                raise AnchoredOutputError(
                    "output-changed",
                    f"Receipt output changed before publication completed: {path}.",
                )
            binding.verify()
            return observed

        binding.verify()
        existing = observe_exact(missing_ok=True)
        if existing is not None:
            binding.verify()
            return
        try:
            published_result: Any | None = None
            for _attempt in range(100):
                try:
                    published_result = loaded_windows_receipt.publish_windows_receipt(
                        parent_handle,
                        binding.leaf,
                        payload,
                        api=windows_api,
                        nt_api=nt_api,
                        publication_lease=publication_lease,
                    )
                except loaded_windows_receipt._StageNameCollision as stage_error:
                    if not loaded_windows_receipt.is_internal_stage_name_collision(stage_error):
                        raise
                    continue
                except loaded_windows_receipt._DefiniteRenameCollision as collision_error:
                    if not loaded_windows_receipt.is_internal_definite_rename_collision(collision_error):
                        raise
                    try:
                        observe_exact()
                    except BaseException as observation_error:
                        for note in getattr(collision_error, "__notes__", ()):
                            observation_error.add_note(note)
                        raise
                    cleanup_failures = loaded_windows_receipt.cleanup_failures_from_error(collision_error)
                    if cleanup_failures:
                        control_flow_failure = next(
                            (failure for failure in cleanup_failures if not isinstance(failure, Exception)),
                            None,
                        )
                        if control_flow_failure is not None:
                            for note in getattr(collision_error, "__notes__", ()):
                                control_flow_failure.add_note(note)
                            raise control_flow_failure from collision_error
                        cleanup_error = AnchoredOutputError(
                            "output-cleanup-retained",
                            "An identical Windows receipt already exists, but its private staging resource "
                            f"could not be cleaned up or closed: {path}.",
                        )
                        for note in getattr(collision_error, "__notes__", ()):
                            cleanup_error.add_note(note)
                        raise cleanup_error from collision_error
                    return
                break
            else:
                raise AnchoredOutputError(
                    "output-temporary-unavailable",
                    f"Could not create a private temporary receipt beside {path}.",
                )
        except BaseException as error:
            outcome = None if windows_receipt is None else windows_receipt.outcome_from_error(error)
            if outcome is None and publication_lease is not None:
                outcome = publication_lease.outcome
            if outcome is not None and outcome.state in {"unknown", "published"}:
                try:
                    binding.verify()
                    observe_exact(outcome.receipt)
                    binding.verify()
                except BaseException as observation_error:
                    error.add_note(
                        "Retained-handle receipt publication may have taken effect; the public name was "
                        f"intentionally left untouched because it could not be verified: {observation_error}"
                    )
                else:
                    error.add_note(
                        "Retained-handle receipt publication took effect before the failure; "
                        "the valid public receipt was left untouched."
                    )
            if outcome is None and loaded_windows_receipt.is_windows_publication_unavailable(error):
                diagnostic_parts = [
                    f"type={type(error).__name__}",
                    f"errno={getattr(error, 'errno', None)}",
                    f"message={error}",
                ]
                nt_operation = getattr(error, "_windows_receipt_nt_operation", None)
                nt_status = getattr(error, "_windows_receipt_nt_status", None)
                if nt_operation is not None:
                    diagnostic_parts.append(f"nt_operation={nt_operation}")
                if nt_status is not None:
                    diagnostic_parts.append(f"nt_status=0x{int(nt_status):08X}")
                native_cause = error.__cause__
                if isinstance(native_cause, OSError):
                    diagnostic_parts.extend(
                        (
                            f"cause_type={type(native_cause).__name__}",
                            f"cause_errno={native_cause.errno}",
                            f"cause_message={native_cause}",
                        )
                    )
                error.add_note(
                    "Windows retained-handle publication diagnostic: "
                    + "; ".join(diagnostic_parts)
                )
                translated = _translated_anchored_output_error(
                    error,
                    "output-anchor-unavailable",
                    f"Windows cannot publish a retained-handle receipt on this filesystem: {path}.",
                )
                raise translated from error
            raise
        binding.verify()
        assert published_result is not None
        observe_exact(published_result)
        binding.verify()
    except BaseException as error:
        primary_error = error
        raise
    finally:
        close_failures: tuple[BaseException, ...] = ()
        publication_closed = publication_lease is None
        if publication_lease is not None:
            resource_failures: list[BaseException] = []
            for _attempt in range(2):
                try:
                    resource_failures.extend(publication_lease.close())
                except BaseException as close_error:
                    resource_failures.append(close_error)
                try:
                    publication_closed = publication_lease.is_closed
                except BaseException as status_error:
                    resource_failures.append(status_error)
                    publication_closed = False
                if publication_closed:
                    break
            close_failures = tuple(resource_failures)
        if publication_closed:
            try:
                binding_close_failures = binding.close()
            except BaseException as close_error:
                binding_close_failures = (close_error,)
            close_failures = (*close_failures, *binding_close_failures)
        elif not close_failures:
            close_failures = (
                AnchoredOutputError(
                    "output-cleanup-retained",
                    "A Windows receipt handle remained open after bounded cleanup attempts.",
                ),
            )
        if close_failures:
            if primary_error is not None:
                for close_error in close_failures:
                    primary_error.add_note(f"Could not close a receipt publication resource: {close_error}")
            else:
                control_flow_failure = next(
                    (failure for failure in close_failures if not isinstance(failure, Exception)),
                    None,
                )
                if control_flow_failure is not None:
                    for failure in close_failures:
                        if failure is not control_flow_failure:
                            control_flow_failure.add_note(f"Receipt publication close failure: {failure}")
                    raise control_flow_failure
                first_close_error = close_failures[0]
                for later_error in close_failures[1:]:
                    first_close_error.add_note(f"Receipt publication close failure: {later_error}")
                raise first_close_error


def publish_identical_receipt_bytes(path: Path, payload: bytes) -> None:
    """Publish or verify one canonical receipt without replacing an existing name."""

    lease = _OutputParentBindingLease()
    primary_error: BaseException | None = None
    try:
        binding = open_rooted_output_parent(path, lease)
        if lease.binding is not binding:
            raise AnchoredOutputError(
                "output-anchor-unavailable",
                "Receipt output binding ownership was not retained across acquisition.",
            )
        if binding.strategy == "posix-dir-fd":
            _publish_posix_receipt_bytes(path, payload, binding, lease)
            return
        if binding.strategy == "windows-handle":
            _publish_windows_receipt_bytes(path, payload, binding, lease)
            return
        raise AnchoredOutputError(
            "output-anchor-unavailable",
            "This platform cannot publish a descriptor-bound canonical receipt.",
        )
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            close_failures = lease.close()
        except BaseException as close_error:
            close_failures = (close_error,)
        if close_failures:
            if primary_error is not None:
                for close_error in close_failures:
                    primary_error.add_note(f"Could not close a receipt publication resource: {close_error}")
            else:
                control_flow_failure = next(
                    (failure for failure in close_failures if not isinstance(failure, Exception)),
                    None,
                )
                if control_flow_failure is not None:
                    for failure in close_failures:
                        if failure is not control_flow_failure:
                            control_flow_failure.add_note(f"Receipt publication close failure: {failure}")
                    raise control_flow_failure
                first_close_error = close_failures[0]
                for later_error in close_failures[1:]:
                    first_close_error.add_note(f"Receipt publication close failure: {later_error}")
                raise first_close_error


__all__ = [
    "AnchoredOutputError",
    "OutputParentBinding",
    "descriptor_relative_output_supported",
    "open_output_parent",
    "open_rooted_output_parent",
    "publish_identical_receipt_bytes",
    "publish_new_bytes",
]
