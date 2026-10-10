"""Synthetic GameMaker font assets and a reference model of GameMaker text.

The reference model follows the GameMaker HTML5 runner (``yyFont.js``):
``Split_TextBlock`` line splitting and wrapping, ``TextWidth``/``GetShift``
measurement, ``GR_Text_Draw`` alignment and line spacing, and
``Draw_String_GL`` glyph placement. It is deliberately independent of the
converter and of the generated GDScript runtime so tests can hold both to the
GameMaker rules.
"""
from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from PIL import Image

NO_WRAP_WIDTH = 10000000
FA_LEFT, FA_CENTER, FA_RIGHT = 0, 1, 2
FA_TOP, FA_MIDDLE, FA_BOTTOM = 0, 1, 2


@dataclass(frozen=True)
class ReferenceGlyph:
    code: int
    x: int
    y: int
    w: int
    h: int
    shift: int
    offset: int


@dataclass(frozen=True)
class ReferenceQuad:
    """A drawn glyph cell: the atlas cell and the pixel its top-left lights."""

    code: int
    left: int
    top: int
    w: int
    h: int
    atlas_x: int
    atlas_y: int


@dataclass(frozen=True)
class SyntheticFont:
    """A GameMaker font asset written by :func:`write_gamemaker_font`."""

    name: str
    yy_path: str
    atlas_path: str | None
    document: dict[str, object]
    glyphs: dict[int, ReferenceGlyph]
    kerning: tuple[tuple[int, int, int], ...]
    apply_kerning: bool
    declared_line_height: int
    ascender: int
    ascender_offset: int
    size: float
    uses_sdf: bool
    sdf_spread: int

    def reference(self) -> GameMakerTextReference:
        line_height = self.declared_line_height
        if line_height <= 0:
            line_height = max(glyph.h for glyph in self.glyphs.values())
        kerning = (
            {(first, second): amount for first, second, amount in self.kerning}
            if self.apply_kerning
            else {}
        )
        return GameMakerTextReference(
            glyphs=self.glyphs,
            line_height=line_height,
            ascender_offset=self.ascender_offset,
            kerning=kerning,
            sdf_spread=self.sdf_spread if self.uses_sdf else 0,
        )


@dataclass(frozen=True)
class GameMakerTextReference:
    glyphs: dict[int, ReferenceGlyph]
    line_height: int
    ascender_offset: int
    kerning: dict[tuple[int, int], int]
    sdf_spread: int

    @property
    def first(self) -> int:
        return min(self.glyphs)

    def text_width(self, line: str) -> int:
        """``TextWidth``: a missing character counts as the first glyph."""
        fallback = self.glyphs[self.first]
        return sum(self.glyphs.get(ord(char), fallback).shift for char in line)

    def get_shift(self, code: int) -> int:
        """``GetShift``: a missing character counts as a space, else the first glyph."""
        glyph = self.glyphs.get(code) or self.glyphs.get(32) or self.glyphs[self.first]
        return glyph.shift

    def split(self, text: str, line_width: int = -1) -> list[str]:
        if line_width < 0 or line_width == NO_WRAP_WIDTH:
            return _split_lines(text)
        return self._wrap_lines(text, line_width)

    def _wrap_lines(self, text: str, line_width: int) -> list[str]:
        lines: list[str] = []
        length = len(text)
        start = end = 0
        while start < length:
            total = 0
            while end < length and total < line_width and text[end] == " ":
                total += self.get_shift(32)
                end += 1
            while end < length and total < line_width and text[end] != "\n":
                total += self.get_shift(ord(text[end]))
                end += 1
            if total > line_width:
                end -= 1
                total -= self.get_shift(ord(text[end]))
            if end < length and text[end] == "\n":
                lines.append(text[start:end])
            else:
                if end == start:
                    return lines
                if end != length and text[end] != " ":
                    word_start = end
                    while word_start > start:
                        word_start -= 1
                        if text[word_start] == " ":
                            break
                    if word_start != start:
                        end = word_start
                    else:
                        while end < length and text[end] != " ":
                            end += 1
                line_end = end
                if line_end > start:
                    while line_end > 0 and text[line_end - 1] == " ":
                        line_end -= 1
                if line_end != start:
                    low, high = sorted((start, line_end))
                    lines.append(text[low:high])
            end += 1
            start = end
        return lines

    def line_step(self, sep: int) -> int:
        return self.line_height if sep < 0 else sep

    def string_width(self, text: str, sep: int = -1, line_width: int = -1) -> int:
        del sep
        return max((self.text_width(line) for line in self.split(text, line_width)), default=0)

    def string_height(self, text: str, sep: int = -1, line_width: int = -1) -> int:
        lines = self.split(text, line_width)
        if not lines:
            return 0
        return (len(lines) - 1) * self.line_step(sep) + self.line_height

    def line_origins(
        self,
        text: str,
        *,
        sep: int = -1,
        line_width: int = -1,
        halign: int = FA_LEFT,
        valign: int = FA_TOP,
    ) -> list[tuple[float, float]]:
        """Pen offsets of each line's top-left relative to the draw origin."""
        lines = self.split(text, line_width)
        step = self.line_step(sep)
        y = 0.0
        if valign == FA_MIDDLE:
            y -= len(lines) * step / 2
        elif valign == FA_BOTTOM:
            y -= len(lines) * step
        origins: list[tuple[float, float]] = []
        for line in lines:
            x = 0.0
            if halign == FA_CENTER:
                x = -self.text_width(line) / 2
            elif halign == FA_RIGHT:
                x = -float(self.text_width(line))
            origins.append((x, y))
            y += step
        return origins

    def quads(
        self,
        x: float,
        y: float,
        text: str,
        *,
        sep: int = -1,
        line_width: int = -1,
        halign: int = FA_LEFT,
        valign: int = FA_TOP,
    ) -> list[ReferenceQuad]:
        """Glyph cells ``draw_text_ext`` draws, snapped like nearest sampling."""
        quads: list[ReferenceQuad] = []
        lines = self.split(text, line_width)
        origins = self.line_origins(
            text, sep=sep, line_width=line_width, halign=halign, valign=valign
        )
        for line, (line_x, line_y) in zip(lines, origins, strict=True):
            pen = x + line_x
            top = y + line_y - self.ascender_offset - self.sdf_spread
            previous: ReferenceGlyph | None = None
            for char in line:
                glyph = self.glyphs.get(ord(char))
                if glyph is None:
                    continue
                if previous is not None:
                    pen += self.kerning.get((previous.code, glyph.code), 0)
                previous = glyph
                if glyph.w * glyph.h > 0:
                    left = pen + glyph.offset - self.sdf_spread
                    quads.append(
                        ReferenceQuad(
                            code=glyph.code,
                            left=math.ceil(left - 0.5),
                            top=math.ceil(top - 0.5),
                            w=glyph.w,
                            h=glyph.h,
                            atlas_x=glyph.x,
                            atlas_y=glyph.y,
                        )
                    )
                pen += glyph.shift
        return quads


def _split_lines(text: str) -> list[str]:
    """``Split_TextBlock`` without wrapping: LF and CR end lines."""
    lines: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] in "\n\r":
            lines.append(text[start:index])
            following = text[index + 1:index + 2]
            if following in ("\n", "\r") and following != text[index]:
                index += 1
            start = index + 1
        index += 1
    if start < len(text):
        lines.append(text[start:])
    return lines


def draw_reference_quads(
    canvas: Image.Image,
    atlas: Image.Image,
    quads: Iterable[ReferenceQuad],
) -> None:
    """Blend each quad's atlas cell over ``canvas`` at its snapped pixel."""
    for quad in quads:
        cell = atlas.crop((quad.atlas_x, quad.atlas_y, quad.atlas_x + quad.w, quad.atlas_y + quad.h))
        canvas.alpha_composite(cell, dest=(quad.left, quad.top))


def synthetic_glyph_cells(
    codes: Iterable[int],
    *,
    seed: int = 0,
    atlas_width: int = 256,
) -> dict[int, ReferenceGlyph]:
    """Deterministic glyph cells with varied sizes, shifts and offsets."""
    glyphs: dict[int, ReferenceGlyph] = {}
    x = y = 1
    row_height = 0
    for code in codes:
        width = 0 if code == 32 else 3 + (code + seed) % 5
        height = 0 if code == 32 else 8 + (code * 7 + seed) % 6
        if x + width + 1 > atlas_width:
            x = 1
            y += row_height + 2
            row_height = 0
        glyphs[code] = ReferenceGlyph(
            code=code,
            x=x,
            y=y,
            w=width,
            h=height,
            shift=4 if code == 32 else width + (code % 3),
            offset=((code + seed) % 4) - 1,
        )
        x += width + 2
        row_height = max(row_height, height)
    return glyphs


def _glyph_alpha(glyph: ReferenceGlyph, column: int, row: int, *, seed: int, uses_sdf: bool) -> int:
    if uses_sdf:
        centre_x = (glyph.w - 1) / 2
        centre_y = (glyph.h - 1) / 2
        distance = 1 - (
            abs(column - centre_x) / max(centre_x, 1) + abs(row - centre_y) / max(centre_y, 1)
        ) / 2
        return max(0, min(255, int(255 * distance)))
    value = (column * 37 + row * 91 + glyph.code * 13 + seed) % 7
    if value < 2:
        return 0
    return 255 if value > 4 else 60 + value * 30


def render_synthetic_atlas(
    glyphs: dict[int, ReferenceGlyph],
    *,
    seed: int = 0,
    uses_sdf: bool = False,
    atlas_width: int = 256,
) -> Image.Image:
    """Draw a white RGBA atlas page whose glyph cells have distinct alphas."""
    atlas_height = max(glyph.y + glyph.h for glyph in glyphs.values()) + 2
    image = Image.new("RGBA", (atlas_width, atlas_height), (255, 255, 255, 0))
    for glyph in glyphs.values():
        for row in range(glyph.h):
            for column in range(glyph.w):
                alpha = _glyph_alpha(glyph, column, row, seed=seed, uses_sdf=uses_sdf)
                image.putpixel((glyph.x + column, glyph.y + row), (255, 255, 255, alpha))
    return image


def write_gamemaker_font(
    project_dir: str,
    name: str,
    *,
    codes: Sequence[int] = tuple(range(32, 127)),
    seed: int = 0,
    kerning: Sequence[tuple[int, int, int]] = (),
    apply_kerning: bool = False,
    ascender: int = 0,
    ascender_offset: int = 0,
    line_height: int = 0,
    size: float = 12.0,
    uses_sdf: bool = False,
    sdf_spread: int = 8,
    write_atlas: bool = True,
    overrides: dict[str, object] | None = None,
) -> SyntheticFont:
    """Write ``fonts/<name>/<name>.yy`` and its baked atlas page."""
    font_dir = os.path.join(project_dir, "fonts", name)
    os.makedirs(font_dir, exist_ok=True)
    glyphs = synthetic_glyph_cells(codes, seed=seed)
    atlas_path: str | None = None
    if write_atlas:
        atlas_path = os.path.join(font_dir, name + ".png")
        render_synthetic_atlas(glyphs, seed=seed, uses_sdf=uses_sdf).save(atlas_path)
    document: dict[str, object] = {
        "$GMFont": "",
        "%Name": name,
        "AntiAlias": 1,
        "applyKerning": 1 if apply_kerning else 0,
        "ascender": ascender,
        "ascenderOffset": ascender_offset,
        "bold": False,
        "canGenerateBitmap": True,
        "charset": 0,
        "first": 0,
        "fontName": "Synthetic Sans",
        "glyphOperations": 0,
        "glyphs": {
            str(glyph.code): {
                "character": glyph.code,
                "h": glyph.h,
                "offset": glyph.offset,
                "shift": glyph.shift,
                "w": glyph.w,
                "x": glyph.x,
                "y": glyph.y,
            }
            for glyph in glyphs.values()
        },
        "hinting": 0,
        "includeTTF": False,
        "interpreter": 0,
        "italic": False,
        "kerningPairs": [
            {"first": first, "second": second, "amount": amount}
            for first, second, amount in kerning
        ],
        "last": 0,
        "lineHeight": line_height,
        "maintainGms1Font": False,
        "name": name,
        "parent": {"name": "Fonts", "path": "folders/Fonts.yy"},
        "pointRounding": 0,
        "ranges": [{"lower": 32, "upper": 127}],
        "regenerateBitmap": False,
        "resourceType": "GMFont",
        "resourceVersion": "2.0",
        "sampleText": "",
        "sdfSpread": sdf_spread,
        "size": size,
        "styleName": "Regular",
        "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
        "TTFName": "",
        "usesSDF": uses_sdf,
    }
    if overrides:
        document.update(overrides)
    yy_path = os.path.join(font_dir, name + ".yy")
    with open(yy_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    return SyntheticFont(
        name=name,
        yy_path=yy_path,
        atlas_path=atlas_path,
        document=document,
        glyphs=glyphs,
        kerning=tuple(kerning),
        apply_kerning=apply_kerning,
        declared_line_height=line_height,
        ascender=ascender,
        ascender_offset=ascender_offset,
        size=size,
        uses_sdf=uses_sdf,
        sdf_spread=sdf_spread,
    )


def write_font_project(project_dir: str, font_names: Sequence[str]) -> None:
    """Write a minimal ``.yyp`` that declares the given fonts."""
    with open(os.path.join(project_dir, "FontReference.yyp"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "resources": [
                    {"id": {"name": name, "path": f"fonts/{name}/{name}.yy"}}
                    for name in font_names
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
            handle,
        )
