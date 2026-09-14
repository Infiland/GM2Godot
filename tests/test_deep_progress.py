# pyright: reportPrivateUsage=false
"""Live job observability, request routing and time survive controls and pauses."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from src.deep.jobs import DeepJob
from src.deep.progress import DeepProgress
from src.deep.session import DeepSession
from src.deep.settings import DeepSettings
from src.gui.main_window import MainWindow
from src.gui.panels.deep_progress_panel import DeepProgressPanel
from src.gui.run_timer import RunTimer
from src.gui.panels.progress_panel import GradientProgressBar
from src.gui.setting_value import SettingValue
from src.gui.workers import ConversionWorker, DeepConversionWorker


class ProgressStateTests(unittest.TestCase):
    def test_task_snapshots_merge_with_agent_updates_and_replayed_events(self) -> None:
        model = DeepProgress()
        model.apply({"result": {"phase": "plan", "tasks": 224, "agents": 3}})
        self.assertEqual(model.tasks, {})
        model.apply({"seq": 1, "result": {"phase": "tasks", "tasks": [
            {"taskId": "obj:player", "label": "Player", "phase": "research", "state": "pending"},
            {"taskId": "room:menu", "phase": "research", "state": "skipped"}]}})
        model.apply({"seq": 2, "result": {"phase": "research", "taskId": "obj:player", "state": "completed", "summary": "Create initializes lives"}})
        model.apply({"seq": 3, "result": {"phase": "agent", "taskId": "obj:player", "agentId": "a1", "state": "completed", "model": "model-a"}})
        model.apply({"seq": 4, "result": {"phase": "tasks", "tasks": [{"taskId": "obj:player", "phase": "implementation", "state": "pending"}]}})
        self.assertFalse(model.apply({"seq": 2, "result": {"phase": "research", "taskId": "obj:player", "state": "running"}}))
        self.assertEqual(model.counts("research"), (2, 2, 0))
        self.assertEqual(model.counts("implementation"), (0, 1, 0))
        self.assertEqual(model.tasks["research:obj:player"]["summary"], "Create initializes lives")
        self.assertEqual(model.agents["a1"]["model"], "model-a")
        with tempfile.TemporaryDirectory() as directory:
            model.save(Path(directory))
            loaded = DeepProgress.load(Path(directory))
            self.assertEqual(loaded.tasks, model.tasks)
            self.assertEqual(loaded.seq, 4)

    def test_pause_clears_phantom_active_agents_but_preserves_completed_tasks(self) -> None:
        model = DeepProgress()
        model.apply({"result": {"phase": "research", "taskId": "pending", "state": "running"}})
        model.apply({"result": {"phase": "research", "taskId": "done", "state": "completed"}})
        model.apply({"result": {"phase": "agent", "taskId": "pending", "agentId": "a", "state": "running"}})
        model.finish("paused", "Rate limited. Progress saved.")
        self.assertEqual(model.tasks["research:pending"]["state"], "pending")
        self.assertEqual(model.counts("research"), (1, 2, 0))
        self.assertEqual(model.agents["a"]["state"], "paused")

    def test_monotonic_timer_keeps_baseline_and_research_but_excludes_review_wait(self) -> None:
        now = [100.0]
        timer = RunTimer(lambda: now[0])
        timer.start()
        now[0] += 12
        self.assertEqual(timer.stop(), 12)
        timer.start(timer.elapsed)
        now[0] += 30
        self.assertEqual(timer.stop(), 42)
        now[0] += 500
        timer.start(timer.elapsed)
        now[0] += 9
        self.assertEqual(timer.elapsed, 51)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = DeepJob(root, "/source", "/baseline", root / "engine", DeepSettings(), elapsed_seconds=timer.stop())
            job.save()
            self.assertEqual(DeepJob.load(root).elapsed_seconds, 51)

    def test_parallel_control_replies_do_not_steal_research_completion(self) -> None:
        script = '''import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if r['method']=='research':
  print(json.dumps({'protocolVersion':1,'id':r['id'],'type':'result','result':{'state':'running'}}),flush=True)
 else:
  print(json.dumps({'protocolVersion':1,'id':r['id'],'type':'result','result':{'analysisWorkers':3}}),flush=True)
  print(json.dumps({'protocolVersion':1,'type':'completed','seq':1,'result':{'state':'review'}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            events: list[dict[str, Any]] = []
            session = DeepSession([sys.executable, "-u", "-c", script], Path(directory), events.append)
            result: list[dict[str, Any]] = []
            thread = threading.Thread(target=lambda: result.append(session.request("research", timeout=5)))
            thread.start()
            try:
                # Registration precedes sending, so wait on the registration rather than a sleep.
                deadline = threading.Event()
                for _ in range(100):
                    with session._routing_lock:
                        registered = bool(session._pending)
                    if registered:
                        break
                    deadline.wait(.01)
                session.notify("configure", {"analysisWorkers": 3})
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result[0]["result"]["state"], "review")
                self.assertEqual(events[0]["method"], "configure")
                self.assertEqual(events[0]["result"]["analysisWorkers"], 3)
            finally:
                session.close()
                thread.join(5)


class ProgressPanelTests(unittest.TestCase):
    application: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = cast(QApplication, QApplication.instance() or QApplication([]))

    def test_progress_retains_fraction_and_formats_two_decimals(self) -> None:
        bar = GradientProgressBar()
        bar.set_progress(100 / 224)
        self.assertEqual(bar.progress_text, "0.45%")
        bar.set_progress(123)
        self.assertEqual(bar.progress_text, "100.00%")
        bar.set_progress(-10)
        self.assertEqual(bar.progress_text, "0.00%")
        bar.close()

    def test_baseline_worker_signal_preserves_fractional_progress(self) -> None:
        worker = ConversionWorker("source", "linux", "target", {}, True, threading.Event())
        bar = GradientProgressBar()
        worker.progress_updated.connect(bar.set_progress)
        worker.progress_updated.emit(100 / 224)
        self.assertEqual(bar.progress_text, "0.45%")
        bar.close()

    def test_search_status_filters_and_recovery_controls(self) -> None:
        panel = DeepProgressPanel()
        model = DeepProgress(features={"monitoring": True, "liveConfiguration": True, "resumeModelSelection": True})
        panel.begin(model, DeepSettings())
        model.apply({"result": {"phase": "tasks", "tasks": [
            {"taskId": "player", "label": "Player", "phase": "research", "state": "completed"},
            {"taskId": "menu", "label": "Main menu", "phase": "research", "state": "blocked", "reason": "Rate limited"}]}})
        panel.refresh()
        self.assertEqual(panel.trees["research"].topLevelItemCount(), 2)
        player = panel.trees["research"].topLevelItem(0)
        menu = panel.trees["research"].topLevelItem(1)
        assert player is not None and menu is not None
        panel.search.setText("menu")
        self.assertTrue(player.isHidden())
        self.assertFalse(menu.isHidden())
        panel.search.clear()
        panel.filter_state.setCurrentText("Completed")
        self.assertFalse(player.isHidden())
        self.assertTrue(menu.isHidden())
        self.assertTrue(panel.apply_button.isEnabled())
        self.assertEqual(panel.resume_button.text(), "Change model…")
        model.finish("paused", "Rate limited; work saved")
        panel.set_running(False)
        panel.refresh()
        self.assertFalse(panel.pause_button.isEnabled())
        self.assertTrue(panel.resume_button.isEnabled())
        panel.close()

    def test_main_window_restarts_deep_timer_and_keeps_settings_available(self) -> None:
        with patch("src.gui.main_window.pending_jobs", return_value=[]):
            window = MainWindow(check_for_updates_on_startup=False)
            try:
                window._prepare_for_conversion()
                self.assertTrue(window._action_panel.settings_button.isEnabled())
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    window._deep_job = DeepJob(root, "/source", "/baseline", root / "engine", DeepSettings(), elapsed_seconds=42)
                    window._deep_job.save()
                    with patch("src.gui.main_window.QThread.start") as start_thread:
                        window._launch_deep("research")
                        start_thread.assert_called_once()
                        self.assertTrue(window._timer.isActive())
                        self.assertIn("00:00:42", window._progress.timer_label.text())
                        self.assertTrue(window._action_panel.settings_button.isEnabled())
                        window._deep_job.phase = "paused"
                        window._deep_finished(False, "Rate limited")
                    self.assertFalse(window._timer.isActive())
                    self.assertTrue(window._deep_progress.resume_button.isEnabled())
                    self.assertGreaterEqual(DeepJob.load(root).elapsed_seconds, 42)
            finally:
                window._deep_thread = None
                window._deep_worker = None
                window.close()
                self.application.processEvents()
                window.deleteLater()

    def test_worker_cleanup_error_still_emits_finished_and_keeps_saved_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = DeepJob(root, "/source", "/baseline", root / "engine", DeepSettings(runtime="mock", freeOnly=False))
            worker = DeepConversionWorker(job)
            results: list[tuple[bool, str]] = []
            def finished(success: bool, message: str) -> None:
                results.append((success, message))
            worker.finished.connect(finished)
            with patch("src.gui.workers.write_host_snapshot"), patch("src.gui.workers.ExtensionManager.command", return_value=["node", "host"]), patch("src.gui.workers.DeepSession") as session:
                session.return_value.request.return_value = {"result": {"state": "review"}}
                session.return_value.close.side_effect = OSError("cleanup failed")
                worker.run()
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0][0])
            self.assertIn("cleanup failed", results[0][1])
            self.assertEqual(DeepJob.load(root).phase, "review")

    def test_progress_persistence_waits_for_host_preparation(self) -> None:
        with patch("src.gui.main_window.pending_jobs", return_value=[]):
            window = MainWindow(check_for_updates_on_startup=False)
            try:
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    window._deep_job = DeepJob(root, "/source", "/baseline", root / "engine", DeepSettings())
                    window._deep_job.save()
                    window._run_timer.start(42)
                    window._save_deep_progress()
                    self.assertEqual({path.name for path in root.iterdir()}, {"client.json"})
                    (root / "host-job.json").write_text("{}")
                    window._save_deep_progress()
                    self.assertTrue((root / "client-progress.json").is_file())
                    self.assertGreaterEqual(DeepJob.load(root).elapsed_seconds, 42)
            finally:
                window.close()
                self.application.processEvents()
                window.deleteLater()

    def test_resume_before_host_preparation_restarts_research(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = DeepJob(root, "/source", "/baseline", root / "engine", DeepSettings(runtime="mock", freeOnly=False), phase="paused")
            worker = DeepConversionWorker(job, method="resume")
            with patch("src.gui.workers.write_host_snapshot") as snapshot, patch("src.gui.workers.ExtensionManager.command", return_value=["node", "host"]), patch("src.gui.workers.DeepSession") as session:
                session.return_value.request.return_value = {"result": {"state": "review"}}
                worker.run()
                snapshot.assert_called_once_with(job.source, str(root / "host-snapshot.json"))
                self.assertEqual([call.args[0] for call in session.return_value.request.call_args_list], ["capabilities", "research"])
            self.assertEqual(DeepJob.load(root).phase, "review")

    def test_settings_edits_do_not_mutate_a_running_baseline_worker(self) -> None:
        choices = {"scripts": SettingValue(True)}
        worker = ConversionWorker("source", "linux", "target", choices, True, threading.Event())
        choices["scripts"].set(False)
        self.assertTrue(worker._conversion_settings["scripts"].get())
