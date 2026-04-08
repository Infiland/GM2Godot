import os
import sys
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.sounds import SoundConverter


class TestSoundConverterBasic(unittest.TestCase):
    """Test SoundConverter copies audio files correctly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        # Create a fake GM sounds folder with a .wav file (empty bytes are fine)
        sounds_dir = os.path.join(self.gm_dir, "sounds")
        os.makedirs(sounds_dir)
        self.test_wav = os.path.join(sounds_dir, "jump.wav")
        with open(self.test_wav, "wb") as f:
            f.write(b"\x00" * 64)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return SoundConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_copies_wav_to_godot(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "sounds", "jump.wav")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

    def test_multiple_sound_formats(self):
        """Converter should handle .mp3 and .ogg files too."""
        sounds_dir = os.path.join(self.gm_dir, "sounds")
        for name in ("bgm.mp3", "hit.ogg"):
            with open(os.path.join(sounds_dir, name), "wb") as f:
                f.write(b"\x00" * 32)

        converter = self._make_converter()
        converter.convert_all()

        for name in ("jump.wav", "bgm.mp3", "hit.ogg"):
            path = os.path.join(self.godot_dir, "sounds", name)
            self.assertTrue(os.path.isfile(path), f"Expected {path}")


class TestSoundConverterEmpty(unittest.TestCase):
    """Empty sounds folder should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs = []

        os.makedirs(os.path.join(self.gm_dir, "sounds"))

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_empty_sounds_no_crash(self):
        converter = SoundConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for empty sounds folder")


if __name__ == "__main__":
    unittest.main()
