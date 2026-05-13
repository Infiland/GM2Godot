# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import hashlib
from typing import Iterable, Mapping, MutableMapping

from .constants import (
    _BINARY_PRECEDENCE,
    _EOF,
    _NAME_REPLACEMENTS,
    _RIGHT_ASSOCIATIVE,
    _TERNARY_PRECEDENCE,
)
from .identifiers import _reject_asset_identifier_name, _validate_gml_identifier
from .model import (
    GMLTranspileError,
    _ArrayLiteral,
    _Binary,
    _Call,
    _DSMapAccess,
    _Expression,
    _FunctionLiteral,
    _FunctionParameter,
    _Grouped,
    _Index,
    _Member,
    _Name,
    _NameOf,
    _NewCall,
    _NumberLiteral,
    _ScopeContext,
    _StringLiteral,
    _StructAccess,
    _StructLiteral,
    _Ternary,
    _Token,
    _Unary,
)
from .static_declarations import _collect_static_declarations, _static_scope_id
from .tokens import _expression_tokens, _is_float_like_number
from .utils import _normalize_scope_context

class _ExpressionParser:
    def __init__(
        self,
        tokens: list[_Token],
        enum_values: MutableMapping[str, dict[str, int]] | None = None,
        enum_names: Iterable[str] | None = None,
        scope_context: _ScopeContext | None = None,
        macro_values: Mapping[str, str] | None = None,
        macro_expansion_stack: frozenset[str] | None = None,
    ) -> None:
        self.tokens = tokens
        self.position = 0
        self.enum_values: MutableMapping[str, dict[str, int]] = (
            enum_values if enum_values is not None else {}
        )
        self.enum_names: set[str] = set(enum_names or [])
        self.scope_context = _normalize_scope_context(scope_context)
        self.macro_values: MutableMapping[str, str] = dict(macro_values or {})
        self.macro_expansion_stack = macro_expansion_stack or frozenset()

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
                        if self._check(",") or self._check(")"):
                            args.append(_Name(_NAME_REPLACEMENTS["undefined"]))
                        else:
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
                if self._match("?"):
                    key = self._parse_expression()
                    self._consume("]")
                    expr = _DSMapAccess(expr, key)
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
        if token.kind == "IDENT" and token.value == "nameof":
            return self._parse_nameof_expression()
        if token.kind == "IDENT" and token.value == "new":
            return self._parse_new_expression()
        if token.kind == "IDENT" and token.value == "function":
            return self._parse_function_literal()
        if token.kind == "IDENT":
            macro_expr = self._parse_macro_expansion(token.value)
            if macro_expr is not None:
                return macro_expr
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

    def _parse_macro_expansion(self, name: str) -> _Expression | None:
        macro_source = self.macro_values.get(name)
        if macro_source is None:
            return None
        if name in self.macro_expansion_stack:
            raise GMLTranspileError(f"Recursive macro expansion for {name}")
        return _parse_gml_expression(
            macro_source,
            self.enum_values,
            self.enum_names,
            self.macro_values,
            self.macro_expansion_stack | {name},
            scope_context=self.scope_context,
        )

    def _parse_new_expression(self) -> _Expression:
        constructor = self._parse_primary()
        while self._match("."):
            constructor = _Member(constructor, self._consume_identifier())

        self._consume("(")
        args: list[_Expression] = []
        if not self._check(")"):
            while True:
                if self._check(",") or self._check(")"):
                    args.append(_Name(_NAME_REPLACEMENTS["undefined"]))
                else:
                    args.append(self._parse_expression())
                if not self._match(","):
                    break
        self._consume(")")
        return _NewCall(constructor, tuple(args))

    def _parse_nameof_expression(self) -> _Expression:
        self._consume("(")
        name = self._parse_nameof_argument_name()
        self._consume(")")
        return _NameOf(name)

    def _parse_nameof_argument_name(self) -> str:
        token = self._advance()
        if token.kind != "IDENT":
            raise GMLTranspileError("nameof requires an identifier")

        name = token.value
        while self._match("."):
            name = self._consume_identifier()

        if self._match("("):
            self._read_balanced_tokens("(", ")")

        if not self._check(")"):
            raise GMLTranspileError("nameof requires an identifier, enum member, or function-call syntax")
        return name

    def _parse_function_literal(self) -> _Expression:
        name = None
        if self._peek().kind == "IDENT":
            name = self._consume_identifier()

        parameters: list[_FunctionParameter] = []
        self._consume("(")
        if not self._check(")"):
            while True:
                parameter_name = self._consume_identifier()
                default = self._parse_expression() if self._match("=") else None
                parameters.append(_FunctionParameter(parameter_name, default))
                if not self._match(","):
                    break
        self._consume(")")
        parent_constructor: _Expression | None = None
        if self._match(":"):
            parent_constructor = self._parse_expression()
        is_constructor = self._match_identifier("constructor")
        self._consume("{")
        body_tokens = self._read_balanced_tokens("{", "}")
        static_declarations = _collect_static_declarations(body_tokens)
        parameter_names = [parameter.name for parameter in parameters]
        for parameter_name in parameter_names:
            _validate_gml_identifier(parameter_name)
            _reject_asset_identifier_name(parameter_name, self.scope_context)
        scope_context = self.scope_context
        static_scope_id = None
        static_scope_name = None
        static_prefix = scope_context.static_prefix
        if static_declarations:
            static_scope_id = _static_scope_id(static_prefix, name, self.position, body_tokens)
            static_scope_name = (
                f"_gml_static_scope_{hashlib.sha1(static_scope_id.encode('utf-8')).hexdigest()[:12]}"
            )
            static_prefix = static_scope_id
        static_names = frozenset(declaration.name for declaration in static_declarations)
        if is_constructor:
            scope_context = _ScopeContext(
                self_expression="_gml_constructor_self",
                other_expression=self.scope_context.other_expression,
                instance_target="_gml_constructor_self",
                global_names=self.scope_context.global_names,
                asset_names=self.scope_context.asset_names,
                static_scope=static_scope_name,
                static_names=static_names,
                static_prefix=static_prefix,
            )
        else:
            scope_context = _ScopeContext(
                self_expression=scope_context.self_expression,
                other_expression=scope_context.other_expression,
                instance_target=scope_context.instance_target,
                global_names=scope_context.global_names,
                asset_names=scope_context.asset_names,
                static_scope=static_scope_name,
                static_names=static_names,
                static_prefix=static_prefix,
            )
        from .statement_parser import _StatementParser

        body_parser = _StatementParser(
            body_tokens,
            local_names=parameter_names,
            return_depth=1,
            enum_values=self.enum_values,
            enum_names=self.enum_names,
            scope_context=scope_context,
            macro_values=self.macro_values,
            global_names=scope_context.global_names,
        )
        body_lines = body_parser.parse()
        prelude_lines: list[str] = []
        if parent_constructor is not None:
            if not is_constructor:
                raise GMLTranspileError("Constructor inheritance requires a constructor function")
            from .function_helpers import _emit_constructor_inheritance_line

            prelude_lines.append(
                _emit_constructor_inheritance_line(
                    parent_constructor,
                    parameter_names,
                    scope_context,
                    self.scope_context,
                )
            )
        if static_declarations:
            from .function_helpers import _emit_static_initialization_lines

            prelude_lines.extend(
                _emit_static_initialization_lines(
                    static_scope_name,
                    static_scope_id,
                    static_declarations,
                    parameter_names,
                    scope_context,
                    self.enum_values,
                    self.enum_names,
                    self.macro_values,
                )
            )
        if prelude_lines:
            body_lines = [*prelude_lines, *body_lines]
        return _FunctionLiteral(
            name,
            tuple(parameters),
            tuple(body_lines or ["pass"]),
            is_constructor,
            static_scope_id if static_declarations else None,
        )

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

    def _match_identifier(self, value: str) -> bool:
        token = self._peek()
        if token.kind == "IDENT" and token.value == value:
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


def _parse_gml_expression(
    source: str,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    macro_values: Mapping[str, str] | None = None,
    macro_expansion_stack: frozenset[str] | None = None,
    scope_context: _ScopeContext | None = None,
) -> _Expression:
    parser = _ExpressionParser(
        _expression_tokens(source),
        enum_values=enum_values,
        enum_names=enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
        macro_expansion_stack=macro_expansion_stack,
    )
    return parser.parse()
