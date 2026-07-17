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
        \tnode.set_meta("gamemaker_layer_x", 0)
        \tnode.set_meta("gamemaker_layer_y", 0)
        \tnode.set_meta("gamemaker_layer_hspeed", 0)
        \tnode.set_meta("gamemaker_layer_vspeed", 0)
        \tnode.set_meta("gamemaker_layer_visible", true)
        \tadd_child(node)
        \treturn node

        func _ready():
        \tvar instances = _layer("Instances", 100)
        \tvar background_layer = _layer("Background", 200)
        \tvar background_visual = ColorRect.new()
        \tbackground_visual.name = "BackgroundVisual"
        \tbackground_visual.color = Color(1, 1, 1, 1)
        \tbackground_visual.modulate = Color(1, 1, 1, 1)
        \tbackground_visual.set_meta("gamemaker_layer_element_type", "background")
        \tbackground_visual.set_meta("gamemaker_background_visual", true)
        \tbackground_visual.set_meta("gamemaker_background_visual_type", "color")
        \tbackground_layer.add_child(background_visual)
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
        \tif not _check(GMRuntime.gml_layer_x(layer_id, 8) and GMRuntime.gml_layer_y(layer_id, 16), "layer position setters failed"):
        \t\treturn
        \tif not _check(instances.position == Vector2(8, 16) and GMRuntime.gml_layer_get_x(layer_id) == 8 and GMRuntime.gml_layer_get_y(layer_id) == 16, "layer position getters mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_hspeed(layer_id, 2) and GMRuntime.gml_layer_vspeed(layer_id, -1), "layer speed setters failed"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_hspeed(layer_id) == 2 and GMRuntime.gml_layer_get_vspeed(layer_id) == -1, "layer speed getters mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_set_visible(layer_id, false) and not GMRuntime.gml_layer_get_visible(layer_id), "layer visibility setters failed"):
        \t\treturn
        \tif not _check(not instances.visible, "layer_set_visible did not update CanvasItem visibility"):
        \t\treturn
        \tGMRuntime.gml_layer_set_visible(layer_id, true)
        \tif not _check(GMRuntime.gml_layer_get_id_at_depth(50).index == layer_id.index, "layer_get_id_at_depth mismatch"):
        \t\treturn
        \tvar background_id = GMRuntime.gml_layer_background_get_id("Background")
        \tif not _check(GMRuntime.gml_handle_is_valid(background_id), "background get id invalid"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_element_type(background_id) == "background", "background element type mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_background_alpha(background_id, 0.25), "background alpha returned false"):
        \t\treturn
        \tif not _check(is_equal_approx(background_visual.modulate.a, 0.25), "background alpha mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_background_blend(background_id, 255), "background blend returned false"):
        \t\treturn
        \tif not _check(is_equal_approx(background_visual.modulate.r, 1.0) and is_equal_approx(background_visual.modulate.g, 0.0) and is_equal_approx(background_visual.modulate.b, 0.0), "background blend mismatch"):
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
        \tif not _check(GMRuntime.gml_layer_element_move(elements[1], fx), "layer_element_move returned false"):
        \t\treturn
        \tif not _check(sprite_element.get_parent() == fx_node, "layer_element_move did not reparent element"):
        \t\treturn

        \tvar image = Image.create(32, 16, false, Image.FORMAT_RGBA8)
        \tfor tile_offset in [0, 16]:
        \t\timage.fill_rect(Rect2i(tile_offset, 0, 8, 8), Color(1, 0, 0, 1))
        \t\timage.fill_rect(Rect2i(tile_offset + 8, 0, 8, 8), Color(0, 1, 0, 1))
        \t\timage.fill_rect(Rect2i(tile_offset, 8, 8, 8), Color(0, 0, 1, 1))
        \t\timage.fill_rect(Rect2i(tile_offset + 8, 8, 8, 8), Color(1, 1, 0, 1))
        \tvar texture = ImageTexture.create_from_image(image)
        \tvar atlas = TileSetAtlasSource.new()
        \tatlas.texture = texture
        \tatlas.texture_region_size = Vector2i(16, 16)
        \tatlas.create_tile(Vector2i(0, 0))
        \tatlas.create_tile(Vector2i(1, 0))
        \tvar tile_set = TileSet.new()
        \ttile_set.tile_size = Vector2i(16, 16)
        \ttile_set.add_source(atlas, 0)
        \ttile_set.set_meta("gamemaker_tileset_out_columns", 2)
        \tvar tile_set_id = GMRuntime.gml_asset_register_dynamic("ts_runtime", "tileset", tile_set)
        \tif not _check(not GMRuntime.gml_handle_is_valid(GMRuntime.gml_layer_tilemap_create(fx, 0, 0, -999, 1, 1)), "invalid tileset created a tilemap"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(GMRuntime.gml_layer_tilemap_create(fx, 0, 0, tile_set_id, 0, 1)), "zero-width tilemap was accepted"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(GMRuntime.gml_layer_tilemap_create("MissingLayer", 0, 0, tile_set_id, 1, 1)), "missing layer created a tilemap"):
        \t\treturn
        \tvar tilemap = GMRuntime.gml_layer_tilemap_create(fx, 3, 4, tile_set_id, 4, 2)
        \tif not _check(GMRuntime.gml_handle_is_valid(tilemap), "layer_tilemap_create returned invalid handle"):
        \t\treturn
        \tvar tilemap_node = GMRuntime.gml_handle_resolve(tilemap)
        \tif not _check(tilemap_node is TileMapLayer and tilemap_node.get_parent() == fx_node, "runtime tilemap node mismatch"):
        \t\treturn
        \tif not _check(tilemap_node.position == Vector2(3, 4) and tilemap_node.tile_set == tile_set, "runtime tilemap properties mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_element_type(tilemap) == "tilemap", "runtime tilemap element type mismatch"):
        \t\treturn
        \tvar found_tilemap = GMRuntime.gml_layer_tilemap_get_id(fx)
        \tif not _check(GMRuntime.gml_handle_is_valid(found_tilemap) and found_tilemap.index == tilemap.index, "layer_tilemap_get_id mismatch"):
        \t\treturn
        \tvar named_tilemap = GMRuntime.gml_layer_tilemap_get_id("Effects")
        \tif not _check(GMRuntime.gml_handle_is_valid(named_tilemap) and named_tilemap.index == tilemap.index, "named layer tilemap lookup mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_tilemap_get_width(tilemap) == 4 and GMRuntime.gml_tilemap_get_height(tilemap) == 2, "runtime tilemap dimensions mismatch"):
        \t\treturn
        \tvar gm_transforms = [
        \t\t0,
        \t\tGMRuntime.GML_TILEMAP_MIRROR,
        \t\tGMRuntime.GML_TILEMAP_FLIP,
        \t\tGMRuntime.GML_TILEMAP_MIRROR | GMRuntime.GML_TILEMAP_FLIP,
        \t\tGMRuntime.GML_TILEMAP_ROTATE,
        \t\tGMRuntime.GML_TILEMAP_MIRROR | GMRuntime.GML_TILEMAP_ROTATE,
        \t\tGMRuntime.GML_TILEMAP_FLIP | GMRuntime.GML_TILEMAP_ROTATE,
        \t\tGMRuntime.GML_TILEMAP_MIRROR | GMRuntime.GML_TILEMAP_FLIP | GMRuntime.GML_TILEMAP_ROTATE,
        \t]
        \tvar h = GMRuntime.GML_TILEMAP_GODOT_FLIP_H
        \tvar v = GMRuntime.GML_TILEMAP_GODOT_FLIP_V
        \tvar t = GMRuntime.GML_TILEMAP_GODOT_TRANSPOSE
        \tvar expected_godot_transforms = [0, h, v, h | v, h | t, h | v | t, t, v | t]
        \tfor transform_index in range(gm_transforms.size()):
        \t\tvar coords = Vector2i(transform_index % 4, transform_index / 4)
        \t\tvar tiledata = 1 | gm_transforms[transform_index]
        \t\tif not _check(GMRuntime.gml_tilemap_set(tilemap, tiledata, coords.x, coords.y), "tilemap_set transform failed at " + str(transform_index)):
        \t\t\treturn
        \t\tif not _check(GMRuntime.gml_tilemap_get(tilemap, coords.x, coords.y) == tiledata, "tilemap_get transform mismatch at " + str(transform_index)):
        \t\t\treturn
        \t\tif not _check(tilemap_node.get_cell_alternative_tile(coords) == expected_godot_transforms[transform_index], "tile transform orientation mismatch at " + str(transform_index)):
        \t\t\treturn
        \tif not _check(tilemap_node.get_cell_source_id(Vector2i(0, 0)) == 0 and tilemap_node.get_cell_atlas_coords(Vector2i(0, 0)) == Vector2i(0, 0), "base tile atlas mapping mismatch"):
        \t\treturn
        \t# Authored room metadata preserves every non-rendering/custom tile-data bit.
        \ttilemap_node.set_meta("gamemaker_tile_raw_cells", {})
        \tvar authored_values = []
        \tfor transform_index in range(gm_transforms.size()):
        \t\tauthored_values.append(1 | gm_transforms[transform_index] | (1 << 20))
        \ttilemap_node.set_meta("gamemaker_tile_raw_values", authored_values)
        \tfor transform_index in range(gm_transforms.size()):
        \t\tvar coords = Vector2i(transform_index % 4, transform_index / 4)
        \t\tif not _check(GMRuntime.gml_tilemap_get(tilemap, coords.x, coords.y) == authored_values[transform_index], "authored raw tile data mismatch at " + str(transform_index)):
        \t\t\treturn
        \t# Verify inverse decoding independently of either raw-value cache.
        \ttilemap_node.remove_meta("gamemaker_tile_raw_values")
        \tfor transform_index in range(gm_transforms.size()):
        \t\tvar coords = Vector2i(transform_index % 4, transform_index / 4)
        \t\tvar tiledata = 1 | gm_transforms[transform_index]
        \t\tif not _check(GMRuntime.gml_tilemap_get(tilemap, coords.x, coords.y) == tiledata, "tilemap inverse transform mismatch at " + str(transform_index)):
        \t\t\treturn
        \tvar custom_bit = 1 << 20
        \tif not _check(GMRuntime.gml_tilemap_set(tilemap, custom_bit, 0, 0), "custom-only tile data was rejected"):
        \t\treturn
        \tif not _check(tilemap_node.get_cell_source_id(Vector2i(0, 0)) == -1, "custom-only empty tile was drawn"):
        \t\treturn
        \tif not _check(GMRuntime.gml_tilemap_get(tilemap, 0, 0) == custom_bit, "custom-only tile data did not round-trip"):
        \t\treturn
        \tif not _check(GMRuntime.gml_tilemap_set(tilemap, 0, 0, 0) and GMRuntime.gml_tilemap_get(tilemap, 0, 0) == 0, "empty tile semantics mismatch"):
        \t\treturn
        \tif not _check(tilemap_node.get_cell_source_id(Vector2i(0, 0)) == -1, "empty tile was not erased"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_tilemap_set(tilemap, 1, -1, 0) and GMRuntime.gml_tilemap_get(tilemap, 4, 0) == -1, "tilemap bounds semantics mismatch"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_tilemap_set(tilemap, 99, 0, 0), "nonexistent atlas tile was accepted"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_tilemap_set(-999, 1, 0, 0) and GMRuntime.gml_tilemap_get(-999, 0, 0) == -1, "invalid tilemap handle semantics mismatch"):
        \t\treturn

        \t# Atlas-grid fallback must account for margins and separation.
        \tvar spaced_image = Image.create(48, 44, false, Image.FORMAT_RGBA8)
        \tspaced_image.fill(Color.WHITE)
        \tvar spaced_atlas = TileSetAtlasSource.new()
        \tspaced_atlas.texture = ImageTexture.create_from_image(spaced_image)
        \tspaced_atlas.texture_region_size = Vector2i(16, 16)
        \tspaced_atlas.margins = Vector2i(8, 4)
        \tspaced_atlas.separation = Vector2i(8, 8)
        \tif not _check(spaced_atlas.get_atlas_grid_size() == Vector2i(2, 2), "spaced atlas fixture grid mismatch"):
        \t\treturn
        \tfor atlas_y in range(2):
        \t\tfor atlas_x in range(2):
        \t\t\tspaced_atlas.create_tile(Vector2i(atlas_x, atlas_y))
        \tvar spaced_tile_set = TileSet.new()
        \tspaced_tile_set.tile_size = Vector2i(16, 16)
        \tspaced_tile_set.add_source(spaced_atlas, 0)
        \tvar spaced_id = GMRuntime.gml_asset_register_dynamic("ts_spaced", "tileset", spaced_tile_set)
        \tvar spaced_tilemap = GMRuntime.gml_layer_tilemap_create(fx, 0, 0, spaced_id, 1, 1)
        \tif not _check(GMRuntime.gml_tilemap_set(spaced_tilemap, 3, 0, 0), "spaced atlas tilemap_set failed"):
        \t\treturn
        \tvar spaced_node = GMRuntime.gml_handle_resolve(spaced_tilemap)
        \tif not _check(spaced_node.get_cell_atlas_coords(Vector2i.ZERO) == Vector2i(0, 1), "atlas grid fallback ignored margins/separation"):
        \t\treturn
        \tif not _check(spaced_tile_set.has_meta("_gm2godot_tilemap_atlas_layout"), "atlas layout was not cached"):
        \t\treturn

        \tvar particles = GMRuntime.gml_part_system_create_layer(fx, false)
        \tvar particle_record = GMRuntime.gml_handle_resolve(particles)
        \tif not _check(particle_record["node"].get_parent() == fx_node, "particle layer resolver ignored layer handle"):
        \t\treturn

        \tif not _check(GMRuntime.gml_layer_destroy(fx), "layer_destroy returned false"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(fx), "layer_destroy did not invalidate handle"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(tilemap), "layer_destroy did not invalidate tilemap handle"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(spaced_tilemap), "layer_destroy did not invalidate spaced tilemap handle"):
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
