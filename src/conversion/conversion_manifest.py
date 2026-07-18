from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

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
_MANIFEST_FILENAME = os.path.basename(CONVERSION_MANIFEST_RELATIVE_PATH)
_IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"})
_AUDIO_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
_FONT_EXTENSIONS = frozenset({".otf", ".ttf", ".woff", ".woff2"})

FileFingerprint: TypeAlias = tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ConversionOutputSnapshot:
    """Destination state captured before a conversion starts."""

    files: Mapping[str, FileFingerprint]


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
    output_snapshot: ConversionOutputSnapshot,
) -> str:
    manifest_path = os.path.join(godot_project_path, CONVERSION_MANIFEST_RELATIVE_PATH)
    payload = build_conversion_manifest(
        gm_project_path,
        godot_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
        output_snapshot=output_snapshot,
    )

    manifest_directory = os.path.dirname(manifest_path)
    os.makedirs(manifest_directory, exist_ok=True)
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=manifest_directory,
        prefix=f".{_MANIFEST_FILENAME}.",
        suffix=".tmp",
    )
    staged_pending = True
    try:
        manifest_file = os.fdopen(file_descriptor, "w", encoding="utf-8", newline="")
        file_descriptor = -1
        with manifest_file:
            json.dump(payload, manifest_file, indent=2, sort_keys=True)
            manifest_file.write("\n")
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.replace(staged_path, manifest_path)
        staged_pending = False
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if staged_pending:
            try:
                os.unlink(staged_path)
            except OSError:
                pass
    return manifest_path


def invalidate_conversion_manifest(godot_project_path: str) -> None:
    """Remove a manifest that can no longer describe the current output."""
    manifest_path = os.path.join(
        godot_project_path,
        CONVERSION_MANIFEST_RELATIVE_PATH,
    )
    try:
        os.unlink(manifest_path)
    except FileNotFoundError:
        return


def build_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
    output_snapshot: ConversionOutputSnapshot,
) -> JsonDict:
    enabled_converter_keys = tuple(sorted(set(enabled_converters)))
    project_manifest = load_gamemaker_project_manifest(gm_project_path, target_platform=target_platform)
    asset_entries = _asset_registry_entries(
        gm_project_path,
        godot_project_path,
        macro_configuration=target_platform,
    )
    generated_files = _generated_files(godot_project_path, output_snapshot)
    return {
        "format_version": 1,
        "target_platform": target_platform,
        "enabled_converters": list(enabled_converter_keys),
        "source_project": {
            "name": project_manifest.project_name,
            "yyp_path": _relative_source_path(project_manifest.yyp_path, gm_project_path),
            "resource_type": project_manifest.resource_type,
            "resource_version": project_manifest.resource_version,
            "ide_version": project_manifest.ide_version,
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
    *,
    macro_configuration: str | None = None,
) -> tuple[AssetRegistryEntry, ...]:
    converter = AssetRegistryConverter(
        gm_project_path,
        godot_project_path,
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
        macro_configuration=macro_configuration,
    )
    return converter.build_entries()


def capture_conversion_output_snapshot(godot_project_path: str) -> ConversionOutputSnapshot:
    """Capture destination files before conversion so emitted outputs are identifiable."""
    files = {
        relative_path: fingerprint
        for _path, relative_path, fingerprint in _destination_files(godot_project_path)
    }
    return ConversionOutputSnapshot(files=files)


def _generated_files(
    godot_project_path: str,
    output_snapshot: ConversionOutputSnapshot,
) -> tuple[GeneratedFileEntry, ...]:
    entries: list[GeneratedFileEntry] = []
    manifest_relative_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/")
    for path, relative_path, fingerprint in _destination_files(godot_project_path):
        if relative_path == manifest_relative_path:
            continue
        if output_snapshot.files.get(relative_path) == fingerprint:
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
            path=manifest_relative_path,
            kind="manifest",
            sha256="self",
        )
    )
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _destination_files(
    godot_project_path: str,
) -> Iterable[tuple[str, str, FileFingerprint]]:
    if os.path.islink(godot_project_path) or not os.path.isdir(godot_project_path):
        return
    for root, dirs, files in os.walk(godot_project_path):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if directory != ".godot"
            and not os.path.islink(os.path.join(root, directory))
        )
        for filename in sorted(files):
            path = os.path.join(root, filename)
            try:
                path_stat = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(path_stat.st_mode):
                continue
            relative_path = os.path.relpath(path, godot_project_path).replace(os.sep, "/")
            yield path, relative_path, _file_fingerprint(path_stat)


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


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
    extension = os.path.splitext(relative_path)[1].lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _FONT_EXTENSIONS:
        return "font"
    if extension == ".import":
        return "import_metadata"
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
