from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime


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


if __name__ == "__main__":
    unittest.main()
