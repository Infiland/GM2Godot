from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.deep_release import PLATFORMS, seal_manifest


class DeepReleaseTests(unittest.TestCase):
    def _bundles(self, root: Path, test_build: bool = False) -> None:
        for platform in PLATFORMS:
            name = f"gm2godot-deep-0.2.1-{platform}.zip"
            content = platform.encode()
            (root / name).write_bytes(content)
            (root / f"manifest-{platform}.json").write_text(json.dumps({
                "testBuild": test_build, "sourceRevision": "a" * 40, "clientRevision": "b" * 40,
                "version": "0.2.1", "protocolVersion": 1,
                "packages": {platform: {
                    "url": f"https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/{name}",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }},
            }))

    def test_seals_exact_platform_set_and_rejects_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundles(root)
            path = seal_manifest(root, "a" * 40, "b" * 40, "0.2.1")
            self.assertEqual(set(json.loads(path.read_text())["packages"]), set(PLATFORMS))
            (root / "gm2godot-deep-0.2.1-win-x64.zip").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "checksum"):
                seal_manifest(root, "a" * 40, "b" * 40, "0.2.1")

    def test_local_test_build_cannot_be_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundles(root, test_build=True)
            with self.assertRaisesRegex(ValueError, "test builds"):
                seal_manifest(root, "a" * 40, "b" * 40, "0.2.1")
