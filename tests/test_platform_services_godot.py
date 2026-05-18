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


class TestPlatformServicesGodotSmoke(unittest.TestCase):
    def test_platform_service_hooks_and_safe_fallbacks(self) -> None:
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
            \tcall_deferred("_run")

            func _run():
            \tif not _check(GMRuntime.gml_steam_is_initialized() == false, "steam fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_xboxlive_user_is_signed_in() == false, "xbox sign-in fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_xboxlive_user_is_signing_in() == false, "xbox signing-in fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_xboxlive_gamertag_for_user() == "", "xbox gamertag fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_browser_width() >= 0, "browser width fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_browser_height() >= 0, "browser height fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_webgl_enabled() == true, "webgl fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_browser_input_capture(true) == null, "browser capture fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_url_get_domain() == "", "empty domain fallback failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_url_get_domain("https://user@example.com:443/a") == "example.com", "domain parse failed"):
            \t\treturn

            \tGMRuntime.gml_platform_service_register("steam", {
            \t\t"steam_is_initialized": func(): return true,
            \t})
            \tif not _check(GMRuntime.gml_steam_is_initialized(), "steam hook failed"):
            \t\treturn

            \tGMRuntime.gml_platform_service_register("web", {
            \t\t"browser_input_capture": func(enable): return "capture:" + str(enable),
            \t\t"browser_width": func(): return 640,
            \t\t"browser_height": func(): return 360,
            \t\t"url_get_domain": func(): return "hook.example",
            \t\t"webgl_enabled": func(): return false,
            \t})
            \tif not _check(GMRuntime.gml_browser_input_capture(false) == "capture:false", "web capture hook failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_browser_width() == 640, "browser width hook failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_browser_height() == 360, "browser height hook failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_url_get_domain() == "hook.example", "domain hook failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_webgl_enabled() == false, "webgl hook failed"):
            \t\treturn

            \tGMRuntime.gml_platform_service_register("xboxlive", {
            \t\t"xboxlive_user_is_signed_in": func(): return true,
            \t\t"xboxlive_gamertag_for_user": func(): return "PlayerOne",
            \t})
            \tif not _check(GMRuntime.gml_xboxlive_user_is_signed_in(), "xbox sign-in hook failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_xboxlive_gamertag_for_user() == "PlayerOne", "xbox gamertag hook failed"):
            \t\treturn

            \tGMRuntime.gml_platform_service_register("steam", null)
            \tGMRuntime.gml_platform_service_register("web", null)
            \tGMRuntime.gml_platform_service_register("xboxlive", null)
            \tprint("PLATFORM_SERVICES_SMOKE_OK")
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
                self.fail("Godot platform-services smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PLATFORM_SERVICES_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
