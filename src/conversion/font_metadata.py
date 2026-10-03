"""Pure font metadata capture with separate legacy consumer projections."""

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
class _CapturedFontField:
    present: bool = False
    value: JsonValue = None

    @property
    def state(self) -> JsonValue | JsonMissing:
        return self.value if self.present else MISSING


@dataclass(frozen=True)
class _FontConversionInputs:
    font_name: _CapturedFontField = field(default_factory=_CapturedFontField)
    name: _CapturedFontField = field(default_factory=_CapturedFontField)
    size: _CapturedFontField = field(default_factory=_CapturedFontField)
    bold: _CapturedFontField = field(default_factory=_CapturedFontField)
    italic: _CapturedFontField = field(default_factory=_CapturedFontField)
    anti_alias: _CapturedFontField = field(default_factory=_CapturedFontField)
    include_ttf: _CapturedFontField = field(default_factory=_CapturedFontField)
    ttf_name: _CapturedFontField = field(default_factory=_CapturedFontField)


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class GameMakerFontMetadata:
    font_name: str = ""
    size_number: int | float = 0.0
    bold: bool = False
    italic: bool = False
    include_ttf: bool = False
    parent_path: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_object)
    source_context: str = field(default="", repr=False, compare=False)
    _conversion_inputs: _FontConversionInputs = field(
        default_factory=_FontConversionInputs, repr=False, compare=False
    )

    def project_conversion_fields(self) -> "FontConversionFields":
        """Apply the legacy conversions to this record's private capture."""
        inputs = self._conversion_inputs
        return FontConversionFields(
            font_name=_python_string(_required_conversion_value(inputs.font_name, "fontName")),
            name=_python_string(_required_conversion_value(inputs.name, "name")),
            size=_python_float(_optional_conversion_value(inputs.size, 12.0)),
            bold=bool(_optional_conversion_value(inputs.bold, False)),
            italic=bool(_optional_conversion_value(inputs.italic, False)),
            anti_alias=_python_int(_optional_conversion_value(inputs.anti_alias, 0)),
            include_ttf=bool(_optional_conversion_value(inputs.include_ttf, False)),
            ttf_name=_python_string(_optional_conversion_value(inputs.ttf_name, "")),
        )


@dataclass(frozen=True)
class FontConversionFields:
    font_name: str
    name: str
    size: float
    bold: bool
    italic: bool
    anti_alias: int
    include_ttf: bool
    ttf_name: str


def _capture_font_field(data: JsonObject, key: str) -> _CapturedFontField:
    value = field_value(data, key)
    if isinstance(value, JsonMissing):
        return _CapturedFontField()
    return _CapturedFontField(present=True, value=value)


def _summary_string(data: JsonObject, *, source_context: str) -> str:
    try:
        return required_string(data, "fontName", source_path=source_context)
    except JsonFieldError:
        return ""


def _summary_number(value: _CapturedFontField) -> int | float:
    state = value.state
    return state if isinstance(state, (int, float)) else 0.0


def _summary_boolean(value: _CapturedFontField) -> bool:
    return bool(value.value) if value.present else False


def _parent_path(data: JsonObject, *, source_context: str) -> str:
    try:
        parent = required_object(data, "parent", source_path=source_context)
        return required_string(parent, "path", source_path=source_context, field_path=("parent",))
    except JsonFieldError:
        return ""


def parse_gamemaker_font_metadata(data: JsonObject, *, source_context: str) -> GameMakerFontMetadata:
    """Capture validated JSON without potentially failing converter coercions."""
    inputs = _FontConversionInputs(
        font_name=_capture_font_field(data, "fontName"),
        name=_capture_font_field(data, "name"),
        size=_capture_font_field(data, "size"),
        bold=_capture_font_field(data, "bold"),
        italic=_capture_font_field(data, "italic"),
        anti_alias=_capture_font_field(data, "AntiAlias"),
        include_ttf=_capture_font_field(data, "includeTTF"),
        ttf_name=_capture_font_field(data, "TTFName"),
    )
    return GameMakerFontMetadata(
        font_name=_summary_string(data, source_context=source_context),
        size_number=_summary_number(inputs.size),
        bold=_summary_boolean(inputs.bold),
        italic=_summary_boolean(inputs.italic),
        include_ttf=_summary_boolean(inputs.include_ttf),
        parent_path=_parent_path(data, source_context=source_context),
        raw_data=data,
        source_context=source_context,
        _conversion_inputs=inputs,
    )


def _required_conversion_value(value: _CapturedFontField, key: str) -> JsonValue:
    state = value.state
    if isinstance(state, JsonMissing):
        raise KeyError(key)
    return state


def _optional_conversion_value(value: _CapturedFontField, default: JsonValue) -> JsonValue:
    state = value.state
    return default if isinstance(state, JsonMissing) else state


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


def project_font_conversion_fields(metadata: GameMakerFontMetadata) -> FontConversionFields:
    """Apply the original eight conversions in their original evaluation order."""
    return metadata.project_conversion_fields()
