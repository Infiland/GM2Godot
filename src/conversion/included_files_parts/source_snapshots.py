from __future__ import annotations
import hashlib
import os
import posixpath
import stat
from dataclasses import replace
from typing import BinaryIO
from src.conversion.included_files_parts.models import PathIdentity as _PathIdentity, IncludedSourceDirectoryIdentity as _IncludedSourceDirectoryIdentity, IncludedSourceBinding as _IncludedSourceBinding, IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt, IncludedGenerationContentReceipt as _IncludedGenerationContentReceipt, IncludedTreeEntry as _IncludedTreeEntry, IncludedTreeSnapshot as _IncludedTreeSnapshot, IncludedTreeDescriptorBinding as _IncludedTreeDescriptorBinding, IncludedTreePathBinding as _IncludedTreePathBinding, IncludedRegistrySnapshot as _IncludedRegistrySnapshot
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.included_files_parts import native_posix as _included_posix
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs


def _read_included_validation_chunk(opened_file: BinaryIO) -> bytes:
    """Read one validation chunk through a deterministic accounting seam."""

    return opened_file.read(1024 * 1024)

def _digest_open_included_file(
    opened_file: BinaryIO,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = read_included_validation_chunk(opened_file)
        if not chunk:
            break
        digest.update(chunk)
        byte_count += len(chunk)
    return byte_count, digest.hexdigest()

def _digest_included_regular_file(
    path: str,
    expected_stat: os.stat_result,
    *,
    expected_device: int | None = None,
    expected_mount_id: int | None = None,
) -> str:
    expected_fingerprint = _included_metadata.included_path_fingerprint(expected_stat)
    expected_binding = _included_metadata.included_path_handle_binding(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    with _included_fs.open_validation_stream(
        path,
        deny_writes=True,
        no_follow=True,
    ) as opened_file:
        opened_stat = os.fstat(opened_file.fileno())
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_metadata.included_path_handle_binding(opened_stat) != expected_binding
        ):
            raise OSError(f"Included Files file changed before hashing: {path}")
        if expected_device is not None:
            _included_fs.verify_mount_boundary(
                path,
                opened_stat,
                expected_device,
                expected_mount_id,
                opened_file.fileno(),
            )
        opened_state = _included_metadata.included_handle_state(opened_stat)
        byte_count, content_sha256 = digest_open_included_file(opened_file)
        current_opened_stat = os.fstat(opened_file.fileno())
        if (
            _included_metadata.included_handle_state(current_opened_stat) != opened_state
            or byte_count != expected_stat.st_size
        ):
            raise OSError(
                f"Included Files file changed while hashing: {path}"
            )

        current_stat = os.lstat(path)
        if (
            _included_fs.output_path_is_redirected(path, current_stat)
            or not stat.S_ISREG(current_stat.st_mode)
            or _included_metadata.included_path_fingerprint(current_stat) != expected_fingerprint
            or current_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files file changed while hashing: {path}"
            )
    return content_sha256

def _capture_fallback_directory_ancestors(
    directory_path: str,
) -> tuple[tuple[str, _PathIdentity], ...]:
    absolute_path = os.path.abspath(directory_path)
    drive, tail = os.path.splitdrive(absolute_path)
    anchor = drive + os.sep
    components = [component for component in tail.split(os.sep) if component]
    if components:
        platform_anchor = os.path.join(anchor, components[0])
        current_path = os.path.realpath(platform_anchor)
        remaining_components = components[1:]
    else:
        current_path = anchor
        remaining_components = []
    identities: list[tuple[str, _PathIdentity]] = []
    for component in (None, *remaining_components):
        if component is not None:
            current_path = os.path.join(current_path, component)
        try:
            current_stat = os.lstat(current_path)
        except OSError as error:
            raise OSError(
                f"Included Files directory ancestor changed: {current_path}"
            ) from error
        if (
            _included_fs.output_path_is_redirected(current_path, current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
        ):
            raise OSError(
                f"Refusing redirected or non-directory Included Files ancestor: "
                f"{current_path}"
            )
        identities.append(
            (current_path, (current_stat.st_dev, current_stat.st_ino))
        )
    return tuple(identities)

def _verify_fallback_directory_ancestors(
    identities: tuple[tuple[str, _PathIdentity], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            current_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Included Files directory ancestor changed: {directory_path}"
            ) from error
        if (
            _included_fs.output_path_is_redirected(directory_path, current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
            or (current_stat.st_dev, current_stat.st_ino) != expected_identity
        ):
            raise OSError(
                f"Included Files directory ancestor changed: {directory_path}"
            )

def _capture_included_source_directory_identities(
    project_root: str,
    source_path: str,
) -> tuple[str, tuple[_IncludedSourceDirectoryIdentity, ...]]:
    canonical_root = os.path.normcase(os.path.realpath(project_root))
    canonical_path = os.path.normcase(os.path.realpath(source_path))
    try:
        contained = (
            os.path.commonpath((canonical_root, canonical_path))
            == canonical_root
        )
    except ValueError:
        contained = False
    if not contained or canonical_path == canonical_root:
        raise OSError(
            "GameMaker Included File source escapes the selected project: "
            f"{source_path}"
        )

    directory_path = canonical_root
    directory_identities: list[_IncludedSourceDirectoryIdentity] = []
    relative_directory = os.path.relpath(
        os.path.dirname(canonical_path),
        canonical_root,
    )
    components = (
        ()
        if relative_directory == os.curdir
        else tuple(relative_directory.split(os.sep))
    )
    for component in (None, *components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
        directory_stat = os.lstat(directory_path)
        if (
            _included_fs.output_path_is_redirected(
                directory_path,
                directory_stat,
            )
            or not stat.S_ISDIR(directory_stat.st_mode)
        ):
            raise OSError(
                "GameMaker Included File source directory is redirected or "
                f"invalid: {directory_path}"
            )
        directory_identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return canonical_path, tuple(directory_identities)

def _included_directory_identity(path: str) -> _PathIdentity | None:
    if _included_fs.descriptor_paths_supported():
        try:
            directory_fd = _included_fs.open_pinned_directory(path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise OSError(
                f"Refusing redirected or non-directory Included Files path: {path}"
            ) from error
        try:
            return _included_metadata.directory_identity_from_fd(directory_fd)
        finally:
            os.close(directory_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    parent_identities = capture_fallback_directory_ancestors(parent_path)
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_fs.output_path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
    ):
        raise OSError(f"Refusing redirected or non-directory Included Files path: {path}")
    verify_fallback_directory_ancestors(parent_identities)
    return (path_stat.st_dev, path_stat.st_ino)

def _included_regular_file_state_at(
    parent_fd: int,
    name: str,
    display_path: str,
    *,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    parent_stat = os.fstat(parent_fd)
    parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
    parent_mount_id = _included_fs.linux_mount_id_from_fd(parent_fd)
    path_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
    if path_stat is None:
        return None
    if not stat.S_ISREG(path_stat.st_mode):
        raise OSError(
            f"Refusing redirected or non-regular Included Files path: {display_path}"
        )
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(
            f"Included Files path changed before reading: {display_path}"
        )
    expected_fingerprint = _included_metadata.included_path_fingerprint(path_stat)
    expected_ctime_ns = path_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_metadata.included_path_fingerprint(opened_stat) != expected_fingerprint
            or opened_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files path changed while reading: {display_path}"
            )
        _included_fs.verify_mount_boundary(
            display_path,
            opened_stat,
            parent_identity[0],
            parent_mount_id,
            file_descriptor,
        )
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = opened_file.read()
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_metadata.included_path_fingerprint(current_stat) != expected_fingerprint
        or current_stat.st_ctime_ns != expected_ctime_ns
    ):
        raise OSError(
            f"Included Files path changed while reading: {display_path}"
        )
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )

def _before_included_fallback_regular_file_open(_path: str) -> None:
    """Narrow test seam before opening a fallback regular-file path."""

def _included_regular_file_state(
    path: str,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    expected_fallback_ancestors: (
        tuple[tuple[str, _PathIdentity], ...] | None
    ) = None,
    allowed_identities: frozenset[_PathIdentity] | None = None,
) -> tuple[_PathIdentity, int, bytes] | None:
    if _included_fs.descriptor_paths_supported():
        try:
            parent_fd, name = _included_fs.open_pinned_parent(path)
        except FileNotFoundError:
            return None
        try:
            _included_metadata.verify_included_directory_fd(
                parent_fd,
                expected_parent_identity,
                os.path.dirname(path),
            )
            return included_regular_file_state_at(
                parent_fd,
                name,
                path,
                allowed_identities=allowed_identities,
            )
        finally:
            os.close(parent_fd)

    parent_path = os.path.dirname(os.path.abspath(path))
    if expected_fallback_ancestors is None:
        parent_identities = capture_fallback_directory_ancestors(parent_path)
    else:
        parent_identities = expected_fallback_ancestors
        if (
            not parent_identities
            or os.path.normcase(os.path.abspath(parent_identities[-1][0]))
            != os.path.normcase(parent_path)
        ):
            raise OSError(
                f"Included Files fallback ancestry does not bind parent: {path}"
            )
    if (
        expected_parent_identity is not None
        and parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files file parent changed: {path}")
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        verify_fallback_directory_ancestors(parent_identities)
        return None
    if (
        _included_fs.output_path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
    ):
        raise OSError(f"Refusing redirected or non-regular Included Files path: {path}")
    path_identity = path_stat.st_dev, path_stat.st_ino
    if (
        allowed_identities is not None
        and path_identity not in allowed_identities
    ):
        raise OSError(f"Included Files path changed before reading: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    parent_mount_id = _included_fs.directory_mount_id(
        parent_path,
        parent_identities[-1][1],
    )
    verify_fallback_directory_ancestors(parent_identities)
    before_included_fallback_regular_file_open(path)
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode) or not os.path.samestat(
            path_stat,
            opened_stat,
        ):
            raise OSError(f"Included Files path changed while reading: {path}")
        _included_fs.verify_mount_boundary(
            path,
            opened_stat,
            parent_identities[-1][1][0],
            parent_mount_id,
            file_descriptor,
        )
        verify_fallback_directory_ancestors(parent_identities)
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            content = opened_file.read()
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)

    current_stat = os.lstat(path)
    if (
        _included_fs.output_path_is_redirected(path, current_stat)
        or not stat.S_ISREG(current_stat.st_mode)
        or _included_metadata.included_path_fingerprint(current_stat)
        != _included_metadata.included_path_fingerprint(path_stat)
        or current_stat.st_ctime_ns != path_stat.st_ctime_ns
    ):
        raise OSError(f"Included Files path changed while reading: {path}")
    verify_fallback_directory_ancestors(parent_identities)
    return (
        (current_stat.st_dev, current_stat.st_ino),
        stat.S_IMODE(current_stat.st_mode),
        content,
    )

def _digest_included_regular_file_at(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    display_path: str,
    *,
    expected_device: int | None = None,
    expected_mount_id: int | None = None,
) -> str:
    expected_fingerprint = _included_metadata.included_path_fingerprint(expected_stat)
    expected_binding = _included_metadata.included_path_handle_binding(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_metadata.included_path_handle_binding(opened_stat) != expected_binding
        ):
            raise OSError(
                f"Included Files file changed before hashing: {display_path}"
            )
        if expected_device is not None:
            _included_fs.verify_mount_boundary(
                display_path,
                opened_stat,
                expected_device,
                expected_mount_id,
                file_descriptor,
            )
        opened_state = _included_metadata.included_handle_state(opened_stat)
        with os.fdopen(file_descriptor, "rb") as opened_file:
            file_descriptor = -1
            byte_count, content_sha256 = digest_open_included_file(opened_file)
            current_opened_stat = os.fstat(opened_file.fileno())
            if (
                _included_metadata.included_handle_state(current_opened_stat) != opened_state
                or byte_count != expected_stat.st_size
            ):
                raise OSError(
                    "Included Files file changed while hashing: "
                    f"{display_path}"
                )

            current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
            if (
                current_stat is None
                or not stat.S_ISREG(current_stat.st_mode)
                or _included_metadata.included_path_fingerprint(current_stat)
                != expected_fingerprint
                or current_stat.st_ctime_ns != expected_ctime_ns
            ):
                raise OSError(
                    "Included Files file changed while hashing: "
                    f"{display_path}"
                )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    return content_sha256

def _verify_included_regular_file_mount_boundary_at(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    display_path: str,
    expected_device: int,
    expected_mount_id: int | None,
) -> None:
    expected_fingerprint = _included_metadata.included_path_fingerprint(expected_stat)
    expected_ctime_ns = expected_stat.st_ctime_ns
    file_descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _included_metadata.included_path_fingerprint(opened_stat) != expected_fingerprint
            or opened_stat.st_ctime_ns != expected_ctime_ns
        ):
            raise OSError(
                f"Included Files file changed while checking its mount: {display_path}"
            )
        _included_fs.verify_mount_boundary(
            display_path,
            opened_stat,
            expected_device,
            expected_mount_id,
            file_descriptor,
        )
    finally:
        os.close(file_descriptor)

def _verify_included_tree_descriptor_binding(
    binding: _IncludedTreeDescriptorBinding,
) -> None:
    """Verify one link in a retained descriptor chain."""

    _included_metadata.verify_included_entry_at(
        binding.parent_fd,
        binding.name,
        binding.fingerprint,
        binding.display_path,
    )

def _verify_included_tree_path_binding(
    binding: _IncludedTreePathBinding,
) -> os.stat_result:
    """Verify one fallback directory through its complete current path."""

    try:
        current_stat = os.lstat(binding.path)
    except OSError as error:
        raise OSError(
            f"Included Files directory changed: {binding.path}"
        ) from error
    if (
        _included_fs.output_path_is_redirected(binding.path, current_stat)
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != binding.identity
    ):
        raise OSError(f"Included Files directory changed: {binding.path}")
    return current_stat

def _capture_included_tree_from_fd(
    directory_fd: int,
    relative_directory: str,
    display_path: str,
    binding: _IncludedTreeDescriptorBinding,
    boundary_device: int,
    boundary_mount_id: int | None,
    *,
    include_content: bool,
) -> list[_IncludedTreeEntry]:
    verify_included_tree_descriptor_binding(binding)
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as error:
        raise OSError(
            f"Could not inspect Included Files directory: {display_path}"
        ) from error
    entries: list[_IncludedTreeEntry] = []
    for name in names:
        verify_included_tree_descriptor_binding(binding)
        entry_path = os.path.join(display_path, name)
        entry_stat = _included_metadata.included_entry_stat_at(directory_fd, name)
        if entry_stat is None:
            raise OSError(
                f"Included Files tree changed while inspecting: {entry_path}"
            )
        relative_path = posixpath.join(relative_directory, name)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise OSError(
                f"Refusing redirected entry in Included Files tree: {entry_path}"
            )
        entry_fingerprint = _included_metadata.included_path_fingerprint(entry_stat)
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = _included_fs.open_tree_directory_at(directory_fd, name)
            try:
                child_stat = os.fstat(child_fd)
                if (
                    not stat.S_ISDIR(child_stat.st_mode)
                    or _included_metadata.included_path_fingerprint(child_stat)
                    != entry_fingerprint
                ):
                    raise OSError(
                        f"Included Files directory changed: {entry_path}"
                    )
                _included_fs.verify_mount_boundary(
                    entry_path,
                    child_stat,
                    boundary_device,
                    boundary_mount_id,
                    child_fd,
                )
                child_binding = _IncludedTreeDescriptorBinding(
                    parent_fd=directory_fd,
                    name=name,
                    fingerprint=entry_fingerprint,
                    display_path=entry_path,
                )

                entries.extend(
                    capture_included_tree_from_fd(
                        child_fd,
                        relative_path,
                        entry_path,
                        child_binding,
                        boundary_device,
                        boundary_mount_id,
                        include_content=include_content,
                    )
                )
            finally:
                os.close(child_fd)
            verify_included_tree_descriptor_binding(binding)
            verify_included_tree_descriptor_binding(child_binding)
            kind = "directory"
            ctime_ns = None
            content_sha256 = None
        elif stat.S_ISREG(entry_stat.st_mode):
            kind = "file"
            ctime_ns = entry_stat.st_ctime_ns
            if include_content:
                content_sha256 = digest_included_regular_file_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    expected_device=boundary_device,
                    expected_mount_id=boundary_mount_id,
                )
            else:
                verify_included_regular_file_mount_boundary_at(
                    directory_fd,
                    name,
                    entry_stat,
                    entry_path,
                    boundary_device,
                    boundary_mount_id,
                )
                content_sha256 = None
        else:
            raise OSError(
                f"Refusing non-regular entry in Included Files tree: {entry_path}"
            )
        entries.append(
            _IncludedTreeEntry(
                relative_path=relative_path,
                kind=kind,
                fingerprint=entry_fingerprint,
                ctime_ns=ctime_ns,
                content_sha256=content_sha256,
            )
        )
    verify_included_tree_descriptor_binding(binding)
    return entries

def _capture_included_tree_descriptor(
    root_path: str,
    expected_parent_identity: _PathIdentity | None,
    *,
    include_content: bool,
) -> _IncludedTreeSnapshot:
    parent_fd, root_name = _included_fs.open_pinned_parent(root_path)
    try:
        parent_stat = os.fstat(parent_fd)
        parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        parent_mount_id = _included_fs.linux_mount_id_from_fd(parent_fd)
        if (
            expected_parent_identity is not None
            and parent_identity != expected_parent_identity
        ):
            raise OSError(f"Included Files root parent changed: {root_path}")
        parent_path = os.path.dirname(os.path.abspath(root_path))
        root_stat = _included_metadata.included_entry_stat_at(parent_fd, root_name)
        if root_stat is None:
            if included_directory_identity(parent_path) != parent_identity:
                raise OSError(
                    f"Included Files root parent changed: {parent_path}"
                )
            return _IncludedTreeSnapshot(root_fingerprint=None, entries=())
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(
                f"Refusing redirected or non-directory Included Files root: {root_path}"
            )
        root_fingerprint = _included_metadata.included_path_fingerprint(root_stat)
        root_fd = _included_fs.open_tree_directory_at(parent_fd, root_name)
        try:
            opened_root_stat = os.fstat(root_fd)
            if _included_metadata.included_path_fingerprint(opened_root_stat) != root_fingerprint:
                raise OSError(
                    f"Included Files root changed while opening: {root_path}"
                )
            root_mount_id = _included_fs.verify_mount_boundary(
                root_path,
                opened_root_stat,
                parent_stat.st_dev,
                parent_mount_id,
                root_fd,
            )
            root_binding = _IncludedTreeDescriptorBinding(
                parent_fd=parent_fd,
                name=root_name,
                fingerprint=root_fingerprint,
                display_path=root_path,
            )

            entries = capture_included_tree_from_fd(
                root_fd,
                "",
                root_path,
                root_binding,
                opened_root_stat.st_dev,
                root_mount_id,
                include_content=include_content,
            )
        finally:
            os.close(root_fd)
        verify_included_tree_descriptor_binding(root_binding)
        if included_directory_identity(parent_path) != parent_identity:
            raise OSError(f"Included Files root parent changed: {parent_path}")
        return _IncludedTreeSnapshot(
            root_fingerprint=root_fingerprint,
            entries=tuple(
                sorted(
                    entries,
                    key=lambda entry: (entry.relative_path, entry.kind),
                )
            ),
        )
    finally:
        os.close(parent_fd)

def _after_included_fallback_tree_directory_scan(_path: str) -> None:
    """Narrow test seam after a fallback path scan returns its entries."""

def _capture_included_tree_fallback(
    root_path: str,
    expected_parent_identity: _PathIdentity | None,
    *,
    include_content: bool,
) -> _IncludedTreeSnapshot:
    root_parent_path = os.path.dirname(os.path.abspath(root_path))
    root_parent_identities = capture_fallback_directory_ancestors(
        root_parent_path
    )
    if (
        expected_parent_identity is not None
        and root_parent_identities[-1][1] != expected_parent_identity
    ):
        raise OSError(f"Included Files root parent changed: {root_path}")
    try:
        root_stat = os.lstat(root_path)
    except FileNotFoundError:
        verify_fallback_directory_ancestors(root_parent_identities)
        return _IncludedTreeSnapshot(root_fingerprint=None, entries=())
    if (
        _included_fs.output_path_is_redirected(root_path, root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected or non-directory Included Files root: {root_path}"
        )

    root_fingerprint = _included_metadata.included_path_fingerprint(root_stat)
    parent_mount_id = _included_fs.directory_mount_id(
        root_parent_path,
        root_parent_identities[-1][1],
    )
    root_mount_id = _included_fs.verify_mount_boundary_path(
        root_path,
        root_stat,
        root_parent_identities[-1][1][0],
        parent_mount_id,
        expect_directory=True,
    )
    entries: list[_IncludedTreeEntry] = []
    pending: list[tuple[str, _IncludedTreePathBinding]] = [
        (
            "",
            _IncludedTreePathBinding(
                path=root_path,
                identity=(root_stat.st_dev, root_stat.st_ino),
            ),
        )
    ]
    while pending:
        relative_directory, directory_binding = pending.pop()
        directory_path = directory_binding.path
        directory_stat = verify_included_tree_path_binding(directory_binding)
        _included_fs.verify_mount_boundary_path(
            directory_path,
            directory_stat,
            root_stat.st_dev,
            root_mount_id,
            expect_directory=True,
        )
        verify_included_tree_path_binding(directory_binding)
        try:
            directory_entries = sorted(
                os.scandir(directory_path),
                key=lambda entry: entry.name,
            )
        except OSError as error:
            raise OSError(
                f"Could not inspect Included Files directory: {directory_path}"
            ) from error
        after_included_fallback_tree_directory_scan(directory_path)
        verify_included_tree_path_binding(directory_binding)
        for directory_entry in directory_entries:
            verify_included_tree_path_binding(directory_binding)
            entry_path = os.path.join(directory_path, directory_entry.name)
            try:
                entry_stat = os.lstat(entry_path)
            except OSError as error:
                raise OSError(
                    f"Included Files tree changed while inspecting: {entry_path}"
                ) from error
            relative_path = posixpath.join(
                relative_directory,
                directory_entry.name,
            )
            if _included_fs.output_path_is_redirected(entry_path, entry_stat):
                raise OSError(
                    f"Refusing redirected entry in Included Files tree: {entry_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                _included_fs.verify_mount_boundary_path(
                    entry_path,
                    entry_stat,
                    root_stat.st_dev,
                    root_mount_id,
                    expect_directory=True,
                )
                kind = "directory"
                ctime_ns = None
                content_sha256 = None
                pending.append(
                    (
                        relative_path,
                        _IncludedTreePathBinding(
                            path=entry_path,
                            identity=(entry_stat.st_dev, entry_stat.st_ino),
                        ),
                    )
                )
            elif stat.S_ISREG(entry_stat.st_mode):
                kind = "file"
                ctime_ns = entry_stat.st_ctime_ns
                verify_included_tree_path_binding(directory_binding)
                if include_content:
                    content_sha256 = digest_included_regular_file(
                        entry_path,
                        entry_stat,
                        expected_device=root_stat.st_dev,
                        expected_mount_id=root_mount_id,
                    )
                else:
                    _included_fs.verify_mount_boundary_path(
                        entry_path,
                        entry_stat,
                        root_stat.st_dev,
                        root_mount_id,
                        expect_directory=False,
                    )
                    content_sha256 = None
            else:
                raise OSError(
                    f"Refusing non-regular entry in Included Files tree: {entry_path}"
                )
            entries.append(
                _IncludedTreeEntry(
                    relative_path=relative_path,
                    kind=kind,
                    fingerprint=_included_metadata.included_path_fingerprint(entry_stat),
                    ctime_ns=ctime_ns,
                    content_sha256=content_sha256,
                )
            )
            verify_included_tree_path_binding(directory_binding)
        verify_included_tree_path_binding(directory_binding)

    verify_fallback_directory_ancestors(root_parent_identities)
    current_root_stat = os.lstat(root_path)
    if (
        _included_fs.output_path_is_redirected(root_path, current_root_stat)
        or not stat.S_ISDIR(current_root_stat.st_mode)
        or _included_metadata.included_path_fingerprint(current_root_stat) != root_fingerprint
    ):
        raise OSError(f"Included Files root changed while inspecting: {root_path}")
    return _IncludedTreeSnapshot(
        root_fingerprint=root_fingerprint,
        entries=tuple(
            sorted(
                entries,
                key=lambda entry: (entry.relative_path, entry.kind),
            )
        ),
    )

def _capture_included_tree(
    root_path: str,
    *,
    expected_parent_identity: _PathIdentity | None = None,
    include_content: bool = True,
) -> _IncludedTreeSnapshot:
    if _included_fs.descriptor_paths_supported():
        return capture_included_tree_descriptor(
            root_path,
            expected_parent_identity,
            include_content=include_content,
        )
    return capture_included_tree_fallback(
        root_path,
        expected_parent_identity,
        include_content=include_content,
    )

def _verify_included_tree_snapshot(
    root_path: str,
    expected: _IncludedTreeSnapshot,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    if (
        capture_included_tree(
            root_path,
            expected_parent_identity=expected_parent_identity,
        )
        != expected
    ):
        raise OSError(f"Included Files tree changed during conversion: {root_path}")

def _verify_included_tree_snapshot_metadata(
    root_path: str,
    expected: _IncludedTreeSnapshot,
    *,
    expected_parent_identity: _PathIdentity | None = None,
) -> None:
    current = capture_included_tree(
        root_path,
        expected_parent_identity=expected_parent_identity,
        include_content=False,
    )
    if current != _included_metadata.included_tree_without_content(expected):
        raise OSError(
            f"Included Files tree metadata changed during conversion: {root_path}"
        )

def _capture_included_tree_from_generation_receipts(
    staged_root_path: str,
    *,
    expected_parent_identity: _PathIdentity,
    transaction_id: str,
    generation_identity: _PathIdentity,
    stage_container_identity: _PathIdentity,
    receipts: tuple[_IncludedGenerationContentReceipt, ...],
    published: bool = False,
) -> _IncludedTreeSnapshot:
    if not receipts:
        raise OSError("Included Files generation receipt set is empty")
    project_path = os.path.dirname(os.path.dirname(staged_root_path))
    public_root_path = os.path.join(
        project_path,
        _included_constants.INCLUDED_FILES_ROOT_NAME,
    )
    receipts_by_path = _included_metadata.included_generation_receipts_by_path(
        transaction_id=transaction_id,
        generation_identity=generation_identity,
        stage_container_identity=stage_container_identity,
        staged_root_path=staged_root_path,
        public_root_path=public_root_path,
        receipts=receipts,
    )
    root_path = public_root_path if published else staged_root_path
    metadata = capture_included_tree(
        root_path,
        expected_parent_identity=expected_parent_identity,
        include_content=False,
    )
    if metadata.identity != generation_identity:
        raise OSError("Included Files generation receipt root changed")
    file_entries = {
        entry.relative_path: entry
        for entry in metadata.entries
        if entry.kind == "file"
    }
    if file_entries.keys() != receipts_by_path.keys():
        raise OSError("Included Files generation receipt inventory changed")

    entries: list[_IncludedTreeEntry] = []
    for entry in metadata.entries:
        if entry.kind != "file":
            entries.append(entry)
            continue
        receipt = receipts_by_path[entry.relative_path]
        expected_output_path = (
            receipt.public_output_path
            if published
            else receipt.staged_output_path
        )
        actual_output_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    root_path,
                    *entry.relative_path.split("/"),
                )
            )
        )
        if (
            actual_output_path != expected_output_path
            or entry.fingerprint != receipt.output.output_fingerprint
            or entry.ctime_ns != receipt.output.output_ctime_ns
        ):
            raise OSError(
                "Included Files generation receipt output identity changed: "
                + entry.relative_path
            )
        entries.append(
            replace(
                entry,
                content_sha256=receipt.output.sha256,
            )
        )
    return _IncludedTreeSnapshot(
        root_fingerprint=metadata.root_fingerprint,
        entries=tuple(entries),
    )

def _verify_included_generation_source_receipt(
    receipt: _IncludedNoOpSourceReceipt,
    *,
    validate_content: bool,
) -> None:
    binding = receipt.binding
    source_path = binding.filesystem_path
    project_root = binding.directory_identities[0][0]
    with _included_fs.open_validation_stream(
        source_path,
        deny_writes=validate_content,
    ) as source_file:
        expected_stat = os.fstat(source_file.fileno())

        def capture_binding() -> _IncludedSourceBinding:
            lexical_stat = os.lstat(source_path)
            path_stat = os.stat(source_path)
            handle_stat = os.fstat(source_file.fileno())
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or not stat.S_ISREG(handle_stat.st_mode)
                or not os.path.samestat(path_stat, handle_stat)
                or _included_metadata.included_path_handle_binding(path_stat)
                != _included_metadata.included_path_handle_binding(handle_stat)
                or _included_metadata.included_handle_state(handle_stat)
                != _included_metadata.included_handle_state(expected_stat)
            ):
                raise OSError(
                    "GameMaker Included File source receipt handle changed: "
                    + receipt.logical_path
                )
            canonical_path, directory_identities = (
                capture_included_source_directory_identities(
                    project_root,
                    source_path,
                )
            )
            verify_fallback_directory_ancestors(directory_identities)
            return _IncludedSourceBinding(
                filesystem_path=os.path.normcase(
                    os.path.abspath(source_path)
                ),
                canonical_path=canonical_path,
                directory_identities=directory_identities,
                lexical_state=_included_metadata.included_handle_state(lexical_stat),
                path_state=_included_metadata.included_handle_state(path_stat),
                handle_state=_included_metadata.included_handle_state(handle_stat),
            )

        before_binding = capture_binding()
        if before_binding != binding:
            raise OSError(
                "GameMaker Included File source receipt binding changed: "
                + receipt.logical_path
            )
        if validate_content:
            byte_count, sha256 = digest_open_included_file(source_file)
            if (
                byte_count != receipt.byte_count
                or sha256 != receipt.sha256
            ):
                raise OSError(
                    "GameMaker Included File source receipt content changed: "
                    + receipt.logical_path
                )
        after_binding = capture_binding()
        if after_binding != binding:
            raise OSError(
                "GameMaker Included File source receipt binding changed: "
                + receipt.logical_path
            )

def _before_included_registry_file_read(
    _project_fd: int,
    _registry_directory_name: str,
) -> None:
    """Narrow test seam after pinning the registry directory for capture."""

def _capture_included_registry(
    project_path: str,
    *,
    expected_project_identity: _PathIdentity | None = None,
    allowed_file_identities: frozenset[_PathIdentity] | None = None,
) -> _IncludedRegistrySnapshot:
    registry_path = _included_paths.included_registry_path(project_path)
    registry_directory = os.path.dirname(registry_path)
    if _included_fs.descriptor_paths_supported():
        project_fd, registry_directory_name = _included_fs.open_pinned_parent(
            registry_directory
        )
        try:
            project_stat = os.fstat(project_fd)
            project_mount_id = _included_fs.linux_mount_id_from_fd(project_fd)
            _included_metadata.verify_included_directory_fd(
                project_fd,
                expected_project_identity,
                project_path,
            )
            registry_directory_stat = _included_metadata.included_entry_stat_at(
                project_fd,
                registry_directory_name,
            )
            if registry_directory_stat is None:
                if expected_project_identity is not None:
                    verify_included_project_identity(
                        project_path,
                        expected_project_identity,
                    )
                return _IncludedRegistrySnapshot(
                    directory_identity=None,
                    file_identity=None,
                    file_mode=None,
                    content=None,
                )
            if not stat.S_ISDIR(registry_directory_stat.st_mode):
                raise OSError(
                    "Refusing redirected or non-directory Included File "
                    f"registry path: {registry_directory}"
                )
            directory_identity = (
                registry_directory_stat.st_dev,
                registry_directory_stat.st_ino,
            )
            registry_directory_fd = os.open(
                registry_directory_name,
                _included_posix.DIRECTORY_OPEN_FLAGS,
                dir_fd=project_fd,
            )
            try:
                if (
                    _included_metadata.directory_identity_from_fd(registry_directory_fd)
                    != directory_identity
                ):
                    raise OSError(
                        "Included File registry directory changed while opening"
                    )
                _included_fs.verify_mount_boundary(
                    registry_directory,
                    os.fstat(registry_directory_fd),
                    project_stat.st_dev,
                    project_mount_id,
                    registry_directory_fd,
                )
                before_included_registry_file_read(
                    project_fd,
                    registry_directory_name,
                )
                file_state = included_regular_file_state_at(
                    registry_directory_fd,
                    os.path.basename(registry_path),
                    registry_path,
                    allowed_identities=allowed_file_identities,
                )
                verify_included_directory_entry_identity_at(
                    project_fd,
                    registry_directory_name,
                    directory_identity,
                    registry_directory,
                )
            finally:
                os.close(registry_directory_fd)
            if expected_project_identity is not None:
                verify_included_project_identity(
                    project_path,
                    expected_project_identity,
                )
            if file_state is None:
                return _IncludedRegistrySnapshot(
                    directory_identity=directory_identity,
                    file_identity=None,
                    file_mode=None,
                    content=None,
                )
            file_identity, file_mode, content = file_state
            return _IncludedRegistrySnapshot(
                directory_identity=directory_identity,
                file_identity=file_identity,
                file_mode=file_mode,
                content=content,
            )
        finally:
            os.close(project_fd)

    project_ancestors = capture_fallback_directory_ancestors(project_path)
    if (
        expected_project_identity is not None
        and project_ancestors[-1][1] != expected_project_identity
    ):
        raise OSError(f"Included Files directory changed: {project_path}")
    try:
        registry_directory_stat = os.lstat(registry_directory)
    except FileNotFoundError:
        verify_fallback_directory_ancestors(project_ancestors)
        return _IncludedRegistrySnapshot(
            directory_identity=None,
            file_identity=None,
            file_mode=None,
            content=None,
        )
    if (
        _included_fs.output_path_is_redirected(
            registry_directory,
            registry_directory_stat,
        )
        or not stat.S_ISDIR(registry_directory_stat.st_mode)
    ):
        raise OSError(
            "Refusing redirected or non-directory Included File registry path: "
            f"{registry_directory}"
        )
    directory_identity = (
        registry_directory_stat.st_dev,
        registry_directory_stat.st_ino,
    )
    project_mount_id = _included_fs.directory_mount_id(
        project_path,
        project_ancestors[-1][1],
    )
    _included_fs.verify_mount_boundary_path(
        registry_directory,
        registry_directory_stat,
        project_ancestors[-1][1][0],
        project_mount_id,
        expect_directory=True,
    )
    registry_ancestors = (
        *project_ancestors,
        (registry_directory, directory_identity),
    )
    verify_fallback_directory_ancestors(registry_ancestors)
    file_state = included_regular_file_state(
        registry_path,
        expected_parent_identity=directory_identity,
        expected_fallback_ancestors=registry_ancestors,
        allowed_identities=allowed_file_identities,
    )
    verify_fallback_directory_ancestors(registry_ancestors)
    if file_state is None:
        return _IncludedRegistrySnapshot(
            directory_identity=directory_identity,
            file_identity=None,
            file_mode=None,
            content=None,
        )
    file_identity, file_mode, content = file_state
    return _IncludedRegistrySnapshot(
        directory_identity=directory_identity,
        file_identity=file_identity,
        file_mode=file_mode,
        content=content,
    )

def _verify_included_registry_snapshot(
    project_path: str,
    expected: _IncludedRegistrySnapshot,
    *,
    expected_project_identity: _PathIdentity | None = None,
) -> None:
    if (
        capture_included_registry(
            project_path,
            expected_project_identity=expected_project_identity,
            allowed_file_identities=(
                frozenset()
                if expected.file_identity is None
                else frozenset({expected.file_identity})
            ),
        )
        != expected
    ):
        raise OSError("Included File registry changed during conversion")

def _verify_included_project_identity(
    project_path: str,
    expected_identity: _PathIdentity,
) -> None:
    if included_directory_identity(project_path) != expected_identity:
        raise OSError(f"Godot project root changed during Included Files conversion: {project_path}")

def _verify_included_directory_entry_identity_at(
    parent_fd: int,
    name: str,
    expected_identity: _PathIdentity,
    display_path: str,
) -> None:
    current_stat = _included_metadata.included_entry_stat_at(parent_fd, name)
    if (
        current_stat is None
        or not stat.S_ISDIR(current_stat.st_mode)
        or (current_stat.st_dev, current_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Included Files directory changed: {display_path}")


read_included_validation_chunk = _read_included_validation_chunk
digest_open_included_file = _digest_open_included_file
digest_included_regular_file = _digest_included_regular_file
capture_fallback_directory_ancestors = _capture_fallback_directory_ancestors
verify_fallback_directory_ancestors = _verify_fallback_directory_ancestors
capture_included_source_directory_identities = _capture_included_source_directory_identities
included_directory_identity = _included_directory_identity
included_regular_file_state_at = _included_regular_file_state_at
before_included_fallback_regular_file_open = _before_included_fallback_regular_file_open
included_regular_file_state = _included_regular_file_state
digest_included_regular_file_at = _digest_included_regular_file_at
verify_included_regular_file_mount_boundary_at = _verify_included_regular_file_mount_boundary_at
verify_included_tree_descriptor_binding = _verify_included_tree_descriptor_binding
verify_included_tree_path_binding = _verify_included_tree_path_binding
capture_included_tree_from_fd = _capture_included_tree_from_fd
capture_included_tree_descriptor = _capture_included_tree_descriptor
after_included_fallback_tree_directory_scan = _after_included_fallback_tree_directory_scan
capture_included_tree_fallback = _capture_included_tree_fallback
capture_included_tree = _capture_included_tree
verify_included_tree_snapshot = _verify_included_tree_snapshot
verify_included_tree_snapshot_metadata = _verify_included_tree_snapshot_metadata
capture_included_tree_from_generation_receipts = _capture_included_tree_from_generation_receipts
verify_included_generation_source_receipt = _verify_included_generation_source_receipt
before_included_registry_file_read = _before_included_registry_file_read
capture_included_registry = _capture_included_registry
verify_included_registry_snapshot = _verify_included_registry_snapshot
verify_included_project_identity = _verify_included_project_identity
verify_included_directory_entry_identity_at = _verify_included_directory_entry_identity_at
