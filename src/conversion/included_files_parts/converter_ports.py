from __future__ import annotations
import os
from typing import BinaryIO
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.project_manifest import GameMakerProjectManifest, ProjectManifestDiagnostic
from src.conversion.project_source_paths import ProjectSourcePathError, ResolvedProjectSourcePath
from src.conversion.type_defs import ConversionRunning, LogCallback, StrPath
from src.conversion.included_files_parts.models import (
    IncludedFileSource as _IncludedFileSource,
    DeclaredIncludedFile as _DeclaredIncludedFile,
    IncludedFileConversionPlan as _IncludedFileConversionPlan,
    PathIdentity as _PathIdentity,
    IncludedCopyReceipt as _IncludedCopyReceipt,
    IncludedSourceBinding as _IncludedSourceBinding,
    IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt,
    IncludedGenerationMatch as _IncludedGenerationMatch,
    IncludedTreeSnapshot as _IncludedTreeSnapshot,
    IncludedRegistrySnapshot as _IncludedRegistrySnapshot,
)
from typing import Protocol
from _thread import LockType


class IncludedCopyWorkerPort(Protocol):
    _active_output_project_path: str | None

    def _capture_pinned_included_source_binding(
        self, source: _IncludedFileSource, source_file: BinaryIO, expected_stat: os.stat_result
    ) -> _IncludedSourceBinding: ...
    def _open_confined_source_file(
        self, filesystem_path: str, *, owner_source_path: str, resource: str, deny_writes: bool = False
    ) -> tuple[BinaryIO, os.stat_result] | None: ...
    def _report_included_file_output_rejection(
        self, relative_path: str, output_path: str, error: BaseException
    ) -> None: ...
    def _resource_failed(self, key: str) -> None: ...
    def _resource_requested(self, key: str) -> None: ...
    def _resource_started(self, key: str) -> None: ...
    @property
    def conversion_running(self) -> ConversionRunning: ...
    @property
    def godot_project_path(self) -> str: ...


class IncludedDiagnosticsPort(Protocol):
    def _diagnostic_source_path(self, owner_source_path: StrPath | None) -> str | None: ...
    @property
    def _lock(self) -> LockType: ...
    def _report_source_path_rejection(
        self,
        rejected_path: str,
        error: ProjectSourcePathError,
        *,
        owner_source_path: StrPath | None,
        resource: str | None,
        resource_type: str | None,
        field: str | None,
    ) -> None: ...
    def _safe_log(self, message: str) -> None: ...
    @property
    def diagnostics(self) -> DiagnosticCollector | None: ...
    @property
    def log_callback(self) -> LogCallback: ...


class IncludedDriverPort(Protocol):
    _active_output_project_path: str | None

    def _included_file_conversion_plan(self) -> _IncludedFileConversionPlan: ...
    def _preflight_included_source_byte_counts(self, sources: tuple[_IncludedFileSource, ...]) -> dict[str, int]: ...
    def _process_file(
        self,
        gm_file_path: str,
        godot_file_path: str,
        rel_path: str,
        owner_source_path: str = "datafiles",
        planned_receipt: _IncludedNoOpSourceReceipt | None = None,
    ) -> tuple[str, bool, _IncludedCopyReceipt | None] | None: ...
    def _report_included_file_output_rejection(
        self, relative_path: str, output_path: str, error: BaseException
    ) -> None: ...
    def _report_included_file_path_collisions(self, assignments: tuple[IncludedFilePathAssignment, ...]) -> None: ...
    def _resource_completed(self, key: str) -> None: ...
    def _resource_failed(self, key: str) -> None: ...
    def _resource_requested(self, key: str) -> None: ...
    def _resource_skipped(self, key: str) -> None: ...
    def _resource_started(self, key: str) -> None: ...
    def _safe_log(self, message: str) -> None: ...
    def _safe_log_progress(self, item_name: str, current: int, total: int) -> None: ...
    def _safe_progress(self, value: int | float) -> None: ...
    def _unchanged_included_generation_matches(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        expected_registry_content: bytes,
        previous_root_snapshot: _IncludedTreeSnapshot,
        previous_registry_snapshot: _IncludedRegistrySnapshot,
        project_identity: _PathIdentity,
        public_root_path: str,
    ) -> _IncludedGenerationMatch: ...
    @property
    def compact_logging(self) -> bool: ...
    @property
    def conversion_running(self) -> ConversionRunning: ...
    @property
    def godot_project_path(self) -> str: ...
    @property
    def log_callback(self) -> LogCallback: ...
    @property
    def max_workers(self) -> int: ...


class IncludedGenerationMatchingPort(Protocol):
    def _collect_unchanged_source_receipts(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        *,
        deny_writes: bool,
    ) -> dict[str, _IncludedNoOpSourceReceipt]: ...
    def _revalidate_unchanged_source_bindings(
        self, sources: tuple[_IncludedFileSource, ...], receipts: dict[str, _IncludedNoOpSourceReceipt]
    ) -> None: ...
    @property
    def conversion_running(self) -> ConversionRunning: ...
    @property
    def godot_project_path(self) -> str: ...


class IncludedPlanningPort(Protocol):
    def _declared_included_files(self, manifest: GameMakerProjectManifest) -> tuple[_DeclaredIncludedFile, ...]: ...
    def _declared_relative_path(
        self, declaration: _DeclaredIncludedFile, resolved: ResolvedProjectSourcePath | None
    ) -> str: ...
    def _discovered_included_files(self) -> tuple[_IncludedFileSource, ...]: ...
    @staticmethod
    def _manifest_diagnostic_is_included_file(diagnostic: ProjectManifestDiagnostic) -> bool: ...
    @staticmethod
    def _normalized_declaration_path(path: str) -> str: ...
    def _plan_manifest_included_files(self, manifest: GameMakerProjectManifest) -> _IncludedFileConversionPlan: ...
    def _record_project_manifest_source_path_diagnostics(
        self,
        manifest: GameMakerProjectManifest,
        *,
        resource_type: str | None = None,
        include_project_sources: bool = False,
    ) -> frozenset[str]: ...
    def _report_source_path_rejection(
        self,
        rejected_path: str,
        error: ProjectSourcePathError,
        *,
        owner_source_path: StrPath | None,
        resource: str | None,
        resource_type: str | None,
        field: str | None,
    ) -> None: ...
    def _report_unavailable_declared_included_file(
        self, declaration: _DeclaredIncludedFile, *, reason: str
    ) -> None: ...
    def _resolve_project_source(
        self,
        source_path: str,
        *,
        owner_source_path: StrPath | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        field: str | None = None,
    ) -> ResolvedProjectSourcePath | None: ...
    @property
    def gm_project_path(self) -> str: ...


class IncludedSourceAccessPort(Protocol):
    def _capture_pinned_included_source_binding(
        self, source: _IncludedFileSource, source_file: BinaryIO, expected_stat: os.stat_result
    ) -> _IncludedSourceBinding: ...
    def _capture_unchanged_source_receipt(
        self, source: _IncludedFileSource, *, deny_writes: bool
    ) -> _IncludedNoOpSourceReceipt: ...
    def _collect_included_files(self, datafiles: ResolvedProjectSourcePath) -> list[_IncludedFileSource]: ...
    def _list_confined_directory(self, directory: ResolvedProjectSourcePath) -> tuple[str, ...] | None: ...
    def _open_confined_source_file(
        self, filesystem_path: str, *, owner_source_path: str, resource: str, deny_writes: bool = False
    ) -> tuple[BinaryIO, os.stat_result] | None: ...
    def _report_directory_swap(self, directory: ResolvedProjectSourcePath) -> None: ...
    def _report_source_path_rejection(
        self,
        rejected_path: str,
        error: ProjectSourcePathError,
        *,
        owner_source_path: StrPath | None,
        resource: str | None,
        resource_type: str | None,
        field: str | None,
    ) -> None: ...
    def _resolve_discovered_project_source(
        self,
        filesystem_path: StrPath,
        *,
        owner_source_path: StrPath | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        field: str | None = None,
    ) -> ResolvedProjectSourcePath | None: ...
    @property
    def conversion_running(self) -> ConversionRunning: ...
    @property
    def gm_project_path(self) -> str: ...
    @property
    def max_workers(self) -> int: ...
