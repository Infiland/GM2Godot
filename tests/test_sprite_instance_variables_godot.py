"""Godot checks for sprite_width, sprite_height, sprite_xoffset and sprite_yoffset.

GameMaker computes these read-only instance variables from the instance's
sprite: its size and origin times image_xscale or image_yscale, or 0 when the
instance has no sprite.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    run_headless_scene,
    write_fixture_text as _write_text,
)

_SMOKE_SCENE = textwrap.dedent(
    """\
    [gd_scene load_steps=2 format=3]

    [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

    [node name="Smoke" type="Node2D"]
    script = ExtResource("smoke_script")
    """
)

# A 32x24 sprite with its origin at (8, 6), laid out as the sprite converter
# writes it (the GameMaker origin as metadata on the root), and an instance
# with the members a converted object declares.
_SMOKE_SCRIPT = textwrap.dedent(
    """\
    extends Node2D

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    class Instance extends Node2D:
    \tvar sprite_index = -1
    \tvar image_xscale = 1.0
    \tvar image_yscale = 1.0

    func _sprite_scene():
    \tvar root = Node2D.new()
    \troot.set_meta("gamemaker_origin_x", 8)
    \troot.set_meta("gamemaker_origin_y", 6)
    \tvar visual = Sprite2D.new()
    \tvisual.name = "Sprite2D"
    \tvisual.centered = false
    \tvisual.texture = ImageTexture.create_from_image(Image.create(32, 24, false, Image.FORMAT_RGBA8))
    \troot.add_child(visual)
    \tvisual.owner = root
    \tvar scene = PackedScene.new()
    \tscene.pack(root)
    \troot.free()
    \treturn scene

    func _probe():
    __PROBE__

    func _ready():
    \tGMRuntime.gml_asset_registry_set([
    \t\t{
    \t\t\t"id": 1,
    \t\t\t"name": "spr_box",
    \t\t\t"kind": "sprites",
    \t\t\t"type": "sprite",
    \t\t\t"type_name": "Sprite",
    \t\t\t"source_path": "sprites/spr_box/spr_box.yy",
    \t\t\t"godot_path": "",
    \t\t\t"legacy_id": "sprites/spr_box/spr_box.yy",
    \t\t\t"tags": [],
    \t\t\t"dynamic": false,
    \t\t\t"metadata": {},
    \t\t\t"resource": _sprite_scene(),
    \t\t}
    \t])
    \tvar boxed = Instance.new()
    \tboxed.sprite_index = GMRuntime.gml_asset_get_index("spr_box")
    \tadd_child(boxed)
    \tvar plain = Instance.new()
    \tadd_child(plain)
    \tGMRuntime.gml_variable_global_set("boxed", boxed)
    \tGMRuntime.gml_variable_global_set("plain", plain)
    \tvar results = _probe()
    \tvar expected = [32, 24, 8, 6, -64, 12, -16, 3, 64, 0, 0, 0, 0]
    \tvar failures = []
    \tfor index in expected.size():
    \t\tif typeof(results[index]) not in [TYPE_INT, TYPE_FLOAT] or abs(float(results[index]) - float(expected[index])) > 0.0001:
    \t\t\tfailures.append("result %d: expected %s, got %s" % [index, str(expected[index]), str(results[index])])
    \tif failures.is_empty():
    \t\tprint("SPRITE_INSTANCE_VARIABLES_OK")
    \t\tget_tree().quit(0)
    \t\treturn
    \tfor failure in failures:
    \t\tprint("FAIL " + failure)
    \tget_tree().quit(1)
    """
)

_PROBE_GML = """\
var _boxed = global.boxed;
var _result = [_boxed.sprite_width, _boxed.sprite_height, _boxed.sprite_xoffset, _boxed.sprite_yoffset];
with (_boxed) {
    image_xscale = -2;
    image_yscale = 0.5;
    array_push(_result, sprite_width, sprite_height, sprite_xoffset, sprite_yoffset);
}
array_push(_result, variable_instance_get(_boxed, "sprite_width") * -1);
_boxed.sprite_index = -1;
array_push(_result, _boxed.sprite_width, _boxed.sprite_yoffset);
var _plain = global.plain;
array_push(_result, _plain.sprite_height, _plain.sprite_xoffset);
return _result;
"""


class TestSpriteInstanceVariablesGodot(unittest.TestCase):
    def test_sprite_size_and_origin_variables_follow_the_sprite_and_scale(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        probe = transpile_gml_code(
            _PROBE_GML,
            indent="\t",
            return_depth=1,
            other_expression="self",
        )
        script = _SMOKE_SCRIPT.replace("__PROBE__", probe)
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", script)
            _write_text(project_dir / "smoke.tscn", _SMOKE_SCENE)
            result = run_headless_scene(godot_binary, project_dir, "smoke.tscn", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SPRITE_INSTANCE_VARIABLES_OK", result.stdout)
        self.assertNotIn("SCRIPT ERROR", result.stdout)


if __name__ == "__main__":
    unittest.main()
