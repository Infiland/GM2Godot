from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, is_dataclass
import inspect
from pathlib import Path
import subprocess
import sys
from typing import (
    Final,
    Iterable,
    Mapping,
    MutableMapping,
    MutableSet,
    get_args,
    get_origin,
    get_type_hints,
)
import unittest

import src.conversion.gml_transpiler as gml_transpiler
from src.conversion.gml_transpiler_parts import statement_api, statement_models
from src.conversion.gml_transpiler_parts.lexical_api import tokenize_gml_source
from src.conversion.gml_transpiler_parts.shared_models import (
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    ScopeContext,
    StaticDeclaration,
    Token,
)
from src.conversion.gml_transpiler_parts.statement_api import (
    collect_static_declarations,
    parse_gml_statements,
    static_scope_id,
)
from src.conversion.gml_transpiler_parts.statement_models import (
    ControlFlowCapture,
    GMLStatementRequest,
    GMLStatementResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARTS_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts"

PUBLIC_NAMES = (
    "collect_static_declarations",
    "parse_gml_statements",
    "static_scope_id",
)
MODEL_NAMES = (
    "ControlFlowCapture",
    "GMLStatementRequest",
    "GMLStatementResult",
)
EXPECTED_SIGNATURES = {
    "collect_static_declarations": (
        "(tokens: 'Iterable[Token]') -> 'tuple[StaticDeclaration, ...]'"
    ),
    "parse_gml_statements": (
        "(request: 'GMLStatementRequest') -> 'GMLStatementResult'"
    ),
    "static_scope_id": (
        "(prefix: 'str', name: 'str | None', position: 'int', "
        "body_tokens: 'Iterable[Token]') -> 'str'"
    ),
}

CONTROL_FLOW_CAPTURE_FIELDS = (
    "variable_name",
    "loop_depth",
    "continue_depth",
    "capture_return",
    "capture_exit",
    "capture_throw",
    "capture_break",
    "capture_continue",
)
STATEMENT_REQUEST_FIELDS = (
    "tokens",
    "local_names",
    "instance_variables",
    "return_depth",
    "enum_values",
    "enum_names",
    "scope_context",
    "inherited_event_call",
    "macro_values",
    "macro_priorities",
    "macro_configuration",
    "top_level_global_scope",
    "global_names",
    "asset_names",
    "static_scope_prefix",
    "extension_functions",
    "extension_function_mappings",
)
STATEMENT_RESULT_FIELDS = (
    "lines",
    "local_names",
    "instance_variables",
    "scope_context",
    "enum_values",
    "enum_names",
    "macro_values",
)

EXPECTED_MODEL_SIGNATURES = {
    ControlFlowCapture: (
        "(variable_name: 'str', loop_depth: 'int', continue_depth: 'int', "
        "capture_return: 'bool' = False, capture_exit: 'bool' = False, "
        "capture_throw: 'bool' = False, capture_break: 'bool' = False, "
        "capture_continue: 'bool' = False) -> None"
    ),
    GMLStatementRequest: (
        "(tokens: 'tuple[Token, ...]', local_names: 'frozenset[str]' = frozenset(), "
        "instance_variables: 'MutableSet[str] | None' = None, return_depth: 'int' = 0, "
        "enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'frozenset[str]' = frozenset(), "
        "scope_context: 'ScopeContext | None' = None, "
        "inherited_event_call: 'str | None' = None, "
        "macro_values: 'MutableMapping[str, str] | None' = None, "
        "macro_priorities: 'MutableMapping[str, int] | None' = None, "
        "macro_configuration: 'str | None' = None, "
        "top_level_global_scope: 'bool' = False, "
        "global_names: 'frozenset[str]' = frozenset(), "
        "asset_names: 'frozenset[str]' = frozenset(), "
        "static_scope_prefix: 'str | None' = None, "
        "extension_functions: 'Mapping[str, GMLExtensionFunction] | None' = None, "
        "extension_function_mappings: "
        "'Mapping[str, GMLExtensionFunctionMapping] | None' = None) -> None"
    ),
    GMLStatementResult: (
        "(lines: 'tuple[str, ...]', local_names: 'frozenset[str]', "
        "instance_variables: 'MutableSet[str] | None', scope_context: 'ScopeContext', "
        "enum_values: 'MutableMapping[str, dict[str, int]]', "
        "enum_names: 'frozenset[str]', "
        "macro_values: 'MutableMapping[str, str]') -> None"
    ),
}


class GMLStatementAPITests(unittest.TestCase):
    def test_exact_static_alphabetized_api_and_model_surfaces(self) -> None:
        self.assertEqual(tuple(statement_api.__all__), PUBLIC_NAMES)
        self.assertEqual(tuple(sorted(statement_api.__all__)), PUBLIC_NAMES)
        self.assertEqual(tuple(statement_models.__all__), MODEL_NAMES)
        self.assertEqual(tuple(sorted(statement_models.__all__)), MODEL_NAMES)

        for module, expected_names in (
            (statement_api, PUBLIC_NAMES),
            (statement_models, MODEL_NAMES),
        ):
            with self.subTest(module=module.__name__):
                self.assertTrue(
                    all(not name.startswith("_") for name in module.__all__)
                )
                module_path_value = module.__file__
                self.assertIsNotNone(module_path_value)
                assert module_path_value is not None
                module_path = Path(module_path_value)
                tree = ast.parse(
                    module_path.read_text(encoding="utf-8"),
                    filename=str(module_path),
                )
                declarations = [
                    node
                    for node in tree.body
                    if (
                        isinstance(node, ast.AnnAssign)
                        and isinstance(node.target, ast.Name)
                        and node.target.id == "__all__"
                    )
                ]
                self.assertEqual(len(declarations), 1)
                declaration = declarations[0]
                assert isinstance(declaration, ast.AnnAssign)
                value = declaration.value
                self.assertIsInstance(value, ast.Tuple)
                assert isinstance(value, ast.Tuple)
                self.assertEqual(
                    tuple(
                        element.value
                        for element in value.elts
                        if (
                            isinstance(element, ast.Constant)
                            and isinstance(element.value, str)
                        )
                    ),
                    expected_names,
                )
                self.assertEqual(len(value.elts), len(expected_names))

                module_hints = get_type_hints(module, include_extras=True)
                self.assertIs(get_origin(module_hints["__all__"]), Final)
                self.assertEqual(
                    get_args(module_hints["__all__"]),
                    (tuple[str, ...],),
                )

    def test_exact_api_signatures_and_resolved_types(self) -> None:
        self.assertEqual(set(EXPECTED_SIGNATURES), set(PUBLIC_NAMES))
        for name, expected_signature in EXPECTED_SIGNATURES.items():
            with self.subTest(name=name):
                operation = getattr(statement_api, name)
                self.assertEqual(
                    str(inspect.signature(operation, eval_str=False)),
                    expected_signature,
                )

        collect_hints = get_type_hints(collect_static_declarations)
        self.assertEqual(collect_hints["tokens"], Iterable[Token])
        self.assertEqual(
            collect_hints["return"],
            tuple[StaticDeclaration, ...],
        )
        parse_hints = get_type_hints(parse_gml_statements)
        self.assertIs(parse_hints["request"], GMLStatementRequest)
        self.assertIs(parse_hints["return"], GMLStatementResult)
        static_id_hints = get_type_hints(static_scope_id)
        self.assertEqual(static_id_hints["body_tokens"], Iterable[Token])
        self.assertIs(static_id_hints["return"], str)

    def test_exact_frozen_model_shapes_signatures_and_types(self) -> None:
        expected_fields = {
            ControlFlowCapture: CONTROL_FLOW_CAPTURE_FIELDS,
            GMLStatementRequest: STATEMENT_REQUEST_FIELDS,
            GMLStatementResult: STATEMENT_RESULT_FIELDS,
        }
        expected_hints = {
            ControlFlowCapture: {
                "variable_name": str,
                "loop_depth": int,
                "continue_depth": int,
                "capture_return": bool,
                "capture_exit": bool,
                "capture_throw": bool,
                "capture_break": bool,
                "capture_continue": bool,
            },
            GMLStatementRequest: {
                "tokens": tuple[Token, ...],
                "local_names": frozenset[str],
                "instance_variables": MutableSet[str] | None,
                "return_depth": int,
                "enum_values": MutableMapping[str, dict[str, int]] | None,
                "enum_names": frozenset[str],
                "scope_context": ScopeContext | None,
                "inherited_event_call": str | None,
                "macro_values": MutableMapping[str, str] | None,
                "macro_priorities": MutableMapping[str, int] | None,
                "macro_configuration": str | None,
                "top_level_global_scope": bool,
                "global_names": frozenset[str],
                "asset_names": frozenset[str],
                "static_scope_prefix": str | None,
                "extension_functions": Mapping[str, GMLExtensionFunction] | None,
                "extension_function_mappings": (
                    Mapping[str, GMLExtensionFunctionMapping] | None
                ),
            },
            GMLStatementResult: {
                "lines": tuple[str, ...],
                "local_names": frozenset[str],
                "instance_variables": MutableSet[str] | None,
                "scope_context": ScopeContext,
                "enum_values": MutableMapping[str, dict[str, int]],
                "enum_names": frozenset[str],
                "macro_values": MutableMapping[str, str],
            },
        }

        for model, field_names in expected_fields.items():
            with self.subTest(model=model.__name__):
                self.assertTrue(is_dataclass(model))
                self.assertEqual(
                    tuple(field.name for field in fields(model)),
                    field_names,
                )
                self.assertEqual(get_type_hints(model), expected_hints[model])
                self.assertEqual(
                    str(inspect.signature(model, eval_str=False)),
                    EXPECTED_MODEL_SIGNATURES[model],
                )
                dataclass_parameters = getattr(model, "__dataclass_params__")
                self.assertTrue(dataclass_parameters.frozen)

        capture = ControlFlowCapture("_gml_flow", 2, 1)
        self.assertEqual(
            capture,
            ControlFlowCapture(
                variable_name="_gml_flow",
                loop_depth=2,
                continue_depth=1,
            ),
        )
        self.assertEqual(
            (
                capture.capture_return,
                capture.capture_exit,
                capture.capture_throw,
                capture.capture_break,
                capture.capture_continue,
            ),
            (False, False, False, False, False),
        )
        request = GMLStatementRequest(tokens=())
        self.assertEqual(request.local_names, frozenset())
        self.assertEqual(request.enum_names, frozenset())
        self.assertEqual(request.global_names, frozenset())
        self.assertEqual(request.asset_names, frozenset())
        with self.assertRaises(FrozenInstanceError):
            setattr(capture, "capture_return", True)
        with self.assertRaises(FrozenInstanceError):
            setattr(request, "return_depth", 1)

    def test_result_preserves_mutable_identity_and_explicit_final_state(self) -> None:
        source = (
            "globalvar shared;\n"
            "enum State { IDLE = 1, RUN }\n"
            "#macro LOCAL_SPEED 4\n"
            "var local_total = seed;\n"
            "local_total += LOCAL_SPEED;\n"
            "instance_score = State.RUN;"
        )
        instance_variables: set[str] = set()
        enum_values: dict[str, dict[str, int]] = {}
        macro_values: dict[str, str] = {}
        macro_priorities: dict[str, int] = {}
        initial_local_names = frozenset({"seed"})
        request = GMLStatementRequest(
            tokens=tuple(tokenize_gml_source(source)),
            local_names=initial_local_names,
            instance_variables=instance_variables,
            enum_values=enum_values,
            macro_values=macro_values,
            macro_priorities=macro_priorities,
            scope_context=ScopeContext(
                self_expression="owner",
                other_expression="peer",
            ),
        )

        result = parse_gml_statements(request)

        self.assertEqual(
            result.lines,
            (
                'var State = GMRuntime.gml_enum({"IDLE": 1, "RUN": 2})',
                "var local_total = seed",
                "local_total = GMRuntime.gml_add(local_total, 4)",
                "instance_score = 2",
            ),
        )
        self.assertEqual(
            result.local_names,
            frozenset({"seed", "State", "local_total"}),
        )
        self.assertEqual(initial_local_names, frozenset({"seed"}))
        self.assertIs(result.instance_variables, instance_variables)
        self.assertEqual(instance_variables, {"instance_score"})
        self.assertIs(result.enum_values, enum_values)
        self.assertEqual(enum_values, {"State": {"IDLE": 1, "RUN": 2}})
        self.assertEqual(result.enum_names, frozenset({"State"}))
        self.assertIs(result.macro_values, macro_values)
        self.assertEqual(macro_values, {"LOCAL_SPEED": "4"})
        self.assertEqual(macro_priorities, {"LOCAL_SPEED": 0})
        self.assertEqual(
            result.scope_context,
            ScopeContext(
                self_expression="owner",
                other_expression="peer",
                global_names=frozenset({"shared"}),
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            setattr(result, "lines", ())

    def test_nested_switch_propagates_child_local_and_instance_state(self) -> None:
        source = (
            "switch (state) { case 1: var local = 0; "
            "nested_instance = local; break; } after = local;"
        )
        instance_variables: set[str] = set()
        result = parse_gml_statements(
            GMLStatementRequest(
                tokens=tuple(tokenize_gml_source(source)),
                local_names=frozenset({"state"}),
                instance_variables=instance_variables,
            )
        )

        self.assertEqual(
            result.lines,
            (
                "var local = GMRuntime.gml_undefined()",
                "var _gml_switch_value_0 = state",
                "var _gml_switch_matched_1 = false",
                "var _gml_switch_has_case_2 = "
                "GMRuntime.gml_eq(_gml_switch_value_0, 1)",
                "while true:",
                "\tif not _gml_switch_matched_1 and "
                "GMRuntime.gml_eq(_gml_switch_value_0, 1):",
                "\t\t_gml_switch_matched_1 = true",
                "\tif _gml_switch_matched_1:",
                "\t\tlocal = 0",
                "\t\tnested_instance = local",
                "\t\tbreak",
                "\tbreak",
                "after = local",
            ),
        )
        self.assertEqual(result.local_names, frozenset({"state", "local"}))
        self.assertIs(result.instance_variables, instance_variables)
        self.assertEqual(instance_variables, {"nested_instance", "after"})

    def test_static_declaration_contract_skips_nested_functions_and_is_stable(self) -> None:
        source = (
            "static outer = 1; "
            "var fn = function() { static inner = 2; }; "
            "static tail;"
        )
        tokens = tuple(tokenize_gml_source(source))
        self.assertEqual(
            collect_static_declarations(tokens),
            (
                StaticDeclaration("outer", "1"),
                StaticDeclaration("tail", "undefined"),
            ),
        )
        self.assertEqual(
            static_scope_id("scr_test", "Fn", 7, tokens),
            "scr_test:Fn:7:fec7e39bd78a",
        )

        static_context = ScopeContext(
            static_scope="_gml_static_scope_test",
            static_names=frozenset({"outer"}),
            static_prefix="scr_test",
        )
        result = parse_gml_statements(
            GMLStatementRequest(
                tokens=tuple(
                    tokenize_gml_source("static outer = 1; outer += 1;")
                ),
                scope_context=static_context,
                static_scope_prefix="scr_test",
            )
        )
        self.assertEqual(
            result.lines,
            (
                "GMRuntime.gml_struct_set(_gml_static_scope_test, \"outer\", "
                "GMRuntime.gml_add(GMRuntime.gml_struct_get("
                "_gml_static_scope_test, \"outer\"), 1))",
            ),
        )
        self.assertEqual(result.scope_context, static_context)

    def test_empty_input_returns_explicit_fresh_state(self) -> None:
        request = GMLStatementRequest(tokens=tuple(tokenize_gml_source("")))
        first = parse_gml_statements(request)
        second = parse_gml_statements(request)

        self.assertEqual(first.lines, ())
        self.assertEqual(first.local_names, frozenset())
        self.assertIsNone(first.instance_variables)
        self.assertEqual(first.scope_context, ScopeContext())
        self.assertEqual(first.enum_values, {})
        self.assertEqual(first.enum_names, frozenset())
        self.assertEqual(first.macro_values, {})
        self.assertIsNot(first.enum_values, second.enum_values)
        self.assertIsNot(first.macro_values, second.macro_values)

    def test_parser_error_preserves_exact_text_line_and_column(self) -> None:
        source = "do {\n score += 1;\n} x score > 2;"
        with self.assertRaises(GMLTranspileError) as raised:
            parse_gml_statements(
                GMLStatementRequest(
                    tokens=tuple(tokenize_gml_source(source)),
                )
            )

        error = raised.exception
        self.assertEqual(error.message, "Expected 'until', got: x")
        self.assertEqual((error.line, error.column), (3, 3))
        self.assertEqual(
            str(error),
            "Expected 'until', got: x at line 3, column 3",
        )

    def test_statement_contract_remains_package_internal(self) -> None:
        self.assertEqual(len(gml_transpiler.__all__), 74)
        self.assertEqual(
            sum(not name.startswith("_") for name in gml_transpiler.__all__),
            44,
        )
        self.assertEqual(
            sum(name.startswith("_") for name in gml_transpiler.__all__),
            30,
        )
        package_internal_names = frozenset((*PUBLIC_NAMES, *MODEL_NAMES))
        self.assertTrue(package_internal_names.isdisjoint(gml_transpiler.__all__))
        self.assertTrue(package_internal_names.isdisjoint(vars(gml_transpiler)))

    def test_expression_parser_keeps_statement_api_import_cycle_safe(self) -> None:
        parser_path = PARTS_PATH / "expression_parser.py"
        tree = ast.parse(
            parser_path.read_text(encoding="utf-8"),
            filename=str(parser_path),
        )
        top_level_statement_api_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "statement_api"
        ]
        self.assertEqual(top_level_statement_api_imports, [])

        parser_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "_ExpressionParser"
        )
        function_literal_parser = next(
            node
            for node in parser_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_parse_function_literal"
        )
        local_imports = [
            node
            for node in ast.walk(function_literal_parser)
            if isinstance(node, ast.ImportFrom) and node.module == "statement_api"
        ]
        self.assertEqual(len(local_imports), 1)
        local_import = local_imports[0]
        self.assertEqual(local_import.level, 1)
        self.assertEqual(
            tuple((alias.name, alias.asname) for alias in local_import.names),
            (
                ("collect_static_declarations", None),
                ("parse_gml_statements", None),
                ("static_scope_id", "build_static_scope_id"),
            ),
        )
        statement_parser_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "statement_parser"
        ]
        self.assertEqual(statement_parser_imports, [])

    def test_fresh_process_import_orders_preserve_function_literal_parsing(self) -> None:
        module_prefix = "src.conversion.gml_transpiler_parts"
        expected = (
            "GMRuntime.gml_receiver_method(self, "
            "func(_gml_method_self = null, _gml_method_other = null): return 1)"
        )
        import_orders = (
            ("statement_api", "expression_api"),
            ("expression_api", "statement_api"),
        )
        for import_order in import_orders:
            with self.subTest(import_order=import_order):
                script = f"""
import importlib

for module_name in {import_order!r}:
    importlib.import_module({module_prefix!r} + "." + module_name)

from {module_prefix}.expression_api import transpile_gml_expression

actual = transpile_gml_expression("function() {{ return 1; }}")
expected = {expected!r}
if actual != expected:
    raise AssertionError((actual, expected))
print("ok")
"""
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=PROJECT_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stdout + completed.stderr,
                )
                self.assertEqual(completed.stdout, "ok\n")
                self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
