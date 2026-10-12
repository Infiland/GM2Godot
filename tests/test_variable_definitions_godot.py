"""Object Variable Definitions in a converted game, checked at Create time.

GameMaker compiles an object's Variable Definitions into a Pre-Create event
that runs before the Create event of every new instance: event_inherited()
(the parent's definitions), then the object's overrides of inherited
definitions, then its own definitions. A room-placed instance then runs its
pre-creation code, the values overridden for it in the Room Editor, and its
instance creation code runs after its Create event (manual, Object Variables
and Event Order; runner _GameMaker.js StartRoom, instance_create_depth and
instance_create_layer in Function_Layers.js). Each value is GML source.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import cast

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
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

REAL, INTEGER, STRING, BOOLEAN, EXPRESSION, ASSET, LIST, COLOUR = range(8)

_SCRIPTS = {
    "scr_trace": (
        "function trace(_text) {\n"
        '    if (!variable_global_exists("trace")) global.trace = [];\n'
        "    array_push(global.trace, _text);\n"
        "}\n"
    ),
    "scr_helpers": (
        "#macro BONUS 100\n"
        "function scr_double(_value) {\n"
        "    return _value * 2;\n"
        "}\n"
        "function scr_mark(_label) {\n"
        '    trace("pre:" + _label);\n'
        "    return _label;\n"
        "}\n"
    ),
}

# Every value o_base defines, read in its Create event (and by the Create
# events of its children through event_inherited()).
_BASE_SUMMARY = (
    'string(x) + ":" + string(v_real) + ":" + string(v_int)'
    ' + ":" + v_str + ":" + typeof(v_str)'
    ' + ":" + (v_true ? "T" : "F") + (v_false ? "T" : "F") + ":" + typeof(v_true)'
    ' + ":" + string(v_expr) + ":" + (v_asset == o_other ? "o_other" : "?") + ":" + v_list'
    ' + ":" + string(array_length(v_multi)) + v_multi[0]'
    ' + ":" + string(colour_get_red(v_col)) + "," + string(colour_get_blue(v_col))'
    ' + ":" + string(v_func)'
)

_BASE_PROPERTIES = (
    # Traces each time an instance's definitions run.
    ("v_mark", EXPRESSION, "scr_mark(string(x))"),
    ("v_real", REAL, "1.5"),
    ("v_int", INTEGER, "3"),
    ("v_str", STRING, '"hello"'),
    ("v_true", BOOLEAN, "True"),
    ("v_false", BOOLEAN, "False"),
    ("v_expr", EXPRESSION, "v_int * 2 + BONUS"),
    ("v_asset", ASSET, "o_other"),
    ("v_list", LIST, '"b"', ('"a"', '"b"', '"c"'), False),
    ("v_multi", LIST, '"a","c"', ('"a"', '"b"', '"c"'), True),
    ("v_col", COLOUR, "$FF0000FF"),
    ("v_func", EXPRESSION, "scr_double(21)"),
)

VARIABLE_DEFINITIONS_PROJECT = GameMakerProject(
    name="VariableDefinitions",
    scripts=_SCRIPTS,
    objects=(
        GameMakerObject("o_other", {}),
        GameMakerObject("o_base", {EVENT_CREATE: f'trace("base:" + {_BASE_SUMMARY});\n'}),
        GameMakerObject(
            "o_child",
            {
                EVENT_CREATE: (
                    "event_inherited();\n"
                    'trace("child:" + string(x) + ":" + string(v_int) + ":" + string(c_own));\n'
                ),
            },
            parent="o_base",
        ),
        # Inherits every definition and the Create event of o_child.
        GameMakerObject("o_grand", {}, parent="o_child"),
        # Overrides a definition of its grandparent.
        GameMakerObject("o_grand_direct", {}, parent="o_child"),
        # Definitions without any event.
        GameMakerObject("o_plain", {}),
        GameMakerObject(
            "o_spawner",
            {
                EVENT_CREATE: (
                    "var made = instance_create_depth(0, 0, 0, o_child);\n"
                    'trace("spawned:" + string(made.v_int) + ":" + made.v_str + ":" + string(made.c_own));\n'
                    'var plain = instance_create_layer(0, 0, "Instances", o_plain);\n'
                    'trace("spawned_plain:" + plain.p_name);\n'
                ),
            },
        ),
        GameMakerObject(
            "o_checker",
            {
                EVENT_CREATE: (
                    'with (o_grand) trace("check_grand:" + v_str + ":" + string(v_int) + ":" + string(c_own));\n'
                    'with (o_grand_direct) trace("check_grand_direct:" + string(v_real) + ":" + v_str);\n'
                    'with (o_plain) trace("check_plain:" + p_name + ":" + string(p_count));\n'
                    "with (o_base) {\n"
                    '    if (object_index == o_base) trace("check_base:" + string(x) + ":" + string(v_int) + ":" + v_str);\n'
                    "}\n"
                ),
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
                        RoomInstance("inst_base1", "o_base", 10, 0),
                        RoomInstance(
                            "inst_base2",
                            "o_base",
                            20,
                            0,
                            creation_code='trace("code_base2:" + v_str + ":" + string(v_int));\nv_int = 99;\n',
                        ),
                        RoomInstance("inst_child1", "o_child", 30, 0),
                        RoomInstance("inst_grand1", "o_grand", 40, 0),
                        RoomInstance("inst_grand_direct1", "o_grand_direct", 50, 0),
                        RoomInstance("inst_plain1", "o_plain", 60, 0),
                        RoomInstance("inst_spawner", "o_spawner", 70, 0),
                        RoomInstance("inst_checker", "o_checker", 80, 0),
                    ),
                ),
            ),
            creation_order=(
                "inst_base1",
                "inst_base2",
                "inst_child1",
                "inst_grand1",
                "inst_grand_direct1",
                "inst_plain1",
                "inst_spawner",
                "inst_checker",
            ),
        ),
    ),
)

# Definitions by object: (name, varType, value[, listItems, multiselect]).
OBJECT_PROPERTIES: dict[str, Sequence[tuple[object, ...]]] = {
    "o_base": _BASE_PROPERTIES,
    # A new definition reading an inherited one sees the child's override.
    "o_child": (("c_own", EXPRESSION, "v_int + 1"),),
    "o_plain": (("p_name", STRING, '"plain"'), ("p_count", INTEGER, "4")),
}
# Overrides of inherited definitions: (defining object, name, value).
OBJECT_OVERRIDES: dict[str, Sequence[tuple[str, str, str]]] = {
    "o_child": (("o_base", "v_int", "7"), ("o_base", "v_str", '"child"')),
    "o_grand_direct": (("o_base", "v_real", "2.5"),),
}
# Room Editor overrides by instance: (defining object, name, value).
INSTANCE_OVERRIDES: dict[str, Sequence[tuple[str, str, str]]] = {
    "inst_base2": (
        ("o_base", "v_str", '"room"'),
        ("o_base", "v_true", "False"),
        ("o_base", "v_multi", '"b"'),
        # Reads the object's definition, assigned before the room's overrides.
        ("o_base", "v_expr", "v_int * 1000"),
    ),
    # Applied in order: c_own reads the v_int set just before.
    "inst_child1": (("o_base", "v_int", "11"), ("o_child", "c_own", "v_int * 10")),
    # A macro in a room override.
    "inst_grand1": (("o_base", "v_str", '"grand_room"'), ("o_base", "v_func", "BONUS + 1")),
    "inst_plain1": (("o_plain", "p_name", '"plain_room"'),),
}

_BASE_DEFAULTS = "1.50:3:hello:string:TF:bool:106:o_other:b:2a:255,0:42"
_EXPECTED_TRACE = [
    "pre:10",
    "base:10:" + _BASE_DEFAULTS,
    "pre:20",
    "base:20:1.50:3:room:string:FF:bool:3000:o_other:b:1b:255,0:42",
    "code_base2:room:3",
    "pre:30",
    "base:30:1.50:11:child:string:TF:bool:106:o_other:b:2a:255,0:42",
    "child:30:11:110",
    "pre:40",
    "base:40:1.50:7:grand_room:string:TF:bool:106:o_other:b:2a:255,0:101",
    "child:40:7:8",
    "pre:50",
    "base:50:2.50:7:child:string:TF:bool:106:o_other:b:2a:255,0:42",
    "child:50:7:8",
    "pre:0",
    "base:0:1.50:7:child:string:TF:bool:106:o_other:b:2a:255,0:42",
    "child:0:7:8",
    "spawned:7:child:8",
    "spawned_plain:plain",
    "check_grand:grand_room:7:8",
    "check_grand_direct:2.50:child",
]
# with (o_plain) and with (o_base) visit instances in no guaranteed order.
_EXPECTED_CHECKS = {
    "check_plain:plain_room:4",
    "check_plain:plain:4",
    "check_base:10:3:hello",
    "check_base:20:99:room",
}

# Like its Create event, an instance's Pre-Create event does not run once a
# room change is pending (PerformEvent in the runner's yyObject.js).
_ROOM_CHANGE_PROJECT = GameMakerProject(
    name="VariableDefinitionsRoomChange",
    scripts=_SCRIPTS,
    objects=(
        GameMakerObject("o_marked", {EVENT_CREATE: 'trace("create_marked:" + m_label);\n'}),
        GameMakerObject(
            "o_leaver",
            {
                EVENT_STEP: (
                    'if (!variable_global_exists("left")) {\n'
                    "    global.left = true;\n"
                    "    room_goto(r_two);\n"
                    "    instance_create_depth(0, 0, 0, o_marked);\n"
                    '    trace("created_late");\n'
                    "}\n"
                ),
            },
        ),
    ),
    rooms=(
        GameMakerRoom(
            "r_one",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_leaver", "o_leaver", 0, 0),)),),
            creation_order=("inst_leaver",),
        ),
        GameMakerRoom(
            "r_two",
            layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_marked", "o_marked", 0, 0),)),),
            creation_order=("inst_marked",),
        ),
    ),
)
_ROOM_CHANGE_PROPERTIES: dict[str, Sequence[tuple[object, ...]]] = {
    "o_marked": (("m_label", EXPRESSION, 'scr_mark("marked")'),),
}

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames == 12:
		print("VARIABLE_DEFINITIONS_TRACE " + JSON.stringify(GMRuntime.gml_global_scope().get("trace", [])))
		get_tree().quit(0)
"""


def _object_property(entry: tuple[object, ...]) -> dict[str, object]:
    name, var_type, value = entry[0], entry[1], entry[2]
    list_items = list(cast(tuple[str, ...], entry[3])) if len(entry) > 3 else []
    multiselect = bool(entry[4]) if len(entry) > 4 else False
    return {
        "$GMObjectProperty": "v1",
        "%Name": name,
        "filters": [],
        "listItems": list_items,
        "multiselect": multiselect,
        "name": name,
        "rangeEnabled": False,
        "rangeMax": 10.0,
        "rangeMin": 0.0,
        "resourceType": "GMObjectProperty",
        "resourceVersion": "2.0",
        "value": value,
        "varType": var_type,
    }


def _overridden_property(object_name: str, name: str, value: str) -> dict[str, object]:
    reference = f"objects/{object_name}/{object_name}.yy"
    return {
        "$GMOverriddenProperty": "v1",
        "%Name": "",
        "name": "",
        "objectId": {"name": object_name, "path": reference},
        "propertyId": {"name": name, "path": reference},
        "resourceType": "GMOverriddenProperty",
        "resourceVersion": "2.0",
        "value": value,
    }


def _rewrite_json(path: Path, update: object) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    update_function = update
    assert callable(update_function)
    update_function(data)
    write_fixture_text(path, json.dumps(data, indent=2) + "\n")


def write_variable_definitions(
    project_dir: Path,
    project: GameMakerProject,
    properties: dict[str, Sequence[tuple[object, ...]]],
    object_overrides: dict[str, Sequence[tuple[str, str, str]]],
    instance_overrides: dict[str, Sequence[tuple[str, str, str]]],
) -> None:
    """Add Variable Definitions and their overrides to a written project."""
    for object_name in set(properties) | set(object_overrides):
        def update_object(data: dict[str, object], object_name: str = object_name) -> None:
            data["properties"] = [_object_property(entry) for entry in properties.get(object_name, ())]
            data["overriddenProperties"] = [
                _overridden_property(*entry) for entry in object_overrides.get(object_name, ())
            ]

        _rewrite_json(project_dir / "objects" / object_name / f"{object_name}.yy", update_object)
    for room in project.rooms:
        def update_room(data: dict[str, object]) -> None:
            layers = data["layers"]
            assert isinstance(layers, list)
            for layer in layers:  # pyright: ignore[reportUnknownVariableType]
                assert isinstance(layer, dict)
                for instance in layer.get("instances", []):  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                    assert isinstance(instance, dict)
                    instance["properties"] = [
                        _overridden_property(*entry) for entry in instance_overrides.get(str(instance["name"]), ())  # pyright: ignore[reportUnknownArgumentType]
                    ]

        _rewrite_json(project_dir / "rooms" / room.name / f"{room.name}.yy", update_room)


class TestVariableDefinitionsGodot(unittest.TestCase):
    def test_definitions_and_overrides_are_set_before_create(self) -> None:
        trace = self._run_trace(VARIABLE_DEFINITIONS_PROJECT, OBJECT_PROPERTIES, OBJECT_OVERRIDES, INSTANCE_OVERRIDES)
        self.assertEqual(trace[: len(_EXPECTED_TRACE)], _EXPECTED_TRACE)
        self.assertEqual(set(trace[len(_EXPECTED_TRACE):]), _EXPECTED_CHECKS)
        self.assertEqual(len(trace), len(_EXPECTED_TRACE) + len(_EXPECTED_CHECKS))

    def test_no_definitions_once_a_room_change_is_pending(self) -> None:
        trace = self._run_trace(_ROOM_CHANGE_PROJECT, _ROOM_CHANGE_PROPERTIES, {}, {})
        self.assertEqual(trace, ["created_late", "pre:marked", "create_marked:marked"])

    def _run_trace(
        self,
        project: GameMakerProject,
        properties: dict[str, Sequence[tuple[object, ...]]],
        object_overrides: dict[str, Sequence[tuple[str, str, str]]],
        instance_overrides: dict[str, Sequence[tuple[str, str, str]]],
    ) -> list[str]:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            write_variable_definitions(root / "gamemaker", project, properties, object_overrides, instance_overrides)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)
        trace_lines = [line for line in output.splitlines() if line.startswith("VARIABLE_DEFINITIONS_TRACE ")]
        self.assertEqual(len(trace_lines), 1, output)
        return json.loads(trace_lines[0].removeprefix("VARIABLE_DEFINITIONS_TRACE "))


if __name__ == "__main__":
    unittest.main()
