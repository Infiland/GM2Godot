"""point_in_rectangle and array_set give the HTML5 runner's results in Godot.

point_in_rectangle (functions/Function_Collision.js) includes the edges of the
rectangle. array_set (yyVariable.js) is array[index] = value and returns
undefined; a value that is not an array is left alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text
from tests.test_string_functions_godot import run_string_probe

_POINT_CASES: tuple[tuple[str, object], ...] = (
    ("point_in_rectangle(5, 5, 0, 0, 10, 10)", True),
    ("point_in_rectangle(0, 0, 0, 0, 10, 10)", True),
    ("point_in_rectangle(10, 10, 0, 0, 10, 10)", True),
    ("point_in_rectangle(10.5, 5, 0, 0, 10, 10)", False),
    ("point_in_rectangle(5, -0.25, 0, 0, 10, 10)", False),
    # The corners are not sorted.
    ("point_in_rectangle(5, 5, 10, 10, 0, 0)", False),
    ("point_in_rectangle(904, 740, 904, 720, 984, 760)", True),
)

_ARRAY_SET_CODE = """\
var _a = [1, 2, 3];
var _result = array_set(_a, 1, "two");
var _b = _a;
array_set(_b, 0, 10);
var _c = 7;
array_set(_c, 0, 1);
global.results = [_a, is_undefined(_result), _c];
"""
_RESULT_PREFIX = "ARRAY_SET_RESULT "


class TestPointAndArrayFunctionsGodot(unittest.TestCase):
    def test_point_in_rectangle_includes_the_edges(self) -> None:
        actual = run_string_probe(self, _POINT_CASES)
        for (expression, expected), value in zip(_POINT_CASES, actual, strict=True):
            with self.subTest(expression=expression):
                self.assertEqual(value, expected)

    def test_array_set_assigns_through_the_array_reference(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        script = (
            "extends Node\n\n"
            'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
            "var other = null\n\n\n"
            "func _ready():\n"
            f"{transpile_gml_code(_ARRAY_SET_CODE, indent=chr(9))}\n"
            f"\tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify(GMRuntime.gml_global_scope().get(\"results\")))\n"
            "\tget_tree().quit(0)\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_fixture_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="ArraySet"\nrun/main_scene="res://probe.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            write_fixture_text(project_dir / "probe.gd", script)
            write_fixture_text(
                project_dir / "probe.tscn",
                '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://probe.gd" id="1"]\n\n'
                '[node name="Probe" type="Node"]\nscript = ExtResource("1")\n',
            )
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "--quit-after", "60"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=dict(os.environ, HOME=str(project_dir)),
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        lines = [line for line in output.splitlines() if line.startswith(_RESULT_PREFIX)]
        self.assertEqual(len(lines), 1, output)
        self.assertEqual(json.loads(lines[0].removeprefix(_RESULT_PREFIX)), [[10, "two", 3], True, 7])


if __name__ == "__main__":
    unittest.main()
