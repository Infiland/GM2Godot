from __future__ import annotations

import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath
from src.localization import get_localized


@dataclass(frozen=True)
class _NoteAsset:
    filesystem_path: str
    source_path: str
    owner_source_path: str
    name: str
    subfolder: str


@dataclass(frozen=True)
class _NoteCopyResult:
    name: str
    copied: bool


class NoteConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)

    def _process_note(
        self,
        src_file: str,
        dst_file: str,
        note_name: str,
        owner_source_path: str,
    ) -> _NoteCopyResult | None:
        if not self.conversion_running():
            return None

        # The source may have changed after discovery while waiting for a worker.
        # Revalidate it at the final source boundary before copying any bytes.
        resolved_source = self._resolve_discovered_project_source(
            src_file,
            owner_source_path=owner_source_path,
            resource=note_name,
            resource_type="note",
            field="note text file (pre-copy)",
        )
        if resolved_source is None or not os.path.isfile(
            resolved_source.filesystem_path
        ):
            return _NoteCopyResult(name=note_name, copied=False)

        try:
            shutil.copy2(resolved_source.filesystem_path, dst_file)
        except OSError:
            return _NoteCopyResult(name=note_name, copied=False)
        return _NoteCopyResult(name=note_name, copied=True)

    def _discover_notes(
        self,
        notes_root: ResolvedProjectSourcePath,
    ) -> list[_NoteAsset]:
        note_assets: list[_NoteAsset] = []
        pending_directories = [notes_root]
        visited_directories: set[str] = set()
        seen_note_files: set[str] = set()

        while pending_directories:
            directory = pending_directories.pop()
            resolved_directory = self._resolve_discovered_project_source(
                directory.filesystem_path,
                owner_source_path=directory.source_path,
                resource_type="note",
                field="discovered note directory",
            )
            if resolved_directory is None or not os.path.isdir(
                resolved_directory.filesystem_path
            ):
                continue

            canonical_directory = os.path.normcase(
                os.path.realpath(resolved_directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            try:
                with os.scandir(resolved_directory.filesystem_path) as entries:
                    directory_entries = sorted(entries, key=lambda entry: entry.name)
            except OSError:
                continue

            resolved_entries: dict[str, ResolvedProjectSourcePath | None] = {}
            child_directories: list[ResolvedProjectSourcePath] = []
            text_entries: list[tuple[str, ResolvedProjectSourcePath]] = []
            for entry in directory_entries:
                lower_name = entry.name.casefold()
                try:
                    is_symlink = entry.is_symlink()
                except OSError:
                    continue
                if lower_name.endswith(".txt"):
                    field = "note text file"
                elif lower_name.endswith(".yy"):
                    field = "note metadata .yy"
                else:
                    field = "discovered note entry"
                resource_name = os.path.splitext(entry.name)[0]
                resolved_entry = self._resolve_discovered_project_source(
                    entry.path,
                    owner_source_path=resolved_directory.source_path,
                    resource=resource_name,
                    resource_type="note",
                    field=field,
                )
                resolved_entries[entry.name] = resolved_entry
                if resolved_entry is None:
                    continue
                if os.path.isdir(resolved_entry.filesystem_path):
                    if not is_symlink:
                        child_directories.append(resolved_entry)
                    continue
                if lower_name.endswith(".txt") and os.path.isfile(
                    resolved_entry.filesystem_path
                ):
                    text_entries.append((entry.name, resolved_entry))

            for filename, resolved_note in text_entries:
                canonical_note = os.path.normcase(
                    os.path.realpath(resolved_note.filesystem_path)
                )
                if canonical_note in seen_note_files:
                    continue
                seen_note_files.add(canonical_note)

                note_name = os.path.splitext(filename)[0]
                metadata_name = note_name + ".yy"
                resolved_metadata = resolved_entries.get(metadata_name)
                subfolder = ""
                if resolved_metadata is not None and os.path.isfile(
                    resolved_metadata.filesystem_path
                ):
                    # _get_subfolder_from_yy performs one more containment check
                    # in _read_yy_file immediately before reading the metadata.
                    subfolder = self._get_subfolder_from_yy(
                        resolved_metadata.filesystem_path
                    )
                note_assets.append(
                    _NoteAsset(
                        filesystem_path=resolved_note.filesystem_path,
                        source_path=resolved_note.source_path,
                        owner_source_path=resolved_directory.source_path,
                        name=note_name,
                        subfolder=subfolder,
                    )
                )

            pending_directories.extend(reversed(child_directories))

        return note_assets

    def convert_notes(self) -> None:
        godot_notes_path = os.path.join(self.godot_project_path, "notes")

        gm_notes_path = self._resolve_project_source(
            "notes",
            resource_type="note",
            field="notes directory",
        )
        if gm_notes_path is None or not os.path.isdir(
            gm_notes_path.filesystem_path
        ):
            self.log_callback(get_localized("Console_Convertor_Notes_Error_NotFound"))
            return

        os.makedirs(godot_notes_path, exist_ok=True)

        note_assets = self._discover_notes(gm_notes_path)
        if not note_assets:
            return

        # Pre-create all directories
        for asset in note_assets:
            if asset.subfolder:
                note_dir = os.path.join(
                    godot_notes_path,
                    asset.subfolder,
                    asset.name,
                )
            else:
                note_dir = os.path.join(godot_notes_path, asset.name)
            os.makedirs(note_dir, exist_ok=True)

        total_notes = len(note_assets)
        processed_notes = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[_NoteCopyResult | None], str] = {}
            for asset in note_assets:
                if asset.subfolder:
                    dst_file = os.path.join(
                        godot_notes_path,
                        asset.subfolder,
                        asset.name,
                        os.path.basename(asset.filesystem_path),
                    )
                else:
                    dst_file = os.path.join(
                        godot_notes_path,
                        asset.name,
                        os.path.basename(asset.filesystem_path),
                    )
                future = executor.submit(
                    self._process_note,
                    asset.filesystem_path,
                    dst_file,
                    asset.name,
                    asset.owner_source_path,
                )
                futures_map[future] = asset.name

            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Notes_Stopped"))
                    return

                processed_notes += 1
                if result.copied:
                    if self.compact_logging:
                        self._safe_log_progress(
                            result.name,
                            processed_notes,
                            total_notes,
                        )
                    else:
                        self._safe_log(
                            get_localized("Console_Convertor_Notes_Copied").format(
                                note_name=result.name
                            )
                        )
                self._safe_progress(int((processed_notes / total_notes) * 100))

    def convert_all(self) -> None:
        self.convert_notes()
