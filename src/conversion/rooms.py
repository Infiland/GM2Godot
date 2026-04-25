import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.conversion.base_converter import BaseConverter
from src.conversion.resource_index import GameMakerResourceIndex


class RoomConverter(BaseConverter):
    """Convert GameMaker rooms into minimal Godot room scenes."""

    def __init__(self, gm_project_path, godot_project_path, log_callback=print,
                 progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False,
                 max_workers=None, resource_index=None):
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging,
                         max_workers=max_workers)
        self.godot_rooms_path = os.path.join(self.godot_project_path, "rooms")
        self.resource_index = resource_index

    def _build_resource_index(self):
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

    def _generate_room_scene(self, room):
        room_settings = room.room_settings
        physics_settings = room.physics_settings

        lines = [
            "[gd_scene format=3]",
            "",
            f'[node name="{room.name}" type="Node2D"]',
            f'metadata/gamemaker_room_width = {json.dumps(room_settings.get("Width", 1024))}',
            f'metadata/gamemaker_room_height = {json.dumps(room_settings.get("Height", 768))}',
            f'metadata/gamemaker_room_persistent = {json.dumps(bool(room_settings.get("persistent", False)))}',
            f'metadata/gamemaker_room_volume = {json.dumps(room.raw_data.get("volume", 1.0))}',
            f'metadata/gamemaker_physics_world = {json.dumps(bool(physics_settings.get("PhysicsWorld", False)))}',
            f'metadata/gamemaker_physics_gravity_x = {json.dumps(physics_settings.get("PhysicsWorldGravityX", 0.0))}',
            f'metadata/gamemaker_physics_gravity_y = {json.dumps(physics_settings.get("PhysicsWorldGravityY", 10.0))}',
            f'metadata/gamemaker_physics_pixels_to_meters = {json.dumps(physics_settings.get("PhysicsWorldPixToMetres", 0.1))}',
            f'metadata/gamemaker_source_yy_path = {json.dumps(room.yy_path)}',
            "",
        ]
        return "\n".join(lines)

    def _room_output_path(self, room):
        if room.godot_path.startswith("res://"):
            relative_path = room.godot_path[len("res://"):]
            return os.path.join(self.godot_project_path, *relative_path.split("/"))

        if room.subfolder:
            return os.path.join(
                self.godot_rooms_path, room.subfolder, room.name, room.name + ".tscn"
            )
        return os.path.join(self.godot_rooms_path, room.name, room.name + ".tscn")

    def _process_room(self, room):
        if not self.conversion_running():
            return None

        output_path = self._room_output_path(room)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self._generate_room_scene(room))

        width = room.room_settings.get("Width", 1024)
        height = room.room_settings.get("Height", 768)
        return {"success": True, "name": room.name, "width": width, "height": height}

    def convert_rooms(self):
        index = self._build_resource_index()
        rooms = index.ordered_rooms()
        if not rooms:
            self.log_callback("Room conversion completed.")
            return

        total = len(rooms)
        processed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_room, room): room.name
                for room in rooms
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback("Room conversion stopped.")
                    return

                processed += 1
                if result["success"]:
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

        self.log_callback("Room conversion completed.")

    def convert_all(self):
        self.convert_rooms()
