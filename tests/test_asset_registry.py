# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from typing import BinaryIO, Iterable, cast
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.asset_registry import (
    ASSET_REGISTRY_RELATIVE_PATH,
    AssetRegistryEntry,
    AssetRegistryConverter,
    GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH,
    _ProjectResource,
)
from src.conversion import asset_registry as asset_registry_module
from src.conversion.animation_curve_registry import ANIMATION_CURVE_REGISTRY_RELATIVE_PATH
from src.conversion.converter import Converter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.extension_registry import (
    EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
    extension_stub_relative_script_path,
)
from src.conversion.fonts import FontConverter
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.path_registry import PATH_REGISTRY_RELATIVE_PATH
from src.conversion.type_defs import JsonDict, StrPath


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


class _EnabledSetting:
    def get(self) -> bool:
        return True


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
        diagnostics: DiagnosticCollector | None = None,
    ) -> AssetRegistryConverter:
        return AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            organize_sounds_by_audio_group=organize_sounds_by_audio_group,
            macro_configuration=macro_configuration,
            diagnostics=diagnostics,
        )

    def _emit_included_files(self) -> None:
        IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        ).convert_included_files()

    def _write_included_source(self, relative_path: str, payload: bytes) -> None:
        source_path = os.path.join(
            self.gm_dir,
            "datafiles",
            *relative_path.split("/"),
        )
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(source_path, "wb") as source_file:
            source_file.write(payload)

    def _write_included_output(self, relative_path: str, payload: bytes) -> None:
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            *relative_path.split("/"),
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as output_file:
            output_file.write(payload)

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

    def test_project_root_bundled_font_paths_match_converted_outputs(self) -> None:
        _write_yyp(
            self.gm_dir,
            [("fonts", "fnt_root"), ("fonts", "fnt_placeholder")],
        )
        references = {
            "fnt_root": ("fonts/shared/Root.ttf", b"root font bytes"),
            "fnt_placeholder": (
                "${project_dir}/fonts/shared/Placeholder.ttf",
                b"placeholder font bytes",
            ),
        }
        for font_name, (reference, _payload) in references.items():
            self._write_resource(
                "fonts",
                font_name,
                "GMFont",
                "folders/Fonts.yy",
                {
                    "fontName": font_name,
                    "includeTTF": True,
                    "TTFName": reference,
                },
            )
        for reference, payload in references.values():
            normalized_reference = reference.removeprefix("${project_dir}/")
            font_path = os.path.join(
                self.gm_dir,
                *normalized_reference.split("/"),
            )
            os.makedirs(os.path.dirname(font_path), exist_ok=True)
            with open(font_path, "wb") as font_file:
                font_file.write(payload)

        entries = self._converter().build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertEqual(
            by_name["fnt_root"].godot_path,
            "res://fonts/root.ttf",
        )
        self.assertEqual(
            by_name["fnt_placeholder"].godot_path,
            "res://fonts/placeholder.ttf",
        )

        FontConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
        ).convert_all()

        for font_name, (_reference, payload) in references.items():
            output_path = os.path.join(
                self.godot_dir,
                *by_name[font_name].godot_path.removeprefix("res://").split("/"),
            )
            with open(output_path, "rb") as font_file:
                self.assertEqual(font_file.read(), payload)

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

    def test_timeline_source_fields_resolve_owner_and_project_relative_paths(self) -> None:
        _write_yyp(self.gm_dir, [("timelines", "tl_paths")])
        fields = (
            ("gmlFile", "Moment_1.gml"),
            ("eventFile", "timelines/tl_paths/Moment_2.gml"),
            ("filename", "${project_dir}/timelines/tl_paths/Moment_3.gml"),
            ("source", "Moment_4.gml"),
            ("sourceFile", r"timelines\tl_paths\Moment_5.gml"),
        )
        self._write_resource(
            "timelines",
            "tl_paths",
            "GMTimeline",
            "folders/Timelines.yy",
            {
                "momentList": [
                    {"moment": frame, field: value}
                    for frame, (field, value) in enumerate(fields, start=1)
                ]
            },
        )
        for frame in range(1, 6):
            _write_file(
                os.path.join(
                    self.gm_dir,
                    "timelines",
                    "tl_paths",
                    f"Moment_{frame}.gml",
                ),
                f"x = {frame};\n",
            )

        entry = self._converter().build_entries()[0]
        assert entry.metadata is not None
        moments = entry.metadata["moments"]
        assert isinstance(moments, list)
        typed_moments = cast(list[dict[str, list[dict[str, str]]]], moments)

        self.assertEqual(
            [moment["actions"][0]["source_path"] for moment in typed_moments],
            [
                f"timelines/tl_paths/Moment_{frame}.gml"
                for frame in range(1, 6)
            ],
        )

    def test_timeline_action_scripts_use_collision_safe_stable_paths(self) -> None:
        timeline_values = {
            "tl-one": 11,
            "tl_one": 22,
        }
        _write_yyp(
            self.gm_dir,
            [("timelines", name) for name in reversed(tuple(timeline_values))],
        )
        for name, value in timeline_values.items():
            self._write_resource(
                "timelines",
                name,
                "GMTimeline",
                "folders/Timelines.yy",
                {"momentList": [{"moment": 1, "eventFile": "Moment_1.gml"}]},
            )
            _write_file(
                os.path.join(
                    self.gm_dir,
                    "timelines",
                    name,
                    "Moment_1.gml",
                ),
                f"timeline_value = {value};\n",
            )

        converter = self._converter()
        entries = converter.build_entries()
        script_paths = {
            entry.name: cast(
                list[dict[str, list[dict[str, str]]]],
                cast(JsonDict, entry.metadata)["moments"],
            )[0]["actions"][0]["script_path"]
            for entry in entries
        }

        self.assertEqual(
            script_paths,
            {
                "tl-one": "res://gm2godot/timelines/tl_one_1.gd",
                "tl_one": "res://gm2godot/timelines/tl_one_2_1.gd",
            },
        )
        self.assertEqual(
            len({path.casefold() for path in script_paths.values()}),
            len(timeline_values),
        )

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=2,
            ),
        )
        for name, value in timeline_values.items():
            output_path = os.path.join(
                self.godot_dir,
                *script_paths[name].removeprefix("res://").split("/"),
            )
            with open(output_path, "r", encoding="utf-8") as script_file:
                self.assertIn(
                    'GMRuntime.gml_variable_instance_set(_gm_instance, '
                    f'"timeline_value", {value})',
                    script_file.read(),
                )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        for script_path in script_paths.values():
            self.assertIn(f'"script_path": "{script_path}"', registry)

        _write_yyp(
            self.gm_dir,
            [("timelines", name) for name in timeline_values],
        )
        reordered_entries = self._converter().build_entries()
        reordered_paths = {
            entry.name: cast(
                list[dict[str, list[dict[str, str]]]],
                cast(JsonDict, entry.metadata)["moments"],
            )[0]["actions"][0]["script_path"]
            for entry in reordered_entries
        }
        self.assertEqual(reordered_paths, script_paths)

    def test_derived_registries_preserve_normalized_name_collisions(self) -> None:
        declarations = (
            ("paths", "path-one"),
            ("paths", "path_one"),
            ("animcurves", "curve-one"),
            ("animcurves", "curve_one"),
        )
        _write_yyp(self.gm_dir, reversed(declarations))
        self._write_resource(
            "paths",
            "path-one",
            "GMPath",
            "folders/Paths.yy",
            {"points": [{"x": 11, "y": 1}]},
        )
        self._write_resource(
            "paths",
            "path_one",
            "GMPath",
            "folders/Paths.yy",
            {"points": [{"x": 22, "y": 2}]},
        )
        self._write_resource(
            "animcurves",
            "curve-one",
            "GMAnimationCurve",
            "folders/Animation Curves.yy",
            {
                "channels": [
                    {"name": "hyphen_channel", "points": [{"x": 0, "y": 11}]}
                ]
            },
        )
        self._write_resource(
            "animcurves",
            "curve_one",
            "GMAnimationCurve",
            "folders/Animation Curves.yy",
            {
                "channels": [
                    {
                        "name": "underscore_channel",
                        "points": [{"x": 0, "y": 22}],
                    }
                ]
            },
        )

        converter = self._converter()
        entries = converter.build_entries()
        path_entries = {
            entry.name: entry
            for entry in entries
            if entry.kind == "paths"
        }
        path_destinations = {
            name: entry.godot_path
            for name, entry in path_entries.items()
        }

        self.assertEqual(
            path_destinations,
            {
                "path-one": "res://paths/path_one/path_one.tscn",
                "path_one": "res://paths/path_one_2/path_one_2.tscn",
            },
        )
        self.assertEqual(
            len({path.casefold() for path in path_destinations.values()}),
            2,
        )

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=4,
                executed=4,
                completed=4,
            ),
        )
        for name, expected_x in (("path-one", 11), ("path_one", 22)):
            output_path = os.path.join(
                self.godot_dir,
                *path_destinations[name].removeprefix("res://").split("/"),
            )
            with open(output_path, "r", encoding="utf-8") as scene_file:
                scene = scene_file.read()
            self.assertIn(f'[node name="{name}" type="Path2D"]', scene)
            self.assertIn(f'"x": {expected_x}.0', scene)

        with open(
            os.path.join(
                self.godot_dir,
                ANIMATION_CURVE_REGISTRY_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as curve_registry_file:
            curve_registry = curve_registry_file.read()
        self.assertIn('"name": "curve-one"', curve_registry)
        self.assertIn('"name": "curve_one"', curve_registry)
        self.assertIn('"name": "hyphen_channel"', curve_registry)
        self.assertIn('"name": "underscore_channel"', curve_registry)

        _write_yyp(self.gm_dir, declarations)
        reordered_paths = {
            entry.name: entry.godot_path
            for entry in self._converter().build_entries()
            if entry.kind == "paths"
        }
        self.assertEqual(reordered_paths, path_destinations)

    def test_extension_stubs_use_collision_safe_selected_paths(self) -> None:
        extension_names = ("Ext-One", "Ext_One")
        _write_yyp(
            self.gm_dir,
            [("extensions", name) for name in reversed(extension_names)],
        )
        for index, name in enumerate(extension_names, start=1):
            self._write_resource(
                "extensions",
                name,
                "GMExtension",
                "folders/Extensions.yy",
                {
                    "files": [
                        {
                            "filename": f"extension_{index}.dll",
                            "functions": [
                                {
                                    "name": f"extension_call_{index}",
                                    "argCount": 0,
                                }
                            ],
                        }
                    ]
                },
            )

        converter = self._converter()
        entries = converter.build_entries()
        extension_entries = {
            entry.name: entry
            for entry in entries
            if entry.kind == "extensions"
        }
        stub_paths = {
            name: entry.godot_path
            for name, entry in extension_entries.items()
        }

        self.assertEqual(
            stub_paths,
            {
                "Ext-One": (
                    "res://addons/gm2godot_extensions/ext_one/"
                    "ext_one_extension.gd"
                ),
                "Ext_One": (
                    "res://addons/gm2godot_extensions/ext_one_2/"
                    "ext_one_2_extension.gd"
                ),
            },
        )
        self.assertEqual(
            len({path.casefold() for path in stub_paths.values()}),
            len(extension_names),
        )
        for name, entry in extension_entries.items():
            metadata = cast(JsonDict, entry.metadata)
            self.assertEqual(metadata["stub_path"], stub_paths[name])

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=2,
            ),
        )
        with open(
            os.path.join(
                self.godot_dir,
                EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = cast(JsonDict, json.load(report_file))
        report_paths = {
            cast(str, stub["extension"]): cast(str, stub["path"])
            for stub in cast(list[JsonDict], report["stubs"])
        }
        self.assertEqual(report_paths, stub_paths)

        for name in extension_names:
            output_path = os.path.join(
                self.godot_dir,
                *stub_paths[name].removeprefix("res://").split("/"),
            )
            with open(output_path, "r", encoding="utf-8") as script_file:
                self.assertIn(
                    f"# GameMaker extension: {name}",
                    script_file.read(),
                )
            with open(
                os.path.join(os.path.dirname(output_path), "plugin.cfg"),
                "r",
                encoding="utf-8",
            ) as plugin_file:
                self.assertIn(
                    f'script="{os.path.basename(output_path)}"',
                    plugin_file.read(),
                )

        _write_yyp(
            self.gm_dir,
            [("extensions", name) for name in extension_names],
        )
        reordered_paths = {
            entry.name: entry.godot_path
            for entry in self._converter().build_entries()
            if entry.kind == "extensions"
        }
        self.assertEqual(reordered_paths, stub_paths)

    def test_valid_yyp_excludes_orphan_extension_auxiliary_outputs(self) -> None:
        _write_yyp(self.gm_dir, [])
        self._write_resource(
            "extensions",
            "OrphanSDK",
            "GMExtension",
            "folders/Extensions.yy",
            {
                "files": [
                    {
                        "filename": "orphan.dll",
                        "functions": [{"name": "orphan_call", "argCount": 0}],
                    }
                ]
            },
        )
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertNotIn("OrphanSDK", registry_file.read())
        with open(
            os.path.join(
                self.godot_dir,
                EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = cast(JsonDict, json.load(report_file))
        self.assertEqual(report["extensions"], [])
        self.assertEqual(report["stubs"], [])
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "addons",
                    "gm2godot_extensions",
                    "orphansdk",
                )
            )
        )

    def test_extension_selection_matches_manifest_path_case_portably(self) -> None:
        extension_name = "ExtCase"
        self._write_resource(
            "extensions",
            extension_name,
            "GMExtension",
            "folders/Extensions.yy",
            {
                "files": [
                    {
                        "filename": "case.dll",
                        "functions": [{"name": "case_call", "argCount": 0}],
                    }
                ]
            },
        )
        declared_path = "extensions/extcase/extcase.yy"
        if not os.path.isfile(os.path.join(self.gm_dir, *declared_path.split("/"))):
            self.skipTest("Host filesystem does not resolve case-mismatched paths")
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": extension_name,
                            "path": declared_path,
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        converter = self._converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        with open(report_path, "r", encoding="utf-8") as report_file:
            report = cast(JsonDict, json.load(report_file))
        stubs = cast(list[JsonDict], report["stubs"])
        self.assertEqual(len(stubs), 1)
        stub_path = cast(str, stubs[0]["path"])
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    *stub_path.removeprefix("res://").split("/"),
                )
            )
        )

    def test_case_sensitive_extension_sources_remain_distinct(self) -> None:
        case_probe = os.path.join(self.gm_dir, "CaseSensitivityProbe")
        os.mkdir(case_probe)
        case_sensitive = not os.path.exists(case_probe.lower())
        os.rmdir(case_probe)
        if not case_sensitive:
            self.skipTest("Host filesystem is case-insensitive")

        extension_names = ("CaseExt", "caseext")
        _write_yyp(
            self.gm_dir,
            [("extensions", name) for name in extension_names],
        )
        for name in extension_names:
            self._write_resource(
                "extensions",
                name,
                "GMExtension",
                "folders/Extensions.yy",
                {
                    "files": [
                        {
                            "filename": f"{name}.dll",
                            "functions": [
                                {"name": f"{name}_call", "argCount": 0}
                            ],
                        }
                    ]
                },
            )
        converter = self._converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, executed=2, completed=2),
        )
        with open(
            os.path.join(
                self.godot_dir,
                EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as report_file:
            report = cast(JsonDict, json.load(report_file))
        stubs = cast(list[JsonDict], report["stubs"])
        self.assertEqual(
            {cast(str, stub["extension"]) for stub in stubs},
            set(extension_names),
        )
        self.assertEqual(
            len({cast(str, stub["path"]).casefold() for stub in stubs}),
            2,
        )

    def test_timeline_rejects_uncontained_source_fields_without_losing_actions(self) -> None:
        _write_yyp(self.gm_dir, [("timelines", "tl_paths")])
        timeline_directory = os.path.join(
            self.gm_dir,
            "timelines",
            "tl_paths",
        )
        os.makedirs(timeline_directory)
        explicit_fields = ("gmlFile", "eventFile", "filename", "source", "sourceFile")
        expected_cases: list[tuple[int, str, str]] = []
        moments: list[dict[str, object]] = []
        diagnostics = DiagnosticCollector()

        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = os.path.join(outside_dir, "outside.gml")
            outside_contents = "outside_read = true;\n"
            _write_file(outside_source, outside_contents)
            traversal = os.path.relpath(
                outside_source,
                timeline_directory,
            ).replace(os.sep, "/")
            frame = 0
            for field in explicit_fields:
                linked_filename = f"linked_{field}.gml"
                try:
                    os.symlink(
                        outside_source,
                        os.path.join(timeline_directory, linked_filename),
                    )
                except (NotImplementedError, OSError) as exc:
                    self.skipTest(f"Symbolic links are unavailable: {exc}")
                unsafe_values = (
                    ("traversal", traversal),
                    ("posix_absolute", "/tmp/outside.gml"),
                    ("drive_absolute", r"C:\outside.gml"),
                    ("drive_relative", r"C:outside.gml"),
                    ("unc", r"\\server\share\outside.gml"),
                    ("nul", "invalid\0source.gml"),
                    ("external_file_symlink", linked_filename),
                )
                for case_name, value in unsafe_values:
                    frame += 1
                    expected_cases.append((frame, field, case_name))
                    moments.append(
                        {
                            "moment": frame,
                            field: value,
                            "actions": [
                                {"script": f"scr_keep_{frame}"},
                                {"callable": f"callable_keep_{frame}"},
                            ],
                        }
                    )

            self._write_resource(
                "timelines",
                "tl_paths",
                "GMTimeline",
                "folders/Timelines.yy",
                {"momentList": moments},
            )
            converter = self._converter(diagnostics=diagnostics)
            with patch("builtins.open", wraps=open) as tracked_open:
                entry = converter.build_entries()[0]
                completeness = converter._write_timeline_action_scripts((entry,))

            outside_accesses = [
                call
                for call in tracked_open.call_args_list
                if call.args
                and isinstance(call.args[0], (str, os.PathLike))
                and os.path.realpath(os.fspath(call.args[0]))
                == os.path.realpath(outside_source)
            ]
            self.assertEqual(outside_accesses, [])
            self.assertEqual(
                completeness,
                {("tl_paths", "timelines/tl_paths/tl_paths.yy"): False},
            )
            with open(outside_source, "r", encoding="utf-8") as outside_file:
                self.assertEqual(outside_file.read(), outside_contents)

        assert entry.metadata is not None
        raw_moments = entry.metadata["moments"]
        assert isinstance(raw_moments, list)
        typed_moments = cast(list[dict[str, object]], raw_moments)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

        self.assertEqual(len(typed_moments), len(expected_cases))
        for moment, (frame, field, case_name) in zip(
            typed_moments,
            expected_cases,
            strict=True,
        ):
            with self.subTest(field=field, case=case_name):
                self.assertEqual(moment["frame"], frame)
                self.assertEqual(
                    moment["actions"],
                    [
                        {"kind": "script", "script": f"scr_keep_{frame}"},
                        {
                            "kind": "callable",
                            "callable": f"callable_keep_{frame}",
                        },
                    ],
                )
                self.assertFalse(
                    os.path.exists(
                        os.path.join(
                            self.godot_dir,
                            "gm2godot",
                            "timelines",
                            f"tl_paths_{frame}.gd",
                        )
                    )
                )
        self.assertEqual(len(rejected), len(expected_cases))
        self.assertTrue(
            all(
                diagnostic.source_path == "timelines/tl_paths/tl_paths.yy"
                and diagnostic.resource == "tl_paths"
                and diagnostic.resource_type == "timeline"
                for diagnostic in rejected
            )
        )
        self.assertEqual(
            [diagnostic.manifest_entry for diagnostic in rejected],
            [field for _frame, field, _case_name in expected_cases],
        )

    def test_timeline_transpile_failure_is_skipped_and_omits_script_path(self) -> None:
        _write_yyp(self.gm_dir, [("timelines", "tl_blocked")])
        self._write_resource(
            "timelines",
            "tl_blocked",
            "GMTimeline",
            "folders/Timelines.yy",
            {"momentList": [{"moment": 3, "eventFile": "Moment_3.gml"}]},
        )
        source_path = os.path.join(
            self.gm_dir,
            "timelines",
            "tl_blocked",
            "Moment_3.gml",
        )
        _write_file(source_path, "if (\n")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                skipped=1,
            ),
        )
        timeline_script_path = os.path.join(
            self.godot_dir,
            "gm2godot",
            "timelines",
            "tl_blocked_3.gd",
        )
        self.assertFalse(os.path.exists(timeline_script_path))
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry_script = registry_file.read()
        self.assertNotIn(
            '"script_path": "res://gm2godot/timelines/tl_blocked_3.gd"',
            registry_script,
        )
        transpile_failures = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-GML-TRANSPILE"
        ]
        self.assertEqual(len(transpile_failures), 1)
        self.assertEqual(transpile_failures[0].source_path, source_path)
        self.assertEqual(transpile_failures[0].line, 1)
        self.assertEqual(transpile_failures[0].column, 5)
        self.assertEqual(transpile_failures[0].resource, "tl_blocked")
        self.assertEqual(transpile_failures[0].resource_type, "timeline")
        self.assertEqual(transpile_failures[0].event, "moment 3")

    def test_safe_timeline_completes_when_other_source_cannot_be_read(self) -> None:
        _write_yyp(
            self.gm_dir,
            [
                ("timelines", "tl_blocked"),
                ("timelines", "tl_safe"),
            ],
        )
        self._write_resource(
            "timelines",
            "tl_blocked",
            "GMTimeline",
            "folders/Timelines.yy",
            {"momentList": [{"moment": 2, "eventFile": "Moment_2.gml"}]},
        )
        self._write_resource(
            "timelines",
            "tl_safe",
            "GMTimeline",
            "folders/Timelines.yy",
            {"momentList": [{"moment": 4, "eventFile": "Moment_4.gml"}]},
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "timelines",
                "tl_safe",
                "Moment_4.gml",
            ),
            "score += 1;\n",
        )
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        safe_script_path = os.path.join(
            self.godot_dir,
            "gm2godot",
            "timelines",
            "tl_safe_4.gd",
        )
        blocked_script_path = os.path.join(
            self.godot_dir,
            "gm2godot",
            "timelines",
            "tl_blocked_2.gd",
        )
        self.assertTrue(os.path.isfile(safe_script_path))
        self.assertFalse(os.path.exists(blocked_script_path))
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry_script = registry_file.read()
        self.assertIn(
            '"script_path": "res://gm2godot/timelines/tl_safe_4.gd"',
            registry_script,
        )
        self.assertNotIn(
            '"script_path": "res://gm2godot/timelines/tl_blocked_2.gd"',
            registry_script,
        )

    def test_timeline_disk_discovery_skips_directory_link_outside_project(self) -> None:
        _write_yyp(self.gm_dir, [])
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_timeline = os.path.join(outside_dir, "tl_paths")
            _write_file(
                os.path.join(outside_timeline, "Moment_7.gml"),
                "x = 7;\n",
            )
            linked_directory = os.path.join(
                self.gm_dir,
                "timelines",
                "tl_paths",
            )
            os.makedirs(os.path.dirname(linked_directory))
            try:
                os.symlink(outside_timeline, linked_directory)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")
            owner_source_path = "timelines/tl_owner/tl_paths.yy"
            _write_json(
                os.path.join(self.gm_dir, *owner_source_path.split("/")),
                _minimal_yy(
                    "tl_paths",
                    "GMTimeline",
                    "folders/Timelines.yy",
                ),
            )
            resource = _ProjectResource(
                kind="timelines",
                name="tl_paths",
                yy_path=os.path.join(linked_directory, "tl_paths.yy"),
                source_path=owner_source_path,
                raw_data={},
            )

            actions = self._converter(
                diagnostics=diagnostics,
            )._timeline_discovered_source_actions(resource)

        self.assertEqual(actions, [])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, resource.source_path)
        self.assertEqual(rejected[0].resource, resource.name)
        self.assertEqual(rejected[0].resource_type, "timeline")
        self.assertEqual(rejected[0].manifest_entry, "timeline source directory")

    def test_timeline_disk_discovery_skips_file_link_outside_project(self) -> None:
        _write_yyp(self.gm_dir, [("timelines", "tl_paths")])
        self._write_resource(
            "timelines",
            "tl_paths",
            "GMTimeline",
            "folders/Timelines.yy",
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = os.path.join(outside_dir, "Moment_7.gml")
            _write_file(outside_source, "x = 7;\n")
            linked_source = os.path.join(
                self.gm_dir,
                "timelines",
                "tl_paths",
                "Moment_7.gml",
            )
            try:
                os.symlink(outside_source, linked_source)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entry = self._converter(diagnostics=diagnostics).build_entries()[0]

        assert entry.metadata is not None
        self.assertEqual(entry.metadata["moments"], [])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "timelines/tl_paths/tl_paths.yy")
        self.assertEqual(rejected[0].manifest_entry, "discovered timeline moment source")

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
        diagnostics = DiagnosticCollector()

        entries = self._converter(diagnostics=diagnostics).build_entries()
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

        self.assertEqual([entry.name for entry in entries], ["s_player"])
        self.assertEqual(
            [
                (
                    diagnostic.source_path,
                    diagnostic.resource,
                    diagnostic.resource_type,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            ],
            [
                (
                    "AssetRegistryTest.yyp",
                    "s_traversal",
                    "GMSprite",
                    "resources[1].id.path",
                ),
                (
                    "AssetRegistryTest.yyp",
                    "s_absolute",
                    "project",
                    "resources[2].id.path",
                ),
            ],
        )
        self.assertTrue(
            any(
                "escapes the selected GameMaker project root" in message
                for message in self.logs
            ),
            self.logs,
        )
        self.assertTrue(
            any(
                "must be relative" in message
                for message in self.logs
            ),
            self.logs,
        )

    def test_malformed_yyp_resource_paths_are_diagnosed_without_rereading_yyp(
        self,
    ) -> None:
        self._write_resource(
            "sprites",
            "s_safe",
            "GMSprite",
            "folders/Sprites.yy",
        )
        self._write_resource(
            "rooms",
            "r_safe",
            "GMRoom",
            "folders/Rooms.yy",
        )
        yyp_path = os.path.join(self.gm_dir, "AssetRegistryTest.yyp")
        malformed_entries: list[dict[str, object]] = [
            {"id": {"name": "s_missing"}, "resourceType": "GMSprite"},
            {
                "id": {"name": "s_null", "path": None},
                "resourceType": "GMSprite",
            },
            {
                "id": {"name": "s_empty", "path": ""},
                "resourceType": "GMSprite",
            },
            {
                "id": {"name": "s_non_string", "path": 7},
                "resourceType": "GMSprite",
            },
        ]
        _write_json(
            yyp_path,
            {
                "resources": [
                    *malformed_entries,
                    _resource_entry("sprites", "s_safe"),
                    _resource_entry("rooms", "r_safe"),
                ],
                "RoomOrderNodes": [
                    {
                        "roomId": {
                            "name": "r_safe",
                            "path": "rooms/r_safe/r_safe.yy",
                        }
                    }
                ],
                "resourceType": "GMProject",
            },
        )
        diagnostics = DiagnosticCollector()

        with patch("builtins.open", wraps=open) as tracked_open:
            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual(
            {entry.name for entry in entries},
            {"r_safe", "s_safe"},
        )
        yyp_reads = [
            call
            for call in tracked_open.call_args_list
            if call.args
            and isinstance(call.args[0], str)
            and os.path.realpath(call.args[0]) == os.path.realpath(yyp_path)
        ]
        self.assertEqual(len(yyp_reads), 1, yyp_reads)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), len(malformed_entries), rejected)
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            {"s_empty", "s_missing", "s_non_string", "s_null"},
        )
        self.assertTrue(
            all(
                diagnostic.source_path == "AssetRegistryTest.yyp"
                and diagnostic.manifest_entry
                == f"resources[{index}].id.path"
                for index, diagnostic in enumerate(rejected)
            )
        )

    def test_manifest_path_cannot_normalize_into_another_resource_family(
        self,
    ) -> None:
        wrong_family_path = os.path.join(
            self.gm_dir,
            "objects",
            "o_cross_family",
            "o_cross_family.yy",
        )
        _write_json(
            wrong_family_path,
            _minimal_yy(
                "o_cross_family",
                "GMObject",
                "folders/Objects.yy",
            ),
        )
        self._write_resource(
            "scripts",
            "scr_safe",
            "GMScript",
            "folders/Scripts.yy",
        )
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "o_cross_family",
                            "path": (
                                "scripts/../objects/o_cross_family/"
                                "o_cross_family.yy"
                            ),
                        }
                    },
                    _resource_entry("scripts", "scr_safe"),
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)
        read_paths: list[str] = []
        original_read = converter._read_yy_file

        def tracking_read(path: str) -> dict[str, object] | None:
            read_paths.append(os.path.realpath(path))
            return original_read(path)

        with patch.object(converter, "_read_yy_file", side_effect=tracking_read):
            entries = converter.build_entries()

        self.assertEqual([entry.name for entry in entries], ["scr_safe"])
        self.assertNotIn(os.path.realpath(wrong_family_path), read_paths)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "AssetRegistryTest.yyp")
        self.assertEqual(rejected[0].resource, "o_cross_family")
        self.assertEqual(rejected[0].resource_type, "script")
        self.assertEqual(
            rejected[0].manifest_entry,
            "resources[0].id.path",
        )

    def test_declared_resource_and_preferred_script_paths_are_authoritative(self) -> None:
        declared_source_path = "scripts/custom/location/source.yy"
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "scr_declared",
                            "path": declared_source_path,
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        script_metadata = _minimal_yy(
            "scr_declared",
            "GMScript",
            "folders/Scripts/Declared.yy",
        )
        _write_json(
            os.path.join(self.gm_dir, *declared_source_path.split("/")),
            script_metadata,
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "scripts",
                "custom",
                "location",
                "scr_declared.gml",
            ),
            "function from_declared_source() { return 41; }\n",
        )
        _write_json(
            os.path.join(
                self.gm_dir,
                "scripts",
                "scr_declared",
                "scr_declared.yy",
            ),
            script_metadata,
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "scripts",
                "scr_declared",
                "scr_declared.gml",
            ),
            "function from_reconstructed_source() { return 99; }\n",
        )

        entries = self._converter().build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertEqual(by_name["scr_declared"].source_path, declared_source_path)
        self.assertIn("from_declared_source", by_name)
        self.assertNotIn("from_reconstructed_source", by_name)
        self.assertEqual(
            by_name["from_declared_source"].metadata,
            {
                "script_function": True,
                "script_asset": "scr_declared",
                "script_source_path": declared_source_path,
            },
        )

    def test_script_fallback_revalidates_sources_and_links_diagnostic_to_yy(self) -> None:
        declared_source_path = "scripts/custom/location/source.yy"
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "scr_fallback",
                            "path": declared_source_path,
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        script_directory = os.path.join(
            self.gm_dir,
            "scripts",
            "custom",
            "location",
        )
        _write_json(
            os.path.join(script_directory, "source.yy"),
            _minimal_yy(
                "scr_fallback",
                "GMScript",
                "folders/Scripts/Declared.yy",
            ),
        )
        _write_file(
            os.path.join(script_directory, "z_valid.gml"),
            "function from_valid_fallback() { return 7; }\n",
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_source = os.path.join(outside_dir, "a_external.gml")
            _write_file(
                outside_source,
                "function from_external_fallback() { return 99; }\n",
            )
            try:
                os.symlink(
                    outside_source,
                    os.path.join(script_directory, "a_external.gml"),
                )
                os.symlink(
                    outside_source,
                    os.path.join(script_directory, "scr_fallback.gml"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        names = {entry.name for entry in entries}
        self.assertIn("from_valid_fallback", names)
        self.assertNotIn("from_external_fallback", names)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            all(
                diagnostic.source_path == declared_source_path
                and diagnostic.resource == "scr_fallback"
                and diagnostic.resource_type == "script"
                for diagnostic in rejected
            )
        )
        self.assertEqual(
            {diagnostic.manifest_entry for diagnostic in rejected},
            {"preferred script source", "discovered script source"},
        )

    def test_script_name_alias_cannot_select_normalized_preferred_source(
        self,
    ) -> None:
        owner_source_path = "scripts/owner/custom.yy"
        owner_path = os.path.join(
            self.gm_dir,
            *owner_source_path.split("/"),
        )
        _write_json(
            owner_path,
            _minimal_yy(
                "nested/../safe",
                "GMScript",
                "folders/Scripts.yy",
            ),
        )
        alias_target = os.path.join(
            self.gm_dir,
            "scripts",
            "owner",
            "safe.gml",
        )
        safe_fallback = os.path.join(
            self.gm_dir,
            "scripts",
            "owner",
            "z_fallback.gml",
        )
        _write_file(
            alias_target,
            "function from_normalized_alias() { return 99; }\n",
        )
        _write_file(
            safe_fallback,
            "function from_safe_fallback() { return 7; }\n",
        )
        diagnostics = DiagnosticCollector()
        resource = _ProjectResource(
            kind="scripts",
            name="nested/../safe",
            yy_path=owner_path,
            source_path=owner_source_path,
            raw_data={},
        )

        selected = self._converter(
            diagnostics=diagnostics,
        )._script_source_gml_path(resource)

        self.assertEqual(selected, safe_fallback)
        self.assertNotEqual(selected, alias_target)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, owner_source_path)
        self.assertEqual(rejected[0].resource, "nested/../safe")
        self.assertEqual(rejected[0].resource_type, "script")
        self.assertEqual(
            rejected[0].manifest_entry,
            "preferred script source",
        )

    def test_manifest_resource_symlink_is_skipped_with_yyp_diagnostic(self) -> None:
        declared_source_path = "sprites/linked/custom.yy"
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "s_external",
                            "path": declared_source_path,
                        }
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yy = os.path.join(outside_dir, "custom.yy")
            _write_json(
                outside_yy,
                _minimal_yy(
                    "s_external",
                    "GMSprite",
                    "folders/Sprites.yy",
                ),
            )
            linked_yy = os.path.join(
                self.gm_dir,
                *declared_source_path.split("/"),
            )
            os.makedirs(os.path.dirname(linked_yy), exist_ok=True)
            try:
                os.symlink(outside_yy, linked_yy)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual(entries, ())
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "AssetRegistryTest.yyp")
        self.assertEqual(rejected[0].resource, "s_external")
        self.assertEqual(rejected[0].resource_type, "GMSprite")
        self.assertEqual(rejected[0].manifest_entry, "resources[0].id.path")

    def test_included_file_registry_does_not_follow_directory_symlinks(
        self,
    ) -> None:
        real_directory = os.path.join(self.gm_dir, "datafiles", "real")
        payload_path = os.path.join(real_directory, "payload.txt")
        _write_file(payload_path, "contained payload")
        alias_directory = os.path.join(self.gm_dir, "datafiles", "alias")
        try:
            os.symlink(real_directory, alias_directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")

        entries = self._converter().build_entries()
        included_entries = [
            entry for entry in entries if entry.kind == "included_files"
        ]

        self.assertEqual(len(included_entries), 1)
        self.assertEqual(
            included_entries[0].source_path,
            "datafiles/real/payload.txt",
        )
        self.assertEqual(
            included_entries[0].godot_path,
            "res://included_files/real/payload.txt",
        )

    def test_included_file_registry_paths_match_converted_outputs(self) -> None:
        payloads = {
            "Config/My File.BIN": b"\x00nested\xffpayload",
            "Foo Bar/item.bin": b"normalized nested-prefix payload",
            "Read Me.txt": b"normalized collision payload",
            "foo_bar": b"normalized blocking-file payload",
            "read_me.txt": b"canonical payload",
            "read_me_2.txt": b"natural suffix payload",
        }
        for relative_path, payload in payloads.items():
            source_path = os.path.join(
                self.gm_dir,
                "datafiles",
                *relative_path.split("/"),
            )
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            with open(source_path, "wb") as source_file:
                source_file.write(payload)

        registry_converter = self._converter()
        entries = {
            entry.name: entry
            for entry in registry_converter.build_entries()
            if entry.kind == "included_files"
        }

        self.assertEqual(set(entries), set(payloads))
        self.assertEqual(
            {name: entry.godot_path for name, entry in entries.items()},
            {
                "Config/My File.BIN": (
                    "res://included_files/config/my_file.bin"
                ),
                "Foo Bar/item.bin": (
                    "res://included_files/foo_bar/item.bin"
                ),
                "Read Me.txt": "res://included_files/read_me_3.txt",
                "foo_bar": "res://included_files/foo_bar_2",
                "read_me.txt": "res://included_files/read_me.txt",
                "read_me_2.txt": "res://included_files/read_me_2.txt",
            },
        )
        self.assertEqual(
            {name: entry.source_path for name, entry in entries.items()},
            {
                name: "datafiles/" + name
                for name in payloads
            },
        )

        resources = registry_converter._ordered_project_resources()
        self.assertEqual(
            registry_converter._stable_godot_paths(resources),
            registry_converter._stable_godot_paths(reversed(resources)),
        )

        included_converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        included_converter.convert_included_files()

        for name, payload in payloads.items():
            output_path = os.path.join(
                self.godot_dir,
                *entries[name].godot_path.removeprefix("res://").split("/"),
            )
            self.assertTrue(os.path.isfile(output_path), output_path)
            with open(output_path, "rb") as output_file:
                self.assertEqual(output_file.read(), payload)

    def test_convert_all_omits_absent_included_file_output(self) -> None:
        self._write_included_source("payload.bin", b"current payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                skipped=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertNotIn('"name": "payload.bin"', registry_file.read())
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].source_path, "datafiles/payload.bin")
        self.assertEqual(unavailable[0].resource, "payload.bin")
        self.assertEqual(unavailable[0].resource_type, "included_file")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "generated Included File output",
        )

    def test_convert_all_omits_stale_included_file_output(self) -> None:
        self._write_included_source("payload.bin", b"current payload")
        self._write_included_output("payload.bin", b"stale payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                skipped=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertNotIn('"name": "payload.bin"', registry_file.read())
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)

    def test_convert_all_filters_colliders_after_full_path_planning(self) -> None:
        self._write_included_source("Read Me.txt", b"suffixed payload")
        self._write_included_source("read_me.txt", b"canonical payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)
        planned = {
            entry.name: entry.godot_path
            for entry in converter.build_entries()
            if entry.kind == "included_files"
        }
        self.assertEqual(
            planned,
            {
                "Read Me.txt": "res://included_files/read_me_2.txt",
                "read_me.txt": "res://included_files/read_me.txt",
            },
        )
        self._write_included_output("read_me.txt", b"stale canonical output")
        self._write_included_output("read_me_2.txt", b"suffixed payload")

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "Read Me.txt"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/read_me_2.txt"',
            registry,
        )
        self.assertNotIn('"name": "read_me.txt"', registry)
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(
            [diagnostic.resource for diagnostic in unavailable],
            ["read_me.txt"],
        )

    def test_prior_single_collision_output_satisfies_no_new_collision_claim(
        self,
    ) -> None:
        self._write_included_source("Read Me.txt", b"original payload")
        self._emit_included_files()
        self._write_included_source("read_me.txt", b"new canonical payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                skipped=2,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertNotIn('"name": "Read Me.txt"', registry)
        self.assertNotIn('"name": "read_me.txt"', registry)
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(
            {diagnostic.resource for diagnostic in unavailable},
            {"Read Me.txt", "read_me.txt"},
        )

    def test_missing_canonical_reserves_suffix_for_matching_normalized_alias(
        self,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "read_me.txt",
                        "path": "datafiles/read_me.txt",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("Read Me.txt", b"alias payload")
        self._write_included_output("read_me_2.txt", b"alias payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "Read Me.txt"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/read_me_2.txt"',
            registry,
        )
        self.assertNotIn('"name": "read_me.txt"', registry)

    def test_identical_stale_canonical_output_cannot_satisfy_normalized_alias(
        self,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "read_me.txt",
                        "path": "datafiles/read_me.txt",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("Read Me.txt", b"identical alias payload")
        self._write_included_output("read_me.txt", b"identical alias payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=1,
                skipped=2,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertNotIn('"name": "Read Me.txt"', registry)
        self.assertNotIn('"name": "read_me.txt"', registry)
        unavailable_outputs = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(
            [diagnostic.resource for diagnostic in unavailable_outputs],
            ["Read Me.txt"],
        )

    def test_missing_natural_suffix_reserves_third_normalized_alias_path(
        self,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "read_me_2.txt",
                        "path": "datafiles/read_me_2.txt",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("read_me.txt", b"canonical payload")
        self._write_included_source("Read Me.txt", b"alias payload")
        self._write_included_output("read_me.txt", b"canonical payload")
        self._write_included_output("read_me_3.txt", b"alias payload")
        converter = self._converter()

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "read_me.txt"', registry)
        self.assertIn('"name": "Read Me.txt"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/read_me_3.txt"',
            registry,
        )
        self.assertNotIn('"name": "read_me_2.txt"', registry)

    def test_missing_nested_alias_reserves_suffix_for_blocking_file(self) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "item.txt",
                        "path": "datafiles/Foo Bar/item.txt",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("foo_bar", b"blocking file payload")
        self._write_included_output("foo_bar_2", b"blocking file payload")
        converter = self._converter()

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "foo_bar"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/foo_bar_2"',
            registry,
        )
        self.assertNotIn('"name": "Foo Bar/item.txt"', registry)

    def test_rejected_traversal_does_not_reserve_safe_alias_basename(
        self,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "read_me.txt",
                        "path": "datafiles/../../outside/read_me.txt",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("Read Me.txt", b"alias payload")
        self._write_included_output("read_me.txt", b"alias payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "Read Me.txt"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/read_me.txt"',
            registry,
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_convert_all_advertises_matching_included_file_output(self) -> None:
        self._write_included_source("payload.bin", b"matching payload")
        self._write_included_output("payload.bin", b"matching payload")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertIn('"name": "payload.bin"', registry_file.read())
        self.assertFalse(
            any(
                diagnostic.code
                == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_windows_path_handle_fingerprint_match_ignores_only_ctime(
        self,
    ) -> None:
        baseline = (11, 22, 33, 44, 55)
        ctime_only_drift = (11, 22, 33, 44, 99)
        real_drift = {
            "device": (12, 22, 33, 44, 55),
            "inode": (11, 23, 33, 44, 55),
            "size": (11, 22, 34, 44, 55),
            "mtime": (11, 22, 33, 45, 55),
        }

        with patch.object(
            asset_registry_module,
            "_uses_windows_included_file_path_handle_semantics",
            return_value=True,
        ):
            self.assertTrue(
                asset_registry_module._included_file_path_handle_fingerprints_match(
                    baseline,
                    ctime_only_drift,
                )
            )
            for field, fingerprint in real_drift.items():
                with self.subTest(field=field):
                    self.assertFalse(
                        asset_registry_module._included_file_path_handle_fingerprints_match(
                            baseline,
                            fingerprint,
                        )
                    )

        with patch.object(
            asset_registry_module,
            "_uses_windows_included_file_path_handle_semantics",
            return_value=False,
        ):
            self.assertFalse(
                asset_registry_module._included_file_path_handle_fingerprints_match(
                    baseline,
                    ctime_only_drift,
                )
            )

    def test_windows_fallback_rejects_same_inode_output_change(self) -> None:
        payload = b"GOOD"
        self._write_included_source("payload.bin", payload)
        self._write_included_output("payload.bin", payload)
        source_path = os.path.join(
            self.gm_dir,
            "datafiles",
            "payload.bin",
        )
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        output_stat = os.lstat(output_path)
        converter = self._converter()
        original_match = asset_registry_module._included_file_streams_match
        original_fingerprint = (
            asset_registry_module._included_file_content_fingerprint
        )
        original_verify = converter._verify_included_file_output_fallback
        verify_calls = 0
        mutated = False

        def compare_then_mutate(
            source_file: BinaryIO,
            output_file: BinaryIO,
        ) -> tuple[bool, str, str]:
            nonlocal mutated
            matches = original_match(source_file, output_file)
            with open(output_path, "r+b", buffering=0) as mutator:
                mutator.write(b"EVIL")
                os.fsync(mutator.fileno())
            os.utime(
                output_path,
                ns=(output_stat.st_atime_ns, output_stat.st_mtime_ns),
            )
            if os.lstat(output_path).st_mtime_ns != output_stat.st_mtime_ns:
                self.skipTest("Filesystem cannot restore nanosecond mtime")
            mutated = True
            return matches

        def verify_initial_path_state(
            directory_identities: list[tuple[str, tuple[int, int]]],
            path: str,
            expected_fingerprint: tuple[int, int, int, int, int],
        ) -> None:
            nonlocal verify_calls
            verify_calls += 1
            if verify_calls == 1:
                original_verify(
                    directory_identities,
                    path,
                    expected_fingerprint,
                )

        def windows_creation_time_fingerprint(
            file_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int]:
            fingerprint = original_fingerprint(file_stat)
            return (*fingerprint[:4], output_stat.st_ctime_ns)

        with open(source_path, "rb") as source_file:
            with (
                patch.object(
                    asset_registry_module,
                    "_uses_windows_included_file_path_handle_semantics",
                    return_value=True,
                ),
                patch.object(
                    asset_registry_module,
                    "_included_file_streams_match",
                    side_effect=compare_then_mutate,
                ),
                patch.object(
                    asset_registry_module,
                    "_included_file_content_fingerprint",
                    side_effect=windows_creation_time_fingerprint,
                ),
                patch.object(
                    converter,
                    "_verify_included_file_output_fallback",
                    side_effect=verify_initial_path_state,
                ),
                self.assertRaisesRegex(OSError, "changed during validation"),
            ):
                converter._included_file_output_matches_fallback(
                    output_path,
                    ("included_files", "payload.bin"),
                    source_file,
                )

        self.assertTrue(mutated)
        self.assertEqual(verify_calls, 1)
        with open(output_path, "rb") as output_file:
            self.assertEqual(output_file.read(), b"EVIL")

    def test_windows_fallback_rejects_same_inode_source_change(self) -> None:
        payload = b"GOOD"
        self._write_included_source("payload.bin", payload)
        self._write_included_output("payload.bin", payload)
        source_path = os.path.join(
            self.gm_dir,
            "datafiles",
            "payload.bin",
        )
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        source_stat = os.lstat(source_path)
        converter = self._converter()
        original_match = asset_registry_module._included_file_streams_match
        mutated = False

        def compare_then_mutate(
            source_file: BinaryIO,
            output_file: BinaryIO,
        ) -> tuple[bool, str, str]:
            nonlocal mutated
            result = original_match(source_file, output_file)
            with open(source_path, "r+b", buffering=0) as mutator:
                mutator.write(b"EVIL")
                os.fsync(mutator.fileno())
            os.utime(
                source_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )
            if os.lstat(source_path).st_mtime_ns != source_stat.st_mtime_ns:
                self.skipTest("Filesystem cannot restore nanosecond mtime")
            mutated = True
            return result

        with open(source_path, "rb") as source_file:
            with (
                patch.object(
                    asset_registry_module,
                    "_included_file_streams_match",
                    side_effect=compare_then_mutate,
                ),
                self.assertRaisesRegex(OSError, "source changed during validation"),
            ):
                converter._included_file_output_matches_fallback(
                    output_path,
                    ("included_files", "payload.bin"),
                    source_file,
                )

        self.assertTrue(mutated)
        with open(source_path, "rb") as source_file:
            self.assertEqual(source_file.read(), b"EVIL")
        with open(output_path, "rb") as output_file:
            self.assertEqual(output_file.read(), b"GOOD")

    def test_convert_all_omits_redirected_included_file_output(self) -> None:
        self._write_included_source("payload.bin", b"matching payload")
        referent_path = os.path.join(self.godot_dir, "matching-payload.bin")
        with open(referent_path, "wb") as referent_file:
            referent_file.write(b"matching payload")
        output_directory = os.path.join(self.godot_dir, "included_files")
        os.makedirs(output_directory, exist_ok=True)
        output_path = os.path.join(output_directory, "payload.bin")
        try:
            os.symlink(referent_path, output_path)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                skipped=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertNotIn('"name": "payload.bin"', registry_file.read())
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-OUTPUT-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)

    def test_output_delete_at_registry_publish_boundary_leaves_no_registry(
        self,
    ) -> None:
        self._write_included_source("payload.bin", b"matching payload")
        self._write_included_output("payload.bin", b"matching payload")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        converter = self._converter()
        real_revalidate = converter.revalidate_published_entries
        validation_calls = 0

        def delete_then_revalidate(
            entries: tuple[AssetRegistryEntry, ...],
        ) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 1:
                os.unlink(output_path)
            real_revalidate(entries)

        with (
            patch.object(
                converter,
                "revalidate_published_entries",
                side_effect=delete_then_revalidate,
            ),
            self.assertRaisesRegex(
                OSError,
                "publication inputs changed",
            ),
        ):
            converter.convert_all()

        self.assertEqual(validation_calls, 1)
        self.assertFalse(os.path.exists(registry_path))
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                failed=1,
            ),
        )

    def test_output_byte_change_after_registry_publish_removes_registry(
        self,
    ) -> None:
        self._write_included_source("payload.bin", b"matching payload")
        self._write_included_output("payload.bin", b"matching payload")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        converter = self._converter()
        real_revalidate = converter.revalidate_published_entries
        validation_calls = 0

        def mutate_then_revalidate(
            entries: tuple[AssetRegistryEntry, ...],
        ) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                with open(output_path, "wb") as output_file:
                    output_file.write(b"changed after publication")
            real_revalidate(entries)

        with (
            patch.object(
                converter,
                "revalidate_published_entries",
                side_effect=mutate_then_revalidate,
            ),
            self.assertRaisesRegex(
                OSError,
                "publication inputs changed",
            ),
        ):
            converter.convert_all()

        self.assertEqual(validation_calls, 2)
        self.assertFalse(os.path.exists(registry_path))
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                failed=1,
            ),
        )

    def test_project_yyp_link_is_rejected_before_disk_fallback(self) -> None:
        self._write_resource(
            "sprites",
            "s_local",
            "GMSprite",
            "folders/Sprites.yy",
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yyp = os.path.join(outside_dir, "External.yyp")
            _write_json(outside_yyp, {"resources": []})
            try:
                os.symlink(
                    outside_yyp,
                    os.path.join(self.gm_dir, "External.yyp"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual([entry.name for entry in entries], ["s_local"])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertIsNone(rejected[0].source_path)
        self.assertEqual(rejected[0].resource_type, "project")
        self.assertEqual(rejected[0].manifest_entry, "External.yyp")

    def test_disk_fallback_revalidates_resource_directory_and_yy_links(self) -> None:
        self._write_resource(
            "sprites",
            "s_local",
            "GMSprite",
            "folders/Sprites.yy",
        )
        linked_yy_directory = os.path.join(
            self.gm_dir,
            "sprites",
            "s_linked_yy",
        )
        os.makedirs(linked_yy_directory)
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_resource_directory = os.path.join(outside_dir, "s_linked_dir")
            os.makedirs(outside_resource_directory)
            _write_json(
                os.path.join(outside_resource_directory, "s_linked_dir.yy"),
                _minimal_yy(
                    "s_linked_dir",
                    "GMSprite",
                    "folders/Sprites.yy",
                ),
            )
            outside_yy = os.path.join(outside_dir, "s_linked_yy.yy")
            _write_json(
                outside_yy,
                _minimal_yy(
                    "s_linked_yy",
                    "GMSprite",
                    "folders/Sprites.yy",
                ),
            )
            try:
                os.symlink(
                    outside_resource_directory,
                    os.path.join(self.gm_dir, "sprites", "s_linked_dir"),
                )
                os.symlink(
                    outside_yy,
                    os.path.join(linked_yy_directory, "s_linked_yy.yy"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual([entry.name for entry in entries], ["s_local"])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(
            {
                (
                    diagnostic.source_path,
                    diagnostic.resource,
                    diagnostic.resource_type,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            },
            {
                (
                    "sprites",
                    "s_linked_dir",
                    "sprite",
                    "disk fallback resource directory",
                ),
                (
                    "sprites/s_linked_yy",
                    "s_linked_yy",
                    "sprite",
                    "disk fallback resource metadata",
                ),
            },
        )

    def test_disk_fallback_validates_canonical_resource_family_before_read(
        self,
    ) -> None:
        self._write_resource(
            "sprites",
            "s_local",
            "GMSprite",
            "folders/Sprites.yy",
        )
        same_family_target = os.path.join(
            self.gm_dir,
            "sprites",
            "targets",
            "shared.yy",
        )
        cross_family_target = os.path.join(
            self.gm_dir,
            "objects",
            "targets",
            "shared.yy",
        )
        _write_json(
            same_family_target,
            _minimal_yy(
                "s_alias_target",
                "GMSprite",
                "folders/Sprites.yy",
            ),
        )
        _write_json(
            cross_family_target,
            _minimal_yy(
                "o_cross_target",
                "GMObject",
                "folders/Objects.yy",
            ),
        )
        same_family_alias = os.path.join(
            self.gm_dir,
            "sprites",
            "s_alias",
            "s_alias.yy",
        )
        cross_family_alias = os.path.join(
            self.gm_dir,
            "sprites",
            "s_cross",
            "s_cross.yy",
        )
        os.makedirs(os.path.dirname(same_family_alias))
        os.makedirs(os.path.dirname(cross_family_alias))
        try:
            os.symlink(same_family_target, same_family_alias)
            os.symlink(cross_family_target, cross_family_alias)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Symbolic links are unavailable: {exc}")
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)
        read_paths: list[str] = []
        original_read = converter._read_yy_file

        def tracking_read(path: str) -> dict[str, object] | None:
            read_paths.append(os.path.realpath(path))
            return original_read(path)

        with patch.object(converter, "_read_yy_file", side_effect=tracking_read):
            resources = converter._resources_from_disk()

        self.assertEqual(
            {resource.name for resource in resources},
            {"s_alias", "s_local"},
        )
        self.assertIn(os.path.realpath(same_family_target), read_paths)
        self.assertNotIn(os.path.realpath(cross_family_target), read_paths)
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "sprites/s_cross")
        self.assertEqual(rejected[0].resource, "s_cross")
        self.assertEqual(rejected[0].resource_type, "sprite")
        self.assertEqual(
            rejected[0].manifest_entry,
            "disk fallback resource metadata",
        )

    def test_disk_fallback_revalidates_kind_directory_link(self) -> None:
        self._write_resource(
            "objects",
            "o_local",
            "GMObject",
            "folders/Objects.yy",
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_sprites = os.path.join(outside_dir, "sprites")
            _write_json(
                os.path.join(outside_sprites, "s_external", "s_external.yy"),
                _minimal_yy(
                    "s_external",
                    "GMSprite",
                    "folders/Sprites.yy",
                ),
            )
            try:
                os.symlink(
                    outside_sprites,
                    os.path.join(self.gm_dir, "sprites"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual([entry.name for entry in entries], ["o_local"])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertIsNone(rejected[0].source_path)
        self.assertEqual(rejected[0].resource_type, "sprite")
        self.assertEqual(
            rejected[0].manifest_entry,
            "disk fallback kind directory",
        )

    def test_datafiles_discovery_preserves_targets_and_rejects_links(self) -> None:
        _write_file(
            os.path.join(self.gm_dir, "datafiles", "config", "game.json"),
            "{}",
        )
        diagnostics = DiagnosticCollector()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_file = os.path.join(outside_dir, "external.txt")
            outside_subdirectory = os.path.join(outside_dir, "external_directory")
            _write_file(outside_file, "external")
            os.makedirs(outside_subdirectory)
            _write_file(os.path.join(outside_subdirectory, "hidden.txt"), "hidden")
            try:
                os.symlink(
                    outside_file,
                    os.path.join(self.gm_dir, "datafiles", "escape.txt"),
                )
                os.symlink(
                    outside_subdirectory,
                    os.path.join(self.gm_dir, "datafiles", "external"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = self._converter(diagnostics=diagnostics).build_entries()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "config/game.json")
        self.assertEqual(entries[0].source_path, "datafiles/config/game.json")
        self.assertEqual(
            entries[0].godot_path,
            "res://included_files/config/game.json",
        )
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            all(
                diagnostic.source_path == "datafiles"
                and diagnostic.resource_type == "included_file"
                and diagnostic.manifest_entry == "discovered datafiles entry"
                for diagnostic in rejected
            )
        )

    def test_sound_output_uses_resolved_basename_and_rejects_escape(self) -> None:
        safe_yy_source = "sounds/declared/safe/custom.yy"
        unsafe_yy_source = "sounds/declared/unsafe/custom.yy"
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "snd_safe",
                            "path": safe_yy_source,
                        }
                    },
                    {
                        "id": {
                            "name": "snd_unsafe",
                            "path": unsafe_yy_source,
                        }
                    },
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        _write_json(
            os.path.join(self.gm_dir, *safe_yy_source.split("/")),
            _minimal_yy(
                "snd_safe",
                "GMSound",
                "folders/Sounds/Safe.yy",
                {
                    "soundFile": (
                        "${project_dir}/sounds/shared/theme.final.ogg"
                    )
                },
            ),
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "sounds",
                "shared",
                "theme.final.ogg",
            ),
            "audio",
        )
        _write_json(
            os.path.join(self.gm_dir, *unsafe_yy_source.split("/")),
            _minimal_yy(
                "snd_unsafe",
                "GMSound",
                "folders/Sounds/Unsafe.yy",
                {"soundFile": "../../../../../outside/escape.wav"},
            ),
        )
        diagnostics = DiagnosticCollector()

        entries = self._converter(diagnostics=diagnostics).build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertEqual(
            by_name["snd_safe"].godot_path,
            "res://sounds/safe/snd_safe/theme.final.ogg",
        )
        self.assertNotIn("shared", by_name["snd_safe"].godot_path)
        self.assertEqual(by_name["snd_unsafe"].godot_path, "")
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, unsafe_yy_source)
        self.assertEqual(rejected[0].resource, "snd_unsafe")
        self.assertEqual(rejected[0].resource_type, "sound")
        self.assertEqual(rejected[0].manifest_entry, "soundFile")

    def test_build_entries_includes_modern_script_function_assets(self) -> None:
        _write_yyp(self.gm_dir, [("scripts", "ending")])
        self._write_resource("scripts", "ending", "GMScript", "folders/Scripts/Game.yy")
        _write_file(
            os.path.join(self.gm_dir, "scripts", "ending", "ending.gml"),
            "function loadending() { return 1; }\n"
            "function saveending() { loadending(); }\n",
        )

        converter = self._converter()
        entries = converter.build_entries()
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

        registry_path = converter.convert_all()

        self.assertEqual(
            registry_path,
            os.path.join(self.godot_dir, ASSET_REGISTRY_RELATIVE_PATH),
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )

    def test_missing_only_manifest_asset_makes_converter_outcome_partial(
        self,
    ) -> None:
        _write_yyp(self.gm_dir, [("sprites", "s_missing")])
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
            max_workers=1,
        )

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"asset_registry": _EnabledSetting()},
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
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "s_missing")
        self.assertEqual(unavailable[0].resource_type, "sprite")
        self.assertEqual(unavailable[0].source_path, "AssetRegistryTest.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "resources[0].id.path",
        )

    def test_safe_missing_and_orphan_manifest_assets_have_strict_counts(
        self,
    ) -> None:
        _write_yyp(
            self.gm_dir,
            [
                ("sprites", "s_safe"),
                ("sprites", "s_missing"),
            ],
        )
        self._write_resource(
            "sprites",
            "s_safe",
            "GMSprite",
            "folders/Sprites.yy",
        )
        self._write_resource(
            "sprites",
            "s_orphan",
            "GMSprite",
            "folders/Sprites.yy",
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "s_safe"', registry)
        self.assertNotIn('"name": "s_missing"', registry)
        self.assertNotIn('"name": "s_orphan"', registry)
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "s_missing")

    def test_malformed_derived_registry_metadata_is_skipped_not_completed(
        self,
    ) -> None:
        declarations = (
            ("paths", "path_malformed"),
            ("animcurves", "curve_malformed"),
            ("extensions", "ExtensionMalformed"),
        )
        _write_yyp(self.gm_dir, declarations)
        for kind, name in declarations:
            _write_file(
                os.path.join(self.gm_dir, kind, name, name + ".yy"),
                "{ malformed json",
            )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=3, skipped=3),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertNotIn("path_malformed", registry)
        self.assertNotIn("curve_malformed", registry)
        self.assertNotIn("ExtensionMalformed", registry)

        with open(
            os.path.join(self.godot_dir, PATH_REGISTRY_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as path_registry_file:
            self.assertNotIn("path_malformed", path_registry_file.read())
        with open(
            os.path.join(
                self.godot_dir,
                ANIMATION_CURVE_REGISTRY_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as curve_registry_file:
            self.assertNotIn("curve_malformed", curve_registry_file.read())
        with open(
            os.path.join(
                self.godot_dir,
                EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as extension_report_file:
            extension_report = json.load(extension_report_file)
        self.assertEqual(extension_report["extensions"], [])

        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(
            {
                (diagnostic.resource, diagnostic.resource_type)
                for diagnostic in unavailable
            },
            {
                ("path_malformed", "path"),
                ("curve_malformed", "animation_curve"),
                ("ExtensionMalformed", "extension"),
            },
        )

    def test_empty_derived_registry_metadata_is_valid(self) -> None:
        declarations = (
            ("paths", "path_empty"),
            ("animcurves", "curve_empty"),
            ("extensions", "ExtensionEmpty"),
        )
        _write_yyp(self.gm_dir, declarations)
        for kind, name in declarations:
            _write_file(
                os.path.join(self.gm_dir, kind, name, name + ".yy"),
                "{}\n",
            )
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=3,
                executed=3,
                completed=3,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "path_empty"', registry)
        self.assertIn('"name": "curve_empty"', registry)
        self.assertIn('"name": "ExtensionEmpty"', registry)

        with open(
            os.path.join(self.godot_dir, PATH_REGISTRY_RELATIVE_PATH),
            "r",
            encoding="utf-8",
        ) as path_registry_file:
            self.assertIn('"name": "path_empty"', path_registry_file.read())
        with open(
            os.path.join(
                self.godot_dir,
                ANIMATION_CURVE_REGISTRY_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as curve_registry_file:
            self.assertIn('"name": "curve_empty"', curve_registry_file.read())
        with open(
            os.path.join(
                self.godot_dir,
                EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
            ),
            "r",
            encoding="utf-8",
        ) as extension_report_file:
            extension_report = json.load(extension_report_file)
        self.assertEqual(
            [entry["name"] for entry in extension_report["extensions"]],
            ["ExtensionEmpty"],
        )

    def test_metadata_read_race_is_skipped_not_completed(self) -> None:
        _write_yyp(self.gm_dir, [("paths", "path_disappears")])
        path_metadata = os.path.join(
            self.gm_dir,
            "paths",
            "path_disappears",
            "path_disappears.yy",
        )
        _write_json(
            path_metadata,
            _minimal_yy(
                "path_disappears",
                "GMPath",
                "folders/Paths.yy",
            ),
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)
        original_read = AssetRegistryConverter._read_yy_file

        def remove_before_read(
            active_converter: AssetRegistryConverter,
            yy_path: StrPath,
        ) -> JsonDict | None:
            os.unlink(os.fspath(yy_path))
            return original_read(active_converter, yy_path)

        with patch.object(
            AssetRegistryConverter,
            "_read_yy_file",
            new=remove_before_read,
        ):
            converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, skipped=1),
        )
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "path_disappears")

    def test_rejected_and_cross_family_declarations_are_skipped(self) -> None:
        cross_family_path = os.path.join(
            self.gm_dir,
            "objects",
            "scr_cross_family",
            "scr_cross_family.yy",
        )
        _write_json(
            cross_family_path,
            _minimal_yy(
                "scr_cross_family",
                "GMObject",
                "folders/Objects.yy",
            ),
        )
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "s_rejected",
                            "path": (
                                "sprites/../../outside/s_rejected/"
                                "s_rejected.yy"
                            ),
                        },
                        "resourceType": "GMSprite",
                    },
                    {
                        "id": {
                            "name": "scr_cross_family",
                            "path": (
                                "scripts/../objects/scr_cross_family/"
                                "scr_cross_family.yy"
                            ),
                        },
                        "resourceType": "GMScript",
                    },
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, skipped=2),
        )
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(
            {diagnostic.resource for diagnostic in unavailable},
            {"s_rejected", "scr_cross_family"},
        )
        self.assertTrue(
            all(
                diagnostic.source_path == "AssetRegistryTest.yyp"
                for diagnostic in unavailable
            )
        )
        source_rejections = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(
            {diagnostic.resource for diagnostic in source_rejections},
            {"s_rejected", "scr_cross_family"},
        )

    def test_duplicate_missing_manifest_declaration_is_accounted_once(
        self,
    ) -> None:
        declaration = ("sprites", "s_missing")
        _write_yyp(self.gm_dir, [declaration, declaration])
        converter = self._converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, skipped=1),
        )

    def test_valid_manifest_included_files_are_strictly_accounted(self) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "safe.json",
                        "path": "datafiles/config/safe.json",
                    },
                    {
                        "name": "missing.json",
                        "path": "datafiles/config/missing.json",
                    },
                    {
                        "name": "safe.json",
                        "path": "datafiles/config/safe.json",
                    },
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "datafiles",
                "config",
                "safe.json",
            ),
            "safe\n",
        )
        _write_file(
            os.path.join(self.gm_dir, "datafiles", "orphan.json"),
            "orphan\n",
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        self._emit_included_files()

        registry_path = converter.convert_all()

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
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "config/safe.json"', registry)
        self.assertNotIn('"name": "config/missing.json"', registry)
        self.assertIn('"name": "orphan.json"', registry)
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "config/missing.json")
        self.assertEqual(unavailable[0].resource_type, "included_file")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "IncludedFiles[1].path",
        )

    def test_nested_gmincludedfile_resource_is_one_logical_resource(self) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "safe.json",
                            "path": "datafiles/config/safe.json",
                        },
                        "resourceType": "GMIncludedFile",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        self._write_included_source("config/safe.json", b"safe payload")
        self._write_included_output("config/safe.json", b"safe payload")
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "config/safe.json"', registry)
        self.assertIn(
            '"godot_path": "res://included_files/config/safe.json"',
            registry,
        )

    def test_current_gamemaker_file_path_directory_combines_payload_name(
        self,
    ) -> None:
        _write_json(
            os.path.join(self.gm_dir, "AssetRegistryTest.yyp"),
            {
                "resources": [],
                "IncludedFiles": [
                    {
                        "name": "safe.json",
                        "filePath": "datafiles/config",
                    }
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        _write_file(
            os.path.join(
                self.gm_dir,
                "datafiles",
                "config",
                "safe.json",
            ),
            "safe\n",
        )
        diagnostics = DiagnosticCollector()
        converter = self._converter(diagnostics=diagnostics)

        self._emit_included_files()

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            registry = registry_file.read()
        self.assertIn('"name": "config/safe.json"', registry)
        self.assertFalse(
            any(
                diagnostic.code
                == "GM2GD-ASSET-REGISTRY-SOURCE-UNAVAILABLE"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_no_yyp_keeps_contained_disk_fallback_accounting(self) -> None:
        self._write_resource(
            "sprites",
            "s_fallback",
            "GMSprite",
            "folders/Sprites.yy",
        )
        converter = self._converter()

        entries = converter.build_entries()

        self.assertEqual([entry.name for entry in entries], ["s_fallback"])
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(),
        )

        registry_path = converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertIn('"name": "s_fallback"', registry_file.read())

    def test_output_exception_fails_every_logical_registry_resource(self) -> None:
        _write_yyp(
            self.gm_dir,
            [("sprites", "s_player"), ("objects", "o_player")],
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites.yy",
        )
        self._write_resource(
            "objects",
            "o_player",
            "GMObject",
            "folders/Objects.yy",
        )
        converter = self._converter()

        with patch(
            "src.conversion.asset_registry.write_path_registry",
            side_effect=RuntimeError("path registry failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "path registry failed"):
                converter.convert_all()

        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        self.assertFalse(os.path.exists(registry_path))
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                failed=2,
            ),
        )

    def test_later_output_exception_preserves_previous_registry(self) -> None:
        _write_yyp(self.gm_dir, [("sprites", "s_player")])
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites.yy",
        )
        converter = self._converter()
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        _write_file(registry_path, "previous registry\n")
        os.chmod(registry_path, 0o640)
        previous_stat = os.stat(registry_path)
        previous_identity = previous_stat.st_dev, previous_stat.st_ino
        previous_mode = stat.S_IMODE(previous_stat.st_mode)
        previous_writable = bool(previous_stat.st_mode & stat.S_IWRITE)

        with patch(
            "src.conversion.asset_registry.write_animation_curve_registry",
            side_effect=RuntimeError("animation registry failed"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "animation registry failed",
            ):
                converter.convert_all()

        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertEqual(registry_file.read(), "previous registry\n")
        current_stat = os.stat(registry_path)
        self.assertEqual(
            (current_stat.st_dev, current_stat.st_ino),
            previous_identity,
        )
        self.assertEqual(
            bool(current_stat.st_mode & stat.S_IWRITE),
            previous_writable,
        )
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(current_stat.st_mode),
                previous_mode,
            )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                failed=1,
            ),
        )

    def _auxiliary_output_path(self, output_kind: str) -> str:
        if output_kind == "group_report":
            return os.path.join(
                self.godot_dir,
                GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH,
            )
        return os.path.join(
            self.godot_dir,
            "gm2godot",
            "timelines",
            "tl_output_1.gd",
        )

    def _publish_auxiliary_output(self, output_kind: str) -> None:
        converter = self._converter()
        if output_kind == "group_report":
            converter._write_group_compatibility_report((), (), ())
            return
        source_path = os.path.join(
            self.gm_dir,
            "timelines",
            "tl_output",
            "Moment_1.gml",
        )
        _write_file(source_path, "timeline_value = 1;\n")
        self.assertTrue(
            converter._write_timeline_action_script(
                "tl_output",
                1,
                "timelines/tl_output/tl_output.yy",
                "timelines/tl_output/Moment_1.gml",
                "res://gm2godot/timelines/tl_output_1.gd",
                set(),
            )
        )

    def test_auxiliary_outputs_refuse_final_symlinks_without_mutating_referents(
        self,
    ) -> None:
        for output_kind in ("group_report", "timeline_script"):
            with self.subTest(output_kind=output_kind):
                output_path = self._auxiliary_output_path(output_kind)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                external_path = os.path.join(
                    self.gm_dir,
                    f"outside_{output_kind}.txt",
                )
                _write_file(external_path, "external sentinel\n")
                try:
                    os.symlink(external_path, output_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Symbolic links are unavailable: {error}")

                with self.assertRaisesRegex(OSError, "non-regular asset registry"):
                    self._publish_auxiliary_output(output_kind)

                self.assertTrue(os.path.islink(output_path))
                with open(external_path, "r", encoding="utf-8") as external_file:
                    self.assertEqual(external_file.read(), "external sentinel\n")
                os.unlink(output_path)

    def test_auxiliary_outputs_replace_hardlinks_without_mutating_referents(
        self,
    ) -> None:
        for output_kind in ("group_report", "timeline_script"):
            with self.subTest(output_kind=output_kind):
                output_path = self._auxiliary_output_path(output_kind)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                external_path = os.path.join(
                    self.gm_dir,
                    f"hardlink_{output_kind}.txt",
                )
                _write_file(external_path, "external sentinel\n")
                try:
                    os.link(external_path, output_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Hard links are unavailable: {error}")
                external_inode = os.stat(external_path).st_ino

                self._publish_auxiliary_output(output_kind)

                with open(external_path, "r", encoding="utf-8") as external_file:
                    self.assertEqual(external_file.read(), "external sentinel\n")
                self.assertNotEqual(os.stat(output_path).st_ino, external_inode)
                os.unlink(output_path)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_auxiliary_outputs_refuse_fifos_without_opening_them(self) -> None:
        for output_kind in ("group_report", "timeline_script"):
            with self.subTest(output_kind=output_kind):
                output_path = self._auxiliary_output_path(output_kind)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                os.mkfifo(output_path)

                with self.assertRaisesRegex(OSError, "non-regular asset registry"):
                    self._publish_auxiliary_output(output_kind)

                self.assertTrue(
                    stat.S_ISFIFO(os.lstat(output_path).st_mode),
                )
                os.unlink(output_path)

    def test_timeline_output_refuses_redirected_managed_ancestor(self) -> None:
        external_root = os.path.join(self.gm_dir, "outside_timeline_output")
        os.makedirs(os.path.join(external_root, "timelines"))
        managed_root = os.path.join(self.godot_dir, "gm2godot")
        try:
            os.symlink(external_root, managed_root)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                patcher = (
                    patch(
                        "src.conversion.asset_registry._confined_asset_output_supported",
                        return_value=False,
                    )
                    if force_fallback
                    else patch(
                        "src.conversion.asset_registry._confined_asset_output_supported",
                        wraps=None,
                    )
                )
                if force_fallback:
                    with patcher:
                        with self.assertRaisesRegex(
                            OSError,
                            "redirected asset-registry output directory",
                        ):
                            self._publish_auxiliary_output("timeline_script")
                else:
                    with self.assertRaisesRegex(
                        OSError,
                        "redirected asset-registry output directory",
                    ):
                        self._publish_auxiliary_output("timeline_script")

                self.assertEqual(os.listdir(os.path.join(external_root, "timelines")), [])

    def test_atomic_registry_publish_failure_preserves_previous_file(self) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)
        _write_file(registry_path, "previous registry\n")
        os.chmod(registry_path, 0o640)
        previous_stat = os.stat(registry_path)
        previous_identity = previous_stat.st_dev, previous_stat.st_ino
        previous_mode = stat.S_IMODE(previous_stat.st_mode)
        previous_writable = bool(previous_stat.st_mode & stat.S_IWRITE)

        for patched_name, error_message in (
            ("os.fsync", "stage failed"),
            ("os.replace", "publish failed"),
        ):
            with self.subTest(patched_name=patched_name):
                with patch(
                    f"src.conversion.asset_registry.{patched_name}",
                    side_effect=OSError(error_message),
                ):
                    with self.assertRaisesRegex(OSError, error_message):
                        AssetRegistryConverter._atomic_write_text(
                            registry_path,
                            "replacement registry\n",
                        )

                with open(registry_path, "r", encoding="utf-8") as registry_file:
                    self.assertEqual(registry_file.read(), "previous registry\n")
                current_stat = os.stat(registry_path)
                self.assertEqual(
                    (current_stat.st_dev, current_stat.st_ino),
                    previous_identity,
                )
                self.assertEqual(
                    bool(current_stat.st_mode & stat.S_IWRITE),
                    previous_writable,
                )
                if os.name != "nt":
                    self.assertEqual(
                        stat.S_IMODE(current_stat.st_mode),
                        previous_mode,
                    )
                staged_prefix = f".{os.path.basename(registry_path)}."
                self.assertFalse(
                    any(
                        name.startswith(staged_prefix)
                        for name in os.listdir(registry_directory)
                    )
                )

    def test_atomic_registry_publish_uses_umask_safe_and_stable_modes(self) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )

        AssetRegistryConverter._atomic_write_text(registry_path, "first\n")

        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(os.stat(registry_path).st_mode),
                0o600,
            )
        os.chmod(registry_path, 0o600)
        previous_stat = os.stat(registry_path)
        previous_identity = previous_stat.st_dev, previous_stat.st_ino
        previous_mode = stat.S_IMODE(previous_stat.st_mode)
        previous_writable = bool(previous_stat.st_mode & stat.S_IWRITE)

        AssetRegistryConverter._atomic_write_text(registry_path, "second\n")

        current_stat = os.stat(registry_path)
        self.assertNotEqual(
            (current_stat.st_dev, current_stat.st_ino),
            previous_identity,
        )
        self.assertEqual(
            bool(current_stat.st_mode & stat.S_IWRITE),
            previous_writable,
        )
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(current_stat.st_mode),
                previous_mode,
            )
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertEqual(registry_file.read(), "second\n")

    def test_atomic_registry_writer_does_not_require_os_fchmod(self) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )

        with patch.object(
            os,
            "fchmod",
            side_effect=AssertionError("os.fchmod must not be called"),
            create=True,
        ):
            AssetRegistryConverter._atomic_write_text(registry_path, "first\n")
            os.chmod(registry_path, 0o640)
            AssetRegistryConverter._atomic_write_text(registry_path, "second\n")

        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertEqual(registry_file.read(), "second\n")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(os.stat(registry_path).st_mode),
                0o640,
            )

    def test_atomic_registry_replaces_hardlink_without_mutating_referent(
        self,
    ) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        external_path = os.path.join(self.gm_dir, "external_registry.gd")
        _write_file(external_path, "external sentinel\n")
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        try:
            os.link(external_path, registry_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable: {error}")

        AssetRegistryConverter._atomic_write_text(registry_path, "replacement\n")

        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "external sentinel\n")
        with open(registry_path, "r", encoding="utf-8") as registry_file:
            self.assertEqual(registry_file.read(), "replacement\n")
        self.assertNotEqual(
            os.stat(external_path).st_ino,
            os.stat(registry_path).st_ino,
        )

    def test_atomic_registry_refuses_symlinked_output_directory(self) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        external_directory = os.path.join(self.gm_dir, "external_registry")
        os.makedirs(external_directory)
        try:
            os.symlink(
                external_directory,
                os.path.dirname(registry_path),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(
            OSError,
            "redirected asset-registry output directory",
        ):
            AssetRegistryConverter._atomic_write_text(
                registry_path,
                "replacement\n",
            )

        self.assertEqual(os.listdir(external_directory), [])

    def test_atomic_registry_refuses_mocked_windows_junction_output_directory(
        self,
    ) -> None:
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)
        os.makedirs(registry_directory)
        normalized_registry_directory = os.path.normcase(
            os.path.abspath(registry_directory)
        )

        def is_mock_junction(path: str) -> bool:
            return (
                os.path.normcase(os.path.abspath(path))
                == normalized_registry_directory
            )

        with patch.object(
            os.path,
            "isjunction",
            side_effect=is_mock_junction,
            create=True,
        ):
            with self.assertRaisesRegex(
                OSError,
                "redirected asset-registry output directory",
            ):
                AssetRegistryConverter._atomic_write_text(
                    registry_path,
                    "replacement\n",
                )

        self.assertEqual(os.listdir(registry_directory), [])

    def test_cancellation_during_entry_build_does_not_publish_partial_registry(
        self,
    ) -> None:
        _write_yyp(
            self.gm_dir,
            [("sprites", "s_player"), ("objects", "o_player")],
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites.yy",
        )
        self._write_resource(
            "objects",
            "o_player",
            "GMObject",
            "folders/Objects.yy",
        )
        running_checks = 0

        def conversion_running() -> bool:
            nonlocal running_checks
            running_checks += 1
            return running_checks == 1

        converter = AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda _value: None,
            conversion_running=conversion_running,
        )
        registry_path = os.path.join(
            self.godot_dir,
            ASSET_REGISTRY_RELATIVE_PATH,
        )

        self.assertEqual(converter.convert_all(), registry_path)

        self.assertFalse(os.path.exists(registry_path))
        with self.assertRaises(ValueError):
            converter.conversion_step_result(finalize_unfinished_as=None)
        result = converter.conversion_step_result()
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=2,
                executed=1,
                skipped=2,
            ),
        )

    def test_empty_registry_reports_zero_logical_resources(self) -> None:
        converter = self._converter()

        registry_path = converter.convert_all()

        self.assertEqual(
            registry_path,
            os.path.join(self.godot_dir, ASSET_REGISTRY_RELATIVE_PATH),
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(),
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
