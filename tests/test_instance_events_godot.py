"""Which events converted games run, and with which self and other.

Each test converts a small GameMaker project with the full converter and runs
it headless. The GML trace() script prints each line as it runs.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CLEAN_UP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_STEP,
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

_TRACE_PREFIX = "TRACE "
_SCRIPTS = {
    "scr_trace": 'function trace(_text) {\n    show_debug_message("TRACE " + _text);\n}\n',
    "scr_yes_no": 'function yes_no(_value) {\n    return _value ? "yes" : "no";\n}\n',
}
_BOX = GameMakerSprite("spr_box", 16, 16)

# The Destroy and Clean Up events run with other being the instance itself,
# also when a collision event (where other is the instance collided with)
# destroys it; the collision event goes on with its own other afterwards
# (HTML5 runner: Command_Destroy in yyInstance.js performs both events with
# self and other the instance; manual, other: outside collision events, with
# and method calls other is the same as self).
_DESTROY_OTHER_PROJECT = GameMakerProject(
    name="DestroyOther",
    scripts=_SCRIPTS,
    sprites=(_BOX,),
    objects=(
        GameMakerObject(
            "o_a",
            {
                EVENT_DESTROY: 'trace("destroy:other_is_self=" + yes_no(other.id == id) + ":other_x=" + string(other.x));\n',
                EVENT_CLEAN_UP: 'trace("clean_up:other_is_self=" + yes_no(other.id == id));\n',
            },
            sprite="spr_box",
            collisions={
                "o_b": (
                    "instance_destroy();\n"
                    'trace("collision:other_is_b=" + yes_no(other.object_index == o_b));\n'
                ),
            },
        ),
        GameMakerObject("o_b", {}, sprite="spr_box"),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (RoomInstance("inst_a", "o_a", 0, 0), RoomInstance("inst_b", "o_b", 4, 0)),
                ),
            ),
            creation_order=("inst_a", "inst_b"),
        ),
    ),
)
_DESTROY_OTHER_TRACE = [
    "destroy:other_is_self=yes:other_x=0",
    "clean_up:other_is_self=yes",
    "collision:other_is_b=yes",
]

# Once an event has requested a room change, no collision event runs any more
# in that step, a persistent instance's neither (HTML5 runner:
# yyObject.PerformEvent returns once New_Room is set, except for some events
# of persistent instances, which collisions are not).
_COLLISION_ROOM_CHANGE_PROJECT = GameMakerProject(
    name="CollisionRoomChange",
    scripts=_SCRIPTS,
    sprites=(_BOX,),
    objects=(
        GameMakerObject(
            "o_a",
            {},
            sprite="spr_box",
            collisions={"o_b": 'trace("collision_a:" + string(x));\nroom_goto(r_two);\n'},
        ),
        GameMakerObject("o_b", {}, sprite="spr_box", collisions={"o_a": 'trace("collision_b:" + string(x));\n'}),
        GameMakerObject(
            "o_keep",
            {},
            persistent=True,
            sprite="spr_box",
            collisions={"o_b": 'trace("collision_keep");\n'},
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
                        RoomInstance("inst_a", "o_a", 0, 0),
                        RoomInstance("inst_b", "o_b", 4, 0),
                        RoomInstance("inst_a2", "o_a", 100, 0),
                        RoomInstance("inst_b2", "o_b", 104, 0),
                        RoomInstance("inst_keep", "o_keep", 2, 0),
                    ),
                ),
            ),
            creation_order=("inst_a", "inst_b", "inst_a2", "inst_b2", "inst_keep"),
        ),
        GameMakerRoom("r_two", layers=(InstanceLayer("Instances", 0, ()),), creation_order=()),
    ),
)
_COLLISION_ROOM_CHANGE_TRACE = ["collision_a:0"]

# instance_create_layer/depth copy the variables of an optional struct onto
# the new instance before its Create event (only once, also when a child
# object's Create event calls event_inherited), binding the struct's methods
# to the instance; instance_destroy(id, false) skips the Destroy event but
# still runs Clean Up (HTML5 runner: instance_create_depth and
# instance_create_layer call ShallowCopyVars between the Pre-Create and Create
# events in Function_Layers.js; DoDestroy in Function_Instance.js; manual,
# instance_create_layer and instance_destroy).
_CREATE_DESTROY_ARGUMENTS_PROJECT = GameMakerProject(
    name="CreateDestroyArguments",
    scripts=_SCRIPTS,
    objects=(
        GameMakerObject(
            "o_t",
            {
                EVENT_CREATE: 'trace("create:hp=" + string(hp) + ":speed=" + string(speed));\nhp += 1;\n',
                EVENT_DESTROY: 'trace("destroy");\n',
                EVENT_CLEAN_UP: 'trace("clean_up");\n',
            },
        ),
        GameMakerObject("o_t_child", {EVENT_CREATE: "hp *= 10;\nevent_inherited();\n"}, parent="o_t"),
        GameMakerObject("o_plain", {EVENT_STEP: "x += 1;\n"}),
        GameMakerObject(
            "o_runner",
            {
                EVENT_STEP: (
                    'if (variable_global_exists("done")) exit;\n'
                    "global.done = true;\n"
                    # Held globally: a struct whose method is bound to it is a
                    # reference cycle that only the global scope breaks at exit.
                    "global.basis = {hp: 5, speed: 2, get_hp: function() { return hp; }};\n"
                    "var t = instance_create_depth(0, 0, 0, o_t, global.basis);\n"
                    'trace("after_create:hp=" + string(t.hp) + ":hspeed=" + string(t.hspeed));\n'
                    "t.hp = 9;\n"
                    'trace("method:" + string(t.get_hp()));\n'
                    'var c = instance_create_layer(0, 0, "Instances", o_t_child, {hp: 5});\n'
                    'trace("child:hp=" + string(c.hp));\n'
                    'var n = instance_create_layer(0, 0, "Instances", o_plain, {tag: "late"});\n'
                    'trace("no_create:" + n.tag);\n'
                    "instance_destroy(t, false);\n"
                    'trace("destroyed:exists=" + yes_no(instance_exists(t)));\n'
                    "instance_destroy(c, true);\n"
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
_CREATE_DESTROY_ARGUMENTS_TRACE = [
    "create:hp=5:speed=2",
    "after_create:hp=6:hspeed=2",
    "method:9",
    "create:hp=50:speed=0",
    "child:hp=51",
    "no_create:late",
    "clean_up",
    "destroyed:exists=no",
    "destroy",
    "clean_up",
]

_PROBE = """extends Node

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 10:
		get_tree().quit(0)
"""


class TestInstanceEventsGodot(unittest.TestCase):
    def test_destroy_and_clean_up_run_with_other_being_the_instance(self) -> None:
        self.assertEqual(self._run_trace(_DESTROY_OTHER_PROJECT), _DESTROY_OTHER_TRACE)

    def test_no_collision_event_runs_once_a_room_change_is_pending(self) -> None:
        self.assertEqual(self._run_trace(_COLLISION_ROOM_CHANGE_PROJECT), _COLLISION_ROOM_CHANGE_TRACE)

    def test_create_variables_and_destroy_without_the_destroy_event(self) -> None:
        self.assertEqual(self._run_trace(_CREATE_DESTROY_ARGUMENTS_PROJECT), _CREATE_DESTROY_ARGUMENTS_TRACE)

    def _run_trace(self, project: GameMakerProject) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            imported = import_converted_project(godot_binary, root / "godot")
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("SCRIPT ERROR", output)
        return [line.removeprefix(_TRACE_PREFIX) for line in output.splitlines() if line.startswith(_TRACE_PREFIX)]


if __name__ == "__main__":
    unittest.main()
