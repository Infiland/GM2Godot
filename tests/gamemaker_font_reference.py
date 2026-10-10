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

Colour = tuple[int, int, int, int]
Point = tuple[float, float]
WHITE: Colour = (255, 255, 255, 255)


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
class ReferenceVertexQuad:
    """A glyph quad as ``Draw_String_GL`` builds it.

    The quad covers the glyph cell plus the one texel of the atlas around it
    that GameMaker also draws. ``points`` and ``colours`` run top-left,
    top-right, bottom-right, bottom-left; ``source`` is the atlas rectangle.
    """

    code: int
    points: tuple[Point, Point, Point, Point]
    source: tuple[int, int, int, int]
    colours: tuple[Colour, Colour, Colour, Colour]


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

    def vertex_quads(
        self,
        x: float,
        y: float,
        text: str,
        *,
        sep: int = -1,
        line_width: int = -1,
        halign: int = FA_LEFT,
        valign: int = FA_TOP,
        xscale: float = 1.0,
        yscale: float = 1.0,
        angle: float = 0.0,
        colours: tuple[Colour, Colour, Colour, Colour] = (WHITE, WHITE, WHITE, WHITE),
    ) -> list[ReferenceVertexQuad]:
        """The quads ``draw_text_ext_transformed_colour`` hands the GPU.

        Follows ``GR_Text_Draw`` (line steps, alignment) and ``Draw_String_GL``
        (glyph quads, rotation about each line origin, corner colours). Text
        without scale or rotation has its line origins snapped the way nearest
        sampling lights the fractional quads.
        """
        if abs(angle) <= 0.001:
            angle = 0.0
        radians = math.radians(angle)
        sine, cosine = math.sin(radians), math.cos(radians)
        lines = self.split(text, line_width)
        step = self.line_step(sep)
        xsep = sine * xscale * step
        ysep = cosine * yscale * step
        if valign == FA_MIDDLE:
            x -= len(lines) * xsep / 2
            y -= len(lines) * ysep / 2
        elif valign == FA_BOTTOM:
            x -= len(lines) * xsep
            y -= len(lines) * ysep
        snap = xscale == 1.0 and yscale == 1.0 and angle == 0.0
        quads: list[ReferenceVertexQuad] = []
        for line in lines:
            xoff = 0.0
            yoff = -self.ascender_offset * yscale
            if halign == FA_CENTER:
                xoff = -(xscale * self.text_width(line) / 2)
            elif halign == FA_RIGHT:
                xoff = -(xscale * self.text_width(line))
            line_x = x + cosine * xoff + sine * yoff
            line_y = y - sine * xoff + cosine * yoff
            if snap:
                line_x, line_y = math.ceil(line_x - 0.5), math.ceil(line_y - 0.5)
            quads.extend(
                self._line_vertex_quads(line, (line_x, line_y), (xscale, yscale), (sine, cosine), colours)
            )
            x += xsep
            y += ysep
        return quads

    def _line_vertex_quads(
        self,
        line: str,
        origin: Point,
        scale: tuple[float, float],
        rotation: tuple[float, float],
        colours: tuple[Colour, Colour, Colour, Colour],
    ) -> list[ReferenceVertexQuad]:
        origin_x, origin_y = origin
        xscale, yscale = scale
        sine, cosine = rotation

        def place(px: float, py: float) -> Point:
            dx, dy = px - origin_x, py - origin_y
            return (origin_x + cosine * dx + sine * dy, origin_y - sine * dx + cosine * dy)

        across = colours[0] != colours[1] or colours[2] != colours[3]
        line_width = self.text_width(line)
        quads: list[ReferenceVertexQuad] = []
        pen = origin_x
        first_left: float | None = None
        previous: ReferenceGlyph | None = None
        for char in line:
            glyph = self.glyphs.get(ord(char))
            if glyph is None:
                continue
            if previous is not None:
                pen += xscale * self.kerning.get((previous.code, glyph.code), 0)
            previous = glyph
            if glyph.w * glyph.h > 0:
                left = pen + (glyph.offset - 1 - self.sdf_spread) * xscale
                top = origin_y - (1 + self.sdf_spread) * yscale
                right = left + (glyph.w + 2) * xscale
                bottom = top + (glyph.h + 2) * yscale
                corner_colours = colours
                if across:
                    first_left = left if first_left is None else first_left
                    start = _gradient_amount(left - first_left, line_width)
                    finish = _gradient_amount(right - first_left, line_width)
                    alpha = colours[0][3]
                    corner_colours = (
                        _merge_colour(colours[0], colours[1], start, alpha),
                        _merge_colour(colours[0], colours[1], finish, alpha),
                        _merge_colour(colours[3], colours[2], finish, alpha),
                        _merge_colour(colours[3], colours[2], start, alpha),
                    )
                quads.append(
                    ReferenceVertexQuad(
                        code=glyph.code,
                        points=(
                            place(left, top),
                            place(right, top),
                            place(right, bottom),
                            place(left, bottom),
                        ),
                        source=(glyph.x - 1, glyph.y - 1, glyph.w + 2, glyph.h + 2),
                        colours=corner_colours,
                    )
                )
            pen += xscale * glyph.shift
        return quads


def _gradient_amount(distance: float, line_width: int) -> float:
    if line_width <= 0:
        return 0.0 if distance == 0 else 1.0
    return min(abs(distance) / line_width, 1.0)


def _merge_colour(start: Colour, end: Colour, amount: float, alpha: int) -> Colour:
    """``merge_colour`` per channel, truncated, with the given alpha."""
    keep = 1.0 - amount
    red, green, blue = (int(start[index] * keep + end[index] * amount) for index in range(3))
    return (red, green, blue, alpha)


def rasterize_vertex_quads(
    canvas: Image.Image,
    atlas: Image.Image,
    quads: Iterable[ReferenceVertexQuad],
) -> None:
    """Draw axis-aligned quads over ``canvas`` like a GPU with nearest sampling.

    A pixel is drawn when its centre lies in the quad (left and top edges
    included), takes the atlas texel under that centre, and multiplies it by
    the corner colours interpolated over the triangles split along the
    top-left to bottom-right diagonal. Results blend source-over.
    """
    pixels = canvas.load()
    texels = atlas.load()
    assert pixels is not None and texels is not None
    for quad in quads:
        (left, top), (right, _), (_, bottom), _ = quad.points
        source_x, source_y, source_w, source_h = quad.source
        width, height = right - left, bottom - top
        for row in range(math.ceil(top - 0.5), math.ceil(bottom - 0.5)):
            v = (row + 0.5 - top) / height
            texel_y = source_y + min(int(v * source_h), source_h - 1)
            for column in range(math.ceil(left - 0.5), math.ceil(right - 0.5)):
                u = (column + 0.5 - left) / width
                texel = texels[source_x + min(int(u * source_w), source_w - 1), texel_y]
                assert isinstance(texel, tuple)
                colour = _corner_colour(quad.colours, u, v)
                alpha = texel[3] / 255 * colour[3]
                if alpha <= 0:
                    continue
                below = pixels[column, row]
                assert isinstance(below, tuple)
                pixels[column, row] = tuple(
                    round(texel[index] / 255 * colour[index] * alpha + below[index] * (1 - alpha))
                    for index in range(3)
                ) + (255,)


def _corner_colour(colours: tuple[Colour, Colour, Colour, Colour], u: float, v: float) -> tuple[float, ...]:
    top_left, top_right, bottom_right, bottom_left = colours
    if u >= v:
        weights = ((top_left, 1 - u), (top_right, u - v), (bottom_right, v))
    else:
        weights = ((top_left, 1 - v), (bottom_right, u), (bottom_left, v - u))
    return tuple(
        sum(colour[index] * weight for colour, weight in weights) / (255 if index == 3 else 1)
        for index in range(4)
    )


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
