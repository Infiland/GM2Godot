from __future__ import annotations

import base64
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src import cli
from src.conversion.godot_validation import (
    GODOT_VALIDATION_REPORT_RELATIVE_PATH,
    detect_godot_output_issues,
    find_godot_binary,
    generated_godot_importable_asset_paths,
    generated_godot_resource_paths,
    validate_generated_godot_project,
)


_PNG_1X1_WHITE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
    "////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
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

    def _write_png_sprite_project(self) -> Path:
        project_dir = self._write_project()
        sprite_dir = project_dir / "sprites" / "spr_player"
        sprite_dir.mkdir(parents=True)
        (sprite_dir / "spr_player.png").write_bytes(base64.b64decode(_PNG_1X1_WHITE))
        (sprite_dir / "spr_player.tscn").write_text(
            "\n".join(
                [
                    "[gd_scene load_steps=2 format=3]",
                    "",
                    '[ext_resource type="Texture2D" path="res://sprites/spr_player/spr_player.png" id="texture"]',
                    "",
                    '[node name="spr_player" type="Node2D"]',
                    "",
                    '[node name="Sprite2D" type="Sprite2D" parent="."]',
                    'texture = ExtResource("texture")',
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

    def test_importable_asset_path_discovery_is_deterministic(self) -> None:
        project_dir = self._write_png_sprite_project()

        self.assertEqual(
            generated_godot_importable_asset_paths(str(project_dir)),
            ("res://sprites/spr_player/spr_player.png",),
        )

    def test_detects_godot_warning_and_error_output(self) -> None:
        issues = detect_godot_output_issues(
            "\n".join(
                [
                    "Godot Engine v4.6.3.stable.official",
                    "SCRIPT ERROR: Parse Error: Identifier not declared.",
                    "          at: GDScript::reload (res://bad.gd:4)",
                    "WARNING: Some generated resource warning.",
                    "GM2GODOT_VALIDATION_OK 1",
                ]
            )
        )

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0].severity, "error")
        self.assertEqual(issues[0].line, "SCRIPT ERROR: Parse Error: Identifier not declared.")
        self.assertEqual(issues[1].severity, "warning")

    def test_validation_fails_when_godot_outputs_error_with_zero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'Godot Engine v4.6.3.stable.official'\n"
            "printf '%s\\n' 'SCRIPT ERROR: Parse Error: Identifier not declared.'\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.returncode, 0)
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "error")

    def test_validation_runs_import_pass_for_importable_assets(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            "    printf '%s\\n' 'GM2GODOT_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 3'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_IMPORT_OK", report.import_output)
        self.assertIn("GM2GODOT_VALIDATION_OK 3", report.output)

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_validation_loads_generated_resources(self) -> None:
        project_dir = self._write_project()

        report = validate_generated_godot_project(str(project_dir))

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("GM2GODOT_VALIDATION_OK", report.output)
        self.assertEqual(report.resource_paths, ("res://main.gd", "res://main.tscn"))

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_validation_imports_png_before_loading_scene(self) -> None:
        project_dir = self._write_png_sprite_project()

        report = validate_generated_godot_project(str(project_dir))

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.import_returncode, 0, report.import_output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("GM2GODOT_VALIDATION_OK", report.output)

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
        self.assertEqual(report["output_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
