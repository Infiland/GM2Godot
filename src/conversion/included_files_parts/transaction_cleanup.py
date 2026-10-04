"""Included Files transaction cleanup ownership."""

from __future__ import annotations
import hashlib
import os
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, IncludedOutputSetTransaction as _IncludedOutputSetTransaction, IncludedRecoveryJournal as _IncludedRecoveryJournal
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import recorded_cleanup as _included_cleanup

def _rollback_included_output_set(
    transaction: _IncludedOutputSetTransaction,
    *,
    root_backup_path: str,
    registry_backup_path: str,
    registry_directory_path: str,
    registry_directory_identity: _PathIdentity | None,
    registry_directory_created: bool,
) -> tuple[Exception, ...]:
    errors: list[Exception] = []
    final_root_path = os.path.join(
        os.path.dirname(transaction.stage_container_path),
        _included_constants.INCLUDED_FILES_ROOT_NAME,
    )
    final_registry_path = _included_paths.included_registry_path(
        os.path.dirname(transaction.stage_container_path)
    )

    try:
        project_path = os.path.dirname(transaction.stage_container_path)
        _included_snapshots.verify_included_project_identity(
            project_path,
            transaction.project_identity,
        )
        previous_registry_directory_identity = (
            transaction.previous_registry_snapshot.directory_identity
        )
        expected_registry_parent_identity = (
            registry_directory_identity
            if registry_directory_identity is not None
            else previous_registry_directory_identity
        )
        current_registry_directory_identity = _included_snapshots.included_directory_identity(
            registry_directory_path
        )
        if current_registry_directory_identity is None:
            if not (
                registry_directory_created
                and previous_registry_directory_identity is None
            ) and expected_registry_parent_identity is not None:
                raise OSError(
                    "Included File registry directory disappeared during rollback"
                )
            final_registry_parent_identity = None
        elif (
            expected_registry_parent_identity is None
            or current_registry_directory_identity
            != expected_registry_parent_identity
        ):
            raise OSError(
                "Included File registry directory changed during rollback"
            )
        else:
            final_registry_parent_identity = current_registry_directory_identity
        previous_registry_identity = (
            transaction.previous_registry_snapshot.file_identity
        )
        allowed_current_registry_identities = {
            transaction.staged_registry_identity
        }
        if previous_registry_identity is not None:
            allowed_current_registry_identities.add(previous_registry_identity)

        if final_registry_parent_identity is None:
            if _included_snapshots.included_directory_identity(registry_directory_path) is not None:
                raise OSError(
                    "Refusing to inspect an Included File registry directory "
                    "that appeared during rollback"
                )
            current_registry_state = None
        else:
            current_registry_state = _included_snapshots.included_regular_file_state(
                final_registry_path,
                expected_parent_identity=final_registry_parent_identity,
                allowed_identities=frozenset(
                    allowed_current_registry_identities
                ),
            )
        current_registry_identity = (
            current_registry_state[0]
            if current_registry_state is not None
            else None
        )
        if previous_registry_identity is None:
            backup_registry_identity = None
        elif current_registry_identity == previous_registry_identity:
            # The previous public registry is already intact. An entry at the
            # reserved backup path is therefore not ours and must be preserved
            # without preventing rollback of the rest of the transaction.
            backup_registry_identity = None
        else:
            if previous_registry_directory_identity is None:
                raise AssertionError(
                    "A previous Included File registry requires its directory"
                )
            backup_registry_state = _included_snapshots.included_regular_file_state(
                registry_backup_path,
                expected_parent_identity=(
                    previous_registry_directory_identity
                ),
                allowed_identities=frozenset({previous_registry_identity}),
            )
            backup_registry_identity = (
                backup_registry_state[0]
                if backup_registry_state is not None
                else None
            )
        if current_registry_identity == transaction.staged_registry_identity:
            if final_registry_parent_identity is None:
                raise AssertionError(
                    "A published Included File registry requires its directory"
                )
            _included_mutations.move_exact_included_file(
                final_registry_path,
                transaction.staged_registry_path,
                transaction.staged_registry_identity,
                source_parent_identity=final_registry_parent_identity,
                destination_parent_identity=transaction.stage_container_identity,
            )
            current_registry_identity = None
        elif current_registry_identity not in {None, previous_registry_identity}:
            raise OSError("Refusing to overwrite an unknown Included File registry during rollback")

        if previous_registry_identity is None:
            if backup_registry_identity is not None or current_registry_identity is not None:
                raise OSError("Could not restore the previously absent Included File registry")
        elif current_registry_identity == previous_registry_identity:
            pass
        elif backup_registry_identity == previous_registry_identity:
            if (
                previous_registry_directory_identity is None
                or final_registry_parent_identity is None
            ):
                raise AssertionError(
                    "A previous Included File registry requires its directory"
                )
            _included_mutations.move_exact_included_file(
                registry_backup_path,
                final_registry_path,
                previous_registry_identity,
                source_parent_identity=(
                    previous_registry_directory_identity
                ),
                destination_parent_identity=final_registry_parent_identity,
            )
        else:
            raise OSError("Previous Included File registry backup is unavailable")
    except Exception as error:
        errors.append(error)

    try:
        current_root_identity = _included_snapshots.included_directory_identity(final_root_path)
        previous_root_identity = transaction.previous_root_snapshot.identity
        backup_root_identity = (
            None
            if current_root_identity == previous_root_identity
            else _included_snapshots.included_directory_identity(root_backup_path)
        )
        staged_root_identity = transaction.staged_root_snapshot.identity
        if staged_root_identity is None:
            raise AssertionError("A staged Included Files root must be present")
        if current_root_identity == staged_root_identity:
            _included_mutations.move_exact_included_directory(
                final_root_path,
                transaction.staged_root_path,
                staged_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.stage_container_identity,
            )
            current_root_identity = None
        elif current_root_identity not in {None, previous_root_identity}:
            raise OSError("Refusing to overwrite an unknown Included Files root during rollback")

        if previous_root_identity is None:
            if backup_root_identity is not None or current_root_identity is not None:
                raise OSError("Could not restore the previously absent Included Files root")
        elif current_root_identity == previous_root_identity:
            pass
        elif backup_root_identity == previous_root_identity:
            _included_mutations.move_exact_included_directory(
                root_backup_path,
                final_root_path,
                previous_root_identity,
                source_parent_identity=transaction.project_identity,
                destination_parent_identity=transaction.project_identity,
            )
        else:
            raise OSError("Previous Included Files root backup is unavailable")
    except Exception as error:
        errors.append(error)

    if registry_directory_created and registry_directory_identity is not None:
        try:
            current_registry_directory_identity = _included_snapshots.included_directory_identity(
                registry_directory_path
            )
            if current_registry_directory_identity is None:
                pass
            elif current_registry_directory_identity == registry_directory_identity:
                _included_cleanup.cleanup_recorded_included_directory(
                    registry_directory_path,
                    registry_directory_identity,
                    transaction.project_identity,
                    (
                        f"{transaction.project_identity[0]:x}"
                        f"{transaction.project_identity[1]:x}"
                    ),
                    "rollback-registry-directory",
                    "gm2godot",
                )
            else:
                raise OSError(
                    "Included File registry directory changed during rollback"
                )
        except Exception as error:
            errors.append(error)
    return tuple(errors)


def _cleanup_committed_included_output_set(
    journal: _IncludedRecoveryJournal,
    *,
    verify_content: bool = True,
) -> tuple[tuple[Exception, ...], tuple[str, ...]]:
    errors: list[Exception] = []
    warnings: list[str] = []
    transaction = journal.transaction
    project_path = os.path.dirname(transaction.stage_container_path)
    final_root_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_ROOT_NAME)
    final_registry_path = _included_paths.included_registry_path(project_path)

    try:
        _included_snapshots.verify_included_project_identity(project_path, transaction.project_identity)
        if verify_content:
            _included_snapshots.verify_included_tree_snapshot(
                final_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.project_identity,
            )
        else:
            _included_snapshots.verify_included_tree_snapshot_metadata(
                final_root_path,
                transaction.staged_root_snapshot,
                expected_parent_identity=transaction.project_identity,
            )
        if (
            _included_snapshots.included_directory_identity(journal.registry_directory_path)
            != journal.registry_directory_identity
        ):
            raise OSError(
                "Included File registry directory changed during committed recovery"
            )
        registry_state = _included_snapshots.included_regular_file_state(
            final_registry_path,
            expected_parent_identity=journal.registry_directory_identity,
            allowed_identities=frozenset(
                {transaction.staged_registry_identity}
            ),
        )
        if (
            registry_state is None
            or registry_state[0] != transaction.staged_registry_identity
            or registry_state[2] != transaction.staged_registry_content
        ):
            raise OSError(
                "Committed Included File registry generation is unavailable"
            )
    except Exception as error:
        return (error,), ()

    try:
        warnings.extend(
            _included_cleanup.cleanup_recorded_included_tree(
                journal.root_backup_path,
                transaction.previous_root_snapshot,
                transaction.project_identity,
                journal.transaction_id,
                "root-backup",
            )
        )
    except Exception as error:
        errors.append(error)

    previous_registry_identity = (
        transaction.previous_registry_snapshot.file_identity
    )
    try:
        if previous_registry_identity is None:
            if os.path.lexists(journal.registry_backup_path):
                warnings.append(
                    "Unknown replacement at the Included File registry backup "
                    f"path was preserved: {journal.registry_backup_path}"
                )
        else:
            previous_registry_content = (
                transaction.previous_registry_snapshot.content
            )
            if previous_registry_content is None:
                raise AssertionError(
                    "A previous Included File registry requires recorded content"
                )
            warnings.extend(
                _included_cleanup.cleanup_recorded_included_file(
                    journal.registry_backup_path,
                    previous_registry_identity,
                    hashlib.sha256(previous_registry_content).hexdigest(),
                    journal.registry_directory_identity,
                    journal.transaction_id,
                    "registry-backup",
                    os.path.basename(journal.registry_backup_path),
                    expected_mode=(
                        transaction.previous_registry_snapshot.file_mode
                    ),
                )
            )
    except Exception as error:
        errors.append(error)

    try:
        warnings.extend(
            _included_cleanup.cleanup_recorded_included_tree(
                transaction.stage_container_path,
                transaction.staged_container_snapshot,
                transaction.project_identity,
                journal.transaction_id,
                "stage",
            )
        )
    except Exception as error:
        errors.append(error)
    return tuple(errors), tuple(warnings)


rollback_included_output_set = _rollback_included_output_set
cleanup_committed_included_output_set = _cleanup_committed_included_output_set
