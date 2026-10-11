"""Godot checks for GameMaker audio gain fades, gain ranges and seamless loops."""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)

_SMOKE_SCRIPT = textwrap.dedent(
    """\
    extends Node

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    var _failures = []

    func _expect_near(label, actual, expected, tolerance = 0.001):
    \tif abs(float(actual) - float(expected)) > tolerance:
    \t\t_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])

    func _expect(label, condition):
    \tif not condition:
    \t\t_failures.append(label)

    func _wait_ms(milliseconds):
    \tvar deadline = Time.get_ticks_msec() + milliseconds
    \twhile Time.get_ticks_msec() < deadline:
    \t\tawait get_tree().process_frame
    \tawait get_tree().process_frame

    func _wav_stream():
    \tvar stream = AudioStreamWAV.new()
    \tstream.format = AudioStreamWAV.FORMAT_16_BITS
    \tstream.mix_rate = 8000
    \tvar data = PackedByteArray()
    \tdata.resize(8000 * 2)
    \tstream.data = data
    \treturn stream

    func _ready():
    \tvar music = _wav_stream()
    \tGMRuntime.gml_asset_registry_set([
    \t\t{
    \t\t\t"id": 100,
    \t\t\t"name": "snd_engine",
    \t\t\t"kind": "sounds",
    \t\t\t"type": "sound",
    \t\t\t"type_name": "Sound",
    \t\t\t"source_path": "sounds/snd_engine/snd_engine.yy",
    \t\t\t"godot_path": "",
    \t\t\t"legacy_id": "sounds/snd_engine/snd_engine.yy",
    \t\t\t"tags": [],
    \t\t\t"dynamic": false,
    \t\t\t"metadata": {"audio_group": "audiogroup_default", "volume": 0.5},
    \t\t\t"resource": music,
    \t\t}
    \t])
    \tcall_deferred("_run")

    func _run():
    \tvar sound_id = GMRuntime.gml_asset_get_index("snd_engine")
    \t_expect_near(".yy volume is the initial asset gain", GMRuntime.gml_audio_sound_get_gain(sound_id), 0.5)
    \tvar voice = GMRuntime.gml_audio_play_sound(sound_id, 0, true)
    \tvar player = GMRuntime.gml_handle_resolve(voice)
    \t_expect("looping play uses a looping stream", player.stream.loop_mode == AudioStreamWAV.LOOP_FORWARD)
    \t_expect("looping stream covers the whole sound", player.stream.loop_end == 8000 and player.stream.loop_begin == 0)
    \t_expect_near("initial player volume", player.volume_linear, 0.5)
    \tvar one_shot = GMRuntime.gml_audio_play_sound(sound_id, 0, false)
    \tvar one_shot_player = GMRuntime.gml_handle_resolve(one_shot)
    \t_expect("one-shot play keeps the plain stream", one_shot_player.stream.loop_mode == AudioStreamWAV.LOOP_DISABLED)
    \tGMRuntime.gml_audio_stop_sound(one_shot)

    \tGMRuntime.gml_audio_sound_gain(sound_id, 0.0, 400)
    \t_expect_near("asset fade starts from the current gain", GMRuntime.gml_audio_sound_get_gain(sound_id), 0.5)
    \tawait _wait_ms(200)
    \tvar halfway = GMRuntime.gml_audio_sound_get_gain(sound_id)
    \t_expect("asset gain is part way through the fade (%s)" % str(halfway), halfway > 0.05 and halfway < 0.45)
    \t_expect_near("asset fade reaches the player", player.volume_linear, halfway, 0.05)
    \tawait _wait_ms(300)
    \t_expect_near("asset fade completes", GMRuntime.gml_audio_sound_get_gain(sound_id), 0.0)
    \t_expect_near("completed fade silences the player", player.volume_linear, 0.0)

    \tGMRuntime.gml_audio_sound_gain(sound_id, 1.0, 0)
    \t_expect_near("time 0 sets the asset gain at once", GMRuntime.gml_audio_sound_get_gain(sound_id), 1.0)
    \t_expect_near("time 0 updates the player at once", player.volume_linear, 1.0)

    \tGMRuntime.gml_audio_sound_gain(voice, 2.0, 100)
    \tawait _wait_ms(250)
    \t_expect_near("instance gain may exceed 1", GMRuntime.gml_audio_sound_get_gain(voice), 2.0)
    \t_expect_near("instance gain multiplies the asset gain", player.volume_linear, 2.0)
    \t_expect_near("instance fade leaves the asset gain alone", GMRuntime.gml_audio_sound_get_gain(sound_id), 1.0)

    \tGMRuntime.gml_audio_sound_gain(voice, -3, 0)
    \t_expect_near("negative gain clamps to 0", GMRuntime.gml_audio_sound_get_gain(voice), 0.0)
    \tGMRuntime.gml_audio_sound_gain(voice, INF, 0)
    \t_expect("infinite gain keeps the player volume finite", is_finite(player.volume_linear) and player.volume_linear > 1.0)
    \tGMRuntime.gml_audio_sound_gain(voice, 1, 0)

    \tGMRuntime.gml_audio_group_set_gain("audiogroup_default", 0.25, 100)
    \tawait _wait_ms(250)
    \t_expect_near("group fade completes", GMRuntime.gml_audio_group_get_gain("audiogroup_default"), 0.25)
    \t_expect_near("group gain reaches the player", player.volume_linear, 0.25)
    \tGMRuntime.gml_audio_group_set_gain("audiogroup_default", 1, 0)

    \tGMRuntime.gml_audio_sound_loop(voice, false)
    \t_expect("audio_sound_loop(false) swaps to the plain stream", player.stream.loop_mode == AudioStreamWAV.LOOP_DISABLED)

    \t# audio_sound_loop only changes the voice's loop flag: a paused voice
    \t# stays paused where it was, and a sound asset index does nothing.
    \tvar paused_voice = GMRuntime.gml_audio_play_sound(sound_id, 0, true)
    \tvar paused_player = GMRuntime.gml_handle_resolve(paused_voice)
    \tawait _wait_ms(300)
    \tGMRuntime.gml_audio_pause_sound(paused_voice)
    \tvar paused_at = paused_player.get_playback_position()
    \t_expect("the voice played before the pause (%s)" % str(paused_at), paused_at > 0.1)
    \tGMRuntime.gml_audio_sound_loop(paused_voice, false)
    \t_expect("audio_sound_loop leaves a paused voice paused", GMRuntime.gml_audio_is_paused(paused_voice))
    \t_expect("audio_sound_loop sets the paused voice's loop flag", not GMRuntime.gml_audio_sound_get_loop(paused_voice))
    \t_expect("the paused voice's player stays paused", paused_player.stream_paused)
    \t_expect_near("the paused voice keeps its position", paused_player.get_playback_position(), paused_at, 0.05)
    \tGMRuntime.gml_audio_resume_sound(paused_voice)
    \t_expect("the voice resumes after audio_sound_loop", paused_player.playing and not paused_player.stream_paused)
    \t_expect_near("the voice resumes where it was paused", paused_player.get_playback_position(), paused_at, 0.05)
    \tGMRuntime.gml_audio_sound_loop(paused_voice, true)
    \tGMRuntime.gml_audio_sound_loop(sound_id, false)
    \t_expect("audio_sound_loop on a sound asset leaves its voices alone", GMRuntime.gml_audio_sound_get_loop(paused_voice))
    \t_expect("audio_sound_get_loop of a sound asset is false", not GMRuntime.gml_audio_sound_get_loop(sound_id))
    \tGMRuntime.gml_audio_stop_all()
    \t_expect("stop_all stops every voice", not GMRuntime.gml_audio_is_playing(sound_id))

    \tif _failures.is_empty():
    \t\tprint("AUDIO_GAIN_FADES_OK")
    \t\tget_tree().quit(0)
    \t\treturn
    \tfor failure in _failures:
    \t\tprint("FAIL " + failure)
    \tget_tree().quit(1)
    """
)

_SMOKE_SCENE = textwrap.dedent(
    """\
    [gd_scene load_steps=2 format=3]

    [ext_resource type="Script" path="res://smoke.gd" id="1"]

    [node name="Smoke" type="Node"]
    script = ExtResource("1")
    """
)


class TestAudioGainFadesGodot(unittest.TestCase):
    def test_gain_fades_ranges_and_loops_follow_gamemaker(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="AudioFades"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", _SMOKE_SCRIPT)
            _write_text(project_dir / "smoke.tscn", _SMOKE_SCENE)

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "--scene", "res://smoke.tscn"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("AUDIO_GAIN_FADES_OK", output)
        self.assertNotIn("SCRIPT ERROR", output)


if __name__ == "__main__":
    unittest.main()
