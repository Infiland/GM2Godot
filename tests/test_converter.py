# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import sys
import threading
import tempfile
import shutil
import unittest
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.base_converter import BaseConverter
from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionStepResult,
)
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
from src.conversion.project_godot import ConversionPreflightError


class TestConversionCategories(unittest.TestCase):
    """Test that CONVERSION_CATEGORIES has the expected structure."""

    def test_has_three_groups(self):
        self.assertEqual(len(CONVERSION_CATEGORIES), 3)

    def test_expected_keys(self):
        self.assertIn("assets", CONVERSION_CATEGORIES)
        self.assertIn("project", CONVERSION_CATEGORIES)
        self.assertIn("wip", CONVERSION_CATEGORIES)

    def test_assets_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["assets"],
                         ["sprites", "fonts", "sounds", "sound_group_folders", "included_files", "scripts", "objects", "rooms", "asset_registry"])

    def test_project_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["project"],
                         ["game_icon", "project_name", "project_settings",
                          "audio_buses", "notes"])

    def test_wip_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["wip"],
                         ["shaders", "tilesets"])


class _FakeBooleanVar:
    """Mimics tkinter BooleanVar for testing."""
    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


class TestConverterOutcomes(unittest.TestCase):
    def setUp(self) -> None:
        self.running = threading.Event()
        self.running.set()
        self.converter = Converter(
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=self.running,
        )

    @staticmethod
    def _settings(*keys: str) -> dict[str, _FakeBooleanVar]:
        return {key: _FakeBooleanVar(True) for key in keys}

    @contextmanager
    def _environment(
        self,
        runners: dict[str, Callable[[], object]],
        *,
        preflight_error: Exception | None = None,
        runner_build_error: object | None = None,
        diagnostic_side_effect: object | None = None,
        architecture_error: object | None = None,
        manifest_error: object | None = None,
    ) -> Generator[dict[str, MagicMock]]:
        with (
            patch("src.conversion.converter.capture_conversion_output_snapshot") as capture,
            patch(
                "src.conversion.converter.prepare_godot_project_destination",
                side_effect=preflight_error,
            ) as prepare,
            patch.object(
                self.converter,
                "_build_step_runners",
                return_value=runners,
                side_effect=runner_build_error,
            ) as build_runners,
            patch(
                "src.conversion.converter.write_conversion_diagnostic_reports",
                side_effect=diagnostic_side_effect,
            ) as write_diagnostics,
            patch(
                "src.conversion.converter.invalidate_conversion_diagnostic_reports",
            ) as invalidate_diagnostics,
            patch(
                "src.conversion.converter.write_architecture_policy_report",
                side_effect=architecture_error,
            ) as write_architecture,
            patch(
                "src.conversion.converter.write_conversion_manifest",
                side_effect=manifest_error,
            ) as write_manifest,
        ):
            yield {
                "capture": capture,
                "prepare": prepare,
                "build_runners": build_runners,
                "write_diagnostics": write_diagnostics,
                "invalidate_diagnostics": invalidate_diagnostics,
                "write_architecture": write_architecture,
                "write_manifest": write_manifest,
            }

    def test_success_counts_requested_executed_and_completed_converters(self) -> None:
        with self._environment(
            {
                "scripts": lambda: ConversionStepResult(),
                "objects": lambda: ConversionStepResult(),
            }
        ):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts", "objects"),
            )

        self.assertEqual(outcome.state, "success")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=2, executed=2, completed=2),
        )
        self.assertEqual(outcome.resources, ConversionCounts())
        self.assertIs(self.converter.last_outcome, outcome)
        self.assertIs(self.converter.diagnostics.outcome(), outcome)

    def test_initially_cancelled_skips_every_requested_converter(self) -> None:
        self.running.clear()
        scripts = MagicMock(return_value=ConversionStepResult())
        objects = MagicMock(return_value=ConversionStepResult())

        with self._environment({"scripts": scripts, "objects": objects}):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts", "objects"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=2, skipped=2),
        )
        scripts.assert_not_called()
        objects.assert_not_called()

    def test_cancellation_during_first_converter_skips_it_and_remaining_work(self) -> None:
        def cancel() -> ConversionStepResult:
            self.running.clear()
            return ConversionStepResult(cancelled=True)

        objects = MagicMock(return_value=ConversionStepResult())
        with self._environment({"scripts": cancel, "objects": objects}):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts", "objects"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=2, executed=1, skipped=2),
        )
        objects.assert_not_called()

    def test_cancellation_after_runner_return_keeps_converter_completed(self) -> None:
        def complete_then_cancel() -> ConversionStepResult:
            self.running.clear()
            return ConversionStepResult(
                resources=ConversionCounts(
                    requested=1,
                    executed=1,
                    completed=1,
                )
            )

        objects = MagicMock(return_value=ConversionStepResult())
        with self._environment(
            {"scripts": complete_then_cancel, "objects": objects}
        ):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts", "objects"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=1,
                skipped=1,
            ),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        objects.assert_not_called()

    def test_cancellation_during_final_converter_keeps_prior_completion(self) -> None:
        def cancel() -> ConversionStepResult:
            self.running.clear()
            return ConversionStepResult(cancelled=True)

        with self._environment(
            {
                "scripts": lambda: ConversionStepResult(),
                "objects": cancel,
            }
        ):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts", "objects"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )

    def test_resource_skip_makes_normally_completed_converter_partial(self) -> None:
        step_result = ConversionStepResult(
            resources=ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            )
        )
        with self._environment({"scripts": lambda: step_result}):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts"),
            )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(outcome.resources, step_result.resources)

    def test_preflight_failure_sets_failed_outcome_before_propagating(self) -> None:
        error = ConversionPreflightError(
            "GM2GD-CONVERT-TEST",
            "unsafe destination",
            destination_path="/godot",
            workaround="Choose another destination.",
        )
        with self._environment({}, preflight_error=error) as calls:
            with self.assertRaises(ConversionPreflightError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, error)
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(self.converter.last_outcome.failure_phase, "preflight")
        self.assertEqual(
            self.converter.last_outcome.converters,
            ConversionCounts(requested=1, skipped=1),
        )
        self.assertIs(
            self.converter.diagnostics.outcome(),
            self.converter.last_outcome,
        )
        calls["build_runners"].assert_not_called()

    def test_runtime_exception_preserves_failed_resource_counts_and_last_outcome(
        self,
    ) -> None:
        error = RuntimeError("script exploded")

        class FailingConverter(BaseConverter):
            def convert_all(self) -> None:
                self._resource_requested("script:bad")
                self._resource_requested("script:not-started")
                self._resource_started("script:bad")
                raise error

        failing = FailingConverter("/gm", "/godot")
        runner = lambda: self.converter._run_base_converter(failing)
        with self._environment({"scripts": runner}):
            with self.assertRaises(RuntimeError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, error)
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(self.converter.last_outcome.failed_step, "scripts")
        self.assertEqual(self.converter.last_outcome.failure_phase, "runtime")
        self.assertEqual(
            self.converter.last_outcome.converters,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self.assertEqual(
            self.converter.last_outcome.resources,
            ConversionCounts(
                requested=2,
                executed=1,
                skipped=1,
                failed=1,
            ),
        )

    def test_runner_build_failure_publishes_failed_outcome_before_reraising(
        self,
    ) -> None:
        build_error = RuntimeError("runner construction failed")
        report_states: list[str | None] = []

        def fail_while_cancelled(_context: object) -> object:
            self.running.clear()
            raise build_error

        def record_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)

        with self._environment(
            {},
            runner_build_error=fail_while_cancelled,
            diagnostic_side_effect=record_report,
        ) as calls:
            with self.assertRaises(RuntimeError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, build_error)
        self.assertEqual(report_states, ["failed"])
        calls["write_architecture"].assert_called_once()
        calls["write_diagnostics"].assert_called_once()
        calls["write_manifest"].assert_called_once()
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(self.converter.last_outcome.failure_phase, "runtime")
        self.assertIsNone(self.converter.last_outcome.failed_step)
        self.assertEqual(
            self.converter.last_outcome.converters,
            ConversionCounts(requested=1, skipped=1),
        )

    def test_runner_build_error_precedes_diagnostic_failure_and_skips_manifest(
        self,
    ) -> None:
        build_error = RuntimeError("runner construction failed")
        diagnostic_error = OSError("diagnostics failed")

        with self._environment(
            {},
            runner_build_error=build_error,
            diagnostic_side_effect=diagnostic_error,
        ) as calls:
            with self.assertRaises(RuntimeError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, build_error)
        calls["write_architecture"].assert_called_once()
        calls["write_diagnostics"].assert_called_once()
        calls["invalidate_diagnostics"].assert_called_once_with("/godot")
        calls["write_manifest"].assert_not_called()
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(self.converter.last_outcome.failure_phase, "runtime")

    def test_legacy_runner_truthiness_does_not_determine_outcome(self) -> None:
        with self._environment(
            {
                "game_icon": lambda: False,
                "project_name": lambda: None,
                "project_settings": lambda: "/generated/path",
            }
        ):
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("game_icon", "project_name", "project_settings"),
            )

        self.assertEqual(outcome.state, "success")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=3, executed=3, completed=3),
        )

    def test_project_operation_checks_cancellation_before_mutation(self) -> None:
        operation = MagicMock(return_value=True)
        self.running.clear()

        result = self.converter._run_project_setting(
            operation,
            self.running.is_set,
        )

        operation.assert_not_called()
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(requested=1, skipped=1),
        )

    def test_real_missing_game_icon_is_partial_and_accounts_for_skipped_resource(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as gm_dir,
            tempfile.TemporaryDirectory() as godot_dir,
        ):
            with open(
                os.path.join(gm_dir, "NoIcon.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"%Name": "No Icon"}, project_file)

            outcome = self.converter.convert(
                gm_dir,
                "windows",
                godot_dir,
                self._settings("game_icon"),
            )

            self.assertFalse(os.path.exists(os.path.join(godot_dir, "icon.png")))

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, executed=1, skipped=1),
        )

    def test_real_project_name_success_accounts_for_completed_resource(self) -> None:
        with (
            tempfile.TemporaryDirectory() as gm_dir,
            tempfile.TemporaryDirectory() as godot_dir,
        ):
            with open(
                os.path.join(gm_dir, "Named.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"%Name": "Named Project"}, project_file)

            outcome = self.converter.convert(
                gm_dir,
                "windows",
                godot_dir,
                self._settings("project_name"),
            )

        self.assertEqual(outcome.state, "success")
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_real_missing_project_options_accounts_for_skipped_resource(self) -> None:
        with (
            tempfile.TemporaryDirectory() as gm_dir,
            tempfile.TemporaryDirectory() as godot_dir,
        ):
            with open(
                os.path.join(gm_dir, "NoOptions.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"%Name": "No Options"}, project_file)

            outcome = self.converter.convert(
                gm_dir,
                "windows",
                godot_dir,
                self._settings("project_settings"),
            )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, executed=1, skipped=1),
        )

    def test_real_project_settings_write_failure_counts_failed_resource(self) -> None:
        with (
            tempfile.TemporaryDirectory() as gm_dir,
            tempfile.TemporaryDirectory() as godot_dir,
        ):
            with open(
                os.path.join(gm_dir, "Settings.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"%Name": "Settings"}, project_file)
            options_dir = os.path.join(gm_dir, "options", "main")
            os.makedirs(options_dir)
            with open(
                os.path.join(options_dir, "options_main.yy"),
                "w",
                encoding="utf-8",
            ) as options_file:
                json.dump({"option_game_speed": 120}, options_file)

            with patch(
                "src.conversion.project_settings.atomic_rewrite_text",
                side_effect=OSError("disk full"),
            ):
                outcome = self.converter.convert(
                    gm_dir,
                    "windows",
                    godot_dir,
                    self._settings("project_settings"),
                )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )

    def test_missing_runner_is_failed_and_raises(self) -> None:
        with self._environment({}):
            with self.assertRaisesRegex(RuntimeError, "scripts"):
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        assert self.converter.last_outcome is not None
        self.assertEqual(
            self.converter.last_outcome.converters,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self.assertEqual(self.converter.last_outcome.failed_step, "scripts")

    def test_runtime_error_precedes_finalizer_error(self) -> None:
        runtime_error = RuntimeError("runner failed")
        finalizer_error = OSError("report failed")

        def fail() -> object:
            raise runtime_error

        with self._environment(
            {"scripts": fail},
            diagnostic_side_effect=finalizer_error,
        ):
            with self.assertRaises(RuntimeError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, runtime_error)
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.failure_phase, "runtime")

    def test_cancellation_during_finalizer_publishes_cancelled_diagnostics(
        self,
    ) -> None:
        report_states: list[str | None] = []

        def record_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)

        def cancel_during_architecture(*_args: object, **_kwargs: object) -> None:
            self.running.clear()

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=record_report,
            architecture_error=cancel_during_architecture,
        ) as calls:
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(report_states, ["cancelled"])
        calls["write_diagnostics"].assert_called_once()

    def test_cancellation_during_diagnostics_rewrites_cancelled_outcome(
        self,
    ) -> None:
        report_states: list[str | None] = []

        def cancel_during_first_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)
            if len(report_states) == 1:
                self.running.clear()

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=cancel_during_first_report,
        ) as calls:
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(report_states, ["success", "cancelled"])
        self.assertEqual(calls["write_diagnostics"].call_count, 2)

    def test_cancellation_during_manifest_refreshes_diagnostics_and_manifest(
        self,
    ) -> None:
        report_states: list[str | None] = []

        def record_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)

        manifest_calls = 0

        def cancel_during_manifest(*_args: object, **_kwargs: object) -> None:
            nonlocal manifest_calls
            manifest_calls += 1
            if manifest_calls == 1:
                self.running.clear()

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=record_report,
            manifest_error=cancel_during_manifest,
        ) as calls:
            outcome = self.converter.convert(
                "/gm",
                "windows",
                "/godot",
                self._settings("scripts"),
            )

        self.assertEqual(outcome.state, "cancelled")
        self.assertEqual(report_states, ["success", "cancelled"])
        self.assertEqual(calls["write_diagnostics"].call_count, 2)
        self.assertEqual(calls["write_manifest"].call_count, 2)

    def test_manifest_failure_with_failed_diagnostic_rewrite_invalidates_reports(
        self,
    ) -> None:
        manifest_error = OSError("manifest failed")
        diagnostic_error = OSError("failed outcome report failed")
        report_states: list[str | None] = []

        def write_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)
            if len(report_states) == 2:
                raise diagnostic_error

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=write_report,
            manifest_error=manifest_error,
        ) as calls:
            with self.assertRaises(OSError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, manifest_error)
        self.assertEqual(report_states, ["success", "failed"])
        calls["write_manifest"].assert_called_once()
        self.assertEqual(calls["write_diagnostics"].call_count, 2)
        calls["invalidate_diagnostics"].assert_called_once_with("/godot")
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "conversion_manifest",
        )

    def test_manifest_failure_invalidates_pre_existing_manifest(self) -> None:
        manifest_error = OSError("manifest failed")
        with tempfile.TemporaryDirectory() as godot_dir:
            manifest_path = os.path.join(
                godot_dir,
                "gm2godot",
                "conversion_manifest.json",
            )
            os.makedirs(os.path.dirname(manifest_path))
            with open(manifest_path, "w", encoding="utf-8") as manifest_file:
                manifest_file.write('{"stale": true}\n')

            with self._environment(
                {"scripts": lambda: ConversionStepResult()},
                manifest_error=manifest_error,
            ):
                with self.assertRaises(OSError) as raised:
                    self.converter.convert(
                        "/gm",
                        "windows",
                        godot_dir,
                        self._settings("scripts"),
                    )

            self.assertIs(raised.exception, manifest_error)
            self.assertFalse(os.path.lexists(manifest_path))

    def test_diagnostic_failure_invalidates_manifest_and_skips_manifest_publish(
        self,
    ) -> None:
        diagnostic_error = OSError("diagnostics failed")
        with tempfile.TemporaryDirectory() as godot_dir:
            manifest_path = os.path.join(
                godot_dir,
                "gm2godot",
                "conversion_manifest.json",
            )
            os.makedirs(os.path.dirname(manifest_path))
            with open(manifest_path, "w", encoding="utf-8") as manifest_file:
                manifest_file.write('{"stale": true}\n')

            with self._environment(
                {"scripts": lambda: ConversionStepResult()},
                diagnostic_side_effect=diagnostic_error,
            ) as calls:
                with self.assertRaises(OSError) as raised:
                    self.converter.convert(
                        "/gm",
                        "windows",
                        godot_dir,
                        self._settings("scripts"),
                    )

            self.assertIs(raised.exception, diagnostic_error)
            self.assertFalse(os.path.lexists(manifest_path))
            calls["write_manifest"].assert_not_called()

    def test_cancelled_diagnostic_rewrite_failure_skips_manifest_refresh(
        self,
    ) -> None:
        diagnostic_error = OSError("cancelled outcome report failed")
        report_states: list[str | None] = []

        def write_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)
            if len(report_states) == 2:
                raise diagnostic_error

        def cancel_during_manifest(*_args: object, **_kwargs: object) -> None:
            self.running.clear()

        with tempfile.TemporaryDirectory() as godot_dir:
            manifest_path = os.path.join(
                godot_dir,
                "gm2godot",
                "conversion_manifest.json",
            )
            os.makedirs(os.path.dirname(manifest_path))
            with open(manifest_path, "w", encoding="utf-8") as manifest_file:
                manifest_file.write('{"success": true}\n')

            with self._environment(
                {"scripts": lambda: ConversionStepResult()},
                diagnostic_side_effect=write_report,
                manifest_error=cancel_during_manifest,
            ) as calls:
                with self.assertRaises(OSError) as raised:
                    self.converter.convert(
                        "/gm",
                        "windows",
                        godot_dir,
                        self._settings("scripts"),
                    )

            self.assertFalse(os.path.lexists(manifest_path))

        self.assertIs(raised.exception, diagnostic_error)
        self.assertEqual(report_states, ["success", "cancelled"])
        calls["write_manifest"].assert_called_once()
        self.assertEqual(calls["write_diagnostics"].call_count, 2)
        calls["invalidate_diagnostics"].assert_called_once_with(godot_dir)
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "conversion_diagnostics",
        )
        self.assertEqual(
            self.converter.last_outcome.failure_phase,
            "finalizer",
        )

    def test_architecture_and_diagnostic_failures_never_publish_success(
        self,
    ) -> None:
        report_states: list[str | None] = []
        architecture_error = OSError("architecture failed")
        diagnostic_error = OSError("diagnostics failed")

        def fail_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)
            raise diagnostic_error

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=fail_report,
            architecture_error=architecture_error,
        ) as calls:
            with self.assertRaises(OSError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, architecture_error)
        self.assertEqual(report_states, ["failed"])
        calls["write_diagnostics"].assert_called_once()
        calls["write_manifest"].assert_not_called()
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "architecture_policy",
        )


class TestConverterSkipsDisabled(unittest.TestCase):
    """Converter.convert() should skip converters whose setting is False."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.statuses: list[str] = []

        # Create minimal GM project structure
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Test" }')

        # Create minimal Godot project
        with open(os.path.join(self.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write('[application]\nconfig/name="Test"\n')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_all_disabled_runs_no_converters(self):
        conversion_running = threading.Event()
        conversion_running.set()

        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            status_callback=lambda msg: self.statuses.append(msg),
            conversion_running=conversion_running,
        )

        # All settings disabled
        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: _FakeBooleanVar(False) for key in all_keys}

        converter.convert(self.gm_dir, "windows", self.godot_dir, settings)

        # With every setting False, no converter log/status messages should appear
        self.assertEqual(self.logs, [])
        self.assertEqual(self.statuses, [])
        self.assertTrue(os.path.isfile(
            os.path.join(self.godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
        ))

    def test_conversion_writes_warning_diagnostics_report(self):
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w", encoding="utf-8") as f:
            f.write('{"resources": [}')

        conversion_running = threading.Event()
        conversion_running.set()

        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            status_callback=lambda msg: self.statuses.append(msg),
            conversion_running=conversion_running,
        )
        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: _FakeBooleanVar(False) for key in all_keys}
        settings["asset_registry"] = _FakeBooleanVar(True)

        converter.convert(self.gm_dir, "windows", self.godot_dir, settings)

        self.assertTrue(any("Warning: Could not parse GameMaker project .yyp" in log for log in self.logs))
        report_path = os.path.join(self.godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)
        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        self.assertEqual(report["summary"]["warning"], 1)
        self.assertEqual(report["diagnostics"][0]["code"], "GM2GD-WARNING")
        self.assertIn("Could not parse GameMaker project .yyp", report["diagnostics"][0]["message"])


class TestConverterRespectsRunningFlag(unittest.TestCase):
    """Converter.convert() should check conversion_running between converters."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.statuses: list[str] = []

        with open(os.path.join(self.gm_dir, "Test.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Test" }')

        with open(os.path.join(self.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write('[application]\nconfig/name="Test"\n')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_stops_when_flag_cleared(self):
        conversion_running = threading.Event()
        # Start cleared -- no converter should run
        # (conversion_running.is_set() returns False)

        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            status_callback=lambda msg: self.statuses.append(msg),
            conversion_running=conversion_running,
        )

        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: _FakeBooleanVar(True) for key in all_keys}

        converter.convert(self.gm_dir, "windows", self.godot_dir, settings)

        # Nothing should have run because the event was never set
        self.assertEqual(self.logs, [])
        self.assertEqual(self.statuses, [])


if __name__ == "__main__":
    unittest.main()
