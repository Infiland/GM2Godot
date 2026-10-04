"""Included Files locking ownership."""

from __future__ import annotations

import os
import secrets
import stat

from src.conversion.included_files_parts import (
    constants as _included_constants,
    guarded_mutations as _included_mutations,
    path_validation as _included_paths,
    record_io as _included_records,
    recorded_cleanup as _included_cleanup,
    source_snapshots as _included_snapshots,
    stat_metadata as _included_metadata,
)
from src.conversion.included_files_parts.models import (
    IncludedProjectLock as _IncludedProjectLock,
    PathIdentity as _PathIdentity,
)
from src.conversion.included_files_parts.native_filesystem import (
    filesystem as _included_fs,
)


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
            after_included_lock_initialization_phase("temporary-partially-written")
    after_included_lock_initialization_phase("temporary-written")
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
        after_included_lock_initialization_phase("temporary-cleanup-quarantined")

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
    after_included_lock_initialization_phase("temporary-cleanup-removed")


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
            remove_exact_included_lock_initialization_temporary(
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
            after_included_lock_initialization_phase("temporary-created")
            write_included_lock_initialization_temporary(file_descriptor)
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
            after_included_lock_initialization_phase("temporary-synced")
            _included_mutations.move_exact_included_file(
                temporary_path,
                lock_path,
                temporary_identity,
                source_parent_identity=project_identity,
                destination_parent_identity=project_identity,
            )
            temporary_pending = False
            _included_fs.sync_directory(project_path, project_identity)
            after_included_lock_initialization_phase("temporary-published")
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
                remove_exact_included_lock_initialization_temporary(
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
            initialize_included_project_lock(
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
        cleanup_included_lock_initialization_temporaries(
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


after_included_lock_initialization_phase = _after_included_lock_initialization_phase
write_included_lock_initialization_temporary = _write_included_lock_initialization_temporary
remove_exact_included_lock_initialization_temporary = _remove_exact_included_lock_initialization_temporary
cleanup_included_lock_initialization_temporaries = _cleanup_included_lock_initialization_temporaries
initialize_included_project_lock = _initialize_included_project_lock
acquire_included_project_lock = _acquire_included_project_lock
release_included_project_lock = _release_included_project_lock
