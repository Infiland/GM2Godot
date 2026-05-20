from __future__ import annotations

import json
import os
import re
from typing import NamedTuple, Protocol, cast

from src.conversion.room_creation_code import resolve_instance_creation_code
from src.conversion.type_defs import JsonDict, JsonList, JsonValue, LogCallback


KNOWN_LAYER_TYPES = {
    "GMRInstanceLayer",
    "GMRBackgroundLayer",
    "GMRTileLayer",
    "GMRAssetLayer",
    "GMREffectLayer",
}

GAMEMAKER_EMPTY_TILE_SENTINEL = -2147483648
GAMEMAKER_TILE_INDEX_MASK = (1 << 19) - 1
GAMEMAKER_TILE_MIRROR_BIT = 1 << 28
GAMEMAKER_TILE_FLIP_BIT = 1 << 29
GAMEMAKER_TILE_ROTATE_BIT = 1 << 30

GODOT_TILE_TRANSFORM_FLIP_H = 1 << 12
GODOT_TILE_TRANSFORM_FLIP_V = 1 << 13
GODOT_TILE_TRANSFORM_TRANSPOSE = 1 << 14


class GameMakerTile(NamedTuple):
    raw_value: int
    tile_index: int
    mirror: bool
    flip: bool
    rotate: bool


class GodotTileCell(NamedTuple):
    x: int
    y: int
    source_id: int
    atlas_x: int
    atlas_y: int
    alternative_tile: int
    raw_value: int


class RoomLayerRoom(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def yy_path(self) -> str: ...

    @property
    def creation_code_file(self) -> str: ...

    @property
    def inherit_code(self) -> bool: ...

    @property
    def room_settings(self) -> JsonDict: ...

    @property
    def layers(self) -> JsonList: ...

    @property
    def instance_creation_order(self) -> JsonList: ...

    @property
    def view_settings(self) -> JsonDict: ...

    @property
    def views(self) -> JsonList: ...


class RoomLayerResourceIndex(Protocol):
    godot_project_path: str

    def resolve_gm_path(self, kind: str, name: str) -> str | None: ...

    def resolve_godot_path(self, kind: str, name: str) -> str | None: ...


def godot_string(value: JsonValue) -> str:
    """Format a Python value as a quoted Godot string literal."""
    return json.dumps(str(value))


def godot_value(value: JsonValue) -> str:
    """Format simple JSON-compatible values as Godot text-scene values."""
    return json.dumps(value)


class SerializedRoomLayers:
    def __init__(
        self, ext_resource_lines: list[str] | None = None, node_lines: list[str] | None = None
    ) -> None:
        self.ext_resource_lines = ext_resource_lines or []
        self.node_lines = node_lines or []


class RoomLayerSerializationContext:
    def __init__(
        self,
        room: RoomLayerRoom,
        gm_project_path: str | None = None,
        resource_index: RoomLayerResourceIndex | None = None,
        warn_callback: LogCallback | None = None,
    ) -> None:
        self.room = room
        self.gm_project_path = gm_project_path
        self.resource_index = resource_index
        self.warn_callback = warn_callback
        self.ext_resource_ids: dict[tuple[str, str], str] = {}
        self.creation_order = _instance_creation_order(room)

    def ext_resource_id(self, resource_type: str, resource_path: str) -> str:
        key = (resource_type, resource_path)
        if key not in self.ext_resource_ids:
            self.ext_resource_ids[key] = str(len(self.ext_resource_ids) + 1)
        return self.ext_resource_ids[key]

    def object_scene_ext_resource_id(self, object_name: str | None) -> str | None:
        scene_path = self.object_scene_path(object_name)
        if scene_path is None:
            return None
        return self.ext_resource_id("PackedScene", scene_path)

    def object_scene_path(self, object_name: str | None) -> str | None:
        if not object_name or self.resource_index is None:
            return None
        scene_path = self.resource_index.resolve_godot_path("objects", object_name)
        if scene_path is None:
            return None
        if not self._scene_path_exists(scene_path):
            return None
        return scene_path

    def sprite_scene_ext_resource_id(self, sprite_name: str | None) -> str | None:
        scene_path = self.sprite_scene_path(sprite_name)
        if scene_path is None:
            return None
        return self.ext_resource_id("PackedScene", scene_path)

    def sprite_scene_path(self, sprite_name: str | None) -> str | None:
        if not sprite_name or self.resource_index is None:
            return None
        scene_path = self.resource_index.resolve_godot_path("sprites", sprite_name)
        if scene_path is None:
            return None
        if not self._scene_path_exists(scene_path):
            return None
        return scene_path

    def tileset_ext_resource_id(self, tileset_name: str | None) -> str | None:
        tileset_path = self.tileset_path(tileset_name)
        if tileset_path is None:
            return None
        return self.ext_resource_id("TileSet", tileset_path)

    def tileset_path(self, tileset_name: str | None) -> str | None:
        if not tileset_name or self.resource_index is None:
            return None
        tileset_path = self.resource_index.resolve_godot_path("tilesets", tileset_name)
        if tileset_path is None:
            return None
        if not self._resource_path_exists(tileset_path):
            return None
        return tileset_path

    def warn(self, message: str) -> None:
        if self.warn_callback is not None:
            self.warn_callback(message)

    def ext_resource_lines(self) -> list[str]:
        return [
            '[ext_resource type="{resource_type}" path={path} id="{resource_id}"]'.format(
                resource_type=resource_type,
                path=godot_string(path),
                resource_id=resource_id,
            )
            for (resource_type, path), resource_id in self.ext_resource_ids.items()
        ]

    def _scene_path_exists(self, scene_path: str) -> bool:
        return self._resource_path_exists(scene_path)

    def _resource_path_exists(self, scene_path: str) -> bool:
        if not scene_path.startswith("res://"):
            return False
        relative_path = scene_path[len("res://"):]
        resource_index = self.resource_index
        if resource_index is None:
            return False
        filesystem_path = os.path.join(
            resource_index.godot_project_path,
            *relative_path.split("/"),
        )
        return os.path.isfile(filesystem_path)


def serialize_room_layers(
    room: RoomLayerRoom,
    gm_project_path: str | None = None,
    resource_index: RoomLayerResourceIndex | None = None,
    warn_callback: LogCallback | None = None,
) -> SerializedRoomLayers:
    """Serialize GameMaker room layers and supported layer children."""
    context = RoomLayerSerializationContext(room, gm_project_path, resource_index, warn_callback)
    node_lines: list[str] = []
    node_lines.extend(_camera_node_lines(context))
    used_names: dict[str, int] = {}
    for layer in room.layers:
        if isinstance(layer, dict):
            _serialize_layer(cast(JsonDict, layer), ".", used_names, node_lines, context)
    return SerializedRoomLayers(context.ext_resource_lines(), node_lines)


def _serialize_layer(
    layer: JsonDict,
    parent_path: str,
    sibling_names: dict[str, int],
    lines: list[str],
    context: RoomLayerSerializationContext,
) -> None:
    original_name = _layer_name(layer)
    node_name = _unique_name(_sanitize_node_name(original_name), sibling_names)
    resource_type = _layer_resource_type(layer)

    if resource_type not in KNOWN_LAYER_TYPES:
        context.warn(
            "Warning: Unsupported room layer type {resource_type} in room {room_name}, "
            "layer {layer_name}; emitted Node2D placeholder.".format(
                resource_type=resource_type,
                room_name=context.room.name,
                layer_name=original_name,
            )
        )

    lines.extend(_layer_node_lines(layer, node_name, parent_path, original_name, resource_type))

    child_parent_path = node_name if parent_path == "." else f"{parent_path}/{node_name}"

    if resource_type == "GMRBackgroundLayer":
        lines.extend(_background_visual_lines(layer, child_parent_path, original_name, context))

    if resource_type == "GMRInstanceLayer":
        lines.extend(_instance_node_lines(layer, child_parent_path, original_name, context))

    if resource_type == "GMRTileLayer":
        lines.extend(_tile_map_layer_lines(layer, child_parent_path, original_name, context))

    if resource_type == "GMRAssetLayer":
        lines.extend(_asset_node_lines(layer, child_parent_path, original_name, context))

    child_names: dict[str, int] = {}
    for child_layer in _child_layers(layer):
        _serialize_layer(
            child_layer,
            child_parent_path,
            child_names,
            lines,
            context,
        )


def _layer_node_lines(
    layer: JsonDict,
    node_name: str,
    parent_path: str,
    original_name: str,
    resource_type: str,
) -> list[str]:
    visible = bool(layer.get("visible", True))
    depth = _coerce_int(layer.get("depth", 0))
    z_index = -depth

    lines = [
        f'[node name={godot_string(node_name)} type="Node2D" parent={godot_string(parent_path)}]',
        f"visible = {godot_value(visible)}",
        f"z_index = {z_index}",
        f"metadata/gamemaker_layer_name = {godot_value(original_name)}",
        f"metadata/gamemaker_layer_node_name = {godot_value(node_name)}",
        f"metadata/gamemaker_layer_type = {godot_value(resource_type)}",
        f"metadata/gamemaker_layer_depth = {godot_value(depth)}",
        f"metadata/gamemaker_layer_visible = {godot_value(visible)}",
        f"metadata/gamemaker_layer_grid_x = {godot_value(layer.get('gridX'))}",
        f"metadata/gamemaker_layer_grid_y = {godot_value(layer.get('gridY'))}",
        f"metadata/gamemaker_layer_properties = {godot_value(layer.get('properties', []))}",
        "metadata/gamemaker_placeholder = true",
    ]

    _append_optional_metadata(lines, layer, "name", "gamemaker_layer_internal_name")
    _append_optional_metadata(lines, layer, "userdefinedDepth", "gamemaker_layer_userdefined_depth")
    _append_optional_metadata(lines, layer, "inheritVisibility", "gamemaker_layer_inherit_visibility")
    _append_optional_metadata(lines, layer, "inheritLayerDepth", "gamemaker_layer_inherit_layer_depth")
    _append_optional_metadata(lines, layer, "inheritLayerSettings", "gamemaker_layer_inherit_layer_settings")
    _append_optional_metadata(lines, layer, "inheritSubLayers", "gamemaker_layer_inherit_sub_layers")

    if resource_type == "GMREffectLayer":
        lines.append(
            f"metadata/gamemaker_layer_effect_type = {godot_value(layer.get('effectType'))}"
        )
        lines.append(
            f"metadata/gamemaker_layer_effect_properties = {godot_value(layer.get('properties', []))}"
        )

    if resource_type == "GMRInstanceLayer":
        instances = _dict_items(layer.get("instances"))
        lines.append(f"metadata/gamemaker_instance_count = {len(instances)}")
        lines.append(
            f"metadata/gamemaker_instance_names = {godot_value(_item_names(instances))}"
        )
    elif resource_type == "GMRAssetLayer":
        assets = _dict_items(layer.get("assets"))
        lines.append(f"metadata/gamemaker_asset_count = {len(assets)}")
        lines.append(f"metadata/gamemaker_asset_names = {godot_value(_item_names(assets))}")
    elif resource_type == "GMRBackgroundLayer":
        sprite_id = _dict_value(layer.get("spriteId"))
        lines.append(
            f"metadata/gamemaker_background_sprite = {godot_value(sprite_id.get('name'))}"
        )
        for key in ("colour", "htiled", "vtiled", "hspeed", "vspeed", "stretch"):
            _append_optional_metadata(lines, layer, key, f"gamemaker_background_{key}")
    elif resource_type == "GMRTileLayer":
        tileset_id = _dict_value(layer.get("tilesetId"))
        tiles = _dict_value(layer.get("tiles"))
        lines.append(f"metadata/gamemaker_tileset = {godot_value(tileset_id.get('name'))}")
        _append_optional_metadata(lines, tiles, "SerialiseWidth", "gamemaker_tile_serialise_width")
        _append_optional_metadata(lines, tiles, "SerialiseHeight", "gamemaker_tile_serialise_height")
        _append_optional_metadata(lines, tiles, "TileDataFormat", "gamemaker_tile_data_format")
        lines.append(
            "metadata/gamemaker_tile_compressed_data_count = {count}".format(
                count=len(tiles.get("TileCompressedData") or [])
            )
        )

    if resource_type not in KNOWN_LAYER_TYPES:
        lines.append("metadata/gamemaker_unsupported_layer = true")

    lines.append("")
    return lines


def _append_optional_metadata(
    lines: list[str], source: JsonDict, source_key: str, metadata_key: str
) -> None:
    if source_key in source:
        lines.append(f"metadata/{metadata_key} = {godot_value(source.get(source_key))}")


def decode_tile_compressed_data(
    serialise_width: int,
    serialise_height: int,
    compressed_data: list[JsonValue],
    tile_data_format: int = 1,
) -> list[int]:
    """Expand GameMaker TileCompressedData format 1 into a row-major cell array."""
    if tile_data_format != 1:
        raise ValueError(f"Unsupported GameMaker tile data format: {tile_data_format}")
    if serialise_width < 0 or serialise_height < 0:
        raise ValueError("GameMaker tile data dimensions must be non-negative")

    expected_length = serialise_width * serialise_height
    decoded: list[int] = []
    index = 0
    while index < len(compressed_data):
        value = _require_int(compressed_data[index], "TileCompressedData value")
        if value < 0 and value != GAMEMAKER_EMPTY_TILE_SENTINEL:
            if index + 1 >= len(compressed_data):
                raise ValueError("Malformed GameMaker tile data: repeated run has no value")
            repeat_value = _require_int(
                compressed_data[index + 1], "TileCompressedData repeated value"
            )
            decoded.extend([repeat_value] * -value)
            index += 2
        else:
            decoded.append(value)
            index += 1

        if len(decoded) > expected_length:
            raise ValueError(
                "Malformed GameMaker tile data: decoded {actual} cells, expected {expected}".format(
                    actual=len(decoded),
                    expected=expected_length,
                )
            )

    if len(decoded) != expected_length:
        raise ValueError(
            "Malformed GameMaker tile data: decoded {actual} cells, expected {expected}".format(
                actual=len(decoded),
                expected=expected_length,
            )
        )
    return decoded


def is_empty_gamemaker_tile(raw_value: int) -> bool:
    if raw_value == GAMEMAKER_EMPTY_TILE_SENTINEL:
        return True
    return decode_gamemaker_tile(raw_value).tile_index == 0


def decode_gamemaker_tile(raw_value: int) -> GameMakerTile:
    unsigned_value = raw_value & 0xFFFFFFFF
    return GameMakerTile(
        raw_value=raw_value,
        tile_index=unsigned_value & GAMEMAKER_TILE_INDEX_MASK,
        mirror=bool(unsigned_value & GAMEMAKER_TILE_MIRROR_BIT),
        flip=bool(unsigned_value & GAMEMAKER_TILE_FLIP_BIT),
        rotate=bool(unsigned_value & GAMEMAKER_TILE_ROTATE_BIT),
    )


def _tile_map_layer_lines(
    layer: JsonDict,
    parent_path: str,
    layer_name: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    tileset_id = _dict_value(layer.get("tilesetId"))
    raw_tileset_name = tileset_id.get("name")
    tileset_name = raw_tileset_name if isinstance(raw_tileset_name, str) else None
    ext_resource_id = context.tileset_ext_resource_id(tileset_name)
    if ext_resource_id is None:
        context.warn(
            "Warning: Could not resolve TileSet resource for GameMaker tile layer "
            "{layer_name} in room {room_name}, tileset {tileset_name}; no TileMapLayer emitted.".format(
                layer_name=layer_name,
                room_name=context.room.name,
                tileset_name=tileset_name or "<missing>",
            )
        )
        return []

    tiles = _dict_value(layer.get("tiles"))
    width = _coerce_int(tiles.get("SerialiseWidth", 0))
    height = _coerce_int(tiles.get("SerialiseHeight", 0))
    tile_data_format = _coerce_int(tiles.get("TileDataFormat", 1))
    raw_compressed_data = tiles.get("TileCompressedData")
    compressed_data: list[JsonValue] = []
    if isinstance(raw_compressed_data, list):
        compressed_data = cast(list[JsonValue], raw_compressed_data)

    try:
        decoded_tiles = decode_tile_compressed_data(
            width,
            height,
            compressed_data,
            tile_data_format,
        )
    except ValueError as error:
        context.warn(
            "Warning: Could not decode GameMaker tile data for room {room_name}, "
            "layer {layer_name}: {error}".format(
                room_name=context.room.name,
                layer_name=layer_name,
                error=error,
            )
        )
        return []

    layout = _tileset_layout(context, tileset_name)
    columns = _tileset_columns(layout, decoded_tiles)
    cells = _godot_tile_cells(decoded_tiles, width, columns)
    tile_map_data = _format_godot_tile_map_data(cells)
    transform_count = sum(
        1 for cell in cells if decode_gamemaker_tile(cell.raw_value).mirror
        or decode_gamemaker_tile(cell.raw_value).flip
        or decode_gamemaker_tile(cell.raw_value).rotate
    )

    if transform_count:
        context.warn(
            "Warning: GameMaker tile layer {layer_name} in room {room_name} uses "
            "tile transform flags; mapped mirror/flip/rotate to Godot TileMapLayer alternative bits.".format(
                layer_name=layer_name,
                room_name=context.room.name,
            )
        )

    lines = [
        f'[node name="TileMap" type="TileMapLayer" parent={godot_string(parent_path)}]',
        f"visible = {godot_value(bool(layer.get('visible', True)))}",
        "position = Vector2({x}, {y})".format(
            x=_format_number(layer.get("x", 0)),
            y=_format_number(layer.get("y", 0)),
        ),
        f'tile_set = ExtResource("{ext_resource_id}")',
    ]
    if tile_map_data:
        lines.append(f"tile_map_data = {tile_map_data}")
    lines.extend([
        "metadata/gamemaker_tile_layer = true",
        f"metadata/gamemaker_tileset = {godot_value(tileset_name)}",
        f"metadata/gamemaker_tile_width = {godot_value(width)}",
        f"metadata/gamemaker_tile_height = {godot_value(height)}",
        f"metadata/gamemaker_tile_data_format = {godot_value(tile_data_format)}",
        f"metadata/gamemaker_tile_decoded_cell_count = {godot_value(len(decoded_tiles))}",
        f"metadata/gamemaker_tile_non_empty_cell_count = {godot_value(len(cells))}",
        f"metadata/gamemaker_tile_transform_cell_count = {godot_value(transform_count)}",
        f"metadata/gamemaker_tile_empty_values = {godot_value([0, GAMEMAKER_EMPTY_TILE_SENTINEL])}",
    ])
    lines.append("")
    return lines


def _tileset_layout(
    context: RoomLayerSerializationContext, tileset_name: str | None
) -> JsonDict:
    if not tileset_name or context.resource_index is None:
        return {}
    tileset_path = context.resource_index.resolve_gm_path("tilesets", tileset_name)
    if tileset_path is None:
        return {}
    data = _read_yy_json(tileset_path)
    return data or {}


def _tileset_columns(layout: JsonDict, decoded_tiles: list[int]) -> int:
    columns = _coerce_int(layout.get("out_columns", 0))
    if columns > 0:
        return columns
    tile_count = _coerce_int(layout.get("tile_count", 0))
    if tile_count > 0:
        return tile_count
    max_index = max((decode_gamemaker_tile(value).tile_index for value in decoded_tiles), default=1)
    return max(1, max_index)


def _godot_tile_cells(
    decoded_tiles: list[int], width: int, columns: int
) -> list[GodotTileCell]:
    cells: list[GodotTileCell] = []
    if width <= 0 or columns <= 0:
        return cells
    for index, raw_tile in enumerate(decoded_tiles):
        if is_empty_gamemaker_tile(raw_tile):
            continue
        tile = decode_gamemaker_tile(raw_tile)
        atlas_index = max(0, tile.tile_index - 1)
        alternative_tile = 0
        if tile.mirror:
            alternative_tile |= GODOT_TILE_TRANSFORM_FLIP_H
        if tile.flip:
            alternative_tile |= GODOT_TILE_TRANSFORM_FLIP_V
        if tile.rotate:
            alternative_tile |= GODOT_TILE_TRANSFORM_TRANSPOSE
        cells.append(
            GodotTileCell(
                x=index % width,
                y=index // width,
                source_id=0,
                atlas_x=atlas_index % columns,
                atlas_y=atlas_index // columns,
                alternative_tile=alternative_tile,
                raw_value=raw_tile,
            )
        )
    return cells


def _format_godot_tile_map_data(cells: list[GodotTileCell]) -> str:
    if not cells:
        return ""
    data: list[int] = [0, 0]
    for cell in cells:
        for value in (
            cell.x,
            cell.y,
            cell.source_id,
            cell.atlas_x,
            cell.atlas_y,
            cell.alternative_tile,
        ):
            data.extend(_encode_uint16(value))
    return "PackedByteArray({values})".format(values=", ".join(str(value) for value in data))


def _encode_uint16(value: int) -> list[int]:
    unsigned = value & 0xFFFF
    return [unsigned & 0xFF, (unsigned >> 8) & 0xFF]


def _read_yy_json(path: str) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        cleaned = re.sub(r",\s*([}\]])", r"\1", content)
        data = json.loads(cleaned)
    except (OSError, json.JSONDecodeError):
        return None
    return cast(JsonDict, data) if isinstance(data, dict) else None


def _asset_node_lines(
    layer: JsonDict,
    parent_path: str,
    layer_name: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    lines: list[str] = []
    sibling_names: dict[str, int] = {}
    for asset in _dict_items(layer.get("assets")):
        asset_name = _asset_name(asset)
        if asset.get("ignore") is True:
            context.warn(
                "Warning: Skipping ignored GameMaker asset {asset_name} in room {room_name}, "
                "layer {layer_name}.".format(
                    asset_name=asset_name,
                    room_name=context.room.name,
                    layer_name=layer_name,
                )
            )
            continue

        node_name = _unique_name(_sanitize_node_name(asset_name), sibling_names)
        asset_type = _asset_resource_type(asset)
        if asset_type == "GMRSpriteGraphic":
            lines.extend(_sprite_asset_lines(asset, node_name, parent_path, layer_name, context))
        else:
            context.warn(
                "Warning: Unsupported GameMaker room asset type {asset_type} in room {room_name}, "
                "layer {layer_name}, asset {asset_name}; emitted Node2D placeholder.".format(
                    asset_type=asset_type,
                    room_name=context.room.name,
                    layer_name=layer_name,
                    asset_name=asset_name,
                )
            )
            lines.extend(_unsupported_asset_lines(asset, node_name, parent_path, asset_type))
    return lines


def _sprite_asset_lines(
    asset: JsonDict,
    node_name: str,
    parent_path: str,
    layer_name: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    sprite_id = _dict_value(asset.get("spriteId"))
    raw_sprite_name = sprite_id.get("name")
    sprite_name = raw_sprite_name if isinstance(raw_sprite_name, str) else None
    ext_resource_id = context.sprite_scene_ext_resource_id(sprite_name)
    if ext_resource_id is None:
        context.warn(
            "Warning: Could not resolve sprite scene for GameMaker room asset {asset_name} "
            "in room {room_name}, layer {layer_name}, sprite {sprite_name}; emitted Node2D placeholder.".format(
                asset_name=_asset_name(asset),
                room_name=context.room.name,
                layer_name=layer_name,
                sprite_name=sprite_name or "<missing>",
            )
        )
        lines = [f'[node name={godot_string(node_name)} type="Node2D" parent={godot_string(parent_path)}]']
    else:
        lines = [
            '[node name={name} parent={parent} instance=ExtResource("{resource_id}")]'.format(
                name=godot_string(node_name),
                parent=godot_string(parent_path),
                resource_id=ext_resource_id,
            )
        ]

    lines.extend(_asset_transform_lines(asset))
    lines.extend([
        f"metadata/gamemaker_asset_name = {godot_value(_asset_name(asset))}",
        f"metadata/gamemaker_asset_node_name = {godot_value(node_name)}",
        f"metadata/gamemaker_asset_type = {godot_value(_asset_resource_type(asset))}",
        f"metadata/gamemaker_asset_sprite_name = {godot_value(sprite_name)}",
        f"metadata/gamemaker_asset_sprite_id = {godot_value(asset.get('spriteId'))}",
        f"metadata/gamemaker_asset_colour = {godot_value(asset.get('colour'))}",
        f"metadata/gamemaker_asset_head_position = {godot_value(asset.get('headPosition'))}",
        f"metadata/gamemaker_asset_animation_speed = {godot_value(asset.get('animationSpeed'))}",
        f"metadata/gamemaker_asset_animation_fps = {godot_value(asset.get('animationFPS'))}",
        f"metadata/gamemaker_asset_animation_speed_type = {godot_value(asset.get('animationSpeedType'))}",
        f"metadata/gamemaker_asset_properties = {godot_value(asset.get('properties', []))}",
        f"metadata/gamemaker_asset_inherited_item_id = {godot_value(asset.get('inheritedItemId'))}",
        f"metadata/gamemaker_asset_inherit_item_settings = {godot_value(bool(asset.get('inheritItemSettings', False)))}",
    ])
    if ext_resource_id is None:
        lines.append("metadata/gamemaker_placeholder = true")
        lines.append("metadata/gamemaker_unresolved_sprite_scene = true")
    lines.append("")
    return lines


def _unsupported_asset_lines(
    asset: JsonDict, node_name: str, parent_path: str, asset_type: str
) -> list[str]:
    lines = [f'[node name={godot_string(node_name)} type="Node2D" parent={godot_string(parent_path)}]']
    lines.extend(_asset_transform_lines(asset))
    lines.extend([
        f"metadata/gamemaker_asset_name = {godot_value(_asset_name(asset))}",
        f"metadata/gamemaker_asset_node_name = {godot_value(node_name)}",
        f"metadata/gamemaker_asset_type = {godot_value(asset_type)}",
        f"metadata/gamemaker_asset_raw = {godot_value(asset)}",
        "metadata/gamemaker_placeholder = true",
        "metadata/gamemaker_unsupported_asset = true",
        "",
    ])
    return lines


def _asset_transform_lines(asset: JsonDict) -> list[str]:
    return [
        "position = Vector2({x}, {y})".format(
            x=_format_number(asset.get("x", 0)),
            y=_format_number(asset.get("y", 0)),
        ),
        "rotation_degrees = {rotation}".format(
            rotation=_format_number(asset.get("rotation", 0))
        ),
        "scale = Vector2({scale_x}, {scale_y})".format(
            scale_x=_format_number(asset.get("scaleX", 1)),
            scale_y=_format_number(asset.get("scaleY", 1)),
        ),
        "modulate = {color}".format(color=_godot_color(asset.get("colour", 4294967295))),
    ]


def _camera_node_lines(context: RoomLayerSerializationContext) -> list[str]:
    if not bool(context.room.view_settings.get("enableViews", False)):
        return []

    views = [view for view in _dict_items(context.room.views) if bool(view.get("visible", False))]
    if not views:
        return []
    if len(views) > 1:
        context.warn(
            "Warning: Room {room_name} has multiple visible GameMaker views; only the first "
            "Camera2D is enabled, additional views are preserved as disabled cameras with metadata.".format(
                room_name=context.room.name,
            )
        )

    lines: list[str] = []
    sibling_names: dict[str, int] = {}
    for visible_index, view in enumerate(views):
        node_name = _unique_name("ViewCamera", sibling_names)
        xview = _coerce_float(view.get("xview", 0))
        yview = _coerce_float(view.get("yview", 0))
        wview = _coerce_float(view.get("wview", 0))
        hview = _coerce_float(view.get("hview", 0))
        xport = _coerce_float(view.get("xport", 0))
        yport = _coerce_float(view.get("yport", 0))
        wport = _coerce_float(view.get("wport", 0))
        hport = _coerce_float(view.get("hport", 0))
        object_id = _dict_value(view.get("objectId"))
        object_name = object_id.get("name") if isinstance(object_id.get("name"), str) else None

        if object_name:
            context.warn(
                "Warning: GameMaker view in room {room_name} follows object {object_name}; "
                "follow behavior is preserved as Camera2D metadata for runtime support.".format(
                    room_name=context.room.name,
                    object_name=object_name,
                )
            )

        lines.extend([
            f'[node name={godot_string(node_name)} type="Camera2D" parent="."]',
            "position = Vector2({x}, {y})".format(
                x=_format_number(xview + (wview / 2)),
                y=_format_number(yview + (hview / 2)),
            ),
            f"enabled = {godot_value(visible_index == 0)}",
            f"limit_left = {_format_number(xview)}",
            f"limit_top = {_format_number(yview)}",
            f"limit_right = {_format_number(xview + wview)}",
            f"limit_bottom = {_format_number(yview + hview)}",
        ])
        if wview > 0 and hview > 0 and wport > 0 and hport > 0:
            lines.append(
                "zoom = Vector2({x}, {y})".format(
                    x=_format_number(wport / wview),
                    y=_format_number(hport / hview),
                )
            )
        lines.extend([
            f"metadata/gamemaker_view_camera = {godot_value(True)}",
            f"metadata/gamemaker_view_enabled_camera = {godot_value(visible_index == 0)}",
            f"metadata/gamemaker_view_index = {godot_value(visible_index)}",
            f"metadata/gamemaker_view_xview = {godot_value(view.get('xview'))}",
            f"metadata/gamemaker_view_yview = {godot_value(view.get('yview'))}",
            f"metadata/gamemaker_view_wview = {godot_value(view.get('wview'))}",
            f"metadata/gamemaker_view_hview = {godot_value(view.get('hview'))}",
            f"metadata/gamemaker_view_xport = {godot_value(xport)}",
            f"metadata/gamemaker_view_yport = {godot_value(yport)}",
            f"metadata/gamemaker_view_wport = {godot_value(wport)}",
            f"metadata/gamemaker_view_hport = {godot_value(hport)}",
            f"metadata/gamemaker_view_object_name = {godot_value(object_name)}",
            f"metadata/gamemaker_view_object_id = {godot_value(view.get('objectId'))}",
            f"metadata/gamemaker_view_hborder = {godot_value(view.get('hborder'))}",
            f"metadata/gamemaker_view_vborder = {godot_value(view.get('vborder'))}",
            f"metadata/gamemaker_view_hspeed = {godot_value(view.get('hspeed'))}",
            f"metadata/gamemaker_view_vspeed = {godot_value(view.get('vspeed'))}",
            "",
        ])
    return lines


def _background_visual_lines(
    layer: JsonDict,
    parent_path: str,
    layer_name: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    sprite_name = _background_sprite_name(layer)
    if sprite_name:
        ext_resource_id = context.sprite_scene_ext_resource_id(sprite_name)
        if ext_resource_id is None:
            context.warn(
                "Warning: Could not resolve sprite scene for GameMaker background layer "
                "{layer_name} in room {room_name}, sprite {sprite_name}; no visual child emitted.".format(
                    layer_name=layer_name,
                    room_name=context.room.name,
                    sprite_name=sprite_name,
                )
            )
            return []
        return _background_sprite_lines(layer, parent_path, sprite_name, ext_resource_id, context)

    return _background_color_lines(layer, parent_path, context)


def _background_color_lines(
    layer: JsonDict, parent_path: str, context: RoomLayerSerializationContext
) -> list[str]:
    width, height = _room_size(context)
    lines = [
        f'[node name="BackgroundVisual" type="ColorRect" parent={godot_string(parent_path)}]',
        f"visible = {godot_value(bool(layer.get('visible', True)))}",
        "position = Vector2({x}, {y})".format(
            x=_format_number(layer.get("x", 0)),
            y=_format_number(layer.get("y", 0)),
        ),
        "size = Vector2({width}, {height})".format(
            width=_format_number(width),
            height=_format_number(height),
        ),
        "color = {color}".format(color=_godot_color(layer.get("colour", 4278190080))),
    ]
    lines.extend(_background_metadata_lines(layer, "color"))
    _warn_background_runtime_requirements(layer, context)
    lines.append("")
    return lines


def _background_sprite_lines(
    layer: JsonDict,
    parent_path: str,
    sprite_name: str,
    ext_resource_id: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    node_name = _sanitize_node_name(sprite_name) or "BackgroundSprite"
    lines = [
        '[node name={name} parent={parent} instance=ExtResource("{resource_id}")]'.format(
            name=godot_string(node_name),
            parent=godot_string(parent_path),
            resource_id=ext_resource_id,
        ),
        f"visible = {godot_value(bool(layer.get('visible', True)))}",
        "position = Vector2({x}, {y})".format(
            x=_format_number(layer.get("x", 0)),
            y=_format_number(layer.get("y", 0)),
        ),
        "modulate = {color}".format(color=_godot_color(layer.get("colour", 4294967295))),
    ]
    lines.extend(_background_metadata_lines(layer, "sprite"))
    _warn_background_runtime_requirements(layer, context)
    lines.append("")
    return lines


def _background_metadata_lines(layer: JsonDict, visual_type: str) -> list[str]:
    colour = layer.get("colour")
    lines = [
        "metadata/gamemaker_background_visual = true",
        f"metadata/gamemaker_background_visual_type = {godot_value(visual_type)}",
        f"metadata/gamemaker_background_sprite = {godot_value(_background_sprite_name(layer))}",
        f"metadata/gamemaker_background_colour = {godot_value(colour)}",
        f"metadata/gamemaker_background_colour_rgba = {godot_value(_decode_gamemaker_colour(colour))}",
    ]
    for source_key, metadata_key in (
        ("x", "gamemaker_background_x"),
        ("y", "gamemaker_background_y"),
        ("stretch", "gamemaker_background_stretch"),
        ("htiled", "gamemaker_background_htiled"),
        ("vtiled", "gamemaker_background_vtiled"),
        ("hspeed", "gamemaker_background_hspeed"),
        ("vspeed", "gamemaker_background_vspeed"),
        ("animationFPS", "gamemaker_background_animation_fps"),
        ("animationSpeedType", "gamemaker_background_animation_speed_type"),
        ("userdefinedAnimFPS", "gamemaker_background_userdefined_anim_fps"),
    ):
        _append_optional_metadata(lines, layer, source_key, metadata_key)
    return lines


def _warn_background_runtime_requirements(
    layer: JsonDict, context: RoomLayerSerializationContext
) -> None:
    if not (_truthy(layer.get("htiled")) or _truthy(layer.get("vtiled"))
            or _nonzero(layer.get("hspeed")) or _nonzero(layer.get("vspeed"))):
        return
    context.warn(
        "Warning: GameMaker background layer {layer_name} in room {room_name} uses "
        "scrolling/tiling; runtime support is required for hspeed/vspeed/htiled/vtiled.".format(
            layer_name=_layer_name(layer),
            room_name=context.room.name,
        )
    )


def _background_sprite_name(layer: JsonDict) -> str | None:
    sprite_id = _dict_value(layer.get("spriteId"))
    name = sprite_id.get("name")
    return name if isinstance(name, str) else None


def _room_size(context: RoomLayerSerializationContext) -> tuple[JsonValue, JsonValue]:
    settings = context.room.room_settings or {}
    return settings.get("Width", 1024), settings.get("Height", 768)


def _godot_color(value: JsonValue) -> str:
    r, g, b, a = _decode_gamemaker_colour(value)
    return "Color({r}, {g}, {b}, {a})".format(
        r=_format_color_component(r),
        g=_format_color_component(g),
        b=_format_color_component(b),
        a=_format_color_component(a),
    )


def _decode_gamemaker_colour(value: JsonValue) -> list[float]:
    try:
        packed = int(value)
    except (TypeError, ValueError):
        packed = 4278190080
    packed = packed & 0xFFFFFFFF
    return [
        (packed & 0xFF) / 255.0,
        ((packed >> 8) & 0xFF) / 255.0,
        ((packed >> 16) & 0xFF) / 255.0,
        ((packed >> 24) & 0xFF) / 255.0,
    ]


def _gamemaker_colour_blend(value: JsonValue) -> int:
    try:
        packed = int(value)
    except (TypeError, ValueError):
        return 0xFFFFFF
    return packed & 0xFFFFFF


def _gamemaker_colour_alpha(value: JsonValue) -> float:
    try:
        packed = int(value)
    except (TypeError, ValueError):
        return 1.0
    packed = packed & 0xFFFFFFFF
    if packed <= 0xFFFFFF:
        return 1.0
    return ((packed >> 24) & 0xFF) / 255.0


def _format_color_component(value: float) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    return ("{:.6f}".format(value)).rstrip("0").rstrip(".")


def _instance_node_lines(
    layer: JsonDict,
    parent_path: str,
    layer_name: str,
    context: RoomLayerSerializationContext,
) -> list[str]:
    lines: list[str] = []
    instances = _dict_items(layer.get("instances"))
    ordered_instances = _ordered_instances(instances, context.creation_order)
    sibling_names: dict[str, int] = {}
    for instance, order_index, _original_index in ordered_instances:
        instance_name = _instance_name(instance)
        object_id = _dict_value(instance.get("objectId"))
        raw_object_name = object_id.get("name")
        object_name = raw_object_name if isinstance(raw_object_name, str) else None

        if instance.get("ignore") is True:
            context.warn(
                "Warning: Skipping ignored GameMaker room instance {instance_name} "
                "in room {room_name}, layer {layer_name}.".format(
                    instance_name=instance_name,
                    room_name=context.room.name,
                    layer_name=layer_name,
                )
            )
            continue

        node_name = _unique_name(_sanitize_node_name(instance_name), sibling_names)
        ext_resource_id = context.object_scene_ext_resource_id(object_name)
        if ext_resource_id is None:
            context.warn(
                "Warning: Could not resolve object scene for GameMaker room instance "
                "{instance_name} in room {room_name}, layer {layer_name}, object {object_name}; "
                "emitted Node2D placeholder.".format(
                    instance_name=instance_name,
                    room_name=context.room.name,
                    layer_name=layer_name,
                    object_name=object_name or "<missing>",
                )
            )

        lines.extend(
            _instance_scene_lines(
                instance,
                node_name,
                parent_path,
                instance_name,
                object_name,
                ext_resource_id,
                order_index,
                context,
            )
        )
    return lines


def _instance_scene_lines(
    instance: JsonDict,
    node_name: str,
    parent_path: str,
    instance_name: str,
    object_name: str | None,
    ext_resource_id: str | None,
    order_index: int | None,
    context: RoomLayerSerializationContext,
) -> list[str]:
    creation_code = resolve_instance_creation_code(
        context.room,
        instance,
        warn_callback=context.warn,
    )
    if ext_resource_id is None:
        lines = [f'[node name={godot_string(node_name)} type="Node2D" parent={godot_string(parent_path)}]']
    else:
        lines = [
            '[node name={name} parent={parent} instance=ExtResource("{resource_id}")]'.format(
                name=godot_string(node_name),
                parent=godot_string(parent_path),
                resource_id=ext_resource_id,
            )
        ]

    lines.extend([
        "position = Vector2({x}, {y})".format(
            x=_format_number(instance.get("x", 0)),
            y=_format_number(instance.get("y", 0)),
        ),
        "rotation_degrees = {rotation}".format(
            rotation=_format_number(instance.get("rotation", 0))
        ),
        "scale = Vector2({scale_x}, {scale_y})".format(
            scale_x=_format_number(instance.get("scaleX", 1)),
            scale_y=_format_number(instance.get("scaleY", 1)),
        ),
        f"metadata/gamemaker_instance_name = {godot_value(instance_name)}",
        f"metadata/gamemaker_instance_node_name = {godot_value(node_name)}",
        f"metadata/gamemaker_instance_object_name = {godot_value(object_name)}",
        f"metadata/gamemaker_instance_creation_order_index = {godot_value(order_index)}",
        f"metadata/gamemaker_instance_ignored = {godot_value(bool(instance.get('ignore', False)))}",
        f"metadata/gamemaker_instance_x = {godot_value(instance.get('x', 0))}",
        f"metadata/gamemaker_instance_y = {godot_value(instance.get('y', 0))}",
        f"metadata/gamemaker_instance_rotation = {godot_value(instance.get('rotation', 0))}",
        f"metadata/gamemaker_instance_scale_x = {godot_value(instance.get('scaleX', 1))}",
        f"metadata/gamemaker_instance_scale_y = {godot_value(instance.get('scaleY', 1))}",
        f"metadata/gamemaker_colour = {godot_value(instance.get('colour'))}",
        f"metadata/gamemaker_image_angle = {godot_value(instance.get('rotation', 0))}",
        f"metadata/gamemaker_image_xscale = {godot_value(instance.get('scaleX', 1))}",
        f"metadata/gamemaker_image_yscale = {godot_value(instance.get('scaleY', 1))}",
        f"metadata/gamemaker_image_blend = {godot_value(_gamemaker_colour_blend(instance.get('colour')))}",
        f"metadata/gamemaker_image_alpha = {godot_value(_gamemaker_colour_alpha(instance.get('colour')))}",
        f"metadata/gamemaker_image_index = {godot_value(instance.get('imageIndex'))}",
        f"metadata/gamemaker_image_speed = {godot_value(instance.get('imageSpeed'))}",
        f"metadata/gamemaker_object_id = {godot_value(instance.get('objectId'))}",
        f"metadata/gamemaker_properties = {godot_value(instance.get('properties', []))}",
        f"metadata/gamemaker_has_creation_code = {godot_value(creation_code.has_code)}",
        f"metadata/gamemaker_inherit_code = {godot_value(creation_code.inherit_code)}",
        f"metadata/gamemaker_is_dnd = {godot_value(creation_code.is_dnd)}",
        f"metadata/gamemaker_creation_code_source_path = {godot_value(creation_code.source_path)}",
        f"metadata/gamemaker_creation_code_file_exists = {godot_value(creation_code.exists)}",
        f"metadata/gamemaker_creation_code_execution_phase = {godot_value(creation_code.execution_phase)}",
        f"metadata/gamemaker_creation_code_execution_phase_index = {godot_value(creation_code.execution_phase_index)}",
    ])

    if ext_resource_id is None:
        lines.append("metadata/gamemaker_placeholder = true")
        lines.append("metadata/gamemaker_unresolved_object_scene = true")

    lines.append("")
    return lines


def _ordered_instances(
    instances: list[JsonDict], creation_order: dict[str, int]
) -> list[tuple[JsonDict, int | None, int]]:
    indexed: list[tuple[int, int, JsonDict, int | None]] = []
    for original_index, instance in enumerate(instances):
        order_index = creation_order.get(_instance_name(instance))
        sort_order = order_index if order_index is not None else len(creation_order) + original_index
        indexed.append((sort_order, original_index, instance, order_index))
    indexed.sort(key=lambda item: (item[0], item[1]))
    return [(instance, order_index, original_index) for _sort, original_index, instance, order_index in indexed]


def _instance_creation_order(room: RoomLayerRoom) -> dict[str, int]:
    order: dict[str, int] = {}
    for index, entry in enumerate(room.instance_creation_order):
        if not isinstance(entry, dict):
            continue
        entry_dict = cast(JsonDict, entry)
        name = entry_dict.get("%Name") or entry_dict.get("name")
        if isinstance(name, str) and name and name not in order:
            order[name] = index
    return order


def _instance_name(instance: JsonDict) -> str:
    name = instance.get("%Name") or instance.get("name")
    return name if isinstance(name, str) and name else "Instance"


def _asset_name(asset: JsonDict) -> str:
    name = asset.get("%Name") or asset.get("name")
    if isinstance(name, str) and name:
        return name
    sprite_id = _dict_value(asset.get("spriteId"))
    sprite_name = sprite_id.get("name")
    return sprite_name if isinstance(sprite_name, str) and sprite_name else "Asset"


def _asset_resource_type(asset: JsonDict) -> str:
    resource_type = asset.get("resourceType")
    if isinstance(resource_type, str) and resource_type:
        return resource_type
    for key in asset:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownAsset"


def _layer_name(layer: JsonDict) -> str:
    name = layer.get("%Name") or layer.get("name")
    return name if isinstance(name, str) and name else "Layer"


def _layer_resource_type(layer: JsonDict) -> str:
    resource_type = layer.get("resourceType")
    if resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _child_layers(layer: JsonDict) -> list[JsonDict]:
    children: JsonValue = layer.get("layers") or layer.get("children") or []
    return _dict_items(children)


def _item_names(items: list[JsonDict]) -> list[str]:
    names: list[str] = []
    for item in items:
        name = item.get("%Name") or item.get("name") or ""
        if isinstance(name, str):
            names.append(name)
    return [name for name in names if name]


def _coerce_int(value: JsonValue) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _require_int(value: JsonValue, label: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer") from None


def _coerce_float(value: JsonValue) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _format_number(value: JsonValue) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if number.is_integer():
        return str(int(number))
    return str(number)


def _truthy(value: JsonValue) -> bool:
    return bool(value)


def _nonzero(value: JsonValue) -> bool:
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return False


def _sanitize_node_name(name: JsonValue) -> str:
    sanitized = str(name).replace("/", "_").replace('"', "_").replace("\\", "_")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "Layer"


def _unique_name(base_name: str, used_names: dict[str, int]) -> str:
    count = used_names.get(base_name, 0) + 1
    used_names[base_name] = count
    if count == 1:
        return base_name
    return f"{base_name}_{count}"


def _dict_value(value: JsonValue) -> JsonDict:
    return cast(JsonDict, value) if isinstance(value, dict) else {}


def _dict_items(value: JsonValue) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    items = cast(list[JsonValue], value)
    return [cast(JsonDict, item) for item in items if isinstance(item, dict)]
