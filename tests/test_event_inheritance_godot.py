"""Events an object inherits through parents that have no events of their own.

An object without an event runs the event of its nearest ancestor that has it,
and event_inherited() runs the nearest ancestor's event above the object, also
past any number of parents without that event (HTML5 runner yyInstance.js:
PerformEvent walks pParent while the object has no such event, and
PerformEventInherited starts at the parent). The chain is o_a -> o_b -> o_e ->
o_c, with o_d, o_f and o_g below o_e as well: o_a has the events, o_b and o_e
have none at all, o_c adds nothing, o_d overrides each event and calls
event_inherited(), o_f replaces only the Create event and o_g replaces a few
events without calling event_inherited().

Each handler records "<event>:<object that owns the handler>:<instance>" on
every run, so the test counts runs. An instance of a descendant must run the
ancestor's handler as often as an instance of o_a placed directly in the room
does (no run missing, none doubled), and one that replaces a handler must not
run the ancestor's.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
EVENT_CLOSE_BUTTON = (7, 30)
EVENT_END_STEP = (3, 2)
EVENT_KEYBOARD_A = (5, 65)
EVENT_KEY_PRESS_A = (9, 65)
EVENT_KEY_RELEASE_A = (10, 65)
EVENT_DRAW = (8, 0)
EVENT_DRAW_GUI = (8, 64)
EVENT_DRAW_RESIZE = (8, 65)
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
        "function who() {\n"
        '    if (object_index == o_a) return "a";\n'
        '    if (object_index == o_c) return "c";\n'
        '    if (object_index == o_d) return "d";\n'
        '    if (object_index == o_f) return "f";\n'
        '    if (object_index == o_g) return "g";\n'
        '    return "?";\n'
        "}\n"
    ),
}

# Event name -> event key. The events of o_a record "<name>:a:<who>", those
# of o_d "<name>:d:<who>" before event_inherited().
_EVENTS: Mapping[str, tuple[int, int]] = {
    "create": EVENT_CREATE,
    "destroy": EVENT_DESTROY,
    "clean_up": EVENT_CLEAN_UP,
    "begin_step": EVENT_BEGIN_STEP,
    "step": EVENT_STEP,
    "end_step": EVENT_END_STEP,
    "alarm0": EVENT_ALARM_0,
    "draw": EVENT_DRAW,
    "draw_begin": EVENT_DRAW_BEGIN,
    "draw_end": EVENT_DRAW_END,
    "pre_draw": EVENT_PRE_DRAW,
    "post_draw": EVENT_POST_DRAW,
    "draw_gui": EVENT_DRAW_GUI,
    "draw_gui_begin": EVENT_DRAW_GUI_BEGIN,
    "draw_gui_end": EVENT_DRAW_GUI_END,
    "user0": EVENT_USER_0,
    "user3": EVENT_USER_3,
    "game_start": EVENT_GAME_START,
    "room_start": EVENT_ROOM_START,
    "outside_room": EVENT_OUTSIDE_ROOM,
    "key_held": EVENT_KEYBOARD_A,
    "key_pressed": EVENT_KEY_PRESS_A,
    "key_released": EVENT_KEY_RELEASE_A,
    "resize": EVENT_DRAW_RESIZE,
    "close_button": EVENT_CLOSE_BUTTON,
}
_COLLISION_EVENT = "collision_wall"
# The events that happen once per instance; every other one repeats (Outside
# Room runs when the instance leaves the room, not while it stays outside:
# Events.js sets fOutsideRoom).
_ONCE = frozenset({
    "create", "destroy", "clean_up", "alarm0", "user0", "user3", "game_start", "room_start",
    "outside_room", "key_pressed", "key_released", "resize", "close_button",
})
# Events the window sends, not the game: the probe triggers them.
_WINDOW_EVENTS = ("resize", "close_button")


def _record(name: str, level: str) -> str:
    return f'trace("{name}:{level}:" + who());\n'


def _events(level: str, inherit: bool, names: Sequence[str]) -> dict[tuple[int, int], str]:
    suffix = "event_inherited();\n" if inherit else ""
    return {_EVENTS[name]: _record(name, level) + suffix for name in names}


# Drives the instances: user events and alarms at step 3, the key down at step
# 4 and up at step 6, a move out of the room at step 8, and the destruction of
# the instances at step 10. The controller is the first instance, so what it
# does in a step reaches every other instance before that instance's own
# events of the same phase.
_CONTROLLER_STEP = (
    "frame += 1;\n"
    "if (frame == 3) {\n"
    "    with (o_a) {\n"
    "        alarm[0] = 2;\n"
    "        event_user(0);\n"
    "        event_perform(ev_other, ev_user3);\n"
    "    }\n"
    "}\n"
    "if (frame == 4) keyboard_key_press(ord(\"A\"));\n"
    "if (frame == 6) keyboard_key_release(ord(\"A\"));\n"
    "if (frame == 8) {\n"
    "    with (o_a) x = -1000;\n"
    "}\n"
    "if (frame == 10) {\n"
    "    with (o_a) instance_destroy();\n"
    "}\n"
)

_BOX = GameMakerSprite("spr_box", 16, 16)
_GAME_EVENTS = [name for name in _EVENTS if name not in _WINDOW_EVENTS]
_STEP_EVENTS = ("step", "resize", "close_button")


def _placed(letters: Sequence[str]) -> tuple[RoomInstance, ...]:
    return tuple(
        RoomInstance(f"inst_{letter}", f"o_{letter}", 20 + 50 * index, 100)
        for index, letter in enumerate(letters)
    )


def _walls(letters: Sequence[str]) -> tuple[RoomInstance, ...]:
    return tuple(
        RoomInstance(f"inst_wall_{letter}", "o_wall", 20 + 50 * index, 100)
        for index, letter in enumerate(letters)
    )


_LETTERS = ("a", "c", "d", "f", "g")

_EVENTS_PROJECT = GameMakerProject(
    name="EventInheritance",
    scripts=_SCRIPTS,
    sprites=(_BOX,),
    objects=(
        GameMakerObject("o_wall", {}, sprite="spr_box"),
        GameMakerObject(
            "o_a",
            _events("a", False, list(_EVENTS)),
            sprite="spr_box",
            collisions={"o_wall": _record(_COLLISION_EVENT, "a")},
        ),
        GameMakerObject("o_b", {}, parent="o_a", sprite="spr_box"),
        GameMakerObject("o_e", {}, parent="o_b", sprite="spr_box"),
        GameMakerObject("o_c", {}, parent="o_e", sprite="spr_box"),
        GameMakerObject(
            "o_d",
            _events("d", True, list(_EVENTS)),
            parent="o_e",
            sprite="spr_box",
            collisions={"o_wall": _record(_COLLISION_EVENT, "d") + "event_inherited();\n"},
        ),
        # Its own Create event replaces the ancestor's.
        GameMakerObject("o_f", _events("f", False, ["create"]), parent="o_e", sprite="spr_box"),
        # Replaces some events without calling event_inherited().
        GameMakerObject("o_g", _events("g", False, _STEP_EVENTS), parent="o_e", sprite="spr_box"),
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
                    (RoomInstance("inst_ctrl", "o_ctrl", 0, 0), *_placed(_LETTERS), *_walls(_LETTERS)),
                ),
            ),
            creation_order=(
                "inst_ctrl",
                *(f"inst_{letter}" for letter in _LETTERS),
                *(f"inst_wall_{letter}" for letter in _LETTERS),
            ),
        ),
    ),
)

# The window events alone: no object has a Create event, and o_f, whose own
# Create event does not call event_inherited(), is the only one with one.
_WINDOW_PROJECT = GameMakerProject(
    name="WindowEventInheritance",
    scripts=_SCRIPTS,
    objects=(
        GameMakerObject("o_a", _events("a", False, _WINDOW_EVENTS)),
        GameMakerObject("o_b", {}, parent="o_a"),
        GameMakerObject("o_e", {}, parent="o_b"),
        GameMakerObject("o_c", {}, parent="o_e"),
        GameMakerObject("o_d", _events("d", True, _WINDOW_EVENTS), parent="o_e"),
        GameMakerObject("o_f", _events("f", False, ["create"]), parent="o_e"),
        GameMakerObject("o_g", _events("g", False, _WINDOW_EVENTS), parent="o_e"),
        GameMakerObject(
            "o_ctrl",
            {
                EVENT_CREATE: "frame = 0;\n",
                # event_perform(ev_other, ev_close_button) runs the handler too.
                EVENT_STEP: "frame += 1;\nif (frame == 8) { with (o_a) event_perform(ev_other, ev_close_button); }\n",
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_ctrl", "o_ctrl", 0, 0), *_placed(_LETTERS))),),
            creation_order=("inst_ctrl", *(f"inst_{letter}" for letter in _LETTERS)),
        ),
    ),
)


@dataclass(frozen=True)
class _Run:
    trace: list[str]
    auto_accept_quit: bool
    # The conversion log.
    log: list[str]


@dataclass(frozen=True)
class _Behaviour:
    """What an instance does with the events o_a handles."""

    # Events the object handles itself and also hands to its ancestor.
    extended: frozenset[str] = frozenset()
    # Events the object handles itself and does not hand on.
    replaced: frozenset[str] = frozenset()


_BEHAVIOURS = {
    "a": _Behaviour(),
    "c": _Behaviour(),
    "d": _Behaviour(extended=frozenset([*_EVENTS, _COLLISION_EVENT])),
    "f": _Behaviour(replaced=frozenset({"create"})),
    "g": _Behaviour(replaced=frozenset(_STEP_EVENTS)),
}


def _expected_runs(per_event: Mapping[str, int], letters: Sequence[str]) -> Counter[str]:
    """Runs of each handler when every instance has per_event[name] events."""
    expected: Counter[str] = Counter()
    for letter in letters:
        behaviour = _BEHAVIOURS[letter]
        for name, count in per_event.items():
            if name in behaviour.replaced:
                expected[f"{name}:{letter}:{letter}"] += count
                continue
            if name in behaviour.extended:
                expected[f"{name}:{letter}:{letter}"] += count
            expected[f"{name}:a:{letter}"] += count
    return expected


# Objects whose Create event does not transpile get no script: o_y below o_x,
# and the root o_r. Their descendants must still load (they used to extend a
# script that was never written) and run the events of the nearest object that
# has a script.
_SKIPPED_SCRIPTS = {
    "scr_trace": (
        "function trace(_text) {\n"
        '    if (!variable_global_exists("trace")) global.trace = [];\n'
        "    array_push(global.trace, _text);\n"
        "}\n"
        "function who() {\n"
        '    if (object_index == o_x) return "x";\n'
        '    if (object_index == o_z) return "z";\n'
        '    if (object_index == o_w) return "w";\n'
        '    if (object_index == o_s) return "s";\n'
        '    if (object_index == o_t) return "t";\n'
        '    return "?";\n'
        "}\n"
    ),
}
_SKIPPED_PARENT_PROJECT = GameMakerProject(
    name="SkippedParent",
    scripts=_SKIPPED_SCRIPTS,
    objects=(
        GameMakerObject("o_x", {EVENT_CREATE: 'trace("create:x:" + who());\n'}),
        GameMakerObject("o_y", {EVENT_CREATE: "hp = ==== 1;\n"}, parent="o_x"),
        GameMakerObject("o_z", {EVENT_CREATE: 'trace("create:z:" + who());\nevent_inherited();\n'}, parent="o_y"),
        GameMakerObject("o_w", {}, parent="o_z"),
        GameMakerObject("o_r", {EVENT_CREATE: "= = ;\n"}),
        GameMakerObject("o_s", {EVENT_CREATE: 'trace("create:s:" + who());\nevent_inherited();\n'}, parent="o_r"),
        GameMakerObject("o_t", {}, parent="o_s"),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    tuple(RoomInstance(f"inst_{letter}", f"o_{letter}", 20 + 50 * index, 100) for index, letter in enumerate("xzwst")),
                ),
            ),
            creation_order=tuple(f"inst_{letter}" for letter in "xzwst"),
        ),
    ),
)
# o_z and o_w run the Create event of o_x, the nearest object with a script;
# o_s is the root of its own script and has nothing to inherit.
_EXPECTED_SKIPPED_PARENT = Counter({
    "create:x:x": 1,
    "create:z:z": 1,
    "create:x:z": 1,
    "create:z:w": 1,
    "create:x:w": 1,
    "create:s:s": 1,
    "create:s:t": 1,
})

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

# Dumps the trace at the 24th frame. The window sends a resize and a close
# request in the third frame, as the operating system does for the root window.
_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _window_events = %s


func _process(_delta):
	_frames += 1
	if _frames == 3 and _window_events:
		get_tree().root.size_changed.emit()
		get_tree().root.propagate_notification(NOTIFICATION_WM_CLOSE_REQUEST)
	if _frames == 24:
		print("EVENT_INHERITANCE_TRACE " + JSON.stringify({
			"trace": GMRuntime.gml_global_scope().get("trace", []),
			"auto_accept_quit": get_tree().auto_accept_quit,
		}))
		get_tree().quit(0)
"""


class TestEventInheritanceGodot(unittest.TestCase):
    maxDiff = None

    def test_every_event_reaches_the_nearest_ancestor_through_parents_without_events(self) -> None:
        run = self._run_trace(_EVENTS_PROJECT, window_events=True)
        runs = Counter(run.trace)
        # What an instance of o_a placed directly in the room does.
        per_event = {name: runs[f"{name}:a:a"] for name in [*_EVENTS, _COLLISION_EVENT]}
        for name, count in per_event.items():
            if name in _ONCE:
                self.assertEqual(count, 1, name)
            else:
                self.assertGreaterEqual(count, 2, name)
        # Every instance runs each handler as often, whichever object owns it.
        expected = _expected_runs(per_event, _LETTERS)
        # The collision event of o_d is handed on like the others.
        self.assertEqual(runs, expected)
        # Closing the window does not end a game that handles the event.
        self.assertFalse(run.auto_accept_quit)

    def test_handlers_of_an_overriding_object_run_before_the_ancestors(self) -> None:
        trace = self._run_trace(_EVENTS_PROJECT, window_events=True).trace
        for name in [*_EVENTS, _COLLISION_EVENT]:
            levels = [line.split(":")[1] for line in trace if line.startswith(f"{name}:") and line.endswith(":d")]
            self.assertEqual(levels, ["d", "a"] * (len(levels) // 2), name)

    def test_window_events_reach_descendants_of_objects_without_a_create_event(self) -> None:
        run = self._run_trace(_WINDOW_PROJECT, window_events=True)
        runs = Counter(run.trace)
        # One close request from the window and one event_perform for the
        # Close Button event, one resize.
        per_event = {"resize": 1, "close_button": 2}
        expected = _expected_runs(per_event, _LETTERS)
        # The own Create event of o_f.
        expected["create:f:f"] += 1
        self.assertEqual(runs, expected)
        self.assertFalse(run.auto_accept_quit)

    def test_children_of_objects_without_a_script_load_and_inherit_from_the_nearest_one(self) -> None:
        run = self._run_trace(_SKIPPED_PARENT_PROJECT)
        self.assertEqual(Counter(run.trace), _EXPECTED_SKIPPED_PARENT)
        self.assertLess(run.trace.index("create:z:z"), run.trace.index("create:x:z"))
        # The conversion says what the children lost.
        warnings = [line for line in run.log if "produced no script" in line]
        self.assertEqual(len(warnings), 2, run.log)
        self.assertTrue(any("'o_z' extends 'o_x'" in line and "'o_y'" in line for line in warnings), warnings)
        self.assertTrue(any("'o_s' extends no object script" in line and "'o_r'" in line for line in warnings), warnings)

    def test_variable_definitions_without_events_run_before_the_inherited_create(self) -> None:
        run = self._run_trace(_DEFINITIONS_PROJECT, properties=_DEFINITIONS_PROPERTIES)
        trace = run.trace
        self.assertEqual(sorted(trace), sorted(_EXPECTED_DEFINITIONS))
        self.assertLess(trace.index("create:d:d:200"), trace.index("create:a:d:1:11"))
        # Without a Close Button event the window closes the game.
        self.assertTrue(run.auto_accept_quit)

    def _run_trace(
        self,
        project: GameMakerProject,
        properties: dict[str, Sequence[tuple[object, ...]]] | None = None,
        window_events: bool = False,
    ) -> _Run:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            if properties is not None:
                write_variable_definitions(root / "gamemaker", project, properties, {}, {})
            log = convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE % str(window_events).lower())
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
        dump = json.loads(trace_lines[0].removeprefix("EVENT_INHERITANCE_TRACE "))
        return _Run(dump["trace"], dump["auto_accept_quit"], log)


if __name__ == "__main__":
    unittest.main()
