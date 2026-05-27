from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Callable

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
        \tGMRuntime.gml_view_set_camera(1, created)
        \tif not _check(GMRuntime.gml_view_get_camera(1) == created, "view_set_camera did not assign camera handle"):
        \t\treturn
        \tif not _check(GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_camera"), 1) == created, "view_camera array did not mirror assigned camera"):
        \t\treturn
        \tGMRuntime.gml_camera_apply(created)
        \tif not _check(GMRuntime.gml_camera_get_active() == created, "camera_apply did not update active camera"):
        \t\treturn
        \tvar surf = GMRuntime.gml_surface_create(32, 16)
        \tif not _check(GMRuntime.gml_view_set_surface_id(1, surf) == surf, "view_set_surface_id did not return assigned surface"):
        \t\treturn
        \tif not _check(GMRuntime.gml_view_get_surface_id(1) == surf, "view_get_surface_id did not return assigned surface"):
        \t\treturn
        \tGMRuntime.gml_view_set_surface_id(1, -1)
        \tif not _check(GMRuntime.gml_view_get_surface_id(1) == -1, "view surface clear did not reset to -1"):
        \t\treturn
        \tGMRuntime.gml_surface_free(surf)
        \tGMRuntime.gml_view_set_camera(1, -1)
        \tif not _check(GMRuntime.gml_view_get_camera(1) == -1, "view camera clear did not reset to -1"):
        \t\treturn
        \tvar empty = GMRuntime.gml_camera_create()
        \tif not _check(GMRuntime.gml_handle_is_valid(empty), "camera_create did not return a valid handle"):
        \t\treturn
        \tGMRuntime.gml_camera_destroy(empty)
        \tif not _check(not GMRuntime.gml_handle_is_valid(empty), "camera_destroy did not invalidate handle"):
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


def _write_window_display_scene(project_dir: Path) -> None:
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
        \tvar headless = DisplayServer.get_name() == "headless"
        \tGMRuntime.gml_display_set_gui_size(-1, -1)
        \tvar base_gui_w = GMRuntime.gml_display_get_gui_width()
        \tvar base_gui_h = GMRuntime.gml_display_get_gui_height()
        \tGMRuntime.gml_display_set_gui_maximise(0.5, 0.25, 4, 8)
        \tif not _check(abs(GMRuntime.gml_display_get_gui_width() - (base_gui_w * 2.0)) < 0.01, "GUI maximise width scale mismatch"):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_display_get_gui_height() - (base_gui_h * 4.0)) < 0.01, "GUI maximise height scale mismatch"):
        \t\treturn
        \tGMRuntime.gml_display_mouse_set(4 + base_gui_w * 0.25, 8 + base_gui_h * 0.125)
        \tif not _check(abs(GMRuntime.gml_device_mouse_x_to_gui(0) - (base_gui_w * 0.5)) < 0.01, "GUI mouse x conversion did not apply maximise offset/scale"):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_device_mouse_y_to_gui(0) - (base_gui_h * 0.5)) < 0.01, "GUI mouse y conversion did not apply maximise offset/scale"):
        \t\treturn
        \tGMRuntime.gml_display_set_gui_size(320, 200)
        \tif not _check(GMRuntime.gml_display_get_gui_width() == 320 and GMRuntime.gml_display_get_gui_height() == 200, "explicit GUI size should override maximise dimensions"):
        \t\treturn
        \tGMRuntime.gml_display_set_gui_size(-1, -1)
        \tif not _check(abs(GMRuntime.gml_display_get_gui_width() - base_gui_w) < 0.01 and abs(GMRuntime.gml_display_get_gui_height() - base_gui_h) < 0.01, "GUI reset did not restore base dimensions"):
        \t\treturn
        \tif not _check(GMRuntime.gml_display_reset(0, false) == 0, "display_reset should return success code"):
        \t\treturn
        \tGMRuntime.gml_display_set_timing_method(0)
        \tif not _check(GMRuntime.gml_display_get_timing_method() == 0, "display timing method state mismatch"):
        \t\treturn
        \tGMRuntime.gml_display_set_sleep_margin(12)
        \tif not _check(GMRuntime.gml_display_get_sleep_margin() == 12, "display sleep margin state mismatch"):
        \t\treturn
        \tGMRuntime.gml_display_set_ui_visibility(0)
        \tif not headless:
        \t\tvar w = GMRuntime.gml_display_get_width()
        \t\tvar h = GMRuntime.gml_display_get_height()
        \t\tif not _check(w > 0 and h > 0, "display_get_width/height should return positive"):
        \t\t\treturn
        \t\tvar dpi_x = GMRuntime.gml_display_get_dpi_x()
        \t\tvar dpi_y = GMRuntime.gml_display_get_dpi_y()
        \t\tif not _check(dpi_x > 0 and dpi_y > 0, "display_get_dpi_x/y should return positive"):
        \t\t\treturn
        \t\tvar freq = GMRuntime.gml_display_get_frequency()
        \t\tif not _check(freq > 0, "display_get_frequency should be positive"):
        \t\t\treturn
        \t\tvar orient = GMRuntime.gml_display_get_orientation()
        \t\tif not _check(typeof(orient) == TYPE_INT, "display_get_orientation should return int"):
        \t\t\treturn
        \t\tGMRuntime.gml_display_set_orientation(orient)
        \t\tvar ww = GMRuntime.gml_window_get_width()
        \t\tvar wh = GMRuntime.gml_window_get_height()
        \t\tif not _check(ww > 0 and wh > 0, "window_get_width/height should return positive"):
        \t\t\treturn
        \t\tvar fullscreen = GMRuntime.gml_window_get_fullscreen()
        \t\tif not _check(typeof(fullscreen) == TYPE_BOOL, "window_get_fullscreen should be bool"):
        \t\t\treturn
        \t\tvar wx = GMRuntime.gml_window_get_x()
        \t\tvar wy = GMRuntime.gml_window_get_y()
        \t\tif not _check(typeof(wx) == TYPE_FLOAT and typeof(wy) == TYPE_FLOAT, "window_get_x/y should return numbers"):
        \t\t\treturn
        \t\tvar rects = GMRuntime.gml_window_get_visible_rects()
        \t\tif not _check(typeof(rects) == TYPE_ARRAY, "window_get_visible_rects should return array"):
        \t\t\treturn
        \t\tGMRuntime.gml_window_center()
        \t\tGMRuntime.gml_window_set_position(100, 100)
        \t\tGMRuntime.gml_window_set_fullscreen(false)
        \t\tGMRuntime.gml_window_set_size(640, 480)
        \t\tGMRuntime.gml_window_set_rectangle(50, 50, 600, 400)
        \t\tGMRuntime.gml_window_set_min_width(200)
        \t\tGMRuntime.gml_window_set_max_width(2000)
        \t\tGMRuntime.gml_window_set_min_height(150)
        \t\tGMRuntime.gml_window_set_max_height(1500)
        \t\tGMRuntime.gml_window_minimise()
        \t\tGMRuntime.gml_window_restore()
        \telse:
        \t\tGMRuntime.gml_display_get_width()
        \t\tGMRuntime.gml_display_get_height()
        \t\tGMRuntime.gml_display_get_orientation()
        \t\tGMRuntime.gml_window_get_width()
        \t\tGMRuntime.gml_window_get_height()
        \t\tGMRuntime.gml_window_get_fullscreen()
        \t\tGMRuntime.gml_window_get_visible_rects()
        \t\tGMRuntime.gml_window_center()
        \t\tGMRuntime.gml_window_set_position(100, 100)
        \t\tGMRuntime.gml_window_set_size(640, 480)
        \t\tGMRuntime.gml_window_set_fullscreen(false)
        \tvar save_result = GMRuntime.gml_screen_save("gm2godot_screens/full.png")
        \tvar save_part_result = GMRuntime.gml_screen_save_part("gm2godot_screens/part.png", 0, 0, 8, 8)
        \tif headless:
        \t\tif not _check(save_result == -1 and save_part_result == -1, "screen save should report unavailable in headless mode"):
        \t\t\treturn
        \telse:
        \t\tif not _check(save_result == 0 and save_part_result == 0, "screen save should succeed when DisplayServer capture is available"):
        \t\t\treturn
        \t\tif not _check(FileAccess.file_exists("user://gm2godot_screens/full.png") and FileAccess.file_exists("user://gm2godot_screens/part.png"), "screen save did not write relative user paths"):
        \t\t\treturn
        \tprint("WINDOW_DISPLAY_SMOKE_OK")
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
    def _run_smoke(self, scene_writer: Callable[[Path], None]) -> tuple[int, str]:
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
            scene_writer(project_dir)

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

        return result.returncode, output

    def test_camera_helpers_sync_view_arrays_and_gui_size(self) -> None:
        returncode, output = self._run_smoke(_write_smoke_scene)
        self.assertEqual(returncode, 0, output)
        self.assertIn("CAMERA_DISPLAY_SMOKE_OK", output)

    def test_window_display_screenshot_apis(self) -> None:
        returncode, output = self._run_smoke(_write_window_display_scene)
        self.assertEqual(returncode, 0, output)
        self.assertIn("WINDOW_DISPLAY_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
