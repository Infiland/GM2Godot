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
    "o_mover": {
        "_on_draw": "draw_rectangle(0, 0, 1, 1, false);",
        "_exit_tree": 'show_debug_message("CLEANUP");',
    },
    "o_draw_depth": {"_on_draw": "draw_rectangle(0, 0, 1, 1, false); depth = -70;"},
    "o_create_depth": {"_ready": "depth = -80;", "_exit_tree": 'show_debug_message("CLEANUP");'},
    "o_early_depth": {"_ready": "depth = 100;", "_on_draw": "draw_rectangle(0, 0, 1, 1, false);"},
}
# GameMaker event (type, number) of each generated method.
_EVENTS = {"_ready": (0, 0), "_on_draw": (8, 0), "_exit_tree": (12, 0)}


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
        events: list[JsonObject] = [
            {"eventType": _EVENTS[method][0], "eventNum": _EVENTS[method][1]} for method in sources
        ]
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


def _room_scene(
    script_name: str,
    layers: tuple[tuple[str, int], ...],
    placed: tuple[tuple[str, str, str], ...] = (),
) -> str:
    """A room scene with the layers and placed (name, object, layer) instances."""
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
    placed_resources: list[str] = []
    placed_nodes: list[str] = []
    for index, (node_name, object_name, layer_name) in enumerate(placed, start=2):
        placed_resources.append(
            f'[ext_resource type="PackedScene" path="res://objects/{object_name}/{object_name}.tscn" id="{index}"]'
        )
        placed_nodes.extend([f'[node name="{node_name}" parent="{layer_name}" instance=ExtResource("{index}")]', ""])
    return "\n".join(
        [
            f"[gd_scene load_steps={2 + len(placed)} format=3]",
            "",
            f'[ext_resource type="Script" path="res://{script_name}" id="1"]',
            *placed_resources,
            "",
            '[node name="Room" type="Node2D"]',
            'script = ExtResource("1")',
            'metadata/gm2godot_room_root_policy = "gm_room_node2d"',
            "",
            *node_lines,
            *placed_nodes,
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

# Whether node is on the room's managed layer at depth.
func _on_managed_layer(node, depth):
\tvar layer = node.get_parent()
\treturn layer != null and layer.get_parent() == self and layer.get_meta(GMRuntime.GML_MANAGED_LAYER_DEPTH_META, null) == depth

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
\thalf.name = "Half"
\tvar ten = _create_depth("o_painter", -10)
\tten.name = "Ten"
\tvar eleven = _create_depth("o_painter", -11)
\televen.name = "Eleven"
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

_LAYER_ROOM_LAYERS = (("Front", -10), ("Hidden", 0), ("Doomed", 0), ("Mid", 20))

_LAYER_SCRIPT = _HELPERS + """
func _ready():
\tGMRuntime.gml_layer_register_scene(self)
\tcall_deferred("_run")

func _exists(inst):
\treturn is_instance_valid(inst) and GMRuntime.gml_instance_exists(inst.id)

func _run():
\t# Assigning a depth moves the instance off its room layer; x and y stay.
\tvar mover = _create_layer("o_mover", "Hidden")
\tmover.position = Vector2(30, 40)
\tmover.depth = -50
\tprint("MOVED ", _on_managed_layer(mover, -50), " ", mover.position, " ", mover.z_index, " ", _exists(mover))
\t# Hiding the room layer it left does not hide it.
\tGMRuntime.gml_layer_set_visible("Hidden", false)
\tGMRuntime.gm2godot_draw_event_trace_enable(true)
\tGMRuntime.gml_draw_event_trace_clear()
\tGMRuntime.gml_draw_event_dispatch_frame()
\tprint("HIDDEN_LAYER ", mover.is_visible_in_tree(), " ", _draw_order().has(str(mover.name)))
\t# Destroying the room layer it left does not destroy it.
\tvar survivor = _create_layer("o_mover", "Doomed")
\tsurvivor.depth = -60
\tGMRuntime.gml_layer_destroy("Doomed")
\tawait get_tree().process_frame
\tprint("SURVIVOR ", _exists(survivor))
\t# Assigning the depth it already has changes nothing: it stays on its
\t# layer and follows layer_depth.
\tvar stayer = _create_layer("o_mover", "Mid")
\tstayer.depth = stayer.depth
\tGMRuntime.gml_layer_depth("Mid", -20)
\tprint("UNCHANGED ", stayer.get_parent().name, " ", stayer.depth, " ", stayer.has_meta(GMRuntime.GML_EXPLICIT_DEPTH_META))
\t# A depth that truncates to the layer's depth keeps it on the layer.
\tvar fraction = _create_layer("o_mover", "Mid")
\tfraction.depth = -20.5
\tprint("SAME_LAYER ", fraction.get_parent().name, " ", fraction.depth, " ", fraction.z_as_relative)
\t# layer_add_instance moves it back onto a layer as the same instance.
\tGMRuntime.gml_layer_add_instance("Front", mover)
\tprint("ADDED_BACK ", mover.get_parent().name, " ", mover.depth, " ", _exists(mover))
\t# A depth set in a Draw event applies after the frame; the frame keeps
\t# what the event drew.
\tvar drawer = _create_layer("o_draw_depth", "Front")
\tGMRuntime.gml_draw_event_dispatch_frame([drawer])
\tvar sink = GMRuntime.gm2godot_draw_debug_sink_for(drawer, "draw")
\tprint("DRAW_DEPTH ", _on_managed_layer(drawer, -70), " ", drawer.z_index, " ", int(sink.get("commands", 0)))
\t# A Create event that sets depth while its layer is still adding its
\t# children moves the instance once the layer can let it go.
\tvar late_layer = Node2D.new()
\tlate_layer.name = "Late"
\tlate_layer.set_meta("gamemaker_layer_depth", 0)
\tvar late = load("res://objects/o_create_depth/o_create_depth.tscn").instantiate()
\tlate_layer.add_child(late)
\tadd_child(late_layer)
\tawait get_tree().process_frame
\tprint("CREATE_DEPTH ", _on_managed_layer(late, -80), " ", late.z_index, " ", _exists(late))
\tprint("DESTROYING")
\tGMRuntime.gml_instance_destroy(mover)
\tawait get_tree().process_frame
\tprint("DEPTH_LAYERS_OK")
\tget_tree().quit(0)
"""


# Room layers in .yy order; Ground, Far and Spare share depths with layers and
# managed layers the script adds.
_TIE_ROOM_LAYERS = (("Top", -100), ("Instances", 0), ("Spare", 50), ("Ground", 100), ("Far", 500))

_TIE_SCRIPT = _HELPERS + """
func _ready():
\tGMRuntime.gml_layer_register_scene(self)
\tcall_deferred("_run")

func _painter(layer_name, label):
\tvar inst = _create_layer("o_painter", layer_name)
\tinst.name = label
\treturn inst

func _run():
\t# depth = the depth of a later room layer, then of an earlier one.
\tvar ground = _painter("Ground", "Ground1")
\tvar down = _painter("Instances", "MovedDown")
\tdown.depth = 100
\tvar top = _painter("Top", "Top1")
\tvar up = _painter("Ground", "MovedUp")
\tup.depth = -100
\t# instance_create_depth at that depth joins the same managed layer.
\tvar made = _create_depth("o_painter", 100)
\tmade.name = "Created100"
\t# layer_create and layer_depth add a layer behind every layer of its depth.
\tGMRuntime.gml_layer_create(100, "Late")
\t_painter("Late", "Late1")
\t_painter("Spare", "Spare1")
\tGMRuntime.gml_layer_depth("Spare", 100)
\t# A managed layer emptied of its instances stays where it was.
\tvar a = _painter("Instances", "A")
\ta.depth = 200
\tvar b = _painter("Instances", "B")
\tb.depth = 200
\ta.depth = 300
\tGMRuntime.gml_instance_destroy(b)
\tGMRuntime.gml_layer_create(200, "After200")
\t_painter("After200", "After200Inst")
\tvar c = _painter("Instances", "C")
\tc.depth = 200
\t# An instance alone on its managed layer takes that layer to the new depth,
\t# behind every layer there, and it takes in the managed layer already there.
\t_painter("Far", "Far1")
\tvar y = _painter("Instances", "Y")
\ty.depth = 500
\tGMRuntime.gml_layer_create(500, "Over500")
\t_painter("Over500", "Over500Inst")
\tvar x = _painter("Instances", "X")
\tx.depth = 400
\tx.depth = 500
\tawait get_tree().process_frame
\tGMRuntime.gm2godot_draw_event_trace_enable(true)
\tGMRuntime.gml_draw_event_trace_clear()
\tGMRuntime.gml_draw_event_dispatch_frame()
\tprint("TIE_DRAW ", " ".join(_draw_order()))
\tvar tree = []
\tfor child in get_children():
\t\tvar names = [str(child.name)]
\t\tfor inner in child.get_children():
\t\t\tnames.append(str(inner.name))
\t\ttree.append(",".join(names))
\tprint("TIE_TREE ", " ".join(tree))
\tvar ground_layer = ground.get_parent()
\tprint("TIE_Z ", down.z_index == ground_layer.z_index, " ", made.z_index == ground_layer.z_index, " ", up.z_index == top.get_parent().z_index)
\tprint("TIE_OK")
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


class TestDepthAssignmentLeavesLayerGodot(unittest.TestCase):
    """An assigned depth moves an instance off its room layer, like GameMaker.

    The depth setter queues the instance only when the value changes
    (yyInstance.js); ProcessDepthList2 (yyRoom.js) then moves it to a managed
    layer at the new depth unless that truncates to its layer's depth. Draw
    passes skip only layers that are themselves hidden, so the room layer's
    visibility and layer_destroy no longer reach it.
    """

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
                '[application]\nconfig/name="DepthLayerSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_objects(project_dir)
            _write_text(project_dir / "smoke.gd", _LAYER_SCRIPT)
            _write_text(project_dir / "smoke.tscn", _room_scene("smoke.gd", _LAYER_ROOM_LAYERS))
            result = _run_godot(godot_binary, project_dir)
        cls.output = result.stdout + result.stderr
        cls.returncode = result.returncode

    def _line(self, tag: str) -> str:
        lines = re.findall(rf"^{tag} (.*)$", self.output, re.MULTILINE)
        self.assertEqual(len(lines), 1, self.output)
        return lines[0]

    def test_smoke_runs_cleanly(self) -> None:
        self.assertEqual(self.returncode, 0, self.output)
        self.assertIn("DEPTH_LAYERS_OK", self.output)
        self.assertNotIn("SCRIPT ERROR", self.output)
        self.assertNotIn("ERROR:", self.output)

    def test_assigned_depth_moves_the_instance_off_its_layer(self) -> None:
        self.assertEqual(self._line("MOVED"), "true (30.0, 40.0) 50 true")

    def test_hidden_room_layer_does_not_hide_a_moved_instance(self) -> None:
        self.assertEqual(self._line("HIDDEN_LAYER"), "true true")

    def test_destroyed_room_layer_does_not_destroy_a_moved_instance(self) -> None:
        self.assertEqual(self._line("SURVIVOR"), "true")

    def test_assigning_the_current_depth_keeps_the_instance_on_its_layer(self) -> None:
        self.assertEqual(self._line("UNCHANGED"), "Mid -20.0 false")

    def test_depth_truncating_to_the_layer_depth_keeps_the_layer(self) -> None:
        self.assertEqual(self._line("SAME_LAYER"), "Mid -20.5 true")

    def test_layer_add_instance_moves_the_same_instance_back(self) -> None:
        self.assertEqual(self._line("ADDED_BACK"), "Front -10.0 true")

    def test_depth_set_while_drawing_keeps_that_frame(self) -> None:
        self.assertEqual(self._line("DRAW_DEPTH"), "true 70 1")

    def test_depth_set_while_the_layer_adds_children_moves_after(self) -> None:
        self.assertEqual(self._line("CREATE_DEPTH"), "true 80 true")

    def test_moving_between_layers_runs_no_clean_up_event(self) -> None:
        before, _marker, after = self.output.partition("DESTROYING")
        self.assertEqual(before.count("CLEANUP"), 0, self.output)
        self.assertEqual(after.partition("DEPTH_LAYERS_OK")[0].count("CLEANUP"), 1, self.output)


class TestEqualDepthLayerOrderGodot(unittest.TestCase):
    """Layers sharing a depth draw in GameMaker's order.

    GameMaker keeps a room's layers in one list sorted by depth and inserts a
    layer after every layer of the same depth (yyOList.Add); DrawRoomLayers and
    ExecuteDrawEvent (yyRoom.js) walk that list from its end, so of the layers
    sharing a depth the one added last draws first, behind the others. Managed
    layers (AddDynamicLayer, Function_Layers.js), layer_create and layer_depth
    (ChangeLayerDepth) all add a layer that way. Godot draws equal z_index in
    tree order, so the added layer node must come first in the room.
    """

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
                '[application]\nconfig/name="DepthTieSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_objects(project_dir)
            _write_text(project_dir / "smoke.gd", _TIE_SCRIPT)
            # Early's Create event sets depth = 100 while the room still adds
            # its children: its managed layer is the first at that depth.
            room = _room_scene("smoke.gd", _TIE_ROOM_LAYERS, (("Early", "o_early_depth", "Instances"),))
            _write_text(project_dir / "smoke.tscn", room)
            result = _run_godot(godot_binary, project_dir)
        cls.output = result.stdout + result.stderr
        cls.returncode = result.returncode

    def _line(self, tag: str) -> str:
        lines = re.findall(rf"^{tag} (.*)$", self.output, re.MULTILINE)
        self.assertEqual(len(lines), 1, self.output)
        return lines[0]

    def _room_positions(self) -> dict[str, int]:
        # The index of the room child (layer or managed layer) holding each node.
        positions: dict[str, int] = {}
        for index, entry in enumerate(self._line("TIE_TREE").split(" ")):
            for name in entry.split(","):
                positions[name] = index
        return positions

    def test_smoke_runs_cleanly(self) -> None:
        self.assertEqual(self.returncode, 0, self.output)
        self.assertIn("TIE_OK", self.output)
        self.assertNotIn("SCRIPT ERROR", self.output)
        self.assertNotIn("ERROR:", self.output)

    def test_draw_events_follow_gamemaker_layer_order_at_each_depth(self) -> None:
        order = self._line("TIE_DRAW").split(" ")
        # Instances on one layer draw in tree order (a documented deviation:
        # GameMaker does not guarantee one), so the instances on the managed
        # layer at 100 only have to share their place.
        expected = [
            ["X"], ["Y"], ["Over500Inst"], ["Far1"],
            ["A"],
            ["After200Inst"], ["C"],
            ["Spare1"], ["Late1"], ["Early", "MovedDown", "Created100"], ["Ground1"],
            ["MovedUp"], ["Top1"],
        ]
        grouped: list[list[str]] = []
        for group in expected:
            grouped.append(sorted(order[: len(group)]))
            order = order[len(group):]
        self.assertEqual(grouped, [sorted(group) for group in expected], self.output)
        self.assertEqual(order, [], self.output)

    def test_layer_added_at_a_depth_comes_first_in_the_room(self) -> None:
        positions = self._room_positions()
        # (behind, in front) pairs that share a depth and so a z_index.
        for behind, front in (
            ("Early", "Ground1"),
            ("MovedDown", "Ground1"),
            ("Created100", "Ground1"),
            ("Late1", "MovedDown"),
            ("Spare1", "Late1"),
            ("MovedUp", "Top1"),
            ("After200Inst", "C"),
            ("X", "Over500Inst"),
            ("Over500Inst", "Far1"),
        ):
            with self.subTest(behind=behind, front=front):
                self.assertLess(positions[behind], positions[front], self.output)
        # The managed layer made while the room loaded is the one later
        # moves join; the merged managed layer holds both of its instances.
        self.assertEqual(positions["Early"], positions["MovedDown"], self.output)
        self.assertEqual(positions["Early"], positions["Created100"], self.output)
        self.assertEqual(positions["X"], positions["Y"], self.output)

    def test_managed_layer_shares_the_z_index_of_its_depth(self) -> None:
        self.assertEqual(self._line("TIE_Z"), "true true true")


if __name__ == "__main__":
    unittest.main()
