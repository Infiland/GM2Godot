# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import gc
import inspect
from pathlib import Path
import sys
from types import FrameType
from typing import Any, cast
import unittest
from unittest import mock

from scripts import _anchored_output as anchored
from scripts import _anchored_receipt_windows as receipt
from scripts import verify_dependency_environment as verifier
from tests.test_anchored_receipt_windows import FakeKernel32
from tests.test_anchored_receipt_windows_relative import (
    FakeKernelApi,
    FakeNtApi,
    _SequencedCloseKernelApi,
)


PAYLOAD = b'{"status":"verified"}\n'
_API_NAMES = (
    "NtCreateFile",
    "RtlNtStatusToDosError",
    "WriteFile",
    "ReadFile",
    "FlushFileBuffers",
    "SetFilePointerEx",
    "GetFileInformationByHandleEx",
    "SetFileInformationByHandle",
    "GetFileType",
    "CloseHandle",
)


class _Binding:
    def __init__(self, api: FakeKernel32) -> None:
        self.parent = Path("C:/bound")
        self.leaf = "receipt.json"
        self.windows_entries = ((self.parent, (1, 2), 0x4567),)
        self.windows_api = api
        self.closed = 0
        self.verified = 0
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def stat(self, _name: str) -> Any:
        raise FileNotFoundError

    def verify(self) -> None:
        self.verified += 1

    def close(self) -> tuple[BaseException, ...]:
        if not self._closed:
            self.closed += 1
            self._closed = True
        return ()


def _assignable_api(api: FakeKernel32) -> FakeKernel32:
    """Give the behavioral fake ctypes-like callables with writable ABI metadata."""

    for name in _API_NAMES:
        setattr(api, name, mock.Mock(wraps=getattr(api, name)))
    return api


class _SequencedNtApi(FakeNtApi):
    def __init__(self, handles: tuple[int, ...], information: tuple[int, ...]) -> None:
        super().__init__(information=information[0], handle=handles[0])
        self._handles = handles
        self._information = information

    def NtCreateFile(
        self,
        output: Any,
        desired_access: int,
        object_attributes: Any,
        io_status: Any,
        allocation_size: object,
        file_attributes: int,
        share_access: int,
        disposition: int,
        options: int,
        ea_buffer: object,
        ea_length: int,
    ) -> int:
        index = len(self.calls)
        self.handle = self._handles[index]
        self.information = self._information[index]
        return super().NtCreateFile(
            output,
            desired_access,
            object_attributes,
            io_status,
            allocation_size,
            file_attributes,
            share_access,
            disposition,
            options,
            ea_buffer,
            ea_length,
        )


class _ExistingWinnerKernel32(FakeKernel32):
    """Model a public winner that would be overwritten by replace semantics."""

    def __init__(self, public_data: bytes) -> None:
        super().__init__({"Rename": False})
        self.error = receipt.ERROR_FILE_EXISTS
        self.public_data = bytearray(public_data)

    def SetFileInformationByHandle(self, handle: int, info_class: int, pointer: Any, size: int) -> bool:
        if info_class == receipt.FILE_RENAME_INFO:
            raw = ctypes.string_at(pointer, size)
            info = receipt._FileRenameInfo.from_buffer_copy(
                raw + bytes(max(0, ctypes.sizeof(receipt._FileRenameInfo) - len(raw)))
            )
            if info.ReplaceIfExists:
                self.failures["Rename"] = True
                try:
                    result = super().SetFileInformationByHandle(handle, info_class, pointer, size)
                finally:
                    self.failures["Rename"] = False
                if result:
                    self.public_data[:] = self.data
                return result
        return super().SetFileInformationByHandle(handle, info_class, pointer, size)


class WindowsReceiptFacadeIntegrationTests(unittest.TestCase):
    def _owner(self, binding: _Binding) -> anchored._OutputParentBindingLease:
        owner = anchored._OutputParentBindingLease()
        owner.binding = cast(anchored.OutputParentBinding, binding)
        return owner

    def _scripted_reader(self) -> tuple[Any, mock.Mock]:
        helper = anchored._windows_receipt_module()
        observed = helper.WindowsReceiptResult("receipt.json", 77, bytes(range(16)), len(PAYLOAD))
        return helper, mock.Mock(side_effect=(FileNotFoundError(), observed))

    def _publish(self, api: FakeKernel32) -> tuple[_Binding, mock.Mock]:
        binding = _Binding(_assignable_api(api))
        helper, reader = self._scripted_reader()
        with mock.patch.object(helper, "read_windows_receipt", reader):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )
        return binding, reader

    def test_initial_exact_receipt_returns_without_native_publication(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        observed = helper.WindowsReceiptResult("receipt.json", 77, bytes(range(16)), len(PAYLOAD))
        with (
            mock.patch.object(helper, "read_windows_receipt", return_value=observed) as reader,
            mock.patch.object(helper, "publish_windows_receipt") as publish,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        reader.assert_called_once()
        publish.assert_not_called()
        self.assertEqual(cast(Any, api).NtCreateFile.call_count, 0)
        self.assertEqual(binding.closed, 1)

    def test_missing_target_does_not_swallow_missing_ancestor_verification(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        parent_missing = FileNotFoundError("bound ancestor disappeared")
        binding.verify = mock.Mock(side_effect=(None, None, parent_missing))
        helper = anchored._windows_receipt_module()
        with (
            mock.patch.object(helper, "read_windows_receipt", side_effect=FileNotFoundError),
            mock.patch.object(helper, "publish_windows_receipt") as publish,
            self.assertRaises(FileNotFoundError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertIs(raised.exception, parent_missing)
        publish.assert_not_called()
        self.assertEqual(binding.closed, 1)

    def test_helper_validation_error_keeps_code_and_closes_binding(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        validation = helper.WindowsReceiptValidationError(
            "output-existing-invalid",
            "induced retained-handle validation failure",
        )
        validation.add_note("validation note")
        with (
            mock.patch.object(helper, "read_windows_receipt", side_effect=validation),
            mock.patch.object(helper, "publish_windows_receipt") as publish,
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-existing-invalid")
        self.assertIs(raised.exception.__cause__, validation)
        self.assertIn("validation note", "\n".join(getattr(raised.exception, "__notes__", ())))
        publish.assert_not_called()
        self.assertEqual(binding.closed, 1)

    def test_post_open_missing_validation_cannot_masquerade_as_initial_absence(self) -> None:
        native_error = FileNotFoundError(
            receipt.ERROR_FILE_NOT_FOUND,
            "opened receipt disappeared during metadata validation",
        )
        native_error.add_note("post-open namespace note")
        kernel = FakeKernelApi()
        kernel.failures["GetInfo:0"] = native_error
        native = FakeNtApi(information=receipt.FILE_OPENED)
        binding = _Binding(cast(Any, kernel))
        helper = anchored._windows_receipt_module()

        def unchanged(api: Any) -> Any:
            return api

        with (
            mock.patch.object(helper, "_select_apis", return_value=(kernel, native)),
            mock.patch.object(helper, "_configure_api", side_effect=unchanged),
            mock.patch.object(helper, "_configure_nt_api", side_effect=unchanged),
            mock.patch.object(helper, "publish_windows_receipt") as publish,
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-changed")
        helper_error = raised.exception.__cause__
        assert helper_error is not None
        self.assertIsInstance(helper_error, helper.WindowsReceiptValidationError)
        self.assertIs(helper_error.__cause__, native_error)
        self.assertIn("post-open namespace note", getattr(raised.exception, "__notes__", ()))
        publish.assert_not_called()
        self.assertEqual(binding.closed, 1)

    def test_helper_validation_code_reaches_verifier_adapter(self) -> None:
        facade = verifier._ANCHORED_OUTPUT
        helper = facade._windows_receipt_module()
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        validation = helper.WindowsReceiptValidationError(
            "output-existing-invalid",
            "induced verifier-facing validation failure",
        )

        def publish(path: Path, payload: bytes) -> None:
            with mock.patch.object(helper, "read_windows_receipt", side_effect=validation):
                facade._publish_windows_receipt_bytes(
                    path,
                    payload,
                    binding,
                    self._owner(binding),
                )

        with (
            mock.patch.object(verifier, "_PUBLISH_IDENTICAL_RECEIPT_BYTES", side_effect=publish),
            self.assertRaises(verifier.ReceiptOutputError) as raised,
        ):
            verifier.atomic_write_receipt(
                binding.parent / binding.leaf,
                {"status": "verified"},
            )

        self.assertEqual(raised.exception.code, "output-existing-invalid")
        facade_error = raised.exception.__cause__
        self.assertIsInstance(facade_error, facade.AnchoredOutputError)
        assert facade_error is not None
        self.assertIs(facade_error.__cause__, validation)
        self.assertEqual(binding.closed, 1)

    def test_unpaired_surrogate_leaf_maps_to_path_invalid_without_native_call(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        binding.leaf = "receipt-\ud800.json"
        helper = anchored._windows_receipt_module()
        with (
            mock.patch.object(helper, "publish_windows_receipt") as publish,
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "path-invalid")
        publish.assert_not_called()
        self.assertEqual(cast(Any, api).NtCreateFile.call_count, 0)
        self.assertEqual(binding.closed, 1)

    def test_final_observation_must_match_published_volume_and_file_id(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        changed = helper.WindowsReceiptResult("receipt.json", 78, b"z" * 16, len(PAYLOAD))
        reader = mock.Mock(side_effect=(FileNotFoundError(), changed))
        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-changed")
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(binding.closed, 1)

    def test_final_validation_failures_remap_to_output_changed(self) -> None:
        helper = anchored._windows_receipt_module()
        for code in ("output-existing-invalid", "output-different"):
            with self.subTest(code=code):
                api = _assignable_api(FakeKernel32())
                binding = _Binding(api)
                validation = helper.WindowsReceiptValidationError(code, f"induced final {code}")
                validation.add_note("final validation note")
                reader = mock.Mock(side_effect=(FileNotFoundError(), validation))
                with (
                    mock.patch.object(helper, "read_windows_receipt", reader),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored._publish_windows_receipt_bytes(
                        binding.parent / binding.leaf,
                        PAYLOAD,
                        cast(anchored.OutputParentBinding, binding),
                        self._owner(binding),
                    )

                self.assertEqual(raised.exception.code, "output-changed")
                self.assertIs(raised.exception.__cause__, validation)
                self.assertIn("final validation note", getattr(raised.exception, "__notes__", ()))
                self.assertEqual(reader.call_count, 2)
                self.assertEqual(binding.closed, 1)

    def test_unsupported_win32_publication_has_stable_anchor_code(self) -> None:
        api = _assignable_api(FakeKernel32({"Rename": False}))
        api.error = receipt.ERROR_NOT_SUPPORTED
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        reader = mock.Mock(side_effect=FileNotFoundError())
        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-anchor-unavailable")
        self.assertIsInstance(raised.exception.__cause__, helper._DefiniteRenameError)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(binding.closed, 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_unsupported_stage_metadata_maps_before_publication_and_keeps_notes(self) -> None:
        native_error = OSError(receipt.ERROR_NOT_SUPPORTED, "unsupported staging metadata")
        native_error.add_note("native staging metadata note")
        api = _assignable_api(FakeKernel32({"GetInfo:0": native_error}))
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        reader = mock.Mock(side_effect=FileNotFoundError())
        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-anchor-unavailable")
        self.assertIs(raised.exception.__cause__, native_error)
        self.assertIn("native staging metadata note", getattr(raised.exception, "__notes__", ()))
        self.assertIsNone(helper.outcome_from_error(native_error))
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(binding.closed, 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertNotIn(receipt.FILE_RENAME_INFO, classes)
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_unsupported_error_after_rename_keeps_published_outcome_and_primary(self) -> None:
        native_error = OSError(receipt.ERROR_NOT_SUPPORTED, "unsupported post-rename read")
        native_error.add_note("native post-rename note")
        api = _assignable_api(FakeKernel32())
        api.read_failure_seek = (1, native_error)
        binding = _Binding(api)
        helper, reader = self._scripted_reader()
        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(OSError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertIs(raised.exception, native_error)
        outcome = helper.outcome_from_error(native_error)
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.state, "published")
        notes = "\n".join(getattr(native_error, "__notes__", ()))
        self.assertIn("native post-rename note", notes)
        self.assertIn("took effect", notes)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(binding.closed, 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_RENAME_INFO, classes)
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_unsupported_rename_exception_keeps_unknown_outcome_and_primary(self) -> None:
        native_error = OSError(receipt.ERROR_CALL_NOT_IMPLEMENTED, "uncertain rename result")
        api = _assignable_api(FakeKernel32({"Rename": native_error}))
        binding = _Binding(api)
        helper, reader = self._scripted_reader()
        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(OSError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertIs(raised.exception, native_error)
        outcome = helper.outcome_from_error(native_error)
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.state, "unknown")
        self.assertIn("took effect", "\n".join(getattr(native_error, "__notes__", ())))
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(binding.closed, 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_RENAME_INFO, classes)
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_generic_win32_publication_io_error_remains_native(self) -> None:
        api = _assignable_api(FakeKernel32({"Rename": False}))
        api.error = 1117
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        with (
            mock.patch.object(helper, "read_windows_receipt", side_effect=FileNotFoundError),
            self.assertRaises(helper._DefiniteRenameError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.errno, 1117)
        self.assertEqual(binding.closed, 1)

    def test_facade_configures_full_fixed_width_api_before_real_helper_use(self) -> None:
        api = FakeKernel32()
        binding, reader = self._publish(api)
        ctypes_api = cast(Any, api)

        self.assertEqual(ctypes_api.WriteFile.argtypes[0], ctypes.c_void_p)
        self.assertEqual(ctypes_api.WriteFile.argtypes[2], ctypes.c_uint32)
        self.assertEqual(ctypes_api.ReadFile.argtypes, ctypes_api.WriteFile.argtypes)
        self.assertEqual(ctypes_api.FlushFileBuffers.argtypes, (ctypes.c_void_p,))
        self.assertEqual(ctypes_api.SetFilePointerEx.argtypes[0], ctypes.c_void_p)
        self.assertEqual(ctypes_api.CloseHandle.argtypes, (ctypes.c_void_p,))
        self.assertEqual(binding.closed, 1)
        self.assertEqual(binding.verified, 7)
        self.assertEqual(reader.call_count, 2)

    def test_one_stage_collision_retries_real_helper_then_succeeds(self) -> None:
        api = _assignable_api(FakeKernel32())
        real_create: Any = api.NtCreateFile
        attempts = 0

        def collide_once(*args: object) -> int:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                api.error = receipt.ERROR_FILE_EXISTS
                return ctypes.c_int32(receipt.STATUS_OBJECT_NAME_COLLISION).value
            return real_create(*args)

        cast(Any, api).NtCreateFile = mock.Mock(side_effect=collide_once)
        binding = _Binding(api)
        helper, reader = self._scripted_reader()
        with mock.patch.object(helper, "read_windows_receipt", reader):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(attempts, 2)
        self.assertEqual(binding.closed, 1)
        self.assertEqual(reader.call_count, 2)

    def test_stage_collision_exhaustion_is_bounded_and_closes_binding(self) -> None:
        api = _assignable_api(FakeKernel32({"NtCreateFile": False}))
        api.error = receipt.ERROR_ALREADY_EXISTS
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()

        with (
            mock.patch.object(helper, "read_windows_receipt", side_effect=FileNotFoundError),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, "output-temporary-unavailable")
        self.assertEqual(cast(Any, api).NtCreateFile.call_count, 100)
        self.assertEqual(binding.closed, 1)

    def test_clean_definite_collision_observes_exact_winner_and_succeeds(self) -> None:
        api = _assignable_api(FakeKernel32({"Rename": False}))
        api.error = receipt.ERROR_FILE_EXISTS
        binding, reader = self._publish(api)

        self.assertEqual(binding.closed, 1)
        self.assertEqual(reader.call_count, 2)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)

    def _assert_collision_preserves_rejected_winner(self, code: str) -> None:
        original = b"pre-existing public winner"
        api = cast(_ExistingWinnerKernel32, _assignable_api(_ExistingWinnerKernel32(original)))
        binding = _Binding(api)
        helper = anchored._windows_receipt_module()
        validation = helper.WindowsReceiptValidationError(code, f"induced {code} winner")
        reader = mock.Mock(side_effect=(FileNotFoundError(), validation))

        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertEqual(raised.exception.code, code)
        self.assertEqual(bytes(api.public_data), original)
        self.assertFalse(api.rename_succeeded)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(binding.closed, 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_RENAME_INFO, classes)
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_definite_collision_preserves_different_existing_winner(self) -> None:
        self._assert_collision_preserves_rejected_winner("output-different")

    def test_definite_collision_preserves_noncanonical_existing_winner(self) -> None:
        self._assert_collision_preserves_rejected_winner("output-existing-invalid")

    def test_unknown_file_exists_after_native_call_is_observed_but_re_raised(self) -> None:
        unknown = FileExistsError("uncertain native return")
        api = _assignable_api(FakeKernel32({"Rename": unknown}))
        binding = _Binding(api)
        helper, reader = self._scripted_reader()

        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(FileExistsError) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertIs(raised.exception, unknown)
        self.assertEqual(binding.closed, 1)
        self.assertEqual(reader.call_count, 2)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)
        self.assertIn("took effect", "\n".join(getattr(unknown, "__notes__", ())))

    def test_publisher_cleanup_entry_interrupt_closes_child_before_parent_and_verifies_effect(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        helper, reader = self._scripted_reader()
        outer_lease = anchored._OutputParentBindingLease()
        outer_lease.binding = cast(anchored.OutputParentBinding, binding)
        interruption = KeyboardInterrupt("publisher cleanup entry")
        target_code = helper.publish_windows_receipt.__code__
        source, first_line = inspect.getsourcelines(helper.publish_windows_receipt)
        active_error_line = first_line + next(
            index for index, line in enumerate(source) if "active_error = sys.exception()" in line
        )
        triggered = False

        original_close = binding.close

        def close_parent() -> tuple[BaseException, ...]:
            self.assertEqual(
                [call for call in api.calls if call[0] == "CloseHandle"],
                [("CloseHandle", (api.handle,))],
            )
            return original_close()

        binding.close = close_parent

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target_code:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is target_code
                and frame.f_lineno == active_error_line
                and not triggered
                and getattr(frame.f_locals.get("publication_lease"), "phase", None) == "published"
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            with (
                mock.patch.object(helper, "read_windows_receipt", reader),
                self.assertRaises(KeyboardInterrupt) as caught,
            ):
                sys.settrace(trace)
                anchored._publish_windows_receipt_bytes(
                    binding.parent / binding.leaf,
                    PAYLOAD,
                    cast(anchored.OutputParentBinding, binding),
                    outer_lease,
                )
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(reader.call_count, 2)
        self.assertIn("took effect", "\n".join(getattr(interruption, "__notes__", ())))
        self.assertEqual(binding.closed, 1)
        self.assertEqual(outer_lease.close(), ())
        self.assertEqual(sum(name == "CloseHandle" for name, _args in api.calls), 1)

    def test_required_outer_owner_recovers_facade_cleanup_entry(self) -> None:
        api = _assignable_api(FakeKernel32())
        binding = _Binding(api)
        helper, reader = self._scripted_reader()
        outer_lease = self._owner(binding)
        interruption = KeyboardInterrupt("Windows facade cleanup entry")
        target_code = anchored._publish_windows_receipt_bytes.__code__
        source, first_line = inspect.getsourcelines(anchored._publish_windows_receipt_bytes)
        cleanup_line = first_line + next(
            index for index, line in enumerate(source) if "close_failures: tuple[BaseException, ...] = ()" in line
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target_code:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is target_code
                and frame.f_lineno == cleanup_line
                and not triggered
                and outer_lease.publication_resources
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            with (
                mock.patch.object(helper, "read_windows_receipt", reader),
                self.assertRaises(KeyboardInterrupt) as caught,
            ):
                sys.settrace(trace)
                anchored._publish_windows_receipt_bytes(
                    binding.parent / binding.leaf,
                    PAYLOAD,
                    cast(anchored.OutputParentBinding, binding),
                    outer_lease,
                )
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(binding.closed, 0)
        self.assertEqual(len(outer_lease.publication_resources), 1)
        publication_lease = cast(Any, outer_lease.publication_resources[0])
        outcome = publication_lease.outcome
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.state, "published")
        self.assertEqual(outer_lease.close(), ())
        self.assertEqual(binding.closed, 1)
        self.assertEqual(sum(name == "CloseHandle" for name, _args in api.calls), 1)

    def test_definite_collision_cannot_swallow_disposition_or_close_failure(self) -> None:
        cases: tuple[tuple[str, dict[str, BaseException | bool]], ...] = (
            ("disposition", {"Rename": False, "Disposition": False}),
            ("close", {"Rename": False, "CloseHandle": False}),
        )
        for label, failures in cases:
            with self.subTest(label=label):
                api = _assignable_api(FakeKernel32(failures))
                api.error = receipt.ERROR_FILE_EXISTS
                binding = _Binding(api)
                helper, reader = self._scripted_reader()
                with (
                    mock.patch.object(helper, "read_windows_receipt", reader),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored._publish_windows_receipt_bytes(
                        binding.parent / binding.leaf,
                        PAYLOAD,
                        cast(anchored.OutputParentBinding, binding),
                        self._owner(binding),
                    )

                self.assertEqual(raised.exception.code, "output-cleanup-retained")
                self.assertEqual(binding.closed, 0 if label == "close" else 1)
                self.assertEqual(reader.call_count, 2)
                notes = "\n".join(getattr(raised.exception, "__notes__", ()))
                self.assertIn("Could not", notes)

    def test_api_raised_collision_and_spoofed_cleanup_evidence_remain_unknown(self) -> None:
        helper = anchored._windows_receipt_module()
        spoof = helper._DefiniteRenameCollision(receipt.ERROR_FILE_EXISTS, "spoofed native exception")
        setattr(spoof, "_windows_receipt_cleanup_failures", (KeyboardInterrupt("spoof"),))
        setattr(spoof, "_windows_receipt_cleanup_record", (KeyboardInterrupt("spoof"),))
        api = _assignable_api(FakeKernel32({"Rename": spoof}))
        binding = _Binding(api)
        _, reader = self._scripted_reader()

        with (
            mock.patch.object(helper, "read_windows_receipt", reader),
            self.assertRaises(helper._DefiniteRenameCollision) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                binding.parent / binding.leaf,
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                self._owner(binding),
            )

        self.assertIs(raised.exception, spoof)
        outcome = helper.outcome_from_error(spoof)
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.state, "unknown")
        self.assertEqual(helper.cleanup_failures_from_error(spoof), ())
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(binding.closed, 1)


class WindowsRootedParentFacadeTests(unittest.TestCase):
    def test_binding_keeps_parent_handle_open_when_child_cleanup_is_retained(self) -> None:
        helper = anchored._windows_receipt_module()
        interruption = KeyboardInterrupt("child handle remains retained")

        for failure_mode in ("return", "raise"):
            with self.subTest(failure_mode=failure_mode):
                root = helper.WindowsHandleLease(0xA001)
                child = helper.WindowsHandleLease(0xA002)
                binding = anchored.OutputParentBinding(
                    checkout=Path("C:/"),
                    parent=Path("C:/parent"),
                    leaf="receipt.json",
                    strategy="windows-handle",
                    windows_api=object(),
                    windows_handle_leases=(root, child),
                )
                calls: list[int] = []
                child_may_close = False

                def close_handle(
                    _api: object,
                    lease: Any,
                    _primary: BaseException | None,
                    _context: str,
                ) -> BaseException | None:
                    calls.append(lease.handle)
                    if lease is child and not child_may_close:
                        if failure_mode == "raise":
                            raise interruption
                        return interruption
                    lease.handle = None
                    return None

                with mock.patch.object(
                    helper,
                    "close_windows_handle_lease",
                    side_effect=close_handle,
                ):
                    first_failures = binding.close()
                    self.assertIn(interruption, first_failures)
                    self.assertTrue(all(handle == 0xA002 for handle in calls))
                    self.assertEqual(root.handle, 0xA001)
                    self.assertEqual(child.handle, 0xA002)
                    self.assertFalse(binding.is_closed)

                    child_may_close = True
                    self.assertEqual(binding.close(), ())

                self.assertEqual(calls[-2:], [0xA002, 0xA001])
                self.assertIsNone(child.handle)
                self.assertIsNone(root.handle)
                self.assertTrue(binding.is_closed)

    def test_recorded_false_keeps_root_open_after_parent_close_reentry(self) -> None:
        kernel = _SequencedCloseKernelApi((False, False))
        root = receipt.WindowsHandleLease(0xD001)
        child = receipt.WindowsHandleLease(0xD002)
        binding = anchored.OutputParentBinding(
            checkout=Path("C:/"),
            parent=Path("C:/parent"),
            leaf="receipt.json",
            strategy="windows-handle",
            windows_api=kernel,
            windows_handle_leases=(root, child),
            receipt_parent_policy=True,
        )

        first_failures = binding.close()
        second_failures = binding.close()

        self.assertTrue(first_failures)
        self.assertTrue(second_failures)
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xD002, 0xD002],
        )
        self.assertEqual(child.handle, 0xD002)
        self.assertEqual(root.handle, 0xD001)
        self.assertFalse(binding.is_closed)

    def test_parent_lease_finalizer_obeys_close_result_lifo(self) -> None:
        cases = (
            ("child-retained", (False, False), [0xE002, 0xE002], False),
            ("retry-succeeds", (False, True, True), [0xE002, 0xE002, 0xE001], True),
        )
        for label, close_results, expected_handles, expected_closed in cases:
            with self.subTest(label=label):
                kernel = _SequencedCloseKernelApi(close_results)
                root = receipt.WindowsHandleLease(0xE001)
                child = receipt.WindowsHandleLease(0xE002)
                binding = anchored.OutputParentBinding(
                    checkout=Path("C:/"),
                    parent=Path("C:/parent"),
                    leaf="receipt.json",
                    strategy="windows-handle",
                    windows_api=kernel,
                    windows_handle_leases=(root, child),
                    receipt_parent_policy=True,
                )
                owner = anchored._OutputParentBindingLease(binding)

                del owner
                gc.collect()

                self.assertEqual(
                    [args[0] for name, args in kernel.calls if name == "CloseHandle"],
                    expected_handles,
                )
                self.assertEqual(binding.is_closed, expected_closed)
                if expected_closed:
                    self.assertIsNone(child.handle)
                    self.assertIsNone(root.handle)
                else:
                    self.assertEqual(child.handle, 0xE002)
                    self.assertEqual(root.handle, 0xE001)

    def test_parent_lease_finalizer_never_reenters_unobserved_child_close(
        self,
    ) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        root = receipt.WindowsHandleLease(0xF001)
        child = receipt.WindowsHandleLease(0xF002)
        binding = anchored.OutputParentBinding(
            checkout=Path("C:/"),
            parent=Path("C:/parent"),
            leaf="receipt.json",
            strategy="windows-handle",
            windows_api=kernel,
            windows_handle_leases=(root, child),
            receipt_parent_policy=True,
        )
        owner = anchored._OutputParentBindingLease(binding)
        interruption = KeyboardInterrupt("unobserved native child close")
        close_entries = 0

        def interrupt_without_observation(*_arguments: object) -> None:
            nonlocal close_entries
            close_entries += 1
            raise interruption

        helper = anchored._windows_receipt_module()
        with (
            mock.patch.object(
                helper,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                helper,
                "_record_close_handle_result",
                side_effect=interrupt_without_observation,
            ),
        ):
            del owner
            gc.collect()

        self.assertEqual(close_entries, 1)
        self.assertEqual(child.handle, 0xF002)
        self.assertEqual(root.handle, 0xF001)
        self.assertFalse(binding.is_closed)

    def test_cleanup_handler_interrupt_prearms_before_outer_finalizer(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = _SequencedNtApi(
            (0xF101, 0xF102),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        helper = anchored._windows_receipt_module()
        target = helper.close_windows_handle_lease
        source, first_line = inspect.getsourcelines(target)
        handler_line = first_line + next(
            index for index, line in enumerate(source) if line.strip() == "retain_failure(close_error)"
        )
        body_primary = SystemExit("parent verification primary")
        unobserved_error = RuntimeError("native CloseHandle result was not recorded")
        handler_interruption = KeyboardInterrupt("CloseHandle handler entry")
        captured_bindings: list[anchored.OutputParentBinding] = []
        native_entries: list[int] = []
        triggered = False

        def reject_binding(binding: anchored.OutputParentBinding) -> None:
            captured_bindings.append(binding)
            raise body_primary

        def interrupt_without_observation(
            _api: object,
            _lease: object,
            handle: int,
            _native_address: int | None,
        ) -> None:
            native_entries.append(handle)
            raise unobserved_error

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is target.__code__
                and frame.f_lineno == handler_line
                and not triggered
            ):
                triggered = True
                raise handler_interruption
            return trace

        owner = anchored._OutputParentBindingLease()
        finalizer = owner._finalizer
        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(
                anchored.OutputParentBinding,
                "verify",
                new=reject_binding,
            ),
            mock.patch.object(
                helper,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                helper,
                "_record_close_handle_result",
                side_effect=interrupt_without_observation,
            ),
        ):
            previous = sys.gettrace()
            try:
                sys.settrace(trace)
                with self.assertRaises(SystemExit) as raised:
                    anchored._open_rooted_windows_parent(
                        Path("C:\\"),
                        Path("C:\\") / "parent" / "receipt.json",
                        ("parent", "receipt.json"),
                        owner,
                    )
            finally:
                sys.settrace(previous)

            self.assertTrue(owner.close())

        self.assertTrue(triggered)
        self.assertIs(raised.exception, body_primary)
        self.assertEqual(len(captured_bindings), 1)
        binding = captured_bindings[0]
        root, child = binding.windows_handle_leases
        self.assertEqual(native_entries, [0xF102])
        self.assertEqual(root.handle, 0xF101)
        self.assertEqual(child.handle, 0xF102)
        self.assertTrue(child.close_retry_blocked)
        self.assertFalse(binding.is_closed)
        self.assertIn(
            str(handler_interruption),
            "\n".join(getattr(body_primary, "__notes__", ())),
        )

        body_primary.__traceback__ = None
        handler_interruption.__traceback__ = None
        unobserved_error.__traceback__ = None
        del owner
        gc.collect()

        self.assertFalse(finalizer.alive)
        self.assertEqual(native_entries, [0xF102])
        self.assertEqual(root.handle, 0xF101)
        self.assertEqual(child.handle, 0xF102)

    def _patch_parent_apis(
        self,
        kernel: FakeKernelApi,
        native: FakeNtApi,
    ) -> tuple[Any, ...]:
        helper = anchored._windows_receipt_module()

        def unchanged(api: Any) -> Any:
            return api

        return (
            mock.patch.object(anchored, "_windows_file_api", return_value=kernel),
            mock.patch.object(anchored, "_windows_receipt_module", return_value=helper),
            mock.patch.object(helper, "_select_apis", return_value=(kernel, native)),
            mock.patch.object(helper, "_configure_api", side_effect=unchanged),
            mock.patch.object(helper, "_configure_nt_api", side_effect=unchanged),
        )

    def test_binding_verification_io_failure_has_stable_parent_changed_code(self) -> None:
        missing = FileNotFoundError("bound Windows ancestor disappeared")
        binding = anchored.OutputParentBinding(
            checkout=Path("C:/"),
            parent=Path("C:/bound"),
            leaf="receipt.json",
            strategy="windows-handle",
            receipt_parent_policy=True,
            windows_api=FakeKernelApi(b"", directory=True),
            windows_entries=((Path("C:/bound"), (1, 2), 0x4567),),
        )
        with (
            mock.patch.object(Path, "lstat", side_effect=missing),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            binding.verify()
        self.assertEqual(raised.exception.code, "output-parent-changed")
        self.assertIs(raised.exception.__cause__, missing)

    def test_root_file_type_unsupported_preserves_stable_code_cause_and_notes(self) -> None:
        helper = anchored._windows_receipt_module()
        native_error = OSError(receipt.ERROR_NOT_SUPPORTED, "unsupported root file type")
        native_error.add_note("native root file type note")
        kernel = FakeKernelApi(b"", directory=True)
        kernel.failures["GetFileType"] = native_error
        native = FakeNtApi(information=receipt.FILE_OPENED)
        lease = anchored._OutputParentBindingLease()
        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._open_rooted_windows_parent(
                Path("C:\\"),
                Path("C:\\") / "receipt.json",
                ("receipt.json",),
                lease,
            )

        self.assertEqual(raised.exception.code, "output-anchor-unavailable")
        helper_error = raised.exception.__cause__
        assert helper_error is not None
        self.assertIsInstance(helper_error, helper.WindowsReceiptValidationError)
        self.assertIs(helper_error.__cause__, native_error)
        self.assertIn("native root file type note", getattr(helper_error, "__notes__", ()))
        self.assertIn("native root file type note", getattr(raised.exception, "__notes__", ()))
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [native.handle],
        )

    def test_root_file_type_generic_io_maps_parent_invalid_with_raw_cause(self) -> None:
        native_error = OSError(1117, "root device I/O failure")
        kernel = FakeKernelApi(b"", directory=True)
        kernel.failures["GetFileType"] = native_error
        native = FakeNtApi(information=receipt.FILE_OPENED)
        lease = anchored._OutputParentBindingLease()
        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._open_rooted_windows_parent(
                Path("C:\\"),
                Path("C:\\") / "receipt.json",
                ("receipt.json",),
                lease,
            )

        self.assertEqual(raised.exception.code, "output-parent-invalid")
        self.assertIs(raised.exception.__cause__, native_error)
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [native.handle],
        )

    def test_root_and_child_leases_transfer_and_binding_closes_in_reverse(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = _SequencedNtApi(
            (0xA101, 0xA102),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        lease = anchored._OutputParentBindingLease()
        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(anchored.OutputParentBinding, "verify"),
            mock.patch.object(anchored.Path, "lstat", side_effect=AssertionError("path stat used")),
            mock.patch.object(anchored.Path, "mkdir", side_effect=AssertionError("path mkdir used")),
            mock.patch.object(anchored.os, "open", side_effect=AssertionError("path open used")),
        ):
            binding = anchored._open_rooted_windows_parent(
                Path("C:\\"),
                Path("C:\\") / "parent" / "receipt.json",
                ("parent", "receipt.json"),
                lease,
            )

        self.assertIs(lease.binding, binding)
        self.assertEqual([entry[2] for entry in binding.windows_entries], [0xA101, 0xA102])
        self.assertEqual(
            [(call["root"], call["name"], call["share_access"], call["disposition"]) for call in native.calls],
            [
                (
                    None,
                    "\\??\\C:\\",
                    receipt.FILE_SHARE_READ | receipt.FILE_SHARE_WRITE,
                    receipt.FILE_OPEN,
                ),
                (
                    0xA101,
                    "parent",
                    receipt.FILE_SHARE_READ | receipt.FILE_SHARE_WRITE,
                    receipt.FILE_OPEN_IF,
                ),
            ],
        )
        self.assertEqual(lease.close(), ())
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xA102, 0xA101],
        )

    def test_binding_lease_survives_windows_opener_to_wrapper_return_gap(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = _SequencedNtApi(
            (0xA201, 0xA202),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        anchor = Path("C:\\")
        absolute = anchor / "parent" / "receipt.json"
        interruption = KeyboardInterrupt("Windows opener returned before wrapper return")
        real_open = anchored._open_rooted_windows_parent
        captured_binding: anchored.OutputParentBinding | None = None
        triggered = False

        def open_then_interrupt(
            root_anchor: Path,
            output_path: Path,
            parts: tuple[str, ...],
            binding_lease: anchored._OutputParentBindingLease,
        ) -> anchored.OutputParentBinding:
            nonlocal captured_binding, triggered
            captured_binding = real_open(root_anchor, output_path, parts, binding_lease)
            triggered = True
            raise interruption

        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(
                anchored,
                "_rooted_output_parts",
                return_value=(anchor, absolute, ("parent", "receipt.json")),
            ),
            mock.patch.object(
                anchored,
                "descriptor_relative_output_supported",
                return_value=False,
            ),
            mock.patch.object(anchored.os, "name", "nt"),
            mock.patch.object(anchored.OutputParentBinding, "verify"),
            mock.patch.object(
                anchored,
                "_open_rooted_windows_parent",
                side_effect=open_then_interrupt,
            ),
            mock.patch.object(anchored, "_publish_windows_receipt_bytes") as publish,
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored.publish_identical_receipt_bytes(absolute, PAYLOAD)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertIsNotNone(captured_binding)
        assert captured_binding is not None
        self.assertTrue(captured_binding._closed)
        publish.assert_not_called()
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xA202, 0xA201],
        )

    def test_binding_lease_survives_wrapper_to_public_assignment_gap(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = _SequencedNtApi(
            (0xA301, 0xA302),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        anchor = Path("C:\\")
        absolute = anchor / "parent" / "receipt.json"
        interruption = KeyboardInterrupt("wrapper returned before public binding assignment")
        real_open = anchored.open_rooted_output_parent
        captured_binding: anchored.OutputParentBinding | None = None
        triggered = False

        def open_then_interrupt(
            output_path: Path,
            binding_lease: anchored._OutputParentBindingLease,
        ) -> anchored.OutputParentBinding:
            nonlocal captured_binding, triggered
            captured_binding = real_open(output_path, binding_lease)
            triggered = True
            raise interruption

        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(
                anchored,
                "_rooted_output_parts",
                return_value=(anchor, absolute, ("parent", "receipt.json")),
            ),
            mock.patch.object(
                anchored,
                "descriptor_relative_output_supported",
                return_value=False,
            ),
            mock.patch.object(anchored.os, "name", "nt"),
            mock.patch.object(anchored.OutputParentBinding, "verify"),
            mock.patch.object(
                anchored,
                "open_rooted_output_parent",
                side_effect=open_then_interrupt,
            ),
            mock.patch.object(anchored, "_publish_windows_receipt_bytes") as publish,
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored.publish_identical_receipt_bytes(absolute, PAYLOAD)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertIsNotNone(captured_binding)
        assert captured_binding is not None
        self.assertTrue(captured_binding._closed)
        publish.assert_not_called()
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xA302, 0xA301],
        )

    def test_helper_return_interrupt_closes_pending_then_retained_handles_once(self) -> None:
        helper = anchored._windows_receipt_module()
        cases: tuple[
            tuple[str, tuple[int, ...], tuple[int, ...], tuple[int, ...]],
            ...,
        ] = (
            ("root", (0xB101,), (receipt.FILE_OPENED,), (0xB101,)),
            (
                "child",
                (0xB201, 0xB202),
                (receipt.FILE_OPENED, receipt.FILE_CREATED),
                (0xB202, 0xB201),
            ),
        )
        for label, handles, information, expected_closes in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi(b"", directory=True)
                native = _SequencedNtApi(handles, information)
                lease = anchored._OutputParentBindingLease()
                interruption = KeyboardInterrupt(f"{label} helper returned before facade assignment")
                helper_name = "open_windows_directory_anchor" if label == "root" else "open_or_create_windows_directory"
                real_helper: Any = getattr(helper, helper_name)
                triggered = False

                def helper_then_interrupt(*arguments: Any, **keywords: Any) -> Any:
                    nonlocal triggered
                    result = real_helper(*arguments, **keywords)
                    if not triggered:
                        triggered = True
                        raise interruption
                    return result

                patches = self._patch_parent_apis(kernel, native)
                with (
                    patches[0],
                    patches[1],
                    patches[2],
                    patches[3],
                    patches[4],
                    mock.patch.object(
                        helper,
                        helper_name,
                        side_effect=helper_then_interrupt,
                    ),
                    mock.patch.object(anchored.OutputParentBinding, "verify"),
                    self.assertRaises(KeyboardInterrupt) as raised,
                ):
                    anchored._open_rooted_windows_parent(
                        Path("C:\\"),
                        Path("C:\\") / "parent" / "receipt.json",
                        ("parent", "receipt.json"),
                        lease,
                    )

                self.assertTrue(triggered)
                self.assertIs(raised.exception, interruption)
                self.assertEqual(
                    [args[0] for name, args in kernel.calls if name == "CloseHandle"],
                    list(expected_closes),
                )

    def test_preinstalled_owner_recovers_root_child_and_verification_interrupts(self) -> None:
        target = anchored._open_rooted_windows_parent
        source, first_line = inspect.getsourcelines(target)
        cleanup_lines = [
            first_line + index
            for index, line in enumerate(source)
            if "cleanup_failures = lease.close()" in line
        ]
        self.assertEqual(len(cleanup_lines), 1)
        cleanup_line = cleanup_lines[0]

        cases = (
            ("root", (0xBA01,), (receipt.FILE_OPENED,)),
            (
                "child",
                (0xBB01, 0xBB02),
                (receipt.FILE_OPENED, receipt.FILE_CREATED),
            ),
            (
                "verify",
                (0xBC01, 0xBC02),
                (receipt.FILE_OPENED, receipt.FILE_CREATED),
            ),
        )
        for seam, handles, information in cases:
            with self.subTest(seam=seam):
                kernel = FakeKernelApi(b"", directory=True)
                native = _SequencedNtApi(handles, information)
                helper = anchored._windows_receipt_module()
                real_root_open = helper.open_windows_directory_anchor
                real_child_open = helper.open_or_create_windows_directory
                body_failure = RuntimeError(f"modeled {seam} acquisition failure")
                cleanup_interruption = KeyboardInterrupt(
                    f"interrupt {seam} exception-handler cleanup entry"
                )
                cleanup_was_interrupted = False

                def root_then_maybe_fail(*arguments: Any, **keywords: Any) -> Any:
                    result = real_root_open(*arguments, **keywords)
                    if seam == "root":
                        raise body_failure
                    return result

                def child_then_maybe_fail(*arguments: Any, **keywords: Any) -> Any:
                    result = real_child_open(*arguments, **keywords)
                    if seam == "child":
                        raise body_failure
                    return result

                def verify_then_maybe_fail(_binding: anchored.OutputParentBinding) -> None:
                    if seam == "verify":
                        raise body_failure

                def trace(frame: FrameType, event: str, _argument: object) -> Any:
                    nonlocal cleanup_was_interrupted
                    if event == "call" and frame.f_code is target.__code__:
                        frame.f_trace = trace
                        return trace
                    if (
                        event == "line"
                        and frame.f_code is target.__code__
                        and frame.f_lineno == cleanup_line
                        and not cleanup_was_interrupted
                    ):
                        cleanup_was_interrupted = True
                        raise cleanup_interruption
                    return trace

                def acquire_without_retaining_lease() -> None:
                    lease = anchored._OutputParentBindingLease()
                    target(
                        Path("C:\\"),
                        Path("C:\\") / "parent" / "receipt.json",
                        ("parent", "receipt.json"),
                        lease,
                    )

                patches = self._patch_parent_apis(kernel, native)
                previous_trace = sys.gettrace()
                try:
                    with (
                        patches[0],
                        patches[1],
                        patches[2],
                        patches[3],
                        patches[4],
                        mock.patch.object(
                            helper,
                            "open_windows_directory_anchor",
                            side_effect=root_then_maybe_fail,
                        ),
                        mock.patch.object(
                            helper,
                            "open_or_create_windows_directory",
                            side_effect=child_then_maybe_fail,
                        ),
                        mock.patch.object(
                            anchored.OutputParentBinding,
                            "verify",
                            new=verify_then_maybe_fail,
                        ),
                        self.assertRaises(anchored.AnchoredOutputError) as raised,
                    ):
                        sys.settrace(trace)
                        acquire_without_retaining_lease()
                finally:
                    sys.settrace(previous_trace)

                self.assertTrue(cleanup_was_interrupted)
                self.assertEqual(raised.exception.code, "output-parent-invalid")
                self.assertIs(raised.exception.__cause__, body_failure)
                self.assertIn(
                    str(cleanup_interruption),
                    "\n".join(getattr(raised.exception, "__notes__", ())),
                )
                raised.exception.__traceback__ = None
                body_failure.__traceback__ = None
                cleanup_interruption.__traceback__ = None
                gc.collect()

                close_handles = [
                    args[0]
                    for name, args in kernel.calls
                    if name == "CloseHandle"
                ]
                self.assertEqual(close_handles, list(reversed(handles)))
                self.assertEqual(len(close_handles), len(set(close_handles)))

    def test_final_binding_verification_failure_preserves_primary_and_reverses_close(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        kernel.failures["CloseHandle"] = False
        native = _SequencedNtApi(
            (0xC101, 0xC102),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        primary = KeyboardInterrupt("final binding verification")
        lease = anchored._OutputParentBindingLease()
        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(anchored.OutputParentBinding, "verify", side_effect=primary),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._open_rooted_windows_parent(
                Path("C:\\"),
                Path("C:\\") / "parent" / "receipt.json",
                ("parent", "receipt.json"),
                lease,
            )

        self.assertIs(raised.exception, primary)
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xC102, 0xC102],
        )
        self.assertGreaterEqual(
            "\n".join(getattr(primary, "__notes__", ())).count(
                "Could not close a receipt output directory handle"
            ),
            1,
        )

    def test_returned_child_handle_mismatch_closes_pending_then_root(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = _SequencedNtApi(
            (0xD101, 0xD102),
            (receipt.FILE_OPENED, receipt.FILE_CREATED),
        )
        helper = anchored._windows_receipt_module()
        lease = anchored._OutputParentBindingLease()
        real_child_open = helper.open_or_create_windows_directory

        def return_mismatch(*args: Any, **kwargs: Any) -> Any:
            result = real_child_open(*args, **kwargs)
            return helper.WindowsDirectoryResult(
                result.handle + 1,
                result.volume_serial_number,
                result.file_id,
                result.created,
            )

        patches = self._patch_parent_apis(kernel, native)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            mock.patch.object(helper, "open_or_create_windows_directory", side_effect=return_mismatch),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._open_rooted_windows_parent(
                Path("C:\\"),
                Path("C:\\") / "parent" / "receipt.json",
                ("parent", "receipt.json"),
                lease,
            )

        self.assertEqual(raised.exception.code, "output-parent-invalid")
        self.assertEqual(
            [args[0] for name, args in kernel.calls if name == "CloseHandle"],
            [0xD102, 0xD101],
        )


if __name__ == "__main__":
    unittest.main()
