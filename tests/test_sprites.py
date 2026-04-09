import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image
from src.conversion.sprites import SpriteConverter


class TestSpriteConverterBasic(unittest.TestCase):
    """Test SpriteConverter with a minimal fake GameMaker project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

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


class TestSpriteConverterCompactLogging(unittest.TestCase):
    """Test SpriteConverter with compact logging enabled."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.log_messages = []
        self.update_messages = []

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
        logs = []
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
        self.logs = []

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
        joined = " ".join(self.logs)
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for empty sprites folder")


# Helper to create a minimal .yy file with trailing commas (like real GameMaker files)
def _make_yy_content(sprite_name, frame_guids, layer_guids, layer_visible=None):
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
        self.logs = []

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
                pixel = img.getpixel((0, 0))[:3]
            expected_rgb = Image.new("RGBA", (1, 1), expected_color).getpixel((0, 0))[:3]
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
    """Test that multi-layer sprites pick the first visible layer."""

    FRAME_GUID = "aaaaaaaa-0000-0000-0000-000000000000"
    LAYER_VISIBLE = "22222222-0000-0000-0000-000000000000"
    LAYER_HIDDEN = "11111111-0000-0000-0000-000000000000"

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        sprite_dir = os.path.join(self.gm_dir, "sprites", "multi_layer")
        os.makedirs(sprite_dir)

        # Hidden layer listed first, visible layer second
        yy_content = _make_yy_content(
            "multi_layer", [self.FRAME_GUID],
            [self.LAYER_HIDDEN, self.LAYER_VISIBLE],
            layer_visible=[False, True])
        with open(os.path.join(sprite_dir, "multi_layer.yy"), "w") as f:
            f.write(yy_content)

        frame_dir = os.path.join(sprite_dir, "layers", self.FRAME_GUID)
        os.makedirs(frame_dir)
        # Hidden layer: red
        img = Image.new("RGBA", (2, 2), "red")
        img.save(os.path.join(frame_dir, self.LAYER_HIDDEN + ".png"), "PNG")
        # Visible layer: green
        img = Image.new("RGBA", (2, 2), "green")
        img.save(os.path.join(frame_dir, self.LAYER_VISIBLE + ".png"), "PNG")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_picks_first_visible_layer(self):
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
            pixel = img.getpixel((0, 0))[:3]
        self.assertEqual(pixel, (0, 128, 0),
                         "Should use the visible layer (green), not hidden (red)")


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

    def _write_yy(self, sprite_name, content):
        sprite_dir = os.path.join(self.gm_dir, "sprites", sprite_name)
        os.makedirs(sprite_dir, exist_ok=True)
        with open(os.path.join(sprite_dir, sprite_name + ".yy"), "w") as f:
            f.write(content)

    def test_parses_frames_in_order(self):
        guids = ["cc-guid", "aa-guid", "bb-guid"]
        self._write_yy("test_spr", _make_yy_content("test_spr", guids, ["layer1"]))

        result = self.converter._parse_sprite_yy("test_spr")
        self.assertIsNotNone(result)
        frame_guids, layer_guid = result
        self.assertEqual(frame_guids, guids)
        self.assertEqual(layer_guid, "layer1")

    def test_trailing_commas_handled(self):
        # Write content with trailing commas (as real .yy files have)
        content = '{"frames":[{"name":"frame1",},],"layers":[{"name":"layer1","visible":true,},],"name":"tc",}'
        self._write_yy("tc", content)

        result = self.converter._parse_sprite_yy("tc")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], ["frame1"])

    def test_returns_none_for_missing_file(self):
        result = self.converter._parse_sprite_yy("nonexistent_sprite")
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        self._write_yy("bad", "not json at all {{{")
        result = self.converter._parse_sprite_yy("bad")
        self.assertIsNone(result)

    def test_selects_first_visible_layer(self):
        guids = ["frame1"]
        layers = ["hidden_layer", "visible_layer"]
        self._write_yy("vis", _make_yy_content("vis", guids, layers,
                                                 layer_visible=[False, True]))
        result = self.converter._parse_sprite_yy("vis")
        self.assertIsNotNone(result)
        _, layer_guid = result
        self.assertEqual(layer_guid, "visible_layer")


if __name__ == "__main__":
    unittest.main()
