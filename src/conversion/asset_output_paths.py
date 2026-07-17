from __future__ import annotations

import os

from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.type_defs import ConversionRunning, StrPath


def build_asset_output_paths(
    gm_project_path: StrPath,
    godot_project_path: StrPath,
    *,
    conversion_running: ConversionRunning | None = None,
    organize_sounds_by_audio_group: bool = False,
) -> dict[str, dict[str, str]]:
    """Return the registry's collision-safe res:// path for every source asset."""
    converter = AssetRegistryConverter(
        gm_project_path,
        godot_project_path,
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=conversion_running,
        organize_sounds_by_audio_group=organize_sounds_by_audio_group,
    )
    paths: dict[str, dict[str, str]] = {}
    for entry in converter.build_entries():
        # Modern-script function aliases share the script kind. The actual
        # resource entry appears first and wins this deterministic name map.
        paths.setdefault(entry.kind, {}).setdefault(entry.name, entry.godot_path)
    return paths


def resource_sibling_path(resource_path: str, extension: str) -> str:
    """Return a sibling res:// path with the same collision-safe stem."""
    stem, _current_extension = os.path.splitext(resource_path)
    return stem + extension


def resource_filesystem_path(godot_project_path: StrPath, resource_path: str) -> str:
    """Resolve a generated res:// path beneath a Godot project root."""
    if not resource_path.startswith("res://"):
        raise ValueError(f"Expected a res:// generated resource path, got {resource_path!r}")
    relative = resource_path.removeprefix("res://").replace("\\", "/")
    parts = relative.split("/")
    if not relative or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Unsafe generated resource path: {resource_path!r}")
    return os.path.join(os.fspath(godot_project_path), *parts)
