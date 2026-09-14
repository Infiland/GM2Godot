"""Small serializers for the Deep inventory, using the client's resource models."""
from __future__ import annotations

import math
from pathlib import Path
from typing import cast

from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.project_manifest import GameMakerProjectManifest
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.resource_models import (
    GameMakerResourceModels,
    ObjectModel,
    RoomModel,
)
from src.conversion.type_defs import JsonDict


def _mapping(value: object) -> JsonDict:
    return cast(JsonDict, value) if isinstance(value, dict) else {}


def _rows(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [cast(JsonDict, row) for row in cast(list[object], value) if isinstance(row, dict)]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _events(model: ObjectModel) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in _rows(model.raw_data.get("eventList")):
        mapping = map_input_event(event) if is_input_event(event) else map_event(event)
        rows.append({
            "eventType": event.get("eventType", 0), "eventNum": event.get("eventNum", 0),
            "file": mapping.gml_filename if mapping is not None and not event.get("isDnD") else None,
        })
    return rows


def _instances(room: IndexedRoom) -> list[dict[str, object]]:
    names = [_text(row.get("name")) or _text(row.get("%Name")) for row in _rows(room.instance_creation_order)]
    order = {name: position for position, name in enumerate(names) if name}
    rows = [instance for layer in _rows(room.layers)
            if layer.get("resourceType") == "GMRInstanceLayer" for instance in _rows(layer.get("instances"))]
    rows.sort(key=lambda row: order.get(_text(row.get("name")) or _text(row.get("%Name")) or "", len(order)))
    return [{
        "name": _text(row.get("%Name")) or _text(row.get("name")),
        "objectName": _text(_mapping(row.get("objectId")).get("name")),
        "x": _number(row.get("x")), "y": _number(row.get("y")),
    } for row in rows]


def _room(room: IndexedRoom, model: RoomModel | None, ordered: bool) -> dict[str, object]:
    return {
        "name": room.name,
        "width": model.width if model else 0, "height": model.height if model else 0,
        "persistent": model.persistent if model else False,
        "parentRoomName": model.parent_room_name if model else None,
        "creationCodeFile": room.creation_code_file or None,
        "ordered": ordered,
        "layers": [{
            "name": _text(layer.get("%Name")) or _text(layer.get("name")) or "",
            "resourceType": _text(layer.get("resourceType")) or "",
            "depth": _number(layer.get("depth")), "order": position,
        } for position, layer in enumerate(_rows(room.layers))],
        "instances": _instances(room),
    }


def _resource_files(source: Path, yy_path: str) -> list[str]:
    path = Path(yy_path)
    if not path.is_absolute():
        path = source / path
    if not path.resolve().is_relative_to(source) or not path.is_file():
        return []
    # Resource sidecars include event GML, sprite frames, shader stages, and data.
    return sorted(str(child) for child in path.parent.rglob("*")
                  if child.is_file() and not child.is_symlink() and child.resolve().is_relative_to(source))


def inventory_resources(
    source: Path, manifest: GameMakerProjectManifest,
    models: GameMakerResourceModels, index: GameMakerResourceIndex,
) -> dict[str, object]:
    resources: list[dict[str, object]] = []
    for reference in manifest.resources:
        indexed = index.get_resource(reference.kind, reference.name)
        resources.append({
            "name": reference.name, "kind": reference.kind, "typeName": reference.resource_type,
            "yypPath": reference.path,
            "sourcePaths": _resource_files(source, indexed.yy_path if indexed else reference.path),
            "godotPath": indexed.godot_path if indexed else None,
        })
    room_models = {model.name: model for model in models.rooms}
    extensions: dict[str, list[dict[str, object]]] = {}
    for function in index.get_extension_functions().values():
        extensions.setdefault(function.extension_name, []).append({
            "name": function.function_name, "externalName": function.external_name or None,
            "argCount": function.arg_count, "fileName": function.file_name,
        })
    return {
        "project": {
            "name": manifest.project_name, "yypPath": manifest.yyp_path,
            "ideVersion": manifest.ide_version, "resourceType": manifest.resource_type,
            "resourceVersion": manifest.resource_version,
        },
        "resources": resources,
        "objects": [{
            "name": model.name, "parentObjectName": model.parent_object_name,
            "persistent": model.persistent, "solid": model.solid,
            "spriteName": model.sprite_name, "events": _events(model),
        } for model in models.objects],
        "rooms": [_room(room, room_models.get(room.name), not index.used_room_order_fallback)
                  for room in index.ordered_rooms()],
        "scripts": [{"name": model.name, "gmlPath": model.gml_path} for model in models.scripts],
        "sprites": [{"name": model.name, "width": model.width, "height": model.height,
                     "frameCount": len(_rows(model.raw_data.get("frames")))} for model in models.sprites],
        "shaders": [{"name": model.name, "vertexPath": model.vertex_path, "fragmentPath": model.fragment_path}
                    for model in models.shaders],
        "extensions": [{"name": name, "functions": functions} for name, functions in sorted(extensions.items())],
        "diagnostics": [
            {"severity": item.severity, "code": item.code, "message": item.message,
             "sourcePath": item.source.path if item.source else None}
            for item in manifest.diagnostics
        ] + [
            {"severity": item.severity, "code": item.code, "message": item.message, "sourcePath": item.source_path}
            for item in models.diagnostics
        ],
    }
