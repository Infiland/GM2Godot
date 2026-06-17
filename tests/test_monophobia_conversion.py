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
from src.conversion.godot_validation import find_godot_binary, validate_generated_godot_project
from src.gui.setting_value import SettingValue


def _get_monophobia_path() -> str | None:
    path = os.environ.get("MONOPHOBIA_PROJECT_PATH")
    if not path or not os.path.isdir(path):
        return None
    return path


@unittest.skipUnless(
    _get_monophobia_path(),
    "MONOPHOBIA_PROJECT_PATH not set or not a valid directory",
)
class TestMonophobiaConversion(unittest.TestCase):
    """Integration test: convert Monophobia and require clean Godot validation."""

    monophobia_path: ClassVar[str | None]
    godot_dir: ClassVar[str]
    logs: ClassVar[list[str]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.monophobia_path = _get_monophobia_path()
        today = date.today().strftime("%Y%m%d")
        cls.godot_dir = tempfile.mkdtemp(prefix=f"monophobia_{today}_")

        with open(os.path.join(cls.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write(
                '[gd_resource]\n\n'
                '[application]\n'
                'config/name="Monophobia Probe"\n'
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
        converter.convert(cls.monophobia_path, "windows", cls.godot_dir, settings)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "godot_dir") and os.path.isdir(cls.godot_dir):
            shutil.rmtree(cls.godot_dir)

    def _read_generated_file(self, *parts: str) -> str:
        with open(os.path.join(self.godot_dir, *parts), "r", encoding="utf-8") as f:
            return f.read()

    def test_ending_script_functions_are_registered(self) -> None:
        registry = self._read_generated_file("gm2godot", "gml_script_registry.gd")
        ending_script = self._read_generated_file("scripts", "ending.gd")

        self.assertIn('"name": "loadending"', registry)
        self.assertIn('"name": "saveending"', registry)
        self.assertIn("gm2godot_callable_loadending()", registry)
        self.assertIn("gm2godot_scoped_callable_saveending()", registry)
        self.assertIn("func _gm_script_call_loadending():", ending_script)
        self.assertIn("func _gm_script_call_saveending():", ending_script)

    def test_ending_call_sites_use_script_registry(self) -> None:
        title_screen = self._read_generated_file(
            "objects",
            "title_screen",
            "o_titlescreen",
            "o_titlescreen.gd",
        )
        ending_picture = self._read_generated_file(
            "objects",
            "o_endingpicture",
            "o_endingpicture.gd",
        )

        self.assertIn(
            'GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index("loadending"), [], self, other)',
            title_screen,
        )
        self.assertIn(
            'GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index("saveending"), [], self, other)',
            ending_picture,
        )
        self.assertNotIn("\tloadending()", title_screen)
        self.assertNotIn("\tsaveending()", ending_picture)

    def test_ending_script_has_no_transpile_failure_diagnostic(self) -> None:
        diagnostics = json.loads(
            self._read_generated_file("gm2godot", "conversion_diagnostics.json")
        )
        ending_failures = [
            diagnostic
            for diagnostic in diagnostics.get("diagnostics", [])
            if diagnostic.get("resource") == "ending"
            and diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
        ]

        self.assertEqual(ending_failures, [])

    def test_player_background_layer_calls_have_no_transpile_failure_diagnostic(self) -> None:
        diagnostics = json.loads(
            self._read_generated_file("gm2godot", "conversion_diagnostics.json")
        )
        player_background_failures = [
            diagnostic
            for diagnostic in diagnostics.get("diagnostics", [])
            if diagnostic.get("resource") == "o_player"
            and diagnostic.get("code") == "GM2GD-GML-TRANSPILE"
            and diagnostic.get("api") == "layer_background_get_id"
        ]

        self.assertEqual(player_background_failures, [])

    def test_generated_project_has_no_godot_warnings_or_errors(self) -> None:
        self.assertIsNotNone(
            find_godot_binary(),
            "Godot binary is required for Monophobia strict validation.",
        )
        report = validate_generated_godot_project(self.godot_dir, timeout=180)

        self.assertEqual(report.status, "passed", report.message + "\n" + report.output)
        self.assertEqual(report.output_issues, (), report.message + "\n" + report.output)


if __name__ == "__main__":
    unittest.main()
