"""Godot checks for GameMaker value semantics: division, comparisons, rounding."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    run_headless_scene,
    write_fixture_text as _write_text,
)

_SMOKE_SCENE = textwrap.dedent(
    """\
    [gd_scene load_steps=2 format=3]

    [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

    [node name="Smoke" type="Node2D"]
    script = ExtResource("smoke_script")
    """
)

_SMOKE_PRELUDE = textwrap.dedent(
    """\
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    var _failures = []

    func _same(actual, expected):
    \tif typeof(expected) == TYPE_FLOAT and is_nan(expected):
    \t\treturn typeof(actual) == TYPE_FLOAT and is_nan(actual)
    \tif typeof(expected) == TYPE_BOOL or typeof(actual) == TYPE_BOOL:
    \t\treturn typeof(actual) == typeof(expected) and actual == expected
    \tif typeof(expected) in [TYPE_INT, TYPE_FLOAT] and typeof(actual) in [TYPE_INT, TYPE_FLOAT]:
    \t\tif is_inf(float(expected)) or is_inf(float(actual)):
    \t\t\treturn float(actual) == float(expected)
    \t\treturn abs(float(actual) - float(expected)) <= 0.0000001
    \treturn typeof(actual) == typeof(expected) and actual == expected

    func _expect(label, actual, expected):
    \tif not _same(actual, expected):
    \t\t_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])

    func _ready():
    \tcall_deferred("_run")

    func _finish(marker):
    \tif _failures.is_empty():
    \t\tprint(marker)
    \t\tget_tree().quit(0)
    \t\treturn
    \tfor failure in _failures:
    \t\tprint("FAIL " + failure)
    \tget_tree().quit(1)

    """
)


def _run_runtime_checks(test: unittest.TestCase, body: str, marker: str) -> None:
    godot_binary = _find_godot_binary()
    if godot_binary is None:
        test.skipTest("Godot binary not available")
    script = _SMOKE_PRELUDE + "func _run():\n" + textwrap.indent(textwrap.dedent(body), "\t")
    script += f'\t_finish("{marker}")\n'
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_text(project_dir / "project.godot", "[application]\n")
        write_gml_runtime(str(project_dir))
        _write_text(project_dir / "smoke.gd", script)
        _write_text(project_dir / "smoke.tscn", _SMOKE_SCENE)
        result = run_headless_scene(godot_binary, project_dir, "smoke.tscn", timeout=60)
    test.assertEqual(result.returncode, 0, result.stdout)
    test.assertIn(marker, result.stdout)
    test.assertNotIn("SCRIPT ERROR", result.stdout)


class TestGMLValueSemanticsGodot(unittest.TestCase):
    def test_division_is_real_division_for_whole_numbers(self) -> None:
        _run_runtime_checks(
            self,
            """\
            _expect("5 / 2", GMRuntime.gml_div(5, 2), 2.5)
            _expect("1 / 3", GMRuntime.gml_div(1, 3), 1.0 / 3.0)
            _expect("-7 / 2", GMRuntime.gml_div(-7, 2), -3.5)
            _expect("6 / 3", GMRuntime.gml_div(6, 3), 2.0)
            _expect("1 / 0", GMRuntime.gml_div(1, 0), INF)
            _expect("-1 / 0", GMRuntime.gml_div(-1, 0), -INF)
            _expect("0 / 0", GMRuntime.gml_div(0, 0), NAN)
            var counter = 7
            counter = GMRuntime.gml_div(counter, 2)
            _expect("counter /= 2", counter, 3.5)
            _expect("deaths / 30", GMRuntime.gml_div(45, 30), 1.5)
            _expect("int64 / int64", GMRuntime.gml_div(GMRuntime.gml_int64(5), GMRuntime.gml_int64(2)).value, 2)
            _expect("5 div 2", GMRuntime.gml_int_div(5, 2), 2)
            _expect("-5 div 2", GMRuntime.gml_int_div(-5, 2), -2)
            _expect("5.5 mod 2", GMRuntime.gml_mod(5.5, 2), 1.5)
            _expect("-5 mod 3", GMRuntime.gml_mod(-5, 3), -2)
            """,
            "GML_DIVISION_OK",
        )

    def test_comparisons_use_gamemaker_epsilon(self) -> None:
        _run_runtime_checks(
            self,
            """\
            var accumulated = 0
            for i in 20:
            \taccumulated = GMRuntime.gml_add(accumulated, 0.1)
            _expect("accumulated != 2.0 exactly", accumulated == 2.0, false)
            _expect("accumulated = 2", GMRuntime.gml_eq(accumulated, 2), true)
            _expect("accumulated != 2", GMRuntime.gml_ne(accumulated, 2), false)
            _expect("accumulated < 2", GMRuntime.gml_lt(accumulated, 2), false)
            _expect("accumulated <= 2", GMRuntime.gml_lte(accumulated, 2), true)
            _expect("accumulated > 2", GMRuntime.gml_gt(accumulated, 2), false)
            _expect("accumulated >= 2", GMRuntime.gml_gte(accumulated, 2), true)
            var alpha = 0
            for i in 10:
            \talpha = GMRuntime.gml_add(alpha, 0.1)
            _expect("alpha >= 1", GMRuntime.gml_gte(alpha, 1), true)
            _expect("1.000001 = 1", GMRuntime.gml_eq(1.000001, 1), true)
            _expect("1.0001 = 1", GMRuntime.gml_eq(1.0001, 1), false)
            _expect("1.0001 > 1", GMRuntime.gml_gt(1.0001, 1), true)
            _expect("0.99999 < 1", GMRuntime.gml_lt(0.999999, 1), false)
            _expect("true = 1.000001", GMRuntime.gml_eq(true, 1.000001), true)
            _expect("default epsilon", GMRuntime.gml_math_get_epsilon(), 0.00001)
            GMRuntime.gml_math_set_epsilon(0.01)
            _expect("custom epsilon", GMRuntime.gml_math_get_epsilon(), 0.01)
            _expect("1.005 = 1 with 0.01", GMRuntime.gml_eq(1.005, 1), true)
            _expect("1.005 > 1 with 0.01", GMRuntime.gml_gt(1.005, 1), false)
            GMRuntime.gml_math_set_epsilon(5)
            _expect("epsilon >= 1 ignored", GMRuntime.gml_math_get_epsilon(), 0.01)
            GMRuntime.gml_math_set_epsilon(-1)
            _expect("negative epsilon ignored", GMRuntime.gml_math_get_epsilon(), 0.01)
            GMRuntime.gml_math_set_epsilon(0)
            _expect("zero epsilon clamps", GMRuntime.gml_math_get_epsilon(), 0.00000000001)
            _expect("1.000001 != 1 with tiny epsilon", GMRuntime.gml_eq(1.000001, 1), false)
            GMRuntime.gml_math_set_epsilon(0.00001)
            _expect("NaN = NaN", GMRuntime.gml_eq(NAN, NAN), false)
            _expect("NaN != NaN", GMRuntime.gml_ne(NAN, NAN), true)
            _expect("NaN < 1", GMRuntime.gml_lt(NAN, 1), false)
            _expect("NaN >= 1", GMRuntime.gml_gte(NAN, 1), false)
            _expect("inf = inf", GMRuntime.gml_eq(INF, INF), true)
            _expect("inf > -inf", GMRuntime.gml_gt(INF, -INF), true)
            _expect("inf = -inf", GMRuntime.gml_eq(INF, -INF), false)
            _expect("string = number", GMRuntime.gml_eq("1", 1), false)
            _expect("NaN = string", GMRuntime.gml_eq(NAN, "abc"), false)
            _expect("string = string", GMRuntime.gml_eq("abc", "abc"), true)
            _expect("string < string", GMRuntime.gml_lt("abc", "abd"), true)
            var big = GMRuntime.gml_int64(9007199254740993)
            var big_next = GMRuntime.gml_int64(9007199254740992)
            _expect("int64 values compare exactly", GMRuntime.gml_eq(big, big_next), false)
            _expect("int64 ordering", GMRuntime.gml_gt(big, big_next), true)
            """,
            "GML_EPSILON_OK",
        )

    def test_round_uses_bankers_rounding(self) -> None:
        _run_runtime_checks(
            self,
            """\
            _expect("round(0.5)", GMRuntime.gml_round(0.5), 0)
            _expect("round(1.5)", GMRuntime.gml_round(1.5), 2)
            _expect("round(2.5)", GMRuntime.gml_round(2.5), 2)
            _expect("round(3.5)", GMRuntime.gml_round(3.5), 4)
            _expect("round(23.5)", GMRuntime.gml_round(23.5), 24)
            _expect("round(24.5)", GMRuntime.gml_round(24.5), 24)
            _expect("round(-0.5)", GMRuntime.gml_round(-0.5), 0)
            _expect("round(-2.5)", GMRuntime.gml_round(-2.5), -2)
            _expect("round(-3.5)", GMRuntime.gml_round(-3.5), -4)
            _expect("round(-23.5)", GMRuntime.gml_round(-23.5), -24)
            _expect("round(2.4)", GMRuntime.gml_round(2.4), 2)
            _expect("round(2.6)", GMRuntime.gml_round(2.6), 3)
            _expect("round(-2.6)", GMRuntime.gml_round(-2.6), -3)
            _expect("round(7)", GMRuntime.gml_round(7), 7)
            _expect("round(inf)", GMRuntime.gml_round(INF), INF)
            """,
            "GML_ROUND_OK",
        )


if __name__ == "__main__":
    unittest.main()
