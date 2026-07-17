from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.conversion.asset_output_paths import build_asset_output_paths
from src.conversion.shaders import ShaderConverter


def _find_godot_binary() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured and os.path.isfile(configured):
        return configured
    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary
    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    return mac_binary if os.path.isfile(mac_binary) else None


class TestConvertedShaderGodotSmoke(unittest.TestCase):
    def test_dual_stage_shader_loads_in_exact_godot_4_7_1(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gm_directory = root / "gamemaker"
            godot_directory = root / "godot"
            shader_directory = gm_directory / "shaders" / "shdPair"
            shader_directory.mkdir(parents=True)
            godot_directory.mkdir()
            (shader_directory / "shdPair.yy").write_text(
                json.dumps(
                    {
                        "name": "shdPair",
                        "resourceType": "GMShader",
                        "parent": {
                            "name": "Shaders",
                            "path": "folders/Shaders.yy",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (shader_directory / "shdPair.vsh").write_text(
                "\n".join(
                    (
                        "precision highp float;",
                        "varying vec2 v_shared;",
                        "uniform float amount;",
                        "void main() { v_shared = vec2(amount); }",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            (shader_directory / "shdPair.fsh").write_text(
                "\n".join(
                    (
                        "precision mediump float;",
                        "varying vec2 v_shared;",
                        "uniform float amount;",
                        "void main() { gl_FragColor = vec4(v_shared, amount, 1.0); }",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            (gm_directory / "Pair.yyp").write_text(
                json.dumps(
                    {
                        "%Name": "Pair",
                        "resources": [
                            {
                                "id": {
                                    "name": "shdPair",
                                    "path": "shaders/shdPair/shdPair.yy",
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ShaderConverter(
                gm_directory,
                godot_directory,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=2,
            ).convert_all()
            resource_path = build_asset_output_paths(
                gm_directory,
                godot_directory,
            )["shaders"]["shdPair"]
            (godot_directory / "project.godot").write_text(
                '[application]\nrun/main_scene="res://smoke.tscn"\n',
                encoding="utf-8",
            )
            (godot_directory / "smoke.gd").write_text(
                "\n".join(
                    (
                        "extends Node",
                        "",
                        "func _ready():",
                        f'\tvar shader = load("{resource_path}")',
                        "\tif shader == null:",
                        '\t\tpush_error("shader load failed")',
                        "\t\tget_tree().quit(1)",
                        "\t\treturn",
                        "\tvar material = ShaderMaterial.new()",
                        "\tmaterial.shader = shader",
                        '\tprint("PAIRED_SHADER_OK")',
                        "\tget_tree().quit(0)",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            (godot_directory / "smoke.tscn").write_text(
                "\n".join(
                    (
                        "[gd_scene load_steps=2 format=3]",
                        "",
                        '[ext_resource type="Script" path="res://smoke.gd" id="1"]',
                        "",
                        '[node name="Smoke" type="Node"]',
                        'script = ExtResource("1")',
                        "",
                    )
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    os.fspath(godot_directory),
                    "smoke.tscn",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Godot Engine v4.7.1.stable", result.stdout)
        self.assertIn("PAIRED_SHADER_OK", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)


if __name__ == "__main__":
    unittest.main()
