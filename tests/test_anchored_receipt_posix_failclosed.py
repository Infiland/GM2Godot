# pyright: reportPrivateUsage=false
from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
from typing import Any
import unittest
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


class AnchoredReceiptPosixFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt" or not anchored.descriptor_relative_output_supported():
            self.skipTest("descriptor-bound POSIX receipt primitive unavailable")
        self.posix = anchored._posix_receipt_module()

    def _record_anchored_opens(self, opened: list[int]):
        real_open = anchored._open_posix_descriptor

        def record_open(
            lease: anchored._PosixDescriptorLease,
            path: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            descriptor = real_open(lease, path, flags, mode, dir_fd=dir_fd)
            opened.append(descriptor)
            return descriptor

        return mock.patch.object(
            anchored,
            "_open_posix_descriptor",
            side_effect=record_open,
        )

    def _assert_closed(self, descriptors: list[int]) -> None:
        self.assertTrue(descriptors)
        self.assertEqual(len(descriptors), len(set(descriptors)))
        for descriptor in descriptors:
            with self.subTest(descriptor=descriptor), self.assertRaises(OSError) as raised:
                os.fstat(descriptor)
            self.assertEqual(raised.exception.errno, errno.EBADF)

    def _assert_absent_target_and_unchanged_sentinel(
        self,
        output: Path,
        sentinel: Path,
        sentinel_before: tuple[tuple[int, ...], bytes],
    ) -> None:
        self.assertFalse(output.exists())
        self.assertEqual(_entry_snapshot(sentinel), sentinel_before)
        self.assertEqual({entry.name for entry in output.parent.iterdir()}, {sentinel.name})

    def _anonymous_stage(self, parent: Path) -> int:
        descriptor, name = tempfile.mkstemp(prefix=".receipt-stage-", dir=parent)
        os.fchmod(descriptor, 0o600)
        os.unlink(name)
        return descriptor

    def _retained_stage_opener(
        self,
        descriptor: int,
        *,
        private_descriptor: int = -1,
        private_name: str = "",
        stage_name: str = "",
    ):
        def open_stage(
            _binding: object,
            _temporary_name: str,
            lease: Any,
        ) -> object:
            lease.descriptor.descriptor_result = ctypes.c_int(descriptor)
            if private_descriptor >= 0:
                lease.private_directory.descriptor_result = ctypes.c_int(private_descriptor)
                lease.named_stage_name = stage_name
            stage = self.posix._PosixReceiptStage(
                descriptor=descriptor,
                private_directory_descriptor=private_descriptor,
                private_directory_name=private_name,
                private_directory_identity=(
                    (os.fstat(private_descriptor).st_dev, os.fstat(private_descriptor).st_ino)
                    if private_descriptor >= 0
                    else None
                ),
                named_stage_name=stage_name,
            )
            lease.stage = stage
            return stage

        return open_stage

    def test_linux_tmpfile_unavailable_and_unsupported_full_facade_fail_closed(self) -> None:
        cases = (
            ("flag unavailable", 0, None),
            ("filesystem unsupported", 1 << 29, getattr(errno, "EOPNOTSUPP", errno.EINVAL)),
            ("kernel unsupported", 1 << 29, errno.ENOENT),
        )
        for label, temporary_flag, stage_errno in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary).resolve() / "output"
                parent.mkdir()
                output = parent / "receipt.json"
                sentinel = parent / "sentinel.bin"
                sentinel.write_bytes(b"untouched\n")
                sentinel_before = _entry_snapshot(sentinel)
                opened: list[int] = []

                def reject_stage_open(
                    _lease: anchored._PosixDescriptorLease,
                    _path: os.PathLike[str] | str,
                    _flags: int,
                    _mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    self.assertIsNotNone(dir_fd)
                    assert stage_errno is not None
                    raise OSError(stage_errno, os.strerror(stage_errno))

                stage_open = mock.Mock(side_effect=reject_stage_open)
                with (
                    mock.patch.object(self.posix, "sys", SimpleNamespace(platform="linux")),
                    mock.patch.object(self.posix.os, "O_TMPFILE", temporary_flag, create=True),
                    self._record_anchored_opens(opened),
                    mock.patch.object(
                        self.posix,
                        "_open_posix_descriptor",
                        stage_open,
                    ),
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored.publish_identical_receipt_bytes(output, PAYLOAD)

                self.assertEqual(raised.exception.code, "output-anchor-unavailable")
                self._assert_absent_target_and_unchanged_sentinel(
                    output,
                    sentinel,
                    sentinel_before,
                )
                self._assert_closed(opened)
                self.assertEqual(stage_open.call_count, 0 if stage_errno is None else 1)

    def test_native_link_and_rename_unavailable_full_facade_fail_closed(self) -> None:
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary).resolve() / "output"
                parent.mkdir()
                output = parent / "receipt.json"
                sentinel = parent / "sentinel.bin"
                sentinel.write_bytes(b"untouched\n")
                private_root = parent / ".modeled-private-root"
                private_descriptor = -1
                stage_name = "stage.tmp"
                if platform == "darwin":
                    private_root.mkdir(mode=0o700)
                    private_descriptor = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
                    stage_descriptor = os.open(
                        stage_name,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=private_descriptor,
                    )
                else:
                    stage_descriptor = self._anonymous_stage(parent)
                sentinel_before = _entry_snapshot(sentinel)
                opened = [stage_descriptor]
                if private_descriptor >= 0:
                    opened.append(private_descriptor)
                native_libc = anchored._posix_libc()
                try:
                    with (
                        mock.patch.object(self.posix, "sys", SimpleNamespace(platform=platform)),
                        self._record_anchored_opens(opened),
                        mock.patch.object(
                            self.posix,
                            "_open_posix_receipt_stage",
                            side_effect=self._retained_stage_opener(
                                stage_descriptor,
                                private_descriptor=private_descriptor,
                                private_name=private_root.name if private_descriptor >= 0 else "",
                                stage_name=stage_name if private_descriptor >= 0 else "",
                            ),
                        ),
                        mock.patch.object(anchored, "_posix_libc", return_value=native_libc),
                        mock.patch.object(
                            self.posix.ctypes,
                            "CDLL",
                            return_value=SimpleNamespace(),
                        ),
                        self.assertRaises(anchored.AnchoredOutputError) as raised,
                    ):
                        anchored.publish_identical_receipt_bytes(output, PAYLOAD)

                    self.assertEqual(raised.exception.code, "output-anchor-unavailable")
                    if private_root.exists():
                        private_root.rmdir()
                    self._assert_absent_target_and_unchanged_sentinel(
                        output,
                        sentinel,
                        sentinel_before,
                    )
                    self._assert_closed(opened)
                finally:
                    try:
                        os.close(stage_descriptor)
                    except OSError:
                        pass

    def test_pre_publication_primary_is_preserved_and_all_resources_close(self) -> None:
        primaries: tuple[BaseException, ...] = (
            OSError(errno.EIO, "injected native publication failure"),
            KeyboardInterrupt("injected native publication interrupt"),
        )
        for primary in primaries:
            with self.subTest(primary=type(primary).__name__), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary).resolve() / "output"
                parent.mkdir()
                output = parent / "receipt.json"
                sentinel = parent / "sentinel.bin"
                sentinel.write_bytes(b"untouched\n")
                stage_descriptor = self._anonymous_stage(parent)
                sentinel_before = _entry_snapshot(sentinel)
                opened = [stage_descriptor]
                try:
                    with (
                        mock.patch.object(self.posix, "sys", SimpleNamespace(platform="linux")),
                        self._record_anchored_opens(opened),
                        mock.patch.object(
                            self.posix,
                            "_open_posix_receipt_stage",
                            side_effect=self._retained_stage_opener(stage_descriptor),
                        ),
                        mock.patch.object(
                            self.posix,
                            "_publish_posix_receipt_descriptor",
                            side_effect=primary,
                        ),
                        self.assertRaises(type(primary)) as raised,
                    ):
                        anchored.publish_identical_receipt_bytes(output, PAYLOAD)

                    self.assertIs(raised.exception, primary)
                    self._assert_absent_target_and_unchanged_sentinel(
                        output,
                        sentinel,
                        sentinel_before,
                    )
                    self._assert_closed(opened)
                finally:
                    try:
                        os.close(stage_descriptor)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
