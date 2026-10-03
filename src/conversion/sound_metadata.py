"""Pure sound metadata capture with separate legacy consumer projections."""

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
class _CapturedSoundField:
    present: bool = False
    value: JsonValue = None

    @property
    def state(self) -> JsonValue | JsonMissing:
        return self.value if self.present else MISSING


@dataclass(frozen=True)
class _AudioGroupConversionInputs:
    root: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    name: _CapturedSoundField = field(default_factory=_CapturedSoundField)


@dataclass(frozen=True)
class _SoundConversionInputs:
    name: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    sound_file: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    volume: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    sound_type: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    bit_depth: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    bit_rate: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    sample_rate: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    compression: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    preload: _CapturedSoundField = field(default_factory=_CapturedSoundField)
    audio_group: _AudioGroupConversionInputs = field(default_factory=_AudioGroupConversionInputs)
    duration: _CapturedSoundField = field(default_factory=_CapturedSoundField)


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerSoundMetadata:
    sound_file: str = ""
    audio_group: str = ""
    parent_path: str = ""
    source_name: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_object)
    source_context: str = field(default="", repr=False, compare=False)
    _conversion_inputs: _SoundConversionInputs = field(
        default_factory=_SoundConversionInputs, repr=False, compare=False
    )

    @property
    def sound_file_value(self) -> JsonValue:
        """Return original soundFile provenance for owner validation, without coercion."""
        captured = self._conversion_inputs.sound_file
        return captured.value if captured.present else None

    def project_conversion_fields(self, *, sound_file: str) -> "SoundConversionFields":
        """Apply legacy conversions after the owner has validated soundFile."""
        inputs = self._conversion_inputs
        return SoundConversionFields(
            name=_python_string(_required_conversion_value(inputs.name, "name")),
            sound_file=sound_file,
            volume=_python_float(_optional_conversion_value(inputs.volume, 1.0)),
            sound_type=_python_int(_optional_conversion_value(inputs.sound_type, 0)),
            bit_depth=_python_int(_optional_conversion_value(inputs.bit_depth, 16)),
            bit_rate=_python_int(_optional_conversion_value(inputs.bit_rate, 128)),
            sample_rate=_python_int(_optional_conversion_value(inputs.sample_rate, 44100)),
            compression=_python_int(_optional_conversion_value(inputs.compression, 0)),
            preload=bool(_optional_conversion_value(inputs.preload, True)),
            audio_group=_python_string(_audio_group_name(inputs.audio_group)),
            duration=_python_float(_optional_conversion_value(inputs.duration, 0.0)),
        )


@dataclass(frozen=True)
class SoundConversionFields:
    name: str
    sound_file: str
    volume: float
    sound_type: int
    bit_depth: int
    bit_rate: int
    sample_rate: int
    compression: int
    preload: bool
    audio_group: str
    duration: float


def _capture_sound_field(data: JsonObject, key: str) -> _CapturedSoundField:
    value = field_value(data, key)
    if isinstance(value, JsonMissing):
        return _CapturedSoundField()
    return _CapturedSoundField(present=True, value=value)


def _capture_audio_group(data: JsonObject) -> _AudioGroupConversionInputs:
    root = _capture_sound_field(data, "audioGroupId")
    name = _capture_sound_field(root.value, "name") if isinstance(root.value, dict) else _CapturedSoundField()
    return _AudioGroupConversionInputs(root=root, name=name)


def _summary_string(value: _CapturedSoundField, *, nonempty: bool = False) -> str:
    captured = value.value
    if isinstance(captured, str) and (captured or not nonempty):
        return captured
    return ""


def _parent_path(data: JsonObject, *, source_context: str) -> str:
    try:
        parent = required_object(data, "parent", source_path=source_context)
        return required_string(parent, "path", source_path=source_context, field_path=("parent",))
    except JsonFieldError:
        return ""


def parse_gamemaker_sound_metadata(data: JsonObject, *, source_context: str) -> GameMakerSoundMetadata:
    """Capture validated JSON without potentially failing converter coercions."""
    inputs = _SoundConversionInputs(
        name=_capture_sound_field(data, "name"),
        sound_file=_capture_sound_field(data, "soundFile"),
        volume=_capture_sound_field(data, "volume"),
        sound_type=_capture_sound_field(data, "type"),
        bit_depth=_capture_sound_field(data, "bitDepth"),
        bit_rate=_capture_sound_field(data, "bitRate"),
        sample_rate=_capture_sound_field(data, "sampleRate"),
        compression=_capture_sound_field(data, "compression"),
        preload=_capture_sound_field(data, "preload"),
        audio_group=_capture_audio_group(data),
        duration=_capture_sound_field(data, "duration"),
    )
    return GameMakerSoundMetadata(
        sound_file=_summary_string(inputs.sound_file),
        audio_group=_summary_string(inputs.audio_group.name, nonempty=True),
        parent_path=_parent_path(data, source_context=source_context),
        source_name=_summary_string(inputs.name, nonempty=True),
        raw_data=data,
        source_context=source_context,
        _conversion_inputs=inputs,
    )


def _required_conversion_value(value: _CapturedSoundField, key: str) -> JsonValue:
    state = value.state
    if isinstance(state, JsonMissing):
        raise KeyError(key)
    return state


def _optional_conversion_value(value: _CapturedSoundField, default: JsonValue) -> JsonValue:
    state = value.state
    return default if isinstance(state, JsonMissing) else state


def _audio_group_name(value: _AudioGroupConversionInputs) -> JsonValue:
    state = value.root.state
    if isinstance(state, JsonMissing):
        return "audiogroup_default"
    if not isinstance(state, dict):
        raise AttributeError(
            f"'{type(state).__name__}' object has no attribute 'get'", name="get", obj=state
        )
    return _optional_conversion_value(value.name, "audiogroup_default")


def _python_string(value: JsonValue) -> str:
    return str(value)


def _python_float(value: JsonValue) -> float:
    if isinstance(value, (str, int, float)):
        return float(value)
    raise TypeError(f"float() argument must be a string or a real number, not '{type(value).__name__}'")


def _python_int(value: JsonValue) -> int:
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(
        f"int() argument must be a string, a bytes-like object or a real number, not '{type(value).__name__}'"
    )


def project_sound_conversion_fields(
    metadata: GameMakerSoundMetadata, *, sound_file: str
) -> SoundConversionFields:
    """Apply the original eleven positions to a captured record and validated soundFile."""
    return metadata.project_conversion_fields(sound_file=sound_file)
