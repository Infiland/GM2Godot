from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_DESTROY,
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

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

# GameMaker starts a room by creating all of its instances, then runs each
# instance's Create event and creation code in the room's creation order (an
# instance created by a Create event runs its own Create event at once), then
# the room creation code and the Room Start events. The instances below are
# placed so that the room's layer order differs from its creation order.
_PROJECT = GameMakerProject(
    name="RoomStart",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_a",
            {
                EVENT_CREATE: (
                    'trace("create_a:" + string(x) + ":b=" + (instance_exists(o_b) ? "yes" : "no")\n'
                    '    + ":a_count=" + string(instance_number(o_a))\n'
                    '    + ":room=" + (room == r_start ? "r_start" : "other") + ":w=" + string(room_width)\n'
                    '    + ":other_is_self=" + (other.id == id ? "yes" : "no"));\n'
                    "if (x == 10) {\n"
                    "    var made = instance_create_depth(0, 0, 0, o_made);\n"
                    '    trace("made_flag:" + string(made.made_flag));\n'
                    "}\n"
                ),
                EVENT_ROOM_START: 'trace("room_start_a:" + string(x));\n',
            },
        ),
        GameMakerObject(
            "o_b",
            {
                EVENT_CREATE: (
                    'trace("create_b:" + string(x) + ":code_flag="\n'
                    '    + (variable_global_exists("code_flag") ? global.code_flag : "unset"));\n'
                ),
                EVENT_ROOM_START: 'trace("room_start_b:" + string(x));\n',
            },
        ),
        GameMakerObject("o_made", {EVENT_CREATE: 'made_flag = 7;\ntrace("create_made");\n'}),
        GameMakerObject(
            "o_killer",
            {
                EVENT_CREATE: 'with (o_victim) instance_destroy();\ntrace("kill:victims=" + string(instance_number(o_victim)));\n',
                EVENT_ROOM_START: 'trace("room_start_killer:victims=" + string(instance_number(o_victim)));\n',
            },
        ),
        GameMakerObject(
            "o_victim",
            {
                EVENT_CREATE: 'trace("create_victim:exists=" + (instance_exists(id) ? "yes" : "no"));\n',
                EVENT_DESTROY: 'trace("destroy_victim");\n',
                EVENT_STEP: 'trace("step_victim");\n',
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_start",
            layers=(
                InstanceLayer(
                    "Upper",
                    0,
                    (
                        RoomInstance("inst_b1", "o_b", 20, 0),
                        RoomInstance("inst_k1", "o_killer", 40, 0),
                    ),
                ),
                InstanceLayer(
                    "Lower",
                    100,
                    (
                        RoomInstance(
                            "inst_a1",
                            "o_a",
                            10,
                            0,
                            creation_code='trace("code_a:" + string(x) + ":other_is_self=" + (other.id == id ? "yes" : "no"));\nglobal.code_flag = "set";\n',
                        ),
                        RoomInstance("inst_a2", "o_a", 30, 0, creation_code='trace("code_a:" + string(x));\n'),
                        RoomInstance("inst_v1", "o_victim", 50, 0, creation_code='trace("code_victim");\n'),
                    ),
                ),
            ),
            creation_order=("inst_a1", "inst_b1", "inst_a2", "inst_k1", "inst_v1"),
            creation_code='trace("room_code");\n',
        ),
    ),
)

# A persistent instance placed in a room is created once. Coming back to that
# room keeps the instance from the first visit: the placed copy is not created
# again, so neither its Create event nor its creation code runs a second time.
_PERSISTENT_PROJECT = GameMakerProject(
    name="PersistentReturn",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_keeper",
            {
                EVENT_CREATE: 'trace("create_keeper");\n',
                EVENT_ROOM_START: (
                    'trace("room_start_keeper:" + room_get_name(room) + ":" + string(instance_number(o_keeper)));\n'
                ),
            },
            persistent=True,
        ),
        GameMakerObject(
            "o_plain",
            {
                EVENT_CREATE: (
                    'trace("create_plain:" + room_get_name(room) + ":keepers=" + string(instance_number(o_keeper)));\n'
                ),
            },
        ),
        GameMakerObject(
            "o_hopper",
            {
                # Leaves the room on its second step; the hop count lives in a
                # global so each visit only hops once.
                EVENT_CREATE: "steps = 0;\n",
                EVENT_STEP: (
                    "steps += 1;\n"
                    'if (!variable_global_exists("hops")) global.hops = 0;\n'
                    "if (steps == 2 && global.hops < 2) {\n"
                    "    global.hops += 1;\n"
                    "    if (room == r_one) room_goto(r_two); else room_goto(r_one);\n"
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
                    (
                        RoomInstance("inst_keeper", "o_keeper", 10, 0, creation_code='trace("code_keeper");\n'),
                        RoomInstance("inst_plain1", "o_plain", 20, 0),
                        RoomInstance("inst_hopper1", "o_hopper", 30, 0),
                    ),
                ),
            ),
            creation_order=("inst_keeper", "inst_plain1", "inst_hopper1"),
        ),
        GameMakerRoom(
            "r_two",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_plain2", "o_plain", 20, 0),
                        RoomInstance("inst_hopper2", "o_hopper", 30, 0),
                    ),
                ),
            ),
            creation_order=("inst_plain2", "inst_hopper2"),
        ),
    ),
)
_PERSISTENT_TRACE = [
    "create_keeper",
    "code_keeper",
    "create_plain:r_one:keepers=1",
    "room_start_keeper:r_one:1",
    "create_plain:r_two:keepers=1",
    "room_start_keeper:r_two:1",
    "create_plain:r_one:keepers=1",
    "room_start_keeper:r_one:1",
]


_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 12:
		print("ROOM_START_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""

_CREATION_TRACE = [
    "create_a:10:b=yes:a_count=2:room=r_start:w=320:other_is_self=yes",
    "create_made",
    "made_flag:7",
    "code_a:10:other_is_self=yes",
    "create_b:20:code_flag=set",
    "create_a:30:b=yes:a_count=2:room=r_start:w=320:other_is_self=yes",
    "code_a:30",
    "destroy_victim",
    "kill:victims=0",
    "create_victim:exists=no",
    "code_victim",
    "room_code",
]
_ROOM_START_TRACE = {
    "room_start_a:10",
    "room_start_b:20",
    "room_start_a:30",
    "room_start_killer:victims=0",
}


class TestRoomStartGodot(unittest.TestCase):
    def test_room_instances_exist_before_create_and_run_in_creation_order(self) -> None:
        trace = self._run_trace(_PROJECT)
        creation = trace[: len(_CREATION_TRACE)]
        self.assertEqual(creation, _CREATION_TRACE)
        self.assertEqual(set(trace[len(_CREATION_TRACE):]), _ROOM_START_TRACE)
        # An instance destroyed before its turn still runs its Create event
        # and creation code when its turn comes, then is gone: it gets no
        # Room Start or Step event.
        self.assertNotIn("step_victim", trace)

    def test_returning_to_a_room_keeps_its_persistent_instance(self) -> None:
        trace = self._run_trace(_PERSISTENT_PROJECT)
        self.assertEqual(trace, _PERSISTENT_TRACE)

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
        trace_lines = [line for line in output.splitlines() if line.startswith("ROOM_START_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("ROOM_START_TRACE "))


if __name__ == "__main__":
    unittest.main()
