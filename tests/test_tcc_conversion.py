from __future__ import annotations

import json
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
from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome
from src.conversion.generated_paths import generated_resource_stem
from src.conversion.godot_validation import find_godot_binary, validate_generated_godot_project
from src.gui.setting_value import SettingValue
from tests.conversion_outcome_helpers import completed_conversion_step_ledger


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

        outcome = cast(
            ConversionOutcome,
            converter.convert(cls.tcc_path, "windows", cls.godot_dir, settings),
        )
        expected_outcome = ConversionOutcome(
            state="partial",
            steps=completed_conversion_step_ledger(all_keys),
            resources=ConversionCounts(
                requested=5386,
                executed=5386,
                completed=5146,
                skipped=240,
            ),
        )
        if outcome != expected_outcome:
            raise AssertionError(
                "The Colorful Creature conversion outcome was unexpected:\n"
                + outcome.summary_line()
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "godot_dir") and os.path.isdir(cls.godot_dir):
            shutil.rmtree(cls.godot_dir)

    def _read_generated_file(self, *parts: str) -> str:
        with open(os.path.join(self.godot_dir, *parts), "r", encoding="utf-8") as f:
            return f.read()

    def _conversion_diagnostics(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(self._read_generated_file("gm2godot", "conversion_diagnostics.json")),
        )

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
        for name in ("calendar", "challenges", "fonts", "languages", "other", "quests"):
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

    def test_partial_outcome_diagnostics_match_known_source_gaps(self) -> None:
        diagnostics = self._conversion_diagnostics()
        diagnostic_entries = cast(list[dict[str, Any]], diagnostics.get("diagnostics", []))

        script_transpile_diagnostics = [
            diagnostic
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
            and diagnostic.get("resource_type") == "script"
        ]
        script_transpile_resources = {
            str(diagnostic.get("resource", ""))
            for diagnostic in script_transpile_diagnostics
        }
        object_transpile_diagnostics = [
            diagnostic
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
            and diagnostic.get("resource_type") == "object"
        ]
        object_transpile_resources = {
            str(diagnostic.get("resource", ""))
            for diagnostic in object_transpile_diagnostics
        }
        room_transpile_diagnostics = [
            diagnostic
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
            and diagnostic.get("resource_type") == "room"
        ]
        room_transpile_resources = {
            str(diagnostic.get("resource", ""))
            for diagnostic in room_transpile_diagnostics
        }
        all_transpile_diagnostics = [
            diagnostic
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
        ]
        self.assertNotIn("", script_transpile_resources)
        self.assertNotIn("", object_transpile_resources)
        self.assertEqual(len(all_transpile_diagnostics), 191)
        self.assertEqual(len(script_transpile_diagnostics), 74)
        self.assertEqual(len(script_transpile_resources), 74)
        self.assertEqual(len(object_transpile_diagnostics), 115)
        self.assertEqual(len(object_transpile_resources), 100)
        self.assertEqual(len(room_transpile_diagnostics), 2)
        self.assertEqual(room_transpile_resources, {"r_donolvl1", "r_lvl1"})

        object_event_source_missing = [
            (
                str(diagnostic.get("resource", "")),
                str(diagnostic.get("event", "")),
            )
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-OBJECT-EVENT-SOURCE-MISSING"
        ]
        object_collision_source_missing = [
            (
                str(diagnostic.get("resource", "")),
                str(diagnostic.get("event", "")),
            )
            for diagnostic in diagnostic_entries
            if diagnostic.get("code")
            == "GM2GD-OBJECT-MISSING-COLLISION-EVENT-SOURCE"
        ]
        self.assertEqual(
            object_event_source_missing,
            [("o_animatedLEicon", "_draw")],
        )
        self.assertEqual(
            object_collision_source_missing,
            [("o_playerbulletMU", "_on_collision")],
        )

        room_creation_missing = [
            diagnostic
            for diagnostic in diagnostic_entries
            if diagnostic.get("code") == "GM2GD-ROOM-CREATION-MISSING"
        ]
        room_creation_missing_resources = {
            str(diagnostic.get("resource", ""))
            for diagnostic in room_creation_missing
        }
        self.assertEqual(len(room_creation_missing), 75)
        self.assertNotIn("", room_creation_missing_resources)
        self.assertEqual(len(room_creation_missing_resources), 64)

        expected_skipped_resources_path = os.path.join(
            PROJECT_ROOT,
            "tests",
            "fixtures",
            "tcc_expected_skipped_resources.json",
        )
        with open(expected_skipped_resources_path, encoding="utf-8") as expected_file:
            expected_skipped_resources = cast(
                dict[str, list[str]],
                json.load(expected_file),
            )
        actual_skipped_resources = {
            "scripts": sorted(script_transpile_resources),
            "objects": sorted(
                object_transpile_resources
                | {resource for resource, _event in object_event_source_missing}
                | {resource for resource, _event in object_collision_source_missing}
            ),
            "rooms": sorted(room_creation_missing_resources | room_transpile_resources),
        }
        self.assertEqual(actual_skipped_resources, expected_skipped_resources)

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
