"""Object Variable Definitions: parsing, GML values and generated code."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from src.conversion.json_values import JsonObject
from src.conversion.object_variables import (
    VAR_TYPE_ASSET,
    VAR_TYPE_BOOLEAN,
    VAR_TYPE_COLOUR,
    VAR_TYPE_EXPRESSION,
    VAR_TYPE_INTEGER,
    VAR_TYPE_LIST,
    VAR_TYPE_REAL,
    VAR_TYPE_STRING,
    VariableDefinition,
    VariableOverride,
    object_pre_create_gml,
    parse_variable_definitions,
    parse_variable_overrides,
    variable_value_gml,
)
from src.conversion.script_generator import ObjectRuntimeConfig, generate_script_content
from tests.gamemaker_project_support import (
    EVENT_CREATE,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    InstanceLayer,
    RoomInstance,
    convert_gamemaker_project,
    write_gamemaker_project,
)
from tests.test_variable_definitions_godot import (
    INSTANCE_OVERRIDES,
    OBJECT_OVERRIDES,
    OBJECT_PROPERTIES,
    VARIABLE_DEFINITIONS_PROJECT,
    write_variable_definitions,
)


def _definition(var_type: int, value: str = "", multiselect: bool = False) -> VariableDefinition:
    return VariableDefinition("v", var_type, value, multiselect)


def _function_body(script: str, name: str) -> str:
    match = re.search(rf"^func {name}\(.*?\):\n(.*?)(?=^func |\Z)", script, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} not in script"
    return match.group(1)


class TestVariableDefinitionParsing(unittest.TestCase):
    def test_reads_definitions_in_order(self) -> None:
        definitions = parse_variable_definitions(
            [
                {"name": "speed_max", "varType": 0, "value": "4.5"},
                {"varName": "legacy", "varType": 2, "value": '"old"'},
                {"name": "choices", "varType": 6, "value": '"a","b"', "multiselect": True},
                {"name": "no_type", "value": "1"},
                {"name": "9bad", "varType": 0, "value": "1"},
                {"name": "no_value", "varType": 0},
                "not a property",
            ]
        )
        self.assertEqual(
            definitions,
            (
                VariableDefinition("speed_max", VAR_TYPE_REAL, "4.5"),
                VariableDefinition("legacy", VAR_TYPE_STRING, '"old"'),
                VariableDefinition("choices", VAR_TYPE_LIST, '"a","b"', multiselect=True),
                VariableDefinition("no_type", VAR_TYPE_EXPRESSION, "1"),
            ),
        )
        self.assertEqual(parse_variable_definitions(None), ())

    def test_reads_overrides_with_their_defining_object(self) -> None:
        overrides = parse_variable_overrides(
            [
                {
                    "objectId": {"name": "o_parent", "path": "objects/o_parent/o_parent.yy"},
                    "propertyId": {"name": "hp", "path": "objects/o_parent/o_parent.yy"},
                    "value": "10",
                },
                # The IDE can leave an override without its property.
                {"objectId": None, "propertyId": None, "value": "10"},
                {"objectId": None, "propertyId": {"name": "lives"}, "value": 3},
            ]
        )
        self.assertEqual(
            overrides,
            (VariableOverride("o_parent", "hp", "10"), VariableOverride(None, "lives", "3")),
        )


class TestVariableValueGml(unittest.TestCase):
    def test_values_are_gml_source(self) -> None:
        self.assertEqual(variable_value_gml("1.5", _definition(VAR_TYPE_REAL)), "1.5")
        self.assertEqual(variable_value_gml("3", _definition(VAR_TYPE_INTEGER)), "3")
        self.assertEqual(variable_value_gml('"hi"', _definition(VAR_TYPE_STRING)), '"hi"')
        self.assertEqual(variable_value_gml("@'raw'", _definition(VAR_TYPE_STRING)), "@'raw'")
        self.assertEqual(variable_value_gml("sqrt(85 * 6) + 5.5", _definition(VAR_TYPE_EXPRESSION)), "sqrt(85 * 6) + 5.5")
        self.assertEqual(variable_value_gml("spr_player", _definition(VAR_TYPE_ASSET)), "spr_player")
        self.assertEqual(variable_value_gml('"b"', _definition(VAR_TYPE_LIST)), '"b"')
        self.assertEqual(variable_value_gml("$FF0000FF", _definition(VAR_TYPE_COLOUR)), "$FF0000FF")
        # An override whose definition is unknown is a plain expression.
        self.assertEqual(variable_value_gml("True", None), "True")

    def test_booleans_are_stored_as_true_or_false(self) -> None:
        for value, expected in (("True", "true"), ("False", "false"), ("true", "true"), ("0", "false"), ("1", "true")):
            self.assertEqual(variable_value_gml(value, _definition(VAR_TYPE_BOOLEAN)), expected)
        self.assertEqual(variable_value_gml("flag && other_flag", _definition(VAR_TYPE_BOOLEAN)), "flag && other_flag")

    def test_unquoted_string_is_quoted(self) -> None:
        self.assertEqual(
            variable_value_gml('say "hi"\\now\n', _definition(VAR_TYPE_STRING)),
            '"say \\"hi\\"\\\\now\\n"',
        )

    def test_multiselect_list_is_an_array(self) -> None:
        self.assertEqual(variable_value_gml('"a","c"', _definition(VAR_TYPE_LIST, multiselect=True)), '["a","c"]')
        self.assertEqual(variable_value_gml("", _definition(VAR_TYPE_LIST, multiselect=True)), "[]")

    def test_pre_create_runs_parent_then_overrides_then_own_definitions(self) -> None:
        inherited = {"flag": VariableDefinition("flag", VAR_TYPE_BOOLEAN, "True")}
        source = object_pre_create_gml(
            (VariableDefinition("own", VAR_TYPE_EXPRESSION, "flag ? 1 : 2"),),
            (VariableOverride("o_parent", "flag", "False"),),
            inherited,
            inherited=True,
        )
        self.assertEqual(source, "event_inherited();\nflag = false;\nown = flag ? 1 : 2;\n")
        self.assertEqual(
            object_pre_create_gml((VariableDefinition("hp", VAR_TYPE_INTEGER, "5"),), (), {}, inherited=False),
            "hp = 5;\n",
        )


class TestVariableDefinitionScripts(unittest.TestCase):
    def test_ready_runs_definitions_before_the_create_event(self) -> None:
        event: JsonObject = {"eventType": 0, "eventNum": 0}
        script = generate_script_content(
            [event],
            code_bodies={"_ready": "\ttrace(hp)", "_gm_variable_definitions": "\thp = 5"},
            instance_variables={"hp"},
            object_runtime=ObjectRuntimeConfig(object_name="o_unit", runs_variable_definitions=True),
        )
        self.assertEqual(_function_body(script, "_gm_variable_definitions").strip(), "hp = 5")
        ready = _function_body(script, "_ready")
        self.assertLess(ready.index("_gm_initialize_motion_runtime()"), ready.index("GMRuntime.gml_instance_pre_create(self)"))
        self.assertLess(ready.index("GMRuntime.gml_instance_pre_create(self)"), ready.index("gml_event_create_blocked"))

    def test_object_without_create_event_still_runs_definitions(self) -> None:
        script = generate_script_content(
            [],
            object_runtime=ObjectRuntimeConfig(object_name="o_unit", runs_variable_definitions=True, inherit_ready=True),
            base_script_path="res://objects/o_parent/o_parent.gd",
        )
        ready = _function_body(script, "_ready").rstrip().splitlines()
        self.assertEqual(ready[-2:], ["\tGMRuntime.gml_instance_pre_create(self)", "\tsuper._ready()"])
        self.assertNotIn("func _gm_variable_definitions", script)

    def test_objects_without_definitions_are_unchanged(self) -> None:
        script = generate_script_content([], object_runtime=ObjectRuntimeConfig(object_name="o_unit"))
        self.assertNotIn("gml_instance_pre_create", script)


class TestVariableDefinitionConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        write_gamemaker_project(root / "gamemaker", VARIABLE_DEFINITIONS_PROJECT)
        write_variable_definitions(root / "gamemaker", VARIABLE_DEFINITIONS_PROJECT, OBJECT_PROPERTIES, OBJECT_OVERRIDES, INSTANCE_OVERRIDES)
        cls.logs = convert_gamemaker_project(root / "gamemaker", root / "godot")
        cls.godot_dir = root / "godot"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _script(self, relative_path: str) -> str:
        return (self.godot_dir / relative_path).read_text(encoding="utf-8")

    def test_object_declares_and_assigns_its_definitions_in_order(self) -> None:
        script = self._script("objects/o_base/o_base.gd")
        self.assertIn("\nvar v_int\n", script)
        body = _function_body(script, "_gm_variable_definitions")
        names = re.findall(r"^\t(\w+) = ", body, re.MULTILINE)
        self.assertEqual(names, [str(entry[0]) for entry in OBJECT_PROPERTIES["o_base"]])
        self.assertIn('\tv_str = "hello"\n', body)
        self.assertIn("\tv_true = true\n\tv_false = false\n", body)
        self.assertIn('\tv_multi = ["a", "c"]\n', body)
        self.assertIn("\tv_expr = GMRuntime.gml_add(GMRuntime.gml_mul(v_int, 2), 100)\n", body)
        self.assertIn('\tv_asset = GMRuntime.gml_asset_get_index("o_other")\n', body)
        ready = _function_body(script, "_ready")
        self.assertLess(ready.index("gml_instance_pre_create(self)"), ready.index("gml_event_create_blocked(self)"))

    def test_child_runs_parent_definitions_then_overrides_then_its_own(self) -> None:
        script = self._script("objects/o_child/o_child.gd")
        self.assertNotIn("\nvar v_int", script)
        self.assertIn("\nvar c_own\n", script)
        lines = _function_body(script, "_gm_variable_definitions").strip().splitlines()
        self.assertEqual(lines[0].strip(), "super._gm_variable_definitions()")
        self.assertIn('"v_int", 7', lines[1])
        self.assertIn('"v_str", "child"', lines[2])
        self.assertTrue(lines[3].strip().startswith("c_own = "))

    def test_descendants_without_definitions_inherit_them(self) -> None:
        script = self._script("objects/o_grand/o_grand.gd")
        self.assertNotIn("func _gm_variable_definitions", script)
        self.assertIn("\tGMRuntime.gml_instance_pre_create(self)\n", _function_body(script, "_ready"))
        self.assertNotIn("gml_instance_pre_create", self._script("objects/o_spawner/o_spawner.gd"))

    def test_room_script_assigns_each_instances_overrides(self) -> None:
        script = self._script("rooms/r_main/r_main.gd")
        dispatcher = _function_body(script, "_gm2godot_run_instance_pre_create_code")
        self.assertEqual(
            re.findall(r'^\t\t"(\w+)":', dispatcher, re.MULTILINE),
            ["inst_base2", "inst_child1", "inst_grand1", "inst_plain1"],
        )
        base2 = _function_body(script, "_gm2godot_instance_pre_create_inst_base2")
        self.assertEqual(
            base2.strip().splitlines(),
            [
                'GMRuntime.gml_variable_instance_set(_gm_instance, "v_str", "room")',
                '\tGMRuntime.gml_variable_instance_set(_gm_instance, "v_true", false)',
                '\tGMRuntime.gml_variable_instance_set(_gm_instance, "v_multi", ["b"])',
                '\tGMRuntime.gml_variable_instance_set(_gm_instance, "v_expr", '
                'GMRuntime.gml_mul(GMRuntime.gml_variable_instance_get(_gm_instance, "v_int"), 1000))',
            ],
        )
        # Project macros expand in room overrides.
        self.assertIn('"v_func", GMRuntime.gml_add(100, 1)', _function_body(script, "_gm2godot_instance_pre_create_inst_grand1"))


class TestVariableDefinitionFailures(unittest.TestCase):
    def test_untranspilable_definition_skips_the_object(self) -> None:
        project = GameMakerProject(
            name="BrokenDefinitions",
            objects=(GameMakerObject("o_broken", {EVENT_CREATE: "x = 1;\n"}),),
            rooms=(
                GameMakerRoom(
                    "r_room",
                    layers=(InstanceLayer("Instances", 0, (RoomInstance("inst_broken", "o_broken", 0, 0),)),),
                    creation_order=("inst_broken",),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", project)
            write_variable_definitions(
                root / "gamemaker",
                project,
                {"o_broken": (("bad", VAR_TYPE_EXPRESSION, "1 +"),)},
                {},
                {"inst_broken": (("o_broken", "bad", "2 *"),)},
            )
            logs = convert_gamemaker_project(root / "gamemaker", root / "godot")
            self.assertFalse((root / "godot" / "objects" / "o_broken" / "o_broken.gd").exists())
            self.assertFalse((root / "godot" / "rooms" / "r_room" / "r_room.tscn").exists())
        self.assertIn(
            "Warning: Could not transpile GameMaker event code for o_broken/Variable Definitions: "
            "Expected expression, got:  at line 1, column 4",
            logs,
        )
        self.assertIn(
            "Warning: Could not transpile the Room Editor variable overrides (pre-creation code for "
            "inst_broken) for room r_room: Expected expression, got:  at line 1, column 4",
            logs,
        )


if __name__ == "__main__":
    unittest.main()
