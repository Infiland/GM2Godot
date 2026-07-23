# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Mapping, MutableMapping

from .constants import (
    _BINARY_PRECEDENCE,
    _EOF,
    _NAME_REPLACEMENTS,
    _RIGHT_ASSOCIATIVE,
    _TERNARY_PRECEDENCE,
)
from .identifiers import _reject_asset_identifier_name, _validate_gml_identifier
from .lexical import _decode_gml_verbatim_string_literal
from .expression_models import (
    ArrayLiteral as _ArrayLiteral,
    ArrayRefAccess as _ArrayRefAccess,
    Binary as _Binary,
    Call as _Call,
    DSGridAccess as _DSGridAccess,
    DSListAccess as _DSListAccess,
    DSMapAccess as _DSMapAccess,
    EnumMember as _EnumMember,
    Expression as _Expression,
    FunctionLiteral as _FunctionLiteral,
    FunctionParameter as _FunctionParameter,
    Grouped as _Grouped,
    Index as _Index,
    Member as _Member,
    Name as _Name,
    NameOf as _NameOf,
    NewCall as _NewCall,
    NumberLiteral as _NumberLiteral,
    StringLiteral as _StringLiteral,
    StructAccess as _StructAccess,
    StructLiteral as _StructLiteral,
    TemplateStringLiteral as _TemplateStringLiteral,
    Ternary as _Ternary,
    Unary as _Unary,
)
from .shared_models import (
    GMLTranspileError,
    ScopeContext as _ScopeContext,
    Token as _Token,
)
from .static_declarations import _collect_static_declarations, _static_scope_id
from .tokens import (
    _decode_gml_string_literal,
    _expression_tokens,
    _is_float_like_number,
    _split_template_string,
)
from .utils import _normalize_scope_context, _strip_comments

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
        self.enum_names: set[str] = set(self.enum_values)
        self.enum_names.update(enum_names or [])
        self.scope_context = _normalize_scope_context(scope_context)
        self.macro_values: MutableMapping[str, str] = dict(macro_values or {})
        self.macro_expansion_stack = macro_expansion_stack or frozenset()

    def parse(self) -> _Expression:
        expr = self._parse_expression()
        if not self._at_end():
            raise self._error(f"Unexpected token: {self._peek().value}")
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
                if self._match("|"):
                    index = self._parse_expression()
                    self._consume("]")
                    expr = _DSListAccess(expr, index)
                    continue
                if self._match("#"):
                    x_index = self._parse_expression()
                    self._consume(",")
                    y_index = self._parse_expression()
                    self._consume("]")
                    expr = _DSGridAccess(expr, x_index, y_index)
                    continue
                if self._match("@"):
                    index = self._parse_expression()
                    self._consume("]")
                    expr = _ArrayRefAccess(expr, index)
                    continue
                index = self._parse_expression()
                self._consume("]")
                expr = _Index(expr, index)
                continue

            if self._match("."):
                member = self._consume_identifier()
                if isinstance(expr, _Name) and expr.value in self.enum_names:
                    enum_members = self.enum_values.get(expr.value, {})
                    if member not in enum_members:
                        raise GMLTranspileError(
                            f"Unknown enum member {expr.value}.{member}"
                        )
                    expr = _EnumMember(
                        enum_name=expr.value,
                        member=member,
                        value=enum_members[member],
                    )
                else:
                    expr = _Member(expr, member)
                continue

            break

        return expr

    def _parse_primary(self) -> _Expression:
        token = self._advance()
        if token.kind == "NUMBER":
            return _NumberLiteral(token.value, _is_float_like_number(token.value))
        if token.kind == "STRING":
            decoded = _decode_gml_string_literal(token.value)
            emitted = json.dumps(decoded)
            if token.value.startswith("'"):
                emitted = "'" + emitted[1:-1].replace('\\"', '"').replace("'", "\\'") + "'"
            return _StringLiteral(emitted)
        if token.kind == "VERBATIM_STRING":
            return _StringLiteral(
                json.dumps(_decode_gml_verbatim_string_literal(token.value))
            )
        if token.kind == "TEMPLATE_STRING":
            return self._parse_template_string(token.value)
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
                    field_token = self._peek()
                    if field_token.kind == "STRING":
                        self._advance()
                        if not field_token.value.startswith('"'):
                            raise GMLTranspileError(
                                "Quoted struct field names must use double quotes",
                                line=field_token.line,
                                column=field_token.column,
                            )
                        field_name = _decode_gml_string_literal(field_token.value)
                        if not field_name:
                            raise GMLTranspileError(
                                "Struct field names cannot be empty",
                                line=field_token.line,
                                column=field_token.column,
                            )
                        self._consume(":")
                        field_value = self._parse_expression()
                    else:
                        field_name = self._consume_identifier()
                        if self._match(":"):
                            field_value = self._parse_expression()
                        else:
                            field_value = _Name(
                                _NAME_REPLACEMENTS.get(field_name, field_name)
                            )
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
        raise GMLTranspileError(
            f"Expected expression, got: {token.value}",
            line=token.line,
            column=token.column,
        )

    def _parse_template_string(self, source: str) -> _TemplateStringLiteral:
        parts: list[str | _Expression] = []
        for part_kind, part_source in _split_template_string(source):
            if part_kind == "text":
                parts.append(part_source)
                continue
            parts.append(
                _parse_gml_expression(
                    _strip_comments(part_source),
                    self.enum_values,
                    self.enum_names,
                    self.macro_values,
                    self.macro_expansion_stack,
                    scope_context=self.scope_context,
                )
            )
        return _TemplateStringLiteral(tuple(parts))

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
        static_scope_name = scope_context.static_scope
        static_prefix = scope_context.static_prefix
        if static_declarations:
            static_scope_id = _static_scope_id(static_prefix, name, self.position, body_tokens)
            static_scope_name = (
                f"_gml_static_scope_{hashlib.sha1(static_scope_id.encode('utf-8')).hexdigest()[:12]}"
            )
            static_prefix = static_scope_id
        static_names = (
            frozenset(declaration.name for declaration in static_declarations)
            if static_declarations
            else scope_context.static_names
        )
        if is_constructor:
            scope_context = _ScopeContext(
                self_expression="_gml_constructor_self",
                other_expression="_gml_constructor_other",
                instance_target="_gml_constructor_self",
                global_names=self.scope_context.global_names,
                asset_names=self.scope_context.asset_names,
                direct_instance_names=self.scope_context.direct_instance_names,
                dynamic_instance_names=self.scope_context.dynamic_instance_names,
                static_scope=static_scope_name,
                static_names=static_names,
                static_prefix=static_prefix,
                extension_functions=self.scope_context.extension_functions,
                extension_function_mappings=self.scope_context.extension_function_mappings,
            )
        else:
            scope_context = _ScopeContext(
                # A GML function body resolves instance/struct fields through
                # the method's bound self, which can later be changed by
                # method().  Keep that receiver dynamic instead of baking in
                # the scope where the function literal was declared.
                self_expression="_gml_method_self",
                other_expression="_gml_method_other",
                instance_target="_gml_method_self",
                global_scope=scope_context.global_scope,
                global_names=scope_context.global_names,
                asset_names=scope_context.asset_names,
                direct_instance_names=scope_context.direct_instance_names,
                dynamic_instance_names=scope_context.dynamic_instance_names,
                static_scope=static_scope_name,
                static_names=static_names,
                static_prefix=static_prefix,
                extension_functions=scope_context.extension_functions,
                extension_function_mappings=scope_context.extension_function_mappings,
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
            raise self._error(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self) -> str:
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

    def _error(self, message: str) -> GMLTranspileError:
        token = self._peek()
        return GMLTranspileError(message, line=token.line, column=token.column)


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
