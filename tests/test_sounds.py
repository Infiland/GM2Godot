# pyright: reportPrivateUsage=false

import json
import os
import sys
import shutil
import tempfile
import unittest
from typing import NotRequired, TypeAlias, TypedDict, Unpack, cast

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.sounds import SoundConverter
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback


SoundYY: TypeAlias = dict[str, object]


class SoundConverterKwargs(TypedDict, total=False):
    log_callback: LogCallback
    progress_callback: ProgressCallback
    conversion_running: ConversionRunning
    organize_by_audio_group: NotRequired[bool]


MINIMAL_SOUND_YY: SoundYY = {
    "$GMSound": "",
    "%Name": "snd_test",
    "name": "snd_test",
    "audioGroupId": {"name": "audiogroup_default", "path": "audiogroups/audiogroup_default.yy"},
    "bitDepth": 16,
    "bitRate": 128,
    "compression": 0,
    "duration": 0.5,
    "preload": True,
    "sampleRate": 44100,
    "soundFile": "snd_test.wav",
    "type": 0,
    "volume": 1.0,
    "parent": {"name": "Sounds", "path": "folders/Sounds.yy"},
    "resourceType": "GMSound",
    "resourceVersion": "2.0",
}


def _make_sound_yy(base_dir: str, sound_name: str, overrides: SoundYY | None = None) -> str:
    """Create a sound .yy file + placeholder audio in standard GM structure."""
    sound_dir = os.path.join(base_dir, "sounds", sound_name)
    os.makedirs(sound_dir, exist_ok=True)
    data = dict(MINIMAL_SOUND_YY)
    data["name"] = sound_name
    data["%Name"] = sound_name
    data["soundFile"] = f"{sound_name}.wav"
    if overrides:
        data.update(overrides)
    yy_path = os.path.join(sound_dir, f"{sound_name}.yy")
    with open(yy_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    # Create placeholder audio file
    sound_file = data["soundFile"]
    assert isinstance(sound_file, str)
    audio_path = os.path.join(sound_dir, sound_file)
    with open(audio_path, "wb") as f:
        f.write(b"\x00" * 64)
    return yy_path


class TestSoundConverterBasic(unittest.TestCase):
    """Test SoundConverter copies audio files via .yy discovery."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        _make_sound_yy(self.gm_dir, "jump")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, **kwargs: Unpack[SoundConverterKwargs]) -> SoundConverter:
        defaults: SoundConverterKwargs = {
            "log_callback": lambda msg: self.logs.append(msg),
            "progress_callback": lambda v: None,
            "conversion_running": lambda: True,
        }
        defaults.update(kwargs)
        return SoundConverter(self.gm_dir, self.godot_dir, **defaults)

    def test_copies_wav_to_godot(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "sounds", "jump", "jump.wav")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

    def test_generates_import_file(self):
        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "jump", "jump.wav.import")
        self.assertTrue(os.path.isfile(import_path),
                        f"Expected {import_path} to exist after conversion")

    def test_import_file_wav_content(self):
        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "jump", "jump.wav.import")
        with open(import_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('importer="wav"', content)
        self.assertIn('type="AudioStreamWAV"', content)
        self.assertIn('source_file="res://sounds/jump/jump.wav"', content)
        self.assertIn('edit/loop_mode=0', content)


class TestSoundConverterFormats(unittest.TestCase):
    """Test that different audio formats produce correct .import files."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

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

    def test_mp3_import(self):
        _make_sound_yy(self.gm_dir, "bgm", overrides={
            "soundFile": "bgm.mp3",
        })
        # Replace the .wav placeholder with .mp3
        wav_path = os.path.join(self.gm_dir, "sounds", "bgm", "bgm.wav")
        if os.path.exists(wav_path):
            os.remove(wav_path)
        mp3_path = os.path.join(self.gm_dir, "sounds", "bgm", "bgm.mp3")
        with open(mp3_path, "wb") as f:
            f.write(b"\x00" * 64)

        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "bgm", "bgm.mp3.import")
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('importer="mp3"', content)
        self.assertIn('type="AudioStreamMP3"', content)
        self.assertIn('loop=false', content)

    def test_ogg_import(self):
        _make_sound_yy(self.gm_dir, "hit", overrides={
            "soundFile": "hit.ogg",
        })
        wav_path = os.path.join(self.gm_dir, "sounds", "hit", "hit.wav")
        if os.path.exists(wav_path):
            os.remove(wav_path)
        ogg_path = os.path.join(self.gm_dir, "sounds", "hit", "hit.ogg")
        with open(ogg_path, "wb") as f:
            f.write(b"\x00" * 64)

        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "hit", "hit.ogg.import")
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('importer="oggvorbisstr"', content)
        self.assertIn('type="AudioStreamOggVorbis"', content)
        self.assertIn('loop=false', content)


class TestSoundConverterMetadata(unittest.TestCase):
    """Test that sound metadata is logged correctly."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

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

    def test_volume_logging(self):
        _make_sound_yy(self.gm_dir, "quiet", overrides={"volume": 0.5})

        converter = self._make_converter()
        converter.convert_all()

        volume_logs = [m for m in self.logs if "volume=" in m]
        self.assertTrue(len(volume_logs) > 0,
                        f"Expected volume note in logs, got: {self.logs}")

    def test_no_volume_logging_at_default(self):
        _make_sound_yy(self.gm_dir, "normal", overrides={"volume": 1.0})

        converter = self._make_converter()
        converter.convert_all()

        volume_logs = [m for m in self.logs if "volume=" in m]
        self.assertEqual(len(volume_logs), 0,
                         "Should not log volume note when volume is 1.0")

    def test_bus_logging(self):
        _make_sound_yy(self.gm_dir, "music", overrides={
            "audioGroupId": {"name": "audiogroup_music", "path": "audiogroups/audiogroup_music.yy"},
        })

        converter = self._make_converter()
        converter.convert_all()

        bus_logs = [m for m in self.logs if "audiogroup_music" in m]
        self.assertTrue(len(bus_logs) > 0,
                        f"Expected bus note in logs, got: {self.logs}")

    def test_no_bus_logging_at_default(self):
        _make_sound_yy(self.gm_dir, "sfx")

        converter = self._make_converter()
        converter.convert_all()

        bus_logs = [m for m in self.logs if "audio bus" in m.lower() or "Audio-Bus" in m]
        self.assertEqual(len(bus_logs), 0,
                         "Should not log bus note when audio group is default")

    def test_parse_sound_yy(self):
        yy_path = _make_sound_yy(self.gm_dir, "test_parse", overrides={
            "volume": 0.7,
            "sampleRate": 22050,
            "bitDepth": 8,
            "audioGroupId": {"name": "audiogroup_sfx", "path": "audiogroups/audiogroup_sfx.yy"},
        })

        converter = self._make_converter()
        result = converter._parse_sound_yy(yy_path)

        self.assertIsNotNone(result)
        result = cast(dict[str, str | int | float], result)
        volume = result["volume"]
        assert isinstance(volume, (int, float))
        self.assertEqual(result['name'], "test_parse")
        self.assertAlmostEqual(volume, 0.7)
        self.assertEqual(result['sampleRate'], 22050)
        self.assertEqual(result['bitDepth'], 8)
        self.assertEqual(result['audioGroupId'], "audiogroup_sfx")


class TestSoundConverterAudioGroupMap(unittest.TestCase):
    """Test sound-to-audio-group mapping export."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, **kwargs: Unpack[SoundConverterKwargs]) -> SoundConverter:
        defaults: SoundConverterKwargs = {
            "log_callback": lambda msg: self.logs.append(msg),
            "progress_callback": lambda v: None,
            "conversion_running": lambda: True,
            "organize_by_audio_group": False,
        }
        defaults.update(kwargs)
        return SoundConverter(self.gm_dir, self.godot_dir, **defaults)

    def test_generates_audio_group_map_file(self):
        _make_sound_yy(self.gm_dir, "snd_music", overrides={
            "audioGroupId": {"name": "audiogroup_music", "path": "audiogroups/audiogroup_music.yy"},
        })
        _make_sound_yy(self.gm_dir, "snd_click")

        converter = self._make_converter()
        converter.convert_all()

        map_path = os.path.join(self.godot_dir, "sounds", "audio_group_map.json")
        self.assertTrue(os.path.isfile(map_path))

        with open(map_path, "r", encoding="utf-8") as f:
            data = cast(dict[str, object], json.load(f))
        sounds = cast(dict[str, str], data["sounds"])

        self.assertEqual(data.get("format_version"), 1)
        self.assertEqual(sounds["snd_music"], "audiogroup_music")
        self.assertEqual(sounds["snd_click"], "audiogroup_default")

    def test_map_skips_failed_sound_entries(self):
        _make_sound_yy(self.gm_dir, "ok")

        # Build a .yy that references a missing audio file
        sound_dir = os.path.join(self.gm_dir, "sounds", "ghost")
        os.makedirs(sound_dir, exist_ok=True)
        data = dict(MINIMAL_SOUND_YY)
        data["name"] = "ghost"
        data["%Name"] = "ghost"
        data["soundFile"] = "ghost.wav"
        with open(os.path.join(sound_dir, "ghost.yy"), "w", encoding="utf-8") as f:
            json.dump(data, f)

        converter = self._make_converter()
        converter.convert_all()

        map_path = os.path.join(self.godot_dir, "sounds", "audio_group_map.json")
        with open(map_path, "r", encoding="utf-8") as f:
            map_data = cast(dict[str, object], json.load(f))
        exported = cast(dict[str, str], map_data["sounds"])

        self.assertIn("ok", exported)
        self.assertNotIn("ghost", exported)


class TestSoundConverterVolumeConversion(unittest.TestCase):
    """Test the volume-to-dB static method."""

    def test_full_volume(self):
        self.assertAlmostEqual(SoundConverter._volume_to_db(1.0), 0.0, places=2)

    def test_half_volume(self):
        self.assertAlmostEqual(SoundConverter._volume_to_db(0.5), -6.02, places=1)

    def test_zero_volume(self):
        self.assertEqual(SoundConverter._volume_to_db(0.0), -80.0)

    def test_quarter_volume(self):
        self.assertAlmostEqual(SoundConverter._volume_to_db(0.25), -12.04, places=1)


class TestSoundConverterSubfolders(unittest.TestCase):
    """Test that GM folder hierarchy is respected."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self, **kwargs: Unpack[SoundConverterKwargs]) -> SoundConverter:
        defaults: SoundConverterKwargs = {
            "log_callback": lambda msg: self.logs.append(msg),
            "progress_callback": lambda v: None,
            "conversion_running": lambda: True,
            "organize_by_audio_group": False,
        }
        defaults.update(kwargs)
        return SoundConverter(self.gm_dir, self.godot_dir, **defaults)

    def test_subfolder_hierarchy(self):
        _make_sound_yy(self.gm_dir, "explosion", overrides={
            "parent": {"name": "SFX", "path": "folders/Sounds/SFX.yy"},
        })

        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "sounds", "SFX", "explosion", "explosion.wav")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} in subfolder")

    def test_subfolder_import_file(self):
        _make_sound_yy(self.gm_dir, "explosion", overrides={
            "parent": {"name": "SFX", "path": "folders/Sounds/SFX.yy"},
        })

        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "SFX", "explosion", "explosion.wav.import")
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('source_file="res://sounds/SFX/explosion/explosion.wav"', content)

    def test_root_level_sound(self):
        _make_sound_yy(self.gm_dir, "beep")

        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "sounds", "beep", "beep.wav")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} at root level")

    def test_grouped_folders_enabled(self):
        _make_sound_yy(self.gm_dir, "theme", overrides={
            "audioGroupId": {"name": "audiogroup_music", "path": "audiogroups/audiogroup_music.yy"},
            "parent": {"name": "SFX", "path": "folders/Sounds/SFX.yy"},
        })

        converter = self._make_converter(organize_by_audio_group=True)
        converter.convert_all()

        expected = os.path.join(
            self.godot_dir, "sounds", "audiogroup_music", "SFX", "theme", "theme.wav"
        )
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} in grouped folder hierarchy")

    def test_grouped_import_file_path(self):
        _make_sound_yy(self.gm_dir, "theme", overrides={
            "audioGroupId": {"name": "audiogroup_music", "path": "audiogroups/audiogroup_music.yy"},
            "parent": {"name": "SFX", "path": "folders/Sounds/SFX.yy"},
        })

        converter = self._make_converter(organize_by_audio_group=True)
        converter.convert_all()

        import_path = os.path.join(
            self.godot_dir, "sounds", "audiogroup_music", "SFX", "theme", "theme.wav.import"
        )
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            'source_file="res://sounds/audiogroup_music/SFX/theme/theme.wav"',
            content,
        )


class TestSoundConverterEdgeCases(unittest.TestCase):
    """Test error handling and edge cases."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

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

    def test_missing_audio_file(self):
        """If the .yy references a file that doesn't exist, skip gracefully."""
        sound_dir = os.path.join(self.gm_dir, "sounds", "ghost")
        os.makedirs(sound_dir)
        data = dict(MINIMAL_SOUND_YY)
        data["name"] = "ghost"
        data["%Name"] = "ghost"
        data["soundFile"] = "ghost.wav"
        yy_path = os.path.join(sound_dir, "ghost.yy")
        with open(yy_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # Do NOT create the audio file

        converter = self._make_converter()
        converter.convert_all()  # should not raise

        audio_path = os.path.join(self.godot_dir, "sounds", "ghost", "ghost.wav")
        self.assertFalse(os.path.isfile(audio_path),
                         "Should not copy nonexistent audio file")

    def test_empty_sounds_no_crash(self):
        os.makedirs(os.path.join(self.gm_dir, "sounds"))

        converter = self._make_converter()
        converter.convert_all()  # should not raise

        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for empty sounds folder")


if __name__ == "__main__":
    unittest.main()
