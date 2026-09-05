from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, MutableSet, NamedTuple, get_type_hints
from unittest.mock import patch

from src.conversion import gml_transpiler as facade
from src.conversion.gml_transpiler_parts import statement_api, statement_parser, statements
from src.conversion.gml_transpiler_parts.lexical_api import tokenize_gml_source
from src.conversion.gml_transpiler_parts.shared_models import ScopeContext
from src.conversion.gml_transpiler_parts.statement_models import (
    ControlFlowCapture,
    GMLStatementRequest,
    GMLStatementResult,
    StatementLoweringContext,
)

FIELD_NAMES = (
    "local_names",
    "declared_local_names",
    "instance_variables",
    "loop_depth",
    "continue_depth",
    "return_depth",
    "finally_depth",
    "enum_values",
    "enum_names",
    "scope_context",
    "inherited_event_call",
    "macro_values",
    "generated_counter",
    "control_flow_capture",
)
FIELD_DEFAULTS = (None, None, None, 0, 0, 0, 0, None, None, None, None, None, None, None)
FIELD_TYPES = (
    MutableSet[str] | None,
    MutableSet[str] | None,
    MutableSet[str] | None,
    int,
    int,
    int,
    int,
    MutableMapping[str, dict[str, int]] | None,
    Iterable[str] | None,
    ScopeContext | None,
    str | None,
    Mapping[str, str] | None,
    list[int] | None,
    ControlFlowCapture | None,
)
LOWER_SIGNATURE = inspect.signature(statements.transpile_statement)


def _lowering_state(args: tuple[object, ...], kwargs: dict[str, object]) -> dict[str, object]:
    bound = LOWER_SIGNATURE.bind(*args, **kwargs)
    bound.apply_defaults()
    context = bound.arguments["context"]
    assert isinstance(context, StatementLoweringContext)
    return {
        "statement": bound.arguments["statement"],
        "context": context,
        **{field.name: getattr(context, field.name) for field in fields(context)},
    }


class _ObservedMapping(dict[str, str]):
    def __init__(self, events: list[str], truthy: bool) -> None:
        super().__init__()
        self.events = events
        self.truthy = truthy

    def __bool__(self) -> bool:
        self.events.append("macro")
        return self.truthy


class _ObservedSet(set[str]):
    def __init__(self, name: str, events: list[tuple[str, str]]) -> None:
        super().__init__()
        self.name = name
        self.events = events

    def add(self, element: str) -> None:
        self.events.append((self.name, element))
        super().add(element)


class _ParserCall(NamedTuple):
    statement: str
    state: dict[str, object]
    context: StatementLoweringContext


def _parser_calls(source: str) -> list[_ParserCall]:
    calls: list[_ParserCall] = []

    def lower(*args: object, **kwargs: object) -> list[str]:
        state = _lowering_state(args, kwargs)
        statement = state["statement"]
        assert isinstance(statement, str)
        context = state["context"]
        assert isinstance(context, StatementLoweringContext)
        calls.append(_ParserCall(statement.replace(" ", ""), state, context))
        return ["LOWERED"]

    with patch.object(statement_parser, "transpile_statement", side_effect=lower):
        statement_api.parse_gml_statements(GMLStatementRequest(tuple(tokenize_gml_source(source))))
    return calls


class TestStatementLoweringContext(unittest.TestCase):
    def test_empty_statement_precedes_context_field_normalization(self) -> None:
        events: list[str] = []
        macro = _ObservedMapping(events, False)
        counter: list[int] = []
        with patch.object(statements, "normalize_scope_context", side_effect=AssertionError("scope was read")):
            first = statements.transpile_statement(
                "", StatementLoweringContext(macro_values=macro, generated_counter=counter)
            )
            second = statements.transpile_statement(
                "", StatementLoweringContext(macro_values=macro, generated_counter=counter)
            )
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertIsNot(first, second)
        self.assertEqual(events, [])
        self.assertEqual(counter, [])
        with patch.object(
            statements, "StatementLoweringContext", side_effect=AssertionError("context was constructed")
        ):
            self.assertEqual(statements.transpile_statement(""), [])
        self.assertEqual(statements.transpile_statement("var default"), ["var default = GMRuntime.gml_undefined()"])

    def test_none_defaults_and_falsey_mapping_preserve_existing_rules(self) -> None:
        observed: list[dict[str, object]] = []
        events: list[str] = []
        normalize = statements.normalize_scope_context

        def scope(value: ScopeContext | None) -> ScopeContext:
            events.append("scope")
            return normalize(value)

        def declaration(*args: object, **kwargs: object) -> list[str]:
            names = (
                "declaration",
                "local_names",
                "declared_local_names",
                "instance_variables",
                "enum_values",
                "enum_names",
            )
            observed.append({**dict(zip(names, args, strict=True)), **kwargs})
            return []

        local: set[str] = set()
        declared: set[str] = set()
        counter: list[int] = []
        supplied_scope = ScopeContext(self_expression="receiver")
        enum_names = iter(["Direction"])
        falsey = _ObservedMapping(events, False)
        truthy = _ObservedMapping(events, True)
        default_context = StatementLoweringContext(macro_values=falsey)
        with (
            patch.object(statements, "normalize_scope_context", side_effect=scope),
            patch.object(statements, "_transpile_var_statement", side_effect=declaration),
        ):
            statements.transpile_statement("var first", default_context)
            statements.transpile_statement("var second", default_context)
            statements.transpile_statement(
                "var third",
                StatementLoweringContext(
                    local_names=local,
                    declared_local_names=declared,
                    enum_names=enum_names,
                    scope_context=supplied_scope,
                    macro_values=truthy,
                    generated_counter=counter,
                ),
            )
        self.assertIsNone(default_context.local_names)
        self.assertIsNone(default_context.declared_local_names)
        self.assertIsNone(default_context.scope_context)
        self.assertIsNone(default_context.generated_counter)
        self.assertIs(default_context.macro_values, falsey)
        self.assertEqual(events, ["scope", "macro"] * 3)
        first, second, supplied = observed
        for record in (first, second):
            self._assert_default_var_channels(record, falsey)
        for name in ("local_names", "declared_local_names", "generated_counter", "macro_values"):
            self.assertIsNot(first[name], second[name])
        for name, value in (
            ("local_names", local),
            ("declared_local_names", declared),
            ("enum_names", enum_names),
            ("scope_context", supplied_scope),
            ("macro_values", truthy),
            ("generated_counter", counter),
        ):
            self.assertIs(supplied[name], value)
        self.assertEqual(next(enum_names), "Direction")

    def _assert_default_var_channels(self, record: dict[str, object], falsey: Mapping[str, str]) -> None:
        self.assertEqual(record["local_names"], set())
        self.assertEqual(record["declared_local_names"], set())
        self.assertIsNot(record["local_names"], record["declared_local_names"])
        self.assertIsNone(record["instance_variables"])
        self.assertIsNone(record["enum_values"])
        self.assertIsNone(record["enum_names"])
        self.assertIs(record["scope_context"], statements.normalize_scope_context(None))
        self.assertEqual(record["macro_values"], {})
        self.assertIsNot(record["macro_values"], falsey)
        self.assertEqual(record["generated_counter"], [0])

    def test_mutable_channels_and_generated_counter_keep_identity(self) -> None:
        events: list[tuple[str, str]] = []
        local = _ObservedSet("local", events)
        declared = _ObservedSet("declared", events)
        instances = _ObservedSet("instance", events)
        counter = [7]
        self.assertEqual(
            statements.transpile_statement(
                "var score=1",
                StatementLoweringContext(
                    local_names=local,
                    declared_local_names=declared,
                    instance_variables=instances,
                    generated_counter=counter,
                ),
            ),
            ["var score = 1"],
        )
        self.assertEqual(events, [("local", "score"), ("declared", "score")])
        events.clear()
        self.assertEqual(
            statements.transpile_statement(
                "target=score++",
                StatementLoweringContext(
                    local_names=local,
                    declared_local_names=declared,
                    instance_variables=instances,
                    generated_counter=counter,
                ),
            ),
            [
                "var _gml_increment_value_7 = score",
                "score = GMRuntime.gml_add(score, 1)",
                "target = _gml_increment_value_7",
            ],
        )
        self.assertEqual(events, [("local", "_gml_increment_value_7"), ("instance", "target")])
        self.assertEqual(counter, [8])
        self.assertEqual(local, {"score", "_gml_increment_value_7"})
        self.assertEqual(declared, {"score"})
        self.assertEqual(instances, {"target"})
        empty: list[int] = []
        self.assertEqual(
            statements.transpile_statement("var plain=1", StatementLoweringContext(generated_counter=empty)),
            ["var plain = 1"],
        )
        self.assertEqual(
            statements.transpile_statement("answer=++i", StatementLoweringContext(generated_counter=empty)),
            ["i = GMRuntime.gml_add(i, 1)", "answer = i"],
        )
        with self.assertRaisesRegex(IndexError, "list index out of range"):
            statements.transpile_statement("answer=i++", StatementLoweringContext(generated_counter=empty))
        self.assertEqual(empty, [])

    def test_parser_reads_fresh_context_in_original_argument_order(self) -> None:
        calls = _parser_calls("first=1; for (a=1; b; c=2) { body=3; } after=4; do tail=5; until (done);")
        self.assertEqual(
            tuple((call.statement, call.state["loop_depth"], call.state["continue_depth"]) for call in calls),
            (("first=1", 0, 0), ("a=1", 0, 0), ("c=2", 0, 0), ("body=3", 1, 1), ("after=4", 0, 0), ("tail=5;", 1, 1)),
        )
        for call in calls:
            for name in ("local_names", "declared_local_names", "enum_values", "macro_values", "generated_counter"):
                self.assertIs(call.state[name], calls[0].state[name])
        self.assertEqual(len({id(call.context) for call in calls}), len(calls))
        self._assert_factory_field_order()
        later = _parser_calls("later=1;")
        for name in ("local_names", "declared_local_names", "enum_values", "macro_values", "generated_counter"):
            self.assertIsNot(calls[0].state[name], later[0].state[name])

    def test_parser_capture_is_present_only_at_existing_call_site(self) -> None:
        calls = _parser_calls("try { exit; for (a=1; b; c=2) {} do value=1; until(done); } finally { cleanup(); }")
        selected = {call.statement: call for call in calls}
        capture = selected["exit"].state["control_flow_capture"]
        self.assertIsInstance(capture, ControlFlowCapture)
        for statement in ("a=1", "c=2", "value=1;"):
            self.assertIsNone(selected[statement].state["control_flow_capture"])
        for source in ("", "for (;;) {}", "do until(done);"):
            with self.subTest(source=source):
                self.assertEqual(_parser_calls(source), [])

    def test_recursive_increment_retains_normalized_state_and_omits_capture(self) -> None:
        lower = statements.transpile_statement
        instances: set[str] = set()
        enum_values = {"Direction": {"LEFT": 2}}
        enum_names = iter(["Direction"])
        capture = ControlFlowCapture("flow", 3, 4, capture_return=True)
        observed: list[dict[str, object]] = []

        def recursive(*args: object, **kwargs: object) -> list[str]:
            state = _lowering_state(args, kwargs)
            observed.append(state)
            self.assertEqual(state["generated_counter"], [1])
            self.assertEqual(state["local_names"], {"_gml_increment_value_0"})
            return ["INCREMENT"]

        with patch.object(statements, "transpile_statement", side_effect=recursive):
            lines = lower(
                "answer=i++",
                StatementLoweringContext(
                    instance_variables=instances,
                    loop_depth=3,
                    continue_depth=4,
                    return_depth=5,
                    finally_depth=6,
                    enum_values=enum_values,
                    enum_names=enum_names,
                    inherited_event_call="super.event()",
                    control_flow_capture=capture,
                ),
            )
        self.assertEqual(lines, ["var _gml_increment_value_0 = i", "INCREMENT", "answer = _gml_increment_value_0"])
        self.assertEqual(len(observed), 1)
        state = observed[0]
        self.assertEqual(state["statement"], "i++")
        self.assertIs(state["instance_variables"], instances)
        self.assertIs(state["enum_values"], enum_values)
        self.assertIs(state["enum_names"], enum_names)
        self.assertEqual(tuple(state[name] for name in FIELD_NAMES[3:7]), (3, 4, 5, 6))
        self.assertEqual(state["inherited_event_call"], "super.event()")
        self.assertEqual(state["declared_local_names"], set())
        self.assertIsNot(state["local_names"], state["declared_local_names"])
        self.assertIs(state["scope_context"], statements.normalize_scope_context(None))
        self.assertEqual(state["macro_values"], {})
        self.assertIsNone(state["control_flow_capture"])
        self.assertEqual(instances, {"answer"})

    def test_context_is_frozen_with_live_referenced_containers(self) -> None:
        self.assertEqual(tuple(LOWER_SIGNATURE.parameters), ("statement", "context"))
        self.assertIsNone(LOWER_SIGNATURE.parameters["context"].default)
        model_fields = fields(StatementLoweringContext)
        self.assertEqual(tuple(field.name for field in model_fields), FIELD_NAMES)
        self.assertEqual(tuple(field.default for field in model_fields), FIELD_DEFAULTS)
        hints = get_type_hints(StatementLoweringContext)
        self.assertEqual(tuple(hints[name] for name in FIELD_NAMES), FIELD_TYPES)
        local: set[str] = set()
        counter = [4]
        context = StatementLoweringContext(local_names=local, generated_counter=counter)
        for name in FIELD_NAMES:
            with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                setattr(context, name, None)
        local.add("visible")
        counter[0] += 1
        self.assertIs(context.local_names, local)
        self.assertIs(context.generated_counter, counter)
        self.assertEqual(context.local_names, {"visible"})
        self.assertEqual(context.generated_counter, [5])

    def _assert_factory_field_order(self) -> None:
        tree = ast.parse(Path(statement_parser.__file__).read_text(encoding="utf-8"))
        factory = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_lowering_context"
        )
        self.assertEqual(len(factory.body), 1)
        returned = factory.body[0]
        assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.Call)
        call = returned.value
        self.assertEqual(ast.unparse(call.func), "StatementLoweringContext")
        self.assertEqual(call.args, [])
        self.assertEqual(tuple(keyword.arg for keyword in call.keywords), FIELD_NAMES)
        for keyword in call.keywords[:-1]:
            self.assertEqual(ast.unparse(keyword.value), "self." + str(keyword.arg))
        self.assertEqual(
            ast.unparse(call.keywords[-1].value),
            "self.control_flow_capture if include_control_flow_capture else None",
        )
        self.assertEqual(tuple(argument.arg for argument in factory.args.kwonlyargs), ("include_control_flow_capture",))
        self.assertEqual([ast.unparse(value) for value in factory.args.kw_defaults if value is not None], ["False"])

    def test_statement_phase_contract_and_facade_stay_unchanged(self) -> None:
        self.assertEqual(len(facade.__all__), 44)
        self.assertNotIn("StatementLoweringContext", facade.__all__)
        self.assertNotIn("StatementLoweringContext", statement_api.__all__)
        self.assertEqual(
            tuple(statement_api.__all__), ("collect_static_declarations", "parse_gml_statements", "static_scope_id")
        )
        self.assertEqual(tuple(inspect.signature(statement_api.parse_gml_statements).parameters), ("request",))
        instances: set[str] = set()
        result = statement_api.parse_gml_statements(GMLStatementRequest((), instance_variables=instances))
        self.assertIsInstance(result, GMLStatementResult)
        self.assertIs(result.instance_variables, instances)
        self.assertEqual(result.lines, ())
        self.assertEqual(result.local_names, frozenset())
