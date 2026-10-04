from __future__ import annotations
import os
import posixpath
import stat
from typing import Callable, cast
from src.conversion.included_files_parts.models import (
    PathIdentity as _PathIdentity,
    PathFingerprint as _PathFingerprint,
    PathHandleBinding as _PathHandleBinding,
    HandleState as _HandleState,
    IncludedSourceFingerprint as _IncludedSourceFingerprint,
    IncludedCleanupFileState as _IncludedCleanupFileState,
    IncludedCopyReceipt as _IncludedCopyReceipt,
    IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt,
    IncludedGenerationContentReceipt as _IncludedGenerationContentReceipt,
    IncludedTreeEntry as _IncludedTreeEntry,
    IncludedTreeSnapshot as _IncludedTreeSnapshot,
)
from src.conversion.included_file_paths import IncludedFilePathAssignment


def _directory_identity_from_fd(directory_fd: int) -> _PathIdentity:
    directory_stat = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OSError("Pinned Included Files descriptor is not a directory")
    return directory_stat.st_dev, directory_stat.st_ino


def _verify_included_directory_fd(
    directory_fd: int,
    expected_identity: _PathIdentity | None,
    display_path: str,
) -> _PathIdentity:
    current_identity = directory_identity_from_fd(directory_fd)
    if expected_identity is not None and current_identity != expected_identity:
        raise OSError(f"Included Files directory changed: {display_path}")
    return current_identity


def _included_entry_stat_at(
    parent_fd: int,
    name: str,
) -> os.stat_result | None:
    try:
        return os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None


def _verify_included_entry_at(
    parent_fd: int,
    name: str,
    expected_fingerprint: _PathFingerprint,
    display_path: str,
) -> None:
    current_stat = included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or included_path_fingerprint(current_stat) != expected_fingerprint
    ):
        raise OSError(f"Included Files entry changed: {display_path}")


def _included_path_fingerprint(path_stat: os.stat_result) -> _PathFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_mode,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_nlink,
    )


def _included_path_handle_binding(
    file_stat: os.stat_result,
) -> _PathHandleBinding:
    """Return metadata that is stable across path and handle stat on Windows."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        stat.S_IFMT(file_stat.st_mode),
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_nlink,
    )


def _included_handle_state(file_stat: os.stat_result) -> _HandleState:
    """Return metadata used to detect mutation of one open file handle."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
        file_stat.st_nlink,
    )


def _included_source_fingerprint(
    source_stat: os.stat_result,
) -> _IncludedSourceFingerprint:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        source_stat.st_mode,
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )


def _included_tree_without_content(
    snapshot: _IncludedTreeSnapshot,
) -> _IncludedTreeSnapshot:
    return _IncludedTreeSnapshot(
        root_fingerprint=snapshot.root_fingerprint,
        entries=tuple(
            _IncludedTreeEntry(
                relative_path=entry.relative_path,
                kind=entry.kind,
                fingerprint=entry.fingerprint,
                ctime_ns=entry.ctime_ns,
                content_sha256=None,
            )
            for entry in snapshot.entries
        ),
    )


def _included_tree_matches_planned_paths(
    snapshot: _IncludedTreeSnapshot,
    assigned_paths: set[str],
) -> bool:
    if snapshot.identity is None:
        return False
    expected_directories = {
        "/".join(path.split("/")[:component_count])
        for path in assigned_paths
        for component_count in range(1, len(path.split("/")))
    }
    actual_files = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "directory"
    }
    if actual_files != assigned_paths or actual_directories != expected_directories:
        return False
    return all(
        entry.content_sha256 is not None and entry.fingerprint[5] == 1
        for entry in snapshot.entries
        if entry.kind == "file"
    )


def _included_tree_matches_source_receipts(
    snapshot: _IncludedTreeSnapshot,
    assigned_receipts: dict[str, _IncludedNoOpSourceReceipt],
) -> bool:
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    return all(
        assigned_path in entries_by_path
        and entries_by_path[assigned_path].fingerprint[3]
        == receipt.byte_count
        and entries_by_path[assigned_path].content_sha256 == receipt.sha256
        for assigned_path, receipt in assigned_receipts.items()
    )


def _included_generation_receipts_by_path(
    *,
    transaction_id: str,
    generation_identity: _PathIdentity,
    stage_container_identity: _PathIdentity,
    staged_root_path: str,
    public_root_path: str,
    receipts: tuple[_IncludedGenerationContentReceipt, ...],
) -> dict[str, _IncludedGenerationContentReceipt]:
    if not receipts:
        raise OSError("Included Files generation receipt set is empty")
    receipts_by_path: dict[str, _IncludedGenerationContentReceipt] = {}
    normalized_staged_root = os.path.normcase(os.path.abspath(staged_root_path))
    normalized_public_root = os.path.normcase(os.path.abspath(public_root_path))
    for receipt in receipts:
        assigned_path = receipt.source.assigned_path
        assigned_components = tuple(assigned_path.split("/"))
        if (
            not assigned_path
            or "\\" in assigned_path
            or any(
                component in {"", ".", ".."}
                for component in assigned_components
            )
            or assigned_path in receipts_by_path
        ):
            raise OSError("Invalid Included Files generation receipt path")
        expected_staged_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    normalized_staged_root,
                    *assigned_components,
                )
            )
        )
        expected_public_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    normalized_public_root,
                    *assigned_components,
                )
            )
        )
        output = receipt.output
        output_binding = (
            output.output_handle_state[0],
            output.output_handle_state[1],
            stat.S_IFMT(output.output_handle_state[2]),
            output.output_handle_state[3],
            output.output_handle_state[4],
            output.output_handle_state[6],
        )
        path_binding = (
            output.output_fingerprint[0],
            output.output_fingerprint[1],
            stat.S_IFMT(output.output_fingerprint[2]),
            output.output_fingerprint[3],
            output.output_fingerprint[4],
            output.output_fingerprint[5],
        )
        if (
            receipt.transaction_id != transaction_id
            or receipt.generation_identity != generation_identity
            or receipt.stage_container_identity
            != stage_container_identity
            or receipt.source.logical_path == ""
            or receipt.staged_output_path != expected_staged_path
            or receipt.public_output_path != expected_public_path
            or output.source_fingerprint
            != receipt.source.binding.handle_state[:6]
            or output.byte_count != receipt.source.byte_count
            or output.sha256 != receipt.source.sha256
            or output_binding != path_binding
            or output.output_fingerprint[5] != 1
        ):
            raise OSError(
                "Included Files generation content receipt binding changed"
            )
        receipts_by_path[assigned_path] = receipt
    return receipts_by_path


def _included_registry_receipts_from_tree(
    snapshot: _IncludedTreeSnapshot,
    assignments_by_source: dict[str, IncludedFilePathAssignment],
    emitted_logical_paths: set[str],
) -> dict[str, tuple[int, str]] | None:
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    receipts: dict[str, tuple[int, str]] = {}
    for logical_path in emitted_logical_paths:
        assignment = assignments_by_source.get(logical_path)
        if assignment is None:
            return None
        entry = entries_by_path.get(assignment.assigned_output_path)
        if entry is None or entry.content_sha256 is None:
            return None
        receipts[logical_path] = (
            entry.fingerprint[3],
            entry.content_sha256,
        )
    return receipts


def _verify_staged_included_inventory(
    snapshot: _IncludedTreeSnapshot,
    assigned_receipts: dict[str, _IncludedCopyReceipt],
) -> None:
    if snapshot.identity is None:
        raise OSError("Included Files staging root disappeared before publication")
    assigned_paths = set(assigned_receipts)
    expected_directories = {
        "/".join(path.split("/")[:component_count])
        for path in assigned_paths
        for component_count in range(1, len(path.split("/")))
    }
    actual_files = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    actual_directories = {
        entry.relative_path
        for entry in snapshot.entries
        if entry.kind == "directory"
    }
    if actual_files != assigned_paths or actual_directories != expected_directories:
        raise OSError(
            "Included Files staging inventory did not match its planned output set"
        )
    entries_by_path = {
        entry.relative_path: entry
        for entry in snapshot.entries
        if entry.kind == "file"
    }
    for assigned_path, receipt in assigned_receipts.items():
        staged_entry = entries_by_path[assigned_path]
        if staged_entry.fingerprint[5] != 1:
            raise OSError(
                "Included Files staging payload has multiple hard links: "
                + assigned_path
            )
        if (
            staged_entry.fingerprint[3] != receipt.byte_count
            or staged_entry.content_sha256 != receipt.sha256
        ):
            raise OSError(
                "Included Files staging payload did not match its immutable "
                f"source receipt: {assigned_path}"
            )


def _validated_included_tree_snapshot(
    root_fingerprint: _PathFingerprint | None,
    entries: list[_IncludedTreeEntry],
    label: str,
) -> _IncludedTreeSnapshot:
    if root_fingerprint is None and entries:
        raise OSError(f"Invalid Included Files recovery absent {label}")
    if root_fingerprint is not None and not stat.S_ISDIR(root_fingerprint[2]):
        raise OSError(f"Invalid Included Files recovery {label} root mode")
    if root_fingerprint is not None and root_fingerprint[5] < 1:
        raise OSError(f"Invalid Included Files recovery {label} root link count")
    if any(entry.fingerprint[5] < 1 for entry in entries):
        raise OSError(f"Invalid Included Files recovery {label} link count")
    if root_fingerprint is not None and any(
        entry.fingerprint[0] != root_fingerprint[0] for entry in entries
    ):
        raise OSError(
            f"Invalid cross-device Included Files recovery {label}"
        )
    directory_paths = {
        entry.relative_path for entry in entries if entry.kind == "directory"
    }
    if any(
        (parent := posixpath.dirname(entry.relative_path))
        and parent not in directory_paths
        for entry in entries
    ):
        raise OSError(f"Invalid Included Files recovery {label} topology")
    if entries != sorted(entries, key=lambda entry: entry.relative_path):
        raise OSError(f"Unsorted Included Files recovery {label}")
    return _IncludedTreeSnapshot(
        root_fingerprint=root_fingerprint,
        entries=tuple(entries),
    )


def _verify_included_bounded_record_size(
    record_stat: os.stat_result,
    path: str,
    maximum_bytes: int,
    record_label: str,
    size_qualifier: str,
) -> None:
    if record_stat.st_size < 0 or record_stat.st_size > maximum_bytes:
        raise OSError(
            f"{record_label} exceeds the {size_qualifier} size limit of "
            f"{maximum_bytes} bytes: {path}"
        )


def _included_cleanup_mode_matches(
    current: int,
    expected: int,
    *,
    allow_windows_writable: bool,
) -> bool:
    if current == expected:
        return True
    if not allow_windows_writable or os.name != "nt":
        return False
    write_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    return (
        not bool(expected & stat.S_IWRITE)
        and bool(current & stat.S_IWRITE)
        and current & ~write_mask == expected & ~write_mask
    )


def _included_cleanup_tombstone_fingerprint_matches(
    current: _PathFingerprint,
    expected: _PathFingerprint,
) -> bool:
    if current == expected:
        return True
    return (
        current[:2] == expected[:2]
        and current[3:] == expected[3:]
        and included_cleanup_mode_matches(
            current[2],
            expected[2],
            allow_windows_writable=True,
        )
    )


def _included_cleanup_file_receipt_matches(
    state: _IncludedCleanupFileState,
    expected_content_sha256: str,
    expected_fingerprint: _PathFingerprint | None,
    expected_mode: int | None,
    *,
    allow_windows_writable: bool,
) -> bool:
    return (
        state[1] == expected_content_sha256
        and (
            expected_fingerprint is None
            or (
                included_cleanup_tombstone_fingerprint_matches(
                    state[2],
                    expected_fingerprint,
                )
                if allow_windows_writable
                else state[2] == expected_fingerprint
            )
        )
        and (
            expected_mode is None
            or included_cleanup_mode_matches(
                state[0],
                expected_mode,
                allow_windows_writable=allow_windows_writable,
            )
        )
    )


def _included_output_state_at(
    directory_fd: int,
    filename: str,
) -> tuple[int, int] | None:
    try:
        output_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing non-regular Included File output: {filename}"
        )
    return (output_stat.st_dev, output_stat.st_ino)


def _verify_included_output_state_at(
    directory_fd: int,
    filename: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity = included_output_state_at(directory_fd, filename)
    if current_identity != expected_identity:
        raise OSError(
            f"Included File output changed during publication: {filename}"
        )


def _included_output_state(
    output_path: str,
) -> tuple[int, int] | None:
    try:
        output_stat = os.lstat(output_path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(output_stat.st_mode):
        raise OSError(
            f"Refusing non-regular Included File output: {output_path}"
        )
    return (output_stat.st_dev, output_stat.st_ino)


def _verify_included_output_state(
    output_path: str,
    expected_identity: tuple[int, int] | None,
) -> None:
    current_identity = included_output_state(output_path)
    if current_identity != expected_identity:
        raise OSError(
            f"Included File output changed during publication: {output_path}"
        )


def _included_output_path_is_redirected(
    path: str,
    path_stat: os.stat_result,
) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


# Finite compatibility exports; each operation has one actual owner.
directory_identity_from_fd = _directory_identity_from_fd
verify_included_directory_fd = _verify_included_directory_fd
included_entry_stat_at = _included_entry_stat_at
verify_included_entry_at = _verify_included_entry_at
included_path_fingerprint = _included_path_fingerprint
included_path_handle_binding = _included_path_handle_binding
included_handle_state = _included_handle_state
included_source_fingerprint = _included_source_fingerprint
included_tree_without_content = _included_tree_without_content
included_tree_matches_planned_paths = _included_tree_matches_planned_paths
included_tree_matches_source_receipts = _included_tree_matches_source_receipts
included_generation_receipts_by_path = _included_generation_receipts_by_path
included_registry_receipts_from_tree = _included_registry_receipts_from_tree
verify_staged_included_inventory = _verify_staged_included_inventory
validated_included_tree_snapshot = _validated_included_tree_snapshot
verify_included_bounded_record_size = _verify_included_bounded_record_size
included_cleanup_mode_matches = _included_cleanup_mode_matches
included_cleanup_tombstone_fingerprint_matches = _included_cleanup_tombstone_fingerprint_matches
included_cleanup_file_receipt_matches = _included_cleanup_file_receipt_matches
included_output_state_at = _included_output_state_at
verify_included_output_state_at = _verify_included_output_state_at
included_output_state = _included_output_state
verify_included_output_state = _verify_included_output_state

included_output_path_is_redirected = _included_output_path_is_redirected
