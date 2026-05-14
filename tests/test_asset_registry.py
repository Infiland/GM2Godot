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
)


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

    def _converter(self, organize_sounds_by_audio_group: bool = False) -> AssetRegistryConverter:
        return AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(str(msg)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            organize_sounds_by_audio_group=organize_sounds_by_audio_group,
        )

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
            ],
        )
        self._write_resource(
            "sprites",
            "s_player",
            "GMSprite",
            "folders/Sprites/Actors.yy",
            {"tags": ["player", {"name": "visible"}]},
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
        _write_file(os.path.join(self.gm_dir, "datafiles", "config", "game.json"), "{}")

        entries = self._converter(organize_sounds_by_audio_group=True).build_entries()
        by_name = {entry.name: entry for entry in entries}

        self.assertEqual(by_name["s_player"].asset_type, "sprite")
        self.assertEqual(by_name["s_player"].godot_path, "res://sprites/Actors/s_player/s_player.tscn")
        self.assertEqual(by_name["s_player"].tags, ("player", "visible"))
        self.assertEqual(by_name["snd_jump"].asset_type, "sound")
        self.assertEqual(
            by_name["snd_jump"].godot_path,
            "res://sounds/audio_sfx/SFX/snd_jump/snd_jump.ogg",
        )
        sound_metadata = by_name["snd_jump"].metadata
        self.assertIsNotNone(sound_metadata)
        assert sound_metadata is not None
        self.assertEqual(sound_metadata["audio_group"], "audio_sfx")
        self.assertEqual(sound_metadata["sound_file"], "snd_jump.ogg")
        self.assertEqual(sound_metadata["volume"], 1.0)
        self.assertEqual(by_name["r_title"].godot_path, "res://rooms/Menus/r_title/r_title.tscn")
        self.assertEqual(by_name["o_player"].godot_path, "res://objects/Actors/o_player/o_player.tscn")
        self.assertEqual(by_name["scr_spawn"].godot_path, "res://scripts/Game/scr_spawn.gd")
        self.assertEqual(by_name["fnt_ui"].godot_path, "res://fonts/UI/fnt_ui.tres")
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

    def test_convert_all_writes_runtime_registry_script(self) -> None:
        _write_yyp(self.gm_dir, [("sprites", "s_player")])
        self._write_resource("sprites", "s_player", "GMSprite", "folders/Sprites.yy")

        registry_path = self._converter().convert_all()

        self.assertEqual(registry_path, os.path.join(self.godot_dir, ASSET_REGISTRY_RELATIVE_PATH))
        with open(registry_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("extends RefCounted", content)
        self.assertIn("const FORMAT_VERSION = 1", content)
        self.assertIn("static func gml_asset_registry_entries():", content)
        self.assertIn('"name": "s_player"', content)
        self.assertIn('"type": "sprite"', content)


if __name__ == "__main__":
    unittest.main()
