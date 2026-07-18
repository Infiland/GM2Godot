from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
from src.conversion.project_godot import GodotProjectFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectPreflightGodotTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("GODOT_BIN"), "GODOT_BIN is not set")
    def test_cli_generated_project_opens_in_exact_godot_4_7_1(self) -> None:
        godot_binary = os.environ["GODOT_BIN"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gm_directory = root / "game-maker"
            gm_directory.mkdir()
            project_name = 'Godot 4.7.1 "Open" Test'
            (gm_directory / "GodotOpen.yyp").write_text(
                json.dumps({"%Name": project_name}),
                encoding="utf-8",
            )
            destination = root / "godot-output"

            conversion_result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "convert",
                    "--gm-project",
                    os.fspath(gm_directory),
                    "--godot-project",
                    os.fspath(destination),
                    "--allow-partial",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                conversion_result.returncode,
                0,
                conversion_result.stdout + conversion_result.stderr,
            )
            expected_outcome = ConversionOutcome(
                state="partial",
                converters=ConversionCounts(
                    requested=15,
                    executed=15,
                    completed=15,
                ),
                resources=ConversionCounts(
                    requested=4,
                    executed=4,
                    completed=1,
                    skipped=3,
                ),
            )
            diagnostics_report = json.loads(
                (destination / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                diagnostics_report["outcome"],
                expected_outcome.to_dict(),
            )
            project_content = (destination / "project.godot").read_text(
                encoding="utf-8"
            )
            self.assertIn("config_version=5", project_content)
            self.assertIn(
                f"config/name={json.dumps(project_name)}",
                project_content,
            )
            self.assertIn(
                'config/features=PackedStringArray("4.7")',
                project_content,
            )

            version_result = subprocess.run(
                [godot_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(version_result.returncode, 0, version_result.stderr)
            self.assertRegex(version_result.stdout.strip(), r"^4\.7\.1\.stable\.")

            open_result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--editor",
                    "--path",
                    os.fspath(destination),
                    "--quit",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            output = open_result.stdout + open_result.stderr
            self.assertEqual(open_result.returncode, 0, output)
            self.assertNotIn("Parse Error", output)
            self.assertNotIn("ERROR:", output)

    @unittest.skipUnless(os.environ.get("GODOT_BIN"), "GODOT_BIN is not set")
    def test_autoload_whitespace_duplicates_resolve_to_managed_path_in_exact_godot(self) -> None:
        godot_binary = os.environ["GODOT_BIN"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_directory = Path(temporary_directory)
            project_file = project_directory / "project.godot"
            project_file.write_text(
                'config_version=5\n\n[autoload]\n'
                'GMRuntime = "*res://old_runtime.gd"\n'
                'GMRuntime="*res://last_runtime.gd"\n',
                encoding="utf-8",
            )
            for filename in ("old_runtime.gd", "last_runtime.gd", "new_runtime.gd"):
                (project_directory / filename).write_text("extends Node\n", encoding="utf-8")

            self.assertTrue(
                GodotProjectFile(os.fspath(project_file)).set_autoloads((
                    ("GMRuntime", "res://new_runtime.gd"),
                ))
            )
            (project_directory / "check_autoload.gd").write_text(
                'extends SceneTree\n'
                'func _initialize():\n'
                '\tvar actual = ProjectSettings.get_setting("autoload/GMRuntime")\n'
                '\tif actual != "*res://new_runtime.gd":\n'
                '\t\tpush_error("Unexpected autoload: " + str(actual))\n'
                '\t\tquit(1)\n'
                '\telse:\n'
                '\t\tquit(0)\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    os.fspath(project_directory),
                    "--script",
                    "res://check_autoload.gd",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertNotIn("Unexpected autoload", output)


if __name__ == "__main__":
    unittest.main()
