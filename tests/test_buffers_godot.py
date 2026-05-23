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


class TestBuffersGodotSmoke(unittest.TestCase):
    def test_buffer_cursor_alignment_save_load_base64_and_hashes(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tvar buf = GMRuntime.gml_buffer_create(2, 1, 4)
            \tif not _check(GMRuntime.gml_buffer_exists(buf), "buffer should exist"):
            \t\treturn
            \tGMRuntime.gml_buffer_write(buf, 1, 7)
            \tif not _check(GMRuntime.gml_buffer_tell(buf) == 4, "u8 write did not align cursor to 4"):
            \t\treturn
            \tGMRuntime.gml_buffer_write(buf, 4, -2)
            \tif not _check(GMRuntime.gml_buffer_tell(buf) == 8, "s16 write did not align cursor to 8"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_used_size(buf) == 6, "used size mismatch after aligned writes"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_size(buf) >= 6, "buffer did not grow"):
            \t\treturn

            \tGMRuntime.gml_buffer_seek(buf, 0, 0)
            \tif not _check(GMRuntime.gml_buffer_read(buf, 1) == 7, "read u8 mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_tell(buf) == 4, "read u8 cursor alignment mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_read(buf, 4) == -2, "read s16 mismatch"):
            \t\treturn

            \tGMRuntime.gml_buffer_poke(buf, 1, 1, 9)
            \tif not _check(GMRuntime.gml_buffer_peek(buf, 1, 1) == 9, "peek/poke mismatch"):
            \t\treturn
            \tGMRuntime.gml_buffer_fill(buf, 8, 1, 65, 3)
            \tif not _check(GMRuntime.gml_buffer_get_used_size(buf) == 11, "fill used size mismatch"):
            \t\treturn

            \tvar copied = GMRuntime.gml_buffer_create(1, 1, 1)
            \tGMRuntime.gml_buffer_copy(buf, 8, 3, copied, 0)
            \tif not _check(GMRuntime.gml_buffer_peek(copied, 0, 11) == "AAA", "copy/text mismatch"):
            \t\treturn

            \tif not _check(GMRuntime.gml_buffer_save(buf, "save/buffer.bin"), "buffer_save failed"):
            \t\treturn
            \tvar loaded = GMRuntime.gml_buffer_load("save/buffer.bin")
            \tif not _check(GMRuntime.gml_buffer_exists(loaded), "buffer_load did not return buffer"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_used_size(loaded) == GMRuntime.gml_buffer_get_used_size(buf), "loaded used size mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(loaded, 1, 1) == 9, "loaded byte mismatch"):
            \t\treturn

            \tvar text = GMRuntime.gml_buffer_create(3, 1, 1)
            \tGMRuntime.gml_buffer_write(text, 11, "abc")
            \tif not _check(GMRuntime.gml_buffer_base64_encode(text, 0, 3) == "YWJj", "base64 encode mismatch"):
            \t\treturn
            \tvar decoded = GMRuntime.gml_buffer_base64_decode("YWJj")
            \tif not _check(GMRuntime.gml_buffer_peek(decoded, 0, 11) == "abc", "base64 decode mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_md5(text, 0, 3) == "900150983cd24fb0d6963f7d28e17f72", "md5 mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_sha1(text, 0, 3) == "a9993e364706816aba3e25717850c26c9cd0d89d", "sha1 mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_sha256(text, 0, 3) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "sha256 mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_crc32(text, 0, 3) == 891568578, "crc32 mismatch"):
            \t\treturn

            \tvar async_id = GMRuntime.gml_buffer_save_async(text, "save/async_buffer.bin")
            \tvar async_log = GMRuntime.gml_async_event_log()
            \tvar async_load = async_log[async_log.size() - 1]["payload"]
            \tif not _check(async_load["id"] == async_id and async_load["status"] == 0, "buffer_save_async payload mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("async_load").is_empty(), "async_load leaked after buffer_save_async"):
            \t\treturn
            \tvar load_async_id = GMRuntime.gml_buffer_load_async("save/async_buffer.bin")
            \tasync_log = GMRuntime.gml_async_event_log()
            \tasync_load = async_log[async_log.size() - 1]["payload"]
            \tif not _check(async_load["id"] == load_async_id and async_load["status"] == 0, "buffer_load_async payload mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(async_load["buffer"], 0, 11) == "abc", "buffer_load_async buffer mismatch"):
            \t\treturn

            \tGMRuntime.gml_buffer_delete(buf)
            \tif not _check(not GMRuntime.gml_buffer_exists(buf), "buffer_delete did not invalidate handle"):
            \t\treturn

            \tprint("BUFFERS_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("BUFFERS_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
