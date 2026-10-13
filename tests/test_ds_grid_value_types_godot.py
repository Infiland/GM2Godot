"""Godot checks for how ds_grid searches, adds and multiplies cells of each type, in a converted project.

The grid loops test the type of val once and of each cell inline (a number
against an int or a real cell, a string against a string cell, an object by
identity), and fall back to GML equality and the add and multiply helpers for
the other combinations. Each combination below has to give what the runner
gives (ds_grid_value_common and ds_grid_add_region in ds_grid.js), including
the region the search covers and the 64-bit integers, which the runner
compares by value (yyCompareVal) where GDScript's == compares two objects.
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
    "function row_text(_grid, _y) {\n"
    '    var _text = "";\n'
    "    for (var _x = 0; _x < ds_grid_width(_grid); _x++) {\n"
    '        _text += (_x > 0 ? "/" : "") + string(ds_grid_get(_grid, _x, _y));\n'
    "    }\n"
    "    return _text;\n"
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

_CREATE = (
    # Whole numbers and reals match a number within the runner's precision
    # (1e-7), whichever of them the cell and the value are.
    "var _numbers = ds_grid_create(4, 3);\n"
    "ds_grid_set(_numbers, 1, 1, 5);\n"
    "ds_grid_set(_numbers, 2, 0, 7.00000001);\n"
    "ds_grid_set(_numbers, 0, 2, 7.1);\n"
    'record("int_cell_near_real", found(_numbers, 0, 0, 3, 2, 5.00000001) + "," + found(_numbers, 0, 0, 3, 2, 5.0000002));\n'
    'record("real_cell_near_int", found(_numbers, 0, 0, 3, 2, 7) + "," + found(_numbers, 0, 0, 3, 2, 7.1));\n'
    'record("int_cell_exact", found(_numbers, 0, 0, 3, 2, 5) + "," + found(_numbers, 0, 0, 3, 2, 6));\n'
    # The search goes row by row and only through the region.
    "ds_grid_set(_numbers, 3, 0, 5);\n"
    "ds_grid_set(_numbers, 0, 1, 5);\n"
    'record("row_order", found(_numbers, 0, 0, 3, 2, 5));\n'
    'record("region_start", found(_numbers, 1, 1, 3, 2, 5) + "," + found(_numbers, 2, 0, 3, 0, 5) + ","'
    ' + found(_numbers, 1, 0, 2, 2, 5));\n'
    # Past 2^53 several whole numbers are one real, so those match what is searched for as reals.
    "var _huge = ds_grid_create(3, 1);\n"
    "ds_grid_set(_huge, 1, 0, 10000000000000000);\n"
    "ds_grid_set(_huge, 2, 0, 9007199254740993);\n"
    'record("huge", found(_huge, 0, 0, 2, 0, 10000000000000000.0) + "," + found(_huge, 0, 0, 2, 0, 9007199254740992));\n'
    "ds_grid_destroy(_huge);\n"
    "ds_grid_destroy(_numbers);\n"
    # A string only equals a string; a number cell never matches it.
    "var _words = ds_grid_create(3, 2);\n"
    'ds_grid_clear(_words, "ab");\n'
    'ds_grid_set(_words, 2, 1, "needle");\n'
    'record("string_grid", found(_words, 0, 0, 2, 1, "ab") + "," + found(_words, 0, 0, 2, 1, "needle")'
    ' + "," + found(_words, 0, 0, 2, 1, "abc"));\n'
    "ds_grid_set(_words, 0, 0, 3);\n"
    'record("string_among_numbers", found(_words, 0, 0, 2, 1, "ab") + "," + found(_words, 0, 0, 2, 1, "3"));\n'
    "ds_grid_destroy(_words);\n"
    # A boolean equals a number that is 1 or 0 and a boolean that is the same.
    "var _flags = ds_grid_create(3, 1);\n"
    "ds_grid_clear(_flags, false);\n"
    'record("bool_grid", found(_flags, 0, 0, 2, 0, true) + "," + found(_flags, 0, 0, 2, 0, false));\n'
    "ds_grid_set(_flags, 2, 0, true);\n"
    'record("bool_found", found(_flags, 0, 0, 2, 0, true));\n'
    "ds_grid_set(_flags, 1, 0, 2);\n"
    "ds_grid_set(_flags, 2, 0, 1);\n"
    'record("bool_number", found(_flags, 0, 0, 2, 0, true) + "," + found(_flags, 1, 0, 1, 0, true));\n'
    "ds_grid_destroy(_flags);\n"
    # An instance equals only itself, and undefined only undefined.
    "var _things = ds_grid_create(3, 1);\n"
    "ds_grid_set(_things, 1, 0, id);\n"
    "ds_grid_set(_things, 2, 0, undefined);\n"
    'record("object_identity", found(_things, 0, 0, 2, 0, id) + "," + found(_things, 0, 0, 2, 0, undefined)'
    ' + "," + found(_things, 0, 0, 2, 0, noone));\n'
    "ds_grid_destroy(_things);\n"
    # 64-bit integers compare by value: with the numbers, and with each other.
    "var _longs = ds_grid_create(3, 1);\n"
    "ds_grid_set(_longs, 0, 0, int64(5));\n"
    "ds_grid_set(_longs, 1, 0, 9);\n"
    "ds_grid_set(_longs, 2, 0, 7.5);\n"
    'record("int64_cell", found(_longs, 0, 0, 2, 0, 5) + "," + found(_longs, 0, 0, 2, 0, 5.0)'
    ' + "," + found(_longs, 0, 0, 2, 0, 6));\n'
    'record("int64_value", found(_longs, 0, 0, 2, 0, int64(9)) + "," + found(_longs, 0, 0, 2, 0, int64(5))'
    ' + "," + found(_longs, 0, 0, 2, 0, int64(6)));\n'
    "ds_grid_destroy(_longs);\n"
    # ds_list_find_index and the other searches use the same equality.
    "var _list = ds_list_create();\n"
    "ds_list_add(_list, 3, int64(5), int64(1) << 60);\n"
    'record("list_int64", string(ds_list_find_index(_list, 5)) + string(ds_list_find_index(_list, int64(5)))'
    ' + string(ds_list_find_index(_list, int64(1) << 60)) + string(ds_list_find_index(_list, (int64(1) << 60) + 1)));\n'
    "ds_list_destroy(_list);\n"
    # add_region and multiply_region on each type of cell, for a number and for a string.
    "var _ops = ds_grid_create(4, 3);\n"
    'ds_grid_set(_ops, 0, 0, 1);\n'
    'ds_grid_set(_ops, 1, 0, 2.0);\n'
    'ds_grid_set(_ops, 2, 0, "s");\n'
    'ds_grid_set(_ops, 3, 0, 4);\n'
    "ds_grid_set_region(_ops, 0, 1, 3, 2, 0);\n"
    'ds_grid_set(_ops, 0, 1, "a");\n'
    'ds_grid_set(_ops, 1, 1, 1);\n'
    'ds_grid_set(_ops, 2, 1, 2.5);\n'
    'ds_grid_add_region(_ops, 0, 0, 3, 0, 2);\n'
    'record("add_number", row_text(_ops, 0));\n'
    'ds_grid_set(_ops, 2, 0, "s");\n'
    "ds_grid_multiply_region(_ops, 0, 0, 3, 0, 2);\n"
    'record("multiply_number", row_text(_ops, 0));\n'
    'ds_grid_add_region(_ops, 0, 1, 3, 1, "x");\n'
    'record("add_string", row_text(_ops, 1));\n'
    'ds_grid_set(_ops, 0, 2, "k");\n'
    'ds_grid_multiply_region(_ops, 0, 2, 3, 2, "x");\n'
    'record("multiply_string", row_text(_ops, 2));\n'
    # A region that does not start at the first column only changes its own cells.
    "ds_grid_set_region(_ops, 0, 0, 3, 0, 1);\n"
    "ds_grid_add_region(_ops, 1, 0, 2, 0, 10);\n"
    'record("add_partial", row_text(_ops, 0));\n'
    "ds_grid_destroy(_ops);\n"
    # ds_grid_clear fills every row, with 0 unless it is given a value.
    "var _cleared = ds_grid_create(2, 3);\n"
    "ds_grid_set_region(_cleared, 0, 0, 1, 2, 4);\n"
    "ds_grid_clear(_cleared);\n"
    'var _text = row_text(_cleared, 0) + row_text(_cleared, 1) + row_text(_cleared, 2);\n'
    'ds_grid_clear(_cleared, "q");\n'
    'record("clear", _text + "," + row_text(_cleared, 0) + row_text(_cleared, 1) + row_text(_cleared, 2));\n'
    "ds_grid_destroy(_cleared);\n"
)

_PROJECT = GameMakerProject(
    name="DsGridValueTypes",
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
    "int_cell_near_real": "T/1/1,F/-1/-1",
    "real_cell_near_int": "T/2/0,T/0/2",
    "int_cell_exact": "T/1/1,F/-1/-1",
    "row_order": "T/3/0",
    "region_start": "T/1/1,T/3/0,T/1/1",
    "huge": "T/1/0,T/2/0",
    "string_grid": "T/0/0,T/2/1,F/-1/-1",
    "string_among_numbers": "T/1/0,F/-1/-1",
    "bool_grid": "F/-1/-1,T/0/0",
    "bool_found": "T/2/0",
    "bool_number": "T/2/0,F/-1/-1",
    "object_identity": "T/1/0,T/2/0,F/-1/-1",
    "int64_cell": "T/0/0,T/0/0,F/-1/-1",
    "int64_value": "T/1/0,T/0/0,F/-1/-1",
    "list_int64": "112-1",
    "add_number": "3/4/2/6",
    "multiply_number": "6/8/s/12",
    "add_string": "ax/x/x/x",
    "multiply_string": "k/0/0/0",
    "add_partial": "1/11/11/1",
    "clear": "0/00/00/0,q/qq/qq/q",
}


class TestDsGridValueTypesGodot(unittest.TestCase):
    def test_grid_loops_give_what_the_runner_gives_for_each_type_of_cell(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
