"""Godot checks for array searches and computed struct member names.

GameMaker compares array elements with == (numbers by value within the
math epsilon), takes a predicate in array_find_index and turns struct member
names that are not strings into text with string().
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
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

_SMOKE_SCRIPT = textwrap.dedent(
    """\
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    func _probe():
    __PROBE__

    func _ready():
    \tvar results = _probe()
    \tvar expected = __EXPECTED__
    \tvar failures = []
    \tfor index in expected.size():
    \t\tif str(results[index]) != str(expected[index]):
    \t\t\tfailures.append("result %d: expected %s, got %s" % [index, str(expected[index]), str(results[index])])
    \tif failures.is_empty():
    \t\tprint("ARRAY_SEARCH_OK")
    \t\tget_tree().quit(0)
    \t\treturn
    \tfor failure in failures:
    \t\tprint("FAIL " + failure)
    \tget_tree().quit(1)
    """
)


def _run_gml_probe(test: unittest.TestCase, gml: str, expected: str) -> None:
    godot_binary = _find_godot_binary()
    if godot_binary is None:
        test.skipTest("Godot binary not available")
    probe = transpile_gml_code(
        textwrap.dedent(gml),
        indent="\t",
        return_depth=1,
        other_expression="self",
    )
    script = _SMOKE_SCRIPT.replace("__PROBE__", probe).replace("__EXPECTED__", expected)
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_text(project_dir / "project.godot", "[application]\n")
        write_gml_runtime(str(project_dir))
        _write_text(project_dir / "smoke.gd", script)
        _write_text(project_dir / "smoke.tscn", _SMOKE_SCENE)
        result = run_headless_scene(godot_binary, project_dir, "smoke.tscn", timeout=60)
    test.assertEqual(result.returncode, 0, result.stdout)
    test.assertIn("ARRAY_SEARCH_OK", result.stdout)
    test.assertNotIn("SCRIPT ERROR", result.stdout)


class TestArraySearchGodot(unittest.TestCase):
    def test_array_contains_and_get_index_compare_like_equality(self) -> None:
        _run_gml_probe(
            self,
            """\
            var _a = [1, 2, 3];
            var _b = [0.3, "3", undefined, 3];
            var _inner = [5];
            var _c = [[5], _inner];
            return [
                array_contains(_a, 6 / 2),
                array_get_index(_a, 6 / 2),
                array_contains(_b, 0.1 + 0.2),
                array_get_index(_b, "3"),
                array_get_index(_b, undefined),
                array_get_index(_b, 3),
                array_get_index(_c, _inner),
                array_contains(_a, 4),
                array_get_index(_a, 4),
            ];
            """,
            "[true, 2, true, 1, 2, 3, 1, false, -1]",
        )

    def test_array_searches_honour_offset_and_length(self) -> None:
        _run_gml_probe(
            self,
            """\
            var _a = [7, 1, 7, 1, 7];
            return [
                array_get_index(_a, 7, 1),
                array_get_index(_a, 7, -1),
                array_get_index(_a, 7, 3, -2),
                array_get_index(_a, 7, 3, -1),
                array_get_index(_a, 1, 2, 1),
                array_get_index(_a, 1, 99),
                array_get_index(_a, 7, -99, 1),
                array_contains(_a, 1, 2, 1),
                array_contains(_a, 1, 2, 2),
                array_contains([], 1),
                array_get_index([], undefined),
            ];
            """,
            "[2, 4, 2, -1, -1, -1, 0, false, true, false, -1]",
        )

    def test_array_find_index_calls_a_predicate(self) -> None:
        _run_gml_probe(
            self,
            """\
            var _a = [3, 8, 1, 9, 4];
            var _seen = [];
            var _first_big = array_find_index(_a, function(_element, _index) {
                return _element > 5;
            });
            var _last_big = array_find_index(_a, function(_element) {
                return _element > 5;
            }, -1, -infinity);
            var _none = array_find_index(_a, function(_element) {
                return _element > 50;
            });
            var _from_two = array_find_index(_a, function(_element) {
                return _element > 5;
            }, 2);
            var _limit = 4;
            var _bound = array_find_index(_a, method({_limit}, function(_element) {
                return _element == _limit;
            }));
            array_find_index(_a, method({_seen}, function(_element, _index) {
                array_push(_seen, _index);
                return _index == 2;
            }));
            return [_first_big, _last_big, _none, _from_two, _bound, _seen];
            """,
            "[1, 3, -1, 3, 4, [0, 1, 2]]",
        )

    def test_struct_member_names_use_gamemaker_string_conversion(self) -> None:
        _run_gml_probe(
            self,
            """\
            var _s = {};
            _s[$ 4 / 2] = "two";
            _s[$ 2.5] = "two and a half";
            variable_struct_set(_s, 6 / 2, "three");
            var _names = variable_struct_get_names(_s);
            array_sort(_names, true);
            return [
                _names,
                _s[$ 2],
                _s[$ "2"],
                _s[$ "2.50"],
                struct_exists(_s, 9 / 3),
                struct_get(_s, 3),
            ];
            """,
            '[["2", "2.50", "3"], "two", "two", "two and a half", true, "three"]',
        )


if __name__ == "__main__":
    unittest.main()
