from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import cast

from src.conversion.asset_registry import (
    AssetRegistryConverter,
    AssetRegistryEntry,
    render_asset_registry_script,
)
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.sequence_assets import (
    normalize_sequence_asset,
    render_sequence_resource,
)
from src.conversion.type_defs import JsonDict


AUTHORED_SEQUENCE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "authored_sequences" / "fixture.json"
)


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


def _authored_sequence_descriptors() -> tuple[JsonDict, JsonDict]:
    with AUTHORED_SEQUENCE_FIXTURE.open(encoding="utf-8") as fixture_file:
        fixture = cast(JsonDict, json.load(fixture_file))
    root, root_issues = normalize_sequence_asset(cast(JsonDict, fixture["root"]))
    nested, nested_issues = normalize_sequence_asset(
        cast(JsonDict, fixture["nested"])
    )
    if root_issues or nested_issues:
        raise AssertionError((root_issues, nested_issues))
    return root, nested


def _write_authored_registry(project_dir: Path) -> None:
    root, nested = _authored_sequence_descriptors()
    fps_sequence = cast(JsonDict, json.loads(json.dumps(root)))
    fps_sequence["name"] = "seq_fps"
    fps_sequence["length"] = 10.0
    fps_sequence["playback_speed"] = 4.0
    fps_sequence["playback_speed_type"] = 0
    fps_sequence["tracks"] = []
    fps_sequence["moments"] = []
    fps_sequence["broadcasts"] = []
    loop_sequence = cast(JsonDict, json.loads(json.dumps(fps_sequence)))
    loop_sequence["name"] = "seq_loop"
    loop_sequence["length"] = 4.0
    loop_sequence["loopmode"] = 1
    pingpong_sequence = cast(JsonDict, json.loads(json.dumps(loop_sequence)))
    pingpong_sequence["name"] = "seq_pingpong"
    pingpong_sequence["loopmode"] = 2
    entries = [
        AssetRegistryEntry(
            id=500,
            name="seq_authored",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_authored/seq_authored.yy",
            godot_path="res://sequences/seq_authored/seq_authored.tres",
            legacy_id="sequences/seq_authored/seq_authored.yy",
            metadata=root,
        ),
        AssetRegistryEntry(
            id=501,
            name="seq_nested",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_nested/seq_nested.yy",
            godot_path="res://sequences/seq_nested/seq_nested.tres",
            legacy_id="sequences/seq_nested/seq_nested.yy",
            metadata=nested,
        ),
        AssetRegistryEntry(
            id=502,
            name="seq_fps",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_fps/seq_fps.yy",
            godot_path="res://sequences/seq_fps/seq_fps.tres",
            legacy_id="sequences/seq_fps/seq_fps.yy",
            metadata=fps_sequence,
        ),
        AssetRegistryEntry(
            id=503,
            name="seq_loop",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_loop/seq_loop.yy",
            godot_path="res://sequences/seq_loop/seq_loop.tres",
            legacy_id="sequences/seq_loop/seq_loop.yy",
            metadata=loop_sequence,
        ),
        AssetRegistryEntry(
            id=504,
            name="seq_pingpong",
            kind="sequences",
            asset_type="sequence",
            type_name="Sequence",
            source_path="sequences/seq_pingpong/seq_pingpong.yy",
            godot_path="res://sequences/seq_pingpong/seq_pingpong.tres",
            legacy_id="sequences/seq_pingpong/seq_pingpong.yy",
            metadata=pingpong_sequence,
        ),
    ]
    asset_specs = (
        (510, "spr_hero", "sprites", "sprite", "Sprite"),
        (511, "spr_nested", "sprites", "sprite", "Sprite"),
        (512, "obj_actor", "objects", "object", "Object"),
        (513, "snd_theme", "sounds", "sound", "Sound"),
        (514, "fnt_caption", "fonts", "font", "Font"),
    )
    for asset_id, name, kind, asset_type, type_name in asset_specs:
        entries.append(
            AssetRegistryEntry(
                id=asset_id,
                name=name,
                kind=kind,
                asset_type=asset_type,
                type_name=type_name,
                source_path=f"{kind}/{name}/{name}.yy",
                godot_path="",
                legacy_id=f"{kind}/{name}/{name}.yy",
                metadata={},
            )
        )
    for entry in entries[:5]:
        assert entry.metadata is not None
        _write_text(
            project_dir
            / Path(entry.godot_path.removeprefix("res://")),
            render_sequence_resource(
                entry.name,
                entry.source_path,
                entry.metadata,
            ),
        )
    _write_text(
        project_dir / "gm2godot" / "gml_asset_registry.gd",
        render_asset_registry_script(tuple(entries)),
    )


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

        func _timeline_loop_zero(instance):
        \tif instance == self:
        \t\tGMRuntime.gml_global_scope()["timeline_loop_order"] = GMRuntime.gml_global_scope().get("timeline_loop_order", "") + "0"

        func _timeline_loop_one(instance):
        \tif instance == self:
        \t\tGMRuntime.gml_global_scope()["timeline_loop_order"] = GMRuntime.gml_global_scope().get("timeline_loop_order", "") + "1"

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
        \tGMRuntime.gml_timeline_moment_add_script(timeline_asset, 0, Callable(self, "_timeline_loop_zero"))
        \tGMRuntime.gml_timeline_moment_add_script(timeline_asset, 1, Callable(self, "_timeline_loop_one"))
        \tGMRuntime.gml_global_scope()["timeline_loop_order"] = ""
        \ttimeline_position = 1
        \ttimeline_speed = 2
        \ttimeline_loop = true
        \tGMRuntime.gml_timeline_step(self)
        \tif not _check(GMRuntime.gml_global_scope().get("timeline_loop_order", "") == "01" and timeline_position == 1, "wrapped timeline moments were skipped or reordered"):
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


def _write_authored_smoke_scene(project_dir: Path) -> None:
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var dispatch_order = []

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _moment_a(_sequence_self, _sequence_other):
        \tdispatch_order.append("moment_a")

        func _moment_b(_sequence_self, _sequence_other):
        \tdispatch_order.append("moment_b")

        func _on_broadcast_message():
        \tvar event_data = GMRuntime.gml_builtin_global("event_data")
        \tdispatch_order.append("broadcast:" + str(event_data.get("message", "")))

        func _ready():
        \tGMRuntime.gml_instance_register(self, "sequence_listener", [])
        \tGMRuntime.gml_script_register("seq_moment_a", Callable(self, "_moment_a"))
        \tGMRuntime.gml_script_register("seq_moment_b", Callable(self, "_moment_b"))

        \tvar layer = Node2D.new()
        \tlayer.name = "Sequences"
        \tlayer.set_meta("gamemaker_layer_name", "Sequences")
        \tlayer.set_meta("gamemaker_layer_depth", 100)
        \tadd_child(layer)
        \tGMRuntime.gml_layer_register_scene(self)

        \tvar sequence_asset = GMRuntime.gml_asset_get_index("seq_authored")
        \tvar descriptor_resource = load("res://sequences/seq_authored/seq_authored.tres")
        \tif not _check(descriptor_resource is Resource and descriptor_resource.has_meta("gamemaker_sequence_descriptor"), "generated sequence resource did not load"):
        \t\treturn
        \tvar element = GMRuntime.gml_layer_sequence_create("Sequences", 10, 20, sequence_asset)
        \tif not _check(GMRuntime.gml_handle_is_valid(element), "authored sequence handle invalid"):
        \t\treturn
        \tvar instance = GMRuntime.gml_layer_sequence_get_instance(element)
        \tif not _check(instance["activeTracks"].is_empty(), "active tracks populated before first sequence update"):
        \t\treturn
        \tif not _check(instance["sequence"]["playbackSpeed"] == 2.0 and instance["sequence"]["playbackSpeedType"] == 1, "playback speed metadata mismatch"):
        \t\treturn
        \tif not _check(instance["sequence"]["xorigin"] == 3.0 and instance["sequence"]["yorigin"] == 4.0, "sequence origin metadata mismatch"):
        \t\treturn
        \tvar states = instance["trackStates"]
        \tif not _check(states[0]["node"].z_index > states[1]["node"].z_index, "track draw order mismatch"):
        \t\treturn
        \tif not _check(states[1]["contents"].size() == 1, "instance track was not created eagerly"):
        \t\treturn
        \tvar actor = states[1]["contents"].values()[0]
        \tif not _check(actor is Node and GMRuntime.gml_variable_instance_get(actor, "in_sequence") == true and not states[1]["node"].visible, "inactive eager instance track mismatch"):
        \t\treturn

        \tGMRuntime.gml_layer_sequence_step(element, 2)
        \tif not _check(dispatch_order == ["moment_a", "moment_b", "broadcast:first", "broadcast:second"], "moment/broadcast dispatch order mismatch: " + str(dispatch_order)):
        \t\treturn
        \tif not _check(instance["activeTracks"].size() == 5, "authored track order/size mismatch"):
        \t\treturn
        \tif not _check(instance["activeTracks"][1]["instanceID"] == actor, "eager instance track ID mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_variable_instance_get(actor, "x") == 7.0 and GMRuntime.gml_variable_instance_get(actor, "y") == 16.0, "sequence object transform did not publish GameMaker coordinates"):
        \t\treturn
        \tif not _check(is_equal_approx(instance["activeTracks"][0]["posx"], 4.0) and is_equal_approx(instance["activeTracks"][0]["posy"], 2.0), "linear position interpolation mismatch"):
        \t\treturn
        \tif not _check(states[0]["node"].position == Vector2(1, -2), "sequence origin transform mismatch"):
        \t\treturn
        \tif not _check(instance["activeTracks"][0]["matrix"].origin == Vector2(1, -2), "active track matrix mismatch"):
        \t\treturn
        \tif not _check(is_equal_approx(states[0]["node"].rotation_degrees, -30.0), "GameMaker rotation transform mismatch"):
        \t\treturn
        \tif not _check(states[0]["node"].modulate == Color(1, 0, 0, 1), "colour multiply mismatch"):
        \t\treturn

        \tvar audio_bus_name = str(states[2]["audio_bus"])
        \tvar audio_bus = AudioServer.get_bus_index(audio_bus_name)
        \tif not _check(audio_bus >= 0 and AudioServer.get_bus_effect_count(audio_bus) == 1, "audio effect bus/order mismatch"):
        \t\treturn
        \tvar gain_effect = AudioServer.get_bus_effect(audio_bus, 0)
        \tif not _check(gain_effect is AudioEffectAmplify and is_equal_approx(gain_effect.volume_linear, 0.75), "audio effect key interpolation mismatch"):
        \t\treturn

        \tvar label = states[3]["contents"].values()[0]
        \tif not _check(label is Label and label.text == "Hello" and label.size == Vector2(160, 40), "text track key/frame mismatch: " + str(label) + " / " + str(label.text if label is Label else "") + " / " + str(label.size if label is Control else Vector2.ZERO)):
        \t\treturn
        \tvar font_variation = label.get_meta("gamemaker_sequence_font_variation")
        \tif not _check(font_variation is FontVariation and font_variation.spacing_glyph == 2, "text character spacing mismatch"):
        \t\treturn
        \tif not _check(label.get_theme_constant("outline_size") == 2, "text effect parameter mismatch"):
        \t\treturn

        \tvar nested = states[4]["nested"][0]
        \tif not _check(is_equal_approx(nested["headPosition"], 2.0), "nested sequence playback mismatch"):
        \t\treturn
        \tif not _check(nested["activeTracks"].size() == 1 and nested["activeTracks"][0]["posx"] == 1.0 and nested["activeTracks"][0]["posy"] == 2.0, "nested sequence transform mismatch"):
        \t\treturn

        \tGMRuntime.gml_layer_sequence_pause(element)
        \tvar automatic = GMRuntime.gml_layer_sequence_create("Sequences", 0, 0, sequence_asset)
        \tvar automatic_instance = GMRuntime.gml_layer_sequence_get_instance(automatic)
        \tvar automatic_bus_name = str(automatic_instance["trackStates"][2]["audio_bus"])
        \tGMRuntime.gml_sequence_timeline_scheduler_frame(0.0, 1, [], -1)
        \tif not _check(is_equal_approx(automatic_instance["headPosition"], 2.0), "frames-per-game-frame playback speed mismatch"):
        \t\treturn
        \tGMRuntime.gml_layer_sequence_pause(automatic)
        \tvar fps_element = GMRuntime.gml_layer_sequence_create("Sequences", 0, 0, GMRuntime.gml_asset_get_index("seq_fps"))
        \tvar fps_instance = GMRuntime.gml_layer_sequence_get_instance(fps_element)
        \tGMRuntime.gml_sequence_timeline_scheduler_frame(0.25, 1, [], -1)
        \tif not _check(is_equal_approx(fps_instance["headPosition"], 1.0), "frames-per-second playback speed mismatch"):
        \t\treturn
        \tvar loop_element = GMRuntime.gml_layer_sequence_create("Sequences", 0, 0, GMRuntime.gml_asset_get_index("seq_loop"))
        \tGMRuntime.gml_layer_sequence_step(loop_element, 6)
        \tif not _check(is_equal_approx(GMRuntime.gml_layer_sequence_get_headpos(loop_element), 2.0), "loop playback boundary mismatch"):
        \t\treturn
        \tvar pingpong_element = GMRuntime.gml_layer_sequence_create("Sequences", 0, 0, GMRuntime.gml_asset_get_index("seq_pingpong"))
        \tGMRuntime.gml_layer_sequence_step(pingpong_element, 6)
        \tif not _check(is_equal_approx(GMRuntime.gml_layer_sequence_get_headpos(pingpong_element), 2.0) and GMRuntime.gml_layer_sequence_get_headdir(pingpong_element) == -1, "ping-pong playback boundary mismatch"):
        \t\treturn

        \tGMRuntime.gml_layer_sequence_destroy(pingpong_element)
        \tGMRuntime.gml_layer_sequence_destroy(loop_element)
        \tGMRuntime.gml_layer_sequence_destroy(fps_element)
        \tGMRuntime.gml_layer_sequence_destroy(automatic)
        \tGMRuntime.gml_layer_sequence_destroy(element)
        \tif not _check(AudioServer.get_bus_index(audio_bus_name) == -1 and AudioServer.get_bus_index(automatic_bus_name) == -1, "sequence audio bus cleanup mismatch"):
        \t\treturn
        \tprint("AUTHORED_SEQUENCES_TIMELINES_OK")
        \tget_tree().quit(0)
        """
    )
    smoke_scene = textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://authored_smoke.gd" id="1"]

        [node name="AuthoredSmoke" type="Node2D"]
        script = ExtResource("1")
        """
    )
    _write_text(project_dir / "authored_smoke.gd", smoke_script)
    _write_text(project_dir / "authored_smoke.tscn", smoke_scene)


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

    def test_authored_track_keyframe_playback_and_order(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                (
                    '[application]\nconfig/name="AuthoredSequenceSmoke"\n'
                    'run/main_scene="res://authored_smoke.tscn"\n'
                ),
            )
            write_gml_runtime(str(project_dir))
            _write_authored_registry(project_dir)
            _write_authored_smoke_scene(project_dir)

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
                    "res://authored_smoke.tscn",
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
        self.assertIn("AUTHORED_SEQUENCES_TIMELINES_OK", output)

    def test_converted_timeline_gml_runs_in_frame_order(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            gm_dir = case_dir / "gamemaker"
            project_dir = case_dir / "godot"
            timeline_dir = gm_dir / "timelines" / "tl_order"
            timeline_dir.mkdir(parents=True)
            project_dir.mkdir()
            _write_text(
                gm_dir / "TimelineOrder.yyp",
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": "tl_order",
                                    "path": "timelines/tl_order/tl_order.yy",
                                }
                            }
                        ],
                        "resourceType": "GMProject",
                    }
                ),
            )
            _write_text(
                timeline_dir / "tl_order.yy",
                json.dumps(
                    {
                        "$GMTimeline": "v1",
                        "%Name": "tl_order",
                        "name": "tl_order",
                        "resourceType": "GMTimeline",
                        "momentList": [
                            {
                                "moment": frame,
                                "eventFile": f"Moment_{frame}.gml",
                            }
                            for frame in (1, 2, 3)
                        ],
                    }
                ),
            )
            for frame, marker in ((1, "A"), (2, "B"), (3, "C")):
                _write_text(
                    timeline_dir / f"Moment_{frame}.gml",
                    f'global.timeline_order = global.timeline_order + "{marker}";\n',
                )
            _write_text(
                project_dir / "project.godot",
                (
                    '[application]\nconfig/name="TimelineOrderSmoke"\n'
                    'run/main_scene="res://timeline_smoke.tscn"\n'
                ),
            )
            AssetRegistryConverter(
                str(gm_dir),
                str(project_dir),
            ).convert_all()
            write_gml_runtime(str(project_dir))
            _write_text(
                project_dir / "timeline_smoke.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    var timeline_index = -1
                    var timeline_position = 0.0
                    var timeline_speed = 3.0
                    var timeline_running = true
                    var timeline_loop = false

                    func _ready():
                    \tGMRuntime.gml_global_scope()["timeline_order"] = ""
                    \ttimeline_index = GMRuntime.gml_asset_get_index("tl_order")
                    \tif not GMRuntime.gml_timeline_step(self):
                    \t\tpush_error("timeline step failed")
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tvar order = GMRuntime.gml_global_scope().get("timeline_order", "")
                    \tif order != "ABC":
                    \t\tpush_error("timeline GML order mismatch: " + str(order))
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tprint("TIMELINE_GML_ORDER_OK")
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(
                project_dir / "timeline_smoke.tscn",
                textwrap.dedent(
                    """\
                    [gd_scene load_steps=2 format=3]

                    [ext_resource type="Script" path="res://timeline_smoke.gd" id="1"]

                    [node name="TimelineSmoke" type="Node"]
                    script = ExtResource("1")
                    """
                ),
            )

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
                    "res://timeline_smoke.tscn",
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
        self.assertIn("TIMELINE_GML_ORDER_OK", output)


class TestAuthoredSequenceDescriptor(unittest.TestCase):
    def test_mixed_current_lts_fixture_normalizes_exact_supported_tracks(self) -> None:
        root, nested = _authored_sequence_descriptors()

        self.assertTrue(root["complete"])
        self.assertEqual(root["descriptor_format_version"], 1)
        self.assertEqual(root["length"], 8.0)
        self.assertEqual(root["playback_speed"], 2.0)
        self.assertEqual(root["playback_speed_type"], 1)
        self.assertEqual(
            [track["kind"] for track in root["tracks"]],
            ["sprite", "instance", "audio", "text", "sequence"],
        )
        self.assertEqual(
            root["tracks"][0]["parameters"][0]["interpolation"],
            1,
        )
        self.assertEqual(
            root["tracks"][0]["parameters"][2]["keyframes"][0]["values"][0],
            [1.0, 1.0, 0.0, 0.0],
        )
        self.assertEqual(
            root["tracks"][2]["parameters"][1]["effect_type"],
            "gain",
        )
        self.assertEqual(
            [moment["script"] for moment in root["moments"]],
            ["seq_moment_a", "seq_moment_b"],
        )
        self.assertEqual(
            [event["message"] for event in root["broadcasts"]],
            ["first", "second"],
        )
        self.assertEqual(nested["tracks"][0]["keyframes"][0]["asset"], "spr_nested")

    def test_unsupported_tracks_keys_and_curves_fail_closed_with_paths(self) -> None:
        raw: JsonDict = {
            "name": "seq_unsupported",
            "length": 10,
            "tracks": [
                {
                    "resourceType": "GMClipMaskTrack",
                    "name": "Mask",
                },
                {
                    "resourceType": "GMGraphicTrack",
                    "name": "Sprite",
                    "keyframes": {
                        "Keyframes": [
                            {
                                "Channels": {
                                    "1": {
                                        "resourceType": "UnknownSpriteKey",
                                        "Id": {"name": "spr_bad"},
                                    }
                                }
                            }
                        ]
                    },
                    "tracks": [
                        {
                            "resourceType": "GMRealTrack",
                            "name": "position",
                            "interpolation": 1,
                            "keyframes": {
                                "Keyframes": [
                                    {
                                        "Channels": {
                                            "0": {
                                                "resourceType": "RealKeyframe",
                                                "RealValue": 0,
                                                "EmbeddedAnimCurve": {
                                                    "channels": []
                                                },
                                            }
                                        }
                                    }
                                ]
                            },
                            "tracks": [],
                        }
                    ],
                },
                {
                    "resourceType": "GMAudioTrack",
                    "name": "Unsupported Effect",
                    "keyframes": {
                        "Keyframes": [
                            {
                                "Channels": {
                                    "0": {
                                        "resourceType": "AudioKeyframe",
                                        "Id": {"name": "snd_test"},
                                    }
                                },
                                "Length": 10,
                            }
                        ]
                    },
                    "tracks": [
                        {
                            "resourceType": "GMAudioEffectTrack",
                            "name": "audioEffect_bitcrusher",
                            "effectType": "bitcrusher",
                            "tracks": [],
                        }
                    ],
                },
            ],
            "events": {"Keyframes": []},
            "moments": {"Keyframes": []},
        }

        descriptor, issues = normalize_sequence_asset(raw)

        self.assertFalse(descriptor["complete"])
        self.assertEqual(descriptor["tracks"][0]["keyframes"], [])
        self.assertEqual(descriptor["tracks"][0]["parameters"][0]["keyframes"], [])
        self.assertEqual(
            {issue.code for issue in issues},
            {
                "GM2GD-SEQUENCE-EFFECT-UNSUPPORTED",
                "GM2GD-SEQUENCE-TRACK-UNSUPPORTED",
                "GM2GD-SEQUENCE-KEY-UNSUPPORTED",
            },
        )
        self.assertIn("tracks[0]", {issue.manifest_entry for issue in issues})
        self.assertTrue(
            any(
                issue.manifest_entry.endswith("EmbeddedAnimCurve")
                for issue in issues
            )
        )


if __name__ == "__main__":
    unittest.main()
