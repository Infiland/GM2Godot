from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import AssetRegistryEntry, render_asset_registry_script
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.script_generator import ObjectRuntimeConfig, generate_script_content


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


def _object_scene(name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="1"]

        [node name="{name}" type="Node2D"]
        script = ExtResource("1")
        """
    )


def _write_object(project_dir: Path, name: str) -> None:
    draw_source = (
        "draw_set_color(c_red);"
        "draw_set_alpha(0.5);"
        "draw_set_line_width(2);"
        "draw_clear(c_black);"
        "draw_rectangle(0, 0, 16, 16, false);"
        "draw_line(0, 0, 16, 16);"
        "draw_circle(8, 8, 4, true);"
        "draw_triangle(0, 16, 8, 0, 16, 16, false);"
        "draw_point(2, 2);"
        "draw_ok = draw_get_alpha();"
    )
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [{"eventType": 8, "eventNum": 0}],
            code_bodies={"_draw": transpile_gml_code(draw_source)},
            instance_variables={"draw_ok"},
            object_runtime=ObjectRuntimeConfig(object_name=name),
        ),
    )
    _write_text(object_dir / f"{name}.tscn", _object_scene(name))


def _write_registry(project_dir: Path) -> None:
    entries = (
        AssetRegistryEntry(
            id=100,
            name="o_drawer",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_drawer/o_drawer.yy",
            godot_path="res://objects/o_drawer/o_drawer.tscn",
            legacy_id="objects/o_drawer/o_drawer.yy",
        ),
    )
    _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))


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
        \tvar layer = Node2D.new()
        \tlayer.name = "Instances"
        \tadd_child(layer)
        \tvar handle = GMRuntime.gml_instance_create_layer(0, 0, "Instances", GMRuntime.gml_asset_get_index("o_drawer"), self)
        \tif not _check(GMRuntime.gml_handle_is_valid(handle), "drawer was not created"):
        \t\treturn
        \tvar drawer = GMRuntime.gml_handle_resolve(handle)
        \tdrawer.queue_redraw()
        \tawait get_tree().process_frame
        \tawait get_tree().process_frame
        \tif not _check(abs(float(drawer.draw_ok) - 0.5) <= 0.01, "draw event did not execute through runtime helpers"):
        \t\treturn
        \tprint("DRAW_SMOKE_OK")
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


class TestDrawBasicGodotSmoke(unittest.TestCase):
    def test_generated_draw_event_uses_basic_draw_runtime(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DrawSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_object(project_dir, "o_drawer")
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
        self.assertIn("DRAW_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
