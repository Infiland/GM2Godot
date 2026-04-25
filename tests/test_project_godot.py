import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.project_godot import GodotProjectFile


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestGodotProjectFile(unittest.TestCase):
    def setUp(self):
        self.godot_dir = tempfile.mkdtemp()
        self.project_path = os.path.join(self.godot_dir, "project.godot")

    def tearDown(self):
        shutil.rmtree(self.godot_dir)

    def _read_project(self):
        with open(self.project_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_set_main_scene_replaces_existing_and_preserves_settings(self):
        _write_file(self.project_path, (
            '[application]\n'
            'config/name="Existing"\n'
            'run/main_scene="res://old.tscn"\n'
            'config/icon="res://icon.png"\n'
            '\n'
            '[rendering]\n'
            'renderer/rendering_method="gl_compatibility"\n'
        ))

        result = GodotProjectFile(self.project_path).set_main_scene(
            "res://rooms/r_first/r_first.tscn"
        )

        content = self._read_project()
        self.assertTrue(result)
        self.assertIn('run/main_scene="res://rooms/r_first/r_first.tscn"', content)
        self.assertNotIn('run/main_scene="res://old.tscn"', content)
        self.assertIn('config/name="Existing"', content)
        self.assertIn('config/icon="res://icon.png"', content)
        self.assertIn('[rendering]', content)
        self.assertIn('renderer/rendering_method="gl_compatibility"', content)

    def test_set_main_scene_adds_to_existing_application_section(self):
        _write_file(self.project_path, (
            '[application]\n'
            'config/name="Existing"\n'
            '\n'
            '[display]\n'
            'window/size/viewport_width=1280\n'
        ))

        result = GodotProjectFile(self.project_path).set_main_scene(
            "res://rooms/r_a/r_a.tscn"
        )

        content = self._read_project()
        self.assertTrue(result)
        self.assertIn('[application]', content)
        self.assertIn('config/name="Existing"', content)
        self.assertIn('run/main_scene="res://rooms/r_a/r_a.tscn"', content)
        self.assertIn('[display]', content)
        self.assertIn('window/size/viewport_width=1280', content)

    def test_set_main_scene_adds_application_section_when_missing(self):
        _write_file(self.project_path, (
            '[rendering]\n'
            'quality/driver="GLES3"\n'
        ))

        result = GodotProjectFile(self.project_path).set_main_scene(
            "res://rooms/r_a/r_a.tscn"
        )

        content = self._read_project()
        self.assertTrue(result)
        self.assertIn('[application]', content)
        self.assertIn('run/main_scene="res://rooms/r_a/r_a.tscn"', content)
        self.assertIn('[rendering]', content)
        self.assertIn('quality/driver="GLES3"', content)

    def test_set_main_scene_does_not_change_other_sections(self):
        _write_file(self.project_path, (
            '[other]\n'
            'run/main_scene="res://other.tscn"\n'
            '\n'
            '[application]\n'
            'config/name="Existing"\n'
        ))

        result = GodotProjectFile(self.project_path).set_main_scene(
            "res://rooms/r_a/r_a.tscn"
        )

        content = self._read_project()
        self.assertTrue(result)
        self.assertIn('[other]\nrun/main_scene="res://other.tscn"', content)
        self.assertIn('run/main_scene="res://rooms/r_a/r_a.tscn"', content)

    def test_set_main_scene_returns_false_when_project_missing(self):
        result = GodotProjectFile(self.project_path).set_main_scene(
            "res://rooms/r_a/r_a.tscn"
        )

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
