from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any, Callable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.rooms import ROOM_RUNTIME_SCRIPT_RELATIVE_PATH, RoomConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.resource_index import IndexedRoom
from src.conversion.room_creation_code import resolve_instance_creation_code
from src.conversion.room_layers import (
    GAMEMAKER_EMPTY_TILE_SENTINEL,
    GAMEMAKER_TILE_FLIP_BIT,
    GAMEMAKER_TILE_MIRROR_BIT,
    GAMEMAKER_TILE_ROTATE_BIT,
    GODOT_TILE_TRANSFORM_FLIP_H,
    GODOT_TILE_TRANSFORM_FLIP_V,
    GODOT_TILE_TRANSFORM_TRANSPOSE,
    decode_gamemaker_tile,
    decode_tile_compressed_data,
    gamemaker_tile_transform_to_godot,
    is_empty_gamemaker_tile,
)


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _make_yyp(
    room_names: list[str],
    room_order: list[str] | None = None,
    extra_resources: list[tuple[str, str]] | None = None,
) -> str:
    room_order = room_order or room_names
    extra_resources = extra_resources or []
    resources: list[str] = []
    for name in room_names:
        resources.append(
            '    {{"id":{{"name":"{name}",'
            '"path":"rooms/{name}/{name}.yy",}},}}'.format(name=name)
        )
    for kind, name in extra_resources:
        resources.append(
            '    {{"id":{{"name":"{name}",'
            '"path":"{kind}/{name}/{name}.yy",}},}}'.format(kind=kind, name=name)
        )
    order_entries: list[str] = []
    for name in room_order:
        order_entries.append(
            '    {{"roomId":{{"name":"{name}",'
            '"path":"rooms/{name}/{name}.yy",}},}}'.format(name=name)
        )

    return (
        "{\n"
        f'  "resources":[\n{",\n".join(resources)},\n  ],\n'
        f'  "RoomOrderNodes":[\n{",\n".join(order_entries)},\n  ],\n'
        '  "resourceType":"GMProject",\n'
        "}\n"
    )


def _make_room_yy(name: str, parent_path: str = "folders/Rooms.yy", width: int = 1024,
                  height: int = 768, persistent: bool = False, volume: float = 1.0,
                  physics_world: bool = False, layers: list[dict[str, Any]] | None = None,
                  instance_creation_order: list[dict[str, Any]] | None = None,
                  creation_code_file: str = "", inherit_code: bool = False,
                  is_dnd: bool = False, inherit_creation_order: bool = False,
                  inherit_layers: bool = False, parent_room: dict[str, Any] | None = None,
                  inherit_room_settings: bool = False,
                  inherit_physics_settings: bool = False,
                  views: list[dict[str, Any]] | None = None,
                  view_settings: dict[str, Any] | None = None) -> str:
    persistent_value = "true" if persistent else "false"
    physics_world_value = "true" if physics_world else "false"
    inherit_code_value = "true" if inherit_code else "false"
    inherit_creation_order_value = "true" if inherit_creation_order else "false"
    inherit_layers_value = "true" if inherit_layers else "false"
    inherit_room_settings_value = "true" if inherit_room_settings else "false"
    inherit_physics_settings_value = "true" if inherit_physics_settings else "false"
    is_dnd_value = "true" if is_dnd else "false"
    layers_json = json.dumps(layers if layers is not None else [])
    instance_creation_order_json = json.dumps(instance_creation_order or [])
    parent_room_json = json.dumps(parent_room)
    views_json = json.dumps(views or [])
    view_settings_json = json.dumps(view_settings or {"enableViews": False})
    return (
        '{{\n'
        '  "$GMRoom":"v1",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "creationCodeFile":{creation_code_file},\n'
        '  "inheritCode":{inherit_code},\n'
        '  "inheritCreationOrder":{inherit_creation_order},\n'
        '  "inheritLayers":{inherit_layers},\n'
        '  "instanceCreationOrder":{instance_creation_order_json},\n'
        '  "isDnd":{is_dnd},\n'
        '  "layers":{layers_json},\n'
        '  "parent":{{"name":"Rooms","path":"{parent_path}",}},\n'
        '  "parentRoom":{parent_room_json},\n'
        '  "physicsSettings":{{\n'
        '    "inheritPhysicsSettings":{inherit_physics_settings},\n'
        '    "PhysicsWorld":{physics_world},\n'
        '    "PhysicsWorldGravityX":0.0,\n'
        '    "PhysicsWorldGravityY":10.0,\n'
        '    "PhysicsWorldPixToMetres":0.1,\n'
        '  }},\n'
        '  "resourceType":"GMRoom",\n'
        '  "roomSettings":{{\n'
        '    "Width":{width},\n'
        '    "Height":{height},\n'
        '    "inheritRoomSettings":{inherit_room_settings},\n'
        '    "persistent":{persistent},\n'
        '  }},\n'
        '  "views":{views_json},\n'
        '  "viewSettings":{view_settings_json},\n'
        '  "volume":{volume},\n'
        '}}\n'
    ).format(
        name=name,
        parent_path=parent_path,
        width=width,
        height=height,
        persistent=persistent_value,
        volume=volume,
        physics_world=physics_world_value,
        layers_json=layers_json,
        instance_creation_order_json=instance_creation_order_json,
        creation_code_file=json.dumps(creation_code_file),
        inherit_code=inherit_code_value,
        inherit_creation_order=inherit_creation_order_value,
        inherit_layers=inherit_layers_value,
        parent_room_json=parent_room_json,
        inherit_room_settings=inherit_room_settings_value,
        inherit_physics_settings=inherit_physics_settings_value,
        views_json=views_json,
        view_settings_json=view_settings_json,
        is_dnd=is_dnd_value,
    )


def _make_object_yy(name: str, parent_path: str = "folders/Objects.yy") -> str:
    return (
        '{{\n'
        '  "$GMObject":"",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "eventList":[],\n'
        '  "parent":{{"name":"Objects","path":"{parent_path}",}},\n'
        '  "resourceType":"GMObject",\n'
        '}}\n'
    ).format(name=name, parent_path=parent_path)


def _make_sprite_yy(name: str, parent_path: str = "folders/Sprites.yy") -> str:
    return (
        '{{\n'
        '  "$GMSprite":"",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "parent":{{"name":"Sprites","path":"{parent_path}",}},\n'
        '  "resourceType":"GMSprite",\n'
        '}}\n'
    ).format(name=name, parent_path=parent_path)


class TestRoomConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.progress: list[int | float] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        conversion_running: Callable[[], bool] = lambda: True,
        diagnostics: DiagnosticCollector | None = None,
    ) -> RoomConverter:
        return RoomConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda value: self.progress.append(value),
            conversion_running=conversion_running,
            max_workers=1,
            diagnostics=diagnostics,
        )

    def _write_yyp(
        self,
        room_names: list[str],
        room_order: list[str] | None = None,
        extra_resources: list[tuple[str, str]] | None = None,
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            _make_yyp(room_names, room_order, extra_resources),
        )

    def _write_project_godot(
        self, content: str = '[application]\nconfig/name="Existing"\n'
    ) -> None:
        _write_file(os.path.join(self.godot_dir, "project.godot"), content)

    def _write_room(self, name: str, **kwargs: Any) -> str:
        room_path = os.path.join(self.gm_dir, "rooms", name, name + ".yy")
        _write_file(room_path, _make_room_yy(name, **kwargs))
        return room_path

    def _write_object(self, name: str, parent_path: str = "folders/Objects.yy") -> str:
        object_path = os.path.join(self.gm_dir, "objects", name, name + ".yy")
        _write_file(object_path, _make_object_yy(name, parent_path))
        return object_path

    def _write_object_scene(self, name: str, *subfolders: str) -> str:
        scene_path = os.path.join(
            self.godot_dir,
            "objects",
            *subfolders,
            name,
            name + ".tscn",
        )
        _write_file(scene_path, '[gd_scene format=3]\n\n[node name="{}" type="Node2D"]\n'.format(name))
        return scene_path

    def _write_sprite(self, name: str, parent_path: str = "folders/Sprites.yy") -> str:
        sprite_path = os.path.join(self.gm_dir, "sprites", name, name + ".yy")
        _write_file(sprite_path, _make_sprite_yy(name, parent_path))
        return sprite_path

    def _write_sprite_scene(self, name: str, *subfolders: str) -> str:
        scene_path = os.path.join(
            self.godot_dir,
            "sprites",
            *subfolders,
            name,
            name + ".tscn",
        )
        _write_file(scene_path, '[gd_scene format=3]\n\n[node name="{}" type="Area2D"]\n'.format(name))
        return scene_path

    def _write_tileset(
        self,
        name: str,
        parent_path: str = "folders/Tile Sets.yy",
        tile_count: int = 4,
        out_columns: int = 2,
    ) -> str:
        tileset_path = os.path.join(self.gm_dir, "tilesets", name, name + ".yy")
        _write_file(
            tileset_path,
            (
                '{{\n'
                '  "$GMTileSet":"v1",\n'
                '  "%Name":"{name}",\n'
                '  "name":"{name}",\n'
                '  "out_columns":{out_columns},\n'
                '  "parent":{{"name":"Tile Sets","path":"{parent_path}",}},\n'
                '  "resourceType":"GMTileSet",\n'
                '  "spriteId":{{"name":"s_tiles","path":"sprites/s_tiles/s_tiles.yy",}},\n'
                '  "tileHeight":16,\n'
                '  "tileWidth":16,\n'
                '  "tile_count":{tile_count},\n'
                '  "tilehsep":0,\n'
                '  "tilevsep":0,\n'
                '  "tilexoff":0,\n'
                '  "tileyoff":0,\n'
                '}}\n'
            ).format(
                name=name,
                out_columns=out_columns,
                parent_path=parent_path,
                tile_count=tile_count,
            ),
        )
        return tileset_path

    def _write_tileset_resource(self, name: str, *subfolders: str) -> str:
        tres_path = os.path.join(
            self.godot_dir,
            "tilesets",
            *subfolders,
            name,
            name + ".tres",
        )
        _write_file(
            tres_path,
            '[gd_resource type="TileSet" format=3]\n\n[resource]\ntile_size = Vector2i(16, 16)\n',
        )
        return tres_path

    def _read_scene(self, room_name: str, *subfolders: str) -> str:
        tscn_path = os.path.join(
            self.godot_dir,
            "rooms",
            *subfolders,
            room_name,
            room_name + ".tscn",
        )
        with open(tscn_path, "r", encoding="utf-8") as f:
            return f.read()

    def _read_room_script(self, room_name: str, *subfolders: str) -> str:
        script_path = os.path.join(
            self.godot_dir,
            "rooms",
            *subfolders,
            room_name,
            room_name + ".gd",
        )
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_generates_minimal_room_scene_with_metadata(self):
        self._write_yyp(["r_test"])
        room_yy_path = self._write_room(
            "r_test",
            width=1024,
            height=768,
            persistent=True,
            volume=0.75,
            physics_world=True,
        )

        self._make_converter().convert_all()

        tscn_path = os.path.join(self.godot_dir, "rooms", "r_test", "r_test.tscn")
        self.assertTrue(os.path.isfile(tscn_path))

        with open(tscn_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('[gd_scene format=3 load_steps=2]', content)
        self.assertIn(
            '[ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]',
            content,
        )
        self.assertIn('[node name="r_test" type="Node2D"]', content)
        self.assertIn('script = ExtResource("gm_room_runtime")', content)
        self.assertIn('metadata/gm2godot_room_root_policy = "gm_room_node2d"', content)
        self.assertIn('metadata/gm2godot_layer_hierarchy_policy = "gm_layer_depth_node2d"', content)
        self.assertIn('[node name="GMGUI" type="CanvasLayer" parent="."]', content)
        self.assertIn('metadata/gm2godot_gui_layer_policy = "gm_gui_canvas_layer"', content)
        self.assertIn('metadata/gamemaker_room_width = 1024', content)
        self.assertIn('metadata/gamemaker_room_height = 768', content)
        self.assertIn('metadata/gamemaker_room_persistent = true', content)
        self.assertIn('metadata/gamemaker_room_volume = 0.75', content)
        self.assertIn('metadata/gamemaker_physics_world = true', content)
        self.assertIn('metadata/gamemaker_physics_gravity_x = 0.0', content)
        self.assertIn('metadata/gamemaker_physics_gravity_y = 10.0', content)
        self.assertIn('metadata/gamemaker_physics_pixels_to_meters = 0.1', content)
        self.assertIn(
            'metadata/gamemaker_source_yy_path = ' + json.dumps(room_yy_path),
            content,
        )
        self.assertNotIn('instance=ExtResource', content)
        self.assertNotIn('Camera2D', content)
        self.assertNotIn('TileMap', content)
        self.assertNotIn('ParallaxBackground', content)
        self.assertTrue(
            os.path.isfile(os.path.join(self.godot_dir, ROOM_RUNTIME_SCRIPT_RELATIVE_PATH))
        )
        self.assertEqual(self.progress[-1], 100)
        self.assertTrue(any("r_test" in log for log in self.logs))

    def test_preserves_room_subfolders(self):
        self._write_yyp(["r_intro"])
        self._write_room("r_intro", parent_path="folders/Rooms/Game/Intro.yy")

        self._make_converter().convert_all()

        self.assertTrue(os.path.isfile(os.path.join(
            self.godot_dir,
            "rooms",
            "game",
            "intro",
            "r_intro",
            "r_intro.tscn",
        )))

    def test_converts_only_rooms_listed_in_yyp(self):
        self._write_yyp(["r_listed"])
        self._write_room("r_listed")
        self._write_room("r_unlisted")

        self._make_converter().convert_all()

        self.assertTrue(os.path.isfile(os.path.join(
            self.godot_dir, "rooms", "r_listed", "r_listed.tscn"
        )))
        self.assertFalse(os.path.exists(os.path.join(
            self.godot_dir, "rooms", "r_unlisted"
        )))

    def test_generates_room_layer_placeholders_with_depth_and_visibility(self):
        self._write_yyp(["r_layers"])
        self._write_room("r_layers", layers=[
            {
                "%Name": "Instances",
                "name": "internal_instances",
                "resourceType": "GMRInstanceLayer",
                "visible": True,
                "depth": 100,
                "gridX": 32,
                "gridY": 16,
                "properties": {"alpha": 1},
                "instances": [{"name": "inst_a"}],
            },
            {
                "name": "Backgrounds",
                "resourceType": "GMRBackgroundLayer",
                "visible": False,
                "depth": -200,
                "gridX": 64,
                "gridY": 64,
                "properties": {},
            },
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_layers")

        self.assertIn('[node name="Instances" type="Node2D" parent="."]', content)
        self.assertIn('visible = true', content)
        self.assertIn('position = Vector2(0, 0)', content)
        self.assertIn('z_index = -100', content)
        self.assertIn('metadata/gm2godot_layer_policy = "gm_layer_depth_node2d"', content)
        self.assertIn('metadata/gm2godot_depth_mapping_policy = "gamemaker_depth_to_negative_z_index"', content)
        self.assertIn('metadata/gamemaker_layer_type = "GMRInstanceLayer"', content)
        self.assertIn('metadata/gamemaker_layer_depth = 100', content)
        self.assertIn('metadata/gamemaker_layer_x = 0', content)
        self.assertIn('metadata/gamemaker_layer_y = 0', content)
        self.assertIn('metadata/gamemaker_layer_hspeed = 0', content)
        self.assertIn('metadata/gamemaker_layer_vspeed = 0', content)
        self.assertIn('metadata/gamemaker_layer_grid_x = 32', content)
        self.assertIn('metadata/gamemaker_layer_grid_y = 16', content)
        self.assertIn('metadata/gamemaker_layer_properties = {"alpha": 1}', content)
        self.assertIn('metadata/gamemaker_instance_count = 1', content)
        self.assertIn('metadata/gamemaker_instance_names = ["inst_a"]', content)

        self.assertIn('[node name="Backgrounds" type="Node2D" parent="."]', content)
        self.assertIn('visible = false', content)
        self.assertIn('z_index = 200', content)
        self.assertIn('metadata/gamemaker_background_sprite = null', content)
        self.assertNotIn('instance=ExtResource', content)
        self.assertNotIn('Sprite2D', content)
        self.assertNotIn('TileMap', content)
        self.assertNotIn('ParallaxBackground', content)

    def test_background_layer_without_sprite_emits_color_visual(self):
        self._write_yyp(["r_background"])
        self._write_room("r_background", width=320, height=180, layers=[
            {
                "%Name": "Backgrounds",
                "resourceType": "GMRBackgroundLayer",
                "depth": 500,
                "colour": 4294967295,
            },
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_background")

        self.assertIn('[node name="Backgrounds" type="Node2D" parent="."]', content)
        self.assertIn('[node name="BackgroundVisual" type="ColorRect" parent="Backgrounds"]', content)
        self.assertIn('size = Vector2(320, 180)', content)
        self.assertIn('color = Color(1, 1, 1, 1)', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "background"', content)
        self.assertIn('metadata/gamemaker_background_visual = true', content)
        self.assertIn('metadata/gamemaker_background_visual_type = "color"', content)

    def test_background_layer_with_sprite_instances_sprite_scene(self):
        self._write_yyp(["r_background"], extra_resources=[("sprites", "s_background")])
        self._write_sprite("s_background")
        self._write_sprite_scene("s_background")
        self._write_room("r_background", layers=[
            {
                "%Name": "Backgrounds",
                "resourceType": "GMRBackgroundLayer",
                "spriteId": {"name": "s_background", "path": "sprites/s_background/s_background.yy"},
                "x": 16,
                "y": 32,
                "colour": 4294967295,
            },
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_background")

        self.assertIn(
            '[ext_resource type="PackedScene" path="res://sprites/s_background/s_background.tscn" id="1"]',
            content,
        )
        self.assertIn(
            '[node name="s_background" parent="Backgrounds" instance=ExtResource("1")]',
            content,
        )
        self.assertIn('position = Vector2(16, 32)', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "background"', content)
        self.assertIn('modulate = Color(1, 1, 1, 1)', content)
        self.assertIn('metadata/gamemaker_background_visual_type = "sprite"', content)

    def test_sprite_background_layer_with_scrolling_uses_parallax_runtime(self):
        self._write_yyp(["r_background"], extra_resources=[("sprites", "s_background")])
        self._write_sprite("s_background")
        self._write_sprite_scene("s_background")
        self._write_room("r_background", layers=[
            {
                "%Name": "Backgrounds",
                "resourceType": "GMRBackgroundLayer",
                "spriteId": {"name": "s_background", "path": "sprites/s_background/s_background.yy"},
                "htiled": True,
                "vtiled": True,
                "hspeed": 1,
                "vspeed": -2,
            },
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_background")

        self.assertIn('[node name="s_background" type="Parallax2D" parent="Backgrounds"]', content)
        self.assertIn('repeat_size = Vector2(1024, 768)', content)
        self.assertIn('scroll_offset = Vector2(0, 0)', content)
        self.assertIn('metadata/gamemaker_background_runtime_support = true', content)
        self.assertIn(
            '[node name="s_backgroundVisual" parent="Backgrounds/s_background" instance=ExtResource("1")]',
            content,
        )
        self.assertFalse(any("scrolling/tiling" in log for log in self.logs))

    def test_background_layer_preserves_scrolling_tiling_runtime_metadata(self):
        self._write_yyp(["r_background"])
        self._write_room("r_background", layers=[
            {
                "%Name": "MovingBackground",
                "resourceType": "GMRBackgroundLayer",
                "htiled": True,
                "vtiled": False,
                "hspeed": 2,
                "vspeed": 0,
                "stretch": True,
                "animationFPS": 12,
                "animationSpeedType": 0,
            },
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_background")

        self.assertIn('metadata/gamemaker_background_htiled = true', content)
        self.assertIn('metadata/gamemaker_background_vtiled = false', content)
        self.assertIn('metadata/gamemaker_background_hspeed = 2', content)
        self.assertIn('metadata/gamemaker_background_vspeed = 0', content)
        self.assertIn('metadata/gamemaker_layer_hspeed = 2', content)
        self.assertIn('metadata/gamemaker_layer_vspeed = 0', content)
        self.assertIn('metadata/gamemaker_background_stretch = true', content)
        self.assertIn('metadata/gamemaker_background_animation_fps = 12', content)
        self.assertIn('[node name="BackgroundVisual" type="Parallax2D" parent="MovingBackground"]', content)
        self.assertIn('repeat_size = Vector2(1024, 0)', content)
        self.assertIn('repeat_times = 3', content)
        self.assertIn('metadata/gamemaker_background_runtime_support = true', content)
        self.assertIn('[node name="BackgroundColor" type="ColorRect" parent="MovingBackground/BackgroundVisual"]', content)
        self.assertFalse(any("scrolling/tiling" in log for log in self.logs))

    def test_layer_depth_maps_to_inverse_z_index(self):
        self._write_yyp(["r_depths"])
        self._write_room("r_depths", layers=[
            {"%Name": "Depth200", "resourceType": "GMRInstanceLayer", "depth": 200},
            {"%Name": "Depth100", "resourceType": "GMRInstanceLayer", "depth": 100},
            {"%Name": "Depth0", "resourceType": "GMRInstanceLayer", "depth": 0},
            {"%Name": "DepthMinus100", "resourceType": "GMRInstanceLayer", "depth": -100},
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_depths")

        self.assertIn('[node name="Depth200" type="Node2D" parent="."]', content)
        self.assertIn("z_index = -200", content)
        self.assertIn('[node name="Depth100" type="Node2D" parent="."]', content)
        self.assertIn("z_index = -100", content)
        self.assertIn('[node name="Depth0" type="Node2D" parent="."]', content)
        self.assertIn("z_index = 0", content)
        self.assertIn('[node name="DepthMinus100" type="Node2D" parent="."]', content)
        self.assertIn("z_index = 100", content)

    def test_generates_nested_layer_placeholders_depth_first(self):
        self._write_yyp(["r_nested"])
        self._write_room("r_nested", layers=[
            {
                "%Name": "Parent",
                "resourceType": "GMRInstanceLayer",
                "depth": 10,
                "layers": [
                    {"%Name": "ChildA", "resourceType": "GMRTileLayer", "depth": 20},
                    {"%Name": "ChildB", "resourceType": "GMRAssetLayer", "depth": 30},
                ],
            },
            {"%Name": "Sibling", "resourceType": "GMRBackgroundLayer", "depth": 40},
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_nested")

        parent_idx = content.index('[node name="Parent" type="Node2D" parent="."]')
        child_a_idx = content.index('[node name="ChildA" type="Node2D" parent="Parent"]')
        child_b_idx = content.index('[node name="ChildB" type="Node2D" parent="Parent"]')
        sibling_idx = content.index('[node name="Sibling" type="Node2D" parent="."]')

        self.assertLess(parent_idx, child_a_idx)
        self.assertLess(child_a_idx, child_b_idx)
        self.assertLess(child_b_idx, sibling_idx)
        self.assertIn('metadata/gamemaker_tile_compressed_data_count = 0', content)
        self.assertIn('metadata/gamemaker_asset_count = 0', content)

    def test_decodes_gamemaker_tile_compressed_data(self):
        decoded = decode_tile_compressed_data(
            3,
            2,
            [-2, 1, 0, -2, GAMEMAKER_EMPTY_TILE_SENTINEL, 2],
        )

        self.assertEqual(decoded, [1, 1, 0, GAMEMAKER_EMPTY_TILE_SENTINEL, GAMEMAKER_EMPTY_TILE_SENTINEL, 2])
        self.assertTrue(is_empty_gamemaker_tile(0))
        self.assertTrue(is_empty_gamemaker_tile(GAMEMAKER_EMPTY_TILE_SENTINEL))
        self.assertFalse(is_empty_gamemaker_tile(1))

    def test_decodes_raw_gamemaker_tile_data_format_zero(self):
        decoded = decode_tile_compressed_data(
            2,
            2,
            [1, 0, GAMEMAKER_EMPTY_TILE_SENTINEL, 2],
            tile_data_format=0,
        )

        self.assertEqual(decoded, [1, 0, GAMEMAKER_EMPTY_TILE_SENTINEL, 2])
        with self.assertRaisesRegex(ValueError, "decoded 1 cells, expected 4"):
            decode_tile_compressed_data(2, 2, [1], tile_data_format=0)

    def test_gamemaker_tile_flags_decode_from_tile_data(self):
        raw_tile = 3 | GAMEMAKER_TILE_MIRROR_BIT | GAMEMAKER_TILE_FLIP_BIT | GAMEMAKER_TILE_ROTATE_BIT
        tile = decode_gamemaker_tile(raw_tile)

        self.assertEqual(tile.tile_index, 3)
        self.assertTrue(tile.mirror)
        self.assertTrue(tile.flip)
        self.assertTrue(tile.rotate)

    def test_gamemaker_tile_transforms_map_all_eight_orientations(self):
        h = GODOT_TILE_TRANSFORM_FLIP_H
        v = GODOT_TILE_TRANSFORM_FLIP_V
        t = GODOT_TILE_TRANSFORM_TRANSPOSE
        expected = {
            (False, False, False): 0,
            (True, False, False): h,
            (False, True, False): v,
            (True, True, False): h | v,
            (False, False, True): h | t,
            (True, False, True): h | v | t,
            (False, True, True): t,
            (True, True, True): v | t,
        }

        for (mirror, flip, rotate), alternative_tile in expected.items():
            with self.subTest(mirror=mirror, flip=flip, rotate=rotate):
                self.assertEqual(
                    gamemaker_tile_transform_to_godot(
                        mirror=mirror,
                        flip=flip,
                        rotate=rotate,
                    ),
                    alternative_tile,
                )

    def test_tile_layer_emits_tilemaplayer_with_decoded_cells(self):
        self._write_yyp(["r_tiles"], extra_resources=[("tilesets", "ts_ground")])
        self._write_tileset("ts_ground", tile_count=4, out_columns=2)
        self._write_tileset_resource("ts_ground")
        self._write_room("r_tiles", layers=[
            {
                "%Name": "Tiles",
                "resourceType": "GMRTileLayer",
                "visible": True,
                "x": 8,
                "y": 16,
                "tilesetId": {"name": "ts_ground", "path": "tilesets/ts_ground/ts_ground.yy"},
                "tiles": {
                    "SerialiseWidth": 3,
                    "SerialiseHeight": 2,
                    "TileDataFormat": 1,
                    "TileCompressedData": [-2, 1, 0, 2, -2, GAMEMAKER_EMPTY_TILE_SENTINEL],
                },
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_tiles")

        self.assertIn('[ext_resource type="TileSet" path="res://tilesets/ts_ground/ts_ground.tres" id="1"]', content)
        self.assertIn('[node name="TileMap" type="TileMapLayer" parent="Tiles"]', content)
        self.assertIn('position = Vector2(8, 16)', content)
        self.assertIn('tile_set = ExtResource("1")', content)
        self.assertIn('tile_map_data = PackedByteArray(0, 0', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "tilemap"', content)
        self.assertIn('metadata/gamemaker_tile_decoded_cell_count = 6', content)
        self.assertIn('metadata/gamemaker_tile_non_empty_cell_count = 3', content)
        self.assertIn('metadata/gamemaker_tile_empty_values = [0, -2147483648]', content)
        self.assertIn('metadata/gamemaker_tile_raw_values = [1, 1, 0, 2, 0, 0]', content)

    def test_tile_layer_accepts_raw_tile_data_format_zero(self):
        self._write_yyp(["r_raw_tiles"], extra_resources=[("tilesets", "ts_ground")])
        self._write_tileset("ts_ground", tile_count=4, out_columns=2)
        self._write_tileset_resource("ts_ground")
        self._write_room("r_raw_tiles", layers=[
            {
                "%Name": "Tiles",
                "resourceType": "GMRTileLayer",
                "visible": True,
                "tilesetId": {"name": "ts_ground", "path": "tilesets/ts_ground/ts_ground.yy"},
                "tiles": {
                    "SerialiseWidth": 2,
                    "SerialiseHeight": 2,
                    "TileDataFormat": 0,
                    "TileCompressedData": [1, 0, GAMEMAKER_EMPTY_TILE_SENTINEL, 2],
                },
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_raw_tiles")

        self.assertIn('[node name="TileMap" type="TileMapLayer" parent="Tiles"]', content)
        self.assertIn('metadata/gamemaker_tile_data_format = 0', content)
        self.assertIn('metadata/gamemaker_tile_decoded_cell_count = 4', content)
        self.assertIn('metadata/gamemaker_tile_non_empty_cell_count = 2', content)
        self.assertFalse(any("Could not decode GameMaker tile data" in log for log in self.logs))

    def test_missing_tileset_warns_without_emitting_tilemaplayer(self):
        self._write_yyp(["r_tiles"])
        self._write_room("r_tiles", layers=[
            {
                "%Name": "Tiles",
                "resourceType": "GMRTileLayer",
                "tilesetId": {"name": "ts_missing"},
                "tiles": {"SerialiseWidth": 1, "SerialiseHeight": 1, "TileCompressedData": [1], "TileDataFormat": 1},
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_tiles")

        self.assertNotIn('type="TileMapLayer"', content)
        self.assertTrue(any("Could not resolve TileSet" in log for log in self.logs))

    def test_effect_layer_preserves_effect_metadata(self):
        self._write_yyp(["r_effect"])
        self._write_room("r_effect", layers=[
            {
                "%Name": "FX",
                "resourceType": "GMREffectLayer",
                "visible": True,
                "depth": 5,
                "effectType": "_filter_whitenoise",
                "properties": [
                    {"name": "g_WhiteNoiseIntensity", "type": 0, "value": "0.15"},
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_effect")

        self.assertIn('[node name="FX" type="Node2D" parent="."]', content)
        self.assertIn('z_index = -5', content)
        self.assertIn('metadata/gamemaker_layer_type = "GMREffectLayer"', content)
        self.assertIn('metadata/gamemaker_layer_effect_type = "_filter_whitenoise"', content)
        self.assertIn('metadata/gamemaker_layer_effect_properties = [{"name": "g_WhiteNoiseIntensity"', content)
        self.assertTrue(any(
            "effect/filter layer FX" in log and "preserved as metadata" in log
            for log in self.logs
        ))

    def test_effect_layer_records_source_linked_diagnostic(self):
        self._write_yyp(["r_effect_diag"])
        room_path = self._write_room("r_effect_diag", layers=[
            {
                "%Name": "FX",
                "resourceType": "GMREffectLayer",
                "effectType": "_filter_whitenoise",
            }
        ])
        diagnostics = DiagnosticCollector()
        converter = RoomConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda value: self.progress.append(value),
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )

        converter.convert_all()
        recorded = diagnostics.diagnostics()

        self.assertTrue(any(
            diagnostic.code == "GM2GD-RESOURCE-UNSUPPORTED"
            and diagnostic.source_path == room_path
            and diagnostic.resource == "r_effect_diag"
            and diagnostic.event == "_filter_whitenoise"
            for diagnostic in recorded
        ))

    def test_unsupported_layer_type_warns_and_emits_placeholder(self):
        self._write_yyp(["r_unknown"])
        self._write_room("r_unknown", layers=[
            {"%Name": "Mystery", "resourceType": "GMRMysteryLayer", "depth": 0}
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_unknown")

        self.assertIn('[node name="Mystery" type="Node2D" parent="."]', content)
        self.assertIn('metadata/gamemaker_layer_type = "GMRMysteryLayer"', content)
        self.assertIn('metadata/gamemaker_unsupported_layer = true', content)
        self.assertTrue(any(
            "Unsupported room layer type GMRMysteryLayer" in log
            and "r_unknown" in log
            and "Mystery" in log
            for log in self.logs
        ))

    def test_layer_names_prefer_display_name_and_are_uniqued(self):
        self._write_yyp(["r_names"])
        self._write_room("r_names", layers=[
            {"%Name": "Display Name", "name": "internal_name", "resourceType": "GMRInstanceLayer"},
            {"%Name": "Display Name", "resourceType": "GMRInstanceLayer"},
            {"name": "FallbackName", "resourceType": "GMRInstanceLayer"},
            {"%Name": "Slash/Name", "resourceType": "GMRInstanceLayer"},
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_names")

        self.assertIn('[node name="Display Name" type="Node2D" parent="."]', content)
        self.assertIn('[node name="Display Name_2" type="Node2D" parent="."]', content)
        self.assertIn('[node name="FallbackName" type="Node2D" parent="."]', content)
        self.assertIn('[node name="Slash_Name" type="Node2D" parent="."]', content)
        self.assertNotIn('[node name="internal_name"', content)
        self.assertIn('metadata/gamemaker_layer_name = "Slash/Name"', content)

    def test_instance_layer_emits_object_scene_children(self):
        self._write_yyp(["r_instances"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player")
        self._write_object_scene("o_player")
        self._write_room("r_instances", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {
                        "name": "inst_player",
                        "objectId": {"name": "o_player", "path": "objects/o_player/o_player.yy"},
                        "x": 100,
                        "y": 200,
                        "rotation": 90,
                        "scaleX": 2,
                        "scaleY": 0.5,
                        "colour": 4294967295,
                        "imageIndex": 3,
                        "imageSpeed": 0.25,
                        "hasCreationCode": True,
                        "properties": [{"name": "hp", "value": 10}],
                    }
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_instances")

        self.assertIn('[gd_scene format=3 load_steps=3]', content)
        self.assertIn(
            '[ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]',
            content,
        )
        self.assertIn(
            '[ext_resource type="PackedScene" path="res://objects/o_player/o_player.tscn" id="1"]',
            content,
        )
        self.assertIn(
            '[node name="inst_player" parent="Instances" instance=ExtResource("1")]',
            content,
        )
        self.assertIn('position = Vector2(100, 200)', content)
        self.assertIn('rotation_degrees = 90', content)
        self.assertIn('scale = Vector2(2, 0.5)', content)
        self.assertIn('metadata/gamemaker_instance_name = "inst_player"', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "instance"', content)
        self.assertIn('metadata/gamemaker_instance_object_name = "o_player"', content)
        self.assertIn('metadata/gamemaker_instance_x = 100', content)
        self.assertIn('metadata/gamemaker_instance_y = 200', content)
        self.assertIn('metadata/gamemaker_instance_rotation = 90', content)
        self.assertIn('metadata/gamemaker_instance_scale_x = 2', content)
        self.assertIn('metadata/gamemaker_instance_scale_y = 0.5', content)
        self.assertIn('metadata/gamemaker_colour = 4294967295', content)
        self.assertIn('metadata/gamemaker_image_angle = 90', content)
        self.assertIn('metadata/gamemaker_image_xscale = 2', content)
        self.assertIn('metadata/gamemaker_image_yscale = 0.5', content)
        self.assertIn('metadata/gamemaker_image_blend = 16777215', content)
        self.assertIn('metadata/gamemaker_image_alpha = 1.0', content)
        self.assertIn('metadata/gamemaker_image_index = 3', content)
        self.assertIn('metadata/gamemaker_image_speed = 0.25', content)
        self.assertIn('metadata/gamemaker_object_id = {"name": "o_player"', content)
        self.assertIn('metadata/gamemaker_properties = [{"name": "hp", "value": 10}]', content)
        self.assertIn('metadata/gamemaker_has_creation_code = true', content)

    def test_instance_layer_reuses_object_scene_ext_resource(self):
        self._write_yyp(["r_reuse"], extra_resources=[("objects", "o_enemy")])
        self._write_object("o_enemy")
        self._write_object_scene("o_enemy")
        self._write_room("r_reuse", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {"name": "inst_enemy_a", "objectId": {"name": "o_enemy"}},
                    {"name": "inst_enemy_b", "objectId": {"name": "o_enemy"}},
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_reuse")

        self.assertEqual(content.count('path="res://objects/o_enemy/o_enemy.tscn"'), 1)
        self.assertIn('[node name="inst_enemy_a" parent="Instances" instance=ExtResource("1")]', content)
        self.assertIn('[node name="inst_enemy_b" parent="Instances" instance=ExtResource("1")]', content)

    def test_instance_layer_resolves_object_subfolder_path(self):
        self._write_yyp(["r_subfolder"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player", parent_path="folders/Objects/Game/Actors.yy")
        self._write_object_scene("o_player", "game", "actors")
        self._write_room("r_subfolder", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [{"name": "inst_player", "objectId": {"name": "o_player"}}],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_subfolder")

        self.assertIn(
            'path="res://objects/game/actors/o_player/o_player.tscn"',
            content,
        )

    def test_asset_layer_instances_sprite_graphic(self):
        self._write_yyp(["r_assets"], extra_resources=[("sprites", "s_decor")])
        self._write_sprite("s_decor")
        self._write_sprite_scene("s_decor")
        self._write_room("r_assets", layers=[
            {
                "%Name": "Assets",
                "resourceType": "GMRAssetLayer",
                "assets": [
                    {
                        "$GMRSpriteGraphic": "",
                        "%Name": "spr_decor_1",
                        "resourceType": "GMRSpriteGraphic",
                        "spriteId": {"name": "s_decor", "path": "sprites/s_decor/s_decor.yy"},
                        "x": 24,
                        "y": 48,
                        "rotation": 15,
                        "scaleX": 2,
                        "scaleY": 3,
                        "colour": 4294967295,
                        "headPosition": 4,
                        "animationSpeed": 0.5,
                    }
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_assets")

        self.assertIn('[ext_resource type="PackedScene" path="res://sprites/s_decor/s_decor.tscn" id="1"]', content)
        self.assertIn('[node name="spr_decor_1" parent="Assets" instance=ExtResource("1")]', content)
        self.assertIn('position = Vector2(24, 48)', content)
        self.assertIn('rotation_degrees = 15', content)
        self.assertIn('scale = Vector2(2, 3)', content)
        self.assertIn('modulate = Color(1, 1, 1, 1)', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "sprite"', content)
        self.assertIn('metadata/gamemaker_asset_sprite_name = "s_decor"', content)
        self.assertIn('metadata/gamemaker_asset_head_position = 4', content)
        self.assertIn('metadata/gamemaker_asset_animation_speed = 0.5', content)

    def test_asset_layer_classifies_unsupported_element_types_with_diagnostics(self):
        self._write_yyp(["r_elements"])
        self._write_room("r_elements", layers=[
            {
                "%Name": "MixedAssets",
                "resourceType": "GMRAssetLayer",
                "assets": [
                    {"%Name": "seq_intro", "resourceType": "GMRSequenceGraphic", "x": 1},
                    {"%Name": "ps_fx", "resourceType": "GMRParticleSystem", "x": 2},
                    {"%Name": "legacy_tile", "resourceType": "GMRTileGraphic", "x": 3},
                    {"%Name": "label", "resourceType": "GMRTextGraphic", "x": 4},
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_elements")

        self.assertIn('[node name="seq_intro" type="Node2D" parent="MixedAssets"]', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "sequence"', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "particle_system"', content)
        self.assertIn("metadata/gamemaker_particle_system_layer_element = true", content)
        self.assertIn('metadata/gamemaker_layer_element_type = "tile"', content)
        self.assertIn('metadata/gamemaker_layer_element_type = "undefined"', content)
        self.assertEqual(content.count("metadata/gamemaker_unsupported_asset = true"), 3)
        self.assertTrue(any(
            "GMRSequenceGraphic" in log and "layer element type sequence" in log
            for log in self.logs
        ))
        self.assertTrue(any(
            "GMRTextGraphic" in log and "layer element type undefined" in log
            for log in self.logs
        ))

    def test_ignored_asset_is_skipped_with_warning(self):
        self._write_yyp(["r_assets"], extra_resources=[("sprites", "s_decor")])
        self._write_sprite("s_decor")
        self._write_sprite_scene("s_decor")
        self._write_room("r_assets", layers=[
            {
                "%Name": "Assets",
                "resourceType": "GMRAssetLayer",
                "assets": [
                    {
                        "%Name": "ignored_decor",
                        "resourceType": "GMRSpriteGraphic",
                        "spriteId": {"name": "s_decor"},
                        "ignore": True,
                    }
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_assets")

        self.assertNotIn('[node name="ignored_decor"', content)
        self.assertTrue(any("Skipping ignored GameMaker asset ignored_decor" in log for log in self.logs))

    def test_ignored_instances_are_skipped_with_warning(self):
        self._write_yyp(["r_ignored"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player")
        self._write_object_scene("o_player")
        self._write_room("r_ignored", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {"name": "inst_ignored", "objectId": {"name": "o_player"}, "ignore": True}
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_ignored")

        self.assertNotIn('[node name="inst_ignored"', content)
        self.assertNotIn('[ext_resource type="PackedScene"', content)
        self.assertTrue(any(
            "Skipping ignored GameMaker room instance inst_ignored" in log
            for log in self.logs
        ))

    def test_unresolved_object_instance_emits_placeholder_with_warning(self):
        self._write_yyp(["r_missing"])
        self._write_room("r_missing", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {"name": "inst_missing", "objectId": {"name": "o_missing"}, "x": 10, "y": 20}
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_missing")

        self.assertNotIn('[ext_resource type="PackedScene"', content)
        self.assertIn('[node name="inst_missing" type="Node2D" parent="Instances"]', content)
        self.assertIn('position = Vector2(10, 20)', content)
        self.assertIn('metadata/gamemaker_placeholder = true', content)
        self.assertIn('metadata/gamemaker_unresolved_object_scene = true', content)
        self.assertTrue(any(
            "Could not resolve object scene" in log and "inst_missing" in log
            for log in self.logs
        ))

    def test_instance_creation_order_controls_layer_child_order(self):
        self._write_yyp(["r_order"], extra_resources=[("objects", "o_enemy")])
        self._write_object("o_enemy")
        self._write_object_scene("o_enemy")
        self._write_room(
            "r_order",
            instance_creation_order=[
                {"name": "inst_a", "path": "rooms/r_order/r_order.yy"},
                {"name": "inst_b", "path": "rooms/r_order/r_order.yy"},
            ],
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {"name": "inst_b", "objectId": {"name": "o_enemy"}},
                        {"name": "inst_a", "objectId": {"name": "o_enemy"}},
                    ],
                }
            ],
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_order")

        self.assertLess(
            content.index('[node name="inst_a" parent="Instances"'),
            content.index('[node name="inst_b" parent="Instances"'),
        )
        self.assertIn('metadata/gamemaker_instance_creation_order_index = 0', content)
        self.assertIn('metadata/gamemaker_instance_creation_order_index = 1', content)

    def test_room_root_emits_creation_code_metadata(self):
        self._write_yyp(["r_code"])
        room_creation_path = os.path.join(
            self.gm_dir, "rooms", "r_code", "RoomCreationCode.gml"
        )
        _write_file(room_creation_path, "// metadata only\n")
        self._write_room(
            "r_code",
            creation_code_file="RoomCreationCode.gml",
            inherit_code=True,
            is_dnd=True,
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_code")

        self.assertIn('metadata/gamemaker_creation_code_file = "RoomCreationCode.gml"', content)
        self.assertIn(
            'metadata/gamemaker_creation_code_source_path = ' + json.dumps(room_creation_path),
            content,
        )
        self.assertIn('metadata/gamemaker_has_creation_code = true', content)
        self.assertIn('metadata/gamemaker_inherit_code = true', content)
        self.assertIn('metadata/gamemaker_is_dnd = true', content)
        self.assertIn('metadata/gamemaker_creation_code_file_exists = true', content)
        self.assertIn(
            'metadata/gamemaker_execution_order = ["object_create", "instance_creation_code", "game_start", "room_creation_code", "room_start"]',
            content,
        )
        self.assertIn(
            'metadata/gamemaker_room_creation_code_execution_phase = "room_creation_code"',
            content,
        )
        self.assertIn('metadata/gamemaker_room_creation_code_execution_phase_index = 3', content)
        self.assertIn(
            '[ext_resource type="Script" path="res://rooms/r_code/r_code.gd" id="gm_room_runtime"]',
            content,
        )
        script = self._read_room_script("r_code")
        self.assertIn('extends "res://gm2godot/gml_room_node.gd"', script)
        self.assertIn("func _gm2godot_room_creation_code():", script)

    def test_room_creation_code_missing_logs_info_and_marks_missing(self):
        self._write_yyp(["r_missing_code"])
        missing_path = os.path.join(
            self.gm_dir, "rooms", "r_missing_code", "MissingCreationCode.gml"
        )
        self._write_room(
            "r_missing_code",
            creation_code_file="MissingCreationCode.gml",
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_missing_code")

        self.assertIn(
            'metadata/gamemaker_creation_code_source_path = ' + json.dumps(missing_path),
            content,
        )
        self.assertIn('metadata/gamemaker_creation_code_file_exists = false', content)
        missing_logs = [
            log
            for log in self.logs
            if (
            "Missing GameMaker room creation code file" in log
            and "r_missing_code" in log
            and missing_path in log
            )
        ]
        self.assertTrue(missing_logs)
        self.assertTrue(all(log.startswith("Info:") for log in missing_logs))

    def test_rejects_unsafe_room_creation_code_paths_with_owner_diagnostics(self):
        room_names = [
            "r_traversal",
            "r_absolute",
            "r_drive_absolute",
            "r_drive_relative",
            "r_unc",
            "r_nul",
            "r_symlink",
        ]
        self._write_yyp(room_names)

        outside_directory = os.path.dirname(self.gm_dir)
        outside_path = os.path.join(
            outside_directory,
            f"{os.path.basename(self.gm_dir)}_outside_room_code.gml",
        )
        _write_file(outside_path, "global.outside_room_code_was_read = true;\n")
        self.addCleanup(
            lambda: os.path.isfile(outside_path) and os.unlink(outside_path)
        )

        traversal_room_directory = os.path.join(
            self.gm_dir,
            "rooms",
            "r_traversal",
        )
        traversal_path = os.path.relpath(outside_path, traversal_room_directory)
        unsafe_paths = {
            "r_traversal": traversal_path,
            "r_absolute": outside_path,
            "r_drive_absolute": r"C:\Games\Outside\RoomCreationCode.gml",
            "r_drive_relative": r"C:Outside\RoomCreationCode.gml",
            "r_unc": r"\\server\share\RoomCreationCode.gml",
            "r_nul": "RoomCreationCode\0.gml",
        }
        for room_name, source_path in unsafe_paths.items():
            self._write_room(room_name, creation_code_file=source_path)

        self._write_room("r_symlink", creation_code_file="LinkedRoomCode.gml")
        linked_path = os.path.join(
            self.gm_dir,
            "rooms",
            "r_symlink",
            "LinkedRoomCode.gml",
        )
        try:
            os.symlink(outside_path, linked_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        diagnostics = DiagnosticCollector()
        self._make_converter(diagnostics=diagnostics).convert_all()

        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), len(room_names), rejected)
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {
                f"rooms/{room_name}/{room_name}.yy"
                for room_name in room_names
            },
        )
        self.assertTrue(
            all(diagnostic.resource_type == "room" for diagnostic in rejected)
        )
        self.assertTrue(
            all(
                diagnostic.manifest_entry == "creationCodeFile"
                for diagnostic in rejected
            )
        )
        for room_name in room_names:
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        self.godot_dir,
                        "rooms",
                        room_name,
                        room_name + ".gd",
                    )
                ),
                room_name,
            )
            scene = self._read_scene(room_name)
            self.assertIn(
                'metadata/gamemaker_creation_code_source_path = ""',
                scene,
            )
            self.assertIn(
                "metadata/gamemaker_creation_code_file_exists = false",
                scene,
            )

    def test_accepts_project_relative_room_creation_code_forms(self):
        room_names = ["r_rooted", "r_placeholder", "r_backslash"]
        self._write_yyp(room_names)
        source_paths = {
            "r_rooted": "rooms/r_rooted/RoomCreationCode.gml",
            "r_placeholder": (
                "${project_dir}/rooms/r_placeholder/RoomCreationCode.gml"
            ),
            "r_backslash": r"rooms\r_backslash\RoomCreationCode.gml",
        }
        for room_name, source_path in source_paths.items():
            _write_file(
                os.path.join(
                    self.gm_dir,
                    "rooms",
                    room_name,
                    "RoomCreationCode.gml",
                ),
                f'global.{room_name}_code = "converted";\n',
            )
            self._write_room(room_name, creation_code_file=source_path)

        self._make_converter().convert_all()

        for room_name in room_names:
            script = self._read_room_script(room_name)
            self.assertIn(f'"{room_name}_code"', script)
            self.assertIn('"converted"', script)

    def test_inherited_room_creation_code_stays_parent_relative(self):
        self._write_yyp(["r_parent", "r_child"])
        _write_file(
            os.path.join(
                self.gm_dir,
                "rooms",
                "r_parent",
                "RoomCreationCode.gml",
            ),
            'global.inherited_room_code = "parent";\n',
        )
        self._write_room(
            "r_parent",
            creation_code_file="RoomCreationCode.gml",
        )
        self._write_room(
            "r_child",
            inherit_code=True,
            parent_room={
                "name": "r_parent",
                "path": "rooms/r_parent/r_parent.yy",
            },
        )

        self._make_converter().convert_all()

        child_script = self._read_room_script("r_child")
        self.assertIn('"inherited_room_code"', child_script)
        self.assertIn('"parent"', child_script)

    def test_rejects_instance_name_sidecar_traversal(self):
        self._write_yyp(["r_instance_escape"])
        room_directory = os.path.join(
            self.gm_dir,
            "rooms",
            "r_instance_escape",
        )
        bridge_directory = os.path.join(
            room_directory,
            "InstanceCreationCode_bridge",
        )
        outside_stem = os.path.join(
            os.path.dirname(self.gm_dir),
            f"{os.path.basename(self.gm_dir)}_outside_instance_code",
        )
        outside_path = outside_stem + ".gml"
        _write_file(outside_path, "outside_instance_code_was_read = true;\n")
        self.addCleanup(
            lambda: os.path.isfile(outside_path) and os.unlink(outside_path)
        )
        instance_name = "bridge/" + os.path.relpath(
            outside_stem,
            bridge_directory,
        ).replace(os.sep, "/")
        self._write_room(
            "r_instance_escape",
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {
                            "name": instance_name,
                            "hasCreationCode": True,
                        }
                    ],
                }
            ],
        )
        os.makedirs(bridge_directory)

        diagnostics = DiagnosticCollector()
        self._make_converter(diagnostics=diagnostics).convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "rooms",
                    "r_instance_escape",
                    "r_instance_escape.gd",
                )
            )
        )
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "rooms/r_instance_escape/r_instance_escape.yy",
        )
        self.assertEqual(
            rejected[0].manifest_entry,
            "layers[].instances[].name",
        )

    def test_rejects_instance_name_that_reaches_another_project_directory(self):
        self._write_yyp(["r_instance_cross_owner"])
        self._write_room(
            "r_instance_cross_owner",
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {
                            "name": "bridge/../../shared/Leak",
                            "hasCreationCode": True,
                        }
                    ],
                }
            ],
        )
        _write_file(
            os.path.join(self.gm_dir, "rooms", "shared", "Leak.gml"),
            "cross_owner_instance_code_was_read = true;\n",
        )
        diagnostics = DiagnosticCollector()

        self._make_converter(diagnostics=diagnostics).convert_all()

        room_script = os.path.join(
            self.godot_dir,
            "rooms",
            "r_instance_cross_owner",
            "r_instance_cross_owner.gd",
        )
        self.assertFalse(os.path.exists(room_script))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "rooms/r_instance_cross_owner/r_instance_cross_owner.yy",
        )
        self.assertEqual(
            rejected[0].manifest_entry,
            "layers[].instances[].name",
        )

    def test_instance_name_aliases_are_rejected_but_safe_name_is_transpiled(self):
        room_name = "r_instance_components"
        self._write_yyp([room_name])
        instances = [
            {"name": "bridge/../alias", "hasCreationCode": True},
            {"name": r"bridge\..\alias", "hasCreationCode": True},
            {"name": ".", "hasCreationCode": True},
            {"name": "..", "hasCreationCode": True},
            {"name": "inst_safe", "hasCreationCode": True},
        ]
        room_path = self._write_room(
            room_name,
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": instances,
                }
            ],
        )
        room_directory = os.path.dirname(room_path)
        unsafe_sources = {
            "alias.gml": "unsafe_component_alias = 1;\n",
            "InstanceCreationCode_..gml": "unsafe_component_dot = 1;\n",
            "InstanceCreationCode_...gml": "unsafe_component_dotdot = 1;\n",
        }
        for filename, source in unsafe_sources.items():
            _write_file(os.path.join(room_directory, filename), source)
        _write_file(
            os.path.join(
                room_directory,
                "InstanceCreationCode_inst_safe.gml",
            ),
            "safe_instance_component = 1;\n",
        )
        diagnostics = DiagnosticCollector()

        self._make_converter(diagnostics=diagnostics).convert_all()

        script = self._read_room_script(room_name)
        self.assertIn("safe_instance_component", script)
        self.assertNotIn("unsafe_component_alias", script)
        self.assertNotIn("unsafe_component_dot", script)
        self.assertNotIn("unsafe_component_dotdot", script)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 4, rejected)
        self.assertTrue(
            all(
                diagnostic.source_path
                == f"rooms/{room_name}/{room_name}.yy"
                for diagnostic in rejected
            )
        )
        self.assertTrue(
            all(
                diagnostic.manifest_entry == "layers[].instances[].name"
                for diagnostic in rejected
            )
        )

    def test_two_argument_instance_creation_code_infers_confined_project_root(self):
        room_name = "r_direct_helper"
        room_path = self._write_room(room_name)
        source_path = os.path.join(
            os.path.dirname(room_path),
            "InstanceCreationCode_inst_safe.gml",
        )
        _write_file(source_path, "safe_direct_helper = true;\n")
        room = IndexedRoom(
            name=room_name,
            yy_path=room_path,
            yyp_path=f"rooms/{room_name}/{room_name}.yy",
            godot_path=f"res://rooms/{room_name}/{room_name}.tscn",
        )

        metadata = resolve_instance_creation_code(
            room,
            {"name": "inst_safe", "hasCreationCode": True},
        )

        self.assertEqual(metadata.source_path, source_path)
        self.assertTrue(metadata.exists)
        self.assertFalse(metadata.path_rejected)

    def test_two_argument_instance_creation_code_rejects_unsafe_root_inference(self):
        absolute_owner = os.path.join(
            self.gm_dir,
            "room_resources",
            "r_direct_helper.yy",
        )
        cases = (
            ("relative", "rooms/r_direct_helper/r_direct_helper.yy"),
            ("missing_rooms_component", absolute_owner),
        )
        for label, owner_path in cases:
            with self.subTest(case=label):
                warnings: list[str] = []
                room = IndexedRoom(
                    name="r_direct_helper",
                    yy_path=owner_path,
                    yyp_path="rooms/r_direct_helper/r_direct_helper.yy",
                    godot_path="res://rooms/r_direct_helper/r_direct_helper.tscn",
                )

                metadata = resolve_instance_creation_code(
                    room,
                    {"name": "inst_safe", "hasCreationCode": True},
                    warn_callback=warnings.append,
                )

                self.assertEqual(metadata.source_path, "")
                self.assertFalse(metadata.exists)
                self.assertTrue(metadata.path_rejected)
                self.assertEqual(len(warnings), 1, warnings)
                self.assertIn(owner_path, warnings[0])
                self.assertIn("layers[].instances[].name", warnings[0])

    def test_instance_emits_creation_code_metadata(self):
        self._write_yyp(["r_instance_code"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player")
        self._write_object_scene("o_player")
        instance_code_path = os.path.join(
            self.gm_dir,
            "rooms",
            "r_instance_code",
            "InstanceCreationCode_inst_player.gml",
        )
        _write_file(instance_code_path, "// metadata only\n")
        self._write_room("r_instance_code", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {
                        "name": "inst_player",
                        "objectId": {"name": "o_player"},
                        "hasCreationCode": True,
                        "inheritCode": True,
                        "isDnd": True,
                    }
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_instance_code")

        self.assertIn('metadata/gamemaker_has_creation_code = true', content)
        self.assertIn('metadata/gamemaker_inherit_code = true', content)
        self.assertIn('metadata/gamemaker_is_dnd = true', content)
        self.assertIn(
            'metadata/gamemaker_creation_code_source_path = ' + json.dumps(instance_code_path),
            content,
        )
        self.assertIn('metadata/gamemaker_creation_code_file_exists = true', content)
        self.assertIn(
            'metadata/gamemaker_creation_code_execution_phase = "instance_creation_code"',
            content,
        )
        self.assertIn('metadata/gamemaker_creation_code_execution_phase_index = 1', content)
        self.assertIn(
            '[ext_resource type="Script" path="res://rooms/r_instance_code/r_instance_code.gd" id="gm_room_runtime"]',
            content,
        )
        script = self._read_room_script("r_instance_code")
        self.assertIn("func _gm2godot_run_instance_creation_code(_gm_instance):", script)
        self.assertIn(
            "func _gm2godot_instance_creation_code_inst_player(_gm_instance):",
            script,
        )
        self.assertIn(json.dumps(instance_code_path), script)

    def test_room_and_instance_creation_code_are_transpiled_with_correct_scope(self):
        self._write_yyp(["r_exec"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player")
        self._write_object_scene("o_player")
        room_creation_path = os.path.join(
            self.gm_dir,
            "rooms",
            "r_exec",
            "RoomCreationCode.gml",
        )
        instance_code_path = os.path.join(
            self.gm_dir,
            "rooms",
            "r_exec",
            "InstanceCreationCode_inst_player.gml",
        )
        _write_file(room_creation_path, 'room_trace = "room creation";\n')
        _write_file(instance_code_path, 'x = 42; custom_value = "instance creation";\n')
        self._write_room(
            "r_exec",
            creation_code_file="RoomCreationCode.gml",
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {
                            "name": "inst_player",
                            "objectId": {"name": "o_player"},
                            "hasCreationCode": True,
                        }
                    ],
                }
            ],
        )

        self._make_converter().convert_all()
        script = self._read_room_script("r_exec")

        self.assertIn("func _gm2godot_room_creation_code():", script)
        self.assertIn(
            'GMRuntime.gml_struct_set(GMRuntime.gml_global_scope(), "room_trace", "room creation")',
            script,
        )
        self.assertIn("func _gm2godot_run_instance_creation_code(_gm_instance):", script)
        self.assertIn(
            'GMRuntime.gml_variable_instance_set(_gm_instance, "x", 42)',
            script,
        )
        self.assertIn(
            'GMRuntime.gml_variable_instance_set(_gm_instance, "custom_value", "instance creation")',
            script,
        )

    def test_instance_creation_code_missing_logs_info_and_marks_missing(self):
        self._write_yyp(["r_missing_instance_code"], extra_resources=[("objects", "o_player")])
        self._write_object("o_player")
        self._write_object_scene("o_player")
        missing_path = os.path.join(
            self.gm_dir,
            "rooms",
            "r_missing_instance_code",
            "InstanceCreationCode_inst_player.gml",
        )
        self._write_room("r_missing_instance_code", layers=[
            {
                "%Name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {
                        "name": "inst_player",
                        "objectId": {"name": "o_player"},
                        "hasCreationCode": True,
                    }
                ],
            }
        ])

        self._make_converter().convert_all()
        content = self._read_scene("r_missing_instance_code")

        self.assertIn(
            'metadata/gamemaker_creation_code_source_path = ' + json.dumps(missing_path),
            content,
        )
        self.assertIn('metadata/gamemaker_creation_code_file_exists = false', content)
        missing_logs = [
            log
            for log in self.logs
            if (
            "Missing GameMaker instance creation code file" in log
            and "inst_player" in log
            and "r_missing_instance_code" in log
            and missing_path in log
            )
        ]
        self.assertTrue(missing_logs)
        self.assertTrue(all(log.startswith("Info:") for log in missing_logs))

    def test_execution_metadata_preserves_lifecycle_order(self):
        self._write_yyp(["r_lifecycle"], extra_resources=[("objects", "o_enemy")])
        self._write_object("o_enemy")
        self._write_object_scene("o_enemy")
        _write_file(
            os.path.join(self.gm_dir, "rooms", "r_lifecycle", "InstanceCreationCode_inst_a.gml"),
            "// metadata only\n",
        )
        _write_file(
            os.path.join(self.gm_dir, "rooms", "r_lifecycle", "InstanceCreationCode_inst_b.gml"),
            "// metadata only\n",
        )
        self._write_room(
            "r_lifecycle",
            instance_creation_order=[
                {"name": "inst_a", "path": "rooms/r_lifecycle/r_lifecycle.yy"},
                {"name": "inst_b", "path": "rooms/r_lifecycle/r_lifecycle.yy"},
            ],
            layers=[
                {
                    "%Name": "Instances",
                    "resourceType": "GMRInstanceLayer",
                    "instances": [
                        {"name": "inst_b", "objectId": {"name": "o_enemy"}, "hasCreationCode": True},
                        {"name": "inst_a", "objectId": {"name": "o_enemy"}, "hasCreationCode": True},
                    ],
                }
            ],
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_lifecycle")

        self.assertIn(
            'metadata/gamemaker_execution_order = ["object_create", "instance_creation_code", "game_start", "room_creation_code", "room_start"]',
            content,
        )
        self.assertIn('metadata/gamemaker_instance_creation_order = ["inst_a", "inst_b"]', content)
        self.assertLess(
            content.index('[node name="inst_a" parent="Instances"'),
            content.index('[node name="inst_b" parent="Instances"'),
        )
        self.assertIn('metadata/gamemaker_instance_creation_order_index = 0', content)
        self.assertIn('metadata/gamemaker_instance_creation_order_index = 1', content)
        self.assertEqual(
            content.count('metadata/gamemaker_creation_code_execution_phase = "instance_creation_code"'),
            2,
        )
        self.assertEqual(
            content.count('metadata/gamemaker_creation_code_execution_phase_index = 1'),
            2,
        )

    def test_visible_view_emits_camera2d_metadata(self):
        self._write_yyp(["r_camera"])
        self._write_room(
            "r_camera",
            views=[
                {
                    "visible": True,
                    "xview": 100,
                    "yview": 200,
                    "wview": 640,
                    "hview": 360,
                    "xport": 0,
                    "yport": 0,
                    "wport": 1280,
                    "hport": 720,
                    "objectId": {"name": "o_player", "path": "objects/o_player/o_player.yy"},
                    "hborder": 32,
                    "vborder": 16,
                    "hspeed": -1,
                    "vspeed": 4,
                }
            ],
            view_settings={"enableViews": True},
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_camera")

        self.assertIn('[node name="ViewCamera" type="Camera2D" parent="."]', content)
        self.assertIn('position = Vector2(420, 380)', content)
        self.assertIn('enabled = true', content)
        self.assertIn('metadata/gamemaker_view_visible = true', content)
        self.assertIn('limit_left = 100', content)
        self.assertIn('limit_top = 200', content)
        self.assertIn('limit_right = 740', content)
        self.assertIn('limit_bottom = 560', content)
        self.assertIn('zoom = Vector2(2, 2)', content)
        self.assertIn('metadata/gamemaker_view_object_name = "o_player"', content)
        self.assertFalse(any("follows object o_player" in log for log in self.logs))

    def test_multiple_visible_views_disable_additional_cameras_and_warn(self):
        self._write_yyp(["r_cameras"])
        self._write_room(
            "r_cameras",
            views=[
                {"visible": True, "xview": 0, "yview": 0, "wview": 320, "hview": 180},
                {"visible": True, "xview": 320, "yview": 0, "wview": 320, "hview": 180},
            ],
            view_settings={"enableViews": True},
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_cameras")

        self.assertIn('[node name="ViewCamera" type="Camera2D" parent="."]\nposition = Vector2(160, 90)\nenabled = true', content)
        self.assertIn('[node name="ViewCamera_2" type="Camera2D" parent="."]\nposition = Vector2(480, 90)\nenabled = false', content)
        self.assertEqual(content.count("metadata/gamemaker_view_visible = true"), 2)
        self.assertTrue(any("multiple visible GameMaker views" in log for log in self.logs))

    def test_room_inheritance_resolves_settings_and_layers(self):
        self._write_yyp(["r_parent", "r_child"], room_order=["r_child"])
        self._write_room("r_parent", width=320, height=180, layers=[
            {"%Name": "ParentLayer", "resourceType": "GMRInstanceLayer"}
        ])
        self._write_room(
            "r_child",
            width=999,
            height=999,
            inherit_room_settings=True,
            inherit_layers=True,
            parent_room={"name": "r_parent", "path": "rooms/r_parent/r_parent.yy"},
            layers=[{"%Name": "ChildLayer", "resourceType": "GMRInstanceLayer"}],
        )

        self._make_converter().convert_all()
        content = self._read_scene("r_child")

        self.assertIn('metadata/gamemaker_room_width = 320', content)
        self.assertIn('metadata/gamemaker_room_height = 180', content)
        self.assertIn('metadata/gamemaker_parent_room = {"name": "r_parent"', content)
        self.assertIn('[node name="ParentLayer" type="Node2D" parent="."]', content)
        self.assertIn('[node name="ChildLayer" type="Node2D" parent="."]', content)

    def test_sets_project_startup_scene_to_first_room_order_node(self):
        self._write_yyp(["r_second", "r_first"], room_order=["r_first", "r_second"])
        self._write_room("r_second")
        self._write_room("r_first")
        self._write_project_godot(
            '[application]\n'
            'config/name="Existing"\n'
            'run/main_scene="res://old.tscn"\n'
            '\n'
            '[display]\n'
            'window/size/viewport_width=1280\n'
        )

        self._make_converter().convert_all()

        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('run/main_scene="res://rooms/r_first/r_first.tscn"', content)
        self.assertNotIn('run/main_scene="res://old.tscn"', content)
        self.assertIn('config/name="Existing"', content)
        self.assertIn('[display]', content)
        self.assertIn('window/size/viewport_width=1280', content)
        self.assertTrue(any("startup scene" in log.lower() for log in self.logs))
        self.assertTrue(any("r_first" in log for log in self.logs))

    def test_sets_project_startup_scene_to_first_room_subfolder_path(self):
        self._write_yyp(["r_intro"])
        self._write_room("r_intro", parent_path="folders/Rooms/Game/Intro.yy")
        self._write_project_godot()

        self._make_converter().convert_all()

        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            'run/main_scene="res://rooms/game/intro/r_intro/r_intro.tscn"',
            content,
        )
        self.assertIn('config/name="Existing"', content)

    def test_missing_room_order_nodes_sets_startup_scene_from_sorted_fallback(self):
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            "{\n"
            '  "resources":[\n'
            '    {"id":{"name":"r_z","path":"rooms/r_z/r_z.yy",}},\n'
            '    {"id":{"name":"r_a","path":"rooms/r_a/r_a.yy",}}\n'
            "  ],\n"
            '  "resourceType":"GMProject"\n'
            "}\n",
        )
        self._write_room("r_z")
        self._write_room("r_a")
        self._write_project_godot()

        self._make_converter().convert_all()

        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('run/main_scene="res://rooms/r_a/r_a.tscn"', content)
        self.assertTrue(any("RoomOrderNodes missing" in log for log in self.logs))
        self.assertTrue(any("fallback" in log.lower() for log in self.logs))

    def test_no_rooms_does_not_crash_or_create_output(self):
        self._make_converter().convert_all()

        self.assertFalse(os.path.exists(os.path.join(self.godot_dir, "rooms")))
        self.assertTrue(any("completed" in log.lower() for log in self.logs))

    def test_no_generated_room_scene_leaves_main_scene_unchanged(self):
        self._write_project_godot(
            '[application]\n'
            'config/name="Existing"\n'
            'run/main_scene="res://keep.tscn"\n'
        )

        self._make_converter().convert_all()

        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('run/main_scene="res://keep.tscn"', content)
        self.assertTrue(any("No room scene generated" in log for log in self.logs))
        self.assertTrue(any("main_scene unchanged" in log for log in self.logs))

    def test_stops_without_writing_scene(self):
        self._write_yyp(["r_test"])
        self._write_room("r_test")
        self._write_project_godot(
            '[application]\n'
            'run/main_scene="res://keep.tscn"\n'
        )

        self._make_converter(conversion_running=lambda: False).convert_all()

        self.assertFalse(os.path.exists(os.path.join(
            self.godot_dir, "rooms", "r_test", "r_test.tscn"
        )))
        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('run/main_scene="res://keep.tscn"', content)
        self.assertTrue(any("stopped" in log.lower() for log in self.logs))


if __name__ == "__main__":
    unittest.main()
