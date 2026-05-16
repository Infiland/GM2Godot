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


class TestFilesIniJsonGodotSmoke(unittest.TestCase):
    def test_files_ini_json_and_path_mapping(self) -> None:
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
            \tif not _check(GMRuntime.gml_builtin_global("working_directory").begins_with("user://"), "working_directory not user path"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("program_directory") == "res://", "program_directory mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("temp_directory").begins_with("user://"), "temp_directory not user path"):
            \t\treturn

            \tGMRuntime.gml_file_delete("config/default.txt")
            \tif not _check(GMRuntime.gml_file_exists("config/default.txt"), "included file not found"):
            \t\treturn
            \tvar included = GMRuntime.gml_file_text_open_read("config/default.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(included) == "included", "included text mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_read_real(included) == 42, "included real mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_eof(included), "included EOF mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(included)

            \tif not _check(GMRuntime.gml_filename_name("save/profile.txt") == "profile", "filename_name mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_ext("save/profile.txt") == ".txt", "filename_ext mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_dir("save/profile.txt") == "save", "filename_dir mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_path("save/profile.txt") == "save/", "filename_path mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_change_ext("save/profile.txt", "dat") == "save/profile.dat", "filename_change_ext mismatch"):
            \t\treturn

            \tif not _check(GMRuntime.gml_directory_create("save/nested"), "directory_create failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_exists("save/nested"), "directory_exists failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_destroy("save/nested"), "directory_destroy failed"):
            \t\treturn

            \tvar writer = GMRuntime.gml_file_text_open_write("save/profile.txt")
            \tGMRuntime.gml_file_text_write_string(writer, "Player")
            \tGMRuntime.gml_file_text_writeln(writer)
            \tGMRuntime.gml_file_text_write_real(writer, 12.5)
            \tGMRuntime.gml_file_text_close(writer)
            \tif not _check(GMRuntime.gml_file_exists("save/profile.txt"), "written file not found"):
            \t\treturn
            \tvar reader = GMRuntime.gml_file_text_open_read("save/profile.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(reader) == "Player", "written string mismatch"):
            \t\treturn
            \tif not _check(abs(GMRuntime.gml_file_text_read_real(reader) - 12.5) < 0.0001, "written real mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(reader)
            \tif not _check(GMRuntime.gml_file_delete("save/profile.txt"), "file_delete failed"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("save/profile.txt"), "deleted file still exists"):
            \t\treturn

            \tGMRuntime.gml_ini_open("save/settings.ini")
            \tGMRuntime.gml_ini_write_string("audio", "device", "headphones")
            \tGMRuntime.gml_ini_write_real("audio", "volume", 0.75)
            \tif not _check(GMRuntime.gml_ini_section_exists("audio"), "ini section missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ini_key_exists("audio", "volume"), "ini key missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ini_read_string("audio", "device", "default") == "headphones", "ini string mismatch"):
            \t\treturn
            \tif not _check(abs(GMRuntime.gml_ini_read_real("audio", "volume", 1.0) - 0.75) < 0.0001, "ini real mismatch"):
            \t\treturn
            \tGMRuntime.gml_ini_key_delete("audio", "device")
            \tif not _check(not GMRuntime.gml_ini_key_exists("audio", "device"), "ini key delete failed"):
            \t\treturn
            \tGMRuntime.gml_ini_close()

            \tGMRuntime.gml_ini_open("save/settings.ini")
            \tif not _check(abs(GMRuntime.gml_ini_read_real("audio", "volume", 1.0) - 0.75) < 0.0001, "ini persisted real mismatch"):
            \t\treturn
            \tGMRuntime.gml_ini_section_delete("audio")
            \tif not _check(not GMRuntime.gml_ini_section_exists("audio"), "ini section delete failed"):
            \t\treturn
            \tGMRuntime.gml_ini_close()

            \tvar list = GMRuntime.gml_ds_list_create()
            \tGMRuntime.gml_ds_list_add(list, [1, GMRuntime.gml_undefined(), NAN, INF])
            \tvar map = GMRuntime.gml_ds_map_create()
            \tGMRuntime.gml_ds_map_set(map, "name", "Ada")
            \tGMRuntime.gml_ds_map_set(map, "items", list)
            \tvar encoded = GMRuntime.gml_json_encode(map)
            \tvar decoded = GMRuntime.gml_json_decode(encoded)
            \tif not _check(decoded["name"] == "Ada", "json string mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][0] == 1, "json list number mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][1] == null, "json undefined mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][2] == null, "json NaN mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][3] == null, "json infinity mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(GMRuntime.gml_json_decode("{bad")), "json invalid should be undefined"):
            \t\treturn

            \tprint("FILES_INI_JSON_SMOKE_OK")
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
            _write_text(project_dir / "datafiles" / "config" / "default.txt", "included\n42\n")
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
        self.assertIn("FILES_INI_JSON_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
