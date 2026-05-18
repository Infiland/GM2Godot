# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable

from src.localization import get_localized
from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.base_converter import BaseConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import (
    EXTENSION_FUNCTION_MAPPING_FILENAME,
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    load_gml_extension_function_mappings,
    transpile_gml_code,
    transpile_gml_expression,
)
from src.conversion.resource_index import GameMakerResourceIndex
from src.conversion.gml_transpiler_parts.identifiers import (
    _sanitize_gdscript_identifier,
    _validate_gml_identifier,
)
from src.conversion.gml_transpiler_parts.utils import (
    _split_assignment,
    _split_top_level,
    _strip_comments,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath


SCRIPT_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_script_registry.gd")
SCRIPT_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_script_registry.gd"


@dataclass(frozen=True)
class ScriptRegistryEntry:
    id: int
    name: str
    resource_path: str
    legacy_arguments: bool


@dataclass(frozen=True)
class _ScriptFunctionParameter:
    name: str
    default: str | None


@dataclass(frozen=True)
class _ScriptFunctionDeclaration:
    name: str
    parameters: tuple[_ScriptFunctionParameter, ...]
    body: str


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
                f"\t\t\t\"id\": {entry.id},\n",
                f"\t\t\t\"name\": {json.dumps(entry.name)},\n",
                f"\t\t\t\"callable\": preload({json.dumps(entry.resource_path)}).new().gm2godot_callable(),\n",
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
        )
        self.godot_scripts_path = os.path.join(self.godot_project_path, "scripts")

    def _asset_entries(self) -> tuple[AssetRegistryEntry, ...]:
        registry_converter = AssetRegistryConverter(
            self.gm_project_path,
            self.godot_project_path,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=self.conversion_running,
        )
        return tuple(
            entry
            for entry in registry_converter.build_entries()
            if entry.asset_type == "script"
        )

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

    def _modern_function_declaration(self, source: str) -> _ScriptFunctionDeclaration | None:
        candidate = _strip_comments(source).strip()
        while candidate.endswith(";"):
            candidate = candidate[:-1].rstrip()
        match = re.match(r"^function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", candidate)
        if match is None:
            return None
        params_start = candidate.find("(", match.start())
        params_end = self._find_matching(candidate, params_start, "(", ")")
        if params_end is None:
            return None
        body_start = candidate.find("{", params_end + 1)
        if body_start == -1 or candidate[params_end + 1:body_start].strip():
            return None
        body_end = self._find_matching(candidate, body_start, "{", "}")
        if body_end is None or candidate[body_end + 1:].strip():
            return None
        try:
            parameters = self._parse_function_parameters(candidate[params_start + 1:params_end])
        except GMLTranspileError:
            return None
        return _ScriptFunctionDeclaration(
            name=match.group(1),
            parameters=parameters,
            body=candidate[body_start + 1:body_end],
        )

    def _find_matching(self, source: str, start: int, opener: str, closer: str) -> int | None:
        if start < 0 or start >= len(source) or source[start] != opener:
            return None
        depth = 0
        index = start
        quote: str | None = None
        while index < len(source):
            char = source[index]
            if quote is not None:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in ("'", '"'):
                quote = char
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    def _parse_function_parameters(self, params_text: str) -> tuple[_ScriptFunctionParameter, ...]:
        if not params_text.strip():
            return ()
        parameters: list[_ScriptFunctionParameter] = []
        for raw_param in _split_top_level(params_text, ","):
            raw_param = raw_param.strip()
            if not raw_param:
                continue
            assignment = _split_assignment(raw_param)
            if assignment is None:
                name = raw_param
                default = None
            else:
                name, operator, default = assignment
                if operator != "=":
                    raise GMLTranspileError("Script function parameters only support simple defaults")
            name = name.strip()
            _validate_gml_identifier(name)
            parameters.append(
                _ScriptFunctionParameter(
                    name=name,
                    default=default.strip() if default is not None else None,
                )
            )
        return tuple(parameters)

    def _modern_function_body(
        self,
        declaration: _ScriptFunctionDeclaration,
        *,
        asset_names: set[str],
        static_scope_prefix: str,
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
    ) -> str:
        local_names = {parameter.name for parameter in declaration.parameters}
        lines: list[str] = []
        for parameter in declaration.parameters:
            parameter_name = _sanitize_gdscript_identifier(parameter.name)
            if parameter.default is None:
                lines.append(f"\tif {parameter_name} == null: {parameter_name} = GMRuntime.gml_undefined()")
                continue
            default_value = transpile_gml_expression(
                parameter.default,
                local_names=local_names,
                asset_names=asset_names,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            lines.append(
                f"\tif {parameter_name} == null or GMRuntime.is_undefined({parameter_name}): "
                f"{parameter_name} = {default_value}"
            )
        body = transpile_gml_code(
            declaration.body,
            return_depth=1,
            asset_names=asset_names,
            static_scope_prefix=static_scope_prefix,
            local_names=local_names,
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
        )
        lines.append(body)
        return "\n".join(lines)

    def _render_script(
        self,
        entry: AssetRegistryEntry,
        source: str,
        *,
        asset_names: set[str],
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
    ) -> tuple[str, bool]:
        modern_declaration = self._modern_function_declaration(source)
        if modern_declaration is not None:
            params = ", ".join(
                f"{_sanitize_gdscript_identifier(parameter.name)} = null"
                for parameter in modern_declaration.parameters
            )
            body = self._modern_function_body(
                modern_declaration,
                asset_names=asset_names,
                static_scope_prefix=f"{entry.name}.{modern_declaration.name}",
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            return (
                "extends RefCounted\n\n"
                'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
                f"func _gm_script_call({params}):\n"
                f"{body}\n"
                "\treturn GMRuntime.gml_undefined()\n\n"
                "func gm2godot_callable():\n"
                '\treturn GMRuntime.gml_method(self, Callable(self, "_gm_script_call"))\n',
                False,
            )

        body = transpile_gml_code(
            source,
            return_depth=1,
            asset_names=asset_names,
            static_scope_prefix=f"{entry.name}.script",
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
        )
        return (
            "extends RefCounted\n\n"
            'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
            "func _gm_script_call():\n"
            f"{body}\n"
            "\treturn GMRuntime.gml_undefined()\n\n"
            "func gm2godot_callable():\n"
            '\treturn GMRuntime.gml_method(self, Callable(self, "_gm_script_call"))\n',
            True,
        )

    def _write_script(
        self,
        entry: AssetRegistryEntry,
        *,
        asset_names: set[str],
        extension_functions: dict[str, GMLExtensionFunction],
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping],
    ) -> ScriptRegistryEntry | None:
        source_path = self._source_gml_path(entry)
        output_path = self._output_path(entry)
        if source_path is None or output_path is None:
            return None
        try:
            with open(source_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            script_content, legacy_arguments = self._render_script(
                entry,
                source,
                asset_names=asset_names,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
        except (OSError, GMLTranspileError) as exc:
            self._safe_log(
                get_localized("Console_Convertor_Scripts_ParseError").format(
                    script_name=entry.name,
                    error=str(exc),
                )
            )
            return None

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(script_content)
        return ScriptRegistryEntry(
            id=entry.id,
            name=entry.name,
            resource_path=entry.godot_path,
            legacy_arguments=legacy_arguments,
        )

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

        entries = self._asset_entries()
        if not entries:
            self.log_callback(get_localized("Console_Convertor_Scripts_Complete"))
            return None

        write_gml_runtime(self.godot_project_path)
        os.makedirs(self.godot_scripts_path, exist_ok=True)
        asset_names = {entry.name for entry in entries}
        extension_functions = self._extension_functions()
        extension_function_mappings = self._extension_function_mappings()
        registry_entries: list[ScriptRegistryEntry] = []
        total = len(entries)

        for index, entry in enumerate(entries, start=1):
            if not self.conversion_running():
                self.log_callback(get_localized("Console_Convertor_Scripts_Stopped"))
                return None
            registry_entry = self._write_script(
                entry,
                asset_names=asset_names,
                extension_functions=extension_functions,
                extension_function_mappings=extension_function_mappings,
            )
            if registry_entry is not None:
                registry_entries.append(registry_entry)
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
