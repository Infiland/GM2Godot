"""Where GML statements and conditions end.

GameMaker treats line breaks as white space and needs no semicolons: a
statement ends where its expression ends, that is, before the first token
that cannot continue it (manual: GML Overview > Language Features > If Else
and Conditional Operators: ``if test == true variable = false else variable
= true;``). So ``a = 2 trace(a)`` is two statements, ``if f(x) g()`` is an
``if`` with the condition ``f(x)``, and ``x = a`` followed by ``+ b`` on the
next line is the single statement ``x = a + b``.

The scanners return the index just past what they read, or None when the
tokens do not form what they expect; callers then keep their line-based
reading.
"""
from __future__ import annotations

from collections.abc import Sequence

from .constants import ASSIGNMENT_OPERATORS, BINARY_PRECEDENCE
from .shared_models import Token

# Words that start or separate statements; none of them can continue an
# expression.
_STATEMENT_KEYWORDS = frozenset({
    "break",
    "case",
    "catch",
    "continue",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "exit",
    "finally",
    "for",
    "globalvar",
    "if",
    "repeat",
    "return",
    "static",
    "switch",
    "then",
    "throw",
    "try",
    "until",
    "var",
    "while",
    "with",
})
_PREFIX_OPERATORS = frozenset({"+", "-", "!", "~", "not", "++", "--"})
_LITERAL_KINDS = frozenset({"NUMBER", "STRING", "VERBATIM_STRING", "TEMPLATE_STRING"})
_CLOSERS = {"(": ")", "[": "]", "{": "}"}
_ONE_WORD_STATEMENTS = frozenset({"break", "continue", "exit"})


def scan_statement_end(tokens: Sequence[Token], index: int) -> int | None:
    """Return the end of the simple statement starting at ``index``."""
    if index >= len(tokens):
        return None
    token = tokens[index]
    if token.kind == "IDENT" and token.value in _ONE_WORD_STATEMENTS:
        return index + 1
    if token.kind == "IDENT" and token.value == "return":
        # A return value starts on the same line as the return.
        value_start = index + 1
        if value_start < len(tokens) and _can_start_expression(tokens[value_start]):
            return scan_expression_end(tokens, value_start)
        return value_start
    if token.kind == "IDENT" and token.value in ("throw", "delete"):
        return scan_expression_end(tokens, index + 1)
    if token.kind == "IDENT" and token.value == "var":
        return _scan_var_declarations_end(tokens, index + 1)
    end = scan_expression_end(tokens, index)
    if end is None:
        return None
    operator_index = skip_newline_tokens(tokens, end)
    if operator_index < len(tokens) and _is_assignment_operator(tokens[operator_index]):
        return scan_expression_end(tokens, operator_index + 1)
    return end


def scan_expression_end(tokens: Sequence[Token], index: int) -> int | None:
    """Return the end of the expression starting at ``index``."""
    end = _scan_operand_end(tokens, index)
    while end is not None:
        next_index = skip_newline_tokens(tokens, end)
        if next_index >= len(tokens):
            return end
        token = tokens[next_index]
        if token.value == "?" and token.kind == "OP":
            true_end = scan_expression_end(tokens, next_index + 1)
            colon_index = skip_newline_tokens(tokens, true_end) if true_end is not None else len(tokens)
            if colon_index >= len(tokens) or tokens[colon_index].value != ":":
                return None
            end = scan_expression_end(tokens, colon_index + 1)
        elif _is_binary_operator(token):
            end = _scan_operand_end(tokens, next_index + 1)
        else:
            return end
    return None


def skip_newline_tokens(tokens: Sequence[Token], index: int) -> int:
    while index < len(tokens) and tokens[index].kind == "NEWLINE":
        index += 1
    return index


def matching_close_index(tokens: Sequence[Token], open_index: int) -> int | None:
    """Return the index of the bracket that closes the one at ``open_index``."""
    stack: list[str] = []
    for index in range(open_index, len(tokens)):
        value = tokens[index].value
        if tokens[index].kind != "OP":
            continue
        if value in _CLOSERS:
            stack.append(_CLOSERS[value])
        elif value in (")", "]", "}"):
            if not stack or stack.pop() != value:
                return None
            if not stack:
                return index
    return None


def _scan_var_declarations_end(tokens: Sequence[Token], index: int) -> int | None:
    while True:
        name_index = skip_newline_tokens(tokens, index)
        if name_index >= len(tokens) or tokens[name_index].kind != "IDENT":
            return None
        end: int | None = name_index + 1
        if name_index + 1 < len(tokens) and tokens[name_index + 1].kind == "IDENT":
            # var foo bar: not a declaration list.
            return None
        next_index = skip_newline_tokens(tokens, name_index + 1)
        if next_index < len(tokens) and tokens[next_index].value in ("=", ":="):
            end = scan_expression_end(tokens, next_index + 1)
            if end is None:
                return None
            next_index = skip_newline_tokens(tokens, end)
        if next_index >= len(tokens) or tokens[next_index].value != ",":
            return end
        index = next_index + 1


def _scan_operand_end(tokens: Sequence[Token], index: int) -> int | None:
    index = skip_newline_tokens(tokens, index)
    while index < len(tokens) and _is_prefix_operator(tokens[index]):
        index = skip_newline_tokens(tokens, index + 1)
    if index >= len(tokens):
        return None
    token = tokens[index]
    if token.kind == "IDENT" and token.value == "new":
        return _scan_operand_end(tokens, index + 1)
    end: int | None
    if token.kind in _LITERAL_KINDS:
        end = index + 1
    elif token.kind == "IDENT" and token.value == "function":
        end = _scan_function_literal_end(tokens, index + 1)
    elif token.kind == "IDENT":
        end = index + 1 if _can_start_expression(token) else None
    elif token.kind == "OP" and token.value in _CLOSERS:
        close_index = matching_close_index(tokens, index)
        end = close_index + 1 if close_index is not None else None
    else:
        end = None
    return _scan_postfix_end(tokens, end) if end is not None else None


def _scan_postfix_end(tokens: Sequence[Token], end: int) -> int | None:
    while True:
        next_index = skip_newline_tokens(tokens, end)
        if next_index >= len(tokens):
            return end
        token = tokens[next_index]
        if token.kind == "OP" and token.value in ("(", "["):
            close_index = matching_close_index(tokens, next_index)
            if close_index is None:
                return None
            end = close_index + 1
        elif token.kind == "OP" and token.value == ".":
            member_index = skip_newline_tokens(tokens, next_index + 1)
            if member_index >= len(tokens) or tokens[member_index].kind != "IDENT":
                return None
            end = member_index + 1
        elif token.kind == "OP" and token.value in ("++", "--") and next_index == end and (
            _is_assignable_end(tokens[end - 1])
            or next_index + 1 >= len(tokens)
            or not _can_start_expression(tokens[next_index + 1])
        ):
            # A postfix ++ or -- follows its operand on the same line; a ++ or
            # -- before another operand (or on the next line) starts the next
            # statement.
            end = next_index + 1
        else:
            return end


def _scan_function_literal_end(tokens: Sequence[Token], index: int) -> int | None:
    index = skip_newline_tokens(tokens, index)
    if index < len(tokens) and tokens[index].kind == "IDENT":
        index = skip_newline_tokens(tokens, index + 1)
    if index >= len(tokens) or tokens[index].value != "(":
        return None
    close_index = matching_close_index(tokens, index)
    if close_index is None:
        return None
    index = skip_newline_tokens(tokens, close_index + 1)
    if index < len(tokens) and tokens[index].value == ":":
        parent_end = _scan_operand_end(tokens, index + 1)
        if parent_end is None:
            return None
        index = skip_newline_tokens(tokens, parent_end)
    if index < len(tokens) and tokens[index].kind == "IDENT" and tokens[index].value == "constructor":
        index = skip_newline_tokens(tokens, index + 1)
    if index >= len(tokens) or tokens[index].value != "{":
        return None
    close_index = matching_close_index(tokens, index)
    return close_index + 1 if close_index is not None else None


def _is_assignable_end(token: Token) -> bool:
    return token.kind == "IDENT" or (token.kind == "OP" and token.value == "]")


def _can_start_expression(token: Token) -> bool:
    if token.kind in _LITERAL_KINDS:
        return True
    if token.kind == "IDENT":
        return token.value not in _STATEMENT_KEYWORDS and token.value not in BINARY_PRECEDENCE
    return token.kind == "OP" and (token.value in _CLOSERS or token.value in _PREFIX_OPERATORS)


def _is_prefix_operator(token: Token) -> bool:
    if token.kind == "IDENT":
        return token.value == "not"
    return token.kind == "OP" and token.value in _PREFIX_OPERATORS


def _is_binary_operator(token: Token) -> bool:
    if token.value not in BINARY_PRECEDENCE:
        return False
    return token.kind == "OP" or (token.kind == "IDENT" and token.value.isalpha())


def _is_assignment_operator(token: Token) -> bool:
    return token.kind == "OP" and token.value in ASSIGNMENT_OPERATORS
