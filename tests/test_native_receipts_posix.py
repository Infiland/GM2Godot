"""Native POSIX namespace and durability checks through the public publisher."""

from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import unittest
from collections.abc import Callable, Collection
from pathlib import Path
from unittest.mock import patch

from scripts._anchored_output import (
    AnchoredOutputError,
    publish_identical_receipt_bytes,
)

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
            self.assertEqual((path.read_bytes(), path.stat().st_ino), (PAYLOAD, identity))
            path.chmod(0o644)
            try:
                with self.assertRaises(AnchoredOutputError):
                    publish_identical_receipt_bytes(path, PAYLOAD)
                self.assertEqual((path.read_bytes(), path.stat().st_ino), (PAYLOAD, identity))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            finally:
                path.chmod(0o600)
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
        descriptors: set[int] = set()
        identities: set[tuple[int, int]] = set()

        def sync(descriptor: int) -> None:
            synchronized.add(stat.S_IFMT(os.fstat(descriptor).st_mode))
            real_sync(descriptor)

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "new-parent" / "receipt.json"
            with (
                patch.object(os, "fsync", side_effect=sync),
                patch.object(os, "fstat", side_effect=self._directory_observer(descriptors, identities)),
            ):
                publish_identical_receipt_bytes(path, PAYLOAD)
            self.assertEqual(synchronized, {stat.S_IFREG, stat.S_IFDIR})
            self._assert_closed(descriptors)
            self.assertTrue(self._ancestor_identities(path.parent).issubset(identities))
            self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_parent_relocation_is_detected_and_retained_descriptor_closes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw).resolve() / "parent"
            parent.mkdir()
            moved = parent.with_name("moved")
            real_write = os.write
            descriptors: list[int] = []
            directories: set[int] = set()
            identities: set[tuple[int, int]] = set()
            expected_ancestors = self._ancestor_identities(parent)

            def write(descriptor: int, payload: bytes) -> int:
                descriptors.append(descriptor)
                parent.rename(moved)
                return real_write(descriptor, payload)

            with (
                patch.object(os, "write", side_effect=write),
                patch.object(os, "fstat", side_effect=self._directory_observer(directories, identities)),
                self.assertRaises((AnchoredOutputError, OSError)),
            ):
                publish_identical_receipt_bytes(parent / "receipt.json", PAYLOAD)
            self._assert_closed(descriptors)
            self._assert_closed(directories)
            self.assertTrue(expected_ancestors.issubset(identities))
            self.assertTrue(moved.is_dir())
            self.assertFalse(parent.exists())
            self.assertFalse((moved / "receipt.json").exists())

    def test_post_write_failure_cleans_stage_and_closes_descriptor(self) -> None:
        errors = (OSError(errno.EIO, "injected after native write"), KeyboardInterrupt("after native write"), SystemExit(3))
        for error in errors:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as raw:
                parent = Path(raw).resolve()
                real_write = os.write
                descriptors: list[int] = []
                directories: set[int] = set()
                identities: set[tuple[int, int]] = set()

                def write(descriptor: int, payload: bytes) -> int:
                    descriptors.append(descriptor)
                    real_write(descriptor, payload)
                    raise error

                with (
                    patch.object(os, "write", side_effect=write),
                    patch.object(os, "fstat", side_effect=self._directory_observer(directories, identities)),
                    self.assertRaises(type(error)) as raised,
                ):
                    publish_identical_receipt_bytes(parent / "receipt.json", PAYLOAD)
                self.assertIs(raised.exception, error)
                self._assert_closed(descriptors)
                self._assert_closed(directories)
                self.assertEqual(len(descriptors), 1)
                self.assertTrue(self._ancestor_identities(parent).issubset(identities))
                self.assertFalse((parent / "receipt.json").exists())
                if sys.platform == "darwin":
                    # macOS keeps one private reusable staging directory; the
                    # failed file must be gone and every descriptor closed.
                    staging = parent / ".gm2godot-receipt-staging"
                    self.assertEqual(list(parent.iterdir()), [staging])
                    status = staging.lstat()
                    self.assertTrue(stat.S_ISDIR(status.st_mode))
                    self.assertEqual(stat.S_IMODE(status.st_mode), 0o700)
                    self.assertEqual(status.st_uid, parent.stat().st_uid)
                    self.assertEqual(list(staging.iterdir()), [])
                else:
                    self.assertEqual(list(parent.iterdir()), [])

    def _directory_observer(
        self,
        descriptors: set[int],
        identities: set[tuple[int, int]],
    ) -> Callable[[int], os.stat_result]:
        real_status = os.fstat

        def status(descriptor: int) -> os.stat_result:
            observed = real_status(descriptor)
            if stat.S_ISDIR(observed.st_mode):
                descriptors.add(descriptor)
                identities.add((observed.st_dev, observed.st_ino))
            return observed

        return status

    def _ancestor_identities(self, parent: Path) -> set[tuple[int, int]]:
        return {(status.st_dev, status.st_ino) for path in (parent, *parent.parents) for status in (path.stat(),)}

    def _assert_closed(self, descriptors: Collection[int]) -> None:
        self.assertTrue(descriptors)
        for descriptor in descriptors:
            with self.assertRaises(OSError) as raised:
                os.fstat(descriptor)
            self.assertEqual(raised.exception.errno, errno.EBADF)
