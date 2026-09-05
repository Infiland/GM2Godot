"""Included Files declarations preserve ordering, reservations, and discovery."""

import json
import os
import posixpath
import shutil
import tempfile
import threading
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, Mock, call

from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostic_models import ProjectManifestDiagnostic, ProjectSourceLocation
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_files_parts.models import (
    DeclaredIncludedFile,
    IncludedFileConversionPlan,
    IncludedFileSource,
)
from src.conversion.included_files_parts.planning import (
    build_included_file_plan,
    declared_included_files,
    plan_output_paths,
)
from src.conversion.project_manifest import GameMakerProjectManifest, ProjectIncludedFile, ProjectResourceReference
from src.conversion.project_source_paths import ResolvedProjectSourcePath


def _plan(manifest: GameMakerProjectManifest, effects: Mock) -> IncludedFileConversionPlan:
    return build_included_file_plan(manifest, resolve_declared=effects.resolve, reject_source=effects.reject,
                                    report_unavailable=effects.unavailable, discover_files=effects.discover)


class TestIncludedFilePlanning(unittest.TestCase):
    def test_manifest_shapes_keep_fallback_discovery_boundaries(self) -> None:
        disk = IncludedFileSource("disk", "disk.txt", "owner")
        base = GameMakerProjectManifest("project", "project.yyp")
        malformed = ProjectManifestDiagnostic("warning", "GM2GD-PROJECT-YYP-MALFORMED", "malformed")
        for manifest in (replace(base, yyp_path=None), base, replace(base, diagnostics=(malformed,)),
                         replace(base, raw_data={"IncludedFiles": []}), replace(base, raw_data={"includedFiles": []})):
            effects = Mock()
            effects.discover.return_value = (disk,)
            self.assertEqual(_plan(manifest, effects), IncludedFileConversionPlan(("disk.txt",), (disk,), ()))
            self.assertEqual(effects.mock_calls, [call.discover()])

    def test_declarations_keep_normalized_precedence_and_field_paths(self) -> None:
        location = ProjectSourceLocation("project.yyp", 1, "IncludedFiles[0]")
        first = ProjectIncludedFile("payload.yy", "datafiles/folder", source=location, raw_data={"filePath": ""})
        duplicate = ProjectIncludedFile("second", "datafiles/folder/./payload.yy")
        resource = ProjectResourceReference("", "resource", "datafiles/folder/payload.yy", "datafiles", "", 0)
        rejected = ProjectManifestDiagnostic("warning", "GM2GD-SOURCE-PATH-REJECTED", "rejected", location,
                                             "bad", "included_file")
        manifest = GameMakerProjectManifest("p", "project.yyp", included_files=(first, duplicate),
                                           resources=(resource,), diagnostics=(rejected,))
        self.assertEqual(declared_included_files(manifest), (
            DeclaredIncludedFile("payload.yy", "datafiles/folder/payload.yy", "project.yyp", "IncludedFiles[0].filePath"),
            DeclaredIncludedFile("bad", None, "project.yyp", "IncludedFiles[0]"),
        ))
        reference = replace(resource, path="datafiles/unique", kind="", resource_type="GMIncludedFile", source=location)
        self.assertEqual(declared_included_files(replace(manifest, resources=(reference,)))[1].manifest_field,
                         "IncludedFiles[0].id.path")

    def test_resolution_and_unavailable_callbacks_keep_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing")
            manifest = GameMakerProjectManifest("p", "project.yyp", raw_data={"IncludedFiles": []}, included_files=tuple(
                ProjectIncludedFile(name, f"datafiles/{name}") for name in ("missing", "alias", "outside", "rejected")
            ))
            effects = Mock()
            effects.resolve.side_effect = (ResolvedProjectSourcePath(missing, "datafiles/missing"),
                                           ResolvedProjectSourcePath(missing, "datafiles/missing"),
                                           ResolvedProjectSourcePath(missing, "scripts/outside"), None)
            effects.discover.return_value = ()
            plan = _plan(manifest, effects)
            self.assertEqual(plan, IncludedFileConversionPlan(("missing", "outside", "rejected"), (),
                                                             ("missing", "outside", "rejected")))
            self.assertEqual([event[0] for event in effects.mock_calls],
                             ["resolve", "unavailable", "resolve", "resolve", "reject", "unavailable",
                              "resolve", "unavailable", "discover"])
            self.assertEqual(effects.resolve.call_args_list[0], call(
                "datafiles/missing", owner_source_path="project.yyp", resource="missing",
                resource_type="included_file", field="path",
            ))
            self.assertEqual([event.kwargs["reason"] for event in effects.unavailable.call_args_list], [
                "the source file is missing at 'datafiles/missing'",
                "its manifest source path was rejected outside the datafiles resource family",
                "its manifest source path was rejected",
            ])
            self.assertEqual(str(effects.reject.call_args.args[1]),
                             "Resolved included-file source must remain under the GameMaker 'datafiles' directory")

    def test_missing_declarations_reserve_discovered_and_output_names(self) -> None:
        with tempfile.NamedTemporaryFile() as source:
            disk = IncludedFileSource(source.name, "name.txt", "disk")
            manifest = GameMakerProjectManifest("p", "p.yyp", raw_data={"IncludedFiles": []}, included_files=(
                ProjectIncludedFile("NAME.txt", "datafiles/NAME.txt"),
                ProjectIncludedFile("name.txt", "datafiles/name.txt"),
            ))
            effects = Mock()
            effects.resolve.side_effect = (None, ResolvedProjectSourcePath(source.name, "datafiles/name.txt"))
            effects.discover.return_value = (IncludedFileSource(source.name, "NAME.txt", "disk"), disk)
            plan = _plan(manifest, effects)
            self.assertEqual(plan.requested_keys, ("NAME.txt", "name.txt"))
            self.assertEqual(plan.skipped_keys, ("NAME.txt",))
            self.assertEqual(plan.available_files, (IncludedFileSource(source.name, "name.txt", "p.yyp"),))
            self.assertEqual(tuple(item.assigned_output_path for item in plan_output_paths(plan)),
                             ("name_2.txt", "name.txt"))

    def test_output_assignments_preserve_collision_order(self) -> None:
        plan = IncludedFileConversionPlan(("../invalid", "a", "A", "a/file", "a_2"),
                                          (IncludedFileSource("disk", "z", "owner"),), ("a",))
        assignments = plan_output_paths(plan)
        self.assertEqual(tuple((item.original_logical_path, item.assigned_output_path) for item in assignments),
                         (("A", "a_4"), ("a", "a_3"), ("a/file", "a/file"), ("a_2", "a_2"), ("z", "z")))
        self.assertEqual(assignments[0].collision_group, ("a", "A", "a/file"))
        self.assertEqual(tuple(item.has_collision for item in assignments), (True, True, False, False, False))


class TestIncludedFilesManifestAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yyp(self, files: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "IncludedPaths.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "IncludedFiles": [
                        {
                            "name": name,
                            "filePath": posixpath.dirname(path),
                        }
                        for name, path in files
                    ]
                },
                project_file,
            )

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
            max_workers=1,
        )

    def test_missing_only_declared_file_makes_conversion_partial(self) -> None:
        self._write_yyp(
            [("missing.txt", "datafiles/config/missing.txt")]
        )
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        included_files_enabled = MagicMock()
        included_files_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"included_files": included_files_enabled},
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
            if diagnostic.code
            == "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].resource, "missing.txt")
        self.assertEqual(unavailable[0].source_path, "IncludedPaths.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "IncludedFiles[0].filePath",
        )
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn(
            '"logical_path": "config/missing.txt"',
            registry_content,
        )
        self.assertIn('"emitted": false', registry_content)

    def test_safe_missing_and_disk_only_file_have_strict_counts(self) -> None:
        safe_source = os.path.join(self.datafiles_dir, "config", "safe.txt")
        os.makedirs(os.path.dirname(safe_source))
        with open(safe_source, "w", encoding="utf-8") as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.datafiles_dir, "orphan.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("orphan")
        self._write_yyp(
            [
                ("safe.txt", "datafiles/config/safe.txt"),
                ("missing.txt", "datafiles/config/missing.txt"),
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
                requested=3,
                executed=2,
                completed=2,
                skipped=1,
            ),
        )
        safe_output = os.path.join(
            self.godot_dir,
            "included_files",
            "config",
            "safe.txt",
        )
        with open(safe_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "safe")
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "config",
                    "missing.txt",
                )
            )
        )
        disk_only_output = os.path.join(
            self.godot_dir,
            "included_files",
            "orphan.txt",
        )
        with open(disk_only_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "orphan")
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].resource, "missing.txt")
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn(
            '"logical_path": "config/missing.txt"',
            registry_content,
        )
        self.assertIn('"logical_path": "config/safe.txt"', registry_content)
        self.assertEqual(registry_content.count('"emitted": false'), 1)
        self.assertEqual(registry_content.count('"emitted": true'), 2)

    def test_duplicate_exact_manifest_file_is_accounted_once(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "once.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("once")
        declaration = ("once.txt", "datafiles/once.txt")
        self._write_yyp([declaration, declaration])
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_manifest_declared_yy_payload_is_copied(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "payload.yy")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("included payload")
        self._write_yyp([("payload.yy", "datafiles/payload.yy")])

        self._make_converter().convert_all()

        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.yy",
        )
        with open(output_path, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "included payload")

    def test_rejected_declared_file_is_requested_and_skipped(self) -> None:
        self._write_yyp(
            [
                (
                    "rejected.txt",
                    "datafiles/../../outside/rejected.txt",
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
        self.assertIn(
            "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE",
            diagnostic_codes,
        )


class TestIncludedFilesConverterNestedDirs(unittest.TestCase):
    """Test that nested Included Files use GameMaker's packaged names."""

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

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
            max_workers=1,
        )

    def test_normalizes_nested_packaged_paths(self):
        converter = self._make_converter()
        converter.convert_all()

        expected_lang = os.path.join(
            self.godot_dir,
            "included_files",
            "languages",
            "english.lang",
        )
        expected_rank = os.path.join(
            self.godot_dir,
            "included_files",
            "modding",
            "ranking_system",
            "ranks.txt",
        )

        self.assertTrue(os.path.isfile(expected_lang), f"Expected {expected_lang}")
        self.assertTrue(os.path.isfile(expected_rank), f"Expected {expected_rank}")

        with open(expected_lang, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "lang data")
        with open(expected_rank, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "rank data")

    def test_collision_paths_reserve_natural_suffixes_and_warn_once(self) -> None:
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        fixtures = {
            "read_me.txt": "canonical",
            "Read Me.txt": "normalized collision",
            "read_me_2.txt": "natural suffix",
        }
        for filename, content in fixtures.items():
            with open(
                os.path.join(datafiles_dir, filename),
                "w",
                encoding="utf-8",
            ) as source_file:
                source_file.write(content)

        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        converter.convert_all()

        expected_outputs = {
            "read_me.txt": "canonical",
            "read_me_2.txt": "natural suffix",
            "read_me_3.txt": "normalized collision",
        }
        for filename, content in expected_outputs.items():
            with self.subTest(filename=filename):
                output_path = os.path.join(
                    self.godot_dir,
                    "included_files",
                    filename,
                )
                with open(output_path, "r", encoding="utf-8") as output_file:
                    self.assertEqual(output_file.read(), content)

        collision_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-PATH-COLLISION"
        ]
        self.assertEqual(len(collision_diagnostics), 1)
        collision = collision_diagnostics[0]
        self.assertEqual(collision.severity, "warning")
        self.assertEqual(collision.source_path, "datafiles")
        self.assertEqual(collision.resource, "read_me.txt")
        self.assertEqual(collision.resource_type, "included_file")
        self.assertIn("'read_me.txt' -> 'read_me.txt'", collision.message)
        self.assertIn("'Read Me.txt' -> 'read_me_3.txt'", collision.message)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=5, executed=5, completed=5),
        )
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn('"logical_path": "Read Me.txt"', registry_content)
        self.assertIn('"assigned_path": "read_me_3.txt"', registry_content)
        self.assertEqual(registry_content.count('"emitted": true'), 5)

    def test_file_directory_prefix_collision_is_relocated_and_reported(
        self,
    ) -> None:
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        with open(
            os.path.join(datafiles_dir, "foo_bar"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("blocking file")
        nested_directory = os.path.join(datafiles_dir, "Foo Bar")
        os.makedirs(nested_directory)
        with open(
            os.path.join(nested_directory, "item.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("nested file")

        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        converter.convert_all()

        blocking_output = os.path.join(
            self.godot_dir,
            "included_files",
            "foo_bar_2",
        )
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "foo_bar",
            "item.txt",
        )
        with open(blocking_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "blocking file")
        with open(nested_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "nested file")

        collision_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-PATH-COLLISION"
        ]
        self.assertEqual(len(collision_diagnostics), 1)
        collision = collision_diagnostics[0]
        self.assertEqual(collision.resource, "foo_bar")
        self.assertEqual(
            collision.manifest_entry,
            "normalized Included File output path",
        )
        self.assertIn("'foo_bar' -> 'foo_bar_2'", collision.message)
        self.assertIn(
            "'Foo Bar/item.txt' -> 'foo_bar/item.txt'",
            collision.message,
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=4, executed=4, completed=4),
        )


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
