# pyright: reportPrivateUsage=false
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .constants import (
    _ARRAY_RUNTIME_FUNCTIONS,
    _ASSET_RUNTIME_FUNCTIONS,
    _COLLISION_RUNTIME_FUNCTIONS,
    _DRAW_RUNTIME_FUNCTIONS,
    _DS_MAP_RUNTIME_FUNCTIONS,
    _INSTANCE_RUNTIME_FUNCTIONS,
    _MOTION_RUNTIME_FUNCTIONS,
    _MP_GRID_RUNTIME_FUNCTIONS,
    _PATH_RUNTIME_FUNCTIONS,
    _RUNTIME_FUNCTIONS,
    _STRUCT_RUNTIME_FUNCTIONS,
    _VARIABLE_RUNTIME_FUNCTIONS,
)
from .gml_api_manifest import get_gml_api_entry

GMLFunctionLoweringKind: TypeAlias = Literal[
    "keyboard_check",
    "method",
    "print",
    "runtime",
    "runtime_append_self",
    "runtime_collision_api",
    "runtime_draw_api",
    "runtime_instance_api",
    "runtime_instance_keyword_first_arg",
    "runtime_motion_api",
    "runtime_path_api",
    "runtime_path_asset_api",
    "runtime_self_default",
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
    "ds_map_exists": (2, 2),
    "ds_map_find_value": (2, 2),
}

_ARRAY_ARITY: dict[str, tuple[int, int | None]] = {
    "array_equals": (2, 2),
    "array_push": (2, None),
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
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _DS_MAP_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _DS_MAP_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

    for name, target in _ARRAY_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _ARRAY_ARITY[name]
        descriptors[name] = _descriptor(name, min_args, max_args, "runtime", target)

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

    for name, target in _DRAW_RUNTIME_FUNCTIONS.items():
        min_args, max_args = _DRAW_ARITY[name]
        lowering_kind: GMLFunctionLoweringKind = "runtime_draw_api"
        if name == "draw_self":
            lowering_kind = "runtime_append_self"
        descriptors[name] = _descriptor(name, min_args, max_args, lowering_kind, target)

    descriptors["keyboard_check"] = _descriptor(
        "keyboard_check",
        1,
        1,
        "keyboard_check",
        "Input",
    )
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
