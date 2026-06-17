from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.rooms import render_room_runtime_script


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


def _room_scene(name: str, width: int, height: int, child_lines: str = "") -> str:
    return textwrap.dedent(
        f"""\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]

        [node name="{name}" type="Node2D"]
        script = ExtResource("gm_room_runtime")
        metadata/gamemaker_room_width = {width}
        metadata/gamemaker_room_height = {height}
        metadata/gamemaker_room_persistent = false
        {child_lines}"""
    )


def _write_registry(project_dir: Path) -> None:
    registry = textwrap.dedent(
        """\
        extends RefCounted

        const FORMAT_VERSION = 1
        const ASSETS = [
          {
            "id": 100,
            "name": "r_one",
            "kind": "rooms",
            "type": "room",
            "type_name": "Room",
            "source_path": "rooms/r_one/r_one.yy",
            "godot_path": "res://rooms/r_one/r_one.tscn",
            "legacy_id": "rooms/r_one/r_one.yy",
            "tags": [],
            "dynamic": false,
            "metadata": {"room_order": 0, "width": 320, "height": 180, "persistent": false, "volume": 1.0}
          },
          {
            "id": 200,
            "name": "r_two",
            "kind": "rooms",
            "type": "room",
            "type_name": "Room",
            "source_path": "rooms/r_two/r_two.yy",
            "godot_path": "res://rooms/r_two/r_two.tscn",
            "legacy_id": "rooms/r_two/r_two.yy",
            "tags": [],
            "dynamic": false,
            "metadata": {"room_order": 1, "width": 640, "height": 360, "persistent": false, "volume": 1.0}
          }
        ]

        static func gml_asset_registry_entries():
        \treturn ASSETS
        """
    )
    _write_text(project_dir / "gm2godot" / "gml_asset_registry.gd", registry)


def _write_scripts(project_dir: Path) -> None:
    controller = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var persistent = true

        func _ready():
        \tset_meta("gamemaker_persistent", true)
        \tcall_deferred("_run")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _run():
        \tawait get_tree().process_frame
        \tif not _check(GMRuntime.gml_builtin_global("room") == GMRuntime.gml_asset_get_index("r_one"), "initial room id mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_builtin_global("room_width") == 320 and GMRuntime.gml_builtin_global("room_height") == 180, "initial room size mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_room_exists(GMRuntime.gml_asset_get_index("r_two")), "room_exists failed"):
        \t\treturn
        \tif not _check(GMRuntime.gml_room_get_name(GMRuntime.gml_asset_get_index("r_two")) == "r_two", "room_get_name failed"):
        \t\treturn
        \tvar info = GMRuntime.gml_room_get_info(GMRuntime.gml_asset_get_index("r_two"))
        \tif not _check(info["width"] == 640 and info["order"] == 1, "room_get_info metadata mismatch"):
        \t\treturn
        \tif not _check(GMRuntime.gml_room_goto_next(), "room_goto_next failed"):
        \t\treturn
        \tawait get_tree().process_frame
        \tif not _check(get_tree().current_scene.name == "r_two", "did not transition to r_two"):
        \t\treturn
        \tif not _check(GMRuntime.gml_builtin_global("room_width") == 640 and GMRuntime.gml_builtin_global("room_height") == 360, "second room size mismatch"):
        \t\treturn
        \tif not _check(get_tree().current_scene.find_child("PersistentProbe", true, false) != null, "persistent probe did not survive transition"):
        \t\treturn
        \tif not _check(GMRuntime.gml_room_restart(), "room_restart failed"):
        \t\treturn
        \tawait get_tree().process_frame
        \tif not _check(get_tree().current_scene.name == "r_two", "restart changed room"):
        \t\treturn
        \tif not _check(GMRuntime.gml_room_goto_previous(), "room_goto_previous failed"):
        \t\treturn
        \tawait get_tree().process_frame
        \tif not _check(get_tree().current_scene.name == "r_one", "did not transition back to r_one"):
        \t\treturn
        \tvar events = GMRuntime.gml_global_scope()["events"]
        \tif not _check(events.has("game_start:PersistentProbe"), "game_start lifecycle missing"):
        \t\treturn
        \tif not _check(events.count("room_start:PersistentProbe") >= 3, "room_start lifecycle count too low"):
        \t\treturn
        \tif not _check(events.count("room_end:PersistentProbe") >= 3, "room_end lifecycle count too low"):
        \t\treturn
        \tprint("ROOM_GAME_FLOW_SMOKE_OK")
        \tget_tree().quit(0)
        """
    )
    probe = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var id = GMRuntime.gml_instance_noone()
        var persistent = true

        func _ready():
        \tif not GMRuntime.gml_global_scope().has("events"):
        \t\tGMRuntime.gml_global_scope()["events"] = []
        \tset_meta("gamemaker_persistent", true)
        \tid = GMRuntime.gml_instance_register(self, "o_probe", [])
        \tGMRuntime.gml_variable_instance_set(self, "persistent", persistent)

        func _exit_tree():
        \tif has_meta("_gm2godot_room_preserving_persistent") and get_meta("_gm2godot_room_preserving_persistent"):
        \t\treturn
        \tGMRuntime.gml_instance_unregister(id)

        func _on_game_start():
        \tGMRuntime.gml_global_scope()["events"].append("game_start:" + name)

        func _on_room_start():
        \tGMRuntime.gml_global_scope()["events"].append("room_start:" + name)

        func _on_room_end():
        \tGMRuntime.gml_global_scope()["events"].append("room_end:" + name)

        func _on_game_end():
        \tGMRuntime.gml_global_scope()["events"].append("game_end:" + name)
        """
    )
    _write_text(project_dir / "controller.gd", controller)
    _write_text(project_dir / "probe.gd", probe)


class TestRoomGameFlowGodotSmoke(unittest.TestCase):
    def test_room_runtime_updates_view_follow_and_scrolling_background(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="RoomRuntimeBehaviorSmoke"\nrun/main_scene="res://rooms/r_one/r_one.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_registry(project_dir)
            _write_text(
                project_dir / "target.gd",
                textwrap.dedent(
                    """\
                    extends Node2D

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    var _gm_handle = GMRuntime.gml_instance_noone()

                    func _ready():
                    \tposition = Vector2(300, 20)
                    \t_gm_handle = GMRuntime.gml_instance_register(self, "o_player", [])

                    func _exit_tree():
                    \tGMRuntime.gml_instance_unregister(_gm_handle)
                    """
                ),
            )
            _write_text(
                project_dir / "controller.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    func _ready():
                    \tcall_deferred("_run")

                    func _check(condition, message):
                    \tif not condition:
                    \t\tpush_error(str(message))
                    \t\tget_tree().quit(1)
                    \t\treturn false
                    \treturn true

                    func _run():
                    \tawait get_tree().process_frame
                    \tawait get_tree().process_frame
                    \tvar room = get_parent()
                    \tvar camera = room.get_node("ViewCamera")
                    \tvar background = room.get_node("Backgrounds/BackgroundVisual")
                    \tif not _check(abs(camera.position.x - 260.0) < 0.01, "Camera2D did not follow target on x"):
                    \t\treturn
                    \tif not _check(background.scroll_offset.x > 0.0, "Background Parallax2D did not scroll"):
                    \t\treturn
                    \tprint("ROOM_RUNTIME_BEHAVIOR_SMOKE_OK")
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(
                project_dir / "rooms" / "r_one" / "r_one.tscn",
                textwrap.dedent(
                    """\
                    [gd_scene load_steps=4 format=3]

                    [ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]
                    [ext_resource type="Script" path="res://controller.gd" id="controller"]
                    [ext_resource type="Script" path="res://target.gd" id="target"]

                    [node name="r_one" type="Node2D"]
                    script = ExtResource("gm_room_runtime")
                    metadata/gamemaker_room_width = 320
                    metadata/gamemaker_room_height = 180
                    metadata/gamemaker_room_persistent = false

                    [node name="ViewCamera" type="Camera2D" parent="."]
                    position = Vector2(50, 50)
                    enabled = true
                    metadata/gamemaker_view_camera = true
                    metadata/gamemaker_view_enabled_camera = true
                    metadata/gamemaker_view_visible = true
                    metadata/gamemaker_view_index = 0
                    metadata/gamemaker_view_xview = 0
                    metadata/gamemaker_view_yview = 0
                    metadata/gamemaker_view_wview = 100
                    metadata/gamemaker_view_hview = 100
                    metadata/gamemaker_view_xport = 0
                    metadata/gamemaker_view_yport = 0
                    metadata/gamemaker_view_wport = 100
                    metadata/gamemaker_view_hport = 100
                    metadata/gamemaker_view_object_name = "o_player"
                    metadata/gamemaker_view_hborder = 10
                    metadata/gamemaker_view_vborder = 10
                    metadata/gamemaker_view_hspeed = -1
                    metadata/gamemaker_view_vspeed = -1

                    [node name="Backgrounds" type="Node2D" parent="."]
                    metadata/gamemaker_layer_name = "Backgrounds"
                    metadata/gamemaker_layer_type = "GMRBackgroundLayer"

                    [node name="BackgroundVisual" type="Parallax2D" parent="Backgrounds"]
                    repeat_size = Vector2(320, 0)
                    repeat_times = 3
                    scroll_offset = Vector2(0, 0)
                    metadata/gamemaker_layer_element_type = "background"
                    metadata/gamemaker_background_visual = true
                    metadata/gamemaker_background_hspeed = 2
                    metadata/gamemaker_background_vspeed = 0
                    metadata/gamemaker_background_runtime_support = true

                    [node name="Target" type="Node2D" parent="."]
                    script = ExtResource("target")

                    [node name="Controller" type="Node" parent="."]
                    script = ExtResource("controller")
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
                    "res://rooms/r_one/r_one.tscn",
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
        self.assertIn("ROOM_RUNTIME_BEHAVIOR_SMOKE_OK", output)

    def test_room_creation_code_lifecycle_trace_order(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="RoomLifecycleSmoke"\nrun/main_scene="res://rooms/r_one/r_one.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_registry(project_dir)
            _write_text(
                project_dir / "probe.gd",
                textwrap.dedent(
                    """\
                    extends Node2D

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    func _ready():
                    \tGMRuntime.gml_global_scope()["trace"] = []
                    \tGMRuntime.gml_global_scope()["trace"].append("object_create")

                    func _on_game_start():
                    \tGMRuntime.gml_global_scope()["trace"].append("game_start")

                    func _on_room_start():
                    \tGMRuntime.gml_global_scope()["trace"].append("room_start")
                    \tcall_deferred("_verify_trace")

                    func _verify_trace():
                    \tvar expected = ["object_create", "instance_creation_code", "game_start", "room_creation_code", "room_start"]
                    \tvar trace = GMRuntime.gml_global_scope()["trace"]
                    \tif trace != expected:
                    \t\tpush_error("Lifecycle trace mismatch: " + str(trace))
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tif GMRuntime.gml_variable_instance_get(self, "creation_ran") != true:
                    \t\tpush_error("Instance creation code did not run against the instance scope")
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tif int(position.x) != 42:
                    \t\tpush_error("Instance creation code did not update scoped x")
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tprint("ROOM_CREATION_LIFECYCLE_TRACE_OK")
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(
                project_dir / "rooms" / "r_one" / "r_one.gd",
                textwrap.dedent(
                    """\
                    extends "res://gm2godot/gml_room_node.gd"

                    func _gm2godot_run_instance_creation_code(_gm_instance):
                    \tif _gm_instance == null:
                    \t\treturn false
                    \tif str(_gm_instance.get_meta("gamemaker_creation_code_source_path")) != "rooms/r_one/InstanceCreationCode_Probe.gml":
                    \t\treturn false
                    \tGMRuntime.gml_global_scope()["trace"].append("instance_creation_code")
                    \tGMRuntime.gml_variable_instance_set(_gm_instance, "creation_ran", true)
                    \tGMRuntime.gml_variable_instance_set(_gm_instance, "x", 42)
                    \treturn true

                    func _gm2godot_room_creation_code():
                    \tGMRuntime.gml_global_scope()["trace"].append("room_creation_code")
                    """
                ),
            )
            _write_text(
                project_dir / "rooms" / "r_one" / "r_one.tscn",
                textwrap.dedent(
                    """\
                    [gd_scene load_steps=3 format=3]

                    [ext_resource type="Script" path="res://rooms/r_one/r_one.gd" id="gm_room_runtime"]
                    [ext_resource type="Script" path="res://probe.gd" id="probe"]

                    [node name="r_one" type="Node2D"]
                    script = ExtResource("gm_room_runtime")
                    metadata/gamemaker_room_width = 320
                    metadata/gamemaker_room_height = 180
                    metadata/gamemaker_room_persistent = false

                    [node name="Probe" type="Node2D" parent="."]
                    script = ExtResource("probe")
                    metadata/gamemaker_instance_name = "Probe"
                    metadata/gamemaker_has_creation_code = true
                    metadata/gamemaker_creation_code_file_exists = true
                    metadata/gamemaker_creation_code_source_path = "rooms/r_one/InstanceCreationCode_Probe.gml"
                    metadata/gamemaker_instance_creation_order_index = 0
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
                    "res://rooms/r_one/r_one.tscn",
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
        self.assertIn("ROOM_CREATION_LIFECYCLE_TRACE_OK", output)

    def test_room_runtime_transitions_lifecycle_and_persistent_nodes(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="RoomFlowSmoke"\nrun/main_scene="res://rooms/r_one/r_one.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "gm2godot" / "gml_room_node.gd", render_room_runtime_script())
            _write_registry(project_dir)
            _write_scripts(project_dir)
            _write_text(
                project_dir / "rooms" / "r_one" / "r_one.tscn",
                _room_scene(
                    "r_one",
                    320,
                    180,
                    textwrap.dedent(
                        """\

                        [node name="Controller" type="Node2D" parent="."]
                        script = ExtResource("controller")

                        [node name="PersistentProbe" type="Node2D" parent="."]
                        script = ExtResource("probe")
                        """
                    ),
                ).replace(
                    '[ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]',
                    '[ext_resource type="Script" path="res://gm2godot/gml_room_node.gd" id="gm_room_runtime"]\n'
                    '[ext_resource type="Script" path="res://controller.gd" id="controller"]\n'
                    '[ext_resource type="Script" path="res://probe.gd" id="probe"]',
                ).replace("[gd_scene load_steps=2 format=3]", "[gd_scene load_steps=4 format=3]"),
            )
            _write_text(
                project_dir / "rooms" / "r_two" / "r_two.tscn",
                _room_scene("r_two", 640, 360),
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
                    "res://rooms/r_one/r_one.tscn",
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
        self.assertIn("ROOM_GAME_FLOW_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
