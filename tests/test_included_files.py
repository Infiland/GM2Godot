# pyright: reportPrivateUsage=false

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.included_files import IncludedFilesConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath


class TestIncludedFilesConverterBasic(unittest.TestCase):
    """Test IncludedFilesConverter copies datafiles to the Godot project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(datafiles_dir)

        self.test_file = os.path.join(datafiles_dir, "test.txt")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("test content")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_copies_file_to_godot(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "included_files", "test.txt")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

        with open(expected, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "test content")

    def test_multiple_files(self):
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        for name in ("config.ini", "data.csv"):
            with open(os.path.join(datafiles_dir, name), "w", encoding="utf-8") as f:
                f.write(f"Content of {name}")

        converter = self._make_converter()
        converter.convert_all()

        for name in ("test.txt", "config.ini", "data.csv"):
            expected = os.path.join(self.godot_dir, "included_files", name)
            self.assertTrue(os.path.isfile(expected), f"Expected {expected}")


class TestIncludedFilesConverterNestedDirs(unittest.TestCase):
    """Test that nested directory structures are preserved."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create nested structure like the Asteroids++ project
        langs_dir = os.path.join(self.gm_dir, "datafiles", "Languages")
        modding_dir = os.path.join(self.gm_dir, "datafiles", "Modding", "Ranking System")
        os.makedirs(langs_dir)
        os.makedirs(modding_dir)

        with open(os.path.join(langs_dir, "english.lang"), "w", encoding="utf-8") as f:
            f.write("lang data")
        with open(os.path.join(modding_dir, "ranks.txt"), "w", encoding="utf-8") as f:
            f.write("rank data")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_preserves_directory_structure(self):
        converter = self._make_converter()
        converter.convert_all()

        expected_lang = os.path.join(self.godot_dir, "included_files", "Languages", "english.lang")
        expected_rank = os.path.join(self.godot_dir, "included_files", "Modding", "Ranking System", "ranks.txt")

        self.assertTrue(os.path.isfile(expected_lang), f"Expected {expected_lang}")
        self.assertTrue(os.path.isfile(expected_rank), f"Expected {expected_rank}")

        with open(expected_lang, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "lang data")
        with open(expected_rank, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "rank data")


class TestIncludedFilesConverterSkipsYY(unittest.TestCase):
    """Test that .yy metadata files are skipped."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(datafiles_dir)

        with open(os.path.join(datafiles_dir, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("readme")
        with open(os.path.join(datafiles_dir, "datafiles.yy"), "w", encoding="utf-8") as f:
            f.write("{}")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_skips_yy_files(self):
        converter = IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        included_dir = os.path.join(self.godot_dir, "included_files")
        self.assertTrue(os.path.isfile(os.path.join(included_dir, "readme.txt")))
        self.assertFalse(os.path.exists(os.path.join(included_dir, "datafiles.yy")))


class TestIncludedFilesConverterMissingFolder(unittest.TestCase):
    """When the datafiles folder does not exist the converter should log an error."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_missing_datafiles_no_crash(self):
        converter = IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing datafiles folder")


class TestIncludedFilesConverterSourceContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(self) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=self.diagnostics,
        )

    def _source_path_rejections(self):
        return [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def _make_symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def test_rejects_datafiles_root_symlink_outside_project(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        shutil.rmtree(self.datafiles_dir)
        self._make_symlink(self.outside_dir, self.datafiles_dir)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "outside.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "datafiles")
        self.assertEqual(rejected[0].resource_type, "included_file")
        self.assertEqual(rejected[0].manifest_entry, "datafiles directory")

    def test_rejects_nested_directory_symlink_outside_project(self) -> None:
        with open(
            os.path.join(self.datafiles_dir, "safe.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.outside_dir, "outside.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("outside project")
        self._make_symlink(
            self.outside_dir,
            os.path.join(self.datafiles_dir, "linked_directory"),
        )

        self._make_converter().convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(self.godot_dir, "included_files", "safe.txt")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "linked_directory",
                    "outside.txt",
                )
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "linked_directory")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles entry")

    def test_rejects_file_symlink_outside_project(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        linked_file = os.path.join(self.datafiles_dir, "linked.txt")
        self._make_symlink(outside_file, linked_file)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "linked.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "linked.txt")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles entry")

    def test_preserves_contained_file_symlink_copy_semantics(self) -> None:
        target_file = os.path.join(self.datafiles_dir, "target.txt")
        with open(target_file, "w", encoding="utf-8") as source_file:
            source_file.write("contained target")
        self._make_symlink(
            target_file,
            os.path.join(self.datafiles_dir, "alias.txt"),
        )

        self._make_converter().convert_all()

        alias_output = os.path.join(
            self.godot_dir,
            "included_files",
            "alias.txt",
        )
        with open(alias_output, "r", encoding="utf-8") as copied_file:
            self.assertEqual(copied_file.read(), "contained target")

    def test_direct_copy_boundary_rejects_malformed_source_forms(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        unsafe_paths = (
            os.path.relpath(outside_file, self.gm_dir),
            outside_file,
            r"C:\Games\Outside\file.txt",
            r"C:Outside\file.txt",
            r"\\server\share\file.txt",
            "invalid\0file.txt",
        )
        output_directory = os.path.join(self.godot_dir, "included_files")
        os.makedirs(output_directory)
        converter = self._make_converter()

        for index, source_path in enumerate(unsafe_paths):
            with self.subTest(source_path=source_path):
                output_path = os.path.join(output_directory, f"rejected_{index}.txt")
                result = converter._process_file(
                    source_path,
                    output_path,
                    f"rejected_{index}.txt",
                )
                self.assertEqual(result, (f"rejected_{index}.txt", False))
                self.assertFalse(os.path.exists(output_path))

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), len(unsafe_paths), rejected)
        self.assertTrue(
            all(
                diagnostic.source_path == "datafiles"
                and diagnostic.resource_type == "included_file"
                and diagnostic.manifest_entry == "discovered datafiles file"
                for diagnostic in rejected
            )
        )

    def test_revalidates_file_after_discovery_before_copy(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "swapped.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("original contained file")
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        converter = self._make_converter()
        original_process_file = converter._process_file
        swapped = False

        def swap_then_process(
            gm_file_path: str,
            godot_file_path: str,
            rel_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool] | None:
            nonlocal swapped
            if not swapped and rel_path == "swapped.txt":
                os.remove(source_path)
                self._make_symlink(outside_file, source_path)
                swapped = True
            return original_process_file(
                gm_file_path,
                godot_file_path,
                rel_path,
                owner_source_path,
            )

        with patch.object(
            converter,
            "_process_file",
            side_effect=swap_then_process,
        ):
            converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "swapped.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "swapped.txt")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles file")

    def test_revalidates_nested_directory_before_listing(self) -> None:
        nested_directory = os.path.join(self.datafiles_dir, "nested")
        os.makedirs(nested_directory)
        with open(
            os.path.join(nested_directory, "safe.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.outside_dir, "outside.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("outside project")
        converter = self._make_converter()
        original_list_directory = converter._list_confined_directory
        swapped = False

        def swap_then_list(
            directory: ResolvedProjectSourcePath,
        ) -> tuple[str, ...] | None:
            nonlocal swapped
            if not swapped and directory.source_path == "datafiles/nested":
                shutil.rmtree(nested_directory)
                self._make_symlink(self.outside_dir, nested_directory)
                swapped = True
            return original_list_directory(directory)

        with patch.object(
            converter,
            "_list_confined_directory",
            side_effect=swap_then_list,
        ):
            converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "nested",
                    "outside.txt",
                )
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "nested")
        self.assertEqual(
            rejected[0].manifest_entry,
            "discovered datafiles directory",
        )


if __name__ == "__main__":
    unittest.main()
