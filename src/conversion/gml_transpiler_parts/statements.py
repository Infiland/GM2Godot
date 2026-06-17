# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, MutableMapping, MutableSet

from .constants import (
    _BUILTIN_ARRAY_VARIABLES,
    _BUILTIN_GLOBAL_VARIABLES,
    _BUILTIN_INSTANCE_VARIABLES,
    _COMPOUND_RUNTIME_FUNCTIONS,
    _GML_LITERAL_IDENTIFIERS,
)
from .emitter import (
    _is_alarm_array_access,
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
    _ArrayRefAccess,
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
    _Token,
)
from .tokens import _expression_tokens
from .utils import (
    _cache_assignment_part,
    _indent_lines,
    _next_generated_name_from_counter,
    _normalize_scope_context,
    _split_assignment,
    _split_top_level,
    _unwrap_grouped_expression,
)

_MOTION_SYNCHRONIZED_BUILTINS = frozenset({"direction", "hspeed", "speed", "vspeed"})


def _alarm_array_index(
    target_expr: _Index,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> str:
    return _emit_expression(
        target_expr.index,
        local_names,
        scope_context=scope_context,
    )[0]


def _alarm_array_get(scope_context: _ScopeContext, index: str) -> str:
    return f"GMRuntime.gml_alarm_get({scope_context.self_expression}, {index})"


def _alarm_array_set(scope_context: _ScopeContext, index: str, value: str) -> str:
    return f"GMRuntime.gml_alarm_set({scope_context.self_expression}, {index}, {value})"


@dataclass(frozen=True)
class _ControlFlowCapture:
    variable_name: str
    loop_depth: int
    continue_depth: int
    capture_return: bool = False
    capture_exit: bool = False
    capture_throw: bool = False
    capture_break: bool = False
    capture_continue: bool = False


def _transpile_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
    declared_local_names: MutableSet[str] | None = None,
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
    control_flow_capture: _ControlFlowCapture | None = None,
) -> list[str]:
    if not statement:
        return []

    if local_names is None:
        local_names = set()
    if declared_local_names is None:
        declared_local_names = set()
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]

    if statement == "return":
        _reject_finally_control_flow(finally_depth)
        if return_depth <= 0:
            raise GMLTranspileError("return used outside a function or method")
        if control_flow_capture is not None and control_flow_capture.capture_return:
            return _captured_control_flow_lines(control_flow_capture, "return")
        return ["return"]
    if statement.startswith("return "):
        _reject_finally_control_flow(finally_depth)
        if return_depth <= 0:
            raise GMLTranspileError("return used outside a function or method")
        prelude_lines, return_source = _lower_mutation_expressions(
            statement[7:].strip(),
            local_names,
            instance_variables,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
        )
        return_value = transpile_gml_expression(
            return_source,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        if control_flow_capture is not None and control_flow_capture.capture_return:
            return [
                *prelude_lines,
                *_captured_control_flow_lines(control_flow_capture, "return", return_value),
            ]
        return [*prelude_lines, f"return {return_value}"]
    if statement == "break":
        _reject_finally_control_flow(finally_depth)
        if loop_depth <= 0:
            raise GMLTranspileError("break used outside a loop")
        if (
            control_flow_capture is not None
            and control_flow_capture.capture_break
            and loop_depth == control_flow_capture.loop_depth
        ):
            return _captured_control_flow_lines(control_flow_capture, "break")
        return ["break"]
    if statement == "continue":
        _reject_finally_control_flow(finally_depth)
        if continue_depth <= 0:
            raise GMLTranspileError("continue used outside a loop")
        if (
            control_flow_capture is not None
            and control_flow_capture.capture_continue
            and continue_depth == control_flow_capture.continue_depth
        ):
            return _captured_control_flow_lines(control_flow_capture, "continue")
        return ["continue"]
    if statement == "exit":
        _reject_finally_control_flow(finally_depth)
        if control_flow_capture is not None and control_flow_capture.capture_exit:
            return _captured_control_flow_lines(control_flow_capture, "exit")
        return ["return"]
    event_inherited_lines = _transpile_event_inherited_statement(statement, inherited_event_call)
    if event_inherited_lines is not None:
        return event_inherited_lines
    if statement == "throw":
        raise GMLTranspileError("throw requires an expression")
    if statement.startswith("throw "):
        prelude_lines, thrown_source = _lower_mutation_expressions(
            statement[6:].strip(),
            local_names,
            instance_variables,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
        )
        thrown_value = transpile_gml_expression(
            thrown_source,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        if control_flow_capture is not None and control_flow_capture.capture_throw:
            return [
                *prelude_lines,
                *_captured_control_flow_lines(
                    control_flow_capture,
                    "throw",
                    f"GMRuntime.gml_throw({thrown_value})",
                ),
            ]
        return [*prelude_lines, f"return GMRuntime.gml_throw({thrown_value})"]

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
        delete_lines = _delete_target_lines(target_expr, local_names, scope_context)
        if delete_lines is not None:
            return delete_lines
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
            declared_local_names,
            instance_variables,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
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
        if _is_alarm_array_access(target_expr, local_names):
            index = _alarm_array_index(target_expr, local_names, scope_context)
            prelude_lines: list[str] = []
            index = _cache_assignment_part(
                prelude_lines,
                target_expr.index,
                index,
                generated_counter,
                "_gml_alarm_index",
            )
            current_value = _alarm_array_get(scope_context, index)
            return [
                *prelude_lines,
                _alarm_array_set(
                    scope_context,
                    index,
                    f"GMRuntime.{helper}({current_value}, 1)",
                ),
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
        if isinstance(target_expr, _ArrayRefAccess):
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
            if operator not in ("=", ":="):
                raise GMLTranspileError("Chained compound assignments are not supported")
            assignment_lines, _assigned_value = _transpile_assignment_expression_to_temp(
                statement,
                local_names,
                instance_variables,
                enum_values=enum_values,
                enum_names=enum_names,
                scope_context=scope_context,
                macro_values=macro_values,
                generated_counter=generated_counter,
                result_required=False,
            )
            return assignment_lines
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
                declared_local_names,
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
        value_prelude_lines, value_source = _lower_mutation_expressions(
            value,
            local_names,
            instance_variables,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
        )
        value = transpile_gml_expression(
            value_source,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )
        prelude_lines = [] if operator == "??=" else value_prelude_lines
        if static_target is not None:
            static_scope, member_name = static_target
            if operator in ("=", ":="):
                return [*prelude_lines, f"GMRuntime.gml_struct_set({static_scope}, {member_name}, {value})"]
            current_value = f"GMRuntime.gml_struct_get({static_scope}, {member_name})"
            if operator == "??=":
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_struct_set({static_scope}, {member_name}, {value})"],
                )
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_struct_set({static_scope}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported static assignment operator")
        if global_target is not None:
            global_scope, member_name = global_target
            if operator in ("=", ":="):
                return [*prelude_lines, f"GMRuntime.gml_struct_set({global_scope}, {member_name}, {value})"]
            current_value = f"GMRuntime.gml_struct_get({global_scope}, {member_name})"
            if operator == "??=":
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_struct_set({global_scope}, {member_name}, {value})"],
                )
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_struct_set({global_scope}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported global assignment operator")
        motion_target = _motion_assignment_parts(target_expr, local_names, scope_context)
        if motion_target is not None:
            instance_target, member_name = motion_target
            if operator == "??=":
                return _nullish_assignment_lines(
                    prelude_lines,
                    _motion_current_value(instance_target, member_name, scope_context),
                    value_prelude_lines,
                    [f"GMRuntime.gml_motion_set_{member_name}({instance_target}, {value})"],
                )
            return [
                *prelude_lines,
                *_motion_assignment_lines(
                    instance_target,
                    member_name,
                    operator,
                    value,
                    scope_context,
                ),
            ]
        if scoped_target is not None:
            instance_target, member_name = scoped_target
            if operator in ("=", ":="):
                return [
                    *prelude_lines,
                    "GMRuntime.gml_variable_instance_set("
                    f"{instance_target}, {member_name}, {value})"
                ]
            current_value = f"GMRuntime.gml_variable_instance_get({instance_target}, {member_name})"
            if operator == "??=":
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [
                        "GMRuntime.gml_variable_instance_set("
                        f"{instance_target}, {member_name}, {value})"
                    ],
                )
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    *prelude_lines,
                    "GMRuntime.gml_variable_instance_set("
                    f"{instance_target}, {member_name}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
            raise GMLTranspileError("Unsupported scoped instance assignment operator")
        if _is_alarm_array_access(target_expr, local_names):
            index = _alarm_array_index(target_expr, local_names, scope_context)
            if operator in ("=", ":="):
                return [*prelude_lines, _alarm_array_set(scope_context, index, value)]
            index = _cache_assignment_part(
                prelude_lines,
                target_expr.index,
                index,
                generated_counter,
                "_gml_alarm_index",
            )
            current_value = _alarm_array_get(scope_context, index)
            if operator == "??=":
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [_alarm_array_set(scope_context, index, value)],
                )
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                return [
                    *prelude_lines,
                    _alarm_array_set(
                        scope_context,
                        index,
                        f"GMRuntime.{helper}({current_value}, {value})",
                    ),
                ]
            raise GMLTranspileError("Unsupported alarm assignment operator")
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
                return [*prelude_lines, f"GMRuntime.gml_array_set({container}, {index}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_array_set({container}, {index}, {value})"],
                )
            if operator in _COMPOUND_RUNTIME_FUNCTIONS:
                helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
                current_value = f"GMRuntime.gml_array_get({container}, {index})"
                return [
                    *prelude_lines,
                    f"GMRuntime.gml_array_set({container}, {index}, "
                    f"GMRuntime.{helper}({current_value}, {value}))"
                ]
        if isinstance(target_expr, _ArrayRefAccess):
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
                return [*prelude_lines, f"GMRuntime.gml_array_set({container}, {index}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_array_set({container}, {index}, {value})"],
                )
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
                return [*prelude_lines, f"GMRuntime.gml_ds_map_set({container}, {key}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_ds_map_set({container}, {key}, {value})"],
                )
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
                return [*prelude_lines, f"GMRuntime.gml_ds_list_set({container}, {index}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_ds_list_set({container}, {index}, {value})"],
                )
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
                return [*prelude_lines, f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})"],
                )
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
                return [*prelude_lines, f"GMRuntime.gml_selector_set({container}, {key}, {value})"]
            if isinstance(target_expr, _Member):
                container = _cache_assignment_part(
                    prelude_lines,
                    target_expr.target,
                    container,
                    generated_counter,
                    "_gml_selector_target",
                )
            if operator == "??=":
                if value_prelude_lines:
                    current_value = _next_generated_name_from_counter(
                        generated_counter,
                        "_gml_selector_value",
                    )
                    return _nullish_assignment_lines(
                        [
                            *prelude_lines,
                            f"var {current_value} = GMRuntime.gml_selector_get({container}, {key})",
                        ],
                        current_value,
                        value_prelude_lines,
                        [f"GMRuntime.gml_selector_set({container}, {key}, {value})"],
                    )
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
                return [*prelude_lines, f"GMRuntime.gml_struct_set({container}, {key}, {value})"]
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
                return _nullish_assignment_lines(
                    prelude_lines,
                    current_value,
                    value_prelude_lines,
                    [f"GMRuntime.gml_struct_set({container}, {key}, {value})"],
                )
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
            return _nullish_assignment_lines(
                prelude_lines,
                target,
                value_prelude_lines,
                [f"{target} = {value}"],
            )
        if operator in _COMPOUND_RUNTIME_FUNCTIONS:
            return [*prelude_lines, f"{target} = GMRuntime.{_COMPOUND_RUNTIME_FUNCTIONS[operator]}({target}, {value})"]
        if operator == ":=":
            return [*prelude_lines, f"{target} = {value}"]
        return [*prelude_lines, f"{target} {operator} {value}"]

    prelude_lines, expression_source = _lower_mutation_expressions(
        statement,
        local_names,
        instance_variables,
        enum_values,
        enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
        generated_counter=generated_counter,
    )
    return [
        *prelude_lines,
        transpile_gml_expression(
            expression_source,
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


def _delete_target_lines(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str] | None:
    if isinstance(target_expr, _Member):
        target = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        return [f"GMRuntime.gml_struct_remove({target}, {json.dumps(target_expr.member)})"]
    if isinstance(target_expr, _StructAccess):
        target = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        key = _emit_expression(target_expr.key, local_names, scope_context=scope_context)[0]
        return [f"GMRuntime.gml_struct_remove({target}, {key})"]
    if isinstance(target_expr, _Index | _ArrayRefAccess):
        target = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        index = _emit_expression(target_expr.index, local_names, scope_context=scope_context)[0]
        return [f"GMRuntime.gml_array_delete({target}, {index})"]
    if isinstance(target_expr, _DSMapAccess):
        target = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        key = _emit_expression(target_expr.key, local_names, scope_context=scope_context)[0]
        return [f"GMRuntime.gml_ds_map_delete({target}, {key})"]
    if isinstance(target_expr, _DSListAccess):
        target = _emit_expression(
            target_expr.target,
            local_names,
            scope_context=scope_context,
        )[0]
        index = _emit_expression(target_expr.index, local_names, scope_context=scope_context)[0]
        return [f"GMRuntime.gml_ds_list_delete({target}, {index})"]
    if isinstance(target_expr, _DSGridAccess):
        raise GMLTranspileError("delete does not support DS grid accessors")
    return None


def _captured_control_flow_lines(
    capture: _ControlFlowCapture,
    kind: str,
    value: str = "GMRuntime.gml_undefined()",
) -> list[str]:
    return [
        f'{capture.variable_name} = {{"kind": {json.dumps(kind)}, "value": {value}}}',
        "break",
    ]


def _control_flow_dispatch_lines(
    control_name: str,
    source_capture: _ControlFlowCapture,
    parent_capture: _ControlFlowCapture | None = None,
) -> list[str]:
    lines: list[str] = []
    for kind in ("return", "exit", "break", "continue", "throw"):
        if not _capture_handles_kind(source_capture, kind):
            continue
        lines.append(
            f"if not GMRuntime.is_undefined({control_name}) and "
            f'{control_name}["kind"] == {json.dumps(kind)}:'
        )
        if parent_capture is not None and _capture_handles_kind(parent_capture, kind):
            lines.extend(
                _indent_lines(
                    _captured_control_flow_lines(
                        parent_capture,
                        kind,
                        f'{control_name}["value"]',
                    )
                )
            )
            continue
        if kind == "return":
            lines.append(f'\treturn {control_name}["value"]')
        elif kind == "exit":
            lines.append("\treturn")
        elif kind == "break":
            lines.append("\tbreak")
        elif kind == "continue":
            lines.append("\tcontinue")
        elif kind == "throw":
            lines.append(f'\treturn {control_name}["value"]')
    return lines


def _capture_handles_kind(capture: _ControlFlowCapture, kind: str) -> bool:
    if kind == "return":
        return capture.capture_return
    if kind == "exit":
        return capture.capture_exit
    if kind == "throw":
        return capture.capture_throw
    if kind == "break":
        return capture.capture_break
    if kind == "continue":
        return capture.capture_continue
    return False


def _nullish_assignment_lines(
    prelude_lines: Iterable[str],
    current_value: str,
    value_prelude_lines: Iterable[str],
    assignment_lines: Iterable[str],
) -> list[str]:
    return [
        *prelude_lines,
        f"if GMRuntime.gml_is_nullish({current_value}):",
        *_indent_lines(value_prelude_lines),
        *_indent_lines(assignment_lines),
    ]


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


def _array_ref_assignment_parts(
    target_expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, str] | None:
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(target_expr, _ArrayRefAccess):
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
    if name in _BUILTIN_GLOBAL_VARIABLES and name not in local_names:
        return "GMRuntime.gml_global_scope()", json.dumps(name)
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
    if len(tokens) >= 4 and tokens[0].kind == "IDENT" and tokens[1].value == "[":
        name = tokens[0].value
        if name not in local_names and name not in _BUILTIN_INSTANCE_VARIABLES:
            instance_variables.add(name)
        return

    if len(tokens) != 2 or tokens[0].kind != "IDENT" or tokens[1].kind != "EOF":
        return

    name = tokens[0].value
    if name in local_names or name in _BUILTIN_INSTANCE_VARIABLES:
        return
    instance_variables.add(name)


def _transpile_var_statement(
    statement: str,
    local_names: MutableSet[str] | None = None,
    declared_local_names: MutableSet[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    generated_counter: list[int] | None = None,
) -> list[str]:
    lines: list[str] = []
    if local_names is None:
        local_names = set()
    if declared_local_names is None:
        declared_local_names = set()
    scope_context = _normalize_scope_context(scope_context)
    enum_name_set = frozenset(enum_names or [])
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]
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
            declaration_prefix = "" if name in declared_local_names else "var "
            lines.append(f"{declaration_prefix}{_sanitize_gdscript_identifier(name)} = GMRuntime.gml_undefined()")
            local_names.add(name)
            declared_local_names.add(name)
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
        nested_assignment = _split_assignment(value)
        if nested_assignment is not None:
            prelude_lines, initial_value = _transpile_assignment_expression_to_temp(
                value,
                local_names,
                instance_variables,
                enum_values=enum_values,
                enum_names=enum_names,
                scope_context=scope_context,
                macro_values=macro_values,
                generated_counter=generated_counter,
            )
            lines.extend(prelude_lines)
        else:
            prelude_lines, value_source = _lower_mutation_expressions(
                value,
                local_names,
                instance_variables,
                enum_values,
                enum_names,
                scope_context=scope_context,
                macro_values=macro_values,
                generated_counter=generated_counter,
            )
            initial_value = transpile_gml_expression(
                value_source,
                local_names,
                enum_values,
                enum_names,
                scope_context=scope_context,
                macro_values=macro_values,
            )
            lines.extend(prelude_lines)
        declaration_prefix = "" if name in declared_local_names else "var "
        lines.append(f"{declaration_prefix}{_sanitize_gdscript_identifier(name)} = {initial_value}")
        local_names.add(name)
        declared_local_names.add(name)
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
    return isinstance(
        expr,
        _Name
        | _Index
        | _ArrayRefAccess
        | _Member
        | _StructAccess
        | _DSMapAccess
        | _DSListAccess
        | _DSGridAccess,
    )


def _lower_mutation_expressions(
    source: str,
    local_names: MutableSet[str],
    instance_variables: MutableSet[str] | None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    generated_counter: list[int] | None = None,
) -> tuple[list[str], str]:
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]
    prelude_lines: list[str] = []
    rewritten_source = source

    while True:
        mutation = _find_next_mutation_expression(rewritten_source)
        if mutation is None:
            return prelude_lines, rewritten_source

        replace_start, replace_end, target_source, delta, mode = mutation
        mutation_lines, replacement = _transpile_increment_expression_to_value(
            target_source,
            delta,
            mode,
            local_names,
            instance_variables,
            enum_values=enum_values,
            enum_names=enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
        )
        prelude_lines.extend(mutation_lines)
        rewritten_source = (
            f"{rewritten_source[:replace_start]}{replacement}{rewritten_source[replace_end:]}"
        )


def _find_next_mutation_expression(
    source: str,
) -> tuple[int, int, str, _IncrementDelta, _IncrementMode] | None:
    tokens = [token for token in _expression_tokens(source) if token.kind != "EOF"]
    for index, token in enumerate(tokens):
        if token.value not in ("++", "--"):
            continue

        delta: _IncrementDelta = 1 if token.value == "++" else -1
        previous_token_can_end_expression = (
            index > 0 and _token_can_end_expression(tokens[index - 1])
        )
        if not previous_token_can_end_expression:
            target_end = _read_postfix_target_end(tokens, index + 1)
            if target_end is None:
                raise GMLTranspileError("Increment expression target must be assignable")
            source_end = _token_end(tokens[target_end - 1])
            target_source = source[tokens[index + 1].index:source_end].strip()
            return token.index, source_end, target_source, delta, "prefix"

        target_start = _find_postfix_target_start(tokens, index)
        if target_start is None:
            raise GMLTranspileError("Increment expression target must be assignable")
        return (
            tokens[target_start].index,
            _token_end(token),
            source[tokens[target_start].index:token.index].strip(),
            delta,
            "postfix",
        )

    return None


def _token_can_end_expression(token: _Token) -> bool:
    return token.kind in ("IDENT", "NUMBER", "STRING") or token.value in ")]}"


def _find_postfix_target_start(tokens: list[_Token], operator_index: int) -> int | None:
    valid_starts: list[int] = []
    for start in range(operator_index):
        target_end = _read_postfix_target_end(tokens, start)
        if target_end == operator_index:
            valid_starts.append(start)
    if not valid_starts:
        return None
    return min(valid_starts)


def _read_postfix_target_end(tokens: list[_Token], start: int) -> int | None:
    end = _read_primary_target_end(tokens, start)
    if end is None:
        return None

    while end < len(tokens):
        token = tokens[end]
        if token.value in ("(", "["):
            balanced_end = _read_balanced_token_end(tokens, end)
            if balanced_end is None:
                return None
            end = balanced_end
            continue
        if token.value == ".":
            if end + 1 >= len(tokens) or tokens[end + 1].kind != "IDENT":
                return None
            end += 2
            continue
        break

    return end


def _read_primary_target_end(tokens: list[_Token], start: int) -> int | None:
    if start >= len(tokens):
        return None
    token = tokens[start]
    if token.kind in ("IDENT", "NUMBER", "STRING"):
        return start + 1
    if token.value in ("(", "[", "{"):
        return _read_balanced_token_end(tokens, start)
    return None


def _read_balanced_token_end(tokens: list[_Token], start: int) -> int | None:
    opener = tokens[start].value
    closer = {"(": ")", "[": "]", "{": "}"}.get(opener)
    if closer is None:
        return None

    depth = 0
    for index in range(start, len(tokens)):
        value = tokens[index].value
        if value == opener:
            depth += 1
        elif value == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _token_end(token: _Token) -> int:
    return token.index + len(token.value)


def _transpile_increment_expression_to_value(
    target_source: str,
    delta: _IncrementDelta,
    mode: _IncrementMode,
    local_names: MutableSet[str],
    instance_variables: MutableSet[str] | None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    generated_counter: list[int] | None = None,
) -> tuple[list[str], str]:
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]
    target_expr = _parse_assignment_target(
        target_source,
        local_names,
        enum_values=enum_values,
        enum_names=enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
    )
    if not _is_increment_target_expression(target_expr):
        raise GMLTranspileError("Increment expression target must be assignable")

    prelude_lines: list[str] = []
    current_value, write_value = _assignment_target_reader_writer(
        target_source,
        target_expr,
        local_names,
        instance_variables,
        scope_context=scope_context,
        generated_counter=generated_counter,
        prelude_lines=prelude_lines,
    )
    helper = "gml_add" if delta > 0 else "gml_sub"
    result_name = _next_expression_generated_name(
        generated_counter,
        "_gm2gd_mutation_value",
        local_names,
    )
    if mode == "postfix":
        return [
            *prelude_lines,
            f"var {result_name} = {current_value}",
            *write_value(f"GMRuntime.{helper}({result_name}, 1)"),
        ], result_name
    return [
        *prelude_lines,
        f"var {result_name} = GMRuntime.{helper}({current_value}, 1)",
        *write_value(result_name),
    ], result_name


def _next_expression_generated_name(
    generated_counter: list[int],
    prefix: str,
    local_names: MutableSet[str],
) -> str:
    while True:
        candidate = _next_generated_name_from_counter(generated_counter, prefix)
        if candidate not in local_names:
            local_names.add(candidate)
            return candidate


def _parse_assignment_target(
    target: str,
    local_names: Iterable[str],
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
) -> _Expression:
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
    target_expr = _unwrap_grouped_expression(target_expr)
    _reject_enum_assignment_target(target_expr, enum_names)
    _reject_readonly_builtin_assignment_target(target_expr, local_names)
    if isinstance(target_expr, _Name):
        _reject_asset_identifier_name(target_expr.value, scope_context)
    return target_expr


def _assignment_target_reader_writer(
    target_source: str,
    target_expr: _Expression,
    local_names: MutableSet[str],
    instance_variables: MutableSet[str] | None,
    scope_context: _ScopeContext,
    generated_counter: list[int],
    prelude_lines: list[str],
) -> tuple[str, Callable[[str], list[str]]]:
    static_target = _static_scope_assignment_parts(target_expr, scope_context)
    if static_target is not None:
        static_scope, member_name = static_target
        return (
            f"GMRuntime.gml_struct_get({static_scope}, {member_name})",
            lambda value: [f"GMRuntime.gml_struct_set({static_scope}, {member_name}, {value})"],
        )

    global_target = _global_scope_assignment_parts(target_expr, local_names, scope_context)
    if global_target is not None:
        global_scope, member_name = global_target
        return (
            f"GMRuntime.gml_struct_get({global_scope}, {member_name})",
            lambda value: [f"GMRuntime.gml_struct_set({global_scope}, {member_name}, {value})"],
        )

    motion_target = _motion_assignment_parts(target_expr, local_names, scope_context)
    if motion_target is not None:
        instance_target, member_name = motion_target
        current_value = _motion_current_value(instance_target, member_name, scope_context)
        return (
            current_value,
            lambda value: [f"GMRuntime.gml_motion_set_{member_name}({instance_target}, {value})"],
        )

    scoped_target = _scoped_instance_assignment_parts(
        target_expr,
        local_names,
        scope_context,
    )
    if scoped_target is not None:
        instance_target, member_name = scoped_target
        return (
            f"GMRuntime.gml_variable_instance_get({instance_target}, {member_name})",
            lambda value: [
                "GMRuntime.gml_variable_instance_set("
                f"{instance_target}, {member_name}, {value})"
            ],
        )

    if _is_alarm_array_access(target_expr, local_names):
        index = _alarm_array_index(target_expr, local_names, scope_context)
        index = _cache_assignment_part(
            prelude_lines,
            target_expr.index,
            index,
            generated_counter,
            "_gml_alarm_index",
        )
        return (
            _alarm_array_get(scope_context, index),
            lambda value: [_alarm_array_set(scope_context, index, value)],
        )

    _record_instance_assignment(target_source, local_names, instance_variables)
    if isinstance(target_expr, _Index | _ArrayRefAccess):
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
        return (
            f"GMRuntime.gml_array_get({container}, {index})",
            lambda value: [f"GMRuntime.gml_array_set({container}, {index}, {value})"],
        )

    ds_map_target = _ds_map_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_map_target is not None:
        container, key = ds_map_target
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
        return (
            f"GMRuntime.gml_ds_map_find_value({container}, {key})",
            lambda value: [f"GMRuntime.gml_ds_map_set({container}, {key}, {value})"],
        )

    ds_list_target = _ds_list_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_list_target is not None:
        container, index = ds_list_target
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
        return (
            f"GMRuntime.gml_ds_list_find_value({container}, {index})",
            lambda value: [f"GMRuntime.gml_ds_list_set({container}, {index}, {value})"],
        )

    ds_grid_target = _ds_grid_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if ds_grid_target is not None:
        container, x_index, y_index = ds_grid_target
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
        return (
            f"GMRuntime.gml_ds_grid_get({container}, {x_index}, {y_index})",
            lambda value: [
                f"GMRuntime.gml_ds_grid_set({container}, {x_index}, {y_index}, {value})"
            ],
        )

    selector_target = _selector_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if selector_target is not None:
        container, key = selector_target
        if isinstance(target_expr, _Member):
            container = _cache_assignment_part(
                prelude_lines,
                target_expr.target,
                container,
                generated_counter,
                "_gml_selector_target",
            )
        return (
            f"GMRuntime.gml_selector_get({container}, {key})",
            lambda value: [f"GMRuntime.gml_selector_set({container}, {key}, {value})"],
        )

    struct_target = _struct_assignment_parts(
        target_expr,
        local_names,
        scope_context=scope_context,
    )
    if struct_target is not None:
        container, key = struct_target
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
        return (
            f"GMRuntime.gml_struct_get({container}, {key})",
            lambda value: [f"GMRuntime.gml_struct_set({container}, {key}, {value})"],
        )

    if isinstance(target_expr, _Name) or (
        isinstance(target_expr, _Member)
        and _uses_direct_member_access(target_expr, scope_context=scope_context)
    ):
        emitted_target = _emit_expression(
            target_expr,
            local_names,
            scope_context=scope_context,
        )[0]
        return emitted_target, lambda value: [f"{emitted_target} = {value}"]

    raise GMLTranspileError("Assignment target must be assignable")


def _transpile_assignment_expression_to_temp(
    source: str,
    local_names: MutableSet[str],
    instance_variables: MutableSet[str] | None,
    enum_values: MutableMapping[str, dict[str, int]] | None = None,
    enum_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
    macro_values: Mapping[str, str] | None = None,
    generated_counter: list[int] | None = None,
    result_required: bool = True,
) -> tuple[list[str], str]:
    scope_context = _normalize_scope_context(scope_context)
    macro_values = macro_values or {}
    generated_counter = generated_counter if generated_counter is not None else [0]
    assignment = _split_assignment(source)
    if assignment is None:
        prelude_lines, value_source = _lower_mutation_expressions(
            source,
            local_names,
            instance_variables,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
        )
        return prelude_lines, transpile_gml_expression(
            value_source,
            local_names,
            enum_values,
            enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
        )

    target, operator, value = assignment
    target_expr = _parse_assignment_target(
        target,
        local_names,
        enum_values=enum_values,
        enum_names=enum_names,
        scope_context=scope_context,
        macro_values=macro_values,
    )
    prelude_lines: list[str] = []
    current_value, write_value = _assignment_target_reader_writer(
        target,
        target_expr,
        local_names,
        instance_variables,
        scope_context=scope_context,
        generated_counter=generated_counter,
        prelude_lines=prelude_lines,
    )

    if operator in ("=", ":="):
        rhs_lines, rhs_value = _transpile_assignment_expression_to_temp(
            value,
            local_names,
            instance_variables,
            enum_values=enum_values,
            enum_names=enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
            result_required=True,
        )
        if not result_required:
            return [
                *prelude_lines,
                *rhs_lines,
                *write_value(rhs_value),
            ], rhs_value
        result_name = _next_generated_name_from_counter(
            generated_counter,
            "_gml_assignment_value",
        )
        local_names.add(result_name)
        return [
            *prelude_lines,
            *rhs_lines,
            f"var {result_name} = {rhs_value}",
            *write_value(result_name),
        ], result_name

    if operator == "??=":
        result_name = _next_generated_name_from_counter(
            generated_counter,
            "_gml_assignment_value",
        )
        local_names.add(result_name)
        rhs_lines, rhs_value = _transpile_assignment_expression_to_temp(
            value,
            local_names,
            instance_variables,
            enum_values=enum_values,
            enum_names=enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
            result_required=True,
        )
        return [
            *prelude_lines,
            f"var {result_name} = {current_value}",
            f"if GMRuntime.gml_is_nullish({result_name}):",
            *_indent_lines(rhs_lines),
            f"\t{result_name} = {rhs_value}",
            *_indent_lines(write_value(result_name)),
        ], result_name

    if operator in _COMPOUND_RUNTIME_FUNCTIONS:
        rhs_lines, rhs_value = _transpile_assignment_expression_to_temp(
            value,
            local_names,
            instance_variables,
            enum_values=enum_values,
            enum_names=enum_names,
            scope_context=scope_context,
            macro_values=macro_values,
            generated_counter=generated_counter,
            result_required=True,
        )
        helper = _COMPOUND_RUNTIME_FUNCTIONS[operator]
        result_name = _next_generated_name_from_counter(
            generated_counter,
            "_gml_assignment_value",
        )
        local_names.add(result_name)
        return [
            *prelude_lines,
            *rhs_lines,
            f"var {result_name} = GMRuntime.{helper}({current_value}, {rhs_value})",
            *write_value(result_name),
        ], result_name

    raise GMLTranspileError("Unsupported assignment expression operator")


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
    if _is_alarm_array_access(target_expr, local_names):
        index = _alarm_array_index(target_expr, local_names, scope_context)
        return [_alarm_array_set(scope_context, index, value)]
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
    if isinstance(target_expr, _ArrayRefAccess):
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
