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

EVENT_PATH_END = (7, 8)

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
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


if __name__ == "__main__":
    unittest.main()
