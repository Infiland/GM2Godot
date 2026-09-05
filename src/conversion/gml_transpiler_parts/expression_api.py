from __future__ import annotations

from typing import Final, Iterable, Mapping, MutableMapping

from .emitter import (
    emit_gml_expression,
    emit_gml_truthy_expression,
    emit_instance_keyword_argument,
    name_resolves_to_global,
    uses_direct_builtin_instance_members,
    uses_direct_member_access,
)
from .enum_helpers import (
    evaluate_enum_value_tokens,
    reject_constant_assignment_target_name,
    reject_constant_declaration_name,
    reject_enum_assignment_target,
    reject_enum_mutation_expression,
    reject_readonly_builtin_assignment_target,
)
from .expression_parser import parse_gml_expression
from .expression_service import (
    transpile_gml_condition as _transpile_gml_condition_impl,
    transpile_gml_expression as _transpile_gml_expression_impl,
)
from .function_helpers import emit_constructor_inheritance_line, emit_static_initialization_lines
from .shared_models import ScopeContext


def transpile_gml_condition(
    source: str,
    local_names: Iterable[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    global_names: Iterable[str] | None = None,
    asset_names: Iterable[str] | None = None,
    extension_functions: object = None,
    extension_function_mappings: object = None,
) -> str:
    return _transpile_gml_condition_impl(
        source,
        local_names=local_names,
        enum_values=enum_values,
        enum_names=enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
        global_names=global_names,
        asset_names=asset_names,
        extension_functions=extension_functions,
        extension_function_mappings=extension_function_mappings,
    )


def transpile_gml_expression(
    source: str,
    local_names: Iterable[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    global_names: Iterable[str] | None = None,
    asset_names: Iterable[str] | None = None,
    extension_functions: object = None,
    extension_function_mappings: object = None,
) -> str:
    return _transpile_gml_expression_impl(
        source,
        local_names=local_names,
        enum_values=enum_values,
        enum_names=enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
        global_names=global_names,
        asset_names=asset_names,
        extension_functions=extension_functions,
        extension_function_mappings=extension_function_mappings,
    )


__all__: Final[tuple[str, ...]] = (
    "emit_constructor_inheritance_line",
    "emit_gml_expression",
    "emit_gml_truthy_expression",
    "emit_instance_keyword_argument",
    "emit_static_initialization_lines",
    "evaluate_enum_value_tokens",
    "name_resolves_to_global",
    "parse_gml_expression",
    "reject_constant_assignment_target_name",
    "reject_constant_declaration_name",
    "reject_enum_assignment_target",
    "reject_enum_mutation_expression",
    "reject_readonly_builtin_assignment_target",
    "transpile_gml_condition",
    "transpile_gml_expression",
    "uses_direct_builtin_instance_members",
    "uses_direct_member_access",
)
