"""Background layers of a converted room drawn the way GameMaker draws them.

GameMaker draws a background layer's sprite from its top-left corner (the
sprite origin is ignored) at the layer offset, scaled by the element's
xscale/yscale or stretched over the room, and along each tiled axis it
repeats the sprite every scaled sprite width or height across the whole area
being drawn (HTML5 runner: yyRoom.js DrawLayerBackgroundElement,
yyWebGL.js WebGL_TextureDrawTiled_RELEASE). A colour background fills that
area whatever the layer offset.

The probe moves, zooms and rotates the view and changes the element's scale,
stretch and tiling, then compares what the room shows against that model:
always through the nodes' transforms, and through rendered pixels when an
OpenGL renderer is available (xvfb-run).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.gamemaker_project_support import (
    BackgroundLayer,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    RoomView,
    add_probe_autoload,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    run_converted_project_rendered,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_Pixel = tuple[int, int, int, int]
_RED: _Pixel = (255, 0, 0, 255)
_GREEN: _Pixel = (0, 255, 0, 255)
_BLUE: _Pixel = (0, 0, 255, 255)


def _tile_frame() -> list[list[_Pixel]]:
    rows: list[list[_Pixel]] = [[_BLUE for _x in range(16)] for _y in range(16)]
    rows[0][0] = _RED
    rows[15][15] = _GREEN
    return rows


_PROJECT = GameMakerProject(
    name="Backgrounds",
    objects=(),
    # A script makes the converter write the GML runtime the room needs.
    scripts={"scr_unused": "function scr_unused() {}\n"},
    sprites=(
        # The origin is the sprite's centre; backgrounds ignore it.
        GameMakerSprite("s_tile", 16, 16, frames=(_tile_frame(),), xorigin=8, yorigin=8),
    ),
    rooms=(
        GameMakerRoom(
            "r_backgrounds",
            layers=(
                BackgroundLayer("TileLayer", 100, sprite="s_tile", x=5, y=3, htiled=True, vtiled=True),
                BackgroundLayer("Colour", 200, colour=0xFFFFFFFF),
            ),
            creation_order=(),
            width=200,
            height=150,
            views=(RoomView(0, 0, 64, 48, 0, 0, 128, 96),),
        ),
    ),
)

_PROBE = """extends Node

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
const LAYER_OFFSET = Vector2(5, 3)
const SIZE = Vector2(16, 16)
const ROOM = Vector2(200, 150)
const MARGIN = 0.1
# [name, view x, y, w, h, angle, xscale, yscale, stretch, htiled, vtiled]
const CASES = [
	["base", 0, 0, 64, 48, 0, 1, 1, false, true, true],
	["outside_room", 1000, 700, 64, 48, 0, 1, 1, false, true, true],
	["zoomed_out", -50, -40, 192, 144, 0, 1, 1, false, true, true],
	["rotated", 20, 10, 64, 48, 30, 1, 1, false, true, true],
	["scaled", 0, 0, 64, 48, 0, 2, 3, false, true, true],
	["stretched", -100, -75, 400, 300, 0, 1, 1, true, true, true],
	["htiled_only", 0, -20, 64, 48, 0, 1, 1, false, true, false],
	["untiled", -6, -6, 64, 48, 0, 1, 1, false, false, false],
]

var _case = -1
var _wait = 0
var _results = []
var _element = null
var _colour = null
var _frames = 0


func _process(_delta):
	_frames += 1
	if _frames > 600:
		print("BACKGROUND_TIMEOUT case " + str(_case))
		get_tree().quit(1)
		return
	if _element == null:
		var scene = get_tree().current_scene
		if scene == null or scene.find_child("TileLayer", true, false) == null:
			return
		# Compare texels without filtering (GameMaker's default draws
		# sprites without interpolation).
		get_tree().root.canvas_item_default_texture_filter = Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST
		_element = scene.find_child("s_tile", true, false)
		_colour = scene.find_child("BackgroundVisual", true, false)
		_next_case()
		return
	_wait -= 1
	if _wait > 0:
		return
	_results.append(_check_case(CASES[_case]))
	_next_case()


func _next_case():
	_case += 1
	if _case >= CASES.size():
		print("BACKGROUND_RESULTS " + JSON.stringify(_results))
		get_tree().quit(0)
		return
	var c = CASES[_case]
	var camera = GMRuntime.gml_view_get_camera(0)
	GMRuntime.gml_camera_set_view_pos(camera, c[1], c[2])
	GMRuntime.gml_camera_set_view_size(camera, c[3], c[4])
	GMRuntime.gml_camera_set_view_angle(camera, c[5])
	_element.set_meta("gamemaker_background_xscale", c[6])
	_element.set_meta("gamemaker_background_yscale", c[7])
	_element.set_meta("gamemaker_background_stretch", c[8])
	_element.set_meta("gamemaker_background_htiled", c[9])
	_element.set_meta("gamemaker_background_vtiled", c[10])
	_wait = 3


# What GameMaker shows at a room position: a texel name, "colour" where only
# the colour layer is drawn, or "" next to a texel edge (not compared).
func _expected(world, c):
	var scale = ROOM / SIZE if c[8] else Vector2(c[6], c[7])
	var local = world - LAYER_OFFSET
	var texel = Vector2.ZERO
	for axis in range(2):
		var step = SIZE[axis] * scale[axis]
		var tiled = c[9] if axis == 0 else c[10]
		var position = fposmod(local[axis], step) if tiled else local[axis]
		if position < 0.0 or position >= step:
			return "colour"
		texel[axis] = position / scale[axis]
		var fraction = texel[axis] - floor(texel[axis])
		if fraction < MARGIN or fraction > 1.0 - MARGIN:
			return ""
	return _texel_name(texel.floor())


func _texel_name(texel):
	if texel == Vector2(0, 0):
		return "red"
	if texel == Vector2(15, 15):
		return "green"
	return "blue"


# What the converted nodes show at a room position.
func _drawn(world):
	var tiles = _element.find_child("Tiles", false, false)
	if tiles != null and tiles.is_visible_in_tree() and tiles.texture != null:
		var local = tiles.get_global_transform().affine_inverse() * world
		if tiles.region_rect.has_point(local):
			return _texel_name(Vector2(fposmod(local.x, SIZE.x), fposmod(local.y, SIZE.y)).floor())
	if _colour != null and _colour.get_global_rect().has_point(world):
		return "colour"
	return "none"


func _pixel_name(colour):
	if colour.r > 0.5 and colour.g > 0.5 and colour.b > 0.5:
		return "colour"
	if colour.r > 0.5 and colour.g < 0.5 and colour.b < 0.5:
		return "red"
	if colour.g > 0.5 and colour.r < 0.5 and colour.b < 0.5:
		return "green"
	if colour.b > 0.5 and colour.r < 0.5 and colour.g < 0.5:
		return "blue"
	return "other"


func _check_case(c):
	var viewport = get_viewport()
	var size = viewport.get_visible_rect().size
	var to_world = viewport.get_canvas_transform().affine_inverse()
	var image = viewport.get_texture().get_image()
	var rendered = image != null and not image.is_empty() and Vector2(image.get_size()) == size
	var compared = 0
	var node_mismatches = []
	var pixel_mismatches = []
	for y in range(int(size.y)):
		for x in range(int(size.x)):
			var world = to_world * Vector2(x + 0.5, y + 0.5)
			var expected = _expected(world, c)
			if expected == "":
				continue
			compared += 1
			var drawn = _drawn(world)
			if drawn != expected and node_mismatches.size() < 5:
				node_mismatches.append([x, y, expected, drawn])
			if rendered:
				var pixel = _pixel_name(image.get_pixel(x, y))
				if pixel != expected and pixel_mismatches.size() < 5:
					pixel_mismatches.append([x, y, expected, pixel])
	return {
		"case": c[0],
		"compared": compared,
		"rendered": rendered,
		"node_mismatches": node_mismatches,
		"pixel_mismatches": pixel_mismatches,
	}
"""


class TestRoomBackgroundsGodot(unittest.TestCase):
    def test_background_layers_tile_like_gamemaker(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_gamemaker_project(root / "gamemaker", _PROJECT)
            convert_gamemaker_project(root / "gamemaker", root / "godot")
            add_probe_autoload(root / "godot", _PROBE)
            imported = import_converted_project(godot_binary, root / "godot")
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            result = run_converted_project_rendered(godot_binary, root / "godot", timeout=120)
            rendered_run = result is not None
            if result is None:
                result = run_converted_project(godot_binary, root / "godot")
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        lines = [line for line in output.splitlines() if line.startswith("BACKGROUND_RESULTS ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("BACKGROUND_RESULTS "))
        self.assertEqual(len(results), 8, results)
        for case in results:
            with self.subTest(case=case["case"]):
                self.assertGreater(case["compared"], 4000, case)
                self.assertEqual(case["node_mismatches"], [], case)
                if rendered_run and case["rendered"]:
                    self.assertEqual(case["pixel_mismatches"], [], case)


if __name__ == "__main__":
    unittest.main()
