# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable

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
from src.conversion.script_functions import (
    ScriptFunctionDeclaration,
    modern_script_function_declarations,
)
from src.conversion.gml_transpiler_parts.identifiers import (
    _sanitize_gdscript_identifier,
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


@dataclass(frozen=True)
class _ScriptCallableNames:
    call_method: str
    scoped_call_method: str
    callable_accessor: str
    scoped_callable_accessor: str


def _script_scope_context() -> _ScopeContext:
    return _ScopeContext(
        self_expression=_SCRIPT_SELF_PARAMETER,
        other_expression=_SCRIPT_OTHER_PARAMETER,
        instance_target=_SCRIPT_SELF_PARAMETER,
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
    lines = [
        "extends RefCounted\n\n",
        "static func gml_script_registry_entries():\n",
        "\treturn [\n",
    ]
    for entry in entries:
        lines.extend(
            [
                "\t\t{\n",
                f"\t\t\t\"id\": {json.dumps(entry.id)},\n",
                f"\t\t\t\"name\": {json.dumps(entry.name)},\n",
                f"\t\t\t\"callable\": preload({json.dumps(entry.resource_path)}).new().{entry.callable_method}(),\n",
                f"\t\t\t\"scoped_callable\": preload({json.dumps(entry.resource_path)}).new().{entry.scoped_callable_method}(),\n",
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
            conversion_running=self.conversion_running,
        )
        return tuple(registry_converter.build_entries())

    def _asset_entries(self) -> tuple[AssetRegistryEntry, ...]:
        return tuple(entry for entry in self._registry_entries() if entry.asset_type == "script")

    def _source_gml_path(self, entry: AssetRegistryEntry) -> str | None:
        yy_path = os.path.join(self.gm_project_path, entry.source_path)
        script_dir = os.path.dirname(yy_path)
        preferred_path = os.path.join(script_dir, entry.name + ".gml")
        if os.path.isfile(preferred_path):
            return preferred_path
        if not os.path.isdir(script_dir):
            return None
        for filename in sorted(os.listdir(script_dir)):
            if filename.endswith(".gml"):
                return os.path.join(script_dir, filename)
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
        generated_line_offset: int = 0,
    ) -> tuple[str, GMLSourceMap]:
        local_names = {parameter.name for parameter in declaration.parameters}
        script_scope = _script_scope_context()
        lines: list[str] = _script_scope_lines()
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
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            lines.append(
                f"\tif {parameter_name} == null or GMRuntime.is_undefined({parameter_name}): "
                f"{parameter_name} = {default_value}"
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
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
            macro_configuration=self.macro_configuration,
            source_path=source_path,
            event=f"script:{declaration.name}",
            preserve_source_comments=True,
            generated_line_offset=generated_line_offset + len(lines),
        )
        lines.append(result.code)
        return "\n".join(lines), result.source_map

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
    ) -> tuple[str, tuple[ScriptRegistryEntry, ...], tuple[GMLSourceMap, ...]]:
        header = render_gml_source_header(
            source_path=source_path,
            event=f"script:{entry.name}",
            source=source,
        )
        modern_declarations = modern_script_function_declarations(source)
        if modern_declarations is not None:
            chunks = [
                "extends RefCounted\n\n",
                f"{header}",
                'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n',
            ]
            registry_entries: list[ScriptRegistryEntry] = []
            source_maps: list[GMLSourceMap] = []
            for declaration in modern_declarations:
                callable_names = _script_callable_names(
                    declaration.name,
                    use_default_names=declaration.name == entry.name,
                )
                params = ", ".join(
                    f"{_sanitize_gdscript_identifier(parameter.name)} = null"
                    for parameter in declaration.parameters
                )
                scoped_params = ", ".join(
                    [
                        f"{_SCRIPT_SELF_PARAMETER} = null",
                        f"{_SCRIPT_OTHER_PARAMETER} = null",
                        *(
                            f"{_sanitize_gdscript_identifier(parameter.name)} = null"
                            for parameter in declaration.parameters
                        ),
                    ]
                )
                function_prefix = (
                    f"func {callable_names.call_method}({params}):\n"
                    f"{_script_forward_call(declaration=declaration, scoped_call_method=callable_names.scoped_call_method)}\n"
                    f"func {callable_names.scoped_call_method}({scoped_params}):\n"
                )
                body, source_map = self._modern_function_body(
                    declaration,
                    source_path=source_path,
                    asset_names=asset_names,
                    static_scope_prefix=f"{entry.name}.{declaration.name}",
                    extension_functions=extension_functions,
                    extension_function_mappings=extension_function_mappings,
                    generated_line_offset=("".join(chunks) + function_prefix).count("\n"),
                )
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
                    )
                )
                source_maps.append(source_map)
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
        mapping_path = os.path.join(self.gm_project_path, EXTENSION_FUNCTION_MAPPING_FILENAME)
        if not os.path.isfile(mapping_path):
            return {}
        try:
            return load_gml_extension_function_mappings(mapping_path)
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
        if not entries:
            self.log_callback(get_localized("Console_Convertor_Scripts_Complete"))
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
        registry_entries: list[ScriptRegistryEntry] = []
        total = len(entries)

        for index, entry in enumerate(entries, start=1):
            if not self.conversion_running():
                self.log_callback(get_localized("Console_Convertor_Scripts_Stopped"))
                return None
            converted_registry_entries = self._write_script(
                entry,
                asset_names=asset_names,
                script_entries_by_name=script_entries_by_name,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            if converted_registry_entries:
                registry_entries.extend(converted_registry_entries)
                self._safe_log(
                    get_localized("Console_Convertor_Scripts_Converted").format(script_name=entry.name)
                )
            self._safe_progress(int(index / total * 100))

        registry_path = os.path.join(self.godot_project_path, SCRIPT_REGISTRY_RELATIVE_PATH)
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        with open(registry_path, "w", encoding="utf-8") as registry_file:
            registry_file.write(render_script_registry_script(registry_entries))

        self.log_callback(get_localized("Console_Convertor_Scripts_Complete"))
        return registry_path

    def convert_all(self) -> str | None:
        return self.convert_scripts()


__all__ = [
    "SCRIPT_REGISTRY_RELATIVE_PATH",
    "SCRIPT_REGISTRY_RESOURCE_PATH",
    "ScriptConverter",
    "ScriptRegistryEntry",
    "render_script_registry_script",
]
