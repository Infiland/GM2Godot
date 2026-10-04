"""Pure sprite summaries and the separate views consumed by sprite owners."""

from dataclasses import dataclass, field

from src.conversion.json_values import JsonObject, JsonValue


def _empty_raw_data() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerSpriteMetadata:
    width: int = 0
    height: int = 0
    origin: int = 0
    raw_data: JsonObject = field(default_factory=_empty_raw_data)
    source_context: str = field(default="", compare=False, repr=False)


def _summary_integer(value: JsonValue) -> int:
    return value if isinstance(value, int) else 0


def parse_gamemaker_sprite_metadata(
    data: JsonObject, *, source_context: str
) -> GameMakerSpriteMetadata:
    return GameMakerSpriteMetadata(
        width=_summary_integer(data.get("width")),
        height=_summary_integer(data.get("height")),
        origin=_summary_integer(data.get("origin")),
        raw_data=data,
        source_context=source_context,
    )


@dataclass(frozen=True)
class SpriteCollisionFields:
    collision_kind: int
    collision_tolerance: int
    bbox_mode: int
    bbox_left: int
    bbox_right: int
    bbox_top: int
    bbox_bottom: int
    width: int
    height: int
    origin: int
    xorigin: int
    yorigin: int


def _sprite_int(value: JsonValue) -> int:
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(
        "int() argument must be a string, a bytes-like object or a real number, "
        f"not '{type(value).__name__}'"
    )


def _sprite_float(value: JsonValue) -> float:
    if isinstance(value, (str, int, float)):
        return float(value)
    raise TypeError(
        f"float() argument must be a string or a real number, not '{type(value).__name__}'"
    )


def parse_sprite_collision_fields(data: JsonObject) -> SpriteCollisionFields:
    collision_kind = _sprite_int(data.get("collisionKind", 1))
    try:
        collision_tolerance = _sprite_int(data.get("collisionTolerance", 0))
    except (TypeError, ValueError):
        collision_tolerance = -1 if collision_kind in (0, 4) else 0
    sequence = data.get("sequence")
    sequence_data: JsonObject = sequence if isinstance(sequence, dict) else {}
    return SpriteCollisionFields(
        collision_kind,
        collision_tolerance,
        _sprite_int(data.get("bboxMode", 0)),
        _sprite_int(data.get("bbox_left", 0)),
        _sprite_int(data.get("bbox_right", 0)),
        _sprite_int(data.get("bbox_top", 0)),
        _sprite_int(data.get("bbox_bottom", 0)),
        _sprite_int(data.get("width", 0)),
        _sprite_int(data.get("height", 0)),
        _sprite_int(data.get("origin", 0)),
        _sprite_int(data.get("xorigin", sequence_data.get("xorigin", 0))),
        _sprite_int(data.get("yorigin", sequence_data.get("yorigin", 0))),
    )


@dataclass(frozen=True)
class SpriteAnimationFields:
    playback_speed: float
    playback_speed_type: int
    loop: bool
    frame_durations: list[float]


def _required_object(value: JsonValue, context: str) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError(f"GameMaker sprite {context} must be an object")
    return value


def _required_array(value: JsonValue, context: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise TypeError(f"GameMaker sprite {context} must be an array")
    return value


def parse_sprite_animation_fields(data: JsonObject) -> SpriteAnimationFields | None:
    sequence = data.get("sequence")
    if not isinstance(sequence, dict):
        return None
    playback_speed = _sprite_float(sequence.get("playbackSpeed", 30.0))
    playback_speed_type = _sprite_int(sequence.get("playbackSpeedType", 0))
    loop = _sprite_int(sequence.get("playback", 1)) == 1
    frame_durations: list[float] = []
    tracks = sequence.get("tracks", [])
    if tracks:
        track = _required_object(_required_array(tracks, "sequence.tracks")[0], "sequence.tracks[0]")
        keyframes_store = _required_object(track.get("keyframes", {}), "sequence.tracks[0].keyframes")
        keyframes = _required_array(keyframes_store.get("Keyframes", []), "sequence.tracks[0].keyframes.Keyframes")
        sorted_keyframes = sorted(
            keyframes,
            key=lambda keyframe: _sprite_float(_required_object(keyframe, "keyframe").get("Key", 0)),
        )
        frame_durations = [
            _sprite_float(_required_object(keyframe, "keyframe").get("Length", 1.0))
            for keyframe in sorted_keyframes
        ]
    return SpriteAnimationFields(playback_speed, playback_speed_type, loop, frame_durations)


@dataclass(frozen=True)
class SpriteFrameLayerFields:
    frames: list[str]
    layers: list[str]


def parse_sprite_frame_layer_fields(data: JsonObject) -> SpriteFrameLayerFields:
    frames = _required_array(data["frames"], "frames")
    frame_guids = [str(_required_object(frame, "frame")["name"]) for frame in frames]
    layers = _required_array(data.get("layers", []), "layers")
    visible_layer_guids = [
        str(_required_object(layer, "layer")["name"])
        for layer in layers
        if _required_object(layer, "layer").get("visible", True)
    ]
    if not visible_layer_guids and layers:
        visible_layer_guids = [str(_required_object(layers[0], "layers[0]")["name"])]
    return SpriteFrameLayerFields(frame_guids, visible_layer_guids)


@dataclass(frozen=True)
class SpriteAtlasFrameInput:
    has_frames: bool = False
    frame_is_object: bool = False
    raw_frame: JsonValue = None
    name_value: JsonValue = ""


def capture_sprite_atlas_frame(data: JsonObject) -> SpriteAtlasFrameInput:
    frames = data.get("frames", [])
    if not isinstance(frames, list) or not frames:
        return SpriteAtlasFrameInput()
    frame = frames[0]
    if not isinstance(frame, dict):
        return SpriteAtlasFrameInput(has_frames=True, raw_frame=frame)
    return SpriteAtlasFrameInput(True, True, frame, frame.get("name", ""))


@dataclass(frozen=True)
class SpriteAtlasLayer:
    index: int
    name_value: JsonValue


def select_sprite_atlas_layer(data: JsonObject) -> SpriteAtlasLayer | None:
    raw_layers = data.get("layers", [])
    if not isinstance(raw_layers, list) or not raw_layers:
        return None
    layers = [(index, layer) for index, layer in enumerate(raw_layers) if isinstance(layer, dict)]
    if not layers:
        return None
    primary_layer: tuple[int, JsonObject] | None = None
    for index, layer in layers:
        if layer.get("visible", True):
            primary_layer = (index, layer)
            break
    if primary_layer is None:
        primary_layer = layers[0]
    index, layer = primary_layer
    return SpriteAtlasLayer(index, layer.get("name", ""))
