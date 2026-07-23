from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

import src.conversion.gml_transpiler as gml_transpiler
import src.conversion.gml_transpiler_parts.extension_functions as extension_functions
import src.conversion.gml_transpiler_parts.preprocessor as preprocessor
import src.conversion.gml_transpiler_parts.source_map as source_map
from src.conversion.gml_transpiler_parts.expression_models import (
    ArrayLiteral,
    ArrayRefAccess,
    Binary,
    Call,
    DSGridAccess,
    DSListAccess,
    DSMapAccess,
    EnumMember,
    Expression,
    FunctionLiteral,
    FunctionParameter,
    Grouped,
    Index,
    Literal,
    Member,
    Name,
    NameOf,
    NewCall,
    NumberLiteral,
    StringLiteral,
    StructAccess,
    StructLiteral,
    TemplateStringLiteral,
    Ternary,
    Unary,
    __all__ as EXPRESSION_MODEL_EXPORTS,
)
from src.conversion.gml_transpiler_parts.result_models import (
    GMLPreprocessResult,
    GMLPreprocessorDiagnostic,
    GMLSourceDiagnostic,
    GMLSourceMap,
    GMLSourceMapEntry,
    GMLTranspileResult,
    SourceDiagnosticSeverity,
    __all__ as RESULT_MODEL_EXPORTS,
)
from src.conversion.gml_transpiler_parts.shared_models import (
    AssignmentOperator,
    BuiltinVariableMetadata,
    DEFAULT_SCOPE_CONTEXT,
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    IncrementDelta,
    IncrementMode,
    ScopeContext,
    StaticDeclaration,
    Token,
    __all__ as SHARED_MODEL_EXPORTS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARTS_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts"

EXPECTED_SHARED_MODEL_EXPORTS = (
    "AssignmentOperator",
    "BuiltinVariableMetadata",
    "DEFAULT_SCOPE_CONTEXT",
    "GMLExtensionFunction",
    "GMLExtensionFunctionMapping",
    "GMLTranspileError",
    "IncrementDelta",
    "IncrementMode",
    "ScopeContext",
    "StaticDeclaration",
    "Token",
)
EXPECTED_EXPRESSION_MODEL_EXPORTS = (
    "ArrayLiteral",
    "ArrayRefAccess",
    "Binary",
    "Call",
    "DSGridAccess",
    "DSListAccess",
    "DSMapAccess",
    "EnumMember",
    "Expression",
    "FunctionLiteral",
    "FunctionParameter",
    "Grouped",
    "Index",
    "Literal",
    "Member",
    "Name",
    "NameOf",
    "NewCall",
    "NumberLiteral",
    "StringLiteral",
    "StructAccess",
    "StructLiteral",
    "TemplateStringLiteral",
    "Ternary",
    "Unary",
)
EXPECTED_RESULT_MODEL_EXPORTS = (
    "GMLPreprocessResult",
    "GMLPreprocessorDiagnostic",
    "GMLSourceDiagnostic",
    "GMLSourceMap",
    "GMLSourceMapEntry",
    "GMLTranspileResult",
    "SourceDiagnosticSeverity",
)


class TestGMLTranspilerModels(unittest.TestCase):
    def test_constructs_every_shared_phase_model_from_explicit_exports(self) -> None:
        assignment_operator: AssignmentOperator = "+="
        increment_delta: IncrementDelta = 1
        increment_mode: IncrementMode = "postfix"
        token = Token("IDENT", "score", line=2, column=3, index=4)
        metadata = BuiltinVariableMetadata(
            "instance",
            "0",
            True,
            False,
            "transform",
        )
        extension_function = GMLExtensionFunction("sdk_call", "SDK", 1, 2)
        extension_mapping = GMLExtensionFunctionMapping(
            "sdk_call",
            "SDKBridge.call",
            1,
            2,
        )
        scope = ScopeContext(
            self_expression="owner",
            other_expression="peer",
            instance_target="target",
            global_scope=True,
            global_names=frozenset({"score"}),
            asset_names=frozenset({"o_player"}),
            direct_instance_names=frozenset({"player"}),
            dynamic_instance_names=frozenset({"enemy"}),
            static_scope="scope",
            static_names=frozenset({"counter"}),
            static_prefix="prefix",
            extension_functions={"sdk_call": extension_function},
            extension_function_mappings={"sdk_call": extension_mapping},
        )
        declaration = StaticDeclaration("counter", "1")

        self.assertEqual(assignment_operator, "+=")
        self.assertEqual(increment_delta, 1)
        self.assertEqual(increment_mode, "postfix")
        self.assertEqual(
            token,
            Token("IDENT", "score", line=2, column=3, index=4),
        )
        self.assertEqual(metadata.subsystem, "transform")
        self.assertEqual(scope.extension_functions["sdk_call"], extension_function)
        self.assertEqual(scope.extension_function_mappings["sdk_call"], extension_mapping)
        self.assertEqual(declaration.value_source, "1")
        self.assertEqual(DEFAULT_SCOPE_CONTEXT, ScopeContext())

        first_default_scope = ScopeContext()
        second_default_scope = ScopeContext()
        self.assertIsNot(
            first_default_scope.extension_functions,
            second_default_scope.extension_functions,
        )
        self.assertIsNot(
            first_default_scope.extension_function_mappings,
            second_default_scope.extension_function_mappings,
        )
        with self.assertRaises(FrozenInstanceError):
            setattr(token, "kind", "NUMBER")

        error = GMLTranspileError("Unexpected token")
        located = error.with_location(4, 7)
        self.assertEqual(str(error), "Unexpected token")
        self.assertEqual(str(located), "Unexpected token at line 4, column 7")
        self.assertEqual((located.line, located.column), (4, 7))
        self.assertIs(located.with_location(8, 9), located)

    def test_constructs_every_expression_model_and_union_member(self) -> None:
        name = Name("score")
        name_of = NameOf("o_player")
        literal = Literal("undefined")
        string = StringLiteral('"text"')
        number = NumberLiteral("1.5", True)
        enum_member = EnumMember("State", "IDLE", 0)
        unary = Unary("-", number)
        binary = Binary(name, "+", number)
        ternary = Ternary(name, number, literal)
        call = Call(name, (number,))
        array = ArrayLiteral((number,))
        parameter = FunctionParameter("value", number)
        function = FunctionLiteral(
            "apply",
            (parameter,),
            ("return value",),
            is_constructor=True,
            static_scope_id="script:apply",
        )
        new_call = NewCall(name, (number,))
        struct = StructLiteral((("value", number),))
        index = Index(name, number)
        struct_access = StructAccess(name, string)
        map_access = DSMapAccess(name, string)
        list_access = DSListAccess(name, number)
        grid_access = DSGridAccess(name, number, number)
        array_ref_access = ArrayRefAccess(name, number)
        member = Member(name, "value")
        grouped = Grouped(binary)
        template = TemplateStringLiteral(("score=", name))
        expressions: tuple[Expression, ...] = (
            name,
            name_of,
            literal,
            string,
            template,
            number,
            enum_member,
            unary,
            binary,
            ternary,
            call,
            array,
            function,
            new_call,
            struct,
            index,
            struct_access,
            map_access,
            list_access,
            grid_access,
            array_ref_access,
            member,
            grouped,
        )

        self.assertEqual(len(expressions), 23)
        self.assertEqual(parameter.default, number)
        self.assertEqual(function.parameters, (parameter,))
        self.assertEqual(template.parts, ("score=", name))
        self.assertEqual(grouped.expr, binary)
        with self.assertRaises(FrozenInstanceError):
            setattr(name, "value", "other")

    def test_constructs_every_result_model_and_preserves_serialization(self) -> None:
        preprocessor_diagnostic = GMLPreprocessorDiagnostic(
            line=3,
            directive="#if",
            message="Unsupported condition",
            source="#if sdk",
        )
        preprocess_result = GMLPreprocessResult(
            source="score = 1;",
            diagnostics=(preprocessor_diagnostic,),
        )
        entry = GMLSourceMapEntry(
            generated_line=2,
            source_line=3,
            source_column=4,
            generated_text="score = 1",
            source_text="score = 1;",
            source_path="objects/o_player/Step_0.gml",
            event="_process",
        )
        source_map_value = GMLSourceMap(
            source_path="objects/o_player/Step_0.gml",
            event="_process",
            entries=(entry,),
        )
        transpile_result = GMLTranspileResult(
            code="score = 1",
            source_map=source_map_value,
            static_scope_id="object:o_player",
        )
        severity: SourceDiagnosticSeverity = "warning"
        source_diagnostic = GMLSourceDiagnostic(
            severity=severity,
            code="GM2GD-GML-RESERVED-NAME",
            message="reserved",
            line=1,
            column=5,
            identifier="class",
            suggested_name="class_",
        )

        self.assertEqual(
            preprocessor_diagnostic.format(),
            "Unsupported condition at line 3: #if sdk",
        )
        self.assertEqual(preprocess_result.diagnostics, (preprocessor_diagnostic,))
        self.assertEqual(
            entry.to_dict(),
            {
                "generated_line": 2,
                "source_line": 3,
                "source_column": 4,
                "generated_text": "score = 1",
                "source_text": "score = 1;",
                "source_path": "objects/o_player/Step_0.gml",
                "event": "_process",
            },
        )
        self.assertEqual(
            source_map_value.to_dict(),
            {
                "version": 1,
                "source_path": "objects/o_player/Step_0.gml",
                "event": "_process",
                "entries": [entry.to_dict()],
            },
        )
        self.assertEqual(
            source_map_value.with_generated_line_offset(2).entries[0].generated_line,
            4,
        )
        source_offset = source_map_value.with_source_offset(2, 3)
        self.assertEqual(
            (source_offset.entries[0].source_line, source_offset.entries[0].source_column),
            (5, 4),
        )
        self.assertEqual(transpile_result.source_map, source_map_value)
        self.assertEqual(source_diagnostic.suggested_name, "class_")
        with self.assertRaises(FrozenInstanceError):
            setattr(source_diagnostic, "line", 2)

    def test_supported_facade_and_phase_reexports_preserve_model_identity(self) -> None:
        self.assertIs(gml_transpiler.GMLTranspileError, GMLTranspileError)
        self.assertIs(gml_transpiler.GMLExtensionFunction, GMLExtensionFunction)
        self.assertIs(
            gml_transpiler.GMLExtensionFunctionMapping,
            GMLExtensionFunctionMapping,
        )
        self.assertIs(extension_functions.GMLExtensionFunction, GMLExtensionFunction)
        self.assertIs(
            extension_functions.GMLExtensionFunctionMapping,
            GMLExtensionFunctionMapping,
        )
        self.assertIs(gml_transpiler.GMLPreprocessResult, GMLPreprocessResult)
        self.assertIs(gml_transpiler.GMLPreprocessorDiagnostic, GMLPreprocessorDiagnostic)
        self.assertIs(preprocessor.GMLPreprocessResult, GMLPreprocessResult)
        self.assertIs(preprocessor.GMLPreprocessorDiagnostic, GMLPreprocessorDiagnostic)
        self.assertIs(gml_transpiler.GMLSourceDiagnostic, GMLSourceDiagnostic)
        self.assertIs(gml_transpiler.GMLSourceMap, GMLSourceMap)
        self.assertIs(gml_transpiler.GMLSourceMapEntry, GMLSourceMapEntry)
        self.assertIs(gml_transpiler.GMLTranspileResult, GMLTranspileResult)
        self.assertIs(source_map.GMLSourceDiagnostic, GMLSourceDiagnostic)
        self.assertIs(source_map.GMLSourceMap, GMLSourceMap)
        self.assertIs(source_map.GMLSourceMapEntry, GMLSourceMapEntry)

    def test_explicit_model_all_declarations_are_static_and_exact(self) -> None:
        expected_by_path = {
            PARTS_PATH / "shared_models.py": EXPECTED_SHARED_MODEL_EXPORTS,
            PARTS_PATH / "expression_models.py": EXPECTED_EXPRESSION_MODEL_EXPORTS,
            PARTS_PATH / "result_models.py": EXPECTED_RESULT_MODEL_EXPORTS,
        }
        runtime_exports = {
            PARTS_PATH / "shared_models.py": tuple(SHARED_MODEL_EXPORTS),
            PARTS_PATH / "expression_models.py": tuple(EXPRESSION_MODEL_EXPORTS),
            PARTS_PATH / "result_models.py": tuple(RESULT_MODEL_EXPORTS),
        }

        for path, expected in expected_by_path.items():
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                all_values = [
                    node.value
                    for node in tree.body
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == "__all__"
                    )
                ]
                self.assertEqual(len(all_values), 1)
                all_value = all_values[0]
                self.assertIsInstance(all_value, (ast.List, ast.Tuple))
                if not isinstance(all_value, (ast.List, ast.Tuple)):
                    self.fail(f"{path.name}.__all__ must be a literal list or tuple")
                static_exports = tuple(
                    element.value
                    for element in all_value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
                self.assertEqual(len(static_exports), len(all_value.elts))
                self.assertEqual(static_exports, expected)
                self.assertEqual(runtime_exports[path], expected)
                self.assertTrue(all(not name.startswith("_") for name in expected))

    def test_model_modules_are_dependency_only(self) -> None:
        model_paths = (
            PARTS_PATH / "shared_models.py",
            PARTS_PATH / "expression_models.py",
            PARTS_PATH / "result_models.py",
            PARTS_PATH / "model.py",
        )
        allowed_absolute_roots = frozenset({"__future__", "dataclasses", "typing"})
        allowed_relative_modules = frozenset(
            {"expression_models", "result_models", "shared_models"}
        )

        for path in model_paths:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for imported in node.names:
                            self.assertIn(
                                imported.name.split(".", maxsplit=1)[0],
                                allowed_absolute_roots,
                            )
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        if node.level:
                            self.assertIn(module, allowed_relative_modules)
                        else:
                            self.assertIn(
                                module.split(".", maxsplit=1)[0],
                                allowed_absolute_roots,
                            )


if __name__ == "__main__":
    unittest.main()
