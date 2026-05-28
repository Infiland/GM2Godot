from __future__ import annotations

import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import cli
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH


class TestCLIReports(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_report_writes_static_and_diagnostic_reports(self) -> None:
        report_dir = os.path.join(self.temp_dir, "reports")

        exit_code = cli.main(["report", "--report-dir", report_dir])

        self.assertEqual(exit_code, 0)
        report_root = os.path.join(report_dir, "gm2godot")
        self.assertTrue(os.path.isfile(os.path.join(report_root, "conversion_diagnostics.json")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "conversion_diagnostics.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "gml_manual_scope.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "gml_api_compatibility.md")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "platform_capability_report.json")))
        self.assertTrue(os.path.isfile(os.path.join(report_root, "platform_capability_report.md")))

        with open(os.path.join(report_root, "conversion_diagnostics.json"), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        self.assertEqual(report["summary"]["total"], 0)

        with open(os.path.join(report_root, "platform_capability_report.json"), "r", encoding="utf-8") as report_file:
            capability_report = json.load(report_file)

        self.assertEqual(capability_report["issue_number"], 606)
        self.assertTrue(
            any(
                check["capability"] == "microphone"
                and "audio_start_recording" in check["apis"]
                for check in capability_report["checks"]
            )
        )

    def test_version_flag_prints_current_version(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), "GM2Godot 0.6.1")

    def test_list_converters_writes_text_inventory(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["list-converters"])

        inventory = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Default groups: assets, project, wip", inventory)
        self.assertIn("Conversion groups:", inventory)
        self.assertIn("Converter keys:", inventory)
        self.assertIn("  assets: sprites, fonts, sounds", inventory)
        self.assertIn("  asset_registry", inventory)

    def test_list_converters_writes_json_inventory(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = cli.main(["list-converters", "--format", "json"])

        inventory = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(inventory["default_groups"], ["assets", "project", "wip"])
        self.assertIn("sprites", inventory["groups"]["assets"])
        self.assertIn("project_settings", inventory["groups"]["project"])
        self.assertIn("sound_group_folders", inventory["converter_keys"])

    def test_module_entrypoint_prints_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--version"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "GM2Godot 0.6.1")

    def test_app_entrypoint_routes_global_cli_flags(self) -> None:
        app_entrypoint = importlib.import_module("main")

        with (
            patch.object(sys, "argv", ["main.py", "--version"]),
            patch("src.cli.main", return_value=0) as cli_main,
            self.assertRaises(SystemExit) as context,
        ):
            app_entrypoint.main()

        self.assertEqual(context.exception.code, 0)
        cli_main.assert_called_once_with(["--version"])

    def test_analyze_only_writes_platform_diagnostic_without_conversion_output(self) -> None:
        gm_dir = os.path.join(self.temp_dir, "gm")
        report_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(gm_dir)

        exit_code = cli.main([
            "analyze",
            "--gm-project",
            gm_dir,
            "--report-dir",
            report_dir,
            "--target-platform",
            "linux",
            "--max-warnings",
            "0",
        ])

        self.assertEqual(exit_code, 2)
        self.assertFalse(os.path.exists(os.path.join(gm_dir, "project.godot")))

        with open(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        codes = [diagnostic["code"] for diagnostic in report["diagnostics"]]
        self.assertIn("GM2GD-CLI-TARGET-PLATFORM", codes)
        self.assertIn("GM2GD-ANALYZE-MISSING-YYP", codes)
        self.assertTrue(any("linux" in diagnostic["message"] for diagnostic in report["diagnostics"]))
        with open(
            os.path.join(report_dir, "gm2godot", "platform_capability_report.json"),
            "r",
            encoding="utf-8",
        ) as capability_file:
            capability_report = json.load(capability_file)
        self.assertEqual(capability_report["selected_target"], "linux")

    def test_validate_applies_thresholds_to_existing_diagnostics_report(self) -> None:
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_root = os.path.join(godot_dir, "gm2godot")
        os.makedirs(report_root)
        with open(os.path.join(godot_dir, "project.godot"), "w", encoding="utf-8") as project_file:
            project_file.write('[application]\nconfig/name="Demo"\n')
        with open(os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "w", encoding="utf-8") as report_file:
            json.dump(
                {
                    "summary": {"info": 0, "warning": 1, "error": 0, "total": 1},
                    "diagnostics": [
                        {
                            "severity": "warning",
                            "code": "GM2GD-GML-UNSUPPORTED",
                            "message": "Unsupported GML API: show_message_async",
                            "api": "show_message_async",
                        }
                    ],
                },
                report_file,
            )

        exit_code = cli.main(["validate", "--godot-project", godot_dir, "--fail-on-unsupported"])

        self.assertEqual(exit_code, 2)

    def test_convert_can_write_selected_reports_and_fail_warning_threshold(self) -> None:
        gm_dir = os.path.join(self.temp_dir, "gm")
        godot_dir = os.path.join(self.temp_dir, "godot")
        report_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(gm_dir)
        os.makedirs(godot_dir)
        with open(os.path.join(gm_dir, "Bad.yyp"), "w", encoding="utf-8") as yyp_file:
            yyp_file.write('{"resources": [}')
        with open(os.path.join(godot_dir, "project.godot"), "w", encoding="utf-8") as project_file:
            project_file.write('[application]\nconfig/name="Demo"\n')

        exit_code = cli.main([
            "convert",
            "--gm-project",
            gm_dir,
            "--godot-project",
            godot_dir,
            "--only",
            "asset_registry",
            "--report-dir",
            report_dir,
            "--max-warnings",
            "0",
        ])

        self.assertEqual(exit_code, 2)
        self.assertTrue(os.path.isfile(os.path.join(godot_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)))
        self.assertTrue(os.path.isfile(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH)))

        with open(os.path.join(report_dir, DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH), "r", encoding="utf-8") as report_file:
            report = json.load(report_file)

        codes = [diagnostic["code"] for diagnostic in report["diagnostics"]]
        self.assertIn("GM2GD-WARNING", codes)
        self.assertIn("GM2GD-CLI-TARGET-PLATFORM", codes)


if __name__ == "__main__":
    unittest.main()
