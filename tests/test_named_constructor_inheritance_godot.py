from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import cast

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.script_functions import modern_script_function_declarations
from src.conversion.scripts import ScriptConverter


def _find_godot_binary() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured and os.path.isfile(configured):
        return configured
    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary
    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    return mac_binary if os.path.isfile(mac_binary) else None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestNamedConstructorInheritanceGodot(unittest.TestCase):
    def test_named_inheritance_registers_runs_and_keeps_original_source_lines(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        source = (
            "// Named constructor inheritance fixture\n"
            "\n"
            "function Parent(value) constructor {\n"
            "    parent_value = value;\n"
            "}\n"
            "\n"
            "function Child(value = 8) : Parent(value) constructor {\n"
            "    child_value = value + 1;\n"
            "}\n"
        )
        declarations = modern_script_function_declarations(source)
        self.assertIsNotNone(declarations)
        assert declarations is not None
        self.assertEqual(tuple(item.name for item in declarations), ("Parent", "Child"))
        self.assertEqual(declarations[1].parent_constructor, "Parent(value)")

        with tempfile.TemporaryDirectory() as gm_tmp, tempfile.TemporaryDirectory() as godot_tmp:
            gm_dir = Path(gm_tmp)
            godot_dir = Path(godot_tmp)
            _write_text(
                gm_dir / "Family.yyp",
                json.dumps(
                    {
                        "resources": [
                            {
                                "id": {
                                    "name": "scr_family",
                                    "path": "scripts/scr_family/scr_family.yy",
                                }
                            }
                        ],
                        "RoomOrderNodes": [],
                        "resourceType": "GMProject",
                    }
                ),
            )
            _write_text(
                gm_dir / "scripts" / "scr_family" / "scr_family.yy",
                json.dumps(
                    {
                        "name": "scr_family",
                        "resourceType": "GMScript",
                        "parent": {
                            "name": "Scripts",
                            "path": "folders/Scripts.yy",
                        },
                    }
                ),
            )
            _write_text(
                gm_dir / "scripts" / "scr_family" / "scr_family.gml",
                source,
            )
            _write_text(godot_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(godot_dir))
            AssetRegistryConverter(gm_dir, godot_dir).convert_all()
            ScriptConverter(gm_dir, godot_dir).convert_all()

            generated_script = (godot_dir / "scripts" / "scr_family.gd").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                'GMRuntime.gml_constructor_inherit(_gml_constructor_self, '
                'GMRuntime.gml_asset_get_index("Parent"), [value], '
                "_gml_constructor_self, _gml_constructor_other)",
                generated_script,
            )
            source_map = cast(
                dict[str, object],
                json.loads(
                    (godot_dir / "scripts" / "scr_family.gd.gmlmap.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            mapped_entries = cast(list[dict[str, object]], source_map["entries"])
            parent_entry = next(
                entry
                for entry in mapped_entries
                if entry["event"] == "script:Parent"
                and "parent_value" in cast(str, entry["source_text"])
            )
            child_entry = next(
                entry
                for entry in mapped_entries
                if entry["event"] == "script:Child"
                and "child_value" in cast(str, entry["source_text"])
            )
            self.assertEqual(parent_entry["source_line"], 4)
            self.assertEqual(child_entry["source_line"], 8)

            _write_text(
                godot_dir / "smoke.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    func _fail(message):
                    \tpush_error(message)
                    \tGMRuntime.gm2godot_runtime_shutdown()
                    \tget_tree().quit(1)

                    func _ready():
                    \tGMRuntime.gml_script_registry_entries()
                    \tvar parent_id = GMRuntime.gml_asset_get_index("Parent")
                    \tvar parent_constructor = GMRuntime.gml_script_get_callable(parent_id)
                    \tvar child_id = GMRuntime.gml_asset_get_index("Child")
                    \tvar instance = GMRuntime.gml_new(child_id, [])
                    \tif GMRuntime.gml_variable_instance_get(instance, "parent_value") != 8:
                    \t\t_fail("named child constructor did not run parent")
                    \t\treturn
                    \tif GMRuntime.gml_variable_instance_get(instance, "child_value") != 9:
                    \t\t_fail("named child constructor body did not run")
                    \t\treturn
                    \tif not GMRuntime.gml_is_instanceof(instance, parent_constructor):
                    \t\t_fail("named child constructor lost parent static chain")
                    \t\treturn
                    \tprint("NAMED_CONSTRUCTOR_INHERITANCE_OK")
                    \tGMRuntime.gm2godot_runtime_shutdown()
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(
                godot_dir / "smoke.tscn",
                textwrap.dedent(
                    """\
                    [gd_scene load_steps=2 format=3]

                    [ext_resource type="Script" path="res://smoke.gd" id="1"]

                    [node name="Smoke" type="Node"]
                    script = ExtResource("1")
                    """
                ),
            )
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(godot_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Godot Engine v4.7.1.stable", result.stdout)
        self.assertIn("NAMED_CONSTRUCTOR_INHERITANCE_OK", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)


if __name__ == "__main__":
    unittest.main()
