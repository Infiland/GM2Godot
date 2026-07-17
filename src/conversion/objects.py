# pyright: reportPrivateUsage=false
import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from src.localization import get_localized
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.asset_output_paths import (
    build_asset_output_paths,
    resource_filesystem_path,
    resource_sibling_path,
)
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.events.base import EventMapping
from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.generated_paths import (
    generated_nested_resource_path,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import (
    GMLSourceMap,
    GMLTranspileError,
    analyze_gml_source_identifiers,
    merge_gml_source_maps,
    transpile_gml_code_with_source_map,
    write_gml_source_map,
)
from src.conversion.gml_transpiler_parts.constants import (
    _ASSIGNMENT_OPERATORS,
    _BUILTIN_GLOBAL_VARIABLES,
    _BUILTIN_INSTANCE_VARIABLES,
    _GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS,
    _GML_LITERAL_IDENTIFIERS,
)
from src.conversion.gml_transpiler_parts.preprocessor import preprocess_gml_source
from src.conversion.gml_transpiler_parts.model import _Token
from src.conversion.gml_transpiler_parts.tokens import _tokenize
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    project_gml_source_paths,
    resolve_project_source_path,
)
from src.conversion.project_enums import collect_project_enum_values
from src.conversion.project_macros import collect_project_macro_values
from src.conversion.script_generator import (
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    _valid_instance_variables,
    generate_script_content,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath

_SPRITE_RUNTIME_IDENTIFIER_RE = re.compile(
    r"\b(?:sprite_index|image_(?:alpha|angle|blend|index|number|speed|xscale|yscale))\b"
)
_SCRIPT_ASSIGNMENT_OPERATORS = frozenset(_ASSIGNMENT_OPERATORS) | frozenset({"++", "--"})
_SCRIPT_ASSIGNMENT_SKIP_IDENTIFIERS = (
    _BUILTIN_GLOBAL_VARIABLES
    | _BUILTIN_INSTANCE_VARIABLES
    | _GML_LITERAL_IDENTIFIERS
    | frozenset(
        {
            "break",
            "case",
            "catch",
            "continue",
            "default",
            "delete",
            "do",
            "else",
            "enum",
            "exit",
            "finally",
            "for",
            "function",
            "global",
            "globalvar",
            "if",
            "new",
            "repeat",
            "return",
            "self",
            "static",
            "switch",
            "then",
            "throw",
            "try",
            "until",
            "var",
            "while",
            "with",
        }
    )
)


class ParsedObject(TypedDict):
    sprite_name: str | None
    parent_object_name: str | None
    event_list: list[JsonDict]
    solid: bool
    persistent: bool


class ObjectProcessResult(TypedDict):
    success: bool
    name: str
    has_sprite: bool
    sprite_name: str | None
    event_count: int


class ObjectEventSource(TypedDict):
    mapping: EventMapping
    source_path: str
    source: str
    inherited_event_call: str | None


def _event_source_filenames(mapping: EventMapping) -> tuple[str, ...]:
    filenames: list[str] = []
    for filename in (mapping.gml_filename, *mapping.fallback_gml_filenames):
        if filename and filename not in filenames:
            filenames.append(filename)
    return tuple(filenames)


def _line_offset_for_block(script_content: str, block: str) -> int:
    script_lines = script_content.splitlines()
    block_lines = block.splitlines()
    if not block_lines:
        return 0
    for index in range(0, len(script_lines) - len(block_lines) + 1):
        if script_lines[index:index + len(block_lines)] == block_lines:
            return index
    first_line = block_lines[0]
    for index, line in enumerate(script_lines):
        if line == first_line:
            return index
    return 0


def _script_assigned_instance_variable_names(
    source: str,
    *,
    asset_names: set[str],
    macro_configuration: str | None = None,
) -> set[str]:
    try:
        tokens = _tokenize(
            preprocess_gml_source(
                source,
                macro_configuration=macro_configuration,
            ).source
        )
    except GMLTranspileError:
        return set()

    assigned_names: set[str] = set()
    local_names = _script_function_parameter_names(tokens)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "IDENT" and token.value == "var":
            local_names.update(_script_var_declaration_names(tokens, index + 1))
        if token.kind == "IDENT":
            name = token.value
            previous_token = tokens[index - 1] if index > 0 else None
            next_token = tokens[index + 1] if index + 1 < len(tokens) else None
            if (
                name not in local_names
                and name not in asset_names
                and name not in _SCRIPT_ASSIGNMENT_SKIP_IDENTIFIERS
                and (previous_token is None or previous_token.value != ".")
                and _script_identifier_is_assigned(previous_token, next_token)
            ):
                assigned_names.add(name)
        index += 1
    return assigned_names


def _script_identifier_is_assigned(previous_token: _Token | None, next_token: _Token | None) -> bool:
    previous_value = previous_token.value if previous_token is not None else None
    next_value = next_token.value if next_token is not None else None
    return (
        next_value in _SCRIPT_ASSIGNMENT_OPERATORS
        or previous_value in {"++", "--"}
    )


def _script_var_declaration_names(tokens: Sequence[_Token], start: int) -> set[str]:
    names: set[str] = set()
    index = start
    depth = 0
    expect_name = True
    while index < len(tokens):
        token = tokens[index]
        value = token.value
        kind = token.kind
        if kind == "EOF":
            break
        if depth == 0 and value in {";", "\n"}:
            break
        if expect_name:
            if kind == "IDENT":
                names.add(str(value))
                expect_name = False
            index += 1
            continue
        if value in {"(", "[", "{"}:
            depth += 1
        elif value in {")", "]", "}"}:
            if depth <= 0:
                break
            depth -= 1
        elif depth == 0 and value == ",":
            expect_name = True
        index += 1
    return names


def _script_function_parameter_names(tokens: Sequence[_Token]) -> set[str]:
    names: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "IDENT" and token.value == "function":
            open_index = _next_token_value_index(tokens, index + 1, "(")
            if open_index is not None:
                close_index = _matching_token_index(tokens, open_index, "(", ")")
                for parameter_index in range(open_index + 1, close_index):
                    parameter = tokens[parameter_index]
                    if parameter.kind == "IDENT":
                        names.add(parameter.value)
                index = close_index
        index += 1
    return names


def _next_token_value_index(tokens: Sequence[_Token], start: int, value: str) -> int | None:
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.kind == "EOF":
            return None
        if token.value == value:
            return index
    return None


def _matching_token_index(tokens: Sequence[_Token], open_index: int, open_value: str, close_value: str) -> int:
    depth = 0
    for index in range(open_index, len(tokens)):
        value = tokens[index].value
        if value == open_value:
            depth += 1
        elif value == close_value:
            depth -= 1
            if depth == 0:
                return index
    return max(open_index, len(tokens) - 1)


class ObjectConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None,
                 macro_configuration: str | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_objects_path = os.path.join(self.godot_project_path, 'objects')
        self.macro_configuration = macro_configuration
        self._project_asset_names_cache: set[str] | None = None
        self._project_script_instance_variables_cache: set[str] | None = None
        self._project_enum_values_cache: dict[str, dict[str, int]] | None = None
        self._project_macro_values_cache: dict[str, str] | None = None
        self._asset_output_paths: dict[str, dict[str, str]] = {}

    def _get_valid_object_names(self) -> dict[str, str] | None:
        """Parse the .yyp project file and return a dict of object name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all objects on disk.
        """
        try:
            yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
            if not yyp_files:
                return None

            yyp_path = os.path.join(self.gm_project_path, yyp_files[0])
            with open(yyp_path, 'r', encoding='utf-8') as f:
                content = f.read()

            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

            valid_objects: dict[str, str] = {}
            for resource in cast(list[JsonDict], data.get('resources', [])):
                res_id = cast(JsonDict, resource.get('id', {}))
                raw_path = res_id.get('path', '')
                if not isinstance(raw_path, str):
                    continue
                path = raw_path.replace('\\', '/')
                if path.startswith('objects/'):
                    raw_name = res_id.get('name', '')
                    name = (
                        raw_name
                        if isinstance(raw_name, str) and raw_name
                        else os.path.splitext(os.path.basename(path))[0]
                    )
                    if not name:
                        continue
                    try:
                        resolved_path = resolve_project_source_path(
                            self.gm_project_path,
                            path,
                        )
                    except ProjectSourcePathError as exc:
                        self._safe_log(
                            f"Warning: Skipping GameMaker object {name}: {exc}"
                        )
                        continue
                    yy_path = resolved_path.filesystem_path
                    valid_objects[name] = self._get_subfolder_from_yy(yy_path)

            return valid_objects
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_YYPFilterWarning"))
            return None

    def _get_project_asset_names(self) -> set[str]:
        """Return GameMaker resource names that can collide with unscoped GML identifiers."""
        if self._project_asset_names_cache is not None:
            return set(self._project_asset_names_cache)

        try:
            registry_converter = AssetRegistryConverter(
                self.gm_project_path,
                self.godot_project_path,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=self.conversion_running,
                macro_configuration=self.macro_configuration,
            )
            asset_names = {entry.name for entry in registry_converter.build_entries()}
            self._project_asset_names_cache = asset_names
            return set(asset_names)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        try:
            yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
            if yyp_files:
                yyp_path = os.path.join(self.gm_project_path, yyp_files[0])
                with open(yyp_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                cleaned = re.sub(r',\s*([}\]])', r'\1', content)
                data = cast(JsonDict, json.loads(cleaned))

                asset_names: set[str] = set()
                for resource in cast(list[JsonDict], data.get('resources', [])):
                    res_id = cast(JsonDict, resource.get('id', {}))
                    name = res_id.get('name')
                    if isinstance(name, str) and name:
                        asset_names.add(name)
                self._project_asset_names_cache = asset_names
                return set(asset_names)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        asset_names = set()
        for resource_dir in ("objects", "sprites", "sounds", "rooms", "scripts"):
            root = os.path.join(self.gm_project_path, resource_dir)
            if not os.path.isdir(root):
                continue
            try:
                asset_names.update(
                    name
                    for name in os.listdir(root)
                    if os.path.isdir(os.path.join(root, name))
                )
            except OSError:
                continue
        self._project_asset_names_cache = asset_names
        return set(asset_names)

    def _get_project_script_instance_variables(self, asset_names: set[str]) -> set[str]:
        """Return bare script-assigned names that execute in caller instance scope."""
        if self._project_script_instance_variables_cache is not None:
            return set(self._project_script_instance_variables_cache)

        script_instance_variables: set[str] = set()
        for source_path in project_gml_source_paths(self.gm_project_path):
            if not source_path.source_path.casefold().startswith("scripts/"):
                continue
            try:
                with open(
                    source_path.filesystem_path,
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    source = source_file.read()
            except OSError:
                continue
            script_instance_variables.update(
                _script_assigned_instance_variable_names(
                    source,
                    asset_names=asset_names,
                    macro_configuration=self.macro_configuration,
                )
            )
        self._project_script_instance_variables_cache = script_instance_variables
        return set(script_instance_variables)

    def _get_project_enum_values(self) -> dict[str, dict[str, int]]:
        if self._project_enum_values_cache is None:
            self._project_enum_values_cache = collect_project_enum_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return {
            name: dict(members)
            for name, members in self._project_enum_values_cache.items()
        }

    def _get_project_macro_values(self) -> dict[str, str]:
        if self._project_macro_values_cache is None:
            self._project_macro_values_cache = collect_project_macro_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return dict(self._project_macro_values_cache)

    def _parse_object_yy(self, object_name: str) -> ParsedObject | None:
        """Parse an object .yy file and extract the sprite reference and event list.

        Returns a dict with 'sprite_name' (str or None) and 'event_list' (list)
        or None if parsing fails.
        """
        yy_path = os.path.join(self.gm_project_path, 'objects', object_name, object_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

            sprite_id = data.get('spriteId')
            sprite_name: str | None = None
            if isinstance(sprite_id, dict):
                sprite_data = cast(JsonDict, sprite_id)
                sprite_name = cast(str | None, sprite_data.get('name', None))

            event_list = cast(list[JsonDict], data.get('eventList', []))
            parent_object_name = self._parse_parent_object_name(data.get('parentObjectId'))

            return {
                "sprite_name": sprite_name,
                "parent_object_name": parent_object_name,
                "event_list": event_list,
                "solid": bool(data.get("solid", False)),
                "persistent": bool(data.get("persistent", False)),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_ParseError").format(
                yy_path=yy_path, object_name=object_name))
            return None

    def _parse_parent_object_name(self, parent_object_id: object) -> str | None:
        if not isinstance(parent_object_id, dict):
            return None

        parent_data = cast(JsonDict, parent_object_id)
        parent_name = parent_data.get("name")
        if isinstance(parent_name, str) and parent_name:
            return parent_name

        parent_path = parent_data.get("path")
        if not isinstance(parent_path, str):
            return None

        path_parts = parent_path.replace("\\", "/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "objects" and path_parts[1]:
            return path_parts[1]
        return None

    def _object_script_res_path(self, object_name: str, subfolder: str = "") -> str:
        return resource_sibling_path(
            self._object_scene_res_path(object_name, subfolder),
            ".gd",
        )

    def _object_scene_res_path(self, object_name: str, subfolder: str = "") -> str:
        return self._asset_output_paths.get("objects", {}).get(
            object_name,
            generated_nested_resource_path("objects", subfolder, object_name, ".tscn"),
        )

    def _get_object_subfolder(self, object_name: str) -> str:
        yy_path = os.path.join(self.gm_project_path, 'objects', object_name, object_name + '.yy')
        return self._get_subfolder_from_yy(yy_path)

    def _get_sprite_subfolder(self, sprite_name: str) -> str:
        """Resolve a sprite's subfolder by reading its .yy file from the GM project."""
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        return self._get_subfolder_from_yy(yy_path)

    def _sprite_scene_exists(self, sprite_name: str, sprite_subfolder: str = "") -> bool:
        """Check whether the converted sprite scene exists in the Godot project."""
        scene_path = self._asset_output_paths.get("sprites", {}).get(
            sprite_name,
            generated_nested_resource_path("sprites", sprite_subfolder, sprite_name, ".tscn"),
        )
        tscn_path = resource_filesystem_path(self.godot_project_path, scene_path)
        return os.path.isfile(tscn_path)

    def _get_available_sprite_scene_paths(self) -> dict[str, str]:
        """Return sprite resource names mapped to converted Godot scene paths."""
        indexed_paths = {
            name: scene_path
            for name, scene_path in self._asset_output_paths.get("sprites", {}).items()
            if os.path.isfile(resource_filesystem_path(self.godot_project_path, scene_path))
        }
        if indexed_paths:
            return indexed_paths

        sprites_root = os.path.join(self.godot_project_path, 'sprites')
        if not os.path.isdir(sprites_root):
            return {}

        scene_paths: dict[str, str] = {}
        for dirpath, _, filenames in os.walk(sprites_root):
            for filename in filenames:
                if not filename.endswith('.tscn'):
                    continue
                sprite_name = os.path.splitext(filename)[0]
                scene_path = os.path.join(dirpath, filename)
                relative_path = os.path.relpath(scene_path, self.godot_project_path).replace(os.sep, '/')
                scene_paths[sprite_name] = f"res://{relative_path}"
        return scene_paths

    def _generate_object_scene(
        self,
        object_name: str,
        sprite_name: str | None,
        sprite_scene_path: str | None = None,
        script_res_path: str | None = None,
    ) -> str:
        """Build the .tscn content string for an object scene.

        If sprite_name is not None, the scene instances the sprite's scene as a child.
        If script_res_path is not None, the scene attaches the script to the root node.
        """
        has_sprite = sprite_name is not None
        has_script = script_res_path is not None
        ext_resource_count = int(has_sprite) + int(has_script)
        load_steps = ext_resource_count + 1 if ext_resource_count > 0 else 0

        if load_steps > 0:
            parts = [f'[gd_scene format=3 load_steps={load_steps}]\n']
        else:
            parts = ['[gd_scene format=3]\n']

        next_id = 1
        sprite_id = None
        script_id = None

        if has_sprite:
            sprite_id = str(next_id)
            next_id += 1
            sprite_path = sprite_scene_path or generated_nested_resource_path(
                "sprites", "", sprite_name or "sprite", ".tscn"
            )
            parts.append(f'\n[ext_resource type="PackedScene" path="{sprite_path}" id="{sprite_id}"]\n')

        if has_script:
            script_id = str(next_id)
            parts.append(f'\n[ext_resource type="Script" path="{script_res_path}" id="{script_id}"]\n')

        if has_script:
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\nscript = ExtResource("{script_id}")\n')
        else:
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\n')

        if has_sprite:
            parts.append(f'\n[node name="{sprite_name}" parent="." instance=ExtResource("{sprite_id}")]\n')

        return ''.join(parts)

    def _load_event_code_bodies(
        self,
        object_name: str,
        event_list: list[JsonDict],
        inherited_event_functions: set[str] | None = None,
        asset_names: set[str] | None = None,
        project_script_instance_variables: set[str] | None = None,
        direct_instance_variables: set[str] | None = None,
        direct_reference_names: set[str] | None = None,
        enum_values: Mapping[str, Mapping[str, int]] | None = None,
        macro_values: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, str], set[str], dict[str, GMLSourceMap]]:
        code_bodies: dict[str, str] = {}
        source_maps: dict[str, GMLSourceMap] = {}
        instance_variables: set[str] = set(project_script_instance_variables or set())
        inherited_functions = inherited_event_functions or set()
        source_entries: list[ObjectEventSource] = []
        object_dir = os.path.join(self.gm_project_path, 'objects', object_name)
        asset_name_set = set(asset_names or set())

        for event in event_list or []:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is None or not mapping.gml_filename:
                continue

            source_path = self._event_source_path(object_dir, mapping)
            if source_path is None:
                self._record_missing_event_source(object_name, object_dir, mapping)
                continue

            try:
                with open(source_path, 'r', encoding='utf-8') as f:
                    source = f.read()
            except OSError:
                self._safe_log(
                    f"Warning: Could not read GameMaker event code file: {source_path}"
                )
                continue

            if not source.strip():
                continue

            inherited_event_call = (
                self._inherited_event_call(mapping)
                if mapping.godot_func in inherited_functions
                else None
            )
            source_entries.append(
                {
                    "mapping": mapping,
                    "source_path": source_path,
                    "source": source,
                    "inherited_event_call": inherited_event_call,
                }
            )
            instance_variables.update(
                _script_assigned_instance_variable_names(
                    source,
                    asset_names=asset_name_set,
                    macro_configuration=self.macro_configuration,
                )
            )

        direct_names = (
            set(_valid_instance_variables(instance_variables))
            if direct_instance_variables is None
            else set(direct_instance_variables)
        )
        direct_names.update(direct_reference_names or set())
        dynamic_names = (
            set(instance_variables)
            | _GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS
        ) - direct_names

        for entry in source_entries:
            mapping = entry["mapping"]
            source_path = entry["source_path"]
            source = entry["source"]
            try:
                self._record_event_source_diagnostics(
                    source,
                    source_path,
                    object_name,
                    mapping.godot_func,
                )
                result = transpile_gml_code_with_source_map(
                    source,
                    instance_variables=instance_variables,
                    inherited_event_call=entry["inherited_event_call"],
                    macro_configuration=self.macro_configuration,
                    asset_names=asset_names,
                    static_scope_prefix=f"{object_name}.{mapping.godot_func}",
                    source_path=source_path,
                    event=mapping.godot_func,
                    preserve_source_comments=True,
                    instance_target="self",
                    direct_instance_names=direct_names,
                    dynamic_instance_names=dynamic_names,
                    enum_values=enum_values,
                    macro_values=macro_values,
                )
                code_bodies[mapping.godot_func] = result.code
                source_maps[mapping.godot_func] = result.source_map
            except GMLTranspileError as exc:
                message = (
                    "Warning: Could not transpile GameMaker event code for "
                    f"{object_name}/{mapping.gml_filename}: {exc}"
                )
                if self.diagnostics is not None:
                    self.diagnostics.add_transpile_failure(
                        message,
                        source_path=source_path,
                        line=exc.line,
                        column=exc.column,
                        resource=object_name,
                        resource_type="object",
                        event=mapping.godot_func,
                        workaround="Split or rewrite unsupported GML for this event, or add the missing runtime/API support tracked by the linked issue.",
                    )
                self._safe_log(message)

        return code_bodies, instance_variables, source_maps

    def _event_source_path(self, object_dir: str, mapping: EventMapping) -> str | None:
        for filename in _event_source_filenames(mapping):
            source_path = os.path.join(object_dir, filename)
            if os.path.isfile(source_path):
                return source_path
        return None

    def _record_missing_event_source(
        self,
        object_name: str,
        object_dir: str,
        mapping: EventMapping,
    ) -> None:
        if not mapping.gml_filename.startswith("Collision_"):
            return
        filenames = _event_source_filenames(mapping)
        message = (
            "Warning: Missing GameMaker collision event code file for "
            f"{object_name}/{mapping.godot_func}; looked for {', '.join(filenames)}"
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-OBJECT-MISSING-COLLISION-EVENT-SOURCE",
                message,
                source_path=os.path.join(object_dir, filenames[0]) if filenames else object_dir,
                resource=object_name,
                resource_type="object",
                event=mapping.godot_func,
                workaround="Add the missing GameMaker collision event GML file or remove the stale event metadata.",
            )
        with self._lock:
            self.log_callback(message)

    def _record_event_source_diagnostics(
        self,
        source: str,
        source_path: str,
        object_name: str,
        event_name: str,
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
                resource=object_name,
                resource_type="object",
                event=event_name,
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

    def _inherited_event_call(self, mapping: EventMapping) -> str:
        if not mapping.params:
            return f"super.{mapping.godot_func}()"
        return f"super.{mapping.godot_func}({mapping.params})"

    def _parent_event_function_names(self, parent_object_name: str | None) -> set[str]:
        if parent_object_name is None:
            return set()

        parsed_parent = self._parse_object_yy(parent_object_name)
        if parsed_parent is None:
            return set()

        function_names: set[str] = set()
        for event in parsed_parent["event_list"]:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is not None:
                function_names.add(mapping.godot_func)
        return function_names

    def _event_function_names(self, event_list: list[JsonDict]) -> set[str]:
        function_names: set[str] = set()
        for event in event_list:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is not None:
                function_names.add(mapping.godot_func)
        return function_names

    def _parent_object_chain(self, object_name: str, seen: set[str] | None = None) -> tuple[str, ...]:
        seen = set(seen or set())
        if object_name in seen:
            return ()
        seen.add(object_name)

        parsed = self._parse_object_yy(object_name)
        if parsed is None or parsed["parent_object_name"] is None:
            return ()

        parent_name = parsed["parent_object_name"]
        return (parent_name, *self._parent_object_chain(parent_name, seen))

    def _object_inherits_sprite_runtime(self, object_name: str | None, seen: set[str] | None = None) -> bool:
        if object_name is None:
            return False
        seen = set(seen or set())
        if object_name in seen:
            return False
        seen.add(object_name)

        parsed = self._parse_object_yy(object_name)
        if parsed is None:
            return False
        if parsed["sprite_name"] is not None:
            return True
        if self._object_event_code_uses_sprite_runtime(object_name, parsed["event_list"]):
            return True
        return self._object_inherits_sprite_runtime(parsed["parent_object_name"], seen)

    def _object_event_code_uses_sprite_runtime(self, object_name: str, event_list: list[JsonDict]) -> bool:
        object_dir = os.path.join(self.gm_project_path, 'objects', object_name)
        for event in event_list:
            mapping = map_input_event(event) if is_input_event(event) else map_event(event)
            if mapping is None or not mapping.gml_filename:
                continue
            source_path = os.path.join(object_dir, mapping.gml_filename)
            try:
                with open(source_path, 'r', encoding='utf-8') as f:
                    if _SPRITE_RUNTIME_IDENTIFIER_RE.search(f.read()) is not None:
                        return True
            except OSError:
                continue
        return False

    def _process_object(
        self,
        object_name: str,
        subfolder: str = "",
        sprite_scene_paths: Mapping[str, str] | None = None,
        asset_names: set[str] | None = None,
        project_script_instance_variables: set[str] | None = None,
        enum_values: Mapping[str, Mapping[str, int]] | None = None,
        macro_values: Mapping[str, str] | None = None,
    ) -> ObjectProcessResult | None:
        """Process a single object: parse .yy, generate scene and script, write files.

        Returns a result dict or None if conversion was stopped.
        """
        if not self.conversion_running():
            return None

        parsed = self._parse_object_yy(object_name)
        if parsed is None:
            return {"success": False, "name": object_name, "has_sprite": False, "sprite_name": None, "event_count": 0}

        sprite_name = parsed["sprite_name"]
        parent_object_name = parsed["parent_object_name"]
        event_list = parsed["event_list"]
        solid = bool(parsed.get("solid", False))
        persistent = bool(parsed.get("persistent", False))
        sprite_scene_path: str | None = None
        parent_script_res_path = None
        inherited_event_functions: set[str] = set()

        if parent_object_name is not None and parent_object_name != object_name:
            parent_subfolder = self._get_object_subfolder(parent_object_name)
            parent_script_res_path = self._object_script_res_path(parent_object_name, parent_subfolder)
            inherited_event_functions = self._parent_event_function_names(parent_object_name)
        inherited_sprite_runtime = self._object_inherits_sprite_runtime(parent_object_name)
        local_event_functions = self._event_function_names(event_list)

        if sprite_name is not None:
            sprite_scene_path = (sprite_scene_paths or {}).get(sprite_name)
            if sprite_scene_path is None:
                sprite_subfolder = self._get_sprite_subfolder(sprite_name)
                if self._sprite_scene_exists(sprite_name, sprite_subfolder):
                    sprite_scene_path = self._asset_output_paths.get("sprites", {}).get(
                        sprite_name,
                        generated_nested_resource_path(
                            "sprites", sprite_subfolder, sprite_name, ".tscn"
                        ),
                    )
            if sprite_scene_path is None:
                self._safe_log(get_localized("Console_Convertor_Objects_SpriteNotFound").format(
                    object_name=object_name, sprite_name=sprite_name))
                sprite_name = None

        scene_res_path = self._object_scene_res_path(object_name, subfolder)
        tscn_path = resource_filesystem_path(self.godot_project_path, scene_res_path)
        object_dir = os.path.dirname(tscn_path)
        script_res_path = self._object_script_res_path(object_name, subfolder)

        code_bodies, instance_variables, event_source_maps = self._load_event_code_bodies(
            object_name,
            event_list,
            inherited_event_functions=inherited_event_functions,
            asset_names=asset_names,
            project_script_instance_variables=(
                project_script_instance_variables
                if parent_object_name is None
                else None
            ),
            direct_instance_variables=set() if parent_object_name is not None else None,
            direct_reference_names=set(sprite_scene_paths or {}),
            enum_values=enum_values,
            macro_values=macro_values,
        )
        script_content = generate_script_content(
            event_list,
            code_bodies=code_bodies,
            instance_variables=instance_variables if parent_object_name is None else set(),
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name=sprite_name,
                sprite_scene_paths=sprite_scene_paths,
                inherit_runtime=inherited_sprite_runtime,
            ),
            object_runtime=ObjectRuntimeConfig(
                object_name=object_name,
                parent_object_names=self._parent_object_chain(object_name),
                solid=solid,
                persistent=persistent,
                inherit_ready="_ready" in inherited_event_functions and "_ready" not in local_event_functions,
                inherit_exit_tree="_exit_tree" in inherited_event_functions and "_exit_tree" not in local_event_functions,
            ),
            base_script_path=parent_script_res_path,
        )
        scene_content = self._generate_object_scene(
            object_name,
            sprite_name,
            sprite_scene_path,
            script_res_path,
        )

        os.makedirs(object_dir, exist_ok=True)

        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(scene_content)

        gd_path = resource_filesystem_path(self.godot_project_path, script_res_path)
        with open(gd_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        self._write_object_source_map(gd_path, script_content, code_bodies, event_source_maps)

        return {"success": True, "name": object_name, "has_sprite": sprite_name is not None,
                "sprite_name": sprite_name, "event_count": len(event_list)}

    def _write_object_source_map(
        self,
        gd_path: str,
        script_content: str,
        code_bodies: Mapping[str, str],
        source_maps: Mapping[str, GMLSourceMap],
    ) -> None:
        offset_maps: list[GMLSourceMap] = []
        for event_name, source_map in source_maps.items():
            body = code_bodies.get(event_name)
            if not body:
                continue
            offset = _line_offset_for_block(script_content, body)
            offset_maps.append(source_map.with_generated_line_offset(offset))
        if offset_maps:
            write_gml_source_map(gd_path, merge_gml_source_maps(offset_maps))

    def convert_objects(self) -> None:
        os.makedirs(self.godot_objects_path, exist_ok=True)

        gm_objects_path = os.path.join(self.gm_project_path, 'objects')
        if not os.path.isdir(gm_objects_path):
            self.log_callback(get_localized("Console_Convertor_Objects_Error_NotFound"))
            return

        write_gml_runtime(self.godot_project_path)

        object_names = [
            name for name in os.listdir(gm_objects_path)
            if os.path.isdir(os.path.join(gm_objects_path, name))
            and os.path.isfile(os.path.join(gm_objects_path, name, name + '.yy'))
        ]

        valid_names = self._get_valid_object_names()
        object_subfolders = {}
        if valid_names is not None:
            object_names = [name for name in object_names if name in valid_names]
            object_subfolders = {name: valid_names[name] for name in object_names}
        else:
            for name in object_names:
                yy_path = os.path.join(self.gm_project_path, 'objects', name, name + '.yy')
                object_subfolders[name] = self._get_subfolder_from_yy(yy_path)

        if not object_names:
            self.log_callback(get_localized("Console_Convertor_Objects_Complete"))
            return

        total = len(object_names)
        processed = 0
        self._asset_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        )
        sprite_scene_paths = self._get_available_sprite_scene_paths()
        asset_names = self._get_project_asset_names()
        project_script_instance_variables = self._get_project_script_instance_variables(asset_names)
        enum_values = self._get_project_enum_values()
        macro_values = self._get_project_macro_values()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(
                    self._process_object,
                    name,
                    object_subfolders.get(name, ""),
                    sprite_scene_paths,
                    asset_names,
                    project_script_instance_variables,
                    enum_values,
                    macro_values,
                ): name
                for name in object_names
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Objects_Stopped"))
                    return

                processed += 1

                if result["success"]:
                    if self.compact_logging:
                        self._safe_log_progress(result["name"], processed, total)
                    else:
                        if result["has_sprite"]:
                            self._safe_log(get_localized("Console_Convertor_Objects_ConvertedWithSprite").format(
                                object_name=result["name"], sprite_name=result["sprite_name"],
                                event_count=result["event_count"]))
                        else:
                            self._safe_log(get_localized("Console_Convertor_Objects_Converted").format(
                                object_name=result["name"], event_count=result["event_count"]))

                self._safe_progress(int(processed / total * 100))

        self.log_callback(get_localized("Console_Convertor_Objects_Complete"))

    def convert_all(self) -> None:
        self.convert_objects()
