# pyright: reportPrivateUsage=false
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .constants import (
    _ARRAY_RUNTIME_FUNCTIONS,
    _ASSET_RUNTIME_FUNCTIONS,
    _ASYNC_RUNTIME_FUNCTIONS,
    _AUDIO_RUNTIME_FUNCTIONS,
    _BUFFER_RUNTIME_FUNCTIONS,
    _COLLISION_RUNTIME_FUNCTIONS,
    _DRAW_RUNTIME_FUNCTIONS,
    _DS_COLLECTIONS_FUNCTIONS,
    _DS_GRID_FUNCTIONS,
    _DS_MAP_RUNTIME_FUNCTIONS,
    _FILE_RUNTIME_FUNCTIONS,
    _INPUT_RUNTIME_FUNCTIONS,
    _INSTANCE_RUNTIME_FUNCTIONS,
    _MATH_RUNTIME_FUNCTIONS,
    _MOTION_RUNTIME_FUNCTIONS,
    _MP_GRID_RUNTIME_FUNCTIONS,
    _NETWORK_RUNTIME_FUNCTIONS,
    _PATH_RUNTIME_FUNCTIONS,
    _PHYSICS_RUNTIME_FUNCTIONS,
    _ROOM_RUNTIME_FUNCTIONS,
    _RUNTIME_FUNCTIONS,
    _STRING_RUNTIME_FUNCTIONS,
    _STRUCT_RUNTIME_FUNCTIONS,
    _TIME_RUNTIME_FUNCTIONS,
    _VARIABLE_RUNTIME_FUNCTIONS,
)
from .gml_api_manifest import get_gml_api_entry

GMLFunctionLoweringKind: TypeAlias = Literal[
    "keyboard_check",
    "method",
    "print",
    "runtime",
    "runtime_audio_api",
    "runtime_append_self",
    "runtime_collision_api",
    "runtime_draw_api",
    "runtime_instance_api",
    "runtime_instance_keyword_first_arg",
    "runtime_motion_api",
    "runtime_path_api",
    "runtime_path_asset_api",
    "runtime_room_api",
    "runtime_self_default",
    "runtime_time_api",
    "runtime_variadic_1",
    "with_targets",
]


@dataclass(frozen=True)
class GMLFunctionDescriptor:
    name: str
    category: str
    min_args: int
    max_args: int | None
    lowering_kind: GMLFunctionLoweringKind
    lowering_target: str
    issue_number: int
    docs_url: str

    @property
    def issue_url(self) -> str:
        return f"https://github.com/Infiland/GM2Godot/issues/{self.issue_number}"

    def arity_description(self) -> str:
        if self.max_args is None:
            return f"at least {self.min_args}"
        if self.min_args == self.max_args:
            return str(self.min_args)
        return f"{self.min_args} to {self.max_args}"


_DEFAULT_CATEGORY = "Runtime Function Dispatch"
_DEFAULT_ISSUE_NUMBER = 483
_DEFAULT_DOCS_URL = (
    "https://manual.gamemaker.io/monthly/en/"
    "GameMaker_Language/GML_Reference/GML_Reference.htm"
)

_STRUCT_ARITY: dict[str, tuple[int, int | None]] = {
    "struct_exists": (2, 2),
    "struct_get": (2, 2),
    "struct_get_names": (1, 1),
    "struct_names_count": (1, 1),
    "struct_set": (3, 3),
    "struct_remove": (2, 2),
    "struct_foreach": (2, 2),
    "static_get": (1, 1),
    "static_set": (2, 2),
    "is_instanceof": (2, 2),
    "instanceof": (1, 1),
    "variable_get_hash": (1, 1),
    "struct_get_from_hash": (2, 2),
    "struct_set_from_hash": (3, 3),
    "struct_exists_from_hash": (2, 2),
    "struct_remove_from_hash": (2, 2),
}

_VARIABLE_ARITY: dict[str, tuple[int, int | None]] = {
    "method_call": (1, 4),
    "method": (2, 2),
    "script_execute": (1, None),
    "script_exists": (1, 1),
    "script_get_name": (1, 1),
    "script_get_callable": (1, 1),
    "global_function": (1, 1),
    "argument_count": (0, 0),
    "ref_create": (2, 3),
    "variable_clone": (1, 2),
    "variable_instance_exists": (2, 2),
    "variable_instance_get": (2, 2),
    "variable_instance_set": (3, 3),
    "variable_instance_get_names": (1, 1),
    "variable_instance_names_count": (1, 1),
    "variable_global_exists": (1, 1),
    "variable_global_get": (1, 1),
    "variable_global_set": (2, 2),
    "variable_struct_get": (2, 2),
}

_DS_MAP_ARITY: dict[str, tuple[int, int | None]] = {
    "ds_map_create": (0, 0),
    "ds_map_destroy": (1, 1),
    "ds_map_clear": (1, 1),
    "ds_map_empty": (1, 1),
    "ds_map_size": (1, 1),
    "ds_map_add": (3, 3),
    "ds_map_set": (3, 3),
    "ds_map_replace": (3, 3),
    "ds_map_delete": (2, 2),
    "ds_map_exists": (2, 2),
    "ds_map_find_value": (2, 2),
    "ds_map_find_first": (1, 1),
    "ds_map_find_last": (1, 1),
    "ds_map_find_next": (2, 2),
    "ds_map_find_previous": (2, 2),
    "ds_map_keys": (1, 1),
    "ds_map_values": (1, 1),
    "ds_map_copy": (2, 2),
    "ds_map_merge": (2, 2),
    "ds_map_read": (2, 2),
    "ds_map_write": (1, 1),
    "ds_map_add_list": (3, 3),
    "ds_map_add_map": (3, 3),
    "ds_map_replace_list": (3, 3),
    "ds_map_replace_map": (3, 3),
    "ds_map_is_list": (2, 2),
    "ds_map_is_map": (2, 2),
}

_DS_GRID_ARITY: dict[str, tuple[int, int | None]] = {
    "ds_grid_create": (2, 2),
    "ds_grid_destroy": (1, 1),
    "ds_grid_width": (1, 1),
    "ds_grid_height": (1, 1),
    "ds_grid_clear": (1, 2),
    "ds_grid_resize": (3, 4),
    "ds_grid_set": (4, 4),
    "ds_grid_get": (3, 3),
    "ds_grid_add": (4, 4),
    "ds_grid_multiply": (4, 4),
    "ds_grid_set_region": (6, 6),
    "ds_grid_get_region": (5, 5),
    "ds_grid_clear_region": (5, 6),
    "ds_grid_add_region": (6, 6),
    "ds_grid_multiply_region": (6, 6),
    "ds_grid_value_exists": (6, 6),
    "ds_grid_value_x": (6, 6),
    "ds_grid_value_y": (6, 6),
    "ds_grid_copy": (2, 2),
    "ds_grid_read": (2, 2),
    "ds_grid_write": (1, 1),
}

_ARRAY_ARITY: dict[str, tuple[int, int | None]] = {
    "array_equals": (2, 2),
    "array_push": (2, None),
    "array_push_back": (2, 2),
    "array_create": (1, 2),
    "array_length_1d": (1, 1),
    "array_resize": (2, 2),
    "array_pop": (1, 1),
    "array_insert": (3, 3),
    "array_delete": (2, 2),
    "array_sort": (1, 1),
    "array_shuffle": (1, 1),
    "array_copy": (5, 5),
    "array_concat": (2, 2),
    "array_contains": (2, 2),
    "array_find_index": (2, 2),
    "array_filter": (2, 2),
    "array_map": (2, 2),
    "array_reduce": (2, 3),
}

_STRING_ARITY: dict[str, tuple[int, int | None]] = {
    "string_length": (1, 1),
    "string_char_at": (2, 2),
    "string_ord_at": (2, 2),
    "string_copy": (3, 3),
    "string_pos": (2, 2),
    "string_replace": (3, 3),
    "string_replace_all": (3, 3),
    "string_delete": (3, 3),
    "string_insert": (3, 3),
    "string_lower": (1, 1),
    "string_upper": (1, 1),
    "string_trim": (1, 1),
    "string_repeat": (2, 2),
    "string_digits": (1, 1),
    "string_letters": (1, 1),
    "string_lettersdigits": (1, 1),
    "string_split": (2, 2),
    "string_join": (2, 2),
    "chr": (1, 1),
    "ord": (1, 1),
    "ansi_char": (1, 1),
}

_MATH_ARITY: dict[str, tuple[int, int | None]] = {
    "abs": (1, 1),
    "sign": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "frac": (1, 1),
    "sqr": (1, 1),
    "power": (2, 2),
    "exp": (1, 1),
    "ln": (1, 1),
    "log2": (1, 1),
    "log10": (1, 1),
    "clamp": (3, 3),
    "lerp": (3, 3),
    "min": (1, None),
    "max": (1, None),
    "sin": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "arcsin": (1, 1),
    "arccos": (1, 1),
    "arctan": (1, 1),
    "arctan2": (2, 2),
    "dsin": (1, 1),
    "dcos": (1, 1),
    "dtan": (1, 1),
    "darcsin": (1, 1),
    "darccos": (1, 1),
    "darctan": (1, 1),
    "darctan2": (2, 2),
    "degtorad": (1, 1),
    "radtodeg": (1, 1),
    "point_distance": (4, 4),
    "point_direction": (4, 4),
    "lengthdir_x": (2, 2),
    "lengthdir_y": (2, 2),
    "angle_difference": (2, 2),
    "dot_product": (4, 4),
    "dot_product_3d": (6, 6),
    "dot_product_normalised": (4, 4),
    "dot_product_3d_normalised": (6, 6),
    "random": (1, 1),
    "irandom": (1, 1),
    "random_range": (2, 2),
    "irandom_range": (2, 2),
    "choose": (1, None),
    "randomize": (0, 0),
    "randomise": (0, 0),
    "random_set_seed": (1, 1),
    "random_get_seed": (0, 0),
}

_FILE_ARITY: dict[str, tuple[int, int | None]] = {
    "file_exists": (1, 1),
    "file_delete": (1, 1),
    "directory_exists": (1, 1),
    "directory_create": (1, 1),
    "directory_destroy": (1, 1),
    "file_text_open_read": (1, 1),
    "file_text_open_write": (1, 1),
    "file_text_open_append": (1, 1),
    "file_text_close": (1, 1),
    "file_text_eof": (1, 1),
    "file_text_read_string": (1, 1),
    "file_text_readln": (1, 1),
    "file_text_read_real": (1, 1),
    "file_text_write_string": (2, 2),
    "file_text_write_real": (2, 2),
    "file_text_writeln": (1, 1),
    "filename_name": (1, 1),
    "filename_ext": (1, 1),
    "filename_dir": (1, 1),
    "filename_path": (1, 1),
    "filename_change_ext": (2, 2),
    "ini_open": (1, 1),
    "ini_close": (0, 0),
    "ini_read_string": (3, 3),
    "ini_read_real": (3, 3),
    "ini_write_string": (3, 3),
    "ini_write_real": (3, 3),
    "ini_section_exists": (1, 1),
    "ini_key_exists": (2, 2),
    "ini_key_delete": (2, 2),
    "ini_section_delete": (1, 1),
    "json_encode": (1, 1),
    "json_decode": (1, 1),
    "json_stringify": (1, 1),
    "json_parse": (1, 1),
}

_BUFFER_ARITY: dict[str, tuple[int, int | None]] = {
    "buffer_create": (3, 3),
    "buffer_delete": (1, 1),
    "buffer_exists": (1, 1),
    "buffer_tell": (1, 1),
    "buffer_seek": (3, 3),
    "buffer_get_size": (1, 1),
    "buffer_get_used_size": (1, 1),
    "buffer_resize": (2, 2),
    "buffer_write": (3, 3),
    "buffer_read": (2, 2),
    "buffer_peek": (3, 3),
    "buffer_poke": (4, 4),
    "buffer_fill": (5, 5),
    "buffer_copy": (5, 5),
    "buffer_save": (2, 2),
    "buffer_load": (1, 1),
    "buffer_save_async": (2, 4),
    "buffer_load_async": (1, 1),
    "buffer_base64_encode": (3, 3),
    "buffer_base64_decode": (1, 1),
    "buffer_md5": (3, 3),
    "buffer_sha1": (3, 3),
    "buffer_sha256": (3, 3),
    "buffer_crc32": (3, 3),
}

_ASYNC_ARITY: dict[str, tuple[int, int | None]] = {
    "http_get": (1, 1),
    "http_post_string": (2, 2),
    "http_request": (4, 4),
}

_NETWORK_ARITY: dict[str, tuple[int, int | None]] = {
    "network_create_socket": (1, 1),
    "network_create_socket_ext": (2, 2),
    "network_create_server": (2, 3),
    "network_create_server_raw": (2, 3),
    "network_connect": (3, 3),
    "network_connect_async": (3, 3),
    "network_connect_raw": (3, 3),
    "network_connect_raw_async": (3, 3),
    "network_send_raw": (3, 3),
    "network_send_packet": (3, 3),
    "network_send_udp": (5, 5),
    "network_send_udp_raw": (5, 5),
    "network_destroy": (1, 1),
}

_PHYSICS_ARITY: dict[str, tuple[int, int | None]] = {
    "physics_world_create": (0, 1),
    "physics_world_gravity": (2, 2),
    "physics_world_gravity_get": (0, 0),
    "physics_world_update_speed": (1, 1),
    "physics_pause_enable": (1, 1),
    "physics_fixture_create": (0, 0),
    "physics_fixture_delete": (1, 1),
    "physics_fixture_set_box_shape": (3, 3),
    "physics_fixture_set_circle_shape": (2, 2),
    "physics_fixture_set_density": (2, 2),
    "physics_fixture_set_friction": (2, 2),
    "physics_fixture_set_restitution": (2, 2),
    "physics_fixture_set_sensor": (2, 2),
    "physics_fixture_bind": (2, 2),
    "physics_apply_force": (4, 4),
    "physics_apply_impulse": (4, 4),
    "physics_apply_local_force": (4, 4),
    "physics_apply_local_impulse": (4, 4),
    "physics_apply_angular_impulse": (1, 1),
    "physics_apply_torque": (1, 1),
}

_ASSET_ARITY: dict[str, tuple[int, int | None]] = {
    "asset_get_index": (1, 1),
    "asset_get_type": (1, 1),
    "asset_get_ids": (0, 1),
    "asset_get_type_name": (1, 1),
    "asset_get_index_from_id": (1, 1),
    "asset_has_any_tag": (2, 2),
}

_INSTANCE_ARITY: dict[str, tuple[int, int | None]] = {
    "instance_create_layer": (4, 4),
    "instance_create_depth": (4, 4),
    "instance_destroy": (0, 1),
    "instance_exists": (1, 1),
    "instance_find": (2, 2),
    "instance_number": (1, 1),
    "instance_nearest": (3, 3),
    "instance_furthest": (3, 3),
    "instance_id_get": (1, 1),
}

_COLLISION_ARITY: dict[str, tuple[int, int | None]] = {
    "place_meeting": (3, 3),
    "position_meeting": (3, 3),
    "instance_place": (3, 3),
    "instance_position": (3, 3),
    "collision_point": (3, 5),
    "collision_rectangle": (5, 7),
    "collision_line": (5, 7),
    "collision_circle": (4, 6),
}

_MOTION_ARITY: dict[str, tuple[int, int | None]] = {
    "motion_set": (2, 2),
    "motion_add": (2, 2),
    "move_towards_point": (3, 3),
    "move_contact_solid": (2, 2),
    "move_contact_all": (2, 2),
    "move_bounce_solid": (1, 1),
    "move_bounce_all": (1, 1),
    "move_random": (2, 2),
    "move_snap": (2, 2),
    "place_snapped": (2, 2),
}

_PATH_ARITY: dict[str, tuple[int, int | None]] = {
    "path_start": (4, 4),
    "path_end": (0, 0),
    "path_get_length": (1, 1),
}

_MP_GRID_ARITY: dict[str, tuple[int, int | None]] = {
    "mp_grid_create": (6, 6),
    "mp_grid_destroy": (1, 1),
    "mp_grid_clear_all": (1, 1),
    "mp_grid_add_cell": (3, 3),
    "mp_grid_clear_cell": (3, 3),
    "mp_grid_add_rectangle": (5, 5),
    "mp_grid_path": (7, 7),
}

_INPUT_ARITY: dict[str, tuple[int, int | None]] = {
    "keyboard_check": (1, 1),
    "keyboard_check_pressed": (1, 1),
    "keyboard_check_released": (1, 1),
    "keyboard_clear": (1, 1),
    "keyboard_key_press": (1, 1),
    "keyboard_key_release": (1, 1),
    "mouse_check_button": (1, 1),
    "mouse_check_button_pressed": (1, 1),
    "mouse_check_button_released": (1, 1),
    "display_mouse_get_x": (0, 0),
    "display_mouse_get_y": (0, 0),
    "device_mouse_x_to_gui": (1, 1),
    "device_mouse_y_to_gui": (1, 1),
    "gamepad_is_connected": (1, 1),
    "gamepad_button_check": (2, 2),
    "gamepad_button_check_pressed": (2, 2),
    "gamepad_button_check_released": (2, 2),
    "gamepad_axis_value": (2, 2),
    "gamepad_set_axis_deadzone": (2, 2),
    "gamepad_get_axis_deadzone": (1, 1),
    "gamepad_set_vibration": (3, 3),
}

_AUDIO_ARITY: dict[str, tuple[int, int | None]] = {
    "audio_play_sound": (3, 7),
    "audio_stop_sound": (1, 1),
    "audio_pause_sound": (1, 1),
    "audio_resume_sound": (1, 1),
    "audio_is_playing": (1, 1),
    "audio_sound_gain": (2, 3),
    "audio_sound_pitch": (2, 2),
    "sound_play": (1, 1),
    "sound_loop": (1, 1),
    "sound_stop": (1, 1),
    "sound_pause": (1, 1),
    "sound_resume": (1, 1),
    "sound_isplaying": (1, 1),
    "sound_volume": (2, 2),
    "sound_pitch": (2, 2),
    "sound_global_volume": (1, 1),
}

_DS_COLLECTIONS_ARITY: dict[str, tuple[int, int | None]] = {
    "ds_list_create": (0, 0),
    "ds_list_destroy": (1, 1),
    "ds_list_clear": (1, 1),
    "ds_list_empty": (1, 1),
    "ds_list_size": (1, 1),
    "ds_list_add": (2, None),
    "ds_list_set": (3, 3),
    "ds_list_delete": (2, 2),
    "ds_list_find_index": (2, 2),
    "ds_list_find_value": (2, 2),
    "ds_list_insert": (3, 3),
    "ds_list_replace": (3, 3),
    "ds_list_shuffle": (1, 1),
    "ds_list_sort": (2, 2),
    "ds_list_copy": (2, 2),
    "ds_list_read": (2, 2),
    "ds_list_write": (1, 1),
    "ds_list_mark_as_list": (2, 2),
    "ds_list_mark_as_map": (2, 2),
    "ds_list_is_list": (2, 2),
    "ds_list_is_map": (2, 2),

    "ds_stack_create": (0, 0),
    "ds_stack_destroy": (1, 1),
    "ds_stack_clear": (1, 1),
    "ds_stack_empty": (1, 1),
    "ds_stack_size": (1, 1),
    "ds_stack_push": (2, None),
    "ds_stack_pop": (1, 1),
    "ds_stack_top": (1, 1),
    "ds_stack_copy": (2, 2),
    "ds_stack_read": (2, 2),
    "ds_stack_write": (1, 1),

    "ds_queue_create": (0, 0),
    "ds_queue_destroy": (1, 1),
    "ds_queue_clear": (1, 1),
    "ds_queue_empty": (1, 1),
    "ds_queue_size": (1, 1),
    "ds_queue_enqueue": (2, None),
    "ds_queue_dequeue": (1, 1),
    "ds_queue_head": (1, 1),
    "ds_queue_tail": (1, 1),
    "ds_queue_copy": (2, 2),
    "ds_queue_read": (2, 2),
    "ds_queue_write": (1, 1),

    "ds_priority_create": (0, 0),
    "ds_priority_destroy": (1, 1),
    "ds_priority_clear": (1, 1),
    "ds_priority_empty": (1, 1),
    "ds_priority_size": (1, 1),
    "ds_priority_add": (3, 3),
    "ds_priority_change_priority": (3, 3),
    "ds_priority_delete_max": (1, 1),
    "ds_priority_delete_min": (1, 1),
    "ds_priority_delete_value": (2, 2),
    "ds_priority_find_max": (1, 1),
    "ds_priority_find_min": (1, 1),
    "ds_priority_find_priority": (2, 2),
    "ds_priority_copy": (2, 2),
    "ds_priority_read": (2, 2),
    "ds_priority_write": (1, 1),
}

_TIME_ARITY: dict[str, tuple[int, int | None]] = {
    "alarm_get": (1, 1),
    "alarm_set": (2, 2),
    "time_source_create": (4, 7),
    "time_source_start": (1, 1),
    "time_source_stop": (1, 1),
    "time_source_pause": (1, 1),
    "time_source_resume": (1, 1),
    "time_source_destroy": (1, 1),
    "time_source_get_state": (1, 1),
    "time_source_get_period": (1, 1),
    "time_source_get_reps_completed": (1, 1),
    "time_source_get_reps_remaining": (1, 1),
    "time_source_get_time_remaining": (1, 1),
    "call_later": (3, 4),
    "call_cancel": (1, 1),
}

_ROOM_ARITY: dict[str, tuple[int, int | None]] = {
    "room_goto": (1, 1),
    "room_goto_next": (0, 0),
    "room_goto_previous": (0, 0),
    "room_restart": (0, 0),
    "game_restart": (0, 0),
    "game_end": (0, 0),
    "room_exists": (1, 1),
    "room_get_name": (1, 1),
    "room_get_info": (1, 1),
}

_DRAW_ARITY: dict[str, tuple[int, int | None]] = {
    "draw_self": (0, 0),
    "draw_sprite": (4, 4),
    "draw_sprite_ext": (9, 9),
    "draw_sprite_part": (8, 8),
    "draw_sprite_part_ext": (12, 12),
    "draw_sprite_general": (16, 16),
    "draw_sprite_pos": (11, 11),
    "draw_sprite_tiled": (4, 4),
    "draw_sprite_tiled_ext": (8, 8),
    "draw_tile": (5, 5),
    "draw_tilemap": (3, 3),
    "draw_set_color": (1, 1),
    "draw_get_color": (0, 0),
    "draw_set_alpha": (1, 1),
    "draw_get_alpha": (0, 0),
    "draw_set_line_width": (1, 1),
    "draw_get_line_width": (0, 0),
    "gpu_set_blendmode": (1, 1),
    "gpu_get_blendmode": (0, 0),
    "draw_set_blend_mode": (1, 1),
    "draw_get_blend_mode": (0, 0),
    "gpu_set_texfilter": (1, 1),
    "gpu_get_texfilter": (0, 0),
    "texture_set_interpolation": (1, 1),
    "texture_get_interpolation": (0, 0),
    "gpu_set_texrepeat": (1, 1),
    "gpu_get_texrepeat": (0, 0),
    "texture_set_repeat": (1, 1),
    "texture_get_repeat": (0, 0),
    "gpu_set_colorwriteenable": (4, 4),
    "gpu_get_colorwriteenable": (0, 0),
    "gpu_set_cullmode": (1, 1),
    "gpu_get_cullmode": (0, 0),
    "gpu_set_alphatestenable": (1, 1),
    "gpu_get_alphatestenable": (0, 0),
    "gpu_set_alphatestref": (1, 1),
    "gpu_get_alphatestref": (0, 0),
    "sprite_get_texture": (2, 2),
    "surface_get_texture": (1, 1),
    "texture_exists": (1, 1),
    "texture_get_width": (1, 1),
    "texture_get_height": (1, 1),
    "shader_set": (1, 1),
    "shader_reset": (0, 0),
    "shader_get_name": (1, 1),
    "shader_is_compiled": (1, 1),
    "shader_get_uniform": (2, 2),
    "shader_get_sampler_index": (2, 2),
    "shader_set_uniform_f": (2, 5),
    "shader_set_uniform_i": (2, 5),
    "shader_set_uniform_f_array": (2, 2),
    "shader_set_uniform_i_array": (2, 2),
    "texture_set_stage": (2, 2),
    "draw_clear": (1, 1),
    "draw_line": (4, 4),
    "draw_rectangle": (5, 5),
    "draw_circle": (4, 4),
    "draw_triangle": (7, 7),
    "draw_point": (2, 2),
    "surface_create": (2, 3),
    "surface_exists": (1, 1),
    "surface_free": (1, 1),
    "surface_set_target": (1, 2),
    "surface_reset_target": (0, 0),
    "surface_get_width": (1, 1),
    "surface_get_height": (1, 1),
    "draw_surface": (3, 3),
    "draw_surface_ext": (8, 8),
    "surface_copy": (4, 4),
    "surface_save": (2, 2),
    "application_surface_enable": (1, 1),
    "application_surface_is_enabled": (0, 0),
    "application_surface_draw_enable": (1, 1),
    "application_surface_is_draw_enabled": (0, 0),
    "application_get_position": (0, 0),
    "camera_create_view": (10, 10),
    "camera_set_view_pos": (3, 3),
    "camera_set_view_size": (3, 3),
    "camera_get_view_x": (1, 1),
    "camera_get_view_y": (1, 1),
    "camera_get_view_width": (1, 1),
    "camera_get_view_height": (1, 1),
    "camera_set_view_angle": (2, 2),
    "camera_get_view_angle": (1, 1),
    "display_get_gui_width": (0, 0),
    "display_get_gui_height": (0, 0),
    "display_set_gui_size": (2, 2),
    "draw_text": (3, 3),
    "draw_text_ext": (5, 5),
    "draw_text_transformed": (6, 6),
    "draw_set_font": (1, 1),
    "draw_get_font": (0, 0),
    "draw_set_halign": (1, 1),
    "draw_get_halign": (0, 0),
    "draw_set_valign": (1, 1),
    "draw_get_valign": (0, 0),
    "string_width": (1, 1),
    "string_height": (1, 1),
    "string_width_ext": (3, 3),
    "string_height_ext": (3, 3),
}


def get_gml_function_descriptor(name: str) -> GMLFunctionDescriptor | None:
    return _GML_FUNCTION_DESCRIPTORS.get(name)


def iter_gml_function_descriptors() -> tuple[GMLFunctionDescriptor, ...]:
    return tuple(_GML_FUNCTION_DESCRIPTORS.values())


def validate_gml_function_arity(
    descriptor: GMLFunctionDescriptor,
    arg_count: int,
) -> str | None:
    if arg_count < descriptor.min_args:
        return _arity_error(descriptor, arg_count)
    if descriptor.max_args is not None and arg_count > descriptor.max_args:
        return _arity_error(descriptor, arg_count)
    return None


def _arity_error(descriptor: GMLFunctionDescriptor, arg_count: int) -> str:
    return (
        f"GML API '{descriptor.name}' expects {descriptor.arity_description()} "
        f"argument(s), got {arg_count}; tracked by #{descriptor.issue_number}."
    )


def _descriptor(
    name: str,
    min_args: int,
    max_args: int | None,
    lowering_kind: GMLFunctionLoweringKind,
    lowering_target: str,
) -> GMLFunctionDescriptor:
    manifest_entry = get_gml_api_entry(name)
    return GMLFunctionDescriptor(
        name=name,
        category=manifest_entry.category if manifest_entry is not None else _DEFAULT_CATEGORY,
        min_args=min_args,
        max_args=max_args,
        lowering_kind=lowering_kind,
        lowering_target=lowering_target,
        issue_number=(
            manifest_entry.issue_number if manifest_entry is not None else _DEFAULT_ISSUE_NUMBER
        ),
        docs_url=manifest_entry.docs_url if manifest_entry is not None else _DEFAULT_DOCS_URL,
    )


def _build_function_descriptors() -> dict[str, GMLFunctionDescriptor]:
    descriptors: dict[str, GMLFunctionDescriptor] = {}

    for name, target in _RUNTIME_FUNCTIONS.items():
        if name == "with_targets":
            continue
        descriptors[name] = _descriptor(name, 1, 1, "runtime", target)

    for name, target in _STRUCT_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _STRUCT_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _VARIABLE_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _VARIABLE_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name == "script_execute":
            lowering_kind = "runtime_variadic_1"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _DS_MAP_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _DS_MAP_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _ARRAY_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _ARRAY_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _STRING_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _STRING_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _MATH_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _MATH_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _FILE_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _FILE_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _BUFFER_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _BUFFER_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _ASYNC_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _ASYNC_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _NETWORK_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _NETWORK_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _PHYSICS_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _PHYSICS_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name in (
            "physics_apply_force",
            "physics_apply_impulse",
            "physics_apply_local_force",
            "physics_apply_local_impulse",
            "physics_apply_angular_impulse",
            "physics_apply_torque",
        ):
            lowering_kind = "runtime_append_self"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _ASSET_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _ASSET_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _INSTANCE_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _INSTANCE_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime_instance_api"
        if name in ("instance_create_layer", "instance_create_depth"):
            lowering_kind = "runtime_append_self"
        elif name == "instance_destroy":
            lowering_kind = "runtime_self_default"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _COLLISION_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _COLLISION_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_collision_api", target)

    for name, target in _MOTION_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _MOTION_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_motion_api", target)

    for name, target in _PATH_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _PATH_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name in ("path_start", "path_end"):
            lowering_kind = "runtime_path_api"
        elif name == "path_get_length":
            lowering_kind = "runtime_path_asset_api"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _MP_GRID_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _MP_GRID_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name == "mp_grid_path":
            lowering_kind = "runtime_path_asset_api"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _INPUT_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _INPUT_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _AUDIO_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _AUDIO_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_audio_api", target)

    for name, target in _ROOM_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _ROOM_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_room_api", target)

    for name, target in _DS_COLLECTIONS_FUNCTIONS.items():
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name in ("ds_list_add", "ds_stack_push", "ds_queue_enqueue"):
            lowering_kind = "runtime_variadic_1"
        min_args, max_args = _DS_COLLECTIONS_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _DS_GRID_FUNCTIONS.items():
        min_args, max_args = _DS_GRID_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _TIME_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _TIME_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name in ("alarm_get", "alarm_set"):
            lowering_kind = "runtime_time_api"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _DRAW_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _DRAW_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime_draw_api"
        if name == "draw_self":
            lowering_kind = "runtime_append_self"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    descriptors["method"] = _descriptor("method", 2, 2, "method", "gml_method")
    descriptors["with_targets"] = _descriptor(
        "with_targets",
        1,
        1,
        "with_targets",
        "gml_with_targets",
    )
    descriptors["show_debug_message"] = _descriptor(
        "show_debug_message",
        1,
        1,
        "print",
        "print",
    )

    for name in (
        "variable_instance_exists",
        "variable_instance_get",
        "variable_instance_set",
        "variable_instance_get_names",
        "variable_instance_names_count",
    ):
        current = descriptors[name]
        descriptors[name] = _descriptor(
            current.name,
            current.min_args,
            current.max_args,
            "runtime_instance_keyword_first_arg",
            current.lowering_target,
        )

    return descriptors


_GML_FUNCTION_DESCRIPTORS = _build_function_descriptors()
