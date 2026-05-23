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


class TestAsyncQueueGodotSmoke(unittest.TestCase):
    def test_async_queue_flushes_fifo_and_scopes_async_load(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        listener_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var label = ""
            var sink = []

            func _on_async_http():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tsink.append(label + ":" + str(payload["id"]) + ":" + str(payload["event_type"]))
            """
        )
        legacy_listener_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var sink = []

            func _on_http_request_completed():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tsink.append("legacy:" + str(payload["id"]))
            """
        )
        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const ListenerScript = preload("res://listener.gd")
            const LegacyListenerScript = preload("res://legacy_listener.gd")

            var order = []
            var legacy_order = []

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tGMRuntime.gml_async_event_log_clear()
            \tvar first = _listener("A")
            \tvar second = _listener("B")
            \tadd_child(first)
            \tadd_child(second)

            \tvar first_id = GMRuntime.gml_async_enqueue("http", {"id": 101, "status": 200, "result": "one", "url": "/one"})
            \tvar second_id = GMRuntime.gml_async_enqueue("http", {"id": 102, "status": 201, "result": "two", "url": "/two"})
            \tif not _check(first_id == 101 and second_id == 102, "enqueue returned wrong ids"):
            \t\treturn
            \tif not _check(GMRuntime.gml_async_queue_size() == 2, "queue size mismatch before flush"):
            \t\treturn
            \tif not _check(order.is_empty(), "enqueue dispatched before flush"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("async_load").is_empty(), "async_load set before flush"):
            \t\treturn

            \tvar flushed = GMRuntime.gml_async_queue_flush()
            \tif not _check(flushed == 2, "flush count mismatch"):
            \t\treturn
            \tif not _check(order == ["A:101:http", "B:101:http", "A:102:http", "B:102:http"], "listener FIFO order mismatch: " + str(order)):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("async_load").is_empty(), "async_load leaked after flush"):
            \t\treturn

            \tvar log = GMRuntime.gml_async_event_log()
            \tif not _check(log.size() == 2, "event log size mismatch"):
            \t\treturn
            \tif not _check(log[0]["queue_sequence"] < log[1]["queue_sequence"], "queue sequence did not increase"):
            \t\treturn
            \tif not _check(log[0]["dispatch_sequence"] == 1 and log[1]["dispatch_sequence"] == 2, "dispatch sequence mismatch"):
            \t\treturn
            \tif not _check(log[0]["listener_count"] == 2 and log[1]["listener_count"] == 2, "listener count mismatch"):
            \t\treturn

            \tremove_child(first)
            \tremove_child(second)
            \tfirst.queue_free()
            \tsecond.queue_free()
            \tvar legacy = Node.new()
            \tlegacy.set_script(LegacyListenerScript)
            \tlegacy.sink = legacy_order
            \tadd_child(legacy)
            \tGMRuntime.gml_async_dispatch("http", {"id": 103, "status": 200, "result": "legacy", "url": "/legacy"})
            \tif not _check(legacy_order == ["legacy:103"], "legacy HTTP alias did not dispatch"):
            \t\treturn

            \tvar schema = GMRuntime.gml_async_payload_schema("http")
            \tif not _check(schema["required"].has("url") and schema["optional"].has("network_result"), "HTTP async schema missing keys"):
            \t\treturn
            \tvar all_schemas = GMRuntime.gml_async_payload_schema()
            \tif not _check(all_schemas["default"]["lifetime"].contains("async_load is set only"), "default async lifecycle schema missing"):
            \t\treturn

            \tvar diagnostic_id = GMRuntime.gml_async_dispatch_unsupported("cloud_save", "cloud_synchronise", "cloud", "", "missing test hook")
            \tvar diagnostics = GMRuntime.gml_async_unsupported_diagnostics()
            \tif not _check(diagnostics.size() == 1 and diagnostics[0]["api"] == "cloud_synchronise", "unsupported diagnostic missing"):
            \t\treturn
            \tlog = GMRuntime.gml_async_event_log()
            \tvar diagnostic_event = log[log.size() - 1]
            \tif not _check(diagnostic_event["payload"]["id"] == diagnostic_id, "diagnostic request id mismatch"):
            \t\treturn
            \tif not _check(diagnostic_event["payload"]["status"] == -1, "diagnostic status mismatch"):
            \t\treturn
            \tif not _check(diagnostic_event["handler"] == "_on_async_cloud_save", "diagnostic handler mismatch"):
            \t\treturn

            \tprint("ASYNC_QUEUE_SMOKE_OK")
            \tget_tree().quit(0)

            func _listener(label):
            \tvar node = Node.new()
            \tnode.set_script(ListenerScript)
            \tnode.label = label
            \tnode.sink = order
            \treturn node
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "listener.gd", listener_script)
            _write_text(project_dir / "legacy_listener.gd", legacy_listener_script)
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ASYNC_QUEUE_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
