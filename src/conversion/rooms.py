from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict

from src.conversion.base_converter import BaseConverter
from src.conversion.project_godot import GodotProjectFile
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.room_creation_code import (
    ROOM_EXECUTION_ORDER,
    instance_creation_order_names,
    resolve_room_creation_code,
)
from src.conversion.room_layers import godot_string, serialize_room_layers
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath

ROOM_RUNTIME_SCRIPT_RELATIVE_PATH = os.path.join("gm2godot", "gml_room_node.gd")
ROOM_RUNTIME_SCRIPT_RESOURCE_PATH = "res://gm2godot/gml_room_node.gd"
ROOM_RUNTIME_EXT_RESOURCE_ID = "gm_room_runtime"


def render_room_runtime_script() -> str:
    return (
        "extends Node2D\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "func _ready():\n"
        "\tGMRuntime.gml_room_enter_scene(self)\n"
    )


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
                  resource_index: GameMakerResourceIndex | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging,
                         max_workers=max_workers)
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
        self, room: IndexedRoom, resource_index: GameMakerResourceIndex | None = None
    ) -> str:
        room_settings = room.room_settings
        physics_settings = room.physics_settings
        room_creation_code = resolve_room_creation_code(
            room,
            self.gm_project_path,
            warn_callback=self._safe_log,
        )
        serialized_layers = serialize_room_layers(
            room,
            gm_project_path=self.gm_project_path,
            resource_index=resource_index,
            warn_callback=self._safe_log,
        )

        if serialized_layers.ext_resource_lines:
            lines = [
                f"[gd_scene format=3 load_steps={len(serialized_layers.ext_resource_lines) + 2}]",
                "",
                (
                    '[ext_resource type="Script" path="{path}" id="{resource_id}"]'.format(
                        path=ROOM_RUNTIME_SCRIPT_RESOURCE_PATH,
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
                        path=ROOM_RUNTIME_SCRIPT_RESOURCE_PATH,
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

    def _process_room(
        self, room: IndexedRoom, resource_index: GameMakerResourceIndex | None = None
    ) -> RoomProcessResult | None:
        if not self.conversion_running():
            return None

        output_path = self._room_output_path(room)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self._generate_room_scene(room, resource_index))

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
