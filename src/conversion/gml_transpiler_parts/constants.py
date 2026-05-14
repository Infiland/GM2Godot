# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from .model import _AssignmentOperator, _BuiltinVariableMetadata, _Token

_EOF = _Token("EOF", "")

_MULTI_CHAR_OPERATORS = (
    "??=",
    "<<=",
    ">>=",
    ":=",
    "??",
    "<=",
    ">=",
    "==",
    "!=",
    "&&",
    "||",
    "^^",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
)

_ASSIGNMENT_OPERATORS: tuple[_AssignmentOperator, ...] = (
    "??=",
    "<<=",
    ">>=",
    ":=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "=",
)

_BINARY_PRECEDENCE = {
    "??": 10,
    "or": 20,
    "||": 20,
    "^^": 20,
    "and": 30,
    "&&": 30,
    "|": 40,
    "^": 50,
    "&": 60,
    "=": 70,
    "==": 70,
    "!=": 70,
    "<": 70,
    "<=": 70,
    ">": 70,
    ">=": 70,
    "<<": 80,
    ">>": 80,
    "+": 90,
    "-": 90,
    "*": 100,
    "/": 100,
    "%": 100,
    "div": 100,
    "mod": 100,
}

_UNARY_PRECEDENCE = 110
_POSTFIX_PRECEDENCE = 120
_PRIMARY_PRECEDENCE = 130
_TERNARY_PRECEDENCE = 5
_GML_IDENTIFIER_MAX_LENGTH = 64
_GENERATED_IDENTIFIER_PREFIX = "_gml_"

_RIGHT_ASSOCIATIVE = {"??"}

_GDSCRIPT_RESERVED_IDENTIFIERS = frozenset({
    "as",
    "break",
    "class",
    "class_name",
    "const",
    "continue",
    "elif",
    "else",
    "enum",
    "extends",
    "false",
    "for",
    "func",
    "if",
    "in",
    "is",
    "match",
    "null",
    "pass",
    "return",
    "self",
    "signal",
    "static",
    "super",
    "true",
    "var",
    "void",
    "when",
    "while",
})
_GML_LITERAL_IDENTIFIERS = frozenset({
    "false",
    "null",
    "self",
    "super",
    "true",
})
_GML_BUILTIN_CONSTANT_IDENTIFIERS = frozenset({
    "NaN",
    "all",
    "false",
    "infinity",
    "nan",
    "noone",
    "null",
    "pi",
    "pointer_invalid",
    "pointer_null",
    "true",
    "undefined",
})
_DIRECT_MEMBER_TARGETS = frozenset({
    "global",
    "other",
    "self",
    "super",
})

_BOOLEAN_RESULT_BINARY_OPERATORS = frozenset({
    "&&",
    "||",
    "^^",
    "and",
    "or",
    "=",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
})

_BOOLEAN_RESULT_FUNCTIONS = frozenset({
    "bool",
    "is_array",
    "is_bool",
    "is_callable",
    "is_handle",
    "is_infinity",
    "is_int32",
    "is_int64",
    "is_method",
    "is_nan",
    "is_numeric",
    "is_ptr",
    "is_real",
    "is_string",
    "is_struct",
    "struct_exists",
    "is_undefined",
    "keyboard_check",
})

_ARITHMETIC_RUNTIME_FUNCTIONS = {
    "+": "gml_add",
    "-": "gml_sub",
    "*": "gml_mul",
    "%": "gml_mod",
    "mod": "gml_mod",
}

_BITWISE_RUNTIME_FUNCTIONS = {
    "&": "gml_bit_and",
    "|": "gml_bit_or",
    "^": "gml_bit_xor",
    "<<": "gml_shift_left",
    ">>": "gml_shift_right",
}

_COMPOUND_RUNTIME_FUNCTIONS: dict[_AssignmentOperator, str] = {
    "&=": "gml_bit_and",
    "+=": "gml_add",
    "-=": "gml_sub",
    "*=": "gml_mul",
    "/=": "gml_div",
    "%=": "gml_mod",
    "<<=": "gml_shift_left",
    ">>=": "gml_shift_right",
    "|=": "gml_bit_or",
    "^=": "gml_bit_xor",
}

_OPERATOR_REPLACEMENTS = {
    "&&": "and",
    "||": "or",
    "=": "==",
    "mod": "%",
}

_NAME_REPLACEMENTS = {
    "all": "GMRuntime.gml_instance_all()",
    "application_surface": 'GMRuntime.gml_builtin_global("application_surface")',
    "c_aqua": "0xffff00",
    "c_black": "0x000000",
    "c_blue": "0xff0000",
    "c_dkgray": "0x404040",
    "c_fuchsia": "0xff00ff",
    "c_gray": "0x808080",
    "c_green": "0x008000",
    "c_lime": "0x00ff00",
    "c_ltgray": "0xc0c0c0",
    "c_maroon": "0x000080",
    "c_navy": "0x800000",
    "c_olive": "0x008080",
    "c_orange": "0x00a5ff",
    "c_purple": "0x800080",
    "c_red": "0x0000ff",
    "c_silver": "0xc0c0c0",
    "c_teal": "0x808000",
    "c_white": "0xffffff",
    "c_yellow": "0x00ffff",
    "fa_left": "0",
    "fa_center": "1",
    "fa_right": "2",
    "fa_top": "0",
    "fa_middle": "1",
    "fa_bottom": "2",
    "global": "GMRuntime.gml_global_scope()",
    "infinity": "INF",
    "NaN": "NAN",
    "nan": "NAN",
    "noone": "GMRuntime.gml_instance_noone()",
    "pi": "PI",
    "pointer_invalid": "GMRuntime.gml_pointer_invalid()",
    "pointer_null": "GMRuntime.gml_pointer_null()",
    "surface_rgba8unorm": "0",
    "surface_r8unorm": "1",
    "surface_rg8unorm": "2",
    "surface_rgba4unorm": "3",
    "surface_rgba16float": "4",
    "surface_r16float": "5",
    "surface_rgba32float": "6",
    "surface_r32float": "7",
    "tile_flip": "0x20000000",
    "tile_index_mask": "0x000fffff",
    "tile_mirror": "0x10000000",
    "tile_rotate": "0x40000000",
    "undefined": "GMRuntime.gml_undefined()",
}

_BLOCK_DELIMITER_REPLACEMENTS = {
    "begin": "{",
    "end": "}",
}

_INSTANCE_NAME_REPLACEMENTS = {
    "x": "position.x",
    "y": "position.y",
}

_LEGACY_GLOBAL_BUILTINS = frozenset({"health", "lives", "score"})

_BUILTIN_VARIABLE_REGISTRY = {
    "application_surface": _BuiltinVariableMetadata("global", "undefined", False, False, "surface"),
    "argument": _BuiltinVariableMetadata("global", "[]", False, False, "script_arguments"),
    "argument_count": _BuiltinVariableMetadata("global", "0", False, False, "script_arguments"),
    "async_load": _BuiltinVariableMetadata("global", "{}", False, False, "async_event"),
    "bbox_bottom": _BuiltinVariableMetadata("instance", "0", False, False, "collision_bounds"),
    "bbox_left": _BuiltinVariableMetadata("instance", "0", False, False, "collision_bounds"),
    "bbox_right": _BuiltinVariableMetadata("instance", "0", False, False, "collision_bounds"),
    "bbox_top": _BuiltinVariableMetadata("instance", "0", False, False, "collision_bounds"),
    "current_time": _BuiltinVariableMetadata("global", "0", False, False, "time"),
    "depth": _BuiltinVariableMetadata("instance", "0", True, False, "rendering"),
    "direction": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "event_data": _BuiltinVariableMetadata("global", "{}", False, False, "event"),
    "fps": _BuiltinVariableMetadata("global", "0", False, False, "time"),
    "friction": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "gravity": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "gravity_direction": _BuiltinVariableMetadata("instance", "270", True, False, "motion"),
    "hspeed": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "id": _BuiltinVariableMetadata("instance", "undefined", False, False, "identity"),
    "image_alpha": _BuiltinVariableMetadata("instance", "1", True, False, "sprite"),
    "image_angle": _BuiltinVariableMetadata("instance", "0", True, False, "sprite"),
    "image_blend": _BuiltinVariableMetadata("instance", "16777215", True, False, "sprite"),
    "image_index": _BuiltinVariableMetadata("instance", "0", True, False, "sprite"),
    "image_number": _BuiltinVariableMetadata("instance", "0", False, False, "sprite"),
    "image_speed": _BuiltinVariableMetadata("instance", "1", True, False, "sprite"),
    "image_xscale": _BuiltinVariableMetadata("instance", "1", True, False, "sprite"),
    "image_yscale": _BuiltinVariableMetadata("instance", "1", True, False, "sprite"),
    "instance_count": _BuiltinVariableMetadata("global", "0", False, False, "instances"),
    "layer": _BuiltinVariableMetadata("instance", "0", True, False, "rendering"),
    "object_index": _BuiltinVariableMetadata("instance", "undefined", False, False, "identity"),
    "path_index": _BuiltinVariableMetadata("instance", "undefined", True, False, "path"),
    "path_position": _BuiltinVariableMetadata("instance", "0", True, False, "path"),
    "path_scale": _BuiltinVariableMetadata("instance", "1", True, False, "path"),
    "path_speed": _BuiltinVariableMetadata("instance", "0", True, False, "path"),
    "room": _BuiltinVariableMetadata("global", "undefined", False, False, "room"),
    "room_height": _BuiltinVariableMetadata("global", "0", False, False, "room"),
    "room_width": _BuiltinVariableMetadata("global", "0", False, False, "room"),
    "solid": _BuiltinVariableMetadata("instance", "false", True, False, "collision"),
    "speed": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "sprite_index": _BuiltinVariableMetadata("instance", "undefined", True, False, "sprite"),
    "view_angle": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_camera": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_current": _BuiltinVariableMetadata("global", "undefined", False, True, "view"),
    "view_enabled": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_hborder": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_hport": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_hspeed": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_hview": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_object": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_surface_id": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_vborder": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_visible": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_vspeed": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_wport": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_wview": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_xport": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_xview": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_yport": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "view_yview": _BuiltinVariableMetadata("global", "undefined", True, True, "view"),
    "visible": _BuiltinVariableMetadata("instance", "true", True, False, "rendering"),
    "vspeed": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "x": _BuiltinVariableMetadata("instance", "0", True, False, "transform"),
    "xprevious": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "xstart": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "y": _BuiltinVariableMetadata("instance", "0", True, False, "transform"),
    "yprevious": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
    "ystart": _BuiltinVariableMetadata("instance", "0", True, False, "motion"),
}

_BUILTIN_GLOBAL_VARIABLES = frozenset(
    name for name, metadata in _BUILTIN_VARIABLE_REGISTRY.items()
    if metadata.scope == "global" and not metadata.is_array
)
_BUILTIN_ARRAY_VARIABLES = frozenset(
    name for name, metadata in _BUILTIN_VARIABLE_REGISTRY.items()
    if metadata.is_array
)
_READ_ONLY_BUILTIN_VARIABLES = frozenset(
    name for name, metadata in _BUILTIN_VARIABLE_REGISTRY.items()
    if not metadata.mutable
)
_BUILTIN_INSTANCE_VARIABLES = frozenset(_BUILTIN_VARIABLE_REGISTRY)

_VIRTUAL_KEY_ACTIONS = {
    "vk_left": "ui_left",
    "vk_right": "ui_right",
    "vk_up": "ui_up",
    "vk_down": "ui_down",
}

_VIRTUAL_KEY_CONSTANTS = {
    "vk_shift": "KEY_SHIFT",
}

_RUNTIME_FUNCTIONS = {
    "int64": "gml_int64",
    "is_array": "is_array",
    "is_bool": "is_bool",
    "is_callable": "is_callable",
    "is_handle": "is_handle",
    "is_infinity": "is_infinity",
    "is_int32": "is_int32",
    "is_int64": "is_int64",
    "is_method": "is_method",
    "is_nan": "is_nan_value",
    "is_numeric": "is_numeric",
    "is_ptr": "is_ptr",
    "is_real": "is_real",
    "is_string": "is_string",
    "is_struct": "is_struct",
    "is_undefined": "is_undefined",
    "handle_parse": "gml_handle_parse",
    "method_get_index": "gml_method_get_index",
    "method_get_self": "gml_method_get_self",
    "real": "gml_real",
    "ptr": "gml_ptr",
    "sqrt": "gml_sqrt",
    "typeof": "gml_typeof",
    "with_targets": "gml_with_targets",
    "string": "gml_string",
    "bool": "gml_bool",
}

_STRUCT_RUNTIME_FUNCTIONS = {
    "struct_exists": "gml_struct_exists",
    "struct_get": "gml_struct_get",
    "struct_get_names": "gml_struct_get_names",
    "struct_names_count": "gml_struct_names_count",
    "struct_set": "gml_struct_set",
    "struct_remove": "gml_struct_remove",
    "struct_foreach": "gml_struct_foreach",
    "static_get": "gml_static_get",
    "static_set": "gml_static_set",
    "is_instanceof": "gml_is_instanceof",
    "instanceof": "gml_instanceof",
    "variable_get_hash": "gml_variable_get_hash",
    "struct_get_from_hash": "gml_struct_get_from_hash",
    "struct_set_from_hash": "gml_struct_set_from_hash",
    "struct_exists_from_hash": "gml_struct_exists_from_hash",
    "struct_remove_from_hash": "gml_struct_remove_from_hash",
}

_VARIABLE_RUNTIME_FUNCTIONS = {
    "method_call": "gml_method_call",
    "method": "gml_method",
    "ref_create": "gml_ref_create",
    "variable_clone": "gml_variable_clone",
    "variable_instance_exists": "gml_variable_instance_exists",
    "variable_instance_get": "gml_variable_instance_get",
    "variable_instance_set": "gml_variable_instance_set",
    "variable_instance_get_names": "gml_variable_instance_get_names",
    "variable_instance_names_count": "gml_variable_instance_names_count",
    "variable_global_exists": "gml_variable_global_exists",
    "variable_global_get": "gml_variable_global_get",
    "variable_global_set": "gml_variable_global_set",
    "variable_struct_get": "gml_variable_struct_get",
}

_DS_MAP_RUNTIME_FUNCTIONS = {
    "ds_map_exists": "gml_ds_map_exists",
    "ds_map_find_value": "gml_ds_map_find_value",
}

_ARRAY_RUNTIME_FUNCTIONS = {
    "array_equals": "gml_array_equals",
    "array_push": "gml_array_push",
}

_ASSET_RUNTIME_FUNCTIONS = {
    "asset_get_index": "gml_asset_get_index",
    "asset_get_type": "gml_asset_get_type",
    "asset_get_ids": "gml_asset_get_ids",
    "asset_get_type_name": "gml_asset_get_type_name",
    "asset_get_index_from_id": "gml_asset_get_index_from_id",
    "asset_has_any_tag": "gml_asset_has_any_tag",
}

_INSTANCE_RUNTIME_FUNCTIONS = {
    "instance_create_layer": "gml_instance_create_layer",
    "instance_create_depth": "gml_instance_create_depth",
    "instance_destroy": "gml_instance_destroy",
    "instance_exists": "gml_instance_exists",
    "instance_find": "gml_instance_find",
    "instance_number": "gml_instance_number",
    "instance_nearest": "gml_instance_nearest",
    "instance_furthest": "gml_instance_furthest",
    "instance_id_get": "gml_instance_id_get",
}

_COLLISION_RUNTIME_FUNCTIONS = {
    "place_meeting": "gml_place_meeting",
    "position_meeting": "gml_position_meeting",
    "instance_place": "gml_instance_place",
    "instance_position": "gml_instance_position",
    "collision_point": "gml_collision_point",
    "collision_rectangle": "gml_collision_rectangle",
    "collision_line": "gml_collision_line",
    "collision_circle": "gml_collision_circle",
}

_MOTION_RUNTIME_FUNCTIONS = {
    "motion_set": "gml_motion_set",
    "motion_add": "gml_motion_add",
    "move_towards_point": "gml_move_towards_point",
    "move_contact_solid": "gml_move_contact_solid",
    "move_contact_all": "gml_move_contact_all",
    "move_bounce_solid": "gml_move_bounce_solid",
    "move_bounce_all": "gml_move_bounce_all",
    "move_random": "gml_move_random",
    "move_snap": "gml_move_snap",
    "place_snapped": "gml_place_snapped",
}

_PATH_RUNTIME_FUNCTIONS = {
    "path_start": "gml_path_start",
    "path_end": "gml_path_end",
    "path_get_length": "gml_path_get_length",
}

_MP_GRID_RUNTIME_FUNCTIONS = {
    "mp_grid_create": "gml_mp_grid_create",
    "mp_grid_destroy": "gml_mp_grid_destroy",
    "mp_grid_clear_all": "gml_mp_grid_clear_all",
    "mp_grid_add_cell": "gml_mp_grid_add_cell",
    "mp_grid_clear_cell": "gml_mp_grid_clear_cell",
    "mp_grid_add_rectangle": "gml_mp_grid_add_rectangle",
    "mp_grid_path": "gml_mp_grid_path",
}

_DRAW_RUNTIME_FUNCTIONS = {
    "draw_self": "gml_draw_self",
    "draw_sprite": "gml_draw_sprite",
    "draw_sprite_ext": "gml_draw_sprite_ext",
    "draw_sprite_part": "gml_draw_sprite_part",
    "draw_sprite_part_ext": "gml_draw_sprite_part_ext",
    "draw_sprite_general": "gml_draw_sprite_general",
    "draw_sprite_pos": "gml_draw_sprite_pos",
    "draw_sprite_tiled": "gml_draw_sprite_tiled",
    "draw_sprite_tiled_ext": "gml_draw_sprite_tiled_ext",
    "draw_tile": "gml_draw_tile",
    "draw_tilemap": "gml_draw_tilemap",
    "draw_set_color": "gml_draw_set_color",
    "draw_get_color": "gml_draw_get_color",
    "draw_set_alpha": "gml_draw_set_alpha",
    "draw_get_alpha": "gml_draw_get_alpha",
    "draw_set_line_width": "gml_draw_set_line_width",
    "draw_get_line_width": "gml_draw_get_line_width",
    "draw_clear": "gml_draw_clear",
    "draw_line": "gml_draw_line",
    "draw_rectangle": "gml_draw_rectangle",
    "draw_circle": "gml_draw_circle",
    "draw_triangle": "gml_draw_triangle",
    "draw_point": "gml_draw_point",
    "surface_create": "gml_surface_create",
    "surface_exists": "gml_surface_exists",
    "surface_free": "gml_surface_free",
    "surface_set_target": "gml_surface_set_target",
    "surface_reset_target": "gml_surface_reset_target",
    "surface_get_width": "gml_surface_get_width",
    "surface_get_height": "gml_surface_get_height",
    "draw_surface": "gml_draw_surface",
    "draw_surface_ext": "gml_draw_surface_ext",
    "surface_copy": "gml_surface_copy",
    "surface_save": "gml_surface_save",
    "application_surface_enable": "gml_application_surface_enable",
    "application_surface_is_enabled": "gml_application_surface_is_enabled",
    "application_surface_draw_enable": "gml_application_surface_draw_enable",
    "application_surface_is_draw_enabled": "gml_application_surface_is_draw_enabled",
    "application_get_position": "gml_application_get_position",
    "camera_create_view": "gml_camera_create_view",
    "camera_set_view_pos": "gml_camera_set_view_pos",
    "camera_set_view_size": "gml_camera_set_view_size",
    "camera_get_view_x": "gml_camera_get_view_x",
    "camera_get_view_y": "gml_camera_get_view_y",
    "camera_get_view_width": "gml_camera_get_view_width",
    "camera_get_view_height": "gml_camera_get_view_height",
    "camera_set_view_angle": "gml_camera_set_view_angle",
    "camera_get_view_angle": "gml_camera_get_view_angle",
    "display_get_gui_width": "gml_display_get_gui_width",
    "display_get_gui_height": "gml_display_get_gui_height",
    "display_set_gui_size": "gml_display_set_gui_size",
    "draw_text": "gml_draw_text",
    "draw_text_ext": "gml_draw_text_ext",
    "draw_text_transformed": "gml_draw_text_transformed",
    "draw_set_font": "gml_draw_set_font",
    "draw_get_font": "gml_draw_get_font",
    "draw_set_halign": "gml_draw_set_halign",
    "draw_get_halign": "gml_draw_get_halign",
    "draw_set_valign": "gml_draw_set_valign",
    "draw_get_valign": "gml_draw_get_valign",
    "string_width": "gml_string_width",
    "string_height": "gml_string_height",
    "string_width_ext": "gml_string_width_ext",
    "string_height_ext": "gml_string_height_ext",
}
