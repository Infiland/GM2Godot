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


class TestQuotedStructKeysGodotSmoke(unittest.TestCase):
    def test_quoted_keys_support_runtime_lookup_and_json_round_trip(self) -> None:
        godot_binary = find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        struct_expression = transpile_gml_expression(
            r'{"display name": 7, "punctuation.!?": 11, '
            r'"Unicode 鍵": {"quote\" and slash\\": "preserved"},}'
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
            \tvar original = {struct_expression}
            \tif not _check(GMRuntime.gml_struct_get(original, "display name") == 7, "space key lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_struct_get(original, "punctuation.!?") == 11, "punctuation key lookup failed"):
            \t\treturn

            \tvar unicode_value = GMRuntime.gml_struct_get(original, "Unicode 鍵")
            \tif not _check(GMRuntime.gml_struct_get(unicode_value, "quote\\\" and slash\\\\") == "preserved", "escaped key lookup failed"):
            \t\treturn

            \tvar restored = GMRuntime.gml_json_decode(GMRuntime.gml_json_encode(original))
            \tvar restored_unicode_value = GMRuntime.gml_struct_get(restored, "Unicode 鍵")
            \tif not _check(GMRuntime.gml_struct_get(restored, "display name") == 7, "space key round trip failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_struct_get(restored_unicode_value, "quote\\\" and slash\\\\") == "preserved", "escaped key round trip failed"):
            \t\treturn

            \tprint("QUOTED_STRUCT_KEYS_SMOKE_OK")
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
                '[application]\nconfig/name="QuotedStructKeysSmoke"\n'
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
                self.fail("Godot quoted-struct-key smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("QUOTED_STRUCT_KEYS_SMOKE_OK", result.stdout)
        for error_marker in ("SCRIPT ERROR:", "Parse Error:", "ERROR:"):
            with self.subTest(error_marker=error_marker):
                self.assertNotIn(error_marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
