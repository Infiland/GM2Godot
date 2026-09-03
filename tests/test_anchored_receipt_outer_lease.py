# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import errno
import gc
import inspect
import os
from pathlib import Path
import sys
import tempfile
from types import FrameType
from typing import Any, Callable
import unittest
from unittest import mock

from scripts import _anchored_output as anchored


PAYLOAD = b'{"status":"verified"}\n'


def _source_line(
    function: Callable[..., object],
    source_fragment: str,
) -> int:
    """Find one cleanup source line without depending on CPython bytecode."""

    lines, first_line = inspect.getsourcelines(function)
    matching_lines = [first_line + index for index, source_line in enumerate(lines) if source_fragment in source_line]
    if len(matching_lines) != 1:
        raise AssertionError(
            f"Expected one {function.__name__} source line containing {source_fragment!r}; found {matching_lines}."
        )
    return matching_lines[0]


class AnchoredReceiptOuterLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("descriptor-relative POSIX test")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.parent = self.root / "parent"
        self.parent.mkdir()
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.posix = anchored._posix_receipt_module()

    def tearDown(self) -> None:
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def assert_descriptor_closed(self, descriptor: int) -> None:
        with self.assertRaises(OSError) as raised:
            os.fstat(descriptor)
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def _open_binding_before_platform_model(
        self,
        output: Path,
    ) -> tuple[anchored.OutputParentBinding, anchored._OutputParentBindingLease]:
        lease = anchored._OutputParentBindingLease()
        binding = anchored.open_rooted_output_parent(output, lease)
        self.assertIs(lease.binding, binding)
        return binding, lease

    def test_binding_preserves_legacy_positional_constructor_contract(self) -> None:
        descriptors = (11, 12)
        links = ((11, "parent", 12),)
        windows_api = object()
        windows_entries = ((Path("C:/parent"), (1, 2), 13),)
        binding = anchored.OutputParentBinding(
            Path("checkout"),
            Path("parent"),
            "snapshot.json",
            "posix-dir-fd",
            descriptors,
            links,
            windows_api,
            windows_entries,
        )

        self.assertIs(binding.descriptors, descriptors)
        self.assertIs(binding.links, links)
        self.assertIs(binding.windows_api, windows_api)
        self.assertIs(binding.windows_entries, windows_entries)
        self.assertFalse(binding.receipt_parent_policy)
        parameters = inspect.signature(anchored.OutputParentBinding).parameters
        for name in (
            "descriptor_leases",
            "windows_handle_leases",
            "receipt_parent_policy",
            "private_posix_descriptor_indexes",
        ):
            self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertNotIn("_closed", parameters)

    def test_outer_lease_keeps_older_resources_and_parent_open_until_newest_closes(
        self,
    ) -> None:
        events: list[str] = []

        class Resource:
            def __init__(self, name: str, close_after: int) -> None:
                self.name = name
                self.close_after = close_after
                self.close_calls = 0
                self.closed = False

            @property
            def is_closed(self) -> bool:
                return self.closed

            def close(self) -> tuple[BaseException, ...]:
                if self.closed:
                    return ()
                self.close_calls += 1
                events.append(self.name)
                if self.close_calls < self.close_after:
                    return (RuntimeError(f"{self.name} is still open"),)
                self.closed = True
                return ()

        class Binding:
            descriptor_leases: tuple[object, ...] = ()

            def __init__(self) -> None:
                self.closed = False

            @property
            def is_closed(self) -> bool:
                return self.closed

            def close(self) -> tuple[BaseException, ...]:
                events.append("binding")
                self.closed = True
                return ()

        binding: Any = Binding()
        older = Resource("older", close_after=1)
        newest = Resource("newest", close_after=3)
        lease = anchored._OutputParentBindingLease(binding)
        lease.retain_publication_resource(older)
        lease.retain_publication_resource(newest)

        first_failures = lease.close()

        self.assertEqual(events, ["newest", "newest"])
        self.assertEqual(len(first_failures), 2)
        self.assertFalse(older.is_closed)
        self.assertFalse(binding.is_closed)
        self.assertTrue(lease._finalizer.alive)

        self.assertEqual(lease.close(), ())
        self.assertEqual(
            events,
            ["newest", "newest", "newest", "older", "binding"],
        )
        self.assertTrue(newest.is_closed)
        self.assertTrue(older.is_closed)
        self.assertTrue(binding.is_closed)
        self.assertFalse(lease._finalizer.alive)

    def test_binding_keeps_parent_open_when_child_exhausts_cleanup(self) -> None:
        root = anchored._PosixDescriptorLease(ctypes.c_int(101))
        child = anchored._PosixDescriptorLease(ctypes.c_int(102))
        binding = anchored.OutputParentBinding(
            checkout=self.root,
            parent=self.parent,
            leaf="receipt.json",
            strategy="posix-dir-fd",
            descriptors=(101, 102),
            descriptor_leases=(root, child),
        )
        interruption = KeyboardInterrupt("child close remains interrupted")
        attempts: list[str] = []
        child_may_close = False

        def close_descriptor(descriptor_lease: anchored._PosixDescriptorLease) -> None:
            label = "child" if descriptor_lease is child else "root"
            attempts.append(label)
            if descriptor_lease is child and not child_may_close:
                raise interruption
            descriptor_lease.descriptor_result = None

        with mock.patch.object(
            anchored._PosixDescriptorLease,
            "close",
            new=close_descriptor,
        ):
            first_failures = binding.close()
            self.assertEqual(attempts, ["child", "child"])
            self.assertIsNotNone(child.descriptor)
            self.assertIsNotNone(root.descriptor)
            self.assertFalse(binding.is_closed)
            self.assertEqual(first_failures, (interruption,))

            child_may_close = True
            self.assertEqual(binding.close(), ())

        self.assertEqual(attempts, ["child", "child", "child", "root"])
        self.assertTrue(binding.is_closed)

    def test_posix_publication_lease_keeps_older_descriptors_open_until_newest_closes(
        self,
    ) -> None:
        binding = anchored.OutputParentBinding(
            checkout=self.root,
            parent=self.parent,
            leaf="receipt.json",
            strategy="posix-dir-fd",
        )
        publication_lease = self.posix._PosixReceiptPublicationLease(binding)
        older = anchored._PosixDescriptorLease(ctypes.c_int(101))
        newest = anchored._PosixDescriptorLease(ctypes.c_int(102))
        publication_lease.transient_descriptors.extend((older, newest))
        publication_lease.stage.descriptor.descriptor_result = ctypes.c_int(103)
        publication_lease.stage.private_directory.descriptor_result = ctypes.c_int(104)
        publication_lease.stage.named_stage_name = "retained-stage.tmp"
        names = {
            id(older): "older",
            id(newest): "newest",
            id(publication_lease.stage.descriptor): "stage",
            id(publication_lease.stage.private_directory): "private",
        }
        close_calls: dict[int, int] = {}
        events: list[str] = []

        def close_descriptor(
            descriptor_lease: anchored._PosixDescriptorLease,
            _primary: BaseException | None,
            _context: str,
        ) -> BaseException | None:
            identity = id(descriptor_lease)
            close_calls[identity] = close_calls.get(identity, 0) + 1
            events.append(names[identity])
            if descriptor_lease is newest and close_calls[identity] < 3:
                return RuntimeError("newest is still open")
            descriptor_lease.descriptor_result = None
            return None

        def cleanup_named_stage(stage: Any) -> None:
            events.append("named-stage")
            stage.named_stage_name = None

        with (
            mock.patch.object(self.posix.sys, "platform", "darwin"),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=close_descriptor,
            ),
            mock.patch.object(
                self.posix,
                "_cleanup_darwin_named_stage",
                side_effect=cleanup_named_stage,
            ),
        ):
            self.assertEqual(len(publication_lease.close()), 1)
            self.assertEqual(events, ["newest"])
            self.assertIsNotNone(older.descriptor)
            self.assertIsNotNone(publication_lease.stage.descriptor.descriptor)
            self.assertIsNotNone(publication_lease.stage.private_directory.descriptor)

            self.assertEqual(len(publication_lease.close()), 1)
            self.assertEqual(events, ["newest", "newest"])
            self.assertIsNotNone(older.descriptor)

            self.assertEqual(publication_lease.close(), ())

        self.assertEqual(
            events,
            [
                "newest",
                "newest",
                "newest",
                "older",
                "named-stage",
                "stage",
                "private",
            ],
        )
        self.assertTrue(publication_lease.is_closed)

    def test_public_finalizer_recovers_when_outer_cleanup_call_is_interrupted(
        self,
    ) -> None:
        target = anchored.publish_identical_receipt_bytes
        cleanup_line = _source_line(
            target,
            "close_failures = lease.close()",
        )
        interruption = KeyboardInterrupt("public outer cleanup call")
        retained = False
        triggered = False

        class Resource:
            def __init__(self) -> None:
                self.closed = False
                self.close_calls = 0

            @property
            def is_closed(self) -> bool:
                return self.closed

            def close(self) -> tuple[BaseException, ...]:
                self.close_calls += 1
                self.closed = True
                raise SystemExit("finalizer-only cleanup interruption")

        class Binding:
            strategy = "posix-dir-fd"

            def __init__(self) -> None:
                self.closed = False
                self.close_calls = 0

            @property
            def is_closed(self) -> bool:
                return self.closed

            def close(self) -> tuple[BaseException, ...]:
                self.close_calls += 1
                self.closed = True
                return ()

        resource = Resource()
        binding: Any = Binding()

        def open_binding(
            _path: Path,
            lease: anchored._OutputParentBindingLease,
        ) -> Any:
            lease.binding = binding
            return binding

        def retain_without_cleanup(
            _path: Path,
            _payload: bytes,
            _binding: object,
            lease: anchored._OutputParentBindingLease,
        ) -> None:
            nonlocal retained
            lease.retain_publication_resource(resource)
            retained = True

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is target.__code__
                and frame.f_lineno == cleanup_line
                and retained
                and not triggered
            ):
                triggered = True
                raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(
                    anchored,
                    "open_rooted_output_parent",
                    new=open_binding,
                ),
                mock.patch.object(
                    anchored,
                    "_publish_posix_receipt_bytes",
                    new=retain_without_cleanup,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                sys.settrace(trace)
                anchored.publish_identical_receipt_bytes(
                    self.parent / "receipt.json",
                    PAYLOAD,
                )
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        # The traceback owns the interrupted frame on every supported Python;
        # clear it before forcing the portable GC boundary for weakref.finalize.
        interruption.__traceback__ = None
        gc.collect()
        self.assertEqual(resource.close_calls, 1)
        self.assertTrue(resource.closed)
        self.assertEqual(binding.close_calls, 1)
        self.assertTrue(binding.closed)

    def test_posix_publisher_keeps_binding_open_while_publication_lease_is_live(
        self,
    ) -> None:
        body_failure = OSError(errno.EIO, "modeled publisher failure")

        class Binding:
            leaf = "receipt.json"

            def __init__(self) -> None:
                self.close_calls = 0

            def stat(self, _name: str) -> os.stat_result:
                raise body_failure

            def close(self) -> tuple[BaseException, ...]:
                self.close_calls += 1
                return ()

        class PublicationLease:
            stage = object()

            def __init__(self, binding: object) -> None:
                self.binding = binding
                self.close_calls = 0

            @property
            def is_closed(self) -> bool:
                return False

            def close(self) -> tuple[BaseException, ...]:
                self.close_calls += 1
                return (RuntimeError("publication descriptor is still open"),)

        binding: Any = Binding()
        publication_lease: Any = PublicationLease(binding)

        with self.assertRaises(OSError) as raised:
            self.posix._publish_posix_receipt_bytes(
                self.parent / binding.leaf,
                PAYLOAD,
                binding,
                publication_lease,
            )

        self.assertIs(raised.exception, body_failure)
        self.assertEqual(publication_lease.close_calls, 2)
        self.assertEqual(binding.close_calls, 0)
        self.assertEqual(len(getattr(body_failure, "__notes__", ())), 2)

    def test_public_facade_closes_read_descriptor_when_finally_prelude_is_interrupted(
        self,
    ) -> None:
        output = self.parent / "receipt.json"
        output.write_bytes(PAYLOAD)
        output.chmod(0o600)
        target = anchored._read_exact_receipt
        cleanup_line = _source_line(
            target,
            "close_call_failures: list[BaseException] = []",
        )
        interruption = KeyboardInterrupt("receipt reader finally prelude")
        captured: list[int] = []
        triggered = False

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if event == "line" and frame.f_code is target.__code__ and frame.f_lineno == cleanup_line and not triggered:
                descriptor_lease = frame.f_locals.get("descriptor_lease")
                if isinstance(descriptor_lease, anchored._PosixDescriptorLease):
                    descriptor = descriptor_lease.descriptor
                    if descriptor is not None:
                        captured.append(descriptor)
                        triggered = True
                        raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaises(KeyboardInterrupt) as raised:
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(len(captured), 1)
        self.assert_descriptor_closed(captured[0])

    def test_public_facade_closes_darwin_public_descriptor_when_finally_prelude_is_interrupted(
        self,
    ) -> None:
        output = self.parent / "receipt.json"
        binding, setup_lease = self._open_binding_before_platform_model(output)
        target = self.posix._sync_posix_public_descriptor
        cleanup_line = _source_line(
            target,
            "close_call_failures: list[BaseException] = []",
        )
        interruption = KeyboardInterrupt("Darwin public descriptor finally prelude")
        captured: list[int] = []
        opened_stages: list[int] = []
        triggered = False

        def reuse_binding(
            _path: Path,
            lease: anchored._OutputParentBindingLease,
        ) -> anchored.OutputParentBinding:
            lease.binding = binding
            return binding

        def open_named_stage(
            _binding: object,
            _temporary_name: str,
            lease: Any,
        ) -> object:
            private_root = self.parent / ".modeled-darwin-private"
            private_root.mkdir(mode=0o700)
            private_descriptor = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
            stage_name = "modeled-darwin-stage.tmp"
            descriptor = os.open(
                stage_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=private_descriptor,
            )
            lease.descriptor.descriptor_result = ctypes.c_int(descriptor)
            lease.private_directory.descriptor_result = ctypes.c_int(private_descriptor)
            lease.named_stage_name = stage_name
            private_value = os.fstat(private_descriptor)
            stage = self.posix._PosixReceiptStage(
                descriptor=descriptor,
                private_directory_descriptor=private_descriptor,
                private_directory_name=private_root.name,
                private_directory_identity=(private_value.st_dev, private_value.st_ino),
                named_stage_name=stage_name,
            )
            lease.stage = stage
            opened_stages.extend((descriptor, private_descriptor))
            return stage

        def rename_stage(
            stage: Any,
            stage_lease: Any,
            parent_descriptor: int,
            destination: str,
        ) -> None:
            stage_lease.private_directory_sync_pending = True
            os.rename(
                stage.named_stage_name,
                destination,
                src_dir_fd=stage.private_directory_descriptor,
                dst_dir_fd=parent_descriptor,
            )

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if event == "line" and frame.f_code is target.__code__ and frame.f_lineno == cleanup_line and not triggered:
                descriptor_lease = frame.f_locals.get("descriptor_lease")
                if isinstance(descriptor_lease, anchored._PosixDescriptorLease):
                    descriptor = descriptor_lease.descriptor
                    if descriptor is not None:
                        captured.append(descriptor)
                        triggered = True
                        raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(anchored, "open_rooted_output_parent", side_effect=reuse_binding),
                mock.patch.object(self.posix.sys, "platform", "darwin"),
                mock.patch.object(
                    self.posix,
                    "_open_posix_receipt_stage",
                    side_effect=open_named_stage,
                ),
                mock.patch.object(
                    self.posix,
                    "_darwin_rename_receipt_stage",
                    side_effect=rename_stage,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                sys.settrace(trace)
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
        finally:
            sys.settrace(previous_trace)
            setup_failures = setup_lease.close()

        self.assertEqual(setup_failures, ())
        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(len(captured), 1)
        self.assert_descriptor_closed(captured[0])
        self.assertEqual(len(opened_stages), 2)
        for descriptor in opened_stages:
            self.assert_descriptor_closed(descriptor)

    def test_public_facade_outer_lease_closes_stage_when_publisher_finally_prelude_is_interrupted(
        self,
    ) -> None:
        output = self.parent / "receipt.json"
        target = self.posix._publish_posix_receipt_bytes
        cleanup_line = _source_line(
            target,
            "close_failures: list[BaseException] = []",
        )
        interruption = KeyboardInterrupt("publisher finally prelude")
        body_failure = OSError(errno.EIO, "modeled publication body failure")
        opened: list[int] = []
        captured: list[int] = []
        triggered = False

        def open_stage(_binding: object, _temporary_name: str, lease: Any) -> object:
            stage_path = self.parent / "unlinked-stage.tmp"
            descriptor = os.open(
                stage_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            stage_path.unlink()
            lease.descriptor.descriptor_result = ctypes.c_int(descriptor)
            stage = self.posix._PosixReceiptStage(descriptor=descriptor)
            lease.stage = stage
            opened.append(descriptor)
            return stage

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if event == "line" and frame.f_code is target.__code__ and frame.f_lineno == cleanup_line and not triggered:
                publication_lease = frame.f_locals.get("publication_lease")
                if publication_lease is not None and isinstance(
                    publication_lease,
                    self.posix._PosixReceiptPublicationLease,
                ):
                    descriptor = publication_lease.stage.descriptor.descriptor
                    if descriptor is not None:
                        captured.append(descriptor)
                        triggered = True
                        raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
                mock.patch.object(
                    self.posix,
                    "_write_and_sync_retained_descriptor",
                    side_effect=body_failure,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                sys.settrace(trace)
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(opened, captured)
        self.assertEqual(len(captured), 1)
        self.assert_descriptor_closed(captured[0])

    def test_required_outer_owner_recovers_direct_posix_facade_cleanup_entry(self) -> None:
        output = self.parent / "receipt.json"
        binding, outer_lease = self._open_binding_before_platform_model(output)
        target = self.posix._publish_posix_receipt_bytes
        cleanup_line = _source_line(
            target,
            "close_failures: list[BaseException] = []",
        )
        interruption = KeyboardInterrupt("direct POSIX facade cleanup entry")
        body_failure = OSError(errno.EIO, "modeled publication body failure")
        opened: list[int] = []
        triggered = False

        def open_stage(_binding: object, _temporary_name: str, lease: Any) -> object:
            stage_path = self.parent / "direct-unlinked-stage.tmp"
            descriptor = os.open(
                stage_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            stage_path.unlink()
            lease.descriptor.descriptor_result = ctypes.c_int(descriptor)
            stage = self.posix._PosixReceiptStage(descriptor=descriptor)
            lease.stage = stage
            opened.append(descriptor)
            return stage

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if event == "line" and frame.f_code is target.__code__ and frame.f_lineno == cleanup_line and not triggered:
                publication_lease: Any = frame.f_locals.get("publication_lease")
                stage_lease: Any = getattr(publication_lease, "stage", None)
                if isinstance(stage_lease, self.posix._PosixReceiptStageLease):
                    descriptor = stage_lease.descriptor.descriptor
                    if descriptor is not None:
                        triggered = True
                        raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
                mock.patch.object(
                    self.posix,
                    "_write_and_sync_retained_descriptor",
                    side_effect=body_failure,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                sys.settrace(trace)
                anchored._publish_posix_receipt_bytes(
                    output,
                    PAYLOAD,
                    binding,
                    outer_lease,
                )
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertEqual(len(opened), 1)
        os.fstat(opened[0])
        self.assertEqual(len(outer_lease.publication_resources), 1)
        self.assertEqual(outer_lease.close(), ())
        self.assert_descriptor_closed(opened[0])
        self.assertTrue(binding.is_closed)


if __name__ == "__main__":
    unittest.main()
