# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import errno
import gc
import inspect
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import FrameType, SimpleNamespace
from typing import Any, Callable
from unittest import mock

from scripts import _anchored_output as anchored

PRIVATE_ROOT = ".gm2godot-receipt-staging"


def _source_line(
    function: Callable[..., object],
    source_fragment: str,
) -> int:
    """Find one cleanup source line without depending on CPython bytecode."""

    lines, first_line = inspect.getsourcelines(function)
    matching_lines = [
        first_line + index
        for index, source_line in enumerate(lines)
        if source_fragment in source_line
    ]
    if len(matching_lines) != 1:
        raise AssertionError(
            f"Expected one {function.__name__} source line containing "
            f"{source_fragment!r}; found {matching_lines}."
        )
    return matching_lines[0]


class _LeaseAwareNativeCall:
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


class AnchoredReceiptDarwinTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("descriptor-relative POSIX test")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.parent = self.root / "parent"
        self.parent.mkdir()
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.binding_lease = anchored._OutputParentBindingLease()
        self.binding = anchored.open_rooted_output_parent(
            self.parent / "receipt.json",
            self.binding_lease,
        )
        self.posix = anchored._posix_receipt_module()

    def tearDown(self) -> None:
        for failure in self.binding_lease.close():
            self.fail(f"could not close output binding: {failure}")
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def _stage_lease(self) -> Any:
        return self.posix._PosixReceiptStageLease(
            anchored._PosixDescriptorLease(),
            anchored._PosixDescriptorLease(),
        )

    def _add_everyone_acl(self, path: Path, *, inherited: bool = False) -> None:
        permissions = "read,write,append"
        if inherited:
            permissions += ",file_inherit,directory_inherit"
        subprocess.run(
            ["chmod", "+a", f"everyone allow {permissions}", os.fspath(path)],
            check=True,
            capture_output=True,
            text=True,
        )

    def _add_everyone_deny_acl(self, path: Path) -> None:
        subprocess.run(
            ["chmod", "+a", "everyone deny delete", os.fspath(path)],
            check=True,
            capture_output=True,
            text=True,
        )

    def _clear_acl(self, path: Path) -> None:
        subprocess.run(
            ["chmod", "-RN", os.fspath(path)],
            check=True,
            capture_output=True,
            text=True,
        )

    def _modeled_acl_api(
        self,
        tags: tuple[int, ...],
        *,
        validity_status: int = 0,
        structural_status: int = 0,
        enumeration_status: int | None = None,
        tag_status: int = 0,
        enumeration_error: BaseException | None = None,
    ) -> tuple[
        dict[str, object],
        _LeaseAwareNativeCall,
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
    ]:
        get_acl = _LeaseAwareNativeCall(1234)
        free_acl = _LeaseAwareNativeCall(0)
        valid_acl = mock.Mock(return_value=validity_status)
        structurally_valid_acl = mock.Mock(return_value=structural_status)
        entry_index = 0

        def enumerate_acl(
            _acl: object,
            _selector: object,
            output: Any,
        ) -> int:
            nonlocal entry_index
            if enumeration_error is not None:
                raise enumeration_error
            if enumeration_status is not None:
                return enumeration_status
            if entry_index >= len(tags):
                ctypes.set_errno(errno.EINVAL)
                return -1
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = (
                2000 + entry_index
            )
            entry_index += 1
            return 0

        tag_index = 0

        def read_tag(_entry: object, output: Any) -> int:
            nonlocal tag_index
            if tag_status != 0:
                return tag_status
            ctypes.cast(output, ctypes.POINTER(ctypes.c_int)).contents.value = tags[
                tag_index
            ]
            tag_index += 1
            return 0

        get_entry = mock.Mock(side_effect=enumerate_acl)
        get_tag_type = mock.Mock(side_effect=read_tag)
        return (
            {
                "acl_get_fd_np": get_acl,
                "acl_free": free_acl,
                "acl_valid_fd_np": valid_acl,
                "acl_valid": structurally_valid_acl,
                "acl_get_entry": get_entry,
                "acl_get_tag_type": get_tag_type,
            },
            free_acl,
            valid_acl,
            structurally_valid_acl,
            get_entry,
            get_tag_type,
        )

    def _run_acl_line_interruption(
        self,
        target: Callable[..., object],
        source_fragment: str,
        interruption: KeyboardInterrupt,
        *,
        trigger_count: int = 1,
    ) -> tuple[_LeaseAwareNativeCall, _LeaseAwareNativeCall]:
        """Interrupt an ACL cleanup line, then release its traceback owner."""

        cleanup_line = _source_line(target, source_fragment)
        get_acl = _LeaseAwareNativeCall(1234)
        free_acl = _LeaseAwareNativeCall(0)
        triggers = 0

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggers
            if event == "call" and frame.f_code is target.__code__:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is target.__code__
                and frame.f_lineno == cleanup_line
                and triggers < trigger_count
            ):
                triggers += 1
                raise interruption
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(
                    anchored,
                    "_posix_libc",
                    return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
                ),
                mock.patch.object(anchored.sys, "platform", "darwin"),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                sys.settrace(trace)
                anchored._darwin_descriptor_has_extended_acl(7)
        finally:
            sys.settrace(previous_trace)

        self.assertEqual(triggers, trigger_count)
        self.assertIs(raised.exception, interruption)
        # The interrupted query frame owns the weak-referenceable lease through
        # its traceback. Clearing it makes the finalizer boundary deterministic.
        interruption.__traceback__ = None
        gc.collect()
        return get_acl, free_acl

    def _close_stage(self, stage: Any, lease: Any, *, verify_root: bool = True) -> None:
        failures: list[BaseException] = []
        try:
            self.posix._cleanup_darwin_named_stage(lease)
        except BaseException as error:
            failures.append(error)
        descriptor_close = self.posix._close_posix_descriptor_lease(
            lease.descriptor,
            None,
            "test receipt staging descriptor",
        )
        if descriptor_close is not None:
            failures.append(descriptor_close)
        if verify_root:
            try:
                self.posix._verify_darwin_private_directory(self.binding, stage)
            except BaseException as error:
                failures.append(error)
        private_close = self.posix._close_posix_descriptor_lease(
            lease.private_directory,
            None,
            "test private receipt directory descriptor",
        )
        if private_close is not None:
            failures.append(private_close)
        if failures:
            self.fail("; ".join(str(failure) for failure in failures))

    def test_existing_stable_root_rejects_wrong_type_symlink_mode_and_owner(self) -> None:
        cases = ("file", "symlink", "mode", "owner")
        for case in cases:
            with self.subTest(case=case):
                private_root = self.parent / PRIVATE_ROOT
                target = self.parent / "symlink-target"
                if case == "file":
                    private_root.write_bytes(b"not a directory")
                elif case == "symlink":
                    target.mkdir()
                    private_root.symlink_to(target.name)
                else:
                    private_root.mkdir(mode=0o700)
                    if case == "mode":
                        private_root.chmod(0o755)

                expected_owner = os.geteuid()
                with (
                    mock.patch.object(
                        self.posix.os,
                        "geteuid",
                        return_value=expected_owner + 1 if case == "owner" else expected_owner,
                    ),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    self.posix._open_darwin_receipt_stage(
                        self.binding,
                        PRIVATE_ROOT,
                        self._stage_lease(),
                    )
                self.assertEqual(raised.exception.code, "output-temporary-invalid")
                self.assertFalse((self.parent / "receipt.json").exists())

                if private_root.is_symlink() or private_root.is_file():
                    private_root.unlink()
                else:
                    private_root.rmdir()
                if target.exists():
                    target.rmdir()

    def test_outer_root_replacement_after_open_cannot_redirect_inner_stage(self) -> None:
        real_open = self.posix._open_posix_descriptor
        private_root = self.parent / PRIVATE_ROOT
        relocated = self.parent / f"{PRIVATE_ROOT}.relocated"
        replaced = False

        def open_then_replace(
            lease: Any,
            path: object,
            flags: int,
            *args: object,
            **kwargs: object,
        ) -> int:
            nonlocal replaced
            descriptor = real_open(lease, path, flags, *args, **kwargs)
            if path == PRIVATE_ROOT and not replaced:
                replaced = True
                private_root.rename(relocated)
                private_root.mkdir(mode=0o700)
            return descriptor

        stage_lease = self._stage_lease()
        with mock.patch.object(
            self.posix,
            "_open_posix_descriptor",
            side_effect=open_then_replace,
        ):
            stage = self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                stage_lease,
            )
        self.assertTrue(replaced)
        self.assertFalse((self.parent / "receipt.json").exists())
        with self.assertRaises(anchored.AnchoredOutputError) as raised:
            self.posix._verify_darwin_private_directory(self.binding, stage)
        self.assertEqual(raised.exception.code, "output-cleanup-retained")

        self._close_stage(stage, stage_lease, verify_root=False)
        private_root.rmdir()
        relocated.rmdir()

    def test_inner_stage_swap_is_rejected_without_publication_or_unsafe_cleanup(self) -> None:
        stage_name = "a" * 32 + ".tmp"
        swapped_name = "swapped.tmp"
        stage_lease = self._stage_lease()
        with mock.patch.object(self.posix.secrets, "token_hex", return_value="a" * 32):
            stage = self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                stage_lease,
            )
        private_descriptor = stage.private_directory_descriptor
        os.rename(
            stage_name,
            swapped_name,
            src_dir_fd=private_descriptor,
            dst_dir_fd=private_descriptor,
        )
        replacement = os.open(
            stage_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=private_descriptor,
        )
        os.close(replacement)

        with self.assertRaises(anchored.AnchoredOutputError) as raised:
            self.posix._cleanup_darwin_named_stage(stage_lease)
        self.assertEqual(raised.exception.code, "output-cleanup-retained")
        self.assertFalse((self.parent / "receipt.json").exists())

        private_root = self.parent / PRIVATE_ROOT
        self.assertTrue((private_root / stage_name).is_file())
        self.assertTrue((private_root / swapped_name).is_file())
        stage_lease.named_stage_retained = True
        self.posix._close_posix_descriptor_lease(stage_lease.descriptor, None, "test stage")
        self.posix._close_posix_descriptor_lease(stage_lease.private_directory, None, "test private directory")
        (private_root / stage_name).unlink()
        (private_root / swapped_name).unlink()
        private_root.rmdir()

    def test_new_and_reused_stable_root_are_canonical_under_extreme_umasks(self) -> None:
        first_lease = self._stage_lease()
        previous_umask = os.umask(0o777)
        try:
            first = self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                first_lease,
            )
        finally:
            os.umask(previous_umask)
        self.assertEqual(stat.S_IMODE((self.parent / PRIVATE_ROOT).stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.fstat(first.descriptor).st_mode), 0o600)
        self.assertEqual(os.fstat(first.descriptor).st_nlink, 1)
        self._close_stage(first, first_lease)

        second_lease = self._stage_lease()
        previous_umask = os.umask(0o000)
        try:
            second = self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                second_lease,
            )
        finally:
            os.umask(previous_umask)
        self.assertEqual(stat.S_IMODE((self.parent / PRIVATE_ROOT).stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.fstat(second.descriptor).st_mode), 0o600)
        self.assertEqual(os.fstat(second.descriptor).st_nlink, 1)
        self._close_stage(second, second_lease)
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_effect_then_interruption_at_every_posix_seal_boundary_is_recoverable(
        self,
    ) -> None:
        cases = (
            ("ancestor-chmod", "ancestor", "chmod", False),
            ("ancestor-fchmod", "ancestor", "fchmod", False),
            ("darwin-root-chmod", "darwin", "chmod", False),
            ("darwin-root-fchmod", "darwin", "fchmod", True),
            ("darwin-stage-fchmod", "darwin", "fchmod", False),
        )
        payload = b'{"status":"verified"}\n'

        for label, scope, operation_name, force_root_fchmod in cases:
            with self.subTest(boundary=label):
                primary = KeyboardInterrupt(f"{label} returned before assignment")
                opened: list[int] = []
                output = self.root / label / "receipt.json"
                real_operation = getattr(self.posix.os, operation_name)
                owner: anchored._OutputParentBindingLease | None = None
                stage_lease: Any | None = None
                private_root_name: str | None = None

                def effect_then_interrupt(*arguments: Any, **kwargs: Any) -> object:
                    real_operation(*arguments, **kwargs)
                    raise primary

                if scope == "ancestor":
                    owner = anchored._OutputParentBindingLease()
                    real_open = anchored._open_posix_descriptor

                    def record_open(
                        descriptor_lease: anchored._PosixDescriptorLease,
                        path: os.PathLike[str] | str,
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

                    def attempt() -> None:
                        assert owner is not None
                        anchored._open_rooted_posix_parent(
                            self.root,
                            output,
                            (label, output.name),
                            owner,
                        )

                    open_patch = mock.patch.object(
                        anchored,
                        "_open_posix_descriptor",
                        side_effect=record_open,
                    )
                else:
                    stage_lease = self._stage_lease()
                    private_root_name = f".{label}"
                    real_open = self.posix._open_posix_descriptor

                    def record_open(
                        descriptor_lease: anchored._PosixDescriptorLease,
                        path: os.PathLike[str] | str,
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

                    def attempt() -> None:
                        self.posix._open_darwin_receipt_stage(
                            self.binding,
                            private_root_name,
                            stage_lease,
                        )

                    open_patch = mock.patch.object(
                        self.posix,
                        "_open_posix_descriptor",
                        side_effect=record_open,
                    )

                canonical_patch = (
                    mock.patch.object(
                        self.posix,
                        "_darwin_private_directory_is_canonical",
                        side_effect=(True, False),
                    )
                    if force_root_fchmod
                    else nullcontext()
                )
                with (
                    open_patch,
                    mock.patch.object(
                        self.posix.os,
                        operation_name,
                        side_effect=effect_then_interrupt,
                    ),
                    canonical_patch,
                    self.assertRaises(KeyboardInterrupt) as raised,
                ):
                    attempt()

                self.assertIs(raised.exception, primary)
                self.assertFalse(output.exists())
                for descriptor in opened:
                    with self.assertRaises(OSError) as closed:
                        os.fstat(descriptor)
                    self.assertEqual(closed.exception.errno, errno.EBADF)

                if scope == "ancestor":
                    assert owner is not None
                    binding = owner.binding
                    self.assertIsNotNone(binding)
                    assert binding is not None
                    self.assertTrue(binding.is_closed)
                    anchored.publish_identical_receipt_bytes(output, payload)
                    self.assertEqual(output.read_bytes(), payload)
                else:
                    assert stage_lease is not None
                    assert private_root_name is not None
                    self.assertIsNone(stage_lease.descriptor.descriptor)
                    self.assertIsNone(stage_lease.private_directory.descriptor)
                    retry_lease = self._stage_lease()
                    retry_stage = self.posix._open_darwin_receipt_stage(
                        self.binding,
                        private_root_name,
                        retry_lease,
                    )
                    self._close_stage(retry_stage, retry_lease)
                    (self.parent / private_root_name).rmdir()

    def test_mkdir_effect_then_file_exists_is_treated_as_changed(self) -> None:
        private_root = self.parent / PRIVATE_ROOT
        real_mkdir = self.posix.os.mkdir

        def mkdir_then_file_exists(
            name: str,
            mode: int,
            *,
            dir_fd: int,
        ) -> None:
            real_mkdir(name, mode, dir_fd=dir_fd)
            raise FileExistsError("mkdir completed before its return was observed")

        previous_umask = os.umask(0o777)
        try:
            with (
                mock.patch.object(
                    self.posix.os,
                    "mkdir",
                    side_effect=mkdir_then_file_exists,
                ),
                self.assertRaises(anchored.AnchoredOutputError) as changed,
            ):
                self.posix._open_darwin_receipt_stage(
                    self.binding,
                    PRIVATE_ROOT,
                    self._stage_lease(),
                )
        finally:
            os.umask(previous_umask)

        self.assertEqual(changed.exception.code, "output-temporary-invalid")
        self.assertEqual(stat.S_IMODE(private_root.stat().st_mode), 0o000)
        private_root.rmdir()

        private_root.mkdir(mode=0o700)
        private_root.chmod(0o755)
        before = private_root.stat()
        with self.assertRaises(anchored.AnchoredOutputError) as raised:
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                self._stage_lease(),
            )
        after = private_root.stat()
        self.assertEqual(raised.exception.code, "output-temporary-invalid")
        self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
        self.assertEqual(stat.S_IMODE(after.st_mode), 0o755)
        self.assertEqual(list(private_root.iterdir()), [])
        private_root.rmdir()

    def test_native_stage_open_interrupt_before_identity_removes_named_inode(self) -> None:
        stage_name = "b" * 32 + ".tmp"
        lease = self._stage_lease()
        interruption = KeyboardInterrupt("native stage open returned before identity")
        real_open = self.posix._open_posix_descriptor
        triggered = False
        opened_descriptor: int | None = None

        def open_then_interrupt(
            descriptor_lease: anchored._PosixDescriptorLease,
            path: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal opened_descriptor, triggered
            descriptor = real_open(
                descriptor_lease,
                path,
                flags,
                mode,
                dir_fd=dir_fd,
            )
            if not triggered and descriptor_lease is lease.descriptor:
                triggered = True
                opened_descriptor = descriptor
                raise interruption
            return descriptor

        with (
            mock.patch.object(self.posix.secrets, "token_hex", return_value="b" * 32),
            mock.patch.object(
                self.posix,
                "_open_posix_descriptor",
                side_effect=open_then_interrupt,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertIsNotNone(opened_descriptor)
        self.assertFalse((self.parent / PRIVATE_ROOT / stage_name).exists())
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        assert opened_descriptor is not None
        with self.assertRaises(OSError):
            os.fstat(opened_descriptor)
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_native_stage_open_interrupt_never_unlinks_swapped_entry(self) -> None:
        stage_name = "c" * 32 + ".tmp"
        relocated_name = "relocated.tmp"
        lease = self._stage_lease()
        interruption = KeyboardInterrupt("native stage open returned before identity")
        real_open = self.posix._open_posix_descriptor
        triggered = False

        def open_then_swap_and_interrupt(
            descriptor_lease: anchored._PosixDescriptorLease,
            path: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal triggered
            descriptor = real_open(
                descriptor_lease,
                path,
                flags,
                mode,
                dir_fd=dir_fd,
            )
            if not triggered and descriptor_lease is lease.descriptor:
                triggered = True
                assert dir_fd is not None
                os.rename(
                    stage_name,
                    relocated_name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                )
                replacement = os.open(
                    stage_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=dir_fd,
                )
                os.close(replacement)
                raise interruption
            return descriptor

        with (
            mock.patch.object(self.posix.secrets, "token_hex", return_value="c" * 32),
            mock.patch.object(
                self.posix,
                "_open_posix_descriptor",
                side_effect=open_then_swap_and_interrupt,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertTrue(triggered)
        self.assertIs(raised.exception, interruption)
        self.assertIn(
            "staging entry changed and was left untouched",
            "\n".join(getattr(interruption, "__notes__", ())),
        )
        private_root = self.parent / PRIVATE_ROOT
        self.assertTrue((private_root / stage_name).is_file())
        self.assertTrue((private_root / relocated_name).is_file())
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        (private_root / stage_name).unlink()
        (private_root / relocated_name).unlink()
        private_root.rmdir()

    def test_post_native_file_exists_seam_cleans_original_stage_name(self) -> None:
        first_stage_name = "e" * 32 + ".tmp"
        second_stage_name = "f" * 32 + ".tmp"
        lease = self._stage_lease()
        collision = FileExistsError("post-native collision seam")
        real_open = self.posix._open_posix_descriptor
        opened_descriptor: int | None = None

        def open_then_report_collision(
            descriptor_lease: Any,
            path: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal opened_descriptor
            descriptor = real_open(
                descriptor_lease,
                path,
                flags,
                mode,
                dir_fd=dir_fd,
            )
            if path == first_stage_name:
                opened_descriptor = descriptor
                raise collision
            return descriptor

        with (
            mock.patch.object(
                self.posix.secrets,
                "token_hex",
                side_effect=("e" * 32, "f" * 32),
            ),
            mock.patch.object(
                self.posix,
                "_open_posix_descriptor",
                side_effect=open_then_report_collision,
            ),
            self.assertRaises(FileExistsError) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertIs(raised.exception, collision)
        self.assertIsNotNone(opened_descriptor)
        private_root = self.parent / PRIVATE_ROOT
        self.assertFalse((private_root / first_stage_name).exists())
        self.assertFalse((private_root / second_stage_name).exists())
        self.assertIsNone(lease.named_stage_name)
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        assert opened_descriptor is not None
        with self.assertRaises(OSError):
            os.fstat(opened_descriptor)
        private_root.rmdir()

    def test_failed_stage_keeps_private_parent_when_stage_close_is_exhausted(
        self,
    ) -> None:
        stage_name = "9" * 32 + ".tmp"
        lease = self._stage_lease()
        primary = OSError("stage validation failed")
        close_attempts: list[str] = []

        def leave_stage_open(
            descriptor_lease: Any,
            _primary: BaseException | None,
            _context: str,
        ) -> BaseException | None:
            close_attempts.append("stage" if descriptor_lease is lease.descriptor else "private")
            return OSError("modeled exhausted close")

        with (
            mock.patch.object(
                self.posix.secrets,
                "token_hex",
                return_value="9" * 32,
            ),
            mock.patch.object(
                self.posix,
                "_receipt_mode_is_canonical",
                side_effect=primary,
            ),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=leave_stage_open,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertIs(raised.exception, primary)
        self.assertEqual(close_attempts, ["stage"])
        self.assertIsNotNone(lease.descriptor.descriptor)
        self.assertIsNotNone(lease.private_directory.descriptor)
        private_root = self.parent / PRIVATE_ROOT
        self.assertFalse((private_root / stage_name).exists())

        self.assertIsNone(
            self.posix._close_posix_descriptor_lease(
                lease.descriptor,
                None,
                "test retained stage descriptor",
            )
        )
        self.assertIsNone(
            self.posix._close_posix_descriptor_lease(
                lease.private_directory,
                None,
                "test retained private directory descriptor",
            )
        )
        private_root.rmdir()

    def test_cleanup_reobserves_stage_after_false_missing_return_gap(self) -> None:
        private_root = self.parent / PRIVATE_ROOT
        private_root.mkdir(mode=0o700)
        stage_name = "f" * 32 + ".tmp"
        stage_path = private_root / stage_name
        stage_path.write_bytes(b"")
        stage = stage_path.stat()
        directory_descriptor = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
        real_stat = os.stat
        stat_calls = 0

        def stat_then_report_missing(*args: Any, **kwargs: Any) -> os.stat_result:
            nonlocal stat_calls
            stat_calls += 1
            result = real_stat(*args, **kwargs)
            if stat_calls == 1:
                raise FileNotFoundError("stat returned before assignment")
            return result

        try:
            with mock.patch.object(self.posix.os, "stat", side_effect=stat_then_report_missing):
                self.posix._unlink_darwin_stage_if_identity(
                    directory_descriptor,
                    stage_name,
                    (stage.st_dev, stage.st_ino),
                )
        finally:
            os.close(directory_descriptor)

        self.assertEqual(stat_calls, 2)
        self.assertFalse(stage_path.exists())
        private_root.rmdir()

    def test_publication_fallback_removes_stage_when_opener_cleanup_is_bypassed(self) -> None:
        private_root = self.parent / PRIVATE_ROOT
        stage_name = "a" * 32 + ".tmp"
        primary = KeyboardInterrupt("opener exception-table gap")
        opened_descriptors: tuple[int, int] | None = None

        def open_then_escape(_binding: Any, _temporary_name: str, lease: Any) -> Any:
            nonlocal opened_descriptors
            private_root.mkdir(mode=0o700)
            private_descriptor = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
            stage_descriptor = os.open(
                stage_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=private_descriptor,
            )
            lease.private_directory.descriptor_result = ctypes.c_int(private_descriptor)
            lease.descriptor.descriptor_result = ctypes.c_int(stage_descriptor)
            lease.named_stage_name = stage_name
            opened_descriptors = (stage_descriptor, private_descriptor)
            raise primary

        binding = SimpleNamespace(
            leaf="receipt.json",
            stat=mock.Mock(side_effect=FileNotFoundError),
            close=mock.Mock(return_value=()),
        )
        with (
            mock.patch.object(
                self.posix,
                "sys",
                SimpleNamespace(platform="darwin"),
            ),
            mock.patch.object(
                self.posix,
                "_open_posix_receipt_stage",
                side_effect=open_then_escape,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            self.posix._publish_posix_receipt_bytes(
                self.parent / "receipt.json",
                b"payload",
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )

        self.assertIs(raised.exception, primary)
        self.assertFalse((private_root / stage_name).exists())
        binding.close.assert_called_once_with()
        assert opened_descriptors is not None
        for descriptor in opened_descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        private_root.rmdir()

    def test_binding_close_return_interrupt_preserves_primary_failure(self) -> None:
        primary = OSError("publication failed")
        interruption = KeyboardInterrupt("binding close returned before assignment")
        close_calls = 0
        triggered = False

        def close() -> tuple[BaseException, ...]:
            nonlocal close_calls, triggered
            close_calls += 1
            triggered = True
            raise interruption

        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=primary),
            close=close,
        )

        with self.assertRaises(OSError) as raised:
            self.posix._publish_posix_receipt_bytes(
                self.parent / "receipt.json",
                b"payload",
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )

        self.assertTrue(triggered)
        self.assertEqual(close_calls, 1)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            "binding close returned before assignment",
            "\n".join(getattr(primary, "__notes__", ())),
        )

    def test_public_descriptor_close_return_interrupt_preserves_primary_failure(self) -> None:
        public = self.parent / "public.json"
        public.write_bytes(b"payload")
        primary = OSError("public validation failed")
        interruption = KeyboardInterrupt("public descriptor close returned before assignment")
        opened_descriptor: int | None = None
        triggered = False
        descriptor_lease = anchored._PosixDescriptorLease()

        def open_read(_name: str, lease: Any) -> int:
            nonlocal opened_descriptor
            opened_descriptor = anchored._open_posix_descriptor(
                lease,
                public,
                os.O_RDONLY,
            )
            return opened_descriptor

        binding = SimpleNamespace(leaf=public.name, open_read=open_read)

        real_close = self.posix._close_posix_descriptor_lease

        def close_then_interrupt(
            lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            nonlocal triggered
            result = real_close(lease, active_primary, context)
            if lease is descriptor_lease and not triggered:
                triggered = True
                raise interruption
            return result

        with (
            mock.patch.object(
                self.posix,
                "_validate_exact_receipt_descriptor",
                side_effect=primary,
            ),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=close_then_interrupt,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._sync_posix_public_descriptor(
                binding,
                b"payload",
                (1, 2),
                descriptor_lease,
            )

        self.assertTrue(triggered)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            "public descriptor close returned before assignment",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        assert opened_descriptor is not None
        with self.assertRaises(OSError):
            os.fstat(opened_descriptor)

    def test_darwin_stage_close_return_interrupt_still_closes_private_directory(self) -> None:
        stage_name = "d" * 32 + ".tmp"
        lease = self._stage_lease()
        primary = OSError("stage validation failed")
        interruption = KeyboardInterrupt("stage close returned before assignment")
        stage_descriptor: int | None = None
        private_descriptor: int | None = None
        triggered = False

        real_close = self.posix._close_posix_descriptor_lease

        def close_then_interrupt(
            descriptor_lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            nonlocal private_descriptor, stage_descriptor, triggered
            descriptor = descriptor_lease.descriptor
            if descriptor_lease is lease.descriptor:
                stage_descriptor = descriptor
            elif descriptor_lease is lease.private_directory:
                private_descriptor = descriptor
            result = real_close(descriptor_lease, active_primary, context)
            if descriptor_lease is lease.descriptor and not triggered:
                triggered = True
                raise interruption
            return result

        with (
            mock.patch.object(self.posix.secrets, "token_hex", return_value="d" * 32),
            mock.patch.object(
                self.posix,
                "_receipt_mode_is_canonical",
                side_effect=primary,
            ),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=close_then_interrupt,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertTrue(triggered)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            "stage close returned before assignment",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        self.assertFalse((self.parent / PRIVATE_ROOT / stage_name).exists())
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        assert stage_descriptor is not None
        assert private_descriptor is not None
        with self.assertRaises(OSError):
            os.fstat(stage_descriptor)
        with self.assertRaises(OSError):
            os.fstat(private_descriptor)
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_linux_stage_close_return_interrupt_preserves_primary_failure(self) -> None:
        stage_path = self.parent / "linux-stage.tmp"
        stage_path.write_bytes(b"")
        lease = self._stage_lease()
        primary = OSError("stage chmod failed")
        interruption = KeyboardInterrupt("Linux stage close returned before assignment")
        opened_descriptor: int | None = None
        triggered = False

        def open_stage(
            descriptor_lease: Any,
            _path: object,
            _flags: int,
            _mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal opened_descriptor
            self.assertIsNotNone(dir_fd)
            opened_descriptor = os.open(stage_path, os.O_RDWR)
            descriptor_lease.descriptor_result = ctypes.c_int(opened_descriptor)
            return opened_descriptor

        real_close = self.posix._close_posix_descriptor_lease

        def close_then_interrupt(
            descriptor_lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            nonlocal triggered
            result = real_close(descriptor_lease, active_primary, context)
            if descriptor_lease is lease.descriptor and not triggered:
                triggered = True
                raise interruption
            return result

        with (
            mock.patch.object(self.posix.sys, "platform", "linux"),
            mock.patch.object(self.posix.os, "O_TMPFILE", 0x400000, create=True),
            mock.patch.object(self.posix, "_open_posix_descriptor", side_effect=open_stage),
            mock.patch.object(self.posix.os, "fchmod", side_effect=primary),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=close_then_interrupt,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._open_posix_receipt_stage(
                self.binding,
                "",
                lease,
            )

        self.assertTrue(triggered)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            "Linux stage close returned before assignment",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        self.assertIsNone(lease.descriptor.descriptor)
        assert opened_descriptor is not None
        with self.assertRaises(OSError):
            os.fstat(opened_descriptor)

    def test_publication_stage_close_return_interrupt_still_closes_private_lease(self) -> None:
        stage_path = self.parent / "publisher-stage.tmp"
        stage_path.write_bytes(b"")
        primary = OSError("publisher stage inspection failed")
        interruption = KeyboardInterrupt("publisher stage close returned before assignment")
        opened_descriptors: tuple[int, int] | None = None
        close_called = False
        triggered = False

        def open_stage(_binding: Any, _temporary_name: str, lease: Any) -> Any:
            nonlocal opened_descriptors
            stage_descriptor = os.open(stage_path, os.O_RDWR)
            private_descriptor = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
            lease.descriptor.descriptor_result = ctypes.c_int(stage_descriptor)
            lease.private_directory.descriptor_result = ctypes.c_int(private_descriptor)
            stage = self.posix._PosixReceiptStage(descriptor=stage_descriptor)
            lease.stage = stage
            opened_descriptors = (stage_descriptor, private_descriptor)
            return stage

        def close() -> tuple[BaseException, ...]:
            nonlocal close_called
            close_called = True
            return ()

        binding = SimpleNamespace(
            leaf="receipt.json",
            descriptors=(8,),
            stat=mock.Mock(side_effect=FileNotFoundError),
            close=close,
        )

        real_close = self.posix._close_posix_descriptor_lease

        def close_then_interrupt(
            descriptor_lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            nonlocal triggered
            result = real_close(descriptor_lease, active_primary, context)
            if context == "receipt staging descriptor" and not triggered:
                triggered = True
                raise interruption
            return result

        with (
            mock.patch.object(self.posix.sys, "platform", "darwin"),
            mock.patch.object(self.posix, "_open_posix_receipt_stage", side_effect=open_stage),
            mock.patch.object(self.posix.os, "fstat", side_effect=primary),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=close_then_interrupt,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._publish_posix_receipt_bytes(
                self.parent / "receipt.json",
                b"payload",
                binding,
                self.posix._PosixReceiptPublicationLease(binding),
            )

        self.assertTrue(triggered)
        self.assertTrue(close_called)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            "publisher stage close returned before assignment",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        assert opened_descriptors is not None
        for descriptor in opened_descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_stage_lease_retains_ownership_when_caller_is_interrupted_before_store(self) -> None:
        lease = self._stage_lease()
        interruption = KeyboardInterrupt("stage return boundary")
        real_open = self.posix._open_darwin_receipt_stage

        def acquire() -> Any:
            stage = self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )
            return stage

        def open_then_interrupt(
            parent_binding: Any,
            private_directory_name: str,
            stage_lease: Any,
        ) -> Any:
            real_open(parent_binding, private_directory_name, stage_lease)
            raise interruption

        with mock.patch.object(
            self.posix,
            "_open_darwin_receipt_stage",
            side_effect=open_then_interrupt,
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                acquire()

        self.assertIs(raised.exception, interruption)
        stage = lease.stage
        self.assertIsNotNone(stage)
        assert stage is not None
        descriptor = stage.descriptor
        private_descriptor = stage.private_directory_descriptor
        self._close_stage(stage, lease)
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        with self.assertRaises(OSError):
            os.fstat(private_descriptor)
        (self.parent / PRIVATE_ROOT).rmdir()

    @unittest.skipUnless(sys.platform == "darwin", "native macOS ACL contract")
    def test_native_acl_query_and_unsupported_query_fail_closed(self) -> None:
        candidate = self.parent / "acl-candidate"
        candidate.write_bytes(b"candidate")
        candidate.chmod(0o600)
        descriptor = os.open(candidate, os.O_RDONLY)
        try:
            self.assertFalse(anchored._darwin_descriptor_has_extended_acl(descriptor))
            self._add_everyone_acl(candidate)
            self.assertTrue(anchored._darwin_descriptor_has_extended_acl(descriptor))
            self.assertTrue(
                anchored._darwin_descriptor_has_extended_acl(
                    descriptor,
                    error_code="output-parent-invalid",
                    context="native allow-ACL ancestor",
                    allow_deny_only=True,
                )
            )
            with (
                mock.patch.object(anchored, "_posix_libc", return_value={}),
                self.assertRaises(anchored.AnchoredOutputError) as unavailable,
            ):
                anchored._darwin_descriptor_has_extended_acl(descriptor)
            self.assertEqual(unavailable.exception.code, "output-anchor-unavailable")
        finally:
            os.close(descriptor)
            self._clear_acl(candidate)
            candidate.unlink()

    @unittest.skipUnless(sys.platform == "darwin", "native macOS deny-only ACL contract")
    def test_native_deny_only_intermediate_supports_publish_and_idempotency(self) -> None:
        denied_ancestor = self.parent / "deny-only-ancestor"
        final_parent = denied_ancestor / "final-parent"
        denied_ancestor.mkdir(mode=0o700)
        final_parent.mkdir(mode=0o700)
        self._add_everyone_deny_acl(denied_ancestor)
        output = final_parent / "receipt.json"
        try:
            anchored.publish_identical_receipt_bytes(output, b"receipt")
            anchored.publish_identical_receipt_bytes(output, b"receipt")
            self.assertEqual(output.read_bytes(), b"receipt")
            self._add_everyone_deny_acl(final_parent)
            try:
                with self.assertRaises(anchored.AnchoredOutputError) as strict_parent:
                    anchored.publish_identical_receipt_bytes(output, b"receipt")
                self.assertEqual(strict_parent.exception.code, "output-parent-invalid")
            finally:
                self._clear_acl(final_parent)
        finally:
            if output.exists():
                output.unlink()
            private_root = final_parent / PRIVATE_ROOT
            if private_root.exists():
                private_root.rmdir()
            self._clear_acl(denied_ancestor)
            final_parent.rmdir()
            denied_ancestor.rmdir()

    def test_modeled_deny_only_acl_is_accepted_after_descriptor_validation(self) -> None:
        (
            libc,
            free_acl,
            valid_acl,
            structurally_valid_acl,
            get_entry,
            get_tag_type,
        ) = self._modeled_acl_api(
            (
                anchored._DARWIN_ACL_EXTENDED_DENY,
                anchored._DARWIN_ACL_EXTENDED_DENY,
            )
        )
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
        ):
            self.assertFalse(
                anchored._darwin_descriptor_has_extended_acl(
                    7,
                    error_code="output-parent-invalid",
                    context="modeled intermediate ancestor",
                    allow_deny_only=True,
                )
            )

        self.assertEqual(valid_acl.call_args.args[:2], (7, anchored._DARWIN_ACL_TYPE_EXTENDED))
        structurally_valid_acl.assert_not_called()
        self.assertEqual(
            [call.args[1] for call in get_entry.call_args_list],
            [
                anchored._DARWIN_ACL_FIRST_ENTRY,
                anchored._DARWIN_ACL_NEXT_ENTRY,
                anchored._DARWIN_ACL_NEXT_ENTRY,
            ],
        )
        self.assertEqual(get_tag_type.call_count, 2)
        self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_allow_and_unknown_entries_are_rejected(self) -> None:
        for tag_type in (anchored._DARWIN_ACL_EXTENDED_ALLOW, 99):
            with self.subTest(tag_type=tag_type):
                libc, free_acl, *_operations = self._modeled_acl_api((tag_type,))
                with (
                    mock.patch.object(anchored, "_posix_libc", return_value=libc),
                    mock.patch.object(anchored.sys, "platform", "darwin"),
                ):
                    self.assertTrue(
                        anchored._darwin_descriptor_has_extended_acl(
                            7,
                            error_code="output-parent-invalid",
                            context="modeled intermediate ancestor",
                            allow_deny_only=True,
                        )
                    )
                self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_validation_and_enumeration_fail_closed(self) -> None:
        cases = (
            (-1, None, 0),
            (0, 1, 0),
            (0, None, -1),
        )
        for validity_status, enumeration_status, tag_status in cases:
            with self.subTest(
                validity_status=validity_status,
                enumeration_status=enumeration_status,
                tag_status=tag_status,
            ):
                libc, free_acl, *_operations = self._modeled_acl_api(
                    (anchored._DARWIN_ACL_EXTENDED_DENY,),
                    validity_status=validity_status,
                    enumeration_status=enumeration_status,
                    tag_status=tag_status,
                )
                with (
                    mock.patch.object(anchored, "_posix_libc", return_value=libc),
                    mock.patch.object(anchored.ctypes, "get_errno", return_value=errno.EINVAL),
                    mock.patch.object(anchored.sys, "platform", "darwin"),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored._darwin_descriptor_has_extended_acl(
                        7,
                        error_code="output-parent-invalid",
                        context="modeled intermediate ancestor",
                        allow_deny_only=True,
                    )
                self.assertEqual(raised.exception.code, "output-parent-invalid")
                self.assertIn("modeled intermediate ancestor", str(raised.exception))
                self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_nonnull_acl_with_no_entries_is_rejected(self) -> None:
        libc, free_acl, *_operations = self._modeled_acl_api(())
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
        ):
            self.assertTrue(
                anchored._darwin_descriptor_has_extended_acl(
                    7,
                    error_code="output-parent-invalid",
                    context="modeled empty extended ACL",
                    allow_deny_only=True,
                )
            )
        self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_unsupported_context_validation_uses_structural_validation(self) -> None:
        (
            libc,
            free_acl,
            valid_acl,
            structurally_valid_acl,
            _get_entry,
            _get_tag_type,
        ) = self._modeled_acl_api((anchored._DARWIN_ACL_EXTENDED_DENY,))
        def unsupported_context(*_arguments: object) -> int:
            ctypes.set_errno(errno.ENOTSUP)
            return -1

        valid_acl.side_effect = unsupported_context
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
        ):
            self.assertFalse(
                anchored._darwin_descriptor_has_extended_acl(
                    7,
                    error_code="output-parent-invalid",
                    context="modeled intermediate ancestor",
                    allow_deny_only=True,
                )
            )
        structurally_valid_acl.assert_called_once()
        self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_structural_validation_failure_is_rejected(self) -> None:
        libc, free_acl, valid_acl, structurally_valid_acl, *_operations = (
            self._modeled_acl_api(
                (anchored._DARWIN_ACL_EXTENDED_DENY,),
                structural_status=-1,
            )
        )
        def unsupported_context(*_arguments: object) -> int:
            ctypes.set_errno(errno.ENOTSUP)
            return -1

        valid_acl.side_effect = unsupported_context
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(
                7,
                error_code="output-parent-invalid",
                context="modeled intermediate ancestor",
                allow_deny_only=True,
            )
        self.assertEqual(raised.exception.code, "output-parent-invalid")
        structurally_valid_acl.assert_called_once()
        self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_enumeration_interrupt_frees_allocation_once(self) -> None:
        primary = KeyboardInterrupt("ACL enumeration returned before assignment")
        libc, free_acl, *_operations = self._modeled_acl_api(
            (anchored._DARWIN_ACL_EXTENDED_DENY,),
            enumeration_error=primary,
        )
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(
                7,
                error_code="output-parent-invalid",
                context="modeled intermediate ancestor",
                allow_deny_only=True,
            )
        self.assertIs(raised.exception, primary)
        self.assertEqual(len(free_acl.calls), 1)

    def test_modeled_acl_enumeration_is_bounded(self) -> None:
        libc, free_acl, *_operations, get_entry, get_tag_type = self._modeled_acl_api(
            (anchored._DARWIN_ACL_EXTENDED_DENY,)
            * (anchored._DARWIN_ACL_MAX_ENTRIES + 1)
        )
        with (
            mock.patch.object(anchored, "_posix_libc", return_value=libc),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(anchored.AnchoredOutputError) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(
                7,
                error_code="output-parent-invalid",
                context="modeled intermediate ancestor",
                allow_deny_only=True,
            )
        self.assertEqual(raised.exception.code, "output-parent-invalid")
        self.assertEqual(get_entry.call_count, anchored._DARWIN_ACL_MAX_ENTRIES + 1)
        self.assertEqual(get_tag_type.call_count, anchored._DARWIN_ACL_MAX_ENTRIES)
        self.assertEqual(len(free_acl.calls), 1)

    def test_acl_query_finalizer_recovers_cleanup_entry_interruption(self) -> None:
        interruption = KeyboardInterrupt("ACL query cleanup entry")
        get_acl, free_acl = self._run_acl_line_interruption(
            anchored._darwin_descriptor_has_extended_acl,
            "free_error = lease.close()",
            interruption,
        )

        self.assertEqual(len(get_acl.calls), 1)
        self.assertEqual(len(free_acl.calls), 1)

    def test_acl_cleanup_interruption_preserves_query_primary_and_finalizes(
        self,
    ) -> None:
        primary = SystemExit("ACL query primary")
        cleanup = KeyboardInterrupt("ACL cleanup interruption")

        class InterruptAfterResult(_LeaseAwareNativeCall):
            def __call__(self, *arguments: object) -> int:
                super().__call__(*arguments)
                raise primary

        cleanup_line = _source_line(
            anchored._close_darwin_acl_query_state,
            "pointer = state.pointer",
        )
        get_acl = InterruptAfterResult(1234)
        free_acl = _LeaseAwareNativeCall(0)
        triggered = False

        def trace(frame: FrameType, event: str, _argument: object) -> Any:
            nonlocal triggered
            if event == "call" and frame.f_code is anchored._close_darwin_acl_query_state.__code__:
                frame.f_trace = trace
                return trace
            if (
                event == "line"
                and frame.f_code is anchored._close_darwin_acl_query_state.__code__
                and frame.f_lineno == cleanup_line
                and not triggered
            ):
                triggered = True
                raise cleanup
            return trace

        previous_trace = sys.gettrace()
        try:
            with (
                mock.patch.object(
                    anchored,
                    "_posix_libc",
                    return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
                ),
                mock.patch.object(anchored.sys, "platform", "darwin"),
                self.assertRaises(SystemExit) as raised,
            ):
                sys.settrace(trace)
                anchored._darwin_descriptor_has_extended_acl(7)
        finally:
            sys.settrace(previous_trace)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, primary)
        self.assertIn(
            str(cleanup),
            "\n".join(getattr(primary, "__notes__", ())),
        )
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        gc.collect()
        self.assertEqual(len(get_acl.calls), 1)
        self.assertEqual(len(free_acl.calls), 1)

    def test_acl_query_finalizer_recovers_bounded_free_precall_interruptions(
        self,
    ) -> None:
        interruption = KeyboardInterrupt("ACL free before native call")

        class InterruptBeforeResult(_LeaseAwareNativeCall):
            def __init__(self) -> None:
                super().__init__(0)
                self.interruptions_remaining = 2
                self.native_calls = 0

            def __call__(self, *arguments: object) -> int:
                self.calls.append(arguments)
                if self.interruptions_remaining:
                    self.interruptions_remaining -= 1
                    raise interruption
                self.native_calls += 1
                result_type = self.restype
                checker = getattr(result_type, "_check_retval_", None)
                if callable(result_type) and callable(checker):
                    checker(result_type(self.result))
                return self.result

        get_acl = _LeaseAwareNativeCall(1234)
        free_acl = InterruptBeforeResult()
        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
            ),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(7)

        # Both explicit attempts were interrupted before the native call. Once
        # the traceback owner is released, the one finalizer call frees it.
        self.assertIs(raised.exception, interruption)
        interruption.__traceback__ = None
        gc.collect()
        self.assertEqual(len(free_acl.calls), 3)
        self.assertEqual(free_acl.native_calls, 1)

    def test_acl_query_recorded_free_result_is_never_replayed_after_gc(self) -> None:
        interruption = KeyboardInterrupt("ACL free returned before assignment")

        class InterruptAfterResult(_LeaseAwareNativeCall):
            def __call__(self, *arguments: object) -> int:
                super().__call__(*arguments)
                raise interruption

        get_acl = _LeaseAwareNativeCall(1234)
        free_acl = InterruptAfterResult(0)
        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
            ),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(7)

        self.assertIs(raised.exception, interruption)
        self.assertEqual(len(free_acl.calls), 1)
        interruption.__traceback__ = None
        gc.collect()
        self.assertEqual(len(free_acl.calls), 1)

    def test_acl_query_null_result_never_calls_free_after_gc(self) -> None:
        get_acl = _LeaseAwareNativeCall(0)
        free_acl = _LeaseAwareNativeCall(0)
        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
            ),
            mock.patch.object(anchored.ctypes, "get_errno", return_value=errno.ENOENT),
            mock.patch.object(anchored.sys, "platform", "darwin"),
        ):
            self.assertFalse(anchored._darwin_descriptor_has_extended_acl(7))

        gc.collect()
        self.assertEqual(len(get_acl.calls), 1)
        self.assertEqual(len(free_acl.calls), 0)

    def test_acl_query_retirement_precedes_interruptible_finalizer_detach(self) -> None:
        interruption = KeyboardInterrupt("ACL finalizer detach")
        _get_acl, free_acl = self._run_acl_line_interruption(
            anchored._DarwinAclQueryLease.close,
            "self._finalizer.detach()",
            interruption,
        )

        # The pointer was already retired. The still-live finalizer therefore
        # becomes a no-op rather than replaying the successful native free.
        self.assertEqual(len(free_acl.calls), 1)

    def test_acl_query_preserves_primary_and_never_replays_recorded_free(self) -> None:
        primary = KeyboardInterrupt("ACL query returned before assignment")

        class NativeCall:
            argtypes: object = None
            restype: object = None

            def __init__(self, result: int, interruption: BaseException | None = None) -> None:
                self.result = result
                self.interruption = interruption
                self.calls = 0

            def __call__(self, *_arguments: object) -> int:
                self.calls += 1
                result_type = self.restype
                checker = getattr(result_type, "_check_retval_", None)
                if callable(result_type) and callable(checker):
                    checker(result_type(self.result))
                if self.interruption is not None:
                    raise self.interruption
                return self.result

        get_acl = NativeCall(1234, primary)
        free_acl = NativeCall(-1)
        with (
            mock.patch.object(
                anchored,
                "_posix_libc",
                return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
            ),
            mock.patch.object(anchored.ctypes, "get_errno", return_value=errno.EIO),
            mock.patch.object(anchored.sys, "platform", "darwin"),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._darwin_descriptor_has_extended_acl(7)
        self.assertIs(raised.exception, primary)
        self.assertEqual(free_acl.calls, 1)
        self.assertIn("Could not release", "\n".join(getattr(primary, "__notes__", ())))

    def test_acl_query_maps_null_results_to_phase_context(self) -> None:
        class NativeCall:
            argtypes: object = None
            restype: object = None

            def __init__(self, result: int) -> None:
                self.result = result
                self.calls = 0

            def __call__(self, *_arguments: object) -> int:
                self.calls += 1
                result_type = self.restype
                checker = getattr(result_type, "_check_retval_", None)
                if callable(result_type) and callable(checker):
                    checker(result_type(self.result))
                return self.result

        unsupported_errno = getattr(errno, "EOPNOTSUPP", errno.ENOSYS)
        cases = (
            (unsupported_errno, "output-anchor-unavailable", unsupported_errno),
            (errno.EBADF, "output-parent-invalid", errno.EBADF),
            (errno.EACCES, "output-parent-invalid", errno.EACCES),
            (errno.EINVAL, "output-parent-invalid", errno.EINVAL),
            (errno.ENOMEM, "output-parent-invalid", errno.ENOMEM),
            (0, "output-parent-invalid", errno.EIO),
        )
        for reported_errno, expected_code, concrete_errno in cases:
            with self.subTest(reported_errno=reported_errno):
                get_acl = NativeCall(0)
                free_acl = NativeCall(0)
                with (
                    mock.patch.object(
                        anchored,
                        "_posix_libc",
                        return_value={"acl_get_fd_np": get_acl, "acl_free": free_acl},
                    ),
                    mock.patch.object(
                        anchored.ctypes,
                        "get_errno",
                        return_value=reported_errno,
                    ),
                    mock.patch.object(anchored.sys, "platform", "darwin"),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored._darwin_descriptor_has_extended_acl(
                        7,
                        error_code="output-parent-invalid",
                        context="modeled output parent",
                    )

                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(get_acl.calls, 1)
                self.assertEqual(free_acl.calls, 0)
                self.assertIsInstance(raised.exception.__cause__, OSError)
                assert isinstance(raised.exception.__cause__, OSError)
                self.assertEqual(raised.exception.__cause__.errno, concrete_errno)
                self.assertIn("modeled output parent", str(raised.exception))

    @unittest.skipUnless(sys.platform == "darwin", "native macOS ACL contract")
    def test_native_acl_parent_root_stage_and_public_receipt_are_rejected(self) -> None:
        acl_parent = self.root / "acl-parent"
        acl_parent.mkdir(mode=0o700)
        self._add_everyone_acl(acl_parent)
        parent_lease = anchored._OutputParentBindingLease()
        try:
            with self.assertRaises(anchored.AnchoredOutputError) as unsafe_parent:
                anchored._open_rooted_posix_parent(
                    self.root,
                    acl_parent / "receipt.json",
                    (acl_parent.name, "receipt.json"),
                    parent_lease,
                )
            self.assertEqual(unsafe_parent.exception.code, "output-parent-invalid")
        finally:
            parent_lease.close()
            self._clear_acl(acl_parent)
            acl_parent.rmdir()

        private_root = self.parent / PRIVATE_ROOT
        private_root.mkdir(mode=0o700)
        self._add_everyone_acl(private_root)
        try:
            with self.assertRaises(anchored.AnchoredOutputError) as unsafe_root:
                self.posix._open_darwin_receipt_stage(
                    self.binding,
                    PRIVATE_ROOT,
                    self._stage_lease(),
                )
            self.assertEqual(unsafe_root.exception.code, "output-temporary-invalid")
        finally:
            self._clear_acl(private_root)
            private_root.rmdir()

        public = self.parent / "acl-public.json"
        public.write_bytes(b"payload")
        public.chmod(0o600)
        self._add_everyone_acl(public)
        try:
            with self.assertRaises(anchored.AnchoredOutputError) as unsafe_public:
                anchored.publish_identical_receipt_bytes(public, b"payload")
            self.assertEqual(unsafe_public.exception.code, "output-existing-invalid")
        finally:
            self._clear_acl(public)
            public.unlink()

        stage_name = "9" * 32 + ".tmp"
        stage_lease = self._stage_lease()
        real_open = self.posix._open_posix_descriptor

        def add_stage_acl_after_open(
            descriptor_lease: anchored._PosixDescriptorLease,
            path: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            descriptor = real_open(descriptor_lease, path, flags, mode, dir_fd=dir_fd)
            if descriptor_lease is stage_lease.descriptor:
                self._add_everyone_acl(self.parent / PRIVATE_ROOT / stage_name)
            return descriptor

        with (
            mock.patch.object(self.posix.secrets, "token_hex", return_value="9" * 32),
            mock.patch.object(self.posix, "_open_posix_descriptor", side_effect=add_stage_acl_after_open),
            self.assertRaises(anchored.AnchoredOutputError) as unsafe_stage,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                stage_lease,
            )
        self.assertEqual(unsafe_stage.exception.code, "output-temporary-invalid")
        retained_stage = self.parent / PRIVATE_ROOT / stage_name
        self.assertTrue(retained_stage.exists())
        self._clear_acl(retained_stage)
        retained_stage.unlink()
        (self.parent / PRIVATE_ROOT).rmdir()

    @unittest.skipUnless(sys.platform == "darwin", "native macOS renameatx_np contract")
    def test_native_rename_moves_same_acl_free_inode_and_collision_preserves_both(self) -> None:
        stage_lease = self._stage_lease()
        stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            stage_lease,
        )
        self.posix._write_and_sync_retained_descriptor(stage.descriptor, b"source")
        source = os.fstat(stage.descriptor)
        self._add_everyone_acl(self.parent, inherited=True)
        try:
            self.posix._darwin_rename_receipt_stage(
                stage,
                stage_lease,
                self.binding.descriptors[-1],
                "moved.json",
            )
        finally:
            self._clear_acl(self.parent)
        moved = (self.parent / "moved.json").stat()
        self.assertEqual((moved.st_dev, moved.st_ino), (source.st_dev, source.st_ino))
        self.assertFalse((self.parent / PRIVATE_ROOT / stage.named_stage_name).exists())
        self.assertFalse(anchored._darwin_descriptor_has_extended_acl(stage.descriptor))
        self.posix._cleanup_darwin_named_stage(stage_lease)
        self.assertFalse(stage_lease.private_directory_sync_pending)
        self._close_stage(stage, stage_lease)
        (self.parent / "moved.json").unlink()

        winner = self.parent / "winner.json"
        winner.write_bytes(b"winner")
        winner.chmod(0o600)
        collision_lease = self._stage_lease()
        collision_stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            collision_lease,
        )
        self.posix._write_and_sync_retained_descriptor(collision_stage.descriptor, b"source")
        with self.assertRaises(FileExistsError):
            self.posix._darwin_rename_receipt_stage(
                collision_stage,
                collision_lease,
                self.binding.descriptors[-1],
                winner.name,
            )
        self.assertEqual(winner.read_bytes(), b"winner")
        self.assertTrue((self.parent / PRIVATE_ROOT / collision_stage.named_stage_name).exists())
        self._close_stage(collision_stage, collision_lease)
        winner.unlink()
        (self.parent / PRIVATE_ROOT).rmdir()

    @unittest.skipUnless(sys.platform == "darwin", "native macOS staging-root selection")
    def test_reserved_staging_root_leaf_uses_deterministic_alternate(self) -> None:
        output = self.parent / PRIVATE_ROOT
        anchored.publish_identical_receipt_bytes(output, b"receipt")
        anchored.publish_identical_receipt_bytes(output, b"receipt")
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_bytes(), b"receipt")
        alternate = self.parent / self.posix._DARWIN_RECEIPT_STAGING_ROOT_ALTERNATE
        self.assertTrue(alternate.is_dir())
        output.unlink()
        alternate.rmdir()

    @unittest.skipUnless(sys.platform == "darwin", "native macOS private-directory durability")
    def test_private_stage_unlink_retries_directory_sync_before_close(self) -> None:
        stage_lease = self._stage_lease()
        stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            stage_lease,
        )
        publication = self.posix._PosixReceiptPublicationLease(
            self.binding,
            stage=stage_lease,
        )
        real_sync = self.posix.os.fsync
        private_sync_calls = 0

        def fail_private_sync_once(descriptor: int) -> None:
            nonlocal private_sync_calls
            if descriptor == stage.private_directory_descriptor:
                private_sync_calls += 1
                if private_sync_calls == 1:
                    raise OSError("private directory sync")
            real_sync(descriptor)

        with mock.patch.object(self.posix.os, "fsync", side_effect=fail_private_sync_once):
            failures = publication.close()
        self.assertEqual(len(failures), 1)
        self.assertEqual(private_sync_calls, 2)
        self.assertTrue(publication.is_closed)
        self.assertFalse((self.parent / PRIVATE_ROOT / stage.named_stage_name).exists())
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_named_stage_unlink_effect_then_interruption_is_recovered_exactly(
        self,
    ) -> None:
        stage_lease = self._stage_lease()
        stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            stage_lease,
        )
        stage_descriptor = stage.descriptor
        private_descriptor = stage.private_directory_descriptor
        stage_path = self.parent / PRIVATE_ROOT / stage.named_stage_name
        neighbor = self.parent / PRIVATE_ROOT / "neighbor.tmp"
        neighbor.write_bytes(b"untouched")
        neighbor_before = neighbor.stat()
        publication = self.posix._PosixReceiptPublicationLease(
            self.binding,
            stage=stage_lease,
        )
        real_unlink = self.posix.os.unlink
        real_fsync = self.posix.os.fsync
        interruption = KeyboardInterrupt("unlink returned before assignment")
        unlinked_names: list[object] = []
        synced: list[int] = []

        def unlink_then_interrupt(
            name: os.PathLike[str] | str,
            *,
            dir_fd: int | None = None,
        ) -> None:
            unlinked_names.append(name)
            real_unlink(name, dir_fd=dir_fd)
            raise interruption

        def record_sync(descriptor: int) -> None:
            synced.append(descriptor)
            real_fsync(descriptor)

        with (
            mock.patch.object(
                self.posix,
                "sys",
                SimpleNamespace(platform="darwin"),
            ),
            mock.patch.object(
                self.posix.os,
                "unlink",
                side_effect=unlink_then_interrupt,
            ),
            mock.patch.object(self.posix.os, "fsync", side_effect=record_sync),
        ):
            failures = publication.close()

        self.assertEqual(failures, (interruption,))
        self.assertEqual(unlinked_names, [stage.named_stage_name])
        self.assertEqual(stage_lease.named_cleanup_attempts, 2)
        self.assertEqual(stage_lease.private_directory_sync_attempts, 1)
        self.assertEqual(synced, [private_descriptor])
        self.assertFalse(stage_path.exists())
        neighbor_after = neighbor.stat()
        self.assertEqual(
            (neighbor_after.st_dev, neighbor_after.st_ino, neighbor.read_bytes()),
            (neighbor_before.st_dev, neighbor_before.st_ino, b"untouched"),
        )
        self.assertTrue(publication.is_closed)
        for descriptor in (stage_descriptor, private_descriptor):
            with self.assertRaises(OSError) as closed:
                os.fstat(descriptor)
            self.assertEqual(closed.exception.errno, errno.EBADF)

        neighbor.unlink()
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_failed_stage_records_exhausted_private_sync_before_descriptor_close(self) -> None:
        stage_name = "8" * 32 + ".tmp"
        lease = self._stage_lease()
        primary = OSError("stage validation failed")
        real_fsync = self.posix.os.fsync
        real_close = self.posix._close_posix_descriptor_lease
        private_sync_calls = 0
        private_close_state: list[tuple[bool, bool, int]] = []

        def fail_private_sync(descriptor: int) -> None:
            nonlocal private_sync_calls
            if descriptor == lease.private_directory.descriptor:
                private_sync_calls += 1
                raise OSError("private directory sync")
            real_fsync(descriptor)

        def record_close_state(
            descriptor_lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            if descriptor_lease is lease.private_directory:
                private_close_state.append(
                    (
                        lease.private_directory_sync_retained,
                        lease.private_directory_sync_pending,
                        lease.private_directory_sync_attempts,
                    )
                )
            return real_close(descriptor_lease, active_primary, context)

        with (
            mock.patch.object(self.posix.secrets, "token_hex", return_value="8" * 32),
            mock.patch.object(
                self.posix,
                "_receipt_mode_is_canonical",
                side_effect=primary,
            ),
            mock.patch.object(self.posix.os, "fsync", side_effect=fail_private_sync),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=record_close_state,
            ),
            self.assertRaises(OSError) as raised,
        ):
            self.posix._open_darwin_receipt_stage(
                self.binding,
                PRIVATE_ROOT,
                lease,
            )

        self.assertIs(raised.exception, primary)
        self.assertEqual(private_sync_calls, 4)
        self.assertEqual(private_close_state, [(True, True, 4)])
        self.assertTrue(lease.private_directory_sync_retained)
        self.assertTrue(lease.private_directory_sync_pending)
        self.assertFalse((self.parent / PRIVATE_ROOT / stage_name).exists())
        self.assertIsNone(lease.descriptor.descriptor)
        self.assertIsNone(lease.private_directory.descriptor)
        self.assertIn(
            "could not be durably flushed after bounded retries",
            "\n".join(getattr(primary, "__notes__", ())),
        )
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_publication_cleanup_does_not_exceed_seeded_private_sync_budget(self) -> None:
        lease = self._stage_lease()
        stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            lease,
        )
        os.unlink(
            stage.named_stage_name,
            dir_fd=stage.private_directory_descriptor,
        )
        lease.named_stage_name = None
        lease.private_directory_sync_pending = True
        lease.private_directory_sync_attempts = 3
        publication = self.posix._PosixReceiptPublicationLease(
            self.binding,
            stage=lease,
        )
        real_close = self.posix._close_posix_descriptor_lease
        sync_calls = 0
        private_close_state: list[tuple[bool, int]] = []

        def fail_final_sync(stage_lease: Any) -> None:
            nonlocal sync_calls
            self.assertIs(stage_lease, lease)
            sync_calls += 1
            stage_lease.private_directory_sync_attempts += 1
            raise OSError("final private directory sync")

        def record_private_close(
            descriptor_lease: anchored._PosixDescriptorLease,
            active_primary: BaseException | None,
            context: str,
        ) -> BaseException | None:
            if descriptor_lease is lease.private_directory:
                private_close_state.append(
                    (
                        lease.private_directory_sync_retained,
                        lease.private_directory_sync_attempts,
                    )
                )
            return real_close(descriptor_lease, active_primary, context)

        with (
            mock.patch.object(
                self.posix,
                "_sync_darwin_private_directory_if_pending",
                side_effect=fail_final_sync,
            ),
            mock.patch.object(
                self.posix,
                "_close_posix_descriptor_lease",
                side_effect=record_private_close,
            ),
        ):
            failures = publication.close()

        self.assertEqual(sync_calls, 1)
        self.assertEqual(lease.private_directory_sync_attempts, 4)
        self.assertEqual(private_close_state, [(True, 4)])
        self.assertTrue(publication.is_closed)
        self.assertEqual(len(failures), 2)
        (self.parent / PRIVATE_ROOT).rmdir()

    def test_publication_cleanup_does_not_exceed_seeded_named_stage_budget(self) -> None:
        lease = self._stage_lease()
        stage = self.posix._open_darwin_receipt_stage(
            self.binding,
            PRIVATE_ROOT,
            lease,
        )
        lease.named_cleanup_attempts = 3
        publication = self.posix._PosixReceiptPublicationLease(
            self.binding,
            stage=lease,
        )
        cleanup_calls = 0

        def fail_final_cleanup(stage_lease: Any) -> None:
            nonlocal cleanup_calls
            self.assertIs(stage_lease, lease)
            cleanup_calls += 1
            raise OSError("final named-stage cleanup")

        with (
            mock.patch.object(
                self.posix,
                "sys",
                SimpleNamespace(platform="darwin"),
            ),
            mock.patch.object(
                self.posix,
                "_cleanup_darwin_named_stage",
                side_effect=fail_final_cleanup,
            ),
        ):
            failures = publication.close()

        self.assertEqual(cleanup_calls, 1)
        self.assertEqual(lease.named_cleanup_attempts, 4)
        self.assertTrue(lease.named_stage_retained)
        self.assertTrue(publication.is_closed)
        self.assertEqual(len(failures), 2)
        retained = self.parent / PRIVATE_ROOT / stage.named_stage_name
        self.assertTrue(retained.is_file())
        retained.unlink()
        (self.parent / PRIVATE_ROOT).rmdir()


if __name__ == "__main__":
    unittest.main()
