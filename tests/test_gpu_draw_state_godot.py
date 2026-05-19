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


class TestGPUDrawStateGodotSmoke(unittest.TestCase):
    def test_gpu_state_and_texture_handles_compile_and_apply(self) -> None:
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
            \tGMRuntime.gml_draw_begin(self, "_draw")
            \tGMRuntime.gml_gpu_set_blendmode(1)
            \tif not _check(GMRuntime.gml_gpu_get_blendmode() == 1, "blend mode getter failed"):
            \t\treturn
            \tif not _check(material is CanvasItemMaterial, "CanvasItemMaterial was not installed"):
            \t\treturn
            \tif not _check(material.blend_mode == CanvasItemMaterial.BLEND_MODE_ADD, "blend mode was not applied"):
            \t\treturn

            \tGMRuntime.gml_gpu_set_texfilter(true)
            \tGMRuntime.gml_gpu_set_texrepeat(true)
            \tif not _check(texture_filter == CanvasItem.TEXTURE_FILTER_LINEAR, "texture filter was not applied"):
            \t\treturn
            \tif not _check(texture_repeat == CanvasItem.TEXTURE_REPEAT_ENABLED, "texture repeat was not applied"):
            \t\treturn

            \tGMRuntime.gml_gpu_set_colorwriteenable(true, false, true, false)
            \tvar writes = GMRuntime.gml_gpu_get_colorwriteenable()
            \tif not _check(writes[0] and not writes[1] and writes[2] and not writes[3], "color write state failed"):
            \t\treturn
            \tvar color = GMRuntime._gml_draw_modulate(0xffffff, 1)
            \tif not _check(color.g == 0.0 and color.a == 0.0, "color write mask was not reflected in modulate"):
            \t\treturn

            \tGMRuntime.gml_gpu_set_alphatestenable(true)
            \tGMRuntime.gml_gpu_set_alphatestref(128)
            \tif not _check(not GMRuntime._gml_draw_alpha_test_allows(0.25), "alpha test low value passed"):
            \t\treturn
            \tif not _check(GMRuntime._gml_draw_alpha_test_allows(0.75), "alpha test high value failed"):
            \t\treturn

            \tvar surf = GMRuntime.gml_surface_create(8, 4)
            \tvar tex = GMRuntime.gml_surface_get_texture(surf)
            \tif not _check(GMRuntime.gml_handle_is_valid(tex), "surface texture handle invalid"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_exists(tex), "texture_exists failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_get_width(tex) == 8, "texture width failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_get_height(tex) == 4, "texture height failed"):
            \t\treturn
            \tif not _check(is_equal_approx(GMRuntime.gml_texture_get_texel_width(tex), 0.125), "texture texel width failed"):
            \t\treturn
            \tif not _check(is_equal_approx(GMRuntime.gml_texture_get_texel_height(tex), 0.25), "texture texel height failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_get_uvs(tex).size() == 8, "texture UV metadata failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_is_ready(tex), "texture_is_ready failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_prefetch(tex), "texture_prefetch failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_texture_flush(tex), "texture_flush failed"):
            \t\treturn
            \tGMRuntime.gml_draw_texture_flush()
            \tGMRuntime.gml_draw_flush()

            \tGMRuntime.gml_surface_free(surf)
            \tGMRuntime.gml_draw_end()
            \tprint("GPU_STATE_SMOKE_OK")
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
        self.assertIn("GPU_STATE_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
