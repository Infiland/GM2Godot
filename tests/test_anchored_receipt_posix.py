# pyright: reportPrivateUsage=false
from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from scripts import _anchored_output as anchored

PAYLOAD = b'{"status":"verified"}\n'


def _entry_snapshot(path: Path) -> tuple[tuple[int, ...], bytes]:
    value = path.lstat()
    return (
        (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        ),
        path.read_bytes(),
    )


class AnchoredReceiptPosixTests(unittest.TestCase):
    def test_retained_writer_syscall_failure_matrix_preserves_primary(self) -> None:
        posix = anchored._posix_receipt_module()
        cases = (
            ("ftruncate", OSError("truncate")),
            ("lseek", KeyboardInterrupt("seek")),
            ("write", OSError("write")),
            ("fsync", SystemExit(23)),
        )
        for operation, primary in cases:
            with self.subTest(operation=operation):

                def effect(name: str, result: object = None) -> object:
                    if operation == name:
                        raise primary
                    return result

                def truncate(_descriptor: int, _size: int) -> object:
                    return effect("ftruncate")

                def seek(_descriptor: int, _offset: int, _whence: int) -> object:
                    return effect("lseek")

                def write(_descriptor: int, _payload: bytes) -> object:
                    return effect("write", len(PAYLOAD))

                def sync(_descriptor: int) -> object:
                    return effect("fsync")

                with (
                    mock.patch.object(posix.os, "ftruncate", side_effect=truncate),
                    mock.patch.object(posix.os, "lseek", side_effect=seek),
                    mock.patch.object(posix.os, "write", side_effect=write),
                    mock.patch.object(posix.os, "fsync", side_effect=sync),
                    self.assertRaises(type(primary)) as raised,
                ):
                    posix._write_and_sync_retained_descriptor(7, PAYLOAD)
                self.assertIs(raised.exception, primary)

    def test_zero_write_progress_fails_boundedly(self) -> None:
        posix = anchored._posix_receipt_module()
        with (
            mock.patch.object(posix.os, "ftruncate"),
            mock.patch.object(posix.os, "lseek"),
            mock.patch.object(posix.os, "write", return_value=0) as write,
            self.assertRaises(OSError),
        ):
            posix._write_and_sync_retained_descriptor(7, PAYLOAD)
        write.assert_called_once()

    def test_retained_descriptor_rejects_identity_link_mode_size_and_content_mutation(self) -> None:
        posix = anchored._posix_receipt_module()
        base = {
            "st_dev": 1,
            "st_ino": 2,
            "st_mode": stat.S_IFREG | 0o600,
            "st_uid": os.geteuid(),
            "st_nlink": 0,
            "st_size": len(PAYLOAD),
            "st_mtime_ns": 3,
            "st_ctime_ns": 4,
        }
        mutations: dict[str, tuple[dict[str, int], bytes]] = {
            "identity": ({"st_ino": 9}, PAYLOAD),
            "link": ({"st_nlink": 1}, PAYLOAD),
            "mode": ({"st_mode": stat.S_IFREG | 0o644}, PAYLOAD),
            "size": ({"st_size": len(PAYLOAD) + 1}, PAYLOAD),
            "content": ({}, b"different\n"),
        }
        for label, (changes, observed) in mutations.items():
            with self.subTest(label=label):
                before = cast(os.stat_result, SimpleNamespace(**base))
                after = cast(os.stat_result, SimpleNamespace(**{**base, **changes}))
                with (
                    mock.patch.object(posix.os, "fstat", side_effect=(before, after)),
                    mock.patch.object(posix.os, "lseek"),
                    mock.patch.object(posix.os, "read", side_effect=(observed, b"")),
                    mock.patch.object(posix, "_darwin_descriptor_has_extended_acl", return_value=False),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    posix._validate_exact_receipt_descriptor(
                        7,
                        PAYLOAD,
                        (1, 2),
                        expected_link_count=0,
                        code="output-temporary-invalid",
                    )
                self.assertEqual(raised.exception.code, "output-temporary-invalid")

    def test_unsupported_publication_errnos_map_fail_closed(self) -> None:
        posix = anchored._posix_receipt_module()
        for error_number in (errno.EINVAL, errno.ENOSYS, errno.EXDEV):
            with self.subTest(error_number=error_number), self.assertRaises(anchored.AnchoredOutputError) as raised:
                posix._raise_posix_publication_error(
                    error_number,
                    "receipt.json",
                    operation="linking",
                    additional_unavailable=frozenset({errno.EXDEV}),
                )
            self.assertEqual(raised.exception.code, "output-anchor-unavailable")

    def setUp(self) -> None:
        if os.name == "nt" or sys.platform not in {"darwin", "linux"}:
            self.skipTest("descriptor-bound POSIX receipt primitive unavailable")

    def _in_checkout(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve()
        parent = root / "parent"
        parent.mkdir()
        return temporary, root, parent

    def test_relocation_inside_native_publication_cannot_redirect_output(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        relocated = root / "relocated"
        try:
            output = parent / "receipt.json"
            hook_name = (
                "_darwin_rename_receipt_stage" if sys.platform == "darwin" else "_linux_link_receipt_descriptor"
            )
            posix = anchored._posix_receipt_module()
            real_hook = getattr(posix, hook_name)

            def relocate_then_publish(*args: object, **kwargs: object) -> None:
                parent.rename(relocated)
                parent.mkdir()
                real_hook(*args, **kwargs)

            with (
                mock.patch.object(posix, hook_name, side_effect=relocate_then_publish),
                self.assertRaises(anchored.AnchoredOutputError) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            self.assertEqual(raised.exception.code, "output-parent-changed")
            self.assertFalse(output.exists())
            self.assertEqual((relocated / output.name).read_bytes(), PAYLOAD)
        finally:
            os.chdir(previous)
            temporary.cleanup()

    def test_native_target_swap_between_stat_and_open_fails_untouched(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        output = parent / "receipt.json"
        displaced = parent / "displaced"
        output.write_bytes(PAYLOAD)
        output.chmod(0o600)
        real_descriptor_open = anchored._open_posix_descriptor
        real_os_open = anchored.os.open
        swapped = False
        snapshots: dict[str, tuple[tuple[int, ...], bytes]] = {}

        def swap_then_open(
            descriptor_lease: anchored._PosixDescriptorLease,
            name: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal swapped
            if name == "receipt.json" and dir_fd is not None and not swapped:
                swapped = True
                os.rename(name, "displaced", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                attacker = real_os_open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=dir_fd,
                )
                try:
                    self.assertEqual(os.write(attacker, PAYLOAD), len(PAYLOAD))
                finally:
                    os.close(attacker)
                snapshots["displaced"] = _entry_snapshot(displaced)
                snapshots["public"] = _entry_snapshot(output)
            return real_descriptor_open(
                descriptor_lease,
                name,
                flags,
                mode,
                dir_fd=dir_fd,
            )

        try:
            with (
                mock.patch.object(anchored, "descriptor_relative_output_supported", return_value=True),
                mock.patch.object(anchored, "_open_posix_descriptor", side_effect=swap_then_open),
                self.assertRaises(anchored.AnchoredOutputError) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            self.assertEqual(raised.exception.code, "output-changed")
            self.assertTrue(swapped)
            self.assertEqual(_entry_snapshot(displaced), snapshots["displaced"])
            self.assertEqual(_entry_snapshot(output), snapshots["public"])
        finally:
            os.chdir(previous)
            temporary.cleanup()

    def test_native_target_swap_after_read_fails_untouched(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        output = parent / "receipt.json"
        displaced = parent / "displaced"
        output.write_bytes(PAYLOAD)
        output.chmod(0o600)
        real_open = anchored.os.open
        real_read = anchored.os.read
        swapped = False
        snapshots: dict[str, tuple[tuple[int, ...], bytes]] = {}

        def read_then_swap(descriptor: int, size: int) -> bytes:
            nonlocal swapped
            observed = real_read(descriptor, size)
            if observed and not swapped:
                swapped = True
                output.rename(displaced)
                attacker = real_open(
                    output,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    self.assertEqual(os.write(attacker, PAYLOAD), len(PAYLOAD))
                finally:
                    os.close(attacker)
                snapshots["displaced"] = _entry_snapshot(displaced)
                snapshots["public"] = _entry_snapshot(output)
            return observed

        try:
            with (
                mock.patch.object(anchored.os, "read", side_effect=read_then_swap),
                self.assertRaises(anchored.AnchoredOutputError) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            self.assertEqual(raised.exception.code, "output-changed")
            self.assertTrue(swapped)
            self.assertEqual(_entry_snapshot(displaced), snapshots["displaced"])
            self.assertEqual(_entry_snapshot(output), snapshots["public"])
        finally:
            os.chdir(previous)
            temporary.cleanup()

    def test_directory_sync_failure_keeps_exact_public_receipt_and_closes(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        output = parent / "receipt.json"
        real_sync = anchored.OutputParentBinding.sync
        real_open = anchored._open_posix_descriptor
        real_close = anchored._PosixDescriptorLease.close
        posix = anchored._posix_receipt_module()
        opened: list[int] = []
        closed: list[int] = []
        live: list[int] = []
        live_at_failure: list[int] = []

        def sync_then_fail(binding: anchored.OutputParentBinding) -> None:
            real_sync(binding)
            if not live_at_failure:
                live_at_failure.extend(live)
            raise OSError(errno.EIO, "injected directory sync failure")

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
            live.append(descriptor)
            return descriptor

        def record_close(descriptor_lease: anchored._PosixDescriptorLease) -> None:
            descriptor = descriptor_lease.descriptor
            if descriptor is None:
                return real_close(descriptor_lease)
            self.assertIn(descriptor, live)
            closed.append(descriptor)
            live.remove(descriptor)
            real_close(descriptor_lease)

        try:
            with (
                mock.patch.object(anchored.OutputParentBinding, "sync", sync_then_fail),
                mock.patch.object(anchored, "descriptor_relative_output_supported", return_value=True),
                mock.patch.object(anchored, "_open_posix_descriptor", side_effect=record_open),
                mock.patch.object(posix, "_open_posix_descriptor", side_effect=record_open),
                mock.patch.object(anchored._PosixDescriptorLease, "close", new=record_close),
                self.assertRaises(OSError),
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            self.assertEqual(output.read_bytes(), PAYLOAD)
            self.assertEqual(live, [])
            self.assertTrue(live_at_failure)
            self.assertCountEqual(closed, opened)
            self.assertEqual(closed[-len(live_at_failure) :], list(reversed(live_at_failure)))
        finally:
            os.chdir(previous)
            temporary.cleanup()

    def test_exact_existing_retry_repeats_public_file_and_parent_durability(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        output = parent / "receipt.json"
        try:
            anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            posix = anchored._posix_receipt_module()
            real_public_sync = posix._sync_posix_public_descriptor
            real_parent_sync = anchored.OutputParentBinding.sync
            public_sync_calls = 0
            parent_sync_calls = 0

            def fail_public_sync_once(
                binding: anchored.OutputParentBinding,
                payload: bytes,
                identity: tuple[int, int],
                descriptor_lease: anchored._PosixDescriptorLease,
            ) -> None:
                nonlocal public_sync_calls
                public_sync_calls += 1
                if public_sync_calls == 1:
                    raise OSError(errno.EIO, "public receipt sync")
                real_public_sync(binding, payload, identity, descriptor_lease)

            def record_parent_sync(binding: anchored.OutputParentBinding) -> None:
                nonlocal parent_sync_calls
                parent_sync_calls += 1
                real_parent_sync(binding)

            with (
                mock.patch.object(posix, "_sync_posix_public_descriptor", side_effect=fail_public_sync_once),
                mock.patch.object(anchored.OutputParentBinding, "sync", new=record_parent_sync),
                self.assertRaises(OSError),
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            with (
                mock.patch.object(posix, "_sync_posix_public_descriptor", side_effect=fail_public_sync_once),
                mock.patch.object(anchored.OutputParentBinding, "sync", new=record_parent_sync),
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)

            self.assertEqual(public_sync_calls, 2)
            self.assertEqual(parent_sync_calls, 1)
            self.assertEqual(output.read_bytes(), PAYLOAD)
        finally:
            os.chdir(previous)
            temporary.cleanup()

    def test_writer_control_flow_failure_preserves_primary_and_notes_close_failure(self) -> None:
        temporary, root, parent = self._in_checkout()
        previous = Path.cwd()
        os.chdir(root)
        output = parent / "receipt.json"
        primary = KeyboardInterrupt("injected writer interrupt")
        real_close = anchored._PosixDescriptorLease.close
        posix = anchored._posix_receipt_module()
        close_failure_injected = False

        def close_then_fail(descriptor_lease: anchored._PosixDescriptorLease) -> None:
            nonlocal close_failure_injected
            owned_descriptor = descriptor_lease.descriptor
            real_close(descriptor_lease)
            if owned_descriptor is not None and not close_failure_injected:
                close_failure_injected = True
                raise OSError("injected close failure")

        try:
            with (
                mock.patch.object(posix, "_write_and_sync_retained_descriptor", side_effect=primary),
                mock.patch.object(anchored._PosixDescriptorLease, "close", new=close_then_fail),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            self.assertIs(raised.exception, primary)
            self.assertIn("injected close failure", "\n".join(getattr(primary, "__notes__", ())))
            self.assertFalse(output.exists())
        finally:
            os.chdir(previous)
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
