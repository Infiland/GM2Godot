"""Headless Godot checks that every distinct GameMaker depth draws in order.

GameMaker puts every distinct (integer, truncated) depth on its own layer and
draws layers from the highest depth to the lowest, so two different depths
never tie. Godot draws by z_index first, so the converted room layers and the
runtime's layers, instances and particle systems must give every distinct depth
in use its own z_index, ordered like the depths, even when the depths are far
beyond Godot's -4096..4096 z_index range.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.architecture_policy import gamemaker_depth_z_indices
from src.conversion.asset_registry import AssetRegistryEntry, render_asset_registry_script
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.json_values import JsonObject
from src.conversion.resource_index import IndexedRoom
from src.conversion.room_layers import serialize_room_layers
from src.conversion.script_generator import ObjectRuntimeConfig, generate_script_content
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)

# Room layers in .yy order (lowest depth first), as the room editor lists them.
_ROOM_LAYERS = (
    ("Front", -10),
    ("Instances", 0),
    ("Near", 3300),
    ("Far", 3320),
    ("Parallax", 9900),
    ("Background", 10000),
)
_NEXT_ROOM_LAYERS = (("Instances", 0), ("Ground", 300))

# Pairs that the old fixed mapping gave one z_index, plus far-out depths.
_CREATED_DEPTHS = (
    "-1e12",
    "-2147483648",
    "-20001",
    "-20000",
    "-10001",
    "-10000",
    "-5050",
    "-5000",
    "-4040",
    "-4000",
    "-3100",
    "-3080",
    "-11",
    "-10.5",
    "-10",
    "0.5",
    "3080",
    "3100",
    "5000",
    "5050",
    "2147483647",
    "1e12",
)

_OBJECTS: dict[str, dict[str, str]] = {
    "o_box": {},
    "o_painter": {"_on_draw": "draw_rectangle(0, 0, 1, 1, false);"},
}


def _object_scene(name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://objects/{name}/{name}.gd" id="1"]

        [node name="{name}" type="Node2D"]
        script = ExtResource("1")
        """
    )


def _write_objects(project_dir: Path) -> None:
    entries: list[AssetRegistryEntry] = []
    for index, (name, sources) in enumerate(_OBJECTS.items()):
        events: list[JsonObject] = [{"eventType": 8, "eventNum": 0} for _method in sources]
        bodies = {method: transpile_gml_code(source) for method, source in sources.items()}
        script = generate_script_content(
            events,
            code_bodies=bodies,
            instance_variables=set(),
            object_runtime=ObjectRuntimeConfig(object_name=name),
        )
        object_dir = project_dir / "objects" / name
        _write_text(object_dir / f"{name}.gd", script)
        _write_text(object_dir / f"{name}.tscn", _object_scene(name))
        entries.append(
            AssetRegistryEntry(
                id=100 + index,
                name=name,
                kind="objects",
                asset_type="object",
                type_name="Object",
                source_path=f"objects/{name}/{name}.yy",
                godot_path=f"res://objects/{name}/{name}.tscn",
                legacy_id=f"objects/{name}/{name}.yy",
            )
        )
    _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(tuple(entries)))


def _room_scene(script_name: str, layers: tuple[tuple[str, int], ...]) -> str:
    room = IndexedRoom(
        name="r",
        yy_path="rooms/r/r.yy",
        yyp_path="rooms/r/r.yy",
        godot_path="res://rooms/r/r.tscn",
        room_settings={},
        view_settings={},
        views=[],
        layers=[
            {"%Name": name, "resourceType": "GMRInstanceLayer", "depth": depth, "instances": []}
            for name, depth in layers
        ],
    )
    node_lines = serialize_room_layers(room).node_lines
    return "\n".join(
        [
            "[gd_scene load_steps=2 format=3]",
            "",
            f'[ext_resource type="Script" path="res://{script_name}" id="1"]',
            "",
            '[node name="Room" type="Node2D"]',
            'script = ExtResource("1")',
            'metadata/gm2godot_room_root_policy = "gm_room_node2d"',
            "",
            *node_lines,
            "",
        ]
    )


_HELPERS = """\
extends Node2D

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

func _check(condition, message):
\tif not condition:
\t\tpush_error(str(message))
\t\tget_tree().quit(1)
\t\treturn false
\treturn true

func _create_depth(object_name, depth):
\treturn GMRuntime.gml_handle_resolve(GMRuntime.gml_instance_create_depth(0, 0, depth, GMRuntime.gml_asset_get_index(object_name), self))

func _create_layer(object_name, layer_name):
\treturn GMRuntime.gml_handle_resolve(GMRuntime.gml_instance_create_layer(0, 0, layer_name, GMRuntime.gml_asset_get_index(object_name), self))

func _report(tag, node, depth):
\tprint(tag, " ", int(float(depth)), " ", node.z_index, " ", node.z_as_relative)

func _report_layers(tag):
\tfor child in get_children():
\t\tif child.has_meta("gamemaker_layer_depth"):
\t\t\t_report(tag, child, child.get_meta("gamemaker_layer_depth"))

func _draw_order():
\tvar order = []
\tfor entry in GMRuntime.gml_draw_event_trace():
\t\tif entry["phase"] == "draw" and entry["kind"] == "custom":
\t\t\torder.append(entry["instance"])
\treturn order
"""

_SMOKE_SCRIPT = _HELPERS + """
func _ready():
\tGMRuntime.gml_layer_register_scene(self)
\tcall_deferred("_run")

func _run():
\t_report_layers("ROOM_LAYER_Z")
\tvar created = []
\tfor depth in [%(created_depths)s]:
\t\tcreated.append([_create_depth("o_box", depth), depth])
\t# depth = -y in a room taller than Godot's z_index range.
\tvar sorted_rows = []
\tfor y in range(3073, 8001, 7):
\t\tvar row = _create_layer("o_box", "Instances")
\t\trow.depth = -y
\t\tsorted_rows.append(row)
\tvar made = GMRuntime.gml_layer_create(-30000, "Made")
\tvar moved = GMRuntime.gml_layer_create(0, "Moved")
\tGMRuntime.gml_layer_depth(moved, 30000)
\tvar system = GMRuntime.gml_part_system_create()
\tGMRuntime.gml_part_system_depth(system, -10002.5)
\t# Draw order: -10.5 truncates to -10, so it shares -10's layer and draws
\t# in creation order there; -11 draws after both.
\tvar half = _create_depth("o_painter", -10.5)
\tvar ten = _create_depth("o_painter", -10)
\tvar eleven = _create_depth("o_painter", -11)
\tGMRuntime.gm2godot_draw_event_trace_enable(true)
\tGMRuntime.gml_draw_event_trace_clear()
\tGMRuntime.gml_draw_event_dispatch_frame([eleven, ten, half])
\tvar names = {str(half.name): "-10.5", str(ten.name): "-10", str(eleven.name): "-11"}
\tvar order = []
\tfor name in _draw_order():
\t\torder.append(names.get(name, name))
\tprint("DRAW_ORDER ", " ".join(order))
\tGMRuntime.gml_draw_event_dispatch_frame()
\t_report_layers("Z")
\tfor record in created:
\t\t_report("Z", record[0], record[1])
\tfor row in sorted_rows:
\t\t_report("Z", row, row.depth)
\tfor painter in [half, ten, eleven]:
\t\t_report("Z", painter, painter.depth)
\t_report("Z", GMRuntime.gml_handle_resolve(made), -30000)
\t_report("Z", GMRuntime.gml_handle_resolve(moved), 30000)
\tvar system_node = GMRuntime._gml_particle_system_resolve(system)["node"]
\t_report("Z", system_node, -10002.5)
\tif not _check(GMRuntime.gml_depth_to_z_index(-10.5) == GMRuntime.gml_depth_to_z_index(-10), "depth -10.5 was not truncated to -10"):
\t\treturn
\tget_tree().change_scene_to_file("res://smoke_next.tscn")
"""

_NEXT_SCRIPT = _HELPERS + """
func _ready():
\tGMRuntime.gml_layer_register_scene(self)
\tcall_deferred("_run")

func _run():
\tvar near = _create_depth("o_box", -50)
\tGMRuntime.gml_draw_event_dispatch_frame()
\t# No depth in use is beyond Godot's range any more: z_index is -depth again.
\t_report_layers("NEXT_Z")
\t_report("NEXT_Z", near, -50)
\tprint("DEPTH_ORDER_OK")
\tget_tree().quit(0)
"""


def _run_godot(godot_binary: str, project_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["HOME"] = str(project_dir)
    return subprocess.run(
        [godot_binary, "--headless", "--path", str(project_dir), "--scene", "res://smoke.tscn", "--quit-after", "60"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=environment,
    )


def _reports(output: str, tag: str) -> list[tuple[int, int, bool]]:
    pattern = rf"^{tag} (-?\d+) (-?\d+) (true|false)$"
    return [
        (int(depth), int(z_index), relative == "true")
        for depth, z_index, relative in re.findall(pattern, output, re.MULTILINE)
    ]


class TestDepthOrderGodot(unittest.TestCase):
    output = ""

    @classmethod
    def setUpClass(cls) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            raise unittest.SkipTest("Godot binary not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DepthOrderSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_objects(project_dir)
            _write_text(project_dir / "smoke.gd", _SMOKE_SCRIPT % {"created_depths": ", ".join(_CREATED_DEPTHS)})
            _write_text(project_dir / "smoke.tscn", _room_scene("smoke.gd", _ROOM_LAYERS))
            _write_text(project_dir / "smoke_next.gd", _NEXT_SCRIPT)
            _write_text(project_dir / "smoke_next.tscn", _room_scene("smoke_next.gd", _NEXT_ROOM_LAYERS))
            result = _run_godot(godot_binary, project_dir)
        cls.output = result.stdout + result.stderr
        cls.returncode = result.returncode

    def test_smoke_runs_cleanly(self) -> None:
        self.assertEqual(self.returncode, 0, self.output)
        self.assertIn("DEPTH_ORDER_OK", self.output)
        self.assertNotIn("SCRIPT ERROR", self.output)
        self.assertNotIn("ERROR:", self.output)

    def test_truncated_depths_share_a_layer_in_draw_order(self) -> None:
        # Created in the order -10.5, -10, -11: the first two share depth -10
        # and draw in creation order, then -11 draws on top.
        self.assertEqual(re.findall(r"^DRAW_ORDER (.*)$", self.output, re.MULTILINE), ["-10.5 -10 -11"])

    def test_converted_room_layers_rank_their_depths(self) -> None:
        reports = _reports(self.output, "ROOM_LAYER_Z")
        expected = gamemaker_depth_z_indices(depth for _name, depth in _ROOM_LAYERS)
        self.assertEqual(len(reports), len(_ROOM_LAYERS), self.output)
        for depth, z_index, relative in reports:
            with self.subTest(depth=depth):
                self.assertFalse(relative)
                self.assertEqual(z_index, expected[depth])
        z_by_depth = {depth: z_index for depth, z_index, _relative in reports}
        self.assertGreater(z_by_depth[9900], z_by_depth[10000])
        self.assertGreater(z_by_depth[3300], z_by_depth[3320])

    def test_every_distinct_depth_in_use_has_its_own_ordered_z_index(self) -> None:
        reports = _reports(self.output, "Z")
        self.assertGreater(len(reports), 700, self.output)
        z_by_depth: dict[int, int] = {}
        for depth, z_index, relative in reports:
            with self.subTest(depth=depth):
                self.assertFalse(relative)
                self.assertTrue(-4096 <= z_index <= 4096)
                # Depths that truncate to the same integer share a layer.
                self.assertEqual(z_by_depth.setdefault(depth, z_index), z_index)
        ordered = [z_by_depth[depth] for depth in sorted(z_by_depth)]
        self.assertEqual(len(set(ordered)), len(ordered), "two distinct depths share a z_index")
        self.assertEqual(ordered, sorted(ordered, reverse=True), "a lower depth does not draw later")
        # The runtime ranks the depths in use exactly like the converter.
        self.assertEqual(z_by_depth, gamemaker_depth_z_indices(z_by_depth))

    def test_z_index_returns_to_negative_depth_when_every_depth_fits(self) -> None:
        reports = _reports(self.output, "NEXT_Z")
        self.assertEqual(len(reports), len(_NEXT_ROOM_LAYERS) + 1, self.output)
        for depth, z_index, _relative in reports:
            with self.subTest(depth=depth):
                self.assertEqual(z_index, -depth)


if __name__ == "__main__":
    unittest.main()
