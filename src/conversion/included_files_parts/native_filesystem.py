from __future__ import annotations

import os
from typing import BinaryIO

from src.conversion.included_files_parts.filesystem_operations import (
    IncludedCleanupParentBinding,
    IncludedFilesystemOperations,
)
from src.conversion.included_files_parts.models import PathIdentity
from src.conversion.included_files_parts import native_posix as _included_posix
from src.conversion.included_files_parts import native_windows as _included_windows
from src.conversion.included_files_parts import stat_metadata as _included_metadata


class NativeIncludedFilesystemOperations:
    """Compose live native owners without selecting or caching a platform."""

    def descriptor_paths_supported(self) -> bool:
        return _included_posix.included_descriptor_paths_supported()

    def native_noreplace_available(self) -> bool:
        return _included_posix.included_native_noreplace_available()

    def open_pinned_directory(self, path: str) -> int:
        return _included_posix.open_pinned_included_directory(path)

    def open_pinned_parent(self, path: str) -> tuple[int, str]:
        return _included_posix.open_pinned_included_parent(path)

    def rename_entry_at(
        self, source_parent_fd: int, source_name: str, destination_parent_fd: int, destination_name: str
    ) -> None:
        return _included_posix.rename_included_transaction_entry_at(
            source_parent_fd, source_name, destination_parent_fd, destination_name
        )

    def linux_mount_id_from_fd(self, file_descriptor: int) -> int | None:
        return _included_posix.included_linux_mount_id_from_fd(file_descriptor)

    def directory_mount_id(self, path: str, expected_identity: PathIdentity) -> int | None:
        return _included_posix.included_directory_mount_id(path, expected_identity)

    def verify_mount_boundary(
        self,
        path: str,
        entry_stat: os.stat_result,
        expected_device: int,
        expected_mount_id: int | None,
        opened_descriptor: int,
    ) -> int | None:
        return _included_posix.verify_included_mount_boundary(
            path, entry_stat, expected_device, expected_mount_id, opened_descriptor
        )

    def verify_mount_boundary_path(
        self,
        path: str,
        entry_stat: os.stat_result,
        expected_device: int,
        expected_mount_id: int | None,
        *,
        expect_directory: bool,
    ) -> int | None:
        return _included_posix.verify_included_mount_boundary_path(
            path, entry_stat, expected_device, expected_mount_id, expect_directory=expect_directory
        )

    def open_tree_directory_at(self, parent_fd: int, name: str) -> int:
        return _included_posix.open_included_tree_directory_at(parent_fd, name)

    def sync_directory(self, path: str, expected_identity: PathIdentity) -> None:
        return _included_posix.sync_included_directory(path, expected_identity)

    def confined_output_supported(self) -> bool:
        return _included_posix.confined_included_output_supported()

    def open_or_create_output_directory(self, parent_fd: int, component: str, flags: int) -> int:
        return _included_posix.open_or_create_included_output_directory(parent_fd, component, flags)

    def apply_output_metadata(self, file_descriptor: int, source_stat: os.stat_result) -> None:
        return _included_posix.apply_included_output_metadata(file_descriptor, source_stat)

    def windows_file_locking(self, file_descriptor: int, mode: int) -> None:
        return _included_windows.windows_included_file_locking(file_descriptor, mode)

    def open_windows_cleanup_parent(self, path: str, expected_identity: PathIdentity) -> IncludedCleanupParentBinding:
        return _included_windows.WindowsIncludedCleanupParentBinding.open(path, expected_identity)

    def verify_windows_cleanup_parent(
        self, binding: IncludedCleanupParentBinding, parent_path: str, expected_identity: PathIdentity
    ) -> None:
        return _included_windows.verify_windows_included_cleanup_parent_binding(binding, parent_path, expected_identity)

    def rename_entry(self, source: str, destination: str) -> None:
        return _included_windows.rename_included_transaction_entry(source, destination)

    def output_path_is_redirected(self, path: str, path_stat: os.stat_result) -> bool:
        return _included_metadata.included_output_path_is_redirected(path, path_stat)

    def open_validation_stream(self, path: str, *, deny_writes: bool, no_follow: bool = False) -> BinaryIO:
        return _included_windows.open_included_file_validation_stream(
            path, deny_writes=deny_writes, no_follow=no_follow
        )


filesystem: IncludedFilesystemOperations = NativeIncludedFilesystemOperations()
