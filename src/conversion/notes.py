from __future__ import annotations

import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

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
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath
from src.localization import get_localized


@dataclass(frozen=True)
class _NoteAsset:
    filesystem_path: str
    source_path: str
    owner_source_path: str
    outcome_key: str
    name: str
    subfolder: str


@dataclass(frozen=True)
class _NoteCopyResult:
    name: str
    copied: bool


@dataclass(frozen=True)
class _DeclaredNoteResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


@dataclass(frozen=True)
class _NoteConversionPlan:
    requested_keys: tuple[str, ...]
    available_assets: tuple[_NoteAsset, ...]
    skipped_keys: tuple[str, ...]


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
        outcome_key: str | None = None,
    ) -> _NoteCopyResult | None:
        if not self.conversion_running():
            return None
        resource_key = outcome_key or src_file
        # Keep the worker helper safe for direct callers while the normal
        # conversion path pre-registers every discovered note before submit.
        self._resource_requested(resource_key)
        self._resource_started(resource_key)

        try:
            # The source may have changed after discovery while waiting for a
            # worker. Revalidate it at the final source boundary before copying.
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
                self._resource_failed(resource_key)
                return _NoteCopyResult(name=note_name, copied=False)
            shutil.copy2(resolved_source.filesystem_path, dst_file)
        except OSError:
            self._resource_failed(resource_key)
            return _NoteCopyResult(name=note_name, copied=False)
        except Exception:
            self._resource_failed(resource_key)
            raise
        self._resource_completed(resource_key)
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
                        outcome_key=resolved_note.filesystem_path,
                        name=note_name,
                        subfolder=subfolder,
                    )
                )

            pending_directories.extend(reversed(child_directories))

        return note_assets

    def _indexed_note_plan(self) -> _NoteConversionPlan | None:
        """Return the authoritative note plan selected by a valid YYP."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="note",
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            return None
        return self._plan_manifest_notes(manifest)

    def _declared_note_resources(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[tuple[_DeclaredNoteResource, ...], ...]:
        """Return every logical YYP note, including rejected declarations."""
        declared_by_name: dict[str, list[_DeclaredNoteResource]] = {}
        seen_declarations: set[tuple[str, str | None]] = set()

        def add(resource: _DeclaredNoteResource) -> None:
            declaration_key = (resource.name, resource.source_path)
            if not resource.name or declaration_key in seen_declarations:
                return
            seen_declarations.add(declaration_key)
            declared_by_name.setdefault(resource.name, []).append(resource)

        for resource in manifest.resources:
            is_note = (
                resource.kind.casefold() == "notes"
                or resource.resource_type.casefold() == "gmnotes"
            )
            if not is_note:
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredNoteResource(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path,
                    manifest_field=manifest_field,
                )
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_note(diagnostic)
            ):
                continue
            add(
                _DeclaredNoteResource(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        diagnostic.source.path
                        if diagnostic.source is not None
                        else manifest.yyp_path
                    ),
                    manifest_field=(
                        diagnostic.source.field_path
                        if diagnostic.source is not None
                        else None
                    ),
                )
            )

        return tuple(
            tuple(resources)
            for resources in declared_by_name.values()
        )

    @staticmethod
    def _manifest_diagnostic_is_note(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "notes"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"note", "gmnotes"}
        )

    def _plan_manifest_notes(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _NoteConversionPlan:
        """Resolve one metadata/text pair for each declared base note."""
        requested_keys: list[str] = []
        available_assets: list[_NoteAsset] = []
        skipped_keys: list[str] = []

        for declarations in self._declared_note_resources(manifest):
            note_name = declarations[0].name
            selected_asset: _NoteAsset | None = None
            unavailable_reason = (
                "all of its manifest source paths are unavailable"
            )

            for declaration in declarations:
                if declaration.source_path is None:
                    unavailable_reason = "its manifest source path was rejected"
                    continue
                resolved_metadata = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=note_name,
                    resource_type="note",
                    field=declaration.manifest_field,
                )
                if resolved_metadata is None:
                    unavailable_reason = (
                        "its manifest source path is unavailable"
                    )
                    continue
                try:
                    validate_project_resource_source_path(
                        resolved_metadata,
                        "notes",
                    )
                except ProjectSourcePathError as exc:
                    self._report_source_path_rejection(
                        declaration.source_path,
                        exc,
                        owner_source_path=declaration.owner_source_path,
                        resource=note_name,
                        resource_type="note",
                        field=declaration.manifest_field,
                    )
                    unavailable_reason = (
                        "its manifest source path is outside the notes "
                        "resource family or is not .yy metadata"
                    )
                    continue
                if not os.path.isfile(resolved_metadata.filesystem_path):
                    unavailable_reason = (
                        f"metadata is missing at "
                        f"{resolved_metadata.source_path!r}"
                    )
                    continue

                text_path = os.path.splitext(
                    resolved_metadata.filesystem_path
                )[0] + ".txt"
                resolved_text = self._resolve_discovered_project_source(
                    text_path,
                    owner_source_path=resolved_metadata.source_path,
                    resource=note_name,
                    resource_type="note",
                    field="derived note text file",
                )
                if resolved_text is None or not os.path.isfile(
                    resolved_text.filesystem_path
                ):
                    unavailable_reason = (
                        "its companion .txt file is missing or unavailable"
                    )
                    continue

                selected_asset = _NoteAsset(
                    filesystem_path=resolved_text.filesystem_path,
                    source_path=resolved_text.source_path,
                    owner_source_path=resolved_metadata.source_path,
                    outcome_key=note_name,
                    name=note_name,
                    subfolder=self._get_subfolder_from_yy(
                        resolved_metadata.filesystem_path
                    ),
                )
                break

            requested_keys.append(note_name)
            if selected_asset is None:
                skipped_keys.append(note_name)
                self._report_unavailable_declared_note(
                    declarations[0],
                    reason=unavailable_reason,
                )
            else:
                available_assets.append(selected_asset)

        return _NoteConversionPlan(
            requested_keys=tuple(requested_keys),
            available_assets=tuple(available_assets),
            skipped_keys=tuple(skipped_keys),
        )

    def _report_unavailable_declared_note(
        self,
        resource: _DeclaredNoteResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker note "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-NOTE-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="note",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker note .yy metadata and its "
                    "companion .txt file inside the project root, or remove "
                    "the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def convert_notes(self) -> None:
        godot_notes_path = os.path.join(self.godot_project_path, "notes")
        indexed_plan = self._indexed_note_plan()
        if indexed_plan is None:
            gm_notes_path = self._resolve_project_source(
                "notes",
                resource_type="note",
                field="notes directory",
            )
            if gm_notes_path is None or not os.path.isdir(
                gm_notes_path.filesystem_path
            ):
                self.log_callback(
                    get_localized("Console_Convertor_Notes_Error_NotFound")
                )
                return
            note_assets = self._discover_notes(gm_notes_path)
            for asset in note_assets:
                self._resource_requested(asset.outcome_key)
        else:
            for resource_key in indexed_plan.requested_keys:
                self._resource_requested(resource_key)
            for resource_key in indexed_plan.skipped_keys:
                self._resource_skipped(resource_key)
            note_assets = list(indexed_plan.available_assets)

        if not note_assets:
            return

        os.makedirs(godot_notes_path, exist_ok=True)

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
                    asset.outcome_key,
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
        self._reset_resource_outcomes()
        self.convert_notes()
