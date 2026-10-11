from __future__ import annotations

import json
import re
import tempfile
import unittest
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
from tests.godot_test_support import find_smoke_godot_binary

# A child object's script declares the variables its own events assign when
# no ancestor script can declare them already (an ancestor declares what its
# events and the project's scripts assign). Everything else the child reads
# and writes through the runtime, so the variables behave the same either
# way, also when other objects change them.
_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    "\n"
    "function set_from_script() {\n"
    "    scripted = 7;\n"
    "}\n"
)

_BASE_CREATE = "hp = 10; // the leaves set shine\n"
_MID_CREATE = "event_inherited();\narmour = hp div 2;\nmid_only = 1;\nset_from_script();\n"
_LEAF_CREATE = (
    "event_inherited();\n"
    "hp += 5;\n"
    "mid_only += 1;\n"
    "leaf_only = armour * 2;\n"
    "shine = 3;\n"
    "scripted += 1;\n"
)
_LEAF_STEP = "leaf_only += 1;\n"
_RUNNER_STEP = """\
if (variable_global_exists("variables_done")) exit;
global.variables_done = true;
with (o_leaf) {
    leaf_only += 100;
    other.seen = leaf_only;
}
trace("seen:" + string(seen));
trace("leaf:" + string(o_leaf.hp) + ":" + string(o_leaf.armour) + ":" + string(o_leaf.mid_only)
    + ":" + string(o_leaf.leaf_only) + ":" + string(o_leaf.shine) + ":" + string(o_leaf.scripted));
trace("mid:" + string(o_mid.hp) + ":" + string(o_mid.armour) + ":" + string(o_mid.mid_only)
    + ":" + (variable_instance_exists(o_mid, "leaf_only") ? "leaf_only" : "no leaf_only"));
var _leaf = instance_find(o_leaf, 0);
variable_instance_set(_leaf, "leaf_only", 1);
trace("set:" + string(variable_instance_get(_leaf, "leaf_only")));
"""

_PROJECT = GameMakerProject(
    name="ChildObjectVariables",
    scripts={"scr_variables": _SCRIPT},
    objects=(
        GameMakerObject("o_base", {EVENT_CREATE: _BASE_CREATE}),
        GameMakerObject("o_mid", {EVENT_CREATE: _MID_CREATE}, parent="o_base"),
        GameMakerObject("o_leaf", {EVENT_CREATE: _LEAF_CREATE, EVENT_STEP: _LEAF_STEP}, parent="o_mid"),
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
                        RoomInstance("inst_mid", "o_mid", 20, 0),
                        RoomInstance("inst_leaf", "o_leaf", 10, 0),
                        RoomInstance("inst_run", "o_runner", 0, 0),
                    ),
                ),
            ),
            # o_mid.<variable> reads o_mid's first instance, children
            # included: the o_mid instance comes first.
            creation_order=("inst_mid", "inst_leaf", "inst_run"),
        ),
    ),
)

# The runner's first step comes after the leaf's (creation order): leaf_only
# is 10 from Create, 11 after that step, 111 after the with.
_EXPECTED_TRACE = [
    "seen:111",
    "leaf:15:5:2:111:3:8",
    "mid:10:5:1:no leaf_only",
    "set:1",
]

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("CHILD_VARIABLES_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


def _declared_members(script: str) -> set[str]:
    return set(re.findall(r"^var ([A-Za-z_][A-Za-z0-9_]*)$", script, flags=re.MULTILINE))


class TestChildObjectVariablesGodot(unittest.TestCase):
    def test_child_objects_declare_their_own_variables(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            scripts = {
                name: (root / "godot" / "objects" / name / f"{name}.gd").read_text(encoding="utf-8")
                for name in ("o_base", "o_mid", "o_leaf")
            }
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertTrue({"hp", "scripted"} <= _declared_members(scripts["o_base"]))
        self.assertEqual(_declared_members(scripts["o_mid"]), {"armour", "mid_only"})
        # shine appears in o_base's code, so o_base could declare it.
        self.assertEqual(_declared_members(scripts["o_leaf"]), {"leaf_only"})
        self.assertIn("\tleaf_only = GMRuntime.gml_add(leaf_only, 1)", scripts["o_leaf"])
        self.assertIn('GMRuntime.gml_variable_instance_set(self, "shine", 3)', scripts["o_leaf"])

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("CHILD_VARIABLES_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        self.assertEqual(json.loads(trace_lines[0].removeprefix("CHILD_VARIABLES_TRACE ")), _EXPECTED_TRACE)


if __name__ == "__main__":
    unittest.main()
