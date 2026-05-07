from src.conversion.gml.ast import (
    Binary,
    Call,
    GMLTranspileError,
    Grouped,
    Index,
    Literal,
    Member,
    Name,
    Ternary,
    Unary,
    EOF,
)
from src.conversion.gml.builtins import NAME_REPLACEMENTS
from src.conversion.gml.emitter import emit_expression
from src.conversion.gml.lexer import tokenize
from src.conversion.gml.operators import (
    BINARY_PRECEDENCE,
    RIGHT_ASSOCIATIVE,
    TERNARY_PRECEDENCE,
)


def transpile_expression(source, local_names=None):
    parser = ExpressionParser(tokenize(source))
    expr = parser.parse()
    return emit_expression(expr, local_names)[0]


class ExpressionParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def parse(self):
        expr = self._parse_expression()
        if not self._at_end():
            raise GMLTranspileError(f"Unexpected token: {self._peek().value}")
        return expr

    def _parse_expression(self, min_precedence=0):
        left = self._parse_unary()

        while True:
            if self._match("?"):
                if TERNARY_PRECEDENCE < min_precedence:
                    self.position -= 1
                    break
                true_expr = self._parse_expression()
                self._consume(":")
                false_expr = self._parse_expression(TERNARY_PRECEDENCE)
                left = Ternary(left, true_expr, false_expr)
                continue

            operator = self._current_operator()
            if operator is None:
                break

            precedence = BINARY_PRECEDENCE[operator]
            if precedence < min_precedence:
                break

            self._advance()
            next_precedence = precedence if operator in RIGHT_ASSOCIATIVE else precedence + 1
            right = self._parse_expression(next_precedence)
            left = Binary(left, operator, right)

        return left

    def _parse_unary(self):
        operator = self._current_unary_operator()
        if operator in ("+", "-", "!", "not", "~"):
            self._advance()
            return Unary(operator, self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self):
        expr = self._parse_primary()
        while True:
            if self._match("("):
                args = []
                if not self._check(")"):
                    while True:
                        args.append(self._parse_expression())
                        if not self._match(","):
                            break
                self._consume(")")
                expr = Call(expr, tuple(args))
                continue

            if self._match("["):
                index = self._parse_expression()
                self._consume("]")
                expr = Index(expr, index)
                continue

            if self._match("."):
                member = self._consume_identifier()
                expr = Member(expr, member)
                continue

            break

        return expr

    def _parse_primary(self):
        token = self._advance()
        if token.kind == "NUMBER" or token.kind == "STRING":
            return Literal(token.value)
        if token.kind == "IDENT":
            return Name(NAME_REPLACEMENTS.get(token.value, token.value))
        if token.value == "(":
            expr = self._parse_expression()
            self._consume(")")
            return Grouped(expr)
        raise GMLTranspileError(f"Expected expression, got: {token.value}")

    def _current_operator(self):
        token = self._peek()
        if token.kind == "IDENT" and token.value in BINARY_PRECEDENCE:
            return token.value
        if token.value in BINARY_PRECEDENCE:
            return token.value
        return None

    def _current_unary_operator(self):
        token = self._peek()
        if token.kind == "IDENT" and token.value == "not":
            return token.value
        if token.value in ("+", "-", "!", "~"):
            return token.value
        return None

    def _match(self, value):
        if self._check(value):
            self.position += 1
            return True
        return False

    def _consume(self, value):
        if not self._match(value):
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self):
        token = self._advance()
        if token.kind != "IDENT":
            raise GMLTranspileError(f"Expected identifier, got: {token.value}")
        return token.value

    def _check(self, value):
        return self._peek().value == value

    def _advance(self):
        token = self._peek()
        if not self._at_end():
            self.position += 1
        return token

    def _peek(self):
        if self.position >= len(self.tokens):
            return EOF
        return self.tokens[self.position]

    def _at_end(self):
        return self._peek().kind == "EOF"
