"""Included Files diagnostics ownership."""

from __future__ import annotations
import posixpath
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.project_source_paths import ProjectSourcePathError, ResolvedProjectSourcePath
from src.conversion.included_files_parts.models import DeclaredIncludedFile as _DeclaredIncludedFile
from src.conversion.included_files_parts.converter_ports import IncludedDiagnosticsPort

class IncludedDiagnosticsOperations(IncludedDiagnosticsPort):
    def _report_included_file_output_rejection(
        self: IncludedDiagnosticsPort,
        relative_path: str,
        output_path: str,
        error: BaseException,
    ) -> None:
        message = (
            "Error: Refusing to publish GameMaker Included File "
            f"{relative_path!r} to {output_path!r}: {error}"
        )
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "error",
                    "GM2GD-INCLUDED-FILE-OUTPUT-REJECTED",
                    message,
                    source_path="datafiles/" + relative_path,
                    resource=relative_path,
                    resource_type="included_file",
                    manifest_entry="generated Included File output",
                    workaround=(
                        "Remove redirected or non-regular entries from the "
                        "Godot included_files output tree and retry conversion."
                    ),
                )
            self.log_callback(message)

    def _report_directory_swap(
        self: IncludedDiagnosticsPort,
        directory: ResolvedProjectSourcePath,
    ) -> None:
        self._report_source_path_rejection(
            directory.filesystem_path,
            ProjectSourcePathError(
                "Discovered GameMaker source directory changed after validation"
            ),
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )

    def _report_unavailable_declared_included_file(
        self: IncludedDiagnosticsPort,
        declaration: _DeclaredIncludedFile,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker included file "
            f"{declaration.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    declaration.owner_source_path
                ),
                resource=declaration.name,
                resource_type="included_file",
                manifest_entry=declaration.manifest_field,
                workaround=(
                    "Restore the declared included file under the GameMaker "
                    "datafiles directory or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _report_included_file_path_collisions(
        self: IncludedDiagnosticsPort,
        assignments: tuple[IncludedFilePathAssignment, ...],
    ) -> None:
        reported_paths: set[str] = set()
        assignments_by_source = {
            assignment.original_logical_path: assignment.assigned_output_path
            for assignment in assignments
        }
        for assignment in assignments:
            canonical_path = assignment.canonical_lookup_path
            if not assignment.has_collision or canonical_path in reported_paths:
                continue
            reported_paths.add(canonical_path)
            rendered_assignments = ", ".join(
                f"{source_path!r} -> {assignments_by_source[source_path]!r}"
                for source_path in assignment.collision_group
            )
            message = (
                "Warning: GameMaker Included File paths conflict after "
                f"packaged-name normalization at {canonical_path!r}; "
                "deterministic output paths were assigned: "
                f"{rendered_assignments}."
            )
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "warning",
                    "GM2GD-INCLUDED-FILE-PATH-COLLISION",
                    message,
                    source_path="datafiles",
                    resource=canonical_path,
                    resource_type="included_file",
                    manifest_entry="normalized Included File output path",
                    workaround=(
                        "Rename the conflicting Included Files so their "
                        "lowercase, space-to-underscore packaged paths do not "
                        "collide as files or directories."
                    ),
                )
            self._safe_log(message)

    report_included_file_output_rejection = _report_included_file_output_rejection
    report_directory_swap = _report_directory_swap
    report_unavailable_declared_included_file = _report_unavailable_declared_included_file
    report_included_file_path_collisions = _report_included_file_path_collisions









_report_included_file_output_rejection = IncludedDiagnosticsOperations.report_included_file_output_rejection
report_included_file_output_rejection = _report_included_file_output_rejection
_report_directory_swap = IncludedDiagnosticsOperations.report_directory_swap
report_directory_swap = _report_directory_swap
_report_unavailable_declared_included_file = IncludedDiagnosticsOperations.report_unavailable_declared_included_file
report_unavailable_declared_included_file = _report_unavailable_declared_included_file
_report_included_file_path_collisions = IncludedDiagnosticsOperations.report_included_file_path_collisions
report_included_file_path_collisions = _report_included_file_path_collisions
