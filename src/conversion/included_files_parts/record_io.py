from __future__ import annotations
import json
import os
import stat
from typing import Any, BinaryIO, Callable
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts import source_snapshots as _included_snapshots


def _read_included_recovery_record_payload(opened_file: BinaryIO) -> bytes:
    """Narrow test seam for a stat-bounded canonical recovery-record read."""

    return opened_file.read(_included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES + 1)

def _read_included_lock_initialization_payload(
    opened_file: BinaryIO,
) -> bytes:
    """Read only enough bytes to distinguish the fixed lock payload."""

    return opened_file.read(len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) + 1)

def _read_opened_included_bounded_record_payload(
    opened_file: BinaryIO,
    expected_stat: os.stat_result,
    path: str,
    expected_device: int,
    expected_mount_id: int | None,
    maximum_bytes: int,
    payload_reader: Callable[[BinaryIO], bytes],
    record_label: str,
    size_qualifier: str,
) -> bytes:
    opened_stat = os.fstat(opened_file.fileno())
    if (
        not stat.S_ISREG(opened_stat.st_mode)
        or _included_metadata.included_path_handle_binding(opened_stat)
        != _included_metadata.included_path_handle_binding(expected_stat)
    ):
        raise OSError(
            f"{record_label} changed before reading: {path}"
        )
    _included_metadata.verify_included_bounded_record_size(
        opened_stat,
        path,
        maximum_bytes,
        record_label,
        size_qualifier,
    )
    _included_fs.verify_mount_boundary(
        path,
        opened_stat,
        expected_device,
        expected_mount_id,
        opened_file.fileno(),
    )
    opened_state = _included_metadata.included_handle_state(opened_stat)
    content = payload_reader(opened_file)
    current_opened_stat = os.fstat(opened_file.fileno())
    if len(content) > maximum_bytes:
        raise OSError(
            f"{record_label} exceeds the {size_qualifier} size limit of "
            f"{maximum_bytes} bytes: {path}"
        )
    if (
        len(content) != opened_stat.st_size
        or _included_metadata.included_handle_state(current_opened_stat) != opened_state
    ):
        raise OSError(
            f"{record_label} changed while reading: {path}"
        )
    return content

def _included_bounded_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    maximum_bytes: int,
    payload_reader: Callable[[BinaryIO], bytes],
    record_label: str,
    size_qualifier: str,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    if _included_fs.descriptor_paths_supported():
        try:
            parent_fd, name = _included_fs.open_pinned_parent(path)
        except FileNotFoundError:
            return None
        try:
            parent_identity = _included_metadata.verify_included_directory_fd(
                parent_fd,
                project_identity,
                os.path.dirname(path),
            )
            parent_mount_id = _included_fs.linux_mount_id_from_fd(parent_fd)
            path_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
            if path_stat is None:
                return None
            if not stat.S_ISREG(path_stat.st_mode):
                raise OSError(
                    f"Refusing redirected or non-regular {record_label}: {path}"
                )
            path_identity = path_stat.st_dev, path_stat.st_ino
            if (
                allowed_identities is not None
                and path_identity not in allowed_identities
            ):
                raise OSError(
                    f"{record_label} changed before reading: {path}"
                )
            _included_metadata.verify_included_bounded_record_size(
                path_stat,
                path,
                maximum_bytes,
                record_label,
                size_qualifier,
            )
            expected_fingerprint = _included_metadata.included_path_fingerprint(path_stat)
            expected_ctime_ns = path_stat.st_ctime_ns
            file_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                with os.fdopen(file_descriptor, "rb") as opened_file:
                    file_descriptor = -1
                    content = read_opened_included_bounded_record_payload(
                        opened_file,
                        path_stat,
                        path,
                        parent_identity[0],
                        parent_mount_id,
                        maximum_bytes,
                        payload_reader,
                        record_label,
                        size_qualifier,
                    )
            finally:
                if file_descriptor >= 0:
                    os.close(file_descriptor)
            current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
            if (
                current_stat is None
                or not stat.S_ISREG(current_stat.st_mode)
                or _included_metadata.included_path_fingerprint(current_stat)
                != expected_fingerprint
                or current_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(
                    f"{record_label} changed while reading: {path}"
                )
            return (
                (current_stat.st_dev, current_stat.st_ino),
                stat.S_IMODE(current_stat.st_mode),
                content,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _included_snapshots.capture_fallback_directory_ancestors(parent_path)
    if parent_identities[-1][1] != project_identity:
        raise OSError(f"{record_label} parent changed: {path}")
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_fs.output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected or non-regular {record_label}: {path}"
        )
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(
            f"{record_label} changed before reading: {path}"
        )
    _included_metadata.verify_included_bounded_record_size(
        path_stat,
        path,
        maximum_bytes,
        record_label,
        size_qualifier,
    )
    expected_fingerprint = _included_metadata.included_path_fingerprint(path_stat)
    expected_ctime_ns = path_stat.st_ctime_ns
    parent_mount_id = _included_fs.directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
    _included_snapshots.before_included_fallback_regular_file_open(path)
    file_descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = read_opened_included_bounded_record_payload(
                opened_file,
                path_stat,
                path,
                project_identity[0],
                parent_mount_id,
                maximum_bytes,
                payload_reader,
                record_label,
                size_qualifier,
            )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    current_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_metadata.included_path_fingerprint(current_stat) != expected_fingerprint
        or current_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(
            f"{record_label} changed while reading: {path}"
        )
    _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )

def _included_recovery_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    return included_bounded_record_state(
        path,
        project_identity,
        maximum_bytes=_included_constants.INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        payload_reader=read_included_recovery_record_payload,
        record_label="Included Files recovery record",
        size_qualifier="canonical",
        allowed_identities=allowed_identities,
    )

def _included_lock_initialization_record_state(
    path: str,
    project_identity: _PathIdentity,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    return included_bounded_record_state(
        path,
        project_identity,
        maximum_bytes=len(_included_constants.INCLUDED_FILES_LOCK_CONTENT),
        payload_reader=read_included_lock_initialization_payload,
        record_label="Included Files lock initialization record",
        size_qualifier="fixed-content",
        allowed_identities=allowed_identities,
    )

def _read_included_recovery_record(
    path: str,
    project_identity: _PathIdentity,
) -> tuple[_PathIdentity, dict[str, Any]] | None:
    state = included_recovery_record_state(path, project_identity)
    if state is None:
        return None
    identity, _mode, content = state
    try:
        decoded = content.decode("utf-8")
        payload = _included_codec.included_recovery_dict(
            json.loads(decoded),
            "record",
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OSError(f"Invalid Included Files recovery record: {path}") from error
    if content != _included_codec.included_recovery_record_content(payload):
        raise OSError(f"Non-canonical Included Files recovery record: {path}")
    return identity, payload

def _read_included_recovery_record_or_tombstone(
    path: str,
    project_identity: _PathIdentity,
) -> tuple[str, _PathIdentity, dict[str, Any]] | None:
    record = read_included_recovery_record(path, project_identity)
    tombstone_path = _included_paths.included_recovery_record_tombstone_path(path)
    tombstone_record = read_included_recovery_record(
        tombstone_path,
        project_identity,
    )
    if record is not None and tombstone_record is not None:
        raise OSError(
            "Included Files recovery record and cleanup tombstone both exist: "
            + path
        )
    if record is not None:
        return path, record[0], record[1]
    if tombstone_record is not None:
        return tombstone_path, tombstone_record[0], tombstone_record[1]
    return None


read_included_recovery_record_payload = _read_included_recovery_record_payload
read_included_lock_initialization_payload = _read_included_lock_initialization_payload
read_opened_included_bounded_record_payload = _read_opened_included_bounded_record_payload
included_bounded_record_state = _included_bounded_record_state
included_recovery_record_state = _included_recovery_record_state
included_lock_initialization_record_state = _included_lock_initialization_record_state
read_included_recovery_record = _read_included_recovery_record
read_included_recovery_record_or_tombstone = _read_included_recovery_record_or_tombstone
