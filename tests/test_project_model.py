import ast
import dataclasses
import inspect
import math
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion import project_manifest, project_model
from src.conversion.gamemaker_json import GameMakerJsonDocument, parse_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectAudioGroup,
    ProjectConfigOverride,
    ProjectConfiguration,
    ProjectIncludedFile,
    ProjectOption,
    ProjectResourceReference,
    ProjectTextureGroup,
    load_gamemaker_project_manifest,
    parse_project_options_document,
)
from src.conversion.project_model import ProjectOptionsMetadata, normalize_project_manifest_path


class TestProjectModel(unittest.TestCase):
    def test_eight_record_exports_are_direct_canonical_identities(self) -> None:
        names = {
            "GameMakerProjectManifest",
            "ProjectAudioGroup",
            "ProjectConfigOverride",
            "ProjectConfiguration",
            "ProjectIncludedFile",
            "ProjectOption",
            "ProjectResourceReference",
            "ProjectTextureGroup",
        }
        for name in names:
            with self.subTest(record=name):
                cls = getattr(project_manifest, name)
                self.assertIs(cls, getattr(project_model, name))
                self.assertEqual(cls.__module__, "src.conversion.project_model")
        tree = ast.parse(inspect.getsource(project_manifest))
        aliases = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "src.conversion.project_model"
            for alias in node.names
            if alias.asname == alias.name
        }
        self.assertEqual(aliases, names)
        self.assertFalse(names & {node.name for node in tree.body if isinstance(node, ast.ClassDef)})
        self.assertFalse(hasattr(project_manifest, "_empty_json_dict"))
        self.assertFalse(hasattr(project_manifest, "_normalize_project_path"))
        self.assertFalse(hasattr(project_manifest, "_read_lenient_json_file"))

    def test_model_dependency_and_recursive_annotations_are_explicit(self) -> None:
        model_tree = ast.parse(inspect.getsource(project_model))
        dependencies = {node.module for node in ast.walk(model_tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(
            dependencies,
            {"__future__", "dataclasses", "typing", "src.conversion.diagnostic_models", "src.conversion.json_values"},
        )
        self.assertIs(project_model.JsonValue, JsonValue)
        self.assertIs(project_model.JsonObject, JsonObject)
        self.assertEqual(inspect.get_annotations(ProjectOption)["value"], "JsonValue")
        self.assertEqual(inspect.get_annotations(ProjectConfigOverride)["value"], "JsonValue")
        self.assertEqual(inspect.get_annotations(GameMakerProjectManifest)["raw_data"], "JsonObject")
        parser_tree = ast.parse(inspect.getsource(project_manifest))
        self.assertFalse(
            any(
                isinstance(node, ast.Name) and node.id in {"JsonDict", "JsonList", "cast"}
                for node in ast.walk(parser_tree)
            )
        )
        self.assertEqual(normalize_project_manifest_path(" scripts\\a\\a.yy "), "scripts/a/a.yy")
        self.assertEqual(normalize_project_manifest_path(None), "")

    def test_manifest_positional_matching_and_metadata_comparison_contract(self) -> None:
        raw: JsonObject = {}
        positional = ("P", None, "GMProject", "1", (), (), (), (), (), (), (), raw, "2026")
        manifest = GameMakerProjectManifest(*positional)
        metadata = ProjectOptionsMetadata("main", "virtual.yy", "{}", {}, ())
        with_metadata = dataclasses.replace(manifest, option_files=(metadata,))
        self.assertEqual(manifest, with_metadata)
        self.assertEqual(repr(manifest), repr(with_metadata))
        self.assertEqual(
            GameMakerProjectManifest.__match_args__,
            (
                "project_name",
                "yyp_path",
                "resource_type",
                "resource_version",
                "resources",
                "configurations",
                "options",
                "texture_groups",
                "audio_groups",
                "included_files",
                "diagnostics",
                "raw_data",
                "ide_version",
            ),
        )
        self.assertEqual(
            inspect.signature(GameMakerProjectManifest).parameters["option_files"].kind, inspect.Parameter.KEYWORD_ONLY
        )
        match manifest:
            case GameMakerProjectManifest("P", None):
                pass
            case _:
                self.fail("Existing positional class matching changed")
        field = dataclasses.fields(manifest)[-1]
        self.assertEqual(
            (field.name, field.default, field.kw_only, field.compare, field.repr),
            ("option_files", (), True, False, False),
        )
        self.assertEqual(len(dataclasses.astuple(with_metadata)), 14)
        self.assertEqual(dataclasses.asdict(with_metadata)["option_files"][0]["source"], "{}")
        self.assertNotIn("option_files", repr(with_metadata))
        restored: object = pickle.loads(pickle.dumps(with_metadata))
        assert isinstance(restored, GameMakerProjectManifest)
        self.assertIs(type(restored), GameMakerProjectManifest)
        self.assertEqual(restored, with_metadata)
        self.assertEqual(restored.option_files, with_metadata.option_files)

    def test_options_metadata_preserves_source_raw_and_nested_value_identity(self) -> None:
        source = '{\n"note":"option_first",\n"option_first":[1,{"nested":null}],\n"OPTION_ignored":2,\n"option_second":false,\n}'
        document = parse_gamemaker_json(source, source_path=r"virtual\options_main.yy")
        with patch("builtins.open", side_effect=AssertionError("Pure options parser must not perform I/O")):
            metadata = parse_project_options_document(document, platform="MaIn")
        assert metadata is not None and isinstance(document.value, dict)
        self.assertEqual(
            [field.name for field in dataclasses.fields(metadata)],
            ["platform", "source_path", "source", "raw_data", "options"],
        )
        self.assertEqual(
            (metadata.platform, metadata.source_path, metadata.source), ("MaIn", document.source_path, source)
        )
        self.assertIs(metadata.raw_data, document.value)
        self.assertEqual([option.key for option in metadata.options], ["option_first", "option_second"])
        self.assertIs(metadata.options[0].value, document.value["option_first"])
        self.assertEqual([option.source.line for option in metadata.options if option.source], [2, 5])
        self.assertEqual(
            [option.source.field_path for option in metadata.options if option.source],
            ["option_first", "option_second"],
        )
        document.value["option_first"] = "replaced"
        self.assertEqual(metadata.options[0].value, [1, {"nested": None}])
        self.assertEqual(metadata.raw_data["option_first"], "replaced")

    def test_options_parser_distinguishes_empty_and_nonobject_documents(self) -> None:
        for source in ("null", "[]", "42", '"text"', "true"):
            with self.subTest(source=source):
                self.assertIsNone(parse_project_options_document(parse_gamemaker_json(source), platform="main"))
        roots: tuple[JsonObject, ...] = ({}, {"unknown": []})
        for raw in roots:
            with self.subTest(raw=raw):
                metadata = parse_project_options_document(
                    GameMakerJsonDocument("p", "original", raw), platform="unknown"
                )
                assert metadata is not None
                self.assertIs(metadata.raw_data, raw)
                self.assertEqual(metadata.options, ())

    def test_audio_properties_keep_first_bool_and_numeric_coercion_rules(self) -> None:
        load_rows: tuple[tuple[JsonObject, bool], ...] = (
            ({}, False),
            ({"loaded": False, "preload": True}, False),
            ({"loaded": 1, "preload": False, "loadOnStartup": True}, False),
            ({"loadOnStartup": True}, True),
        )
        for raw, expected in load_rows:
            with self.subTest(raw=raw):
                self.assertEqual(ProjectAudioGroup("music", raw_data=raw).initial_loaded, expected)
                self.assertTrue(ProjectAudioGroup("audiogroup_default", raw_data=raw).initial_loaded)
                self.assertTrue(ProjectAudioGroup("", raw_data=raw).initial_loaded)
        gain_rows: tuple[tuple[JsonValue, float], ...] = (
            (None, 1.0),
            ([], 1.0),
            ({}, 1.0),
            ("bad", 1.0),
            ("0.5", 0.5),
            (False, 0.0),
            (True, 1.0),
            (-2, -2.0),
            (float("inf"), float("inf")),
        )
        for value, expected_gain in gain_rows:
            with self.subTest(value=value):
                self.assertEqual(ProjectAudioGroup("music", raw_data={"gain": value}).gain, expected_gain)
        self.assertTrue(math.isnan(ProjectAudioGroup("music", raw_data={"gain": float("nan")}).gain))
        group = ProjectAudioGroup("music", raw_data={"gain": 10**400})
        with self.assertRaises(OverflowError):
            _ = group.gain

    def test_audio_state_retains_live_shape_and_cached_name_policy(self) -> None:
        raw: JsonObject = {}
        manifest = GameMakerProjectManifest("P", None, raw_data=raw, audio_groups=(ProjectAudioGroup("cached"),))
        self.assertEqual(manifest.audio_groups_state, "missing")
        rows: tuple[tuple[JsonValue, str], ...] = (
            (None, "malformed"),
            (1, "malformed"),
            ([], "available"),
            ({}, "available"),
            ([{}], "available"),
        )
        for value, expected in rows:
            with self.subTest(value=value):
                raw["AudioGroups"] = value
                self.assertEqual(manifest.audio_groups_state, expected)
        unnamed = dataclasses.replace(manifest, audio_groups=())
        self.assertEqual(unnamed.audio_groups_state, "unnamed")

    def test_existing_record_defaults_and_frozen_fields(self) -> None:
        records = (
            ProjectResourceReference("u", "n", "scripts/n/n.yy", "scripts", "GMScript", 3),
            ProjectConfigOverride("cfg", "field", {"nested": []}),
            ProjectConfiguration("cfg"),
            ProjectOption("main", "option_speed", {"nested": []}),
            ProjectTextureGroup("textures"),
            ProjectAudioGroup("audio"),
            ProjectIncludedFile("data.txt", "datafiles/data.txt"),
            GameMakerProjectManifest("Project", "Project.yyp"),
            ProjectOptionsMetadata("main", "virtual.yy", "{}", {}, ()),
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(record, dataclasses.fields(record)[0].name, "changed")
        self.assertEqual(records[0].tags, ())
        self.assertIsNone(records[1].source)
        self.assertEqual(records[2].overrides, ())
        self.assertFalse(records[4].is_dynamic)
        self.assertEqual(records[5].targets, ())
        self.assertEqual(records[7].ide_version, "")

    def test_empty_factories_are_independent_and_raw_values_stay_live(self) -> None:
        first = (
            ProjectConfiguration("c"),
            ProjectTextureGroup("t"),
            ProjectAudioGroup("a"),
            ProjectIncludedFile("f", "f"),
            GameMakerProjectManifest("p", None),
        )
        second = (
            ProjectConfiguration("c"),
            ProjectTextureGroup("t"),
            ProjectAudioGroup("a"),
            ProjectIncludedFile("f", "f"),
            GameMakerProjectManifest("p", None),
        )
        for left, right in zip(first, second, strict=True):
            with self.subTest(record=type(left).__name__):
                self.assertEqual(left, right)
                self.assertIsNot(left.raw_data, right.raw_data)
                left.raw_data["unknown"] = [1, None]
                self.assertNotEqual(left, right)
                self.assertEqual(right.raw_data, {})
                with self.assertRaises(TypeError):
                    hash(left)
        nested: JsonObject = {"value": []}
        option = ProjectOption("main", "option_data", nested)
        override = ProjectConfigOverride("Default", "options", nested)
        self.assertIs(option.value, nested)
        self.assertIs(override.value, nested)
        nested["changed"] = True
        self.assertEqual(option.value, {"value": [], "changed": True})

    def test_queries_keep_order_case_and_original_record_identities(self) -> None:
        first = ProjectOption("main", "option_speed", 60)
        second = ProjectOption("WINDOWS", "OPTION_SPEED", 120)
        last = ProjectOption("windows", "option_speed", 144)
        resource = ProjectResourceReference("uuid", "Scr", "scripts/Scr/Scr.yy", "scripts", "GMScript", 3)
        manifest = GameMakerProjectManifest("P", None, options=(first, second, last), resources=(resource, resource))
        self.assertIs(manifest.get_option("OPTION_SPEED"), last)
        self.assertIs(manifest.get_option("OPTION_SPEED", "MAIN"), first)
        self.assertEqual(list(manifest.options_for_platform("WINDOWS")), ["option_speed", "OPTION_SPEED"])
        self.assertIs(manifest.options_for_platform("windows")["option_speed"], last)
        self.assertEqual(
            manifest.find_resources(
                path=" scripts\\Scr\\Scr.yy ", name="scr", kind="SCRIPTS", resource_type="gmscript"
            ),
            (resource, resource),
        )
        self.assertEqual(manifest.find_resources(uuid="UUID"), ())
        self.assertEqual(manifest.find_resources(path="scripts/scr/scr.yy"), ())

    def test_loader_keeps_nested_raw_references_and_snapshot_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "P.yyp").write_text(
                '{"name":"P","AudioGroups":[{"name":"music"}],"Configs":[{"name":"Default","overrides":{"a":[1]}}]}',
                encoding="utf-8",
            )
            manifest = load_gamemaker_project_manifest(directory)
        groups = manifest.raw_data["AudioGroups"]
        assert isinstance(groups, list) and isinstance(groups[0], dict)
        self.assertIs(manifest.audio_groups[0].raw_data, groups[0])
        groups[0]["name"] = "replaced"
        self.assertEqual(manifest.audio_group_names(), ["music"])
        configs = manifest.raw_data["Configs"]
        assert isinstance(configs, list) and isinstance(configs[0], dict)
        raw_overrides = configs[0]["overrides"]
        assert isinstance(raw_overrides, dict)
        self.assertIs(manifest.configurations[0].raw_data, configs[0])
        self.assertIs(manifest.configurations[0].overrides[0].value, raw_overrides["a"])
