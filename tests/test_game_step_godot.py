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
from src.conversion.json_values import JsonObject
from src.conversion.path_registry import (
    PathPoint,
    PathRegistryEntry,
    render_path_registry_script,
)
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


def _event(event_type: int, event_num: int) -> JsonObject:
    return {"eventType": event_type, "eventNum": event_num}


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
            \t# A change requested by a Draw event happens right after the draw;
            \t# the new room steps and draws in the same frame.
            \tvar draw_goto_frame = _frame_of(log, "Q:goto_from_draw")
            \tvar expected_draw_frame = [
            \t\t"Q:begin", "Q:step", "Q:end", "Q:draw_gui", "Q:goto_from_draw",
            \t\t"Q:room_end",
            \t\t"P1:create", "P2:create", "P1:room_start", "P2:room_start",
            \t\t"P1:begin", "P2:begin", "P1:step", "P2:step", "P1:end", "P2:end", "P1:draw_gui", "P2:draw_gui",
            \t]
            \tif not _check(_in_frame(log, draw_goto_frame) == expected_draw_frame, "room change requested in Draw: " + str(_in_frame(log, draw_goto_frame))):
            \t\treturn
            \tvar after = _in_frame(log, draw_goto_frame + 1)
            \tif not _check(after == ["P1:begin", "P2:begin", "P1:step", "P2:step", "P1:end", "P2:end", "P1:draw_gui", "P2:draw_gui"], "frame after the change: " + str(after)):
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

    def test_room_change_from_path_end_keeps_the_other_events_of_persistent_instances(self) -> None:
        # GameMaker moves every instance (running Path End events) and then
        # runs HandleOther before it checks for a room change. After a Path
        # End event called room_goto(), only persistent instances still get
        # their Path End and Outside Room events, and the step ends there.
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        asset_names = {"r_first", "r_second", "path_in", "path_out"}

        def log(what: str) -> str:
            return f'array_push(global.events, room_get_name(room) + ":{what}");\n'

        def object_script(name: str, path: str, events: dict[tuple[int, int], str], *, persistent: bool = False, create: str = "") -> str:
            event_list = [_event(0, 0)] + [_event(kind, num) for kind, num in events]
            method_names = {(7, 8): "_on_path_ended", (7, 0): "_on_outside_room", (3, 2): "_on_end_step", (8, 64): "_on_draw_gui"}
            code_bodies = {
                "_ready": transpile_gml_code(create + f"path_start({path}, 20, 0, true);\n", asset_names=asset_names),
            }
            for key, body in events.items():
                code_bodies[method_names[key]] = transpile_gml_code(body, asset_names=asset_names)
            return generate_script_content(
                event_list,
                code_bodies=code_bodies,
                object_runtime=ObjectRuntimeConfig(object_name=name, persistent=persistent),
            )

        # Instances are created, and move, in this order. Every path is 20
        # pixels long and ends in the first step at speed 20.
        objects = {
            "o_walker": object_script(
                "o_walker",
                "path_in",
                {(7, 8): log("walker_path_end") + "room_goto(r_second);\n"},
                create="global.events = [];\n",
            ),
            "o_follower": object_script("o_follower", "path_in", {(7, 8): log("follower_path_end")}),
            "o_keeper": object_script(
                "o_keeper",
                "path_out",
                {
                    (7, 8): log("keeper_path_end"),
                    (7, 0): log("keeper_outside"),
                    (3, 2): log("keeper_end_step"),
                    (8, 64): log("keeper_draw_gui"),
                },
                persistent=True,
            ),
            "o_drifter": object_script(
                "o_drifter",
                "path_out",
                {(7, 0): log("drifter_outside"), (3, 2): log("drifter_end_step")},
            ),
        }
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
            \tvar events = GMRuntime.gml_global_scope().get("events", [])
            \tvar first_room = []
            \tfor event in events:
            \t\tif str(event).begins_with("r_first:"):
            \t\t\tfirst_room.append(str(event))
            \tvar expected = ["r_first:walker_path_end", "r_first:keeper_path_end", "r_first:keeper_outside"]
            \tif not _check(first_room == expected, "events of the step that requested the change: " + str(first_room)):
            \t\treturn
            \tif not _check(events.has("r_second:keeper_end_step") and events.has("r_second:keeper_draw_gui"), "the persistent instance did not carry on in the new room: " + str(events)):
            \t\treturn
            \tprint("GAME_STEP_PATH_END_ROOM_CHANGE_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        instance_nodes = "".join(
            f'\n[node name="inst_{name}" parent="." instance=ExtResource("{name}")]\n' for name in objects
        )
        first_room = (
            textwrap.dedent(
                f"""\
                [gd_scene load_steps={len(objects) + 2} format=3]

                [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]
                """
            )
            + "".join(
                f'[ext_resource type="PackedScene" path="res://objects/{name}/{name}.tscn" id="{name}"]\n'
                for name in objects
            )
            + textwrap.dedent(
                """\

                [node name="r_first" type="Node2D"]
                script = ExtResource("room")
                metadata/gamemaker_room_width = 320
                metadata/gamemaker_room_height = 180
                metadata/gamemaker_room_persistent = false
                """
            )
            + instance_nodes
        )
        second_room = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]

            [node name="r_second" type="Node2D"]
            script = ExtResource("room")
            metadata/gamemaker_room_width = 320
            metadata/gamemaker_room_height = 180
            metadata/gamemaker_room_persistent = false
            """
        )
        path_points = {"path_in": (PathPoint(10, 10), PathPoint(30, 10)), "path_out": (PathPoint(10, 10), PathPoint(-10, 10))}
        entries = (
            tuple(
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
            + tuple(
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
                for order, name in enumerate(objects)
            )
            + tuple(
                AssetRegistryEntry(
                    id=300 + order,
                    name=name,
                    kind="paths",
                    asset_type="path",
                    type_name="Path",
                    source_path=f"paths/{name}/{name}.yy",
                    godot_path=f"res://paths/{name}/{name}.tscn",
                    legacy_id=f"paths/{name}/{name}.yy",
                )
                for order, name in enumerate(path_points)
            )
        )
        paths = tuple(
            PathRegistryEntry(
                id=300 + order,
                name=name,
                closed=False,
                kind=0,
                precision=4,
                godot_path=f"res://paths/{name}/{name}.tscn",
                points=points,
            )
            for order, (name, points) in enumerate(path_points.items())
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                _project_file("GameStepPathEndRoomChangeSmoke", "res://rooms/r_first/r_first.tscn")
                + '\n[autoload]\n\nChecker="*res://checker.gd"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "gm2godot" / "gml_path_registry.gd", render_path_registry_script(paths))
            _write_text(project_dir / "checker.gd", checker_script)
            for name, script in objects.items():
                _write_text(project_dir / "objects" / name / f"{name}.gd", script)
                _write_text(project_dir / "objects" / name / f"{name}.tscn", _scene(name, f"res://objects/{name}/{name}.gd"))
            _write_text(project_dir / "rooms" / "r_first" / "r_first.tscn", first_room)
            _write_text(project_dir / "rooms" / "r_second" / "r_second.tscn", second_room)
            self._run_project(project_dir, "res://rooms/r_first/r_first.tscn", "GAME_STEP_PATH_END_ROOM_CHANGE_SMOKE_OK")

    def test_delta_time_and_get_timer_follow_the_step_clock(self) -> None:
        # GameMaker_DoAStep sets delta_time to the microseconds since the
        # previous step on the tick clock, so the new room's first step,
        # which runs in the tick of the room change, sees 0. get_timer()
        # counts the microseconds the game has been running.
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        asset_names = {"r_second"}
        go_script = generate_script_content(
            [{"eventType": 3, "eventNum": 0}],
            code_bodies={"_on_step": transpile_gml_code("room_goto(r_second);", asset_names=asset_names)},
            object_runtime=ObjectRuntimeConfig(object_name="o_go"),
        )
        clock_script = generate_script_content(
            [{"eventType": 0, "eventNum": 0}, {"eventType": 3, "eventNum": 0}],
            code_bodies={
                "_ready": transpile_gml_code("global.deltas = []; global.timers = [];"),
                "_on_step": transpile_gml_code(
                    "array_push(global.deltas, delta_time);\n"
                    "array_push(global.timers, get_timer());\n"
                ),
            },
            object_runtime=ObjectRuntimeConfig(object_name="o_clock"),
        )
        checker_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _process(_delta):
            \tvar deltas = GMRuntime.gml_global_scope().get("deltas", [])
            \tif deltas.size() < 6:
            \t\tif Engine.get_process_frames() > 60:
            \t\t\t_check(false, "the clock object did not step: " + str(deltas))
            \t\treturn
            \tvar timers = GMRuntime.gml_global_scope()["timers"]
            \tfor value in deltas + timers:
            \t\tif not _check(typeof(value) == TYPE_INT, "delta_time or get_timer() is not an integer: " + str(deltas) + " " + str(timers)):
            \t\t\treturn
            \tif not _check(deltas[0] == 0, "the step after a room change in the same tick did not get delta_time 0: " + str(deltas)):
            \t\treturn
            \tvar total = 0
            \tfor index in range(1, deltas.size()):
            \t\tif not _check(deltas[index] > 0, "a step in a later frame got delta_time 0: " + str(deltas)):
            \t\t\treturn
            \t\tif not _check(timers[index] > timers[index - 1], "get_timer() did not advance: " + str(timers)):
            \t\t\treturn
            \t\t# The tick of the room change also loaded the new room, which
            \t\t# the next delta_time includes, as in GameMaker; the sum
            \t\t# starts after it.
            \t\tif index >= 2:
            \t\t\ttotal += deltas[index]
            \tvar elapsed = timers[-1] - timers[1]
            \tif not _check(abs(elapsed - total) < 20000, "delta_time does not add up to the get_timer() time: " + str(total) + " vs " + str(elapsed)):
            \t\treturn
            \tif not _check(GMRuntime.gml_get_timer() >= timers[-1], "get_timer() went back"):
            \t\treturn
            \tprint("GAME_STEP_DELTA_TIME_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        rooms = {
            "r_first": ("o_go", "inst_go"),
            "r_second": ("o_clock", "inst_clock"),
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
            for order, name in enumerate(("o_go", "o_clock"))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                _project_file("GameStepDeltaTimeSmoke", "res://rooms/r_first/r_first.tscn")
                + '\n[autoload]\n\nChecker="*res://checker.gd"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
            _write_text(project_dir / "checker.gd", checker_script)
            for name, script in (("o_go", go_script), ("o_clock", clock_script)):
                _write_text(project_dir / "objects" / name / f"{name}.gd", script)
                _write_text(project_dir / "objects" / name / f"{name}.tscn", _scene(name, f"res://objects/{name}/{name}.gd"))
            for room_name, (object_name, instance_name) in rooms.items():
                _write_text(
                    project_dir / "rooms" / room_name / f"{room_name}.tscn",
                    _room_scene(room_name, object_name, instance_name),
                )
            self._run_project(project_dir, "res://rooms/r_first/r_first.tscn", "GAME_STEP_DELTA_TIME_SMOKE_OK")

    def test_room_speed_is_the_game_speed_from_the_project(self) -> None:
        # room_speed reads and writes GameMaker's game timer (yyBuiltIn.js
        # get_room_speed/set_room_speed), which starts at the project's game
        # speed; game_set_speed takes steps per second or microseconds per
        # step (Function_Game.js).
        if _find_godot_binary() is None:
            self.skipTest("Godot binary not available")
        speed_script = generate_script_content(
            [{"eventType": 0, "eventNum": 0}],
            code_bodies={
                "_ready": transpile_gml_code(
                    "global.speeds = [room_speed, game_get_speed(gamespeed_fps), game_get_speed(gamespeed_microseconds)];\n"
                    "room_speed = 20;\n"
                    "array_push(global.speeds, room_speed, game_get_speed(gamespeed_fps));\n"
                    "room_speed += 4;\n"
                    "array_push(global.speeds, game_get_speed(gamespeed_fps));\n"
                    "game_set_speed(40000, gamespeed_microseconds);\n"
                    "array_push(global.speeds, room_speed, game_get_speed(gamespeed_microseconds));\n"
                    "game_set_speed(-1, gamespeed_fps);\n"
                    "array_push(global.speeds, room_speed);\n"
                    "game_set_speed(50, gamespeed_fps);\n"
                ),
            },
            object_runtime=ObjectRuntimeConfig(object_name="o_speed"),
        )
        checker_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var max_fps_seen = []

            """
        ) + _CHECK_HELPER + textwrap.dedent(
            """\

            func _process(_delta):
            \tvar speeds = GMRuntime.gml_global_scope().get("speeds", [])
            \tif speeds.is_empty():
            \t\tif Engine.get_process_frames() > 30:
            \t\t\t_check(false, "the speed object did not run its Create event")
            \t\treturn
            \tvar project_speed = float(ProjectSettings.get_setting("application/run/max_fps"))
            \tvar expected = [project_speed, project_speed, 1000000.0 / project_speed, 20.0, 20.0, 24.0, 25.0, 40000.0, 25.0]
            \tif not _check(speeds == expected, "game speeds were " + str(speeds) + ", expected " + str(expected)):
            \t\treturn
            \tif not _check(Engine.max_fps == 50 and GMRuntime.gml_builtin_global("room_speed") == 50.0, "game_set_speed did not set the frame rate: " + str(Engine.max_fps)):
            \t\treturn
            \tif not _check(GMRuntime.gml_string(GMRuntime.gml_builtin_global("room_speed")) == "50", "room_speed does not print as a whole number"):
            \t\treturn
            \tprint("GAME_SPEED_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )
        entries = (
            AssetRegistryEntry(
                id=100,
                name="r_speed",
                kind="rooms",
                asset_type="room",
                type_name="Room",
                source_path="rooms/r_speed/r_speed.yy",
                godot_path="res://rooms/r_speed/r_speed.tscn",
                legacy_id="rooms/r_speed/r_speed.yy",
                metadata={"room_order": 0, "width": 320, "height": 180, "persistent": False, "volume": 1.0},
            ),
            AssetRegistryEntry(
                id=200,
                name="o_speed",
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path="objects/o_speed/o_speed.yy",
                godot_path="res://objects/o_speed/o_speed.tscn",
                legacy_id="objects/o_speed/o_speed.yy",
            ),
        )
        for project_speed in (30, 45):
            with self.subTest(project_speed=project_speed), tempfile.TemporaryDirectory() as tmpdir:
                project_dir = Path(tmpdir)
                _write_text(
                    project_dir / "project.godot",
                    _project_file("GameSpeedSmoke", "res://rooms/r_speed/r_speed.tscn").replace(
                        "[application]\n", f"[application]\nrun/max_fps={project_speed}\n"
                    )
                    + '\n[autoload]\n\nChecker="*res://checker.gd"\n',
                )
                write_gml_runtime(str(project_dir))
                _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
                _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
                _write_text(project_dir / "checker.gd", checker_script)
                _write_text(project_dir / "objects" / "o_speed" / "o_speed.gd", speed_script)
                _write_text(
                    project_dir / "objects" / "o_speed" / "o_speed.tscn",
                    _scene("o_speed", "res://objects/o_speed/o_speed.gd"),
                )
                _write_text(
                    project_dir / "rooms" / "r_speed" / "r_speed.tscn",
                    _room_scene("r_speed", "o_speed", "inst_speed"),
                )
                self._run_project(project_dir, "res://rooms/r_speed/r_speed.tscn", "GAME_SPEED_SMOKE_OK")

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
            var spriteless = null
            var spriteless_history = []
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
            \t# Without a sprite image_index still advances by image_speed.
            \tspriteless = GMRuntime.gml_handle_resolve(GMRuntime.gml_instance_create_layer(0, 0, "Instances", GMRuntime.gml_asset_get_index("o_anim"), self))
            \tspriteless.image_speed = 0.5
            \tspriteless.sprite_index = -1
            \tif not _check(spriteless.image_number == 0, "image_number without a sprite"):
            \t\treturn

            func _visual(probe):
            \treturn probe._gm_sprite_visual_node()

            func _process(_delta):
            \ttick += 1
            \tfor key in probes.keys():
            \t\tvar probe = probes[key]
            \t\tvar visual = _visual(probe)
            \t\thistory[key].append([probe.image_index, visual.frame, int(probe.ended), visual.is_playing(), probe.image_number])
            \tspriteless_history.append([spriteless.image_index, spriteless.image_number, int(spriteless.ended)])
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
            \tif not _check(spriteless_history[9] == [5.0, 0, 0], "sprite-less instance after 10 steps: " + str(spriteless_history[9])):
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


def _room_scene(room_name: str, object_name: str, instance_name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=3 format=3]

        [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="room"]
        [ext_resource type="PackedScene" path="res://objects/{object_name}/{object_name}.tscn" id="object"]

        [node name="{room_name}" type="Node2D"]
        script = ExtResource("room")
        metadata/gamemaker_room_width = 320
        metadata/gamemaker_room_height = 180
        metadata/gamemaker_room_persistent = false

        [node name="{instance_name}" parent="." instance=ExtResource("object")]
        """
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
