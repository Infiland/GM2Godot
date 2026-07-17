from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression
from src.conversion.godot_validation import find_godot_binary


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDebugStringsGodotSmoke(unittest.TestCase):
    def test_generated_debug_calls_format_and_return_with_gml_semantics(self) -> None:
        godot_binary = find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        undefined_call = transpile_gml_expression("show_debug_message(undefined)")
        fractional_call = transpile_gml_expression("show_debug_message(1.2)")
        single_format_call = transpile_gml_expression(
            'show_debug_message("SINGLE={{0}}/{0}")'
        )
        formatted_call = transpile_gml_expression(
            'show_debug_message('
            '"FORMAT={{0}}|{0}|{Not}|{2}|{-1}|{1}|{00}|{01}", '
            '1.2, "{0}")'
        )

        smoke_script = textwrap.dedent(
            f"""\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tif not _check(GMRuntime.gml_string(1.0) == "1", "integral real string mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_string(-0.0) == "0", "negative-zero string mismatch"):
            \t\treturn

            \tvar undefined_result = {undefined_call}
            \tif not _check(GMRuntime.is_undefined(undefined_result), "single debug return was not undefined"):
            \t\treturn

            \tvar fractional_result = {fractional_call}
            \tif not _check(GMRuntime.is_undefined(fractional_result), "fractional debug return was not undefined"):
            \t\treturn

            \tvar single_format_result = {single_format_call}
            \tif not _check(GMRuntime.is_undefined(single_format_result), "single format-like return was not undefined"):
            \t\treturn

            \tvar formatted_result = {formatted_call}
            \tif not _check(GMRuntime.is_undefined(formatted_result), "variadic debug return was not undefined"):
            \t\treturn

            \tvar ext_result = GMRuntime.gml_show_debug_message_ext(
            \t\t"EXT={{{{0}}}}|{{0}}|{{missing}}",
            \t\t[1.2]
            \t)
            \tif not _check(GMRuntime.is_undefined(ext_result), "extended debug return was not undefined"):
            \t\treturn

            \tprint("DEBUG_STRINGS_SMOKE_OK")
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
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="DebugStringsSmoke"\nrun/main_scene="res://smoke.tscn"\n',
            )
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
                        "--scene",
                        "res://smoke.tscn",
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
                self.fail("Godot debug-string smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"(?m)^undefined$")
        self.assertRegex(result.stdout, r"(?m)^1\.20$")
        self.assertIn("SINGLE={{0}}/{0}", result.stdout)
        self.assertIn(
            "FORMAT={0}|1.20|{Not}|{2}|{-1}|{0}|{00}|{01}",
            result.stdout,
        )
        self.assertIn("EXT={0}|1.20|{missing}", result.stdout)
        self.assertIn("DEBUG_STRINGS_SMOKE_OK", result.stdout)
        for error_marker in ("SCRIPT ERROR:", "Parse Error:", "ERROR:"):
            with self.subTest(error_marker=error_marker):
                self.assertNotIn(error_marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
