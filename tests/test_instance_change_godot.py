"""instance_change turns an instance into an instance of another object.

As instance_change_RELEASE in the HTML5 runner (functions/Function_Instance.js)
does it: with perf true the instance runs its Destroy and Clean Up events,
then it takes the new object's events, object_index, parents, mask, solid,
visible and persistent flags and sprite (SetObjectIndex and UpdateSpriteIndex in
yyInstance.js), keeping its id, variables, position, depth, image values and
xstart/ystart; with perf true the new object's Create event runs last.

A converted object's events are its node's script, and Godot cannot replace
the script of a node while one of its methods runs. So the switch, and the
new object's Create event, happen as soon as the event that called
instance_change returns to the runtime: the rest of that event still sees the
old object (the "after change", "with pending" and "after o_a" lines below; in
GameMaker they would come after the new Create event and print false or o_b).
What the rest of the event assigns is assigned again after the Create event,
and its instance_change and instance_destroy calls wait for the first change.
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

# An object's visible flag starts each instance and comes with
# instance_change (SetObjectIndex in yyInstance.js), whether or not perf is
# true: o_hidden is not visible, and an o_shown instance made invisible
# becomes visible again when it changes into o_shown.
_VISIBLE_PROJECT = GameMakerProject(
    name="InstanceChangeVisible",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject("o_hidden", {EVENT_CREATE: 'trace("hidden create " + string(visible));\n'}, visible=False),
        GameMakerObject("o_shown", {}),
        GameMakerObject("o_plain", {EVENT_CREATE: "instance_change(o_hidden, false);\n"}),
        GameMakerObject("o_perf", {EVENT_CREATE: "instance_change(o_hidden, true);\n"}),
        GameMakerObject("o_back", {EVENT_CREATE: "visible = false;\ninstance_change(o_shown, false);\n"}),
        GameMakerObject(
            "o_ctrl",
            {EVENT_STEP: 'with (all) trace(object_get_name(object_index) + " " + string(visible));\nglobal.done = true;\n'},
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
                        RoomInstance("inst_hidden", "o_hidden", 0, 0),
                        RoomInstance("inst_plain", "o_plain", 0, 0),
                        RoomInstance("inst_perf", "o_perf", 0, 0),
                        RoomInstance("inst_back", "o_back", 0, 0),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_hidden", "inst_plain", "inst_perf", "inst_back", "inst_ctrl"),
        ),
    ),
)

_TRACE_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		print("INSTANCE_CHANGE_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		print("INSTANCE_CHANGE_NODES []")
		get_tree().quit(0)
"""

# An instance that asks for instance_change and then for instance_destroy, or
# for a second instance_change, in the same event: GameMaker runs these on the
# object the instance has changed into (the change and its Create event are
# done by then), so in the converted game they wait for the first change.
_ORDER_STEP = """\
steps += 1;
if (steps == mode) {
    if (mode == 1) {
        instance_change(o_b, true);
        instance_destroy();
    } else if (mode == 2) {
        instance_change(o_b, false);
        instance_change(o_c, true);
    }
}
"""


_ORDER_CTRL_STEP = """\
global.ctrl_step += 1;
if (global.ctrl_step == 3) {
    trace("counts " + string(instance_number(o_a)) + " " + string(instance_number(o_b)) + " "
        + string(instance_number(o_c)));
    global.done = true;
}
"""


def _order_object(name: str, step: str | None = None) -> GameMakerObject:
    short = name.removeprefix("o_")
    events: dict[tuple[int, int | str], str] = {
        EVENT_CREATE: f'trace("{short} create " + string(mode));\n',
        EVENT_DESTROY: f'trace("{short} destroy " + string(mode));\n',
        EVENT_CLEAN_UP: f'trace("{short} cleanup " + string(mode));\n',
    }
    if step is not None:
        events[EVENT_CREATE] = "steps = 0;\n"
        events[EVENT_STEP] = step
    return GameMakerObject(name, events)


_ORDER_PROJECT = GameMakerProject(
    name="InstanceChangeOrder",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        _order_object("o_a", _ORDER_STEP),
        _order_object("o_b"),
        _order_object("o_c"),
        GameMakerObject("o_ctrl", {EVENT_CREATE: "global.ctrl_step = 0;\n", EVENT_STEP: _ORDER_CTRL_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_destroy", "o_a", 0, 0, creation_code="mode = 1;\n"),
                        RoomInstance("inst_twice", "o_a", 0, 0, creation_code="mode = 2;\n"),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_destroy", "inst_twice", "inst_ctrl"),
        ),
    ),
)


# Code after instance_change in the same event. In GameMaker it runs after
# the change and the new object's Create event; in the converted game it runs
# first, on the old object, but what it assigns is assigned again after the
# Create event, and the Create event sees the values from before the call.
# An instance whose Create event changes it runs its creation code as the new
# object.
_AFTER_A_STEP = """\
if (global.phase == 1) {
    instance_change(o_b, true);
    sprite_index = s_c;
    hp = 99;
    gone = 1;
    x = 70;
    visible = false;
    trace("after " + object_get_name(object_index));
}
"""
_AFTER_B_CREATE = """\
trace("b create hp=" + string(hp) + " gone=" + string(variable_instance_exists(id, "gone")));
maxhp = hp * 2;
hp = 10;
sprite_index = s_b2;
x = 5;
"""
_AFTER_CTRL_STEP = """\
global.phase += 1;
if (global.phase == 3) {
    with (o_b) {
        trace(tag + " " + object_get_name(object_index) + " " + sprite_get_name(sprite_index) + " hp=" + string(hp)
            + " maxhp=" + string(maxhp) + " x=" + string(x) + " visible=" + string(visible));
        if (tag == "step") trace("name " + name);
    }
    global.done = true;
}
"""

_AFTER_PROJECT = GameMakerProject(
    name="InstanceChangeAfter",
    scripts={"scr_trace": _SCRIPT},
    sprites=tuple(
        GameMakerSprite(name, 2, 2, frames=_frames(colour, 2))
        for name, colour in (("s_a", _RED), ("s_b", _GREEN), ("s_b2", _BLUE), ("s_c", _RED))
    ),
    objects=(
        GameMakerObject("o_a", {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _AFTER_A_STEP}, sprite="s_a"),
        GameMakerObject("o_b", {EVENT_CREATE: _AFTER_B_CREATE}, sprite="s_b"),
        GameMakerObject("o_m", {EVENT_CREATE: "hp = 4;\ninstance_change(o_b, true);\n"}, sprite="s_a"),
        GameMakerObject("o_n", {EVENT_CREATE: "hp = 5;\n"}, sprite="s_a"),
        GameMakerObject("o_ctrl", {EVENT_CREATE: "global.phase = 0;\n", EVENT_STEP: _AFTER_CTRL_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_step", "o_a", 10, 0, creation_code='tag = "step";\nname = "bob";\n'),
                        RoomInstance(
                            "inst_create",
                            "o_m",
                            20,
                            0,
                            creation_code=(
                                'tag = "create";\n'
                                'trace("code " + object_get_name(object_index) + " hp=" + string(hp));\n'
                                "hp = 50;\n"
                            ),
                        ),
                        RoomInstance(
                            "inst_code",
                            "o_n",
                            30,
                            0,
                            creation_code='tag = "code";\ninstance_change(o_b, true);\nsprite_index = s_c;\nhp = 77;\n',
                        ),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_step", "inst_create", "inst_code", "inst_ctrl"),
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

    def test_destroy_and_second_change_wait_for_a_pending_change(self) -> None:
        trace, _nodes = self._run(_ORDER_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                # instance_change(o_b, true); instance_destroy();
                "a destroy 1",
                "a cleanup 1",
                "b create 1",
                "b destroy 1",
                "b cleanup 1",
                # instance_change(o_b, false); instance_change(o_c, true);
                "b destroy 2",
                "b cleanup 2",
                "c create 2",
                "counts 0 0 1",
            ],
        )

    def test_assignments_after_instance_change_follow_the_create_event(self) -> None:
        trace, _nodes = self._run(_AFTER_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                # o_m's Create event changes it to o_b; its creation code then
                # runs as o_b.
                "b create hp=4 gone=false",
                "code o_b hp=10",
                # The creation code changes o_n to o_b and assigns sprite_index
                # and hp after the call.
                "b create hp=5 gone=false",
                # In GameMaker "b create hp=3 gone=false" would come first and
                # the rest of the event would see o_b.
                "after o_a",
                "b create hp=3 gone=false",
                "step o_b s_c hp=99 maxhp=6 x=70 visible=false",
                # A variable called name is the game's own too.
                "name bob",
                "create o_b s_b2 hp=50 maxhp=8 x=5 visible=true",
                "code o_b s_c hp=77 maxhp=10 x=5 visible=true",
            ],
        )

    def test_instance_change_takes_the_objects_visible_flag(self) -> None:
        trace, _nodes = self._run(_VISIBLE_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                "hidden create false",
                "hidden create false",
                "o_hidden false",
                "o_hidden false",
                "o_hidden false",
                "o_shown true",
                "o_ctrl true",
            ],
        )


if __name__ == "__main__":
    unittest.main()
