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


class TestShaderRuntimeGodotSmoke(unittest.TestCase):
    def test_shader_state_uniforms_and_texture_stage_apply_to_material(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        shader_source = textwrap.dedent(
            """\
            shader_type canvas_item;
            uniform float amount = 0.0;
            uniform vec4 tint = vec4(1.0);
            uniform sampler2D overlay;

            void fragment() {
                COLOR = vec4(amount, tint.g, tint.b, 1.0);
            }
            """
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
            \tGMRuntime.gml_asset_registry_set([{
            \t\t"id": 1001,
            \t\t"name": "shd_wave",
            \t\t"kind": "shaders",
            \t\t"type": "shader",
            \t\t"type_name": "Shader",
            \t\t"source_path": "",
            \t\t"godot_path": "res://shaders/shd_wave.gdshader",
            \t\t"legacy_id": "shd_wave",
            \t\t"tags": [],
            \t\t"dynamic": false,
            \t\t"metadata": {}
            \t}])
            \tvar shader_id = GMRuntime.gml_asset_get_index("shd_wave")
            \tif not _check(GMRuntime.gml_shader_get_name(shader_id) == "shd_wave", "shader name lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_shader_is_compiled(shader_id), "shader did not compile"):
            \t\treturn

            \tGMRuntime.gml_draw_begin(self, "_draw")
            \tif not _check(GMRuntime.gml_shader_set(shader_id), "shader_set failed"):
            \t\treturn
            \tif not _check(material is ShaderMaterial, "shader material was not applied"):
            \t\treturn

            \tvar amount = GMRuntime.gml_shader_get_uniform(shader_id, "amount")
            \tvar amount_again = GMRuntime.gml_shader_get_uniform(shader_id, "amount")
            \tif not _check(amount.index == amount_again.index, "uniform handles were not stable"):
            \t\treturn
            \tif not _check(GMRuntime.gml_shader_set_uniform_f(amount, 0.75), "float uniform set failed"):
            \t\treturn
            \tif not _check(abs(material.get_shader_parameter("amount") - 0.75) < 0.001, "float uniform value mismatch"):
            \t\treturn

            \tvar tint = GMRuntime.gml_shader_get_uniform(shader_id, "tint")
            \tif not _check(GMRuntime.gml_shader_set_uniform_f(tint, 1, 0.5, 0.25, 1), "vec4 uniform set failed"):
            \t\treturn
            \tvar tint_value = material.get_shader_parameter("tint")
            \tif not _check(abs(tint_value.y - 0.5) < 0.001 and abs(tint_value.z - 0.25) < 0.001, "vec4 uniform mismatch"):
            \t\treturn

            \tvar surf = GMRuntime.gml_surface_create(4, 4)
            \tvar tex = GMRuntime.gml_surface_get_texture(surf)
            \tvar sampler = GMRuntime.gml_shader_get_sampler_index(shader_id, "overlay")
            \tif not _check(GMRuntime.gml_texture_set_stage(sampler, tex), "texture stage set failed"):
            \t\treturn
            \tif not _check(material.get_shader_parameter("overlay") is Texture2D, "texture stage did not receive Texture2D"):
            \t\treturn

            \tGMRuntime.gml_surface_free(surf)
            \tGMRuntime.gml_shader_reset()
            \tif not _check(not (material is ShaderMaterial), "shader_reset did not restore non-shader material"):
            \t\treturn
            \tGMRuntime.gml_draw_end()
            \tprint("SHADER_RUNTIME_SMOKE_OK")
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
            _write_text(project_dir / "shaders" / "shd_wave.gdshader", shader_source)
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
        self.assertIn("SHADER_RUNTIME_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
