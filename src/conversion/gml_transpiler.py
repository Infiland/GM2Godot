from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Literal, MutableSet, TypeAlias


_AssignmentOperator: TypeAlias = Literal[
    "??=",
    "<<=",
    ">>=",
    ":=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "=",
]

_IncrementDelta: TypeAlias = Literal[-1, 1]


class GMLTranspileError(ValueError):
    """Raised when the small GML subset transpiler cannot parse input."""


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


@dataclass(frozen=True)
class _Name:
    value: str


@dataclass(frozen=True)
class _Literal:
    value: str


@dataclass(frozen=True)
class _StringLiteral:
    value: str


@dataclass(frozen=True)
class _NumberLiteral:
    value: str
    is_float_like: bool


@dataclass(frozen=True)
class _Unary:
    operator: str
    operand: _Expression


@dataclass(frozen=True)
class _Binary:
    left: _Expression
    operator: str
    right: _Expression


@dataclass(frozen=True)
class _Ternary:
    condition: _Expression
    true_expr: _Expression
    false_expr: _Expression


@dataclass(frozen=True)
class _Call:
    callee: _Expression
    args: tuple[_Expression, ...]


@dataclass(frozen=True)
class _ArrayLiteral:
    elements: tuple[_Expression, ...]


@dataclass(frozen=True)
class _FunctionLiteral:
    name: str | None
    parameters: tuple[str, ...]
    body_lines: tuple[str, ...]


@dataclass(frozen=True)
class _StructLiteral:
    fields: tuple[tuple[str, _Expression], ...]


@dataclass(frozen=True)
class _Index:
    target: _Expression
    index: _Expression


@dataclass(frozen=True)
class _StructAccess:
    target: _Expression
    key: _Expression


@dataclass(frozen=True)
class _Member:
    target: _Expression
    member: str


@dataclass(frozen=True)
class _Grouped:
    expr: _Expression


_Expression: TypeAlias = (
    _Name
    | _Literal
    | _StringLiteral
    | _NumberLiteral
    | _Unary
    | _Binary
    | _Ternary
    | _Call
    | _ArrayLiteral
    | _FunctionLiteral
    | _StructLiteral
    | _Index
    | _StructAccess
    | _Member
    | _Grouped
)


_EOF = _Token("EOF", "")

_MULTI_CHAR_OPERATORS = (
    "??=",
    "<<=",
    ">>=",
    ":=",
    "??",
    "<=",
    ">=",
    "==",
    "!=",
    "&&",
    "||",
    "^^",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
)

_ASSIGNMENT_OPERATORS: tuple[_AssignmentOperator, ...] = (
    "??=",
    "<<=",
    ">>=",
    ":=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "=",
)

_BINARY_PRECEDENCE = {
    "??": 10,
    "or": 20,
    "||": 20,
    "^^": 20,
    "and": 30,
    "&&": 30,
    "|": 40,
    "^": 50,
    "&": 60,
    "=": 70,
    "==": 70,
    "!=": 70,
    "<": 70,
    "<=": 70,
    ">": 70,
    ">=": 70,
    "<<": 80,
    ">>": 80,
    "+": 90,
    "-": 90,
    "*": 100,
    "/": 100,
    "%": 100,
    "div": 100,
    "mod": 100,
}

_UNARY_PRECEDENCE = 110
_POSTFIX_PRECEDENCE = 120
_PRIMARY_PRECEDENCE = 130
_TERNARY_PRECEDENCE = 5
_GML_IDENTIFIER_MAX_LENGTH = 64
_GENERATED_IDENTIFIER_PREFIX = "_gml_"

_RIGHT_ASSOCIATIVE = {"??"}

_GDSCRIPT_RESERVED_IDENTIFIERS = frozenset({
    "as",
    "break",
    "class",
    "class_name",
    "const",
    "continue",
    "elif",
    "else",
    "enum",
    "extends",
    "false",
    "for",
    "func",
    "if",
    "in",
    "is",
    "match",
    "null",
    "pass",
    "return",
    "self",
    "signal",
    "static",
    "super",
    "true",
    "var",
    "void",
    "when",
    "while",
})
_GML_LITERAL_IDENTIFIERS = frozenset({
    "false",
    "null",
    "self",
    "super",
    "true",
})
_DIRECT_MEMBER_TARGETS = frozenset({
    "global",
    "other",
    "self",
    "super",
})

_BOOLEAN_RESULT_BINARY_OPERATORS = frozenset({
    "&&",
    "||",
    "^^",
    "and",
    "or",
    "=",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
})

_BOOLEAN_RESULT_FUNCTIONS = frozenset({
    "bool",
    "is_array",
    "is_bool",
    "is_callable",
    "is_infinity",
    "is_int32",
    "is_int64",
    "is_method",
    "is_nan",
    "is_numeric",
    "is_ptr",
    "is_real",
    "is_string",
    "is_struct",
    "struct_exists",
    "is_undefined",
    "keyboard_check",
})

_ARITHMETIC_RUNTIME_FUNCTIONS = {
    "+": "gml_add",
    "-": "gml_sub",
    "*": "gml_mul",
    "%": "gml_mod",
    "mod": "gml_mod",
}

_BITWISE_RUNTIME_FUNCTIONS = {
    "&": "gml_bit_and",
    "|": "gml_bit_or",
    "^": "gml_bit_xor",
    "<<": "gml_shift_left",
    ">>": "gml_shift_right",
}

_COMPOUND_RUNTIME_FUNCTIONS: dict[_AssignmentOperator, str] = {
    "+=": "gml_add",
    "-=": "gml_sub",
    "*=": "gml_mul",
    "/=": "gml_div",
    "%=": "gml_mod",
}

_OPERATOR_REPLACEMENTS = {
    "&&": "and",
    "||": "or",
    "=": "==",
    "mod": "%",
}

_NAME_REPLACEMENTS = {
    "infinity": "INF",
    "NaN": "NAN",
    "nan": "NAN",
    "pointer_invalid": "GMRuntime.gml_pointer_invalid()",
    "pointer_null": "GMRuntime.gml_pointer_null()",
    "undefined": "GMRuntime.gml_undefined()",
}

_BLOCK_DELIMITER_REPLACEMENTS = {
    "begin": "{",
    "end": "}",
}

_INSTANCE_NAME_REPLACEMENTS = {
    "x": "position.x",
    "y": "position.y",
}

_BUILTIN_INSTANCE_VARIABLES = frozenset({
    *_INSTANCE_NAME_REPLACEMENTS,
    "sprite_index",
    "image_index",
})

_VIRTUAL_KEY_ACTIONS = {
    "vk_left": "ui_left",
    "vk_right": "ui_right",
    "vk_up": "ui_up",
    "vk_down": "ui_down",
}

_VIRTUAL_KEY_CONSTANTS = {
    "vk_shift": "KEY_SHIFT",
}

_RUNTIME_FUNCTIONS = {
    "int64": "gml_int64",
    "is_array": "is_array",
    "is_bool": "is_bool",
    "is_callable": "is_callable",
    "is_infinity": "is_infinity",
    "is_int32": "is_int32",
    "is_int64": "is_int64",
    "is_method": "is_method",
    "is_nan": "is_nan_value",
    "is_numeric": "is_numeric",
    "is_ptr": "is_ptr",
    "is_real": "is_real",
    "is_string": "is_string",
    "is_struct": "is_struct",
    "is_undefined": "is_undefined",
    "real": "gml_real",
    "ptr": "gml_ptr",
    "sqrt": "gml_sqrt",
    "typeof": "gml_typeof",
    "string": "gml_string",
    "bool": "gml_bool",
}

_STRUCT_RUNTIME_FUNCTIONS = {
    "struct_exists": "gml_struct_exists",
    "struct_get": "gml_struct_get",
    "struct_get_names": "gml_struct_get_names",
    "struct_names_count": "gml_struct_names_count",
    "struct_set": "gml_struct_set",
    "struct_remove": "gml_struct_remove",
}

_VARIABLE_RUNTIME_FUNCTIONS = {
    "variable_clone": "gml_variable_clone",
}


def transpile_gml_expression(source: str, local_names: Iterable[str] | None = None) -> str:
    """Transpile a single GML expression to a GDScript expression."""
    parser = _ExpressionParser(_expression_tokens(source))
    expr = parser.parse()
    return _emit_expression(expr, _normalize_local_names(local_names))[0]


def transpile_gml_condition(source: str, local_names: Iterable[str] | None = None) -> str:
    """Transpile a GML condition using GameMaker truthiness semantics."""
    parser = _ExpressionParser(_expression_tokens(source))
    expr = parser.parse()
    return _emit_truthy_expression(expr, _normalize_local_names(local_names))


def _parse_gml_expression(source: str) -> _Expression:
    parser = _ExpressionParser(_expression_tokens(source))
    return parser.parse()


def transpile_gml_code(
    source: str,
    indent: str = "\t",
    instance_variables: MutableSet[str] | None = None,
) -> str:
    """Transpile supported GML statements to GDScript."""
    parser = _StatementParser(
        _tokenize(_strip_comments(source)),
        instance_variables=instance_variables,
    )
    lines = parser.parse()

    if not lines:
        return f"{indent}pass"

    return "\n".join(f"{indent}{line}" if line else "" for line in lines)


class _ExpressionParser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def parse(self) -> _Expression:
        expr = self._parse_expression()
        if not self._at_end():
            raise GMLTranspileError(f"Unexpected token: {self._peek().value}")
        return expr

    def _parse_expression(self, min_precedence: int = 0) -> _Expression:
        left = self._parse_unary()

        while True:
            if self._match("?"):
                if _TERNARY_PRECEDENCE < min_precedence:
                    self.position -= 1
                    break
                true_expr = self._parse_expression()
                self._consume(":")
                false_expr = self._parse_expression(_TERNARY_PRECEDENCE)
                left = _Ternary(left, true_expr, false_expr)
                continue

            operator = self._current_operator()
            if operator is None:
                break

            precedence = _BINARY_PRECEDENCE[operator]
            if precedence < min_precedence:
                break

            self._advance()
            next_precedence = precedence if operator in _RIGHT_ASSOCIATIVE else precedence + 1
            right = self._parse_expression(next_precedence)
            left = _Binary(left, operator, right)

        return left

    def _parse_unary(self) -> _Expression:
        operator = self._current_unary_operator()
        if operator in ("+", "-", "!", "not", "~"):
            self._advance()
            return _Unary(operator, self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self) -> _Expression:
        expr = self._parse_primary()
        while True:
            if self._match("("):
                args: list[_Expression] = []
                if not self._check(")"):
                    while True:
                        args.append(self._parse_expression())
                        if not self._match(","):
                            break
                self._consume(")")
                expr = _Call(expr, tuple(args))
                continue

            if self._match("["):
                if self._match("$"):
                    key = self._parse_expression()
                    self._consume("]")
                    expr = _StructAccess(expr, key)
                    continue
                index = self._parse_expression()
                self._consume("]")
                expr = _Index(expr, index)
                continue

            if self._match("."):
                member = self._consume_identifier()
                expr = _Member(expr, member)
                continue

            break

        return expr

    def _parse_primary(self) -> _Expression:
        token = self._advance()
        if token.kind == "NUMBER":
            return _NumberLiteral(token.value, _is_float_like_number(token.value))
        if token.kind == "STRING":
            return _StringLiteral(token.value)
        if token.kind == "IDENT" and token.value == "function":
            return self._parse_function_literal()
        if token.kind == "IDENT":
            return _Name(_NAME_REPLACEMENTS.get(token.value, token.value))
        if token.value == "[":
            elements: list[_Expression] = []
            if not self._check("]"):
                while True:
                    elements.append(self._parse_expression())
                    if not self._match(","):
                        break
                    if self._check("]"):
                        break
            self._consume("]")
            return _ArrayLiteral(tuple(elements))
        if token.value == "{":
            fields: list[tuple[str, _Expression]] = []
            if not self._check("}"):
                while True:
                    field_name = self._consume_identifier()
                    if self._match(":"):
                        field_value = self._parse_expression()
                    else:
                        field_value = _Name(_NAME_REPLACEMENTS.get(field_name, field_name))
                    fields.append((field_name, field_value))
                    if not self._match(","):
                        break
                    if self._check("}"):
                        break
            self._consume("}")
            return _StructLiteral(tuple(fields))
        if token.value == "(":
            expr = self._parse_expression()
            self._consume(")")
            return _Grouped(expr)
        raise GMLTranspileError(f"Expected expression, got: {token.value}")

    def _parse_function_literal(self) -> _Expression:
        name = None
        if self._peek().kind == "IDENT":
            name = self._consume_identifier()

        parameters: list[str] = []
        self._consume("(")
        if not self._check(")"):
            while True:
                parameters.append(self._consume_identifier())
                if not self._match(","):
                    break
        self._consume(")")
        self._consume("{")
        body_tokens = self._read_balanced_tokens("{", "}")
        body_parser = _StatementParser(body_tokens, local_names=parameters)
        body_lines = body_parser.parse()
        return _FunctionLiteral(name, tuple(parameters), tuple(body_lines or ["pass"]))

    def _current_operator(self) -> str | None:
        token = self._peek()
        if token.kind == "IDENT" and token.value in _BINARY_PRECEDENCE:
            return token.value
        if token.value in _BINARY_PRECEDENCE:
            return token.value
        return None

    def _current_unary_operator(self) -> str | None:
        token = self._peek()
        if token.kind == "IDENT" and token.value == "not":
            return token.value
        if token.value in ("+", "-", "!", "~"):
            return token.value
        return None

    def _match(self, value: str) -> bool:
        if self._check(value):
            self.position += 1
            return True
        return False

    def _consume(self, value: str) -> None:
        if not self._match(value):
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self) -> str:
        token = self._advance()
        if token.kind != "IDENT":
            raise GMLTranspileError(f"Expected identifier, got: {token.value}")
        _validate_gml_identifier(token.value)
        return token.value

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

        raise GMLTranspileError(f"Expected '{closer}'")

    def _check(self, value: str) -> bool:
        return self._peek().value == value

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


class _StatementParser:
    def __init__(
        self,
        tokens: list[_Token],
        local_names: Iterable[str] | None = None,
        instance_variables: MutableSet[str] | None = None,
        loop_depth: int = 0,
        continue_depth: int = 0,
        generated_counter: list[int] | None = None,
    ) -> None:
        self.tokens = tokens
        self.position = 0
        self.local_names = set(local_names or [])
        self.instance_variables = instance_variables
        self.loop_depth = loop_depth
        self.continue_depth = continue_depth
        self.generated_counter = generated_counter if generated_counter is not None else [0]

    def parse(self, terminator: str | None = None) -> list[str]:
        lines: list[str] = []
        while not self._at_end() and not self._check(terminator):
            if self._match(";") or self._match("\n"):
                continue
            lines.extend(self._parse_statement())
        return lines

    def _parse_statement(self) -> list[str]:
        if self._check_identifier("if"):
            return self._parse_if_statement()
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
        )

    def _parse_if_statement(self) -> list[str]:
        self._consume_identifier("if")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected if condition")

        condition = transpile_gml_condition(
            _tokens_to_source(condition_tokens),
            local_names=self.local_names,
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

    def _parse_while_statement(self) -> list[str]:
        self._consume_identifier("while")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected while condition")

        condition = transpile_gml_condition(
            _tokens_to_source(condition_tokens),
            local_names=self.local_names,
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
                )
            )

        condition = (
            transpile_gml_condition(condition_source, local_names=self.local_names)
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
        expression = transpile_gml_expression(
            _tokens_to_source(expression_tokens),
            local_names=self.local_names,
        )
        sections = self._parse_switch_sections()
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

        lines = [
            f"var {switch_value} = {expression}",
            f"var {switch_matched} = false",
            f"var {switch_has_case} = {has_case_expression}",
            "while true:",
        ]
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
        return lines

    def _parse_switch_sections(self) -> list[tuple[str, str | None, list[str]]]:
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
                )
                body_tokens = self._read_switch_section_body_tokens()
                sections.append(("case", label, self._parse_switch_section_body(body_tokens)))
                continue
            if self._match_identifier("default"):
                self._consume(":")
                body_tokens = self._read_switch_section_body_tokens()
                sections.append(("default", None, self._parse_switch_section_body(body_tokens)))
                continue
            raise GMLTranspileError(f"Expected switch case or default, got: {self._peek().value}")

        self._consume("}")
        return sections

    def _parse_switch_section_body(self, body_tokens: list[_Token]) -> list[str]:
        parser = _StatementParser(
            body_tokens,
            local_names=self.local_names,
            instance_variables=self.instance_variables,
            loop_depth=self.loop_depth + 1,
            continue_depth=self.continue_depth,
            generated_counter=self.generated_counter,
        )
        lines = parser.parse()
        self.local_names.update(parser.local_names)
        return lines

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

        raise GMLTranspileError(f"Expected '{closer}'")

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
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self, value: str) -> None:
        if not self._match_identifier(value):
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _check(self, value: str | None) -> bool:
        if value is None:
            return False
        return self._peek().value == value

    def _check_identifier(self, value: str) -> bool:
        token = self._peek()
        return token.kind == "IDENT" and token.value == value

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


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        char = source[index]

        if char in "\r\n":
            if char == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
                index += 1
            tokens.append(_Token("NEWLINE", "\n"))
            index += 1
            continue

        if char.isspace():
            index += 1
            continue

        if char.isdigit() or (char == "." and index + 1 < len(source) and source[index + 1].isdigit()):
            number_end = _read_number(source, index)
            tokens.append(_Token("NUMBER", source[index:number_end].replace("_", "")))
            index = number_end
            continue

        if char == '"' or char == "'":
            tokens.append(_Token("STRING", _read_string(source, index)))
            index += len(tokens[-1].value)
            continue

        if char == "$":
            next_char = source[index + 1] if index + 1 < len(source) else ""
            if next_char.lower() in "0123456789abcdef" or next_char == "_":
                hex_end = _read_hex_number(source, index + 1)
                tokens.append(_Token("NUMBER", f"0x{source[index + 1:hex_end].replace('_', '')}"))
                index = hex_end
            else:
                tokens.append(_Token("OP", char))
                index += 1
            continue

        if char == "#":
            color_literal, color_end = _read_hash_color_literal(source, index)
            tokens.append(_Token("NUMBER", color_literal))
            index = color_end
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                index += 1
            identifier = source[start:index]
            _validate_gml_identifier(identifier)
            block_delimiter = _BLOCK_DELIMITER_REPLACEMENTS.get(identifier)
            if block_delimiter is not None:
                tokens.append(_Token("OP", block_delimiter))
            else:
                tokens.append(_Token("IDENT", identifier))
            continue

        matched_operator = None
        for operator in _MULTI_CHAR_OPERATORS:
            if source.startswith(operator, index):
                matched_operator = operator
                break
        if matched_operator is not None:
            tokens.append(_Token("OP", matched_operator))
            index += len(matched_operator)
            continue

        if char in "+-*/%&|^~!=<>()[]{}?:,.;.":
            tokens.append(_Token("OP", char))
            index += 1
            continue

        raise GMLTranspileError(f"Unexpected character: {char}")

    tokens.append(_EOF)
    return tokens


def _expression_tokens(source: str) -> list[_Token]:
    return [token for token in _tokenize(source) if token.kind != "NEWLINE"]


def _read_number(source: str, start: int) -> int:
    if source.startswith(("0b", "0B"), start):
        return _read_binary_number(source, start)

    if source.startswith(("0x", "0X"), start):
        return _read_hex_number(source, start + 2)

    return _read_decimal_number(source, start)


def _read_decimal_number(source: str, start: int) -> int:
    index = start
    if source[index] == ".":
        index += 1
        index, saw_fraction_digit = _read_separated_digits(
            source,
            index,
            "0123456789",
            "numeric",
        )
        if not saw_fraction_digit:
            raise GMLTranspileError("Malformed numeric literal")
        return index

    index, _saw_integer_digit = _read_separated_digits(
        source,
        index,
        "0123456789",
        "numeric",
    )
    if index < len(source) and source[index] == ".":
        index += 1
        if index < len(source) and source[index] == "_":
            raise GMLTranspileError("Malformed numeric literal")
        index, _saw_fraction_digit = _read_separated_digits(
            source,
            index,
            "0123456789",
            "numeric",
        )

    return index


def _read_hex_number(source: str, start: int) -> int:
    index, saw_digit = _read_separated_digits(
        source,
        start,
        "0123456789abcdef",
        "hexadecimal",
    )

    if not saw_digit:
        raise GMLTranspileError("Malformed hexadecimal literal")

    if index < len(source) and source[index].isalnum():
        raise GMLTranspileError(f"Invalid hexadecimal literal digit: {source[index]}")

    return index


def _read_hash_color_literal(source: str, start: int) -> tuple[str, int]:
    hex_start = start + 1
    hex_end = hex_start + 6
    if hex_end > len(source):
        raise GMLTranspileError("Malformed hash color literal")

    value = source[hex_start:hex_end]
    if any(char.lower() not in "0123456789abcdef" for char in value):
        raise GMLTranspileError("Malformed hash color literal")

    if hex_end < len(source) and source[hex_end].isalnum():
        raise GMLTranspileError(f"Invalid hash color literal digit: {source[hex_end]}")

    red = value[0:2]
    green = value[2:4]
    blue = value[4:6]
    return f"0x{blue}{green}{red}".lower(), hex_end


def _read_binary_number(source: str, start: int) -> int:
    index, saw_digit = _read_separated_digits(
        source,
        start + 2,
        "01",
        "binary",
    )

    if not saw_digit:
        raise GMLTranspileError("Malformed binary literal")

    if index < len(source) and source[index].isalnum():
        raise GMLTranspileError(f"Invalid binary literal digit: {source[index]}")

    return index


def _read_separated_digits(
    source: str,
    start: int,
    valid_digits: str,
    literal_name: str,
) -> tuple[int, bool]:
    index = start
    saw_digit = False
    previous_was_digit = False

    while index < len(source):
        char = source[index]
        if char.lower() in valid_digits:
            saw_digit = True
            previous_was_digit = True
            index += 1
            continue

        if char == "_":
            next_char = source[index + 1] if index + 1 < len(source) else ""
            if (
                not previous_was_digit
                or next_char == ""
                or next_char.lower() not in valid_digits
            ):
                raise GMLTranspileError(f"Malformed {literal_name} literal")
            previous_was_digit = False
            index += 1
            continue

        break

    return index, saw_digit


def _is_float_like_number(value: str) -> bool:
    return "." in value


def _read_string(source: str, start: int) -> str:
    quote = source[start]
    index = start + 1
    escaped = False
    while index < len(source):
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return source[start:index + 1]
        index += 1
    raise GMLTranspileError("Unterminated string literal")


def _normalize_local_names(local_names: Iterable[str] | None) -> frozenset[str]:
    return frozenset(local_names or [])


def _tokens_to_source(tokens: Iterable[_Token]) -> str:
    return " ".join(token.value for token in tokens if token.kind not in ("EOF", "NEWLINE"))


def _split_top_level_tokens(tokens: Iterable[_Token], separator: str) -> list[list[_Token]]:
    parts: list[list[_Token]] = [[]]
    depth = 0
    for token in tokens:
        if token.value in "([{":
            depth += 1
        elif token.value in ")]}" and depth > 0:
            depth -= 1

        if depth == 0 and token.value == separator:
            parts.append([])
            continue
        parts[-1].append(token)
    return parts


def _indent_lines(lines: Iterable[str]) -> list[str]:
    return [f"\t{line}" if line else "" for line in lines]


def _insert_lines_before_continue(lines: Iterable[str], inserted_lines: Iterable[str]) -> list[str]:
    inserted = list(inserted_lines)
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip("\t")
        if stripped == "continue":
            indentation = line[: len(line) - len(stripped)]
            result.extend(f"{indentation}{inserted_line}" for inserted_line in inserted)
        result.append(line)
    return result


def _insert_until_check_before_continue(lines: Iterable[str], condition: str) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip("\t")
        if stripped == "continue":
            indentation = line[: len(line) - len(stripped)]
            result.append(f"{indentation}if {condition}:")
            result.append(f"{indentation}\tbreak")
        result.append(line)
    return result


def _emit_expression(
    expr: _Expression,
    local_names: Iterable[str] | None = None,
) -> tuple[str, int]:
    local_names = _normalize_local_names(local_names)
    if isinstance(expr, _Literal | _StringLiteral | _NumberLiteral):
        return expr.value, _PRIMARY_PRECEDENCE
    if isinstance(expr, _Name):
        value = expr.value
        is_local = value in local_names
        if not is_local and value in _GML_LITERAL_IDENTIFIERS:
            return value, _PRIMARY_PRECEDENCE
        if not is_local:
            value = _INSTANCE_NAME_REPLACEMENTS.get(value, value)
        value = _sanitize_gdscript_identifier(value)
        return value, _PRIMARY_PRECEDENCE
    if isinstance(expr, _Grouped):
        return f"({_emit_expression(expr.expr, local_names)[0]})", _PRIMARY_PRECEDENCE
    if isinstance(expr, _Unary):
        if expr.operator == "!":
            return f"not {_emit_truthy_expression(expr.operand, local_names)}", _UNARY_PRECEDENCE
        if expr.operator == "not":
            return f"not {_emit_truthy_expression(expr.operand, local_names)}", _UNARY_PRECEDENCE
        if expr.operator == "~":
            operand = _emit_expression(expr.operand, local_names)[0]
            return f"GMRuntime.gml_bit_not({operand})", _POSTFIX_PRECEDENCE
        operand = _emit_child(expr.operand, _UNARY_PRECEDENCE, local_names=local_names)
        return f"{expr.operator}{operand}", _UNARY_PRECEDENCE
    if isinstance(expr, _Binary):
        return _emit_binary(expr, local_names)
    if isinstance(expr, _Ternary):
        condition = _emit_truthy_expression(expr.condition, local_names)
        true_expr = _emit_child(expr.true_expr, _TERNARY_PRECEDENCE, local_names=local_names)
        false_expr = _emit_child(expr.false_expr, _TERNARY_PRECEDENCE, local_names=local_names)
        return f"{true_expr} if {condition} else {false_expr}", _TERNARY_PRECEDENCE
    if isinstance(expr, _Call):
        builtin_call = _emit_builtin_call(expr, local_names)
        if builtin_call is not None:
            return builtin_call, _POSTFIX_PRECEDENCE
        callee = _emit_child(expr.callee, _POSTFIX_PRECEDENCE, local_names=local_names)
        args = ", ".join(_emit_expression(arg, local_names)[0] for arg in expr.args)
        return f"{callee}({args})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _ArrayLiteral):
        elements = ", ".join(_emit_expression(element, local_names)[0] for element in expr.elements)
        return f"[{elements}]", _PRIMARY_PRECEDENCE
    if isinstance(expr, _FunctionLiteral):
        name = f" {_sanitize_gdscript_identifier(expr.name)}" if expr.name is not None else ""
        parameters = ", ".join(_sanitize_gdscript_identifier(parameter) for parameter in expr.parameters)
        body = "; ".join(expr.body_lines)
        return f"func{name}({parameters}): {body}", _PRIMARY_PRECEDENCE
    if isinstance(expr, _StructLiteral):
        fields = ", ".join(
            f"{json.dumps(field_name)}: {_emit_expression(field_value, local_names)[0]}"
            for field_name, field_value in expr.fields
        )
        return f"GMRuntime.gml_struct({{{fields}}})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _Index):
        target = _emit_expression(expr.target, local_names)[0]
        index = _emit_expression(expr.index, local_names)[0]
        return f"GMRuntime.gml_array_get({target}, {index})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _StructAccess):
        target = _emit_expression(expr.target, local_names)[0]
        key = _emit_expression(expr.key, local_names)[0]
        return f"GMRuntime.gml_struct_get({target}, {key})", _POSTFIX_PRECEDENCE
    if _uses_direct_member_access(expr):
        target = _emit_child(expr.target, _POSTFIX_PRECEDENCE, local_names=local_names)
        return f"{target}.{_sanitize_gdscript_identifier(expr.member)}", _POSTFIX_PRECEDENCE
    target = _emit_child(expr.target, _POSTFIX_PRECEDENCE, local_names=local_names)
    return f"GMRuntime.gml_struct_get({target}, {json.dumps(expr.member)})", _POSTFIX_PRECEDENCE


def _uses_direct_member_access(expr: _Member) -> bool:
    return isinstance(expr.target, _Name) and expr.target.value in _DIRECT_MEMBER_TARGETS


def _emit_builtin_call(expr: _Call, local_names: Iterable[str]) -> str | None:
    if isinstance(expr.callee, _Name) and expr.callee.value == "keyboard_check" and len(expr.args) == 1:
        key = expr.args[0]
        if isinstance(key, _Name) and key.value in _VIRTUAL_KEY_ACTIONS:
            return f'Input.is_action_pressed("{_VIRTUAL_KEY_ACTIONS[key.value]}")'
        if isinstance(key, _Name) and key.value in _VIRTUAL_KEY_CONSTANTS:
            return f"Input.is_key_pressed({_VIRTUAL_KEY_CONSTANTS[key.value]})"
    if isinstance(expr.callee, _Name) and expr.callee.value in _STRUCT_RUNTIME_FUNCTIONS:
        args = ", ".join(_emit_expression(arg, local_names)[0] for arg in expr.args)
        return f"GMRuntime.{_STRUCT_RUNTIME_FUNCTIONS[expr.callee.value]}({args})"
    if isinstance(expr.callee, _Name) and expr.callee.value in _VARIABLE_RUNTIME_FUNCTIONS:
        args = ", ".join(_emit_expression(arg, local_names)[0] for arg in expr.args)
        return f"GMRuntime.{_VARIABLE_RUNTIME_FUNCTIONS[expr.callee.value]}({args})"
    if (
        isinstance(expr.callee, _Name)
        and expr.callee.value in _RUNTIME_FUNCTIONS
        and len(expr.args) == 1
    ):
        arg = _emit_expression(expr.args[0], local_names)[0]
        return f"GMRuntime.{_RUNTIME_FUNCTIONS[expr.callee.value]}({arg})"
    return None


def _emit_binary(expr: _Binary, local_names: Iterable[str]) -> tuple[str, int]:
    operator = _OPERATOR_REPLACEMENTS.get(expr.operator, expr.operator)

    if expr.operator in ("&&", "and", "||", "or"):
        operator = "and" if expr.operator in ("&&", "and") else "or"
        left = _emit_truthy_expression(expr.left, local_names)
        right = _emit_truthy_expression(expr.right, local_names)
        return f"{left} {operator} {right}", _BINARY_PRECEDENCE[expr.operator]

    if expr.operator == "^^":
        left = _emit_truthy_expression(expr.left, local_names)
        right = _emit_truthy_expression(expr.right, local_names)
        return f"{left} != {right}", _BINARY_PRECEDENCE[expr.operator]

    if expr.operator == "div":
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_expression(expr.right, local_names)[0]
        return f"GMRuntime.gml_int_div({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator == "??":
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_child(expr.right, _TERNARY_PRECEDENCE, local_names=local_names)
        return f"{left} if not GMRuntime.gml_is_nullish({left}) else {right}", _TERNARY_PRECEDENCE

    if expr.operator in ("=", "==", "!=") and (
        _contains_gml_undefined(expr.left)
        or _contains_gml_undefined(expr.right)
        or _contains_gml_nan(expr.left)
        or _contains_gml_nan(expr.right)
        or _contains_gml_pointer(expr.left)
        or _contains_gml_pointer(expr.right)
    ):
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_expression(expr.right, local_names)[0]
        helper = "gml_ne" if expr.operator == "!=" else "gml_eq"
        return f"GMRuntime.{helper}({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator == "/":
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_expression(expr.right, local_names)[0]
        return f"GMRuntime.gml_div({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator in _ARITHMETIC_RUNTIME_FUNCTIONS:
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_expression(expr.right, local_names)[0]
        return f"GMRuntime.{_ARITHMETIC_RUNTIME_FUNCTIONS[expr.operator]}({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator in _BITWISE_RUNTIME_FUNCTIONS:
        left = _emit_expression(expr.left, local_names)[0]
        right = _emit_expression(expr.right, local_names)[0]
        return f"GMRuntime.{_BITWISE_RUNTIME_FUNCTIONS[expr.operator]}({left}, {right})", _POSTFIX_PRECEDENCE

    precedence = _BINARY_PRECEDENCE[expr.operator]
    left = _emit_child(expr.left, precedence, local_names=local_names)
    right = _emit_child(
        expr.right,
        precedence,
        is_right_child=True,
        parent_operator=expr.operator,
        local_names=local_names,
    )
    return f"{left} {operator} {right}", precedence


def _contains_gml_undefined(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value == "GMRuntime.gml_undefined()"
    if isinstance(expr, _Grouped):
        return _contains_gml_undefined(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_undefined(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_undefined(expr.left) or _contains_gml_undefined(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_undefined(expr.condition)
            or _contains_gml_undefined(expr.true_expr)
            or _contains_gml_undefined(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return _contains_gml_undefined(expr.callee) or any(
            _contains_gml_undefined(arg) for arg in expr.args
        )
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_undefined(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_undefined(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.key)
    if isinstance(expr, _Member):
        return _contains_gml_undefined(expr.target)
    return False


def _contains_gml_nan(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value == "NAN"
    if isinstance(expr, _Grouped):
        return _contains_gml_nan(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_nan(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_nan(expr.left) or _contains_gml_nan(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_nan(expr.condition)
            or _contains_gml_nan(expr.true_expr)
            or _contains_gml_nan(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return _contains_gml_nan(expr.callee) or any(_contains_gml_nan(arg) for arg in expr.args)
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_nan(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_nan(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.key)
    if isinstance(expr, _Member):
        return _contains_gml_nan(expr.target)
    return False


def _contains_gml_pointer(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value in ("GMRuntime.gml_pointer_null()", "GMRuntime.gml_pointer_invalid()")
    if isinstance(expr, _Grouped):
        return _contains_gml_pointer(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_pointer(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_pointer(expr.left) or _contains_gml_pointer(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_pointer(expr.condition)
            or _contains_gml_pointer(expr.true_expr)
            or _contains_gml_pointer(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return (
            isinstance(expr.callee, _Name)
            and expr.callee.value == "ptr"
        ) or any(_contains_gml_pointer(arg) for arg in expr.args)
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_pointer(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_pointer(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.key)
    if isinstance(expr, _Member):
        return _contains_gml_pointer(expr.target)
    return False


def _emit_truthy_expression(expr: _Expression, local_names: Iterable[str]) -> str:
    if _emits_boolean_result(expr):
        return _emit_expression(expr, local_names)[0]
    return _gml_bool_call(_emit_expression(expr, local_names)[0])


def _emits_boolean_result(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value in ("true", "false")
    if isinstance(expr, _Grouped):
        return _emits_boolean_result(expr.expr)
    if isinstance(expr, _Unary):
        return expr.operator in ("!", "not")
    if isinstance(expr, _Binary):
        return expr.operator in _BOOLEAN_RESULT_BINARY_OPERATORS
    if isinstance(expr, _Call) and isinstance(expr.callee, _Name):
        return expr.callee.value in _BOOLEAN_RESULT_FUNCTIONS
    return False


def _gml_bool_call(expression: str) -> str:
    return f"GMRuntime.gml_bool({expression})"


def _emit_child(
    expr: _Expression,
    parent_precedence: int,
    is_right_child: bool = False,
    parent_operator: str | None = None,
    local_names: Iterable[str] | None = None,
) -> str:
    text, precedence = _emit_expression(expr, local_names)
    needs_parentheses = precedence < parent_precedence
    if is_right_child and precedence == parent_precedence and parent_operator not in _RIGHT_ASSOCIATIVE:
        needs_parentheses = True
    if needs_parentheses:
        return f"({text})"
    return text


def _strip_comments(source: str) -> str:
    result: list[str] = []
    index = 0
    in_string: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]

        if in_string is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char == '"' or char == "'":
            in_string = char
            result.append(char)
            index += 1
            continue

        if source.startswith("//", index):
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue

        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end == -1:
                break
            index = end + 2
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _split_statements(source: str) -> list[str]:  # pyright: ignore[reportUnusedFunction]
    statements: list[str] = []
    start = 0
    depth = 0
    in_string: str | None = None
    escaped = False

    for index, char in enumerate(source):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char == '"' or char == "'":
            in_string = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            continue
        if char == ";" and depth == 0:
            statements.append(source[start:index])
            start = index + 1

    trailing = source[start:].strip()
    if trailing:
        statements.append(trailing)
    return [statement for statement in statements if statement.strip()]


def _transpile_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    loop_depth: int = 0,
    continue_depth: int = 0,
) -> list[str]:
    if not statement:
        return []

    if local_names is None:
        local_names = set()

    if statement == "return":
        return ["return"]
    if statement.startswith("return "):
        return [f"return {transpile_gml_expression(statement[7:].strip(), local_names)}"]
    if statement == "break":
        if loop_depth <= 0:
            raise GMLTranspileError("break used outside a loop")
        return ["break"]
    if statement == "continue":
        if continue_depth <= 0:
            raise GMLTranspileError("continue used outside a loop")
        return ["continue"]
    if statement == "exit":
        return ["return"]

    if statement.startswith("delete "):
        target_source = statement[7:].strip()
        target_expr = _parse_gml_expression(target_source)
        if not isinstance(target_expr, _Name):
            raise GMLTranspileError("delete can only be used with variables")
        target = _emit_expression(target_expr, local_names)[0]
        return [f"{target} = GMRuntime.gml_undefined()"]

    if statement.startswith("var "):
        return _transpile_var_statement(statement[4:].strip(), local_names)

    increment = _parse_increment_statement(statement)
    if increment is not None:
        target, delta = increment
        helper = "gml_add" if delta > 0 else "gml_sub"
        target_expr = _parse_gml_expression(target)
        struct_target = _struct_assignment_parts(target_expr, local_names)
        if struct_target is not None:
            container, key = struct_target
            current_value = f"GMRuntime.gml_struct_get({container}, {key})"
            return [
                f"GMRuntime.gml_struct_set({container}, {key}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        target = _emit_expression(target_expr, local_names)[0]
        return [f"{target} = GMRuntime.{helper}({target}, 1)"]

    assignment = _split_assignment(statement)
    if assignment is not None:
        target, operator, value = assignment
        if _split_assignment(value) is not None:
            raise GMLTranspileError("Chained assignments are not supported")
        _record_instance_assignment(target, local_names, instance_variables)
        target_expr = _parse_gml_expression(target)
        target = _emit_expression(target_expr, local_names)[0]
        value = transpile_gml_expression(value, local_names)
        if isinstance(target_expr, _Index):
            container = _emit_expression(target_expr.target, local_names)[0]
            index = _emit_expression(target_expr.index, local_names)[0]
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_array_set({container}, {index}, {value})"]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_array_get({container}, {index})"
                return [
                    f"GMRuntime.gml_array_set({container}, {index}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
        struct_target = _struct_assignment_parts(target_expr, local_names)
        if struct_target is not None:
            container, key = struct_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_struct_set({container}, {key}, {value})"]
            if operator == "??=":
                current_value = f"GMRuntime.gml_struct_get({container}, {key})"
                return [
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_struct_set({container}, {key}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_struct_get({container}, {key})"
                return [
                    f"GMRuntime.gml_struct_set({container}, {key}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported struct member assignment operator")
        if operator == "??=":
            return [f"if GMRuntime.gml_is_nullish({target}):", f"\t{target} = {value}"]
        if operator in _COMPOUND_RUNTIME_FUNCTIONS:
            return [f"{target} = GMRuntime.{_COMPOUND_RUNTIME_FUNCTIONS[operator]}({target}, {value})"]
        if operator == ":=":
            return [f"{target} = {value}"]
        return [f"{target} {operator} {value}"]

    return [transpile_gml_expression(statement, local_names)]


def _struct_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
) -> tuple[str, str] | None:
    if isinstance(target_expr, _StructAccess):
        container = _emit_expression(target_expr.target, local_names)[0]
        key = _emit_expression(target_expr.key, local_names)[0]
        return container, key
    if isinstance(target_expr, _Member) and not _uses_direct_member_access(target_expr):
        container = _emit_expression(target_expr.target, local_names)[0]
        return container, json.dumps(target_expr.member)
    return None


def _record_instance_assignment(
    target: str,
    local_names: Iterable[str],
    instance_variables: MutableSet[str] | None,
) -> None:
    if instance_variables is None:
        return

    tokens = _expression_tokens(target.strip())
    if len(tokens) != 2 or tokens[0].kind != "IDENT" or tokens[1].kind != "EOF":
        return

    name = tokens[0].value
    if name in local_names or name in _BUILTIN_INSTANCE_VARIABLES:
        return
    instance_variables.add(name)


def _transpile_var_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
) -> list[str]:
    lines: list[str] = []
    if local_names is None:
        local_names = set()
    for declaration in _split_top_level(statement, ","):
        declaration = declaration.strip()
        if not declaration:
            continue
        assignment = _split_assignment(declaration)
        if assignment is None:
            name = declaration.strip()
            _validate_gml_identifier(name)
            lines.append(f"var {_sanitize_gdscript_identifier(name)} = GMRuntime.gml_undefined()")
            local_names.add(name)
            continue
        name, operator, value = assignment
        if operator not in ("=", ":="):
            raise GMLTranspileError("Variable declarations only support simple assignments")
        name = name.strip()
        _validate_gml_identifier(name)
        lines.append(
            f"var {_sanitize_gdscript_identifier(name)} = {transpile_gml_expression(value, local_names)}"
        )
        local_names.add(name)
    return lines


def _sanitize_gdscript_identifier(name: str) -> str:
    if not _is_plain_identifier(name):
        return name
    if name in _GDSCRIPT_RESERVED_IDENTIFIERS:
        return f"{name}_"
    if name.startswith(_GENERATED_IDENTIFIER_PREFIX):
        return f"gml_user{name}"
    return name


def _is_plain_identifier(name: str) -> bool:
    if not name:
        return False
    return (name[0].isalpha() or name[0] == "_") and all(
        char.isalnum() or char == "_" for char in name
    )


def _validate_gml_identifier(name: str) -> None:
    if not name:
        raise GMLTranspileError("Expected identifier name")
    if len(name) > _GML_IDENTIFIER_MAX_LENGTH:
        raise GMLTranspileError("GML identifier exceeds 64 characters")
    if not (name[0].isalpha() or name[0] == "_"):
        raise GMLTranspileError("GML identifier must start with a letter or underscore")
    if not all(char.isalnum() or char == "_" for char in name):
        raise GMLTranspileError("GML identifier can only contain letters, numbers, and underscores")


def _parse_increment_statement(statement: str) -> tuple[str, _IncrementDelta] | None:
    stripped = statement.strip()
    if stripped.endswith("++"):
        return stripped[:-2].strip(), 1
    if stripped.endswith("--"):
        return stripped[:-2].strip(), -1
    if stripped.startswith("++"):
        return stripped[2:].strip(), 1
    if stripped.startswith("--"):
        return stripped[2:].strip(), -1
    return None


def _split_assignment(statement: str) -> tuple[str, _AssignmentOperator, str] | None:
    depth = 0
    in_string: str | None = None
    escaped = False
    index = 0

    while index < len(statement):
        char = statement[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char == '"' or char == "'":
            in_string = char
            index += 1
            continue
        if char in "([{":
            depth += 1
            index += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            index += 1
            continue

        if depth == 0:
            for operator in _ASSIGNMENT_OPERATORS:
                if statement.startswith(operator, index):
                    if operator == "=" and _is_comparison_assignment_false_positive(statement, index):
                        continue
                    left = statement[:index].strip()
                    right = statement[index + len(operator):].strip()
                    if left and right:
                        return left, operator, right
        index += 1
    return None


def _is_comparison_assignment_false_positive(statement: str, index: int) -> bool:
    previous_char = statement[index - 1] if index > 0 else ""
    next_char = statement[index + 1] if index + 1 < len(statement) else ""
    return previous_char in "!<>=?" or next_char == "="


def _split_top_level(source: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string: str | None = None
    escaped = False

    for index, char in enumerate(source):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char == '"' or char == "'":
            in_string = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            continue
        if char == separator and depth == 0:
            parts.append(source[start:index])
            start = index + 1

    parts.append(source[start:])
    return parts
