from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_GAME_START,
    EVENT_ROOM_START,
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

EVENT_GAME_END = (7, 3)
EVENT_ROOM_END = (7, 5)

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
		var scope = GMRuntime.gml_global_scope()
		var trace = scope.get("trace", [])
		# Time sources the game kept in globals: whether each still exists.
		for key in ["later", "kept"]:
			if scope.has(key):
				trace.append(key + "_exists:" + str(GMRuntime.gml_handle_is_valid(scope[key])))
		print("ROOM_LIFECYCLE_TRACE " + JSON.stringify(trace))
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

# Destroyed instances receive no further events: one that destroys itself in
# its Create event gets no Game Start or Room Start, one destroyed by an
# earlier Room Start event gets no Room Start, and one destroyed in the step
# that changes the room gets no Room End.
_DESTROYED_PROJECT = GameMakerProject(
    name="DestroyedLifecycle",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_gone",
            {
                EVENT_CREATE: "instance_destroy();\n",
                EVENT_GAME_START: 'trace("game_start_gone");\n',
                EVENT_ROOM_START: 'trace("room_start_gone");\n',
            },
        ),
        GameMakerObject("o_killer", {EVENT_ROOM_START: 'trace("room_start_killer");\ninstance_destroy(o_victim);\n'}),
        GameMakerObject("o_victim", {EVENT_ROOM_START: 'trace("room_start_victim");\n'}),
        GameMakerObject(
            "o_leaver",
            {
                EVENT_STEP: (
                    'if (room == r_one) {\n    trace("leave");\n    instance_destroy(o_ender);\n    room_goto(r_two);\n}\n'
                ),
            },
        ),
        GameMakerObject("o_ender", {EVENT_ROOM_END: 'trace("room_end_ender");\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_gone", "o_gone", 0, 0),
                        RoomInstance("inst_killer", "o_killer", 0, 0),
                        RoomInstance("inst_victim", "o_victim", 0, 0),
                        RoomInstance("inst_leaver", "o_leaver", 0, 0),
                        RoomInstance("inst_ender", "o_ender", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_gone", "inst_killer", "inst_victim", "inst_leaver", "inst_ender"),
        ),
        GameMakerRoom("r_two", layers=(), creation_order=()),
    ),
)
_DESTROYED_TRACE = ["room_start_killer", "leave"]


# game_restart ends the game like the runner's Run_EndGame(true): every
# instance goes, persistent ones included (placed or created by code), and
# the time sources made by call_later are destroyed; those made by
# time_source_create stay. The first room then starts as at launch: the
# persistent controller runs its Create event and creation code again and
# Game Start runs again. Game End runs before the restart.
_RESTART_PROJECT = GameMakerProject(
    name="GameRestart",
    scripts={"scr_trace": _TRACE_SCRIPT, "scr_later": "function later_callback() {}\n"},
    objects=(
        GameMakerObject(
            "o_ctrl",
            {
                EVENT_CREATE: (
                    "counter = 0;\n"
                    'trace("create_ctrl:" + string(instance_number(o_ctrl)));\n'
                    'if (!variable_global_exists("runs")) {\n'
                    "    global.runs = 0;\n"
                    "    global.later = call_later(100000, 1, later_callback, true);\n"
                    "    global.kept = time_source_create(time_source_global, 100000, 1, later_callback, [], -1);\n"
                    "    time_source_start(global.kept);\n"
                    "}\n"
                    "global.runs += 1;\n"
                ),
                EVENT_GAME_START: 'trace("game_start_ctrl");\n',
                EVENT_ROOM_START: (
                    'trace("room_start_ctrl:counter=" + string(counter) + ":managers=" + string(instance_number(o_manager)));\n'
                ),
                EVENT_STEP: 'counter += 1;\nif (counter == 3 && global.runs == 1) {\n    trace("restart");\n    game_restart();\n}\n',
                EVENT_GAME_END: 'trace("game_end_ctrl");\n',
            },
            persistent=True,
        ),
        GameMakerObject("o_spawner", {EVENT_CREATE: "instance_create_depth(0, 0, 0, o_manager);\n"}),
        GameMakerObject("o_manager", {EVENT_CREATE: 'trace("create_manager:" + string(instance_number(o_manager)));\n'}, persistent=True),
    ),
    rooms=(
        GameMakerRoom(
            "r_first",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0, creation_code='trace("code_ctrl");\n'),
                        RoomInstance("inst_spawner", "o_spawner", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_ctrl", "inst_spawner"),
        ),
    ),
)
_RESTART_RUN = [
    "create_ctrl:1",
    "code_ctrl",
    "create_manager:1",
    "game_start_ctrl",
    "room_start_ctrl:counter=0:managers=1",
]
_RESTART_TRACE = [
    *_RESTART_RUN,
    "restart",
    "game_end_ctrl",
    *_RESTART_RUN,
    "later_exists:false",
    "kept_exists:true",
]


class TestRoomLifecycleGodot(unittest.TestCase):
    def test_room_change_in_create_skips_later_create_and_creation_code(self) -> None:
        self.assertEqual(self._run_trace(_REDIRECT_PROJECT), _REDIRECT_TRACE)

    def test_destroyed_instances_get_no_room_or_game_events(self) -> None:
        self.assertEqual(self._run_trace(_DESTROYED_PROJECT), _DESTROYED_TRACE)

    def test_game_restart_removes_persistent_instances_and_call_later_sources(self) -> None:
        self.assertEqual(self._run_trace(_RESTART_PROJECT), _RESTART_TRACE)

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
