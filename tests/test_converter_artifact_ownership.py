from __future__ import annotations

import threading
import unittest
from collections.abc import Callable
from unittest.mock import patch

from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import Converter


class TestConverterArtifactOwnership(unittest.TestCase):
    def setUp(self) -> None:
        self.logs: list[str] = []
        self.progress: list[int | float] = []
        self.status: list[str] = []
        self.updates: list[str] = []
        self.finalizations: list[str] = []
        self.running = threading.Event()
        self.running.set()
        self.converter = Converter(
            log_callback=self.logs.append,
            progress_callback=self.progress.append,
            status_callback=self.status.append,
            conversion_running=self.running,
            update_log_callback=self.updates.append,
            staged_output_finalizer=self.finalizations.append,
        )
        self.converter.diagnostics.add(
            "warning", "existing-diagnostic", "Preserve this diagnostic on refusal."
        )

    def _assert_preflight_refusal(
        self, publish: Callable[[Converter, ConversionOutcome], object]
    ) -> None:
        diagnostics = self.converter.diagnostics
        diagnostic_json = diagnostics.to_json()
        outcome = ConversionOutcome(state="failed", failure_phase="preflight")
        with (
            patch(
                "src.conversion.converter.recover_managed_output_generation",
                side_effect=AssertionError("Recovery must not begin before preflight."),
            ) as recover,
            patch(
                "src.conversion.converter.capture_conversion_output_snapshot",
                side_effect=AssertionError("Output inspection must not begin before preflight."),
            ) as capture,
            patch(
                "src.conversion.converter.publish_managed_output_attempt",
                side_effect=AssertionError("Attempt publication must not begin before preflight."),
            ) as publish_attempt,
            patch(
                "src.conversion.converter.write_conversion_artifacts",
                side_effect=AssertionError("Artifact publication must not begin before preflight."),
            ) as write_artifacts,
            self.assertRaises(RuntimeError) as caught,
        ):
            publish(self.converter, outcome)

        self.assertIs(type(caught.exception), RuntimeError)
        self.assertEqual(
            str(caught.exception),
            "Cannot publish a conversion attempt before conversion preflight.",
        )
        self.assertIsNone(self.converter.last_outcome)
        self.assertIs(self.converter.diagnostics, diagnostics)
        self.assertIsNone(diagnostics.outcome())
        self.assertEqual(diagnostics.to_json(), diagnostic_json)
        self.assertTrue(self.running.is_set())
        self.assertEqual(self.logs, [])
        self.assertEqual(self.progress, [])
        self.assertEqual(self.status, [])
        self.assertEqual(self.updates, [])
        self.assertEqual(self.finalizations, [])
        recover.assert_not_called()
        capture.assert_not_called()
        publish_attempt.assert_not_called()
        write_artifacts.assert_not_called()

    def test_publish_attempt_requires_preflight_without_side_effects(self) -> None:
        self._assert_preflight_refusal(Converter.publish_conversion_attempt)

    def test_refresh_artifacts_requires_preflight_without_side_effects(self) -> None:
        self._assert_preflight_refusal(Converter.refresh_conversion_artifacts)
