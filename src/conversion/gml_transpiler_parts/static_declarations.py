# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import hashlib

from typing import Iterable

from .identifiers import _validate_gml_identifier
from .model import GMLTranspileError, _StaticDeclaration, _Token
from .utils import _split_assignment, _split_top_level, _tokens_to_source

def _static_scope_id(
    prefix: str,
    name: str | None,
    position: int,
    body_tokens: Iterable[_Token],
) -> str:
    body_source = _tokens_to_source(body_tokens)
    digest = hashlib.sha1(body_source.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{name or '<anonymous>'}:{position}:{digest}"


def _collect_static_declarations(tokens: Iterable[_Token]) -> tuple[_StaticDeclaration, ...]:
    token_list = list(tokens)
    declarations: list[_StaticDeclaration] = []
    index = 0
    while index < len(token_list):
        token = token_list[index]
        if token.kind == "IDENT" and token.value == "function":
            index = _skip_function_literal_tokens(token_list, index)
            continue
        if token.kind == "IDENT" and token.value == "static":
            statement_tokens, index = _read_static_declaration_tokens(token_list, index + 1)
            declarations.extend(_parse_static_declarations(_tokens_to_source(statement_tokens)))
            continue
        index += 1
    return tuple(declarations)


def _skip_function_literal_tokens(tokens: list[_Token], index: int) -> int:
    body_start = index + 1
    while body_start < len(tokens) and tokens[body_start].value != "{":
        body_start += 1
    if body_start >= len(tokens):
        return index + 1

    depth = 1
    current = body_start + 1
    while current < len(tokens) and depth > 0:
        value = tokens[current].value
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
        current += 1
    return current


def _read_static_declaration_tokens(
    tokens: list[_Token],
    index: int,
) -> tuple[list[_Token], int]:
    statement_tokens: list[_Token] = []
    depth = 0
    current = index
    while current < len(tokens):
        token = tokens[current]
        if depth == 0 and token.value == ";":
            return statement_tokens, current + 1
        if depth == 0 and token.kind == "NEWLINE":
            return statement_tokens, current + 1
        if token.value in "([{":
            depth += 1
        elif token.value in ")]}" and depth > 0:
            depth -= 1
        statement_tokens.append(token)
        current += 1
    return statement_tokens, current


def _parse_static_declarations(source: str) -> list[_StaticDeclaration]:
    declarations: list[_StaticDeclaration] = []
    for declaration in _split_top_level(source, ","):
        declaration = declaration.strip()
        if not declaration:
            continue
        assignment = _split_assignment(declaration)
        if assignment is None:
            name = declaration
            value_source = "undefined"
        else:
            name, operator, value_source = assignment
            if operator not in ("=", ":="):
                raise GMLTranspileError("Static declarations only support simple assignments")
            name = name.strip()
            value_source = value_source.strip()
        _validate_gml_identifier(name)
        declarations.append(_StaticDeclaration(name, value_source))
    return declarations
