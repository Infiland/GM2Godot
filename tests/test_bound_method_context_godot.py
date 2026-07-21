from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.scripts import SCRIPT_REGISTRY_RELATIVE_PATH, ScriptConverter


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "bound_method_context"


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


def _run_godot(godot_binary: str, project_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )


def _smoke_scene() -> str:
    return textwrap.dedent(
        """\
        [gd_scene load_steps=2 format=3]

        [ext_resource type="Script" path="res://smoke.gd" id="1"]

        [node name="Smoke" type="Node"]
        script = ExtResource("1")
        """
    )


class TestBoundMethodContextGodot(unittest.TestCase):
    def test_fixture_preserves_dynamic_other_script_rebinding_and_constructors(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as gm_tmp, tempfile.TemporaryDirectory() as godot_tmp:
            gm_dir = Path(gm_tmp)
            godot_dir = Path(godot_tmp)
            shutil.copytree(FIXTURE_ROOT, gm_dir, dirs_exist_ok=True)
            _write_text(godot_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(godot_dir))
            AssetRegistryConverter(gm_dir, godot_dir).convert_all()
            ScriptConverter(gm_dir, godot_dir).convert_all()

            probe_scripts = tuple((godot_dir / "scripts").rglob("scr_probe.gd"))
            receiver_scripts = tuple((godot_dir / "scripts").rglob("scr_receiver.gd"))
            constructor_scripts = tuple(
                (godot_dir / "scripts").rglob("scr_constructor.gd")
            )
            self.assertEqual(len(probe_scripts), 1)
            self.assertEqual(len(receiver_scripts), 1)
            self.assertEqual(len(constructor_scripts), 1)
            probe_output = probe_scripts[0].read_text(encoding="utf-8")
            receiver_output = receiver_scripts[0].read_text(encoding="utf-8")
            constructor_output = constructor_scripts[0].read_text(encoding="utf-8")
            registry_output = (
                godot_dir / SCRIPT_REGISTRY_RELATIVE_PATH
            ).read_text(encoding="utf-8")

            self.assertIn(
                "func _gm_script_call_scoped("
                "_gml_script_self = null, _gml_script_other = null",
                receiver_output,
            )
            self.assertIn("GMRuntime.gml_receiver_method(", receiver_output)
            self.assertIn(
                "GMRuntime.gml_script_get_callable("
                'GMRuntime.gml_asset_get_index("scr_receiver"))',
                probe_output,
            )
            self.assertIn(
                "func _gm_script_call("
                "_gml_constructor_self = null, _gml_constructor_other = null",
                constructor_output,
            )
            self.assertIn(
                "GMRuntime.gml_receiver_constructor(",
                constructor_output,
            )
            self.assertIn('"scoped_callable":', registry_output)

            _write_text(
                godot_dir / "smoke.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    var tag = "root"

                    func _fail(message):
                    \tpush_error(str(message))
                    \tGMRuntime.gm2godot_runtime_shutdown()
                    \tget_tree().quit(1)

                    func _ready():
                    \tcall_deferred("_run")

                    func _run():
                    \tvar probe_id = GMRuntime.gml_asset_get_index("scr_probe")
                    \tvar receiver_id = GMRuntime.gml_asset_get_index("scr_receiver")
                    \tvar receiver_reference = GMRuntime.gml_script_get_callable(
                    \t\treceiver_id
                    \t)
                    \tif receiver_reference.receiver_argument_count != 2:
                    \t\t_fail("script receiver metadata was not explicit")
                    \t\treturn
                    \tif receiver_reference.has_bound_self:
                    \t\t_fail("script function reference was not unbound")
                    \t\treturn
                    \tvar runtime_rebound = GMRuntime.gml_method(
                    \t\t{"tag": "runtime-target"},
                    \t\treceiver_id
                    \t)
                    \tvar runtime_rebound_result = GMRuntime.gml_call_value(
                    \t\truntime_rebound,
                    \t\t["runtime"],
                    \t\tself,
                    \t\t{"tag": "ignored"}
                    \t)
                    \tif runtime_rebound_result != [
                    \t\t"runtime-target",
                    \t\t"root",
                    \t\t"runtime",
                    \t]:
                    \t\t_fail("dynamic script handle rebinding lost receiver metadata")
                    \t\treturn
                    \tvar previous_scope = {"tag": "previous"}
                    \tvar result = GMRuntime.gml_script_call(
                    \t\tprobe_id,
                    \t\t[],
                    \t\tself,
                    \t\tprevious_scope
                    \t)
                    \tvar expected = [
                    \t\t["root", "previous", "direct"],
                    \t\t["target", "root", "rebound"],
                    \t\t["root", 7],
                    \t\t["constructor-bound", 9],
                    \t\t[
                    \t\t\t["second", "first"],
                    \t\t\t["second", "caller"],
                    \t\t\t[["second", "caller", 7, 0, 1]],
                    \t\t\t[["foreach", "caller", 8, 0]],
                    \t\t],
                    \t]
                    \tif result != expected:
                    \t\t_fail("bound method context mismatch: " + str(result))
                    \t\treturn
                    \tprint("BOUND_METHOD_CONTEXT_OK")
                    \tGMRuntime.gm2godot_runtime_shutdown()
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(godot_dir / "smoke.tscn", _smoke_scene())
            result = _run_godot(godot_binary, godot_dir)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "Godot Engine v4.7.1.stable.official.a13da4feb",
            result.stdout,
        )
        self.assertIn("BOUND_METHOD_CONTEXT_OK", result.stdout)
        self.assertNotIn("SCRIPT ERROR:", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)
        self.assertNotIn("WARNING:", result.stdout)

    def test_unmarked_custom_callable_fails_closed(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as godot_tmp:
            godot_dir = Path(godot_tmp)
            _write_text(godot_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(godot_dir))
            _write_text(
                godot_dir / "smoke.gd",
                textwrap.dedent(
                    """\
                    extends Node

                    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

                    func _ready():
                    \tvar unsupported = GMRuntime.gml_method(
                    \t\t{},
                    \t\tfunc(receiver): return receiver
                    \t)
                    \tif not GMRuntime.is_undefined(unsupported):
                    \t\tget_tree().quit(1)
                    \t\treturn
                    \tprint("UNMARKED_RECEIVER_FAILED_CLOSED")
                    \tGMRuntime.gm2godot_runtime_shutdown()
                    \tget_tree().quit(0)
                    """
                ),
            )
            _write_text(godot_dir / "smoke.tscn", _smoke_scene())
            result = _run_godot(godot_binary, godot_dir)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("UNMARKED_RECEIVER_FAILED_CLOSED", result.stdout)
        self.assertIn(
            "GML method cannot bind a custom Godot Callable "
            "without explicit receiver metadata",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
