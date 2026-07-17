from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.runtime_managers import (
    register_runtime_manager_autoloads,
    write_runtime_managers,
)


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestRuntimeManagersGodotSmoke(unittest.TestCase):
    def test_runtime_shutdown_releases_methods_nested_in_cyclic_containers(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        helper_script = textwrap.dedent(
            """\
            extends RefCounted

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _call():
            \treturn 1

            func gml_callable():
            \treturn GMRuntime.gml_method(self, Callable(self, "_call"))
            """
        )
        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const Helper = preload("res://helper.gd")

            func _ready():
            \tvar helper_method = Helper.new().gml_callable()
            \tGMRuntime.gml_script_register("shutdown_helper", helper_method, false, helper_method)
            \tvar nested_array = []
            \tvar nested_struct = GMRuntime.gml_struct({
            \t\t"method": helper_method,
            \t\t"shared": nested_array,
            \t})
            \tnested_array.append(nested_struct)
            \tnested_array.append(nested_array)
            \tnested_struct["cycle"] = nested_struct
            \tGMRuntime.gml_global_scope()["shutdown_cycle"] = {
            \t\t"nested": [nested_array],
            \t}
            \tvar static_scope = GMRuntime.gml_static_scope("shutdown_cycle")
            \tstatic_scope["nested"] = nested_struct
            \tprint("RUNTIME_SHUTDOWN_CYCLE_READY")
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
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            write_runtime_managers(str(project_dir))
            self.assertTrue(register_runtime_manager_autoloads(str(project_dir)))
            _write_text(project_dir / "helper.gd", helper_script)
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [
                        godot_binary,
                        "--headless",
                        "--verbose",
                        "--path",
                        str(project_dir),
                        "smoke.tscn",
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
                self.fail("Godot runtime-shutdown smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("RUNTIME_SHUTDOWN_CYCLE_READY", result.stdout)
        self.assertNotIn("ObjectDB instances were leaked", result.stdout)
        self.assertNotIn("resources still in use", result.stdout)
        self.assertNotIn("Leaked instance:", result.stdout)
        self.assertNotIn("recursive mutex", result.stdout.lower())
        self.assertNotIn("mutex lock", result.stdout.lower())

    def test_generated_runtime_managers_autoload_in_order(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tvar runtime_root = get_node("/root/GMRuntime")
            \tif not _check(runtime_root != null, "GMRuntime autoload missing"):
            \t\treturn
            \tvar expected = [
            \t\t"GMRuntime",
            \t\t"GMAssets",
            \t\t"GMRooms",
            \t\t"GMInstances",
            \t\t"GMEvents",
            \t\t"GMDraw",
            \t\t"GMInput",
            \t\t"GMAudio",
            \t\t"GMAsync",
            \t\t"GMPlatform"
            \t]
            \tif not _check(runtime_root.manager_order() == expected, "manager order mismatch"):
            \t\treturn
            \tvar registry = runtime_root.manager_registry_snapshot()
            \tif not _check(registry.has("GMAssets"), "GMAssets registry missing"):
            \t\treturn
            \tif not _check(registry["GMAssets"]["dependencies"].has("GMRuntime"), "GMAssets dependency missing"):
            \t\treturn
            \tvar assets = get_node("/root/GMAssets")
            \tif not _check(assets.state_bucket("asset_registry") is Dictionary, "GMAssets state bucket missing"):
            \t\treturn
            \tif not _check(get_node("/root/GMPlatform").manager_initialization_index() == 9, "GMPlatform order mismatch"):
            \t\treturn
            \tprint("RUNTIME_MANAGERS_SMOKE_OK")
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
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot runtime-manager smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("RUNTIME_MANAGERS_SMOKE_OK", result.stdout)

    def test_dynamic_asset_registry_updates_and_releases_runtime_assets(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tvar asset_id = GMRuntime.gml_asset_register_dynamic("spr_runtime", "sprite", "res://runtime/spr_runtime.png", ["runtime", "generated"])
            \tif not _check(asset_id >= GMRuntime.GML_DYNAMIC_ASSET_ID_START, "dynamic asset id range mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_get_index("spr_runtime") == asset_id, "dynamic asset name lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_get_type(asset_id) == "sprite", "dynamic asset type lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_get_type_name(asset_id) == "Sprite", "dynamic asset type name lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_has_any_tag(asset_id, ["missing", "generated"]), "dynamic asset tags missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_get_ids("sprite").has("dynamic:" + str(asset_id)), "dynamic asset type ids missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_release(asset_id), "dynamic asset release failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_asset_get_index("spr_runtime") == -1, "released dynamic asset still resolved"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_asset_release(asset_id), "released dynamic asset released twice"):
            \t\treturn
            \tprint("DYNAMIC_ASSET_REGISTRY_SMOKE_OK")
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
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            try:
                result = subprocess.run(
                    [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output or "")
                self.fail("Godot dynamic-asset smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("DYNAMIC_ASSET_REGISTRY_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
