from __future__ import annotations

import os
import re
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from src.conversion.asset_output_paths import build_asset_output_paths, resource_filesystem_path
from src.conversion.base_converter import BaseConverter
from src.conversion.generated_paths import generated_resource_stem, generated_subfolder_path
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    resolve_project_source_path,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath
from src.localization import get_localized


@dataclass(frozen=True)
class _ShaderAsset:
    name: str
    subfolder: str
    vertex_path: str | None = None
    fragment_path: str | None = None

    @property
    def source_label(self) -> str:
        paths = [
            path
            for path in (self.vertex_path, self.fragment_path)
            if path is not None
        ]
        return ", ".join(os.path.basename(path) for path in paths) or self.name


@dataclass
class _ShaderAssetBuilder:
    name: str
    subfolder: str
    source_directory: str
    vertex_path: str | None = None
    fragment_path: str | None = None

    def build(self) -> _ShaderAsset:
        return _ShaderAsset(
            name=self.name,
            subfolder=self.subfolder,
            vertex_path=self.vertex_path,
            fragment_path=self.fragment_path,
        )


_FUNCTION_START_RE = re.compile(
    r"^\s*[A-Za-z_]\w*(?:\s*\[[^\]]+\])?\s+[A-Za-z_]\w*\s*\(",
)
_DECLARATION_RE = re.compile(
    r"^\s*(uniform|varying|const|in|out)\b.*?\b([A-Za-z_]\w*)\s*"
    r"(?:\[[^\]]*\])?\s*;\s*$",
)


class ShaderConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path,
                         log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_shaders_path = os.path.join(self.godot_project_path, 'shaders')
        self._shader_output_paths: dict[str, str] = {}

    def convert_shader(self, input_file: str, output_file: str) -> None:
        """Convert one legacy stage and publish it as a complete shader resource."""
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        stage = "vertex" if input_file.lower().endswith(".vsh") else "fragment"
        translated = self._translate_shader_source(content, stage)
        self._atomic_write_text(
            output_file,
            self._merge_shader_sources((translated,)),
        )

    @staticmethod
    def _translate_shader_source(content: str, stage: str) -> str:
        content = re.sub(
            r"(?m)^\s*precision\s+(?:lowp|mediump|highp)\s+\w+\s*;\s*$",
            "",
            content,
        )
        content = re.sub(
            r"(?m)^\s*shader_type\s+\w+\s*;\s*$",
            "",
            content,
        )
        content = re.sub(
            r"(?m)^\s*uniform\s+sampler2D\s+gm_BaseTexture\s*;\s*$",
            "",
            content,
        )

        content = re.sub(r'\battribute\b', 'in', content)
        content = re.sub(r'gl_FragColor', 'COLOR', content)
        content = re.sub(r'texture2D', 'texture', content)
        content = re.sub(r'gl_Position', 'VERTEX', content)

        if stage == "vertex":
            content = re.sub(r'void main\(\)', 'void vertex()', content)
        else:
            content = re.sub(r'void main\(\)', 'void fragment()', content)

        content = re.sub(r'gm_BaseTexture', 'TEXTURE', content)
        content = re.sub(r'gm_Matrices\[MATRIX_WORLD_VIEW_PROJECTION\]',
                         'PROJECTION_MATRIX * MODELVIEW_MATRIX', content)

        if 'u_fTime' in content:
            content = content.replace('u_fTime', 'TIME')

        return content.strip()

    @classmethod
    def _merge_shader_sources(cls, sources: tuple[str, ...]) -> str:
        preambles: list[str] = []
        bodies: list[str] = []
        seen_declarations: set[tuple[str, str]] = set()
        for source in sources:
            preamble, body = cls._split_shader_source(source)
            filtered_preamble: list[str] = []
            for line in preamble.splitlines():
                declaration = _DECLARATION_RE.match(line)
                if declaration is not None:
                    key = (declaration.group(1), declaration.group(2))
                    if key in seen_declarations:
                        continue
                    seen_declarations.add(key)
                filtered_preamble.append(line)
            rendered_preamble = "\n".join(filtered_preamble).strip()
            if rendered_preamble:
                preambles.append(rendered_preamble)
            rendered_body = body.strip()
            if rendered_body:
                bodies.append(rendered_body)

        sections = ["shader_type canvas_item;", *preambles, *bodies]
        return "\n\n".join(sections).rstrip() + "\n"

    @staticmethod
    def _split_shader_source(source: str) -> tuple[str, str]:
        lines = source.splitlines()
        for index, line in enumerate(lines):
            if _FUNCTION_START_RE.match(line):
                return ("\n".join(lines[:index]), "\n".join(lines[index:]))
        return (source, "")

    @staticmethod
    def _atomic_write_text(output_file: str, content: str) -> None:
        output_dir = os.path.dirname(output_file) or os.curdir
        os.makedirs(output_dir, exist_ok=True)
        file_descriptor, staged_path = tempfile.mkstemp(
            dir=output_dir,
            prefix=f".{os.path.basename(output_file)}.",
            suffix=".tmp",
        )
        staged_pending = True
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as staged_file:
                file_descriptor = -1
                staged_file.write(content)
                staged_file.flush()
                os.fsync(staged_file.fileno())
            os.replace(staged_path, output_file)
            staged_pending = False
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if staged_pending:
                try:
                    os.unlink(staged_path)
                except FileNotFoundError:
                    pass

    def _render_shader_asset(self, asset: _ShaderAsset) -> str:
        translated_sources: list[str] = []
        for stage, source_path in (
            ("vertex", asset.vertex_path),
            ("fragment", asset.fragment_path),
        ):
            if source_path is None:
                continue
            with open(source_path, "r", encoding="utf-8") as source_file:
                translated_sources.append(
                    self._translate_shader_source(source_file.read(), stage)
                )
        return self._merge_shader_sources(tuple(translated_sources))

    def _process_shader(
        self,
        asset: _ShaderAsset,
    ) -> tuple[str, str] | None:
        if not self.conversion_running():
            return None
        resource_path = self._shader_output_paths.get(asset.name, "")
        if resource_path:
            output_path = resource_filesystem_path(self.godot_project_path, resource_path)
            output_name = os.path.basename(output_path)
        else:
            output_name = generated_resource_stem(asset.name) + '.gdshader'
            safe_subfolder = generated_subfolder_path(asset.subfolder)
            output_dir = (
                os.path.join(self.godot_shaders_path, *safe_subfolder.split("/"))
                if safe_subfolder
                else self.godot_shaders_path
            )
            output_path = os.path.join(output_dir, output_name)
        shader_source = self._render_shader_asset(asset)
        self._atomic_write_text(output_path, shader_source)
        return (asset.source_label, output_name)

    def _indexed_shader_assets(self) -> tuple[_ShaderAsset, ...] | None:
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        if manifest.yyp_path is None:
            return None
        if not manifest.raw_data:
            self._safe_log(
                "Warning: Could not parse GameMaker project .yyp; skipping unowned shader files."
            )
            return ()

        assets: list[_ShaderAsset] = []
        seen_names: set[str] = set()
        for resource in manifest.resources:
            if resource.kind.casefold() != "shaders" or resource.name in seen_names:
                continue
            try:
                resolved = resolve_project_source_path(
                    self.gm_project_path,
                    resource.path,
                )
            except ProjectSourcePathError as exc:
                self._safe_log(
                    f"Warning: Skipping GameMaker shader {resource.name}: {exc}"
                )
                continue
            yy_path = resolved.filesystem_path
            if not os.path.isfile(yy_path):
                self._safe_log(
                    f"Warning: Skipping missing GameMaker shader {resource.name}: {yy_path}"
                )
                continue
            base_path = os.path.splitext(yy_path)[0]
            vertex_path = base_path + ".vsh"
            fragment_path = base_path + ".fsh"
            asset = _ShaderAsset(
                name=resource.name,
                subfolder=self._get_subfolder_from_yy(yy_path),
                vertex_path=vertex_path if os.path.isfile(vertex_path) else None,
                fragment_path=fragment_path if os.path.isfile(fragment_path) else None,
            )
            if asset.vertex_path is None and asset.fragment_path is None:
                self._safe_log(
                    f"Warning: GameMaker shader {resource.name} has no .vsh or .fsh stage."
                )
                continue
            seen_names.add(resource.name)
            assets.append(asset)
        return tuple(assets)

    def _disk_shader_assets(self, gm_shaders_path: str) -> tuple[_ShaderAsset, ...]:
        builders: dict[str, _ShaderAssetBuilder] = {}
        for root, directories, files in os.walk(gm_shaders_path):
            directories.sort()
            for filename in sorted(files):
                extension = os.path.splitext(filename)[1].lower()
                if extension not in (".vsh", ".fsh"):
                    continue
                full_path = os.path.join(root, filename)
                directory_name = os.path.basename(root)
                yy_path = os.path.join(root, directory_name + ".yy")
                yy_data = self._read_yy_file(yy_path)
                raw_resource_name = yy_data.get("name") if yy_data is not None else None
                resource_name = (
                    raw_resource_name
                    if isinstance(raw_resource_name, str) and raw_resource_name
                    else os.path.splitext(filename)[0]
                )
                builder = builders.get(resource_name)
                if builder is None:
                    builder = _ShaderAssetBuilder(
                        name=resource_name,
                        subfolder=(
                            self._get_subfolder_from_yy(yy_path)
                            if os.path.isfile(yy_path)
                            else ""
                        ),
                        source_directory=root,
                    )
                    builders[resource_name] = builder
                elif builder.source_directory != root:
                    continue
                if extension == ".vsh" and builder.vertex_path is None:
                    builder.vertex_path = full_path
                elif extension == ".fsh" and builder.fragment_path is None:
                    builder.fragment_path = full_path
        return tuple(
            builders[name].build()
            for name in sorted(builders, key=lambda value: (value.casefold(), value))
        )

    def convert_all(self) -> None:
        gm_shaders_path = os.path.join(self.gm_project_path, 'shaders')

        if not os.path.exists(gm_shaders_path):
            self.log_callback("No shaders directory found. Skipping shader conversion.")
            return

        os.makedirs(self.godot_shaders_path, exist_ok=True)

        self._shader_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        ).get("shaders", {})

        shader_assets = self._indexed_shader_assets()
        if shader_assets is None:
            shader_assets = self._disk_shader_assets(gm_shaders_path)

        if not shader_assets:
            self.log_callback("No shader files (.vsh/.fsh) found.")
            return

        total = len(shader_assets)
        processed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[tuple[str, str] | None], _ShaderAsset] = {
                executor.submit(self._process_shader, asset): asset
                for asset in shader_assets
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback("Shader conversion stopped.")
                    return

                filename, output_name = result
                processed += 1

                if self.compact_logging:
                    self._safe_log_progress(filename, processed, total)
                else:
                    self._safe_log(get_localized("Console_Convertor_Shaders_Converted").format(
                        filename=filename, output_path=output_name))

                self._safe_progress(int((processed / total) * 100))

        self.log_callback("Shader conversion complete.")
