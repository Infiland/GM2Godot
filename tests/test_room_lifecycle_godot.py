from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_GAME_START,
    EVENT_ROOM_START,
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

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 12:
		print("ROOM_LIFECYCLE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""

# A redirecting init room: the first instance's Create event requests a room
# change. The runner's StartRoom decides before each instance's Create event
# whether its Create event and creation code run, so the requesting instance
# still runs its own creation code while the later one runs neither. Game
# Start and Room Start are Other events and are skipped for non-persistent
# instances once the change is pending; the room creation code still runs.
_REDIRECT_PROJECT = GameMakerProject(
    name="RedirectInCreate",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_go",
            {
                EVENT_CREATE: 'trace("create_go");\nroom_goto(r_next);\n',
                EVENT_GAME_START: 'trace("game_start_go");\n',
                EVENT_ROOM_START: 'trace("room_start_go");\n',
            },
        ),
        GameMakerObject(
            "o_late",
            {
                EVENT_CREATE: 'trace("create_late");\nsetting = 1;\n',
                EVENT_ROOM_START: 'trace("room_start_late");\n',
            },
        ),
        GameMakerObject("o_next", {EVENT_CREATE: 'trace("create_next");\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_init",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_go", "o_go", 0, 0, creation_code='trace("code_go");\n'),
                        RoomInstance("inst_late", "o_late", 0, 0, creation_code='trace("code_late:" + string(setting));\n'),
                    ),
                ),
            ),
            creation_order=("inst_go", "inst_late"),
            creation_code='trace("room_code_init");\n',
        ),
        GameMakerRoom(
            "r_next",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_next", "o_next", 0, 0),)),),
            creation_order=("inst_next",),
        ),
    ),
)
_REDIRECT_TRACE = ["create_go", "code_go", "room_code_init", "create_next"]

class TestRoomLifecycleGodot(unittest.TestCase):
    def test_room_change_in_create_skips_later_create_and_creation_code(self) -> None:
        self.assertEqual(self._run_trace(_REDIRECT_PROJECT), _REDIRECT_TRACE)

    def _run_trace(self, project: GameMakerProject) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("ROOM_LIFECYCLE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("ROOM_LIFECYCLE_TRACE "))


if __name__ == "__main__":
    unittest.main()
