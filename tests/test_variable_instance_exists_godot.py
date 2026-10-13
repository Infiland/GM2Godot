from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.conversion.gml_runtime import GML_RUNTIME_SCRIPT
from src.conversion.gml_transpiler_parts.constants import BUILTIN_VARIABLE_REGISTRY
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

_SCRIPTS = (
    "function trace(_text) {\n"
    '    if (!variable_global_exists("trace")) global.trace = [];\n'
    "    array_push(global.trace, _text);\n"
    "}\n"
    'function flag(_value) { return _value ? "T" : "F"; }\n'
    "function any_name_starts(_names, _prefix) {\n"
    "    for (var i = 0; i < array_length(_names); i++) {\n"
    "        if (string_pos(_prefix, _names[i]) == 1) return true;\n"
    "    }\n"
    "    return false;\n"
    "}\n"
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 8:
		var scope = GMRuntime.gml_global_scope()
		print("VARIABLE_EXISTS_TRACE " + JSON.stringify(scope.get("trace", [])))
		get_tree().quit(0)
"""

# An instance variable the object's code assigns is a member the converted
# script declares from the start, but in GameMaker it only exists once it has
# been assigned (the runner's variable_instance_exists looks for the property
# the first assignment creates, and an assigned undefined creates it too):
# before that variable_instance_exists is false, variable_instance_get gives
# undefined and variable_instance_get_names does not list it.
_PROJECT = GameMakerProject(
    name="VariableExists",
    scripts={"scr_helpers": _SCRIPTS},
    objects=(
        # The reported pattern: the first step finds no n.
        GameMakerObject(
            "o_counter",
            {
                EVENT_STEP: (
                    'n = variable_instance_exists(id, "n") ? n + 1 : 1;\n'
                    'if (n <= 3) trace("n=" + string(n));\n'
                ),
            },
        ),
        GameMakerObject(
            "o_subject",
            {
                EVENT_CREATE: (
                    "var _count = variable_instance_names_count(id);\n"
                    "var _names = variable_instance_get_names(id);\n"
                    'trace("before exists=" + flag(variable_instance_exists(id, "a"))'
                    ' + flag(variable_instance_exists(id, "b")) + flag(variable_instance_exists(id, "c"))'
                    ' + flag(variable_struct_exists(id, "a")) + flag(struct_exists(id, "a")));\n'
                    'trace("before get_undefined=" + flag(is_undefined(variable_instance_get(id, "a")))'
                    ' + flag(is_undefined(variable_struct_get(id, "a")))'
                    ' + " listed=" + flag(array_contains(_names, "a"))'
                    ' + " internal=" + flag(any_name_starts(_names, "_gm")));\n'
                    "a = 5;\n"
                    "b = undefined;\n"
                    'variable_instance_set(id, "c", 7);\n'
                    "_names = variable_instance_get_names(id);\n"
                    'trace("after exists=" + flag(variable_instance_exists(id, "a"))'
                    ' + flag(variable_instance_exists(id, "b")) + flag(variable_instance_exists(id, "c"))'
                    ' + flag(variable_struct_exists(id, "a")) + flag(struct_exists(id, "b")));\n'
                    'trace("after get=" + string(variable_instance_get(id, "a"))'
                    ' + "," + flag(is_undefined(variable_instance_get(id, "b")))'
                    ' + "," + string(variable_instance_get(id, "c")));\n'
                    'trace("after listed=" + flag(array_contains(_names, "a")) + flag(array_contains(_names, "b"))'
                    ' + flag(array_contains(_names, "c")) + " grew=" + string(variable_instance_names_count(id) - _count));\n'
                ),
                EVENT_STEP: "c += 1;\n",
            },
        ),
        # Another object's view of an instance variable assigned later.
        GameMakerObject(
            "o_watcher",
            {
                EVENT_STEP: (
                    'trace("watch exists=" + flag(variable_instance_exists(o_late, "late"))'
                    ' + " undefined=" + flag(is_undefined(variable_instance_get(o_late, "late")))'
                    ' + " listed=" + flag(array_contains(variable_instance_get_names(o_late), "late")));\n'
                ),
            },
        ),
        GameMakerObject("o_late", {EVENT_STEP: "late = 1;\n"}),
        # A variable the parent object's code declares.
        GameMakerObject(
            "o_base",
            {EVENT_CREATE: "shared = 1;\n"},
        ),
        GameMakerObject(
            "o_child",
            {
                EVENT_CREATE: (
                    'trace("child before=" + flag(variable_instance_exists(id, "shared")));\n'
                    "event_inherited();\n"
                    'trace("child after=" + flag(variable_instance_exists(id, "shared")));\n'
                ),
            },
            parent="o_base",
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
                        RoomInstance("inst_counter", "o_counter", 0, 0),
                        RoomInstance("inst_subject", "o_subject", 0, 0),
                        RoomInstance("inst_watcher", "o_watcher", 0, 0),
                        RoomInstance("inst_late", "o_late", 0, 0),
                        RoomInstance("inst_child", "o_child", 0, 0),
                    ),
                ),
            ),
            creation_order=("inst_counter", "inst_subject", "inst_watcher", "inst_late", "inst_child"),
        ),
    ),
)

_EXPECTED_TRACE = [
    # Create events, in creation order.
    "before exists=FFFFF",
    "before get_undefined=TT listed=F internal=F",
    "after exists=TTTTT",
    "after get=5,T,7",
    "after listed=TTT grew=3",
    "child before=F",
    "child after=T",
    # Step 1: o_late has not run yet.
    "n=1",
    "watch exists=F undefined=T listed=F",
    # Step 2.
    "n=2",
    "watch exists=T undefined=F listed=T",
    # Step 3.
    "n=3",
    "watch exists=T undefined=F listed=T",
]


# The tests below record what they see under a key, the last value written
# winning, so a repeating event reports its state once the run is over.
_RECORD_SCRIPTS = (
    "function record(_key, _text) {\n"
    '    if (!variable_global_exists("record")) global.record = {};\n'
    "    global.record[$ _key] = _text;\n"
    "}\n"
    'function flag(_value) { return _value ? "T" : "F"; }\n'
    "function joined(_values) {\n"
    '    var _text = "";\n'
    "    for (var i = 0; i < array_length(_values); i++) {\n"
    '        _text += (i > 0 ? "," : "") + string(_values[i]);\n'
    "    }\n"
    "    return _text;\n"
    "}\n"
)

_RECORD_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 10:
		var scope = GMRuntime.gml_global_scope()
		print("RECORD " + JSON.stringify(scope.get("record", {})))
		get_tree().quit(0)
"""


def _run_record_project(test: unittest.TestCase, project: GameMakerProject) -> dict[str, str]:
    godot_binary = find_smoke_godot_binary()
    if godot_binary is None:
        test.skipTest("Godot binary not available")

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        write_gamemaker_project(root / "gamemaker", project)
        convert_gamemaker_project(root / "gamemaker", root / "godot")
        add_probe_autoload(root / "godot", _RECORD_PROBE)
        result = run_converted_project(godot_binary, root / "godot")
        output = result.stdout + result.stderr

    test.assertEqual(result.returncode, 0, output)
    test.assertNotIn("ERROR:", output)
    test.assertNotIn("WARNING:", output)
    record_lines = [line for line in output.splitlines() if line.startswith("RECORD ")]
    test.assertEqual(len(record_lines), 1, output)
    return json.loads(record_lines[0].removeprefix("RECORD "))


def _single_room(*instances: RoomInstance) -> GameMakerRoom:
    return GameMakerRoom(
        "r_main",
        layers=(InstanceLayer("Instances", 0, instances),),
        creation_order=tuple(instance.name for instance in instances),
    )


# A member holding an instance that was destroyed holds a freed object, which
# Godot compares equal to null: it is still a value the variable was assigned
# (the runner keeps a variable holding a destroyed instance's id), so the
# variable keeps existing.
_FREED_REFERENCE_PROJECT = GameMakerProject(
    name="VariableFreedReference",
    scripts={"scr_helpers": _RECORD_SCRIPTS},
    objects=(
        GameMakerObject(
            "o_holder",
            {
                EVENT_CREATE: "buddy = noone;\nnever_assigned_later = 1;\n",
                EVENT_STEP: (
                    'record("holder", "exists=" + flag(variable_instance_exists(id, "buddy"))'
                    ' + " get_undefined=" + flag(is_undefined(variable_instance_get(id, "buddy")))'
                    ' + " listed=" + flag(array_contains(variable_instance_get_names(id), "buddy"))'
                    ' + " struct_exists=" + flag(variable_struct_exists(id, "buddy"))'
                    ' + " buddy_alive=" + flag(instance_exists(buddy)));\n'
                ),
            },
        ),
        GameMakerObject(
            "o_victim",
            {
                EVENT_STEP: (
                    'if (!variable_global_exists("linked")) {\n'
                    "    global.linked = true;\n"
                    "    with (o_holder) { buddy = other; }\n"
                    "    instance_destroy();\n"
                    "}\n"
                ),
            },
        ),
    ),
    rooms=(_single_room(RoomInstance("inst_holder", "o_holder", 0, 0), RoomInstance("inst_victim", "o_victim", 0, 0)),),
)

# The struct functions take an instance id as the runner redirects
# variable_struct_* and struct_* to variable_instance_*: writing through an
# id must reach the instance the reads see.
_STRUCT_WRITES_PROJECT = GameMakerProject(
    name="VariableStructWrites",
    scripts={"scr_helpers": _RECORD_SCRIPTS},
    objects=(
        GameMakerObject("o_target", {EVENT_CREATE: 'hp = 10;\nbonus = 4;\nlabel = "t";\ntag = 1;\n'}),
        GameMakerObject(
            "o_ctrl",
            {
                EVENT_CREATE: "frame = 0;\n",
                EVENT_STEP: (
                    "frame += 1;\n"
                    "if (frame == 2) {\n"
                    "    var t = instance_find(o_target, 0);\n"
                    '    variable_struct_set(t, "hp", 5);\n'
                    '    record("set", string(t.hp));\n'
                    '    t[$ "hp"] = 7;\n'
                    '    record("bracket", string(t.hp));\n'
                    '    t[$ "hp"] += 1;\n'
                    '    record("bracket_add", string(t.hp));\n'
                    '    struct_set(t, "hp", 9);\n'
                    '    record("struct_set", string(t.hp));\n'
                    '    var h = o_target.id;\n'
                    '    h[$ "label"] = "n2";\n'
                    '    with (o_target) { record("instance_sees", string(hp) + "," + label); }\n'
                    '    variable_struct_set(t, "extra", 3);\n'
                    '    record("new_member", string(variable_instance_get(t, "extra"))'
                    ' + flag(variable_instance_exists(t, "extra")));\n'
                    '    variable_struct_remove(t, "extra");\n'
                    '    record("removed_new", flag(variable_instance_exists(t, "extra")));\n'
                    '    variable_struct_remove(t, "bonus");\n'
                    '    record("removed_declared", flag(variable_instance_exists(t, "bonus"))'
                    ' + flag(is_undefined(variable_instance_get(t, "bonus")))'
                    ' + flag(array_contains(variable_instance_get_names(t), "bonus")));\n'
                    '    struct_remove(t, "tag");\n'
                    '    record("struct_removed", flag(variable_instance_exists(t, "tag")));\n'
                    '    variable_struct_remove(t, "nothere");\n'
                    '    variable_struct_set(t, "x", 50);\n'
                    '    variable_struct_remove(t, "x");\n'
                    '    variable_struct_remove(t, "speed");\n'
                    '    record("builtins_stay", string(t.x) + flag(variable_instance_exists(t, "x"))'
                    ' + flag(variable_instance_exists(t, "speed")));\n'
                    '    variable_struct_set(t, "bonus", 6);\n'
                    '    record("set_again", string(t.bonus) + flag(variable_instance_exists(t, "bonus")));\n'
                    "}\n"
                ),
            },
        ),
    ),
    rooms=(_single_room(RoomInstance("inst_target", "o_target", 0, 0), RoomInstance("inst_ctrl", "o_ctrl", 0, 0)),),
)

_BUILTIN_NAMES_PROBED = (
    "id, x, y, xstart, ystart, xprevious, yprevious, speed, direction, hspeed, vspeed, friction, gravity,"
    " gravity_direction, depth, image_index, image_speed, image_xscale, image_yscale, image_angle, image_alpha,"
    " image_blend, image_number, sprite_index, mask_index, solid, persistent, object_index, path_index,"
    " path_position, path_positionprevious, path_speed, path_scale, path_orientation, path_endaction, visible,"
    " layer, alarm, other"
)

# variable_instance_get_names and variable_instance_names_count list the
# variables a game defines (the runner's __internal__get_variable_names leaves
# GameMaker's own instance variables out) and count 0 when no instance matches.
_NAMES_PROJECT = GameMakerProject(
    name="VariableNames",
    scripts={"scr_helpers": _RECORD_SCRIPTS},
    objects=(
        GameMakerObject(
            "o_subject",
            {
                EVENT_CREATE: (
                    "hp = 3;\n"
                    'label = "a";\n'
                    "unset_value = undefined;\n"
                    'if (variable_global_exists("never")) { pending = 1; }\n'
                    'variable_instance_set(id, "dyn", 1);\n'
                ),
                EVENT_STEP: (
                    "var _names = variable_instance_get_names(id);\n"
                    "array_sort(_names, true);\n"
                    'record("names", joined(_names));\n'
                    'record("count", string(variable_instance_names_count(id)));\n'
                    'record("struct_count", string(variable_struct_names_count(id)));\n'
                    f'var _builtins = string_split("{_BUILTIN_NAMES_PROBED}", ", ");\n'
                    'var _leaked = [];\n'
                    "for (var i = 0; i < array_length(_builtins); i++) {\n"
                    "    if (array_contains(_names, _builtins[i])) array_push(_leaked, _builtins[i]);\n"
                    "}\n"
                    'record("leaked", joined(_leaked));\n'
                    'var _plain = { a: 1, b: 2 };\n'
                    'record("plain_struct", string(variable_struct_names_count(_plain)) + "/"'
                    " + joined(variable_struct_get_names(_plain)));\n"
                    'record("no_instance", string(variable_instance_names_count(o_none))'
                    ' + "/" + string(array_length(variable_instance_get_names(o_none)))'
                    ' + "/" + string(variable_instance_names_count(noone))'
                    ' + "/" + string(array_length(variable_instance_get_names(noone))));\n'
                ),
            },
        ),
        GameMakerObject("o_none", {}),
    ),
    rooms=(_single_room(RoomInstance("inst_subject", "o_subject", 0, 0)),),
)


class TestVariableInstanceExistsGodot(unittest.TestCase):
    def test_instance_builtin_names_match_the_transpilers_builtin_variables(self) -> None:
        block = re.search(r"const GML_INSTANCE_BUILTIN_VARIABLES = \{(.*?)\n\}", GML_RUNTIME_SCRIPT, re.DOTALL)
        assert block is not None
        listed = set(re.findall(r'"([a-z_0-9]+)": true', block.group(1)))
        instance_builtins = {
            name for name, metadata in BUILTIN_VARIABLE_REGISTRY.items() if metadata.scope == "instance"
        }
        self.assertEqual(sorted(instance_builtins - listed), [])
        # The runner's own instance variables the registry does not list.
        for name in ("ystart", "alarm", "persistent", "image_single", "sprite_width", "phy_speed", "layer"):
            self.assertIn(name, listed)

    def test_unassigned_members_are_told_apart_by_type(self) -> None:
        # A freed instance compares equal to null (see
        # test_member_holding_a_destroyed_instance_keeps_existing), and the
        # read of an instance variable is hot, so the read tests the type
        # inline rather than through a helper call.
        self.assertIn(
            "return gml_undefined() if typeof(property_value) == TYPE_NIL else property_value",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("typeof(instance.get(key)) != TYPE_NIL", GML_RUNTIME_SCRIPT)
        self.assertIn("typeof(instance.get(name)) != TYPE_NIL", GML_RUNTIME_SCRIPT)

    def test_member_holding_a_destroyed_instance_keeps_existing(self) -> None:
        record = _run_record_project(self, _FREED_REFERENCE_PROJECT)
        self.assertEqual(
            record["holder"],
            "exists=T get_undefined=F listed=T struct_exists=T buddy_alive=F",
        )

    def test_struct_functions_write_to_the_instance_behind_an_id(self) -> None:
        record = _run_record_project(self, _STRUCT_WRITES_PROJECT)
        self.assertEqual(
            record,
            {
                "set": "5",
                "bracket": "7",
                "bracket_add": "8",
                "struct_set": "9",
                "instance_sees": "9,n2",
                "new_member": "3T",
                "removed_new": "F",
                "removed_declared": "FTF",
                "struct_removed": "F",
                "builtins_stay": "50TT",
                "set_again": "6T",
            },
        )

    def test_instance_variable_names_list_only_user_variables(self) -> None:
        record = _run_record_project(self, _NAMES_PROJECT)
        self.assertEqual(record["names"], "dyn,hp,label,unset_value")
        self.assertEqual(record["count"], "4")
        self.assertEqual(record["struct_count"], "4")
        self.assertEqual(record["leaked"], "")
        self.assertEqual(record["plain_struct"], "2/a,b")
        self.assertEqual(record["no_instance"], "0/0/0/0")

    def test_declared_instance_variables_exist_only_once_assigned(self) -> None:
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
        trace_lines = [line for line in output.splitlines() if line.startswith("VARIABLE_EXISTS_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        trace = json.loads(trace_lines[0].removeprefix("VARIABLE_EXISTS_TRACE "))
        self.assertEqual(trace[: len(_EXPECTED_TRACE)], _EXPECTED_TRACE, output)


if __name__ == "__main__":
    unittest.main()
