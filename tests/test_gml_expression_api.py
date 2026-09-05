from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path
from typing import Iterable, get_args, get_type_hints

from src.conversion.gml_transpiler import (
    transpile_gml_condition as facade_transpile_gml_condition,
    transpile_gml_expression as facade_transpile_gml_expression,
)
from src.conversion.gml_transpiler_parts.expression_api import (
    emit_constructor_inheritance_line,
    emit_gml_expression,
    emit_gml_truthy_expression,
    emit_instance_keyword_argument,
    emit_static_initialization_lines,
    evaluate_enum_value_tokens,
    name_resolves_to_global,
    parse_gml_expression,
    reject_constant_assignment_target_name,
    reject_constant_declaration_name,
    reject_enum_assignment_target,
    reject_enum_mutation_expression,
    reject_readonly_builtin_assignment_target,
    transpile_gml_condition,
    transpile_gml_expression,
    uses_direct_builtin_instance_members,
    uses_direct_member_access,
)
from src.conversion.gml_transpiler_parts.expression_models import (
    Binary,
    EnumMember,
    Expression,
    GMLExpression,
    GMLExpressionEmission,
    Member,
    Name,
    NumberLiteral,
)
from src.conversion.gml_transpiler_parts.lexical_api import tokenize_gml_expression
from src.conversion.gml_transpiler_parts.shared_models import GMLTranspileError, ScopeContext, StaticDeclaration, Token
from tests.gml_facade_contract_support import static_all_exports

PUBLIC_NAMES = (
    "emit_constructor_inheritance_line",
    "emit_gml_expression",
    "emit_gml_truthy_expression",
    "emit_instance_keyword_argument",
    "emit_static_initialization_lines",
    "evaluate_enum_value_tokens",
    "name_resolves_to_global",
    "parse_gml_expression",
    "reject_constant_assignment_target_name",
    "reject_constant_declaration_name",
    "reject_enum_assignment_target",
    "reject_enum_mutation_expression",
    "reject_readonly_builtin_assignment_target",
    "transpile_gml_condition",
    "transpile_gml_expression",
    "uses_direct_builtin_instance_members",
    "uses_direct_member_access",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPRESSION_API_PATH = (
    PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts" / "expression_api.py"
)
FACADE_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler.py"
EXPRESSION_API_FUNCTIONS = {
    "emit_constructor_inheritance_line": emit_constructor_inheritance_line,
    "emit_gml_expression": emit_gml_expression,
    "emit_gml_truthy_expression": emit_gml_truthy_expression,
    "emit_instance_keyword_argument": emit_instance_keyword_argument,
    "emit_static_initialization_lines": emit_static_initialization_lines,
    "evaluate_enum_value_tokens": evaluate_enum_value_tokens,
    "name_resolves_to_global": name_resolves_to_global,
    "parse_gml_expression": parse_gml_expression,
    "reject_constant_assignment_target_name": reject_constant_assignment_target_name,
    "reject_constant_declaration_name": reject_constant_declaration_name,
    "reject_enum_assignment_target": reject_enum_assignment_target,
    "reject_enum_mutation_expression": reject_enum_mutation_expression,
    "reject_readonly_builtin_assignment_target": reject_readonly_builtin_assignment_target,
    "transpile_gml_condition": transpile_gml_condition,
    "transpile_gml_expression": transpile_gml_expression,
    "uses_direct_builtin_instance_members": uses_direct_builtin_instance_members,
    "uses_direct_member_access": uses_direct_member_access,
}

EXPECTED_SIGNATURES = {
    "emit_constructor_inheritance_line": (
        "(parent_constructor: 'GMLExpression', local_names: 'Iterable[str]', "
        "scope_context: 'ScopeContext', constructor_scope_context: 'ScopeContext') -> 'str'"
    ),
    "emit_gml_expression": (
        "(expr: 'GMLExpression', local_names: 'Iterable[str] | None' = None, "
        "bind_function_literals: 'bool' = True, scope_context: 'ScopeContext | None' = None) "
        "-> 'GMLExpressionEmission'"
    ),
    "emit_gml_truthy_expression": (
        "(expr: 'GMLExpression', local_names: 'Iterable[str]', "
        "scope_context: 'ScopeContext | None' = None) -> 'str'"
    ),
    "emit_instance_keyword_argument": (
        "(expr: 'GMLExpression', local_names: 'Iterable[str]', "
        "scope_context: 'ScopeContext | None' = None) -> 'str'"
    ),
    "emit_static_initialization_lines": (
        "(static_scope_name: 'str | None', static_scope_id: 'str | None', "
        "declarations: 'Iterable[StaticDeclaration]', local_names: 'Iterable[str]', "
        "scope_context: 'ScopeContext', enum_values: 'MutableMapping[str, dict[str, int]]', "
        "enum_names: 'Iterable[str]', macro_values: 'Mapping[str, str]') -> 'list[str]'"
    ),
    "evaluate_enum_value_tokens": (
        "(tokens: 'Iterable[Token]', enum_values: 'Mapping[str, Mapping[str, int]]', "
        "current_enum_values: 'Mapping[str, int]', macro_values: 'Mapping[str, str] | None' = None) "
        "-> 'int'"
    ),
    "name_resolves_to_global": (
        "(name: 'str', local_names: 'Iterable[str]', scope_context: 'ScopeContext') -> 'bool'"
    ),
    "parse_gml_expression": (
        "(source: 'str', enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'Iterable[str] | None' = None, macro_values: 'Mapping[str, str] | None' = None, "
        "macro_expansion_stack: 'frozenset[str] | None' = None, "
        "scope_context: 'ScopeContext | None' = None) -> 'GMLExpression'"
    ),
    "reject_constant_assignment_target_name": (
        "(target_source: 'str', macro_names: 'Iterable[str]') -> 'None'"
    ),
    "reject_constant_declaration_name": (
        "(name: 'str', macro_names: 'Iterable[str]') -> 'None'"
    ),
    "reject_enum_assignment_target": (
        "(target_expr: 'GMLExpression', enum_names: 'Iterable[str] | None') -> 'None'"
    ),
    "reject_enum_mutation_expression": (
        "(expr: 'GMLExpression', enum_names: 'Iterable[str] | None') -> 'None'"
    ),
    "reject_readonly_builtin_assignment_target": (
        "(target_expr: 'GMLExpression', local_names: 'Iterable[str]') -> 'None'"
    ),
    "transpile_gml_condition": (
        "(source: 'str', local_names: 'Iterable[str] | None' = None, "
        "enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'Iterable[str] | None' = None, scope_context: 'ScopeContext | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None, global_names: 'Iterable[str] | None' = None, "
        "asset_names: 'Iterable[str] | None' = None, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None) -> 'str'"
    ),
    "transpile_gml_expression": (
        "(source: 'str', local_names: 'Iterable[str] | None' = None, "
        "enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'Iterable[str] | None' = None, scope_context: 'ScopeContext | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None, global_names: 'Iterable[str] | None' = None, "
        "asset_names: 'Iterable[str] | None' = None, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None) -> 'str'"
    ),
    "uses_direct_builtin_instance_members": "(scope_context: 'ScopeContext') -> 'bool'",
    "uses_direct_member_access": (
        "(expr: 'Member', scope_context: 'ScopeContext | None' = None) -> 'bool'"
    ),
}

EXPRESSION_VARIANT_NAMES = (
    "Name",
    "NameOf",
    "Literal",
    "StringLiteral",
    "TemplateStringLiteral",
    "NumberLiteral",
    "EnumMember",
    "Unary",
    "Binary",
    "Ternary",
    "Call",
    "ArrayLiteral",
    "FunctionLiteral",
    "NewCall",
    "StructLiteral",
    "Index",
    "StructAccess",
    "DSMapAccess",
    "DSListAccess",
    "DSGridAccess",
    "ArrayRefAccess",
    "Member",
    "Grouped",
)


class GMLExpressionAPITests(unittest.TestCase):
    def test_exact_static_alphabetized_public_surface(self) -> None:
        public_exports = static_all_exports(EXPRESSION_API_PATH.read_text(encoding="utf-8"))
        self.assertEqual(public_exports, PUBLIC_NAMES)
        self.assertEqual(len(public_exports), 17)
        self.assertEqual(tuple(sorted(public_exports)), PUBLIC_NAMES)
        self.assertTrue(all(not name.startswith("_") for name in public_exports))

        module_path = EXPRESSION_API_PATH
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        declarations = [
            node
            for node in tree.body
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "__all__"
            )
        ]
        self.assertEqual(len(declarations), 1)
        declaration = declarations[0]
        self.assertIsInstance(declaration, ast.AnnAssign)
        assert isinstance(declaration, ast.AnnAssign)
        value = declaration.value
        self.assertIsInstance(value, (ast.List, ast.Tuple))
        assert isinstance(value, (ast.List, ast.Tuple))
        self.assertEqual(
            tuple(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ),
            PUBLIC_NAMES,
        )
        self.assertEqual(len(value.elts), len(PUBLIC_NAMES))

        annotation = declaration.annotation
        self.assertIsInstance(annotation, ast.Subscript)
        assert isinstance(annotation, ast.Subscript)
        self.assertEqual(ast.unparse(annotation), "Final[tuple[str, ...]]")

    def test_exact_public_signatures_and_resolved_model_types(self) -> None:
        self.assertEqual(set(EXPECTED_SIGNATURES), set(PUBLIC_NAMES))
        for name, expected_signature in EXPECTED_SIGNATURES.items():
            with self.subTest(name=name):
                operation = EXPRESSION_API_FUNCTIONS[name]
                self.assertEqual(
                    str(inspect.signature(operation, eval_str=False)),
                    expected_signature,
                )

        expression_type = GMLExpression
        expression_parameters = {
            "emit_constructor_inheritance_line": "parent_constructor",
            "emit_gml_expression": "expr",
            "emit_gml_truthy_expression": "expr",
            "emit_instance_keyword_argument": "expr",
            "reject_enum_assignment_target": "target_expr",
            "reject_enum_mutation_expression": "expr",
            "reject_readonly_builtin_assignment_target": "target_expr",
        }
        for name, parameter in expression_parameters.items():
            with self.subTest(name=name, parameter=parameter):
                self.assertIs(
                    get_type_hints(EXPRESSION_API_FUNCTIONS[name])[parameter],
                    expression_type,
                )

        self.assertIs(get_type_hints(parse_gml_expression)["return"], expression_type)
        self.assertIs(get_type_hints(emit_gml_expression)["return"], GMLExpressionEmission)
        self.assertEqual(get_type_hints(evaluate_enum_value_tokens)["tokens"], Iterable[Token])
        self.assertEqual(
            get_type_hints(emit_static_initialization_lines)["declarations"],
            Iterable[StaticDeclaration],
        )
        self.assertIs(get_type_hints(uses_direct_member_access)["expr"], Member)

        expected_returns = {
            "emit_constructor_inheritance_line": str,
            "emit_gml_expression": GMLExpressionEmission,
            "emit_gml_truthy_expression": str,
            "emit_instance_keyword_argument": str,
            "emit_static_initialization_lines": list[str],
            "evaluate_enum_value_tokens": int,
            "name_resolves_to_global": bool,
            "parse_gml_expression": expression_type,
            "reject_constant_assignment_target_name": type(None),
            "reject_constant_declaration_name": type(None),
            "reject_enum_assignment_target": type(None),
            "reject_enum_mutation_expression": type(None),
            "reject_readonly_builtin_assignment_target": type(None),
            "transpile_gml_condition": str,
            "transpile_gml_expression": str,
            "uses_direct_builtin_instance_members": bool,
            "uses_direct_member_access": bool,
        }
        for name, expected_return in expected_returns.items():
            with self.subTest(name=name):
                self.assertEqual(
                    get_type_hints(EXPRESSION_API_FUNCTIONS[name])["return"],
                    expected_return,
                )

    def test_canonical_expression_alias_and_frozen_emission_model(self) -> None:
        expression_type = Expression
        gml_expression_type = GMLExpression
        self.assertIs(gml_expression_type, expression_type)
        self.assertEqual(
            tuple(member.__name__ for member in get_args(gml_expression_type)),
            EXPRESSION_VARIANT_NAMES,
        )

        self.assertTrue(is_dataclass(GMLExpressionEmission))
        self.assertEqual(
            tuple(field.name for field in fields(GMLExpressionEmission)),
            ("text", "precedence"),
        )
        self.assertEqual(
            get_type_hints(GMLExpressionEmission),
            {"text": str, "precedence": int},
        )
        self.assertEqual(
            str(inspect.signature(GMLExpressionEmission, eval_str=False)),
            "(text: 'str', precedence: 'int') -> None",
        )
        dataclass_parameters = getattr(GMLExpressionEmission, "__dataclass_params__")
        self.assertTrue(dataclass_parameters.frozen)
        self.assertFalse(hasattr(GMLExpressionEmission("value", 130), "__slots__"))

        emission = GMLExpressionEmission("value", 130)
        self.assertEqual(emission, GMLExpressionEmission(text="value", precedence=130))
        self.assertNotIsInstance(emission, tuple)
        with self.assertRaises(FrozenInstanceError):
            setattr(emission, "text", "changed")

    def test_parse_and_emit_preserve_ast_context_text_and_precedence(self) -> None:
        enum_values = {"State": {"RUN": 4}}
        expression = parse_gml_expression(
            "State.RUN + SPEED",
            enum_values=enum_values,
            macro_values={"SPEED": "2"},
        )
        self.assertIsInstance(expression, Binary)
        assert isinstance(expression, Binary)
        self.assertIsInstance(expression.left, EnumMember)
        self.assertEqual(expression.left, EnumMember("State", "RUN", 4))
        self.assertIsInstance(expression.right, NumberLiteral)
        self.assertEqual(enum_values, {"State": {"RUN": 4}})
        self.assertEqual(
            emit_gml_expression(expression),
            GMLExpressionEmission("GMRuntime.gml_add(4, 2)", 120),
        )

        precedence_cases = {
            "value": ("value", 130),
            "-value": ("-value", 110),
            "a * b": ("GMRuntime.gml_mul(a, b)", 120),
            "a and b": ("GMRuntime.gml_bool(a) and GMRuntime.gml_bool(b)", 30),
            "a or b": ("GMRuntime.gml_bool(a) or GMRuntime.gml_bool(b)", 20),
            "a ?? b": ("a if not GMRuntime.gml_is_nullish(a) else b", 5),
            "a ? b : c": ("b if GMRuntime.gml_bool(a) else c", 5),
        }
        for source, expected in precedence_cases.items():
            with self.subTest(source=source):
                actual = emit_gml_expression(parse_gml_expression(source))
                self.assertEqual((actual.text, actual.precedence), expected)

        function = parse_gml_expression("function() { return self; }")
        self.assertEqual(
            emit_gml_expression(function, bind_function_literals=False),
            GMLExpressionEmission(
                "func(_gml_method_self = null, _gml_method_other = null): "
                "return _gml_method_self",
                130,
            ),
        )

        scope_context = ScopeContext(
            self_expression="owner",
            other_expression="peer",
            instance_target="owner",
            global_names=frozenset({"global_score"}),
            asset_names=frozenset({"obj_enemy"}),
            direct_instance_names=frozenset({"direct"}),
            dynamic_instance_names=frozenset({"dynamic"}),
        )
        context_cases = {
            "self": "owner",
            "other": "peer",
            "global_score": 'GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "global_score")',
            "obj_enemy": 'GMRuntime.gml_asset_get_index("obj_enemy")',
            "direct": "direct",
            "dynamic": 'GMRuntime.gml_variable_instance_get(owner, "dynamic")',
        }
        for source, expected in context_cases.items():
            with self.subTest(source=source):
                emission = emit_gml_expression(
                    parse_gml_expression(source, scope_context=scope_context),
                    scope_context=scope_context,
                )
                self.assertEqual(emission.text, expected)

        self.assertTrue(name_resolves_to_global("global_score", (), scope_context))
        self.assertFalse(name_resolves_to_global("global_score", {"global_score"}, scope_context))
        self.assertFalse(uses_direct_builtin_instance_members(scope_context))
        self.assertTrue(uses_direct_builtin_instance_members(ScopeContext()))

        member = parse_gml_expression("self.x")
        self.assertIsInstance(member, Member)
        assert isinstance(member, Member)
        self.assertFalse(uses_direct_member_access(member, scope_context))
        self.assertTrue(uses_direct_member_access(member, ScopeContext()))
        indirect_member = Member(Name("value"), "x")
        self.assertFalse(uses_direct_member_access(indirect_member, scope_context))

    def test_truthy_and_instance_keyword_emission_preserve_context(self) -> None:
        self.assertEqual(
            emit_gml_truthy_expression(parse_gml_expression("score"), {"score"}),
            "GMRuntime.gml_bool(score)",
        )
        self.assertEqual(
            emit_gml_truthy_expression(parse_gml_expression("true"), ()),
            "true",
        )

        scope_context = ScopeContext(
            self_expression="owner",
            other_expression="peer",
            asset_names=frozenset({"obj_enemy"}),
        )
        expected_by_source = {
            "self": "owner",
            "other": "peer",
            "all": "GMRuntime.gml_instance_all()",
            "noone": "GMRuntime.gml_instance_noone()",
            "obj_enemy": 'GMRuntime.gml_asset_get_index("obj_enemy")',
        }
        for source, expected in expected_by_source.items():
            with self.subTest(source=source):
                self.assertEqual(
                    emit_instance_keyword_argument(
                        parse_gml_expression(source, scope_context=scope_context),
                        (),
                        scope_context,
                    ),
                    expected,
                )

    def test_enum_and_constant_semantic_operations_preserve_results_and_errors(self) -> None:
        self.assertEqual(
            evaluate_enum_value_tokens(
                tokenize_gml_expression("State.RUN + BASE"),
                {"State": {"RUN": 4}},
                {"BASE": 2},
            ),
            6,
        )

        enum_member = parse_gml_expression(
            "State.RUN",
            enum_values={"State": {"RUN": 4}},
        )
        with self.assertRaisesRegex(GMLTranspileError, "^Cannot assign to enum member$"):
            reject_enum_assignment_target(enum_member, {"State"})

        enum_mutation = parse_gml_expression(
            'struct_set(State, "RUN", 2)',
            enum_names={"State"},
        )
        with self.assertRaisesRegex(GMLTranspileError, "^Cannot mutate enum member$"):
            reject_enum_mutation_expression(enum_mutation, {"State"})

        readonly_name = parse_gml_expression("room_width")
        with self.assertRaisesRegex(
            GMLTranspileError,
            "^Cannot assign to read-only built-in variable room_width$",
        ):
            reject_readonly_builtin_assignment_target(readonly_name, ())
        reject_readonly_builtin_assignment_target(readonly_name, {"room_width"})

        rejection_cases = (
            (
                reject_constant_assignment_target_name,
                ("pi", ()),
                "Cannot assign to built-in constant pi",
            ),
            (
                reject_constant_assignment_target_name,
                ("MAX", {"MAX"}),
                "Cannot assign to macro constant MAX",
            ),
            (
                reject_constant_declaration_name,
                ("undefined", ()),
                "Cannot redeclare built-in constant undefined",
            ),
            (
                reject_constant_declaration_name,
                ("MAX", {"MAX"}),
                "Cannot redeclare macro constant MAX",
            ),
        )
        for operation, args, message in rejection_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(GMLTranspileError, f"^{message}$"):
                    operation(*args)

    def test_constructor_and_static_emission_preserve_exact_lines(self) -> None:
        outer_scope = ScopeContext(
            self_expression="owner",
            other_expression="peer",
            instance_target="owner",
        )
        constructor_scope = ScopeContext(
            self_expression="_gml_constructor_self",
            other_expression="_gml_constructor_other",
            instance_target="_gml_constructor_self",
        )
        parent_constructor = parse_gml_expression(
            "Parent(x)",
            scope_context=outer_scope,
        )
        self.assertEqual(
            emit_constructor_inheritance_line(
                parent_constructor,
                {"x"},
                constructor_scope,
                outer_scope,
            ),
            "GMRuntime.gml_constructor_inherit(_gml_constructor_self, "
            'GMRuntime.gml_variable_instance_get(owner, "Parent"), [x], '
            "_gml_constructor_self, _gml_constructor_other)",
        )

        static_scope = ScopeContext(
            static_scope="_gml_static_scope_a",
            static_names=frozenset({"memo"}),
        )
        self.assertEqual(
            emit_static_initialization_lines(
                "_gml_static_scope_a",
                "gml_static:Fn:4:abc",
                (StaticDeclaration("memo", "score + 1"),),
                {"score"},
                static_scope,
                {},
                (),
                {},
            ),
            [
                'var _gml_static_scope_a = GMRuntime.gml_static_scope("gml_static:Fn:4:abc")',
                "GMRuntime.gml_static_initialize(_gml_static_scope_a, "
                '[["memo", func(): return GMRuntime.gml_add(score, 1)]])',
            ],
        )
        self.assertEqual(
            emit_static_initialization_lines(
                None,
                None,
                (),
                (),
                ScopeContext(),
                {},
                (),
                {},
            ),
            [],
        )

    def test_parser_error_location_and_top_facade_contract_remain_exact(self) -> None:
        with self.assertRaises(GMLTranspileError) as raised:
            parse_gml_expression("value\n+ )")
        error = raised.exception
        self.assertEqual(error.message, "Expected expression, got: )")
        self.assertEqual((error.line, error.column), (2, 3))
        self.assertEqual(str(error), "Expected expression, got: ) at line 2, column 3")

        facade_exports = static_all_exports(FACADE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(facade_exports), 44)
        self.assertEqual(sum(not name.startswith("_") for name in facade_exports), 44)
        self.assertEqual(sum(name.startswith("_") for name in facade_exports), 0)
        package_internal_only: set[str] = {str(name) for name in PUBLIC_NAMES}
        package_internal_only.difference_update(
            {"transpile_gml_condition", "transpile_gml_expression"}
        )
        package_internal_only.update({"GMLExpression", "GMLExpressionEmission"})
        self.assertTrue(package_internal_only.isdisjoint(facade_exports))

        facade_scope_annotation = "scope_context: '_ScopeContext | None' = None"
        self.assertIn(
            facade_scope_annotation,
            str(inspect.signature(facade_transpile_gml_expression, eval_str=False)),
        )
        self.assertIn(
            facade_scope_annotation,
            str(inspect.signature(facade_transpile_gml_condition, eval_str=False)),
        )
        self.assertEqual(
            transpile_gml_expression("score + 1", local_names={"score"}),
            facade_transpile_gml_expression("score + 1", local_names={"score"}),
        )
        self.assertEqual(
            transpile_gml_condition("score", local_names={"score"}),
            facade_transpile_gml_condition("score", local_names={"score"}),
        )


if __name__ == "__main__":
    unittest.main()
