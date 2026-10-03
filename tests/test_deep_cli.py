from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.deep.install import ExtensionManager
from src.deep.jobs import DeepJob
from src.deep.settings import DeepSettings
from src.deep_cli import main, run_job
from tests.test_deep_client import VerifiedReleaseFixture


class DeepCliOutcomeTests(unittest.TestCase):
    def test_interrupted_research_never_becomes_review_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = DeepJob(Path(directory), "/source", "/baseline", Path("/installation"),
                          DeepSettings(runtime="mock", model="mock", freeOnly=False))
            session = MagicMock()
            session.request.return_value = {
                "protocolVersion": 1, "type": "completed",
                "result": {"state": "paused", "error": {"message": "No free model passed"}},
            }
            with patch("src.deep_cli.DeepSession", return_value=session), patch("src.deep_cli.ExtensionManager"):
                self.assertEqual(run_job(job, "research"), 1)
            self.assertEqual(DeepJob.load(Path(directory)).phase, "paused")
            session.close.assert_called_once()

    def test_successful_research_stops_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = DeepJob(Path(directory), "/source", "/baseline", Path("/installation"),
                          DeepSettings(runtime="mock", model="mock", freeOnly=False))
            session = MagicMock()
            session.request.return_value = {"type": "completed", "result": {"state": "review"}}
            with patch("src.deep_cli.DeepSession", return_value=session), patch("src.deep_cli.ExtensionManager"):
                self.assertEqual(run_job(job, "research"), 0)
            self.assertEqual(DeepJob.load(Path(directory)).phase, "review")


class DeepCliSetupTests(unittest.TestCase):
    def test_install_uses_shipped_default_and_preserves_explicit_manifest_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = VerifiedReleaseFixture(root)
            manager = ExtensionManager(root / "managed")
            output = io.StringIO()
            with patch("src.deep_cli.ExtensionManager", return_value=manager), patch(
                "src.deep.install.platform_key", return_value="linux-x64",
            ), patch("src.deep.install.download_verified_transport", side_effect=releases.download), redirect_stdout(output):
                self.assertEqual(main(["install"]), 0)
                current = manager.installation()
                self.assertEqual(json.loads((current / "install.json").read_text())["manifest"]["version"], "0.2.2")
                self.assertEqual(manager.command(), [
                    str(current / "node/bin/node"), str(current / "engine/dist/host/main.js"),
                ])
                self.assertEqual((current / "engine/dist/host/main.js").read_bytes(), b"fixture engine 0.2.2\n")

                self.assertEqual(main([
                    "install", "--manifest-url",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                ]), 0)
                legacy = manager.installation()
                self.assertNotEqual(legacy, current)
                self.assertEqual(json.loads((legacy / "install.json").read_text())["manifest"]["version"], "0.2.1")
                self.assertEqual((legacy / "engine/dist/host/main.js").read_bytes(), b"fixture engine 0.2.1\n")
                self.assertEqual(manager.command(current), [
                    str(current / "node/bin/node"), str(current / "engine/dist/host/main.js"),
                ])
                self.assertEqual(releases.requested_urls, [
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/deep-manifest.json",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.2/fixture-deep-linux-x64.zip",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/deep-manifest.json",
                    "https://github.com/Infiland/GM2Godot/releases/download/deep-v0.2.1/fixture-deep-linux-x64.zip",
                ])
            self.assertEqual(output.getvalue().splitlines(), [str(current), str(legacy)])

    def test_configure_custom_codex_path_then_restore_auto_detection(self) -> None:
        settings = DeepSettings()
        with patch("src.deep_cli.load_settings", return_value=settings), patch("src.deep_cli.save_settings") as save:
            self.assertEqual(main(["configure", "--runtime", "codex", "--provider", "codex", "--model", "discovered",
                                   "--allow-paid", "--executable", "/custom installation/codex"]), 0)
            self.assertEqual(save.call_args.args[0].executable, "/custom installation/codex")
            self.assertFalse(settings.freeOnly)
            self.assertEqual(main(["configure", "--executable", ""]), 0)
            self.assertIsNone(save.call_args.args[0].executable)
            settings.executable = "/custom installation/codex"
            self.assertEqual(main(["configure", "--runtime", "claude", "--provider", "claude"]), 0)
            self.assertIsNone(save.call_args.args[0].executable)

    def test_codex_configure_never_imports_an_api_key(self) -> None:
        settings = DeepSettings(runtime="codex", provider="codex", model="discovered", freeOnly=False)
        with patch("src.deep_cli.load_settings", return_value=settings), patch("src.deep_cli.save_settings") as save, patch("src.deep_cli.save_credential") as credential:
            self.assertEqual(main(["configure", "--api-key-stdin"]), 1)
            credential.assert_not_called()
            save.assert_not_called()

    def test_discovery_uses_saved_settings_and_managed_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = MagicMock()
            manager.root = Path(directory)
            session = MagicMock()
            session.request.return_value = {"type": "result", "result": {}}
            with patch("src.deep_cli.ExtensionManager", return_value=manager), patch("src.deep_cli.DeepSession", return_value=session) as session_class, patch("src.deep_cli.load_settings", return_value=DeepSettings()), patch("src.deep_cli.credential_environment", return_value={}), patch("src.deep_cli.opencode_path", return_value="/managed/opencode"):
                self.assertEqual(main(["models"]), 0)
            self.assertTrue(session_class.call_args.kwargs["environment"]["PATH"].startswith("/managed"))
            self.assertEqual(session.request.call_args.args[1]["settings"]["model"], "automatic-free")

    def test_free_resume_cannot_enable_paid_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = DeepJob(Path(directory), "/source", "/baseline", Path("/installation"), DeepSettings(), "paused")
            job.save()
            with patch("src.deep_cli.run_job") as run:
                self.assertEqual(main(["resume", "--job", directory, "--max-cost-usd", "1"]), 1)
                run.assert_not_called()
            self.assertEqual(DeepJob.load(Path(directory)).settings.budgets["maxCostUsd"], 0)


class DeepCliBaselineTests(unittest.TestCase):
    def test_partial_baseline_can_be_researched_but_failed_conversion_cannot(self) -> None:
        for exit_code in (0, 1, 2):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                baseline = Path(directory)
                (baseline / "project.godot").write_text("config_version=5\n")
                job = DeepJob(baseline / "job", "/source", directory, Path("/installation"), DeepSettings())
                with patch("src.cli.main", return_value=exit_code), patch("src.deep_cli.load_settings", return_value=DeepSettings()), patch("src.deep_cli.ExtensionManager"), patch("src.deep_cli.DeepJob.create", return_value=job), patch("src.deep_cli.write_host_snapshot"), patch("src.deep_cli.run_job", return_value=0) as run:
                    result = main(["research", "--gm-project", "/source", "--godot-project", directory, "--allow-source-upload"])
                if exit_code == 1:
                    self.assertEqual(result, 1)
                    run.assert_not_called()
                else:
                    self.assertEqual(result, 0)
                    run.assert_called_once_with(job, "research")
