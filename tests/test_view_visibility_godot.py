"""With views enabled, a room is drawn only through its visible views.

GameMaker draws the room once per visible view: Draw Begin, Draw and Draw
End run for each of them, after the window is cleared to the window colour
(HTML5 runner: yyRoom.js DrawViews, which only falls back to one view of
the whole room when views are disabled). With views enabled and none
visible, nothing of the room is drawn and its Draw events do not run, while
Pre Draw, Post Draw and the Draw GUI events still do.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    BackgroundLayer,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    RoomView,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    run_converted_project_rendered,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_EVENT_DRAW = (8, 0)
_EVENT_DRAW_GUI = (8, 64)
_EVENT_PRE_DRAW = (8, 76)
_EVENT_POST_DRAW = (8, 77)


def _count(name: str) -> str:
    return f'global.{name} = (variable_global_exists("{name}") ? global.{name} : 0) + 1;\n'


_PROJECT = GameMakerProject(
    name="ViewVisibility",
    objects=(
        GameMakerObject(
            "o_drawer",
            {
                _EVENT_DRAW: _count("draws"),
                _EVENT_PRE_DRAW: _count("pre_draws"),
                _EVENT_POST_DRAW: _count("post_draws"),
                _EVENT_DRAW_GUI: _count("gui_draws") + "draw_set_colour(c_lime);\ndraw_rectangle(0, 0, 9, 9, false);\n",
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_views",
            layers=(
                InstanceLayer("Instances", 0, (RoomInstance("inst_drawer", "o_drawer", 20, 20),)),
                # A red background over the whole room.
                BackgroundLayer("Back", 100, colour=0xFF0000FF),
            ),
            creation_order=("inst_drawer",),
            width=100,
            height=80,
            views=(RoomView(0, 0, 100, 80, 0, 0, 100, 80),),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _stage = 0
var _wait = 0
var _results = {}


func _process(_delta):
	_frames += 1
	if _frames > 600:
		print("VIEWS_TIMEOUT stage " + str(_stage))
		get_tree().quit(1)
		return
	var scope = GMRuntime.gml_global_scope()
	if not scope.has("gui_draws"):
		return
	if _wait > 0:
		_wait -= 1
		return
	match _stage:
		0:
			# Blue window colour (GameMaker colours are BGR).
			GMRuntime.gml_window_set_colour(0xFF0000)
			_wait = 3
		1:
			_results["shown"] = _sample(scope)
			GMRuntime.gml_view_set_visible(0, false)
			_wait = 3
		2:
			_results["hidden_start"] = _sample(scope)
			_wait = 5
		3:
			_results["hidden_end"] = _sample(scope)
			GMRuntime.gml_view_set_visible(0, true)
			_wait = 3
		4:
			_results["shown_again"] = _sample(scope)
			print("VIEWS_RESULTS " + JSON.stringify(_results))
			get_tree().quit(0)
	_stage += 1


func _sample(scope):
	var sample = {
		"draws": scope.get("draws", 0),
		"pre_draws": scope.get("pre_draws", 0),
		"post_draws": scope.get("post_draws", 0),
		"gui_draws": scope.get("gui_draws", 0),
	}
	var image = get_viewport().get_texture().get_image()
	if image != null and not image.is_empty():
		var size = Vector2(image.get_size())
		sample["room"] = _name(image.get_pixelv(Vector2i(size * 0.5)))
		sample["gui"] = _name(image.get_pixelv(Vector2i(size * 0.02)))
	return sample


func _name(colour):
	if colour.r > 0.5 and colour.g < 0.5 and colour.b < 0.5:
		return "red"
	if colour.b > 0.5 and colour.r < 0.5 and colour.g < 0.5:
		return "blue"
	if colour.g > 0.5 and colour.r < 0.5 and colour.b < 0.5:
		return "lime"
	return "other"
"""


class TestViewVisibilityGodot(unittest.TestCase):
    def test_room_with_no_visible_view_draws_nothing_but_gui(self) -> None:
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
        lines = [line for line in output.splitlines() if line.startswith("VIEWS_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("VIEWS_RESULTS "))
        shown, start, end, again = (
            results["shown"], results["hidden_start"], results["hidden_end"], results["shown_again"]
        )
        # Without a visible view the Draw event stops; the other draw events go on.
        self.assertEqual(end["draws"], start["draws"], results)
        for event in ("pre_draws", "post_draws", "gui_draws"):
            self.assertGreater(end[event], start[event], (event, results))
        self.assertGreater(again["draws"], end["draws"], results)
        if "room" in shown:
            self.assertEqual((shown["room"], shown["gui"]), ("red", "lime"), results)
            self.assertEqual((end["room"], end["gui"]), ("blue", "lime"), results)
            self.assertEqual((again["room"], again["gui"]), ("red", "lime"), results)


if __name__ == "__main__":
    unittest.main()
