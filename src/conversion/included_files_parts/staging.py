"""Included Files staging ownership."""

from __future__ import annotations
import hashlib
import os
import secrets
import stat
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, IncludedTreeEntry as _IncludedTreeEntry, IncludedTreeSnapshot as _IncludedTreeSnapshot, IncludedRegistrySnapshot as _IncludedRegistrySnapshot
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import native_posix as _included_posix
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import record_io as _included_records

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
        verify_included_stage_container(
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
            write_included_stage_marker(
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
        write_included_stage_marker(
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
            before_included_registry_directory_binding_check(
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


included_stage_container_snapshot = _included_stage_container_snapshot
before_included_registry_directory_binding_check = _before_included_registry_directory_binding_check
verify_included_stage_container = _verify_included_stage_container
write_included_stage_marker = _write_included_stage_marker
create_included_output_stage = _create_included_output_stage
sync_included_tree_directories_bottom_up = _sync_included_tree_directories_bottom_up
prepare_included_registry_directory = _prepare_included_registry_directory
