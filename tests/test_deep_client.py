"""Public client contracts, safe installation and resumable protocol tests."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.deep.install import ExtensionManager, extract_package
from src.deep.jobs import DeepJob, pending_jobs
from src.deep.session import DeepSession
from src.deep.settings import DeepSettings, load_settings, save_settings


class DeepClientTests(unittest.TestCase):
    def test_default_free_settings_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = load_settings(root)
            self.assertFalse(settings.allowRemoteSourceUpload)
            self.assertTrue(settings.freeOnly)
            self.assertEqual(settings.analysisWorkers, 4)
            self.assertEqual(settings.freeProviderConcurrency, 1)
            settings.analysisWorkers = 8
            save_settings(settings, root)
            self.assertEqual(load_settings(root).analysisWorkers, 8)
            settings.runtime = "codex"
            with self.assertRaisesRegex(ValueError, "requires OpenCode"):
                settings.validate()

    def test_untrusted_archive_cannot_escape_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape", "untrusted")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                extract_package(archive, root / "target")
            self.assertFalse((root / "escape").exists())

    def test_verified_atomic_install_and_checksum_failure_preserve_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("node/bin/node", "runtime")
                bundle.writestr("engine/dist/host/main.js", "engine")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest: dict[str, Any] = {"version": "0.2.0", "protocolVersion": 1, "minClientVersion": "0.0.1", "packages": {"linux-x64": {"url": "https://example.test/package", "sha256": digest, "runtime": "node/bin/node", "entrypoint": "engine/dist/host/main.js"}}}
            def download(url: str, destination: Path) -> None:
                destination.write_bytes(json.dumps(manifest).encode() if "manifest" in url else archive.read_bytes())
            manager = ExtensionManager(root / "data")
            with patch("src.deep.install.platform_key", return_value="linux-x64"), patch("src.deep.install.download_verified_transport", side_effect=download):
                installed = manager.install("https://example.test/manifest")
                self.assertEqual(manager.installation(), installed)
                self.assertEqual(manager.command()[1], str(installed / "engine/dist/host/main.js"))
                manifest["packages"]["linux-x64"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    manager.install("https://example.test/manifest")
                self.assertEqual(manager.installation(), installed)

    def test_jobs_retain_installation_and_offer_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = DeepJob(root / "jobs" / "one", "/source", "/baseline", root / "v1", DeepSettings(), "paused")
            job.save()
            loaded = pending_jobs(root)
            self.assertEqual(loaded[0].installation, root / "v1")
            self.assertEqual(loaded[0].phase, "paused")
            job.phase = "complete"
            job.save()
            self.assertEqual(pending_jobs(root), [])

    def test_protocol_waits_for_completion_after_acceptance(self) -> None:
        script = '''import json,sys
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({"protocolVersion":1,"id":r["id"],"type":"result","result":{"state":"running"}}),flush=True)
 print(json.dumps({"protocolVersion":1,"type":"progress","seq":1,"result":{"completed":1,"total":1}}),flush=True)
 print(json.dumps({"protocolVersion":1,"type":"completed","seq":2,"result":{"state":"review"}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as temporary:
            events: list[object] = []
            session = DeepSession([sys.executable, "-u", "-c", script], Path(temporary), events.append)
            try:
                result = session.request("research", {}, timeout=5)
                self.assertEqual(result["result"]["state"], "review")
                self.assertEqual(len(events), 1)
            finally:
                session.close()

    def test_protocol_rejects_version_drift(self) -> None:
        script = 'import json,sys; sys.stdin.readline(); print(json.dumps({"protocolVersion":2,"type":"result","result":{}}),flush=True)'
        with tempfile.TemporaryDirectory() as temporary:
            session = DeepSession([sys.executable, "-u", "-c", script], Path(temporary))
            try:
                with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                    session.request("capabilities", timeout=5)
            finally:
                session.close()
