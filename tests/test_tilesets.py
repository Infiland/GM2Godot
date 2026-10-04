# pyright: reportPrivateUsage=false

import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest
from typing import cast
from unittest.mock import MagicMock, patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.tileset_metadata import (
    GameMakerTilesetMetadata,
    parse_gamemaker_tileset_metadata,
)
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

    def test_resource_outcome_counts_logical_tileset(self):
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result().resources

        self.assertEqual(counts.requested, 1)
        self.assertEqual(counts.executed, 1)
        self.assertEqual(counts.completed, 1)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)

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


class TestTileSetSourceContainment(unittest.TestCase):
    FRAME_GUID = "aaaaaaaa-0000-0000-0000-000000000001"
    LAYER_GUID = "bbbbbbbb-0000-0000-0000-000000000001"

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(self) -> TileSetConverter:
        return TileSetConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=self.diagnostics,
        )

    def _write_json(self, path: str, value: object) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output_file:
            json.dump(value, output_file)

    def _write_tileset(
        self,
        path: str,
        name: str,
        sprite_id: object,
        *,
        tile_width: int = 16,
        tile_height: int = 16,
    ) -> None:
        self._write_json(
            path,
            {
                "$GMTileSet": "v1",
                "%Name": name,
                "spriteId": sprite_id,
                "tileWidth": tile_width,
                "tileHeight": tile_height,
                "tile_count": 4,
                "out_columns": 2,
                "parent": {
                    "name": "Tilesets",
                    "path": "folders/Tilesets.yy",
                },
                "resourceType": "GMTileSet",
                "resourceVersion": "2.0",
            },
        )

    def _write_sprite(
        self,
        yy_path: str,
        *,
        color: str,
        width: int = 48,
        height: int = 40,
    ) -> str:
        self._write_json(
            yy_path,
            {
                "frames": [{"name": self.FRAME_GUID}],
                "layers": [{"name": self.LAYER_GUID, "visible": True}],
                "resourceType": "GMSprite",
                "resourceVersion": "2.0",
            },
        )
        image_path = os.path.join(
            os.path.dirname(yy_path),
            "layers",
            self.FRAME_GUID,
            self.LAYER_GUID + ".png",
        )
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        Image.new("RGBA", (width, height), color).save(image_path, "PNG")
        return image_path

    def test_manifest_discovery_reads_selected_yyp_once(self) -> None:
        yyp_path = os.path.join(self.gm_dir, "TileSetPaths.yyp")
        self._write_json(yyp_path, {"resources": []})

        with patch("builtins.open", wraps=open) as tracked_open:
            valid_tilesets = self._make_converter()._get_valid_tileset_names()

        self.assertEqual(valid_tilesets, {})
        yyp_reads = [
            call
            for call in tracked_open.call_args_list
            if call.args
            and isinstance(call.args[0], (str, os.PathLike))
            and os.path.abspath(os.fspath(call.args[0])) == yyp_path
        ]
        self.assertEqual(len(yyp_reads), 1, yyp_reads)

    def test_missing_only_declared_tileset_makes_conversion_partial(self) -> None:
        missing_resource = {
            "id": {
                "name": "ts_missing",
                "path": "tilesets/ts_missing/ts_missing.yy",
                "resourceType": "GMTileSet",
            },
            "resourceType": "GMTileSet",
        }
        self._write_json(
            os.path.join(self.gm_dir, "MissingTileset.yyp"),
            {
                "resources": [missing_resource, missing_resource],
                "resourceType": "GMProject",
            },
        )
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        tilesets_enabled = MagicMock()
        tilesets_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"tilesets": tilesets_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, skipped=1),
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-TILESET-SOURCE-UNAVAILABLE"
                and diagnostic.resource == "ts_missing"
                for diagnostic in converter.diagnostics.diagnostics()
            )
        )
        self.assertTrue(
            any(
                "Skipping manifest-declared GameMaker tileset 'ts_missing'"
                in log
                for log in self.logs
            )
        )

    def test_safe_and_missing_declared_tilesets_have_strict_counts(self) -> None:
        safe_name = "ts_safe"
        safe_sprite = "s_safe"
        self._write_tileset(
            os.path.join(
                self.gm_dir,
                "tilesets",
                safe_name,
                safe_name + ".yy",
            ),
            safe_name,
            {
                "name": safe_sprite,
                "path": f"sprites/{safe_sprite}/{safe_sprite}.yy",
            },
        )
        self._write_sprite(
            os.path.join(
                self.gm_dir,
                "sprites",
                safe_sprite,
                safe_sprite + ".yy",
            ),
            color="green",
        )
        self._write_json(
            os.path.join(self.gm_dir, "MixedTilesets.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": safe_name,
                            "path": f"tilesets/{safe_name}/{safe_name}.yy",
                        }
                    },
                    {
                        "id": {
                            "name": "ts_missing",
                            "path": "tilesets/ts_missing/ts_missing.yy",
                        }
                    },
                ],
                "resourceType": "GMProject",
            },
        )
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "tilesets",
                    safe_name,
                    safe_name + ".tres",
                )
            )
        )
        unavailable = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-TILESET-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "ts_missing")
        self.assertEqual(unavailable[0].source_path, "MixedTilesets.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "resources[1].id.path",
        )

    def test_rejected_and_cross_family_declared_tilesets_are_skipped(self) -> None:
        cross_family_path = "objects/ts_cross_family/ts_cross_family.yy"
        self._write_json(
            os.path.join(self.gm_dir, *cross_family_path.split("/")),
            {"resourceType": "GMTileSet"},
        )
        orphan_name = "ts_orphan"
        orphan_sprite = "s_orphan"
        self._write_tileset(
            os.path.join(
                self.gm_dir,
                "tilesets",
                orphan_name,
                orphan_name + ".yy",
            ),
            orphan_name,
            {
                "name": orphan_sprite,
                "path": f"sprites/{orphan_sprite}/{orphan_sprite}.yy",
            },
        )
        self._write_sprite(
            os.path.join(
                self.gm_dir,
                "sprites",
                orphan_sprite,
                orphan_sprite + ".yy",
            ),
            color="blue",
        )
        self._write_json(
            os.path.join(self.gm_dir, "RejectedTilesets.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "ts_rejected",
                            "path": "tilesets/../../outside/ts_rejected.yy",
                            "resourceType": "GMTileSet",
                        }
                    },
                    {
                        "id": {
                            "name": "ts_cross_family",
                            "path": cross_family_path,
                            "resourceType": "GMTileSet",
                        }
                    },
                ],
                "resourceType": "GMProject",
            },
        )
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, skipped=2),
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "tilesets", orphan_name)
            )
        )
        unavailable = [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-TILESET-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(
            {diagnostic.resource for diagnostic in unavailable},
            {"ts_rejected", "ts_cross_family"},
        )
        rejected = [
            diagnostic
            for diagnostic in self._source_path_rejections()
            if diagnostic.resource in {"ts_rejected", "ts_cross_family"}
        ]
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            {"ts_rejected", "ts_cross_family"},
        )

    def _source_path_rejections(self):
        return [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def test_declared_tileset_and_sprite_paths_override_name_reconstruction(self) -> None:
        declared_tileset = os.path.join(
            self.gm_dir,
            "tilesets",
            "declared",
            "custom_tileset.yy",
        )
        declared_sprite = os.path.join(
            self.gm_dir,
            "sprites",
            "declared",
            "custom_sprite.yy",
        )
        self._write_tileset(
            declared_tileset,
            "ts_declared",
            {
                "name": "s_decoy",
                "path": "sprites/declared/custom_sprite.yy",
            },
            tile_width=24,
            tile_height=20,
        )
        self._write_sprite(declared_sprite, color="red")

        reconstructed_tileset = os.path.join(
            self.gm_dir,
            "tilesets",
            "ts_declared",
            "ts_declared.yy",
        )
        self._write_tileset(
            reconstructed_tileset,
            "ts_declared",
            {"name": "s_decoy", "path": "sprites/s_decoy/s_decoy.yy"},
            tile_width=8,
            tile_height=8,
        )
        decoy_sprite = os.path.join(
            self.gm_dir,
            "sprites",
            "s_decoy",
            "s_decoy.yy",
        )
        self._write_sprite(decoy_sprite, color="blue")
        self._write_json(
            os.path.join(self.gm_dir, "DeclaredPaths.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "ts_declared",
                            "path": "tilesets/declared/custom_tileset.yy",
                        }
                    }
                ],
                "resourceType": "GMProject",
            },
        )

        self._make_converter().convert_all()

        output_dir = os.path.join(self.godot_dir, "tilesets", "ts_declared")
        with open(
            os.path.join(output_dir, "ts_declared.tres"),
            "r",
            encoding="utf-8",
        ) as tres_file:
            tres = tres_file.read()
        self.assertIn("texture_region_size = Vector2i(24, 20)", tres)
        self.assertIn("tile_size = Vector2i(24, 20)", tres)
        with Image.open(os.path.join(output_dir, "ts_declared.png")) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_external_first_yyp_cannot_mask_contained_declared_tileset_path(self) -> None:
        declared_path = os.path.join(
            self.gm_dir,
            "tilesets",
            "nested",
            "custom_tileset.yy",
        )
        self._write_tileset(
            declared_path,
            "ts_inside",
            {"name": "s_inside", "path": "sprites/s_inside/s_inside.yy"},
        )
        self._write_json(
            os.path.join(self.gm_dir, "BInside.yyp"),
            {
                "resources": [
                    {
                        "id": {
                            "name": "ts_inside",
                            "path": "tilesets/nested/custom_tileset.yy",
                        }
                    }
                ],
                "resourceType": "GMProject",
            },
        )
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_yyp = os.path.join(outside_dir, "Outside.yyp")
            self._write_json(
                outside_yyp,
                {
                    "resources": [
                        {
                            "id": {
                                "name": "ts_outside",
                                "path": "tilesets/ts_outside/ts_outside.yy",
                            }
                        }
                    ]
                },
            )
            try:
                os.symlink(
                    outside_yyp,
                    os.path.join(self.gm_dir, "AOutside.yyp"),
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            converter = self._make_converter()
            valid_tilesets = converter._get_valid_tileset_names()

        self.assertEqual(valid_tilesets, {"ts_inside": ""})
        self.assertEqual(
            converter._tileset_source_paths,
            {"ts_inside": "tilesets/nested/custom_tileset.yy"},
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1)
        self.assertIsNone(rejected[0].source_path)
        self.assertEqual(rejected[0].resource_type, "project")
        self.assertEqual(rejected[0].manifest_entry, "AOutside.yyp")
        self.assertIn("AOutside.yyp", rejected[0].message)

    def test_non_file_first_yyp_is_rejected_with_source_link(self) -> None:
        os.makedirs(os.path.join(self.gm_dir, "ADirectory.yyp"))
        self._write_json(
            os.path.join(self.gm_dir, "BInside.yyp"),
            {"resources": [], "resourceType": "GMProject"},
        )

        valid_tilesets = self._make_converter()._get_valid_tileset_names()

        self.assertEqual(valid_tilesets, {})
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source_path, "ADirectory.yyp")
        self.assertEqual(rejected[0].resource_type, "project")
        self.assertEqual(rejected[0].manifest_entry, "ADirectory.yyp")

    def test_validates_and_preserves_legacy_sprite_name_fallback(self) -> None:
        tileset_path = os.path.join(
            self.gm_dir,
            "tilesets",
            "ts_legacy",
            "ts_legacy.yy",
        )
        self._write_tileset(
            tileset_path,
            "ts_legacy",
            {"name": "s_legacy"},
        )
        _make_sprite_for_tileset(self.gm_dir, "s_legacy", width=32, height=16)

        self._make_converter().convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "tilesets",
                    "ts_legacy",
                    "ts_legacy.tres",
                )
            )
        )
        self.assertEqual(self._source_path_rejections(), [])

    def test_rejects_malformed_sprite_reference_forms_with_owner_diagnostics(
        self,
    ) -> None:
        outside_sprite = os.path.join(self.outside_dir, "outside.yy")
        self._write_json(outside_sprite, {"frames": [], "layers": []})
        traversal_path = os.path.relpath(
            outside_sprite,
            os.path.join(self.gm_dir, "tilesets", "ts_traversal"),
        )
        cross_family_path = "objects/o_decoy/o_decoy.yy"
        self._write_json(
            os.path.join(self.gm_dir, *cross_family_path.split("/")),
            {"resourceType": "GMObject"},
        )
        cases: list[tuple[str, object, str]] = [
            ("ts_absolute", {"path": outside_sprite}, "spriteId.path"),
            ("ts_traversal", {"path": traversal_path}, "spriteId.path"),
            (
                "ts_drive_absolute",
                {"path": r"C:\Games\Outside\sprite.yy"},
                "spriteId.path",
            ),
            (
                "ts_drive_relative",
                {"path": r"C:Outside\sprite.yy"},
                "spriteId.path",
            ),
            (
                "ts_unc",
                {"path": r"\\server\share\sprite.yy"},
                "spriteId.path",
            ),
            ("ts_nul", {"path": "bad\0sprite.yy"}, "spriteId.path"),
            ("ts_non_string", {"path": 7}, "spriteId.path"),
            (
                "ts_cross_family",
                {"path": cross_family_path},
                "spriteId.path",
            ),
            ("ts_bad_legacy", {"name": "../outside"}, "spriteId.name"),
            ("ts_not_object", ["sprites/s_safe/s_safe.yy"], "spriteId"),
        ]
        for name, sprite_id, _field in cases:
            tileset_path = os.path.join(
                self.gm_dir,
                "tilesets",
                name,
                name + ".yy",
            )
            self._write_tileset(tileset_path, name, sprite_id)

        converter = self._make_converter()
        for name, _sprite_id, _field in cases:
            result = converter._process_tileset(name)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertFalse(result["success"])

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), len(cases), rejected)
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            {name for name, _sprite_id, _field in cases},
        )
        self.assertTrue(
            all(
                diagnostic.source_path
                == f"tilesets/{diagnostic.resource}/{diagnostic.resource}.yy"
                and diagnostic.resource_type == "tileset"
                for diagnostic in rejected
            )
        )
        expected_fields = {
            name: field for name, _sprite_id, field in cases
        }
        self.assertTrue(
            all(
                diagnostic.manifest_entry
                == expected_fields[cast(str, diagnostic.resource)]
                for diagnostic in rejected
            )
        )

    def test_rejects_referenced_sprite_metadata_symlink_escape(self) -> None:
        outside_sprite = os.path.join(self.outside_dir, "outside_sprite.yy")
        self._write_json(
            outside_sprite,
            {
                "frames": [{"name": self.FRAME_GUID}],
                "layers": [{"name": self.LAYER_GUID, "visible": True}],
                "resourceType": "GMSprite",
            },
        )
        sprite_name = "s_linked_metadata"
        linked_sprite = os.path.join(
            self.gm_dir,
            "sprites",
            sprite_name,
            sprite_name + ".yy",
        )
        os.makedirs(os.path.dirname(linked_sprite), exist_ok=True)
        try:
            os.symlink(outside_sprite, linked_sprite)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        tileset_name = "ts_linked_sprite_metadata"
        self._write_tileset(
            os.path.join(
                self.gm_dir,
                "tilesets",
                tileset_name,
                tileset_name + ".yy",
            ),
            tileset_name,
            {
                "name": sprite_name,
                "path": f"sprites/{sprite_name}/{sprite_name}.yy",
            },
        )

        converter = self._make_converter()
        with patch("builtins.open", wraps=open) as tracked_open:
            result = converter._process_tileset(tileset_name)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result["success"])
        self.assertNotIn(
            os.path.realpath(outside_sprite),
            {
                os.path.realpath(call.args[0])
                for call in tracked_open.call_args_list
                if call.args and isinstance(call.args[0], str)
            },
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, tileset_name)
        self.assertEqual(
            rejected[0].source_path,
            f"tilesets/{tileset_name}/{tileset_name}.yy",
        )
        self.assertEqual(rejected[0].manifest_entry, "spriteId.path")

    def test_rejects_normalized_cross_family_and_non_yy_sprite_paths(
        self,
    ) -> None:
        rejected_targets = {
            "ts_cross_family": os.path.join(
                self.gm_dir,
                "tilesets",
                "decoy",
                "decoy.yy",
            ),
            "ts_non_yy": os.path.join(
                self.gm_dir,
                "sprites",
                "decoy",
                "decoy.json",
            ),
        }
        for target in rejected_targets.values():
            self._write_json(
                target,
                {
                    "frames": [{"name": self.FRAME_GUID}],
                    "layers": [{"name": self.LAYER_GUID, "visible": True}],
                },
            )

        sprite_paths = {
            "ts_cross_family": (
                "sprites/placeholder/../../tilesets/decoy/decoy.yy"
            ),
            "ts_non_yy": "sprites/decoy/decoy.json",
        }
        for tileset_name, sprite_path in sprite_paths.items():
            self._write_tileset(
                os.path.join(
                    self.gm_dir,
                    "tilesets",
                    tileset_name,
                    tileset_name + ".yy",
                ),
                tileset_name,
                {"name": "s_decoy", "path": sprite_path},
            )

        safe_tileset = "ts_safe_reference"
        safe_sprite = "s_safe_reference"
        self._write_tileset(
            os.path.join(
                self.gm_dir,
                "tilesets",
                safe_tileset,
                safe_tileset + ".yy",
            ),
            safe_tileset,
            {
                "name": safe_sprite,
                "path": f"sprites/{safe_sprite}/{safe_sprite}.yy",
            },
        )
        self._write_sprite(
            os.path.join(
                self.gm_dir,
                "sprites",
                safe_sprite,
                safe_sprite + ".yy",
            ),
            color="green",
        )

        converter = self._make_converter()
        with patch("builtins.open", wraps=open) as tracked_open:
            rejected_results = {
                tileset_name: converter._process_tileset(tileset_name)
                for tileset_name in sprite_paths
            }
            safe_result = converter._process_tileset(safe_tileset)

        self.assertTrue(
            all(
                result is not None and not result["success"]
                for result in rejected_results.values()
            )
        )
        self.assertIsNotNone(safe_result)
        assert safe_result is not None
        self.assertTrue(safe_result["success"])

        opened_paths = {
            os.path.realpath(call.args[0])
            for call in tracked_open.call_args_list
            if call.args and isinstance(call.args[0], str)
        }
        self.assertTrue(
            opened_paths.isdisjoint(
                os.path.realpath(path) for path in rejected_targets.values()
            )
        )
        rejected = [
            diagnostic
            for diagnostic in self._source_path_rejections()
            if diagnostic.resource in sprite_paths
        ]
        self.assertEqual(len(rejected), len(sprite_paths), rejected)
        self.assertTrue(
            all(
                diagnostic.source_path
                == f"tilesets/{diagnostic.resource}/{diagnostic.resource}.yy"
                and diagnostic.manifest_entry == "spriteId.path"
                for diagnostic in rejected
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "tilesets",
                    safe_tileset,
                    safe_tileset + ".png",
                )
            )
        )

    def test_sprite_frame_and_layer_rejections_are_linked_to_sprite_metadata(
        self,
    ) -> None:
        cases: list[tuple[str, str, str, object]] = [
            ("ts_frame_slash", "s_frame_slash", "frames[0].name", "nested/frame"),
            ("ts_frame_dot", "s_frame_dot", "frames[0].name", ".."),
            (
                "ts_frame_drive",
                "s_frame_drive",
                "frames[0].name",
                r"C:\Outside\frame",
            ),
            ("ts_frame_nul", "s_frame_nul", "frames[0].name", "bad\0frame"),
            ("ts_frame_non_string", "s_frame_non_string", "frames[0].name", 7),
            (
                "ts_layer_backslash",
                "s_layer_backslash",
                "layers[0].name",
                r"nested\layer",
            ),
            ("ts_layer_dot", "s_layer_dot", "layers[0].name", "."),
            (
                "ts_layer_unc",
                "s_layer_unc",
                "layers[0].name",
                r"\\server\share\layer",
            ),
            (
                "ts_layer_non_string",
                "s_layer_non_string",
                "layers[0].name",
                ["layer"],
            ),
        ]
        for tileset_name, sprite_name, field, invalid_value in cases:
            frames: list[dict[str, object]] = [{"name": self.FRAME_GUID}]
            layers: list[dict[str, object]] = [
                {"name": self.LAYER_GUID, "visible": True}
            ]
            if field == "frames[0].name":
                frames[0]["name"] = invalid_value
            else:
                layers[0]["name"] = invalid_value
            self._write_tileset(
                os.path.join(
                    self.gm_dir,
                    "tilesets",
                    tileset_name,
                    tileset_name + ".yy",
                ),
                tileset_name,
                {
                    "name": sprite_name,
                    "path": f"sprites/{sprite_name}/{sprite_name}.yy",
                },
            )
            self._write_json(
                os.path.join(
                    self.gm_dir,
                    "sprites",
                    sprite_name,
                    sprite_name + ".yy",
                ),
                {
                    "frames": frames,
                    "layers": layers,
                    "resourceType": "GMSprite",
                },
            )

        safe_tileset = "ts_safe_sidecar"
        safe_sprite = "s_safe_sidecar"
        self._write_tileset(
            os.path.join(
                self.gm_dir,
                "tilesets",
                safe_tileset,
                safe_tileset + ".yy",
            ),
            safe_tileset,
            {
                "name": safe_sprite,
                "path": f"sprites/{safe_sprite}/{safe_sprite}.yy",
            },
        )
        self._write_sprite(
            os.path.join(
                self.gm_dir,
                "sprites",
                safe_sprite,
                safe_sprite + ".yy",
            ),
            color="green",
        )

        self._make_converter().convert_all()

        expected = {
            tileset_name: (f"sprites/{sprite_name}/{sprite_name}.yy", field)
            for tileset_name, sprite_name, field, _invalid_value in cases
        }
        rejected = [
            diagnostic
            for diagnostic in self._source_path_rejections()
            if diagnostic.resource in expected
        ]
        self.assertEqual(len(rejected), len(cases), rejected)
        self.assertEqual(
            {
                diagnostic.resource: (
                    diagnostic.source_path,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            },
            expected,
        )
        for tileset_name in expected:
            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        self.godot_dir,
                        "tilesets",
                        tileset_name,
                        tileset_name + ".png",
                    )
                )
            )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "tilesets",
                    safe_tileset,
                    safe_tileset + ".png",
                )
            )
        )

    def test_disk_fallback_rejects_tileset_file_and_directory_symlink_escapes(
        self,
    ) -> None:
        tilesets_root = os.path.join(self.gm_dir, "tilesets")
        linked_file_dir = os.path.join(tilesets_root, "ts_file_link")
        os.makedirs(linked_file_dir)
        outside_file = os.path.join(self.outside_dir, "ts_file_link.yy")
        self._write_tileset(
            outside_file,
            "ts_file_link",
            {"name": "s_outside"},
        )
        outside_directory = os.path.join(self.outside_dir, "ts_directory_link")
        self._write_tileset(
            os.path.join(outside_directory, "ts_directory_link.yy"),
            "ts_directory_link",
            {"name": "s_outside"},
        )
        try:
            os.symlink(
                outside_file,
                os.path.join(linked_file_dir, "ts_file_link.yy"),
            )
            os.symlink(
                outside_directory,
                os.path.join(tilesets_root, "ts_directory_link"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        self._make_converter().convert_all()

        for name in ("ts_file_link", "ts_directory_link"):
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        self.godot_dir,
                        "tilesets",
                        name,
                        name + ".tres",
                    )
                )
            )
        rejected = self._source_path_rejections()
        self.assertEqual(
            {(item.resource, item.manifest_entry) for item in rejected},
            {
                ("ts_file_link", "tileset .yy"),
                ("ts_directory_link", "tileset directory"),
            },
        )

    def test_rejects_sprite_image_symlink_escapes_with_sprite_provenance(
        self,
    ) -> None:
        outside_file_image = os.path.join(self.outside_dir, "outside_file.png")
        Image.new("RGBA", (16, 16), "magenta").save(
            outside_file_image,
            "PNG",
        )

        for name, sprite_name in (
            ("ts_layer_file", "s_layer_file"),
            ("ts_layer_directory", "s_layer_directory"),
            ("ts_frame_directory", "s_frame_directory"),
            ("ts_layer_fallback", "s_layer_fallback"),
            ("ts_layer_safe", "s_layer_safe"),
        ):
            self._write_tileset(
                os.path.join(self.gm_dir, "tilesets", name, name + ".yy"),
                name,
                {
                    "name": sprite_name,
                    "path": f"sprites/{sprite_name}/{sprite_name}.yy",
                },
            )
            self._write_sprite(
                os.path.join(
                    self.gm_dir,
                    "sprites",
                    sprite_name,
                    sprite_name + ".yy",
                ),
                color="green",
            )

        file_sprite_dir = os.path.join(
            self.gm_dir,
            "sprites",
            "s_layer_file",
        )
        file_image = os.path.join(
            file_sprite_dir,
            "layers",
            self.FRAME_GUID,
            self.LAYER_GUID + ".png",
        )
        os.remove(file_image)

        directory_sprite_dir = os.path.join(
            self.gm_dir,
            "sprites",
            "s_layer_directory",
        )
        shutil.rmtree(os.path.join(directory_sprite_dir, "layers"))
        frame_sprite_dir = os.path.join(
            self.gm_dir,
            "sprites",
            "s_frame_directory",
        )
        shutil.rmtree(
            os.path.join(frame_sprite_dir, "layers", self.FRAME_GUID)
        )
        fallback_sprite_dir = os.path.join(
            self.gm_dir,
            "sprites",
            "s_layer_fallback",
        )
        os.remove(
            os.path.join(
                fallback_sprite_dir,
                "layers",
                self.FRAME_GUID,
                self.LAYER_GUID + ".png",
            )
        )
        outside_layers = os.path.join(self.outside_dir, "outside_layers")
        outside_directory_image = os.path.join(
            outside_layers,
            self.FRAME_GUID,
            self.LAYER_GUID + ".png",
        )
        os.makedirs(os.path.dirname(outside_directory_image))
        Image.new("RGBA", (16, 16), "cyan").save(
            outside_directory_image,
            "PNG",
        )
        outside_frame = os.path.join(self.outside_dir, "outside_frame")
        os.makedirs(outside_frame)
        Image.new("RGBA", (16, 16), "yellow").save(
            os.path.join(outside_frame, self.LAYER_GUID + ".png"),
            "PNG",
        )
        try:
            os.symlink(outside_file_image, file_image)
            os.symlink(
                outside_layers,
                os.path.join(directory_sprite_dir, "layers"),
            )
            os.symlink(
                outside_frame,
                os.path.join(
                    frame_sprite_dir,
                    "layers",
                    self.FRAME_GUID,
                ),
            )
            os.symlink(
                outside_file_image,
                os.path.join(fallback_sprite_dir, "layers", "fallback.png"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        real_copy2 = shutil.copy2
        with (
            patch("builtins.open", wraps=open) as tracked_open,
            patch(
                "src.conversion.tilesets.shutil.copy2",
                wraps=real_copy2,
            ) as tracked_copy,
        ):
            self._make_converter().convert_all()

        outside_root = os.path.realpath(self.outside_dir)
        opened_paths = {
            os.path.realpath(call.args[0])
            for call in tracked_open.call_args_list
            if call.args and isinstance(call.args[0], str)
        }
        copied_sources = {
            os.path.realpath(call.args[0])
            for call in tracked_copy.call_args_list
            if call.args and isinstance(call.args[0], str)
        }
        self.assertFalse(
            any(
                path == outside_root or path.startswith(outside_root + os.sep)
                for path in opened_paths | copied_sources
            )
        )

        rejected = [
            diagnostic
            for diagnostic in self._source_path_rejections()
            if diagnostic.resource
            in {
                "ts_layer_file",
                "ts_layer_directory",
                "ts_frame_directory",
                "ts_layer_fallback",
            }
        ]
        self.assertEqual(len(rejected), 4, rejected)
        self.assertEqual(
            {
                diagnostic.resource: (
                    diagnostic.source_path,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            },
            {
                "ts_layer_file": (
                    "sprites/s_layer_file/s_layer_file.yy",
                    "layers[0].name",
                ),
                "ts_layer_directory": (
                    "sprites/s_layer_directory/s_layer_directory.yy",
                    "layers",
                ),
                "ts_frame_directory": (
                    "sprites/s_frame_directory/s_frame_directory.yy",
                    "frames[0].name",
                ),
                "ts_layer_fallback": (
                    "sprites/s_layer_fallback/s_layer_fallback.yy",
                    "layers",
                ),
            },
        )
        for name in (
            "ts_layer_file",
            "ts_layer_directory",
            "ts_frame_directory",
            "ts_layer_fallback",
        ):
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        self.godot_dir,
                        "tilesets",
                        name,
                        name + ".png",
                    )
                )
            )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "tilesets",
                    "ts_layer_safe",
                    "ts_layer_safe.png",
                )
            )
        )


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

        tres_path = os.path.join(self.godot_dir, "tilesets", "world", "ts_terrain", "ts_terrain.tres")
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

        tres_path = os.path.join(self.godot_dir, "tilesets", "world", "ts_terrain", "ts_terrain.tres")
        with open(tres_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('res://tilesets/world/ts_terrain/ts_terrain.png', content)


class TestTileSetGeneratedPathCollisions(unittest.TestCase):
    def test_emitted_tilesets_match_collision_safe_registry_paths(self) -> None:
        gm_dir = tempfile.mkdtemp()
        godot_dir = tempfile.mkdtemp()
        try:
            _make_sprite_for_tileset(gm_dir, "s_tiles", width=32, height=16)
            resources: list[dict[str, object]] = [
                {
                    "id": {
                        "name": "s_tiles",
                        "path": "sprites/s_tiles/s_tiles.yy",
                    }
                }
            ]
            for name in ("FooBar", "foo_bar"):
                tileset_dir = os.path.join(gm_dir, "tilesets", name)
                os.makedirs(tileset_dir)
                with open(
                    os.path.join(tileset_dir, name + ".yy"),
                    "w",
                    encoding="utf-8",
                ) as tileset_file:
                    tileset_file.write(
                        _make_tileset_yy_content(name, "s_tiles", tile_count=2)
                    )
                resources.append(
                    {"id": {"name": name, "path": f"tilesets/{name}/{name}.yy"}}
                )
            with open(
                os.path.join(gm_dir, "CollisionTilesets.yyp"),
                "w",
                encoding="utf-8",
            ) as project_file:
                json.dump({"resources": resources, "RoomOrderNodes": []}, project_file)

            TileSetConverter(
                gm_dir,
                godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=2,
            ).convert_all()
            entries = AssetRegistryConverter(
                gm_dir,
                godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
            ).build_entries()
            paths = {
                entry.name: entry.godot_path
                for entry in entries
                if entry.kind == "tilesets"
            }

            self.assertEqual(len(paths), 2)
            self.assertEqual(len(set(paths.values())), 2)
            for resource_path in paths.values():
                tres_path = os.path.join(
                    godot_dir,
                    *resource_path.removeprefix("res://").split("/"),
                )
                texture_path = os.path.splitext(tres_path)[0] + ".png"
                self.assertTrue(os.path.isfile(tres_path), resource_path)
                self.assertTrue(os.path.isfile(texture_path), texture_path)
                with open(tres_path, "r", encoding="utf-8") as tres_file:
                    expected_texture = os.path.splitext(resource_path)[0] + ".png"
                    self.assertIn(f'path="{expected_texture}"', tres_file.read())
        finally:
            shutil.rmtree(gm_dir)
            shutil.rmtree(godot_dir)


class TestTypedTilesetMetadataIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.relative_source = "tilesets/declared/renamed.yy"
        self.yy_path = os.path.join(self.gm_dir, *self.relative_source.split("/"))
        os.makedirs(os.path.dirname(self.yy_path))
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()
        self.converter = TileSetConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_data(self, value: JsonValue) -> None:
        with open(self.yy_path, "w", encoding="utf-8") as source_file:
            json.dump(value, source_file)

    def _parse(self) -> TilesetData | None:
        return self.converter._parse_tileset_yy("ts_typed", self.relative_source)

    def test_real_decoder_retains_literal_rewrite_and_public_field_order(self) -> None:
        source = (
            '{"tileWidth":"32", "tileHeight":17.9, "tilehsep":true,'
            '"tileAnimationFrames":[{"text":"a,}",},], "tileAnimationSpeed":"9",}'
        )
        with open(self.yy_path, "w", encoding="utf-8") as source_file:
            source_file.write(source)
        with patch("src.conversion.tilesets.decode_gamemaker_json", wraps=decode_gamemaker_json) as decoder:
            result = self._parse()
        assert result is not None
        self.assertEqual(
            list(result),
            [
                "source_path", "sprite_name", "sprite_path", "sprite_reference_field",
                "tileWidth", "tileHeight", "tilehsep", "tilevsep", "tilexoff", "tileyoff",
                "tile_count", "out_columns", "tileAnimationFrames", "tileAnimationSpeed",
                "brushes", "autoTileSets", "tileSetCollisions", "out_tilehborder", "out_tilevborder",
            ],
        )
        self.assertEqual(TilesetData.__module__, "src.conversion.tilesets")
        self.assertEqual(result["source_path"], self.relative_source)
        self.assertEqual((result["tileWidth"], result["tileHeight"], result["tilehsep"]), (32, 17, 1))
        self.assertEqual(result["tileAnimationSpeed"], 15.0)
        self.assertEqual(result["tileAnimationFrames"], [{"text": "a}"}])
        decoder.assert_called_once_with(source, source_path=self.yy_path)

    def test_legal_nonobject_files_preserve_builtin_get_attribute_errors(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, True, 23, -0.0, "text", [], [1, {"x": 2}])
        for value in values:
            with self.subTest(value=value):
                self._write_data(value)
                with self.assertRaises(AttributeError) as expected:
                    getattr(value, "get")
                with self.assertRaises(AttributeError) as actual:
                    self._parse()
                self.assertEqual(str(actual.exception), str(expected.exception))
                self.assertEqual(actual.exception.name, "get")
                self.assertEqual(actual.exception.obj, value)
                self.assertIs(type(actual.exception.obj), type(value))
        self.assertEqual(self.diagnostics.diagnostics(), ())

    def test_nonobject_error_retains_actual_decoded_object_identity(self) -> None:
        value: JsonValue = [None, {"child": [3]}]
        self._write_data({})
        with patch("src.conversion.gamemaker_json.json.loads", return_value=value):
            with self.assertRaises(AttributeError) as caught:
                self._parse()
        self.assertIs(caught.exception.obj, value)
        self.assertEqual(caught.exception.name, "get")

    def test_reference_callback_runs_before_numeric_capture(self) -> None:
        root: JsonObject = {"spriteId": ["bad reference"], "tileWidth": "invalid", "tileHeight": None}
        self._write_data({})
        order: list[str] = []

        def reject_callback(message: str) -> None:
            self.logs.append(message)
            order.append("callback")
            root["tileWidth"] = "48"
            root["tileHeight"] = "24"

        def capture(data: JsonObject, *, source_context: str) -> GameMakerTilesetMetadata:
            order.append("metadata")
            self.assertIs(data, root)
            self.assertEqual(source_context, self.yy_path)
            return parse_gamemaker_tileset_metadata(data, source_context=source_context)

        self.converter.log_callback = reject_callback
        with (
            patch("src.conversion.gamemaker_json.json.loads", return_value=root),
            patch("src.conversion.tilesets.parse_gamemaker_tileset_metadata", side_effect=capture),
        ):
            result = self._parse()
        assert result is not None
        self.assertEqual((result["tileWidth"], result["tileHeight"]), (48, 24))
        self.assertEqual(order, ["callback", "metadata"])
        rejection = self.diagnostics.diagnostics()[0]
        self.assertEqual((rejection.source_path, rejection.manifest_entry), (self.relative_source, "spriteId"))

    def test_present_invalid_path_never_uses_valid_legacy_name(self) -> None:
        values: tuple[JsonValue, ...] = (None, "", 7, [], {})
        for value in values:
            with self.subTest(value=value):
                self._write_data({"spriteId": {"path": value, "name": "s_safe"}})
                result = self._parse()
                assert result is not None
                self.assertEqual((result["sprite_name"], result["sprite_path"]), ("", ""))
                self.assertEqual(result["sprite_reference_field"], "spriteId")
        self.assertEqual(
            [item.manifest_entry for item in self.diagnostics.diagnostics()],
            ["spriteId.path"] * len(values),
        )

    def test_declared_sprite_path_and_legacy_name_keep_distinct_authority(self) -> None:
        self._write_data({"spriteId": {"name": "ignored", "path": "sprites/custom/actual.yy"}})
        result = self._parse()
        assert result is not None
        self.assertEqual(
            (result["sprite_name"], result["sprite_path"], result["sprite_reference_field"]),
            ("actual", "sprites/custom/actual.yy", "spriteId.path"),
        )
        self._write_data({"spriteId": {"name": "s_legacy"}})
        result = self._parse()
        assert result is not None
        self.assertEqual(
            (result["sprite_name"], result["sprite_path"], result["sprite_reference_field"]),
            ("s_legacy", "sprites/s_legacy/s_legacy.yy", "spriteId.name"),
        )

    def test_primary_source_is_opened_once_before_projection(self) -> None:
        self._write_data({"tileWidth": 42})
        reads: list[str] = []
        real_open = open

        def track_open(path: str, mode: str = "r", *, encoding: str | None = None):
            reads.append(path)
            return real_open(path, mode, encoding=encoding)

        def capture(data: JsonObject, *, source_context: str) -> GameMakerTilesetMetadata:
            self.assertEqual(reads, [self.yy_path])
            return parse_gamemaker_tileset_metadata(data, source_context=source_context)

        with (
            patch("src.conversion.tilesets.open", side_effect=track_open, create=True),
            patch("src.conversion.tilesets.parse_gamemaker_tileset_metadata", side_effect=capture),
        ):
            result = self._parse()
        assert result is not None
        self.assertEqual(result["tileWidth"], 42)
        self.assertEqual(reads, [self.yy_path])

    def test_live_reread_uses_current_declared_source(self) -> None:
        decoy = os.path.join(self.gm_dir, "tilesets", "ts_typed", "ts_typed.yy")
        os.makedirs(os.path.dirname(decoy))
        with open(decoy, "w", encoding="utf-8") as source_file:
            source_file.write('{"tileWidth":99}')
        self._write_data({"tileWidth": 16})
        first = self._parse()
        self._write_data({"tileWidth": 64})
        second = self._parse()
        assert first is not None and second is not None
        self.assertEqual((first["tileWidth"], second["tileWidth"]), (16, 64))
        self.assertEqual(first["source_path"], self.relative_source)
        self.assertEqual(second["source_path"], self.relative_source)

    def test_decoder_caught_errors_return_none_without_projection(self) -> None:
        self._write_data({})
        errors = (
            OSError("read"), json.JSONDecodeError("bad", "{", 0), KeyError("missing"),
            TypeError("type"), ValueError("value"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with (
                    patch("src.conversion.tilesets.decode_gamemaker_json", side_effect=error),
                    patch("src.conversion.tilesets.parse_gamemaker_tileset_metadata") as metadata,
                ):
                    self.assertIsNone(self._parse())
                    metadata.assert_not_called()
        self.assertEqual(self.diagnostics.diagnostics(), ())

    def test_decoder_uncaught_errors_preserve_exact_instance(self) -> None:
        self._write_data({})
        errors = (
            AttributeError("attribute"), OverflowError("overflow"), RecursionError("depth"),
            RuntimeError("runtime"), KeyboardInterrupt("cancel"), SystemExit("exit"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.tilesets.decode_gamemaker_json", side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        self._parse()
                self.assertIs(caught.exception, error)

    def test_resolver_remains_outside_parse_catch(self) -> None:
        error = ValueError("owner containment failure")
        with (
            patch.object(self.converter, "_resolve_tileset_yy_source", side_effect=error),
            patch("src.conversion.tilesets.decode_gamemaker_json") as decoder,
        ):
            with self.assertRaises(ValueError) as caught:
                self._parse()
            decoder.assert_not_called()
        self.assertIs(caught.exception, error)

    def test_reference_and_projection_keep_original_catch_boundaries(self) -> None:
        self._write_data({})
        for target in (
            "src.conversion.tilesets.TileSetConverter._resolve_sprite_reference",
            "src.conversion.tilesets.project_tileset_conversion_fields",
        ):
            with self.subTest(target=target):
                with patch(target, side_effect=TypeError("caught")):
                    self.assertIsNone(self._parse())
                error = RuntimeError("propagate unchanged")
                with patch(target, side_effect=error):
                    with self.assertRaises(RuntimeError) as caught:
                        self._parse()
                self.assertIs(caught.exception, error)

    def test_real_invalid_utf8_and_malformed_json_return_none(self) -> None:
        for contents in (b"\xff", b'{"tileWidth":', b'{"tileWidth":null}'):
            with self.subTest(contents=contents):
                with open(self.yy_path, "wb") as source_file:
                    source_file.write(contents)
                self.assertIsNone(self._parse())
        self.assertEqual(self.diagnostics.diagnostics(), ())

    def test_rejected_source_is_not_decoded(self) -> None:
        self._write_data({})
        for source in ("objects/o_wrong/o_wrong.yy", "../outside.yy", "bad\0path.yy"):
            with self.subTest(source=source):
                with patch("src.conversion.tilesets.decode_gamemaker_json") as decoder:
                    self.assertIsNone(self.converter._parse_tileset_yy("ts_typed", source))
                    decoder.assert_not_called()
        self.assertEqual(os.listdir(self.godot_dir), [])

    def test_filtered_lists_keep_shared_children_and_fresh_mutable_lists(self) -> None:
        child: JsonObject = {"unknown": {"points": [1, 2]}}
        source_list: list[JsonValue] = [None, child, 3, child]
        root: JsonObject = {
            "tileAnimationFrames": source_list, "brushes": source_list,
            "autoTileSets": source_list, "tileSetCollisions": source_list,
        }
        self._write_data({})
        with patch("src.conversion.gamemaker_json.json.loads", return_value=root):
            result = self._parse()
        assert result is not None
        lists = [result["tileAnimationFrames"], result["brushes"], result["autoTileSets"], result["tileSetCollisions"]]
        self.assertEqual(len({id(value) for value in lists}), 4)
        for value in lists:
            self.assertIsNot(value, source_list)
            self.assertEqual(len(value), 2)
            self.assertIs(value[0], child)
            self.assertIs(value[1], child)
        child["later"] = True
        self.assertTrue(result["brushes"][0]["later"])

    def test_deep_unknown_data_and_shared_children_survive_validated_boundary(self) -> None:
        child: JsonObject = {"leaf": 1}
        deep: JsonValue = child
        for _ in range(1500):
            deep = [deep]
        root: JsonObject = {"unknown": deep, "tileAnimationFrames": [child, child]}
        self._write_data({})
        with patch("src.conversion.gamemaker_json.json.loads", return_value=root):
            result = self._parse()
        assert result is not None
        self.assertIs(result["tileAnimationFrames"][0], child)
        self.assertIs(result["tileAnimationFrames"][1], child)

    def test_invalid_injected_graph_is_caught_before_reference_callbacks(self) -> None:
        cycle: JsonObject = {"spriteId": ["would reject"]}
        cycle["unknown"] = cycle
        values: tuple[object, ...] = (cycle, {"unknown": object()}, {1: "invalid key"})
        self._write_data({})
        for value in values:
            with self.subTest(kind=type(value).__name__):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=value):
                    self.assertIsNone(self._parse())
        self.assertEqual(self.logs, [])
        self.assertEqual(self.diagnostics.diagnostics(), ())

    def test_ordered_coercion_preserves_first_caught_or_uncaught_failure(self) -> None:
        cases: tuple[tuple[JsonObject, type[Exception] | None], ...] = (
            ({"tileWidth": None, "tileHeight": float("inf")}, None),
            ({"tileWidth": float("nan"), "tileHeight": float("inf")}, None),
            ({"tileWidth": float("inf"), "tileHeight": None}, OverflowError),
            ({"tileWidth": 16, "tileHeight": float("inf"), "tilehsep": None}, OverflowError),
            ({"tilehsep": None, "tileAnimationSpeed": 10**1000}, None),
            ({"tileAnimationSpeed": 10**1000, "out_tilehborder": None}, OverflowError),
        )
        for value, expected in cases:
            with self.subTest(keys=list(value)):
                self._write_data(value)
                if expected is None:
                    self.assertIsNone(self._parse())
                else:
                    with self.assertRaises(expected):
                        self._parse()

    def test_native_speed_and_integer_provenance_remain_distinct(self) -> None:
        cases: tuple[tuple[JsonValue, float], ...] = ((True, 1.0), (False, 0.0), (12.5, 12.5), ("12.5", 15.0))
        for speed, expected in cases:
            with self.subTest(speed=speed):
                self._write_data({"tileWidth": 10**1000, "tileHeight": False, "tileAnimationSpeed": speed})
                result = self._parse()
                assert result is not None
                self.assertEqual(result["tileWidth"], 10**1000)
                self.assertIs(type(result["tileWidth"]), int)
                self.assertEqual(result["tileHeight"], 0)
                self.assertEqual(result["tileAnimationSpeed"], expected)
        self._write_data({"tileAnimationSpeed": -0.0})
        result = self._parse()
        assert result is not None
        self.assertEqual(math.copysign(1.0, result["tileAnimationSpeed"]), -1.0)

    def test_nonfinite_speed_copies_real_png_before_render_failure_and_preserves_tres(self) -> None:
        _make_sprite_for_tileset(self.gm_dir, "s_typed", width=16, height=16)
        source_image = os.path.join(
            self.gm_dir, "sprites", "s_typed", "layers",
            "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000001.png",
        )
        output_dir = os.path.join(self.godot_dir, "tilesets", "ts_typed")
        os.makedirs(output_dir)
        tres_path = os.path.join(output_dir, "ts_typed.tres")
        png_path = os.path.join(output_dir, "ts_typed.png")
        sentinel = b"previous tres remains"
        for speed, expected in ((float("nan"), ValueError), (float("inf"), OverflowError), (-float("inf"), OverflowError)):
            with self.subTest(speed=speed):
                self._write_data({"spriteId": {"name": "s_typed"}, "tileAnimationSpeed": speed})
                with open(tres_path, "wb") as output_file:
                    output_file.write(sentinel)
                with open(png_path, "wb") as output_file:
                    output_file.write(b"old png")
                with (
                    patch("src.conversion.tilesets.shutil.copy2", wraps=shutil.copy2) as copied,
                    patch("builtins.open", wraps=open) as opened,
                ):
                    with self.assertRaises(expected):
                        self.converter._process_tileset("ts_typed", tileset_source_path=self.relative_source)
                copied.assert_called_once_with(source_image, png_path)
                self.assertFalse(any(call.args and call.args[0] == tres_path for call in opened.call_args_list))
                with open(tres_path, "rb") as output_file:
                    self.assertEqual(output_file.read(), sentinel)
                with open(png_path, "rb") as output_file, open(source_image, "rb") as source_file:
                    self.assertEqual(output_file.read(), source_file.read())


class TestTypedSpriteAtlasAcquisition(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()
        self.converter = TileSetConverter(self.gm_dir, self.godot_dir, log_callback=self.logs.append,
                                          conversion_running=lambda: True, diagnostics=self.diagnostics)
        self.sprite_path = os.path.join(self.gm_dir, "sprites", "atlas", "atlas.yy")
        os.makedirs(os.path.dirname(self.sprite_path))
        self.image_path = os.path.join(os.path.dirname(self.sprite_path), "layers", "frame", "chosen.png")
        os.makedirs(os.path.dirname(self.image_path))
        Image.new("RGBA", (16, 16), "red").save(self.image_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_atlas(self, source: str) -> None:
        with open(self.sprite_path, "w", encoding="utf-8") as stream:
            stream.write(source)

    def _find_atlas(self):
        return self.converter._find_sprite_image("atlas", "sprites/atlas/atlas.yy", tileset_name="typed")

    def test_real_shared_decode_feeds_safe_atlas_and_copied_tileset_output(self) -> None:
        source = '{"frames":[{"name":"frame",}],"layers":[null,{"visible":false},{"name":"chosen"}],"unknown":"a,}",}'
        self._write_atlas(source)
        with patch("src.conversion.tilesets.decode_gamemaker_json", wraps=decode_gamemaker_json) as decoder:
            result = self._find_atlas()
        assert result is not None
        resolved, field = result
        self.assertEqual(resolved.filesystem_path, self.image_path)
        self.assertEqual(field, "layers[2].name")
        decoder.assert_called_once_with(source, source_path=self.sprite_path)
        tileset_path = os.path.join(self.gm_dir, "tilesets", "typed", "typed.yy")
        os.makedirs(os.path.dirname(tileset_path))
        with open(tileset_path, "w", encoding="utf-8") as stream:
            stream.write('{"spriteId":{"name":"atlas","path":"sprites/atlas/atlas.yy"},"tile_count":1}')
        processed = self.converter._process_tileset("typed")
        assert processed is not None
        self.assertTrue(processed["success"])
        copied = os.path.join(self.godot_dir, "tilesets", "typed", "typed.png")
        with open(copied, "rb") as output, open(self.image_path, "rb") as original:
            self.assertEqual(output.read(), original.read())
        with open(os.path.join(self.godot_dir, "tilesets", "typed", "typed.tres"), encoding="utf-8") as output:
            self.assertIn('type="TileSet"', output.read())

    def test_nonobject_roots_preserve_builtin_get_attribute_metadata(self) -> None:
        for source in ("null", "[]", "false", '"value"', "3"):
            with self.subTest(source=source):
                self._write_atlas(source)
                with self.assertRaises(AttributeError) as caught:
                    self._find_atlas()
                value = json.loads(source)
                self.assertEqual(str(caught.exception), f"'{type(value).__name__}' object has no attribute 'get'")
                self.assertEqual(caught.exception.name, "get")
                self.assertEqual(caught.exception.obj, value)

    def test_frame_owner_validation_precedes_layer_capture_and_observes_mutation(self) -> None:
        source = '{"frames":[{"name":"frame"}],"layers":[{"name":"old"}]}'
        self._write_atlas(source)
        document = decode_gamemaker_json(source, source_path=self.sprite_path)
        data = document.value
        assert isinstance(data, dict)
        original_validator = self.converter._valid_reference_component
        seen: list[str] = []

        def validate_and_mutate(component: str) -> bool:
            seen.append(component)
            if component == "frame":
                data["layers"] = [{"name": "chosen"}]
            return original_validator(component)

        with (
            patch("src.conversion.tilesets.decode_gamemaker_json", return_value=document),
            patch.object(self.converter, "_valid_reference_component", side_effect=validate_and_mutate),
        ):
            result = self._find_atlas()
        assert result is not None
        self.assertEqual(result[0].filesystem_path, self.image_path)
        self.assertEqual(seen, ["frame", "chosen"])

    def test_rejected_frame_does_not_read_layer_or_invoke_png_fallback(self) -> None:
        for frame in ('null', '{"name":"../escape"}'):
            with self.subTest(frame=frame):
                self._write_atlas('{"frames":[' + frame + '],"layers":[{"name":"chosen"}]}')
                with (
                    patch("src.conversion.tilesets.select_sprite_atlas_layer") as layers,
                    patch.object(self.converter, "_find_fallback_sprite_png") as fallback,
                ):
                    self.assertIsNone(self._find_atlas())
                layers.assert_not_called()
                fallback.assert_not_called()
        fields = [diagnostic.manifest_entry for diagnostic in self.diagnostics.diagnostics()]
        self.assertIn("frames[0]", fields)
        self.assertIn("frames[0].name", fields)

    def test_layer_filter_and_fallback_keep_original_index_and_diagnostic_field(self) -> None:
        self._write_atlas('{"frames":[{"name":"frame"}],"layers":[null,{"visible":false,"name":"chosen"},'
                          '{"visible":false,"name":"unused"}]}')
        result = self._find_atlas()
        assert result is not None
        self.assertEqual(result[1], "layers[1].name")
        self._write_atlas('{"frames":[{"name":"frame"}],"layers":[null,{"visible":false},'
                          '{"name":"../escape"}]}')
        self.assertIsNone(self._find_atlas())
        self.assertEqual(self.diagnostics.diagnostics()[-1].manifest_entry, "layers[2].name")

    def test_malformed_graph_uses_original_decode_failure_png_fallback(self) -> None:
        self._write_atlas('{}')
        with (
            patch("src.conversion.gamemaker_json.json.loads", return_value={"frames": [], "unknown": b"bad"}),
            patch("src.conversion.tilesets.capture_sprite_atlas_frame") as frame,
            patch.object(self.converter, "_find_fallback_sprite_png", return_value=None) as fallback,
        ):
            self.assertIsNone(self._find_atlas())
        frame.assert_not_called()
        fallback.assert_called_once()

    def test_decoder_controls_and_outside_resolver_keep_exception_identity(self) -> None:
        self._write_atlas('{}')
        for error in (RuntimeError("control"), RecursionError("depth"), AttributeError("uncaught"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.tilesets.decode_gamemaker_json", side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        self._find_atlas()
                self.assertIs(caught.exception, error)
        error = ValueError("initial owner resolver remains outside acquisition catch")
        with (
            patch.object(self.converter, "_resolve_project_source", side_effect=error),
            patch("src.conversion.tilesets.decode_gamemaker_json") as decoder,
        ):
            with self.assertRaises(ValueError) as caught:
                self._find_atlas()
        self.assertIs(caught.exception, error)
        decoder.assert_not_called()

    def test_utf8_bom_and_json_errors_keep_existing_fallback_seam(self) -> None:
        for contents in (b"\xff", b'\xef\xbb\xbf{}', b'{"frames":'):
            with self.subTest(contents=contents):
                with open(self.sprite_path, "wb") as stream:
                    stream.write(contents)
                with patch.object(self.converter, "_find_fallback_sprite_png", return_value=None) as fallback:
                    self.assertIsNone(self._find_atlas())
                fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
