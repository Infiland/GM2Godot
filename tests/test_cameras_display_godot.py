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
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _ready():
        \tGMRuntime.gml_draw_begin(self, "_draw")
        \tvar view_camera = GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_camera"), 0)
        \tGMRuntime.gml_array_set(GMRuntime.gml_builtin_array("view_xview"), 0, 100)
        \tGMRuntime.gml_array_set(GMRuntime.gml_builtin_array("view_yview"), 0, 200)
        \tif not _check(GMRuntime.gml_camera_get_view_x(view_camera) == 100, "view_xview did not sync to camera"):
        \t\treturn
        \tif not _check(GMRuntime.gml_camera_get_view_y(view_camera) == 200, "view_yview did not sync to camera"):
        \t\treturn
        \tGMRuntime.gml_camera_set_view_pos(view_camera, 300, 400)
        \tif not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_xview"), 0) == 300, "camera x did not sync to view_xview"):
        \t\treturn
        \tif not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_yview"), 0) == 400, "camera y did not sync to view_yview"):
        \t\treturn
        \tGMRuntime.gml_camera_set_view_size(view_camera, 320, 180)
        \tif not _check(GMRuntime.gml_camera_get_view_width(view_camera) == 320, "camera width mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_camera_get_view_height(view_camera) == 180, "camera height mismatch"):
        \t\treturn
        \tGMRuntime.gml_camera_set_view_angle(view_camera, 15)
        \tif not _check(GMRuntime.gml_camera_get_view_angle(view_camera) == 15, "camera angle mismatch"):
        \t\treturn
        \tif not _check(abs($ViewCamera.position.x - 460.0) < 0.01 and abs($ViewCamera.position.y - 490.0) < 0.01, "Camera2D position did not update"):
        \t\treturn
        \tif not _check(abs($ViewCamera.rotation_degrees - 15.0) < 0.01, "Camera2D rotation did not update"):
        \t\treturn
        \tvar created = GMRuntime.gml_camera_create_view(1, 2, 3, 4, 5, -1, 0, 0, 0, 0)
        \tif not _check(GMRuntime.gml_camera_get_view_x(created) == 1 and GMRuntime.gml_camera_get_view_y(created) == 2, "created camera position mismatch"):
        \t\treturn
        \tGMRuntime.gml_display_set_gui_size(800, 450)
        \tif not _check(GMRuntime.gml_display_get_gui_width() == 800, "GUI width mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_display_get_gui_height() == 450, "GUI height mismatch"):
        \t\treturn
        \tGMRuntime.gml_draw_end()
        \tprint("CAMERA_DISPLAY_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")

        [node name="ViewCamera" type="Camera2D" parent="."]
        position = Vector2(160, 90)
        enabled = true
        metadata/gamemaker_view_camera = true
        metadata/gamemaker_view_enabled_camera = true
        metadata/gamemaker_view_index = 0
        metadata/gamemaker_view_xview = 0
        metadata/gamemaker_view_yview = 0
        metadata/gamemaker_view_wview = 320
        metadata/gamemaker_view_hview = 180
        """
    )
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestCamerasDisplayGodotSmoke(unittest.TestCase):
    def test_camera_helpers_sync_view_arrays_and_gui_size(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="CameraDisplaySmoke"\nrun/main_scene="res://smoke.tscn"\n',
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
        self.assertIn("CAMERA_DISPLAY_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
