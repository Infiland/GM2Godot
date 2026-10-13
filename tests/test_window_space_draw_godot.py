"""Pre Draw and Post Draw draw in window pixels.

GameMaker runs Pre Draw and Post Draw straight on the back buffer, with the
viewport and view area set to the window size (HTML5 runner: yyRoom.js
PostDraw sets Graphics_SetViewPort/SetViewArea to window_get_width/height),
so their coordinates are window pixels, not application surface pixels,
whatever the application surface is scaled to.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    run_converted_project_rendered,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_EVENT_PRE_DRAW = (8, 76)
_EVENT_POST_DRAW = (8, 77)

_PROJECT = GameMakerProject(
    name="WindowSpaceDraw",
    objects=(
        GameMakerObject(
            "o_overlay",
            {
                _EVENT_PRE_DRAW: "draw_set_colour(c_lime);\ndraw_rectangle(0, 40, 6, 46, false);\n",
                # A 7x7 square in the window's top-left corner, and one in its
                # top-right corner placed with window_get_width().
                _EVENT_POST_DRAW: (
                    "draw_set_colour(c_red);\n"
                    "draw_rectangle(0, 0, 6, 6, false);\n"
                    "draw_rectangle(window_get_width() - 7, 0, window_get_width() - 1, 6, false);\n"
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_window",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_overlay", "o_overlay", 0, 0),)),),
            creation_order=("inst_overlay",),
            width=64,
            height=48,
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 2:
		# Ten window pixels per application surface pixel.
		get_window().size = Vector2i(640, 480)
	if _frames < 8:
		return
	var scene = get_tree().current_scene
	var result = {"window": [get_window().size.x, get_window().size.y]}
	for name in ["_GM2GodotPreDraw", "_GM2GodotPostDraw"]:
		var layer = scene.get_node_or_null(name)
		if layer is CanvasLayer:
			# Where window pixel (7, 7) lands in the application surface.
			var point = layer.transform * Vector2(7, 7)
			result[name] = [point.x, point.y]
	var image = get_viewport().get_texture().get_image()
	if image != null and not image.is_empty():
		result["pixels"] = {
			"top_left": _name(image.get_pixel(3, 3)),
			"top_right": _name(image.get_pixel(image.get_width() - 4, 3)),
			"corner": _name(image.get_pixel(0, 0)),
			"right_corner": _name(image.get_pixel(image.get_width() - 1, 0)),
		}
	print("WINDOW_RESULTS " + JSON.stringify(result))
	get_tree().quit(0)


func _name(colour):
	if colour.r > 0.5 and colour.g < 0.5 and colour.b < 0.5:
		return "red"
	return "other"
"""


class TestWindowSpaceDrawGodot(unittest.TestCase):
    def test_pre_and_post_draw_use_window_pixels(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project_rendered(godot_binary, root / "godot")
            if result is None:
                result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        lines = [line for line in output.splitlines() if line.startswith("WINDOW_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("WINDOW_RESULTS "))
        self.assertEqual(results["window"], [640, 480], results)
        for name in ("_GM2GodotPreDraw", "_GM2GodotPostDraw"):
            self.assertIn(name, results, results)
            self.assertAlmostEqual(results[name][0], 0.7, places=4, msg=results)
            self.assertAlmostEqual(results[name][1], 0.7, places=4, msg=results)
        if "pixels" in results:
            # The 7x7 window-pixel squares cover less than one application
            # surface pixel, in the corners only.
            pixels = results["pixels"]
            self.assertEqual(pixels["top_left"], "other", results)
            self.assertEqual(pixels["top_right"], "other", results)
            self.assertEqual(pixels["right_corner"], "red", results)


if __name__ == "__main__":
    unittest.main()
