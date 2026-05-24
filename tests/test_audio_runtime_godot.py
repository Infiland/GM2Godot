from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_smoke_scene(project_dir: Path) -> None:
    smoke_script = textwrap.dedent(
        """\
        extends Node

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _ready():
        \tif AudioServer.get_bus_index("audiogroup_music") == -1:
        \t\tAudioServer.add_bus()
        \t\tAudioServer.set_bus_name(AudioServer.get_bus_count() - 1, "audiogroup_music")
        \tvar stream = AudioStreamGenerator.new()
        \tstream.mix_rate = 44100.0
        \tstream.buffer_length = 0.25
        \tGMRuntime.gml_asset_registry_set([
        \t\t{
        \t\t\t"id": 100,
        \t\t\t"name": "snd_hit",
        \t\t\t"kind": "sounds",
        \t\t\t"type": "sound",
        \t\t\t"type_name": "Sound",
        \t\t\t"source_path": "sounds/snd_hit/snd_hit.yy",
        \t\t\t"godot_path": "",
        \t\t\t"legacy_id": "sounds/snd_hit/snd_hit.yy",
        \t\t\t"tags": [],
        \t\t\t"dynamic": false,
        \t\t\t"metadata": {"audio_group": "audiogroup_music", "volume": 0.5},
        \t\t\t"resource": stream,
        \t\t}
        \t])
        \tvar sound_id = GMRuntime.gml_asset_get_index("snd_hit")
        \tvar first = GMRuntime.gml_audio_play_sound(sound_id, 10, false, 0.5, 0, 2.0)
        \tvar second = GMRuntime.gml_audio_play_sound(sound_id, 1, false)
        \tif not _check(GMRuntime.gml_handle_is_valid(first), "first sound handle invalid"):
        \t\treturn
        \tif not _check(GMRuntime.gml_handle_is_valid(second), "second sound handle invalid"):
        \t\treturn
        \tif not _check(first.index != second.index, "sound handles were not distinct"):
        \t\treturn
        \tvar first_player = GMRuntime.gml_handle_resolve(first)
        \tif not _check(first_player is AudioStreamPlayer, "first handle did not resolve to AudioStreamPlayer"):
        \t\treturn
        \tif not _check(first_player.bus == "audiogroup_music", "audio group did not map to sound bus"):
        \t\treturn
        \tif not _check(abs(first_player.volume_linear - 0.25) <= 0.001, "initial gain did not combine asset and instance gain"):
        \t\treturn
        \tif not _check(abs(first_player.pitch_scale - 2.0) <= 0.001, "initial pitch was not applied"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_is_playing(sound_id), "asset did not report playing"):
        \t\treturn
        \tGMRuntime.gml_audio_pause_sound(first)
        \tif not _check(GMRuntime.gml_audio_is_playing(first), "paused sound should still count as playing"):
        \t\treturn
        \tGMRuntime.gml_audio_resume_sound(first)
        \tGMRuntime.gml_audio_sound_gain(first, 0.2, 0)
        \tif not _check(abs(first_player.volume_linear - 0.1) <= 0.001, "instance gain update failed"):
        \t\treturn
        \tGMRuntime.gml_audio_sound_pitch(first, 0.75)
        \tif not _check(abs(first_player.pitch_scale - 0.75) <= 0.001, "instance pitch update failed"):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_audio_sound_get_gain(first) - 0.2) <= 0.001, "instance gain getter failed"):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_audio_sound_get_pitch(first) - 0.75) <= 0.001, "instance pitch getter failed"):
        \t\treturn
        \tGMRuntime.gml_audio_sound_loop(first, true)
        \tif not _check(GMRuntime.gml_audio_sound_get_loop(first), "sound loop getter failed"):
        \t\treturn
        \tGMRuntime.gml_audio_sound_set_listener_mask(first, 4)
        \tif not _check(GMRuntime.gml_audio_sound_get_listener_mask(first) == 4, "sound listener mask getter failed"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_sound_get_asset(first) == sound_id, "sound asset getter failed"):
        \t\treturn
        \tGMRuntime.gml_audio_set_master_gain(0.5)
        \tif not _check(abs(GMRuntime.gml_audio_get_master_gain() - 0.5) <= 0.001, "master gain getter failed"):
        \t\treturn
        \tGMRuntime.gml_audio_set_master_gain(1.0)
        \tvar spatial = GMRuntime.gml_audio_play_sound_at(sound_id, 12, 34, 0, 64, 512, 1, false, 4, 0.75)
        \tvar spatial_player = GMRuntime.gml_handle_resolve(spatial)
        \tif not _check(spatial_player is AudioStreamPlayer2D, "positional sound did not use AudioStreamPlayer2D"):
        \t\treturn
        \tif not _check(spatial_player.position == Vector2(12, 34), "positional sound coordinates were not applied"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(spatial)
        \tvar emitter = GMRuntime.gml_audio_emitter_create()
        \tif not _check(GMRuntime.gml_audio_emitter_exists(emitter), "emitter was not created"):
        \t\treturn
        \tGMRuntime.gml_audio_emitter_position(emitter, 21, 43, 0)
        \tGMRuntime.gml_audio_emitter_gain(emitter, 0.5)
        \tGMRuntime.gml_audio_emitter_pitch(emitter, 1.25)
        \tvar attached = GMRuntime.gml_audio_play_sound_on(emitter, sound_id, false, 4)
        \tvar attached_player = GMRuntime.gml_handle_resolve(attached)
        \tif not _check(attached_player is AudioStreamPlayer2D, "emitter sound did not use AudioStreamPlayer2D"):
        \t\treturn
        \tif not _check(abs(attached_player.volume_linear - 0.25) <= 0.001, "emitter gain was not applied"):
        \t\treturn
        \tif not _check(abs(attached_player.pitch_scale - 1.25) <= 0.001, "emitter pitch was not applied"):
        \t\treturn
        \tGMRuntime.gml_audio_emitter_position(emitter, 55, 66, 0)
        \tif not _check(attached_player.position == Vector2(55, 66), "emitter position did not update active player"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_emitter_get_x(emitter) == 55 and GMRuntime.gml_audio_emitter_get_y(emitter) == 66, "emitter position getters failed"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(attached)
        \tif not _check(GMRuntime.gml_audio_emitter_free(emitter), "emitter did not free"):
        \t\treturn
        \tGMRuntime.gml_async_event_log_clear()
        \tvar queue = GMRuntime.gml_audio_create_play_queue(1, 44100, 2)
        \tif not _check(GMRuntime.gml_audio_queue_sound(queue, 77, 0, 128), "queue sound failed"):
        \t\treturn
        \tvar playback_log = GMRuntime.gml_async_event_log()
        \tif not _check(playback_log.size() > 0 and playback_log[playback_log.size() - 1]["kind"] == "audio_playback", "audio queue did not dispatch playback async"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_free_play_queue(queue), "queue did not free"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_get_recorder_count() == 0, "recorder count should be deterministic zero"):
        \t\treturn
        \tGMRuntime.gml_async_event_log_clear()
        \tif not _check(GMRuntime.gml_audio_start_recording(0) == -1, "recording fallback should fail deterministically"):
        \t\treturn
        \tvar recording_log = GMRuntime.gml_async_event_log()
        \tif not _check(recording_log.size() > 0 and recording_log[recording_log.size() - 1]["kind"] == "audio_recording", "recording fallback did not dispatch async"):
        \t\treturn
        \tvar sync_group = GMRuntime.gml_audio_create_sync_group(false)
        \tif not _check(GMRuntime.gml_audio_play_in_sync_group(sync_group, sound_id) == 0, "sync group did not accept sound"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_start_sync_group(sync_group), "sync group did not start"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_sync_group_is_playing(sync_group), "sync group did not report playing"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_destroy_sync_group(sync_group), "sync group did not destroy"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(first)
        \tif not _check(not GMRuntime.gml_handle_is_valid(first), "stopped handle remained valid"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_is_playing(sound_id), "stopping one handle stopped all instances"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(sound_id)
        \tif not _check(not GMRuntime.gml_audio_is_playing(sound_id), "asset stop did not stop all instances"):
        \t\treturn
        \tGMRuntime.gml_audio_channel_num(1)
        \tvar low_priority = GMRuntime.gml_audio_play_sound(sound_id, 0, false)
        \tvar high_priority = GMRuntime.gml_audio_play_sound(sound_id, 100, false)
        \tif not _check(not GMRuntime.gml_handle_is_valid(low_priority), "channel limit did not evict lower priority handle"):
        \t\treturn
        \tif not _check(GMRuntime.gml_handle_is_valid(high_priority), "channel limit evicted higher priority handle"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(high_priority)
        \tGMRuntime.gml_audio_channel_num(128)
        \tvar alias_handle = GMRuntime.gml_sound_play(sound_id)
        \tif not _check(GMRuntime.gml_handle_is_valid(alias_handle), "legacy sound_play alias did not return a handle"):
        \t\treturn
        \tGMRuntime.gml_sound_stop(sound_id)
        \tif not _check(not GMRuntime.gml_sound_isplaying(sound_id), "legacy stop/isplaying aliases failed"):
        \t\treturn
        \tprint("AUDIO_RUNTIME_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestAudioRuntimeGodotSmoke(unittest.TestCase):
    def test_audio_runtime_handles_assets_and_legacy_aliases(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="AudioSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_smoke_scene(project_dir)

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--log-file",
                    str(project_dir / "godot.log"),
                    "--path",
                    str(project_dir),
                    "--scene",
                    "res://smoke.tscn",
                    "--quit-after",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("AUDIO_RUNTIME_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
