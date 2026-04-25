import json
import os
import re
from dataclasses import dataclass, field


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


@dataclass
class SerializedRoomLayers:
    ext_resource_lines: list = field(default_factory=list)
    node_lines: list = field(default_factory=list)


class RoomLayerSerializationContext:
    def __init__(self, room, resource_index=None, warn_callback=None):
        self.room = room
        self.resource_index = resource_index
        self.warn_callback = warn_callback
        self.ext_resource_ids = {}
        self.creation_order = _instance_creation_order(room)

    def object_scene_ext_resource_id(self, object_name):
        scene_path = self.object_scene_path(object_name)
        if scene_path is None:
            return None
        if scene_path not in self.ext_resource_ids:
            self.ext_resource_ids[scene_path] = str(len(self.ext_resource_ids) + 1)
        return self.ext_resource_ids[scene_path]

    def object_scene_path(self, object_name):
        if not object_name or self.resource_index is None:
            return None
        scene_path = self.resource_index.resolve_godot_path("objects", object_name)
        if scene_path is None:
            return None
        if not self._scene_path_exists(scene_path):
            return None
        return scene_path

    def warn(self, message):
        if self.warn_callback is not None:
            self.warn_callback(message)

    def ext_resource_lines(self):
        return [
            '[ext_resource type="PackedScene" path={path} id="{resource_id}"]'.format(
                path=godot_string(path),
                resource_id=resource_id,
            )
            for path, resource_id in self.ext_resource_ids.items()
        ]

    def _scene_path_exists(self, scene_path):
        if not scene_path.startswith("res://"):
            return False
        relative_path = scene_path[len("res://"):]
        filesystem_path = os.path.join(
            self.resource_index.godot_project_path,
            *relative_path.split("/"),
        )
        return os.path.isfile(filesystem_path)


def serialize_room_layers(room, resource_index=None, warn_callback=None):
    """Serialize GameMaker room layers and supported layer children."""
    context = RoomLayerSerializationContext(room, resource_index, warn_callback)
    node_lines = []
    used_names = {}
    for layer in room.layers:
        _serialize_layer(layer, ".", used_names, node_lines, context)
    return SerializedRoomLayers(context.ext_resource_lines(), node_lines)


def _serialize_layer(layer, parent_path, sibling_names, lines, context):
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

    if resource_type == "GMRInstanceLayer":
        lines.extend(_instance_node_lines(layer, child_parent_path, original_name, context))

    child_names = {}
    for child_layer in _child_layers(layer):
        _serialize_layer(
            child_layer,
            child_parent_path,
            child_names,
            lines,
            context,
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


def _instance_node_lines(layer, parent_path, layer_name, context):
    lines = []
    instances = layer.get("instances") or []
    ordered_instances = _ordered_instances(instances, context.creation_order)
    sibling_names = {}
    for instance, order_index, _original_index in ordered_instances:
        instance_name = _instance_name(instance)
        object_id = instance.get("objectId") or {}
        object_name = object_id.get("name")

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
            )
        )
    return lines


def _instance_scene_lines(instance, node_name, parent_path, instance_name, object_name,
                          ext_resource_id, order_index):
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
        f"metadata/gamemaker_colour = {godot_value(instance.get('colour'))}",
        f"metadata/gamemaker_image_index = {godot_value(instance.get('imageIndex'))}",
        f"metadata/gamemaker_image_speed = {godot_value(instance.get('imageSpeed'))}",
        f"metadata/gamemaker_object_id = {godot_value(instance.get('objectId'))}",
        f"metadata/gamemaker_properties = {godot_value(instance.get('properties', []))}",
        f"metadata/gamemaker_has_creation_code = {godot_value(bool(instance.get('hasCreationCode', False)))}",
    ])

    if ext_resource_id is None:
        lines.append("metadata/gamemaker_placeholder = true")
        lines.append("metadata/gamemaker_unresolved_object_scene = true")

    lines.append("")
    return lines


def _ordered_instances(instances, creation_order):
    indexed = []
    for original_index, instance in enumerate(instances):
        order_index = creation_order.get(_instance_name(instance))
        sort_order = order_index if order_index is not None else len(creation_order) + original_index
        indexed.append((sort_order, original_index, instance, order_index))
    indexed.sort(key=lambda item: (item[0], item[1]))
    return [(instance, order_index, original_index) for _sort, original_index, instance, order_index in indexed]


def _instance_creation_order(room):
    order = {}
    for index, entry in enumerate(room.instance_creation_order):
        if not isinstance(entry, dict):
            continue
        name = entry.get("%Name") or entry.get("name")
        if name and name not in order:
            order[name] = index
    return order


def _instance_name(instance):
    return instance.get("%Name") or instance.get("name") or "Instance"


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


def _format_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if number.is_integer():
        return str(int(number))
    return str(number)


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
