"""Draw functions light the pixels GameMaker's runner lights.

The generated runtime draws into a Godot window rendered with OpenGL under
``xvfb-run``, and the frame is compared with what the GameMaker HTML5 runner
draws:

- a line covers the same pixels whichever end it starts from (yyWebGL.js
  WebGL_draw_line_width_color_RELEASE builds the same quad either way);
- draw_roundrect's corner ellipses are xrad by yrad, capped at the rectangle,
  so a corner's radius is half of them (yyWebGL.js
  WebGL_draw_roundrect_color_EXT_RELEASE, ported below);
- draw_sprite_part clips the part to the frame and leaves the visible pixels
  where they would have been (yyWebGL.js WebGL_DrawPart_RELEASE), while
  draw_sprite_general does not clip, so texels outside the frame stay empty
  (WebGL_TextureDrawWH_RELEASE);
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import ClassVar

from PIL import Image

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_SIZE = 128
_FRAME = (5, 3)
_BLACK = (0, 0, 0)
_WHITE = (255, 255, 255)
Pixel = tuple[int, int, int]
Region = tuple[int, int, int, int]

# Each line is drawn forwards in the left half and backwards 64 pixels to the
# right; GameMaker lights the same pixels for both.
_LINE_PAIRS = (
    ("gml_draw_line(2, 2, 12, 2)", "gml_draw_line(76, 2, 66, 2)"),
    ("gml_draw_line(14, 2, 14, 12)", "gml_draw_line(78, 12, 78, 2)"),
    ("gml_draw_line(18, 2, 28, 9)", "gml_draw_line(92, 9, 82, 2)"),
    ("gml_draw_line(30, 4, 36, 14)", "gml_draw_line(100, 14, 94, 4)"),
    ("gml_draw_line_width(40, 2, 50, 2, 2)", "gml_draw_line_width(114, 2, 104, 2, 2)"),
    ("gml_draw_line_width(40, 8, 50, 13, 3)", "gml_draw_line_width(114, 13, 104, 8, 3)"),
    ("gml_draw_line_color(2, 16, 20, 16, 0x0000ff, 0x00ff00)", "gml_draw_line_color(84, 16, 66, 16, 0x00ff00, 0x0000ff)"),
    ("gml_draw_triangle(2, 20, 14, 20, 8, 28, true)", "gml_draw_triangle(66, 20, 72, 28, 78, 20, true)"),
)
_LINE_REGION = (0, 0, 64, 32)

# (x1, y1, x2, y2, xrad, yrad, circle precision); None radii use draw_roundrect.
_ROUNDRECTS = (
    (4, 36, 43, 65, 20, 20, 64),
    (50, 36, 73, 48, None, None, 24),
    (80, 36, 89, 65, 30, 8, 32),
    (96, 36, 123, 49, 12, 26, 16),
    (50, 54, 73, 72, 1, 3, 24),
)
_ROUNDRECT_REGION = (0, 34, 128, 76)

# (call, GameMaker's destination x, y, width, height, source left, top,
# width, height); integer scales so every pixel centre samples one texel.
_PART_CASES = (
    ("gml_draw_sprite_part(tex, 0, -2, 0, 4, 3, 2, 80)", (4, 80, 2, 3), (0, 0, 2, 3)),
    ("gml_draw_sprite_part(tex, 0, 1, -2, 3, 4, 10, 80)", (10, 82, 3, 2), (1, 0, 3, 2)),
    ("gml_draw_sprite_part(tex, 0, 3, 1, 6, 6, 18, 80)", (18, 80, 2, 2), (3, 1, 2, 2)),
    ("gml_draw_sprite_part_ext(tex, 0, -2, -1, 4, 3, 26, 80, 2, 2, 0xffffff, 1)", (30, 82, 4, 4), (0, 0, 2, 2)),
    ("gml_draw_sprite_part_ext(tex, 0, -1, 0, 3, 2, 38, 80, 3, 1, 0xffffff, 1)", (41, 80, 6, 2), (0, 0, 2, 2)),
)
# draw_sprite_general: (call, x, y, xscale, yscale, left, top, width, height).
_GENERAL_CASES = (
    ("gml_draw_sprite_general(tex, 0, -2, 0, 4, 3, 56, 80, 1, 1, 0, 0xffffff, 0xffffff, 0xffffff, 0xffffff, 1)",
     (56, 80, 1, 1), (-2, 0, 4, 3)),
    ("gml_draw_sprite_general(tex, 0, 3, -1, 4, 3, 64, 80, 2, 2, 0, 0xffffff, 0xffffff, 0xffffff, 0xffffff, 1)",
     (64, 80, 2, 2), (3, -1, 4, 3)),
    ("gml_draw_sprite_general(tex, 0, 1, 1, 3, 2, 76, 80, 2, 1, 0, 0xffffff, 0xffffff, 0xffffff, 0xffffff, 1)",
     (76, 80, 2, 1), (1, 1, 3, 2)),
)
_PART_REGION = (0, 78, 128, 100)


def _texel(column: int, row: int) -> Pixel:
    return (40 * column + 40, 70 * row + 60, 250 - 30 * column)


# The scene draws every case in _ready; `tex` is a 5x3 texture whose texels
# all differ and `tm` a hidden tilemap layer of two white 4x4 cells.
def _draw_script() -> str:
    calls: list[str] = ["gml_draw_set_color(0xffffff)"]
    for forward, backward in _LINE_PAIRS:
        calls += [forward, backward]
    for x1, y1, x2, y2, xrad, yrad, precision in _ROUNDRECTS:
        calls.append(f"gml_draw_set_circle_precision({precision})")
        if xrad is None:
            calls.append(f"gml_draw_roundrect({x1}, {y1}, {x2}, {y2}, false)")
        else:
            calls.append(f"gml_draw_roundrect_ext({x1}, {y1}, {x2}, {y2}, {xrad}, {yrad}, false)")
    calls += [case[0] for case in _PART_CASES]
    calls += [case[0] for case in _GENERAL_CASES]
    body = "".join(f"\tGMRuntime.{call}\n" for call in calls)
    return (
        "extends Node2D\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "# Members, so the textures outlive _ready while the canvas draws them.\n"
        "var tex = null\n"
        "var tm = null\n\n\n"
        "func _texture():\n"
        f"\tvar image = Image.create({_FRAME[0]}, {_FRAME[1]}, false, Image.FORMAT_RGBA8)\n"
        f"\tfor row in range({_FRAME[1]}):\n"
        f"\t\tfor column in range({_FRAME[0]}):\n"
        "\t\t\timage.set_pixel(column, row, Color8(40 * column + 40, 70 * row + 60, 250 - 30 * column, 255))\n"
        "\treturn ImageTexture.create_from_image(image)\n\n\n"
        "func _tilemap():\n"
        "\tvar image = Image.create(4, 4, false, Image.FORMAT_RGBA8)\n"
        "\timage.fill(Color(1, 1, 1, 1))\n"
        "\tvar source = TileSetAtlasSource.new()\n"
        "\tsource.texture = ImageTexture.create_from_image(image)\n"
        "\tsource.texture_region_size = Vector2i(4, 4)\n"
        "\tsource.create_tile(Vector2i(0, 0))\n"
        "\tvar tile_set = TileSet.new()\n"
        "\ttile_set.tile_size = Vector2i(4, 4)\n"
        "\ttile_set.add_source(source, 0)\n"
        "\tvar layer = TileMapLayer.new()\n"
        "\tlayer.tile_set = tile_set\n"
        "\tlayer.visible = false\n"
        "\tlayer.set_cell(Vector2i(0, 0), 0, Vector2i(0, 0))\n"
        "\tlayer.set_cell(Vector2i(1, 0), 0, Vector2i(0, 0))\n"
        "\tadd_child(layer)\n"
        "\treturn layer\n\n\n"
        "func _ready():\n"
        "\ttex = _texture()\n"
        "\ttm = _tilemap()\n"
        '\tGMRuntime.gml_draw_begin(self, "draw")\n'
        f"{body}"
        "\tGMRuntime.gml_draw_end()\n"
    )


def _project_settings() -> str:
    return (
        "[application]\n"
        'config/name="DrawPixels"\n'
        'run/main_scene="res://draw.tscn"\n\n'
        "[display]\n"
        f"window/size/viewport_width={_SIZE}\n"
        f"window/size/viewport_height={_SIZE}\n\n"
        "[rendering]\n"
        "textures/canvas_textures/default_texture_filter=0\n"
        "environment/defaults/default_clear_color=Color(0, 0, 0, 1)\n"
    )


def _roundrect_rim(x1: float, y1: float, x2: float, y2: float, xrad: float, yrad: float, steps: int) -> list[tuple[float, float]]:
    """The rim of WebGL_draw_roundrect_color_EXT_RELEASE (without the legacy offset)."""
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    w = min(xrad, abs(right - left))
    h = min(yrad, abs(bottom - top))
    xm, ym = (left + right) * 0.5, (top + bottom) * 0.5
    rx = abs(right - left) * 0.5 - w * 0.5
    ry = abs(bottom - top) * 0.5 - h * 0.5
    cosines = [1.0] + [math.cos(i * 2 * math.pi / steps) for i in range(1, steps)] + [1.0]
    sines = [0.0] + [math.sin(i * 2 * math.pi / steps) for i in range(1, steps)] + [0.0]
    quarter = steps // 4
    rim: list[tuple[float, float]] = []
    for corner, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        for i in range(corner * quarter, (corner + 1) * quarter + 1):
            rim.append((xm + sx * rx + w * cosines[i] / 2, ym + sy * ry + h * sines[i] / 2))
    return rim


def _convex_coverage(rim: list[tuple[float, float]], px: float, py: float) -> bool | None:
    """Whether the convex rim covers a point; None when it lies on the rim."""
    edges = [(rim[i], rim[(i + 1) % len(rim)]) for i in range(len(rim))]
    edges = [(a, b) for a, b in edges if math.dist(a, b) > 1e-9]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    orientation = 1.0 if area > 0 else -1.0
    inside = True
    for (ax, ay), (bx, by) in edges:
        distance = orientation * ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / math.dist((ax, ay), (bx, by))
        if distance < -1e-3:
            return False
        if distance <= 1e-3:
            inside = False
    return True if inside else None


def _paint_part(
    expected: dict[tuple[int, int], Pixel],
    destination: tuple[float, float, float, float],
    source: tuple[float, float, float, float],
) -> None:
    """Paint source texels stretched over the destination rect, nearest sampling.

    Texels outside the frame are left empty like GameMaker's texture page.
    """
    dx, dy, dw, dh = destination
    sx, sy, sw, sh = source
    for py in range(math.ceil(dy - 0.5), math.ceil(dy + dh - 0.5)):
        for px in range(math.ceil(dx - 0.5), math.ceil(dx + dw - 0.5)):
            column = math.floor(sx + (px + 0.5 - dx) / dw * sw)
            row = math.floor(sy + (py + 0.5 - dy) / dh * sh)
            if 0 <= column < _FRAME[0] and 0 <= row < _FRAME[1]:
                expected[(px, py)] = _texel(column, row)


def _region_pixels(image: Image.Image, region: Region) -> Iterable[tuple[int, int, Pixel]]:
    left, top, right, bottom = region
    for y in range(top, bottom):
        for x in range(left, right):
            pixel = image.getpixel((x, y))
            assert isinstance(pixel, tuple)
            yield x, y, (int(pixel[0]), int(pixel[1]), int(pixel[2]))


class TestDrawGameMakerPixelsGodot(unittest.TestCase):
    workspace: ClassVar[tempfile.TemporaryDirectory[str]]
    frame: ClassVar[Image.Image]

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        if shutil.which("xvfb-run") is None:
            raise unittest.SkipTest("xvfb-run is not available for an OpenGL render")
        cls.workspace = tempfile.TemporaryDirectory()
        project_dir = Path(cls.workspace.name) / "project"
        movie_dir = Path(cls.workspace.name) / "movie"
        movie_dir.mkdir(parents=True)
        write_gml_runtime(str(project_dir))
        write_fixture_text(project_dir / "project.godot", _project_settings())
        write_fixture_text(project_dir / "draw.gd", _draw_script())
        write_fixture_text(
            project_dir / "draw.tscn",
            '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://draw.gd" id="1"]\n\n'
            '[node name="Draw" type="Node2D"]\nscript = ExtResource("1")\n',
        )
        completed = subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                f"-screen 0 {_SIZE + 64}x{_SIZE + 64}x24",
                godot_binary,
                "--path",
                str(project_dir),
                "--rendering-driver",
                "opengl3",
                "--write-movie",
                str(movie_dir / "frame.png"),
                "--fixed-fps",
                "60",
                "--quit-after",
                "3",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=dict(os.environ, HOME=str(cls.workspace.name)),
        )
        output = completed.stdout + completed.stderr
        frames = sorted(movie_dir.glob("frame*.png"))
        if not frames:
            cls.workspace.cleanup()
            raise unittest.SkipTest("OpenGL rendering is unavailable: " + output[-2000:])
        if "SCRIPT ERROR" in output:
            cls.workspace.cleanup()
            raise AssertionError(output)
        with Image.open(frames[-1]) as image:
            cls.frame = image.convert("RGB")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    def _assert_region(self, region: Region, expected: Callable[[int, int], Pixel | None]) -> None:
        self.assertEqual(self.frame.size, (_SIZE, _SIZE))
        wrong = [
            (x, y, actual, want)
            for x, y, actual in _region_pixels(self.frame, region)
            if (want := expected(x, y)) is not None and actual != want
        ]
        self.assertEqual(wrong, [], f"{len(wrong)} pixels differ from GameMaker (x, y, actual, expected)")

    def test_lines_light_the_same_pixels_whichever_end_they_start_from(self) -> None:
        self.assertEqual(self.frame.size, (_SIZE, _SIZE))
        forward = {(x, y): pixel for x, y, pixel in _region_pixels(self.frame, _LINE_REGION)}
        left, top, right, bottom = _LINE_REGION
        backward = {
            (x - 64, y): pixel
            for x, y, pixel in _region_pixels(self.frame, (left + 64, top, right + 64, bottom))
        }
        self.assertGreater(sum(pixel != _BLACK for pixel in forward.values()), 100)
        differing = sorted(point for point in forward if forward[point] != backward[point])
        self.assertEqual(differing, [], "pixels a reversed line lights differently")

    def test_roundrect_corners_are_half_of_xrad_and_yrad(self) -> None:
        rims = [_roundrect_rim(x1, y1, x2, y2, 10 if xr is None else xr, 10 if yr is None else yr, steps)
                for x1, y1, x2, y2, xr, yr, steps in _ROUNDRECTS]

        # Pixel centres on a rim edge depend on the GPU's fill rule.
        def expected(x: int, y: int) -> Pixel | None:
            for rim in rims:
                covered = _convex_coverage(rim, x + 0.5, y + 0.5)
                if covered is None:
                    return None
                if covered:
                    return _WHITE
            return _BLACK

        self._assert_region(_ROUNDRECT_REGION, expected)

    def test_sprite_parts_clip_to_the_frame_like_gamemaker(self) -> None:
        painted: dict[tuple[int, int], Pixel] = {}
        for _call, destination, source in _PART_CASES:
            _paint_part(painted, destination, source)
        for _call, (x, y, xscale, yscale), (left, top, width, height) in _GENERAL_CASES:
            _paint_part(painted, (x, y, width * xscale, height * yscale), (left, top, width, height))
        self._assert_region(_PART_REGION, lambda x, y: painted.get((x, y), _BLACK))


if __name__ == "__main__":
    unittest.main()
