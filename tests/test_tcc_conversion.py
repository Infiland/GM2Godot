from __future__ import annotations

import os
import sys
import shutil
import tempfile
import threading
import unittest
from datetime import date
from typing import Any, ClassVar, cast

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.conversion.generated_paths import generated_resource_stem
from src.conversion.godot_validation import find_godot_binary, validate_generated_godot_project
from src.gui.setting_value import SettingValue


def _get_tcc_path():
    """Return TCC project path from env var, or None if not available."""
    path = os.environ.get("TCC_PROJECT_PATH")
    if not path or not os.path.isdir(path):
        return None
    return path


@unittest.skipUnless(_get_tcc_path(), "TCC_PROJECT_PATH not set or not a valid directory")
class TestTCCConversion(unittest.TestCase):
    """Integration test: convert The Colorful Creature project to Godot."""

    tcc_path: ClassVar[str | None]
    godot_dir: ClassVar[str]
    logs: ClassVar[list[str]]

    @classmethod
    def setUpClass(cls):
        cls.tcc_path = _get_tcc_path()
        today = date.today().strftime("%Y%m%d")
        cls.godot_dir = tempfile.mkdtemp(prefix=f"sample_project_{today}_")

        # Minimal project.godot required by the converter
        with open(os.path.join(cls.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write(
                '[gd_resource]\n\n'
                '[application]\n'
                'config/name="Placeholder"\n'
                'config/icon="res://old_icon.png"\n'
            )

        # Enable all conversion categories
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

        converter.convert(cls.tcc_path, "windows", cls.godot_dir, settings)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "godot_dir") and os.path.isdir(cls.godot_dir):
            shutil.rmtree(cls.godot_dir)

    # --- Sprites ---

    def test_sprites_directory_created(self):
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, "sprites")))

    def test_known_sprites_exist(self):
        sprites_dir = os.path.join(self.godot_dir, "sprites")
        all_dirs: set[str] = set()
        for _root, dirs, _ in os.walk(sprites_dir):
            all_dirs.update(dirs)
        for name in ("s_C1AIcon", "s_C2AIcon", "s_C3AIcon"):
            expected = generated_resource_stem(name)
            self.assertIn(expected, all_dirs, f"Expected sprites/{expected}/ directory (nested)")

    def test_sprites_contain_png_files(self):
        sprites_dir = os.path.join(self.godot_dir, "sprites")
        sprite_path = None
        for root, dirs, _ in os.walk(sprites_dir):
            expected = generated_resource_stem("s_C1AIcon")
            if expected in dirs:
                sprite_path = os.path.join(root, expected)
                break
        if sprite_path and os.path.isdir(sprite_path):
            pngs = [f for f in os.listdir(sprite_path) if f.endswith(".png")]
            self.assertGreater(
                len(pngs),
                0,
                f"Expected at least one PNG in {generated_resource_stem('s_C1AIcon')}/",
            )

    def test_sprites_count(self):
        sprites_dir = os.path.join(self.godot_dir, "sprites")
        sprite_dirs: list[str] = []
        for root, _dirs, files in os.walk(sprites_dir):
            if any(f.endswith(".png") for f in files):
                sprite_dirs.append(root)
        self.assertGreater(len(sprite_dirs), 800, f"Expected 800+ sprite directories, got {len(sprite_dirs)}")

    # --- Sounds ---

    def test_sounds_directory_created(self):
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, "sounds")))

    def test_known_sound_exists(self):
        sounds_dir = os.path.join(self.godot_dir, "sounds")
        found = False
        for _root, _, files in os.walk(sounds_dir):
            if "m_ahoy.wav" in files:
                found = True
                break
        self.assertTrue(found, "Expected m_ahoy.wav somewhere under sounds/")

    def test_sounds_count(self):
        sounds_dir = os.path.join(self.godot_dir, "sounds")
        sound_files: list[str] = []
        for _root, _, files in os.walk(sounds_dir):
            sound_files.extend(f for f in files if f.endswith((".wav", ".mp3", ".ogg")))
        self.assertGreater(len(sound_files), 50, f"Expected 50+ sound files, got {len(sound_files)}")

    # --- Shaders ---

    def test_shaders_directory_created(self):
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, "shaders")))

    def test_known_shader_converted(self):
        shader_path = os.path.join(self.godot_dir, "shaders", "shd_wave.gdshader")
        self.assertTrue(os.path.isfile(shader_path), "Expected shaders/shd_wave.gdshader")

    # --- Notes ---

    def test_notes_directory_created(self):
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, "notes")))

    def test_known_notes_converted(self):
        notes_dir = os.path.join(self.godot_dir, "notes")
        all_files: dict[str, str] = {}
        for root, _, files in os.walk(notes_dir):
            for f in files:
                all_files[f] = os.path.join(root, f)
        for name in ("InvisibleIsntHere", "LEG SKIN", "color"):
            expected = f"{name}.txt"
            self.assertIn(expected, all_files, f"Expected {expected} somewhere under notes/")

    # --- Included files ---

    def test_included_files_directory_created(self):
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, "included_files")))

    def test_included_files_subdirectories(self):
        included_dir = os.path.join(self.godot_dir, "included_files")
        for name in ("Calendar", "Challenges", "Fonts", "Languages", "Other", "Quests"):
            self.assertTrue(
                os.path.isdir(os.path.join(included_dir, name)),
                f"Expected included_files/{name}/ directory",
            )

    # --- Project settings ---

    def test_project_name_updated(self):
        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('config/name="The Colorful Creature"', content)
        self.assertNotIn("Placeholder", content)

    def test_icon_files_created(self):
        self.assertTrue(os.path.isfile(os.path.join(self.godot_dir, "icon.ico")))
        self.assertTrue(os.path.isfile(os.path.join(self.godot_dir, "icon.png")))

    def test_audio_bus_layout_created(self):
        bus_layout = os.path.join(self.godot_dir, "default_bus_layout.tres")
        self.assertTrue(os.path.isfile(bus_layout))
        with open(bus_layout, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Master", content)

    # --- No crashes ---

    def test_no_tracebacks_in_logs(self):
        joined = "\n".join(str(msg) for msg in self.logs)
        self.assertNotIn("Traceback", joined, "Conversion produced a Python traceback")

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_generated_project_has_no_godot_warnings_or_errors(self) -> None:
        report = validate_generated_godot_project(
            self.godot_dir,
            timeout=360,
            load_resources=False,
        )

        self.assertEqual(report.status, "passed", report.message + "\n" + report.output)
        self.assertEqual(report.output_issues, (), report.message + "\n" + report.output)


if __name__ == "__main__":
    unittest.main()
