"""Included Files recovery ownership."""

from __future__ import annotations
import hashlib
import os
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, IncludedRegistrySnapshot as _IncludedRegistrySnapshot
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import record_io as _included_records
from src.conversion.included_files_parts import recorded_cleanup as _included_cleanup
from src.conversion.included_files_parts import phase_observer as _included_phases
from src.conversion.included_files_parts import record_lifecycle as _included_record_lifecycle
from src.conversion.included_files_parts import transaction_cleanup as _included_transaction_cleanup
from src.conversion.included_files_parts import transaction_state as _included_transaction_state

def _cleanup_orphan_included_recovery_state(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[int, tuple[str, ...]]:
    """Remove exact self-identifying orphans and preserve ambiguous state."""

    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    names = sorted(os.listdir(project_path))
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    cleaned = 0
    warnings: list[str] = []
    for name in names:
        if name.startswith(_included_constants.INCLUDED_FILES_STAGE_PREFIX) and name.endswith(
            ".stage"
        ):
            stage_path = os.path.join(project_path, name)
            try:
                _included_paths.included_recovery_managed_name(
                    name,
                    prefix=_included_constants.INCLUDED_FILES_STAGE_PREFIX,
                    suffix=".stage",
                    label="orphan stage",
                )
                stage_identity = _included_snapshots.included_directory_identity(stage_path)
            except OSError:
                warnings.append(
                    "ambiguous entry at a reserved Included Files staging path "
                    f"was preserved: {stage_path}"
                )
                continue
            if stage_identity is None:
                continue
            marker_path = os.path.join(
                stage_path,
                _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
            )
            try:
                marker_record = _included_records.read_included_recovery_record(
                    marker_path,
                    stage_identity,
                )
                stage_names = sorted(os.listdir(stage_path))
                if _included_snapshots.included_directory_identity(stage_path) != stage_identity:
                    raise OSError("Included Files orphan stage changed")
                marker_matches = (
                    marker_record is not None
                    and _included_codec.included_stage_marker_matches(
                        marker_record[1],
                        project_identity,
                        stage_identity,
                    )
                )
            except OSError:
                marker_record = None
                marker_matches = False
                stage_names = []
            if (
                not marker_matches
                or marker_record is None
                or stage_names != [_included_constants.INCLUDED_FILES_STAGE_MARKER_NAME]
            ):
                warnings.append(
                    "ambiguous Included Files staging directory was preserved: "
                    + stage_path
                )
                continue
            orphan_snapshot = _included_snapshots.capture_included_tree(
                stage_path,
                expected_parent_identity=project_identity,
            )
            orphan_warnings = _included_cleanup.cleanup_recorded_included_tree(
                stage_path,
                orphan_snapshot,
                project_identity,
                hashlib.sha256(
                    _included_codec.included_recovery_record_content(marker_record[1])
                ).hexdigest()[:32],
                "orphan-stage",
            )
            if orphan_warnings:
                warnings.extend(orphan_warnings)
            else:
                cleaned += 1

    names = sorted(os.listdir(project_path))
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    for name in names:
        record_kind: str | None = None
        if name.startswith(_included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX) and name.endswith(
            ".tmp"
        ):
            record_kind = "journal"
        elif name.startswith(_included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX) and name.endswith(
            ".tmp"
        ):
            record_kind = "commit"
        if record_kind is None:
            continue
        record_path = os.path.join(project_path, name)
        try:
            _included_paths.included_recovery_managed_name(
                name,
                prefix=(
                    _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    if record_kind == "journal"
                    else _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                ),
                suffix=".tmp",
                label=record_kind + " temporary record",
            )
            record = _included_records.read_included_recovery_record(
                record_path,
                project_identity,
            )
        except OSError:
            warnings.append(
                "ambiguous Included Files recovery temporary record was "
                f"preserved: {record_path}"
            )
            continue
        if record is None:
            continue
        record_identity, payload = record
        try:
            if record_kind == "journal":
                _included_codec.included_recovery_journal_from_payload(
                    project_path,
                    project_identity,
                    payload,
                )
            else:
                _included_codec.included_commit_marker_and_journal_from_payload(
                    project_path,
                    payload,
                    project_identity,
                )
        except OSError:
            warnings.append(
                "ambiguous Included Files recovery temporary record was "
                f"preserved: {record_path}"
            )
            continue
        if record_kind == "journal":
            warnings.append(
                "unpromoted Included Files journal temporary was preserved: "
                + record_path
            )
            continue
        _included_record_lifecycle.remove_included_recovery_record(
            record_path,
            record_identity,
            project_path,
            project_identity,
        )
        cleaned += 1

    names = sorted(os.listdir(project_path))
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    for name in names:
        if not (
            name.startswith(_included_constants.INCLUDED_FILES_CLEANUP_PREFIX)
            and name.endswith(".file")
        ):
            continue
        record_path = os.path.join(project_path, name)
        try:
            record = _included_records.read_included_recovery_record(
                record_path,
                project_identity,
            )
            if record is None:
                continue
            record_identity, payload = record
            content_sha256 = hashlib.sha256(
                _included_codec.included_recovery_record_content(payload)
            ).hexdigest()
            state = payload.get("state")
            if state == "prepared":
                _included_codec.included_recovery_journal_from_payload(
                    project_path,
                    project_identity,
                    payload,
                )
                role = "journal-temporary-record"
                relative_path = "journal"
            elif state == "committed":
                _included_codec.included_commit_marker_and_journal_from_payload(
                    project_path,
                    payload,
                    project_identity,
                )
                role = "commit-temporary-record"
                relative_path = "commit"
            else:
                raise OSError("Unknown Included Files recovery tombstone state")
            expected_path = _included_paths.included_cleanup_tombstone_path(
                os.path.join(project_path, "temporary-record"),
                content_sha256[:32],
                role,
                relative_path,
                expect_directory=False,
            )
            if os.path.normcase(record_path) != os.path.normcase(expected_path):
                raise OSError("Included Files recovery tombstone name mismatch")
        except OSError:
            warnings.append(
                "ambiguous Included Files cleanup tombstone was preserved: "
                + record_path
            )
            continue
        _included_record_lifecycle.remove_included_recovery_record(
            record_path,
            record_identity,
            project_path,
            project_identity,
        )
        cleaned += 1
    return cleaned, tuple(warnings)


def _promote_included_journal_temporary(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[bool, tuple[str, ...]]:
    journal_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_JOURNAL_NAME)
    if os.path.lexists(journal_path):
        return False, ()
    candidates: list[tuple[str, _PathIdentity]] = []
    warnings: list[str] = []
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    for name in sorted(os.listdir(project_path)):
        if not (
            name.startswith(_included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX)
            and name.endswith(".tmp")
        ):
            continue
        candidate_path = os.path.join(project_path, name)
        try:
            _included_paths.included_recovery_managed_name(
                name,
                prefix=_included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
                suffix=".tmp",
                label="journal temporary record",
            )
            record = _included_records.read_included_recovery_record(
                candidate_path,
                project_identity,
            )
            if record is None:
                continue
            candidate_identity, payload = record
            journal = _included_codec.included_recovery_journal_from_payload(
                project_path,
                project_identity,
                payload,
            )
            transaction = journal.transaction
            _included_snapshots.verify_included_tree_snapshot(
                transaction.stage_container_path,
                transaction.staged_container_snapshot,
                expected_parent_identity=project_identity,
            )
            _included_snapshots.verify_included_tree_snapshot(
                os.path.join(project_path, _included_constants.INCLUDED_FILES_ROOT_NAME),
                transaction.previous_root_snapshot,
                expected_parent_identity=project_identity,
            )
            if journal.registry_directory_created:
                if transaction.previous_registry_snapshot != (
                    _IncludedRegistrySnapshot(
                        directory_identity=None,
                        file_identity=None,
                        file_mode=None,
                        content=None,
                    )
                ):
                    raise OSError(
                        "Created Included File registry directory disagrees "
                        "with the previous generation"
                    )
                _included_snapshots.verify_included_registry_snapshot(
                    project_path,
                    _IncludedRegistrySnapshot(
                        directory_identity=journal.registry_directory_identity,
                        file_identity=None,
                        file_mode=None,
                        content=None,
                    ),
                    expected_project_identity=project_identity,
                )
            else:
                _included_snapshots.verify_included_registry_snapshot(
                    project_path,
                    transaction.previous_registry_snapshot,
                    expected_project_identity=project_identity,
                )
        except OSError:
            warnings.append(
                "ambiguous Included Files journal temporary was preserved: "
                + candidate_path
            )
            continue
        candidates.append((candidate_path, candidate_identity))
    if len(candidates) > 1:
        raise OSError(
            "Multiple valid Included Files journal temporaries require manual "
            "inspection"
        )
    if not candidates:
        return False, tuple(warnings)
    candidate_path, candidate_identity = candidates[0]
    _included_mutations.move_exact_included_file(
        candidate_path,
        journal_path,
        candidate_identity,
        source_parent_identity=project_identity,
        destination_parent_identity=project_identity,
    )
    _included_fs.sync_directory(project_path, project_identity)
    _included_phases.after_included_transaction_phase("recovery-journal-promoted")
    return True, tuple(warnings)


def _recover_included_output_set(
    project_path: str,
    project_identity: _PathIdentity,
) -> str | None:
    journal_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_JOURNAL_NAME)
    commit_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_COMMIT_NAME)
    journal_promoted, promotion_warnings = promote_included_journal_temporary(
        project_path,
        project_identity,
    )
    journal_record = _included_records.read_included_recovery_record_or_tombstone(
        journal_path,
        project_identity,
    )
    commit_record = _included_records.read_included_recovery_record_or_tombstone(
        commit_path,
        project_identity,
    )
    if journal_record is None:
        messages: list[str] = list(promotion_warnings)
        if commit_record is not None:
            commit_record_path, commit_identity, commit_payload = commit_record
            marker, embedded_journal = (
                _included_codec.included_commit_marker_and_journal_from_payload(
                    project_path,
                    commit_payload,
                    project_identity,
                )
            )
            _included_transaction_state.verify_included_commit_marker_generation(project_path, marker)
            cleanup_errors, cleanup_warnings = (
                _included_transaction_cleanup.cleanup_committed_included_output_set(embedded_journal)
            )
            if cleanup_errors:
                error = OSError(
                    "Committed Included Files marker-only recovery could not "
                    "finish cleanup"
                )
                for cleanup_error in cleanup_errors:
                    error.add_note(str(cleanup_error))
                raise error
            _included_record_lifecycle.remove_included_recovery_record(
                commit_record_path,
                commit_identity,
                project_path,
                project_identity,
            )
            messages.append(
                "finalized an already committed Included Files generation"
            )
            messages.extend(cleanup_warnings)
        orphan_count, orphan_warnings = cleanup_orphan_included_recovery_state(
            project_path,
            project_identity,
        )
        if orphan_count:
            messages.append(
                f"removed {orphan_count} self-identified orphan transaction entries"
            )
        messages.extend(orphan_warnings)
        return "; ".join(messages) if messages else None

    journal_record_path, journal_identity, journal_payload = journal_record
    journal = _included_codec.included_recovery_journal_from_payload(
        project_path,
        project_identity,
        journal_payload,
    )
    commit_identity: _PathIdentity | None = None
    commit_record_path = commit_path
    if commit_record is not None:
        commit_record_path, commit_identity, commit_payload = commit_record
        marker, embedded_journal = (
            _included_codec.included_commit_marker_and_journal_from_payload(
                project_path,
                commit_payload,
                project_identity,
            )
        )
        if (
            marker != _included_codec.included_commit_marker_from_journal(journal)
            or embedded_journal != journal
        ):
            raise OSError(
                "Included Files recovery journal and commit marker disagree"
            )

    transaction = journal.transaction
    if commit_identity is None:
        rollback_errors = _included_transaction_cleanup.rollback_included_output_set(
            transaction,
            root_backup_path=journal.root_backup_path,
            registry_backup_path=journal.registry_backup_path,
            registry_directory_path=journal.registry_directory_path,
            registry_directory_identity=journal.registry_directory_identity,
            registry_directory_created=journal.registry_directory_created,
        )
        if rollback_errors:
            error = OSError(
                "Interrupted Included Files generation could not be rolled back"
            )
            for rollback_error in rollback_errors:
                error.add_note(str(rollback_error))
            raise error
        final_root_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_ROOT_NAME)
        _included_snapshots.verify_included_tree_snapshot(
            final_root_path,
            transaction.previous_root_snapshot,
            expected_parent_identity=project_identity,
        )
        _included_snapshots.verify_included_registry_snapshot(
            project_path,
            transaction.previous_registry_snapshot,
            expected_project_identity=project_identity,
        )
        rollback_cleanup_warnings = _included_cleanup.cleanup_recorded_included_tree(
            transaction.stage_container_path,
            transaction.staged_container_snapshot,
            project_identity,
            journal.transaction_id,
            "rollback-stage",
        )
        _included_fs.sync_directory(project_path, project_identity)
        previous_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
        )
        if previous_registry_directory_identity is not None:
            _included_fs.sync_directory(
                journal.registry_directory_path,
                previous_registry_directory_identity,
            )
        _included_record_lifecycle.remove_included_recovery_record(
            journal_record_path,
            journal_identity,
            project_path,
            project_identity,
        )
        orphan_count, orphan_warnings = cleanup_orphan_included_recovery_state(
            project_path,
            project_identity,
        )
        _included_phases.after_included_transaction_phase("recovery-rolled-back")
        message = "rolled back an interrupted Included Files generation"
        if journal_promoted:
            message += " from its durable journal temporary"
        if orphan_count:
            message += f"; removed {orphan_count} orphan transaction entries"
        all_warnings = (
            *promotion_warnings,
            *rollback_cleanup_warnings,
            *orphan_warnings,
        )
        if all_warnings:
            message += "; " + "; ".join(all_warnings)
        return message

    cleanup_errors, cleanup_warnings = _included_transaction_cleanup.cleanup_committed_included_output_set(
        journal
    )
    if cleanup_errors:
        error = OSError(
            "Committed Included Files generation recovery could not finish cleanup"
        )
        for cleanup_error in cleanup_errors:
            error.add_note(str(cleanup_error))
        raise error
    _included_record_lifecycle.remove_included_recovery_record(
        journal_record_path,
        journal_identity,
        project_path,
        project_identity,
    )
    _included_phases.after_included_transaction_phase("recovery-journal-removed")
    _included_record_lifecycle.remove_included_recovery_record(
        commit_record_path,
        commit_identity,
        project_path,
        project_identity,
    )
    orphan_count, orphan_warnings = cleanup_orphan_included_recovery_state(
        project_path,
        project_identity,
    )
    _included_phases.after_included_transaction_phase("recovery-committed")
    message = "finalized a committed Included Files generation"
    all_warnings = (*promotion_warnings, *cleanup_warnings, *orphan_warnings)
    if orphan_count:
        message += f"; removed {orphan_count} orphan transaction entries"
    if all_warnings:
        message += "; " + "; ".join(all_warnings)
    return message


cleanup_orphan_included_recovery_state = _cleanup_orphan_included_recovery_state
promote_included_journal_temporary = _promote_included_journal_temporary
recover_included_output_set = _recover_included_output_set
