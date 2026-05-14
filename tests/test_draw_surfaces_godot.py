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
        \tvar surf = GMRuntime.gml_surface_create(16, 8)
        \tif not _check(GMRuntime.gml_surface_exists(surf), "surface was not created"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_get_width(surf) == 16, "surface width mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_get_height(surf) == 8, "surface height mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_set_target(surf), "surface target was not set"):
        \t\treturn
        \tGMRuntime.gml_draw_clear(0x0000ff)
        \tvar surf_data = GMRuntime._gml_surface_resolve(surf)
        \tvar pixel = surf_data["image"].get_pixel(0, 0)
        \tif not _check(pixel.r > 0.95 and pixel.a > 0.95, "surface clear did not write to active target"):
        \t\treturn
        \tif not _check(GMRuntime._gml_surface_has_active_target(), "surface target stack was not active"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_reset_target(), "surface target was not reset"):
        \t\treturn
        \tif not _check(not GMRuntime._gml_surface_has_active_target(), "surface target stack did not reset"):
        \t\treturn
        \tvar copy = GMRuntime.gml_surface_create(16, 8)
        \tGMRuntime.gml_surface_copy(copy, 0, 0, surf)
        \tvar copy_pixel = GMRuntime._gml_surface_resolve(copy)["image"].get_pixel(0, 0)
        \tif not _check(copy_pixel.r > 0.95 and copy_pixel.a > 0.95, "surface copy did not copy pixels"):
        \t\treturn
        \tGMRuntime.gml_draw_surface_ext(surf, 0, 0, 1, 1, 0, 0xffffff, 1)
        \tGMRuntime.gml_application_surface_enable(false)
        \tGMRuntime.gml_application_surface_draw_enable(false)
        \tif not _check(not GMRuntime.gml_application_surface_is_enabled(), "application surface enabled state mismatch"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_application_surface_is_draw_enabled(), "application surface draw state mismatch"):
        \t\treturn
        \tvar app_pos = GMRuntime.gml_application_get_position()
        \tif not _check(app_pos.size() == 4 and app_pos[2] > app_pos[0] and app_pos[3] > app_pos[1], "application position invalid"):
        \t\treturn
        \tGMRuntime.gml_surface_free(surf)
        \tif not _check(not GMRuntime.gml_surface_exists(surf), "freed surface still exists"):
        \t\treturn
        \tGMRuntime.gml_surface_free(copy)
        \tGMRuntime.gml_draw_end()
        \tprint("DRAW_SURFACE_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestDrawSurfacesGodotSmoke(unittest.TestCase):
    def test_surface_runtime_handles_targets_and_application_surface(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DrawSurfaceSmoke"\nrun/main_scene="res://smoke.tscn"\n',
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
        self.assertIn("DRAW_SURFACE_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
