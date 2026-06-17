# pyright: reportPrivateUsage=false
from __future__ import annotations

import re
from dataclasses import dataclass

from src.conversion.gml_transpiler import GMLTranspileError
from src.conversion.gml_transpiler_parts.identifiers import _validate_gml_identifier
from src.conversion.gml_transpiler_parts.utils import (
    _split_assignment,
    _split_top_level,
    _strip_comments,
)


@dataclass(frozen=True)
class ScriptFunctionParameter:
    name: str
    default: str | None


@dataclass(frozen=True)
class ScriptFunctionDeclaration:
    name: str
    parameters: tuple[ScriptFunctionParameter, ...]
    body: str


def find_matching_delimiter(source: str, start: int, opener: str, closer: str) -> int | None:
    if start < 0 or start >= len(source) or source[start] != opener:
        return None
    depth = 0
    index = start
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def parse_script_function_parameters(params_text: str) -> tuple[ScriptFunctionParameter, ...]:
    if not params_text.strip():
        return ()
    parameters: list[ScriptFunctionParameter] = []
    for raw_param in _split_top_level(params_text, ","):
        raw_param = raw_param.strip()
        if not raw_param:
            continue
        assignment = _split_assignment(raw_param)
        if assignment is None:
            name = raw_param
            default = None
        else:
            name, operator, default = assignment
            if operator != "=":
                raise GMLTranspileError("Script function parameters only support simple defaults")
        name = name.strip()
        _validate_gml_identifier(name)
        parameters.append(
            ScriptFunctionParameter(
                name=name,
                default=default.strip() if default is not None else None,
            )
        )
    return tuple(parameters)


def modern_script_function_declarations(source: str) -> tuple[ScriptFunctionDeclaration, ...] | None:
    candidate = _strip_comments(source).strip()
    if not candidate:
        return None

    declarations: list[ScriptFunctionDeclaration] = []
    index = 0
    while index < len(candidate):
        while index < len(candidate) and (candidate[index].isspace() or candidate[index] == ";"):
            index += 1
        if index >= len(candidate):
            break

        match = re.match(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", candidate[index:])
        if match is None:
            return None
        name = match.group(1)
        declaration_start = index + match.start()
        params_start = candidate.find("(", declaration_start)
        params_end = find_matching_delimiter(candidate, params_start, "(", ")")
        if params_end is None:
            return None
        body_start = candidate.find("{", params_end + 1)
        if body_start == -1 or candidate[params_end + 1:body_start].strip():
            return None
        body_end = find_matching_delimiter(candidate, body_start, "{", "}")
        if body_end is None:
            return None
        try:
            parameters = parse_script_function_parameters(candidate[params_start + 1:params_end])
        except GMLTranspileError:
            return None
        declarations.append(
            ScriptFunctionDeclaration(
                name=name,
                parameters=parameters,
                body=candidate[body_start + 1:body_end],
            )
        )
        index = body_end + 1

    return tuple(declarations) if declarations else None


def modern_script_function_names(source: str) -> tuple[str, ...]:
    declarations = modern_script_function_declarations(source)
    if declarations is None:
        return ()
    return tuple(declaration.name for declaration in declarations)


__all__ = [
    "ScriptFunctionDeclaration",
    "ScriptFunctionParameter",
    "find_matching_delimiter",
    "modern_script_function_declarations",
    "modern_script_function_names",
    "parse_script_function_parameters",
]
