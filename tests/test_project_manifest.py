import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields
from typing import get_type_hints
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.json_values import JsonArray, JsonObject, JsonValue
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectAudioGroup,
    ProjectConfigOverride,
    ProjectConfiguration,
    ProjectIncludedFile,
    ProjectManifestDiagnostic,
    ProjectOption,
    ProjectResourceReference,
    ProjectSourceLocation,
    ProjectTextureGroup,
    load_gamemaker_project_manifest,
    unsupported_project_option_diagnostics,
)


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


class TestGameMakerProjectManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)

    def test_parses_manifest_graph_options_configs_and_groups(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Manifest.yyp"),
            """\
{
  "$GMProject": "",
  "%Name": "ManifestFixture",
  "resourceType": "GMProject",
  "resourceVersion": "1.7",
  "MetaData": {"IDEVersion": "2026.0.1.123"},
  "resources": [
    {"id": {"id": "uuid-sprite", "name": "s_player", "path": "sprites/s_player/s_player.yy"}, "resourceType": "GMSprite", "order": 2, "tags": ["hero", "combat"]},
    {"Key": "uuid-room", "Value": {"id": "uuid-room", "name": "r_main", "resourcePath": "rooms/r_main/r_main.yy", "resourceType": "GMRoom", "order": 1}}
  ],
  "Configs": [
    {"name": "Default", "options": {"option_game_speed": 60}, "children": [
      {"name": "Mobile", "parent": "Default", "overrides": {"AudioGroups": {"music": "audiogroup_mobile"}}}
    ]}
  ],
  "ConfigValues": {"Mobile": {"options": {"option_android_version": "2.0.0"}}},
  "TextureGroups": [
    {"%Name": "texturegroup_world", "parentGroup": {"name": "Default"}, "isDynamic": true, "dynamicPath": "tg/world", "copyToWindows": true}
  ],
  "AudioGroups": [
    {"%Name": "audiogroup_default"},
    {"%Name": "audiogroup_music", "targets": ["windows", "android"]}
  ],
  "IncludedFiles": [
    {"name": "license.txt", "path": "datafiles/license.txt", "copyToWindows": true}
  ],
  "FutureManifestThing": {"keep": true}
}
""",
        )
        _write_file(
            os.path.join(self.gm_dir, "options", "main", "options_main.yy"),
            '{"option_game_speed":144,}',
        )
        _write_file(
            os.path.join(self.gm_dir, "options", "windows", "options_windows.yy"),
            '{"option_windows_version":"1.2.3","option_windows_resize_window":true,}',
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir, target_platform="windows")

        self.assertEqual(manifest.project_name, "ManifestFixture")
        self.assertEqual(manifest.resource_version, "1.7")
        self.assertEqual(manifest.ide_version, "2026.0.1.123")
        sprite = manifest.find_resources(uuid="uuid-sprite")[0]
        self.assertEqual(sprite.name, "s_player")
        self.assertEqual(sprite.kind, "sprites")
        self.assertEqual(sprite.resource_type, "GMSprite")
        self.assertEqual(sprite.tags, ("hero", "combat"))
        assert sprite.source is not None
        self.assertEqual(sprite.source.path, os.path.join(self.gm_dir, "Manifest.yyp"))
        self.assertGreater(sprite.source.line, 0)
        self.assertEqual(manifest.find_resources(path="rooms\\r_main\\r_main.yy")[0].uuid, "uuid-room")
        self.assertEqual(manifest.find_resources(resource_type="GMRoom")[0].name, "r_main")
        game_speed = manifest.get_option("option_game_speed", "main")
        windows_version = manifest.get_option("option_windows_version", "windows")
        assert game_speed is not None
        assert windows_version is not None
        self.assertEqual(game_speed.value, 144)
        self.assertEqual(windows_version.value, "1.2.3")
        self.assertEqual(manifest.audio_group_names(), ["audiogroup_default", "audiogroup_music"])
        self.assertEqual(manifest.texture_groups[0].name, "texturegroup_world")
        self.assertTrue(manifest.texture_groups[0].is_dynamic)
        self.assertEqual(manifest.texture_groups[0].targets, ("windows",))
        self.assertEqual(manifest.included_files[0].path, "datafiles/license.txt")
        mobile = next(config for config in manifest.configurations if config.name == "Mobile")
        self.assertEqual(mobile.parent, "Default")
        self.assertTrue(any("AudioGroups" in override.field_path for override in mobile.overrides))
        self.assertTrue(any("option_android_version" in override.field_path for override in mobile.overrides))
        self.assertTrue(
            any(diagnostic.code == "GM2GD-PROJECT-UNKNOWN-FIELD" for diagnostic in manifest.diagnostics)
        )

        unsupported = unsupported_project_option_diagnostics(
            manifest,
            target_platform="windows",
            supported_keys={"option_game_speed", "option_windows_resize_window"},
        )
        self.assertTrue(unsupported)
        self.assertTrue(all(diagnostic.severity == "info" for diagnostic in unsupported))

    def test_reports_duplicate_resource_conflicts_without_rejecting_manifest(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Conflicts.yyp"),
            """\
{
  "%Name": "Conflicts",
  "resourceType": "GMProject",
  "resources": [
    {"id": {"id": "duplicate-id", "name": "s_player", "path": "sprites/s_player/s_player.yy"}, "resourceType": "GMSprite"},
    {"id": {"id": "duplicate-id", "name": "s_player", "path": "sprites/s_player_hd/s_player_hd.yy"}, "resourceType": "GMSprite"}
  ]
}
""",
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertEqual(len(manifest.resources), 2)
        self.assertTrue(
            any(diagnostic.code == "GM2GD-PROJECT-RESOURCE-CONFLICT" for diagnostic in manifest.diagnostics)
        )

    def test_invalid_resource_path_kind_takes_precedence_over_declared_type(
        self,
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "ConflictingKind.yyp"),
            json.dumps(
                {
                    "resources": [
                        {
                            "id": {
                                "name": "s_conflicting",
                                "path": "sprites/../../outside.yy",
                            },
                            "resourceType": "GMObject",
                        }
                    ],
                    "resourceType": "GMProject",
                }
            ),
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir)

        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "s_conflicting")
        self.assertEqual(rejected[0].resource_kind, "sprites")
        self.assertEqual(rejected[0].resource_type, "GMSprite")
        assert rejected[0].source is not None
        self.assertEqual(
            rejected[0].source.field_path,
            "resources[0].id.path",
        )

    def test_invalid_resource_paths_report_missing_and_actual_legacy_fields(
        self,
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "MalformedPaths.yyp"),
            json.dumps(
                {
                    "resources": [
                        {
                            "id": {"name": "s_missing"},
                            "resourceType": "GMSprite",
                        },
                        {
                            "Key": "room-null",
                            "Value": {
                                "name": "r_null",
                                "resourcePath": None,
                                "resourceType": "GMRoom",
                            },
                        },
                        {
                            "Key": "script-empty",
                            "Value": {
                                "name": "scr_empty",
                                "resource_path": "",
                                "resourceType": "GMScript",
                            },
                        },
                        {
                            "name": "snd_numeric",
                            "path": 7,
                            "resourceType": "GMSound",
                        },
                    ],
                    "resourceType": "GMProject",
                }
            ),
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir)

        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 4, rejected)
        self.assertEqual(
            {
                diagnostic.source.field_path
                for diagnostic in rejected
                if diagnostic.source is not None
            },
            {
                "resources[0].id.path",
                "resources[1].Value.resourcePath",
                "resources[2].Value.resource_path",
                "resources[3].path",
            },
        )
        self.assertIn("<missing>", rejected[0].message)
        self.assertEqual(manifest.resources, ())

    def test_duplicate_rejected_resource_paths_have_entry_specific_lines(
        self,
    ) -> None:
        _write_file(
            os.path.join(self.gm_dir, "DuplicateRejectedPaths.yyp"),
            "{\n"
            '  "resources": [\n'
            '    {"id":{"name":"s_first","path":"../../outside.yy"}},\n'
            '    {"id":{"name":"s_second","path":"../../outside.yy"}}\n'
            "  ]\n"
            "}\n",
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir)

        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 2, rejected)
        self.assertEqual(
            [
                diagnostic.source.line
                for diagnostic in rejected
                if diagnostic.source is not None
            ],
            [3, 4],
        )

    def test_skips_project_yyp_symlink_that_resolves_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yyp = os.path.join(outside_dir, "Outside.yyp")
            _write_file(
                outside_yyp,
                '{"%Name":"Outside","resourceType":"GMProject"}',
            )
            try:
                os.symlink(
                    outside_yyp,
                    os.path.join(self.gm_dir, "AOutside.yyp"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")
            _write_file(
                os.path.join(self.gm_dir, "BInside.yyp"),
                '{"%Name":"Inside","resourceType":"GMProject"}',
            )

            manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertEqual(manifest.project_name, "Inside")
        self.assertEqual(manifest.yyp_path, os.path.join(self.gm_dir, "BInside.yyp"))
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        assert rejected[0].source is not None
        self.assertEqual(
            rejected[0].source.path,
            os.path.join(self.gm_dir, "AOutside.yyp"),
        )
        self.assertEqual(rejected[0].source.field_path, "AOutside.yyp")

    def test_skips_non_file_yyp_candidate_with_source_diagnostic(self) -> None:
        invalid_yyp = os.path.join(self.gm_dir, "AInvalid.yyp")
        os.makedirs(invalid_yyp)
        _write_file(
            os.path.join(self.gm_dir, "BInside.yyp"),
            '{"%Name":"Inside","resourceType":"GMProject"}',
        )

        manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertEqual(manifest.project_name, "Inside")
        self.assertEqual(
            manifest.yyp_path,
            os.path.join(self.gm_dir, "BInside.yyp"),
        )
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.path, invalid_yyp)
        self.assertEqual(rejected[0].source.field_path, "AInvalid.yyp")
        self.assertIn("not a regular .yyp file", rejected[0].message)

    def test_skips_project_option_symlink_that_resolves_outside_project(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Manifest.yyp"),
            '{"%Name":"Inside","resourceType":"GMProject"}',
        )
        _write_file(
            os.path.join(self.gm_dir, "options", "main", "options_main.yy"),
            '{"option_game_speed":60}',
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_options = os.path.join(outside_dir, "options_windows.yy")
            _write_file(outside_options, '{"option_windows_version":"outside"}')
            linked_options = os.path.join(
                self.gm_dir,
                "options",
                "windows",
                "options_windows.yy",
            )
            os.makedirs(os.path.dirname(linked_options))
            try:
                os.symlink(outside_options, linked_options)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertIsNotNone(manifest.get_option("option_game_speed", "main"))
        self.assertIsNone(manifest.get_option("option_windows_version", "windows"))
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.path, linked_options)
        self.assertEqual(
            rejected[0].source.field_path,
            "options/windows/options_windows.yy",
        )

    def test_skips_project_option_symlink_to_contained_wrong_family(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Manifest.yyp"),
            '{"%Name":"Inside","resourceType":"GMProject"}',
        )
        _write_file(
            os.path.join(self.gm_dir, "options", "main", "options_main.yy"),
            '{"option_game_speed":60}',
        )
        wrong_family_target = os.path.join(
            self.gm_dir,
            "sprites",
            "s_options_decoy",
            "s_options_decoy.yy",
        )
        _write_file(
            wrong_family_target,
            '{"option_windows_version":"wrong-family"}',
        )
        linked_options = os.path.join(
            self.gm_dir,
            "options",
            "windows",
            "options_windows.yy",
        )
        os.makedirs(os.path.dirname(linked_options), exist_ok=True)
        try:
            os.symlink(wrong_family_target, linked_options)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        with patch("builtins.open", wraps=open) as tracked_open:
            manifest = load_gamemaker_project_manifest(self.gm_dir)

        game_speed = manifest.get_option("option_game_speed", "main")
        self.assertIsNotNone(game_speed)
        assert game_speed is not None
        self.assertEqual(game_speed.value, 60)
        self.assertIsNone(
            manifest.get_option("option_windows_version", "windows")
        )
        opened_paths = {
            os.path.realpath(call.args[0])
            for call in tracked_open.call_args_list
            if call.args and isinstance(call.args[0], str)
        }
        self.assertNotIn(os.path.realpath(wrong_family_target), opened_paths)
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.path, linked_options)
        self.assertEqual(
            rejected[0].source.field_path,
            "options/windows/options_windows.yy",
        )

    def test_skips_project_option_directory_symlink_with_source_diagnostic(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Manifest.yyp"),
            '{"%Name":"Inside","resourceType":"GMProject"}',
        )
        _write_file(
            os.path.join(self.gm_dir, "options", "main", "options_main.yy"),
            '{"option_game_speed":60}',
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            _write_file(
                os.path.join(outside_dir, "options_linux.yy"),
                '{"option_linux_display_name":"outside"}',
            )
            linked_directory = os.path.join(self.gm_dir, "options", "linux")
            try:
                os.symlink(outside_dir, linked_directory)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertIsNotNone(manifest.get_option("option_game_speed", "main"))
        self.assertIsNone(manifest.get_option("option_linux_display_name", "linux"))
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.path, linked_directory)
        self.assertEqual(rejected[0].source.field_path, "options/linux")

    def test_skips_project_option_root_symlink_with_source_diagnostic(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Manifest.yyp"),
            '{"%Name":"Inside","resourceType":"GMProject"}',
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            _write_file(
                os.path.join(outside_dir, "main", "options_main.yy"),
                '{"option_game_speed":999}',
            )
            linked_root = os.path.join(self.gm_dir, "options")
            try:
                os.symlink(outside_dir, linked_root)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            manifest = load_gamemaker_project_manifest(self.gm_dir)

        self.assertIsNone(manifest.get_option("option_game_speed", "main"))
        rejected = [
            diagnostic
            for diagnostic in manifest.diagnostics
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.path, linked_root)
        self.assertEqual(rejected[0].source.field_path, "options")

    def test_ide_version_is_empty_when_metadata_is_absent_or_malformed(self) -> None:
        yyp_path = os.path.join(self.gm_dir, "VersionFallback.yyp")
        cases: tuple[dict[str, object], ...] = (
            {"%Name": "MissingMetadata", "resourceType": "GMProject"},
            {"%Name": "MalformedMetadata", "resourceType": "GMProject", "MetaData": []},
            {
                "%Name": "MalformedIDEVersion",
                "resourceType": "GMProject",
                "MetaData": {"IDEVersion": 2026},
            },
        )

        for yyp_data in cases:
            with self.subTest(project_name=yyp_data["%Name"]):
                _write_file(yyp_path, json.dumps(yyp_data))
                manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual(manifest.ide_version, "")


    def test_model_owners_constructor_order_frozen_defaults_and_json_annotations(self) -> None:
        instances_and_fields = (
            (ProjectSourceLocation("source.yyp", 2), ("path", "line", "field_path")),
            (
                ProjectManifestDiagnostic("warning", "code", "message"),
                ("severity", "code", "message", "source", "resource", "resource_type", "resource_kind"),
            ),
            (
                ProjectResourceReference("id", "s", "sprites/s/s.yy", "sprites", "GMSprite", 0),
                ("uuid", "name", "path", "kind", "resource_type", "order", "tags", "source"),
            ),
            (ProjectConfigOverride("Default", "values.x", None), ("configuration", "field_path", "value", "source")),
            (ProjectConfiguration("Default"), ("name", "parent", "overrides", "source", "raw_data")),
            (ProjectOption("main", "option_x", None), ("platform", "key", "value", "source")),
            (
                ProjectTextureGroup("texture"),
                ("name", "parent", "is_dynamic", "dynamic_path", "targets", "source", "raw_data"),
            ),
            (ProjectAudioGroup("audio"), ("name", "targets", "source", "raw_data")),
            (ProjectIncludedFile("data.txt", "datafiles/data.txt"), ("name", "path", "targets", "source", "raw_data")),
            (
                GameMakerProjectManifest("Project", None),
                (
                    "project_name", "yyp_path", "resource_type", "resource_version", "resources", "configurations",
                    "options", "texture_groups", "audio_groups", "included_files", "diagnostics", "raw_data", "ide_version",
                ),
            ),
        )
        for instance, expected_fields in instances_and_fields:
            model = type(instance)
            with self.subTest(model=model.__name__):
                self.assertEqual(model.__module__, "src.conversion.project_manifest")
                self.assertEqual(model.__qualname__, model.__name__)
                self.assertEqual(tuple(item.name for item in fields(instance)), expected_fields)
                self.assertEqual(tuple(inspect.signature(model).parameters), expected_fields)
                with self.assertRaises(FrozenInstanceError):
                    setattr(instance, expected_fields[0], "changed")
        raw_models = (
            ProjectConfiguration, ProjectTextureGroup, ProjectAudioGroup, ProjectIncludedFile, GameMakerProjectManifest,
        )
        for model in raw_models:
            with self.subTest(annotation=model.__name__):
                self.assertIs(get_type_hints(model)["raw_data"], JsonObject)
        self.assertIs(get_type_hints(ProjectConfigOverride)["value"], JsonValue)
        self.assertIs(get_type_hints(ProjectOption)["value"], JsonValue)
        default_pairs = (
            (ProjectConfiguration("Default"), ProjectConfiguration("Default")),
            (ProjectTextureGroup("texture"), ProjectTextureGroup("texture")),
            (ProjectAudioGroup("audio"), ProjectAudioGroup("audio")),
            (ProjectIncludedFile("data", "datafiles/data"), ProjectIncludedFile("data", "datafiles/data")),
            (GameMakerProjectManifest("Project", None), GameMakerProjectManifest("Project", None)),
        )
        for first, second in default_pairs:
            with self.subTest(default=type(first).__name__):
                self.assertEqual(first, second)
                self.assertEqual(first.raw_data, {})
                self.assertIsNot(first.raw_data, second.raw_data)
        configuration = ProjectConfiguration("Default")
        self.assertEqual(configuration.parent, "")
        self.assertEqual(configuration.overrides, ())
        self.assertIsNone(configuration.source)
        self.assertEqual(
            repr(ProjectOption("main", "option_x", None)),
            "ProjectOption(platform='main', key='option_x', value=None, source=None)",
        )

    def test_manifest_keeps_all_raw_model_and_unknown_nested_value_references(self) -> None:
        config_value: JsonArray = [1, None, {"keep": True}]
        config: JsonObject = {"name": "Default", "values": {"unknown": config_value}}
        texture: JsonObject = {"name": "texture"}
        audio: JsonObject = {"name": "audio"}
        included: JsonObject = {"name": "data.txt", "path": "datafiles/data.txt"}
        unknown: JsonArray = [1, {"nested": [False, None]}]
        option_value: JsonArray = [None, {"unknown": [1, True]}]
        data: JsonObject = {
            "%Name": "References", "configs": [config], "TextureGroups": [texture],
            "AudioGroups": [audio], "IncludedFiles": [included], "Unknown": unknown,
        }
        options: JsonObject = {"option_future": option_value}
        _write_file(os.path.join(self.gm_dir, "References.yyp"), "{}")
        _write_file(os.path.join(self.gm_dir, "options", "main", "options_main.yy"), "{}")
        with patch("src.conversion.gamemaker_json.json.loads", side_effect=[data, options]):
            manifest = load_gamemaker_project_manifest(self.gm_dir)
        self.assertIs(manifest.raw_data, data)
        self.assertIs(manifest.configurations[0].raw_data, config)
        self.assertIs(manifest.texture_groups[0].raw_data, texture)
        self.assertIs(manifest.audio_groups[0].raw_data, audio)
        self.assertIs(manifest.included_files[0].raw_data, included)
        self.assertIs(manifest.raw_data["Unknown"], unknown)
        self.assertIs(manifest.options[0].value, option_value)
        self.assertIs(manifest.configurations[0].overrides[0].value, config_value)
        self.assertEqual([item.code for item in manifest.diagnostics], ["GM2GD-PROJECT-UNKNOWN-FIELD"])
        self.assertEqual(tuple(manifest.raw_data), tuple(data))

    def test_deep_unknown_native_metadata_is_validated_without_copying_or_recursive_visit(self) -> None:
        leaf: JsonObject = {"keep": [None, True]}
        nested: JsonObject = leaf
        for _ in range(1600):
            nested = {"child": nested}
        data: JsonObject = {"%Name": "Deep", "Unknown": nested}
        _write_file(os.path.join(self.gm_dir, "Deep.yyp"), "{}")
        with patch("src.conversion.gamemaker_json.json.loads", return_value=data):
            manifest = load_gamemaker_project_manifest(self.gm_dir)
        self.assertIs(manifest.raw_data, data)
        current = manifest.raw_data["Unknown"]
        for _ in range(1600):
            assert isinstance(current, dict)
            current = current["child"]
        self.assertIs(current, leaf)
        self.assertEqual([item.code for item in manifest.diagnostics], ["GM2GD-PROJECT-UNKNOWN-FIELD"])

    def test_config_aliases_sorting_null_arrays_and_legacy_parent_selection(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Configs.yyp"),
            json.dumps({
                "configs": None,
                "Configs": [
                    {"name": "Z", "parent": "", "parentConfig": {"%Name": "Parent"},
                     "values": {"null": None, "array": [1, None, {"keep": True}], "nested": {"leaf": False}},
                     "children": [None, 2, {"%Name": "A", "overrides": ["one", None]}]},
                    "ignored", {"name": 7},
                ],
                "ConfigValues": {"Z": {"options": {"last": "value"}}, "A": None, "M": [42, None]},
            }),
        )
        manifest = load_gamemaker_project_manifest(self.gm_dir)
        self.assertEqual([item.name for item in manifest.configurations], ["A", "M", "Z"])
        a, m, z = manifest.configurations
        self.assertEqual(z.parent, "Parent")
        self.assertEqual([item.field_path for item in z.overrides], [
            "values.null", "values.array", "values.nested.leaf", "ConfigValues.options.last",
        ])
        self.assertEqual([item.value for item in z.overrides], [None, [1, None, {"keep": True}], False, "value"])
        self.assertEqual([item.value for item in a.overrides], [["one", None], None])
        self.assertEqual([item.value for item in m.overrides], [[42, None]])
        self.assertEqual(m.raw_data, {})

    def test_resource_scalar_shapes_order_and_tag_coercions_remain_legacy(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Resources.yyp"),
            json.dumps({"resources": [
                None, 3, [], "ignored",
                {"id": None, "Key": "bool-id", "name": "s_bool", "path": "sprites/s_bool/s_bool.yy", "order": True,
                 "tags": [0, False, None, "", {"tag": 1}]},
                {"Key": "numeric-id", "Value": {"id": 9, "name": "r_string", "resourcePath": "rooms/r/r.yy",
                                                   "order": "12", "tags": "wrong"}},
                {"id": {"uuid": "float-id", "name": "scr_float", "path": "scripts/scr/scr.yy"}, "order": 3.9},
                {"name": "snd_invalid", "path": "sounds/snd/snd.yy", "order": "4.8"},
                {"id": {"name": "nested_missing"}, "path": "sprites/ignored/ignored.yy"},
            ]}),
        )
        manifest = load_gamemaker_project_manifest(self.gm_dir)
        self.assertEqual([item.order for item in manifest.resources], [4, 12, 3, 7])
        self.assertEqual([item.uuid for item in manifest.resources], ["bool-id", "numeric-id", "float-id", ""])
        self.assertEqual(manifest.resources[0].tags, ("0", "False", "None", "{'tag': 1}"))
        self.assertEqual(manifest.resources[1].tags, ())
        self.assertEqual(manifest.resources[1].resource_type, "GMRoom")
        rejected = [item for item in manifest.diagnostics if item.code == "GM2GD-SOURCE-PATH-REJECTED"]
        self.assertEqual(len(rejected), 1)
        assert rejected[0].source is not None
        self.assertEqual(rejected[0].source.field_path, "resources[8].id.path")
        self.assertIn("<missing>", rejected[0].message)

    def test_group_mapping_shapes_target_truthiness_and_stringification_remain_legacy(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "Groups.yyp"),
            json.dumps({
                "TextureGroups": [],
                "textureGroups": {"texture": {
                    "%Name": 7, "name": "texture", "parent": "", "parentGroup": {"%Name": "Parent"},
                    "isDynamic": False, "dynamic": [False], "dynamicPath": None, "path": "dynamic",
                    "targets": {"z": [], "windows": 1, "android": "false", "linux": {}, "mac": [False]},
                }, "ignored": 2},
                "AudioGroups": [None, [], {"name": "audio", "targets": ["windows", 0, False, None, "", {"nested": 1}]}],
                "IncludedFiles": {"included": {"name": None, "path": "", "filePath": "datafiles/a.txt",
                                                 "targets": {}, "copyToAndroid": ["truthy"], "copyToWindows": False}},
            }),
        )
        manifest = load_gamemaker_project_manifest(self.gm_dir)
        texture = manifest.texture_groups[0]
        self.assertEqual(texture.name, "texture")
        self.assertEqual(texture.parent, "Parent")
        self.assertTrue(texture.is_dynamic)
        self.assertEqual(texture.dynamic_path, "dynamic")
        self.assertEqual(texture.targets, ("android", "mac", "windows"))
        self.assertEqual(manifest.audio_groups[0].targets, ("windows", "0", "False", "None", "{'nested': 1}"))
        self.assertEqual(manifest.included_files[0].name, "a.txt")
        self.assertEqual(manifest.included_files[0].path, "datafiles/a.txt")
        self.assertEqual(manifest.included_files[0].targets, ("android",))

    def test_malformed_known_fields_stay_silent_and_unknown_fields_stay_preserved(self) -> None:
        path = os.path.join(self.gm_dir, "MalformedShapes.yyp")
        values: tuple[JsonValue, ...] = (None, 7, False, "wrong", [], {"wrong": [1, None]})
        for value in values:
            with self.subTest(value=value):
                _write_file(path, json.dumps({
                    "%Name": value, "name": "Fallback", "resourceType": value, "resourceVersion": value,
                    "resources": value, "configs": value, "ConfigValues": value, "TextureGroups": value,
                    "AudioGroups": value, "IncludedFiles": value, "MetaData": {"IDEVersion": value},
                    "Unknown": {"keep": [None, True]},
                }))
                manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual(manifest.project_name, value if isinstance(value, str) else "Fallback")
                self.assertEqual(manifest.resource_type, value if isinstance(value, str) else "")
                self.assertEqual(manifest.resource_version, value if isinstance(value, str) else "")
                self.assertEqual(manifest.ide_version, value if isinstance(value, str) else "")
                self.assertEqual(manifest.resources, ())
                if isinstance(value, dict):
                    self.assertEqual([item.name for item in manifest.configurations], ["wrong"])
                    self.assertEqual(manifest.configurations[0].overrides[0].value, [1, None])
                else:
                    self.assertEqual(manifest.configurations, ())
                self.assertEqual(manifest.texture_groups, ())
                self.assertEqual(manifest.audio_groups, ())
                self.assertEqual(manifest.included_files, ())
                self.assertEqual(manifest.raw_data["Unknown"], {"keep": [None, True]})
                self.assertEqual([item.code for item in manifest.diagnostics], ["GM2GD-PROJECT-UNKNOWN-FIELD"])

    def test_missing_null_and_empty_text_fields_keep_silent_fallbacks(self) -> None:
        path = os.path.join(self.gm_dir, "Text.yyp")
        field_cases: tuple[JsonObject, ...] = ({}, {"%Name": None}, {"%Name": ""}, {"%Name": False}, {"%Name": []})
        for fields_value in field_cases:
            with self.subTest(fields=fields_value):
                _write_file(path, json.dumps({"name": "Fallback", **fields_value}))
                manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual(manifest.project_name, "Fallback")
                self.assertEqual(manifest.diagnostics, ())

    def test_nonobject_root_has_existing_malformed_warning_location_and_empty_raw_data(self) -> None:
        path = os.path.join(self.gm_dir, "Nonobject.yyp")
        for source in ("null", "false", "7", '"text"', "[]", "[1, {}]"):
            with self.subTest(source=source):
                _write_file(path, source)
                manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual(manifest.project_name, "")
                self.assertEqual(manifest.raw_data, {})
                self.assertEqual(len(manifest.diagnostics), 1)
                diagnostic = manifest.diagnostics[0]
                self.assertEqual(diagnostic.code, "GM2GD-PROJECT-YYP-MALFORMED")
                self.assertEqual(diagnostic.message, f"Could not parse GameMaker project .yyp: {path}")
                self.assertEqual(diagnostic.source, ProjectSourceLocation(path, 1))

    def test_boundary_rejects_injected_nested_nonjson_values_as_existing_malformed_warning(self) -> None:
        path = os.path.join(self.gm_dir, "InvalidNested.yyp")
        _write_file(path, '{}')
        for decoded in ({"Unknown": [b"invalid"]}, {"Unknown": {1: "bad key"}}):
            with self.subTest(decoded=decoded):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=decoded):
                    manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual([item.code for item in manifest.diagnostics], ["GM2GD-PROJECT-YYP-MALFORMED"])
                self.assertEqual(manifest.raw_data, {})

    def test_read_decode_failures_are_swallowed_but_controls_keep_identity(self) -> None:
        path = os.path.join(self.gm_dir, "Errors.yyp")
        _write_file(path, '{}')
        swallowed = (
            OSError("read"), json.JSONDecodeError("parse", "{", 1), TypeError("type"), ValueError("limit"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"),
        )
        for error in swallowed:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.project_manifest.read_gamemaker_json", side_effect=error):
                    manifest = load_gamemaker_project_manifest(self.gm_dir)
                self.assertEqual([item.code for item in manifest.diagnostics], ["GM2GD-PROJECT-YYP-MALFORMED"])
                self.assertEqual(manifest.diagnostics[0].source, ProjectSourceLocation(path, 1))
        for error in (RecursionError("depth"), KeyboardInterrupt(), SystemExit(4)):
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.project_manifest.read_gamemaker_json", side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        load_gamemaker_project_manifest(self.gm_dir)
                self.assertIs(caught.exception, error)

    def test_actual_invalid_utf8_project_and_options_keep_manifest_acquisition_policy(self) -> None:
        path = os.path.join(self.gm_dir, "Unicode.yyp")
        with open(path, "wb") as stream:
            stream.write(b"\xff")
        malformed = load_gamemaker_project_manifest(self.gm_dir)
        self.assertEqual([item.code for item in malformed.diagnostics], ["GM2GD-PROJECT-YYP-MALFORMED"])
        _write_file(path, '{"%Name":"Valid"}')
        option_path = os.path.join(self.gm_dir, "options", "main", "options_main.yy")
        os.makedirs(os.path.dirname(option_path), exist_ok=True)
        with open(option_path, "wb") as stream:
            stream.write(b"\xff")
        valid = load_gamemaker_project_manifest(self.gm_dir)
        self.assertEqual(valid.project_name, "Valid")
        self.assertEqual(valid.options, ())
        self.assertEqual(valid.diagnostics, ())

    def test_option_walk_keeps_case_sensitive_suffix_sorting_and_last_selection(self) -> None:
        _write_file(os.path.join(self.gm_dir, "Options.yyp"), '{"%Name":"Options"}')
        _write_file(os.path.join(self.gm_dir, "options", "main", "a.yy"), '{"option_x":1,"ignored":2}')
        _write_file(os.path.join(self.gm_dir, "options", "main", "z.yy"), '{"option_x":2}')
        _write_file(os.path.join(self.gm_dir, "options", "windows", "a.yy"), '{"option_x":3}')
        _write_file(os.path.join(self.gm_dir, "options", "main", "ignored.YY"), '{"option_x":99}')
        _write_file(os.path.join(self.gm_dir, "options", "main", "bad.yy"), '[]')
        manifest = load_gamemaker_project_manifest(self.gm_dir)
        self.assertEqual([(item.platform, item.value) for item in manifest.options], [("main", 1), ("main", 2), ("windows", 3)])
        main = manifest.get_option("OPTION_X", "MAIN")
        windows = manifest.options_for_platform("windows")["option_x"]
        assert main is not None
        self.assertEqual(main.value, 2)
        self.assertEqual(windows.value, 3)
        self.assertIs(manifest.get_option("option_x"), windows)


if __name__ == "__main__":
    unittest.main()
