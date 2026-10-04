"""Shared acquisition, text fixtures and runner for Godot smoke tests."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_smoke_godot_binary() -> str | None:
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


def write_fixture_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_headless_scene(
    godot_binary: str,
    project_dir: Path,
    scene_name: str,
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [godot_binary, "--headless", "--path", str(project_dir), scene_name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
