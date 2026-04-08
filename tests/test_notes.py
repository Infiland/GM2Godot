import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.notes import NoteConverter


class TestNoteConverterBasic(unittest.TestCase):
    """Test NoteConverter copies text files to the Godot project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        notes_dir = os.path.join(self.gm_dir, "notes")
        os.makedirs(notes_dir)

        self.note_path = os.path.join(notes_dir, "test_note.txt")
        with open(self.note_path, "w", encoding="utf-8") as f:
            f.write("This is a test note.")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return NoteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_copies_note_to_godot(self):
        converter = self._make_converter()
        converter.convert_all()

        # NoteConverter creates a folder named after the note, then copies the txt inside
        expected = os.path.join(self.godot_dir, "notes", "test_note", "test_note.txt")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

        with open(expected, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "This is a test note.")

    def test_multiple_notes(self):
        notes_dir = os.path.join(self.gm_dir, "notes")
        for name in ("readme.txt", "changelog.txt"):
            with open(os.path.join(notes_dir, name), "w", encoding="utf-8") as f:
                f.write(f"Content of {name}")

        converter = self._make_converter()
        converter.convert_all()

        for base in ("test_note", "readme", "changelog"):
            expected = os.path.join(self.godot_dir, "notes", base, f"{base}.txt")
            self.assertTrue(os.path.isfile(expected), f"Expected {expected}")


class TestNoteConverterMissingFolder(unittest.TestCase):
    """When the notes folder does not exist the converter should log an error."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []
        # Deliberately do NOT create a notes folder

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_missing_notes_no_crash(self):
        converter = NoteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing notes folder")


if __name__ == "__main__":
    unittest.main()
