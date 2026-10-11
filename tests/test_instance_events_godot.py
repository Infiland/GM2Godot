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
    EVENT_DESTROY,
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
