"""Instance deactivation in converted games, checked against GameMaker.

GameMaker keeps a room's instances in an active and a deactivated list
(HTML5 runner: yyRoom.js m_Active / m_Deactive, DeactivateInstance and
ActivateInstance; Function_Instance.js instance_deactivate_* and
instance_activate_*). A deactivated instance leaves the active list and its
objects' instance lists at once: it runs no events (its alarms do not count
down), is not drawn, takes part in no collision, and with, instance_exists,
instance_number, instance_find, instance_nearest and the collision and
position queries do not see it, even through its id. It keeps its state, and
its variables can still be read and written through its id. Activation puts
it back at the end of the active list and of its objects' lists.
instance_deactivate_region and instance_activate_region select instances by
their bounding box (or by x/y without a sprite or mask) against a region
whose right and bottom edges are left + width - 1 and top + height - 1; notme
spares the calling instance. A deactivated instance cannot be destroyed, gets
no Room End event, is not carried to the next room even when persistent, and
is discarded with its room.

The Godot node of a deactivated instance stops processing (which also takes
its Area2D out of the physics space) and is not rendered.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_BEGIN_STEP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_ROOM_START,
    EVENT_STEP,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    run_converted_project_rendered,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

EVENT_ALARM_0 = (2, 0)
EVENT_DRAW = (8, 0)
EVENT_ROOM_END = (7, 5)

_Pixel = tuple[int, int, int, int]
_RED: _Pixel = (255, 0, 0, 255)

_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    "\n"
    "function yn(_value) {\n"
    '    return _value ? "y" : "n";\n'
    "}\n"
    "\n"
    "function tags(_obj) {\n"
    '    var _text = "";\n'
    "    with (_obj) {\n"
    '        _text += tag + " ";\n'
    "    }\n"
    "    return _text;\n"
    "}\n"
)


def _tag(name: str) -> str:
    return f'tag = "{name}";\nglobal.{name} = id;\n'


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _object_yy_path(project_dir: Path, object_name: str) -> Path:
    return project_dir / "objects" / object_name / f"{object_name}.yy"


def _set_object_sprite(project_dir: Path, object_name: str, sprite_name: str) -> None:
    path = _object_yy_path(project_dir, object_name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["spriteId"] = {"name": sprite_name, "path": f"sprites/{sprite_name}/{sprite_name}.yy"}
    _write_json(path, data)


def _add_collision_event(project_dir: Path, object_name: str, target: str, source: str) -> None:
    path = _object_yy_path(project_dir, object_name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["eventList"].append(
        {
            "$GMEvent": "v1",
            "%Name": "",
            "collisionObjectId": {"name": target, "path": f"objects/{target}/{target}.yy"},
            "eventNum": 0,
            "eventType": 4,
            "isDnD": False,
            "name": "",
            "resourceType": "GMEvent",
            "resourceVersion": "2.0",
        }
    )
    _write_json(path, data)
    (path.parent / f"Collision_{target}.gml").write_text(source, encoding="utf-8")


def _box_sprite(name: str, size: int, colour: _Pixel) -> GameMakerSprite:
    return GameMakerSprite(name, size, size, frames=([[colour for _x in range(size)] for _y in range(size)],))


def _trace_lines(output: str, prefix: str) -> list[str]:
    return [line.removeprefix(prefix) for line in output.splitlines() if line.startswith(prefix)]


# --- Events, lists and queries ---------------------------------------------------
#
# o_run is created first, so its Step runs before the others' in each step.
# It counts the steps in its Begin Step and drives the scenario from its Step.

_CORE_RUN_STEP = """\
var _t = global.t;
if (_t == 1) {
    instance_deactivate_object(o_parent);
    trace("t1 exists:" + yn(instance_exists(o_parent)) + yn(instance_exists(o_child)) + yn(instance_exists(global.c1)) + yn(instance_exists(o_other)));
    trace("t1 number:" + string(instance_number(o_parent)) + ":" + string(instance_number(all)) + ":" + string(instance_count));
    trace("t1 find:" + yn(instance_find(o_parent, 0) == noone) + ":" + instance_find(all, 1).tag);
    var _n = 0;
    with (o_parent) {
        _n += 1;
    }
    with (global.c1) {
        _n += 10;
    }
    with (all) {
        _n += 100;
    }
    trace("t1 with:" + string(_n));
    trace("t1 nearest:" + instance_nearest(25, 0, all).tag);
    trace("t1 read:" + string(global.c1.x) + ":" + global.c1.tag + ":" + string(global.c1.steps));
    global.c1.marker = 7;
    trace("t1 variable_instance_get:" + string(variable_instance_get(global.c1, "tag")));
    instance_destroy(global.p2);
}
if (_t == 2) {
    trace("t2 marker:" + string(global.c1.marker));
    instance_activate_object(o_child);
    trace("t2 parents:" + tags(o_parent) + "number:" + string(instance_number(o_parent)));
}
if (_t == 3) {
    instance_activate_all();
    trace("t3 parents:" + tags(o_parent) + "all:" + tags(all));
}
if (_t == 6) {
    trace("t6 steps:" + string(global.p1.steps) + ":" + string(global.c1.steps) + ":" + string(global.p2.steps) + ":" + string(global.o1.steps));
    trace("t6 missed draws:" + string(global.o1.draws - global.p1.draws));
    instance_deactivate_all(true);
    trace("t6 number:" + string(instance_number(all)) + ":" + yn(instance_exists(id)));
    instance_activate_object(global.o1);
}
if (_t == 7) {
    trace("t7 o1:" + string(global.o1.steps) + ":" + string(instance_number(all)));
    instance_activate_all();
    var _v = instance_create_depth(0, 0, 0, o_other);
    instance_destroy(_v);
    instance_activate_object(_v);
    trace("t7 destroyed:" + yn(instance_exists(_v)) + ":" + string(instance_number(o_other)));
}
if (_t == 8) {
    instance_deactivate_all(false);
    trace("t8 self:" + yn(instance_exists(id)) + ":" + string(instance_number(all)));
}
if (_t == 9) {
    trace("t9 resumed:" + tags(all));
}
"""

_CORE_PROJECT = GameMakerProject(
    name="DeactivationCore",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: "global.t = 0;\n",
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: _CORE_RUN_STEP,
            },
        ),
        GameMakerObject(
            "o_parent",
            {
                EVENT_CREATE: "steps = 0;\ndraws = 0;\nalarm[0] = 2;\n",
                EVENT_STEP: "steps += 1;\n",
                EVENT_ALARM_0: 'trace("alarm:" + tag + "@" + string(global.t));\n',
                EVENT_DESTROY: 'trace("destroy:" + tag);\n',
                EVENT_DRAW: "draws += 1;\n",
            },
        ),
        GameMakerObject("o_child", {}, parent="o_parent"),
        GameMakerObject(
            "o_other",
            {
                EVENT_CREATE: 'steps = 0;\ndraws = 0;\ntag = "";\n',
                EVENT_STEP: "steps += 1;\n",
                EVENT_DRAW: "draws += 1;\n",
            },
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
                        RoomInstance("inst_run", "o_run", 0, 0, creation_code=_tag("run")),
                        RoomInstance("inst_p1", "o_parent", 10, 0, creation_code=_tag("p1")),
                        RoomInstance("inst_c1", "o_child", 20, 0, creation_code=_tag("c1")),
                        RoomInstance("inst_p2", "o_parent", 30, 0, creation_code=_tag("p2")),
                        RoomInstance("inst_o1", "o_other", 40, 0, creation_code=_tag("o1")),
                    ),
                ),
            ),
            creation_order=("inst_run", "inst_p1", "inst_c1", "inst_p2", "inst_o1"),
        ),
    ),
)

_CORE_EXPECTED = [
    "t1 exists:nnny",
    "t1 number:0:2:2",
    "t1 find:y:o1",
    "t1 with:200",
    "t1 nearest:o1",
    "t1 read:20:c1:0",
    "t1 variable_instance_get:undefined",
    "t2 marker:7",
    "t2 parents:c1 number:1",
    # c1 was active again for the alarm phase of step 3, p1 and p2 only for
    # step 4's: deactivated alarms do not count down.
    "alarm:c1@3",
    "t3 parents:c1 p1 p2 all:run o1 c1 p1 p2 ",
    "alarm:p1@4",
    "alarm:p2@4",
    # p1 and p2 rejoined after step 3's Step events, c1 after step 2's.
    "t6 steps:2:3:2:5",
    "t6 missed draws:2",
    "t6 number:1:y",
    # o1 was deactivated and activated again before its Step event: it
    # stepped once in step 6.
    "t7 o1:6:2",
    "t7 destroyed:n:1",
    "t8 self:n:0",
    "t9 resumed:run o1 c1 p1 p2 ",
]

# The probe reads the Godot state of deactivated and active instance nodes,
# and activates every instance once the runner has deactivated itself.
_CORE_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _states = []
var _seen = {}


func _instance(name):
	return GMRuntime.gml_handle_resolve(GMRuntime.gml_global_scope().get(name))


func _record(label, name):
	var node = _instance(name)
	_states.append(label + ":" + name + ":" + str(node.process_mode) + ":" + str(node.visibility_layer))


func _process(_delta):
	_frames += 1
	if _frames > 120:
		print("DEACTIVATION_TIMEOUT")
		get_tree().quit(1)
		return
	var t = int(GMRuntime.gml_global_scope().get("t", 0))
	if t == 2 and not _seen.has(2):
		_seen[2] = true
		_record("t2", "p1")
		_record("t2", "c1")
		_record("t2", "o1")
	if t == 8:
		if not _seen.has(8):
			_seen[8] = true
			_frames = 100
			return
		if _frames == 103:
			_record("t8", "run")
			_record("t8", "o1")
			GMRuntime.gml_instance_activate_all()
	if t == 9:
		_record("t9", "run")
		_record("t9", "p1")
		print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		print("DEACTIVATION_NODES " + JSON.stringify(_states))
		get_tree().quit(0)
"""

_CORE_NODES_EXPECTED = [
    "t2:p1:4:0",
    "t2:c1:0:1",
    "t2:o1:0:1",
    "t8:run:4:0",
    "t8:o1:4:0",
    "t9:run:0:1",
    "t9:p1:0:1",
]


# --- Regions, collisions and room-to-room behaviour ------------------------------

_REGION_RUN_STEP = """\
var _t = global.t;
if (_t == 1) {
    instance_deactivate_region(100, 100, 100, 100, true, true);
    trace("t1 inside:" + tags(all));
    trace("t1 queries:" + yn(collision_point(105, 105, o_box, false, false) == noone)
        + ":" + instance_position(305, 305, o_box).tag
        + ":" + collision_rectangle(0, 0, 400, 400, o_box, false, false).tag
        + ":" + yn(collision_circle(103, 103, 2, all, false, true) == noone)
        + ":" + instance_nearest(100, 110, o_box).tag);
}
if (_t == 2) {
    instance_activate_region(100, 100, 100, 100, false);
    trace("t2 none:" + tags(all));
    instance_activate_region(100, 100, 100, 100, true);
    trace("t2 all:" + tags(all));
    instance_deactivate_region(100, 100, 100, 100, false, true);
    trace("t2 outside:" + tags(all));
}
if (_t == 3) {
    instance_activate_object(o_box);
    trace("t3 boxes:" + tags(o_box));
}
if (_t == 4) {
    instance_activate_all();
}
if (_t == 5) {
    instance_deactivate_region(100, 100, 100, 100, true, false);
    trace("t5 self:" + yn(instance_exists(id)) + ":" + tags(all));
}
if (_t == 6) {
    trace("t6 resumed:" + tags(all));
}
"""

_REGION_PROJECT = GameMakerProject(
    name="DeactivationRegions",
    scripts={"scr_trace": _SCRIPT},
    sprites=(_box_sprite("spr_box", 10, _RED),),
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: "global.t = 0;\n",
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: _REGION_RUN_STEP,
            },
        ),
        GameMakerObject("o_box", {}),
        GameMakerObject("o_dot", {}),
        GameMakerObject("o_hit", {}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_run", "o_run", 150, 150, creation_code=_tag("run")),
                        RoomInstance("inst_b_in", "o_box", 100, 100, creation_code=_tag("b_in")),
                        # Its origin lies left of the region, its bounding box
                        # reaches into it.
                        RoomInstance("inst_b_edge", "o_box", 95, 130, creation_code=_tag("b_edge")),
                        RoomInstance("inst_b_left", "o_box", 80, 160, creation_code=_tag("b_left")),
                        RoomInstance("inst_b_out", "o_box", 300, 300, creation_code=_tag("b_out")),
                        # No sprite: x/y on the region's last column is inside,
                        # one pixel further is outside.
                        RoomInstance("inst_n_in", "o_dot", 199, 199, creation_code=_tag("n_in")),
                        RoomInstance("inst_n_out", "o_dot", 200, 150, creation_code=_tag("n_out")),
                        RoomInstance("inst_hit", "o_hit", 302, 302, creation_code=_tag("hit")),
                    ),
                ),
            ),
            creation_order=(
                "inst_run",
                "inst_b_in",
                "inst_b_edge",
                "inst_b_left",
                "inst_b_out",
                "inst_n_in",
                "inst_n_out",
                "inst_hit",
            ),
            width=400,
            height=400,
        ),
    ),
)

_REGION_EXPECTED = [
    "t1 inside:run b_left b_out n_out hit ",
    "t1 queries:y:b_out:b_left:y:b_left",
    "hit:b_out@1",
    "t2 none:run b_left b_out n_out hit ",
    "t2 all:run b_left b_out n_out hit b_in b_edge n_in ",
    "t2 outside:run b_in b_edge n_in ",
    "t3 boxes:b_in b_edge b_left b_out ",
    "hit:b_out@4",
    "t5 self:n:b_left b_out n_out hit ",
    # Without the runner, global.t stays 5 until the probe activates it
    # again two steps later.
    "hit:b_out@5",
    "hit:b_out@5",
    "hit:b_out@5",
    "t6 resumed:b_left b_out n_out hit run b_in b_edge n_in ",
    "hit:b_out@6",
]

_REGION_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _states = []
var _paused_at = -1


func _area_state(label, name):
	var node = GMRuntime.gml_handle_resolve(GMRuntime.gml_global_scope().get(name))
	var area = null
	for child in node.get_children():
		if child is Area2D:
			area = child
	var in_space = area != null and PhysicsServer2D.area_get_space(area.get_rid()).is_valid()
	_states.append(label + ":" + name + ":" + str(area.can_process()) + ":" + str(in_space))


func _process(_delta):
	_frames += 1
	if _frames > 120:
		print("DEACTIVATION_TIMEOUT")
		get_tree().quit(1)
		return
	var t = int(GMRuntime.gml_global_scope().get("t", 0))
	if t == 5:
		if _paused_at < 0:
			_paused_at = _frames
		elif _frames == _paused_at + 2:
			_area_state("t5", "b_in")
			_area_state("t5", "b_out")
			GMRuntime.gml_instance_activate_all()
	if t == 6:
		_area_state("t6", "b_in")
		print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		print("DEACTIVATION_AREAS " + JSON.stringify(_states))
		get_tree().quit(0)
"""

_REGION_AREAS_EXPECTED = [
    "t5:b_in:false:false",
    "t5:b_out:true:true",
    "t6:b_in:true:true",
]

_ROOMS_PROJECT = GameMakerProject(
    name="DeactivationRooms",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject(
            "o_ctl",
            {
                EVENT_STEP: (
                    "instance_deactivate_object(o_gone);\n"
                    "instance_deactivate_object(global.plain);\n"
                    "room_goto(r_two);\n"
                ),
            },
        ),
        GameMakerObject("o_keep", {EVENT_ROOM_END: 'trace("room end:keep");\n'}, persistent=True),
        GameMakerObject("o_gone", {EVENT_ROOM_END: 'trace("room end:gone");\n'}, persistent=True),
        GameMakerObject("o_plain", {EVENT_ROOM_END: 'trace("room end:" + tag);\n'}),
        GameMakerObject(
            "o_late",
            {
                EVENT_CREATE: 'trace("create:late");\n',
                EVENT_ROOM_START: 'trace("room start:late");\n',
            },
        ),
        GameMakerObject(
            "o_check",
            {
                # Placed later, o_late is registered but not yet created.
                EVENT_CREATE: "instance_deactivate_object(o_late);\n",
                EVENT_ROOM_START: 'trace("room start:check");\n',
                EVENT_STEP: (
                    'if (variable_global_exists("checked")) exit;\n'
                    "global.checked = true;\n"
                    'trace("r_two keep:" + string(instance_number(o_keep))'
                    ' + " gone:" + string(instance_number(o_gone)) + yn(instance_exists(global.gone))'
                    ' + " plain:" + string(instance_number(o_plain)) + yn(instance_exists(global.plain)));\n'
                    "instance_activate_object(global.gone);\n"
                    "instance_activate_all();\n"
                    'trace("r_two activated:" + string(instance_number(o_gone)) + yn(instance_exists(global.gone))'
                    ' + ":" + string(instance_number(all)));\n'
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_keep", "o_keep", 0, 0, creation_code=_tag("keep")),
                        RoomInstance("inst_gone", "o_gone", 0, 0, creation_code=_tag("gone")),
                        RoomInstance("inst_plain", "o_plain", 0, 0, creation_code=_tag("plain")),
                        RoomInstance("inst_plain2", "o_plain", 0, 0, creation_code=_tag("plain2")),
                        RoomInstance("inst_ctl", "o_ctl", 0, 0, creation_code=_tag("ctl")),
                    ),
                ),
            ),
            creation_order=("inst_keep", "inst_gone", "inst_plain", "inst_plain2", "inst_ctl"),
        ),
        GameMakerRoom(
            "r_two",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_check", "o_check", 0, 0, creation_code=_tag("check")),
                        RoomInstance("inst_late", "o_late", 0, 0, creation_code=_tag("late")),
                    ),
                ),
            ),
            creation_order=("inst_check", "inst_late"),
        ),
    ),
)

_ROOMS_EXPECTED = [
    "room end:keep",
    "room end:plain2",
    # A deactivated instance placed in the room still gets its Create event,
    # but no Room Start.
    "create:late",
    "room start:check",
    "r_two keep:1 gone:0n plain:0n",
    "r_two activated:0n:3",
]

_ROOMS_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames > 120:
		print("DEACTIVATION_TIMEOUT")
		get_tree().quit(1)
		return
	if GMRuntime.gml_global_scope().has("checked"):
		print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


# --- A step list built afresh ----------------------------------------------------
#
# Other parts of the runtime may empty the step list and set its creation mark
# back to 0 between steps (a persistent room left or entered again), expecting
# the next step to take in every live instance again. Instances that were in
# the list before keep stepping, and an instance that was deactivated while it
# was still in the list joins the list again once it is activated (at the end,
# like a new instance).

EVENT_END_STEP = (3, 2)

_RESET_PROJECT = GameMakerProject(
    name="DeactivationStepReset",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: "global.t = 0;\n",
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: (
                    'trace("run:" + string(global.t));\n'
                    "if (global.t == 2) instance_deactivate_object(global.b);\n"
                ),
                EVENT_END_STEP: "if (global.t == 3) instance_activate_object(global.b);\n",
            },
        ),
        GameMakerObject("o_cnt", {EVENT_STEP: 'trace(tag + ":" + string(global.t));\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_run", "o_run", 0, 0, creation_code=_tag("run")),
                        RoomInstance("inst_a", "o_cnt", 0, 0, creation_code=_tag("a")),
                        RoomInstance("inst_b", "o_cnt", 0, 0, creation_code=_tag("b")),
                        RoomInstance("inst_c", "o_cnt", 0, 0, creation_code=_tag("c")),
                    ),
                ),
            ),
            creation_order=("inst_run", "inst_a", "inst_b", "inst_c"),
        ),
    ),
)

_RESET_EXPECTED = [
    "run:1",
    "a:1",
    "b:1",
    "c:1",
    "run:2",
    "a:2",
    "c:2",
    # The step list is emptied here.
    "run:3",
    "a:3",
    "c:3",
    "run:4",
    "a:4",
    "c:4",
    "b:4",
    "run:5",
    "a:5",
    "c:5",
    "b:5",
]

_RESET_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _reset = false


func _process(_delta):
	_frames += 1
	var t = int(GMRuntime.gml_global_scope().get("t", 0))
	if not _reset and t >= 2:
		_reset = true
		print("DEACTIVATION_RESET " + str(t) + ":" + str(GMRuntime._gml_step_running))
		GMRuntime._gml_step_entries = []
		GMRuntime._gml_step_infos = []
		GMRuntime._gml_step_creation_mark = 0
	if t >= 5 or _frames > 60:
		print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


# --- A persistent room keeps its deactivated instances -----------------------------
#
# Only a room that is not persistent deletes its deactivated instances when it
# ends (yyRoom.js ClearInstances, which _GameMaker.js StartRoom runs only for
# such a room); persistent instances move on from the active list only. A
# persistent room keeps its deactivated list, persistent instances in it too,
# and instance_activate_* in another room does not reach it (they look at the
# current room's list). Back in the room, the instances are still deactivated
# (no Room Start); activated, they run their events again, an alarm that
# stopped counting down while they were deactivated included.

_PARKED_RUN_STEP = """\
var _t = global.t;
if (_t == 1) {
    instance_deactivate_object(global.sleeper);
    instance_deactivate_object(global.pkeep);
    room_goto(r_away);
}
if (_t == 2) {
    instance_activate_all();
    trace("away:" + string(instance_number(o_sleeper)) + yn(instance_exists(global.sleeper))
        + ":" + string(instance_number(o_pkeep)) + yn(instance_exists(global.pkeep))
        + ":" + string(instance_number(all)));
}
if (_t == 3) {
    room_goto(r_hub);
}
if (_t == 4) {
    trace("hub:" + string(instance_number(o_sleeper)) + yn(instance_exists(global.sleeper))
        + ":" + string(instance_number(o_pkeep)) + yn(instance_exists(global.pkeep)));
    instance_activate_object(global.sleeper);
    instance_activate_object(o_pkeep);
    trace("hub activated:" + string(instance_number(o_sleeper)) + yn(instance_exists(global.sleeper))
        + ":" + string(instance_number(o_pkeep)) + yn(instance_exists(global.pkeep))
        + ":" + string(instance_number(all)));
}
"""

_PARKED_PROJECT = GameMakerProject(
    name="DeactivationPersistentRoom",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: "global.t = 0;\n",
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: _PARKED_RUN_STEP,
                EVENT_END_STEP: "if (global.t == 6) global.done = true;\n",
            },
            persistent=True,
        ),
        GameMakerObject(
            "o_sleeper",
            {
                EVENT_CREATE: "alarm[0] = 2;\n",
                EVENT_ROOM_START: 'trace("room start:" + tag + "@" + string(global.t));\n',
                EVENT_ALARM_0: 'trace("alarm:" + tag + "@" + string(global.t));\n',
                EVENT_STEP: 'trace("step:" + tag + "@" + string(global.t));\n',
            },
        ),
        GameMakerObject(
            "o_pkeep",
            {
                EVENT_ROOM_START: 'trace("room start:" + tag + "@" + string(global.t));\n',
                EVENT_STEP: 'trace("step:" + tag + "@" + string(global.t));\n',
            },
            persistent=True,
        ),
        GameMakerObject("o_mark", {}),
    ),
    rooms=(
        GameMakerRoom(
            "r_hub",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_run", "o_run", 0, 0, creation_code=_tag("run")),
                        RoomInstance("inst_sleeper", "o_sleeper", 0, 0, creation_code=_tag("sleeper")),
                        RoomInstance("inst_pkeep", "o_pkeep", 0, 0, creation_code=_tag("pkeep")),
                    ),
                ),
            ),
            creation_order=("inst_run", "inst_sleeper", "inst_pkeep"),
            persistent=True,
        ),
        GameMakerRoom(
            "r_away",
            layers=(
                InstanceLayer("Instances", 0, (RoomInstance("inst_mark", "o_mark", 0, 0, creation_code=_tag("mark")),)),
            ),
            creation_order=("inst_mark",),
        ),
    ),
)

_PARKED_EXPECTED = [
    "room start:sleeper@0",
    "room start:pkeep@0",
    "away:0n:0n:2",
    "hub:0n:0n",
    "hub activated:1y:1y:3",
    # Activated during the Step, they join the step after it.
    "alarm:sleeper@5",
    "step:sleeper@5",
    "step:pkeep@5",
    "step:sleeper@6",
    "step:pkeep@6",
]

_PARKED_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames > 120:
		print("DEACTIVATION_TIMEOUT")
		get_tree().quit(1)
		return
	if GMRuntime.gml_global_scope().has("done"):
		print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


# --- game_restart ---------------------------------------------------------------------
#
# game_restart ends the game first (_GameMaker.js Run_EndGame empties the
# active and the deactivated list, and every persistent room starts afresh):
# deactivated instances go, those of the current room and of a persistent
# room that was left alike. The first room then starts with only its own
# instances, each stepping once per step.

_RESTART_RUN_STEP = """\
var _t = global.t;
trace("run" + string(global.runs) + ":" + string(_t));
if (global.runs == 1 && _t == 1) {
    instance_deactivate_object(global.b);
    room_goto(r_away);
}
if (global.runs == 1 && _t == 2) {
    instance_deactivate_object(global.c);
    game_restart();
}
if (global.runs == 2 && _t == 1) {
    trace("count:" + string(instance_number(all)) + ":" + string(instance_number(o_cnt)));
    instance_activate_all();
    trace("activated:" + string(instance_number(all)) + ":" + string(instance_number(o_cnt)));
}
"""

_RESTART_PROJECT = GameMakerProject(
    name="DeactivationRestart",
    scripts={"scr_trace": _SCRIPT},
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: (
                    'global.runs = (variable_global_exists("runs") ? global.runs : 0) + 1;\nglobal.t = 0;\n'
                ),
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: _RESTART_RUN_STEP,
                EVENT_END_STEP: "if (global.runs == 2 && global.t == 2) global.done = true;\n",
            },
            persistent=True,
        ),
        GameMakerObject("o_cnt", {EVENT_STEP: 'trace(tag + string(global.runs) + ":" + string(global.t));\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_hub",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_run", "o_run", 0, 0, creation_code=_tag("run")),
                        RoomInstance("inst_a", "o_cnt", 0, 0, creation_code=_tag("a")),
                        RoomInstance("inst_b", "o_cnt", 0, 0, creation_code=_tag("b")),
                    ),
                ),
            ),
            creation_order=("inst_run", "inst_a", "inst_b"),
            persistent=True,
        ),
        GameMakerRoom(
            "r_away",
            layers=(
                InstanceLayer("Instances", 0, (RoomInstance("inst_c", "o_cnt", 0, 0, creation_code=_tag("c")),)),
            ),
            creation_order=("inst_c",),
        ),
    ),
)

_RESTART_EXPECTED = [
    "run1:1",
    "run1:2",
    "run2:1",
    "count:3:2",
    "activated:3:2",
    "a2:1",
    "b2:1",
    "run2:2",
    "a2:2",
    "b2:2",
]


# --- Layers and what is drawn ------------------------------------------------------

_LAYERS_RUN_STEP = """\
var _t = global.t;
if (_t == 1) {
    instance_deactivate_layer("Front");
    trace("t1 front off:" + tags(o_box));
}
if (_t == 2) {
    instance_activate_layer("Front");
    trace("t2 front on:" + tags(o_box));
    instance_deactivate_layer(layer_get_id("Back"));
    trace("t2 back off:" + tags(o_box));
}
"""

_LAYERS_PROJECT = GameMakerProject(
    name="DeactivationLayers",
    scripts={"scr_trace": _SCRIPT},
    sprites=(_box_sprite("spr_box", 16, _RED),),
    objects=(
        GameMakerObject(
            "o_run",
            {
                EVENT_CREATE: "global.t = 0;\n",
                EVENT_BEGIN_STEP: "global.t += 1;\n",
                EVENT_STEP: _LAYERS_RUN_STEP,
            },
        ),
        GameMakerObject("o_box", {}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer("Control", -100, (RoomInstance("inst_run", "o_run", 0, 0, creation_code=_tag("run")),)),
                InstanceLayer(
                    "Front",
                    0,
                    (
                        RoomInstance("inst_f1", "o_box", 8, 8, creation_code=_tag("f1")),
                        RoomInstance("inst_f2", "o_box", 40, 8, creation_code=_tag("f2")),
                    ),
                ),
                InstanceLayer("Back", 100, (RoomInstance("inst_b1", "o_box", 72, 8, creation_code=_tag("b1")),)),
            ),
            creation_order=("inst_run", "inst_f1", "inst_f2", "inst_b1"),
        ),
    ),
)

_LAYERS_EXPECTED = [
    "t1 front off:b1 ",
    "t2 front on:b1 f1 f2 ",
    "t2 back off:f1 f2 ",
]

# Once Back is deactivated, b1's sprite is no longer rendered while f1's is.
_LAYERS_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0
var _checked_at = -1


func _process(_delta):
	_frames += 1
	if _frames > 120:
		print("DEACTIVATION_TIMEOUT")
		get_tree().quit(1)
		return
	if int(GMRuntime.gml_global_scope().get("t", 0)) < 2:
		return
	if _checked_at < 0:
		_checked_at = _frames
		return
	if _frames < _checked_at + 3:
		return
	var pixels = "headless"
	var viewport = get_viewport()
	var image = viewport.get_texture().get_image() if DisplayServer.get_name() != "headless" else null
	if image != null and not image.is_empty() and Vector2(image.get_size()) == viewport.get_visible_rect().size:
		var to_screen = viewport.get_canvas_transform()
		var front = Vector2i(to_screen * Vector2(16, 16))
		var back = Vector2i(to_screen * Vector2(80, 16))
		pixels = str(image.get_pixelv(front).r8) + ":" + str(image.get_pixelv(back).r8)
	print("DEACTIVATION_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
	print("DEACTIVATION_PIXELS " + pixels)
	get_tree().quit(0)
"""


class TestInstanceDeactivationGodot(unittest.TestCase):
    def _run(self, godot_dir: Path, probe: str) -> str:
        godot_binary = find_smoke_godot_binary()
        assert godot_binary is not None
        add_probe_autoload(godot_dir, probe)
        result = run_converted_project(godot_binary, godot_dir)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("SCRIPT ERROR", output)
        return output

    def setUp(self) -> None:
        if find_smoke_godot_binary() is None:
            self.skipTest("Godot binary not available")

    def test_deactivated_instances_leave_events_lists_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _CORE_PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            output = self._run(root / "godot", _CORE_PROBE)

        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _CORE_EXPECTED)
        nodes = _trace_lines(output, "DEACTIVATION_NODES ")
        self.assertEqual(len(nodes), 1, output)
        self.assertEqual(json.loads(nodes[0]), _CORE_NODES_EXPECTED)

    def test_regions_select_by_bounding_box_and_skip_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gamemaker_dir = root / "gamemaker"
            write_gamemaker_project(gamemaker_dir, _REGION_PROJECT)
            for object_name in ("o_box", "o_hit"):
                _set_object_sprite(gamemaker_dir, object_name, "spr_box")
            _add_collision_event(
                gamemaker_dir, "o_hit", "o_box", 'trace("hit:" + other.tag + "@" + string(global.t));\n'
            )
            convert_gamemaker_project(gamemaker_dir, root / "godot")
            godot_binary = find_smoke_godot_binary()
            assert godot_binary is not None
            import_converted_project(godot_binary, root / "godot")
            output = self._run(root / "godot", _REGION_PROBE)

        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _REGION_EXPECTED)
        areas = _trace_lines(output, "DEACTIVATION_AREAS ")
        self.assertEqual(len(areas), 1, output)
        self.assertEqual(json.loads(areas[0]), _REGION_AREAS_EXPECTED)

    def test_room_change_discards_deactivated_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _ROOMS_PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            output = self._run(root / "godot", _ROOMS_PROBE)

        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _ROOMS_EXPECTED)

    def test_persistent_room_keeps_its_deactivated_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PARKED_PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            output = self._run(root / "godot", _PARKED_PROBE)

        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _PARKED_EXPECTED)

    def test_game_restart_drops_deactivated_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _RESTART_PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            output = self._run(root / "godot", _PARKED_PROBE)

        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _RESTART_EXPECTED)

    def test_step_list_built_afresh_takes_in_every_live_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _RESET_PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            output = self._run(root / "godot", _RESET_PROBE)

        self.assertEqual(_trace_lines(output, "DEACTIVATION_RESET "), ["2:false"], output)
        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _RESET_EXPECTED)

    def test_layers_deactivate_and_hide_their_instances(self) -> None:
        godot_binary = find_smoke_godot_binary()
        assert godot_binary is not None
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gamemaker_dir = root / "gamemaker"
            write_gamemaker_project(gamemaker_dir, _LAYERS_PROJECT)
            _set_object_sprite(gamemaker_dir, "o_box", "spr_box")
            convert_gamemaker_project(gamemaker_dir, root / "godot")
            import_converted_project(godot_binary, root / "godot")
            add_probe_autoload(root / "godot", _LAYERS_PROBE)
            result = run_converted_project_rendered(godot_binary, root / "godot")
            if result is None:
                result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        traces = _trace_lines(output, "DEACTIVATION_TRACE ")
        self.assertEqual(len(traces), 1, output)
        self.assertEqual(json.loads(traces[0]), _LAYERS_EXPECTED)
        pixels = _trace_lines(output, "DEACTIVATION_PIXELS ")
        self.assertEqual(len(pixels), 1, output)
        if pixels[0] != "headless":
            # f1 (active) is drawn in red; b1 (deactivated) is not drawn.
            front, back = (int(value) for value in pixels[0].split(":"))
            self.assertGreater(front, 200, output)
            self.assertLess(back, 128, output)


if __name__ == "__main__":
    unittest.main()
