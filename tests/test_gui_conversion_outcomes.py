# pyright: reportPrivateUsage=false
# ruff: noqa: E402

from __future__ import annotations

import os
import threading
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from src.gui.main_window import MainWindow
from src.gui.panels.console_panel import ConsolePanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.workers import ConversionWorker
from src.localization import get_localized


class _MainWindowOutcomeHarness:
    def __init__(self) -> None:
        self._progress = ProgressPanel()
        self._console = ConsolePanel()
        self._action_panel = SimpleNamespace(
            convert_button=QPushButton(),
            stop_button=QPushButton(),
            settings_button=QPushButton(),
        )
        self._conversion_running = threading.Event()
        self._conversion_thread = None
        self._worker = None
        self.timer_stopped = False

    def _stop_timer(self) -> None:
        self.timer_stopped = True


class ConversionWorkerOutcomeTests(unittest.TestCase):
    def test_exception_emits_failure_outcome_instead_of_success(self) -> None:
        converter = MagicMock()
        converter.convert.side_effect = RuntimeError("disk full")
        conversion_running = threading.Event()
        conversion_running.set()
        worker = ConversionWorker(
            "/game-maker",
            "macos",
            "/godot",
            {},
            True,
            conversion_running,
        )
        outcomes: list[tuple[bool, str]] = []

        def record_outcome(succeeded: bool, error: str) -> None:
            outcomes.append((succeeded, error))

        worker.conversion_finished.connect(record_outcome)

        with patch("src.gui.workers.Converter", return_value=converter):
            worker.run()

        self.assertEqual(outcomes, [(False, "disk full")])


class MainWindowConversionOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing_app = QApplication.instance()
        cls.app = existing_app if isinstance(existing_app, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.harness = _MainWindowOutcomeHarness()
        self.window = cast(MainWindow, self.harness)

    def tearDown(self) -> None:
        self.harness._progress.deleteLater()
        self.harness._console.deleteLater()
        self.harness._action_panel.convert_button.deleteLater()
        self.harness._action_panel.stop_button.deleteLater()
        self.harness._action_panel.settings_button.deleteLater()

    def test_cancelled_conversion_keeps_partial_progress_and_stopped_status(self) -> None:
        self.window._progress.progress_bar.set_progress(37)
        self.window._conversion_running.clear()

        MainWindow._conversion_complete(self.window, True, "")

        stopped_message = get_localized("Console_ConversionStopped")
        self.assertEqual(self.window._progress.progress_bar._progress, 37)
        self.assertEqual(self.window._progress.status_label.text(), stopped_message)
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(stopped_message, console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete"), console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)

    def test_failed_conversion_keeps_partial_progress_and_displays_error(self) -> None:
        self.window._progress.progress_bar.set_progress(42)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(self.window, False, "disk full")

        failure_message = get_localized("Console_ConversionFailed").format(
            error="disk full"
        )
        self.assertEqual(self.window._progress.progress_bar._progress, 42)
        self.assertEqual(self.window._progress.status_label.text(), failure_message)
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(failure_message, console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete"), console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)

    def test_successful_conversion_still_reaches_complete_state(self) -> None:
        self.window._progress.progress_bar.set_progress(84)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(self.window, True, "")

        self.assertEqual(self.window._progress.progress_bar._progress, 100)
        self.assertEqual(
            self.window._progress.status_label.text(),
            get_localized("Console_ConversionComplete"),
        )
        self.assertIn(
            get_localized("Console_ConversionComplete_B"),
            self.window._console._text_edit.toPlainText(),
        )


if __name__ == "__main__":
    unittest.main()
