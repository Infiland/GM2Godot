"""Included Files generation matching ownership."""

from __future__ import annotations
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.included_files_parts.models import IncludedFileSource as _IncludedFileSource, PathIdentity as _PathIdentity, IncludedGenerationMatch as _IncludedGenerationMatch, IncludedTreeSnapshot as _IncludedTreeSnapshot, IncludedRegistrySnapshot as _IncludedRegistrySnapshot, IncludedOutputSetCancelled as _IncludedOutputSetCancelled
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts.converter_ports import IncludedGenerationMatchingPort

def _before_included_unchanged_source_revalidation() -> None:
    """Narrow test seam before the second stable source-content pass."""


def _before_included_unchanged_public_revalidation() -> None:
    """Narrow test seam before rehashing the candidate public generation."""


def _before_included_unchanged_final_revalidation() -> None:
    """Narrow test seam before final source and public identity checks."""


class IncludedGenerationMatchingOperations(IncludedGenerationMatchingPort):
    def _unchanged_included_generation_matches(
        self: IncludedGenerationMatchingPort,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        expected_registry_content: bytes,
        previous_root_snapshot: _IncludedTreeSnapshot,
        previous_registry_snapshot: _IncludedRegistrySnapshot,
        project_identity: _PathIdentity,
        public_root_path: str,
    ) -> _IncludedGenerationMatch:
        assigned_paths = {
            assignments_by_source[source.relative_path].assigned_output_path
            for source in sources
        }
        if (
            previous_registry_snapshot.directory_identity is None
            or previous_registry_snapshot.file_identity is None
            or previous_registry_snapshot.content != expected_registry_content
            or not _included_metadata.included_tree_matches_planned_paths(
                previous_root_snapshot,
                assigned_paths,
            )
        ):
            return _IncludedGenerationMatch(
                unchanged=False,
                source_receipts=(),
            )

        first_receipts = self._collect_unchanged_source_receipts(
            sources,
            assignments_by_source,
            deny_writes=False,
        )
        assigned_receipts = {
            assignments_by_source[source.relative_path].assigned_output_path:
                first_receipts[source.relative_path]
            for source in sources
        }
        if not _included_metadata.included_tree_matches_source_receipts(
            previous_root_snapshot,
            assigned_receipts,
        ):
            return _IncludedGenerationMatch(
                unchanged=False,
                source_receipts=tuple(
                    first_receipts[source.relative_path]
                    for source in sources
                ),
            )

        before_included_unchanged_source_revalidation()
        second_receipts = self._collect_unchanged_source_receipts(
            sources,
            assignments_by_source,
            deny_writes=True,
        )
        if second_receipts != first_receipts:
            raise OSError(
                "GameMaker Included File sources changed during unchanged-"
                "generation validation"
            )

        before_included_unchanged_public_revalidation()
        _included_snapshots.verify_included_tree_snapshot(
            public_root_path,
            previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _included_snapshots.verify_included_registry_snapshot(
            self.godot_project_path,
            previous_registry_snapshot,
            expected_project_identity=project_identity,
        )

        before_included_unchanged_final_revalidation()
        self._revalidate_unchanged_source_bindings(
            sources,
            first_receipts,
        )
        _included_snapshots.verify_included_tree_snapshot_metadata(
            public_root_path,
            previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _included_snapshots.verify_included_registry_snapshot(
            self.godot_project_path,
            previous_registry_snapshot,
            expected_project_identity=project_identity,
        )
        _included_snapshots.verify_included_project_identity(
            self.godot_project_path,
            project_identity,
        )
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        return _IncludedGenerationMatch(
            unchanged=True,
            source_receipts=tuple(
                first_receipts[source.relative_path]
                for source in sources
            ),
        )

    unchanged_included_generation_matches = _unchanged_included_generation_matches



before_included_unchanged_source_revalidation = _before_included_unchanged_source_revalidation
before_included_unchanged_public_revalidation = _before_included_unchanged_public_revalidation
before_included_unchanged_final_revalidation = _before_included_unchanged_final_revalidation
_unchanged_included_generation_matches = IncludedGenerationMatchingOperations.unchanged_included_generation_matches
unchanged_included_generation_matches = _unchanged_included_generation_matches
