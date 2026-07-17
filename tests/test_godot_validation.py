from __future__ import annotations

# pyright: reportPrivateUsage=false

import base64
import json
import os
import signal
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import cli
from src.conversion.godot_validation import (
    GODOT_VALIDATION_REPORT_RELATIVE_PATH,
    detect_godot_output_issues,
    find_godot_binary,
    generated_godot_importable_asset_paths,
    generated_godot_resource_paths,
    _run_godot_command,
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

    def _write_fake_godot(self, script: str) -> Path:
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        fake_godot.chmod(0o755)
        return fake_godot

    @staticmethod
    def _high_volume_output_shell(
        first_line: str,
        last_line: str,
        *,
        central_line: str = "CENTRAL_OUTPUT_MUST_BE_DISCARDED",
        last_to_stderr: bool = False,
    ) -> str:
        last_redirect = " >&2" if last_to_stderr else ""
        return (
            f"printf '%s\\n' '{first_line}'\n"
            "i=0\n"
            "while [ \"$i\" -lt 200 ]; do\n"
            "  if [ \"$i\" -eq 100 ]; then\n"
            f"    printf '%s\\n' '{central_line}'\n"
            "  else\n"
            "    printf 'filler-%03d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\\n' \"$i\"\n"
            "  fi\n"
            "  i=$((i + 1))\n"
            "done\n"
            f"printf '%s\\n' '{last_line}'{last_redirect}\n"
        )

    def test_find_godot_binary_uses_version_neutral_macos_app_path(self) -> None:
        macos_app_binary = "/Applications/Godot.app/Contents/MacOS/Godot"

        def is_existing_candidate(candidate: str) -> bool:
            return candidate == macos_app_binary

        with (
            patch("src.conversion.godot_validation.os.environ.get", return_value=None),
            patch("src.conversion.godot_validation.shutil.which", return_value=None),
            patch(
                "src.conversion.godot_validation.os.path.isfile",
                side_effect=is_existing_candidate,
            ) as is_file,
        ):
            resolved_binary = find_godot_binary()

        self.assertEqual(resolved_binary, macos_app_binary)
        is_file.assert_called_once_with(macos_app_binary)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_command_exit_with_inherited_stdout_remains_bounded(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot("sleep 3 &\nexit 0\n")
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }
        started = time.monotonic()

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
        )

        elapsed = time.monotonic() - started
        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.returncode, 0)
        self.assertLess(elapsed, 2.0)
        self.assertEqual(lingering_readers, [])

    @unittest.skipUnless(os.name == "posix", "requires fork and POSIX sessions")
    def test_detached_stdout_holder_does_not_consume_remaining_timeout(self) -> None:
        child_pid_path = self.temp_dir / "detached-child.pid"
        fake_godot = self.temp_dir / "detached-stdout-holder.py"
        fake_godot.write_text(
            "\n".join(
                (
                    "import os",
                    "import time",
                    "from pathlib import Path",
                    "",
                    "child_pid = os.fork()",
                    "if child_pid == 0:",
                    "    os.setsid()",
                    f"    Path({os.fspath(child_pid_path)!r}).write_text(str(os.getpid()))",
                    "    time.sleep(30)",
                    "    os._exit(0)",
                    "os._exit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }
        started = time.monotonic()
        child_pid: int | None = None

        try:
            result = _run_godot_command(
                [sys.executable, os.fspath(fake_godot)],
                timeout=3,
            )
            elapsed = time.monotonic() - started
            for _attempt in range(100):
                if child_pid_path.is_file():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    break
                time.sleep(0.01)
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertEqual(result.returncode, 0)
        self.assertLess(elapsed, 1.5)
        self.assertIsNotNone(child_pid)
        self.assertEqual(lingering_readers, [])

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

    def test_detects_colored_godot_warning_and_error_output(self) -> None:
        issues = detect_godot_output_issues(
            "\n".join(
                [
                    "\x1b[1;31mERROR:\x1b[0;91m Failed loading resource.",
                    "\x1b[1;33mWARNING:\x1b[0;93m Scan thread aborted...",
                ]
            )
        )

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0].severity, "error")
        self.assertEqual(issues[0].line, "ERROR: Failed loading resource.")
        self.assertEqual(issues[1].severity, "warning")

    def test_resource_validation_bounds_output_and_keeps_deterministic_context(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot(
            self._high_volume_output_shell(
                "FIRST RESOURCE VALIDATION CONTEXT",
                "LAST RESOURCE VALIDATION CONTEXT",
                central_line="ERROR: CENTRAL OUTPUT MUST BE SUMMARIZED",
            )
            + "exit 0\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            with patch(
                "src.conversion.godot_validation._GODOT_OUTPUT_READ_CHUNK_BYTES",
                17,
            ):
                first_report = validate_generated_godot_project(
                    str(project_dir),
                    godot_binary=str(fake_godot),
                )
            with patch(
                "src.conversion.godot_validation._GODOT_OUTPUT_READ_CHUNK_BYTES",
                4096,
            ):
                second_report = validate_generated_godot_project(
                    str(project_dir),
                    godot_binary=str(fake_godot),
                )

        self.assertEqual(first_report.status, "failed")
        self.assertEqual(first_report.returncode, 0)
        self.assertEqual(first_report.output, second_report.output)
        self.assertIn("FIRST RESOURCE VALIDATION CONTEXT", first_report.output)
        self.assertIn("LAST RESOURCE VALIDATION CONTEXT", first_report.output)
        self.assertIn("GM2Godot: Godot output truncated", first_report.output)
        self.assertNotIn("ERROR: CENTRAL OUTPUT MUST BE SUMMARIZED", first_report.output)
        self.assertIn("omitted 1 additional Godot error diagnostic", first_report.output)
        self.assertLess(len(first_report.output.encode("utf-8")), 512)
        self.assertEqual(len(first_report.output_issues), 1)

    def test_import_validation_bounds_output_and_preserves_exit_status(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self._write_fake_godot(
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            + self._high_volume_output_shell(
                "FIRST IMPORT CONTEXT",
                "WARNING: LAST IMPORT CONTEXT",
            )
            + "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'resource validation should not run'\n"
            "exit 31\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
            )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("FIRST IMPORT CONTEXT", report.import_output)
        self.assertIn("WARNING: LAST IMPORT CONTEXT", report.import_output)
        self.assertIn("GM2Godot: Godot output truncated", report.import_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.import_output)
        self.assertNotIn("resource validation should not run", report.output)
        self.assertLess(len(report.import_output.encode("utf-8")), 512)

    def test_boot_validation_bounds_combined_stdout_and_stderr(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot(
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            + self._high_volume_output_shell(
                "FIRST BOOT CONTEXT",
                "ERROR: LAST BOOT STDERR CONTEXT",
                last_to_stderr=True,
            )
            + "    exit 23\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
                boot_frames=2,
            )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 23)
        self.assertIn("FIRST BOOT CONTEXT", report.boot_output)
        self.assertIn("ERROR: LAST BOOT STDERR CONTEXT", report.boot_output)
        self.assertIn("GM2Godot: Godot output truncated", report.boot_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.boot_output)
        self.assertLess(len(report.boot_output.encode("utf-8")), 512)
        self.assertEqual(report.output_issues[-1].line, "ERROR: LAST BOOT STDERR CONTEXT")

    def test_import_timeout_returns_bounded_partial_output(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self._write_fake_godot(
            self._high_volume_output_shell(
                "FIRST TIMEOUT CONTEXT",
                "LAST TIMEOUT CONTEXT",
            )
            + "sleep 5\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
                timeout=1,
                load_resources=False,
            )

        self.assertEqual(report.status, "passed")
        self.assertIsNone(report.import_returncode)
        self.assertIn("ran for 1 seconds", report.message)
        self.assertIn("FIRST TIMEOUT CONTEXT", report.import_output)
        self.assertIn("LAST TIMEOUT CONTEXT", report.import_output)
        self.assertIn("GM2Godot: Godot output truncated", report.import_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.import_output)
        self.assertLess(len(report.import_output.encode("utf-8")), 512)

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

    def test_import_pass_uses_recovery_mode(self) -> None:
        project_dir = self._write_png_sprite_project()
        args_file = self.temp_dir / "import-args.txt"
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            f"    printf '%s\\n' \"$@\" > '{args_file}'\n"
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
        self.assertIn("--recovery-mode", args_file.read_text(encoding="utf-8").splitlines())

    def test_import_only_validation_skips_resource_load_script(self) -> None:
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
            "printf '%s\\n' 'resource loading should have been skipped'\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.returncode, 0)
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_IMPORT_OK", report.output)
        self.assertIn("skipped loading 3 generated scripts/scenes/resources", report.message)

    def test_import_only_validation_falls_back_without_audio_after_clean_nonzero_import(self) -> None:
        project_dir = self._write_png_sprite_project()
        (project_dir / "sounds").mkdir()
        (project_dir / "sounds" / "theme.mp3").write_bytes(b"fake mp3")
        fake_godot = self.temp_dir / "fake-godot"
        marker = self.temp_dir / "first-import-done"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            f"    if [ ! -f '{marker}' ]; then\n"
            f"      touch '{marker}'\n"
            "      printf '%s\\n' 'Godot exited without diagnostics during audio import.'\n"
            "      exit 11\n"
            "    fi\n"
            "    printf '%s\\n' 'GM2GODOT_NO_AUDIO_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'resource loading should have been skipped'\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_NO_AUDIO_IMPORT_OK", report.output)
        self.assertIn("no-audio import fallback completed", report.message)

    def test_import_only_timeout_passes_when_no_warning_or_error_output(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'Godot Engine v4.6.3.stable.official'\n"
            "sleep 5\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertIsNone(report.import_returncode)
        self.assertEqual(report.output_issues, ())
        self.assertIn("without warning/error output", report.message)

    def test_import_only_timeout_fails_when_warning_or_error_output_exists(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'SCRIPT ERROR: Parse Error: Identifier not declared.'\n"
            "sleep 5\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
            load_resources=False,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "error")

    def test_boot_validation_runs_main_scene_for_requested_frames(self) -> None:
        project_dir = self._write_project()
        args_file = self.temp_dir / "boot-args.txt"
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "is_boot=0\n"
            "is_script=0\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then is_boot=1; fi\n"
            "  if [ \"$arg\" = \"--script\" ]; then is_script=1; fi\n"
            "done\n"
            "if [ \"$is_boot\" = \"1\" ]; then\n"
            f"  printf '%s\\n' \"$@\" > '{args_file}'\n"
            "  printf '%s\\n' 'GM2GODOT_BOOT_OK'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$is_script\" = \"1\" ]; then\n"
            "  printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' 'unexpected Godot invocation'\n"
            "exit 8\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=4,
        )

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.boot_frames, 4)
        self.assertEqual(report.boot_returncode, 0)
        self.assertIn("GM2GODOT_VALIDATION_OK 2", report.output)
        self.assertIn("GM2GODOT_BOOT_OK", report.boot_output)
        boot_args = args_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("--headless", boot_args)
        self.assertIn("--fixed-fps", boot_args)
        self.assertIn("--path", boot_args)
        self.assertIn("--quit-after", boot_args)
        self.assertIn("4", boot_args)
        self.assertNotIn("--script", boot_args)

    def test_boot_validation_fails_on_runtime_warning_with_zero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            "    printf '%s\\n' 'WARNING: Runtime warning from main scene.'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=2,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 0)
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "warning")
        self.assertIn("boot reported 0 error(s) and 1 warning(s)", report.message)

    def test_boot_validation_fails_on_runtime_nonzero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            "    printf '%s\\n' 'Runtime exited without warning lines.'\n"
            "    exit 13\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=2,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 13)
        self.assertEqual(report.output_issues, ())
        self.assertIn("boot exited with code 13", report.message)

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
    def test_headless_godot_boots_main_scene_without_warnings(self) -> None:
        project_dir = self._write_project()

        report = validate_generated_godot_project(str(project_dir), boot_frames=2)

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.boot_frames, 2)
        self.assertEqual(report.boot_returncode, 0, report.boot_output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("main scene", report.message)

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
        self.assertEqual(report["boot_frames"], 0)
        self.assertEqual(report["output_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
