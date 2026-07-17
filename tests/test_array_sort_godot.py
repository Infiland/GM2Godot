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


class TestArraySortGodotSmoke(unittest.TestCase):
    def test_array_sort_matches_lts_boolean_method_and_return_semantics(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var comparator_calls = []

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _compare_rank(current, next):
            \tcomparator_calls.append([current["label"], next["label"]])
            \treturn current["rank"] - next["rank"]

            func _ready():
            \tvar ascending = [5, 1, 3, 2, 4]
            \tvar ascending_alias = ascending
            \tvar ascending_result = GMRuntime.gml_array_sort(ascending, true, self, self)
            \tif not _check(ascending == [1, 2, 3, 4, 5], "ascending sort mismatch"):
            \t\treturn
            \tif not _check(ascending_alias == [1, 2, 3, 4, 5], "ascending sort did not mutate alias"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(ascending_result), "ascending N/A must be undefined"):
            \t\treturn

            \tvar descending = [5, 1, 3, 2, 4]
            \tvar descending_alias = descending
            \tvar descending_result = GMRuntime.gml_array_sort(descending, false, self, self)
            \tif not _check(descending == [5, 4, 3, 2, 1], "descending sort mismatch"):
            \t\treturn
            \tif not _check(descending_alias == [5, 4, 3, 2, 1], "descending sort did not mutate alias"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(descending_result), "descending N/A must be undefined"):
            \t\treturn

            \tvar records = [
            \t\t{"label": "five", "rank": 5},
            \t\t{"label": "one", "rank": 1},
            \t\t{"label": "three", "rank": 3},
            \t\t{"label": "two", "rank": 2},
            \t\t{"label": "four", "rank": 4},
            \t]
            \tvar records_alias = records
            \tvar comparator = GMRuntime.gml_method(self, Callable(self, "_compare_rank"))
            \tvar callback_result = GMRuntime.gml_array_sort(records, comparator, self, self)
            \tvar ranks = records.map(func(record): return record["rank"])
            \tif not _check(ranks == [1, 2, 3, 4, 5], "method comparator sort mismatch"):
            \t\treturn
            \tif not _check(records_alias.map(func(record): return record["rank"]) == ranks, "method sort did not mutate alias"):
            \t\treturn
            \tif not _check(not comparator_calls.is_empty(), "method comparator was not called"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(callback_result), "method N/A must be undefined"):
            \t\treturn

            \tprint("ARRAY_SORT_LTS_OK")
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
                self.fail("Godot array_sort smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ARRAY_SORT_LTS_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
