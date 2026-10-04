from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
import stat
from typing import Any, cast
from dataclasses import replace
from src.conversion.included_files_parts.models import (
    PathIdentity as _PathIdentity,
    PathFingerprint as _PathFingerprint,
    IncludedTreeEntry as _IncludedTreeEntry,
    IncludedTreeSnapshot as _IncludedTreeSnapshot,
    IncludedRegistrySnapshot as _IncludedRegistrySnapshot,
    IncludedRecoveryRecordSizes as _IncludedRecoveryRecordSizes,
    IncludedOutputSetTransaction as _IncludedOutputSetTransaction,
    IncludedRecoveryJournal as _IncludedRecoveryJournal,
    IncludedCommitMarker as _IncludedCommitMarker,
)
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata


def _included_identity_payload(identity: _PathIdentity | None) -> list[int] | None:
    return None if identity is None else [identity[0], identity[1]]


def _included_recovery_compact_integer_payload(
    value: int,
    label: str,
) -> str:
    if (
        type(value) is not int
        or value < 0
        or value > _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_MAX
    ):
        raise OSError(f"Included Files recovery {label} is outside uint64")
    return f"{value:0{_included_constants.INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS}x}"


def _included_compact_identity_payload(
    identity: _PathIdentity | None,
) -> list[str] | None:
    if identity is None:
        return None
    return [
        included_recovery_compact_integer_payload(
            identity[0],
            "identity device",
        ),
        included_recovery_compact_integer_payload(
            identity[1],
            "identity inode",
        ),
    ]


def _included_compact_fingerprint_payload(
    fingerprint: _PathFingerprint,
) -> list[str]:
    return [
        included_recovery_compact_integer_payload(
            component,
            "fingerprint component",
        )
        for component in fingerprint
    ]


def _included_tree_snapshot_payload(snapshot: _IncludedTreeSnapshot) -> dict[str, Any]:
    """Serialize the legacy format-v1 tree representation."""

    return {
        "root_fingerprint": (
            None
            if snapshot.root_fingerprint is None
            else list(snapshot.root_fingerprint)
        ),
        "entries": [
            {
                "relative_path": entry.relative_path,
                "kind": entry.kind,
                "fingerprint": list(entry.fingerprint),
                "ctime_ns": entry.ctime_ns,
                "content_sha256": entry.content_sha256,
            }
            for entry in snapshot.entries
        ],
    }


def _included_compact_tree_snapshot_payload(
    snapshot: _IncludedTreeSnapshot,
) -> list[Any]:
    """Serialize a format-v2 tree without per-entry field-name repetition."""

    if len(snapshot.entries) > _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError("Included Files recovery tree has too many entries")
    return [
        (
            None
            if snapshot.root_fingerprint is None
            else included_compact_fingerprint_payload(
                snapshot.root_fingerprint
            )
        ),
        [
            [
                entry.relative_path,
                "f" if entry.kind == "file" else "d",
                included_compact_fingerprint_payload(entry.fingerprint),
                (
                    None
                    if entry.ctime_ns is None
                    else included_recovery_compact_integer_payload(
                        entry.ctime_ns,
                        "entry ctime",
                    )
                ),
                entry.content_sha256,
            ]
            for entry in snapshot.entries
        ],
    ]


def _included_registry_snapshot_payload(
    snapshot: _IncludedRegistrySnapshot,
) -> dict[str, Any]:
    """Serialize the legacy format-v1 registry representation."""

    return {
        "directory_identity": included_identity_payload(
            snapshot.directory_identity
        ),
        "file_identity": included_identity_payload(snapshot.file_identity),
        "file_mode": snapshot.file_mode,
        "content_base64": (
            None
            if snapshot.content is None
            else base64.b64encode(snapshot.content).decode("ascii")
        ),
    }


def _included_compact_registry_snapshot_payload(
    snapshot: _IncludedRegistrySnapshot,
) -> list[Any]:
    return [
        included_compact_identity_payload(snapshot.directory_identity),
        included_compact_identity_payload(snapshot.file_identity),
        (
            None
            if snapshot.file_mode is None
            else included_recovery_compact_integer_payload(
                snapshot.file_mode,
                "registry mode",
            )
        ),
        (
            None
            if snapshot.content is None
            else base64.b64encode(snapshot.content).decode("ascii")
        ),
    ]


def _included_recovery_journal_payload_v1(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    transaction = journal.transaction
    registry_backup_location = _included_paths.included_registry_backup_location(journal)
    return {
        "format_version": _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "project_identity": included_identity_payload(transaction.project_identity),
        "stage_container_name": os.path.basename(transaction.stage_container_path),
        "stage_container_identity": included_identity_payload(
            transaction.stage_container_identity
        ),
        "staged_container_snapshot": included_tree_snapshot_payload(
            transaction.staged_container_snapshot
        ),
        "staged_root_snapshot": included_tree_snapshot_payload(
            transaction.staged_root_snapshot
        ),
        "staged_registry_identity": included_identity_payload(
            transaction.staged_registry_identity
        ),
        "staged_registry_mode": transaction.staged_registry_mode,
        "staged_registry_content_base64": base64.b64encode(
            transaction.staged_registry_content
        ).decode("ascii"),
        "previous_root_snapshot": included_tree_snapshot_payload(
            transaction.previous_root_snapshot
        ),
        "previous_registry_snapshot": included_registry_snapshot_payload(
            transaction.previous_registry_snapshot
        ),
        "root_backup_name": os.path.basename(journal.root_backup_path),
        "registry_backup_name": os.path.basename(journal.registry_backup_path),
        "registry_backup_location": registry_backup_location,
        "registry_directory_identity": included_identity_payload(
            journal.registry_directory_identity
        ),
        "registry_directory_created": journal.registry_directory_created,
    }


def _included_recovery_journal_payload_v2(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    transaction = journal.transaction
    registry_backup_location = _included_paths.included_registry_backup_location(journal)
    return {
        "format_version": _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        "state": "prepared",
        "transaction_id": journal.transaction_id,
        "project_identity": included_compact_identity_payload(
            transaction.project_identity
        ),
        "stage_container_name": os.path.basename(
            transaction.stage_container_path
        ),
        "stage_container_identity": included_compact_identity_payload(
            transaction.stage_container_identity
        ),
        "staged_container_snapshot": included_compact_tree_snapshot_payload(
            transaction.staged_container_snapshot
        ),
        "staged_root_snapshot": included_compact_tree_snapshot_payload(
            transaction.staged_root_snapshot
        ),
        "staged_registry_identity": included_compact_identity_payload(
            transaction.staged_registry_identity
        ),
        "staged_registry_mode": included_recovery_compact_integer_payload(
            transaction.staged_registry_mode,
            "staged registry mode",
        ),
        "staged_registry_content_base64": base64.b64encode(
            transaction.staged_registry_content
        ).decode("ascii"),
        "previous_root_snapshot": included_compact_tree_snapshot_payload(
            transaction.previous_root_snapshot
        ),
        "previous_registry_snapshot": included_compact_registry_snapshot_payload(
            transaction.previous_registry_snapshot
        ),
        "root_backup_name": os.path.basename(journal.root_backup_path),
        "registry_backup_name": os.path.basename(journal.registry_backup_path),
        "registry_backup_location": registry_backup_location,
        "registry_directory_identity": included_compact_identity_payload(
            journal.registry_directory_identity
        ),
        "registry_directory_created": journal.registry_directory_created,
    }


def _included_recovery_journal_payload(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    if journal.format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return included_recovery_journal_payload_v1(journal)
    if journal.format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return included_recovery_journal_payload_v2(journal)
    raise OSError("Unsupported Included Files recovery journal format")


def _included_tree_snapshot_sha256(
    snapshot: _IncludedTreeSnapshot,
    format_version: int,
) -> str:
    if format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        payload: Any = included_tree_snapshot_payload(snapshot)
        compact = False
    elif format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        payload = included_compact_tree_snapshot_payload(snapshot)
        compact = True
    else:
        raise OSError("Unsupported Included Files recovery tree digest format")
    return hashlib.sha256(
        included_serialized_json_content(
            {"tree_snapshot": payload},
            compact=compact,
        )
    ).hexdigest()


def _included_commit_marker_from_journal(
    journal: _IncludedRecoveryJournal,
) -> _IncludedCommitMarker:
    transaction = journal.transaction
    root_identity = transaction.staged_root_snapshot.identity
    if root_identity is None:
        raise AssertionError("A committed Included Files root must be present")
    return _IncludedCommitMarker(
        format_version=journal.format_version,
        transaction_id=journal.transaction_id,
        project_identity=transaction.project_identity,
        root_identity=root_identity,
        root_snapshot_sha256=included_tree_snapshot_sha256(
            transaction.staged_root_snapshot,
            journal.format_version,
        ),
        registry_directory_identity=journal.registry_directory_identity,
        registry_identity=transaction.staged_registry_identity,
        registry_content_sha256=hashlib.sha256(
            transaction.staged_registry_content
        ).hexdigest(),
    )


def _included_commit_marker_payload_v1(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    versioned_journal = replace(
        journal,
        format_version=_included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
    )
    marker = included_commit_marker_from_journal(versioned_journal)
    journal_payload = included_recovery_journal_payload_v1(
        versioned_journal
    )
    return {
        "format_version": _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
        "state": "committed",
        "transaction_id": marker.transaction_id,
        "project_identity": included_identity_payload(marker.project_identity),
        "root_identity": included_identity_payload(marker.root_identity),
        "root_snapshot_sha256": marker.root_snapshot_sha256,
        "registry_directory_identity": included_identity_payload(
            marker.registry_directory_identity
        ),
        "registry_identity": included_identity_payload(marker.registry_identity),
        "registry_content_sha256": marker.registry_content_sha256,
        "recovery_journal": journal_payload,
        "recovery_journal_sha256": hashlib.sha256(
            included_recovery_record_content(journal_payload)
        ).hexdigest(),
    }


def _included_commit_marker_payload_v2(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    versioned_journal = replace(
        journal,
        format_version=_included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
    )
    marker = included_commit_marker_from_journal(versioned_journal)
    journal_payload = included_recovery_journal_payload_v2(
        versioned_journal
    )
    return {
        "format_version": _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        "state": "committed",
        "transaction_id": marker.transaction_id,
        "project_identity": included_compact_identity_payload(
            marker.project_identity
        ),
        "root_identity": included_compact_identity_payload(
            marker.root_identity
        ),
        "root_snapshot_sha256": marker.root_snapshot_sha256,
        "registry_directory_identity": included_compact_identity_payload(
            marker.registry_directory_identity
        ),
        "registry_identity": included_compact_identity_payload(
            marker.registry_identity
        ),
        "registry_content_sha256": marker.registry_content_sha256,
        "recovery_journal": journal_payload,
        "recovery_journal_sha256": hashlib.sha256(
            included_recovery_record_content(journal_payload)
        ).hexdigest(),
    }


def _included_commit_marker_payload(
    journal: _IncludedRecoveryJournal,
) -> dict[str, Any]:
    if journal.format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return included_commit_marker_payload_v1(journal)
    if journal.format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return included_commit_marker_payload_v2(journal)
    raise OSError("Unsupported Included Files recovery commit format")


def _included_recovery_record_sizes(
    journal: _IncludedRecoveryJournal,
) -> _IncludedRecoveryRecordSizes:
    journal_content = included_recovery_record_content(
        included_recovery_journal_payload(journal)
    )
    commit_content = included_recovery_record_content(
        included_commit_marker_payload(journal)
    )
    return _IncludedRecoveryRecordSizes(
        journal_bytes=len(journal_content),
        commit_bytes=len(commit_content),
    )


def _included_preflight_placeholder_snapshots(
    project_identity: _PathIdentity,
    assigned_byte_counts: dict[str, int],
    staged_registry_content: bytes,
) -> tuple[
    _PathIdentity,
    _IncludedTreeSnapshot,
    _IncludedTreeSnapshot,
    _PathIdentity,
    int,
]:
    if len(assigned_byte_counts) > _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError("Included Files recovery tree has too many entries")
    device = project_identity[0]
    used_inodes = {project_identity[1]}
    next_inode = _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_MAX

    def allocate_identity() -> _PathIdentity:
        nonlocal next_inode
        while next_inode in used_inodes:
            next_inode -= 1
        if next_inode < 0:
            raise OSError("Could not allocate Included Files preflight identity")
        identity = (device, next_inode)
        used_inodes.add(next_inode)
        next_inode -= 1
        return identity

    def fingerprint(
        identity: _PathIdentity,
        mode: int,
        size: int,
    ) -> _PathFingerprint:
        return (identity[0], identity[1], mode, size, 0, 1)

    assigned_paths = sorted(assigned_byte_counts)
    directory_paths = sorted(
        {
            "/".join(path.split("/")[:component_count])
            for path in assigned_paths
            for component_count in range(1, len(path.split("/")))
        }
    )
    if len(assigned_paths) + len(directory_paths) > (
        _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES
    ):
        raise OSError("Included Files recovery tree has too many entries")
    for relative_path in (*directory_paths, *assigned_paths):
        _included_paths.included_recovery_relative_path(relative_path)

    staged_root_identity = allocate_identity()
    staged_root_fingerprint = fingerprint(
        staged_root_identity,
        stat.S_IFDIR | 0o755,
        0,
    )
    entry_kinds = {
        **{path: "directory" for path in directory_paths},
        **{path: "file" for path in assigned_paths},
    }
    staged_root_entries: list[_IncludedTreeEntry] = []
    for relative_path in sorted(entry_kinds):
        kind = entry_kinds[relative_path]
        identity = allocate_identity()
        if kind == "directory":
            staged_root_entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=fingerprint(
                        identity,
                        stat.S_IFDIR | 0o755,
                        0,
                    ),
                    ctime_ns=None,
                    content_sha256=None,
                )
            )
        else:
            byte_count = assigned_byte_counts[relative_path]
            staged_root_entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=fingerprint(
                        identity,
                        stat.S_IFREG | 0o600,
                        byte_count,
                    ),
                    ctime_ns=0,
                    content_sha256=(
                        _included_constants.INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256
                    ),
                )
            )
    staged_root_snapshot = _IncludedTreeSnapshot(
        root_fingerprint=staged_root_fingerprint,
        entries=tuple(staged_root_entries),
    )

    stage_container_identity = allocate_identity()
    stage_marker_identity = allocate_identity()
    staged_registry_identity = allocate_identity()
    staged_registry_mode = 0o600
    stage_marker_content = included_recovery_record_content(
        {
            "format_version": _included_constants.INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": included_identity_payload(project_identity),
            "stage_identity": included_identity_payload(
                stage_container_identity
            ),
        }
    )
    container_entries = [
        _IncludedTreeEntry(
            relative_path=_included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
            kind="file",
            fingerprint=fingerprint(
                stage_marker_identity,
                stat.S_IFREG | 0o600,
                len(stage_marker_content),
            ),
            ctime_ns=0,
            content_sha256=hashlib.sha256(stage_marker_content).hexdigest(),
        ),
        _IncludedTreeEntry(
            relative_path=_included_constants.INCLUDED_FILES_ROOT_NAME,
            kind="directory",
            fingerprint=staged_root_fingerprint,
            ctime_ns=None,
            content_sha256=None,
        ),
        *(
            _IncludedTreeEntry(
                relative_path=(
                    _included_constants.INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
                ),
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=entry.content_sha256,
            )
            for entry in staged_root_entries
        ),
        _IncludedTreeEntry(
            relative_path="gml_included_file_registry.gd",
            kind="file",
            fingerprint=fingerprint(
                staged_registry_identity,
                stat.S_IFREG | staged_registry_mode,
                len(staged_registry_content),
            ),
            ctime_ns=0,
            content_sha256=hashlib.sha256(
                staged_registry_content
            ).hexdigest(),
        ),
    ]
    staged_container_snapshot = _IncludedTreeSnapshot(
        root_fingerprint=fingerprint(
            stage_container_identity,
            stat.S_IFDIR | 0o700,
            0,
        ),
        entries=tuple(
            sorted(
                container_entries,
                key=lambda entry: entry.relative_path,
            )
        ),
    )
    return (
        stage_container_identity,
        staged_container_snapshot,
        staged_root_snapshot,
        staged_registry_identity,
        staged_registry_mode,
    )


def _preflight_included_recovery_record_sizes(
    project_path: str,
    project_identity: _PathIdentity,
    assigned_byte_counts: dict[str, int],
    staged_registry_content: bytes,
    previous_root_snapshot: _IncludedTreeSnapshot,
    previous_registry_snapshot: _IncludedRegistrySnapshot,
) -> _IncludedRecoveryRecordSizes:
    """Serialize exact-size format-v2 stand-ins before payload staging."""

    try:
        (
            stage_container_identity,
            staged_container_snapshot,
            staged_root_snapshot,
            staged_registry_identity,
            staged_registry_mode,
        ) = included_preflight_placeholder_snapshots(
            project_identity,
            assigned_byte_counts,
            staged_registry_content,
        )
        token = "0" * 16
        stage_container_path = os.path.join(
            project_path,
            _included_constants.INCLUDED_FILES_STAGE_PREFIX + token + ".stage",
        )
        registry_directory_path = os.path.dirname(
            _included_paths.included_registry_path(project_path)
        )
        registry_directory_created = (
            previous_registry_snapshot.directory_identity is None
        )
        registry_directory_identity = (
            previous_registry_snapshot.directory_identity
            or (
                project_identity[0],
                _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_MAX - 4,
            )
        )
        registry_backup_parent = (
            registry_directory_path
            if previous_registry_snapshot.file_identity is not None
            else project_path
        )
        transaction = _IncludedOutputSetTransaction(
            project_identity=project_identity,
            stage_container_path=stage_container_path,
            stage_container_identity=stage_container_identity,
            staged_container_snapshot=staged_container_snapshot,
            staged_root_path=os.path.join(
                stage_container_path,
                _included_constants.INCLUDED_FILES_ROOT_NAME,
            ),
            staged_root_snapshot=staged_root_snapshot,
            staged_registry_path=os.path.join(
                stage_container_path,
                "gml_included_file_registry.gd",
            ),
            staged_registry_identity=staged_registry_identity,
            staged_registry_mode=staged_registry_mode,
            staged_registry_content=staged_registry_content,
            previous_root_snapshot=previous_root_snapshot,
            previous_registry_snapshot=previous_registry_snapshot,
        )
        journal = _IncludedRecoveryJournal(
            format_version=_included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
            transaction_id="0" * 32,
            transaction=transaction,
            root_backup_path=os.path.join(
                project_path,
                f".included_files.{token}.backup",
            ),
            registry_backup_path=os.path.join(
                registry_backup_parent,
                f".gml_included_file_registry.gd.{token}.backup",
            ),
            registry_directory_path=registry_directory_path,
            registry_directory_identity=registry_directory_identity,
            registry_directory_created=registry_directory_created,
        )
        return included_recovery_record_sizes(journal)
    except OSError as error:
        raise OSError(
            "Included Files recovery metadata preflight failed before payload "
            f"staging: {error}"
        ) from error


def _verify_included_recovery_record_sizes(
    expected: _IncludedRecoveryRecordSizes,
    journal: _IncludedRecoveryJournal,
) -> None:
    actual = included_recovery_record_sizes(journal)
    if actual != expected:
        raise OSError(
            "Included Files recovery metadata changed after its byte-accurate "
            "preflight"
        )


def _included_recovery_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OSError(f"Invalid Included Files recovery {label}")
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(dict[str, Any], mapping)


def _included_recovery_exact_keys(
    payload: dict[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    if payload.keys() != expected:
        raise OSError(f"Invalid Included Files recovery {label} fields")


def _included_recovery_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_compact_int(value: Any, label: str) -> int:
    if (
        not isinstance(value, str)
        or len(value) != _included_constants.INCLUDED_FILES_RECOVERY_INTEGER_HEX_DIGITS
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return int(value, 16)


def _included_recovery_identity(
    value: Any,
    label: str,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if value is None and optional:
        return None
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    first = included_recovery_int(components[0], label)
    second = included_recovery_int(components[1], label)
    if first < 0 or second < 0:
        raise OSError(f"Invalid Included Files recovery {label}")
    return (first, second)


def _included_recovery_compact_identity(
    value: Any,
    label: str,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if value is None and optional:
        return None
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    return (
        included_recovery_compact_int(components[0], label),
        included_recovery_compact_int(components[1], label),
    )


def _included_recovery_identity_for_format(
    value: Any,
    label: str,
    format_version: int,
    *,
    optional: bool = False,
) -> _PathIdentity | None:
    if format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return included_recovery_identity(
            value,
            label,
            optional=optional,
        )
    if format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return included_recovery_compact_identity(
            value,
            label,
            optional=optional,
        )
    raise OSError("Unsupported Included Files recovery identity format")


def _included_recovery_fingerprint(value: Any, label: str) -> _PathFingerprint:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 6:
        raise OSError(f"Invalid Included Files recovery {label}")
    fingerprint = tuple(
        included_recovery_int(component, label) for component in components
    )
    if any(component < 0 for component in fingerprint):
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(_PathFingerprint, fingerprint)


def _included_recovery_compact_fingerprint(
    value: Any,
    label: str,
) -> _PathFingerprint:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 6:
        raise OSError(f"Invalid Included Files recovery {label}")
    return cast(
        _PathFingerprint,
        tuple(
            included_recovery_compact_int(component, label)
            for component in components
        ),
    )


def _included_recovery_sha256(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OSError(f"Invalid Included Files recovery {label}")
    return value


def _included_recovery_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise OSError(f"Invalid Included Files recovery {label}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise OSError(f"Invalid Included Files recovery {label}") from error
    if base64.b64encode(decoded).decode("ascii") != value:
        raise OSError(f"Non-canonical Included Files recovery {label}")
    return decoded


def _included_tree_snapshot_from_payload_v1(
    value: Any,
    label: str,
) -> _IncludedTreeSnapshot:
    payload = included_recovery_dict(value, label)
    included_recovery_exact_keys(
        payload,
        frozenset({"root_fingerprint", "entries"}),
        label,
    )
    root_value = payload.get("root_fingerprint")
    root_fingerprint = (
        None
        if root_value is None
        else included_recovery_fingerprint(
            root_value,
            label + " root fingerprint",
        )
    )
    entries_value = payload.get("entries")
    if not isinstance(entries_value, list):
        raise OSError(f"Invalid Included Files recovery {label} entries")
    raw_entries = cast(list[Any], entries_value)
    if len(raw_entries) > _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError(f"Included Files recovery {label} has too many entries")
    entries: list[_IncludedTreeEntry] = []
    seen_paths: set[str] = set()
    for raw_entry in raw_entries:
        entry_payload = included_recovery_dict(raw_entry, label + " entry")
        included_recovery_exact_keys(
            entry_payload,
            frozenset(
                {
                    "relative_path",
                    "kind",
                    "fingerprint",
                    "ctime_ns",
                    "content_sha256",
                }
            ),
            label + " entry",
        )
        relative_path = _included_paths.included_recovery_relative_path(
            entry_payload.get("relative_path")
        )
        if relative_path in seen_paths:
            raise OSError(f"Duplicate Included Files recovery tree path: {relative_path}")
        seen_paths.add(relative_path)
        kind = entry_payload.get("kind")
        if not isinstance(kind, str) or kind not in {"file", "directory"}:
            raise OSError(f"Invalid Included Files recovery tree kind: {relative_path}")
        fingerprint = included_recovery_fingerprint(
            entry_payload.get("fingerprint"),
            label + " entry fingerprint",
        )
        expected_kind = stat.S_IFREG if kind == "file" else stat.S_IFDIR
        if stat.S_IFMT(fingerprint[2]) != expected_kind:
            raise OSError(f"Invalid Included Files recovery tree mode: {relative_path}")
        ctime_value = entry_payload.get("ctime_ns")
        ctime_ns = (
            None
            if ctime_value is None
            else included_recovery_int(ctime_value, label + " entry ctime")
        )
        content_sha256 = included_recovery_sha256(
            entry_payload.get("content_sha256"),
            label + " entry content digest",
        )
        if kind == "directory":
            if ctime_ns is not None or content_sha256 is not None:
                raise OSError(
                    "Invalid Included Files recovery directory receipt: "
                    + relative_path
                )
        elif ctime_ns is None or ctime_ns < 0 or content_sha256 is None:
            raise OSError(
                "Incomplete Included Files recovery file receipt: " + relative_path
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    return _included_metadata.validated_included_tree_snapshot(
        root_fingerprint,
        entries,
        label,
    )


def _included_tree_snapshot_from_payload_v2(
    value: Any,
    label: str,
) -> _IncludedTreeSnapshot:
    if not isinstance(value, list):
        raise OSError(f"Invalid Included Files recovery {label}")
    components = cast(list[Any], value)
    if len(components) != 2:
        raise OSError(f"Invalid Included Files recovery {label}")
    root_value, entries_value = components
    root_fingerprint = (
        None
        if root_value is None
        else included_recovery_compact_fingerprint(
            root_value,
            label + " root fingerprint",
        )
    )
    if not isinstance(entries_value, list):
        raise OSError(f"Invalid Included Files recovery {label} entries")
    raw_entries = cast(list[Any], entries_value)
    if len(raw_entries) > _included_constants.INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES:
        raise OSError(f"Included Files recovery {label} has too many entries")

    entries: list[_IncludedTreeEntry] = []
    seen_paths: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, list):
            raise OSError(f"Invalid Included Files recovery {label} entry")
        entry_components = cast(list[Any], raw_entry)
        if len(entry_components) != 5:
            raise OSError(f"Invalid Included Files recovery {label} entry")
        (
            path_value,
            kind_value,
            fingerprint_value,
            ctime_value,
            digest_value,
        ) = entry_components
        relative_path = _included_paths.included_recovery_relative_path(path_value)
        if relative_path in seen_paths:
            raise OSError(
                f"Duplicate Included Files recovery tree path: {relative_path}"
            )
        seen_paths.add(relative_path)
        if kind_value == "f":
            kind = "file"
        elif kind_value == "d":
            kind = "directory"
        else:
            raise OSError(
                f"Invalid Included Files recovery tree kind: {relative_path}"
            )
        fingerprint = included_recovery_compact_fingerprint(
            fingerprint_value,
            label + " entry fingerprint",
        )
        expected_kind = stat.S_IFREG if kind == "file" else stat.S_IFDIR
        if stat.S_IFMT(fingerprint[2]) != expected_kind:
            raise OSError(
                f"Invalid Included Files recovery tree mode: {relative_path}"
            )
        ctime_ns = (
            None
            if ctime_value is None
            else included_recovery_compact_int(
                ctime_value,
                label + " entry ctime",
            )
        )
        content_sha256 = included_recovery_sha256(
            digest_value,
            label + " entry content digest",
        )
        if kind == "directory":
            if ctime_ns is not None or content_sha256 is not None:
                raise OSError(
                    "Invalid Included Files recovery directory receipt: "
                    + relative_path
                )
        elif ctime_ns is None or content_sha256 is None:
            raise OSError(
                "Incomplete Included Files recovery file receipt: "
                + relative_path
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    return _included_metadata.validated_included_tree_snapshot(
        root_fingerprint,
        entries,
        label,
    )


def _included_tree_snapshot_from_payload(
    value: Any,
    label: str,
    *,
    format_version: int = _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
) -> _IncludedTreeSnapshot:
    if format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return included_tree_snapshot_from_payload_v1(value, label)
    if format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return included_tree_snapshot_from_payload_v2(value, label)
    raise OSError("Unsupported Included Files recovery tree format")


def _included_registry_snapshot_from_payload_v1(
    value: Any,
) -> _IncludedRegistrySnapshot:
    payload = included_recovery_dict(value, "registry snapshot")
    included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "directory_identity",
                "file_identity",
                "file_mode",
                "content_base64",
            }
        ),
        "registry snapshot",
    )
    directory_identity = included_recovery_identity(
        payload.get("directory_identity"),
        "registry directory identity",
        optional=True,
    )
    file_identity = included_recovery_identity(
        payload.get("file_identity"),
        "registry file identity",
        optional=True,
    )
    file_mode_value = payload.get("file_mode")
    file_mode = (
        None
        if file_mode_value is None
        else included_recovery_int(file_mode_value, "registry file mode")
    )
    if file_mode is not None and (
        file_mode < 0 or stat.S_IMODE(file_mode) != file_mode
    ):
        raise OSError("Invalid Included File registry recovery mode")
    content_value = payload.get("content_base64")
    content = (
        None
        if content_value is None
        else included_recovery_bytes(content_value, "registry content")
    )
    if file_identity is None:
        if file_mode is not None or content is not None:
            raise OSError("Invalid absent Included File registry recovery state")
    elif directory_identity is None or file_mode is None or content is None:
        raise OSError("Incomplete Included File registry recovery state")
    elif file_identity[0] != directory_identity[0]:
        raise OSError("Invalid cross-device Included File registry recovery state")
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )


def _included_registry_snapshot_from_payload_v2(
    value: Any,
) -> _IncludedRegistrySnapshot:
    if not isinstance(value, list):
        raise OSError("Invalid Included Files recovery registry snapshot")
    components = cast(list[Any], value)
    if len(components) != 4:
        raise OSError("Invalid Included Files recovery registry snapshot")
    (
        directory_identity_value,
        file_identity_value,
        file_mode_value,
        content_value,
    ) = components
    directory_identity = included_recovery_compact_identity(
        directory_identity_value,
        "registry directory identity",
        optional=True,
    )
    file_identity = included_recovery_compact_identity(
        file_identity_value,
        "registry file identity",
        optional=True,
    )
    file_mode = (
        None
        if file_mode_value is None
        else included_recovery_compact_int(
            file_mode_value,
            "registry file mode",
        )
    )
    if file_mode is not None and stat.S_IMODE(file_mode) != file_mode:
        raise OSError("Invalid Included File registry recovery mode")
    content = (
        None
        if content_value is None
        else included_recovery_bytes(content_value, "registry content")
    )
    if file_identity is None:
        if file_mode is not None or content is not None:
            raise OSError("Invalid absent Included File registry recovery state")
    elif directory_identity is None or file_mode is None or content is None:
        raise OSError("Incomplete Included File registry recovery state")
    elif file_identity[0] != directory_identity[0]:
        raise OSError(
            "Invalid cross-device Included File registry recovery state"
        )
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )


def _included_registry_snapshot_from_payload(
    value: Any,
    *,
    format_version: int = _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
) -> _IncludedRegistrySnapshot:
    if format_version == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION:
        return included_registry_snapshot_from_payload_v1(value)
    if format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION:
        return included_registry_snapshot_from_payload_v2(value)
    raise OSError("Unsupported Included Files recovery registry format")


def _included_recovery_journal_from_payload(
    project_path: str,
    project_identity: _PathIdentity,
    value: Any,
) -> _IncludedRecoveryJournal:
    payload = included_recovery_dict(value, "journal")
    included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "project_identity",
                "stage_container_name",
                "stage_container_identity",
                "staged_container_snapshot",
                "staged_root_snapshot",
                "staged_registry_identity",
                "staged_registry_mode",
                "staged_registry_content_base64",
                "previous_root_snapshot",
                "previous_registry_snapshot",
                "root_backup_name",
                "registry_backup_name",
                "registry_backup_location",
                "registry_directory_identity",
                "registry_directory_created",
            }
        ),
        "journal",
    )
    format_version = included_recovery_int(
        payload.get("format_version"),
        "journal format version",
    )
    if (
        format_version
        not in {
            _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
            _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        }
        or payload.get("state") != "prepared"
    ):
        raise OSError("Unsupported Included Files recovery journal")
    transaction_id = _included_paths.included_recovery_token(
        payload.get("transaction_id"),
        32,
        "transaction id",
    )
    recorded_project_identity = included_recovery_identity_for_format(
        payload.get("project_identity"),
        "project identity",
        format_version,
    )
    if recorded_project_identity != project_identity:
        raise OSError("Godot project root changed since Included Files interruption")
    stage_container_name = _included_paths.included_recovery_managed_name(
        payload.get("stage_container_name"),
        prefix=_included_constants.INCLUDED_FILES_STAGE_PREFIX,
        suffix=".stage",
        label="stage container",
    )
    stage_container_identity = included_recovery_identity_for_format(
        payload.get("stage_container_identity"),
        "stage container identity",
        format_version,
    )
    if stage_container_identity is None:
        raise OSError("Missing Included Files recovery stage identity")
    staged_container_snapshot = included_tree_snapshot_from_payload(
        payload.get("staged_container_snapshot"),
        "staged container snapshot",
        format_version=format_version,
    )
    if staged_container_snapshot.identity != stage_container_identity:
        raise OSError("Included Files recovery stage snapshot identity mismatch")
    staged_root_snapshot = included_tree_snapshot_from_payload(
        payload.get("staged_root_snapshot"),
        "staged root snapshot",
        format_version=format_version,
    )
    if staged_root_snapshot.identity is None:
        raise OSError("Missing Included Files recovery staged root")
    staged_registry_identity = included_recovery_identity_for_format(
        payload.get("staged_registry_identity"),
        "staged registry identity",
        format_version,
    )
    if staged_registry_identity is None:
        raise OSError("Missing Included Files recovery staged registry")
    staged_registry_mode = (
        included_recovery_int(
            payload.get("staged_registry_mode"),
            "staged registry mode",
        )
        if format_version
        == _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
        else included_recovery_compact_int(
            payload.get("staged_registry_mode"),
            "staged registry mode",
        )
    )
    if (
        staged_registry_mode < 0
        or stat.S_IMODE(staged_registry_mode) != staged_registry_mode
    ):
        raise OSError("Invalid Included Files recovery staged registry mode")
    staged_registry_content = included_recovery_bytes(
        payload.get("staged_registry_content_base64"),
        "staged registry content",
    )
    previous_root_snapshot = included_tree_snapshot_from_payload(
        payload.get("previous_root_snapshot"),
        "previous root snapshot",
        format_version=format_version,
    )
    previous_registry_snapshot = included_registry_snapshot_from_payload(
        payload.get("previous_registry_snapshot"),
        format_version=format_version,
    )
    staged_entries = {
        entry.relative_path: entry
        for entry in staged_container_snapshot.entries
    }
    staged_root_entry = staged_entries.get(_included_constants.INCLUDED_FILES_ROOT_NAME)
    staged_registry_entry = staged_entries.get("gml_included_file_registry.gd")
    staged_marker_entry = staged_entries.get(_included_constants.INCLUDED_FILES_STAGE_MARKER_NAME)
    expected_stage_marker_content = included_recovery_record_content(
        {
            "format_version": _included_constants.INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION,
            "state": "staging",
            "project_identity": included_identity_payload(project_identity),
            "stage_identity": included_identity_payload(stage_container_identity),
        }
    )
    expected_staged_paths = {
        _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
        _included_constants.INCLUDED_FILES_ROOT_NAME,
        "gml_included_file_registry.gd",
        *(
            _included_constants.INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path
            for entry in staged_root_snapshot.entries
        ),
    }
    staged_root_entries = {
        _included_constants.INCLUDED_FILES_ROOT_NAME + "/" + entry.relative_path: entry
        for entry in staged_root_snapshot.entries
    }
    if (
        set(staged_entries) != expected_staged_paths
        or staged_root_entry is None
        or staged_root_entry.kind != "directory"
        or staged_root_entry.fingerprint != staged_root_snapshot.root_fingerprint
        or staged_registry_entry is None
        or staged_registry_entry.kind != "file"
        or staged_registry_entry.fingerprint[:2] != staged_registry_identity
        or stat.S_IMODE(staged_registry_entry.fingerprint[2])
        != staged_registry_mode
        or staged_registry_entry.fingerprint[3] != len(staged_registry_content)
        or staged_registry_entry.content_sha256
        != hashlib.sha256(staged_registry_content).hexdigest()
        or staged_marker_entry is None
        or staged_marker_entry.kind != "file"
        or staged_marker_entry.content_sha256
        != hashlib.sha256(expected_stage_marker_content).hexdigest()
        or staged_marker_entry.fingerprint[3] != len(expected_stage_marker_content)
        or any(
            (
                staged_entries[path].kind != expected_entry.kind
                or staged_entries[path].fingerprint != expected_entry.fingerprint
                or staged_entries[path].ctime_ns != expected_entry.ctime_ns
                or staged_entries[path].content_sha256
                != expected_entry.content_sha256
            )
            for path, expected_entry in staged_root_entries.items()
        )
    ):
        raise OSError("Included Files recovery staged snapshots disagree")
    root_backup_name = _included_paths.included_recovery_managed_name(
        payload.get("root_backup_name"),
        prefix=".included_files.",
        suffix=".backup",
        label="root backup",
    )
    registry_backup_name = _included_paths.included_recovery_managed_name(
        payload.get("registry_backup_name"),
        prefix=".gml_included_file_registry.gd.",
        suffix=".backup",
        label="registry backup",
    )
    registry_backup_location = payload.get("registry_backup_location")
    if (
        not isinstance(registry_backup_location, str)
        or registry_backup_location not in {"project", "registry"}
    ):
        raise OSError("Invalid Included File registry recovery backup location")
    expected_registry_backup_location = (
        "registry"
        if previous_registry_snapshot.file_identity is not None
        else "project"
    )
    if registry_backup_location != expected_registry_backup_location:
        raise OSError("Included File registry recovery backup location disagrees")
    registry_directory_identity = included_recovery_identity_for_format(
        payload.get("registry_directory_identity"),
        "registry directory identity",
        format_version,
    )
    if registry_directory_identity is None:
        raise OSError("Missing Included File registry recovery directory")
    registry_directory_created = payload.get("registry_directory_created")
    if type(registry_directory_created) is not bool:
        raise OSError("Invalid Included File registry recovery directory state")
    previous_directory_identity = previous_registry_snapshot.directory_identity
    if registry_directory_created:
        if previous_directory_identity is not None:
            raise OSError("Invalid created Included File registry recovery directory")
    elif previous_directory_identity != registry_directory_identity:
        raise OSError("Included File registry recovery directory identity mismatch")
    managed_identities = (
        stage_container_identity,
        staged_root_snapshot.identity,
        staged_registry_identity,
        previous_root_snapshot.identity,
        previous_registry_snapshot.directory_identity,
        previous_registry_snapshot.file_identity,
        registry_directory_identity,
    )
    if any(
        identity is not None and identity[0] != project_identity[0]
        for identity in managed_identities
    ):
        raise OSError(
            "Included Files recovery state crosses the Godot project filesystem"
        )
    if (
        staged_root_snapshot.identity == previous_root_snapshot.identity
        and previous_root_snapshot.identity is not None
    ):
        raise OSError("Included Files staged and previous roots alias")
    if (
        staged_registry_identity == previous_registry_snapshot.file_identity
        and previous_registry_snapshot.file_identity is not None
    ):
        raise OSError("Included File staged and previous registries alias")
    if stage_container_identity in {
        project_identity,
        staged_root_snapshot.identity,
        registry_directory_identity,
    }:
        raise OSError("Included Files recovery directories alias")

    project_path = os.path.abspath(project_path)
    stage_container_path = os.path.join(project_path, stage_container_name)
    registry_directory_path = os.path.dirname(_included_paths.included_registry_path(project_path))
    registry_backup_parent = (
        project_path
        if registry_backup_location == "project"
        else registry_directory_path
    )
    transaction = _IncludedOutputSetTransaction(
        project_identity=project_identity,
        stage_container_path=stage_container_path,
        stage_container_identity=stage_container_identity,
        staged_container_snapshot=staged_container_snapshot,
        staged_root_path=os.path.join(
            stage_container_path,
            _included_constants.INCLUDED_FILES_ROOT_NAME,
        ),
        staged_root_snapshot=staged_root_snapshot,
        staged_registry_path=os.path.join(
            stage_container_path,
            "gml_included_file_registry.gd",
        ),
        staged_registry_identity=staged_registry_identity,
        staged_registry_mode=staged_registry_mode,
        staged_registry_content=staged_registry_content,
        previous_root_snapshot=previous_root_snapshot,
        previous_registry_snapshot=previous_registry_snapshot,
    )
    return _IncludedRecoveryJournal(
        format_version=format_version,
        transaction_id=transaction_id,
        transaction=transaction,
        root_backup_path=os.path.join(project_path, root_backup_name),
        registry_backup_path=os.path.join(
            registry_backup_parent,
            registry_backup_name,
        ),
        registry_directory_path=registry_directory_path,
        registry_directory_identity=registry_directory_identity,
        registry_directory_created=registry_directory_created,
    )


def _included_serialized_json_content(
    payload: Any,
    *,
    compact: bool,
) -> bytes:
    if compact:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    return (rendered + "\n").encode("utf-8")


def _included_recovery_record_content(payload: dict[str, Any]) -> bytes:
    format_version = payload.get("format_version")
    content = included_serialized_json_content(
        payload,
        compact=(
            type(format_version) is int
            and format_version == _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION
        ),
    )
    if len(content) > _included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES:
        raise OSError(
            "Generated Included Files recovery record exceeds the canonical "
            "size limit of "
            f"{_included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES} bytes"
        )
    return content


def _included_commit_marker_and_journal_from_payload(
    project_path: str,
    payload: dict[str, Any],
    project_identity: _PathIdentity,
) -> tuple[_IncludedCommitMarker, _IncludedRecoveryJournal]:
    included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "transaction_id",
                "project_identity",
                "root_identity",
                "root_snapshot_sha256",
                "registry_directory_identity",
                "registry_identity",
                "registry_content_sha256",
                "recovery_journal",
                "recovery_journal_sha256",
            }
        ),
        "commit marker",
    )
    format_version = included_recovery_int(
        payload.get("format_version"),
        "commit marker format version",
    )
    if (
        format_version
        not in {
            _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION,
            _included_constants.INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        }
        or payload.get("state") != "committed"
    ):
        raise OSError("Unsupported Included Files recovery commit marker")
    transaction_id = _included_paths.included_recovery_token(
        payload.get("transaction_id"),
        32,
        "commit transaction id",
    )
    recorded_project_identity = included_recovery_identity_for_format(
        payload.get("project_identity"),
        "commit project identity",
        format_version,
    )
    if recorded_project_identity != project_identity:
        raise OSError("Included Files commit marker belongs to another project")
    root_identity = included_recovery_identity_for_format(
        payload.get("root_identity"),
        "commit root identity",
        format_version,
    )
    registry_directory_identity = included_recovery_identity_for_format(
        payload.get("registry_directory_identity"),
        "commit registry directory identity",
        format_version,
    )
    registry_identity = included_recovery_identity_for_format(
        payload.get("registry_identity"),
        "commit registry identity",
        format_version,
    )
    root_snapshot_sha256 = included_recovery_sha256(
        payload.get("root_snapshot_sha256"),
        "commit root snapshot digest",
    )
    registry_content_sha256 = included_recovery_sha256(
        payload.get("registry_content_sha256"),
        "commit registry content digest",
    )
    if (
        root_identity is None
        or registry_directory_identity is None
        or registry_identity is None
        or root_snapshot_sha256 is None
        or registry_content_sha256 is None
    ):
        raise OSError("Incomplete Included Files recovery commit marker")
    marker = _IncludedCommitMarker(
        format_version=format_version,
        transaction_id=transaction_id,
        project_identity=project_identity,
        root_identity=root_identity,
        root_snapshot_sha256=root_snapshot_sha256,
        registry_directory_identity=registry_directory_identity,
        registry_identity=registry_identity,
        registry_content_sha256=registry_content_sha256,
    )
    journal_payload = included_recovery_dict(
        payload.get("recovery_journal"),
        "commit recovery journal",
    )
    journal_sha256 = included_recovery_sha256(
        payload.get("recovery_journal_sha256"),
        "commit recovery journal digest",
    )
    if (
        journal_sha256 is None
        or hashlib.sha256(
            included_recovery_record_content(journal_payload)
        ).hexdigest()
        != journal_sha256
    ):
        raise OSError("Included Files commit recovery journal digest mismatch")
    journal = included_recovery_journal_from_payload(
        project_path,
        project_identity,
        journal_payload,
    )
    if journal.format_version != format_version:
        raise OSError("Included Files commit recovery journal format mismatch")
    if marker != included_commit_marker_from_journal(journal):
        raise OSError("Included Files commit recovery journal disagrees with marker")
    return marker, journal


def _included_stage_marker_matches(
    payload: dict[str, Any],
    project_identity: _PathIdentity,
    stage_identity: _PathIdentity,
) -> bool:
    included_recovery_exact_keys(
        payload,
        frozenset(
            {
                "format_version",
                "state",
                "project_identity",
                "stage_identity",
            }
        ),
        "stage marker",
    )
    return (
        included_recovery_int(
            payload.get("format_version"),
            "stage marker format version",
        )
        == _included_constants.INCLUDED_FILES_STAGE_MARKER_FORMAT_VERSION
        and payload.get("state") == "staging"
        and included_recovery_identity(
            payload.get("project_identity"),
            "stage project identity",
        )
        == project_identity
        and included_recovery_identity(
            payload.get("stage_identity"),
            "stage identity",
        )
        == stage_identity
    )


# Finite compatibility exports; each operation has one actual owner.
included_identity_payload = _included_identity_payload
included_recovery_compact_integer_payload = _included_recovery_compact_integer_payload
included_compact_identity_payload = _included_compact_identity_payload
included_compact_fingerprint_payload = _included_compact_fingerprint_payload
included_tree_snapshot_payload = _included_tree_snapshot_payload
included_compact_tree_snapshot_payload = _included_compact_tree_snapshot_payload
included_registry_snapshot_payload = _included_registry_snapshot_payload
included_compact_registry_snapshot_payload = _included_compact_registry_snapshot_payload
included_recovery_journal_payload_v1 = _included_recovery_journal_payload_v1
included_recovery_journal_payload_v2 = _included_recovery_journal_payload_v2
included_recovery_journal_payload = _included_recovery_journal_payload
included_tree_snapshot_sha256 = _included_tree_snapshot_sha256
included_commit_marker_from_journal = _included_commit_marker_from_journal
included_commit_marker_payload_v1 = _included_commit_marker_payload_v1
included_commit_marker_payload_v2 = _included_commit_marker_payload_v2
included_commit_marker_payload = _included_commit_marker_payload
included_recovery_record_sizes = _included_recovery_record_sizes
included_preflight_placeholder_snapshots = _included_preflight_placeholder_snapshots
preflight_included_recovery_record_sizes = _preflight_included_recovery_record_sizes
verify_included_recovery_record_sizes = _verify_included_recovery_record_sizes
included_recovery_dict = _included_recovery_dict
included_recovery_exact_keys = _included_recovery_exact_keys
included_recovery_int = _included_recovery_int
included_recovery_compact_int = _included_recovery_compact_int
included_recovery_identity = _included_recovery_identity
included_recovery_compact_identity = _included_recovery_compact_identity
included_recovery_identity_for_format = _included_recovery_identity_for_format
included_recovery_fingerprint = _included_recovery_fingerprint
included_recovery_compact_fingerprint = _included_recovery_compact_fingerprint
included_recovery_sha256 = _included_recovery_sha256
included_recovery_bytes = _included_recovery_bytes
included_tree_snapshot_from_payload_v1 = _included_tree_snapshot_from_payload_v1
included_tree_snapshot_from_payload_v2 = _included_tree_snapshot_from_payload_v2
included_tree_snapshot_from_payload = _included_tree_snapshot_from_payload
included_registry_snapshot_from_payload_v1 = _included_registry_snapshot_from_payload_v1
included_registry_snapshot_from_payload_v2 = _included_registry_snapshot_from_payload_v2
included_registry_snapshot_from_payload = _included_registry_snapshot_from_payload
included_recovery_journal_from_payload = _included_recovery_journal_from_payload
included_serialized_json_content = _included_serialized_json_content
included_recovery_record_content = _included_recovery_record_content
included_commit_marker_and_journal_from_payload = _included_commit_marker_and_journal_from_payload
included_stage_marker_matches = _included_stage_marker_matches
