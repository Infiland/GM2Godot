from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from typing import Callable, Mapping, TypeAlias

from src.conversion.base_converter import BaseConverter
from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
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
from src.conversion.project_godot import (
    inspect_godot_project_destination,
    prepare_godot_project_destination,
)
from src.conversion.project_settings import (
    ProjectOperationResult,
    ProjectSettingsConverter,
)
from src.conversion.architecture_policy import (
    ArchitecturePolicyPublicationReceipt,
    ArchitecturePolicySnapshot,
    capture_architecture_policy_snapshot,
    publish_architecture_policy_report,
    restore_architecture_policy_snapshot,
)
from src.conversion.conversion_context import (
    ConversionContext,
    RunningFlag,
    enabled_converter_keys,
    sound_group_folders_enabled,
)
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_EVIDENCE_MAX_BYTES,
    CONVERSION_MANIFEST_RELATIVE_PATH,
    ConversionOutputSnapshot,
    build_verified_preserved_attempt,
    capture_conversion_output_snapshot,
    write_conversion_artifacts,
)
from src.conversion.generation_inventory import (
    GenerationInventory,
    capture_generation_inventory,
    stage_inventory_carry_forward,
    validate_staged_generation_inventory,
)
from src.conversion.managed_output_publisher import (
    MANAGED_OUTPUT_POINTER_NAME,
    publish_managed_output_attempt,
    publish_managed_output_generation,
    recover_managed_output_generation,
)
from src.conversion.managed_output_workspace import (
    DESTINATION_LOCK_NAME,
    WORKSPACE_PARENT_NAME,
    WORKSPACE_STAGE_MARKER_NAME,
    ManagedOutputWorkspace,
)
from src.conversion.conversion_plan import build_conversion_plan
from src.conversion.diagnostics import (
    ConversionDiagnosticReportPublicationReceipt,
    ConversionDiagnosticReportSnapshot,
    DiagnosticCollector,
    capture_conversion_diagnostic_reports,
    publish_conversion_diagnostic_reports,
    restore_conversion_diagnostic_reports,
)
from src.conversion.type_defs import BoolSetting, LogCallback, ProgressCallback

from src.localization import get_localized


CONVERSION_CATEGORIES: dict[str, list[str]] = {
    "assets": ["sprites", "fonts", "sounds", "sound_group_folders", "included_files", "scripts", "objects", "rooms", "asset_registry"],
    "project": ["game_icon", "project_name", "project_settings", "audio_buses", "notes"],
    "wip": ["shaders", "tilesets"],
}


ConverterFn: TypeAlias = Callable[[], object]
StagedOutputFinalizer: TypeAlias = Callable[[str], None]


def _before_conversion_transaction_phase(
    _phase: str,
    _path: str,
) -> None:
    """Narrow cancellation/failure test seam before the durable decision."""


@dataclass
class _FinalizerReportCheckpoint:
    architecture_snapshot: ArchitecturePolicySnapshot | None = None
    architecture_receipt: ArchitecturePolicyPublicationReceipt | None = None
    diagnostics_snapshot: ConversionDiagnosticReportSnapshot | None = None
    diagnostics_receipt: ConversionDiagnosticReportPublicationReceipt | None = None


class Converter:
    managed_output_transactional = True

    def __init__(self, log_callback: LogCallback, progress_callback: ProgressCallback,
                 status_callback: LogCallback, conversion_running: RunningFlag,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 staged_output_finalizer: StagedOutputFinalizer | None = None) -> None:
        self.log_callback: LogCallback = log_callback
        self.progress_callback: ProgressCallback = progress_callback
        self.status_callback: LogCallback = status_callback
        self.conversion_running = conversion_running
        self._raw_log_callback: LogCallback = log_callback
        self._raw_update_log_callback: LogCallback = update_log_callback or log_callback
        self.update_log_callback: LogCallback = self._raw_update_log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers
        self.staged_output_finalizer = staged_output_finalizer
        self.diagnostics = DiagnosticCollector()
        self.last_outcome: ConversionOutcome | None = None
        self._step_exception_resources = ConversionCounts()
        self._conversion_context: ConversionContext | None = None
        self._output_snapshot: ConversionOutputSnapshot | None = None
        self._canonical_outcome: ConversionOutcome | None = None
        self._public_godot_path: str | None = None
        self._active_workspace: ManagedOutputWorkspace | None = None
        self._desired_inventory: GenerationInventory | None = None
        self._committed_inventory: GenerationInventory | None = None
        self._transaction_decided = False

    def convert(self, gm_path: str, gm_platform: str, godot_path: str,
                settings: Mapping[str, BoolSetting], *,
                diagnostics: DiagnosticCollector | None = None) -> ConversionOutcome:
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticCollector()
        self.last_outcome = None
        self._step_exception_resources = ConversionCounts()
        self._conversion_context = None
        self._output_snapshot = None
        self._canonical_outcome = None
        self._public_godot_path = os.path.abspath(godot_path)
        self._active_workspace = None
        self._desired_inventory = None
        self._committed_inventory = None
        self._transaction_decided = False
        enabled_converters = enabled_converter_keys(settings)
        plan = build_conversion_plan(enabled_converters)
        steps = ConversionStepLedger.from_requested(step.key for step in plan)
        public_path = self._public_godot_path
        previous_inventory: GenerationInventory | None = None
        workspace: ManagedOutputWorkspace | None = None
        preflight_error: Exception | None = None
        work_error: Exception | None = None
        cleanup_error: Exception | None = None

        assert public_path is not None
        try:
            recover_managed_output_generation(public_path)
            workspace = ManagedOutputWorkspace.open(public_path)
        except Exception:
            self._set_outcome(
                self._outcome(
                    "failed",
                    steps=steps,
                    failure_phase="recovery",
                )
            )
            raise

        self._active_workspace = workspace
        try:
            try:
                output_snapshot = self._attempt_only_output_snapshot(
                    workspace,
                    public_path,
                )
                if output_snapshot is None:
                    inspect_godot_project_destination(
                        public_path,
                        ignored_transaction_entries=(
                            DESTINATION_LOCK_NAME,
                            WORKSPACE_PARENT_NAME,
                        ),
                    )
                    output_snapshot = capture_conversion_output_snapshot(
                        public_path
                    )
                previous_inventory = (
                    output_snapshot.generation_inventory
                    if output_snapshot.generation_inventory is not None
                    else GenerationInventory()
                )
                stage_inventory_carry_forward(
                    workspace,
                    previous_inventory,
                    enabled_converters=(),
                )
                prepare_godot_project_destination(
                    gm_path,
                    workspace.stage_path,
                    ignored_transaction_entries=(WORKSPACE_STAGE_MARKER_NAME,),
                )
            except Exception as error:
                preflight_error = error
                self._set_outcome(
                    self._outcome(
                        "failed",
                        steps=steps,
                        failure_phase="preflight",
                    )
                )
            else:
                self.log_callback = self.diagnostics.wrap_log_callback(
                    self._raw_log_callback
                )
                self.update_log_callback = self.diagnostics.wrap_log_callback(
                    self._raw_update_log_callback
                )
                context = self._create_context(
                    gm_path,
                    gm_platform,
                    workspace.stage_path,
                    settings,
                    enabled_converters=enabled_converters,
                )
                self._conversion_context = context
                self._output_snapshot = output_snapshot
                resources = ConversionCounts()
                runtime_error: Exception | None = None

                try:
                    runners = self._build_step_runners(context)
                    for step in plan:
                        if not context.is_running():
                            break
                        steps = steps.start(step.key)
                        self._step_exception_resources = ConversionCounts()
                        converter_fn = runners.get(step.key)
                        if converter_fn is None:
                            raise RuntimeError(
                                "No converter runner registered for step "
                                f"{step.key!r}."
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
                        steps = steps.complete(step.key)
                        if not context.is_running():
                            break

                    if steps.active_step is not None or not context.is_running():
                        outcome = self._outcome(
                            "cancelled",
                            steps=steps,
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
                            steps=steps,
                            resources=resources,
                        )
                        self._canonical_outcome = outcome
                    self._set_outcome(outcome)
                except Exception as error:
                    runtime_error = error
                    resources += self._step_exception_resources
                    failed_step = steps.active_step
                    if failed_step is not None:
                        steps = steps.fail(failed_step)
                    self._set_outcome(
                        self._outcome(
                            "failed",
                            steps=steps,
                            resources=resources,
                            failed_step=failed_step,
                            failure_phase="runtime",
                        )
                    )

                finalizer_errors = self._run_finalizers(
                    context,
                    preserve_outcome=runtime_error is not None,
                )
                if runtime_error is not None:
                    for finalizer_error in finalizer_errors:
                        self._add_secondary_exception_context(
                            runtime_error,
                            finalizer_error,
                            summary_prefix="Conversion finalizer also failed: ",
                            detail_prefix="Conversion finalizer failure detail: ",
                        )
                    work_error = runtime_error
                elif finalizer_errors:
                    work_error = finalizer_errors[0]
                    for secondary_error in finalizer_errors[1:]:
                        self._add_secondary_exception_context(
                            work_error,
                            secondary_error,
                            summary_prefix=(
                                "Additional conversion finalizer failure: "
                            ),
                            detail_prefix=(
                                "Additional conversion finalizer failure detail: "
                            ),
                        )

                if work_error is None:
                    work_error = self._validate_and_publish_candidate(
                        workspace,
                        previous_inventory,
                        context,
                    )
        finally:
            self._active_workspace = None
            try:
                workspace.close()
            except Exception as error:
                cleanup_error = error

        if cleanup_error is not None:
            if preflight_error is not None:
                self._add_secondary_exception_context(
                    preflight_error,
                    cleanup_error,
                    summary_prefix="Managed-output cleanup also failed: ",
                    detail_prefix="Managed-output cleanup failure detail: ",
                )
            elif work_error is not None:
                self._add_secondary_exception_context(
                    work_error,
                    cleanup_error,
                    summary_prefix="Managed-output cleanup also failed: ",
                    detail_prefix="Managed-output cleanup failure detail: ",
                )
            else:
                work_error = cleanup_error

        if (
            preflight_error is None
            and previous_inventory is not None
            and not self._transaction_decided
            and not workspace.preserved_for_recovery
            and cleanup_error is None
        ):
            outcome = self.last_outcome
            assert outcome is not None
            try:
                self._publish_verified_attempt(
                    previous_inventory,
                    outcome,
                )
            except Exception as attempt_error:
                if work_error is None:
                    work_error = attempt_error
                else:
                    self._add_secondary_exception_context(
                        work_error,
                        attempt_error,
                        summary_prefix=(
                            "Publishing the verified conversion attempt also "
                            "failed: "
                        ),
                        detail_prefix=(
                            "Verified conversion-attempt publication detail: "
                        ),
                    )

        if preflight_error is not None:
            raise preflight_error
        if work_error is not None:
            raise work_error
        assert self.last_outcome is not None
        return self.last_outcome

    @staticmethod
    def _attempt_only_output_snapshot(
        workspace: ManagedOutputWorkspace,
        public_path: str,
    ) -> ConversionOutputSnapshot | None:
        """Recognize a verified empty generation carrying only its attempt."""

        artifact_directory = os.path.join(public_path, "gm2godot")
        attempt_path = os.path.join(
            public_path,
            CONVERSION_ATTEMPT_RELATIVE_PATH,
        )
        pointer_path = os.path.join(
            public_path,
            WORKSPACE_PARENT_NAME,
            MANAGED_OUTPUT_POINTER_NAME,
        )
        expected_top_level = {
            DESTINATION_LOCK_NAME,
            WORKSPACE_PARENT_NAME,
            "gm2godot",
        }
        try:
            if set(os.listdir(public_path)) != expected_top_level:
                return None
            if set(os.listdir(artifact_directory)) != {
                os.path.basename(CONVERSION_ATTEMPT_RELATIVE_PATH)
            }:
                return None
            artifact_stat = os.lstat(artifact_directory)
            attempt_stat = os.lstat(attempt_path)
            pointer_stat = os.lstat(pointer_path)
        except OSError:
            return None
        is_junction = getattr(os.path, "isjunction", None)
        if (
            stat.S_ISLNK(artifact_stat.st_mode)
            or (
                callable(is_junction)
                and bool(is_junction(artifact_directory))
            )
            or not stat.S_ISDIR(artifact_stat.st_mode)
            or not stat.S_ISREG(attempt_stat.st_mode)
            or attempt_stat.st_nlink != 1
            or not stat.S_ISREG(pointer_stat.st_mode)
            or pointer_stat.st_nlink != 1
        ):
            return None
        workspace.verify()
        snapshot = capture_conversion_output_snapshot(public_path)
        if (
            snapshot.files
            or snapshot.generation_inventory is None
            or snapshot.generation_inventory.entries
        ):
            return None
        workspace.verify()
        return snapshot

    def _validate_and_publish_candidate(
        self,
        workspace: ManagedOutputWorkspace,
        previous_inventory: GenerationInventory,
        context: ConversionContext,
    ) -> Exception | None:
        outcome = self.last_outcome
        if outcome is None:
            return RuntimeError("Conversion produced no terminal outcome.")
        if outcome.state not in {"success", "partial"}:
            self._canonical_outcome = None
            return None
        desired_inventory = self._desired_inventory
        if desired_inventory is None:
            error = RuntimeError(
                "Conversion finalizers produced no frozen managed inventory."
            )
            self._set_transaction_failure(
                "managed_output_validation",
                "validation",
            )
            return error

        try:
            _before_conversion_transaction_phase(
                "before_staged_validation",
                workspace.stage_path,
            )
            if not context.is_running():
                self._set_transaction_cancellation()
                return None
            validate_staged_generation_inventory(workspace, desired_inventory)
            _before_conversion_transaction_phase(
                "after_staged_validation",
                workspace.stage_path,
            )
            if not context.is_running():
                self._set_transaction_cancellation()
                return None
            manifest_content = workspace.read_staged_bytes(
                CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
                maximum=CONVERSION_EVIDENCE_MAX_BYTES,
            )
            attempt_content = workspace.read_staged_bytes(
                CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/"),
                maximum=CONVERSION_EVIDENCE_MAX_BYTES,
            )
            validate_staged_generation_inventory(workspace, desired_inventory)
            _before_conversion_transaction_phase(
                "before_commit_decision",
                workspace.destination_path,
            )
            if not context.is_running():
                self._set_transaction_cancellation()
                return None
        except Exception as error:
            self._set_transaction_failure(
                "managed_output_validation",
                "validation",
            )
            return error

        try:
            publish_managed_output_generation(
                workspace,
                previous_inventory=previous_inventory,
                desired_inventory=desired_inventory,
                canonical_manifest_content=manifest_content,
                attempt_content=attempt_content,
            )
        except Exception as error:
            self._set_transaction_failure(
                "managed_output_publication",
                "publication",
            )
            return error
        self._transaction_decided = True
        self._committed_inventory = desired_inventory
        return None

    def _set_transaction_failure(
        self,
        failed_step: str,
        failure_phase: str,
    ) -> None:
        self._canonical_outcome = None
        previous = self.last_outcome
        outcome = (
            replace(
                previous,
                state="failed",
                failed_step=failed_step,
                failure_phase=failure_phase,
            )
            if previous is not None
            else ConversionOutcome(
                state="failed",
                failed_step=failed_step,
                failure_phase=failure_phase,
            )
        )
        self._set_outcome(outcome)

    def _set_transaction_cancellation(self) -> None:
        self._canonical_outcome = None
        self._set_finalizer_cancellation()

    def _publish_verified_attempt(
        self,
        inventory: GenerationInventory,
        outcome: ConversionOutcome,
    ) -> str:
        public_path = self._public_godot_path
        if public_path is None:
            raise RuntimeError(
                "Cannot publish a conversion attempt before conversion preflight."
            )
        recover_managed_output_generation(public_path)
        with ManagedOutputWorkspace.open(public_path) as workspace:
            publish_managed_output_attempt(
                workspace,
                verified_inventory=inventory,
                attempt_content=lambda manifest_content: (
                    build_verified_preserved_attempt(
                        outcome,
                        manifest_content,
                    )
                ),
            )
        self._set_outcome(outcome)
        return os.path.join(public_path, CONVERSION_ATTEMPT_RELATIVE_PATH)

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

    def refresh_conversion_artifacts(
        self,
        attempt_outcome: ConversionOutcome,
    ) -> tuple[str | None, str]:
        """Publish an attempt and refresh the original trustworthy manifest.

        Conversions that never reached a successful or partial runtime outcome
        have no canonical candidate. In that case this intentionally degrades
        to attempt-only publication instead of creating a failed manifest.
        """
        if self._active_workspace is None:
            attempt_path = self.publish_conversion_attempt(attempt_outcome)
            public_path = self._public_godot_path
            assert public_path is not None
            manifest_path = os.path.join(
                public_path,
                CONVERSION_MANIFEST_RELATIVE_PATH,
            )
            return (
                manifest_path if os.path.isfile(manifest_path) else None,
                attempt_path,
            )
        return self._write_conversion_artifacts(
            manifest_outcome=self._canonical_outcome,
            attempt_outcome=attempt_outcome,
        )

    def publish_conversion_attempt(
        self,
        attempt_outcome: ConversionOutcome,
    ) -> str:
        """Publish terminal attempt state without mutating the canonical manifest."""
        if self._active_workspace is None:
            public_path = self._public_godot_path
            if public_path is None:
                raise RuntimeError(
                    "Cannot publish a conversion attempt before conversion "
                    "preflight."
                )
            recover_managed_output_generation(public_path)
            snapshot = capture_conversion_output_snapshot(public_path)
            inventory = (
                snapshot.generation_inventory
                if snapshot.generation_inventory is not None
                else GenerationInventory()
            )
            return self._publish_verified_attempt(inventory, attempt_outcome)
        _manifest_path, attempt_path = self._write_conversion_artifacts(
            manifest_outcome=None,
            attempt_outcome=attempt_outcome,
        )
        return attempt_path

    def _write_conversion_artifacts(
        self,
        *,
        manifest_outcome: ConversionOutcome | None,
        attempt_outcome: ConversionOutcome,
    ) -> tuple[str | None, str]:
        context = self._conversion_context
        output_snapshot = self._output_snapshot
        if context is None or output_snapshot is None:
            raise RuntimeError(
                "Cannot write conversion artifacts before conversion preflight."
            )
        frozen_inventory: GenerationInventory | None = None
        if manifest_outcome is not None:
            previous_inventory = (
                output_snapshot.generation_inventory
                if output_snapshot.generation_inventory is not None
                else GenerationInventory()
            )
            frozen_inventory = capture_generation_inventory(
                context.godot_project_path,
                previous_inventory=previous_inventory,
                enabled_converters=context.enabled_converters,
            )
            self._desired_inventory = frozen_inventory
        paths = write_conversion_artifacts(
            context.gm_project_path,
            context.godot_project_path,
            target_platform=context.target_platform,
            enabled_converters=context.enabled_converters,
            output_snapshot=output_snapshot,
            generation_inventory=frozen_inventory,
            generation_root_path=context.godot_project_path,
            manifest_outcome=manifest_outcome,
            attempt_outcome=attempt_outcome,
        )
        self._set_outcome(attempt_outcome)
        return paths

    def _run_finalizers(
        self,
        context: ConversionContext,
        *,
        preserve_outcome: bool,
    ) -> list[Exception]:
        errors: list[Exception] = []
        architecture_current = True
        canonical_current = self._canonical_manifest_existed_before_conversion()
        checkpoint = _FinalizerReportCheckpoint()

        if canonical_current:
            try:
                checkpoint.architecture_snapshot = (
                    capture_architecture_policy_snapshot(
                        context.godot_project_path
                    )
                )
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="architecture_policy",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                architecture_current = False

        if architecture_current:
            try:
                checkpoint.architecture_receipt = (
                    publish_architecture_policy_report(
                        context.gm_project_path,
                        context.godot_project_path,
                        target_platform=context.target_platform,
                        enabled_converters=context.enabled_converters,
                    )
                )
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="architecture_policy",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                architecture_current = False

        self._observe_finalizer_cancellation(
            context,
            preserve_outcome=preserve_outcome,
            errors=errors,
        )
        diagnostics_current = True
        if canonical_current:
            try:
                checkpoint.diagnostics_snapshot = (
                    capture_conversion_diagnostic_reports(
                        context.godot_project_path
                    )
                )
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="conversion_diagnostics",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                diagnostics_current = False

        if diagnostics_current:
            checkpoint.diagnostics_receipt = self._write_finalizer_diagnostics(
                context,
                preserve_outcome=preserve_outcome,
                errors=errors,
            )
            diagnostics_current = checkpoint.diagnostics_receipt is not None

        if diagnostics_current and self._observe_finalizer_cancellation(
            context,
            preserve_outcome=preserve_outcome,
            errors=errors,
        ):
            diagnostics_current = self._restore_diagnostic_checkpoint(
                context,
                checkpoint,
                preserve_outcome=preserve_outcome,
                errors=errors,
            )
            if diagnostics_current:
                checkpoint.diagnostics_receipt = (
                    self._write_finalizer_diagnostics(
                        context,
                        preserve_outcome=preserve_outcome,
                        errors=errors,
                    )
                )
                diagnostics_current = checkpoint.diagnostics_receipt is not None

        staged_output_current = True
        if (
            not preserve_outcome
            and architecture_current
            and diagnostics_current
            and not errors
            and self._canonical_outcome is not None
            and self.staged_output_finalizer is not None
        ):
            try:
                self.staged_output_finalizer(context.godot_project_path)
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="staged_output_finalizer",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                staged_output_current = False
            else:
                self._observe_finalizer_cancellation(
                    context,
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )

        include_manifest = (
            not preserve_outcome
            and architecture_current
            and diagnostics_current
            and staged_output_current
            and not errors
            and self._canonical_outcome is not None
        )
        if canonical_current and not include_manifest:
            self._restore_finalizer_reports(
                context,
                checkpoint,
                preserve_outcome=preserve_outcome,
                errors=errors,
            )

        artifacts_published, canonical_committed, diagnostics_receipt = (
            self._publish_finalizer_artifacts(
                context,
                preserve_outcome=preserve_outcome,
                include_manifest=include_manifest,
                checkpoint=checkpoint,
                diagnostics_receipt=checkpoint.diagnostics_receipt,
                errors=errors,
            )
        )
        checkpoint.diagnostics_receipt = diagnostics_receipt
        if canonical_committed:
            canonical_current = True
            checkpoint = _FinalizerReportCheckpoint()
        elif canonical_current and self._checkpoint_has_pending_restore(checkpoint):
            self._restore_finalizer_reports(
                context,
                checkpoint,
                preserve_outcome=preserve_outcome,
                errors=errors,
            )

        if (
            artifacts_published
            and canonical_committed
            and self._observe_finalizer_cancellation(
                context,
                preserve_outcome=preserve_outcome,
                errors=errors,
            )
        ):
            try:
                checkpoint.diagnostics_snapshot = (
                    capture_conversion_diagnostic_reports(
                        context.godot_project_path
                    )
                )
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="conversion_diagnostics",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                diagnostics_current = False
            else:
                checkpoint.diagnostics_receipt = (
                    self._write_finalizer_diagnostics(
                        context,
                        preserve_outcome=preserve_outcome,
                        errors=errors,
                    )
                )
                diagnostics_current = checkpoint.diagnostics_receipt is not None

            _published, canonical_committed, diagnostics_receipt = (
                self._publish_finalizer_artifacts(
                    context,
                    preserve_outcome=preserve_outcome,
                    include_manifest=(
                        diagnostics_current
                        and not errors
                        and self._canonical_outcome is not None
                    ),
                    checkpoint=checkpoint,
                    diagnostics_receipt=checkpoint.diagnostics_receipt,
                    errors=errors,
                )
            )
            checkpoint.diagnostics_receipt = diagnostics_receipt
            if not canonical_committed and canonical_current:
                self._restore_finalizer_reports(
                    context,
                    checkpoint,
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )

        return errors

    def _canonical_manifest_existed_before_conversion(self) -> bool:
        snapshot = self._output_snapshot
        if snapshot is None:
            return False
        manifest_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace("\\", "/")
        return manifest_path in snapshot.files

    def _record_finalizer_error(
        self,
        error: Exception,
        *,
        failed_step: str,
        preserve_outcome: bool,
        errors: list[Exception],
    ) -> None:
        first_error = not errors
        errors.append(error)
        if not preserve_outcome and first_error:
            self._set_finalizer_failure(failed_step)

    def _restore_finalizer_reports(
        self,
        context: ConversionContext,
        checkpoint: _FinalizerReportCheckpoint,
        *,
        preserve_outcome: bool,
        errors: list[Exception],
    ) -> None:
        self._restore_diagnostic_checkpoint(
            context,
            checkpoint,
            preserve_outcome=preserve_outcome,
            errors=errors,
        )
        if (
            checkpoint.architecture_snapshot is not None
            and checkpoint.architecture_receipt is not None
        ):
            try:
                restore_architecture_policy_snapshot(
                    context.godot_project_path,
                    checkpoint.architecture_snapshot,
                    checkpoint.architecture_receipt,
                )
            except Exception as error:
                self._record_finalizer_error(
                    error,
                    failed_step="architecture_policy",
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
            else:
                checkpoint.architecture_receipt = None

    def _restore_diagnostic_checkpoint(
        self,
        context: ConversionContext,
        checkpoint: _FinalizerReportCheckpoint,
        *,
        preserve_outcome: bool,
        errors: list[Exception],
    ) -> bool:
        if (
            checkpoint.diagnostics_snapshot is None
            or checkpoint.diagnostics_receipt is None
        ):
            return True
        try:
            restore_conversion_diagnostic_reports(
                context.godot_project_path,
                checkpoint.diagnostics_snapshot,
                checkpoint.diagnostics_receipt,
            )
        except Exception as error:
            self._record_finalizer_error(
                error,
                failed_step="conversion_diagnostics",
                preserve_outcome=preserve_outcome,
                errors=errors,
            )
            return False
        checkpoint.diagnostics_receipt = None
        return True

    @staticmethod
    def _checkpoint_has_pending_restore(
        checkpoint: _FinalizerReportCheckpoint,
    ) -> bool:
        return (
            checkpoint.diagnostics_snapshot is not None
            and checkpoint.diagnostics_receipt is not None
        ) or (
            checkpoint.architecture_snapshot is not None
            and checkpoint.architecture_receipt is not None
        )

    def _write_finalizer_diagnostics(
        self,
        context: ConversionContext,
        *,
        preserve_outcome: bool,
        errors: list[Exception],
    ) -> ConversionDiagnosticReportPublicationReceipt | None:
        try:
            return publish_conversion_diagnostic_reports(
                context.godot_project_path,
                context.diagnostics,
            )
        except Exception as error:
            self._record_finalizer_error(
                error,
                failed_step="conversion_diagnostics",
                preserve_outcome=preserve_outcome,
                errors=errors,
            )
            return None

    def _publish_finalizer_artifacts(
        self,
        context: ConversionContext,
        *,
        preserve_outcome: bool,
        include_manifest: bool,
        checkpoint: _FinalizerReportCheckpoint,
        diagnostics_receipt: ConversionDiagnosticReportPublicationReceipt | None,
        errors: list[Exception],
    ) -> tuple[
        bool,
        bool,
        ConversionDiagnosticReportPublicationReceipt | None,
    ]:
        outcome = self.last_outcome
        if outcome is None:
            raise RuntimeError("Conversion finalizers require a terminal outcome.")

        try:
            if include_manifest:
                manifest_path, _attempt_path = self.refresh_conversion_artifacts(
                    outcome
                )
                canonical_committed = manifest_path is not None
            else:
                self.publish_conversion_attempt(outcome)
                canonical_committed = False
        except Exception as error:
            first_error = not errors
            errors.append(error)
            if preserve_outcome or not first_error:
                return False, False, diagnostics_receipt

            self._set_finalizer_failure("conversion_artifacts")
            checkpoint.diagnostics_receipt = diagnostics_receipt
            if self._restore_diagnostic_checkpoint(
                context,
                checkpoint,
                preserve_outcome=preserve_outcome,
                errors=errors,
            ):
                rewritten_receipt = self._write_finalizer_diagnostics(
                    context,
                    preserve_outcome=preserve_outcome,
                    errors=errors,
                )
                if rewritten_receipt is not None:
                    diagnostics_receipt = rewritten_receipt
                    checkpoint.diagnostics_receipt = rewritten_receipt
                else:
                    diagnostics_receipt = checkpoint.diagnostics_receipt
            failed_outcome = self.last_outcome
            assert failed_outcome is not None
            try:
                self.publish_conversion_attempt(failed_outcome)
            except Exception as attempt_error:
                errors.append(attempt_error)
            return False, False, diagnostics_receipt
        return True, canonical_committed, diagnostics_receipt

    @staticmethod
    def _add_secondary_exception_context(
        primary_error: Exception,
        secondary_error: Exception,
        *,
        summary_prefix: str,
        detail_prefix: str,
    ) -> None:
        """Attach one secondary failure and its PEP 678 notes without repeats."""
        if primary_error is secondary_error:
            return
        secondary_notes: tuple[str, ...] = tuple(
            getattr(secondary_error, "__notes__", ())
        )
        existing_notes: set[str] = set(
            getattr(primary_error, "__notes__", ())
        )
        propagated_notes = (
            summary_prefix + str(secondary_error),
            *(detail_prefix + note for note in secondary_notes),
        )
        for note in propagated_notes:
            if note in existing_notes:
                continue
            primary_error.add_note(note)
            existing_notes.add(note)

    def _observe_finalizer_cancellation(
        self,
        context: ConversionContext,
        *,
        preserve_outcome: bool,
        errors: list[Exception],
    ) -> bool:
        outcome = self.last_outcome
        if (
            preserve_outcome
            or errors
            or context.is_running()
            or (outcome is not None and outcome.state == "cancelled")
        ):
            return False
        self._set_finalizer_cancellation()
        return True

    def _set_outcome(self, outcome: ConversionOutcome) -> None:
        self.last_outcome = outcome
        self.diagnostics.set_outcome(outcome)

    def _set_finalizer_failure(self, failed_step: str) -> None:
        # A finalizer failure means this invocation never produced a trustworthy
        # canonical replacement. Late CLI repair may still publish its attempt,
        # but it must preserve any canonical manifest from an earlier run.
        self._canonical_outcome = None
        previous = self.last_outcome
        outcome = (
            replace(
                previous,
                state="failed",
                failed_step=failed_step,
                failure_phase="finalizer",
            )
            if previous is not None
            else ConversionOutcome(
                state="failed",
                failed_step=failed_step,
                failure_phase="finalizer",
            )
        )
        self._set_outcome(outcome)

    def _set_finalizer_cancellation(self) -> None:
        previous = self.last_outcome
        outcome = (
            replace(
                previous,
                state="cancelled",
                failed_step=None,
                failure_phase=None,
            )
            if previous is not None
            else ConversionOutcome(state="cancelled")
        )
        self._set_outcome(outcome)

    @staticmethod
    def _outcome(
        state: ConversionTerminalState,
        *,
        steps: ConversionStepLedger,
        resources: ConversionCounts = ConversionCounts(),
        failed_step: str | None = None,
        failure_phase: str | None = None,
    ) -> ConversionOutcome:
        return ConversionOutcome(
            state=state,
            steps=steps,
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
