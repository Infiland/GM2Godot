from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import (
    AssetRegistryEntry,
    render_asset_registry_script,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.path_registry import (
    PathPoint,
    PathRegistryEntry,
    render_path_registry_script,
)
from src.conversion.script_generator import ObjectRuntimeConfig, generate_script_content
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)


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
            godot_path="res://paths/path_patrol/path_patrol.tscn",
            legacy_id="paths/path_patrol/path_patrol.yy",
        ),
    )
    path_entries = (
        PathRegistryEntry(
            id=path_id,
            name="path_patrol",
            closed=False,
            kind=0,
            precision=4,
            godot_path="res://paths/path_patrol/path_patrol.tscn",
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


# Synthetic paths and what GameMaker's yyPath.js computes for them (lengths,
# internal point counts and GetPosition samples [pos, x, y, speed factor]),
# taken by running the HTML5 runner's yyPath.js under Node.
_GEOMETRY_PATHS = (
    PathRegistryEntry(
        id=301, name="pth_smooth_open", closed=False, kind=1, precision=4, godot_path="",
        points=(PathPoint(0, 0, 100), PathPoint(64, 0, 50), PathPoint(64, 64, 200), PathPoint(0, 64, 100)),
    ),
    PathRegistryEntry(
        id=302, name="pth_smooth_closed", closed=True, kind=1, precision=3, godot_path="",
        points=(PathPoint(0, 0, 100), PathPoint(100, 0, 100), PathPoint(100, 100, 100)),
    ),
    PathRegistryEntry(
        id=303, name="pth_straight_closed", closed=True, kind=0, precision=4, godot_path="",
        points=(PathPoint(0, 0, 100), PathPoint(30, 0, 50), PathPoint(30, 40, 100)),
    ),
    PathRegistryEntry(
        id=304, name="pth_smooth_flat", closed=False, kind=1, precision=0, godot_path="",
        points=(PathPoint(0, 0, 100), PathPoint(50, 50, 100), PathPoint(100, 0, 100)),
    ),
)
_GEOMETRY_POSITIONS = (0.0, 0.1, 0.25, 0.5, 0.77, 1.0)
_GEOMETRY_EXPECTED: dict[str, tuple[float, list[tuple[float, float, float]]]] = {
    "pth_smooth_open": (167.83710758768837, [
        (0, 0, 100),
        (16.7836088784623, 0.05847947344411951, 87.02486682958599),
        (41.89892706354746, 0.9442457525087887, 69.47953921404603),
        (63.875, 32, 124.951171875),
        (38.587839814986566, 63.594361398449664, 159.34278423853291),
        (0, 64, 100),
    ]),
    "pth_smooth_closed": (234.3968047304862, [
        (61.71875, 0.78125, 100),
        (83.29196747128637, 9.227085811000508, 100),
        (99.21875, 39.3391007315086, 100),
        (71.82493351402685, 68.7114873184822, 100),
        (28.52886466735191, 23.136251890145175, 100),
        (61.71875, 0.78125, 100),
    ]),
    "pth_straight_closed": (120, [
        (0, 0, 100),
        (12, 0, 80),
        (30, 0, 50),
        (30, 30, 87.5),
        (16.559999999999995, 22.079999999999995, 100),
        (0, 0, 100),
    ]),
    "pth_smooth_flat": (100, [
        (0, 0, 100),
        (10, 0, 100),
        (25, 0, 100),
        (50, 0, 100),
        (77, 0, 100),
        (100, 0, 100),
    ]),
}

_GEOMETRY_SCRIPT = """extends Node2D

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

func _ready():
\tvar result = {}
\tfor name in NAMES:
\t\tvar path = GMRuntime.gml_asset_get_index(name)
\t\tvar samples = []
\t\tfor pos in POSITIONS:
\t\t\tsamples.append([GMRuntime.gml_path_get_x(path, pos), GMRuntime.gml_path_get_y(path, pos), GMRuntime.gml_path_get_speed(path, pos)])
\t\tvar points = []
\t\tfor n in range(-1, GMRuntime.gml_path_get_number(path) + 1):
\t\t\tpoints.append([GMRuntime.gml_path_get_point_x(path, n), GMRuntime.gml_path_get_point_y(path, n), GMRuntime.gml_path_get_point_speed(path, n)])
\t\tresult[name] = {
\t\t\t"exists": GMRuntime.gml_path_exists(path),
\t\t\t"name": GMRuntime.gml_path_get_name(path),
\t\t\t"length": GMRuntime.gml_path_get_length(path),
\t\t\t"kind": GMRuntime.gml_path_get_kind(path),
\t\t\t"closed": GMRuntime.gml_path_get_closed(path),
\t\t\t"precision": GMRuntime.gml_path_get_precision(path),
\t\t\t"samples": samples,
\t\t\t"points": points,
\t\t}
\t# A path that does not exist.
\tresult["missing"] = [
\t\tGMRuntime.gml_path_exists(-1), GMRuntime.gml_path_exists(GMRuntime.gml_undefined()), GMRuntime.gml_path_get_name(999),
\t\tGMRuntime.gml_path_get_length(999), GMRuntime.gml_path_get_kind(999), GMRuntime.gml_path_get_closed(999),
\t\tGMRuntime.gml_path_get_precision(999), GMRuntime.gml_path_get_number(999), GMRuntime.gml_path_get_point_x(999, 0),
\t\tGMRuntime.gml_path_get_x(999, 0.5), GMRuntime.gml_path_get_y(999, 0.5), GMRuntime.gml_path_get_speed(999, 0.5),
\t]
\tprint("PATH_GEOMETRY " + JSON.stringify(result))
\tget_tree().quit(0)
"""


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

    def test_paths_are_built_and_sampled_like_gamemaker(self) -> None:
        # Smooth paths subdivide each corner up to their precision, closed
        # paths run back to their first point, and positions along a path
        # interpolate x, y and the speed factor by distance.
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        names = [entry.name for entry in _GEOMETRY_PATHS]
        script = _GEOMETRY_SCRIPT.replace("NAMES", json.dumps(names)).replace(
            "POSITIONS", json.dumps(list(_GEOMETRY_POSITIONS))
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="PathGeometry"\nrun/main_scene="res://geometry.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            asset_entries = tuple(
                AssetRegistryEntry(
                    id=entry.id,
                    name=entry.name,
                    kind="paths",
                    asset_type="path",
                    type_name="Path",
                    source_path=f"paths/{entry.name}/{entry.name}.yy",
                    godot_path="",
                    legacy_id=f"paths/{entry.name}/{entry.name}.yy",
                )
                for entry in _GEOMETRY_PATHS
            )
            _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(asset_entries))
            _write_text(project_dir / "gm2godot" / "gml_path_registry.gd", render_path_registry_script(_GEOMETRY_PATHS))
            _write_text(project_dir / "geometry.gd", script)
            _write_text(
                project_dir / "geometry.tscn",
                '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://geometry.gd" id="1"]\n\n'
                '[node name="Geometry" type="Node2D"]\nscript = ExtResource("1")\n',
            )
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "--scene", "res://geometry.tscn", "--quit-after", "10"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=dict(os.environ, HOME=str(project_dir)),
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("ERROR", output)
        lines = [line for line in output.splitlines() if line.startswith("PATH_GEOMETRY ")]
        self.assertEqual(len(lines), 1, output)
        geometry = json.loads(lines[0].removeprefix("PATH_GEOMETRY "))
        for entry in _GEOMETRY_PATHS:
            with self.subTest(path=entry.name):
                actual = geometry[entry.name]
                length, samples = _GEOMETRY_EXPECTED[entry.name]
                self.assertTrue(actual["exists"])
                self.assertEqual(actual["name"], entry.name)
                self.assertEqual((actual["kind"], actual["closed"], actual["precision"]), (entry.kind, entry.closed, entry.precision))
                self.assertAlmostEqual(actual["length"], length, places=9)
                for position, expected, sample in zip(_GEOMETRY_POSITIONS, samples, actual["samples"], strict=True):
                    for axis, (want, got) in enumerate(zip(expected, sample, strict=True)):
                        self.assertAlmostEqual(got, want, places=9, msg=f"pos {position} axis {axis}")
                # Defining points; 0 for indices outside the path.
                self.assertEqual(
                    actual["points"],
                    [[0, 0, 0]] + [[point.x, point.y, point.speed] for point in entry.points] + [[0, 0, 0]],
                )
        self.assertEqual(geometry["missing"], [False, False, "", 0, 0, True, 8, 0, 0, -1, -1, -1])


if __name__ == "__main__":
    unittest.main()
