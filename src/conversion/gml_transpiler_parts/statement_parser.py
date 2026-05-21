# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from typing import Iterable, MutableMapping, MutableSet

from .constants import _EOF
from .emitter import _emit_instance_keyword_argument
from .enum_helpers import _evaluate_enum_value_tokens
from .expression_parser import _parse_gml_expression
from .expression_service import transpile_gml_condition, transpile_gml_expression
from .identifiers import (
    _reject_asset_identifier_name,
    _sanitize_gdscript_identifier,
    _validate_gml_identifier,
)
from .model import (
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    GMLTranspileError,
    _ScopeContext,
    _Token,
)
from .statements import (
    _ControlFlowCapture,
    _control_flow_dispatch_lines,
    _transpile_statement,
)
from .utils import (
    _indent_lines,
    _insert_lines_before_continue,
    _insert_until_check_before_continue,
    _macro_configuration_matches,
    _normalize_scope_context,
    _scope_context_with_global_names,
    _split_top_level_tokens,
    _tokens_to_source,
)

class _StatementParser:
    def __init__(
        self,
        tokens: list[_Token],
        local_names: Iterable[str] | None = None,
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
        extension_functions: dict[str, GMLExtensionFunction] | None = None,
        extension_function_mappings: dict[str, GMLExtensionFunctionMapping] | None = None,
        control_flow_capture: _ControlFlowCapture | None = None,
    ) -> None:
        self.tokens = tokens
        self.position = 0
        self.local_names = set(local_names or [])
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
        self.scope_context = _scope_context_with_global_names(
            _normalize_scope_context(scope_context),
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
        while not self._at_end() and not self._check(terminator):
            if self._match(";") or self._match("\n"):
                continue
            lines.extend(self._parse_statement())
        return lines

    def _parse_statement(self) -> list[str]:
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

        statement_tokens = self._read_simple_statement()
        if not statement_tokens:
            return []
        return _transpile_statement(
            _tokens_to_source(statement_tokens),
            self.local_names,
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

    def _parse_macro_statement(self) -> list[str]:
        self._consume_directive("#macro")
        configuration_or_name = self._consume_identifier_name()
        configuration: str | None = None
        name = configuration_or_name
        if self._match(":"):
            configuration = configuration_or_name
            name = self._consume_identifier_name()

        value_tokens = self._read_macro_value_tokens()
        value_source = _tokens_to_source(value_tokens)
        if not value_source:
            raise GMLTranspileError("Expected macro value")

        priority = 0
        if configuration is not None:
            if not _macro_configuration_matches(configuration, self.macro_configuration):
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
            _validate_gml_identifier(name)
            _reject_asset_identifier_name(name, self.scope_context)
            self.global_names.add(name)
            if not self._match(","):
                break
        self._match(";")
        self._match("\n")
        self.scope_context = _scope_context_with_global_names(
            self.scope_context,
            self.global_names,
        )
        return []

    def _parse_static_statement(self) -> list[str]:
        self._read_simple_statement()
        if self.scope_context.static_scope is None:
            raise GMLTranspileError("static declarations are only supported inside functions")
        return []

    def _parse_enum_statement(self) -> list[str]:
        self._consume_identifier("enum")
        enum_name = self._consume_identifier_name()
        gdscript_enum_name = _sanitize_gdscript_identifier(enum_name)
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
                enum_value = _evaluate_enum_value_tokens(
                    value_tokens,
                    self.enum_values,
                    current_enum_values,
                    self.macro_values,
                )
                next_integer_value = enum_value + 1
            else:
                enum_value = next_integer_value
                next_integer_value += 1
            value = str(enum_value)
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

        condition = transpile_gml_condition(
            _tokens_to_source(condition_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        body_lines = self._parse_body()
        lines = [f"if {condition}:"]
        lines.extend(_indent_lines(body_lines or ["pass"]))

        self._skip_newlines()
        if self._match_identifier("else"):
            if self._check_identifier("if"):
                else_lines = self._parse_if_statement()
                lines.append(f"elif {else_lines[0][3:]}")
                lines.extend(else_lines[1:])
            else:
                else_body_lines = self._parse_body()
                lines.append("else:")
                lines.extend(_indent_lines(else_body_lines or ["pass"]))

        return lines

    def _parse_with_statement(self) -> list[str]:
        self._consume_identifier("with")
        target_tokens = self._read_condition_tokens()
        if not target_tokens:
            raise GMLTranspileError("Expected with target")

        target_expr = _parse_gml_expression(
            _tokens_to_source(target_tokens),
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            macro_values=self.macro_values,
            scope_context=self.scope_context,
        )
        target = _emit_instance_keyword_argument(
            target_expr,
            self.local_names,
            scope_context=self.scope_context,
        )
        with_target = self._next_generated_name("_gml_with_target")
        outer_scope_context = self.scope_context
        self.scope_context = _ScopeContext(
            self_expression=with_target,
            other_expression=outer_scope_context.self_expression,
            instance_target=with_target,
            global_names=outer_scope_context.global_names,
            asset_names=outer_scope_context.asset_names,
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
        lines.extend(_indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_while_statement(self) -> list[str]:
        self._consume_identifier("while")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected while condition")

        condition = transpile_gml_condition(
            _tokens_to_source(condition_tokens),
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
        lines.extend(_indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_repeat_statement(self) -> list[str]:
        self._consume_identifier("repeat")
        count_tokens = self._read_condition_tokens()
        if not count_tokens:
            raise GMLTranspileError("Expected repeat count")

        count = transpile_gml_expression(
            _tokens_to_source(count_tokens),
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

        lines = [f"for _gml_repeat_index in range(GMRuntime.gml_repeat_count({count})):"]
        lines.extend(_indent_lines(body_lines or ["pass"]))
        return lines

    def _parse_for_statement(self) -> list[str]:
        self._consume_identifier("for")
        self._consume("(")
        header_tokens = self._read_balanced_tokens("(", ")")
        header_parts = _split_top_level_tokens(header_tokens, ";")
        if len(header_parts) != 3:
            raise GMLTranspileError("Expected for initializer, condition, and operation clauses")

        initializer = _tokens_to_source(header_parts[0])
        condition_source = _tokens_to_source(header_parts[1])
        operation = _tokens_to_source(header_parts[2])

        lines: list[str] = []
        if initializer:
            lines.extend(
                _transpile_statement(
                    initializer,
                    self.local_names,
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
            _transpile_statement(
                operation,
                self.local_names,
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
            body_lines = _insert_lines_before_continue(body_lines, operation_lines)
            body_lines.extend(operation_lines)

        lines.append(f"while {condition}:")
        lines.extend(_indent_lines(body_lines or ["pass"]))
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
            _tokens_to_source(condition_tokens),
            local_names=self.local_names,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=self.scope_context,
            macro_values=self.macro_values,
        )
        body_lines = _insert_until_check_before_continue(body_lines, condition)
        lines = ["while true:"]
        lines.extend(_indent_lines(body_lines or ["pass"]))
        lines.append(f"\tif {condition}:")
        lines.append("\t\tbreak")
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
            _tokens_to_source(expression_tokens),
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
                lines.append(
                    f"\tif not {switch_matched} and GMRuntime.gml_eq({switch_value}, {section_value}):"
                )
                lines.append(f"\t\t{switch_matched} = true")
            else:
                lines.append(f"\tif not {switch_matched} and not {switch_has_case}:")
                lines.append(f"\t\t{switch_matched} = true")

            lines.append(f"\tif {switch_matched}:")
            lines.extend(f"\t\t{line}" for line in (section_lines or ["pass"]))
        lines.append("\tbreak")
        if switch_capture is not None:
            lines.extend(
                _control_flow_dispatch_lines(
                    switch_control,
                    switch_capture,
                    self.control_flow_capture,
                )
            )
        return lines

    def _switch_control_capture(self, switch_control: str) -> _ControlFlowCapture | None:
        parent_capture = self.control_flow_capture
        capture_return = bool(parent_capture and parent_capture.capture_return)
        capture_exit = bool(parent_capture and parent_capture.capture_exit)
        capture_throw = bool(parent_capture and parent_capture.capture_throw)
        capture_continue = self.continue_depth > 0 or bool(
            parent_capture and parent_capture.capture_continue
        )
        if not (capture_return or capture_exit or capture_throw or capture_continue):
            return None
        return _ControlFlowCapture(
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
        control_flow_capture: _ControlFlowCapture | None,
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
                    _tokens_to_source(label_tokens),
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
        control_flow_capture: _ControlFlowCapture | None,
    ) -> list[str]:
        parser = _StatementParser(
            body_tokens,
            local_names=self.local_names,
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
        self.scope_context = _scope_context_with_global_names(
            self.scope_context,
            self.global_names,
        )
        return lines

    def _parse_try_statement(self) -> list[str]:
        self._consume_identifier("try")
        control_name = self._next_generated_name("_gml_try_control")
        try_capture = _ControlFlowCapture(
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
        if self._match_identifier("catch"):
            catch_name = self._parse_catch_variable_name()
            had_catch_local = catch_name in self.local_names
            self.local_names.add(catch_name)
            self.control_flow_capture = try_capture
            try:
                catch_lines = self._parse_body()
            finally:
                self.control_flow_capture = parent_capture
                if not had_catch_local:
                    self.local_names.discard(catch_name)

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
            *_indent_lines(try_lines or ["pass"]),
            "\tbreak",
        ]

        if catch_lines is not None and catch_name is not None:
            gdscript_catch_name = _sanitize_gdscript_identifier(catch_name)
            lines.extend([
                f"if not GMRuntime.is_undefined({control_name}) and {control_name}[\"kind\"] == \"throw\":",
                f"\tvar {gdscript_catch_name} = GMRuntime.gml_exception_struct({control_name}[\"value\"])",
                f"\t{control_name} = GMRuntime.gml_undefined()",
                "\twhile true:",
                *[f"\t\t{line}" if line else "" for line in (catch_lines or ["pass"])],
                "\t\tbreak",
            ])

        if finally_lines is not None:
            lines.extend(finally_lines or ["pass"])

        lines.extend(_control_flow_dispatch_lines(control_name, try_capture, parent_capture))
        return lines

    def _parse_catch_variable_name(self) -> str:
        catch_tokens = self._read_condition_tokens()
        if len(catch_tokens) != 1 or catch_tokens[0].kind != "IDENT":
            raise GMLTranspileError("catch requires a variable name")
        catch_name = catch_tokens[0].value
        _validate_gml_identifier(catch_name)
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
        if self._match("{"):
            lines = self.parse(terminator="}")
            self._consume("}")
            return lines

        statement_tokens = self._read_do_until_statement_tokens()
        if not statement_tokens:
            return []
        return _transpile_statement(
            _tokens_to_source(statement_tokens),
            self.local_names,
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
        if self._match("{"):
            lines = self.parse(terminator="}")
            self._consume("}")
            return lines
        if self._at_end() or self._check("}"):
            return []
        return self._parse_statement()

    def _read_condition_tokens(self) -> list[_Token]:
        if self._match("("):
            return self._read_balanced_tokens("(", ")")

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
            _validate_gml_identifier(token.value)
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
            return _EOF
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
