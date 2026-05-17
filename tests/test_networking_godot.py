from __future__ import annotations

import os
import shutil
import socket
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


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestNetworkingGodotSmoke(unittest.TestCase):
    def test_tcp_loopback_dispatches_async_networking_payload(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        port = _free_tcp_port()
        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            var server = null
            var client = null
            var connect_seen = false
            var sent = false
            var data_seen = false

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tserver = GMRuntime.gml_network_create_server(0, __PORT__, 4)
            \tif not _check(GMRuntime.gml_handle_is_valid(server), "server handle is invalid"):
            \t\treturn
            \tclient = GMRuntime.gml_network_create_socket(0)
            \tif not _check(GMRuntime.gml_handle_is_valid(client), "client handle is invalid"):
            \t\treturn
            \tvar connected = GMRuntime.gml_network_connect(client, "127.0.0.1", __PORT__)
            \tif not _check(GMRuntime.gml_handle_is_valid(connected), "connect returned invalid handle"):
            \t\treturn

            \tvar buffer = GMRuntime.gml_buffer_create(8, 1, 1)
            \tGMRuntime.gml_buffer_write(buffer, 11, "ping")

            \tfor _i in range(60):
            \t\tGMRuntime.gml_network_poll()
            \t\tif connect_seen and not sent:
            \t\t\tvar bytes_sent = GMRuntime.gml_network_send_raw(client, buffer, 4)
            \t\t\tif bytes_sent == 4:
            \t\t\t\tsent = true
            \t\tif data_seen:
            \t\t\tbreak
            \t\tawait get_tree().create_timer(0.05).timeout

            \tif not _check(sent, "client did not send raw bytes"):
            \t\treturn
            \tif not _check(data_seen, "server did not dispatch Async Networking data"):
            \t\treturn
            \tif not _check(GMRuntime.gml_async_event_log().size() >= 2, "networking events were not logged"):
            \t\treturn

            \tGMRuntime.gml_network_destroy(client)
            \tGMRuntime.gml_network_destroy(server)
            \tprint("NETWORK_SMOKE_OK")
            \tget_tree().quit(0)

            func _on_async_networking():
            \tvar payload = GMRuntime.gml_builtin_global("async_load")
            \tif payload["type"] == 1:
            \t\tconnect_seen = true
            \telif payload["type"] == 3:
            \t\tvar packet_buffer = payload["buffer"]
            \t\tvar text = GMRuntime.gml_buffer_read(packet_buffer, 11)
            \t\tif payload["size"] == 4 and text == "ping":
            \t\t\tdata_seen = true
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

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
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
                self.fail("Godot networking smoke timed out\n" + output)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("NETWORK_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
