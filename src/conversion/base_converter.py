from __future__ import annotations

import json
import os
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, cast

from src.localization import get_localized
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import generated_subfolder_path
from src.conversion.project_manifest import GameMakerProjectManifest
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    resolve_project_filesystem_source_path,
    resolve_project_sidecar_source_path,
    resolve_project_source_path,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


class BaseConverter(ABC):
    """Base class for all GM2Godot converters."""

    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        self.gm_project_path = os.fspath(gm_project_path)
        self.godot_project_path = os.fspath(godot_project_path)
        self.log_callback: LogCallback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running: ConversionRunning = conversion_running or (lambda: True)
        self.update_log_callback: LogCallback = update_log_callback or log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers or os.cpu_count() or 1
        self.diagnostics = diagnostics
        self._lock = threading.Lock()

    def _safe_log(self, message: str) -> None:
        """Thread-safe wrapper for log_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add_from_log_message(message)
            self.log_callback(message)

    def _safe_update_log(self, message: str) -> None:
        """Thread-safe wrapper for update_log_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add_from_log_message(message)
            self.update_log_callback(message)

    def _safe_progress(self, value: int | float) -> None:
        """Thread-safe wrapper for progress_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.progress_callback:
                self.progress_callback(value)

    def _resolve_project_source(
        self,
        source_path: str,
        *,
        owner_source_path: StrPath | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        field: str | None = None,
    ) -> ResolvedProjectSourcePath | None:
        """Resolve metadata-owned input and report a structured rejection."""
        try:
            if owner_source_path is None:
                return resolve_project_source_path(
                    self.gm_project_path,
                    source_path,
                )
            return resolve_project_sidecar_source_path(
                self.gm_project_path,
                owner_source_path,
                source_path,
            )
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                source_path,
                exc,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type=resource_type,
                field=field,
            )
            return None

    def _resolve_discovered_project_source(
        self,
        filesystem_path: StrPath,
        *,
        owner_source_path: StrPath | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        field: str | None = None,
    ) -> ResolvedProjectSourcePath | None:
        """Revalidate a disk-scan candidate before any source-side access."""
        try:
            return resolve_project_filesystem_source_path(
                self.gm_project_path,
                filesystem_path,
            )
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                os.fspath(filesystem_path),
                exc,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type=resource_type,
                field=field,
            )
            return None

    def _report_source_path_rejection(
        self,
        rejected_path: str,
        error: ProjectSourcePathError,
        *,
        owner_source_path: StrPath | None,
        resource: str | None,
        resource_type: str | None,
        field: str | None,
    ) -> None:
        owner_label = (
            os.fspath(owner_source_path)
            if owner_source_path is not None
            else "the selected GameMaker project"
        )
        field_label = f" field {field}" if field else ""
        message = (
            "Warning: Rejected GameMaker source path "
            f"{rejected_path!r} from {owner_label}{field_label}: {error}"
        )
        diagnostic_owner = self._diagnostic_source_path(owner_source_path)
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "warning",
                    "GM2GD-SOURCE-PATH-REJECTED",
                    message,
                    source_path=diagnostic_owner,
                    resource=resource,
                    resource_type=resource_type,
                    manifest_entry=field,
                    workaround=(
                        "Keep GameMaker resource and sidecar files inside the "
                        "selected project root and reference them with contained "
                        "project-relative paths."
                    ),
                )
            self.log_callback(message)

    def _record_project_manifest_source_path_diagnostics(
        self,
        manifest: GameMakerProjectManifest,
        *,
        resource_type: str | None = None,
        include_project_sources: bool = False,
    ) -> frozenset[str]:
        """Forward manifest-level source-path rejections to conversion output."""
        rejected_fields: set[str] = set()
        for diagnostic in manifest.diagnostics:
            if diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED":
                continue
            source = diagnostic.source
            field = (
                source.field_path
                if source is not None and source.field_path
                else None
            )
            # Dedicated converters already report their own discovered roots,
            # options, and YYP candidates. This bridge exists for raw resource
            # entries that manifest kind inference would otherwise discard.
            if field is None:
                continue
            is_resource_field = field.startswith("resources[")
            if not is_resource_field and not include_project_sources:
                continue
            if (
                is_resource_field
                and resource_type is not None
                and diagnostic.resource_kind is not None
                and not self._manifest_kind_matches_resource_type(
                    diagnostic.resource_kind,
                    resource_type,
                )
            ):
                continue
            rejected_fields.add(field)
            source_path = (
                self._diagnostic_source_path(source.path)
                if source is not None
                else None
            )
            if self.diagnostics is not None:
                if any(
                    existing.code == diagnostic.code
                    and existing.source_path == source_path
                    and existing.manifest_entry == field
                    for existing in self.diagnostics.diagnostics()
                ):
                    continue
                self.diagnostics.add(
                    diagnostic.severity,
                    diagnostic.code,
                    diagnostic.message,
                    source_path=source_path,
                    line=source.line if source is not None else None,
                    resource=diagnostic.resource,
                    resource_type=(
                        (
                            resource_type
                            if is_resource_field
                            and diagnostic.resource_kind is not None
                            else None
                        )
                        or diagnostic.resource_type
                        or "project"
                    ),
                    manifest_entry=field,
                    workaround=(
                        "Keep GameMaker resource and sidecar files inside the "
                        "selected project root and reference them with contained "
                        "project-relative paths."
                    ),
                )
            self.log_callback(diagnostic.message)
        return frozenset(rejected_fields)

    @staticmethod
    def _manifest_kind_matches_resource_type(
        resource_kind: str,
        resource_type: str,
    ) -> bool:
        expected_kind = {
            "animation_curve": "animcurves",
            "audio_group": "audiogroups",
            "font": "fonts",
            "included_file": "datafiles",
            "object": "objects",
            "particle_system": "particlesystems",
            "path": "paths",
            "room": "rooms",
            "script": "scripts",
            "sequence": "sequences",
            "shader": "shaders",
            "sound": "sounds",
            "sprite": "sprites",
            "tileset": "tilesets",
            "timeline": "timelines",
        }.get(resource_type, resource_type)
        return resource_kind.casefold() == expected_kind.casefold()

    def _diagnostic_source_path(
        self,
        owner_source_path: StrPath | None,
    ) -> str | None:
        if owner_source_path is None:
            return None
        owner_text = os.fspath(owner_source_path)
        try:
            resolved = (
                resolve_project_filesystem_source_path(
                    self.gm_project_path,
                    owner_text,
                )
                if os.path.isabs(owner_text)
                else resolve_project_source_path(
                    self.gm_project_path,
                    owner_text,
                )
            )
        except ProjectSourcePathError:
            return None
        return resolved.source_path

    def _log_progress(self, item_name: str, current: int, total: int) -> None:
        """Log compact progress. First item appends a line; subsequent items update it in place."""
        msg = get_localized("Console_Compact_Progress").format(
            name=item_name, current=current, total=total)
        if current == 1:
            self.log_callback(msg)
        else:
            self.update_log_callback(msg)

    def _safe_log_progress(self, item_name: str, current: int, total: int) -> None:
        """Thread-safe version of _log_progress."""
        with self._lock:
            self._log_progress(item_name, current, total)

    def _read_yy_file(self, yy_path: StrPath) -> JsonDict | None:
        """Read and parse a GameMaker .yy file, cleaning trailing commas."""
        try:
            resolved = resolve_project_filesystem_source_path(
                self.gm_project_path,
                yy_path,
            )
            with open(resolved.filesystem_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)
            return cast(JsonDict, data) if isinstance(data, dict) else None
        except (
            OSError,
            ProjectSourcePathError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

    def _get_subfolder_from_yy(self, yy_path: StrPath) -> str:
        """Extract the IDE subfolder path from a resource's .yy file.

        Reads parent.path (e.g. "folders/Objects/Game/Abilities.yy"),
        strips "folders/" prefix, ".yy" suffix, and the first path component
        (resource type), returning the remaining subfolder (e.g. "Game/Abilities").

        Returns "" for root-level resources or on any parse failure.
        """
        data = self._read_yy_file(yy_path)
        if data is None:
            return ""
        try:
            raw_parent = data.get('parent')
            if not isinstance(raw_parent, dict):
                return ""
            parent = cast(JsonDict, raw_parent)
            parent_path = parent.get('path')
            if not isinstance(parent_path, str):
                return ""
            if parent_path.startswith('folders/'):
                parent_path = parent_path[len('folders/'):]
            if parent_path.endswith('.yy'):
                parent_path = parent_path[:-len('.yy')]
            parts = parent_path.split('/')
            if len(parts) <= 1:
                return ""
            return generated_subfolder_path('/'.join(parts[1:]))
        except (KeyError, TypeError, AttributeError):
            return ""

    @abstractmethod
    def convert_all(self) -> Any:
        """Run the full conversion for this converter type."""
        pass
