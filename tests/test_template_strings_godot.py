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


class TestTemplateStringsGodotSmoke(unittest.TestCase):
    def test_generated_template_strings_execute_with_gml_semantics(self) -> None:
        godot_binary = find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        scalar_expression = transpile_gml_expression(
            '$"number={number_value}; bool={flag}; undefined={undefined}"',
            local_names={"number_value", "flag"},
        )
        accessor_expression = transpile_gml_expression(
            '$"first={values[| 0]}; count={ds_list_size(values)}"',
            local_names={"values"},
        )
        nested_expression = transpile_gml_expression(
            r'$"outer={$"inner={number_value}"}; \{literal\}"',
            local_names={"number_value"},
        )
        unicode_expression = transpile_gml_expression(
            r'$"unicode=\u61; emoji=\u1F600; hex=\x41; octal=\101"'
        )
        ordinary_escape_expression = transpile_gml_expression(
            r'"unknown=\q; unicode=\u61a; octal=\101"'
        )
        ordinary_single_quote_expression = transpile_gml_expression(
            r"'unknown=\q; quote=\''"
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
            \tvar number_value = 1.2
            \tvar flag = true
            \tvar scalar_result = {scalar_expression}
            \tif not _check(
            \t\tscalar_result == "number=1.20; bool=true; undefined=undefined",
            \t\t"scalar template mismatch: " + scalar_result
            \t):
            \t\treturn

            \tvar values = GMRuntime.gml_ds_list_create()
            \tGMRuntime.gml_ds_list_add(values, ["alpha", "beta"])
            \tvar accessor_result = {accessor_expression}
            \tif not _check(
            \t\taccessor_result == "first=alpha; count=2",
            \t\t"accessor template mismatch: " + accessor_result
            \t):
            \t\treturn
            \tGMRuntime.gml_ds_list_destroy(values)

            \tvar nested_result = {nested_expression}
            \tif not _check(
            \t\tnested_result == "outer=inner=1.20; {{literal}}",
            \t\t"nested template mismatch: " + nested_result
            \t):
            \t\treturn

            \tvar unicode_result = {unicode_expression}
            \tif not _check(
            \t\tunicode_result == "unicode=a; emoji=😀; hex=A; octal=A",
            \t\t"unicode template mismatch: " + unicode_result
            \t):
            \t\treturn

            \tvar ordinary_escape_result = {ordinary_escape_expression}
            \tif not _check(
            \t\tordinary_escape_result == "unknown=q; unicode=ؚ; octal=A",
            \t\t"ordinary string escape mismatch: " + ordinary_escape_result
            \t):
            \t\treturn

            \tvar ordinary_single_quote_result = {ordinary_single_quote_expression}
            \tif not _check(
            \t\tordinary_single_quote_result == "unknown=q; quote='",
            \t\t"single-quoted string escape mismatch: " + ordinary_single_quote_result
            \t):
            \t\treturn

            \tprint("TEMPLATE_STRINGS_SMOKE_OK")
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
                '[application]\nconfig/name="TemplateStringsSmoke"\nrun/main_scene="res://smoke.tscn"\n',
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
                self.fail("Godot template-string smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("TEMPLATE_STRINGS_SMOKE_OK", result.stdout)
        for error_marker in ("SCRIPT ERROR:", "Parse Error:", "ERROR:"):
            with self.subTest(error_marker=error_marker):
                self.assertNotIn(error_marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
