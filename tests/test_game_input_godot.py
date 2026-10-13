from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)


def _write_smoke_scene(project_dir: Path) -> None:
    input_probe_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var id = GMRuntime.gml_instance_noone()
        var events = []

        func _ready():
        \tid = GMRuntime.gml_instance_register(self, "o_input_probe", [])

        func _exit_tree():
        \tGMRuntime.gml_instance_unregister(id)

        func _gm_input_contains_point(x, y):
        \treturn x >= 0 and x <= 100 and y >= 0 and y <= 100

        func _gm_input_event_bindings():
        \treturn [
        \t\t{"event_type": 5, "event_num": KEY_SPACE, "method": "_gm_input_keyboard_32"},
        \t\t{"event_type": 9, "event_num": KEY_SPACE, "method": "_gm_input_key_press_32"},
        \t\t{"event_type": 10, "event_num": KEY_SPACE, "method": "_gm_input_key_release_32"},
        \t\t{"event_type": 6, "event_num": 53, "method": "_gm_input_mouse_53"},
        \t\t{"event_type": 13, "event_num": 0, "method": "_gm_input_gesture_0"},
        \t]

        func _gm_input_keyboard_32():
        \tevents.append("held")

        func _gm_input_key_press_32():
        \tevents.append("pressed")

        func _gm_input_key_release_32():
        \tevents.append("released")

        func _gm_input_mouse_53():
        \tevents.append("mouse_global_press")

        func _gm_input_gesture_0():
        \tvar data = GMRuntime.gml_builtin_global("event_data")
        \tevents.append("tap:" + str(GMRuntime.gml_ds_map_find_value(data, "posX")))
        """
    )
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const InputProbe = preload("res://input_probe.gd")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _ready():
        \t# Checks the input bridge without the GameMaker frame pump, where
        \t# input changes are visible at once (tests/test_game_step_godot.py
        \t# covers the step-latched input of a running game).
        \tGMRuntime.gml_event_scheduler_pump_detach()
        \tGMRuntime.gml_input_begin_frame()
        \tGMRuntime.gml_input_set_key_state(KEY_SPACE, true)
        \tif not _check(GMRuntime.gml_keyboard_check(KEY_SPACE), "keyboard held state missing"):
        \t\treturn
        \tif not _check(GMRuntime.gml_keyboard_check_pressed(KEY_SPACE), "keyboard press edge missing"):
        \t\treturn
        \tGMRuntime.gml_input_begin_frame()
        \tif not _check(GMRuntime.gml_keyboard_check(KEY_SPACE), "keyboard held state did not persist"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_keyboard_check_pressed(KEY_SPACE), "keyboard press edge persisted too long"):
        \t\treturn
        \tGMRuntime.gml_input_set_key_state(KEY_SPACE, false)
        \tif not _check(GMRuntime.gml_keyboard_check_released(KEY_SPACE), "keyboard release edge missing"):
        \t\treturn
        \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, true)
        \tif not _check(GMRuntime.gml_mouse_check_button(MOUSE_BUTTON_LEFT), "mouse held state missing"):
        \t\treturn
        \tif not _check(GMRuntime.gml_mouse_check_button_pressed(MOUSE_BUTTON_LEFT), "mouse press edge missing"):
        \t\treturn
        \tGMRuntime.gml_input_begin_frame()
        \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, false)
        \tif not _check(GMRuntime.gml_mouse_check_button_released(MOUSE_BUTTON_LEFT), "mouse release edge missing"):
        \t\treturn
        \tGMRuntime.gml_display_set_gui_size(800, 450)
        \tGMRuntime.gml_input_set_mouse_position(400, 225)
        \tif not _check(GMRuntime.gml_display_mouse_get_x() == 400 and GMRuntime.gml_display_mouse_get_y() == 225, "mouse position mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_device_mouse_x_to_gui(0) > 0 and GMRuntime.gml_device_mouse_y_to_gui(0) > 0, "GUI mouse conversion failed"):
        \t\treturn
        \tGMRuntime.gml_input_set_gamepad_button_state(0, JOY_BUTTON_A, true)
        \tif not _check(GMRuntime.gml_gamepad_button_check(0, JOY_BUTTON_A), "gamepad held state missing"):
        \t\treturn
        \tif not _check(GMRuntime.gml_gamepad_button_check_pressed(0, JOY_BUTTON_A), "gamepad press edge missing"):
        \t\treturn
        \tGMRuntime.gml_input_begin_frame()
        \tGMRuntime.gml_input_set_gamepad_button_state(0, JOY_BUTTON_A, false)
        \tif not _check(GMRuntime.gml_gamepad_button_check_released(0, JOY_BUTTON_A), "gamepad release edge missing"):
        \t\treturn
        \tGMRuntime.gml_gamepad_set_axis_deadzone(0, 0.2)
        \tGMRuntime.gml_input_set_gamepad_axis_value(0, JOY_AXIS_LEFT_X, 0.1)
        \tif not _check(GMRuntime.gml_gamepad_axis_value(0, JOY_AXIS_LEFT_X) == 0.0, "gamepad deadzone was not applied"):
        \t\treturn
        \tGMRuntime.gml_input_set_gamepad_axis_value(0, JOY_AXIS_LEFT_X, 0.5)
        \tif not _check(GMRuntime.gml_gamepad_axis_value(0, JOY_AXIS_LEFT_X) == 0.5, "gamepad axis value mismatch"):
        \t\treturn
        \tGMRuntime.gml_input_append_text("a")
        \tif not _check(GMRuntime.gml_builtin_global("keyboard_string") == "a", "keyboard_string mismatch"):
        \t\treturn
        \t# Like GameMaker, keyboard_clear() leaves keyboard_string alone.
        \tGMRuntime.gml_keyboard_clear(1)
        \tif not _check(GMRuntime.gml_builtin_global("keyboard_string") == "a", "keyboard_clear changed keyboard_string"):
        \t\treturn
        \tvar probe = InputProbe.new()
        \tprobe.name = "Probe"
        \tadd_child(probe)
        \tGMRuntime.gml_input_begin_frame()
        \tGMRuntime.gml_input_set_key_state(KEY_SPACE, true)
        \tGMRuntime.gml_input_set_mouse_position(10, 10)
        \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, true)
        \tGMRuntime.gml_input_enqueue_gesture(0, {"posX": 42, "posY": 24}, true)
        \tvar dispatched = GMRuntime.gml_input_dispatch_frame([probe])
        \tif not _check(dispatched == 4, "input dispatch count mismatch"):
        \t\treturn
        \tif not _check(probe.events == ["held", "pressed", "mouse_global_press", "tap:42"], "input dispatch order mismatch: " + str(probe.events)):
        \t\treturn
        \tif not _check(GMRuntime.gml_ds_map_size(GMRuntime.gml_builtin_global("event_data")) == 0, "event_data was not reset"):
        \t\treturn
        \tprobe.events.clear()
        \tGMRuntime.gml_input_begin_frame()
        \tdispatched = GMRuntime.gml_input_dispatch_frame([probe])
        \tif not _check(dispatched == 1 and probe.events == ["held"], "held input did not persist exactly one frame"):
        \t\treturn
        \tprobe.events.clear()
        \tGMRuntime.gml_input_begin_frame()
        \tGMRuntime.gml_input_set_key_state(KEY_SPACE, false)
        \tdispatched = GMRuntime.gml_input_dispatch_frame([probe])
        \tif not _check(dispatched == 1 and probe.events == ["released"], "release input did not dispatch"):
        \t\treturn
        \tprint("GAME_INPUT_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "input_probe.gd", input_probe_script)
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


_CLEAR_SMOKE_SCRIPT = textwrap.dedent(
    """\
    extends Node

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    var _failures = []

    func _expect(label, condition):
    \tif not condition:
    \t\t_failures.append(label)

    func _held(button):
    \treturn GMRuntime.gml_mouse_check_button(button)

    func _ready():
    \t# Drives the step latch by hand, as the GameMaker frame pump does.
    \tGMRuntime.gml_event_scheduler_pump_detach()
    \tGMRuntime.gml_input_set_step_latching(true)

    \t# mouse_clear: the button reads as up at once and stays up while held;
    \t# its release is still reported and a new press is seen again.
    \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, true)
    \tGMRuntime.gml_input_begin_step()
    \t_expect("left press latched", _held(1) and GMRuntime.gml_mouse_check_button_pressed(1))
    \tGMRuntime.gml_mouse_clear(1)
    \t_expect("mouse_clear releases the button at once", not _held(1))
    \t_expect("mouse_clear clears the press edge", not GMRuntime.gml_mouse_check_button_pressed(1))
    \t_expect("mb_any sees no cleared button", not _held(-1))
    \tGMRuntime.gml_input_begin_step()
    \t_expect("a cleared button stays up while held", not _held(1) and not GMRuntime.gml_mouse_check_button_pressed(1))
    \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, false)
    \tGMRuntime.gml_input_begin_step()
    \t_expect("the release of a cleared button is reported", GMRuntime.gml_mouse_check_button_released(1))
    \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_LEFT, true)
    \tGMRuntime.gml_input_begin_step()
    \t_expect("a new press is seen after the release", _held(1) and GMRuntime.gml_mouse_check_button_pressed(1))

    \t# mb_any clears mb_left, mb_right and mb_middle only. A press that
    \t# arrived after this step latched still belongs to the next step.
    \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_XBUTTON1, true)
    \tGMRuntime.gml_input_begin_step()
    \tGMRuntime.gml_input_set_mouse_button_state(MOUSE_BUTTON_RIGHT, true)
    \tGMRuntime.gml_mouse_clear(-1)
    \t_expect("mb_any clears the left button", not _held(1))
    \t_expect("mb_any leaves the side buttons", _held(4))
    \tGMRuntime.gml_input_begin_step()
    \t_expect("left stays cleared on the next step", not _held(1))
    \t_expect("a press after the latch is seen on the next step", _held(2) and GMRuntime.gml_mouse_check_button_pressed(2))

    \t# io_clear: keys and buttons read as up for the rest of the step,
    \t# keyboard_key, keyboard_lastkey and keyboard_string are reset and the
    \t# wheel is cleared. Held keys come back on the next step; held mouse
    \t# buttons stay up like after mouse_clear.
    \tGMRuntime.gml_input_set_key_state(KEY_A, true)
    \tGMRuntime.gml_input_set_key_state(KEY_B, true)
    \tGMRuntime.gml_input_append_text("ab")
    \tGMRuntime.gml_input_set_mouse_wheel(true, false)
    \tGMRuntime.gml_input_begin_step()
    \t_expect("keys latched", GMRuntime.gml_keyboard_check(KEY_A) and GMRuntime.gml_keyboard_check_pressed(KEY_B))
    \t_expect("keyboard_key latched", GMRuntime.gml_builtin_global("keyboard_key") != 0)
    \t_expect("wheel latched", GMRuntime.gml_builtin_global("mouse_wheel_up"))
    \tGMRuntime.gml_io_clear()
    \t_expect("io_clear releases held keys", not GMRuntime.gml_keyboard_check(KEY_A) and not GMRuntime.gml_keyboard_check(KEY_B))
    \t_expect("io_clear clears key press edges", not GMRuntime.gml_keyboard_check_pressed(KEY_B))
    \t_expect("io_clear leaves no key for vk_anykey", not GMRuntime.gml_keyboard_check(1) and GMRuntime.gml_keyboard_check(0))
    \t_expect("io_clear resets keyboard_key", GMRuntime.gml_builtin_global("keyboard_key") == 0)
    \t_expect("io_clear resets keyboard_lastkey", GMRuntime.gml_builtin_global("keyboard_lastkey") == 0)
    \t_expect("io_clear resets keyboard_string", GMRuntime.gml_builtin_global("keyboard_string") == "")
    \t_expect("io_clear clears the wheel", not GMRuntime.gml_builtin_global("mouse_wheel_up"))
    \t_expect("io_clear releases mouse buttons", not _held(2) and not _held(4) and not GMRuntime.gml_mouse_check_button_pressed(2))
    \tGMRuntime.gml_input_begin_step()
    \t_expect("a held key is seen again on the next step", GMRuntime.gml_keyboard_check(KEY_A) and not GMRuntime.gml_keyboard_check_pressed(KEY_A))
    \t_expect("held mouse buttons stay up after io_clear", not _held(2) and not _held(4))

    \tif _failures.is_empty():
    \t\tprint("INPUT_CLEAR_SMOKE_OK")
    \telse:
    \t\tfor failure in _failures:
    \t\t\tprint("FAIL " + failure)
    \tget_tree().quit(0 if _failures.is_empty() else 1)
    """
)


class TestGameInputGodotSmoke(unittest.TestCase):
    def test_input_bridge_tracks_edges_and_coordinates(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="GameInputSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_smoke_scene(project_dir)

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--log-file",
                    str(project_dir / "godot.log"),
                    "--path",
                    str(project_dir),
                    "--scene",
                    "res://smoke.tscn",
                    "--quit-after",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("GAME_INPUT_SMOKE_OK", output)

    def test_io_clear_and_mouse_clear_follow_gamemaker(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="InputClearSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", _CLEAR_SMOKE_SCRIPT)
            _write_text(
                project_dir / "smoke.tscn",
                '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://smoke.gd" id="1"]\n\n'
                '[node name="Smoke" type="Node"]\nscript = ExtResource("1")\n',
            )
            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "--scene", "res://smoke.tscn", "--quit-after", "10"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertIn("INPUT_CLEAR_SMOKE_OK", output)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)


if __name__ == "__main__":
    unittest.main()
