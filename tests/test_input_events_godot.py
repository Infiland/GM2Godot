"""Godot smoke tests for GameMaker keyboard and mouse events under the frame pump.

Input arrives as real Godot input events and the GMEvents autoload runs the
steps, so key codes, event order, the <No Key>/<Any Key> events and mouse
enter/leave behave the way a converted game sees them.
"""
from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import (
    AssetRegistryEntry,
    render_asset_registry_script,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.script_generator import (
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    generate_script_content,
)
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    run_headless_scene,
    write_fixture_text as _write_text,
)

_CHECK_HELPER = """\
func _check(condition, message):
\tif not condition:
\t\tpush_error(str(message))
\t\tget_tree().quit(1)
\t\treturn false
\treturn true
"""

_MAIN_SCENE = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")
"""

_LOG_HELPER = """\
func _log(what):
\tvar scope = GMRuntime.gml_global_scope()
\tif not scope.has("log"):
\t\tscope["log"] = []
\tscope["log"].append(str(name) + ":" + what)
"""


def _project_file(name: str) -> str:
    return f'[application]\nconfig/name="{name}"\nrun/main_scene="res://main.tscn"\n'


class TestInputEventsGodotSmoke(unittest.TestCase):
    def _run_project(self, project_dir: Path, marker: str) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        try:
            result = run_headless_scene(godot_binary, project_dir, "main.tscn", timeout=60)
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
            self.fail("Godot input event smoke timed out\n" + output)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(marker, result.stdout)
        self.assertNotIn("SCRIPT ERROR", result.stdout)

    def test_keyboard_events_follow_gamemaker_key_codes_and_order(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        probe_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var id = GMRuntime.gml_instance_noone()
            var cleared = false

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, "o_keys", [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _gm_input_event_bindings():
            \t# Event numbers are GameMaker key codes: 37 left, 39 right,
            \t# 27 escape, 0 <No Key>, 1 <Any Key>.
            \treturn [
            \t\t{"event_type": 5, "event_num": 1, "method": "_held_any"},
            \t\t{"event_type": 5, "event_num": 39, "method": "_held_right"},
            \t\t{"event_type": 5, "event_num": 37, "method": "_held_left"},
            \t\t{"event_type": 5, "event_num": 0, "method": "_held_none"},
            \t\t{"event_type": 9, "event_num": 39, "method": "_press_right"},
            \t\t{"event_type": 9, "event_num": 37, "method": "_press_left"},
            \t\t{"event_type": 9, "event_num": 1, "method": "_press_any"},
            \t\t{"event_type": 9, "event_num": 0, "method": "_press_none"},
            \t\t{"event_type": 10, "event_num": 27, "method": "_release_escape"},
            \t\t{"event_type": 10, "event_num": 0, "method": "_release_none"},
            \t]

            """
        ) + _LOG_HELPER + textwrap.dedent(
            """\

            func _held_any():
            \t_log("held_any")

            func _held_right():
            \t_log("held_right")

            func _held_left():
            \t_log("held_left")

            func _held_none():
            \t_log("held_none")

            func _press_right():
            \t_log("press_right")

            func _press_left():
            \t_log("press_left")
            \t# Clearing a key in an earlier key's event skips its own events.
            \tif str(name) == "P1" and not cleared:
            \t\tcleared = true
            \t\tGMRuntime.gml_keyboard_clear(39)

            func _press_any():
            \t_log("press_any")

            func _press_none():
            \t_log("press_none")

            func _release_escape():
            \t_log("release_escape")

            func _release_none():
            \t_log("release_none")
            """
        )
        main_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const Probe = preload("res://probe.gd")

            var frames = []
            var states = []
            var tick = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _ready():
            \tfor probe_name in ["P1", "P2"]:
            \t\tvar probe = Probe.new()
            \t\tprobe.name = probe_name
            \t\tadd_child(probe)

            func _key(keycode, pressed, location = KEY_LOCATION_UNSPECIFIED):
            \tvar event = InputEventKey.new()
            \tevent.keycode = keycode
            \tevent.physical_keycode = keycode
            \tevent.location = location
            \tevent.pressed = pressed
            \tget_viewport().push_input(event)

            func _state():
            \tvar result = {}
            \tfor code in [0, 1, 16, 27, 37, 38, 39, 160, 161]:
            \t\tresult[code] = [
            \t\t\tint(GMRuntime.gml_keyboard_check(code)),
            \t\t\tint(GMRuntime.gml_keyboard_check_pressed(code)),
            \t\t\tint(GMRuntime.gml_keyboard_check_released(code)),
            \t\t]
            \tresult["godot_left"] = int(GMRuntime.gml_keyboard_check(KEY_LEFT))
            \tresult["key"] = GMRuntime.gml_builtin_global("keyboard_key")
            \tresult["lastkey"] = GMRuntime.gml_builtin_global("keyboard_lastkey")
            \treturn result

            func _process(_delta):
            \t# Runs after the GMEvents autoload: the step of this frame is done.
            \ttick += 1
            \tvar scope = GMRuntime.gml_global_scope()
            \tframes.append(scope.get("log", []))
            \tscope["log"] = []
            \tstates.append(_state())
            \tmatch tick:
            \t\t1:
            \t\t\t_key(KEY_RIGHT, true)
            \t\t\t_key(KEY_LEFT, true)
            \t\t2:
            \t\t\t_key(KEY_LEFT, false)
            \t\t\t_key(KEY_ESCAPE, true)
            \t\t\t_key(KEY_ESCAPE, false)
            \t\t3:
            \t\t\t_key(KEY_RIGHT, false)
            \t\t\t_key(KEY_SHIFT, true, KEY_LOCATION_LEFT)
            \t\t4:
            \t\t\t_key(KEY_SHIFT, true, KEY_LOCATION_RIGHT)
            \t\t\t_key(KEY_SHIFT, false, KEY_LOCATION_LEFT)
            \t\t5:
            \t\t\t_key(KEY_SHIFT, false, KEY_LOCATION_RIGHT)
            \t\t6:
            \t\t\tGMRuntime.gml_keyboard_key_press(38)
            \t\t7:
            \t\t\tGMRuntime.gml_keyboard_key_release(38)
            \t\t9:
            \t\t\t_verify()

            func _both(events):
            \tvar result = []
            \tfor event in events:
            \t\tresult.append("P1:" + event)
            \t\tresult.append("P2:" + event)
            \treturn result

            func _expect_frame(index, expected):
            \treturn _check(frames[index] == expected, "step " + str(index + 1) + " events: " + str(frames[index]) + ", expected " + str(expected))

            func _expect_state(index, key, expected):
            \treturn _check(states[index][key] == expected, "step " + str(index + 1) + " state of " + str(key) + ": " + str(states[index][key]) + ", expected " + str(expected))

            func _verify():
            \tvar idle = _both(["held_none"]) + _both(["press_none"]) + _both(["release_none"])
            \tif not _expect_frame(0, idle):
            \t\treturn
            \t# Keys run in GameMaker key code order (37 before 39) for every
            \t# instance, then <Any Key>; P1 clears 39 in its Key Press event.
            \tvar both_keys = _both(["held_left", "held_right", "held_any"]) + _both(["press_left", "press_any"]) + _both(["release_none"])
            \tif not _expect_frame(1, both_keys):
            \t\treturn
            \tif not (_expect_state(1, 37, [1, 1, 0]) and _expect_state(1, 39, [0, 0, 0]) and _expect_state(1, 1, [1, 1, 0]) and _expect_state(1, 0, [0, 0, 1])):
            \t\treturn
            \tif not (_expect_state(1, "godot_left", 0) and _expect_state(1, "key", 37)):
            \t\treturn
            \t# The cleared key stays up while it is held and its release is not
            \t# reported; escape is pressed and released between two steps.
            \tif not _expect_frame(2, _both(["held_none"]) + _both(["press_any"]) + _both(["release_escape"])):
            \t\treturn
            \tif not (_expect_state(2, 39, [0, 0, 0]) and _expect_state(2, 37, [0, 0, 1]) and _expect_state(2, 27, [0, 1, 1])):
            \t\treturn
            \tif not (_expect_state(2, "key", 27) and _expect_state(2, "lastkey", 37)):
            \t\treturn
            \tif not _expect_frame(3, _both(["held_any"]) + _both(["press_any"]) + _both(["release_none"])):
            \t\treturn
            \tif not (_expect_state(3, 39, [0, 0, 0]) and _expect_state(3, 16, [1, 1, 0]) and _expect_state(3, 160, [1, 1, 0]) and _expect_state(3, 161, [0, 0, 0])):
            \t\treturn
            \tif not (_expect_state(3, "key", 16) and _expect_state(3, "lastkey", 27)):
            \t\treturn
            \t# vk_shift stays held while either shift key is.
            \tif not (_expect_state(4, 16, [1, 0, 0]) and _expect_state(4, 160, [0, 0, 1]) and _expect_state(4, 161, [1, 1, 0])):
            \t\treturn
            \tif not (_expect_state(5, 16, [0, 0, 1]) and _expect_state(5, 0, [1, 1, 0]) and _expect_state(5, 1, [0, 0, 1])):
            \t\treturn
            \tif not (_expect_state(5, "key", 0) and _expect_state(5, "lastkey", 16)):
            \t\treturn
            \tif not _expect_frame(5, _both(["held_none"]) + _both(["press_none"])):
            \t\treturn
            \t# keyboard_key_press()/keyboard_key_release() take GameMaker codes.
            \tif not (_expect_state(6, 38, [1, 1, 0]) and _expect_state(6, "key", 38)):
            \t\treturn
            \tif not _expect_state(7, 38, [0, 0, 1]):
            \t\treturn
            \tprint("INPUT_KEYBOARD_EVENTS_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(project_dir / "project.godot", _project_file("InputKeyboardEventsSmoke"))
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "probe.gd", probe_script)
            _write_text(project_dir / "main.gd", main_script)
            _write_text(project_dir / "main.tscn", _MAIN_SCENE)
            self._run_project(project_dir, "INPUT_KEYBOARD_EVENTS_SMOKE_OK")

    def test_mouse_events_follow_gamemaker_order_and_enter_leave(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        probe_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var id = GMRuntime.gml_instance_noone()
            var object_name = ""
            var over = true

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, object_name, [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _gm_input_contains_point(_x, _y):
            \treturn over

            func _gm_input_event_bindings():
            \treturn [
            \t\t{"event_type": 6, "event_num": 0, "method": "_left_held"},
            \t\t{"event_type": 6, "event_num": 3, "method": "_no_button"},
            \t\t{"event_type": 6, "event_num": 4, "method": "_left_pressed"},
            \t\t{"event_type": 6, "event_num": 7, "method": "_left_released"},
            \t\t{"event_type": 6, "event_num": 10, "method": "_enter"},
            \t\t{"event_type": 6, "event_num": 11, "method": "_leave"},
            \t\t{"event_type": 6, "event_num": 53, "method": "_global_left_pressed"},
            \t\t{"event_type": 6, "event_num": 60, "method": "_wheel_up"},
            \t]

            """
        ) + _LOG_HELPER + textwrap.dedent(
            """\

            func _left_held():
            \t_log("held")

            func _no_button():
            \t_log("none")

            func _left_pressed():
            \t_log("pressed")

            func _left_released():
            \t_log("released")

            func _enter():
            \t_log("enter")

            func _leave():
            \t_log("leave")

            func _global_left_pressed():
            \t_log("global_pressed")

            func _wheel_up():
            \t_log("wheel_up")
            """
        )
        main_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const Probe = preload("res://probe.gd")

            var probes = {}
            var frames = []
            var tick = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _ready():
            \t# B1 is created first, but o_a has the lower object index.
            \tfor setup in [["B1", "o_b"], ["A1", "o_a"], ["A2", "o_a"]]:
            \t\tvar probe = Probe.new()
            \t\tprobe.name = setup[0]
            \t\tprobe.object_name = setup[1]
            \t\tadd_child(probe)
            \t\tprobes[setup[0]] = probe

            func _button(button_index, pressed):
            \tvar event = InputEventMouseButton.new()
            \tevent.button_index = button_index
            \tevent.pressed = pressed
            \tevent.position = Vector2(4, 4)
            \tget_viewport().push_input(event)

            func _process(_delta):
            \ttick += 1
            \tvar scope = GMRuntime.gml_global_scope()
            \tframes.append(scope.get("log", []))
            \tscope["log"] = []
            \tmatch tick:
            \t\t2:
            \t\t\t_button(MOUSE_BUTTON_LEFT, true)
            \t\t3:
            \t\t\tprobes["A1"].over = false
            \t\t\t_button(MOUSE_BUTTON_LEFT, false)
            \t\t4:
            \t\t\t_button(MOUSE_BUTTON_WHEEL_UP, true)
            \t\t\t_button(MOUSE_BUTTON_WHEEL_UP, false)
            \t\t5:
            \t\t\tprobes["A1"].over = true
            \t\t6:
            \t\t\t_verify()

            func _expect_frame(index, expected):
            \treturn _check(frames[index] == expected, "step " + str(index + 1) + " events: " + str(frames[index]) + ", expected " + str(expected))

            func _verify():
            \t# Object by object in object index order, newest instance first;
            \t# Mouse Enter runs once, when the mouse first is over the instance.
            \tif not _expect_frame(0, ["A2:none", "A2:enter", "A1:none", "A1:enter", "B1:none", "B1:enter"]):
            \t\treturn
            \tif not _expect_frame(1, ["A2:none", "A1:none", "B1:none"]):
            \t\treturn
            \t# Held, then pressed button events; global events in instance order.
            \tif not _expect_frame(2, ["A2:held", "A2:pressed", "A1:held", "A1:pressed", "B1:held", "B1:pressed", "B1:global_pressed", "A1:global_pressed", "A2:global_pressed"]):
            \t\treturn
            \t# The released step: no button is held or pressed, so <No Button>
            \t# runs too; A1 is no longer under the mouse and leaves once.
            \tif not _expect_frame(3, ["A2:released", "A2:none", "A1:leave", "B1:released", "B1:none"]):
            \t\treturn
            \tif not _expect_frame(4, ["A2:none", "B1:none", "B1:wheel_up", "A1:wheel_up", "A2:wheel_up"]):
            \t\treturn
            \tif not _expect_frame(5, ["A2:none", "A1:none", "A1:enter", "B1:none"]):
            \t\treturn
            \tprint("INPUT_MOUSE_EVENTS_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        entries = tuple(
            AssetRegistryEntry(
                id=asset_id,
                name=name,
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path=f"objects/{name}/{name}.yy",
                godot_path=f"res://objects/{name}/{name}.tscn",
                legacy_id=f"objects/{name}/{name}.yy",
            )
            for asset_id, name in ((10, "o_a"), (11, "o_b"))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(project_dir / "project.godot", _project_file("InputMouseEventsSmoke"))
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "probe.gd", probe_script)
            _write_text(project_dir / "main.gd", main_script)
            _write_text(project_dir / "main.tscn", _MAIN_SCENE)
            self._run_project(project_dir, "INPUT_MOUSE_EVENTS_SMOKE_OK")

    def test_mouse_events_hit_test_the_collision_mask(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        sprite_scene_paths = {"s_button": "res://sprites/s_button/s_button.tscn"}
        object_script = generate_script_content(
            [
                {"eventType": 0, "eventNum": 0},
                {"eventType": 6, "eventNum": 4},
                {"eventType": 6, "eventNum": 10},
                {"eventType": 6, "eventNum": 11},
            ],
            code_bodies={
                "_ready": transpile_gml_code("hover = 0; clicks = 0;"),
                "_gm_input_mouse_4": transpile_gml_code("clicks += 1;"),
                "_gm_input_mouse_10": transpile_gml_code("hover = 1;"),
                "_gm_input_mouse_11": transpile_gml_code("hover = 0;"),
            },
            instance_variables={"hover", "clicks"},
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name="s_button",
                sprite_scene_paths=sprite_scene_paths,
            ),
            object_runtime=ObjectRuntimeConfig(object_name="o_button"),
        )
        main_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var button = null
            var history = []
            var tick = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _ready():
            \tvar layer = Node2D.new()
            \tlayer.name = "Instances"
            \tadd_child(layer)
            \tvar handle = GMRuntime.gml_instance_create_layer(100, 100, "Instances", GMRuntime.gml_asset_get_index("o_button"), self)
            \tbutton = GMRuntime.gml_handle_resolve(handle)

            func _mouse(position, button_index = MOUSE_BUTTON_NONE, pressed = false):
            \tvar event = null
            \tif button_index == MOUSE_BUTTON_NONE:
            \t\tevent = InputEventMouseMotion.new()
            \telse:
            \t\tevent = InputEventMouseButton.new()
            \t\tevent.button_index = button_index
            \t\tevent.pressed = pressed
            \tevent.position = position
            \tget_viewport().push_input(event)

            func _process(_delta):
            \ttick += 1
            \thistory.append([int(button.hover), int(button.clicks)])
            \tmatch tick:
            \t\t1:
            \t\t\t# The 40x8 mask spans x 100..139 and y 100..107 in the room.
            \t\t\t_mouse(Vector2(130, 104))
            \t\t2:
            \t\t\t_mouse(Vector2(130, 104), MOUSE_BUTTON_LEFT, true)
            \t\t3:
            \t\t\t_mouse(Vector2(130, 104), MOUSE_BUTTON_LEFT, false)
            \t\t\t_mouse(Vector2(130, 112))
            \t\t4:
            \t\t\t_mouse(Vector2(130, 112), MOUSE_BUTTON_LEFT, true)
            \t\t6:
            \t\t\t_verify()

            func _verify():
            \tvar expected = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 1], [0, 1]]
            \tif not _check(history == expected, "hover and clicks per step: " + str(history) + ", expected " + str(expected)):
            \t\treturn
            \tprint("INPUT_MOUSE_MASK_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        sprite_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=3 format=3]

            [sub_resource type="PlaceholderTexture2D" id="texture"]
            size = Vector2(40, 8)

            [sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]
            size = Vector2(40, 8)

            [node name="s_button" type="Area2D"]
            metadata/gamemaker_width = 40
            metadata/gamemaker_height = 8
            metadata/gamemaker_origin_x = 0
            metadata/gamemaker_origin_y = 0
            metadata/gamemaker_collision_kind = 1
            metadata/gamemaker_collision_tolerance = 0
            metadata/gamemaker_bbox_left = 0
            metadata/gamemaker_bbox_right = 39
            metadata/gamemaker_bbox_top = 0
            metadata/gamemaker_bbox_bottom = 7

            [node name="Sprite2D" type="Sprite2D" parent="."]
            texture = SubResource("texture")
            position = Vector2(20.0, 4.0)

            [node name="CollisionShape2D" type="CollisionShape2D" parent="."]
            shape = SubResource("RectangleShape2D_1")
            position = Vector2(20.0, 4.0)
            """
        )
        object_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=3 format=3]

            [ext_resource type="PackedScene" path="res://sprites/s_button/s_button.tscn" id="1"]
            [ext_resource type="Script" path="res://objects/o_button/o_button.gd" id="2"]

            [node name="o_button" type="Node2D"]
            script = ExtResource("2")

            [node name="s_button" parent="." instance=ExtResource("1")]
            """
        )
        entries = (
            AssetRegistryEntry(
                id=400,
                name="s_button",
                kind="sprites",
                asset_type="sprite",
                type_name="Sprite",
                source_path="sprites/s_button/s_button.yy",
                godot_path=sprite_scene_paths["s_button"],
                legacy_id="sprites/s_button/s_button.yy",
                metadata={"frame_count": 1, "playback_speed": 15.0, "playback_speed_type": 0},
            ),
            AssetRegistryEntry(
                id=401,
                name="o_button",
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path="objects/o_button/o_button.yy",
                godot_path="res://objects/o_button/o_button.tscn",
                legacy_id="objects/o_button/o_button.yy",
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(project_dir / "project.godot", _project_file("InputMouseMaskSmoke"))
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "sprites" / "s_button" / "s_button.tscn", sprite_scene)
            _write_text(project_dir / "objects" / "o_button" / "o_button.gd", object_script)
            _write_text(project_dir / "objects" / "o_button" / "o_button.tscn", object_scene)
            _write_text(project_dir / "main.gd", main_script)
            _write_text(project_dir / "main.tscn", _MAIN_SCENE)
            self._run_project(project_dir, "INPUT_MOUSE_MASK_SMOKE_OK")


if __name__ == "__main__":
    unittest.main()
