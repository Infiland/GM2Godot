import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion import resource_models
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.json_values import JsonObject
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectAudioGroup,
    ProjectOption,
    load_gamemaker_project_manifest,
)
from src.conversion.project_settings import ProjectOperationResult, ProjectSettingsConverter


class TestProjectModelConsumers(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.gm = self.root / "gm"
        self.out = self.root / "out"
        self.gm.mkdir()
        self.out.mkdir()
        self.yyp = self.gm / "Project.yyp"
        self.yyp.write_text('{"name":"Project"}', encoding="utf-8")
        self.options = self.gm / "options/main/options_main.yy"
        self.options.parent.mkdir(parents=True)
        self.options.write_text('{"option_game_speed":60}', encoding="utf-8")
        self.project = self.out / "project.godot"
        self.project.write_bytes(b"config_version=5\n\n[application]\nrun/max_fps=1\n")
        self.logs: list[str] = []

    def settings(self) -> ProjectSettingsConverter:
        return ProjectSettingsConverter(str(self.gm), str(self.out), log_callback=self.logs.append)

    def test_aggregate_keeps_the_same_manifest_and_retires_project_projection(self) -> None:
        manifest = load_gamemaker_project_manifest(str(self.gm))
        with patch("src.conversion.resource_models.load_gamemaker_project_manifest", return_value=manifest):
            models = resource_models.parse_gamemaker_resource_models(str(self.gm))
        self.assertIs(models.project, manifest)
        self.assertEqual(models.project.project_name, "Project")
        self.assertFalse(hasattr(models.project, "resource_count"))
        self.assertFalse(hasattr(resource_models, "ProjectModel"))
        self.assertFalse(hasattr(resource_models, "_project_model"))

    def test_option_files_keep_traversal_empty_unknown_and_shared_option_records(self) -> None:
        rows = (
            ("options/options_main.yy", '{"option_same":1}'),
            ("options/main/a.yy", "{}"),
            ("options/main/b.yy", '{"unknown":{"nested":[null]}}'),
            ("options/main/c.yy", '{"option_same":[1],"option_text":",]",}'),
            ("options/main/ignored.YY", '{"option_ignored":true}'),
            ("options/windows/a.yy", '{"option_same":2}'),
            ("options/windows/b.yy", "null"),
        )
        for relative, source in rows:
            path = self.gm / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        manifest = load_gamemaker_project_manifest(str(self.gm))
        self.assertEqual(
            [Path(metadata.source_path).relative_to(self.gm).as_posix() for metadata in manifest.option_files],
            [
                "options/options_main.yy",
                "options/main/a.yy",
                "options/main/b.yy",
                "options/main/c.yy",
                "options/main/options_main.yy",
                "options/windows/a.yy",
            ],
        )
        self.assertEqual([metadata.platform for metadata in manifest.option_files], ["main"] * 5 + ["windows"])
        self.assertEqual(manifest.option_files[1].options, ())
        self.assertEqual(manifest.option_files[2].raw_data, {"unknown": {"nested": [None]}})
        flattened = tuple(option for metadata in manifest.option_files for option in metadata.options)
        for loaded, option in zip(manifest.options, flattened, strict=True):
            self.assertIs(loaded, option)
        self.assertEqual(
            [option.key for option in manifest.options],
            ["option_same", "option_same", "option_text", "option_game_speed", "option_same"],
        )
        metadata = manifest.option_files[3]
        self.assertEqual(metadata.source, rows[3][1])
        self.assertEqual(metadata.options[1].value, "]")
        nested = metadata.raw_data["option_same"]
        assert isinstance(nested, list)
        nested.append(False)
        self.assertIs(metadata.options[0].value, nested)
        self.assertEqual(metadata.options[0].value, [1, False])
        metadata.raw_data["option_same"] = None
        self.assertEqual(metadata.options[0].value, [1, False])

    def test_manifest_options_keep_reader_skip_and_recursion_boundaries(self) -> None:
        for source in (b"\xff", b"{", b"null", b"1" * 5000):
            with self.subTest(source=source[:20]):
                self.options.write_bytes(source)
                manifest = load_gamemaker_project_manifest(str(self.gm))
                self.assertEqual(manifest.options, ())
                self.assertEqual(manifest.option_files, ())
                self.assertFalse(manifest.diagnostics)
        self.options.write_bytes(b"[" * 20000 + b"0" + b"]" * 20000)
        with self.assertRaises(RecursionError):
            load_gamemaker_project_manifest(str(self.gm))

    def test_operation_scan_keeps_platform_order_and_ignores_nested_candidates(self) -> None:
        nested = self.options.parent / "nested/extra.yy"
        nested.parent.mkdir()
        nested.write_text('{"option_extra":true}', encoding="utf-8")
        converter = self.settings()
        nested.write_bytes(b"\xff")
        self.assertEqual(converter.update_project_settings(), ProjectOperationResult("completed"))
        windows = self.gm / "options/windows"
        windows.mkdir()
        (windows / "z.yy").write_text("null", encoding="utf-8")
        first = windows / "a.YY"
        first.write_text("[]", encoding="utf-8")
        self.options.write_text("{", encoding="utf-8")
        self.assertEqual(
            converter.update_project_settings(),
            ProjectOperationResult("skipped", f"GameMaker options metadata is malformed: {first}"),
        )

    def test_fresh_valid_and_empty_replacements_render_cached_options(self) -> None:
        converter = self.settings()
        manifest = converter.project_manifest
        cached = manifest.options
        for source in ('{"option_game_speed":120}', "{}"):
            with self.subTest(source=source):
                self.options.write_text(source, encoding="utf-8")
                self.assertEqual(converter.update_project_settings(), ProjectOperationResult("completed"))
                self.assertIn("run/max_fps=60", self.project.read_text(encoding="utf-8"))
                self.assertIs(converter.project_manifest, manifest)
                self.assertIs(manifest.options, cached)
                self.assertEqual(cached[0].value, 60)

    def test_fresh_malformed_roots_log_reason_and_do_not_write(self) -> None:
        converter = self.settings()
        before = self.project.read_bytes()
        expected = ProjectOperationResult("skipped", f"GameMaker options metadata is malformed: {self.options}")
        for source in ("null", "[]", '"text"', "true", "12", "{", "1" * 5000):
            with self.subTest(source=source[:20]):
                self.options.write_text(source, encoding="utf-8")
                self.logs.clear()
                self.assertEqual(converter.update_project_settings(), expected)
                self.assertEqual(self.logs, [expected.reason])
                self.assertEqual(self.project.read_bytes(), before)

    def test_encoding_and_recursion_errors_propagate_before_output_checks(self) -> None:
        converter = self.settings()
        self.project.unlink()
        for source, error in ((b"\xff", UnicodeDecodeError), (b"[" * 20000 + b"0" + b"]" * 20000, RecursionError)):
            with self.subTest(error=error):
                self.options.write_bytes(source)
                self.logs.clear()
                with self.assertRaises(error):
                    converter.update_project_settings()
                self.assertEqual(self.logs, [])
                self.assertFalse(self.project.exists())

    def test_directory_read_error_keeps_native_reason_and_no_write(self) -> None:
        converter = self.settings()
        before = self.project.read_bytes()
        self.options.unlink()
        self.options.mkdir()
        with self.assertRaises(OSError) as native:
            self.options.read_text(encoding="utf-8")
        result = converter.update_project_settings()
        self.assertEqual(result, ProjectOperationResult("failed", str(native.exception)))
        self.assertEqual(self.logs, [str(native.exception)])
        self.assertEqual(self.project.read_bytes(), before)

    def test_uppercase_file_validates_without_manifest_options(self) -> None:
        self.options.rename(self.options.with_suffix(".YY"))
        converter = self.settings()
        before = self.project.read_bytes()
        self.assertEqual(converter.project_manifest.options, ())
        self.assertEqual(converter.update_project_settings(), ProjectOperationResult("completed"))
        self.assertEqual(self.project.read_bytes(), before)

    def test_missing_candidates_use_injected_platform_fallback(self) -> None:
        self.options.unlink()
        converter = self.settings()
        absent = converter.update_project_settings()
        self.assertEqual(
            absent,
            ProjectOperationResult("skipped", "No GameMaker main or target-platform options metadata was found."),
        )
        converter.project_manifest = GameMakerProjectManifest(
            "Injected", str(self.yyp), options=(ProjectOption("MAIN", "option_game_speed", 33),)
        )
        self.assertEqual(converter.update_project_settings(), ProjectOperationResult("completed"))
        self.assertIn("run/max_fps=33", self.project.read_text(encoding="utf-8"))

    def test_cancellation_precedes_validation_and_output_lookup(self) -> None:
        converter = self.settings()
        converter.conversion_running = lambda: False
        self.options.write_bytes(b"\xff")
        self.project.unlink()
        with patch.object(converter, "_project_options_source_result") as validate:
            self.assertEqual(
                converter.update_project_settings(), ProjectOperationResult("skipped", "Conversion was cancelled.")
            )
        validate.assert_not_called()
        self.assertEqual(self.logs, [])

    def test_second_cancellation_preserves_original_project(self) -> None:
        converter = self.settings()
        before = self.project.read_bytes()
        with patch.object(converter, "conversion_running", side_effect=[True, False]):
            result = converter.update_project_settings()
        self.assertEqual(result, ProjectOperationResult("skipped", "Conversion was cancelled."))
        self.assertEqual(self.project.read_bytes(), before)
        self.assertEqual(self.logs, [])

    def test_audio_source_uses_live_raw_shape_and_cached_names(self) -> None:
        converter = self.settings()
        raw: JsonObject = {}
        converter.project_manifest = GameMakerProjectManifest("Injected", str(self.yyp), raw_data=raw)
        self.assertEqual(converter.generate_audio_bus_layout().reason, "GameMaker AudioGroups metadata is unavailable.")
        raw["AudioGroups"] = None
        self.assertEqual(converter.generate_audio_bus_layout().reason, "GameMaker AudioGroups metadata is malformed.")
        raw["AudioGroups"] = [{"name": "new_on_disk"}]
        self.assertEqual(
            converter.generate_audio_bus_layout().reason,
            "GameMaker AudioGroups metadata does not contain valid group names.",
        )
        raw["AudioGroups"] = []
        self.assertEqual(converter.generate_audio_bus_layout(), ProjectOperationResult("completed"))
        converter.project_manifest = GameMakerProjectManifest("Missing", None, raw_data=raw)
        self.assertEqual(
            converter.generate_audio_bus_layout().reason,
            "GameMaker project metadata is unavailable because no .yyp was found.",
        )

    def test_registry_audio_gain_and_load_are_live_and_deferred(self) -> None:
        raw: JsonObject = {"loaded": False, "preload": True, "gain": "0.25"}
        group = ProjectAudioGroup("music", raw_data=raw)
        converter = AssetRegistryConverter(str(self.gm), str(self.out), log_callback=self.logs.append)
        converter.project_manifest = GameMakerProjectManifest("Injected", str(self.yyp), audio_groups=(group,))
        initial = converter.build_group_registries(())[1]
        self.assertEqual(
            [(item["name"], item["loaded"], item["gain"]) for item in initial],
            [("audiogroup_default", True, 1.0), ("music", False, 0.25)],
        )
        raw.update({"loaded": 1, "gain": "bad"})
        changed = converter.build_group_registries(())[1]
        self.assertEqual((changed[1]["loaded"], changed[1]["gain"]), (True, 1.0))
        raw["gain"] = 10**400
        with self.assertRaises(OverflowError):
            converter.build_group_registries(())[1]

    def test_registry_duplicate_group_replacement_and_default_policy(self) -> None:
        converter = AssetRegistryConverter(str(self.gm), str(self.out), log_callback=self.logs.append)
        converter.project_manifest = GameMakerProjectManifest(
            "Injected",
            str(self.yyp),
            audio_groups=(
                ProjectAudioGroup("z", raw_data={"gain": 2}),
                ProjectAudioGroup("audiogroup_default", raw_data={"loaded": False}),
                ProjectAudioGroup("z", raw_data={"gain": 3}),
                ProjectAudioGroup("", raw_data={"gain": 10**400}),
            ),
        )
        groups = converter.build_group_registries(())[1]
        self.assertEqual(
            [(item["name"], item["loaded"], item["gain"]) for item in groups],
            [("audiogroup_default", True, 1.0), ("z", False, 3.0)],
        )
