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
    "function no_return(_a) { var _q = _a + 1; }\n"
    "function bare_return(_a) { if (_a) return; return 5; }\n"
    "function exit_early(_a) { if (_a) exit; return 5; }\n"
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

# A GML value is never a raw null: GameMaker's arrays, grids, lists and
# functions give 0 or undefined where the converted GDScript left null, and
# adding to such a null fails ("GML add does not support values of type ...").
# Every probe below is therefore an addition or a type test.
_CREATE = (
    # array_create fills with 0 unless it is given a value (the manual, and
    # the runner's array_create), and an explicit undefined is a value.
    "var _created = array_create(3);\n"
    'record("array_create", string(_created[0] + 1) + flag(is_real(_created[2])));\n'
    "var _undefined_fill = array_create(2, undefined);\n"
    'record("array_create_undefined", flag(is_undefined(_undefined_fill[1])));\n'
    'record("array_create_value", string(array_create(2, "x")[1]));\n'
    # A write past the end fills the gap with 0.
    "var _gap = [];\n"
    "_gap[3] = 1;\n"
    'record("array_gap", string(_gap[0]) + string(_gap[2] + 1) + string(_gap[3]) + string(array_length(_gap)));\n'
    "array_resize(_gap, 6);\n"
    'record("array_resize", string(_gap[5] + 1) + flag(is_real(_gap[4])) + string(array_length(_gap)));\n'
    "var _copied = [];\n"
    "array_copy(_copied, 2, [7], 0, 1);\n"
    'record("array_copy", string(_copied[0] + 1) + string(_copied[1]) + string(_copied[2]));\n'
    # The runner's array_copy works out how much of the source there is first
    # and copies from the last element to the first, so an array copied
    # onto itself moves right as a whole; array_resize and array_copy zero
    # the gap however long it is.
    "var _shift = [1, 2, 3];\n"
    "array_copy(_shift, 1, _shift, 0, 3);\n"
    'record("array_copy_self", string(_shift[0]) + string(_shift[1]) + string(_shift[2]) + string(_shift[3])'
    " + string(array_length(_shift)));\n"
    "var _wide = [1];\n"
    "array_copy(_wide, 1, [5, 6, 7], 0, 9);\n"
    'record("array_copy_grow", string(_wide[0]) + string(_wide[1]) + string(_wide[2]) + string(_wide[3])'
    " + string(array_length(_wide)));\n"
    "var _far = [];\n"
    "array_copy(_far, 30, [1, 2, 3], 0, 3);\n"
    'record("array_copy_far", string(_far[29] + 1) + string(_far[30]) + string(_far[32]) + string(array_length(_far)));\n'
    "var _long = [3];\n"
    "array_resize(_long, 40);\n"
    'record("array_resize_long", string(_long[0]) + string(_long[39] + 1) + flag(is_real(_long[20]))'
    " + string(array_length(_long)));\n"
    # array_insert past the end fills the gap with 0 and inserts there.
    "var _inserted = [1, 2];\n"
    "array_insert(_inserted, 5, 9);\n"
    'record("array_insert_far", string(_inserted[2] + 1) + string(_inserted[4] + 1) + string(_inserted[5])'
    " + string(array_length(_inserted)));\n"
    # array_push and struct_foreach give no value.
    "var _pushed = [1];\n"
    'record("array_push", flag(is_undefined(array_push(_pushed, 2))) + string(array_length(_pushed)));\n'
    'record("struct_foreach", flag(is_undefined(struct_foreach({ a: 1 }, function(_name, _value) {}))));\n'
    # Fresh and gained ds_grid cells hold 0, and resizing keeps the old ones.
    "var _grid = ds_grid_create(2, 2);\n"
    "ds_grid_set(_grid, 1, 1, 5);\n"
    'record("grid_create", string(ds_grid_get(_grid, 0, 0) + 1) + flag(is_real(_grid[# 1, 0])));\n'
    "ds_grid_resize(_grid, 3, 3);\n"
    'record("grid_resize", string(_grid[# 1, 1]) + string(_grid[# 2, 2] + 1)'
    " + flag(is_real(_grid[# 2, 0])) + flag(is_real(_grid[# 0, 2])));\n"
    "ds_grid_destroy(_grid);\n"
    # ds_list_set past the end fills with 0 as well.
    "var _list = ds_list_create();\n"
    "ds_list_set(_list, 2, 9);\n"
    'record("list_set", string(ds_list_find_value(_list, 0) + 1) + string(ds_list_find_value(_list, 2))'
    " + string(ds_list_size(_list)));\n"
    "ds_list_destroy(_list);\n"
    # A function that gives no value gives undefined.
    "var _anonymous = function() { var _w = 3; };\n"
    "var _bare = function() { return; };\n"
    "var _holder = { run: function() { var _w = 3; } };\n"
    'record("no_return", flag(is_undefined(no_return(1))) + flag(is_undefined(bare_return(true)))'
    " + flag(is_undefined(exit_early(true))) + flag(is_undefined(_anonymous()))"
    " + flag(is_undefined(_bare())) + flag(is_undefined(_holder.run()))"
    " + flag(is_undefined(method(self, _anonymous)()))"
    " + flag(is_undefined(script_execute(no_return, 1))));\n"
    'record("return_values", string(bare_return(false)) + string(exit_early(false)));\n'
    # json_parse makes every JSON null undefined.
    'record("json_null", flag(is_undefined(json_parse("null"))));\n'
    "var _parsed = json_parse(\"[1, null, {\\\"a\\\": null, \\\"b\\\": 2}]\");\n"
    'record("json_nested", flag(is_undefined(_parsed[1])) + flag(is_undefined(_parsed[2].a))'
    ' + string(_parsed[2].b) + flag(variable_struct_exists(_parsed[2], "a")));\n'
    # Text that mentions null inside a string is still walked and keeps its words;
    # text without a null is returned as decoded.
    'var _worded = json_parse("{\\"note\\": \\"nullable\\", \\"gap\\": null, \\"list\\": [null, \\"null\\", 3]}");\n'
    'record("json_null_word", string(_worded.note) + flag(is_undefined(_worded.gap)) + flag(is_undefined(_worded.list[0]))'
    " + string(_worded.list[1]) + string(_worded.list[2]));\n"
    'var _plain = json_parse("{\\"a\\": [1, {\\"b\\": 2}], \\"c\\": \\"x\\"}");\n'
    'record("json_plain", string(_plain.a[0]) + string(_plain.a[1].b) + _plain.c);\n'
)

_PROJECT = GameMakerProject(
    name="GmlNullValues",
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
    "array_create": "1T",
    "array_create_undefined": "T",
    "array_create_value": "x",
    "array_gap": "0114",
    "array_resize": "1T6",
    "array_copy": "107",
    "array_copy_self": "11234",
    "array_copy_grow": "15674",
    "array_copy_far": "11333",
    "array_resize_long": "31T40",
    "array_insert_far": "1196",
    "array_push": "T2",
    "struct_foreach": "T",
    "grid_create": "1T",
    "grid_resize": "51TT",
    "list_set": "193",
    "no_return": "TTTTTTTT",
    "return_values": "55",
    "json_null": "T",
    "json_nested": "TT2T",
    "json_null_word": "nullableTTnull3",
    "json_plain": "12x",
}


class TestGmlNullValuesGodot(unittest.TestCase):
    def test_json_parse_walks_only_text_that_contains_null(self) -> None:
        # A decoded null needs "null" in the text, so a document without it is
        # not walked (the runner counts the nulls its reviver sees for the same
        # reason).
        start = GML_RUNTIME_SCRIPT.index("static func gml_json_parse(")
        body = GML_RUNTIME_SCRIPT[start : GML_RUNTIME_SCRIPT.index("\nstatic func", start)]
        self.assertIn('if not str(text).contains("null"):', body)
        self.assertLess(body.index('contains("null")'), body.index("_gml_json_nulls_to_undefined(decoded)"))

    def test_gml_values_are_never_a_raw_null(self) -> None:
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
        # Not "ERROR:" alone: a struct holding a method bound to itself is a
        # reference cycle Godot reports as leaked when the run quits.
        for failure in ("GML runtime error", "SCRIPT ERROR", "Parse Error"):
            self.assertNotIn(failure, output)
        record_lines = [line for line in output.splitlines() if line.startswith("RECORD ")]
        self.assertEqual(len(record_lines), 1, output)
        record = json.loads(record_lines[0].removeprefix("RECORD "))
        self.assertEqual(record, _EXPECTED, output)


if __name__ == "__main__":
    unittest.main()
