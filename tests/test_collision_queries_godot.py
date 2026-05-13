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


def _object_scene(name: str, size: int = 16) -> str:
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


def _write_object(project_dir: Path, name: str) -> None:
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content([], object_runtime=ObjectRuntimeConfig(object_name=name)),
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

        func _same_handle(left, right):
        \treturn left.index == right.index

        func _ready():
        \tvar layer = Node2D.new()
        \tlayer.name = "Instances"
        \tadd_child(layer)

        \tvar player_selector = GMRuntime.gml_asset_get_index("o_player")
        \tvar wall_selector = GMRuntime.gml_asset_get_index("o_wall")
        \tvar player_handle = GMRuntime.gml_instance_create_layer(10, 20, "Instances", player_selector, self)
        \tvar wall_handle = GMRuntime.gml_instance_create_layer(40, 20, "Instances", wall_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(player_handle), "player was not created"):
        \t\treturn
        \tif not _check(GMRuntime.gml_handle_is_valid(wall_handle), "wall was not created"):
        \t\treturn
        \tvar player = GMRuntime.gml_handle_resolve(player_handle)

        \tif not _check(GMRuntime.gml_place_meeting(player, 40, 20, wall_selector), "place_meeting missed wall"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_place_meeting(player, 10, 20, wall_selector), "place_meeting hit wall at current position"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_instance_place(player, 40, 20, wall_selector), wall_handle), "instance_place returned wrong wall"):
        \t\treturn
        \tif not _check(GMRuntime.gml_position_meeting(player, 40, 20, wall_selector), "position_meeting missed wall"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_instance_position(player, 40, 20, wall_selector), wall_handle), "instance_position returned wrong wall"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_collision_point(player, 40, 20, wall_selector, true, false), wall_handle), "collision_point missed wall"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_collision_rectangle(player, 32, 12, 48, 28, wall_selector, false, false), wall_handle), "collision_rectangle missed wall"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_collision_line(player, 0, 20, 80, 20, wall_selector, false, false), wall_handle), "collision_line missed wall"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_collision_circle(player, 40, 20, 8, wall_selector, false, false), wall_handle), "collision_circle missed wall"):
        \t\treturn
        \tif not _check(GMRuntime.gml_collision_point(player, 10, 20, GMRuntime.gml_instance_all(), false, true).index == GMRuntime.GML_INSTANCE_INVALID_INDEX, "notme did not exclude current instance"):
        \t\treturn
        \tif not _check(_same_handle(GMRuntime.gml_collision_point(player, 10, 20, GMRuntime.gml_instance_all(), false, false), player_handle), "all selector did not include current instance"):
        \t\treturn
        \tif not _check(GMRuntime.gml_collision_point(player, -100, -100, wall_selector, false, false).index == GMRuntime.GML_INSTANCE_INVALID_INDEX, "miss did not return noone"):
        \t\treturn

        \tprint("COLLISION_SMOKE_OK")
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


class TestCollisionQueriesGodotSmoke(unittest.TestCase):
    def test_runtime_collision_queries_against_generated_shapes(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="CollisionSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_object(project_dir, "o_player")
            _write_object(project_dir, "o_wall")
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
        self.assertIn("COLLISION_SMOKE_OK", output)
