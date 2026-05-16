# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from typing import Iterable, Mapping, MutableMapping, MutableSet

from .constants import (
    _BUILTIN_ARRAY_VARIABLES,
    _BUILTIN_GLOBAL_VARIABLES,
    _BUILTIN_INSTANCE_VARIABLES,
    _COMPOUND_RUNTIME_FUNCTIONS,
    _GML_LITERAL_IDENTIFIERS,
)
from .emitter import (
    _emit_expression,
    _emit_instance_keyword_argument,
    _name_resolves_to_global,
    _uses_direct_member_access,
)
from .enum_helpers import (
    _reject_constant_assignment_target_name,
    _reject_constant_declaration_name,
    _reject_enum_assignment_target,
    _reject_readonly_builtin_assignment_target,
)
from .expression_parser import _parse_gml_expression
from .expression_service import transpile_gml_expression
from .identifiers import (
    _is_plain_identifier,
    _reject_asset_identifier_name,
    _sanitize_gdscript_identifier,
    _validate_gml_identifier,
)
from .model import (
    GMLTranspileError,
    _Call,
    _DSGridAccess,
    _DSMapAccess,
    _DSListAccess,
    _Expression,
    _Index,
    _IncrementDelta,
    _IncrementMode,
    _Member,
    _Name,
    _ScopeContext,
    _StructAccess,
)
from .tokens import _expression_tokens
from .utils import (
    _cache_assignment_part,
    _next_generated_name_from_counter,
    _normalize_scope_context,
    _split_assignment,
    _split_top_level,
    _unwrap_grouped_expression,
)

_MOTION_SYNCHRONIZED_BUILTINS = frozenset({"direction", "hspeed", "speed", "vspeed"})


def _transpile_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    loop_depth: int = 0,
    continue_depth: int = 0,
    return_depth: int = 0,
    finally_depth: int = 0,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    inherited_event_call: str | None = None,
    macro_values: Mapping[str, str] | None = None,
    generated_counter: list[int] | None = None,
) -> list[str]:
    if not statement:
        return []

    if local_names is None:
        local_names = set()
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]

    if statement == "return":
        _reject_finally_control_flow(finally_depth)
        if return_depth <= 0:
            raise GMLTranspileError("return used outside a function or method")
        return ["return"]
    if statement.startswith("return "):
        _reject_finally_control_flow(finally_depth)
        if return_depth <= 0:
            raise GMLTranspileError("return used outside a function or method")
        return_value = transpile_gml_expression(
            statement[7:].strip(),
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        return [f"return {return_value}"]
    if statement == "break":
        _reject_finally_control_flow(finally_depth)
        if loop_depth <= 0:
            raise GMLTranspileError("break used outside a loop")
        return ["break"]
    if statement == "continue":
        _reject_finally_control_flow(finally_depth)
        if continue_depth <= 0:
            raise GMLTranspileError("continue used outside a loop")
        return ["continue"]
    if statement == "exit":
        _reject_finally_control_flow(finally_depth)
        return ["return"]
    event_inherited_lines = _transpile_event_inherited_statement(statement, inherited_event_call)
    if event_inherited_lines is not None:
        return event_inherited_lines
    if statement == "throw":
        raise GMLTranspileError("throw requires an expression")
    if statement.startswith("throw "):
        thrown_value = transpile_gml_expression(
            statement[6:].strip(),
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        return [f"return GMRuntime.gml_throw({thrown_value})"]

    if statement.startswith("delete "):
        target_source = statement[7:].strip()
        _reject_constant_assignment_target_name(target_source, macro_values.keys())
        target_expr = _parse_gml_expression(
            target_source,
            enum_values,
            enum_names,
            macro_values=macro_values,
            scope_context=scope_context,
        )
        _reject_enum_assignment_target(target_expr, enum_names)
        _reject_readonly_builtin_assignment_target(target_expr, local_names)
        if isinstance(target_expr, _Name):
            _reject_asset_identifier_name(target_expr.value, scope_context)
        static_target = _static_scope_assignment_parts(target_expr, scope_context)
        if static_target is not None:
            static_scope, member_name = static_target
            return [f"GMRuntime.gml_struct_set({static_scope}, {member_name}, GMRuntime.gml_undefined())"]
        global_target = _global_scope_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        if global_target is not None:
            global_scope, member_name = global_target
            return [f"GMRuntime.gml_struct_set({global_scope}, {member_name}, GMRuntime.gml_undefined())"]
        if not isinstance(target_expr, _Name):
            raise GMLTranspileError("delete can only be used with variables")
        scoped_target = _scoped_instance_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        if scoped_target is not None:
            instance_target, member_name = scoped_target
            return [
                "GMRuntime.gml_variable_instance_set("
                f"{instance_target}, {member_name}, GMRuntime.gml_undefined())"
            ]
        target = _emit_expression(target_expr, local_names, scope_context=scope_context)[0]
        return [f"{target} = GMRuntime.gml_undefined()"]

    if statement.startswith("var "):
        return _transpile_var_statement(
            statement[4:].strip(),
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )

    increment = _parse_increment_statement(statement)
    if increment is not None:
        target, delta = increment
        helper = "gml_add" if delta > 0 else "gml_sub"
        _reject_constant_assignment_target_name(target, macro_values.keys())
        target_expr = _parse_gml_expression(
            target,
            enum_values,
            enum_names,
            macro_values=macro_values,
            scope_context=scope_context,
        )
        if not _is_increment_target_expression(target_expr):
            raise GMLTranspileError("Increment target must be assignable")
        _reject_enum_assignment_target(target_expr, enum_names)
        _reject_readonly_builtin_assignment_target(target_expr, local_names)
        if isinstance(target_expr, _Name):
            _reject_asset_identifier_name(target_expr.value, scope_context)
        static_target = _static_scope_assignment_parts(target_expr, scope_context)
        if static_target is not None:
            static_scope, member_name = static_target
            current_value = f"GMRuntime.gml_struct_get({static_scope}, {member_name})"
            return [
                f"GMRuntime.gml_struct_set({static_scope}, {member_name}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        global_target = _global_scope_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        if global_target is not None:
            global_scope, member_name = global_target
            current_value = f"GMRuntime.gml_struct_get({global_scope}, {member_name})"
            return [
                f"GMRuntime.gml_struct_set({global_scope}, {member_name}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        motion_target = _motion_assignment_parts(target_expr, local_names, scope_context)
        if motion_target is not None:
            instance_target, member_name = motion_target
            current_value = _motion_current_value(instance_target, member_name, scope_context)
            return [
                f"GMRuntime.gml_motion_set_{member_name}("
                f"{instance_target}, GMRuntime.{helper}({current_value}, 1))"
            ]
        scoped_target = _scoped_instance_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        if scoped_target is not None:
            instance_target, member_name = scoped_target
            current_value = f"GMRuntime.gml_variable_instance_get({instance_target}, {member_name})"
            return [
                "GMRuntime.gml_variable_instance_set("
                f"{instance_target}, {member_name}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        selector_target = _selector_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if selector_target is not None:
            container, key = selector_target
            prelude_lines: list[str] = []
            if isinstance(target_expr, _Member):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_selector_target",
                )
            current_value = _next_generated_name_from_counter(
                generated_counter,
                "_gml_selector_value",
            )
            return [
                *prelude_lines,
                f"GMRuntime.gml_selector_update({container}, {key}, "
                f"func({current_value}): return GMRuntime.{helper}({current_value}, 1))",
            ]
        if isinstance(target_expr, _Index):
            container = _emit_expression(
                target_expr.target,
                local_names,
                scope_context=scope_context,
            )[0]
            index = _emit_expression(
                target_expr.index,
                local_names,
                scope_context=scope_context,
            )[0]
            prelude_lines: list[str] = []
            container = _cache_assignment_part(
                prelude_lines,
                target_expr.target,
                container,
                generated_counter,
                "_gml_array_target",
            )
            index = _cache_assignment_part(
                prelude_lines,
                target_expr.index,
                index,
                generated_counter,
                "_gml_array_index",
            )
            current_value = f"GMRuntime.gml_array_get({container}, {index})"
            return [
                *prelude_lines,
                f"GMRuntime.gml_array_set({container}, {index}, "
                f"GMRuntime.{helper}({current_value}, 1))",
            ]
        struct_target = _struct_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if struct_target is not None:
            container, key = struct_target
            prelude_lines: list[str] = []
            if isinstance(target_expr, _StructAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_struct_target",
                )
                key = _cache_assignment_part(
                    prelude_lines,
                    target_expr.key,
                    key,
                    generated_counter,
                    "_gml_struct_key",
                )
            elif isinstance(target_expr, _Member):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_struct_target",
                )
            current_value = f"GMRuntime.gml_struct_get({container}, {key})"
            return [
                *prelude_lines,
                f"GMRuntime.gml_struct_set({container}, {key}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        ds_map_target = _ds_map_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_map_target is not None:
            container, key = ds_map_target
            prelude_lines = []
            if isinstance(target_expr, _DSMapAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_map_target",
                )
                key = _cache_assignment_part(
                    prelude_lines,
                    target_expr.key,
                    key,
                    generated_counter,
                    "_gml_map_key",
                )
            current_value = f"GMRuntime.gml_ds_map_find_value({container}, {key})"
            return [
                *prelude_lines,
                f"GMRuntime.gml_ds_map_set({container}, {key}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        ds_list_target = _ds_list_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_list_target is not None:
            container, index = ds_list_target
            prelude_lines = []
            if isinstance(target_expr, _DSListAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_list_target",
                )
                index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.index,
                    index,
                    generated_counter,
                    "_gml_list_index",
                )
            current_value = f"GMRuntime.gml_ds_list_find_value({container}, {index})"
            return [
                *prelude_lines,
                f"GMRuntime.gml_ds_list_set({container}, {index}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        ds_grid_target = _ds_grid_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_grid_target is not None:
            container, x_index, y_index = ds_grid_target
            prelude_lines = []
            if isinstance(target_expr, _DSGridAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_grid_target",
                )
                x_index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.x_index,
                    x_index,
                    generated_counter,
                    "_gml_grid_x",
                )
                y_index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.y_index,
                    y_index,
                    generated_counter,
                    "_gml_grid_y",
                )
            current_value = f"GMRuntime.gml_ds_grid_get({container}, {x_index}, {y_index})"
            return [
                *prelude_lines,
                f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, "
                f"GMRuntime.{helper}({current_value}, 1))"
            ]
        target = _emit_expression(target_expr, local_names, scope_context=scope_context)[0]
        return [f"{target} = GMRuntime.{helper}({target}, 1)"]

    assignment = _split_assignment(statement)
    if assignment is not None:
        target, operator, value = assignment
        if _split_assignment(value) is not None:
            raise GMLTranspileError("Chained assignments are not supported")
        increment_value = _parse_increment_expression(value)
        if operator in ("=", ":=") and increment_value is not None:
            increment_target, increment_delta, increment_mode = increment_value
            increment_expr = _parse_gml_expression(
                increment_target,
                enum_values,
                enum_names,
                macro_values=macro_values,
                scope_context=scope_context,
            )
            if not _is_increment_target_expression(increment_expr):
                raise GMLTranspileError("Increment expression target must be assignable")
            increment_value_text = _emit_expression(
                increment_expr,
                local_names,
                scope_context=scope_context,
            )[0]
            prelude_lines: list[str] = []
            assigned_value = increment_value_text
            if increment_mode == "postfix":
                assigned_value = _next_generated_name_from_counter(
                    generated_counter,
                    "_gml_increment_value",
                )
                prelude_lines.append(f"var {assigned_value} = {increment_value_text}")
                local_names.add(assigned_value)
            suffix = "++" if increment_delta > 0 else "--"
            increment_lines = _transpile_statement(
                f"{increment_target}{suffix}",
                local_names,
                instance_variables,
                loop_depth=loop_depth,
                continue_depth=continue_depth,
                return_depth=return_depth,
                finally_depth=finally_depth,
                enum_values=enum_values,
                enum_names=enum_names,
                scope_context=scope_context,
                inherited_event_call=inherited_event_call,
                macro_values=macro_values,
                generated_counter=generated_counter,
            )
            assignment_lines = _transpile_assignment_to_emitted_value(
                target,
                assigned_value,
                local_names,
                instance_variables,
                enum_values=enum_values,
                enum_names=enum_names,
                scope_context=scope_context,
                macro_values=macro_values,
            )
            return [*prelude_lines, *increment_lines, *assignment_lines]
        _reject_constant_assignment_target_name(target, macro_values.keys())
        target_expr = _parse_gml_expression(
            target,
            enum_values,
            enum_names,
            macro_values=macro_values,
            scope_context=scope_context,
        )
        _reject_enum_assignment_target(target_expr, enum_names)
        _reject_readonly_builtin_assignment_target(target_expr, local_names)
        if isinstance(target_expr, _Name):
            _reject_asset_identifier_name(target_expr.value, scope_context)
        static_target = _static_scope_assignment_parts(target_expr, scope_context)
        global_target = _global_scope_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        scoped_target = _scoped_instance_assignment_parts(
            target_expr,
            local_names,
            scope_context,
        )
        value = transpile_gml_expression(
            value,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        if static_target is not None:
            static_scope, member_name = static_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_struct_set({static_scope}, {member_name}, {value})"]
            current_value = f"GMRuntime.gml_struct_get({static_scope}, {member_name})"
            if operator == "??=":
                return [
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_struct_set({static_scope}, {member_name}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    f"GMRuntime.gml_struct_set({static_scope}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported static assignment operator")
        if global_target is not None:
            global_scope, member_name = global_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_struct_set({global_scope}, {member_name}, {value})"]
            current_value = f"GMRuntime.gml_struct_get({global_scope}, {member_name})"
            if operator == "??=":
                return [
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_struct_set({global_scope}, {member_name}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    f"GMRuntime.gml_struct_set({global_scope}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported global assignment operator")
        motion_target = _motion_assignment_parts(target_expr, local_names, scope_context)
        if motion_target is not None:
            instance_target, member_name = motion_target
            return _motion_assignment_lines(
                instance_target,
                member_name,
                operator,
                value,
                scope_context,
            )
        if scoped_target is not None:
            instance_target, member_name = scoped_target
            if operator in ("=", ":="):
                return [
                    "GMRuntime.gml_variable_instance_set("
                    f"{instance_target}, {member_name}, {value})"
                ]
            current_value = f"GMRuntime.gml_variable_instance_get({instance_target}, {member_name})"
            if operator == "??=":
                return [
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    "\tGMRuntime.gml_variable_instance_set("
                    f"{instance_target}, {member_name}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    "GMRuntime.gml_variable_instance_set("
                    f"{instance_target}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported scoped instance assignment operator")
        _record_instance_assignment(target, local_names, instance_variables)
        target = _emit_expression(target_expr, local_names, scope_context=scope_context)[0]
        if isinstance(target_expr, _Index):
            container = _emit_expression(
                target_expr.target,
                local_names,
                scope_context=scope_context,
            )[0]
            index = _emit_expression(
                target_expr.index,
                local_names,
                scope_context=scope_context,
            )[0]
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_array_set({container}, {index}, {value})"]
            prelude_lines: list[str] = []
            container = _cache_assignment_part(
                prelude_lines,
                target_expr.target,
                container,
                generated_counter,
                "_gml_array_target",
            )
            index = _cache_assignment_part(
                prelude_lines,
                target_expr.index,
                index,
                generated_counter,
                "_gml_array_index",
            )
            if operator == "??=":
                current_value = f"GMRuntime.gml_array_get({container}, {index})"
                return [
                    *prelude_lines,
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_array_set({container}, {index}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_array_get({container}, {index})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_array_set({container}, {index}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
        ds_map_target = _ds_map_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_map_target is not None:
            container, key = ds_map_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_ds_map_set({container}, {key}, {value})"]
            prelude_lines: list[str] = []
            if isinstance(target_expr, _DSMapAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_map_target",
                )
                key = _cache_assignment_part(
                    prelude_lines,
                    target_expr.key,
                    key,
                    generated_counter,
                    "_gml_map_key",
                )
            if operator == "??=":
                current_value = f"GMRuntime.gml_ds_map_find_value({container}, {key})"
                return [
                    *prelude_lines,
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_ds_map_set({container}, {key}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_ds_map_find_value({container}, {key})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_ds_map_set({container}, {key}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported DS map accessor assignment operator")
        ds_list_target = _ds_list_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_list_target is not None:
            container, index = ds_list_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_ds_list_set({container}, {index}, {value})"]
            prelude_lines = []
            if isinstance(target_expr, _DSListAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_list_target",
                )
                index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.index,
                    index,
                    generated_counter,
                    "_gml_list_index",
                )
            if operator == "??=":
                current_value = f"GMRuntime.gml_ds_list_find_value({container}, {index})"
                return [
                    *prelude_lines,
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_ds_list_set({container}, {index}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_ds_list_find_value({container}, {index})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_ds_list_set({container}, {index}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
        ds_grid_target = _ds_grid_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if ds_grid_target is not None:
            container, x_index, y_index = ds_grid_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})"]
            prelude_lines = []
            if isinstance(target_expr, _DSGridAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_grid_target",
                )
                x_index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.x_index,
                    x_index,
                    generated_counter,
                    "_gml_grid_x",
                )
                y_index = _cache_assignment_part(
                    prelude_lines,
                    target_expr.y_index,
                    y_index,
                    generated_counter,
                    "_gml_grid_y",
                )
            if operator == "??=":
                current_value = f"GMRuntime.gml_ds_grid_get({container}, {x_index}, {y_index})"
                return [
                    *prelude_lines,
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_ds_grid_get({container}, {x_index}, {y_index})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported DS grid accessor assignment operator")
            raise GMLTranspileError("Unsupported DS list accessor assignment operator")
        selector_target = _selector_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if selector_target is not None:
            container, key = selector_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_selector_set({container}, {key}, {value})"]
            prelude_lines = []
            if isinstance(target_expr, _Member):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_selector_target",
                )
            if operator == "??=":
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_selector_set_if_nullish({container}, {key}, "
                    f"func(): return {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = _next_generated_name_from_counter(
                    generated_counter,
                    "_gml_selector_value",
                )
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_selector_update({container}, {key}, "
                    f"func({current_value}): return GMRuntime.{helper}({current_value}, {value}))",
                ]
            raise GMLTranspileError("Unsupported selector member assignment operator")
        struct_target = _struct_assignment_parts(
            target_expr,
            local_names,
            scope_context=scope_context,
        )
        if struct_target is not None:
            container, key = struct_target
            if operator in ("=", ":="):
                return [f"GMRuntime.gml_struct_set({container}, {key}, {value})"]
            prelude_lines = []
            if isinstance(target_expr, _StructAccess):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_struct_target",
                )
                key = _cache_assignment_part(
                    prelude_lines,
                    target_expr.key,
                    key,
                    generated_counter,
                    "_gml_struct_key",
                )
            elif isinstance(target_expr, _Member):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_struct_target",
                )
            if operator == "??=":
                current_value = f"GMRuntime.gml_struct_get({container}, {key})"
                return [
                    *prelude_lines,
                    f"if GMRuntime.gml_is_nullish({current_value}):",
                    f"\tGMRuntime.gml_struct_set({container}, {key}, {value})",
                ]
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_struct_get({container}, {key})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_struct_set({container}, {key}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported struct member assignment operator")
        if operator == "??=":
            return [f"if GMRuntime.gml_is_nullish({target}):", f"\t{target} = {value}"]
        if operator in _COMPOUND_RUNTIME_FUNCTIONS:
            return [f"{target} = GMRuntime.{_COMPOUND_RUNTIME_FUNCTIONS[operator]}({target}, {value})"]
        if operator == ":=":
            return [f"{target} = {value}"]
        return [f"{target} {operator} {value}"]

    return [
        transpile_gml_expression(
            statement,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
    ]


def _reject_finally_control_flow(finally_depth: int) -> None:
    if finally_depth > 0:
        raise GMLTranspileError("break, continue, exit, and return are not allowed inside finally")


def _transpile_event_inherited_statement(
    statement: str,
    inherited_event_call: str | None,
) -> list[str] | None:
    if not statement.strip().startswith("event_inherited"):
        return None

    expr = _parse_gml_expression(statement)
    expr = _unwrap_grouped_expression(expr)
    if not (
        isinstance(expr, _Call)
        and isinstance(expr.callee, _Name)
        and expr.callee.value == "event_inherited"
    ):
        return None

    if expr.args:
        raise GMLTranspileError("event_inherited does not accept arguments")

    if inherited_event_call is None:
        return ["pass"]
    return [inherited_event_call]


def _struct_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(target_expr, _StructAccess):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        key = _emit_expression(
            target_expr.key,
            local_names,
            scope_context=scope_context,
        )[0]
        return container, key
    if isinstance(target_expr, _Member) and not _uses_direct_member_access(
        target_expr,
        scope_context=scope_context,
    ):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        return container, json.dumps(target_expr.member)
    return None


def _ds_map_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(target_expr, _DSMapAccess):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        key = _emit_expression(
            target_expr.key,
            local_names,
            scope_context=scope_context,
        )[0]
        return container, key
    return None


def _ds_list_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(target_expr, _DSListAccess):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        index = _emit_expression(
            target_expr.index,
            local_names,
            scope_context=scope_context,
        )[0]
        return container, index
    return None


def _ds_grid_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(target_expr, _DSGridAccess):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        x_index = _emit_expression(
            target_expr.x_index,
            local_names,
            scope_context=scope_context,
        )[0]
        y_index = _emit_expression(
            target_expr.y_index,
            local_names,
            scope_context=scope_context,
        )[0]
        return container, x_index, y_index
    return None


def _scoped_instance_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if scope_context.instance_target is None or not isinstance(target_expr, _Name):
        return None

    name = target_expr.value
    if (
        name in local_names
        or name in _GML_LITERAL_IDENTIFIERS
        or name in _BUILTIN_ARRAY_VARIABLES
        or name in _BUILTIN_GLOBAL_VARIABLES
        or not _is_plain_identifier(name)
    ):
        return None
    return scope_context.instance_target, json.dumps(name)


def _motion_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if not isinstance(target_expr, _Name):
        return None
    name = target_expr.value
    if name in local_names or name not in _MOTION_SYNCHRONIZED_BUILTINS:
        return None
    instance_target = scope_context.instance_target or scope_context.self_expression
    return instance_target, name


def _motion_current_value(
    instance_target: str,
    member_name: str,
    scope_context: _ScopeContext | None = None,
) -> str:
    scope_context = _normalize_scope_context(scope_context)
    if scope_context.instance_target is not None:
        return f"GMRuntime.gml_variable_instance_get({instance_target}, {json.dumps(member_name)})"
    return _sanitize_gdscript_identifier(member_name)


def _motion_assignment_lines(
    instance_target: str,
    member_name: str,
    operator: str,
    value: str,
    scope_context: _ScopeContext | None = None,
) -> list[str]:
    if operator in ("=", ":="):
        return [f"GMRuntime.gml_motion_set_{member_name}({instance_target}, {value})"]
    current_value = _motion_current_value(instance_target, member_name, scope_context)
    if operator == "??=":
        return [
            f"if GMRuntime.gml_is_nullish({current_value}):",
            f"\tGMRuntime.gml_motion_set_{member_name}({instance_target}, {value})",
        ]
    if operator in _COMPOUND_RUNTIME_FUNCTIONS:
        helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
        return [
            f"GMRuntime.gml_motion_set_{member_name}("
            f"{instance_target}, GMRuntime.{helper}({current_value}, {value}))"
        ]
    raise GMLTranspileError("Unsupported motion assignment operator")


def _static_scope_assignment_parts(
    target_expr: _Expression,
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if scope_context.static_scope is None or not isinstance(target_expr, _Name):
        return None
    name = target_expr.value
    if name not in scope_context.static_names:
        return None
    return scope_context.static_scope, json.dumps(name)


def _global_scope_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if not isinstance(target_expr, _Name):
        return None
    name = target_expr.value
    if not _name_resolves_to_global(name, local_names, scope_context):
        return None
    return "GMRuntime.gml_global_scope()", json.dumps(name)


def _record_instance_assignment(
    target: str,
    local_names: Iterable[str],
    instance_variables: MutableSet[str] | None,
) -> None:
    if instance_variables is None:
        return

    tokens = _expression_tokens(target.strip())
    if len(tokens) != 2 or tokens[0].kind != "IDENT" or tokens[1].kind != "EOF":
        return

    name = tokens[0].value
    if name in local_names or name in _BUILTIN_INSTANCE_VARIABLES:
        return
    instance_variables.add(name)


def _transpile_var_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
) -> list[str]:
    lines: list[str] = []
    if local_names is None:
        local_names = set()
    scope_context = _normalize_scope_context(scope_context)
    enum_name_set = frozenset(enum_names or [])
    macro_values = macro_values or {}
    for declaration in _split_top_level(statement, ","):
        declaration = declaration.strip()
        if not declaration:
            continue
        assignment = _split_assignment(declaration)
        if assignment is None:
            name = declaration.strip()
            _validate_gml_identifier(name)
            _reject_asset_identifier_name(name, scope_context)
            _reject_constant_declaration_name(name, macro_values.keys())
            if name in enum_name_set:
                raise GMLTranspileError("Cannot redeclare enum")
            lines.append(f"var {_sanitize_gdscript_identifier(name)} = GMRuntime.gml_undefined()")
            local_names.add(name)
            continue
        name, operator, value = assignment
        if operator not in ("=", ":="):
            raise GMLTranspileError("Variable declarations only support simple assignments")
        name = name.strip()
        _validate_gml_identifier(name)
        _reject_asset_identifier_name(name, scope_context)
        _reject_constant_declaration_name(name, macro_values.keys())
        if name in enum_name_set:
            raise GMLTranspileError("Cannot redeclare enum")
        initial_value = transpile_gml_expression(
            value,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        lines.append(f"var {_sanitize_gdscript_identifier(name)} = {initial_value}")
        local_names.add(name)
    return lines

def _parse_increment_statement(statement: str) -> tuple[str, _IncrementDelta] | None:
    stripped = statement.strip()
    if stripped.endswith("++"):
        target = stripped[:-2].strip()
        if _split_assignment(target) is not None:
            return None
        return target, 1
    if stripped.endswith("--"):
        target = stripped[:-2].strip()
        if _split_assignment(target) is not None:
            return None
        return target, -1
    if stripped.startswith("++"):
        target = stripped[2:].strip()
        if _split_assignment(target) is not None:
            return None
        return target, 1
    if stripped.startswith("--"):
        target = stripped[2:].strip()
        if _split_assignment(target) is not None:
            return None
        return target, -1
    return None


def _parse_increment_expression(statement: str) -> tuple[str, _IncrementDelta, _IncrementMode] | None:
    stripped = statement.strip()
    if stripped.endswith("++"):
        target = stripped[:-2].strip()
        if _split_assignment(target) is not None:
            return None
        return target, 1, "postfix"
    if stripped.endswith("--"):
        target = stripped[:-2].strip()
        if _split_assignment(target) is not None:
            return None
        return target, -1, "postfix"
    if stripped.startswith("++"):
        target = stripped[2:].strip()
        if _split_assignment(target) is not None:
            return None
        return target, 1, "prefix"
    if stripped.startswith("--"):
        target = stripped[2:].strip()
        if _split_assignment(target) is not None:
            return None
        return target, -1, "prefix"
    return None


def _is_increment_target_expression(expr: _Expression) -> bool:
    return isinstance(expr, _Name | _Index | _Member | _StructAccess | _DSMapAccess | _DSListAccess)


def _transpile_assignment_to_emitted_value(
    target: str,
    value: str,
    local_names: MutableSet[str],
    instance_variables: MutableSet[str] | None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
) -> list[str]:
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    _reject_constant_assignment_target_name(target, macro_values.keys())
    target_expr = _parse_gml_expression(
        target,
        enum_values,
        enum_names,
        macro_values=macro_values,
        scope_context=scope_context,
    )
    _reject_enum_assignment_target(target_expr, enum_names)
    _reject_readonly_builtin_assignment_target(target_expr, local_names)
    if isinstance(target_expr, _Name):
        _reject_asset_identifier_name(target_expr.value, scope_context)
    static_target = _static_scope_assignment_parts(target_expr, scope_context)
    if static_target is not None:
        static_scope, member_name = static_target
        return [f"GMRuntime.gml_struct_set({static_scope}, {member_name}, {value})"]
    global_target = _global_scope_assignment_parts(
        target_expr,
        local_names,
        scope_context,
    )
    if global_target is not None:
        global_scope, member_name = global_target
        return [f"GMRuntime.gml_struct_set({global_scope}, {member_name}, {value})"]
    motion_target = _motion_assignment_parts(target_expr, local_names, scope_context)
    if motion_target is not None:
        instance_target, member_name = motion_target
        return [f"GMRuntime.gml_motion_set_{member_name}({instance_target}, {value})"]
    scoped_target = _scoped_instance_assignment_parts(
        target_expr,
        local_names,
        scope_context,
    )
    if scoped_target is not None:
        instance_target, member_name = scoped_target
        return [
            "GMRuntime.gml_variable_instance_set("
            f"{instance_target}, {member_name}, {value})"
        ]
    _record_instance_assignment(target, local_names, instance_variables)
    if isinstance(target_expr, _Index):
        container = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        index = _emit_expression(
            target_expr.index,
            local_names,
            scope_context=scope_context,
        )[0]
        return [f"GMRuntime.gml_array_set({container}, {index}, {value})"]
    ds_map_target = _ds_map_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_map_target is not None:
        container, key = ds_map_target
        return [f"GMRuntime.gml_ds_map_set({container}, {key}, {value})"]
    ds_list_target = _ds_list_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_list_target is not None:
        container, index = ds_list_target
        return [f"GMRuntime.gml_ds_list_set({container}, {index}, {value})"]
    ds_grid_target = _ds_grid_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_grid_target is not None:
        container, x_index, y_index = ds_grid_target
        return [f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})"]
    selector_target = _selector_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if selector_target is not None:
        container, key = selector_target
        return [f"GMRuntime.gml_selector_set({container}, {key}, {value})"]
    struct_target = _struct_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if struct_target is not None:
        container, key = struct_target
        return [f"GMRuntime.gml_struct_set({container}, {key}, {value})"]
    emitted_target = _emit_expression(
        target_expr,
        local_names,
        scope_context=scope_context,
    )[0]
    return [f"{emitted_target} = {value}"]


def _selector_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if not isinstance(target_expr, _Member) or _uses_direct_member_access(
        target_expr,
        scope_context=scope_context,
    ):
        return None
    container = _emit_instance_keyword_argument(
        target_expr.target,
        local_names,
        scope_context=scope_context,
    )
    return container, json.dumps(target_expr.member)
