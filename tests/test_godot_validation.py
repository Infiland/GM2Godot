from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src import cli
from src.conversion.godot_validation import (
    GODOT_VALIDATION_REPORT_RELATIVE_PATH,
    find_godot_binary,
    generated_godot_resource_paths,
    validate_generated_godot_project,
)


class TestGodotValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def _write_project(self) -> Path:
        project_dir = self.temp_dir / "godot"
        project_dir.mkdir()
        (project_dir / "project.godot").write_text(
            '[application]\nconfig/name="Validation Fixture"\nrun/main_scene="res://main.tscn"\n',
            encoding="utf-8",
        )
        (project_dir / "main.gd").write_text(
            "extends Node\n\nfunc _ready():\n\tpass\n",
            encoding="utf-8",
        )
        (project_dir / "main.tscn").write_text(
            "\n".join(
                [
                    "[gd_scene load_steps=2 format=3]",
                    "",
                    '[ext_resource type="Script" path="res://main.gd" id="main_script"]',
                    "",
                    '[node name="Main" type="Node"]',
                    'script = ExtResource("main_script")',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return project_dir

    def test_resource_path_discovery_is_deterministic(self) -> None:
        project_dir = self._write_project()

        self.assertEqual(
            generated_godot_resource_paths(str(project_dir)),
            ("res://main.gd", "res://main.tscn"),
        )

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_validation_loads_generated_resources(self) -> None:
        project_dir = self._write_project()

        report = validate_generated_godot_project(str(project_dir))

        self.assertEqual(report.status, "passed", report.output)
        self.assertIn("GM2GODOT_VALIDATION_OK", report.output)
        self.assertEqual(report.resource_paths, ("res://main.gd", "res://main.tscn"))

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_cli_validate_writes_godot_validation_report(self) -> None:
        project_dir = self._write_project()
        (project_dir / "gm2godot").mkdir()
        (project_dir / "gm2godot" / "conversion_diagnostics.json").write_text(
            '{"summary":{"info":0,"warning":0,"error":0,"total":0},"diagnostics":[]}\n',
            encoding="utf-8",
        )

        exit_code = cli.main(["validate", "--godot-project", str(project_dir)])

        self.assertEqual(exit_code, 0)
        report_path = project_dir / GODOT_VALIDATION_REPORT_RELATIVE_PATH
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["resource_count"], 2)


if __name__ == "__main__":
    unittest.main()
