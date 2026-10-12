"""surface_resize, on the application surface and on other surfaces.

Resizing the application surface is recorded and carried out when the next
frame starts drawing, so surface_get_width/height still report the old size
in the same step (HTML5 runner: Function_Surface.js surface_resize sets
g_NewApplicationSize, yyRoom.js SetApplicationSurface applies it; manual:
surface_resize). The new size is the resolution the room is drawn at, and
the default GUI size follows it. Any other surface is recreated at the new
size at once.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_transpiler_parts.api import transpile_gml_code
from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_STEP,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_CREATE = """steps = 0;
global.log = [];
surface_resize(application_surface, 128, 96);
array_push(global.log, "same_step:" + string(surface_get_width(application_surface)) + "x" + string(surface_get_height(application_surface)));
global.s = surface_create(10, 10);
surface_resize(global.s, 20, 30);
array_push(global.log, "surface:" + string(surface_get_width(global.s)) + "x" + string(surface_get_height(global.s)));
"""

_STEP = """steps += 1;
if (steps == 3) {
    var app = string(surface_get_width(application_surface)) + "x" + string(surface_get_height(application_surface));
    var gui = string(display_get_gui_width()) + "x" + string(display_get_gui_height());
    array_push(global.log, "next_frame:" + app + ":gui=" + gui);
    global.done = true;
}
"""

_PROJECT = GameMakerProject(
    name="SurfaceResize",
    objects=(GameMakerObject("o_resizer", {EVENT_CREATE: _CREATE, EVENT_STEP: _STEP}),),
    rooms=(
        GameMakerRoom(
            "r_resize",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_resizer", "o_resizer", 0, 0),)),),
            creation_order=("inst_resizer",),
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
	var scope = GMRuntime.gml_global_scope()
	if _frames > 300:
		print("RESIZE_TIMEOUT " + JSON.stringify(scope.get("log", [])))
		get_tree().quit(1)
		return
	if not bool(scope.get("done", false)):
		return
	var scale = get_viewport().get_canvas_transform().get_scale()
	print("RESIZE_RESULTS " + JSON.stringify({
		"log": scope["log"],
		"viewport": [get_viewport().get_visible_rect().size.x, get_viewport().get_visible_rect().size.y],
		"room_scale": [scale.x, scale.y],
	}))
	get_tree().quit(0)
"""


class TestSurfaceResizeGodot(unittest.TestCase):
    def test_surface_resize_is_a_runtime_call(self) -> None:
        code = transpile_gml_code("surface_resize(application_surface, 640, 360);")
        self.assertIn("GMRuntime.gml_surface_resize(", code)
        self.assertNotIn("gml_call_named", code)

    def test_application_surface_resizes_when_the_next_frame_draws(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        lines = [line for line in output.splitlines() if line.startswith("RESIZE_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("RESIZE_RESULTS "))
        self.assertEqual(
            results["log"],
            ["same_step:64x48", "surface:20x30", "next_frame:128x96:gui=128x96"],
        )
        # The room is drawn at the new resolution: the whole 64x48 room fills
        # the 128x96 application surface.
        self.assertEqual(results["viewport"], [128, 96])
        self.assertEqual(results["room_scale"], [2, 2])


if __name__ == "__main__":
    unittest.main()
