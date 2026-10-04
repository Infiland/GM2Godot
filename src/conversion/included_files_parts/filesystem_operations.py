"""Finite Included Files filesystem operation and owned-binding contracts."""

from __future__ import annotations

import os
from typing import BinaryIO, Protocol

from src.conversion.included_files_parts.models import PathIdentity


class IncludedCleanupParentBinding(Protocol):
    """Owned Windows binding; supplied parent descriptors elsewhere stay borrowed."""

    @property
    def path(self) -> str: ...

    @property
    def identity(self) -> PathIdentity: ...

    def verify(self) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> IncludedCleanupParentBinding: ...

    def __exit__(
        self,
        _exception_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> bool | None: ...


class IncludedFilesystemOperations(Protocol):
    """Finite port; operations preserve their own original platform decision stage."""

    def descriptor_paths_supported(self) -> bool: ...

    def native_noreplace_available(self) -> bool: ...

    def open_pinned_directory(self, path: str) -> int: ...

    def open_pinned_parent(self, path: str) -> tuple[int, str]: ...

    def rename_entry_at(
        self,
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None: ...

    def linux_mount_id_from_fd(self, file_descriptor: int) -> int | None: ...

    def directory_mount_id(
        self,
        path: str,
        expected_identity: PathIdentity,
    ) -> int | None: ...

    def verify_mount_boundary(
        self,
        path: str,
        entry_stat: os.stat_result,
        expected_device: int,
        expected_mount_id: int | None,
        opened_descriptor: int,
    ) -> int | None: ...

    def verify_mount_boundary_path(
        self,
        path: str,
        entry_stat: os.stat_result,
        expected_device: int,
        expected_mount_id: int | None,
        *,
        expect_directory: bool,
    ) -> int | None: ...

    def open_tree_directory_at(self, parent_fd: int, name: str) -> int: ...

    def sync_directory(self, path: str, expected_identity: PathIdentity) -> None: ...

    def confined_output_supported(self) -> bool: ...

    def open_or_create_output_directory(
        self,
        parent_fd: int,
        component: str,
        flags: int,
    ) -> int: ...

    def apply_output_metadata(
        self,
        file_descriptor: int,
        source_stat: os.stat_result,
    ) -> None: ...

    def windows_file_locking(self, file_descriptor: int, mode: int) -> None: ...

    def open_windows_cleanup_parent(
        self,
        path: str,
        expected_identity: PathIdentity,
    ) -> IncludedCleanupParentBinding: ...

    def verify_windows_cleanup_parent(
        self,
        binding: IncludedCleanupParentBinding,
        parent_path: str,
        expected_identity: PathIdentity,
    ) -> None: ...

    def rename_entry(self, source: str, destination: str) -> None: ...

    def output_path_is_redirected(
        self,
        path: str,
        path_stat: os.stat_result,
    ) -> bool: ...

    def open_validation_stream(
        self,
        path: str,
        *,
        deny_writes: bool,
        no_follow: bool = False,
    ) -> BinaryIO: ...
