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
        var depth = 0
        var trace = []
        var custom_draw = true

        func configure(instance_name, depth_value, trace_ref, use_custom_draw = true, is_visible = true):
        \tname = str(instance_name)
        \tdepth = int(depth_value)
        \ttrace = trace_ref
        \tcustom_draw = bool(use_custom_draw)
        \tvisible = bool(is_visible)

        func _ready():
        \tid = GMRuntime.gml_instance_register(self, "o_draw_probe", [])

        func _exit_tree():
        \tGMRuntime.gml_instance_unregister(id)

        func _on_pre_draw():
        \ttrace.append(name + ":pre")

        func _on_draw_begin():
        \ttrace.append(name + ":begin")

        func _draw():
        \tif custom_draw:
        \t\ttrace.append(name + ":draw")

        func _on_draw_end():
        \ttrace.append(name + ":end")

        func _on_post_draw():
        \ttrace.append(name + ":post")

        func _on_draw_gui_begin():
        \ttrace.append(name + ":gui_begin")

        func _on_draw_gui():
        \ttrace.append(name + ":gui")

        func _on_draw_gui_end():
        \ttrace.append(name + ":gui_end")
        """
    )
    default_probe_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

        var id = GMRuntime.gml_instance_noone()
        var depth = 0
        var trace = []

        func configure(instance_name, depth_value, trace_ref):
        \tname = str(instance_name)
        \tdepth = int(depth_value)
        \ttrace = trace_ref

        func _ready():
        \tid = GMRuntime.gml_instance_register(self, "o_default_draw_probe", [])

        func _exit_tree():
        \tGMRuntime.gml_instance_unregister(id)

        func _on_pre_draw():
        \ttrace.append(name + ":pre")

        func _on_draw_begin():
        \ttrace.append(name + ":begin")

        func _on_draw_end():
        \ttrace.append(name + ":end")
        """
    )
    smoke_script = textwrap.dedent(
        """\
        extends Node2D

        const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
        const DrawProbe = preload("res://draw_probe.gd")
        const DefaultProbe = preload("res://default_draw_probe.gd")

        func _check(condition, message):
        \tif not condition:
        \t\tpush_error(str(message))
        \t\tget_tree().quit(1)
        \t\treturn false
        \treturn true

        func _ready():
        \tvar trace = []
        \tvar front = DrawProbe.new()
        \tfront.configure("Front", -100, trace)
        \tadd_child(front)
        \tvar back = DrawProbe.new()
        \tback.configure("Back", 100, trace)
        \tadd_child(back)
        \tvar hidden = DrawProbe.new()
        \thidden.configure("Hidden", 50, trace, true, false)
        \tadd_child(hidden)
        \tvar defaulted = DefaultProbe.new()
        \tdefaulted.configure("Default", 0, trace)
        \tadd_child(defaulted)

        \tGMRuntime.gml_draw_event_trace_clear()
        \tvar dispatched = GMRuntime.gml_draw_event_dispatch_frame([front, back, hidden, defaulted])
        \tif not _check(dispatched == 20, "draw dispatch count mismatch: " + str(dispatched)):
        \t\treturn
        \tvar expected_prefix = [
        \t\t"Back:pre",
        \t\t"Default:pre",
        \t\t"Front:pre",
        \t\t"Back:begin",
        \t\t"Default:begin",
        \t\t"Front:begin",
        \t]
        \tif not _check(trace.slice(0, expected_prefix.size()) == expected_prefix, "draw depth/order mismatch: " + str(trace)):
        \t\treturn
        \tif not _check(not trace.has("Hidden:draw"), "hidden instance received draw"):
        \t\treturn
        \tif not _check(trace.find("Back:post") < trace.find("Back:gui_begin"), "GUI phase ran before Post Draw"):
        \t\treturn
        \tvar runtime_trace = GMRuntime.gml_draw_event_trace()
        \tvar default_seen = false
        \tfor entry in runtime_trace:
        \t\tif entry["kind"] == "default" and entry["instance"] == "Default":
        \t\t\tdefault_seen = true
        \tif not _check(default_seen, "default draw path was not recorded"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_exists(GMRuntime.gml_builtin_global("application_surface")), "application surface was not created"):
        \t\treturn
        \tvar surf = GMRuntime.gml_surface_create(8, 8)
        \tif not _check(GMRuntime.gml_surface_set_target(surf), "surface target could not be set"):
        \t\treturn
        \tif not _check(GMRuntime.gml_surface_target_stack_depth() == 1, "surface target stack depth did not increment"):
        \t\treturn
        \tGMRuntime.gml_surface_reset_target()
        \tif not _check(GMRuntime.gml_surface_target_stack_depth() == 0, "surface target stack depth did not reset"):
        \t\treturn
        \tGMRuntime.gml_surface_free(surf)
        \tif not _check(not GMRuntime.gml_surface_exists(surf), "surface remained valid after free"):
        \t\treturn
        \tif not _check(GMRuntime.gml_draw_event_phase_order() == ["pre_draw", "draw_begin", "draw", "draw_end", "post_draw", "draw_gui_begin", "draw_gui", "draw_gui_end"], "draw phase order mismatch"):
        \t\treturn
        \tprint("DRAW_EVENT_DISPATCH_SMOKE_OK")
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
    _write_text(project_dir / "draw_probe.gd", probe_script)
    _write_text(project_dir / "default_draw_probe.gd", default_probe_script)
    _write_text(project_dir / "smoke.gd", smoke_script)
    _write_text(project_dir / "smoke.tscn", smoke_scene)


class TestDrawEventDispatchGodotSmoke(unittest.TestCase):
    def test_draw_dispatch_order_default_draw_and_surface_stack(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DrawEventDispatchSmoke"\nrun/main_scene="res://smoke.tscn"\n',
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
        self.assertIn("DRAW_EVENT_DISPATCH_SMOKE_OK", output)


if __name__ == "__main__":
    unittest.main()
