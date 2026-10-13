"""Godot checks that converted GML handles the edge cases of numbers like GameMaker.

Each case is GML source in a converted object's Create event; the game records
what the expressions give, and the test compares it with what GameMaker's
runner gives (scripts/functions/Function_Maths.js, scripts/long/long.js).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
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
    "function trace(_name, _value) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    '    array_push(global.trace, _name + ":" + (is_undefined(_value) ? "error" : string(_value)));\n'
    "}\n"
)

_PROBE_CREATE = """\
var zero = 0;
// A zero divisor is an error for every kind of mod (yyfmod).
trace("5.5 mod 0", 5.5 mod 0);
trace("5 mod 0.0", 5 mod 0.0);
trace("5.5 % zero", 5.5 % zero);
var counter = 7.5;
counter %= zero;
trace("counter %= zero", counter);
trace("int64(5) mod 0", int64(5) mod 0);
trace("5 mod 0", 5 mod 0);
trace("5.5 mod 2", 5.5 mod 2);
trace("-5 mod 3", -5 mod 3);
// An int64 is made of a real as Long.fromNumber does: NaN is 0 and a real
// beyond the int64 range saturates.
var huge = power(10, 19);
trace("int64(1e19)", int64(huge));
trace("int64(-1e19)", int64(-huge));
trace("int64(infinity)", int64(infinity));
trace("int64(-infinity)", int64(-infinity));
trace("int64(NaN)", int64(NaN));
trace("int64(-3.9)", int64(-3.9));
var smallest = 1 << 63;
trace("(1 << 63) div 1e20", smallest div power(10, 20));
trace("(1 << 63) div infinity", smallest div infinity);
trace("(1 << 63) div NaN", smallest div NaN);
trace("1e19 & 255", huge & 255);
"""

_EXPECTED_TRACE = [
    "5.5 mod 0:error",
    "5 mod 0.0:error",
    "5.5 % zero:error",
    "counter %= zero:error",
    "int64(5) mod 0:error",
    "5 mod 0:error",
    "5.5 mod 2:1.50",
    "-5 mod 3:-2",
    "int64(1e19):9223372036854775807",
    "int64(-1e19):-9223372036854775808",
    "int64(infinity):9223372036854775807",
    "int64(-infinity):-9223372036854775808",
    "int64(NaN):0",
    "int64(-3.9):-3",
    "(1 << 63) div 1e20:-1",
    "(1 << 63) div infinity:-1",
    "(1 << 63) div NaN:error",
    "1e19 & 255:255",
]

_PROJECT = GameMakerProject(
    name="NumberEdgeCases",
    scripts={"scr_trace": _SCRIPT},
    objects=(GameMakerObject("o_probe", {EVENT_CREATE: _PROBE_CREATE}),),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_probe", "o_probe", 16, 16),)),),
            creation_order=("inst_probe",),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 6:
		print("NUMBER_EDGES_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestNumberEdgeCasesGodot(unittest.TestCase):
    def test_converted_numbers_follow_the_runner(self) -> None:
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
        self.assertNotIn("Parse Error", output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("Cannot represent", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("NUMBER_EDGES_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("NUMBER_EDGES_TRACE ")), _EXPECTED_TRACE)
        self.assertEqual(output.count("GML runtime error: unable to mod with zero"), 6, output)
        self.assertEqual(output.count("GML runtime error: GML int64 division by zero"), 1, output)


if __name__ == "__main__":
    unittest.main()
