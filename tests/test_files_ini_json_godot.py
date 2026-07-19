from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.included_files import IncludedFilesConverter


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

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

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

            \tGMRuntime.gml_file_delete("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", true) == "user://gm2godot/Config/My File.txt", "relative write path was normalized or escaped user storage"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "res://included_files/config/my_file.txt", "included text path was not normalized for packaged lookup"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Binary Data/My Bytes.bin", false) == "res://included_files/binary_data/my_bytes.bin", "nested included binary path was not normalized"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Missing Folder/Missing File.txt", false) == "user://gm2godot/Missing Folder/Missing File.txt", "missing relative read did not fall back to exact user path"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("user://explicit.txt", false) == "user://explicit.txt", "explicit user path changed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("res://included_files/config/my_file.txt", false) == "res://included_files/config/my_file.txt", "explicit resource read path changed"):
            \t\treturn

            \tGMRuntime.gml_file_delete("Read Me.txt")
            \tGMRuntime.gml_file_delete("read_me.txt")
            \tGMRuntime.gml_file_delete("READ_ME_2.TXT")
            \tGMRuntime.gml_file_delete("READ ME.TXT")
            \tGMRuntime.gml_file_delete("foo_bar")
            \tGMRuntime.gml_file_delete("Foo Bar/item.txt")
            \tGMRuntime.gml_file_delete("Gone File.txt")
            \tGMRuntime.gml_file_delete("Ghost File.txt")
            \tif not _check(GMRuntime.gml_file_resolve_path("Read Me.txt", false) == "res://included_files/read_me_3.txt", "exact colliding logical path did not use reserved suffix"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("read_me.txt", false) == "res://included_files/read_me.txt", "canonical collision member resolved incorrectly"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("READ_ME_2.TXT", false) == "res://included_files/read_me_2.txt", "unique canonical natural suffix lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("READ ME.TXT", false) == "user://gm2godot/READ ME.TXT", "ambiguous canonical lookup did not fail closed"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("READ ME.TXT"), "ambiguous canonical lookup selected a payload"):
            \t\treturn
            \tvar collision_reader = GMRuntime.gml_file_text_open_read("Read Me.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(collision_reader) == "normalized collision", "exact collision payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(collision_reader)
            \tvar canonical_reader = GMRuntime.gml_file_text_open_read("read_me.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(canonical_reader) == "canonical collision", "canonical collision payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(canonical_reader)

            \tif not _check(GMRuntime.gml_file_resolve_path("foo_bar", false) == "res://included_files/foo_bar_2", "file/directory blocker file did not resolve to relocation"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Foo Bar/item.txt", false) == "res://included_files/foo_bar/item.txt", "file/directory blocker nested file path mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_exists("Foo Bar"), "file/directory blocker directory lookup failed"):
            \t\treturn
            \tvar blocker_reader = GMRuntime.gml_file_text_open_read("foo_bar")
            \tif not _check(GMRuntime.gml_file_text_read_string(blocker_reader) == "blocking file", "relocated blocking file payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(blocker_reader)
            \tvar nested_reader = GMRuntime.gml_file_text_open_read("Foo Bar/item.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(nested_reader) == "nested item", "nested blocker payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(nested_reader)

            \tif not _check(GMRuntime.gml_file_resolve_path("Gone File.txt", false) == "user://gm2godot/Gone File.txt", "known missing assigned target fell through to canonical payload"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("Gone File.txt"), "known missing assigned target selected canonical payload"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Ghost File.txt", false) == "user://gm2godot/Ghost File.txt", "planned but unemitted logical path fell through to canonical payload"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("Ghost File.txt"), "planned but unemitted logical path selected canonical payload"):
            \t\treturn

            \tGMRuntime.gml_file_delete(" Leading.txt")
            \tGMRuntime.gml_file_delete("Trailing.txt ")
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", true) == "user://gm2godot/ Leading.txt", "leading-space write path lost its literal space"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", true) == "user://gm2godot/Trailing.txt ", "trailing-space write path lost its literal space"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "res://included_files/_leading.txt", "leading-space packaged lookup mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "res://included_files/trailing.txt_", "trailing-space packaged lookup mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_exists(" Leading.txt") and GMRuntime.gml_file_exists("Trailing.txt "), "edge-space included file not found"):
            \t\treturn
            \tvar leading_space_reader = GMRuntime.gml_file_text_open_read(" Leading.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(leading_space_reader) == "leading packaged", "leading-space included text mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(leading_space_reader)
            \tvar trailing_space_reader = GMRuntime.gml_file_text_open_read("Trailing.txt ")
            \tif not _check(GMRuntime.gml_file_text_read_string(trailing_space_reader) == "trailing packaged", "trailing-space included text mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(trailing_space_reader)

            \tvar leading_space_writer = GMRuntime.gml_file_text_open_write(" Leading.txt")
            \tGMRuntime.gml_file_text_write_string(leading_space_writer, "leading user")
            \tGMRuntime.gml_file_text_close(leading_space_writer)
            \tvar trailing_space_writer = GMRuntime.gml_file_text_open_write("Trailing.txt ")
            \tGMRuntime.gml_file_text_write_string(trailing_space_writer, "trailing user")
            \tGMRuntime.gml_file_text_close(trailing_space_writer)
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "user://gm2godot/ Leading.txt", "leading-space user override did not take precedence"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "user://gm2godot/Trailing.txt ", "trailing-space user override did not take precedence"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_delete(" Leading.txt") and GMRuntime.gml_file_delete("Trailing.txt "), "edge-space user override delete failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "res://included_files/_leading.txt" and GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "res://included_files/trailing.txt_", "edge-space packaged files did not reappear"):
            \t\treturn

            \tif not _check(GMRuntime.gml_file_exists("Config/My File.txt"), "included file not found through mixed-case logical path"):
            \t\treturn
            \tvar included = GMRuntime.gml_file_text_open_read("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(included) == "included", "included text mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_read_real(included) == 42, "included real mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_eof(included), "included EOF mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(included)

            \tvar included_buffer = GMRuntime.gml_buffer_load("Binary Data/My Bytes.bin")
            \tif not _check(GMRuntime.gml_buffer_exists(included_buffer), "included binary buffer_load failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_used_size(included_buffer) == 5, "included binary size mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(included_buffer, 0, 1) == 0 and GMRuntime.gml_buffer_peek(included_buffer, 4, 1) == 255, "included binary contents mismatch"):
            \t\treturn
            \tGMRuntime.gml_buffer_delete(included_buffer)

            \tvar override_writer = GMRuntime.gml_file_text_open_write("Config/My File.txt")
            \tGMRuntime.gml_file_text_write_string(override_writer, "user override")
            \tGMRuntime.gml_file_text_close(override_writer)
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "user://gm2godot/Config/My File.txt", "exact user override did not take precedence"):
            \t\treturn
            \tvar override_reader = GMRuntime.gml_file_text_open_read("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(override_reader) == "user override", "user override content mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(override_reader)
            \tif not _check(GMRuntime.gml_file_delete("Config/My File.txt"), "user override delete failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "res://included_files/config/my_file.txt", "packaged file did not reappear after deleting override"):
            \t\treturn

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
            workspace = Path(tmp)
            gm_project_dir = workspace / "gamemaker"
            project_dir = workspace / "godot"
            _write_text(
                gm_project_dir / "RuntimeParity.yyp",
                json.dumps(
                    {
                        "IncludedFiles": [
                            {
                                "name": "My File.txt",
                                "filePath": "datafiles/Config",
                            },
                            {
                                "name": "My Bytes.bin",
                                "filePath": "datafiles/Binary Data",
                            },
                            {
                                "name": " Leading.txt",
                                "filePath": "datafiles",
                            },
                            {
                                "name": "Trailing.txt ",
                                "filePath": "datafiles",
                            },
                            {
                                "name": "Ghost File.txt",
                                "filePath": "datafiles",
                            },
                        ]
                    }
                ),
            )
            _write_text(
                gm_project_dir / "datafiles" / "Config" / "My File.txt",
                "included\n42\n",
            )
            _write_text(
                gm_project_dir / "datafiles" / " Leading.txt",
                "leading packaged\n",
            )
            _write_text(
                gm_project_dir / "datafiles" / "Trailing.txt ",
                "trailing packaged\n",
            )
            collision_payloads = {
                "Read Me.txt": "normalized collision\n",
                "read_me.txt": "canonical collision\n",
                "read_me_2.txt": "natural suffix\n",
                "foo_bar": "blocking file\n",
                "Foo Bar/item.txt": "nested item\n",
                "Gone File.txt": "target removed after conversion\n",
                "gone_file.txt": "canonical payload must not leak\n",
                "ghost_file.txt": "unavailable alias must not leak\n",
            }
            for relative_path, payload in collision_payloads.items():
                _write_text(
                    gm_project_dir
                    / "datafiles"
                    / Path(*relative_path.split("/")),
                    payload,
                )
            binary_source = (
                gm_project_dir
                / "datafiles"
                / "Binary Data"
                / "My Bytes.bin"
            )
            binary_source.parent.mkdir(parents=True, exist_ok=True)
            binary_source.write_bytes(bytes((0, 1, 127, 128, 255)))

            included_files_converter = IncludedFilesConverter(
                os.fspath(gm_project_dir),
                os.fspath(project_dir),
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            )
            included_files_converter.convert_all()
            published_root = project_dir / "included_files"
            published_registry = (
                project_dir
                / "gm2godot"
                / "gml_included_file_registry.gd"
            )
            published_root_identity = published_root.stat().st_ino
            published_registry_identity = published_registry.stat().st_ino
            published_registry_content = published_registry.read_bytes()
            included_files_converter.convert_all()
            self.assertEqual(published_root.stat().st_ino, published_root_identity)
            self.assertEqual(
                published_registry.stat().st_ino,
                published_registry_identity,
            )
            self.assertEqual(
                published_registry.read_bytes(),
                published_registry_content,
            )

            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "config"
                    / "my_file.txt"
                ).read_text(encoding="utf-8"),
                "included\n42\n",
            )
            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "binary_data"
                    / "my_bytes.bin"
                ).read_bytes(),
                bytes((0, 1, 127, 128, 255)),
            )
            self.assertEqual(
                (project_dir / "included_files" / "_leading.txt").read_text(
                    encoding="utf-8"
                ),
                "leading packaged\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "trailing.txt_").read_text(
                    encoding="utf-8"
                ),
                "trailing packaged\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "read_me_3.txt").read_text(
                    encoding="utf-8"
                ),
                "normalized collision\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "foo_bar_2").read_text(
                    encoding="utf-8"
                ),
                "blocking file\n",
            )
            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "foo_bar"
                    / "item.txt"
                ).read_text(encoding="utf-8"),
                "nested item\n",
            )
            missing_assigned_target = (
                project_dir / "included_files" / "gone_file_2.txt"
            )
            self.assertTrue(missing_assigned_target.is_file())
            missing_assigned_target.unlink()

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
        self.assertIn("FILES_INI_JSON_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
