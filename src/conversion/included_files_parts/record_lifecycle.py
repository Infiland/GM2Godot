"""Included Files record lifecycle ownership."""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

from src.conversion.included_files_parts import (
    constants as _included_constants,
    guarded_mutations as _included_mutations,
    phase_observer as _included_phases,
    record_io as _included_records,
    recorded_cleanup as _included_cleanup,
    recovery_codec as _included_codec,
    source_snapshots as _included_snapshots,
)
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity
from src.conversion.included_files_parts.native_filesystem import (
    filesystem as _included_fs,
)


def _publish_included_recovery_record(
    project_path: str,
    project_identity: _PathIdentity,
    *,
    filename: str,
    temporary_prefix: str,
    payload: dict[str, Any],
    staged_phase: str | None = None,
) -> _PathIdentity:
    destination_path = os.path.join(project_path, filename)
    if (
        _included_records.included_recovery_record_state(
            destination_path,
            project_identity,
            allowed_identities=frozenset(),
        )
        is not None
    ):
        raise OSError(
            "Included Files recovery record already exists: " + destination_path
        )
    content = _included_codec.included_recovery_record_content(payload)
    file_descriptor = -1
    temporary_path = ""
    for _attempt in range(100):
        temporary_name = temporary_prefix + secrets.token_hex(8) + ".tmp"
        candidate_path = os.path.join(project_path, temporary_name)
        try:
            file_descriptor = os.open(
                candidate_path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            continue
        temporary_path = candidate_path
        break
    if file_descriptor < 0 or not temporary_path:
        raise OSError("Could not allocate Included Files recovery staging record")
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            file_descriptor = -1
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _included_snapshots.verify_included_project_identity(project_path, project_identity)
        temporary_state = _included_records.included_recovery_record_state(
            temporary_path,
            project_identity,
            allowed_identities=frozenset({temporary_identity}),
        )
        if (
            temporary_state is None
            or temporary_state[0] != temporary_identity
            or temporary_state[2] != content
        ):
            raise OSError("Included Files recovery staging record changed")
        # The crash-test phase names this temporary "durable". Persist its
        # project-directory entry as well as its already-fsynced contents
        # before exposing that boundary to recovery.
        _included_fs.sync_directory(project_path, project_identity)
        if staged_phase is not None:
            _included_phases.after_included_transaction_phase(staged_phase)
        _included_mutations.move_exact_included_file(
            temporary_path,
            destination_path,
            temporary_identity,
            source_parent_identity=project_identity,
            destination_parent_identity=project_identity,
        )
        temporary_pending = False
        _included_fs.sync_directory(project_path, project_identity)
        published_state = _included_records.included_recovery_record_state(
            destination_path,
            project_identity,
            allowed_identities=frozenset({temporary_identity}),
        )
        if (
            published_state is None
            or published_state[0] != temporary_identity
            or published_state[2] != content
        ):
            raise OSError("Included Files recovery record changed after publication")
        return temporary_identity
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                remove_included_recovery_record(
                    temporary_path,
                    temporary_identity,
                    project_path,
                    project_identity,
                )
            except OSError:
                pass


def _remove_included_recovery_record(
    path: str,
    identity: _PathIdentity,
    project_path: str,
    project_identity: _PathIdentity,
) -> None:
    current_state = _included_records.included_recovery_record_state(
        path,
        project_identity,
        allowed_identities=frozenset({identity}),
    )
    if current_state is None:
        return
    if os.path.basename(path).startswith(_included_constants.INCLUDED_FILES_CLEANUP_PREFIX):
        _included_cleanup.remove_included_cleanup_tombstone(
            path,
            identity,
            project_path,
            project_identity,
            expect_directory=False,
        )
        _included_phases.after_included_transaction_phase(
            f"cleanup:record:{os.path.basename(path)}:removed"
        )
        return
    basename = os.path.basename(path)
    content_sha256 = hashlib.sha256(current_state[2]).hexdigest()
    if basename in {
        _included_constants.INCLUDED_FILES_JOURNAL_NAME,
        _included_constants.INCLUDED_FILES_COMMIT_NAME,
    }:
        cleanup_transaction_id = "recovery-record"
        cleanup_role = "record"
        cleanup_relative_path = basename
    elif basename.startswith(_included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX):
        cleanup_transaction_id = content_sha256[:32]
        cleanup_role = "journal-temporary-record"
        cleanup_relative_path = "journal"
    elif basename.startswith(_included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX):
        cleanup_transaction_id = content_sha256[:32]
        cleanup_role = "commit-temporary-record"
        cleanup_relative_path = "commit"
    else:
        cleanup_transaction_id = "recovery-record"
        cleanup_role = "record"
        cleanup_relative_path = basename
    warnings = _included_cleanup.cleanup_recorded_included_file(
        path,
        identity,
        content_sha256,
        project_identity,
        cleanup_transaction_id,
        cleanup_role,
        cleanup_relative_path,
    )
    if warnings:
        raise OSError("; ".join(warnings))


publish_included_recovery_record = _publish_included_recovery_record
remove_included_recovery_record = _remove_included_recovery_record
