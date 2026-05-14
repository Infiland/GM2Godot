from __future__ import annotations

import base64
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
from src.conversion.script_generator import ObjectRuntimeConfig, SpriteRuntimeConfig, generate_script_content


_PNG_1X1_WHITE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


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


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _object_scene(name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=3 format=3]

        [ext_resource type="PackedScene" path="res://sprites/spr_player/spr_player.tscn" id="1"]
        [ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="2"]

        [node name="{name}" type="Node2D"]
        script = ExtResource("2")

        [node name="spr_player" parent="." instance=ExtResource("1")]
        """
    )


def _sprite_scene() -> str:
    return textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Texture2D" path="res://sprites/spr_player/spr_player.png" id="1"]

        [node name="spr_player" type="Area2D"]
        metadata/gamemaker_width = 1
        metadata/gamemaker_height = 1
        metadata/gamemaker_origin_x = 0
        metadata/gamemaker_origin_y = 0

        [node name="Sprite2D" type="Sprite2D" parent="."]
        texture = ExtResource("1")
        """
    )


def _write_registry(project_dir: Path) -> None:
    entries = (
        AssetRegistryEntry(
            id=100,
            name="spr_player",
            kind="sprites",
            asset_type="sprite",
            type_name="Sprite",
            source_path="sprites/spr_player/spr_player.yy",
            godot_path="res://sprites/spr_player/spr_player.tscn",
            legacy_id="sprites/spr_player/spr_player.yy",
        ),
        AssetRegistryEntry(
            id=101,
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


def _write_object(project_dir: Path, name: str) -> None:
    draw_source = (
        "draw_set_alpha(0.9);"
        "draw_self();"
        "draw_sprite(spr_player, image_index, 2, 2);"
        "draw_sprite_ext(spr_player, 0, 4, 4, 2, 1, 45, c_red, 0.5);"
        "draw_sprite_part(spr_player, 0, 0, 0, 1, 1, 6, 6);"
        "draw_sprite_pos(spr_player, 0, 0, 0, 4, 0, 4, 4, 0, 4, 0.75);"
        "draw_sprite_tiled(spr_player, 0, 0, 0);"
        "draw_set_halign(fa_center);"
        "draw_set_valign(fa_middle);"
        'draw_text(8, 8, "Hi");'
        'draw_text_ext(8, 16, "Hi there", -1, 32);'
        'draw_text_transformed(8, 24, "Hi", 1, 1, 15);'
        'text_width = string_width("Hi");'
        'text_height = string_height_ext("Hi there", -1, 32);'
        "draw_ok = draw_get_halign() + draw_get_valign();"
    )
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [{"eventType": 8, "eventNum": 0}],
            code_bodies={
                "_draw": transpile_gml_code(draw_source, asset_names={"spr_player"}),
            },
            instance_variables={"draw_ok", "text_height", "text_width"},
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name="spr_player",
                sprite_scene_paths={"spr_player": "res://sprites/spr_player/spr_player.tscn"},
            ),
            object_runtime=ObjectRuntimeConfig(object_name=name),
        ),
    )
    _write_text(object_dir / f"{name}.tscn", _object_scene(name))


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
        \tif not _check(int(drawer.draw_ok) == 2, "text alignment state was not preserved"):
        \t\treturn
        \tif not _check(float(drawer.text_width) > 0.0, "string_width did not use a font"):
        \t\treturn
        \tif not _check(float(drawer.text_height) > 0.0, "string_height_ext did not use a font"):
        \t\treturn
        \tprint("DRAW_SPRITE_TEXT_SMOKE_OK")
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


class TestDrawSpriteTextGodotSmoke(unittest.TestCase):
    def test_generated_draw_event_uses_sprite_text_runtime(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DrawSpriteTextSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_bytes(
                project_dir / "sprites" / "spr_player" / "spr_player.png",
                base64.b64decode(_PNG_1X1_WHITE),
            )
            _write_text(project_dir / "sprites" / "spr_player" / "spr_player.tscn", _sprite_scene())
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
        self.assertIn("DRAW_SPRITE_TEXT_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
