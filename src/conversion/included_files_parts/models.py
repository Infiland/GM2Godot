from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class _IncludedFileSource:
    filesystem_path: str
    relative_path: str
    owner_source_path: str


@dataclass(frozen=True)
class _DeclaredIncludedFile:
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str | None


@dataclass(frozen=True)
class _IncludedFileConversionPlan:
    requested_keys: tuple[str, ...]
    available_files: tuple[_IncludedFileSource, ...]
    skipped_keys: tuple[str, ...]

_PathIdentity = tuple[int, int]

_PathFingerprint = tuple[int, int, int, int, int, int]

_PathHandleBinding = tuple[int, int, int, int, int, int]

_HandleState = tuple[int, int, int, int, int, int, int]

_IncludedSourceFingerprint = tuple[int, int, int, int, int, int]

_IncludedSourceDirectoryIdentity = tuple[str, _PathIdentity]

_IncludedCleanupFileState = tuple[int, str, _PathFingerprint]


@dataclass(frozen=True)
class _IncludedPayloadReceipt:
    source_fingerprint: _IncludedSourceFingerprint
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class _IncludedCopyReceipt:
    payload: _IncludedPayloadReceipt
    output_fingerprint: _PathFingerprint
    output_ctime_ns: int
    output_handle_state: _HandleState

    @property
    def source_fingerprint(self) -> _IncludedSourceFingerprint:
        return self.payload.source_fingerprint

    @property
    def byte_count(self) -> int:
        return self.payload.byte_count

    @property
    def sha256(self) -> str:
        return self.payload.sha256


@dataclass(frozen=True)
class _IncludedSourceBinding:
    filesystem_path: str
    canonical_path: str
    directory_identities: tuple[_IncludedSourceDirectoryIdentity, ...]
    lexical_state: _HandleState
    path_state: _HandleState
    handle_state: _HandleState


@dataclass(frozen=True)
class _IncludedNoOpSourceReceipt:
    logical_path: str
    assigned_path: str
    binding: _IncludedSourceBinding
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class _IncludedGenerationMatch:
    unchanged: bool
    source_receipts: tuple[_IncludedNoOpSourceReceipt, ...]


@dataclass(frozen=True)
class _IncludedGenerationContentReceipt:
    transaction_id: str
    generation_identity: _PathIdentity
    stage_container_identity: _PathIdentity
    source: _IncludedNoOpSourceReceipt
    staged_output_path: str
    public_output_path: str
    output: _IncludedCopyReceipt


@dataclass(frozen=True)
class _IncludedTreeEntry:
    relative_path: str
    kind: str
    fingerprint: _PathFingerprint
    ctime_ns: int | None
    content_sha256: str | None


@dataclass(frozen=True)
class _IncludedTreeSnapshot:
    root_fingerprint: _PathFingerprint | None
    entries: tuple[_IncludedTreeEntry, ...]

    @property
    def identity(self) -> _PathIdentity | None:
        if self.root_fingerprint is None:
            return None
        return self.root_fingerprint[:2]


@dataclass(frozen=True)
class _IncludedTreeDescriptorBinding:
    parent_fd: int
    name: str
    fingerprint: _PathFingerprint
    display_path: str


@dataclass(frozen=True)
class _IncludedTreePathBinding:
    path: str
    identity: _PathIdentity


@dataclass(frozen=True)
class _IncludedRegistrySnapshot:
    directory_identity: _PathIdentity | None
    file_identity: _PathIdentity | None
    file_mode: int | None
    content: bytes | None


@dataclass(frozen=True)
class _IncludedRecoveryRecordSizes:
    journal_bytes: int
    commit_bytes: int


@dataclass(frozen=True)
class _IncludedOutputSetTransaction:
    project_identity: _PathIdentity
    stage_container_path: str
    stage_container_identity: _PathIdentity
    staged_container_snapshot: _IncludedTreeSnapshot
    staged_root_path: str
    staged_root_snapshot: _IncludedTreeSnapshot
    staged_registry_path: str
    staged_registry_identity: _PathIdentity
    staged_registry_mode: int
    staged_registry_content: bytes
    previous_root_snapshot: _IncludedTreeSnapshot
    previous_registry_snapshot: _IncludedRegistrySnapshot
    recovery_record_sizes: _IncludedRecoveryRecordSizes | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    publication_transaction_id: str | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    content_receipts: tuple[_IncludedGenerationContentReceipt, ...] = field(
        default=(),
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class _IncludedRecoveryJournal:
    format_version: int
    transaction_id: str
    transaction: _IncludedOutputSetTransaction
    root_backup_path: str
    registry_backup_path: str
    registry_directory_path: str
    registry_directory_identity: _PathIdentity
    registry_directory_created: bool


@dataclass(frozen=True)
class _IncludedCommitMarker:
    format_version: int
    transaction_id: str
    project_identity: _PathIdentity
    root_identity: _PathIdentity
    root_snapshot_sha256: str
    registry_directory_identity: _PathIdentity
    registry_identity: _PathIdentity
    registry_content_sha256: str


@dataclass
class _IncludedProjectLock:
    file_descriptor: int
    path: str
    windows: bool


class _IncludedOutputSetCancelled(Exception):
    """Signal cancellation while a reversible output-set commit is active."""


# Finite package-internal aliases; the facade reexports these same objects.
IncludedFileSource = _IncludedFileSource
DeclaredIncludedFile = _DeclaredIncludedFile
IncludedFileConversionPlan = _IncludedFileConversionPlan
PathIdentity = _PathIdentity
PathFingerprint = _PathFingerprint
PathHandleBinding = _PathHandleBinding
HandleState = _HandleState
IncludedSourceFingerprint = _IncludedSourceFingerprint
IncludedSourceDirectoryIdentity = _IncludedSourceDirectoryIdentity
IncludedCleanupFileState = _IncludedCleanupFileState
IncludedPayloadReceipt = _IncludedPayloadReceipt
IncludedCopyReceipt = _IncludedCopyReceipt
IncludedSourceBinding = _IncludedSourceBinding
IncludedNoOpSourceReceipt = _IncludedNoOpSourceReceipt
IncludedGenerationMatch = _IncludedGenerationMatch
IncludedGenerationContentReceipt = _IncludedGenerationContentReceipt
IncludedTreeEntry = _IncludedTreeEntry
IncludedTreeSnapshot = _IncludedTreeSnapshot
IncludedTreeDescriptorBinding = _IncludedTreeDescriptorBinding
IncludedTreePathBinding = _IncludedTreePathBinding
IncludedRegistrySnapshot = _IncludedRegistrySnapshot
IncludedRecoveryRecordSizes = _IncludedRecoveryRecordSizes
IncludedOutputSetTransaction = _IncludedOutputSetTransaction
IncludedRecoveryJournal = _IncludedRecoveryJournal
IncludedCommitMarker = _IncludedCommitMarker
IncludedProjectLock = _IncludedProjectLock
IncludedOutputSetCancelled = _IncludedOutputSetCancelled
