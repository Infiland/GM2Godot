from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.godot_validation import find_godot_binary
from src.conversion.scripts import ScriptConverter


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, object]) -> None:
    _write_text(path, json.dumps(data))


class TestScriptTopLevelEnumGodotSmoke(unittest.TestCase):
    def test_modern_script_after_enum_executes_on_exact_godot_4_7_1(self) -> None:
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

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gm_dir = root / "game_maker"
            godot_dir = root / "godot"
            script_name = "snap_enum_script"
            _write_json(
                gm_dir / "EnumScript.yyp",
                {
                    "resources": [
                        {
                            "id": {
                                "name": script_name,
                                "path": f"scripts/{script_name}/{script_name}.yy",
                            }
                        }
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
            )
            _write_json(
                gm_dir / "scripts" / script_name / f"{script_name}.yy",
                {
                    "%Name": script_name,
                    "name": script_name,
                    "parent": {
                        "name": "Game",
                        "path": "folders/Scripts/Game.yy",
                    },
                    "resourceType": "GMScript",
                },
            )
            _write_text(
                gm_dir / "scripts" / script_name / f"{script_name}.gml",
                textwrap.dedent(
                    """\
                    enum TokenKind
                    {
                        UNKNOWN,
                        NUMBER = 4,
                    }

                    function snap_enum_script(value)
                    {
                        return value == TokenKind.NUMBER;
                    }
                    """
                ),
            )

            diagnostics = DiagnosticCollector()
            ScriptConverter(
                gm_dir,
                godot_dir,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                diagnostics=diagnostics,
            ).convert_all()
            self.assertEqual(diagnostics.diagnostics(), ())

            _write_text(
                godot_dir / "project.godot",
                '[application]\nconfig/name="TopLevelEnumSmoke"\n'
                'run/main_scene="res://smoke.tscn"\n'
                '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
            )
            _write_text(
                godot_dir / "smoke.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    const ConvertedScript = preload("res://scripts/game/snap_enum_script.gd")

                    func _ready():
                    \tvar converted = ConvertedScript.new()
                    \tif converted._gm_script_call(4) != true:
                    \t\tpush_error("enum member was not lowered to its project-global value")
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tif converted._gm_script_call(3) != false:
                    \t\tpush_error("enum comparison returned an incorrect result")
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tprint("TOP_LEVEL_ENUM_SCRIPT_OK")
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(
                godot_dir / "smoke.tscn",
                textwrap.dedent(
                    """\
                    [gd_scene load_steps=2 format=3]

                    [ext_resource type="Script" path="res://smoke.gd" id="1_smoke"]

                    [node name="Smoke" type="Node"]
                    script = ExtResource("1_smoke")
                    """
                ),
            )

            try:
                result = subprocess.run(
                    [
                        godot_binary,
                        "--headless",
                        "--path",
                        str(godot_dir),
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
                self.fail("Godot top-level-enum smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("TOP_LEVEL_ENUM_SCRIPT_OK", result.stdout)
        self.assertNotIn("Parse Error:", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)


if __name__ == "__main__":
    unittest.main()
