"""Baked GameMaker font atlases rendered as Godot-importable BMFont files.

GameMaker never rasterises a font asset's TTF at runtime. The IDE bakes every
glyph into ``fonts/<name>/<name>.png`` and records a glyph table in the
``.yy`` metadata; the runner draws text from that atlas. This module turns the
same data into an AngelCode BMFont text file that Godot imports natively as a
fixed-size bitmap ``FontFile``.

Glyph placement follows the GameMaker runner (``yyFont.js``): for each
character the runner applies the kerning amount for the previous glyph, draws
the full ``w`` x ``h`` glyph cell at ``(pen_x + offset, line_top -
ascenderOffset)`` and advances ``pen_x`` by ``shift``. The generated BMFont
encodes ``xoffset = offset`` and ``yoffset = -ascenderOffset`` relative to the
line top, ``xadvance = shift`` and ``base`` as the font ascent, so drawing a
line with ``Font.draw_string`` at ``baseline = line_top + font.get_ascent()``
puts every glyph pixel where GameMaker puts it. ``lineHeight`` is GameMaker's
line height (the ``lineHeight`` field, or the tallest glyph cell when it is 0),
so ``Font.get_height()`` equals ``string_height("M")``.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field

from PIL import Image

from src.conversion.json_values import JsonObject, JsonValue

BMFONT_EXTENSION = ".fnt"
FONT_ATLAS_IMAGE_EXTENSION = ".png"
_MAX_GLYPH_CODE = 0x10FFFF
_MAX_ATLAS_COORDINATE = 1 << 16


@dataclass(frozen=True)
class GameMakerFontGlyph:
    """One baked glyph cell from a GameMaker font ``glyphs`` table."""

    code: int
    x: int
    y: int
    width: int
    height: int
    shift: int
    offset: int


@dataclass(frozen=True)
class GameMakerFontKerningPair:
    """Extra advance applied to ``second`` when it follows ``first``."""

    first: int
    second: int
    amount: int


@dataclass(frozen=True)
class GameMakerFontAtlasMetadata:
    """Atlas-relevant GameMaker font fields parsed from ``.yy`` JSON only."""

    glyphs: tuple[GameMakerFontGlyph, ...]
    rejected_glyph_keys: tuple[str, ...]
    kerning_pairs: tuple[GameMakerFontKerningPair, ...]
    apply_kerning: bool
    line_height: int
    ascender: int
    ascender_offset: int
    size: float
    bold: bool
    italic: bool
    anti_alias: bool
    uses_sdf: bool
    sdf_spread: int
    font_name: str


@dataclass(frozen=True)
class GameMakerFontAtlasPlan:
    """A validated atlas image plus the glyphs that lie inside it."""

    metadata: GameMakerFontAtlasMetadata
    image_path: str
    image_width: int
    image_height: int
    image_mode: str
    glyphs: tuple[GameMakerFontGlyph, ...]
    out_of_bounds_glyph_codes: tuple[int, ...] = field(default=())

    @property
    def kerning_pairs(self) -> tuple[GameMakerFontKerningPair, ...]:
        """Kerning pairs the GameMaker runner applies for this font."""
        if not self.metadata.apply_kerning:
            return ()
        codes = {glyph.code for glyph in self.glyphs}
        return tuple(
            pair
            for pair in self.metadata.kerning_pairs
            if pair.amount != 0 and pair.first in codes and pair.second in codes
        )

    @property
    def sdf_padding(self) -> int:
        """Distance-field border the runner subtracts from SDF glyph origins."""
        return self.metadata.sdf_spread if self.metadata.uses_sdf else 0


def font_atlas_image_name(yy_path: str) -> str:
    """Return GameMaker's atlas file name for a font ``.yy`` path."""
    return os.path.splitext(os.path.basename(yy_path))[0] + FONT_ATLAS_IMAGE_EXTENSION


def _integer(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _number(value: JsonValue, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return default


def _truthy(value: JsonValue) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _glyph_entries(raw_glyphs: JsonValue) -> list[tuple[str, JsonValue]]:
    """Return ``(key, glyph)`` pairs from the 2.3+ map or 2.2 list layout."""
    if isinstance(raw_glyphs, dict):
        return list(raw_glyphs.items())
    if not isinstance(raw_glyphs, list):
        return []
    entries: list[tuple[str, JsonValue]] = []
    for item in raw_glyphs:
        if isinstance(item, dict) and "Value" in item:
            key = item.get("Key")
            entries.append((str(key) if key is not None else "", item.get("Value")))
        elif isinstance(item, dict):
            character = item.get("character")
            entries.append((str(character) if character is not None else "", item))
        else:
            entries.append(("", item))
    return entries


def _parse_glyph(key: str, raw_glyph: JsonValue) -> GameMakerFontGlyph | None:
    if not isinstance(raw_glyph, dict):
        return None
    code = _integer(key)
    if code is None:
        code = _integer(raw_glyph.get("character"))
    values = {
        name: _integer(raw_glyph.get(name))
        for name in ("x", "y", "w", "h", "shift", "offset")
    }
    x, y, width, height = values["x"], values["y"], values["w"], values["h"]
    shift, offset = values["shift"], values["offset"]
    if (
        code is None
        or x is None
        or y is None
        or width is None
        or height is None
        or shift is None
        or offset is None
    ):
        return None
    if not 0 < code <= _MAX_GLYPH_CODE:
        return None
    if min(x, y, width, height) < 0 or max(x, y, width, height) > _MAX_ATLAS_COORDINATE:
        return None
    if abs(shift) > _MAX_ATLAS_COORDINATE or abs(offset) > _MAX_ATLAS_COORDINATE:
        return None
    return GameMakerFontGlyph(
        code=code,
        x=x,
        y=y,
        width=width,
        height=height,
        shift=shift,
        offset=offset,
    )


def _parse_kerning_pairs(raw_pairs: JsonValue) -> tuple[GameMakerFontKerningPair, ...]:
    if not isinstance(raw_pairs, list):
        return ()
    pairs: dict[tuple[int, int], GameMakerFontKerningPair] = {}
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, dict):
            continue
        first = _integer(raw_pair.get("first"))
        second = _integer(raw_pair.get("second"))
        amount = _integer(raw_pair.get("amount"))
        if first is None or second is None or amount is None:
            continue
        if not (0 < first <= _MAX_GLYPH_CODE and 0 < second <= _MAX_GLYPH_CODE):
            continue
        pairs[(first, second)] = GameMakerFontKerningPair(first, second, amount)
    return tuple(pairs[key] for key in sorted(pairs))


def parse_gamemaker_font_atlas_metadata(data: JsonObject) -> GameMakerFontAtlasMetadata | None:
    """Parse the baked glyph table; ``None`` when the font has no glyph data."""
    glyphs: dict[int, GameMakerFontGlyph] = {}
    rejected: list[str] = []
    for key, raw_glyph in _glyph_entries(data.get("glyphs")):
        glyph = _parse_glyph(key, raw_glyph)
        if glyph is None:
            rejected.append(key)
            continue
        glyphs[glyph.code] = glyph
    if not glyphs:
        return None

    ordered = tuple(glyphs[code] for code in sorted(glyphs))
    declared_line_height = _integer(data.get("lineHeight"))
    line_height = (
        declared_line_height
        if declared_line_height is not None and declared_line_height > 0
        else max(glyph.height for glyph in ordered)
    )
    sdf_spread = _integer(data.get("sdfSpread"))
    raw_font_name = data.get("fontName")
    raw_name = data.get("name")
    return GameMakerFontAtlasMetadata(
        glyphs=ordered,
        rejected_glyph_keys=tuple(rejected),
        kerning_pairs=_parse_kerning_pairs(data.get("kerningPairs")),
        apply_kerning=_truthy(data.get("applyKerning", False)),
        line_height=max(1, line_height),
        ascender=max(0, _integer(data.get("ascender")) or 0),
        ascender_offset=_integer(data.get("ascenderOffset")) or 0,
        size=_number(data.get("size"), 12.0),
        bold=_truthy(data.get("bold", False)),
        italic=_truthy(data.get("italic", False)),
        anti_alias=_truthy(data.get("AntiAlias", 1)),
        uses_sdf=_truthy(data.get("usesSDF", False)),
        sdf_spread=max(0, sdf_spread or 0),
        font_name=(
            raw_font_name
            if isinstance(raw_font_name, str) and raw_font_name
            else raw_name if isinstance(raw_name, str) else ""
        ),
    )


def font_registry_metadata(data: JsonObject, *, bitmap: bool) -> JsonObject:
    """Return the font fields the generated runtime needs from the registry.

    ``size`` stays in GameMaker points: the runtime derives the pixel size of
    a TTF/SystemFont fallback from it (GameMaker rasterises at 96 DPI), while
    ``bitmap`` fonts always draw at the fixed size baked into their atlas.
    """
    raw_font_name = data.get("fontName")
    return {
        "font_name": raw_font_name if isinstance(raw_font_name, str) else "",
        "size": _number(data.get("size"), 12.0),
        "bold": _truthy(data.get("bold", False)),
        "italic": _truthy(data.get("italic", False)),
        "sdf": _truthy(data.get("usesSDF", False)),
        "bitmap": bitmap,
    }


def plan_gamemaker_font_atlas(
    metadata: GameMakerFontAtlasMetadata,
    image_path: str,
) -> GameMakerFontAtlasPlan | None:
    """Validate the atlas image; ``None`` when it is missing or unreadable."""
    if not os.path.isfile(image_path):
        return None
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            mode = image.mode
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    if width <= 0 or height <= 0:
        return None
    inside: list[GameMakerFontGlyph] = []
    outside: list[int] = []
    for glyph in metadata.glyphs:
        if glyph.x + glyph.width > width or glyph.y + glyph.height > height:
            outside.append(glyph.code)
        else:
            inside.append(glyph)
    if not inside:
        return None
    return GameMakerFontAtlasPlan(
        metadata=metadata,
        image_path=image_path,
        image_width=width,
        image_height=height,
        image_mode=mode,
        glyphs=tuple(inside),
        out_of_bounds_glyph_codes=tuple(outside),
    )


def bmfont_fixed_size(metadata: GameMakerFontAtlasMetadata) -> int:
    """Return the integer ``info size`` (Godot ``fixed_size``) for a font."""
    return max(1, int(math.floor(metadata.size + 0.5)))


def bmfont_base(metadata: GameMakerFontAtlasMetadata) -> int:
    """Return the BMFont ``base``: the baseline below the line top.

    GameMaker's ``ascender`` is the distance from the line top (the glyph
    cell top plus ``ascenderOffset``) to the baseline. Older fonts store 0;
    then the whole line counts as ascent so ``get_descent()`` is zero.
    """
    if 0 < metadata.ascender <= metadata.line_height:
        return metadata.ascender
    return metadata.line_height


_UNSAFE_FACE_CHARACTERS = re.compile(r'["\r\n\t]')


def render_bmfont_text(plan: GameMakerFontAtlasPlan, page_file: str) -> str:
    """Render an AngelCode BMFont text descriptor for Godot's importer."""
    metadata = plan.metadata
    face = _UNSAFE_FACE_CHARACTERS.sub("", metadata.font_name).strip() or "GameMaker Font"
    padding = plan.sdf_padding
    lines = [
        (
            f'info face="{face}" size={bmfont_fixed_size(metadata)} '
            f"bold={int(metadata.bold)} italic={int(metadata.italic)} "
            f'charset="" unicode=1 stretchH=100 smooth={int(metadata.anti_alias)} '
            "aa=1 padding=0,0,0,0 spacing=0,0 outline=0"
        ),
        (
            f"common lineHeight={metadata.line_height} base={bmfont_base(metadata)} "
            f"scaleW={plan.image_width} scaleH={plan.image_height} pages=1 packed=0 "
            "alphaChnl=0 redChnl=0 greenChnl=0 blueChnl=0"
        ),
        f'page id=0 file="{page_file}"',
        f"chars count={len(plan.glyphs)}",
    ]
    y_offset = -metadata.ascender_offset - padding
    for glyph in plan.glyphs:
        lines.append(
            f"char id={glyph.code} x={glyph.x} y={glyph.y} "
            f"width={glyph.width} height={glyph.height} "
            f"xoffset={glyph.offset - padding} yoffset={y_offset} "
            f"xadvance={glyph.shift} page=0 chnl=15"
        )
    kerning_pairs = plan.kerning_pairs
    if kerning_pairs:
        lines.append(f"kernings count={len(kerning_pairs)}")
        for pair in kerning_pairs:
            lines.append(
                f"kerning first={pair.first} second={pair.second} amount={pair.amount}"
            )
    return "\n".join(lines) + "\n"


def render_bmfont_import_config(source_resource_path: str) -> str:
    """Return the ``.fnt.import`` settings for a GameMaker bitmap font.

    Scaling stays disabled: GameMaker draws baked fonts at their native pixel
    size and only scales text through draw transforms, so any requested font
    size must render (and measure) the baked glyphs unchanged.
    """
    return (
        "[remap]\n"
        "\n"
        'importer="font_data_bmfont"\n'
        'type="FontFile"\n'
        "\n"
        "[deps]\n"
        "\n"
        f"source_file={json.dumps(source_resource_path, ensure_ascii=False)}\n"
        "\n"
        "[params]\n"
        "\n"
        "fallbacks=[]\n"
        "compress=true\n"
        "scaling_mode=0\n"
    )


def render_skipped_import_config() -> str:
    """Return the ``.import`` file that keeps an atlas page out of imports.

    Godot's BMFont importer reads the page image itself and embeds it in the
    imported font, so the page must not also become a standalone texture.
    """
    return '[remap]\n\nimporter="skip"\n'


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = min(1.0, max(0.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _sdf_coverage_table(spread: int) -> list[int]:
    """Map 8-bit distance samples to coverage like the runner's SDF shader.

    The runner smooths the distance field over ``0.4 / sdfSpread`` on each
    side of the 0.5 edge per screen pixel (``yyFont.js``
    ``Start_Rendering_SDF``), which at the native size of the atlas is the
    coverage this table bakes.
    """
    half_width = 0.4 / max(1, spread)
    return [
        int(round(255.0 * _smoothstep(0.5 - half_width, 0.5 + half_width, sample / 255.0)))
        for sample in range(256)
    ]


def build_font_atlas_image(plan: GameMakerFontAtlasPlan) -> Image.Image | None:
    """Return a converted RGBA8 page, or ``None`` when it can be copied as is.

    Godot's BMFont loader only accepts RGBA8 colour pages, so other PNG modes
    are converted. Signed-distance-field atlases are resolved to coverage at
    the font's native size because the importer has no SDF bitmap mode.
    """
    if plan.image_mode == "RGBA" and not plan.metadata.uses_sdf:
        return None
    with Image.open(plan.image_path) as source:
        image = source.convert("RGBA")
    if not plan.metadata.uses_sdf:
        return image
    distance = image.getchannel("A")
    alpha_extrema = distance.getextrema()
    if alpha_extrema[0] == alpha_extrema[1]:
        # A constant alpha channel means the field lives in the colour channels.
        distance = image.getchannel("R")
    lookup = bytes(_sdf_coverage_table(plan.metadata.sdf_spread))
    coverage = Image.frombytes("L", distance.size, distance.tobytes().translate(lookup))
    white = Image.new("L", image.size, 255)
    return Image.merge("RGBA", (white, white, white, coverage))
