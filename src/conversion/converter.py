from __future__ import annotations

from typing import Callable, Mapping, TypeAlias

from src.conversion.base_converter import BaseConverter
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepResult,
    ConversionTerminalState,
)
from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.scripts import ScriptConverter
from src.conversion.objects import ObjectConverter
from src.conversion.rooms import RoomConverter
from src.conversion.shaders import ShaderConverter
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.project_godot import prepare_godot_project_destination
from src.conversion.project_settings import (
    ProjectOperationResult,
    ProjectSettingsConverter,
)
from src.conversion.architecture_policy import write_architecture_policy_report
from src.conversion.conversion_context import (
    ConversionContext,
    RunningFlag,
    enabled_converter_keys,
    sound_group_folders_enabled,
)
from src.conversion.conversion_manifest import (
    ConversionOutputSnapshot,
    capture_conversion_output_snapshot,
    invalidate_conversion_manifest,
    write_conversion_manifest,
)
from src.conversion.conversion_plan import build_conversion_plan
from src.conversion.diagnostics import (
    DiagnosticCollector,
    invalidate_conversion_diagnostic_reports,
    write_conversion_diagnostic_reports,
)
from src.conversion.type_defs import BoolSetting, LogCallback, ProgressCallback

from src.localization import get_localized


CONVERSION_CATEGORIES: dict[str, list[str]] = {
    "assets": ["sprites", "fonts", "sounds", "sound_group_folders", "included_files", "scripts", "objects", "rooms", "asset_registry"],
    "project": ["game_icon", "project_name", "project_settings", "audio_buses", "notes"],
    "wip": ["shaders", "tilesets"],
}


ConverterFn: TypeAlias = Callable[[], object]


class Converter:
    def __init__(self, log_callback: LogCallback, progress_callback: ProgressCallback,
                 status_callback: LogCallback, conversion_running: RunningFlag,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        self.log_callback: LogCallback = log_callback
        self.progress_callback: ProgressCallback = progress_callback
        self.status_callback: LogCallback = status_callback
        self.conversion_running = conversion_running
        self._raw_log_callback: LogCallback = log_callback
        self._raw_update_log_callback: LogCallback = update_log_callback or log_callback
        self.update_log_callback: LogCallback = self._raw_update_log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers
        self.diagnostics = DiagnosticCollector()
        self.last_outcome: ConversionOutcome | None = None
        self._step_exception_resources = ConversionCounts()
        self._conversion_context: ConversionContext | None = None
        self._output_snapshot: ConversionOutputSnapshot | None = None

    def convert(self, gm_path: str, gm_platform: str, godot_path: str,
                settings: Mapping[str, BoolSetting], *,
                diagnostics: DiagnosticCollector | None = None) -> ConversionOutcome:
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticCollector()
        self.last_outcome = None
        self._step_exception_resources = ConversionCounts()
        self._conversion_context = None
        self._output_snapshot = None
        enabled_converters = enabled_converter_keys(settings)
        plan = build_conversion_plan(enabled_converters)
        requested_converters = len(plan)

        try:
            output_snapshot = capture_conversion_output_snapshot(godot_path)
            prepare_godot_project_destination(gm_path, godot_path)
        except Exception:
            self._set_outcome(
                self._outcome(
                    "failed",
                    requested=requested_converters,
                    executed=0,
                    completed=0,
                    failed=0,
                    failure_phase="preflight",
                )
            )
            raise

        self.log_callback = self.diagnostics.wrap_log_callback(self._raw_log_callback)
        self.update_log_callback = self.diagnostics.wrap_log_callback(self._raw_update_log_callback)
        context = self._create_context(
            gm_path,
            gm_platform,
            godot_path,
            settings,
            enabled_converters=enabled_converters,
        )
        self._conversion_context = context
        self._output_snapshot = output_snapshot
        executed_converters = 0
        completed_converters = 0
        resources = ConversionCounts()
        current_step: str | None = None
        runtime_error: Exception | None = None

        try:
            runners = self._build_step_runners(context)
            for step in plan:
                if not context.is_running():
                    break
                current_step = step.key
                executed_converters += 1
                self._step_exception_resources = ConversionCounts()
                converter_fn = runners.get(step.key)
                if converter_fn is None:
                    raise RuntimeError(
                        f"No converter runner registered for step {step.key!r}."
                    )
                log_message = get_localized(step.log_key)
                context.log_callback(log_message)
                context.status_callback(log_message)
                raw_result = converter_fn()
                step_result = (
                    raw_result
                    if isinstance(raw_result, ConversionStepResult)
                    else ConversionStepResult()
                )
                resources += step_result.resources
                context.progress_callback(0)
                if step_result.cancelled:
                    break
                completed_converters += 1
                current_step = None
                if not context.is_running():
                    break

            if current_step is not None or not context.is_running():
                outcome = self._outcome(
                    "cancelled",
                    requested=requested_converters,
                    executed=executed_converters,
                    completed=completed_converters,
                    failed=0,
                    resources=resources,
                )
            else:
                state = (
                    "partial"
                    if resources.skipped > 0 or resources.failed > 0
                    else "success"
                )
                outcome = self._outcome(
                    state,
                    requested=requested_converters,
                    executed=executed_converters,
                    completed=completed_converters,
                    failed=0,
                    resources=resources,
                )
            self._set_outcome(outcome)
        except Exception as error:
            runtime_error = error
            resources += self._step_exception_resources
            failed_converters = 1 if current_step is not None else 0
            self._set_outcome(
                self._outcome(
                    "failed",
                    requested=requested_converters,
                    executed=executed_converters,
                    completed=completed_converters,
                    failed=failed_converters,
                    resources=resources,
                    failed_step=current_step,
                    failure_phase="runtime",
                )
            )

        finalizer_errors = self._run_finalizers(
            context,
            preserve_outcome=runtime_error is not None,
        )
        if runtime_error is not None:
            raise runtime_error
        if finalizer_errors:
            raise finalizer_errors[0]

        assert self.last_outcome is not None
        return self.last_outcome

    def _run_base_converter(self, converter: BaseConverter) -> ConversionStepResult:
        try:
            converter.convert_all()
        except Exception:
            try:
                self._step_exception_resources = converter.conversion_step_result(
                    cancelled=False,
                    finalize_unfinished_as="failed",
                ).resources
            except Exception:
                self._step_exception_resources = ConversionCounts()
            raise
        return converter.conversion_step_result()

    def _run_project_setting(
        self,
        operation: Callable[[], bool | ProjectOperationResult],
        is_running: Callable[[], bool],
    ) -> ConversionStepResult:
        """Account for one logical project-setting resource."""
        if not is_running():
            return ConversionStepResult(
                resources=ConversionCounts(requested=1, skipped=1),
                cancelled=True,
            )

        try:
            operation_result = operation()
        except Exception:
            self._step_exception_resources = ConversionCounts(
                requested=1,
                executed=1,
                failed=1,
            )
            raise

        state = (
            operation_result.state
            if isinstance(operation_result, ProjectOperationResult)
            else "completed" if operation_result else "skipped"
        )
        resources = ConversionCounts(
            requested=1,
            executed=1,
            completed=1 if state == "completed" else 0,
            skipped=1 if state == "skipped" else 0,
            failed=1 if state == "failed" else 0,
        )
        return ConversionStepResult(
            resources=resources,
            cancelled=not is_running(),
        )

    def refresh_conversion_manifest(self) -> str:
        """Rewrite the manifest after a late canonical report update."""
        context = self._conversion_context
        output_snapshot = self._output_snapshot
        if context is None or output_snapshot is None:
            raise RuntimeError(
                "Cannot write a conversion manifest before conversion preflight."
            )
        try:
            return write_conversion_manifest(
                context.gm_project_path,
                context.godot_project_path,
                target_platform=context.target_platform,
                enabled_converters=context.enabled_converters,
                output_snapshot=output_snapshot,
            )
        except Exception as error:
            try:
                invalidate_conversion_manifest(context.godot_project_path)
            except OSError as invalidation_error:
                error.add_note(
                    "The stale conversion manifest could not be invalidated: "
                    f"{invalidation_error}"
                )
            raise

    def invalidate_conversion_manifest(self) -> None:
        context = self._conversion_context
        if context is None:
            return
        invalidate_conversion_manifest(context.godot_project_path)

    def _invalidate_manifest_after_diagnostic_failure(
        self,
        report_error: Exception,
    ) -> None:
        try:
            self.invalidate_conversion_manifest()
        except OSError as invalidation_error:
            report_error.add_note(
                "The stale conversion manifest could not be invalidated: "
                f"{invalidation_error}"
            )

    def _run_finalizers(
        self,
        context: ConversionContext,
        *,
        preserve_outcome: bool,
    ) -> list[Exception]:
        errors: list[Exception] = []
        diagnostics_current = False

        try:
            write_architecture_policy_report(
                context.gm_project_path,
                context.godot_project_path,
                target_platform=context.target_platform,
                enabled_converters=context.enabled_converters,
            )
        except Exception as error:
            first_error = not errors
            errors.append(error)
            if not preserve_outcome and first_error:
                self._set_finalizer_failure("architecture_policy")

        if not preserve_outcome and not errors and not context.is_running():
            self._set_finalizer_cancellation()

        try:
            write_conversion_diagnostic_reports(
                context.godot_project_path,
                context.diagnostics,
            )
            diagnostics_current = True
        except Exception as error:
            first_error = not errors
            errors.append(error)
            if not preserve_outcome and first_error:
                self._set_finalizer_failure("conversion_diagnostics")
            invalidate_conversion_diagnostic_reports(context.godot_project_path)
            self._invalidate_manifest_after_diagnostic_failure(error)
        else:
            outcome = self.last_outcome
            cancellation_observed_during_write = (
                not preserve_outcome
                and not errors
                and not context.is_running()
                and (outcome is None or outcome.state != "cancelled")
            )
            if cancellation_observed_during_write:
                self._set_finalizer_cancellation()
                diagnostics_current = False
                try:
                    write_conversion_diagnostic_reports(
                        context.godot_project_path,
                        context.diagnostics,
                    )
                except Exception as error:
                    errors.append(error)
                    self._set_finalizer_failure("conversion_diagnostics")
                    invalidate_conversion_diagnostic_reports(
                        context.godot_project_path
                    )
                    self._invalidate_manifest_after_diagnostic_failure(error)
                else:
                    diagnostics_current = True

        if diagnostics_current:
            try:
                self.refresh_conversion_manifest()
            except Exception as error:
                first_error = not errors
                errors.append(error)
                if not preserve_outcome and first_error:
                    self._set_finalizer_failure("conversion_manifest")
                    diagnostics_current = False
                    try:
                        write_conversion_diagnostic_reports(
                            context.godot_project_path,
                            context.diagnostics,
                        )
                    except Exception as report_error:
                        errors.append(report_error)
                        invalidate_conversion_diagnostic_reports(
                            context.godot_project_path
                        )
                        self._invalidate_manifest_after_diagnostic_failure(
                            report_error
                        )
                    else:
                        diagnostics_current = True
            else:
                outcome = self.last_outcome
                cancellation_observed_during_manifest = (
                    not preserve_outcome
                    and not errors
                    and not context.is_running()
                    and (outcome is None or outcome.state != "cancelled")
                )
                if cancellation_observed_during_manifest:
                    self._set_finalizer_cancellation()
                    diagnostics_current = False
                    try:
                        write_conversion_diagnostic_reports(
                            context.godot_project_path,
                            context.diagnostics,
                        )
                    except Exception as error:
                        errors.append(error)
                        self._set_finalizer_failure("conversion_diagnostics")
                        invalidate_conversion_diagnostic_reports(
                            context.godot_project_path
                        )
                        self._invalidate_manifest_after_diagnostic_failure(
                            error
                        )
                    else:
                        diagnostics_current = True
                        try:
                            self.refresh_conversion_manifest()
                        except Exception as error:
                            errors.append(error)
                            self._set_finalizer_failure("conversion_manifest")
                            diagnostics_current = False
                            try:
                                write_conversion_diagnostic_reports(
                                    context.godot_project_path,
                                    context.diagnostics,
                                )
                            except Exception as report_error:
                                errors.append(report_error)
                                invalidate_conversion_diagnostic_reports(
                                    context.godot_project_path
                                )
                                self._invalidate_manifest_after_diagnostic_failure(
                                    report_error
                                )
                            else:
                                diagnostics_current = True

        return errors

    def _set_outcome(self, outcome: ConversionOutcome) -> None:
        self.last_outcome = outcome
        self.diagnostics.set_outcome(outcome)

    def _set_finalizer_failure(self, failed_step: str) -> None:
        previous = self.last_outcome
        self._set_outcome(
            ConversionOutcome(
                state="failed",
                converters=(
                    previous.converters
                    if previous is not None
                    else ConversionCounts()
                ),
                resources=(
                    previous.resources
                    if previous is not None
                    else ConversionCounts()
                ),
                failed_step=failed_step,
                failure_phase="finalizer",
            )
        )

    def _set_finalizer_cancellation(self) -> None:
        previous = self.last_outcome
        self._set_outcome(
            ConversionOutcome(
                state="cancelled",
                converters=(
                    previous.converters
                    if previous is not None
                    else ConversionCounts()
                ),
                resources=(
                    previous.resources
                    if previous is not None
                    else ConversionCounts()
                ),
            )
        )

    @staticmethod
    def _outcome(
        state: ConversionTerminalState,
        *,
        requested: int,
        executed: int,
        completed: int,
        failed: int,
        resources: ConversionCounts = ConversionCounts(),
        failed_step: str | None = None,
        failure_phase: str | None = None,
    ) -> ConversionOutcome:
        return ConversionOutcome(
            state=state,
            converters=ConversionCounts(
                requested=requested,
                executed=executed,
                completed=completed,
                skipped=requested - completed - failed,
                failed=failed,
            ),
            resources=resources,
            failed_step=failed_step,
            failure_phase=failure_phase,
        )

    def _create_context(
        self,
        gm_path: str,
        gm_platform: str,
        godot_path: str,
        settings: Mapping[str, BoolSetting],
        *,
        enabled_converters: tuple[str, ...] | None = None,
    ) -> ConversionContext:
        return ConversionContext(
            gm_project_path=gm_path,
            godot_project_path=godot_path,
            target_platform=gm_platform,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            status_callback=self.status_callback,
            conversion_running=self.conversion_running.is_set,
            update_log_callback=self.update_log_callback,
            compact_logging=self.compact_logging,
            max_workers=self.max_workers,
            diagnostics=self.diagnostics,
            enabled_converters=(
                enabled_converters
                if enabled_converters is not None
                else enabled_converter_keys(settings)
            ),
            group_sounds_by_audio_group=sound_group_folders_enabled(settings),
        )

    def _build_step_runners(self, context: ConversionContext) -> dict[str, ConverterFn]:
        project_settings = ProjectSettingsConverter(
            context.gm_project_path,
            context.godot_project_path,
            context.log_callback,
            context.progress_callback,
            context.is_running,
            gm_platform=context.target_platform,
            max_workers=context.max_workers,
            diagnostics=context.diagnostics,
        )

        return {
            "game_icon": lambda: self._run_project_setting(
                project_settings.convert_icon,
                context.is_running,
            ),
            "project_name": lambda: self._run_project_setting(
                project_settings.update_project_name,
                context.is_running,
            ),
            "project_settings": lambda: self._run_project_setting(
                project_settings.update_project_settings,
                context.is_running,
            ),
            "audio_buses": lambda: self._run_project_setting(
                project_settings.generate_audio_bus_layout,
                context.is_running,
            ),
            "sprites": lambda: self._run_base_converter(
                SpriteConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "fonts": lambda: self._run_base_converter(
                FontConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "tilesets": lambda: self._run_base_converter(
                TileSetConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "sounds": lambda: self._run_base_converter(
                SoundConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    organize_by_audio_group=context.group_sounds_by_audio_group,
                    diagnostics=context.diagnostics,
                )
            ),
            "notes": lambda: self._run_base_converter(
                NoteConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "shaders": lambda: self._run_base_converter(
                ShaderConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "included_files": lambda: self._run_base_converter(
                IncludedFilesConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "scripts": lambda: self._run_base_converter(
                ScriptConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                    macro_configuration=context.target_platform,
                )
            ),
            "objects": lambda: self._run_base_converter(
                ObjectConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                    macro_configuration=context.target_platform,
                )
            ),
            "rooms": lambda: self._run_base_converter(
                RoomConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    diagnostics=context.diagnostics,
                )
            ),
            "asset_registry": lambda: self._run_base_converter(
                AssetRegistryConverter(
                    context.gm_project_path,
                    context.godot_project_path,
                    context.log_callback,
                    context.progress_callback,
                    context.is_running,
                    update_log_callback=context.update_log_callback,
                    compact_logging=context.compact_logging,
                    max_workers=context.max_workers,
                    organize_sounds_by_audio_group=context.group_sounds_by_audio_group,
                    macro_configuration=context.target_platform,
                    diagnostics=context.diagnostics,
                )
            ),
        }
