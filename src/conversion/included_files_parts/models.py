from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IncludedFileSource:
    filesystem_path: str
    relative_path: str
    owner_source_path: str


@dataclass(frozen=True)
class DeclaredIncludedFile:
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str | None


@dataclass(frozen=True)
class IncludedFileConversionPlan:
    requested_keys: tuple[str, ...]
    available_files: tuple[IncludedFileSource, ...]
    skipped_keys: tuple[str, ...]


PathIdentity = tuple[int, int]


PathFingerprint = tuple[int, int, int, int, int, int]


PathHandleBinding = tuple[int, int, int, int, int, int]


HandleState = tuple[int, int, int, int, int, int, int]


IncludedSourceFingerprint = tuple[int, int, int, int, int, int]


IncludedSourceDirectoryIdentity = tuple[str, PathIdentity]


IncludedCleanupFileState = tuple[int, str, PathFingerprint]


@dataclass(frozen=True)
class IncludedPayloadReceipt:
    source_fingerprint: IncludedSourceFingerprint
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class IncludedCopyReceipt:
    payload: IncludedPayloadReceipt
    output_fingerprint: PathFingerprint
    output_ctime_ns: int
    output_handle_state: HandleState

    @property
    def source_fingerprint(self) -> IncludedSourceFingerprint:
        return self.payload.source_fingerprint

    @property
    def byte_count(self) -> int:
        return self.payload.byte_count

    @property
    def sha256(self) -> str:
        return self.payload.sha256


@dataclass(frozen=True)
class IncludedSourceBinding:
    filesystem_path: str
    canonical_path: str
    directory_identities: tuple[IncludedSourceDirectoryIdentity, ...]
    lexical_state: HandleState
    path_state: HandleState
    handle_state: HandleState


@dataclass(frozen=True)
class IncludedNoOpSourceReceipt:
    logical_path: str
    assigned_path: str
    binding: IncludedSourceBinding
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class IncludedGenerationMatch:
    unchanged: bool
    source_receipts: tuple[IncludedNoOpSourceReceipt, ...]


@dataclass(frozen=True)
class IncludedGenerationContentReceipt:
    transaction_id: str
    generation_identity: PathIdentity
    stage_container_identity: PathIdentity
    source: IncludedNoOpSourceReceipt
    staged_output_path: str
    public_output_path: str
    output: IncludedCopyReceipt


@dataclass(frozen=True)
class IncludedTreeEntry:
    relative_path: str
    kind: str
    fingerprint: PathFingerprint
    ctime_ns: int | None
    content_sha256: str | None


@dataclass(frozen=True)
class IncludedTreeSnapshot:
    root_fingerprint: PathFingerprint | None
    entries: tuple[IncludedTreeEntry, ...]

    @property
    def identity(self) -> PathIdentity | None:
        if self.root_fingerprint is None:
            return None
        return self.root_fingerprint[:2]


@dataclass(frozen=True)
class IncludedTreeDescriptorBinding:
    parent_fd: int
    name: str
    fingerprint: PathFingerprint
    display_path: str


@dataclass(frozen=True)
class IncludedTreePathBinding:
    path: str
    identity: PathIdentity


@dataclass(frozen=True)
class IncludedRegistrySnapshot:
    directory_identity: PathIdentity | None
    file_identity: PathIdentity | None
    file_mode: int | None
    content: bytes | None


@dataclass(frozen=True)
class IncludedRecoveryRecordSizes:
    journal_bytes: int
    commit_bytes: int


@dataclass(frozen=True)
class IncludedOutputSetTransaction:
    project_identity: PathIdentity
    stage_container_path: str
    stage_container_identity: PathIdentity
    staged_container_snapshot: IncludedTreeSnapshot
    staged_root_path: str
    staged_root_snapshot: IncludedTreeSnapshot
    staged_registry_path: str
    staged_registry_identity: PathIdentity
    staged_registry_mode: int
    staged_registry_content: bytes
    previous_root_snapshot: IncludedTreeSnapshot
    previous_registry_snapshot: IncludedRegistrySnapshot
    recovery_record_sizes: IncludedRecoveryRecordSizes | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    publication_transaction_id: str | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    content_receipts: tuple[IncludedGenerationContentReceipt, ...] = field(
        default=(),
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class IncludedRecoveryJournal:
    format_version: int
    transaction_id: str
    transaction: IncludedOutputSetTransaction
    root_backup_path: str
    registry_backup_path: str
    registry_directory_path: str
    registry_directory_identity: PathIdentity
    registry_directory_created: bool


@dataclass(frozen=True)
class IncludedCommitMarker:
    format_version: int
    transaction_id: str
    project_identity: PathIdentity
    root_identity: PathIdentity
    root_snapshot_sha256: str
    registry_directory_identity: PathIdentity
    registry_identity: PathIdentity
    registry_content_sha256: str


@dataclass
class IncludedProjectLock:
    file_descriptor: int
    path: str
    windows: bool


class IncludedOutputSetCancelled(Exception):
    """Signal cancellation while a reversible output-set commit is active."""
