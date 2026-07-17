from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.scripts import ScriptConverter


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path
    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary
    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    return mac_binary if os.path.isfile(mac_binary) else None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _script_resource(name: str) -> dict[str, object]:
    return {"id": {"name": name, "path": f"scripts/{name}/{name}.yy"}}


def _write_script(gm_dir: Path, name: str, source: str) -> None:
    _write_json(
        gm_dir / "scripts" / name / f"{name}.yy",
        {
            "%Name": name,
            "name": name,
            "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
            "resourceType": "GMScript",
        },
    )
    _write_text(gm_dir / "scripts" / name / f"{name}.gml", source)


class TestScriptTopLevelInitializersGodot(unittest.TestCase):
    def test_two_phase_initialization_order_multiplicity_and_inheritance(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as gm_tmp, tempfile.TemporaryDirectory() as godot_tmp:
            gm_dir = Path(gm_tmp)
            godot_dir = Path(godot_tmp)
            _write_json(
                gm_dir / "TopLevelInitializers.yyp",
                {
                    "resources": [
                        _script_resource("scr_order"),
                        _script_resource("scr_standalone"),
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
            )
            _write_script(
                gm_dir,
                "scr_order",
                "function scr_order() constructor {\n"
                "    if (!variable_global_exists(\"trace\")) global.trace = \"\";\n"
                "    if (variable_global_exists(\"First\")) global.trace += \"F\";\n"
                "    if (variable_global_exists(\"Second\")) global.trace += \"S\";\n"
                "    if (!script_exists(scr_standalone)) global.trace += \"X\";\n"
                "}\n"
                "global.First = function() constructor {};\n"
                "new scr_order();\n"
                "global.Second = function() constructor {};\n"
                "new scr_order();\n"
                "new scr_order();\n",
            )
            _write_script(
                gm_dir,
                "scr_standalone",
                "global.BaseCtor = function(value) constructor {\n"
                "    base_value = value;\n"
                "};\n"
                "global.DerivedCtor = function(value): global.BaseCtor(value) constructor {\n"
                "    child_value = value + 1;\n"
                "};\n",
            )

            _write_text(godot_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(godot_dir))
            AssetRegistryConverter(gm_dir, godot_dir).convert_all()
            ScriptConverter(gm_dir, godot_dir).convert_all()

            smoke_script = textwrap.dedent(
                """\
                extends Node

                const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                func _fail(message):
                \tpush_error(message)
                \tGMRuntime.gm2godot_runtime_shutdown()
                \tget_tree().quit(1)

                func _ready():
                \tGMRuntime.gml_script_registry_entries()
                \tvar trace = GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "trace")
                \tif trace != "FFSFS":
                \t\t_fail("top-level order/multiplicity or registry reentrancy failed: " + str(trace))
                \t\treturn
                \tvar derived = GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "DerivedCtor")
                \tvar base = GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "BaseCtor")
                \tvar instance = GMRuntime.gml_new(derived, [8])
                \tif GMRuntime.gml_variable_instance_get(instance, "base_value") != 8:
                \t\t_fail("derived anonymous constructor did not invoke its parent")
                \t\treturn
                \tif GMRuntime.gml_variable_instance_get(instance, "child_value") != 9:
                \t\t_fail("derived anonymous constructor body did not run")
                \t\treturn
                \tif not GMRuntime.gml_is_instanceof(instance, base):
                \t\t_fail("derived anonymous constructor did not retain the parent static chain")
                \t\treturn
                \tif not GMRuntime.gml_script_exists(GMRuntime.gml_asset_get_index("scr_standalone")):
                \t\t_fail("standalone top-level constructor script was not registered")
                \t\treturn
                \tGMRuntime.gml_script_registry_entries()
                \tif GMRuntime.gml_struct_get(GMRuntime.gml_global_scope(), "trace") != "FFSFS":
                \t\t_fail("top-level initializers ran more than once")
                \t\treturn
                \tprint("SCRIPT_TOP_LEVEL_INITIALIZERS_OK")
                \tGMRuntime.gm2godot_runtime_shutdown()
                \tget_tree().quit(0)
                """
            )
            smoke_scene = textwrap.dedent(
                """\
                [gd_scene load_steps=2 format=3]

                [ext_resource type="Script" path="res://smoke.gd" id="1"]

                [node name="Smoke" type="Node"]
                script = ExtResource("1")
                """
            )
            _write_text(godot_dir / "smoke.gd", smoke_script)
            _write_text(godot_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(godot_dir), "smoke.tscn"],
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
                self.fail("Godot top-level initializer smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SCRIPT_TOP_LEVEL_INITIALIZERS_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
