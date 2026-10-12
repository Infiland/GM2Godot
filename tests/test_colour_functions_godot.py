"""GameMaker's colour functions give the runner's values in a converted game.

The reference below ports Function_Graphics.js from the GameMaker HTML5
runner (make_color_rgb, make_color_hsv, merge_color, color_get_* and
Color_RGBtoHSV), including its yyGetInt32 / ``~~`` truncation and 32-bit
wrapping. The test transpiles GML calls to every documented spelling,
runs it through the generated runtime in Godot and compares each value.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_RESULT_PREFIX = "COLOUR_RESULT "


def _int32(value: float) -> int:
    """JavaScript ToInt32, which the runner's ``~~`` and yyGetInt32 apply."""
    if math.isnan(value) or math.isinf(value):
        return 0
    wrapped = int(math.trunc(value)) % 2**32
    return wrapped - 2**32 if wrapped >= 2**31 else wrapped


def _make_color_rgb(red: float, green: float, blue: float) -> int:
    return _int32(_int32(red) | _int32(_int32(green) << 8) | _int32(_int32(blue) << 16))


def _color_get(colour: float, shift: int) -> int:
    return (_int32(colour) >> shift) & 0xFF


def _rgb_to_hsv(colour: float) -> tuple[float, float, float]:
    packed = _int32(colour)
    rr = (packed & 0xFF) / 255.0
    gg = ((packed >> 8) & 0xFF) / 255.0
    bb = ((packed >> 16) & 0xFF) / 255.0
    low = min(min(rr, gg), bb)
    vv = max(max(rr, gg), bb)
    d = vv - low
    ss = 0.0 if vv == 0 else 1.0 * d / vv
    if ss == 0:
        hh = 0.0
    elif rr == vv:
        hh = 60.0 * (gg - bb) / d
    elif gg == vv:
        hh = 120.0 + 60.0 * (bb - rr) / d
    else:
        hh = 240.0 + 60.0 * (rr - gg) / d
    if hh < 0:
        hh += 360.0
    return (
        min(255.0, max(0.0, (hh * 255.0) / 360.0)),
        min(255.0, max(0.0, ss * 255.0)),
        min(255.0, max(0.0, vv * 255.0)),
    )


def _merge_color(col1: float, col2: float, amount: float) -> int:
    first, second = _int32(col1), _int32(col2)
    keep = 1.0 - amount
    channels = [
        _int32(((first >> shift) & 0xFF) * keep + ((second >> shift) & 0xFF) * amount)
        for shift in (16, 8, 0)
    ]
    return ((channels[0] << 16) & 0xFF0000) | ((channels[1] << 8) & 0xFF00) | (channels[2] & 0xFF)


def _make_color_hsv(hue: float, saturation: float, value: float) -> int:
    hh = hue * 360.0 / 255.0
    if hh == 360.0:
        hh = 0.0
    ss = saturation / 255.0
    vv = value / 255.0
    if ss == 0:
        rr = gg = bb = vv
    else:
        hh = hh / 60.0
        sector = math.floor(hh)
        f = hh - sector
        p = vv * (1.0 - ss)
        q = vv * (1.0 - (ss * f))
        t = vv * (1.0 - (ss * (1.0 - f)))
        rr, gg, bb = {
            0: (vv, t, p),
            1: (q, vv, p),
            2: (p, vv, t),
            3: (p, q, vv),
            4: (t, p, vv),
        }.get(sector, (vv, p, q))
    levels = [max(0, min(255, math.floor(channel * 255.0 + 0.5))) for channel in (rr, gg, bb)]
    return levels[0] | (levels[1] << 8) | (levels[2] << 16)


_RGB_CASES = (
    (255, 128, 0),
    (0, 0, 255),
    (127.5, 254.9, 0.99),
    (-0.5, 12.7, 200.2),
    (255, 255, 256),
    (300, 0, 0),
    (0, 300, 200),
    (-1, 0, 0),
    (0, 0, 2**31 + 5),
    (1e10, 0, 0),
)
_COLOURS = (0x000000, 0xFFFFFF, 0x0000FF, 0x00FF00, 0xFF0000, 0x4080C0, 0x123456, 0xC08040, 255.7, -1, 0x1FFFFFF)
_MERGES = ((0x0000FF, 0xFF0000, 0.5), (0x4080C0, 0x123456, 0.25), (0xFFFFFF, 0x000000, 0.3), (0x102030, 0xF0E0D0, 1.5),
           (0x102030, 0xF0E0D0, -0.5), (0x00FF00, 0x0000FF, 2.0), (0x808080, 0x808080, 0.0), (0x0000FF, 0xFF0000, 1.0))
_HSV_CASES = ((0, 255, 255), (21.25, 255, 255), (42.5, 200, 180), (85, 128, 255), (127.5, 255, 100), (170, 64, 64),
              (212.5, 255, 255), (255, 255, 255), (300, 255, 255), (-10, 255, 255), (40, 0, 77), (100, 255, 255.5),
              (12.3, 45.6, 78.9))

# GML for each case, with the value GameMaker returns.
_CASES: tuple[tuple[str, float], ...] = (
    *(
        (f"{name}({r}, {g}, {b})", float(_make_color_rgb(r, g, b)))
        for r, g, b in _RGB_CASES
        for name in ("make_color_rgb", "make_colour_rgb")
    ),
    *(
        (f"{spelling}_get_{channel}({colour})", float(_color_get(colour, shift)))
        for colour in _COLOURS
        for channel, shift in (("red", 0), ("green", 8), ("blue", 16))
        for spelling in ("color", "colour")
    ),
    *(
        (f"{spelling}_get_{part}({colour})", _rgb_to_hsv(colour)[index])
        for colour in _COLOURS
        for index, part in enumerate(("hue", "saturation", "value"))
        for spelling in ("color", "colour")
    ),
    *(
        (f"{name}({col1}, {col2}, {amount})", float(_merge_color(col1, col2, amount)))
        for col1, col2, amount in _MERGES
        for name in ("merge_color", "merge_colour")
    ),
    *(
        (f"{name}({h}, {s}, {v})", float(_make_color_hsv(h, s, v)))
        for h, s, v in _HSV_CASES
        for name in ("make_color_hsv", "make_colour_hsv")
    ),
    ('make_colour_rgb("200", true, 0)', float(_make_color_rgb(200, 1, 0))),
    ("colour_get_hue(make_colour_hsv(42.5, 255, 255))", _rgb_to_hsv(_make_color_hsv(42.5, 255, 255))[0]),
)


def _probe_script() -> str:
    values = "".join(f"\t\t{transpile_gml_expression(expression)},\n" for expression, _ in _CASES)
    return (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var other = null\n\n\n"
        "func _ready():\n"
        f"\tvar results = [\n{values}\t]\n"
        f"\tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify(results))\n"
        "\tget_tree().quit(0)\n"
    )


class TestColourFunctionsGodot(unittest.TestCase):
    def test_colour_functions_return_gamemaker_values(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_fixture_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="ColourFunctions"\nrun/main_scene="res://probe.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            write_fixture_text(project_dir / "probe.gd", _probe_script())
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
        values = json.loads(lines[0].removeprefix(_RESULT_PREFIX))
        self.assertEqual(len(values), len(_CASES))
        for (expression, expected), actual in zip(_CASES, values, strict=True):
            with self.subTest(expression=expression):
                self.assertAlmostEqual(float(actual), expected, places=9)


if __name__ == "__main__":
    unittest.main()
