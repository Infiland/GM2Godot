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


class TestArrayDeleteGodotSmoke(unittest.TestCase):
    def test_array_delete_matches_lts_offset_length_and_return_semantics(self) -> None:
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

            func _ready():
            \tvar forward = [0, 1, 2, 3, 4, 5]
            \tvar forward_alias = forward
            \tvar result = GMRuntime.gml_array_delete(forward, 2, 3)
            \tif not _check(forward == [0, 1, 5], "forward delete mismatch"):
            \t\treturn
            \tif not _check(forward_alias == [0, 1, 5], "array reference was not mutated"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(result), "N/A return must be undefined"):
            \t\treturn

            \tvar backward = ["a", "b", "c", "d", "e", -1, -1, -1]
            \tGMRuntime.gml_array_delete(backward, -1, -3)
            \tif not _check(backward == ["a", "b", "c", "d", "e"], "backward delete mismatch"):
            \t\treturn

            \tvar negative_offset = [0, 1, 2, 3, 4, 5]
            \tGMRuntime.gml_array_delete(negative_offset, -3, 3)
            \tif not _check(negative_offset == [0, 1, 2], "negative offset mismatch"):
            \t\treturn

            \tvar high_offset = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(high_offset, 99, 1)
            \tif not _check(high_offset == [0, 1, 2], "high offset clamp mismatch"):
            \t\treturn

            \tvar low_offset = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(low_offset, -99, 1)
            \tif not _check(low_offset == [1, 2, 3], "low offset clamp mismatch"):
            \t\treturn

            \tvar low_infinity_offset = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(low_infinity_offset, -INF, 1)
            \tif not _check(low_infinity_offset == [1, 2, 3], "negative infinity offset mismatch"):
            \t\treturn

            \tvar high_infinity_offset = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(high_infinity_offset, INF, 1)
            \tif not _check(high_infinity_offset == [0, 1, 2], "positive infinity offset mismatch"):
            \t\treturn

            \tvar forward_range_clamp = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(forward_range_clamp, 2, 99)
            \tif not _check(forward_range_clamp == [0, 1], "forward range clamp mismatch"):
            \t\treturn

            \tvar backward_range_clamp = [0, 1, 2, 3]
            \tGMRuntime.gml_array_delete(backward_range_clamp, 1, -99)
            \tif not _check(backward_range_clamp == [2, 3], "backward range clamp mismatch"):
            \t\treturn

            \tvar forward_infinity = [0, 1, 2, 3, 4]
            \tGMRuntime.gml_array_delete(forward_infinity, 2, INF)
            \tif not _check(forward_infinity == [0, 1], "positive infinity mismatch"):
            \t\treturn

            \tvar backward_infinity = [0, 1, 2, 3, 4]
            \tGMRuntime.gml_array_delete(backward_infinity, 2, -INF)
            \tif not _check(backward_infinity == [3, 4], "negative infinity mismatch"):
            \t\treturn

            \tvar zero_count = [0, 1, 2]
            \tGMRuntime.gml_array_delete(zero_count, 1, 0)
            \tif not _check(zero_count == [0, 1, 2], "zero count should not mutate"):
            \t\treturn

            \tvar empty = []
            \tvar empty_result = GMRuntime.gml_array_delete(empty, 0, 1)
            \tif not _check(empty.is_empty(), "empty array should remain empty"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(empty_result), "empty return must be undefined"):
            \t\treturn

            \tprint("ARRAY_DELETE_LTS_OK")
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
                output = (
                    exc.output.decode("utf-8", errors="replace")
                    if isinstance(exc.output, bytes)
                    else str(exc.output or "")
                )
                self.fail("Godot array_delete smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            result.stdout.count(
                "array_delete: requested range exceeded array bounds and was clamped"
            ),
            6,
            result.stdout,
        )
        self.assertIn("ARRAY_DELETE_LTS_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
