from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class _AsyncSmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_text("GET:" + self.path)

    def do_POST(self) -> None:
        self._send_text("POST:" + self._read_body())

    def do_PUT(self) -> None:
        self._send_text("PUT:" + self._read_body())

    def log_message(self, format: str, *_args: object) -> None:
        return

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length).decode("utf-8")

    def _send_text(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class TestAsyncHttpGodotSmoke(unittest.TestCase):
    def test_http_requests_dispatch_async_load_to_generated_handlers(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        server = ThreadingHTTPServer(("127.0.0.1", 0), _AsyncSmokeHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var expected = {}
            var seen = {}
            var save_seen = false
            var dialog_seen = false

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tvar get_id = GMRuntime.gml_http_get("http://127.0.0.1:__PORT__/hello")
            \texpected[get_id] = "GET:/hello"
            \tvar post_id = GMRuntime.gml_http_post_string("http://127.0.0.1:__PORT__/post", "x=1")
            \texpected[post_id] = "POST:x=1"
            \tvar put_id = GMRuntime.gml_http_request("http://127.0.0.1:__PORT__/put", "PUT", ["X-Test: 1"], "body")
            \texpected[put_id] = "PUT:body"

            \tvar buffer = GMRuntime.gml_buffer_create(4, 1, 1)
            \tGMRuntime.gml_buffer_write(buffer, 11, "save")
            \tvar save_id = GMRuntime.gml_buffer_save_async(buffer, "save/async_bridge.bin")

            \tGMRuntime.gml_async_dispatch("dialog", {"id": 999, "status": 0}, "_on_async_dialog")
            \tif not _check(dialog_seen, "manual async dialog dispatch did not reach handler"):
            \t\treturn

            \tfor _i in range(30):
            \t\tif seen.size() == expected.size() and save_seen:
            \t\t\tbreak
            \t\tawait get_tree().create_timer(0.1).timeout

            \tif not _check(seen.size() == expected.size(), "not all HTTP async events arrived"):
            \t\treturn
            \tif not _check(save_seen, "buffer save async event did not dispatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_async_event_log().size() >= 5, "async event log missing events"):
            \t\treturn

            \tprint("ASYNC_HTTP_SMOKE_OK")
            \tget_tree().quit(0)

            func _on_async_http():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tvar request_id = payload["id"]
            \tif expected.has(request_id):
            \t\tif payload["status"] == 200 and payload["result"] == expected[request_id]:
            \t\t\tseen[request_id] = payload

            func _on_async_save_load():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tif payload.has("filename") and payload["status"] == 0:
            \t\tsave_seen = true

            func _on_async_dialog():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tdialog_seen = payload["id"] == 999 and payload["event_type"] == "dialog"
            """
        ).replace("__PORT__", str(port))

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        try:
            with tempfile.TemporaryDirectory() as tmp:
                project_dir = Path(tmp)
                _write_text(project_dir / "project.godot", "[application]\n")
                write_gml_runtime(str(project_dir))
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
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ASYNC_HTTP_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
