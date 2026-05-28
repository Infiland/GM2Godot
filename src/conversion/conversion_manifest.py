from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Iterable

from src.conversion.architecture_policy import build_architecture_policy_report
from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_nested_resource_path,
    generated_resource_stem,
    is_snake_case_path_segment,
    res_path_segments,
    snake_case_res_path,
)
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.type_defs import JsonDict

CONVERSION_MANIFEST_RELATIVE_PATH = os.path.join("gm2godot", "conversion_manifest.json")
_GODOT_RESOURCE_EXTENSIONS = (".gd", ".gdshader", ".tscn", ".tres", ".json")


@dataclass(frozen=True)
class GeneratedFileEntry:
    path: str
    kind: str
    sha256: str

    def to_dict(self) -> JsonDict:
        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
        }


def write_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> str:
    manifest_path = os.path.join(godot_project_path, CONVERSION_MANIFEST_RELATIVE_PATH)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    payload = build_conversion_manifest(
        gm_project_path,
        godot_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
    )
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(payload, manifest_file, indent=2, sort_keys=True)
        manifest_file.write("\n")
    return manifest_path


def build_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> JsonDict:
    enabled_converter_keys = tuple(sorted(set(enabled_converters)))
    project_manifest = load_gamemaker_project_manifest(gm_project_path, target_platform=target_platform)
    asset_entries = _asset_registry_entries(gm_project_path, godot_project_path)
    generated_files = _generated_files(godot_project_path)
    return {
        "format_version": 1,
        "target_platform": target_platform,
        "enabled_converters": list(enabled_converter_keys),
        "source_project": {
            "name": project_manifest.project_name,
            "yyp_path": _relative_source_path(project_manifest.yyp_path, gm_project_path),
            "resource_type": project_manifest.resource_type,
            "resource_version": project_manifest.resource_version,
        },
        "resources": [entry.to_godot_dict() for entry in asset_entries],
        "generated_files": [entry.to_dict() for entry in generated_files],
        "source_maps": [
            entry.to_dict()
            for entry in generated_files
            if entry.path.endswith(".gmlmap.json")
        ],
        "architecture_policies": build_architecture_policy_report(
            gm_project_path,
            target_platform=target_platform,
            enabled_converters=enabled_converter_keys,
        ),
        "path_diagnostics": _path_diagnostics(asset_entries),
    }


def _asset_registry_entries(
    gm_project_path: str,
    godot_project_path: str,
) -> tuple[AssetRegistryEntry, ...]:
    converter = AssetRegistryConverter(
        gm_project_path,
        godot_project_path,
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
    )
    return converter.build_entries()


def _generated_files(godot_project_path: str) -> tuple[GeneratedFileEntry, ...]:
    entries: list[GeneratedFileEntry] = []
    for root, dirs, files in os.walk(godot_project_path):
        dirs[:] = sorted(directory for directory in dirs if directory != ".godot")
        for filename in sorted(files):
            path = os.path.join(root, filename)
            relative_path = os.path.relpath(path, godot_project_path).replace(os.sep, "/")
            if relative_path == CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"):
                continue
            if not _is_generated_manifest_file(relative_path):
                continue
            entries.append(
                GeneratedFileEntry(
                    path=relative_path,
                    kind=_generated_file_kind(relative_path),
                    sha256=_sha256_file(path),
                )
            )
    entries.append(
        GeneratedFileEntry(
            path=CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            kind="manifest",
            sha256="self",
        )
    )
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _is_generated_manifest_file(relative_path: str) -> bool:
    if relative_path == "project.godot":
        return True
    return relative_path.endswith(_GODOT_RESOURCE_EXTENSIONS)


def _generated_file_kind(relative_path: str) -> str:
    if relative_path == "project.godot":
        return "project"
    if relative_path.endswith(".gmlmap.json"):
        return "source_map"
    if relative_path.endswith(".json"):
        return "report"
    if relative_path.endswith(".gd"):
        return "gdscript"
    if relative_path.endswith(".gdshader"):
        return "shader"
    if relative_path.endswith(".tscn"):
        return "scene"
    if relative_path.endswith(".tres"):
        return "resource"
    return "file"


def _path_diagnostics(entries: tuple[AssetRegistryEntry, ...]) -> list[JsonDict]:
    diagnostics: list[JsonDict] = []
    paths_by_casefold: dict[str, list[AssetRegistryEntry]] = {}
    base_paths_by_casefold: dict[str, list[tuple[AssetRegistryEntry, str]]] = {}
    for entry in entries:
        if not entry.godot_path:
            continue
        paths_by_casefold.setdefault(entry.godot_path.casefold(), []).append(entry)
        base_path = _base_generated_path(entry)
        if base_path:
            base_paths_by_casefold.setdefault(base_path.casefold(), []).append((entry, base_path))
        unsafe_segments = _unsafe_segments(entry.godot_path)
        if unsafe_segments:
            diagnostics.append({
                "code": "GM2GD-PATH-NON-SNAKE-CASE",
                "severity": "info",
                "resource": entry.name,
                "resource_type": entry.kind,
                "godot_path": entry.godot_path,
                "unsafe_segments": unsafe_segments,
                "stable_suggestion": snake_case_res_path(entry.godot_path),
                "message": "Generated path contains non-snake-case segments; source metadata preserves the original GameMaker name.",
            })

    for folded_path, colliding_items in sorted(base_paths_by_casefold.items()):
        if len(colliding_items) < 2:
            continue
        diagnostics.append({
            "code": "GM2GD-PATH-COLLISION-RENAMED",
            "severity": "warning",
            "base_godot_path_casefold": folded_path,
            "resources": [
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "source_path": entry.source_path,
                    "base_godot_path": base_path,
                    "stable_godot_path": entry.godot_path,
                }
                for entry, base_path in sorted(
                    colliding_items,
                    key=lambda item: (item[0].kind, item[0].name, item[0].source_path),
                )
            ],
            "message": "Multiple GameMaker resources map to the same Godot-friendly path; stable suffixes were applied deterministically.",
        })

    for folded_path, colliding_entries in sorted(paths_by_casefold.items()):
        if len(colliding_entries) < 2:
            continue
        diagnostics.append({
            "code": "GM2GD-PATH-CASE-COLLISION",
            "severity": "warning",
            "godot_path_casefold": folded_path,
            "resources": [
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "source_path": entry.source_path,
                    "godot_path": entry.godot_path,
                }
                for entry in sorted(colliding_entries, key=lambda item: (item.kind, item.name, item.source_path))
            ],
            "stable_suggestions": [
                _collision_safe_path(entry.godot_path, index)
                for index, entry in enumerate(sorted(colliding_entries, key=lambda item: (item.kind, item.name, item.source_path)))
            ],
            "message": "Generated paths collide on case-insensitive file systems; suggestions are deterministic for project-specific remapping.",
        })
    return diagnostics


def _base_generated_path(entry: AssetRegistryEntry) -> str:
    segments = res_path_segments(entry.godot_path)
    if len(segments) < 2:
        return ""
    kind = segments[0]
    if kind in {"sprites", "objects", "rooms", "tilesets", "paths"} and len(segments) >= 3:
        extension = os.path.splitext(segments[-1])[1]
        subfolder = "/".join(segments[1:-2])
        return generated_nested_resource_path(kind, subfolder, entry.name, extension)
    if kind in {"scripts", "shaders", "fonts"}:
        extension = os.path.splitext(segments[-1])[1]
        subfolder = "/".join(segments[1:-1])
        return generated_flat_resource_path(kind, subfolder, entry.name, extension)
    if kind == "sounds" and len(segments) >= 3:
        base_segments = list(segments)
        base_segments[-2] = generated_resource_stem(entry.name)
        return "res://" + "/".join(base_segments)
    return entry.godot_path


def _unsafe_segments(res_path: str) -> list[str]:
    segments = res_path_segments(res_path)
    return [
        segment
        for segment in segments
        if not is_snake_case_path_segment(segment)
    ]


def _collision_safe_path(res_path: str, index: int) -> str:
    if index == 0:
        return snake_case_res_path(res_path)
    snake_path = snake_case_res_path(res_path)
    stem, extension = os.path.splitext(snake_path)
    return f"{stem}_{index + 1}{extension}"


def _relative_source_path(path: str | None, gm_project_path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path, gm_project_path).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
