from __future__ import annotations

import ast
from collections.abc import Sequence, Set
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast, get_args, get_origin, get_type_hints
import unittest

from src.conversion.gml_transpiler_parts import constants
from src.conversion.gml_transpiler_parts.shared_models import BuiltinVariableMetadata


PUBLIC_NAMES = (
    "EOF",
    "MULTI_CHAR_OPERATORS",
    "ASSIGNMENT_OPERATORS",
    "BINARY_PRECEDENCE",
    "UNARY_PRECEDENCE",
    "POSTFIX_PRECEDENCE",
    "PRIMARY_PRECEDENCE",
    "TERNARY_PRECEDENCE",
    "GML_IDENTIFIER_MAX_LENGTH",
    "GENERATED_IDENTIFIER_PREFIX",
    "RIGHT_ASSOCIATIVE",
    "GDSCRIPT_RESERVED_IDENTIFIERS",
    "GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS",
    "GML_LITERAL_IDENTIFIERS",
    "GML_BUILTIN_CONSTANT_IDENTIFIERS",
    "DIRECT_MEMBER_TARGETS",
    "BOOLEAN_RESULT_BINARY_OPERATORS",
    "BOOLEAN_RESULT_FUNCTIONS",
    "ARITHMETIC_RUNTIME_FUNCTIONS",
    "BITWISE_RUNTIME_FUNCTIONS",
    "COMPARISON_RUNTIME_FUNCTIONS",
    "DS_COLLECTIONS_FUNCTIONS",
    "COMPOUND_RUNTIME_FUNCTIONS",
    "OPERATOR_REPLACEMENTS",
    "NAME_REPLACEMENTS",
    "BLOCK_DELIMITER_REPLACEMENTS",
    "INSTANCE_NAME_REPLACEMENTS",
    "LEGACY_GLOBAL_BUILTINS",
    "BUILTIN_VARIABLE_REGISTRY",
    "BUILTIN_GLOBAL_VARIABLES",
    "BUILTIN_ARRAY_VARIABLES",
    "READ_ONLY_BUILTIN_VARIABLES",
    "BUILTIN_INSTANCE_VARIABLES",
    "VIRTUAL_KEY_ACTIONS",
    "VIRTUAL_KEY_CONSTANTS",
    "RUNTIME_FUNCTIONS",
    "MATH_RUNTIME_FUNCTIONS",
    "FILE_RUNTIME_FUNCTIONS",
    "BUFFER_RUNTIME_FUNCTIONS",
    "ASYNC_RUNTIME_FUNCTIONS",
    "NETWORK_RUNTIME_FUNCTIONS",
    "PHYSICS_RUNTIME_FUNCTIONS",
    "STRUCT_RUNTIME_FUNCTIONS",
    "VARIABLE_RUNTIME_FUNCTIONS",
    "DS_MAP_RUNTIME_FUNCTIONS",
    "DS_GRID_FUNCTIONS",
    "STRING_RUNTIME_FUNCTIONS",
    "ARRAY_RUNTIME_FUNCTIONS",
    "ASSET_RUNTIME_FUNCTIONS",
    "INSTANCE_RUNTIME_FUNCTIONS",
    "COLLISION_RUNTIME_FUNCTIONS",
    "MOTION_RUNTIME_FUNCTIONS",
    "PATH_RUNTIME_FUNCTIONS",
    "MP_GRID_RUNTIME_FUNCTIONS",
    "INPUT_RUNTIME_FUNCTIONS",
    "AUDIO_RUNTIME_FUNCTIONS",
    "TIME_RUNTIME_FUNCTIONS",
    "ROOM_RUNTIME_FUNCTIONS",
    "LAYER_RUNTIME_FUNCTIONS",
    "SEQUENCE_TIMELINE_RUNTIME_FUNCTIONS",
    "FLEXPANEL_RUNTIME_FUNCTIONS",
    "OS_DEBUG_GC_RUNTIME_FUNCTIONS",
    "PLATFORM_SERVICE_RUNTIME_FUNCTIONS",
    "DRAW_RUNTIME_FUNCTIONS",
)

MAPPING_NAMES = tuple(
    name
    for name in PUBLIC_NAMES
    if (name.endswith("FUNCTIONS") and name != "BOOLEAN_RESULT_FUNCTIONS")
    or name.endswith("REPLACEMENTS")
    or name
    in {
        "BINARY_PRECEDENCE",
        "BUILTIN_VARIABLE_REGISTRY",
        "COMPOUND_RUNTIME_FUNCTIONS",
        "VIRTUAL_KEY_ACTIONS",
        "VIRTUAL_KEY_CONSTANTS",
    }
)

FROZEN_SET_NAMES = (
    "RIGHT_ASSOCIATIVE",
    "GDSCRIPT_RESERVED_IDENTIFIERS",
    "GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS",
    "GML_LITERAL_IDENTIFIERS",
    "GML_BUILTIN_CONSTANT_IDENTIFIERS",
    "DIRECT_MEMBER_TARGETS",
    "BOOLEAN_RESULT_BINARY_OPERATORS",
    "BOOLEAN_RESULT_FUNCTIONS",
    "LEGACY_GLOBAL_BUILTINS",
    "BUILTIN_GLOBAL_VARIABLES",
    "BUILTIN_ARRAY_VARIABLES",
    "READ_ONLY_BUILTIN_VARIABLES",
    "BUILTIN_INSTANCE_VARIABLES",
)

TUPLE_NAMES = ("MULTI_CHAR_OPERATORS", "ASSIGNMENT_OPERATORS")


class GmlLanguageMetadataTests(unittest.TestCase):
    def test_exact_public_surface(self) -> None:
        self.assertEqual(tuple(constants.__all__), PUBLIC_NAMES)
        self.assertEqual(len(constants.__all__), 64)
        self.assertTrue(all(not name.startswith("_") for name in constants.__all__))

    def test_public_declarations_are_final_and_direct_literals(self) -> None:
        hints = get_type_hints(constants, include_extras=True)
        self.assertEqual(
            {name for name in PUBLIC_NAMES if get_origin(hints.get(name)) is Final},
            set(PUBLIC_NAMES),
        )
        self.assertIs(get_origin(hints.get("__all__")), Final)
        for name in TUPLE_NAMES:
            with self.subTest(name=name):
                annotation = get_args(hints[name])[0]
                self.assertIs(get_origin(annotation), Sequence)
        for name in FROZEN_SET_NAMES:
            with self.subTest(name=name):
                annotation = get_args(hints[name])[0]
                self.assertIs(get_origin(annotation), Set)

        module_path = Path(constants.__file__)
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        declarations = {
            node.target.id: node
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertEqual(set(PUBLIC_NAMES), set(declarations) & set(PUBLIC_NAMES))

        all_value = declarations["__all__"].value
        self.assertIsInstance(all_value, ast.Tuple)
        assert isinstance(all_value, ast.Tuple)
        self.assertEqual(len(all_value.elts), len(PUBLIC_NAMES))
        self.assertTrue(
            all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in all_value.elts)
        )
        self.assertEqual(
            tuple(cast(ast.Constant, element).value for element in all_value.elts),
            PUBLIC_NAMES,
        )

        for name in MAPPING_NAMES:
            with self.subTest(name=name):
                value = declarations[name].value
                self.assertIsInstance(value, ast.Call)
                assert isinstance(value, ast.Call)
                self.assertIsInstance(value.func, ast.Name)
                assert isinstance(value.func, ast.Name)
                self.assertEqual(value.func.id, "MappingProxyType")
                self.assertEqual(len(value.args), 1)
                self.assertIsInstance(value.args[0], ast.Dict)

    def test_mapping_exports_are_read_only_mapping_proxies(self) -> None:
        for name in MAPPING_NAMES:
            with self.subTest(name=name):
                value = getattr(constants, name)
                self.assertIsInstance(value, MappingProxyType)
                with self.assertRaises(TypeError):
                    value["__mutation_probe__"] = "changed"
                if value:
                    with self.assertRaises(TypeError):
                        del value[next(iter(value))]

    def test_set_exports_are_frozensets(self) -> None:
        for name in FROZEN_SET_NAMES:
            with self.subTest(name=name):
                value = getattr(constants, name)
                self.assertIsInstance(value, frozenset)
                with self.assertRaises(AttributeError):
                    value.add("__mutation_probe__")

    def test_sequence_exports_remain_tuples(self) -> None:
        for name in TUPLE_NAMES:
            with self.subTest(name=name):
                self.assertIsInstance(getattr(constants, name), tuple)

    def test_registry_values_are_frozen(self) -> None:
        self.assertTrue(constants.BUILTIN_VARIABLE_REGISTRY)
        values: list[object] = []
        values.extend(constants.BUILTIN_VARIABLE_REGISTRY.values())
        self.assertTrue(all(isinstance(metadata, BuiltinVariableMetadata) for metadata in values))
        metadata = constants.BUILTIN_VARIABLE_REGISTRY["x"]
        with self.assertRaises(FrozenInstanceError):
            cast(Any, metadata).scope = "global"

    def test_facade_compatibility_alias_preserves_registry_identity(self) -> None:
        self.assertIs(
            getattr(constants, "_BUILTIN_VARIABLE_REGISTRY"),
            constants.BUILTIN_VARIABLE_REGISTRY,
        )
        self.assertEqual(
            [name for name in vars(constants) if name.startswith("_") and name[1:] in PUBLIC_NAMES],
            ["_BUILTIN_VARIABLE_REGISTRY"],
        )


if __name__ == "__main__":
    unittest.main()
