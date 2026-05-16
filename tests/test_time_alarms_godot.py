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


class TestTimeAlarmsGodotSmoke(unittest.TestCase):
    def test_alarm_countdown_and_time_source_scheduler(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var _alarm_fired = []
            var _ts_callback_count = 0
            var _call_later_fired = false

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _on_alarm_0():
            \t_alarm_fired.append(0)

            func _on_alarm_3():
            \t_alarm_fired.append(3)

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \t# --- Alarm tests ---
            \t# Default alarm values should be -1
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == -1, "default alarm 0 not -1"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 5) == -1, "default alarm 5 not -1"):
            \t\treturn

            \t# Set alarm 0 to fire after 2 ticks
            \tGMRuntime.gml_alarm_set(self, 0, 2)
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == 2, "alarm 0 not set to 2"):
            \t\treturn

            \t# Set alarm 3 to fire after 1 tick
            \tGMRuntime.gml_alarm_set(self, 3, 1)

            \t# Tick 1: alarm 3 should fire (was 1, decrements to 0)
            \tGMRuntime.gml_alarm_tick(self, 1)
            \tif not _check(3 in _alarm_fired, "alarm 3 did not fire after tick 1"):
            \t\treturn
            \tif not _check(0 not in _alarm_fired, "alarm 0 fired too early"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == 1, "alarm 0 not decremented to 1"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 3) == -1, "alarm 3 not reset after firing"):
            \t\treturn

            \t# Tick 2: alarm 0 should fire (was 1, decrements to 0)
            \tGMRuntime.gml_alarm_tick(self, 1)
            \tif not _check(0 in _alarm_fired, "alarm 0 did not fire after tick 2"):
            \t\treturn

            \t# Out of range alarm access
            \tif not _check(GMRuntime.gml_alarm_get(self, -1) == -1, "negative alarm index not -1"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 12) == -1, "alarm index 12 not -1"):
            \t\treturn

            \t# --- Time source tests ---
            \tvar cb_count_ref = {"n": 0}
            \tvar cb = func(): cb_count_ref["n"] += 1

            \t# One-shot time source (frame mode)
            \tvar ts = GMRuntime.gml_time_source_create(null, 3, 0, cb, [], 1, 0)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 0, "initial state not INITIAL"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_period(ts) == 3, "period not 3"):
            \t\treturn

            \tGMRuntime.gml_time_source_start(ts)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 1, "started state not ACTIVE"):
            \t\treturn

            \t# Tick 2 frames - should not fire yet
            \tGMRuntime.gml_time_source_tick_all(0.0, 2)
            \tif not _check(cb_count_ref["n"] == 0, "callback fired too early"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_time_remaining(ts) == 1, "time remaining not 1"):
            \t\treturn

            \t# Tick 1 more frame - should fire
            \tGMRuntime.gml_time_source_tick_all(0.0, 1)
            \tif not _check(cb_count_ref["n"] == 1, "callback did not fire at period"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 3, "one-shot not STOPPED"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_reps_completed(ts) == 1, "reps completed not 1"):
            \t\treturn

            \t# --- Pause/resume test ---
            \tvar cb2_ref = {"n": 0}
            \tvar cb2 = func(): cb2_ref["n"] += 1
            \tvar ts2 = GMRuntime.gml_time_source_create(null, 2, 0, cb2, [], 3, 0)
            \tGMRuntime.gml_time_source_start(ts2)

            \t# Tick 1 frame
            \tGMRuntime.gml_time_source_tick_all(0.0, 1)

            \t# Pause
            \tGMRuntime.gml_time_source_pause(ts2)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts2) == 2, "paused state not PAUSED"):
            \t\treturn

            \t# Tick while paused - should not advance
            \tGMRuntime.gml_time_source_tick_all(0.0, 5)
            \tif not _check(cb2_ref["n"] == 0, "callback fired while paused"):
            \t\treturn

            \t# Resume
            \tGMRuntime.gml_time_source_resume(ts2)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts2) == 1, "resumed state not ACTIVE"):
            \t\treturn

            \t# Tick 1 more frame to reach period (1 elapsed before pause + 1 now = 2)
            \tGMRuntime.gml_time_source_tick_all(0.0, 1)
            \tif not _check(cb2_ref["n"] == 1, "callback did not fire after resume"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_reps_remaining(ts2) == 2, "reps remaining not 2"):
            \t\treturn

            \t# Destroy
            \tGMRuntime.gml_time_source_destroy(ts2)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts2) == 3, "destroyed state not STOPPED"):
            \t\treturn

            \t# --- call_later test ---
            \tvar later_ref = {"fired": false}
            \tvar later_cb = func(): later_ref["fired"] = true
            \tvar later_handle = GMRuntime.gml_call_later(1, 0, later_cb, false)
            \tGMRuntime.gml_time_source_tick_all(0.0, 1)
            \tif not _check(later_ref["fired"], "call_later callback did not fire"):
            \t\treturn

            \t# --- call_cancel test ---
            \tvar cancel_ref = {"fired": false}
            \tvar cancel_cb = func(): cancel_ref["fired"] = true
            \tvar cancel_handle = GMRuntime.gml_call_later(2, 0, cancel_cb, false)
            \tGMRuntime.gml_call_cancel(cancel_handle)
            \tGMRuntime.gml_time_source_tick_all(0.0, 5)
            \tif not _check(not cancel_ref["fired"], "cancelled callback still fired"):
            \t\treturn

            \t# --- Seconds mode test ---
            \tvar sec_ref = {"n": 0}
            \tvar sec_cb = func(): sec_ref["n"] += 1
            \tvar ts_sec = GMRuntime.gml_time_source_create(null, 0.5, 1, sec_cb, [], 1, 0)
            \tGMRuntime.gml_time_source_start(ts_sec)
            \t# Tick with frames only - should not fire
            \tGMRuntime.gml_time_source_tick_all(0.0, 100)
            \tif not _check(sec_ref["n"] == 0, "seconds mode fired on frame tick"):
            \t\treturn
            \t# Tick with seconds
            \tGMRuntime.gml_time_source_tick_all(0.5, 0)
            \tif not _check(sec_ref["n"] == 1, "seconds mode did not fire"):
            \t\treturn

            	# Cleanup remaining time sources to avoid static closure leaks
            	GMRuntime._gml_time_sources.clear()

            	print("TIME_ALARM_SMOKE_OK")
            	get_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="TimeAlarmSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

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
        self.assertIn("TIME_ALARM_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
