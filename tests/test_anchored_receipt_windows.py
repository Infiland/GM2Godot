# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import inspect
import sys
import unittest
from typing import Any, Callable, cast
from unittest import mock

from scripts import _anchored_receipt_windows as receipt

PAYLOAD = b'{"ok":true}\n'


class FakeKernel32:
    def __init__(self, failures: dict[str, BaseException | bool] | None = None) -> None:
        self.failures = failures or {}
        self.error = 5
        self._last_error = 0
        self.handle = 0x1234
        self.data = bytearray()
        self.position = 0
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.identity = bytes(range(16))
        self.attributes = receipt.FILE_ATTRIBUTE_NORMAL
        self.directory = 0
        self.links = 1
        self.read_override: bytes | None = None
        self.read_sequences: list[bytes] | None = None
        self.seek_index = -1
        self.write_zero = False
        self.metadata_index = 0
        self.metadata_overrides: list[dict[str, object]] = [{}, {}, {}]
        self.rename_succeeded = False
        self.create_succeeded = False
        self.excessive_read_count = False
        self.info_failure_at: tuple[int, int, BaseException] | None = None
        self.info_counts: dict[int, int] = {}
        self.read_failure_seek: tuple[int, BaseException] | None = None
        self.rename_status = 0
        self.rename_completion_status = 0
        self.rename_information = 0

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

    def NtCreateFile(
        self,
        output: Any,
        desired_access: int,
        object_attributes: Any,
        io_status: Any,
        allocation_size: object,
        attributes: int,
        share_access: int,
        disposition: int,
        options: int,
        ea_buffer: object,
        ea_length: int,
    ) -> int:
        native = ctypes.cast(object_attributes, ctypes.POINTER(receipt._ObjectAttributes)).contents
        name = native.ObjectName.contents
        raw_name = ctypes.string_at(name.Buffer, name.Length)
        self.calls.append(
            (
                "NtCreateFile",
                (
                    desired_access,
                    native.RootDirectory,
                    raw_name.decode("utf-16-le"),
                    name.Length,
                    name.MaximumLength,
                    native.Attributes,
                    allocation_size,
                    attributes,
                    share_access,
                    disposition,
                    options,
                    ea_buffer,
                    ea_length,
                ),
            )
        )
        action = self.failures.get("NtCreateFile")
        if isinstance(action, BaseException):
            raise action
        if action is False:
            if self.error in (receipt.ERROR_FILE_EXISTS, receipt.ERROR_ALREADY_EXISTS):
                return ctypes.c_int32(receipt.STATUS_OBJECT_NAME_COLLISION).value
            return ctypes.c_int32(0xC0000022).value
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = self.handle
        completion = ctypes.cast(io_status, ctypes.POINTER(receipt._IoStatusBlock)).contents
        completion.Status = 0
        completion.Information = receipt.FILE_CREATED
        self.create_succeeded = True
        return 0

    def RtlNtStatusToDosError(self, status: int) -> int:
        self.calls.append(("RtlNtStatusToDosError", (status,)))
        if ctypes.c_uint32(status).value == receipt.STATUS_OBJECT_NAME_COLLISION:
            return self.error
        return self.error

    def NtSetInformationFile(
        self,
        handle: int,
        io_status: Any,
        pointer: Any,
        size: int,
        info_class: int,
    ) -> int:
        raw = ctypes.string_at(pointer, size)
        self.calls.append(("NtSetInformationFile", (handle, info_class, raw, size)))
        padded = raw + bytes(max(0, ctypes.sizeof(receipt._FileRenameInformation) - len(raw)))
        rename = receipt._FileRenameInformation.from_buffer_copy(padded)
        minimum_size = ctypes.sizeof(receipt._FileRenameInformation) + rename.FileNameLength
        if info_class != receipt.FILE_RENAME_INFORMATION or size < minimum_size:
            return ctypes.c_int32(0xC0000004).value
        action = self.failures.get("Rename")
        if isinstance(action, BaseException):
            raise action
        if action is False:
            status = receipt.STATUS_OBJECT_NAME_COLLISION if self.error in (
                receipt.ERROR_FILE_EXISTS,
                receipt.ERROR_ALREADY_EXISTS,
            ) else 0xC0000022
            return ctypes.c_int32(status).value
        completion = ctypes.cast(io_status, ctypes.POINTER(receipt._IoStatusBlock)).contents
        completion.Status = ctypes.c_int32(self.rename_completion_status).value
        completion.Information = self.rename_information
        if self.rename_status == 0 and self.rename_completion_status == 0:
            self.rename_succeeded = True
        return ctypes.c_int32(self.rename_status).value

    def WriteFile(self, handle: int, buffer: Any, size: int, written: Any, _overlap: object) -> bool:
        self.calls.append(("WriteFile", (handle, size)))
        if not self._action("WriteFile"):
            return False
        amount = 0 if self.write_zero else min(size, 3)
        self.data.extend(ctypes.string_at(buffer, amount))
        ctypes.cast(written, ctypes.POINTER(receipt.DWORD)).contents.value = amount
        return True

    def FlushFileBuffers(self, handle: int) -> bool:
        self.calls.append(("FlushFileBuffers", (handle,)))
        return self._action("FlushFileBuffers")

    def SetFilePointerEx(self, handle: int, offset: int, _new: object, method: int) -> bool:
        self.calls.append(("SetFilePointerEx", (handle, offset, method)))
        if not self._action("SetFilePointerEx"):
            return False
        self.position = offset
        self.seek_index += 1
        return True

    def ReadFile(self, handle: int, buffer: Any, size: int, read: Any, _overlap: object) -> bool:
        self.calls.append(("ReadFile", (handle, size)))
        if self.read_failure_seek is not None and self.read_failure_seek[0] == self.seek_index:
            raise self.read_failure_seek[1]
        if not self._action("ReadFile"):
            return False
        source: bytes | bytearray = self.data
        if self.read_sequences is not None:
            source = self.read_sequences[min(self.seek_index, len(self.read_sequences) - 1)]
        elif self.read_override is not None:
            source = self.read_override
        chunk = bytes(source[self.position : self.position + size])
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
        return receipt.FILE_TYPE_DISK

    def GetFileInformationByHandleEx(self, handle: int, info_class: int, pointer: Any, size: int) -> bool:
        self.calls.append(("GetFileInformationByHandleEx", (handle, info_class, size)))
        count = self.info_counts.get(info_class, 0) + 1
        self.info_counts[info_class] = count
        if self.info_failure_at is not None and self.info_failure_at[:2] == (info_class, count):
            raise self.info_failure_at[2]
        if not self._action(f"GetInfo:{info_class}"):
            return False
        if info_class == receipt.FILE_BASIC_INFO:
            override = self.metadata_overrides[min(self.metadata_index, 2)]
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileBasicInfo)).contents
            value.FileAttributes = cast(int, override.get("attributes", self.attributes))
        elif info_class == receipt.FILE_STANDARD_INFO:
            override = self.metadata_overrides[min(self.metadata_index, 2)]
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileStandardInfo)).contents
            default_size = 0 if self.metadata_index == 0 else len(self.data)
            value.EndOfFile = cast(int, override.get("size", default_size))
            value.NumberOfLinks = cast(int, override.get("links", self.links))
            value.Directory = cast(int, override.get("directory", self.directory))
        else:
            override = self.metadata_overrides[min(self.metadata_index, 2)]
            value = ctypes.cast(pointer, ctypes.POINTER(receipt._FileIdInfo)).contents
            value.VolumeSerialNumber = 77
            identity = cast(bytes, override.get("identity", self.identity))
            for index, byte in enumerate(identity):
                value.FileId.Identifier[index] = byte
            self.metadata_index += 1
        return True

    def SetFileInformationByHandle(self, handle: int, info_class: int, pointer: Any, size: int) -> bool:
        raw = ctypes.string_at(pointer, size)
        self.calls.append(("SetFileInformationByHandle", (handle, info_class, raw, size)))
        name = "Disposition" if info_class == receipt.FILE_DISPOSITION_INFO else f"SetInfo:{info_class}"
        result = self._action(name)
        return result

    def CloseHandle(self, handle: int) -> bool:
        self.calls.append(("CloseHandle", (handle,)))
        return self._action("CloseHandle")


class WindowsAnchoredReceiptTests(unittest.TestCase):
    def publish(self, api: FakeKernel32) -> receipt.WindowsReceiptResult:
        return receipt.publish_windows_receipt(
            0x4567,
            "receipt.json",
            PAYLOAD,
            api=api,
            stage_token="feed",
            publication_lease=receipt._WindowsReceiptPublicationLease(api),
        )

    def test_success_uses_exact_access_and_retained_handle_abi(self) -> None:
        api = FakeKernel32()
        result = self.publish(api)
        self.assertEqual(
            result,
            receipt.WindowsReceiptResult("receipt.json", 77, bytes(range(16)), len(PAYLOAD)),
        )
        self.assertEqual(api.calls[0][0], "NtCreateFile")
        creation = api.calls[0][1]
        self.assertEqual(
            creation,
            (
                receipt._STAGE_ACCESS,
                0x4567,
                ".receipt.json.feed.tmp",
                len(".receipt.json.feed.tmp".encode("utf-16-le")),
                len(".receipt.json.feed.tmp".encode("utf-16-le")) + 2,
                receipt.OBJ_CASE_INSENSITIVE,
                None,
                receipt.FILE_ATTRIBUTE_NORMAL,
                receipt.FILE_SHARE_READ,
                receipt.FILE_CREATE,
                receipt._FILE_OPEN_OPTIONS,
                None,
                0,
            ),
        )
        rename_call = next(
            args
            for name, args in api.calls
            if name == "NtSetInformationFile" and args[1] == receipt.FILE_RENAME_INFORMATION
        )
        raw = cast(bytes, rename_call[2])
        info = receipt._FileRenameInformation.from_buffer_copy(
            raw + bytes(max(0, ctypes.sizeof(receipt._FileRenameInformation) - len(raw)))
        )
        encoded = "receipt.json".encode("utf-16-le")
        self.assertEqual(info.ReplaceIfExists, 0)
        self.assertIsNone(info.RootDirectory)
        self.assertEqual(info.FileNameLength, len(encoded))
        offset = receipt._FileRenameInformation.FileName.offset
        self.assertEqual(raw[offset : offset + len(encoded)], encoded)
        self.assertEqual(rename_call[3], ctypes.sizeof(receipt._FileRenameInformation) + len(encoded))
        self.assertEqual(
            raw[offset + len(encoded) :],
            bytes(ctypes.sizeof(receipt._FileRenameInformation) - offset),
        )
        self.assertNotIn(
            receipt.FILE_DISPOSITION_INFO, [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        )
        self.assertEqual(api.calls[-1], ("CloseHandle", (api.handle,)))

    def test_one_character_leaf_passes_full_allocated_rename_structure(self) -> None:
        api = FakeKernel32()
        receipt.publish_windows_receipt(
            0x4567,
            "x",
            PAYLOAD,
            api=api,
            stage_token="feed",
            publication_lease=receipt._WindowsReceiptPublicationLease(api),
        )
        rename_call = next(
            args
            for name, args in api.calls
            if name == "NtSetInformationFile" and args[1] == receipt.FILE_RENAME_INFORMATION
        )
        self.assertEqual(
            rename_call[3],
            ctypes.sizeof(receipt._FileRenameInformation) + len("x".encode("utf-16-le")),
        )
        info = receipt._FileRenameInformation.from_buffer_copy(cast(bytes, rename_call[2]))
        self.assertEqual(info.FileNameLength, len("x".encode("utf-16-le")))

    def test_modeled_nt_rejects_undersized_rename_buffer(self) -> None:
        api = FakeKernel32()
        encoded = "receipt.json".encode("utf-16-le")
        undersized = ctypes.create_string_buffer(
            receipt._FileRenameInformation.FileName.offset + len(encoded)
        )
        rename = receipt._FileRenameInformation.from_buffer(undersized)
        rename.FileNameLength = len(encoded)

        self.assertFalse(
            receipt._nt_success(
                api.NtSetInformationFile(
                    api.handle,
                    ctypes.byref(receipt._IoStatusBlock()),
                    undersized,
                    len(undersized),
                    receipt.FILE_RENAME_INFORMATION,
                )
            )
        )

    def test_modeled_nt_allows_explicit_root_handle_for_relative_target(self) -> None:
        api = FakeKernel32()
        encoded = "receipt.json".encode("utf-16-le")
        storage = ctypes.create_string_buffer(
            ctypes.sizeof(receipt._FileRenameInformation) + len(encoded)
        )
        rename = receipt._FileRenameInformation.from_buffer(storage)
        rename.RootDirectory = 0x4567
        rename.FileNameLength = len(encoded)
        ctypes.memmove(
            ctypes.addressof(storage) + receipt._FileRenameInformation.FileName.offset,
            encoded,
            len(encoded),
        )

        self.assertTrue(
            receipt._nt_success(
                api.NtSetInformationFile(
                    api.handle,
                    ctypes.byref(receipt._IoStatusBlock()),
                    storage,
                    len(storage),
                    receipt.FILE_RENAME_INFORMATION,
                )
            )
        )

    def test_write_loops_and_read_requires_exact_eof(self) -> None:
        api = FakeKernel32()
        self.publish(api)
        self.assertGreater(len([call for call in api.calls if call[0] == "WriteFile"]), 1)
        self.assertEqual(bytes(api.data), PAYLOAD)
        self.assertGreaterEqual(len([call for call in api.calls if call[0] == "ReadFile"]), 2)

    def test_creation_failure_has_no_handle_cleanup(self) -> None:
        api = FakeKernel32({"NtCreateFile": False})
        with self.assertRaises(OSError):
            self.publish(api)
        self.assertEqual([name for name, _args in api.calls], ["NtCreateFile", "RtlNtStatusToDosError"])

    def test_every_primary_boundary_disposes_and_closes(self) -> None:
        cases = (
            "GetInfo:0",
            "GetInfo:1",
            "GetInfo:18",
            "GetFileType",
            "WriteFile",
            "FlushFileBuffers",
            "SetFilePointerEx",
            "ReadFile",
        )
        for boundary in cases:
            with self.subTest(boundary=boundary):
                error = RuntimeError(boundary)
                api = FakeKernel32({boundary: error})
                with self.assertRaises(BaseException) as caught:
                    self.publish(api)
                self.assertIs(caught.exception, error)
                info_classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertIn(receipt.FILE_DISPOSITION_INFO, info_classes)
                self.assertEqual(api.calls[-1][0], "CloseHandle")

    def test_kind_identity_size_and_payload_drift_fail_before_rename(self) -> None:
        def reparse(api: FakeKernel32) -> None:
            api.attributes = receipt.FILE_ATTRIBUTE_REPARSE_POINT

        def readonly(api: FakeKernel32) -> None:
            api.attributes = receipt.FILE_ATTRIBUTE_READONLY

        def basic_directory(api: FakeKernel32) -> None:
            api.attributes = receipt.FILE_ATTRIBUTE_DIRECTORY

        def directory(api: FakeKernel32) -> None:
            api.directory = 1

        def links(api: FakeKernel32) -> None:
            api.links = 2

        def wrong_type(api: FakeKernel32) -> None:
            api.failures["GetFileType"] = False

        for label, mutate in (
            ("reparse", cast(Callable[[FakeKernel32], None], reparse)),
            ("readonly", readonly),
            ("basic-directory", basic_directory),
            ("directory", directory),
            ("links", links),
            ("type", wrong_type),
        ):
            with self.subTest(label=label):
                api = FakeKernel32()
                mutate(api)
                with self.assertRaises(OSError):
                    self.publish(api)
                self.assertFalse(
                    any(
                        args[1] == receipt.FILE_RENAME_INFORMATION
                        for name, args in api.calls
                        if name == "NtSetInformationFile"
                    )
                )

    def test_fixed_width_win32_abi_layouts(self) -> None:
        self.assertEqual(ctypes.sizeof(receipt.DWORD), 4)
        self.assertEqual(ctypes.sizeof(receipt.BOOLEAN), 1)
        self.assertEqual(ctypes.sizeof(receipt.WCHAR), 2)
        self.assertEqual(ctypes.sizeof(receipt._FileBasicInfo), 40)
        self.assertEqual(ctypes.sizeof(receipt._FileStandardInfo), 24)
        self.assertEqual(ctypes.sizeof(receipt._FileDispositionInfo), 1)
        self.assertEqual(ctypes.sizeof(receipt._FileId128), 16)
        self.assertEqual(ctypes.sizeof(receipt._FileIdInfo), 24)
        self.assertEqual(receipt._FileIdInfo.VolumeSerialNumber.offset, 0)
        self.assertEqual(receipt._FileIdInfo.FileId.offset, 8)
        self.assertEqual(receipt._FileId128.Identifier.offset, 0)
        expected_root_offset = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
        expected_name_length_offset = expected_root_offset + ctypes.sizeof(ctypes.c_void_p)
        self.assertEqual(receipt._FileRenameInformation.RootDirectory.offset, expected_root_offset)
        self.assertEqual(receipt._FileRenameInformation.FileNameLength.offset, expected_name_length_offset)
        self.assertEqual(receipt._FileRenameInformation.FileName.offset, expected_name_length_offset + 4)

    def test_native_api_declarations_use_fixed_width_counts(self) -> None:
        class Function:
            argtypes: object = None
            restype: object = None

            def __call__(self, *_args: object) -> int:
                return 1

        api = type("Api", (), {})()
        for name in (
            "WriteFile",
            "ReadFile",
            "FlushFileBuffers",
            "SetFilePointerEx",
            "GetFileInformationByHandleEx",
            "SetFileInformationByHandle",
            "GetFileType",
            "CloseHandle",
        ):
            setattr(api, name, Function())
        configured: Any = receipt._configure_api(api)
        self.assertIs(configured.WriteFile.argtypes[2], receipt.DWORD)
        self.assertIs(configured.WriteFile.argtypes[3]._type_, receipt.DWORD)
        self.assertEqual(configured.ReadFile.argtypes, configured.WriteFile.argtypes)
        self.assertIs(configured.SetFileInformationByHandle.argtypes[3], receipt.DWORD)

    def test_leaf_and_stage_token_reject_paths_and_ads(self) -> None:
        for leaf in (
            "",
            ".",
            "..",
            "NUL.txt",
            "CoM¹.log",
            "receipt.",
            "receipt ",
            "a?b",
            "a/b",
            r"a\b",
            "a:b",
            "a\x00b",
            "a\x1fb",
            "\ud800",
        ):
            with self.subTest(leaf=repr(leaf)):
                api = FakeKernel32()
                with self.assertRaises(ValueError):
                    receipt.publish_windows_receipt(
                        1,
                        leaf,
                        PAYLOAD,
                        api=api,
                        publication_lease=receipt._WindowsReceiptPublicationLease(api),
                    )
                self.assertEqual(api.calls, [])
        api = FakeKernel32()
        for token in ("", "ABC", "a/b", "a:b"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                receipt.publish_windows_receipt(
                    1,
                    "receipt.json",
                    PAYLOAD,
                    api=api,
                    stage_token=token,
                    publication_lease=receipt._WindowsReceiptPublicationLease(api),
                )

    def test_valid_unicode_and_long_leaves_publish_without_normalization(self) -> None:
        leaves = (
            "NUL\N{NO-BREAK SPACE}.txt",
            "receipt-ž-文件-\N{GRINNING FACE}.json",
            f"{'long-' * 60}.json",
        )
        for leaf in leaves:
            with self.subTest(leaf=repr(leaf)):
                api = FakeKernel32()
                result = receipt.publish_windows_receipt(
                    0x4567,
                    leaf,
                    PAYLOAD,
                    api=api,
                    stage_token="feed",
                    publication_lease=receipt._WindowsReceiptPublicationLease(api),
                )
                self.assertEqual(result.leaf, leaf)
                create = next(arguments for name, arguments in api.calls if name == "NtCreateFile")
                self.assertEqual(create[2], f".{leaf}.feed.tmp")

    def test_zero_write_progress_early_eof_extra_and_mismatch_fail(self) -> None:
        cases: list[tuple[str, Callable[[FakeKernel32], None]]] = []

        def zero(api: FakeKernel32) -> None:
            api.write_zero = True

        def early(api: FakeKernel32) -> None:
            api.read_override = PAYLOAD[:-1]

        def extra(api: FakeKernel32) -> None:
            api.read_override = PAYLOAD + b"x"

        def mismatch(api: FakeKernel32) -> None:
            api.read_override = b"X" + PAYLOAD[1:]

        def excessive(api: FakeKernel32) -> None:
            api.excessive_read_count = True

        cases.extend(
            (("zero", zero), ("early", early), ("extra", extra), ("mismatch", mismatch), ("excessive", excessive))
        )
        for label, configure in cases:
            with self.subTest(label=label):
                api = FakeKernel32()
                configure(api)
                with self.assertRaises(OSError):
                    self.publish(api)
                classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_initial_nonempty_and_metadata_drift_fail_closed(self) -> None:
        cases = (
            ("initial-size", 0, "size", 1),
            ("identity", 1, "identity", bytes(reversed(range(16)))),
            ("attributes", 1, "attributes", receipt.FILE_ATTRIBUTE_READONLY),
            ("links", 1, "links", 2),
            ("size", 1, "size", len(PAYLOAD) + 1),
        )
        for label, phase, field, value in cases:
            with self.subTest(label=label):
                api = FakeKernel32()
                api.metadata_overrides[phase][field] = value
                with self.assertRaises(OSError):
                    self.publish(api)

    def test_post_rename_exact_read_and_metadata_drift_are_detected_without_disposition(self) -> None:
        def bytes_drift(api: FakeKernel32) -> None:
            api.read_sequences = [PAYLOAD, b"X" + PAYLOAD[1:]]

        def identity_drift(api: FakeKernel32) -> None:
            api.metadata_overrides[2]["identity"] = b"z" * 16

        def attributes_drift(api: FakeKernel32) -> None:
            api.metadata_overrides[2]["attributes"] = receipt.FILE_ATTRIBUTE_READONLY

        def links_drift(api: FakeKernel32) -> None:
            api.metadata_overrides[2]["links"] = 2

        def size_drift(api: FakeKernel32) -> None:
            api.metadata_overrides[2]["size"] = len(PAYLOAD) + 1

        for label, configure in (
            ("bytes", bytes_drift),
            ("identity", identity_drift),
            ("attributes", attributes_drift),
            ("links", links_drift),
            ("size", size_drift),
        ):
            with self.subTest(label=label):
                api = FakeKernel32()
                configure(api)
                with self.assertRaises(OSError) as caught:
                    self.publish(api)
                outcome = receipt.outcome_from_error(caught.exception)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertEqual(outcome.state, "published")
                classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)

    def test_second_and_third_pass_api_failures_report_exact_phase(self) -> None:
        for info_class in (receipt.FILE_BASIC_INFO, receipt.FILE_STANDARD_INFO, receipt.FILE_ID_INFO):
            for pass_number, expected_state, disposition in (
                (2, None, True),
                (3, "published", False),
            ):
                with self.subTest(info_class=info_class, pass_number=pass_number):
                    failure = KeyboardInterrupt(f"info-{info_class}-{pass_number}")
                    api = FakeKernel32()
                    api.info_failure_at = (info_class, pass_number, failure)
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        self.publish(api)
                    self.assertIs(caught.exception, failure)
                    outcome = receipt.outcome_from_error(failure)
                    self.assertEqual(None if outcome is None else outcome.state, expected_state)
                    classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                    self.assertEqual(receipt.FILE_DISPOSITION_INFO in classes, disposition)

        for seek_index, expected_state, disposition in ((0, None, True), (1, "published", False)):
            with self.subTest(read_pass=seek_index + 1):
                failure = SystemExit(f"read-{seek_index}")
                api = FakeKernel32()
                api.read_failure_seek = (seek_index, failure)
                with self.assertRaises(SystemExit) as caught:
                    self.publish(api)
                self.assertIs(caught.exception, failure)
                outcome = receipt.outcome_from_error(failure)
                self.assertEqual(None if outcome is None else outcome.state, expected_state)
                classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertEqual(receipt.FILE_DISPOSITION_INFO in classes, disposition)

    def test_create_new_collision_codes_are_retryable_file_exists(self) -> None:
        for code in (receipt.ERROR_FILE_EXISTS, receipt.ERROR_ALREADY_EXISTS):
            api = FakeKernel32({"NtCreateFile": False})
            api.error = code
            with self.subTest(code=code), self.assertRaises(FileExistsError) as caught:
                self.publish(api)
            self.assertEqual(caught.exception.errno, code)

    def test_definite_negative_rename_disposes_but_raised_rename_is_unknown(self) -> None:
        api = FakeKernel32({"Rename": False})
        api.error = 5
        with self.assertRaises(receipt._DefiniteRenameError):
            self.publish(api)
        self.assertIn(
            receipt.FILE_DISPOSITION_INFO,
            [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"],
        )
        for failure in (
            OSError("rename"),
            FileExistsError("raised collision"),
            KeyboardInterrupt("rename"),
            SystemExit("rename"),
        ):
            with self.subTest(failure=type(failure).__name__):
                api = FakeKernel32({"Rename": failure, "CloseHandle": OSError("close")})
                with self.assertRaises(type(failure)) as caught:
                    self.publish(api)
                self.assertIs(caught.exception, failure)
                outcome = receipt.outcome_from_error(failure)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertEqual(outcome.state, "unknown")
                self.assertEqual(outcome.receipt.file_id, bytes(range(16)))
                classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)
                self.assertIn("Could not close", "\n".join(getattr(failure, "__notes__", [])))

    def test_raw_collision_status_is_authenticated_before_dos_code_mapping(self) -> None:
        api = FakeKernel32()
        api.rename_status = receipt.STATUS_OBJECT_NAME_COLLISION
        api.error = 5

        with self.assertRaises(receipt._DefiniteRenameCollision) as caught:
            self.publish(api)

        self.assertTrue(receipt.is_internal_definite_rename_collision(caught.exception))
        self.assertIn(
            receipt.FILE_DISPOSITION_INFO,
            [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"],
        )

    def test_nonfinal_return_and_nonzero_completion_keep_unknown_outcome(self) -> None:
        cases = (
            ("nonfinal-return", receipt.STATUS_PENDING, 0),
            ("failing-completion", 0, 0xC0000022),
            ("nonfinal-completion", 0, receipt.STATUS_PENDING),
        )
        for label, status, completion_status in cases:
            with self.subTest(label=label):
                api = FakeKernel32()
                api.rename_status = status
                api.rename_completion_status = completion_status

                with self.assertRaises(OSError) as caught:
                    self.publish(api)

                outcome = receipt.outcome_from_error(caught.exception)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertEqual(outcome.state, "unknown")
                self.assertFalse(api.rename_succeeded)
                self.assertEqual(
                    sum(name == "NtSetInformationFile" for name, _args in api.calls),
                    1,
                )
                self.assertNotIn(
                    receipt.FILE_DISPOSITION_INFO,
                    [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"],
                )

    def test_trace_boundaries_never_dispose_unknown_or_published_rename(self) -> None:
        publisher_code = receipt.publish_windows_receipt.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.publish_windows_receipt)
        rename_index = next(index for index, line in enumerate(source_lines) if line.lstrip().startswith("_rename("))
        publish_index = next(
            index for index, line in enumerate(source_lines) if line.strip() == 'publication_lease.phase = "published"'
        )
        post_confirmation_index = next(
            index
            for index, line in enumerate(source_lines)
            if index > publish_index and line.lstrip().startswith("if _read_exact(")
        )
        boundary_lines = {
            "pre-call": source_start + rename_index,
            "post-native": source_start + publish_index,
            "post-confirmation": source_start + post_confirmation_index,
        }
        for boundary in ("pre-call", "post-native", "post-confirmation"):
            with self.subTest(boundary=boundary):
                api = FakeKernel32()
                interruption = KeyboardInterrupt(boundary)
                triggered = False

                def trace(frame: Any, event: str, _argument: object) -> Any:
                    nonlocal triggered
                    if (
                        not triggered
                        and event == "line"
                        and frame.f_code is publisher_code
                        and frame.f_lineno == boundary_lines[boundary]
                    ):
                        triggered = True
                        raise interruption
                    return trace

                previous = sys.gettrace()
                try:
                    sys.settrace(trace)
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        self.publish(api)
                finally:
                    sys.settrace(previous)

                self.assertIs(caught.exception, interruption)
                outcome = receipt.outcome_from_error(interruption)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertEqual(outcome.state, "published" if boundary == "post-confirmation" else "unknown")
                rename_calls = [args for name, args in api.calls if name == "NtSetInformationFile"]
                self.assertEqual(len(rename_calls), 0 if boundary == "pre-call" else 1)
                classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
                self.assertNotIn(receipt.FILE_DISPOSITION_INFO, classes)
                self.assertEqual(api.calls[-1][0], "CloseHandle")

    def test_trace_after_create_acquisition_disposes_and_closes_tracked_handle(self) -> None:
        api = FakeKernel32()
        interruption = KeyboardInterrupt("post-create acquisition")
        publisher_code = receipt.publish_windows_receipt.__code__
        source_lines, source_start = inspect.getsourcelines(receipt.publish_windows_receipt)
        ownership_line = source_start + next(
            index for index, line in enumerate(source_lines) if line.strip() == "handle = lease.handle"
        )
        triggered = False

        def trace(frame: Any, event: str, _argument: object) -> Any:
            nonlocal triggered
            if (
                event == "line"
                and frame.f_code is publisher_code
                and not triggered
                and frame.f_lineno == ownership_line
                and api.create_succeeded
            ):
                triggered = True
                raise interruption
            return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.publish(api)
        finally:
            sys.settrace(previous)
        self.assertIs(caught.exception, interruption)
        classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertIn(receipt.FILE_DISPOSITION_INFO, classes)
        self.assertEqual(api.calls[-1][0], "CloseHandle")

    def test_both_collision_codes_map_to_file_exists(self) -> None:
        for code in (receipt.ERROR_FILE_EXISTS, receipt.ERROR_ALREADY_EXISTS):
            with self.subTest(code=code):
                api = FakeKernel32({"Rename": False})
                api.error = code
                with self.assertRaises(FileExistsError) as caught:
                    self.publish(api)
                self.assertEqual(caught.exception.errno, code)

    def test_cleanup_failures_preserve_primary_and_order_notes(self) -> None:
        for primary_factory in (
            lambda: OSError("write"),
            lambda: KeyboardInterrupt("write"),
            lambda: SystemExit("write"),
        ):
            with self.subTest(primary=primary_factory().__class__.__name__):
                primary = primary_factory()
                disposition = KeyboardInterrupt("dispose")
                close = SystemExit("close")
                api = FakeKernel32({"WriteFile": primary, "Disposition": disposition, "CloseHandle": close})
                with self.assertRaises(BaseException) as caught:
                    self.publish(api)
                self.assertIs(caught.exception, primary)
                self.assertEqual(
                    getattr(primary, "__notes__", []),
                    [
                        "Could not mark receipt staging file for deletion: dispose",
                        "Could not close receipt staging handle: close",
                    ],
                )
                self.assertEqual(receipt.cleanup_failures_from_error(primary), (disposition, close))

    def test_close_call_return_gap_preserves_active_primary(self) -> None:
        primary = RuntimeError("write")
        interruption = KeyboardInterrupt("between close return and result assignment")
        api = FakeKernel32({"WriteFile": primary})
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
                self.publish(api)

        self.assertTrue(triggered)
        self.assertIs(caught.exception, primary)
        self.assertEqual(receipt.cleanup_failures_from_error(primary), (interruption,))
        self.assertIn(
            "Could not close receipt staging handle: between close return and result assignment",
            getattr(primary, "__notes__", ()),
        )
        self.assertEqual(sum(name == "CloseHandle" for name, _args in api.calls), 1)

    def test_cleanup_and_definite_rename_evidence_rejects_spoofed_attributes(self) -> None:
        spoof = receipt._DefiniteRenameCollision(receipt.ERROR_FILE_EXISTS, "spoof")
        setattr(spoof, "_windows_receipt_cleanup_failures", (KeyboardInterrupt("spoof"),))
        setattr(spoof, "_windows_receipt_cleanup_record", (KeyboardInterrupt("spoof"),))
        setattr(spoof, "_windows_receipt_definite_provenance", object())

        self.assertEqual(receipt.cleanup_failures_from_error(spoof), ())
        self.assertFalse(receipt.is_internal_definite_rename_collision(spoof))

    def test_post_rename_close_failure_does_not_dispose_public_name(self) -> None:
        close = OSError("close")
        api = FakeKernel32({"CloseHandle": close})
        with self.assertRaises(OSError) as caught:
            self.publish(api)
        self.assertIs(caught.exception, close)
        info_classes = [args[1] for name, args in api.calls if name == "SetFileInformationByHandle"]
        self.assertNotIn(receipt.FILE_DISPOSITION_INFO, info_classes)


if __name__ == "__main__":
    unittest.main()
