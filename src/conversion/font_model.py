"""Font conversion values and the registry's separate source eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass

from src.conversion.json_values import JsonObject, JsonValue


@dataclass(frozen=True)
class FontModel:
    font_name: str
    name: str
    size: float
    bold: bool
    italic: bool
    antialiasing: int
    include_ttf: bool
    ttf_name: str
    source_path: str
    raw_data: JsonObject


def parse_font_model(data: JsonObject, *, source_path: str) -> FontModel:
    """Normalize in the existing worker order; the caller owns error handling."""
    return FontModel(
        font_name=str(data["fontName"]),
        name=str(data["name"]),
        size=float(_font_number_input(data.get("size", 12.0))),
        bold=bool(data.get("bold", False)),
        italic=bool(data.get("italic", False)),
        antialiasing=int(_font_number_input(data.get("AntiAlias", 0))),
        include_ttf=bool(data.get("includeTTF", False)),
        ttf_name=str(data.get("TTFName", "")),
        source_path=source_path,
        raw_data=data,
    )


def _font_number_input(value: JsonValue) -> str | int | float:
    if isinstance(value, str | int | float):
        return value
    # The converter already catches TypeError and emits its fixed parse warning.
    raise TypeError("Font numeric field requires a string or number")


def bundled_font_reference(data: JsonObject) -> str | None:
    """Keep raw TTFName sampling before the includeTTF truthiness check."""
    value = data.get("TTFName")
    include_ttf = bool(data.get("includeTTF", False))
    return value if include_ttf and isinstance(value, str) and value else None


def system_font_reference(data: JsonObject) -> str | None:
    """The registry resolves only nonempty raw string family names."""
    value = data.get("fontName")
    return value if isinstance(value, str) and value else None
