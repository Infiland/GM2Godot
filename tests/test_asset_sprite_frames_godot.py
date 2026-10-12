"""Sprites placed on an asset layer start at their Room Editor frame.

The Room Editor stores a sprite element's initial frame as headPosition and
its animation speed as animationSpeed. GameMaker uses them as the element's
image index and image speed (HTML5 runner: Function_Layers.js, NewSprite
m_imageIndex / m_sequencePos = sImageIndex and m_imageSpeed = sImageSpeed);
the head wraps into the sprite's frames (yySequence.js
HandleSequenceWrapping for a looping sprite, yySprite.js Draw), and each
step it moves by the sprite's speed times the element's speed
(LayerManager.UpdateLayers).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    AssetLayer,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    SpriteAsset,
    add_probe_autoload,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary


def _frame(shade: int) -> list[list[tuple[int, int, int, int]]]:
    return [[(shade, 0, 0, 255)] * 4 for _row in range(4)]


_FRAMES = tuple(_frame(shade) for shade in (10, 20, 30, 40))

_PROJECT = GameMakerProject(
    name="AssetFrames",
    objects=(),
    # A script makes the converter write the GML runtime the room needs.
    scripts={"scr_unused": "function scr_unused() {}\n"},
    sprites=(
        GameMakerSprite("s_still", 4, 4, frames=_FRAMES),
        GameMakerSprite("s_moving", 4, 4, frames=_FRAMES, playback_speed=10.0),
    ),
    rooms=(
        GameMakerRoom(
            "r_assets",
            layers=(
                AssetLayer(
                    "Assets",
                    100,
                    (
                        SpriteAsset("still_0", "s_still", 0, 0, head_position=0),
                        SpriteAsset("still_1", "s_still", 8, 0, head_position=1),
                        SpriteAsset("still_3", "s_still", 16, 0, head_position=3),
                        SpriteAsset("still_4", "s_still", 24, 0, head_position=4),
                        SpriteAsset("still_minus_1", "s_still", 32, 0, head_position=-1),
                        SpriteAsset("still_2_5", "s_still", 40, 0, head_position=2.5),
                        SpriteAsset("held", "s_moving", 0, 8, head_position=2, animation_speed=0.0),
                        SpriteAsset("fast", "s_moving", 8, 8, head_position=1, animation_speed=2.0),
                    ),
                ),
            ),
            creation_order=(),
        ),
    ),
)

_PROBE = """extends Node

var _frames = 0
var _first = {}


func _process(_delta):
	_frames += 1
	var scene = get_tree().current_scene
	if scene == null or scene.find_child("Assets", true, false) == null:
		return
	var layer = scene.find_child("Assets", true, false)
	var state = {}
	for element in layer.get_children():
		var visual = element.get_node_or_null("AnimatedSprite2D")
		if visual is AnimatedSprite2D:
			state[str(element.get_meta("gamemaker_asset_name"))] = [visual.frame, visual.speed_scale, visual.is_playing()]
	if _first.is_empty():
		_first = state
		return
	if _frames < 30:
		return
	print("ASSET_FRAMES " + JSON.stringify({"first": _first, "later": state}))
	get_tree().quit(0)
"""


class TestAssetSpriteFramesGodot(unittest.TestCase):
    def test_asset_sprites_start_at_their_room_editor_frame(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            imported = import_converted_project(godot_binary, root / "godot")
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        lines = [line for line in output.splitlines() if line.startswith("ASSET_FRAMES ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("ASSET_FRAMES "))
        first = {name: (frame, scale) for name, (frame, scale, _playing) in results["first"].items()}
        self.assertEqual(
            first,
            {
                "still_0": (0, 1),
                "still_1": (1, 1),
                "still_3": (3, 1),
                # The head wraps into the sprite's four frames.
                "still_4": (0, 1),
                "still_minus_1": (3, 1),
                "still_2_5": (2, 1),
                "held": (2, 0),
                "fast": (1, 2),
            },
        )
        later = results["later"]
        # A sprite with no speed, or an element with none, keeps its frame.
        for name in ("still_0", "still_1", "still_3", "still_4", "still_minus_1", "still_2_5", "held"):
            self.assertEqual(later[name][0], results["first"][name][0], name)
        # An animated sprite plays from its first frame on.
        self.assertTrue(later["fast"][2], later)


if __name__ == "__main__":
    unittest.main()
