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


class TestPhysicsRuntimeGodotSmoke(unittest.TestCase):
    def test_fixture_binding_and_impulse_apply_to_rigidbody2d(self) -> None:
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
            \tGMRuntime.gml_physics_world_create(0.1)
            \tGMRuntime.gml_physics_world_gravity(0, 9.8)
            \tvar gravity = GMRuntime.gml_physics_world_gravity_get()
            \tif not _check(gravity[0] == 0 and abs(gravity[1] - 9.8) < 0.001, "gravity state mismatch"):
            \t\treturn

            \tvar body = RigidBody2D.new()
            \tbody.name = "PhysicsBody"
            \tbody.mass = 1.0
            \tbody.gravity_scale = 0.0
            \tadd_child(body)

            \tvar fixture = GMRuntime.gml_physics_fixture_create()
            \tGMRuntime.gml_physics_fixture_set_box_shape(fixture, 8, 4)
            \tGMRuntime.gml_physics_fixture_set_density(fixture, 1)
            \tGMRuntime.gml_physics_fixture_set_friction(fixture, 0.4)
            \tGMRuntime.gml_physics_fixture_set_restitution(fixture, 0.2)
            \tif not _check(GMRuntime.gml_physics_fixture_bind(fixture, body), "fixture bind failed"):
            \t\treturn
            \tvar shape = body.get_node_or_null("_gm_physics_fixture_" + str(fixture.index))
            \tif not _check(shape is CollisionShape2D, "fixture did not create CollisionShape2D"):
            \t\treturn
            \tif not _check(shape.shape is RectangleShape2D, "fixture did not create rectangle shape"):
            \t\treturn

            \tGMRuntime.gml_physics_apply_impulse(0, 0, 20, 0, body)
            \tawait get_tree().physics_frame
            \tif not _check(body.linear_velocity.x > 0.0, "impulse did not affect body velocity"):
            \t\treturn
            \tGMRuntime.gml_physics_apply_force(0, 0, 5, 0, body)
            \tGMRuntime.gml_physics_apply_angular_impulse(1, body)
            \tGMRuntime.gml_physics_apply_torque(0.5, body)

            \tGMRuntime.gml_physics_fixture_delete(fixture)
            \tprint("PHYSICS_RUNTIME_SMOKE_OK")
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
        self.assertIn("PHYSICS_RUNTIME_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
