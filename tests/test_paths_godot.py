"""Converted games that follow GameMaker paths, run headless in Godot.

Each test writes a small GameMaker project with path assets, converts it with
the full converter and traces what the instances do. The expected traces
follow the GameMaker runner (yyInstance.js Assign_Path/Adapt_Path, yyPath.js
and Function_Path.js).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

EVENT_END_STEP = (3, 2)
EVENT_PATH_END = (7, 8)

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    "function f3(_value) {\n"
    "    return string(round(_value * 1000));\n"
    "}\n"
    "function following(_path_index) {\n"
    '    return (_path_index == -1) ? "none" : "on";\n'
    "}\n"
)
# What the end action tests trace: x, y, path_position, path_speed (times
# 1000) and whether the instance still follows a path.
_PATH_STATE = (
    'f3(x) + "," + f3(y) + "," + f3(path_position) + "," + f3(path_speed) + "," + following(path_index)'
)


@dataclass(frozen=True)
class GameMakerPath:
    name: str
    points: Sequence[tuple[float, float, float]]
    closed: bool = False
    kind: int = 0
    precision: int = 4


def _write_paths(project_dir: Path, paths: Sequence[GameMakerPath]) -> None:
    # Adds GMPath assets to a project written by write_gamemaker_project.
    project_file = next(project_dir.glob("*.yyp"))
    project = json.loads(project_file.read_text(encoding="utf-8"))
    for path in paths:
        document = {
            "$GMPath": "",
            "%Name": path.name,
            "closed": path.closed,
            "kind": path.kind,
            "name": path.name,
            "parent": {"name": "Paths", "path": "folders/Paths.yy"},
            "points": [{"speed": speed, "x": x, "y": y} for x, y, speed in path.points],
            "precision": path.precision,
            "resourceType": "GMPath",
            "resourceVersion": "2.0",
        }
        write_fixture_text(project_dir / "paths" / path.name / f"{path.name}.yy", json.dumps(document, indent=2))
        project["resources"].append({"id": {"name": path.name, "path": f"paths/{path.name}/{path.name}.yy"}})
    project_file.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")


def _probe(frames: int) -> str:
    return (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var _frames = 0\n\n\n"
        "func _process(_delta):\n"
        "\t_frames += 1\n"
        f"\tif _frames == {frames}:\n"
        '\t\tprint("PATH_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))\n'
        "\t\tget_tree().quit(0)\n"
    )


def _project(objects: Mapping[str, Mapping[tuple[int, int], str]], instances: Sequence[tuple[str, float, float]]) -> GameMakerProject:
    room_instances = tuple(
        RoomInstance(f"inst_{index}", object_name, x, y) for index, (object_name, x, y) in enumerate(instances)
    )
    return GameMakerProject(
        name="PathGame",
        scripts={"scr_trace": _TRACE_SCRIPT},
        objects=tuple(GameMakerObject(name, events) for name, events in objects.items()),
        rooms=(
            GameMakerRoom(
                "r_paths",
                layers=(InstanceLayer("Instances", 0, room_instances),),
                creation_order=tuple(instance.name for instance in room_instances),
            ),
        ),
    )


class TestPathsGodot(unittest.TestCase):
    def _run_trace(
        self,
        objects: Mapping[str, Mapping[tuple[int, int], str]],
        instances: Sequence[tuple[str, float, float]],
        paths: Sequence[GameMakerPath],
        *,
        frames: int,
    ) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _project(objects, instances))
            _write_paths(root / "gamemaker", paths)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _probe(frames))
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("PATH_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("PATH_TRACE "))

    def test_path_start_takes_the_path_end_action_constants(self) -> None:
        # path_action_stop/restart/continue/reverse are the built-in
        # constants 0/1/2/3 that path_start and path_endaction take.
        trace = self._run_trace(
            {
                "o_runner": {
                    EVENT_CREATE: (
                        "path_start(pth_line, 10, path_action_stop, true);\n"
                        'trace("actions:" + string(path_action_stop) + string(path_action_restart)'
                        " + string(path_action_continue) + string(path_action_reverse));\n"
                        'trace("index:" + string(path_index == pth_line));\n'
                    ),
                    EVENT_STEP: 'trace("x:" + string(x));\n',
                    EVENT_PATH_END: 'trace("end:" + string(x));\n',
                },
            },
            (("o_runner", 100, 50),),
            (GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),),
            frames=6,
        )
        self.assertEqual(
            trace,
            ["actions:0123", "index:true", "x:0", "x:10", "x:20", "x:30", "end:40", "x:40"],
        )

    def test_instances_follow_the_curve_of_a_smooth_closed_path(self) -> None:
        # A smooth path rounds each corner (precision 3 here) and a closed
        # one runs on to its start, which on a closed smooth path is the
        # middle of the closing leg's curve. Positions are x and y times 100,
        # as GameMaker's runner computes them (yyPath.js).
        trace = self._run_trace(
            {
                "o_runner": {
                    EVENT_CREATE: "path_start(pth_loop, 30, path_action_stop, true);\n",
                    EVENT_STEP: 'trace(string(round(x * 100)) + "," + string(round(y * 100)));\n',
                    EVENT_PATH_END: 'trace("end:" + string(round(x * 100)) + "," + string(round(y * 100)));\n',
                },
            },
            (("o_runner", 10, 10),),
            (GameMakerPath("pth_loop", ((0, 0, 100), (100, 0, 100), (100, 100, 100)), closed=True, kind=1, precision=3),),
            frames=11,
        )
        self.assertEqual(
            trace,
            [
                "6172,78",
                "8825,1347",
                "9922,4074",
                "9582,7001",
                "6960,6700",
                "4754,4676",
                "2876,2356",
                "3740,128",
                "end:6172,78",
                "6172,78",
                "6172,78",
            ],
        )

    def test_end_actions_apply_before_the_path_end_event(self) -> None:
        # Adapt_Path applies the end action as soon as the position passes an
        # end, and only then does the Path End event run: stop has already
        # ended the path, restart and continue have wrapped the position
        # (continue also moved the path on to where it ended), and reverse has
        # turned path_speed around. Going backwards (negative speed) starts at
        # the end of the path; the runner stops such a path at position 1.
        objects: dict[str, dict[tuple[int, int], str]] = {}
        starts = {
            "stop": "15, path_action_stop",
            "restart": "15, path_action_restart",
            "continue": "15, path_action_continue",
            "reverse": "15, path_action_reverse",
            "back": "-15, path_action_stop",
        }
        for name, arguments in starts.items():
            objects[f"o_{name}"] = {
                EVENT_CREATE: f"path_start(pth_line, {arguments}, true);\n",
                EVENT_STEP: f'trace("{name}:" + {_PATH_STATE});\n',
                EVENT_PATH_END: f'trace("{name}_end:" + {_PATH_STATE});\n',
            }
        trace = self._run_trace(
            objects,
            tuple((f"o_{name}", 100, 50) for name in starts),
            (GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),),
            frames=6,
        )
        by_instance = {
            name: [line for line in trace if line.split(":")[0].removesuffix("_end") == name] for name in starts
        }
        self.assertEqual(
            by_instance,
            {
                "stop": [
                    "stop:0,0,0,15000,on",
                    "stop:15000,0,375,15000,on",
                    "stop:30000,0,750,15000,on",
                    "stop_end:40000,0,1000,15000,none",
                    "stop:40000,0,1000,15000,none",
                    "stop:40000,0,1000,15000,none",
                ],
                "restart": [
                    "restart:0,0,0,15000,on",
                    "restart:15000,0,375,15000,on",
                    "restart:30000,0,750,15000,on",
                    "restart_end:5000,0,125,15000,on",
                    "restart:5000,0,125,15000,on",
                    "restart:20000,0,500,15000,on",
                ],
                "continue": [
                    "continue:0,0,0,15000,on",
                    "continue:15000,0,375,15000,on",
                    "continue:30000,0,750,15000,on",
                    "continue_end:45000,0,125,15000,on",
                    "continue:45000,0,125,15000,on",
                    "continue:60000,0,500,15000,on",
                ],
                "reverse": [
                    "reverse:0,0,0,15000,on",
                    "reverse:15000,0,375,15000,on",
                    "reverse:30000,0,750,15000,on",
                    "reverse_end:35000,0,875,-15000,on",
                    "reverse:35000,0,875,-15000,on",
                    "reverse:20000,0,500,-15000,on",
                ],
                "back": [
                    "back:40000,0,1000,-15000,on",
                    "back:25000,0,625,-15000,on",
                    "back:10000,0,250,-15000,on",
                    "back_end:40000,0,1000,-15000,none",
                    "back:40000,0,1000,-15000,none",
                    "back:40000,0,1000,-15000,none",
                ],
            },
        )

    def test_scale_orientation_and_point_speeds_shape_a_relative_path(self) -> None:
        # A relative path starts where the instance is. Each step adds
        # path_speed times the speed factor at the current position, divided
        # by path_scale, to path_position; the path is drawn path_scale times
        # larger and turned path_orientation degrees (counterclockwise)
        # around its start. Following the path sets direction and leaves
        # speed 0, and path_positionprevious holds the position from the
        # start of the step.
        trace = self._run_trace(
            {
                "o_runner": {
                    EVENT_CREATE: (
                        "path_start(pth_slow, 10, path_action_stop, false);\n"
                        "path_scale = 2;\n"
                        "path_orientation = 90;\n"
                    ),
                    EVENT_END_STEP: (
                        'trace(f3(x) + "," + f3(y) + "," + f3(path_position) + "," + f3(path_positionprevious)'
                        ' + "," + f3(direction) + "," + f3(speed));\n'
                    ),
                },
            },
            (("o_runner", 200, 100),),
            (GameMakerPath("pth_slow", ((0, 0, 100), (100, 0, 50))),),
            frames=6,
        )
        self.assertEqual(
            trace,
            [
                "200000,90000,50,0,90000,0",
                "200000,80250,99,50,90000,0",
                "200000,70744,146,99,90000,0",
                "200000,61475,193,146,90000,0",
                "200000,52438,238,193,90000,0",
            ],
        )

    def test_a_path_started_in_the_path_end_event_is_followed(self) -> None:
        # The stop end action has ended the path before Path End runs, so a
        # path started there is the one the instance follows next (relative,
        # from where the first one ended). path_index is -1 when the instance
        # follows no path.
        trace = self._run_trace(
            {
                "o_chain": {
                    EVENT_CREATE: (
                        'trace("chain_idle:" + string(path_index == -1));\n'
                        "ends = 0;\n"
                        "path_start(pth_line, 20, path_action_stop, true);\n"
                    ),
                    EVENT_STEP: (
                        'var _which = (path_index == pth_line) ? "line" : ((path_index == pth_down) ? "down" : "none");\n'
                        'trace("chain:" + f3(x) + "," + f3(y) + "," + f3(direction) + "," + _which);\n'
                    ),
                    EVENT_PATH_END: (
                        "ends += 1;\n"
                        'trace("chain_end" + string(ends) + ":" + f3(x) + "," + f3(y) + "," + f3(path_position)'
                        ' + "," + following(path_index));\n'
                        "if (ends == 1) path_start(pth_down, 20, path_action_stop, false);\n"
                    ),
                },
            },
            (("o_chain", 100, 50),),
            (
                GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),
                GameMakerPath("pth_down", ((0, 0, 100), (0, 40, 100))),
            ),
            frames=8,
        )
        self.assertEqual(
            trace,
            [
                "chain_idle:true",
                "chain:0,0,0,line",
                "chain:20000,0,0,line",
                "chain_end1:40000,0,1000,none",
                "chain:40000,0,0,down",
                "chain:40000,20000,270000,down",
                "chain_end2:40000,40000,1000,none",
                "chain:40000,40000,270000,none",
                "chain:40000,40000,270000,none",
                "chain:40000,40000,270000,none",
            ],
        )

    def test_path_end_stops_following_but_keeps_the_path_values(self) -> None:
        # path_end only sets path_index to -1: path_position and path_speed
        # keep their values, and the instance stays where it is.
        trace = self._run_trace(
            {
                "o_ender": {
                    EVENT_CREATE: "steps = 0;\npath_start(pth_line, 10, path_action_restart, true);\n",
                    EVENT_STEP: (
                        "steps += 1;\n"
                        "if (steps == 3) path_end();\n"
                        'trace("ender:" + f3(x) + "," + f3(path_position) + "," + f3(path_speed) + "," + following(path_index));\n'
                    ),
                },
            },
            (("o_ender", 100, 50),),
            (GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),),
            frames=6,
        )
        self.assertEqual(
            trace,
            [
                "ender:0,0,10000,on",
                "ender:10000,250,10000,on",
                "ender:20000,500,10000,none",
                "ender:20000,500,10000,none",
                "ender:20000,500,10000,none",
            ],
        )


if __name__ == "__main__":
    unittest.main()
