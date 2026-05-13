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
from src.conversion.path_registry import PathPoint, PathRegistryEntry, render_path_registry_script
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


def _write_object(project_dir: Path, name: str) -> None:
    object_dir = project_dir / "objects" / name
    _write_text(
        object_dir / f"{name}.gd",
        generate_script_content(
            [{"eventType": 7, "eventNum": 8}],
            code_bodies={"_on_path_ended": "\tpath_done = true"},
            instance_variables={"path_done"},
            object_runtime=ObjectRuntimeConfig(object_name=name),
        ),
    )
    _write_text(object_dir / f"{name}.tscn", _object_scene(name))


def _write_registries(project_dir: Path) -> int:
    path_id = 200
    asset_entries = (
        AssetRegistryEntry(
            id=100,
            name="o_runner",
            kind="objects",
            asset_type="object",
            type_name="Object",
            source_path="objects/o_runner/o_runner.yy",
            godot_path="res://objects/o_runner/o_runner.tscn",
            legacy_id="objects/o_runner/o_runner.yy",
        ),
        AssetRegistryEntry(
            id=path_id,
            name="path_patrol",
            kind="paths",
            asset_type="path",
            type_name="Path",
            source_path="paths/path_patrol/path_patrol.yy",
            godot_path="",
            legacy_id="paths/path_patrol/path_patrol.yy",
        ),
    )
    path_entries = (
        PathRegistryEntry(
            id=path_id,
            name="path_patrol",
            closed=False,
            precision=4,
            points=(PathPoint(0, 0), PathPoint(20, 0)),
        ),
    )
    _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(asset_entries))
    _write_text(project_dir / "gm2godot" / "gml_path_registry.gd", render_path_registry_script(path_entries))
    return path_id


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

        \tvar runner_selector = GMRuntime.gml_asset_get_index("o_runner")
        \tvar path_selector = GMRuntime.gml_asset_get_index("path_patrol")
        \tvar runner_handle = GMRuntime.gml_instance_create_layer(0, 0, "Instances", runner_selector, self)
        \tif not _check(GMRuntime.gml_handle_is_valid(runner_handle), "runner was not created"):
        \t\treturn
        \tvar runner = GMRuntime.gml_handle_resolve(runner_handle)
        \tif not _check(_near(GMRuntime.gml_path_get_length(path_selector), 20), "generated path length was wrong"):
        \t\treturn

        \trunner.path_done = false
        \tGMRuntime.gml_path_start(runner, path_selector, 10, 0, true)
        \tGMRuntime.gml_path_step(runner)
        \tif not _check(_near(runner.position.x, 10) and _near(runner.path_position, 0.5), "path_start did not advance halfway"):
        \t\treturn
        \tGMRuntime.gml_path_step(runner)
        \tif not _check(_near(runner.position.x, 20) and runner.path_done, "path completion did not dispatch Path Ended"):
        \t\treturn
        \tif not _check(GMRuntime.is_undefined(runner.path_index), "path_end state was not cleared"):
        \t\treturn

        \tvar grid = GMRuntime.gml_mp_grid_create(0, 0, 4, 4, 10, 10)
        \tGMRuntime.gml_mp_grid_add_cell(grid, 1, 0)
        \tif not _check(GMRuntime.gml_mp_grid_path(grid, path_selector, 0, 0, 30, 0, false), "mp_grid_path did not find route"):
        \t\treturn
        \tif not _check(_near(GMRuntime.gml_path_get_length(path_selector), 50), "mp_grid_path wrote wrong route length"):
        \t\treturn
        \tGMRuntime.gml_path_start(runner, path_selector, 10, 0, true)
        \tif not _check(runner.position == Vector2(5, 5), "dynamic mp_grid path did not start at cell center"):
        \t\treturn

        \tprint("PATHS_SMOKE_OK")
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


class TestPathsMotionGodotSmoke(unittest.TestCase):
    def test_runtime_paths_and_mp_grid_smoke_scene(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="PathsSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registries(project_dir)
            _write_object(project_dir, "o_runner")
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
        self.assertIn("PATHS_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
