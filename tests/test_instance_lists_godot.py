from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_DESTROY,
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
from tests.godot_test_support import find_smoke_godot_binary

_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    "\n"
    "function count_with(_obj) {\n"
    "    var _n = 0;\n"
    "    with (_obj) {\n"
    "        _n += 1;\n"
    "    }\n"
    "    return _n;\n"
    "}\n"
)

# GameMaker keeps each object's instances, children included, in creation
# order: with visits them in that order, object.x reads the first of them,
# instance_find counts through them and instance_nearest keeps the first of
# equally near ones. with works on the instances that existed when it
# started. An instance still exists during its own Destroy event and is gone
# as soon as instance_destroy returns.
_RUNNER_STEP = """\
if (variable_global_exists("lists_done")) exit;
global.lists_done = true;
var _order = "";
with (o_parent) {
    _order += string(x) + " ";
}
trace("with_parent:" + _order);
trace("first_x:" + string(o_parent.x));
trace("child_first_x:" + string(o_child.x));
trace("find_1:" + string(instance_find(o_parent, 1).x));
trace("count:" + string(instance_number(o_parent)) + ":" + string(instance_number(o_child)));
trace("empty:" + (instance_exists(o_empty) ? "yes" : "no") + ":" + string(instance_number(o_empty)));
var _visits = 0;
with (o_parent) {
    _visits += 1;
    if (_visits == 1) {
        instance_create_depth(50, 0, 0, o_child);
    }
}
trace("with_snapshot:" + string(_visits) + ":" + string(instance_number(o_parent)));
trace("nearest_tie:" + string(instance_nearest(25, 0, o_parent).x));
trace("furthest_tie:" + string(instance_furthest(30, 0, o_parent).x));
var _victim = instance_find(o_victim, 0);
instance_destroy(_victim);
trace("after_destroy:" + (instance_exists(_victim) ? "yes" : "no") + ":" + string(instance_number(o_victim)));
instance_destroy(instance_find(o_parent, 0));
trace("first_after_destroy:" + string(o_parent.x));
_order = "";
with (o_parent) {
    _order += string(x) + " ";
}
trace("with_after_destroy:" + _order);
"""

_VICTIM_DESTROY = (
    'trace("destroy:self=" + (instance_exists(id) ? "yes" : "no")\n'
    '    + ":count=" + string(instance_number(o_victim))\n'
    '    + ":with=" + string(count_with(o_victim)));\n'
)

_PROJECT = GameMakerProject(
    name="InstanceLists",
    scripts={"scr_lists": _SCRIPT},
    objects=(
        GameMakerObject("o_parent", {}),
        GameMakerObject("o_child", {}, parent="o_parent"),
        GameMakerObject("o_empty", {}),
        GameMakerObject("o_victim", {EVENT_DESTROY: _VICTIM_DESTROY}),
        GameMakerObject("o_runner", {EVENT_STEP: _RUNNER_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_p1", "o_parent", 10, 0),
                        RoomInstance("inst_c1", "o_child", 20, 0),
                        RoomInstance("inst_p2", "o_parent", 30, 0),
                        RoomInstance("inst_c2", "o_child", 40, 0),
                        RoomInstance("inst_v1", "o_victim", 100, 0),
                        RoomInstance("inst_v2", "o_victim", 110, 0),
                        RoomInstance("inst_run", "o_runner", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_p1", "inst_c1", "inst_p2", "inst_c2", "inst_v1", "inst_v2", "inst_run"),
        ),
    ),
)

_EXPECTED_TRACE = [
    "with_parent:10 20 30 40 ",
    "first_x:10",
    "child_first_x:20",
    "find_1:20",
    "count:4:2",
    "empty:no:0",
    "with_snapshot:4:5",
    "nearest_tie:20",
    "furthest_tie:10",
    "destroy:self=yes:count=2:with=2",
    "after_destroy:no:1",
    "first_after_destroy:20",
    "with_after_destroy:20 30 40 50 ",
]

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("INSTANCE_LISTS_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


class TestInstanceListsGodot(unittest.TestCase):
    def test_instance_lists_follow_gamemaker_order_and_lifetime(self) -> None:
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
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("INSTANCE_LISTS_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("INSTANCE_LISTS_TRACE ")), _EXPECTED_TRACE)


if __name__ == "__main__":
    unittest.main()
