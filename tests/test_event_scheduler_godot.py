from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
            \tif not _check(GMRuntime.gml_event_scheduler_phase_order() == ["begin_step", "time_sources", "alarms", "step", "motion", "collision", "end_step"], "phase order mismatch"):
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
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot event-scheduler smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("EVENT_SCHEDULER_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
