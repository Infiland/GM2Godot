from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import cast

from src.conversion.diagnostics import DiagnosticCollector
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


def _extension_yy(name: str) -> dict[str, object]:
    return {
        "%Name": name,
        "name": name,
        "files": [
            {
                "filename": f"{name}.dll",
                "functions": [
                    {
                        "name": "ads_show_rewarded",
                        "externalName": "Ads_ShowRewarded",
                        "argCount": 1,
                    }
                ],
            }
        ],
        "resourceType": "GMExtension",
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

    def _converter(self, macro_configuration: str | None = None) -> ScriptConverter:
        return ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            macro_configuration=macro_configuration,
        )

    def test_converts_scripts_and_generated_registry(self) -> None:
        self._write_project()

        registry_path = self._converter().convert_all()

        self.assertEqual(registry_path, str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH))
        legacy_script = (self.godot_dir / "scripts" / "game" / "scr_add.gd").read_text(encoding="utf-8")
        modern_script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(encoding="utf-8")
        legacy_source_map = json.loads(
            (self.godot_dir / "scripts" / "game" / "scr_add.gd.gmlmap.json").read_text(encoding="utf-8")
        )
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")

        self.assertIn("func _gm_script_call():", legacy_script)
        self.assertIn("func _gm_script_call_scoped(_gml_script_self = null, _gml_script_other = null):", legacy_script)
        self.assertIn("# GM2Godot source:", legacy_script)
        self.assertIn("GMRuntime.gml_argument(0)", legacy_script)
        self.assertIn("GMRuntime.gml_argument(1)", legacy_script)
        self.assertEqual(legacy_source_map["event"], "script:scr_add")
        self.assertTrue(legacy_source_map["entries"])
        self.assertEqual(
            legacy_source_map["entries"][0]["source_path"],
            str(self.gm_dir / "scripts" / "scr_add" / "scr_add.gml"),
        )
        self.assertEqual(legacy_source_map["entries"][0]["source_line"], 1)
        self.assertIn("func gm2godot_callable():", modern_script)
        self.assertIn("func gm2godot_scoped_callable():", modern_script)
        self.assertIn("func _gm_script_call(a = null, b = null):", modern_script)
        self.assertIn(
            "func _gm_script_call_scoped(_gml_script_self = null, _gml_script_other = null, a = null, b = null):",
            modern_script,
        )
        self.assertIn("if b == null or GMRuntime.is_undefined(b): b = 4", modern_script)
        self.assertIn('preload("res://scripts/game/scr_add.gd").new().gm2godot_callable()', registry)
        self.assertIn('preload("res://scripts/game/scr_add.gd").new().gm2godot_scoped_callable()', registry)
        self.assertIn('"legacy_arguments": true', registry)
        self.assertIn('preload("res://scripts/game/scr_modern.gd").new().gm2godot_callable()', registry)
        self.assertIn('preload("res://scripts/game/scr_modern.gd").new().gm2godot_scoped_callable()', registry)
        self.assertIn('"legacy_arguments": false', registry)

    def test_script_body_uses_caller_instance_scope(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("scripts", "scr_move"))
        _write_json(project_path, project)
        _write_json(
            self.gm_dir / "scripts" / "scr_move" / "scr_move.yy",
            {
                "%Name": "scr_move",
                "name": "scr_move",
                "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                "resourceType": "GMScript",
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_move" / "scr_move.gml",
            "function scr_move(amount) { x += amount; return x; }",
        )

        self._converter().convert_all()

        script = (self.godot_dir / "scripts" / "game" / "scr_move.gd").read_text(encoding="utf-8")
        self.assertIn('GMRuntime.gml_variable_instance_get(_gml_script_self, "x")', script)
        self.assertIn('GMRuntime.gml_variable_instance_set(_gml_script_self, "x"', script)
        self.assertNotIn("position.x", script)

    def test_converts_scripts_with_mapped_extension_calls(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("extensions", "AdSDK"))
        _write_json(project_path, project)
        _write_json(self.gm_dir / "extensions" / "AdSDK" / "AdSDK.yy", _extension_yy("AdSDK"))
        _write_json(
            self.gm_dir / "gm2godot_extension_functions.json",
            {
                "functions": {
                    "ads_show_rewarded": {
                        "target": "AdBridge.show_rewarded",
                        "min_args": 1,
                        "max_args": 1,
                    }
                }
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "scr_add" / "scr_add.gml",
            'ads_show_rewarded("zone_1"); return 1;',
        )

        self._converter().convert_all()

        legacy_script = (self.godot_dir / "scripts" / "game" / "scr_add.gd").read_text(encoding="utf-8")
        self.assertIn('AdBridge.show_rewarded("zone_1")', legacy_script)

    def test_applies_macro_configuration_to_script_sources(self) -> None:
        self._write_project()
        _write_text(
            self.gm_dir / "scripts" / "scr_modern" / "scr_modern.gml",
            "#if Android\n"
            "function scr_modern() { return 11; }\n"
            "#else\n"
            "function scr_modern() { return 22; }\n"
            "#endif\n",
        )

        self._converter(macro_configuration="Android").convert_all()

        modern_script = (self.godot_dir / "scripts" / "game" / "scr_modern.gd").read_text(encoding="utf-8")
        self.assertIn("return 11", modern_script)
        self.assertNotIn("return 22", modern_script)

    def test_converts_multi_function_script_assets_and_declared_registry_names(self) -> None:
        self._write_project()
        project_path = self.gm_dir / "ScriptTest.yyp"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        resources = cast(list[object], project["resources"])
        resources.append(_resource_entry("scripts", "ending"))
        _write_json(project_path, project)
        _write_json(
            self.gm_dir / "scripts" / "ending" / "ending.yy",
            {
                "%Name": "ending",
                "name": "ending",
                "parent": {"name": "Game", "path": "folders/Scripts/Game.yy"},
                "resourceType": "GMScript",
            },
        )
        _write_text(
            self.gm_dir / "scripts" / "ending" / "ending.gml",
            "function loadending() {\n"
            "    for (var i = 1; i <= 7; i++) { global.endingnum[i] = i; }\n"
            "}\n"
            "function saveending() {\n"
            "    for (var i = 1; i <= 7; i++) { loadending(); }\n"
            "}\n",
        )
        diagnostics = DiagnosticCollector()

        registry_path = ScriptConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
        ).convert_all()

        self.assertEqual(registry_path, str(self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH))
        self.assertEqual(diagnostics.diagnostics(), ())
        ending_script = (self.godot_dir / "scripts" / "game" / "ending.gd").read_text(encoding="utf-8")
        self.assertIn("func _gm_script_call_loadending():", ending_script)
        self.assertIn(
            "func _gm_script_call_scoped_loadending(_gml_script_self = null, _gml_script_other = null):",
            ending_script,
        )
        self.assertIn("func _gm_script_call_saveending():", ending_script)
        self.assertIn(
            "GMRuntime.gml_script_call(GMRuntime.gml_asset_get_index(\"loadending\"), [], "
            "_gml_script_self, _gml_script_other)",
            ending_script,
        )
        registry = (self.godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertIn('"name": "scr_add"', registry)
        self.assertIn('"name": "scr_modern"', registry)
        self.assertIn('"name": "loadending"', registry)
        self.assertIn('"name": "saveending"', registry)
        self.assertNotIn('"name": "ending"', registry)
        self.assertIn(
            'preload("res://scripts/game/ending.gd").new().gm2godot_callable_loadending()',
            registry,
        )
        self.assertIn(
            'preload("res://scripts/game/ending.gd").new().gm2godot_scoped_callable_saveending()',
            registry,
        )


if __name__ == "__main__":
    unittest.main()
