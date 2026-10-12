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
    "function str_bool(_value) {\n"
    '    return _value ? "yes" : "no";\n'
    "}\n"
    "function pts(_path) {\n"
    '    var _text = "";\n'
    "    for (var _i = 0; _i < path_get_number(_path); _i++) {\n"
    '        _text += f3(path_get_point_x(_path, _i)) + " " + f3(path_get_point_y(_path, _i)) + " "'
    ' + f3(path_get_point_speed(_path, _i)) + ";";\n'
    "    }\n"
    "    return _text;\n"
    "}\n"
)
# What the end action tests trace: x, y, path_position, path_speed (times
# 1000) and whether the instance still follows a path.
_PATH_STATE = (
    'f3(x) + "," + f3(y) + "," + f3(path_position) + "," + f3(path_speed) + "," + following(path_index)'
)


# Builds and edits paths at run time, tracing them (Create of o_editor).
_EDITING_GML = """\
var p = path_add();
trace("new:" + str_bool(path_exists(p)) + "," + (path_get_closed(p) ? "closed" : "open")
    + "," + string(path_get_kind(p)) + "," + string(path_get_precision(p))
    + "," + string(path_get_number(p)) + "," + f3(path_get_length(p)) + "," + path_get_name(p) + ".");
path_add_point(p, 0, 0, 100);
path_add_point(p, 30, 0, 100);
path_add_point(p, 30, 40, 50);
trace("closed:" + f3(path_get_length(p)) + "," + f3(path_get_x(p, 0.9)) + "," + f3(path_get_y(p, 0.9))
    + "," + f3(path_get_speed(p, 0.9)));
path_set_closed(p, false);
trace("open:" + f3(path_get_length(p)));
path_insert_point(p, 1, 10, 0, 100);
path_change_point(p, 3, 30, 20, 100);
path_delete_point(p, 0);
trace("edit:" + pts(p));
path_insert_point(p, 9, 0, 0, 100);
path_delete_point(p, -1);
path_change_point(p, 3, 0, 0, 0);
trace("ignored:" + pts(p));
var q = path_duplicate(p);
path_reverse(q);
path_append(q, p);
trace("dup:" + str_bool(q != p) + "," + pts(q) + f3(path_get_length(q)));
path_shift(q, 5, -5);
trace("shift:" + pts(q));
path_rescale(q, 2, 0.5);
trace("rescale:" + pts(q));
path_rotate(q, 90);
trace("rotate:" + pts(q));
path_flip(q);
trace("flip:" + pts(q));
path_mirror(q);
trace("mirror:" + pts(q));
path_set_kind(q, 1);
path_set_precision(q, 2);
trace("smooth:" + string(path_get_kind(q)) + "," + string(path_get_precision(q)) + "," + f3(path_get_length(q))
    + "," + f3(path_get_x(q, 0.3)) + "," + f3(path_get_y(q, 0.3)));
path_set_kind(q, 5);
path_set_precision(q, 12);
trace("clamp:" + string(path_get_kind(q)) + "," + string(path_get_precision(q)));
path_assign(q, pth_line);
trace("assign:" + path_get_name(q) + "," + (path_get_closed(q) ? "closed" : "open") + "," + pts(q)
    + f3(path_get_length(q)));
path_clear_points(p);
trace("clear:" + string(path_get_number(p)) + "," + f3(path_get_length(p)) + "," + str_bool(path_exists(p)));
path_delete(p);
trace("delete:" + str_bool(path_exists(p)) + "," + str_bool(path_exists(q)));
"""


# Plans paths through an mp_grid with a wall at column 2 (open in the bottom
# row) and a blocked cell at (4, 1) (Create of o_planner).
_GRID_GML = """\
var g = mp_grid_create(10, 20, 6, 5, 16, 16);
for (var v = 0; v < 4; v++) mp_grid_add_cell(g, 2, v);
mp_grid_add_cell(g, 4, 1);
var p = path_add();
path_add_point(p, 999, 999, 50);
var ok = mp_grid_path(g, p, 13.7, 25.2, 90.9, 30.5, false);
trace("straight:" + str_bool(ok) + "," + (path_get_closed(p) ? "closed" : "open") + "," + pts(p) + f3(path_get_length(p)));
ok = mp_grid_path(g, p, 13.7, 25.2, 90.9, 30.5, true);
trace("diagonal:" + str_bool(ok) + "," + pts(p) + f3(path_get_length(p)));
ok = mp_grid_path(g, p, 13, 25, 42, 30, true);
trace("blocked:" + str_bool(ok) + "," + string(path_get_number(p)));
ok = mp_grid_path(g, p, 9, 25, 90, 30, true);
trace("outside:" + str_bool(ok) + "," + string(path_get_number(p)));
ok = mp_grid_path(g, p, 13, 25, 13, 25, true);
trace("same:" + str_bool(ok) + "," + pts(p));
"""

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

    def test_friction_and_gravity_act_before_the_path_and_speed_after_path_end(self) -> None:
        # Each step GameMaker applies friction and gravity, then the path
        # (which leaves speed 0, so gravity does not pull a path follower off
        # its path), then Path End, then moves the instance by hspeed/vspeed:
        # a speed set in Path End moves the instance in that same step, before
        # friction slows it (yyInstance.js UpdatePositions).
        trace = self._run_trace(
            {
                "o_heavy": {
                    EVENT_CREATE: "gravity = 1;\npath_start(pth_line, 10, path_action_stop, true);\n",
                    EVENT_STEP: 'trace("heavy:" + f3(x) + "," + f3(y) + "," + f3(speed) + "," + f3(vspeed));\n',
                    EVENT_PATH_END: 'trace("heavy_end:" + f3(x) + "," + f3(y) + "," + f3(speed) + "," + f3(vspeed));\n',
                },
                "o_launch": {
                    EVENT_CREATE: "friction = 1;\npath_start(pth_line, 20, path_action_stop, true);\n",
                    EVENT_STEP: 'trace("launch:" + f3(x) + "," + f3(speed) + "," + f3(direction));\n',
                    EVENT_PATH_END: 'speed = 5;\ntrace("launch_end:" + f3(x) + "," + f3(speed) + "," + f3(direction));\n',
                },
            },
            (("o_heavy", 100, 50), ("o_launch", 100, 50)),
            (GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),),
            frames=8,
        )
        self.assertEqual(
            [line for line in trace if line.startswith("heavy")],
            [
                "heavy:0,0,0,0",
                "heavy:10000,0,0,0",
                "heavy:20000,0,0,0",
                "heavy:30000,0,0,0",
                "heavy_end:40000,0,0,0",
                "heavy:40000,0,0,0",
                "heavy:40000,1000,1000,1000",
                "heavy:40000,3000,2000,2000",
            ],
        )
        self.assertEqual(
            [line for line in trace if line.startswith("launch")],
            [
                "launch:0,0,0",
                "launch:20000,0,0",
                "launch_end:40000,5000,0",
                "launch:45000,5000,0",
                "launch:49000,4000,0",
                "launch:52000,3000,0",
                "launch:54000,2000,0",
                "launch:55000,1000,0",
            ],
        )

    def test_paths_are_made_and_edited_at_run_time_like_gamemaker(self) -> None:
        # path_add makes an empty closed straight path with precision 4 and
        # no name; the editing functions change its points and settings and
        # rebuild it, ignoring point indices out of range. Rescaling,
        # rotating, flipping and mirroring work around the centre of the
        # points' bounding box, path_assign and path_duplicate copy the name
        # too, and kind and precision are clamped (Function_Path.js,
        # yyPath.js).
        trace = self._run_trace(
            {
                "o_editor": {
                    EVENT_CREATE: _EDITING_GML,
                },
            },
            (("o_editor", 0, 0),),
            (GameMakerPath("pth_line", ((0, 0, 100), (40, 0, 100))),),
            frames=2,
        )
        self.assertEqual(
            trace,
            [
                "new:yes,closed,0,4,0,0,.",
                "closed:120000,7200,9600,88000",
                "open:70000",
                "edit:10000 0 100000;30000 0 100000;30000 20000 100000;",
                "ignored:10000 0 100000;30000 0 100000;30000 20000 100000;",
                "dup:yes,30000 20000 100000;30000 0 100000;10000 0 100000;10000 0 100000;30000 0 100000;"
                "30000 20000 100000;80000",
                "shift:35000 15000 100000;35000 -5000 100000;15000 -5000 100000;15000 -5000 100000;"
                "35000 -5000 100000;35000 15000 100000;",
                "rescale:45000 10000 100000;45000 0 100000;5000 0 100000;5000 0 100000;45000 0 100000;"
                "45000 10000 100000;",
                "rotate:30000 -15000 100000;20000 -15000 100000;20000 25000 100000;20000 25000 100000;"
                "20000 -15000 100000;30000 -15000 100000;",
                "flip:30000 25000 100000;20000 25000 100000;20000 -15000 100000;20000 -15000 100000;"
                "20000 25000 100000;30000 25000 100000;",
                "mirror:20000 25000 100000;30000 25000 100000;30000 -15000 100000;30000 -15000 100000;"
                "30000 25000 100000;20000 25000 100000;",
                "smooth:1,2,82861,29816,6571",
                "clamp:0,8",
                "assign:pth_line,open,0 0 100000;40000 0 100000;40000",
                "clear:0,0,yes",
                "delete:no,yes",
            ],
        )

    def test_instances_follow_paths_made_with_path_add(self) -> None:
        # A path from path_add is closed, so a relative path runs back to
        # where it started. Once its path is deleted an instance stops where
        # it is but keeps path_index.
        follower = (
            "r = path_add();\n"
            "path_add_point(r, 0, 0, 100);\n"
            "path_add_point(r, 0, 40, 100);\n"
            "path_start(r, 10, path_action_stop, false);\n"
            "steps = 0;\n"
        )
        state = (
            'f3(x) + "," + f3(y) + "," + f3(path_position) + "," + str_bool(path_index == r)'
            ' + "," + str_bool(path_exists(r))'
        )
        trace = self._run_trace(
            {
                "o_maker": {
                    EVENT_CREATE: follower,
                    EVENT_STEP: f'trace("maker:" + {state});\n',
                    EVENT_PATH_END: 'trace("maker_end:" + f3(y) + "," + str_bool(path_index == -1));\n',
                },
                "o_dropper": {
                    EVENT_CREATE: follower,
                    EVENT_STEP: f'steps += 1;\nif (steps == 3) path_delete(r);\ntrace("dropper:" + {state});\n',
                },
            },
            (("o_maker", 100, 50), ("o_dropper", 100, 50)),
            (),
            frames=11,
        )
        self.assertEqual(
            [line for line in trace if line.startswith("maker")],
            [
                "maker:100000,50000,0,yes,yes",
                "maker:100000,60000,125,yes,yes",
                "maker:100000,70000,250,yes,yes",
                "maker:100000,80000,375,yes,yes",
                "maker:100000,90000,500,yes,yes",
                "maker:100000,80000,625,yes,yes",
                "maker:100000,70000,750,yes,yes",
                "maker:100000,60000,875,yes,yes",
                "maker_end:50000,yes",
                "maker:100000,50000,1000,no,yes",
                "maker:100000,50000,1000,no,yes",
            ],
        )
        self.assertEqual(
            [line for line in trace if line.startswith("dropper")],
            ["dropper:100000,50000,0,yes,yes", "dropper:100000,60000,125,yes,yes"]
            + ["dropper:100000,70000,250,yes,no"] * 8,
        )

    def test_mp_grid_path_writes_the_path_gamemaker_plans(self) -> None:
        # mp_grid_path searches the grid breadth first (left, right, up,
        # down, then the diagonals whose two neighbouring cells are free) and
        # replaces the path's points with an open path from the start
        # position through the centres of the cells in between to the goal
        # position, all as whole numbers (Function_MotionPlanning.js). It
        # leaves the path alone when the goal is blocked or the start is off
        # the grid.
        trace = self._run_trace(
            {"o_planner": {EVENT_CREATE: _GRID_GML}},
            (("o_planner", 0, 0),),
            (),
            frames=2,
        )
        self.assertEqual(
            trace,
            [
                "straight:yes,open,13000 25000 100000;18000 44000 100000;18000 60000 100000;18000 76000 100000;"
                "18000 92000 100000;34000 92000 100000;50000 92000 100000;66000 92000 100000;66000 76000 100000;"
                "66000 60000 100000;66000 44000 100000;66000 28000 100000;82000 28000 100000;90000 30000 100000;"
                "203893",
                "diagonal:yes,13000 25000 100000;34000 44000 100000;34000 60000 100000;34000 76000 100000;"
                "34000 92000 100000;50000 92000 100000;66000 92000 100000;82000 76000 100000;98000 60000 100000;"
                "98000 44000 100000;90000 30000 100000;185699",
                "blocked:no,11",
                "outside:no,11",
                "same:yes,13000 25000 100000;13000 25000 100000;",
            ],
        )


if __name__ == "__main__":
    unittest.main()
