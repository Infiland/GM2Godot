# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from typing import Iterable, Mapping

from .constants import _GML_BUILTIN_CONSTANT_IDENTIFIERS, _READ_ONLY_BUILTIN_VARIABLES
from .expression_parser import _parse_gml_expression
from .model import (
    GMLTranspileError,
    _ArrayLiteral,
    _Binary,
    _Call,
    _DSMapAccess,
    _DSListAccess,
    _Expression,
    _Grouped,
    _Index,
    _Member,
    _Name,
    _NumberLiteral,
    _StructAccess,
    _StructLiteral,
    _Ternary,
    _Token,
    _Unary,
)
from .tokens import _expression_tokens
from .utils import _normalize_local_names, _tokens_to_source, _unwrap_grouped_expression

def _evaluate_enum_value_tokens(
    tokens: Iterable[_Token],
    enum_values: Mapping[str, Mapping[str, int]],
    current_enum_values: Mapping[str, int],
    macro_values: Mapping[str, str] | None = None,
) -> int:
    source = _tokens_to_source(tokens)
    value = _evaluate_enum_expression(
        _parse_gml_expression(source, macro_values=macro_values),
        enum_values,
        current_enum_values,
    )
    if value is None:
        raise GMLTranspileError("Enum values must be integer compile-time constants")
    return value


def _evaluate_enum_expression(
    expr: _Expression,
    enum_values: Mapping[str, Mapping[str, int]],
    current_enum_values: Mapping[str, int],
) -> int | None:
    if isinstance(expr, _NumberLiteral):
        return _parse_enum_int_literal(expr)
    if isinstance(expr, _Grouped):
        return _evaluate_enum_expression(expr.expr, enum_values, current_enum_values)
    if isinstance(expr, _Name):
        if expr.value == "true":
            return 1
        if expr.value == "false":
            return 0
        return current_enum_values.get(expr.value)
    if isinstance(expr, _Member) and isinstance(expr.target, _Name):
        enum_members = enum_values.get(expr.target.value)
        if enum_members is None:
            return None
        return enum_members.get(expr.member)
    if isinstance(expr, _Unary):
        operand = _evaluate_enum_expression(expr.operand, enum_values, current_enum_values)
        if operand is None:
            return None
        if expr.operator == "+":
            return operand
        if expr.operator == "-":
            return -operand
        if expr.operator == "~":
            return ~operand
        return None
    if isinstance(expr, _Binary):
        left = _evaluate_enum_expression(expr.left, enum_values, current_enum_values)
        right = _evaluate_enum_expression(expr.right, enum_values, current_enum_values)
        if left is None or right is None:
            return None
        return _evaluate_enum_binary(expr.operator, left, right)
    if isinstance(expr, _Call) and isinstance(expr.callee, _Name):
        args: list[int] = []
        for arg in expr.args:
            arg_value = _evaluate_enum_expression(arg, enum_values, current_enum_values)
            if arg_value is None:
                return None
            args.append(arg_value)
        return _evaluate_enum_call(expr.callee.value, args)
    return None


def _parse_enum_int_literal(expr: _NumberLiteral) -> int | None:
    if expr.is_float_like:
        return None
    try:
        return int(expr.value, 0)
    except ValueError:
        return None


def _evaluate_enum_binary(operator: str, left: int, right: int) -> int | None:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator in ("div", "/"):
        if right == 0:
            return None
        return int(left / right)
    if operator in ("mod", "%"):
        if right == 0:
            return None
        return left % right
    if operator == "<<":
        return left << right
    if operator == ">>":
        return left >> right
    if operator == "&":
        return left & right
    if operator == "|":
        return left | right
    if operator == "^":
        return left ^ right
    return None


def _evaluate_enum_call(function_name: str, args: Iterable[int]) -> int | None:
    arg_values = list(args)
    if function_name in ("int64", "real") and len(arg_values) == 1:
        return int(arg_values[0])
    if function_name == "bool" and len(arg_values) == 1:
        return 1 if arg_values[0] else 0
    if function_name == "abs" and len(arg_values) == 1:
        return abs(int(arg_values[0]))
    return None


def _reject_enum_assignment_target(
    target_expr: _Expression,
    enum_names: Iterable[str] | None,
) -> None:
    enum_name_set = frozenset(enum_names or [])
    if not enum_name_set:
        return

    unwrapped_target = _unwrap_grouped_expression(target_expr)
    if _is_enum_reference(unwrapped_target, enum_name_set):
        raise GMLTranspileError("Cannot assign to enum")
    if _target_chain_starts_with_enum(unwrapped_target, enum_name_set):
        raise GMLTranspileError("Cannot assign to enum member")


def _reject_readonly_builtin_assignment_target(
    target_expr: _Expression,
    local_names: Iterable[str],
) -> None:
    local_name_set = _normalize_local_names(local_names)
    unwrapped_target = _unwrap_grouped_expression(target_expr)
    if isinstance(unwrapped_target, _Index):
        unwrapped_target = _unwrap_grouped_expression(unwrapped_target.target)
    if isinstance(unwrapped_target, _Name):
        name = unwrapped_target.value
        if name not in local_name_set and name in _READ_ONLY_BUILTIN_VARIABLES:
            raise GMLTranspileError(f"Cannot assign to read-only built-in variable {name}")


def _reject_constant_assignment_target_name(
    target_source: str,
    macro_names: Iterable[str],
) -> None:
    target_name = _raw_identifier_target_name(target_source)
    if target_name is None:
        return
    if target_name in _GML_BUILTIN_CONSTANT_IDENTIFIERS:
        raise GMLTranspileError(f"Cannot assign to built-in constant {target_name}")
    if target_name in macro_names:
        raise GMLTranspileError(f"Cannot assign to macro constant {target_name}")


def _reject_constant_declaration_name(
    name: str,
    macro_names: Iterable[str],
) -> None:
    if name in _GML_BUILTIN_CONSTANT_IDENTIFIERS:
        raise GMLTranspileError(f"Cannot redeclare built-in constant {name}")
    if name in macro_names:
        raise GMLTranspileError(f"Cannot redeclare macro constant {name}")


def _raw_identifier_target_name(target_source: str) -> str | None:
    tokens = _expression_tokens(target_source)
    if len(tokens) == 2 and tokens[0].kind == "IDENT" and tokens[1].kind == "EOF":
        return tokens[0].value
    return None


def _reject_enum_mutation_expression(
    expr: _Expression,
    enum_names: Iterable[str] | None,
) -> None:
    enum_name_set = frozenset(enum_names or [])
    if not enum_name_set:
        return

    if isinstance(expr, _Call):
        if (
            isinstance(expr.callee, _Name)
            and expr.callee.value in ("struct_set", "struct_remove")
            and expr.args
            and _is_enum_reference(expr.args[0], enum_name_set)
        ):
            raise GMLTranspileError("Cannot mutate enum member")
        _reject_enum_mutation_expression(expr.callee, enum_name_set)
        for arg in expr.args:
            _reject_enum_mutation_expression(arg, enum_name_set)
        return
    if isinstance(expr, _Grouped):
        _reject_enum_mutation_expression(expr.expr, enum_name_set)
        return
    if isinstance(expr, _Unary):
        _reject_enum_mutation_expression(expr.operand, enum_name_set)
        return
    if isinstance(expr, _Binary):
        _reject_enum_mutation_expression(expr.left, enum_name_set)
        _reject_enum_mutation_expression(expr.right, enum_name_set)
        return
    if isinstance(expr, _Ternary):
        _reject_enum_mutation_expression(expr.condition, enum_name_set)
        _reject_enum_mutation_expression(expr.true_expr, enum_name_set)
        _reject_enum_mutation_expression(expr.false_expr, enum_name_set)
        return
    if isinstance(expr, _ArrayLiteral):
        for element in expr.elements:
            _reject_enum_mutation_expression(element, enum_name_set)
        return
    if isinstance(expr, _StructLiteral):
        for _field_name, field_value in expr.fields:
            _reject_enum_mutation_expression(field_value, enum_name_set)
        return
    if isinstance(expr, _Index):
        _reject_enum_mutation_expression(expr.target, enum_name_set)
        _reject_enum_mutation_expression(expr.index, enum_name_set)
        return
    if isinstance(expr, _StructAccess):
        _reject_enum_mutation_expression(expr.target, enum_name_set)
        _reject_enum_mutation_expression(expr.key, enum_name_set)
        return
    if isinstance(expr, _DSMapAccess):
        _reject_enum_mutation_expression(expr.target, enum_name_set)
        _reject_enum_mutation_expression(expr.key, enum_name_set)
        return
    if isinstance(expr, _DSListAccess):
        _reject_enum_mutation_expression(expr.target, enum_name_set)
        _reject_enum_mutation_expression(expr.index, enum_name_set)
        return
    if isinstance(expr, _Member):
        _reject_enum_mutation_expression(expr.target, enum_name_set)

def _is_enum_reference(expr: _Expression, enum_names: Iterable[str]) -> bool:
    unwrapped_expr = _unwrap_grouped_expression(expr)
    return isinstance(unwrapped_expr, _Name) and unwrapped_expr.value in enum_names


def _target_chain_starts_with_enum(expr: _Expression, enum_names: Iterable[str]) -> bool:
    unwrapped_expr = _unwrap_grouped_expression(expr)
    if isinstance(unwrapped_expr, _Member | _StructAccess | _DSMapAccess | _DSListAccess | _Index):
        return _is_enum_reference(unwrapped_expr.target, enum_names) or _target_chain_starts_with_enum(
            unwrapped_expr.target,
            enum_names,
        )
    return False
