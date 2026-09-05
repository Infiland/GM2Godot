"""Trusted macOS root aliases retain the physical receipt inode."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from scripts._anchored_output import AnchoredOutputError, publish_identical_receipt_bytes


@unittest.skipUnless(sys.platform == "darwin", "requires native macOS root aliases")
class TestNativeReceiptsDarwin(unittest.TestCase):
    def _assert_alias(self, prefix: str) -> None:
        self.assertEqual(Path(prefix).resolve(), Path("/private" + prefix))
        with tempfile.TemporaryDirectory(dir=prefix) as raw:
            alias = Path(raw) / "receipt.json"
            physical = alias.parent.resolve() / alias.name
            publish_identical_receipt_bytes(alias, b"native alias\n")
            identity = physical.stat().st_ino
            publish_identical_receipt_bytes(physical, b"native alias\n")
            self.assertEqual(alias.stat().st_ino, identity)
            self.assertEqual(physical.read_bytes(), b"native alias\n")

    def test_tmp_alias_preserves_physical_inode(self) -> None:
        self._assert_alias("/tmp")

    def test_var_alias_preserves_physical_inode(self) -> None:
        self._assert_alias("/var/tmp")

    def test_redirect_below_trusted_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            parent = Path(raw)
            target = parent / "target"
            target.mkdir()
            link = parent / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(AnchoredOutputError):
                publish_identical_receipt_bytes(link / "receipt.json", b"payload")
            self.assertFalse((target / "receipt.json").exists())
