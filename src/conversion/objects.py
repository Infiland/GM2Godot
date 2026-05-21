import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Mapping
from typing import TypedDict, cast

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.events.base import EventMapping
from src.conversion.event_mapping import map_event
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import GMLTranspileError, transpile_gml_code
from src.conversion.script_generator import ObjectRuntimeConfig, SpriteRuntimeConfig, generate_script_content
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


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


class ObjectConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_objects_path = os.path.join(self.godot_project_path, 'objects')

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
                path = cast(str, res_id.get('path', ''))
                if path.startswith('objects/'):
                    name = cast(str, res_id.get('name', ''))
                    yy_path = os.path.join(self.gm_project_path, 'objects', name, name + '.yy')
                    valid_objects[name] = self._get_subfolder_from_yy(yy_path)

            return valid_objects
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_YYPFilterWarning"))
            return None

    def _get_project_asset_names(self) -> set[str]:
        """Return GameMaker resource names that can collide with unscoped GML identifiers."""
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
                return asset_names
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
        return asset_names

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
        if subfolder:
            return f"res://objects/{subfolder}/{object_name}/{object_name}.gd"
        return f"res://objects/{object_name}/{object_name}.gd"

    def _get_object_subfolder(self, object_name: str) -> str:
        yy_path = os.path.join(self.gm_project_path, 'objects', object_name, object_name + '.yy')
        return self._get_subfolder_from_yy(yy_path)

    def _get_sprite_subfolder(self, sprite_name: str) -> str:
        """Resolve a sprite's subfolder by reading its .yy file from the GM project."""
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        return self._get_subfolder_from_yy(yy_path)

    def _sprite_scene_exists(self, sprite_name: str, sprite_subfolder: str = "") -> bool:
        """Check whether the converted sprite scene exists in the Godot project."""
        if sprite_subfolder:
            tscn_path = os.path.join(self.godot_project_path, 'sprites', sprite_subfolder, sprite_name, sprite_name + '.tscn')
        else:
            tscn_path = os.path.join(self.godot_project_path, 'sprites', sprite_name, sprite_name + '.tscn')
        return os.path.isfile(tscn_path)

    def _get_available_sprite_scene_paths(self) -> dict[str, str]:
        """Return sprite resource names mapped to converted Godot scene paths."""
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

    def _generate_object_scene(self, object_name: str, sprite_name: str | None,
                               sprite_subfolder: str = "", script_res_path: str | None = None) -> str:
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
            if sprite_subfolder:
                sprite_path = f"res://sprites/{sprite_subfolder}/{sprite_name}/{sprite_name}.tscn"
            else:
                sprite_path = f"res://sprites/{sprite_name}/{sprite_name}.tscn"
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
    ) -> tuple[dict[str, str], set[str]]:
        code_bodies: dict[str, str] = {}
        instance_variables: set[str] = set()
        inherited_functions = inherited_event_functions or set()
        object_dir = os.path.join(self.gm_project_path, 'objects', object_name)

        for event in event_list or []:
            mapping = map_event(event)
            if mapping is None or not mapping.gml_filename:
                continue

            source_path = os.path.join(object_dir, mapping.gml_filename)
            if not os.path.isfile(source_path):
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
            try:
                code_bodies[mapping.godot_func] = transpile_gml_code(
                    source,
                    instance_variables=instance_variables,
                    inherited_event_call=inherited_event_call,
                    asset_names=asset_names,
                    static_scope_prefix=f"{object_name}.{mapping.godot_func}",
                )
            except GMLTranspileError as exc:
                message = (
                    "Warning: Could not transpile GameMaker event code for "
                    f"{object_name}/{mapping.gml_filename}: {exc}"
                )
                if self.diagnostics is not None:
                    self.diagnostics.add_transpile_failure(
                        message,
                        source_path=source_path,
                        resource=object_name,
                        resource_type="object",
                        event=mapping.godot_func,
                        workaround="Split or rewrite unsupported GML for this event, or add the missing runtime/API support tracked by the linked issue.",
                    )
                self._safe_log(message)

        return code_bodies, instance_variables

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
            mapping = map_event(event)
            if mapping is not None:
                function_names.add(mapping.godot_func)
        return function_names

    def _event_function_names(self, event_list: list[JsonDict]) -> set[str]:
        function_names: set[str] = set()
        for event in event_list:
            mapping = map_event(event)
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

    def _process_object(
        self,
        object_name: str,
        subfolder: str = "",
        sprite_scene_paths: Mapping[str, str] | None = None,
        asset_names: set[str] | None = None,
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
        sprite_subfolder = ""
        parent_script_res_path = None
        inherited_event_functions: set[str] = set()

        if parent_object_name is not None and parent_object_name != object_name:
            parent_subfolder = self._get_object_subfolder(parent_object_name)
            parent_script_res_path = self._object_script_res_path(parent_object_name, parent_subfolder)
            inherited_event_functions = self._parent_event_function_names(parent_object_name)
        local_event_functions = self._event_function_names(event_list)

        if sprite_name is not None:
            sprite_subfolder = self._get_sprite_subfolder(sprite_name)
            if not self._sprite_scene_exists(sprite_name, sprite_subfolder):
                self._safe_log(get_localized("Console_Convertor_Objects_SpriteNotFound").format(
                    object_name=object_name, sprite_name=sprite_name))
                sprite_name = None

        if subfolder:
            object_dir = os.path.join(self.godot_objects_path, subfolder, object_name)
        else:
            object_dir = os.path.join(self.godot_objects_path, object_name)
        script_res_path = self._object_script_res_path(object_name, subfolder)

        code_bodies, instance_variables = self._load_event_code_bodies(
            object_name,
            event_list,
            inherited_event_functions=inherited_event_functions,
            asset_names=asset_names,
        )
        script_content = generate_script_content(
            event_list,
            code_bodies=code_bodies,
            instance_variables=instance_variables,
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name=sprite_name,
                sprite_scene_paths=sprite_scene_paths,
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
        scene_content = self._generate_object_scene(object_name, sprite_name, sprite_subfolder, script_res_path)

        os.makedirs(object_dir, exist_ok=True)

        tscn_path = os.path.join(object_dir, f"{object_name}.tscn")
        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(scene_content)

        gd_path = os.path.join(object_dir, f"{object_name}.gd")
        with open(gd_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        return {"success": True, "name": object_name, "has_sprite": sprite_name is not None,
                "sprite_name": sprite_name, "event_count": len(event_list)}

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
        sprite_scene_paths = self._get_available_sprite_scene_paths()
        asset_names = self._get_project_asset_names()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(
                    self._process_object,
                    name,
                    object_subfolders.get(name, ""),
                    sprite_scene_paths,
                    asset_names,
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
