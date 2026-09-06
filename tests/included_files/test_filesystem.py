"""Validation-stream ownership; modeled failures never claim native handle proof."""

import ctypes
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from src.conversion.included_files_parts.filesystem import open_validation_stream


class TestIncludedFilesFilesystem(unittest.TestCase):
    def test_plain_validation_open_avoids_native_acquisition(self) -> None:
        for host, deny in (("posix", False), ("posix", True), ("nt", False)):
            stream = io.BytesIO(b"plain")
            with (
                self.subTest(host=host, deny=deny),
                patch.object(os, "name", host),
                patch("builtins.open", return_value=stream) as plain,
                patch.object(os, "open") as descriptor,
                patch("src.conversion.included_files_parts.filesystem.file_read_api") as load,
            ):
                self.assertIs(open_validation_stream("payload", deny_writes=deny), stream)
                plain.assert_called_once_with("payload", "rb")
                descriptor.assert_not_called()
                load.assert_not_called()
                self.assertFalse(stream.closed)
            stream.close()

    def _assert_posix_wrapper_failure(self, close_failure: BaseException | None) -> None:
        failure = KeyboardInterrupt("fdopen interrupted")
        with (
            patch.object(os, "name", "posix"),
            patch.object(os, "open", return_value=31),
            patch.object(os, "fdopen", side_effect=failure),
            patch.object(os, "close", side_effect=close_failure) as close,
            self.assertRaises(BaseException) as caught,
        ):
            open_validation_stream("payload", deny_writes=True, no_follow=True)
        self.assertIs(caught.exception, close_failure or failure)
        close.assert_called_once_with(31)

    def test_posix_no_follow_transfers_fd_and_closes_wrapper_failure(self) -> None:
        for supported in (False, True):
            stream = io.BytesIO(b"no follow")
            with (
                self.subTest(supported=supported),
                patch.object(os, "name", "posix"),
                patch.dict(os.__dict__),
                patch.object(os, "open", return_value=31) as acquire,
                patch.object(os, "fdopen", return_value=stream) as wrap,
                patch.object(os, "close") as close,
                patch("src.conversion.included_files_parts.filesystem.file_read_api") as load,
            ):
                os.__dict__.pop("O_NOFOLLOW", None)
                if supported:
                    os.__dict__["O_NOFOLLOW"] = 0x20000000
                self.assertIs(open_validation_stream("payload", deny_writes=False, no_follow=True), stream)
                acquire.assert_called_once_with("payload", os.O_RDONLY | (0x20000000 if supported else 0))
                wrap.assert_called_once_with(31, "rb")
                close.assert_not_called()
                load.assert_not_called()
                self.assertFalse(stream.closed)
            stream.close()
        self._assert_posix_wrapper_failure(None)
        self._assert_posix_wrapper_failure(OSError("descriptor close failed"))

    def _assert_error_lookups(self, api: Mock, absent: str) -> None:
        events: list[str] = []
        missing = AttributeError("selected ctypes attribute absent")

        def last_error() -> int:
            events.append("call:last")
            return 5

        def message(number: int) -> str:
            self.assertEqual(number, 5)
            events.append("call:format")
            return " denied \r\n"

        def lookup(name: str) -> object:
            events.append("lookup:" + name)
            if name == absent:
                raise missing
            if name == "get_last_error":
                return last_error
            if name == "FormatError":
                return message
            raise AttributeError(name)

        with (
            patch.object(os, "name", "nt"),
            patch.dict(ctypes.__dict__),
            patch.object(ctypes, "__getattr__", lookup, create=True),
            patch("src.conversion.included_files_parts.filesystem.file_read_api", return_value=api),
            patch.object(os, "close") as close,
            self.assertRaises((OSError, AttributeError)) as caught,
        ):
            ctypes.__dict__.pop("get_last_error", None)
            ctypes.__dict__.pop("FormatError", None)
            open_validation_stream("payload", deny_writes=True)
        expected = ["lookup:get_last_error"]
        if absent != "get_last_error":
            expected += ["call:last", "lookup:FormatError"]
        if not absent:
            expected.append("call:format")
            self.assertIsInstance(caught.exception, OSError)
            assert isinstance(caught.exception, OSError)
            self.assertEqual((caught.exception.errno, caught.exception.strerror, caught.exception.filename),
                             (5, "denied", "payload"))
        else:
            self.assertIs(caught.exception, missing)
        self.assertEqual(events, expected)
        api.CloseHandle.assert_not_called()
        close.assert_not_called()

    def test_windows_invalid_handles_preserve_error_without_close(self) -> None:
        for invalid in (None, ctypes.c_void_p(-1).value):
            for absent in ("", "get_last_error", "FormatError"):
                with self.subTest(handle=invalid, absent=absent):
                    self._assert_error_lookups(Mock(CreateFileW=Mock(return_value=invalid)), absent)

    def test_windows_handle_transfer_failure_closes_native_handle_once(self) -> None:
        for close_failure in (None, OSError("native close failed")):
            failure = SystemExit("CRT transfer interrupted")
            api = Mock(CreateFileW=Mock(return_value=71), CloseHandle=Mock(side_effect=close_failure))
            transfer = Mock(side_effect=failure)
            module = ModuleType("msvcrt")
            with (
                self.subTest(close_failure=close_failure),
                patch.object(os, "name", "nt"),
                patch.object(module, "open_osfhandle", transfer, create=True),
                patch.dict(sys.modules, {"msvcrt": module}),
                patch("src.conversion.included_files_parts.filesystem.file_read_api", return_value=api),
                patch.object(os, "fdopen") as wrap,
                patch.object(os, "close") as close,
                self.assertRaises(BaseException) as caught,
            ):
                open_validation_stream("payload", deny_writes=True)
            self.assertIs(caught.exception, close_failure or failure)
            transfer.assert_called_once_with(71, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            api.CloseHandle.assert_called_once_with(71)
            wrap.assert_not_called()
            close.assert_not_called()

    def _assert_windows_wrapper_failure(self, close_failure: BaseException | None) -> None:
        api = Mock(CreateFileW=Mock(return_value=71))
        failure = KeyboardInterrupt("stream transfer interrupted")
        module = ModuleType("msvcrt")
        with (
            patch.object(os, "name", "nt"),
            patch.object(module, "open_osfhandle", return_value=31, create=True),
            patch.dict(sys.modules, {"msvcrt": module}),
            patch("src.conversion.included_files_parts.filesystem.file_read_api", return_value=api),
            patch.object(os, "fdopen", side_effect=failure),
            patch.object(os, "close", side_effect=close_failure) as close,
            self.assertRaises(BaseException) as caught,
        ):
            open_validation_stream("payload", deny_writes=True, no_follow=True)
        self.assertIs(caught.exception, close_failure or failure)
        close.assert_called_once_with(31)
        api.CloseHandle.assert_not_called()

    def test_windows_stream_wrapper_failure_closes_only_transferred_fd(self) -> None:
        for deny, no_follow in ((True, False), (False, True), (True, True)):
            api = Mock(CreateFileW=Mock(return_value=71))
            module = ModuleType("msvcrt")
            stream = io.BytesIO(b"transferred")
            with (
                self.subTest(deny=deny, no_follow=no_follow),
                patch.object(os, "name", "nt"),
                patch.object(module, "open_osfhandle", return_value=31, create=True) as transfer,
                patch.dict(sys.modules, {"msvcrt": module}),
                patch("src.conversion.included_files_parts.filesystem.file_read_api", return_value=api),
                patch("src.conversion.included_files_parts.filesystem.extended_path",
                      return_value="extended") as extend,
                patch.object(os, "fdopen", return_value=stream) as wrap,
                patch.object(os, "close") as close,
            ):
                self.assertIs(open_validation_stream("payload", deny_writes=deny, no_follow=no_follow), stream)
                extend.assert_called_once_with("payload")
                api.CreateFileW.assert_called_once_with(
                    "extended", 0x80000000, 1, None, 3, 0x80 | 0x08000000 | (0x00200000 if no_follow else 0), None,
                )
                transfer.assert_called_once_with(71, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                wrap.assert_called_once_with(31, "rb")
                close.assert_not_called()
                api.CloseHandle.assert_not_called()
                self.assertFalse(stream.closed)
            stream.close()
        self._assert_windows_wrapper_failure(None)
        self._assert_windows_wrapper_failure(OSError("descriptor close failed"))

    def _assert_write_access_denied(self, path: Path) -> None:
        with self.assertRaises(PermissionError):
            with path.open("r+b") as forbidden:
                forbidden.read(0)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows sharing and handle transfer")
    def test_native_windows_validation_stream_closure_restores_write_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "payload")
            path.write_bytes(b"read sharing")
            for deny, no_follow in ((True, False), (False, True), (True, True)):
                with self.subTest(deny=deny, no_follow=no_follow):
                    with open_validation_stream(str(path), deny_writes=deny, no_follow=no_follow) as stream:
                        self.assertEqual(stream.read(), b"read sharing")
                        self.assertGreaterEqual(stream.fileno(), 0)
                        self._assert_write_access_denied(path)
                    with path.open("r+b") as writer:
                        self.assertEqual(writer.read(), b"read sharing")
                        writer.seek(0)
                        writer.write(b"read sharing")
            path.unlink()
