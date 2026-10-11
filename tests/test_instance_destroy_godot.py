"""How converted games destroy instances and run Destroy and Clean Up events.

Each test converts a small GameMaker project with the full converter and runs
it headless. The GML trace() script prints each line as it runs, so a trace
survives game_end() and closing the window.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CLEAN_UP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_ROOM_END,
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

_TRACE_PREFIX = "TRACE "
_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    show_debug_message("TRACE " + _text);\n'
    "}\n"
)

# Clean Up runs once, as an instance leaves the game: inside instance_destroy,
# right after the Destroy event and while the instance still exists; for the
# instances of a room that ends, after their Room End events; for every
# instance when the game ends. A persistent instance that moves on to the next
# room does not run it (GameMaker HTML5 runner: Command_Destroy in
# yyInstance.js, StartRoom in _GameMaker.js, yyRoom.ClearInstances).
_CLEAN_UP_PROJECT = GameMakerProject(
    name="CleanUpEvents",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_keep",
            {
                EVENT_CREATE: 'trace("create_keep");\n',
                EVENT_CLEAN_UP: 'trace("clean_up_keep:" + room_get_name(room));\n',
            },
            persistent=True,
        ),
        GameMakerObject(
            "o_plain",
            {
                EVENT_DESTROY: 'trace("destroy_plain");\n',
                EVENT_CLEAN_UP: 'trace("clean_up_plain:exists=" + (instance_exists(id) ? "yes" : "no"));\n',
            },
        ),
        GameMakerObject(
            "o_stay",
            {
                EVENT_ROOM_END: 'trace("room_end_stay");\n',
                EVENT_CLEAN_UP: 'trace("clean_up_stay:" + room_get_name(room));\n',
            },
        ),
        GameMakerObject("o_child_stay", {}, parent="o_stay"),
        GameMakerObject(
            "o_hop",
            {
                EVENT_STEP: (
                    "with (o_plain) {\n"
                    "    instance_destroy();\n"
                    '    trace("after_destroy");\n'
                    "}\n"
                    "room_goto(r_two);\n"
                ),
            },
        ),
        GameMakerObject(
            "o_end",
            {
                EVENT_CREATE: "steps = 0;\n",
                EVENT_STEP: "steps += 1;\nif (steps == 2) game_end();\n",
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_keep", "o_keep", 0, 0),
                        RoomInstance("inst_plain", "o_plain", 10, 0),
                        RoomInstance("inst_stay", "o_stay", 20, 0),
                        RoomInstance("inst_child_stay", "o_child_stay", 30, 0),
                        RoomInstance("inst_hop", "o_hop", 40, 0),
                    ),
                ),
            ),
            creation_order=("inst_keep", "inst_plain", "inst_stay", "inst_child_stay", "inst_hop"),
        ),
        GameMakerRoom(
            "r_two",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_end", "o_end", 0, 0),)),),
            creation_order=("inst_end",),
        ),
    ),
)
_CLEAN_UP_TRACE = [
    "create_keep",
    "destroy_plain",
    "clean_up_plain:exists=yes",
    "after_destroy",
    "room_end_stay",
    "room_end_stay",
    "clean_up_stay:r_one",
    "clean_up_stay:r_one",
    "clean_up_keep:r_two",
]

# game_restart() ends the game, so every instance runs its Clean Up event
# (once) before the game starts again; closing the window ends it too.
_GAME_EXIT_PROJECT = GameMakerProject(
    name="CleanUpGameExit",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_res",
            {
                EVENT_CREATE: 'trace("create_res");\n',
                EVENT_CLEAN_UP: 'trace("clean_up_res:" + global.phase);\n',
            },
        ),
        GameMakerObject(
            "o_ctl",
            {
                EVENT_STEP: (
                    'if (!variable_global_exists("phase")) {\n'
                    '    global.phase = "restart";\n'
                    "    game_restart();\n"
                    "} else {\n"
                    '    global.phase = "close";\n'
                    "}\n"
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (RoomInstance("inst_res", "o_res", 0, 0), RoomInstance("inst_ctl", "o_ctl", 10, 0)),
                ),
            ),
            creation_order=("inst_res", "inst_ctl"),
        ),
    ),
)
_GAME_EXIT_TRACE = ["create_res", "clean_up_res:restart", "create_res", "clean_up_res:close"]

# instance_destroy only marks an instance: it stops existing for instance
# lookups at once (instance_exists, instance_number, with, also through self,
# other or a stored self), but its id stays a number (never noone, true, and
# different from every other id), and its variables can still be read and
# written until it is removed at the end of the step (HTML5 runner:
# Command_Destroy marks it, GetWithArray and instance_exists skip marked
# instances, yyInst finds it by id until RemoveMarked; manual,
# instance_destroy: "it will continue to perform the code contained in the
# current event").
_DESTROYED_REFERENCE_PROJECT = GameMakerProject(
    name="DestroyedReferences",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject("o_target", {EVENT_CREATE: "hp = 1;\n"}),
        GameMakerObject(
            "o_runner",
            {
                EVENT_STEP: (
                    'if (variable_global_exists("kept")) {\n'
                    '    trace("later:noone=" + (global.kept == noone ? "yes" : "no")\n'
                    '        + ":exists=" + (instance_exists(global.kept) ? "yes" : "no"));\n'
                    "    exit;\n"
                    "}\n"
                    "var b = instance_create_depth(5, 6, 0, o_target);\n"
                    "var c = instance_create_depth(7, 8, 0, o_target);\n"
                    "b.hp = 42;\n"
                    "instance_destroy(b);\n"
                    "instance_destroy(c);\n"
                    'trace("id:noone=" + (b == noone ? "yes" : "no") + ":same=" + (b == c ? "yes" : "no")\n'
                    '    + ":true=" + (b ? "yes" : "no"));\n'
                    'trace("lookup:exists=" + (instance_exists(b) ? "yes" : "no")\n'
                    '    + ":number=" + string(instance_number(o_target)));\n'
                    'trace("vars:hp=" + string(b.hp) + ":x=" + string(b.x));\n'
                    "b.hp = 50;\n"
                    'trace("vars:set_hp=" + string(b.hp));\n'
                    "var n = 0;\n"
                    "with (b) n += 1;\n"
                    'trace("with:" + string(n));\n'
                    "global.kept = b;\n"
                    "var d = instance_create_depth(0, 0, 0, o_target);\n"
                    "with (d) {\n"
                    "    global.node = self;\n"
                    "    instance_destroy();\n"
                    '    trace("self:noone=" + (id == noone ? "yes" : "no")\n'
                    '        + ":exists=" + (instance_exists(self) ? "yes" : "no") + ":hp=" + string(hp));\n'
                    "}\n"
                    "n = 0;\n"
                    "with (global.node) n += 1;\n"
                    'trace("stored_self:exists=" + (instance_exists(global.node) ? "yes" : "no") + ":with=" + string(n));\n'
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_runner", "o_runner", 0, 0),)),),
            creation_order=("inst_runner",),
        ),
    ),
)
_DESTROYED_REFERENCE_TRACE = [
    "id:noone=no:same=no:true=yes",
    "lookup:exists=no:number=0",
    "vars:hp=42:x=5",
    "vars:set_hp=50",
    "with:0",
    "self:noone=no:exists=no:hp=1",
    "stored_self:exists=no:with=0",
    "later:noone=no:exists=no",
]

_PROBE = """extends Node

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 10:
		print("PROBE_CLOSE")
		get_tree().root.propagate_notification(NOTIFICATION_WM_CLOSE_REQUEST)
		get_tree().quit(0)
"""


class TestInstanceDestroyGodot(unittest.TestCase):
    def test_clean_up_runs_once_as_an_instance_leaves_the_game(self) -> None:
        self.assertEqual(self._run_trace(_CLEAN_UP_PROJECT), _CLEAN_UP_TRACE)

    def test_game_restart_and_closing_the_window_run_clean_up(self) -> None:
        self.assertEqual(self._run_trace(_GAME_EXIT_PROJECT), _GAME_EXIT_TRACE)

    def test_a_destroyed_instance_keeps_its_id_and_variables_but_stops_existing(self) -> None:
        trace = self._run_trace(_DESTROYED_REFERENCE_PROJECT)
        # The runner keeps stepping; every later step traces the same line.
        self.assertEqual(trace[: len(_DESTROYED_REFERENCE_TRACE)], _DESTROYED_REFERENCE_TRACE)

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
        self.assertNotIn("SCRIPT ERROR", output)
        return [line.removeprefix(_TRACE_PREFIX) for line in output.splitlines() if line.startswith(_TRACE_PREFIX)]


if __name__ == "__main__":
    unittest.main()
