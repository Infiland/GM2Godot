from __future__ import annotations

import json
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


class TestVerbatimStringsGodotSmoke(unittest.TestCase):
    def test_generated_verbatim_strings_execute_on_exact_godot(self) -> None:
        godot_binary = find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        double_value = "first\nsecond\\n // literal ; { }"
        single_value = 'double " quote\nand \\t stays literal'
        double_expression = transpile_gml_expression(
            '@"first\nsecond\\n // literal ; { }"'
        )
        single_expression = transpile_gml_expression(
            "@'double \" quote\nand \\t stays literal'"
        )
        empty_expression = transpile_gml_expression("@''")
        nested_expression = transpile_gml_expression(
            '$"wrapped={@\'literal { } // text\'}"'
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
            \tvar double_result = {double_expression}
            \tif not _check(
            \t\tdouble_result == {json.dumps(double_value)},
            \t\t"double-delimited verbatim mismatch"
            \t):
            \t\treturn

            \tvar single_result = {single_expression}
            \tif not _check(
            \t\tsingle_result == {json.dumps(single_value)},
            \t\t"single-delimited verbatim mismatch"
            \t):
            \t\treturn

            \tif not _check({empty_expression} == "", "empty verbatim mismatch"):
            \t\treturn

            \tvar nested_result = {nested_expression}
            \tif not _check(
            \t\tnested_result == "wrapped=literal {{ }} // text",
            \t\t"nested template/verbatim mismatch"
            \t):
            \t\treturn

            \tprint("VERBATIM_STRINGS_SMOKE_OK")
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
                '[application]\nconfig/name="VerbatimStringsSmoke"\n'
                'run/main_scene="res://smoke.tscn"\n',
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
                self.fail("Godot verbatim-string smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("VERBATIM_STRINGS_SMOKE_OK", result.stdout)
        for error_marker in ("SCRIPT ERROR:", "Parse Error:", "ERROR:"):
            with self.subTest(error_marker=error_marker):
                self.assertNotIn(error_marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
