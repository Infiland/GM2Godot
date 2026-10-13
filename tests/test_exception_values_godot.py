"""Godot checks of the value a catch block receives.

GameMaker's runner passes a value given to throw through to catch unchanged;
only a runtime error becomes a struct with message, longMessage, script and
stacktrace (Function_Debug.js, __yy__processException: only an Error object is
converted, anything else is returned as it is).
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

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 4:
		var trace = GMRuntime.gml_global_scope().get("trace", [])
		var runtime_error = GMRuntime.gml_exception_struct("boom")
		trace.append("runtime error:" + JSON.stringify([
			runtime_error.get("message"),
			runtime_error.get("longMessage"),
			runtime_error.get("script"),
			runtime_error.get("stacktrace"),
		]))
		print("EXCEPTION_VALUES_TRACE " + JSON.stringify(trace))
		get_tree().quit(0)
"""

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

_CREATE_CODE = """
try { throw 5; } catch (_e) {
    trace("number:" + (is_real(_e) ? "yes" : "no") + ":" + string(_e));
}
try { throw "text"; } catch (_e) {
    trace("string:" + (is_string(_e) ? "yes" : "no") + ":" + _e);
}
var _thrown = { code: 7 };
try { throw _thrown; } catch (_e) {
    trace("struct:" + (is_struct(_e) ? "yes" : "no") + ":" + ((_e == _thrown) ? "same" : "other") + ":" + string(_e.code));
}
try { throw [1, 2]; } catch (_e) {
    trace("array:" + (is_array(_e) ? "yes" : "no") + ":" + string(array_length(_e)));
}
try { throw undefined; } catch (_e) {
    trace("undefined:" + (is_undefined(_e) ? "yes" : "no"));
}
try { throw true; } catch (_e) {
    trace("bool:" + (is_bool(_e) ? "yes" : "no") + ":" + (_e ? "true" : "false"));
}
try {
    try { throw 9; } catch (_inner) { throw _inner + 1; }
} catch (_outer) {
    trace("rethrown:" + string(_outer));
}
try { throw 3; } catch (_e) { trace("shape:" + (is_struct(_e) ? "struct" : "plain")); }
"""


class TestExceptionValuesGodot(unittest.TestCase):
    def test_catch_receives_the_value_that_was_thrown(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        project = GameMakerProject(
            name="ExceptionValues",
            scripts={"scr_trace": _TRACE_SCRIPT},
            objects=(GameMakerObject("o_main", {EVENT_CREATE: _CREATE_CODE}),),
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
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        trace_lines = [line for line in output.splitlines() if line.startswith("EXCEPTION_VALUES_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        trace = json.loads(trace_lines[0].removeprefix("EXCEPTION_VALUES_TRACE "))

        self.assertNotIn("Parse Error", output)
        self.assertEqual(
            trace,
            [
                "number:yes:5",
                "string:yes:text",
                "struct:yes:same:7",
                "array:yes:2",
                "undefined:yes",
                "bool:yes:true",
                "rethrown:10",
                "shape:plain",
                'runtime error:["boom","boom","",[]]',
            ],
        )


if __name__ == "__main__":
    unittest.main()
