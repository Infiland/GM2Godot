import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.project_manifest import load_gamemaker_project_manifest


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


if __name__ == "__main__":
    unittest.main()
