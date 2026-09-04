# pyright: reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from typing import Iterable, Mapping, MutableMapping

from .emitter import emit_gml_expression, emit_gml_truthy_expression
from .enum_helpers import reject_enum_mutation_expression
from .extension_functions import (
    normalize_extension_function_mappings,
    normalize_extension_functions,
)
from .expression_parser import parse_gml_expression
from .shared_models import ScopeContext as _ScopeContext
from .utils import normalize_local_names, normalize_scope_context, scope_context_with_global_names


def transpile_gml_expression(
    source: str,
    local_names: Iterable[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    global_names: Iterable[str] | None = None,
    asset_names: Iterable[str] | None = None,
    extension_functions: object = None,
    extension_function_mappings: object = None,
) -> str:
    """Transpile a single GML expression to a GDScript expression."""
    scope_context = scope_context_with_global_names(
        normalize_scope_context(scope_context),
        global_names,
        asset_names=asset_names,
        extension_functions=normalize_extension_functions(extension_functions),
        extension_function_mappings=normalize_extension_function_mappings(extension_function_mappings),
    )
    expr = parse_gml_expression(
        source,
        enum_values=enum_values,
        enum_names=enum_names,
        macro_values=macro_values,
        scope_context=scope_context,
    )
    reject_enum_mutation_expression(expr, enum_names)
    return emit_gml_expression(
        expr,
        normalize_local_names(local_names),
        scope_context=scope_context,
    ).text


def transpile_gml_condition(
    source: str,
    local_names: Iterable[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    global_names: Iterable[str] | None = None,
    asset_names: Iterable[str] | None = None,
    extension_functions: object = None,
    extension_function_mappings: object = None,
) -> str:
    """Transpile a GML condition using GameMaker truthiness semantics."""
    scope_context = scope_context_with_global_names(
        normalize_scope_context(scope_context),
        global_names,
        asset_names=asset_names,
        extension_functions=normalize_extension_functions(extension_functions),
        extension_function_mappings=normalize_extension_function_mappings(extension_function_mappings),
    )
    expr = parse_gml_expression(
        source,
        enum_values=enum_values,
        enum_names=enum_names,
        macro_values=macro_values,
        scope_context=scope_context,
    )
    reject_enum_mutation_expression(expr, enum_names)
    return emit_gml_truthy_expression(
        expr,
        normalize_local_names(local_names),
        scope_context=scope_context,
    )
