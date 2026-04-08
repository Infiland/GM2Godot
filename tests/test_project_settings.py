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

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        # Write a fake .yyp file
        self.yyp_path = os.path.join(self.gm_dir, "TestProject.yyp")
        with open(self.yyp_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_YYP)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_returns_project_name(self):
        converter = self._make_converter()
        name = converter.get_gm_project_name()
        self.assertEqual(name, "TestProject")

    def test_returns_none_when_no_yyp(self):
        os.remove(self.yyp_path)
        converter = self._make_converter()
        name = converter.get_gm_project_name()
        self.assertIsNone(name)


class TestUpdateProjectName(unittest.TestCase):
    """Test ProjectSettingsConverter.update_project_name()."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        # .yyp in GM dir
        with open(os.path.join(self.gm_dir, "MyGame.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "MyGame" }')

        # project.godot in Godot dir
        self.project_godot = os.path.join(self.godot_dir, "project.godot")
        with open(self.project_godot, "w", encoding="utf-8") as f:
            f.write(SAMPLE_PROJECT_GODOT)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_updates_name_in_project_godot(self):
        converter = self._make_converter()
        converter.update_project_name()

        with open(self.project_godot, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('config/name="MyGame"', content)
        self.assertNotIn("Placeholder", content)

    def test_missing_project_godot_no_crash(self):
        os.remove(self.project_godot)
        converter = self._make_converter()
        converter.update_project_name()  # should not raise
        self.assertTrue(len(self.logs) > 0)


class TestReadAudioGroups(unittest.TestCase):
    """Test ProjectSettingsConverter.read_audio_groups()."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        with open(os.path.join(self.gm_dir, "Game.yyp"), "w", encoding="utf-8") as f:
            f.write(SAMPLE_YYP)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return ProjectSettingsConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_reads_audio_groups(self):
        converter = self._make_converter()
        groups = converter.read_audio_groups()
        self.assertEqual(groups, ["audiogroup_default", "audiogroup_music"])

    def test_empty_audio_groups(self):
        # Overwrite with a .yyp that has no AudioGroups section
        with open(os.path.join(self.gm_dir, "Game.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Game" }')

        converter = self._make_converter()
        groups = converter.read_audio_groups()
        self.assertEqual(groups, [])


if __name__ == "__main__":
    unittest.main()
