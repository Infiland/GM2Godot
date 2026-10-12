"""device_mouse_check_button* and mouse_wheel_up/down read the mouse in Godot.

As in the HTML5 runner: device_mouse_check_button, _pressed and _released
(functions/Function_YoYo.js) read the mouse for device 0 and touches for the
other devices, which report 0 when there is no touch; mouse_wheel_up and
mouse_wheel_down (functions/Function_IO.js) say whether the wheel turned that
way since the previous step.
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

_RESULT_PREFIX = "MOUSE_DEVICE_RESULT "


def _gml(expression: str) -> str:
    return transpile_gml_expression(expression)


_HELD = (
    "device_mouse_check_button(0, mb_left)",
    "device_mouse_check_button_pressed(0, mb_left)",
    "device_mouse_check_button_released(0, mb_left)",
    "device_mouse_check_button(1, mb_left)",
    "device_mouse_check_button_pressed(1, mb_left)",
    "device_mouse_check_button(0.5, mb_any)",
)
_RELEASED = (
    "device_mouse_check_button(0, mb_left)",
    "device_mouse_check_button_released(0, mb_left)",
    "device_mouse_check_button_released(2, mb_left)",
)
_WHEEL = ("mouse_wheel_up()", "mouse_wheel_down()")

_PROBE = f"""extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var other = null


func _ready():
	GMRuntime.gml_event_scheduler_pump_detach()
	var results = []
	GMRuntime.gml_input_begin_frame()
	GMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, true)
	results.append([{", ".join(_gml(expression) for expression in _HELD)}])
	GMRuntime.gml_input_begin_frame()
	GMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, false)
	results.append([{", ".join(_gml(expression) for expression in _RELEASED)}])
	GMRuntime.gml_input_begin_frame()
	GMRuntime.gml_input_set_mouse_wheel(true, false)
	results.append([{", ".join(_gml(expression) for expression in _WHEEL)}])
	GMRuntime.gml_input_begin_frame()
	results.append([{", ".join(_gml(expression) for expression in _WHEEL)}])
	GMRuntime.gml_input_set_mouse_wheel(false, true)
	results.append([{", ".join(_gml(expression) for expression in _WHEEL)}])
	print({json.dumps(_RESULT_PREFIX)} + JSON.stringify(results))
	get_tree().quit(0)
"""


class TestMouseDeviceFunctionsGodot(unittest.TestCase):
    def test_device_mouse_buttons_and_wheel(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_fixture_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="MouseDevice"\nrun/main_scene="res://probe.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            write_fixture_text(project_dir / "probe.gd", _PROBE)
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
        self.assertEqual(
            json.loads(lines[0].removeprefix(_RESULT_PREFIX)),
            [
                [True, True, False, 0, 0, True],
                [False, True, 0],
                [True, False],
                [False, False],
                [False, True],
            ],
        )


if __name__ == "__main__":
    unittest.main()
