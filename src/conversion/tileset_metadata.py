"""Pure tileset metadata capture with separate legacy consumer projections."""

from dataclasses import dataclass, field

from src.conversion.json_fields import (
    MISSING,
    JsonFieldError,
    JsonMissing,
    field_value,
    required_object,
    required_string,
)
from src.conversion.json_values import JsonObject, JsonValue


@dataclass(frozen=True)
class _CapturedTilesetField:
    present: bool = False
    value: JsonValue = None

    @property
    def state(self) -> JsonValue | JsonMissing:
        return self.value if self.present else MISSING


@dataclass(frozen=True)
class _TilesetConversionInputs:
    tile_width: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_height: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_hsep: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_vsep: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_xoff: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_yoff: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_count: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    out_columns: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_animation_frames: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_animation_speed: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    brushes: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    auto_tile_sets: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    tile_set_collisions: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    out_tile_hborder: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)
    out_tile_vborder: _CapturedTilesetField = field(default_factory=_CapturedTilesetField)


@dataclass(frozen=True)
class GameMakerTilesetSpriteReference:
    raw_value: JsonValue = None
    path_present: bool = False
    path_value: JsonValue = None
    name_value: JsonValue = None
    source_context: str = field(default="", repr=False, compare=False)

    @property
    def is_object(self) -> bool:
        return isinstance(self.raw_value, dict)


def parse_gamemaker_tileset_sprite_reference(
    data: JsonObject, *, source_context: str
) -> GameMakerTilesetSpriteReference:
    """Capture only reference provenance before owner validation and callbacks."""
    value = field_value(data, "spriteId")
    raw = None if isinstance(value, JsonMissing) else value
    if not isinstance(raw, dict):
        return GameMakerTilesetSpriteReference(raw_value=raw, source_context=source_context)
    path = field_value(raw, "path")
    name = field_value(raw, "name")
    return GameMakerTilesetSpriteReference(
        raw_value=raw,
        path_present=not isinstance(path, JsonMissing),
        path_value=None if isinstance(path, JsonMissing) else path,
        name_value=None if isinstance(name, JsonMissing) else name,
        source_context=source_context,
    )


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerTilesetMetadata:
    sprite_name: str | None = None
    tile_width: int = 0
    tile_height: int = 0
    parent_path: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_object)
    source_context: str = field(default="", repr=False, compare=False)
    _conversion_inputs: _TilesetConversionInputs = field(
        default_factory=_TilesetConversionInputs, repr=False, compare=False
    )

    def project_conversion_fields(self) -> "TilesetConversionFields":
        """Apply the original fifteen conversions in their evaluation order."""
        inputs = self._conversion_inputs
        return TilesetConversionFields(
            tile_width=_python_int(_optional_conversion_value(inputs.tile_width, 16)),
            tile_height=_python_int(_optional_conversion_value(inputs.tile_height, 16)),
            tile_hsep=_python_int(_optional_conversion_value(inputs.tile_hsep, 0)),
            tile_vsep=_python_int(_optional_conversion_value(inputs.tile_vsep, 0)),
            tile_xoff=_python_int(_optional_conversion_value(inputs.tile_xoff, 0)),
            tile_yoff=_python_int(_optional_conversion_value(inputs.tile_yoff, 0)),
            tile_count=_python_int(_optional_conversion_value(inputs.tile_count, 0)),
            out_columns=_python_int(_optional_conversion_value(inputs.out_columns, 0)),
            tile_animation_frames=_json_object_list(
                _optional_conversion_value(inputs.tile_animation_frames, None)
            ),
            tile_animation_speed=_animation_speed(
                _optional_conversion_value(inputs.tile_animation_speed, None)
            ),
            brushes=_json_object_list(_optional_conversion_value(inputs.brushes, None)),
            auto_tile_sets=_json_object_list(_optional_conversion_value(inputs.auto_tile_sets, None)),
            tile_set_collisions=_json_object_list(
                _optional_conversion_value(inputs.tile_set_collisions, None)
            ),
            out_tile_hborder=_python_int(_optional_conversion_value(inputs.out_tile_hborder, 0)),
            out_tile_vborder=_python_int(_optional_conversion_value(inputs.out_tile_vborder, 0)),
        )


@dataclass(frozen=True)
class TilesetConversionFields:
    tile_width: int
    tile_height: int
    tile_hsep: int
    tile_vsep: int
    tile_xoff: int
    tile_yoff: int
    tile_count: int
    out_columns: int
    tile_animation_frames: list[JsonObject]
    tile_animation_speed: float
    brushes: list[JsonObject]
    auto_tile_sets: list[JsonObject]
    tile_set_collisions: list[JsonObject]
    out_tile_hborder: int
    out_tile_vborder: int


def _capture_tileset_field(data: JsonObject, key: str) -> _CapturedTilesetField:
    value = field_value(data, key)
    if isinstance(value, JsonMissing):
        return _CapturedTilesetField()
    return _CapturedTilesetField(present=True, value=value)


def _summary_integer(value: _CapturedTilesetField) -> int:
    return value.value if isinstance(value.value, int) else 0


def _parent_path(data: JsonObject, *, source_context: str) -> str:
    try:
        parent = required_object(data, "parent", source_path=source_context)
        return required_string(parent, "path", source_path=source_context, field_path=("parent",))
    except JsonFieldError:
        return ""


def parse_gamemaker_tileset_metadata(
    data: JsonObject, *, source_context: str
) -> GameMakerTilesetMetadata:
    """Capture validated JSON after owner reference callbacks, without coercion."""
    inputs = _TilesetConversionInputs(
        tile_width=_capture_tileset_field(data, "tileWidth"),
        tile_height=_capture_tileset_field(data, "tileHeight"),
        tile_hsep=_capture_tileset_field(data, "tilehsep"),
        tile_vsep=_capture_tileset_field(data, "tilevsep"),
        tile_xoff=_capture_tileset_field(data, "tilexoff"),
        tile_yoff=_capture_tileset_field(data, "tileyoff"),
        tile_count=_capture_tileset_field(data, "tile_count"),
        out_columns=_capture_tileset_field(data, "out_columns"),
        tile_animation_frames=_capture_tileset_field(data, "tileAnimationFrames"),
        tile_animation_speed=_capture_tileset_field(data, "tileAnimationSpeed"),
        brushes=_capture_tileset_field(data, "brushes"),
        auto_tile_sets=_capture_tileset_field(data, "autoTileSets"),
        tile_set_collisions=_capture_tileset_field(data, "tileSetCollisions"),
        out_tile_hborder=_capture_tileset_field(data, "out_tilehborder"),
        out_tile_vborder=_capture_tileset_field(data, "out_tilevborder"),
    )
    reference = parse_gamemaker_tileset_sprite_reference(data, source_context=source_context)
    name = reference.name_value
    return GameMakerTilesetMetadata(
        sprite_name=name if isinstance(name, str) and name else None,
        tile_width=_summary_integer(inputs.tile_width),
        tile_height=_summary_integer(inputs.tile_height),
        parent_path=_parent_path(data, source_context=source_context),
        raw_data=data,
        source_context=source_context,
        _conversion_inputs=inputs,
    )


def _optional_conversion_value(value: _CapturedTilesetField, default: JsonValue) -> JsonValue:
    state = value.state
    return default if isinstance(state, JsonMissing) else state


def _python_int(value: JsonValue) -> int:
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(
        f"int() argument must be a string, a bytes-like object or a real number, not '{type(value).__name__}'"
    )


def _animation_speed(value: JsonValue) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return 15.0


def _json_object_list(value: JsonValue) -> list[JsonObject]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def project_tileset_conversion_fields(metadata: GameMakerTilesetMetadata) -> TilesetConversionFields:
    """Request the pure ordered projection from the authoritative capture."""
    return metadata.project_conversion_fields()
