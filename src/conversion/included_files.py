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
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
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


@dataclass(frozen=True)
class _DeclaredIncludedFile:
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str | None


@dataclass(frozen=True)
class _IncludedFileConversionPlan:
    requested_keys: tuple[str, ...]
    available_files: tuple[_IncludedFileSource, ...]
    skipped_keys: tuple[str, ...]


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
        self._resource_requested(rel_path)
        self._resource_started(rel_path)

        try:
            opened_source = self._open_confined_source_file(
                gm_file_path,
                owner_source_path=owner_source_path,
                resource=rel_path,
            )
            if opened_source is None:
                self._resource_failed(rel_path)
                return rel_path, False

            source_file, source_stat = opened_source
            with source_file:
                with open(godot_file_path, "wb") as target_file:
                    shutil.copyfileobj(source_file, target_file)

            # Preserve metadata without consulting the source path again after
            # its validated descriptor has been pinned.
            os.chmod(godot_file_path, stat.S_IMODE(source_stat.st_mode))
            os.utime(
                godot_file_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )
        except Exception:
            self._resource_failed(rel_path)
            raise
        self._resource_completed(rel_path)
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

    def _included_file_conversion_plan(self) -> _IncludedFileConversionPlan:
        """Plan logical included files before filtering unavailable sources."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="included_file",
        )
        malformed = any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        )
        manifest_declares_included_files = (
            "IncludedFiles" in manifest.raw_data
            or "includedFiles" in manifest.raw_data
            or any(
                resource.kind.casefold() == "datafiles"
                or resource.resource_type.casefold() == "gmincludedfile"
                for resource in manifest.resources
            )
            or any(
                self._manifest_diagnostic_is_included_file(diagnostic)
                for diagnostic in manifest.diagnostics
            )
        )
        if (
            manifest.yyp_path is not None
            and not malformed
            and manifest_declares_included_files
        ):
            declared_plan = self._plan_manifest_included_files(manifest)
            # Included Files are directory-backed rather than ordinary Asset
            # Browser resources: current GameMaker automatically reflects
            # contained files added under datafiles even before their YYP
            # metadata is refreshed. Preserve those files while still
            # accounting for stale manifest declarations.
            requested_keys = list(declared_plan.requested_keys)
            available_files = list(declared_plan.available_files)
            seen_keys = set(requested_keys)
            for source in self._discovered_included_files():
                if source.relative_path in seen_keys:
                    continue
                seen_keys.add(source.relative_path)
                requested_keys.append(source.relative_path)
                available_files.append(source)
            return _IncludedFileConversionPlan(
                requested_keys=tuple(requested_keys),
                available_files=tuple(available_files),
                skipped_keys=declared_plan.skipped_keys,
            )

        available_files = self._discovered_included_files()
        return _IncludedFileConversionPlan(
            requested_keys=tuple(
                source.relative_path for source in available_files
            ),
            available_files=available_files,
            skipped_keys=(),
        )

    def _discovered_included_files(self) -> tuple[_IncludedFileSource, ...]:
        """Return every contained regular payload under datafiles."""

        datafiles = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource="datafiles",
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles is None or not os.path.isdir(datafiles.filesystem_path):
            return ()
        return tuple(self._collect_included_files(datafiles))

    def _plan_manifest_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _IncludedFileConversionPlan:
        requested_keys: list[str] = []
        available_files: list[_IncludedFileSource] = []
        skipped_keys: list[str] = []
        seen_keys: set[str] = set()

        for declaration in self._declared_included_files(manifest):
            resolved: ResolvedProjectSourcePath | None = None
            unavailable_reason = "its manifest source path was rejected"
            if declaration.source_path is not None:
                resolved = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=declaration.name,
                    resource_type="included_file",
                    field=declaration.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = "its manifest source path was rejected"

            relative_path = self._declared_relative_path(declaration, resolved)
            if relative_path in seen_keys:
                continue
            seen_keys.add(relative_path)
            requested_keys.append(relative_path)

            if resolved is not None:
                source_root, separator, source_relative = (
                    resolved.source_path.partition("/")
                )
                if (
                    not separator
                    or source_root.casefold() != "datafiles"
                    or not source_relative
                ):
                    self._report_source_path_rejection(
                        declaration.source_path or resolved.source_path,
                        ProjectSourcePathError(
                            "Resolved included-file source must remain under "
                            "the GameMaker 'datafiles' directory"
                        ),
                        owner_source_path=declaration.owner_source_path,
                        resource=declaration.name,
                        resource_type="included_file",
                        field=declaration.manifest_field,
                    )
                    resolved = None
                    unavailable_reason = (
                        "its manifest source path was rejected outside the "
                        "datafiles resource family"
                    )
                elif not os.path.isfile(resolved.filesystem_path):
                    unavailable_reason = (
                        f"the source file is missing at {resolved.source_path!r}"
                    )
                    resolved = None

            if resolved is None:
                skipped_keys.append(relative_path)
                self._report_unavailable_declared_included_file(
                    declaration,
                    reason=unavailable_reason,
                )
                continue

            available_files.append(
                _IncludedFileSource(
                    filesystem_path=resolved.filesystem_path,
                    relative_path=relative_path,
                    owner_source_path=declaration.owner_source_path,
                )
            )

        return _IncludedFileConversionPlan(
            requested_keys=tuple(requested_keys),
            available_files=tuple(available_files),
            skipped_keys=tuple(skipped_keys),
        )

    def _declared_included_files(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[_DeclaredIncludedFile, ...]:
        """Return unique included-file declarations from a valid YYP."""
        declared: dict[str, _DeclaredIncludedFile] = {}

        def add(resource: _DeclaredIncludedFile, identity: str) -> None:
            normalized_identity = self._normalized_declaration_path(identity)
            if not normalized_identity:
                normalized_identity = resource.name
            if not normalized_identity:
                return
            declared.setdefault(normalized_identity, resource)

        for included_file in manifest.included_files:
            source = included_file.source
            field = source.field_path if source is not None else None
            raw_field = next(
                (
                    key
                    for key in ("path", "filePath", "filename")
                    if key in included_file.raw_data
                ),
                "path",
            )
            manifest_field = f"{field}.{raw_field}" if field else raw_field
            source_path = included_file.path
            if (
                raw_field == "filePath"
                and included_file.name
                and posixpath.basename(source_path) != included_file.name
            ):
                # Current GameMaker YYP files store the containing directory in
                # ``filePath`` and the payload filename separately in ``name``.
                source_path = posixpath.join(source_path, included_file.name)
            add(
                _DeclaredIncludedFile(
                    name=included_file.name or included_file.path,
                    source_path=source_path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=manifest_field,
                ),
                source_path or included_file.name,
            )

        for resource in manifest.resources:
            if (
                resource.kind.casefold() != "datafiles"
                and resource.resource_type.casefold() != "gmincludedfile"
            ):
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredIncludedFile(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=field,
                ),
                resource.path,
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_included_file(diagnostic)
            ):
                continue
            source = diagnostic.source
            field = source.field_path if source is not None else None
            add(
                _DeclaredIncludedFile(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        source.path
                        if source is not None
                        else manifest.yyp_path or ""
                    ),
                    manifest_field=field,
                ),
                f"rejected:{diagnostic.resource}",
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_included_file(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "datafiles"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold()
            in {"included_file", "includedfile", "gmincludedfile"}
        )

    @staticmethod
    def _normalized_declaration_path(path: str) -> str:
        normalized = posixpath.normpath(path.replace("\\", "/").strip())
        return "" if normalized in {"", "."} else normalized

    def _declared_relative_path(
        self,
        declaration: _DeclaredIncludedFile,
        resolved: ResolvedProjectSourcePath | None,
    ) -> str:
        if resolved is not None:
            source_root, separator, source_relative = (
                resolved.source_path.partition("/")
            )
            if (
                separator
                and source_root.casefold() == "datafiles"
                and source_relative
            ):
                return source_relative

        fallback = self._normalized_declaration_path(
            declaration.source_path or declaration.name
        )
        source_root, separator, source_relative = fallback.partition("/")
        if (
            separator
            and source_root.casefold() == "datafiles"
            and source_relative
        ):
            return source_relative
        return fallback or declaration.name

    def _report_unavailable_declared_included_file(
        self,
        declaration: _DeclaredIncludedFile,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker included file "
            f"{declaration.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    declaration.owner_source_path
                ),
                resource=declaration.name,
                resource_type="included_file",
                manifest_entry=declaration.manifest_field,
                workaround=(
                    "Restore the declared included file under the GameMaker "
                    "datafiles directory or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def convert_included_files(self) -> None:
        godot_included_path = os.path.join(self.godot_project_path, "included_files")
        plan = self._included_file_conversion_plan()
        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for resource_key in plan.skipped_keys:
            self._resource_skipped(resource_key)

        if not plan.requested_keys:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        all_files = list(plan.available_files)
        if not all_files:
            return

        os.makedirs(godot_included_path, exist_ok=True)

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
        self._reset_resource_outcomes()
        self.convert_included_files()
