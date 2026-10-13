"""Tiles of a converted game are the cells GameMaker draws and collides with.

GameMaker's tile N is cell N of the tileset's source sprite, in the sprite's
own grid and counted from 0 at the top-left cell, the always-empty tile 0
(Tile_Sets.htm; the runner's tilemap collisions use
numtilesperrow = spr.GetWidth() / (tilewidth + tilehsep) and tile N -> sprite
cell N, Function_Instance.js; tilemap_set refuses an index >= tilecount,
Function_Layers.js). The tileset's out_columns describe the compiled texture
page (tileset_get_info), not the numbering.

The project has two tilesets whose cells are told apart by colour: ts_tiles
(4 x 3 cells) and ts_wide (8 x 2 cells with out_columns 4, unlike the 8 of its
sprite). Odd cells of their sprites are opaque all over, even cells only in
the top half, so that the same sprite cell says, through a position test of
the bottom half, whether a tile collides there. Tiles come from a room tile
layer, tilemap_set and draw_tile, some with flip, mirror and custom bits. The
probe reads the colour of the rendered pixels (under xvfb), the colour of the
atlas cell each TileMapLayer cell uses, and what tilemap_get and
position_meeting say, and the test compares them with that model.
"""
from __future__ import annotations

import itertools
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

from tests.gamemaker_project_support import (
    EVENT_CREATE,
    BackgroundLayer,
    GameMakerObject,
    GameMakerProject,
    GameMakerRoom,
    GameMakerSprite,
    InstanceLayer,
    RoomInstance,
    add_probe_autoload,
    convert_gamemaker_project,
    import_converted_project,
    run_converted_project,
    run_converted_project_rendered,
    write_gamemaker_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_Pixel = tuple[int, int, int, int]
_Rgb = tuple[int, int, int]

_CELL = 16
_MIRROR = 1 << 28
_FLIP = 1 << 29
_CUSTOM = 1 << 20
_GODOT_FLIP_H = 1 << 12
_GODOT_FLIP_V = 1 << 13
_EVENT_DRAW = (8, 0)
_BLACK: _Rgb = (0, 0, 0)

_LEVELS = (0, 85, 170, 255)
# 28 distinct colours, neither the black room background nor white.
_PALETTE: list[_Rgb] = [
    (red, green, blue)
    for red, green, blue in itertools.product(_LEVELS, repeat=3)
    if (red, green, blue) not in (_BLACK, (255, 255, 255))
][::2][:28]


class _Results(TypedDict):
    # Pixel colours at the probe points; the [x, y, red, green, blue, alternative]
    # of every cell of each TileMapLayer, by the name of its layer.
    pixels: list[list[int]]
    layers: dict[str, list[list[int]]]


@dataclass(frozen=True)
class _Tileset:
    name: str
    sprite: str
    columns: int  # cells per row of the sprite
    rows: int
    palette_base: int
    out_columns: int  # the compiled texture page's, not the sprite's

    @property
    def tile_count(self) -> int:
        return self.columns * self.rows


_TILES = _Tileset("ts_tiles", "s_tiles", 4, 3, 0, 4)
_WIDE = _Tileset("ts_wide", "s_wide", 8, 2, 12, 4)
_TILESETS = (_TILES, _WIDE)


def _cell_colour(tileset: _Tileset, tile: int) -> _Rgb:
    return _PALETTE[tileset.palette_base + tile]


def _solid_half(tile: int, flags: int) -> tuple[bool, bool]:
    """Whether the (top, bottom) half of a placed tile is opaque and collides."""
    if tile % 2 == 1:
        return True, True
    return (False, True) if flags & _FLIP else (True, False)


def _sprite_image(tileset: _Tileset) -> list[list[_Pixel]]:
    rows: list[list[_Pixel]] = []
    for y in range(tileset.rows * _CELL):
        row: list[_Pixel] = []
        for x in range(tileset.columns * _CELL):
            cell = (y // _CELL) * tileset.columns + x // _CELL
            red, green, blue = _cell_colour(tileset, cell)
            opaque = cell % 2 == 1 or y % _CELL < _CELL // 2
            row.append((red, green, blue, 255 if opaque else 0))
        rows.append(row)
    return rows


@dataclass(frozen=True)
class _Placed:
    layer: str
    tileset: _Tileset
    column: int
    row: int
    tile: int
    flags: int = 0
    custom: int = 0

    @property
    def data(self) -> int:
        return self.tile | self.flags | self.custom


# Row 0 of the room tile layer "Tiles", row 3 of the room tile layer "Wide".
_AUTHORED_TILES = [
    _Placed("Tiles", _TILES, column, 0, tile, flags, custom)
    for column, (tile, flags, custom) in enumerate(
        [(1, 0, 0), (2, 0, 0), (5, 0, 0), (4, 0, 0), (9, 0, 0), (11, 0, 0), (4, _FLIP, 0), (3, _MIRROR, _CUSTOM)]
    )
]
_AUTHORED_WIDE = [
    _Placed("Wide", _WIDE, column, 3, tile) for column, tile in enumerate([1, 3, 9, 12, 15])
]
# Row 1 of "Tiles", set by tilemap_set when the instance is created.
_SET_TILES = [
    _Placed("Tiles", _TILES, 0, 1, 3),
    _Placed("Tiles", _TILES, 1, 1, 6),
    _Placed("Tiles", _TILES, 2, 1, 8, _FLIP),
    _Placed("Tiles", _TILES, 3, 1, 11, _MIRROR | _FLIP),
]
# Row 2, drawn by draw_tile.
_DRAWN_TILES = [
    _Placed("", _TILES, 0, 2, 1),
    _Placed("", _TILES, 1, 2, 5),
    _Placed("", _TILES, 2, 2, 10),
    _Placed("", _TILES, 3, 2, 4, _FLIP),
]

_CREATE = """
var tiles = layer_tilemap_get_id(layer_get_id("Tiles"));
var wide = layer_tilemap_get_id(layer_get_id("Wide"));
tilemap_set(tiles, 3, 0, 1);
tilemap_set(tiles, 6, 1, 1);
tilemap_set(tiles, 8 | tile_flip, 2, 1);
tilemap_set(tiles, 11 | tile_mirror | tile_flip, 3, 1);
// A tile past the tileset's tile count is refused, and tile 0 is empty.
tilemap_set(tiles, 12, 4, 1);
tilemap_set(tiles, 0, 5, 1);
var maps = [tiles, tiles, wide];
var map_rows = [0, 1, 3];
var states = "";
for (var k = 0; k < 3; k++) {
    for (var column = 0; column < 8; column++) {
        var left = column * 16;
        var top = map_rows[k] * 16;
        states += string(tilemap_get(maps[k], column, map_rows[k]));
        states += "/" + string(position_meeting(left + 8, top + 4, maps[k]) ? 1 : 0);
        states += string(position_meeting(left + 8, top + 12, maps[k]) ? 1 : 0) + " ";
    }
    states += "| ";
}
show_debug_message("TILE_STATE " + states);
"""
_DRAW = """
draw_tile(ts_tiles, 1, 0, 0, 32);
draw_tile(ts_tiles, 5, 0, 16, 32);
draw_tile(ts_tiles, 10, 0, 32, 32);
draw_tile(ts_tiles, 4 | tile_flip, 0, 48, 32);
"""

_MAP_WIDTH, _MAP_HEIGHT = 10, 6


def _project() -> GameMakerProject:
    return GameMakerProject(
        name="TileAtlas",
        objects=(GameMakerObject("o_runtime", {EVENT_CREATE: _CREATE, _EVENT_DRAW: _DRAW}),),
        sprites=tuple(
            GameMakerSprite(
                tileset.sprite,
                tileset.columns * _CELL,
                tileset.rows * _CELL,
                frames=(_sprite_image(tileset),),
                collision_kind=0,
            )
            for tileset in _TILESETS
        ),
        rooms=(
            GameMakerRoom(
                "r_tiles",
                layers=(
                    InstanceLayer("Instances", 0, (RoomInstance("inst_runtime", "o_runtime", 200, 200),)),
                    BackgroundLayer("Back", 300, colour=0xFF000000),
                ),
                creation_order=("inst_runtime",),
                width=160,
                height=96,
            ),
        ),
    )


def _tile_layer(name: str, depth: int, tileset: _Tileset, placed: list[_Placed]) -> dict[str, object]:
    cells = [0] * (_MAP_WIDTH * _MAP_HEIGHT)
    for tile in placed:
        cells[tile.row * _MAP_WIDTH + tile.column] = tile.data
    # TileDataFormat 1 repeat runs only, [-count, value]; every cell on its own here.
    compressed = [entry for cell in cells for entry in (-1, cell)]
    return {
        "$GMRTileLayer": "",
        "%Name": name,
        "depth": depth,
        "effectEnabled": True,
        "effectType": None,
        "gridX": _CELL,
        "gridY": _CELL,
        "hierarchyFrozen": False,
        "inheritLayerDepth": False,
        "inheritLayerSettings": False,
        "inheritSubLayers": True,
        "inheritVisibility": True,
        "layers": [],
        "name": name,
        "properties": [],
        "resourceType": "GMRTileLayer",
        "resourceVersion": "2.0",
        "tiles": {
            "SerialiseHeight": _MAP_HEIGHT,
            "SerialiseWidth": _MAP_WIDTH,
            "TileCompressedData": compressed,
            "TileDataFormat": 1,
        },
        "tilesetId": {"name": tileset.name, "path": f"tilesets/{tileset.name}/{tileset.name}.yy"},
        "userdefinedDepth": False,
        "visible": True,
        "x": 0,
        "y": 0,
    }


def _tileset_yy(tileset: _Tileset) -> dict[str, object]:
    return {
        "$GMTileSet": "v1",
        "%Name": tileset.name,
        "autoTileSets": [],
        "macroPageTiles": {"SerialiseHeight": 0, "SerialiseWidth": 0, "TileSerialiseData": []},
        "name": tileset.name,
        "out_columns": tileset.out_columns,
        "out_tilehborder": 2,
        "out_tilevborder": 2,
        "parent": {"name": "Tile Sets", "path": "folders/Tile Sets.yy"},
        "resourceType": "GMTileSet",
        "resourceVersion": "2.0",
        "spriteId": {"name": tileset.sprite, "path": f"sprites/{tileset.sprite}/{tileset.sprite}.yy"},
        "spriteNoExport": True,
        "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
        "tile_count": tileset.tile_count,
        "tileAnimationFrames": [],
        "tileAnimationSpeed": 15.0,
        "tileHeight": _CELL,
        "tilehsep": 0,
        "tilevsep": 0,
        "tileWidth": _CELL,
        "tilexoff": 0,
        "tileyoff": 0,
        "tileSetCollisions": [],
    }


def _write_tiles(gamemaker_dir: Path) -> None:
    """Add the tilesets and the room's tile layers, which the support module has no model for."""
    for tileset in _TILESETS:
        path = gamemaker_dir / "tilesets" / tileset.name / f"{tileset.name}.yy"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_tileset_yy(tileset), indent=1), encoding="utf-8")
    project_path = gamemaker_dir / "TileAtlas.yyp"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    for tileset in _TILESETS:
        project["resources"].append({"id": {"name": tileset.name, "path": f"tilesets/{tileset.name}/{tileset.name}.yy"}})
    project_path.write_text(json.dumps(project, indent=1), encoding="utf-8")
    room_path = gamemaker_dir / "rooms" / "r_tiles" / "r_tiles.yy"
    room = json.loads(room_path.read_text(encoding="utf-8"))
    room["layers"].insert(1, _tile_layer("Tiles", 100, _TILES, _AUTHORED_TILES))
    room["layers"].insert(2, _tile_layer("Wide", 150, _WIDE, _AUTHORED_WIDE))
    room_path.write_text(json.dumps(room, indent=1), encoding="utf-8")


# Probe points are the middle of a cell's top half and of its bottom half.
_PROBE = """extends Node

var _frames = 0
var _done = false
const POINTS = %s


func _ready():
	RenderingServer.frame_post_draw.connect(_post_draw)


func _process(_delta):
	_frames += 1
	if _frames > 400:
		print("TILE_TIMEOUT")
		get_tree().quit(1)


func _post_draw():
	if _done or _frames < 10:
		return
	var scene = get_tree().current_scene
	if scene == null or scene.name != "r_tiles":
		return
	_done = true
	var pixels = []
	if DisplayServer.get_name() != "headless":
		get_tree().root.canvas_item_default_texture_filter = Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST
		var image = get_viewport().get_texture().get_image()
		if image != null and not image.is_empty():
			var canvas = get_viewport().get_canvas_transform()
			for point in POINTS:
				var p = canvas * Vector2(point[0], point[1])
				var c = image.get_pixel(int(p.x), int(p.y))
				pixels.append([int(round(c.r * 255)), int(round(c.g * 255)), int(round(c.b * 255))])
	var layers = {}
	for layer in scene.find_children("*", "TileMapLayer", true, false):
		var source = layer.tile_set.get_source(0)
		var texture_image = source.texture.get_image()
		var cells = []
		for coords in layer.get_used_cells():
			var atlas = layer.get_cell_atlas_coords(coords)
			var region = source.get_tile_texture_region(atlas)
			var c = texture_image.get_pixelv(region.position + Vector2i(8, 4))
			cells.append([coords.x, coords.y, int(round(c.r * 255)), int(round(c.g * 255)), int(round(c.b * 255)), layer.get_cell_alternative_tile(coords)])
		layers[str(layer.get_parent().name)] = cells
	print("TILE_RESULTS " + JSON.stringify({"pixels": pixels, "layers": layers}))
	get_tree().quit(0)
"""


def _probe_points(placed: list[_Placed]) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for tile in placed:
        for y in (4, 12):
            points.append((tile.column * _CELL + 8, tile.row * _CELL + y))
    return points


def _expected_pixels(placed: list[_Placed]) -> list[_Rgb]:
    expected: list[_Rgb] = []
    for tile in placed:
        colour = _cell_colour(tile.tileset, tile.tile)
        for opaque in _solid_half(tile.tile, tile.flags):
            expected.append(colour if opaque else _BLACK)
    return expected


def _alternative(flags: int) -> int:
    return (_GODOT_FLIP_H if flags & _MIRROR else 0) | (_GODOT_FLIP_V if flags & _FLIP else 0)


def _run(godot_binary: str) -> tuple[_Results, str, bool]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        write_gamemaker_project(root / "gamemaker", _project())
        _write_tiles(root / "gamemaker")
        convert_gamemaker_project(root / "gamemaker", root / "godot")
        add_probe_autoload(root / "godot", _PROBE % json.dumps(_probe_points(_ALL_PLACED)))
        imported = import_converted_project(godot_binary, root / "godot")
        if imported.returncode != 0:
            raise AssertionError(imported.stdout + imported.stderr)
        result = run_converted_project_rendered(godot_binary, root / "godot", timeout=120)
        rendered_run = result is not None
        if result is None:
            result = run_converted_project(godot_binary, root / "godot")
        output = result.stdout + result.stderr
    if result.returncode != 0:
        raise AssertionError(output)
    lines = [line for line in output.splitlines() if line.startswith("TILE_RESULTS ")]
    if len(lines) != 1:
        raise AssertionError(output)
    return cast(_Results, json.loads(lines[0].removeprefix("TILE_RESULTS "))), output, rendered_run


_ALL_PLACED = _AUTHORED_TILES + _SET_TILES + _DRAWN_TILES + _AUTHORED_WIDE


class TestTileAtlasGodot(unittest.TestCase):
    results: _Results
    output: str
    rendered_run: bool

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        cls.results, cls.output, cls.rendered_run = _run(godot_binary)

    def test_no_script_errors(self) -> None:
        self.assertNotIn("SCRIPT ERROR", self.output)
        self.assertNotIn("Cannot create tile", self.output)
        self.assertNotIn("TILE_TIMEOUT", self.output)

    def test_every_tile_layer_cell_uses_the_sprite_cell_of_its_tile_number(self) -> None:
        layers = self.results["layers"]
        for layer_name in ("Tiles", "Wide"):
            placed = [tile for tile in _AUTHORED_TILES + _SET_TILES + _AUTHORED_WIDE if tile.layer == layer_name]
            cells = {(cell[0], cell[1]): tuple(cell[2:]) for cell in layers[layer_name]}
            self.assertEqual(sorted(cells), sorted((tile.column, tile.row) for tile in placed), layer_name)
            for tile in placed:
                with self.subTest(layer=layer_name, column=tile.column, row=tile.row, tile=tile.tile):
                    red, green, blue, alternative = cells[(tile.column, tile.row)]
                    # The colour of the atlas cell is that of sprite cell N.
                    self.assertEqual((red, green, blue), _cell_colour(tile.tileset, tile.tile))
                    self.assertEqual(alternative, _alternative(tile.flags))

    def test_rendered_pixels_show_the_sprite_cell_of_each_tile_number(self) -> None:
        pixels = self.results["pixels"]
        if not self.rendered_run or not pixels:
            self.skipTest("no OpenGL renderer (xvfb-run) to read pixels from")
        expected = _expected_pixels(_ALL_PLACED)
        points = _probe_points(_ALL_PLACED)
        self.assertEqual(len(pixels), len(expected))
        for point, drawn, wanted in zip(points, pixels, expected, strict=True):
            tile = next(
                candidate for candidate in _ALL_PLACED
                if (candidate.column, candidate.row) == (point[0] // _CELL, point[1] // _CELL)
            )
            with self.subTest(cell=(tile.column, tile.row), tile=tile.tile, flags=tile.flags, y=point[1] % _CELL):
                self.assertEqual(tuple(drawn), wanted)

    def test_collisions_and_tilemap_get_agree_with_the_drawn_tiles(self) -> None:
        line = next(row for row in self.output.splitlines() if "TILE_STATE " in row)
        groups = [group.split() for group in line.split("TILE_STATE ", 1)[1].split("|") if group.strip()]
        self.assertEqual(len(groups), 3, line)
        expectations: dict[tuple[int, int], tuple[int, int, int]] = {}
        for tile in _AUTHORED_TILES + _SET_TILES + _AUTHORED_WIDE:
            top, bottom = _solid_half(tile.tile, tile.flags)
            expectations[(tile.column, tile.row)] = (tile.data, int(top), int(bottom))
        for group, row in zip(groups, (0, 1, 3), strict=True):
            self.assertEqual(len(group), 8, group)
            for column, state in enumerate(group):
                value, _separator, solid = state.partition("/")
                wanted_value, wanted_top, wanted_bottom = expectations.get((column, row), (0, 0, 0))
                with self.subTest(row=row, column=column):
                    # A flipped even tile collides in its bottom half, an odd one throughout:
                    # exactly where the sprite cell is opaque, which is where it is drawn.
                    self.assertEqual((int(value), solid), (wanted_value, f"{wanted_top}{wanted_bottom}"))


if __name__ == "__main__":
    unittest.main()
