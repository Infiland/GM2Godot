import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.resource_index import GameMakerResourceIndex


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _resource_entry(kind, name):
    return (
        '    {{"id":{{"name":"{name}",'
        '"path":"{kind}/{name}/{name}.yy",}},}}'
    ).format(kind=kind, name=name)


def _room_order_entry(name):
    return (
        '    {{"roomId":{{"name":"{name}",'
        '"path":"rooms/{name}/{name}.yy",}},}}'
    ).format(name=name)


def _make_yyp(resources, room_order=None):
    room_order = room_order or []
    resource_lines = ",\n".join(
        _resource_entry(kind, name) for kind, name in resources
    )
    room_order_lines = ",\n".join(_room_order_entry(name) for name in room_order)
    return (
        "{\n"
        f'  "resources":[\n{resource_lines},\n  ],\n'
        f'  "RoomOrderNodes":[\n{room_order_lines},\n  ],\n'
        '  "resourceType":"GMProject",\n'
        "}\n"
    )


def _make_room_yy(name, parent_path="folders/Rooms.yy"):
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
        '  "isDnd":false,\n'
        '  "layers":[],\n'
        '  "parent":{{"name":"Rooms","path":"{parent_path}",}},\n'
        '  "parentRoom":null,\n'
        '  "physicsSettings":{{"PhysicsWorld":false,}},\n'
        '  "resourceType":"GMRoom",\n'
        '  "roomSettings":{{"Width":640,"Height":480,"persistent":false,}},\n'
        '  "views":[],\n'
        '  "viewSettings":{{"enableViews":false,}},\n'
        '}}\n'
    ).format(name=name, parent_path=parent_path)


def _make_minimal_yy(name, resource_type, parent_name, parent_path):
    return (
        '{{\n'
        '  "name":"{name}",\n'
        '  "parent":{{"name":"{parent_name}","path":"{parent_path}",}},\n'
        '  "resourceType":"{resource_type}",\n'
        '}}\n'
    ).format(
        name=name,
        parent_name=parent_name,
        parent_path=parent_path,
        resource_type=resource_type,
    )


class TestGameMakerResourceIndex(unittest.TestCase):
    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _build_index(self):
        index = GameMakerResourceIndex(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        return index.build()

    def _write_yyp(self, resources, room_order=None):
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            _make_yyp(resources, room_order),
        )

    def _write_room(self, name, parent_path="folders/Rooms.yy", content=None):
        _write_file(
            os.path.join(self.gm_dir, "rooms", name, name + ".yy"),
            content if content is not None else _make_room_yy(name, parent_path),
        )

    def _write_resource(self, kind, name, parent_path, resource_type):
        parent_name = kind.capitalize()
        _write_file(
            os.path.join(self.gm_dir, kind, name, name + ".yy"),
            _make_minimal_yy(name, resource_type, parent_name, parent_path),
        )

    def test_indexes_yyp_resources_and_preserves_room_order(self):
        self._write_yyp(
            [("rooms", "r_second"), ("rooms", "r_first")],
            room_order=["r_first", "r_second"],
        )
        self._write_room("r_first")
        self._write_room("r_second")

        index = self._build_index()

        self.assertEqual(
            [room.name for room in index.ordered_rooms()],
            ["r_first", "r_second"],
        )
        self.assertEqual(index.first_room().name, "r_first")
        self.assertEqual(
            index.resolve_gm_path("rooms", "r_first"),
            os.path.join(self.gm_dir, "rooms", "r_first", "r_first.yy"),
        )

    def test_resolves_resource_gm_paths_for_supported_kinds(self):
        self._write_yyp([
            ("rooms", "r_test"),
            ("objects", "o_player"),
            ("sprites", "s_player"),
            ("tilesets", "ts_ground"),
        ], room_order=["r_test"])
        self._write_room("r_test")
        self._write_resource("objects", "o_player", "folders/Objects.yy", "GMObject")
        self._write_resource("sprites", "s_player", "folders/Sprites.yy", "GMSprite")
        self._write_resource("tilesets", "ts_ground", "folders/Tile Sets.yy", "GMTileSet")

        index = self._build_index()

        self.assertTrue(index.resolve_gm_path("rooms", "r_test").endswith(
            os.path.join("rooms", "r_test", "r_test.yy")
        ))
        self.assertTrue(index.resolve_gm_path("objects", "o_player").endswith(
            os.path.join("objects", "o_player", "o_player.yy")
        ))
        self.assertTrue(index.resolve_gm_path("sprites", "s_player").endswith(
            os.path.join("sprites", "s_player", "s_player.yy")
        ))
        self.assertTrue(index.resolve_gm_path("tilesets", "ts_ground").endswith(
            os.path.join("tilesets", "ts_ground", "ts_ground.yy")
        ))

    def test_computes_godot_paths_with_subfolders(self):
        self._write_yyp([
            ("rooms", "r_intro"),
            ("objects", "o_player"),
            ("sprites", "s_player"),
            ("tilesets", "ts_ground"),
        ], room_order=["r_intro"])
        self._write_room("r_intro", "folders/Rooms/Game/Intro.yy")
        self._write_resource(
            "objects", "o_player", "folders/Objects/Game/Actors.yy", "GMObject"
        )
        self._write_resource(
            "sprites", "s_player", "folders/Sprites/Game/Actors.yy", "GMSprite"
        )
        self._write_resource(
            "tilesets", "ts_ground", "folders/Tile Sets/World.yy", "GMTileSet"
        )

        index = self._build_index()

        self.assertEqual(
            index.resolve_godot_path("rooms", "r_intro"),
            "res://rooms/Game/Intro/r_intro/r_intro.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("objects", "o_player"),
            "res://objects/Game/Actors/o_player/o_player.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("sprites", "s_player"),
            "res://sprites/Game/Actors/s_player/s_player.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("tilesets", "ts_ground"),
            "res://tilesets/World/ts_ground/ts_ground.tres",
        )

    def test_handles_trailing_commas_in_yyp_and_room_yy(self):
        self._write_yyp([("rooms", "r_trailing")], room_order=["r_trailing"])
        self._write_room("r_trailing")

        index = self._build_index()
        room = index.get_room("r_trailing")

        self.assertIsNotNone(room)
        self.assertEqual(room.room_settings["Width"], 640)
        self.assertEqual(room.room_settings["Height"], 480)

    def test_missing_yyp_falls_back_to_disk_scan(self):
        self._write_room("r_disk")
        self._write_resource("objects", "o_disk", "folders/Objects.yy", "GMObject")
        self._write_resource("sprites", "s_disk", "folders/Sprites.yy", "GMSprite")
        self._write_resource("tilesets", "ts_disk", "folders/Tile Sets.yy", "GMTileSet")

        index = self._build_index()

        self.assertIsNotNone(index.get_room("r_disk"))
        self.assertIsNotNone(index.get_resource("objects", "o_disk"))
        self.assertIsNotNone(index.get_resource("sprites", "s_disk"))
        self.assertIsNotNone(index.get_resource("tilesets", "ts_disk"))
        self.assertEqual([room.name for room in index.ordered_rooms()], ["r_disk"])

    def test_malformed_yyp_falls_back_to_disk_scan(self):
        _write_file(os.path.join(self.gm_dir, "BadProject.yyp"), "not valid json {{{")
        self._write_room("r_disk")

        index = self._build_index()

        self.assertIsNotNone(index.get_room("r_disk"))
        self.assertTrue(any("falling back" in msg for msg in self.logs))

    def test_missing_room_order_nodes_uses_sorted_fallback_and_logs_warning(self):
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            "{\n"
            '  "resources":[\n'
            f'{_resource_entry("rooms", "r_z")},\n'
            f'{_resource_entry("rooms", "r_a")}\n'
            "  ],\n"
            '  "resourceType":"GMProject"\n'
            "}\n",
        )
        self._write_room("r_z")
        self._write_room("r_a")

        index = self._build_index()

        self.assertEqual([room.name for room in index.ordered_rooms()], ["r_a", "r_z"])
        self.assertEqual(index.first_room().name, "r_a")
        self.assertTrue(index.used_room_order_fallback)
        self.assertTrue(any("RoomOrderNodes missing" in msg for msg in self.logs))
        self.assertTrue(any("fallback" in msg.lower() for msg in self.logs))

    def test_malformed_room_is_skipped_and_logged(self):
        self._write_yyp([("rooms", "r_bad")], room_order=["r_bad"])
        self._write_room("r_bad", content="not valid json {{{")

        index = self._build_index()

        self.assertIsNone(index.get_room("r_bad"))
        self.assertTrue(any("r_bad" in msg for msg in self.logs))

    def test_missing_optional_room_fields_do_not_crash(self):
        self._write_yyp([("rooms", "r_minimal")], room_order=["r_minimal"])
        self._write_room(
            "r_minimal",
            content='{"name":"r_minimal","resourceType":"GMRoom",}',
        )

        index = self._build_index()
        room = index.get_room("r_minimal")

        self.assertEqual(room.room_settings, {})
        self.assertEqual(room.physics_settings, {})
        self.assertEqual(room.view_settings, {})
        self.assertEqual(room.views, [])
        self.assertEqual(room.layers, [])
        self.assertEqual(room.instance_creation_order, [])
        self.assertIsNone(room.parent_room)
        self.assertEqual(room.creation_code_file, "")

    def test_no_scene_output_is_written(self):
        self._write_yyp([("rooms", "r_empty")], room_order=["r_empty"])
        self._write_room("r_empty")

        self._build_index()

        self.assertFalse(os.path.exists(os.path.join(self.godot_dir, "rooms")))


if __name__ == "__main__":
    unittest.main()
