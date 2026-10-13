from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import textwrap
import unittest
import zlib
from pathlib import Path

from src.conversion.asset_registry import (
    AssetRegistryEntry,
    render_asset_registry_script,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.script_generator import (
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    generate_script_content,
)
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)


def _solid_png(width: int, height: int) -> bytes:
    """Encode an opaque white RGBA PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    rows = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


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
        AssetRegistryEntry(
            id=102,
            name="o_transform",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_transform/o_transform.yy",
            godot_path="res://objects/o_transform/o_transform.tscn",
            legacy_id="objects/o_transform/o_transform.yy",
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
                "_on_draw": transpile_gml_code(draw_source, asset_names={"spr_player"}),
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


def _write_transform_object(project_dir: Path, name: str) -> None:
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [],
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
        \tGMRuntime.gml_draw_event_dispatch_frame()
        \tvar sink = GMRuntime.gm2godot_draw_debug_sink_for(drawer, "draw")
        \tif not _check(int(sink.get("commands", 0)) >= 9, "sprite and text commands did not reach the draw sink: " + str(sink)):
        \t\treturn
        \tvar visual = drawer.find_child("Sprite2D", true, false)
        \tif not _check(visual != null and not visual.visible, "the default sprite visual of an instance with a Draw event stayed visible"):
        \t\treturn
        \tif not _check(int(drawer.draw_ok) == 2, "text alignment state was not preserved"):
        \t\treturn
        \tif not _check(float(drawer.text_width) > 0.0, "string_width did not use a font"):
        \t\treturn
        \tif not _check(float(drawer.text_height) > 0.0, "string_height_ext did not use a font"):
        \t\treturn
        \tvar sprite_id = GMRuntime.gml_asset_get_index("spr_player")
        \tvar frame = GMRuntime._gml_draw_sprite_frame(sprite_id, 0)
        \tif not _check(frame != null and is_same(frame, GMRuntime._gml_draw_sprite_frame(sprite_id, 0)), "sprite frame records were not reused"):
        \t\treturn
        \tGMRuntime.gml_sprite_set_offset(sprite_id, 3, 1)
        \tvar moved = GMRuntime._gml_draw_sprite_frame(sprite_id, 0)
        \tif not _check(moved != null and moved["origin"] == Vector2(3, 1), "sprite_set_offset did not reach later draws: " + str(moved)):
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


def _write_transform_smoke_scene(project_dir: Path) -> None:
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
        \tvar instance = $inst_rotated
        \tawait get_tree().process_frame
        \tif not _check(abs(instance.image_angle - 90.0) < 0.01, "room rotation did not hydrate image_angle"):
        \t\treturn
        \t# GameMaker angles turn counter-clockwise on screen: at 90 degrees the
        \t# sprite's +x axis points up the screen (towards -y).
        \tif not _check(instance.transform.basis_xform(Vector2(1, 0)).distance_to(Vector2(0, -2)) < 0.01, "image_angle 90 did not turn the sprite counter-clockwise: " + str(instance.transform)):
        \t\treturn
        \tinstance.image_angle = 30.0
        \tvar expected_axis = Vector2(cos(deg_to_rad(30.0)), -sin(deg_to_rad(30.0))) * 2.0
        \tif not _check(instance.transform.basis_xform(Vector2(1, 0)).distance_to(expected_axis) < 0.01, "image_angle 30 did not turn the sprite counter-clockwise: " + str(instance.transform)):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_struct_get(instance, "image_angle") - 30.0) < 0.01, "image_angle did not read back"):
        \t\treturn
        \tinstance.image_angle = 90.0
        \tvar plain = Node2D.new()
        \tadd_child(plain)
        \tGMRuntime.gml_struct_set(plain, "image_angle", 90)
        \tif not _check(plain.transform.basis_xform(Vector2(1, 0)).distance_to(Vector2(0, -1)) < 0.01, "image_angle on a plain node did not turn it counter-clockwise: " + str(plain.transform)):
        \t\treturn
        \tif not _check(abs(GMRuntime.gml_struct_get(plain, "image_angle") - 90.0) < 0.01, "image_angle on a plain node did not read back"):
        \t\treturn
        \tif not _check(abs(instance.image_xscale - 2.0) < 0.01 and abs(instance.image_yscale - 0.5) < 0.01, "room scale did not hydrate image scale"):
        \t\treturn
        \tif not _check(instance.scale.distance_to(Vector2(2, 0.5)) < 0.01, "image scale did not apply to node scale"):
        \t\treturn
        \tif not _check(abs(instance.image_speed - 0.25) < 0.01, "room image_speed did not hydrate"):
        \t\treturn
        \tif not _check(instance.image_blend == 255, "room blend did not hydrate"):
        \t\treturn
        \tif not _check(abs(instance.image_alpha - 0.5) < 0.01, "room alpha did not hydrate"):
        \t\treturn
        \tvar sprite_node = instance.find_child("Sprite2D", true, false)
        \tif not _check(sprite_node != null and sprite_node.modulate.is_equal_approx(Color(1, 0, 0, 0.5)), "image blend/alpha did not apply to sprite visual"):
        \t\treturn
        \tprint("ROOM_INSTANCE_TRANSFORM_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=3 format=3]

        [ext_resource type="Script" path="res://smoke_transform.gd" id="1"]
        [ext_resource type="PackedScene" path="res://objects/o_transform/o_transform.tscn" id="2"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")

        [node name="inst_rotated" parent="." instance=ExtResource("2")]
        position = Vector2(100, 200)
        rotation_degrees = -90
        scale = Vector2(2, 0.5)
        metadata/gamemaker_image_angle = 90
        metadata/gamemaker_image_xscale = 2
        metadata/gamemaker_image_yscale = 0.5
        metadata/gamemaker_image_blend = 255
        metadata/gamemaker_image_alpha = 0.5
        metadata/gamemaker_image_index = 0
        metadata/gamemaker_image_speed = 0.25
        """
    )
    _write_text(project_dir / "smoke_transform.gd", smoke_script)
    _write_text(project_dir / "smoke_transform.tscn", smoke_scene)


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
                _solid_png(1, 1),
            )
            _write_text(project_dir / "sprites" / "spr_player" / "spr_player.tscn", _sprite_scene())
            _write_object(project_dir, "o_drawer")
            _write_smoke_scene(project_dir)

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            import_result = subprocess.run(
                [godot_binary, "--headless", "--recovery-mode", "--path", str(project_dir), "--import"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=godot_env,
            )
            self.assertEqual(import_result.returncode, 0, import_result.stdout + import_result.stderr)
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
        self.assertNotIn("Drawing is only allowed", output)
        self.assertNotIn("SCRIPT ERROR", output)

    def test_room_instance_transform_metadata_hydrates_sprite_runtime(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="RoomInstanceTransformSmoke"\nrun/main_scene="res://smoke_transform.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_bytes(
                project_dir / "sprites" / "spr_player" / "spr_player.png",
                _solid_png(1, 1),
            )
            _write_text(project_dir / "sprites" / "spr_player" / "spr_player.tscn", _sprite_scene())
            _write_transform_object(project_dir, "o_transform")
            _write_transform_smoke_scene(project_dir)

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
                    "res://smoke_transform.tscn",
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
        self.assertIn("ROOM_INSTANCE_TRANSFORM_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
