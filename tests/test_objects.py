import os
# pyright: reportPrivateUsage=false
import json
import sys
import shutil
import tempfile
import unittest
from typing import cast

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.objects import ObjectConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.type_defs import JsonDict


def _make_object_yy_content(name: str, sprite_name: str | None = None,
                            parent_path: str = "folders/Objects.yy",
                            event_list: list[JsonDict] | None = None,
                            parent_object_name: str | None = None,
                            persistent: bool = False) -> str:
    """Build a GameMaker object .yy file string."""
    if sprite_name is not None:
        sprite_id = (
            '{{"name": "{sprite_name}", '
            '"path": "sprites/{sprite_name}/{sprite_name}.yy",}}'
        ).format(sprite_name=sprite_name)
    else:
        sprite_id = "null"

    if parent_object_name is None:
        parent_object_id = "null"
    else:
        parent_object_id = (
            '{{"name": "{parent_object_name}", '
            '"path": "objects/{parent_object_name}/{parent_object_name}.yy",}}'
        ).format(parent_object_name=parent_object_name)

    if event_list is None:
        event_list = []
    event_entries: list[str] = []
    for evt in event_list:
        collision_id = "null"
        if evt.get("collisionObjectId") is not None:
            col = cast(JsonDict, evt["collisionObjectId"])
            collision_id = '{{"name": "{name}", "path": "objects/{name}/{name}.yy",}}'.format(name=col["name"])
        entry = (
            '{{"isDnD":false,"eventNum":{eventNum},"eventType":{eventType},'
            '"collisionObjectId":{collisionObjectId},'
            '"resourceVersion":"2.0","name":"","resourceType":"GMEvent",}}'
        ).format(
            eventNum=evt.get("eventNum", 0),
            eventType=evt.get("eventType", 0),
            collisionObjectId=collision_id,
        )
        event_entries.append(entry)
    event_list_str = ",\n    ".join(event_entries)
    if event_list_str:
        event_list_str = "\n    " + event_list_str + ",\n  "

    return (
        '{{\n'
        '  "$GMObject": "",\n'
        '  "%Name": "{name}",\n'
        '  "eventList": [{event_list_str}],\n'
        '  "managed": true,\n'
        '  "name": "{name}",\n'
        '  "overriddenProperties": [],\n'
        '  "parent": {{"name": "Objects", "path": "{parent_path}",}},\n'
        '  "parentObjectId": {parent_object_id},\n'
        '  "persistent": {persistent},\n'
        '  "physicsObject": false,\n'
        '  "properties": [],\n'
        '  "resourceType": "GMObject",\n'
        '  "resourceVersion": "2.0",\n'
        '  "solid": false,\n'
        '  "spriteId": {sprite_id},\n'
        '  "spriteMaskId": null,\n'
        '  "visible": true,\n'
        '}}'
    ).format(
        name=name,
        sprite_id=sprite_id,
        parent_path=parent_path,
        parent_object_id=parent_object_id,
        event_list_str=event_list_str,
        persistent=str(persistent).lower(),
    )


def _create_fake_sprite_scene(godot_dir: str, sprite_name: str, subfolder: str = "") -> None:
    """Create a minimal sprite .tscn file in the Godot project."""
    if subfolder:
        sprite_dir = os.path.join(godot_dir, "sprites", subfolder, sprite_name)
    else:
        sprite_dir = os.path.join(godot_dir, "sprites", sprite_name)
    os.makedirs(sprite_dir, exist_ok=True)
    tscn_path = os.path.join(sprite_dir, sprite_name + ".tscn")
    with open(tscn_path, "w", encoding="utf-8") as f:
        f.write('[gd_scene format=3]\n\n[node name="{}" type="Area2D"]\n'.format(sprite_name))


def _make_sprite_yy_content(sprite_name: str, parent_path: str = "folders/Sprites.yy") -> str:
    """Build a minimal sprite .yy file with parent folder info."""
    return (
        '{{\n'
        '  "name": "{name}",\n'
        '  "parent": {{"name": "Sprites", "path": "{parent_path}",}},\n'
        '  "resourceType": "GMSprite",\n'
        '}}'
    ).format(name=sprite_name, parent_path=parent_path)


class TestObjectConverterBasic(unittest.TestCase):
    """Test ObjectConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create an object with a sprite reference
        obj_dir = os.path.join(self.gm_dir, "objects", "o_player")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_player", sprite_name="s_player")
        with open(os.path.join(obj_dir, "o_player.yy"), "w") as f:
            f.write(yy_content)

        # Create an object without a sprite
        obj_dir2 = os.path.join(self.gm_dir, "objects", "o_controller")
        os.makedirs(obj_dir2)
        yy_content2 = _make_object_yy_content("o_controller", sprite_name=None)
        with open(os.path.join(obj_dir2, "o_controller.yy"), "w") as f:
            f.write(yy_content2)

        # Create the fake converted sprite scene for o_player's sprite
        _create_fake_sprite_scene(self.godot_dir, "s_player")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, macro_configuration: str | None = None) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def test_converts_object_to_godot_dir(self):
        converter = self._make_converter()
        converter.convert_all()

        godot_obj_dir = os.path.join(self.godot_dir, "objects", "o_player")
        self.assertTrue(os.path.isdir(godot_obj_dir),
                        "Expected objects/o_player directory in Godot project")

    def test_generates_tscn_file(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        self.assertTrue(os.path.isfile(tscn_path), "Expected .tscn file to be generated")

    def test_tscn_instances_sprite(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('PackedScene', content)
        self.assertIn('res://sprites/s_player/s_player.tscn', content)
        self.assertIn('instance=ExtResource("1")', content)
        self.assertIn('type="Node2D"', content)

    def test_object_without_sprite(self):
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_controller", "o_controller.tscn")
        self.assertTrue(os.path.isfile(tscn_path), "Expected .tscn file for object without sprite")

        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('type="Node2D"', content)
        self.assertNotIn('PackedScene', content)
        self.assertNotIn('instance', content)
        self.assertIn('type="Script"', content)
        self.assertIn('script = ExtResource', content)


class TestObjectConverterEmpty(unittest.TestCase):
    """Edge cases: missing objects dir and missing sprites."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_objects_no_crash(self):
        """No objects directory at all should log an error and not crash."""
        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing objects folder")

    def test_missing_sprite_scene_fallback(self):
        """Object referencing a sprite whose scene doesn't exist should fall back to no-sprite."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_broken")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_broken", sprite_name="s_nonexistent")
        with open(os.path.join(obj_dir, "o_broken.yy"), "w") as f:
            f.write(yy_content)

        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        # Scene should still be created, but without sprite reference
        tscn_path = os.path.join(self.godot_dir, "objects", "o_broken", "o_broken.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Should still generate .tscn even when sprite is missing")

        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('type="Node2D"', content)
        self.assertNotIn('PackedScene', content)
        self.assertIn('type="Script"', content)


class TestParseObjectYY(unittest.TestCase):
    """Test _parse_object_yy directly."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_object_yy(self, object_name: str, content: str) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", object_name)
        os.makedirs(obj_dir, exist_ok=True)
        with open(os.path.join(obj_dir, object_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_valid_object_with_sprite(self):
        content = _make_object_yy_content("o_test", sprite_name="s_test")
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["sprite_name"], "s_test")

    def test_parses_valid_object_without_sprite(self):
        content = _make_object_yy_content("o_empty", sprite_name=None)
        self._write_object_yy("o_empty", content)

        result = self.converter._parse_object_yy("o_empty")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result["sprite_name"])

    def test_parses_parent_object_name(self):
        content = _make_object_yy_content("o_child", parent_object_name="o_parent")
        self._write_object_yy("o_child", content)

        result = self.converter._parse_object_yy("o_child")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["parent_object_name"], "o_parent")

    def test_returns_none_for_missing(self):
        result = self.converter._parse_object_yy("nonexistent_object")
        self.assertIsNone(result)

    def test_handles_trailing_commas(self):
        content = (
            '{\n'
            '  "spriteId": {"name": "s_tc", "path": "sprites/s_tc/s_tc.yy",},\n'
            '  "name": "o_tc",\n'
            '  "resourceType": "GMObject",\n'
            '}'
        )
        self._write_object_yy("o_tc", content)

        result = self.converter._parse_object_yy("o_tc")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["sprite_name"], "s_tc")


class TestObjectConverterYYPFiltering(unittest.TestCase):
    """Test that objects are filtered against the .yyp project file."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create two objects on disk
        for name in ["o_listed", "o_unlisted"]:
            obj_dir = os.path.join(self.gm_dir, "objects", name)
            os.makedirs(obj_dir)
            yy_content = _make_object_yy_content(name, sprite_name=None)
            with open(os.path.join(obj_dir, name + ".yy"), "w") as f:
                f.write(yy_content)

        # Create a .yyp that only lists o_listed
        yyp_content = (
            '{\n'
            '  "resources": [\n'
            '    {"id": {"name": "o_listed", "path": "objects/o_listed/o_listed.yy"}}\n'
            '  ]\n'
            '}'
        )
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w") as f:
            f.write(yyp_content)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_only_listed_objects_converted(self):
        converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        listed_path = os.path.join(self.godot_dir, "objects", "o_listed", "o_listed.tscn")
        unlisted_path = os.path.join(self.godot_dir, "objects", "o_unlisted", "o_unlisted.tscn")

        self.assertTrue(os.path.isfile(listed_path),
                        "Object listed in .yyp should be converted")
        self.assertFalse(os.path.isfile(unlisted_path),
                         "Object not listed in .yyp should be skipped")


class TestObjectConverterSubfolders(unittest.TestCase):
    """Test that objects respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, macro_configuration: str | None = None) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def test_object_in_subfolder(self):
        """Object with nested parent path should be placed in subfolder."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_boss")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_boss", sprite_name=None,
                                              parent_path="folders/Objects/Game/Enemies.yy")
        with open(os.path.join(obj_dir, "o_boss.yy"), "w") as f:
            f.write(yy_content)

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "game", "enemies", "o_boss", "o_boss.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Object should be in objects/game/enemies/o_boss/")

    def test_object_with_sprite_in_subfolder(self):
        """Object should resolve sprite cross-reference with correct subfolder path."""
        # Create object
        obj_dir = os.path.join(self.gm_dir, "objects", "o_player")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_player", sprite_name="s_player",
                                              parent_path="folders/Objects.yy")
        with open(os.path.join(obj_dir, "o_player.yy"), "w") as f:
            f.write(yy_content)

        # Create sprite .yy in GM project (for subfolder resolution)
        sprite_gm_dir = os.path.join(self.gm_dir, "sprites", "s_player")
        os.makedirs(sprite_gm_dir)
        sprite_yy = _make_sprite_yy_content("s_player", parent_path="folders/Sprites/Player.yy")
        with open(os.path.join(sprite_gm_dir, "s_player.yy"), "w") as f:
            f.write(sprite_yy)

        # Create converted sprite scene at the subfolder location
        _create_fake_sprite_scene(self.godot_dir, "s_player", subfolder="player")

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('res://sprites/player/s_player/s_player.tscn', content)

    def test_root_level_object_stays_flat(self):
        """Object with root-level parent should stay in flat structure."""
        obj_dir = os.path.join(self.gm_dir, "objects", "o_ctrl")
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content("o_ctrl", sprite_name=None,
                                              parent_path="folders/Objects.yy")
        with open(os.path.join(obj_dir, "o_ctrl.yy"), "w") as f:
            f.write(yy_content)

        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_ctrl", "o_ctrl.tscn")
        self.assertTrue(os.path.isfile(tscn_path),
                        "Root-level object should remain at objects/o_ctrl/")


class TestScriptGeneration(unittest.TestCase):
    """Test .gd script file generation for objects."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, macro_configuration: str | None = None) -> ObjectConverter:
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def _setup_object(self, name: str, sprite_name: str | None = None,
                      event_list: list[JsonDict] | None = None,
                      parent_object_name: str | None = None,
                      persistent: bool = False) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", name)
        os.makedirs(obj_dir)
        yy_content = _make_object_yy_content(
            name,
            sprite_name=sprite_name,
            event_list=event_list,
            parent_object_name=parent_object_name,
            persistent=persistent,
        )
        with open(os.path.join(obj_dir, name + ".yy"), "w") as f:
            f.write(yy_content)
        if sprite_name:
            _create_fake_sprite_scene(self.godot_dir, sprite_name)

    def test_generates_gd_file(self):
        """A .gd file should be created alongside the .tscn."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        self.assertTrue(os.path.isfile(gd_path), "Expected .gd file to be generated")

    def test_script_extends_node2d(self):
        """Script should start with extends Node2D."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertTrue(content.startswith("extends Node2D"))

    def test_script_with_no_events(self):
        """Object with empty eventList still registers with the runtime instance registry."""
        self._setup_object("o_empty", event_list=[])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_empty", "o_empty.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn('GMRuntime.gml_instance_register(self, "o_empty", [])', content)
        self.assertIn("func _ready():\n\t_gm_register_instance()", content)
        self.assertIn("func _exit_tree():\n\t_gm_unregister_instance()", content)

    def test_script_records_persistent_object_state(self):
        self._setup_object("o_persist", event_list=[], persistent=True)
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_persist", "o_persist.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("var persistent = true", content)
        self.assertIn("\tpersistent = true", content)
        self.assertIn('GMRuntime.gml_variable_instance_set(self, "persistent", persistent)', content)
        self.assertIn('set_meta("gamemaker_persistent", persistent)', content)

    def test_script_registers_parent_object_chain(self):
        self._setup_object("o_parent", event_list=[{"eventType": 0, "eventNum": 0}])
        self._setup_object("o_child", event_list=[], parent_object_name="o_parent")
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn('GMRuntime.gml_instance_register(self, "o_child", ["o_parent"])', content)
        self.assertIn(
            "func _ready():\n\t_gm_register_instance()\n\t_gm_initialize_motion_runtime()\n\tsuper._ready()",
            content,
        )

    def test_child_object_reuses_inherited_sprite_runtime_members(self):
        self._setup_object(
            "o_parent",
            sprite_name="s_parent",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        self._setup_object(
            "o_child",
            sprite_name="s_child",
            event_list=[],
            parent_object_name="o_parent",
        )
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertTrue(content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertNotIn('const s_child = "s_child"', content)
        self.assertNotIn("const _GM_SPRITE_SCENES", content)
        self.assertNotIn("\nvar sprite_index =", content)
        self.assertNotIn("\nvar image_index =", content)
        self.assertNotIn("func _gm_apply_sprite_index():", content)
        self.assertIn("\tsprite_index = \"s_child\"\n\t_gm_initialize_sprite_runtime()", content)
        self.assertIn("\tsuper._ready()", content)

    def test_script_event_sources_use_selected_macro_configuration(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                "#if Android\n"
                "score = 11;\n"
                "#else\n"
                "score = 22;\n"
                "#endif\n"
            )

        converter = self._make_converter(macro_configuration="Android")
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("\tscore = 11", content)
        self.assertNotIn("\tscore = 22", content)

    def test_script_with_create_event(self):
        """eventType 0 should produce func _ready()."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _ready():", content)
        self.assertIn("\t_gm_register_instance()", content)

    def test_script_transpiles_create_event_gml_body(self):
        """Simple expression/operator GML bodies should populate event functions."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("var speed = base_speed * 2; score ??= 0; score += speed div 2;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(f"{gd_path}.gmlmap.json", "r", encoding="utf-8") as f:
            source_map = json.load(f)

        self.assertIn("func _ready():", content)
        self.assertIn("\tvar speed = GMRuntime.gml_mul(base_speed, 2)", content)
        self.assertIn("\tif GMRuntime.gml_is_nullish(score):\n\t\tscore = 0", content)
        self.assertIn("\tscore = GMRuntime.gml_add(score, GMRuntime.gml_int_div(speed, 2))", content)
        self.assertNotIn("\tpass", content)
        self.assertTrue(source_map["entries"])
        self.assertEqual(source_map["entries"][0]["source_path"], source_path)
        self.assertEqual(source_map["entries"][0]["event"], "_ready")
        self.assertEqual(source_map["entries"][0]["source_line"], 1)

    def test_script_transpiles_calls_to_modern_script_function_assets(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        script_dir = os.path.join(self.gm_dir, "scripts", "ending")
        os.makedirs(script_dir)
        with open(os.path.join(script_dir, "ending.yy"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "%Name": "ending",
                    "name": "ending",
                    "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                    "resourceType": "GMScript",
                },
                f,
            )
        with open(os.path.join(script_dir, "ending.gml"), "w", encoding="utf-8") as f:
            f.write("function loadending() { return 1; }\nfunction saveending() { loadending(); }\n")
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("loadending();")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            'GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index("loadending"), [], self, other)',
            content,
        )
        self.assertNotIn("\tloadending()", content)

    def test_script_transpiles_infinity_runtime_support(self):
        """Infinity-sensitive GML should use the shared runtime support layer."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(
                "var limit = infinity; "
                "var ratio = 1 / 0; "
                "show_debug_message(string(limit));"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        runtime_path = os.path.join(self.godot_dir, "gm2godot", "gml_runtime.gd")
        self.assertTrue(os.path.isfile(runtime_path))
        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn("\tvar limit = INF", content)
        self.assertIn("\tvar ratio = GMRuntime.gml_div(1, 0)", content)
        self.assertIn("\tprint(GMRuntime.gml_string(limit))", content)

    def test_script_transpiles_string_runtime_support(self):
        """String conversion and concatenation should use the shared runtime."""
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write('var label = "Score: " + string(score); show_debug_message(label);')

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('const GMRuntime = preload("res://gm2godot/gml_runtime.gd")', content)
        self.assertIn(
            '\tvar label = GMRuntime.gml_add("Score: ", GMRuntime.gml_string(score))',
            content,
        )
        self.assertIn("\tprint(label)", content)

    def test_transpile_failure_records_structured_diagnostic(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write('show_message_async("Hello");')

        diagnostics = DiagnosticCollector()
        converter = ObjectConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        )
        converter.convert_all()

        recorded = diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].code, "GM2GD-GML-TRANSPILE")
        self.assertEqual(recorded[0].api, "show_message_async")
        self.assertEqual(recorded[0].issue_number, 507)
        self.assertEqual(recorded[0].resource, "o_test")
        self.assertEqual(recorded[0].resource_type, "object")
        self.assertEqual(recorded[0].event, "_ready")

    def test_child_event_inherited_preserves_parent_exit_boundary(self):
        """exit in an inherited parent event should not abort the child event."""
        self._setup_object("o_parent", event_list=[{"eventType": 0, "eventNum": 0}])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 0, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        with open(
            os.path.join(self.gm_dir, "objects", "o_parent", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("parent_ran = true; exit; parent_after_exit = true;")
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("child_before = true; event_inherited(); child_after = true;")

        converter = self._make_converter()
        converter.convert_all()

        parent_gd_path = os.path.join(self.godot_dir, "objects", "o_parent", "o_parent.gd")
        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(parent_gd_path, "r", encoding="utf-8") as f:
            parent_content = f.read()
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn("func _ready():", parent_content)
        self.assertIn("\tparent_ran = true\n\treturn\n\tparent_after_exit = true", parent_content)
        self.assertTrue(child_content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn(
            "\tchild_before = true\n\tsuper._ready()\n\tchild_after = true",
            child_content,
        )

    def test_event_inherited_noops_when_parent_lacks_matching_event(self):
        self._setup_object("o_parent", event_list=[{"eventType": 3, "eventNum": 0}])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 0, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("event_inherited(); child_after = true;")

        converter = self._make_converter()
        converter.convert_all()

        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn("\tpass\n\tchild_after = true", child_content)
        self.assertNotIn("super._ready()", child_content)

    def test_script_with_step_event(self):
        """eventType 3, eventNum 0 should produce the scheduler Step callback."""
        self._setup_object("o_test", event_list=[{"eventType": 3, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_step():", content)
        self.assertNotIn("func _process(delta):", content)

    def test_script_transpiles_topdown_step_movement(self):
        """Step polling movement should become Godot held-input movement."""
        self._setup_object("o_player", event_list=[{"eventType": 3, "eventNum": 0}])
        source_path = os.path.join(self.gm_dir, "objects", "o_player", "Step_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(
                "if keyboard_check(vk_left) { x -= 10; }\n"
                "if keyboard_check(vk_right) { x += 10; }\n"
                "if keyboard_check(vk_up) { y -= 10; }\n"
                "if keyboard_check(vk_down) { y += 10; }\n"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("func _on_step():", content)
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_LEFT):\n"
            "\t\tposition.x = GMRuntime.gml_sub(position.x, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_RIGHT):\n"
            "\t\tposition.x = GMRuntime.gml_add(position.x, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_UP):\n"
            "\t\tposition.y = GMRuntime.gml_sub(position.y, 10)",
            content,
        )
        self.assertIn(
            "\tif GMRuntime.gml_keyboard_check(KEY_DOWN):\n"
            "\t\tposition.y = GMRuntime.gml_add(position.y, 10)",
            content,
        )

    def test_script_declares_instance_variables_shared_across_events(self):
        """Assignments without var should become reusable object member state."""
        self._setup_object(
            "o_player",
            event_list=[
                {"eventType": 0, "eventNum": 0},
                {"eventType": 3, "eventNum": 0},
            ],
        )
        object_dir = os.path.join(self.gm_dir, "objects", "o_player")
        with open(os.path.join(object_dir, "Create_0.gml"), "w", encoding="utf-8") as f:
            f.write("superSpeed = 0\nfaster = false;")
        with open(os.path.join(object_dir, "Step_0.gml"), "w", encoding="utf-8") as f:
            f.write(
                "if keyboard_check(vk_shift) { faster = true } else { faster = false }\n"
                "if faster = true { superSpeed = 20 }\n"
                "if keyboard_check(vk_left) { x -= superSpeed; }\n"
                "superSpeed = 10;"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("var faster", content)
        self.assertIn("var superSpeed", content)
        self.assertIn("\tsuperSpeed = 0", content)
        self.assertIn("\tif GMRuntime.gml_keyboard_check(KEY_SHIFT):", content)
        self.assertIn("\tif GMRuntime.gml_eq(faster, true):", content)
        self.assertIn("\t\tposition.x = GMRuntime.gml_sub(position.x, superSpeed)", content)
        self.assertNotIn("Could not transpile", "\n".join(str(msg) for msg in self.logs))

    def test_script_assigned_instance_variables_are_declared_on_objects(self):
        self._setup_object("o_player", event_list=[{"eventType": 3, "eventNum": 0}])
        scripts_dir = os.path.join(self.gm_dir, "scripts", "scr_controls")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(os.path.join(scripts_dir, "scr_controls.gml"), "w", encoding="utf-8") as f:
            f.write(
                "function scr_controls(local_param) {\n"
                "    var local_only = 0;\n"
                "    local_param = 1;\n"
                "    leftcontrols = 0;\n"
                "    rightcontrols = 1;\n"
                "}\n"
            )

        object_dir = os.path.join(self.gm_dir, "objects", "o_player")
        with open(os.path.join(object_dir, "Step_0.gml"), "w", encoding="utf-8") as f:
            f.write(
                "scr_controls(0);\n"
                "if leftcontrols = 0 { key_left = true; }\n"
                "if rightcontrols = 1 { key_right = true; }\n"
            )

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("var leftcontrols", content)
        self.assertIn("var rightcontrols", content)
        self.assertNotIn("var local_only", content)
        self.assertNotIn("var local_param", content)
        self.assertIn("if GMRuntime.gml_eq(leftcontrols, 0):", content)
        self.assertIn("if GMRuntime.gml_eq(rightcontrols, 1):", content)

    def test_script_assigned_instance_variables_are_inherited_by_child_objects(self):
        self._setup_object("o_parent", event_list=[])
        self._setup_object(
            "o_child",
            event_list=[{"eventType": 3, "eventNum": 0}],
            parent_object_name="o_parent",
        )
        scripts_dir = os.path.join(self.gm_dir, "scripts", "scr_controls")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(os.path.join(scripts_dir, "scr_controls.gml"), "w", encoding="utf-8") as f:
            f.write("function scr_controls() { leftcontrols = 0; }\n")
        with open(
            os.path.join(self.gm_dir, "objects", "o_child", "Step_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("scr_controls(); if leftcontrols = 0 { key_left = true; }")

        converter = self._make_converter()
        converter.convert_all()

        parent_gd_path = os.path.join(self.godot_dir, "objects", "o_parent", "o_parent.gd")
        child_gd_path = os.path.join(self.godot_dir, "objects", "o_child", "o_child.gd")
        with open(parent_gd_path, "r", encoding="utf-8") as f:
            parent_content = f.read()
        with open(child_gd_path, "r", encoding="utf-8") as f:
            child_content = f.read()

        self.assertIn("var leftcontrols", parent_content)
        self.assertNotIn("var leftcontrols", child_content)
        self.assertTrue(child_content.startswith('extends "res://objects/o_parent/o_parent.gd"'))
        self.assertIn("if GMRuntime.gml_eq(leftcontrols, 0):", child_content)

    def test_script_supports_sprite_and_image_index(self):
        """sprite_index and image_index should map to generated sprite runtime state."""
        self._setup_object(
            "o_player",
            sprite_name="s_player",
            event_list=[{"eventType": 0, "eventNum": 0}],
        )
        _create_fake_sprite_scene(self.godot_dir, "s_enemy")
        source_path = os.path.join(self.gm_dir, "objects", "o_player", "Create_0.gml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write("image_index = 2; sprite_index = s_enemy;")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_player", "o_player.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('const s_enemy = "s_enemy"', content)
        self.assertIn('const s_player = "s_player"', content)
        self.assertIn('"s_enemy": preload("res://sprites/s_enemy/s_enemy.tscn")', content)
        self.assertIn('"s_player": preload("res://sprites/s_player/s_player.tscn")', content)
        self.assertIn('var sprite_index = "s_player":', content)
        self.assertIn('var image_index = 0.0:', content)
        self.assertIn('func _gm_apply_sprite_index():', content)
        self.assertIn('func _gm_apply_image_index():', content)
        self.assertIn('if has_meta("gamemaker_image_index"):', content)
        self.assertIn("\t_gm_initialize_sprite_runtime()\n\timage_index = 2", content)
        self.assertIn("\tsprite_index = s_enemy", content)
        self.assertNotIn("\n\nvar image_index\n", content)
        self.assertNotIn("\n\nvar sprite_index\n", content)

    def test_script_with_begin_step(self):
        """eventType 3, eventNum 1 should produce the scheduler Begin Step callback."""
        self._setup_object("o_test", event_list=[{"eventType": 3, "eventNum": 1}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_begin_step():", content)
        self.assertNotIn("func _physics_process(delta):", content)

    def test_script_with_draw_event(self):
        """eventType 8, eventNum 0 should produce func _draw()."""
        self._setup_object("o_test", event_list=[{"eventType": 8, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _draw():", content)

    def test_script_with_cleanup_event(self):
        """eventType 12 should produce func _exit_tree()."""
        self._setup_object("o_test", event_list=[{"eventType": 12, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _exit_tree():", content)

    def test_script_with_alarm_event(self):
        """eventType 2 should produce func _on_alarm_N()."""
        self._setup_object("o_test", event_list=[{"eventType": 2, "eventNum": 3}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_alarm_3():", content)

    def test_event_source_uses_runtime_alarm_array_access(self):
        self._setup_object("o_test", event_list=[{"eventType": 0, "eventNum": 0}])
        with open(
            os.path.join(self.gm_dir, "objects", "o_test", "Create_0.gml"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("alarm[0] = 3;\nnext_alarm = alarm[0];")

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("GMRuntime.gml_alarm_set(self, 0, 3)", content)
        self.assertIn("next_alarm = GMRuntime.gml_alarm_get(self, 0)", content)
        self.assertNotIn("alarm[", content)

    def test_script_with_collision_event(self):
        """eventType 4 with collisionObjectId should produce func _on_collision_NAME()."""
        self._setup_object("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_bullet"}}
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_collision_event_bindings():", content)
        self.assertIn('{"target_object": "o_bullet", "method": "_on_collision_o_bullet"}', content)
        self.assertIn("func _on_collision_o_bullet():", content)

    def test_script_with_multiple_events(self):
        """Multiple events should produce multiple function stubs."""
        self._setup_object("o_test", event_list=[
            {"eventType": 0, "eventNum": 0},
            {"eventType": 3, "eventNum": 0},
            {"eventType": 1, "eventNum": 0},
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _ready():", content)
        self.assertIn("func _on_step():", content)
        self.assertIn("func _on_destroy():", content)

    def test_input_events_merged(self):
        """Mouse and keyboard events should produce GMInput dispatch bindings."""
        self._setup_object("o_test", event_list=[
            {"eventType": 6, "eventNum": 4},   # Mouse left click
            {"eventType": 9, "eventNum": 32},   # KeyPress space
            {"eventType": 10, "eventNum": 13},  # KeyRelease enter
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_event_bindings():", content)
        self.assertIn("func _gm_input_mouse_4():", content)
        self.assertIn("func _gm_input_key_press_32():", content)
        self.assertIn("func _gm_input_key_release_13():", content)
        self.assertNotIn("func _input(event):", content)

    def test_mouse_event_ranges_merged(self):
        """All ev_mouse ranges should be listed in one binding table."""
        self._setup_object("o_test", event_list=[
            {"eventType": 6, "eventNum": 0},
            {"eventType": 6, "eventNum": 11},
            {"eventType": 6, "eventNum": 50},
            {"eventType": 6, "eventNum": 58},
            {"eventType": 6, "eventNum": 60},
            {"eventType": 6, "eventNum": 61},
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_event_bindings():", content)
        self.assertIn("func _gm_input_mouse_0():", content)
        self.assertIn("func _gm_input_mouse_61():", content)
        self.assertNotIn("func _input(event):", content)

    def test_input_event_code_files_transpile_to_dispatch_methods(self):
        """Input .gml source should load into the event-specific GMInput method."""
        self._setup_object("o_test", event_list=[
            {"eventType": 9, "eventNum": 32},
            {"eventType": 13, "eventNum": 0},
        ])
        with open(os.path.join(self.gm_dir, "objects", "o_test", "KeyPress_32.gml"), "w", encoding="utf-8") as f:
            f.write("pressed_space = true;")
        with open(os.path.join(self.gm_dir, "objects", "o_test", "Gesture_0.gml"), "w", encoding="utf-8") as f:
            f.write('tap_x = event_data[? "posX"];')

        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _gm_input_key_press_32():", content)
        self.assertIn("\tpressed_space = true", content)
        self.assertIn("func _gm_input_gesture_0():", content)
        self.assertIn('tap_x = GMRuntime.gml_ds_map_find_value(GMRuntime.gml_builtin_global("event_data"), "posX")', content)
        self.assertIn('{"event_type": 9, "event_num": 32, "method": "_gm_input_key_press_32"}', content)

    def test_script_attached_to_tscn(self):
        """The .tscn file should reference the .gd script."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('type="Script"', content)
        self.assertIn('o_test.gd', content)
        self.assertIn('script = ExtResource', content)

    def test_load_steps_script_only(self):
        """load_steps should be 2 when only script (no sprite)."""
        self._setup_object("o_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('load_steps=2', content)

    def test_load_steps_sprite_and_script(self):
        """load_steps should be 3 when both sprite and script are present."""
        self._setup_object("o_test", sprite_name="s_test")
        converter = self._make_converter()
        converter.convert_all()

        tscn_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.tscn")
        with open(tscn_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('load_steps=3', content)
        self.assertIn('PackedScene', content)
        self.assertIn('type="Script"', content)

    def test_function_ordering(self):
        """Functions should be in canonical order: lifecycle, input, custom."""
        self._setup_object("o_test", event_list=[
            {"eventType": 2, "eventNum": 0},   # Alarm (custom)
            {"eventType": 6, "eventNum": 4},   # Mouse (input)
            {"eventType": 3, "eventNum": 0},   # Step (lifecycle)
            {"eventType": 0, "eventNum": 0},   # Create (lifecycle)
        ])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        ready_pos = content.index("_ready")
        step_pos = content.index("_on_step")
        input_pos = content.index("_gm_input_event_bindings")
        alarm_pos = content.index("_on_alarm")
        self.assertLess(ready_pos, step_pos)
        self.assertLess(step_pos, input_pos)
        self.assertLess(input_pos, alarm_pos)

    def test_script_with_destroy_event(self):
        """eventType 1 should produce func _on_destroy()."""
        self._setup_object("o_test", event_list=[{"eventType": 1, "eventNum": 0}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_destroy():", content)

    def test_script_with_other_event(self):
        """eventType 7 should produce func _on_other_N()."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 26}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_other_26():", content)

    def test_script_with_no_more_lives_event(self):
        """eventType 7, eventNum 6 should add the legacy lives setter."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 6}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("var lives = 0:", content)
        self.assertIn("func _on_no_more_lives():", content)

    def test_script_with_close_button_event(self):
        """eventType 7, eventNum 30 should generate close request handling."""
        self._setup_object("o_test", event_list=[{"eventType": 7, "eventNum": 30}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("get_tree().auto_accept_quit = false", content)
        self.assertIn("func _notification(what):", content)
        self.assertIn("NOTIFICATION_WM_CLOSE_REQUEST", content)

    def test_script_with_draw_gui_event(self):
        """eventType 8, eventNum 64 should produce func _on_draw_gui()."""
        self._setup_object("o_test", event_list=[{"eventType": 8, "eventNum": 64}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_draw_gui():", content)

    def test_unknown_event_type(self):
        """Unknown event types should produce safe fallback function names."""
        self._setup_object("o_test", event_list=[{"eventType": 99, "eventNum": 5}])
        converter = self._make_converter()
        converter.convert_all()

        gd_path = os.path.join(self.godot_dir, "objects", "o_test", "o_test.gd")
        with open(gd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("func _on_event_99_5():", content)


class TestParseObjectYYEvents(unittest.TestCase):
    """Test that _parse_object_yy extracts event lists."""

    def setUp(self):
        self.gm_dir: str = tempfile.mkdtemp()
        self.godot_dir: str = tempfile.mkdtemp()
        self.converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_object_yy(self, object_name: str, content: str) -> None:
        obj_dir = os.path.join(self.gm_dir, "objects", object_name)
        os.makedirs(obj_dir, exist_ok=True)
        with open(os.path.join(obj_dir, object_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_event_list(self):
        """event_list should be included in parse result."""
        content = _make_object_yy_content("o_test", event_list=[
            {"eventType": 0, "eventNum": 0},
            {"eventType": 3, "eventNum": 0},
        ])
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result["event_list"]), 2)
        self.assertEqual(result["event_list"][0]["eventType"], 0)
        self.assertEqual(result["event_list"][1]["eventType"], 3)

    def test_empty_event_list(self):
        """Empty event list should parse as empty list."""
        content = _make_object_yy_content("o_test")
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["event_list"], [])

    def test_event_with_collision_object(self):
        """Collision events should preserve collisionObjectId."""
        content = _make_object_yy_content("o_test", event_list=[
            {"eventType": 4, "eventNum": 0, "collisionObjectId": {"name": "o_enemy"}},
        ])
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result["event_list"]), 1)
        self.assertEqual(result["event_list"][0]["collisionObjectId"]["name"], "o_enemy")


if __name__ == "__main__":
    unittest.main()
