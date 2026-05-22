from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, Protocol, cast

from src.conversion.type_defs import JsonDict

ANIMATION_CURVE_REGISTRY_RELATIVE_PATH = os.path.join(
    "gm2godot", "gml_animation_curve_registry.gd"
)
ANIMATION_CURVE_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_animation_curve_registry.gd"


class _AnimationCurveAssetEntry(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def source_path(self) -> str: ...


@dataclass(frozen=True)
class AnimationCurvePoint:
    x: float
    y: float
    bezier_x0: float = 0.0
    bezier_y0: float = 0.0
    bezier_x1: float = 0.0
    bezier_y1: float = 0.0

    def to_godot_dict(self) -> JsonDict:
        return {
            "x": self.x,
            "y": self.y,
            "bezier_x0": self.bezier_x0,
            "bezier_y0": self.bezier_y0,
            "bezier_x1": self.bezier_x1,
            "bezier_y1": self.bezier_y1,
        }


@dataclass(frozen=True)
class AnimationCurveChannel:
    name: str
    function: str
    iterations: int
    points: tuple[AnimationCurvePoint, ...]

    def to_godot_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "function": self.function,
            "iterations": self.iterations,
            "points": [point.to_godot_dict() for point in self.points],
        }


@dataclass(frozen=True)
class AnimationCurveRegistryEntry:
    id: int
    name: str
    channels: tuple[AnimationCurveChannel, ...]

    def to_godot_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "channels": [channel.to_godot_dict() for channel in self.channels],
        }


def build_animation_curve_registry_entries(
    gm_project_path: str,
    asset_entries: Iterable[_AnimationCurveAssetEntry],
) -> tuple[AnimationCurveRegistryEntry, ...]:
    entries: list[AnimationCurveRegistryEntry] = []
    for asset_entry in asset_entries:
        if asset_entry.kind != "animcurves":
            continue
        yy_path = os.path.join(gm_project_path, asset_entry.source_path)
        data = _read_json_lenient(yy_path)
        if data is None:
            continue
        entries.append(_animation_curve_entry_from_yy(asset_entry, data))
    return tuple(entries)


def render_animation_curve_registry_script(
    entries: Iterable[AnimationCurveRegistryEntry],
) -> str:
    entry_dicts = [entry.to_godot_dict() for entry in entries]
    lines = [
        "extends RefCounted\n\n",
        "static func entries():\n",
        "\treturn ",
        json.dumps(entry_dicts, indent="\t"),
        "\n",
    ]
    return "".join(lines)


def write_animation_curve_registry(
    gm_project_path: str,
    godot_project_path: str,
    asset_entries: Iterable[_AnimationCurveAssetEntry],
) -> str:
    entries = build_animation_curve_registry_entries(gm_project_path, asset_entries)
    registry_path = os.path.join(godot_project_path, ANIMATION_CURVE_REGISTRY_RELATIVE_PATH)
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        f.write(render_animation_curve_registry_script(entries))
    return registry_path


def _animation_curve_entry_from_yy(
    asset_entry: _AnimationCurveAssetEntry,
    data: JsonDict,
) -> AnimationCurveRegistryEntry:
    channels: list[AnimationCurveChannel] = []
    raw_channels = data.get("channels")
    if isinstance(raw_channels, list):
        for raw_channel in cast(list[object], raw_channels):
            if not isinstance(raw_channel, dict):
                continue
            channels.append(_animation_curve_channel_from_yy(cast(JsonDict, raw_channel)))
    return AnimationCurveRegistryEntry(
        id=asset_entry.id,
        name=asset_entry.name,
        channels=tuple(channels),
    )


def _animation_curve_channel_from_yy(channel: JsonDict) -> AnimationCurveChannel:
    raw_points = channel.get("points")
    points: list[AnimationCurvePoint] = []
    if isinstance(raw_points, list):
        for raw_point in cast(list[object], raw_points):
            if not isinstance(raw_point, dict):
                continue
            point = cast(JsonDict, raw_point)
            points.append(
                AnimationCurvePoint(
                    x=_number(point.get("x"), 0.0),
                    y=_number(point.get("y"), 0.0),
                    bezier_x0=_number(point.get("bezierX0"), 0.0),
                    bezier_y0=_number(point.get("bezierY0"), 0.0),
                    bezier_x1=_number(point.get("bezierX1"), 0.0),
                    bezier_y1=_number(point.get("bezierY1"), 0.0),
                )
            )
    return AnimationCurveChannel(
        name=_string(channel.get("name")),
        function=_string(channel.get("function")),
        iterations=int(_number(channel.get("iterations"), 1.0)),
        points=tuple(points),
    )


def _read_json_lenient(path: str) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    try:
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", content))
    except json.JSONDecodeError:
        return None
    return cast(JsonDict, data) if isinstance(data, dict) else None


def _number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return default


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
