from __future__ import annotations

import json
import os
import platform
import re
import shutil
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Literal, TypedDict, cast

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_resource_stem,
)
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    resolve_project_source_path,
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
                 max_workers: int | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_fonts_path = os.path.join(self.godot_project_path, 'fonts')
        self._font_output_paths: dict[str, str] = {}

    def find_font_files(self) -> list[str]:
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        if manifest.yyp_path is not None:
            font_files: list[str] = []
            seen_paths: set[str] = set()
            for resource in manifest.resources:
                if resource.kind.casefold() != "fonts":
                    continue
                source_path = resource.path.casefold()
                if not source_path.endswith(".yy") or source_path.endswith(".old.yy"):
                    continue
                try:
                    resolved = resolve_project_source_path(
                        self.gm_project_path,
                        resource.path,
                    )
                except ProjectSourcePathError:
                    continue
                if not os.path.isfile(resolved.filesystem_path):
                    continue
                canonical_path = os.path.normcase(
                    os.path.realpath(resolved.filesystem_path)
                )
                if canonical_path in seen_paths:
                    continue
                seen_paths.add(canonical_path)
                font_files.append(resolved.filesystem_path)
            return font_files

        font_folder = os.path.join(self.gm_project_path, 'fonts')
        font_files: list[str] = []
        for root, dirs, files in os.walk(font_folder):
            dirs.sort()
            font_files.extend(
                os.path.join(root, file)
                for file in sorted(files)
                if file.lower().endswith('.yy') and not file.lower().endswith('.old.yy')
            )
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

        font_data = self._parse_font_yy(yy_path)
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
            ttf_path = resolve_bundled_font_source(yy_path, font_data['TTFName'])
            bundled_output_file = bundled_font_output_filename(font_data['TTFName'])
            if ttf_path is not None and bundled_output_file is not None:
                font_source_path = ttf_path
                output_filename = bundled_output_file
                preserve_metadata = True
                bundled_font = True
            else:
                self._safe_log(get_localized("Console_Convertor_Fonts_TTFMissing").format(
                    name=font_name, ttf_name=font_data['TTFName']))

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
            yy_path,
            font_name,
            output_filename,
        )
        output_file = os.path.basename(output_path)

        if font_source_path is not None:
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

        gm_fonts_path = os.path.join(self.gm_project_path, 'fonts')

        if not os.path.exists(gm_fonts_path):
            self.log_callback(get_localized("Console_Convertor_Fonts_Error_NotFound").format(gm_project_path=self.gm_project_path))
            return

        font_files = self.find_font_files()

        if not font_files:
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

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[str | Literal[False] | None], str] = {executor.submit(self._process_font, ff): ff for ff in font_files}
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Fonts_Stopped"))
                    return
                if result is not False:
                    processed_fonts += 1
                    if self.compact_logging:
                        self._safe_log_progress(result, processed_fonts, total_fonts)
                    self._safe_progress(int(processed_fonts / total_fonts * 100))
                else:
                    processed_fonts += 1
                    self._safe_progress(int(processed_fonts / total_fonts * 100))

        self.log_callback(get_localized("Console_Convertor_Fonts_Complete"))

    def convert_all(self) -> None:
        self.convert_fonts()
