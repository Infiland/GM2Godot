import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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
                '"option_windows_description_info":"Arcade run",'
                '"option_windows_version":"1.2.3",'
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
            f.write(SAMPLE_PROJECT_GODOT)

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

        self.assertIn('config/description="Arcade run"', content)
        self.assertIn('config/version="1.2.3"', content)
        self.assertIn("boot_splash/show_image=false", content)
        self.assertIn("run/max_fps=144", content)
        self.assertIn("window/vsync/vsync_mode=0", content)
        self.assertIn("window/size/resizable=true", content)
        self.assertIn("window/size/borderless=false", content)
        self.assertIn("textures/canvas_textures/default_texture_filter=1", content)
        self.assertIn("window/size/mode=3", content)
        self.assertTrue(any("option_windows_custom_future" in log for log in self.logs))


class TestConvertIconFallback(unittest.TestCase):
    """Test that convert_icon falls back to other platforms when the selected platform has no icons."""

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, platform: str = 'linux') -> ProjectSettingsConverter:
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            gm_platform=platform,
        )

    def _create_icon(self, platform: str) -> None:
        """Create a minimal .ico file under options/<platform>/icons/."""
        from PIL import Image
        icons_dir = os.path.join(self.gm_dir, 'options', platform, 'icons')
        os.makedirs(icons_dir, exist_ok=True)
        img = Image.new("RGBA", (16, 16), "blue")
        img.save(os.path.join(icons_dir, "icon.ico"), "PNG")

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


if __name__ == "__main__":
    unittest.main()
