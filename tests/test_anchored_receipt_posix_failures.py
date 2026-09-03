# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import tempfile
from typing import Any, cast
import unittest
from unittest import mock

from scripts import _anchored_output as anchored


PAYLOAD = b'{"status":"verified"}\n'


def _metadata(**changes: int) -> os.stat_result:
    values = {
        "st_dev": 11,
        "st_ino": 22,
        "st_mode": 0o100600,
        "st_uid": os.geteuid(),
        "st_nlink": 0,
        "st_size": len(PAYLOAD),
        "st_mtime_ns": 33,
        "st_ctime_ns": 44,
    }
    values.update(changes)
    return cast(os.stat_result, SimpleNamespace(**values))


class _NativeCall:
    argtypes: object = None
    restype: object = None

    def __init__(self, result: int) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *arguments: object) -> int:
        self.calls.append(arguments)
        result_type = self.restype
        checker = getattr(result_type, "_check_retval_", None)
        if callable(result_type) and callable(checker):
            checker(result_type(self.result))
        return self.result


def _retain_descriptor(descriptor: int):
    def open_read(_name: str, lease: anchored._PosixDescriptorLease) -> int:
        lease.descriptor_result = ctypes.c_int(descriptor)
        return descriptor

    return open_read


def _retain_stage(posix: Any, descriptor: int):
    stage = posix._PosixReceiptStage(descriptor=descriptor)

    def open_stage(
        _binding: object,
        _temporary_name: str,
        lease: Any,
    ) -> object:
        lease.descriptor.descriptor_result = ctypes.c_int(descriptor)
        lease.stage = stage
        return stage

    return stage, open_stage


class AnchoredReceiptPosixFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX receipt failure model")
        self.posix = anchored._posix_receipt_module()
        acl_patch = mock.patch.object(
            self.posix,
            "_darwin_descriptor_has_extended_acl",
            return_value=False,
        )
        acl_patch.start()
        self.addCleanup(acl_patch.stop)
        reader_acl_patch = mock.patch.object(
            anchored,
            "_darwin_descriptor_has_extended_acl",
            return_value=False,
        )
        reader_acl_patch.start()
        self.addCleanup(reader_acl_patch.stop)

    def test_canonical_receipt_requires_effective_user_ownership(self) -> None:
        wrong_owner = _metadata(st_uid=os.geteuid() + 1)
        with (
            mock.patch.object(self.posix.os, "fstat", return_value=wrong_owner),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            self.posix._validate_exact_receipt_descriptor(
                7,
                PAYLOAD,
                (wrong_owner.st_dev, wrong_owner.st_ino),
                expected_link_count=0,
                code="output-temporary-invalid",
            )
        self.assertEqual(raised.exception.code, "output-temporary-invalid")

        binding = SimpleNamespace(
            parent=Path("."),
            stat=mock.Mock(return_value=_metadata(st_nlink=1, st_uid=os.geteuid() + 1)),
        )
        with self.assertRaises(anchored.AnchoredOutputError) as public_raised:
            anchored._read_exact_receipt(
                cast(anchored.OutputParentBinding, binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
            )
        self.assertEqual(public_raised.exception.code, "output-existing-invalid")

    def test_retained_validation_rejects_bounded_read_and_metadata_drift(self) -> None:
        cases = (
            ("early EOF", (PAYLOAD[:-1], b""), _metadata(), _metadata()),
            ("extra byte", (PAYLOAD + b"x",), _metadata(), _metadata()),
            ("mismatch", (b"different\n", b""), _metadata(), _metadata()),
            ("identity drift", (PAYLOAD, b""), _metadata(), _metadata(st_ino=23)),
            ("metadata drift", (PAYLOAD, b""), _metadata(), _metadata(st_mtime_ns=34)),
            ("ownership drift", (PAYLOAD, b""), _metadata(), _metadata(st_uid=os.geteuid() + 1)),
        )
        for label, reads, before, after in cases:
            with self.subTest(label=label):
                with (
                    mock.patch.object(self.posix.os, "fstat", side_effect=(before, after)),
                    mock.patch.object(self.posix.os, "lseek"),
                    mock.patch.object(self.posix.os, "read", side_effect=reads) as read,
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    self.posix._validate_exact_receipt_descriptor(
                        7,
                        PAYLOAD,
                        (11, 22),
                        expected_link_count=0,
                        code="output-temporary-invalid",
                    )
                self.assertEqual(raised.exception.code, "output-temporary-invalid")
                self.assertLessEqual(read.call_count, 2)

    def test_public_validation_rejects_bounded_read_and_namespace_drift(self) -> None:
        stable = _metadata(st_nlink=1)
        cases = (
            ("early EOF", (PAYLOAD[:-1], b""), stable, stable, stable, "output-different"),
            ("extra byte", (PAYLOAD + b"x",), stable, stable, stable, "output-different"),
            ("mismatch", (b"different\n", b""), stable, stable, stable, "output-different"),
            (
                "descriptor drift",
                (PAYLOAD, b""),
                stable,
                _metadata(st_nlink=1, st_ino=23),
                stable,
                "output-changed",
            ),
            (
                "namespace drift",
                (PAYLOAD, b""),
                stable,
                stable,
                _metadata(st_nlink=1, st_ino=23),
                "output-changed",
            ),
        )
        for label, reads, before, opened_after, after, expected_code in cases:
            with self.subTest(label=label):
                close_operation = _NativeCall(0)
                binding = SimpleNamespace(
                    parent=Path("parent"),
                    stat=mock.Mock(side_effect=(before, after)),
                    open_read=mock.Mock(side_effect=_retain_descriptor(71)),
                    verify=mock.Mock(),
                )
                with (
                    mock.patch.object(anchored.os, "fstat", side_effect=(before, opened_after)),
                    mock.patch.object(anchored.os, "read", side_effect=reads) as read,
                    mock.patch.object(
                        anchored,
                        "_posix_libc",
                        return_value={"close": close_operation},
                    ),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored._read_exact_receipt(
                        cast(Any, binding),
                        "receipt.json",
                        PAYLOAD,
                        descriptor_lease=anchored._PosixDescriptorLease(),
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertLessEqual(read.call_count, 2)
                self.assertEqual(close_operation.calls, [(71,)])

    def test_namespace_shaped_reader_failures_have_stable_changed_code(self) -> None:
        stable = _metadata(st_nlink=1)
        for label, primary in (
            ("missing", FileNotFoundError(errno.ENOENT, "missing")),
            ("symlink race", OSError(errno.ELOOP, "symlink loop")),
        ):
            with self.subTest(label=label):
                primary.add_note("native namespace note")
                binding = SimpleNamespace(
                    parent=Path("parent"),
                    stat=mock.Mock(return_value=stable),
                    open_read=mock.Mock(side_effect=primary),
                )
                with self.assertRaises(anchored.AnchoredOutputError) as raised:
                    anchored._read_exact_receipt(
                        cast(Any, binding),
                        "receipt.json",
                        PAYLOAD,
                        descriptor_lease=anchored._PosixDescriptorLease(),
                    )
                self.assertEqual(raised.exception.code, "output-changed")
                self.assertIs(raised.exception.__cause__, primary)
                self.assertIn("native namespace note", getattr(raised.exception, "__notes__", ()))

        generic = OSError(errno.EIO, "read open")
        binding = SimpleNamespace(
            parent=Path("parent"),
            stat=mock.Mock(return_value=stable),
            open_read=mock.Mock(side_effect=generic),
        )
        with self.assertRaises(OSError) as raised:
            anchored._read_exact_receipt(
                cast(Any, binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
            )
        self.assertIs(raised.exception, generic)

    def test_final_namespace_and_contract_drift_remap_to_output_changed(self) -> None:
        stable = _metadata(st_nlink=1)
        close_operation = _NativeCall(0)
        missing = FileNotFoundError(errno.ENOENT, "missing after read")
        binding = SimpleNamespace(
            parent=Path("parent"),
            stat=mock.Mock(side_effect=(stable, missing)),
            open_read=mock.Mock(side_effect=_retain_descriptor(71)),
            verify=mock.Mock(),
        )
        with (
            mock.patch.object(anchored.os, "fstat", side_effect=(stable, stable)),
            mock.patch.object(anchored.os, "read", side_effect=(PAYLOAD, b"")),
            mock.patch.object(anchored, "_posix_libc", return_value={"close": close_operation}),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._read_exact_receipt(
                cast(Any, binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
                expected_identity=(11, 22),
            )
        self.assertEqual(raised.exception.code, "output-changed")
        self.assertIs(raised.exception.__cause__, missing)
        self.assertEqual(close_operation.calls, [(71,)])

        invalid = _metadata(st_nlink=1, st_mode=stat.S_IFREG | 0o644)
        invalid_binding = SimpleNamespace(parent=Path("parent"), stat=mock.Mock(return_value=invalid))
        with self.assertRaises(anchored.AnchoredOutputError) as invalid_raised:
            anchored._read_exact_receipt(
                cast(Any, invalid_binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
                expected_identity=(11, 22),
            )
        self.assertEqual(invalid_raised.exception.code, "output-changed")

        different_close = _NativeCall(0)
        different_binding = SimpleNamespace(
            parent=Path("parent"),
            stat=mock.Mock(side_effect=(stable, stable)),
            open_read=mock.Mock(side_effect=_retain_descriptor(72)),
            verify=mock.Mock(),
        )
        with (
            mock.patch.object(anchored.os, "fstat", side_effect=(stable, stable)),
            mock.patch.object(anchored.os, "read", side_effect=(b"different\n", b"")),
            mock.patch.object(anchored, "_posix_libc", return_value={"close": different_close}),
            self.assertRaises(anchored.AnchoredOutputError) as different_raised,
        ):
            anchored._read_exact_receipt(
                cast(Any, different_binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
                expected_identity=(11, 22),
            )
        self.assertEqual(different_raised.exception.code, "output-changed")
        self.assertEqual(different_close.calls, [(72,)])

    def test_darwin_public_open_namespace_failure_has_stable_changed_code(self) -> None:
        primary = OSError(errno.ELOOP, "public name became a symlink")
        primary.add_note("public open note")
        binding = SimpleNamespace(
            parent=Path("parent"),
            leaf="receipt.json",
            open_read=mock.Mock(side_effect=primary),
        )
        with self.assertRaises(anchored.AnchoredOutputError) as raised:
            self.posix._sync_posix_public_descriptor(
                binding,
                PAYLOAD,
                (11, 22),
                anchored._PosixDescriptorLease(),
            )
        self.assertEqual(raised.exception.code, "output-changed")
        self.assertIs(raised.exception.__cause__, primary)
        self.assertIn("public open note", getattr(raised.exception, "__notes__", ()))

    def test_darwin_public_descriptor_validation_uses_changed_code(self) -> None:
        binding = SimpleNamespace(
            parent=Path("parent"),
            leaf="receipt.json",
            open_read=mock.Mock(side_effect=_retain_descriptor(71)),
        )
        close_operation = _NativeCall(0)
        with (
            mock.patch.object(self.posix, "_validate_exact_receipt_descriptor") as validate,
            mock.patch.object(self.posix.os, "fsync"),
            mock.patch.object(anchored, "_posix_libc", return_value={"close": close_operation}),
        ):
            self.posix._sync_posix_public_descriptor(
                binding,
                PAYLOAD,
                (11, 22),
                anchored._PosixDescriptorLease(),
            )
        validate.assert_called_once_with(
            71,
            PAYLOAD,
            (11, 22),
            expected_link_count=1,
            code="output-changed",
        )
        self.assertEqual(close_operation.calls, [(71,)])

    def test_native_publication_classifies_collision_unavailable_and_io_error(self) -> None:
        cases = (
            ("linux", errno.EEXIST, FileExistsError),
            ("linux", errno.EXDEV, anchored.AnchoredOutputError),
            ("darwin", errno.EINVAL, anchored.AnchoredOutputError),
            ("darwin", errno.EIO, OSError),
        )
        for platform, error_number, expected in cases:
            with self.subTest(platform=platform, error_number=error_number):
                operation = _NativeCall(-1)
                library = SimpleNamespace(linkat=operation, renameatx_np=operation)
                stage_lease = self.posix._PosixReceiptStageLease(
                    anchored._PosixDescriptorLease(),
                    anchored._PosixDescriptorLease(),
                    named_stage_name="stage.tmp",
                )
                stage = self.posix._PosixReceiptStage(
                    descriptor=7,
                    private_directory_descriptor=6,
                    named_stage_name="stage.tmp",
                )
                with (
                    mock.patch.object(self.posix.ctypes, "CDLL", return_value=library),
                    mock.patch.object(self.posix.ctypes, "get_errno", return_value=error_number),
                    mock.patch.object(self.posix.os, "stat", return_value=_metadata(st_nlink=1)),
                    mock.patch.object(self.posix.os, "fstat", return_value=_metadata(st_nlink=1)),
                    self.assertRaises(expected),
                ):
                    if platform == "linux":
                        self.posix._linux_link_receipt_descriptor(7, 8, "receipt.json")
                    else:
                        self.posix._darwin_rename_receipt_stage(
                            stage,
                            stage_lease,
                            8,
                            "receipt.json",
                        )
                self.assertEqual(len(operation.calls), 1)

    def test_public_descriptor_failures_close_once_and_preserve_primary(self) -> None:
        cases = (
            ("open", OSError("open")),
            ("validate", KeyboardInterrupt("read")),
            ("fsync", SystemExit(19)),
        )
        for boundary, primary in cases:
            with self.subTest(boundary=boundary):
                close_operation = _NativeCall(0)
                binding = SimpleNamespace(
                    leaf="receipt.json",
                    open_read=mock.Mock(side_effect=_retain_descriptor(71)),
                )
                if boundary == "open":
                    binding.open_read.side_effect = primary
                with (
                    mock.patch.object(
                        self.posix,
                        "_validate_exact_receipt_descriptor",
                        side_effect=primary if boundary == "validate" else None,
                    ),
                    mock.patch.object(
                        self.posix.os,
                        "fsync",
                        side_effect=primary if boundary == "fsync" else None,
                    ),
                    mock.patch.object(
                        anchored,
                        "_posix_libc",
                        return_value={"close": close_operation},
                    ),
                    self.assertRaises(type(primary)) as raised,
                ):
                    self.posix._sync_posix_public_descriptor(
                        binding,
                        PAYLOAD,
                        (11, 22),
                        anchored._PosixDescriptorLease(),
                    )
                self.assertIs(raised.exception, primary)
                self.assertEqual(len(close_operation.calls), 0 if boundary == "open" else 1)

    def test_public_descriptor_primary_gets_close_failure_note(self) -> None:
        primary = KeyboardInterrupt("read")
        close_operation = _NativeCall(-1)
        binding = SimpleNamespace(
            leaf="receipt.json",
            open_read=mock.Mock(side_effect=_retain_descriptor(71)),
        )
        with (
            mock.patch.object(self.posix, "_validate_exact_receipt_descriptor", side_effect=primary),
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
            mock.patch.object(anchored.ctypes, "get_errno", return_value=29),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._sync_posix_public_descriptor(
                binding,
                PAYLOAD,
                (11, 22),
                anchored._PosixDescriptorLease(),
            )
        self.assertIs(raised.exception, primary)
        self.assertEqual(close_operation.calls, [(71,)])
        self.assertIn("29", "\n".join(getattr(primary, "__notes__", ())))

    def test_native_open_return_interrupt_is_owned_and_closed_once(self) -> None:
        stable = _metadata(st_nlink=1)
        interruption = KeyboardInterrupt("native open returned before Python assignment")
        triggered = False

        class _InterruptingNativeCall(_NativeCall):
            def __call__(self, *arguments: object) -> int:
                nonlocal triggered
                result = super().__call__(*arguments)
                if not triggered:
                    triggered = True
                    raise interruption
                return result

        open_operation = _InterruptingNativeCall(71)
        close_operation = _NativeCall(0)
        library = {"openat": open_operation, "close": close_operation}

        def open_read(
            name: str,
            lease: anchored._PosixDescriptorLease,
        ) -> int:
            return anchored._open_posix_descriptor(
                lease,
                name,
                os.O_RDONLY,
                dir_fd=8,
            )

        binding = SimpleNamespace(
            parent=Path("parent"),
            stat=mock.Mock(return_value=stable),
            open_read=open_read,
            verify=mock.Mock(),
        )

        with (
            mock.patch.object(anchored, "_posix_libc", return_value=library),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._read_exact_receipt(
                cast(Any, binding),
                "receipt.json",
                PAYLOAD,
                descriptor_lease=anchored._PosixDescriptorLease(),
            )
        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(len(open_operation.calls), 1)
        self.assertEqual(close_operation.calls, [(71,)])

    def test_native_close_result_survives_interrupt_without_reusing_descriptor(self) -> None:
        lease = anchored._PosixDescriptorLease(
            descriptor_result=ctypes.c_int(71),
        )
        close_operation = _NativeCall(-1)
        interruption = KeyboardInterrupt("native close returned before Python assignment")
        real_native_int_result = anchored._native_int_result
        triggered = False

        def interrupt_result_interpretation(value: object) -> int:
            nonlocal triggered
            if (
                not triggered
                and value is lease.close_result
                and lease.close_result is not anchored._POSIX_NATIVE_RESULT_PENDING
            ):
                triggered = True
                raise interruption
            return real_native_int_result(value)

        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
            mock.patch.object(anchored, "_native_int_result", interrupt_result_interpretation),
            mock.patch.object(anchored.ctypes, "get_errno", return_value=errno.EIO),
        ):
            observed = anchored._close_posix_descriptor_lease(
                lease,
                None,
                "test descriptor",
            )
        self.assertTrue(triggered)
        self.assertIs(observed, interruption)
        self.assertEqual(close_operation.calls, [(71,)])
        self.assertIsNone(lease.descriptor)
        self.assertIs(lease.close_result, anchored._POSIX_NATIVE_RESULT_PENDING)
        self.assertIn("Input/output error", "\n".join(getattr(interruption, "__notes__", ())))

    def test_retired_close_marker_is_normalized_before_lease_reuse(self) -> None:
        lease = anchored._PosixDescriptorLease(
            descriptor_result=ctypes.c_int(71),
        )
        open_operation = _NativeCall(72)
        close_operation = _NativeCall(0)
        interruption = KeyboardInterrupt("descriptor retired before close marker reset")
        triggered = False

        def interrupt_marker_reset(
            target: anchored._PosixDescriptorLease,
            name: str,
            value: object,
        ) -> None:
            nonlocal triggered
            if (
                not triggered
                and target is lease
                and name == "close_result"
                and value is anchored._POSIX_NATIVE_RESULT_PENDING
                and target.descriptor_result is None
                and target.close_result is not anchored._POSIX_NATIVE_RESULT_PENDING
            ):
                triggered = True
                raise interruption
            object.__setattr__(target, name, value)

        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"openat": open_operation, "close": close_operation},
            ),
            mock.patch.object(
                anchored._PosixDescriptorLease,
                "__setattr__",
                new=interrupt_marker_reset,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                lease.close()
            self.assertEqual(
                anchored._open_posix_descriptor(lease, "next", os.O_RDONLY, dir_fd=8),
                72,
            )
            lease.close()

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(close_operation.calls, [(71,), (72,)])
        self.assertIsNone(lease.descriptor)
        self.assertIs(lease.close_result, anchored._POSIX_NATIVE_RESULT_PENDING)

    def test_binding_retries_interrupted_child_before_closing_parent(self) -> None:
        root = anchored._PosixDescriptorLease(descriptor_result=ctypes.c_int(70))
        child = anchored._PosixDescriptorLease(descriptor_result=ctypes.c_int(71))
        binding = anchored.OutputParentBinding(
            checkout=Path("checkout"),
            parent=Path("parent"),
            leaf="receipt.json",
            strategy="posix-dir-fd",
            descriptors=(70, 71),
            descriptor_leases=(root, child),
        )
        interruption = KeyboardInterrupt("child close interrupted before effect")
        attempts: list[str] = []
        completed: list[str] = []

        def close_lease(lease: anchored._PosixDescriptorLease) -> None:
            label = "child" if lease is child else "root"
            attempts.append(label)
            if lease is child and attempts.count("child") == 1:
                raise interruption
            lease.descriptor_result = None
            completed.append(label)

        with mock.patch.object(anchored._PosixDescriptorLease, "close", new=close_lease):
            failures = binding.close()

        self.assertEqual(attempts, ["child", "child", "root"])
        self.assertEqual(completed, ["child", "root"])
        self.assertEqual(failures, (interruption,))
        self.assertTrue(binding.is_closed)

    def test_binding_retries_helper_boundary_before_moving_to_parent(self) -> None:
        root = anchored._PosixDescriptorLease(descriptor_result=ctypes.c_int(70))
        child = anchored._PosixDescriptorLease(descriptor_result=ctypes.c_int(71))
        binding = anchored.OutputParentBinding(
            checkout=Path("checkout"),
            parent=Path("parent"),
            leaf="receipt.json",
            strategy="posix-dir-fd",
            descriptors=(70, 71),
            descriptor_leases=(root, child),
        )
        interruption = KeyboardInterrupt("helper call interrupted before child close")
        real_helper = anchored._close_posix_descriptor_lease
        helper_attempts: list[str] = []
        completed: list[str] = []

        def interrupt_helper_once(
            lease: anchored._PosixDescriptorLease,
            primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            label = "child" if lease is child else "root"
            helper_attempts.append(label)
            if lease is child and helper_attempts.count("child") == 1:
                raise interruption
            return real_helper(lease, primary, context)

        def close_lease(lease: anchored._PosixDescriptorLease) -> None:
            completed.append("child" if lease is child else "root")
            lease.descriptor_result = None

        with (
            mock.patch.object(
                anchored,
                "_close_posix_descriptor_lease",
                side_effect=interrupt_helper_once,
            ),
            mock.patch.object(anchored._PosixDescriptorLease, "close", new=close_lease),
        ):
            failures = anchored._OutputParentBindingLease(binding).close()

        self.assertEqual(helper_attempts, ["child", "child", "root"])
        self.assertEqual(completed, ["child", "root"])
        self.assertEqual(failures, (interruption,))
        self.assertTrue(binding.is_closed)

    def test_receipt_reader_retries_cleanup_helper_boundary_without_leaking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            output = directory / "receipt.json"
            output.write_bytes(PAYLOAD)
            output.chmod(0o600)
            opened: list[int] = []

            def open_read(
                _name: str,
                lease: anchored._PosixDescriptorLease,
            ) -> int:
                descriptor = os.open(output, os.O_RDONLY)
                opened.append(descriptor)
                lease.descriptor_result = ctypes.c_int(descriptor)
                return descriptor

            def output_stat(_name: str) -> os.stat_result:
                return output.lstat()

            binding = SimpleNamespace(
                parent=directory,
                stat=output_stat,
                open_read=open_read,
                verify=lambda: None,
            )
            cleanup_interrupt = KeyboardInterrupt("reader cleanup helper boundary")
            real_helper = anchored._close_posix_descriptor_lease
            attempts = 0

            def interrupt_helper_once(
                lease: anchored._PosixDescriptorLease,
                primary: BaseException | None,
                context: str,
            ) -> BaseException | None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise cleanup_interrupt
                return real_helper(lease, primary, context)

            with (
                mock.patch.object(
                    anchored,
                    "_close_posix_descriptor_lease",
                    side_effect=interrupt_helper_once,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                anchored._read_exact_receipt(
                    cast(Any, binding),
                    output.name,
                    PAYLOAD,
                    descriptor_lease=anchored._PosixDescriptorLease(),
                )

            self.assertIs(raised.exception, cleanup_interrupt)
            self.assertEqual(attempts, 2)
            self.assertEqual(len(opened), 1)
            with self.assertRaises(OSError):
                os.fstat(opened[0])

    def test_stage_helper_return_interrupt_closes_retained_descriptor_once(self) -> None:
        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=FileNotFoundError),
            verify=mock.Mock(),
            sync=mock.Mock(),
            close=mock.Mock(return_value=()),
        )
        _stage, open_stage = _retain_stage(self.posix, 71)
        close_operation = _NativeCall(0)
        interruption = KeyboardInterrupt("stage returned before publisher assignment")
        triggered = False

        def open_stage_then_interrupt(
            parent_binding: object,
            temporary_name: str,
            stage_lease: Any,
        ) -> object:
            nonlocal triggered
            stage = open_stage(parent_binding, temporary_name, stage_lease)
            if not triggered:
                triggered = True
                raise interruption
            return stage

        with (
            mock.patch.object(self.posix.sys, "platform", "linux"),
            mock.patch.object(
                self.posix,
                "_open_posix_receipt_stage",
                side_effect=open_stage_then_interrupt,
            ),
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._publish_posix_receipt_bytes(
                Path("receipt.json"),
                PAYLOAD,
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )
        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(close_operation.calls, [(71,)])
        binding.close.assert_called_once_with()

    def test_collision_observes_exact_winner_and_never_unlinks_public_name(self) -> None:
        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=FileNotFoundError),
            verify=mock.Mock(),
            sync=mock.Mock(),
            close=mock.Mock(return_value=()),
        )
        source = _metadata()
        _stage, open_stage = _retain_stage(self.posix, 7)
        exact_identity = (55, 66)
        close_operation = _NativeCall(0)
        public_sync = mock.Mock()
        with (
            mock.patch.object(self.posix.sys, "platform", "linux"),
            mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
            mock.patch.object(self.posix.os, "fstat", return_value=source),
            mock.patch.object(self.posix, "_write_and_sync_retained_descriptor"),
            mock.patch.object(self.posix, "_validate_exact_receipt_descriptor"),
            mock.patch.object(self.posix, "_publish_posix_receipt_descriptor", side_effect=FileExistsError),
            mock.patch.object(self.posix, "_read_exact_receipt", return_value=exact_identity) as observe,
            mock.patch.object(self.posix, "_sync_posix_public_descriptor", public_sync),
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
        ):
            self.posix._publish_posix_receipt_bytes(
                Path("receipt.json"),
                PAYLOAD,
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )
        self.assertEqual(observe.call_count, 2)
        self.assertEqual(observe.call_args_list[0], mock.call(
            binding,
            "receipt.json",
            PAYLOAD,
            descriptor_lease=mock.ANY,
        ))
        public_sync.assert_called_once()
        binding.sync.assert_called_once_with()
        self.assertEqual(close_operation.calls, [(7,)])

    def test_successful_collision_promotes_control_flow_close_failure(self) -> None:
        ordinary_close = OSError("ordinary binding close")
        control_flow_close = KeyboardInterrupt("binding close interrupt")
        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=FileNotFoundError),
            verify=mock.Mock(),
            sync=mock.Mock(),
            close=mock.Mock(return_value=(ordinary_close, control_flow_close)),
        )
        _stage, open_stage = _retain_stage(self.posix, 7)
        close_operation = _NativeCall(0)
        with (
            mock.patch.object(self.posix.sys, "platform", "linux"),
            mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
            mock.patch.object(self.posix.os, "fstat", return_value=_metadata()),
            mock.patch.object(self.posix, "_write_and_sync_retained_descriptor"),
            mock.patch.object(self.posix, "_validate_exact_receipt_descriptor"),
            mock.patch.object(self.posix, "_publish_posix_receipt_descriptor", side_effect=FileExistsError),
            mock.patch.object(self.posix, "_read_exact_receipt", return_value=(55, 66)),
            mock.patch.object(self.posix, "_sync_posix_public_descriptor"),
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._publish_posix_receipt_bytes(
                Path("receipt.json"),
                PAYLOAD,
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )

        self.assertIs(raised.exception, control_flow_close)
        self.assertIn("ordinary binding close", "\n".join(getattr(control_flow_close, "__notes__", ())))

    def test_post_publication_parent_sync_failure_keeps_public_name_and_closes(self) -> None:
        primary = OSError(errno.EIO, "directory sync")
        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=FileNotFoundError),
            verify=mock.Mock(),
            sync=mock.Mock(side_effect=primary),
            close=mock.Mock(return_value=()),
        )
        source = _metadata()
        _stage, open_stage = _retain_stage(self.posix, 7)
        reads = mock.Mock(return_value=(11, 22))
        close_operation = _NativeCall(0)
        with (
            mock.patch.object(self.posix.sys, "platform", "linux"),
            mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
            mock.patch.object(self.posix.os, "fstat", return_value=source),
            mock.patch.object(self.posix, "_write_and_sync_retained_descriptor"),
            mock.patch.object(self.posix, "_validate_exact_receipt_descriptor") as validate,
            mock.patch.object(self.posix, "_publish_posix_receipt_descriptor"),
            mock.patch.object(self.posix, "_read_exact_receipt", reads),
            mock.patch.object(self.posix, "_sync_posix_public_descriptor"),
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"close": close_operation},
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._publish_posix_receipt_bytes(
                Path("receipt.json"),
                PAYLOAD,
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )
        self.assertIs(raised.exception, primary)
        self.assertGreaterEqual(reads.call_count, 2)
        self.assertEqual(
            [call.kwargs["code"] for call in validate.call_args_list],
            ["output-temporary-invalid", "output-changed"],
        )
        self.assertIn("left untouched", "\n".join(getattr(primary, "__notes__", ())))
        self.assertEqual(close_operation.calls, [(7,)])
        binding.close.assert_called_once_with()

    def test_effect_then_control_flow_still_runs_durability_pipeline(self) -> None:
        for platform, output_identity in (
            ("linux", (11, 22)),
            ("darwin", (33, 44)),
        ):
            with self.subTest(platform=platform):
                primary = KeyboardInterrupt(f"{platform} native publication returned before assignment")
                binding = SimpleNamespace(
                    leaf="receipt.json",
                    descriptors=(8,),
                    stat=mock.Mock(side_effect=(FileNotFoundError(), _metadata())),
                    verify=mock.Mock(),
                    sync=mock.Mock(),
                    close=mock.Mock(return_value=()),
                )
                source = _metadata()
                _stage, open_stage = _retain_stage(self.posix, 7)
                close_operation = _NativeCall(0)
                reads = mock.Mock(return_value=output_identity)
                public_sync = mock.Mock()
                with (
                    mock.patch.object(self.posix.sys, "platform", platform),
                    mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
                    mock.patch.object(self.posix.os, "fstat", return_value=source),
                    mock.patch.object(self.posix, "_write_and_sync_retained_descriptor"),
                    mock.patch.object(self.posix, "_validate_exact_receipt_descriptor") as validate,
                    mock.patch.object(
                        self.posix,
                        "_publish_posix_receipt_descriptor",
                        side_effect=primary,
                    ),
                    mock.patch.object(self.posix, "_read_exact_receipt", reads),
                    mock.patch.object(
                        self.posix,
                        "_sync_posix_public_descriptor",
                        public_sync,
                    ),
                    mock.patch.object(
                        anchored,
                        "_posix_libc",
                        return_value={"close": close_operation},
                    ),
                    self.assertRaises(KeyboardInterrupt) as raised,
                ):
                    self.posix._publish_posix_receipt_bytes(
                        Path("receipt.json"),
                        PAYLOAD,
                        binding,
                        self.posix._PosixReceiptPublicationLease(binding),
                    )

                self.assertIs(raised.exception, primary)
                self.assertEqual(
                    [call.kwargs["code"] for call in validate.call_args_list],
                    ["output-temporary-invalid"],
                )
                binding.sync.assert_called_once_with()
                self.assertEqual(reads.call_count, 2)
                public_sync.assert_called_once()
                self.assertEqual(close_operation.calls, [(7,)])
                binding.close.assert_called_once_with()

    def test_effect_then_file_exists_runs_durability_pipeline(self) -> None:
        for platform, output_identity in (
            ("linux", (11, 22)),
            ("darwin", (33, 44)),
        ):
            with self.subTest(platform=platform):
                binding = SimpleNamespace(
                    leaf="receipt.json",
                    descriptors=(8,),
                    stat=mock.Mock(side_effect=FileNotFoundError),
                    verify=mock.Mock(),
                    sync=mock.Mock(),
                    close=mock.Mock(return_value=()),
                )
                source = _metadata()
                _stage, open_stage = _retain_stage(self.posix, 7)
                close_operation = _NativeCall(0)
                reads = mock.Mock(return_value=output_identity)
                public_sync = mock.Mock()
                with (
                    mock.patch.object(self.posix.sys, "platform", platform),
                    mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
                    mock.patch.object(self.posix.os, "fstat", return_value=source),
                    mock.patch.object(self.posix, "_write_and_sync_retained_descriptor"),
                    mock.patch.object(self.posix, "_validate_exact_receipt_descriptor"),
                    mock.patch.object(
                        self.posix,
                        "_publish_posix_receipt_descriptor",
                        side_effect=FileExistsError("native call completed before exception"),
                    ),
                    mock.patch.object(self.posix, "_read_exact_receipt", reads),
                    mock.patch.object(
                        self.posix,
                        "_sync_posix_public_descriptor",
                        public_sync,
                    ),
                    mock.patch.object(
                        anchored,
                        "_posix_libc",
                        return_value={"close": close_operation},
                    ),
                ):
                    self.posix._publish_posix_receipt_bytes(
                        Path("receipt.json"),
                        PAYLOAD,
                        binding,
                        self.posix._PosixReceiptPublicationLease(binding),
                    )

                binding.sync.assert_called_once_with()
                self.assertEqual(reads.call_count, 2)
                public_sync.assert_called_once()
                self.assertEqual(close_operation.calls, [(7,)])
                binding.close.assert_called_once_with()

    def test_new_ancestor_sync_failure_prevents_publication_and_closes_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            os.chdir(temporary)
            real_open = anchored._open_posix_descriptor
            real_close = anchored._PosixDescriptorLease.close
            opened: list[int] = []
            closed: list[int] = []

            def record_open(
                descriptor_lease: anchored._PosixDescriptorLease,
                name: os.PathLike[str] | str,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = real_open(
                    descriptor_lease,
                    name,
                    flags,
                    mode,
                    dir_fd=dir_fd,
                )
                opened.append(descriptor)
                return descriptor

            def record_close(descriptor_lease: anchored._PosixDescriptorLease) -> None:
                descriptor = descriptor_lease.descriptor
                if descriptor is None:
                    return real_close(descriptor_lease)
                closed.append(descriptor)
                real_close(descriptor_lease)

            try:
                with (
                    mock.patch.object(anchored, "descriptor_relative_output_supported", return_value=True),
                    mock.patch.object(anchored, "_open_posix_descriptor", side_effect=record_open),
                    mock.patch.object(anchored._PosixDescriptorLease, "close", new=record_close),
                    mock.patch.object(anchored.os, "fsync", side_effect=OSError(errno.EIO, "ancestor sync")),
                ):
                    with self.assertRaises(anchored.AnchoredOutputError) as raised:
                        anchored.open_rooted_output_parent(
                            Path("new-parent/receipt.json"),
                            anchored._OutputParentBindingLease(),
                        )
                self.assertEqual(raised.exception.code, "output-parent-invalid")
                self.assertFalse(Path("new-parent/receipt.json").exists())
                self.assertTrue(opened)
                self.assertEqual(closed, list(reversed(opened)))
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
