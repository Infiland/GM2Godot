"""Draw functions light the pixels GameMaker's runner lights.

The generated runtime draws into a Godot window rendered with OpenGL under
``xvfb-run``, and the frame is compared with what the GameMaker HTML5 runner
draws:

- a line covers the same pixels whichever end it starts from (yyWebGL.js
  WebGL_draw_line_width_color_RELEASE builds the same quad either way);
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from PIL import Image

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_SIZE = 128
_FRAME = (5, 3)
_BLACK = (0, 0, 0)
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


# The scene draws every case in _ready; `tex` is a 5x3 texture whose texels
# all differ and `tm` a hidden tilemap layer of two white 4x4 cells.
def _draw_script() -> str:
    calls: list[str] = ["gml_draw_set_color(0xffffff)"]
    for forward, backward in _LINE_PAIRS:
        calls += [forward, backward]
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


if __name__ == "__main__":
    unittest.main()
