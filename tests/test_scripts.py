from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.conversion.scripts import (
    SCRIPT_REGISTRY_RELATIVE_PATH,
    ScriptConverter,
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resource_entry(kind: str, name: str) -> dict[str, object]:
    return {
        "id": {
            "name": name,
            "path": f"{kind}/{name}/{name}.yy",
        }
    }


class TestScriptConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = Path(tempfile.mkdtemp())
        self.godot_dir = Path(tempfile.mkdtemp())
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_project(self) -> None:
        _write_json(
            self.gm_dir / "ScriptTest.yyp",
            {
                "resources": [
                    _resource_entry("scripts", "scr_add"),
                    _resource_entry("scripts", "scr_modern"),
                ],
                "RoomOrderNodes": [],
                "resourceType": "GMProject",
            },
        )
        for script_name in ("scr_add", "scr_modern"):
            _write_json(
                self.gm_dir / "scripts" / script_name / f"{script_name}.yy",
                {
                    "%Name": script_name,
                    "name": script_name,
                    "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                    "resourceType": "GMScript",
                },
            )
        _write_text(
            self.gm_dir / "scripts" / "scr_add" / "scr_add.gml",
            "return argument0 + argument1;",
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "function scr_modern(a, b = 4) { return a + b; }",
        )

    def _converter(self) -> ScriptConverter:
        return ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )

    def test_converts_scripts_and_generated_registry(self) -> None:
        self._write_project()

        registry_path = self._converter().convert_all()

        self.assertEqual(registry_path, str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH))
        legacy_script = (self.godot_dir / "scripts" / "Game" / "scr_add.gd").read_text(encoding="utf-8")
        modern_script = (self.godot_dir / "scripts" / "Game" / "scr_modern.gd").read_text(encoding="utf-8")
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")

        self.assertIn("func _gm_script_call():", legacy_script)
        self.assertIn("GMRuntime.gml_argument(0)", legacy_script)
        self.assertIn("GMRuntime.gml_argument(1)", legacy_script)
        self.assertIn("func gm2godot_callable():", modern_script)
        self.assertIn("func _gm_script_call(a = null, b = null):", modern_script)
        self.assertIn("if b == null or GMRuntime.is_undefined(b): b = 4", modern_script)
        self.assertIn('preload("res://scripts/Game/scr_add.gd").new().gm2godot_callable()', registry)
        self.assertIn('"legacy_arguments": true', registry)
        self.assertIn('preload("res://scripts/Game/scr_modern.gd").new().gm2godot_callable()', registry)
        self.assertIn('"legacy_arguments": false', registry)


if __name__ == "__main__":
    unittest.main()
