# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Iterable, cast
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.asset_registry import (
    ASSET_REGISTRY_RELATIVE_PATH,
    AssetRegistryConverter,
    GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH,
    _ProjectResource,
)
from src.conversion.animation_curve_registry import ANIMATION_CURVE_REGISTRY_RELATIVE_PATH
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.extension_registry import (
    EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
    extension_stub_relative_script_path,
)
from src.conversion.fonts import FontConverter
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
                converter._write_timeline_action_scripts((entry,))

            outside_accesses = [
                call
                for call in tracked_open.call_args_list
                if call.args
                and isinstance(call.args[0], (str, os.PathLike))
                and os.path.realpath(os.fspath(call.args[0]))
                == os.path.realpath(outside_source)
            ]
            self.assertEqual(outside_accesses, [])
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
