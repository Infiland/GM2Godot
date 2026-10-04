from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json

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

    def test_skips_uncontained_animation_curve_metadata_sources(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside_yy = os.path.join(outside_dir, "ac_outside.yy")
            with open(outside_yy, "w", encoding="utf-8") as source_file:
                source_file.write('{"name":"ac_outside","channels":[]}')
            linked_dir = os.path.join(gm_dir, "animcurves", "ac_linked")
            os.makedirs(linked_dir)
            linked_yy = os.path.join(linked_dir, "ac_linked.yy")
            try:
                os.symlink(outside_yy, linked_yy)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = build_animation_curve_registry_entries(
                gm_dir,
                (
                    _AssetEntry(
                        1,
                        "ac_parent",
                        "animcurves",
                        "../../../outside.yy",
                    ),
                    _AssetEntry(
                        2,
                        "ac_linked",
                        "animcurves",
                        "animcurves/ac_linked/ac_linked.yy",
                    ),
                ),
            )

        self.assertEqual(entries, ())



class TestAnimationCurveTypedAcquisition(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.gm_dir = self.temp.name
        self.yy_path = os.path.join(self.gm_dir, "animcurves", "a", "a.yy")
        os.makedirs(os.path.dirname(self.yy_path))
        self.asset = _AssetEntry(3, "a", "animcurves", "animcurves/a/a.yy")
        self._write('{}')

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, source: str) -> None:
        with open(self.yy_path, "w", encoding="utf-8") as stream:
            stream.write(source)

    def test_one_shared_decode_and_authoritative_serialized_models(self) -> None:
        self._write('{"channels":[null,{"name":"height","points":[false,{"x":true,"y":"7"},],},],}')
        with patch("src.conversion.animation_curve_registry.decode_gamemaker_json", wraps=decode_gamemaker_json) as decoder:
            entries = build_animation_curve_registry_entries(self.gm_dir, (self.asset,))
        self.assertEqual(decoder.call_count, 1)
        self.assertEqual(decoder.call_args.kwargs["source_path"], self.yy_path)
        self.assertEqual(entries[0].channels[0].points[0].x, 1.0)
        self.assertEqual(entries[0].channels[0].points[0].y, 0.0)
        self.assertEqual(entries[0].to_godot_dict()["channels"], [entries[0].channels[0].to_godot_dict()])

    def test_decode_and_live_replacement_nonobject_policy(self) -> None:
        self._write('[]')
        self.assertEqual(build_animation_curve_registry_entries(self.gm_dir, (self.asset,)), ())
        self._write('{"channels":[{"points":[{"x":2}]}]}')
        entries = build_animation_curve_registry_entries(self.gm_dir, (self.asset,))
        self.assertEqual(entries[0].channels[0].points[0].x, 2.0)

    def test_json_error_is_skipped_but_value_and_runtime_errors_escape_by_identity(self) -> None:
        error = json.JSONDecodeError("bad", "{", 0)
        with patch("src.conversion.animation_curve_registry.decode_gamemaker_json", side_effect=error):
            self.assertEqual(build_animation_curve_registry_entries(self.gm_dir, (self.asset,)), ())
        for error in (ValueError("graph"), RuntimeError("decoder")):
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.animation_curve_registry.decode_gamemaker_json", side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        build_animation_curve_registry_entries(self.gm_dir, (self.asset,))
                self.assertIs(caught.exception, error)

    def test_invalid_utf8_escapes_before_decoder(self) -> None:
        with open(self.yy_path, "wb") as stream:
            stream.write(b'\xff')
        with patch("src.conversion.animation_curve_registry.decode_gamemaker_json") as decoder:
            with self.assertRaises(UnicodeDecodeError):
                build_animation_curve_registry_entries(self.gm_dir, (self.asset,))
        decoder.assert_not_called()

    def test_native_nonfinite_point_provenance_and_iterations_failure_remain(self) -> None:
        self._write('{"channels":[{"points":[{"x":NaN,"y":Infinity}]}]}')
        entry = build_animation_curve_registry_entries(self.gm_dir, (self.asset,))[0]
        self.assertTrue(math.isnan(entry.channels[0].points[0].x))
        self.assertEqual(entry.channels[0].points[0].y, float("inf"))
        self.assertIn("NaN", render_animation_curve_registry_script((entry,)))
        self._write('{"channels":[{"iterations":Infinity}]}')
        with self.assertRaises(OverflowError):
            build_animation_curve_registry_entries(self.gm_dir, (self.asset,))

    def test_point_conversion_failure_precedes_channel_iteration_conversion(self) -> None:
        self._write(json.dumps({"channels": [{"iterations": "ignored", "points": [{"x": 10 ** 400}]}]}))
        with self.assertRaises(OverflowError):
            build_animation_curve_registry_entries(self.gm_dir, (self.asset,))

if __name__ == "__main__":
    unittest.main()
