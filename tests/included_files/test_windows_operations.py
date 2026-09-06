"""Windows ABI and lookup contracts; modeled calls are distinct from native proof."""

import ctypes
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, call, patch

from src.conversion.included_files_parts.windows_operations import (
    WindowsFileBasicInfo,
    WindowsFileId128,
    WindowsFileIdInfo,
    cleanup_parent_api,
    extended_path,
    file_read_api,
    lock_file,
    rename_transaction_entry,
    transaction_api,
    transaction_error,
)


class TestIncludedFilesWindowsOperations(unittest.TestCase):
    def setUp(self) -> None:
        for loader in (file_read_api, cleanup_parent_api, transaction_api):
            loader.cache_clear()
            self.addCleanup(loader.cache_clear)

    def _assert_layout(self) -> None:
        self.assertEqual(ctypes.sizeof(WindowsFileId128), 16)
        self.assertEqual(WindowsFileId128.Identifier.offset, 0)
        self.assertEqual(ctypes.sizeof(WindowsFileIdInfo), 24)
        self.assertEqual(WindowsFileIdInfo.VolumeSerialNumber.offset, 0)
        self.assertEqual(WindowsFileIdInfo.FileId.offset, 8)
        self.assertEqual(ctypes.sizeof(WindowsFileBasicInfo), 40)
        self.assertEqual(
            (WindowsFileBasicInfo.CreationTime.offset, WindowsFileBasicInfo.LastAccessTime.offset,
             WindowsFileBasicInfo.LastWriteTime.offset, WindowsFileBasicInfo.ChangeTime.offset,
             WindowsFileBasicInfo.FileAttributes.offset),
            (0, 8, 16, 24, 32),
        )

    def test_abi_records_preserve_sizes_offsets_and_values(self) -> None:
        self._assert_layout()
        identity = WindowsFileIdInfo()
        identity.VolumeSerialNumber = 2**63 + 17
        identity.FileId.Identifier[:] = bytes(range(16))
        self.assertEqual(identity.VolumeSerialNumber, 2**63 + 17)
        self.assertEqual(bytes(identity.FileId.Identifier), bytes(range(16)))
        basic = WindowsFileBasicInfo(-11, -22, 33, 44, 0x410)
        self.assertEqual(
            (basic.CreationTime, basic.LastAccessTime, basic.LastWriteTime, basic.ChangeTime, basic.FileAttributes),
            (-11, -22, 33, 44, 0x410),
        )

    def _assert_read_signatures(self, create: Mock, close: Mock) -> None:
        self.assertEqual(create.argtypes, (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ))
        self.assertIs(create.restype, ctypes.c_void_p)
        self.assertEqual(close.argtypes, (ctypes.c_void_p,))
        self.assertIs(close.restype, ctypes.c_int)

    def _assert_query_signatures(self, information: Mock, file_type: Mock) -> None:
        self.assertEqual(information.argtypes, (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32))
        self.assertIs(information.restype, ctypes.c_int)
        self.assertEqual(file_type.argtypes, (ctypes.c_void_p,))
        self.assertIs(file_type.restype, ctypes.c_uint32)

    def _assert_move_signature(self, move: Mock) -> None:
        self.assertEqual(move.argtypes, (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32))
        self.assertIs(move.restype, ctypes.c_int)

    def _assert_missing_loader_lookup(self) -> None:
        missing = AttributeError("WinDLL unavailable")
        lookup = Mock(side_effect=missing)
        with patch.dict(ctypes.__dict__), patch.object(ctypes, "__getattr__", lookup, create=True):
            ctypes.__dict__.pop("WinDLL", None)
            with patch.object(os, "name", "nt"):
                for loader in (file_read_api, cleanup_parent_api, transaction_api):
                    loader.cache_clear()
                    with self.assertRaises(AttributeError) as caught:
                        loader()
                    self.assertIs(caught.exception, missing)
                    self.assertEqual(loader.cache_info().currsize, 0)
        self.assertEqual(lookup.call_args_list, [call("WinDLL")] * 3)

    def test_cached_loaders_preserve_signatures_and_independent_lifetimes(self) -> None:
        events: list[str] = []
        apis = [Mock(), Mock(), Mock(), Mock()]
        dll = Mock(side_effect=apis)

        def lookup(name: str) -> object:
            events.append(name)
            if name == "WinDLL":
                return dll
            raise AttributeError(name)

        with patch.dict(ctypes.__dict__), patch.object(ctypes, "__getattr__", lookup, create=True):
            ctypes.__dict__.pop("WinDLL", None)
            with patch.object(os, "name", "nt"):
                for loader, api in zip((file_read_api, cleanup_parent_api, transaction_api), apis[:3], strict=True):
                    self.assertIs(loader(), api)
                    self.assertIs(loader(), api)
                    self.assertEqual(loader.cache_info().maxsize, 1)
                file_read_api.cache_clear()
                self.assertIs(file_read_api(), apis[3])
                self.assertIs(cleanup_parent_api(), apis[1])
                self.assertIs(transaction_api(), apis[2])
        self.assertEqual(events, ["WinDLL"] * 4)
        self.assertEqual(dll.call_args_list, [call("kernel32", use_last_error=True)] * 4)
        self._assert_read_signatures(apis[0].CreateFileW, apis[0].CloseHandle)
        self._assert_read_signatures(apis[1].CreateFileW, apis[1].CloseHandle)
        self._assert_query_signatures(apis[1].GetFileInformationByHandleEx, apis[1].GetFileType)
        self._assert_move_signature(apis[2].MoveFileExW)
        self._assert_missing_loader_lookup()

    def test_loaders_reject_non_windows_before_loading(self) -> None:
        messages = (
            "Windows Included File read handles are unavailable",
            "Windows Included Files cleanup parent handles are unavailable",
            "Windows Included Files transaction APIs are unavailable",
        )
        with patch.object(os, "name", "posix"), patch.object(ctypes, "WinDLL", create=True) as dll:
            for loader, message in zip((file_read_api, cleanup_parent_api, transaction_api), messages, strict=True):
                with self.subTest(message=message), self.assertRaises(OSError) as caught:
                    loader()
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(loader.cache_info().currsize, 0)
            dll.assert_not_called()

    def test_cleanup_loader_rejects_unsupported_layout_before_loading(self) -> None:
        cases = ((15, 24, 8, 40, 32), (16, 23, 8, 40, 32), (16, 24, 7, 40, 32),
                 (16, 24, 8, 39, 32), (16, 24, 8, 40, 31))
        for id_size, info_size, id_offset, basic_size, attributes_offset in cases:
            with self.subTest(case=(id_size, info_size, id_offset, basic_size, attributes_offset)):
                with (
                    patch.object(os, "name", "nt"),
                    patch.object(ctypes, "sizeof", side_effect=(id_size, info_size, basic_size)),
                    patch.object(ctypes, "WinDLL", create=True) as dll,
                    patch("src.conversion.included_files_parts.windows_operations.WindowsFileIdInfo",
                          Mock(FileId=Mock(offset=id_offset))),
                    patch("src.conversion.included_files_parts.windows_operations.WindowsFileBasicInfo",
                          Mock(FileAttributes=Mock(offset=attributes_offset))),
                    self.assertRaises(OSError) as caught,
                ):
                    cleanup_parent_api()
                self.assertEqual(str(caught.exception), "Unsupported Windows Included Files cleanup ABI layout")
                dll.assert_not_called()
                self.assertEqual(cleanup_parent_api.cache_info().currsize, 0)

    def test_transaction_error_preserves_lookup_order_number_and_filename(self) -> None:
        events: list[str] = []
        last = Mock(side_effect=lambda: events.append("call:last") or 5)

        def message(number: int) -> str:
            self.assertEqual(number, 5)
            events.append("call:format")
            return " denied \r\n"

        format_message = Mock(side_effect=message)
        absent = ""
        missing = AttributeError("selected ctypes attribute absent")

        def lookup(name: str) -> object:
            events.append("lookup:" + name)
            if name == absent:
                raise missing
            if name == "get_last_error":
                return last
            if name == "FormatError":
                return format_message
            raise AttributeError(name)

        with patch.dict(ctypes.__dict__), patch.object(ctypes, "__getattr__", lookup, create=True):
            ctypes.__dict__.pop("get_last_error", None)
            ctypes.__dict__.pop("FormatError", None)
            error = transaction_error("move", "destination")
            self.assertEqual((error.errno, error.strerror, error.filename), (5, "move: denied", "destination"))
            self.assertEqual(events, ["lookup:get_last_error", "lookup:FormatError", "call:last", "call:format"])
            format_message.assert_called_once_with(5)
            for absent in ("get_last_error", "FormatError"):
                events.clear()
                last.reset_mock()
                with self.subTest(absent=absent), self.assertRaises(AttributeError) as caught:
                    transaction_error("move", "destination")
                self.assertIs(caught.exception, missing)
                self.assertEqual(events, ["lookup:get_last_error"] +
                                 (["lookup:FormatError"] if absent == "FormatError" else []))
                last.assert_not_called()

    def test_lock_file_preserves_one_byte_and_error_identity(self) -> None:
        events: list[str] = []
        locking = Mock()
        missing = AttributeError("locking unavailable")
        absent = False

        def lookup(name: str) -> object:
            events.append(name)
            if name == "locking" and not absent:
                return locking
            raise missing

        module = ModuleType("msvcrt")
        with patch.object(module, "__getattr__", lookup, create=True), patch.dict(sys.modules, {"msvcrt": module}):
            lock_file(41, 2)
            locking.assert_called_once_with(41, 2, 1)
            failure = OSError("CRT lock failed")
            locking.side_effect = failure
            with self.assertRaises(OSError) as caught:
                lock_file(41, 0)
            self.assertIs(caught.exception, failure)
            self.assertEqual(locking.call_args_list, [call(41, 2, 1), call(41, 0, 1)])
            absent = True
            with self.assertRaises(AttributeError) as caught:
                lock_file(41, 2)
            self.assertIs(caught.exception, missing)
            self.assertEqual(events, ["locking"] * 3)

    def _assert_extended_paths(self) -> None:
        cases = (("\\\\?\\C:\\x", "\\\\?\\C:\\x"), ("\\\\.\\device", "\\\\.\\device"),
                 ("\\\\server\\share\\x", "\\\\?\\UNC\\server\\share\\x"), ("C:\\x", "\\\\?\\C:\\x"))
        for absolute, expected in cases:
            with self.subTest(absolute=absolute), patch.object(os.path, "abspath", return_value=absolute) as resolve:
                self.assertEqual(extended_path("input"), expected)
                resolve.assert_called_once_with("input")

    def test_rename_preserves_refusal_fallback_native_flags_and_error(self) -> None:
        self._assert_extended_paths()
        api = Mock()
        with patch("src.conversion.included_files_parts.windows_operations.transaction_api", return_value=api) as load:
            with patch.object(os, "name", "posix"), patch.object(os, "rename") as rename:
                with self.assertRaises(OSError) as caught:
                    rename_transaction_entry("source", "destination")
                self.assertEqual(str(caught.exception), "Unsafe path-based Included Files rename is disabled on POSIX")
                rename.assert_not_called()
                load.assert_not_called()
            failure = OSError("modeled rename failed")
            with patch.object(os, "name", "nt"), patch.object(sys, "platform", "darwin"):
                with patch.object(os, "rename", side_effect=failure) as rename:
                    with self.assertRaises(OSError) as caught:
                        rename_transaction_entry("source", "destination")
                    self.assertIs(caught.exception, failure)
                    rename.assert_called_once_with("source", "destination")
                    load.assert_not_called()
            with patch.object(os, "name", "nt"), patch.object(sys, "platform", "win32"):
                with patch("src.conversion.included_files_parts.windows_operations.extended_path",
                           side_effect=("extended source", "extended destination")):
                    rename_transaction_entry("source", "destination")
                api.MoveFileExW.assert_called_once_with("extended source", "extended destination", 8)
                api.MoveFileExW.return_value = 0
                with patch("src.conversion.included_files_parts.windows_operations.transaction_error",
                           return_value=failure) as error:
                    with self.assertRaises(OSError) as caught:
                        rename_transaction_entry("source", "destination")
                    self.assertIs(caught.exception, failure)
                    error.assert_called_once_with(
                        "Could not durably move Included Files transaction entry", "destination",
                    )

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows API calls")
    def test_native_windows_abi_and_write_through_rename(self) -> None:
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)
        self._assert_layout()
        read_api, parent_api, move_api = file_read_api(), cleanup_parent_api(), transaction_api()
        self._assert_read_signatures(read_api.CreateFileW, read_api.CloseHandle)
        self._assert_read_signatures(parent_api.CreateFileW, parent_api.CloseHandle)
        self._assert_query_signatures(parent_api.GetFileInformationByHandleEx, parent_api.GetFileType)
        self._assert_move_signature(move_api.MoveFileExW)
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory, "source"), Path(directory, "destination")
            source.write_bytes(b"native rename")
            rename_transaction_entry(str(source), str(destination))
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b"native rename")
            source.write_bytes(b"collision source")
            with self.assertRaises(OSError) as caught:
                rename_transaction_entry(str(source), str(destination))
            self.assertEqual(caught.exception.filename, str(destination))
            self.assertEqual(source.read_bytes(), b"collision source")
            self.assertEqual(destination.read_bytes(), b"native rename")
            source.unlink()
            destination.unlink()
