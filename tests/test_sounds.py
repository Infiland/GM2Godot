# pyright: reportPrivateUsage=false

import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest
from typing import NotRequired, TypeAlias, TypedDict, Unpack, cast
from unittest.mock import patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.asset_output_paths import (
    build_asset_output_paths,
    resource_filesystem_path,
)
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.sound_metadata import (
    SoundConversionFields,
    parse_gamemaker_sound_metadata,
)
from src.conversion.sounds import SoundConverter, SoundData
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback
from src.localization import get_localized

SoundYY: TypeAlias = dict[str, object]


class SoundConverterKwargs(TypedDict, total=False):
    log_callback: LogCallback
    progress_callback: ProgressCallback
    conversion_running: ConversionRunning
    organize_by_audio_group: NotRequired[bool]
    diagnostics: NotRequired[DiagnosticCollector]


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

    def test_resource_outcome_counts_logical_sounds(self):
        _make_sound_yy(self.gm_dir, "second")
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result().resources

        self.assertEqual(counts.requested, 2)
        self.assertEqual(counts.executed, 2)
        self.assertEqual(counts.completed, 2)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)

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

    def test_import_source_path_uses_escaped_godot_string_literal(self) -> None:
        converter = self._make_converter()
        sound_file = 'clip"\\\n[remap]\nimporter=\t\x01evil.wav'
        expected_path = f"res://sounds/injected/{sound_file}"

        content = converter._generate_import_file(sound_file, "injected")

        self.assertIsNotNone(content)
        assert content is not None
        source_line = next(
            line for line in content.splitlines() if line.startswith("source_file=")
        )
        self.assertEqual(
            source_line,
            "source_file=" + json.dumps(expected_path, ensure_ascii=False),
        )
        self.assertNotIn('\n[remap]\nimporter=', content)


class TestSoundGeneratedPathCollisions(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        _make_sound_yy(self.gm_dir, "sndHit", {"soundFile": "sound.wav"})
        _make_sound_yy(self.gm_dir, "snd_hit", {"soundFile": "sound.wav"})
        for index, resource_name in enumerate(("sndHit", "snd_hit"), start=1):
            with open(
                os.path.join(self.gm_dir, "sounds", resource_name, "sound.wav"),
                "wb",
            ) as sound_file:
                sound_file.write(bytes([index]) * 64)

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_emitted_sounds_match_collision_safe_registry_paths(self) -> None:
        converter = SoundConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        paths = build_asset_output_paths(self.gm_dir, self.godot_dir)["sounds"]
        self.assertEqual(len({path.casefold() for path in paths.values()}), 2)
        payloads: list[bytes] = []
        for resource_name in ("sndHit", "snd_hit"):
            output_path = os.path.join(
                self.godot_dir,
                *paths[resource_name].removeprefix("res://").split("/"),
            )
            with open(output_path, "rb") as sound_file:
                payloads.append(sound_file.read())
            self.assertTrue(os.path.isfile(output_path + ".import"))
        self.assertNotEqual(payloads[0], payloads[1])

    def test_yyp_orphan_cannot_compete_for_referenced_output(self) -> None:
        with open(os.path.join(self.gm_dir, "CollisionSounds.yyp"), "w", encoding="utf-8") as project_file:
            json.dump(
                {
                    "resources": [
                        {
                            "id": {
                                "name": "sndHit",
                                "path": "sounds/sndHit/sndHit.yy",
                            }
                        }
                    ]
                },
                project_file,
            )

        for _attempt in range(4):
            shutil.rmtree(self.godot_dir)
            os.makedirs(self.godot_dir)
            SoundConverter(
                self.gm_dir,
                self.godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=2,
            ).convert_all()
            output_path = os.path.join(
                self.godot_dir,
                "sounds",
                "snd_hit",
                "sound.wav",
            )
            with open(output_path, "rb") as sound_file:
                self.assertEqual(sound_file.read(), bytes([1]) * 64)


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

    def test_map_write_failure_does_not_report_sound_completion(self) -> None:
        _make_sound_yy(self.gm_dir, "snd_music")
        _make_sound_yy(self.gm_dir, "snd_click")
        converter = self._make_converter()

        with patch.object(
            converter,
            "_write_audio_group_map",
            side_effect=OSError("map write failed"),
        ):
            with self.assertRaisesRegex(OSError, "map write failed"):
                converter.convert_all()

        with self.assertRaises(ValueError):
            converter.conversion_step_result(finalize_unfinished_as=None)
        self.assertEqual(
            converter.conversion_step_result(
                cancelled=False,
                finalize_unfinished_as="failed",
            ).resources,
            ConversionCounts(
                requested=2,
                executed=2,
                failed=2,
            ),
        )

    def test_cancellation_before_map_publication_skips_unfinished_sound(self) -> None:
        _make_sound_yy(self.gm_dir, "snd_cancelled")
        running = threading.Event()
        running.set()
        converter = self._make_converter(conversion_running=running.is_set)
        original_process_sound = converter._process_sound

        def process_then_cancel(yy_path: str):
            result = original_process_sound(yy_path)
            running.clear()
            return result

        with patch.object(
            converter,
            "_process_sound",
            side_effect=process_then_cancel,
        ):
            converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "sounds",
                    "audio_group_map.json",
                )
            )
        )
        with self.assertRaises(ValueError):
            converter.conversion_step_result(finalize_unfinished_as=None)
        result = converter.conversion_step_result()
        self.assertTrue(result.cancelled)
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=1,
                executed=1,
                skipped=1,
            ),
        )


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

        expected = os.path.join(self.godot_dir, "sounds", "sfx", "explosion", "explosion.wav")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} in subfolder")

    def test_subfolder_import_file(self):
        _make_sound_yy(self.gm_dir, "explosion", overrides={
            "parent": {"name": "SFX", "path": "folders/Sounds/SFX.yy"},
        })

        converter = self._make_converter()
        converter.convert_all()

        import_path = os.path.join(self.godot_dir, "sounds", "sfx", "explosion", "explosion.wav.import")
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('source_file="res://sounds/sfx/explosion/explosion.wav"', content)

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
            self.godot_dir, "sounds", "audiogroup_music", "sfx", "theme", "theme.wav"
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
            self.godot_dir, "sounds", "audiogroup_music", "sfx", "theme", "theme.wav.import"
        )
        self.assertTrue(os.path.isfile(import_path))
        with open(import_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            'source_file="res://sounds/audiogroup_music/sfx/theme/theme.wav"',
            content,
        )


class TestSoundConverterSourcePathContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> SoundConverter:
        return SoundConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )

    def _write_yyp(self, resources: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "SoundPaths.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "resources": [
                        {"id": {"name": name, "path": path}}
                        for name, path in resources
                    ]
                },
                project_file,
            )

    def _write_sound_yy(self, sound_name: str, sound_file: object) -> str:
        sound_dir = os.path.join(self.gm_dir, "sounds", sound_name)
        os.makedirs(sound_dir, exist_ok=True)
        data = dict(MINIMAL_SOUND_YY)
        data["name"] = sound_name
        data["%Name"] = sound_name
        data["soundFile"] = sound_file
        yy_path = os.path.join(sound_dir, f"{sound_name}.yy")
        with open(yy_path, "w", encoding="utf-8") as yy_file:
            json.dump(data, yy_file)
        return yy_path

    def test_accepts_contained_manifest_and_disk_discovered_sound_yy(self) -> None:
        referenced_yy = _make_sound_yy(self.gm_dir, "snd_referenced")
        orphan_yy = _make_sound_yy(self.gm_dir, "snd_orphan")
        converter = self._make_converter()

        self.assertEqual(
            set(converter.find_sound_files()),
            {referenced_yy, orphan_yy},
        )

        self._write_yyp(
            [("snd_referenced", r"sounds\snd_referenced\snd_referenced.yy")]
        )

        self.assertEqual(converter.find_sound_files(), [referenced_yy])

    def test_duplicate_manifest_sound_reference_is_converted_once(self) -> None:
        _make_sound_yy(self.gm_dir, "snd_duplicate")
        duplicate_path = "sounds/snd_duplicate/snd_duplicate.yy"
        self._write_yyp(
            [
                ("snd_duplicate", duplicate_path),
                ("snd_duplicate_alias", duplicate_path),
            ]
        )
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result(
            finalize_unfinished_as=None,
        ).resources

        self.assertEqual(counts.requested, 1)
        self.assertEqual(counts.executed, 1)
        self.assertEqual(counts.completed, 1)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)

    def test_missing_only_declared_sound_is_requested_and_skipped(self) -> None:
        self._write_yyp(
            [("snd_missing", "sounds/snd_missing/snd_missing.yy")]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-SOUND-SOURCE-UNAVAILABLE"
                and diagnostic.resource == "snd_missing"
                for diagnostic in diagnostics.diagnostics()
            )
        )
        self.assertTrue(
            any(
                "Skipping manifest-declared GameMaker sound 'snd_missing'"
                in log
                for log in self.logs
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "sounds",
                    "audio_group_map.json",
                )
            )
        )

    def test_safe_and_missing_declared_sounds_have_strict_counts(self) -> None:
        _make_sound_yy(self.gm_dir, "snd_safe")
        self._write_yyp(
            [
                ("snd_safe", "sounds/snd_safe/snd_safe.yy"),
                ("snd_missing", "sounds/snd_missing/snd_missing.yy"),
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

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
                    "sounds",
                    "snd_safe",
                    "snd_safe.wav",
                )
            )
        )
        map_path = os.path.join(
            self.godot_dir,
            "sounds",
            "audio_group_map.json",
        )
        with open(map_path, encoding="utf-8") as map_file:
            audio_group_map = cast(dict[str, str], json.load(map_file))
        self.assertEqual(
            audio_group_map,
            {
                "format_version": 1,
                "sounds": {"snd_safe": "audiogroup_default"},
            },
        )
        self.assertTrue(
            any(
                diagnostic.code == "GM2GD-SOUND-SOURCE-UNAVAILABLE"
                and diagnostic.resource == "snd_missing"
                for diagnostic in diagnostics.diagnostics()
            )
        )

    def test_rejected_declared_sound_is_requested_and_skipped(self) -> None:
        cross_family_yy = os.path.join(
            self.gm_dir,
            "objects",
            "snd_rejected",
            "snd_rejected.yy",
        )
        os.makedirs(os.path.dirname(cross_family_yy))
        with open(cross_family_yy, "w", encoding="utf-8") as yy_file:
            json.dump(MINIMAL_SOUND_YY, yy_file)
        self._write_yyp(
            [
                (
                    "snd_rejected",
                    "sounds/../objects/snd_rejected/snd_rejected.yy",
                )
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                skipped=1,
            ),
        )
        diagnostic_codes = {
            diagnostic.code for diagnostic in diagnostics.diagnostics()
        }
        self.assertIn("GM2GD-SOURCE-PATH-REJECTED", diagnostic_codes)
        self.assertIn("GM2GD-SOUND-SOURCE-UNAVAILABLE", diagnostic_codes)

    def test_rejects_cross_family_manifest_resource_after_normalization(
        self,
    ) -> None:
        cross_family_yy = os.path.join(
            self.gm_dir,
            "objects",
            "snd_cross_family",
            "snd_cross_family.yy",
        )
        os.makedirs(os.path.dirname(cross_family_yy))
        with open(cross_family_yy, "w", encoding="utf-8") as yy_file:
            json.dump(MINIMAL_SOUND_YY, yy_file)
        self._write_yyp(
            [
                (
                    "snd_cross_family",
                    "sounds/../objects/snd_cross_family/snd_cross_family.yy",
                )
            ]
        )
        diagnostics = DiagnosticCollector()

        sound_files = self._make_converter(diagnostics).find_sound_files()

        self.assertEqual(sound_files, [])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "SoundPaths.yyp")
        self.assertEqual(rejected[0].resource, "snd_cross_family")
        self.assertEqual(rejected[0].resource_type, "sound")
        self.assertEqual(rejected[0].manifest_entry, "resources[0].id.path")

    def test_accepts_owner_and_project_relative_sound_file_forms(self) -> None:
        references = {
            "snd_owner": "snd_owner.wav",
            "snd_project": "sounds/shared/snd_project.wav",
            "snd_placeholder": (
                "${project_dir}/sounds/shared/snd_placeholder.wav"
            ),
            "snd_backslash": r"sounds\shared\snd_backslash.wav",
        }
        shared_dir = os.path.join(self.gm_dir, "sounds", "shared")
        os.makedirs(shared_dir)
        yy_paths: dict[str, str] = {}
        expected_payloads: dict[str, bytes] = {}
        for index, (sound_name, sound_file) in enumerate(
            references.items(),
            start=1,
        ):
            yy_path = self._write_sound_yy(sound_name, sound_file)
            yy_paths[sound_name] = yy_path
            payload = bytes([index]) * 16
            expected_payloads[sound_name] = payload
            audio_path = (
                os.path.join(os.path.dirname(yy_path), sound_file)
                if sound_name == "snd_owner"
                else os.path.join(shared_dir, f"{sound_name}.wav")
            )
            with open(audio_path, "wb") as audio_file:
                audio_file.write(payload)

        converter = self._make_converter()
        self._write_yyp(
            [
                (sound_name, f"sounds/{sound_name}/{sound_name}.yy")
                for sound_name in references
            ]
        )
        converter.convert_all()

        for sound_name in yy_paths:
            with self.subTest(sound_name=sound_name):
                output_path = resource_filesystem_path(
                    self.godot_dir,
                    converter._sound_output_paths[sound_name],
                )
                with open(output_path, "rb") as output_file:
                    self.assertEqual(
                        output_file.read(),
                        expected_payloads[sound_name],
                    )

    def test_rejects_unsafe_sound_file_paths_with_owner_diagnostics(self) -> None:
        outside_path = os.path.join(self.outside_dir, "outside.wav")
        with open(outside_path, "wb") as outside_file:
            outside_file.write(b"outside project audio")

        traversal_directory = os.path.join(
            self.gm_dir,
            "sounds",
            "snd_traversal",
        )
        unsafe_paths = {
            "snd_traversal": os.path.relpath(
                outside_path,
                traversal_directory,
            ),
            "snd_absolute": outside_path,
            "snd_drive_absolute": r"C:\Games\Outside\sound.wav",
            "snd_drive_relative": r"C:Outside\sound.wav",
            "snd_unc": r"\\server\share\sound.wav",
            "snd_nul": "sound\0.wav",
            "snd_symlink": "linked.wav",
        }
        yy_paths = {
            sound_name: self._write_sound_yy(sound_name, sound_file)
            for sound_name, sound_file in unsafe_paths.items()
        }
        try:
            os.symlink(
                outside_path,
                os.path.join(
                    self.gm_dir,
                    "sounds",
                    "snd_symlink",
                    "linked.wav",
                ),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        for sound_name, yy_path in yy_paths.items():
            with self.subTest(sound_name=sound_name):
                result = converter._process_sound(yy_path)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result["success"])

        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), len(unsafe_paths), rejected)
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {
                f"sounds/{sound_name}/{sound_name}.yy"
                for sound_name in unsafe_paths
            },
        )
        self.assertTrue(
            all(diagnostic.resource_type == "sound" for diagnostic in rejected)
        )
        self.assertTrue(
            all(diagnostic.manifest_entry == "soundFile" for diagnostic in rejected)
        )
        self.assertFalse(
            any(
                files
                for _root, _directories, files in os.walk(self.godot_dir)
            )
        )

    def test_rejects_non_string_and_empty_sound_file_without_coercion(
        self,
    ) -> None:
        malformed_values: dict[str, object] = {
            "snd_number": 7,
            "snd_boolean": True,
            "snd_null": None,
            "snd_list": ["list.wav"],
            "snd_object": {"path": "object.wav"},
            "snd_empty": "",
        }
        yy_paths = {
            sound_name: self._write_sound_yy(sound_name, sound_file)
            for sound_name, sound_file in malformed_values.items()
        }
        for sound_name in ("snd_number", "snd_boolean", "snd_null"):
            coerced_name = str(malformed_values[sound_name])
            with open(
                os.path.join(os.path.dirname(yy_paths[sound_name]), coerced_name),
                "wb",
            ) as audio_file:
                audio_file.write(b"must not be copied")

        safe_yy = self._write_sound_yy("snd_safe", "snd_safe.wav")
        with open(
            os.path.join(os.path.dirname(safe_yy), "snd_safe.wav"),
            "wb",
        ) as safe_audio:
            safe_audio.write(b"safe sibling")
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        safe_output = resource_filesystem_path(
            self.godot_dir,
            converter._sound_output_paths["snd_safe"],
        )
        with open(safe_output, "rb") as safe_audio:
            self.assertEqual(safe_audio.read(), b"safe sibling")
        for sound_name in malformed_values:
            self.assertFalse(
                os.path.exists(os.path.join(self.godot_dir, "sounds", sound_name))
            )
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), len(malformed_values), rejected)
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            set(malformed_values),
        )
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {
                f"sounds/{sound_name}/{sound_name}.yy"
                for sound_name in malformed_values
            },
        )
        self.assertTrue(
            all(
                diagnostic.resource_type == "sound"
                and diagnostic.manifest_entry == "soundFile"
                for diagnostic in rejected
            )
        )

    def test_shared_pipeline_dedupes_identical_unsafe_sound_file_rejection(
        self,
    ) -> None:
        outside_audio = os.path.join(self.outside_dir, "outside.wav")
        with open(outside_audio, "wb") as audio_file:
            audio_file.write(b"outside")
        sound_name = "snd_shared_diagnostic"
        sound_directory = os.path.join(self.gm_dir, "sounds", sound_name)
        unsafe_reference = os.path.relpath(outside_audio, sound_directory)
        self._write_sound_yy(sound_name, unsafe_reference)
        diagnostics = DiagnosticCollector()
        rejection_logs: list[str] = []
        sound_converter = SoundConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=rejection_logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )

        sound_converter.convert_all()
        AssetRegistryConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=rejection_logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).build_entries()

        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        emitted_rejections = [
            message
            for message in rejection_logs
            if "Rejected GameMaker source path" in message
        ]
        self.assertEqual(len(emitted_rejections), 2, emitted_rejections)
        self.assertEqual(emitted_rejections[0], emitted_rejections[1])

    def test_disk_fallback_rejects_external_directory_and_keeps_safe_sibling(
        self,
    ) -> None:
        safe_yy = _make_sound_yy(self.gm_dir, "snd_safe")
        outside_sound_directory = os.path.join(
            self.outside_dir,
            "snd_directory_link",
        )
        os.makedirs(outside_sound_directory)
        with open(
            os.path.join(outside_sound_directory, "snd_directory_link.yy"),
            "w",
            encoding="utf-8",
        ) as yy_file:
            json.dump(MINIMAL_SOUND_YY, yy_file)
        try:
            os.symlink(
                outside_sound_directory,
                os.path.join(
                    self.gm_dir,
                    "sounds",
                    "snd_directory_link",
                ),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()

        sound_files = self._make_converter(diagnostics).find_sound_files()

        self.assertEqual(sound_files, [safe_yy])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "sounds")
        self.assertEqual(rejected[0].resource, "snd_directory_link")
        self.assertEqual(rejected[0].resource_type, "sound")
        self.assertEqual(
            rejected[0].manifest_entry,
            "discovered sound entry",
        )

    def test_rejects_manifest_sound_yy_path_outside_project(self) -> None:
        outside_yy = os.path.join(self.outside_dir, "snd_escape.yy")
        with open(outside_yy, "w", encoding="utf-8") as yy_file:
            json.dump(MINIMAL_SOUND_YY, yy_file)
        unsafe_path = os.path.relpath(outside_yy, self.gm_dir).replace(
            os.sep,
            "/",
        )
        self._write_yyp(
            [("snd_escape", f"sounds/../{unsafe_path}")]
        )
        diagnostics = DiagnosticCollector()

        sound_files = self._make_converter(diagnostics).find_sound_files()

        self.assertEqual(sound_files, [])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "SoundPaths.yyp")
        self.assertEqual(rejected[0].resource, "snd_escape")
        self.assertEqual(rejected[0].resource_type, "sound")
        self.assertEqual(rejected[0].manifest_entry, "resources[0].id.path")

    def test_rejects_disk_discovered_yy_symlink_to_outside_project(self) -> None:
        outside_yy = os.path.join(self.outside_dir, "snd_link.yy")
        with open(outside_yy, "w", encoding="utf-8") as yy_file:
            json.dump(MINIMAL_SOUND_YY, yy_file)
        sound_dir = os.path.join(self.gm_dir, "sounds", "snd_link")
        os.makedirs(sound_dir)
        linked_yy = os.path.join(sound_dir, "snd_link.yy")
        try:
            os.symlink(outside_yy, linked_yy)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        diagnostics = DiagnosticCollector()

        sound_files = self._make_converter(diagnostics).find_sound_files()

        self.assertEqual(sound_files, [])
        rejected = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "sounds/snd_link")
        self.assertEqual(rejected[0].resource, "snd_link")
        self.assertEqual(rejected[0].resource_type, "sound")
        self.assertEqual(rejected[0].manifest_entry, "discovered .yy")
        self.assertIn(linked_yy, rejected[0].message)


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


class TestSoundTypedMetadataBoundary(unittest.TestCase):
    """Preserve sound-specific coercion, source validation and reread policy."""

    def setUp(self) -> None:
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.gm_dir = os.path.join(workspace.name, "game")
        self.godot_dir = os.path.join(workspace.name, "godot")
        os.makedirs(self.gm_dir)
        os.makedirs(self.godot_dir)
        self.yy_path = _make_sound_yy(self.gm_dir, "snd_bound")
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()
        self.converter = SoundConverter(
            self.gm_dir, self.godot_dir,
            log_callback=self.logs.append, diagnostics=self.diagnostics,
        )

    def _write(self, data: JsonObject) -> None:
        self._write_text(json.dumps(data))

    def _write_text(self, text: str) -> None:
        with open(self.yy_path, "w", encoding="utf-8") as source_file:
            source_file.write(text)

    def _assert_parse_failure(self) -> None:
        self.assertIsNone(self.converter._parse_sound_yy(self.yy_path))
        self.assertEqual(self.logs, [
            get_localized("Console_Convertor_Sounds_ParseError").format(yy_path=self.yy_path)
        ])
        self.assertEqual(os.listdir(self.godot_dir), [])

    def test_original_sound_data_keys_and_missing_defaults(self) -> None:
        self._write({"name": "Sound", "soundFile": "clip.wav"})
        result = self.converter._parse_sound_yy(self.yy_path)
        self.assertEqual(result, {
            "name": "Sound", "soundFile": "clip.wav", "volume": 1.0,
            "type": 0, "bitDepth": 16, "bitRate": 128, "sampleRate": 44100,
            "compression": 0, "preload": True,
            "audioGroupId": "audiogroup_default", "duration": 0.0,
        })
        assert result is not None
        self.assertEqual(tuple(result), tuple(SoundData.__annotations__))
        self.assertEqual(SoundData.__module__, "src.conversion.sounds")
        self.assertEqual(self.logs, [])

    def test_conversion_retains_stringification_numeric_strings_and_truthiness(self) -> None:
        self._write({
            "name": [None, True, "Sound"], "soundFile": "clip.wav",
            "volume": " 1.25e1 ", "type": True, "bitDepth": 16.9,
            "bitRate": " 192 ", "sampleRate": "48000", "compression": False,
            "preload": "false", "audioGroupId": {"name": None}, "duration": "2.5",
        })
        self.assertEqual(self.converter._parse_sound_yy(self.yy_path), {
            "name": "[None, True, 'Sound']", "soundFile": "clip.wav", "volume": 12.5,
            "type": 1, "bitDepth": 16, "bitRate": 192, "sampleRate": 48000,
            "compression": 0, "preload": True, "audioGroupId": "None", "duration": 2.5,
        })

    def test_projection_is_authoritative_for_all_eleven_fields(self) -> None:
        view = SoundConversionFields(
            name="Projected sound", sound_file="projected.ogg", volume=0.5,
            sound_type=1, bit_depth=8, bit_rate=256, sample_rate=22050,
            compression=2, preload=False, audio_group="projected_group", duration=3.5,
        )
        with patch("src.conversion.sounds.project_sound_conversion_fields", return_value=view) as projection:
            result = self.converter._parse_sound_yy(self.yy_path)
        self.assertEqual(result, {
            "name": "Projected sound", "soundFile": "projected.ogg", "volume": 0.5,
            "type": 1, "bitDepth": 8, "bitRate": 256, "sampleRate": 22050,
            "compression": 2, "preload": False, "audioGroupId": "projected_group", "duration": 3.5,
        })
        projection.assert_called_once()
        self.assertEqual(projection.call_args.kwargs, {"sound_file": "snd_bound.wav"})
        self.assertEqual(os.listdir(self.godot_dir), [])

    def test_captured_sound_file_and_source_name_control_rejection(self) -> None:
        metadata = parse_gamemaker_sound_metadata(
            {"soundFile": False, "name": "Captured name"}, source_context="captured.yy"
        )
        metadata.raw_data.update({"soundFile": "different.wav", "name": "Different name"})
        with patch("src.conversion.sounds.parse_gamemaker_sound_metadata", return_value=metadata):
            with patch("src.conversion.sounds.project_sound_conversion_fields") as projection:
                self.assertIsNone(self.converter._parse_sound_yy(self.yy_path))
        projection.assert_not_called()
        rejected = self.diagnostics.diagnostics()
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].resource, "Captured name")
        self.assertIn("False", rejected[0].message)

    def test_sound_file_validation_precedes_required_name_and_numeric_projection(self) -> None:
        values: list[JsonValue] = [None, "", False, 7, [], {"clip": "invalid"}]
        for value in values:
            with self.subTest(value=value):
                self._write({"soundFile": value, "volume": "invalid", "audioGroupId": None})
                with patch("src.conversion.sounds.project_sound_conversion_fields") as projection:
                    self.assertIsNone(self.converter._parse_sound_yy(self.yy_path))
                projection.assert_not_called()
        rejected = self.diagnostics.diagnostics()
        self.assertEqual(len(rejected), len(values))
        self.assertTrue(all(item.code == "GM2GD-SOURCE-PATH-REJECTED" for item in rejected))
        self.assertTrue(all(item.resource == "snd_bound" for item in rejected))
        self.assertTrue(all(item.resource_type == "sound" for item in rejected))
        self.assertTrue(all(item.manifest_entry == "soundFile" for item in rejected))
        self.assertTrue(all(item.source_path == "sounds/snd_bound/snd_bound.yy" for item in rejected))
        self.assertEqual(os.listdir(self.godot_dir), [])

    def test_nonobject_malformed_and_invalid_numeric_inputs_keep_parse_log(self) -> None:
        sources = ["null", "[]", '"sound"', "true", "12", "{",
                   '{"soundFile":"clip.wav"}',
                   '{"name":"Sound","soundFile":"clip.wav","volume":null}',
                   '{"name":"Sound","soundFile":"clip.wav","type":[]}',
                   '{"name":"Sound","soundFile":"clip.wav","volume":"invalid"}']
        for source in sources:
            with self.subTest(source=source):
                self.logs.clear()
                self._write_text(source)
                self._assert_parse_failure()

    def test_rejected_deep_or_huge_sound_file_repr_failures_precede_projection(self) -> None:
        deep: JsonValue = []
        for _ in range(sys.getrecursionlimit() + 20):
            deep = [deep]
        limit = sys.get_int_max_str_digits()
        huge = 10 ** ((limit or 4300) + 1)
        for value in (deep, huge):
            with self.subTest(value_type=type(value).__name__):
                raw: JsonObject = {"soundFile": value, "volume": "invalid"}
                try:
                    repr(value)
                except (ValueError, RecursionError) as expected:
                    with patch("src.conversion.sounds.json.loads", return_value=raw):
                        with patch("src.conversion.sounds.project_sound_conversion_fields") as projection:
                            with self.assertRaises(type(expected)):
                                self.converter._parse_sound_yy(self.yy_path)
                    projection.assert_not_called()
                else:
                    with patch("src.conversion.sounds.json.loads", return_value=raw):
                        self.assertIsNone(self.converter._parse_sound_yy(self.yy_path))
        self.assertEqual(os.listdir(self.godot_dir), [])

    def test_rejection_keeps_separate_first_repr_and_error_message_repr(self) -> None:
        self._write({"soundFile": [], "volume": "invalid"})
        with patch("src.conversion.sounds.repr", return_value="first representation", create=True) as first_repr:
            with patch.object(self.converter, "_report_source_path_rejection") as report:
                self.assertIsNone(self.converter._parse_sound_yy(self.yy_path))
        first_repr.assert_called_once_with([])
        report.assert_called_once()
        self.assertEqual(report.call_args.args[0], "first representation")
        self.assertEqual(str(report.call_args.args[1]), "GameMaker soundFile must be a non-empty string: []")
        self.assertEqual(report.call_args.kwargs, {
            "owner_source_path": self.yy_path, "resource": "snd_bound",
            "resource_type": "sound", "field": "soundFile",
        })

    def test_shared_decoder_preserves_trailing_comma_rewrite(self) -> None:
        self._write_text('{"name":"Sound,}","soundFile":"clip.wav",}')
        result = self.converter._parse_sound_yy(self.yy_path)
        assert result is not None
        self.assertEqual(result["name"], "Sound}")
        self.assertEqual(result["soundFile"], "clip.wav")

    def test_audio_group_malformed_root_keeps_delayed_attribute_error(self) -> None:
        values: list[JsonValue] = [None, [], "group", 3, False, 1.5]
        for value in values:
            with self.subTest(value=value):
                self._write({"name": "Sound", "soundFile": "clip.wav", "audioGroupId": value,
                             "duration": "invalid"})
                with self.assertRaises(AttributeError) as raised:
                    self.converter._parse_sound_yy(self.yy_path)
                self.assertEqual(str(raised.exception), f"'{type(value).__name__}' object has no attribute 'get'")
                self.assertEqual(raised.exception.name, "get")
                self.assertEqual(raised.exception.obj, value)
        self.assertEqual(self.logs, [])

    def test_earlier_numeric_failure_is_caught_before_malformed_audio_group(self) -> None:
        self._write({"name": "Sound", "soundFile": "clip.wav", "volume": "invalid",
                     "audioGroupId": None, "duration": 10 ** 400})
        self._assert_parse_failure()

    def test_audio_group_nested_names_keep_legacy_string_values(self) -> None:
        cases: list[tuple[JsonValue, str]] = [
            ({}, "audiogroup_default"), ({"name": None}, "None"), ({"name": ""}, ""),
            ({"name": False}, "False"), ({"name": 3}, "3"), ({"name": []}, "[]"),
        ]
        for group, expected in cases:
            with self.subTest(group=group):
                self._write({"name": "Sound", "soundFile": "clip.wav", "audioGroupId": group})
                result = self.converter._parse_sound_yy(self.yy_path)
                assert result is not None
                self.assertEqual(result["audioGroupId"], expected)

    def test_numeric_overflow_and_nonfinite_policy_is_preserved(self) -> None:
        for fields in [{"volume": 10 ** 400}, {"type": float("inf")}, {"duration": 10 ** 400}]:
            with self.subTest(fields=fields):
                self._write({"name": "Sound", "soundFile": "clip.wav", **fields})
                with self.assertRaises(OverflowError):
                    self.converter._parse_sound_yy(self.yy_path)
        for field_name in ("volume", "duration"):
            for value in (float("nan"), float("inf"), -0.0):
                with self.subTest(field=field_name, value=value):
                    self._write({"name": "Sound", "soundFile": "clip.wav", field_name: value})
                    result = self.converter._parse_sound_yy(self.yy_path)
                    assert result is not None
                    actual = result["volume"] if field_name == "volume" else result["duration"]
                    if math.isnan(value):
                        self.assertTrue(math.isnan(actual))
                    else:
                        self.assertEqual(actual, value)
                        self.assertEqual(math.copysign(1, actual), math.copysign(1, value))
        self._write({"name": "Sound", "soundFile": "clip.wav", "type": float("nan")})
        self._assert_parse_failure()

    def test_acquisition_caught_errors_keep_original_parse_log(self) -> None:
        errors: list[Exception] = [OSError("read"), json.JSONDecodeError("decode", "{", 0),
                                  KeyError("field"), TypeError("root"), ValueError("limit"),
                                  UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.logs.clear()
                with patch("src.conversion.sounds.decode_gamemaker_json", side_effect=error):
                    self._assert_parse_failure()

    def test_projection_caught_errors_keep_original_parse_log(self) -> None:
        for error in [KeyError("name"), TypeError("numeric"), ValueError("numeric")]:
            with self.subTest(error=type(error).__name__):
                self.logs.clear()
                with patch("src.conversion.sounds.project_sound_conversion_fields", side_effect=error):
                    self._assert_parse_failure()

    def test_acquisition_and_projection_unhandled_errors_keep_identity(self) -> None:
        errors: list[BaseException] = [OverflowError("huge"), RecursionError("deep"),
                                       KeyboardInterrupt(), SystemExit(7)]
        for seam in ("decode_gamemaker_json", "project_sound_conversion_fields"):
            for error in errors:
                with self.subTest(seam=seam, error=type(error).__name__):
                    with patch("src.conversion.sounds." + seam, side_effect=error):
                        with self.assertRaises(type(error)) as raised:
                            self.converter._parse_sound_yy(self.yy_path)
                    self.assertIs(raised.exception, error)
        self.assertEqual(self.logs, [])

    def test_actual_utf8_and_integer_decoder_errors_are_caught(self) -> None:
        with open(self.yy_path, "wb") as source_file:
            source_file.write(b"\xff")
        self._assert_parse_failure()
        limit = sys.get_int_max_str_digits()
        if limit:
            self.logs.clear()
            self._write_text('{"name":"Sound","soundFile":"clip.wav","volume":' + "1" * (limit + 1) + '}')
            self._assert_parse_failure()

    def test_unknown_validated_graph_reaches_leaf_with_identity_and_order(self) -> None:
        nested: JsonValue = "terminal"
        for _ in range(1600):
            nested = {"next": nested}
        shared: JsonObject = {"z": None, "a": [True, 1]}
        raw: JsonObject = {"name": "Sound", "soundFile": "clip.wav", "unknown": nested,
                           "first": shared, "second": shared}
        with patch("src.conversion.sounds.json.loads", return_value=raw):
            with patch("src.conversion.sounds.parse_gamemaker_sound_metadata",
                       wraps=parse_gamemaker_sound_metadata) as capture:
                result = self.converter._parse_sound_yy(self.yy_path)
        assert result is not None
        self.assertEqual(result["name"], "Sound")
        self.assertIs(capture.call_args.args[0], raw)
        self.assertEqual(capture.call_args.kwargs, {"source_context": self.yy_path})
        self.assertIs(raw["first"], raw["second"])
        self.assertIs(raw["unknown"], nested)
        self.assertEqual(tuple(raw), ("name", "soundFile", "unknown", "first", "second"))

    def test_illegal_unknown_json_graph_is_caught_before_leaf(self) -> None:
        raw = {"name": "Sound", "soundFile": "clip.wav", "unknown": {1, 2}}
        with patch("src.conversion.sounds.json.loads", return_value=raw):
            with patch("src.conversion.sounds.parse_gamemaker_sound_metadata") as capture:
                self._assert_parse_failure()
        capture.assert_not_called()

    def test_sound_folder_preserves_literal_case_slashes_and_suffix_order(self) -> None:
        cases = [("folders/Sounds/UI.yy", "ui"),
                 ("folders/Sounds/Game/Abilities.yy", "game/abilities"),
                 ("Folders/Sounds/UI.yy", "sounds/ui"),
                 ("folders/Sounds/UI.YY", "ui_yy"),
                 ("folders/Sounds/Game\\Abilities.yy", "game/abilities"),
                 ("folders\\Sounds\\UI.yy", ""), ("folders/Sounds.yy", "")]
        for path, expected in cases:
            with self.subTest(path=path):
                self._write({"parent": {"path": path}})
                self.assertEqual(self.converter._get_subfolder_from_yy(self.yy_path), expected)

    def test_folder_rereads_replacement_without_coercing_unrelated_fields(self) -> None:
        self._write({"name": "Sound", "soundFile": "clip.wav",
                     "parent": {"path": "folders/Sounds/Old.yy"}})
        self.assertIsNotNone(self.converter._parse_sound_yy(self.yy_path))
        self._write({"soundFile": None, "volume": "invalid", "audioGroupId": None,
                     "parent": {"path": "folders/Sounds/New.yy"}})
        with patch("src.conversion.sounds.project_sound_conversion_fields") as projection:
            self.assertEqual(self.converter._get_subfolder_from_yy(self.yy_path), "new")
        projection.assert_not_called()
        os.unlink(self.yy_path)
        self.assertEqual(self.converter._get_subfolder_from_yy(self.yy_path), "")

    def test_folder_containment_rejection_precedes_open(self) -> None:
        outside = os.path.join(os.path.dirname(self.gm_dir), "outside.yy")
        with open(outside, "w", encoding="utf-8") as source_file:
            source_file.write('{"parent":{"path":"folders/Sounds/Unsafe.yy"}}')
        with patch("src.conversion.sounds.open", create=True) as source_open:
            self.assertEqual(self.converter._get_subfolder_from_yy(outside), "")
        source_open.assert_not_called()

    def test_folder_reader_and_extraction_retain_separate_catches(self) -> None:
        for error in [OSError("read"), KeyError("field"), TypeError("root"), ValueError("limit")]:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.sounds.decode_gamemaker_json", side_effect=error):
                    self.assertEqual(self.converter._get_subfolder_from_yy(self.yy_path), "")
        for error in [KeyError("field"), TypeError("field"), AttributeError("field")]:
            with self.subTest(error=type(error).__name__):
                with patch("src.conversion.sounds.parse_gamemaker_sound_metadata", side_effect=error):
                    self.assertEqual(self.converter._get_subfolder_from_yy(self.yy_path), "")
        error = ValueError("extraction")
        with patch("src.conversion.sounds.parse_gamemaker_sound_metadata", side_effect=error):
            with self.assertRaises(ValueError) as raised:
                self.converter._get_subfolder_from_yy(self.yy_path)
        self.assertIs(raised.exception, error)
        self.assertEqual(self.logs, [])

    def test_planned_output_path_wins_without_folder_reread(self) -> None:
        self.converter._sound_output_paths = {"snd_bound": "res://sounds/planned/clip.wav"}
        with patch.object(self.converter, "_get_subfolder_from_yy", side_effect=AssertionError("fallback")):
            result = self.converter._process_sound(self.yy_path)
        self.assertEqual(result, {"success": True, "name": "snd_bound", "audio_group": "audiogroup_default"})
        destination = os.path.join(self.godot_dir, "sounds", "planned", "clip.wav")
        with open(destination, "rb") as copied:
            self.assertEqual(copied.read(), b"\x00" * 64)
        with open(destination + ".import", encoding="utf-8") as imported:
            self.assertIn('source_file="res://sounds/planned/clip.wav"', imported.read())

if __name__ == "__main__":
    unittest.main()
