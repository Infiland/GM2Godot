from src.conversion.gml.ast import GMLTranspileError, EOF
from src.conversion.gml.expression_parser import transpile_expression
from src.conversion.gml.source import indent_lines, tokens_to_source
from src.conversion.gml.statements import transpile_simple_statement


class StatementParser:
    def __init__(self, tokens, local_names=None):
        self.tokens = tokens
        self.position = 0
        self.local_names = set(local_names or [])

    def parse(self, terminator=None):
        lines = []
        while not self._at_end() and not self._check(terminator):
            if self._match(";"):
                continue
            lines.extend(self._parse_statement())
        return lines

    def _parse_statement(self):
        if self._check_identifier("if"):
            return self._parse_if_statement()

        statement_tokens = self._read_simple_statement()
        if not statement_tokens:
            return []
        return transpile_simple_statement(tokens_to_source(statement_tokens), self.local_names)

    def _parse_if_statement(self):
        self._consume_identifier("if")
        condition_tokens = self._read_condition_tokens()
        if not condition_tokens:
            raise GMLTranspileError("Expected if condition")

        condition = transpile_expression(tokens_to_source(condition_tokens), self.local_names)
        body_lines = self._parse_body()
        lines = [f"if {condition}:"]
        lines.extend(indent_lines(body_lines or ["pass"]))

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

    def _parse_body(self):
        if self._match("{"):
            lines = self.parse(terminator="}")
            self._consume("}")
            return lines
        if self._at_end() or self._check("}"):
            return []
        return self._parse_statement()

    def _read_condition_tokens(self):
        if self._match("("):
            return self._read_balanced_tokens("(", ")")

        tokens = []
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

    def _read_balanced_tokens(self, opener, closer):
        tokens = []
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

    def _read_simple_statement(self):
        tokens = []
        depth = 0
        while not self._at_end():
            token = self._peek()
            if depth == 0 and token.value == "}":
                break
            if depth == 0 and token.value == ";":
                self._advance()
                break

            if token.value in "([{":
                depth += 1
            elif token.value in ")]}" and depth > 0:
                depth -= 1
            tokens.append(self._advance())

        return tokens

    def _match(self, value):
        if self._check(value):
            self.position += 1
            return True
        return False

    def _match_identifier(self, value):
        if self._check_identifier(value):
            self.position += 1
            return True
        return False

    def _consume(self, value):
        if not self._match(value):
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _consume_identifier(self, value):
        if not self._match_identifier(value):
            raise GMLTranspileError(f"Expected '{value}', got: {self._peek().value}")

    def _check(self, value):
        if value is None:
            return False
        return self._peek().value == value

    def _check_identifier(self, value):
        token = self._peek()
        return token.kind == "IDENT" and token.value == value

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
