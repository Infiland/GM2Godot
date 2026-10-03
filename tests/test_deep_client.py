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


class VerifiedReleaseFixture:
    """Two synthetic releases exercise the real verified installer without network or execution."""

    def __init__(self, root: Path) -> None:
        self.requested_urls: list[str] = []
        self.transport_data: dict[str, bytes] = {}
        releases = {
            "0.2.1": (
                "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/fixture-deep-linux-x64.zip",
            ),
            "0.2.2": (
                "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/deep-manifest.json",
                "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/fixture-deep-linux-x64.zip",
            ),
        }
        for version, (manifest_url, package_url) in releases.items():
            archive = root / f"release-{version}.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("node/bin/node", f"fixture runtime {version}\n")
                bundle.writestr("engine/dist/host/main.js", f"fixture engine {version}\n")
            package_bytes = archive.read_bytes()
            manifest = {
                "version": version,
                "protocolVersion": 1,
                "minClientVersion": "0.8.1",
                "packages": {
                    "linux-x64": {
                        "url": package_url,
                        "sha256": hashlib.sha256(package_bytes).hexdigest(),
                        "runtime": "node/bin/node",
                        "entrypoint": "engine/dist/host/main.js",
                    },
                },
            }
            self.transport_data[manifest_url] = json.dumps(manifest).encode("utf-8")
            self.transport_data[package_url] = package_bytes

    def download(self, url: str, destination: Path) -> None:
        self.requested_urls.append(url)
        if url not in self.transport_data:
            raise AssertionError(f"Unexpected fixture download URL: {url}")
        destination.write_bytes(self.transport_data[url])


class DeepClientTests(unittest.TestCase):
    def test_default_upgrade_preserves_explicit_legacy_install_and_saved_job_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = VerifiedReleaseFixture(root)
            manager = ExtensionManager(root / "managed")
            source, baseline = root / "source", root / "baseline"
            source.mkdir()
            baseline.mkdir()
            with patch("src.deep.install.platform_key", return_value="linux-x64"), patch(
                "src.deep.install.download_verified_transport", side_effect=releases.download,
            ):
                legacy = manager.install(
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                )
                old_job = DeepJob.create(str(source), str(baseline), DeepSettings(analysisWorkers=2), manager)
                old_job.phase = "paused"
                old_job.save()
                old_saved = (old_job.root / "client.json").read_bytes()
                old_settings = old_job.settings.to_dict()

                current = manager.install()
                self.assertNotEqual(current, legacy)
                self.assertEqual(manager.installation(), current)
                self.assertEqual(json.loads((current / "install.json").read_text())["manifest"]["version"], "0.2.2")
                self.assertEqual(json.loads((legacy / "install.json").read_text())["manifest"]["version"], "0.2.1")
                new_job = DeepJob.create(str(source), str(baseline), DeepSettings(analysisWorkers=3), manager)
                self.assertEqual(new_job.installation, current)
                self.assertEqual(DeepJob.load(new_job.root).installation, current)
                restored = DeepJob.load(old_job.root)
                self.assertEqual(restored.installation, legacy)
                self.assertEqual(restored.phase, "paused")
                self.assertEqual(restored.settings.to_dict(), old_settings)
                self.assertEqual((old_job.root / "client.json").read_bytes(), old_saved)
                self.assertEqual((legacy / "node/bin/node").read_bytes(), b"fixture runtime 0.2.1\n")
                self.assertEqual((legacy / "engine/dist/host/main.js").read_bytes(), b"fixture engine 0.2.1\n")
                self.assertEqual((current / "node/bin/node").read_bytes(), b"fixture runtime 0.2.2\n")
                self.assertEqual((current / "engine/dist/host/main.js").read_bytes(), b"fixture engine 0.2.2\n")
                old_command = [str(legacy / "node/bin/node"), str(legacy / "engine/dist/host/main.js")]
                new_command = [str(current / "node/bin/node"), str(current / "engine/dist/host/main.js")]
                self.assertEqual(manager.command(restored.installation), old_command)
                self.assertEqual(manager.command(new_job.installation), new_command)
                self.assertEqual(manager.command(), new_command)

                self.assertEqual(manager.install(
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                ), legacy)
                self.assertEqual(manager.installation(), legacy)
                self.assertEqual(manager.command(), old_command)
                self.assertEqual(manager.command(DeepJob.load(new_job.root).installation), new_command)
                self.assertEqual(manager.command(DeepJob.load(old_job.root).installation), old_command)
                self.assertEqual((old_job.root / "client.json").read_bytes(), old_saved)
                self.assertEqual(releases.requested_urls, [
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/fixture-deep-linux-x64.zip",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/deep-manifest.json",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/fixture-deep-linux-x64.zip",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                ])

    def test_custom_codex_executable_survives_settings_and_job_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = DeepSettings(runtime="codex", provider="codex", model="discovered", freeOnly=False,
                                    executable="/custom installation/bin/codex")
            save_settings(settings, root)
            self.assertEqual(load_settings(root), settings)
            job = DeepJob(root / "jobs" / "one", "/source", "/baseline", root / "v1", settings, "paused")
            job.save()
            self.assertEqual(pending_jobs(root)[0].settings.executable, settings.executable)
            self.assertEqual(settings.to_dict()["executable"], settings.executable)

    def test_executable_defaults_to_detection_and_rejects_invalid_paths(self) -> None:
        self.assertIsNone(DeepSettings().executable)
        self.assertIsNone(DeepSettings().to_dict()["executable"])
        for executable in ("", "   ", "codex\x00extra"):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(ValueError, "executable"):
                    DeepSettings(executable=executable).validate()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "settings.json").write_text('{"executable":123}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "executable"):
                load_settings(root)

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
