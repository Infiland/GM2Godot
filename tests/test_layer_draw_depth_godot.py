"""layer_force_draw_depth keeps the setting its getters report.

As in the HTML5 runner (functions/Function_Layers.js): layer_force_draw_depth
(force, depth) stores yyGetBool(force) and yyGetInt32(depth), which
layer_is_draw_depth_forced and layer_get_forced_depth return; forcing is off
and the depth 0 at the start.
"""
from __future__ import annotations

import unittest

from tests.test_string_functions_godot import run_string_probe

_CASES: tuple[tuple[str, object], ...] = (
    ("layer_is_draw_depth_forced()", False),
    ("layer_get_forced_depth()", 0),
    ("is_undefined(layer_force_draw_depth(true, 7.9))", True),
    ("layer_is_draw_depth_forced()", True),
    ("layer_get_forced_depth()", 7),
    ("is_undefined(layer_force_draw_depth(0, -5))", True),
    ("layer_is_draw_depth_forced()", False),
    ("layer_get_forced_depth()", -5),
)


class TestLayerDrawDepthGodot(unittest.TestCase):
    def test_forced_draw_depth_setting(self) -> None:
        actual = run_string_probe(self, _CASES)
        for (expression, expected), value in zip(_CASES, actual, strict=True):
            with self.subTest(expression=expression):
                self.assertEqual(value, expected)


if __name__ == "__main__":
    unittest.main()
