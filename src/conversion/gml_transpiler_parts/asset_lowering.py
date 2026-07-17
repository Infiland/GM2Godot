from __future__ import annotations

from typing import Literal


AssetLoweringDomain = Literal[
    "audio",
    "draw",
    "layer",
    "path",
    "room",
    "script",
    "sequence_timeline",
]


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
    "audio_play_sound_at": frozenset({0}),
    "audio_play_sound_on": frozenset({1}),
    "audio_stop_sound": frozenset({0}),
    "audio_pause_sound": frozenset({0}),
    "audio_resume_sound": frozenset({0}),
    "audio_is_playing": frozenset({0}),
    "audio_is_paused": frozenset({0}),
    "audio_sound_gain": frozenset({0}),
    "audio_sound_get_gain": frozenset({0}),
    "audio_sound_pitch": frozenset({0}),
    "audio_sound_get_pitch": frozenset({0}),
    "audio_sound_loop": frozenset({0}),
    "audio_sound_get_loop": frozenset({0}),
    "audio_sound_set_listener_mask": frozenset({0}),
    "audio_sound_get_listener_mask": frozenset({0}),
    "audio_sound_get_asset": frozenset({0}),
    "audio_play_in_sync_group": frozenset({1}),
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

_LAYER_ASSET_ARG_INDICES: dict[str, frozenset[int]] = {
    "layer_tilemap_create": frozenset({3}),
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

_DOMAIN_INDICES: dict[AssetLoweringDomain, dict[str, frozenset[int]]] = {
    "audio": _AUDIO_ASSET_ARG_INDICES,
    "draw": _DRAW_ASSET_ARG_INDICES,
    "layer": _LAYER_ASSET_ARG_INDICES,
    "path": _PATH_ASSET_ARG_INDICES,
    "room": _ROOM_ASSET_ARG_INDICES,
    "script": _SCRIPT_ASSET_ARG_INDICES,
    "sequence_timeline": _SEQUENCE_TIMELINE_ASSET_ARG_INDICES,
}


def asset_argument_indices(function_name: str, domain: AssetLoweringDomain) -> frozenset[int]:
    return _DOMAIN_INDICES[domain].get(function_name, frozenset())


def first_argument_is_script_asset(function_name: str) -> bool:
    return 0 in asset_argument_indices(function_name, "script")
