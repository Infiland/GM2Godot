from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict, cast

from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_transpiler import GMLTranspileError, transpile_gml_code
from src.conversion.project_godot import GodotProjectFile
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.room_creation_code import (
    ROOM_EXECUTION_ORDER,
    instance_creation_order_names,
    resolve_instance_creation_code,
    resolve_room_creation_code,
)
from src.conversion.room_layers import godot_string, serialize_room_layers
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath

ROOM_RUNTIME_SCRIPT_RELATIVE_PATH = os.path.join("gm2godot", "gml_room_node.gd")
ROOM_RUNTIME_SCRIPT_RESOURCE_PATH = "res://gm2godot/gml_room_node.gd"
ROOM_RUNTIME_EXT_RESOURCE_ID = "gm_room_runtime"
ROOM_SCRIPT_BASE_RESOURCE_PATH = "res://gm2godot/gml_room_node.gd"


def render_room_runtime_script() -> str:
    return (
        "extends Node2D\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "func _ready():\n"
        "\tGMRuntime.gml_room_enter_scene(self)\n"
    )


class InstanceCreationCodeMethod(TypedDict):
    source_path: str
    method_name: str
    body: str


def _room_script_resource_path(room: IndexedRoom) -> str:
    if room.godot_path.endswith(".tscn"):
        return room.godot_path[:-5] + ".gd"
    return room.godot_path + ".gd"


def _gdscript_identifier_suffix(value: str, fallback: str) -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_")
    if not identifier:
        identifier = fallback
    if identifier[0].isdigit():
        identifier = "_" + identifier
    return identifier


def _dict_items(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    items: list[JsonDict] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            items.append(cast(JsonDict, item))
    return items


def _layer_resource_type(layer: JsonDict) -> str:
    resource_type = layer.get("resourceType")
    if isinstance(resource_type, str) and resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _instance_name(instance: JsonDict) -> str:
    name = instance.get("%Name") or instance.get("name")
    return name if isinstance(name, str) and name else "Instance"


def _iter_room_instances(layers: object) -> list[JsonDict]:
    instances: list[JsonDict] = []
    for layer in _dict_items(layers):
        if _layer_resource_type(layer) == "GMRInstanceLayer":
            instances.extend(_dict_items(layer.get("instances")))
        instances.extend(_iter_room_instances(layer.get("layers") or layer.get("children")))
    return instances


def _iter_room_effect_layers(layers: object) -> list[JsonDict]:
    effect_layers: list[JsonDict] = []
    for layer in _dict_items(layers):
        if _layer_resource_type(layer) == "GMREffectLayer":
            effect_layers.append(layer)
        effect_layers.extend(_iter_room_effect_layers(layer.get("layers") or layer.get("children")))
    return effect_layers


class RoomProcessResult(TypedDict):
    success: bool
    name: str
    width: object
    height: object
    scene_path: str


class RoomConverter(BaseConverter):
    """Convert GameMaker rooms into minimal Godot room scenes."""

    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                  log_callback: LogCallback = print,
                  progress_callback: ProgressCallback | None = None,
                  conversion_running: ConversionRunning | None = None,
                  update_log_callback: LogCallback | None = None,
                  compact_logging: bool = False,
                  max_workers: int | None = None,
                  resource_index: GameMakerResourceIndex | None = None,
                  diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging,
                         max_workers=max_workers, diagnostics=diagnostics)
        self.godot_rooms_path = os.path.join(self.godot_project_path, "rooms")
        self.resource_index = resource_index

    def _build_resource_index(self) -> GameMakerResourceIndex:
        if self.resource_index is not None:
            return self.resource_index
        return GameMakerResourceIndex(
            self.gm_project_path,
            self.godot_project_path,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            conversion_running=self.conversion_running,
            update_log_callback=self.update_log_callback,
            compact_logging=self.compact_logging,
            max_workers=self.max_workers,
        ).build()

    def _generate_room_scene(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None = None,
        room_script_resource_path: str | None = None,
    ) -> str:
        room_settings = room.room_settings
        physics_settings = room.physics_settings
        room_creation_code = resolve_room_creation_code(
            room,
            self.gm_project_path,
            warn_callback=self._safe_log,
        )
        self._record_effect_layer_diagnostics(room)
        serialized_layers = serialize_room_layers(
            room,
            gm_project_path=self.gm_project_path,
            resource_index=resource_index,
            warn_callback=self._safe_log,
        )

        script_resource_path = room_script_resource_path or ROOM_RUNTIME_SCRIPT_RESOURCE_PATH
        if serialized_layers.ext_resource_lines:
            lines = [
                f"[gd_scene format=3 load_steps={len(serialized_layers.ext_resource_lines) + 2}]",
                "",
                (
                    '[ext_resource type="Script" path="{path}" id="{resource_id}"]'.format(
                        path=script_resource_path,
                        resource_id=ROOM_RUNTIME_EXT_RESOURCE_ID,
                    )
                ),
            ]
            lines.extend(serialized_layers.ext_resource_lines)
            lines.append("")
        else:
            lines = [
                "[gd_scene format=3 load_steps=2]",
                "",
                (
                    '[ext_resource type="Script" path="{path}" id="{resource_id}"]'.format(
                        path=script_resource_path,
                        resource_id=ROOM_RUNTIME_EXT_RESOURCE_ID,
                    )
                ),
                "",
            ]

        lines.extend([
            f'[node name={godot_string(room.name)} type="Node2D"]',
            f'script = ExtResource("{ROOM_RUNTIME_EXT_RESOURCE_ID}")',
            f'metadata/gamemaker_room_width = {json.dumps(room_settings.get("Width", 1024))}',
            f'metadata/gamemaker_room_height = {json.dumps(room_settings.get("Height", 768))}',
            f'metadata/gamemaker_room_persistent = {json.dumps(bool(room_settings.get("persistent", False)))}',
            f'metadata/gamemaker_room_volume = {json.dumps(room.raw_data.get("volume", 1.0))}',
            f'metadata/gamemaker_parent_room = {json.dumps(room.parent_room)}',
            f'metadata/gamemaker_inherit_layers = {json.dumps(room.inherit_layers)}',
            f'metadata/gamemaker_inherit_creation_order = {json.dumps(room.inherit_creation_order)}',
            f'metadata/gamemaker_view_settings = {json.dumps(room.view_settings)}',
            f'metadata/gamemaker_view_count = {json.dumps(len(room.views))}',
            f'metadata/gamemaker_physics_world = {json.dumps(bool(physics_settings.get("PhysicsWorld", False)))}',
            f'metadata/gamemaker_physics_gravity_x = {json.dumps(physics_settings.get("PhysicsWorldGravityX", 0.0))}',
            f'metadata/gamemaker_physics_gravity_y = {json.dumps(physics_settings.get("PhysicsWorldGravityY", 10.0))}',
            f'metadata/gamemaker_physics_pixels_to_meters = {json.dumps(physics_settings.get("PhysicsWorldPixToMetres", 0.1))}',
            f'metadata/gamemaker_source_yy_path = {json.dumps(room.yy_path)}',
            f'metadata/gamemaker_creation_code_file = {json.dumps(room.creation_code_file)}',
            f'metadata/gamemaker_creation_code_source_path = {json.dumps(room_creation_code.source_path)}',
            f'metadata/gamemaker_has_creation_code = {json.dumps(room_creation_code.has_code)}',
            f'metadata/gamemaker_inherit_code = {json.dumps(room_creation_code.inherit_code)}',
            f'metadata/gamemaker_is_dnd = {json.dumps(room_creation_code.is_dnd)}',
            f'metadata/gamemaker_creation_code_file_exists = {json.dumps(room_creation_code.exists)}',
            f'metadata/gamemaker_execution_order = {json.dumps(ROOM_EXECUTION_ORDER)}',
            f'metadata/gamemaker_instance_creation_order = {json.dumps(instance_creation_order_names(room))}',
            f'metadata/gamemaker_room_creation_code_execution_phase = {json.dumps(room_creation_code.execution_phase)}',
            f'metadata/gamemaker_room_creation_code_execution_phase_index = {json.dumps(room_creation_code.execution_phase_index)}',
            "",
        ])
        lines.extend(serialized_layers.node_lines)
        return "\n".join(lines)

    def _room_output_path(self, room: IndexedRoom) -> str:
        if room.godot_path.startswith("res://"):
            relative_path = room.godot_path[len("res://"):]
            return os.path.join(self.godot_project_path, *relative_path.split("/"))

        if room.subfolder:
            return os.path.join(
                self.godot_rooms_path, room.subfolder, room.name, room.name + ".tscn"
            )
        return os.path.join(self.godot_rooms_path, room.name, room.name + ".tscn")

    def _room_script_output_path(self, room: IndexedRoom) -> str:
        script_resource_path = _room_script_resource_path(room)
        if script_resource_path.startswith("res://"):
            relative_path = script_resource_path[len("res://"):]
            return os.path.join(self.godot_project_path, *relative_path.split("/"))
        return os.path.splitext(self._room_output_path(room))[0] + ".gd"

    def _generate_room_script(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None = None,
    ) -> str | None:
        asset_names = self._asset_names(resource_index)
        room_creation_code = resolve_room_creation_code(room, self.gm_project_path)
        room_creation_body: str | None = None
        if room_creation_code.has_code and room_creation_code.exists:
            room_creation_body = self._transpile_creation_code(
                room_creation_code.source_path,
                room.name,
                "room creation code",
                asset_names=asset_names,
                top_level_global_scope=True,
            )

        instance_methods: list[InstanceCreationCodeMethod] = []
        used_method_names: dict[str, int] = {}
        for instance in _iter_room_instances(room.layers):
            creation_code = resolve_instance_creation_code(room, instance)
            if not creation_code.has_code or not creation_code.exists:
                continue
            instance_name = _instance_name(instance)
            method_name = self._unique_instance_creation_method_name(
                instance_name,
                used_method_names,
            )
            body = self._transpile_creation_code(
                creation_code.source_path,
                room.name,
                f"instance creation code for {instance_name}",
                asset_names=asset_names,
                self_expression="_gm_instance",
                other_expression="GMRuntime.gml_instance_noone()",
                instance_target="_gm_instance",
            )
            if body is None:
                continue
            instance_methods.append({
                "source_path": creation_code.source_path,
                "method_name": method_name,
                "body": body,
            })

        if room_creation_body is None and not instance_methods:
            return None
        return self._render_room_script(room_creation_body, instance_methods)

    def _transpile_creation_code(
        self,
        source_path: str,
        room_name: str,
        label: str,
        *,
        asset_names: set[str],
        top_level_global_scope: bool = False,
        self_expression: str = "self",
        other_expression: str = "other",
        instance_target: str | None = None,
    ) -> str | None:
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                source = f.read()
        except OSError:
            self._safe_log(
                "Warning: Could not read GameMaker {label} for room {room}: {path}".format(
                    label=label,
                    room=room_name,
                    path=source_path,
                )
            )
            return None

        try:
            return transpile_gml_code(
                source,
                asset_names=asset_names,
                top_level_global_scope=top_level_global_scope,
                source_path=source_path,
                event=label,
                preserve_source_comments=True,
                self_expression=self_expression,
                other_expression=other_expression,
                instance_target=instance_target,
            )
        except GMLTranspileError as exc:
            self._safe_log(
                "Warning: Could not transpile GameMaker {label} for room {room}: {path}: {error}".format(
                    label=label,
                    room=room_name,
                    path=source_path,
                    error=exc,
                )
            )
            return None

    def _render_room_script(
        self,
        room_creation_body: str | None,
        instance_methods: list[InstanceCreationCodeMethod],
    ) -> str:
        lines = [f'extends "{ROOM_SCRIPT_BASE_RESOURCE_PATH}"']
        if instance_methods:
            lines.extend([
                "",
                "func _gm2godot_run_instance_creation_code(_gm_instance):",
                "\tif _gm_instance == null:",
                "\t\treturn false",
                "\tif not _gm_instance.has_meta(\"gamemaker_creation_code_source_path\"):",
                "\t\treturn false",
                "\tvar _gm_source_path = str(_gm_instance.get_meta(\"gamemaker_creation_code_source_path\"))",
                "\tmatch _gm_source_path:",
            ])
            for method in instance_methods:
                lines.extend([
                    f"\t\t{json.dumps(method['source_path'])}:",
                    f"\t\t\t{method['method_name']}(_gm_instance)",
                    "\t\t\treturn true",
                ])
            lines.extend([
                "\treturn false",
            ])

            for method in instance_methods:
                lines.extend([
                    "",
                    f"func {method['method_name']}(_gm_instance):",
                    method["body"],
                ])

        if room_creation_body is not None:
            lines.extend([
                "",
                "func _gm2godot_room_creation_code():",
                room_creation_body,
            ])

        return "\n".join(lines).rstrip() + "\n"

    def _record_effect_layer_diagnostics(self, room: IndexedRoom) -> None:
        if self.diagnostics is None:
            return
        for layer in _iter_room_effect_layers(room.layers):
            layer_name = layer.get("%Name") or layer.get("name")
            effect_type = layer.get("effectType")
            self.diagnostics.add(
                "warning",
                "GM2GD-RESOURCE-UNSUPPORTED",
                "GameMaker effect/filter layer {layer_name} in room {room_name} "
                "is preserved as metadata; native shader/filter behavior requires "
                "project-specific Godot material support.".format(
                    layer_name=layer_name if isinstance(layer_name, str) and layer_name else "Layer",
                    room_name=room.name,
                ),
                source_path=room.yy_path,
                resource=room.name,
                resource_type="room",
                event=str(effect_type) if isinstance(effect_type, str) and effect_type else None,
                issue_number=592,
                workaround="Replace the effect with a Godot material/shader or add a project-specific compatibility mapping.",
            )

    def _unique_instance_creation_method_name(
        self,
        instance_name: str,
        used_method_names: dict[str, int],
    ) -> str:
        base = "_gm2godot_instance_creation_code_" + _gdscript_identifier_suffix(
            instance_name,
            "instance",
        )
        count = used_method_names.get(base, 0)
        used_method_names[base] = count + 1
        if count == 0:
            return base
        return f"{base}_{count + 1}"

    def _asset_names(self, resource_index: GameMakerResourceIndex | None) -> set[str]:
        if resource_index is None:
            return set()
        names = set(resource_index.rooms.keys())
        for resources in resource_index.resources.values():
            names.update(resources.keys())
        return names

    def _process_room(
        self, room: IndexedRoom, resource_index: GameMakerResourceIndex | None = None
    ) -> RoomProcessResult | None:
        if not self.conversion_running():
            return None

        output_path = self._room_output_path(room)
        room_script = self._generate_room_script(room, resource_index)
        room_script_resource_path: str | None = None
        if room_script is not None:
            room_script_resource_path = _room_script_resource_path(room)
            script_output_path = self._room_script_output_path(room)
            os.makedirs(os.path.dirname(script_output_path), exist_ok=True)
            with open(script_output_path, "w", encoding="utf-8") as f:
                f.write(room_script)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self._generate_room_scene(room, resource_index, room_script_resource_path))

        width = room.room_settings.get("Width", 1024)
        height = room.room_settings.get("Height", 768)
        return {
            "success": True,
            "name": room.name,
            "width": width,
            "height": height,
            "scene_path": room.godot_path,
        }

    def _set_startup_scene(
        self, index: GameMakerResourceIndex, generated_scene_paths: dict[str, str]
    ) -> None:
        if not generated_scene_paths:
            self.log_callback(
                "Warning: No room scene generated; leaving project.godot main_scene unchanged."
            )
            return

        first_room = index.first_room()
        if first_room is None or first_room.name not in generated_scene_paths:
            self.log_callback(
                "Warning: First GameMaker room scene was not generated; leaving project.godot main_scene unchanged."
            )
            return

        project_file = GodotProjectFile(
            os.path.join(self.godot_project_path, "project.godot")
        )
        scene_path = generated_scene_paths[first_room.name]
        if project_file.set_main_scene(scene_path):
            self.log_callback(
                "Set Godot startup scene to first GameMaker room: {name} ({scene_path})".format(
                    name=first_room.name,
                    scene_path=scene_path,
                )
            )
        else:
            self.log_callback(
                "Warning: project.godot not found; could not set startup scene."
            )

    def convert_rooms(self) -> None:
        index = self._build_resource_index()
        rooms = index.ordered_rooms()
        if not rooms:
            self._set_startup_scene(index, {})
            self.log_callback("Room conversion completed.")
            return

        self._write_room_runtime_script()

        total = len(rooms)
        processed = 0
        generated_scene_paths: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_room, room, index): room.name
                for room in rooms
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback("Room conversion stopped.")
                    return

                processed += 1
                if result["success"]:
                    generated_scene_paths[result["name"]] = result["scene_path"]
                    if self.compact_logging:
                        self._safe_log_progress(result["name"], processed, total)
                    else:
                        self._safe_log(
                            "Converted room: {name} ({width}x{height})".format(
                                name=result["name"],
                                width=result["width"],
                                height=result["height"],
                            )
                        )

                self._safe_progress(int(processed / total * 100))

        self._set_startup_scene(index, generated_scene_paths)
        self.log_callback("Room conversion completed.")

    def convert_all(self) -> None:
        self.convert_rooms()

    def _write_room_runtime_script(self) -> None:
        runtime_path = os.path.join(self.godot_project_path, ROOM_RUNTIME_SCRIPT_RELATIVE_PATH)
        os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
        with open(runtime_path, "w", encoding="utf-8") as f:
            f.write(render_room_runtime_script())
