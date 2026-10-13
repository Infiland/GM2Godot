"""Godot checks for how the array functions read the results of GML callbacks, in a converted project.

A callback that falls off its end (or returns nothing) gives undefined. The
runner reads a predicate's result with yyGetBool, which is false for
undefined and for a number up to 0.5 (yyTypes.js), so array_filter drops an
element whose predicate gives undefined or 0.3; a GDScript truth test would
keep any object, including the undefined value, and any non-zero number.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_runtime import GML_RUNTIME_SCRIPT
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

_SCRIPTS = (
    "function record(_key, _text) {\n"
    '    if (!variable_global_exists("record")) global.record = {};\n'
    "    global.record[$ _key] = _text;\n"
    "}\n"
    'function flag(_value) { return _value ? "T" : "F"; }\n'
    "function joined(_values) {\n"
    '    var _text = "";\n'
    "    for (var i = 0; i < array_length(_values); i++) {\n"
    '        _text += (i > 0 ? "," : "") + string(_values[i]);\n'
    "    }\n"
    "    return _text;\n"
    "}\n"
    # A script function whose body ends without a return.
    "function pred_off_end(_v) { if (_v > 2) return true; }\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 6:
		var scope = GMRuntime.gml_global_scope()
		print("RECORD " + JSON.stringify(scope.get("record", {})))
		get_tree().quit(0)
"""

_CREATE = (
    "global.total = 0;\n"
    'global.keys = "";\n'
    "var _a = [1, 2, 3, 4];\n"
    # Predicates that fall off the end, in the 1-parameter literal form and as
    # a script function and a bound method.
    'record("filter_literal", joined(array_filter(_a, function(v) { if (v > 2) return true; })));\n'
    'record("filter_nothing", joined(array_filter(_a, function(v) { var _w = v; })));\n'
    'record("filter_bare_return", joined(array_filter(_a, function(v) { if (v > 3) return; return true; })));\n'
    'record("filter_script", joined(array_filter(_a, pred_off_end)));\n'
    "var _bound = method(self, function(v) { if (v < 3) return true; });\n"
    'record("filter_method", joined(array_filter(_a, _bound)));\n'
    # yyGetBool reads a number as true above 0.5, and "true" and "false".
    'record("filter_fraction", joined(array_filter(_a, function(v) { return v * 0.3; })));\n'
    'record("filter_text", joined(array_filter(_a, function(v) { return v > 2 ? "true" : "false"; })));\n'
    'record("filter_bool", joined(array_filter(_a, function(v) { return v == 2 || v == 4; })));\n'
    # The other callback consumers.
    'record("find_index", string(array_find_index(_a, function(v) { if (v > 2) return true; }))'
    ' + "/" + string(array_find_index(_a, function(v) { var _w = v; })));\n'
    "var _mapped = array_map(_a, function(v) { if (v > 2) return v; });\n"
    'record("map", flag(is_undefined(_mapped[0])) + flag(is_undefined(_mapped[1])) + flag(is_undefined(_mapped[2])) + flag(is_undefined(_mapped[3])));\n'
    "var _reduced = array_reduce(_a, function(acc, v) { if (v < 4) return acc + v; }, 0);\n"
    'record("reduce", flag(is_undefined(_reduced)));\n'
    "array_foreach(_a, function(v) { global.total += v; });\n"
    'record("foreach", string(global.total));\n'
    "struct_foreach({ a: 1, b: 2 }, function(k, v) { global.keys += k; });\n"
    'record("struct_foreach", global.keys);\n'
)

_PROJECT = GameMakerProject(
    name="CallbackResults",
    scripts={"scr_helpers": _SCRIPTS},
    objects=(GameMakerObject("o_probe", {EVENT_CREATE: _CREATE}),),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_probe", "o_probe", 0, 0),)),),
            creation_order=("inst_probe",),
        ),
    ),
)

_EXPECTED = {
    "filter_literal": "3,4",
    "filter_nothing": "",
    "filter_bare_return": "1,2,3",
    "filter_script": "3,4",
    "filter_method": "1,2",
    "filter_fraction": "2,3,4",
    "filter_text": "3,4",
    "filter_bool": "2,4",
    "find_index": "2/-1",
    "map": "TTFF",
    "reduce": "T",
    "foreach": "10",
    "struct_foreach": "ab",
}


class TestCallbackResultsGodot(unittest.TestCase):
    def test_predicate_results_are_read_as_gml_booleans(self) -> None:
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
        for failure in ("GML runtime error", "SCRIPT ERROR", "Parse Error"):
            self.assertNotIn(failure, output)
        record_lines = [line for line in output.splitlines() if line.startswith("RECORD ")]
        self.assertEqual(len(record_lines), 1, output)
        record = json.loads(record_lines[0].removeprefix("RECORD "))
        self.assertEqual(record, _EXPECTED, output)

    def test_array_functions_test_callback_results_with_gml_bool(self) -> None:
        # The results of callbacks are GML values: an `if` on one would be a
        # GDScript truth test.
        start = GML_RUNTIME_SCRIPT.index("static func gml_array_filter(")
        body = GML_RUNTIME_SCRIPT[start : GML_RUNTIME_SCRIPT.index("\nstatic func", start)]
        self.assertIn("if gml_bool(gml_call_value(", body)


if __name__ == "__main__":
    unittest.main()
