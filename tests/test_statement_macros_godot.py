"""Godot checks that macros used as statements run their statements.

A GameMaker macro is text substitution done before compiling (manual: GML
Overview > Variables > Constants, Macros). Its value may be several
statements joined with line continuations, and the macro may then be used on
its own as a statement, in the script that defines it or in any other.
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
        '    if (!variable_global_exists("trace")) global.trace = [];\n'
        "    array_push(global.trace, _text);\n"
        "}\n"
    ),
    "scr_macros": (
        "#macro READ_WORD var _word = string_upper(_name);\\\n"
        "    if (_word == \"SKIP\") return \"skipped\";\\\n"
        "    _count += 1;\n"
        "#macro TRACE_COUNT trace(\"count:\" + string(_count))\n"
        "#macro BUMP ++global.bumps;\n"
    ),
    "scr_parse": (
        "function parse(_name) {\n"
        "    var _count = 0;\n"
        "    switch (_name) {\n"
        "        case \"one\": READ_WORD; break;\n"
        "        case \"two\": READ_WORD READ_WORD break;\n"
        "        default: READ_WORD\n"
        "    }\n"
        "    TRACE_COUNT;\n"
        "    return _word;\n"
        "}\n"
    ),
}

_CREATE = (
    "global.bumps = 0;\n"
    'trace(parse("one"));\n'
    'trace(parse("two"));\n'
    'trace(parse("skip"));\n'
    'trace(parse("other"));\n'
    "BUMP BUMP;\n"
    'trace("bumps:" + string(global.bumps));\n'
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 4:
		print("STATEMENT_MACROS_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestStatementMacrosGodot(unittest.TestCase):
    def test_macros_holding_statements_run_where_they_are_used(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        project = GameMakerProject(
            name="StatementMacros",
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
        trace_lines = [line for line in output.splitlines() if line.startswith("STATEMENT_MACROS_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(
            json.loads(trace_lines[0].removeprefix("STATEMENT_MACROS_TRACE ")),
            ["count:1", "ONE", "count:2", "TWO", "skipped", "count:1", "OTHER", "bumps:2"],
        )


if __name__ == "__main__":
    unittest.main()
