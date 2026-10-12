"""Headless Godot checks for the GameMaker draw pipeline runtime.

Draw events run from ``gml_draw_event_dispatch_frame`` and record their
commands on runtime-owned RenderingServer canvas items ("draw sinks"). These
tests cover the phase spaces, GameMaker draw-state persistence, depth to
z_index reordering, GPU state segments and the canvas item
lifecycle across instance destruction, room changes and shutdown.
"""
from __future__ import annotations

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
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.json_values import JsonObject
from src.conversion.script_generator import ObjectRuntimeConfig, generate_script_content
from tests.godot_test_support import (
    find_smoke_godot_binary as _find_godot_binary,
    write_fixture_text as _write_text,
)

_SHADER_SOURCE = textwrap.dedent(
    """\
    shader_type canvas_item;
    uniform float amount = 0.0;

    void fragment() {
        COLOR = vec4(amount, 0.0, 0.0, 1.0);
    }
    """
)

_OBJECTS: dict[str, tuple[dict[str, str], set[str]]] = {
    "o_phases": (
        {
            "_on_pre_draw": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw_begin": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw_end": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_post_draw": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw_gui_begin": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw_gui": "draw_rectangle(0, 0, 2, 2, false);",
            "_on_draw_gui_end": "draw_rectangle(0, 0, 2, 2, false);",
        },
        set(),
    ),
    "o_state_a": (
        {
            "_on_draw": (
                "start_alpha = draw_get_alpha();"
                "draw_set_alpha(0.25);"
                "draw_set_colour(c_lime);"
                "draw_rectangle(0, 0, 1, 1, false);"
            ),
        },
        {"start_alpha"},
    ),
    "o_state_b": (
        {
            "_on_draw": (
                "seen_alpha = draw_get_alpha();"
                "seen_colour = draw_get_colour();"
                "draw_rectangle(0, 0, 1, 1, false);"
            ),
        },
        {"seen_alpha", "seen_colour"},
    ),
    "o_depth": (
        {"_on_draw": "draw_rectangle(0, 0, 1, 1, false); depth = -300;"},
        {"z_during"},
    ),
    "o_shader": (
        {
            "_on_draw": (
                'var u_amount = shader_get_uniform(shd_test, "amount");'
                "shader_set(shd_test);"
                "shader_set_uniform_f(u_amount, 0.25);"
                "draw_rectangle(0, 0, 1, 1, false);"
                "shader_set_uniform_f(u_amount, 0.75);"
                "draw_rectangle(0, 0, 1, 1, false);"
                "shader_reset();"
                "draw_rectangle(0, 0, 1, 1, false);"
            ),
        },
        set(),
    ),
}

_EVENT_NUMBERS = {
    "_on_draw": 0,
    "_on_draw_gui": 64,
    "_on_draw_begin": 72,
    "_on_draw_end": 73,
    "_on_draw_gui_begin": 74,
    "_on_draw_gui_end": 75,
    "_on_pre_draw": 76,
    "_on_post_draw": 77,
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
    for name, (sources, variables) in _OBJECTS.items():
        events: list[JsonObject] = [
            {"eventType": 8, "eventNum": _EVENT_NUMBERS[method]} for method in sources
        ]
        bodies = {
            method: transpile_gml_code(source, asset_names={"shd_test"})
            for method, source in sources.items()
        }
        script = generate_script_content(
            events,
            code_bodies=bodies,
            instance_variables=variables,
            object_runtime=ObjectRuntimeConfig(object_name=name),
        )
        if name == "o_depth":
            # Record the z_index the instance has right after its Draw event
            # assigned a new depth.
            script = script.replace("\tdepth = -300\n", "\tdepth = -300\n\tz_during = z_index\n")
            assert "z_during = z_index" in script
        object_dir = project_dir / "objects" / name
        _write_text(object_dir / f"{name}.gd", script)
        _write_text(object_dir / f"{name}.tscn", _object_scene(name))


def _write_registry(project_dir: Path) -> None:
    entries = [
        AssetRegistryEntry(
            id=200,
            name="shd_test",
            kind="shaders",
            asset_type="shader",
            type_name="Shader",
            source_path="shaders/shd_test/shd_test.yy",
            godot_path="res://shaders/shd_test.gdshader",
            legacy_id="shaders/shd_test/shd_test.yy",
        )
    ]
    for index, name in enumerate(_OBJECTS):
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
    _write_text(project_dir / "shaders" / "shd_test.gdshader", _SHADER_SOURCE)


_SMOKE_HELPERS = """\
extends Node2D

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

# space: [layer name, layer order, follows the viewport, commands per frame]
const SPACE_LAYERS = {
\t"pre_draw": ["_GM2GodotPreDraw", -2, false, 1],
\t"draw_begin": ["_GM2GodotDrawBegin", -1, true, 1],
\t"draw_end": ["_GM2GodotDrawEnd", 1, true, 1],
\t"post_draw": ["_GM2GodotPostDraw", 999, false, 1],
\t"gui": ["GMGUI", 1000, false, 3],
}

func _check(condition, message):
\tif not condition:
\t\tpush_error(str(message))
\t\tget_tree().quit(1)
\t\treturn false
\treturn true

func _sinks():
\tvar sinks = {}
\tfor sink in GMRuntime.gm2godot_draw_debug_snapshot():
\t\tsinks[sink["key"]] = sink
\treturn sinks

func _make_layer():
\tvar layer = Node2D.new()
\tlayer.name = "Instances"
\tlayer.set_meta("gamemaker_layer_depth", 0)
\tlayer.position = Vector2(5, 7)
\tadd_child(layer)
\treturn layer

func _create(object_name, x = 0, y = 0):
\treturn GMRuntime.gml_handle_resolve(GMRuntime.gml_instance_create_layer(x, y, "Instances", GMRuntime.gml_asset_get_index(object_name), self))

func _create_depth(object_name, depth):
\treturn GMRuntime.gml_handle_resolve(GMRuntime.gml_instance_create_depth(0, 0, depth, GMRuntime.gml_asset_get_index(object_name), self))

func _check_phase_spaces(phases):
\tvar sinks = _sinks()
\tvar instance_sink = sinks.get("instance:" + str(phases.get_instance_id()), {})
\tif not _check(int(instance_sink.get("commands", 0)) == 1, "Draw event commands did not reach the instance sink: " + str(instance_sink)):
\t\treturn false
\tif not _check(instance_sink["parent"] == phases.get_canvas_item(), "Draw event sink is not a child of the instance canvas item"):
\t\treturn false
\tfor space in SPACE_LAYERS:
\t\tvar spec = SPACE_LAYERS[space]
\t\tvar layer = get_node_or_null(NodePath(spec[0]))
\t\tif not _check(layer is CanvasLayer, "missing draw space layer " + spec[0]):
\t\t\treturn false
\t\tif not _check(layer.layer == spec[1] and layer.follow_viewport_enabled == spec[2], "draw space layer has the wrong order or viewport mode: " + spec[0]):
\t\t\treturn false
\t\tvar sink = sinks.get("space:" + space, {})
\t\tif not _check(int(sink.get("commands", 0)) == spec[3], "phase commands did not reach the " + space + " sink: " + str(sink)):
\t\t\treturn false
\t\tif not _check(sink["parent"] == layer.get_canvas(), "the " + space + " sink is not on its layer canvas"):
\t\t\treturn false
\treturn true
"""

_SMOKE_SCRIPT = _SMOKE_HELPERS + """
func _ready():
\tcall_deferred("_run")

func _run():
\tvar layer = _make_layer()
\tvar phases = _create("o_phases", 10, 20)
\tphases.rotation_degrees = 30.0
\tphases.scale = Vector2(2.0, 0.5)
\tvar state_a = _create_depth("o_state_a", 100)
\tvar state_b = _create_depth("o_state_b", 50)
\tif not _check(get_node_or_null("_GM2GodotDrawBegin") == null and get_node_or_null("GMGUI") == null, "draw space layers were created before anything drew"):
\t\treturn
\tif not _check(state_a.z_index == -100 and not state_a.z_as_relative and state_b.z_index == -50, "instance depth did not map to an absolute z_index"):
\t\treturn

\tGMRuntime.gml_draw_event_dispatch_frame()
\tif not _check_phase_spaces(phases):
\t\treturn
\tvar phases_sink = GMRuntime.gm2godot_draw_debug_sink_for(phases, "draw")
\tvar room_space = phases.get_global_transform() * phases_sink["transform"]
\tif not _check(room_space.is_equal_approx(layer.get_global_transform()), "Draw event coordinates are not in the instance's layer space: " + str(room_space)):
\t\treturn
\tif not _check(abs(float(state_b.seen_alpha) - 0.25) < 0.001 and int(state_b.seen_colour) == 0x00ff00, "draw state set by a deeper instance did not reach the next instance"):
\t\treturn
\tif not _check(abs(float(state_a.start_alpha) - 1.0) < 0.001, "draw alpha did not start at 1"):
\t\treturn
\tvar first_root = phases_sink["root"]

\tGMRuntime.gml_draw_event_dispatch_frame()
\tif not _check(abs(float(state_a.start_alpha) - 0.25) < 0.001, "draw state did not persist into the next frame"):
\t\treturn
\tphases_sink = GMRuntime.gm2godot_draw_debug_sink_for(phases, "draw")
\tif not _check(phases_sink["root"] == first_root and int(phases_sink["commands"]) == 1 and phases_sink["segments"].size() == 1, "draw sink was not cleared and reused: " + str(phases_sink)):
\t\treturn

\tGMRuntime.gm2godot_draw_event_trace_enable(true)
\tGMRuntime.gml_draw_event_trace_clear()
\tGMRuntime.gml_draw_event_dispatch_frame([state_a, state_b])
\tif not _check(_draw_order() == [str(state_a.name), str(state_b.name)], "deeper instance did not draw first: " + str(_draw_order())):
\t\treturn
\tstate_a.depth = -200
\tif not _check(state_a.z_index == 200, "depth assignment did not move the instance's z_index"):
\t\treturn
\tGMRuntime.gml_draw_event_trace_clear()
\tGMRuntime.gml_draw_event_dispatch_frame([state_a, state_b])
\tif not _check(_draw_order() == [str(state_b.name), str(state_a.name)], "depth assignment did not reorder drawing: " + str(_draw_order())):
\t\treturn

\tvar mover = _create_depth("o_depth", 0)
\tGMRuntime.gml_draw_event_dispatch_frame([mover])
\tif not _check(int(mover.z_during) == 0, "depth set in a Draw event moved the instance during the same frame"):
\t\treturn
\tif not _check(float(mover.depth) == -300.0 and mover.z_index == 300, "depth set in a Draw event was not applied after the frame"):
\t\treturn

\tvar shaded = _create("o_shader")
\tGMRuntime.gml_draw_event_dispatch_frame([shaded])
\tvar shader_segments = GMRuntime.gm2godot_draw_debug_sink_for(shaded, "draw")["segments"]
\tif not _check(shader_segments.size() == 3, "shader state did not split the sink into segments: " + str(shader_segments)):
\t\treturn
\tvar first_material = shader_segments[0]["material_ref"]
\tvar second_material = shader_segments[1]["material_ref"]
\tif not _check(first_material is ShaderMaterial and second_material is ShaderMaterial and first_material != second_material, "uniform change after a draw did not get its own material"):
\t\treturn
\tif not _check(abs(float(first_material.get_shader_parameter("amount")) - 0.25) < 0.001 and abs(float(second_material.get_shader_parameter("amount")) - 0.75) < 0.001, "draws did not keep the uniform values they were drawn with"):
\t\treturn
\tif not _check(shader_segments[2]["material"] == "none", "shader_reset did not restore the default material"):
\t\treturn
\tGMRuntime.gml_draw_event_dispatch_frame([shaded])
\tvar again = GMRuntime.gm2godot_draw_debug_sink_for(shaded, "draw")["segments"]
\tif not _check(again[0]["material_ref"] == first_material and again[1]["material_ref"] == second_material, "per-draw shader materials were not reused on the next frame"):
\t\treturn

\tif not _check(float(phases.depth) == 0.0, "an instance on a layer did not report the layer depth: " + str(phases.depth)):
\t\treturn
\tGMRuntime.gml_layer_depth(layer, 40)
\tif not _check(float(phases.depth) == 40.0 and layer.z_index == -40, "layer_depth did not reach the instances on the layer: " + str(phases.depth)):
\t\treturn
\tvar moved = _create_depth("o_state_b", -20)
\tGMRuntime.gml_layer_add_instance(layer, moved)
\tif not _check(float(moved.depth) == 40.0 and moved.z_as_relative and moved.z_index == 0, "layer_add_instance did not give the instance the layer's depth"):
\t\treturn
\tGMRuntime.gml_instance_destroy(moved)

\tvar destroyed_key = "instance:" + str(state_b.get_instance_id())
\tGMRuntime.gml_instance_destroy(state_b)
\tawait get_tree().process_frame
\tGMRuntime.gml_draw_event_dispatch_frame()
\tif not _check(not _sinks().has(destroyed_key), "the draw sink of a destroyed instance was not released"):
\t\treturn
\tget_tree().change_scene_to_file("res://smoke_next.tscn")

func _draw_order():
\tvar order = []
\tfor entry in GMRuntime.gml_draw_event_trace():
\t\tif entry["phase"] == "draw" and entry["kind"] == "custom":
\t\t\torder.append(entry["instance"])
\treturn order
"""

_NEXT_SCRIPT = _SMOKE_HELPERS + """
func _ready():
\tcall_deferred("_run")

func _run():
\tif not _check(_sinks().is_empty(), "draw sinks survived the room change: " + str(_sinks().keys())):
\t\treturn
\t_make_layer()
\t# A converted room registers its layers when it is entered.
\tGMRuntime.gml_layer_register_scene(self)
\tvar phases = _create("o_phases")
\tGMRuntime.gml_draw_event_dispatch_frame()
\tif not _check_phase_spaces(phases):
\t\treturn
\tGMRuntime.gm2godot_runtime_shutdown()
\tif not _check(_sinks().is_empty(), "runtime shutdown did not release the draw sinks"):
\t\treturn
\tprint("DRAW_PIPELINE_SMOKE_OK")
\tget_tree().quit(0)
"""


def _scene(script_name: str) -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://{script_name}" id="1"]

        [node name="Smoke" type="Node2D"]
        script = ExtResource("1")
        """
    )


def _run_godot(godot_binary: str, project_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["HOME"] = str(project_dir)
    return subprocess.run(
        [
            godot_binary,
            "--headless",
            "--path",
            str(project_dir),
            "--scene",
            "res://smoke.tscn",
            "--quit-after",
            "60",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=environment,
    )


class TestDrawPipelineGodot(unittest.TestCase):
    def test_draw_pipeline_spaces_state_depth_and_canvas_item_lifecycle(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DrawPipelineSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
            _write_objects(project_dir)
            _write_text(project_dir / "smoke.gd", _SMOKE_SCRIPT)
            _write_text(project_dir / "smoke.tscn", _scene("smoke.gd"))
            _write_text(project_dir / "smoke_next.gd", _NEXT_SCRIPT)
            _write_text(project_dir / "smoke_next.tscn", _scene("smoke_next.gd"))

            result = _run_godot(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("DRAW_PIPELINE_SMOKE_OK", output)
        self.assertNotIn("Drawing is only allowed", output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("leaked", output)


if __name__ == "__main__":
    unittest.main()
