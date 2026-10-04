"""Included Files transaction state ownership."""

from __future__ import annotations
import hashlib
import os
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, IncludedRecoveryJournal as _IncludedRecoveryJournal, IncludedCommitMarker as _IncludedCommitMarker
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import record_io as _included_records

def _verify_included_commit_marker_generation(
    project_path: str,
    marker: _IncludedCommitMarker,
) -> None:
    root_snapshot = _included_snapshots.capture_included_tree(
        os.path.join(project_path, _included_constants.INCLUDED_FILES_ROOT_NAME),
        expected_parent_identity=marker.project_identity,
    )
    if (
        root_snapshot.identity != marker.root_identity
        or _included_codec.included_tree_snapshot_sha256(
            root_snapshot,
            marker.format_version,
        )
        != marker.root_snapshot_sha256
    ):
        raise OSError("Committed Included Files root generation is unavailable")
    registry_snapshot = _included_snapshots.capture_included_registry(
        project_path,
        expected_project_identity=marker.project_identity,
        allowed_file_identities=frozenset({marker.registry_identity}),
    )
    if (
        registry_snapshot.directory_identity
        != marker.registry_directory_identity
        or registry_snapshot.file_identity != marker.registry_identity
        or registry_snapshot.content is None
        or hashlib.sha256(registry_snapshot.content).hexdigest()
        != marker.registry_content_sha256
    ):
        raise OSError("Committed Included File registry generation is unavailable")


def _verify_included_published_journal(
    project_path: str,
    project_identity: _PathIdentity,
    expected_journal: _IncludedRecoveryJournal,
    expected_identity: _PathIdentity | None,
) -> _PathIdentity:
    journal_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_JOURNAL_NAME)
    record = _included_records.read_included_recovery_record(journal_path, project_identity)
    if record is None:
        raise OSError("Included Files recovery journal disappeared")
    identity, payload = record
    if expected_identity is not None and identity != expected_identity:
        raise OSError("Included Files recovery journal identity changed")
    journal = _included_codec.included_recovery_journal_from_payload(
        project_path,
        project_identity,
        payload,
    )
    if journal != expected_journal:
        raise OSError("Included Files recovery journal changed")
    return identity


def _verify_included_published_commit_marker(
    project_path: str,
    project_identity: _PathIdentity,
    expected_journal: _IncludedRecoveryJournal,
    expected_identity: _PathIdentity | None,
    *,
    verify_generation: bool = True,
) -> _PathIdentity:
    commit_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_COMMIT_NAME)
    record = _included_records.read_included_recovery_record(commit_path, project_identity)
    if record is None:
        raise OSError("Included Files commit marker disappeared")
    identity, payload = record
    if expected_identity is not None and identity != expected_identity:
        raise OSError("Included Files commit marker identity changed")
    marker, embedded_journal = _included_codec.included_commit_marker_and_journal_from_payload(
        project_path,
        payload,
        project_identity,
    )
    if (
        marker != _included_codec.included_commit_marker_from_journal(expected_journal)
        or embedded_journal != expected_journal
    ):
        raise OSError("Included Files commit marker changed")
    if verify_generation:
        verify_included_commit_marker_generation(project_path, marker)
    return identity


verify_included_commit_marker_generation = _verify_included_commit_marker_generation
verify_included_published_journal = _verify_included_published_journal
verify_included_published_commit_marker = _verify_included_published_commit_marker
