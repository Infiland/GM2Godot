from dataclasses import dataclass


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
class _Unary:
    operator: str
    operand: object


@dataclass(frozen=True)
class _Binary:
    left: object
    operator: str
    right: object


@dataclass(frozen=True)
class _Ternary:
    condition: object
    true_expr: object
    false_expr: object


@dataclass(frozen=True)
class _Call:
    callee: object
    args: tuple


@dataclass(frozen=True)
class _Index:
    target: object
    index: object


@dataclass(frozen=True)
class _Member:
    target: object
    member: str


@dataclass(frozen=True)
class _Grouped:
    expr: object


_EOF = _Token("EOF", "")

_MULTI_CHAR_OPERATORS = (
    "??=",
    "<<=",
    ">>=",
    "??",
    "<=",
    ">=",
    "==",
    "!=",
    "&&",
    "||",
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

_ASSIGNMENT_OPERATORS = (
    "??=",
    "<<=",
    ">>=",
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
    "and": 30,
    "&&": 30,
    "|": 40,
    "^": 50,
    "&": 60,
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

_RIGHT_ASSOCIATIVE = {"??"}

_OPERATOR_REPLACEMENTS = {
    "&&": "and",
    "||": "or",
    "mod": "%",
}

_NAME_REPLACEMENTS = {
    "undefined": "null",
}


def transpile_gml_expression(source):
    """Transpile a single GML expression to a GDScript expression."""
    parser = _ExpressionParser(_tokenize(source))
    expr = parser.parse()
    return _emit_expression(expr)[0]


def transpile_gml_code(source, indent="\t"):
    """Transpile simple expression/assignment GML statements to GDScript.

    This intentionally covers the expressions-and-operators milestone slice:
    declarations, assignments, compound assignments, nullish assignment,
    increment/decrement statements, and expression statements. Control flow is
    left for later GML language-structure issues.
    """
    lines = []
    for statement in _split_statements(_strip_comments(source)):
        lines.extend(_transpile_statement(statement.strip()))

    if not lines:
        return f"{indent}pass"

    return "\n".join(f"{indent}{line}" if line else "" for line in lines)


class _ExpressionParser:
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

    def _parse_unary(self):
        operator = self._current_unary_operator()
        if operator in ("+", "-", "!", "not", "~"):
            self._advance()
            return _Unary(operator, self._parse_unary())
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
                expr = _Call(expr, tuple(args))
                continue

            if self._match("["):
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

    def _parse_primary(self):
        token = self._advance()
        if token.kind == "NUMBER" or token.kind == "STRING":
            return _Literal(token.value)
        if token.kind == "IDENT":
            return _Name(_NAME_REPLACEMENTS.get(token.value, token.value))
        if token.value == "(":
            expr = self._parse_expression()
            self._consume(")")
            return _Grouped(expr)
        raise GMLTranspileError(f"Expected expression, got: {token.value}")

    def _current_operator(self):
        token = self._peek()
        if token.kind == "IDENT" and token.value in _BINARY_PRECEDENCE:
            return token.value
        if token.value in _BINARY_PRECEDENCE:
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
            return _EOF
        return self.tokens[self.position]

    def _at_end(self):
        return self._peek().kind == "EOF"


def _tokenize(source):
    tokens = []
    index = 0
    while index < len(source):
        char = source[index]

        if char.isspace():
            index += 1
            continue

        if char.isdigit():
            start = index
            if source[index:index + 2].lower() == "0x":
                index += 2
                while index < len(source) and source[index].lower() in "0123456789abcdef":
                    index += 1
            else:
                while index < len(source) and (source[index].isdigit() or source[index] == "."):
                    index += 1
            tokens.append(_Token("NUMBER", source[start:index]))
            continue

        if char == '"' or char == "'":
            tokens.append(_Token("STRING", _read_string(source, index)))
            index += len(tokens[-1].value)
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                index += 1
            tokens.append(_Token("IDENT", source[start:index]))
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


def _read_string(source, start):
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


def _emit_expression(expr):
    if isinstance(expr, _Literal):
        return expr.value, _PRIMARY_PRECEDENCE
    if isinstance(expr, _Name):
        return expr.value, _PRIMARY_PRECEDENCE
    if isinstance(expr, _Grouped):
        return f"({_emit_expression(expr.expr)[0]})", _PRIMARY_PRECEDENCE
    if isinstance(expr, _Unary):
        operand = _emit_child(expr.operand, _UNARY_PRECEDENCE)
        if expr.operator == "!":
            return f"not {operand}", _UNARY_PRECEDENCE
        if expr.operator == "not":
            return f"not {operand}", _UNARY_PRECEDENCE
        return f"{expr.operator}{operand}", _UNARY_PRECEDENCE
    if isinstance(expr, _Binary):
        return _emit_binary(expr)
    if isinstance(expr, _Ternary):
        condition = _emit_child(expr.condition, _TERNARY_PRECEDENCE)
        true_expr = _emit_child(expr.true_expr, _TERNARY_PRECEDENCE)
        false_expr = _emit_child(expr.false_expr, _TERNARY_PRECEDENCE)
        return f"{true_expr} if {condition} else {false_expr}", _TERNARY_PRECEDENCE
    if isinstance(expr, _Call):
        callee = _emit_child(expr.callee, _POSTFIX_PRECEDENCE)
        args = ", ".join(_emit_expression(arg)[0] for arg in expr.args)
        return f"{callee}({args})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _Index):
        target = _emit_child(expr.target, _POSTFIX_PRECEDENCE)
        index = _emit_expression(expr.index)[0]
        return f"{target}[{index}]", _POSTFIX_PRECEDENCE
    if isinstance(expr, _Member):
        target = _emit_child(expr.target, _POSTFIX_PRECEDENCE)
        return f"{target}.{expr.member}", _POSTFIX_PRECEDENCE
    raise GMLTranspileError("Unknown expression node")


def _emit_binary(expr):
    operator = _OPERATOR_REPLACEMENTS.get(expr.operator, expr.operator)

    if expr.operator == "div":
        left = _emit_expression(expr.left)[0]
        right = _emit_expression(expr.right)[0]
        return f"int({left} / {right})", _PRIMARY_PRECEDENCE

    if expr.operator == "??":
        left = _emit_expression(expr.left)[0]
        right = _emit_child(expr.right, _TERNARY_PRECEDENCE)
        return f"{left} if {left} != null else {right}", _TERNARY_PRECEDENCE

    precedence = _BINARY_PRECEDENCE[expr.operator]
    left = _emit_child(expr.left, precedence)
    right = _emit_child(expr.right, precedence, is_right_child=True, parent_operator=expr.operator)
    return f"{left} {operator} {right}", precedence


def _emit_child(expr, parent_precedence, is_right_child=False, parent_operator=None):
    text, precedence = _emit_expression(expr)
    needs_parentheses = precedence < parent_precedence
    if is_right_child and precedence == parent_precedence and parent_operator not in _RIGHT_ASSOCIATIVE:
        needs_parentheses = True
    if needs_parentheses:
        return f"({text})"
    return text


def _strip_comments(source):
    result = []
    index = 0
    in_string = None
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


def _split_statements(source):
    statements = []
    start = 0
    depth = 0
    in_string = None
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


def _transpile_statement(statement):
    if not statement:
        return []

    if statement.startswith("var "):
        return _transpile_var_statement(statement[4:].strip())

    increment = _parse_increment_statement(statement)
    if increment is not None:
        target, delta = increment
        return [f"{transpile_gml_expression(target)} {'+=' if delta > 0 else '-='} 1"]

    assignment = _split_assignment(statement)
    if assignment is not None:
        target, operator, value = assignment
        target = transpile_gml_expression(target)
        value = transpile_gml_expression(value)
        if operator == "??=":
            return [f"if {target} == null:", f"\t{target} = {value}"]
        return [f"{target} {operator} {value}"]

    return [transpile_gml_expression(statement)]


def _transpile_var_statement(statement):
    lines = []
    for declaration in _split_top_level(statement, ","):
        declaration = declaration.strip()
        if not declaration:
            continue
        assignment = _split_assignment(declaration)
        if assignment is None:
            lines.append(f"var {declaration}")
            continue
        name, operator, value = assignment
        if operator != "=":
            raise GMLTranspileError("Variable declarations only support '=' assignments")
        lines.append(f"var {name.strip()} = {transpile_gml_expression(value)}")
    return lines


def _parse_increment_statement(statement):
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


def _split_assignment(statement):
    depth = 0
    in_string = None
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


def _is_comparison_assignment_false_positive(statement, index):
    previous_char = statement[index - 1] if index > 0 else ""
    next_char = statement[index + 1] if index + 1 < len(statement) else ""
    return previous_char in "!<>=?" or next_char == "="


def _split_top_level(source, separator):
    parts = []
    start = 0
    depth = 0
    in_string = None
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
