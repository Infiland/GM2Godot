"""Report publication and restoration for the existing CLI conversion driver."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.diagnostics import (
    ConversionDiagnosticReportPublicationReceipt,
    ConversionDiagnosticReportSnapshot,
    DiagnosticCollector,
)


@dataclass
class _ManagedDiagnosticCheckpoint:
    destination: str
    snapshot: ConversionDiagnosticReportSnapshot
    receipt: ConversionDiagnosticReportPublicationReceipt | None = None


ManagedDiagnosticCheckpoint = _ManagedDiagnosticCheckpoint


@dataclass
class ConversionReportState:
    external_report_dir: str | None
    canonical_reports_authorized: bool = False
    canonical_refresh_disabled: bool = False
    late_artifact_error: Exception | None = None
    late_report_error: Exception | None = None
    attempt_publication_error: Exception | None = None
    report_restore_error: Exception | None = None
    protect_managed_reports: bool = False
    managed_report_checkpoints: dict[str, ManagedDiagnosticCheckpoint] = field(
        default_factory=dict[str, ManagedDiagnosticCheckpoint]
    )



class ReportValues(Protocol):
    """A live reference to the original args object, never a dataclass snapshot."""

    @property
    def platform(self) -> str: ...

    @property
    def godot_project(self) -> str: ...



class ReportBackend(Protocol):
    """The existing converter object; diagnostics may be reassigned by convert."""

    @property
    def diagnostics(self) -> DiagnosticCollector: ...

    def refresh_conversion_artifacts(self, attempt_outcome: ConversionOutcome) -> tuple[str | None, str]: ...

    def publish_conversion_attempt(self, attempt_outcome: ConversionOutcome) -> str: ...



class ReportOperations(Protocol):
    """Seven explicit live CLI operations; properties return original functions."""

    @property
    def resolved_path_is_within(self) -> Callable[[str, str], bool]: ...

    @property
    def resolved_path_key(self) -> Callable[[str], str]: ...

    @property
    def capture_diagnostic_reports(self) -> Callable[[str], ConversionDiagnosticReportSnapshot]: ...

    @property
    def restore_diagnostic_reports(self) -> Callable[[str, ConversionDiagnosticReportSnapshot, ConversionDiagnosticReportPublicationReceipt], None]: ...

    @property
    def exception_notes(self) -> Callable[[BaseException], tuple[str, ...]]: ...

    @property
    def write_static_reports(self) -> Callable[[str, str | None], None]: ...

    @property
    def write_external_reports(self) -> Callable[[str | None, str, DiagnosticCollector], ConversionDiagnosticReportPublicationReceipt | None]: ...



class ConversionReportLifecycle:
    def __init__(
        self,
        backend: ReportBackend,
        values: ReportValues,
        state: ConversionReportState,
        operations: ReportOperations,
        observe_cancellation: Callable[[ConversionOutcome], ConversionOutcome],
    ) -> None:
        self.backend = backend
        self.values = values
        self.state = state
        self.operations = operations
        self.observe_cancellation = observe_cancellation

    def checkpoint(
        self,
        destination: str,
    ) -> _ManagedDiagnosticCheckpoint | None:
        if (
            not self.state.protect_managed_reports
            or not self.operations.resolved_path_is_within(
                destination,
                self.values.godot_project,
            )
        ):
            return None
        destination_key = self.operations.resolved_path_key(destination)
        checkpoint = self.state.managed_report_checkpoints.get(destination_key)
        if checkpoint is None:
            normalized_destination = os.path.realpath(
                os.path.abspath(destination)
            )
            checkpoint = _ManagedDiagnosticCheckpoint(
                destination=normalized_destination,
                snapshot=self.operations.capture_diagnostic_reports(
                    normalized_destination
                ),
            )
            self.state.managed_report_checkpoints[destination_key] = checkpoint
        return checkpoint

    def reset_publications(self) -> bool:
        restore_errors: list[tuple[str, Exception]] = []
        for checkpoint in reversed(tuple(self.state.managed_report_checkpoints.values())):
            if checkpoint.receipt is None:
                continue
            try:
                self.operations.restore_diagnostic_reports(
                    checkpoint.destination,
                    checkpoint.snapshot,
                    checkpoint.receipt,
                )
            except Exception as error:
                restore_errors.append((checkpoint.destination, error))
            else:
                checkpoint.receipt = None
        if restore_errors:
            restore_error = OSError(
                "managed conversion diagnostics could not be restored: "
                + "; ".join(
                    f"{destination}: {error}"
                    for destination, error in restore_errors
                )
            )
            for destination, error in restore_errors:
                for note in self.operations.exception_notes(error):
                    restore_error.add_note(f"{destination}: {note}")
            self.state.report_restore_error = restore_error
            return False
        self.state.report_restore_error = None
        return True

    def restore_managed_reports(self) -> bool:
        restored = self.reset_publications()
        if restored:
            self.state.managed_report_checkpoints.clear()
        return restored

    def repair(
        self,
        current: ConversionOutcome,
    ) -> ConversionOutcome:
        destinations: list[tuple[str, str]] = []
        seen_destinations: set[str] = set()
        canonical_destination_key = (
            self.operations.resolved_path_key(self.values.godot_project)
            if self.state.canonical_reports_authorized
            else None
        )
        candidate_destinations = (
            self.values.godot_project if self.state.canonical_reports_authorized else None,
            self.state.external_report_dir,
        )
        for destination in candidate_destinations:
            if destination is None:
                continue
            destination_key = self.operations.resolved_path_key(destination)
            if destination_key in seen_destinations:
                continue
            seen_destinations.add(destination_key)
            destinations.append((destination, destination_key))

        while True:
            self.backend.diagnostics.set_outcome(current)
            if not self.reset_publications():
                self.state.canonical_refresh_disabled = True
            canonical_reports_current = False
            report_repair_error: Exception | None = None
            for destination, destination_key in destinations:
                if (
                    self.state.canonical_refresh_disabled
                    and self.state.protect_managed_reports
                    and self.operations.resolved_path_is_within(
                        destination,
                        self.values.godot_project,
                    )
                ):
                    # Once a managed repair or artifact publication fails
                    # while a current manifest is protected, preserve the
                    # exact diagnostic files described by that manifest.
                    # Failed and cancelled attempts have no new canonical
                    # candidate, so their terminal diagnostics must still
                    # be published when no current manifest is protected.
                    continue
                try:
                    checkpoint = self.checkpoint(destination)
                    publication_destination = (
                        checkpoint.destination
                        if checkpoint is not None
                        else destination
                    )
                    receipt = self.backend.diagnostics.publish_reports(
                        publication_destination
                    )
                except Exception as error:
                    # A failed late repair must not delete a previously
                    # trustworthy report or its canonical manifest.
                    if report_repair_error is None:
                        report_repair_error = error
                    continue
                else:
                    if checkpoint is not None:
                        checkpoint.receipt = receipt
                    if destination_key == canonical_destination_key:
                        canonical_reports_current = True

            observed = self.observe_cancellation(current)
            if observed.state != current.state:
                current = observed
                continue

            if (
                report_repair_error is not None
                and current.state in {"success", "partial"}
            ):
                self.state.canonical_refresh_disabled = True
                self.state.late_report_error = report_repair_error
                self.restore_managed_reports()
                current = replace(
                    current,
                    state="failed",
                    failed_step="conversion_diagnostics",
                    failure_phase="finalizer",
                )
                self.backend.diagnostics.set_outcome(current)
                continue

            if canonical_destination_key is not None:
                if canonical_reports_current and not self.state.canonical_refresh_disabled:
                    try:
                        manifest_path, _attempt_path = (
                            self.backend.refresh_conversion_artifacts(current)
                        )
                    except Exception as error:
                        self.state.canonical_refresh_disabled = True
                        self.restore_managed_reports()
                        if current.state in {"success", "partial"}:
                            self.state.late_artifact_error = error
                            current = replace(
                                current,
                                state="failed",
                                failed_step="conversion_artifacts",
                                failure_phase="finalizer",
                            )
                            self.backend.diagnostics.set_outcome(current)
                            continue
                        try:
                            self.backend.publish_conversion_attempt(current)
                        except Exception as error:
                            self.state.attempt_publication_error = error
                        else:
                            self.state.attempt_publication_error = None
                    else:
                        self.state.attempt_publication_error = None
                        if manifest_path is None and self.state.protect_managed_reports:
                            self.restore_managed_reports()
                            self.state.canonical_refresh_disabled = True
                        else:
                            self.state.managed_report_checkpoints.clear()
                            self.state.report_restore_error = None
                            if manifest_path is not None:
                                self.state.protect_managed_reports = True
                else:
                    if self.state.protect_managed_reports and self.state.managed_report_checkpoints:
                        self.restore_managed_reports()
                        self.state.canonical_refresh_disabled = True
                    try:
                        self.backend.publish_conversion_attempt(current)
                    except Exception as error:
                        self.state.attempt_publication_error = error
                    else:
                        self.state.attempt_publication_error = None

            observed = self.observe_cancellation(current)
            if observed.state == current.state:
                return observed
            current = observed

    def publish_external_reports(self) -> None:
        external_checkpoint = (
            self.checkpoint(self.state.external_report_dir)
            if self.state.external_report_dir is not None
            else None
        )
        external_publication_destination = (
            external_checkpoint.destination
            if external_checkpoint is not None
            else self.state.external_report_dir
        )
        external_receipt = self.operations.write_external_reports(
            external_publication_destination,
            self.values.platform,
            self.backend.diagnostics,
        )
        if external_checkpoint is not None and external_receipt is not None:
            external_checkpoint.receipt = external_receipt


def write_staged_cli_reports(
    staged_path: str,
    managed_report_relative: str | None,
    conversion_diagnostics: DiagnosticCollector,
    values: ReportValues,
    operations: ReportOperations,
) -> None:
    if managed_report_relative is None:
        return
    staged_report_root = os.path.normpath(
        os.path.join(staged_path, managed_report_relative)
    )
    operations.write_static_reports(staged_report_root, values.platform)
    if managed_report_relative not in {"", os.curdir}:
        conversion_diagnostics.publish_reports(staged_report_root)
