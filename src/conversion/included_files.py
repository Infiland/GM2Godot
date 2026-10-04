from __future__ import annotations

import hashlib as hashlib
import os
import posixpath as posixpath
import secrets as secrets
import stat as stat
import tempfile as tempfile
from concurrent.futures import (
    FIRST_COMPLETED as FIRST_COMPLETED,
    Future as Future,
    ThreadPoolExecutor as ThreadPoolExecutor,
    wait as wait,
)
from dataclasses import replace as replace
from typing import (
    Any as Any,
    BinaryIO,
    Callable as Callable,
    Iterable as Iterable,
    TypeVar as TypeVar,
)

from src.conversion.atomic_generated_text import (
    atomic_write_confined_generated_text as atomic_write_confined_generated_text,
)
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_paths import (
    IncludedFilePathAssignment,
    canonical_included_file_lookup_path as canonical_included_file_lookup_path,
    plan_included_file_paths as plan_included_file_paths,
)
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH as INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
)
from src.conversion.included_files_parts import (
    constants as _included_constants,
    copy_worker as _included_copy_worker,
    diagnostics as _included_diagnostics,
    driver as _included_driver,
    file_publication as _included_file_publication,
    generation_matching as _included_generation_matching,
    guarded_mutations as _included_mutations,
    locking as _included_locking,
    models as _included_models,
    native_posix as _included_posix,
    native_windows as _included_windows,
    path_validation as _included_paths,
    phase_observer as _included_phases,
    planning as _included_planning,
    publisher as _included_publisher,
    record_io as _included_records,
    record_lifecycle as _included_record_lifecycle,
    recorded_cleanup as _included_cleanup,
    recovery as _included_recovery,
    recovery_codec as _included_codec,
    source_access as _included_source_access,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
    stat_metadata as _included_metadata,
    transaction_cleanup as _included_transaction_cleanup,
    transaction_state as _included_transaction_state,
    worker_pool as _included_worker_pool,
)
from src.conversion.included_files_parts.models import (
    DeclaredIncludedFile as _DeclaredIncludedFile,
    IncludedCopyReceipt as _IncludedCopyReceipt,
    IncludedFileConversionPlan as _IncludedFileConversionPlan,
    IncludedFileSource as _IncludedFileSource,
    IncludedGenerationMatch as _IncludedGenerationMatch,
    IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt,
    IncludedRegistrySnapshot as _IncludedRegistrySnapshot,
    IncludedSourceBinding as _IncludedSourceBinding,
    IncludedTreeSnapshot as _IncludedTreeSnapshot,
    PathIdentity as _PathIdentity,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest as load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError as ProjectSourcePathError,
    ResolvedProjectSourcePath,
)
from src.conversion.type_defs import (
    ConversionRunning,
    LogCallback,
    ProgressCallback,
    StrPath,
)
from src.localization import get_localized as get_localized

_run_bounded_included_worker_phase = _included_worker_pool.run_bounded_included_worker_phase
_included_stage_container_snapshot = _included_staging.included_stage_container_snapshot
_before_included_registry_directory_binding_check = _included_staging.before_included_registry_directory_binding_check
_verify_included_stage_container = _included_staging.verify_included_stage_container
_write_included_stage_marker = _included_staging.write_included_stage_marker
_create_included_output_stage = _included_staging.create_included_output_stage
_sync_included_tree_directories_bottom_up = _included_staging.sync_included_tree_directories_bottom_up
_prepare_included_registry_directory = _included_staging.prepare_included_registry_directory
_after_included_lock_initialization_phase = _included_locking.after_included_lock_initialization_phase
_write_included_lock_initialization_temporary = _included_locking.write_included_lock_initialization_temporary
_remove_exact_included_lock_initialization_temporary = _included_locking.remove_exact_included_lock_initialization_temporary
_cleanup_included_lock_initialization_temporaries = _included_locking.cleanup_included_lock_initialization_temporaries
_initialize_included_project_lock = _included_locking.initialize_included_project_lock
_acquire_included_project_lock = _included_locking.acquire_included_project_lock
_release_included_project_lock = _included_locking.release_included_project_lock
_publish_included_recovery_record = _included_record_lifecycle.publish_included_recovery_record
_verify_included_commit_marker_generation = _included_transaction_state.verify_included_commit_marker_generation
_verify_included_published_journal = _included_transaction_state.verify_included_published_journal
_verify_included_published_commit_marker = _included_transaction_state.verify_included_published_commit_marker
_remove_included_recovery_record = _included_record_lifecycle.remove_included_recovery_record
_cleanup_orphan_included_recovery_state = _included_recovery.cleanup_orphan_included_recovery_state
_rollback_included_output_set = _included_transaction_cleanup.rollback_included_output_set
_cleanup_committed_included_output_set = _included_transaction_cleanup.cleanup_committed_included_output_set
_promote_included_journal_temporary = _included_recovery.promote_included_journal_temporary
_recover_included_output_set = _included_recovery.recover_included_output_set
_commit_included_output_set = _included_publisher.commit_included_output_set
_ensure_included_output_project_root = _included_file_publication.ensure_included_output_project_root
_verify_open_included_output_directory = _included_file_publication.verify_open_included_output_directory
_read_included_payload_chunk = _included_file_publication.read_included_payload_chunk
_copy_included_payload = _included_file_publication.copy_included_payload
_stage_included_output_at = _included_file_publication.stage_included_output_at
_publish_included_output_at = _included_file_publication.publish_included_output_at
_prepare_included_output_directories_fallback = _included_file_publication.prepare_included_output_directories_fallback
_verify_included_output_directories_fallback = _included_file_publication.verify_included_output_directories_fallback
_verify_included_output_stage_fallback = _included_file_publication.verify_included_output_stage_fallback
_remove_included_output_stage_fallback = _included_file_publication.remove_included_output_stage_fallback
_publish_included_output_fallback = _included_file_publication.publish_included_output_fallback
_publish_confined_included_output = _included_file_publication.publish_confined_included_output
_before_included_unchanged_source_revalidation = _included_generation_matching.before_included_unchanged_source_revalidation
_before_included_unchanged_public_revalidation = _included_generation_matching.before_included_unchanged_public_revalidation
_before_included_unchanged_final_revalidation = _included_generation_matching.before_included_unchanged_final_revalidation
_before_included_changed_generation_final_validation = _included_publisher.before_included_changed_generation_final_validation
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
_IncludedPayloadReceipt = _included_models.IncludedPayloadReceipt
_IncludedGenerationContentReceipt = _included_models.IncludedGenerationContentReceipt
_IncludedTreeEntry = _included_models.IncludedTreeEntry
_IncludedOutputSetTransaction = _included_models.IncludedOutputSetTransaction
_IncludedRecoveryJournal = _included_models.IncludedRecoveryJournal
_IncludedCommitMarker = _included_models.IncludedCommitMarker
_IncludedProjectLock = _included_models.IncludedProjectLock
_IncludedOutputSetCancelled = _included_models.IncludedOutputSetCancelled
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


_IncludedWorkerItem = _included_worker_pool.IncludedWorkerItem
_IncludedWorkerResult = _included_worker_pool.IncludedWorkerResult


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


render_included_file_registry = _included_driver.render_included_file_registry

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
        return _included_copy_worker.process_file(self, gm_file_path, godot_file_path, rel_path, owner_source_path, planned_receipt)

    def _report_included_file_output_rejection(
        self,
        relative_path: str,
        output_path: str,
        error: BaseException,
    ) -> None:
        return _included_diagnostics.report_included_file_output_rejection(self, relative_path, output_path, error)

    def _open_confined_source_file(
        self,
        filesystem_path: str,
        *,
        owner_source_path: str,
        resource: str,
        deny_writes: bool = False,
    ) -> tuple[BinaryIO, os.stat_result] | None:
        """Open a contained regular file and pin it against late path swaps."""
        return _included_source_access.open_confined_source_file(self, filesystem_path, owner_source_path=owner_source_path, resource=resource, deny_writes=deny_writes)

    def _preflight_included_source_byte_counts(
        self,
        sources: tuple[_IncludedFileSource, ...],
    ) -> dict[str, int]:
        """Capture byte counts without reading or staging payload bodies."""
        return _included_source_access.preflight_included_source_byte_counts(self, sources)

    def _capture_pinned_included_source_binding(
        self,
        source: _IncludedFileSource,
        source_file: BinaryIO,
        expected_stat: os.stat_result,
    ) -> _IncludedSourceBinding:
        return _included_source_access.capture_pinned_included_source_binding(self, source, source_file, expected_stat)

    def _capture_unchanged_source_receipt(
        self,
        source: _IncludedFileSource,
        *,
        deny_writes: bool,
    ) -> _IncludedNoOpSourceReceipt:
        return _included_source_access.capture_unchanged_source_receipt(self, source, deny_writes=deny_writes)

    def _collect_unchanged_source_receipts(
        self,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        *,
        deny_writes: bool,
    ) -> dict[str, _IncludedNoOpSourceReceipt]:
        return _included_source_access.collect_unchanged_source_receipts(self, sources, assignments_by_source, deny_writes=deny_writes)

    def _revalidate_unchanged_source_bindings(
        self,
        sources: tuple[_IncludedFileSource, ...],
        receipts: dict[str, _IncludedNoOpSourceReceipt],
    ) -> None:
        return _included_source_access.revalidate_unchanged_source_bindings(self, sources, receipts)

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
        return _included_generation_matching.unchanged_included_generation_matches(self, sources, assignments_by_source, expected_registry_content, previous_root_snapshot, previous_registry_snapshot, project_identity, public_root_path)

    def _list_confined_directory(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> tuple[str, ...] | None:
        """List a contained directory without following a late path swap."""
        return _included_source_access.list_confined_directory(self, directory)

    def _report_directory_swap(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> None:
        return _included_diagnostics.report_directory_swap(self, directory)

    def _collect_included_files(
        self,
        datafiles: ResolvedProjectSourcePath,
    ) -> list[_IncludedFileSource]:
        return _included_source_access.collect_included_files(self, datafiles)

    def _included_file_conversion_plan(self) -> _IncludedFileConversionPlan:
        """Plan logical included files before filtering unavailable sources."""
        return _included_planning.included_file_conversion_plan(self)

    def _discovered_included_files(self) -> tuple[_IncludedFileSource, ...]:
        """Return every contained regular payload under datafiles."""
        return _included_source_access.discovered_included_files(self)

    def _plan_manifest_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _IncludedFileConversionPlan:
        return _included_planning.plan_manifest_included_files(self, manifest)

    def _declared_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[_DeclaredIncludedFile, ...]:
        """Return unique included-file declarations from a valid YYP."""
        return _included_planning.declared_included_files(self, manifest)

    @staticmethod
    def _manifest_diagnostic_is_included_file(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        return _included_planning.manifest_diagnostic_is_included_file(diagnostic)

    @staticmethod
    def _normalized_declaration_path(path: str) -> str:
        return _included_planning.normalized_declaration_path(path)

    def _declared_relative_path(
        self,
        declaration: _DeclaredIncludedFile,
        resolved: ResolvedProjectSourcePath | None,
    ) -> str:
        return _included_planning.declared_relative_path(self, declaration, resolved)

    def _report_unavailable_declared_included_file(
        self,
        declaration: _DeclaredIncludedFile,
        *,
        reason: str,
    ) -> None:
        return _included_diagnostics.report_unavailable_declared_included_file(self, declaration, reason=reason)

    def _report_included_file_path_collisions(
        self,
        assignments: tuple[IncludedFilePathAssignment, ...],
    ) -> None:
        return _included_diagnostics.report_included_file_path_collisions(self, assignments)

    def convert_included_files(self) -> None:
        return _included_driver.convert_included_files(self)

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_included_files()
