"""Godot checks that converted timelines run their moments on GameMaker's steps.

Each step the timeline position moves by timeline_speed first, then every
moment from the first one at or after the old position up to (not including)
the first one at or after the new position runs (HTML5 runner Events.js
HandleTimeLine, yyTimeline.js FindLarger/FindSmaller). A looping timeline
restarts at 0 once the position is past its last moment, or at its last
moment once it is below 0 when running backwards. Moments may change the
timeline variables themselves.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
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
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_EVENT_BEGIN_STEP = (3, 1)


def _moment(list_name: str, label: str, extra: str = "") -> str:
    return (
        f'if (steps <= 6) array_push(global.{list_name}, "{label}:" + string(steps) + ":"'
        " + string(timeline_position));\n" + extra
    )


# Moment code by timeline and moment.
_TIMELINES: dict[str, dict[int, str]] = {
    "tl_steps": {
        0: _moment("runner", "m0"),
        2: _moment("runner", "m2"),
        3: _moment("runner", "m3", "timeline_running = false;\ntimeline_position = 10;\n"),
    },
    "tl_loop": {
        1: _moment("looper", "l1"),
        3: _moment("looper", "l3"),
    },
    "tl_back": {
        1: _moment("reverser", "b1"),
        2: _moment("reverser", "b2"),
    },
}

_STEP_COUNTER = "steps += 1;\n"

_PROJECT = GameMakerProject(
    name="TimelineSteps",
    objects=(
        GameMakerObject(
            "o_runner",
            {
                EVENT_CREATE: (
                    "steps = 0;\nglobal.runner = [];\n"
                    "timeline_index = tl_steps;\ntimeline_running = true;\n"
                ),
                _EVENT_BEGIN_STEP: _STEP_COUNTER
                + (
                    'if (steps == 6) array_push(global.runner, "after:" + string(timeline_position) + ":"'
                    ' + (timeline_running ? "running" : "stopped"));\n'
                ),
            },
        ),
        GameMakerObject(
            "o_looper",
            {
                EVENT_CREATE: (
                    "steps = 0;\nglobal.looper = [];\n"
                    "timeline_index = tl_loop;\ntimeline_speed = 2;\ntimeline_loop = true;\n"
                    "timeline_running = true;\n"
                ),
                _EVENT_BEGIN_STEP: _STEP_COUNTER,
            },
        ),
        GameMakerObject(
            "o_reverser",
            {
                EVENT_CREATE: (
                    "steps = 0;\nglobal.reverser = [];\n"
                    "timeline_index = tl_back;\ntimeline_position = 2;\ntimeline_speed = -1;\n"
                    "timeline_loop = true;\ntimeline_running = true;\n"
                ),
                _EVENT_BEGIN_STEP: _STEP_COUNTER,
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_runner", "o_runner", 16, 16),
                        RoomInstance("inst_looper", "o_looper", 32, 16),
                        RoomInstance("inst_reverser", "o_reverser", 48, 16),
                    ),
                ),
            ),
            creation_order=("inst_runner", "inst_looper", "inst_reverser"),
        ),
    ),
)

_EXPECTED = {
    # Moment 0 runs on the first step; a moment at the new position waits
    # for the next step. Moment 3 stops the timeline and moves it.
    "runner": ["m0:1:1", "m2:3:3", "m3:4:4", "after:10:stopped"],
    # Past the last moment (3) the looping position restarts at 0.
    "looper": ["l1:1:2", "l3:2:4", "l1:3:2", "l3:4:4", "l1:5:2", "l3:6:4"],
    # Running backwards, a looping position below 0 restarts at the last
    # moment (2).
    "reverser": ["b2:1:1", "b1:2:0", "b2:4:1", "b1:5:0"],
}

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 12:
		var scope = GMRuntime.gml_global_scope()
		var lists = {}
		for list_name in ["runner", "looper", "reverser"]:
			lists[list_name] = scope.get(list_name, [])
		print("TIMELINE_STEPS " + JSON.stringify(lists))
		get_tree().quit(0)
"""


def _write_timelines(gamemaker_dir: Path) -> None:
    project_path = gamemaker_dir / f"{_PROJECT.name}.yyp"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    for timeline_name, moments in _TIMELINES.items():
        timeline_dir = gamemaker_dir / "timelines" / timeline_name
        write_fixture_text(
            timeline_dir / f"{timeline_name}.yy",
            json.dumps(
                {
                    "$GMTimeline": "v1",
                    "%Name": timeline_name,
                    "name": timeline_name,
                    "resourceType": "GMTimeline",
                    "resourceVersion": "2.0",
                    "momentList": [
                        {"moment": frame, "eventFile": f"Moment_{frame}.gml"} for frame in sorted(moments)
                    ],
                }
            ),
        )
        for frame, source in moments.items():
            write_fixture_text(timeline_dir / f"Moment_{frame}.gml", source)
        project["resources"].append(
            {"id": {"name": timeline_name, "path": f"timelines/{timeline_name}/{timeline_name}.yy"}}
        )
    project_path.write_text(json.dumps(project), encoding="utf-8")


class TestTimelineStepsGodot(unittest.TestCase):
    def test_timeline_moments_run_on_gamemaker_steps(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            _write_timelines(root / "gamemaker")
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("TIMELINE_STEPS ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("TIMELINE_STEPS ")), _EXPECTED)


if __name__ == "__main__":
    unittest.main()
