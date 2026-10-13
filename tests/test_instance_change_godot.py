"""instance_change turns an instance into an instance of another object.

As instance_change_RELEASE in the HTML5 runner (functions/Function_Instance.js)
does it: with perf true the instance runs its Destroy and Clean Up events,
then it takes the new object's events, object_index, parents, mask, solid,
visible and persistent flags and sprite (SetObjectIndex and UpdateSpriteIndex in
yyInstance.js), keeping its id, variables, position, depth, image values and
xstart/ystart; with perf true the new object's Create event runs last.

A converted object's events are its node's script, and Godot cannot replace
the script of a node while a method of that script that uses the node's
members runs. An instance_change statement of a Create, Step, Alarm,
collision, input, Game Start, Room Start or Animation End event is therefore
converted with the rest of the event as a function, which the runtime runs
after the change and the new Create event, as GameMaker does; so is the rest
of a child's event after an event_inherited() that reaches such a statement of
its parent. Any other instance_change (in a script function, a with block,
creation code) changes the object once the event returns: the rest of that
event still sees the old object (the "with pending" and "after o_a" lines
below), what it assigns is assigned again after the Create event, and its
instance_change and instance_destroy calls wait for the first change. The
converter warns where code meets the instance after such a call, also after a
call of a script function that runs instance_change.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from tests.gamemaker_project_support import (
    EVENT_CLEAN_UP,
    EVENT_CREATE,
    EVENT_DESTROY,
    EVENT_DRAW,
    EVENT_GAME_START,
    EVENT_ROOM_START,
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
    "to create 11 hp=3 other=true",
    # The rest of the event runs on the new object.
    "after change 11 false",
    # perf false: no Destroy, Clean Up or Create event.
    "from step 21",
    "from step 31",
    "to step 40 hp=3",
    "spawn create",
    "to create 50 hp=7 other=true",
    "spawn after change",
    "created is o_to true count 4",
    # A with block changes the object once the event returns.
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
                    'trace("wall after " + string(object_index == o_brick) + " " + string(instance_exists(other)));\n'
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


# Code after instance_change in the same event, or in an instance's creation
# code, runs after the change and the new object's Create event; the Create
# event sees the values from before the call. An instance whose Create event
# changes it runs its creation code as the new object.
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
                        RoomInstance(
                            "inst_keep",
                            "o_n",
                            40,
                            0,
                            creation_code=(
                                'tag = "keep";\nvar _s = sprite_index;\ninstance_change(o_b, true);\n'
                                "sprite_index = _s;\nhp = hp + 1;\n"
                            ),
                        ),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_step", "inst_create", "inst_code", "inst_keep", "inst_ctrl"),
        ),
    ),
)

# The rest of an event after instance_change runs on the new object, after
# its Create event, so that what the event assigns wins, also an assignment of
# the value the variable had at the call (the common "keep the sprite" idiom),
# and what it reads comes from the new object.
_RUN_STEP = """\
steps += 1;
if (steps != 1) exit;
if (mode == 1) {
    var _s = sprite_index;
    var _i = image_index;
    instance_change(o_d1, false);
    sprite_index = _s;
    image_index = _i;
    trace("m1 " + sprite_get_name(sprite_index) + " " + object_get_name(object_index));
} else if (mode == 2) {
    hp = 3;
    speed = 0;
    visible = true;
    instance_change(o_d2, true);
    hp = 3;
    speed = 0;
    visible = true;
    trace("m2 hp=" + string(hp) + " speed=" + string(speed) + " visible=" + string(visible));
} else if (mode == 3) {
    list = [1];
    var _l = list;
    instance_change(o_d3, true);
    list = _l;
    array_push(list, 3);
    trace("m3 " + string(array_length(list)) + " " + string(list[0]) + " " + string(list[1]));
} else if (mode == 4) {
    instance_change(o_d4, true);
    trace("m4 " + object_get_name(object_index) + " " + string(instance_number(o_d4)) + " "
        + string(instance_exists(o_d4)));
    hp = 99;
    sprite_index = s_c;
    x += 5;
    y -= 8;
    alarm[1] = 30;
    dst_only += 1;
    trace("m4 hp=" + string(hp) + " " + sprite_get_name(sprite_index) + " x=" + string(x) + " y=" + string(y)
        + " alarm=" + string(alarm[1]) + " dst_only=" + string(dst_only));
} else if (mode == 5) {
    instance_change(o_d5, true);
    instance_destroy();
    trace("m5 " + string(instance_exists(id)));
} else if (mode >= 6 and mode <= 8) {
    if (mode == 6) { instance_change(o_d6a, true); }
    if (mode == 7) { instance_change(o_d6b, true); }
    hp = 7;
    trace("m" + string(mode) + " " + object_get_name(object_index) + " hp=" + string(hp));
} else if (mode == 9) {
    scr_become(o_d9);
    y -= 8;
} else if (mode == 10) {
    // Two changes in a row: the second one is made on the first one's object.
    instance_change(o_d10a, false);
    trace("m10 " + object_get_name(object_index));
    instance_change(o_d10b, true);
}
"""
_RUN_BECOME = """\
function scr_become(_object) {
    instance_change(_object, true);
}
"""
_PARENT_STEP = """\
if (steps == 0) {
    steps = 1;
    instance_change(o_d11, true);
    hp = 1;
}
"""
_CHILD_STEP = """\
event_inherited();
trace("child ran");
"""
_CONTINUE_CTRL_STEP = """\
global.ctrl_step += 1;
if (global.ctrl_step == 3) {
    with (all) {
        if (variable_instance_exists(id, "report")) trace(report + " " + object_get_name(object_index)
            + " " + sprite_get_name(sprite_index) + " hp=" + string(hp) + " speed=" + string(speed)
            + " visible=" + string(visible) + " x=" + string(x) + " y=" + string(y)
            + " n=" + (variable_instance_exists(id, "list") ? string(array_length(list)) : "-"));
    }
    global.done = true;
}
"""


def _continue_target(name: str, create: str, *, visible: bool = True) -> GameMakerObject:
    return GameMakerObject(
        name,
        {
            EVENT_CREATE: create + f'trace("{name} create");\n',
            EVENT_DESTROY: f'trace("{name} destroy");\n',
        },
        sprite="s_b",
        visible=visible,
    )


_CONTINUE_PROJECT = GameMakerProject(
    name="InstanceChangeContinue",
    scripts={"scr_trace": _SCRIPT, "scr_become": _RUN_BECOME},
    sprites=tuple(
        GameMakerSprite(name, 2, 2, frames=_frames(colour, 2))
        for name, colour in (("s_a", _RED), ("s_b", _GREEN), ("s_c", _BLUE))
    ),
    objects=(
        GameMakerObject(
            "o_run",
            {EVENT_CREATE: "steps = 0;\nhp = 0;\nimage_speed = 0;\n", EVENT_STEP: _RUN_STEP},
            sprite="s_a",
        ),
        _continue_target("o_d1", ""),
        _continue_target("o_d2", "hp = 10;\nspeed = 5;\n", visible=False),
        _continue_target("o_d3", "list = [];\n"),
        _continue_target("o_d4", "hp = 10;\nx = 0;\nalarm[1] = 60;\ndst_only = 5;\n"),
        _continue_target("o_d5", ""),
        _continue_target("o_d6a", "hp = 1;\n"),
        _continue_target("o_d6b", "hp = 2;\n"),
        _continue_target("o_d9", "x = 0;\nhp = 3;\n"),
        _continue_target("o_d10a", ""),
        _continue_target("o_d10b", ""),
        _continue_target("o_d11", "hp = 11;\n"),
        _continue_target("o_d12", "hp = 10;\n"),
        _continue_target("o_d13", ""),
        GameMakerObject("o_parent", {EVENT_CREATE: "steps = 0;\nhp = 0;\n", EVENT_STEP: _PARENT_STEP}, sprite="s_a"),
        GameMakerObject("o_child", {EVENT_STEP: _CHILD_STEP}, parent="o_parent", sprite="s_a"),
        GameMakerObject(
            "o_creating",
            {
                EVENT_CREATE: (
                    "hp = 4;\ninstance_change(o_d12, true);\nhp = hp + 1;\n"
                    'trace("creating " + object_get_name(object_index) + " hp=" + string(hp));\n'
                )
            },
        ),
        GameMakerObject(
            "o_alarm",
            {
                EVENT_CREATE: "alarm[0] = 1;\n",
                (2, 0): 'instance_change(o_d13, true);\ntrace("alarm " + object_get_name(object_index));\n',
            },
        ),
        GameMakerObject("o_ctrl", {EVENT_CREATE: "global.ctrl_step = 0;\n", EVENT_STEP: _CONTINUE_CTRL_STEP}),
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    tuple(
                        RoomInstance(
                            f"inst_{mode}",
                            "o_run",
                            100,
                            50,
                            creation_code=f"mode = {mode};\n" + (f'report = "r{mode}";\n' if mode in (1, 2, 3, 4, 9) else ""),
                        )
                        for mode in range(1, 11)
                    )
                    + (
                        RoomInstance("inst_child", "o_child", 0, 0, creation_code='report = "child";\n'),
                        RoomInstance("inst_creating", "o_creating", 0, 0),
                        RoomInstance("inst_alarm", "o_alarm", 0, 0),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=tuple(f"inst_{mode}" for mode in range(1, 11))
            + ("inst_child", "inst_creating", "inst_alarm", "inst_ctrl"),
        ),
    ),
)

# A child's event_inherited() reaches the parent's instance_change: the change
# is made at once, the parent's event goes on as the new object, and so does
# the child's event after the call (Step, then Create: the child that has no
# event of its own runs the parent's as its own).
_FRAME_GUARD = "if (global.fr != 1) exit;\n"
_FRAME_CTRL_STEP = (
    "global.fr += 1;\n"
    "if (global.fr == 3) {\n"
    "    with (all) if (variable_instance_exists(id, \"hp\")) trace(\"final \" + object_get_name(object_index) + \" \"\n"
    "        + sprite_get_name(sprite_index) + \" hp=\" + string(hp) + \" x=\" + string(x));\n"
    "    global.done = true;\n"
    "}\n"
)
_FRAME_CTRL = GameMakerObject("o_ctrl", {EVENT_CREATE: "global.fr = 0;\n", EVENT_STEP: _FRAME_CTRL_STEP})
_FRAME_SPRITES = (
    GameMakerSprite("s_a", 2, 2, frames=_frames(_RED, 2)),
    GameMakerSprite("s_b", 2, 2, frames=_frames(_GREEN, 2)),
)
_KEEP_SPRITE_AND_HP = (
    "var _s = sprite_index;\n"
    "instance_change(o_t1, true);\n"
    "sprite_index = _s;\n"
    "hp = 3;\n"
    'trace("par " + object_get_name(object_index) + " " + sprite_get_name(sprite_index) + " hp=" + string(hp));\n'
)
_AFTER_INHERITED = 'trace("kid " + object_get_name(object_index) + " " + sprite_get_name(sprite_index) + " hp=" + string(hp));\n'
_TARGET_T1 = GameMakerObject("o_t1", {EVENT_CREATE: 'hp = 100; trace("t1 create");\n'}, sprite="s_b")

_INHERITED_STEP_PROJECT = GameMakerProject(
    name="InstanceChangeInheritedStep",
    scripts={"scr_trace": _SCRIPT},
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject("o_par", {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _FRAME_GUARD + _KEEP_SPRITE_AND_HP}, sprite="s_a"),
        GameMakerObject(
            "o_kid",
            {EVENT_STEP: _FRAME_GUARD + "event_inherited();\n" + _AFTER_INHERITED + "x += 5;\nhp = 3;\n"},
            parent="o_par",
            sprite="s_a",
        ),
        _TARGET_T1,
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances", 0, (RoomInstance("inst_kid", "o_kid", 10, 20), RoomInstance("inst_ctrl", "o_ctrl", 0, 0))
                ),
            ),
            creation_order=("inst_kid", "inst_ctrl"),
        ),
    ),
)

_INHERITED_IN_SWITCH_PROJECT = GameMakerProject(
    name="InstanceChangeInheritedInSwitch",
    scripts={"scr_trace": _SCRIPT},
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject("o_par", {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _FRAME_GUARD + _KEEP_SPRITE_AND_HP}, sprite="s_a"),
        GameMakerObject(
            "o_sw",
            {
                EVENT_STEP: _FRAME_GUARD
                + "switch (global.fr) {\n    case 1: event_inherited(); break;\n    default: break;\n}\n"
                + _AFTER_INHERITED
                + "x += 5;\nhp = 3;\n"
            },
            parent="o_par",
            sprite="s_a",
        ),
        _TARGET_T1,
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances", 0, (RoomInstance("inst_sw", "o_sw", 10, 20), RoomInstance("inst_ctrl", "o_ctrl", 0, 0))
                ),
            ),
            creation_order=("inst_sw", "inst_ctrl"),
        ),
    ),
)

_INHERITED_CREATE_PROJECT = GameMakerProject(
    name="InstanceChangeInheritedCreate",
    scripts={"scr_trace": _SCRIPT},
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject("o_par", {EVENT_CREATE: "hp = 3;\n" + _KEEP_SPRITE_AND_HP}, sprite="s_a"),
        GameMakerObject("o_kid", {EVENT_STEP: 'trace("never");\n'}, parent="o_par", sprite="s_a"),
        GameMakerObject(
            "o_kid2",
            {EVENT_CREATE: 'trace("kid2 pre");\nevent_inherited();\n' + _AFTER_INHERITED.replace('"kid ', '"kid2 post ')},
            parent="o_par",
            sprite="s_a",
        ),
        _TARGET_T1,
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_kid", "o_kid", 10, 20),
                        RoomInstance("inst_kid2", "o_kid2", 10, 20),
                        RoomInstance("inst_par", "o_par", 10, 20),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_kid", "inst_kid2", "inst_par", "inst_ctrl"),
        ),
    ),
)

# An unrelated instance created while a child's event_inherited() runs the
# parent's event (the parent creates it, and its Create event changes it)
# changes at once too, whatever event of whatever instance is below it.
_UNRELATED_CREATE_PROJECT = GameMakerProject(
    name="InstanceChangeUnrelated",
    scripts={"scr_trace": _SCRIPT},
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject(
            "o_par",
            {EVENT_CREATE: "steps = 0;\n", EVENT_STEP: "if (global.fr == 1) { instance_create_depth(0, 0, 0, o_spawn); }\n"},
            sprite="s_a",
        ),
        GameMakerObject(
            "o_kid", {EVENT_STEP: 'event_inherited();\ntrace("kid end");\n'}, parent="o_par", sprite="s_a"
        ),
        GameMakerObject(
            "o_spawn",
            {
                EVENT_CREATE: (
                    "hp = 1;\n"
                    "var _s = sprite_index;\n"
                    "instance_change(o_to, true);\n"
                    'trace("spawn after " + object_get_name(object_index) + " hp=" + string(hp));\n'
                    "hp = 1;\n"
                    "sprite_index = _s;\n"
                    'trace("spawn end hp=" + string(hp) + " " + sprite_get_name(sprite_index));\n'
                )
            },
            sprite="s_a",
        ),
        GameMakerObject("o_to", {EVENT_CREATE: 'hp = 100; trace("to create");\n'}, sprite="s_b"),
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances", 0, (RoomInstance("inst_kid", "o_kid", 10, 0), RoomInstance("inst_ctrl", "o_ctrl", 0, 0))
                ),
            ),
            creation_order=("inst_kid", "inst_ctrl"),
        ),
    ),
)

# The events the runtime calls by itself with no method of the instance's
# script below them change the object at once too: Game Start, Room Start
# and Animation End.
_ANIMATION_END = (7, 7)
_KEEP_SPRITE = (
    "var _s = sprite_index;\n"
    "instance_change(o_t1, true);\n"
    "sprite_index = _s;\n"
    "hp = 5;\n"
    'trace("%s " + object_get_name(object_index) + " " + sprite_get_name(sprite_index) + " hp=" + string(hp));\n'
)
_OTHER_EVENTS_PROJECT = GameMakerProject(
    name="InstanceChangeOtherEvents",
    scripts={"scr_trace": _SCRIPT},
    sprites=(
        GameMakerSprite("s_a", 2, 2, frames=_frames(_RED, 2), playback_speed=60.0),
        GameMakerSprite("s_b", 2, 2, frames=_frames(_GREEN, 2)),
    ),
    objects=(
        GameMakerObject(
            "o_gs", {EVENT_CREATE: 'hp = 5;\ntrace("gs create");\n', EVENT_GAME_START: _KEEP_SPRITE % "gs"}, sprite="s_a"
        ),
        GameMakerObject(
            "o_rs", {EVENT_CREATE: 'hp = 5;\ntrace("rs create");\n', EVENT_ROOM_START: _KEEP_SPRITE % "rs"}, sprite="s_a"
        ),
        GameMakerObject(
            "o_ae", {EVENT_CREATE: 'hp = 5;\ntrace("ae create");\n', _ANIMATION_END: _KEEP_SPRITE % "ae"}, sprite="s_a"
        ),
        _TARGET_T1,
        GameMakerObject(
            "o_ctrl",
            {EVENT_CREATE: "global.fr = 0;\n", EVENT_STEP: _FRAME_CTRL_STEP.replace("== 3", "== 6")},
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
                        RoomInstance("inst_gs", "o_gs", 10, 20),
                        RoomInstance("inst_rs", "o_rs", 10, 20),
                        RoomInstance("inst_ae", "o_ae", 10, 20),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_gs", "inst_rs", "inst_ae", "inst_ctrl"),
        ),
    ),
)

# event_perform runs another event of the instance inside the calling event,
# whose method goes on using the instance's script when it returns: the
# instance's change waits for the calling event to return (and the runtime
# says so), where an unrelated instance's change does not.
_PERFORM_PROJECT = GameMakerProject(
    name="InstanceChangePerform",
    scripts={"scr_trace": _SCRIPT},
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject(
            "o_ep",
            {
                EVENT_CREATE: (
                    'hp = 3;\ntrace("ep create");\nevent_perform(ev_step, ev_step_normal);\n'
                    'trace("ep after " + object_get_name(object_index) + " hp=" + string(hp));\n'
                ),
                EVENT_STEP: (
                    'if (variable_global_exists("once")) exit;\nglobal.once = true;\n'
                    'instance_change(o_t1, true);\ntrace("step rest " + object_get_name(object_index));\n'
                ),
            },
            sprite="s_a",
        ),
        _TARGET_T1,
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances", 0, (RoomInstance("inst_ep", "o_ep", 10, 20), RoomInstance("inst_ctrl", "o_ctrl", 0, 0))
                ),
            ),
            creation_order=("inst_ep", "inst_ctrl"),
        ),
    ),
)

# Where the converter cannot run the rest of the event after the change (a
# script function, or a macro that is not a statement of the event), the
# object changes once the event returns and the converter warns about the code
# after the call.
_DEFERRED_STEP = (
    _FRAME_GUARD
    + "var _s = sprite_index;\n"
    + "%s;\n"
    + "sprite_index = _s;\n"
    + "hp = 3;\n"
    + 'trace("%s " + object_get_name(object_index) + " " + sprite_get_name(sprite_index) + " hp=" + string(hp));\n'
)
_DEFERRED_PROJECT = GameMakerProject(
    name="InstanceChangeDeferred",
    scripts={
        "scr_trace": _SCRIPT,
        "scr_become": "function scr_become(_object) { instance_change(_object, true); }\n",
        "scr_become_via": "function scr_become_via(_object) {\n    scr_become(_object);\n}\n",
        "macros": "#macro BECOME_T1 instance_change(o_t1, true)\n",
    },
    sprites=_FRAME_SPRITES,
    objects=(
        GameMakerObject(
            "o_fn",
            {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _DEFERRED_STEP % ("scr_become(o_t1)", "fn")},
            sprite="s_a",
        ),
        GameMakerObject(
            "o_via",
            {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _DEFERRED_STEP % ("scr_become_via(o_t1)", "via")},
            sprite="s_a",
        ),
        GameMakerObject(
            "o_macro",
            {EVENT_CREATE: "hp = 3;\n", EVENT_STEP: _DEFERRED_STEP % ("BECOME_T1", "macro")},
            sprite="s_a",
        ),
        GameMakerObject(
            "o_macro_loop",
            {
                EVENT_CREATE: "hp = 3;\n",
                EVENT_STEP: _FRAME_GUARD + 'repeat (1) { BECOME_T1; }\nhp = 3;\ntrace("loop " + object_get_name(object_index));\n',
            },
            sprite="s_a",
        ),
        _TARGET_T1,
        _FRAME_CTRL,
    ),
    rooms=(
        GameMakerRoom(
            "r_main",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_fn", "o_fn", 10, 20),
                        RoomInstance("inst_via", "o_via", 10, 20),
                        RoomInstance("inst_macro", "o_macro", 10, 20),
                        RoomInstance("inst_loop", "o_macro_loop", 10, 20),
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_fn", "inst_via", "inst_macro", "inst_loop", "inst_ctrl"),
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


def _deferred_warnings(diagnostics_path: Path) -> list[tuple[str, str, int, str]]:
    """The converter's instance_change warnings as (resource, event, line, message)."""
    if not diagnostics_path.exists():
        return []
    data = cast(object, json.loads(diagnostics_path.read_text(encoding="utf-8")))
    entries = cast(
        list[dict[str, object]],
        cast(dict[str, object], data).get("diagnostics", []) if isinstance(data, dict) else data,
    )
    found: list[tuple[str, str, int, str]] = []
    for entry in entries:
        if entry.get("code") == "GM2GD-GML-INSTANCE-CHANGE-DEFERRED":
            line = entry.get("line")
            found.append(
                (
                    str(entry.get("resource")),
                    str(entry.get("event")),
                    line if isinstance(line, int) else 0,
                    str(entry.get("message")),
                )
            )
    return sorted(found)


class TestInstanceChangeGodot(unittest.TestCase):
    deferred_warnings: list[tuple[str, str, int, str]]

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
            diagnostics_path = root / "godot" / "gm2godot" / "conversion_diagnostics.json"
            self.deferred_warnings = _deferred_warnings(diagnostics_path)

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

        # (The rest of the Collision event runs on the brick, with its other.)
        self.assertEqual(trace, ["wall hit true", "brick create true", "wall after true true", "brick hit"])
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
                # and hp after the call, on o_b.
                "b create hp=5 gone=false",
                # The same, keeping the sprite the instance had: the value is
                # the old one, but the assignment still wins, and hp is read
                # from the new object.
                "b create hp=5 gone=false",
                # The rest of the event runs on o_b, after its Create event.
                "b create hp=3 gone=false",
                "after o_b",
                "step o_b s_c hp=99 maxhp=6 x=70 visible=false",
                # A variable called name is the game's own too.
                "name bob",
                "create o_b s_b2 hp=50 maxhp=8 x=5 visible=true",
                "code o_b s_c hp=77 maxhp=10 x=5 visible=true",
                "keep o_b s_a hp=11 maxhp=10 x=5 visible=true",
            ],
        )

    def test_the_rest_of_the_event_runs_on_the_new_object(self) -> None:
        trace, _nodes = self._run(_CONTINUE_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                # o_creating's Create event: hp is the new Create event's, then
                # the event's own assignment.
                "o_d12 create",
                "creating o_d12 hp=11",
                # The Alarm event of o_alarm.
                "o_d13 create",
                "alarm o_d13",
                # Keeping the sprite: an assignment of the value the variable
                # had before the call still wins over the new object's.
                "m1 s_a o_d1",
                # Assignments of the values the variables had before the call
                # win over the new Create event and the object's visible flag.
                "o_d2 create",
                "m2 hp=3 speed=0 visible=true",
                "o_d3 create",
                "m3 2 1 3",
                # Reads come from the new object; the new Create event
                # assigned x and alarm[1] and defined dst_only.
                "o_d4 create",
                "m4 o_d4 1 true",
                "m4 hp=99 s_c x=5 y=42 alarm=30 dst_only=6",
                # instance_destroy runs the new object's Destroy event at once.
                "o_d5 create",
                "o_d5 destroy",
                "m5 false",
                # Two statements in a row, the rest of the event after them.
                "o_d6a create",
                "m6 o_d6a hp=7",
                "o_d6b create",
                "m7 o_d6b hp=7",
                "m8 o_run hp=7",
                # In a script function the object changes once the event
                # returns: x stays 0 from the new Create event, y follows
                # the event.
                "o_d9 create",
                # A second change of the event runs on the first one's object.
                "m10 o_d10a",
                "o_d10a destroy",
                "o_d10b create",
                # The parent's change below event_inherited() is made at once:
                # the child's event goes on afterwards, as the new object.
                "o_d11 create",
                "child ran",
                # What the instances ended up as.
                "r1 o_d1 s_a hp=0 speed=0 visible=true x=100 y=50 n=-",
                "r2 o_d2 s_b hp=3 speed=0 visible=true x=100 y=50 n=-",
                "r3 o_d3 s_b hp=0 speed=0 visible=true x=100 y=50 n=2",
                "r4 o_d4 s_c hp=99 speed=0 visible=true x=5 y=42 n=-",
                "r9 o_d9 s_b hp=3 speed=0 visible=true x=0 y=42 n=-",
                "child o_d11 s_b hp=1 speed=0 visible=true x=0 y=0 n=-",
            ],
        )

    def test_event_inherited_reaching_a_parents_instance_change_in_a_step_event(self) -> None:
        trace, _nodes = self._run(_INHERITED_STEP_PROJECT, _TRACE_PROBE)

        # The parent's rest runs on o_t1, then the child's: neither the
        # sprite nor hp the child sees is o_t1's, and the child's last
        # assignments (hp = 3, x += 5) are on o_t1 too.
        self.assertEqual(
            trace,
            ["t1 create", "par o_t1 s_a hp=3", "kid o_t1 s_a hp=3", "final o_t1 s_a hp=3 x=15"],
        )
        self.assertEqual(self.deferred_warnings, [])

    def test_event_inherited_inside_a_switch_case_defers_the_parents_change_safely(self) -> None:
        trace, _nodes = self._run(_INHERITED_IN_SWITCH_PROJECT, _TRACE_PROBE)

        # The rest of a switch case cannot become a function, so the parent's
        # change waits for the child's event to return instead of replacing the
        # script under the child's running method (which crashed the engine).
        assert isinstance(trace, list)
        self.assertEqual(trace[-1], "final o_t1 s_b hp=100 x=15")
        self.assertIn("kid o_sw s_a hp=3", trace)

    def test_event_inherited_reaching_a_parents_instance_change_in_a_create_event(self) -> None:
        trace, _nodes = self._run(_INHERITED_CREATE_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                # o_kid has no Create event: the parent's runs as its own.
                "t1 create",
                "par o_t1 s_a hp=3",
                # o_kid2's own Create event goes on as o_t1 after the call.
                "kid2 pre",
                "t1 create",
                "par o_t1 s_a hp=3",
                "kid2 post o_t1 s_a hp=3",
                "t1 create",
                "par o_t1 s_a hp=3",
                "final o_t1 s_a hp=3 x=10",
                "final o_t1 s_a hp=3 x=10",
                "final o_t1 s_a hp=3 x=10",
            ],
        )
        self.assertEqual(self.deferred_warnings, [])

    def test_an_unrelated_instances_create_event_changes_the_object_at_once(self) -> None:
        trace, _nodes = self._run(_UNRELATED_CREATE_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                "kid end",
                # The parent's Step event, run by the child's event_inherited(),
                # creates o_spawn, whose Create event runs the rest of itself on
                # o_to; the child's event is not affected.
                "to create",
                "spawn after o_to hp=100",
                "spawn end hp=1 s_a",
                "kid end",
                "kid end",
                "final o_to s_a hp=1 x=0",
            ],
        )

    def test_a_change_in_an_event_performed_by_the_same_instance_waits_for_the_calling_event(self) -> None:
        trace, _nodes = self._run(_PERFORM_PROJECT, _TRACE_PROBE)

        # Changing the node's script under the Create event's method would
        # free the instance that method runs on; the change is made once the
        # Create event has returned.
        self.assertEqual(
            trace,
            [
                "ep create",
                "step rest o_ep",
                "ep after o_ep hp=3",
                "t1 create",
                "final o_t1 s_b hp=100 x=10",
            ],
        )

    def test_game_start_room_start_and_animation_end_events_change_the_object_at_once(self) -> None:
        trace, _nodes = self._run(_OTHER_EVENTS_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                "gs create",
                "rs create",
                "ae create",
                "t1 create",
                "gs o_t1 s_a hp=5",
                "t1 create",
                "rs o_t1 s_a hp=5",
                "t1 create",
                "ae o_t1 s_a hp=5",
                "final o_t1 s_a hp=5 x=10",
                "final o_t1 s_a hp=5 x=10",
                "final o_t1 s_a hp=5 x=10",
            ],
        )
        self.assertEqual(self.deferred_warnings, [])

    def test_calls_of_script_functions_and_macros_that_change_the_object_are_warned_about(self) -> None:
        trace, _nodes = self._run(_DEFERRED_PROJECT, _TRACE_PROBE)

        self.assertEqual(
            trace,
            [
                # The change inside a script function waits for the event to
                # return, so the rest of the event runs on the old object, and
                # its assignments of the values the variables had at the call
                # (the sprite, hp) are lost: the warnings below tell so.
                "fn o_fn s_a hp=3",
                "t1 create",
                "via o_via s_a hp=3",
                "t1 create",
                # A macro used as a statement of the event runs the rest of the
                # event on the new object, as GameMaker does.
                "t1 create",
                "macro o_t1 s_a hp=3",
                # In a loop it waits for the event to return too.
                "loop o_macro_loop",
                "t1 create",
                "final o_t1 s_b hp=100 x=10",
                "final o_t1 s_b hp=100 x=10",
                "final o_t1 s_a hp=3 x=10",
                "final o_t1 s_b hp=100 x=10",
            ],
        )
        warnings = [(resource, event, line) for resource, event, line, _message in self.deferred_warnings]
        # (The macro statement of o_macro is made at once and is not reported.)
        self.assertEqual(
            warnings,
            [("o_fn", "_on_step", 3), ("o_macro_loop", "_on_step", 2), ("o_via", "_on_step", 3)],
        )
        messages = {resource: message for resource, _event, _line, message in self.deferred_warnings}
        self.assertIn(
            "The call of the script function scr_become, which runs instance_change, at line 3",
            messages["o_fn"],
        )
        self.assertIn("assignment to the instance's variable 'sprite_index' (line 4)", messages["o_fn"])
        self.assertIn(
            "The call of the script function scr_become_via, which runs instance_change, at line 3",
            messages["o_via"],
        )
        self.assertIn("The macro BECOME_T1, which runs instance_change, at line 2", messages["o_macro_loop"])
        self.assertIn("assignment to the instance's variable 'hp' (line 3)", messages["o_macro_loop"])

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
