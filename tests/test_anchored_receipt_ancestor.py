# pyright: reportPrivateUsage=false
from __future__ import annotations

import errno
import gc
import inspect
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import FrameType
from typing import Any
import unittest
from unittest import mock

from scripts import _anchored_output as anchored


class AnchoredReceiptAncestorTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt" or not anchored.descriptor_relative_output_supported():
            self.skipTest("descriptor-relative POSIX ancestry unavailable")

    def test_substitution_after_created_ancestor_is_rejected_untouched(self) -> None:
        for substitute in ("symlink", "file"):
            with self.subTest(substitute=substitute), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                attacker = root / "attacker"
                attacker.mkdir()
                real_mkdir = anchored.os.mkdir
                retained_parent = -1
                binding_lease = anchored._OutputParentBindingLease()

                def mkdir_then_replace(name: str, mode: int, *, dir_fd: int) -> None:
                    nonlocal retained_parent
                    retained_parent = os.dup(dir_fd)
                    real_mkdir(name, mode, dir_fd=dir_fd)
                    os.rmdir(name, dir_fd=dir_fd)
                    if substitute == "symlink":
                        os.symlink(attacker, name, dir_fd=dir_fd, target_is_directory=True)
                    else:
                        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dir_fd)
                        os.write(descriptor, b"attacker")
                        os.close(descriptor)

                with mock.patch.object(anchored.os, "mkdir", side_effect=mkdir_then_replace) as patched_mkdir:
                    anchored.os.supports_dir_fd.add(patched_mkdir)
                    try:
                        with self.assertRaises(anchored.AnchoredOutputError):
                            anchored._open_rooted_posix_parent(
                                root,
                                root / "victim" / "receipt.json",
                                ("victim", "receipt.json"),
                                binding_lease,
                            )
                    finally:
                        anchored.os.supports_dir_fd.discard(patched_mkdir)
                binding = binding_lease.binding
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertTrue(binding.is_closed)
                self.assertGreaterEqual(retained_parent, 0)
                entry = os.stat("victim", dir_fd=retained_parent, follow_symlinks=False)
                self.assertEqual(stat.S_ISLNK(entry.st_mode), substitute == "symlink")
                if substitute == "file":
                    descriptor = os.open("victim", os.O_RDONLY, dir_fd=retained_parent)
                    try:
                        self.assertEqual(os.read(descriptor, 64), b"attacker")
                    finally:
                        os.close(descriptor)
                os.close(retained_parent)

    def test_mkdir_effect_then_file_exists_is_treated_as_changed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            binding_lease = anchored._OutputParentBindingLease()
            real_mkdir = anchored.os.mkdir

            def mkdir_then_file_exists(name: str, mode: int, *, dir_fd: int) -> None:
                real_mkdir(name, mode, dir_fd=dir_fd)
                raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), name)

            with (
                mock.patch.object(anchored.os, "mkdir", side_effect=mkdir_then_file_exists) as patched_mkdir,
                mock.patch.object(anchored.os, "fsync") as fsync,
            ):
                anchored.os.supports_dir_fd.add(patched_mkdir)
                try:
                    with self.assertRaises(anchored.AnchoredOutputError) as raised:
                        anchored._open_rooted_posix_parent(
                            root,
                            root / "victim" / "receipt.json",
                            ("victim", "receipt.json"),
                            binding_lease,
                        )
                finally:
                    anchored.os.supports_dir_fd.discard(patched_mkdir)

            self.assertEqual(raised.exception.code, "output-parent-changed")
            self.assertTrue((root / "victim").is_dir())
            fsync.assert_not_called()
            self.assertEqual(binding_lease.close(), ())
            binding = binding_lease.binding
            self.assertIsNotNone(binding)
            assert binding is not None
            self.assertTrue(binding.is_closed)

    def test_replacement_between_stat_and_open_is_rejected_untouched(self) -> None:
        for substitute in ("directory", "symlink"):
            with self.subTest(substitute=substitute), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                victim = root / "victim"
                victim.mkdir()
                displaced = root / "displaced"
                attacker = root / "attacker"
                attacker.mkdir()
                real_open = anchored._open_posix_descriptor
                replaced = False
                binding_lease = anchored._OutputParentBindingLease()

                def open_after_replace(
                    descriptor_lease: anchored._PosixDescriptorLease,
                    path: str | os.PathLike[str],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    nonlocal replaced
                    if os.fspath(path) == "victim" and not replaced:
                        replaced = True
                        victim.rename(displaced)
                        if substitute == "directory":
                            victim.mkdir()
                        else:
                            victim.symlink_to(attacker, target_is_directory=True)
                    return real_open(
                        descriptor_lease,
                        path,
                        flags,
                        mode,
                        dir_fd=dir_fd,
                    )

                with (
                    mock.patch.object(anchored, "_open_posix_descriptor", side_effect=open_after_replace),
                    self.assertRaises(anchored.AnchoredOutputError),
                ):
                    anchored._open_rooted_posix_parent(
                        root,
                        root / "victim" / "receipt.json",
                        ("victim", "receipt.json"),
                        binding_lease,
                    )
                binding = binding_lease.binding
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertTrue(binding.is_closed)
                self.assertTrue(displaced.is_dir())
                self.assertEqual(victim.is_symlink(), substitute == "symlink")

    def test_bound_ancestor_disappearance_has_stable_changed_code(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent = root / "parent"
            parent.mkdir()
            relocated = root / "relocated"
            binding_lease = anchored._OutputParentBindingLease()
            binding = anchored._open_rooted_posix_parent(
                root,
                parent / "receipt.json",
                ("parent", "receipt.json"),
                binding_lease,
            )
            parent.rename(relocated)

            try:
                with self.assertRaises(anchored.AnchoredOutputError) as raised:
                    binding.verify()
            finally:
                self.assertEqual(binding_lease.close(), ())

            self.assertEqual(raised.exception.code, "output-parent-changed")
            self.assertIsInstance(raised.exception.__cause__, FileNotFoundError)

    def test_open_and_final_verification_failures_close_every_acquired_descriptor(self) -> None:
        failures: tuple[tuple[str, BaseException], ...] = (
            ("open", OSError("injected child open failure")),
            ("verify", KeyboardInterrupt("injected verification interrupt")),
        )
        for seam, primary in failures:
            with self.subTest(seam=seam), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                (root / "victim").mkdir()
                real_open = anchored._open_posix_descriptor
                real_close = anchored._PosixDescriptorLease.close
                opened: list[int] = []
                closed: list[int] = []
                binding_lease = anchored._OutputParentBindingLease()

                def open_or_fail(
                    descriptor_lease: anchored._PosixDescriptorLease,
                    path: str | os.PathLike[str],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    if seam == "open" and os.fspath(path) == "victim":
                        raise primary
                    descriptor = real_open(
                        descriptor_lease,
                        path,
                        flags,
                        mode,
                        dir_fd=dir_fd,
                    )
                    opened.append(descriptor)
                    return descriptor

                def record_close(descriptor_lease: anchored._PosixDescriptorLease) -> None:
                    descriptor = descriptor_lease.descriptor
                    if descriptor is not None:
                        closed.append(descriptor)
                    real_close(descriptor_lease)

                verify_patch = (
                    mock.patch.object(anchored.OutputParentBinding, "verify", side_effect=primary)
                    if seam == "verify"
                    else mock.patch.object(anchored.OutputParentBinding, "verify", autospec=True)
                )
                with (
                    mock.patch.object(anchored, "_open_posix_descriptor", side_effect=open_or_fail),
                    mock.patch.object(anchored._PosixDescriptorLease, "close", new=record_close),
                    verify_patch,
                    self.assertRaises(anchored.AnchoredOutputError if seam == "open" else type(primary)) as raised,
                ):
                    anchored._open_rooted_posix_parent(
                        root,
                        root / "victim" / "receipt.json",
                        ("victim", "receipt.json"),
                        binding_lease,
                    )
                if seam == "open":
                    self.assertIs(raised.exception.__cause__, primary)
                else:
                    self.assertIs(raised.exception, primary)
                binding = binding_lease.binding
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertTrue(binding.is_closed)
                self.assertEqual(closed, list(reversed(opened)))

    def test_preinstalled_owner_recovers_root_child_and_verification_interrupts(self) -> None:
        target = anchored._open_rooted_posix_parent
        source, first_line = inspect.getsourcelines(target)
        cleanup_lines = [
            first_line + index
            for index, line in enumerate(source)
            if "cleanup_failures = lease.close()" in line
        ]
        self.assertEqual(len(cleanup_lines), 1)
        cleanup_line = cleanup_lines[0]

        for seam in ("root", "child", "verify"):
            with self.subTest(seam=seam), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                (root / "parent").mkdir()
                output = root / "parent" / "receipt.json"
                body_failure = RuntimeError(f"modeled {seam} acquisition failure")
                cleanup_interruption = KeyboardInterrupt(
                    f"interrupt {seam} exception-handler cleanup entry"
                )
                opened: list[int] = []
                closed: list[int] = []
                open_count = 0
                cleanup_was_interrupted = False
                real_open = anchored._open_posix_descriptor
                real_close = anchored._PosixDescriptorLease.close
                real_verify = anchored.OutputParentBinding.verify

                def open_then_maybe_fail(
                    descriptor_lease: anchored._PosixDescriptorLease,
                    path: str | os.PathLike[str],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    nonlocal open_count
                    descriptor = real_open(
                        descriptor_lease,
                        path,
                        flags,
                        mode,
                        dir_fd=dir_fd,
                    )
                    opened.append(descriptor)
                    current_open = open_count
                    open_count += 1
                    if (seam == "root" and current_open == 0) or (
                        seam == "child" and current_open == 1
                    ):
                        raise body_failure
                    return descriptor

                def verify_then_maybe_fail(binding: anchored.OutputParentBinding) -> None:
                    real_verify(binding)
                    if seam == "verify":
                        raise body_failure

                def record_close(descriptor_lease: anchored._PosixDescriptorLease) -> None:
                    descriptor = descriptor_lease.descriptor
                    if descriptor is not None:
                        closed.append(descriptor)
                    real_close(descriptor_lease)

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
                        root,
                        output,
                        ("parent", "receipt.json"),
                        lease,
                    )

                previous_trace = sys.gettrace()
                try:
                    with (
                        mock.patch.object(
                            anchored,
                            "_open_posix_descriptor",
                            side_effect=open_then_maybe_fail,
                        ),
                        mock.patch.object(
                            anchored._PosixDescriptorLease,
                            "close",
                            new=record_close,
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

                self.assertEqual(closed, list(reversed(opened)))
                self.assertEqual(len(closed), len(set(closed)))
                for descriptor in opened:
                    with self.assertRaises(OSError) as descriptor_error:
                        os.fstat(descriptor)
                    self.assertEqual(descriptor_error.exception.errno, errno.EBADF)

    def test_binding_lease_survives_posix_opener_to_wrapper_return_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "parent").mkdir()
            output = root / "parent" / "receipt.json"
            interruption = KeyboardInterrupt("POSIX opener returned before wrapper assignment")
            real_parent_open = anchored._open_rooted_posix_parent
            captured_lease: anchored._OutputParentBindingLease | None = None
            opened: list[int] = []
            closed: list[int] = []
            triggered = False
            real_open = anchored._open_posix_descriptor
            real_close = anchored._PosixDescriptorLease.close

            def open_and_record(
                descriptor_lease: anchored._PosixDescriptorLease,
                path: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = real_open(
                    descriptor_lease,
                    path,
                    flags,
                    mode,
                    dir_fd=dir_fd,
                )
                opened.append(descriptor)
                return descriptor

            def close_and_record(descriptor_lease: anchored._PosixDescriptorLease) -> None:
                descriptor = descriptor_lease.descriptor
                if descriptor is not None:
                    closed.append(descriptor)
                real_close(descriptor_lease)

            def open_then_interrupt(
                root_anchor: Path,
                absolute: Path,
                parts: tuple[str, ...],
                binding_lease: anchored._OutputParentBindingLease,
            ) -> anchored.OutputParentBinding:
                nonlocal captured_lease, triggered
                real_parent_open(root_anchor, absolute, parts, binding_lease)
                captured_lease = binding_lease
                triggered = True
                raise interruption

            with (
                mock.patch.object(
                    anchored,
                    "_open_posix_descriptor",
                    side_effect=open_and_record,
                ),
                mock.patch.object(
                    anchored._PosixDescriptorLease,
                    "close",
                    new=close_and_record,
                ),
                mock.patch.object(
                    anchored,
                    "_open_rooted_posix_parent",
                    side_effect=open_then_interrupt,
                ),
                mock.patch.object(anchored, "_publish_posix_receipt_bytes") as publish,
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, b"receipt\n")

            self.assertTrue(triggered)
            self.assertIs(raised.exception, interruption)
            self.assertIsNotNone(captured_lease)
            assert captured_lease is not None
            binding = captured_lease.binding
            self.assertIsNotNone(binding)
            assert binding is not None
            self.assertTrue(binding.is_closed)
            publish.assert_not_called()
            self.assertGreaterEqual(len(opened), 2)
            self.assertEqual(closed, list(reversed(opened)))

    def test_unsafe_final_or_creation_parent_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            unsafe = root / "unsafe"
            unsafe.mkdir()
            unsafe.chmod(0o777)
            try:
                for output in (unsafe / "receipt.json", unsafe / "missing" / "receipt.json"):
                    with self.subTest(output=output):
                        lease = anchored._OutputParentBindingLease()
                        with self.assertRaises(anchored.AnchoredOutputError) as raised:
                            anchored._open_rooted_posix_parent(
                                root,
                                output,
                                output.relative_to(root).parts,
                                lease,
                            )
                        self.assertIn(raised.exception.code, {"output-parent-invalid", "output-parent-changed"})
                        self.assertFalse((unsafe / "missing").exists())
                        self.assertEqual(lease.close(), ())
            finally:
                unsafe.chmod(0o700)

    def test_safe_namespace_predicate_rejects_untrusted_owner(self) -> None:
        untrusted = mock.Mock(
            st_mode=stat.S_IFDIR | 0o755,
            st_uid=os.geteuid() + 1,
        )
        with (
            mock.patch.object(anchored.os, "fstat", return_value=untrusted),
            mock.patch.object(anchored, "_darwin_descriptor_has_extended_acl", return_value=False),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._validate_safe_posix_directory_descriptor(
                7,
                code="output-parent-invalid",
                context="modeled final parent",
            )
        self.assertEqual(raised.exception.code, "output-parent-invalid")

    def test_bound_intermediate_becoming_world_writable_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            intermediate = root / "intermediate"
            final_parent = intermediate / "final"
            final_parent.mkdir(parents=True)
            lease = anchored._OutputParentBindingLease()
            binding = anchored._open_rooted_posix_parent(
                root,
                final_parent / "receipt.json",
                ("intermediate", "final", "receipt.json"),
                lease,
            )
            intermediate.chmod(0o777)
            try:
                with self.assertRaises(anchored.AnchoredOutputError) as raised:
                    binding.verify()
                self.assertEqual(raised.exception.code, "output-parent-changed")
            finally:
                intermediate.chmod(0o700)
                self.assertEqual(lease.close(), ())

    def test_sticky_safe_parent_is_accepted_and_unsafe_intermediate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            sticky = root / "sticky"
            sticky.mkdir()
            sticky.chmod(0o1777)
            sticky_lease = anchored._OutputParentBindingLease()
            sticky_binding = anchored._open_rooted_posix_parent(
                root,
                sticky / "receipt.json",
                ("sticky", "receipt.json"),
                sticky_lease,
            )
            self.assertEqual(sticky_lease.close(), ())
            self.assertTrue(sticky_binding.is_closed)

            unsafe = root / "unsafe-ancestor"
            safe = unsafe / "safe-final"
            unsafe.mkdir(mode=0o700)
            safe.mkdir(mode=0o700)
            unsafe.chmod(0o777)
            try:
                safe_lease = anchored._OutputParentBindingLease()
                with self.assertRaises(anchored.AnchoredOutputError) as raised:
                    anchored._open_rooted_posix_parent(
                        root,
                        safe / "receipt.json",
                        ("unsafe-ancestor", "safe-final", "receipt.json"),
                        safe_lease,
                    )
                self.assertEqual(raised.exception.code, "output-parent-invalid")
                self.assertEqual(safe_lease.close(), ())
                self.assertIsNotNone(safe_lease.binding)
                assert safe_lease.binding is not None
                self.assertTrue(safe_lease.binding.is_closed)
            finally:
                unsafe.chmod(0o700)

    def test_created_ancestors_are_private_under_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            lease = anchored._OutputParentBindingLease()
            previous_umask = os.umask(0o777)
            try:
                binding = anchored._open_rooted_posix_parent(
                    root,
                    root / "one" / "two" / "receipt.json",
                    ("one", "two", "receipt.json"),
                    lease,
                )
            finally:
                os.umask(previous_umask)
            self.assertEqual(stat.S_IMODE((root / "one").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "one" / "two").stat().st_mode), 0o700)
            self.assertEqual(lease.close(), ())
            self.assertTrue(binding.is_closed)

    def test_existing_ancestor_retries_containing_directory_sync(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            output = root / "parent" / "receipt.json"
            first_lease = anchored._OutputParentBindingLease()
            with (
                mock.patch.object(anchored.os, "fsync", side_effect=OSError(errno.EIO, "sync")),
                self.assertRaises(anchored.AnchoredOutputError),
            ):
                anchored._open_rooted_posix_parent(
                    root,
                    output,
                    ("parent", "receipt.json"),
                    first_lease,
                )
            self.assertTrue((root / "parent").is_dir())
            self.assertEqual(first_lease.close(), ())

            second_lease = anchored._OutputParentBindingLease()
            with mock.patch.object(anchored.os, "fsync") as retry_sync:
                binding = anchored._open_rooted_posix_parent(
                    root,
                    output,
                    ("parent", "receipt.json"),
                    second_lease,
                )
            retry_sync.assert_called_once_with(binding.descriptors[0])
            self.assertEqual(second_lease.close(), ())

    def test_binding_lease_survives_wrapper_to_public_assignment_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "parent").mkdir()
            output = root / "parent" / "receipt.json"
            interruption = KeyboardInterrupt("wrapper returned before public binding assignment")
            real_parent_open = anchored.open_rooted_output_parent
            captured_lease: anchored._OutputParentBindingLease | None = None
            opened: list[int] = []
            closed: list[int] = []
            triggered = False
            real_open = anchored._open_posix_descriptor
            real_close = anchored._PosixDescriptorLease.close

            def open_and_record(
                descriptor_lease: anchored._PosixDescriptorLease,
                path: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = real_open(
                    descriptor_lease,
                    path,
                    flags,
                    mode,
                    dir_fd=dir_fd,
                )
                opened.append(descriptor)
                return descriptor

            def close_and_record(descriptor_lease: anchored._PosixDescriptorLease) -> None:
                descriptor = descriptor_lease.descriptor
                if descriptor is not None:
                    closed.append(descriptor)
                real_close(descriptor_lease)

            def open_then_interrupt(
                path: Path,
                binding_lease: anchored._OutputParentBindingLease,
            ) -> anchored.OutputParentBinding:
                nonlocal captured_lease, triggered
                real_parent_open(path, binding_lease)
                captured_lease = binding_lease
                triggered = True
                raise interruption

            with (
                mock.patch.object(
                    anchored,
                    "_open_posix_descriptor",
                    side_effect=open_and_record,
                ),
                mock.patch.object(
                    anchored._PosixDescriptorLease,
                    "close",
                    new=close_and_record,
                ),
                mock.patch.object(
                    anchored,
                    "open_rooted_output_parent",
                    side_effect=open_then_interrupt,
                ),
                mock.patch.object(anchored, "_publish_posix_receipt_bytes") as publish,
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, b"receipt\n")

            self.assertTrue(triggered)
            self.assertIs(raised.exception, interruption)
            self.assertIsNotNone(captured_lease)
            assert captured_lease is not None
            binding = captured_lease.binding
            self.assertIsNotNone(binding)
            assert binding is not None
            self.assertTrue(binding.is_closed)
            publish.assert_not_called()
            self.assertGreaterEqual(len(opened), 2)
            self.assertEqual(closed, list(reversed(opened)))


if __name__ == "__main__":
    unittest.main()
