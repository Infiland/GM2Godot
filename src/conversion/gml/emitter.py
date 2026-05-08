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
)
from src.conversion.gml.builtins import emit_builtin_call, emit_name
from src.conversion.gml.operators import (
    BINARY_PRECEDENCE,
    OPERATOR_REPLACEMENTS,
    POSTFIX_PRECEDENCE,
    PRIMARY_PRECEDENCE,
    RIGHT_ASSOCIATIVE,
    TERNARY_PRECEDENCE,
    UNARY_PRECEDENCE,
)


def emit_expression(expr, local_names=None):
    local_names = frozenset(local_names or [])
    if isinstance(expr, Literal):
        return expr.value, PRIMARY_PRECEDENCE
    if isinstance(expr, Name):
        return emit_name(expr.value, local_names), PRIMARY_PRECEDENCE
    if isinstance(expr, Grouped):
        return f"({emit_expression(expr.expr, local_names)[0]})", PRIMARY_PRECEDENCE
    if isinstance(expr, Unary):
        operand = _emit_child(expr.operand, UNARY_PRECEDENCE, local_names=local_names)
        if expr.operator == "!":
            return f"not {operand}", UNARY_PRECEDENCE
        if expr.operator == "not":
            return f"not {operand}", UNARY_PRECEDENCE
        return f"{expr.operator}{operand}", UNARY_PRECEDENCE
    if isinstance(expr, Binary):
        return _emit_binary(expr, local_names)
    if isinstance(expr, Ternary):
        condition = _emit_child(expr.condition, TERNARY_PRECEDENCE, local_names=local_names)
        true_expr = _emit_child(expr.true_expr, TERNARY_PRECEDENCE, local_names=local_names)
        false_expr = _emit_child(expr.false_expr, TERNARY_PRECEDENCE, local_names=local_names)
        return f"{true_expr} if {condition} else {false_expr}", TERNARY_PRECEDENCE
    if isinstance(expr, Call):
        builtin_call = emit_builtin_call(expr, lambda arg: emit_expression(arg, local_names)[0])
        if builtin_call is not None:
            return builtin_call, POSTFIX_PRECEDENCE
        callee = _emit_child(expr.callee, POSTFIX_PRECEDENCE, local_names=local_names)
        args = ", ".join(emit_expression(arg, local_names)[0] for arg in expr.args)
        return f"{callee}({args})", POSTFIX_PRECEDENCE
    if isinstance(expr, Index):
        target = _emit_child(expr.target, POSTFIX_PRECEDENCE, local_names=local_names)
        index = emit_expression(expr.index, local_names)[0]
        return f"{target}[{index}]", POSTFIX_PRECEDENCE
    if isinstance(expr, Member):
        target = _emit_child(expr.target, POSTFIX_PRECEDENCE, local_names=local_names)
        return f"{target}.{expr.member}", POSTFIX_PRECEDENCE
    raise GMLTranspileError("Unknown expression node")


def _emit_binary(expr, local_names):
    operator = OPERATOR_REPLACEMENTS.get(expr.operator, expr.operator)

    if expr.operator == "div":
        left = emit_expression(expr.left, local_names)[0]
        right = emit_expression(expr.right, local_names)[0]
        return f"int({left} / {right})", PRIMARY_PRECEDENCE

    if expr.operator == "??":
        left = emit_expression(expr.left, local_names)[0]
        right = _emit_child(expr.right, TERNARY_PRECEDENCE, local_names=local_names)
        return f"{left} if {left} != null else {right}", TERNARY_PRECEDENCE

    if expr.operator == "/":
        left = emit_expression(expr.left, local_names)[0]
        right = emit_expression(expr.right, local_names)[0]
        return f"GMRuntime.gml_div({left}, {right})", POSTFIX_PRECEDENCE

    precedence = BINARY_PRECEDENCE[expr.operator]
    left = _emit_child(expr.left, precedence, local_names=local_names)
    right = _emit_child(
        expr.right,
        precedence,
        is_right_child=True,
        parent_operator=expr.operator,
        local_names=local_names,
    )
    return f"{left} {operator} {right}", precedence


def _emit_child(expr, parent_precedence, is_right_child=False, parent_operator=None, local_names=None):
    text, precedence = emit_expression(expr, local_names)
    needs_parentheses = precedence < parent_precedence
    if is_right_child and precedence == parent_precedence and parent_operator not in RIGHT_ASSOCIATIVE:
        needs_parentheses = True
    if needs_parentheses:
        return f"({text})"
    return text
