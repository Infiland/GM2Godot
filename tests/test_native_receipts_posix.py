"""Native POSIX namespace and durability checks through the public publisher."""

from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts._anchored_output import AnchoredOutputError, publish_identical_receipt_bytes

PAYLOAD = b'{"native":"receipt"}\n'


@unittest.skipUnless(sys.platform in {"darwin", "linux"}, "requires native POSIX receipts")
class TestNativeReceiptsPosix(unittest.TestCase):
    def test_absent_and_identical_preserve_private_inode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "new" / "receipt.json"
            publish_identical_receipt_bytes(path, PAYLOAD)
            before = path.stat()
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertEqual((stat.S_IMODE(before.st_mode), before.st_nlink), (0o600, 1))
            self.assertTrue(stat.S_ISREG(before.st_mode))
            publish_identical_receipt_bytes(path, PAYLOAD)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), (before.st_dev, before.st_ino))
            self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_different_and_linked_targets_fail_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            path = root / "receipt.json"
            publish_identical_receipt_bytes(path, PAYLOAD)
            identity = path.stat().st_ino
            with self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(path, b"different")
            os.link(path, root / "hardlink")
            with self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(path, PAYLOAD)
            self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_nlink), (PAYLOAD, identity, 2))

    def test_symlink_parent_and_target_never_redirect_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            outside = root / "outside"
            outside.mkdir()
            link = root / "redirect"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(link / "receipt.json", PAYLOAD)
            target = root / "receipt.json"
            target.symlink_to(outside / "untouched")
            with self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(target, PAYLOAD)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue(target.is_symlink())

    def test_real_file_and_directory_fsync_are_executed(self) -> None:
        real_sync = os.fsync
        synchronized: set[int] = set()

        def sync(descriptor: int) -> None:
            synchronized.add(stat.S_IFMT(os.fstat(descriptor).st_mode))
            real_sync(descriptor)

        with tempfile.TemporaryDirectory() as raw, patch.object(os, "fsync", side_effect=sync):
            publish_identical_receipt_bytes(Path(raw).resolve() / "receipt.json", PAYLOAD)
        self.assertEqual(synchronized, {stat.S_IFREG, stat.S_IFDIR})

    def test_parent_relocation_is_detected_and_retained_descriptor_closes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw).resolve() / "parent"
            parent.mkdir()
            moved = parent.with_name("moved")
            real_write = os.write
            descriptors: list[int] = []

            def write(descriptor: int, payload: bytes) -> int:
                descriptors.append(descriptor)
                parent.rename(moved)
                return real_write(descriptor, payload)

            with patch.object(os, "write", side_effect=write), self.assertRaises((AnchoredOutputError, OSError)):
                publish_identical_receipt_bytes(parent / "receipt.json", PAYLOAD)
            self._assert_closed(descriptors)
            self.assertTrue(moved.is_dir())
            self.assertFalse(parent.exists())
            self.assertFalse((moved / "receipt.json").exists())

    def test_post_write_failure_cleans_stage_and_closes_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw).resolve()
            real_write = os.write
            descriptors: list[int] = []

            def write(descriptor: int, payload: bytes) -> int:
                descriptors.append(descriptor)
                real_write(descriptor, payload)
                raise OSError(errno.EIO, "injected after native write")

            with patch.object(os, "write", side_effect=write), self.assertRaises(OSError):
                publish_identical_receipt_bytes(parent / "receipt.json", PAYLOAD)
            self._assert_closed(descriptors)
            self.assertFalse((parent / "receipt.json").exists())
            self.assertFalse(list(parent.rglob("*.tmp")))

    def _assert_closed(self, descriptors: list[int]) -> None:
        self.assertTrue(descriptors)
        for descriptor in descriptors:
            with self.assertRaises(OSError) as raised:
                os.fstat(descriptor)
            self.assertEqual(raised.exception.errno, errno.EBADF)
