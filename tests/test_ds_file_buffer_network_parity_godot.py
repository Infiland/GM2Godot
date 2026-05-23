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


class TestDSFileBufferNetworkParityGodotSmoke(unittest.TestCase):
    def test_ds_file_buffer_network_parity_slice(self) -> None:
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
            \tvar list = GMRuntime.gml_ds_list_create()
            \tvar map = GMRuntime.gml_ds_map_create()
            \tif not _check(GMRuntime.gml_ds_exists(list, 2), "ds_exists did not accept list"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_ds_exists(list, 1), "ds_exists accepted wrong DS type"):
            \t\treturn
            \tGMRuntime.gml_ds_list_add(list, ["nested"])
            \tGMRuntime.gml_ds_map_add_list(map, "items", list)
            \tvar restored_map = GMRuntime.gml_ds_map_create()
            \tGMRuntime.gml_ds_map_read(restored_map, GMRuntime.gml_ds_map_write(map))
            \tif not _check(GMRuntime.gml_ds_map_is_list(restored_map, "items"), "map nested list mark failed"):
            \t\treturn
            \tvar restored_list = GMRuntime.gml_ds_map_find_value(restored_map, "items")
            \tif not _check(GMRuntime.gml_ds_exists(restored_list, 2), "restored nested list handle missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ds_list_find_value(restored_list, 0) == "nested", "restored nested list value failed"):
            \t\treturn
            \tGMRuntime.gml_ds_list_destroy(list)
            \tif not _check(not GMRuntime.gml_ds_exists(list, 2), "destroyed list still exists"):
            \t\treturn

            \tvar marked_map = GMRuntime.gml_ds_map_create()
            \tGMRuntime.gml_ds_map_set(marked_map, "kind", "marked")
            \tvar outer_list = GMRuntime.gml_ds_list_create()
            \tGMRuntime.gml_ds_list_add(outer_list, [marked_map])
            \tGMRuntime.gml_ds_list_mark_as_map(outer_list, 0)
            \tvar restored_outer = GMRuntime.gml_ds_list_create()
            \tGMRuntime.gml_ds_list_read(restored_outer, GMRuntime.gml_ds_list_write(outer_list))
            \tif not _check(GMRuntime.gml_ds_list_is_map(restored_outer, 0), "list nested map mark failed"):
            \t\treturn
            \tvar restored_marked_map = GMRuntime.gml_ds_list_find_value(restored_outer, 0)
            \tif not _check(GMRuntime.gml_ds_map_find_value(restored_marked_map, "kind") == "marked", "list nested map value failed"):
            \t\treturn

            \tvar bin = GMRuntime.gml_file_bin_open("save/parity.bin", 1)
            \tGMRuntime.gml_file_bin_write_byte(bin, 65)
            \tGMRuntime.gml_file_bin_write_byte(bin, 66)
            \tGMRuntime.gml_file_bin_write_byte(bin, 67)
            \tif not _check(GMRuntime.gml_file_bin_position(bin) == 3, "binary position after write failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_bin_size(bin) == 3, "binary size after write failed"):
            \t\treturn
            \tGMRuntime.gml_file_bin_close(bin)
            \tbin = GMRuntime.gml_file_bin_open("save/parity.bin", 2)
            \tGMRuntime.gml_file_bin_seek(bin, 1)
            \tif not _check(GMRuntime.gml_file_bin_read_byte(bin) == 66, "binary read byte failed"):
            \t\treturn
            \tGMRuntime.gml_file_bin_rewrite(bin)
            \tGMRuntime.gml_file_bin_write_byte(bin, 90)
            \tif not _check(GMRuntime.gml_file_bin_size(bin) == 1, "binary rewrite size failed"):
            \t\treturn
            \tGMRuntime.gml_file_bin_close(bin)

            \tif not _check(GMRuntime.gml_buffer_sizeof(3) == 2 and GMRuntime.gml_buffer_sizeof(8) == 8, "buffer_sizeof failed"):
            \t\treturn
            \tvar bytes = GMRuntime.gml_buffer_create(4, 1, 1)
            \tGMRuntime.gml_buffer_write(bytes, 1, 10)
            \tGMRuntime.gml_buffer_write(bytes, 1, 20)
            \tGMRuntime.gml_buffer_write(bytes, 1, 30)
            \tGMRuntime.gml_buffer_write(bytes, 1, 40)
            \tif not _check(GMRuntime.gml_buffer_save_ext(bytes, "save/partial.bin", 1, 2), "buffer_save_ext failed"):
            \t\treturn
            \tvar loaded = GMRuntime.gml_buffer_create(2, 1, 1)
            \tGMRuntime.gml_buffer_load_ext(loaded, "save/partial.bin", 0)
            \tif not _check(GMRuntime.gml_buffer_peek(loaded, 0, 1) == 20 and GMRuntime.gml_buffer_peek(loaded, 1, 1) == 30, "buffer_load_ext values failed"):
            \t\treturn

            \tvar text = GMRuntime.gml_buffer_create(1, 1, 1)
            \tGMRuntime.gml_buffer_write(text, 11, "compressible-payload")
            \tvar compressed = GMRuntime.gml_buffer_compress(text, 0, GMRuntime.gml_buffer_get_used_size(text))
            \tif not _check(GMRuntime.gml_buffer_exists(compressed), "buffer_compress returned invalid handle"):
            \t\treturn
            \tvar decompressed = GMRuntime.gml_buffer_decompress(compressed)
            \tif not _check(GMRuntime.gml_buffer_exists(decompressed), "buffer_decompress returned invalid handle"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(decompressed, 0, 11) == "compressible-payload", "buffer_decompress payload failed"):
            \t\treturn

            \tvar tcp = GMRuntime.gml_network_create_socket(0)
            \tif not _check(GMRuntime.gml_network_send_broadcast(tcp, 6502, bytes, 2) == -1, "broadcast accepted non-UDP socket"):
            \t\treturn
            \tGMRuntime.gml_network_destroy(tcp)

            \tprint("DS_FILE_BUFFER_NETWORK_PARITY_OK")
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
        self.assertIn("DS_FILE_BUFFER_NETWORK_PARITY_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
