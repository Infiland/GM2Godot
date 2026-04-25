import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.rooms import RoomConverter


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _make_yyp(room_names, room_order=None, extra_resources=None):
    room_order = room_order or room_names
    extra_resources = extra_resources or []
    resources = []
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
    order_entries = []
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


def _make_room_yy(name, parent_path="folders/Rooms.yy", width=1024, height=768,
                  persistent=False, volume=1.0, physics_world=False, layers=None,
                  instance_creation_order=None):
    persistent_value = "true" if persistent else "false"
    physics_world_value = "true" if physics_world else "false"
    layers_json = json.dumps(layers if layers is not None else [])
    instance_creation_order_json = json.dumps(instance_creation_order or [])
    return (
        '{{\n'
        '  "$GMRoom":"v1",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "creationCodeFile":"",\n'
        '  "inheritCode":false,\n'
        '  "inheritCreationOrder":false,\n'
        '  "inheritLayers":false,\n'
        '  "instanceCreationOrder":{instance_creation_order_json},\n'
        '  "layers":{layers_json},\n'
        '  "parent":{{"name":"Rooms","path":"{parent_path}",}},\n'
        '  "parentRoom":null,\n'
        '  "physicsSettings":{{\n'
        '    "PhysicsWorld":{physics_world},\n'
        '    "PhysicsWorldGravityX":0.0,\n'
        '    "PhysicsWorldGravityY":10.0,\n'
        '    "PhysicsWorldPixToMetres":0.1,\n'
        '  }},\n'
        '  "resourceType":"GMRoom",\n'
        '  "roomSettings":{{\n'
        '    "Width":{width},\n'
        '    "Height":{height},\n'
        '    "persistent":{persistent},\n'
        '  }},\n'
        '  "views":[],\n'
        '  "viewSettings":{{"enableViews":false,}},\n'
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
    )


def _make_object_yy(name, parent_path="folders/Objects.yy"):
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


def _make_sprite_yy(name, parent_path="folders/Sprites.yy"):
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
    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
        self.progress = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, conversion_running=lambda: True):
        return RoomConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda value: self.progress.append(value),
            conversion_running=conversion_running,
            max_workers=1,
        )

    def _write_yyp(self, room_names, room_order=None, extra_resources=None):
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            _make_yyp(room_names, room_order, extra_resources),
        )

    def _write_project_godot(self, content='[application]\nconfig/name="Existing"\n'):
        _write_file(os.path.join(self.godot_dir, "project.godot"), content)

    def _write_room(self, name, **kwargs):
        room_path = os.path.join(self.gm_dir, "rooms", name, name + ".yy")
        _write_file(room_path, _make_room_yy(name, **kwargs))
        return room_path

    def _write_object(self, name, parent_path="folders/Objects.yy"):
        object_path = os.path.join(self.gm_dir, "objects", name, name + ".yy")
        _write_file(object_path, _make_object_yy(name, parent_path))
        return object_path

    def _write_object_scene(self, name, *subfolders):
        scene_path = os.path.join(
            self.godot_dir,
            "objects",
            *subfolders,
            name,
            name + ".tscn",
        )
        _write_file(scene_path, '[gd_scene format=3]\n\n[node name="{}" type="Node2D"]\n'.format(name))
        return scene_path

    def _write_sprite(self, name, parent_path="folders/Sprites.yy"):
        sprite_path = os.path.join(self.gm_dir, "sprites", name, name + ".yy")
        _write_file(sprite_path, _make_sprite_yy(name, parent_path))
        return sprite_path

    def _write_sprite_scene(self, name, *subfolders):
        scene_path = os.path.join(
            self.godot_dir,
            "sprites",
            *subfolders,
            name,
            name + ".tscn",
        )
        _write_file(scene_path, '[gd_scene format=3]\n\n[node name="{}" type="Area2D"]\n'.format(name))
        return scene_path

    def _read_scene(self, room_name, *subfolders):
        tscn_path = os.path.join(
            self.godot_dir,
            "rooms",
            *subfolders,
            room_name,
            room_name + ".tscn",
        )
        with open(tscn_path, "r", encoding="utf-8") as f:
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

        self.assertIn('[gd_scene format=3]', content)
        self.assertIn('[node name="r_test" type="Node2D"]', content)
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
        self.assertEqual(self.progress[-1], 100)
        self.assertTrue(any("r_test" in log for log in self.logs))

    def test_preserves_room_subfolders(self):
        self._write_yyp(["r_intro"])
        self._write_room("r_intro", parent_path="folders/Rooms/Game/Intro.yy")

        self._make_converter().convert_all()

        self.assertTrue(os.path.isfile(os.path.join(
            self.godot_dir,
            "rooms",
            "Game",
            "Intro",
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
        self.assertIn('z_index = -100', content)
        self.assertIn('metadata/gamemaker_layer_type = "GMRInstanceLayer"', content)
        self.assertIn('metadata/gamemaker_layer_depth = 100', content)
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
        self.assertIn('modulate = Color(1, 1, 1, 1)', content)
        self.assertIn('metadata/gamemaker_background_visual_type = "sprite"', content)

    def test_background_layer_preserves_scrolling_tiling_metadata_and_warns(self):
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
        self.assertIn('metadata/gamemaker_background_stretch = true', content)
        self.assertIn('metadata/gamemaker_background_animation_fps = 12', content)
        self.assertTrue(any(
            "scrolling/tiling" in log and "MovingBackground" in log
            for log in self.logs
        ))

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

        self.assertIn('[node name="Depth200" type="Node2D" parent="."]\nvisible = true\nz_index = -200', content)
        self.assertIn('[node name="Depth100" type="Node2D" parent="."]\nvisible = true\nz_index = -100', content)
        self.assertIn('[node name="Depth0" type="Node2D" parent="."]\nvisible = true\nz_index = 0', content)
        self.assertIn('[node name="DepthMinus100" type="Node2D" parent="."]\nvisible = true\nz_index = 100', content)

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

        self.assertIn('[gd_scene format=3 load_steps=2]', content)
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
        self.assertIn('metadata/gamemaker_instance_object_name = "o_player"', content)
        self.assertIn('metadata/gamemaker_colour = 4294967295', content)
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
        self._write_object_scene("o_player", "Game", "Actors")
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
            'path="res://objects/Game/Actors/o_player/o_player.tscn"',
            content,
        )

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
            'run/main_scene="res://rooms/Game/Intro/r_intro/r_intro.tscn"',
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
