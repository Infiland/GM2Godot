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
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.resource_index import GameMakerResourceIndex
from src.conversion.sprites import AnimationData, CollisionData, SpriteConverter, SpriteParseResult


class TestSpriteConverterBasic(unittest.TestCase):
    """Test SpriteConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Build a fake GM sprite directory structure:
        # sprites/test_sprite/layers/<layer_id>/
        # find_sprite_images uses root.split(os.sep)[-3] to get the sprite name,
        # so images must live exactly at sprites/<name>/layers/<id>/
        layer_dir = os.path.join(
            self.gm_dir, "sprites", "test_sprite", "layers",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        os.makedirs(layer_dir)

        # Create a tiny valid PNG using Pillow
        img = Image.new("RGBA", (2, 2), "red")
        img.save(os.path.join(layer_dir, "frame0.png"), "PNG")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_converts_sprite_to_godot_dir(self):
        converter = self._make_converter()
        converter.convert_all()

        godot_sprite_dir = os.path.join(self.godot_dir, "sprites", "test_sprite")
        self.assertTrue(os.path.isdir(godot_sprite_dir),
                        "Expected sprites/test_sprite directory in Godot project")

        png_files = [f for f in os.listdir(godot_sprite_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 1)

    def test_multiple_frames(self):
        """When a sprite has multiple frames each should get a numbered filename."""
        layer_dir = os.path.join(
            self.gm_dir, "sprites", "test_sprite", "layers",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        img = Image.new("RGBA", (2, 2), "blue")
        img.save(os.path.join(layer_dir, "frame1.png"), "PNG")

        converter = self._make_converter()
        converter.convert_all()

        godot_sprite_dir = os.path.join(self.godot_dir, "sprites", "test_sprite")
        png_files = [f for f in os.listdir(godot_sprite_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 2)

    def test_empty_layers_directory_does_not_create_phantom_sprite(self):
        """The structural layers directory must not be mistaken for a sprite."""
        os.makedirs(
            os.path.join(self.gm_dir, "sprites", "test_sprite", "layers", "empty_layer")
        )

        converter = self._make_converter()

        self.assertEqual(set(converter._find_all_sprite_images()), {"test_sprite"})


class TestSpriteConverterCompactLogging(unittest.TestCase):
    """Test SpriteConverter with compact logging enabled."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.log_messages: list[str] = []
        self.update_messages: list[str] = []

        # Build two sprites with 2 frames each
        for sprite_name in ["sprite_a", "sprite_b"]:
            for i in range(2):
                layer_dir = os.path.join(
                    self.gm_dir, "sprites", sprite_name, "layers",
                    f"aaaaaaaa-bbbb-cccc-dddd-{sprite_name}{i:08d}",
                )
                os.makedirs(layer_dir)
                img = Image.new("RGBA", (2, 2), "red")
                img.save(os.path.join(layer_dir, f"frame{i}.png"), "PNG")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_compact_logging_uses_progress_messages(self):
        converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.log_messages.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            update_log_callback=lambda msg: self.update_messages.append(msg),
            compact_logging=True,
        )
        converter.convert_all()

        # Should NOT have any verbose "Converted:" messages
        all_messages = self.log_messages + self.update_messages
        for msg in all_messages:
            self.assertNotIn("Converted:", msg)

        # Should have compact progress messages with [current/total] format
        progress_messages = [m for m in all_messages if "[" in m and "/" in m]
        self.assertTrue(len(progress_messages) > 0,
                        "Expected compact progress messages")

    def test_verbose_logging_when_compact_disabled(self):
        logs: list[str] = []
        converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            compact_logging=False,
        )
        converter.convert_all()

        # Should have verbose per-file messages
        converted_messages = [m for m in logs if "Converted:" in m]
        self.assertEqual(len(converted_messages), 4)  # 2 sprites x 2 frames


class TestSpriteConverterEmpty(unittest.TestCase):
    """When the sprites folder is empty the converter should log an error, not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create the sprites folder but leave it empty
        os.makedirs(os.path.join(self.gm_dir, "sprites"))

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_sprites_no_crash(self):
        converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise

        # Should log the "not found" message
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for empty sprites folder")


# Helper to create a minimal .yy file with trailing commas (like real GameMaker files)
def _make_yy_content(sprite_name: str, frame_guids: list[str], layer_guids: list[str],
                     layer_visible: list[bool] | None = None) -> str:
    """Build a .yy file string with the given frames and layers."""
    if layer_visible is None:
        layer_visible = [True] * len(layer_guids)
    frames_json = ",\n    ".join(
        '{{"$GMSpriteFrame":"v1","%Name":"{g}","name":"{g}","resourceType":"GMSpriteFrame","resourceVersion":"2.0",}}'.format(g=g)
        for g in frame_guids
    )
    layers_json = ",\n    ".join(
        '{{"$GMImageLayer":"","name":"{g}","displayName":"Layer {i}","opacity":100.0,"visible":{v},"resourceType":"GMImageLayer","resourceVersion":"2.0",}}'.format(
            g=g, i=i, v="true" if v else "false")
        for i, (g, v) in enumerate(zip(layer_guids, layer_visible))
    )
    return '''{{\n  "frames":[\n    {frames}\n  ],\n  "layers":[\n    {layers}\n  ],\n  "name":"{name}",\n  "resourceType":"GMSprite",\n  "resourceVersion":"2.0",\n}}'''.format(
        frames=frames_json, layers=layers_json, name=sprite_name)


class TestSpriteConverterFrameOrdering(unittest.TestCase):
    """Test that sprite frames are ordered according to the .yy file."""

    # GUIDs chosen so alphabetical order (aa, bb, cc) differs from .yy order (cc, aa, bb)
    FRAME_GUIDS = [
        "cccccccc-0000-0000-0000-000000000000",
        "aaaaaaaa-0000-0000-0000-000000000000",
        "bbbbbbbb-0000-0000-0000-000000000000",
    ]
    LAYER_GUID = "11111111-0000-0000-0000-000000000000"
    FRAME_COLORS = ["red", "green", "blue"]

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        sprite_dir = os.path.join(self.gm_dir, "sprites", "ordered_sprite")
        os.makedirs(sprite_dir)

        # Write .yy file
        yy_content = _make_yy_content("ordered_sprite", self.FRAME_GUIDS,
                                       [self.LAYER_GUID])
        with open(os.path.join(sprite_dir, "ordered_sprite.yy"), "w") as f:
            f.write(yy_content)

        # Create frame directories with distinct colors
        for guid, color in zip(self.FRAME_GUIDS, self.FRAME_COLORS):
            frame_dir = os.path.join(sprite_dir, "layers", guid)
            os.makedirs(frame_dir)
            img = Image.new("RGBA", (2, 2), color)
            img.save(os.path.join(frame_dir, self.LAYER_GUID + ".png"), "PNG")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_frame_order_matches_yy_file(self):
        converter = self._make_converter()
        converter.convert_all()

        godot_dir = os.path.join(self.godot_dir, "sprites", "ordered_sprite")
        # Frame 1 should be red (cc), frame 2 green (aa), frame 3 blue (bb)
        for idx, expected_color in enumerate(self.FRAME_COLORS, start=1):
            path = os.path.join(godot_dir, f"ordered_sprite_{idx}.png")
            self.assertTrue(os.path.exists(path), f"Missing {path}")
            with Image.open(path) as img:
                pixel = cast(tuple[int, int, int, int], img.getpixel((0, 0)))[:3]
            expected_rgb = cast(
                tuple[int, int, int, int],
                Image.new("RGBA", (1, 1), expected_color).getpixel((0, 0)),
            )[:3]
            self.assertEqual(pixel, expected_rgb,
                             f"Frame {idx} has wrong color: {pixel} != {expected_rgb}")

    def test_correct_frame_count(self):
        converter = self._make_converter()
        converter.convert_all()

        godot_dir = os.path.join(self.godot_dir, "sprites", "ordered_sprite")
        png_files = [f for f in os.listdir(godot_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 3)

    def test_fallback_when_yy_missing(self):
        # Remove the .yy file
        yy_path = os.path.join(self.gm_dir, "sprites", "ordered_sprite",
                               "ordered_sprite.yy")
        os.remove(yy_path)

        converter = self._make_converter()
        converter.convert_all()

        godot_dir = os.path.join(self.godot_dir, "sprites", "ordered_sprite")
        png_files = [f for f in os.listdir(godot_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 3)

    def test_fallback_when_yy_malformed(self):
        yy_path = os.path.join(self.gm_dir, "sprites", "ordered_sprite",
                               "ordered_sprite.yy")
        with open(yy_path, "w") as f:
            f.write("{this is not valid json at all")

        converter = self._make_converter()
        converter.convert_all()

        godot_dir = os.path.join(self.godot_dir, "sprites", "ordered_sprite")
        png_files = [f for f in os.listdir(godot_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 3)


class TestSpriteConverterMultiLayer(unittest.TestCase):
    """Test that multi-layer sprites composite visible layers."""

    FRAME_GUID = "aaaaaaaa-0000-0000-0000-000000000000"
    LAYER_VISIBLE_A = "22222222-0000-0000-0000-000000000000"
    LAYER_VISIBLE_B = "33333333-0000-0000-0000-000000000000"
    LAYER_HIDDEN = "11111111-0000-0000-0000-000000000000"

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        sprite_dir = os.path.join(self.gm_dir, "sprites", "multi_layer")
        os.makedirs(sprite_dir)

        # Hidden layer listed first, then two visible layers.
        yy_content = _make_yy_content(
            "multi_layer", [self.FRAME_GUID],
            [self.LAYER_HIDDEN, self.LAYER_VISIBLE_A, self.LAYER_VISIBLE_B],
            layer_visible=[False, True, True])
        with open(os.path.join(sprite_dir, "multi_layer.yy"), "w") as f:
            f.write(yy_content)

        frame_dir = os.path.join(sprite_dir, "layers", self.FRAME_GUID)
        os.makedirs(frame_dir)

        img = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        img.save(os.path.join(frame_dir, self.LAYER_HIDDEN + ".png"), "PNG")

        img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        img.putpixel((0, 0), (0, 255, 0, 255))
        img.save(os.path.join(frame_dir, self.LAYER_VISIBLE_A + ".png"), "PNG")

        img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        img.putpixel((1, 0), (0, 0, 255, 255))
        img.save(os.path.join(frame_dir, self.LAYER_VISIBLE_B + ".png"), "PNG")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_composites_visible_layers_and_ignores_hidden_layers(self):
        converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        godot_dir = os.path.join(self.godot_dir, "sprites", "multi_layer")
        png_files = [f for f in os.listdir(godot_dir) if f.endswith(".png")]
        self.assertEqual(len(png_files), 1, "Should output 1 file, not 1 per layer")

        with Image.open(os.path.join(godot_dir, png_files[0])) as img:
            converted = img.convert("RGBA")
            self.assertEqual(converted.getpixel((0, 0)), (0, 255, 0, 255))
            self.assertEqual(converted.getpixel((1, 0)), (0, 0, 255, 255))
            self.assertEqual(cast(tuple[int, int, int, int], converted.getpixel((1, 1)))[3], 0)


class TestParseSpriteYY(unittest.TestCase):
    """Test _parse_sprite_yy directly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yy(self, sprite_name: str, content: str) -> None:
        sprite_dir = os.path.join(self.gm_dir, "sprites", sprite_name)
        os.makedirs(sprite_dir, exist_ok=True)
        with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_frames_in_order(self):
        guids = ["cc-guid", "aa-guid", "bb-guid"]
        self._write_yy("test_spr", _make_yy_content("test_spr", guids, ["layer1"]))

        result = self.converter._parse_sprite_yy("test_spr")
        self.assertIsNotNone(result)
        result = cast(SpriteParseResult, result)
        frame_guids, layer_guids = result
        self.assertEqual(frame_guids, guids)
        self.assertEqual(layer_guids, ["layer1"])

    def test_trailing_commas_handled(self):
        # Write content with trailing commas (as real .yy files have)
        content = '{"frames":[{"name":"frame1",},],"layers":[{"name":"layer1","visible":true,},],"name":"tc",}'
        self._write_yy("tc", content)

        result = self.converter._parse_sprite_yy("tc")
        self.assertIsNotNone(result)
        result = cast(SpriteParseResult, result)
        self.assertEqual(result[0], ["frame1"])

    def test_returns_none_for_missing_file(self):
        result = self.converter._parse_sprite_yy("nonexistent_sprite")
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        self._write_yy("bad", "not json at all {{{")
        result = self.converter._parse_sprite_yy("bad")
        self.assertIsNone(result)

    def test_selects_visible_layers(self):
        guids = ["frame1"]
        layers = ["hidden_layer", "visible_layer"]
        self._write_yy("vis", _make_yy_content("vis", guids, layers,
                                                 layer_visible=[False, True]))
        result = self.converter._parse_sprite_yy("vis")
        self.assertIsNotNone(result)
        result = cast(SpriteParseResult, result)
        _, layer_guids = result
        self.assertEqual(layer_guids, ["visible_layer"])


def _make_yyp_content(sprite_names: list[str], extra_resources: list[str] | None = None) -> str:
    """Build a minimal .yyp file string with the given sprite names in the resources array."""
    resources: list[str] = []
    for name in sprite_names:
        resources.append(
            '{{"id":{{"name":"{name}","path":"sprites/{name}/{name}.yy",}},}}'.format(name=name)
        )
    if extra_resources:
        resources.extend(extra_resources)
    res_str = ",\n    ".join(resources) if resources else ""
    return '{{\n  "%Name": "TestProject",\n  "resources": [\n    {res}\n  ],\n}}'.format(res=res_str)


def _make_sprite_on_disk(gm_dir: str, sprite_name: str,
                         layer_guid: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") -> None:
    """Create a minimal sprite folder structure with a single-frame PNG."""
    layer_dir = os.path.join(gm_dir, "sprites", sprite_name, "layers", layer_guid)
    os.makedirs(layer_dir, exist_ok=True)
    img = Image.new("RGBA", (2, 2), "red")
    img.save(os.path.join(layer_dir, "frame0.png"), "PNG")


class TestGetValidSpriteNames(unittest.TestCase):
    """Test _get_valid_sprite_names() parsing of .yyp files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_returns_sprite_names_from_yyp(self):
        sound_resource = '{"id":{"name":"snd_explosion","path":"sounds/snd_explosion/snd_explosion.yy",},}'
        yyp = _make_yyp_content(["s_player", "s_enemy", "s_bullet"], extra_resources=[sound_resource])
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w") as f:
            f.write(yyp)

        converter = self._make_converter()
        result = converter._get_valid_sprite_names()
        result = cast(dict[str, str], result)
        self.assertEqual(set(result.keys()), {"s_player", "s_enemy", "s_bullet"})

    def test_handles_trailing_commas(self):
        # Trailing commas are present in the _make_yyp_content output
        yyp = _make_yyp_content(["s_test"])
        with open(os.path.join(self.gm_dir, "Game.yyp"), "w") as f:
            f.write(yyp)

        converter = self._make_converter()
        result = converter._get_valid_sprite_names()
        result = cast(dict[str, str], result)
        self.assertEqual(set(result.keys()), {"s_test"})

    def test_returns_none_when_no_yyp(self):
        converter = self._make_converter()
        result = converter._get_valid_sprite_names()
        self.assertIsNone(result)

    def test_returns_none_when_yyp_malformed(self):
        with open(os.path.join(self.gm_dir, "Bad.yyp"), "w") as f:
            f.write("not valid json {{{")

        converter = self._make_converter()
        result = converter._get_valid_sprite_names()
        self.assertIsNone(result)

    def test_returns_empty_dict_when_no_sprites(self):
        sound_resource = '{"id":{"name":"snd_boom","path":"sounds/snd_boom/snd_boom.yy",},}'
        yyp = _make_yyp_content([], extra_resources=[sound_resource])
        with open(os.path.join(self.gm_dir, "Game.yyp"), "w") as f:
            f.write(yyp)

        converter = self._make_converter()
        result = converter._get_valid_sprite_names()
        self.assertIsNotNone(result)
        self.assertEqual(result, {})


class TestSpriteConverterFiltering(unittest.TestCase):
    """Test that orphaned sprites are filtered out based on .yyp."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_skips_orphaned_sprites(self):
        _make_sprite_on_disk(self.gm_dir, "s_valid1")
        _make_sprite_on_disk(self.gm_dir, "s_valid2")
        _make_sprite_on_disk(self.gm_dir, "s_orphan")

        yyp = _make_yyp_content(["s_valid1", "s_valid2"])
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w") as f:
            f.write(yyp)

        converter = self._make_converter()
        converter.convert_all()

        godot_sprites = os.path.join(self.godot_dir, "sprites")
        converted: set[str] = set(os.listdir(godot_sprites)) if os.path.exists(godot_sprites) else set()
        self.assertIn("s_valid1", converted)
        self.assertIn("s_valid2", converted)
        self.assertNotIn("s_orphan", converted)

        skipped_logs = [l for l in self.logs if "s_orphan" in l]
        self.assertTrue(len(skipped_logs) > 0, "Expected a log message about skipped orphan sprite")

    def test_converts_all_when_all_in_yyp(self):
        _make_sprite_on_disk(self.gm_dir, "s_a")
        _make_sprite_on_disk(self.gm_dir, "s_b")

        yyp = _make_yyp_content(["s_a", "s_b"])
        with open(os.path.join(self.gm_dir, "Test.yyp"), "w") as f:
            f.write(yyp)

        converter = self._make_converter()
        converter.convert_all()

        godot_sprites = os.path.join(self.godot_dir, "sprites")
        converted = set(os.listdir(godot_sprites))
        self.assertIn("s_a", converted)
        self.assertIn("s_b", converted)

        skipped_logs = [l for l in self.logs if "orphaned" in l.lower() and ("s_a" in l or "s_b" in l)]
        self.assertEqual(len(skipped_logs), 0, "No real sprites should be skipped")

    def test_converts_all_when_yyp_missing(self):
        _make_sprite_on_disk(self.gm_dir, "s_x")
        _make_sprite_on_disk(self.gm_dir, "s_y")

        converter = self._make_converter()
        converter.convert_all()

        godot_sprites = os.path.join(self.godot_dir, "sprites")
        converted = set(os.listdir(godot_sprites))
        self.assertIn("s_x", converted)
        self.assertIn("s_y", converted)

    def test_converts_all_when_yyp_malformed(self):
        _make_sprite_on_disk(self.gm_dir, "s_m")
        _make_sprite_on_disk(self.gm_dir, "s_n")

        with open(os.path.join(self.gm_dir, "Bad.yyp"), "w") as f:
            f.write("totally broken {{{")

        converter = self._make_converter()
        converter.convert_all()

        godot_sprites = os.path.join(self.godot_dir, "sprites")
        converted = set(os.listdir(godot_sprites))
        self.assertIn("s_m", converted)
        self.assertIn("s_n", converted)


class TestSpriteGeneratedPathCollisions(unittest.TestCase):
    SPRITES = {
        "Foo-Bar": (255, 0, 0, 255),
        "Foo_Bar": (0, 128, 0, 255),
        "foo bar": (0, 0, 255, 255),
    }

    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

        for index, (sprite_name, color) in enumerate(self.SPRITES.items()):
            frame_guid = f"frame-{index}"
            layer_guid = f"layer-{index}"
            sprite_dir = os.path.join(self.gm_dir, "sprites", sprite_name)
            frame_dir = os.path.join(sprite_dir, "layers", frame_guid)
            os.makedirs(frame_dir)
            with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w", encoding="utf-8") as yy_file:
                yy_file.write(_make_yy_content(sprite_name, [frame_guid], [layer_guid]))
            Image.new("RGBA", (2, 2), color).save(
                os.path.join(frame_dir, layer_guid + ".png"),
                "PNG",
            )

        with open(os.path.join(self.gm_dir, "CollisionTest.yyp"), "w", encoding="utf-8") as yyp_file:
            yyp_file.write(_make_yyp_content(list(self.SPRITES)))

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_emitted_sprites_match_collision_safe_index_and_registry_paths(self) -> None:
        SpriteConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
        ).convert_all()
        resource_index = GameMakerResourceIndex(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        ).build()
        registry_entries = AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        ).build_entries()

        index_paths = {
            name: resource_index.resolve_godot_path("sprites", name)
            for name in self.SPRITES
        }
        registry_paths = {
            entry.name: entry.godot_path
            for entry in registry_entries
            if entry.kind == "sprites"
        }
        self.assertEqual(
            index_paths,
            {
                "Foo-Bar": "res://sprites/foo_bar_2/foo_bar_2.tscn",
                "Foo_Bar": "res://sprites/foo_bar_3/foo_bar_3.tscn",
                "foo bar": "res://sprites/foo_bar/foo_bar.tscn",
            },
        )
        self.assertEqual(index_paths, registry_paths)
        self.assertEqual(len(set(index_paths.values())), len(self.SPRITES))

        emitted_scene_paths: set[str] = set()
        for root, _, filenames in os.walk(os.path.join(self.godot_dir, "sprites")):
            for filename in filenames:
                if filename.endswith(".tscn"):
                    relative_path = os.path.relpath(os.path.join(root, filename), self.godot_dir)
                    emitted_scene_paths.add("res://" + relative_path.replace(os.sep, "/"))
        self.assertEqual(emitted_scene_paths, set(index_paths.values()))

        for sprite_name, scene_path in index_paths.items():
            assert scene_path is not None
            texture_path = os.path.splitext(scene_path)[0] + ".png"
            scene_file = os.path.join(self.godot_dir, scene_path.removeprefix("res://"))
            texture_file = os.path.join(self.godot_dir, texture_path.removeprefix("res://"))
            self.assertTrue(os.path.isfile(texture_file), texture_path)
            with open(scene_file, "r", encoding="utf-8") as scene:
                self.assertIn(f'path="{texture_path}"', scene.read())
            with Image.open(texture_file) as image:
                self.assertEqual(
                    image.convert("RGBA").getpixel((0, 0)),
                    self.SPRITES[sprite_name],
                )

    def test_missing_yyp_sprite_does_not_shift_emitted_collision_paths(self) -> None:
        missing_sprite = "Foo+Bar"
        with open(os.path.join(self.gm_dir, "CollisionTest.yyp"), "w", encoding="utf-8") as yyp_file:
            yyp_file.write(_make_yyp_content([missing_sprite, *self.SPRITES]))

        SpriteConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
        ).convert_all()
        resource_index = GameMakerResourceIndex(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        ).build()
        registry_entries = AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        ).build_entries()

        index_paths = {
            name: resource_index.resolve_godot_path("sprites", name)
            for name in self.SPRITES
        }
        registry_paths = {
            entry.name: entry.godot_path
            for entry in registry_entries
            if entry.kind == "sprites"
        }
        emitted_scene_paths = {
            "res://" + os.path.relpath(os.path.join(root, filename), self.godot_dir).replace(os.sep, "/")
            for root, _, filenames in os.walk(os.path.join(self.godot_dir, "sprites"))
            for filename in filenames
            if filename.endswith(".tscn")
        }

        self.assertIsNone(resource_index.resolve_godot_path("sprites", missing_sprite))
        self.assertNotIn(missing_sprite, registry_paths)
        self.assertEqual(index_paths, registry_paths)
        self.assertEqual(emitted_scene_paths, set(index_paths.values()))


def _make_yy_content_with_collision(sprite_name: str, frame_guids: list[str], layer_guids: list[str],
                                    collision_kind: int = 1, bbox_mode: int = 0,
                                    bbox_left: int = 0, bbox_right: int = 31,
                                    bbox_top: int = 0, bbox_bottom: int = 31,
                                    width: int = 32, height: int = 32,
                                    origin: int = 0, xorigin: int = 0, yorigin: int = 0,
                                    layer_visible: list[bool] | None = None) -> str:
    """Build a .yy file string with collision mask fields."""
    if layer_visible is None:
        layer_visible = [True] * len(layer_guids)
    frames_json = ",\n    ".join(
        '{{"$GMSpriteFrame":"v1","%Name":"{g}","name":"{g}","resourceType":"GMSpriteFrame","resourceVersion":"2.0",}}'.format(g=g)
        for g in frame_guids
    )
    layers_json = ",\n    ".join(
        '{{"$GMImageLayer":"","name":"{g}","displayName":"Layer {i}","opacity":100.0,"visible":{v},"resourceType":"GMImageLayer","resourceVersion":"2.0",}}'.format(
            g=g, i=i, v="true" if v else "false")
        for i, (g, v) in enumerate(zip(layer_guids, layer_visible))
    )
    return (
        '{{\n'
        '  "collisionKind": {ck},\n'
        '  "bboxMode": {bm},\n'
        '  "bbox_left": {bl},\n'
        '  "bbox_right": {br},\n'
        '  "bbox_top": {bt},\n'
        '  "bbox_bottom": {bb},\n'
        '  "width": {w},\n'
        '  "height": {h},\n'
        '  "origin": {orig},\n'
        '  "xorigin": {xo},\n'
        '  "yorigin": {yo},\n'
        '  "frames":[\n    {frames}\n  ],\n'
        '  "layers":[\n    {layers}\n  ],\n'
        '  "name":"{name}",\n'
        '  "resourceType":"GMSprite",\n'
        '  "resourceVersion":"2.0",\n'
        '}}'
    ).format(
        ck=collision_kind, bm=bbox_mode,
        bl=bbox_left, br=bbox_right, bt=bbox_top, bb=bbox_bottom,
        w=width, h=height, orig=origin, xo=xorigin, yo=yorigin,
        frames=frames_json, layers=layers_json, name=sprite_name,
    )


def _make_yy_content_with_sequence(sprite_name: str, frame_guids: list[str], layer_guids: list[str],
                                     collision_kind: int = 1, bbox_mode: int = 0,
                                     bbox_left: int = 0, bbox_right: int = 31,
                                     bbox_top: int = 0, bbox_bottom: int = 31,
                                     width: int = 32, height: int = 32,
                                     origin: int = 0, xorigin: int = 0, yorigin: int = 0,
                                     layer_visible: list[bool] | None = None,
                                     playback_speed: float = 30.0, playback_speed_type: int = 0,
                                     playback: int = 1, frame_lengths: list[float] | None = None) -> str:
    """Build a .yy file string with collision fields AND sequence animation data."""
    if layer_visible is None:
        layer_visible = [True] * len(layer_guids)
    if frame_lengths is None:
        frame_lengths = [1.0] * len(frame_guids)
    frames_json = ",\n    ".join(
        '{{"$GMSpriteFrame":"v1","%Name":"{g}","name":"{g}","resourceType":"GMSpriteFrame","resourceVersion":"2.0",}}'.format(g=g)
        for g in frame_guids
    )
    layers_json = ",\n    ".join(
        '{{"$GMImageLayer":"","name":"{g}","displayName":"Layer {i}","opacity":100.0,"visible":{v},"resourceType":"GMImageLayer","resourceVersion":"2.0",}}'.format(
            g=g, i=i, v="true" if v else "false")
        for i, (g, v) in enumerate(zip(layer_guids, layer_visible))
    )
    # Build sequence keyframes
    keyframes: list[str] = []
    for idx, (guid, length) in enumerate(zip(frame_guids, frame_lengths)):
        keyframes.append(
            '{{"Key": {key}, "Length": {length}, "Channels": {{"0": {{"Id": {{"name": "{guid}"}}}}}}}}'.format(
                key=idx, length=length, guid=guid)
        )
    keyframes_json = ",\n        ".join(keyframes)
    return (
        '{{\n'
        '  "collisionKind": {ck},\n'
        '  "bboxMode": {bm},\n'
        '  "bbox_left": {bl},\n'
        '  "bbox_right": {br},\n'
        '  "bbox_top": {bt},\n'
        '  "bbox_bottom": {bb},\n'
        '  "width": {w},\n'
        '  "height": {h},\n'
        '  "origin": {orig},\n'
        '  "xorigin": {xo},\n'
        '  "yorigin": {yo},\n'
        '  "frames":[\n    {frames}\n  ],\n'
        '  "layers":[\n    {layers}\n  ],\n'
        '  "sequence": {{\n'
        '    "playbackSpeed": {pbs},\n'
        '    "playbackSpeedType": {pbst},\n'
        '    "playback": {pb},\n'
        '    "tracks": [{{\n'
        '      "keyframes": {{\n'
        '        "Keyframes": [\n'
        '        {kf}\n'
        '        ]\n'
        '      }}\n'
        '    }}]\n'
        '  }},\n'
        '  "name":"{name}",\n'
        '  "resourceType":"GMSprite",\n'
        '  "resourceVersion":"2.0",\n'
        '}}'
    ).format(
        ck=collision_kind, bm=bbox_mode,
        bl=bbox_left, br=bbox_right, bt=bbox_top, bb=bbox_bottom,
        w=width, h=height, orig=origin, xo=xorigin, yo=yorigin,
        frames=frames_json, layers=layers_json, name=sprite_name,
        pbs=playback_speed, pbst=playback_speed_type, pb=playback,
        kf=keyframes_json,
    )


class TestParseCollisionData(unittest.TestCase):
    """Test _parse_collision_data() directly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yy(self, sprite_name: str, content: str) -> None:
        sprite_dir = os.path.join(self.gm_dir, "sprites", sprite_name)
        os.makedirs(sprite_dir, exist_ok=True)
        with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_valid_collision_fields(self):
        content = _make_yy_content_with_collision(
            "spr_test", ["frame1"], ["layer1"],
            collision_kind=1, bbox_mode=2,
            bbox_left=5, bbox_right=27,
            bbox_top=3, bbox_bottom=29,
            width=32, height=32, origin=4,
        )
        self._write_yy("spr_test", content)

        result = self.converter._parse_collision_data("spr_test")
        self.assertIsNotNone(result)
        result = cast(CollisionData, result)
        self.assertEqual(result["collisionKind"], 1)
        self.assertEqual(result["bboxMode"], 2)
        self.assertEqual(result["bbox_left"], 5)
        self.assertEqual(result["bbox_right"], 27)
        self.assertEqual(result["bbox_top"], 3)
        self.assertEqual(result["bbox_bottom"], 29)
        self.assertEqual(result["width"], 32)
        self.assertEqual(result["height"], 32)
        self.assertEqual(result["origin"], 4)

    def test_parses_custom_origin(self):
        content = _make_yy_content_with_collision(
            "spr_custom", ["frame1"], ["layer1"],
            origin=9, xorigin=10, yorigin=20,
            width=64, height=64,
        )
        self._write_yy("spr_custom", content)

        result = self.converter._parse_collision_data("spr_custom")
        self.assertIsNotNone(result)
        result = cast(CollisionData, result)
        self.assertEqual(result["origin"], 9)
        self.assertEqual(result["xorigin"], 10)
        self.assertEqual(result["yorigin"], 20)

    def test_returns_none_for_missing_file(self):
        result = self.converter._parse_collision_data("nonexistent_sprite")
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        self._write_yy("bad_spr", "not json at all {{{")
        result = self.converter._parse_collision_data("bad_spr")
        self.assertIsNone(result)


class TestComputeOriginOffset(unittest.TestCase):
    """Test _compute_origin_offset() for all origin presets."""

    def setUp(self):
        self.converter = SpriteConverter(
            "/fake/gm", "/fake/godot",
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def _make_data(self, origin: int, w: int = 64, h: int = 32,
                   xorigin: int = 0, yorigin: int = 0) -> CollisionData:
        return {
            "collisionKind": 1, "bboxMode": 0,
            "bbox_left": 0, "bbox_right": w - 1,
            "bbox_top": 0, "bbox_bottom": h - 1,
            "width": w, "height": h,
            "origin": origin,
            "xorigin": xorigin, "yorigin": yorigin,
        }

    def test_top_left(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(0)), (0, 0))

    def test_top_center(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(1)), (32, 0))

    def test_top_right(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(2)), (64, 0))

    def test_middle_left(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(3)), (0, 16))

    def test_middle_center(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(4)), (32, 16))

    def test_middle_right(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(5)), (64, 16))

    def test_bottom_left(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(6)), (0, 32))

    def test_bottom_center(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(7)), (32, 32))

    def test_bottom_right(self):
        self.assertEqual(self.converter._compute_origin_offset(self._make_data(8)), (64, 32))

    def test_custom_origin(self):
        self.assertEqual(
            self.converter._compute_origin_offset(self._make_data(9, xorigin=10, yorigin=25)),
            (10, 25),
        )


class TestGenerateSpriteScene(unittest.TestCase):
    """Test _generate_sprite_scene() .tscn file creation."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_collision_data(self, collision_kind: int = 1, bbox_left: int = 0, bbox_right: int = 31,
                              bbox_top: int = 0, bbox_bottom: int = 31, width: int = 32, height: int = 32,
                              origin: int = 0, xorigin: int = 0, yorigin: int = 0) -> CollisionData:
        return {
            "collisionKind": collision_kind,
            "bboxMode": 0,
            "bbox_left": bbox_left, "bbox_right": bbox_right,
            "bbox_top": bbox_top, "bbox_bottom": bbox_bottom,
            "width": width, "height": height,
            "origin": origin, "xorigin": xorigin, "yorigin": yorigin,
        }

    def test_rectangle_scene_created(self):
        data = self._make_collision_data(collision_kind=1)
        self.converter._generate_sprite_scene("spr_rect", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_rect", "spr_rect.tscn")
        self.assertTrue(os.path.exists(tscn_path))

        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn("[gd_scene format=3 load_steps=2]", content)
        self.assertIn('type="RectangleShape2D"', content)
        self.assertIn("size = Vector2(32, 32)", content)
        self.assertIn('type="Area2D"', content)
        self.assertIn("metadata/gamemaker_width = 32", content)
        self.assertIn("metadata/gamemaker_height = 32", content)
        self.assertIn("metadata/gamemaker_origin_x = 0", content)
        self.assertIn("metadata/gamemaker_origin_y = 0", content)
        self.assertIn('type="Sprite2D"', content)
        self.assertIn('type="CollisionShape2D"', content)
        self.assertIn('res://sprites/spr_rect/spr_rect.png', content)

    def test_static_scene_uses_sanitized_texture_filename(self):
        self.converter._generate_sprite_scene("sLogo", None, 1, subfolder="logo")

        tscn_path = os.path.join(self.godot_dir, "sprites", "logo", "s_logo", "s_logo.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('res://sprites/logo/s_logo/s_logo.png', content)
        self.assertNotIn("sLogo.png", content)

    def test_rectangle_with_origin_offset(self):
        # Middle center origin on 32x32 sprite, full bbox
        data = self._make_collision_data(collision_kind=1, origin=4, width=32, height=32,
                                          bbox_left=0, bbox_right=31, bbox_top=0, bbox_bottom=31)
        self.converter._generate_sprite_scene("spr_centered", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_centered", "spr_centered.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        # Full bbox on 32x32: bbox_center = (0+31+1)/2 = 16, sprite_center = 16
        # offset = (0, 0) → no position line needed (but code still writes it)
        self.assertIn("position = Vector2(0.0, 0.0)", content)
        self.assertIn("metadata/gamemaker_origin_x = 16.0", content)
        self.assertIn("metadata/gamemaker_origin_y = 16.0", content)

    def test_multiframe_references_first_frame(self):
        data = self._make_collision_data(collision_kind=1)
        anim_data: AnimationData = {"playbackSpeed": 30.0, "playbackSpeedType": 0,
                                    "loop": True, "frame_durations": [1.0, 1.0, 1.0]}
        self.converter._generate_sprite_scene("spr_anim", data, 3, anim_data)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_anim", "spr_anim.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn("spr_anim_1.png", content)

    def test_animated_scene_uses_sanitized_texture_filenames(self):
        anim_data: AnimationData = {
            "playbackSpeed": 30.0,
            "playbackSpeedType": 0,
            "loop": True,
            "frame_durations": [1.0, 1.0],
        }
        self.converter._generate_sprite_scene("sLogo", None, 2, anim_data, subfolder="logo")

        tscn_path = os.path.join(self.godot_dir, "sprites", "logo", "s_logo", "s_logo.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('res://sprites/logo/s_logo/s_logo_1.png', content)
        self.assertIn('res://sprites/logo/s_logo/s_logo_2.png', content)
        self.assertNotIn("sLogo_1.png", content)
        self.assertNotIn("sLogo_2.png", content)

    def test_ellipse_circle_shape(self):
        # Square bbox -> CircleShape2D
        data = self._make_collision_data(collision_kind=2, bbox_left=0, bbox_right=31,
                                          bbox_top=0, bbox_bottom=31)
        self.converter._generate_sprite_scene("spr_circle", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_circle", "spr_circle.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('type="CircleShape2D"', content)
        self.assertIn("radius = 16.0", content)

    def test_ellipse_capsule_shape(self):
        # Non-square bbox -> CapsuleShape2D
        data = self._make_collision_data(collision_kind=2, bbox_left=0, bbox_right=15,
                                          bbox_top=0, bbox_bottom=63, width=16, height=64)
        self.converter._generate_sprite_scene("spr_capsule", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_capsule", "spr_capsule.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('type="CapsuleShape2D"', content)
        self.assertIn("radius = 8.0", content)
        self.assertIn("height = 64", content)

    def test_diamond_shape(self):
        data = self._make_collision_data(collision_kind=3, bbox_left=0, bbox_right=31,
                                          bbox_top=0, bbox_bottom=31)
        self.converter._generate_sprite_scene("spr_diamond", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_diamond", "spr_diamond.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('type="ConvexPolygonShape2D"', content)
        self.assertIn("PackedVector2Array(", content)

    def test_precise_falls_back_to_rectangle(self):
        data = self._make_collision_data(collision_kind=0)
        self.converter._generate_sprite_scene("spr_precise", data, 1)

        tscn_path = os.path.join(self.godot_dir, "sprites", "spr_precise", "spr_precise.tscn")
        with open(tscn_path, "r") as f:
            content = f.read()

        self.assertIn('type="RectangleShape2D"', content)


class TestParseAnimationData(unittest.TestCase):
    """Test _parse_animation_data() directly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yy(self, sprite_name: str, content: str) -> None:
        sprite_dir = os.path.join(self.gm_dir, "sprites", sprite_name)
        os.makedirs(sprite_dir, exist_ok=True)
        with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_fps_speed(self):
        content = _make_yy_content_with_sequence(
            "spr_fps", ["f1"], ["l1"],
            playback_speed=30.0, playback_speed_type=0, playback=1,
        )
        self._write_yy("spr_fps", content)
        result = self.converter._parse_animation_data("spr_fps")
        self.assertIsNotNone(result)
        result = cast(AnimationData, result)
        self.assertEqual(result["playbackSpeed"], 30.0)
        self.assertEqual(result["playbackSpeedType"], 0)
        self.assertTrue(result["loop"])

    def test_parses_per_game_frame_speed(self):
        content = _make_yy_content_with_sequence(
            "spr_pgf", ["f1"], ["l1"],
            playback_speed=1.0, playback_speed_type=1,
        )
        self._write_yy("spr_pgf", content)
        result = self.converter._parse_animation_data("spr_pgf")
        self.assertIsNotNone(result)
        result = cast(AnimationData, result)
        self.assertEqual(result["playbackSpeed"], 1.0)
        self.assertEqual(result["playbackSpeedType"], 1)

    def test_parses_non_looping(self):
        content = _make_yy_content_with_sequence(
            "spr_noloop", ["f1"], ["l1"],
            playback=0,
        )
        self._write_yy("spr_noloop", content)
        result = self.converter._parse_animation_data("spr_noloop")
        self.assertIsNotNone(result)
        result = cast(AnimationData, result)
        self.assertFalse(result["loop"])

    def test_parses_custom_frame_durations(self):
        content = _make_yy_content_with_sequence(
            "spr_dur", ["f1", "f2", "f3"], ["l1"],
            frame_lengths=[1.0, 2.0, 0.5],
        )
        self._write_yy("spr_dur", content)
        result = self.converter._parse_animation_data("spr_dur")
        self.assertIsNotNone(result)
        result = cast(AnimationData, result)
        self.assertEqual(result["frame_durations"], [1.0, 2.0, 0.5])

    def test_returns_none_for_missing_file(self):
        result = self.converter._parse_animation_data("nonexistent_sprite")
        self.assertIsNone(result)

    def test_returns_none_for_no_sequence(self):
        # Use the old helper that doesn't include a sequence object
        content = _make_yy_content_with_collision(
            "spr_old", ["f1"], ["l1"],
        )
        self._write_yy("spr_old", content)
        result = self.converter._parse_animation_data("spr_old")
        self.assertIsNone(result)


class TestComputeGodotFps(unittest.TestCase):
    """Test _compute_godot_fps() static method."""

    def test_fps_type_passthrough(self):
        data: AnimationData = {"playbackSpeed": 30.0, "playbackSpeedType": 0, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 30.0)

    def test_fps_type_sixty(self):
        data: AnimationData = {"playbackSpeed": 60.0, "playbackSpeedType": 0, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 60.0)

    def test_per_game_frame_one(self):
        data: AnimationData = {"playbackSpeed": 1.0, "playbackSpeedType": 1, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 60.0)

    def test_per_game_frame_half(self):
        data: AnimationData = {"playbackSpeed": 0.5, "playbackSpeedType": 1, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 30.0)

    def test_per_game_frame_zero(self):
        data: AnimationData = {"playbackSpeed": 0.0, "playbackSpeedType": 1, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 0.0)

    def test_zero_fps(self):
        data: AnimationData = {"playbackSpeed": 0.0, "playbackSpeedType": 0, "loop": True, "frame_durations": [1.0]}
        self.assertEqual(SpriteConverter._compute_godot_fps(data), 0.0)


class TestGenerateAnimatedScene(unittest.TestCase):
    """Test animated and static scene generation."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.converter = SpriteConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: None,
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_collision_data(self, collision_kind: int = 1, bbox_left: int = 0, bbox_right: int = 31,
                              bbox_top: int = 0, bbox_bottom: int = 31, width: int = 32, height: int = 32,
                              origin: int = 0, xorigin: int = 0, yorigin: int = 0) -> CollisionData:
        return {
            "collisionKind": collision_kind,
            "bboxMode": 0,
            "bbox_left": bbox_left, "bbox_right": bbox_right,
            "bbox_top": bbox_top, "bbox_bottom": bbox_bottom,
            "width": width, "height": height,
            "origin": origin, "xorigin": xorigin, "yorigin": yorigin,
        }

    def _make_anim_data(self, speed: float = 30.0, speed_type: int = 0,
                        loop: bool = True, durations: list[float] | None = None) -> AnimationData:
        if durations is None:
            durations = [1.0]
        return {
            "playbackSpeed": speed,
            "playbackSpeedType": speed_type,
            "loop": loop,
            "frame_durations": durations,
        }

    def _read_tscn(self, sprite_name: str) -> str:
        tscn_path = os.path.join(self.godot_dir, "sprites", sprite_name, sprite_name + ".tscn")
        with open(tscn_path, "r") as f:
            return f.read()

    def test_animated_scene_has_animated_sprite2d(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(durations=[1.0, 1.0, 1.0])
        self.converter._generate_sprite_scene("spr_anim", collision, 3, anim)
        content = self._read_tscn("spr_anim")
        self.assertIn('type="AnimatedSprite2D"', content)
        self.assertIn('type="SpriteFrames"', content)
        self.assertIn("metadata/gamemaker_origin_x = 0", content)
        self.assertIn("metadata/gamemaker_origin_y = 0", content)
        self.assertNotIn('type="Sprite2D"', content)

    def test_animated_scene_has_correct_frame_count(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(durations=[1.0, 1.0, 1.0, 1.0])
        self.converter._generate_sprite_scene("spr_4f", collision, 4, anim)
        content = self._read_tscn("spr_4f")
        # Should have 4 ext_resources
        for i in range(1, 5):
            self.assertIn(f'spr_4f_{i}.png', content)

    def test_animated_scene_has_correct_speed(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(speed=60.0, durations=[1.0, 1.0])
        self.converter._generate_sprite_scene("spr_fast", collision, 2, anim)
        content = self._read_tscn("spr_fast")
        self.assertIn('"speed": 60.0', content)

    def test_animated_scene_loop_flag(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(loop=False, durations=[1.0, 1.0])
        self.converter._generate_sprite_scene("spr_noloop", collision, 2, anim)
        content = self._read_tscn("spr_noloop")
        self.assertIn('"loop": false', content)

    def test_animated_scene_custom_durations(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(durations=[1.0, 2.0, 0.5])
        self.converter._generate_sprite_scene("spr_dur", collision, 3, anim)
        content = self._read_tscn("spr_dur")
        self.assertIn('"duration": 1.0', content)
        self.assertIn('"duration": 2.0', content)
        self.assertIn('"duration": 0.5', content)

    def test_animated_scene_has_collision(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(durations=[1.0, 1.0])
        self.converter._generate_sprite_scene("spr_col", collision, 2, anim)
        content = self._read_tscn("spr_col")
        self.assertIn('type="CollisionShape2D"', content)

    def test_animated_scene_autoplay(self):
        collision = self._make_collision_data()
        anim = self._make_anim_data(durations=[1.0, 1.0])
        self.converter._generate_sprite_scene("spr_auto", collision, 2, anim)
        content = self._read_tscn("spr_auto")
        self.assertIn('autoplay = "default"', content)
        self.assertIn('animation = &"default"', content)

    def test_scene_without_collision(self):
        anim = self._make_anim_data(durations=[1.0, 1.0])
        self.converter._generate_sprite_scene("spr_nocol", None, 2, anim)
        content = self._read_tscn("spr_nocol")
        self.assertIn('type="AnimatedSprite2D"', content)
        self.assertNotIn('CollisionShape2D', content)

    def test_static_scene_without_collision(self):
        self.converter._generate_sprite_scene("spr_static", None, 1)
        content = self._read_tscn("spr_static")
        self.assertIn('type="Sprite2D"', content)
        self.assertNotIn('CollisionShape2D', content)
        self.assertNotIn('AnimatedSprite2D', content)


if __name__ == "__main__":
    unittest.main()
