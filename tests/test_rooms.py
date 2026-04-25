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


def _make_yyp(room_names, room_order=None):
    room_order = room_order or room_names
    resources = []
    for name in room_names:
        resources.append(
            '    {{"id":{{"name":"{name}",'
            '"path":"rooms/{name}/{name}.yy",}},}}'.format(name=name)
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
                  persistent=False, volume=1.0, physics_world=False):
    persistent_value = "true" if persistent else "false"
    physics_world_value = "true" if physics_world else "false"
    return (
        '{{\n'
        '  "$GMRoom":"v1",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "creationCodeFile":"",\n'
        '  "inheritCode":false,\n'
        '  "inheritCreationOrder":false,\n'
        '  "inheritLayers":false,\n'
        '  "instanceCreationOrder":[],\n'
        '  "layers":[],\n'
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
    )


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

    def _write_yyp(self, room_names, room_order=None):
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            _make_yyp(room_names, room_order),
        )

    def _write_project_godot(self, content='[application]\nconfig/name="Existing"\n'):
        _write_file(os.path.join(self.godot_dir, "project.godot"), content)

    def _write_room(self, name, **kwargs):
        room_path = os.path.join(self.gm_dir, "rooms", name, name + ".yy")
        _write_file(room_path, _make_room_yy(name, **kwargs))
        return room_path

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
