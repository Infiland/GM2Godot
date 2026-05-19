from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime


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


class TestParticlesRuntimeGodotSmoke(unittest.TestCase):
    def test_particle_lifecycle_handles_and_nodes_are_cleaned_up(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

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
            \tcall_deferred("_run")

            func _run():
            \tvar effects_layer = Node2D.new()
            \teffects_layer.name = "Effects"
            \tadd_child(effects_layer)
            \tvar ps = GMRuntime.gml_part_system_create_layer("Effects", true)
            \tif not _check(GMRuntime.gml_part_system_exists(ps), "particle system handle invalid"):
            \t\treturn
            \tvar system_record = ps.reference
            \tif not _check(system_record["node"] is Node2D, "particle system node missing"):
            \t\treturn
            \tif not _check(system_record["node"].get_parent() == effects_layer, "particle system node not attached to layer"):
            \t\treturn
            \tif not _check(GMRuntime.gml_part_system_get_layer(ps) == "Effects", "particle system layer mismatch"):
            \t\treturn
            \tGMRuntime.gml_part_system_depth(ps, -1000)
            \tif not _check(system_record["node"].z_index == 1000, "particle system depth mismatch"):
            \t\treturn
            \tGMRuntime.gml_part_system_position(ps, 20, 30)
            \tif not _check(system_record["node"].position == Vector2(20, 30), "particle system position mismatch"):
            \t\treturn

            \tvar pt = GMRuntime.gml_part_type_create()
            \tif not _check(GMRuntime.gml_part_type_exists(pt), "particle type handle invalid"):
            \t\treturn
            \tGMRuntime.gml_part_type_shape(pt, "flare")
            \tGMRuntime.gml_part_type_size(pt, 1, 2, 0.1, 0)
            \tGMRuntime.gml_part_type_scale(pt, 2, 1)
            \tGMRuntime.gml_part_type_life(pt, 30, 60)
            \tGMRuntime.gml_part_type_speed(pt, 0.5, 2, 0, 0)
            \tGMRuntime.gml_part_type_direction(pt, 0, 359, 0, 10)
            \tGMRuntime.gml_part_type_gravity(pt, 0.25, 270)
            \tGMRuntime.gml_part_type_orientation(pt, 0, 90, 0, 0, true)
            \tGMRuntime.gml_part_type_colour3(pt, 0x0000ff, 0xffffff, 0x00ffff)
            \tGMRuntime.gml_part_type_alpha3(pt, 1, 0.5, 0)
            \tGMRuntime.gml_part_type_blend(pt, true)
            \tif not _check(pt.reference["shape"] == "flare" and pt.reference["life_max"] == 60, "particle type properties not stored"):
            \t\treturn
            \tvar pe = GMRuntime.gml_part_emitter_create(ps)
            \tif not _check(GMRuntime.gml_part_emitter_exists(ps, pe), "particle emitter handle invalid"):
            \t\treturn
            \tvar emitter_node = pe.reference["node"]
            \tif not _check(emitter_node is GPUParticles2D, "emitter node missing"):
            \t\treturn
            \tif not _check(emitter_node.get_parent() == system_record["node"], "emitter node not parented to system"):
            \t\treturn
            \tGMRuntime.gml_part_emitter_region(ps, pe, -10, 10, -5, 5, "ellipse", "linear")
            \tif not _check(emitter_node.position == Vector2(0, 0), "emitter region center mismatch"):
            \t\treturn
            \tif not _check(emitter_node.visibility_rect.size == Vector2(20, 10), "emitter region size mismatch"):
            \t\treturn
            \tGMRuntime.gml_part_emitter_relative(ps, pe, false)

            \tGMRuntime.gml_part_particles_create(ps, 10, 20, pt, 3)
            \tGMRuntime.gml_part_emitter_burst(ps, pe, pt, 4)
            \tif not _check(GMRuntime.gml_part_particles_count(ps) == 7, "particle count mismatch"):
            \t\treturn
            \tif not _check(abs(emitter_node.lifetime - 0.75) < 0.001, "type lifetime not applied to emitter"):
            \t\treturn
            \tif not _check(emitter_node.modulate.r > 0.9 and emitter_node.modulate.a > 0.9, "type colour not applied to emitter"):
            \t\treturn
            \tGMRuntime.gml_part_emitter_stream(ps, pe, pt, 2)
            \tif not _check(emitter_node.emitting, "emitter stream did not start"):
            \t\treturn
            \tGMRuntime.gml_part_emitter_enable(ps, pe, false)
            \tif not _check(not emitter_node.emitting, "disabled emitter kept streaming"):
            \t\treturn
            \tGMRuntime.gml_part_emitter_clear(ps, pe)
            \tif not _check(pe.reference["stream_number"] == 0, "emitter clear did not reset stream"):
            \t\treturn
            \tGMRuntime.gml_part_system_clear(ps)
            \tif not _check(GMRuntime.gml_part_particles_count(ps) == 0, "particle clear failed"):
            \t\treturn

            \tGMRuntime.gml_part_emitter_destroy(ps, pe)
            \tif not _check(not GMRuntime.gml_part_emitter_exists(ps, pe), "emitter handle survived destroy"):
            \t\treturn
            \tGMRuntime.gml_part_type_destroy(pt)
            \tif not _check(not GMRuntime.gml_part_type_exists(pt), "type handle survived destroy"):
            \t\treturn
            \tGMRuntime.gml_part_system_destroy(ps)
            \tif not _check(not GMRuntime.gml_part_system_exists(ps), "system handle survived destroy"):
            \t\treturn
            \tprint("PARTICLES_RUNTIME_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PARTICLES_RUNTIME_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
