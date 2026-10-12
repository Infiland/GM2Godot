from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    EVENT_CREATE,
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
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

EVENT_GAME_END = (7, 3)
EVENT_ROOM_END = (7, 5)

_TRACE_SCRIPT = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 12:
		var scope = GMRuntime.gml_global_scope()
		var trace = scope.get("trace", [])
		# Time sources the game kept in globals: whether each still exists.
		for key in ["later", "kept"]:
			if scope.has(key):
				trace.append(key + "_exists:" + str(GMRuntime.gml_handle_is_valid(scope[key])))
		print("ROOM_LIFECYCLE_TRACE " + JSON.stringify(trace))
		get_tree().quit(0)
"""

# A redirecting init room: the first instance's Create event requests a room
# change. The runner's StartRoom decides before each instance's Create event
# whether its Create event and creation code run, so the requesting instance
# still runs its own creation code while the later one runs neither. Game
# Start and Room Start are Other events and are skipped for non-persistent
# instances once the change is pending; the room creation code still runs.
_REDIRECT_PROJECT = GameMakerProject(
    name="RedirectInCreate",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_go",
            {
                EVENT_CREATE: 'trace("create_go");\nroom_goto(r_next);\n',
                EVENT_GAME_START: 'trace("game_start_go");\n',
                EVENT_ROOM_START: 'trace("room_start_go");\n',
            },
        ),
        GameMakerObject(
            "o_late",
            {
                EVENT_CREATE: 'trace("create_late");\nsetting = 1;\n',
                EVENT_ROOM_START: 'trace("room_start_late");\n',
            },
        ),
        GameMakerObject("o_next", {EVENT_CREATE: 'trace("create_next");\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_init",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_go", "o_go", 0, 0, creation_code='trace("code_go");\n'),
                        RoomInstance("inst_late", "o_late", 0, 0, creation_code='trace("code_late:" + string(setting));\n'),
                    ),
                ),
            ),
            creation_order=("inst_go", "inst_late"),
            creation_code='trace("room_code_init");\n',
        ),
        GameMakerRoom(
            "r_next",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_next", "o_next", 0, 0),)),),
            creation_order=("inst_next",),
        ),
    ),
)
_REDIRECT_TRACE = ["create_go", "code_go", "room_code_init", "create_next"]

# Destroyed instances receive no further events: one that destroys itself in
# its Create event gets no Game Start or Room Start, one destroyed by an
# earlier Room Start event gets no Room Start, and one destroyed in the step
# that changes the room gets no Room End.
_DESTROYED_PROJECT = GameMakerProject(
    name="DestroyedLifecycle",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_gone",
            {
                EVENT_CREATE: "instance_destroy();\n",
                EVENT_GAME_START: 'trace("game_start_gone");\n',
                EVENT_ROOM_START: 'trace("room_start_gone");\n',
            },
        ),
        GameMakerObject("o_killer", {EVENT_ROOM_START: 'trace("room_start_killer");\ninstance_destroy(o_victim);\n'}),
        GameMakerObject("o_victim", {EVENT_ROOM_START: 'trace("room_start_victim");\n'}),
        GameMakerObject(
            "o_leaver",
            {
                EVENT_STEP: (
                    'if (room == r_one) {\n    trace("leave");\n    instance_destroy(o_ender);\n    room_goto(r_two);\n}\n'
                ),
            },
        ),
        GameMakerObject("o_ender", {EVENT_ROOM_END: 'trace("room_end_ender");\n'}),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_gone", "o_gone", 0, 0),
                        RoomInstance("inst_killer", "o_killer", 0, 0),
                        RoomInstance("inst_victim", "o_victim", 0, 0),
                        RoomInstance("inst_leaver", "o_leaver", 0, 0),
                        RoomInstance("inst_ender", "o_ender", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_gone", "inst_killer", "inst_victim", "inst_leaver", "inst_ender"),
        ),
        GameMakerRoom("r_two", layers=(), creation_order=()),
    ),
)
_DESTROYED_TRACE = ["room_start_killer", "leave"]


# game_restart ends the game like the runner's Run_EndGame(true): every
# instance goes, persistent ones included (placed or created by code), and
# the time sources made by call_later are destroyed; those made by
# time_source_create stay. The first room then starts as at launch: the
# persistent controller runs its Create event and creation code again and
# Game Start runs again. Game End runs before the restart.
_RESTART_PROJECT = GameMakerProject(
    name="GameRestart",
    scripts={"scr_trace": _TRACE_SCRIPT, "scr_later": "function later_callback() {}\n"},
    objects=(
        GameMakerObject(
            "o_ctrl",
            {
                EVENT_CREATE: (
                    "counter = 0;\n"
                    'trace("create_ctrl:" + string(instance_number(o_ctrl)));\n'
                    'if (!variable_global_exists("runs")) {\n'
                    "    global.runs = 0;\n"
                    "    global.later = call_later(100000, 1, later_callback, true);\n"
                    "    global.kept = time_source_create(time_source_global, 100000, 1, later_callback, [], -1);\n"
                    "    time_source_start(global.kept);\n"
                    "}\n"
                    "global.runs += 1;\n"
                ),
                EVENT_GAME_START: 'trace("game_start_ctrl");\n',
                EVENT_ROOM_START: (
                    'trace("room_start_ctrl:counter=" + string(counter) + ":managers=" + string(instance_number(o_manager)));\n'
                ),
                EVENT_STEP: 'counter += 1;\nif (counter == 3 && global.runs == 1) {\n    trace("restart");\n    game_restart();\n}\n',
                EVENT_GAME_END: 'trace("game_end_ctrl");\n',
            },
            persistent=True,
        ),
        GameMakerObject("o_spawner", {EVENT_CREATE: "instance_create_depth(0, 0, 0, o_manager);\n"}),
        GameMakerObject("o_manager", {EVENT_CREATE: 'trace("create_manager:" + string(instance_number(o_manager)));\n'}, persistent=True),
    ),
    rooms=(
        GameMakerRoom(
            "r_first",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0, creation_code='trace("code_ctrl");\n'),
                        RoomInstance("inst_spawner", "o_spawner", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_ctrl", "inst_spawner"),
        ),
    ),
)
_RESTART_RUN = [
    "create_ctrl:1",
    "code_ctrl",
    "create_manager:1",
    "game_start_ctrl",
    "room_start_ctrl:counter=0:managers=1",
]
_RESTART_TRACE = [
    *_RESTART_RUN,
    "restart",
    "game_end_ctrl",
    *_RESTART_RUN,
    "later_exists:false",
    "kept_exists:true",
]


# GameMaker builds every instance once, before its Create event: a placed
# instance gets its start position (xstart, xprevious) and its room
# placement's scale, angle and image_index before the first Create event of
# the room runs, so an earlier instance's Create event already sees them.
# event_inherited() runs only the parent's event code: the instance keeps its
# own sprite, its start position and what its Create event set before the
# call. Sprites are not inherited: a child object without a sprite of its own
# starts with none (-1), with or without a Create event of its own.
_CONSTRUCT_PROJECT = GameMakerProject(
    name="BuildOnce",
    scripts={"scr_trace": _TRACE_SCRIPT},
    sprites=(GameMakerSprite("s_parent"), GameMakerSprite("s_child"), GameMakerSprite("s_grandchild", frames=4)),
    objects=(
        GameMakerObject("o_parent", {EVENT_CREATE: 'trace("create_parent");\n'}, sprite="s_parent"),
        GameMakerObject(
            "o_child",
            {EVENT_CREATE: 'trace("create_child");\nevent_inherited();\n'},
            sprite="s_child",
            parent="o_parent",
        ),
        GameMakerObject(
            "o_grandchild",
            {
                EVENT_CREATE: (
                    "x = 200;\nhspeed = 3;\nimage_index = 2;\nimage_speed = 0;\nevent_inherited();\n"
                    'trace("grandchild:" + sprite_get_name(sprite_index) + ":xstart=" + string(xstart)\n'
                    '    + ":xprevious=" + string(xprevious) + ":hspeed=" + string(hspeed)\n'
                    '    + ":image_index=" + string(image_index) + ":image_speed=" + string(image_speed));\n'
                ),
            },
            sprite="s_grandchild",
            parent="o_child",
        ),
        GameMakerObject(
            "o_reader",
            {
                EVENT_CREATE: (
                    "var placed = instance_find(o_placed, 0);\n"
                    'trace("reader:xstart=" + string(placed.xstart) + ":ystart=" + string(placed.ystart)\n'
                    '    + ":xprevious=" + string(placed.xprevious) + ":xscale=" + string(placed.image_xscale)\n'
                    '    + ":yscale=" + string(placed.image_yscale) + ":angle=" + string(placed.image_angle)\n'
                    '    + ":image_index=" + string(placed.image_index));\n'
                ),
            },
        ),
        GameMakerObject("o_placed", {EVENT_CREATE: 'trace("create_placed");\n'}, sprite="s_grandchild"),
        GameMakerObject(
            "o_spriteless",
            {EVENT_CREATE: 'trace("spriteless:" + string(sprite_index));\nevent_inherited();\n'},
            parent="o_parent",
        ),
        GameMakerObject(
            "o_spriteless_quiet",
            {EVENT_ROOM_START: 'trace("spriteless_quiet:" + string(sprite_index));\n'},
            parent="o_parent",
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_build",
            layers=(
                InstanceLayer(
                    "Instances",
                    0,
                    (
                        RoomInstance("inst_reader", "o_reader", 0, 0),
                        RoomInstance("inst_placed", "o_placed", 16, 24, scale_x=2, scale_y=3, rotation=45, image_index=2),
                        RoomInstance("inst_grandchild", "o_grandchild", 10, 10),
                        RoomInstance("inst_spriteless", "o_spriteless", 0, 0),
                        RoomInstance("inst_spriteless_quiet", "o_spriteless_quiet", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_reader", "inst_placed", "inst_grandchild", "inst_spriteless", "inst_spriteless_quiet"),
        ),
    ),
)
_CONSTRUCT_TRACE = [
    "reader:xstart=16:ystart=24:xprevious=16:xscale=2:yscale=3:angle=45:image_index=2",
    "create_placed",
    "create_child",
    "create_parent",
    "grandchild:s_grandchild:xstart=10:xprevious=10:hspeed=3:image_index=2:image_speed=0",
    "spriteless:-1",
    "create_parent",
    "create_parent",
    "spriteless_quiet:-1",
]


# A persistent instance on a room layer moves to the layer of the same name
# in each room it goes to, taking that layer's depth; when the room has no
# such layer, one is made at the instance's depth. An instance that has its
# own depth (instance_create_depth) keeps it. (Runner StartRoom: the layer
# names it records, GetLayerFromName / AddLayer.)
_LAYER_REPORT = (
    'trace("keeper:" + room_get_name(room) + ":depth=" + string(depth) + ":actors="\n'
    '    + (layer_exists("Actors") ? string(layer_get_depth("Actors")) + "/"\n'
    '    + string(array_length(layer_get_all_elements(layer_get_id("Actors")))) : "none")\n'
    '    + ":floater=" + string(global.floater.depth));\n'
)
_LAYERS_PROJECT = GameMakerProject(
    name="PersistentLayers",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_keeper",
            {
                EVENT_CREATE: "steps = 0;\nglobal.floater = instance_create_depth(0, 0, -7, o_floater);\n",
                EVENT_ROOM_START: _LAYER_REPORT,
                EVENT_STEP: "steps += 1;\nif (steps == 2 && room != r_three) { steps = 0; room_goto_next(); }\n",
            },
            persistent=True,
        ),
        GameMakerObject("o_floater", {}, persistent=True),
        GameMakerObject("o_plain", {}),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(InstanceLayer("Actors", 100, (RoomInstance("inst_keeper", "o_keeper", 0, 0),)),),
            creation_order=("inst_keeper",),
        ),
        GameMakerRoom(
            "r_two",
            layers=(
                InstanceLayer("Back", 200, (RoomInstance("inst_back", "o_plain", 0, 0),)),
                InstanceLayer("Actors", -50, (RoomInstance("inst_actor", "o_plain", 0, 0),)),
            ),
            creation_order=("inst_back", "inst_actor"),
        ),
        GameMakerRoom(
            "r_three",
            layers=(InstanceLayer("Ground", 300, (RoomInstance("inst_ground", "o_plain", 0, 0),)),),
            creation_order=("inst_ground",),
        ),
    ),
)
_LAYERS_TRACE = [
    "keeper:r_one:depth=100:actors=100/1:floater=-7",
    "keeper:r_two:depth=-50:actors=-50/2:floater=-7",
    "keeper:r_three:depth=-50:actors=-50/1:floater=-7",
]


# A persistent room is built once: coming back to it, or restarting it, finds
# it as it was left, with no Create event, instance creation code or room
# creation code run again, and only Room Start runs. Its instances take no
# part in the other rooms (they are not in their object's instance lists and
# get no events), and the ids of its instances and layers are the same when
# it is entered again (runner StartRoom: a persistent room that was
# initialised is not created from storage again). game_restart() resets it.
_PERSISTENT_ROOM_PROJECT = GameMakerProject(
    name="PersistentRoom",
    scripts={"scr_trace": _TRACE_SCRIPT},
    objects=(
        GameMakerObject(
            "o_ctrl",
            {
                EVENT_CREATE: 'if (!variable_global_exists("t")) global.t = 0;\n',
                EVENT_STEP: (
                    "global.t += 1;\n"
                    "if (global.t == 3) room_goto(r_away);\n"
                    "if (global.t == 5) room_goto(r_hub);\n"
                    "if (global.t == 7) room_restart();\n"
                    'if (global.t == 9) { trace("restart_game"); game_restart(); }\n'
                ),
            },
            persistent=True,
        ),
        GameMakerObject(
            "o_counter",
            {
                EVENT_CREATE: (
                    'n = 0;\ntrace("create_counter");\nglobal.counter_id = id;\n'
                    'global.layer_id = layer_get_id("Things");\n'
                    'instance_create_layer(0, 0, "Things", o_made);\n'
                ),
                EVENT_STEP: "n += 1;\n",
                EVENT_ROOM_START: (
                    'trace("hub_start:n=" + string(n) + ":made=" + string(instance_number(o_made))\n'
                    '    + ":layer=" + (layer_exists(global.layer_id) ? "yes" : "no")\n'
                    '    + ":id=" + (instance_exists(global.counter_id) ? "yes" : "no"));\n'
                ),
            },
        ),
        GameMakerObject("o_made", {}),
        GameMakerObject(
            "o_probe",
            {
                EVENT_CREATE: (
                    'trace("away:counters=" + string(instance_number(o_counter)) + ":made=" + string(instance_number(o_made))\n'
                    '    + ":hub_layer=" + (layer_exists(global.layer_id) ? "yes" : "no"));\n'
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_hub",
            layers=(
                InstanceLayer(
                    "Things",
                    0,
                    (
                        RoomInstance("inst_ctrl", "o_ctrl", 0, 0),
                        RoomInstance("inst_counter", "o_counter", 0, 0, creation_code='trace("code_counter");\n'),
                    ),
                ),
            ),
            creation_order=("inst_ctrl", "inst_counter"),
            creation_code='trace("room_code_hub");\n',
            persistent=True,
        ),
        GameMakerRoom(
            "r_away",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_probe", "o_probe", 0, 0),)),),
            creation_order=("inst_probe",),
        ),
    ),
)
_PERSISTENT_ROOM_FIRST_VISIT = ["create_counter", "code_counter", "room_code_hub", "hub_start:n=0:made=1:layer=yes:id=yes"]
_PERSISTENT_ROOM_TRACE = [
    *_PERSISTENT_ROOM_FIRST_VISIT,
    "away:counters=0:made=0:hub_layer=no",
    "hub_start:n=2:made=1:layer=yes:id=yes",
    "hub_start:n=3:made=1:layer=yes:id=yes",
    "restart_game",
    *_PERSISTENT_ROOM_FIRST_VISIT,
]


class TestRoomLifecycleGodot(unittest.TestCase):
    def test_room_change_in_create_skips_later_create_and_creation_code(self) -> None:
        self.assertEqual(self._run_trace(_REDIRECT_PROJECT), _REDIRECT_TRACE)

    def test_destroyed_instances_get_no_room_or_game_events(self) -> None:
        self.assertEqual(self._run_trace(_DESTROYED_PROJECT), _DESTROYED_TRACE)

    def test_game_restart_removes_persistent_instances_and_call_later_sources(self) -> None:
        self.assertEqual(self._run_trace(_RESTART_PROJECT), _RESTART_TRACE)

    def test_instances_are_built_once_before_their_create_events(self) -> None:
        self.assertEqual(self._run_trace(_CONSTRUCT_PROJECT), _CONSTRUCT_TRACE)

    def test_persistent_instances_move_to_the_layer_of_the_same_name(self) -> None:
        self.assertEqual(self._run_trace(_LAYERS_PROJECT), _LAYERS_TRACE)

    def test_persistent_room_keeps_its_state_until_game_restart(self) -> None:
        self.assertEqual(self._run_trace(_PERSISTENT_ROOM_PROJECT), _PERSISTENT_ROOM_TRACE)

    def _run_trace(self, project: GameMakerProject) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            if project.sprites:
                imported = import_converted_project(godot_binary, root / "godot")
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("ROOM_LIFECYCLE_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("ROOM_LIFECYCLE_TRACE "))


if __name__ == "__main__":
    unittest.main()
