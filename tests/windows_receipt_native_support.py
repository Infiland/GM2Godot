"""Finite observations of real receipt Win32 calls; never model the filesystem."""

from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch


class UnicodeString(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("maximum", ctypes.c_uint16), ("buffer", ctypes.c_void_p)]


class ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32), ("root", ctypes.c_void_p), ("name", ctypes.POINTER(UnicodeString)),
        ("attributes", ctypes.c_uint32), ("security", ctypes.c_void_p), ("quality", ctypes.c_void_p),
    ]


class IoStatus(ctypes.Structure):
    _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]


class RenameInformation(ctypes.Structure):
    _fields_ = [
        ("replace", ctypes.c_ubyte), ("root", ctypes.c_void_p),
        ("length", ctypes.c_uint32), ("name", ctypes.c_uint16 * 1),
    ]


class BasicInformation(ctypes.Structure):
    _fields_ = [("times", ctypes.c_int64 * 4), ("attributes", ctypes.c_uint32)]


class StandardInformation(ctypes.Structure):
    _fields_ = [
        ("allocation", ctypes.c_int64), ("size", ctypes.c_int64), ("links", ctypes.c_uint32),
        ("delete_pending", ctypes.c_ubyte), ("directory", ctypes.c_ubyte),
    ]


class FileIdentity(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("identifier", ctypes.c_ubyte * 16)]


WINDOWS_AMD64_ABI = {
    "scalar widths": (2, 4, 4, 1, 8, 8),
    "UNICODE_STRING": (16, 0, 2, 8),
    "OBJECT_ATTRIBUTES": (48, 0, 8, 16, 24, 32, 40),
    "IO_STATUS_BLOCK": (16, 0, 8),
    "FILE_RENAME_INFORMATION": (24, 0, 8, 16, 20),
    "FILE_BASIC_INFO": (40, 32),
    "FILE_STANDARD_INFO": (24, 0, 8, 16, 20, 21),
    "FILE_ID_INFO": (24, 0, 8),
}


def native_abi_layout() -> dict[str, tuple[int, ...]]:
    """Observe the fixed-width layouts on the executing host, including offsets."""
    return {
        "scalar widths": tuple(ctypes.sizeof(value) for value in (
            ctypes.c_uint16, ctypes.c_int32, ctypes.c_uint32, ctypes.c_ubyte, ctypes.c_void_p, ctypes.c_size_t,
        )),
        "UNICODE_STRING": (ctypes.sizeof(UnicodeString), UnicodeString.length.offset,
                           UnicodeString.maximum.offset, UnicodeString.buffer.offset),
        "OBJECT_ATTRIBUTES": (ctypes.sizeof(ObjectAttributes), ObjectAttributes.length.offset,
                              ObjectAttributes.root.offset, ObjectAttributes.name.offset, ObjectAttributes.attributes.offset,
                              ObjectAttributes.security.offset, ObjectAttributes.quality.offset),
        "IO_STATUS_BLOCK": (ctypes.sizeof(IoStatus), IoStatus.status.offset, IoStatus.information.offset),
        "FILE_RENAME_INFORMATION": (ctypes.sizeof(RenameInformation), RenameInformation.replace.offset,
                                    RenameInformation.root.offset, RenameInformation.length.offset, RenameInformation.name.offset),
        "FILE_BASIC_INFO": (ctypes.sizeof(BasicInformation), BasicInformation.attributes.offset),
        "FILE_STANDARD_INFO": (ctypes.sizeof(StandardInformation), StandardInformation.allocation.offset,
                               StandardInformation.size.offset, StandardInformation.links.offset,
                               StandardInformation.delete_pending.offset, StandardInformation.directory.offset),
        "FILE_ID_INFO": (ctypes.sizeof(FileIdentity), FileIdentity.volume.offset, FileIdentity.identifier.offset),
    }


class NativeFunction(Protocol):
    argtypes: tuple[object, ...] | None
    restype: object

    def __call__(self, *arguments: object) -> int | None: ...


class NativeLibrary(Protocol):
    CreateFileW: NativeFunction
    NtCreateFile: NativeFunction
    NtSetInformationFile: NativeFunction
    WriteFile: NativeFunction
    ReadFile: NativeFunction
    FlushFileBuffers: NativeFunction
    GetFileInformationByHandleEx: NativeFunction
    GetFileType: NativeFunction
    CloseHandle: NativeFunction
    GetHandleInformation: NativeFunction
    GetCurrentProcess: NativeFunction
    GetProcessHandleCount: NativeFunction
    GetVolumePathNameW: NativeFunction
    GetVolumeInformationW: NativeFunction


class WindowsCtypes(Protocol):
    def WinDLL(self, name: str, *arguments: object, **keywords: object) -> NativeLibrary: ...

    def get_last_error(self) -> int: ...

    def set_last_error(self, error: int) -> None: ...

    def WinError(self, error: int) -> OSError: ...


def windows_ctypes() -> WindowsCtypes:
    """The documented Windows-only ctypes API, unavailable on other hosts."""
    if os.name != "nt":
        raise OSError("Native Windows ctypes functions are required")
    return cast(WindowsCtypes, ctypes)


@dataclass(frozen=True)
class NativeCall:
    name: str
    arguments: tuple[object, ...]
    result: int | None
    last_error: int
    argtypes: tuple[object, ...] | None
    restype: object


BeforeCall = Callable[[str, tuple[object, ...]], None]
AfterCall = Callable[[NativeCall], None]


class ObservedFunction:
    def __init__(self, native: NativeFunction, name: str, capture: NativeCapture) -> None:
        self.native = native
        self.name = name
        self.capture = capture
        self.argtypes = native.argtypes
        self.restype = native.restype

    argtypes: tuple[object, ...] | None
    restype: object

    def __setattr__(self, name: str, value: object) -> None:
        # These two public ctypes fields must configure the real native callable.
        if name == "argtypes":
            if value is not None and not isinstance(value, tuple):
                raise TypeError("Observed receipt argtypes must be a tuple or None")
            self.native.argtypes = cast(tuple[object, ...] | None, value)
        elif name == "restype":
            self.native.restype = value
        object.__setattr__(self, name, value)

    def __call__(self, *arguments: object) -> int | None:
        incoming = windows_ctypes().get_last_error()
        try:
            if self.capture.before is not None:
                self.capture.before(self.name, arguments)
        finally:
            windows_ctypes().set_last_error(incoming)
        result = self.native(*arguments)
        error = windows_ctypes().get_last_error()
        try:
            call = NativeCall(self.name, arguments, result, error, self.argtypes, self.restype)
            self.capture.record(call)
            if self.capture.after is not None:
                self.capture.after(call)
        finally:
            windows_ctypes().set_last_error(error)
        return result


def pointer(value: object) -> ctypes.c_void_p:
    """A native-call argument already governed by the observed ctypes ABI."""
    return cast(ctypes.c_void_p, value)


def nt_name(arguments: tuple[object, ...]) -> str:
    attributes = ctypes.cast(pointer(arguments[2]), ctypes.POINTER(ObjectAttributes)).contents
    name = attributes.name.contents
    return ctypes.string_at(name.buffer, name.length).decode("utf-16-le")


class NativeCapture:
    def __init__(self, before: BeforeCall | None = None, after: AfterCall | None = None) -> None:
        self.factory = windows_ctypes().WinDLL
        self.before = before
        self.after = after
        self.handles: set[int] = set()
        self.calls: list[NativeCall] = []
        self.patch = patch.object(ctypes, "WinDLL", side_effect=self.load)

    def __enter__(self) -> NativeCapture:
        self.patch.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.patch.stop()

    def load(self, name: str, *arguments: object, **keywords: object) -> NativeLibrary:
        factory = cast(Callable[..., NativeLibrary], self.factory)
        library = factory(name, *arguments, **keywords)
        if name.casefold() == "kernel32":
            library.CreateFileW = ObservedFunction(library.CreateFileW, "CreateFileW", self)
            library.ReadFile = ObservedFunction(library.ReadFile, "ReadFile", self)
            library.WriteFile = ObservedFunction(library.WriteFile, "WriteFile", self)
            library.FlushFileBuffers = ObservedFunction(library.FlushFileBuffers, "FlushFileBuffers", self)
            library.GetFileInformationByHandleEx = ObservedFunction(
                library.GetFileInformationByHandleEx, "GetFileInformationByHandleEx", self,
            )
            library.GetFileType = ObservedFunction(library.GetFileType, "GetFileType", self)
        elif name.casefold() == "ntdll":
            library.NtCreateFile = ObservedFunction(library.NtCreateFile, "NtCreateFile", self)
            library.NtSetInformationFile = ObservedFunction(library.NtSetInformationFile, "NtSetInformationFile", self)
        return library

    def record(self, call: NativeCall) -> None:
        self.calls.append(call)
        handle = None
        if call.name == "CreateFileW" and call.result not in {None, ctypes.c_void_p(-1).value}:
            handle = call.result
        elif call.name == "NtCreateFile" and call.result == 0:
            handle = ctypes.cast(pointer(call.arguments[0]), ctypes.POINTER(ctypes.c_void_p)).contents.value
        if handle is not None:
            self.handles.add(handle)


@dataclass(frozen=True)
class NativeMetadata:
    volume: int
    file_id: bytes
    attributes: int
    links: int
    size: int
    directory: int
    file_type: int


class NativeWindows:
    """Independent metadata/closure probes from an unwrapped native DLL."""

    def __init__(self) -> None:
        self.api = windows_ctypes().WinDLL("kernel32", use_last_error=True)
        self.api.CreateFileW.argtypes = (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        )
        self.api.CreateFileW.restype = ctypes.c_void_p
        self.api.CloseHandle.argtypes = (ctypes.c_void_p,)
        self.api.CloseHandle.restype = ctypes.c_int
        self.api.GetFileType.argtypes = (ctypes.c_void_p,)
        self.api.GetFileType.restype = ctypes.c_uint32
        self.api.GetFileInformationByHandleEx.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
        self.api.GetFileInformationByHandleEx.restype = ctypes.c_int
        self.api.GetHandleInformation.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        self.api.GetHandleInformation.restype = ctypes.c_int
        self.api.GetCurrentProcess.argtypes = ()
        self.api.GetCurrentProcess.restype = ctypes.c_void_p
        self.api.GetProcessHandleCount.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        self.api.GetProcessHandleCount.restype = ctypes.c_int

    def handle_is_closed(self, handle: int) -> bool:
        flags = ctypes.c_uint32()
        result = self.api.GetHandleInformation(handle, ctypes.byref(flags))
        error = windows_ctypes().get_last_error()
        return result == 0 and error == 6

    def handle_count(self) -> int:
        count = ctypes.c_uint32()
        if not self.api.GetProcessHandleCount(self.api.GetCurrentProcess(), ctypes.byref(count)):
            raise windows_ctypes().WinError(windows_ctypes().get_last_error())
        return count.value

    def metadata(self, path: Path) -> NativeMetadata:
        handle = self.api.CreateFileW(extended_path(path), 0x80, 7, None, 3, 0x02200000, None)
        if handle in {None, ctypes.c_void_p(-1).value}:
            raise windows_ctypes().WinError(windows_ctypes().get_last_error())
        try:
            basic, standard, identity = BasicInformation(), StandardInformation(), FileIdentity()
            for information, storage in ((0, basic), (1, standard), (18, identity)):
                if not self.api.GetFileInformationByHandleEx(handle, information, ctypes.byref(storage), ctypes.sizeof(storage)):
                    raise windows_ctypes().WinError(windows_ctypes().get_last_error())
            return NativeMetadata(
                identity.volume, bytes(identity.identifier), basic.attributes,
                standard.links, standard.size, standard.directory, int(self.api.GetFileType(handle) or 0),
            )
        finally:
            if not self.api.CloseHandle(handle):
                raise windows_ctypes().WinError(windows_ctypes().get_last_error())

    def filesystem(self, path: Path) -> str:
        self.api.GetVolumePathNameW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        self.api.GetVolumePathNameW.restype = ctypes.c_int
        self.api.GetVolumeInformationW.argtypes = (
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
        )
        self.api.GetVolumeInformationW.restype = ctypes.c_int
        volume, filesystem = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(32)
        if not self.api.GetVolumePathNameW(str(path), volume, len(volume)):
            raise windows_ctypes().WinError(windows_ctypes().get_last_error())
        if not self.api.GetVolumeInformationW(volume, None, 0, None, None, None, filesystem, len(filesystem)):
            raise windows_ctypes().WinError(windows_ctypes().get_last_error())
        return filesystem.value


def extended_path(path: Path) -> str:
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def create_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    if completed.returncode != 0:
        raise OSError(f"Native junction creation failed: {completed.stdout} {completed.stderr}")
