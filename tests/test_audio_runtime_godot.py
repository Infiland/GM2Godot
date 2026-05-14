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
        \tGMRuntime.gml_audio_stop_sound(first)
        \tif not _check(not GMRuntime.gml_handle_is_valid(first), "stopped handle remained valid"):
        \t\treturn
        \tif not _check(GMRuntime.gml_audio_is_playing(sound_id), "stopping one handle stopped all instances"):
        \t\treturn
        \tGMRuntime.gml_audio_stop_sound(sound_id)
        \tif not _check(not GMRuntime.gml_audio_is_playing(sound_id), "asset stop did not stop all instances"):
        \t\treturn
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
