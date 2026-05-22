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


def _write_registry(project_dir: Path) -> None:
    entries = (
        AssetRegistryEntry(
            id=300,
            name="seq_intro",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_intro/seq_intro.yy",
            godot_path="",
            legacy_id="sequences/seq_intro/seq_intro.yy",
            metadata={
                "length": 12.0,
                "playback_speed": 1.0,
                "loopmode": 0,
                "tracks": [],
                "moments": [{"frame": 1.0, "callable": "_sequence_callback"}],
                "broadcasts": [{"frame": 2.0, "message": "beat", "callable": "_sequence_callback"}],
            },
        ),
        AssetRegistryEntry(
            id=400,
            name="tl_intro",
            kind="timelines",
            asset_type="timeline",
            type_name="Timeline",
            source_path="timelines/tl_intro/tl_intro.yy",
            godot_path="",
            legacy_id="timelines/tl_intro/tl_intro.yy",
            metadata={
                "moments": [
                    {"frame": 1, "actions": [{"kind": "callable", "callable": "_timeline_seed_callback"}]}
                ]
            },
        ),
    )
    _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", render_asset_registry_script(entries))


def _write_smoke_scene(project_dir: Path) -> None:
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var timeline_index = -1
        var timeline_position = 0.0
        var timeline_speed = 1.0
        var timeline_running = false
        var timeline_loop = false

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _timeline_callback(instance):
        \tGMRuntime.gml_global_scope()["timeline_hits"] = GMRuntime.gml_global_scope().get("timeline_hits", 0) + 1
        \tif instance != self:
        \t\tGMRuntime.gml_global_scope()["timeline_wrong_self"] = true

        func _timeline_seed_callback(instance, action):
        \tGMRuntime.gml_global_scope()["timeline_seed_hits"] = GMRuntime.gml_global_scope().get("timeline_seed_hits", 0) + 1
        \tif instance != self:
        \t\tGMRuntime.gml_global_scope()["timeline_seed_wrong_self"] = true

        func _sequence_callback(instance, action):
        \tGMRuntime.gml_global_scope()["sequence_events"] = GMRuntime.gml_global_scope().get("sequence_events", 0) + 1
        \tif action.get("message", "") == "beat":
        \t\tGMRuntime.gml_global_scope()["sequence_broadcast"] = action["message"]

        func _ready():
        \tvar layer = Node2D.new()
        \tlayer.name = "Sequences"
        \tlayer.set_meta("gamemaker_layer_name", "Sequences")
        \tlayer.set_meta("gamemaker_layer_depth", 100)
        \tadd_child(layer)
        \tGMRuntime.gml_layer_register_scene(self)

        \tvar sequence_asset = GMRuntime.gml_asset_get_index("seq_intro")
        \tif not _check(GMRuntime.gml_sequence_exists(sequence_asset), "sequence_exists failed"):
        \t\treturn
        \tvar sequence_object = GMRuntime.gml_sequence_get(sequence_asset)
        \tif not _check(sequence_object["name"] == "seq_intro" and sequence_object["length"] == 12.0, "sequence_get metadata mismatch"):
        \t\treturn
        \tvar element = GMRuntime.gml_layer_sequence_create("Sequences", 4, 5, sequence_asset)
        \tif not _check(GMRuntime.gml_handle_is_valid(element), "layer_sequence_create returned invalid handle"):
        \t\treturn
        \tvar element_node = GMRuntime.gml_handle_resolve(element)
        \tif not _check(element_node.get_parent() == layer and element_node.position == Vector2(4, 5), "sequence element node mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_layer_get_element_type(element) == "sequence", "sequence element type mismatch"):
        \t\treturn
        \tvar instance = GMRuntime.gml_layer_sequence_get_instance(element)
        \tif not _check(instance["sequence"]["name"] == "seq_intro" and instance["elementID"].index == element.index, "sequence instance mismatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_step(element, 2)
        \tif not _check(GMRuntime.gml_global_scope().get("sequence_events", 0) == 2, "sequence authored events did not fire"):
        \t\treturn
        \tif not _check(GMRuntime.gml_global_scope().get("sequence_broadcast", "") == "beat", "sequence broadcast did not dispatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_headpos(element, 6)
        \tif not _check(GMRuntime.gml_layer_sequence_get_headpos(element) == 6, "sequence headpos mismatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_speedscale(element, 2)
        \tGMRuntime.gml_layer_sequence_headdir(element, GMRuntime.gml_real(-1))
        \tGMRuntime.gml_layer_sequence_step(element, 2)
        \tif not _check(GMRuntime.gml_layer_sequence_get_headpos(element) == 2, "sequence step mismatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_pause(element)
        \tif not _check(GMRuntime.gml_layer_sequence_is_paused(element), "sequence pause mismatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_play(element)
        \tif not _check(not GMRuntime.gml_layer_sequence_is_paused(element), "sequence play mismatch"):
        \t\treturn

        \tvar dynamic_sequence = GMRuntime.gml_sequence_create()
        \tdynamic_sequence["length"] = 5
        \tif not _check(GMRuntime.gml_sequence_exists(dynamic_sequence), "dynamic sequence did not exist"):
        \t\treturn
        \tif not _check(GMRuntime.gml_sequence_destroy(dynamic_sequence), "sequence_destroy failed"):
        \t\treturn

        \tvar timeline_asset = GMRuntime.gml_asset_get_index("tl_intro")
        \tif not _check(GMRuntime.gml_timeline_exists(timeline_asset), "timeline_exists failed"):
        \t\treturn
        \tif not _check(GMRuntime.gml_timeline_get_name(timeline_asset) == "tl_intro", "timeline_get_name failed"):
        \t\treturn
        \tif not _check(GMRuntime.gml_timeline_size(timeline_asset) == 1 and GMRuntime.gml_timeline_max_moment(timeline_asset) == 1, "authored timeline metadata failed"):
        \t\treturn
        \tGMRuntime.gml_timeline_moment_add_script(timeline_asset, 2, Callable(self, "_timeline_callback"))
        \tif not _check(GMRuntime.gml_timeline_size(timeline_asset) == 2 and GMRuntime.gml_timeline_max_moment(timeline_asset) == 2, "timeline moment metadata failed"):
        \t\treturn
        \ttimeline_index = timeline_asset
        \ttimeline_position = 0
        \ttimeline_speed = 1
        \ttimeline_running = true
        \tGMRuntime.gml_timeline_step(self)
        \tGMRuntime.gml_timeline_step(self)
        \tif not _check(GMRuntime.gml_global_scope().get("timeline_seed_hits", 0) == 1, "authored timeline callback did not fire"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_global_scope().get("timeline_seed_wrong_self", false), "authored timeline callback self mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_global_scope().get("timeline_hits", 0) == 1, "timeline callback did not fire"):
        \t\treturn
        \tif not _check(not GMRuntime.gml_global_scope().get("timeline_wrong_self", false), "timeline callback self mismatch"):
        \t\treturn
        \tGMRuntime.gml_timeline_moment_clear(timeline_asset, 2)
        \tif not _check(GMRuntime.gml_timeline_size(timeline_asset) == 1, "timeline clear moment failed"):
        \t\treturn

        \tGMRuntime.gml_layer_sequence_destroy(element)
        \tif not _check(not GMRuntime.gml_handle_is_valid(element), "sequence destroy did not invalidate element"):
        \t\treturn
        \tprint("SEQUENCES_TIMELINES_SMOKE_OK")
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


class TestSequencesTimelinesGodotSmoke(unittest.TestCase):
    def test_sequence_timeline_runtime_smoke_scene(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="SequenceTimelineSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_registry(project_dir)
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
        self.assertIn("SEQUENCES_TIMELINES_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
