"""gml_pragma("global", code) runs its code before the first room.

The manual (gml_pragma.htm) says the "global" pragma runs the given GML at
global scope before the first room of the game, wherever the pragma appears;
the call itself is compile-time and does nothing when its code runs. Projects
imported from GameMaker 1.x rely on it to set up globals (for example the
generated __global_object_depths and __init_global scripts).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.scripts import ScriptConverter
from tests.godot_test_support import (
    find_smoke_godot_binary,
    run_headless_scene,
    write_fixture_text,
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


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
    write_fixture_text(gm_dir / "scripts" / name / f"{name}.gml", source)


_SMOKE_SCRIPT = textwrap.dedent(
    """\
    extends Node

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    func _ready():
    \tGMRuntime.gml_script_registry_entries()
    \tvar scope = GMRuntime.gml_global_scope()
    \tvar results = {
    \t\t"trace": GMRuntime.gml_struct_get(scope, "trace"),
    \t\t"depth": GMRuntime.gml_array_get(GMRuntime.gml_struct_get(scope, "depths"), 1),
    \t\t"legacy": GMRuntime.gml_struct_get(scope, "legacy"),
    \t\t"call": GMRuntime.gml_script_execute(GMRuntime.gml_asset_get_index("scr_legacy"), [1]),
    \t}
    \tGMRuntime.gml_script_registry_entries()
    \tresults["trace_after_reload"] = GMRuntime.gml_struct_get(scope, "trace")
    \tprint("GLOBAL_PRAGMA " + JSON.stringify(results))
    \tGMRuntime.gm2godot_runtime_shutdown()
    \tget_tree().quit(0)
    """
)


class TestGlobalPragmaGodot(unittest.TestCase):
    def test_global_pragma_code_runs_once_before_the_first_room(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as gm_tmp, tempfile.TemporaryDirectory() as godot_tmp:
            gm_dir = Path(gm_tmp)
            godot_dir = Path(godot_tmp)
            names = ("scr_depths", "scr_order", "scr_legacy", "scr_unity")
            _write_json(
                gm_dir / "GlobalPragma.yyp",
                {
                    "resources": [
                        {"id": {"name": name, "path": f"scripts/{name}/{name}.yy"}} for name in names
                    ],
                    "RoomOrderNodes": [],
                    "resourceType": "GMProject",
                },
            )
            # As GameMaker's 1.x importer writes it: the pragma calls the
            # function that contains it.
            _write_script(
                gm_dir,
                "scr_depths",
                "function scr_depths() {\n"
                '\tgml_pragma( "global", "scr_depths()");\n'
                "\tglobal.depths[1] = 7;\n"
                '\tglobal.trace += "P";\n'
                "}\n",
            )
            _write_script(
                gm_dir,
                "scr_order",
                "function scr_order() constructor {\n"
                '    if (!variable_global_exists("trace")) global.trace = "";\n'
                '    global.trace += "T";\n'
                "}\n"
                "new scr_order();\n",
            )
            _write_script(
                gm_dir,
                "scr_legacy",
                "gml_pragma(\"global\", @'global.legacy = 3; global.trace += \"L\";');\n"
                "return argument0 + 1;\n",
            )
            _write_script(gm_dir, "scr_unity", 'gml_pragma("UnityBuild", "true");\nreturn 0;\n')

            write_fixture_text(godot_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(godot_dir))
            AssetRegistryConverter(gm_dir, godot_dir).convert_all()
            ScriptConverter(gm_dir, godot_dir).convert_all()
            write_fixture_text(godot_dir / "smoke.gd", _SMOKE_SCRIPT)
            write_fixture_text(
                godot_dir / "smoke.tscn",
                '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://smoke.gd" id="1"]\n\n'
                '[node name="Smoke" type="Node"]\nscript = ExtResource("1")\n',
            )
            try:
                result = run_headless_scene(godot_binary, godot_dir, "smoke.tscn", timeout=60)
            except subprocess.TimeoutExpired as exc:
                self.fail(f"Godot global pragma smoke timed out\n{exc.output!r}")

        output = result.stdout
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        lines = [line for line in output.splitlines() if line.startswith("GLOBAL_PRAGMA ")]
        self.assertEqual(len(lines), 1, output)
        results = json.loads(lines[0].removeprefix("GLOBAL_PRAGMA "))
        # Every script's top-level code (T) runs first, then the pragma code in
        # script order (P, L), once.
        self.assertEqual(results["trace"], "TPL")
        self.assertEqual(results["trace_after_reload"], "TPL")
        self.assertEqual(results["depth"], 7)
        self.assertEqual(results["legacy"], 3)
        # The pragma in the script body does nothing when the script runs.
        self.assertEqual(results["call"], 2)


if __name__ == "__main__":
    unittest.main()
