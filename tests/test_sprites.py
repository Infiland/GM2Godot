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


if __name__ == "__main__":
    unittest.main()
