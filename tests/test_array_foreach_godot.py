from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code


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


class TestArrayForeachGodotSmoke(unittest.TestCase):
    def test_array_foreach_matches_lts_range_binding_and_mutation_semantics(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        binding_probe = transpile_gml_code(
            textwrap.dedent(
                """\
                var _output = [1, 2, 3];
                array_foreach(_output, method({_output}, function(_value, _index) {
                    _output[_index] = _value * 10;
                }));
                var _method_scope = {value: 7};
                var _bound = method(_method_scope, function() { return value; });
                var _same_name = 3;
                var _same_name_scope = {_same_name: 7};
                var _bound_same_name = method(_same_name_scope, function() {
                    return _same_name;
                });
                var _source_scope = {value: 11};
                var _target_scope = {value: 13};
                var _rebound = method(_target_scope, method(_source_scope, function() {
                    return value;
                }));
                return [_output, _bound(), _bound_same_name(), _rebound()];
                """
            ),
            indent="\t",
            return_depth=1,
            other_expression="self",
        )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var calls = []
            var active_array = []
            var future_seen = []

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _collect(value, index):
            \tcalls.append([value, index])
            \treturn "ignored"

            func _assign_parameter(element, index):
            \telement = 99
            \tif index < 0:
            \t\tcalls.append(element)

            func _mutate_reference(element, index):
            \tif index == 0:
            \t\telement["x"] = 10
            \telse:
            \t\telement[0] = 20

            func _mutate_current(value, index):
            \tactive_array[index] = value * 10

            func _mutate_future(value, index):
            \tfuture_seen.append(value)
            \tif index == 0:
            \t\tactive_array[1] = 99

            func _script_callback(value, index):
            \tcalls.append(["unscoped", value, index])

            func _script_callback_scoped(callback_self, callback_other, value, index):
            \tcallback_self["seen"].append([value, index])
            \tcallback_self["other_tag"] = callback_other["tag"]

            func _run_transpiled_binding_probe():
            __BINDING_PROBE__

            func _ready():
            \tvar binding_result = _run_transpiled_binding_probe()
            \tif not _check(binding_result == [[10, 20, 30], 7, 7, 13], "transpiled method callback lost its bound struct scope"):
            \t\treturn

            \tvar callback = GMRuntime.gml_method(self, Callable(self, "_collect"))

            \tcalls = []
            \tvar whole_result = GMRuntime.gml_array_foreach([10, 20, 30], callback)
            \tif not _check(calls == [[10, 0], [20, 1], [30, 2]], "whole range or callback arguments mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(whole_result), "callback return must be ignored and foreach must return undefined"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 2)
            \tif not _check(calls == [[2, 2], [3, 3], [4, 4]], "offset-only range mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 1, 3)
            \tif not _check(calls == [[1, 1], [2, 2], [3, 3]], "forward range mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 3, -3)
            \tif not _check(calls == [[3, 3], [2, 2], [1, 1]], "reverse range mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, -2, 2)
            \tif not _check(calls == [[3, 3], [4, 4]], "negative offset mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 3, 99)
            \tif not _check(calls == [[3, 3], [4, 4]], "forward length clamp mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 1, -99)
            \tif not _check(calls == [[1, 1], [0, 0]], "reverse length clamp mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 2, INF)
            \tif not _check(calls == [[2, 2], [3, 3], [4, 4]], "positive infinity length mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 2, -INF)
            \tif not _check(calls == [[2, 2], [1, 1], [0, 0]], "negative infinity length mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2, 3, 4], callback, 1.8, 2.8)
            \tif not _check(calls == [[1, 1], [2, 2]], "fractional range coercion mismatch"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2], callback, 1, 0)
            \tif not _check(calls.is_empty(), "zero length should not call callback"):
            \t\treturn

            \tcalls = []
            \tGMRuntime.gml_array_foreach([0, 1, 2], callback, 99, 2)
            \tif not _check(calls.is_empty(), "high out-of-bounds offset should not be clamped"):
            \t\treturn
            \tGMRuntime.gml_array_foreach([0, 1, 2], callback, -99, 2)
            \tif not _check(calls.is_empty(), "low out-of-bounds offset should not be clamped"):
            \t\treturn

            \tvar empty_result = GMRuntime.gml_array_foreach([], callback)
            \tif not _check(GMRuntime.is_undefined(empty_result), "empty range must return undefined"):
            \t\treturn

            \tvar primitive = [1, 2]
            \tGMRuntime.gml_array_foreach(primitive, GMRuntime.gml_method(self, Callable(self, "_assign_parameter")))
            \tif not _check(primitive == [1, 2], "assigning the callback element must not replace primitive array entries"):
            \t\treturn

            \tvar references = [{"x": 1}, [2]]
            \tGMRuntime.gml_array_foreach(references, GMRuntime.gml_method(self, Callable(self, "_mutate_reference")))
            \tif not _check(references == [{"x": 10}, [20]], "referenced struct and array mutations were not preserved"):
            \t\treturn

            \tactive_array = [1, 2, 3]
            \tGMRuntime.gml_array_foreach(active_array, GMRuntime.gml_method(self, Callable(self, "_mutate_current")))
            \tif not _check(active_array == [10, 20, 30], "bound callback could not mutate source by index"):
            \t\treturn

            \tactive_array = [1, 2, 3]
            \tfuture_seen = []
            \tGMRuntime.gml_array_foreach(active_array, GMRuntime.gml_method(self, Callable(self, "_mutate_future")))
            \tif not _check(future_seen == [1, 99, 3], "later callbacks did not observe source mutations"):
            \t\treturn

            \tGMRuntime.gml_script_register(
            \t\t7001,
            \t\tCallable(self, "_script_callback"),
            \t\tfalse,
            \t\tCallable(self, "_script_callback_scoped")
            \t)
            \tvar caller_scope = {"seen": [], "other_tag": ""}
            \tvar other_scope = {"tag": "other"}
            \tGMRuntime.gml_array_foreach([4, 5], 7001, 0, null, caller_scope, other_scope)
            \tif not _check(caller_scope["seen"] == [[4, 0], [5, 1]], "script asset callback arguments mismatch"):
            \t\treturn
            \tif not _check(caller_scope["other_tag"] == "other", "script asset callback lost caller self/other binding"):
            \t\treturn

            \tprint("ARRAY_FOREACH_LTS_OK")
            \tget_tree().quit(0)
            """
        ).replace("__BINDING_PROBE__", binding_probe)

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
                    [
                        godot_binary,
                        "--headless",
                        "--path",
                        str(project_dir),
                        "smoke.tscn",
                    ],
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
                self.fail("Godot array_foreach smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            result.stdout.count(
                "array_for_each :: index is not within the array bounds."
            ),
            2,
            result.stdout,
        )
        self.assertIn("ARRAY_FOREACH_LTS_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
