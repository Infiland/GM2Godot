"""Godot checks that every GameMaker built-in instance variable works in converted objects.

Every instance has GameMaker's built-in variables (manual: Instance Variables,
Timelines, Sequences), so object code may read and assign them directly. An
undeclared name makes Godot reject the whole object script, so the object
would lose every event.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_transpiler_parts.constants import BUILTIN_VARIABLE_REGISTRY
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
from tests.godot_test_support import find_smoke_godot_binary

_INSTANCE_BUILTINS = sorted(
    name
    for name, metadata in BUILTIN_VARIABLE_REGISTRY.items()
    if metadata.scope == "instance" and not metadata.is_array
)
# Assigning these changes the instance's layer, which the reader checks.
_NOT_REASSIGNED = {"depth", "layer"}
_WRITABLE_BUILTINS = [
    name
    for name in _INSTANCE_BUILTINS
    if BUILTIN_VARIABLE_REGISTRY[name].mutable and name not in _NOT_REASSIGNED
]

_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    "\n"
    "function own_layer() {\n"
    "    return layer;\n"
    "}\n"
)

_READER_CREATE = (
    "var _all = [" + ", ".join(_INSTANCE_BUILTINS) + "];\n"
    'trace("read:" + string(array_length(_all)));\n'
    'trace("layer:" + (layer == layer_get_id("Instances") ? "room layer" : "other"));\n'
    'trace("script layer:" + (own_layer() == layer ? "same" : "other"));\n'
    'trace("timeline:" + (timeline_index == -1 ? "none" : "set") + ":" + string(timeline_position) + ":"'
    ' + string(timeline_speed) + ":" + (timeline_running ? "running" : "stopped") + ":"'
    ' + (timeline_loop ? "loop" : "once"));\n'
    'trace("sequence:" + (in_sequence ? "in" : "out") + ":" + (drawn_by_sequence ? "drawn" : "self") + ":"'
    ' + (is_undefined(sequence_instance) ? "undefined" : "set"));\n'
    "var _child = instance_create_layer(x, y, layer, o_child);\n"
    'trace("child:" + (_child.layer == layer ? "same layer" : "other"));\n'
    "var _deep = instance_create_depth(x, y, -5, o_child);\n"
    'trace("depth child:" + (_deep.layer == -1 ? "managed" : "layer"));\n'
    'layer = layer_get_id("Above");\n'
    'trace("moved:" + (layer == layer_get_id("Above") ? "above" : "other") + ":" + string(depth));\n'
    "var _made = layer_create(-1000);\n"
    "layer = _made;\n"
    'trace("created:" + (layer == _made ? "new layer" : "other") + ":" + string(depth));\n'
    'trace("still exists:" + (instance_exists(id) ? "yes" : "no"));\n'
    "depth = 7;\n"
    'trace("own depth:" + (layer == -1 ? "managed" : "layer"));\n'
)

_WRITER_CREATE = "".join(f"{name} = {name};\n" for name in _WRITABLE_BUILTINS) + (
    "timeline_position = 4;\n"
    "timeline_speed = 2;\n"
    "timeline_loop = true;\n"
    'trace("wrote:" + string(timeline_position) + ":" + string(timeline_speed) + ":"'
    ' + (timeline_loop ? "loop" : "once"));\n'
)

_PROJECT = GameMakerProject(
    name="InstanceBuiltins",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject("o_reader", {EVENT_CREATE: _READER_CREATE}),
        GameMakerObject("o_writer", {EVENT_CREATE: _WRITER_CREATE}),
        GameMakerObject("o_child", {}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer("Above", -100, ()),
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_reader", "o_reader", 16, 16),
                        RoomInstance("inst_writer", "o_writer", 32, 16),
                    ),
                ),
            ),
            creation_order=("inst_reader", "inst_writer"),
        ),
    ),
)

_EXPECTED_TRACE = [
    f"read:{len(_INSTANCE_BUILTINS)}",
    "layer:room layer",
    "script layer:same",
    "timeline:none:0:1:stopped:once",
    "sequence:out:self:undefined",
    "child:same layer",
    "depth child:managed",
    "moved:above:-100",
    "created:new layer:-1000",
    "still exists:yes",
    "own depth:managed",
    "wrote:4:2:loop",
]

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 6:
		print("INSTANCE_BUILTINS_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestInstanceBuiltinVariablesGodot(unittest.TestCase):
    def test_objects_read_and_assign_every_builtin_instance_variable(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("Parse Error", output)
        self.assertNotIn("SCRIPT ERROR", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("INSTANCE_BUILTINS_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("INSTANCE_BUILTINS_TRACE ")), _EXPECTED_TRACE)


if __name__ == "__main__":
    unittest.main()
