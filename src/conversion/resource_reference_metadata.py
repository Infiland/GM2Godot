"""Pure, domain-specific captures of GameMaker resource declarations."""

import os
from dataclasses import dataclass

from src.conversion.json_values import JsonObject, JsonValue


@dataclass(frozen=True)
class RegistryResourceDeclaration:
    path: str
    name_value: JsonValue
    raw_id: JsonObject


@dataclass(frozen=True)
class SpriteResourceDeclaration:
    name: str
    path_value: JsonValue
    raw_resource: JsonObject
    raw_id: JsonObject


@dataclass(frozen=True)
class AssetNameDeclaration:
    name: str | None
    raw_resource: JsonObject
    raw_id: JsonObject


@dataclass(frozen=True)
class TilesetResourceDeclaration:
    name: str
    path: str
    path_value: JsonValue
    raw_resource: JsonObject
    raw_id: JsonObject


def capture_tileset_resource_declaration(resource: JsonObject) -> TilesetResourceDeclaration | None:
    """Read one declaration at the owner's original filtered iteration stage."""
    resource_id = resource.get("id", {})
    if not isinstance(resource_id, dict):
        return None
    raw_path = resource_id.get("path", "")
    path = raw_path.replace("\\", "/") if isinstance(raw_path, str) else ""
    resource_type = resource.get("resourceType")
    id_resource_type = resource_id.get("resourceType")
    is_tileset = (
        path.partition("/")[0].casefold() == "tilesets"
        or resource_type == "GMTileSet"
        or id_resource_type == "GMTileSet"
    )
    if not is_tileset:
        return None
    raw_name = resource_id.get("name", "")
    name = (
        raw_name if isinstance(raw_name, str) and raw_name
        else os.path.splitext(os.path.basename(path))[0]
    )
    if not name:
        return None
    return TilesetResourceDeclaration(name, path, raw_path, resource, resource_id)


def capture_registry_resource_declaration(resource_id: JsonObject) -> RegistryResourceDeclaration | None:
    """Capture only an accepted path and then its optional declared name.

    The owner checks rejected manifest fields before invoking this capture;
    its own path-derived naming policy remains outside this pure view.
    """
    path = resource_id.get("path")
    if not isinstance(path, str) or not path:
        return None
    return RegistryResourceDeclaration(path, resource_id.get("name"), resource_id)


def capture_sprite_resource_declaration(resource: JsonObject) -> SpriteResourceDeclaration | None:
    """Keep sprite type hints, including declarations with unusable paths."""
    resource_id = resource.get("id", {})
    if not isinstance(resource_id, dict):
        return None
    path = resource_id.get("path", "")
    resource_type = resource.get("resourceType")
    id_resource_type = resource_id.get("resourceType")
    is_sprite = (
        isinstance(path, str) and path.replace("\\", "/").casefold().startswith("sprites/")
    ) or resource_type == "GMSprite" or id_resource_type == "GMSprite"
    if not is_sprite:
        return None
    raw_name = resource_id.get("name", "")
    name = raw_name if isinstance(raw_name, str) and raw_name else (
        os.path.splitext(os.path.basename(path))[0] if isinstance(path, str) else ""
    )
    if not name:
        return None
    return SpriteResourceDeclaration(name, path, resource, resource_id)


def capture_asset_name_declaration(resource: JsonValue) -> AssetNameDeclaration:
    """Read name-only declarations with the original object-access failures."""
    if not isinstance(resource, dict):
        raise AttributeError(
            f"'{type(resource).__name__}' object has no attribute 'get'", name="get", obj=resource
        )
    resource_id = resource.get("id", {})
    if not isinstance(resource_id, dict):
        raise AttributeError(
            f"'{type(resource_id).__name__}' object has no attribute 'get'", name="get", obj=resource_id
        )
    raw_name = resource_id.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name else None
    return AssetNameDeclaration(name, resource, resource_id)
