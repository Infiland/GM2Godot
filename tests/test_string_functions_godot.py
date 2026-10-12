"""GameMaker's string functions give the runner's values in a converted game.

Each case is a GML expression and the value the HTML5 runner
(functions/Function_String.js) gives for it. The test transpiles every
expression, runs it through the generated runtime in Godot and compares.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_RESULT_PREFIX = "STRING_RESULT "

# string_join(delimiter, value1, ...) runs string() on each value.
_JOIN_CASES: tuple[tuple[str, object], ...] = (
    ('string_join("... ", "Ready", "Set", "Go!")', "Ready... Set... Go!"),
    ('string_join(", ", 1, 2.5, "x")', "1, 2.50, x"),
    ('string_join("-", "only")', "only"),
    ('string_join(0, "a", "b")', "a0b"),
    ('string_join("")', ""),
)


def run_string_probe(test: unittest.TestCase, cases: tuple[tuple[str, object], ...]) -> list[object]:
    """Run each GML expression in Godot and return the values it gives."""
    godot_binary = find_smoke_godot_binary()
    if godot_binary is None:
        test.skipTest("Godot binary not available")
    values = "".join(f"\t\t{transpile_gml_expression(expression)},\n" for expression, _ in cases)
    script = (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var other = null\n\n\n"
        "func _ready():\n"
        f"\tvar results = [\n{values}\t]\n"
        f"\tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify(results))\n"
        "\tget_tree().quit(0)\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        write_fixture_text(
            project_dir / "project.godot",
            '[application]\nconfig/name="StringFunctions"\nrun/main_scene="res://probe.tscn"\n',
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
    test.assertEqual(result.returncode, 0, output)
    test.assertNotIn("SCRIPT ERROR", output)
    test.assertNotIn("GML runtime error", output)
    lines = [line for line in output.splitlines() if line.startswith(_RESULT_PREFIX)]
    test.assertEqual(len(lines), 1, output)
    actual = json.loads(lines[0].removeprefix(_RESULT_PREFIX))
    test.assertEqual(len(actual), len(cases))
    return actual


class TestStringFunctionsGodot(unittest.TestCase):
    def test_string_join_joins_the_values_after_the_delimiter(self) -> None:
        actual = run_string_probe(self, _JOIN_CASES)
        for (expression, expected), value in zip(_JOIN_CASES, actual, strict=True):
            with self.subTest(expression=expression):
                self.assertEqual(value, expected)


if __name__ == "__main__":
    unittest.main()
