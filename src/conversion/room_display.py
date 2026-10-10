"""GameMaker window, application-surface and view-slot data derived from rooms.

GameMaker sizes the application surface (and the initial window) from the
first room in the room order: the bounding box of the visible viewports when
that room enables views, otherwise the room size.  Every later room is scaled
onto that fixed surface, so the Godot root viewport uses the same size with
the ``viewport`` stretch mode.
"""

from __future__ import annotations

import math

from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.room_metadata import (
    RoomSettingsFields,
    RoomViewFields,
    RoomViewSettingsFields,
    room_object_items,
)

GAMEMAKER_VIEW_COUNT = 8
GODOT_DISPLAY_SECTION = "display"
GODOT_VIEWPORT_WIDTH_SETTING = "window/size/viewport_width"
GODOT_VIEWPORT_HEIGHT_SETTING = "window/size/viewport_height"
GODOT_STRETCH_MODE_SETTING = "window/stretch/mode"
GODOT_STRETCH_MODE_VIEWPORT = "viewport"


def _number(value: JsonValue, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return default
    else:
        return default
    return number if math.isfinite(number) else default


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def room_size(room_settings: JsonValue, source_context: str = "") -> tuple[float, float]:
    """Return the room size, using GameMaker's 1024x768 default for missing values."""
    settings = RoomSettingsFields(room_settings or {}, source_context)
    return _number(settings.width, 1024.0), _number(settings.height, 768.0)


def _view_entry(view: JsonObject, source_context: str) -> JsonObject:
    fields = RoomViewFields(view, source_context)
    object_name = fields.object_name
    return {
        "visible": fields.visible,
        "xview": _compact_number(_number(fields.xview_value)),
        "yview": _compact_number(_number(fields.yview_value)),
        "wview": _compact_number(_number(fields.wview_value)),
        "hview": _compact_number(_number(fields.hview_value)),
        "xport": _compact_number(_number(fields.xport_value)),
        "yport": _compact_number(_number(fields.yport_value)),
        "wport": _compact_number(_number(fields.wport_value)),
        "hport": _compact_number(_number(fields.hport_value)),
        "object": object_name if isinstance(object_name, str) and object_name else None,
        "hborder": _compact_number(_number(fields.hborder, 32.0)),
        "vborder": _compact_number(_number(fields.vborder, 32.0)),
        "hspeed": _compact_number(_number(fields.hspeed, -1.0)),
        "vspeed": _compact_number(_number(fields.vspeed, -1.0)),
    }


def _default_view_entry(width: float, height: float) -> JsonObject:
    return {
        "visible": False,
        "xview": 0,
        "yview": 0,
        "wview": _compact_number(width),
        "hview": _compact_number(height),
        "xport": 0,
        "yport": 0,
        "wport": _compact_number(width),
        "hport": _compact_number(height),
        "object": None,
        "hborder": 32,
        "vborder": 32,
        "hspeed": -1,
        "vspeed": -1,
    }


def room_view_entries(
    views: JsonValue,
    room_settings: JsonValue,
    source_context: str = "",
) -> list[JsonObject]:
    """Normalize a room's view slots into exactly ``GAMEMAKER_VIEW_COUNT`` entries."""
    entries = [_view_entry(view, source_context) for view in room_object_items(views)]
    entries = entries[:GAMEMAKER_VIEW_COUNT]
    width, height = room_size(room_settings, source_context)
    while len(entries) < GAMEMAKER_VIEW_COUNT:
        entries.append(_default_view_entry(width, height))
    return entries


def _visible_port_extent(entries: list[JsonObject]) -> tuple[float, float] | None:
    right = 0.0
    bottom = 0.0
    found = False
    for entry in entries:
        if entry["visible"] is not True:
            continue
        found = True
        right = max(right, _number(entry["xport"]) + _number(entry["wport"]))
        bottom = max(bottom, _number(entry["yport"]) + _number(entry["hport"]))
    if not found or right <= 0.0 or bottom <= 0.0:
        return None
    return right, bottom


def application_surface_size(
    room_settings: JsonValue,
    view_settings: JsonValue,
    views: JsonValue,
    source_context: str = "",
) -> tuple[int, int]:
    """Return the application-surface size GameMaker derives from a (first) room."""
    width, height = room_size(room_settings, source_context)
    if RoomViewSettingsFields(view_settings or {}, source_context).enable_views:
        extent = _visible_port_extent(room_view_entries(views, room_settings, source_context))
        if extent is not None:
            width, height = extent
    return max(int(round(width)), 1), max(int(round(height)), 1)


def application_surface_display_settings(
    width: int,
    height: int,
) -> tuple[tuple[str, str, int | str], ...]:
    """Godot project settings that present the application surface like GameMaker."""
    return (
        (GODOT_DISPLAY_SECTION, GODOT_VIEWPORT_WIDTH_SETTING, width),
        (GODOT_DISPLAY_SECTION, GODOT_VIEWPORT_HEIGHT_SETTING, height),
        (GODOT_DISPLAY_SECTION, GODOT_STRETCH_MODE_SETTING, GODOT_STRETCH_MODE_VIEWPORT),
    )


__all__ = [
    "GAMEMAKER_VIEW_COUNT",
    "application_surface_display_settings",
    "application_surface_size",
    "room_size",
    "room_view_entries",
]
