"""Text drawn under a zoomed view or a scaled GUI lights GameMaker's pixels.

GameMaker's runner places glyph quads at the exact, often fractional, draw
position (``yyFont.js`` ``GR_Text_Draw`` and ``Draw_String_GL`` round
nothing). The view, Draw End and GUI transforms then scale those quads, and the
GPU picks the lit pixels by the pixel-centre rule in application-surface
pixels. So with a 64x64 view on a 256x256 port, text keeps quarter-room-pixel
precision, and text drawn at ``camera_get_view_x() + n`` keeps its place on
screen while the camera sits between room pixels.

The fixture converts a synthetic GameMaker font, runs a room whose 64x64 view
fills a 256x256 port with the camera at a fractional position, and draws text
through the generated runtime's real draw_text functions in the Draw, Draw End
and Draw GUI phases (with ``display_set_gui_size(64, 64)``). The rendered frame
is compared pixel by pixel with ``tests.gamemaker_font_reference``: the
GameMaker glyph quads, mapped through the same view and GUI transforms and
rasterized with nearest sampling. Positions keep texel edges clear of pixel
centres, so nearest sampling has no ties.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageChops

from src.conversion.asset_registry import AssetRegistryConverter, render_asset_registry_script
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.fonts import FontConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.godot_validation import validate_generated_godot_project
from src.conversion.json_values import JsonArray, JsonObject
from src.conversion.room_display import room_view_entries
from tests.gamemaker_font_reference import (
    FA_CENTER,
    FA_LEFT,
    WHITE,
    Colour,
    GameMakerTextReference,
    Point,
    ReferenceVertexQuad,
    rasterize_vertex_quads,
    write_font_project,
    write_gamemaker_font,
)
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_FONT = "fnt_view"
_VIEW_SIZE = 64
_PORT_SIZE = 256
_ZOOM = _PORT_SIZE / _VIEW_SIZE
_VIEW_X = 0.3
_VIEW_Y = 0.55
_YELLOW: Colour = (255, 255, 0, 255)
_ORANGE: Colour = (255, 128, 0, 255)


def _gml_colour(colour: Colour) -> int:
    red, green, blue, _alpha = colour
    return red | green << 8 | blue << 16


@dataclass(frozen=True)
class _ViewText:
    """One draw_text_ext_transformed_colour call in a draw phase.

    ``camera_relative`` adds camera_get_view_x/y to the position, like a HUD
    drawn in room space.
    """

    phase: str
    x: float
    y: float
    text: str
    sep: int = -1
    halign: int = FA_LEFT
    xscale: float = 1.0
    colours: tuple[Colour, Colour, Colour, Colour] | None = None
    camera_relative: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "sep": self.sep,
            "halign": self.halign,
            "xscale": self.xscale,
            "colours": None if self.colours is None else [_gml_colour(colour) for colour in self.colours],
            "camera_relative": self.camera_relative,
        }

    def screen_quads(self, reference: GameMakerTextReference) -> list[ReferenceVertexQuad]:
        x, y = self.x, self.y
        if self.camera_relative:
            x, y = x + _VIEW_X, y + _VIEW_Y
        quads = reference.vertex_quads(
            x,
            y,
            self.text,
            sep=self.sep,
            halign=self.halign,
            xscale=self.xscale,
            colours=self.colours or (WHITE, WHITE, WHITE, WHITE),
        )
        origin = (0.0, 0.0) if self.phase == "draw_gui" else (_VIEW_X, _VIEW_Y)

        def screen(point: Point) -> Point:
            return ((point[0] - origin[0]) * _ZOOM, (point[1] - origin[1]) * _ZOOM)

        return [
            ReferenceVertexQuad(
                code=quad.code,
                points=(screen(quad.points[0]), screen(quad.points[1]), screen(quad.points[2]), screen(quad.points[3])),
                source=quad.source,
                colours=quad.colours,
            )
            for quad in quads
        ]


# Draw, then Draw End, then Draw GUI, as GameMaker renders them. Positions are
# quarter pixels and the view sits at (0.3, 0.55), so on screen every texel
# edge lands at least 0.3 px from a pixel centre.
_TEXTS = (
    _ViewText("draw", 2.25, 4.25, "Ab"),
    _ViewText("draw", 22.5, 4.25, "Ab"),
    _ViewText("draw", 42.75, 4.25, "Ab"),
    _ViewText("draw", 12.0, 17.25, "Odd", halign=FA_CENTER),
    _ViewText("draw", 30.5, 17.25, "Ab", xscale=1.0001),
    _ViewText("draw", 46.0, 17.0, "Hd", camera_relative=True),
    _ViewText("draw", 2.75, 32.75, "Ab", colours=(_YELLOW, _YELLOW, _ORANGE, _ORANGE)),
    _ViewText("draw", 30.25, 32.5, "A\nb", sep=9),
    _ViewText("draw_end", 2.25, 47.25, "En"),
    _ViewText("draw_end", 18.0, 47.0, "Hv", camera_relative=True),
    _ViewText("draw_gui", 34.25, 47.5, "Gu"),
    _ViewText("draw_gui", 48.75, 47.75, "Gx"),
)


def _gd(source: str) -> str:
    """Dedent GDScript written with 4-space indentation and indent it with tabs."""
    lines: list[str] = []
    for line in textwrap.dedent(source).splitlines():
        stripped = line.lstrip(" ")
        lines.append("\t" * ((len(line) - len(stripped)) // 4) + stripped)
    return "\n".join(lines) + "\n"


def _drawer_script(data_path: Path) -> str:
    return _gd(
        f"""
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const DATA_PATH = {json.dumps(str(data_path))}

        var _drawn = false

        func _process(_delta):
            if _drawn:
                return
            _drawn = true
            var texts = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
            var camera = GMRuntime.gml_view_get_camera(0)
            GMRuntime.gml_camera_set_view_pos(camera, {_VIEW_X}, {_VIEW_Y})
            GMRuntime.gml_display_set_gui_size({_VIEW_SIZE}, {_VIEW_SIZE})
            GMRuntime._gml_camera_update_visible_views()
            var view_x = GMRuntime.gml_camera_get_view_x(camera)
            var view_y = GMRuntime.gml_camera_get_view_y(camera)
            for phase in ["draw", "draw_end", "draw_gui"]:
                GMRuntime.gml_draw_begin(self, phase)
                GMRuntime.gml_draw_set_font(GMRuntime.gml_asset_get_index("{_FONT}"))
                for text in texts:
                    if text["phase"] != phase:
                        continue
                    var x = float(text["x"])
                    var y = float(text["y"])
                    if text["camera_relative"]:
                        x += view_x
                        y += view_y
                    GMRuntime.gml_draw_set_halign(int(text["halign"]))
                    var colours = text["colours"]
                    if colours != null:
                        GMRuntime.gml_draw_text_ext_transformed_color(x, y, text["text"], text["sep"], -1, text["xscale"], 1, 0, colours[0], colours[1], colours[2], colours[3], 1)
                    elif float(text["xscale"]) != 1.0:
                        GMRuntime.gml_draw_text_ext_transformed(x, y, text["text"], text["sep"], -1, text["xscale"], 1, 0)
                    elif int(text["sep"]) >= 0:
                        GMRuntime.gml_draw_text_ext(x, y, text["text"], text["sep"], -1)
                    else:
                        GMRuntime.gml_draw_text(x, y, text["text"])
                GMRuntime.gml_draw_end()
        """
    )


_ROOM_SCRIPT = _gd(
    """
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    func _enter_tree():
        GMRuntime._gml_view_room_prepare(self)
    """
)


def _room_scene() -> str:
    view: JsonObject = {
        "visible": True,
        "xview": 0,
        "yview": 0,
        "wview": _VIEW_SIZE,
        "hview": _VIEW_SIZE,
        "xport": 0,
        "yport": 0,
        "wport": _PORT_SIZE,
        "hport": _PORT_SIZE,
        "objectId": None,
        "hborder": 32,
        "vborder": 32,
        "hspeed": -1,
        "vspeed": -1,
    }
    views: JsonArray = [view]
    entries = room_view_entries(views, {"Width": 128, "Height": 128})
    view_settings = {"enableViews": True, "clearViewBackground": False, "clearDisplayBuffer": True}
    return (
        "[gd_scene format=3]\n\n"
        '[ext_resource type="Script" path="res://room.gd" id="room"]\n'
        '[ext_resource type="Script" path="res://drawer.gd" id="drawer"]\n\n'
        '[node name="r_view" type="Node2D"]\n'
        'script = ExtResource("room")\n'
        "metadata/gamemaker_room_width = 128\n"
        "metadata/gamemaker_room_height = 128\n"
        "metadata/gamemaker_room_persistent = false\n"
        f"metadata/gamemaker_view_settings = {json.dumps(view_settings)}\n"
        f"metadata/gamemaker_views = {json.dumps(entries)}\n\n"
        '[node name="Drawer" type="Node2D" parent="."]\n'
        'script = ExtResource("drawer")\n\n'
        '[node name="GMGUI" type="CanvasLayer" parent="."]\n'
        "layer = 1000\n"
        'metadata/gm2godot_gui_layer_policy = "gm_gui_canvas_layer"\n'
    )


def _project_settings() -> str:
    return (
        "config_version=5\n\n"
        "[application]\n"
        'config/name="FontViewRender"\n'
        'run/main_scene="res://room.tscn"\n\n'
        "[display]\n"
        f"window/size/viewport_width={_PORT_SIZE}\n"
        f"window/size/viewport_height={_PORT_SIZE}\n"
        'window/stretch/mode="viewport"\n\n'
        "[rendering]\n"
        "textures/canvas_textures/default_texture_filter=0\n"
        'environment/defaults/default_clear_color=Color(0, 0, 0, 1)\n'
    )


def _max_channel_difference(actual: Image.Image, expected: Image.Image) -> int:
    worst = 0
    for band in ImageChops.difference(actual, expected).split():
        high = band.getextrema()[1]
        if isinstance(high, (int, float)):
            worst = max(worst, int(high))
    return worst


class TestFontViewRenderGodot(unittest.TestCase):
    godot_binary: ClassVar[str]
    workspace: ClassVar[tempfile.TemporaryDirectory[str]]
    root: ClassVar[Path]
    project_dir: ClassVar[Path]
    reference: ClassVar[GameMakerTextReference]

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        if shutil.which("xvfb-run") is None:
            raise unittest.SkipTest("xvfb-run is not available for an OpenGL render")
        cls.godot_binary = godot_binary
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        cls.project_dir = cls.root / "godot"
        gm_dir = cls.root / "gm"
        gm_dir.mkdir()
        cls.project_dir.mkdir()
        font = write_gamemaker_font(str(gm_dir), _FONT, ascender=10, ascender_offset=2)
        cls.reference = font.reference()
        write_font_project(str(gm_dir), [_FONT])
        FontConverter(
            str(gm_dir),
            str(cls.project_dir),
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=DiagnosticCollector(),
        ).convert_all()
        entries = AssetRegistryConverter(
            str(gm_dir),
            str(cls.project_dir),
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
        ).build_entries()
        write_fixture_text(cls.project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))
        write_gml_runtime(str(cls.project_dir))
        data_path = cls.root / "texts.json"
        data_path.write_text(json.dumps([text.to_json() for text in _TEXTS]), encoding="utf-8")
        write_fixture_text(cls.project_dir / "project.godot", _project_settings())
        write_fixture_text(cls.project_dir / "room.gd", _ROOM_SCRIPT)
        write_fixture_text(cls.project_dir / "drawer.gd", _drawer_script(data_path))
        write_fixture_text(cls.project_dir / "room.tscn", _room_scene())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    def _render(self) -> Image.Image:
        validation = validate_generated_godot_project(str(self.project_dir), godot_binary=self.godot_binary, timeout=180)
        self.assertEqual(validation.status, "passed", validation.output)
        movie_dir = self.root / "movie"
        movie_dir.mkdir(exist_ok=True)
        completed = subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                f"-screen 0 {_PORT_SIZE + 64}x{_PORT_SIZE + 64}x24",
                self.godot_binary,
                "--path",
                str(self.project_dir),
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
            env=dict(os.environ, HOME=str(self.root)),
        )
        output = completed.stdout + completed.stderr
        self.assertNotIn("SCRIPT ERROR", output)
        frames = sorted(movie_dir.glob("frame*.png"))
        if not frames:
            self.skipTest("OpenGL rendering is unavailable: " + output[-2000:])
        with Image.open(frames[-1]) as frame:
            return frame.convert("RGB")

    def test_text_under_zoomed_view_and_scaled_gui_matches_gamemaker_pixels(self) -> None:
        actual = self._render()
        expected = Image.new("RGBA", (_PORT_SIZE, _PORT_SIZE), (0, 0, 0, 255))
        with Image.open(self.project_dir / "fonts" / f"{_FONT}.png") as page:
            atlas = page.convert("RGBA")
        for text in _TEXTS:
            rasterize_vertex_quads(expected, atlas, text.screen_quads(self.reference))
        self.assertEqual(actual.size, expected.size)
        differing = ImageChops.difference(actual, expected.convert("RGB")).getbbox()
        # Blending may round differently between drivers; a misplaced glyph
        # differs by far more than a couple of levels.
        worst = _max_channel_difference(actual, expected.convert("RGB"))
        self.assertLessEqual(worst, 2, f"render differs from GameMaker by up to {worst} levels in {differing}")


if __name__ == "__main__":
    unittest.main()
