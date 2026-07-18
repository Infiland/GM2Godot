import json
import os
import sys
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.notes import NoteConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostics import DiagnosticCollector


class TestableNoteConverter(NoteConverter):
    def discover_notes_for_test(self):
        notes_root = self._resolve_project_source("notes")
        assert notes_root is not None
        return self._discover_notes(notes_root)

    def process_note_for_test(
        self,
        src_file: str,
        dst_file: str,
        note_name: str,
        owner_source_path: str,
    ):
        return self._process_note(
            src_file,
            dst_file,
            note_name,
            owner_source_path,
        )


class TestNoteConverterBasic(unittest.TestCase):
    """Test NoteConverter copies text files to the Godot project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

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

    def test_resource_outcome_counts_logical_notes(self):
        notes_dir = os.path.join(self.gm_dir, "notes")
        with open(os.path.join(notes_dir, "second.txt"), "w", encoding="utf-8") as f:
            f.write("Second note")
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result().resources

        self.assertEqual(counts.requested, 2)
        self.assertEqual(counts.executed, 2)
        self.assertEqual(counts.completed, 2)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)


class TestNoteConverterManifestAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        os.makedirs(os.path.join(self.gm_dir, "notes"))

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> NoteConverter:
        return NoteConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )

    def _write_yyp(self, resources: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "NoteAccounting.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "resources": [
                        {"id": {"name": name, "path": path}}
                        for name, path in resources
                    ],
                    "resourceType": "GMProject",
                },
                project_file,
            )

    def _write_note(
        self,
        note_name: str,
        *,
        include_text: bool = True,
    ) -> None:
        note_directory = os.path.join(self.gm_dir, "notes", note_name)
        os.makedirs(note_directory)
        with open(
            os.path.join(note_directory, f"{note_name}.yy"),
            "w",
            encoding="utf-8",
        ) as metadata_file:
            json.dump(
                {
                    "name": note_name,
                    "resourceType": "GMNotes",
                    "parent": {
                        "name": "Notes",
                        "path": "folders/Notes.yy",
                    },
                },
                metadata_file,
            )
        if include_text:
            with open(
                os.path.join(note_directory, f"{note_name}.txt"),
                "w",
                encoding="utf-8",
            ) as note_file:
                note_file.write(f"Contents of {note_name}")

    def test_missing_only_declared_note_makes_conversion_partial(self) -> None:
        self._write_yyp(
            [("note_missing", "notes/note_missing/note_missing.yy")]
        )
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
            max_workers=1,
        )
        notes_enabled = MagicMock()
        notes_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"notes": notes_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, skipped=1),
        )
        unavailable = [
            diagnostic
            for diagnostic in converter.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-NOTE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "note_missing")
        self.assertEqual(unavailable[0].source_path, "NoteAccounting.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "resources[0].id.path",
        )

    def test_safe_and_missing_declared_notes_have_strict_counts(self) -> None:
        self._write_note("note_safe")
        self._write_note("note_missing_text", include_text=False)
        self._write_note("note_orphan")
        safe_reference = (
            "note_safe",
            "notes/note_safe/note_safe.yy",
        )
        self._write_yyp(
            [
                safe_reference,
                safe_reference,
                (
                    "note_missing_text",
                    "notes/note_missing_text/note_missing_text.yy",
                ),
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "notes",
                    "note_safe",
                    "note_safe.txt",
                )
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "notes", "note_orphan")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "notes", "note_missing_text")
            )
        )
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-NOTE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "note_missing_text")

    def test_rejected_declared_note_is_requested_and_skipped(self) -> None:
        self._write_yyp(
            [
                (
                    "note_rejected",
                    "notes/../../outside/note_rejected/note_rejected.yy",
                )
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, skipped=1),
        )
        diagnostic_codes = {
            diagnostic.code for diagnostic in diagnostics.diagnostics()
        }
        self.assertIn("GM2GD-SOURCE-PATH-REJECTED", diagnostic_codes)
        self.assertIn("GM2GD-NOTE-SOURCE-UNAVAILABLE", diagnostic_codes)

    def test_malformed_yyp_uses_contained_disk_fallback(self) -> None:
        self._write_note("note_fallback")
        with open(
            os.path.join(self.gm_dir, "NoteAccounting.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            project_file.write("{ malformed")
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "notes",
                    "note_fallback",
                    "note_fallback.txt",
                )
            )
        )


class TestNoteConverterMissingFolder(unittest.TestCase):
    """When the notes folder does not exist the converter should log an error."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
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


class TestNoteConverterSubfolders(unittest.TestCase):
    """Test that notes respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create a note with a .yy file that specifies a subfolder
        note_dir = os.path.join(self.gm_dir, "notes", "my_note")
        os.makedirs(note_dir)
        with open(os.path.join(note_dir, "my_note.txt"), "w") as f:
            f.write("Note content")
        with open(os.path.join(note_dir, "my_note.yy"), "w") as f:
            f.write('{"name": "my_note", "parent": {"name": "Design", "path": "folders/Notes/Design.yy",},}')

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

    def test_note_in_subfolder(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "notes", "design", "my_note", "my_note.txt")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected note at {expected}")

    def test_note_without_yy_stays_flat(self):
        """A note without a .yy file should default to root."""
        note_dir = os.path.join(self.gm_dir, "notes", "plain_note")
        os.makedirs(note_dir)
        with open(os.path.join(note_dir, "plain_note.txt"), "w") as f:
            f.write("Plain note")

        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "notes", "plain_note", "plain_note.txt")
        self.assertTrue(os.path.isfile(expected),
                        "Note without .yy should remain at root level")


class TestNoteConverterSourceContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()
        os.makedirs(os.path.join(self.gm_dir, "notes"))

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(self) -> TestableNoteConverter:
        return TestableNoteConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def _source_path_rejections(self):
        return [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def _symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output_file:
            output_file.write(content)

    def test_rejects_notes_root_symlink_to_external_directory(self) -> None:
        notes_root = os.path.join(self.gm_dir, "notes")
        shutil.rmtree(notes_root)
        external_note = os.path.join(self.outside_dir, "external_note.txt")
        self._write_text(external_note, "EXTERNAL ROOT NOTE")
        self._symlink(self.outside_dir, notes_root)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "notes",
                    "external_note",
                    "external_note.txt",
                )
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource_type, "note")
        self.assertEqual(rejected[0].manifest_entry, "notes directory")

    def test_skips_external_nested_directory_but_copies_safe_note(self) -> None:
        safe_note = os.path.join(self.gm_dir, "notes", "safe.txt")
        self._write_text(safe_note, "SAFE NOTE")
        external_note = os.path.join(self.outside_dir, "leak.txt")
        self._write_text(external_note, "EXTERNAL DIRECTORY NOTE")
        self._symlink(
            self.outside_dir,
            os.path.join(self.gm_dir, "notes", "linked_notes"),
        )

        self._make_converter().convert_all()

        safe_output = os.path.join(
            self.godot_dir,
            "notes",
            "safe",
            "safe.txt",
        )
        with open(safe_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "SAFE NOTE")
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "notes", "leak", "leak.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "notes")
        self.assertEqual(rejected[0].resource, "linked_notes")
        self.assertEqual(rejected[0].resource_type, "note")
        self.assertEqual(rejected[0].manifest_entry, "discovered note entry")

    def test_rejects_external_note_file_symlink(self) -> None:
        external_note = os.path.join(self.outside_dir, "outside.txt")
        self._write_text(external_note, "EXTERNAL FILE NOTE")
        linked_note = os.path.join(self.gm_dir, "notes", "linked.txt")
        self._symlink(external_note, linked_note)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "notes", "linked", "linked.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "notes")
        self.assertEqual(rejected[0].resource, "linked")
        self.assertEqual(rejected[0].resource_type, "note")
        self.assertEqual(rejected[0].manifest_entry, "note text file")

    def test_rejects_external_companion_yy_without_reading_it(self) -> None:
        note_directory = os.path.join(self.gm_dir, "notes", "my_note")
        note_path = os.path.join(note_directory, "my_note.txt")
        self._write_text(note_path, "SAFE NOTE")
        outside_yy = os.path.join(self.outside_dir, "my_note.yy")
        self._write_text(
            outside_yy,
            '{"parent":{"path":"folders/Notes/External.yy"}}',
        )
        self._symlink(outside_yy, os.path.join(note_directory, "my_note.yy"))

        self._make_converter().convert_all()

        flat_output = os.path.join(
            self.godot_dir,
            "notes",
            "my_note",
            "my_note.txt",
        )
        external_folder_output = os.path.join(
            self.godot_dir,
            "notes",
            "external",
            "my_note",
            "my_note.txt",
        )
        self.assertTrue(os.path.isfile(flat_output))
        self.assertFalse(os.path.exists(external_folder_output))
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "notes/my_note")
        self.assertEqual(rejected[0].resource, "my_note")
        self.assertEqual(rejected[0].resource_type, "note")
        self.assertEqual(rejected[0].manifest_entry, "note metadata .yy")

    def test_final_pre_copy_check_rejects_late_note_symlink_swap(self) -> None:
        note_path = os.path.join(self.gm_dir, "notes", "late.txt")
        self._write_text(note_path, "ORIGINAL SAFE NOTE")
        outside_note = os.path.join(self.outside_dir, "late.txt")
        self._write_text(outside_note, "LATE EXTERNAL NOTE")
        converter = self._make_converter()
        assets = converter.discover_notes_for_test()
        self.assertEqual(len(assets), 1)

        os.unlink(note_path)
        self._symlink(outside_note, note_path)
        destination = os.path.join(self.godot_dir, "late.txt")
        result = converter.process_note_for_test(
            assets[0].filesystem_path,
            destination,
            assets[0].name,
            assets[0].owner_source_path,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.copied)
        self.assertFalse(os.path.exists(destination))
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "notes")
        self.assertEqual(rejected[0].resource, "late")
        self.assertEqual(rejected[0].resource_type, "note")
        self.assertEqual(
            rejected[0].manifest_entry,
            "note text file (pre-copy)",
        )

    def test_final_pre_copy_check_rejects_malformed_source_candidates(self) -> None:
        outside_note = os.path.join(self.outside_dir, "outside.txt")
        self._write_text(outside_note, "OUTSIDE NOTE")
        traversal_path = os.path.relpath(outside_note, self.gm_dir)
        unsafe_paths = [
            traversal_path,
            outside_note,
            r"C:\Games\Outside\note.txt",
            r"C:Outside\note.txt",
            r"\\server\share\note.txt",
            "notes/bad\0note.txt",
        ]
        converter = self._make_converter()

        for index, unsafe_path in enumerate(unsafe_paths):
            with self.subTest(unsafe_path=unsafe_path):
                result = converter.process_note_for_test(
                    unsafe_path,
                    os.path.join(self.godot_dir, f"unsafe_{index}.txt"),
                    f"unsafe_{index}",
                    "notes",
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.copied)

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), len(unsafe_paths), rejected)
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {"notes"},
        )
        self.assertTrue(
            all(diagnostic.resource_type == "note" for diagnostic in rejected)
        )
        self.assertTrue(
            all(
                diagnostic.manifest_entry == "note text file (pre-copy)"
                for diagnostic in rejected
            )
        )
        self.assertFalse(
            any(
                filenames
                for _root, _directories, filenames in os.walk(self.godot_dir)
            )
        )


if __name__ == "__main__":
    unittest.main()
