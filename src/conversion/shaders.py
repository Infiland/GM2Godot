from __future__ import annotations

import os
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from src.conversion.asset_output_paths import build_asset_output_paths, resource_filesystem_path
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import generated_resource_stem, generated_subfolder_path
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
from src.conversion.shader_translation import (
    ShaderStage,
    ShaderStageSource,
    ShaderTranslationIssue,
    translate_gamemaker_shader,
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


@dataclass(frozen=True)
class _DeclaredShaderResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


@dataclass(frozen=True)
class _ShaderConversionPlan:
    requested_names: tuple[str, ...]
    available_assets: tuple[_ShaderAsset, ...]
    skipped_names: tuple[str, ...]


@dataclass(frozen=True)
class _ShaderRenderResult:
    source: str | None
    reported_failure: bool = False


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
        stage: ShaderStage = (
            "vertex"
            if resolved_input.filesystem_path.lower().endswith(".vsh")
            else "fragment"
        )
        translation = translate_gamemaker_shader(
            (ShaderStageSource(stage=stage, source=content),)
        )
        if translation.source is None:
            self._report_shader_translation_issues(
                _ShaderAsset(
                    name=os.path.splitext(
                        os.path.basename(resolved_input.filesystem_path)
                    )[0],
                    subfolder="",
                    owner_path=resolved_input.source_path,
                    vertex_path=(
                        resolved_input.filesystem_path
                        if stage == "vertex"
                        else None
                    ),
                    fragment_path=(
                        resolved_input.filesystem_path
                        if stage == "fragment"
                        else None
                    ),
                ),
                translation.issues,
                {stage: resolved_input.filesystem_path},
            )
            return
        self._atomic_write_text(output_file, translation.source)

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

    def _render_shader_asset(self, asset: _ShaderAsset) -> _ShaderRenderResult:
        stage_sources: list[ShaderStageSource] = []
        source_paths: dict[ShaderStage, str] = {}
        stage_paths: tuple[tuple[ShaderStage, str | None], ...] = (
            ("vertex", asset.vertex_path),
            ("fragment", asset.fragment_path),
        )
        for stage, source_path in stage_paths:
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
                return _ShaderRenderResult(source=None)
            try:
                with open(
                    resolved_source.filesystem_path,
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    source = source_file.read()
            except OSError:
                return _ShaderRenderResult(source=None)
            if not source.strip():
                return _ShaderRenderResult(source=None)
            stage_sources.append(ShaderStageSource(stage=stage, source=source))
            source_paths[stage] = resolved_source.filesystem_path
        if not stage_sources:
            return _ShaderRenderResult(source=None)
        translation = translate_gamemaker_shader(tuple(stage_sources))
        if translation.source is None:
            self._report_shader_translation_issues(
                asset,
                translation.issues,
                source_paths,
            )
            return _ShaderRenderResult(source=None, reported_failure=True)
        return _ShaderRenderResult(source=translation.source)

    def _report_shader_translation_issues(
        self,
        asset: _ShaderAsset,
        issues: tuple[ShaderTranslationIssue, ...],
        source_paths: dict[ShaderStage, str],
    ) -> None:
        for issue in issues:
            source_path = self._diagnostic_source_path(
                source_paths.get(issue.stage)
            )
            location = (
                f"{source_path or asset.source_label}:"
                f"{issue.line}:{issue.column}"
            )
            message = (
                f"Warning: GameMaker shader {asset.name!r} {issue.stage} "
                f"stage at {location}: {issue.message}"
            )
            with self._lock:
                if self.diagnostics is not None:
                    self.diagnostics.add(
                        "warning",
                        issue.code,
                        message,
                        source_path=source_path,
                        line=issue.line,
                        column=issue.column,
                        resource=asset.name,
                        resource_type="shader",
                        event=issue.stage,
                        manifest_entry=issue.construct,
                        issue_number=708,
                        workaround=issue.workaround,
                    )
                self.log_callback(message)

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
        render_result = self._render_shader_asset(asset)
        if render_result.source is None:
            if not render_result.reported_failure:
                self._safe_log(
                    f"Warning: GameMaker shader {asset.name} does not have a "
                    "complete, non-empty readable stage set during conversion."
                )
            return None
        self._atomic_write_text(output_path, render_result.source)
        return (asset.source_label, output_name)

    def _process_shader_with_outcome(
        self,
        asset: _ShaderAsset,
    ) -> tuple[str, str] | None:
        if not self.conversion_running():
            return None
        self._resource_started(asset.name)
        try:
            result = self._process_shader(asset)
        except Exception:
            self._resource_failed(asset.name)
            raise
        if result is None:
            if self.conversion_running():
                self._resource_failed(asset.name)
            else:
                self._resource_skipped(asset.name)
        else:
            self._resource_completed(asset.name)
        return result

    def _indexed_shader_plan(self) -> _ShaderConversionPlan | None:
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="shader",
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            return None
        return self._plan_manifest_shaders(manifest)

    def _declared_shader_resources(
        self,
        manifest: GameMakerProjectManifest,
    ) -> tuple[tuple[_DeclaredShaderResource, ...], ...]:
        """Return every logical shader declaration, including rejected paths."""
        declared_by_name: dict[str, list[_DeclaredShaderResource]] = {}
        seen_declarations: set[tuple[str, str | None]] = set()

        def add(resource: _DeclaredShaderResource) -> None:
            declaration_key = (resource.name, resource.source_path)
            if not resource.name or declaration_key in seen_declarations:
                return
            seen_declarations.add(declaration_key)
            declared_by_name.setdefault(resource.name, []).append(resource)

        for resource in manifest.resources:
            is_shader = (
                resource.kind.casefold() == "shaders"
                or resource.resource_type.casefold() == "gmshader"
            )
            if not is_shader:
                continue
            manifest_field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredShaderResource(
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
                or not self._manifest_diagnostic_is_shader(diagnostic)
            ):
                continue
            add(
                _DeclaredShaderResource(
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
    def _manifest_diagnostic_is_shader(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "shaders"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"shader", "gmshader"}
        )

    def _plan_manifest_shaders(
        self,
        manifest: GameMakerProjectManifest,
    ) -> _ShaderConversionPlan:
        """Resolve one available stage set for each declared base shader."""
        requested_names: list[str] = []
        available_assets: list[_ShaderAsset] = []
        skipped_names: list[str] = []

        for declarations in self._declared_shader_resources(manifest):
            shader_name = declarations[0].name
            selected_asset: _ShaderAsset | None = None
            unavailable_reason = (
                "all of its manifest source paths are unavailable"
            )

            for declaration in declarations:
                if declaration.source_path is None:
                    unavailable_reason = "its manifest source path was rejected"
                    continue
                resolved = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=shader_name,
                    resource_type="shader",
                    field=declaration.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = (
                        "its manifest source path is unavailable"
                    )
                    continue
                try:
                    validate_project_resource_source_path(
                        resolved,
                        "shaders",
                    )
                except ProjectSourcePathError as exc:
                    self._report_source_path_rejection(
                        declaration.source_path,
                        exc,
                        owner_source_path=declaration.owner_source_path,
                        resource=shader_name,
                        resource_type="shader",
                        field=declaration.manifest_field,
                    )
                    unavailable_reason = (
                        "its manifest source path is outside the shaders "
                        "resource family or is not .yy metadata"
                    )
                    continue

                yy_path = resolved.filesystem_path
                if not os.path.isfile(yy_path):
                    unavailable_reason = (
                        f"metadata is missing at {resolved.source_path!r}"
                    )
                    continue

                base_path = os.path.splitext(yy_path)[0]
                vertex_source = self._resolve_discovered_project_source(
                    base_path + ".vsh",
                    owner_source_path=resolved.source_path,
                    resource=shader_name,
                    resource_type="shader",
                    field="derived .vsh stage",
                )
                fragment_source = self._resolve_discovered_project_source(
                    base_path + ".fsh",
                    owner_source_path=resolved.source_path,
                    resource=shader_name,
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
                if vertex_path is None and fragment_path is None:
                    unavailable_reason = (
                        "it has no readable .vsh or .fsh stage beside its "
                        "metadata"
                    )
                    continue

                selected_asset = _ShaderAsset(
                    name=shader_name,
                    subfolder=self._get_subfolder_from_yy(yy_path),
                    owner_path=resolved.source_path,
                    vertex_path=vertex_path,
                    fragment_path=fragment_path,
                )
                break

            requested_names.append(shader_name)
            if selected_asset is None:
                skipped_names.append(shader_name)
                self._report_unavailable_declared_shader(
                    declarations[0],
                    reason=unavailable_reason,
                )
            else:
                available_assets.append(selected_asset)

        return _ShaderConversionPlan(
            requested_names=tuple(requested_names),
            available_assets=tuple(available_assets),
            skipped_names=tuple(skipped_names),
        )

    def _report_unavailable_declared_shader(
        self,
        resource: _DeclaredShaderResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker shader "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-SHADER-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="shader",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker shader .yy metadata and "
                    "at least one .vsh or .fsh stage inside the project root, "
                    "or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

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
        self._reset_resource_outcomes()
        shader_plan = self._indexed_shader_plan()
        if shader_plan is None:
            shader_root = self._resolve_discovered_project_source(
                os.path.join(self.gm_project_path, 'shaders'),
                resource_type="shader",
                field="shaders directory",
            )
            if shader_root is None or not os.path.isdir(
                shader_root.filesystem_path
            ):
                self.log_callback(
                    "No shaders directory found. Skipping shader conversion."
                )
                return
            disk_assets = self._disk_shader_assets(shader_root)
            shader_plan = _ShaderConversionPlan(
                requested_names=tuple(asset.name for asset in disk_assets),
                available_assets=disk_assets,
                skipped_names=(),
            )

        for shader_name in shader_plan.requested_names:
            self._resource_requested(shader_name)
        for shader_name in shader_plan.skipped_names:
            self._resource_skipped(shader_name)

        shader_assets = shader_plan.available_assets
        if not shader_assets:
            self.log_callback("No shader files (.vsh/.fsh) found.")
            return

        os.makedirs(self.godot_shaders_path, exist_ok=True)
        self._shader_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        ).get("shaders", {})

        total = len(shader_plan.requested_names)
        processed = len(shader_plan.skipped_names)
        if processed:
            self._safe_progress(int((processed / total) * 100))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[tuple[str, str] | None], _ShaderAsset] = {
                executor.submit(self._process_shader_with_outcome, asset): asset
                for asset in shader_assets
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    if not self.conversion_running():
                        self.log_callback("Shader conversion stopped.")
                        return
                    processed += 1
                    self._safe_progress(int((processed / total) * 100))
                    continue

                filename, output_name = result
                processed += 1

                if self.compact_logging:
                    self._safe_log_progress(filename, processed, total)
                else:
                    self._safe_log(get_localized("Console_Convertor_Shaders_Converted").format(
                        filename=filename, output_path=output_name))

                self._safe_progress(int((processed / total) * 100))

        self.log_callback("Shader conversion complete.")
