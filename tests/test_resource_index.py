import os
import shutil
import sys
import tempfile
import unittest
from typing import Iterable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.resource_index import GameMakerResourceIndex


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _resource_entry(kind: str, name: str) -> str:
    return (
        '    {{"id":{{"name":"{name}",'
        '"path":"{kind}/{name}/{name}.yy",}},}}'
    ).format(kind=kind, name=name)


def _room_order_entry(name: str) -> str:
    return (
        '    {{"roomId":{{"name":"{name}",'
        '"path":"rooms/{name}/{name}.yy",}},}}'
    ).format(name=name)


def _make_yyp(
    resources: Iterable[tuple[str, str]], room_order: Iterable[str] | None = None
) -> str:
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


def _make_room_yy(name: str, parent_path: str = "folders/Rooms.yy") -> str:
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


def _make_minimal_yy(
    name: str, resource_type: str, parent_name: str, parent_path: str
) -> str:
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


def _make_extension_yy(name: str) -> str:
    return (
        '{{\n'
        '  "$GMExtension":"",\n'
        '  "%Name":"{name}",\n'
        '  "name":"{name}",\n'
        '  "files":[\n'
        '    {{\n'
        '      "filename":"{name}.dll",\n'
        '      "functions":[\n'
        '        {{"name":"ads_show_rewarded","externalName":"Ads_ShowRewarded","argCount":1,}},\n'
        '        {{"name":"analytics_track","args":[{{}},{{}},],}},\n'
        '      ],\n'
        '    }},\n'
        '  ],\n'
        '  "resourceType":"GMExtension",\n'
        '}}\n'
    ).format(name=name)


class TestGameMakerResourceIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _build_index(self) -> GameMakerResourceIndex:
        index = GameMakerResourceIndex(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        return index.build()

    def _write_yyp(
        self, resources: Iterable[tuple[str, str]], room_order: Iterable[str] | None = None
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "TestProject.yyp"),
            _make_yyp(resources, room_order),
        )

    def _write_room(
        self, name: str, parent_path: str = "folders/Rooms.yy", content: str | None = None
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "rooms", name, name + ".yy"),
            content if content is not None else _make_room_yy(name, parent_path),
        )

    def _write_resource(
        self, kind: str, name: str, parent_path: str, resource_type: str
    ) -> None:
        parent_name = kind.capitalize()
        _write_file(
            os.path.join(self.gm_dir, kind, name, name + ".yy"),
            _make_minimal_yy(name, resource_type, parent_name, parent_path),
        )

    def _write_extension(self, name: str) -> None:
        _write_file(
            os.path.join(self.gm_dir, "extensions", name, name + ".yy"),
            _make_extension_yy(name),
        )

    def test_indexes_yyp_resources_and_preserves_room_order(self) -> None:
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
        first_room = index.first_room()
        assert first_room is not None
        self.assertEqual(first_room.name, "r_first")
        self.assertEqual(
            index.resolve_gm_path("rooms", "r_first"),
            os.path.join(self.gm_dir, "rooms", "r_first", "r_first.yy"),
        )

    def test_resolves_resource_gm_paths_for_supported_kinds(self) -> None:
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

        room_path = index.resolve_gm_path("rooms", "r_test")
        object_path = index.resolve_gm_path("objects", "o_player")
        sprite_path = index.resolve_gm_path("sprites", "s_player")
        tileset_path = index.resolve_gm_path("tilesets", "ts_ground")

        assert room_path is not None
        assert object_path is not None
        assert sprite_path is not None
        assert tileset_path is not None
        self.assertTrue(room_path.endswith(
            os.path.join("rooms", "r_test", "r_test.yy")
        ))
        self.assertTrue(object_path.endswith(
            os.path.join("objects", "o_player", "o_player.yy")
        ))
        self.assertTrue(sprite_path.endswith(
            os.path.join("sprites", "s_player", "s_player.yy")
        ))
        self.assertTrue(tileset_path.endswith(
            os.path.join("tilesets", "ts_ground", "ts_ground.yy")
        ))

    def test_skips_yyp_resource_that_escapes_through_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            _write_file(
                os.path.join(outside_dir, "s_escape.yy"),
                _make_minimal_yy(
                    "s_escape",
                    "GMSprite",
                    "Sprites",
                    "folders/Sprites.yy",
                ),
            )
            sprites_dir = os.path.join(self.gm_dir, "sprites")
            os.makedirs(sprites_dir)
            try:
                os.symlink(
                    outside_dir,
                    os.path.join(sprites_dir, "linked"),
                    target_is_directory=True,
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")
            _write_file(
                os.path.join(self.gm_dir, "TestProject.yyp"),
                "{\n"
                '  "resources":[\n'
                '    {"id":{"name":"s_escape",'
                '"path":"sprites/linked/s_escape.yy"}}\n'
                "  ],\n"
                '  "RoomOrderNodes":[],\n'
                '  "resourceType":"GMProject"\n'
                "}\n",
            )

            index = self._build_index()

        self.assertIsNone(index.get_resource("sprites", "s_escape"))
        self.assertTrue(
            any(
                "s_escape" in message and "symbolic link" in message
                for message in self.logs
            ),
            self.logs,
        )

    def test_preserves_manifest_resource_metadata_and_resolves_by_graph_fields(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Graph.yyp"),
            "{\n"
            '  "resources":[\n'
            '    {"id":{"id":"uuid-sprite","name":"s_player","path":"sprites/s_player/s_player.yy"},'
            '"resourceType":"GMSprite","tags":["hero"],"order":7}\n'
            "  ],\n"
            '  "RoomOrderNodes":[],\n'
            '  "resourceType":"GMProject"\n'
            "}\n",
        )
        self._write_resource("sprites", "s_player", "folders/Sprites/Actors.yy", "GMSprite")

        index = self._build_index()
        sprite = index.get_resource("sprites", "s_player")
        resolved_by_uuid = index.resolve_indexed_resource(uuid="uuid-sprite")
        resolved_by_path = index.resolve_indexed_resource(path="sprites\\s_player\\s_player.yy")
        refs_by_type = index.find_project_resources(resource_type="GMSprite")

        assert sprite is not None
        assert resolved_by_uuid is not None
        assert resolved_by_path is not None
        self.assertEqual(sprite.uuid, "uuid-sprite")
        self.assertEqual(sprite.resource_type, "GMSprite")
        self.assertEqual(sprite.tags, ("hero",))
        self.assertEqual(sprite.order, 7)
        self.assertEqual(resolved_by_uuid.name, "s_player")
        self.assertEqual(resolved_by_path.name, "s_player")
        self.assertEqual([resource.name for resource in refs_by_type], ["s_player"])

    def test_indexes_extension_functions_from_yyp_metadata(self) -> None:
        self._write_yyp([("extensions", "AdSDK")])
        self._write_extension("AdSDK")

        index = self._build_index()
        rewarded = index.get_extension_function("ads_show_rewarded")
        analytics = index.get_extension_function("analytics_track")

        assert rewarded is not None
        assert analytics is not None
        self.assertEqual(rewarded.extension_name, "AdSDK")
        self.assertEqual(rewarded.external_name, "Ads_ShowRewarded")
        self.assertEqual(rewarded.arg_count, 1)
        self.assertEqual(analytics.arg_count, 2)
        self.assertEqual(
            index.extension_function_names(),
            {"ads_show_rewarded", "analytics_track"},
        )

    def test_indexes_extension_functions_from_disk_fallback(self) -> None:
        self._write_extension("AdSDK")

        index = self._build_index()

        self.assertIn("ads_show_rewarded", index.get_extension_functions())

    def test_computes_godot_paths_with_subfolders(self) -> None:
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
            "res://rooms/game/intro/r_intro/r_intro.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("objects", "o_player"),
            "res://objects/game/actors/o_player/o_player.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("sprites", "s_player"),
            "res://sprites/game/actors/s_player/s_player.tscn",
        )
        self.assertEqual(
            index.resolve_godot_path("tilesets", "ts_ground"),
            "res://tilesets/world/ts_ground/ts_ground.tres",
        )

    def test_handles_trailing_commas_in_yyp_and_room_yy(self) -> None:
        self._write_yyp([("rooms", "r_trailing")], room_order=["r_trailing"])
        self._write_room("r_trailing")

        index = self._build_index()
        room = index.get_room("r_trailing")

        assert room is not None
        self.assertEqual(room.room_settings["Width"], 640)
        self.assertEqual(room.room_settings["Height"], 480)

    def test_indexes_room_creation_code_metadata(self) -> None:
        content = _make_room_yy("r_code").replace(
            '"creationCodeFile":"",',
            '"creationCodeFile":"rooms/r_code/RoomCreationCode.gml",',
        ).replace(
            '"inheritCode":false,',
            '"inheritCode":true,',
        ).replace(
            '"isDnd":false,',
            '"isDnd":true,',
        )
        self._write_yyp([("rooms", "r_code")], room_order=["r_code"])
        self._write_room("r_code", content=content)

        index = self._build_index()
        room = index.get_room("r_code")

        assert room is not None
        self.assertEqual(room.creation_code_file, "rooms/r_code/RoomCreationCode.gml")
        self.assertTrue(room.inherit_code)
        self.assertTrue(room.is_dnd)

    def test_missing_yyp_falls_back_to_disk_scan(self) -> None:
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

    def test_malformed_yyp_falls_back_to_disk_scan(self) -> None:
        _write_file(os.path.join(self.gm_dir, "BadProject.yyp"), "not valid json {{{")
        self._write_room("r_disk")

        index = self._build_index()

        self.assertIsNotNone(index.get_room("r_disk"))
        self.assertTrue(any("falling back" in msg for msg in self.logs))

    def test_missing_room_order_nodes_uses_sorted_fallback_and_logs_warning(self) -> None:
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
        first_room = index.first_room()
        assert first_room is not None
        self.assertEqual(first_room.name, "r_a")
        self.assertTrue(index.used_room_order_fallback)
        self.assertTrue(any("RoomOrderNodes missing" in msg for msg in self.logs))
        self.assertTrue(any("fallback" in msg.lower() for msg in self.logs))

    def test_malformed_room_is_skipped_and_logged(self) -> None:
        self._write_yyp([("rooms", "r_bad")], room_order=["r_bad"])
        self._write_room("r_bad", content="not valid json {{{")

        index = self._build_index()

        self.assertIsNone(index.get_room("r_bad"))
        self.assertTrue(any("r_bad" in msg for msg in self.logs))

    def test_missing_optional_room_fields_do_not_crash(self) -> None:
        self._write_yyp([("rooms", "r_minimal")], room_order=["r_minimal"])
        self._write_room(
            "r_minimal",
            content='{"name":"r_minimal","resourceType":"GMRoom",}',
        )

        index = self._build_index()
        room = index.get_room("r_minimal")

        assert room is not None
        self.assertEqual(room.room_settings, {})
        self.assertEqual(room.physics_settings, {})
        self.assertEqual(room.view_settings, {})
        self.assertEqual(room.views, [])
        self.assertEqual(room.layers, [])
        self.assertEqual(room.instance_creation_order, [])
        self.assertIsNone(room.parent_room)
        self.assertEqual(room.creation_code_file, "")

    def test_no_scene_output_is_written(self) -> None:
        self._write_yyp([("rooms", "r_empty")], room_order=["r_empty"])
        self._write_room("r_empty")

        self._build_index()

        self.assertFalse(os.path.exists(os.path.join(self.godot_dir, "rooms")))


if __name__ == "__main__":
    unittest.main()
