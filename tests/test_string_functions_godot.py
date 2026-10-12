"""GameMaker's string functions give the runner's values in a converted game.

Each case is a GML expression and the value the HTML5 runner
(functions/Function_String.js) gives for it. The test transpiles every
expression, runs it through the generated runtime in Godot and compares.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import unittest
from fractions import Fraction
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



def _js_to_fixed(value: float, places: int) -> str:
    """JavaScript Number.prototype.toFixed (ECMA-262 Number.prototype.toFixed)."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if abs(value) >= 1e21:
        return repr(value)  # Python's repr spells these as JavaScript does.
    sign = "-" if value < 0 else ""
    scaled = Fraction(abs(value)) * 10**places  # The double's exact value.
    whole = math.floor(scaled)
    if scaled - whole >= Fraction(1, 2):  # A tie takes the larger n.
        whole += 1
    digits = str(whole)
    if places == 0:
        return sign + digits
    digits = digits.rjust(places + 1, "0")
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def _string_format(value: float, total: int, places: int) -> str:
    """Function_String.js string_format."""
    parts = _js_to_fixed(value, places).split(".")
    text = parts[0].rjust(total, " ")
    if len(parts) > 1:
        text += "." + parts[1].ljust(places, "0")
    return text


# (GML value expression, its double) for string_format.
_FORMAT_VALUES: tuple[tuple[str, float], ...] = (
    ("1234", 1234.0),
    ("pi", math.pi),
    ("420.578", 420.578),
    ("0.125", 0.125),
    ("2.5", 2.5),
    ("-2.5", -2.5),
    ("1.005", 1.005),
    ("0.1", 0.1),
    ("-0.001", -0.001),
    ("-0.0", -0.0),
    ("0", 0.0),
    ("123456789 + 0.987654321", 123456789 + 0.987654321),
    ("4503599627370495 + 0.5", 4503599627370495.5),
    ("10000000000.0 * 100000000000.0", 1e21),
    ("-15000000000.0 * 100000000000.0", -1.5e21),
    ("power(2, -1074)", 5e-324),
)
_FORMAT_LAYOUTS = ((8, 0), (1, 10), (5, 5), (0, 2), (3, 1), (-4, 3), (12, 20), (1, 100))
_FORMAT_CASES: tuple[tuple[str, object], ...] = (
    *(
        (f"string_format({expression}, {total}, {places})", _string_format(value, total, places))
        for expression, value in _FORMAT_VALUES
        for total, places in _FORMAT_LAYOUTS
    ),
    ("string_format(12.5, 6.9, 1.9)", _string_format(12.5, 6, 1)),
    ("string_format(true, 3, 2)", _string_format(1.0, 3, 2)),
    ("string_format(undefined, 3, 2)", "undefined"),
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

    def test_string_format_matches_the_runner(self) -> None:
        # The manual's examples, among the cases.
        self.assertEqual(_string_format(1234, 8, 0), "    1234")
        self.assertEqual(_string_format(math.pi, 1, 10), "3.1415926536")
        self.assertEqual(_string_format(math.pi, 5, 5), "    3.14159")
        actual = run_string_probe(self, _FORMAT_CASES)
        for (expression, expected), value in zip(_FORMAT_CASES, actual, strict=True):
            with self.subTest(expression=expression):
                self.assertEqual(value, expected)


if __name__ == "__main__":
    unittest.main()
