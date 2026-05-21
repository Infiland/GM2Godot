# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

import json
from typing import Iterable

from .constants import (
    _ARITHMETIC_RUNTIME_FUNCTIONS,
    _BINARY_PRECEDENCE,
    _BITWISE_RUNTIME_FUNCTIONS,
    _BOOLEAN_RESULT_BINARY_OPERATORS,
    _BOOLEAN_RESULT_FUNCTIONS,
    _BUILTIN_ARRAY_VARIABLES,
    _BUILTIN_GLOBAL_VARIABLES,
    _BUILTIN_INSTANCE_VARIABLES,
    _COMPARISON_RUNTIME_FUNCTIONS,
    _DIRECT_MEMBER_TARGETS,
    _GML_BUILTIN_CONSTANT_IDENTIFIERS,
    _GML_LITERAL_IDENTIFIERS,
    _INSTANCE_NAME_REPLACEMENTS,
    _NAME_REPLACEMENTS,
    _OPERATOR_REPLACEMENTS,
    _POSTFIX_PRECEDENCE,
    _PRIMARY_PRECEDENCE,
    _RIGHT_ASSOCIATIVE,
    _TERNARY_PRECEDENCE,
    _UNARY_PRECEDENCE,
    _VIRTUAL_KEY_ACTIONS,
    _VIRTUAL_KEY_CONSTANTS,
)
from .gml_function_dispatch import (
    GMLFunctionDescriptor,
    get_gml_function_descriptor,
    validate_gml_function_arity,
)
from .gml_api_manifest import diagnostic_for_unimplemented_gml_api
from .extension_functions import (
    diagnostic_for_unmapped_extension_function,
    validate_extension_mapping_arity,
)
from .identifiers import _is_plain_identifier, _sanitize_gdscript_identifier
from .model import (
    _ArrayLiteral,
    _ArrayRefAccess,
    _Binary,
    _Call,
    _DSGridAccess,
    _DSMapAccess,
    _DSListAccess,
    _Expression,
    _FunctionLiteral,
    _FunctionParameter,
    GMLTranspileError,
    _Grouped,
    _Index,
    _Literal,
    _Member,
    _Name,
    _NameOf,
    _NewCall,
    _NumberLiteral,
    _ScopeContext,
    _StringLiteral,
    _StructAccess,
    _StructLiteral,
    _Ternary,
    _Unary,
)
from .utils import _normalize_local_names, _normalize_scope_context, _unwrap_grouped_expression

_INSTANCE_SELECTOR_ARG_INDICES: dict[str, frozenset[int]] = {
    "instance_create_layer": frozenset({3}),
    "instance_create_depth": frozenset({3}),
    "instance_destroy": frozenset({0}),
    "instance_exists": frozenset({0}),
    "instance_find": frozenset({0}),
    "instance_number": frozenset({0}),
    "instance_nearest": frozenset({2}),
    "instance_furthest": frozenset({2}),
}

_COLLISION_SELECTOR_ARG_INDICES: dict[str, frozenset[int]] = {
    "place_meeting": frozenset({2}),
    "position_meeting": frozenset({2}),
    "instance_place": frozenset({2}),
    "instance_position": frozenset({2}),
    "collision_point": frozenset({2}),
    "collision_rectangle": frozenset({4}),
    "collision_line": frozenset({4}),
    "collision_circle": frozenset({3}),
    "collision_point_list": frozenset({2}),
    "collision_rectangle_list": frozenset({4}),
    "collision_line_list": frozenset({4}),
    "collision_circle_list": frozenset({3}),
}

_PATH_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "path_get_length": frozenset({0}),
    "path_start": frozenset({0}),
    "mp_grid_path": frozenset({1}),
}

_DRAW_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "draw_sprite": frozenset({0}),
    "draw_sprite_ext": frozenset({0}),
    "draw_sprite_part": frozenset({0}),
    "draw_sprite_part_ext": frozenset({0}),
    "draw_sprite_general": frozenset({0}),
    "draw_sprite_pos": frozenset({0}),
    "draw_sprite_tiled": frozenset({0}),
    "draw_sprite_tiled_ext": frozenset({0}),
    "draw_tile": frozenset({0}),
    "draw_set_font": frozenset({0}),
    "sprite_get_texture": frozenset({0}),
    "sprite_get_uvs": frozenset({0}),
    "sprite_prefetch": frozenset({0}),
    "sprite_flush": frozenset({0}),
    "texturegroup_set_mode": frozenset({2}),
    "shader_set": frozenset({0}),
    "shader_get_name": frozenset({0}),
    "shader_is_compiled": frozenset({0}),
    "shader_get_uniform": frozenset({0}),
    "shader_get_sampler_index": frozenset({0}),
    "part_system_create": frozenset({0}),
    "part_system_create_layer": frozenset({2}),
    "part_type_sprite": frozenset({1}),
    "camera_create_view": frozenset({5}),
}

_AUDIO_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "audio_play_sound": frozenset({0}),
    "audio_stop_sound": frozenset({0}),
    "audio_pause_sound": frozenset({0}),
    "audio_resume_sound": frozenset({0}),
    "audio_is_playing": frozenset({0}),
    "audio_sound_gain": frozenset({0}),
    "audio_sound_pitch": frozenset({0}),
    "sound_play": frozenset({0}),
    "sound_loop": frozenset({0}),
    "sound_stop": frozenset({0}),
    "sound_pause": frozenset({0}),
    "sound_resume": frozenset({0}),
    "sound_isplaying": frozenset({0}),
    "sound_volume": frozenset({0}),
    "sound_pitch": frozenset({0}),
}

_SCRIPT_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "script_execute": frozenset({0}),
    "script_exists": frozenset({0}),
    "script_get_name": frozenset({0}),
    "script_get_callable": frozenset({0}),
}

_ROOM_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "room_goto": frozenset({0}),
    "room_exists": frozenset({0}),
    "room_get_name": frozenset({0}),
    "room_get_info": frozenset({0}),
}

_SEQUENCE_TIMELINE_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "timeline_exists": frozenset({0}),
    "timeline_get_name": frozenset({0}),
    "timeline_moment_add_script": frozenset({0, 2}),
    "timeline_moment_clear": frozenset({0}),
    "timeline_clear": frozenset({0}),
    "timeline_size": frozenset({0}),
    "timeline_max_moment": frozenset({0}),
    "sequence_exists": frozenset({0}),
    "sequence_get": frozenset({0}),
    "sequence_destroy": frozenset({0}),
    "layer_sequence_create": frozenset({3}),
}


def _emit_name(
    value: str,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> tuple[str, int]:
    is_local = value in local_names
    if not is_local and value == "self":
        return scope_context.self_expression, _PRIMARY_PRECEDENCE
    if not is_local and value == "other":
        return scope_context.other_expression, _PRIMARY_PRECEDENCE
    if not is_local and value in _GML_LITERAL_IDENTIFIERS:
        return value, _PRIMARY_PRECEDENCE
    if (
        not is_local
        and scope_context.static_scope is not None
        and value in scope_context.static_names
    ):
        return (
            f"GMRuntime.gml_struct_get({scope_context.static_scope}, {json.dumps(value)})",
            _POSTFIX_PRECEDENCE,
        )
    if not is_local:
        if value in _BUILTIN_ARRAY_VARIABLES:
            return f"GMRuntime.gml_builtin_array({json.dumps(value)})", _POSTFIX_PRECEDENCE
        if value in _BUILTIN_GLOBAL_VARIABLES:
            return f"GMRuntime.gml_builtin_global({json.dumps(value)})", _POSTFIX_PRECEDENCE
        legacy_argument = _legacy_argument_replacement(value)
        if legacy_argument is not None:
            return legacy_argument, _POSTFIX_PRECEDENCE
        if _name_resolves_to_global(value, local_names, scope_context):
            return (
                "GMRuntime.gml_struct_get("
                f"GMRuntime.gml_global_scope(), {json.dumps(value)})"
            ), _POSTFIX_PRECEDENCE
        if scope_context.instance_target is not None and _is_plain_identifier(value):
            return (
                "GMRuntime.gml_variable_instance_get("
                f"{scope_context.instance_target}, {json.dumps(value)})"
            ), _POSTFIX_PRECEDENCE
        value = _INSTANCE_NAME_REPLACEMENTS.get(value, value)
    value = _sanitize_gdscript_identifier(value)
    return value, _PRIMARY_PRECEDENCE


def _name_resolves_to_global(
    name: str,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> bool:
    if name in local_names or not _is_plain_identifier(name):
        return False
    if name in _GML_LITERAL_IDENTIFIERS:
        return False
    if name in _BUILTIN_ARRAY_VARIABLES or name in _BUILTIN_GLOBAL_VARIABLES:
        return False
    if name in scope_context.global_names:
        return True
    return (
        scope_context.global_scope
        and name not in _BUILTIN_INSTANCE_VARIABLES
        and name not in _GML_BUILTIN_CONSTANT_IDENTIFIERS
    )


def _legacy_argument_replacement(name: str) -> str | None:
    if not name.startswith("argument"):
        return None
    suffix = name.removeprefix("argument")
    if not suffix.isdigit():
        return None
    index = int(suffix)
    if index < 0 or index > 15:
        return None
    return f"GMRuntime.gml_argument({index})"


def _emit_expression(
    expr: _Expression,
    local_names: Iterable[str] | None = None,
    bind_function_literals: bool = True,
    scope_context: _ScopeContext | None = None,
) -> tuple[str, int]:
    local_names = _normalize_local_names(local_names)
    scope_context = _normalize_scope_context(scope_context)
    if isinstance(expr, _Literal | _StringLiteral | _NumberLiteral):
        return expr.value, _PRIMARY_PRECEDENCE
    if isinstance(expr, _NameOf):
        return json.dumps(expr.value), _PRIMARY_PRECEDENCE
    if isinstance(expr, _Name):
        return _emit_name(expr.value, local_names, scope_context)
    if isinstance(expr, _Grouped):
        return (
            f"({_emit_expression(expr.expr, local_names, scope_context=scope_context)[0]})",
            _PRIMARY_PRECEDENCE,
        )
    if isinstance(expr, _Unary):
        if expr.operator == "!":
            return (
                f"not {_emit_truthy_expression(expr.operand, local_names, scope_context=scope_context)}",
                _UNARY_PRECEDENCE,
            )
        if expr.operator == "not":
            return (
                f"not {_emit_truthy_expression(expr.operand, local_names, scope_context=scope_context)}",
                _UNARY_PRECEDENCE,
            )
        if expr.operator == "~":
            operand = _emit_expression(expr.operand, local_names, scope_context=scope_context)[0]
            return f"GMRuntime.gml_bit_not({operand})", _POSTFIX_PRECEDENCE
        operand = _emit_child(
            expr.operand,
            _UNARY_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        return f"{expr.operator}{operand}", _UNARY_PRECEDENCE
    if isinstance(expr, _Binary):
        return _emit_binary(expr, local_names, scope_context=scope_context)
    if isinstance(expr, _Ternary):
        condition = _emit_truthy_expression(
            expr.condition,
            local_names,
            scope_context=scope_context,
        )
        true_expr = _emit_child(
            expr.true_expr,
            _TERNARY_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        false_expr = _emit_child(
            expr.false_expr,
            _TERNARY_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        return f"{true_expr} if {condition} else {false_expr}", _TERNARY_PRECEDENCE
    if isinstance(expr, _Call):
        builtin_call = _emit_builtin_call(expr, local_names, scope_context=scope_context)
        if builtin_call is not None:
            return builtin_call, _POSTFIX_PRECEDENCE
        callee = _emit_child(
            expr.callee,
            _POSTFIX_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        args = ", ".join(
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in expr.args
        )
        return f"{callee}({args})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _ArrayLiteral):
        elements = ", ".join(
            _emit_expression(element, local_names, scope_context=scope_context)[0]
            for element in expr.elements
        )
        return f"[{elements}]", _PRIMARY_PRECEDENCE
    if isinstance(expr, _FunctionLiteral):
        function_literal = _emit_function_literal(expr, local_names, scope_context=scope_context)
        if expr.static_scope_id is not None:
            function_literal = (
                "GMRuntime.gml_static_bind("
                f"{function_literal}, {json.dumps(expr.static_scope_id)}, {json.dumps(expr.name or '')})"
            )
        if bind_function_literals:
            if expr.is_constructor:
                return (
                    f"GMRuntime.gml_constructor({scope_context.self_expression}, {function_literal})",
                    _POSTFIX_PRECEDENCE,
                )
            return (
                f"GMRuntime.gml_method({scope_context.self_expression}, {function_literal})",
                _POSTFIX_PRECEDENCE,
            )
        return function_literal, _PRIMARY_PRECEDENCE
    if isinstance(expr, _NewCall):
        constructor = _emit_expression(
            expr.constructor,
            local_names,
            scope_context=scope_context,
        )[0]
        args = ", ".join(
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in expr.args
        )
        return f"GMRuntime.gml_new({constructor}, [{args}])", _POSTFIX_PRECEDENCE
    if isinstance(expr, _StructLiteral):
        fields = ", ".join(
            _emit_struct_field(
                field_name,
                field_value,
                local_names,
                scope_context=scope_context,
            )
            for field_name, field_value in expr.fields
        )
        return f"GMRuntime.gml_struct({{{fields}}})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _Index):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        index = _emit_expression(expr.index, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_array_get({target}, {index})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _StructAccess):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        key = _emit_expression(expr.key, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_struct_get({target}, {key})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _DSMapAccess):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        key = _emit_expression(expr.key, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_ds_map_find_value({target}, {key})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _DSListAccess):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        index = _emit_expression(expr.index, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_ds_list_find_value({target}, {index})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _DSGridAccess):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        x_index = _emit_expression(expr.x_index, local_names, scope_context=scope_context)[0]
        y_index = _emit_expression(expr.y_index, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_ds_grid_get({target}, {x_index}, {y_index})", _POSTFIX_PRECEDENCE
    if isinstance(expr, _ArrayRefAccess):
        target = _emit_expression(expr.target, local_names, scope_context=scope_context)[0]
        index = _emit_expression(expr.index, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_array_get({target}, {index})", _POSTFIX_PRECEDENCE
    if _uses_direct_member_access(expr, scope_context=scope_context):
        target = _emit_child(
            expr.target,
            _POSTFIX_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        return f"{target}.{_sanitize_gdscript_identifier(expr.member)}", _POSTFIX_PRECEDENCE
    target = _emit_instance_keyword_argument(
        expr.target,
        local_names,
        scope_context=scope_context,
    )
    return f"GMRuntime.gml_selector_get({target}, {json.dumps(expr.member)})", _POSTFIX_PRECEDENCE


def _uses_direct_member_access(
    expr: _Member,
    scope_context: _ScopeContext | None = None,
) -> bool:
    scope_context = _normalize_scope_context(scope_context)
    if not isinstance(expr.target, _Name):
        return False
    if expr.target.value == "self" and scope_context.self_expression != "self":
        return False
    if expr.target.value == "other" and scope_context.other_expression != "other":
        return False
    return expr.target.value in _DIRECT_MEMBER_TARGETS


def _emit_function_literal(
    expr: _FunctionLiteral,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> str:
    name = f" {_sanitize_gdscript_identifier(expr.name)}" if expr.name is not None else ""
    parameter_names = [parameter.name for parameter in expr.parameters]
    emitted_parameters = [
        f"{_sanitize_gdscript_identifier(parameter.name)} = null"
        for parameter in expr.parameters
    ]
    if expr.is_constructor:
        emitted_parameters.insert(0, "_gml_constructor_self = null")
    parameters = ", ".join(emitted_parameters)
    default_lines = _emit_function_parameter_default_lines(
        expr.parameters,
        parameter_names,
        scope_context=scope_context,
    )
    body = "; ".join([*default_lines, *expr.body_lines])
    return f"func{name}({parameters}): {body}"


def _emit_struct_field(
    field_name: str,
    field_value: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> str:
    bind_function_literal = not isinstance(_unwrap_grouped_expression(field_value), _FunctionLiteral)
    field_text = _emit_expression(
        field_value,
        local_names,
        bind_function_literal,
        scope_context=scope_context,
    )[0]
    return f"{json.dumps(field_name)}: {field_text}"


def _emit_function_parameter_default_lines(
    parameters: Iterable[_FunctionParameter],
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> list[str]:
    default_lines: list[str] = []
    for parameter in parameters:
        parameter_name = _sanitize_gdscript_identifier(parameter.name)
        if parameter.default is None:
            default_lines.append(f"if {parameter_name} == null: {parameter_name} = GMRuntime.gml_undefined()")
            continue
        default_value = _emit_expression(
            parameter.default,
            local_names,
            scope_context=scope_context,
        )[0]
        default_lines.append(
            f"if {parameter_name} == null or GMRuntime.is_undefined({parameter_name}): "
            f"{parameter_name} = {default_value}",
        )
    return default_lines


def _emit_builtin_call(
    expr: _Call,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> str | None:
    scope_context = _normalize_scope_context(scope_context)
    if not isinstance(expr.callee, _Name):
        return None

    descriptor = get_gml_function_descriptor(expr.callee.value)
    if descriptor is not None and descriptor.lowering_kind != "runtime_platform_service_api":
        return _emit_descriptor_call(
            descriptor,
            expr.args,
            local_names,
            scope_context=scope_context,
        )

    extension_mapping = scope_context.extension_function_mappings.get(expr.callee.value)
    if extension_mapping is not None:
        arity_diagnostic = validate_extension_mapping_arity(extension_mapping, len(expr.args))
        if arity_diagnostic is not None:
            raise GMLTranspileError(arity_diagnostic)
        emitted_args = ", ".join(
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in expr.args
        )
        return f"{extension_mapping.target}({emitted_args})"

    extension_function = scope_context.extension_functions.get(expr.callee.value)
    if extension_function is not None:
        raise GMLTranspileError(diagnostic_for_unmapped_extension_function(extension_function))

    if descriptor is not None:
        return _emit_descriptor_call(
            descriptor,
            expr.args,
            local_names,
            scope_context=scope_context,
        )

    diagnostic = diagnostic_for_unimplemented_gml_api(expr.callee.value)
    if diagnostic is not None:
        raise GMLTranspileError(diagnostic)
    return None


def _emit_descriptor_call(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> str:
    arity_diagnostic = validate_gml_function_arity(descriptor, len(args))
    if arity_diagnostic is not None:
        raise GMLTranspileError(arity_diagnostic)

    if descriptor.lowering_kind == "keyboard_check":
        key = args[0]
        if isinstance(key, _Name) and key.value in _VIRTUAL_KEY_ACTIONS:
            return f'Input.is_action_pressed("{_VIRTUAL_KEY_ACTIONS[key.value]}")'
        if isinstance(key, _Name) and key.value in _VIRTUAL_KEY_CONSTANTS:
            return f"Input.is_key_pressed({_VIRTUAL_KEY_CONSTANTS[key.value]})"
        raise GMLTranspileError(
            "GML API 'keyboard_check' currently supports mapped vk_* constants only; "
            f"tracked by #{descriptor.issue_number}."
        )

    if descriptor.lowering_kind == "method":
        scope = _emit_expression(args[0], local_names, scope_context=scope_context)[0]
        if scope == _NAME_REPLACEMENTS["undefined"]:
            scope = scope_context.self_expression
        function_value = _emit_expression(
            args[1],
            local_names,
            scope_context=scope_context,
        )[0]
        return f"GMRuntime.{descriptor.lowering_target}({scope}, {function_value})"

    if descriptor.lowering_kind == "with_targets":
        target = _emit_instance_keyword_argument(
            args[0],
            local_names,
            scope_context=scope_context,
        )
        return f"GMRuntime.{descriptor.lowering_target}({target})"

    if descriptor.lowering_kind == "print":
        arg = _emit_expression(args[0], local_names, scope_context=scope_context)[0]
        return f"{descriptor.lowering_target}({arg})"

    if descriptor.lowering_kind == "runtime_instance_keyword_first_arg":
        first_arg = _emit_instance_keyword_argument(
            args[0],
            local_names,
            scope_context=scope_context,
        )
        remaining_args = [
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in args[1:]
        ]
        emitted_args = ", ".join([first_arg, *remaining_args])
        return f"GMRuntime.{descriptor.lowering_target}({emitted_args})"

    if descriptor.lowering_kind in {
        "runtime_audio_api",
        "runtime_append_self",
        "runtime_collision_api",
        "runtime_draw_api",
        "runtime_instance_api",
        "runtime_motion_api",
        "runtime_layer_api",
        "runtime_path_api",
        "runtime_path_asset_api",
        "runtime_room_api",
        "runtime_sequence_api",
        "runtime_self_default",
        "runtime_time_api",
    }:
        emitted_args = _emit_instance_api_args(
            descriptor,
            args,
            local_names,
            scope_context=scope_context,
        )
        if descriptor.lowering_kind == "runtime_audio_api":
            emitted_args = _emit_audio_api_args(
                descriptor,
                args,
                local_names,
                scope_context=scope_context,
            )
        if descriptor.lowering_kind == "runtime_collision_api":
            emitted_args.insert(0, scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_draw_api":
            emitted_args = _emit_draw_api_args(
                descriptor,
                args,
                local_names,
                scope_context=scope_context,
            )
        if descriptor.lowering_kind == "runtime_room_api":
            emitted_args = _emit_room_api_args(
                descriptor,
                args,
                local_names,
                scope_context=scope_context,
            )
        if descriptor.lowering_kind == "runtime_sequence_api":
            emitted_args = _emit_sequence_api_args(
                descriptor,
                args,
                local_names,
                scope_context=scope_context,
            )
            if descriptor.name == "timeline_step" and not emitted_args:
                emitted_args.append(scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_time_api":
            emitted_args.insert(0, scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_motion_api":
            emitted_args.insert(0, scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_path_api":
            emitted_args.insert(0, scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_append_self":
            emitted_args.append(scope_context.self_expression)
        if descriptor.lowering_kind == "runtime_self_default" and not emitted_args:
            emitted_args.append(scope_context.self_expression)
        return f"GMRuntime.{descriptor.lowering_target}({', '.join(emitted_args)})"

    if descriptor.lowering_kind == "runtime_variadic_1":
        if 0 in _SCRIPT_ASSET_ARG_INDICES.get(descriptor.name, frozenset()):
            emitted_first = _emit_asset_argument(args[0], local_names, scope_context=scope_context)
        else:
            emitted_first = _emit_expression(args[0], local_names, scope_context=scope_context)[0]
        emitted_rest = ", ".join(
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in args[1:]
        )
        return f"GMRuntime.{descriptor.lowering_target}({emitted_first}, [{emitted_rest}])"

    if descriptor.lowering_kind == "runtime_platform_service_api":
        emitted_args = ", ".join(
            _emit_expression(arg, local_names, scope_context=scope_context)[0]
            for arg in args
        )
        return (
            f"GMRuntime.gml_platform_service_call("
            f"{json.dumps(descriptor.lowering_target)}, "
            f"{json.dumps(descriptor.name)}, "
            f"[{emitted_args}]"
            f")"
        )

    script_asset_indices = _SCRIPT_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args = ", ".join(
        _emit_asset_argument(arg, local_names, scope_context=scope_context)
        if index in script_asset_indices
        else _emit_expression(arg, local_names, scope_context=scope_context)[0]
        for index, arg in enumerate(args)
    )
    return f"GMRuntime.{descriptor.lowering_target}({emitted_args})"


def _emit_instance_keyword_argument(
    expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> str:
    scope_context = _normalize_scope_context(scope_context)
    legacy_keyword = _legacy_instance_keyword_value(expr)
    if legacy_keyword == -1:
        return scope_context.self_expression
    if legacy_keyword == -2:
        return scope_context.other_expression
    if legacy_keyword == -3:
        return "GMRuntime.gml_instance_all()"
    if legacy_keyword == -4:
        return "GMRuntime.gml_instance_noone()"
    unwrapped_expr = _unwrap_grouped_expression(expr)
    if isinstance(unwrapped_expr, _Name) and unwrapped_expr.value in scope_context.asset_names:
        return f"GMRuntime.gml_asset_get_index({json.dumps(unwrapped_expr.value)})"
    return _emit_expression(expr, local_names, scope_context=scope_context)[0]


def _emit_instance_api_args(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str]:
    selector_indices = _INSTANCE_SELECTOR_ARG_INDICES.get(descriptor.name)
    if selector_indices is None:
        selector_indices = _COLLISION_SELECTOR_ARG_INDICES.get(descriptor.name, frozenset())
    asset_indices = _PATH_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args: list[str] = []
    for index, arg in enumerate(args):
        if index in selector_indices or index in asset_indices:
            emitted_args.append(
                _emit_instance_keyword_argument(
                    arg,
                    local_names,
                    scope_context=scope_context,
                )
            )
        else:
            emitted_args.append(_emit_expression(arg, local_names, scope_context=scope_context)[0])
    return emitted_args


def _emit_draw_api_args(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str]:
    asset_indices = _DRAW_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args: list[str] = []
    for index, arg in enumerate(args):
        if index in asset_indices:
            emitted_args.append(_emit_asset_argument(arg, local_names, scope_context=scope_context))
        else:
            emitted_args.append(_emit_expression(arg, local_names, scope_context=scope_context)[0])
    return emitted_args


def _emit_audio_api_args(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str]:
    asset_indices = _AUDIO_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args: list[str] = []
    for index, arg in enumerate(args):
        if index in asset_indices:
            emitted_args.append(_emit_asset_argument(arg, local_names, scope_context=scope_context))
        else:
            emitted_args.append(_emit_expression(arg, local_names, scope_context=scope_context)[0])
    return emitted_args


def _emit_room_api_args(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str]:
    asset_indices = _ROOM_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args: list[str] = []
    for index, arg in enumerate(args):
        if index in asset_indices:
            emitted_args.append(_emit_asset_argument(arg, local_names, scope_context=scope_context))
        else:
            emitted_args.append(_emit_expression(arg, local_names, scope_context=scope_context)[0])
    return emitted_args


def _emit_sequence_api_args(
    descriptor: GMLFunctionDescriptor,
    args: tuple[_Expression, ...],
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> list[str]:
    asset_indices = _SEQUENCE_TIMELINE_ASSET_ARG_INDICES.get(descriptor.name, frozenset())
    emitted_args: list[str] = []
    for index, arg in enumerate(args):
        if index in asset_indices:
            emitted_args.append(_emit_asset_argument(arg, local_names, scope_context=scope_context))
        else:
            emitted_args.append(_emit_expression(arg, local_names, scope_context=scope_context)[0])
    return emitted_args


def _emit_asset_argument(
    expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext,
) -> str:
    unwrapped_expr = _unwrap_grouped_expression(expr)
    if isinstance(unwrapped_expr, _Name) and unwrapped_expr.value in scope_context.asset_names:
        return f"GMRuntime.gml_asset_get_index({json.dumps(unwrapped_expr.value)})"
    return _emit_expression(expr, local_names, scope_context=scope_context)[0]


def _legacy_instance_keyword_value(expr: _Expression) -> int | None:
    unwrapped_expr = _unwrap_grouped_expression(expr)
    if not isinstance(unwrapped_expr, _Unary) or unwrapped_expr.operator != "-":
        return None
    operand = _unwrap_grouped_expression(unwrapped_expr.operand)
    if not isinstance(operand, _NumberLiteral) or operand.is_float_like:
        return None
    try:
        value = int(operand.value, 0)
    except ValueError:
        return None
    if value in (1, 2, 3, 4):
        return -value
    return None


def _emit_binary(
    expr: _Binary,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> tuple[str, int]:
    scope_context = _normalize_scope_context(scope_context)
    operator = _OPERATOR_REPLACEMENTS.get(expr.operator, expr.operator)

    if expr.operator in ("&&", "and", "||", "or"):
        operator = "and" if expr.operator in ("&&", "and") else "or"
        left = _emit_truthy_expression(expr.left, local_names, scope_context=scope_context)
        right = _emit_truthy_expression(expr.right, local_names, scope_context=scope_context)
        return f"{left} {operator} {right}", _BINARY_PRECEDENCE[expr.operator]

    if expr.operator == "^^":
        left = _emit_truthy_expression(expr.left, local_names, scope_context=scope_context)
        right = _emit_truthy_expression(expr.right, local_names, scope_context=scope_context)
        return f"{left} != {right}", _BINARY_PRECEDENCE[expr.operator]

    if expr.operator == "div":
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_int_div({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator == "??":
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_child(
            expr.right,
            _TERNARY_PRECEDENCE,
            local_names=local_names,
            scope_context=scope_context,
        )
        return f"{left} if not GMRuntime.gml_is_nullish({left}) else {right}", _TERNARY_PRECEDENCE

    if expr.operator in ("=", "==", "!=") and (
        _contains_gml_undefined(expr.left)
        or _contains_gml_undefined(expr.right)
        or _contains_gml_nan(expr.left)
        or _contains_gml_nan(expr.right)
        or _contains_gml_pointer(expr.left)
        or _contains_gml_pointer(expr.right)
        or _contains_gml_handle(expr.left)
        or _contains_gml_handle(expr.right)
        or _may_need_gml_reference_equality(expr.left)
        or _may_need_gml_reference_equality(expr.right)
    ):
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        helper = "gml_ne" if expr.operator == "!=" else "gml_eq"
        return f"GMRuntime.{helper}({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator == "/":
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.gml_div({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator in _COMPARISON_RUNTIME_FUNCTIONS:
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.{_COMPARISON_RUNTIME_FUNCTIONS[expr.operator]}({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator in _ARITHMETIC_RUNTIME_FUNCTIONS:
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.{_ARITHMETIC_RUNTIME_FUNCTIONS[expr.operator]}({left}, {right})", _POSTFIX_PRECEDENCE

    if expr.operator in _BITWISE_RUNTIME_FUNCTIONS:
        left = _emit_expression(expr.left, local_names, scope_context=scope_context)[0]
        right = _emit_expression(expr.right, local_names, scope_context=scope_context)[0]
        return f"GMRuntime.{_BITWISE_RUNTIME_FUNCTIONS[expr.operator]}({left}, {right})", _POSTFIX_PRECEDENCE

    precedence = _BINARY_PRECEDENCE[expr.operator]
    left = _emit_child(
        expr.left,
        precedence,
        local_names=local_names,
        scope_context=scope_context,
    )
    right = _emit_child(
        expr.right,
        precedence,
        is_right_child=True,
        parent_operator=expr.operator,
        local_names=local_names,
        scope_context=scope_context,
    )
    return f"{left} {operator} {right}", precedence


def _contains_gml_undefined(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value == "GMRuntime.gml_undefined()"
    if isinstance(expr, _Grouped):
        return _contains_gml_undefined(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_undefined(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_undefined(expr.left) or _contains_gml_undefined(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_undefined(expr.condition)
            or _contains_gml_undefined(expr.true_expr)
            or _contains_gml_undefined(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return _contains_gml_undefined(expr.callee) or any(
            _contains_gml_undefined(arg) for arg in expr.args
        )
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_undefined(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _NewCall):
        return _contains_gml_undefined(expr.constructor) or any(
            _contains_gml_undefined(arg) for arg in expr.args
        )
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_undefined(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.key)
    if isinstance(expr, _DSMapAccess):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.key)
    if isinstance(expr, _DSListAccess):
        return _contains_gml_undefined(expr.target) or _contains_gml_undefined(expr.index)
    if isinstance(expr, _Member):
        return _contains_gml_undefined(expr.target)
    return False


def _contains_gml_nan(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value == "NAN"
    if isinstance(expr, _Grouped):
        return _contains_gml_nan(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_nan(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_nan(expr.left) or _contains_gml_nan(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_nan(expr.condition)
            or _contains_gml_nan(expr.true_expr)
            or _contains_gml_nan(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return _contains_gml_nan(expr.callee) or any(_contains_gml_nan(arg) for arg in expr.args)
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_nan(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _NewCall):
        return _contains_gml_nan(expr.constructor) or any(
            _contains_gml_nan(arg) for arg in expr.args
        )
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_nan(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.key)
    if isinstance(expr, _DSMapAccess):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.key)
    if isinstance(expr, _DSListAccess):
        return _contains_gml_nan(expr.target) or _contains_gml_nan(expr.index)
    if isinstance(expr, _Member):
        return _contains_gml_nan(expr.target)
    return False


def _contains_gml_pointer(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value in ("GMRuntime.gml_pointer_null()", "GMRuntime.gml_pointer_invalid()")
    if isinstance(expr, _Grouped):
        return _contains_gml_pointer(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_pointer(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_pointer(expr.left) or _contains_gml_pointer(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_pointer(expr.condition)
            or _contains_gml_pointer(expr.true_expr)
            or _contains_gml_pointer(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return (
            isinstance(expr.callee, _Name)
            and expr.callee.value == "ptr"
        ) or any(_contains_gml_pointer(arg) for arg in expr.args)
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_pointer(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _NewCall):
        return _contains_gml_pointer(expr.constructor) or any(
            _contains_gml_pointer(arg) for arg in expr.args
        )
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_pointer(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.key)
    if isinstance(expr, _DSMapAccess):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.key)
    if isinstance(expr, _DSListAccess):
        return _contains_gml_pointer(expr.target) or _contains_gml_pointer(expr.index)
    if isinstance(expr, _Member):
        return _contains_gml_pointer(expr.target)
    return False


def _contains_gml_handle(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value == "GMRuntime.gml_instance_noone()"
    if isinstance(expr, _Grouped):
        return _contains_gml_handle(expr.expr)
    if isinstance(expr, _Unary):
        return _contains_gml_handle(expr.operand)
    if isinstance(expr, _Binary):
        return _contains_gml_handle(expr.left) or _contains_gml_handle(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _contains_gml_handle(expr.condition)
            or _contains_gml_handle(expr.true_expr)
            or _contains_gml_handle(expr.false_expr)
        )
    if isinstance(expr, _Call):
        return any(_contains_gml_handle(arg) for arg in expr.args)
    if isinstance(expr, _ArrayLiteral):
        return any(_contains_gml_handle(element) for element in expr.elements)
    if isinstance(expr, _FunctionLiteral):
        return False
    if isinstance(expr, _NewCall):
        return _contains_gml_handle(expr.constructor) or any(
            _contains_gml_handle(arg) for arg in expr.args
        )
    if isinstance(expr, _StructLiteral):
        return any(_contains_gml_handle(field_value) for _field_name, field_value in expr.fields)
    if isinstance(expr, _Index):
        return _contains_gml_handle(expr.target) or _contains_gml_handle(expr.index)
    if isinstance(expr, _StructAccess):
        return _contains_gml_handle(expr.target) or _contains_gml_handle(expr.key)
    if isinstance(expr, _DSMapAccess):
        return _contains_gml_handle(expr.target) or _contains_gml_handle(expr.key)
    if isinstance(expr, _DSListAccess):
        return _contains_gml_handle(expr.target) or _contains_gml_handle(expr.index)
    if isinstance(expr, _Member):
        return _contains_gml_handle(expr.target)
    return False


def _may_need_gml_reference_equality(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value not in {"true", "false", "INF", "NAN"}
    if isinstance(expr, (_ArrayLiteral, _StructLiteral, _FunctionLiteral)):
        return True
    if isinstance(expr, (_Call, _NewCall, _Index, _StructAccess, _DSMapAccess, _DSListAccess, _Member)):
        return True
    if isinstance(expr, _Grouped):
        return _may_need_gml_reference_equality(expr.expr)
    if isinstance(expr, _Unary):
        return _may_need_gml_reference_equality(expr.operand)
    if isinstance(expr, _Binary):
        return _may_need_gml_reference_equality(expr.left) or _may_need_gml_reference_equality(expr.right)
    if isinstance(expr, _Ternary):
        return (
            _may_need_gml_reference_equality(expr.condition)
            or _may_need_gml_reference_equality(expr.true_expr)
            or _may_need_gml_reference_equality(expr.false_expr)
        )
    return False


def _emit_truthy_expression(
    expr: _Expression,
    local_names: Iterable[str],
    scope_context: _ScopeContext | None = None,
) -> str:
    if _emits_boolean_result(expr):
        return _emit_expression(expr, local_names, scope_context=scope_context)[0]
    return _gml_bool_call(_emit_expression(expr, local_names, scope_context=scope_context)[0])


def _emits_boolean_result(expr: _Expression) -> bool:
    if isinstance(expr, _Name):
        return expr.value in ("true", "false")
    if isinstance(expr, _Grouped):
        return _emits_boolean_result(expr.expr)
    if isinstance(expr, _Unary):
        return expr.operator in ("!", "not")
    if isinstance(expr, _Binary):
        return expr.operator in _BOOLEAN_RESULT_BINARY_OPERATORS
    if isinstance(expr, _Call) and isinstance(expr.callee, _Name):
        return expr.callee.value in _BOOLEAN_RESULT_FUNCTIONS
    return False


def _gml_bool_call(expression: str) -> str:
    return f"GMRuntime.gml_bool({expression})"


def _emit_child(
    expr: _Expression,
    parent_precedence: int,
    is_right_child: bool = False,
    parent_operator: str | None = None,
    local_names: Iterable[str] | None = None,
    scope_context: _ScopeContext | None = None,
) -> str:
    text, precedence = _emit_expression(expr, local_names, scope_context=scope_context)
    needs_parentheses = precedence < parent_precedence
    if is_right_child and precedence == parent_precedence and parent_operator not in _RIGHT_ASSOCIATIVE:
        needs_parentheses = True
    if needs_parentheses:
        return f"({text})"
    return text
