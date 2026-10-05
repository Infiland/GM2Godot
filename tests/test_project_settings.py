import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_godot import prepare_godot_project_destination
from src.conversion.project_settings import (
    ProjectOperationResult,
    ProjectSettingsConverter,
)

SAMPLE_YYP = """\
{
  "%Name": "TestProject",
  "resourceType": "GMProject",
  "AudioGroups": [
    {"%Name": "audiogroup_default", "resourceType": "GMAudioGroup"},
    {"%Name": "audiogroup_music", "resourceType": "GMAudioGroup"}
  ]
}
"""

SAMPLE_PROJECT_GODOT = """\
[gd_resource]

[application]
config/name="Placeholder"
config/icon="res://old_icon.png"
"""


class TestGetGmProjectName(unittest.TestCase):
    """Test ProjectSettingsConverter.get_gm_project_name()."""

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Write a fake .yyp file
        self.yyp_path = os.path.join(self.gm_dir, "TestProject.yyp")
        with open(self.yyp_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_YYP)

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_returns_project_name(self) -> None:
        converter = self._make_converter()
        name = converter.get_gm_project_name()
        self.assertEqual(name, "TestProject")

    def test_returns_none_when_no_yyp(self) -> None:
        os.remove(self.yyp_path)
        converter = self._make_converter()
        name = converter.get_gm_project_name()
        self.assertIsNone(name)


class TestConvertAllOutcomeAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        conversion_running: Callable[[], bool] | None = None,
    ) -> ProjectSettingsConverter:
        running = (
            conversion_running
            if conversion_running is not None
            else lambda: True
        )
        return ProjectSettingsConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=running,
        )

    def test_all_completed_operations_are_reported_once(self) -> None:
        converter = self._make_converter()
        completed = ProjectOperationResult("completed")

        with (
            patch.object(converter, "convert_icon", return_value=completed),
            patch.object(converter, "update_project_name", return_value=completed),
            patch.object(converter, "update_project_settings", return_value=completed),
            patch.object(
                converter,
                "generate_audio_bus_layout",
                return_value=completed,
            ),
        ):
            converter.convert_all()

        first = converter.conversion_step_result(finalize_unfinished_as=None)
        second = converter.conversion_step_result(finalize_unfinished_as=None)
        self.assertEqual(first, second)
        self.assertFalse(first.cancelled)
        self.assertEqual(
            first.resources,
            ConversionCounts(requested=4, executed=4, completed=4),
        )

    def test_repeated_convert_all_starts_a_fresh_outcome_run(self) -> None:
        converter = self._make_converter()
        completed = ProjectOperationResult("completed")

        with (
            patch.object(
                converter,
                "convert_icon",
                side_effect=(
                    completed,
                    ProjectOperationResult("skipped", "missing icon"),
                ),
            ) as convert_icon,
            patch.object(
                converter,
                "update_project_name",
                side_effect=(completed, completed),
            ) as update_project_name,
            patch.object(
                converter,
                "update_project_settings",
                side_effect=(
                    completed,
                    ProjectOperationResult("failed", "write failed"),
                ),
            ) as update_project_settings,
            patch.object(
                converter,
                "generate_audio_bus_layout",
                side_effect=(
                    completed,
                    ProjectOperationResult("skipped", "missing groups"),
                ),
            ) as generate_audio_bus_layout,
        ):
            converter.convert_all()
            first = converter.conversion_step_result(finalize_unfinished_as=None)
            converter.convert_all()
            second = converter.conversion_step_result(finalize_unfinished_as=None)

        self.assertEqual(
            first.resources,
            ConversionCounts(requested=4, executed=4, completed=4),
        )
        self.assertEqual(
            second.resources,
            ConversionCounts(
                requested=4,
                executed=4,
                completed=1,
                skipped=2,
                failed=1,
            ),
        )
        for operation in (
            convert_icon,
            update_project_name,
            update_project_settings,
            generate_audio_bus_layout,
        ):
            self.assertEqual(operation.call_count, 2)
            operation.assert_called_with()

    def test_mixed_operation_states_preserve_terminal_counts(self) -> None:
        converter = self._make_converter()

        with (
            patch.object(
                converter,
                "convert_icon",
                return_value=ProjectOperationResult("completed"),
            ),
            patch.object(
                converter,
                "update_project_name",
                return_value=ProjectOperationResult("skipped", "missing name"),
            ),
            patch.object(
                converter,
                "update_project_settings",
                return_value=ProjectOperationResult("failed", "write failed"),
            ),
            patch.object(
                converter,
                "generate_audio_bus_layout",
                return_value=ProjectOperationResult("completed"),
            ),
        ):
            converter.convert_all()

        result = converter.conversion_step_result(finalize_unfinished_as=None)
        self.assertFalse(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=4,
                executed=4,
                completed=2,
                skipped=1,
                failed=1,
            ),
        )

    def test_mid_run_cancellation_skips_unstarted_operations(self) -> None:
        running = {"value": True}
        converter = self._make_converter(lambda: running["value"])

        def cancel_during_name_update() -> ProjectOperationResult:
            running["value"] = False
            return ProjectOperationResult("skipped", "Conversion was cancelled.")

        with (
            patch.object(
                converter,
                "convert_icon",
                return_value=ProjectOperationResult("completed"),
            ) as convert_icon,
            patch.object(
                converter,
                "update_project_name",
                side_effect=cancel_during_name_update,
            ) as update_project_name,
            patch.object(converter, "update_project_settings") as update_settings,
            patch.object(converter, "generate_audio_bus_layout") as generate_buses,
        ):
            converter.convert_all()

        result = converter.conversion_step_result(finalize_unfinished_as=None)
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=4,
                executed=2,
                completed=1,
                skipped=3,
            ),
        )
        convert_icon.assert_called_once_with()
        update_project_name.assert_called_once_with()
        update_settings.assert_not_called()
        generate_buses.assert_not_called()


class TestUpdateProjectName(unittest.TestCase):
    """Test ProjectSettingsConverter.update_project_name()."""

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # .yyp in GM dir
        with open(os.path.join(self.gm_dir, "MyGame.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "MyGame" }')

        # project.godot in Godot dir
        self.project_godot = os.path.join(self.godot_dir, "project.godot")
        with open(self.project_godot, "w", encoding="utf-8") as f:
            f.write(SAMPLE_PROJECT_GODOT)

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_updates_name_in_project_godot(self) -> None:
        converter = self._make_converter()
        self.assertTrue(converter.update_project_name())

        with open(self.project_godot, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('config/name="MyGame"', content)
        self.assertNotIn("Placeholder", content)

    def test_missing_project_godot_no_crash(self) -> None:
        os.remove(self.project_godot)
        converter = self._make_converter()
        self.assertFalse(converter.update_project_name())
        self.assertTrue(len(self.logs) > 0)

    def test_updates_only_application_name_when_other_section_has_same_key(self) -> None:
        with open(self.project_godot, "w", encoding="utf-8") as project_file:
            project_file.write(
                "config_version=5\n\n"
                "[custom]\n"
                'config/name="Keep Custom"\n\n'
                "[application]\n"
                'config/name="Replace Application"\n'
            )

        self._make_converter().update_project_name()

        with open(self.project_godot, "r", encoding="utf-8") as project_file:
            content = project_file.read()
        self.assertIn('[custom]\nconfig/name="Keep Custom"', content)
        self.assertIn('[application]\nconfig/name="MyGame"', content)

    def test_inserts_application_name_when_setting_is_missing(self) -> None:
        with open(self.project_godot, "w", encoding="utf-8") as project_file:
            project_file.write(
                "config_version=5\n\n"
                "[application]\n"
                "run/max_fps=60\n"
            )

        self._make_converter().update_project_name()

        with open(self.project_godot, "r", encoding="utf-8") as project_file:
            content = project_file.read()
        self.assertIn('config/name="MyGame"', content)
        self.assertIn("run/max_fps=60", content)

    def test_atomic_name_update_failure_preserves_original_bytes(self) -> None:
        with open(self.project_godot, "rb") as project_file:
            original = project_file.read()

        with patch(
            "src.conversion.project_godot.os.replace",
            side_effect=OSError("injected replace failure"),
        ):
            self.assertFalse(self._make_converter().update_project_name())

        with open(self.project_godot, "rb") as project_file:
            self.assertEqual(project_file.read(), original)
        self.assertTrue(any("injected replace failure" in log for log in self.logs))

    def test_cancellation_after_name_lookup_does_not_mutate_project(self) -> None:
        running = MagicMock(side_effect=(True, False))
        converter = ProjectSettingsConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(message),
            conversion_running=running,
        )

        with patch(
            "src.conversion.project_settings.GodotProjectFile.set_setting"
        ) as set_setting:
            result = converter.update_project_name()

        self.assertEqual(result.state, "skipped")
        set_setting.assert_not_called()


class TestReadAudioGroups(unittest.TestCase):
    """Test ProjectSettingsConverter.read_audio_groups()."""

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        with open(os.path.join(self.gm_dir, "Game.yyp"), "w", encoding="utf-8") as f:
            f.write(SAMPLE_YYP)

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_reads_audio_groups(self) -> None:
        converter = self._make_converter()
        groups = converter.read_audio_groups()
        self.assertEqual(groups, ["audiogroup_default", "audiogroup_music"])

    def test_empty_audio_groups(self) -> None:
        # Overwrite with a .yyp that has no AudioGroups section
        with open(os.path.join(self.gm_dir, "Game.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Game" }')

        converter = self._make_converter()
        groups = converter.read_audio_groups()
        self.assertEqual(groups, [])


class TestGenerateAudioBusLayout(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.yyp_path = os.path.join(self.gm_dir, "Game.yyp")
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(message),
            conversion_running=lambda: True,
        )

    def test_missing_audio_groups_is_skipped_without_writing_fallback(self) -> None:
        with open(self.yyp_path, "w", encoding="utf-8") as project_file:
            json.dump({"%Name": "No Audio Metadata"}, project_file)

        result = self._make_converter().generate_audio_bus_layout()

        self.assertEqual(result.state, "skipped")
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "default_bus_layout.tres"))
        )

    def test_malformed_audio_groups_is_skipped_without_writing_fallback(self) -> None:
        with open(self.yyp_path, "w", encoding="utf-8") as project_file:
            json.dump(
                {"%Name": "Malformed Audio Metadata", "AudioGroups": "invalid"},
                project_file,
            )

        result = self._make_converter().generate_audio_bus_layout()

        self.assertEqual(result.state, "skipped")
        self.assertFalse(
            os.path.exists(os.path.join(self.godot_dir, "default_bus_layout.tres"))
        )

    def test_explicit_empty_audio_groups_generates_master_bus(self) -> None:
        with open(self.yyp_path, "w", encoding="utf-8") as project_file:
            json.dump({"%Name": "Empty Audio Metadata", "AudioGroups": []}, project_file)

        result = self._make_converter().generate_audio_bus_layout()

        self.assertEqual(result.state, "completed")
        with open(
            os.path.join(self.godot_dir, "default_bus_layout.tres"),
            "r",
            encoding="utf-8",
        ) as bus_file:
            content = bus_file.read()
        self.assertIn('bus/0/name = "Master"', content)

    def test_write_failure_is_structured_as_failed(self) -> None:
        with open(self.yyp_path, "w", encoding="utf-8") as project_file:
            json.dump({"%Name": "Audio", "AudioGroups": []}, project_file)
        converter = self._make_converter()

        with patch(
            "src.conversion.project_settings.open",
            create=True,
            side_effect=OSError("disk full"),
        ):
            result = converter.generate_audio_bus_layout()

        self.assertEqual(result.state, "failed")
        self.assertIn("disk full", result.reason)


class TestUpdateProjectSettingsFromManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        with open(os.path.join(self.gm_dir, "Game.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Manifest Settings", "resourceType": "GMProject" }')
        os.makedirs(os.path.join(self.gm_dir, "options", "main"), exist_ok=True)
        os.makedirs(os.path.join(self.gm_dir, "options", "windows"), exist_ok=True)
        with open(os.path.join(self.gm_dir, "options", "main", "options_main.yy"), "w", encoding="utf-8") as f:
            f.write('{"option_game_speed":144,}')
        with open(os.path.join(self.gm_dir, "options", "windows", "options_windows.yy"), "w", encoding="utf-8") as f:
            f.write(
                "{"
                '"option_windows_description_info":"true",'
                '"option_windows_version":"123",'
                '"option_windows_use_splash":false,'
                '"option_windows_vsync":false,'
                '"option_windows_resize_window":true,'
                '"option_windows_borderless":false,'
                '"option_windows_interpolate_pixels":true,'
                '"option_windows_start_fullscreen":true,'
                '"option_windows_custom_future":true,'
                "}"
            )
        self.project_godot = os.path.join(self.godot_dir, "project.godot")
        with open(self.project_godot, "w", encoding="utf-8") as f:
            f.write(
                "; Engine configuration file.\n"
                "config_version=5\n\n"
                "[application]\n"
                'config/name="Placeholder"\n'
                'custom/keep="untouched"\n'
                "window/vsync/vsync_mode=2\n"
                "window/size/mode=2\n"
                "textures/canvas_textures/default_texture_filter=2\n\n"
                "[display]\n"
                "window/size/viewport_width=1600\n"
                "window/size/mode=1\n\n"
                "[rendering]\n"
                'renderer/rendering_method="gl_compatibility"\n'
            )

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            gm_platform="windows",
        )

    def test_updates_project_godot_from_typed_options_and_reports_gaps(self) -> None:
        converter = self._make_converter()
        converter.update_project_settings()

        with open(self.project_godot, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('config/description="true"', content)
        self.assertIn('config/version="123"', content)
        self.assertIn("boot_splash/show_image=false", content)
        self.assertIn("run/max_fps=144", content)
        self.assertIn("window/vsync/vsync_mode=0", content)
        self.assertIn("window/size/resizable=true", content)
        self.assertIn("window/size/borderless=false", content)
        self.assertIn("textures/canvas_textures/default_texture_filter=1", content)
        self.assertIn("window/size/mode=3", content)
        unsupported_logs = [
            log for log in self.logs if "option_windows_custom_future" in log
        ]
        self.assertTrue(unsupported_logs)
        self.assertTrue(all(log.startswith("Info:") for log in unsupported_logs))

    def test_places_settings_in_canonical_sections_and_preserves_existing_settings(self) -> None:
        converter = self._make_converter()
        converter.update_project_settings()

        with open(self.project_godot, "r", encoding="utf-8") as f:
            content = f.read()

        application = self._section_body(content, "application")
        display = self._section_body(content, "display")
        rendering = self._section_body(content, "rendering")

        self.assertIn('custom/keep="untouched"', application)
        self.assertIn('config/description="true"', application)
        self.assertIn('config/version="123"', application)
        self.assertIn("run/max_fps=144", application)
        self.assertNotIn("window/", application)
        self.assertNotIn("textures/canvas_textures/default_texture_filter", application)

        self.assertIn("window/size/viewport_width=1600", display)
        self.assertIn("window/vsync/vsync_mode=0", display)
        self.assertIn("window/size/resizable=true", display)
        self.assertIn("window/size/borderless=false", display)
        self.assertIn("window/size/mode=3", display)
        self.assertNotIn("window/size/mode=1", display)

        self.assertIn('renderer/rendering_method="gl_compatibility"', rendering)
        self.assertIn("textures/canvas_textures/default_texture_filter=1", rendering)

    def test_missing_options_is_skipped_without_rewriting_project(self) -> None:
        shutil.rmtree(os.path.join(self.gm_dir, "options"))
        with open(self.project_godot, "rb") as project_file:
            original = project_file.read()

        result = self._make_converter().update_project_settings()

        self.assertEqual(result.state, "skipped")
        with open(self.project_godot, "rb") as project_file:
            self.assertEqual(project_file.read(), original)

    def test_malformed_options_is_skipped_without_rewriting_project(self) -> None:
        with open(
            os.path.join(self.gm_dir, "options", "windows", "options_windows.yy"),
            "w",
            encoding="utf-8",
        ) as options_file:
            options_file.write("{not json")
        with open(self.project_godot, "rb") as project_file:
            original = project_file.read()

        result = self._make_converter().update_project_settings()

        self.assertEqual(result.state, "skipped")
        with open(self.project_godot, "rb") as project_file:
            self.assertEqual(project_file.read(), original)

    def test_options_read_failure_is_structured_as_failed(self) -> None:
        converter = self._make_converter()

        with patch(
            "src.conversion.project_settings.os.listdir",
            side_effect=OSError("permission denied"),
        ):
            result = converter.update_project_settings()

        self.assertEqual(result.state, "failed")
        self.assertIn("permission denied", result.reason)

    def test_options_symlink_outside_project_is_skipped_without_reading(self) -> None:
        main_options = os.path.join(
            self.gm_dir,
            "options",
            "main",
            "options_main.yy",
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_options = os.path.join(outside_dir, "outside.yy")
            with open(outside_options, "w", encoding="utf-8") as options_file:
                options_file.write('{"option_game_speed":999}')
            os.unlink(main_options)
            try:
                os.symlink(outside_options, main_options)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            with open(self.project_godot, "rb") as project_file:
                original = project_file.read()

            result = self._make_converter().update_project_settings()

        self.assertEqual(result.state, "skipped")
        with open(self.project_godot, "rb") as project_file:
            self.assertEqual(project_file.read(), original)
        self.assertTrue(any("Rejected GameMaker source path" in log for log in self.logs))

    def test_valid_empty_options_is_a_completed_no_op(self) -> None:
        for platform in ("main", "windows"):
            with open(
                os.path.join(
                    self.gm_dir,
                    "options",
                    platform,
                    f"options_{platform}.yy",
                ),
                "w",
                encoding="utf-8",
            ) as options_file:
                options_file.write("{}")
        converter = self._make_converter()

        with patch("src.conversion.project_settings.atomic_rewrite_text") as rewrite:
            result = converter.update_project_settings()

        self.assertEqual(result.state, "completed")
        rewrite.assert_not_called()

    @unittest.skipUnless(os.environ.get("GODOT_BIN"), "GODOT_BIN is not set")
    def test_godot_reads_generated_settings_at_canonical_project_settings_paths(self) -> None:
        converter = self._make_converter()
        converter.update_project_settings()

        probe_path = os.path.join(self.godot_dir, "project_settings_probe.gd")
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write(
                "extends SceneTree\n\n"
                "func _init():\n"
                "\tvar settings = {\n"
                '\t\t"description": ProjectSettings.get_setting('
                '"application/config/description"),\n'
                '\t\t"description_type": type_string(typeof(ProjectSettings.get_setting('
                '"application/config/description"))),\n'
                '\t\t"max_fps": ProjectSettings.get_setting("application/run/max_fps"),\n'
                '\t\t"vsync": ProjectSettings.get_setting("display/window/vsync/vsync_mode"),\n'
                '\t\t"resizable": ProjectSettings.get_setting("display/window/size/resizable"),\n'
                '\t\t"borderless": ProjectSettings.get_setting("display/window/size/borderless"),\n'
                '\t\t"mode": ProjectSettings.get_setting("display/window/size/mode"),\n'
                '\t\t"texture_filter": ProjectSettings.get_setting('
                '"rendering/textures/canvas_textures/default_texture_filter"),\n'
                '\t\t"version": ProjectSettings.get_setting("application/config/version"),\n'
                '\t\t"version_type": type_string(typeof(ProjectSettings.get_setting('
                '"application/config/version"))),\n'
                '\t\t"legacy_mode": ProjectSettings.has_setting("application/window/size/mode"),\n'
                '\t\t"legacy_texture_filter": ProjectSettings.has_setting('
                '"application/textures/canvas_textures/default_texture_filter"),\n'
                "\t}\n"
                '\tprint("GM2GODOT_PROJECT_SETTINGS=" + JSON.stringify(settings))\n'
                "\tquit()\n"
            )

        godot_bin = os.environ["GODOT_BIN"]
        version_result = subprocess.run(
            [godot_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        self.assertEqual(
            version_result.stdout.strip(),
            "4.7.2.stable.official.ed1daf0bf",
            version_result.stdout + version_result.stderr,
        )
        result = subprocess.run(
            [
                godot_bin,
                "--headless",
                "--path",
                self.godot_dir,
                "--script",
                "res://project_settings_probe.gd",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)

        marker = "GM2GODOT_PROJECT_SETTINGS="
        payload_line = next(
            (line for line in output.splitlines() if line.startswith(marker)),
            None,
        )
        self.assertIsNotNone(payload_line, output)
        assert payload_line is not None
        settings = json.loads(payload_line.removeprefix(marker))
        self.assertEqual(
            settings,
            {
                "borderless": False,
                "description": "true",
                "description_type": "String",
                "legacy_mode": False,
                "legacy_texture_filter": False,
                "max_fps": 144,
                "mode": 3,
                "resizable": True,
                "texture_filter": 1,
                "version": "123",
                "version_type": "String",
                "vsync": 0,
            },
        )

    def _section_body(self, content: str, section: str) -> str:
        match = re.search(
            rf"(?ms)^\[{re.escape(section)}\][ \t]*\r?\n(.*?)(?=^\[|\Z)",
            content,
        )
        self.assertIsNotNone(match, content)
        assert match is not None
        return match.group(1)


class TestConvertIconFallback(unittest.TestCase):
    """Test that convert_icon falls back to other platforms when the selected platform has no icons."""

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        platform: str = 'linux',
        diagnostics: DiagnosticCollector | None = None,
    ) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            gm_platform=platform,
            diagnostics=diagnostics,
        )

    def _create_icon(self, platform: str) -> None:
        """Create a minimal .ico file under options/<platform>/icons/."""
        from PIL import Image
        icons_dir = os.path.join(self.gm_dir, 'options', platform, 'icons')
        os.makedirs(icons_dir, exist_ok=True)
        img = Image.new("RGBA", (16, 16), "blue")
        img.save(os.path.join(icons_dir, "icon.ico"), "PNG")

    def _create_yyp(self) -> None:
        with open(
            os.path.join(self.gm_dir, "IconGame.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump({"%Name": "Icon Game"}, project_file)

    def test_uses_fallback_platform_when_selected_missing(self) -> None:
        self._create_icon('windows')
        converter = self._make_converter(platform='linux')
        result = converter.convert_icon()

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.godot_dir, 'icon.png')))
        fallback_logs = [log for log in self.logs if 'windows' in log]
        self.assertTrue(len(fallback_logs) > 0, "Should log which platform was used as fallback")

    def test_uses_selected_platform_when_available(self) -> None:
        self._create_icon('linux')
        self._create_icon('windows')
        converter = self._make_converter(platform='linux')
        result = converter.convert_icon()

        self.assertTrue(result)
        fallback_logs = [log for log in self.logs if 'Fallback' in log or 'instead' in log]
        self.assertEqual(len(fallback_logs), 0, "Should not fall back when selected platform has icons")

    def test_returns_false_when_no_platform_has_icons(self) -> None:
        converter = self._make_converter(platform='linux')
        result = converter.convert_icon()

        self.assertFalse(result)

    def test_rejects_selected_icon_file_link_outside_project(self) -> None:
        from PIL import Image

        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_icon = os.path.join(outside_dir, "outside.png")
            Image.new("RGBA", (16, 16), "red").save(outside_icon, "PNG")
            icons_dir = os.path.join(self.gm_dir, "options", "linux", "icons")
            os.makedirs(icons_dir)
            try:
                os.symlink(outside_icon, os.path.join(icons_dir, "icon.png"))
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            result = self._make_converter(
                platform="linux",
                diagnostics=diagnostics,
            ).convert_icon()

        self.assertFalse(result)
        self.assertFalse(os.path.exists(os.path.join(self.godot_dir, "icon.png")))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "options/linux/icons")
        self.assertEqual(rejected[0].manifest_entry, "icon file")

    def test_rejects_fallback_icon_directory_link_outside_project(self) -> None:
        from PIL import Image

        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            Image.new("RGBA", (16, 16), "red").save(
                os.path.join(outside_dir, "icon.png"),
                "PNG",
            )
            platform_dir = os.path.join(self.gm_dir, "options", "windows")
            os.makedirs(platform_dir)
            try:
                os.symlink(
                    outside_dir,
                    os.path.join(platform_dir, "icons"),
                    target_is_directory=True,
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            result = self._make_converter(
                platform="linux",
                diagnostics=diagnostics,
            ).convert_icon()

        self.assertFalse(result)
        self.assertFalse(os.path.exists(os.path.join(self.godot_dir, "icon.png")))
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "options/windows")
        self.assertEqual(rejected[0].manifest_entry, "icons directory")

    def test_converted_icon_is_wired_into_fresh_minimal_project(self) -> None:
        self._create_yyp()
        self._create_icon("windows")
        prepare_godot_project_destination(self.gm_dir, self.godot_dir)

        result = self._make_converter(platform="windows").convert_icon()

        self.assertTrue(result)
        with open(
            os.path.join(self.godot_dir, "project.godot"),
            "r",
            encoding="utf-8",
        ) as project_file:
            content = project_file.read()
        self.assertEqual(content.count('config/icon="res://icon.png"'), 1)
        application = re.search(
            r"(?ms)^\[application\][ \t]*\r?\n(.*?)(?=^\[|\Z)",
            content,
        )
        self.assertIsNotNone(application, content)
        assert application is not None
        self.assertIn('config/icon="res://icon.png"', application.group(1))

    @unittest.skipUnless(os.environ.get("GODOT_BIN"), "GODOT_BIN is not set")
    def test_exact_godot_reads_icon_from_fresh_cli_conversion(self) -> None:
        self._create_yyp()
        self._create_icon("windows")

        conversion = subprocess.run(
            [
                sys.executable,
                "main.py",
                "convert",
                "--gm-project",
                self.gm_dir,
                "--godot-project",
                self.godot_dir,
                "--platform",
                "windows",
                "--only",
                "game_icon",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            conversion.returncode,
            0,
            conversion.stdout + conversion.stderr,
        )

        probe_path = os.path.join(self.godot_dir, "icon_settings_probe.gd")
        with open(probe_path, "w", encoding="utf-8") as probe_file:
            probe_file.write(
                "extends SceneTree\n\n"
                "func _init():\n"
                "\tvar settings = {\n"
                '\t\t"icon": ProjectSettings.get_setting("application/config/icon"),\n'
                '\t\t"icon_exists": FileAccess.file_exists("res://icon.png"),\n'
                "\t}\n"
                '\tprint("GM2GODOT_ICON_SETTINGS=" + JSON.stringify(settings))\n'
                "\tquit()\n"
            )

        godot_bin = os.environ["GODOT_BIN"]
        version_result = subprocess.run(
            [godot_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        self.assertEqual(
            version_result.stdout.strip(),
            "4.7.2.stable.official.ed1daf0bf",
            version_result.stdout + version_result.stderr,
        )
        result = subprocess.run(
            [
                godot_bin,
                "--headless",
                "--path",
                self.godot_dir,
                "--script",
                "res://icon_settings_probe.gd",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        marker = "GM2GODOT_ICON_SETTINGS="
        payload_line = next(
            (line for line in output.splitlines() if line.startswith(marker)),
            None,
        )
        self.assertIsNotNone(payload_line, output)
        assert payload_line is not None
        self.assertEqual(
            json.loads(payload_line.removeprefix(marker)),
            {"icon": "res://icon.png", "icon_exists": True},
        )


class TestFreshOptionsJsonBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.gm_dir)
        self.addCleanup(shutil.rmtree, self.godot_dir)
        self.logs: list[str] = []
        self.yyp_path = Path(self.gm_dir) / "Game.yyp"
        self.yyp_path.write_text(SAMPLE_YYP, encoding="utf-8")
        self.main_options = Path(self.gm_dir) / "options" / "main" / "options_main.yy"
        self.windows_options = Path(self.gm_dir) / "options" / "windows" / "options_windows.yy"
        self.main_options.parent.mkdir(parents=True)
        self.windows_options.parent.mkdir(parents=True)
        self.main_options.write_text('{"option_game_speed":144,}', encoding="utf-8")
        self.windows_options.write_text(
            '{"option_windows_description_info":"cached description",'
            '"option_windows_version":"123","option_windows_vsync":false,}',
            encoding="utf-8",
        )
        self.project_path = Path(self.godot_dir) / "project.godot"
        self.project_path.write_text(
            'config_version=5\n\n[application]\nconfig/name="Existing"\n'
            'custom/keep="unchanged"\n\n[display]\nwindow/size/viewport_width=1600\n',
            encoding="utf-8",
        )
        self.bus_path = Path(self.godot_dir) / "default_bus_layout.tres"
        self.bus_path.write_bytes(b"existing audio bus bytes\n")
        self.converter = ProjectSettingsConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            conversion_running=lambda: True,
            gm_platform="windows",
        )

    def _output_bytes(self) -> tuple[bytes, bytes]:
        return self.project_path.read_bytes(), self.bus_path.read_bytes()

    def _assert_cached_settings(self) -> None:
        content = self.project_path.read_text(encoding="utf-8")
        self.assertIn('config/description="cached description"', content)
        self.assertIn('config/version="123"', content)
        self.assertIn("run/max_fps=144", content)
        self.assertIn("window/vsync/vsync_mode=0", content)
        self.assertIn('custom/keep="unchanged"', content)
        self.assertIn("window/size/viewport_width=1600", content)

    def test_valid_fresh_replacements_render_cached_settings_and_audio_groups(self) -> None:
        manifest = self.converter.project_manifest
        self.main_options.write_text(
            '{"option_game_speed":999,"unknown":{"nested":[null,true,{},[]]},}',
            encoding="utf-8",
        )
        self.windows_options.write_text(
            '{"option_windows_description_info":"fresh description",'
            '"option_windows_version":"999","option_windows_vsync":true}',
            encoding="utf-8",
        )
        self.yyp_path.write_text(
            '{"%Name":"Fresh Project","AudioGroups":[{"%Name":"fresh_audio"}]}',
            encoding="utf-8",
        )

        settings = self.converter.update_project_settings()
        buses = self.converter.generate_audio_bus_layout()

        self.assertEqual(settings.state, "completed")
        self.assertEqual(buses.state, "completed")
        self.assertIs(self.converter.project_manifest, manifest)
        self._assert_cached_settings()
        self.assertNotIn("fresh description", self.project_path.read_text(encoding="utf-8"))
        self.assertNotIn("999", self.project_path.read_text(encoding="utf-8"))
        bus_text = self.bus_path.read_text(encoding="utf-8")
        self.assertIn('bus/0/name = "Master"', bus_text)
        self.assertIn('bus/1/name = "audiogroup_music"', bus_text)
        self.assertNotIn("fresh_audio", bus_text)

    def test_fresh_empty_objects_are_valid_and_keep_cached_options(self) -> None:
        self.main_options.write_text("{}", encoding="utf-8")
        self.windows_options.write_text("{}", encoding="utf-8")

        result = self.converter.update_project_settings()

        self.assertEqual(result.state, "completed")
        self._assert_cached_settings()
        self.assertEqual(self.bus_path.read_bytes(), b"existing audio bus bytes\n")

    def test_nonobject_fresh_roots_skip_without_rewriting_outputs(self) -> None:
        before = self._output_bytes()
        for source in ("null", "true", "17", '"fresh"', "[]", '[1,{"extra":true}]'):
            with self.subTest(source=source):
                self.main_options.write_text(source, encoding="utf-8")
                result = self.converter.update_project_settings()
                self.assertEqual(result.state, "skipped")
                self.assertEqual(
                    result.reason,
                    f"GameMaker options metadata is malformed: {self.main_options}",
                )
                self.assertEqual(self._output_bytes(), before)

    def test_malformed_and_bom_fresh_text_skip_without_rewriting_outputs(self) -> None:
        before = self._output_bytes()
        for source in ('{"broken":', '\ufeff{"option_game_speed":999}'):
            with self.subTest(source=source):
                self.main_options.write_text(source, encoding="utf-8")
                result = self.converter.update_project_settings()
                self.assertEqual(result.state, "skipped")
                self.assertEqual(
                    result.reason,
                    f"GameMaker options metadata is malformed: {self.main_options}",
                )
                self.assertEqual(self._output_bytes(), before)

    def test_fresh_decoder_exhaustively_rejects_invalid_nested_values(self) -> None:
        before = self._output_bytes()
        invalid: dict[str, object] = {"extra": [{"unsupported": b"bytes"}]}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=invalid):
            result = self.converter.update_project_settings()

        self.assertEqual(result.state, "skipped")
        self.assertEqual(
            result.reason,
            f"GameMaker options metadata is malformed: {self.windows_options}",
        )
        self.assertEqual(self._output_bytes(), before)

    def test_invalid_utf8_fresh_read_propagates_without_rewriting_outputs(self) -> None:
        before = self._output_bytes()
        self.main_options.write_bytes(b"\xff")

        with self.assertRaises(UnicodeDecodeError) as raised:
            self.converter.update_project_settings()

        self.assertEqual(raised.exception.object, b"\xff")
        self.assertEqual(raised.exception.start, 0)
        self.assertEqual(self._output_bytes(), before)

    def test_fresh_read_oserror_is_failed_without_rewriting_outputs(self) -> None:
        before = self._output_bytes()
        error = PermissionError("options read denied")
        with patch("src.conversion.project_settings.open", side_effect=error, create=True):
            result = self.converter.update_project_settings()

        self.assertEqual(result.state, "failed")
        self.assertEqual(result.reason, str(error))
        self.assertEqual(self._output_bytes(), before)

    def test_fresh_read_non_os_errors_keep_their_identity(self) -> None:
        before = self._output_bytes()
        errors = (
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
            ValueError("read value error"),
            RecursionError("read recursion error"),
            KeyboardInterrupt(),
            SystemExit(17),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.project_settings.open", side_effect=error, create=True):
                    with self.assertRaises(type(error)) as raised:
                        self.converter.update_project_settings()
                self.assertIs(raised.exception, error)
                self.assertEqual(self._output_bytes(), before)

    def test_fresh_decode_errors_remain_skipped(self) -> None:
        before = self._output_bytes()
        errors = (
            json.JSONDecodeError("bad JSON", "{", 1),
            TypeError("decode type error"),
            ValueError("decode value error"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.project_settings.decode_gamemaker_json", side_effect=error):
                    result = self.converter.update_project_settings()
                self.assertEqual(result.state, "skipped")
                self.assertEqual(
                    result.reason,
                    f"GameMaker options metadata is malformed: {self.windows_options}",
                )
                self.assertEqual(self._output_bytes(), before)

    def test_fresh_decode_recursion_and_controls_keep_their_identity(self) -> None:
        before = self._output_bytes()
        for error in (RecursionError("decode depth"), KeyboardInterrupt(), SystemExit(23)):
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.project_settings.decode_gamemaker_json", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        self.converter.update_project_settings()
                self.assertIs(raised.exception, error)
                self.assertEqual(self._output_bytes(), before)

    def test_uppercase_fresh_options_suffix_is_validated_without_refreshing_manifest(self) -> None:
        uppercase = self.main_options.with_suffix(".YY")
        self.main_options.rename(uppercase)
        uppercase.write_text('{"option_game_speed":999}', encoding="utf-8")

        result = self.converter.update_project_settings()

        self.assertEqual(result.state, "completed")
        self._assert_cached_settings()

    def test_contained_fresh_options_symlink_keeps_cached_settings(self) -> None:
        target = Path(self.gm_dir) / "fresh_options.txt"
        target.write_text('{"option_game_speed":999}', encoding="utf-8")
        self.main_options.unlink()
        try:
            self.main_options.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        result = self.converter.update_project_settings()

        self.assertEqual(result.state, "completed")
        self._assert_cached_settings()

    def test_rejected_fresh_options_symlink_is_not_decoded(self) -> None:
        before = self._output_bytes()
        with tempfile.TemporaryDirectory() as outside_dir:
            target = Path(outside_dir) / "outside.yy"
            target.write_bytes(b"\xff")
            self.main_options.unlink()
            try:
                self.main_options.symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            with patch("src.conversion.project_settings.decode_gamemaker_json") as decode:
                result = self.converter.update_project_settings()
            decode.assert_not_called()

        self.assertEqual(result.state, "skipped")
        self.assertEqual(result.reason, "GameMaker options metadata contains a rejected source path.")
        self.assertEqual(self._output_bytes(), before)
        self.assertTrue(any("Rejected GameMaker source path" in log for log in self.logs))


class TestMissingProjectFileDiagnosticParity(unittest.TestCase):
    ENGLISH_MESSAGE = "Error: No project.godot file found in the Godot project folder."
    GERMAN_MESSAGE = "Fehler: Keine project.godot-Datei im Godot-Projektordner gefunden."

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.gm_dir = self.root / "gamemaker"
        self.godot_dir = self.root / "godot"
        self.gm_dir.mkdir()
        self.godot_dir.mkdir()
        (self.gm_dir / "Game.yyp").write_text(SAMPLE_YYP, encoding="utf-8")
        for platform in ("main", "windows"):
            options = self.gm_dir / "options" / platform / f"options_{platform}.yy"
            options.parent.mkdir(parents=True)
            options.write_text("{}", encoding="utf-8")

    def _make_converter(
        self,
        callback: Callable[[str], None],
        collector: DiagnosticCollector | None,
    ) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            str(self.gm_dir),
            str(self.godot_dir),
            log_callback=callback,
            conversion_running=lambda: True,
            diagnostics=collector,
        )

    def _assert_missing_result(self, result: ProjectOperationResult) -> None:
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.reason, "project.godot is missing.")
        self.assertFalse(result)
        self.assertEqual(list(self.godot_dir.iterdir()), [])

    def _exercise_repeated_operations(
        self,
        collector: DiagnosticCollector,
        message: str,
        *,
        wrapped: bool,
    ) -> list[str]:
        logs: list[str] = []
        callback = collector.wrap_log_callback(logs.append) if wrapped else logs.append
        converter = self._make_converter(callback, collector)
        with patch("src.conversion.project_settings.get_localized", return_value=message) as localized:
            for _repeat in range(2):
                self._assert_missing_result(converter.update_project_name())
                self._assert_missing_result(converter.update_project_settings())
        self.assertEqual(localized.call_count, 4)
        self.assertTrue(all(call.args == ("Console_Error_MissingGodotFile",) for call in localized.call_args_list))
        self.assertEqual(logs, [message] * 4)
        return logs

    def _report_bytes(self, collector: DiagnosticCollector) -> tuple[bytes, bytes]:
        report_root = tempfile.mkdtemp(dir=self.root)
        json_path, markdown_path = collector.write_reports(report_root)
        return Path(json_path).read_bytes(), Path(markdown_path).read_bytes()

    def test_both_public_methods_record_english_error_before_raw_callback(self) -> None:
        collector = DiagnosticCollector()
        logs: list[str] = []
        observed_error_counts: list[int] = []

        def callback(message: str) -> None:
            observed_error_counts.append(collector.summary()["error"])
            logs.append(message)

        converter = self._make_converter(callback, collector)
        with patch("src.conversion.project_settings.get_localized", return_value=self.ENGLISH_MESSAGE):
            self._assert_missing_result(converter.update_project_name())
            self._assert_missing_result(converter.update_project_settings())

        self.assertEqual(observed_error_counts, [1, 1])
        self.assertEqual(logs, [self.ENGLISH_MESSAGE, self.ENGLISH_MESSAGE])
        self.assertEqual(collector.summary(), {"info": 0, "warning": 0, "error": 1, "total": 1})
        self.assertEqual(
            collector.diagnostics()[0].to_dict(),
            {
                "severity": "error",
                "code": "GM2GD-WARNING",
                "message": self.ENGLISH_MESSAGE,
                "source_path": None,
                "line": None,
                "column": None,
                "resource": None,
                "resource_type": None,
                "event": None,
                "api": None,
                "manifest_entry": None,
                "issue_number": None,
                "workaround": None,
            },
        )

    def test_repeated_direct_and_wrapped_reports_match_with_contextual_preseed(self) -> None:
        for preseeded in (False, True):
            with self.subTest(preseeded=preseeded):
                direct = DiagnosticCollector()
                wrapped = DiagnosticCollector()
                for collector in (direct, wrapped):
                    if preseeded:
                        collector.add(
                            "warning",
                            "GM2GD-EXISTING-CONTEXT",
                            self.ENGLISH_MESSAGE,
                            source_path="options/main/options_main.yy",
                            resource="preexisting",
                            resource_type="project_options",
                        )
                direct_before = direct.diagnostics()
                wrapped_before = wrapped.diagnostics()
                direct_logs = self._exercise_repeated_operations(direct, self.ENGLISH_MESSAGE, wrapped=False)
                wrapped_logs = self._exercise_repeated_operations(wrapped, self.ENGLISH_MESSAGE, wrapped=True)
                self.assertEqual(direct_logs, wrapped_logs)
                self.assertEqual(direct.diagnostics(), wrapped.diagnostics())
                self.assertEqual(len(direct.diagnostics()), 1)
                self.assertEqual(self._report_bytes(direct), self._report_bytes(wrapped))
                if preseeded:
                    self.assertEqual(direct.diagnostics(), direct_before)
                    self.assertEqual(wrapped.diagnostics(), wrapped_before)
                    self.assertIs(direct.diagnostics()[0], direct_before[0])
                    self.assertIs(wrapped.diagnostics()[0], wrapped_before[0])
                    self.assertEqual(direct.summary()["error"], 0)
                else:
                    self.assertEqual(direct.summary()["error"], 1)

    def test_german_message_preserves_wrapped_unrecognized_classification(self) -> None:
        direct = DiagnosticCollector()
        wrapped = DiagnosticCollector()
        direct_logs = self._exercise_repeated_operations(direct, self.GERMAN_MESSAGE, wrapped=False)
        wrapped_logs = self._exercise_repeated_operations(wrapped, self.GERMAN_MESSAGE, wrapped=True)
        self.assertEqual(direct_logs, wrapped_logs)
        self.assertEqual(direct.diagnostics(), ())
        self.assertEqual(wrapped.diagnostics(), ())
        self.assertEqual(direct.summary(), {"info": 0, "warning": 0, "error": 0, "total": 0})
        self.assertEqual(self._report_bytes(direct), self._report_bytes(wrapped))

    def test_callback_error_identity_escapes_before_failed_return_with_or_without_collector(self) -> None:
        for use_collector in (False, True):
            for update_settings in (False, True):
                with self.subTest(collector=use_collector, settings=update_settings):
                    collector = DiagnosticCollector() if use_collector else None
                    sentinel = RuntimeError("raw project-file callback sentinel")
                    observed_error_counts: list[int] = []
                    logs: list[str] = []

                    def callback(message: str) -> None:
                        observed_error_counts.append(collector.summary()["error"] if collector is not None else 0)
                        logs.append(message)
                        raise sentinel

                    converter = self._make_converter(callback, collector)
                    operation = converter.update_project_settings if update_settings else converter.update_project_name
                    with patch("src.conversion.project_settings.get_localized", return_value=self.ENGLISH_MESSAGE):
                        with self.assertRaises(RuntimeError) as raised:
                            operation()
                    self.assertIs(raised.exception, sentinel)
                    self.assertEqual(logs, [self.ENGLISH_MESSAGE])
                    self.assertEqual(observed_error_counts, [1 if use_collector else 0])
                    self.assertEqual(list(self.godot_dir.iterdir()), [])
                    if collector is not None:
                        self.assertEqual(collector.summary()["error"], 1)


if __name__ == "__main__":
    unittest.main()
