"""Godot checks for the values ds_grid and ds_list functions compare, add and insert, in a converted project.

A fresh ds_grid cell holds 0 (the runner's yyGrid), so searching a grid that
also holds instance ids or strings compares values of different types, which
GDScript's == refuses. The runner searches row by row after putting the
corners in order and cutting them to the grid, matches two numbers within
its precision (1e-7) and anything else by ==, and reports -1 for a value it
does not find (ds_grid_value_common, ds_grid.js). ds_grid_add joins strings,
adds numbers and otherwise replaces the cell, and ds_grid_multiply leaves a
cell alone when it or the factor is a string. yyList.Insert does nothing for
a position past the end of the list (yyList.js).
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
    "function found(_grid, _x1, _y1, _x2, _y2, _value) {\n"
    '    return (ds_grid_value_exists(_grid, _x1, _y1, _x2, _y2, _value) ? "T" : "F")'
    ' + "/" + string(ds_grid_value_x(_grid, _x1, _y1, _x2, _y2, _value))'
    ' + "/" + string(ds_grid_value_y(_grid, _x1, _y1, _x2, _y2, _value));\n'
    "}\n"
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

# The grid holds an instance id and a string next to the fresh cells' 0.
_CREATE = (
    "var _grid = ds_grid_create(3, 3);\n"
    # Values of other types than the cells' 0 are not found, and -1 says so.
    'record("fresh_id", found(_grid, 0, 0, 2, 2, id));\n'
    'record("fresh_string", found(_grid, 0, 0, 2, 2, "abc"));\n'
    'record("fresh_zero", found(_grid, 1, 1, 2, 2, 0));\n'
    "ds_grid_set(_grid, 1, 1, id);\n"
    'ds_grid_set(_grid, 2, 0, "abc");\n'
    "ds_grid_set(_grid, 0, 1, 0.1 + 0.2);\n"
    'record("found_id", found(_grid, 0, 0, 2, 2, id));\n'
    'record("found_string", found(_grid, 0, 0, 2, 2, "abc") + "/" + found(_grid, 0, 0, 2, 2, "abd"));\n'
    # A number matches within the runner's precision.
    'record("precision", found(_grid, 0, 0, 2, 2, 0.3));\n'
    # The corners may come in either order and the region is cut to the grid.
    'record("swapped", found(_grid, 2, 2, 0, 0, "abc"));\n'
    'record("cut", found(_grid, -4, -4, 9, 9, id));\n'
    'record("outside", found(_grid, 5, 5, 9, 9, "abc"));\n'
    "ds_grid_destroy(_grid);\n"
    # ds_grid_add joins strings, adds numbers and otherwise replaces the cell.
    "var _sums = ds_grid_create(3, 2);\n"
    'ds_grid_add(_sums, 0, 0, "ab");\n'
    'record("add_string_first", string(ds_grid_get(_sums, 0, 0)));\n'
    'ds_grid_add(_sums, 0, 0, "cd");\n'
    "ds_grid_add(_sums, 1, 0, 3);\n"
    "ds_grid_add(_sums, 1, 0, 4);\n"
    'record("add_join", string(ds_grid_get(_sums, 0, 0)) + "/" + string(ds_grid_get(_sums, 1, 0)));\n'
    "ds_grid_add(_sums, 0, 0, 5);\n"
    'ds_grid_add(_sums, 1, 0, "x");\n'
    'record("add_replace", string(ds_grid_get(_sums, 0, 0)) + "/" + string(ds_grid_get(_sums, 1, 0)));\n'
    "ds_grid_multiply(_sums, 0, 0, 3);\n"
    "ds_grid_multiply(_sums, 1, 0, 2);\n"
    'record("multiply", string(ds_grid_get(_sums, 0, 0)) + "/" + string(ds_grid_get(_sums, 1, 0)));\n'
    'ds_grid_set(_sums, 2, 0, "keep");\n'
    "ds_grid_multiply(_sums, 2, 0, 2);\n"
    'ds_grid_multiply(_sums, 0, 0, "2");\n'
    'record("multiply_string", string(ds_grid_get(_sums, 2, 0)) + "/" + string(ds_grid_get(_sums, 0, 0)));\n'
    'ds_grid_add_region(_sums, 0, 1, 2, 1, "z");\n'
    'ds_grid_add_region(_sums, 0, 1, 1, 1, "y");\n'
    "ds_grid_multiply_region(_sums, 0, 1, 2, 1, 2);\n"
    'record("regions", string(ds_grid_get(_sums, 0, 1)) + "/" + string(ds_grid_get(_sums, 1, 1)) + "/" + string(ds_grid_get(_sums, 2, 1)));\n'
    "ds_grid_destroy(_sums);\n"
    # ds_list_insert does nothing past the end of the list; the end itself appends.
    "var _list = ds_list_create();\n"
    'ds_list_add(_list, "a", "b");\n'
    'ds_list_insert(_list, 5, "far");\n'
    'ds_list_insert(_list, -1, "negative");\n'
    'record("insert_outside", string(ds_list_size(_list)) + ":" + string(ds_list_find_value(_list, 2)));\n'
    'ds_list_insert(_list, 2, "end");\n'
    'ds_list_insert(_list, 0, "first");\n'
    'record("insert", string(ds_list_size(_list)) + ":" + string(ds_list_find_value(_list, 0)) + string(ds_list_find_value(_list, 1))'
    ' + string(ds_list_find_value(_list, 2)) + string(ds_list_find_value(_list, 3)));\n'
    "ds_list_destroy(_list);\n"
)

_PROJECT = GameMakerProject(
    name="DsValues",
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
    "fresh_id": "F/-1/-1",
    "fresh_string": "F/-1/-1",
    "fresh_zero": "T/1/1",
    "found_id": "T/1/1",
    "found_string": "T/2/0/F/-1/-1",
    "precision": "T/0/1",
    "swapped": "T/2/0",
    "cut": "T/1/1",
    "outside": "F/-1/-1",
    "add_string_first": "ab",
    "add_join": "abcd/7",
    "add_replace": "5/x",
    "multiply": "15/x",
    "multiply_string": "keep/15",
    "regions": "zy/zy/z",
    "insert_outside": "2:undefined",
    "insert": "4:firstabend",
}


class TestDsValuesGodot(unittest.TestCase):
    def test_grid_searches_adds_and_list_inserts_match_the_runner(self) -> None:
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

    def test_grid_value_searches_use_gml_equality_not_gdscript_equality(self) -> None:
        # GDScript's == raises "Invalid operands" for an int cell and an
        # object or string value, which is what the fresh cells' 0 hit.
        for name in ("value_exists", "value_x", "value_y"):
            start = GML_RUNTIME_SCRIPT.index(f"static func gml_ds_grid_{name}(")
            body = GML_RUNTIME_SCRIPT[start : GML_RUNTIME_SCRIPT.index("\nstatic func", start)]
            self.assertNotIn("row[x] == val", body)
            self.assertIn("_gml_ds_grid_value_find(", body)
        self.assertIn("elif _gml_is_equal(cell, val):", GML_RUNTIME_SCRIPT)


if __name__ == "__main__":
    unittest.main()
