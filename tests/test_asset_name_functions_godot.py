"""object_get_name and sprite_exists read the converted game's assets.

As in the HTML5 runner: object_get_name (functions/Function_Object.js) gives
the name of the object with that index, or "" when there is none, and
sprite_exists (functions/Function_Sprite.js) says whether the value is a
sprite index, false for undefined.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_CTRL_CREATE = """\
global.results = [
    object_get_name(o_block),
    object_get_name(object_index),
    object_get_name(global.block.object_index),
    object_get_name(-1),
    object_get_name(noone),
    sprite_exists(s_block),
    sprite_exists(global.block.sprite_index),
    sprite_exists(sprite_index),
    sprite_exists(-1),
    sprite_exists(undefined),
];
"""

_PROJECT = GameMakerProject(
    name="AssetNames",
    sprites=(GameMakerSprite("s_block", 2, 2, frames=([[(255, 0, 0, 255)] * 2] * 2,)),),
    objects=(
        GameMakerObject("o_block", {EVENT_CREATE: "global.block = id;\n"}, sprite="s_block"),
        GameMakerObject("o_ctrl", {EVENT_CREATE: _CTRL_CREATE}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (RoomInstance("inst_block", "o_block", 0, 0), RoomInstance("inst_ctrl", "o_ctrl", 0, 0)),
                ),
            ),
            creation_order=("inst_block", "inst_ctrl"),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 3:
		print("ASSET_NAMES " + JSON.stringify(GMRuntime.gml_global_scope().get("results", [])))
		get_tree().quit(0)
"""


class TestAssetNameFunctionsGodot(unittest.TestCase):
    def test_object_get_name_and_sprite_exists(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            import_converted_project(godot_binary, root / "godot")
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        lines = [line for line in output.splitlines() if line.startswith("ASSET_NAMES ")]
        self.assertEqual(len(lines), 1, output)
        self.assertEqual(
            json.loads(lines[0].removeprefix("ASSET_NAMES ")),
            ["o_block", "o_ctrl", "o_block", "", "", True, True, False, False, False],
        )


if __name__ == "__main__":
    unittest.main()
