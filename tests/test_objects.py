import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.objects import ObjectConverter


def _make_object_yy_content(name, sprite_name=None):
    """Build a GameMaker object .yy file string."""
    if sprite_name is not None:
        sprite_id = (
            '{{"name": "{sprite_name}", '
            '"path": "sprites/{sprite_name}/{sprite_name}.yy",}}'
        ).format(sprite_name=sprite_name)
    else:
        sprite_id = "null"

    return (
        '{{\n'
        '  "$GMObject": "",\n'
        '  "%Name": "{name}",\n'
        '  "eventList": [],\n'
        '  "managed": true,\n'
        '  "name": "{name}",\n'
        '  "overriddenProperties": [],\n'
        '  "parent": {{"name": "Objects", "path": "folders/Objects.yy",}},\n'
        '  "parentObjectId": null,\n'
        '  "persistent": false,\n'
        '  "physicsObject": false,\n'
        '  "properties": [],\n'
        '  "resourceType": "GMObject",\n'
        '  "resourceVersion": "2.0",\n'
        '  "solid": false,\n'
        '  "spriteId": {sprite_id},\n'
        '  "spriteMaskId": null,\n'
        '  "visible": true,\n'
        '}}'
    ).format(name=name, sprite_id=sprite_id)


def _create_fake_sprite_scene(godot_dir, sprite_name):
    """Create a minimal sprite .tscn file in the Godot project."""
    sprite_dir = os.path.join(godot_dir, "sprites", sprite_name)
    os.makedirs(sprite_dir, exist_ok=True)
    tscn_path = os.path.join(sprite_dir, sprite_name + ".tscn")
    with open(tscn_path, "w", encoding="utf-8") as f:
        f.write('[gd_scene format=3]\n\n[node name="{}" type="Area2D"]\n'.format(sprite_name))


class TestObjectConverterBasic(unittest.TestCase):
    """Test ObjectConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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

    def _make_converter(self):
        return ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
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
        self.assertNotIn('ext_resource', content)
        self.assertNotIn('instance', content)


class TestObjectConverterEmpty(unittest.TestCase):
    """Edge cases: missing objects dir and missing sprites."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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
        self.assertNotIn('ext_resource', content)


class TestParseObjectYY(unittest.TestCase):
    """Test _parse_object_yy directly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = ObjectConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_object_yy(self, object_name, content):
        obj_dir = os.path.join(self.gm_dir, "objects", object_name)
        os.makedirs(obj_dir, exist_ok=True)
        with open(os.path.join(obj_dir, object_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_valid_object_with_sprite(self):
        content = _make_object_yy_content("o_test", sprite_name="s_test")
        self._write_object_yy("o_test", content)

        result = self.converter._parse_object_yy("o_test")
        self.assertIsNotNone(result)
        self.assertEqual(result["sprite_name"], "s_test")

    def test_parses_valid_object_without_sprite(self):
        content = _make_object_yy_content("o_empty", sprite_name=None)
        self._write_object_yy("o_empty", content)

        result = self.converter._parse_object_yy("o_empty")
        self.assertIsNotNone(result)
        self.assertIsNone(result["sprite_name"])

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
        self.assertEqual(result["sprite_name"], "s_tc")


class TestObjectConverterYYPFiltering(unittest.TestCase):
    """Test that objects are filtered against the .yyp project file."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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


if __name__ == "__main__":
    unittest.main()
