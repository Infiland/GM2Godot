# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from typing import Iterable

from .constants import _ASSIGNMENT_OPERATORS
from .model import (
    _ArrayLiteral,
    _AssignmentOperator,
    _Binary,
    _Call,
    _DEFAULT_SCOPE_CONTEXT,
    _DSMapAccess,
    _DSListAccess,
    _Expression,
    _FunctionLiteral,
    _Grouped,
    _Index,
    _Member,
    _NewCall,
    _ScopeContext,
    _StructAccess,
    _StructLiteral,
    _Ternary,
    _Token,
    _Unary,
)

def _normalize_local_names(local_names: Iterable[str] | None) -> frozenset[str]:
    return frozenset(local_names or [])


def _tokens_to_source(tokens: Iterable[_Token]) -> str:
    return " ".join(token.value for token in tokens if token.kind not in ("EOF", "NEWLINE"))

def _unwrap_grouped_expression(expr: _Expression) -> _Expression:
    while isinstance(expr, _Grouped):
        expr = expr.expr
    return expr

def _split_top_level_tokens(tokens: Iterable[_Token], separator: str) -> list[list[_Token]]:
    parts: list[list[_Token]] = [[]]
    depth = 0
    for token in tokens:
        if token.value in "([{":
            depth += 1
        elif token.value in ")]}" and depth > 0:
            depth -= 1

        if depth == 0 and token.value == separator:
            parts.append([])
            continue
        parts[-1].append(token)
    return parts


def _indent_lines(lines: Iterable[str]) -> list[str]:
    return [f"\t{line}" if line else "" for line in lines]


def _insert_lines_before_continue(lines: Iterable[str], inserted_lines: Iterable[str]) -> list[str]:
    inserted = list(inserted_lines)
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip("\t")
        if stripped == "continue":
            indentation = line[: len(line) - len(stripped)]
            result.extend(f"{indentation}{inserted_line}" for inserted_line in inserted)
        result.append(line)
    return result


def _insert_until_check_before_continue(lines: Iterable[str], condition: str) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip("\t")
        if stripped == "continue":
            indentation = line[: len(line) - len(stripped)]
            result.append(f"{indentation}if {condition}:")
            result.append(f"{indentation}\tbreak")
        result.append(line)
    return result


def _next_generated_name_from_counter(generated_counter: list[int], prefix: str) -> str:
    index = generated_counter[0]
    generated_counter[0] += 1
    return f"{prefix}_{index}"


def _expression_needs_assignment_cache(expr: _Expression) -> bool:
    if isinstance(expr, _Call | _NewCall | _FunctionLiteral):
        return True
    if isinstance(expr, _Grouped):
        return _expression_needs_assignment_cache(expr.expr)
    if isinstance(expr, _Unary):
        return _expression_needs_assignment_cache(expr.operand)
    if isinstance(expr, _Binary):
        return (
            _expression_needs_assignment_cache(expr.left)
            or _expression_needs_assignment_cache(expr.right)
        )
    if isinstance(expr, _Ternary):
        return (
            _expression_needs_assignment_cache(expr.condition)
            or _expression_needs_assignment_cache(expr.true_expr)
            or _expression_needs_assignment_cache(expr.false_expr)
        )
    if isinstance(expr, _ArrayLiteral):
        return any(_expression_needs_assignment_cache(element) for element in expr.elements)
    if isinstance(expr, _StructLiteral):
        return any(
            _expression_needs_assignment_cache(field_value)
            for _field_name, field_value in expr.fields
        )
    if isinstance(expr, _Index):
        return (
            _expression_needs_assignment_cache(expr.target)
            or _expression_needs_assignment_cache(expr.index)
        )
    if isinstance(expr, _StructAccess):
        return (
            _expression_needs_assignment_cache(expr.target)
            or _expression_needs_assignment_cache(expr.key)
        )
    if isinstance(expr, _DSMapAccess):
        return (
            _expression_needs_assignment_cache(expr.target)
            or _expression_needs_assignment_cache(expr.key)
        )
    if isinstance(expr, _DSListAccess):
        return (
            _expression_needs_assignment_cache(expr.target)
            or _expression_needs_assignment_cache(expr.index)
        )
    if isinstance(expr, _Member):
        return _expression_needs_assignment_cache(expr.target)
    return False


def _cache_assignment_part(
    prelude_lines: list[str],
    expr: _Expression,
    emitted: str,
    generated_counter: list[int],
    prefix: str,
) -> str:
    if not _expression_needs_assignment_cache(expr):
        return emitted
    temp_name = _next_generated_name_from_counter(generated_counter, prefix)
    prelude_lines.append(f"var {temp_name} = {emitted}")
    return temp_name


def _normalize_scope_context(scope_context: _ScopeContext | None) -> _ScopeContext:
    return scope_context if scope_context is not None else _DEFAULT_SCOPE_CONTEXT


def _scope_context_with_global_names(
    scope_context: _ScopeContext,
    global_names: Iterable[str] | None,
    top_level_global_scope: bool | None = None,
    asset_names: Iterable[str] | None = None,
    static_prefix: str | None = None,
) -> _ScopeContext:
    names = set(scope_context.global_names)
    names.update(global_names or [])
    assets = set(scope_context.asset_names)
    assets.update(asset_names or [])
    return _ScopeContext(
        self_expression=scope_context.self_expression,
        other_expression=scope_context.other_expression,
        instance_target=scope_context.instance_target,
        global_scope=scope_context.global_scope if top_level_global_scope is None else top_level_global_scope,
        global_names=frozenset(names),
        asset_names=frozenset(assets),
        static_scope=scope_context.static_scope,
        static_names=scope_context.static_names,
        static_prefix=scope_context.static_prefix if static_prefix is None else static_prefix,
    )


def _macro_configuration_matches(configuration: str, active_configuration: str | None) -> bool:
    if active_configuration is None:
        return False
    return configuration.casefold() == active_configuration.casefold()

def _strip_comments(source: str) -> str:
    result: list[str] = []
    index = 0
    in_string: str | None = None
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


def _join_macro_continuation_lines(source: str) -> str:
    lines: list[str] = []
    pending_macro: str | None = None
    for line in source.splitlines():
        current = line if pending_macro is None else f"{pending_macro} {line.lstrip()}"
        if current.lstrip().startswith("#macro") and current.rstrip().endswith("\\"):
            pending_macro = current.rstrip()[:-1].rstrip()
            continue
        lines.append(current)
        pending_macro = None

    if pending_macro is not None:
        lines.append(pending_macro)

    return "\n".join(lines)


def _split_statements(source: str) -> list[str]:  # pyright: ignore[reportUnusedFunction]
    statements: list[str] = []
    start = 0
    depth = 0
    in_string: str | None = None
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

def _split_assignment(statement: str) -> tuple[str, _AssignmentOperator, str] | None:
    depth = 0
    in_string: str | None = None
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


def _is_comparison_assignment_false_positive(statement: str, index: int) -> bool:
    previous_char = statement[index - 1] if index > 0 else ""
    next_char = statement[index + 1] if index + 1 < len(statement) else ""
    return previous_char in "!<>=?" or next_char == "="


def _split_top_level(source: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string: str | None = None
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
