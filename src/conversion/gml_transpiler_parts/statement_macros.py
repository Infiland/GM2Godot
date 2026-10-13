"""Macros used as statements.

A GameMaker macro is text substitution done before compiling (manual: GML
Overview > Variables > Constants, Macros): a macro may hold several
statements (joined with line continuations) and may be used on its own as a
statement. Macros whose value is one expression are expanded by the
expression parser; the helpers here put a macro's tokens in place of its name
where the value is statements, or where the macro is used as a statement.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import lru_cache

from .lexical_api import tokenize_gml_source
from .shared_models import Token

_STATEMENT_KEYWORDS = frozenset({
    "break",
    "continue",
    "delete",
    "do",
    "exit",
    "for",
    "globalvar",
    "if",
    "repeat",
    "return",
    "static",
    "switch",
    "throw",
    "try",
    "var",
    "while",
    "with",
})
_SPLICE_DEPTH_LIMIT = 32


@lru_cache(maxsize=4096)
def macro_value_tokens(value: str) -> tuple[Token, ...]:
    return tuple(token for token in tokenize_gml_source(value) if token.kind not in ("EOF", "NEWLINE"))


@lru_cache(maxsize=4096)
def _is_statement_value(value: str) -> bool:
    # The value is statements rather than one expression when it starts with
    # a statement keyword, has a ; outside brackets, or opens or closes a
    # block.
    tokens = macro_value_tokens(value)
    if not tokens:
        return False
    if tokens[0].kind == "IDENT" and tokens[0].value in _STATEMENT_KEYWORDS:
        return True
    bracket_depth = 0
    brace_depth = 0
    for token in tokens:
        if token.kind != "OP":
            continue
        if token.value in ("(", "["):
            bracket_depth += 1
        elif token.value in (")", "]"):
            bracket_depth -= 1
        elif token.value == "{":
            brace_depth += 1
        elif token.value == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return True
        elif token.value == ";" and bracket_depth == 0 and brace_depth == 0:
            return True
    return brace_depth != 0


def expand_statement_macros(tokens: list[Token], macro_values: Mapping[str, str]) -> list[Token]:
    """Put the tokens of every macro whose value is statements in place of its name."""
    if not any(token.kind == "IDENT" and _is_statement_macro(token.value, macro_values) for token in tokens):
        return tokens
    return _splice_statement_macros(tokens, macro_values, frozenset())


def _is_statement_macro(name: str, values: Mapping[str, str]) -> bool:
    # A macro whose value is just another macro's name is that macro.
    seen: set[str] = set()
    while name in values and name not in seen:
        seen.add(name)
        if _is_statement_value(values[name]):
            return True
        value_tokens = macro_value_tokens(values[name])
        if len(value_tokens) != 1 or value_tokens[0].kind != "IDENT":
            return False
        name = value_tokens[0].value
    return False


def macro_tokens_at(value: str, use: Token) -> list[Token]:
    """The macro value's tokens, placed where the macro name was used."""
    return [replace(token, line=use.line, column=use.column, index=use.index) for token in macro_value_tokens(value)]


def _splice_statement_macros(
    tokens: Sequence[Token],
    values: Mapping[str, str],
    active: frozenset[str],
) -> list[Token]:
    result: list[Token] = []
    in_definition = False
    for token in tokens:
        if token.kind == "DIRECTIVE" and token.value == "#macro":
            in_definition = True
        elif token.kind == "NEWLINE":
            in_definition = False
        if (
            not in_definition
            and token.kind == "IDENT"
            and token.value not in active
            and len(active) < _SPLICE_DEPTH_LIMIT
            and _is_statement_macro(token.value, values)
            and not (result and result[-1].kind == "OP" and result[-1].value == ".")
        ):
            result.extend(
                _splice_statement_macros(
                    macro_tokens_at(values[token.value], token),
                    values,
                    active | {token.value},
                )
            )
            continue
        result.append(token)
    return result
