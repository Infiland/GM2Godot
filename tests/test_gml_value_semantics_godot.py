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

    def test_sqrt_counts_values_within_epsilon_below_zero_as_zero(self) -> None:
        _run_runtime_checks(
            self,
            """\
            _expect("sqrt(16)", GMRuntime.gml_sqrt(16), 4.0)
            _expect("sqrt(0)", GMRuntime.gml_sqrt(0), 0.0)
            _expect("sqrt(-0.000001)", GMRuntime.gml_sqrt(-0.000001), 0.0)
            _expect("sqrt(-epsilon)", GMRuntime.gml_sqrt(-0.00001), 0.0)
            _expect("sqrt(-0.0001)", GMRuntime.gml_sqrt(-0.0001), NAN)
            _expect("sqrt(-1)", GMRuntime.gml_sqrt(-1), NAN)
            GMRuntime.gml_math_set_epsilon(0.001)
            _expect("sqrt(-0.0005) with 0.001", GMRuntime.gml_sqrt(-0.0005), 0.0)
            _expect("sqrt(-0.002) with 0.001", GMRuntime.gml_sqrt(-0.002), NAN)
            GMRuntime.gml_math_set_epsilon(0.00001)
            """,
            "GML_SQRT_OK",
        )

    def test_point_direction_follows_the_runner(self) -> None:
        # The runner rounds point_direction to six decimals (computed with its
        # value of pi), so vectors on the diagonals give whole angles and
        # floor(point_direction(...) / 45) picks the expected octant.
        _run_runtime_checks(
            self,
            """\
            _expect("3,4 rounded to six decimals", absf(GMRuntime.gml_point_direction(0, 0, 3, 4) - 306.869898) < 0.000000001, true)
            _expect("7,-3 rounded to six decimals", absf(GMRuntime.gml_point_direction(0, 0, 7, -3) - 23.198591) < 0.000000001, true)
            _expect("from another point", absf(GMRuntime.gml_point_direction(3, 5, 11, 2) - 20.556045) < 0.000000001, true)
            _expect("straight up", GMRuntime.gml_point_direction(10, 10, 10, 5), 90.0)
            _expect("straight down", GMRuntime.gml_point_direction(10, 10, 10, 15), 270.0)
            _expect("no vector", GMRuntime.gml_point_direction(10, 10, 10, 10), 0.0)
            _expect("straight right", GMRuntime.gml_point_direction(0, 0, 5, 0), 0.0)
            _expect("straight right is not -0", 1.0 / GMRuntime.gml_point_direction(0, 0, 5, 0), INF)
            _expect("straight left", GMRuntime.gml_point_direction(0, 0, -5, 0), 180.0)
            _expect("up right", GMRuntime.gml_point_direction(0, 0, 1, -1), 45.0)
            _expect("down left", GMRuntime.gml_point_direction(0, 0, -1, 1), 225.0)
            _expect("down left octant", floor(GMRuntime.gml_point_direction(0, 0, -1, 1) / 45.0), 5.0)
            _expect("down right", GMRuntime.gml_point_direction(0, 0, 1, 1), 315.0)
            _expect("degtorad uses the runner's pi / 180", GMRuntime.gml_degtorad(180), 180.0 * 0.0174532925)
            """,
            "GML_POINT_DIRECTION_OK",
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

    def test_structs_keep_id_handle_and_type_members_as_members(self) -> None:
        # A struct has whatever members it is given: an id, a handle or a
        # type member does not make it an instance, an object or an asset.
        _run_runtime_checks(
            self,
            """\
            var level = {"id": 3, "type": "object", "name": "o_level", "title": "Workshop"}
            _expect("read", GMRuntime.gml_selector_get(level, "title"), "Workshop")
            _expect("read id", GMRuntime.gml_selector_get(level, "id"), 3)
            GMRuntime.gml_selector_set(level, "title", "Renamed")
            _expect("write", level.get("title"), "Renamed")
            GMRuntime.gml_selector_update(level, "id", func(value): return value + 1)
            _expect("update", level.get("id"), 4)
            var with_targets = GMRuntime.gml_with_targets(level)
            _expect("with", with_targets.size() == 1 and is_same(with_targets[0], level), true)
            _expect("variable_instance_get", GMRuntime.gml_variable_instance_get(level, "name"), "o_level")
            var holder = {"handle": 7, "file": "save.ini"}
            _expect("handle member", GMRuntime.gml_selector_get(holder, "file"), "save.ini")
            _expect("variable_instance_exists", GMRuntime.gml_variable_instance_exists(holder, "file"), true)
            GMRuntime.gml_variable_instance_set(holder, "file", "other.ini")
            _expect("variable_instance_set", holder.get("file"), "other.ini")
            var globals = GMRuntime.gml_global_scope()
            globals["handle"] = 1
            globals["score_seen"] = 12
            _expect("global with a handle member", GMRuntime.gml_selector_get(globals, "score_seen"), 12)
            globals.erase("handle")
            globals.erase("score_seen")
            """,
            "GML_STRUCT_MEMBERS_OK",
        )


if __name__ == "__main__":
    unittest.main()
