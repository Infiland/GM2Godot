from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.deep.jobs import DeepJob
from src.deep.settings import DeepSettings
from src.deep_cli import main, run_job


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
