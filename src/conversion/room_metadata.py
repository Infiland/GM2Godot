"""Staged room metadata views preserving the consumer’s field-read policies."""

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

from src.conversion.json_values import JsonArray, JsonObject, JsonValue


def _json_object(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _json_objects(value: JsonValue) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def room_object_at_get(value: JsonValue) -> JsonObject:
    """Narrow at the original get operation, retaining native wrong-kind failure."""
    if isinstance(value, dict):
        return value
    raise AttributeError(
        f"'{type(value).__name__}' object has no attribute 'get'",
        name="get",
        obj=value,
    )


def iter_room_field_values(value: JsonValue) -> Iterator[JsonValue]:
    """Preserve direct native iteration, including string characters/dict keys."""
    if isinstance(value, (str, dict, list)):
        yield from value
        return
    raise TypeError(f"'{type(value).__name__}' object is not iterable")


def room_object_items(value: JsonValue) -> list[JsonObject]:
    """Existing forgiving object-list projection, with fresh list/member identity."""
    return _json_objects(value)


@dataclass(frozen=True)
class RoomIndexFields:
    room_settings: JsonValue
    physics_settings: JsonValue
    view_settings: JsonValue
    views: JsonValue
    layers: JsonValue
    instance_creation_order: JsonValue
    parent_room: JsonValue
    inherit_code: bool
    inherit_creation_order: bool
    inherit_layers: bool
    is_dnd: bool
    raw_data: JsonObject
    source_context: str = field(compare=False, repr=False)


def capture_room_creation_code_value(data: JsonObject) -> JsonValue:
    return data.get("creationCodeFile")


def capture_room_index_fields(
    data: JsonObject, *, source_context: str
) -> RoomIndexFields:
    """Called only after the owner's creationCodeFile diagnostic/callback."""
    return RoomIndexFields(
        room_settings=data.get("roomSettings") or {},
        physics_settings=data.get("physicsSettings") or {},
        view_settings=data.get("viewSettings") or {},
        views=data.get("views") or [],
        layers=data.get("layers") or [],
        instance_creation_order=data.get("instanceCreationOrder") or [],
        parent_room=data.get("parentRoom"),
        inherit_code=bool(data.get("inheritCode", False)),
        inherit_creation_order=bool(data.get("inheritCreationOrder", False)),
        inherit_layers=bool(data.get("inheritLayers", False)),
        is_dnd=bool(data.get("isDnd", False)),
        raw_data=data,
        source_context=source_context,
    )


@dataclass(frozen=True)
class RoomSummarySettings:
    raw_settings: JsonObject
    source_context: str = field(compare=False, repr=False)


@dataclass(frozen=True)
class RoomSummaryFields:
    width: int
    height: int
    persistent: bool
    inherit_layers: bool
    parent_room_name: str | None
    raw_data: JsonObject
    source_context: str = field(compare=False, repr=False)


def capture_room_summary_settings(
    data: JsonObject, *, source_context: str
) -> RoomSummarySettings:
    return RoomSummarySettings(_json_object(data.get("roomSettings")), source_context)


def _native_int(value: JsonValue) -> int:
    # Existing aggregate policy deliberately preserves bool/native int identity.
    return value if isinstance(value, int) else 0


def _native_optional_int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) else None


def _strict_named_reference(value: JsonValue) -> str | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    return name if isinstance(name, str) and name else None


def project_room_summary_fields(
    data: JsonObject,
    settings: RoomSummarySettings,
    *,
    source_context: str,
) -> RoomSummaryFields:
    """Called after preorder layer summary traversal; no converter coercion."""
    return RoomSummaryFields(
        width=_native_int(settings.raw_settings.get("Width")),
        height=_native_int(settings.raw_settings.get("Height")),
        persistent=bool(settings.raw_settings.get("persistent", False)),
        inherit_layers=bool(data.get("inheritLayers", False)),
        parent_room_name=_strict_named_reference(data.get("parentRoom")),
        raw_data=data,
        source_context=source_context,
    )


@dataclass(frozen=True)
class RoomLayerSummaryFields:
    name: str
    resource_type: str
    depth: int | None
    order: int
    raw_data: JsonObject
    source_context: str = field(compare=False, repr=False)


def room_strict_layer_resource_type(layer: JsonObject) -> str:
    resource_type = layer.get("resourceType")
    if isinstance(resource_type, str) and resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _summary_layer_name(layer: JsonObject) -> str:
    first = layer.get("%Name")
    first_string = first if isinstance(first, str) else ""
    if first_string:
        return first_string
    second = layer.get("name")
    second_string = second if isinstance(second, str) else ""
    return second_string or "Layer"


def iter_room_layer_summary_fields(
    value: JsonValue, *, source_context: str
) -> Iterator[RoomLayerSummaryFields]:
    for index, layer in enumerate(_json_objects(value)):
        yield RoomLayerSummaryFields(
            name=_summary_layer_name(layer),
            resource_type=room_strict_layer_resource_type(layer),
            depth=_native_optional_int(layer.get("depth")),
            order=index,
            raw_data=layer,
            source_context=source_context,
        )
        # This read follows the caller's construction of the yielded model.
        yield from iter_room_layer_summary_fields(
            layer.get("layers") or layer.get("children"),
            source_context=source_context,
        )


@dataclass(frozen=True)
class RoomLayerHeader:
    name: str
    resource_type: JsonValue
    raw_data: JsonObject
    source_context: str = field(compare=False, repr=False)


def capture_room_render_layer_name(layer: JsonObject) -> str:
    name = layer.get("%Name") or layer.get("name")
    return name if isinstance(name, str) and name else "Layer"


def capture_room_layer_header(
    layer: JsonObject, *, name: str, source_context: str
) -> RoomLayerHeader:
    """After owner name allocation; before warnings and variant-field reads."""
    resource_type = layer.get("resourceType")
    if not resource_type:
        resource_type = "UnknownLayer"
        for key in layer:
            if key.startswith("$GMR"):
                resource_type = key[1:]
                break
    return RoomLayerHeader(name, resource_type, layer, source_context)


@dataclass(frozen=True)
class RoomOptionalMetadataField:
    present: bool
    value: JsonValue


def capture_optional_room_metadata(
    data: JsonObject, key: str
) -> RoomOptionalMetadataField:
    if key not in data:
        return RoomOptionalMetadataField(False, None)
    return RoomOptionalMetadataField(True, data.get(key))


@dataclass(frozen=True)
class RoomSettingsFields:
    raw_value: JsonValue
    source_context: str = field(compare=False, repr=False)

    @property
    def width(self) -> JsonValue:
        return room_object_at_get(self.raw_value).get("Width", 1024)

    @property
    def height(self) -> JsonValue:
        return room_object_at_get(self.raw_value).get("Height", 768)

    @property
    def persistent(self) -> bool:
        return bool(room_object_at_get(self.raw_value).get("persistent", False))


@dataclass(frozen=True)
class RoomViewSettingsFields:
    raw_value: JsonValue
    source_context: str = field(compare=False, repr=False)

    @property
    def enable_views(self) -> bool:
        return bool(room_object_at_get(self.raw_value).get("enableViews", False))

    @property
    def inherit_views(self) -> bool:
        return bool(room_object_at_get(self.raw_value).get("inheritViewSettings", False))


@dataclass(frozen=True)
class _RoomRawFields:
    raw_data: JsonObject
    source_context: str = field(compare=False, repr=False)


@dataclass(frozen=True)
class RoomLayerFields(_RoomRawFields):
    """Live named field reads, invoked only at their existing owner expressions."""

    @property
    def visible(self) -> bool:
        return bool(self.raw_data.get("visible", True))

    @property
    def instances(self) -> list[JsonObject]:
        return _json_objects(self.raw_data.get("instances"))

    @property
    def assets(self) -> list[JsonObject]:
        return _json_objects(self.raw_data.get("assets"))

    @property
    def child_values(self) -> JsonValue:
        return self.raw_data.get("layers") or self.raw_data.get("children")

    @property
    def tileset_reference(self) -> "RoomNamedReferenceFields":
        return RoomNamedReferenceFields(_json_object(self.raw_data.get("tilesetId")), self.source_context)

    @property
    def children(self) -> list[JsonObject]:
        return _json_objects(self.raw_data.get("layers") or self.raw_data.get("children") or [])

    @property
    def sprite_name(self) -> str | None:
        name = _json_object(self.raw_data.get("spriteId")).get("name")
        return name if isinstance(name, str) else None

    @property
    def tileset_name(self) -> str | None:
        name = _json_object(self.raw_data.get("tilesetId")).get("name")
        return name if isinstance(name, str) else None

    @property
    def tile_data(self) -> "RoomTileDataFields":
        return RoomTileDataFields(_json_object(self.raw_data.get("tiles")), self.source_context)

    @property
    def depth(self) -> JsonValue:
        return self.raw_data.get('depth', 0)

    @property
    def x(self) -> JsonValue:
        return self.raw_data.get('x', 0)

    @property
    def y(self) -> JsonValue:
        return self.raw_data.get('y', 0)

    @property
    def hspeed(self) -> JsonValue:
        return self.raw_data.get('hspeed', 0)

    @property
    def vspeed(self) -> JsonValue:
        return self.raw_data.get('vspeed', 0)

    @property
    def hspeed_raw(self) -> JsonValue:
        return self.raw_data.get("hspeed")

    @property
    def vspeed_raw(self) -> JsonValue:
        return self.raw_data.get("vspeed")

    @property
    def grid_x(self) -> JsonValue:
        return self.raw_data.get('gridX')

    @property
    def grid_y(self) -> JsonValue:
        return self.raw_data.get('gridY')

    @property
    def properties(self) -> JsonValue:
        return self.raw_data.get('properties', [])

    @property
    def effect_name(self) -> JsonValue:
        return self.raw_data.get("%Name") or self.raw_data.get("name")

    @property
    def effect_type(self) -> JsonValue:
        return self.raw_data.get('effectType')

    @property
    def colour(self) -> JsonValue:
        return self.raw_data.get('colour')

    @property
    def background_colour(self) -> JsonValue:
        return self.raw_data.get("colour", 4278190080)

    @property
    def sprite_colour(self) -> JsonValue:
        return self.raw_data.get("colour", 4294967295)

    @property
    def background_sprite_value(self) -> JsonValue:
        return _json_object(self.raw_data.get("spriteId")).get("name")

    @property
    def tileset_name_value(self) -> JsonValue:
        return _json_object(self.raw_data.get("tilesetId")).get("name")

    @property
    def htiled(self) -> JsonValue:
        return self.raw_data.get('htiled')

    @property
    def vtiled(self) -> JsonValue:
        return self.raw_data.get('vtiled')

    @property
    def stretch(self) -> JsonValue:
        return self.raw_data.get('stretch')


@dataclass(frozen=True)
class RoomViewFields(_RoomRawFields):
    @property
    def visible(self) -> bool:
        return bool(self.raw_data.get("visible", False))

    @property
    def object_name(self) -> JsonValue:
        reference = _json_object(self.raw_data.get("objectId"))
        # Preserve the original condition-first and successful second get.
        # A virtual dictionary can change that second value; keep it honest.
        return reference.get("name") if isinstance(reference.get("name"), str) else None

    @property
    def xview_value(self) -> JsonValue:
        return self.raw_data.get('xview', 0)

    @property
    def yview_value(self) -> JsonValue:
        return self.raw_data.get('yview', 0)

    @property
    def wview_value(self) -> JsonValue:
        return self.raw_data.get('wview', 0)

    @property
    def hview_value(self) -> JsonValue:
        return self.raw_data.get('hview', 0)

    @property
    def xport_value(self) -> JsonValue:
        return self.raw_data.get('xport', 0)

    @property
    def yport_value(self) -> JsonValue:
        return self.raw_data.get('yport', 0)

    @property
    def wport_value(self) -> JsonValue:
        return self.raw_data.get('wport', 0)

    @property
    def hport_value(self) -> JsonValue:
        return self.raw_data.get('hport', 0)

    @property
    def xview(self) -> JsonValue:
        return self.raw_data.get('xview')

    @property
    def yview(self) -> JsonValue:
        return self.raw_data.get('yview')

    @property
    def wview(self) -> JsonValue:
        return self.raw_data.get('wview')

    @property
    def hview(self) -> JsonValue:
        return self.raw_data.get('hview')

    @property
    def object_id(self) -> JsonValue:
        return self.raw_data.get('objectId')

    @property
    def hborder(self) -> JsonValue:
        return self.raw_data.get('hborder')

    @property
    def vborder(self) -> JsonValue:
        return self.raw_data.get('vborder')

    @property
    def hspeed(self) -> JsonValue:
        return self.raw_data.get('hspeed')

    @property
    def vspeed(self) -> JsonValue:
        return self.raw_data.get('vspeed')


@dataclass(frozen=True)
class RoomTransformFields(_RoomRawFields):

    @property
    def modulate_colour(self) -> JsonValue:
        return self.raw_data.get("colour", 4294967295)

    @property
    def x(self) -> JsonValue:
        return self.raw_data.get('x', 0)

    @property
    def y(self) -> JsonValue:
        return self.raw_data.get('y', 0)

    @property
    def rotation(self) -> JsonValue:
        return self.raw_data.get('rotation', 0)

    @property
    def scale_x(self) -> JsonValue:
        return self.raw_data.get('scaleX', 1)

    @property
    def scale_y(self) -> JsonValue:
        return self.raw_data.get('scaleY', 1)

    @property
    def colour(self) -> JsonValue:
        return self.raw_data.get('colour')

    @property
    def properties(self) -> JsonValue:
        return self.raw_data.get('properties', [])


@dataclass(frozen=True)
class RoomInstanceFields(RoomTransformFields):
    @property
    def name(self) -> str:
        name = self.raw_data.get("%Name") or self.raw_data.get("name")
        return name if isinstance(name, str) and name else "Instance"

    @property
    def object_name(self) -> str | None:
        name = _json_object(self.raw_data.get("objectId")).get("name")
        return name if isinstance(name, str) else None

    @property
    def is_ignored(self) -> bool:
        return self.raw_data.get("ignore") is True

    @property
    def ignored(self) -> bool:
        return bool(self.raw_data.get("ignore", False))

    @property
    def has_creation_code(self) -> bool:
        return bool(self.raw_data.get("hasCreationCode", False))

    @property
    def object_id(self) -> JsonValue:
        return self.raw_data.get('objectId')

    @property
    def image_index(self) -> JsonValue:
        return self.raw_data.get('imageIndex')

    @property
    def image_speed(self) -> JsonValue:
        return self.raw_data.get('imageSpeed')


@dataclass(frozen=True)
class RoomAssetFields(RoomTransformFields):
    @property
    def name(self) -> str:
        name = self.raw_data.get("%Name") or self.raw_data.get("name")
        if isinstance(name, str) and name:
            return name
        name = _json_object(self.raw_data.get("spriteId")).get("name")
        return name if isinstance(name, str) and name else "Asset"

    @property
    def resource_type(self) -> str:
        resource_type = self.raw_data.get("resourceType")
        if isinstance(resource_type, str) and resource_type:
            return resource_type
        for key in self.raw_data:
            if key.startswith("$GMR"):
                return key[1:]
        return "UnknownAsset"

    @property
    def is_ignored(self) -> bool:
        return self.raw_data.get("ignore") is True

    @property
    def sprite_name(self) -> str | None:
        name = _json_object(self.raw_data.get("spriteId")).get("name")
        return name if isinstance(name, str) else None

    @property
    def particle_system_id(self) -> JsonObject:
        return _json_object(
            self.raw_data.get("particleSystemId")
            if self.raw_data.get("particleSystemId") is not None
            else self.raw_data.get("particlesystemId")
        )

    @property
    def inherit_item_settings(self) -> bool:
        return bool(self.raw_data.get("inheritItemSettings", False))

    @property
    def sprite_id(self) -> JsonValue:
        return self.raw_data.get('spriteId')

    @property
    def head_position(self) -> JsonValue:
        return self.raw_data.get('headPosition')

    @property
    def animation_speed(self) -> JsonValue:
        return self.raw_data.get('animationSpeed')

    @property
    def animation_fps(self) -> JsonValue:
        return self.raw_data.get('animationFPS')

    @property
    def animation_speed_type(self) -> JsonValue:
        return self.raw_data.get('animationSpeedType')

    @property
    def inherited_item_id(self) -> JsonValue:
        return self.raw_data.get('inheritedItemId')


@dataclass(frozen=True)
class RoomTileDataFields(_RoomRawFields):
    @property
    def compressed_count(self) -> int:
        value = self.raw_data.get("TileCompressedData") or []
        if isinstance(value, (str, dict, list)):
            return len(value)
        raise TypeError(f"object of type '{type(value).__name__}' has no len()")

    @property
    def compressed_data(self) -> JsonArray:
        value = self.raw_data.get("TileCompressedData")
        return value if isinstance(value, list) else []

    @property
    def width(self) -> JsonValue:
        return self.raw_data.get('SerialiseWidth', 0)

    @property
    def height(self) -> JsonValue:
        return self.raw_data.get('SerialiseHeight', 0)

    @property
    def data_format(self) -> JsonValue:
        return self.raw_data.get('TileDataFormat', 1)


def room_inherited_reference_name(value: JsonValue) -> str:
    if not isinstance(value, dict):
        return ""
    name = value.get("name")
    if isinstance(name, str) and name:
        return name
    path = value.get("path")
    if isinstance(path, str) and path:
        return os.path.splitext(os.path.basename(path))[0]
    return ""


def room_inherited_item_key(item: JsonObject) -> str:
    for key in ("inheritedItemId", "%Name", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name:
                return name
    return ""


def room_creation_order_name(entry: JsonObject) -> str | None:
    name = entry.get("%Name") or entry.get("name")
    return name if isinstance(name, str) and name else None


@dataclass(frozen=True)
class RoomPhysicsSettingsFields:
    raw_value: JsonValue
    source_context: str = field(compare=False, repr=False)

    @property
    def physics_world(self) -> bool:
        return bool(room_object_at_get(self.raw_value).get("PhysicsWorld", False))

    @property
    def gravity_x(self) -> JsonValue:
        return room_object_at_get(self.raw_value).get("PhysicsWorldGravityX", 0.0)

    @property
    def gravity_y(self) -> JsonValue:
        return room_object_at_get(self.raw_value).get("PhysicsWorldGravityY", 10.0)

    @property
    def pixels_to_meters(self) -> JsonValue:
        return room_object_at_get(self.raw_value).get("PhysicsWorldPixToMetres", 0.1)


@dataclass(frozen=True)
class RoomArchitectureLayerFields(_RoomRawFields):
    @property
    def htiled(self) -> JsonValue:
        return self.raw_data.get("htiled", False)

    @property
    def vtiled(self) -> JsonValue:
        return self.raw_data.get("vtiled", False)

    @property
    def stretch(self) -> JsonValue:
        return self.raw_data.get("stretch", False)

    @property
    def hspeed(self) -> JsonValue:
        return self.raw_data.get("hspeed")

    @property
    def vspeed(self) -> JsonValue:
        return self.raw_data.get("vspeed")


def room_value_length(value: JsonValue) -> int:
    if isinstance(value, (str, dict, list)):
        return len(value)
    raise TypeError(f"object of type '{type(value).__name__}' has no len()")


@dataclass(frozen=True)
class RoomSceneRootFields(_RoomRawFields):
    @property
    def volume(self) -> JsonValue:
        return self.raw_data.get("volume", 1.0)


@dataclass(frozen=True)
class RoomNamedReferenceFields(_RoomRawFields):
    @property
    def name_value(self) -> JsonValue:
        return self.raw_data.get("name")


def room_item_name_value(item: JsonObject) -> JsonValue:
    return item.get("%Name") or item.get("name") or ""
