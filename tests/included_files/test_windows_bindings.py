"""Cleanup-parent handle and error ownership with finite native-call models."""

import ctypes
import os
import stat
import unittest
from unittest.mock import Mock, call, patch

from src.conversion.included_files_parts.windows_bindings import (
    WindowsCleanupParentBinding,
    cleanup_parent_attributes,
    cleanup_parent_identity,
    verify_cleanup_parent_binding,
)
from src.conversion.included_files_parts.windows_operations import WindowsFileBasicInfo, WindowsFileIdInfo


class TestIncludedFilesWindowsBindings(unittest.TestCase):
    def _state(self, mode: int = stat.S_IFDIR, device: int = 5, inode: int = 9) -> os.stat_result:
        return os.stat_result((mode | 0o700, inode, device, 1, 0, 0, 0, 0, 0, 0))

    def _assert_open_validation(self, state: os.stat_result, redirected: bool) -> None:
        with (
            patch.object(os, "name", "nt"),
            patch.object(os.path, "abspath", return_value="absolute"),
            patch.object(os, "lstat", return_value=state),
            patch("src.conversion.included_files_parts.windows_bindings.output_path_is_redirected",
                  return_value=redirected),
            patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_api") as load,
            self.assertRaises(OSError) as caught,
        ):
            WindowsCleanupParentBinding.open("parent", (5, 9))
        self.assertEqual(str(caught.exception), "Included Files cleanup parent changed: absolute")
        load.assert_not_called()

    def test_open_refusals_precede_native_acquisition(self) -> None:
        with patch.object(os, "name", "posix"), patch.object(os, "lstat") as inspect:
            with self.assertRaises(OSError) as caught:
                WindowsCleanupParentBinding.open("parent", (5, 9))
            self.assertEqual(str(caught.exception), "Windows Included Files cleanup parent bindings are unavailable")
            inspect.assert_not_called()
        failure = FileNotFoundError("parent missing")
        with (
            patch.object(os, "name", "nt"),
            patch.object(os.path, "abspath", return_value="absolute"),
            patch.object(os, "lstat", side_effect=failure),
            patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_api") as load,
            self.assertRaises(OSError) as caught,
        ):
            WindowsCleanupParentBinding.open("parent", (5, 9))
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(str(caught.exception), "Included Files cleanup parent changed: absolute")
        load.assert_not_called()
        self._assert_open_validation(self._state(), True)
        self._assert_open_validation(self._state(stat.S_IFREG), False)
        self._assert_open_validation(self._state(device=6), False)
        self._assert_invalid_handles()

    def _assert_invalid_handles(self) -> None:
        failure = OSError("CreateFileW failed")
        for value in (None, ctypes.c_void_p(-1).value):
            api = Mock(CreateFileW=Mock(return_value=value))
            with (
                self.subTest(handle=value),
                patch.object(os, "name", "nt"),
                patch.object(os.path, "abspath", return_value="absolute"),
                patch.object(os, "lstat", return_value=self._state()),
                patch("src.conversion.included_files_parts.windows_bindings.output_path_is_redirected",
                      return_value=False),
                patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_api", return_value=api),
                patch("src.conversion.included_files_parts.windows_bindings.transaction_error",
                      return_value=failure) as err,
                self.assertRaises(OSError) as caught,
            ):
                WindowsCleanupParentBinding.open("parent", (5, 9))
            self.assertIs(caught.exception, failure)
            err.assert_called_once_with("Could not bind Included Files cleanup parent", "absolute")
            api.CloseHandle.assert_not_called()

    def test_rejected_verification_retains_primary_error_and_close_note(self) -> None:
        for close_failure in (None, SystemExit("close interrupted")):
            failure = KeyboardInterrupt("verification interrupted")
            api = Mock(CreateFileW=Mock(return_value=71), CloseHandle=Mock(return_value=1, side_effect=close_failure))
            with (
                self.subTest(close_failure=close_failure),
                patch.object(os, "name", "nt"),
                patch.object(os.path, "abspath", return_value="absolute"),
                patch.object(os, "lstat", return_value=self._state()),
                patch("src.conversion.included_files_parts.windows_bindings.output_path_is_redirected",
                      return_value=False),
                patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_api", return_value=api),
                patch("src.conversion.included_files_parts.windows_bindings.extended_path",
                      return_value="extended") as ext,
                patch.object(WindowsCleanupParentBinding, "verify", autospec=True, side_effect=failure) as verify,
                self.assertRaises(KeyboardInterrupt) as caught,
            ):
                WindowsCleanupParentBinding.open("parent", (5, 9))
            self.assertIs(caught.exception, failure)
            ext.assert_called_once_with("absolute")
            api.CreateFileW.assert_called_once_with(
                "extended", 0x20 | 0x80, 1 | 2, None, 3, 0x02000000 | 0x00200000, None,
            )
            api.CloseHandle.assert_called_once_with(71)
            binding = verify.call_args.args[0]
            self.assertIsInstance(binding, WindowsCleanupParentBinding)
            self.assertEqual((binding.path, binding.identity, binding.kernel32, binding.handle),
                             ("absolute", (5, 9), api, None))
            self.assertEqual(getattr(failure, "__notes__", []), [] if close_failure is None else [
                "Could not close rejected Included Files cleanup parent binding: close interrupted",
            ])

    def test_context_entry_and_exit_preserve_verification_and_error_order(self) -> None:
        api = Mock(CloseHandle=Mock(return_value=1))
        binding = WindowsCleanupParentBinding("parent", (5, 9), api, 71)
        failure = KeyboardInterrupt("entry interrupted")
        with patch.object(binding, "verify", side_effect=failure) as verify:
            with self.assertRaises(KeyboardInterrupt) as caught:
                with binding:
                    self.fail("failed entry must not enter the body")
            self.assertIs(caught.exception, failure)
            verify.assert_called_once_with()
        self.assertEqual(binding.handle, 71)
        api.CloseHandle.assert_not_called()
        with patch.object(binding, "verify") as verify:
            with binding as entered:
                self.assertIs(entered, binding)
            verify.assert_called_once_with()
        api.CloseHandle.assert_called_once_with(71)
        self.assertIsNone(binding.handle)
        self._assert_exit_failure(None)
        self._assert_exit_failure(KeyboardInterrupt("active error"))

    def _assert_exit_failure(self, active: BaseException | None) -> None:
        failure = OSError("close failed")
        api = Mock(CloseHandle=Mock(side_effect=failure))
        binding = WindowsCleanupParentBinding("parent", (5, 9), api, 71)
        if active is None:
            with self.assertRaises(OSError) as caught:
                binding.__exit__(None, None, None)
            self.assertIs(caught.exception, failure)
        else:
            active.add_note("prior note")
            self.assertIsNone(binding.__exit__(type(active), active, None))
            self.assertEqual(active.__notes__, [
                "prior note", "Could not close Included Files cleanup parent binding: close failed",
            ])
        self.assertIsNone(binding.handle)
        api.CloseHandle.assert_called_once_with(71)

    def test_close_clears_handle_before_native_call_and_never_retries(self) -> None:
        for answer in (0, 1):
            self._assert_close_answer(answer)

    def _assert_close_answer(self, answer: int) -> None:
        binding = WindowsCleanupParentBinding("parent", (5, 9), Mock(), 71)
        states: list[int | None] = []

        def close(handle: int) -> int:
            self.assertEqual(handle, 71)
            states.append(binding.handle)
            return answer

        binding.kernel32.CloseHandle.side_effect = close
        failure = OSError("close failed")
        with patch("src.conversion.included_files_parts.windows_bindings.transaction_error",
                   return_value=failure) as err:
            if answer:
                self.assertIsNone(binding.close())
                err.assert_not_called()
            else:
                with self.assertRaises(OSError) as caught:
                    binding.close()
                self.assertIs(caught.exception, failure)
                err.assert_called_once_with("Could not close Included Files cleanup parent handle", "parent")
            self.assertIsNone(binding.close())
        self.assertEqual(states, [None])
        self.assertIsNone(binding.handle)
        binding.kernel32.CloseHandle.assert_called_once_with(71)

    def _assert_verify_case(self, fail_at: str) -> None:
        api = Mock(GetFileType=Mock(return_value=2 if fail_at == "file_type" else 1))
        binding = WindowsCleanupParentBinding("parent", (5, 9), api, 71)
        state = self._state(stat.S_IFREG if fail_at == "directory" else stat.S_IFDIR,
                            device=6 if fail_at == "path_identity" else 5)
        attributes = 0 if fail_at == "directory_attribute" else 0x410 if fail_at == "reparse_attribute" else 0x10
        trace = Mock()
        with (
            patch.object(os, "lstat", return_value=state) as inspect,
            patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_attributes",
                  return_value=attributes) as attrs,
            patch("src.conversion.included_files_parts.windows_bindings.output_path_is_redirected",
                  return_value=fail_at == "redirect") as redirect,
            patch.object(stat, "S_ISDIR", wraps=stat.S_ISDIR) as directory,
            patch("src.conversion.included_files_parts.windows_bindings.cleanup_parent_identity",
                  return_value=(6, 9) if fail_at == "native_identity" else (5, 9)) as identity,
        ):
            for name, method in (("lstat", inspect), ("attributes", attrs), ("file_type", api.GetFileType),
                                 ("redirect", redirect), ("directory", directory), ("identity", identity)):
                trace.attach_mock(method, name)
            if fail_at:
                with self.assertRaises(OSError) as caught:
                    binding.verify()
                self.assertEqual(str(caught.exception), "Included Files cleanup parent changed: parent")
            else:
                self.assertIsNone(binding.verify())
            order = ["lstat", "attributes", "file_type", "redirect", "directory", "identity"]
            stop = {"file_type": 3, "redirect": 4, "directory": 5, "path_identity": 5}.get(fail_at, 6)
            self.assertEqual([entry[0] for entry in trace.mock_calls], order[:stop])
            inspect.assert_called_once_with("parent")
            attrs.assert_called_once_with(api, 71, "parent")
            api.GetFileType.assert_called_once_with(71)

    def _assert_queries_preserve_records_and_failures(self) -> None:
        identity = WindowsFileIdInfo()
        identity.VolumeSerialNumber = 2**63 + 17
        identity.FileId.Identifier[:] = bytes(range(16))
        basic = WindowsFileBasicInfo(0, 0, 0, 0, 0x410)
        api = Mock(GetFileInformationByHandleEx=Mock(return_value=1))
        with patch("src.conversion.included_files_parts.windows_bindings.WindowsFileIdInfo", return_value=identity):
            self.assertEqual(cleanup_parent_identity(api, 71, "parent"),
                             (2**63 + 17, int.from_bytes(bytes(range(16)), "little")))
        self.assertEqual(api.GetFileInformationByHandleEx.call_args.args[:2], (71, 18))
        self.assertEqual(api.GetFileInformationByHandleEx.call_args.args[3], 24)
        with patch("src.conversion.included_files_parts.windows_bindings.WindowsFileBasicInfo", return_value=basic):
            self.assertEqual(cleanup_parent_attributes(api, 71, "parent"), 0x410)
        self.assertEqual(api.GetFileInformationByHandleEx.call_args.args[:2], (71, 0))
        self.assertEqual(api.GetFileInformationByHandleEx.call_args.args[3], 40)
        failure = OSError("native query failed")
        api.GetFileInformationByHandleEx.return_value = 0
        with patch("src.conversion.included_files_parts.windows_bindings.transaction_error",
                   return_value=failure) as err:
            for query, operation in ((cleanup_parent_identity, "identify"), (cleanup_parent_attributes, "inspect")):
                with self.subTest(operation=operation), self.assertRaises(OSError) as caught:
                    query(api, 71, "parent")
                self.assertIs(caught.exception, failure)
                self.assertEqual(err.call_args, call(
                    f"Could not {operation} Included Files cleanup parent handle", "parent",
                ))

    def test_verify_preserves_short_circuit_order_and_closed_refusal(self) -> None:
        binding = WindowsCleanupParentBinding("parent", (5, 9), Mock(), None)
        with patch.object(os, "lstat") as inspect, self.assertRaises(OSError) as caught:
            binding.verify()
        self.assertEqual(str(caught.exception), "Included Files cleanup parent binding is closed: parent")
        inspect.assert_not_called()
        binding.handle = 71
        failure = FileNotFoundError("parent missing")
        with patch.object(os, "lstat", side_effect=failure), self.assertRaises(OSError) as caught:
            binding.verify()
        self.assertIs(caught.exception.__cause__, failure)
        for fail_at in ("", "file_type", "redirect", "directory", "path_identity", "native_identity",
                        "directory_attribute", "reparse_attribute"):
            with self.subTest(fail_at=fail_at):
                self._assert_verify_case(fail_at)
        self._assert_queries_preserve_records_and_failures()

    def _assert_binding_mismatch(self, binding: WindowsCleanupParentBinding, identity: tuple[int, int]) -> None:
        with patch.object(binding, "verify") as verify, self.assertRaises(OSError) as caught:
            verify_cleanup_parent_binding(binding, "input", identity)
        self.assertEqual(
            str(caught.exception), "Included Files cleanup parent binding mismatch: absolute",
        )
        verify.assert_not_called()

    def test_binding_argument_mismatch_precedes_verify(self) -> None:
        binding = WindowsCleanupParentBinding("ABSOLUTE", (5, 9), Mock(), 71)
        with patch.object(os.path, "abspath", return_value="absolute") as resolve:
            with patch.object(os.path, "normcase", side_effect=str.lower):
                for host, identity in (("posix", (5, 9)), ("nt", (6, 9))):
                    with self.subTest(host=host, identity=identity), patch.object(os, "name", host):
                        self._assert_binding_mismatch(binding, identity)
                with patch.object(os, "name", "nt"), patch.object(binding, "verify") as verify:
                    self.assertIsNone(verify_cleanup_parent_binding(binding, "input", (5, 9)))
                    verify.assert_called_once_with()
                binding.path = "different"
                with patch.object(os, "name", "nt"), patch.object(binding, "verify") as verify:
                    with self.assertRaises(OSError):
                        verify_cleanup_parent_binding(binding, "input", (5, 9))
                    verify.assert_not_called()
            self.assertEqual(resolve.call_args_list, [call("input")] * 4)
