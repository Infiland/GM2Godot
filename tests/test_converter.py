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
from src.conversion.conversion_context import ConversionContext, enabled_converter_keys
from src.conversion.converter import (
    CONVERSION_CATEGORIES,
    Converter,
    _FinalizerReportCheckpoint,
)
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepResult,
)
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
from src.conversion.generation_inventory import GenerationInventory
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

    def test_enabled_converter_keys_filter_non_step_settings(self) -> None:
        settings = {
            "scripts": _FakeBooleanVar(True),
            "sound_group_folders": _FakeBooleanVar(True),
            "future_ui_toggle": _FakeBooleanVar(True),
        }

        self.assertEqual(enabled_converter_keys(settings), ("scripts",))


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
        def publish_diagnostics(*args: object) -> object:
            if diagnostic_side_effect is None:
                return MagicMock()
            if isinstance(diagnostic_side_effect, BaseException):
                raise diagnostic_side_effect
            if callable(diagnostic_side_effect):
                result = diagnostic_side_effect(*args)
                return MagicMock() if result is None else result
            raise TypeError("Unsupported diagnostic publication test side effect.")

        workspace = MagicMock()
        workspace.stage_path = "/godot"
        workspace.destination_path = "/godot"
        workspace.preserved_for_recovery = False
        workspace.read_staged_bytes.return_value = b"{}\n"
        workspace.__enter__.return_value = workspace
        workspace.__exit__.return_value = None

        with (
            patch("src.conversion.converter.recover_managed_output_generation"),
            patch(
                "src.conversion.converter.ManagedOutputWorkspace.open",
                return_value=workspace,
            ),
            patch("src.conversion.converter.inspect_godot_project_destination"),
            patch("src.conversion.converter.stage_inventory_carry_forward"),
            patch(
                "src.conversion.converter.capture_generation_inventory",
                return_value=GenerationInventory(),
            ),
            patch("src.conversion.converter.validate_staged_generation_inventory"),
            patch("src.conversion.converter.publish_managed_output_generation"),
            patch("src.conversion.converter.publish_managed_output_attempt"),
            patch("src.conversion.converter.capture_conversion_output_snapshot") as capture,
            patch(
                "src.conversion.converter.capture_conversion_diagnostic_reports"
            ) as capture_diagnostics,
            patch(
                "src.conversion.converter.capture_architecture_policy_snapshot"
            ) as capture_architecture,
            patch(
                "src.conversion.converter.restore_conversion_diagnostic_reports"
            ) as restore_diagnostics,
            patch(
                "src.conversion.converter.restore_architecture_policy_snapshot"
            ) as restore_architecture,
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
                "src.conversion.converter.publish_conversion_diagnostic_reports",
                side_effect=publish_diagnostics,
            ) as write_diagnostics,
            patch(
                "src.conversion.converter.publish_architecture_policy_report",
                side_effect=architecture_error,
            ) as write_architecture,
            patch(
                "src.conversion.converter.write_conversion_artifacts",
                side_effect=manifest_error,
                return_value=(
                    "/godot/gm2godot/conversion_manifest.json",
                    "/godot/gm2godot/conversion_attempt.json",
                ),
            ) as write_artifacts,
        ):
            capture.return_value.generation_inventory = GenerationInventory()
            yield {
                "capture": capture,
                "capture_diagnostics": capture_diagnostics,
                "capture_architecture": capture_architecture,
                "restore_diagnostics": restore_diagnostics,
                "restore_architecture": restore_architecture,
                "prepare": prepare,
                "build_runners": build_runners,
                "write_diagnostics": write_diagnostics,
                "write_architecture": write_architecture,
                "write_artifacts": write_artifacts,
            }

    def test_success_counts_requested_executed_and_completed_converters(self) -> None:
        with self._environment(
            {
                "scripts": lambda: ConversionStepResult(),
                "objects": lambda: ConversionStepResult(),
            }
        ) as calls:
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
        self.assertEqual(outcome.steps.requested, ("scripts", "objects"))
        self.assertEqual(outcome.steps.executed, ("scripts", "objects"))
        self.assertEqual(outcome.steps.completed, ("scripts", "objects"))
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIs(artifact_kwargs["manifest_outcome"], outcome)
        self.assertIs(artifact_kwargs["attempt_outcome"], outcome)
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
        with self._environment(
            {"scripts": cancel, "objects": objects}
        ) as calls:
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
        self.assertEqual(outcome.steps.executed, ("scripts",))
        self.assertEqual(outcome.steps.completed, ())
        self.assertEqual(outcome.steps.skipped, ("scripts", "objects"))
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(artifact_kwargs["manifest_outcome"])
        self.assertIs(artifact_kwargs["attempt_outcome"], outcome)
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
        with self._environment({"scripts": lambda: step_result}) as calls:
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
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIs(artifact_kwargs["manifest_outcome"], outcome)
        self.assertIs(artifact_kwargs["attempt_outcome"], outcome)

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
        with self._environment({"scripts": runner}) as calls:
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
        self.assertEqual(self.converter.last_outcome.steps.failed, ("scripts",))
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(artifact_kwargs["manifest_outcome"])
        self.assertIs(
            artifact_kwargs["attempt_outcome"],
            self.converter.last_outcome,
        )

    def test_mid_plan_exception_records_completed_failed_and_skipped_step_names(
        self,
    ) -> None:
        error = RuntimeError("objects exploded")
        rooms = MagicMock(return_value=ConversionStepResult())

        with self._environment(
            {
                "scripts": lambda: ConversionStepResult(),
                "objects": MagicMock(side_effect=error),
                "rooms": rooms,
            }
        ) as calls:
            with self.assertRaises(RuntimeError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts", "objects", "rooms"),
                )

        self.assertIs(raised.exception, error)
        assert self.converter.last_outcome is not None
        self.assertEqual(
            self.converter.last_outcome.steps.to_dict(),
            {
                "requested": ["scripts", "objects", "rooms"],
                "executed": ["scripts", "objects"],
                "completed": ["scripts"],
                "skipped": ["rooms"],
                "failed": ["objects"],
            },
        )
        rooms.assert_not_called()
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(artifact_kwargs["manifest_outcome"])
        self.assertIs(
            artifact_kwargs["attempt_outcome"],
            self.converter.last_outcome,
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
        calls["write_artifacts"].assert_called_once()
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(self.converter.last_outcome.failure_phase, "runtime")
        self.assertIsNone(self.converter.last_outcome.failed_step)
        self.assertEqual(
            self.converter.last_outcome.converters,
            ConversionCounts(requested=1, skipped=1),
        )

    def test_runner_build_error_precedes_diagnostic_failure_and_is_attempt_only(
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
        calls["write_artifacts"].assert_called_once()
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(artifact_kwargs["manifest_outcome"])
        self.assertEqual(artifact_kwargs["attempt_outcome"].state, "failed")
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

    def test_failed_second_run_restores_verified_prior_generation(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as gm_dir,
            tempfile.TemporaryDirectory() as godot_dir,
        ):
            project_path = os.path.join(gm_dir, "Named.yyp")
            with open(project_path, "w", encoding="utf-8") as project_file:
                json.dump({"%Name": "First Name"}, project_file)

            first_outcome = self.converter.convert(
                gm_dir,
                "windows",
                godot_dir,
                self._settings("project_name"),
            )
            manifest_path = os.path.join(
                godot_dir,
                "gm2godot",
                "conversion_manifest.json",
            )
            with open(manifest_path, "rb") as manifest_file:
                original_manifest = manifest_file.read()

            with open(project_path, "w", encoding="utf-8") as project_file:
                json.dump({"%Name": "Second Name"}, project_file)

            runtime_error = RuntimeError("notes conversion failed")
            real_build_step_runners = self.converter._build_step_runners

            def build_failing_runners(
                context: ConversionContext,
            ) -> dict[str, Callable[[], object]]:
                runners = real_build_step_runners(context)

                def fail_after_project_name() -> object:
                    raise runtime_error

                runners["notes"] = fail_after_project_name
                return runners

            with patch.object(
                self.converter,
                "_build_step_runners",
                side_effect=build_failing_runners,
            ):
                with self.assertRaises(RuntimeError) as raised:
                    self.converter.convert(
                        gm_dir,
                        "windows",
                        godot_dir,
                        self._settings("project_name", "notes"),
                    )

            self.assertIs(raised.exception, runtime_error)
            self.assertEqual(first_outcome.state, "success")
            with open(manifest_path, "rb") as manifest_file:
                self.assertEqual(manifest_file.read(), original_manifest)
            with open(
                os.path.join(godot_dir, "gm2godot", "conversion_attempt.json"),
                encoding="utf-8",
            ) as attempt_file:
                attempt = json.load(attempt_file)
            with open(
                os.path.join(godot_dir, "project.godot"),
                encoding="utf-8",
            ) as project_file:
                converted_project = project_file.read()

        self.assertIn('config/name="First Name"', converted_project)
        self.assertNotIn('config/name="Second Name"', converted_project)
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(attempt["canonical_manifest"]["status"], "preserved")
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "verified",
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
        finalizer_error.add_note("report rollback also failed")

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
        self.assertEqual(
            getattr(raised.exception, "__notes__", []),
            [
                "Conversion finalizer also failed: report failed",
                "Conversion finalizer failure detail: "
                "report rollback also failed",
            ],
        )
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

    def test_cancelled_checkpoint_restore_failure_is_failed_and_retried(
        self,
    ) -> None:
        restore_error = OSError("transient diagnostic restore failure")

        def cancel_during_report(_path: str, _diagnostics: object) -> None:
            self.running.clear()

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            diagnostic_side_effect=cancel_during_report,
        ) as calls:
            calls["capture"].return_value.files = {
                "gm2godot/conversion_manifest.json": (1, 2, 3, 4, 5),
            }
            calls["restore_diagnostics"].side_effect = [restore_error, None]

            with self.assertRaises(OSError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

            assert self.converter.last_outcome is not None
            self.converter.refresh_conversion_artifacts(
                self.converter.last_outcome,
            )

        self.assertIs(raised.exception, restore_error)
        self.assertEqual(calls["restore_diagnostics"].call_count, 2)
        first_restore = calls["restore_diagnostics"].call_args_list[0].args
        retry_restore = calls["restore_diagnostics"].call_args_list[1].args
        self.assertIs(first_restore[1], retry_restore[1])
        self.assertIs(first_restore[2], retry_restore[2])
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "conversion_diagnostics",
        )
        self.assertEqual(
            self.converter.last_outcome.failure_phase,
            "finalizer",
        )
        self.assertEqual(calls["write_artifacts"].call_count, 1)
        terminal_attempt = calls["write_artifacts"].call_args_list[0].kwargs
        self.assertIsNone(terminal_attempt["manifest_outcome"])
        self.assertEqual(terminal_attempt["attempt_outcome"].state, "failed")

    def test_architecture_checkpoint_restore_failure_revokes_canonical(
        self,
    ) -> None:
        restore_error = OSError("architecture restore failed")
        context = self.converter._create_context(
            "/gm",
            "windows",
            "/godot",
            {},
        )
        cancelled_outcome = ConversionOutcome(state="cancelled")
        self.converter._set_outcome(cancelled_outcome)
        self.converter._canonical_outcome = ConversionOutcome(state="success")
        checkpoint = _FinalizerReportCheckpoint(
            architecture_snapshot=MagicMock(),
            architecture_receipt=MagicMock(),
        )
        errors: list[Exception] = []

        with patch(
            "src.conversion.converter.restore_architecture_policy_snapshot",
            side_effect=restore_error,
        ):
            self.converter._restore_finalizer_reports(
                context,
                checkpoint,
                preserve_outcome=False,
                errors=errors,
            )

        self.assertEqual(errors, [restore_error])
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "architecture_policy",
        )
        self.assertEqual(
            self.converter.last_outcome.failure_phase,
            "finalizer",
        )
        self.assertIsNone(self.converter._canonical_outcome)

    def test_cancelled_architecture_restore_failure_precedes_attempt(self) -> None:
        restore_error = OSError("architecture restore failed")
        events: list[str] = []
        restore_calls = 0

        def cancel_runner() -> ConversionStepResult:
            self.running.clear()
            return ConversionStepResult()

        def restore_architecture(*_args: object) -> None:
            nonlocal restore_calls
            restore_calls += 1
            events.append("architecture_restore")
            if restore_calls == 1:
                raise restore_error

        def write_artifacts(*_args: object, **_kwargs: object) -> tuple[str, str]:
            events.append("artifacts")
            return (
                "/godot/gm2godot/conversion_manifest.json",
                "/godot/gm2godot/conversion_attempt.json",
            )

        with self._environment({"scripts": cancel_runner}) as calls:
            calls["capture"].return_value.files = {
                "gm2godot/conversion_manifest.json": (1, 2, 3, 4, 5),
            }
            calls["restore_architecture"].side_effect = restore_architecture
            calls["write_artifacts"].side_effect = write_artifacts

            with self.assertRaises(OSError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, restore_error)
        self.assertEqual(
            events,
            ["architecture_restore", "artifacts", "architecture_restore"],
        )
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "architecture_policy",
        )
        artifact_kwargs = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(artifact_kwargs["manifest_outcome"])
        self.assertEqual(artifact_kwargs["attempt_outcome"].state, "failed")
        self.assertIsNone(self.converter._canonical_outcome)

    def test_secondary_exception_notes_are_propagated_once(self) -> None:
        primary_error = OSError("primary")
        secondary_error = OSError("secondary")
        secondary_error.add_note("rollback detail")

        for _attempt in range(2):
            self.converter._add_secondary_exception_context(
                primary_error,
                secondary_error,
                summary_prefix="Additional failure: ",
                detail_prefix="Additional detail: ",
            )

        self.assertEqual(
            getattr(primary_error, "__notes__", []),
            [
                "Additional failure: secondary",
                "Additional detail: rollback detail",
            ],
        )

    def test_checkpoint_restore_error_preserves_runtime_outcome(self) -> None:
        restore_error = OSError("diagnostic restore failed")
        context = self.converter._create_context(
            "/gm",
            "windows",
            "/godot",
            {},
        )
        runtime_outcome = ConversionOutcome(
            state="failed",
            failed_step="scripts",
            failure_phase="runtime",
        )
        self.converter._set_outcome(runtime_outcome)
        checkpoint = _FinalizerReportCheckpoint(
            diagnostics_snapshot=MagicMock(),
            diagnostics_receipt=MagicMock(),
        )
        errors: list[Exception] = []

        with patch(
            "src.conversion.converter.restore_conversion_diagnostic_reports",
            side_effect=restore_error,
        ):
            restored = self.converter._restore_diagnostic_checkpoint(
                context,
                checkpoint,
                preserve_outcome=True,
                errors=errors,
            )

        self.assertFalse(restored)
        self.assertEqual(errors, [restore_error])
        self.assertIs(self.converter.last_outcome, runtime_outcome)

    def test_cancellation_during_artifact_publish_keeps_success_canonical(
        self,
    ) -> None:
        report_states: list[str | None] = []

        def record_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)

        manifest_calls = 0

        def cancel_during_manifest(
            *_args: object,
            **_kwargs: object,
        ) -> tuple[str, str]:
            nonlocal manifest_calls
            manifest_calls += 1
            if manifest_calls == 1:
                self.running.clear()
            return (
                "/godot/gm2godot/conversion_manifest.json",
                "/godot/gm2godot/conversion_attempt.json",
            )

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
        self.assertEqual(calls["write_artifacts"].call_count, 2)
        first_kwargs = calls["write_artifacts"].call_args_list[0].kwargs
        second_kwargs = calls["write_artifacts"].call_args_list[1].kwargs
        canonical_outcome = first_kwargs["manifest_outcome"]
        self.assertEqual(canonical_outcome.state, "success")
        self.assertIs(first_kwargs["attempt_outcome"], canonical_outcome)
        self.assertIs(second_kwargs["manifest_outcome"], canonical_outcome)
        self.assertIs(second_kwargs["attempt_outcome"], outcome)
        self.assertEqual(second_kwargs["attempt_outcome"].state, "cancelled")

    def test_artifact_failure_with_failed_diagnostic_rewrite_is_attempt_only(
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
        self.assertEqual(calls["write_artifacts"].call_count, 2)
        self.assertEqual(calls["write_diagnostics"].call_count, 2)
        retry_kwargs = calls["write_artifacts"].call_args_list[1].kwargs
        self.assertIsNone(retry_kwargs["manifest_outcome"])
        self.assertEqual(retry_kwargs["attempt_outcome"].state, "failed")
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "conversion_artifacts",
        )

    def test_artifact_failure_keeps_report_restore_failures_as_notes(self) -> None:
        artifact_error = OSError("manifest failed")
        diagnostic_restore_error = OSError("diagnostic restore failed")
        diagnostic_restore_error.add_note("diagnostic rollback detail")
        architecture_restore_error = OSError("architecture restore failed")

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
            manifest_error=[
                artifact_error,
                (None, "/godot/gm2godot/conversion_attempt.json"),
            ],
        ) as calls:
            calls["capture"].return_value.files = {
                "gm2godot/conversion_manifest.json": (1, 2, 3, 4, 5),
            }
            calls["restore_diagnostics"].side_effect = [
                None,
                diagnostic_restore_error,
            ]
            calls["restore_architecture"].side_effect = architecture_restore_error

            with self.assertRaises(OSError) as raised:
                self.converter.convert(
                    "/gm",
                    "windows",
                    "/godot",
                    self._settings("scripts"),
                )

        self.assertIs(raised.exception, artifact_error)
        self.assertEqual(
            getattr(raised.exception, "__notes__", []),
            [
                "Additional conversion finalizer failure: "
                "diagnostic restore failed",
                "Additional conversion finalizer failure detail: "
                "diagnostic rollback detail",
                "Additional conversion finalizer failure: "
                "architecture restore failed",
            ],
        )
        self.assertEqual(calls["restore_diagnostics"].call_count, 2)
        calls["restore_architecture"].assert_called_once()

    def test_artifact_failure_preserves_pre_existing_manifest(self) -> None:
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
                manifest_error=[
                    manifest_error,
                    (None, "/godot/gm2godot/conversion_attempt.json"),
                ],
            ) as calls:
                with self.assertRaises(OSError) as raised:
                    self.converter.convert(
                        "/gm",
                        "windows",
                        godot_dir,
                        self._settings("scripts"),
                    )

            self.assertIs(raised.exception, manifest_error)
            with open(manifest_path, encoding="utf-8") as manifest_file:
                self.assertEqual(manifest_file.read(), '{"stale": true}\n')

        self.assertEqual(calls["write_artifacts"].call_count, 2)
        pair_kwargs = calls["write_artifacts"].call_args_list[0].kwargs
        retry_kwargs = calls["write_artifacts"].call_args_list[1].kwargs
        self.assertEqual(pair_kwargs["manifest_outcome"].state, "success")
        self.assertIsNone(retry_kwargs["manifest_outcome"])
        self.assertEqual(retry_kwargs["attempt_outcome"].state, "failed")

    def test_diagnostic_failure_preserves_manifest_and_publishes_attempt_only(
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
            with open(manifest_path, encoding="utf-8") as manifest_file:
                self.assertEqual(manifest_file.read(), '{"stale": true}\n')
            calls["write_artifacts"].assert_called_once()
            artifact_kwargs = calls["write_artifacts"].call_args.kwargs
            self.assertIsNone(artifact_kwargs["manifest_outcome"])
            self.assertEqual(artifact_kwargs["attempt_outcome"].state, "failed")

    def test_cancelled_diagnostic_rewrite_failure_preserves_manifest(
        self,
    ) -> None:
        diagnostic_error = OSError("cancelled outcome report failed")
        report_states: list[str | None] = []

        def write_report(_path: str, diagnostics: object) -> None:
            outcome = self.converter.diagnostics.outcome()
            report_states.append(outcome.state if outcome is not None else None)
            if len(report_states) == 2:
                raise diagnostic_error

        def cancel_during_manifest(
            *_args: object,
            **_kwargs: object,
        ) -> tuple[str, str]:
            self.running.clear()
            return (
                "/godot/gm2godot/conversion_manifest.json",
                "/godot/gm2godot/conversion_attempt.json",
            )

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

            with open(manifest_path, encoding="utf-8") as manifest_file:
                self.assertEqual(manifest_file.read(), '{"success": true}\n')

        self.assertIs(raised.exception, diagnostic_error)
        self.assertEqual(report_states, ["success", "cancelled"])
        self.assertEqual(calls["write_artifacts"].call_count, 2)
        self.assertEqual(calls["write_diagnostics"].call_count, 2)
        retry_kwargs = calls["write_artifacts"].call_args_list[1].kwargs
        self.assertIsNone(retry_kwargs["manifest_outcome"])
        self.assertEqual(retry_kwargs["attempt_outcome"].state, "failed")
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
        calls["write_artifacts"].assert_called_once()
        assert self.converter.last_outcome is not None
        self.assertEqual(self.converter.last_outcome.state, "failed")
        self.assertEqual(
            self.converter.last_outcome.failed_step,
            "architecture_policy",
        )

    def test_finalizer_failure_revokes_late_canonical_refresh_candidate(self) -> None:
        architecture_error = OSError("architecture failed")

        with self._environment(
            {"scripts": lambda: ConversionStepResult()},
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
            assert self.converter.last_outcome is not None
            self.converter.refresh_conversion_artifacts(
                self.converter.last_outcome,
            )

        late_refresh = calls["write_artifacts"].call_args.kwargs
        self.assertIsNone(late_refresh["manifest_outcome"])
        self.assertEqual(late_refresh["attempt_outcome"].state, "failed")


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
