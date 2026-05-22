from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass

from src.conversion.animation_curve_registry import (
    build_animation_curve_registry_entries,
    render_animation_curve_registry_script,
    write_animation_curve_registry,
)


@dataclass(frozen=True)
class _AssetEntry:
    id: int
    name: str
    kind: str
    source_path: str


class TestAnimationCurveRegistry(unittest.TestCase):
    def test_builds_animation_curve_registry_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            curve_dir = os.path.join(tmpdir, "animcurves", "ac_bounce")
            os.makedirs(curve_dir)
            with open(os.path.join(curve_dir, "ac_bounce.yy"), "w", encoding="utf-8") as f:
                f.write(
                    '{\n'
                    '  "name": "ac_bounce",\n'
                    '  "channels": [\n'
                    '    {"name": "height", "function": "linear", "iterations": 1,\n'
                    '     "points": [\n'
                    '       {"x": 0.0, "y": 0.0, "bezierX0": 0.1, "bezierY0": 0.2,},\n'
                    '       {"x": 1.0, "y": 1.0, "bezierX1": 0.8, "bezierY1": 0.9,},\n'
                    '     ],},\n'
                    '  ],\n'
                    '}\n'
                )

            entries = build_animation_curve_registry_entries(
                tmpdir,
                (
                    _AssetEntry(
                        300,
                        "ac_bounce",
                        "animcurves",
                        "animcurves/ac_bounce/ac_bounce.yy",
                    ),
                ),
            )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.id, 300)
        self.assertEqual(entry.name, "ac_bounce")
        self.assertEqual(entry.channels[0].name, "height")
        self.assertEqual(entry.channels[0].points[1].bezier_x1, 0.8)

    def test_writes_animation_curve_registry_script(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            curve_dir = os.path.join(gm_dir, "animcurves", "ac_fade")
            os.makedirs(curve_dir)
            with open(os.path.join(curve_dir, "ac_fade.yy"), "w", encoding="utf-8") as f:
                f.write('{"name":"ac_fade","channels":[{"name":"alpha","points":[{"x":0,"y":1}]}]}\n')

            registry_path = write_animation_curve_registry(
                gm_dir,
                godot_dir,
                (
                    _AssetEntry(
                        301,
                        "ac_fade",
                        "animcurves",
                        "animcurves/ac_fade/ac_fade.yy",
                    ),
                ),
            )
            with open(registry_path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("extends RefCounted", content)
        self.assertIn('"id": 301', content)
        self.assertIn('"name": "ac_fade"', content)
        self.assertIn('"channels"', content)
        self.assertEqual(
            render_animation_curve_registry_script(()),
            "extends RefCounted\n\nstatic func entries():\n\treturn []\n",
        )


if __name__ == "__main__":
    unittest.main()
