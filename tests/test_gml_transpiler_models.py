from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from src.conversion.gml_transpiler_parts.expression_models import (
    ArrayLiteral,
    ArrayRefAccess,
    Binary,
    Call,
    DSGridAccess,
    DSListAccess,
    DSMapAccess,
    EnumMember,
    FunctionLiteral,
    FunctionParameter,
    GMLExpression,
    GMLExpressionEmission,
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
)
from src.conversion.gml_transpiler_parts.extension_functions import (
    GMLExtensionFunction as extension_gml_extension_function,
    GMLExtensionFunctionMapping as extension_gml_extension_function_mapping,
)
from src.conversion.gml_transpiler_parts.result_models import (
    GMLPreprocessorDiagnostic,
    GMLPreprocessResult,
    GMLSourceDiagnostic,
    GMLSourceMap,
    GMLSourceMapEntry,
    GMLTranspileResult,
    SourceDiagnosticSeverity,
)
from src.conversion.gml_transpiler_parts.shared_models import (
    DEFAULT_SCOPE_CONTEXT,
    AssignmentOperator,
    BuiltinVariableMetadata,
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    IncrementDelta,
    IncrementMode,
    ScopeContext,
    StaticDeclaration,
    Token,
)
from src.conversion.gml_transpiler_parts.source_map import (
    GMLSourceDiagnostic as source_map_gml_source_diagnostic,
    GMLSourceMap as source_map_gml_source_map,
    GMLSourceMapEntry as source_map_gml_source_map_entry,
)
from src.conversion.gml_transpiler_parts.statement_models import (
    ControlFlowCapture,
    GMLStatementRequest,
    GMLStatementResult,
)
from tests.gml_facade_contract_support import static_all_exports

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
    "GMLExpression",
    "GMLExpressionEmission",
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
EXPECTED_STATEMENT_MODEL_EXPORTS = (
    "ControlFlowCapture",
    "GMLStatementRequest",
    "GMLStatementResult",
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
        expressions: tuple[GMLExpression, ...] = (
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
        expression_emission = GMLExpressionEmission("score", 130)
        self.assertEqual(expression_emission.text, "score")
        self.assertEqual(expression_emission.precedence, 130)
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

    def test_constructs_every_statement_model_and_preserves_mutable_channels(self) -> None:
        token = Token("IDENT", "score", line=2, column=3, index=4)
        instance_variables = {"existing"}
        enum_values = {"State": {"IDLE": 0}}
        macro_values = {"STEP": "2"}
        macro_priorities = {"STEP": 2}
        extension_function = GMLExtensionFunction("sdk_call", "SDK", 1, 2)
        extension_mapping = GMLExtensionFunctionMapping(
            "sdk_call",
            "SDKBridge.call",
            1,
            2,
        )
        scope = ScopeContext(self_expression="owner", other_expression="peer")
        request = GMLStatementRequest(
            tokens=(token,),
            local_names=frozenset({"local"}),
            instance_variables=instance_variables,
            return_depth=1,
            enum_values=enum_values,
            enum_names=frozenset({"State"}),
            scope_context=scope,
            inherited_event_call="super._process(delta)",
            macro_values=macro_values,
            macro_priorities=macro_priorities,
            macro_configuration="Android",
            top_level_global_scope=True,
            global_names=frozenset({"global_score"}),
            asset_names=frozenset({"o_player"}),
            static_scope_prefix="scr_test.scr_test",
            extension_functions={"sdk_call": extension_function},
            extension_function_mappings={"sdk_call": extension_mapping},
        )
        capture = ControlFlowCapture(
            "_gml_control_0",
            2,
            1,
            capture_return=True,
            capture_exit=True,
            capture_throw=True,
            capture_break=True,
            capture_continue=True,
        )
        result = GMLStatementResult(
            lines=("score = 1",),
            local_names=frozenset({"local"}),
            instance_variables=instance_variables,
            scope_context=scope,
            enum_values=enum_values,
            enum_names=frozenset({"State"}),
            macro_values=macro_values,
        )

        self.assertEqual(request.tokens, (token,))
        self.assertIs(request.instance_variables, instance_variables)
        self.assertIs(request.enum_values, enum_values)
        self.assertIs(request.macro_values, macro_values)
        self.assertIs(request.macro_priorities, macro_priorities)
        self.assertTrue(capture.capture_continue)
        self.assertEqual(result.lines, ("score = 1",))
        self.assertIs(result.instance_variables, instance_variables)
        self.assertIs(result.enum_values, enum_values)
        self.assertIs(result.macro_values, macro_values)
        for value, attribute in (
            (request, "return_depth"),
            (capture, "loop_depth"),
            (result, "lines"),
        ):
            with self.subTest(model=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, attribute, None)

    def test_phase_reexports_preserve_model_identity(self) -> None:
        self.assertIs(extension_gml_extension_function, GMLExtensionFunction)
        self.assertIs(
            extension_gml_extension_function_mapping,
            GMLExtensionFunctionMapping,
        )
        self.assertIs(source_map_gml_source_diagnostic, GMLSourceDiagnostic)
        self.assertIs(source_map_gml_source_map, GMLSourceMap)
        self.assertIs(source_map_gml_source_map_entry, GMLSourceMapEntry)

    def test_explicit_model_all_declarations_are_static_and_exact(self) -> None:
        expected_by_path = {
            PARTS_PATH / "shared_models.py": EXPECTED_SHARED_MODEL_EXPORTS,
            PARTS_PATH / "expression_models.py": EXPECTED_EXPRESSION_MODEL_EXPORTS,
            PARTS_PATH / "result_models.py": EXPECTED_RESULT_MODEL_EXPORTS,
            PARTS_PATH / "statement_models.py": EXPECTED_STATEMENT_MODEL_EXPORTS,
        }
        for path, expected in expected_by_path.items():
            with self.subTest(path=path.name):
                exports = static_all_exports(path.read_text(encoding="utf-8"))
                self.assertEqual(exports, expected)
                self.assertTrue(all(not name.startswith("_") for name in exports))
    def test_model_modules_are_dependency_only(self) -> None:
        model_paths = (
            PARTS_PATH / "shared_models.py",
            PARTS_PATH / "expression_models.py",
            PARTS_PATH / "result_models.py",
            PARTS_PATH / "statement_models.py",
        )
        allowed_absolute_roots = frozenset({"__future__", "dataclasses", "typing"})
        allowed_relative_modules = frozenset(
            {
                "expression_models",
                "result_models",
                "shared_models",
                "statement_models",
            }
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
