# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from typing import Iterable, Mapping, MutableMapping

from .emitter import _emit_expression
from .expression_parser import _parse_gml_expression
from .model import _Call, _Expression, _ScopeContext, _StaticDeclaration

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
        value_expr = _parse_gml_expression(
            declaration.value_source,
            enum_values,
            enum_names,
            macro_values=macro_values,
            scope_context=scope_context,
        )
        value = _emit_expression(
            value_expr,
            initializer_names,
            scope_context=scope_context,
        )[0]
        initializers.append(f"[{json.dumps(declaration.name)}, func(): return {value}]")
    return [
        f"var {static_scope_name} = GMRuntime.gml_static_scope({json.dumps(static_scope_id)})",
        f"GMRuntime.gml_static_initialize({static_scope_name}, [{', '.join(initializers)}])",
    ]


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

    constructor = _emit_expression(
        parent_expr,
        local_names,
        scope_context=constructor_scope_context,
    )[0]
    emitted_args = ", ".join(
        _emit_expression(arg, local_names, scope_context=scope_context)[0]
        for arg in args
    )
    return (
        "GMRuntime.gml_constructor_inherit("
        f"_gml_constructor_self, {constructor}, [{emitted_args}], "
        f"{scope_context.self_expression}, {scope_context.other_expression})"
    )
