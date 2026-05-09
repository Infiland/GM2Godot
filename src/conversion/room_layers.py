from __future__ import annotations

import json
import os
import re
from typing import Protocol, cast

from src.conversion.room_creation_code import resolve_instance_creation_code
from src.conversion.type_defs import JsonDict, JsonList, JsonValue, LogCallback


KNOWN_LAYER_TYPES = {
    "GMRInstanceLayer",
    "GMRBackgroundLayer",
    "GMRTileLayer",
    "GMRAssetLayer",
    "GMREffectLayer",
}


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


class RoomLayerResourceIndex(Protocol):
    godot_project_path: str

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
        f"metadata/gamemaker_colour = {godot_value(instance.get('colour'))}",
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
