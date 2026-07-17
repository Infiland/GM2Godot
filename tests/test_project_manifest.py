import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.project_manifest import (
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


if __name__ == "__main__":
    unittest.main()
