# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import inspect
from pathlib import Path
import sys
import unittest
from unittest import mock
from typing import Any, Callable, cast

from scripts import _anchored_receipt_windows as receipt
from tests.test_anchored_receipt_windows import FakeKernel32


PAYLOAD = b'{"status":"verified"}\n'

INVALID_WINDOWS_RELATIVE_LEAVES = (
    "",
    ".",
    "..",
    "receipt.",
    "receipt ",
    "CON",
    "PrN.txt",
    "aUx.backup.tar",
    "NUL.txt",
    "NUL .txt",
    *(f"CoM{index}.txt" for index in range(1, 10)),
    *(f"lPt{index}.backup" for index in range(1, 10)),
    "COM¹",
    "com².txt",
    "CoM³.backup",
    "LPT¹",
    "lpt².txt",
    "LpT³.backup",
    "a?b",
    "a<b",
    "a>b",
    'a"b',
    "a|b",
    "a*b",
    "a:b",
    "a/b",
    r"a\b",
    "a\x00b",
    "a\x01b",
    "a\x1fb",
    "\ud800",
)

VALID_WINDOWS_RELATIVE_LEAVES = (
    "COM0",
    "com10.txt",
    "LPT0",
    "lpt10.backup",
    "CONSOLE",
    "AUXiliary.txt",
    "NULl.txt",
    "COM¹x.txt",
    "NUL\N{NO-BREAK SPACE}.txt",
    "receipt\N{NO-BREAK SPACE}",
    "receipt\N{ONE DOT LEADER}",
    "ＣＯＮ.txt",
    "receipt-ž-文件-\N{GRINNING FACE}.json",
    f"{'long-' * 60}.json",
)


def _interrupt_relative_handle_handler(
    action: Callable[[], object],
    interruption: BaseException,
) -> BaseException:
    """Interrupt recovery after NtCreateFile has populated its output handle."""

    source, first_line = inspect.getsourcelines(receipt._relative_handle)
    handler_line = first_line + next(
        index for index, line in enumerate(source) if line.strip() == "if primary is not None:"
    )
    triggered = False
    observed: BaseException | None = None

    def trace(frame: Any, event: str, _argument: object) -> Any:
        nonlocal triggered
        if (
            event == "line"
            and frame.f_code is receipt._relative_handle.__code__
            and frame.f_lineno == handler_line
            and not triggered
        ):
            triggered = True
            raise interruption
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        try:
            action()
        except BaseException as error:
            observed = error
    finally:
        sys.settrace(previous)
    if not triggered:
        raise AssertionError("The relative-handle recovery boundary was not reached.")
    if observed is None:
        raise AssertionError("The relative-handle recovery interruption did not escape.")
    return observed


class FakeNtApi:
    def __init__(
        self,
        *,
        information: int,
        status: int = 0,
        completion_status: int = 0,
        handle: int = 0xA123,
    ) -> None:
        self.information = information
        self.status = ctypes.c_int32(status).value
        self.completion_status = ctypes.c_int32(completion_status).value
        self.handle = handle
        self.calls: list[dict[str, object]] = []
        self.conversions: list[int] = []
        self.raise_create: BaseException | None = None
        self.raise_after_acquire: BaseException | None = None
        self.raise_convert: BaseException | None = None
        self.error_codes: dict[int, int] = {
            0xC000000F: receipt.ERROR_FILE_NOT_FOUND,
            0xC0000022: 5,
            0xC0000034: receipt.ERROR_FILE_NOT_FOUND,
            0xC0000035: receipt.ERROR_FILE_EXISTS,
            0xC000003A: receipt.ERROR_PATH_NOT_FOUND,
        }

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
        attributes = ctypes.cast(object_attributes, ctypes.POINTER(receipt._ObjectAttributes)).contents
        name = attributes.ObjectName.contents
        encoded = ctypes.string_at(name.Buffer, name.Length)
        terminator = ctypes.string_at(name.Buffer + name.Length, ctypes.sizeof(receipt.WCHAR))
        self.calls.append(
            {
                "desired_access": desired_access,
                "root": attributes.RootDirectory,
                "name": encoded.decode("utf-16-le"),
                "name_length": name.Length,
                "name_maximum": name.MaximumLength,
                "terminator": terminator,
                "object_length": attributes.Length,
                "object_flags": attributes.Attributes,
                "security": attributes.SecurityDescriptor,
                "quality": attributes.SecurityQualityOfService,
                "allocation": allocation_size,
                "file_attributes": file_attributes,
                "share_access": share_access,
                "disposition": disposition,
                "options": options,
                "ea_buffer": ea_buffer,
                "ea_length": ea_length,
            }
        )
        if self.raise_create is not None:
            raise self.raise_create
        if receipt._nt_success(self.status):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.handle
            completion = ctypes.cast(io_status, ctypes.POINTER(receipt._IoStatusBlock)).contents
            completion.Status = self.completion_status
            completion.Information = self.information
            if self.raise_after_acquire is not None:
                raise self.raise_after_acquire
        return self.status

    def RtlNtStatusToDosError(self, status: int) -> int:
        if self.raise_convert is not None:
            raise self.raise_convert
        bits = ctypes.c_uint32(status).value
        self.conversions.append(bits)
        return self.error_codes.get(bits, 317)


class FakeKernelApi:
    def __init__(self, data: bytes = PAYLOAD, *, directory: bool = False) -> None:
        self.data = data
        self.position = 0
        self.handle = 0xA123
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.failures: dict[str, BaseException | bool] = {}
        self.error = 5
        self._last_error = 0
        self.file_type = receipt.FILE_TYPE_DISK
        self.identity = bytes(range(16))
        self.volume = 91
        self.attributes = receipt.FILE_ATTRIBUTE_DIRECTORY if directory else receipt.FILE_ATTRIBUTE_NORMAL
        self.directory = int(directory)
        self.delete_pending = 0
        self.links = 1
        self.metadata_pass = 0
        self.metadata_overrides: list[dict[str, object]] = [{}, {}]
        self.excessive_read_count = False

    def get_last_error(self) -> int:
        return self._last_error

    def set_last_error(self, value: int) -> None:
        self._last_error = value

    def _action(self, name: str) -> bool:
        action = self.failures.get(name)
        if isinstance(action, BaseException):
            raise action
        if action is False:
            self._last_error = self.error
        return action is not False

    def SetFilePointerEx(self, handle: int, offset: int, _new: object, method: int) -> bool:
        self.calls.append(("SetFilePointerEx", (handle, offset, method)))
        if not self._action("SetFilePointerEx"):
            return False
        self.position = offset
        return True

    def ReadFile(self, handle: int, buffer: Any, size: int, read: Any, _overlap: object) -> bool:
        self.calls.append(("ReadFile", (handle, size)))
        if not self._action("ReadFile"):
            return False
        chunk = self.data[self.position : self.position + size]
        if chunk:
            ctypes.memmove(buffer, chunk, len(chunk))
        self.position += len(chunk)
        reported = size + 1 if self.excessive_read_count else len(chunk)
        ctypes.cast(read, ctypes.POINTER(receipt.DWORD)).contents.value = reported
        return True

    def GetFileType(self, handle: int) -> int:
        self.calls.append(("GetFileType", (handle,)))
        if not self._action("GetFileType"):
            return 0
        return self.file_type

    def GetFileInformationByHandleEx(self, handle: int, info_class: int, pointer: Any, size: int) -> bool:
        self.calls.append(("GetFileInformationByHandleEx", (handle, info_class, size)))
        if not self._action(f"GetInfo:{info_class}"):
            return False
        override = self.metadata_overrides[min(self.metadata_pass, len(self.metadata_overrides) - 1)]
        if info_class == receipt.FILE_BASIC_INFO:
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileBasicInfo)).contents
            value.FileAttributes = cast(int, override.get("attributes", self.attributes))
        elif info_class == receipt.FILE_STANDARD_INFO:
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileStandardInfo)).contents
            value.EndOfFile = cast(int, override.get("size", len(self.data)))
            value.NumberOfLinks = cast(int, override.get("links", self.links))
            value.DeletePending = cast(int, override.get("delete_pending", self.delete_pending))
            value.Directory = cast(int, override.get("directory", self.directory))
        elif info_class == receipt.FILE_ID_INFO:
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileIdInfo)).contents
            value.VolumeSerialNumber = cast(int, override.get("volume", self.volume))
            identity = cast(bytes, override.get("identity", self.identity))
            for index, byte in enumerate(identity):
                value.FileId.Identifier[index] = byte
            self.metadata_pass += 1
        else:
            raise AssertionError(f"Unexpected info class: {info_class}")
        return True

    def CloseHandle(self, handle: int) -> bool:
        self.calls.append(("CloseHandle", (handle,)))
        return self._action("CloseHandle")


class _SequencedCloseKernelApi(FakeKernelApi):
    def __init__(self, close_results: tuple[bool, ...]) -> None:
        super().__init__()
        self.close_results = list(close_results)

    def CloseHandle(self, handle: int) -> bool:
        self.calls.append(("CloseHandle", (handle,)))
        if not self.close_results:
            raise AssertionError("Unexpected extra CloseHandle call")
        result = self.close_results.pop(0)
        if not result:
            self._last_error = self.error
        return result


class WindowsNtAbiTests(unittest.TestCase):
    def test_fixed_width_native_layout_matches_current_pointer_abi(self) -> None:
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        expected = {
            4: {
                "unicode": 8,
                "unicode_buffer": 4,
                "object": 24,
                "object_root": 4,
                "object_name": 8,
                "object_flags": 12,
                "io": 8,
                "io_information": 4,
            },
            8: {
                "unicode": 16,
                "unicode_buffer": 8,
                "object": 48,
                "object_root": 8,
                "object_name": 16,
                "object_flags": 24,
                "io": 16,
                "io_information": 8,
            },
        }[pointer_size]
        self.assertEqual(ctypes.sizeof(receipt.USHORT), 2)
        self.assertEqual(ctypes.sizeof(receipt.ULONG), 4)
        self.assertEqual(ctypes.sizeof(receipt.NTSTATUS), 4)
        self.assertEqual(ctypes.sizeof(receipt._UnicodeString), expected["unicode"])
        self.assertEqual(receipt._UnicodeString.Buffer.offset, expected["unicode_buffer"])
        self.assertEqual(ctypes.sizeof(receipt._ObjectAttributes), expected["object"])
        self.assertEqual(receipt._ObjectAttributes.RootDirectory.offset, expected["object_root"])
        self.assertEqual(receipt._ObjectAttributes.ObjectName.offset, expected["object_name"])
        self.assertEqual(receipt._ObjectAttributes.Attributes.offset, expected["object_flags"])
        self.assertEqual(ctypes.sizeof(receipt._IoStatusBlock), expected["io"])
        self.assertEqual(receipt._IoStatusBlock.Information.offset, expected["io_information"])

    def test_native_declarations_use_pointer_safe_exact_types(self) -> None:
        class Function:
            argtypes: object = None
            restype: object = None

            def __call__(self, *_args: object) -> int:
                return 0

        api = type("Api", (), {"NtCreateFile": Function(), "RtlNtStatusToDosError": Function()})()
        configured: Any = receipt._configure_nt_api(api)
        args = configured.NtCreateFile.argtypes
        self.assertIs(args[0]._type_, ctypes.c_void_p)
        self.assertIs(args[1], receipt.ULONG)
        self.assertIs(args[2]._type_, receipt._ObjectAttributes)
        self.assertIs(args[3]._type_, receipt._IoStatusBlock)
        self.assertIs(args[4]._type_, ctypes.c_int64)
        self.assertEqual(args[5:9], (receipt.ULONG,) * 4)
        self.assertIs(args[9], ctypes.c_void_p)
        self.assertIs(args[10], receipt.ULONG)
        self.assertIs(configured.NtCreateFile.restype, receipt.NTSTATUS)
        self.assertEqual(configured.RtlNtStatusToDosError.argtypes, (receipt.NTSTATUS,))
        self.assertIs(configured.RtlNtStatusToDosError.restype, receipt.ULONG)

    def test_nt_success_uses_signed_32_bit_semantics(self) -> None:
        self.assertTrue(receipt._nt_success(0))
        self.assertTrue(receipt._nt_success(0x40000000))
        self.assertFalse(receipt._nt_success(0x80000005))
        self.assertFalse(receipt._nt_success(0xC0000034))

    def test_relative_native_open_requires_a_retained_parent(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)
        with self.assertRaisesRegex(ValueError, "retained parent"):
            receipt._relative_handle(
                kernel,
                native,
                None,
                "receipt.json",
                receipt.WindowsHandleLease(),
                desired_access=receipt._TARGET_READ_ACCESS,
                share_access=receipt.FILE_SHARE_READ,
                disposition=receipt.FILE_OPEN,
                options=receipt._FILE_OPEN_OPTIONS,
                expected_information=(receipt.FILE_OPENED,),
                operation="open receipt",
            )
        self.assertEqual(native.calls, [])
        self.assertEqual(kernel.calls, [])


class WindowsHandleLeaseTests(unittest.TestCase):
    def test_recorded_false_retries_once_then_success_retires_handle(self) -> None:
        kernel = _SequencedCloseKernelApi((False, True))
        lease = receipt.WindowsHandleLease(kernel.handle)

        close_error = receipt.close_windows_handle_lease(
            kernel,
            lease,
            None,
            "test handle",
        )

        self.assertIsInstance(close_error, OSError)
        self.assertIsNone(lease.handle)
        self.assertIs(lease.close_result, receipt._WINDOWS_CLOSE_RESULT_PENDING)
        self.assertEqual(
            kernel.calls,
            [
                ("CloseHandle", (kernel.handle,)),
                ("CloseHandle", (kernel.handle,)),
            ],
        )

    def test_repeated_recorded_false_exhausts_retry_and_retains_handle(self) -> None:
        kernel = _SequencedCloseKernelApi((False, False))
        lease = receipt.WindowsHandleLease(kernel.handle)

        close_error = receipt.close_windows_handle_lease(
            kernel,
            lease,
            None,
            "test handle",
        )

        self.assertIsInstance(close_error, OSError)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertEqual(lease.close_result, 0)
        self.assertEqual(len(lease.recorded_close_results), 2)
        self.assertEqual(len(kernel.calls), 2)

        # Retry exhaustion persists across nested callers and finalizer entry.
        repeated_error = receipt.close_windows_handle_lease(
            kernel,
            lease,
            None,
            "test handle",
        )
        self.assertIsInstance(repeated_error, OSError)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertEqual(len(kernel.calls), 2)

    def test_recorded_false_preserves_primary_base_exception(self) -> None:
        kernel = _SequencedCloseKernelApi((False, False))
        lease = receipt.WindowsHandleLease(kernel.handle)
        primary = KeyboardInterrupt("body primary")

        result = receipt.close_windows_handle_lease(
            kernel,
            lease,
            primary,
            "test handle",
        )

        self.assertIs(result, primary)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertEqual(len(kernel.calls), 2)
        self.assertGreaterEqual(
            "\n".join(getattr(primary, "__notes__", ())).count("CloseHandle"),
            2,
        )

    def test_native_true_return_interruption_never_replays_close(self) -> None:
        kernel = FakeKernelApi()
        lease = receipt.WindowsHandleLease(kernel.handle)
        interruption = KeyboardInterrupt("native CloseHandle returned TRUE")
        native_calls: list[int] = []

        def prototype_factory(
            result_type: type[ctypes.c_int],
            *_argument_types: object,
            **_options: object,
        ) -> Callable[[int], Callable[[int], int]]:
            def bind(_address: int) -> Callable[[int], int]:
                def close(handle: int) -> int:
                    native_calls.append(handle)
                    checker = getattr(result_type, "_check_retval_")
                    checker(result_type(1))
                    raise interruption

                return close

            return bind

        with (
            mock.patch.object(
                receipt,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                receipt.ctypes,
                "WINFUNCTYPE",
                new=prototype_factory,
                create=True,
            ),
            mock.patch.object(
                receipt.ctypes,
                "get_last_error",
                return_value=0,
                create=True,
            ),
        ):
            result = receipt.close_windows_handle_lease(
                kernel,
                lease,
                None,
                "test handle",
            )

        self.assertIs(result, interruption)
        self.assertIsNone(lease.handle)
        self.assertIs(lease.close_result, receipt._WINDOWS_CLOSE_RESULT_PENDING)
        self.assertEqual(native_calls, [kernel.handle])

    def test_unobserved_native_call_blocks_all_reentry(self) -> None:
        kernel = FakeKernelApi()
        lease = receipt.WindowsHandleLease(kernel.handle)
        interruption = KeyboardInterrupt("native CloseHandle result was not recorded")
        calls = 0

        def interrupt_without_observation(*_arguments: object) -> None:
            nonlocal calls
            calls += 1
            raise interruption

        with (
            mock.patch.object(
                receipt,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                receipt,
                "_record_close_handle_result",
                side_effect=interrupt_without_observation,
            ),
        ):
            first_result = receipt.close_windows_handle_lease(
                kernel,
                lease,
                None,
                "test handle",
            )
            second_result = receipt.close_windows_handle_lease(
                kernel,
                lease,
                None,
                "test handle",
            )

        self.assertIs(first_result, interruption)
        self.assertIsNone(second_result)
        self.assertEqual(calls, 1)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertTrue(lease.close_retry_blocked)

    def test_unobserved_native_call_handler_interrupt_stays_prearmed(self) -> None:
        kernel = FakeKernelApi()
        lease = receipt.WindowsHandleLease(kernel.handle)
        body_primary = SystemExit("body primary")
        unobserved_error = RuntimeError("native CloseHandle result was not recorded")
        handler_interruption = KeyboardInterrupt("CloseHandle handler entry")
        native_entries = 0
        target = receipt.close_windows_handle_lease
        source, first_line = inspect.getsourcelines(target)
        handler_line = first_line + next(
            index for index, line in enumerate(source) if line.strip() == "retain_failure(close_error)"
        )
        triggered = False

        def interrupt_without_observation(*_arguments: object) -> None:
            nonlocal native_entries
            native_entries += 1
            raise unobserved_error

        def trace(frame: Any, event: str, _argument: object) -> Any:
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

        with (
            mock.patch.object(
                receipt,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                receipt,
                "_record_close_handle_result",
                side_effect=interrupt_without_observation,
            ),
        ):
            previous = sys.gettrace()
            try:
                sys.settrace(trace)
                with self.assertRaises(KeyboardInterrupt) as raised:
                    target(kernel, lease, body_primary, "test handle")
            finally:
                sys.settrace(previous)

            repeated_result = target(kernel, lease, body_primary, "test handle")

        self.assertTrue(triggered)
        self.assertIs(raised.exception, handler_interruption)
        self.assertIs(repeated_result, body_primary)
        self.assertEqual(native_entries, 1)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertEqual(lease.recorded_close_results, [])
        self.assertTrue(lease.close_retry_blocked)

    def test_observed_false_before_prearm_clear_uses_only_safe_retry(self) -> None:
        target = receipt.close_windows_handle_lease
        source, first_line = inspect.getsourcelines(target)
        clear_line = first_line + next(
            index
            for index, line in enumerate(source)
            if line.strip() == "lease.close_retry_blocked = False"
        )
        cases = (
            ("retry-succeeds", (0, 1), False),
            ("retry-fails", (0, 0), True),
        )
        for label, close_results, expected_live in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi()
                lease = receipt.WindowsHandleLease(kernel.handle)
                body_primary = SystemExit("body primary")
                interruption = KeyboardInterrupt("after definitive CloseHandle FALSE")
                statuses = iter(close_results)
                native_entries: list[int] = []
                triggered = False

                def record_result(
                    _api: object,
                    active_lease: receipt.WindowsHandleLease,
                    handle: int,
                    _native_address: int | None,
                ) -> None:
                    native_entries.append(handle)
                    status = next(statuses)
                    active_lease.recorded_close_results.append(
                        receipt._WindowsCloseObservation(status, 123 if not status else 0)
                    )

                def trace(frame: Any, event: str, _argument: object) -> Any:
                    nonlocal triggered
                    if event == "call" and frame.f_code is target.__code__:
                        frame.f_trace = trace
                        return trace
                    if (
                        event == "line"
                        and frame.f_code is target.__code__
                        and frame.f_lineno == clear_line
                        and not triggered
                    ):
                        triggered = True
                        raise interruption
                    return trace

                with (
                    mock.patch.object(
                        receipt,
                        "_native_close_handle_address",
                        return_value=0x123456,
                    ),
                    mock.patch.object(
                        receipt,
                        "_record_close_handle_result",
                        side_effect=record_result,
                    ),
                ):
                    previous = sys.gettrace()
                    try:
                        sys.settrace(trace)
                        with self.assertRaises(KeyboardInterrupt) as raised:
                            target(kernel, lease, None, "test handle")
                    finally:
                        sys.settrace(previous)

                    repeated_result = target(kernel, lease, body_primary, "test handle")
                    final_result = target(kernel, lease, body_primary, "test handle")

                self.assertTrue(triggered)
                self.assertIs(raised.exception, interruption)
                self.assertIs(repeated_result, body_primary)
                self.assertIs(final_result, body_primary)
                self.assertEqual(native_entries, [kernel.handle, kernel.handle])
                self.assertEqual(lease.handle is not None, expected_live)
                self.assertIn("CloseHandle", "\n".join(getattr(body_primary, "__notes__", ())))
                if expected_live:
                    self.assertEqual(len(lease.recorded_close_results), 2)
                else:
                    self.assertEqual(lease.recorded_close_results, [])

    def test_native_false_captures_last_error_before_successful_retry(self) -> None:
        kernel = FakeKernelApi()
        lease = receipt.WindowsHandleLease(kernel.handle)
        statuses = iter((0, 1))
        native_calls: list[int] = []

        def prototype_factory(
            result_type: type[ctypes.c_int],
            *_argument_types: object,
            **_options: object,
        ) -> Callable[[int], Callable[[int], int]]:
            def bind(_address: int) -> Callable[[int], int]:
                def close(handle: int) -> int:
                    native_calls.append(handle)
                    status = next(statuses)
                    checker = getattr(result_type, "_check_retval_")
                    checker(result_type(status))
                    return status

                return close

            return bind

        with (
            mock.patch.object(
                receipt,
                "_native_close_handle_address",
                return_value=0x123456,
            ),
            mock.patch.object(
                receipt.ctypes,
                "WINFUNCTYPE",
                new=prototype_factory,
                create=True,
            ),
            mock.patch.object(
                receipt.ctypes,
                "get_last_error",
                side_effect=(123, 0),
                create=True,
            ),
        ):
            result = receipt.close_windows_handle_lease(
                kernel,
                lease,
                None,
                "test handle",
            )

        self.assertIsInstance(result, OSError)
        assert isinstance(result, OSError)
        self.assertEqual(result.errno, 123)
        self.assertIsNone(lease.handle)
        self.assertEqual(native_calls, [kernel.handle, kernel.handle])

    def test_publication_close_stops_before_older_handles_on_false_exhaustion(
        self,
    ) -> None:
        kernel = _SequencedCloseKernelApi((False, False))
        publication = receipt._WindowsReceiptPublicationLease(kernel)
        publication.stage.handle = 0xA100
        older_child = publication.new_transient_handle()
        older_child.handle = 0xA200
        newest_child = publication.new_transient_handle()
        newest_child.handle = 0xA300

        failures = publication.close()

        self.assertTrue(failures)
        self.assertEqual(
            kernel.calls,
            [
                ("CloseHandle", (0xA300,)),
                ("CloseHandle", (0xA300,)),
            ],
        )
        self.assertEqual(newest_child.handle, 0xA300)
        self.assertEqual(older_child.handle, 0xA200)
        self.assertEqual(publication.stage.handle, 0xA100)
        self.assertFalse(publication.is_closed)
        self.assertEqual(publication.close(), ())
        self.assertEqual(len(kernel.calls), 2)

    def test_close_address_resolution_interrupt_is_bounded_and_does_not_skip_close(self) -> None:
        kernel = FakeKernelApi()
        lease = receipt.WindowsHandleLease(kernel.handle)
        interruption = KeyboardInterrupt("resolve CloseHandle")
        original = receipt._native_close_handle_address
        attempts = 0

        def interrupted_once(_api: object) -> int | None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise interruption
            return None

        receipt._native_close_handle_address = interrupted_once
        try:
            primary = receipt.close_windows_handle_lease(kernel, lease, None, "test handle")
        finally:
            receipt._native_close_handle_address = original

        self.assertIs(primary, interruption)
        self.assertEqual(attempts, 2)
        self.assertIsNone(lease.handle)
        self.assertEqual(kernel.calls, [("CloseHandle", (kernel.handle,))])

    def test_close_result_extraction_failure_preserves_primary(self) -> None:
        extraction_error = KeyboardInterrupt("extract CloseHandle result")

        class Result:
            @property
            def value(self) -> int:
                raise extraction_error

        kernel = FakeKernelApi()
        primary = RuntimeError("primary")
        recorded = Result()
        lease = receipt.WindowsHandleLease(kernel.handle, recorded)
        result = receipt.close_windows_handle_lease(kernel, lease, primary, "test handle")

        self.assertIs(result, primary)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertIs(lease.close_result, recorded)
        self.assertIn("extract CloseHandle result", "\n".join(getattr(primary, "__notes__", ())))
        self.assertEqual(kernel.calls, [])

    def test_close_failure_translation_failure_preserves_primary(self) -> None:
        translation_error = SystemExit("translate CloseHandle failure")

        class ErrorKernel(FakeKernelApi):
            def get_last_error(self) -> int:
                raise translation_error

        kernel = ErrorKernel()
        kernel.failures["CloseHandle"] = False
        primary = RuntimeError("primary")
        lease = receipt.WindowsHandleLease(kernel.handle)
        result = receipt.close_windows_handle_lease(kernel, lease, primary, "test handle")

        self.assertIs(result, primary)
        self.assertEqual(lease.handle, kernel.handle)
        self.assertEqual(lease.close_result, 0)
        self.assertIn("translate CloseHandle failure", "\n".join(getattr(primary, "__notes__", ())))
        self.assertEqual(
            kernel.calls,
            [
                ("CloseHandle", (kernel.handle,)),
                ("CloseHandle", (kernel.handle,)),
            ],
        )

    def test_recorded_result_consumption_retries_before_handle_retirement(self) -> None:
        kernel = FakeKernelApi()
        primary = RuntimeError("primary")
        interruption = KeyboardInterrupt("before recorded handle retirement")
        lease = receipt.WindowsHandleLease(kernel.handle, 1)
        target_code = receipt.close_windows_handle_lease.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.close_windows_handle_lease)
        retirement_line = source_start + [
            index
            for index, line in enumerate(source_lines)
            if line.strip() == "lease.handle = None"
        ][-1]
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if (
                event == "line"
                and frame.f_code is target_code
                and not triggered
                and frame.f_lineno == retirement_line
                and getattr(frame.f_locals.get("recorded"), "status", None) == 1
                and frame.f_locals.get("raw_status") == 1
                and lease.handle == kernel.handle
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            result = receipt.close_windows_handle_lease(kernel, lease, primary, "recorded handle")
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(result, primary)
        self.assertIsNone(lease.handle)
        self.assertIs(lease.close_result, receipt._WINDOWS_CLOSE_RESULT_PENDING)
        self.assertIn("before recorded handle retirement", "\n".join(getattr(primary, "__notes__", ())))
        self.assertEqual(kernel.calls, [])

    def test_empty_lease_with_stale_close_marker_is_safe_to_reuse(self) -> None:
        kernel = FakeKernelApi()
        first_handle = kernel.handle
        lease = receipt.WindowsHandleLease(first_handle)
        interruption = KeyboardInterrupt("after handle retirement")
        target_code = receipt.close_windows_handle_lease.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.close_windows_handle_lease)
        result_line = source_start + next(
            index
            for index, line in enumerate(source_lines)
            if line.strip() == "lease.recorded_close_results.clear()"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if (
                not triggered
                and event == "line"
                and frame.f_code is target_code
                and frame.f_lineno == result_line
                and lease.handle is None
                and lease.close_result is not receipt._WINDOWS_CLOSE_RESULT_PENDING
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            first_result = receipt.close_windows_handle_lease(kernel, lease, None, "first handle")
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(first_result, interruption)
        self.assertIsNone(lease.handle)
        self.assertIs(lease.close_result, receipt._WINDOWS_CLOSE_RESULT_PENDING)

        # Model a second interruption after handle retirement but before the
        # history reset; acquisition must normalize this empty stale state.
        lease.close_result = 1
        second_handle = 0xBEEF
        native = FakeNtApi(information=receipt.FILE_OPENED, handle=second_handle)
        information = receipt._relative_handle(
            kernel,
            native,
            7,
            "receipt.json",
            lease,
            desired_access=receipt._TARGET_READ_ACCESS,
            share_access=receipt.FILE_SHARE_READ,
            disposition=receipt.FILE_OPEN,
            options=receipt._FILE_OPEN_OPTIONS,
            expected_information=(receipt.FILE_OPENED,),
            operation="open receipt",
        )
        self.assertEqual(information, receipt.FILE_OPENED)
        self.assertEqual(lease.handle, second_handle)
        self.assertIs(lease.close_result, receipt._WINDOWS_CLOSE_RESULT_PENDING)
        self.assertIsNone(receipt.close_windows_handle_lease(kernel, lease, None, "second handle"))
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (first_handle,)), ("CloseHandle", (second_handle,))],
        )


class WindowsRelativeReceiptReaderTests(unittest.TestCase):
    def read(
        self,
        kernel: FakeKernelApi,
        native: FakeNtApi,
        *,
        leaf: str = "receipt-ž.json",
        payload: bytes = PAYLOAD,
    ) -> receipt.WindowsReceiptResult:
        return receipt.read_windows_receipt(
            0x4567,
            leaf,
            payload,
            api=kernel,
            nt_api=native,
            publication_lease=receipt._WindowsReceiptPublicationLease(kernel),
        )

    def test_exact_relative_open_abi_and_result(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)

        result = self.read(kernel, native)

        self.assertEqual(result, receipt.WindowsReceiptResult("receipt-ž.json", 91, bytes(range(16)), len(PAYLOAD)))
        self.assertEqual(len(native.calls), 1)
        call = native.calls[0]
        encoded_length = len("receipt-ž.json".encode("utf-16-le"))
        self.assertEqual(call["root"], 0x4567)
        self.assertEqual(call["name"], "receipt-ž.json")
        self.assertEqual(call["name_length"], encoded_length)
        self.assertEqual(call["name_maximum"], encoded_length + 2)
        self.assertEqual(call["terminator"], b"\x00\x00")
        self.assertEqual(call["object_length"], ctypes.sizeof(receipt._ObjectAttributes))
        self.assertEqual(call["object_flags"], receipt.OBJ_CASE_INSENSITIVE)
        self.assertIsNone(call["security"])
        self.assertIsNone(call["quality"])
        self.assertIsNone(call["allocation"])
        self.assertEqual(call["desired_access"], receipt._TARGET_READ_ACCESS)
        self.assertEqual(call["file_attributes"], receipt.FILE_ATTRIBUTE_NORMAL)
        self.assertEqual(call["share_access"], receipt.FILE_SHARE_READ)
        self.assertEqual(call["disposition"], receipt.FILE_OPEN)
        self.assertEqual(call["options"], receipt._FILE_OPEN_OPTIONS)
        self.assertIsNone(call["ea_buffer"])
        self.assertEqual(call["ea_length"], 0)
        self.assertEqual(kernel.calls[-1], ("CloseHandle", (native.handle,)))
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_native_not_found_statuses_translate_through_rtl(self) -> None:
        cases = (
            (0xC000000F, receipt.ERROR_FILE_NOT_FOUND),
            (0xC0000034, receipt.ERROR_FILE_NOT_FOUND),
            (0xC000003A, receipt.ERROR_PATH_NOT_FOUND),
        )
        for status, code in cases:
            with self.subTest(status=hex(status)):
                kernel = FakeKernelApi()
                native = FakeNtApi(information=receipt.FILE_OPENED, status=status)
                with self.assertRaises(FileNotFoundError) as caught:
                    self.read(kernel, native)
                self.assertEqual(caught.exception.errno, code)
                self.assertEqual(native.conversions, [status])
                self.assertFalse(any(name == "CloseHandle" for name, _args in kernel.calls))

    def test_completion_not_found_after_handle_acquisition_is_changed(self) -> None:
        for error_number in (receipt.ERROR_FILE_NOT_FOUND, receipt.ERROR_PATH_NOT_FOUND):
            with self.subTest(error_number=error_number):
                kernel = FakeKernelApi()
                native = FakeNtApi(
                    information=receipt.FILE_OPENED,
                    completion_status=0xC0000022,
                )
                native.error_codes[0xC0000022] = error_number

                with self.assertRaises(receipt.WindowsReceiptValidationError) as raised:
                    self.read(kernel, native)

                self.assertEqual(raised.exception.code, "output-changed")
                self.assertIsInstance(raised.exception.__cause__, FileNotFoundError)
                assert isinstance(raised.exception.__cause__, FileNotFoundError)
                self.assertEqual(raised.exception.__cause__.errno, error_number)
                self.assertEqual(
                    [call for call in kernel.calls if call[0] == "CloseHandle"],
                    [("CloseHandle", (native.handle,))],
                )

    def test_native_directory_rejection_has_stable_existing_invalid_code(self) -> None:
        native = FakeNtApi(
            information=receipt.FILE_OPENED,
            status=receipt.STATUS_FILE_IS_A_DIRECTORY,
        )
        native.error_codes[receipt.STATUS_FILE_IS_A_DIRECTORY] = 5
        kernel = FakeKernelApi(directory=True)
        with self.assertRaises(receipt.WindowsReceiptValidationError) as raised:
            self.read(kernel, native)
        self.assertEqual(raised.exception.code, "output-existing-invalid")
        self.assertIsInstance(raised.exception.__cause__, OSError)
        assert isinstance(raised.exception.__cause__, OSError)
        self.assertEqual(raised.exception.__cause__.errno, 5)
        self.assertEqual(native.conversions, [receipt.STATUS_FILE_IS_A_DIRECTORY])
        self.assertFalse(any(name == "CloseHandle" for name, _args in kernel.calls))

    def test_post_open_unsupported_operations_have_stable_anchor_code(self) -> None:
        cases = (
            ("metadata", "GetInfo:0", receipt.ERROR_NOT_SUPPORTED),
            ("file type", "GetFileType", receipt.ERROR_INVALID_FUNCTION),
            ("seek", "SetFilePointerEx", receipt.ERROR_INVALID_PARAMETER),
            ("read", "ReadFile", receipt.ERROR_CALL_NOT_IMPLEMENTED),
        )
        for label, operation, error_number in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi()
                kernel.failures[operation] = False
                kernel.error = error_number
                with self.assertRaises(receipt.WindowsReceiptValidationError) as raised:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(raised.exception.code, "output-anchor-unavailable")
                self.assertIsInstance(raised.exception.__cause__, OSError)
                assert isinstance(raised.exception.__cause__, OSError)
                self.assertEqual(raised.exception.__cause__.errno, error_number)
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_post_open_unsupported_translation_preserves_native_notes(self) -> None:
        native_error = OSError(receipt.ERROR_NOT_SUPPORTED, "unsupported metadata query")
        native_error.add_note("native metadata note")
        kernel = FakeKernelApi()
        kernel.failures["GetInfo:0"] = native_error

        with self.assertRaises(receipt.WindowsReceiptValidationError) as raised:
            self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))

        self.assertEqual(raised.exception.code, "output-anchor-unavailable")
        self.assertIs(raised.exception.__cause__, native_error)
        self.assertIn("native metadata note", getattr(raised.exception, "__notes__", ()))
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_post_open_namespace_failures_have_stable_changed_code(self) -> None:
        cases = (
            (
                "metadata",
                "GetInfo:0",
                FileNotFoundError(receipt.ERROR_FILE_NOT_FOUND, "metadata target disappeared"),
            ),
            (
                "read",
                "ReadFile",
                OSError(receipt.ERROR_PATH_NOT_FOUND, "receipt path disappeared"),
            ),
        )
        for label, operation, native_error in cases:
            with self.subTest(label=label):
                native_error.add_note("native namespace note")
                kernel = FakeKernelApi()
                kernel.failures[operation] = native_error

                with self.assertRaises(receipt.WindowsReceiptValidationError) as raised:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))

                self.assertEqual(raised.exception.code, "output-changed")
                self.assertIs(raised.exception.__cause__, native_error)
                self.assertIn("native namespace note", getattr(raised.exception, "__notes__", ()))
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_post_open_generic_io_operations_remain_native(self) -> None:
        for operation in ("GetInfo:0", "GetFileType", "SetFilePointerEx", "ReadFile"):
            with self.subTest(operation=operation):
                kernel = FakeKernelApi()
                kernel.failures[operation] = False
                kernel.error = 1117
                with self.assertRaises(OSError) as raised:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(raised.exception.errno, 1117)
                self.assertNotIsInstance(raised.exception, receipt.WindowsReceiptValidationError)
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_native_and_completion_failures_close_only_owned_handles(self) -> None:
        native_failure = FakeNtApi(information=receipt.FILE_OPENED, status=0xC0000022)
        kernel = FakeKernelApi()
        with self.assertRaises(OSError) as caught:
            self.read(kernel, native_failure)
        self.assertEqual(caught.exception.errno, 5)
        self.assertFalse(any(name == "CloseHandle" for name, _args in kernel.calls))

        completion_failure = FakeNtApi(
            information=receipt.FILE_OPENED,
            completion_status=0xC0000022,
        )
        kernel = FakeKernelApi()
        with self.assertRaises(OSError) as caught:
            self.read(kernel, completion_failure)
        self.assertEqual(caught.exception.errno, 5)
        self.assertEqual([name for name, _args in kernel.calls], ["CloseHandle"])

        wrong_information = FakeNtApi(information=receipt.FILE_CREATED)
        kernel = FakeKernelApi()
        with self.assertRaisesRegex(OSError, "IO_STATUS_BLOCK.Information"):
            self.read(kernel, wrong_information)
        self.assertEqual([name for name, _args in kernel.calls], ["CloseHandle"])

    def test_exception_after_native_handle_acquisition_closes_exactly_once(self) -> None:
        for primary in (OSError("acquire"), KeyboardInterrupt("acquire"), SystemExit("acquire")):
            with self.subTest(primary=type(primary).__name__):
                kernel = FakeKernelApi()
                native = FakeNtApi(information=receipt.FILE_OPENED)
                native.raise_after_acquire = primary
                with self.assertRaises(BaseException) as caught:
                    self.read(kernel, native)
                self.assertIs(caught.exception, primary)
                self.assertEqual(
                    [call for call in kernel.calls if call[0] == "CloseHandle"],
                    [("CloseHandle", (native.handle,))],
                )

        primary = KeyboardInterrupt("acquire")
        kernel = FakeKernelApi()
        kernel.failures["CloseHandle"] = SystemExit("close")
        native = FakeNtApi(information=receipt.FILE_OPENED)
        native.raise_after_acquire = primary
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.read(kernel, native)
        self.assertIs(caught.exception, primary)
        self.assertIn("Could not close", "\n".join(getattr(primary, "__notes__", ())))

    def test_handler_entry_interrupt_closes_lease_owned_native_output(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)
        native.raise_after_acquire = RuntimeError("native read acquisition returned before raising")
        interruption = KeyboardInterrupt("relative read acquisition handler entry")
        publication_lease = receipt._WindowsReceiptPublicationLease(kernel)

        caught = _interrupt_relative_handle_handler(
            lambda: receipt.read_windows_receipt(
                7,
                "receipt.json",
                PAYLOAD,
                api=kernel,
                nt_api=native,
                publication_lease=publication_lease,
            ),
            interruption,
        )

        self.assertIs(caught, interruption)
        self.assertTrue(publication_lease.is_closed)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_opcode_interrupt_after_native_return_closes_acquired_handle(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)
        interruption = KeyboardInterrupt("between native return and Python assignment")
        real_create = native.NtCreateFile
        triggered = False

        class _InterruptingStatus:
            def __int__(self) -> int:
                nonlocal triggered
                triggered = True
                raise interruption

        def create_then_return_status(*arguments: Any, **keywords: Any) -> object:
            real_create(*arguments, **keywords)
            return _InterruptingStatus()

        with mock.patch.object(
            native,
            "NtCreateFile",
            side_effect=create_then_return_status,
        ):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.read(kernel, native)
        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_reader_call_return_gap_is_owned_by_shared_lease(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)
        interruption = KeyboardInterrupt("relative helper returned before caller assignment")
        target_code = receipt.read_windows_receipt.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.read_windows_receipt)
        ownership_line = source_start + next(
            index for index, line in enumerate(source_lines) if line.strip() == "handle = lease.handle"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "line" and frame.f_code is target_code and not triggered and frame.f_lineno == ownership_line:
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.read(kernel, native)
        finally:
            sys.settrace(previous)
        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_leaf_and_payload_validation_precede_native_call(self) -> None:
        for leaf in INVALID_WINDOWS_RELATIVE_LEAVES:
            with self.subTest(leaf=repr(leaf)):
                kernel = FakeKernelApi()
                native = FakeNtApi(information=receipt.FILE_OPENED)
                with self.assertRaises(ValueError):
                    self.read(kernel, native, leaf=leaf)
                self.assertEqual(native.calls, [])
                self.assertEqual(kernel.calls, [])
        empty_kernel = FakeKernelApi(b"")
        empty_native = FakeNtApi(information=receipt.FILE_OPENED)
        with self.assertRaises(ValueError):
            self.read(empty_kernel, empty_native, payload=b"")
        self.assertEqual(empty_native.calls, [])
        self.assertEqual(empty_kernel.calls, [])

    def test_valid_near_miss_unicode_and_long_leaves_reach_native_unchanged(self) -> None:
        for leaf in VALID_WINDOWS_RELATIVE_LEAVES:
            with self.subTest(leaf=repr(leaf)):
                kernel = FakeKernelApi()
                native = FakeNtApi(information=receipt.FILE_OPENED)
                result = self.read(kernel, native, leaf=leaf)
                self.assertEqual(result.leaf, leaf)
                self.assertEqual(len(native.calls), 1)
                self.assertEqual(native.calls[0]["name"], leaf)

    def test_noncanonical_targets_have_stable_validation_code(self) -> None:
        cases: tuple[tuple[str, Callable[[FakeKernelApi], None]], ...] = (
            ("readonly", lambda api: setattr(api, "attributes", receipt.FILE_ATTRIBUTE_READONLY)),
            ("basic-directory", lambda api: setattr(api, "attributes", receipt.FILE_ATTRIBUTE_DIRECTORY)),
            ("reparse", lambda api: setattr(api, "attributes", receipt.FILE_ATTRIBUTE_REPARSE_POINT)),
            ("standard-directory", lambda api: setattr(api, "directory", 1)),
            ("delete-pending", lambda api: setattr(api, "delete_pending", 1)),
            ("multiple-links", lambda api: setattr(api, "links", 2)),
            ("non-disk", lambda api: setattr(api, "file_type", 0)),
        )
        for label, configure in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi()
                configure(kernel)
                with self.assertRaises(receipt.WindowsReceiptValidationError) as caught:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(caught.exception.code, "output-existing-invalid")
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_exact_size_bytes_and_eof_are_required(self) -> None:
        for label, data in (
            ("short", PAYLOAD[:-1]),
            ("long", PAYLOAD + b"x"),
            ("same-size-different", b"X" + PAYLOAD[1:]),
        ):
            with self.subTest(label=label):
                kernel = FakeKernelApi(data)
                with self.assertRaises(receipt.WindowsReceiptValidationError) as caught:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(caught.exception.code, "output-different")
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_identity_attributes_links_and_size_must_remain_stable(self) -> None:
        cases: tuple[tuple[str, str, object], ...] = (
            ("identity", "identity", b"z" * 16),
            ("volume", "volume", 92),
            ("attributes", "attributes", receipt.FILE_ATTRIBUTE_READONLY),
            ("links", "links", 2),
            ("size", "size", len(PAYLOAD) + 1),
        )
        for label, field, value in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi()
                kernel.metadata_overrides[1][field] = value
                with self.assertRaises(receipt.WindowsReceiptValidationError) as caught:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(caught.exception.code, "output-changed")

    def test_read_failures_and_control_flow_preserve_primary_over_close(self) -> None:
        for operation in ("SetFilePointerEx", "ReadFile"):
            with self.subTest(operation=operation):
                kernel = FakeKernelApi()
                kernel.failures[operation] = False
                with self.assertRaises(OSError):
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

        for primary in (OSError("read"), KeyboardInterrupt("read"), SystemExit("read")):
            with self.subTest(primary=type(primary).__name__):
                kernel = FakeKernelApi()
                cleanup = RuntimeError("close")
                kernel.failures.update({"ReadFile": primary, "CloseHandle": cleanup})
                with self.assertRaises(BaseException) as caught:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                self.assertIs(caught.exception, primary)
                self.assertIn("Could not close", "\n".join(getattr(primary, "__notes__", ())))
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_reader_close_call_return_gap_preserves_primary(self) -> None:
        kernel = FakeKernelApi()
        primary = RuntimeError("read")
        kernel.failures["ReadFile"] = primary
        interruption = KeyboardInterrupt("between reader close return and assignment")
        triggered = False

        real_close = receipt._WindowsReceiptPublicationLease.close

        def close_then_interrupt(
            publication_lease: receipt._WindowsReceiptPublicationLease,
        ) -> tuple[BaseException, ...]:
            nonlocal triggered
            result = real_close(publication_lease)
            if not triggered:
                triggered = True
                raise interruption
            return result

        with mock.patch.object(
            receipt._WindowsReceiptPublicationLease,
            "close",
            new=close_then_interrupt,
        ):
            with self.assertRaises(RuntimeError) as caught:
                self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))

        self.assertTrue(triggered)
        self.assertIs(caught.exception, primary)
        self.assertIn(
            "Could not close receipt verification handle: between reader close return and assignment",
            getattr(primary, "__notes__", ()),
        )
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_reader_cleanup_entry_interrupt_is_recovered_by_shared_owner(self) -> None:
        kernel = FakeKernelApi()
        native = FakeNtApi(information=receipt.FILE_OPENED)
        publication_lease = receipt._WindowsReceiptPublicationLease(kernel)
        interruption = KeyboardInterrupt("reader cleanup entry")
        target_code = receipt.read_windows_receipt.__code__
        source, first_line = inspect.getsourcelines(receipt.read_windows_receipt)
        cleanup_line = first_line + next(
            index for index, line in enumerate(source) if "close_failures = publication_lease.close()" in line
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target_code:
                frame.f_trace = trace
                return trace
            if event == "line" and frame.f_code is target_code and frame.f_lineno == cleanup_line and not triggered:
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.read_windows_receipt(
                    0x4567,
                    "receipt.json",
                    PAYLOAD,
                    api=kernel,
                    nt_api=native,
                    publication_lease=publication_lease,
                )
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertFalse(publication_lease.is_closed)
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 0)
        self.assertEqual(publication_lease.close(), ())
        self.assertTrue(publication_lease.is_closed)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_invalid_read_count_and_close_failure_are_not_hidden(self) -> None:
        kernel = FakeKernelApi()
        kernel.excessive_read_count = True
        with self.assertRaisesRegex(OSError, "more bytes"):
            self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

        for close_error in (False, KeyboardInterrupt("close"), SystemExit("close")):
            with self.subTest(close=type(close_error).__name__):
                kernel = FakeKernelApi()
                kernel.failures["CloseHandle"] = close_error
                with self.assertRaises(BaseException) as caught:
                    self.read(kernel, FakeNtApi(information=receipt.FILE_OPENED))
                if close_error is False:
                    self.assertIsInstance(caught.exception, OSError)
                else:
                    self.assertIs(caught.exception, close_error)
                expected_calls = 2 if close_error is False else 1
                self.assertEqual(
                    sum(name == "CloseHandle" for name, _args in kernel.calls),
                    expected_calls,
                )


class WindowsRelativeDirectoryTests(unittest.TestCase):
    def test_drive_and_unc_anchors_use_absolute_nt_names_with_external_lease(self) -> None:
        cases = (
            (Path("C:\\"), "\\??\\C:\\"),
            (Path("\\\\server\\share\\"), "\\??\\UNC\\server\\share\\"),
            (Path("\\\\?\\D:\\"), "\\??\\D:\\"),
            (Path("\\\\?\\UNC\\server\\share\\"), "\\??\\UNC\\server\\share\\"),
            (Path("\\\\?\\unc\\server\\share\\"), "\\??\\UNC\\server\\share\\"),
        )
        for path, expected_name in cases:
            with self.subTest(path=str(path)):
                kernel = FakeKernelApi(b"", directory=True)
                native = FakeNtApi(information=receipt.FILE_OPENED)
                lease = receipt.WindowsHandleLease()
                result = receipt.open_windows_directory_anchor(path, lease, api=kernel, nt_api=native)
                self.assertEqual(result.handle, native.handle)
                self.assertFalse(result.created)
                self.assertEqual(lease.handle, native.handle)
                call = native.calls[0]
                self.assertIsNone(call["root"])
                self.assertEqual(call["name"], expected_name)
                self.assertEqual(call["disposition"], receipt.FILE_OPEN)
                self.assertEqual(call["options"], receipt._DIRECTORY_OPEN_OPTIONS)
                self.assertFalse(any(name == "CloseHandle" for name, _args in kernel.calls))

    def test_anchor_rejects_relative_paths_before_native_open(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = FakeNtApi(information=receipt.FILE_OPENED)
        for path in (
            Path("relative"),
            Path("C:relative"),
            Path("é:\\"),
            Path("C:\\nested"),
            Path("\\\\server"),
            Path("\\\\server\\share\\nested"),
            Path("\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\"),
            Path("\\\\.\\C:\\"),
            Path("\\\\?\\UNC\\server\\share\\nested"),
            Path("\\\\?\\UNC\\.\\share\\"),
        ):
            with self.subTest(path=str(path)), self.assertRaises(ValueError):
                receipt.open_windows_directory_anchor(
                    path,
                    receipt.WindowsHandleLease(),
                    api=kernel,
                    nt_api=native,
                )
        self.assertEqual(native.calls, [])

    def test_invalid_directory_leaves_are_rejected_before_native_open(self) -> None:
        for leaf in ("NUL.txt", "CoM¹.log", "directory.", "bad?directory", "bad\x1fdirectory"):
            with self.subTest(leaf=repr(leaf)):
                kernel = FakeKernelApi(b"", directory=True)
                native = FakeNtApi(information=receipt.FILE_CREATED)
                lease = receipt.WindowsHandleLease()
                with self.assertRaises(ValueError):
                    receipt.open_or_create_windows_directory(
                        0xBEEF,
                        leaf,
                        lease,
                        api=kernel,
                        nt_api=native,
                    )
                self.assertEqual(native.calls, [])
                self.assertEqual(kernel.calls, [])
                self.assertIsNone(lease.handle)

    def test_anchor_relative_helper_return_gap_closes_shared_lease(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = FakeNtApi(information=receipt.FILE_OPENED)
        lease = receipt.WindowsHandleLease()
        interruption = KeyboardInterrupt("relative helper returned before anchor assignment")
        target_code = receipt.open_windows_directory_anchor.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.open_windows_directory_anchor)
        ownership_line = source_start + next(
            index for index, line in enumerate(source_lines) if line.strip() == "handle = lease.handle"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "line" and frame.f_code is target_code and not triggered and frame.f_lineno == ownership_line:
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.open_windows_directory_anchor(Path("C:\\"), lease, api=kernel, nt_api=native)
        finally:
            sys.settrace(previous)
        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertIsNone(lease.handle)
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_anchor_handler_entry_interrupt_closes_lease_owned_native_output(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = FakeNtApi(information=receipt.FILE_OPENED)
        native.raise_after_acquire = RuntimeError("native root acquisition returned before raising")
        interruption = KeyboardInterrupt("relative root acquisition handler entry")
        lease = receipt.WindowsHandleLease()

        caught = _interrupt_relative_handle_handler(
            lambda: receipt.open_windows_directory_anchor(
                Path("C:\\"),
                lease,
                api=kernel,
                nt_api=native,
            ),
            interruption,
        )

        self.assertIs(caught, interruption)
        self.assertIsNone(lease.handle)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_open_if_is_relative_and_returns_created_or_opened_identity(self) -> None:
        for information, created in ((receipt.FILE_CREATED, True), (receipt.FILE_OPENED, False)):
            with self.subTest(information=information):
                kernel = FakeKernelApi(b"", directory=True)
                native = FakeNtApi(information=information)
                lease = receipt.WindowsHandleLease()
                result = receipt.open_or_create_windows_directory(
                    0xBEEF,
                    "cache-ž",
                    lease,
                    api=kernel,
                    nt_api=native,
                )
                self.assertEqual(
                    result,
                    receipt.WindowsDirectoryResult(native.handle, 91, bytes(range(16)), created),
                )
                self.assertEqual(lease.handle, native.handle)
                call = native.calls[0]
                self.assertEqual(call["root"], 0xBEEF)
                self.assertEqual(call["name"], "cache-ž")
                self.assertEqual(call["desired_access"], receipt._DIRECTORY_ACCESS)
                self.assertEqual(call["share_access"], receipt.FILE_SHARE_READ | receipt.FILE_SHARE_WRITE)
                self.assertEqual(call["disposition"], receipt.FILE_OPEN_IF)
                self.assertEqual(call["options"], receipt._DIRECTORY_OPEN_OPTIONS)
                self.assertFalse(any(name == "CloseHandle" for name, _args in kernel.calls))

    def test_directory_helper_call_return_gap_closes_its_shared_lease(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = FakeNtApi(information=receipt.FILE_OPENED)
        lease = receipt.WindowsHandleLease()
        interruption = KeyboardInterrupt("relative helper returned before directory assignment")
        target_code = receipt.open_or_create_windows_directory.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.open_or_create_windows_directory)
        ownership_line = source_start + next(
            index for index, line in enumerate(source_lines) if line.strip() == "handle = lease.handle"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "line" and frame.f_code is target_code and not triggered and frame.f_lineno == ownership_line:
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.open_or_create_windows_directory(7, "child", lease, api=kernel, nt_api=native)
        finally:
            sys.settrace(previous)
        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertIsNone(lease.handle)
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_child_handler_entry_interrupt_closes_lease_owned_native_output(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        native = FakeNtApi(information=receipt.FILE_CREATED)
        native.raise_after_acquire = RuntimeError("native child acquisition returned before raising")
        interruption = KeyboardInterrupt("relative child acquisition handler entry")
        lease = receipt.WindowsHandleLease()

        caught = _interrupt_relative_handle_handler(
            lambda: receipt.open_or_create_windows_directory(
                7,
                "child",
                lease,
                api=kernel,
                nt_api=native,
            ),
            interruption,
        )

        self.assertIs(caught, interruption)
        self.assertIsNone(lease.handle)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_directory_rejection_and_metadata_drift_close_once(self) -> None:
        cases: tuple[tuple[str, Callable[[FakeKernelApi], None]], ...] = (
            ("file", lambda api: setattr(api, "directory", 0)),
            ("no-directory-attribute", lambda api: setattr(api, "attributes", receipt.FILE_ATTRIBUTE_NORMAL)),
            (
                "reparse",
                lambda api: setattr(
                    api,
                    "attributes",
                    receipt.FILE_ATTRIBUTE_DIRECTORY | receipt.FILE_ATTRIBUTE_REPARSE_POINT,
                ),
            ),
            ("delete-pending", lambda api: setattr(api, "delete_pending", 1)),
            ("non-disk", lambda api: setattr(api, "file_type", 0)),
            ("identity-drift", lambda api: api.metadata_overrides[1].update(identity=b"z" * 16)),
            (
                "attribute-drift",
                lambda api: api.metadata_overrides[1].update(
                    attributes=receipt.FILE_ATTRIBUTE_DIRECTORY | receipt.FILE_ATTRIBUTE_REPARSE_POINT
                ),
            ),
        )
        for label, configure in cases:
            with self.subTest(label=label):
                kernel = FakeKernelApi(b"", directory=True)
                configure(kernel)
                with self.assertRaises(receipt.WindowsReceiptValidationError) as caught:
                    receipt.open_or_create_windows_directory(
                        7,
                        "child",
                        receipt.WindowsHandleLease(),
                        api=kernel,
                        nt_api=FakeNtApi(information=receipt.FILE_OPENED),
                    )
                self.assertEqual(caught.exception.code, "output-parent-invalid")
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_directory_file_type_failure_distinguishes_unsupported_and_io(self) -> None:
        cases = (
            (receipt.ERROR_NOT_SUPPORTED, receipt.WindowsReceiptValidationError, "output-anchor-unavailable"),
            (1117, OSError, None),
        )
        for error_number, expected_type, expected_code in cases:
            with self.subTest(error_number=error_number):
                kernel = FakeKernelApi(b"", directory=True)
                kernel.failures["GetFileType"] = False
                kernel.error = error_number
                with self.assertRaises(expected_type) as raised:
                    receipt.open_or_create_windows_directory(
                        7,
                        "child",
                        receipt.WindowsHandleLease(),
                        api=kernel,
                        nt_api=FakeNtApi(information=receipt.FILE_OPENED),
                    )
                self.assertEqual(getattr(raised.exception, "code", None), expected_code)
                if expected_code is not None:
                    self.assertIsInstance(raised.exception.__cause__, OSError)
                    assert isinstance(raised.exception.__cause__, OSError)
                    self.assertEqual(raised.exception.__cause__.errno, error_number)
                else:
                    self.assertEqual(cast(OSError, raised.exception).errno, error_number)
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_directory_native_status_completion_and_information_fail_closed(self) -> None:
        cases = (
            FakeNtApi(information=receipt.FILE_OPENED, status=0xC0000035),
            FakeNtApi(information=receipt.FILE_OPENED, completion_status=0xC0000022),
            FakeNtApi(information=99),
        )
        for native in cases:
            with self.subTest(status=native.status, completion=native.completion_status):
                kernel = FakeKernelApi(b"", directory=True)
                with self.assertRaises(OSError):
                    receipt.open_or_create_windows_directory(
                        7,
                        "child",
                        receipt.WindowsHandleLease(),
                        api=kernel,
                        nt_api=native,
                    )
                expected_closes = int(receipt._nt_success(native.status))
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), expected_closes)

    def test_directory_primary_base_exception_beats_close_failure(self) -> None:
        for primary in (OSError("metadata"), KeyboardInterrupt("metadata"), SystemExit("metadata")):
            with self.subTest(primary=type(primary).__name__):
                kernel = FakeKernelApi(b"", directory=True)
                kernel.failures["GetInfo:0"] = primary
                kernel.failures["CloseHandle"] = RuntimeError("close")
                with self.assertRaises(BaseException) as caught:
                    receipt.open_or_create_windows_directory(
                        7,
                        "child",
                        receipt.WindowsHandleLease(),
                        api=kernel,
                        nt_api=FakeNtApi(information=receipt.FILE_OPENED),
                    )
                self.assertIs(caught.exception, primary)
                self.assertIn("Could not close", "\n".join(getattr(primary, "__notes__", ())))
                self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)

    def test_directory_close_call_return_gap_preserves_primary(self) -> None:
        kernel = FakeKernelApi(b"", directory=True)
        primary = RuntimeError("metadata")
        kernel.failures["GetInfo:0"] = primary
        interruption = KeyboardInterrupt("between directory close return and completion")
        triggered = False

        real_close = receipt.close_windows_handle_lease

        def close_then_interrupt(
            api: Any,
            lease: receipt.WindowsHandleLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            nonlocal triggered
            result = real_close(api, lease, active_primary, context)
            if not triggered:
                triggered = True
                raise interruption
            return result

        with mock.patch.object(
            receipt,
            "close_windows_handle_lease",
            side_effect=close_then_interrupt,
        ):
            with self.assertRaises(RuntimeError) as caught:
                receipt.open_or_create_windows_directory(
                    7,
                    "child",
                    receipt.WindowsHandleLease(),
                    api=kernel,
                    nt_api=FakeNtApi(information=receipt.FILE_OPENED),
                )

        self.assertTrue(triggered)
        self.assertIs(caught.exception, primary)
        self.assertIn(
            "Could not close rejected directory handle: between directory close return and completion",
            getattr(primary, "__notes__", ()),
        )
        self.assertEqual(sum(name == "CloseHandle" for name, _args in kernel.calls), 1)


class WindowsRelativeStageTests(unittest.TestCase):
    def test_staging_uses_only_relative_file_create(self) -> None:
        api = FakeKernel32()
        result = receipt.publish_windows_receipt(
            0x4567,
            "receipt.json",
            PAYLOAD,
            api=api,
            nt_api=api,
            stage_token="feed",
            publication_lease=receipt._WindowsReceiptPublicationLease(api),
        )
        self.assertEqual(result.leaf, "receipt.json")
        create = next(args for name, args in api.calls if name == "NtCreateFile")
        self.assertEqual(create[0], receipt._STAGE_ACCESS)
        self.assertEqual(create[1], 0x4567)
        self.assertEqual(create[2], ".receipt.json.feed.tmp")
        self.assertEqual(create[8], receipt.FILE_SHARE_READ)
        self.assertEqual(create[9], receipt.FILE_CREATE)
        self.assertEqual(create[10], receipt._FILE_OPEN_OPTIONS)

    def test_staging_call_return_gap_disposes_and_closes_shared_lease(self) -> None:
        api = FakeKernel32()
        interruption = KeyboardInterrupt("relative helper returned before publisher assignment")
        target_code = receipt.publish_windows_receipt.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.publish_windows_receipt)
        ownership_line = source_start + next(
            index for index, line in enumerate(source_lines) if line.strip() == "handle = lease.handle"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "line" and frame.f_code is target_code and not triggered and frame.f_lineno == ownership_line:
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.publish_windows_receipt(
                    7,
                    "receipt.json",
                    PAYLOAD,
                    api=api,
                    nt_api=api,
                    stage_token="feed",
                    publication_lease=receipt._WindowsReceiptPublicationLease(api),
                )
        finally:
            sys.settrace(previous)
        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)
        self.assertEqual(api.calls[-1], ("CloseHandle", (api.handle,)))

    def test_stage_handler_entry_interrupt_disposes_and_closes_lease_owned_native_output(self) -> None:
        kernel = FakeKernel32()
        native = FakeNtApi(information=receipt.FILE_CREATED, handle=kernel.handle)
        native.raise_after_acquire = RuntimeError("native stage acquisition returned before raising")
        interruption = KeyboardInterrupt("relative stage acquisition handler entry")
        publication_lease = receipt._WindowsReceiptPublicationLease(kernel)

        caught = _interrupt_relative_handle_handler(
            lambda: receipt.publish_windows_receipt(
                7,
                "receipt.json",
                PAYLOAD,
                api=kernel,
                nt_api=native,
                stage_token="feed",
                publication_lease=publication_lease,
            ),
            interruption,
        )

        self.assertIs(caught, interruption)
        self.assertTrue(publication_lease.is_closed)
        disposition_calls = [
            args
            for name, args in kernel.calls
            if name == "SetFileInformationByHandle" and args[1] == receipt.FILE_DISPOSITION_INFO
        ]
        self.assertEqual(len(disposition_calls), 1)
        self.assertEqual(
            [call for call in kernel.calls if call[0] == "CloseHandle"],
            [("CloseHandle", (native.handle,))],
        )

    def test_caller_held_lease_recovers_publisher_cleanup_entry_and_outcome(self) -> None:
        api = FakeKernel32()
        publication_lease = receipt._WindowsReceiptPublicationLease(api)
        interruption = KeyboardInterrupt("publisher cleanup entry")
        target_code = receipt.publish_windows_receipt.__code__
        source, first_line = inspect.getsourcelines(receipt.publish_windows_receipt)
        cleanup_line = first_line + next(
            index for index, line in enumerate(source) if "active_error = sys.exception()" in line
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
                and publication_lease.phase == "published"
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.publish_windows_receipt(
                    7,
                    "receipt.json",
                    PAYLOAD,
                    api=api,
                    nt_api=api,
                    stage_token="feed",
                    publication_lease=publication_lease,
                )
        finally:
            sys.settrace(previous)

        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(receipt.outcome_from_error(interruption), None)
        outcome = publication_lease.outcome
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.state, "published")
        self.assertEqual(outcome.receipt.leaf, "receipt.json")
        self.assertFalse(publication_lease.is_closed)
        self.assertFalse(any(name == "CloseHandle" for name, _args in api.calls))
        self.assertEqual(publication_lease.close(), ())
        self.assertTrue(publication_lease.is_closed)
        self.assertEqual(sum(name == "CloseHandle" for name, _args in api.calls), 1)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_post_native_stage_rejections_dispose_before_exactly_once_close(self) -> None:
        interruption = KeyboardInterrupt("native create returned a handle before raising")
        cases = (
            (
                "native-interruption",
                FakeNtApi(information=receipt.FILE_CREATED, handle=0x1234),
                interruption,
            ),
            (
                "completion-error",
                FakeNtApi(
                    information=receipt.FILE_CREATED,
                    completion_status=0xC0000022,
                    handle=0x1234,
                ),
                None,
            ),
            (
                "information-error",
                FakeNtApi(information=receipt.FILE_OPENED, handle=0x1234),
                None,
            ),
        )
        cases[0][1].raise_after_acquire = interruption

        for label, native, expected_primary in cases:
            with self.subTest(label=label):
                kernel = FakeKernel32()
                with self.assertRaises(BaseException) as caught:
                    receipt.publish_windows_receipt(
                        7,
                        "receipt.json",
                        PAYLOAD,
                        api=kernel,
                        nt_api=native,
                        stage_token="feed",
                        publication_lease=receipt._WindowsReceiptPublicationLease(kernel),
                    )
                if expected_primary is not None:
                    self.assertIs(caught.exception, expected_primary)

                disposition_indexes = [
                    index
                    for index, (name, args) in enumerate(kernel.calls)
                    if name == "SetFileInformationByHandle" and args[1] == receipt.FILE_DISPOSITION_INFO
                ]
                close_indexes = [index for index, (name, _args) in enumerate(kernel.calls) if name == "CloseHandle"]
                self.assertEqual(len(disposition_indexes), 1)
                self.assertEqual(len(close_indexes), 1)
                self.assertLess(disposition_indexes[0], close_indexes[0])
                self.assertEqual(kernel.calls[close_indexes[0]], ("CloseHandle", (native.handle,)))

    def test_stage_opcode_interrupt_after_native_return_disposes_before_close(self) -> None:
        kernel = FakeKernel32()
        native = FakeNtApi(information=receipt.FILE_CREATED, handle=kernel.handle)
        interruption = KeyboardInterrupt("between NtCreateFile return and stage handoff")
        real_create = native.NtCreateFile
        triggered = False

        class _InterruptingStatus:
            def __int__(self) -> int:
                nonlocal triggered
                triggered = True
                raise interruption

        def create_then_return_status(*arguments: Any, **keywords: Any) -> object:
            real_create(*arguments, **keywords)
            return _InterruptingStatus()

        with mock.patch.object(
            native,
            "NtCreateFile",
            side_effect=create_then_return_status,
        ):
            with self.assertRaises(KeyboardInterrupt) as caught:
                receipt.publish_windows_receipt(
                    7,
                    "receipt.json",
                    PAYLOAD,
                    api=kernel,
                    nt_api=native,
                    stage_token="feed",
                    publication_lease=receipt._WindowsReceiptPublicationLease(kernel),
                )

        self.assertTrue(triggered)
        self.assertIs(caught.exception, interruption)
        disposition_indexes = [
            index
            for index, (name, args) in enumerate(kernel.calls)
            if name == "SetFileInformationByHandle" and args[1] == receipt.FILE_DISPOSITION_INFO
        ]
        close_indexes = [index for index, (name, _args) in enumerate(kernel.calls) if name == "CloseHandle"]
        self.assertEqual(len(disposition_indexes), 1)
        self.assertEqual(len(close_indexes), 1)
        self.assertLess(disposition_indexes[0], close_indexes[0])

    def test_only_native_collision_status_has_internal_retry_provenance(self) -> None:
        api = FakeKernel32({"NtCreateFile": False})
        api.error = receipt.ERROR_FILE_EXISTS
        with self.assertRaises(receipt._StageNameCollision) as caught:
            receipt.publish_windows_receipt(
                7,
                "receipt.json",
                PAYLOAD,
                api=api,
                nt_api=api,
                stage_token="feed",
                publication_lease=receipt._WindowsReceiptPublicationLease(api),
            )
        self.assertTrue(receipt.is_internal_stage_name_collision(caught.exception))

        spoof = receipt._StageNameCollision(receipt.ERROR_FILE_EXISTS, "spoof")
        api = FakeKernel32({"NtCreateFile": spoof})
        with self.assertRaises(receipt._StageNameCollision) as caught:
            receipt.publish_windows_receipt(
                7,
                "receipt.json",
                PAYLOAD,
                api=api,
                nt_api=api,
                stage_token="feed",
                publication_lease=receipt._WindowsReceiptPublicationLease(api),
            )
        self.assertIs(caught.exception, spoof)
        self.assertFalse(receipt.is_internal_stage_name_collision(spoof))


if __name__ == "__main__":
    unittest.main()
