"""Canonical GameMaker path geometry, independent of source I/O and output writers."""

from __future__ import annotations

from dataclasses import dataclass

from src.conversion.json_values import JsonObject, JsonValue


@dataclass(frozen=True)
class PathPoint:
    x: float
    y: float
    speed: float = 100.0

    def to_godot_dict(self) -> JsonObject:
        return {"x": self.x, "y": self.y, "speed": self.speed}


@dataclass(frozen=True)
class PathModel:
    name: str
    source_path: str
    raw_data: JsonObject
    points: tuple[PathPoint, ...]
    closed: bool
    kind: int
    precision: int

    @property
    def point_count(self) -> int:
        return len(self.points)


def parse_path_model(
    data: JsonObject,
    *,
    name: str,
    source_path: str,
) -> PathModel:
    points = _path_points(data.get("points"))
    return PathModel(
        name=name,
        source_path=source_path,
        raw_data=data,
        points=points,
        closed=bool(data.get("closed", False)),
        kind=int(_number(data.get("kind"), 0.0)),
        precision=int(_number(data.get("precision"), 4.0)),
    )


def _path_points(value: JsonValue) -> tuple[PathPoint, ...]:
    if not isinstance(value, list):
        return ()
    points: list[PathPoint] = []
    for point in value:
        if isinstance(point, dict):
            points.append(
                PathPoint(
                    x=_number(point.get("x"), 0.0),
                    y=_number(point.get("y"), 0.0),
                    speed=_number(point.get("speed"), 100.0),
                )
            )
    return tuple(points)


def _number(value: JsonValue, default: float) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return default
