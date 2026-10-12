"""Events an object inherits through parents that have no events of their own.

An object without an event runs the event of its nearest ancestor that has it,
and event_inherited() runs the nearest ancestor's event above the object, also
past any number of parents without that event (HTML5 runner yyInstance.js:
PerformEvent walks pParent while the object has no such event, and
PerformEventInherited starts at the parent). The chain is o_a -> o_b -> o_e ->
o_c and o_a -> o_b -> o_e -> o_d: o_a has the events, o_b and o_e have none at
all, o_c adds nothing and o_d overrides each event and calls event_inherited().
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_BEGIN_STEP,
    EVENT_CLEAN_UP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_GAME_START,
    EVENT_ROOM_START,
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
from tests.test_variable_definitions_godot import EXPRESSION, INTEGER, write_variable_definitions

EVENT_ALARM_0 = (2, 0)
EVENT_OUTSIDE_ROOM = (7, 0)
EVENT_USER_0 = (7, 10)
EVENT_USER_3 = (7, 13)
EVENT_END_STEP = (3, 2)
EVENT_KEYBOARD_A = (5, 65)
EVENT_KEY_PRESS_A = (9, 65)
EVENT_KEY_RELEASE_A = (10, 65)
EVENT_DRAW = (8, 0)
EVENT_DRAW_GUI = (8, 64)
EVENT_DRAW_BEGIN = (8, 72)
EVENT_DRAW_END = (8, 73)
EVENT_DRAW_GUI_BEGIN = (8, 74)
EVENT_DRAW_GUI_END = (8, 75)
EVENT_PRE_DRAW = (8, 76)
EVENT_POST_DRAW = (8, 77)

_SCRIPTS = {
    "scr_trace": (
        "function trace(_text) {\n"
        '    if (!variable_global_exists("trace")) global.trace = [];\n'
        "    array_push(global.trace, _text);\n"
        "}\n"
        # Events that repeat every step or frame are traced once per text.
        "function trace_once(_text) {\n"
        '    if (!variable_global_exists("seen")) global.seen = {};\n'
        "    if (variable_struct_exists(global.seen, _text)) return;\n"
        "    variable_struct_set(global.seen, _text, true);\n"
        "    trace(_text);\n"
        "}\n"
        "function who() {\n"
        '    if (object_index == o_c) return "c";\n'
        '    if (object_index == o_d) return "d";\n'
        '    return "?";\n'
        "}\n"
    ),
}

# Event name -> (event key, whether it repeats). The events of o_a trace
# "<name>:a:<who>", those of o_d "<name>:d:<who>" before event_inherited().
_EVENTS: Mapping[str, tuple[tuple[int, int], bool]] = {
    "create": (EVENT_CREATE, False),
    "destroy": (EVENT_DESTROY, False),
    "clean_up": (EVENT_CLEAN_UP, False),
    "begin_step": (EVENT_BEGIN_STEP, True),
    "step": (EVENT_STEP, True),
    "end_step": (EVENT_END_STEP, True),
    "alarm0": (EVENT_ALARM_0, False),
    "draw": (EVENT_DRAW, True),
    "draw_begin": (EVENT_DRAW_BEGIN, True),
    "draw_end": (EVENT_DRAW_END, True),
    "pre_draw": (EVENT_PRE_DRAW, True),
    "post_draw": (EVENT_POST_DRAW, True),
    "draw_gui": (EVENT_DRAW_GUI, True),
    "draw_gui_begin": (EVENT_DRAW_GUI_BEGIN, True),
    "draw_gui_end": (EVENT_DRAW_GUI_END, True),
    "user0": (EVENT_USER_0, False),
    "user3": (EVENT_USER_3, False),
    "game_start": (EVENT_GAME_START, False),
    "room_start": (EVENT_ROOM_START, False),
    "outside_room": (EVENT_OUTSIDE_ROOM, True),
    "key_held": (EVENT_KEYBOARD_A, True),
    "key_pressed": (EVENT_KEY_PRESS_A, False),
    "key_released": (EVENT_KEY_RELEASE_A, False),
}
_COLLISION_EVENT = "collision_wall"


def _call(name: str, level: str, repeats: bool) -> str:
    function = "trace_once" if repeats else "trace"
    return f'{function}("{name}:{level}:" + who());\n'


def _events(level: str, inherit: bool) -> dict[tuple[int, int], str]:
    suffix = "event_inherited();\n" if inherit else ""
    return {key: _call(name, level, repeats) + suffix for name, (key, repeats) in _EVENTS.items()}


# Drives the instances: user events and alarms at step 3, the key down at step
# 4 and up at step 6, a move out of the room at step 8, and the destruction of
# the instances at step 10.
_CONTROLLER_STEP = (
    "frame += 1;\n"
    "if (frame == 3) {\n"
    "    with (o_b) {\n"
    "        alarm[0] = 2;\n"
    "        event_user(0);\n"
    "        event_perform(ev_other, ev_user3);\n"
    "    }\n"
    "}\n"
    "if (frame == 4) keyboard_key_press(ord(\"A\"));\n"
    "if (frame == 6) keyboard_key_release(ord(\"A\"));\n"
    "if (frame == 8) {\n"
    "    with (o_b) x = -1000;\n"
    "}\n"
    "if (frame == 10) {\n"
    "    with (o_b) instance_destroy();\n"
    "}\n"
)

_BOX = GameMakerSprite("spr_box", 16, 16)

_EVENTS_PROJECT = GameMakerProject(
    name="EventInheritance",
    scripts=_SCRIPTS,
    sprites=(_BOX,),
    objects=(
        GameMakerObject("o_wall", {}, sprite="spr_box"),
        GameMakerObject(
            "o_a",
            _events("a", False),
            sprite="spr_box",
            collisions={"o_wall": _call(_COLLISION_EVENT, "a", True)},
        ),
        GameMakerObject("o_b", {}, parent="o_a", sprite="spr_box"),
        GameMakerObject("o_e", {}, parent="o_b", sprite="spr_box"),
        GameMakerObject("o_c", {}, parent="o_e", sprite="spr_box"),
        GameMakerObject(
            "o_d",
            _events("d", True),
            parent="o_e",
            sprite="spr_box",
            collisions={"o_wall": _call(_COLLISION_EVENT, "d", True) + "event_inherited();\n"},
        ),
        GameMakerObject(
            "o_ctrl",
            {EVENT_CREATE: "frame = 0;\n", EVENT_STEP: _CONTROLLER_STEP},
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_c", "o_c", 100, 100),
                        RoomInstance("inst_d", "o_d", 200, 100),
                        RoomInstance("inst_wall_c", "o_wall", 100, 100),
                        RoomInstance("inst_wall_d", "o_wall", 200, 100),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_c", "inst_d", "inst_wall_c", "inst_wall_d", "inst_ctrl"),
        ),
    ),
)

# Every event, as (name, level) per instance, in the order the instance runs
# them: o_d's own handler first, then the ancestor's through event_inherited().
_NAMES = [*_EVENTS, _COLLISION_EVENT]
_EXPECTED_C = {name: [f"{name}:a:c"] for name in _NAMES}
_EXPECTED_D = {name: [f"{name}:d:d", f"{name}:a:d"] for name in _NAMES}

# Variable Definitions without any event, in the middle and at the leaf: the
# definitions of every ancestor reach the instance before the nearest Create
# event above it runs.
_DEFINITIONS_PROJECT = GameMakerProject(
    name="EventInheritanceDefinitions",
    scripts=_SCRIPTS,
    objects=(
        GameMakerObject("o_a", {EVENT_CREATE: 'trace("create:a:" + who() + ":" + string(base_value) + ":" + string(mid_value));\n'}),
        # Variable Definitions only.
        GameMakerObject("o_b", {}, parent="o_a"),
        # Neither events nor Variable Definitions.
        GameMakerObject("o_e", {}, parent="o_b"),
        # Variable Definitions only, below two middle objects.
        GameMakerObject("o_c", {}, parent="o_e"),
        GameMakerObject(
            "o_d",
            {EVENT_CREATE: 'trace("create:d:" + who() + ":" + string(leaf_value));\nevent_inherited();\n'},
            parent="o_e",
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (RoomInstance("inst_c", "o_c", 100, 100), RoomInstance("inst_d", "o_d", 200, 100)),
                ),
            ),
            creation_order=("inst_c", "inst_d"),
        ),
    ),
)
_DEFINITIONS_PROPERTIES: dict[str, Sequence[tuple[object, ...]]] = {
    "o_a": (("base_value", INTEGER, "1"),),
    "o_b": (("mid_value", EXPRESSION, "base_value + 10"),),
    "o_c": (("leaf_value", INTEGER, "100"),),
    "o_d": (("leaf_value", INTEGER, "200"),),
}
_EXPECTED_DEFINITIONS = ["create:a:c:1:11", "create:d:d:200", "create:a:d:1:11"]

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 24:
		print("EVENT_INHERITANCE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestEventInheritanceGodot(unittest.TestCase):
    maxDiff = None

    def test_every_event_reaches_the_nearest_ancestor_through_parents_without_events(self) -> None:
        trace = self._run_trace(_EVENTS_PROJECT)
        for who, expected in (("c", _EXPECTED_C), ("d", _EXPECTED_D)):
            suffix = f":{who}"
            # An instance of o_c or o_d runs each event once (the repeating
            # ones are traced once), in the order its handlers call each other.
            actual = {name: [line for line in trace if line.startswith(f"{name}:") and line.endswith(suffix)] for name in _NAMES}
            self.assertEqual(actual, expected)

    def test_variable_definitions_without_events_run_before_the_inherited_create(self) -> None:
        trace = self._run_trace(_DEFINITIONS_PROJECT, properties=_DEFINITIONS_PROPERTIES)
        self.assertEqual(sorted(trace), sorted(_EXPECTED_DEFINITIONS))
        self.assertLess(trace.index("create:d:d:200"), trace.index("create:a:d:1:11"))

    def _run_trace(
        self,
        project: GameMakerProject,
        properties: dict[str, Sequence[tuple[object, ...]]] | None = None,
    ) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            if properties is not None:
                write_variable_definitions(root / "gamemaker", project, properties, {}, {})
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            if project.sprites:
                imported = import_converted_project(godot_binary, root / "godot")
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("EVENT_INHERITANCE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("EVENT_INHERITANCE_TRACE "))


if __name__ == "__main__":
    unittest.main()
