"""room_set_width and room_set_height change the size a room starts with.

As the HTML5 runner does it: room_set_width/room_set_height
(functions/Function_Room.js) change the room's stored size, and a room takes
its stored size when it starts afresh (CreateRoomFromStorage in yyRoom.js,
also on room_restart). The running room keeps its size until then.
room_get_info reports the stored size, and the views of the room use its new
size, so a camera following an instance stops at the new right edge.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
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

_CTRL_A_CREATE = """\
if (!variable_global_exists("log")) {
    global.log = [];
    global.restarted = false;
    global.back = false;
}
if (!global.back) {
    room_set_width(r_b, 300);
    room_set_height(r_b, 200);
    room_set_width(r_a, 640);
    var _info = room_get_info(r_b);
    array_push(global.log, "a " + string(room_width) + " " + string(room_height)
        + " info " + string(_info.width) + " " + string(_info.height));
    room_goto(r_b);
} else {
    array_push(global.log, "a again " + string(room_width));
}
"""
_CTRL_B_CREATE = """\
steps = 0;
array_push(global.log, "b " + string(room_width) + " " + string(room_height));
if (!global.restarted) {
    room_set_width(r_b, 250);
    array_push(global.log, "b after set " + string(room_width));
}
camera_set_view_target(view_camera[0], global.mover);
"""
_CTRL_B_STEP = """\
steps += 1;
if (steps == 2) {
    array_push(global.log, "view " + string(camera_get_view_x(view_camera[0])));
    if (!global.restarted) {
        global.restarted = true;
        room_restart();
    } else {
        global.back = true;
        room_goto(r_a);
    }
}
"""

_PROJECT = GameMakerProject(
    name="RoomSize",
    objects=(
        GameMakerObject("o_ctrl_a", {EVENT_CREATE: _CTRL_A_CREATE}),
        GameMakerObject("o_mover", {EVENT_CREATE: "global.mover = id;\n"}),
        GameMakerObject("o_ctrl_b", {EVENT_CREATE: _CTRL_B_CREATE, EVENT_STEP: _CTRL_B_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_a",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_a", "o_ctrl_a", 0, 0),)),),
            creation_order=("inst_a",),
            width=64,
            height=48,
        ),
        GameMakerRoom(
            "r_b",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (RoomInstance("inst_mover", "o_mover", 290, 40), RoomInstance("inst_b", "o_ctrl_b", 0, 0)),
                ),
            ),
            creation_order=("inst_mover", "inst_b"),
            width=100,
            height=80,
            views=(RoomView(0, 0, 100, 80, 0, 0, 100, 80),),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 30:
		print("ROOM_SIZE_LOG " + JSON.stringify(GMRuntime.gml_global_scope().get("log", [])))
		get_tree().quit(0)
"""


class TestRoomSizeGodot(unittest.TestCase):
    def test_room_takes_the_stored_size_when_it_starts(self) -> None:
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
        lines = [line for line in output.splitlines() if line.startswith("ROOM_SIZE_LOG ")]
        self.assertEqual(len(lines), 1, output)
        self.assertEqual(
            json.loads(lines[0].removeprefix("ROOM_SIZE_LOG ")),
            [
                "a 64 48 info 300 200",
                "b 300 200",
                # The running room keeps its size.
                "b after set 300",
                # The camera following the instance at x = 290 stops at the right edge.
                "view 200",
                # room_restart starts the room afresh with the stored size.
                "b 250 200",
                "view 150",
                "a again 640",
            ],
        )


if __name__ == "__main__":
    unittest.main()
