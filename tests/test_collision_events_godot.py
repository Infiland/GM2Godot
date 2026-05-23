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


def _write_smoke_scene(project_dir: Path) -> None:
    probe_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var id = GMRuntime.gml_instance_noone()
        var other = GMRuntime.gml_instance_noone()
        var object_name = ""
        var parent_names = []
        var solid = false
        var trace = []
        var xprevious = 0.0
        var yprevious = 0.0

        func configure(instance_name, gm_object_name, gm_parent_names, is_solid, trace_ref, world_position):
        \tname = str(instance_name)
        \tobject_name = str(gm_object_name)
        \tparent_names = gm_parent_names
        \tsolid = bool(is_solid)
        \ttrace = trace_ref
        \tglobal_position = world_position
        \txprevious = world_position.x
        \typrevious = world_position.y

        func _ready():
        \t_ensure_collision_shape()
        \tid = GMRuntime.gml_instance_register(self, object_name, parent_names)

        func _exit_tree():
        \tGMRuntime.gml_instance_unregister(id)

        func _ensure_collision_shape():
        \tif get_child_count() > 0:
        \t\treturn
        \tvar shape_node = CollisionShape2D.new()
        \tvar rect = RectangleShape2D.new()
        \trect.size = Vector2(16, 16)
        \tshape_node.shape = rect
        \tadd_child(shape_node)

        func _gm_collision_event_bindings():
        \tif object_name != "o_player":
        \t\treturn []
        \treturn [
        \t\t{"target_object": "o_wall_parent", "method": "_on_collision_o_wall_parent"},
        \t]

        func _on_collision_o_wall_parent():
        \ttrace.append(name + ":hit:" + str(other.name) + ":x=" + str(int(global_position.x)))
        \tGMRuntime.gml_instance_destroy(other)
        """
    )
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const CollisionProbe = preload("res://collision_probe.gd")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _ready():
        \tvar trace = []
        \tvar player = CollisionProbe.new()
        \tplayer.configure("Player", "o_player", [], false, trace, Vector2(20, 0))
        \tplayer.xprevious = 0
        \tplayer.yprevious = 0
        \tadd_child(player)
        \tvar wall = CollisionProbe.new()
        \twall.configure("Wall", "o_wall_child", ["o_wall_parent"], true, trace, Vector2(20, 0))
        \tadd_child(wall)

        \tGMRuntime.gml_collision_event_trace_clear()
        \tvar dispatched = GMRuntime.gml_collision_event_dispatch_frame([player, wall], 7)
        \tif not _check(dispatched == 1, "collision dispatch count mismatch: " + str(dispatched)):
        \t\treturn
        \tif not _check(trace == ["Player:hit:Wall:x=0"], "collision trace mismatch: " + str(trace)):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(wall.id), "destroyed collision other handle remained valid"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_handle_is_valid(player.other), "other was not restored after dispatch"):
        \t\treturn
        \tvar runtime_trace = GMRuntime.gml_collision_event_trace()
        \tif not _check(runtime_trace[0]["event"] == "solid_rollback", "solid rollback trace missing"):
        \t\treturn
        \tif not _check(runtime_trace[1]["method"] == "_on_collision_o_wall_parent", "collision method trace missing"):
        \t\treturn
        \tprint("COLLISION_EVENT_SMOKE_OK")
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
    _write_text(project_dir / "collision_probe.gd", probe_script)
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestCollisionEventGodotSmoke(unittest.TestCase):
    def test_collision_dispatch_parent_other_solid_and_destroy(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="CollisionEventSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
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
        self.assertIn("COLLISION_EVENT_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
