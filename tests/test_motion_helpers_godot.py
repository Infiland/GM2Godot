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


def _object_scene(name: str, size: int = 10) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=3 format=3]

        [ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="1"]

        [sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]
        size = Vector2({size}, {size})

        [node name="{name}" type="Node2D"]
        script = ExtResource("1")

        [node name="Mask" type="Area2D" parent="."]

        [node name="CollisionShape2D" type="CollisionShape2D" parent="Mask"]
        shape = SubResource("RectangleShape2D_1")
        """
    )


def _write_object(project_dir: Path, name: str, *, solid: bool = False) -> None:
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [],
            object_runtime=ObjectRuntimeConfig(object_name=name, solid=solid),
        ),
    )
    _write_text(object_dir / f"{name}.tscn", _object_scene(name))


def _write_registry(project_dir: Path) -> None:
    entries = (
        AssetRegistryEntry(
            id=100,
            name="o_player",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_player/o_player.yy",
            godot_path="res://objects/o_player/o_player.tscn",
            legacy_id="objects/o_player/o_player.yy",
        ),
        AssetRegistryEntry(
            id=101,
            name="o_wall",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_wall/o_wall.yy",
            godot_path="res://objects/o_wall/o_wall.tscn",
            legacy_id="objects/o_wall/o_wall.yy",
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

        func _near(left, right):
        \treturn abs(float(left) - float(right)) <= 0.01

        func _ready():
        \tvar layer = Node2D.new()
        \tlayer.name = "Instances"
        \tadd_child(layer)

        \tvar player_selector = GMRuntime.gml_asset_get_index("o_player")
        \tvar wall_selector = GMRuntime.gml_asset_get_index("o_wall")
        \tvar player_handle = GMRuntime.gml_instance_create_layer(0, 0, "Instances", player_selector, self)
        \tvar wall_handle = GMRuntime.gml_instance_create_layer(20, 0, "Instances", wall_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(player_handle), "player was not created"):
        \t\treturn
        \tif not _check(GMRuntime.gml_handle_is_valid(wall_handle), "wall was not created"):
        \t\treturn
        \tvar player = GMRuntime.gml_handle_resolve(player_handle)
        \tvar wall = GMRuntime.gml_handle_resolve(wall_handle)
        \tif not _check(wall.solid, "object solid metadata was not generated"):
        \t\treturn

        \tGMRuntime.gml_motion_set(player, 0, 4)
        \tif not _check(_near(player.speed, 4) and _near(player.direction, 0), "motion_set lost speed/direction"):
        \t\treturn
        \tif not _check(_near(player.hspeed, 4) and _near(player.vspeed, 0), "motion_set lost vector components"):
        \t\treturn
        \tGMRuntime.gml_motion_set_direction(player, 90)
        \tif not _check(_near(player.hspeed, 0) and _near(player.vspeed, -4), "direction did not use GameMaker y-down convention"):
        \t\treturn
        \tGMRuntime.gml_motion_set_hspeed(player, 3)
        \tif not _check(_near(player.speed, 5) and _near(player.direction, 53.1301), "hspeed did not resync speed/direction"):
        \t\treturn
        \tGMRuntime.gml_move_towards_point(player, 0, 10, 5)
        \tif not _check(_near(player.direction, 270) and _near(player.vspeed, 5), "move_towards_point chose wrong direction"):
        \t\treturn

        \tplayer.position = Vector2(0, 0)
        \tplayer.friction = 0
        \tplayer.gravity = 0
        \tGMRuntime.gml_motion_set(player, 0, 4)
        \tGMRuntime.gml_motion_step(player)
        \tif not _check(_near(player.position.x, 4) and _near(player.xprevious, 0), "motion step did not move by hspeed"):
        \t\treturn
        \tGMRuntime.gml_motion_set(player, 0, 0)
        \tplayer.gravity = 1
        \tplayer.gravity_direction = 270
        \tGMRuntime.gml_motion_step(player)
        \tif not _check(_near(player.vspeed, 1) and _near(player.position.y, 1), "gravity did not accelerate downward"):
        \t\treturn

        \tplayer.position = Vector2(13, 18)
        \tGMRuntime.gml_move_snap(player, 8, 10)
        \tif not _check(player.position == Vector2(16, 20), "move_snap used the wrong grid point"):
        \t\treturn
        \tif not _check(GMRuntime.gml_place_snapped(player, 8, 10), "place_snapped missed snapped position"):
        \t\treturn

        \tplayer.position = Vector2(0, 0)
        \tGMRuntime.gml_move_contact_solid(player, 0, 100)
        \tif not _check(_near(player.position.x, 9), "move_contact_solid did not stop before wall"):
        \t\treturn
        \tGMRuntime.gml_motion_set(player, 0, 4)
        \tGMRuntime.gml_move_bounce_solid(player, true)
        \tif not _check(player.hspeed < 0 and _near(player.direction, 180), "move_bounce_solid did not reflect horizontal speed"):
        \t\treturn

        \tprint("MOTION_SMOKE_OK")
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


class TestMotionHelpersGodotSmoke(unittest.TestCase):
    def test_runtime_motion_helpers_and_generated_motion_state(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="MotionSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_object(project_dir, "o_player")
            _write_object(project_dir, "o_wall", solid=True)
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
        self.assertIn("MOTION_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
