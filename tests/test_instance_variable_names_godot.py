"""Godot checks for which variables an instance has, in a converted project.

GameMaker gives an instance a variable when code first assigns it, so
variable_instance_exists is false until then (which the lazy set-up idiom
`if (!variable_instance_exists(id, "steps")) steps = 0;` relies on) and true
for every built-in instance variable. variable_instance_get_names,
variable_instance_names_count and the struct_* functions list only the
variables code has assigned, and count 0 when nothing is selected. The
runner's variable_instance_exists checks for the "gml" property code assigns
and __internal__get_variable_names lists those properties (yyVariable.js).
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
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_SCRIPT = (
    "function trace(_value) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _value);\n"
    "}\n"
)

_COUNTER_CREATE = "hp = 3;\ngone = undefined;\n"
_COUNTER_STEP = (
    'if (!variable_instance_exists(id, "steps")) steps = 0;\n'
    "steps += 1;\n"
    "if (hp > 100) unused = 1;\n"
)
_RUNNER_STEP = """\
if (variable_global_exists("names_done")) exit;
global.names_done = true;
var _c = instance_find(o_counter, 0);
variable_instance_set(_c, "added", 5);
trace(_c.steps);
trace([
    variable_instance_exists(_c, "hp"),
    variable_instance_exists(_c, "steps"),
    variable_instance_exists(_c, "gone"),
    variable_instance_exists(_c, "added"),
    variable_instance_exists(_c, "unused"),
    variable_instance_exists(_c, "x"),
    variable_instance_exists(_c, "sprite_width"),
    variable_instance_exists(_c, "speed"),
    variable_instance_exists(_c, "id"),
    variable_instance_exists(_c, "name"),
    variable_instance_exists(_c, "position"),
    variable_instance_exists(_c, "other"),
    struct_exists(_c, "unused"),
]);
var _names = variable_instance_get_names(_c);
array_sort(_names, true);
trace(_names);
var _struct_names = struct_get_names(_c);
array_sort(_struct_names, true);
trace(_struct_names);
trace([variable_instance_names_count(_c), struct_names_count(_c)]);
with (_c) {
    trace(variable_instance_names_count(self));
}
trace([variable_instance_names_count(noone), struct_names_count(noone), variable_instance_get_names(noone)]);
"""

_PROJECT = GameMakerProject(
    name="InstanceVariableNames",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject("o_counter", {EVENT_CREATE: _COUNTER_CREATE, EVENT_STEP: _COUNTER_STEP}),
        GameMakerObject("o_runner", {EVENT_STEP: _RUNNER_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_counter", "o_counter", 0, 0),
                        RoomInstance("inst_runner", "o_runner", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_counter", "inst_runner"),
        ),
    ),
)

# The counter's first step (it comes first) sets steps up and adds 1.
_EXPECTED_TRACE: list[object] = [
    1,
    [True, True, True, True, False, True, True, True, True, False, False, False, False],
    ["added", "gone", "hp", "steps"],
    ["added", "gone", "hp", "steps"],
    [4, 4],
    4,
    [0, 0, []],
]

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("INSTANCE_NAMES_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestInstanceVariableNamesGodot(unittest.TestCase):
    def test_instances_have_the_variables_their_code_assigned(self) -> None:
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
        trace_lines = [line for line in output.splitlines() if line.startswith("INSTANCE_NAMES_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("INSTANCE_NAMES_TRACE ")), _EXPECTED_TRACE)


if __name__ == "__main__":
    unittest.main()
