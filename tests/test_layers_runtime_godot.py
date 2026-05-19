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

        func _layer(name, depth):
        \tvar node = Node2D.new()
        \tnode.name = name
        \tnode.z_index = -depth
        \tnode.set_meta("gamemaker_layer_name", name)
        \tnode.set_meta("gamemaker_layer_node_name", name)
        \tnode.set_meta("gamemaker_layer_depth", depth)
        \tnode.set_meta("gamemaker_layer_type", "GMRInstanceLayer")
        \tadd_child(node)
        \treturn node

        func _ready():
        \tvar instances = _layer("Instances", 100)
        \t_layer("Background", 200)
        \tGMRuntime.gml_layer_register_scene(self)

        \tvar layer_id = GMRuntime.gml_layer_get_id("Instances")
        \tif not _check(GMRuntime.gml_handle_is_valid(layer_id), "layer_get_id returned invalid handle"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_exists(layer_id), "layer_exists missed registered layer"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_name(layer_id) == "Instances", "layer_get_name mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_depth(layer_id) == 100, "layer_get_depth mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_depth(layer_id, 50), "layer_depth returned false"):
        \t\treturn
        \tif not _check(instances.z_index == -50 and GMRuntime.gml_layer_get_depth(layer_id) == 50, "layer_depth did not update z"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_id_at_depth(50).index == layer_id.index, "layer_get_id_at_depth mismatch"):
        \t\treturn

        \tvar fx = GMRuntime.gml_layer_create(25, "Effects")
        \tif not _check(GMRuntime.gml_handle_is_valid(fx), "layer_create returned invalid handle"):
        \t\treturn
        \tvar fx_node = GMRuntime.gml_handle_resolve(fx)
        \tif not _check(fx_node is Node2D and fx_node.get_parent() == self, "runtime layer node mismatch"):
        \t\treturn
        \tvar all_layers = GMRuntime.gml_layer_get_all()
        \tif not _check(all_layers.size() == 3 and all_layers[0].index == fx.index, "layer_get_all ordering mismatch"):
        \t\treturn

        \tvar enemy_selector = GMRuntime.gml_asset_get_index("o_enemy")
        \tvar enemy = GMRuntime.gml_instance_create_layer(4, 5, fx, enemy_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(enemy), "instance_create_layer with handle failed"):
        \t\treturn
        \tvar enemy_node = GMRuntime.gml_handle_resolve(enemy)
        \tif not _check(enemy_node.get_parent() == fx_node, "instance_create_layer ignored layer handle"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_add_instance(layer_id, enemy), "layer_add_instance returned false"):
        \t\treturn
        \tif not _check(enemy_node.get_parent() == instances, "layer_add_instance did not move instance"):
        \t\treturn

        \tvar sprite_element = Node2D.new()
        \tsprite_element.name = "spr_player"
        \tsprite_element.set_meta("gamemaker_asset_name", "spr_player")
        \tsprite_element.set_meta("gamemaker_asset_type", "GMRSpriteGraphic")
        \tinstances.add_child(sprite_element)
        \tvar elements = GMRuntime.gml_layer_get_all_elements(layer_id)
        \tif not _check(elements.size() == 2, "layer_get_all_elements count mismatch"):
        \t\treturn
        \tvar element_types = [
        \t\tGMRuntime.gml_layer_get_element_type(elements[0]),
        \t\tGMRuntime.gml_layer_get_element_type(elements[1]),
        \t]
        \tif not _check(element_types.has("instance") and element_types.has("sprite"), "layer element type mismatch: " + str(element_types)):
        \t\treturn

        \tvar particles = GMRuntime.gml_part_system_create_layer(fx, false)
        \tvar particle_record = GMRuntime.gml_handle_resolve(particles)
        \tif not _check(particle_record["node"].get_parent() == fx_node, "particle layer resolver ignored layer handle"):
        \t\treturn

        \tif not _check(GMRuntime.gml_layer_destroy(fx), "layer_destroy returned false"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(fx), "layer_destroy did not invalidate handle"):
        \t\treturn

        \tprint("LAYERS_RUNTIME_SMOKE_OK")
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


class TestLayersRuntimeGodotSmoke(unittest.TestCase):
    def test_layer_registry_runtime_smoke_scene(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="LayerSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_object(
                project_dir,
                "o_enemy",
                generate_script_content(
                    [],
                    object_runtime=ObjectRuntimeConfig(object_name="o_enemy"),
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
        self.assertIn("LAYERS_RUNTIME_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
