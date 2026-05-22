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

    @property
    def godot_path(self) -> str: ...


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
    kind: int
    precision: int
    godot_path: str
    points: tuple[PathPoint, ...]

    def to_godot_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "closed": self.closed,
            "kind": self.kind,
            "precision": self.precision,
            "godot_path": self.godot_path,
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
    for entry in entries:
        _write_path_scene(godot_project_path, entry)
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
        kind=int(_number(data.get("kind"), 0.0)),
        precision=int(_number(data.get("precision"), 4.0)),
        godot_path=asset_entry.godot_path,
        points=tuple(points),
    )


def render_path_scene(entry: PathRegistryEntry) -> str:
    curve_points: list[str] = []
    tilts: list[str] = []
    for point in entry.points:
        curve_points.extend(("0", "0", "0", "0", _format_number(point.x), _format_number(point.y)))
        tilts.append("0")
    curve_data = "PackedVector2Array({values})".format(values=", ".join(curve_points))
    tilt_data = "PackedFloat32Array({values})".format(values=", ".join(tilts))
    lines = [
        "[gd_scene load_steps=2 format=3]",
        "",
        '[sub_resource type="Curve2D" id="Curve2D_1"]',
        '_data = {"points": ' + curve_data + ', "tilts": ' + tilt_data + "}",
        f"point_count = {len(entry.points)}",
        "",
        f"[node name={json.dumps(entry.name)} type=\"Path2D\"]",
        'curve = SubResource("Curve2D_1")',
        f"metadata/gamemaker_path_id = {entry.id}",
        f"metadata/gamemaker_path_name = {json.dumps(entry.name)}",
        f"metadata/gamemaker_path_closed = {json.dumps(entry.closed)}",
        f"metadata/gamemaker_path_kind = {entry.kind}",
        f"metadata/gamemaker_path_precision = {entry.precision}",
        f"metadata/gamemaker_path_points = {json.dumps([point.to_godot_dict() for point in entry.points])}",
        "",
    ]
    return "\n".join(lines)


def _write_path_scene(godot_project_path: str, entry: PathRegistryEntry) -> None:
    if not entry.godot_path.startswith("res://"):
        return
    relative_path = entry.godot_path[len("res://"):]
    output_path = os.path.join(godot_project_path, *relative_path.split("/"))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_path_scene(entry))


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


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return ("{:.6f}".format(value)).rstrip("0").rstrip(".")
