"""Required real NTFS receipt cases, using native calls through the public API."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path

from scripts._anchored_output import (
    AnchoredOutputError,
    publish_identical_receipt_bytes,
)
from tests.windows_receipt_native_support import (
    WINDOWS_AMD64_ABI,
    BasicInformation,
    FileIdentity,
    IoStatus,
    NativeCall,
    NativeCapture,
    NativeWindows,
    ObjectAttributes,
    ObservedFunction,
    RenameInformation,
    StandardInformation,
    create_junction,
    native_abi_layout,
    nt_name,
    pointer,
    windows_ctypes,
)

PAYLOAD = b'{"native":"NTFS"}\n'


@unittest.skipUnless(sys.platform == "win32", "requires native NTFS receipts")
class TestNativeReceiptsWindows(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "receipt.json"
        self.native = NativeWindows()
        self.assertEqual(self.native.filesystem(self.root), "NTFS")

    def _assert_closed(self, capture: NativeCapture) -> None:
        self.assertTrue(capture.handles)
        for handle in capture.handles:
            self.assertTrue(self.native.handle_is_closed(handle), f"retained handle still live: {handle}")

    def _assert_sharing_denial(self, source: Path, destination: Path) -> None:
        with self.assertRaises(OSError) as raised:
            os.replace(source, destination)
        self.assertEqual(raised.exception.errno, errno.EACCES)

    def _assert_native_call_abi(self, call: NativeCall) -> None:
        arguments = call.arguments
        self.assertIsNotNone(call.argtypes)
        if call.name == "CreateFileW":
            self.assertEqual(call.argtypes, (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p))
            self.assertEqual(call.restype, ctypes.c_void_p)
            self.assertEqual(arguments[1], 0xA0)
            self.assertEqual(arguments[2], 3)
            self.assertEqual(arguments[4], 3)
            self.assertEqual(arguments[5], 0x02200000)
            return
        elif call.name == "NtCreateFile":
            self._assert_nt_open(call)
            return
        elif call.name == "NtSetInformationFile":
            self._assert_nt_rename(call)
            return
        if call.name == "GetFileInformationByHandleEx":
            self.assertEqual(call.argtypes, (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32))
            self.assertEqual(call.restype, ctypes.c_int)
            sizes = {0: ctypes.sizeof(BasicInformation), 1: ctypes.sizeof(StandardInformation), 18: ctypes.sizeof(FileIdentity)}
            information = arguments[1]
            assert isinstance(information, int)
            self.assertEqual(arguments[3], sizes[information])
            self.assertEqual(call.result, 1)
        elif call.name == "GetFileType":
            self.assertEqual(call.argtypes, (ctypes.c_void_p,))
            self.assertEqual(call.restype, ctypes.c_uint32)
            self.assertEqual(call.result, 1)
        else:
            self._assert_native_io(call)

    def _assert_native_io(self, call: NativeCall) -> None:
        expected = (ctypes.c_void_p,) if call.name == "FlushFileBuffers" else (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        )
        self.assertEqual(call.argtypes, expected)
        self.assertEqual(call.restype, ctypes.c_int)
        self.assertEqual(call.result, 1)
        if call.name in {"ReadFile", "WriteFile"}:
            count = ctypes.cast(pointer(call.arguments[3]), ctypes.POINTER(ctypes.c_uint32)).contents.value
            size = call.arguments[2]
            assert isinstance(size, int)
            self.assertLessEqual(count, size)
            if call.name == "WriteFile":
                self.assertEqual(ctypes.string_at(pointer(call.arguments[1]), count), PAYLOAD)

    def _assert_nt_open(self, call: NativeCall) -> None:
        arguments = call.arguments
        signature = call.argtypes
        assert signature is not None
        self.assertEqual(len(signature), 11)
        self.assertEqual(signature[0], ctypes.POINTER(ctypes.c_void_p))
        self.assertEqual(signature[4], ctypes.POINTER(ctypes.c_int64))
        self.assertEqual(signature[9], ctypes.c_void_p)
        self.assertEqual([signature[index] for index in (1, 5, 6, 7, 8, 10)], [ctypes.c_uint32] * 6)
        self.assertEqual([ctypes.sizeof(pointer(signature[index])) for index in (2, 3)], [8, 8])
        self.assertEqual(call.restype, ctypes.c_int32)
        attributes = ctypes.cast(pointer(arguments[2]), ctypes.POINTER(ObjectAttributes)).contents
        self.assertEqual(attributes.length, 48)
        self.assertEqual(attributes.attributes, 0x40)
        name = attributes.name.contents
        self.assertEqual(name.length % 2, 0)
        self.assertEqual(name.maximum, name.length + 2)
        self.assertEqual(ctypes.string_at(name.buffer + name.length, 2), b"\0\0")
        options = arguments[8]
        self.assertIsInstance(options, int)
        assert isinstance(options, int)
        self.assertTrue(options & 0x00200000)
        self.assertEqual(arguments[6], 3 if options & 1 else 1)
        if not nt_name(arguments).startswith("\\??\\"):
            self.assertIsNotNone(attributes.root)
        if call.result == 0:
            completion = ctypes.cast(pointer(arguments[3]), ctypes.POINTER(IoStatus)).contents
            self.assertIsNone(completion.status)
            self.assertIn(completion.information, {1, 2})

    def _assert_nt_rename(self, call: NativeCall) -> None:
        signature = call.argtypes
        assert signature is not None
        self.assertEqual(len(signature), 5)
        self.assertEqual((signature[0], signature[2], signature[3], signature[4]),
                         (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32))
        self.assertEqual(ctypes.sizeof(pointer(signature[1])), 8)
        self.assertEqual(call.restype, ctypes.c_int32)
        self.assertEqual(call.result, 0)
        completion = ctypes.cast(pointer(call.arguments[1]), ctypes.POINTER(IoStatus)).contents
        self.assertIsNone(completion.status)
        self.assertEqual(call.arguments[4], 10)
        rename = ctypes.cast(pointer(call.arguments[2]), ctypes.POINTER(RenameInformation)).contents
        self.assertIsNone(rename.root)
        self.assertEqual(rename.replace, 0)
        self.assertEqual(call.arguments[3], ctypes.sizeof(RenameInformation) + rename.length)
        encoded = ctypes.string_at(ctypes.addressof(rename) + RenameInformation.name.offset, rename.length)
        self.assertEqual(encoded.decode("utf-16-le"), self.path.name)

    def test_native_abi_publication_and_identical_identity(self) -> None:
        self.assertEqual(native_abi_layout(), WINDOWS_AMD64_ABI)
        with NativeCapture(after=self._assert_native_call_abi) as capture:
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(capture)
        observed = {call.name for call in capture.calls}
        self.assertEqual(observed, {
            "CreateFileW", "NtCreateFile", "NtSetInformationFile", "WriteFile", "ReadFile",
            "FlushFileBuffers", "GetFileInformationByHandleEx", "GetFileType",
        })
        first = self.native.metadata(self.path)
        self.assertEqual((first.links, first.size, first.directory, first.file_type), (1, len(PAYLOAD), 0, 1))
        self.assertEqual(first.attributes & (0x400 | 0x10 | 1), 0)
        self.assertNotEqual(first.volume, 0)
        self.assertNotEqual(first.file_id, bytes(16))
        with NativeCapture() as repeated:
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(repeated)
        self.assertEqual(self.native.metadata(self.path), first)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_different_content_and_hardlinks_are_rejected(self) -> None:
        publish_identical_receipt_bytes(self.path, PAYLOAD)
        first = self.native.metadata(self.path)
        with NativeCapture() as conflict, self.assertRaises(AnchoredOutputError):
            publish_identical_receipt_bytes(self.path, b"different")
        self._assert_closed(conflict)
        self.assertEqual(self.native.metadata(self.path), first)
        os.link(self.path, self.root / "hardlink")
        with NativeCapture() as linked, self.assertRaises(AnchoredOutputError):
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(linked)
        self.assertEqual(self.native.metadata(self.path).links, 2)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)

    def test_junction_directory_and_reserved_targets_fail_closed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        junction = self.root / "junction"
        create_junction(junction, outside)
        self.assertTrue(self.native.metadata(junction).attributes & 0x400)
        for target in (junction / "receipt.json", junction, outside, self.root / "NUL"):
            with self.subTest(target=target), self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(target, PAYLOAD)
        self.assertEqual(list(outside.iterdir()), [])

    def test_retained_ancestors_deny_relocation_then_close(self) -> None:
        parent = self.root / "parent"
        parent.mkdir()
        attempted: list[Path] = []

        def before(name: str, _arguments: tuple[object, ...]) -> None:
            if name == "WriteFile" and not attempted:
                for source in (parent, self.root):
                    attempted.append(source)
                    self._assert_sharing_denial(source, source.with_name(source.name + "-moved"))

        with NativeCapture(before=before) as capture:
            publish_identical_receipt_bytes(parent / "receipt.json", PAYLOAD)
        self._assert_closed(capture)
        self.assertEqual(attempted, [parent, self.root])
        for source in attempted:
            moved = source.with_name(source.name + "-moved")
            source.rename(moved)
            moved.rename(source)

    def test_existing_target_is_pinned_during_identical_comparison(self) -> None:
        publish_identical_receipt_bytes(self.path, PAYLOAD)
        original_id = self.native.metadata(self.path).file_id
        attacker = self.root / "attacker"
        attacker.write_bytes(b"attacker")
        linked = False
        attempted = False

        def before(name: str, _arguments: tuple[object, ...]) -> None:
            nonlocal linked, attempted
            if name != "ReadFile" or attempted:
                return
            attempted = True
            self._assert_sharing_denial(attacker, self.path)
            self._assert_sharing_denial(self.path, self.root / "renamed")
            with self.assertRaises(OSError) as deletion:
                self.path.unlink()
            self.assertEqual(deletion.exception.errno, errno.EACCES)
            with self.assertRaises(OSError):
                self.path.write_bytes(b"attacker")
            try:
                os.link(self.path, self.root / "new-link")
            except OSError:
                return
            linked = True

        with NativeCapture(before=before) as capture:
            try:
                publish_identical_receipt_bytes(self.path, PAYLOAD)
            except AnchoredOutputError:
                self.assertTrue(linked)
            else:
                self.assertFalse(linked)
        self._assert_closed(capture)
        self.assertTrue(attempted)
        self.assertEqual(self.native.metadata(self.path).file_id, original_id)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        self.assertEqual(attacker.read_bytes(), b"attacker")

    def test_stage_substitution_is_denied(self) -> None:
        attacker = self.root / "attacker"
        attacker.write_bytes(b"attacker")
        attempts: list[Path] = []

        def after(call: NativeCall) -> None:
            if call.name == "WriteFile" and not attempts:
                stages = list(self.root.glob(".*.tmp"))
                self.assertEqual(len(stages), 1)
                attempts.extend(stages)
                self._assert_sharing_denial(attacker, stages[0])
                self._assert_sharing_denial(stages[0], self.root / "substituted")
                with self.assertRaises(OSError) as deletion:
                    stages[0].unlink()
                self.assertEqual(deletion.exception.errno, errno.EACCES)

        with NativeCapture(after=after) as capture:
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(capture)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        self.assertEqual(attacker.read_bytes(), b"attacker")

    def test_concurrent_target_winner_is_not_overwritten(self) -> None:
        winner_ids: list[bytes] = []

        def after(call: NativeCall) -> None:
            if call.name == "WriteFile" and not winner_ids:
                self.path.write_bytes(b"concurrent winner")
                winner_ids.append(self.native.metadata(self.path).file_id)

        with NativeCapture(after=after) as capture, self.assertRaises(AnchoredOutputError):
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(capture)
        self.assertEqual(self.native.metadata(self.path).file_id, winner_ids[0])
        self.assertEqual(self.path.read_bytes(), b"concurrent winner")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_long_unicode_path_publishes_and_reuses(self) -> None:
        path = self.root
        for index in range(7):
            path /= f"{index}-" + "ž日本" * 16
        path.mkdir(parents=True)
        path /= "доказ-証明.json"
        self.assertGreater(len(str(path)), 260)
        with NativeCapture() as capture:
            publish_identical_receipt_bytes(path, PAYLOAD)
        self._assert_closed(capture)
        first = self.native.metadata(path)
        publish_identical_receipt_bytes(path, PAYLOAD)
        self.assertEqual(self.native.metadata(path), first)

    def test_post_write_failure_cleans_stage_and_handles(self) -> None:
        def after(call: NativeCall) -> None:
            if call.name == "WriteFile":
                raise OSError("injected after native write")

        with NativeCapture(after=after) as capture, self.assertRaisesRegex(OSError, "after native write"):
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(capture)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_post_rename_failure_retains_published_identity(self) -> None:
        staged_ids: list[bytes] = []

        def after(call: NativeCall) -> None:
            if call.name == "WriteFile":
                stages = list(self.root.glob(".*.tmp"))
                self.assertEqual(len(stages), 1)
                staged_ids.append(self.native.metadata(stages[0]).file_id)
            if call.name == "NtSetInformationFile" and call.result == 0:
                raise RuntimeError("injected after native rename")

        with NativeCapture(after=after) as capture, self.assertRaisesRegex(RuntimeError, "after native rename"):
            publish_identical_receipt_bytes(self.path, PAYLOAD)
        self._assert_closed(capture)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        published = self.native.metadata(self.path)
        self.assertEqual(published.links, 1)
        self.assertEqual(staged_ids, [published.file_id])
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_repeated_publication_does_not_leak_handles(self) -> None:
        publish_identical_receipt_bytes(self.path, PAYLOAD)
        count = self.native.handle_count()
        for _index in range(20):
            with NativeCapture() as capture:
                publish_identical_receipt_bytes(self.path, PAYLOAD)
            self._assert_closed(capture)
        self.assertEqual(self.native.handle_count(), count)

    def test_observers_preserve_ctypes_last_error_and_native_close(self) -> None:
        def before(_name: str, _arguments: tuple[object, ...]) -> None:
            windows_ctypes().set_last_error(1234)

        def after(_call: NativeCall) -> None:
            windows_ctypes().set_last_error(5678)

        with NativeCapture(before=before, after=after) as capture:
            observed = windows_ctypes().WinDLL("kernel32", use_last_error=True)
            observed.GetFileType.argtypes = (ctypes.c_void_p,)
            observed.GetFileType.restype = ctypes.c_uint32
            self.assertEqual(observed.GetFileType(None), 0)
            self.assertEqual(windows_ctypes().get_last_error(), 6)
            windows_ctypes().set_last_error(4321)
            self.assertEqual(self.native.api.GetCurrentProcess(), ctypes.c_void_p(-1).value)
            self.assertEqual(windows_ctypes().get_last_error(), 4321)
            delegate = ObservedFunction(self.native.api.GetCurrentProcess, "GetCurrentProcess", capture)
            self.assertEqual(delegate(), ctypes.c_void_p(-1).value)
            self.assertEqual(windows_ctypes().get_last_error(), 4321)
        self.assertEqual(capture.calls[0].last_error, 6)
        self.assertEqual(
            ctypes.cast(pointer(observed.CloseHandle), ctypes.c_void_p).value,
            ctypes.cast(pointer(self.native.api.CloseHandle), ctypes.c_void_p).value,
        )
        self._assert_hook_failures_restore_error()

    def _assert_hook_failures_restore_error(self) -> None:
        def fail_before(_name: str, _arguments: tuple[object, ...]) -> None:
            windows_ctypes().set_last_error(7777)
            raise RuntimeError("before native call")

        def fail_after(_call: NativeCall) -> None:
            windows_ctypes().set_last_error(8888)
            raise RuntimeError("after native call")

        for before, after, calls in ((fail_before, None, 0), (None, fail_after, 1)):
            with NativeCapture(before=before, after=after) as capture:
                delegate = ObservedFunction(self.native.api.GetCurrentProcess, "GetCurrentProcess", capture)
                windows_ctypes().set_last_error(4321)
                with self.assertRaisesRegex(RuntimeError, "native call"):
                    delegate()
                self.assertEqual(windows_ctypes().get_last_error(), 4321)
                self.assertEqual(len(capture.calls), calls)
