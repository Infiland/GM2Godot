from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from src.conversion.gml_transpiler_parts.constants import BUILTIN_VARIABLE_REGISTRY
from src.conversion.gml_transpiler_parts.shared_models import BuiltinVariableMetadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PATH = (
    PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts" / "constants.py"
)
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


def _declarations() -> dict[str, ast.AnnAssign]:
    tree = ast.parse(CONSTANTS_PATH.read_text(encoding="utf-8"), filename=str(CONSTANTS_PATH))
    return {
        node.target.id: node
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

def _literal_export_names(declaration: ast.AnnAssign) -> tuple[str, ...]:
    value = declaration.value
    if not isinstance(value, ast.Tuple):
        raise AssertionError("constants.__all__ must remain a literal tuple")
    exports: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            raise AssertionError("constants.__all__ must contain only literal strings")
        exports.append(element.value)
    return tuple(exports)


class GmlLanguageMetadataTests(unittest.TestCase):
    def test_exact_public_surface(self) -> None:
        declarations = _declarations()
        exports = _literal_export_names(declarations["__all__"])
        self.assertEqual(exports, PUBLIC_NAMES)
        self.assertEqual(len(exports), 64)
        self.assertTrue(all(not name.startswith("_") for name in exports))

    def test_public_declarations_are_final_and_direct_literals(self) -> None:
        declarations = _declarations()
        self.assertEqual(set(PUBLIC_NAMES), set(declarations) & set(PUBLIC_NAMES))
        for name in (*PUBLIC_NAMES, "__all__"):
            with self.subTest(name=name):
                self.assertTrue(ast.unparse(declarations[name].annotation).startswith("Final["))
        for name in TUPLE_NAMES:
            with self.subTest(name=name):
                self.assertIn("Sequence[", ast.unparse(declarations[name].annotation))
        for name in FROZEN_SET_NAMES:
            with self.subTest(name=name):
                self.assertIn("Set[", ast.unparse(declarations[name].annotation))

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

    def test_registry_export_is_read_only_mapping_proxy(self) -> None:
        self.assertIsInstance(BUILTIN_VARIABLE_REGISTRY, MappingProxyType)
        mutable_registry = cast(Any, BUILTIN_VARIABLE_REGISTRY)
        with self.assertRaises(TypeError):
            mutable_registry["__mutation_probe__"] = "changed"
        with self.assertRaises(TypeError):
            del mutable_registry[next(iter(mutable_registry))]

    def test_registry_values_are_frozen(self) -> None:
        self.assertTrue(BUILTIN_VARIABLE_REGISTRY)
        values: list[object] = list(BUILTIN_VARIABLE_REGISTRY.values())
        self.assertTrue(all(isinstance(metadata, BuiltinVariableMetadata) for metadata in values))
        metadata = BUILTIN_VARIABLE_REGISTRY["x"]
        with self.assertRaises(FrozenInstanceError):
            cast(Any, metadata).scope = "global"

    def test_removed_registry_compatibility_alias_cannot_return(self) -> None:
        declarations = _declarations()
        self.assertNotIn("_BUILTIN_VARIABLE_REGISTRY", declarations)
        self.assertNotIn("_BUILTIN_VARIABLE_REGISTRY", CONSTANTS_PATH.read_text(encoding="utf-8"))
