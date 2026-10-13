# pyright: reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from typing import Iterable, Mapping, MutableMapping

from .emitter import emit_gml_expression
from .expression_models import (
    Call as _Call,
    Expression as _Expression,
    FunctionLiteral as _FunctionLiteral,
    GMLExpression,
    Grouped as _Grouped,
)
from .expression_parser import parse_gml_expression
from .shared_models import (
    ScopeContext,
    ScopeContext as _ScopeContext,
    StaticDeclaration,
    StaticDeclaration as _StaticDeclaration,
)


def _emit_static_initialization_lines(
    static_scope_name: str | None,
    static_scope_id: str | None,
    declarations: Iterable[_StaticDeclaration],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
    enum_values: MutableMapping[str, dict[str, int]],
    enum_names: Iterable[str],
    macro_values: Mapping[str, str],
) -> list[str]:
    if static_scope_name is None or static_scope_id is None:
        return []

    initializer_names = set(local_names)
    initializers: list[str] = []
    for declaration in declarations:
        value_expr = parse_gml_expression(
            declaration.value_source,
            enum_values,
            enum_names,
            macro_values=macro_values,
            scope_context=scope_context,
        )
        value = _emit_static_value(value_expr, initializer_names, scope_context)
        initializers.append(f"[{json.dumps(declaration.name)}, func(): return {value}]")
    return [
        f"var {static_scope_name} = GMRuntime.gml_static_scope({json.dumps(static_scope_id)})",
        f"GMRuntime.gml_static_initialize({static_scope_name}, [{', '.join(initializers)}])",
    ]


def _emit_static_value(
    value_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> str:
    # A static function belongs to the constructor, not to the struct that
    # happened to be built first: it is unbound, so the struct it is called
    # through (inst.method()) is its self, as in the runner's static_get.
    unwrapped = value_expr
    while isinstance(unwrapped, _Grouped):
        unwrapped = unwrapped.expr
    if not isinstance(unwrapped, _FunctionLiteral):
        return emit_gml_expression(
            value_expr,
            local_names,
            scope_context=scope_context,
        ).text
    function_literal = emit_gml_expression(
        unwrapped,
        local_names,
        bind_function_literals=False,
        scope_context=scope_context,
    ).text
    helper = "gml_receiver_constructor" if unwrapped.is_constructor else "gml_receiver_method"
    return f"GMRuntime.{helper}(GMRuntime.gml_undefined(), {function_literal})"


def _emit_constructor_inheritance_line(
    parent_constructor: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
    constructor_scope_context: _ScopeContext,
) -> str:
    parent_expr = parent_constructor
    args: tuple[_Expression, ...] = ()
    if isinstance(parent_constructor, _Call):
        parent_expr = parent_constructor.callee
        args = parent_constructor.args

    constructor = emit_gml_expression(
        parent_expr,
        local_names,
        scope_context=constructor_scope_context,
    ).text
    emitted_args = ", ".join(
        emit_gml_expression(arg, local_names, scope_context=scope_context).text
        for arg in args
    )
    return (
        "GMRuntime.gml_constructor_inherit("
        f"_gml_constructor_self, {constructor}, [{emitted_args}], "
        f"{scope_context.self_expression}, {scope_context.other_expression})"
    )


def emit_constructor_inheritance_line(
    parent_constructor: GMLExpression,
    local_names: Iterable[str],
    scope_context: ScopeContext,
    constructor_scope_context: ScopeContext,
) -> str:
    return _emit_constructor_inheritance_line(
        parent_constructor,
        local_names,
        scope_context,
        constructor_scope_context,
    )


def emit_static_initialization_lines(
    static_scope_name: str | None,
    static_scope_id: str | None,
    declarations: Iterable[StaticDeclaration],
    local_names: Iterable[str],
    scope_context: ScopeContext,
    enum_values: MutableMapping[str, dict[str, int]],
    enum_names: Iterable[str],
    macro_values: Mapping[str, str],
) -> list[str]:
    return _emit_static_initialization_lines(
        static_scope_name,
        static_scope_id,
        declarations,
        local_names,
        scope_context,
        enum_values,
        enum_names,
        macro_values,
    )
