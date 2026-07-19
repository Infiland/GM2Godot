from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
from typing import cast
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QEventLoop,
    QObject,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QApplication

from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
)
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
from src.gui.setting_value import SettingValue
from src.gui.workers import ConversionWorker, ConversionWorkerResult


class _FakeConverter:
    def __init__(
        self,
        *,
        return_value: object = None,
        error: Exception | None = None,
        last_outcome: object = None,
    ) -> None:
        self.return_value = return_value
        self.error = error
        self.last_outcome = last_outcome

    def convert(
        self,
        _gm_path: str,
        _gm_platform: str,
        _godot_path: str,
        _settings: dict[str, SettingValue],
    ) -> ConversionOutcome:
        if self.error is not None:
            raise self.error
        return cast(ConversionOutcome, self.return_value)


class _SilentError(RuntimeError):
    def __str__(self) -> str:
        return ""


class _UnprintableError(RuntimeError):
    def __str__(self) -> str:
        raise ValueError("stringification failed")


class _QueuedResultReceiver(QObject):
    delivered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.results: list[ConversionWorkerResult] = []
        self.invalid_results: list[object] = []
        self.delivery_thread: QThread | None = None

    @Slot(object)
    def record(self, raw_result: object) -> None:
        self.delivery_thread = QThread.currentThread()
        if isinstance(raw_result, ConversionWorkerResult):
            self.results.append(raw_result)
        else:
            self.invalid_results.append(raw_result)
        self.delivered.emit()


def _completed_steps(*names: str) -> ConversionStepLedger:
    steps = ConversionStepLedger.from_requested(names)
    for name in names:
        steps = steps.start(name).complete(name)
    return steps


def _outcomes() -> dict[str, ConversionOutcome]:
    completed_steps = _completed_steps("scripts", "objects")

    failed_steps = ConversionStepLedger.from_requested(("scripts", "objects"))
    failed_steps = failed_steps.start("scripts").fail("scripts")

    cancelled_steps = ConversionStepLedger.from_requested(("scripts", "objects"))
    cancelled_steps = cancelled_steps.start("scripts")

    return {
        "success": ConversionOutcome(
            state="success",
            steps=completed_steps,
            resources=ConversionCounts(
                requested=4,
                executed=4,
                completed=4,
            ),
        ),
        "partial": ConversionOutcome(
            state="partial",
            steps=completed_steps,
            resources=ConversionCounts(
                requested=5,
                executed=4,
                completed=3,
                skipped=1,
                failed=1,
            ),
        ),
        "failed": ConversionOutcome(
            state="failed",
            steps=failed_steps,
            resources=ConversionCounts(
                requested=3,
                executed=2,
                completed=1,
                skipped=1,
                failed=1,
            ),
            failed_step="scripts",
            failure_phase="runtime",
        ),
        "cancelled": ConversionOutcome(
            state="cancelled",
            steps=cancelled_steps,
            resources=ConversionCounts(
                requested=3,
                executed=1,
                completed=1,
                skipped=2,
            ),
        ),
    }


class ConversionWorkerResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.app = existing if isinstance(existing, QApplication) else QApplication([])

    @staticmethod
    def _worker(godot_path: str = "/godot") -> ConversionWorker:
        conversion_running = threading.Event()
        conversion_running.set()
        return ConversionWorker(
            "/game-maker",
            "macos",
            godot_path,
            {},
            True,
            conversion_running,
        )

    def _run_worker(
        self,
        converter: _FakeConverter,
        *,
        worker: ConversionWorker | None = None,
    ) -> ConversionWorkerResult:
        selected_worker = worker if worker is not None else self._worker()
        results: list[ConversionWorkerResult] = []
        invalid_results: list[object] = []

        def record(raw_result: object) -> None:
            if isinstance(raw_result, ConversionWorkerResult):
                results.append(raw_result)
            else:
                invalid_results.append(raw_result)

        selected_worker.conversion_finished.connect(record)
        with patch("src.gui.workers.Converter", return_value=converter):
            selected_worker.run()

        self.assertEqual(invalid_results, [])
        self.assertEqual(len(results), 1)
        return results[0]

    def test_all_terminal_states_preserve_exact_outcome_and_counts(self) -> None:
        outcomes = _outcomes()
        expected_partial_report = os.path.join(
            os.path.abspath("/godot"),
            DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
        )

        for state, outcome in outcomes.items():
            with self.subTest(state=state):
                result = self._run_worker(
                    _FakeConverter(
                        return_value=outcome,
                        last_outcome=outcome,
                    )
                )

                self.assertIs(result.outcome, outcome)
                assert result.outcome is not None
                self.assertEqual(result.outcome.converters, outcome.converters)
                self.assertEqual(result.outcome.resources, outcome.resources)
                self.assertIsNone(result.error_message)
                self.assertEqual(
                    result.diagnostic_report_path,
                    expected_partial_report if state == "partial" else None,
                )

    def test_exception_preserves_exact_converter_outcome_and_error(self) -> None:
        failed_outcome = _outcomes()["failed"]

        result = self._run_worker(
            _FakeConverter(
                error=RuntimeError("disk full"),
                last_outcome=failed_outcome,
            )
        )

        self.assertIs(result.outcome, failed_outcome)
        self.assertEqual(result.error_message, "disk full")
        self.assertIsNone(result.diagnostic_report_path)

    def test_exception_without_valid_converter_outcome_does_not_fabricate_one(
        self,
    ) -> None:
        result = self._run_worker(
            _FakeConverter(
                error=RuntimeError("disk full"),
                last_outcome=object(),
            )
        )

        self.assertIsNone(result.outcome)
        self.assertEqual(result.error_message, "disk full")
        self.assertIsNone(result.diagnostic_report_path)

    def test_empty_exception_message_uses_exception_class_name(self) -> None:
        result = self._run_worker(
            _FakeConverter(
                error=_SilentError(),
                last_outcome=None,
            )
        )

        self.assertIsNone(result.outcome)
        self.assertEqual(result.error_message, "_SilentError")
        self.assertIsNone(result.diagnostic_report_path)

    def test_exception_stringification_failure_still_emits_once(self) -> None:
        result = self._run_worker(
            _FakeConverter(
                error=_UnprintableError(),
                last_outcome=None,
            )
        )

        self.assertIsNone(result.outcome)
        self.assertEqual(result.error_message, "_UnprintableError")
        self.assertIsNone(result.diagnostic_report_path)

    def test_wrong_normal_return_becomes_contract_error_without_dummy_outcome(
        self,
    ) -> None:
        result = self._run_worker(
            _FakeConverter(
                return_value=None,
                last_outcome=None,
            )
        )

        self.assertIsNone(result.outcome)
        self.assertEqual(
            result.error_message,
            "Converter.convert() must return ConversionOutcome; got NoneType.",
        )
        self.assertIsNone(result.diagnostic_report_path)

    def test_result_envelope_rejects_ambiguous_report_contracts(self) -> None:
        partial_outcome = _outcomes()["partial"]
        success_outcome = _outcomes()["success"]

        with self.assertRaisesRegex(ValueError, "requires an outcome or an error"):
            ConversionWorkerResult(None, None, None)
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            ConversionWorkerResult(None, "", None)
        with self.assertRaisesRegex(ValueError, "normal partial result requires"):
            ConversionWorkerResult(partial_outcome, None, None)
        with self.assertRaisesRegex(ValueError, "Only a normal partial"):
            ConversionWorkerResult(success_outcome, None, "/tmp/report.md")
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            ConversionWorkerResult(partial_outcome, None, "relative/report.md")

    def test_partial_report_path_is_absolute_and_captured_at_construction(
        self,
    ) -> None:
        partial_outcome = _outcomes()["partial"]

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            construction_directory = root / "construction"
            later_directory = root / "later"
            construction_directory.mkdir()
            later_directory.mkdir()
            previous_directory = Path.cwd()
            try:
                os.chdir(construction_directory)
                worker = self._worker("relative-output")
                expected_report = os.path.join(
                    os.path.abspath("relative-output"),
                    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
                )
                os.chdir(later_directory)

                result = self._run_worker(
                    _FakeConverter(
                        return_value=partial_outcome,
                        last_outcome=partial_outcome,
                    ),
                    worker=worker,
                )
            finally:
                os.chdir(previous_directory)

        self.assertIs(result.outcome, partial_outcome)
        self.assertEqual(result.diagnostic_report_path, expected_report)
        assert result.diagnostic_report_path is not None
        self.assertTrue(os.path.isabs(result.diagnostic_report_path))

    def test_result_crosses_a_queued_qthread_connection_once(self) -> None:
        partial_outcome = _outcomes()["partial"]
        converter = _FakeConverter(
            return_value=partial_outcome,
            last_outcome=partial_outcome,
        )
        worker = self._worker()
        thread = QThread()
        receiver = _QueuedResultReceiver()
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        receiver.delivered.connect(loop.quit)
        worker.conversion_finished.connect(receiver.record)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        stopped = False
        with patch("src.gui.workers.Converter", return_value=converter):
            thread.start()
            try:
                timeout.start(5_000)
                loop.exec()
            finally:
                timeout.stop()
                thread.quit()
                stopped = thread.wait(5_000)

        self.assertTrue(stopped)
        self.assertEqual(receiver.invalid_results, [])
        self.assertEqual(len(receiver.results), 1)
        self.assertIs(receiver.results[0].outcome, partial_outcome)
        self.assertIs(receiver.delivery_thread, receiver.thread())


if __name__ == "__main__":
    unittest.main()
