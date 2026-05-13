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


def _object_scene(name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="1"]

        [node name="{name}" type="Node2D"]
        script = ExtResource("1")
        """
    )


def _write_object(project_dir: Path, name: str, script: str) -> None:
    object_dir = project_dir / "objects" / name
    _write_text(object_dir / f"{name}.gd", script)
    _write_text(object_dir / f"{name}.tscn", _object_scene(name))


def _write_registry(project_dir: Path) -> None:
    entries = (
        AssetRegistryEntry(
            id=100,
            name="o_parent",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_parent/o_parent.yy",
            godot_path="res://objects/o_parent/o_parent.tscn",
            legacy_id="objects/o_parent/o_parent.yy",
        ),
        AssetRegistryEntry(
            id=101,
            name="o_enemy",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_enemy/o_enemy.yy",
            godot_path="res://objects/o_enemy/o_enemy.tscn",
            legacy_id="objects/o_enemy/o_enemy.yy",
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

        \tvar enemy_selector = GMRuntime.gml_asset_get_index("o_enemy")
        \tvar parent_selector = GMRuntime.gml_asset_get_index("o_parent")
        \tvar handle_a = GMRuntime.gml_instance_create_layer(10, 20, "Instances", enemy_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(handle_a), "instance_create_layer returned noone"):
        \t\treturn
        \tvar first = GMRuntime.gml_handle_resolve(handle_a)
        \tif not _check(first is Node2D, "created layer instance did not resolve to Node2D"):
        \t\treturn
        \tif not _check(first.get_parent() == layer, "instance_create_layer used the wrong parent"):
        \t\treturn
        \tif not _check(first.position == Vector2(10, 20), "instance_create_layer lost x/y"):
        \t\treturn
        \tif not _check(first.object_index == enemy_selector, "inherited _ready clobbered object_index"):
        \t\treturn

        \tvar raw_a = handle_a.index
        \tvar handle_b = GMRuntime.gml_instance_create_depth(30, 20, -12, enemy_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(handle_b), "instance_create_depth returned noone"):
        \t\treturn
        \tvar second = GMRuntime.gml_handle_resolve(handle_b)
        \tif not _check(second is Node2D, "created depth instance did not resolve to Node2D"):
        \t\treturn
        \tif not _check(second.position == Vector2(30, 20), "instance_create_depth lost x/y"):
        \t\treturn
        \tif not _check(second.depth == -12 and second.z_index == 12, "instance_create_depth lost depth"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_number(enemy_selector) == 2, "object selector count is wrong"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_number(parent_selector) == 2, "parent selector count is wrong"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_exists(raw_a), "raw instance id did not resolve"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_find(parent_selector, 1).index == handle_b.index, "parent find order is wrong"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_id_get(0).index == handle_a.index, "instance_id_get order is wrong"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_nearest(0, 20, enemy_selector).index == handle_a.index, "nearest picked the wrong instance"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_furthest(0, 20, enemy_selector).index == handle_b.index, "furthest picked the wrong instance"):
        \t\treturn

        \tGMRuntime.gml_selector_set(enemy_selector, "hp", 7, self, null)
        \tif not _check(first.hp == 7 and second.hp == 7, "object selector write did not update every child instance"):
        \t\treturn
        \tif not _check(GMRuntime.gml_selector_get(enemy_selector, "hp", self, null) == 7, "object selector read did not return first matching value"):
        \t\treturn
        \tGMRuntime.gml_selector_set(parent_selector, "hp", 9, self, null)
        \tif not _check(first.hp == 9 and second.hp == 9, "parent selector write did not update inherited child instances"):
        \t\treturn
        \tGMRuntime.gml_variable_instance_set(parent_selector, "hp", 13)
        \tif not _check(first.hp == 13 and second.hp == 13, "variable_instance_set did not update parent selector matches"):
        \t\treturn
        \tif not _check(GMRuntime.gml_variable_instance_get(parent_selector, "hp") == 13, "variable_instance_get did not read parent selector match"):
        \t\treturn
        \tif not _check(GMRuntime.gml_variable_instance_exists(parent_selector, "hp"), "variable_instance_exists did not inspect parent selector matches"):
        \t\treturn
        \tif not _check(GMRuntime.gml_variable_instance_get_names(parent_selector).has("hp"), "variable_instance_get_names did not inspect parent selector matches"):
        \t\treturn
        \tif not _check(GMRuntime.gml_variable_instance_names_count(parent_selector) > 0, "variable_instance_names_count did not inspect parent selector matches"):
        \t\treturn
        \tGMRuntime.gml_selector_set(handle_b, "hp", 11, self, null)
        \tif not _check(first.hp == 13 and second.hp == 11, "handle selector write affected the wrong instances"):
        \t\treturn
        \tGMRuntime.gml_selector_set(raw_a, "hp", 5, self, null)
        \tif not _check(first.hp == 5 and second.hp == 11, "raw instance id selector write affected the wrong instances"):
        \t\treturn

        \tGMRuntime.gml_instance_destroy(handle_a)
        \tif not _check(not GMRuntime.gml_instance_exists(raw_a), "destroyed raw instance id still exists"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_number(enemy_selector) == 1, "destroyed instance still counted"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_find(enemy_selector, 0).index == handle_b.index, "remaining instance find is wrong"):
        \t\treturn
        \tif not _check(GMRuntime.gml_instance_find(enemy_selector, 1).index == GMRuntime.GML_INSTANCE_INVALID_INDEX, "missing find did not return noone"):
        \t\treturn

        \tprint("INSTANCE_SMOKE_OK")
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


class TestInstanceRegistryGodotSmoke(unittest.TestCase):
    def test_generated_instance_registry_smoke_scene(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="InstanceSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_object(
                project_dir,
                "o_parent",
                generate_script_content(
                    [],
                    instance_variables=["hp"],
                    object_runtime=ObjectRuntimeConfig(object_name="o_parent"),
                ),
            )
            _write_object(
                project_dir,
                "o_enemy",
                generate_script_content(
                    [],
                    object_runtime=ObjectRuntimeConfig(
                        object_name="o_enemy",
                        parent_object_names=("o_parent",),
                        inherit_ready=True,
                        inherit_exit_tree=True,
                    ),
                    base_script_path="res://objects/o_parent/o_parent.gd",
                ),
            )
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
        self.assertIn("INSTANCE_SMOKE_OK", output)
