from __future__ import annotations

import json
import os
import platform
import re
import shutil
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_resource_stem,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath

FONT_EXTENSIONS = ('.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2')


class FontData(TypedDict):
    fontName: str
    name: str
    size: float
    bold: bool
    italic: bool
    AntiAlias: int
    includeTTF: bool
    TTFName: str


@dataclass(frozen=True)
class _DeclaredFontResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


@dataclass(frozen=True)
class _FontConversionPlan:
    requested_keys: tuple[str, ...]
    available_fonts: tuple[tuple[str, str], ...]
    skipped_keys: tuple[str, ...]


def bundled_font_output_filename(ttf_name: str) -> str | None:
    """Return the safe, deterministic filename used for an included font."""
    normalized = ttf_name.replace('\\', '/')
    if not normalized or normalized.startswith('/') or re.match(r'^[A-Za-z]:', normalized):
        return None
    parts = normalized.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return None
    stem, extension = os.path.splitext(parts[-1])
    if not stem or extension.lower() not in FONT_EXTENSIONS:
        return None
    return generated_resource_stem(stem) + extension.lower()


def resolve_bundled_font_source(yy_path: str, ttf_name: str) -> str | None:
    """Resolve an included font without allowing the resource to escape its folder."""
    output_filename = bundled_font_output_filename(ttf_name)
    if output_filename is None:
        return None

    normalized = ttf_name.replace('\\', '/')
    resource_dir = os.path.realpath(os.path.dirname(yy_path))
    source_path = os.path.realpath(os.path.join(resource_dir, *normalized.split('/')))
    try:
        if os.path.commonpath((resource_dir, source_path)) != resource_dir:
            return None
    except ValueError:
        return None
    return source_path if os.path.isfile(source_path) else None


def _get_system_font_dirs() -> list[str]:
    """Return a list of system font directories for the current OS."""
    system = platform.system()
    dirs: list[str] = []
    if system == 'Windows':
        windir = os.environ.get('WINDIR', r'C:\Windows')
        dirs.append(os.path.join(windir, 'Fonts'))
        local_app = os.environ.get('LOCALAPPDATA', '')
        if local_app:
            dirs.append(os.path.join(local_app, 'Microsoft', 'Windows', 'Fonts'))
    elif system == 'Darwin':
        dirs.extend([
            '/Library/Fonts',
            '/System/Library/Fonts',
            os.path.expanduser('~/Library/Fonts'),
        ])
    else:
        dirs.extend([
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.local/share/fonts'),
            os.path.expanduser('~/.fonts'),
        ])
    return [d for d in dirs if os.path.isdir(d)]


def _find_system_font(font_name: str) -> str | None:
    """Search system font directories for a font file matching the given name.

    Returns the path to the font file if found, None otherwise.
    """
    font_name_lower = font_name.lower().replace(' ', '')
    for font_dir in _get_system_font_dirs():
        for root, _, files in os.walk(font_dir):
            for filename in files:
                if not filename.lower().endswith(FONT_EXTENSIONS):
                    continue
                name_without_ext = os.path.splitext(filename)[0].lower().replace(' ', '')
                if name_without_ext == font_name_lower:
                    return os.path.join(root, filename)
                # Also match with common suffixes stripped (e.g. "Arial-Regular" -> "Arial")
                for suffix in ('-regular', '-normal', '_regular', '_normal'):
                    if name_without_ext.endswith(suffix):
                        base = name_without_ext[:-len(suffix)]
                        if base == font_name_lower:
                            return os.path.join(root, filename)
    return None


def resolve_system_font_source(font_name: str) -> str | None:
    """Return the system font file the converter would copy, if available."""
    return _find_system_font(font_name)


def _copy_font_file_atomically(
    source_path: str,
    destination_path: str,
    *,
    preserve_metadata: bool,
) -> None:
    """Stage a font beside its destination and publish only a complete copy."""
    destination_name = os.path.basename(destination_path)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination_name}.",
        suffix=".part",
        dir=os.path.dirname(destination_path),
    ) as staged_dir:
        staged_path = os.path.join(staged_dir, destination_name)

        if preserve_metadata:
            shutil.copy2(source_path, staged_path)
        else:
            shutil.copyfile(source_path, staged_path)

        os.replace(staged_path, destination_path)


class FontConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_fonts_path = os.path.join(self.godot_project_path, 'fonts')
        self._font_output_paths: dict[str, str] = {}

    def find_font_files(self) -> list[str]:
        """Return available font metadata selected by the project plan."""
        return [
            yy_path
            for _resource_key, yy_path in self._font_conversion_plan().available_fonts
        ]

    def _font_conversion_plan(self) -> _FontConversionPlan:
        """Plan logical font resources before filtering unavailable metadata."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="font",
        )
        if manifest.yyp_path is not None:
            return self._plan_manifest_fonts(manifest)

        font_files = self._find_disk_font_files()
        return _FontConversionPlan(
            requested_keys=tuple(font_files),
            available_fonts=tuple((font_file, font_file) for font_file in font_files),
            skipped_keys=(),
        )

    def _declared_font_resources(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[tuple[_DeclaredFontResource, ...], ...]:
        """Return ordered logical YYP fonts, including rejected declarations."""
        declared_by_name: dict[str, list[_DeclaredFontResource]] = {}
        seen_declarations: set[tuple[str, str | None]] = set()

        def add(resource: _DeclaredFontResource) -> None:
            declaration_key = (resource.name, resource.source_path)
            if not resource.name or declaration_key in seen_declarations:
                return
            seen_declarations.add(declaration_key)
            declared_by_name.setdefault(resource.name, []).append(resource)

        for resource in manifest.resources:
            if resource.kind.casefold() != "fonts":
                continue
            source_path = resource.path.casefold()
            if not source_path.endswith(".yy") or source_path.endswith(".old.yy"):
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredFontResource(
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
                or not self._manifest_diagnostic_is_font(diagnostic)
            ):
                continue
            add(
                _DeclaredFontResource(
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

        return tuple(tuple(resources) for resources in declared_by_name.values())

    @staticmethod
    def _manifest_diagnostic_is_font(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "fonts"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"font", "gmfont"}
        )

    def _plan_manifest_fonts(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _FontConversionPlan:
        """Resolve one available source for every logical base font."""
        requested_keys: list[str] = []
        available_fonts: list[tuple[str, str]] = []
        skipped_keys: list[str] = []
        seen_paths: set[str] = set()

        for declarations in self._declared_font_resources(manifest):
            font_name = declarations[0].name
            selected_path: str | None = None
            duplicate_source = False
            unavailable_reason = "all of its manifest source paths are unavailable"

            for resource in declarations:
                if resource.source_path is None:
                    unavailable_reason = "its manifest source path was rejected"
                    continue
                resolved = self._resolve_project_source(
                    resource.source_path,
                    owner_source_path=resource.owner_source_path,
                    resource=font_name,
                    resource_type="font",
                    field=resource.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = "its manifest source path is unavailable"
                    continue
                try:
                    validate_project_resource_source_path(resolved, "fonts")
                except ProjectSourcePathError as exc:
                    self._report_source_path_rejection(
                        resource.source_path,
                        exc,
                        owner_source_path=resource.owner_source_path,
                        resource=font_name,
                        resource_type="font",
                        field=resource.manifest_field,
                    )
                    unavailable_reason = "its manifest source path was rejected"
                    continue
                if not os.path.isfile(resolved.filesystem_path):
                    unavailable_reason = (
                        f"metadata is missing at {resolved.source_path!r}"
                    )
                    continue

                canonical_path = os.path.normcase(
                    os.path.realpath(resolved.filesystem_path)
                )
                if canonical_path in seen_paths:
                    # Preserve the historical behavior for duplicate exact YYP
                    # references: convert and account for the source only once.
                    duplicate_source = True
                    break
                seen_paths.add(canonical_path)
                selected_path = resolved.filesystem_path
                break

            if duplicate_source:
                continue

            requested_keys.append(font_name)
            if selected_path is None:
                skipped_keys.append(font_name)
                self._report_unavailable_declared_font(
                    declarations[0],
                    reason=unavailable_reason,
                )
            else:
                available_fonts.append((font_name, selected_path))

        return _FontConversionPlan(
            requested_keys=tuple(requested_keys),
            available_fonts=tuple(available_fonts),
            skipped_keys=tuple(skipped_keys),
        )

    def _report_unavailable_declared_font(
        self,
        resource: _DeclaredFontResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker font "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-FONT-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="font",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker font .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _find_disk_font_files(self) -> list[str]:
        """Discover fonts on disk when the project has no YYP manifest."""

        font_folder = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, 'fonts'),
            resource_type="font",
            field="fonts directory",
        )
        if font_folder is None or not os.path.isdir(font_folder.filesystem_path):
            return []

        font_files: list[str] = []
        pending_directories = [
            (font_folder.filesystem_path, font_folder.source_path)
        ]
        visited_directories: set[str] = set()
        while pending_directories:
            directory_path, directory_source_path = pending_directories.pop()
            canonical_directory = os.path.normcase(os.path.realpath(directory_path))
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            try:
                entries = sorted(
                    os.scandir(directory_path),
                    key=lambda entry: entry.name,
                )
            except OSError:
                continue

            child_directories: list[tuple[str, str]] = []
            for entry in entries:
                filename = entry.name
                lower_filename = filename.casefold()
                is_font_yy = (
                    lower_filename.endswith('.yy')
                    and not lower_filename.endswith('.old.yy')
                )
                try:
                    is_unlinked_directory = entry.is_dir(
                        follow_symlinks=False
                    )
                    is_symlink = entry.is_symlink()
                except OSError:
                    continue

                # Bundled font sidecars are validated against their owning .yy
                # when referenced. They are not discovery inputs by themselves.
                if (
                    is_symlink
                    and not is_font_yy
                    and lower_filename.endswith(FONT_EXTENSIONS)
                ):
                    continue
                if not is_unlinked_directory and not is_symlink and not is_font_yy:
                    continue

                resolved_entry = self._resolve_discovered_project_source(
                    entry.path,
                    owner_source_path=directory_source_path,
                    resource=(
                        os.path.splitext(filename)[0]
                        if is_font_yy
                        else filename
                    ),
                    resource_type="font",
                    field=(
                        "discovered font .yy"
                        if is_font_yy
                        else "discovered font directory"
                    ),
                )
                if resolved_entry is None:
                    continue

                # Resolve containment before following a possible directory
                # symlink to classify the canonical target.
                if os.path.isdir(resolved_entry.filesystem_path):
                    if is_font_yy:
                        continue
                    if not is_symlink:
                        child_directories.append(
                            (
                                resolved_entry.filesystem_path,
                                resolved_entry.source_path,
                            )
                        )
                    continue

                if not is_font_yy:
                    continue
                if os.path.isfile(resolved_entry.filesystem_path):
                    try:
                        validate_project_resource_source_path(
                            resolved_entry,
                            "fonts",
                        )
                    except ProjectSourcePathError as exc:
                        self._report_source_path_rejection(
                            entry.path,
                            exc,
                            owner_source_path=directory_source_path,
                            resource=os.path.splitext(filename)[0],
                            resource_type="font",
                            field="discovered font .yy",
                        )
                        continue
                    font_files.append(resolved_entry.filesystem_path)

            pending_directories.extend(reversed(child_directories))
        return font_files

    def _parse_font_yy(self, yy_path: str) -> FontData | None:
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))
            return {
                'fontName': str(data['fontName']),
                'name': str(data['name']),
                'size': float(data.get('size', 12.0)),
                'bold': bool(data.get('bold', False)),
                'italic': bool(data.get('italic', False)),
                'AntiAlias': int(data.get('AntiAlias', 0)),
                'includeTTF': bool(data.get('includeTTF', False)),
                'TTFName': str(data.get('TTFName', '')),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self._safe_log(get_localized("Console_Convertor_Fonts_ParseError").format(yy_path=yy_path))
            return None

    def _generate_system_font_tres(self, font_data: FontData) -> str:
        font_name = font_data['fontName']
        italic = "true" if font_data['italic'] else "false"
        weight = 700 if font_data['bold'] else 400
        antialiasing = 1 if font_data['AntiAlias'] else 0

        return (
            '[gd_resource type="SystemFont" format=3]\n'
            '\n'
            '[resource]\n'
            f'font_names = PackedStringArray("{font_name}")\n'
            f'font_italic = {italic}\n'
            f'font_weight = {weight}\n'
            f'antialiasing = {antialiasing}\n'
        )

    def _process_font(self, yy_path: str) -> str | Literal[False] | None:
        if not self.conversion_running():
            return None

        discovered_name = os.path.splitext(os.path.basename(yy_path))[0]
        resolved_yy = self._resolve_discovered_project_source(
            yy_path,
            owner_source_path=os.path.dirname(yy_path),
            resource=discovered_name,
            resource_type="font",
            field="font .yy",
        )
        if resolved_yy is None:
            return False
        try:
            validate_project_resource_source_path(resolved_yy, "fonts")
        except ProjectSourcePathError as exc:
            self._report_source_path_rejection(
                yy_path,
                exc,
                owner_source_path=os.path.dirname(yy_path),
                resource=discovered_name,
                resource_type="font",
                field="font .yy",
            )
            return False

        font_data = self._parse_font_yy(resolved_yy.filesystem_path)
        if font_data is None:
            return False

        font_name = font_data['name']
        system_font_name = font_data['fontName']
        font_source_path: str | None = None
        preserve_metadata = False
        output_filename: str | None = None
        bundled_font = False

        # 1. Try bundled TTF from GameMaker project
        if font_data['includeTTF'] and font_data['TTFName']:
            ttf_name = font_data['TTFName']
            resolved_ttf = self._resolve_project_source(
                ttf_name,
                owner_source_path=resolved_yy.source_path,
                resource=font_name,
                resource_type="font",
                field="TTFName",
            )
            bundled_output_file = bundled_font_output_filename(ttf_name)
            if resolved_ttf is not None and bundled_output_file is None:
                self._report_source_path_rejection(
                    ttf_name,
                    ProjectSourcePathError(
                        "Bundled font paths must use non-empty relative path "
                        "segments and a supported font extension: "
                        f"{ttf_name!r}"
                    ),
                    owner_source_path=resolved_yy.source_path,
                    resource=font_name,
                    resource_type="font",
                    field="TTFName",
                )
            if (
                resolved_ttf is not None
                and bundled_output_file is not None
                and os.path.isfile(resolved_ttf.filesystem_path)
            ):
                font_source_path = os.path.realpath(resolved_ttf.filesystem_path)
                output_filename = bundled_output_file
                preserve_metadata = True
                bundled_font = True
            else:
                self._safe_log(get_localized("Console_Convertor_Fonts_TTFMissing").format(
                    name=font_name, ttf_name=ttf_name))

        # 2. Try finding the font on the system
        if font_source_path is None:
            system_path = resolve_system_font_source(system_font_name)
            if system_path:
                font_source_path = system_path
                output_filename = (
                    generated_resource_stem(font_name)
                    + os.path.splitext(system_path)[1].lower()
                )

        # 3. Fall back to SystemFont .tres reference
        if output_filename is None:
            output_filename = generated_resource_stem(font_name) + '.tres'

        output_path = self._font_output_destination(
            resolved_yy.filesystem_path,
            font_name,
            output_filename,
        )
        output_file = os.path.basename(output_path)

        if font_source_path is not None:
            if bundled_font:
                refreshed_ttf = self._resolve_project_source(
                    font_data['TTFName'],
                    owner_source_path=resolved_yy.source_path,
                    resource=font_name,
                    resource_type="font",
                    field="TTFName",
                )
                if refreshed_ttf is None or not os.path.isfile(
                    refreshed_ttf.filesystem_path
                ):
                    self._safe_log(
                        get_localized(
                            "Console_Convertor_Fonts_TTFMissing"
                        ).format(
                            name=font_name,
                            ttf_name=font_data['TTFName'],
                        )
                    )
                    return False
                font_source_path = os.path.realpath(
                    refreshed_ttf.filesystem_path
                )
            _copy_font_file_atomically(
                font_source_path,
                output_path,
                preserve_metadata=preserve_metadata,
            )
            if not self.compact_logging:
                message_key = (
                    "Console_Convertor_Fonts_CopiedTTF"
                    if bundled_font
                    else "Console_Convertor_Fonts_Converted"
                )
                self._safe_log(
                    get_localized(message_key).format(
                        name=font_name,
                        output_file=output_file,
                    )
                )
        else:
            tres_content = self._generate_system_font_tres(font_data)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(tres_content)
            self._safe_log(get_localized("Console_Convertor_Fonts_SystemFontFallback").format(
                name=font_name, font_name=system_font_name))

        if not self.compact_logging:
            size = font_data['size']
            self._safe_log(get_localized("Console_Convertor_Fonts_SizeNote").format(
                name=font_name, size=size))

        return font_name

    def _process_requested_font(
        self,
        resource_key: str,
        yy_path: str,
    ) -> str | Literal[False] | None:
        """Process one requested font while preserving cancellation semantics."""
        if not self.conversion_running():
            return None
        self._resource_started(resource_key)
        return self._process_font(yy_path)

    def _font_output_destination(
        self,
        yy_path: str,
        font_name: str,
        output_filename: str,
    ) -> str:
        # Imported lazily because the registry imports this module to plan font
        # paths before any converter writes output.
        from src.conversion.asset_output_paths import resource_filesystem_path

        resource_name = os.path.splitext(os.path.basename(yy_path))[0]
        resource_path = (
            self._font_output_paths.get(resource_name)
            or self._font_output_paths.get(font_name)
        )
        if resource_path is None:
            output_stem, output_extension = os.path.splitext(output_filename)
            resource_path = generated_flat_resource_path(
                "fonts",
                self._get_subfolder_from_yy(yy_path),
                output_stem,
                output_extension,
            )
        output_path = resource_filesystem_path(
            self.godot_project_path,
            resource_path,
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        return output_path

    def convert_fonts(self) -> None:
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_fonts_path, exist_ok=True)

        plan = self._font_conversion_plan()
        font_files = plan.available_fonts

        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for resource_key in plan.skipped_keys:
            self._resource_skipped(resource_key)

        if not font_files:
            if plan.requested_keys:
                self.log_callback(get_localized("Console_Convertor_Fonts_Complete"))
            else:
                self.log_callback(get_localized("Console_Convertor_Fonts_Error_NotFound").format(gm_project_path=self.gm_project_path))
            return

        # Imported lazily to avoid the fonts -> asset registry -> fonts import
        # cycle. The registry is the single authority for collision suffixes.
        from src.conversion.asset_output_paths import build_asset_output_paths

        self._font_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        ).get("fonts", {})

        total_fonts = len(font_files)
        processed_fonts = 0
        cancelled = False
        completed_font_keys: set[str] = set()
        failed_font_keys: set[str] = set()
        first_error: Exception | None = None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[
                Future[str | Literal[False] | None],
                str,
            ] = {
                executor.submit(
                    self._process_requested_font,
                    resource_key,
                    font_file,
                ): resource_key
                for resource_key, font_file in font_files
            }
            for future in as_completed(futures_map):
                resource_key = futures_map[future]
                try:
                    result = future.result()
                except Exception as error:
                    failed_font_keys.add(resource_key)
                    if first_error is None:
                        first_error = error
                    continue
                if result is None:
                    cancelled = True
                    continue
                processed_fonts += 1
                if result is not False:
                    completed_font_keys.add(resource_key)
                    if self.compact_logging:
                        self._safe_log_progress(result, processed_fonts, total_fonts)
                else:
                    failed_font_keys.add(resource_key)
                self._safe_progress(int(processed_fonts / total_fonts * 100))

        for resource_key in sorted(completed_font_keys):
            self._resource_completed(resource_key)
        for resource_key in sorted(failed_font_keys):
            self._resource_failed(resource_key)

        if first_error is not None:
            raise first_error
        if cancelled:
            self.log_callback(get_localized("Console_Convertor_Fonts_Stopped"))
            return

        self.log_callback(get_localized("Console_Convertor_Fonts_Complete"))

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_fonts()
