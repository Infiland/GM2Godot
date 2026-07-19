# pyright: reportPrivateUsage=false
# ruff: noqa: E402

from __future__ import annotations

import os
import threading
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
)
from src.gui.main_window import MainWindow
from src.gui.panels.console_panel import ConsoleLogStyle, ConsolePanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.workers import ConversionWorkerResult
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
        self._action_panel.convert_button.setEnabled(False)
        self._action_panel.stop_button.setEnabled(True)
        self._action_panel.settings_button.setEnabled(False)
        self._conversion_running = threading.Event()
        self._conversion_thread = None
        self._worker = None
        self.timer_stopped = False

    def _stop_timer(self) -> None:
        self.timer_stopped = True

    def _append_resource_counts(
        self,
        outcome: ConversionOutcome,
        style: ConsoleLogStyle,
    ) -> None:
        MainWindow._append_resource_counts(
            cast(MainWindow, self),
            outcome,
            style,
        )

    def _present_conversion_result(self, result: ConversionWorkerResult) -> None:
        MainWindow._present_conversion_result(cast(MainWindow, self), result)

    def _finish_conversion_lifecycle(self) -> None:
        MainWindow._finish_conversion_lifecycle(cast(MainWindow, self))


def _completed_steps(*names: str) -> ConversionStepLedger:
    steps = ConversionStepLedger.from_requested(names)
    for name in names:
        steps = steps.start(name).complete(name)
    return steps


def _outcome(state: str) -> ConversionOutcome:
    if state == "success":
        return ConversionOutcome(
            state="success",
            steps=_completed_steps("scripts", "objects"),
            resources=ConversionCounts(
                requested=4,
                executed=4,
                completed=4,
            ),
        )
    if state == "partial":
        return ConversionOutcome(
            state="partial",
            steps=_completed_steps("scripts", "objects"),
            resources=ConversionCounts(
                requested=5,
                executed=4,
                completed=3,
                skipped=1,
                failed=1,
            ),
        )
    if state == "failed":
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        return ConversionOutcome(
            state="failed",
            steps=steps.start("scripts").fail("scripts"),
            resources=ConversionCounts(
                requested=3,
                executed=2,
                completed=1,
                skipped=1,
                failed=1,
            ),
            failed_step="scripts",
            failure_phase="runtime",
        )
    if state == "cancelled":
        steps = ConversionStepLedger.from_requested(("scripts", "objects"))
        return ConversionOutcome(
            state="cancelled",
            steps=steps.start("scripts"),
            resources=ConversionCounts(
                requested=3,
                executed=1,
                completed=1,
                skipped=2,
            ),
        )
    raise ValueError(f"Unsupported test outcome: {state}")


def _resource_message(outcome: ConversionOutcome) -> str:
    counts = outcome.resources
    return get_localized("Console_ConversionResourceCounts").format(
        requested=counts.requested,
        executed=counts.executed,
        completed=counts.completed,
        skipped=counts.skipped,
        failed=counts.failed,
    )


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

    def _assert_cleanup(self) -> None:
        self.assertFalse(self.window._conversion_running.is_set())
        self.assertTrue(self.window._action_panel.convert_button.isEnabled())
        self.assertFalse(self.window._action_panel.stop_button.isEnabled())
        self.assertTrue(self.window._action_panel.settings_button.isEnabled())
        self.assertTrue(self.harness.timer_stopped)

    def test_success_uses_exact_outcome_even_when_stop_event_is_clear(self) -> None:
        outcome = _outcome("success")
        self.window._progress.progress_bar.set_progress(84)
        self.window._conversion_running.clear()

        MainWindow._conversion_complete(
            self.window,
            ConversionWorkerResult(outcome, None, None),
        )

        self.assertEqual(self.window._progress.progress_bar._progress, 100)
        self.assertEqual(self.window._progress.presentation_state, "success")
        self.assertEqual(
            self.window._progress.status_label.text(),
            get_localized("Console_ConversionComplete"),
        )
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(get_localized("Console_ConversionComplete_B"), console_text)
        self.assertIn(_resource_message(outcome), console_text)
        self._assert_cleanup()

    def test_partial_is_amber_with_counts_and_report_while_event_is_set(self) -> None:
        outcome = _outcome("partial")
        report_path = "/godot/gm2godot/conversion_diagnostics.md"
        self.window._progress.progress_bar.set_progress(72)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(
            self.window,
            ConversionWorkerResult(outcome, None, report_path),
        )

        self.assertEqual(self.window._progress.progress_bar._progress, 100)
        self.assertEqual(self.window._progress.presentation_state, "partial")
        self.assertEqual(
            self.window._progress.status_label.text(),
            get_localized("Console_ConversionPartial"),
        )
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(get_localized("Console_ConversionPartial"), console_text)
        self.assertIn(_resource_message(outcome), console_text)
        self.assertIn(report_path, console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)
        self._assert_cleanup()

    def test_failed_outcome_preserves_progress_and_counts(self) -> None:
        outcome = _outcome("failed")
        self.window._progress.progress_bar.set_progress(42)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(
            self.window,
            ConversionWorkerResult(outcome, None, None),
        )

        self.assertEqual(self.window._progress.progress_bar._progress, 42)
        self.assertEqual(self.window._progress.presentation_state, "failed")
        self.assertEqual(
            self.window._progress.status_label.text(),
            get_localized("Console_ConversionFailedState"),
        )
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(get_localized("Console_ConversionFailedState"), console_text)
        self.assertIn(_resource_message(outcome), console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)
        self._assert_cleanup()

    def test_cancelled_outcome_preserves_progress_even_when_event_is_set(self) -> None:
        outcome = _outcome("cancelled")
        self.window._progress.progress_bar.set_progress(37)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(
            self.window,
            ConversionWorkerResult(outcome, None, None),
        )

        stopped_message = get_localized("Console_ConversionStopped")
        self.assertEqual(self.window._progress.progress_bar._progress, 37)
        self.assertEqual(self.window._progress.presentation_state, "cancelled")
        self.assertEqual(self.window._progress.status_label.text(), stopped_message)
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(stopped_message, console_text)
        self.assertIn(_resource_message(outcome), console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)
        self._assert_cleanup()

    def test_worker_exception_preserves_failed_counts_and_error_detail(self) -> None:
        outcome = _outcome("failed")
        self.window._progress.progress_bar.set_progress(41)
        self.window._conversion_running.set()

        MainWindow._conversion_complete(
            self.window,
            ConversionWorkerResult(outcome, "disk full", None),
        )

        failure_message = get_localized("Console_ConversionFailed").format(error="disk full")
        self.assertEqual(self.window._progress.progress_bar._progress, 41)
        self.assertEqual(self.window._progress.presentation_state, "failed")
        self.assertEqual(self.window._progress.status_label.text(), failure_message)
        console_text = self.window._console._text_edit.toPlainText()
        self.assertIn(failure_message, console_text)
        self.assertIn(_resource_message(outcome), console_text)
        self.assertNotIn(get_localized("Console_ConversionComplete_B"), console_text)
        self._assert_cleanup()

    def test_presentation_failure_still_restores_conversion_lifecycle(self) -> None:
        outcome = _outcome("success")
        self.window._conversion_running.set()

        with patch.object(
            self.window._console,
            "append_log",
            side_effect=RuntimeError("render failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                MainWindow._conversion_complete(
                    self.window,
                    ConversionWorkerResult(outcome, None, None),
                )

        self._assert_cleanup()


if __name__ == "__main__":
    unittest.main()
