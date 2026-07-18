# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import posixpath
import tempfile
from dataclasses import dataclass
from typing import Iterable, Mapping

from src.localization import get_localized
from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import (
    EXTENSION_FUNCTION_MAPPING_FILENAME,
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    GMLSourceMap,
    analyze_gml_source_identifiers,
    merge_gml_source_maps,
    render_gml_source_header,
    load_gml_extension_function_mappings,
    transpile_gml_code_with_source_map,
    transpile_gml_expression,
    write_gml_source_map,
)
from src.conversion.resource_index import GameMakerResourceIndex
from src.conversion.project_manifest import (
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    is_safe_project_source_component,
    validate_project_resource_source_path,
)
from src.conversion.project_enums import collect_project_enum_values
from src.conversion.project_macros import collect_project_macro_values
from src.conversion.script_functions import (
    ScriptFunctionDeclaration,
    modern_script_structure,
    render_script_top_level_source,
)
from src.conversion.gml_transpiler_parts.identifiers import (
    _sanitize_gdscript_identifier,
)
from src.conversion.gml_transpiler_parts.expression_parser import (
    _parse_gml_expression,
)
from src.conversion.gml_transpiler_parts.function_helpers import (
    _emit_constructor_inheritance_line,
)
from src.conversion.gml_transpiler_parts.model import _ScopeContext
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath


SCRIPT_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_script_registry.gd")
SCRIPT_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_script_registry.gd"
_SCRIPT_SELF_PARAMETER = "_gml_script_self"
_SCRIPT_OTHER_PARAMETER = "_gml_script_other"


@dataclass(frozen=True)
class ScriptRegistryEntry:
    id: int | str
    name: str
    resource_path: str
    legacy_arguments: bool
    callable_method: str = "gm2godot_callable"
    scoped_callable_method: str = "gm2godot_scoped_callable"
    is_constructor: bool = False
    initializer_method: str | None = None


@dataclass(frozen=True)
class _ScriptCallableNames:
    call_method: str
    scoped_call_method: str
    callable_accessor: str
    scoped_callable_accessor: str


@dataclass(frozen=True)
class _DeclaredScriptResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


def _script_scope_context() -> _ScopeContext:
    return _ScopeContext(
        self_expression=_SCRIPT_SELF_PARAMETER,
        other_expression=_SCRIPT_OTHER_PARAMETER,
        instance_target=_SCRIPT_SELF_PARAMETER,
    )


def _constructor_scope_context() -> _ScopeContext:
    return _ScopeContext(
        self_expression="_gml_constructor_self",
        other_expression="_gml_constructor_self",
        instance_target="_gml_constructor_self",
    )


def _script_scope_lines() -> list[str]:
    return [
        (
            f"\tif {_SCRIPT_SELF_PARAMETER} == null "
            f"or GMRuntime.is_undefined({_SCRIPT_SELF_PARAMETER}): "
            f"{_SCRIPT_SELF_PARAMETER} = self"
        ),
        (
            f"\tif {_SCRIPT_OTHER_PARAMETER} == null "
            f"or GMRuntime.is_undefined({_SCRIPT_OTHER_PARAMETER}): "
            f"{_SCRIPT_OTHER_PARAMETER} = {_SCRIPT_SELF_PARAMETER}"
        ),
    ]


def _script_forward_call(*, declaration: ScriptFunctionDeclaration, scoped_call_method: str) -> str:
    args = [
        "self",
        "self",
        *(_sanitize_gdscript_identifier(parameter.name) for parameter in declaration.parameters),
    ]
    return f"\treturn {scoped_call_method}({', '.join(args)})\n"


def _script_callable_names(declaration_name: str, *, use_default_names: bool) -> _ScriptCallableNames:
    if use_default_names:
        return _ScriptCallableNames(
            call_method="_gm_script_call",
            scoped_call_method="_gm_script_call_scoped",
            callable_accessor="gm2godot_callable",
            scoped_callable_accessor="gm2godot_scoped_callable",
        )
    suffix = _sanitize_gdscript_identifier(declaration_name)
    return _ScriptCallableNames(
        call_method=f"_gm_script_call_{suffix}",
        scoped_call_method=f"_gm_script_call_scoped_{suffix}",
        callable_accessor=f"gm2godot_callable_{suffix}",
        scoped_callable_accessor=f"gm2godot_scoped_callable_{suffix}",
    )


def _is_script_function_entry(entry: AssetRegistryEntry) -> bool:
    metadata = entry.metadata or {}
    return bool(metadata.get("script_function"))


def render_script_registry_script(entries: Iterable[ScriptRegistryEntry]) -> str:
    entry_list = list(entries)
    lines = [
        "extends RefCounted\n\n",
        "static func gml_script_registry_entries():\n",
    ]
    constructor_variables: dict[int, str] = {}
    initializer_owner_variables: dict[int, str] = {}
    for index, entry in enumerate(entry_list):
        if not entry.is_constructor:
            if entry.initializer_method is None:
                continue
        if entry.is_constructor:
            variable_name = f"_gm_constructor_{index}"
            constructor_variables[index] = variable_name
            lines.append(
                f"\tvar {variable_name} = "
                f"preload({json.dumps(entry.resource_path)}).new().{entry.callable_method}()\n"
            )
        if entry.initializer_method is not None:
            owner_variable_name = f"_gm_initializer_owner_{index}"
            initializer_owner_variables[index] = owner_variable_name
            lines.append(
                f"\tvar {owner_variable_name} = "
                f"preload({json.dumps(entry.resource_path)}).new()\n"
            )
    lines.append("\treturn [\n")
    for index, entry in enumerate(entry_list):
        constructor_variable = constructor_variables.get(index)
        callable_expression = (
            constructor_variable
            if constructor_variable is not None
            else f"preload({json.dumps(entry.resource_path)}).new().{entry.callable_method}()"
        )
        scoped_callable_expression = (
            constructor_variable
            if constructor_variable is not None
            else (
                f"preload({json.dumps(entry.resource_path)}).new()."
                f"{entry.scoped_callable_method}()"
            )
        )
        lines.extend(
            [
                "\t\t{\n",
                f"\t\t\t\"id\": {json.dumps(entry.id)},\n",
                f"\t\t\t\"name\": {json.dumps(entry.name)},\n",
                f"\t\t\t\"callable\": {callable_expression},\n",
                f"\t\t\t\"scoped_callable\": {scoped_callable_expression},\n",
            ]
        )
        if entry.initializer_method is not None:
            initializer_owner = initializer_owner_variables[index]
            lines.append(
                f"\t\t\t\"initializer_owner\": {initializer_owner},\n"
                f"\t\t\t\"initializer\": Callable({initializer_owner}, "
                f"{json.dumps(entry.initializer_method)}),\n"
            )
        lines.extend(
            [
                f"\t\t\t\"legacy_arguments\": {str(entry.legacy_arguments).lower()},\n",
                "\t\t},\n",
            ]
        )
    lines.append("\t]\n")
    return "".join(lines)


class ScriptConverter(BaseConverter):
    """Convert GameMaker script assets into callable Godot wrappers."""

    def __init__(
        self,
        gm_project_path: StrPath,
        godot_project_path: StrPath,
        log_callback: LogCallback = print,
        progress_callback: ProgressCallback | None = None,
        conversion_running: ConversionRunning | None = None,
        update_log_callback: LogCallback | None = None,
        compact_logging: bool = False,
        max_workers: int | None = None,
        diagnostics: DiagnosticCollector | None = None,
        macro_configuration: str | None = None,
    ) -> None:
        super().__init__(
            gm_project_path,
            godot_project_path,
            log_callback,
            progress_callback,
            conversion_running,
            update_log_callback,
            compact_logging,
            max_workers=max_workers,
            diagnostics=diagnostics,
        )
        self.godot_scripts_path = os.path.join(self.godot_project_path, "scripts")
        self.macro_configuration = macro_configuration

    def _registry_entries(self) -> tuple[AssetRegistryEntry, ...]:
        registry_converter = AssetRegistryConverter(
            self.gm_project_path,
            self.godot_project_path,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            # Planning must enumerate the complete deterministic resource set.
            # The live cancellation flag is checked before script execution.
            conversion_running=lambda: True,
            macro_configuration=self.macro_configuration,
        )
        return tuple(registry_converter.build_entries())

    def _asset_entries(self) -> tuple[AssetRegistryEntry, ...]:
        return tuple(entry for entry in self._registry_entries() if entry.asset_type == "script")

    def _declared_script_resources(
        self,
    ) -> tuple[_DeclaredScriptResource, ...] | None:
        """Return base scripts selected by a valid YYP, including rejected paths."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="script",
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            return None

        declared: dict[str, _DeclaredScriptResource] = {}
        for resource in manifest.find_resources(kind="scripts"):
            if not resource.name:
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            declared.setdefault(
                resource.name,
                _DeclaredScriptResource(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path,
                    manifest_field=field,
                ),
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_script(diagnostic)
            ):
                continue
            declared.setdefault(
                diagnostic.resource,
                _DeclaredScriptResource(
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
                ),
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_script(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "scripts"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold() in {"script", "gmscript"}
        )

    def _report_unavailable_declared_script(
        self,
        resource: _DeclaredScriptResource,
    ) -> None:
        """Retain path diagnostics while accounting for an unavailable script."""
        if resource.source_path is None:
            return
        resolved = self._resolve_project_source(
            resource.source_path,
            owner_source_path=resource.owner_source_path,
            resource=resource.name,
            resource_type="script",
            field=resource.manifest_field,
        )
        if resolved is None:
            return
        try:
            validate_project_resource_source_path(resolved, "scripts")
        except ProjectSourcePathError as error:
            self._report_source_path_rejection(
                resource.source_path,
                error,
                owner_source_path=resource.owner_source_path,
                resource=resource.name,
                resource_type="script",
                field=resource.manifest_field,
            )
            return
        if not os.path.isfile(resolved.filesystem_path):
            self._safe_log(
                "Warning: Skipping missing GameMaker asset "
                f"{resource.name}: {resolved.filesystem_path}"
            )

    def _script_yy_source(
        self,
        entry: AssetRegistryEntry,
    ) -> ResolvedProjectSourcePath | None:
        resolved = self._resolve_project_source(
            entry.source_path,
            resource=entry.name,
            resource_type="script",
            field="script .yy",
        )
        if resolved is None:
            return None

        normalized_source_path = resolved.source_path.casefold()
        if not (
            normalized_source_path.startswith("scripts/")
            and normalized_source_path.endswith(".yy")
        ):
            self._report_source_path_rejection(
                entry.source_path,
                ProjectSourcePathError(
                    "GameMaker script reference must name a .yy file under scripts/: "
                    f"{entry.source_path!r}"
                ),
                owner_source_path=None,
                resource=entry.name,
                resource_type="script",
                field="script .yy",
            )
            return None
        if not os.path.isfile(resolved.filesystem_path):
            return None
        return resolved

    def _source_gml_path(self, entry: AssetRegistryEntry) -> str | None:
        yy_source = self._script_yy_source(entry)
        if yy_source is None:
            return None

        script_directory = self._resolve_discovered_project_source(
            os.path.dirname(yy_source.filesystem_path),
            owner_source_path=yy_source.source_path,
            resource=entry.name,
            resource_type="script",
            field="script source directory",
        )
        if script_directory is None or not os.path.isdir(
            script_directory.filesystem_path
        ):
            return None

        preferred_filename = entry.name + ".gml"
        excluded_filenames = {preferred_filename}
        preferred_source: ResolvedProjectSourcePath | None = None
        if is_safe_project_source_component(entry.name):
            preferred_source = self._resolve_project_source(
                preferred_filename,
                owner_source_path=yy_source.source_path,
                resource=entry.name,
                resource_type="script",
                field="preferred script source",
            )
        else:
            normalized_preferred_filename = posixpath.basename(
                posixpath.normpath(preferred_filename.replace("\\", "/"))
            )
            if normalized_preferred_filename:
                excluded_filenames.add(normalized_preferred_filename)
            self._report_source_path_rejection(
                preferred_filename,
                ProjectSourcePathError(
                    "GameMaker script resource names used to derive source "
                    "filenames must be exactly one safe path component: "
                    f"{entry.name!r}"
                ),
                owner_source_path=yy_source.source_path,
                resource=entry.name,
                resource_type="script",
                field="preferred script source",
            )
        if preferred_source is not None:
            owner_directory = posixpath.dirname(yy_source.source_path)
            preferred_directory = posixpath.dirname(preferred_source.source_path)
            if preferred_directory != owner_directory:
                self._report_source_path_rejection(
                    preferred_filename,
                    ProjectSourcePathError(
                        "GameMaker script source derived from the resource name "
                        "must be next to its script .yy owner: "
                        f"{preferred_filename!r}"
                    ),
                    owner_source_path=yy_source.source_path,
                    resource=entry.name,
                    resource_type="script",
                    field="preferred script source",
                )
                preferred_source = None
            elif os.path.isfile(preferred_source.filesystem_path):
                return preferred_source.filesystem_path

        try:
            filenames = sorted(os.listdir(script_directory.filesystem_path))
        except OSError:
            return None
        for filename in filenames:
            if not filename.endswith(".gml"):
                continue
            if filename in excluded_filenames:
                continue
            discovered_source = self._resolve_discovered_project_source(
                os.path.join(script_directory.filesystem_path, filename),
                owner_source_path=yy_source.source_path,
                resource=entry.name,
                resource_type="script",
                field="discovered script source",
            )
            if discovered_source is None or not os.path.isfile(
                discovered_source.filesystem_path
            ):
                continue
            return discovered_source.filesystem_path
        return None

    def _output_path(self, entry: AssetRegistryEntry) -> str | None:
        if not entry.godot_path.startswith("res://"):
            return None
        relative_path = entry.godot_path[len("res://"):].replace("/", os.sep)
        return os.path.join(self.godot_project_path, relative_path)

    def _modern_function_body(
        self,
        declaration: ScriptFunctionDeclaration,
        *,
        source_path: str,
        asset_names: set[str],
        static_scope_prefix: str,
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
        enum_values: Mapping[str, Mapping[str, int]],
        macro_values: Mapping[str, str],
        generated_line_offset: int = 0,
    ) -> tuple[str, GMLSourceMap, str | None]:
        local_names = {parameter.name for parameter in declaration.parameters}
        script_scope = (
            _constructor_scope_context()
            if declaration.is_constructor
            else _script_scope_context()
        )
        lines: list[str] = [] if declaration.is_constructor else _script_scope_lines()
        for parameter in declaration.parameters:
            parameter_name = _sanitize_gdscript_identifier(parameter.name)
            if parameter.default is None:
                lines.append(f"\tif {parameter_name} == null: {parameter_name} = GMRuntime.gml_undefined()")
                continue
            default_value = transpile_gml_expression(
                parameter.default,
                local_names=local_names,
                asset_names=asset_names,
                scope_context=script_scope,
                enum_values={
                    name: dict(members) for name, members in enum_values.items()
                },
                enum_names=enum_values,
                macro_values=macro_values,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            lines.append(
                f"\tif {parameter_name} == null or GMRuntime.is_undefined({parameter_name}): "
                f"{parameter_name} = {default_value}"
            )
        if declaration.parent_constructor is not None:
            outer_scope = _ScopeContext(
                self_expression="self",
                other_expression="self",
                instance_target="self",
                asset_names=frozenset(asset_names),
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            constructor_scope = _ScopeContext(
                self_expression="_gml_constructor_self",
                other_expression="_gml_constructor_self",
                instance_target="_gml_constructor_self",
                asset_names=frozenset(asset_names),
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            parent_expression = _parse_gml_expression(
                declaration.parent_constructor,
                {name: dict(members) for name, members in enum_values.items()},
                enum_values,
                macro_values=macro_values,
                scope_context=outer_scope,
            )
            lines.append(
                "\t"
                + _emit_constructor_inheritance_line(
                    parent_expression,
                    local_names,
                    constructor_scope,
                    outer_scope,
                )
            )
        result = transpile_gml_code_with_source_map(
            declaration.body,
            return_depth=1,
            asset_names=asset_names,
            static_scope_prefix=static_scope_prefix,
            self_expression=script_scope.self_expression,
            other_expression=script_scope.other_expression,
            instance_target=script_scope.instance_target,
            local_names=local_names,
            enum_values=enum_values,
            macro_values=macro_values,
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
            macro_configuration=self.macro_configuration,
            source_path=source_path,
            event=f"script:{declaration.name}",
            preserve_source_comments=True,
            generated_line_offset=generated_line_offset + len(lines),
        )
        lines.append(result.code)
        return (
            "\n".join(lines),
            result.source_map.with_source_offset(
                declaration.body_line_offset,
                declaration.body_column_offset,
            ),
            result.static_scope_id,
        )

    def _render_script(
        self,
        entry: AssetRegistryEntry,
        source: str,
        *,
        source_path: str,
        asset_names: set[str],
        script_entries_by_name: dict[str, AssetRegistryEntry],
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
        enum_values: Mapping[str, Mapping[str, int]],
        macro_values: Mapping[str, str],
    ) -> tuple[str, tuple[ScriptRegistryEntry, ...], tuple[GMLSourceMap, ...]]:
        header = render_gml_source_header(
            source_path=source_path,
            event=f"script:{entry.name}",
            source=source,
        )
        modern_structure = modern_script_structure(
            source,
            macro_configuration=self.macro_configuration,
        )
        if modern_structure is not None:
            modern_declarations = modern_structure.declarations
            if not modern_declarations:
                modern_declarations = (
                    ScriptFunctionDeclaration(
                        name=entry.name,
                        parameters=(),
                        body="",
                    ),
                )
            chunks = [
                "extends RefCounted\n\n",
                f"{header}",
                'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n',
            ]
            registry_entries: list[ScriptRegistryEntry] = []
            source_maps: list[GMLSourceMap] = []
            for declaration_index, declaration in enumerate(modern_declarations):
                use_default_names = declaration.name == entry.name
                callable_names = _script_callable_names(
                    declaration.name,
                    use_default_names=use_default_names,
                )
                parameter_declarations = [
                    f"{_sanitize_gdscript_identifier(parameter.name)} = null"
                    for parameter in declaration.parameters
                ]
                constructor_value: str | None = None
                if declaration.is_constructor:
                    constructor_suffix = _sanitize_gdscript_identifier(declaration.name)
                    constructor_value = f"_gm_constructor_{constructor_suffix}"
                    constructor_params = ", ".join(
                        ["_gml_constructor_self = null", *parameter_declarations]
                    )
                    function_prefix = (
                        f"func {callable_names.call_method}({constructor_params}):\n"
                    )
                else:
                    params = ", ".join(parameter_declarations)
                    scoped_params = ", ".join(
                        [
                            f"{_SCRIPT_SELF_PARAMETER} = null",
                            f"{_SCRIPT_OTHER_PARAMETER} = null",
                            *parameter_declarations,
                        ]
                    )
                    function_prefix = (
                        f"func {callable_names.call_method}({params}):\n"
                        f"{_script_forward_call(declaration=declaration, scoped_call_method=callable_names.scoped_call_method)}\n"
                        f"func {callable_names.scoped_call_method}({scoped_params}):\n"
                    )
                body, source_map, static_scope_id = self._modern_function_body(
                    declaration,
                    source_path=source_path,
                    asset_names=asset_names,
                    static_scope_prefix=f"{entry.name}.{declaration.name}",
                    extension_functions=extension_functions,
                    extension_function_mappings=extension_function_mappings,
                    enum_values=enum_values,
                    macro_values=macro_values,
                    generated_line_offset=("".join(chunks) + function_prefix).count("\n"),
                )
                if declaration.is_constructor:
                    assert constructor_value is not None
                    constructor_scope_id = (
                        static_scope_id
                        or f"{entry.name}.{declaration.name}:constructor"
                    )
                    chunks.append(
                        function_prefix
                        + f"{body}\n"
                        + "\treturn GMRuntime.gml_undefined()\n\n"
                        + f"func {callable_names.callable_accessor}():\n"
                        + f"\tvar {constructor_value} = GMRuntime.gml_constructor(\n"
                        + "\t\tself,\n"
                        + "\t\tGMRuntime.gml_static_bind(\n"
                        + f'\t\t\tCallable(self, "{callable_names.call_method}"),\n'
                        + f"\t\t\t{json.dumps(constructor_scope_id)},\n"
                        + f"\t\t\t{json.dumps(declaration.name)}\n"
                        + "\t\t)\n"
                        + "\t)\n"
                        + f"\treturn {constructor_value}\n\n"
                        + f"func {callable_names.scoped_callable_accessor}():\n"
                        + f"\treturn {callable_names.callable_accessor}()\n\n"
                    )
                else:
                    chunks.append(
                        function_prefix
                        + f"{body}\n"
                        + "\treturn GMRuntime.gml_undefined()\n\n"
                        + f"func {callable_names.callable_accessor}():\n"
                        + f'\treturn GMRuntime.gml_method(self, Callable(self, "{callable_names.call_method}"))\n\n'
                        + f"func {callable_names.scoped_callable_accessor}():\n"
                        + f'\treturn GMRuntime.gml_method(self, Callable(self, "{callable_names.scoped_call_method}"))\n\n'
                    )
                script_entry = script_entries_by_name.get(declaration.name)
                registry_entries.append(
                    ScriptRegistryEntry(
                        id=script_entry.id if script_entry is not None else f"{entry.name}:{declaration.name}",
                        name=declaration.name,
                        resource_path=entry.godot_path,
                        legacy_arguments=False,
                        callable_method=callable_names.callable_accessor,
                        scoped_callable_method=callable_names.scoped_callable_accessor,
                        is_constructor=declaration.is_constructor,
                        initializer_method=(
                            "gm2godot_initialize_top_level"
                            if declaration_index == 0
                            and modern_structure.top_level_statements
                            else None
                        ),
                    )
                )
                source_maps.append(source_map)
            if modern_structure.top_level_statements:
                initializer_prefix = "func gm2godot_initialize_top_level():\n"
                initializer_result = transpile_gml_code_with_source_map(
                    render_script_top_level_source(
                        source,
                        modern_structure.top_level_statements,
                    ),
                    indent="\t",
                    top_level_global_scope=True,
                    asset_names=asset_names,
                    static_scope_prefix=f"{entry.name}.top_level",
                    enum_values=enum_values,
                    macro_values=macro_values,
                    extension_functions=extension_functions,
                    extension_function_mappings=extension_function_mappings,
                    macro_configuration=self.macro_configuration,
                    source_path=source_path,
                    event=f"script:{entry.name}:top-level",
                    self_expression="self",
                    other_expression="self",
                    instance_target="self",
                    generated_line_offset=(
                        "".join(chunks) + initializer_prefix
                    ).count("\n"),
                )
                chunks.append(
                    initializer_prefix
                    + initializer_result.code.rstrip("\n")
                    + "\n"
                )
                source_maps.append(initializer_result.source_map)
            return "".join(chunks).rstrip("\n") + "\n", tuple(registry_entries), tuple(source_maps)

        prefix = (
            "extends RefCounted\n\n"
            f"{header}"
            'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
            "func _gm_script_call():\n"
            "\treturn _gm_script_call_scoped(self, self)\n\n"
            f"func _gm_script_call_scoped({_SCRIPT_SELF_PARAMETER} = null, {_SCRIPT_OTHER_PARAMETER} = null):\n"
        )
        script_scope = _script_scope_context()
        result = transpile_gml_code_with_source_map(
            source,
            return_depth=1,
            asset_names=asset_names,
            static_scope_prefix=f"{entry.name}.script",
            self_expression=script_scope.self_expression,
            other_expression=script_scope.other_expression,
            instance_target=script_scope.instance_target,
            enum_values=enum_values,
            macro_values=macro_values,
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
            macro_configuration=self.macro_configuration,
            source_path=source_path,
            event=f"script:{entry.name}",
            preserve_source_comments=True,
            generated_line_offset=prefix.count("\n") + len(_script_scope_lines()),
        )
        return (
            prefix
            + "\n".join(_script_scope_lines())
            + "\n"
            + f"{result.code}\n"
            + "\treturn GMRuntime.gml_undefined()\n\n"
            + "func gm2godot_callable():\n"
            + '\treturn GMRuntime.gml_method(self, Callable(self, "_gm_script_call"))\n\n'
            + "func gm2godot_scoped_callable():\n"
            + '\treturn GMRuntime.gml_method(self, Callable(self, "_gm_script_call_scoped"))\n',
            (
                ScriptRegistryEntry(
                    id=entry.id,
                    name=entry.name,
                    resource_path=entry.godot_path,
                    legacy_arguments=True,
                ),
            ),
            (result.source_map,),
        )

    def _record_source_diagnostics(
        self, source: str, source_path: str, entry: AssetRegistryEntry
    ) -> None:
        if self.diagnostics is None:
            return
        for diagnostic in analyze_gml_source_identifiers(source):
            self.diagnostics.add(
                diagnostic.severity,
                diagnostic.code,
                diagnostic.message,
                source_path=source_path,
                line=diagnostic.line,
                column=diagnostic.column,
                resource=entry.name,
                resource_type="script",
                workaround=(
                    f"Rename '{diagnostic.identifier}'"
                    + (
                        f" to '{diagnostic.suggested_name}'"
                        if diagnostic.suggested_name
                        else ""
                    )
                    + " before conversion."
                ),
            )

    def _write_script(
        self,
        entry: AssetRegistryEntry,
        *,
        asset_names: set[str],
        script_entries_by_name: dict[str, AssetRegistryEntry],
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
        enum_values: Mapping[str, Mapping[str, int]],
        macro_values: Mapping[str, str],
    ) -> tuple[ScriptRegistryEntry, ...]:
        source_path = self._source_gml_path(entry)
        output_path = self._output_path(entry)
        if source_path is None or output_path is None:
            return ()
        try:
            with open(source_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            self._record_source_diagnostics(source, source_path, entry)
            script_content, registry_entries, source_maps = self._render_script(
                entry,
                source,
                source_path=source_path,
                asset_names=asset_names,
                script_entries_by_name=script_entries_by_name,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
                enum_values=enum_values,
                macro_values=macro_values,
            )
        except (OSError, GMLTranspileError) as exc:
            message = get_localized("Console_Convertor_Scripts_ParseError").format(
                script_name=entry.name,
                error=str(exc),
            )
            if self.diagnostics is not None:
                if isinstance(exc, GMLTranspileError):
                    self.diagnostics.add_transpile_failure(
                        message,
                        source_path=source_path,
                        line=exc.line,
                        column=exc.column,
                        resource=entry.name,
                        resource_type="script",
                        workaround="Split or rewrite unsupported GML for this script, or add the missing runtime/API support tracked by the linked issue.",
                    )
                else:
                    self.diagnostics.add(
                        "warning",
                        "GM2GD-SCRIPT-READ",
                        message,
                        source_path=source_path,
                        resource=entry.name,
                        resource_type="script",
                    )
            self._safe_log(message)
            return ()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(script_content)
        write_gml_source_map(
            output_path,
            merge_gml_source_maps(source_maps, source_path=source_path, event=f"script:{entry.name}"),
        )
        return registry_entries

    def _extension_functions(self) -> dict[str, GMLExtensionFunction]:
        index = GameMakerResourceIndex(
            self.gm_project_path,
            self.godot_project_path,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=self.conversion_running,
            diagnostics=self.diagnostics,
        ).build()
        return {
            name: GMLExtensionFunction(
                name=function.function_name,
                extension_name=function.extension_name,
                min_args=function.arg_count,
                max_args=function.arg_count,
            )
            for name, function in index.get_extension_functions().items()
        }

    def _extension_function_mappings(self) -> dict[str, GMLExtensionFunctionMapping]:
        mapping_source = self._resolve_project_source(
            EXTENSION_FUNCTION_MAPPING_FILENAME,
            resource_type="script",
            field="extension function mapping",
        )
        if mapping_source is None or not os.path.isfile(mapping_source.filesystem_path):
            return {}
        try:
            return load_gml_extension_function_mappings(mapping_source.filesystem_path)
        except (OSError, ValueError, TypeError) as exc:
            self._safe_log(
                f"Warning: Could not load {EXTENSION_FUNCTION_MAPPING_FILENAME}: {exc}"
            )
            return {}

    def convert_scripts(self) -> str | None:
        if not self.conversion_running():
            return None

        all_entries = self._registry_entries()
        entries = tuple(
            entry
            for entry in all_entries
            if entry.asset_type == "script" and not _is_script_function_entry(entry)
        )
        declared_resources = self._declared_script_resources()
        entries_by_name = {entry.name: entry for entry in entries}
        requested_names = dict.fromkeys(
            (
                resource.name
                for resource in declared_resources
            )
            if declared_resources is not None
            else ()
        )
        requested_names.update(dict.fromkeys(entries_by_name))
        for script_name in requested_names:
            self._resource_requested(script_name)
        if declared_resources is not None:
            for resource in declared_resources:
                if resource.name in entries_by_name:
                    continue
                self._report_unavailable_declared_script(resource)
                self._resource_skipped(resource.name)
        if not entries:
            self.log_callback(get_localized("Console_Convertor_Scripts_Complete"))
            return None
        if not self.conversion_running():
            self.log_callback(get_localized("Console_Convertor_Scripts_Stopped"))
            return None

        write_gml_runtime(self.godot_project_path)
        os.makedirs(self.godot_scripts_path, exist_ok=True)
        asset_names = {entry.name for entry in all_entries}
        script_entries_by_name = {
            entry.name: entry
            for entry in all_entries
            if entry.asset_type == "script"
        }
        extension_functions = self._extension_functions()
        extension_function_mappings = self._extension_function_mappings()
        enum_values = collect_project_enum_values(
            self.gm_project_path,
            macro_configuration=self.macro_configuration,
        )
        macro_values = collect_project_macro_values(
            self.gm_project_path,
            macro_configuration=self.macro_configuration,
        )
        registry_entries: list[ScriptRegistryEntry] = []
        successful_script_names: list[str] = []
        total = len(entries)

        for index, entry in enumerate(entries, start=1):
            if not self.conversion_running():
                self.log_callback(get_localized("Console_Convertor_Scripts_Stopped"))
                return None
            self._resource_started(entry.name)
            try:
                converted_registry_entries = self._write_script(
                    entry,
                    asset_names=asset_names,
                    script_entries_by_name=script_entries_by_name,
                    extension_functions=extension_functions,
                    extension_function_mappings=extension_function_mappings,
                    enum_values=enum_values,
                    macro_values=macro_values,
                )
            except Exception:
                self._resource_failed(entry.name)
                raise
            if converted_registry_entries:
                successful_script_names.append(entry.name)
                registry_entries.extend(converted_registry_entries)
                self._safe_log(
                    get_localized("Console_Convertor_Scripts_Converted").format(script_name=entry.name)
                )
            else:
                self._resource_skipped(entry.name)
            self._safe_progress(int(index / total * 100))

        registry_path = os.path.join(self.godot_project_path, SCRIPT_REGISTRY_RELATIVE_PATH)
        self._atomic_write_text(
            registry_path,
            render_script_registry_script(registry_entries),
        )
        for script_name in successful_script_names:
            self._resource_completed(script_name)

        self.log_callback(get_localized("Console_Convertor_Scripts_Complete"))
        return registry_path

    @staticmethod
    def _atomic_write_text(output_path: str, content: str) -> None:
        """Publish generated UTF-8 text without exposing a partial file."""
        output_directory = os.path.dirname(output_path) or os.curdir
        os.makedirs(output_directory, exist_ok=True)
        file_descriptor, staged_path = tempfile.mkstemp(
            dir=output_directory,
            prefix=f".{os.path.basename(output_path)}.",
            suffix=".tmp",
        )
        staged_pending = True
        try:
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
                newline="",
            ) as staged_file:
                file_descriptor = -1
                staged_file.write(content)
                staged_file.flush()
                os.fsync(staged_file.fileno())
            os.replace(staged_path, output_path)
            staged_pending = False
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if staged_pending:
                try:
                    os.unlink(staged_path)
                except FileNotFoundError:
                    pass

    def convert_all(self) -> str | None:
        self._reset_resource_outcomes()
        return self.convert_scripts()


__all__ = [
    "SCRIPT_REGISTRY_RELATIVE_PATH",
    "SCRIPT_REGISTRY_RESOURCE_PATH",
    "ScriptConverter",
    "ScriptRegistryEntry",
    "render_script_registry_script",
]
