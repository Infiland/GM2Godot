from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Protocol, cast

from src.conversion.type_defs import JsonDict

PATH_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_path_registry.gd")
PATH_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_path_registry.gd"


class _PathAssetEntry(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def source_path(self) -> str: ...


@dataclass(frozen=True)
class PathPoint:
    x: float
    y: float
    speed: float = 100.0

    def to_godot_dict(self) -> JsonDict:
        return {"x": self.x, "y": self.y, "speed": self.speed}


@dataclass(frozen=True)
class PathRegistryEntry:
    id: int
    name: str
    closed: bool
    precision: int
    points: tuple[PathPoint, ...]

    def to_godot_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "closed": self.closed,
            "precision": self.precision,
            "points": [point.to_godot_dict() for point in self.points],
        }


def build_path_registry_entries(
    gm_project_path: str,
    asset_entries: Iterable[_PathAssetEntry],
) -> tuple[PathRegistryEntry, ...]:
    path_entries: list[PathRegistryEntry] = []
    for asset_entry in asset_entries:
        if asset_entry.kind != "paths":
            continue
        yy_path = os.path.join(gm_project_path, asset_entry.source_path)
        data = _read_json_lenient(yy_path)
        if data is None:
            continue
        path_entries.append(_path_entry_from_yy(asset_entry, data))
    return tuple(path_entries)


def render_path_registry_script(entries: Iterable[PathRegistryEntry]) -> str:
    entry_dicts = [entry.to_godot_dict() for entry in entries]
    lines = [
        "extends RefCounted\n\n",
        "static func entries():\n",
        "\treturn ",
        json.dumps(entry_dicts, indent="\t"),
        "\n",
    ]
    return "".join(lines)


def write_path_registry(
    gm_project_path: str,
    godot_project_path: str,
    asset_entries: Iterable[_PathAssetEntry],
) -> str:
    entries = build_path_registry_entries(gm_project_path, asset_entries)
    registry_path = os.path.join(godot_project_path, PATH_REGISTRY_RELATIVE_PATH)
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        f.write(render_path_registry_script(entries))
    return registry_path


def _path_entry_from_yy(asset_entry: _PathAssetEntry, data: JsonDict) -> PathRegistryEntry:
    raw_points = data.get("points")
    points: list[PathPoint] = []
    if isinstance(raw_points, list):
        for raw_point in cast(list[object], raw_points):
            if not isinstance(raw_point, dict):
                continue
            point = cast(JsonDict, raw_point)
            points.append(
                PathPoint(
                    x=_number(point.get("x"), 0.0),
                    y=_number(point.get("y"), 0.0),
                    speed=_number(point.get("speed"), 100.0),
                )
            )
    return PathRegistryEntry(
        id=asset_entry.id,
        name=asset_entry.name,
        closed=bool(data.get("closed", False)),
        precision=int(_number(data.get("precision"), 4.0)),
        points=tuple(points),
    )


def _read_json_lenient(path: str) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    try:
        return cast(JsonDict, json.loads(_strip_trailing_commas(content)))
    except json.JSONDecodeError:
        return None


def _strip_trailing_commas(content: str) -> str:
    import re

    return re.sub(r",\s*([}\]])", r"\1", content)


def _number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return default

