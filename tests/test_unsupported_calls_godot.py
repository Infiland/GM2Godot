"""A call the converted game cannot run fails on its own, not the whole script.

GameMaker's HTML5 runner binds functions it does not support to ErrorFunction
(yyRunTime.js), which reports "function X is not supported" once per function
and returns, so the rest of the event keeps running. The converter emits such
a call as GMRuntime.gml_unsupported_call; this runs that code in Godot.
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

_RESULT_PREFIX = "UNSUPPORTED_RESULT "

_GML = """
var a = show_message_async("first");
var b = 1;
var c = show_message_async("second");
var d = gif_open(320, 180);
b += 1;
var e = [is_undefined(a), is_undefined(c), is_undefined(d), b];
"""


def _probe_script() -> str:
    body = transpile_gml_code(_GML, indent="\t")
    return (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var other = null\n\n\n"
        "func _ready():\n"
        f"{body}\n"
        f"\tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify(e))\n"
        "\tget_tree().quit(0)\n"
    )


class TestUnsupportedCallsGodot(unittest.TestCase):
    def test_unsupported_call_reports_once_and_the_rest_runs(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_fixture_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="UnsupportedCalls"\nrun/main_scene="res://probe.tscn"\n',
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
        lines = [line for line in output.splitlines() if line.startswith(_RESULT_PREFIX)]
        self.assertEqual(len(lines), 1, output)
        self.assertEqual(json.loads(lines[0].removeprefix(_RESULT_PREFIX)), [True, True, True, 2])
        # Each function is reported once, however often it is called.
        self.assertEqual(
            output.count("GML function 'show_message_async' cannot run in the converted game"), 1, output
        )
        self.assertEqual(output.count("GML function 'gif_open' cannot run in the converted game"), 1, output)


if __name__ == "__main__":
    unittest.main()
