"""instance_change turns an instance into an instance of another object.

As instance_change_RELEASE in the HTML5 runner (functions/Function_Instance.js)
does it: with perf true the instance runs its Destroy and Clean Up events,
then it takes the new object's events, object_index, parents, mask, solid and
persistent flags and sprite (SetObjectIndex and UpdateSpriteIndex in
yyInstance.js), keeping its id, variables, position, depth, image values and
xstart/ystart; with perf true the new object's Create event runs last.

A converted object's events are its node's script, and Godot cannot replace
the script of a node while one of its methods runs. So the switch, and the
new object's Create event, happen as soon as the event that called
instance_change returns to the runtime: the rest of that event still sees the
old object (the "after change" and "with pending" lines below; in GameMaker
they would come after the new Create event and print false).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CLEAN_UP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_DRAW,
    EVENT_STEP,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    collision_event,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_RED = (255, 0, 0, 255)
_GREEN = (0, 255, 0, 255)
_BLUE = (0, 0, 255, 255)


def _frames(colour: tuple[int, int, int, int], size: int) -> tuple[list[list[tuple[int, int, int, int]]], ...]:
    return tuple([[colour] * size for _row in range(size)] for _frame in range(2))


_SCRIPT = """\
function trace(_text) {
    if (!variable_global_exists("trace")) global.trace = [];
    if (!variable_global_exists("done")) global.done = false;
    if (!global.done) array_push(global.trace, _text);
}
"""

_FROM_CREATE = """\
hp = 3;
image_xscale = 2;
image_angle = 45;
image_speed = 0;
image_index = 1;
trace("from create " + string(x));
"""
_FROM_STEP = """\
x += 1;
trace("from step " + string(x));
if (mode == 1) {
    instance_change(o_to, true);
    trace("after change " + string(x) + " " + string(object_index == o_from));
} else if (mode == 2) {
    instance_change(o_to, false);
}
"""
_TO_CREATE = 'trace("to create " + string(x) + " hp=" + string(hp) + " other=" + string(other.id == id));\n'
_TO_STEP = """\
if (x == 31) extra += 1;
trace("to step " + string(x) + " hp=" + string(hp));
"""
_SPAWN_CREATE = """\
hp = 7;
trace("spawn create");
instance_change(o_to, true);
trace("spawn after change");
"""
_CTRL_STEP = """\
if (global.ctrl_step == 0) {
    var _spawned = instance_create_depth(50, 0, 0, o_spawn);
    trace("created is o_to " + string(_spawned.object_index == o_to) + " count " + string(instance_number(o_to)));
    with (global.with_target) instance_change(o_to, true);
    trace("with pending " + string(global.with_target.object_index == o_from));
} else if (global.ctrl_step == 1) {
    var _a = global.perf_target;
    trace("perf " + string(_a.object_index == o_to) + " " + string(_a.sprite_index == s_to) + " "
        + string(_a.image_xscale) + " " + string(_a.image_angle) + " " + string(_a.image_index) + " "
        + string(_a.image_speed) + " " + string(_a.xstart) + " " + string(_a.hp) + " " + string(_a.id == global.perf_id));
    var _b = global.noperf_target;
    trace("noperf " + string(_b.object_index == o_to) + " " + string(_b.sprite_index == s_to) + " "
        + string(_b.xstart) + " " + string(_b.hp));
    trace("with extra " + string(global.with_target.extra));
    trace("counts " + string(instance_number(o_from)) + " " + string(instance_number(o_to)) + " "
        + string(instance_number(o_base)));
    global.done = true;
}
global.ctrl_step += 1;
"""

_PROJECT = GameMakerProject(
    name="InstanceChange",
    scripts={"scr_trace": _SCRIPT},
    sprites=(
        GameMakerSprite("s_from", 2, 2, frames=_frames(_RED, 2)),
        GameMakerSprite("s_to", 4, 4, frames=_frames(_GREEN, 4)),
    ),
    objects=(
        GameMakerObject("o_base", {}),
        GameMakerObject(
            "o_from",
            {
                EVENT_CREATE: _FROM_CREATE,
                EVENT_STEP: _FROM_STEP,
                EVENT_DESTROY: 'trace("from destroy " + string(x));\n',
                EVENT_CLEAN_UP: 'trace("from cleanup " + string(x));\n',
            },
            parent="o_base",
            sprite="s_from",
        ),
        GameMakerObject(
            "o_to",
            {EVENT_CREATE: _TO_CREATE, EVENT_STEP: _TO_STEP, EVENT_DESTROY: 'trace("to destroy");\n'},
            sprite="s_to",
        ),
        GameMakerObject("o_spawn", {EVENT_CREATE: _SPAWN_CREATE}),
        GameMakerObject("o_ctrl", {EVENT_CREATE: "global.ctrl_step = 0;\n", EVENT_STEP: _CTRL_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance(
                            "inst_perf", "o_from", 10, 0,
                            creation_code="mode = 1;\nglobal.perf_target = id;\nglobal.perf_id = id;\n",
                        ),
                        RoomInstance("inst_noperf", "o_from", 20, 0, creation_code="mode = 2;\nglobal.noperf_target = id;\n"),
                        RoomInstance("inst_with", "o_from", 30, 0, creation_code="mode = 0;\nglobal.with_target = id;\nextra = 5;\n"),
                        RoomInstance("inst_code", "o_from", 40, 0, creation_code="mode = 0;\ninstance_change(o_to, true);\n"),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_perf", "inst_noperf", "inst_with", "inst_code", "inst_ctrl"),
        ),
    ),
)

_EXPECTED_TRACE = [
    "from create 10",
    "from create 20",
    "from create 30",
    # Instance creation code runs after the Create event.
    "from create 40",
    "from destroy 40",
    "from cleanup 40",
    "to create 40 hp=3 other=true",
    # First step.
    "from step 11",
    "from destroy 11",
    "from cleanup 11",
    "after change 11 true",
    "to create 11 hp=3 other=true",
    # perf false: no Destroy, Clean Up or Create event.
    "from step 21",
    "from step 31",
    "to step 40 hp=3",
    "spawn create",
    "spawn after change",
    "to create 50 hp=7 other=true",
    "created is o_to true count 4",
    "from destroy 31",
    "from cleanup 31",
    "with pending true",
    "to create 31 hp=3 other=true",
    # Second step: every changed instance runs o_to's Step event.
    "to step 11 hp=3",
    "to step 21 hp=3",
    "to step 31 hp=3",
    "to step 40 hp=3",
    "perf true true 2 45 1 0 10 3 true",
    "noperf true true 20 3",
    "with extra 6",
    "counts 0 5 0",
]

# A wall with a Draw event becomes a brick, which has none, in a Collision
# event: the brick's Create event runs before the frame's Draw event, its sprite
# is drawn by default, and the next collision runs the brick's Collision event.
_COLLISION_PROJECT = GameMakerProject(
    name="InstanceChangeCollision",
    scripts={"scr_trace": _SCRIPT},
    sprites=(
        GameMakerSprite("s_ball", 4, 4, frames=_frames(_RED, 4)),
        GameMakerSprite("s_wall", 4, 4, frames=_frames(_GREEN, 4)),
        GameMakerSprite("s_brick", 4, 4, frames=_frames(_BLUE, 4)),
    ),
    objects=(
        GameMakerObject("o_ball", {}, sprite="s_ball"),
        GameMakerObject(
            "o_wall",
            {
                EVENT_DRAW: 'draw_self();\ntrace("wall draw");\n',
                collision_event("o_ball"): (
                    'trace("wall hit " + string(object_index == o_wall));\ninstance_change(o_brick, true);\n'
                ),
            },
            sprite="s_wall",
        ),
        GameMakerObject(
            "o_brick",
            {
                EVENT_CREATE: 'trace("brick create " + string(sprite_index == s_brick));\n',
                collision_event("o_ball"): 'trace("brick hit");\nglobal.done = true;\n',
            },
            sprite="s_brick",
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
                        RoomInstance("inst_wall", "o_wall", 100, 0, creation_code="global.wall = id;\n"),
                        RoomInstance("inst_ball", "o_ball", 101, 1),
                    ),
                ),
            ),
            creation_order=("inst_wall", "inst_ball"),
        ),
    ),
)

_COLLISION_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("INSTANCE_CHANGE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		var node = GMRuntime.gml_handle_resolve(GMRuntime.gml_global_scope().get("wall"))
		var children = []
		for child in node.get_children():
			children.append([str(child.name), child.visible])
		print("INSTANCE_CHANGE_NODES " + JSON.stringify([node.get_script().resource_path.get_file(), children]))
		get_tree().quit(0)
"""

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("INSTANCE_CHANGE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		var nodes = {}
		for key in ["perf_target", "noperf_target", "with_target"]:
			var node = GMRuntime.gml_handle_resolve(GMRuntime.gml_global_scope().get(key))
			var children = []
			for child in node.get_children():
				children.append([str(child.name), child.visible])
			nodes[key] = [node.get_script().resource_path.get_file(), children]
		print("INSTANCE_CHANGE_NODES " + JSON.stringify(nodes))
		get_tree().quit(0)
"""


class TestInstanceChangeGodot(unittest.TestCase):
    def _run(self, project: GameMakerProject, probe: str) -> tuple[object, object]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", probe)
            import_converted_project(godot_binary, root / "godot")
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        found: dict[str, object] = {}
        for tag in ("INSTANCE_CHANGE_TRACE", "INSTANCE_CHANGE_NODES"):
            lines = [line for line in output.splitlines() if line.startswith(tag + " ")]
            self.assertEqual(len(lines), 1, output)
            found[tag] = json.loads(lines[0].removeprefix(tag + " "))
        return found["INSTANCE_CHANGE_TRACE"], found["INSTANCE_CHANGE_NODES"]

    def test_instance_change_switches_object_and_keeps_the_instance(self) -> None:
        trace, nodes = self._run(_PROJECT, _PROBE)

        self.assertEqual(trace, _EXPECTED_TRACE)
        # The nodes run o_to's script and show o_to's sprite.
        expected_node = ["o_to.gd", [["s_to", True]]]
        self.assertEqual(
            nodes, {"perf_target": expected_node, "noperf_target": expected_node, "with_target": expected_node}
        )

    def test_instance_change_in_a_collision_event(self) -> None:
        trace, node = self._run(_COLLISION_PROJECT, _COLLISION_PROBE)

        self.assertEqual(trace, ["wall hit true", "brick create true", "brick hit"])
        # The brick has no Draw event, so its sprite shows again.
        self.assertEqual(node, ["o_brick.gd", [["s_brick", True]]])


if __name__ == "__main__":
    unittest.main()
