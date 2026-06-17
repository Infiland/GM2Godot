from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import date
from typing import Any, ClassVar, cast

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.godot_validation import find_godot_binary, validate_generated_godot_project
from src.gui.setting_value import SettingValue


def _get_simple_topdown_path():
    """Return SimpleTopDown project path from env var, or None if unavailable."""
    path = os.environ.get("SIMPLE_TOPDOWN_PROJECT_PATH")
    if not path or not os.path.isdir(path):
        return None
    return path


@unittest.skipUnless(
    _get_simple_topdown_path(),
    "SIMPLE_TOPDOWN_PROJECT_PATH not set or not a valid directory",
)
class TestSimpleTopDownConversion(unittest.TestCase):
    """Integration test: convert the SimpleTopDown GameMaker test project."""

    project_path: ClassVar[str | None]
    godot_dir: ClassVar[str]
    logs: ClassVar[list[str]]

    @classmethod
    def setUpClass(cls):
        cls.project_path = _get_simple_topdown_path()
        today = date.today().strftime("%Y%m%d")
        cls.godot_dir = tempfile.mkdtemp(prefix=f"simple_topdown_{today}_")

        with open(os.path.join(cls.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write(
                '[gd_resource]\n\n'
                '[application]\n'
                'config/name="Placeholder"\n'
                'config/icon="res://old_icon.png"\n'
            )

        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: SettingValue(True) for key in all_keys}

        cls.logs = []
        conversion_running = threading.Event()
        conversion_running.set()

        def log_message(msg: object) -> None:
            cls.logs.append(str(msg))

        def ignore_progress(_value: object) -> None:
            return None

        def ignore_status(_msg: object) -> None:
            return None

        converter = cast(Any, Converter)(
            log_callback=log_message,
            progress_callback=ignore_progress,
            status_callback=ignore_status,
            conversion_running=conversion_running,
            compact_logging=True,
        )
        converter.convert(cls.project_path, "windows", cls.godot_dir, settings)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "godot_dir") and os.path.isdir(cls.godot_dir):
            shutil.rmtree(cls.godot_dir)

    def _find_generated_file(self, resource_dir: str, filename: str) -> str:
        root_dir = os.path.join(self.godot_dir, resource_dir)
        for root, _dirs, files in os.walk(root_dir):
            if filename in files:
                return os.path.join(root, filename)
        self.fail(f"Expected {filename} somewhere under {resource_dir}/")

    def _read_generated_file(self, resource_dir: str, filename: str) -> str:
        path = self._find_generated_file(resource_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_player_step_transpiles_keyboard_movement(self):
        content = self._read_generated_file("objects", "o_player.gd")

        self.assertIn("func _on_step():", content)
        self.assertIn("if GMRuntime.gml_keyboard_check(KEY_LEFT):", content)
        self.assertIn("if GMRuntime.gml_keyboard_check(KEY_RIGHT):", content)
        self.assertIn("if GMRuntime.gml_keyboard_check(KEY_UP):", content)
        self.assertIn("if GMRuntime.gml_keyboard_check(KEY_DOWN):", content)
        self.assertNotIn("func _process(delta):", content)
        self.assertNotRegex(content, r"(?<!gml_)keyboard_check\(")
        self.assertNotIn("vk_left", content)
        self.assertNotIn("vk_shift", content)

        if "superSpeed" in content or "faster" in content:
            self.assertIn("var faster", content)
            self.assertIn("var superSpeed", content)
            self.assertIn("func _ready():", content)
            self.assertIn("\tsuperSpeed = 0", content)
            self.assertIn("\tfaster = false", content)
            self.assertNotIn("func _ready():\n\tpass", content)
            self.assertIn("\tif GMRuntime.gml_keyboard_check(KEY_SHIFT):", content)
            self.assertIn("\t\tfaster = true", content)
            self.assertIn("\telse:\n\t\tfaster = false", content)
            self.assertIn("\tif GMRuntime.gml_eq(faster, true):", content)
            self.assertIn("\t\tsuperSpeed = 20", content)
            self.assertIn("position.x = GMRuntime.gml_sub(position.x, superSpeed)", content)
            self.assertIn("position.x = GMRuntime.gml_add(position.x, superSpeed)", content)
            self.assertIn("position.y = GMRuntime.gml_sub(position.y, superSpeed)", content)
            self.assertIn("position.y = GMRuntime.gml_add(position.y, superSpeed)", content)
            self.assertIn("\tsuperSpeed = 10", content)
        else:
            self.assertIn("position.x = GMRuntime.gml_sub(position.x, 10)", content)
            self.assertIn("position.x = GMRuntime.gml_add(position.x, 10)", content)
            self.assertIn("position.y = GMRuntime.gml_sub(position.y, 10)", content)
            self.assertIn("position.y = GMRuntime.gml_add(position.y, 10)", content)

    def test_player_object_instances_sprite(self):
        content = self._read_generated_file("objects", "o_player.tscn")

        self.assertIn('type="Node2D"', content)
        self.assertIn('res://sprites/s_player/s_player.tscn', content)
        self.assertIn('script = ExtResource', content)

    def test_starting_room_instantiates_player(self):
        content = self._read_generated_file("rooms", "r_starting_room.tscn")

        self.assertIn('metadata/gamemaker_room_width = 1366', content)
        self.assertIn('metadata/gamemaker_room_height = 768', content)
        self.assertIn('o_player.tscn', content)
        self.assertIn('position = Vector2(704, 384)', content)

    def test_startup_scene_points_to_starting_room(self):
        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('run/main_scene=', content)
        self.assertIn('r_starting_room.tscn', content)
        self.assertIn('GMEvents="*res://gm2godot/managers/gm_events.gd"', content)

    def test_no_tracebacks_in_logs(self):
        joined = "\n".join(str(msg) for msg in self.logs)
        self.assertNotIn("Traceback", joined, "Conversion produced a Python traceback")
        self.assertNotIn("Could not transpile GameMaker event code", joined)

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_generated_project_has_no_godot_warnings_or_errors(self) -> None:
        report = validate_generated_godot_project(self.godot_dir)

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.output_issues, (), report.output)


if __name__ == "__main__":
    unittest.main()
