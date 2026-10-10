from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    run_headless_scene,
    write_fixture_text as _write_text,
)


class TestEventSchedulerGodotSmoke(unittest.TestCase):
    def test_scheduler_phase_order_alarms_and_mutation_queue(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        event_instance_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var label = ""
            var trace = []
            var id = GMRuntime.gml_instance_noone()
            var begin_count = 0
            var step_count = 0
            var created_child = false

            func configure(label_value, trace_ref):
            \tlabel = str(label_value)
            \ttrace = trace_ref

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, label, [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _on_begin_step():
            \tbegin_count += 1
            \ttrace.append(label + ":begin" + str(begin_count))
            \tif begin_count == 1:
            \t\tGMRuntime.gml_alarm_set(self, 0, 1)

            func _on_alarm_0():
            \ttrace.append(label + ":alarm0")

            func _on_alarm_1():
            \ttrace.append(label + ":alarm1")

            func _on_step():
            \tstep_count += 1
            \ttrace.append(label + ":step" + str(step_count))
            \tGMRuntime.gml_alarm_set(self, 1, 1)
            \tif label == "A" and not created_child:
            \t\tcreated_child = true
            \t\tvar child = load("res://event_instance.gd").new()
            \t\tchild.configure("C", trace)
            \t\tget_parent().add_child(child)
            \t\ttrace.append("A:createC")
            \tif label == "B" and step_count == 1:
            \t\ttrace.append("B:destroy-request")
            \t\tGMRuntime.gml_instance_destroy(id)

            func _gm_apply_motion_step():
            \ttrace.append(label + ":motion")

            func _on_end_step():
            \ttrace.append(label + ":end")

            func _on_destroy():
            \ttrace.append(label + ":destroy")
            """
        )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const EventInstance = preload("res://event_instance.gd")

            var trace = []

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tGMRuntime.gml_event_scheduler_set_enabled(false)
            \tvar a = EventInstance.new()
            \ta.configure("A", trace)
            \tadd_child(a)
            \tvar b = EventInstance.new()
            \tb.configure("B", trace)
            \tadd_child(b)
            \tGMRuntime.gml_event_scheduler_trace_clear()
            \tGMRuntime.gml_event_scheduler_set_tracing(true)
            \tGMRuntime.gml_event_scheduler_set_enabled(true)
            \tGMRuntime.gml_event_scheduler_frame(0.016, 1)
            \tGMRuntime.gml_event_scheduler_set_enabled(false)

            \tvar expected_first = [
            \t\t"A:begin1",
            \t\t"B:begin1",
            \t\t"A:alarm0",
            \t\t"B:alarm0",
            \t\t"A:step1",
            \t\t"A:createC",
            \t\t"B:step1",
            \t\t"B:destroy-request",
            \t\t"B:destroy",
            \t\t"A:motion",
            \t\t"C:motion",
            \t\t"A:end",
            \t\t"C:end"
            \t]
            \tif not _check(trace == expected_first, "first frame trace mismatch: " + str(trace)):
            \t\treturn
            \tif not _check(not trace.has("C:step1"), "created child received Step in creation frame"):
            \t\treturn
            \tif not _check(not trace.has("B:motion"), "destroyed instance received motion"):
            \t\treturn
            \tvar runtime_trace = GMRuntime.gml_event_scheduler_trace()
            \tif not _check(runtime_trace[0]["phase"] == "begin_step", "runtime trace did not start with begin_step"):
            \t\treturn
            \tvar first_alarm_phase = -1
            \tvar first_step_phase = -1
            \tfor i in range(runtime_trace.size()):
            \t\tif runtime_trace[i]["phase"] == "alarms" and first_alarm_phase < 0:
            \t\t\tfirst_alarm_phase = i
            \t\tif runtime_trace[i]["phase"] == "step" and first_step_phase < 0:
            \t\t\tfirst_step_phase = i
            \tif not _check(first_alarm_phase > 0 and first_alarm_phase < first_step_phase, "alarms did not run before Step"):
            \t\treturn
            \tif not _check(GMRuntime.gml_event_scheduler_phase_order() == ["animation", "begin_step", "async", "timelines", "time_sources", "alarms", "keyboard", "mouse", "sequences", "step", "motion", "other", "collision", "end_step"], "phase order mismatch"):
            \t\treturn

            \ttrace.clear()
            \tGMRuntime.gml_event_scheduler_set_enabled(true)
            \tGMRuntime.gml_event_scheduler_frame(0.016, 1)
            \tGMRuntime.gml_event_scheduler_set_enabled(false)
            \tif not _check(trace.find("A:alarm1") > trace.find("A:begin2"), "Step-set alarm did not fire after next Begin Step"):
            \t\treturn
            \tif not _check(trace.find("A:alarm1") < trace.find("A:step2"), "Step-set alarm fired after Step"):
            \t\treturn

            \tprint("EVENT_SCHEDULER_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as godot_tmp:
            project_dir = Path(godot_tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "event_instance.gd", event_instance_script)
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = run_headless_scene(godot_binary, project_dir, 'smoke.tscn', timeout=30)
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot event-scheduler smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("EVENT_SCHEDULER_SMOKE_OK", result.stdout)

    def test_step_instance_list_motion_skip_and_bounded_traces(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        listed_instance_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var label = ""
            var log = []
            var id = GMRuntime.gml_instance_noone()
            var steps = 0

            func configure(label_value, log_ref):
            \tlabel = str(label_value)
            \tlog = log_ref

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, label, [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _spawn(child_label):
            \tvar child = load("res://listed_instance.gd").new()
            \tchild.configure(child_label, log)
            \tget_parent().add_child(child)

            func _on_begin_step():
            \tsteps += 1
            \tlog.append(label + ":begin")
            \tif label == "A" and steps == 1:
            \t\t_spawn("B")

            func _on_step():
            \tlog.append(label + ":step")

            func _on_end_step():
            \tlog.append(label + ":end")
            \tif label == "A" and steps == 1:
            \t\t_spawn("C")
            \tif label == "B":
            \t\tGMRuntime.gml_instance_destroy(id)

            func _gm_input_event_bindings():
            \treturn [{"event_type": 5, "event_num": 0, "method": "_on_no_key"}]

            func _on_no_key():
            \tpass
            """
        )

        moving_instance_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var label = ""
            var log = []
            var id = GMRuntime.gml_instance_noone()
            var hspeed = 0.0
            var vspeed = 0.0
            var speed = 0.0
            var friction = 0.0
            var gravity = 0.0
            var path_index = GMRuntime.gml_undefined()

            func configure(label_value, log_ref):
            \tlabel = str(label_value)
            \tlog = log_ref

            func _ready():
            \tid = GMRuntime.gml_instance_register(self, label, [])

            func _exit_tree():
            \tGMRuntime.gml_instance_unregister(id)

            func _gm_apply_motion_step():
            \tlog.append(label + ":motion")
            """
        )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const ListedInstance = preload("res://listed_instance.gd")
            const MovingInstance = preload("res://moving_instance.gd")

            var log = []

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _frame():
            \tGMRuntime.gml_event_scheduler_set_enabled(true)
            \tvar frame = GMRuntime.gml_event_scheduler_frame(0.016, 1)
            \tGMRuntime.gml_event_scheduler_set_enabled(false)
            \treturn frame

            func _add(script, label, settings = {}):
            \tvar inst = script.new()
            \tinst.configure(label, log)
            \tfor key in settings.keys():
            \t\tinst.set(key, settings[key])
            \tadd_child(inst)
            \treturn inst

            func _run():
            \tGMRuntime.gml_event_scheduler_set_enabled(false)
            \tif not _check(not GMRuntime.gml_event_scheduler_tracing(), "tracing is on by default"):
            \t\treturn
            \tvar a = _add(ListedInstance, "A")
            \t# Created in Begin Step: no Begin Step of its own, but Step and End
            \t# Step in the same step. Created in End Step: first events next step.
            \t_frame()
            \tif not _check(log == ["A:begin", "A:step", "B:step", "A:end", "B:end"], "first step: " + str(log)):
            \t\treturn
            \tlog.clear()
            \t_frame()
            \tif not _check(log == ["A:begin", "C:begin", "A:step", "C:step", "A:end", "C:end"], "second step: " + str(log)):
            \t\treturn
            \tif not _check(GMRuntime.gml_event_scheduler_trace().is_empty() and GMRuntime.gml_input_dispatch_trace().is_empty(), "events were recorded with tracing off"):
            \t\treturn

            \t# Tracing keeps only the latest records.
            \tGMRuntime.gml_event_scheduler_set_tracing(true)
            \tvar last_frame = -1
            \tfor i in range(800):
            \t\tlast_frame = _frame()
            \tvar trace = GMRuntime.gml_event_scheduler_trace()
            \tif not _check(trace.size() == GMRuntime.GML_EVENT_SCHEDULER_TRACE_LIMIT, "scheduler trace size " + str(trace.size())):
            \t\treturn
            \tif not _check(GMRuntime._gml_event_scheduler_trace.size() < 2 * GMRuntime.GML_EVENT_SCHEDULER_TRACE_LIMIT, "scheduler trace kept growing"):
            \t\treturn
            \tif not _check(trace[-1]["frame"] == last_frame and trace[-1]["phase"] == "end_step", "last record " + str(trace[-1])):
            \t\treturn
            \tvar input_trace = GMRuntime.gml_input_dispatch_trace()
            \tif not _check(input_trace.size() == GMRuntime.GML_INPUT_TRACE_LIMIT, "input trace size " + str(input_trace.size())):
            \t\treturn
            \tif not _check(GMRuntime._gml_input_dispatch_trace.size() < 2 * GMRuntime.GML_INPUT_TRACE_LIMIT, "input trace kept growing"):
            \t\treturn
            \tGMRuntime.gml_event_scheduler_set_tracing(false)
            \tGMRuntime.gml_event_scheduler_trace_clear()
            \t_frame()
            \tif not _check(GMRuntime.gml_event_scheduler_trace().is_empty(), "events were recorded after tracing was turned off"):
            \t\treturn

            \t# Instances that stand still skip the motion step; anything that
            \t# could move them takes it.
            \tfor child in get_children():
            \t\tchild.queue_free()
            \tawait get_tree().process_frame
            \t_add(MovingInstance, "idle")
            \t_add(MovingInstance, "hspeed", {"hspeed": 1.0, "speed": 1.0})
            \t_add(MovingInstance, "vspeed", {"vspeed": -2})
            \t_add(MovingInstance, "gravity", {"gravity": 0.5})
            \t_add(MovingInstance, "friction_still", {"friction": 0.2})
            \t_add(MovingInstance, "friction_moving", {"friction": 0.2, "speed": 1.0, "hspeed": 1.0})
            \t_add(MovingInstance, "path", {"path_index": 0})
            \t_add(MovingInstance, "no_path", {"path_index": -1})
            \t_add(MovingInstance, "undefined_speed", {"hspeed": GMRuntime.gml_undefined()})
            \tlog.clear()
            \t_frame()
            \tvar expected = ["hspeed:motion", "vspeed:motion", "gravity:motion", "friction_moving:motion", "path:motion", "undefined_speed:motion"]
            \tif not _check(log == expected, "motion steps: " + str(log)):
            \t\treturn

            \t# A freed node in an instance list is skipped, not type-tested.
            \tvar freed = _add(ListedInstance, "freed")
            \tvar kept = _add(ListedInstance, "kept")
            \tfreed.free()
            \tGMRuntime.gml_input_dispatch_frame([freed, kept], [5])
            \t_frame()

            \tprint("EVENT_SCHEDULER_LIST_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as godot_tmp:
            project_dir = Path(godot_tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "listed_instance.gd", listed_instance_script)
            _write_text(project_dir / "moving_instance.gd", moving_instance_script)
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = run_headless_scene(godot_binary, project_dir, 'smoke.tscn', timeout=60)
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot step instance list smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("EVENT_SCHEDULER_LIST_SMOKE_OK", result.stdout)
        self.assertNotIn("SCRIPT ERROR", result.stdout)


if __name__ == "__main__":
    unittest.main()
