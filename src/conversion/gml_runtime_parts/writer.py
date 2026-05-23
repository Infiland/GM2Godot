from __future__ import annotations

import os

from src.conversion.runtime_managers import (
    register_runtime_manager_autoloads,
    write_runtime_managers,
)

from .script import GML_RUNTIME_SCRIPT

GML_RUNTIME_RELATIVE_PATH = os.path.join("gm2godot", "gml_runtime.gd")
GML_RUNTIME_RESOURCE_PATH = "res://gm2godot/gml_runtime.gd"


def write_gml_runtime(godot_project_path: str) -> str:
    runtime_path = os.path.join(godot_project_path, GML_RUNTIME_RELATIVE_PATH)
    os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
    with open(runtime_path, "w", encoding="utf-8") as f:
        f.write(GML_RUNTIME_SCRIPT)
    write_runtime_managers(godot_project_path)
    register_runtime_manager_autoloads(godot_project_path)
    return runtime_path
