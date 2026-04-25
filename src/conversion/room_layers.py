import json
import re


KNOWN_LAYER_TYPES = {
    "GMRInstanceLayer",
    "GMRBackgroundLayer",
    "GMRTileLayer",
    "GMRAssetLayer",
    "GMREffectLayer",
}


def godot_string(value):
    """Format a Python value as a quoted Godot string literal."""
    return json.dumps(str(value))


def godot_value(value):
    """Format simple JSON-compatible values as Godot text-scene values."""
    return json.dumps(value)


def serialize_room_layers(room, warn_callback=None):
    """Serialize GameMaker room layers as Godot Node2D placeholders."""
    lines = []
    used_names = {}
    for layer in room.layers:
        _serialize_layer(layer, room.name, ".", used_names, lines, warn_callback)
    return lines


def _serialize_layer(layer, room_name, parent_path, sibling_names, lines, warn_callback):
    original_name = _layer_name(layer)
    node_name = _unique_name(_sanitize_node_name(original_name), sibling_names)
    resource_type = _layer_resource_type(layer)

    if resource_type not in KNOWN_LAYER_TYPES and warn_callback is not None:
        warn_callback(
            "Warning: Unsupported room layer type {resource_type} in room {room_name}, "
            "layer {layer_name}; emitted Node2D placeholder.".format(
                resource_type=resource_type,
                room_name=room_name,
                layer_name=original_name,
            )
        )

    lines.extend(_layer_node_lines(layer, node_name, parent_path, original_name, resource_type))

    child_parent_path = node_name if parent_path == "." else f"{parent_path}/{node_name}"
    child_names = {}
    for child_layer in _child_layers(layer):
        _serialize_layer(
            child_layer,
            room_name,
            child_parent_path,
            child_names,
            lines,
            warn_callback,
        )


def _layer_node_lines(layer, node_name, parent_path, original_name, resource_type):
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
        instances = layer.get("instances") or []
        lines.append(f"metadata/gamemaker_instance_count = {len(instances)}")
        lines.append(
            f"metadata/gamemaker_instance_names = {godot_value(_item_names(instances))}"
        )
    elif resource_type == "GMRAssetLayer":
        assets = layer.get("assets") or []
        lines.append(f"metadata/gamemaker_asset_count = {len(assets)}")
        lines.append(f"metadata/gamemaker_asset_names = {godot_value(_item_names(assets))}")
    elif resource_type == "GMRBackgroundLayer":
        sprite_id = layer.get("spriteId") or {}
        lines.append(
            f"metadata/gamemaker_background_sprite = {godot_value(sprite_id.get('name'))}"
        )
        for key in ("colour", "htiled", "vtiled", "hspeed", "vspeed", "stretch"):
            _append_optional_metadata(lines, layer, key, f"gamemaker_background_{key}")
    elif resource_type == "GMRTileLayer":
        tileset_id = layer.get("tilesetId") or {}
        tiles = layer.get("tiles") or {}
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


def _append_optional_metadata(lines, source, source_key, metadata_key):
    if source_key in source:
        lines.append(f"metadata/{metadata_key} = {godot_value(source.get(source_key))}")


def _layer_name(layer):
    return layer.get("%Name") or layer.get("name") or "Layer"


def _layer_resource_type(layer):
    resource_type = layer.get("resourceType")
    if resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _child_layers(layer):
    children = layer.get("layers") or layer.get("children") or []
    return children if isinstance(children, list) else []


def _item_names(items):
    names = []
    for item in items:
        if isinstance(item, dict):
            names.append(item.get("%Name") or item.get("name") or "")
    return [name for name in names if name]


def _coerce_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _sanitize_node_name(name):
    sanitized = str(name).replace("/", "_").replace('"', "_").replace("\\", "_")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "Layer"


def _unique_name(base_name, used_names):
    count = used_names.get(base_name, 0) + 1
    used_names[base_name] = count
    if count == 1:
        return base_name
    return f"{base_name}_{count}"
