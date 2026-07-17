# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Iterable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.asset_registry import (
    ASSET_REGISTRY_RELATIVE_PATH,
    AssetRegistryConverter,
    GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH,
)
from src.conversion.animation_curve_registry import ANIMATION_CURVE_REGISTRY_RELATIVE_PATH
from src.conversion.extension_registry import (
    EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
    extension_stub_relative_script_path,
)
from src.conversion.path_registry import PATH_REGISTRY_RELATIVE_PATH


def _write_json(path: str, data: dict[str, object]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _resource_entry(kind: str, name: str) -> dict[str, object]:
    return {
        "id": {
            "name": name,
            "path": f"{kind}/{name}/{name}.yy",
        }
    }


def _write_yyp(base_dir: str, resources: Iterable[tuple[str, str]]) -> None:
    _write_json(
        os.path.join(base_dir, "AssetRegistryTest.yyp"),
        {
            "resources": [_resource_entry(kind, name) for kind, name in resources],
            "RoomOrderNodes": [],
            "resourceType": "GMProject",
        },
    )


def _minimal_yy(
    name: str,
    resource_type: str,
    parent_path: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "%Name": name,
        "name": name,
        "parent": {"name": "Parent", "path": parent_path},
        "resourceType": resource_type,
    }
    if extra:
        data.update(extra)
    return data


class TestAssetRegistryConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_resource(
        self,
        kind: str,
        name: str,
        resource_type: str,
        parent_path: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, kind, name, name + ".yy"),
            _minimal_yy(name, resource_type, parent_path, extra),
        )

    def _converter(
        self,
        organize_sounds_by_audio_group: bool = False,
        macro_configuration: str | None = None,
    ) -> AssetRegistryConverter:
        return AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            organize_sounds_by_audio_group=organize_sounds_by_audio_group,
            macro_configuration=macro_configuration,
        )

    def test_bundled_font_registry_path_matches_safe_emitted_filename(self) -> None:
        _write_yyp(self.gm_dir, [("fonts", "fnt_ui")])
        self._write_resource(
            "fonts",
            "fnt_ui",
            "GMFont",
            "folders/Fonts/UI.yy",
            {
                "includeTTF": True,
                "TTFName": "CustomFont.TTF",
            },
        )
        _write_file(
            os.path.join(self.gm_dir, "fonts", "fnt_ui", "CustomFont.TTF"),
            "font bytes",
        )

        entries = self._converter().build_entries()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].godot_path, "res://fonts/ui/custom_font.ttf")

    def test_builds_registry_entries_for_core_asset_types(self) -> None:
        _write_yyp(
            self.gm_dir,
            [
                ("sprites", "s_player"),
                ("sounds", "snd_jump"),
                ("rooms", "r_title"),
                ("objects", "o_player"),
                ("scripts", "scr_spawn"),
                ("fonts", "fnt_ui"),
                ("paths", "path_patrol"),
                ("animcurves", "ac_fade"),
                ("sequences", "seq_intro"),
                ("timelines", "tl_intro"),
                ("particlesystems", "ps_spark"),
                ("particles", "ps_legacy"),
                ("extensions", "AdSDK"),
            ],
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites/Actors.yy",
            {
                "tags": ["player", {"name": "visible"}],
                "textureGroupId": {"name": "Characters", "path": "texturegroups/Characters"},
            },
        )
        self._write_resource(
            "sounds",
            "snd_jump",
            "GMSound",
            "folders/Sounds/SFX.yy",
            {
                "soundFile": "snd_jump.ogg",
                "audioGroupId": {"name": "audio_sfx", "path": "audiogroups/audio_sfx.yy"},
            },
        )
        self._write_resource("rooms", "r_title", "GMRoom", "folders/Rooms/Menus.yy")
        self._write_resource("objects", "o_player", "GMObject", "folders/Objects/Actors.yy")
        self._write_resource("scripts", "scr_spawn", "GMScript", "folders/Scripts/Game.yy")
        self._write_resource("fonts", "fnt_ui", "GMFont", "folders/Fonts/UI.yy")
        self._write_resource("paths", "path_patrol", "GMPath", "folders/Paths/Movement.yy")
        self._write_resource("animcurves", "ac_fade", "GMAnimationCurve", "folders/Animation Curves.yy")
        self._write_resource(
            "sequences",
            "seq_intro",
            "GMSequence",
            "folders/Sequences.yy",
            {
                "length": 120,
                "playbackSpeed": 30,
                "playback": 1,
                "tracks": [{"name": "Title"}],
                "moments": [{"frame": 2, "callable": "_on_sequence_moment"}],
                "broadcastMessages": [{"frame": 4, "message": "beat"}],
            },
        )
        self._write_resource(
            "timelines",
            "tl_intro",
            "GMTimeline",
            "folders/Timelines.yy",
            {
                "momentList": [
                    {"moment": 2, "eventFile": "Moment_2.gml"},
                    {"moment": 4, "actions": [{"script": "scr_spawn"}]},
                ]
            },
        )
        _write_file(os.path.join(self.gm_dir, "timelines", "tl_intro", "Moment_2.gml"), "x = 42;\n")
        self._write_resource(
            "particlesystems",
            "ps_spark",
            "GMParticleSystem",
            "folders/Particles.yy",
            {
                "particleTypes": [{"name": "pt_spark", "lifeMin": 10, "lifeMax": 20}],
                "emitters": [{"name": "pe_spark", "streamNumber": 4}],
            },
        )
        self._write_resource(
            "particles",
            "ps_legacy",
            "GMParticleSystem",
            "folders/Particles.yy",
            {
                "particleTypes": [{"name": "pt_legacy"}],
                "emitters": [{"name": "pe_legacy"}],
            },
        )
        self._write_resource(
            "extensions",
            "AdSDK",
            "GMExtension",
            "folders/Extensions.yy",
            {
                "version": "1.2.3",
                "files": [
                    {
                        "filename": "ads.dll",
                        "platform": "windows",
                        "functions": [
                            {
                                "name": "ads_show_rewarded",
                                "externalName": "AdsShowRewarded",
                                "argCount": 1,
                            }
                        ],
                    }
                ],
            },
        )
        _write_file(os.path.join(self.gm_dir, "datafiles", "config", "game.json"), "{}")

        entries = self._converter(organize_sounds_by_audio_group=True).build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertEqual(by_name["s_player"].asset_type, "sprite")
        self.assertEqual(by_name["s_player"].godot_path, "res://sprites/actors/s_player/s_player.tscn")
        self.assertEqual(by_name["s_player"].tags, ("player", "visible"))
        sprite_metadata = by_name["s_player"].metadata
        self.assertIsNotNone(sprite_metadata)
        assert sprite_metadata is not None
        self.assertEqual(sprite_metadata["texture_group"], "Characters")
        self.assertEqual(by_name["snd_jump"].asset_type, "sound")
        self.assertEqual(
            by_name["snd_jump"].godot_path,
            "res://sounds/audio_sfx/sfx/snd_jump/snd_jump.ogg",
        )
        sound_metadata = by_name["snd_jump"].metadata
        self.assertIsNotNone(sound_metadata)
        assert sound_metadata is not None
        self.assertEqual(sound_metadata["audio_group"], "audio_sfx")
        self.assertEqual(sound_metadata["sound_file"], "snd_jump.ogg")
        self.assertEqual(sound_metadata["volume"], 1.0)
        self.assertEqual(by_name["r_title"].godot_path, "res://rooms/menus/r_title/r_title.tscn")
        room_metadata = by_name["r_title"].metadata
        self.assertIsNotNone(room_metadata)
        assert room_metadata is not None
        self.assertEqual(room_metadata["room_order"], 0)
        self.assertEqual(room_metadata["width"], 1024)
        self.assertEqual(room_metadata["height"], 768)
        self.assertFalse(room_metadata["persistent"])
        self.assertEqual(by_name["o_player"].godot_path, "res://objects/actors/o_player/o_player.tscn")
        self.assertEqual(by_name["scr_spawn"].godot_path, "res://scripts/game/scr_spawn.gd")
        self.assertEqual(by_name["fnt_ui"].godot_path, "res://fonts/ui/fnt_ui.tres")
        self.assertEqual(by_name["path_patrol"].asset_type, "path")
        self.assertEqual(
            by_name["path_patrol"].godot_path,
            "res://paths/movement/path_patrol/path_patrol.tscn",
        )
        self.assertEqual(by_name["ac_fade"].asset_type, "animation_curve")
        self.assertEqual(by_name["seq_intro"].asset_type, "sequence")
        sequence_metadata = by_name["seq_intro"].metadata
        self.assertIsNotNone(sequence_metadata)
        assert sequence_metadata is not None
        self.assertEqual(sequence_metadata["length"], 120.0)
        self.assertEqual(sequence_metadata["playback_speed"], 30.0)
        self.assertEqual(sequence_metadata["loopmode"], 1)
        self.assertEqual(sequence_metadata["tracks"], [{"name": "Title"}])
        self.assertEqual(sequence_metadata["moments"][0]["callable"], "_on_sequence_moment")
        self.assertEqual(sequence_metadata["broadcasts"][0]["message"], "beat")
        self.assertEqual(by_name["tl_intro"].asset_type, "timeline")
        timeline_metadata = by_name["tl_intro"].metadata
        self.assertIsNotNone(timeline_metadata)
        assert timeline_metadata is not None
        self.assertEqual(timeline_metadata["moment_count"], 2)
        self.assertEqual(timeline_metadata["max_moment"], 4)
        first_timeline_action = timeline_metadata["moments"][0]["actions"][0]
        self.assertEqual(first_timeline_action["source_path"], "timelines/tl_intro/Moment_2.gml")
        self.assertEqual(first_timeline_action["script_path"], "res://gm2godot/timelines/tl_intro_2.gd")
        self.assertEqual(by_name["ps_spark"].asset_type, "particle_system")
        particle_metadata = by_name["ps_spark"].metadata
        self.assertIsNotNone(particle_metadata)
        assert particle_metadata is not None
        self.assertEqual(particle_metadata["types"][0]["name"], "pt_spark")
        self.assertEqual(particle_metadata["emitters"][0]["name"], "pe_spark")
        self.assertEqual(by_name["ps_legacy"].asset_type, "particle_system")
        legacy_particle_metadata = by_name["ps_legacy"].metadata
        self.assertIsNotNone(legacy_particle_metadata)
        assert legacy_particle_metadata is not None
        self.assertEqual(legacy_particle_metadata["types"][0]["name"], "pt_legacy")
        self.assertEqual(by_name["AdSDK"].asset_type, "extension")
        self.assertEqual(
            by_name["AdSDK"].godot_path,
            "res://addons/gm2godot_extensions/adsdk/adsdk_extension.gd",
        )
        extension_metadata = by_name["AdSDK"].metadata
        self.assertIsNotNone(extension_metadata)
        assert extension_metadata is not None
        self.assertEqual(extension_metadata["version"], "1.2.3")
        self.assertEqual(extension_metadata["files"][0]["functions"][0]["name"], "ads_show_rewarded")
        self.assertEqual(by_name["config/game.json"].asset_type, "included_file")
        self.assertEqual(by_name["config/game.json"].godot_path, "res://included_files/config/game.json")

    def test_static_ids_are_stable_across_yyp_resource_order(self) -> None:
        resources = [("sprites", "s_player"), ("sounds", "snd_jump")]
        _write_yyp(self.gm_dir, resources)
        self._write_resource("sprites", "s_player", "GMSprite", "folders/Sprites.yy")
        self._write_resource(
            "sounds",
            "snd_jump",
            "GMSound",
            "folders/Sounds.yy",
            {"soundFile": "snd_jump.wav"},
        )

        first_ids = {entry.name: entry.id for entry in self._converter().build_entries()}
        _write_yyp(self.gm_dir, reversed(resources))
        second_ids = {entry.name: entry.id for entry in self._converter().build_entries()}

        self.assertEqual(first_ids, second_ids)

    def test_backslash_yyp_path_resolves_existing_resource_and_normalizes_source_path(self) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "s_player",
                            "path": "sprites\\s_player\\s_player.yy",
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites/Actors.yy",
        )

        entries = self._converter().build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertIn("s_player", by_name)
        self.assertEqual(by_name["s_player"].source_path, "sprites/s_player/s_player.yy")
        self.assertEqual(
            by_name["s_player"].godot_path,
            "res://sprites/actors/s_player/s_player.tscn",
        )

    def test_unsafe_yyp_paths_are_skipped_with_clear_diagnostics(self) -> None:
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites/Actors.yy",
        )
        valid_yy_path = os.path.join(
            self.gm_dir,
            "sprites",
            "s_player",
            "s_player.yy",
        )
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "s_player",
                            "path": "sprites/s_player/s_player.yy",
                        }
                    },
                    {
                        "id": {
                            "name": "s_traversal",
                            "path": "sprites/../../outside.yy",
                        }
                    },
                    {
                        "id": {
                            "name": "s_absolute",
                            "path": valid_yy_path,
                        }
                    },
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )

        entries = self._converter().build_entries()

        self.assertEqual([entry.name for entry in entries], ["s_player"])
        self.assertTrue(
            any(
                "s_traversal" in message
                and "escapes the selected GameMaker project root" in message
                for message in self.logs
            ),
            self.logs,
        )
        self.assertTrue(
            any(
                "s_absolute" in message and "must be relative" in message
                for message in self.logs
            ),
            self.logs,
        )

    def test_build_entries_includes_modern_script_function_assets(self) -> None:
        _write_yyp(self.gm_dir, [("scripts", "ending")])
        self._write_resource("scripts", "ending", "GMScript", "folders/Scripts/Game.yy")
        _write_file(
            os.path.join(self.gm_dir, "scripts", "ending", "ending.gml"),
            "function loadending() { return 1; }\n"
            "function saveending() { loadending(); }\n",
        )

        entries = self._converter().build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertIn("ending", by_name)
        self.assertIn("loadending", by_name)
        self.assertIn("saveending", by_name)
        self.assertEqual(by_name["ending"].godot_path, "res://scripts/game/ending.gd")
        self.assertEqual(by_name["loadending"].asset_type, "script")
        self.assertEqual(by_name["loadending"].godot_path, by_name["ending"].godot_path)
        self.assertNotEqual(by_name["loadending"].id, by_name["ending"].id)
        self.assertEqual(
            by_name["loadending"].legacy_id,
            "scripts/ending/ending.yy#function:loadending",
        )
        self.assertEqual(
            by_name["loadending"].metadata,
            {
                "script_function": True,
                "script_asset": "ending",
                "script_source_path": "scripts/ending/ending.yy",
            },
        )

    def test_script_function_assets_follow_selected_macro_configuration(self) -> None:
        _write_yyp(self.gm_dir, [("scripts", "conditional")])
        self._write_resource(
            "scripts",
            "conditional",
            "GMScript",
            "folders/Scripts/Game.yy",
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "scripts",
                "conditional",
                "conditional.gml",
            ),
            "#if Android\n"
            "function android_only() { return 11; }\n"
            "#else\n"
            "function desktop_only() { return 22; }\n"
            "#endif\n"
            "function shared_function() { return 33; }\n",
        )

        entries = self._converter(macro_configuration="Android").build_entries()
        names = {entry.name for entry in entries}

        self.assertIn("conditional", names)
        self.assertIn("android_only", names)
        self.assertIn("shared_function", names)
        self.assertNotIn("desktop_only", names)

    def test_invalid_script_conditional_does_not_abort_registry_discovery(self) -> None:
        _write_yyp(self.gm_dir, [("scripts", "conditional")])
        self._write_resource(
            "scripts",
            "conditional",
            "GMScript",
            "folders/Scripts/Game.yy",
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "scripts",
                "conditional",
                "conditional.gml",
            ),
            "#if Android &&\n"
            "function android_only() { return 11; }\n"
            "#endif\n",
        )

        entries = self._converter(macro_configuration="Android").build_entries()

        self.assertEqual([entry.name for entry in entries], ["conditional"])

    def test_convert_all_writes_runtime_registry_script(self) -> None:
        _write_yyp(
            self.gm_dir,
            [
                ("sprites", "s_player"),
                ("paths", "path_patrol"),
                ("animcurves", "ac_fade"),
                ("timelines", "tl_intro"),
                ("extensions", "AdSDK"),
            ],
        )
        self._write_resource("sprites", "s_player", "GMSprite", "folders/Sprites.yy")
        self._write_resource(
            "paths",
            "path_patrol",
            "GMPath",
            "folders/Paths.yy",
            {"points": [{"x": 0, "y": 0}, {"x": 16, "y": 0}]},
        )
        self._write_resource(
            "animcurves",
            "ac_fade",
            "GMAnimationCurve",
            "folders/Animation Curves.yy",
            {"channels": [{"name": "alpha", "points": [{"x": 0, "y": 1}]}]},
        )
        self._write_resource(
            "timelines",
            "tl_intro",
            "GMTimeline",
            "folders/Timelines.yy",
            {"momentList": [{"moment": 3, "eventFile": "Moment_3.gml"}]},
        )
        _write_file(os.path.join(self.gm_dir, "timelines", "tl_intro", "Moment_3.gml"), "x = 42;\n")
        self._write_resource(
            "extensions",
            "AdSDK",
            "GMExtension",
            "folders/Extensions.yy",
            {
                "files": [
                    {
                        "filename": "ads.dll",
                        "platform": "windows",
                        "functions": [
                            {
                                "name": "ads_show_rewarded",
                                "externalName": "AdsShowRewarded",
                                "argCount": 1,
                            }
                        ],
                    }
                ],
            },
        )
        _write_json(
            os.path.join(self.gm_dir, "gm2godot_extension_functions.json"),
            {"functions": {"ads_show_rewarded": "AdBridge.show_rewarded"}},
        )

        registry_path = self._converter().convert_all()

        self.assertEqual(registry_path, os.path.join(self.godot_dir, ASSET_REGISTRY_RELATIVE_PATH))
        with open(registry_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("extends RefCounted", content)
        self.assertIn("const FORMAT_VERSION = 1", content)
        self.assertIn("static func gml_asset_registry_entries():", content)
        self.assertIn('"name": "s_player"', content)
        self.assertIn('"type": "sprite"', content)

        path_registry_path = os.path.join(self.godot_dir, PATH_REGISTRY_RELATIVE_PATH)
        path_scene_path = os.path.join(self.godot_dir, "paths", "path_patrol", "path_patrol.tscn")
        animation_curve_registry_path = os.path.join(self.godot_dir, ANIMATION_CURVE_REGISTRY_RELATIVE_PATH)
        timeline_script_path = os.path.join(self.godot_dir, "gm2godot", "timelines", "tl_intro_3.gd")
        extension_report_path = os.path.join(self.godot_dir, EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH)
        extension_stub_path = os.path.join(self.godot_dir, extension_stub_relative_script_path("AdSDK"))
        self.assertTrue(os.path.isfile(path_registry_path))
        self.assertTrue(os.path.isfile(path_scene_path))
        self.assertTrue(os.path.isfile(animation_curve_registry_path))
        self.assertTrue(os.path.isfile(timeline_script_path))
        self.assertTrue(os.path.isfile(extension_report_path))
        self.assertTrue(os.path.isfile(extension_stub_path))
        with open(path_scene_path, "r", encoding="utf-8") as f:
            path_scene = f.read()
        with open(animation_curve_registry_path, "r", encoding="utf-8") as f:
            curve_registry = f.read()
        with open(timeline_script_path, "r", encoding="utf-8") as f:
            timeline_script = f.read()
        with open(extension_report_path, "r", encoding="utf-8") as f:
            extension_report = json.load(f)
        self.assertIn('[node name="path_patrol" type="Path2D"]', path_scene)
        self.assertIn('"name": "ac_fade"', curve_registry)
        self.assertIn("static func execute(_gm_instance):", timeline_script)
        self.assertIn('GMRuntime.gml_variable_instance_set(_gm_instance, "x", 42)', timeline_script)
        self.assertEqual(extension_report["mapped_functions"], ["ads_show_rewarded"])
        self.assertEqual(extension_report["stubs"][0]["path"], "res://addons/gm2godot_extensions/adsdk/adsdk_extension.gd")

    def test_generates_actionable_texture_and_audio_group_registries(self) -> None:
        _write_json(
            os.path.join(self.gm_dir, "Groups.yyp"),
            {
                "resources": [_resource_entry("sprites", "s_player"), _resource_entry("sounds", "snd_theme")],
                "TextureGroups": [
                    {
                        "%Name": "Characters",
                        "isDynamic": True,
                        "dynamicPath": "texturegroups/characters",
                        "targets": ["windows"],
                    }
                ],
                "AudioGroups": [
                    {"%Name": "audiogroup_default"},
                    {"%Name": "audiogroup_music", "targets": ["windows"], "gain": 0.75},
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites.yy",
            {"textureGroupId": {"name": "Characters", "path": "texturegroups/Characters"}},
        )
        self._write_resource(
            "sounds",
            "snd_theme",
            "GMSound",
            "folders/Sounds.yy",
            {
                "soundFile": "theme.ogg",
                "audioGroupId": {"name": "audiogroup_music", "path": "audiogroups/audiogroup_music.yy"},
                "preload": False,
                "compression": 1,
                "type": 1,
            },
        )

        converter = self._converter()
        entries = converter.build_entries()
        texture_groups, audio_groups = converter.build_group_registries(entries)
        texture_by_name = {str(group["name"]): group for group in texture_groups}
        audio_by_name = {str(group["name"]): group for group in audio_groups}

        self.assertEqual(texture_by_name["Characters"]["asset_names"], ["s_player"])
        self.assertTrue(texture_by_name["Characters"]["dynamic"])
        self.assertEqual(texture_by_name["Characters"]["dynamic_path"], "texturegroups/characters")
        self.assertEqual(texture_by_name["Characters"]["targets"], ["windows"])
        self.assertEqual(audio_by_name["audiogroup_music"]["asset_names"], ["snd_theme"])
        self.assertFalse(audio_by_name["audiogroup_music"]["loaded"])
        self.assertEqual(audio_by_name["audiogroup_music"]["gain"], 0.75)
        self.assertTrue(audio_by_name["audiogroup_default"]["loaded"])

        registry_path = converter.convert_all()
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = f.read()
        self.assertIn("const TEXTURE_GROUPS =", registry)
        self.assertIn("static func gml_audio_group_registry_entries():", registry)
        self.assertIn('"texture_group_dynamic": true', registry)

        report_path = os.path.join(self.godot_dir, GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH)
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        codes = {diagnostic["code"] for diagnostic in report["diagnostics"]}
        self.assertIn("texture_group_dynamic_runtime", codes)
        self.assertIn("audio_group_memory_runtime", codes)
        self.assertIn("sound_preload_lazy", codes)
        self.assertIn("sound_import_semantics", codes)


if __name__ == "__main__":
    unittest.main()
