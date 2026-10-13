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


def trace_probe(*, declarations: str = "", each_frame: str = "", final: str = "") -> str:
    """The probe autoload that prints the trace on the sixth frame.

    ``declarations`` are extra member variables, ``each_frame`` runs on every
    frame after the frame count is raised and ``final`` just before the trace
    is printed; both are GDScript lines indented with one tab. ``trace`` adds a
    line to the trace.
    """
    return (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var _frames = 0\n"
        f"{declarations}\n\n"
        "func trace(text):\n"
        "\tvar lines = GMRuntime.gml_global_scope().get(\"trace\", [])\n"
        "\tlines.append(text)\n"
        "\tGMRuntime.gml_global_scope()[\"trace\"] = lines\n\n\n"
        "func _process(_delta):\n"
        "\t_frames += 1\n"
        f"{each_frame}"
        "\tif _frames == 6:\n"
        f"{final}"
        f'\t\tprint("{_TRACE_MARKER}" + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))\n'
        "\t\tget_tree().quit(0)\n"
    )


_PROBE = trace_probe()


def run_gml_trace(
    test_case: unittest.TestCase,
    scripts: Mapping[str, str],
    events: Mapping[tuple[int, int], str],
    *,
    objects: tuple[GameMakerObject, ...] = (),
    compatibility_scripts: tuple[str, ...] = (),
    probe: str | None = None,
    timeout: float = 120,
    output_lines: list[str] | None = None,
) -> list[str]:
    """Convert and run a project; return what the GML traced, in order.

    ``events`` belong to the object ``o_main``, which is the only instance in
    the first room. ``objects`` are further objects the project defines, and
    ``compatibility_scripts`` names the scripts saved as pre-2.3 compatibility
    scripts (every other script is a 2.3+ script).
    ``probe`` replaces the probe autoload (see ``trace_probe``). A list passed
    as ``output_lines`` receives everything the run printed (what
    show_debug_message wrote, say).
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
        add_probe_autoload(root / "godot", probe or _PROBE)
        result = run_converted_project(godot_binary, root / "godot", timeout=timeout)
    output = result.stdout + result.stderr
    if output_lines is not None:
        output_lines.extend(output.splitlines())
    test_case.assertEqual([line for line in logs if "Could not" in line], [])
    test_case.assertEqual(result.returncode, 0, output)
    test_case.assertNotIn("SCRIPT ERROR", output)
    trace_lines = [line for line in output.splitlines() if line.startswith(_TRACE_MARKER)]
    test_case.assertEqual(len(trace_lines), 1, output)
    return json.loads(trace_lines[0].removeprefix(_TRACE_MARKER))
