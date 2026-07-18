from __future__ import annotations

import os
import re
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from src.conversion.asset_output_paths import build_asset_output_paths, resource_filesystem_path
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import generated_resource_stem, generated_subfolder_path
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath
from src.localization import get_localized


@dataclass(frozen=True)
class _ShaderAsset:
    name: str
    subfolder: str
    owner_path: str | None = None
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
    owner_path: str | None = None
    vertex_path: str | None = None
    fragment_path: str | None = None

    def build(self) -> _ShaderAsset:
        return _ShaderAsset(
            name=self.name,
            subfolder=self.subfolder,
            owner_path=self.owner_path,
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
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path,
                         log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_shaders_path = os.path.join(self.godot_project_path, 'shaders')
        self._shader_output_paths: dict[str, str] = {}

    def convert_shader(self, input_file: str, output_file: str) -> None:
        """Convert one legacy stage and publish it as a complete shader resource."""
        resolved_input = self._resolve_discovered_project_source(
            input_file,
            owner_source_path=input_file,
            resource=os.path.splitext(os.path.basename(input_file))[0],
            resource_type="shader",
            field="shader stage",
        )
        if resolved_input is None or not os.path.isfile(resolved_input.filesystem_path):
            return
        with open(resolved_input.filesystem_path, 'r', encoding='utf-8') as f:
            content = f.read()
        stage = (
            "vertex"
            if resolved_input.filesystem_path.lower().endswith(".vsh")
            else "fragment"
        )
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
            resolved_source = self._resolve_discovered_project_source(
                source_path,
                owner_source_path=asset.owner_path or source_path,
                resource=asset.name,
                resource_type="shader",
                field=f"{stage} stage",
            )
            if resolved_source is None or not os.path.isfile(
                resolved_source.filesystem_path
            ):
                continue
            with open(
                resolved_source.filesystem_path,
                "r",
                encoding="utf-8",
            ) as source_file:
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
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="shader",
        )
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
            is_shader = (
                resource.kind.casefold() == "shaders"
                or resource.resource_type.casefold() == "gmshader"
            )
            if not is_shader or resource.name in seen_names:
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            resolved = self._resolve_project_source(
                resource.path,
                owner_source_path=manifest.yyp_path,
                resource=resource.name,
                resource_type="shader",
                field=manifest_field,
            )
            if resolved is None:
                continue
            try:
                validate_project_resource_source_path(resolved, "shaders")
            except ProjectSourcePathError as exc:
                self._report_source_path_rejection(
                    resource.path,
                    exc,
                    owner_source_path=manifest.yyp_path,
                    resource=resource.name,
                    resource_type="shader",
                    field=manifest_field,
                )
                continue
            yy_path = resolved.filesystem_path
            if not os.path.isfile(yy_path):
                self._safe_log(
                    f"Warning: Skipping missing GameMaker shader {resource.name}: {yy_path}"
                )
                continue
            base_path = os.path.splitext(yy_path)[0]
            vertex_source = self._resolve_discovered_project_source(
                base_path + ".vsh",
                owner_source_path=resolved.source_path,
                resource=resource.name,
                resource_type="shader",
                field="derived .vsh stage",
            )
            fragment_source = self._resolve_discovered_project_source(
                base_path + ".fsh",
                owner_source_path=resolved.source_path,
                resource=resource.name,
                resource_type="shader",
                field="derived .fsh stage",
            )
            vertex_path = (
                vertex_source.filesystem_path
                if vertex_source is not None
                and os.path.isfile(vertex_source.filesystem_path)
                else None
            )
            fragment_path = (
                fragment_source.filesystem_path
                if fragment_source is not None
                and os.path.isfile(fragment_source.filesystem_path)
                else None
            )
            asset = _ShaderAsset(
                name=resource.name,
                subfolder=self._get_subfolder_from_yy(yy_path),
                owner_path=resolved.source_path,
                vertex_path=vertex_path,
                fragment_path=fragment_path,
            )
            if asset.vertex_path is None and asset.fragment_path is None:
                self._safe_log(
                    f"Warning: GameMaker shader {resource.name} has no .vsh or .fsh stage."
                )
                continue
            seen_names.add(resource.name)
            assets.append(asset)
        return tuple(assets)

    def _disk_shader_assets(
        self,
        shader_root: ResolvedProjectSourcePath,
    ) -> tuple[_ShaderAsset, ...]:
        builders: dict[str, _ShaderAssetBuilder] = {}
        pending_directories = [shader_root]
        visited_directories: set[str] = set()
        while pending_directories:
            directory = pending_directories.pop()
            resolved_directory = self._resolve_discovered_project_source(
                directory.filesystem_path,
                owner_source_path=directory.source_path,
                resource=os.path.basename(directory.source_path),
                resource_type="shader",
                field="discovered shader directory",
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

            directory_name = os.path.basename(resolved_directory.filesystem_path)
            expected_yy_name = directory_name + ".yy"
            stages: list[tuple[str, str]] = []
            resolved_yy: ResolvedProjectSourcePath | None = None
            child_directories: list[ResolvedProjectSourcePath] = []
            try:
                with os.scandir(resolved_directory.filesystem_path) as entries:
                    for entry in sorted(entries, key=lambda item: item.name):
                        extension = os.path.splitext(entry.name)[1].casefold()
                        is_stage = extension in (".vsh", ".fsh")
                        is_expected_yy = entry.name == expected_yy_name
                        try:
                            is_unlinked_directory = entry.is_dir(
                                follow_symlinks=False
                            )
                            is_symlink = entry.is_symlink()
                        except OSError:
                            continue
                        if (
                            not is_stage
                            and not is_expected_yy
                            and not is_unlinked_directory
                            and not is_symlink
                        ):
                            continue

                        if is_unlinked_directory or (
                            is_symlink and not is_stage and not is_expected_yy
                        ):
                            resource_name = entry.name
                            field = "discovered shader directory"
                        elif is_expected_yy:
                            resource_name = directory_name
                            field = "discovered .yy"
                        else:
                            resource_name = os.path.splitext(entry.name)[0]
                            field = f"discovered {extension} stage"
                        resolved_entry = self._resolve_discovered_project_source(
                            entry.path,
                            owner_source_path=resolved_directory.source_path,
                            resource=resource_name,
                            resource_type="shader",
                            field=field,
                        )
                        if resolved_entry is None:
                            continue

                        if os.path.isdir(resolved_entry.filesystem_path):
                            # Validate directory links so escaping targets are
                            # diagnosed, but never follow links during fallback.
                            if not is_symlink:
                                child_directories.append(resolved_entry)
                            continue
                        if is_expected_yy and os.path.isfile(
                            resolved_entry.filesystem_path
                        ):
                            try:
                                validate_project_resource_source_path(
                                    resolved_entry,
                                    "shaders",
                                )
                            except ProjectSourcePathError as exc:
                                self._report_source_path_rejection(
                                    entry.path,
                                    exc,
                                    owner_source_path=resolved_directory.source_path,
                                    resource=directory_name,
                                    resource_type="shader",
                                    field="discovered .yy",
                                )
                                continue
                            resolved_yy = resolved_entry
                        elif is_stage and os.path.isfile(
                            resolved_entry.filesystem_path
                        ):
                            stages.append((extension, resolved_entry.filesystem_path))
            except OSError:
                continue
            pending_directories.extend(reversed(child_directories))
            if not stages:
                continue

            yy_path = resolved_yy.filesystem_path if resolved_yy is not None else None
            yy_data = self._read_yy_file(yy_path) if yy_path is not None else None
            subfolder = (
                self._get_subfolder_from_yy(yy_path)
                if yy_path is not None
                else ""
            )
            owner_path = (
                resolved_yy.source_path
                if resolved_yy is not None
                else resolved_directory.source_path
            )
            for extension, full_path in stages:
                raw_resource_name = yy_data.get("name") if yy_data is not None else None
                resource_name = (
                    raw_resource_name
                    if isinstance(raw_resource_name, str) and raw_resource_name
                    else os.path.splitext(os.path.basename(full_path))[0]
                )
                builder = builders.get(resource_name)
                if builder is None:
                    builder = _ShaderAssetBuilder(
                        name=resource_name,
                        subfolder=subfolder,
                        source_directory=resolved_directory.filesystem_path,
                        owner_path=owner_path,
                    )
                    builders[resource_name] = builder
                elif builder.source_directory != resolved_directory.filesystem_path:
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
        shader_root = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, 'shaders'),
            resource_type="shader",
            field="shaders directory",
        )

        if shader_root is None or not os.path.isdir(shader_root.filesystem_path):
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
            shader_assets = self._disk_shader_assets(shader_root)

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
