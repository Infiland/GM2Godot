"""Godot checks that GML written without semicolons converts and runs.

GameMaker needs no semicolons and treats line breaks as white space: a
statement ends before the first token that cannot continue it, and an if
condition needs no parentheses (manual: If Else and Conditional Operators).
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

_SCRIPTS = {
    "scr_trace": (
        "function trace(_text) {\n"
        '    if !variable_global_exists("trace") global.trace = []\n'
        "    array_push(global.trace, _text)\n"
        "}\n"
    ),
    "scr_loc": (
        "function loc(_key) {\n"
        "    if !is_string(_key) return \"?\";\n"
        "    var _text = string_upper(_key) _text += \"!\"\n"
        "    return _text\n"
        "}\n"
    ),
    "scr_keys": (
        "function key_for(_code) {\n"
        "    var _key = -1\n"
        "    switch (_code) {\n"
        '        case("40"): _key = vk_down break;\n'
        "        case 38: _key = vk_up break\n"
        "        default: _key = 0 break\n"
        "    }\n"
        "    return _key\n"
        "}\n"
    ),
}

_CREATE = (
    'trace(loc("loading"))\n'
    'trace(loc(5)) trace(string(key_for("40") == vk_down) + string(key_for(38) == vk_up) + string(key_for(1)))\n'
    "var _total = 1 +\n"
    "    2\n"
    "    * 3\n"
    "if _total == 7 trace(\"total:\" + string(_total)) else trace(\"wrong\")\n"
    "var _step = function(_n) {\n"
    "    var _out = _n\n"
    "    _out += 1\n"
    "    return _out\n"
    "}\n"
    "if _step(1) == 2 then trace(\"method\")\n"
    "with self trace(\"with\")\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 4:
		print("SEMICOLON_FREE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestSemicolonFreeGmlGodot(unittest.TestCase):
    def test_statements_without_semicolons_or_condition_parentheses_run(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        project = GameMakerProject(
            name="SemicolonFree",
            scripts=_SCRIPTS,
            objects=(GameMakerObject("o_main", {EVENT_CREATE: _CREATE}),),
            rooms=(
                GameMakerRoom(
                    "r_main",
                    layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_main", "o_main", 0, 0),)),),
                    creation_order=("inst_main",),
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            logs = convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
        output = result.stdout + result.stderr

        self.assertEqual([line for line in logs if "Could not" in line], [])
        self.assertEqual(result.returncode, 0, output)
        trace_lines = [line for line in output.splitlines() if line.startswith("SEMICOLON_FREE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(
            json.loads(trace_lines[0].removeprefix("SEMICOLON_FREE_TRACE ")),
            ["LOADING!", "?", "truetrue0", "total:7", "method", "with"],
        )


if __name__ == "__main__":
    unittest.main()
