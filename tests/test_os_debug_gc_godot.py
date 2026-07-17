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


class TestOSDebugGCGodotSmoke(unittest.TestCase):
    def test_os_debug_gc_runtime_helpers_emit_and_return_stable_values(self) -> None:
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
            \tvar os_type = GMRuntime.gml_os_type()
            \tif not _check(os_type == GMRuntime.gml_builtin_global("os_type"), "os_type builtin mismatch"):
            \t\treturn
            \tvar info = GMRuntime.gml_os_get_info()
            \tif not _check(GMRuntime.gml_selector_get(info, "os_type") == os_type, "os_get_info os_type mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_os_get_language().length() <= 2, "language code too long"):
            \t\treturn
            \tGMRuntime.gml_clipboard_set_text("gm2godot clipboard smoke")
            \tif not _check(GMRuntime.gml_clipboard_has_text(), "clipboard_has_text failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_clipboard_get_text() == "gm2godot clipboard smoke", "clipboard_get_text failed"):
            \t\treturn
            \tGMRuntime.gml_clipboard_set_text("")

            \tGMRuntime.gml_show_debug_message_ext("OS_DEBUG_VALUE {0}", [os_type])
            \tGMRuntime.gml_show_debug_message_ext("SHOW_DEBUG_VARIADIC {0}/{1}", ["alpha", 7])
            \tGMRuntime.gml_gc_enable(false)
            \tif not _check(GMRuntime.gml_gc_is_enabled() == false, "gc_enable false failed"):
            \t\treturn
            \tGMRuntime.gml_gc_target_frame_time(50)
            \tif not _check(GMRuntime.gml_gc_get_target_frame_time() == 50, "gc target failed"):
            \t\treturn
            \tGMRuntime.gml_gc_collect()
            \tvar stats = GMRuntime.gml_gc_get_stats()
            \tif not _check(GMRuntime.gml_selector_get(stats, "gc_frame") == 1, "gc frame failed"):
            \t\treturn

            \tvar weak = GMRuntime.gml_weak_ref_create({"value": 1})
            \tif not _check(GMRuntime.gml_weak_ref_alive(weak), "weak ref alive failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_weak_ref_any_alive([weak], 0, 1), "weak ref any alive failed"):
            \t\treturn
            \tvar stack = GMRuntime.gml_debug_get_callstack(1)
            \tif not _check(stack.size() >= 1, "callstack missing sentinel"):
            \t\treturn

            \tprint("OS_DEBUG_GC_SMOKE_OK")
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
                self.fail("Godot OS/debug/GC smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("OS_DEBUG_VALUE", result.stdout)
        self.assertIn("SHOW_DEBUG_VARIADIC alpha/7", result.stdout)
        self.assertIn("OS_DEBUG_GC_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
