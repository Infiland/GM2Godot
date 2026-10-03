"""Pure typed path metadata with the existing GameMaker field fallbacks."""

from dataclasses import dataclass, field

from src.conversion.json_fields import (
    JsonFieldError,
    JsonMissing,
    field_value,
    required_array,
    required_number,
    required_object,
    required_string,
)
from src.conversion.json_values import JsonObject, JsonPath


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class PathMetadataPoint:
    x: int | float
    y: int | float
    speed: int | float = 100.0
    raw_data: JsonObject = field(default_factory=_empty_json_object)


@dataclass(frozen=True)
class GameMakerPathMetadata:
    closed: bool = False
    kind: int | float = 0.0
    precision: int | float = 4.0
    points: tuple[PathMetadataPoint, ...] = ()
    parent_path: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_object)


def _number_or_default(
    data: JsonObject,
    key: str,
    default: int | float,
    *,
    source_path: str,
    field_path: JsonPath = (),
) -> int | float:
    value = field_value(data, key)
    if isinstance(value, bool):
        return int(value)
    try:
        return required_number(data, key, source_path=source_path, field_path=field_path)
    except JsonFieldError:
        return default


def _path_points(data: JsonObject, *, source_path: str) -> tuple[PathMetadataPoint, ...]:
    try:
        raw_points = required_array(data, "points", source_path=source_path)
    except JsonFieldError:
        return ()
    points: list[PathMetadataPoint] = []
    for index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, dict):
            continue
        field_path: JsonPath = ("points", index)
        points.append(
            PathMetadataPoint(
                x=_number_or_default(raw_point, "x", 0.0, source_path=source_path, field_path=field_path),
                y=_number_or_default(raw_point, "y", 0.0, source_path=source_path, field_path=field_path),
                speed=_number_or_default(raw_point, "speed", 100.0, source_path=source_path, field_path=field_path),
                raw_data=raw_point,
            )
        )
    return tuple(points)


def _parent_path(data: JsonObject, *, source_path: str) -> str:
    try:
        parent = required_object(data, "parent", source_path=source_path)
        return required_string(parent, "path", source_path=source_path, field_path=("parent",))
    except JsonFieldError:
        return ""


def parse_gamemaker_path_metadata(
    data: JsonObject,
    *,
    source_path: str,
) -> GameMakerPathMetadata:
    """Project validated raw JSON without coercing native numeric values."""
    closed = field_value(data, "closed")
    return GameMakerPathMetadata(
        closed=False if isinstance(closed, JsonMissing) else bool(closed),
        kind=_number_or_default(data, "kind", 0.0, source_path=source_path),
        precision=_number_or_default(data, "precision", 4.0, source_path=source_path),
        points=_path_points(data, source_path=source_path),
        parent_path=_parent_path(data, source_path=source_path),
        raw_data=data,
    )
