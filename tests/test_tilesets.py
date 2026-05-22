# pyright: reportPrivateUsage=false

import os
import sys
import shutil
import tempfile
import unittest
from typing import cast

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image
from src.conversion.tilesets import TileSetConverter, TilesetData


def _make_tileset_yy_content(name: str, sprite_name: str, tile_width: int = 16, tile_height: int = 16,
                              tilehsep: int = 0, tilevsep: int = 0, tilexoff: int = 0, tileyoff: int = 0,
                              tile_count: int = 2, out_columns: int = 1,
                              parent_path: str = "folders/Tilesets.yy") -> str:
    """Build a GameMaker tileset .yy file string."""
    return (
        '{{\n'
        '  "$GMTileSet": "v1",\n'
        '  "%Name": "{name}",\n'
        '  "spriteId": {{"name": "{sprite_name}", "path": "sprites/{sprite_name}/{sprite_name}.yy",}},\n'
        '  "tileWidth": {tile_width},\n'
        '  "tileHeight": {tile_height},\n'
        '  "tilehsep": {tilehsep},\n'
        '  "tilevsep": {tilevsep},\n'
        '  "tilexoff": {tilexoff},\n'
        '  "tileyoff": {tileyoff},\n'
        '  "tile_count": {tile_count},\n'
        '  "out_columns": {out_columns},\n'
        '  "tileAnimationFrames": [],\n'
        '  "tileAnimationSpeed": 15.0,\n'
        '  "parent": {{"name": "Tilesets", "path": "{parent_path}",}},\n'
        '  "resourceType": "GMTileSet",\n'
        '  "resourceVersion": "2.0",\n'
        '}}'
    ).format(
        name=name, sprite_name=sprite_name,
        tile_width=tile_width, tile_height=tile_height,
        tilehsep=tilehsep, tilevsep=tilevsep,
        tilexoff=tilexoff, tileyoff=tileyoff,
        tile_count=tile_count, out_columns=out_columns,
        parent_path=parent_path,
    )


def _make_sprite_for_tileset(gm_dir: str, sprite_name: str, width: int = 64, height: int = 64) -> None:
    """Create a minimal sprite directory with a .yy and a single-frame PNG image.

    The structure matches what TileSetConverter._find_sprite_image expects:
      sprites/{sprite_name}/{sprite_name}.yy
      sprites/{sprite_name}/layers/{frame_guid}/{layer_guid}.png
    """
    frame_guid = "aaaaaaaa-0000-0000-0000-000000000001"
    layer_guid = "bbbbbbbb-0000-0000-0000-000000000001"

    sprite_dir = os.path.join(gm_dir, "sprites", sprite_name)
    os.makedirs(sprite_dir, exist_ok=True)

    # Write sprite .yy
    yy_content = (
        '{{\n'
        '  "frames": [{{"$GMSpriteFrame":"v1","%Name":"{frame_guid}","name":"{frame_guid}",'
        '"resourceType":"GMSpriteFrame","resourceVersion":"2.0",}}],\n'
        '  "layers": [{{"$GMImageLayer":"","name":"{layer_guid}","displayName":"Layer 0",'
        '"opacity":100.0,"visible":true,"resourceType":"GMImageLayer","resourceVersion":"2.0",}}],\n'
        '  "name": "{sprite_name}",\n'
        '  "width": {width},\n'
        '  "height": {height},\n'
        '  "resourceType": "GMSprite",\n'
        '  "resourceVersion": "2.0",\n'
        '}}'
    ).format(
        frame_guid=frame_guid, layer_guid=layer_guid,
        sprite_name=sprite_name, width=width, height=height,
    )
    with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w") as f:
        f.write(yy_content)

    # Create the image
    layer_dir = os.path.join(sprite_dir, "layers", frame_guid)
    os.makedirs(layer_dir, exist_ok=True)
    img = Image.new("RGBA", (width, height), "blue")
    img.save(os.path.join(layer_dir, layer_guid + ".png"), "PNG")


class TestTileSetConverterBasic(unittest.TestCase):
    """Test TileSetConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create a tileset that references a sprite
        tileset_dir = os.path.join(self.gm_dir, "tilesets", "ts_ground")
        os.makedirs(tileset_dir)
        yy_content = _make_tileset_yy_content("ts_ground", "s_ground",
                                               tile_width=16, tile_height=16,
                                               tile_count=4)
        with open(os.path.join(tileset_dir, "ts_ground.yy"), "w") as f:
            f.write(yy_content)

        # Create the referenced sprite
        _make_sprite_for_tileset(self.gm_dir, "s_ground", width=64, height=64)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_converts_tileset_to_godot_dir(self):
        converter = self._make_converter()
        converter.convert_all()

        godot_tileset_dir = os.path.join(self.godot_dir, "tilesets", "ts_ground")
        self.assertTrue(os.path.isdir(godot_tileset_dir),
                        "Expected tilesets/ts_ground directory in Godot project")

    def test_generates_tres_file(self):
        converter = self._make_converter()
        converter.convert_all()

        tres_path = os.path.join(self.godot_dir, "tilesets", "ts_ground", "ts_ground.tres")
        self.assertTrue(os.path.isfile(tres_path), "Expected .tres file to be generated")

        with open(tres_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('TileSet', content)
        self.assertIn('TileSetAtlasSource', content)
        self.assertIn('Vector2i(16, 16)', content)
        self.assertIn('0:0/0 = 0', content)
        self.assertIn('metadata/gamemaker_tileset_tile_count = 4', content)
        self.assertIn('metadata/gamemaker_tileset_animation_frames = []', content)

    def test_warns_when_preserving_tileset_metadata(self):
        yy_content = (
            '{\n'
            '  "$GMTileSet": "v1",\n'
            '  "%Name": "ts_ground",\n'
            '  "spriteId": {"name": "s_ground", "path": "sprites/s_ground/s_ground.yy",},\n'
            '  "tileWidth": 16,\n'
            '  "tileHeight": 16,\n'
            '  "tile_count": 2,\n'
            '  "out_columns": 2,\n'
            '  "tileAnimationFrames": [{"frames": [0, 1], "duration": 2,}],\n'
            '  "brushes": [{"name": "grass",}],\n'
            '  "autoTileSets": [{"name": "terrain",}],\n'
            '  "tileSetCollisions": [{"tileId": 1, "points": [[0, 0], [16, 0]],}],\n'
            '  "parent": {"name": "Tilesets", "path": "folders/Tilesets.yy",},\n'
            '  "resourceType": "GMTileSet",\n'
            '  "resourceVersion": "2.0",\n'
            '}'
        )
        with open(os.path.join(self.gm_dir, "tilesets", "ts_ground", "ts_ground.yy"), "w") as f:
            f.write(yy_content)

        converter = self._make_converter()
        converter.convert_all()

        self.assertTrue(any(
            "preserves animation frames, collision data, auto-tile metadata, brush metadata"
            in log
            for log in self.logs
        ))

    def test_copies_sprite_image(self):
        converter = self._make_converter()
        converter.convert_all()

        image_path = os.path.join(self.godot_dir, "tilesets", "ts_ground", "ts_ground.png")
        self.assertTrue(os.path.isfile(image_path),
                        "Expected PNG image to be copied to tileset output dir")


class TestTileSetConverterEmpty(unittest.TestCase):
    """Edge cases: missing tilesets dir and missing sprites."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_tilesets_no_crash(self):
        """No tilesets directory at all should log an error and not crash."""
        converter = TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing tilesets folder")

    def test_missing_sprite_logs_warning(self):
        """A tileset referencing a nonexistent sprite should log a warning, not crash."""
        tileset_dir = os.path.join(self.gm_dir, "tilesets", "ts_broken")
        os.makedirs(tileset_dir)
        yy_content = _make_tileset_yy_content("ts_broken", "s_nonexistent")
        with open(os.path.join(tileset_dir, "ts_broken.yy"), "w") as f:
            f.write(yy_content)

        converter = TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        # The .tres file should NOT be created since the sprite is missing
        tres_path = os.path.join(self.godot_dir, "tilesets", "ts_broken", "ts_broken.tres")
        self.assertFalse(os.path.isfile(tres_path),
                         "Should not generate .tres when sprite is missing")


class TestParseTilesetYY(unittest.TestCase):
    """Test _parse_tileset_yy directly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_tileset_yy(self, tileset_name: str, content: str) -> None:
        tileset_dir = os.path.join(self.gm_dir, "tilesets", tileset_name)
        os.makedirs(tileset_dir, exist_ok=True)
        with open(os.path.join(tileset_dir, tileset_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_valid_tileset(self):
        content = _make_tileset_yy_content("ts_test", "s_test",
                                            tile_width=32, tile_height=32,
                                            tile_count=8)
        self._write_tileset_yy("ts_test", content)

        result = self.converter._parse_tileset_yy("ts_test")
        self.assertIsNotNone(result)
        result = cast(TilesetData, result)
        self.assertEqual(result["sprite_name"], "s_test")
        self.assertEqual(result["tileWidth"], 32)
        self.assertEqual(result["tileHeight"], 32)
        self.assertEqual(result["tile_count"], 8)

    def test_returns_none_for_missing(self):
        result = self.converter._parse_tileset_yy("nonexistent_tileset")
        self.assertIsNone(result)

    def test_handles_trailing_commas(self):
        # Content with trailing commas (like real GameMaker .yy files)
        content = (
            '{\n'
            '  "spriteId": {"name": "s_tc", "path": "sprites/s_tc/s_tc.yy",},\n'
            '  "tileWidth": 16,\n'
            '  "tileHeight": 16,\n'
            '  "tilehsep": 0,\n'
            '  "tilevsep": 0,\n'
            '  "tilexoff": 0,\n'
            '  "tileyoff": 0,\n'
            '  "tile_count": 2,\n'
            '}'
        )
        self._write_tileset_yy("ts_tc", content)

        result = self.converter._parse_tileset_yy("ts_tc")
        self.assertIsNotNone(result)
        result = cast(TilesetData, result)
        self.assertEqual(result["sprite_name"], "s_tc")
        self.assertEqual(result["tileWidth"], 16)

    def test_preserves_animation_collision_and_autotile_metadata(self):
        content = (
            '{\n'
            '  "spriteId": {"name": "s_meta", "path": "sprites/s_meta/s_meta.yy",},\n'
            '  "tileWidth": 16,\n'
            '  "tileHeight": 16,\n'
            '  "tile_count": 2,\n'
            '  "out_columns": 2,\n'
            '  "tileAnimationFrames": [{"frames": [0, 1], "duration": 2,}],\n'
            '  "tileAnimationSpeed": 12.5,\n'
            '  "brushes": [{"name": "grass",}],\n'
            '  "autoTileSets": [{"name": "terrain",}],\n'
            '  "tileSetCollisions": [{"tileId": 1, "points": [[0, 0], [16, 0]],}],\n'
            '  "out_tilehborder": 1,\n'
            '  "out_tilevborder": 2,\n'
            '}'
        )
        self._write_tileset_yy("ts_meta", content)

        result = self.converter._parse_tileset_yy("ts_meta")
        self.assertIsNotNone(result)
        result = cast(TilesetData, result)
        self.assertEqual(result["tileAnimationSpeed"], 12.5)
        self.assertEqual(result["out_tilehborder"], 1)
        tres = self.converter._generate_tileset_tres("ts_meta", result)
        self.assertIn('metadata/gamemaker_tileset_animation_speed = 12.5', tres)
        self.assertIn('metadata/gamemaker_tileset_animation_frames = [{"frames": [0, 1], "duration": 2}]', tres)
        self.assertIn('metadata/gamemaker_tileset_auto_tile_sets = [{"name": "terrain"}]', tres)
        self.assertIn('metadata/gamemaker_tileset_collisions = [{"tileId": 1', tres)


class TestTileSetConverterSubfolders(unittest.TestCase):
    """Test that tilesets respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        tileset_dir = os.path.join(self.gm_dir, "tilesets", "ts_terrain")
        os.makedirs(tileset_dir)
        yy_content = _make_tileset_yy_content("ts_terrain", "s_terrain",
                                               tile_width=16, tile_height=16,
                                               tile_count=4,
                                               parent_path="folders/Tilesets/World.yy")
        with open(os.path.join(tileset_dir, "ts_terrain.yy"), "w") as f:
            f.write(yy_content)

        _make_sprite_for_tileset(self.gm_dir, "s_terrain", width=64, height=64)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_tileset_in_subfolder(self):
        converter = TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        tres_path = os.path.join(self.godot_dir, "tilesets", "World", "ts_terrain", "ts_terrain.tres")
        self.assertTrue(os.path.isfile(tres_path),
                        f"Expected tileset at {tres_path}")

    def test_tileset_tres_has_subfolder_res_path(self):
        converter = TileSetConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        tres_path = os.path.join(self.godot_dir, "tilesets", "World", "ts_terrain", "ts_terrain.tres")
        with open(tres_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('res://tilesets/World/ts_terrain/ts_terrain.png', content)


if __name__ == "__main__":
    unittest.main()
