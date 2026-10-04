"""Included Files publisher ownership."""

from __future__ import annotations

import os
import secrets

from src.conversion.included_files_parts import (
    constants as _included_constants,
    guarded_mutations as _included_mutations,
    path_validation as _included_paths,
    phase_observer as _included_phases,
    record_io as _included_records,
    record_lifecycle as _included_record_lifecycle,
    recorded_cleanup as _included_cleanup,
    recovery_codec as _included_codec,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
    transaction_cleanup as _included_transaction_cleanup,
    transaction_state as _included_transaction_state,
)
from src.conversion.included_files_parts.models import (
    IncludedOutputSetCancelled as _IncludedOutputSetCancelled,
    IncludedOutputSetTransaction as _IncludedOutputSetTransaction,
    IncludedRecoveryJournal as _IncludedRecoveryJournal,
    PathIdentity as _PathIdentity,
)
from src.conversion.included_files_parts.native_filesystem import (
    filesystem as _included_fs,
)
from src.conversion.type_defs import ConversionRunning


def _commit_included_output_set(
    project_path: str,
    transaction: _IncludedOutputSetTransaction,
    conversion_running: ConversionRunning,
) -> tuple[str, ...]:
    """Publish one journaled, recoverable root/registry generation."""
    final_root_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_ROOT_NAME)
    final_registry_path = _included_paths.included_registry_path(project_path)
    journal_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_JOURNAL_NAME)
    commit_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_COMMIT_NAME)
    root_backup_path = _included_mutations.unique_included_transaction_path(
        project_path,
        "included_files",
    )
    registry_directory_path = os.path.dirname(final_registry_path)
    registry_backup_path = _included_mutations.unique_included_transaction_path(
        registry_directory_path
        if transaction.previous_registry_snapshot.file_identity is not None
        else project_path,
        "gml_included_file_registry.gd",
    )
    registry_directory_identity: _PathIdentity | None = None
    registry_directory_created = False
    journal_identity: _PathIdentity | None = None
    commit_marker_identity: _PathIdentity | None = None
    recovery_journal: _IncludedRecoveryJournal | None = None

    try:
        _included_snapshots.verify_included_project_identity(
            project_path,
            transaction.project_identity,
        )
        _included_staging.verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _included_snapshots.verify_included_tree_snapshot(
            final_root_path,
            transaction.previous_root_snapshot,
            expected_parent_identity=transaction.project_identity,
        )
        _included_snapshots.verify_included_registry_snapshot(
            project_path,
            transaction.previous_registry_snapshot,
            expected_project_identity=transaction.project_identity,
        )
        if transaction.content_receipts:
            publication_transaction_id = (
                transaction.publication_transaction_id
            )
            staged_generation_identity = (
                transaction.staged_root_snapshot.identity
            )
            if (
                publication_transaction_id is None
                or staged_generation_identity is None
            ):
                raise OSError(
                    "Included Files generation receipts lost their "
                    "transaction binding"
                )
            current_staged_snapshot = (
                _included_snapshots.capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=(
                        transaction.stage_container_identity
                    ),
                    transaction_id=publication_transaction_id,
                    generation_identity=staged_generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=transaction.content_receipts,
                )
            )
            if current_staged_snapshot != transaction.staged_root_snapshot:
                raise OSError(
                    "Included Files generation receipt snapshot changed"
                )
            for content_receipt in transaction.content_receipts:
                _included_snapshots.verify_included_generation_source_receipt(
                    content_receipt.source,
                    validate_content=False,
                )
        else:
            _included_snapshots.verify_included_tree_snapshot(
                transaction.staged_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.stage_container_identity,
            )
        staged_registry_state = _included_snapshots.included_regular_file_state(
            transaction.staged_registry_path,
            expected_parent_identity=transaction.stage_container_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            staged_registry_state is None
            or staged_registry_state[0] != transaction.staged_registry_identity
            or staged_registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError("Included File registry staging candidate changed")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        expected_record_sizes = transaction.recovery_record_sizes
        if expected_record_sizes is None:
            raise OSError(
                "Included Files recovery metadata was not preflighted before "
                "payload staging"
            )
        provisional_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
            or (
                transaction.project_identity[0],
                _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_MAX,
            )
        )
        provisional_journal = _IncludedRecoveryJournal(
            format_version=_included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id="0" * 32,
            transaction=transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=(
                provisional_registry_directory_identity
            ),
            registry_directory_created=(
                transaction.previous_registry_snapshot.directory_identity
                is None
            ),
        )
        _included_codec.verify_included_recovery_record_sizes(
            expected_record_sizes,
            provisional_journal,
        )

        (
            registry_directory_path,
            registry_directory_identity,
            registry_directory_created,
        ) = _included_staging.prepare_included_registry_directory(
            project_path,
            transaction.previous_registry_snapshot,
            transaction.project_identity,
        )
        registry_backup_path = _included_mutations.unique_included_transaction_path(
            registry_directory_path
            if transaction.previous_registry_snapshot.file_identity is not None
            else project_path,
            "gml_included_file_registry.gd",
        )
        recovery_journal = _IncludedRecoveryJournal(
            format_version=_included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id=(
                transaction.publication_transaction_id
                or secrets.token_hex(16)
            ),
            transaction=transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        _included_codec.verify_included_recovery_record_sizes(
            expected_record_sizes,
            recovery_journal,
        )
        journal_identity = _included_record_lifecycle.publish_included_recovery_record(
            project_path,
            transaction.project_identity,
            filename=_included_constants.INCLUDED_FILES_JOURNAL_NAME,
            temporary_prefix=_included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
            payload=_included_codec.included_recovery_journal_payload(recovery_journal),
            staged_phase="journal-record-staged",
        )
        _included_phases.after_included_transaction_phase("journal-prepared")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        previous_root_identity = transaction.previous_root_snapshot.identity
        if previous_root_identity is not None:
            _included_mutations.move_exact_included_directory(
                final_root_path,
                root_backup_path,
                previous_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.project_identity,
            )
        _included_fs.sync_directory(project_path, transaction.project_identity)
        _included_phases.after_included_transaction_phase("previous-root-backed-up")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        staged_root_identity = transaction.staged_root_snapshot.identity
        if staged_root_identity is None:
            raise AssertionError("A staged Included Files root must be present")
        _included_mutations.move_exact_included_directory(
            transaction.staged_root_path,
            final_root_path,
            staged_root_identity,
            source_parent_identity=transaction.stage_container_identity,
            destination_parent_identity=transaction.project_identity,
        )
        _included_fs.sync_directory(
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _included_fs.sync_directory(project_path, transaction.project_identity)
        _included_snapshots.verify_included_tree_snapshot_metadata(
            final_root_path,
            transaction.staged_root_snapshot,
            expected_parent_identity=transaction.project_identity,
        )
        _included_phases.after_included_transaction_phase("new-root-published")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        previous_registry_identity = (
            transaction.previous_registry_snapshot.file_identity
        )
        if previous_registry_identity is not None:
            _included_mutations.move_exact_included_file(
                final_registry_path,
                registry_backup_path,
                previous_registry_identity,
                source_parent_identity=registry_directory_identity,
                destination_parent_identity=registry_directory_identity,
            )
        _included_fs.sync_directory(
            registry_directory_path,
            registry_directory_identity,
        )
        _included_phases.after_included_transaction_phase("previous-registry-backed-up")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()

        _included_mutations.move_exact_included_file(
            transaction.staged_registry_path,
            final_registry_path,
            transaction.staged_registry_identity,
            source_parent_identity=transaction.stage_container_identity,
            destination_parent_identity=registry_directory_identity,
        )
        _included_fs.sync_directory(
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        _included_fs.sync_directory(
            registry_directory_path,
            registry_directory_identity,
        )
        published_registry_state = _included_snapshots.included_regular_file_state(
            final_registry_path,
            expected_parent_identity=registry_directory_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            published_registry_state is None
            or published_registry_state[0] != transaction.staged_registry_identity
            or published_registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError("Included File registry changed after publication")
        _included_phases.after_included_transaction_phase("new-registry-published")
        if not conversion_running():
            raise _IncludedOutputSetCancelled()
        _included_staging.sync_included_tree_directories_bottom_up(
            final_root_path,
            transaction.staged_root_snapshot,
            transaction.project_identity,
        )
        journal_identity = _included_transaction_state.verify_included_published_journal(
            project_path,
            transaction.project_identity,
            recovery_journal,
            journal_identity,
        )
        if transaction.content_receipts:
            publication_transaction_id = (
                transaction.publication_transaction_id
            )
            staged_generation_identity = (
                transaction.staged_root_snapshot.identity
            )
            if (
                publication_transaction_id is None
                or staged_generation_identity is None
                or recovery_journal.transaction_id
                != publication_transaction_id
            ):
                raise OSError(
                    "Included Files generation receipts crossed transaction "
                    "or generation boundaries"
                )
            final_receipt_snapshot = (
                _included_snapshots.capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=transaction.project_identity,
                    transaction_id=publication_transaction_id,
                    generation_identity=staged_generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=transaction.content_receipts,
                    published=True,
                )
            )
            if final_receipt_snapshot != transaction.staged_root_snapshot:
                raise OSError(
                    "Published Included Files generation receipt changed"
                )
            before_included_changed_generation_final_validation()
            for content_receipt in transaction.content_receipts:
                _included_snapshots.verify_included_generation_source_receipt(
                    content_receipt.source,
                    validate_content=True,
                )
        _included_transaction_state.verify_included_commit_marker_generation(
            project_path,
            _included_codec.included_commit_marker_from_journal(recovery_journal),
        )
        _included_staging.verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        commit_marker_identity = _included_record_lifecycle.publish_included_recovery_record(
            project_path,
            transaction.project_identity,
            filename=_included_constants.INCLUDED_FILES_COMMIT_NAME,
            temporary_prefix=_included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX,
            payload=_included_codec.included_commit_marker_payload(recovery_journal),
            staged_phase="commit-record-staged",
        )
        _included_phases.after_included_transaction_phase("generation-committed")
        commit_marker_identity = _included_transaction_state.verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
    except BaseException as error:
        if commit_marker_identity is None and recovery_journal is not None:
            try:
                stable_commit_record = _included_records.read_included_recovery_record(
                    commit_path,
                    transaction.project_identity,
                )
                if stable_commit_record is not None:
                    commit_marker_identity = (
                        _included_transaction_state.verify_included_published_commit_marker(
                            project_path,
                            transaction.project_identity,
                            recovery_journal,
                            None,
                            verify_generation=False,
                        )
                    )
            except Exception as marker_error:
                error.add_note(
                    "The Included Files commit path became ambiguous after "
                    "publication; rollback was not attempted: " + str(marker_error)
                )
                raise error from marker_error
        if commit_marker_identity is not None:
            error.add_note(
                "The new Included Files generation was durably committed; "
                "the next conversion will finish cleanup"
            )
            raise
        rollback_errors = _included_transaction_cleanup.rollback_included_output_set(
            transaction,
            root_backup_path=root_backup_path,
            registry_backup_path=registry_backup_path,
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        if not rollback_errors:
            try:
                rollback_cleanup_warnings = _included_cleanup.cleanup_recorded_included_tree(
                    transaction.stage_container_path,
                    transaction.staged_container_snapshot,
                    transaction.project_identity,
                    (
                        recovery_journal.transaction_id
                        if recovery_journal is not None
                        else "unprepared-stage"
                    ),
                    "rollback-stage",
                )
                for cleanup_warning in rollback_cleanup_warnings:
                    error.add_note(cleanup_warning)
                _included_fs.sync_directory(
                    project_path,
                    transaction.project_identity,
                )
                if (
                    registry_directory_identity is not None
                    and _included_snapshots.included_directory_identity(registry_directory_path)
                    == registry_directory_identity
                ):
                    _included_fs.sync_directory(
                        registry_directory_path,
                        registry_directory_identity,
                    )
                stable_journal_record = _included_records.read_included_recovery_record(
                    journal_path,
                    transaction.project_identity,
                )
                if recovery_journal is not None and stable_journal_record is not None:
                    journal_identity = _included_transaction_state.verify_included_published_journal(
                        project_path,
                        transaction.project_identity,
                        recovery_journal,
                        journal_identity,
                    )
                    _included_record_lifecycle.remove_included_recovery_record(
                        journal_path,
                        journal_identity,
                        project_path,
                        transaction.project_identity,
                    )
                    journal_identity = None
                _included_phases.after_included_transaction_phase("rollback-complete")
            except Exception as cleanup_error:
                rollback_errors = (cleanup_error,)
        if rollback_errors:
            error.add_note(
                "Included Files rollback also failed: "
                + "; ".join(str(rollback_error) for rollback_error in rollback_errors)
            )
        raise

    cleanup_errors, cleanup_warnings = _included_transaction_cleanup.cleanup_committed_included_output_set(
        recovery_journal,
        verify_content=False,
    )
    if cleanup_errors:
        return tuple(str(cleanup_error) for cleanup_error in cleanup_errors)

    try:
        commit_marker_identity = _included_transaction_state.verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _included_record_lifecycle.remove_included_recovery_record(
            journal_path,
            journal_identity,
            project_path,
            transaction.project_identity,
        )
        _included_phases.after_included_transaction_phase("journal-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))

    try:
        commit_marker_identity = _included_transaction_state.verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _included_record_lifecycle.remove_included_recovery_record(
            commit_path,
            commit_marker_identity,
            project_path,
            transaction.project_identity,
        )
        _included_phases.after_included_transaction_phase("commit-marker-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))
    return cleanup_warnings


def _before_included_changed_generation_final_validation() -> None:
    """Narrow test seam before final receipt-bound content validation."""


commit_included_output_set = _commit_included_output_set
before_included_changed_generation_final_validation = _before_included_changed_generation_final_validation
