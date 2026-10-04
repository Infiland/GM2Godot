from __future__ import annotations

import hashlib

import os
import posixpath
import secrets
import stat

import tempfile

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Any, BinaryIO, Callable, Iterable, TypeVar

from src.localization import get_localized
from src.conversion.atomic_generated_text import (
    atomic_write_confined_generated_text,
)
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_paths import (
    IncludedFilePathAssignment,
    canonical_included_file_lookup_path,
    plan_included_file_paths,
)
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH as INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    render_included_file_registry,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath
from src.conversion.included_files_parts.models import IncludedFileSource as _IncludedFileSource, DeclaredIncludedFile as _DeclaredIncludedFile, IncludedFileConversionPlan as _IncludedFileConversionPlan, PathIdentity as _PathIdentity, IncludedPayloadReceipt as _IncludedPayloadReceipt, IncludedCopyReceipt as _IncludedCopyReceipt, IncludedSourceBinding as _IncludedSourceBinding, IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt, IncludedGenerationMatch as _IncludedGenerationMatch, IncludedGenerationContentReceipt as _IncludedGenerationContentReceipt, IncludedTreeEntry as _IncludedTreeEntry, IncludedTreeSnapshot as _IncludedTreeSnapshot, IncludedRegistrySnapshot as _IncludedRegistrySnapshot, IncludedOutputSetTransaction as _IncludedOutputSetTransaction, IncludedRecoveryJournal as _IncludedRecoveryJournal, IncludedCommitMarker as _IncludedCommitMarker, IncludedProjectLock as _IncludedProjectLock, IncludedOutputSetCancelled as _IncludedOutputSetCancelled

from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import models as _included_models
from src.conversion.included_files_parts import native_posix as _included_posix
from src.conversion.included_files_parts import native_windows as _included_windows
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs


from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import record_io as _included_records
from src.conversion.included_files_parts import recorded_cleanup as _included_cleanup
from src.conversion.included_files_parts import phase_observer as _included_phases

_before_included_transaction_rename = _included_mutations.before_included_transaction_rename
_before_included_transaction_rename_fallback = _included_mutations.before_included_transaction_rename_fallback
_preserve_or_restore_unexpected_moved_entry_at = _included_mutations.preserve_or_restore_unexpected_moved_entry_at
_preserve_or_restore_unexpected_moved_entry_fallback = _included_mutations.preserve_or_restore_unexpected_moved_entry_fallback
_read_included_validation_chunk = _included_snapshots.read_included_validation_chunk
_digest_open_included_file = _included_snapshots.digest_open_included_file
_digest_included_regular_file = _included_snapshots.digest_included_regular_file
_capture_fallback_directory_ancestors = _included_snapshots.capture_fallback_directory_ancestors
_verify_fallback_directory_ancestors = _included_snapshots.verify_fallback_directory_ancestors
_capture_included_source_directory_identities = _included_snapshots.capture_included_source_directory_identities
_included_directory_identity = _included_snapshots.included_directory_identity
_included_regular_file_state_at = _included_snapshots.included_regular_file_state_at
_before_included_fallback_regular_file_open = _included_snapshots.before_included_fallback_regular_file_open
_included_regular_file_state = _included_snapshots.included_regular_file_state
_digest_included_regular_file_at = _included_snapshots.digest_included_regular_file_at
_verify_included_regular_file_mount_boundary_at = _included_snapshots.verify_included_regular_file_mount_boundary_at
_verify_included_tree_descriptor_binding = _included_snapshots.verify_included_tree_descriptor_binding
_verify_included_tree_path_binding = _included_snapshots.verify_included_tree_path_binding
_capture_included_tree_from_fd = _included_snapshots.capture_included_tree_from_fd
_capture_included_tree_descriptor = _included_snapshots.capture_included_tree_descriptor
_after_included_fallback_tree_directory_scan = _included_snapshots.after_included_fallback_tree_directory_scan
_capture_included_tree_fallback = _included_snapshots.capture_included_tree_fallback
_capture_included_tree = _included_snapshots.capture_included_tree
_verify_included_tree_snapshot = _included_snapshots.verify_included_tree_snapshot
_verify_included_tree_snapshot_metadata = _included_snapshots.verify_included_tree_snapshot_metadata
_capture_included_tree_from_generation_receipts = _included_snapshots.capture_included_tree_from_generation_receipts
_verify_included_generation_source_receipt = _included_snapshots.verify_included_generation_source_receipt
_before_included_registry_file_read = _included_snapshots.before_included_registry_file_read
_capture_included_registry = _included_snapshots.capture_included_registry
_verify_included_registry_snapshot = _included_snapshots.verify_included_registry_snapshot
_verify_included_project_identity = _included_snapshots.verify_included_project_identity
_verify_included_directory_entry_identity_at = _included_snapshots.verify_included_directory_entry_identity_at
_before_included_cleanup_quarantine = _included_mutations.before_included_cleanup_quarantine
_before_included_cleanup_remove = _included_mutations.before_included_cleanup_remove
_quarantine_included_entry_at = _included_mutations.quarantine_included_entry_at
_unlink_exact_quarantined_entry_at = _included_mutations.unlink_exact_quarantined_entry_at
_rmdir_exact_quarantined_entry_at = _included_mutations.rmdir_exact_quarantined_entry_at
_remove_included_tree_contents_at = _included_mutations.remove_included_tree_contents_at
_before_included_cleanup_quarantine_fallback = _included_mutations.before_included_cleanup_quarantine_fallback
_before_included_cleanup_remove_fallback = _included_mutations.before_included_cleanup_remove_fallback
_quarantine_included_entry_fallback = _included_mutations.quarantine_included_entry_fallback
_unlink_exact_quarantined_entry_fallback = _included_mutations.unlink_exact_quarantined_entry_fallback
_chmod_exact_included_directory_fallback = _included_mutations.chmod_exact_included_directory_fallback
_rmdir_exact_quarantined_entry_fallback = _included_mutations.rmdir_exact_quarantined_entry_fallback
_remove_owned_included_tree_fallback = _included_mutations.remove_owned_included_tree_fallback
_remove_owned_included_tree = _included_mutations.remove_owned_included_tree
_before_included_fallback_chmod_open = _included_mutations.before_included_fallback_chmod_open
_chmod_exact_included_file = _included_mutations.chmod_exact_included_file
_unique_included_transaction_path = _included_mutations.unique_included_transaction_path
_move_exact_included_entry = _included_mutations.move_exact_included_entry
_move_exact_included_directory = _included_mutations.move_exact_included_directory
_move_exact_included_file = _included_mutations.move_exact_included_file
_after_included_transaction_phase = _included_phases.after_included_transaction_phase
_read_included_recovery_record_payload = _included_records.read_included_recovery_record_payload
_read_included_lock_initialization_payload = _included_records.read_included_lock_initialization_payload
_read_opened_included_bounded_record_payload = _included_records.read_opened_included_bounded_record_payload
_included_bounded_record_state = _included_records.included_bounded_record_state
_included_recovery_record_state = _included_records.included_recovery_record_state
_included_lock_initialization_record_state = _included_records.included_lock_initialization_record_state
_read_included_recovery_record = _included_records.read_included_recovery_record
_read_included_recovery_record_or_tombstone = _included_records.read_included_recovery_record_or_tombstone
_included_cleanup_file_state = _included_cleanup.included_cleanup_file_state
_included_cleanup_directory_state = _included_cleanup.included_cleanup_directory_state
_remove_included_cleanup_tombstone = _included_cleanup.remove_included_cleanup_tombstone
_cleanup_recorded_included_file = _included_cleanup.cleanup_recorded_included_file
_cleanup_recorded_included_directory = _included_cleanup.cleanup_recorded_included_directory
_cleanup_recorded_included_tree = _included_cleanup.cleanup_recorded_included_tree

_PathFingerprint = _included_models.PathFingerprint
_IncludedSourceDirectoryIdentity = _included_models.IncludedSourceDirectoryIdentity
_IncludedCleanupFileState = _included_models.IncludedCleanupFileState
_IncludedTreeDescriptorBinding = _included_models.IncludedTreeDescriptorBinding
_IncludedTreePathBinding = _included_models.IncludedTreePathBinding
_PathHandleBinding = _included_models.PathHandleBinding
_HandleState = _included_models.HandleState
_IncludedSourceFingerprint = _included_models.IncludedSourceFingerprint
_IncludedRecoveryRecordSizes = _included_models.IncludedRecoveryRecordSizes

_windows_included_file_locking = _included_windows.windows_included_file_locking
_WindowsIncludedFileId128 = _included_windows.WindowsIncludedFileId128
_WindowsIncludedFileIdInfo = _included_windows.WindowsIncludedFileIdInfo
_WindowsIncludedFileBasicInfo = _included_windows.WindowsIncludedFileBasicInfo
_included_descriptor_paths_supported = _included_posix.included_descriptor_paths_supported
_included_native_noreplace_available = _included_posix.included_native_noreplace_available
_open_pinned_included_directory = _included_posix.open_pinned_included_directory
_open_pinned_included_parent = _included_posix.open_pinned_included_parent
_rename_included_transaction_entry_at = _included_posix.rename_included_transaction_entry_at
_included_output_path_is_redirected = _included_metadata.included_output_path_is_redirected
_included_linux_mount_id_from_fd = _included_posix.included_linux_mount_id_from_fd
_included_directory_mount_id = _included_posix.included_directory_mount_id
_verify_included_mount_boundary = _included_posix.verify_included_mount_boundary
_verify_included_mount_boundary_path = _included_posix.verify_included_mount_boundary_path
_windows_included_file_read_api = _included_windows.windows_included_file_read_api
_windows_included_cleanup_parent_api = _included_windows.windows_included_cleanup_parent_api
_windows_included_transaction_api = _included_windows.windows_included_transaction_api
_windows_included_transaction_error = _included_windows.windows_included_transaction_error
_windows_included_cleanup_parent_identity = _included_windows.windows_included_cleanup_parent_identity
_windows_included_cleanup_parent_attributes = _included_windows.windows_included_cleanup_parent_attributes
_WindowsIncludedCleanupParentBinding = _included_windows.WindowsIncludedCleanupParentBinding
_verify_windows_included_cleanup_parent_binding = _included_windows.verify_windows_included_cleanup_parent_binding
_open_included_file_validation_stream = _included_windows.open_included_file_validation_stream
_open_included_tree_directory_at = _included_posix.open_included_tree_directory_at
_rename_included_transaction_entry = _included_windows.rename_included_transaction_entry
_sync_included_directory = _included_posix.sync_included_directory
_confined_included_output_supported = _included_posix.confined_included_output_supported
_open_or_create_included_output_directory = _included_posix.open_or_create_included_output_directory
_apply_included_output_metadata = _included_posix.apply_included_output_metadata

_INCLUDED_FILES_ROOT_NAME = _included_constants.INCLUDED_FILES_ROOT_NAME
_INCLUDED_FILES_STAGE_PREFIX = _included_constants.INCLUDED_FILES_STAGE_PREFIX
_INCLUDED_FILES_LOCK_NAME = _included_constants.INCLUDED_FILES_LOCK_NAME
_INCLUDED_FILES_LOCK_TEMP_PREFIX = _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
_INCLUDED_FILES_LOCK_CLEANUP_PREFIX = _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
_INCLUDED_FILES_JOURNAL_NAME = _included_constants.INCLUDED_FILES_JOURNAL_NAME
_INCLUDED_FILES_COMMIT_NAME = _included_constants.INCLUDED_FILES_COMMIT_NAME
_INCLUDED_FILES_JOURNAL_TEMP_PREFIX = _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
_INCLUDED_FILES_COMMIT_TEMP_PREFIX = _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
_INCLUDED_FILES_STAGE_MARKER_NAME = _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME
_INCLUDED_FILES_CLEANUP_PREFIX = _included_constants.INCLUDED_FILES_CLEANUP_PREFIX
_INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION = _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
_INCLUDED_FILES_RECOVERY_FORMAT_VERSION = _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
_INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION = _included_constants.INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION
_INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER = _included_constants.INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER
_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES = _included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES
_INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES = _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES
_INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS = _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS
_INCLUDED_FILES_RECOVERY_INTEGER_MAX = _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_MAX
_INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256 = _included_constants.INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256
_INCLUDED_FILES_LOCK_CONTENT = _included_constants.INCLUDED_FILES_LOCK_CONTENT

_WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES = _included_paths.WINDOWS_RESERVED_RECOVERY_DEVICE_NAMES

_directory_identity_from_fd = _included_metadata.directory_identity_from_fd
_verify_included_directory_fd = _included_metadata.verify_included_directory_fd
_included_entry_stat_at = _included_metadata.included_entry_stat_at
_verify_included_entry_at = _included_metadata.verify_included_entry_at
_included_path_fingerprint = _included_metadata.included_path_fingerprint
_included_path_handle_binding = _included_metadata.included_path_handle_binding
_included_handle_state = _included_metadata.included_handle_state
_included_source_fingerprint = _included_metadata.included_source_fingerprint
_windows_extended_included_path = _included_paths.windows_extended_included_path
_included_tree_without_content = _included_metadata.included_tree_without_content
_included_tree_matches_planned_paths = _included_metadata.included_tree_matches_planned_paths
_included_tree_matches_source_receipts = _included_metadata.included_tree_matches_source_receipts
_included_generation_receipts_by_path = _included_metadata.included_generation_receipts_by_path
_included_registry_receipts_from_tree = _included_metadata.included_registry_receipts_from_tree
_verify_staged_included_inventory = _included_metadata.verify_staged_included_inventory
_included_registry_path = _included_paths.included_registry_path
_included_identity_payload = _included_codec.included_identity_payload
_included_recovery_compact_integer_payload = _included_codec.included_recovery_compact_integer_payload
_included_compact_identity_payload = _included_codec.included_compact_identity_payload
_included_compact_fingerprint_payload = _included_codec.included_compact_fingerprint_payload
_included_tree_snapshot_payload = _included_codec.included_tree_snapshot_payload
_included_compact_tree_snapshot_payload = _included_codec.included_compact_tree_snapshot_payload
_included_registry_snapshot_payload = _included_codec.included_registry_snapshot_payload
_included_compact_registry_snapshot_payload = _included_codec.included_compact_registry_snapshot_payload
_included_registry_backup_location = _included_paths.included_registry_backup_location
_included_recovery_journal_payload_v1 = _included_codec.included_recovery_journal_payload_v1
_included_recovery_journal_payload_v2 = _included_codec.included_recovery_journal_payload_v2
_included_recovery_journal_payload = _included_codec.included_recovery_journal_payload
_included_tree_snapshot_sha256 = _included_codec.included_tree_snapshot_sha256
_included_commit_marker_from_journal = _included_codec.included_commit_marker_from_journal
_included_commit_marker_payload_v1 = _included_codec.included_commit_marker_payload_v1
_included_commit_marker_payload_v2 = _included_codec.included_commit_marker_payload_v2
_included_commit_marker_payload = _included_codec.included_commit_marker_payload
_included_recovery_record_sizes = _included_codec.included_recovery_record_sizes
_included_preflight_placeholder_snapshots = _included_codec.included_preflight_placeholder_snapshots
_preflight_included_recovery_record_sizes = _included_codec.preflight_included_recovery_record_sizes
_verify_included_recovery_record_sizes = _included_codec.verify_included_recovery_record_sizes
_included_recovery_dict = _included_codec.included_recovery_dict
_included_recovery_exact_keys = _included_codec.included_recovery_exact_keys
_included_recovery_int = _included_codec.included_recovery_int
_included_recovery_compact_int = _included_codec.included_recovery_compact_int
_included_recovery_identity = _included_codec.included_recovery_identity
_included_recovery_compact_identity = _included_codec.included_recovery_compact_identity
_included_recovery_identity_for_format = _included_codec.included_recovery_identity_for_format
_included_recovery_fingerprint = _included_codec.included_recovery_fingerprint
_included_recovery_compact_fingerprint = _included_codec.included_recovery_compact_fingerprint
_included_recovery_sha256 = _included_codec.included_recovery_sha256
_included_recovery_bytes = _included_codec.included_recovery_bytes
_included_windows_recovery_component_is_ambiguous = _included_paths.included_windows_recovery_component_is_ambiguous
_included_recovery_relative_path = _included_paths.included_recovery_relative_path
_included_recovery_tree_entry_path = _included_paths.included_recovery_tree_entry_path
_included_tree_snapshot_from_payload_v1 = _included_codec.included_tree_snapshot_from_payload_v1
_validated_included_tree_snapshot = _included_metadata.validated_included_tree_snapshot
_included_tree_snapshot_from_payload_v2 = _included_codec.included_tree_snapshot_from_payload_v2
_included_tree_snapshot_from_payload = _included_codec.included_tree_snapshot_from_payload
_included_registry_snapshot_from_payload_v1 = _included_codec.included_registry_snapshot_from_payload_v1
_included_registry_snapshot_from_payload_v2 = _included_codec.included_registry_snapshot_from_payload_v2
_included_registry_snapshot_from_payload = _included_codec.included_registry_snapshot_from_payload
_included_recovery_token = _included_paths.included_recovery_token
_included_recovery_managed_name = _included_paths.included_recovery_managed_name
_included_recovery_journal_from_payload = _included_codec.included_recovery_journal_from_payload
_verify_included_bounded_record_size = _included_metadata.verify_included_bounded_record_size
_included_serialized_json_content = _included_codec.included_serialized_json_content
_included_recovery_record_content = _included_codec.included_recovery_record_content
_included_recovery_record_tombstone_path = _included_paths.included_recovery_record_tombstone_path
_included_commit_marker_and_journal_from_payload = _included_codec.included_commit_marker_and_journal_from_payload
_included_cleanup_tombstone_path = _included_paths.included_cleanup_tombstone_path
_included_cleanup_mode_matches = _included_metadata.included_cleanup_mode_matches
_included_cleanup_tombstone_fingerprint_matches = _included_metadata.included_cleanup_tombstone_fingerprint_matches
_included_cleanup_file_receipt_matches = _included_metadata.included_cleanup_file_receipt_matches
_included_stage_marker_matches = _included_codec.included_stage_marker_matches
_included_output_components = _included_paths.included_output_components
_included_output_state_at = _included_metadata.included_output_state_at
_verify_included_output_state_at = _included_metadata.verify_included_output_state_at
_included_output_state = _included_metadata.included_output_state
_verify_included_output_state = _included_metadata.verify_included_output_state


_IncludedWorkerItem = TypeVar("_IncludedWorkerItem")
_IncludedWorkerResult = TypeVar("_IncludedWorkerResult")


def _run_bounded_included_worker_phase(
    items: Iterable[_IncludedWorkerItem],
    *,
    max_workers: int,
    conversion_running: ConversionRunning,
    submit: Callable[
        [ThreadPoolExecutor, _IncludedWorkerItem],
        Future[_IncludedWorkerResult],
    ],
    consume: Callable[
        [_IncludedWorkerItem, Future[_IncludedWorkerResult]],
        bool,
    ],
) -> bool:
    """Run an Included Files phase with concurrency-proportional bookkeeping."""
    if max_workers < 1:
        raise ValueError("Included Files max_workers must be at least one")

    window_size = max_workers * _included_constants.INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER
    item_iterator = iter(items)
    pending: dict[Future[_IncludedWorkerResult], _IncludedWorkerItem] = {}
    input_exhausted = False
    accepting_work = conversion_running()
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        while accepting_work:
            while not input_exhausted and len(pending) < window_size:
                if not conversion_running():
                    accepting_work = False
                    break
                try:
                    item = next(item_iterator)
                except StopIteration:
                    input_exhausted = True
                    break
                pending[submit(executor, item)] = item

            if not accepting_work or not pending:
                break

            done, _not_done = wait(
                tuple(pending),
                return_when=FIRST_COMPLETED,
            )
            completed = tuple(
                (future, pending[future])
                for future in tuple(pending)
                if future in done
            )
            for future, _item in completed:
                del pending[future]

            for future, item in completed:
                if not consume(item, future):
                    accepting_work = False
                    break
                if not conversion_running():
                    accepting_work = False
                    break

        return accepting_work and input_exhausted and not pending
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)




_DIRECTORY_OPEN_FLAGS = _included_posix.DIRECTORY_OPEN_FLAGS

_WINDOWS_GENERIC_READ = _included_windows.WINDOWS_GENERIC_READ
_WINDOWS_FILE_TRAVERSE = _included_windows.WINDOWS_FILE_TRAVERSE
_WINDOWS_FILE_READ_ATTRIBUTES = _included_windows.WINDOWS_FILE_READ_ATTRIBUTES
_WINDOWS_FILE_SHARE_READ = _included_windows.WINDOWS_FILE_SHARE_READ
_WINDOWS_FILE_SHARE_WRITE = _included_windows.WINDOWS_FILE_SHARE_WRITE
_WINDOWS_FILE_SHARE_DELETE = _included_windows.WINDOWS_FILE_SHARE_DELETE
_WINDOWS_OPEN_EXISTING = _included_windows.WINDOWS_OPEN_EXISTING
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
_WINDOWS_FILE_ATTRIBUTE_NORMAL = _included_windows.WINDOWS_FILE_ATTRIBUTE_NORMAL
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = _included_windows.WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = _included_windows.WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = _included_windows.WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
_WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN = _included_windows.WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN
_WINDOWS_FILE_TYPE_DISK = _included_windows.WINDOWS_FILE_TYPE_DISK
_WINDOWS_FILE_BASIC_INFO_CLASS = _included_windows.WINDOWS_FILE_BASIC_INFO_CLASS
_WINDOWS_FILE_ID_INFO_CLASS = _included_windows.WINDOWS_FILE_ID_INFO_CLASS
_WINDOWS_MOVEFILE_WRITE_THROUGH = _included_windows.WINDOWS_MOVEFILE_WRITE_THROUGH






































































































def _included_stage_container_snapshot(
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
    staged_root_snapshot: _IncludedTreeSnapshot,
    staged_registry_identity: _PathIdentity,
    staged_registry_content: bytes,
) -> _IncludedTreeSnapshot:
    """Bind the complete staged namespace without re-reading payload bodies."""

    metadata = _included_snapshots.capture_included_tree(
        stage_path,
        expected_parent_identity=project_identity,
        include_content=False,
    )
    if metadata.identity != stage_identity:
        raise OSError("Included Files staging container changed")
    marker_path = os.path.join(stage_path, _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME)
    marker_record = _included_records.read_included_recovery_record(
        marker_path,
        stage_identity,
    )
    if marker_record is None or not _included_codec.included_stage_marker_matches(
        marker_record[1],
        project_identity,
        stage_identity,
    ):
        raise OSError("Included Files staging ownership marker changed")
    marker_content = _included_codec.included_recovery_record_content(marker_record[1])
    expected_file_hashes = {
        _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME: hashlib.sha256(
            marker_content
        ).hexdigest(),
        "gml_included_file_registry.gd": hashlib.sha256(
            staged_registry_content
        ).hexdigest(),
        **{
            _included_constants.INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path:
                entry.content_sha256
            for entry in staged_root_snapshot.entries
            if entry.kind == "file" and entry.content_sha256 is not None
        },
    }
    expected_directories = {
        _included_constants.INCLUDED_FILES_ROOT_NAME,
        *(
            _included_constants.INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
            for entry in staged_root_snapshot.entries
            if entry.kind == "directory"
        ),
    }
    actual_files = {
        entry.relative_path
        for entry in metadata.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in metadata.entries
        if entry.kind == "directory"
    }
    if actual_files != set(expected_file_hashes) or actual_directories != expected_directories:
        raise OSError("Included Files staging container inventory changed")
    entries: list[_IncludedTreeEntry] = []
    for entry in metadata.entries:
        if entry.kind == "file" and entry.fingerprint[5] != 1:
            raise OSError(
                "Included Files staging file has multiple hard links: "
                + entry.relative_path
            )
        if (
            entry.relative_path == _included_constants.INCLUDED_FILES_ROOT_NAME
            and entry.fingerprint[:2] != staged_root_snapshot.identity
        ):
            raise OSError("Included Files staging root identity changed")
        if (
            entry.relative_path == "gml_included_file_registry.gd"
            and entry.fingerprint[:2] != staged_registry_identity
        ):
            raise OSError("Included File staging registry identity changed")
        entries.append(
            _IncludedTreeEntry(
                relative_path=entry.relative_path,
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=(
                    expected_file_hashes[entry.relative_path]
                    if entry.kind == "file"
                    else None
                ),
            )
        )
    return _IncludedTreeSnapshot(
        root_fingerprint=metadata.root_fingerprint,
        entries=tuple(entries),
    )




def _before_included_registry_directory_binding_check(
    _project_fd: int,
    _registry_directory_name: str,
) -> None:
    """Narrow test seam after securely creating the registry directory."""








def _verify_included_stage_container(
    project_path: str,
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
) -> None:
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    expected_parent = os.path.normcase(os.path.abspath(project_path))
    actual_parent = os.path.normcase(
        os.path.dirname(os.path.abspath(stage_path))
    )
    if actual_parent != expected_parent:
        raise OSError("Included Files staging directory escaped the Godot project")
    try:
        current_stage_identity = _included_snapshots.included_directory_identity(stage_path)
    except OSError as error:
        raise OSError(
            "Refusing redirected or non-directory Included Files staging "
            f"path: {stage_path}"
        ) from error
    if current_stage_identity != stage_identity:
        raise OSError("Included Files staging directory changed during conversion")
    _included_snapshots.verify_included_project_identity(project_path, project_identity)


def _write_included_stage_marker(
    project_path: str,
    project_identity: _PathIdentity,
    stage_path: str,
    stage_identity: _PathIdentity,
) -> None:
    marker_path = os.path.join(stage_path, _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME)
    content = _included_codec.included_recovery_record_content(
        {
            "format_version": _included_constants.INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": _included_codec.included_identity_payload(project_identity),
            "stage_identity": _included_codec.included_identity_payload(stage_identity),
        }
    )
    file_descriptor = os.open(
        marker_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    marker_stat = os.fstat(file_descriptor)
    marker_identity = (marker_stat.st_dev, marker_stat.st_ino)
    try:
        with os.fdopen(file_descriptor, "wb") as marker_file:
            file_descriptor = -1
            marker_file.write(content)
            marker_file.flush()
            os.fsync(marker_file.fileno())
        marker_state = _included_snapshots.included_regular_file_state(
            marker_path,
            expected_parent_identity=stage_identity,
            allowed_identities=frozenset({marker_identity}),
        )
        if marker_state is None or marker_state[2] != content:
            raise OSError("Included Files staging ownership marker changed")
        _included_fs.sync_directory(stage_path, stage_identity)
        _included_fs.sync_directory(project_path, project_identity)
        _verify_included_stage_container(
            project_path,
            project_identity,
            stage_path,
            stage_identity,
        )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _create_included_output_stage(
    project_path: str,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity]:
    _included_snapshots.verify_included_project_identity(project_path, project_identity)
    if _included_fs.descriptor_paths_supported():
        project_fd = _included_fs.open_pinned_directory(project_path)
        stage_name = ""
        stage_identity: _PathIdentity | None = None
        try:
            _included_metadata.verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            for _attempt in range(100):
                candidate = (
                    _included_constants.INCLUDED_FILES_STAGE_PREFIX
                    + secrets.token_hex(8)
                    + ".stage"
                )
                try:
                    os.mkdir(candidate, 0o700, dir_fd=project_fd)
                except FileExistsError:
                    continue
                stage_name = candidate
                break
            if not stage_name:
                raise OSError("Could not allocate Included Files staging directory")
            stage_fd = os.open(
                stage_name,
                _included_posix.DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                stage_identity = _included_metadata.directory_identity_from_fd(stage_fd)
            finally:
                os.close(stage_fd)
            stage_stat = _included_metadata.included_entry_stat_at(project_fd, stage_name)
            if (
                stage_stat is None
                or not stat.S_ISDIR(stage_stat.st_mode)
                or (stage_stat.st_dev, stage_stat.st_ino) != stage_identity
            ):
                raise OSError("Included Files staging directory changed after creation")
            _included_metadata.verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            if _included_snapshots.included_directory_identity(project_path) != project_identity:
                raise OSError(
                    "Godot project root changed during Included Files staging"
                )
            stage_path = os.path.join(project_path, stage_name)
            _write_included_stage_marker(
                project_path,
                project_identity,
                stage_path,
                stage_identity,
            )
            return stage_path, stage_identity
        except BaseException:
            if stage_name and stage_identity is not None:
                try:
                    _included_mutations.remove_owned_included_tree(
                        os.path.join(project_path, stage_name),
                        stage_identity,
                        expected_parent_identity=project_identity,
                    )
                except OSError:
                    pass
            raise
        finally:
            os.close(project_fd)

    stage_path = ""
    for _attempt in range(100):
        candidate_path = os.path.join(
            project_path,
            _included_constants.INCLUDED_FILES_STAGE_PREFIX
            + secrets.token_hex(8)
            + ".stage",
        )
        try:
            os.mkdir(candidate_path, 0o700)
        except FileExistsError:
            continue
        stage_path = candidate_path
        break
    if not stage_path:
        raise OSError("Could not allocate Included Files staging directory")
    stage_identity = _included_snapshots.included_directory_identity(stage_path)
    if stage_identity is None:
        raise OSError("Included Files staging directory disappeared")
    try:
        _included_snapshots.verify_included_project_identity(project_path, project_identity)
        stage_parent_identity = _included_snapshots.included_directory_identity(
            os.path.dirname(stage_path)
        )
        if stage_parent_identity != project_identity:
            raise OSError("Included Files staging directory escaped the Godot project")
        _write_included_stage_marker(
            project_path,
            project_identity,
            stage_path,
            stage_identity,
        )
    except Exception:
        try:
            _included_mutations.remove_owned_included_tree(
                stage_path,
                stage_identity,
                expected_parent_identity=project_identity,
            )
        except OSError:
            pass
        raise
    return stage_path, stage_identity
















































def _sync_included_tree_directories_bottom_up(
    root_path: str,
    snapshot: _IncludedTreeSnapshot,
    expected_parent_identity: _PathIdentity,
) -> None:
    """Durably bind every recorded tree namespace before committing it."""

    root_identity = snapshot.identity
    if root_identity is None:
        raise OSError("Cannot sync an absent Included Files generation")
    _included_snapshots.verify_included_tree_snapshot_metadata(
        root_path,
        snapshot,
        expected_parent_identity=expected_parent_identity,
    )
    directories = sorted(
        (entry for entry in snapshot.entries if entry.kind == "directory"),
        key=lambda entry: (
            entry.relative_path.count("/"),
            entry.relative_path,
        ),
        reverse=True,
    )
    for entry in directories:
        _included_fs.sync_directory(
            _included_paths.included_recovery_tree_entry_path(
                root_path,
                entry.relative_path,
            ),
            entry.fingerprint[:2],
        )
    _included_fs.sync_directory(root_path, root_identity)
    _included_snapshots.verify_included_tree_snapshot_metadata(
        root_path,
        snapshot,
        expected_parent_identity=expected_parent_identity,
    )




def _prepare_included_registry_directory(
    project_path: str,
    expected: _IncludedRegistrySnapshot,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity, bool]:
    registry_directory = os.path.dirname(_included_paths.included_registry_path(project_path))
    current_identity = _included_snapshots.included_directory_identity(registry_directory)
    if expected.directory_identity is not None:
        if current_identity != expected.directory_identity:
            raise OSError("Included File registry directory changed during conversion")
        return registry_directory, expected.directory_identity, False
    if current_identity is not None:
        raise OSError("Included File registry directory appeared during conversion")
    if _included_fs.descriptor_paths_supported():
        project_fd = _included_fs.open_pinned_directory(project_path)
        try:
            _included_metadata.verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
            registry_name = os.path.basename(registry_directory)
            os.mkdir(registry_name, 0o755, dir_fd=project_fd)
            registry_fd = os.open(
                registry_name,
                _included_posix.DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                created_identity = _included_metadata.directory_identity_from_fd(registry_fd)
            finally:
                os.close(registry_fd)
            _before_included_registry_directory_binding_check(
                project_fd,
                registry_name,
            )
            registry_stat = _included_metadata.included_entry_stat_at(project_fd, registry_name)
            if (
                registry_stat is None
                or not stat.S_ISDIR(registry_stat.st_mode)
                or (registry_stat.st_dev, registry_stat.st_ino)
                != created_identity
            ):
                raise OSError(
                    "Included File registry directory changed after creation"
                )
        finally:
            os.close(project_fd)
    else:
        project_ancestors = _included_snapshots.capture_fallback_directory_ancestors(project_path)
        if project_ancestors[-1][1] != project_identity:
            raise OSError(
                "Godot project root changed before registry directory creation"
            )
        os.mkdir(registry_directory, 0o755)
        _included_snapshots.verify_fallback_directory_ancestors(project_ancestors)
        created_identity = _included_snapshots.included_directory_identity(registry_directory)
        if created_identity is None:
            raise OSError(
                "Included File registry directory disappeared after creation"
            )
    visible_identity = _included_snapshots.included_directory_identity(registry_directory)
    if visible_identity != created_identity:
        raise OSError(
            "Included File registry directory changed after secure creation"
        )
    if (
        _included_snapshots.included_regular_file_state(
            _included_paths.included_registry_path(project_path),
            expected_parent_identity=created_identity,
            allowed_identities=frozenset(),
        )
        is not None
    ):
        raise OSError("Included File registry appeared during directory creation")
    return registry_directory, created_identity, True


def _after_included_lock_initialization_phase(_phase: str) -> None:
    """Narrow test seam around durable project-lock initialization."""


def _write_included_lock_initialization_temporary(file_descriptor: int) -> None:
    midpoint = len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) // 2
    chunks = (
        _included_constants.INCLUDED_FILES_LOCK_CONTENT[:midpoint],
        _included_constants.INCLUDED_FILES_LOCK_CONTENT[midpoint:],
    )
    for index, chunk in enumerate(chunks):
        pending = memoryview(chunk)
        while pending:
            written = os.write(file_descriptor, pending)
            if written <= 0:
                raise OSError("Could not initialize Included Files transaction lock")
            pending = pending[written:]
        if index == 0:
            _after_included_lock_initialization_phase("temporary-partially-written")
    _after_included_lock_initialization_phase("temporary-written")
    os.fsync(file_descriptor)


def _remove_exact_included_lock_initialization_temporary(
    path: str,
    expected_identity: _PathIdentity,
    project_identity: _PathIdentity,
) -> None:
    state = _included_records.included_lock_initialization_record_state(
        path,
        project_identity,
        allowed_identities=frozenset({expected_identity}),
    )
    if state is None:
        return
    current_stat = os.lstat(path)
    if (
        (current_stat.st_dev, current_stat.st_ino) != expected_identity
        or current_stat.st_nlink != 1
        or state[2] != _included_constants.INCLUDED_FILES_LOCK_CONTENT
    ):
        return

    name = os.path.basename(path)
    initialization_token: str | None = None
    cleanup_token: str | None = None
    try:
        _included_paths.included_recovery_managed_name(
            name,
            prefix=_included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX,
            suffix=".tmp",
            label="lock initialization temporary",
        )
        initialization_token = name[
            len(_included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX) : -len(".tmp")
        ]
    except OSError:
        try:
            _included_paths.included_recovery_managed_name(
                name,
                prefix=_included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX,
                suffix=".tmp",
                label="lock initialization cleanup tombstone",
            )
            cleanup_token = name[
                len(_included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX) : -len(".tmp")
            ]
        except OSError:
            return

    parent_path = os.path.dirname(path)
    if cleanup_token is not None:
        initialization_path = os.path.join(
            parent_path,
            _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX + cleanup_token + ".tmp",
        )
        if os.path.lexists(initialization_path):
            return
        tombstone_path = path
    else:
        assert initialization_token is not None
        tombstone_path = os.path.join(
            parent_path,
            _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
            + initialization_token
            + ".tmp",
        )
        if os.path.lexists(tombstone_path):
            return
        _included_mutations.move_exact_included_file(
            path,
            tombstone_path,
            expected_identity,
            source_parent_identity=project_identity,
            destination_parent_identity=project_identity,
        )
        _included_fs.sync_directory(parent_path, project_identity)
        _after_included_lock_initialization_phase("temporary-cleanup-quarantined")

    tombstone_state = _included_records.included_lock_initialization_record_state(
        tombstone_path,
        project_identity,
        allowed_identities=frozenset({expected_identity}),
    )
    if (
        tombstone_state is None
        or tombstone_state[2] != _included_constants.INCLUDED_FILES_LOCK_CONTENT
    ):
        return
    _included_cleanup.remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        project_identity,
        expect_directory=False,
    )
    _after_included_lock_initialization_phase("temporary-cleanup-removed")


def _cleanup_included_lock_initialization_temporaries(
    project_path: str,
    project_identity: _PathIdentity,
) -> None:
    for name in sorted(os.listdir(project_path)):
        managed = False
        for prefix, label in (
            (
                _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX,
                "lock initialization temporary",
            ),
            (
                _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX,
                "lock initialization cleanup tombstone",
            ),
        ):
            try:
                _included_paths.included_recovery_managed_name(
                    name,
                    prefix=prefix,
                    suffix=".tmp",
                    label=label,
                )
            except OSError:
                continue
            managed = True
            break
        if not managed:
            continue
        candidate_path = os.path.join(project_path, name)
        try:
            state = _included_records.included_lock_initialization_record_state(
                candidate_path,
                project_identity,
            )
            if state is None or state[2] != _included_constants.INCLUDED_FILES_LOCK_CONTENT:
                continue
            _remove_exact_included_lock_initialization_temporary(
                candidate_path,
                state[0],
                project_identity,
            )
        except OSError:
            # Partial, redirected, aliased, or concurrently changed candidates are
            # not sufficient evidence of converter ownership and stay untouched.
            continue


def _initialize_included_project_lock(
    project_path: str,
    project_identity: _PathIdentity,
    *,
    project_fd: int,
) -> None:
    lock_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_LOCK_NAME)
    file_descriptor = -1
    temporary_path = ""
    temporary_identity: _PathIdentity | None = None
    for _attempt in range(100):
        temporary_name = (
            _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX + secrets.token_hex(8) + ".tmp"
        )
        candidate_path = os.path.join(project_path, temporary_name)
        try:
            temporary_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            if project_fd >= 0:
                file_descriptor = os.open(
                    temporary_name,
                    temporary_flags,
                    0o600,
                    dir_fd=project_fd,
                )
            else:
                file_descriptor = os.open(
                    candidate_path,
                    temporary_flags,
                    0o600,
                )
        except FileExistsError:
            continue
        temporary_path = candidate_path
        temporary_stat = os.fstat(file_descriptor)
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        break
    if file_descriptor < 0 or not temporary_path or temporary_identity is None:
        raise OSError("Could not allocate Included Files lock initialization record")

    temporary_pending = True
    try:
        try:
            _after_included_lock_initialization_phase("temporary-created")
            _write_included_lock_initialization_temporary(file_descriptor)
            os.close(file_descriptor)
            file_descriptor = -1
            temporary_state = _included_records.included_lock_initialization_record_state(
                temporary_path,
                project_identity,
                allowed_identities=frozenset({temporary_identity}),
            )
            if (
                temporary_state is None
                or temporary_state[2] != _included_constants.INCLUDED_FILES_LOCK_CONTENT
            ):
                raise OSError("Included Files lock initialization record changed")
            _included_fs.sync_directory(project_path, project_identity)
            _after_included_lock_initialization_phase("temporary-synced")
            _included_mutations.move_exact_included_file(
                temporary_path,
                lock_path,
                temporary_identity,
                source_parent_identity=project_identity,
                destination_parent_identity=project_identity,
            )
            temporary_pending = False
            _included_fs.sync_directory(project_path, project_identity)
            _after_included_lock_initialization_phase("temporary-published")
        except OSError:
            # A competing initializer may have atomically published the complete
            # stable record first. The caller opens and validates that winner.
            stable_exists = (
                _included_metadata.included_entry_stat_at(project_fd, _included_constants.INCLUDED_FILES_LOCK_NAME)
                is not None
                if project_fd >= 0
                else os.path.lexists(lock_path)
            )
            if not stable_exists:
                raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _remove_exact_included_lock_initialization_temporary(
                    temporary_path,
                    temporary_identity,
                    project_identity,
                )
            except OSError:
                pass


def _acquire_included_project_lock(
    project_path: str,
    project_identity: _PathIdentity,
) -> _IncludedProjectLock:
    """Acquire the cooperative lock that serializes recovery and publication."""

    lock_path = os.path.join(project_path, _included_constants.INCLUDED_FILES_LOCK_NAME)
    flags = (
        os.O_RDWR
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    project_fd = -1
    descriptor_bound = _included_fs.descriptor_paths_supported()
    if descriptor_bound:
        project_fd = _included_fs.open_pinned_directory(project_path)
        try:
            _included_metadata.verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
        except BaseException:
            os.close(project_fd)
            raise

    def open_lock(open_flags: int, mode: int = 0o600) -> int:
        if descriptor_bound:
            return os.open(
                _included_constants.INCLUDED_FILES_LOCK_NAME,
                open_flags,
                mode,
                dir_fd=project_fd,
            )
        return os.open(lock_path, open_flags, mode)

    def lock_lstat() -> os.stat_result:
        if descriptor_bound:
            return os.stat(
                _included_constants.INCLUDED_FILES_LOCK_NAME,
                dir_fd=project_fd,
                follow_symlinks=False,
            )
        return os.lstat(lock_path)

    try:
        try:
            file_descriptor = open_lock(flags)
        except FileNotFoundError:
            _initialize_included_project_lock(
                project_path,
                project_identity,
                project_fd=project_fd,
            )
            file_descriptor = open_lock(flags)
    except BaseException:
        if project_fd >= 0:
            os.close(project_fd)
        raise

    windows = os.name == "nt"
    locked = False
    try:
        opened_stat = os.fstat(file_descriptor)
        path_stat = lock_lstat()
        if (
            _included_fs.output_path_is_redirected(lock_path, path_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or not os.path.samestat(opened_stat, path_stat)
            or opened_stat.st_nlink != 1
        ):
            raise OSError(
                "Refusing redirected or aliased Included Files transaction lock: "
                + lock_path
            )
        if windows:
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            try:
                _included_fs.windows_file_locking(file_descriptor, 2)
            except OSError as error:
                raise OSError(
                    "Another GM2Godot conversion is already publishing or "
                    f"recovering Included Files in {project_path}"
                ) from error
            locked = True
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        initial_content = os.read(
            file_descriptor,
            len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) + 1,
        )
        if initial_content != _included_constants.INCLUDED_FILES_LOCK_CONTENT:
            raise OSError(
                "Refusing an unknown or incomplete file at the reserved Included "
                f"Files transaction lock path: {lock_path}"
            )
        if not windows:
            os.lseek(file_descriptor, 0, os.SEEK_SET)
            try:
                import fcntl

                fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise OSError(
                    "Another GM2Godot conversion is already publishing or "
                    f"recovering Included Files in {project_path}"
                ) from error
            locked = True

        os.lseek(file_descriptor, 0, os.SEEK_SET)
        current_content = os.read(
            file_descriptor,
            len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) + 1,
        )
        if current_content != _included_constants.INCLUDED_FILES_LOCK_CONTENT:
            raise OSError(
                "Included Files transaction lock changed after acquisition: "
                + lock_path
            )
        _included_snapshots.verify_included_project_identity(project_path, project_identity)
        if descriptor_bound:
            _included_metadata.verify_included_directory_fd(
                project_fd,
                project_identity,
                project_path,
            )
        final_stat = lock_lstat()
        if (
            _included_fs.output_path_is_redirected(lock_path, final_stat)
            or not os.path.samestat(os.fstat(file_descriptor), final_stat)
        ):
            raise OSError(f"Included Files transaction lock changed: {lock_path}")
        _cleanup_included_lock_initialization_temporaries(
            project_path,
            project_identity,
        )
        project_lock = _IncludedProjectLock(
            file_descriptor=file_descriptor,
            path=lock_path,
            windows=windows,
        )
        if project_fd >= 0:
            os.close(project_fd)
        return project_lock
    except BaseException:
        if locked:
            try:
                if windows:
                    os.lseek(file_descriptor, 0, os.SEEK_SET)
                    _included_fs.windows_file_locking(file_descriptor, 0)
                else:
                    import fcntl

                    fcntl.flock(file_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(file_descriptor)
        if project_fd >= 0:
            os.close(project_fd)
        raise


def _release_included_project_lock(project_lock: _IncludedProjectLock) -> None:
    try:
        if project_lock.windows:
            os.lseek(project_lock.file_descriptor, 0, os.SEEK_SET)
            _included_fs.windows_file_locking(project_lock.file_descriptor, 0)
        else:
            import fcntl

            fcntl.flock(project_lock.file_descriptor, fcntl.LOCK_UN)
    finally:
        os.close(project_lock.file_descriptor)














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
                _remove_included_recovery_record(
                    temporary_path,
                    temporary_identity,
                    project_path,
                    project_identity,
                )
            except OSError:
                pass






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
        _verify_included_commit_marker_generation(project_path, marker)
    return identity














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
        _remove_included_recovery_record(
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
        _remove_included_recovery_record(
            record_path,
            record_identity,
            project_path,
            project_identity,
        )
        cleaned += 1
    return cleaned, tuple(warnings)


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
    journal_promoted, promotion_warnings = _promote_included_journal_temporary(
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
            _verify_included_commit_marker_generation(project_path, marker)
            cleanup_errors, cleanup_warnings = (
                _cleanup_committed_included_output_set(embedded_journal)
            )
            if cleanup_errors:
                error = OSError(
                    "Committed Included Files marker-only recovery could not "
                    "finish cleanup"
                )
                for cleanup_error in cleanup_errors:
                    error.add_note(str(cleanup_error))
                raise error
            _remove_included_recovery_record(
                commit_record_path,
                commit_identity,
                project_path,
                project_identity,
            )
            messages.append(
                "finalized an already committed Included Files generation"
            )
            messages.extend(cleanup_warnings)
        orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
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
        rollback_errors = _rollback_included_output_set(
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
        _remove_included_recovery_record(
            journal_record_path,
            journal_identity,
            project_path,
            project_identity,
        )
        orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
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

    cleanup_errors, cleanup_warnings = _cleanup_committed_included_output_set(
        journal
    )
    if cleanup_errors:
        error = OSError(
            "Committed Included Files generation recovery could not finish cleanup"
        )
        for cleanup_error in cleanup_errors:
            error.add_note(str(cleanup_error))
        raise error
    _remove_included_recovery_record(
        journal_record_path,
        journal_identity,
        project_path,
        project_identity,
    )
    _included_phases.after_included_transaction_phase("recovery-journal-removed")
    _remove_included_recovery_record(
        commit_record_path,
        commit_identity,
        project_path,
        project_identity,
    )
    orphan_count, orphan_warnings = _cleanup_orphan_included_recovery_state(
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
        _verify_included_stage_container(
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
        ) = _prepare_included_registry_directory(
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
        journal_identity = _publish_included_recovery_record(
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
        _sync_included_tree_directories_bottom_up(
            final_root_path,
            transaction.staged_root_snapshot,
            transaction.project_identity,
        )
        journal_identity = _verify_included_published_journal(
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
            _before_included_changed_generation_final_validation()
            for content_receipt in transaction.content_receipts:
                _included_snapshots.verify_included_generation_source_receipt(
                    content_receipt.source,
                    validate_content=True,
                )
        _verify_included_commit_marker_generation(
            project_path,
            _included_codec.included_commit_marker_from_journal(recovery_journal),
        )
        _verify_included_stage_container(
            project_path,
            transaction.project_identity,
            transaction.stage_container_path,
            transaction.stage_container_identity,
        )
        commit_marker_identity = _publish_included_recovery_record(
            project_path,
            transaction.project_identity,
            filename=_included_constants.INCLUDED_FILES_COMMIT_NAME,
            temporary_prefix=_included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX,
            payload=_included_codec.included_commit_marker_payload(recovery_journal),
            staged_phase="commit-record-staged",
        )
        _included_phases.after_included_transaction_phase("generation-committed")
        commit_marker_identity = _verify_included_published_commit_marker(
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
                        _verify_included_published_commit_marker(
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
        rollback_errors = _rollback_included_output_set(
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
                    journal_identity = _verify_included_published_journal(
                        project_path,
                        transaction.project_identity,
                        recovery_journal,
                        journal_identity,
                    )
                    _remove_included_recovery_record(
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

    cleanup_errors, cleanup_warnings = _cleanup_committed_included_output_set(
        recovery_journal,
        verify_content=False,
    )
    if cleanup_errors:
        return tuple(str(cleanup_error) for cleanup_error in cleanup_errors)

    try:
        commit_marker_identity = _verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _remove_included_recovery_record(
            journal_path,
            journal_identity,
            project_path,
            transaction.project_identity,
        )
        _included_phases.after_included_transaction_phase("journal-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))

    try:
        commit_marker_identity = _verify_included_published_commit_marker(
            project_path,
            transaction.project_identity,
            recovery_journal,
            commit_marker_identity,
            verify_generation=False,
        )
        _remove_included_recovery_record(
            commit_path,
            commit_marker_identity,
            project_path,
            transaction.project_identity,
        )
        _included_phases.after_included_transaction_phase("commit-marker-removed")
    except OSError as cleanup_error:
        return (*cleanup_warnings, str(cleanup_error))
    return cleanup_warnings


def _ensure_included_output_project_root(project_path: str) -> tuple[int, int]:
    os.makedirs(project_path, exist_ok=True)
    project_stat = os.lstat(project_path)
    if (
        _included_fs.output_path_is_redirected(project_path, project_stat)
        or not stat.S_ISDIR(project_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected Included File output root: {project_path}"
        )
    return (project_stat.st_dev, project_stat.st_ino)






def _verify_open_included_output_directory(
    project_path: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Included File output directory changed: {directory_path}"
        ) from error
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_real = os.path.normcase(os.path.realpath(directory_path))
    try:
        contained = (
            os.path.commonpath((project_real, directory_real))
            == project_real
        )
    except ValueError:
        contained = False
    if (
        _included_fs.output_path_is_redirected(directory_path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected Included File output directory: {directory_path}"
        )




def _read_included_payload_chunk(source_file: BinaryIO) -> bytes:
    return source_file.read(1024 * 1024)


def _copy_included_payload(
    source_file: BinaryIO,
    target_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedPayloadReceipt:
    expected_fingerprint = _included_metadata.included_source_fingerprint(source_stat)
    if source_file.tell() != 0:
        raise OSError("GameMaker Included File source did not start at offset zero")
    before_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(before_copy.st_mode)
        or _included_metadata.included_source_fingerprint(before_copy) != expected_fingerprint
    ):
        raise OSError("GameMaker Included File source changed before copying")

    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = _read_included_payload_chunk(source_file)
        if not chunk:
            break
        written = target_file.write(chunk)
        if written != len(chunk):
            raise OSError("Could not write the complete Included File payload")
        digest.update(chunk)
        byte_count += len(chunk)

    after_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(after_copy.st_mode)
        or _included_metadata.included_source_fingerprint(after_copy) != expected_fingerprint
        or byte_count != source_stat.st_size
    ):
        raise OSError("GameMaker Included File source changed while copying")
    streamed_sha256 = digest.hexdigest()
    if expected_receipt is not None:
        if (
            expected_receipt.byte_count != byte_count
            or expected_receipt.sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed after its "
                "planning receipt"
            )
    else:
        source_file.seek(0)
        verified_byte_count, verified_sha256 = _included_snapshots.digest_open_included_file(
            source_file
        )
        after_verification = os.fstat(source_file.fileno())
        if (
            _included_metadata.included_source_fingerprint(after_verification)
            != expected_fingerprint
            or verified_byte_count != byte_count
            or verified_sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed while copying"
            )
    return _IncludedPayloadReceipt(
        source_fingerprint=expected_fingerprint,
        byte_count=byte_count,
        sha256=streamed_sha256,
    )


def _stage_included_output_at(
    directory_fd: int,
    filename: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    verify_directory: Callable[[], None],
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    verify_directory()
    output_identity = _included_metadata.included_output_state_at(directory_fd, filename)
    temporary_name = ""
    file_descriptor = -1
    for _attempt in range(100):
        temporary_name = f".gm2godot-{secrets.token_hex(8)}.tmp"
        try:
            file_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileExistsError:
            continue
    if file_descriptor < 0:
        raise OSError(f"Could not stage Included File output: {filename}")

    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    published_pending = False
    try:
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _included_fs.apply_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        staged_stat = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(f"Included File staging output changed: {filename}")
        verify_directory()
        _included_metadata.verify_included_output_state_at(
            directory_fd,
            filename,
            output_identity,
        )
        verify_directory()
        os.rename(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_pending = False
        published_pending = True
        published_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(f"Included File output changed after publication: {filename}")
        verify_directory()
        published_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            opened_stat = os.fstat(published_fd)
            current_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_metadata.included_path_handle_binding(current_stat)
                != _included_metadata.included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {filename}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_metadata.included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_metadata.included_handle_state(opened_stat),
            )
        finally:
            os.close(published_fd)
        verify_directory()
        published_pending = False
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending and temporary_name:
            try:
                current_stat = os.stat(
                    temporary_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    current_stat.st_dev,
                    current_stat.st_ino,
                ) == temporary_identity:
                    os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        if published_pending:
            try:
                current_stat = os.stat(
                    filename,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISREG(current_stat.st_mode)
                    and (
                        current_stat.st_dev,
                        current_stat.st_ino,
                    )
                    == temporary_identity
                ):
                    os.unlink(filename, dir_fd=directory_fd)
            except OSError:
                pass


def _publish_included_output_at(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    project_fd = os.open(project_path, directory_flags)
    current_fd = project_fd
    try:
        _verify_open_included_output_directory(
            project_path,
            project_path,
            project_fd,
        )
        for component in components[:-1]:
            child_fd = _included_fs.open_or_create_output_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != project_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(project_path, *components[:-1])
        def verify_output_directory() -> None:
            _verify_open_included_output_directory(
                project_path,
                output_directory,
                current_fd,
            )

        verify_output_directory()
        receipt = _stage_included_output_at(
            current_fd,
            components[-1],
            source_file,
            source_stat,
            verify_output_directory,
            expected_receipt,
        )
        verify_output_directory()
        return receipt
    finally:
        if current_fd != project_fd:
            os.close(current_fd)
        os.close(project_fd)


def _prepare_included_output_directories_fallback(
    project_path: str,
    directory_components: tuple[str, ...],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_path = project_path
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in (None, *directory_components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
            try:
                directory_stat = os.lstat(directory_path)
            except FileNotFoundError:
                try:
                    os.mkdir(directory_path)
                except FileExistsError:
                    pass
                directory_stat = os.lstat(directory_path)
        else:
            directory_stat = os.lstat(directory_path)
        directory_real = os.path.normcase(os.path.realpath(directory_path))
        try:
            contained = (
                os.path.commonpath((project_real, directory_real))
                == project_real
            )
        except ValueError:
            contained = False
        if (
            _included_fs.output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not contained
        ):
            raise OSError(
                "Refusing redirected Included File output directory: "
                f"{directory_path}"
            )
        identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return tuple(identities)


def _verify_included_output_directories_fallback(
    identities: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            directory_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            ) from error
        if (
            _included_fs.output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or (directory_stat.st_dev, directory_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            )


def _verify_included_output_stage_fallback(
    staged_path: str,
    expected_identity: tuple[int, int],
    expected_project_identity: tuple[int, int],
) -> None:
    try:
        staged_stat = os.lstat(staged_path)
        parent_path = os.path.dirname(staged_path) or os.curdir
        parent_stat = os.lstat(parent_path)
    except OSError as error:
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        ) from error
    if (
        _included_fs.output_path_is_redirected(staged_path, staged_stat)
        or not stat.S_ISREG(staged_stat.st_mode)
        or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        or _included_fs.output_path_is_redirected(parent_path, parent_stat)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or (parent_stat.st_dev, parent_stat.st_ino)
        != expected_project_identity
    ):
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        )


def _remove_included_output_stage_fallback(
    staged_paths: tuple[str, ...],
    expected_identity: tuple[int, int],
) -> None:
    checked_paths: set[str] = set()
    for staged_path in staged_paths:
        normalized_path = os.path.normcase(os.path.abspath(staged_path))
        if normalized_path in checked_paths:
            continue
        checked_paths.add(normalized_path)
        try:
            staged_stat = os.lstat(staged_path)
        except OSError:
            continue
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        ):
            continue
        try:
            os.unlink(staged_path)
        except PermissionError:
            if os.name != "nt":
                raise
            os.chmod(staged_path, stat.S_IWRITE)
            writable_stat = os.lstat(staged_path)
            if (
                not stat.S_ISREG(writable_stat.st_mode)
                or (writable_stat.st_dev, writable_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Included File staging output changed: {staged_path}"
                )
            os.unlink(staged_path)
        return


def _publish_included_output_fallback(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_identities = _prepare_included_output_directories_fallback(
        project_path,
        components[:-1],
    )
    output_directory = os.path.join(project_path, *components[:-1])
    output_path = os.path.join(output_directory, components[-1])
    output_identity = _included_metadata.included_output_state(output_path)
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=project_path,
        prefix=".gm2godot-",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    resolved_temporary_path = temporary_path
    temporary_pending = True
    try:
        resolved_temporary_path = os.path.realpath(temporary_path)
        _verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        _verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        _verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = _copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _included_fs.apply_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        _verify_included_output_directories_fallback(directory_identities)
        _verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        _included_metadata.verify_included_output_state(output_path, output_identity)
        _verify_included_output_directories_fallback(directory_identities)
        os.replace(resolved_temporary_path, output_path)
        temporary_pending = False
        published_stat = os.lstat(output_path)
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(
                f"Included File output changed after publication: {output_path}"
            )
        with _included_fs.open_validation_stream(
            output_path,
            deny_writes=False,
            no_follow=True,
        ) as published_file:
            opened_stat = os.fstat(published_file.fileno())
            current_stat = os.lstat(output_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_metadata.included_path_handle_binding(current_stat)
                != _included_metadata.included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {output_path}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_metadata.included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_metadata.included_handle_state(opened_stat),
            )
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                _remove_included_output_stage_fallback(
                    (resolved_temporary_path, temporary_path),
                    temporary_identity,
                )
            except OSError:
                pass


def _publish_confined_included_output(
    project_path: str,
    output_path: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    components = _included_paths.included_output_components(project_path, output_path)
    _ensure_included_output_project_root(project_path)
    if _included_fs.confined_output_supported():
        return _publish_included_output_at(
            project_path,
            components,
            source_file,
            source_stat,
            expected_receipt,
        )
    return _publish_included_output_fallback(
        project_path,
        components,
        source_file,
        source_stat,
        expected_receipt,
    )


def _before_included_unchanged_source_revalidation() -> None:
    """Narrow test seam before the second stable source-content pass."""


def _before_included_unchanged_public_revalidation() -> None:
    """Narrow test seam before rehashing the candidate public generation."""


def _before_included_unchanged_final_revalidation() -> None:
    """Narrow test seam before final source and public identity checks."""


def _before_included_changed_generation_final_validation() -> None:
    """Narrow test seam before final receipt-bound content validation."""


class IncludedFilesConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self._active_output_project_path: str | None = None

    def _process_file(
        self,
        gm_file_path: str,
        godot_file_path: str,
        rel_path: str,
        owner_source_path: str = "datafiles",
        planned_receipt: _IncludedNoOpSourceReceipt | None = None,
    ) -> tuple[str, bool, _IncludedCopyReceipt | None] | None:
        if not self.conversion_running():
            return None
        self._resource_requested(rel_path)
        self._resource_started(rel_path)

        try:
            opened_source = self._open_confined_source_file(
                gm_file_path,
                owner_source_path=owner_source_path,
                resource=rel_path,
            )
            if opened_source is None:
                self._resource_failed(rel_path)
                return rel_path, False, None

            source_file, source_stat = opened_source
            with source_file:
                try:
                    if planned_receipt is not None:
                        active_project_path = (
                            self._active_output_project_path
                            or self.godot_project_path
                        )
                        output_components = _included_paths.included_output_components(
                            active_project_path,
                            godot_file_path,
                        )
                        assigned_path = posixpath.join(
                            *output_components[1:]
                        )
                        if (
                            planned_receipt.logical_path != rel_path
                            or planned_receipt.assigned_path != assigned_path
                            or self._capture_pinned_included_source_binding(
                                _IncludedFileSource(
                                    filesystem_path=gm_file_path,
                                    relative_path=rel_path,
                                    owner_source_path=owner_source_path,
                                ),
                                source_file,
                                source_stat,
                            )
                            != planned_receipt.binding
                        ):
                            raise OSError(
                                "GameMaker Included File planning receipt "
                                f"changed before staging: {rel_path}"
                            )
                    if planned_receipt is None:
                        copy_receipt = _publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                        )
                    else:
                        copy_receipt = _publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                            planned_receipt,
                        )
                    if (
                        planned_receipt is not None
                        and self._capture_pinned_included_source_binding(
                            _IncludedFileSource(
                                filesystem_path=gm_file_path,
                                relative_path=rel_path,
                                owner_source_path=owner_source_path,
                            ),
                            source_file,
                            source_stat,
                        )
                        != planned_receipt.binding
                    ):
                        raise OSError(
                            "GameMaker Included File planning receipt changed "
                            f"while staging: {rel_path}"
                        )
                except (OSError, ValueError) as error:
                    self._resource_failed(rel_path)
                    self._report_included_file_output_rejection(
                        rel_path,
                        godot_file_path,
                        error,
                    )
                    return rel_path, False, None
        except Exception:
            self._resource_failed(rel_path)
            raise
        return rel_path, True, copy_receipt

    def _report_included_file_output_rejection(
        self,
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

    def _open_confined_source_file(
        self,
        filesystem_path: str,
        *,
        owner_source_path: str,
        resource: str,
        deny_writes: bool = False,
    ) -> tuple[BinaryIO, os.stat_result] | None:
        """Open a contained regular file and pin it against late path swaps."""
        resolved = self._resolve_discovered_project_source(
            filesystem_path,
            owner_source_path=owner_source_path,
            resource=resource,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            return None

        try:
            source_file = _included_fs.open_validation_stream(
                resolved.filesystem_path,
                deny_writes=deny_writes,
            )
        except OSError:
            return None

        try:
            opened_stat = os.fstat(source_file.fileno())
            revalidated = self._resolve_discovered_project_source(
                resolved.filesystem_path,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="included_file",
                field="discovered datafiles file",
            )
            if revalidated is None:
                source_file.close()
                return None
            current_stat = os.stat(revalidated.filesystem_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
            ):
                source_file.close()
                self._report_source_path_rejection(
                    filesystem_path,
                    ProjectSourcePathError(
                        "Discovered GameMaker source file changed after validation"
                    ),
                    owner_source_path=owner_source_path,
                    resource=resource,
                    resource_type="included_file",
                    field="discovered datafiles file",
                )
                return None
        except OSError:
            source_file.close()
            return None
        return source_file, opened_stat

    def _preflight_included_source_byte_counts(
        self,
        sources: tuple[_IncludedFileSource, ...],
    ) -> dict[str, int]:
        """Capture byte counts without reading or staging payload bodies."""

        byte_counts: dict[str, int] = {}
        for source in sources:
            if not self.conversion_running():
                raise _IncludedOutputSetCancelled()
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    "recovery-record preflight: "
                    + source.relative_path
                )
            source_file, source_stat = opened_source
            with source_file:
                _included_codec.included_recovery_compact_integer_payload(
                    source_stat.st_size,
                    "source byte count",
                )
                byte_counts[source.relative_path] = source_stat.st_size
        return byte_counts

    def _capture_pinned_included_source_binding(
        self,
        source: _IncludedFileSource,
        source_file: BinaryIO,
        expected_stat: os.stat_result,
    ) -> _IncludedSourceBinding:
        resolved = self._resolve_discovered_project_source(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )

        lexical_stat = os.lstat(resolved.filesystem_path)
        path_stat = os.stat(resolved.filesystem_path)
        handle_stat = os.fstat(source_file.fileno())
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(handle_stat.st_mode)
            or not os.path.samestat(expected_stat, path_stat)
            or not os.path.samestat(path_stat, handle_stat)
            or _included_metadata.included_handle_state(handle_stat)
            != _included_metadata.included_handle_state(expected_stat)
            or _included_metadata.included_path_handle_binding(path_stat)
            != _included_metadata.included_path_handle_binding(handle_stat)
        ):
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )
        canonical_path, directory_identities = (
            _included_snapshots.capture_included_source_directory_identities(
                self.gm_project_path,
                resolved.filesystem_path,
            )
        )
        _included_snapshots.verify_fallback_directory_ancestors(directory_identities)
        return _IncludedSourceBinding(
            filesystem_path=os.path.normcase(
                os.path.abspath(resolved.filesystem_path)
            ),
            canonical_path=canonical_path,
            directory_identities=directory_identities,
            lexical_state=_included_metadata.included_handle_state(lexical_stat),
            path_state=_included_metadata.included_handle_state(path_stat),
            handle_state=_included_metadata.included_handle_state(handle_stat),
        )

    def _capture_unchanged_source_receipt(
        self,
        source: _IncludedFileSource,
        *,
        deny_writes: bool,
    ) -> _IncludedNoOpSourceReceipt:
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        opened_source = self._open_confined_source_file(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            deny_writes=deny_writes,
        )
        if opened_source is None:
            raise OSError(
                "GameMaker Included File source became unavailable during "
                f"unchanged-generation validation: {source.relative_path}"
            )
        source_file, source_stat = opened_source
        with source_file:
            if source_file.tell() != 0:
                raise OSError(
                    "GameMaker Included File validation stream did not start "
                    f"at offset zero: {source.relative_path}"
                )
            before_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            byte_count, sha256 = _included_snapshots.digest_open_included_file(source_file)
            after_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            if (
                after_binding != before_binding
                or byte_count != source_stat.st_size
            ):
                raise OSError(
                    "GameMaker Included File source changed while validating "
                    f"an unchanged generation: {source.relative_path}"
                )
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        return _IncludedNoOpSourceReceipt(
            logical_path=source.relative_path,
            assigned_path="",
            binding=before_binding,
            byte_count=byte_count,
            sha256=sha256,
        )

    def _collect_unchanged_source_receipts(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        *,
        deny_writes: bool,
    ) -> dict[str, _IncludedNoOpSourceReceipt]:
        receipts: dict[str, _IncludedNoOpSourceReceipt] = {}

        def submit_receipt(
            executor: ThreadPoolExecutor,
            source: _IncludedFileSource,
        ) -> Future[_IncludedNoOpSourceReceipt]:
            return executor.submit(
                self._capture_unchanged_source_receipt,
                source,
                deny_writes=deny_writes,
            )

        def consume_receipt(
            source: _IncludedFileSource,
            future: Future[_IncludedNoOpSourceReceipt],
        ) -> bool:
            receipts[source.relative_path] = replace(
                future.result(),
                assigned_path=assignments_by_source[
                    source.relative_path
                ].assigned_output_path,
            )
            return True

        phase_completed = _run_bounded_included_worker_phase(
            sources,
            max_workers=self.max_workers,
            conversion_running=self.conversion_running,
            submit=submit_receipt,
            consume=consume_receipt,
        )
        if not phase_completed:
            raise _IncludedOutputSetCancelled()
        return receipts

    def _revalidate_unchanged_source_bindings(
        self,
        sources: tuple[_IncludedFileSource, ...],
        receipts: dict[str, _IncludedNoOpSourceReceipt],
    ) -> None:
        for source in sources:
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
                deny_writes=True,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    f"final unchanged-generation validation: {source.relative_path}"
                )
            source_file, source_stat = opened_source
            with source_file:
                current_binding = self._capture_pinned_included_source_binding(
                    source,
                    source_file,
                    source_stat,
                )
            if current_binding != receipts[source.relative_path].binding:
                raise OSError(
                    "GameMaker Included File source changed during final "
                    f"unchanged-generation validation: {source.relative_path}"
                )

    def _unchanged_included_generation_matches(
        self,
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

        _before_included_unchanged_source_revalidation()
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

        _before_included_unchanged_public_revalidation()
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

        _before_included_unchanged_final_revalidation()
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

    def _list_confined_directory(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> tuple[str, ...] | None:
        """List a contained directory without following a late path swap."""
        revalidated = self._resolve_discovered_project_source(
            directory.filesystem_path,
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )
        if revalidated is None:
            return None

        # On POSIX, list through a validated directory descriptor. If the path
        # is exchanged after validation, the descriptor remains bound to the
        # original contained directory. Other platforms get a before/after
        # identity check around their path-based directory listing.
        if os.listdir in os.supports_fd and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            try:
                directory_fd = os.open(revalidated.filesystem_path, flags)
            except OSError:
                return None
            try:
                opened_stat = os.fstat(directory_fd)
                current = self._resolve_discovered_project_source(
                    revalidated.filesystem_path,
                    owner_source_path=directory.source_path,
                    resource=posixpath.basename(directory.source_path),
                    resource_type="included_file",
                    field="discovered datafiles directory",
                )
                if current is None:
                    return None
                current_stat = os.stat(current.filesystem_path)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or not os.path.samestat(opened_stat, current_stat)
                ):
                    self._report_directory_swap(directory)
                    return None
                return tuple(sorted(os.listdir(directory_fd)))
            except OSError:
                return None
            finally:
                os.close(directory_fd)

        try:
            before_stat = os.stat(revalidated.filesystem_path)
            entries = tuple(sorted(os.listdir(revalidated.filesystem_path)))
            current = self._resolve_discovered_project_source(
                revalidated.filesystem_path,
                owner_source_path=directory.source_path,
                resource=posixpath.basename(directory.source_path),
                resource_type="included_file",
                field="discovered datafiles directory",
            )
            if current is None:
                return None
            after_stat = os.stat(current.filesystem_path)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(before_stat.st_mode)
            or not os.path.samestat(before_stat, after_stat)
        ):
            self._report_directory_swap(directory)
            return None
        return entries

    def _report_directory_swap(
        self,
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

    def _collect_included_files(
        self,
        datafiles: ResolvedProjectSourcePath,
    ) -> list[_IncludedFileSource]:
        included_files: list[_IncludedFileSource] = []
        pending_directories = [datafiles]
        visited_directories: set[str] = set()

        while pending_directories:
            directory = pending_directories.pop()
            canonical_directory = os.path.normcase(
                os.path.realpath(directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            entry_names = self._list_confined_directory(directory)
            if entry_names is None:
                continue
            for entry_name in entry_names:
                entry = self._resolve_discovered_project_source(
                    os.path.join(directory.filesystem_path, entry_name),
                    owner_source_path=directory.source_path,
                    resource=entry_name,
                    resource_type="included_file",
                    field="discovered datafiles entry",
                )
                if entry is None:
                    continue
                if os.path.isdir(entry.filesystem_path):
                    # Match os.walk's historical default: contained directory
                    # symlinks are not traversed, while the datafiles root itself
                    # may still be a contained symlink.
                    if not os.path.islink(entry.filesystem_path):
                        pending_directories.append(entry)
                    continue
                if entry_name.endswith(".yy") or not os.path.isfile(
                    entry.filesystem_path
                ):
                    continue
                relative_path = posixpath.relpath(
                    entry.source_path,
                    datafiles.source_path,
                )
                included_files.append(
                    _IncludedFileSource(
                        filesystem_path=entry.filesystem_path,
                        relative_path=relative_path,
                        owner_source_path=directory.source_path,
                    )
                )
        return sorted(included_files, key=lambda item: item.relative_path)

    def _included_file_conversion_plan(self) -> _IncludedFileConversionPlan:
        """Plan logical included files before filtering unavailable sources."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="included_file",
        )
        malformed = any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        )
        manifest_declares_included_files = (
            "IncludedFiles" in manifest.raw_data
            or "includedFiles" in manifest.raw_data
            or any(
                resource.kind.casefold() == "datafiles"
                or resource.resource_type.casefold() == "gmincludedfile"
                for resource in manifest.resources
            )
            or any(
                self._manifest_diagnostic_is_included_file(diagnostic)
                for diagnostic in manifest.diagnostics
            )
        )
        if (
            manifest.yyp_path is not None
            and not malformed
            and manifest_declares_included_files
        ):
            declared_plan = self._plan_manifest_included_files(manifest)
            # Included Files are directory-backed rather than ordinary Asset
            # Browser resources: current GameMaker automatically reflects
            # contained files added under datafiles even before their YYP
            # metadata is refreshed. Preserve those files while still
            # accounting for stale manifest declarations.
            requested_keys = list(declared_plan.requested_keys)
            available_files = list(declared_plan.available_files)
            seen_keys = set(requested_keys)
            for source in self._discovered_included_files():
                if source.relative_path in seen_keys:
                    continue
                seen_keys.add(source.relative_path)
                requested_keys.append(source.relative_path)
                available_files.append(source)
            return _IncludedFileConversionPlan(
                requested_keys=tuple(requested_keys),
                available_files=tuple(available_files),
                skipped_keys=declared_plan.skipped_keys,
            )

        available_files = self._discovered_included_files()
        return _IncludedFileConversionPlan(
            requested_keys=tuple(
                source.relative_path for source in available_files
            ),
            available_files=available_files,
            skipped_keys=(),
        )

    def _discovered_included_files(self) -> tuple[_IncludedFileSource, ...]:
        """Return every contained regular payload under datafiles."""

        datafiles = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource="datafiles",
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles is None or not os.path.isdir(datafiles.filesystem_path):
            return ()
        return tuple(self._collect_included_files(datafiles))

    def _plan_manifest_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _IncludedFileConversionPlan:
        requested_keys: list[str] = []
        available_files: list[_IncludedFileSource] = []
        skipped_keys: list[str] = []
        seen_keys: set[str] = set()

        for declaration in self._declared_included_files(manifest):
            resolved: ResolvedProjectSourcePath | None = None
            unavailable_reason = "its manifest source path was rejected"
            if declaration.source_path is not None:
                resolved = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=declaration.name,
                    resource_type="included_file",
                    field=declaration.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = "its manifest source path was rejected"

            relative_path = self._declared_relative_path(declaration, resolved)
            if relative_path in seen_keys:
                continue
            seen_keys.add(relative_path)
            requested_keys.append(relative_path)

            if resolved is not None:
                source_root, separator, source_relative = (
                    resolved.source_path.partition("/")
                )
                if (
                    not separator
                    or source_root.casefold() != "datafiles"
                    or not source_relative
                ):
                    self._report_source_path_rejection(
                        declaration.source_path or resolved.source_path,
                        ProjectSourcePathError(
                            "Resolved included-file source must remain under "
                            "the GameMaker 'datafiles' directory"
                        ),
                        owner_source_path=declaration.owner_source_path,
                        resource=declaration.name,
                        resource_type="included_file",
                        field=declaration.manifest_field,
                    )
                    resolved = None
                    unavailable_reason = (
                        "its manifest source path was rejected outside the "
                        "datafiles resource family"
                    )
                elif not os.path.isfile(resolved.filesystem_path):
                    unavailable_reason = (
                        f"the source file is missing at {resolved.source_path!r}"
                    )
                    resolved = None

            if resolved is None:
                skipped_keys.append(relative_path)
                self._report_unavailable_declared_included_file(
                    declaration,
                    reason=unavailable_reason,
                )
                continue

            available_files.append(
                _IncludedFileSource(
                    filesystem_path=resolved.filesystem_path,
                    relative_path=relative_path,
                    owner_source_path=declaration.owner_source_path,
                )
            )

        return _IncludedFileConversionPlan(
            requested_keys=tuple(requested_keys),
            available_files=tuple(available_files),
            skipped_keys=tuple(skipped_keys),
        )

    def _declared_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[_DeclaredIncludedFile, ...]:
        """Return unique included-file declarations from a valid YYP."""
        declared: dict[str, _DeclaredIncludedFile] = {}

        def add(resource: _DeclaredIncludedFile, identity: str) -> None:
            normalized_identity = self._normalized_declaration_path(identity)
            if not normalized_identity:
                normalized_identity = resource.name
            if not normalized_identity:
                return
            declared.setdefault(normalized_identity, resource)

        for included_file in manifest.included_files:
            source = included_file.source
            field = source.field_path if source is not None else None
            raw_field = next(
                (
                    key
                    for key in ("path", "filePath", "filename")
                    if key in included_file.raw_data
                ),
                "path",
            )
            manifest_field = f"{field}.{raw_field}" if field else raw_field
            source_path = included_file.path
            if (
                raw_field == "filePath"
                and included_file.name
                and posixpath.basename(source_path) != included_file.name
            ):
                # Current GameMaker YYP files store the containing directory in
                # ``filePath`` and the payload filename separately in ``name``.
                source_path = posixpath.join(source_path, included_file.name)
            add(
                _DeclaredIncludedFile(
                    name=included_file.name or included_file.path,
                    source_path=source_path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=manifest_field,
                ),
                source_path or included_file.name,
            )

        for resource in manifest.resources:
            if (
                resource.kind.casefold() != "datafiles"
                and resource.resource_type.casefold() != "gmincludedfile"
            ):
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredIncludedFile(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=field,
                ),
                resource.path,
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_included_file(diagnostic)
            ):
                continue
            source = diagnostic.source
            field = source.field_path if source is not None else None
            add(
                _DeclaredIncludedFile(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        source.path
                        if source is not None
                        else manifest.yyp_path or ""
                    ),
                    manifest_field=field,
                ),
                f"rejected:{diagnostic.resource}",
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_included_file(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "datafiles"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold()
            in {"included_file", "includedfile", "gmincludedfile"}
        )

    @staticmethod
    def _normalized_declaration_path(path: str) -> str:
        normalized = posixpath.normpath(path.replace("\\", "/").strip())
        return "" if normalized in {"", "."} else normalized

    def _declared_relative_path(
        self,
        declaration: _DeclaredIncludedFile,
        resolved: ResolvedProjectSourcePath | None,
    ) -> str:
        if resolved is not None:
            source_root, separator, source_relative = (
                resolved.source_path.partition("/")
            )
            if (
                separator
                and source_root.casefold() == "datafiles"
                and source_relative
            ):
                return source_relative

        fallback = self._normalized_declaration_path(
            declaration.source_path or declaration.name
        )
        source_root, separator, source_relative = fallback.partition("/")
        if (
            separator
            and source_root.casefold() == "datafiles"
            and source_relative
        ):
            return source_relative
        return fallback or declaration.name

    def _report_unavailable_declared_included_file(
        self,
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
        self,
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

    def convert_included_files(self) -> None:
        plan = self._included_file_conversion_plan()
        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for resource_key in plan.skipped_keys:
            self._resource_skipped(resource_key)

        planned_logical_paths: list[str] = []
        for logical_path in (
            *plan.requested_keys,
            *(source.relative_path for source in plan.available_files),
        ):
            try:
                canonical_included_file_lookup_path(logical_path)
            except ProjectSourcePathError:
                continue
            planned_logical_paths.append(logical_path)
        path_assignments = plan_included_file_paths(planned_logical_paths)
        assignments_by_source = {
            assignment.original_logical_path: assignment
            for assignment in path_assignments
        }

        if not plan.requested_keys:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
        all_files = list(plan.available_files)
        if path_assignments:
            self._report_included_file_path_collisions(path_assignments)
        emitted_logical_paths = {
            source.relative_path for source in all_files
        }

        project_identity = _ensure_included_output_project_root(
            self.godot_project_path
        )
        lock_primary_error: BaseException | None = None
        try:
            project_lock = _acquire_included_project_lock(
                self.godot_project_path,
                project_identity,
            )
        except Exception:
            for source in all_files:
                self._resource_failed(source.relative_path)
            raise
        try:
            try:
                recovery_message = _recover_included_output_set(
                    self.godot_project_path,
                    project_identity,
                )
                if recovery_message is not None:
                    self._safe_log("Recovered: " + recovery_message)
            except Exception:
                for source in all_files:
                    self._resource_failed(source.relative_path)
                raise
            public_root_path = os.path.join(
                self.godot_project_path,
                _included_constants.INCLUDED_FILES_ROOT_NAME,
            )
            previous_root_snapshot: _IncludedTreeSnapshot
            previous_registry_snapshot: _IncludedRegistrySnapshot
            try:
                previous_root_snapshot = _included_snapshots.capture_included_tree(
                    public_root_path,
                    expected_parent_identity=project_identity,
                )
                previous_registry_snapshot = _included_snapshots.capture_included_registry(
                    self.godot_project_path,
                    expected_project_identity=project_identity,
                )
            except Exception as error:
                for source in all_files:
                    self._resource_failed(source.relative_path)
                    assignment = assignments_by_source[source.relative_path]
                    self._report_included_file_output_rejection(
                        source.relative_path,
                        os.path.join(
                            public_root_path,
                            *assignment.assigned_output_path.split("/"),
                        ),
                        error,
                    )
                raise

            stage_container_path: str | None = None
            stage_container_identity: _PathIdentity | None = None
            active_error: BaseException | None = None
            transaction_committed = False
            transaction_cleanup_managed = False
            try:
                previous_content_receipts = _included_metadata.included_registry_receipts_from_tree(
                    previous_root_snapshot,
                    assignments_by_source,
                    emitted_logical_paths,
                )
                expected_registry_content = (
                    b""
                    if previous_content_receipts is None
                    else render_included_file_registry(
                        path_assignments,
                        emitted_logical_paths,
                        previous_content_receipts,
                    ).encode("utf-8")
                )
                generation_match = self._unchanged_included_generation_matches(
                    tuple(all_files),
                    assignments_by_source,
                    expected_registry_content,
                    previous_root_snapshot,
                    previous_registry_snapshot,
                    project_identity,
                    public_root_path,
                )
                if generation_match.unchanged:
                    for completed_count, source in enumerate(all_files, start=1):
                        self._resource_started(source.relative_path)
                        self._resource_completed(source.relative_path)
                        if self.compact_logging:
                            self._safe_log_progress(
                                os.path.basename(source.relative_path),
                                completed_count,
                                len(all_files),
                            )
                        else:
                            self._safe_log(
                                get_localized(
                                    "Console_Convertor_IncludedFiles_Unchanged"
                                ).format(path=source.relative_path)
                            )
                    self._safe_progress(100)
                    return
                planned_source_receipts = {
                    receipt.logical_path: receipt
                    for receipt in generation_match.source_receipts
                }

                source_byte_counts = self._preflight_included_source_byte_counts(
                    tuple(all_files)
                )
                preflight_registry_content = render_included_file_registry(
                    path_assignments,
                    emitted_logical_paths,
                    {
                        logical_path: (
                            source_byte_counts[logical_path],
                            _included_constants.INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256,
                        )
                        for logical_path in emitted_logical_paths
                    },
                ).encode("utf-8")
                assigned_byte_counts = {
                    assignments_by_source[
                        source.relative_path
                    ].assigned_output_path: source_byte_counts[
                        source.relative_path
                    ]
                    for source in all_files
                }
                recovery_record_sizes = (
                    _included_codec.preflight_included_recovery_record_sizes(
                        self.godot_project_path,
                        project_identity,
                        assigned_byte_counts,
                        preflight_registry_content,
                        previous_root_snapshot,
                        previous_registry_snapshot,
                    )
                )
                publication_transaction_id = (
                    secrets.token_hex(16)
                    if len(planned_source_receipts) == len(all_files)
                    and all(
                        source.relative_path in planned_source_receipts
                        for source in all_files
                    )
                    else None
                )

                (
                    stage_container_path,
                    stage_container_identity,
                ) = _create_included_output_stage(
                    self.godot_project_path,
                    project_identity,
                )
                staged_root_path = os.path.join(
                    stage_container_path,
                    _included_constants.INCLUDED_FILES_ROOT_NAME,
                )
                os.mkdir(staged_root_path, 0o755)
                staged_root_identity = _included_snapshots.included_directory_identity(staged_root_path)
                if staged_root_identity is None:
                    raise OSError("Included Files staging root disappeared")

                self._active_output_project_path = stage_container_path
                successful_logical_paths: set[str] = set()
                copy_receipts: dict[str, _IncludedCopyReceipt] = {}
                worker_failed = False
                worker_cancelled = False
                first_worker_error: BaseException | None = None
                processed_files = 0
                total_files = len(all_files)
                try:
                    def submit_copy(
                        executor: ThreadPoolExecutor,
                        source: _IncludedFileSource,
                    ) -> Future[
                        tuple[str, bool, _IncludedCopyReceipt | None] | None
                    ]:
                        assignment = assignments_by_source[source.relative_path]
                        staged_output_path = os.path.join(
                            staged_root_path,
                            *assignment.assigned_output_path.split("/"),
                        )
                        planned_receipt = planned_source_receipts.get(
                            source.relative_path
                        )
                        if planned_receipt is None:
                            return executor.submit(
                                self._process_file,
                                source.filesystem_path,
                                staged_output_path,
                                source.relative_path,
                                source.owner_source_path,
                            )
                        return executor.submit(
                            self._process_file,
                            source.filesystem_path,
                            staged_output_path,
                            source.relative_path,
                            source.owner_source_path,
                            planned_receipt,
                        )

                    def consume_copy(
                        _source: _IncludedFileSource,
                        future: Future[
                            tuple[str, bool, _IncludedCopyReceipt | None] | None
                        ],
                    ) -> bool:
                        nonlocal worker_failed
                        nonlocal worker_cancelled
                        nonlocal first_worker_error
                        nonlocal processed_files

                        try:
                            result = future.result()
                        except BaseException as error:
                            worker_failed = True
                            if first_worker_error is None:
                                first_worker_error = error
                            return False
                        if result is None:
                            worker_cancelled = True
                            return False

                        processed_files += 1
                        relative_path, copied, copy_receipt = result
                        if copied and copy_receipt is not None:
                            successful_logical_paths.add(relative_path)
                            copy_receipts[relative_path] = copy_receipt
                        else:
                            worker_failed = True
                        if total_files:
                            self._safe_progress(
                                min(
                                    99,
                                    int((processed_files / total_files) * 99),
                                )
                            )
                        return not worker_failed

                    phase_completed = _run_bounded_included_worker_phase(
                        all_files,
                        max_workers=self.max_workers,
                        conversion_running=self.conversion_running,
                        submit=submit_copy,
                        consume=consume_copy,
                    )
                    if not phase_completed and not worker_failed:
                        worker_cancelled = True
                finally:
                    self._active_output_project_path = None

                if worker_failed:
                    for source in all_files:
                        self._resource_failed(source.relative_path)
                    if first_worker_error is not None:
                        raise first_worker_error
                    raise OSError(
                        "Included Files output-set staging failed; the previous "
                        "managed output was preserved"
                    )
                if (
                    worker_cancelled
                    or not self.conversion_running()
                    or len(successful_logical_paths) != len(all_files)
                ):
                    for source in all_files:
                        self._resource_skipped(source.relative_path)
                    self.log_callback(
                        get_localized("Console_Convertor_IncludedFiles_Stopped")
                    )
                    return

                generation_content_receipts = (
                    tuple(
                        _IncludedGenerationContentReceipt(
                            transaction_id=publication_transaction_id,
                            generation_identity=staged_root_identity,
                            stage_container_identity=stage_container_identity,
                            source=planned_source_receipts[
                                source.relative_path
                            ],
                            staged_output_path=os.path.normcase(
                                os.path.abspath(
                                    os.path.join(
                                        staged_root_path,
                                        *assignments_by_source[
                                            source.relative_path
                                        ].assigned_output_path.split("/"),
                                    )
                                )
                            ),
                            public_output_path=os.path.normcase(
                                os.path.abspath(
                                    os.path.join(
                                        public_root_path,
                                        *assignments_by_source[
                                            source.relative_path
                                        ].assigned_output_path.split("/"),
                                    )
                                )
                            ),
                            output=copy_receipts[source.relative_path],
                        )
                        for source in all_files
                    )
                    if publication_transaction_id is not None
                    else ()
                )
                if generation_content_receipts:
                    if publication_transaction_id is None:
                        raise AssertionError(
                            "Generation receipts require a transaction id"
                        )
                    staged_root_snapshot = (
                        _included_snapshots.capture_included_tree_from_generation_receipts(
                            staged_root_path,
                            expected_parent_identity=stage_container_identity,
                            transaction_id=publication_transaction_id,
                            generation_identity=staged_root_identity,
                            stage_container_identity=stage_container_identity,
                            receipts=generation_content_receipts,
                        )
                    )
                else:
                    staged_root_snapshot = _included_snapshots.capture_included_tree(
                        staged_root_path,
                        expected_parent_identity=stage_container_identity,
                    )
                assigned_receipts = {
                    assignments_by_source[source.relative_path].assigned_output_path:
                        copy_receipts[source.relative_path]
                    for source in all_files
                }
                _included_metadata.verify_staged_included_inventory(
                    staged_root_snapshot,
                    assigned_receipts,
                )

                staged_registry_text = render_included_file_registry(
                    path_assignments,
                    emitted_logical_paths,
                    {
                        logical_path: (
                            receipt.byte_count,
                            receipt.sha256,
                        )
                        for logical_path, receipt in copy_receipts.items()
                    },
                )
                staged_registry_path = os.path.join(
                    stage_container_path,
                    "gml_included_file_registry.gd",
                )
                atomic_write_confined_generated_text(
                    staged_registry_path,
                    staged_registry_text,
                    confinement_root=stage_container_path,
                )
                staged_registry_state = _included_snapshots.included_regular_file_state(
                    staged_registry_path,
                    expected_parent_identity=stage_container_identity,
                )
                if staged_registry_state is None:
                    raise OSError("Included File registry staging candidate disappeared")
                if previous_registry_snapshot.file_mode is not None:
                    _included_mutations.chmod_exact_included_file(
                        staged_registry_path,
                        staged_registry_state[0],
                        previous_registry_snapshot.file_mode,
                        stage_container_identity,
                    )
                    staged_registry_state = _included_snapshots.included_regular_file_state(
                        staged_registry_path,
                        expected_parent_identity=stage_container_identity,
                        allowed_identities=frozenset({staged_registry_state[0]}),
                    )
                    if staged_registry_state is None:
                        raise OSError(
                            "Included File registry staging candidate disappeared"
                        )
                staged_registry_identity, staged_registry_mode, staged_registry_content = (
                    staged_registry_state
                )
                staged_container_snapshot = _included_stage_container_snapshot(
                    project_identity,
                    stage_container_path,
                    stage_container_identity,
                    staged_root_snapshot,
                    staged_registry_identity,
                    staged_registry_content,
                )

                transaction = _IncludedOutputSetTransaction(
                    project_identity=project_identity,
                    stage_container_path=stage_container_path,
                    stage_container_identity=stage_container_identity,
                    staged_container_snapshot=staged_container_snapshot,
                    staged_root_path=staged_root_path,
                    staged_root_snapshot=staged_root_snapshot,
                    staged_registry_path=staged_registry_path,
                    staged_registry_identity=staged_registry_identity,
                    staged_registry_mode=staged_registry_mode,
                    staged_registry_content=staged_registry_content,
                    previous_root_snapshot=previous_root_snapshot,
                    previous_registry_snapshot=previous_registry_snapshot,
                    recovery_record_sizes=recovery_record_sizes,
                    publication_transaction_id=publication_transaction_id,
                    content_receipts=generation_content_receipts,
                )
                # From this handoff onward, only manifest-bound transaction
                # cleanup may remove the stage, including after rollback.
                transaction_cleanup_managed = True
                cleanup_warnings = _commit_included_output_set(
                    self.godot_project_path,
                    transaction,
                    self.conversion_running,
                )
                transaction_committed = True
                for cleanup_warning in cleanup_warnings:
                    self._safe_log(
                        "Warning: Included Files transaction cleanup failed: "
                        + cleanup_warning
                    )

                for source in all_files:
                    self._resource_completed(source.relative_path)
                    if self.compact_logging:
                        self._safe_log_progress(
                            os.path.basename(source.relative_path),
                            len(successful_logical_paths),
                            len(all_files),
                        )
                    else:
                        self._safe_log(
                            get_localized(
                                "Console_Convertor_IncludedFiles_Copied"
                            ).format(path=source.relative_path)
                        )
                self._safe_progress(100)
            except _IncludedOutputSetCancelled:
                for source in all_files:
                    self._resource_skipped(source.relative_path)
                self.log_callback(
                    get_localized("Console_Convertor_IncludedFiles_Stopped")
                )
                return
            except BaseException as error:
                active_error = error
                for source in all_files:
                    self._resource_failed(source.relative_path)
                raise
            finally:
                self._active_output_project_path = None
                recovery_pending = os.path.lexists(
                    os.path.join(
                        self.godot_project_path,
                        _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                    )
                )
                if (
                    not transaction_cleanup_managed
                    and not recovery_pending
                    and stage_container_path is not None
                    and stage_container_identity is not None
                ):
                    try:
                        _included_mutations.remove_owned_included_tree(
                            stage_container_path,
                            stage_container_identity,
                            expected_parent_identity=project_identity,
                        )
                    except OSError as cleanup_error:
                        if active_error is not None:
                            active_error.add_note(
                                "Included Files staging cleanup also failed: "
                                + str(cleanup_error)
                            )
                        elif transaction_committed:
                            self._safe_log(
                                "Warning: Included Files staging cleanup failed: "
                                + str(cleanup_error)
                            )
                elif recovery_pending:
                    message = (
                        "Included Files recovery state was retained; the next "
                        "conversion will resume it"
                    )
                    if active_error is not None:
                        active_error.add_note(message)
                    else:
                        self._safe_log("Warning: " + message)
        except BaseException as error:
            lock_primary_error = error
            raise
        finally:
            try:
                _release_included_project_lock(project_lock)
            except BaseException as lock_error:
                if lock_primary_error is not None:
                    lock_primary_error.add_note(
                        "Included Files transaction lock release failed: "
                        + str(lock_error)
                    )
                elif isinstance(lock_error, OSError):
                    self._safe_log(
                        "Warning: Included Files transaction lock release failed: "
                        + str(lock_error)
                    )
                else:
                    raise

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_included_files()
