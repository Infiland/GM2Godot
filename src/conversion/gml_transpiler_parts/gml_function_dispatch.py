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
    _FLEXPANEL_RUNTIME_FUNCTIONS,
    _INPUT_RUNTIME_FUNCTIONS,
    _INSTANCE_RUNTIME_FUNCTIONS,
    _LAYER_RUNTIME_FUNCTIONS,
    _MATH_RUNTIME_FUNCTIONS,
    _MOTION_RUNTIME_FUNCTIONS,
    _MP_GRID_RUNTIME_FUNCTIONS,
    _NETWORK_RUNTIME_FUNCTIONS,
    _OS_DEBUG_GC_RUNTIME_FUNCTIONS,
    _PLATFORM_SERVICE_RUNTIME_FUNCTIONS,
    _PATH_RUNTIME_FUNCTIONS,
    _PHYSICS_RUNTIME_FUNCTIONS,
    _ROOM_RUNTIME_FUNCTIONS,
    _RUNTIME_FUNCTIONS,
    _SEQUENCE_TIMELINE_RUNTIME_FUNCTIONS,
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
    "runtime_array_foreach",
    "runtime_array_sort",
    "runtime_audio_api",
    "runtime_append_self",
    "runtime_collision_api",
    "runtime_draw_api",
    "runtime_instance_api",
    "runtime_instance_keyword_first_arg",
    "runtime_layer_api",
    "runtime_motion_api",
    "runtime_path_api",
    "runtime_path_asset_api",
    "runtime_platform_service_api",
    "runtime_room_api",
    "runtime_sequence_api",
    "runtime_self_default",
    "runtime_time_api",
    "runtime_variadic_all",
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
    "variable_struct_exists": (2, 2),
    "variable_struct_get": (2, 2),
    "variable_struct_set": (3, 3),
    "variable_struct_remove": (2, 2),
    "variable_struct_get_names": (1, 1),
    "variable_struct_names_count": (1, 1),
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
    "ds_map_read": (2, 3),
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
    "ds_grid_read": (2, 3),
    "ds_grid_write": (1, 1),
}

_ARRAY_ARITY: dict[str, tuple[int, int | None]] = {
    "array_equals": (2, 2),
    "array_push": (2, None),
    "array_push_back": (2, 2),
    "array_create": (1, 2),
    "array_length_1d": (1, 1),
    "array_length": (1, 1),
    "array_resize": (2, 2),
    "array_pop": (1, 1),
    "array_insert": (3, 3),
    "array_delete": (3, 3),
    "array_sort": (2, 2),
    "array_shuffle": (1, 1),
    "array_copy": (5, 5),
    "array_concat": (2, 2),
    "array_contains": (2, 2),
    "array_find_index": (2, 2),
    "array_foreach": (2, 4),
    "array_filter": (2, 2),
    "array_map": (2, 2),
    "array_reduce": (2, 3),
}

_STRING_ARITY: dict[str, tuple[int, int | None]] = {
    "string_length": (1, 1),
    "string_byte_length": (1, 1),
    "string_char_at": (2, 2),
    "string_ord_at": (2, 2),
    "string_copy": (3, 3),
    "string_pos": (2, 2),
    "string_replace": (3, 3),
    "string_replace_all": (3, 3),
    "string_hash_to_newline": (1, 1),
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
    "matrix_build_lookat": (9, 9),
    "matrix_build_projection_ortho": (4, 4),
    "make_color_rgb": (3, 3),
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
    "file_bin_open": (2, 2),
    "file_bin_rewrite": (1, 1),
    "file_bin_close": (1, 1),
    "file_bin_size": (1, 1),
    "file_bin_position": (1, 1),
    "file_bin_seek": (2, 2),
    "file_bin_read_byte": (1, 1),
    "file_bin_write_byte": (2, 2),
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
    "buffer_sizeof": (1, 1),
    "buffer_write": (3, 3),
    "buffer_read": (2, 2),
    "buffer_peek": (3, 3),
    "buffer_poke": (4, 4),
    "buffer_fill": (5, 5),
    "buffer_copy": (5, 5),
    "buffer_save": (2, 2),
    "buffer_load": (1, 1),
    "buffer_save_ext": (4, 4),
    "buffer_load_ext": (3, 3),
    "buffer_save_async": (2, 4),
    "buffer_load_async": (1, 1),
    "buffer_compress": (3, 3),
    "buffer_decompress": (1, 1),
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
    "network_send_broadcast": (4, 4),
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
    "physics_fixture_set_linear_damping": (2, 2),
    "physics_fixture_set_angular_damping": (2, 2),
    "physics_fixture_set_sensor": (2, 2),
    "physics_fixture_bind": (2, 2),
    "physics_apply_force": (4, 4),
    "physics_apply_impulse": (4, 4),
    "physics_apply_local_force": (4, 4),
    "physics_apply_local_impulse": (4, 4),
    "physics_apply_angular_impulse": (1, 1),
    "physics_apply_torque": (1, 1),
    "physics_joint_distance_create": (7, 7),
    "physics_joint_revolute_create": (11, 11),
    "physics_joint_delete": (1, 1),
    "physics_joint_get_value": (2, 2),
    "physics_joint_set_value": (3, 3),
    "physics_joint_enable_motor": (2, 2),
    "physics_mass_properties": (4, 4),
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
    "distance_to_object": (1, 1),
    "place_meeting": (3, 3),
    "position_meeting": (3, 3),
    "instance_place": (3, 3),
    "instance_position": (3, 3),
    "collision_point": (3, 5),
    "collision_rectangle": (5, 7),
    "collision_line": (5, 7),
    "collision_circle": (4, 6),
    "collision_point_list": (7, 7),
    "collision_rectangle_list": (9, 9),
    "collision_line_list": (9, 9),
    "collision_circle_list": (8, 8),
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
    "display_mouse_set": (2, 2),
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
    "gamepad_set_color": (2, 2),
}

_AUDIO_ARITY: dict[str, tuple[int, int | None]] = {
    "audio_play_sound": (3, 7),
    "audio_play_sound_at": (9, 13),
    "audio_play_sound_on": (4, 8),
    "audio_stop_sound": (1, 1),
    "audio_stop_all": (0, 0),
    "audio_pause_sound": (1, 1),
    "audio_pause_all": (0, 0),
    "audio_resume_sound": (1, 1),
    "audio_resume_all": (0, 0),
    "audio_is_playing": (1, 1),
    "audio_is_paused": (1, 1),
    "audio_sound_gain": (2, 3),
    "audio_sound_get_gain": (1, 1),
    "audio_sound_pitch": (2, 2),
    "audio_sound_get_pitch": (1, 1),
    "audio_sound_loop": (2, 2),
    "audio_sound_get_loop": (1, 1),
    "audio_sound_set_listener_mask": (2, 2),
    "audio_sound_get_listener_mask": (1, 1),
    "audio_sound_get_asset": (1, 1),
    "audio_channel_num": (1, 1),
    "audio_master_gain": (1, 1),
    "audio_set_master_gain": (1, 1),
    "audio_get_master_gain": (0, 0),
    "audio_throw_on_error": (1, 1),
    "audio_emitter_create": (0, 0),
    "audio_emitter_exists": (1, 1),
    "audio_emitter_free": (1, 1),
    "audio_emitter_position": (4, 4),
    "audio_emitter_velocity": (4, 4),
    "audio_emitter_falloff": (4, 4),
    "audio_emitter_gain": (2, 2),
    "audio_emitter_get_gain": (1, 1),
    "audio_emitter_pitch": (2, 2),
    "audio_emitter_get_pitch": (1, 1),
    "audio_emitter_set_listener_mask": (2, 2),
    "audio_emitter_get_listener_mask": (1, 1),
    "audio_emitter_get_x": (1, 1),
    "audio_emitter_get_y": (1, 1),
    "audio_emitter_get_z": (1, 1),
    "audio_listener_position": (3, 3),
    "audio_listener_velocity": (3, 3),
    "audio_listener_orientation": (6, 6),
    "audio_listener_set_position": (4, 4),
    "audio_listener_set_velocity": (4, 4),
    "audio_listener_set_orientation": (7, 7),
    "audio_get_listener_count": (0, 0),
    "audio_get_listener_info": (1, 1),
    "audio_get_listener_mask": (0, 0),
    "audio_set_listener_mask": (1, 1),
    "audio_create_play_queue": (3, 3),
    "audio_queue_sound": (4, 4),
    "audio_free_play_queue": (1, 1),
    "audio_get_recorder_count": (0, 0),
    "audio_get_recorder_info": (1, 1),
    "audio_start_recording": (1, 1),
    "audio_stop_recording": (1, 1),
    "audio_create_stream": (1, 1),
    "audio_destroy_stream": (1, 1),
    "audio_create_sync_group": (1, 1),
    "audio_play_in_sync_group": (2, 2),
    "audio_start_sync_group": (1, 1),
    "audio_stop_sync_group": (1, 1),
    "audio_pause_sync_group": (1, 1),
    "audio_resume_sync_group": (1, 1),
    "audio_sync_group_is_playing": (1, 1),
    "audio_sync_group_get_track_pos": (1, 1),
    "audio_destroy_sync_group": (1, 1),
    "audio_group_load": (1, 1),
    "audio_group_unload": (1, 1),
    "audio_group_is_loaded": (1, 1),
    "audio_group_load_progress": (1, 1),
    "audio_group_name": (1, 1),
    "audio_group_stop_all": (1, 1),
    "audio_group_set_gain": (2, 3),
    "audio_group_get_gain": (1, 1),
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
    "ds_exists": (2, 2),
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
    "ds_list_read": (2, 3),
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
    "game_set_speed": (2, 2),
    "game_restart": (0, 0),
    "game_end": (0, 0),
    "room_exists": (1, 1),
    "room_get_name": (1, 1),
    "room_get_info": (1, 1),
}

_LAYER_ARITY: dict[str, tuple[int, int | None]] = {
    "layer_exists": (1, 1),
    "layer_get_id": (1, 1),
    "layer_get_id_at_depth": (1, 1),
    "layer_get_name": (1, 1),
    "layer_get_all": (0, 0),
    "layer_get_depth": (1, 1),
    "layer_get_x": (1, 1),
    "layer_get_y": (1, 1),
    "layer_get_hspeed": (1, 1),
    "layer_get_vspeed": (1, 1),
    "layer_depth": (2, 2),
    "layer_x": (2, 2),
    "layer_y": (2, 2),
    "layer_hspeed": (2, 2),
    "layer_vspeed": (2, 2),
    "layer_create": (1, 2),
    "layer_destroy": (1, 1),
    "layer_add_instance": (2, 2),
    "layer_get_all_elements": (1, 1),
    "layer_element_move": (2, 2),
    "layer_get_element_type": (1, 1),
    "layer_set_visible": (2, 2),
    "layer_get_visible": (1, 1),
    "layer_background_get_id": (1, 1),
    "layer_background_alpha": (2, 2),
    "layer_background_blend": (2, 2),
    "layer_tilemap_get_id": (1, 1),
    "layer_tilemap_create": (6, 6),
    "tilemap_set": (4, 4),
    "tilemap_get": (3, 3),
    "tilemap_get_width": (1, 1),
    "tilemap_get_height": (1, 1),
}

_SEQUENCE_TIMELINE_ARITY: dict[str, tuple[int, int | None]] = {
    "timeline_exists": (1, 1),
    "timeline_get_name": (1, 1),
    "timeline_moment_add_script": (3, 3),
    "timeline_moment_clear": (2, 2),
    "timeline_clear": (1, 1),
    "timeline_size": (1, 1),
    "timeline_max_moment": (1, 1),
    "timeline_step": (0, 1),
    "sequence_exists": (1, 1),
    "sequence_get": (1, 1),
    "sequence_create": (0, 0),
    "sequence_destroy": (1, 1),
    "layer_sequence_create": (4, 4),
    "layer_sequence_destroy": (1, 1),
    "layer_sequence_get_instance": (1, 1),
    "layer_sequence_headpos": (2, 2),
    "layer_sequence_get_headpos": (1, 1),
    "layer_sequence_speedscale": (2, 2),
    "layer_sequence_get_speedscale": (1, 1),
    "layer_sequence_headdir": (2, 2),
    "layer_sequence_get_headdir": (1, 1),
    "layer_sequence_pause": (1, 1),
    "layer_sequence_play": (1, 1),
    "layer_sequence_is_paused": (1, 1),
    "layer_sequence_is_finished": (1, 1),
    "layer_sequence_step": (1, 2),
}

_FLEXPANEL_ARITY: dict[str, tuple[int, int | None]] = {
    "flexpanel_create_node": (0, 1),
    "flexpanel_delete_node": (1, 1),
    "flexpanel_node_insert_child": (3, 3),
    "flexpanel_node_remove_child": (2, 2),
    "flexpanel_node_remove_all_children": (1, 1),
    "flexpanel_calculate_layout": (4, 4),
    "flexpanel_node_set_name": (2, 2),
    "flexpanel_node_layout_get_position": (1, 2),
    "flexpanel_node_get_num_children": (1, 1),
    "flexpanel_node_get_child": (2, 2),
    "flexpanel_node_get_child_hash": (2, 2),
    "flexpanel_node_get_parent": (1, 1),
    "flexpanel_node_get_name": (1, 1),
    "flexpanel_node_get_data": (1, 1),
    "flexpanel_node_get_struct": (1, 1),
    "flexpanel_node_set_measure_function": (2, 2),
    "flexpanel_node_get_measure_function": (1, 1),
    "flexpanel_node_style_set_width": (3, 3),
    "flexpanel_node_style_set_height": (3, 3),
    "flexpanel_node_style_set_min_width": (3, 3),
    "flexpanel_node_style_set_max_width": (3, 3),
    "flexpanel_node_style_set_min_height": (3, 3),
    "flexpanel_node_style_set_max_height": (3, 3),
    "flexpanel_node_style_set_aspect_ratio": (2, 2),
    "flexpanel_node_style_set_position": (4, 4),
    "flexpanel_node_style_set_position_type": (2, 2),
    "flexpanel_node_style_set_margin": (3, 4),
    "flexpanel_node_style_set_padding": (3, 4),
    "flexpanel_node_style_set_border": (3, 3),
    "flexpanel_node_style_set_gap": (3, 3),
    "flexpanel_node_style_set_direction": (2, 2),
    "flexpanel_node_style_set_flex_direction": (2, 2),
    "flexpanel_node_style_set_flex_wrap": (2, 2),
    "flexpanel_node_style_set_flex_basis": (3, 3),
    "flexpanel_node_style_set_flex_grow": (2, 2),
    "flexpanel_node_style_set_flex_shrink": (2, 2),
    "flexpanel_node_style_set_flex": (2, 2),
    "flexpanel_node_style_set_justify_content": (2, 2),
    "flexpanel_node_style_set_align_items": (2, 2),
    "flexpanel_node_style_set_align_self": (2, 2),
    "flexpanel_node_style_set_align_content": (2, 2),
    "flexpanel_node_style_set_display": (2, 2),
    "flexpanel_node_style_get_width": (1, 1),
    "flexpanel_node_style_get_height": (1, 1),
    "flexpanel_node_style_get_min_width": (1, 1),
    "flexpanel_node_style_get_max_width": (1, 1),
    "flexpanel_node_style_get_min_height": (1, 1),
    "flexpanel_node_style_get_max_height": (1, 1),
    "flexpanel_node_style_get_aspect_ratio": (1, 1),
    "flexpanel_node_style_get_position": (2, 2),
    "flexpanel_node_style_get_position_type": (1, 1),
    "flexpanel_node_style_get_margin": (2, 2),
    "flexpanel_node_style_get_padding": (2, 2),
    "flexpanel_node_style_get_border": (2, 2),
    "flexpanel_node_style_get_gap": (2, 2),
    "flexpanel_node_style_get_direction": (1, 1),
    "flexpanel_node_style_get_flex_direction": (1, 1),
    "flexpanel_node_style_get_flex_wrap": (1, 1),
    "flexpanel_node_style_get_flex_basis": (1, 1),
    "flexpanel_node_style_get_flex_grow": (1, 1),
    "flexpanel_node_style_get_flex_shrink": (1, 1),
    "flexpanel_node_style_get_flex": (1, 1),
    "flexpanel_node_style_get_justify_content": (1, 1),
    "flexpanel_node_style_get_align_items": (1, 1),
    "flexpanel_node_style_get_align_self": (1, 1),
    "flexpanel_node_style_get_align_content": (1, 1),
    "flexpanel_node_style_get_display": (1, 1),
}

_OS_DEBUG_GC_ARITY: dict[str, tuple[int, int | None]] = {
    "os_is_paused": (0, 0),
    "os_is_network_connected": (0, 1),
    "os_get_config": (0, 0),
    "os_get_language": (0, 0),
    "os_get_region": (0, 0),
    "os_get_info": (0, 0),
    "parameter_count": (0, 0),
    "parameter_string": (1, 1),
    "environment_get_variable": (1, 1),
    "clipboard_has_text": (0, 0),
    "clipboard_get_text": (0, 0),
    "clipboard_set_text": (1, 1),
    "debug_get_callstack": (0, 1),
    "exception_unhandled_handler": (1, 1),
    "show_debug_message_ext": (2, 2),
    "show_message": (1, 1),
    "show_error": (2, 2),
    "code_is_compiled": (0, 0),
    "gc_enable": (1, 1),
    "gc_is_enabled": (0, 0),
    "gc_collect": (0, 0),
    "gc_target_frame_time": (1, 1),
    "gc_get_target_frame_time": (0, 0),
    "gc_get_stats": (0, 0),
    "weak_ref_create": (1, 1),
    "weak_ref_alive": (1, 1),
    "weak_ref_any_alive": (1, 3),
}

_PLATFORM_SERVICE_ARITY: dict[str, tuple[int, int | None]] = {
    "steam_is_initialized": (0, 0),
    "browser_input_capture": (1, 1),
    "url_open": (1, 1),
    "url_open_ext": (2, 2),
    "url_open_full": (3, 3),
    "url_get_domain": (0, 0),
    "xboxlive_user_is_signed_in": (0, 0),
    "xboxlive_user_is_signing_in": (0, 0),
    "xboxlive_gamertag_for_user": (0, 0),
    "xboxlive_show_account_picker": (0, 0),
    "wallpaper_set_config": (1, 1),
    "wallpaper_set_subscriptions": (1, 1),
    "cloud_synchronise": (0, 0),
    "cloud_string_save": (2, 2),
    "cloud_file_save": (2, 2),
}

_PLATFORM_SERVICE_HOOK_API_SERVICES: dict[str, str] = {
    "steam_activate_overlay": "steam",
    "steam_get_persona_name": "steam",
    "steam_set_achievement": "steam",
    "steam_get_achievement": "steam",
    "steam_user_owns_dlc": "steam",
    "steam_download_scores": "steam",
    "steam_upload_score": "steam",
    "steam_ugc_create_item": "steam",
    "steam_ugc_publish": "steam",
    "iap_data": "iap",
    "iap_activate": "iap",
    "iap_status": "iap",
    "iap_enumerate_products": "iap",
    "iap_restore_all": "iap",
    "iap_acquire": "iap",
    "iap_consume": "iap",
    "iap_product_details": "iap",
    "iap_purchase_details": "iap",
    "mac_refresh_receipt_validation": "iap",
    "clickable_exists": "web",
    "clickable_add": "web",
    "clickable_add_ext": "web",
    "clickable_change": "web",
    "clickable_change_ext": "web",
    "clickable_set_style": "web",
    "clickable_delete": "web",
    "analytics_event": "web",
    "analytics_event_ext": "web",
    "http_get_request_crossorigin": "web",
    "http_set_request_crossorigin": "web",
    "uwp_suspend": "xboxlive",
    "uwp_is_suspending": "xboxlive",
    "uwp_is_constrained": "xboxlive",
    "uwp_was_terminated": "xboxlive",
    "uwp_was_closed_by_user": "xboxlive",
    "uwp_show_help": "xboxlive",
    "uwp_license_trial_version": "xboxlive",
    "uwp_license_trial_user": "xboxlive",
    "uwp_license_trial_time_remaining": "xboxlive",
    "uwp_check_privilege": "xboxlive",
    "xboxlive_get_user_count": "xboxlive",
    "xboxlive_get_user": "xboxlive",
    "xboxlive_get_activating_user": "xboxlive",
    "xboxlive_user_is_guest": "xboxlive",
    "xboxlive_user_is_active": "xboxlive",
    "xboxlive_user_is_remote": "xboxlive",
    "xboxlive_user_id_for_user": "xboxlive",
    "xboxlive_sponsor_for_user": "xboxlive",
    "xboxlive_set_rich_presence": "xboxlive",
    "xboxlive_gamedisplayname_for_user": "xboxlive",
    "xboxlive_user_for_pad": "xboxlive",
    "xboxlive_pad_for_user": "xboxlive",
    "xboxlive_pad_count_for_user": "xboxlive",
    "xboxlive_agegroup_for_user": "xboxlive",
    "xboxlive_gamerscore_for_user": "xboxlive",
    "xboxlive_show_profile_card_for_user": "xboxlive",
    "xboxlive_reputation_for_user": "xboxlive",
    "xboxlive_sprite_add_from_gamerpicture": "xboxlive",
    "xboxlive_generate_player_session_id": "xboxlive",
    "xboxlive_set_savedata_user": "xboxlive",
    "xboxlive_get_savedata_user": "xboxlive",
    "xboxlive_get_file_error": "xboxlive",
    "xboxlive_stats_setup": "xboxlive",
    "xboxlive_stats_add_user": "xboxlive",
    "xboxlive_stats_remove_user": "xboxlive",
    "xboxlive_stats_flush_user": "xboxlive",
    "xboxlive_stats_set_stat_real": "xboxlive",
    "xboxlive_stats_set_stat_int": "xboxlive",
    "xboxlive_stats_set_stat_string": "xboxlive",
    "xboxlive_stats_delete_stat": "xboxlive",
    "xboxlive_stats_get_stat_names": "xboxlive",
    "xboxlive_stats_get_stat": "xboxlive",
    "xboxlive_stats_get_leaderboard": "xboxlive",
    "xboxlive_stats_get_social_leaderboard": "xboxlive",
    "xboxlive_achievement_show_achievements": "xboxlive",
    "xboxlive_achievement_load_friends": "xboxlive",
    "xboxlive_achievement_load_leaderboard": "xboxlive",
    "xboxlive_achievements_set_progress": "xboxlive",
    "xboxlive_get_stats_for_user": "xboxlive",
    "xboxlive_read_player_leaderboard": "xboxlive",
    "xboxlive_fire_event": "xboxlive",
    "xboxlive_matchmaking_start": "xboxlive",
    "xboxlive_matchmaking_stop": "xboxlive",
    "xboxlive_matchmaking_create": "xboxlive",
    "xboxlive_matchmaking_find": "xboxlive",
    "xboxlive_matchmaking_session_get_users": "xboxlive",
    "xboxlive_matchmaking_join_session": "xboxlive",
    "xboxlive_matchmaking_session_leave": "xboxlive",
    "xboxlive_matchmaking_send_invites": "xboxlive",
    "xboxlive_matchmaking_set_joinable_session": "xboxlive",
    "xboxlive_matchmaking_join_invite": "xboxlive",
}

_PLATFORM_SERVICE_HOOK_ARITY: dict[str, tuple[int, int | None]] = {
    "steam_set_achievement": (1, 1),
    "steam_get_achievement": (1, 1),
    "steam_upload_score": (2, 2),
    "steam_download_scores": (3, 3),
    "iap_activate": (0, 0),
    "iap_restore_all": (0, 0),
    "iap_acquire": (1, 2),
    "iap_consume": (1, 1),
    "xboxlive_achievements_set_progress": (3, 3),
    "xboxlive_stats_get_leaderboard": (1, None),
    "xboxlive_read_player_leaderboard": (4, 4),
    "xboxlive_matchmaking_create": (0, None),
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
    "draw_line_width": (5, 5),
    "draw_rectangle_color": (9, 9),
    "draw_circle_color": (6, 6),
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
    "sprite_get_uvs": (2, 2),
    "sprite_get_width": (1, 1),
    "sprite_get_height": (1, 1),
    "sprite_set_offset": (3, 3),
    "sprite_delete": (1, 1),
    "surface_get_texture": (1, 1),
    "texture_exists": (1, 1),
    "texture_get_width": (1, 1),
    "texture_get_height": (1, 1),
    "texture_get_texel_width": (1, 1),
    "texture_get_texel_height": (1, 1),
    "texture_get_uvs": (1, 1),
    "texture_is_ready": (1, 1),
    "texture_prefetch": (1, 1),
    "texture_flush": (1, 1),
    "sprite_prefetch": (1, 1),
    "sprite_flush": (1, 1),
    "sprite_prefetch_multi": (1, 1),
    "sprite_flush_multi": (1, 1),
    "draw_texture_flush": (0, 0),
    "draw_flush": (0, 0),
    "texture_global_scale": (1, 1),
    "texture_debug_messages": (1, 1),
    "texturegroup_set_mode": (1, 3),
    "texturegroup_load": (1, 1),
    "texturegroup_unload": (1, 1),
    "texturegroup_get_status": (1, 1),
    "texturegroup_get_names": (0, 0),
    "texturegroup_get_textures": (1, 1),
    "texturegroup_get_sprites": (1, 1),
    "texturegroup_get_fonts": (1, 1),
    "texturegroup_get_tilesets": (1, 1),
    "video_open": (1, 1),
    "video_close": (0, 0),
    "video_draw": (0, 0),
    "video_set_volume": (1, 1),
    "video_pause": (0, 0),
    "video_resume": (0, 0),
    "video_enable_loop": (1, 1),
    "video_seek_to": (1, 1),
    "video_is_looping": (0, 0),
    "video_get_volume": (0, 0),
    "video_get_duration": (0, 0),
    "video_get_position": (0, 0),
    "video_get_status": (0, 0),
    "video_get_format": (0, 0),
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
    "shader_set_uniform_matrix": (1, 1),
    "texture_set_stage": (2, 2),
    "part_system_exists": (1, 1),
    "part_system_create": (0, 1),
    "part_system_create_layer": (2, 3),
    "part_system_get_layer": (1, 1),
    "part_system_layer": (2, 2),
    "part_system_depth": (2, 2),
    "part_system_position": (3, 3),
    "part_system_destroy": (1, 1),
    "part_system_clear": (1, 1),
    "part_particles_clear": (1, 1),
    "part_particles_count": (1, 1),
    "part_particles_create": (5, 5),
    "part_type_exists": (1, 1),
    "part_type_create": (0, 0),
    "part_type_destroy": (1, 1),
    "part_type_shape": (2, 2),
    "part_type_size": (5, 5),
    "part_type_scale": (3, 3),
    "part_type_life": (3, 3),
    "part_type_speed": (5, 5),
    "part_type_direction": (5, 5),
    "part_type_gravity": (3, 3),
    "part_type_orientation": (6, 6),
    "part_type_colour1": (2, 2),
    "part_type_colour2": (3, 3),
    "part_type_colour3": (4, 4),
    "part_type_alpha1": (2, 2),
    "part_type_alpha2": (3, 3),
    "part_type_alpha3": (4, 4),
    "part_type_blend": (2, 2),
    "part_type_sprite": (5, 5),
    "part_emitter_exists": (2, 2),
    "part_emitter_create": (1, 1),
    "part_emitter_region": (8, 8),
    "part_emitter_relative": (3, 3),
    "part_emitter_destroy": (2, 2),
    "part_emitter_destroy_all": (1, 1),
    "part_emitter_clear": (2, 2),
    "part_emitter_enable": (3, 3),
    "part_emitter_burst": (4, 4),
    "part_emitter_stream": (4, 4),
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
    "camera_create": (0, 0),
    "camera_create_view": (10, 10),
    "camera_destroy": (1, 1),
    "camera_apply": (1, 1),
    "camera_get_active": (0, 0),
    "camera_get_default": (0, 0),
    "camera_set_default": (1, 1),
    "camera_set_view_mat": (2, 2),
    "camera_get_view_mat": (1, 1),
    "camera_set_proj_mat": (2, 2),
    "camera_get_proj_mat": (1, 1),
    "camera_set_view_target": (2, 2),
    "camera_get_view_target": (1, 1),
    "camera_set_view_speed": (3, 3),
    "camera_get_view_speed_x": (1, 1),
    "camera_get_view_speed_y": (1, 1),
    "camera_set_view_border": (3, 3),
    "camera_get_view_border_x": (1, 1),
    "camera_get_view_border_y": (1, 1),
    "camera_set_view_pos": (3, 3),
    "camera_set_view_size": (3, 3),
    "camera_get_view_x": (1, 1),
    "camera_get_view_y": (1, 1),
    "camera_get_view_width": (1, 1),
    "camera_get_view_height": (1, 1),
    "camera_set_view_angle": (2, 2),
    "camera_get_view_angle": (1, 1),
    "view_get_camera": (1, 1),
    "view_set_camera": (2, 2),
    "view_get_surface_id": (1, 1),
    "view_set_surface_id": (2, 2),
    "view_get_visible": (1, 1),
    "view_set_visible": (2, 2),
    "view_get_xport": (1, 1),
    "view_get_yport": (1, 1),
    "view_get_wport": (1, 1),
    "view_get_hport": (1, 1),
    "view_set_xport": (2, 2),
    "view_set_yport": (2, 2),
    "view_set_wport": (2, 2),
    "view_set_hport": (2, 2),
    "display_get_gui_width": (0, 0),
    "display_get_gui_height": (0, 0),
    "display_set_gui_size": (2, 2),
    "display_set_gui_maximise": (0, 4),
    "display_get_width": (0, 0),
    "display_get_height": (0, 0),
    "display_get_dpi_x": (0, 0),
    "display_get_dpi_y": (0, 0),
    "display_get_orientation": (0, 0),
    "display_set_orientation": (1, 1),
    "display_get_frequency": (0, 0),
    "display_reset": (2, 2),
    "display_get_timing_method": (0, 0),
    "display_get_sleep_margin": (0, 0),
    "display_set_ui_visibility": (1, 1),
    "display_set_timing_method": (1, 1),
    "display_set_sleep_margin": (1, 1),
    "window_center": (0, 0),
    "window_get_fullscreen": (0, 0),
    "window_get_width": (0, 0),
    "window_get_height": (0, 0),
    "window_get_x": (0, 0),
    "window_get_y": (0, 0),
    "window_get_visible_rects": (0, 0),
    "window_mouse_get_x": (0, 0),
    "window_mouse_get_y": (0, 0),
    "window_mouse_set": (2, 2),
    "window_view_mouse_get_x": (1, 1),
    "window_view_mouse_get_y": (1, 1),
    "window_views_mouse_get_x": (0, 0),
    "window_views_mouse_get_y": (0, 0),
    "window_set_fullscreen": (1, 1),
    "window_set_position": (2, 2),
    "window_set_size": (2, 2),
    "window_set_rectangle": (4, 4),
    "window_set_cursor": (1, 1),
    "window_set_min_width": (1, 1),
    "window_set_max_width": (1, 1),
    "window_set_min_height": (1, 1),
    "window_set_max_height": (1, 1),
    "window_minimise": (0, 0),
    "window_restore": (0, 0),
    "screen_save": (1, 1),
    "screen_save_part": (5, 5),
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
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name == "array_push":
            lowering_kind = "runtime_variadic_1"
        elif name == "array_foreach":
            lowering_kind = "runtime_array_foreach"
        elif name == "array_sort":
            lowering_kind = "runtime_array_sort"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    for name, target in _STRING_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _STRING_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _MATH_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _MATH_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime"
        if name in ("min", "max", "choose"):
            lowering_kind = "runtime_variadic_all"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

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
            "physics_mass_properties",
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

    for name, target in _LAYER_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _LAYER_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_layer_api", target)

    for name, target in _SEQUENCE_TIMELINE_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _SEQUENCE_TIMELINE_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime_sequence_api", target)

    for name, target in _FLEXPANEL_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _FLEXPANEL_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _OS_DEBUG_GC_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _OS_DEBUG_GC_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _PLATFORM_SERVICE_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _PLATFORM_SERVICE_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, service_name in _PLATFORM_SERVICE_HOOK_API_SERVICES.items():
        min_args, max_args = _PLATFORM_SERVICE_HOOK_ARITY.get(name, (0, None))
        descriptors[name] = _descriptor(
            name,
            min_args,
            max_args,
            "runtime_platform_service_api",
            service_name,
        )

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
        None,
        "print",
        "gml_show_debug_message",
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
