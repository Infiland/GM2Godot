"""Godot smoke tests for the GameMaker step loop driven by the GMEvents pump.

They run real Godot frames with the runtime manager autoloads, so the step
order, input latching, image animation and room-change abort are checked
the way a converted game runs them.
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
from src.conversion.rooms import render_room_runtime_script
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


def _scene(name: str, script_path: str, root_type: str = "Node2D") -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="{script_path}" id="1"]

        [node name="{name}" type="{root_type}"]
        script = ExtResource("1")
        """
    )


def _project_file(name: str, main_scene: str) -> str:
    return f'[application]\nconfig/name="{name}"\nrun/main_scene="{main_scene}"\n'


class TestGameStepGodotSmoke(unittest.TestCase):
    def _run_project(self, project_dir: Path, scene: str, marker: str) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        try:
            result = run_headless_scene(godot_binary, project_dir, scene, timeout=60)
        except subprocess.TimeoutExpired as exc:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
            self.fail("Godot game-step smoke timed out\n" + output)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(marker, result.stdout)
        self.assertNotIn("SCRIPT ERROR", result.stdout)

    def test_step_phases_and_latched_input_edges(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        probe_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var id = GMRuntime.gml_instance_noone()
            var xprevious = 0.0
            var yprevious = 0.0
            var records = []
            var step_no = 0

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, "o_probe", [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _gm_input_event_bindings():
            \treturn [
            \t\t{"event_type": 5, "event_num": KEY_A, "method": "_on_key_held_a"},
            \t\t{"event_type": 9, "event_num": KEY_A, "method": "_on_key_pressed_a"},
            \t\t{"event_type": 10, "event_num": KEY_A, "method": "_on_key_released_a"},
            \t]

            func keys():
            \treturn [
            \t\tint(GMRuntime.gml_keyboard_check_pressed(KEY_A)),
            \t\tint(GMRuntime.gml_keyboard_check(KEY_A)),
            \t\tint(GMRuntime.gml_keyboard_check_released(KEY_A)),
            \t\tint(GMRuntime.gml_keyboard_check_pressed(KEY_B)),
            \t\tint(GMRuntime.gml_keyboard_check(KEY_B)),
            \t\tint(GMRuntime.gml_keyboard_check_released(KEY_B)),
            \t]

            func _record(phase):
            \trecords.append({"step": step_no, "phase": phase, "keys": keys()})

            func _on_begin_step():
            \tstep_no += 1
            \t_record("begin_step")
            \trecords[-1]["previous"] = [xprevious, position.x]
            \tposition.x += 3.0
            \tif GMRuntime.gml_keyboard_check_pressed(KEY_A):
            \t\tGMRuntime.gml_alarm_set(self, 0, 1)

            func _on_alarm_0():
            \t_record("alarm_0")

            func _on_key_held_a():
            \t_record("key_held")

            func _on_key_pressed_a():
            \t_record("key_pressed")

            func _on_key_released_a():
            \t_record("key_released")

            func _on_step():
            \t_record("step")

            func _on_end_step():
            \t_record("end_step")
            \trecords[-1]["previous"] = [xprevious, position.x]

            func _on_draw_gui():
            \t_record("draw_gui")
            """
        )
        main_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const Probe = preload("res://probe.gd")

            var probe = null
            var late = []
            var injected = {}
            var tick = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _ready():
            \tprobe = Probe.new()
            \tprobe.name = "Probe"
            \tadd_child(probe)

            func _key(keycode, pressed):
            \tvar event = InputEventKey.new()
            \tevent.keycode = keycode
            \tevent.physical_keycode = keycode
            \tevent.pressed = pressed
            \tget_viewport().push_input(event)

            func _process(_delta):
            \t# Scene nodes process after the GMEvents/GMDraw autoloads, so this
            \t# sees the input state of the step that just ran.
            \ttick += 1
            \tlate.append({"step": probe.step_no, "keys": probe.keys()})
            \tif tick == 2:
            \t\tinjected["a_down"] = probe.step_no
            \t\t_key(KEY_A, true)
            \telif tick == 4:
            \t\tinjected["b_tap"] = probe.step_no
            \t\t_key(KEY_B, true)
            \t\t_key(KEY_B, false)
            \telif tick == 6:
            \t\tinjected["a_up"] = probe.step_no
            \t\t_key(KEY_A, false)
            \telif tick == 9:
            \t\t_verify()

            func _records(step):
            \tvar result = []
            \tfor record in probe.records:
            \t\tif record["step"] == step:
            \t\t\tresult.append(record)
            \treturn result

            func _phases(step):
            \tvar result = []
            \tfor record in _records(step):
            \t\tresult.append(record["phase"])
            \treturn result

            func _late(step):
            \tvar keys = []
            \tfor record in late:
            \t\tif record["step"] == step:
            \t\t\tkeys = record["keys"]
            \treturn keys

            func _all_keys(step, index, expected):
            \tfor record in _records(step):
            \t\tif record["keys"][index] != expected:
            \t\t\treturn false
            \tvar late_keys = _late(step)
            \treturn late_keys.size() > index and late_keys[index] == expected

            func _verify():
            \tvar press_step = injected["a_down"] + 1
            \tif not _check(_phases(press_step) == ["begin_step", "alarm_0", "key_held", "key_pressed", "step", "end_step", "draw_gui"], "step phase order: " + str(_phases(press_step))):
            \t\treturn
            \tif not _check(_all_keys(press_step, 0, 1) and _all_keys(press_step, 1, 1), "pressed A was not visible in every event of its step: " + str(_records(press_step))):
            \t\treturn
            \tif not _check(_all_keys(press_step - 1, 0, 0) and _all_keys(press_step - 1, 1, 0), "A was seen before the step after the key arrived"):
            \t\treturn
            \tif not _check(_all_keys(press_step + 1, 0, 0) and _all_keys(press_step + 1, 1, 1), "pressed A did not clear on the next step"):
            \t\treturn
            \tif not _check(_phases(press_step + 1) == ["begin_step", "key_held", "step", "end_step", "draw_gui"], "held key events: " + str(_phases(press_step + 1))):
            \t\treturn
            \tvar tap_step = injected["b_tap"] + 1
            \tif not _check(_all_keys(tap_step, 3, 1) and _all_keys(tap_step, 4, 0) and _all_keys(tap_step, 5, 1), "press and release between steps were not both reported: " + str(_records(tap_step))):
            \t\treturn
            \tif not _check(_all_keys(tap_step + 1, 3, 0) and _all_keys(tap_step + 1, 5, 0), "B edges lasted more than one step"):
            \t\treturn
            \tvar release_step = injected["a_up"] + 1
            \tif not _check(_all_keys(release_step, 2, 1) and _all_keys(release_step, 1, 0), "released A was not visible in its step: " + str(_records(release_step))):
            \t\treturn
            \tif not _check(_phases(release_step) == ["begin_step", "key_released", "step", "end_step", "draw_gui"], "release event phases: " + str(_phases(release_step))):
            \t\treturn
            \tif not _check(_all_keys(release_step + 1, 2, 0), "released A lasted more than one step"):
            \t\treturn
            \tfor step in range(2, release_step + 1):
            \t\tvar begin = _records(step)[0]
            \t\tvar end = _records(step)[-2]
            \t\tif not _check(begin["previous"][0] == begin["previous"][1], "xprevious was not the position at the start of the step"):
            \t\t\treturn
            \t\tif not _check(end["previous"][0] == begin["previous"][1] and end["previous"][1] == begin["previous"][1] + 3.0, "xprevious changed during the step"):
            \t\t\treturn
            \tprint("GAME_STEP_INPUT_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(project_dir / "project.godot", _project_file("GameStepInputSmoke", "res://main.tscn"))
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "probe.gd", probe_script)
            _write_text(project_dir / "main.gd", main_script)
            _write_text(project_dir / "main.tscn", _scene("Main", "res://main.gd"))
            self._run_project(project_dir, "main.tscn", "GAME_STEP_INPUT_SMOKE_OK")

    def test_room_change_ends_the_step_and_the_new_room_steps_in_the_same_frame(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        probe_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var id = GMRuntime.gml_instance_noone()
            var persistent = false
            var steps = 0
            var draws = 0

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, "o_probe", [])
            \t_log("create")

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _log(what):
            \tvar scope = GMRuntime.gml_global_scope()
            \tif not scope.has("log"):
            \t\tscope["log"] = []
            \tscope["log"].append([Engine.get_process_frames(), str(name) + ":" + what])

            func _on_room_start():
            \t_log("room_start")

            func _on_room_end():
            \t_log("room_end")

            func _on_begin_step():
            \t_log("begin")

            func _on_step():
            \tsteps += 1
            \t_log("step")
            \tvar scope = GMRuntime.gml_global_scope()
            \tif str(name) == "P1" and steps == 3 and not scope.has("left_first_room"):
            \t\tscope["left_first_room"] = true
            \t\t# The last request of the step wins.
            \t\tGMRuntime.gml_room_restart()
            \t\tGMRuntime.gml_room_goto(GMRuntime.gml_asset_get_index("r_second"))
            \t\t_log("goto")

            func _on_end_step():
            \t_log("end")

            func _on_draw_gui():
            \tdraws += 1
            \t_log("draw_gui")
            \tvar scope = GMRuntime.gml_global_scope()
            \tif str(name) == "Q" and draws == 2 and not scope.has("left_second_room"):
            \t\tscope["left_second_room"] = true
            \t\tGMRuntime.gml_room_goto_previous()
            \t\t_log("goto_from_draw")
            """
        )
        checker_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _process(_delta):
            \tvar log = GMRuntime.gml_global_scope().get("log", [])
            \tvar creates = 0
            \tfor entry in log:
            \t\tif entry[1] == "P1:create":
            \t\t\tcreates += 1
            \tif creates < 2 or Engine.get_process_frames() < _frame_of(log, "P1:create", 2) + 3:
            \t\treturn
            \t_verify(log)

            func _frame_of(log, what, occurrence = 1):
            \tvar seen = 0
            \tfor entry in log:
            \t\tif entry[1] == what:
            \t\t\tseen += 1
            \t\t\tif seen == occurrence:
            \t\t\t\treturn entry[0]
            \treturn -1

            func _in_frame(log, frame):
            \tvar result = []
            \tfor entry in log:
            \t\tif entry[0] == frame:
            \t\t\tresult.append(entry[1])
            \treturn result

            func _verify(log):
            \tvar goto_frame = _frame_of(log, "P1:goto")
            \tvar expected = [
            \t\t"P1:begin", "P2:begin", "P1:step", "P1:goto",
            \t\t"P1:room_end", "P2:room_end",
            \t\t"Q:create", "Q:room_start",
            \t\t"Q:begin", "Q:step", "Q:end", "Q:draw_gui",
            \t]
            \tif not _check(_in_frame(log, goto_frame) == expected, "room change frame: " + str(_in_frame(log, goto_frame))):
            \t\treturn
            \tvar before = _in_frame(log, goto_frame - 1)
            \tif not _check(before == ["P1:begin", "P2:begin", "P1:step", "P2:step", "P1:end", "P2:end", "P1:draw_gui", "P2:draw_gui"], "normal frame: " + str(before)):
            \t\treturn
            \tvar draw_goto_frame = _frame_of(log, "Q:goto_from_draw")
            \tif not _check(_in_frame(log, draw_goto_frame) == ["Q:begin", "Q:step", "Q:end", "Q:draw_gui", "Q:goto_from_draw"], "draw frame: " + str(_in_frame(log, draw_goto_frame))):
            \t\treturn
            \tvar after = _in_frame(log, draw_goto_frame + 1)
            \tvar expected_after = [
            \t\t"Q:room_end",
            \t\t"P1:create", "P2:create", "P1:room_start", "P2:room_start",
            \t\t"P1:begin", "P2:begin", "P1:step", "P2:step", "P1:end", "P2:end", "P1:draw_gui", "P2:draw_gui",
            \t]
            \tif not _check(after == expected_after, "room change requested in Draw did not happen before the next step: " + str(after)):
            \t\treturn
            \tif not _check(get_tree().current_scene.name == "r_first", "did not return to the first room"):
            \t\treturn
            \tprint("GAME_STEP_ROOM_ABORT_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        first_room = textwrap.dedent(
            """\
            [gd_scene load_steps=3 format=3]

            [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]
            [ext_resource type="Script" path="res://probe.gd" id="probe"]

            [node name="r_first" type="Node2D"]
            script = ExtResource("room")
            metadata/gamemaker_room_width = 320
            metadata/gamemaker_room_height = 180
            metadata/gamemaker_room_persistent = false

            [node name="P1" type="Node2D" parent="."]
            script = ExtResource("probe")

            [node name="P2" type="Node2D" parent="."]
            script = ExtResource("probe")
            """
        )
        second_room = textwrap.dedent(
            """\
            [gd_scene load_steps=3 format=3]

            [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]
            [ext_resource type="Script" path="res://probe.gd" id="probe"]

            [node name="r_second" type="Node2D"]
            script = ExtResource("room")
            metadata/gamemaker_room_width = 320
            metadata/gamemaker_room_height = 180
            metadata/gamemaker_room_persistent = false

            [node name="Q" type="Node2D" parent="."]
            script = ExtResource("probe")
            """
        )
        entries = tuple(
            AssetRegistryEntry(
                id=100 + order,
                name=name,
                kind="rooms",
                asset_type="room",
                type_name="Room",
                source_path=f"rooms/{name}/{name}.yy",
                godot_path=f"res://rooms/{name}/{name}.tscn",
                legacy_id=f"rooms/{name}/{name}.yy",
                metadata={"room_order": order, "width": 320, "height": 180, "persistent": False, "volume": 1.0},
            )
            for order, name in enumerate(("r_first", "r_second"))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                _project_file("GameStepRoomAbortSmoke", "res://rooms/r_first/r_first.tscn")
                + '\n[autoload]\n\nChecker="*res://checker.gd"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "probe.gd", probe_script)
            _write_text(project_dir / "checker.gd", checker_script)
            _write_text(project_dir / "rooms" / "r_first" / "r_first.tscn", first_room)
            _write_text(project_dir / "rooms" / "r_second" / "r_second.tscn", second_room)
            self._run_project(project_dir, "res://rooms/r_first/r_first.tscn", "GAME_STEP_ROOM_ABORT_SMOKE_OK")

    def test_create_and_destroy_after_a_room_change_request_follow_persistence(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        asset_names = {"r_second", "o_spawned", "o_keeper"}
        trigger_script = generate_script_content(
            [
                {"eventType": 0, "eventNum": 0},
                {"eventType": 1, "eventNum": 0},
                {"eventType": 3, "eventNum": 0},
            ],
            code_bodies={
                "_ready": transpile_gml_code("triggered = false;", instance_variables={"triggered"}),
                "_on_destroy": transpile_gml_code("global.trigger_destroyed = true;"),
                "_on_step": transpile_gml_code(
                    "if (!triggered) {\n"
                    "    triggered = true;\n"
                    "    room_goto(r_second);\n"
                    "    instance_create_depth(0, 0, 0, o_spawned);\n"
                    "    global.spawned_exists = instance_exists(o_spawned);\n"
                    "    instance_create_depth(0, 0, 0, o_keeper);\n"
                    "    instance_destroy();\n"
                    "}\n",
                    instance_variables={"triggered"},
                    asset_names=asset_names,
                ),
            },
            instance_variables={"triggered"},
            object_runtime=ObjectRuntimeConfig(object_name="o_trigger"),
        )
        spawned_script = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={"_ready": transpile_gml_code("global.spawned_created = true;")},
            object_runtime=ObjectRuntimeConfig(object_name="o_spawned"),
        )
        keeper_script = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={"_ready": transpile_gml_code("global.keeper_created = true;")},
            object_runtime=ObjectRuntimeConfig(object_name="o_keeper", persistent=True),
        )
        checker_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var frames_in_second_room = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _process(_delta):
            \tvar scene = get_tree().current_scene
            \tif scene == null or str(scene.name) != "r_second":
            \t\tif Engine.get_process_frames() > 30:
            \t\t\t_check(false, "the room change did not happen")
            \t\treturn
            \tframes_in_second_room += 1
            \tif frames_in_second_room < 3:
            \t\treturn
            \tvar scope = GMRuntime.gml_global_scope()
            \tif not _check(bool(scope.get("spawned_exists", false)), "the instance created after room_goto() did not exist"):
            \t\treturn
            \tif not _check(not scope.has("spawned_created"), "Create ran for a non-persistent instance created after room_goto()"):
            \t\treturn
            \tif not _check(bool(scope.get("keeper_created", false)), "Create did not run for a persistent instance"):
            \t\treturn
            \tif not _check(not scope.has("trigger_destroyed"), "Destroy ran after room_goto()"):
            \t\treturn
            \tprint("GAME_STEP_BLOCKED_EVENTS_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        rooms = {
            "r_first": textwrap.dedent(
                """\
                [gd_scene load_steps=3 format=3]

                [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]
                [ext_resource type="PackedScene" path="res://objects/o_trigger/o_trigger.tscn" id="trigger"]

                [node name="r_first" type="Node2D"]
                script = ExtResource("room")
                metadata/gamemaker_room_width = 320
                metadata/gamemaker_room_height = 180
                metadata/gamemaker_room_persistent = false

                [node name="inst_trigger" parent="." instance=ExtResource("trigger")]
                """
            ),
            "r_second": textwrap.dedent(
                """\
                [gd_scene load_steps=2 format=3]

                [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]

                [node name="r_second" type="Node2D"]
                script = ExtResource("room")
                metadata/gamemaker_room_width = 320
                metadata/gamemaker_room_height = 180
                metadata/gamemaker_room_persistent = false
                """
            ),
        }
        entries = tuple(
            AssetRegistryEntry(
                id=100 + order,
                name=name,
                kind="rooms",
                asset_type="room",
                type_name="Room",
                source_path=f"rooms/{name}/{name}.yy",
                godot_path=f"res://rooms/{name}/{name}.tscn",
                legacy_id=f"rooms/{name}/{name}.yy",
                metadata={"room_order": order, "width": 320, "height": 180, "persistent": False, "volume": 1.0},
            )
            for order, name in enumerate(rooms)
        ) + tuple(
            AssetRegistryEntry(
                id=200 + order,
                name=name,
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path=f"objects/{name}/{name}.yy",
                godot_path=f"res://objects/{name}/{name}.tscn",
                legacy_id=f"objects/{name}/{name}.yy",
            )
            for order, name in enumerate(("o_trigger", "o_spawned", "o_keeper"))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                _project_file("GameStepBlockedEventsSmoke", "res://rooms/r_first/r_first.tscn")
                + '\n[autoload]\n\nChecker="*res://checker.gd"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "checker.gd", checker_script)
            for name, script in (("o_trigger", trigger_script), ("o_spawned", spawned_script), ("o_keeper", keeper_script)):
                _write_text(project_dir / "objects" / name / f"{name}.gd", script)
                _write_text(project_dir / "objects" / name / f"{name}.tscn", _scene(name, f"res://objects/{name}/{name}.gd"))
            for name, scene in rooms.items():
                _write_text(project_dir / "rooms" / name / f"{name}.tscn", scene)
            self._run_project(project_dir, "res://rooms/r_first/r_first.tscn", "GAME_STEP_BLOCKED_EVENTS_SMOKE_OK")

    def test_image_index_advances_by_sprite_playback_speed(self) -> None:
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        sprite_scene_paths = {
            "s_four": "res://sprites/s_four/s_four.tscn",
            "s_two": "res://sprites/s_two/s_two.tscn",
        }
        object_script = generate_script_content(
            [{"eventType": 0, "eventNum": 0}, {"eventType": 7, "eventNum": 7}],
            code_bodies={
                "_ready": transpile_gml_code("ended = 0;"),
                "_on_animation_end": transpile_gml_code("ended += 1;"),
            },
            instance_variables={"ended"},
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name="s_four",
                sprite_scene_paths=sprite_scene_paths,
            ),
            object_runtime=ObjectRuntimeConfig(object_name="o_anim"),
        )
        main_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var probes = {}
            var history = {}
            var tick = 0

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _ready():
            \tGMRuntime.gml_game_set_speed(60, 0)
            \tif not _check(GMRuntime.gml_image_frame_for_index(-0.5, 4) == 0, "frame for -0.5"):
            \t\treturn
            \tif not _check(GMRuntime.gml_image_frame_for_index(-1.5, 4) == 3, "frame for -1.5"):
            \t\treturn
            \tif not _check(GMRuntime.gml_image_frame_for_index(5.9, 4) == 1, "frame for 5.9"):
            \t\treturn
            \tif not _check(GMRuntime.gml_image_frame_for_index(3, 0) == 0, "frame without sub-images"):
            \t\treturn
            \tvar layer = Node2D.new()
            \tlayer.name = "Instances"
            \tadd_child(layer)
            \tfor setup in [["fps", 1.0], ["half", 0.5], ["backwards", -1.0], ["still", 0.0], ["frames", 1.0], ["switch", 1.0]]:
            \t\tvar handle = GMRuntime.gml_instance_create_layer(0, 0, "Instances", GMRuntime.gml_asset_get_index("o_anim"), self)
            \t\tvar probe = GMRuntime.gml_handle_resolve(handle)
            \t\tprobe.image_speed = setup[1]
            \t\tprobes[setup[0]] = probe
            \t\thistory[setup[0]] = []
            \tprobes["frames"].sprite_index = GMRuntime.gml_asset_get_index("s_two")
            \tif not _check(probes["fps"].sprite_index == GMRuntime.gml_asset_get_index("s_four"), "sprite_index does not hold the sprite's asset index"):
            \t\treturn
            \tif not _check(probes["fps"].image_number == 4 and probes["frames"].image_number == 2, "image_number does not follow the sprite"):
            \t\treturn

            func _visual(probe):
            \treturn probe._gm_sprite_visual_node()

            func _process(_delta):
            \ttick += 1
            \tfor key in probes.keys():
            \t\tvar probe = probes[key]
            \t\tvar visual = _visual(probe)
            \t\thistory[key].append([probe.image_index, visual.frame, int(probe.ended), visual.is_playing(), probe.image_number])
            \tif tick == 3:
            \t\tprobes["switch"].sprite_index = GMRuntime.gml_asset_get_index("s_two")
            \t\thistory["switch"].append([probes["switch"].image_index, _visual(probes["switch"]).frame, int(probes["switch"].ended), false, probes["switch"].image_number])
            \tif tick == 18:
            \t\t_verify()

            func _expect(key, index, expected):
            \tvar row = history[key][index]
            \treturn _check(is_equal_approx(float(row[0]), float(expected[0])) and row[1] == expected[1] and row[2] == expected[2] and not row[3], key + " step " + str(index + 1) + " was " + str(row) + ", expected " + str(expected))

            func _verify():
            \t# 15 FPS sprite at 60 steps per second: 0.25 sub-images per step.
            \tfor step in range(15):
            \t\tif not _expect("fps", step, [0.25 * (step + 1), int(0.25 * (step + 1)), 0]):
            \t\t\treturn
            \tif not _expect("fps", 15, [0.0, 0, 1]):
            \t\treturn
            \tif not _expect("fps", 16, [0.25, 0, 1]):
            \t\treturn
            \tif not _expect("half", 7, [1.0, 1, 0]):
            \t\treturn
            \tif not _expect("half", 2, [0.375, 0, 0]):
            \t\treturn
            \t# Backwards animation wraps below zero and also ends the animation.
            \tif not _expect("backwards", 0, [3.75, 3, 1]):
            \t\treturn
            \tif not _expect("backwards", 3, [3.0, 3, 1]):
            \t\treturn
            \tif not _expect("backwards", 4, [2.75, 2, 1]):
            \t\treturn
            \tif not _expect("still", 10, [0.0, 0, 0]):
            \t\treturn
            \t# s_two plays 0.5 sub-images per game frame.
            \tif not _expect("frames", 0, [0.5, 0, 0]):
            \t\treturn
            \tif not _expect("frames", 2, [1.5, 1, 0]):
            \t\treturn
            \tif not _expect("frames", 3, [0.0, 0, 1]):
            \t\treturn
            \t# Changing sprite_index keeps image_index and uses the new sprite.
            \tif not _expect("switch", 2, [0.75, 0, 0]):
            \t\treturn
            \tif not _expect("switch", 3, [0.75, 0, 0]):
            \t\treturn
            \tif not _check(history["switch"][3][4] == 2, "image_number did not follow the new sprite"):
            \t\treturn
            \tif not _expect("switch", 4, [1.25, 1, 0]):
            \t\treturn
            \tif not _expect("switch", 6, [0.25, 0, 1]):
            \t\treturn
            \tprint("GAME_STEP_ANIMATION_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        entries = (
            AssetRegistryEntry(
                id=300,
                name="s_four",
                kind="sprites",
                asset_type="sprite",
                type_name="Sprite",
                source_path="sprites/s_four/s_four.yy",
                godot_path=sprite_scene_paths["s_four"],
                legacy_id="sprites/s_four/s_four.yy",
                metadata={"frame_count": 4, "playback_speed": 15.0, "playback_speed_type": 0},
            ),
            AssetRegistryEntry(
                id=301,
                name="s_two",
                kind="sprites",
                asset_type="sprite",
                type_name="Sprite",
                source_path="sprites/s_two/s_two.yy",
                godot_path=sprite_scene_paths["s_two"],
                legacy_id="sprites/s_two/s_two.yy",
                metadata={"frame_count": 2, "playback_speed": 0.5, "playback_speed_type": 1},
            ),
            AssetRegistryEntry(
                id=302,
                name="o_anim",
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path="objects/o_anim/o_anim.yy",
                godot_path="res://objects/o_anim/o_anim.tscn",
                legacy_id="objects/o_anim/o_anim.yy",
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(project_dir / "project.godot", _project_file("GameStepAnimationSmoke", "res://main.tscn"))
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            for sprite_name, frame_count in (("s_four", 4), ("s_two", 2)):
                _write_text(
                    project_dir / "sprites" / sprite_name / f"{sprite_name}.tscn",
                    _animated_sprite_scene(sprite_name, frame_count),
                )
            _write_text(project_dir / "objects" / "o_anim" / "o_anim.gd", object_script)
            _write_text(project_dir / "objects" / "o_anim" / "o_anim.tscn", _object_scene("o_anim", "s_four"))
            _write_text(project_dir / "main.gd", main_script)
            _write_text(project_dir / "main.tscn", _scene("Main", "res://main.gd"))
            self._run_project(project_dir, "main.tscn", "GAME_STEP_ANIMATION_SMOKE_OK")


def _animated_sprite_scene(sprite_name: str, frame_count: int) -> str:
    # Like converted sprites, the scene autoplays its frames at a fast Godot
    # speed; object instances must ignore that and follow image_index.
    textures = "".join(
        f'\n[sub_resource type="PlaceholderTexture2D" id="frame_{index}"]\nsize = Vector2(8, 8)\n'
        for index in range(frame_count)
    )
    frames = ", ".join(
        f'{{"duration": 1.0, "texture": SubResource("frame_{index}")}}' for index in range(frame_count)
    )
    return (
        f"[gd_scene load_steps={frame_count + 2} format=3]\n"
        f"{textures}"
        '\n[sub_resource type="SpriteFrames" id="frames"]\n'
        f'animations = [{{"frames": [{frames}], "loop": true, "name": &"default", "speed": 60.0}}]\n'
        f'\n[node name="{sprite_name}" type="Area2D"]\n'
        '\n[node name="AnimatedSprite2D" type="AnimatedSprite2D" parent="."]\n'
        'sprite_frames = SubResource("frames")\n'
        'animation = &"default"\n'
        'autoplay = "default"\n'
    )


def _object_scene(object_name: str, sprite_name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=3 format=3]

        [ext_resource type="PackedScene" path="res://sprites/{sprite_name}/{sprite_name}.tscn" id="1"]
        [ext_resource type="Script" path="res://objects/{object_name}/{object_name}.gd" id="2"]

        [node name="{object_name}" type="Node2D"]
        script = ExtResource("2")

        [node name="{sprite_name}" parent="." instance=ExtResource("1")]
        """
    )


if __name__ == "__main__":
    unittest.main()
