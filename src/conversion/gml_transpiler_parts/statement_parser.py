# pyright: reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Iterable, Mapping, MutableMapping, MutableSet

from .constants import ASSIGNMENT_OPERATORS, BINARY_PRECEDENCE, EOF
from .expression_api import (
    emit_instance_keyword_argument,
    evaluate_enum_value_tokens,
    parse_gml_expression,
    transpile_gml_condition,
    transpile_gml_expression,
)
from .lexical_api import (
    reject_asset_identifier_name,
    sanitize_gdscript_identifier,
    validate_gml_identifier,
)
from .shared_models import (
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    ScopeContext as _ScopeContext,
    Token as _Token,
)
from .statement_boundaries import (
    matching_close_index,
    scan_expression_end,
    scan_statement_end,
    skip_newline_tokens,
)
from .statement_macros import expand_statement_macros, macro_tokens_at
from .statement_models import (
    ControlFlowCapture,
    GMLStatementRequest,
    GMLStatementResult,
)
from .statements import (
    control_flow_dispatch_lines,
    transpile_statement,
)
from .static_declarations import read_static_declaration_tokens
from .utils import (
    indent_lines,
    insert_lines_before_continue,
    insert_until_check_before_continue,
    int64_literal_source,
    macro_configuration_matches,
    normalize_scope_context,
    scope_context_with_global_names,
    split_top_level_tokens,
    tokens_to_source,
)


class _StatementParser:
    def __init__(
        self,
        tokens: list[_Token],
        local_names: Iterable[str] | None = None,
        declared_local_names: MutableSet[str] | None = None,
        instance_variables: MutableSet[str] | None = None,
        loop_depth: int = 0,
        continue_depth: int = 0,
        return_depth: int = 0,
        finally_depth: int = 0,
        generated_counter: list[int] | None = None,
        enum_values: MutableMapping[str, dict[str, int]] | None = None,
        enum_names: Iterable[str] | None = None,
        scope_context: _ScopeContext | None = None,
        inherited_event_call: str | None = None,
        macro_values: MutableMapping[str, str] | None = None,
        macro_priorities: MutableMapping[str, int] | None = None,
        macro_configuration: str | None = None,
        top_level_global_scope: bool = False,
        global_names: Iterable[str] | None = None,
        asset_names: Iterable[str] | None = None,
        static_scope_prefix: str | None = None,
        extension_functions: Mapping[str, GMLExtensionFunction] | None = None,
        extension_function_mappings: Mapping[str, GMLExtensionFunctionMapping] | None = None,
        control_flow_capture: ControlFlowCapture | None = None,
    ) -> None:
        # Macros whose value is statements are spliced in before anything
        # reads the tokens, so their var declarations are hoisted like any
        # other.
        tokens = expand_statement_macros(
            tokens,
            {**_source_macro_values(tokens, macro_configuration), **(macro_values or {})},
        )
        self.tokens = tokens
        self.position = 0
        initial_local_names = set(local_names or [])
        self.local_names = set(initial_local_names)
        self.declared_local_names: MutableSet[str] = (
            declared_local_names if declared_local_names is not None else set[str]()
        )
        self.hoisted_local_names = _collect_hoisted_local_names(tokens)
        self._hoisted_local_declaration_lines = [
            f"var {sanitize_gdscript_identifier(name)} = GMRuntime.gml_undefined()"
            for name in self.hoisted_local_names
            if name not in initial_local_names
        ]
        self.local_names.update(self.hoisted_local_names)
        for name in initial_local_names:
            self.declared_local_names.add(name)
        for name in self.hoisted_local_names:
            self.declared_local_names.add(name)
        self._emitted_hoisted_local_declarations = False
        self.instance_variables = instance_variables
        self.loop_depth = loop_depth
        self.continue_depth = continue_depth
        self.return_depth = return_depth
        self.finally_depth = finally_depth
        self.generated_counter = generated_counter if generated_counter is not None else [0]
        self.enum_values: MutableMapping[str, dict[str, int]] = (
            enum_values if enum_values is not None else {}
        )
        self.enum_names: set[str] = set(enum_names or [])
        self.global_names: set[str] = set(global_names or [])
        self.scope_context = scope_context_with_global_names(
            normalize_scope_context(scope_context),
            self.global_names,
            top_level_global_scope=top_level_global_scope,
            asset_names=asset_names,
            static_prefix=static_scope_prefix,
            extension_functions=extension_functions,
            extension_function_mappings=extension_function_mappings,
        )
        self.inherited_event_call = inherited_event_call
        self.control_flow_capture = control_flow_capture
        self.macro_values: MutableMapping[str, str] = (
            macro_values if macro_values is not None else {}
        )
        self.macro_priorities: MutableMapping[str, int] = (
            macro_priorities if macro_priorities is not None else {}
        )
        self.macro_configuration = macro_configuration

    def parse(self, terminator: str | None = None) -> list[str]:
        lines: list[str] = []
        if terminator is None and not self._emitted_hoisted_local_declarations:
            lines.extend(self._hoisted_local_declaration_lines)
            self._emitted_hoisted_local_declarations = True
        while not self._at_end() and not self._check(terminator):
            if self._match(";") or self._match("\n"):
                continue
            lines.extend(self._parse_statement())
        return lines

    def _parse_statement(self) -> list[str]:
        self._expand_statement_start_macro()
        if self._check_directive("#macro"):
            return self._parse_macro_statement()
        if self._check_identifier("globalvar"):
            return self._parse_globalvar_statement()
        if self._check_identifier("static"):
            return self._parse_static_statement()
        if self._check_identifier("enum"):
            return self._parse_enum_statement()
        if self._check_identifier("if"):
            return self._parse_if_statement()
        if self._check_identifier("with"):
            return self._parse_with_statement()
        if self._check_identifier("while"):
            return self._parse_while_statement()
        if self._check_identifier("repeat"):
            return self._parse_repeat_statement()
        if self._check_identifier("do"):
            return self._parse_do_until_statement()
        if self._check_identifier("for"):
            return self._parse_for_statement()
        if self._check_identifier("switch"):
            return self._parse_switch_statement()
        if self._check_identifier("try"):
            return self._parse_try_statement()

        if self._match("{"):
            lines = self.parse(terminator="}")
            self._consume("}")
            return lines

        return self._parse_simple_statement()

    def _parse_simple_statement(self) -> list[str]:
        declared_function = _named_function_declaration_name(self.tokens, self.position)
        statement_tokens = self._read_simple_statement()
        if not statement_tokens:
            return []
        if declared_function is not None:
            statement_tokens = _function_declaration_as_assignment(
                declared_function,
                statement_tokens,
            )
        return transpile_statement(
            tokens_to_source(statement_tokens),
            self.local_names,
            self.declared_local_names,
            self.instance_variables,
            loop_depth=self.loop_depth,
            continue_depth=self.continue_depth,
            return_depth=self.return_depth,
            finally_depth=self.finally_depth,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            inherited_event_call=self.inherited_event_call,
            macro_values=self.macro_values,
            generated_counter=self.generated_counter,
            control_flow_capture=self.control_flow_capture,
        )

    def _expand_statement_start_macro(self) -> None:
        # A macro is text substitution, so one used as a statement runs its
        # value as that statement: with #macro M x = 5, M; assigns x. (A
        # write to the macro itself is left to report the constant.)
        expanded: set[str] = set()
        token = self._peek()
        while (
            token.kind == "IDENT"
            and token.value in self.macro_values
            and token.value not in expanded
            and not self._macro_is_written(self.position)
        ):
            expanded.add(token.value)
            self.tokens = [
                *self.tokens[:self.position],
                *macro_tokens_at(self.macro_values[token.value], token),
                *self.tokens[self.position + 1:],
            ]
            token = self._peek()

    def _macro_is_written(self, index: int) -> bool:
        next_index = skip_newline_tokens(self.tokens, index + 1)
        if next_index >= len(self.tokens):
            return False
        next_token = self.tokens[next_index]
        return next_token.kind == "OP" and (next_token.value in ASSIGNMENT_OPERATORS or next_token.value in ("++", "--"))

    def _parse_macro_statement(self) -> list[str]:
        self._consume_directive("#macro")
        configuration_or_name = self._consume_identifier_name()
        configuration: str | None = None
        name = configuration_or_name
        if self._match(":"):
            configuration = configuration_or_name
            name = self._consume_identifier_name()

        value_tokens = self._read_macro_value_tokens()
        value_source = tokens_to_source(value_tokens)
        if not value_source:
            raise GMLTranspileError("Expected macro value")

        priority = 0
        if configuration is not None:
            if not macro_configuration_matches(configuration, self.macro_configuration):
                return []
            priority = 1

        current_priority = self.macro_priorities.get(name, -1)
        if priority >= current_priority:
            self.macro_values[name] = value_source
            self.macro_priorities[name] = priority
        return []

    def _parse_globalvar_statement(self) -> list[str]:
        self._consume_identifier("globalvar")
        while not self._at_end() and not self._check(";") and not self._check("\n"):
            name = self._consume_identifier_name()
            validate_gml_identifier(name)
            reject_asset_identifier_name(name, self.scope_context)
            self.global_names.add(name)
            if not self._match(","):
                break
        self._match(";")
        self._match("\n")
        self.scope_context = scope_context_with_global_names(
            self.scope_context,
            self.global_names,
        )
        return []

    def _parse_static_statement(self) -> list[str]:
        self._consume_identifier("static")
        _, self.position = read_static_declaration_tokens(self.tokens, self.position)
        if self.scope_context.static_scope is None:
            raise GMLTranspileError("static declarations are only supported inside functions")
        return []

    def _parse_enum_statement(self) -> list[str]:
        self._consume_identifier("enum")
        enum_name = self._consume_identifier_name()
        gdscript_enum_name = sanitize_gdscript_identifier(enum_name)
        self._skip_newlines()
        self._consume("{")

        members: list[tuple[str, str]] = []
        current_enum_values: dict[str, int] = {}
        next_integer_value = 0
        while not self._at_end() and not self._check("}"):
            if self._match(",") or self._match(";") or self._match("\n"):
                continue
            member_name = self._consume_identifier_name()
            if self._match("="):
                value_tokens = self._read_enum_value_tokens()
                enum_value = evaluate_enum_value_tokens(
                    value_tokens,
                    self.enum_values,
                    current_enum_values,
                    self.macro_values,
                )
                next_integer_value = enum_value + 1
            else:
                enum_value = next_integer_value
                next_integer_value += 1
            value = int64_literal_source(enum_value)
            current_enum_values[member_name] = enum_value
            members.append((member_name, value))

        self._consume("}")
        self.enum_values[enum_name] = current_enum_values
        self.enum_names.add(enum_name)
        self.local_names.add(enum_name)

        fields = ", ".join(f"{json.dumps(member_name)}: {value}" for member_name, value in members)
        return [f"var {gdscript_enum_name} = GMRuntime.gml_enum({{{fields}}})"]

    def _parse_if_statement(self) -> list[str]:
        self._consume_identifier("if")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected if condition")
        # if <condition> then <statement> (manual: If Else and Conditional
        # Operators).
        self._skip_newlines()
        self._match_identifier("then")

        condition = transpile_gml_condition(
            tokens_to_source(condition_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        body_lines = self._parse_body()
        lines = [f"if {condition}:"]
        lines.extend(indent_lines(body_lines or ["pass"]))

        self._skip_newlines()
        if self._match_identifier("else"):
            if self._check_identifier("if"):
                else_lines = self._parse_if_statement()
                lines.append(f"elif {else_lines[0][3:]}")
                lines.extend(else_lines[1:])
            else:
                else_body_lines = self._parse_body()
                lines.append("else:")
                lines.extend(indent_lines(else_body_lines or ["pass"]))

        return lines

    def _parse_with_statement(self) -> list[str]:
        self._consume_identifier("with")
        target_tokens = self._read_condition_tokens()
        if not target_tokens:
            raise GMLTranspileError("Expected with target")

        target_expr = parse_gml_expression(
            tokens_to_source(target_tokens),
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            macro_values=self.macro_values,
            scope_context=self.scope_context,
        )
        target = emit_instance_keyword_argument(
            target_expr,
            self.local_names,
            scope_context=self.scope_context,
        )
        with_target = self._next_generated_name("_gml_with_target")
        outer_scope_context = self.scope_context
        # Inside with, instance variables are the with instance's: the
        # members the calling object's script declares are not.
        self.scope_context = _ScopeContext(
            self_expression=with_target,
            other_expression=outer_scope_context.self_expression,
            instance_target=with_target,
            global_names=outer_scope_context.global_names,
            asset_names=outer_scope_context.asset_names,
            direct_instance_names=frozenset(),
            dynamic_instance_names=outer_scope_context.dynamic_instance_names,
            static_scope=outer_scope_context.static_scope,
            static_names=outer_scope_context.static_names,
            static_prefix=outer_scope_context.static_prefix,
            extension_functions=outer_scope_context.extension_functions,
            extension_function_mappings=outer_scope_context.extension_function_mappings,
        )
        self.loop_depth += 1
        self.continue_depth += 1
        try:
            body_lines = self._parse_body()
        finally:
            self.loop_depth -= 1
            self.continue_depth -= 1
            self.scope_context = outer_scope_context

        lines = [
            "for "
            f"{with_target} in "
            f"GMRuntime.gml_with_targets({target}, "
            f"{outer_scope_context.self_expression}, {outer_scope_context.other_expression}):"
        ]
        lines.extend(indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_while_statement(self) -> list[str]:
        self._consume_identifier("while")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected while condition")

        condition = transpile_gml_condition(
            tokens_to_source(condition_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        self.loop_depth += 1
        self.continue_depth += 1
        try:
            body_lines = self._parse_body()
        finally:
            self.loop_depth -= 1
            self.continue_depth -= 1
        lines = [f"while {condition}:"]
        lines.extend(indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_repeat_statement(self) -> list[str]:
        self._consume_identifier("repeat")
        count_tokens = self._read_condition_tokens()
        if not count_tokens:
            raise GMLTranspileError("Expected repeat count")

        count = transpile_gml_expression(
            tokens_to_source(count_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        self.loop_depth += 1
        self.continue_depth += 1
        try:
            body_lines = self._parse_body()
        finally:
            self.loop_depth -= 1
            self.continue_depth -= 1

        repeat_index = self._next_generated_name("_gml_repeat_index")
        lines = [f"for {repeat_index} in range(GMRuntime.gml_repeat_count({count})):"]
        lines.extend(indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_for_statement(self) -> list[str]:
        self._consume_identifier("for")
        self._consume("(")
        header_tokens = self._read_balanced_tokens("(", ")")
        header_parts = split_top_level_tokens(header_tokens, ";")
        if len(header_parts) == 4 and all(token.kind == "NEWLINE" for token in header_parts[3]):
            # The operation may end with a semicolon: the manual's form is
            # for (<assignment>; <expression>; <operation>;).
            header_parts = header_parts[:3]
        if len(header_parts) != 3:
            raise GMLTranspileError("Expected for initializer, condition, and operation clauses")

        initializer = tokens_to_source(header_parts[0])
        condition_source = tokens_to_source(header_parts[1])
        operation = tokens_to_source(header_parts[2])

        lines: list[str] = []
        if initializer:
            lines.extend(
                transpile_statement(
                    initializer,
                    self.local_names,
                    self.declared_local_names,
                    self.instance_variables,
                    loop_depth=self.loop_depth,
                    continue_depth=self.continue_depth,
                    return_depth=self.return_depth,
                    finally_depth=self.finally_depth,
                    enum_values=self.enum_values,
                    enum_names=self.enum_names,
                    scope_context=self.scope_context,
                    inherited_event_call=self.inherited_event_call,
                    macro_values=self.macro_values,
                    generated_counter=self.generated_counter,
                )
            )

        condition = (
            transpile_gml_condition(
                condition_source,
                local_names=self.local_names,
                enum_values=self.enum_values,
                enum_names=self.enum_names,
                scope_context=self.scope_context,
                macro_values=self.macro_values,
            )
            if condition_source
            else "true"
        )
        operation_lines = (
            transpile_statement(
                operation,
                self.local_names,
                self.declared_local_names,
                self.instance_variables,
                loop_depth=self.loop_depth,
                continue_depth=self.continue_depth,
                return_depth=self.return_depth,
                finally_depth=self.finally_depth,
                enum_values=self.enum_values,
                enum_names=self.enum_names,
                scope_context=self.scope_context,
                inherited_event_call=self.inherited_event_call,
                macro_values=self.macro_values,
                generated_counter=self.generated_counter,
            )
            if operation
            else []
        )

        self.loop_depth += 1
        self.continue_depth += 1
        try:
            body_lines = self._parse_body()
        finally:
            self.loop_depth -= 1
            self.continue_depth -= 1

        if operation_lines:
            body_lines = insert_lines_before_continue(body_lines, operation_lines)
            body_lines.extend(operation_lines)

        lines.append(f"while {condition}:")
        lines.extend(indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_do_until_statement(self) -> list[str]:
        self._consume_identifier("do")
        self.loop_depth += 1
        self.continue_depth += 1
        try:
            body_lines = self._parse_do_until_body()
        finally:
            self.loop_depth -= 1
            self.continue_depth -= 1

        self._skip_newlines()
        self._consume_identifier("until")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected until condition")

        condition = transpile_gml_condition(
            tokens_to_source(condition_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        body_lines = insert_until_check_before_continue(body_lines, condition)
        lines = ["while true:"]
        lines.extend(indent_lines(body_lines or ["pass"]))
        lines.extend(indent_lines([f"if {condition}:", "\tbreak"]))
        return lines

    def _parse_switch_statement(self) -> list[str]:
        self._consume_identifier("switch")
        expression_tokens = self._read_condition_tokens()
        if not expression_tokens:
            raise GMLTranspileError("Expected switch expression")

        switch_value = self._next_generated_name("_gml_switch_value")
        switch_matched = self._next_generated_name("_gml_switch_matched")
        switch_has_case = self._next_generated_name("_gml_switch_has_case")
        switch_control = self._next_generated_name("_gml_switch_control")
        switch_capture = self._switch_control_capture(switch_control)
        expression = transpile_gml_expression(
            tokens_to_source(expression_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        sections = self._parse_switch_sections(switch_capture)
        case_values = [
            section_value
            for section_kind, section_value, _ in sections
            if section_kind == "case" and section_value is not None
        ]
        case_conditions = [
            f"GMRuntime.gml_eq({switch_value}, {case_value})"
            for case_value in case_values
        ]
        has_case_expression = " or ".join(case_conditions) if case_conditions else "false"

        lines: list[str] = []
        if switch_capture is not None:
            lines.append(f"var {switch_control} = GMRuntime.gml_undefined()")
        lines.extend([
            f"var {switch_value} = {expression}",
            f"var {switch_matched} = false",
            f"var {switch_has_case} = {has_case_expression}",
            "while true:",
        ])
        for section_kind, section_value, section_lines in sections:
            if section_kind == "case":
                section_test = (
                    f"if not {switch_matched} and "
                    f"GMRuntime.gml_eq({switch_value}, {section_value}):"
                )
            else:
                section_test = f"if not {switch_matched} and not {switch_has_case}:"
            lines.extend(
                indent_lines(
                    [
                        section_test,
                        f"\t{switch_matched} = true",
                        f"if {switch_matched}:",
                    ]
                )
            )
            lines.extend(indent_lines(indent_lines(section_lines or ["pass"])))
        lines.append("\tbreak")
        if switch_capture is not None:
            lines.extend(
                control_flow_dispatch_lines(
                    switch_control,
                    switch_capture,
                    self.control_flow_capture,
                    return_value_allowed=self.return_depth > 0,
                )
            )
        return lines

    def _switch_control_capture(self, switch_control: str) -> ControlFlowCapture | None:
        parent_capture = self.control_flow_capture
        capture_return = bool(parent_capture and parent_capture.capture_return)
        capture_exit = bool(parent_capture and parent_capture.capture_exit)
        capture_throw = bool(parent_capture and parent_capture.capture_throw)
        capture_continue = self.continue_depth > 0 or bool(
            parent_capture and parent_capture.capture_continue
        )
        if not (capture_return or capture_exit or capture_throw or capture_continue):
            return None
        return ControlFlowCapture(
            switch_control,
            self.loop_depth + 1,
            self.continue_depth,
            capture_return=capture_return,
            capture_exit=capture_exit,
            capture_throw=capture_throw,
            capture_continue=capture_continue,
        )

    def _parse_switch_sections(
        self,
        control_flow_capture: ControlFlowCapture | None,
    ) -> list[tuple[str, str | None, list[str]]]:
        self._skip_newlines()
        self._consume("{")
        sections: list[tuple[str, str | None, list[str]]] = []
        while not self._at_end() and not self._check("}"):
            if self._match(";") or self._match("\n"):
                continue
            if self._match_identifier("case"):
                label_tokens = self._read_switch_label_tokens()
                if not label_tokens:
                    raise GMLTranspileError("Expected switch case value")
                label = transpile_gml_expression(
                    tokens_to_source(label_tokens),
                    local_names=self.local_names,
                    enum_values=self.enum_values,
                    enum_names=self.enum_names,
                    scope_context=self.scope_context,
                    macro_values=self.macro_values,
                )
                body_tokens = self._read_switch_section_body_tokens()
                sections.append(
                    (
                        "case",
                        label,
                        self._parse_switch_section_body(body_tokens, control_flow_capture),
                    )
                )
                continue
            if self._match_identifier("default"):
                self._consume(":")
                body_tokens = self._read_switch_section_body_tokens()
                sections.append(
                    (
                        "default",
                        None,
                        self._parse_switch_section_body(body_tokens, control_flow_capture),
                    )
                )
                continue
            raise GMLTranspileError(f"Expected switch case or default, got: {self._peek().value}")

        self._consume("}")
        return sections

    def _parse_switch_section_body(
        self,
        body_tokens: list[_Token],
        control_flow_capture: ControlFlowCapture | None,
    ) -> list[str]:
        parser = _StatementParser(
            body_tokens,
            local_names=self.local_names,
            declared_local_names=set[str](),
            instance_variables=self.instance_variables,
            loop_depth=self.loop_depth + 1,
            continue_depth=self.continue_depth,
            return_depth=self.return_depth,
            finally_depth=self.finally_depth,
            generated_counter=self.generated_counter,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            inherited_event_call=self.inherited_event_call,
            macro_values=self.macro_values,
            macro_priorities=self.macro_priorities,
            macro_configuration=self.macro_configuration,
            global_names=self.global_names,
            control_flow_capture=control_flow_capture,
        )
        lines = parser.parse()
        self.local_names.update(parser.local_names)
        self.enum_names.update(parser.enum_names)
        self.global_names.update(parser.global_names)
        self.scope_context = scope_context_with_global_names(
            self.scope_context,
            self.global_names,
        )
        return lines

    def _parse_try_statement(self) -> list[str]:
        self._consume_identifier("try")
        control_name = self._next_generated_name("_gml_try_control")
        try_capture = ControlFlowCapture(
            control_name,
            self.loop_depth,
            self.continue_depth,
            capture_return=True,
            capture_exit=True,
            capture_throw=True,
            capture_break=self.loop_depth > 0,
            capture_continue=self.continue_depth > 0,
        )
        parent_capture = self.control_flow_capture
        self.control_flow_capture = try_capture
        try:
            try_lines = self._parse_body()
        finally:
            self.control_flow_capture = parent_capture

        self._skip_newlines()
        catch_name: str | None = None
        catch_lines: list[str] | None = None
        catch_declares = False
        if self._match_identifier("catch"):
            catch_name = self._parse_catch_variable_name()
            had_catch_local = catch_name in self.local_names
            # GDScript refuses a variable that has the name of one already
            # declared in the function, in any block around it; a catch
            # variable named like an outer catch variable or local (catch (e)
            # inside catch (e)) is that variable again, as in GML.
            catch_declares = catch_name not in self.declared_local_names
            self.local_names.add(catch_name)
            self.declared_local_names.add(catch_name)
            self.control_flow_capture = try_capture
            try:
                catch_lines = self._parse_body()
            finally:
                self.control_flow_capture = parent_capture
                if not had_catch_local:
                    self.local_names.discard(catch_name)
                if catch_declares:
                    self.declared_local_names.discard(catch_name)

        self._skip_newlines()
        finally_lines: list[str] | None = None
        if self._match_identifier("finally"):
            self.finally_depth += 1
            try:
                finally_lines = self._parse_body()
            finally:
                self.finally_depth -= 1

        if catch_lines is None and finally_lines is None:
            raise GMLTranspileError("try requires catch or finally")

        lines = [
            f"var {control_name} = GMRuntime.gml_undefined()",
            "while true:",
            *indent_lines(try_lines or ["pass"]),
            "\tbreak",
        ]

        if catch_lines is not None and catch_name is not None:
            gdscript_catch_name = sanitize_gdscript_identifier(catch_name)
            catch_declaration = "var " if catch_declares else ""
            lines.extend([
                f"if not GMRuntime.is_undefined({control_name}) and {control_name}[\"kind\"] == \"throw\":",
                f"\t{catch_declaration}{gdscript_catch_name} = GMRuntime.gml_exception_struct({control_name}[\"value\"])",
                f"\t{control_name} = GMRuntime.gml_undefined()",
                "\twhile true:",
                *indent_lines(indent_lines(catch_lines or ["pass"])),
                "\t\tbreak",
            ])

        if finally_lines is not None:
            lines.extend(finally_lines or ["pass"])

        lines.extend(
            control_flow_dispatch_lines(
                control_name,
                try_capture,
                parent_capture,
                return_value_allowed=self.return_depth > 0,
            )
        )
        return lines

    def _parse_catch_variable_name(self) -> str:
        catch_tokens = self._read_condition_tokens()
        if len(catch_tokens) != 1 or catch_tokens[0].kind != "IDENT":
            raise GMLTranspileError("catch requires a variable name")
        catch_name = catch_tokens[0].value
        validate_gml_identifier(catch_name)
        return catch_name

    def _read_switch_label_tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value == ":":
                self._advance()
                return tokens

            if token.value in "([{":
                depth += 1
            elif token.value in ")]}" and depth > 0:
                depth -= 1
            tokens.append(self._advance())

        raise GMLTranspileError("Expected ':' after switch case")

    def _read_switch_section_body_tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value == "}":
                break
            if depth == 0 and token.kind == "IDENT" and token.value in ("case", "default"):
                break

            if token.value in "([{":
                depth += 1
            elif token.value in ")]}":
                if depth > 0:
                    depth -= 1
            tokens.append(self._advance())

        return tokens

    def _parse_do_until_body(self) -> list[str]:
        self._skip_newlines()
        if self._match("{"):
            return self._parse_nested_braced_body()

        statement_tokens = self._read_do_until_statement_tokens()
        if not statement_tokens:
            return []
        return transpile_statement(
            tokens_to_source(statement_tokens),
            self.local_names,
            self.declared_local_names,
            self.instance_variables,
            loop_depth=self.loop_depth,
            continue_depth=self.continue_depth,
            return_depth=self.return_depth,
            finally_depth=self.finally_depth,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            inherited_event_call=self.inherited_event_call,
            macro_values=self.macro_values,
            generated_counter=self.generated_counter,
        )

    def _parse_body(self) -> list[str]:
        self._skip_newlines()
        if self._match("{"):
            return self._parse_nested_braced_body()
        if self._at_end() or self._check("}"):
            return []
        return self._parse_nested_single_statement_body()

    def _parse_nested_braced_body(self) -> list[str]:
        lines = self.parse(terminator="}")
        self._consume("}")
        return lines

    def _parse_nested_single_statement_body(self) -> list[str]:
        return self._parse_statement()

    def _read_condition_tokens(self) -> list[_Token]:
        # The condition is one expression, with or without parentheses; the
        # body may follow on the same line.
        start = skip_newline_tokens(self.tokens, self.position)
        end = scan_expression_end(self.tokens, start)
        if end is not None:
            self.position = end
            tokens = [token for token in self.tokens[start:end] if token.kind != "NEWLINE"]
            if tokens[0].value == "(" and matching_close_index(tokens, 0) == len(tokens) - 1:
                return tokens[1:-1]
            return tokens
        if self._check("("):
            condition_start = self.position
            self._advance()
            parenthesized_tokens = self._read_balanced_tokens("(", ")")
            lookahead = self.position
            while lookahead < len(self.tokens) and self.tokens[lookahead].value == "\n":
                lookahead += 1
            next_value = self.tokens[lookahead].value if lookahead < len(self.tokens) else ""
            if next_value not in BINARY_PRECEDENCE and next_value not in {"?", "(", "[", "."}:
                return parenthesized_tokens

            tokens = list(self.tokens[condition_start:self.position])
            depth = 0
            while not self._at_end():
                token = self._peek()
                if depth == 0 and token.value in {"{", ";"}:
                    break
                if token.value in "([":
                    depth += 1
                elif token.value in ")]" and depth > 0:
                    depth -= 1
                tokens.append(self._advance())
            return tokens

        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value == "{":
                break
            if depth == 0 and token.value == ";":
                break

            if token.value in "([":
                depth += 1
            elif token.value in ")]" and depth > 0:
                depth -= 1
            tokens.append(self._advance())

        return tokens

    def _read_do_until_statement_tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.kind == "IDENT" and token.value == "until":
                break

            if token.value in "([":
                depth += 1
            elif token.value in ")]" and depth > 0:
                depth -= 1
            tokens.append(self._advance())

        return tokens

    def _read_enum_value_tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value in (",", "}", "\n"):
                break
            if token.value in "([":
                depth += 1
            elif token.value in ")]" and depth > 0:
                depth -= 1
            tokens.append(self._advance())
        if not tokens:
            raise GMLTranspileError("Expected enum value")
        return tokens

    def _read_macro_value_tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        while not self._at_end() and not self._check("\n"):
            tokens.append(self._advance())
        self._match("\n")
        return tokens

    def _skip_newlines(self) -> None:
        while self._match("\n"):
            pass

    def _read_balanced_tokens(self, opener: str, closer: str) -> list[_Token]:
        tokens: list[_Token] = []
        depth = 1
        while not self._at_end():
            token = self._advance()
            if token.value == opener:
                depth += 1
            elif token.value == closer:
                depth -= 1
                if depth == 0:
                    return tokens
            tokens.append(token)

        raise self._error(f"Expected '{closer}'")

    def _read_simple_statement(self) -> list[_Token]:
        # A statement ends where its expression ends: it may share a line
        # with the next statement, and line breaks inside it are white space.
        end = scan_statement_end(self.tokens, self.position)
        if end is not None:
            statement_tokens = [token for token in self.tokens[self.position:end] if token.kind != "NEWLINE"]
            self.position = end
            self._match(";")
            return statement_tokens
        tokens: list[_Token] = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value == "}":
                break
            if depth == 0 and token.value in (";", "\n"):
                self._advance()
                break

            if token.value in "([{":
                depth += 1
            elif token.value in ")]}":
                if depth > 0:
                    depth -= 1
            tokens.append(self._advance())

        return tokens

    def _match(self, value: str) -> bool:
        if self._check(value):
            self.position += 1
            return True
        return False

    def _match_identifier(self, value: str) -> bool:
        if self._check_identifier(value):
            self.position += 1
            return True
        return False

    def _consume(self, value: str) -> None:
        if not self._match(value):
            raise self._error(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self, value: str) -> None:
        if not self._match_identifier(value):
            raise self._error(f"Expected '{value}', got: {self._peek().value}")

    def _consume_directive(self, value: str) -> None:
        if not self._check_directive(value):
            raise self._error(f"Expected '{value}', got: {self._peek().value}")
        self.position += 1

    def _consume_identifier_name(self) -> str:
        token = self._advance()
        if token.kind != "IDENT":
            raise GMLTranspileError(
                f"Expected identifier, got: {token.value}",
                line=token.line,
                column=token.column,
            )
        try:
            validate_gml_identifier(token.value)
        except GMLTranspileError as exc:
            raise exc.with_location(token.line, token.column) from exc
        return token.value

    def _check(self, value: str | None) -> bool:
        if value is None:
            return False
        return self._peek().value == value

    def _check_identifier(self, value: str) -> bool:
        token = self._peek()
        return token.kind == "IDENT" and token.value == value

    def _check_directive(self, value: str) -> bool:
        token = self._peek()
        return token.kind == "DIRECTIVE" and token.value == value

    def _advance(self) -> _Token:
        token = self._peek()
        if not self._at_end():
            self.position += 1
        return token

    def _peek(self) -> _Token:
        if self.position >= len(self.tokens):
            return EOF
        return self.tokens[self.position]

    def _at_end(self) -> bool:
        return self._peek().kind == "EOF"

    def _next_generated_name(self, prefix: str) -> str:
        index = self.generated_counter[0]
        self.generated_counter[0] += 1
        return f"{prefix}_{index}"

    def _error(self, message: str) -> GMLTranspileError:
        token = self._peek()
        return GMLTranspileError(message, line=token.line, column=token.column)


# The temporaries counter of the statements being parsed. Statements parsed
# while it is set are a method's body written in them, which becomes a GDScript
# lambda inside them; redeclaring a name already in scope there is a parse
# error, so the method numbers its temporaries (switch, try, with, repeat...)
# from the same counter.
_ACTIVE_GENERATED_COUNTER: ContextVar[list[int] | None] = ContextVar(
    "gml_active_generated_counter", default=None
)


def parse_gml_statements(request: GMLStatementRequest) -> GMLStatementResult:
    parser = _StatementParser(
        _hoist_function_declarations(list(request.tokens)),
        local_names=request.local_names,
        instance_variables=request.instance_variables,
        return_depth=request.return_depth,
        enum_values=request.enum_values,
        enum_names=request.enum_names,
        scope_context=request.scope_context,
        inherited_event_call=request.inherited_event_call,
        macro_values=request.macro_values,
        macro_priorities=request.macro_priorities,
        macro_configuration=request.macro_configuration,
        top_level_global_scope=request.top_level_global_scope,
        global_names=request.global_names,
        asset_names=request.asset_names,
        static_scope_prefix=request.static_scope_prefix,
        extension_functions=request.extension_functions,
        extension_function_mappings=request.extension_function_mappings,
        generated_counter=_ACTIVE_GENERATED_COUNTER.get(),
    )
    active_counter = _ACTIVE_GENERATED_COUNTER.set(parser.generated_counter)
    try:
        lines = parser.parse()
    finally:
        _ACTIVE_GENERATED_COUNTER.reset(active_counter)
    return GMLStatementResult(
        lines=tuple(lines),
        local_names=frozenset(parser.local_names),
        instance_variables=parser.instance_variables,
        scope_context=parser.scope_context,
        enum_values=parser.enum_values,
        enum_names=frozenset(parser.enum_names),
        macro_values=parser.macro_values,
    )


# A named function declaration (function name(...) {...}) in event, method,
# constructor or script-function code is a method variable of the instance or
# struct running that code, bound to it, as if it were written name =
# function(...) {...} (manual: GML Overview > Script Functions And Variables,
# Method Variables: "Defining a function in an Object's event using either
# syntax will make the function only available in the context of its
# instance"). GameMaker has the function available throughout the body, even
# before its line runs, so the declarations at the top of a body are moved to
# its start.
_EXPRESSION_KEYWORDS = frozenset({
    "and",
    "case",
    "delete",
    "div",
    "do",
    "else",
    "in",
    "mod",
    "new",
    "not",
    "or",
    "return",
    "then",
    "throw",
    "xor",
})
_OPENING_BRACKETS = frozenset({"(", "[", "{"})
_CLOSING_BRACKETS = frozenset({")", "]", "}"})


def _named_function_declaration_name(tokens: list[_Token], index: int) -> str | None:
    if index >= len(tokens) or tokens[index].kind != "IDENT" or tokens[index].value != "function":
        return None
    name_index = skip_newline_tokens(tokens, index + 1)
    if (
        name_index >= len(tokens)
        or tokens[name_index].kind != "IDENT"
        or tokens[name_index].value == "constructor"
    ):
        return None
    parameters_index = skip_newline_tokens(tokens, name_index + 1)
    if parameters_index >= len(tokens) or tokens[parameters_index].value != "(":
        return None
    return tokens[name_index].value


def _function_declaration_as_assignment(name: str, statement_tokens: list[_Token]) -> list[_Token]:
    first = statement_tokens[0]
    return [
        _Token("IDENT", name, line=first.line, column=first.column, index=first.index),
        _Token("OP", "=", line=first.line, column=first.column, index=first.index),
        *statement_tokens,
    ]


def _starts_statement(tokens: list[_Token], index: int) -> bool:
    previous = index - 1
    crossed_line_break = False
    while previous >= 0 and tokens[previous].kind == "NEWLINE":
        previous -= 1
        crossed_line_break = True
    if previous < 0:
        return True
    token = tokens[previous]
    if token.value in (";", "}"):
        return True
    if not crossed_line_break:
        return False
    # Line breaks are white space, but a function declaration cannot continue
    # an expression: after anything that can end one, it starts a statement.
    if token.kind == "IDENT":
        return token.value not in _EXPRESSION_KEYWORDS
    return token.kind in ("NUMBER", "STRING", "VERBATIM_STRING", "TEMPLATE_STRING") or token.value in (")", "]")


def _hoist_function_declarations(tokens: list[_Token]) -> list[_Token]:
    spans: list[tuple[int, int]] = []
    depth = 0
    in_directive = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "DIRECTIVE":
            in_directive = True
        elif token.kind == "NEWLINE":
            in_directive = False
        elif token.kind == "OP" and token.value in _OPENING_BRACKETS:
            depth += 1
        elif token.kind == "OP" and token.value in _CLOSING_BRACKETS:
            depth = max(0, depth - 1)
        elif (
            depth == 0
            and not in_directive
            and _named_function_declaration_name(tokens, index) is not None
            and _starts_statement(tokens, index)
        ):
            end = scan_statement_end(tokens, index)
            if end is not None and end > index:
                spans.append((index, end))
                index = end
                continue
        index += 1
    if not spans:
        return tokens
    hoisted: list[_Token] = []
    remaining: list[_Token] = []
    cursor = 0
    for start, end in spans:
        remaining.extend(tokens[cursor:start])
        hoisted.extend(tokens[start:end])
        hoisted.append(_Token("OP", ";", line=tokens[end - 1].line, column=tokens[end - 1].column, index=tokens[end - 1].index))
        cursor = end
    remaining.extend(tokens[cursor:])
    return [*hoisted, *remaining]


def _source_macro_values(tokens: list[_Token], macro_configuration: str | None) -> dict[str, str]:
    # The #macro definitions in these tokens; one for the active
    # configuration replaces the plain one.
    values: dict[str, str] = {}
    configured: set[str] = set()
    index = 0
    while index < len(tokens):
        if tokens[index].kind != "DIRECTIVE" or tokens[index].value != "#macro":
            index += 1
            continue
        end = index + 1
        while end < len(tokens) and tokens[end].kind not in ("NEWLINE", "EOF"):
            end += 1
        definition = tokens[index + 1:end]
        index = end
        if len(definition) >= 3 and definition[1].value == ":":
            configuration, name, value_tokens = definition[0].value, definition[2].value, definition[3:]
            if not macro_configuration_matches(configuration, macro_configuration):
                continue
            configured.add(name)
        elif definition and definition[0].kind == "IDENT":
            name, value_tokens = definition[0].value, definition[1:]
            if name in configured:
                continue
        else:
            continue
        if value_tokens:
            values[name] = tokens_to_source(value_tokens)
    return values


def _collect_hoisted_local_names(tokens: list[_Token]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    root_declared_names: set[str] = set()
    brace_depth = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "DIRECTIVE" and token.value == "#macro":
            # A macro's value declares its locals where the macro is used.
            while index < len(tokens) and tokens[index].kind not in ("NEWLINE", "EOF"):
                index += 1
            continue
        if token.kind == "IDENT" and token.value == "function":
            index = _skip_function_literal(tokens, index)
            continue
        if token.kind == "IDENT" and token.value == "var":
            should_hoist = brace_depth > 0 or not _is_root_var_statement(tokens, index)
            declared_names = _collect_var_statement_names(tokens, index + 1)
            if should_hoist:
                for name in declared_names:
                    if name in root_declared_names:
                        continue
                    if name not in seen:
                        names.append(name)
                        seen.add(name)
            else:
                root_declared_names.update(declared_names)
        elif token.value == "{":
            brace_depth += 1
        elif token.value == "}":
            brace_depth = max(0, brace_depth - 1)
        index += 1
    return tuple(names)


def _collect_var_statement_names(tokens: list[_Token], start: int) -> tuple[str, ...]:
    names: list[str] = []
    index = start
    depth = 0
    expect_name = True
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if depth == 0 and token.value in {";", "\n"}:
            break
        if expect_name:
            if token.kind == "IDENT":
                names.append(token.value)
                expect_name = False
            index += 1
            continue
        if token.kind == "IDENT" and token.value == "function":
            index = _skip_function_literal(tokens, index)
            continue
        if token.value in {"(", "[", "{"}:
            depth += 1
        elif token.value in {")", "]", "}"}:
            if depth <= 0:
                break
            depth -= 1
        elif depth == 0 and token.value == ",":
            expect_name = True
        index += 1
    return tuple(names)


def _is_root_var_statement(tokens: list[_Token], index: int) -> bool:
    previous_index = _previous_token_index(tokens, index)
    if previous_index is None:
        return True
    previous = tokens[previous_index]
    if previous.value in {";", "\n", "}"}:
        return True
    if previous.value == "(":
        before_previous_index = _previous_token_index(tokens, previous_index)
        if before_previous_index is None:
            return False
        before_previous = tokens[before_previous_index]
        return before_previous.kind == "IDENT" and before_previous.value == "for"
    return False


def _previous_token_index(tokens: list[_Token], index: int) -> int | None:
    cursor = index - 1
    return cursor if cursor >= 0 else None


def _skip_function_literal(tokens: list[_Token], index: int) -> int:
    cursor = index + 1
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.kind == "EOF":
            return cursor
        if token.value == "{":
            return _matching_closing_brace_index(tokens, cursor) + 1
        cursor += 1
    return cursor


def _matching_closing_brace_index(tokens: list[_Token], open_index: int) -> int:
    depth = 0
    cursor = open_index
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.value == "{":
            depth += 1
        elif token.value == "}":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return max(open_index, len(tokens) - 1)
