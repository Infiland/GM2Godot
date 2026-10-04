from __future__ import annotations
import os
import posixpath
import stat
import sys
from contextlib import ExitStack
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, PathFingerprint as _PathFingerprint, IncludedCleanupFileState as _IncludedCleanupFileState, IncludedTreeEntry as _IncludedTreeEntry, IncludedTreeSnapshot as _IncludedTreeSnapshot
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts.filesystem_operations import IncludedCleanupParentBinding as _IncludedCleanupParentBinding
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import phase_observer as _included_phases


def _included_cleanup_file_state(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
    *,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> _IncludedCleanupFileState | None:
    if _included_fs.descriptor_paths_supported():
        parent_fd, name = _included_fs.open_pinned_parent(path)
        try:
            _included_metadata.verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
            if current_stat is None:
                return None
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or (current_stat.st_dev, current_stat.st_ino)
                != expected_identity
            ):
                raise OSError(f"Included Files cleanup file changed: {path}")
            expected_fingerprint = _included_metadata.included_path_fingerprint(current_stat)
            expected_ctime_ns = current_stat.st_ctime_ns
            parent_mount_id = _included_fs.linux_mount_id_from_fd(parent_fd)
            content_sha256 = _included_snapshots.digest_included_regular_file_at(
                parent_fd,
                name,
                current_stat,
                path,
                expected_device=expected_parent_identity[0],
                expected_mount_id=parent_mount_id,
            )
            final_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
            if (
                final_stat is None
                or not stat.S_ISREG(final_stat.st_mode)
                or (final_stat.st_dev, final_stat.st_ino) != expected_identity
                or _included_metadata.included_path_fingerprint(final_stat)
                != expected_fingerprint
                or final_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(f"Included Files cleanup file changed: {path}")
            return (
                stat.S_IMODE(final_stat.st_mode),
                content_sha256,
                expected_fingerprint,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities: tuple[tuple[str, _PathIdentity], ...] | None
    if windows_parent_binding is None:
        parent_identities = _included_snapshots.capture_fallback_directory_ancestors(parent_path)
        if parent_identities[-1][1] != expected_parent_identity:
            raise OSError(f"Included Files cleanup parent changed: {path}")
    else:
        parent_identities = None
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )

    def verify_parent() -> None:
        if windows_parent_binding is None:
            if parent_identities is None:
                raise AssertionError("Missing Included Files cleanup parent state")
            _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
        else:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
    try:
        current_stat = os.lstat(path)
    except FileNotFoundError:
        verify_parent()
        return None
    if (
        _included_fs.output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files cleanup file changed: {path}")
    expected_fingerprint = _included_metadata.included_path_fingerprint(current_stat)
    expected_ctime_ns = current_stat.st_ctime_ns
    parent_mount_id = _included_fs.directory_mount_id(
        parent_path,
        expected_parent_identity,
    )
    verify_parent()
    content_sha256 = _included_snapshots.digest_included_regular_file(
        path,
        current_stat,
        expected_device=expected_parent_identity[0],
        expected_mount_id=parent_mount_id,
    )
    verify_parent()
    final_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, final_stat)
        or not stat.S_ISREG(final_stat.st_mode)
        or (final_stat.st_dev, final_stat.st_ino) != expected_identity
        or _included_metadata.included_path_fingerprint(final_stat) != expected_fingerprint
        or final_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(f"Included Files cleanup file changed: {path}")
    verify_parent()
    return (
        stat.S_IMODE(final_stat.st_mode),
        content_sha256,
        expected_fingerprint,
    )

def _included_cleanup_directory_state(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
    *,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> bool | None:
    parent_path = os.path.dirname(os.path.abspath(path))
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
            return None
        if (
            _included_fs.output_path_is_redirected(path, path_stat)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Included Files cleanup directory changed: {path}")
        parent_mount_id = _included_fs.directory_mount_id(
            parent_path,
            expected_parent_identity,
        )
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
        _included_fs.verify_mount_boundary_path(
            path,
            path_stat,
            expected_parent_identity[0],
            parent_mount_id,
            expect_directory=True,
        )
        final_stat = os.lstat(path)
        if (
            _included_fs.output_path_is_redirected(path, final_stat)
            or not stat.S_ISDIR(final_stat.st_mode)
            or (final_stat.st_dev, final_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Included Files cleanup directory changed: {path}")
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
        return True

    current_parent_identity = _included_snapshots.included_directory_identity(parent_path)
    if current_parent_identity != expected_parent_identity:
        raise OSError(f"Included Files cleanup parent changed: {parent_path}")
    current_identity = _included_snapshots.included_directory_identity(path)
    if current_identity is None:
        return None
    if current_identity != expected_identity:
        raise OSError(f"Included Files cleanup directory changed: {path}")
    path_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
    ):
        raise OSError(f"Included Files cleanup directory changed: {path}")
    parent_mount_id = _included_fs.directory_mount_id(
        parent_path,
        expected_parent_identity,
    )
    _included_fs.verify_mount_boundary_path(
        path,
        path_stat,
        expected_parent_identity[0],
        parent_mount_id,
        expect_directory=True,
    )
    if (
        _included_snapshots.included_directory_identity(path) != expected_identity
        or _included_snapshots.included_directory_identity(parent_path) != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup directory changed: {path}")
    return True

def _remove_included_cleanup_tombstone(
    path: str,
    expected_identity: _PathIdentity,
    parent_path: str,
    parent_identity: _PathIdentity,
    *,
    expect_directory: bool,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> None:
    # The fallback removers must observe the original Windows READONLY state
    # themselves so they can restore that attribute after a sharing failure.
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            parent_identity,
        )
    if _included_fs.descriptor_paths_supported():
        parent_fd, name = _included_fs.open_pinned_parent(path)
        try:
            _included_metadata.verify_included_directory_fd(
                parent_fd,
                parent_identity,
                parent_path,
            )
            if expect_directory:
                _included_mutations.rmdir_exact_quarantined_entry_at(
                    parent_fd,
                    name,
                    expected_identity,
                    path,
                )
            else:
                _included_mutations.unlink_exact_quarantined_entry_at(
                    parent_fd,
                    name,
                    expected_identity,
                    path,
                )
        finally:
            os.close(parent_fd)
    elif expect_directory:
        _included_mutations.rmdir_exact_quarantined_entry_fallback(
            path,
            expected_identity,
            expected_parent_identity=parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    else:
        _included_mutations.unlink_exact_quarantined_entry_fallback(
            path,
            expected_identity,
            expected_parent_identity=parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    _included_fs.sync_directory(parent_path, parent_identity)

def _cleanup_recorded_included_file(
    path: str,
    expected_identity: _PathIdentity,
    expected_content_sha256: str,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
    relative_path: str,
    *,
    expected_fingerprint: _PathFingerprint | None = None,
    expected_mode: int | None = None,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    parent_path = os.path.dirname(os.path.abspath(path))
    tombstone_path = _included_paths.included_cleanup_tombstone_path(
        path,
        transaction_id,
        role,
        relative_path,
        expect_directory=False,
    )
    try:
        source_state = included_cleanup_file_state(
            path,
            expected_identity,
            expected_parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    except OSError:
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        source_state = None
        if os.path.lexists(path):
            warnings.append(
                f"unknown Included Files cleanup entry was preserved: {path}"
            )
    try:
        tombstone_state = included_cleanup_file_state(
            tombstone_path,
            expected_identity,
            expected_parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    except OSError:
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        tombstone_state = None
        if os.path.lexists(tombstone_path):
            warnings.append(
                "unknown Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)

    if source_state is not None and tombstone_state is not None:
        warnings.append(
            f"ambiguous duplicate Included Files cleanup entry was preserved: {path}"
        )
        return tuple(warnings)
    if tombstone_state is not None:
        if not _included_metadata.included_cleanup_file_receipt_matches(
            tombstone_state,
            expected_content_sha256,
            expected_fingerprint,
            expected_mode,
            allow_windows_writable=True,
        ):
            warnings.append(
                "changed Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        remove_included_cleanup_tombstone(
            tombstone_path,
            expected_identity,
            parent_path,
            expected_parent_identity,
            expect_directory=False,
            windows_parent_binding=windows_parent_binding,
        )
        _included_phases.after_included_transaction_phase(
            f"cleanup:{role}:{relative_path}:removed"
        )
        return tuple(warnings)
    if source_state is None:
        return tuple(warnings)
    if not _included_metadata.included_cleanup_file_receipt_matches(
        source_state,
        expected_content_sha256,
        expected_fingerprint,
        expected_mode,
        allow_windows_writable=False,
    ):
        warnings.append(f"changed Included Files cleanup entry was preserved: {path}")
        return tuple(warnings)

    _included_mutations.move_exact_included_file(
        path,
        tombstone_path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
        windows_source_parent_binding=windows_parent_binding,
        windows_destination_parent_binding=windows_parent_binding,
    )
    _included_fs.sync_directory(parent_path, expected_parent_identity)
    _included_phases.after_included_transaction_phase(
        f"cleanup:{role}:{relative_path}:quarantined"
    )
    tombstone_state = included_cleanup_file_state(
        tombstone_path,
        expected_identity,
        expected_parent_identity,
        windows_parent_binding=windows_parent_binding,
    )
    if tombstone_state is None or not _included_metadata.included_cleanup_file_receipt_matches(
        tombstone_state,
        expected_content_sha256,
        expected_fingerprint,
        expected_mode,
        allow_windows_writable=True,
    ):
        raise OSError(
            "Included Files cleanup tombstone changed after publication: "
            + tombstone_path
        )
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        expected_parent_identity,
        expect_directory=False,
        windows_parent_binding=windows_parent_binding,
    )
    _included_phases.after_included_transaction_phase(f"cleanup:{role}:{relative_path}:removed")
    return tuple(warnings)

def _cleanup_recorded_included_directory(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
    relative_path: str,
    *,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    parent_path = os.path.dirname(os.path.abspath(path))
    tombstone_path = _included_paths.included_cleanup_tombstone_path(
        path,
        transaction_id,
        role,
        relative_path,
        expect_directory=True,
    )
    try:
        source_state = included_cleanup_directory_state(
            path,
            expected_identity,
            expected_parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    except OSError:
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        source_state = None
        if os.path.lexists(path):
            warnings.append(
                f"unknown Included Files cleanup directory was preserved: {path}"
            )
    try:
        tombstone_state = included_cleanup_directory_state(
            tombstone_path,
            expected_identity,
            expected_parent_identity,
            windows_parent_binding=windows_parent_binding,
        )
    except OSError:
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        tombstone_state = None
        if os.path.lexists(tombstone_path):
            warnings.append(
                "unknown Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)

    if source_state is not None and tombstone_state is not None:
        warnings.append(
            f"ambiguous duplicate Included Files cleanup directory was preserved: {path}"
        )
        return tuple(warnings)
    if tombstone_state is not None:
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        if os.listdir(tombstone_path):
            warnings.append(
                "non-empty Included Files cleanup tombstone was preserved: "
                + tombstone_path
            )
            return tuple(warnings)
        if windows_parent_binding is not None:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )
        remove_included_cleanup_tombstone(
            tombstone_path,
            expected_identity,
            parent_path,
            expected_parent_identity,
            expect_directory=True,
            windows_parent_binding=windows_parent_binding,
        )
        _included_phases.after_included_transaction_phase(
            f"cleanup:{role}:{relative_path}:removed"
        )
        return tuple(warnings)
    if source_state is None:
        return tuple(warnings)
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    if os.listdir(path):
        warnings.append(
            f"non-empty Included Files cleanup directory was preserved: {path}"
        )
        return tuple(warnings)
    if windows_parent_binding is None:
        if (
            _included_snapshots.included_directory_identity(path) != expected_identity
            or _included_snapshots.included_directory_identity(parent_path)
            != expected_parent_identity
        ):
            raise OSError(f"Included Files cleanup directory changed: {path}")
    else:
        current_stat = os.lstat(path)
        if (
            _included_fs.output_path_is_redirected(path, current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
            or (current_stat.st_dev, current_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Included Files cleanup directory changed: {path}")
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    _included_mutations.move_exact_included_directory(
        path,
        tombstone_path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
        windows_source_parent_binding=windows_parent_binding,
        windows_destination_parent_binding=windows_parent_binding,
    )
    _included_fs.sync_directory(parent_path, expected_parent_identity)
    _included_phases.after_included_transaction_phase(
        f"cleanup:{role}:{relative_path}:quarantined"
    )
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    if os.listdir(tombstone_path):
        warnings.append(
            "non-empty Included Files cleanup tombstone was preserved: "
            + tombstone_path
        )
        return tuple(warnings)
    if windows_parent_binding is not None:
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    remove_included_cleanup_tombstone(
        tombstone_path,
        expected_identity,
        parent_path,
        expected_parent_identity,
        expect_directory=True,
        windows_parent_binding=windows_parent_binding,
    )
    _included_phases.after_included_transaction_phase(f"cleanup:{role}:{relative_path}:removed")
    return tuple(warnings)

def _cleanup_recorded_included_tree(
    path: str,
    snapshot: _IncludedTreeSnapshot,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    role: str,
) -> tuple[str, ...]:
    recorded_entry_paths = {
        entry.relative_path: _included_paths.included_recovery_tree_entry_path(
            path,
            entry.relative_path,
        )
        for entry in snapshot.entries
    }
    if len(recorded_entry_paths) != len(snapshot.entries):
        raise OSError("Duplicate Included Files cleanup manifest path")
    root_identity = snapshot.identity
    if root_identity is None:
        if os.path.lexists(path):
            return (f"unknown Included Files cleanup tree was preserved: {path}",)
        return ()
    if (
        root_identity[0] != expected_parent_identity[0]
        or any(
            entry.fingerprint[0] != root_identity[0]
            for entry in snapshot.entries
        )
    ):
        return (
            f"cross-mount Included Files cleanup tree was preserved: {path}",
        )
    directory_identities: dict[str, _PathIdentity] = {"": root_identity}
    for entry in snapshot.entries:
        if entry.kind == "directory":
            directory_identities[entry.relative_path] = entry.fingerprint[:2]

    try:
        root_state = included_cleanup_directory_state(
            path,
            root_identity,
            expected_parent_identity,
        )
    except OSError:
        return (f"unknown or mounted Included Files cleanup tree was preserved: {path}",)
    if root_state is None:
        return cleanup_recorded_included_directory(
            path,
            root_identity,
            expected_parent_identity,
            transaction_id,
            role,
            ".",
        )

    warnings: list[str] = []
    windows_bindings_enabled = (
        os.name == "nt"
        and sys.platform == "win32"
        and not _included_fs.descriptor_paths_supported()
    )
    if not windows_bindings_enabled or not snapshot.entries:
        absent_directories: set[str] = set()
        for entry in sorted(
            (
                candidate
                for candidate in snapshot.entries
                if candidate.kind == "directory"
            ),
            key=lambda candidate: (
                candidate.relative_path.count("/"),
                candidate.relative_path,
            ),
        ):
            entry_path = recorded_entry_paths[entry.relative_path]
            parent_relative = posixpath.dirname(entry.relative_path)
            if parent_relative in absent_directories:
                absent_directories.add(entry.relative_path)
                continue
            try:
                entry_state = included_cleanup_directory_state(
                    entry_path,
                    entry.fingerprint[:2],
                    directory_identities[parent_relative],
                )
            except OSError:
                return (
                    "unknown or mounted Included Files cleanup directory was "
                    f"preserved: {entry_path}",
                )
            if entry_state is None:
                absent_directories.add(entry.relative_path)

        for entry in sorted(
            (
                candidate
                for candidate in snapshot.entries
                if candidate.kind == "file"
            ),
            key=lambda candidate: candidate.relative_path,
            reverse=True,
        ):
            parent_relative = posixpath.dirname(entry.relative_path)
            if parent_relative in absent_directories:
                # Bottom-up directory cleanup rechecks and preserves anything that
                # reappears; probing every known-absent descendant is redundant.
                continue
            if entry.content_sha256 is None:
                warnings.append(
                    "Included Files cleanup manifest omitted a file digest: "
                    + entry.relative_path
                )
                continue
            warnings.extend(
                cleanup_recorded_included_file(
                    recorded_entry_paths[entry.relative_path],
                    entry.fingerprint[:2],
                    entry.content_sha256,
                    directory_identities[parent_relative],
                    transaction_id,
                    role,
                    entry.relative_path,
                    expected_fingerprint=entry.fingerprint,
                )
            )

        for entry in sorted(
            (
                candidate
                for candidate in snapshot.entries
                if candidate.kind == "directory"
            ),
            key=lambda candidate: (
                candidate.relative_path.count("/"),
                candidate.relative_path,
            ),
            reverse=True,
        ):
            parent_relative = posixpath.dirname(entry.relative_path)
            warnings.extend(
                cleanup_recorded_included_directory(
                    recorded_entry_paths[entry.relative_path],
                    entry.fingerprint[:2],
                    directory_identities[parent_relative],
                    transaction_id,
                    role,
                    entry.relative_path,
                )
            )
    else:
        directory_entries_by_parent: dict[
            str,
            list[_IncludedTreeEntry],
        ] = {}
        file_entries_by_parent: dict[str, list[_IncludedTreeEntry]] = {}
        for entry in snapshot.entries:
            parent_relative = posixpath.dirname(entry.relative_path)
            entries_by_parent = (
                directory_entries_by_parent
                if entry.kind == "directory"
                else file_entries_by_parent
            )
            entries_by_parent.setdefault(parent_relative, []).append(entry)

        def parent_path_for(relative_path: str) -> str:
            return (
                path
                if not relative_path
                else recorded_entry_paths[relative_path]
            )

        def verify_parent_binding(
            binding: _IncludedCleanupParentBinding,
            relative_path: str,
        ) -> None:
            _included_fs.verify_windows_cleanup_parent(
                binding,
                parent_path_for(relative_path),
                directory_identities[relative_path],
            )

        with ExitStack() as root_binding_scope:
            root_parent_binding = _included_fs.open_windows_cleanup_parent(
                path,
                root_identity,
            )
            # ``open`` already verifies and closes on failure. Register its
            # exception-aware ``__exit__`` without a second racy ``__enter__``.
            root_binding_scope.push(root_parent_binding)

            def open_child_binding(
                binding_scope: ExitStack,
                active_bindings: dict[
                    str,
                    _IncludedCleanupParentBinding,
                ],
                relative_path: str,
            ) -> _IncludedCleanupParentBinding:
                parent_relative = posixpath.dirname(relative_path)
                parent_binding = active_bindings.get(parent_relative)
                if parent_binding is None:
                    raise OSError(
                        "Missing Included Files cleanup ancestor binding: "
                        + parent_relative
                    )
                verify_parent_binding(parent_binding, parent_relative)
                binding = _included_fs.open_windows_cleanup_parent(
                    parent_path_for(relative_path),
                    directory_identities[relative_path],
                )
                # Register before the post-open parent check so both handles
                # unwind if a parent changes during child acquisition.
                binding_scope.push(binding)
                verify_parent_binding(parent_binding, parent_relative)
                active_bindings[relative_path] = binding
                return binding

            absent_directories = set()
            with ExitStack() as preflight_binding_scope:
                active_preflight_bindings = {"": root_parent_binding}
                preflight_actions: list[tuple[str, str]] = [("enter", "")]
                while preflight_actions:
                    action, parent_relative = preflight_actions.pop()
                    if action == "leave":
                        binding = active_preflight_bindings.pop(
                            parent_relative
                        )
                        binding.close()
                        continue
                    if action != "enter":
                        raise AssertionError(
                            "Unknown Included Files cleanup preflight action"
                        )
                    parent_binding = active_preflight_bindings.get(
                        parent_relative
                    )
                    if parent_binding is None:
                        parent_binding = open_child_binding(
                            preflight_binding_scope,
                            active_preflight_bindings,
                            parent_relative,
                        )
                    present_child_parents: list[str] = []
                    for entry in sorted(
                        directory_entries_by_parent.get(parent_relative, ()),
                        key=lambda candidate: candidate.relative_path,
                    ):
                        entry_path = recorded_entry_paths[entry.relative_path]
                        try:
                            entry_state = included_cleanup_directory_state(
                                entry_path,
                                entry.fingerprint[:2],
                                directory_identities[parent_relative],
                                windows_parent_binding=parent_binding,
                            )
                        except OSError:
                            verify_parent_binding(
                                parent_binding,
                                parent_relative,
                            )
                            return (
                                "unknown or mounted Included Files cleanup "
                                f"directory was preserved: {entry_path}",
                            )
                        if entry_state is None:
                            absent_directories.add(entry.relative_path)
                        elif entry.relative_path in directory_entries_by_parent:
                            present_child_parents.append(entry.relative_path)
                    if parent_relative:
                        preflight_actions.append(("leave", parent_relative))
                    preflight_actions.extend(
                        ("enter", child_relative)
                        for child_relative in reversed(present_child_parents)
                    )

            for entry in sorted(
                (
                    candidate
                    for candidate in snapshot.entries
                    if candidate.kind == "directory"
                ),
                key=lambda candidate: (
                    candidate.relative_path.count("/"),
                    candidate.relative_path,
                ),
            ):
                if (
                    posixpath.dirname(entry.relative_path)
                    in absent_directories
                ):
                    absent_directories.add(entry.relative_path)

            with ExitStack() as cleanup_binding_scope:
                active_cleanup_bindings = {"": root_parent_binding}
                cleanup_actions: list[
                    tuple[str, str, _IncludedTreeEntry | None]
                ] = [("enter", "", None)]
                while cleanup_actions:
                    action, relative_path, own_entry = cleanup_actions.pop()
                    if action == "remove":
                        if own_entry is None:
                            raise AssertionError(
                                "Missing Included Files cleanup directory entry"
                            )
                        parent_relative = posixpath.dirname(relative_path)
                        parent_binding = active_cleanup_bindings.get(
                            parent_relative
                        )
                        if parent_binding is None:
                            raise OSError(
                                "Missing Included Files cleanup parent binding: "
                                + parent_relative
                            )
                        warnings.extend(
                            cleanup_recorded_included_directory(
                                recorded_entry_paths[relative_path],
                                own_entry.fingerprint[:2],
                                directory_identities[parent_relative],
                                transaction_id,
                                role,
                                relative_path,
                                windows_parent_binding=parent_binding,
                            )
                        )
                        continue
                    if action == "leave":
                        if own_entry is None:
                            continue
                        binding = active_cleanup_bindings.pop(relative_path)
                        # Closing the child first permits its own removal while
                        # the complete parent chain remains retained.
                        binding.close()
                        parent_relative = posixpath.dirname(relative_path)
                        parent_binding = active_cleanup_bindings.get(
                            parent_relative
                        )
                        if parent_binding is None:
                            raise OSError(
                                "Missing Included Files cleanup parent binding: "
                                + parent_relative
                            )
                        warnings.extend(
                            cleanup_recorded_included_directory(
                                recorded_entry_paths[relative_path],
                                own_entry.fingerprint[:2],
                                directory_identities[parent_relative],
                                transaction_id,
                                role,
                                relative_path,
                                windows_parent_binding=parent_binding,
                            )
                        )
                        continue

                    if action != "enter" or (
                        relative_path and own_entry is None
                    ):
                        raise AssertionError(
                            "Invalid Included Files cleanup traversal action"
                        )

                    parent_binding = active_cleanup_bindings.get(relative_path)
                    if parent_binding is None:
                        parent_binding = open_child_binding(
                            cleanup_binding_scope,
                            active_cleanup_bindings,
                            relative_path,
                        )
                    for entry in sorted(
                        file_entries_by_parent.get(relative_path, ()),
                        key=lambda candidate: candidate.relative_path,
                        reverse=True,
                    ):
                        if entry.content_sha256 is None:
                            warnings.append(
                                "Included Files cleanup manifest omitted a file "
                                "digest: "
                                + entry.relative_path
                            )
                            continue
                        warnings.extend(
                            cleanup_recorded_included_file(
                                recorded_entry_paths[entry.relative_path],
                                entry.fingerprint[:2],
                                entry.content_sha256,
                                directory_identities[relative_path],
                                transaction_id,
                                role,
                                entry.relative_path,
                                expected_fingerprint=entry.fingerprint,
                                windows_parent_binding=parent_binding,
                            )
                        )

                    cleanup_actions.append(
                        ("leave", relative_path, own_entry)
                    )
                    child_entries = sorted(
                        directory_entries_by_parent.get(relative_path, ()),
                        key=lambda candidate: candidate.relative_path,
                        reverse=True,
                    )
                    for entry in reversed(child_entries):
                        child_relative = entry.relative_path
                        has_recorded_children = (
                            child_relative in directory_entries_by_parent
                            or child_relative in file_entries_by_parent
                        )
                        child_action = (
                            "enter"
                            if child_relative not in absent_directories
                            and has_recorded_children
                            else "remove"
                        )
                        cleanup_actions.append(
                            (child_action, child_relative, entry)
                        )

    # The binding deliberately denies deletion sharing, so release it before
    # removing the now-empty root that it protected.
    warnings.extend(
        cleanup_recorded_included_directory(
            path,
            root_identity,
            expected_parent_identity,
            transaction_id,
            role,
            ".",
        )
    )
    return tuple(warnings)


included_cleanup_file_state = _included_cleanup_file_state
included_cleanup_directory_state = _included_cleanup_directory_state
remove_included_cleanup_tombstone = _remove_included_cleanup_tombstone
cleanup_recorded_included_file = _cleanup_recorded_included_file
cleanup_recorded_included_directory = _cleanup_recorded_included_directory
cleanup_recorded_included_tree = _cleanup_recorded_included_tree
