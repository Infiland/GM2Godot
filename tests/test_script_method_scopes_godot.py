"""Godot checks that GML methods and struct literals convert to scripts Godot loads.

Each GML function or method has its own local variables (manual: Local
Variables), so methods may reuse the names of the enclosing function's locals
and parameters. A script Godot cannot parse must not stop the project's other
scripts from running.
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

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 4:
		print("METHOD_SCOPES_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


def _run_project(
    test: unittest.TestCase,
    scripts: dict[str, str],
    create_code: str,
    *,
    unloadable_script: str | None = None,
) -> tuple[list[object], str]:
    godot_binary = find_smoke_godot_binary()
    if godot_binary is None:
        test.skipTest("Godot binary not available")
    project = GameMakerProject(
        name="MethodScopes",
        scripts={"scr_trace": _TRACE_SCRIPT, **scripts},
        objects=(GameMakerObject("o_main", {EVENT_CREATE: create_code}),),
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
        if unloadable_script is not None:
            script_path = root / "godot" / "scripts" / f"{unloadable_script}.gd"
            script_path.write_text(script_path.read_text(encoding="utf-8") + "\nfunc (:\n", encoding="utf-8")
        add_probe_autoload(root / "godot", _PROBE)
        result = run_converted_project(godot_binary, root / "godot")
    output = result.stdout + result.stderr
    test.assertEqual(result.returncode, 0, output)
    trace_lines = [line for line in output.splitlines() if line.startswith("METHOD_SCOPES_TRACE ")]
    test.assertEqual(len(trace_lines), 1, output)
    return json.loads(trace_lines[0].removeprefix("METHOD_SCOPES_TRACE ")), output


class TestScriptMethodScopesGodot(unittest.TestCase):
    def test_methods_reuse_enclosing_local_and_parameter_names(self) -> None:
        scripts = {
            "scr_ok": "function ok_value() { return 7; }\n",
            "scr_font": (
                "function Font(_name) constructor {\n"
                "    name = _name;\n"
                "    var _count = 2;\n"
                "    describe = function() {\n"
                "        var _name = name + \"!\";\n"
                "        var _count = 10;\n"
                "        var _inner = function() { var _count = 100; return _count; };\n"
                "        return _name + string(_count + _inner());\n"
                "    };\n"
                "    count = _count;\n"
                "}\n"
                "\n"
                "function sum_with_method() {\n"
                "    var n = 1;\n"
                "    var f = function() {\n"
                "        var n = 2;\n"
                "        for (var _i = 0; _i < 3; _i += 1) { n += 1; }\n"
                "        return n;\n"
                "    };\n"
                "    return f() + n;\n"
                "}\n"
            ),
        }
        create_code = (
            'trace("ok:" + string(ok_value()));\n'
            'var _font = new Font("mono");\n'
            'trace("method:" + _font.describe() + ":" + string(_font.count));\n'
            'trace("sum:" + string(sum_with_method()));\n'
        )

        trace, output = _run_project(self, scripts, create_code)

        self.assertNotIn("Parse Error", output)
        self.assertEqual(trace, ["ok:7", "method:mono!110:2", "sum:6"])

    def test_increments_inside_methods_run_when_the_method_runs(self) -> None:
        scripts = {
            "scr_counter": (
                "function count_up(_limit) {\n"
                "    var _step = function(_to) {\n"
                "        var _n = 0;\n"
                "        for (var _i = 0; _i < _to; _i++) { _n++; }\n"
                "        var _before = _n--;\n"
                "        return string(_before) + \":\" + string(++_n);\n"
                "    };\n"
                "    return _step(_limit) + \"/\" + _step(_limit + 1);\n"
                "}\n"
            ),
        }
        create_code = 'trace("count:" + count_up(2));\n'

        trace, output = _run_project(self, scripts, create_code)

        self.assertNotIn("Parse Error", output)
        self.assertEqual(trace, ["count:2:2/3:3"])

    def test_struct_literals_may_repeat_a_variable_name(self) -> None:
        scripts = {
            "scr_colours": (
                "function colours() {\n"
                "    global.order = \"\";\n"
                "    return {\n"
                "        c_red: mark(\"r\", 1),\n"
                "        c_gray: mark(\"g\", 2),\n"
                "        c_blue: mark(\"b\", 3),\n"
                "        c_gray: mark(\"G\", 4),\n"
                "    };\n"
                "}\n"
                "\n"
                "function mark(_label, _value) {\n"
                "    global.order += _label;\n"
                "    return _value;\n"
                "}\n"
            ),
        }
        create_code = (
            "var _colours = colours();\n"
            'trace("gray:" + string(_colours.c_gray) + ":" + global.order + ":"'
            " + string(variable_struct_names_count(_colours)));\n"
        )

        trace, output = _run_project(self, scripts, create_code)

        self.assertNotIn("Parse Error", output)
        self.assertEqual(trace, ["gray:4:rgbG:3"])

    def test_a_script_godot_cannot_load_leaves_the_other_scripts_working(self) -> None:
        scripts = {
            "scr_ok": "function ok_value() { return 7; }\n",
            "scr_broken": "function broken_value() { return 1; }\n",
            "scr_thing": (
                "function Thing(_size) constructor {\n"
                "    size = _size * 2;\n"
                "}\n"
                "global.Counted = function() constructor {};\n"
            ),
        }
        create_code = (
            'trace("ok:" + string(ok_value()));\n'
            'trace("thing:" + string(new Thing(3).size) + ":" + string(is_method(global.Counted)));\n'
        )

        trace, output = _run_project(self, scripts, create_code, unloadable_script="scr_broken")

        self.assertIn('Failed to load script "res://scripts/scr_broken.gd"', output)
        self.assertNotIn('Failed to load script "res://gm2godot/gml_script_registry.gd"', output)
        self.assertEqual(trace, ["ok:7", "thing:6:true"])


if __name__ == "__main__":
    unittest.main()
