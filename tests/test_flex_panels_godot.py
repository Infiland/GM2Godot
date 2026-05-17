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


class TestFlexPanelsGodotSmoke(unittest.TestCase):
    def test_flex_panel_runtime_computes_stable_column_layout(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _approx(value, expected):
            \treturn abs(float(value) - float(expected)) < 0.01

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tvar unit = GMRuntime.gml_flexpanel_unit()
            \tvar gutter = GMRuntime.gml_flexpanel_gutter()
            \tvar direction = GMRuntime.gml_flexpanel_direction()
            \tvar root = GMRuntime.gml_flexpanel_create_node()
            \tvar child_a = GMRuntime.gml_flexpanel_create_node({"name": "a"})
            \tvar child_b = GMRuntime.gml_flexpanel_create_node({"name": "b"})

            \tGMRuntime.gml_flexpanel_node_style_set_width(root, 100, GMRuntime.gml_selector_get(unit, "percent"))
            \tGMRuntime.gml_flexpanel_node_style_set_height(root, 100, GMRuntime.gml_selector_get(unit, "percent"))
            \tGMRuntime.gml_flexpanel_node_style_set_gap(root, GMRuntime.gml_selector_get(gutter, "row"), 10)
            \tGMRuntime.gml_flexpanel_node_style_set_width(child_a, 50, GMRuntime.gml_selector_get(unit, "percent"))
            \tGMRuntime.gml_flexpanel_node_style_set_height(child_a, 20, GMRuntime.gml_selector_get(unit, "point"))
            \tGMRuntime.gml_flexpanel_node_style_set_width(child_b, 100, GMRuntime.gml_selector_get(unit, "point"))
            \tGMRuntime.gml_flexpanel_node_style_set_height(child_b, 30, GMRuntime.gml_selector_get(unit, "point"))
            \tGMRuntime.gml_flexpanel_node_insert_child(root, child_a, 0)
            \tGMRuntime.gml_flexpanel_node_insert_child(root, child_b, 1)
            \tGMRuntime.gml_flexpanel_calculate_layout(root, 200, 100, GMRuntime.gml_selector_get(direction, "LTR"))

            \tif not _check(GMRuntime.gml_flexpanel_node_get_num_children(root) == 2, "child count failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_flexpanel_node_get_name(GMRuntime.gml_flexpanel_node_get_child(root, 1)) == "b", "child lookup failed"):
            \t\treturn

            \tvar width_style = GMRuntime.gml_flexpanel_node_style_get_width(child_a)
            \tif not _check(GMRuntime.gml_selector_get(width_style, "unit") == "percent", "width unit failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(width_style, "value"), 50), "width value failed"):
            \t\treturn

            \tvar pos_a = GMRuntime.gml_flexpanel_node_layout_get_position(child_a)
            \tvar pos_b = GMRuntime.gml_flexpanel_node_layout_get_position(child_b)
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_a, "left"), 0), "child a left failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_a, "top"), 0), "child a top failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_a, "width"), 100), "child a width failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_a, "height"), 20), "child a height failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_b, "top"), 30), "child b top failed"):
            \t\treturn
            \tif not _check(_approx(GMRuntime.gml_selector_get(pos_b, "width"), 100), "child b width failed"):
            \t\treturn

            \tprint("FLEX_PANEL_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as godot_tmp:
            project_dir = Path(godot_tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot flex panel smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("FLEX_PANEL_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
