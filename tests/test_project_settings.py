import json
import os
import re
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.project_godot import prepare_godot_project_destination
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_settings import ProjectSettingsConverter

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
        converter.update_project_name()

        with open(self.project_godot, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('config/name="MyGame"', content)
        self.assertNotIn("Placeholder", content)

    def test_missing_project_godot_no_crash(self) -> None:
        os.remove(self.project_godot)
        converter = self._make_converter()
        converter.update_project_name()  # should not raise
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
            self._make_converter().update_project_name()

        with open(self.project_godot, "rb") as project_file:
            self.assertEqual(project_file.read(), original)
        self.assertTrue(any("injected replace failure" in log for log in self.logs))


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
        self.assertTrue(
            version_result.stdout.strip().startswith("4.7.1."),
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
        fallback_logs = [l for l in self.logs if 'windows' in l]
        self.assertTrue(len(fallback_logs) > 0, "Should log which platform was used as fallback")

    def test_uses_selected_platform_when_available(self) -> None:
        self._create_icon('linux')
        self._create_icon('windows')
        converter = self._make_converter(platform='linux')
        result = converter.convert_icon()

        self.assertTrue(result)
        fallback_logs = [l for l in self.logs if 'Fallback' in l or 'instead' in l]
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
        self.assertTrue(
            version_result.stdout.strip().startswith("4.7.1."),
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


if __name__ == "__main__":
    unittest.main()
