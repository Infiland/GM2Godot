from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_code
from src.conversion.godot_validation import find_godot_binary


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestAssignmentIndexPostincrementGodotSmoke(unittest.TestCase):
    def test_array_index_postincrement_executes_on_exact_godot_4_7_1(self) -> None:
        godot_binary = find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        converted = transpile_gml_code(
            textwrap.dedent(
                """\
                var index = 0;
                var values = [];
                values[@ index++] = "first";
                values[@ index++] = "second";
                return [index, values];
                """
            ),
            indent="\t",
            return_depth=1,
        )
        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _run_converted():
            __CONVERTED__

            func _ready():
            \tvar result = _run_converted()
            \tif result != [2, ["first", "second"]]:
            \t\tpush_error("postincrement array index semantics mismatch: " + str(result))
            \t\tget_tree().quit(1)
            \t\treturn
            \tprint("ASSIGNMENT_INDEX_POSTINCREMENT_OK")
            \tget_tree().quit(0)
            """
        ).replace("__CONVERTED__", converted)
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="1_smoke"]

            [node name="Smoke" type="Node"]
            script = ExtResource("1_smoke")
            """
        )

        with tempfile.TemporaryDirectory() as godot_tmp:
            project_dir = Path(godot_tmp)
            _write_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="AssignmentIndexPostincrementSmoke"\n'
                'run/main_scene="res://smoke.tscn"\n'
                '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
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
                self.fail("Godot assignment-index postincrement smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ASSIGNMENT_INDEX_POSTINCREMENT_OK", result.stdout)
        self.assertNotIn("Parse Error:", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)


if __name__ == "__main__":
    unittest.main()
