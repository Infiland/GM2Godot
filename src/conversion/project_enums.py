# pyright: reportPrivateUsage=false
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.conversion.gml_transpiler_parts.enum_helpers import (
    _evaluate_enum_value_tokens,
)
from src.conversion.gml_transpiler_parts.preprocessor import preprocess_gml_source
from src.conversion.gml_transpiler_parts.shared_models import GMLTranspileError, Token
from src.conversion.gml_transpiler_parts.tokens import _tokenize
from src.conversion.project_macros import collect_project_macro_values
from src.conversion.project_source_paths import project_gml_source_paths
from src.conversion.type_defs import StrPath


@dataclass(frozen=True)
class _ProjectEnumMember:
    name: str
    value_tokens: tuple[Token, ...] | None


@dataclass(frozen=True)
class _ProjectEnumDeclaration:
    name: str
    members: tuple[_ProjectEnumMember, ...]


def collect_project_enum_values(
    gm_project_path: StrPath,
    *,
    macro_configuration: str | None = None,
) -> dict[str, dict[str, int]]:
    """Collect GameMaker's project-global enum constants from GML sources."""
    token_streams: list[list[Token]] = []
    for source_path in project_gml_source_paths(gm_project_path):
        try:
            with open(source_path.filesystem_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            preprocessed = preprocess_gml_source(
                source,
                macro_configuration=macro_configuration,
            )
            token_streams.append(_tokenize(preprocessed.source))
        except (OSError, GMLTranspileError):
            # The owning converter will report malformed/unsupported source with
            # its normal resource-level diagnostic. Enum discovery must not make
            # unrelated resources unconvertible.
            continue

    macro_values = collect_project_macro_values(
        gm_project_path,
        macro_configuration=macro_configuration,
    )
    declarations = [
        declaration
        for tokens in token_streams
        for declaration in _enum_declarations(tokens)
    ]
    return _evaluate_project_enums(declarations, macro_values)
def _enum_declarations(tokens: Sequence[Token]) -> tuple[_ProjectEnumDeclaration, ...]:
    declarations: list[_ProjectEnumDeclaration] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind != "IDENT" or token.value != "enum":
            index += 1
            continue
        parsed = _parse_enum_declaration(tokens, index)
        if parsed is None:
            index += 1
            continue
        declaration, index = parsed
        declarations.append(declaration)
    return tuple(declarations)


def _parse_enum_declaration(
    tokens: Sequence[Token],
    start: int,
) -> tuple[_ProjectEnumDeclaration, int] | None:
    index = _skip_newlines(tokens, start + 1)
    if index >= len(tokens) or tokens[index].kind != "IDENT":
        return None
    enum_name = tokens[index].value
    index = _skip_newlines(tokens, index + 1)
    if index >= len(tokens) or tokens[index].value != "{":
        return None
    index += 1

    members: list[_ProjectEnumMember] = []
    while index < len(tokens):
        while index < len(tokens) and (
            tokens[index].kind == "NEWLINE" or tokens[index].value in {",", ";"}
        ):
            index += 1
        if index >= len(tokens) or tokens[index].kind == "EOF":
            return None
        if tokens[index].value == "}":
            return _ProjectEnumDeclaration(enum_name, tuple(members)), index + 1
        if tokens[index].kind != "IDENT":
            return None

        member_name = tokens[index].value
        index += 1
        value_tokens: tuple[Token, ...] | None = None
        if index < len(tokens) and tokens[index].value == "=":
            index += 1
            expression_tokens: list[Token] = []
            depth = 0
            while index < len(tokens):
                current = tokens[index]
                if depth == 0 and (
                    current.kind in {"NEWLINE", "EOF"}
                    or current.value in {",", "}"}
                ):
                    break
                if current.value in {"(", "["}:
                    depth += 1
                elif current.value in {")",
                    "]",
                } and depth > 0:
                    depth -= 1
                expression_tokens.append(current)
                index += 1
            if not expression_tokens:
                return None
            value_tokens = tuple(expression_tokens)
        members.append(_ProjectEnumMember(member_name, value_tokens))

    return None


def _skip_newlines(tokens: Sequence[Token], index: int) -> int:
    while index < len(tokens) and tokens[index].kind == "NEWLINE":
        index += 1
    return index


def _evaluate_project_enums(
    declarations: Sequence[_ProjectEnumDeclaration],
    macro_values: Mapping[str, str],
) -> dict[str, dict[str, int]]:
    enum_values: dict[str, dict[str, int]] = {}
    pending = list(declarations)
    while pending:
        unresolved: list[_ProjectEnumDeclaration] = []
        made_progress = False
        for declaration in pending:
            if declaration.name in enum_values:
                continue
            try:
                values = _evaluate_project_enum_declaration(
                    declaration,
                    enum_values,
                    macro_values,
                )
            except GMLTranspileError:
                unresolved.append(declaration)
                continue
            enum_values[declaration.name] = values
            made_progress = True
        if not made_progress:
            break
        pending = unresolved
    return enum_values


def _evaluate_project_enum_declaration(
    declaration: _ProjectEnumDeclaration,
    enum_values: Mapping[str, Mapping[str, int]],
    macro_values: Mapping[str, str],
) -> dict[str, int]:
    current_values: dict[str, int] = {}
    next_integer_value = 0
    for member in declaration.members:
        if member.value_tokens is None:
            value = next_integer_value
        else:
            value = _evaluate_enum_value_tokens(
                member.value_tokens,
                enum_values,
                current_values,
                macro_values,
            )
        current_values[member.name] = value
        next_integer_value = value + 1
    return current_values


__all__ = ["collect_project_enum_values"]
