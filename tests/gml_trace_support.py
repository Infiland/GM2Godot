"""Run GML in a converted project and read back what it traced.

A test gives the GML scripts and the events of one object (placed in a room by
itself); the object calls trace("...") and the helper returns the traced
strings in order. The project is converted with every converter enabled and
run headless, so the result is what the converted game does.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from tests.gamemaker_project_support import (
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
from tests.godot_test_support import find_smoke_godot_binary

TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

_TRACE_MARKER = "GML_TRACE "

_PROBE = f"""extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 6:
		print("{_TRACE_MARKER}" + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


def run_gml_trace(
    test_case: unittest.TestCase,
    scripts: Mapping[str, str],
    events: Mapping[tuple[int, int], str],
    *,
    objects: tuple[GameMakerObject, ...] = (),
    compatibility_scripts: tuple[str, ...] = (),
) -> list[str]:
    """Convert and run a project; return what the GML traced, in order.

    ``events`` belong to the object ``o_main``, which is the only instance in
    the first room. ``objects`` are further objects the project defines, and
    ``compatibility_scripts`` names the scripts saved as pre-2.3 compatibility
    scripts (every other script is a 2.3+ script).
    """
    godot_binary = find_smoke_godot_binary()
    if godot_binary is None:
        test_case.skipTest("Godot binary not available")
    project = GameMakerProject(
        name="GmlTrace",
        scripts={"scr_trace": TRACE_SCRIPT, **scripts},
        compatibility_scripts=compatibility_scripts,
        objects=(GameMakerObject("o_main", events), *objects),
        rooms=(
            GameMakerRoom(
                "r_main",
                layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_main", "o_main", 0, 0),)),),
                creation_order=("inst_main",),
            ),
        ),
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        write_gamemaker_project(root / "gamemaker", project)
        logs = convert_gamemaker_project(root / "gamemaker", root / "godot")
        add_probe_autoload(root / "godot", _PROBE)
        result = run_converted_project(godot_binary, root / "godot")
    output = result.stdout + result.stderr
    test_case.assertEqual([line for line in logs if "Could not" in line], [])
    test_case.assertEqual(result.returncode, 0, output)
    test_case.assertNotIn("SCRIPT ERROR", output)
    trace_lines = [line for line in output.splitlines() if line.startswith(_TRACE_MARKER)]
    test_case.assertEqual(len(trace_lines), 1, output)
    return json.loads(trace_lines[0].removeprefix(_TRACE_MARKER))
