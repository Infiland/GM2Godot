from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
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

# Project macros and enums are available to every piece of GML in the project:
# GameMaker's compiler replaces a macro by its expression and an enum member by
# its value wherever they appear, including in the Room Editor's room creation
# code and instance creation code.
_CONFIG_SCRIPT = (
    "#macro SPAWN_X 128\n"
    "#macro DOUBLE_X (SPAWN_X * 2)\n"
    "#macro Android:SPAWN_Y 48\n"
    "#macro SPAWN_Y 96\n"
    "enum Mood { calm, angry = 5, afraid }\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 6:
		print("CREATION_CODE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""

_PROJECT = GameMakerProject(
    name="CreationCodeMacros",
    scripts={"scr_trace": _TRACE_SCRIPT, "scr_config": _CONFIG_SCRIPT},
    objects=(
        GameMakerObject(
            "o_thing",
            {
                EVENT_CREATE: "mood = Mood.calm;\ntrace(\"create:\" + string(mood));\n",
                EVENT_ROOM_START: (
                    'trace("start:x=" + string(x) + ",y=" + string(y) + ",mood=" + string(mood));\n'
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_macros",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance(
                            "inst_thing",
                            "o_thing",
                            0,
                            0,
                            creation_code=(
                                "x = SPAWN_X;\n"
                                "y = SPAWN_Y;\n"
                                "mood = Mood.angry;\n"
                                'trace("instance:" + string(DOUBLE_X) + ":" + string(Mood.afraid));\n'
                            ),
                        ),
                    ),
                ),
            ),
            creation_order=("inst_thing",),
            creation_code=(
                "global.room_sum = SPAWN_X + Mood.afraid;\n"
                'trace("room:" + string(DOUBLE_X) + ":" + string(global.room_sum) + ":" + string(Mood.angry));\n'
            ),
        ),
    ),
)

# Create, then instance creation code, then room creation code, then Room Start.
_TRACE = [
    "create:0",
    "instance:256:6",
    "room:256:134:5",
    "start:x=128,y=96,mood=5",
]


class TestRoomCreationCodeMacrosGodot(unittest.TestCase):
    def test_room_and_instance_creation_code_use_project_macros_and_enums(self) -> None:
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
        self.assertNotIn("ERROR:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("CREATION_CODE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("CREATION_CODE_TRACE ")), _TRACE)


if __name__ == "__main__":
    unittest.main()
