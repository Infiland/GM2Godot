from __future__ import annotations
import os
import secrets
import stat
import sys
from typing import Callable
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import native_posix as _included_posix
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts.filesystem_operations import IncludedCleanupParentBinding as _IncludedCleanupParentBinding
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import phase_observer as _included_phases


def _before_included_transaction_rename(
    _source_parent_fd: int,
    _source_name: str,
) -> None:
    """Narrow test seam immediately before a namespace mutation."""

def _before_included_transaction_rename_fallback(
    _source: str,
    _destination: str,
) -> None:
    """Narrow fallback test seam immediately before a namespace mutation."""

def _preserve_or_restore_unexpected_moved_entry_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    source_display_path: str,
    destination_display_path: str,
) -> OSError:
    try:
        _included_fs.rename_entry_at(
            destination_parent_fd,
            destination_name,
            source_parent_fd,
            source_name,
        )
    except OSError as restore_error:
        destination_parent_path = os.path.dirname(destination_display_path)
        quarantine_name = (
            f".{os.path.basename(destination_display_path)}."
            f"{secrets.token_hex(8)}.quarantine"
        )
        quarantine_path = os.path.join(
            destination_parent_path,
            quarantine_name,
        )
        try:
            _included_fs.rename_entry_at(
                destination_parent_fd,
                destination_name,
                destination_parent_fd,
                quarantine_name,
            )
        except OSError as quarantine_error:
            error = OSError(
                "Unexpected Included Files replacement was preserved at "
                f"{destination_display_path!r}; automatic restore to "
                f"{source_display_path!r} failed"
            )
            error.add_note(f"Restore error: {restore_error}")
            error.add_note(f"Quarantine error: {quarantine_error}")
            return error
        error = OSError(
            "Unexpected Included Files replacement was preserved at "
            f"recoverable quarantine path {quarantine_path!r}; automatic "
            f"restore to {source_display_path!r} failed"
        )
        error.add_note(f"Restore error: {restore_error}")
        return error
    return OSError(
        "Unexpected Included Files replacement was restored without loss to "
        f"{source_display_path!r}; refused transaction move to "
        f"{destination_display_path!r}"
    )

def _preserve_or_restore_unexpected_moved_entry_fallback(
    source: str,
    destination: str,
) -> OSError:
    try:
        _included_fs.rename_entry(destination, source)
    except OSError as restore_error:
        quarantine_path = (
            destination
            + "."
            + secrets.token_hex(8)
            + ".quarantine"
        )
        try:
            _included_fs.rename_entry(destination, quarantine_path)
        except OSError as quarantine_error:
            error = OSError(
                "Unexpected Included Files replacement was preserved at "
                f"{destination!r}; automatic restore to {source!r} failed"
            )
            error.add_note(f"Restore error: {restore_error}")
            error.add_note(f"Quarantine error: {quarantine_error}")
            return error
        error = OSError(
            "Unexpected Included Files replacement was preserved at "
            f"recoverable quarantine path {quarantine_path!r}; automatic "
            f"restore to {source!r} failed"
        )
        error.add_note(f"Restore error: {restore_error}")
        return error
    return OSError(
        "Unexpected Included Files replacement was restored without loss to "
        f"{source!r}; refused transaction move to {destination!r}"
    )

def _before_included_cleanup_quarantine(
    _parent_fd: int,
    _name: str,
) -> None:
    """Narrow test seam before moving a cleanup candidate to quarantine."""

def _before_included_cleanup_remove(
    _parent_fd: int,
    _name: str,
) -> None:
    """Narrow test seam before removing a verified quarantine entry."""

def _quarantine_included_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
    display_path: str,
) -> tuple[str, str]:
    quarantine_name = (
        f".{name}.{secrets.token_hex(8)}.quarantine"
    )
    quarantine_path = os.path.join(
        os.path.dirname(display_path),
        quarantine_name,
    )
    before_included_cleanup_quarantine(parent_fd, name)
    _included_fs.rename_entry_at(
        parent_fd,
        name,
        parent_fd,
        quarantine_name,
    )
    quarantine_stat = _included_metadata.included_entry_stat_at(parent_fd, quarantine_name)
    quarantine_is_expected_kind = (
        quarantine_stat is not None
        and (
            stat.S_ISDIR(quarantine_stat.st_mode)
            if expect_directory
            else not stat.S_ISDIR(quarantine_stat.st_mode)
        )
    )
    if (
        not quarantine_is_expected_kind
        or quarantine_stat is None
        or (quarantine_stat.st_dev, quarantine_stat.st_ino)
        != expected_identity
    ):
        raise preserve_or_restore_unexpected_moved_entry_at(
            parent_fd,
            name,
            parent_fd,
            quarantine_name,
            display_path,
            quarantine_path,
        )
    return quarantine_name, quarantine_path

def _unlink_exact_quarantined_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    before_included_cleanup_remove(parent_fd, name)
    current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"entry retained at {display_path!r}"
        )
    os.unlink(name, dir_fd=parent_fd)

def _rmdir_exact_quarantined_entry_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    before_included_cleanup_remove(parent_fd, name)
    current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"directory retained at {display_path!r}"
        )
    os.rmdir(name, dir_fd=parent_fd)

def _remove_included_tree_contents_at(
    directory_fd: int,
    display_path: str,
    verify_binding: Callable[[], None],
    boundary_device: int,
    boundary_mount_id: int | None,
) -> None:
    verify_binding()
    for name in sorted(os.listdir(directory_fd)):
        verify_binding()
        entry_path = os.path.join(display_path, name)
        entry_stat = _included_metadata.included_entry_stat_at(directory_fd, name)
        if entry_stat is None:
            raise OSError(f"Included Files cleanup entry changed: {entry_path}")
        entry_identity = entry_stat.st_dev, entry_stat.st_ino
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = os.open(
                name,
                _included_posix.DIRECTORY_OPEN_FLAGS,
                dir_fd=directory_fd,
            )
            try:
                child_stat = os.fstat(child_fd)
                if (
                    not stat.S_ISDIR(child_stat.st_mode)
                    or (child_stat.st_dev, child_stat.st_ino)
                    != entry_identity
                ):
                    raise OSError(
                        f"Included Files cleanup directory changed: {entry_path}"
                    )
                _included_fs.verify_mount_boundary(
                    entry_path,
                    child_stat,
                    boundary_device,
                    boundary_mount_id,
                    child_fd,
                )
                quarantined_name, quarantined_path = (
                    quarantine_included_entry_at(
                        directory_fd,
                        name,
                        entry_identity,
                        expect_directory=True,
                        display_path=entry_path,
                    )
                )

                def verify_child_binding() -> None:
                    verify_binding()
                    _included_snapshots.verify_included_directory_entry_identity_at(
                        directory_fd,
                        quarantined_name,
                        entry_identity,
                        quarantined_path,
                    )
                    current_child_stat = os.fstat(child_fd)
                    if (
                        not stat.S_ISDIR(current_child_stat.st_mode)
                        or (current_child_stat.st_dev, current_child_stat.st_ino)
                        != entry_identity
                    ):
                        raise OSError(
                            "Included Files cleanup directory changed: "
                            f"{quarantined_path}"
                        )
                    _included_fs.verify_mount_boundary(
                        quarantined_path,
                        current_child_stat,
                        boundary_device,
                        boundary_mount_id,
                        child_fd,
                    )

                remove_included_tree_contents_at(
                    child_fd,
                    quarantined_path,
                    verify_child_binding,
                    boundary_device,
                    boundary_mount_id,
                )
                verify_child_binding()
                rmdir_exact_quarantined_entry_at(
                    directory_fd,
                    quarantined_name,
                    entry_identity,
                    quarantined_path,
                )
            finally:
                os.close(child_fd)
        else:
            if stat.S_ISREG(entry_stat.st_mode):
                _included_snapshots.verify_included_regular_file_mount_boundary_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    boundary_device,
                    boundary_mount_id,
                )
            quarantined_name, quarantined_path = quarantine_included_entry_at(
                directory_fd,
                name,
                entry_identity,
                expect_directory=False,
                display_path=entry_path,
            )
            unlink_exact_quarantined_entry_at(
                directory_fd,
                quarantined_name,
                entry_identity,
                quarantined_path,
            )
    verify_binding()

def _before_included_cleanup_quarantine_fallback(_path: str) -> None:
    """Narrow fallback test seam before quarantining a cleanup candidate."""

def _before_included_cleanup_remove_fallback(_path: str) -> None:
    """Narrow fallback test seam before removing a quarantine candidate."""

def _quarantine_included_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
) -> str:
    quarantine_path = path + "." + secrets.token_hex(8) + ".quarantine"
    before_included_cleanup_quarantine_fallback(path)
    _included_fs.rename_entry(path, quarantine_path)
    quarantine_stat = os.lstat(quarantine_path)
    quarantine_is_expected_kind = (
        stat.S_ISDIR(quarantine_stat.st_mode)
        if expect_directory
        else not stat.S_ISDIR(quarantine_stat.st_mode)
    )
    if (
        _included_fs.output_path_is_redirected(quarantine_path, quarantine_stat)
        or not quarantine_is_expected_kind
        or (quarantine_stat.st_dev, quarantine_stat.st_ino)
        != expected_identity
    ):
        raise preserve_or_restore_unexpected_moved_entry_fallback(
            path,
            quarantine_path,
        )
    return quarantine_path

def _unlink_exact_quarantined_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    if windows_parent_binding is not None:
        if expected_parent_identity is None:
            raise OSError(
                "Included Files cleanup parent binding requires an exact identity"
            )
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    before_included_cleanup_remove_fallback(path)
    current_stat = os.lstat(path)
    if (
        stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"entry retained at {path!r}"
        )
    original_mode = stat.S_IMODE(current_stat.st_mode)
    windows_read_only = (
        os.name == "nt"
        and not bool(current_stat.st_mode & stat.S_IWRITE)
    )
    if windows_read_only:
        if current_stat.st_nlink != 1:
            raise OSError(
                "Refusing to clear the Windows read-only attribute on an "
                "Included Files cleanup file with multiple hard links; "
                f"recoverable quarantine retained at {path!r}"
            )
        if windows_parent_binding is None:
            parent_identity = _included_snapshots.capture_fallback_directory_ancestors(
                parent_path
            )[-1][1]
        else:
            assert expected_parent_identity is not None
            parent_identity = expected_parent_identity
        try:
            chmod_exact_included_file(
                path,
                expected_identity,
                original_mode | stat.S_IWRITE,
                parent_identity,
                windows_parent_binding=windows_parent_binding,
            )
        except OSError as error:
            raise OSError(
                "Could not clear the Windows read-only attribute from an "
                "identity-verified Included Files cleanup file; recoverable "
                f"quarantine retained at {path!r}"
            ) from error
        writable_stat = os.lstat(path)
        if (
            _included_fs.output_path_is_redirected(path, writable_stat)
            or not stat.S_ISREG(writable_stat.st_mode)
            or (writable_stat.st_dev, writable_stat.st_ino)
            != expected_identity
            or not bool(writable_stat.st_mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files cleanup file changed while clearing its "
                f"Windows read-only attribute: {path!r}"
            )
        _included_phases.after_included_transaction_phase("cleanup-readonly-cleared")
    if windows_parent_binding is not None:
        assert expected_parent_identity is not None
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    try:
        os.unlink(path)
    except OSError as error:
        if windows_read_only:
            try:
                if windows_parent_binding is None:
                    parent_identity = _included_snapshots.capture_fallback_directory_ancestors(
                        parent_path
                    )[-1][1]
                else:
                    assert expected_parent_identity is not None
                    parent_identity = expected_parent_identity
                chmod_exact_included_file(
                    path,
                    expected_identity,
                    original_mode,
                    parent_identity,
                    windows_parent_binding=windows_parent_binding,
                )
            except OSError as restore_error:
                error.add_note(
                    "Restoring the Windows read-only attribute on the "
                    "recoverable Included Files quarantine also failed: "
                    + str(restore_error)
                )
        raise OSError(
            "Could not remove an identity-verified Included Files cleanup "
            f"file; recoverable quarantine retained at {path!r}"
        ) from error

def _chmod_exact_included_directory_fallback(
    path: str,
    expected_identity: _PathIdentity,
    mode: int,
    expected_parent_identity: _PathIdentity,
    *,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities: tuple[tuple[str, _PathIdentity], ...] | None
    if windows_parent_binding is None:
        parent_identities = _included_snapshots.capture_fallback_directory_ancestors(parent_path)
        if parent_identities[-1][1] != expected_parent_identity:
            raise OSError(
                "Included Files directory parent changed before chmod: "
                + parent_path
            )
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
                raise AssertionError("Missing Included Files directory parent state")
            _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
        else:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )

    current_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, current_stat)
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino)
        != expected_identity
    ):
        raise OSError(f"Included Files directory changed before chmod: {path}")
    if bool(current_stat.st_mode & stat.S_IWRITE) == bool(
        mode & stat.S_IWRITE
    ):
        return
    if os.name != "nt":
        raise OSError(
            "Path-based Included Files directory chmod is only supported on "
            "Windows"
        )
    verify_parent()
    quarantined_path = quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=True,
    )
    try:
        quarantined_stat = os.lstat(quarantined_path)
        if (
            _included_fs.output_path_is_redirected(
                quarantined_path,
                quarantined_stat,
            )
            or not stat.S_ISDIR(quarantined_stat.st_mode)
            or (quarantined_stat.st_dev, quarantined_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                "Included Files directory chmod quarantine changed: "
                f"{quarantined_path}"
            )
        os.chmod(quarantined_path, mode)
        changed_stat = os.lstat(quarantined_path)
        if (
            _included_fs.output_path_is_redirected(
                quarantined_path,
                changed_stat,
            )
            or not stat.S_ISDIR(changed_stat.st_mode)
            or (changed_stat.st_dev, changed_stat.st_ino)
            != expected_identity
            or bool(changed_stat.st_mode & stat.S_IWRITE)
            != bool(mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files directory chmod quarantine changed: "
                f"{quarantined_path}"
            )
    except BaseException as error:
        try:
            move_exact_included_directory(
                quarantined_path,
                path,
                expected_identity,
                source_parent_identity=expected_parent_identity,
                destination_parent_identity=expected_parent_identity,
                windows_source_parent_binding=windows_parent_binding,
                windows_destination_parent_binding=windows_parent_binding,
            )
        except BaseException as restore_error:
            error.add_note(
                "Included Files directory chmod quarantine restore also "
                "failed: "
                + str(restore_error)
            )
        raise
    move_exact_included_directory(
        quarantined_path,
        path,
        expected_identity,
        source_parent_identity=expected_parent_identity,
        destination_parent_identity=expected_parent_identity,
        windows_source_parent_binding=windows_parent_binding,
        windows_destination_parent_binding=windows_parent_binding,
    )
    final_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, final_stat)
        or not stat.S_ISDIR(final_stat.st_mode)
        or (final_stat.st_dev, final_stat.st_ino) != expected_identity
        or bool(final_stat.st_mode & stat.S_IWRITE)
        != bool(mode & stat.S_IWRITE)
    ):
        raise OSError(f"Included Files directory changed after chmod: {path}")
    verify_parent()

def _rmdir_exact_quarantined_entry_fallback(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    if windows_parent_binding is not None:
        if expected_parent_identity is None:
            raise OSError(
                "Included Files cleanup parent binding requires an exact identity"
            )
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    before_included_cleanup_remove_fallback(path)
    current_stat = os.lstat(path)
    if (
        not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(
            "Refusing to remove changed Included Files quarantine; recoverable "
            f"directory retained at {path!r}"
        )
    original_mode = stat.S_IMODE(current_stat.st_mode)
    windows_read_only = (
        os.name == "nt"
        and not bool(current_stat.st_mode & stat.S_IWRITE)
    )
    if windows_read_only:
        if windows_parent_binding is None:
            parent_identity = _included_snapshots.capture_fallback_directory_ancestors(
                parent_path
            )[-1][1]
        else:
            assert expected_parent_identity is not None
            parent_identity = expected_parent_identity
        try:
            chmod_exact_included_directory_fallback(
                path,
                expected_identity,
                original_mode | stat.S_IWRITE,
                parent_identity,
                windows_parent_binding=windows_parent_binding,
            )
        except OSError as error:
            raise OSError(
                "Could not clear the Windows read-only attribute from an "
                "identity-verified Included Files cleanup directory; "
                f"recoverable quarantine retained at {path!r}"
            ) from error
        writable_stat = os.lstat(path)
        if (
            _included_fs.output_path_is_redirected(path, writable_stat)
            or not stat.S_ISDIR(writable_stat.st_mode)
            or (writable_stat.st_dev, writable_stat.st_ino)
            != expected_identity
            or not bool(writable_stat.st_mode & stat.S_IWRITE)
        ):
            raise OSError(
                "Included Files cleanup directory changed while clearing its "
                f"Windows read-only attribute: {path!r}"
            )
    if windows_parent_binding is not None:
        assert expected_parent_identity is not None
        _included_fs.verify_windows_cleanup_parent(
            windows_parent_binding,
            parent_path,
            expected_parent_identity,
        )
    try:
        os.rmdir(path)
    except OSError as error:
        if windows_read_only:
            try:
                if windows_parent_binding is None:
                    parent_identity = _included_snapshots.capture_fallback_directory_ancestors(
                        parent_path
                    )[-1][1]
                else:
                    assert expected_parent_identity is not None
                    parent_identity = expected_parent_identity
                chmod_exact_included_directory_fallback(
                    path,
                    expected_identity,
                    original_mode,
                    parent_identity,
                    windows_parent_binding=windows_parent_binding,
                )
            except OSError as restore_error:
                error.add_note(
                    "Restoring the Windows read-only attribute on the "
                    "recoverable Included Files directory quarantine also "
                    "failed: "
                    + str(restore_error)
                )
        raise OSError(
            "Could not remove an identity-verified Included Files cleanup "
            f"directory; recoverable quarantine retained at {path!r}"
        ) from error

def _remove_owned_included_tree_fallback(
    path: str,
    expected_identity: _PathIdentity,
    expected_parent_identity: _PathIdentity | None,
) -> None:
    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = _included_snapshots.capture_fallback_directory_ancestors(parent_path)
    if (
        expected_parent_identity is not None
        and parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files cleanup parent changed: {parent_path}")
    try:
        root_stat = os.lstat(path)
    except FileNotFoundError:
        _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
        return
    if (
        _included_fs.output_path_is_redirected(path, root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
        or (root_stat.st_dev, root_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Refusing to remove changed Included Files tree: {path}")
    parent_mount_id = _included_fs.directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    root_mount_id = _included_fs.verify_mount_boundary_path(
        path,
        root_stat,
        parent_identities[-1][1][0],
        parent_mount_id,
        expect_directory=True,
    )
    quarantined_root_path = quarantine_included_entry_fallback(
        path,
        expected_identity,
        expect_directory=True,
    )

    def remove_directory(
        directory_path: str,
        directory_identity: _PathIdentity,
    ) -> None:
        directory_ancestors = _included_snapshots.capture_fallback_directory_ancestors(
            directory_path
        )
        if directory_ancestors[-1][1] != directory_identity:
            raise OSError(
                f"Included Files cleanup directory changed: {directory_path}"
            )
        directory_stat = os.lstat(directory_path)
        _included_fs.verify_mount_boundary_path(
            directory_path,
            directory_stat,
            root_stat.st_dev,
            root_mount_id,
            expect_directory=True,
        )
        for name in sorted(os.listdir(directory_path)):
            _included_snapshots.verify_fallback_directory_ancestors(directory_ancestors)
            entry_path = os.path.join(directory_path, name)
            entry_stat = os.lstat(entry_path)
            entry_identity = entry_stat.st_dev, entry_stat.st_ino
            if _included_fs.output_path_is_redirected(entry_path, entry_stat):
                raise OSError(
                    f"Refusing redirected Included Files cleanup entry: {entry_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                _included_fs.verify_mount_boundary_path(
                    entry_path,
                    entry_stat,
                    root_stat.st_dev,
                    root_mount_id,
                    expect_directory=True,
                )
                quarantined_entry_path = quarantine_included_entry_fallback(
                    entry_path,
                    entry_identity,
                    expect_directory=True,
                )
                remove_directory(quarantined_entry_path, entry_identity)
                _included_snapshots.verify_fallback_directory_ancestors(directory_ancestors)
                rmdir_exact_quarantined_entry_fallback(
                    quarantined_entry_path,
                    entry_identity,
                )
            else:
                if stat.S_ISREG(entry_stat.st_mode):
                    _included_fs.verify_mount_boundary_path(
                        entry_path,
                        entry_stat,
                        root_stat.st_dev,
                        root_mount_id,
                        expect_directory=False,
                    )
                _included_snapshots.verify_fallback_directory_ancestors(directory_ancestors)
                quarantined_entry_path = quarantine_included_entry_fallback(
                    entry_path,
                    entry_identity,
                    expect_directory=False,
                )
                unlink_exact_quarantined_entry_fallback(
                    quarantined_entry_path,
                    entry_identity,
                )
        _included_snapshots.verify_fallback_directory_ancestors(directory_ancestors)

    remove_directory(quarantined_root_path, expected_identity)
    _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
    rmdir_exact_quarantined_entry_fallback(
        quarantined_root_path,
        expected_identity,
    )

def _remove_owned_included_tree(
    path: str,
    expected_identity: _PathIdentity,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    if not _included_fs.descriptor_paths_supported():
        remove_owned_included_tree_fallback(
            path,
            expected_identity,
            expected_parent_identity,
        )
        return
    parent_fd, name = _included_fs.open_pinned_parent(path)
    try:
        parent_identity = _included_metadata.verify_included_directory_fd(
            parent_fd,
            expected_parent_identity,
            os.path.dirname(path),
        )
        root_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
        if root_stat is None:
            return
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or (root_stat.st_dev, root_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Refusing to remove changed Included Files tree: {path}")
        root_fd = os.open(
            name,
            _included_posix.DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_fd,
        )
        try:
            opened_root_stat = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(opened_root_stat.st_mode)
                or (opened_root_stat.st_dev, opened_root_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Refusing to remove changed Included Files tree: {path}"
                )
            parent_mount_id = _included_fs.linux_mount_id_from_fd(parent_fd)
            root_mount_id = _included_fs.verify_mount_boundary(
                path,
                opened_root_stat,
                parent_identity[0],
                parent_mount_id,
                root_fd,
            )
            quarantined_name, quarantined_path = quarantine_included_entry_at(
                parent_fd,
                name,
                expected_identity,
                expect_directory=True,
                display_path=path,
            )

            def verify_root_binding() -> None:
                _included_snapshots.verify_included_directory_entry_identity_at(
                    parent_fd,
                    quarantined_name,
                    expected_identity,
                    quarantined_path,
                )
                current_root_stat = os.fstat(root_fd)
                if (
                    not stat.S_ISDIR(current_root_stat.st_mode)
                    or (current_root_stat.st_dev, current_root_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(
                        "Refusing to remove changed Included Files tree: "
                        f"{quarantined_path}"
                    )
                _included_fs.verify_mount_boundary(
                    quarantined_path,
                    current_root_stat,
                    opened_root_stat.st_dev,
                    root_mount_id,
                    root_fd,
                )

            remove_included_tree_contents_at(
                root_fd,
                quarantined_path,
                verify_root_binding,
                opened_root_stat.st_dev,
                root_mount_id,
            )
            verify_root_binding()
            rmdir_exact_quarantined_entry_at(
                parent_fd,
                quarantined_name,
                expected_identity,
                quarantined_path,
            )
        finally:
            os.close(root_fd)
    finally:
        os.close(parent_fd)

def _before_included_fallback_chmod_open(_path: str) -> None:
    """Narrow test seam before opening a fallback chmod target."""

def _chmod_exact_included_file(
    path: str,
    expected_identity: _PathIdentity,
    mode: int,
    expected_parent_identity: _PathIdentity,
    *,
    windows_parent_binding: _IncludedCleanupParentBinding | None = None,
) -> None:
    if _included_fs.descriptor_paths_supported():
        parent_fd, name = _included_fs.open_pinned_parent(path)
        try:
            _included_metadata.verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            file_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                opened_stat = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(opened_stat.st_mode)
                    or (opened_stat.st_dev, opened_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(f"Included Files file changed: {path}")
                os.chmod(file_descriptor, mode)
            finally:
                os.close(file_descriptor)
        finally:
            os.close(parent_fd)
        return
    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities: tuple[tuple[str, _PathIdentity], ...] | None
    if windows_parent_binding is None:
        parent_identities = _included_snapshots.capture_fallback_directory_ancestors(parent_path)
        if parent_identities[-1][1] != expected_parent_identity:
            raise OSError(f"Included Files file parent changed: {path}")
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
                raise AssertionError("Missing Included Files file parent state")
            _included_snapshots.verify_fallback_directory_ancestors(parent_identities)
        else:
            _included_fs.verify_windows_cleanup_parent(
                windows_parent_binding,
                parent_path,
                expected_parent_identity,
            )

    try:
        path_stat = os.lstat(path)
    except FileNotFoundError as error:
        raise OSError(f"Included Files file changed: {path}") from error
    if (
        _included_fs.output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files file changed: {path}")
    verify_parent()
    before_included_fallback_chmod_open(path)
    file_descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    path_chmod_required = False
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino) != expected_identity
        ):
            raise OSError(f"Included Files file changed: {path}")
        verify_parent()
        if os.chmod in os.supports_fd:
            os.chmod(file_descriptor, mode)
        elif os.name == "nt":
            path_chmod_required = bool(opened_stat.st_mode & stat.S_IWRITE) != (
                bool(mode & stat.S_IWRITE)
            )
        else:
            raise OSError(
                "Descriptor-bound Included Files chmod is unavailable on "
                f"{sys.platform}"
            )
    finally:
        os.close(file_descriptor)
    if path_chmod_required:
        verify_parent()
        quarantined_path = quarantine_included_entry_fallback(
            path,
            expected_identity,
            expect_directory=False,
        )
        try:
            quarantined_stat = os.lstat(quarantined_path)
            if (
                not stat.S_ISREG(quarantined_stat.st_mode)
                or (quarantined_stat.st_dev, quarantined_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    "Included Files chmod quarantine changed: "
                    f"{quarantined_path}"
                )
            os.chmod(quarantined_path, mode)
            changed_stat = os.lstat(quarantined_path)
            if (
                not stat.S_ISREG(changed_stat.st_mode)
                or (changed_stat.st_dev, changed_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    "Included Files chmod quarantine changed: "
                    f"{quarantined_path}"
                )
        except BaseException as error:
            try:
                move_exact_included_file(
                    quarantined_path,
                    path,
                    expected_identity,
                    source_parent_identity=expected_parent_identity,
                    destination_parent_identity=expected_parent_identity,
                    windows_source_parent_binding=windows_parent_binding,
                    windows_destination_parent_binding=windows_parent_binding,
                )
            except OSError as restore_error:
                error.add_note(
                    "Included Files chmod quarantine restore also failed: "
                    + str(restore_error)
                )
            raise
        move_exact_included_file(
            quarantined_path,
            path,
            expected_identity,
            source_parent_identity=expected_parent_identity,
            destination_parent_identity=expected_parent_identity,
            windows_source_parent_binding=windows_parent_binding,
            windows_destination_parent_binding=windows_parent_binding,
        )
    try:
        current_stat = os.lstat(path)
    except FileNotFoundError as error:
        raise OSError(f"Included Files file changed: {path}") from error
    if (
        _included_fs.output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files file changed: {path}")
    verify_parent()

def _unique_included_transaction_path(
    directory: str,
    label: str,
) -> str:
    for _attempt in range(100):
        candidate = os.path.join(
            directory,
            f".{label}.{secrets.token_hex(8)}.backup",
        )
        if not os.path.lexists(candidate):
            return candidate
    raise OSError(f"Could not allocate Included Files transaction backup for {label}")

def _move_exact_included_entry(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    expect_directory: bool,
    source_parent_identity: _PathIdentity | None,
    destination_parent_identity: _PathIdentity | None,
    windows_source_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
    windows_destination_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
) -> None:
    source_parent_path = os.path.dirname(os.path.abspath(source))
    destination_parent_path = os.path.dirname(os.path.abspath(destination))
    if _included_fs.descriptor_paths_supported():
        source_parent_fd, source_name = _included_fs.open_pinned_parent(source)
        try:
            _included_metadata.verify_included_directory_fd(
                source_parent_fd,
                source_parent_identity,
                source_parent_path,
            )
            destination_parent_fd, destination_name = (
                _included_fs.open_pinned_parent(destination)
            )
            try:
                _included_metadata.verify_included_directory_fd(
                    destination_parent_fd,
                    destination_parent_identity,
                    destination_parent_path,
                )
                source_stat = _included_metadata.included_entry_stat_at(
                    source_parent_fd,
                    source_name,
                )
                if source_stat is None:
                    raise OSError(
                        f"Included Files transaction source disappeared: {source}"
                    )
                source_is_expected_kind = (
                    stat.S_ISDIR(source_stat.st_mode)
                    if expect_directory
                    else stat.S_ISREG(source_stat.st_mode)
                )
                if (
                    not source_is_expected_kind
                    or (source_stat.st_dev, source_stat.st_ino)
                    != expected_identity
                ):
                    raise OSError(
                        f"Included Files transaction source changed: {source}"
                    )
                before_included_transaction_rename(
                    source_parent_fd,
                    source_name,
                )
                _included_fs.rename_entry_at(
                    source_parent_fd,
                    source_name,
                    destination_parent_fd,
                    destination_name,
                )
                destination_stat = _included_metadata.included_entry_stat_at(
                    destination_parent_fd,
                    destination_name,
                )
                destination_is_expected_kind = (
                    destination_stat is not None
                    and (
                        stat.S_ISDIR(destination_stat.st_mode)
                        if expect_directory
                        else stat.S_ISREG(destination_stat.st_mode)
                    )
                )
                if (
                    not destination_is_expected_kind
                    or destination_stat is None
                    or (destination_stat.st_dev, destination_stat.st_ino)
                    != expected_identity
                ):
                    raise preserve_or_restore_unexpected_moved_entry_at(
                        source_parent_fd,
                        source_name,
                        destination_parent_fd,
                        destination_name,
                        source,
                        destination,
                    )
            finally:
                os.close(destination_parent_fd)
        finally:
            os.close(source_parent_fd)
        return

    source_parent_ancestors: tuple[tuple[str, _PathIdentity], ...] | None
    if windows_source_parent_binding is None:
        source_parent_ancestors = _included_snapshots.capture_fallback_directory_ancestors(
            source_parent_path
        )
        if (
            source_parent_identity is not None
            and source_parent_ancestors[-1][1] != source_parent_identity
        ):
            raise OSError(
                f"Included Files source parent changed: {source_parent_path}"
            )
    else:
        source_parent_ancestors = None
        if source_parent_identity is None:
            raise OSError(
                "Included Files source parent binding requires an exact identity"
            )
        _included_fs.verify_windows_cleanup_parent(
            windows_source_parent_binding,
            source_parent_path,
            source_parent_identity,
        )

    destination_parent_ancestors: (
        tuple[tuple[str, _PathIdentity], ...] | None
    )
    if windows_destination_parent_binding is None:
        destination_parent_ancestors = _included_snapshots.capture_fallback_directory_ancestors(
            destination_parent_path
        )
        if (
            destination_parent_identity is not None
            and destination_parent_ancestors[-1][1]
            != destination_parent_identity
        ):
            raise OSError(
                "Included Files destination parent changed: "
                + destination_parent_path
            )
    else:
        destination_parent_ancestors = None
        if destination_parent_identity is None:
            raise OSError(
                "Included Files destination parent binding requires an exact identity"
            )
        _included_fs.verify_windows_cleanup_parent(
            windows_destination_parent_binding,
            destination_parent_path,
            destination_parent_identity,
        )

    def verify_parents() -> None:
        if windows_source_parent_binding is None:
            if source_parent_ancestors is None:
                raise AssertionError("Missing Included Files source parent state")
            _included_snapshots.verify_fallback_directory_ancestors(source_parent_ancestors)
        else:
            if source_parent_identity is None:
                raise AssertionError("Missing Included Files source parent identity")
            _included_fs.verify_windows_cleanup_parent(
                windows_source_parent_binding,
                source_parent_path,
                source_parent_identity,
            )
        if windows_destination_parent_binding is None:
            if destination_parent_ancestors is None:
                raise AssertionError("Missing Included Files destination parent state")
            _included_snapshots.verify_fallback_directory_ancestors(destination_parent_ancestors)
        elif windows_destination_parent_binding is not windows_source_parent_binding:
            if destination_parent_identity is None:
                raise AssertionError(
                    "Missing Included Files destination parent identity"
                )
            _included_fs.verify_windows_cleanup_parent(
                windows_destination_parent_binding,
                destination_parent_path,
                destination_parent_identity,
            )
    source_stat = os.lstat(source)
    source_is_expected_kind = (
        stat.S_ISDIR(source_stat.st_mode)
        if expect_directory
        else stat.S_ISREG(source_stat.st_mode)
    )
    if (
        _included_fs.output_path_is_redirected(source, source_stat)
        or not source_is_expected_kind
        or (source_stat.st_dev, source_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files transaction source changed: {source}")
    if os.path.lexists(destination):
        raise OSError(
            f"Included Files transaction destination already exists: {destination}"
        )
    verify_parents()
    before_included_transaction_rename_fallback(source, destination)
    verify_parents()
    _included_fs.rename_entry(source, destination)
    verify_parents()
    destination_stat = os.lstat(destination)
    destination_is_expected_kind = (
        stat.S_ISDIR(destination_stat.st_mode)
        if expect_directory
        else stat.S_ISREG(destination_stat.st_mode)
    )
    if (
        _included_fs.output_path_is_redirected(destination, destination_stat)
        or not destination_is_expected_kind
        or (destination_stat.st_dev, destination_stat.st_ino)
        != expected_identity
    ):
        raise preserve_or_restore_unexpected_moved_entry_fallback(
            source,
            destination,
        )

def _move_exact_included_directory(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    source_parent_identity: _PathIdentity | None = None,
    destination_parent_identity: _PathIdentity | None = None,
    windows_source_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
    windows_destination_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
) -> None:
    move_exact_included_entry(
        source,
        destination,
        expected_identity,
        expect_directory=True,
        source_parent_identity=source_parent_identity,
        destination_parent_identity=destination_parent_identity,
        windows_source_parent_binding=windows_source_parent_binding,
        windows_destination_parent_binding=windows_destination_parent_binding,
    )

def _move_exact_included_file(
    source: str,
    destination: str,
    expected_identity: _PathIdentity,
    *,
    source_parent_identity: _PathIdentity | None = None,
    destination_parent_identity: _PathIdentity | None = None,
    windows_source_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
    windows_destination_parent_binding: (
        _IncludedCleanupParentBinding | None
    ) = None,
) -> None:
    move_exact_included_entry(
        source,
        destination,
        expected_identity,
        expect_directory=False,
        source_parent_identity=source_parent_identity,
        destination_parent_identity=destination_parent_identity,
        windows_source_parent_binding=windows_source_parent_binding,
        windows_destination_parent_binding=windows_destination_parent_binding,
    )


before_included_transaction_rename = _before_included_transaction_rename
before_included_transaction_rename_fallback = _before_included_transaction_rename_fallback
preserve_or_restore_unexpected_moved_entry_at = _preserve_or_restore_unexpected_moved_entry_at
preserve_or_restore_unexpected_moved_entry_fallback = _preserve_or_restore_unexpected_moved_entry_fallback
before_included_cleanup_quarantine = _before_included_cleanup_quarantine
before_included_cleanup_remove = _before_included_cleanup_remove
quarantine_included_entry_at = _quarantine_included_entry_at
unlink_exact_quarantined_entry_at = _unlink_exact_quarantined_entry_at
rmdir_exact_quarantined_entry_at = _rmdir_exact_quarantined_entry_at
remove_included_tree_contents_at = _remove_included_tree_contents_at
before_included_cleanup_quarantine_fallback = _before_included_cleanup_quarantine_fallback
before_included_cleanup_remove_fallback = _before_included_cleanup_remove_fallback
quarantine_included_entry_fallback = _quarantine_included_entry_fallback
unlink_exact_quarantined_entry_fallback = _unlink_exact_quarantined_entry_fallback
chmod_exact_included_directory_fallback = _chmod_exact_included_directory_fallback
rmdir_exact_quarantined_entry_fallback = _rmdir_exact_quarantined_entry_fallback
remove_owned_included_tree_fallback = _remove_owned_included_tree_fallback
remove_owned_included_tree = _remove_owned_included_tree
before_included_fallback_chmod_open = _before_included_fallback_chmod_open
chmod_exact_included_file = _chmod_exact_included_file
unique_included_transaction_path = _unique_included_transaction_path
move_exact_included_entry = _move_exact_included_entry
move_exact_included_directory = _move_exact_included_directory
move_exact_included_file = _move_exact_included_file
