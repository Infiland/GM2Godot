from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.gamemaker_project_support import (
    EVENT_CREATE,
    EVENT_STEP,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

# Time sources and call_later from converted GML, with GameMaker's named
# constants and every kind of callback: a method (the function literal keeps
# the instance as self and gets the arguments array spread), a script
# function and a call_later function. In each step the time sources run
# before the Step event, so the callbacks see the previous step's count; a
# time source made by a callback first counts in the next step.
_CLOCK_CREATE = """\
global.step = 0;
global.deltas = [];
trace("constants " + string(time_source_units_seconds) + string(time_source_units_frames)
    + string(time_source_expire_nearest) + string(time_source_expire_after)
    + string(time_source_global) + string(time_source_game));
var _method = function(_text, _number) {
    trace("method " + string(global.step) + " " + _text + string(_number) + " x=" + string(x));
};
global.ts = time_source_create(time_source_global, 2, time_source_units_frames, _method, ["a", 7], 2);
trace("created " + string(time_source_get_state(global.ts)));
time_source_start(global.ts);
trace("started " + string(time_source_get_state(global.ts)) + " " + string(time_source_get_period(global.ts))
    + " " + string(time_source_get_parent(global.ts) == time_source_global));
call_later(3, time_source_units_frames, scr_tick);
global.reps = 0;
global.rep = call_later(1, time_source_units_frames, function() {
    global.reps += 1;
    trace("repeat " + string(global.step));
    if (global.reps == 3) call_cancel(global.rep);
}, true);
call_later(1, time_source_units_frames, function() {
    trace("outer " + string(global.step));
    call_later(1, time_source_units_frames, function() { trace("inner " + string(global.step)); });
});
global.game = time_source_create(time_source_game, 1, time_source_units_frames,
    function() { trace("game " + string(global.step)); }, [], -1);
time_source_start(global.game);
trace("roots " + string(time_source_get_state(time_source_global)) + " " + string(time_source_get_state(time_source_game)));
trace("exists " + string(time_source_exists(global.ts)) + " " + string(time_source_exists(global.rep)));
"""
# A seconds time source counts the real time of each frame from the step
# after it was made, which is what delta_time measures; it expires in the
# first step by which its period has passed.
_CLOCK_STEP = """\
global.step += 1;
array_push(global.deltas, delta_time);
if (global.step == 2) {
    call_later(0.1, time_source_units_seconds, function() {
        var _total = delta_time;
        for (var _i = 2; _i < array_length(global.deltas); _i += 1) _total += global.deltas[_i];
        trace("seconds " + string(_total >= 100000) + " " + string(_total - delta_time < 100000));
    });
}
if (global.step == 3) time_source_pause(time_source_game);
if (global.step == 5) time_source_resume(time_source_game);
if (global.step == 6) {
    trace("ran out " + string(time_source_get_state(global.ts)) + " " + string(time_source_get_reps_completed(global.ts))
        + " " + string(time_source_get_reps_remaining(global.ts)));
    time_source_destroy(global.ts);
    time_source_destroy(global.game);
    trace("destroyed " + string(time_source_exists(global.ts)) + " " + string(time_source_exists(global.game)));
}
"""
_CLOCK_PROJECT = GameMakerProject(
    name="TimeSources",
    scripts={
        "scr_trace": _TRACE_SCRIPT,
        "scr_tick": 'function scr_tick() {\n    trace("script " + string(global.step));\n}\n',
    },
    objects=(GameMakerObject("o_clock", {EVENT_CREATE: _CLOCK_CREATE, EVENT_STEP: _CLOCK_STEP}),),
    rooms=(
        GameMakerRoom(
            "r_clock",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_clock", "o_clock", 32, 0),)),),
            creation_order=("inst_clock",),
        ),
    ),
)
_CLOCK_TRACE = [
    "constants 010101",
    "created 0",
    "started 1 2 true",
    "roots undefined 1",
    "exists true false",
    "repeat 0",
    "outer 0",
    "game 0",
    "method 1 a7 x=32",
    "repeat 1",
    "inner 1",
    "game 1",
    "script 2",
    "repeat 2",
    "game 2",
    "method 3 a7 x=32",
    "game 5",
    "ran out 3 2 0",
    "destroyed false false",
]

# game_restart drops the pending call_later calls (Run_EndGame); time sources
# made with time_source_create keep running.
_RESTART_PROJECT = GameMakerProject(
    name="TimeSourcesRestart",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_restart",
            {
                EVENT_CREATE: (
                    'if (!variable_global_exists("runs")) global.runs = 0;\n'
                    "global.runs += 1;\n"
                    'trace("create " + string(global.runs));\n'
                    "if (global.runs == 1) {\n"
                    '    call_later(2, time_source_units_frames, function() { trace("call_later survived"); });\n'
                    "    global.kept = time_source_create(time_source_global, 2, time_source_units_frames,\n"
                    '        function() { trace("time source kept"); });\n'
                    "    time_source_start(global.kept);\n"
                    "}\n"
                ),
                EVENT_STEP: "if (global.runs == 1) game_restart();\n",
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_restart",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_restart", "o_restart", 0, 0),)),),
            creation_order=("inst_restart",),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 30:
		print("TIME_SOURCE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


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
            \tif not _check(GMRuntime.gml_alarm_get(self, 3) == 0, "alarm 3 not left at 0 after firing"):
            \t\treturn

            \t# Tick 2: alarm 0 should fire (was 1, decrements to 0)
            \tGMRuntime.gml_alarm_tick(self, 1)
            \tif not _check(0 in _alarm_fired, "alarm 0 did not fire after tick 2"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == 0, "alarm 0 not left at 0 after firing"):
            \t\treturn
            \tGMRuntime.gml_alarm_tick(self, 1)
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == -1, "alarm 0 did not clear to -1 on the next tick"):
            \t\treturn
            \tGMRuntime.gml_alarm_set(self, 0, 0)
            \tGMRuntime.gml_alarm_tick(self, 1)
            \tif not _check(_alarm_fired.count(0) == 1, "alarm 0 fired when explicitly set to 0"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 0) == -1, "alarm 0 set to 0 did not clear to -1"):
            \t\treturn

            \t# Out of range alarm access
            \tif not _check(GMRuntime.gml_alarm_get(self, -1) == -1, "negative alarm index not -1"):
            \t\treturn
            \tif not _check(GMRuntime.gml_alarm_get(self, 12) == -1, "alarm index 12 not -1"):
            \t\treturn

            \t# --- Time source tests ---
            \t# GameMaker's values (yyTime.js): units seconds 0 and frames 1,
            \t# expiry nearest 0 and after 1; time_source_global is 0 and
            \t# time_source_game 1. gml_time_source_frame_tick hands the real
            \t# frame time to the global source and gml_time_source_step runs
            \t# the step's time-source phase with the step's delta_time.
            \tvar frames_ref = {"n": 0, "args": []}
            \tvar frames_cb = func(a, b):
            \t\tframes_ref["n"] += 1
            \t\tframes_ref["args"] = [a, b]
            \tvar ts = GMRuntime.gml_time_source_create(0, 3, 1, frames_cb, [4, 5])
            \tif not _check(GMRuntime.gml_time_source_exists(ts), "created time source does not exist"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 0, "initial state not INITIAL"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_period(ts) == 3, "period not 3"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_units(ts) == 1, "units not frames"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_parent(ts) == 0, "parent not the global time source"):
            \t\treturn
            \t# A time source counts only once it is started.
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(GMRuntime.gml_time_source_get_time_remaining(ts) == 3, "initial time source counted a step"):
            \t\treturn
            \tGMRuntime.gml_time_source_start(ts)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 1, "started state not ACTIVE"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(0)
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(frames_ref["n"] == 0, "callback fired too early"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_time_remaining(ts) == 1, "time remaining not 1"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(frames_ref["n"] == 1 and frames_ref["args"] == [4, 5], "callback did not fire with its arguments at the period: " + str(frames_ref)):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 3, "one-shot not STOPPED"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_reps_completed(ts) == 1, "reps completed not 1"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_reps_remaining(ts) == 0, "reps remaining not 0"):
            \t\treturn
            \tfor _i in range(3):
            \t\tGMRuntime.gml_time_source_step(0)
            \tif not _check(frames_ref["n"] == 1, "stopped time source fired again"):
            \t\treturn
            \t# Starting a time source that ran out runs it again.
            \tGMRuntime.gml_time_source_start(ts)
            \tfor _i in range(3):
            \t\tGMRuntime.gml_time_source_step(0)
            \tif not _check(frames_ref["n"] == 2 and GMRuntime.gml_time_source_get_reps_completed(ts) == 2, "restarted time source did not run again"):
            \t\treturn

            \t# --- Pausing the game time source pauses its children ---
            \tvar game_ref = {"n": 0}
            \tvar game_cb = func(): game_ref["n"] += 1
            \tvar ts2 = GMRuntime.gml_time_source_create(1, 2, 1, game_cb, [], 3)
            \tGMRuntime.gml_time_source_start(ts2)
            \tGMRuntime.gml_time_source_step(0)
            \tGMRuntime.gml_time_source_pause(1)
            \tif not _check(GMRuntime.gml_time_source_get_state(1) == 2, "game time source not PAUSED"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_state(ts2) == 2, "child of the game time source not PAUSED"):
            \t\treturn
            \tfor _i in range(5):
            \t\tGMRuntime.gml_time_source_step(0)
            \tif not _check(game_ref["n"] == 0, "callback fired while paused"):
            \t\treturn
            \tGMRuntime.gml_time_source_resume(1)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts2) == 1, "resumed state not ACTIVE"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(game_ref["n"] == 1, "callback did not fire after resume"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_reps_remaining(ts2) == 2, "reps remaining not 2"):
            \t\treturn

            \t# --- Seconds: real frame time for the global time source, the
            \t# step's delta_time for the game time source ---
            \tvar sec_ref = {"n": 0}
            \tvar sec_cb = func(): sec_ref["n"] += 1
            \tvar ts_sec = GMRuntime.gml_time_source_create(0, 0.5, 0, sec_cb)
            \tGMRuntime.gml_time_source_start(ts_sec)
            \tfor _i in range(100):
            \t\tGMRuntime.gml_time_source_step(1000000)
            \tif not _check(sec_ref["n"] == 0, "global seconds time source counted the game time"):
            \t\treturn
            \tGMRuntime.gml_time_source_frame_tick(300000)
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(sec_ref["n"] == 0 and is_equal_approx(GMRuntime.gml_time_source_get_time_remaining(ts_sec), 0.2), "seconds time source fired early or lost time"):
            \t\treturn
            \tGMRuntime.gml_time_source_frame_tick(200000)
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(sec_ref["n"] == 1, "seconds time source did not fire after its period"):
            \t\treturn
            \tvar ts_game_sec = GMRuntime.gml_time_source_create(1, 0.5, 0, sec_cb)
            \tGMRuntime.gml_time_source_start(ts_game_sec)
            \tGMRuntime.gml_time_source_frame_tick(1000000)
            \tGMRuntime.gml_time_source_step(250000)
            \tif not _check(sec_ref["n"] == 1, "game seconds time source counted the real frame time"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(250000)
            \tif not _check(sec_ref["n"] == 2, "game seconds time source did not count delta_time"):
            \t\treturn

            \t# --- Trees, destroy and the built-in time sources ---
            \tvar parent_ts = GMRuntime.gml_time_source_create(0, 10, 1, frames_cb, [0, 0])
            \tvar child_ts = GMRuntime.gml_time_source_create(parent_ts, 10, 1, frames_cb, [0, 0])
            \tif not _check(GMRuntime.gml_time_source_get_parent(child_ts) == parent_ts, "child parent mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_children(parent_ts) == [child_ts], "children mismatch"):
            \t\treturn
            \t# A time source with children is only destroyed with its tree.
            \tGMRuntime.gml_time_source_destroy(parent_ts)
            \tif not _check(GMRuntime.gml_time_source_exists(parent_ts), "time source with children was destroyed"):
            \t\treturn
            \tGMRuntime.gml_time_source_destroy(parent_ts, true)
            \tif not _check(not GMRuntime.gml_time_source_exists(parent_ts) and not GMRuntime.gml_time_source_exists(child_ts), "destroy_tree left time sources"):
            \t\treturn
            \tGMRuntime.gml_time_source_destroy(ts2)
            \tif not _check(not GMRuntime.gml_time_source_exists(ts2), "destroyed time source still exists"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(GMRuntime.gml_time_source_get_state(0)), "the global time source has a state"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_get_state(1) == 1, "the game time source is not ACTIVE"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_exists(0) and GMRuntime.gml_time_source_exists(1), "built-in time sources missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_source_create(0, 1, 1, frames_cb, [], 1, 2) == -1, "illegal expiry type accepted"):
            \t\treturn
            \t# Reconfiguring resets the time source.
            \tGMRuntime.gml_time_source_reconfigure(ts, 1, 1, frames_cb, [6, 7], 1, 0)
            \tif not _check(GMRuntime.gml_time_source_get_state(ts) == 0 and GMRuntime.gml_time_source_get_reps_completed(ts) == 0, "reconfigure did not reset"):
            \t\treturn
            \tGMRuntime.gml_time_source_start(ts)
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(frames_ref["n"] == 3 and frames_ref["args"] == [6, 7], "reconfigured time source did not fire: " + str(frames_ref)):
            \t\treturn
            \tif not _check(GMRuntime.gml_time_bpm_to_seconds(120) == 0.5 and GMRuntime.gml_time_seconds_to_bpm(0.5) == 120, "bpm conversion mismatch"):
            \t\treturn

            \t# --- call_later test ---
            \tvar later_ref = {"fired": false}
            \tvar later_cb = func(): later_ref["fired"] = true
            \tvar later_handle = GMRuntime.gml_call_later(1, 1, later_cb, false)
            \tif not _check(not GMRuntime.gml_time_source_exists(later_handle), "call_later time source is visible to time_source_exists"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(later_ref["fired"], "call_later callback did not fire"):
            \t\treturn

            \t# --- call_cancel test ---
            \tvar cancel_ref = {"fired": false}
            \tvar cancel_cb = func(): cancel_ref["fired"] = true
            \tvar cancel_handle = GMRuntime.gml_call_later(2, 1, cancel_cb, false)
            \tGMRuntime.gml_call_cancel(cancel_handle)
            \tfor _i in range(5):
            \t\tGMRuntime.gml_time_source_step(0)
            \tif not _check(not cancel_ref["fired"], "cancelled callback still fired"):
            \t\treturn

            \t# --- A time source made by a callback starts counting next step ---
            \tvar nested_ref = {"outer": 0, "inner": 0}
            \tvar inner_cb = func(): nested_ref["inner"] += 1
            \tvar outer_cb = func():
            \t\tnested_ref["outer"] += 1
            \t\tGMRuntime.gml_call_later(1, 1, inner_cb)
            \tGMRuntime.gml_call_later(1, 1, outer_cb)
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(nested_ref["outer"] == 1 and nested_ref["inner"] == 0, "time source made by a callback fired in the same step"):
            \t\treturn
            \tGMRuntime.gml_time_source_step(0)
            \tif not _check(nested_ref["inner"] == 1, "time source made by a callback did not fire"):
            \t\treturn

            	# Cleanup remaining time sources to avoid static closure leaks
            	GMRuntime.gml_time_source_destroy(0, true)
            	GMRuntime.gml_time_source_destroy(1, true)
            	GMRuntime.gml_time_source_clear_call_later()

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


class TestConvertedTimeSourcesGodot(unittest.TestCase):
    def test_time_sources_and_call_later_run_gml_callbacks_like_gamemaker(self) -> None:
        trace = self._run_trace(_CLOCK_PROJECT)
        self.assertEqual(trace.count("seconds true true"), 1, trace)
        self.assertEqual([entry for entry in trace if not entry.startswith("seconds ")], _CLOCK_TRACE)

    def test_game_restart_drops_call_later_but_keeps_time_sources(self) -> None:
        self.assertEqual(self._run_trace(_RESTART_PROJECT), ["create 1", "create 2", "time source kept"])

    def _run_trace(self, project: GameMakerProject) -> list[str]:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("TIME_SOURCE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("TIME_SOURCE_TRACE "))


if __name__ == "__main__":
    unittest.main()
