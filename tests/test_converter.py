import os
import sys
import threading
import tempfile
import shutil
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.converter import CONVERSION_CATEGORIES, Converter


class TestConversionCategories(unittest.TestCase):
    """Test that CONVERSION_CATEGORIES has the expected structure."""

    def test_has_three_groups(self):
        self.assertEqual(len(CONVERSION_CATEGORIES), 3)

    def test_expected_keys(self):
        self.assertIn("assets", CONVERSION_CATEGORIES)
        self.assertIn("project", CONVERSION_CATEGORIES)
        self.assertIn("wip", CONVERSION_CATEGORIES)

    def test_assets_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["assets"],
                         ["sprites", "fonts", "sounds", "included_files"])

    def test_project_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["project"],
                         ["game_icon", "project_name", "project_settings",
                          "audio_buses", "notes"])

    def test_wip_contents(self):
        self.assertEqual(CONVERSION_CATEGORIES["wip"],
                         ["objects", "shaders", "tilesets"])


class _FakeBooleanVar:
    """Mimics tkinter BooleanVar for testing."""
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class TestConverterSkipsDisabled(unittest.TestCase):
    """Converter.convert() should skip converters whose setting is False."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
        self.statuses = []

        # Create minimal GM project structure
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Test" }')

        # Create minimal Godot project
        with open(os.path.join(self.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write('[application]\nconfig/name="Test"\n')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_all_disabled_runs_no_converters(self):
        conversion_running = threading.Event()
        conversion_running.set()

        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            status_callback=lambda msg: self.statuses.append(msg),
            conversion_running=conversion_running,
        )

        # All settings disabled
        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: _FakeBooleanVar(False) for key in all_keys}

        converter.convert(self.gm_dir, "windows", self.godot_dir, settings)

        # With every setting False, no converter log/status messages should appear
        self.assertEqual(self.logs, [])
        self.assertEqual(self.statuses, [])


class TestConverterRespectsRunningFlag(unittest.TestCase):
    """Converter.convert() should check conversion_running between converters."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
        self.statuses = []

        with open(os.path.join(self.gm_dir, "Test.yyp"), "w", encoding="utf-8") as f:
            f.write('{ "%Name": "Test" }')

        with open(os.path.join(self.godot_dir, "project.godot"), "w", encoding="utf-8") as f:
            f.write('[application]\nconfig/name="Test"\n')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_stops_when_flag_cleared(self):
        conversion_running = threading.Event()
        # Start cleared -- no converter should run
        # (conversion_running.is_set() returns False)

        converter = Converter(
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            status_callback=lambda msg: self.statuses.append(msg),
            conversion_running=conversion_running,
        )

        all_keys = (
            CONVERSION_CATEGORIES["assets"]
            + CONVERSION_CATEGORIES["project"]
            + CONVERSION_CATEGORIES["wip"]
        )
        settings = {key: _FakeBooleanVar(True) for key in all_keys}

        converter.convert(self.gm_dir, "windows", self.godot_dir, settings)

        # Nothing should have run because the event was never set
        self.assertEqual(self.logs, [])
        self.assertEqual(self.statuses, [])


if __name__ == "__main__":
    unittest.main()
