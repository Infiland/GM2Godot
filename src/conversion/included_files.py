from __future__ import annotations

import os
import posixpath
import stat
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import BinaryIO

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath


@dataclass(frozen=True)
class _IncludedFileSource:
    filesystem_path: str
    relative_path: str
    owner_source_path: str


class IncludedFilesConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)

    def _process_file(
        self,
        gm_file_path: str,
        godot_file_path: str,
        rel_path: str,
        owner_source_path: str = "datafiles",
    ) -> tuple[str, bool] | None:
        if not self.conversion_running():
            return None

        opened_source = self._open_confined_source_file(
            gm_file_path,
            owner_source_path=owner_source_path,
            resource=rel_path,
        )
        if opened_source is None:
            return rel_path, False

        source_file, source_stat = opened_source
        with source_file:
            with open(godot_file_path, "wb") as target_file:
                shutil.copyfileobj(source_file, target_file)

        # Preserve the source file's main copy2 metadata without consulting the
        # source path again after it has been validated and opened. The held
        # descriptor remains safe if a path component is swapped concurrently.
        os.chmod(godot_file_path, stat.S_IMODE(source_stat.st_mode))
        os.utime(
            godot_file_path,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )
        return rel_path, True

    def _open_confined_source_file(
        self,
        filesystem_path: str,
        *,
        owner_source_path: str,
        resource: str,
    ) -> tuple[BinaryIO, os.stat_result] | None:
        """Open a contained regular file and pin it against late path swaps."""
        resolved = self._resolve_discovered_project_source(
            filesystem_path,
            owner_source_path=owner_source_path,
            resource=resource,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            return None

        try:
            source_file = open(resolved.filesystem_path, "rb")
        except OSError:
            return None

        try:
            opened_stat = os.fstat(source_file.fileno())
            revalidated = self._resolve_discovered_project_source(
                resolved.filesystem_path,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="included_file",
                field="discovered datafiles file",
            )
            if revalidated is None:
                source_file.close()
                return None
            current_stat = os.stat(revalidated.filesystem_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
            ):
                source_file.close()
                self._report_source_path_rejection(
                    filesystem_path,
                    ProjectSourcePathError(
                        "Discovered GameMaker source file changed after validation"
                    ),
                    owner_source_path=owner_source_path,
                    resource=resource,
                    resource_type="included_file",
                    field="discovered datafiles file",
                )
                return None
        except OSError:
            source_file.close()
            return None
        return source_file, opened_stat

    def _list_confined_directory(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> tuple[str, ...] | None:
        """List a contained directory without following a late path swap."""
        revalidated = self._resolve_discovered_project_source(
            directory.filesystem_path,
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )
        if revalidated is None:
            return None

        # On POSIX, list through a validated directory descriptor. If the path
        # is exchanged after validation, the descriptor remains bound to the
        # original contained directory. Other platforms get a before/after
        # identity check around their path-based directory listing.
        if os.listdir in os.supports_fd and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            try:
                directory_fd = os.open(revalidated.filesystem_path, flags)
            except OSError:
                return None
            try:
                opened_stat = os.fstat(directory_fd)
                current = self._resolve_discovered_project_source(
                    revalidated.filesystem_path,
                    owner_source_path=directory.source_path,
                    resource=posixpath.basename(directory.source_path),
                    resource_type="included_file",
                    field="discovered datafiles directory",
                )
                if current is None:
                    return None
                current_stat = os.stat(current.filesystem_path)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or not os.path.samestat(opened_stat, current_stat)
                ):
                    self._report_directory_swap(directory)
                    return None
                return tuple(sorted(os.listdir(directory_fd)))
            except OSError:
                return None
            finally:
                os.close(directory_fd)

        try:
            before_stat = os.stat(revalidated.filesystem_path)
            entries = tuple(sorted(os.listdir(revalidated.filesystem_path)))
            current = self._resolve_discovered_project_source(
                revalidated.filesystem_path,
                owner_source_path=directory.source_path,
                resource=posixpath.basename(directory.source_path),
                resource_type="included_file",
                field="discovered datafiles directory",
            )
            if current is None:
                return None
            after_stat = os.stat(current.filesystem_path)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(before_stat.st_mode)
            or not os.path.samestat(before_stat, after_stat)
        ):
            self._report_directory_swap(directory)
            return None
        return entries

    def _report_directory_swap(
        self,
        directory: ResolvedProjectSourcePath,
    ) -> None:
        self._report_source_path_rejection(
            directory.filesystem_path,
            ProjectSourcePathError(
                "Discovered GameMaker source directory changed after validation"
            ),
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )

    def _collect_included_files(
        self,
        datafiles: ResolvedProjectSourcePath,
    ) -> list[_IncludedFileSource]:
        included_files: list[_IncludedFileSource] = []
        pending_directories = [datafiles]
        visited_directories: set[str] = set()

        while pending_directories:
            directory = pending_directories.pop()
            canonical_directory = os.path.normcase(
                os.path.realpath(directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            entry_names = self._list_confined_directory(directory)
            if entry_names is None:
                continue
            for entry_name in entry_names:
                entry = self._resolve_discovered_project_source(
                    os.path.join(directory.filesystem_path, entry_name),
                    owner_source_path=directory.source_path,
                    resource=entry_name,
                    resource_type="included_file",
                    field="discovered datafiles entry",
                )
                if entry is None:
                    continue
                if os.path.isdir(entry.filesystem_path):
                    # Match os.walk's historical default: contained directory
                    # symlinks are not traversed, while the datafiles root itself
                    # may still be a contained symlink.
                    if not os.path.islink(entry.filesystem_path):
                        pending_directories.append(entry)
                    continue
                if entry_name.endswith(".yy") or not os.path.isfile(
                    entry.filesystem_path
                ):
                    continue
                relative_path = posixpath.relpath(
                    entry.source_path,
                    datafiles.source_path,
                )
                included_files.append(
                    _IncludedFileSource(
                        filesystem_path=entry.filesystem_path,
                        relative_path=relative_path,
                        owner_source_path=directory.source_path,
                    )
                )
        return sorted(included_files, key=lambda item: item.relative_path)

    def convert_included_files(self) -> None:
        godot_included_path = os.path.join(self.godot_project_path, "included_files")

        datafiles = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource="datafiles",
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles is None or not os.path.isdir(datafiles.filesystem_path):
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        os.makedirs(godot_included_path, exist_ok=True)

        all_files = self._collect_included_files(datafiles)

        if not all_files:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        # Pre-create all directories
        for source in all_files:
            godot_dir = os.path.dirname(
                os.path.join(
                    godot_included_path,
                    *source.relative_path.split("/"),
                )
            )
            os.makedirs(godot_dir, exist_ok=True)

        total_files = len(all_files)
        processed_files = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[tuple[str, bool] | None], str] = {}
            for source in all_files:
                godot_file_path = os.path.join(
                    godot_included_path,
                    *source.relative_path.split("/"),
                )
                future = executor.submit(
                    self._process_file,
                    source.filesystem_path,
                    godot_file_path,
                    source.relative_path,
                    source.owner_source_path,
                )
                futures_map[future] = source.relative_path

            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_IncludedFiles_Stopped"))
                    return

                processed_files += 1
                rel_path, copied = result
                if copied:
                    if self.compact_logging:
                        self._safe_log_progress(os.path.basename(rel_path), processed_files, total_files)
                    else:
                        self._safe_log(get_localized("Console_Convertor_IncludedFiles_Copied").format(path=rel_path))
                self._safe_progress(int((processed_files / total_files) * 100))

    def convert_all(self) -> None:
        self.convert_included_files()
