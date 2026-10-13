"""A persistent room keeps its view cameras and view settings across visits.

When GameMaker leaves a persistent room it marks the cameras of the room's
views persistent instead of destroying them, and coming back reuses the
same room with the same views and cameras (HTML5 runner: _GameMaker.js
StartRoom, pCam.SetPersistent(true), CopyViewsToArrays). A room that is not
persistent gets fresh cameras on each visit and frees them when it ends, and
game_restart starts persistent rooms afresh too (StartRoom with _starting).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_ROOM_START,
    EVENT_STEP,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    RoomView,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_ROOM_START = """hop_step = steps + 2;
if (room == r_keep) {
    if (!variable_global_exists("keep_camera")) {
        global.keep_camera = view_camera[0];
        camera_set_view_pos(view_camera[0], 40, 30);
        view_visible[1] = true;
    } else {
        array_push(global.log, (view_camera[0] == global.keep_camera ? "same" : "new")
            + ":" + string(camera_get_view_x(view_camera[0]))
            + ":" + (view_visible[1] ? "visible" : "hidden"));
    }
}
"""

_STEP = """steps += 1;
if (steps == hop_step && global.hops < 4) {
    global.hops += 1;
    if (room == r_keep) room_goto(r_other); else room_goto(r_keep);
} else if (steps == hop_step && global.hops == 4) {
    global.hops += 1;
    game_restart();
}
"""


def _room(name: str, persistent: bool) -> GameMakerRoom:
    return GameMakerRoom(
        name,
        layers=(InstanceLayer("Instances", 0, (RoomInstance(f"inst_{name}", "o_hopper", 10, 10),)),),
        creation_order=(f"inst_{name}",),
        views=(
            RoomView(0, 0, 64, 48, 0, 0, 64, 48),
            RoomView(0, 0, 64, 48, 0, 0, 64, 48, visible=False),
        ),
        persistent=persistent,
    )


_PROJECT = GameMakerProject(
    name="PersistentViews",
    objects=(
        GameMakerObject(
            "o_hopper",
            {
                EVENT_CREATE: 'if (!variable_global_exists("hops")) {\n    global.hops = 0;\n    global.log = [];\n}\nsteps = 0;\n',
                EVENT_ROOM_START: _ROOM_START,
                EVENT_STEP: _STEP,
            },
        ),
    ),
    rooms=(_room("r_keep", True), _room("r_other", False)),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _cameras = {}
var _settled = 0


func _process(_delta):
	_frames += 1
	if _frames > 600:
		print("VIEWS_TIMEOUT")
		get_tree().quit(1)
		return
	var scene = get_tree().current_scene
	var scope = GMRuntime.gml_global_scope()
	if scene == null or scene.name != "r_keep" or not scope.has("hops"):
		return
	var hops = int(scope["hops"])
	if hops % 2 == 1 and hops != 5:
		return
	_cameras[str(hops)] = _live_cameras()
	if hops == 5:
		_settled += 1
		if _settled > 3:
			print("VIEWS_RESULTS " + JSON.stringify({"log": scope["log"], "cameras": _cameras}))
			get_tree().quit(0)


func _live_cameras():
	var count = 0
	for handle in GMRuntime._gml_handle_registry.values():
		if handle.kind == GMRuntime.GML_CAMERA_HANDLE_KIND and GMRuntime.gml_handle_is_valid(handle):
			count += 1
	return count
"""


class TestPersistentRoomViewsGodot(unittest.TestCase):
    def test_persistent_room_keeps_its_view_cameras(self) -> None:
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
        lines = [line for line in output.splitlines() if line.startswith("VIEWS_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("VIEWS_RESULTS "))
        # Each return finds the cameras and view settings of the first visit;
        # game_restart starts the room afresh.
        self.assertEqual(results["log"], ["same:40:visible", "same:40:visible", "new:0:hidden"])
        # No visit leaves cameras behind.
        cameras = results["cameras"]
        for hops in ("2", "4", "5"):
            self.assertEqual(cameras[hops], cameras["0"], cameras)


if __name__ == "__main__":
    unittest.main()
