"""Layer offsets and scroll speeds of a converted room, as GameMaker runs them.

Every step, after updating instance images and before Begin Step, GameMaker
adds each layer's speed to its offset (HTML5 runner: _GameMaker.js
GameMaker_DoAStep calls LayerManager.UpdateLayers, Function_Layers.js
`layer.m_xoffset += layer.m_hspeed`). layer_hspeed/layer_vspeed set that
speed, which starts as the Room Editor's for a background layer, and
layer_get_x/layer_get_y return the offset. Backgrounds, tilemaps, sprites
and sequences are drawn at the offset; instances are not moved by it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_BEGIN_STEP,
    EVENT_CREATE,
    BackgroundLayer,
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

_WHITE = (255, 255, 255, 255)

_BEGIN_STEP = """steps += 1;
array_push(global.log, string(steps) + ":" + offsets());
if (steps == 3) {
    layer_hspeed("Clouds", 0);
    layer_vspeed("Clouds", 0);
    layer_hspeed("Still", 3);
    layer_hspeed("Instances", 4);
    global.marker = instance_create_layer(40, 50, "Still", o_marker);
}
if (steps == 6) {
    layer_hspeed("Still", 0);
    layer_hspeed("Instances", 0);
    array_push(global.log, "x:" + string(x) + "," + string(global.marker.x));
    global.done = true;
}
"""

_OFFSETS = """function offsets() {
    var clouds = string(layer_get_x("Clouds")) + "," + string(layer_get_y("Clouds"));
    var others = string(layer_get_x("Still")) + ":" + string(layer_get_x("Instances"));
    return clouds + ":" + string(layer_get_hspeed("Clouds")) + ":" + others;
}
"""

_PROJECT = GameMakerProject(
    name="LayerScrolling",
    scripts={"scr_offsets": _OFFSETS},
    sprites=(GameMakerSprite("s_cloud", 8, 8, frames=([[_WHITE] * 8 for _row in range(8)],)),),
    objects=(
        GameMakerObject(
            "o_probe",
            {
                EVENT_CREATE: 'steps = 0;\nglobal.log = ["create:" + offsets()];\nglobal.probe = id;\nglobal.done = false;\n',
                EVENT_BEGIN_STEP: _BEGIN_STEP,
            },
        ),
        GameMakerObject("o_marker", {EVENT_CREATE: "marked = true;\n"}),
    ),
    rooms=(
        GameMakerRoom(
            "r_scroll",
            layers=(
                InstanceLayer("Instances", 0, (RoomInstance("inst_probe", "o_probe", 100, 60),)),
                BackgroundLayer("Clouds", 100, sprite="s_cloud", x=5, y=3, htiled=True, hspeed=2, vspeed=-1),
                BackgroundLayer("Still", 200, sprite="s_cloud", htiled=True),
            ),
            creation_order=("inst_probe",),
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
		print("LAYER_TIMEOUT " + JSON.stringify(scope.get("log", [])))
		get_tree().quit(1)
		return
	if not bool(scope.get("done", false)):
		return
	var scene = get_tree().current_scene
	var probe = GMRuntime.gml_handle_resolve(scope["probe"])
	var marker = GMRuntime.gml_handle_resolve(scope["marker"])
	var result = {
		"log": scope["log"],
		"clouds": _point(scene.get_node("Clouds/s_cloud").global_position),
		"still": _point(scene.get_node("Still/s_cloud").global_position),
		"probe": _point(probe.global_position),
		"marker": _point(marker.global_position),
	}
	print("LAYER_RESULTS " + JSON.stringify(result))
	get_tree().quit(0)


func _point(value):
	return [value.x, value.y]
"""


class TestLayerScrollingGodot(unittest.TestCase):
    def test_layer_speeds_scroll_layer_offsets_each_step(self) -> None:
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
        lines = [line for line in output.splitlines() if line.startswith("LAYER_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("LAYER_RESULTS "))
        # Begin Step of step n sees the offsets after n layer updates; the
        # speeds set in step 3 apply from step 4.
        self.assertEqual(
            results["log"],
            [
                "create:5,3:2:0:0",
                "1:7,2:2:0:0",
                "2:9,1:2:0:0",
                "3:11,0:2:0:0",
                "4:11,0:0:3:4",
                "5:11,0:0:6:8",
                "6:11,0:0:9:12",
                "x:100,40",
            ],
        )
        # Backgrounds are drawn at their layer's offset ...
        self.assertEqual(results["clouds"], [11, 0])
        self.assertEqual(results["still"], [9, 0])
        # ... and instances stay where they are, whatever their layer's offset.
        self.assertEqual(results["probe"], [100, 60])
        self.assertEqual(results["marker"], [40, 50])


if __name__ == "__main__":
    unittest.main()
