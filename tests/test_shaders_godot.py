from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast

from src.conversion.asset_output_paths import build_asset_output_paths
from src.conversion.shaders import ShaderConverter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHADER_CORPUS_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "shader_corpus"


class _ShaderCorpusCase(TypedDict):
    name: str
    vertex: str
    fragment: str
    vertex_sha256: str
    fragment_sha256: str
    origin: str
    license: str
    features: list[str]


class _ShaderCorpusManifest(TypedDict):
    format_version: int
    cases: list[_ShaderCorpusCase]


def _load_shader_corpus() -> _ShaderCorpusManifest:
    return cast(
        _ShaderCorpusManifest,
        json.loads(
            (SHADER_CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8")
        ),
    )


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
    def test_supported_corpus_compiles_and_loads_in_exact_godot_4_7_1(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        corpus = _load_shader_corpus()
        self.assertEqual(corpus["format_version"], 1)
        self.assertGreaterEqual(len(corpus["cases"]), 3)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gm_directory = root / "gamemaker"
            godot_directory = root / "godot"
            godot_directory.mkdir()
            resources: list[dict[str, object]] = []
            for case in corpus["cases"]:
                shader_name = case["name"]
                shader_directory = gm_directory / "shaders" / shader_name
                shader_directory.mkdir(parents=True)
                vertex_source = (
                    SHADER_CORPUS_ROOT / case["vertex"]
                ).read_text(encoding="utf-8")
                fragment_source = (
                    SHADER_CORPUS_ROOT / case["fragment"]
                ).read_text(encoding="utf-8")
                self.assertEqual(
                    hashlib.sha256(vertex_source.encode("utf-8")).hexdigest(),
                    case["vertex_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(fragment_source.encode("utf-8")).hexdigest(),
                    case["fragment_sha256"],
                )
                (shader_directory / f"{shader_name}.vsh").write_text(
                    vertex_source,
                    encoding="utf-8",
                )
                (shader_directory / f"{shader_name}.fsh").write_text(
                    fragment_source,
                    encoding="utf-8",
                )
                (shader_directory / f"{shader_name}.yy").write_text(
                    json.dumps(
                        {
                            "name": shader_name,
                            "resourceType": "GMShader",
                            "parent": {
                                "name": "Shaders",
                                "path": "folders/Shaders.yy",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                resources.append(
                    {
                        "id": {
                            "name": shader_name,
                            "path": (
                                f"shaders/{shader_name}/{shader_name}.yy"
                            ),
                        }
                    }
                )
            (gm_directory / "ShaderCorpus.yyp").write_text(
                json.dumps({"%Name": "ShaderCorpus", "resources": resources}),
                encoding="utf-8",
            )

            converter = ShaderConverter(
                gm_directory,
                godot_directory,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=3,
            )
            converter.convert_all()
            counts = converter.conversion_step_result().resources
            self.assertEqual(counts.requested, len(corpus["cases"]))
            self.assertEqual(counts.completed, len(corpus["cases"]))
            self.assertEqual(counts.failed, 0)
            output_paths = build_asset_output_paths(
                gm_directory,
                godot_directory,
            )["shaders"]
            for case in corpus["cases"]:
                generated_path = (
                    godot_directory
                    / output_paths[case["name"]].removeprefix("res://")
                )
                generated_source = generated_path.read_text(encoding="utf-8")
                self.assertNotIn("gm_Matrices", generated_source)
                self.assertNotIn("gm_BaseTexture", generated_source)
                self.assertNotIn("gl_Position", generated_source)
                self.assertNotIn("gl_FragColor", generated_source)

            (godot_directory / "project.godot").write_text(
                '[application]\nrun/main_scene="res://smoke.tscn"\n',
                encoding="utf-8",
            )
            script_lines = [
                "extends Node",
                "",
                "func _ready():",
            ]
            for index, case in enumerate(corpus["cases"]):
                resource_path = output_paths[case["name"]]
                script_lines.extend(
                    (
                        f'\tvar shader_{index} = load("{resource_path}")',
                        f"\tif shader_{index} == null:",
                        (
                            '\t\tpush_error("shader corpus load failed: '
                            f'{case["name"]}")'
                        ),
                        "\t\tget_tree().quit(1)",
                        "\t\treturn",
                        f"\tvar material_{index} = ShaderMaterial.new()",
                        f"\tmaterial_{index}.shader = shader_{index}",
                        f"\tif material_{index}.shader == null:",
                        (
                            '\t\tpush_error("shader corpus compile failed: '
                            f'{case["name"]}")'
                        ),
                        "\t\tget_tree().quit(1)",
                        "\t\treturn",
                        (
                            f"\tvar uniforms_{index} = "
                            f"shader_{index}.get_shader_uniform_list()"
                        ),
                        (
                            f'\tprint("SHADER_COMPILED:{case["name"]}:", '
                            f"uniforms_{index}.size())"
                        ),
                    )
                )
            script_lines.extend(
                (
                    '\tprint("SHADER_CORPUS_OK")',
                    "\tget_tree().quit(0)",
                    "",
                )
            )
            (godot_directory / "smoke.gd").write_text(
                "\n".join(script_lines),
                encoding="utf-8",
            )
            (godot_directory / "smoke.tscn").write_text(
                "\n".join(
                    (
                        "[gd_scene load_steps=2 format=3]",
                        "",
                        (
                            '[ext_resource type="Script" '
                            'path="res://smoke.gd" id="1"]'
                        ),
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
        self.assertIn(
            "Godot Engine v4.7.1.stable.official.a13da4feb",
            result.stdout,
        )
        self.assertIn("SHADER_CORPUS_OK", result.stdout)
        self.assertNotIn("SHADER ERROR:", result.stdout)
        self.assertNotIn("Shader compilation failed", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)

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
                        "attribute vec3 in_Position;",
                        "varying vec2 v_shared;",
                        "uniform float amount;",
                        "void main() {",
                        "    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION]",
                        "        * vec4(in_Position, 1.0);",
                        "    v_shared = vec2(amount);",
                        "}",
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
                        "\tvar uniforms = shader.get_shader_uniform_list()",
                        '\tprint("PAIRED_SHADER_COMPILED:", uniforms.size())',
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
        self.assertIn("PAIRED_SHADER_COMPILED:", result.stdout)
        self.assertNotIn("SHADER ERROR:", result.stdout)
        self.assertNotIn("Shader compilation failed", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)


if __name__ == "__main__":
    unittest.main()
