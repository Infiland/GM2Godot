from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import ClassVar, Iterable, cast

from src.conversion.base_converter import BaseConverter
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectTextureGroup,
    load_gamemaker_project_manifest,
)
from src.conversion.gml_transpiler import GMLTranspileError, transpile_gml_code
from src.conversion.type_defs import (
    ConversionRunning,
    JsonDict,
    LogCallback,
    ProgressCallback,
    StrPath,
)
from src.conversion.path_registry import write_path_registry
from src.conversion.animation_curve_registry import write_animation_curve_registry

ASSET_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_asset_registry.gd")
ASSET_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_asset_registry.gd"
GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH = os.path.join("gm2godot", "group_compatibility_report.json")
STATIC_ASSET_ID_MASK = 0x3FFFFFFF


def _empty_int_list() -> list[int]:
    return []


def _empty_str_list() -> list[str]:
    return []


@dataclass(frozen=True)
class AssetRegistryEntry:
    id: int
    name: str
    kind: str
    asset_type: str
    type_name: str
    source_path: str
    godot_path: str
    legacy_id: str
    tags: tuple[str, ...] = ()
    dynamic: bool = False
    metadata: JsonDict | None = None

    def to_godot_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "type": self.asset_type,
            "type_name": self.type_name,
            "source_path": self.source_path,
            "godot_path": self.godot_path,
            "legacy_id": self.legacy_id,
            "tags": list(self.tags),
            "dynamic": self.dynamic,
            "metadata": self.metadata or {},
        }


@dataclass(frozen=True)
class _ProjectResource:
    kind: str
    name: str
    yy_path: str
    source_path: str
    raw_data: JsonDict


@dataclass
class _TextureGroupRegistryEntry:
    name: str
    parent: str = ""
    dynamic: bool = False
    dynamic_path: str = ""
    targets: tuple[str, ...] = ()
    asset_ids: list[int] = field(default_factory=_empty_int_list)
    asset_names: list[str] = field(default_factory=_empty_str_list)

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "parent": self.parent,
            "dynamic": self.dynamic,
            "dynamic_path": self.dynamic_path,
            "targets": list(self.targets),
            "asset_ids": sorted(self.asset_ids),
            "asset_names": sorted(self.asset_names),
        }


@dataclass
class _AudioGroupRegistryEntry:
    name: str
    targets: tuple[str, ...] = ()
    loaded: bool = False
    gain: float = 1.0
    asset_ids: list[int] = field(default_factory=_empty_int_list)
    asset_names: list[str] = field(default_factory=_empty_str_list)

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "targets": list(self.targets),
            "loaded": self.loaded,
            "gain": self.gain,
            "asset_ids": sorted(self.asset_ids),
            "asset_names": sorted(self.asset_names),
        }


class AssetRegistryConverter(BaseConverter):
    """Generate a stable GameMaker asset registry for GMRuntime helpers."""

    RESOURCE_TYPE_BY_KIND: ClassVar[dict[str, str]] = {
        "sprites": "sprite",
        "sounds": "sound",
        "rooms": "room",
        "objects": "object",
        "scripts": "script",
        "fonts": "font",
        "paths": "path",
        "animcurves": "animation_curve",
        "shaders": "shader",
        "tilesets": "tileset",
        "particlesystems": "particle_system",
        "timelines": "timeline",
        "sequences": "sequence",
        "included_files": "included_file",
    }
    TYPE_NAME_BY_KIND: ClassVar[dict[str, str]] = {
        "sprites": "Sprite",
        "sounds": "Sound",
        "rooms": "Room",
        "objects": "Object",
        "scripts": "Script",
        "fonts": "Font",
        "paths": "Path",
        "animcurves": "Animation Curve",
        "shaders": "Shader",
        "tilesets": "Tile Set",
        "particlesystems": "Particle System",
        "timelines": "Timeline",
        "sequences": "Sequence",
        "included_files": "Included File",
    }
    STATIC_RESOURCE_EXTENSIONS: ClassVar[dict[str, str]] = {
        "sprites": ".tscn",
        "objects": ".tscn",
        "rooms": ".tscn",
        "tilesets": ".tres",
        "paths": ".tscn",
    }
    KIND_ORDER: ClassVar[dict[str, int]] = {
        kind: index for index, kind in enumerate(RESOURCE_TYPE_BY_KIND)
    }
    FOLDER_BY_KIND: ClassVar[dict[str, str]] = {
        **{kind: kind for kind in RESOURCE_TYPE_BY_KIND if kind != "included_files"},
        "included_files": "datafiles",
    }

    def __init__(
        self,
        gm_project_path: StrPath,
        godot_project_path: StrPath,
        log_callback: LogCallback = print,
        progress_callback: ProgressCallback | None = None,
        conversion_running: ConversionRunning | None = None,
        update_log_callback: LogCallback | None = None,
        compact_logging: bool = False,
        max_workers: int | None = None,
        organize_sounds_by_audio_group: bool = False,
    ) -> None:
        super().__init__(
            gm_project_path,
            godot_project_path,
            log_callback,
            progress_callback,
            conversion_running,
            update_log_callback,
            compact_logging,
            max_workers=max_workers,
        )
        self.organize_sounds_by_audio_group = bool(organize_sounds_by_audio_group)
        self.project_manifest: GameMakerProjectManifest = load_gamemaker_project_manifest(
            self.gm_project_path
        )

    def build_entries(self) -> tuple[AssetRegistryEntry, ...]:
        resources = sorted(
            self._load_project_resources(),
            key=lambda resource: (
                self.KIND_ORDER.get(resource.kind, len(self.KIND_ORDER)),
                resource.name.lower(),
                resource.source_path,
            ),
        )
        room_order_indices = self._room_order_indices(resources)
        used_ids: set[int] = set()
        entries: list[AssetRegistryEntry] = []

        for resource in resources:
            if not self.conversion_running():
                break
            asset_type = self.RESOURCE_TYPE_BY_KIND[resource.kind]
            entry = AssetRegistryEntry(
                id=self._stable_asset_id(asset_type, resource.name, used_ids),
                name=resource.name,
                kind=resource.kind,
                asset_type=asset_type,
                type_name=self.TYPE_NAME_BY_KIND[resource.kind],
                source_path=resource.source_path,
                godot_path=self._godot_path(resource),
                legacy_id=self._legacy_id(resource),
                tags=self._extract_tags(resource.raw_data),
                metadata=self._metadata(resource, room_order_indices),
            )
            entries.append(entry)

        return tuple(entries)

    def convert_all(self) -> str:
        entries = self.build_entries()
        texture_groups, audio_groups = self.build_group_registries(entries)
        registry_path = os.path.join(self.godot_project_path, ASSET_REGISTRY_RELATIVE_PATH)
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)

        with open(registry_path, "w", encoding="utf-8") as f:
            f.write(
                render_asset_registry_script(
                    entries,
                    texture_groups=texture_groups,
                    audio_groups=audio_groups,
                )
            )
        self._write_group_compatibility_report(entries, texture_groups, audio_groups)
        self._write_timeline_action_scripts(entries)
        write_path_registry(self.gm_project_path, self.godot_project_path, entries)
        write_animation_curve_registry(self.gm_project_path, self.godot_project_path, entries)

        self.log_callback(
            "Generated GameMaker asset registry: {path} ({count} assets)".format(
                path=ASSET_REGISTRY_RELATIVE_PATH.replace(os.sep, "/"),
                count=len(entries),
            )
        )
        return registry_path

    def build_group_registries(
        self,
        entries: tuple[AssetRegistryEntry, ...],
    ) -> tuple[tuple[JsonDict, ...], tuple[JsonDict, ...]]:
        """Return generated texture/audio group registry entries."""
        return (
            self._texture_group_registry(entries),
            self._audio_group_registry(entries),
        )

    def _load_project_resources(self) -> tuple[_ProjectResource, ...]:
        yyp_path = self._find_yyp_path()
        if yyp_path is not None:
            yyp_data = self._read_yy_file(yyp_path)
            if yyp_data is not None:
                resources = list(self._resources_from_yyp(yyp_data))
                resources.extend(self._included_files_from_disk())
                return tuple(self._dedupe_resources(resources))

            self._safe_log("Warning: Could not parse GameMaker project .yyp; using disk asset scan.")

        resources = list(self._resources_from_disk())
        resources.extend(self._included_files_from_disk())
        return tuple(self._dedupe_resources(resources))

    def _find_yyp_path(self) -> str | None:
        try:
            yyp_files = sorted(
                name for name in os.listdir(self.gm_project_path) if name.endswith(".yyp")
            )
        except OSError:
            return None

        if not yyp_files:
            return None
        return os.path.join(self.gm_project_path, yyp_files[0])

    def _resources_from_yyp(self, yyp_data: JsonDict) -> tuple[_ProjectResource, ...]:
        resource_entries = yyp_data.get("resources")
        if not isinstance(resource_entries, list):
            return ()

        resources: list[_ProjectResource] = []
        for raw_entry in cast(list[object], resource_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(JsonDict, raw_entry)
            raw_id = entry.get("id")
            if not isinstance(raw_id, dict):
                continue
            resource_id = cast(JsonDict, raw_id)
            raw_path = resource_id.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                continue

            kind = self._normalize_yyp_kind(raw_path)
            if kind not in self.RESOURCE_TYPE_BY_KIND or kind == "included_files":
                continue

            raw_name = resource_id.get("name")
            name = raw_name if isinstance(raw_name, str) and raw_name else self._name_from_path(raw_path)
            if not name:
                continue

            yy_path = os.path.normpath(os.path.join(self.gm_project_path, raw_path))
            if not os.path.isfile(yy_path):
                self._safe_log(f"Skipping missing GameMaker asset {name}: {yy_path}")
                continue

            resources.append(
                _ProjectResource(
                    kind=kind,
                    name=name,
                    yy_path=yy_path,
                    source_path=raw_path.replace("\\", "/"),
                    raw_data=self._read_yy_file(yy_path) or {},
                )
            )
        return tuple(resources)

    def _resources_from_disk(self) -> tuple[_ProjectResource, ...]:
        resources: list[_ProjectResource] = []
        for kind in self.RESOURCE_TYPE_BY_KIND:
            if kind == "included_files":
                continue
            folder = self.FOLDER_BY_KIND[kind]
            kind_dir = os.path.join(self.gm_project_path, folder)
            if not os.path.isdir(kind_dir):
                continue

            try:
                resource_names = sorted(os.listdir(kind_dir))
            except OSError:
                continue

            for name in resource_names:
                resource_dir = os.path.join(kind_dir, name)
                yy_path = os.path.join(resource_dir, name + ".yy")
                if not os.path.isdir(resource_dir) or not os.path.isfile(yy_path):
                    continue
                source_path = "/".join([folder, name, name + ".yy"])
                resources.append(
                    _ProjectResource(
                        kind=kind,
                        name=name,
                        yy_path=yy_path,
                        source_path=source_path,
                        raw_data=self._read_yy_file(yy_path) or {},
                    )
                )
        return tuple(resources)

    def _included_files_from_disk(self) -> tuple[_ProjectResource, ...]:
        datafiles_dir = os.path.join(self.gm_project_path, "datafiles")
        if not os.path.isdir(datafiles_dir):
            return ()

        resources: list[_ProjectResource] = []
        for root, dirs, files in os.walk(datafiles_dir):
            dirs.sort()
            for filename in sorted(files):
                if filename.endswith(".yy"):
                    continue
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, datafiles_dir).replace(os.sep, "/")
                resources.append(
                    _ProjectResource(
                        kind="included_files",
                        name=rel_path,
                        yy_path="",
                        source_path="datafiles/" + rel_path,
                        raw_data={},
                    )
                )
        return tuple(resources)

    @staticmethod
    def _dedupe_resources(resources: list[_ProjectResource]) -> tuple[_ProjectResource, ...]:
        deduped: dict[tuple[str, str], _ProjectResource] = {}
        for resource in resources:
            deduped.setdefault((resource.kind, resource.name), resource)
        return tuple(deduped.values())

    def _godot_path(self, resource: _ProjectResource) -> str:
        if resource.kind in self.STATIC_RESOURCE_EXTENSIONS:
            return self._nested_resource_path(
                resource.kind,
                self._get_subfolder_from_resource(resource),
                resource.name,
                self.STATIC_RESOURCE_EXTENSIONS[resource.kind],
            )
        if resource.kind == "sounds":
            return self._sound_godot_path(resource)
        if resource.kind == "fonts":
            return self._font_godot_path(resource)
        if resource.kind == "scripts":
            return self._flat_resource_path("scripts", self._get_subfolder_from_resource(resource), resource.name, ".gd")
        if resource.kind == "shaders":
            return self._flat_resource_path("shaders", self._get_subfolder_from_resource(resource), resource.name, ".gdshader")
        if resource.kind == "included_files":
            return "res://included_files/" + resource.name
        return ""

    def _sound_godot_path(self, resource: _ProjectResource) -> str:
        sound_file = resource.raw_data.get("soundFile")
        if not isinstance(sound_file, str) or not sound_file:
            return ""

        parts = ["sounds"]
        if self.organize_sounds_by_audio_group:
            audio_group = self._reference_name(resource.raw_data.get("audioGroupId"))
            parts.append(audio_group or "audiogroup_default")
        subfolder = self._get_subfolder_from_resource(resource)
        parts.extend(part for part in subfolder.split("/") if part)
        parts.extend([resource.name, sound_file])
        return "res://" + "/".join(parts)

    def _metadata(
        self,
        resource: _ProjectResource,
        room_order_indices: dict[str, int] | None = None,
    ) -> JsonDict:
        if resource.kind == "rooms":
            room_settings = resource.raw_data.get("roomSettings")
            settings = cast(JsonDict, room_settings) if isinstance(room_settings, dict) else {}
            return {
                "room_order": (room_order_indices or {}).get(resource.name, -1),
                "width": self._metadata_int(settings.get("Width"), 1024),
                "height": self._metadata_int(settings.get("Height"), 768),
                "persistent": bool(settings.get("persistent", False)),
                "volume": self._metadata_float(resource.raw_data.get("volume"), 1.0),
            }

        if resource.kind == "sequences":
            return self._sequence_metadata(resource.raw_data)

        if resource.kind == "timelines":
            return self._timeline_metadata(resource)

        if resource.kind == "particlesystems":
            return self._particle_system_metadata(resource.raw_data)

        if resource.kind in {"sprites", "fonts", "tilesets"}:
            texture_group = self._reference_name(resource.raw_data.get("textureGroupId"))
            if texture_group:
                return self._texture_group_asset_metadata(texture_group)
            return {}

        if resource.kind != "sounds":
            return {}

        audio_group = self._reference_name(resource.raw_data.get("audioGroupId"))
        sound_file = resource.raw_data.get("soundFile")
        return {
            "audio_group": audio_group or "audiogroup_default",
            "sound_file": sound_file if isinstance(sound_file, str) else "",
            "volume": self._metadata_float(resource.raw_data.get("volume"), 1.0),
            "duration": self._metadata_float(resource.raw_data.get("duration"), 0.0),
            "preload": bool(resource.raw_data.get("preload", True)),
            "compression": self._metadata_int(resource.raw_data.get("compression"), 0),
            "type": self._metadata_int(resource.raw_data.get("type"), 0),
        }

    def _texture_group_asset_metadata(self, texture_group: str) -> JsonDict:
        metadata: JsonDict = {"texture_group": texture_group}
        group = self._manifest_texture_group(texture_group)
        if group is None:
            return metadata
        metadata["texture_group_dynamic"] = group.is_dynamic
        metadata["texture_group_targets"] = list(group.targets)
        if group.dynamic_path:
            metadata["texture_group_dynamic_path"] = group.dynamic_path
        return metadata

    def _texture_group_registry(self, entries: tuple[AssetRegistryEntry, ...]) -> tuple[JsonDict, ...]:
        groups: dict[str, _TextureGroupRegistryEntry] = {}
        for manifest_group in self.project_manifest.texture_groups:
            if not manifest_group.name:
                continue
            groups[manifest_group.name] = _TextureGroupRegistryEntry(
                name=manifest_group.name,
                parent=manifest_group.parent,
                dynamic=manifest_group.is_dynamic,
                dynamic_path=manifest_group.dynamic_path,
                targets=manifest_group.targets,
            )

        for entry in entries:
            if entry.asset_type not in {"sprite", "font", "tileset"}:
                continue
            metadata = entry.metadata or {}
            group_name = self._metadata_string(metadata.get("texture_group"), "Default")
            group = groups.setdefault(group_name, _TextureGroupRegistryEntry(name=group_name))
            group.asset_ids.append(entry.id)
            group.asset_names.append(entry.name)

        return tuple(groups[name].to_dict() for name in sorted(groups))

    def _audio_group_registry(self, entries: tuple[AssetRegistryEntry, ...]) -> tuple[JsonDict, ...]:
        groups: dict[str, _AudioGroupRegistryEntry] = {}
        for manifest_group in self.project_manifest.audio_groups:
            if not manifest_group.name:
                continue
            groups[manifest_group.name] = _AudioGroupRegistryEntry(
                name=manifest_group.name,
                targets=manifest_group.targets,
                loaded=self._audio_group_initial_loaded(manifest_group.name, manifest_group.raw_data),
                gain=self._metadata_float(manifest_group.raw_data.get("gain"), 1.0),
            )

        groups.setdefault(
            "audiogroup_default",
            _AudioGroupRegistryEntry(name="audiogroup_default", loaded=True),
        )
        for entry in entries:
            if entry.asset_type != "sound":
                continue
            metadata = entry.metadata or {}
            group_name = self._metadata_string(metadata.get("audio_group"), "audiogroup_default")
            group = groups.setdefault(
                group_name,
                _AudioGroupRegistryEntry(
                    name=group_name,
                    loaded=group_name in {"", "audiogroup_default"},
                ),
            )
            group.asset_ids.append(entry.id)
            group.asset_names.append(entry.name)

        return tuple(groups[name].to_dict() for name in sorted(groups))

    def _write_group_compatibility_report(
        self,
        entries: tuple[AssetRegistryEntry, ...],
        texture_groups: tuple[JsonDict, ...],
        audio_groups: tuple[JsonDict, ...],
    ) -> str:
        report_path = os.path.join(self.godot_project_path, GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        payload = self._group_compatibility_report(entries, texture_groups, audio_groups)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        return report_path

    def _group_compatibility_report(
        self,
        entries: tuple[AssetRegistryEntry, ...],
        texture_groups: tuple[JsonDict, ...],
        audio_groups: tuple[JsonDict, ...],
    ) -> JsonDict:
        diagnostics: list[JsonDict] = []
        for group in texture_groups:
            name = self._metadata_string(group.get("name"), "Default")
            if bool(group.get("dynamic", False)):
                diagnostics.append(self._group_diagnostic(
                    "texture_group_dynamic_runtime",
                    "warning",
                    name,
                    "Godot imports textures as resources; GM2Godot tracks dynamic texture-group load state but cannot evict packed texture pages exactly like GameMaker.",
                ))
            if group.get("targets"):
                diagnostics.append(self._group_diagnostic(
                    "texture_group_platform_targets",
                    "info",
                    name,
                    "Texture group platform export targets are preserved in metadata; Godot export filtering must be handled by export presets or project-specific tooling.",
                ))

        for group in audio_groups:
            name = self._metadata_string(group.get("name"), "audiogroup_default")
            if name != "audiogroup_default":
                diagnostics.append(self._group_diagnostic(
                    "audio_group_memory_runtime",
                    "warning",
                    name,
                    "Audio group load/unload updates GM2Godot compatibility state; Godot ResourceLoader may still cache imported streams after unload.",
                ))
            if group.get("targets"):
                diagnostics.append(self._group_diagnostic(
                    "audio_group_platform_targets",
                    "info",
                    name,
                    "Audio group platform export targets are preserved in metadata; Godot export filtering must be handled by export presets or project-specific tooling.",
                ))

        for entry in entries:
            if entry.asset_type != "sound":
                continue
            metadata = entry.metadata or {}
            if metadata.get("preload") is False:
                diagnostics.append(self._group_diagnostic(
                    "sound_preload_lazy",
                    "info",
                    entry.name,
                    "Sound preload=false is preserved; runtime loading occurs through ResourceLoader when the sound or audio group is used.",
                ))
            if self._metadata_int(metadata.get("compression"), 0) != 0 or self._metadata_int(metadata.get("type"), 0) != 0:
                diagnostics.append(self._group_diagnostic(
                    "sound_import_semantics",
                    "warning",
                    entry.name,
                    "Sound compression/type metadata is preserved, but Godot import parameters cannot exactly reproduce every GameMaker audio packaging mode.",
                ))

        return {
            "format_version": 1,
            "texture_groups": list(texture_groups),
            "audio_groups": list(audio_groups),
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _group_diagnostic(code: str, severity: str, subject: str, message: str) -> JsonDict:
        return {
            "code": code,
            "severity": severity,
            "subject": subject,
            "message": message,
        }

    def _manifest_texture_group(self, name: str) -> ProjectTextureGroup | None:
        for group in self.project_manifest.texture_groups:
            if group.name == name:
                return group
        return None

    @staticmethod
    def _audio_group_initial_loaded(name: str, raw_data: JsonDict) -> bool:
        if name in {"", "audiogroup_default"}:
            return True
        for key in ("loaded", "preload", "loadOnStartup"):
            value = raw_data.get(key)
            if isinstance(value, bool):
                return value
        return False

    def _sequence_metadata(self, raw_data: JsonDict) -> JsonDict:
        length = raw_data.get("length")
        if length is None:
            length = raw_data.get("duration")
        playback_speed = raw_data.get("playbackSpeed")
        loopmode = raw_data.get("playback")
        if loopmode is None:
            loopmode = raw_data.get("loopmode")
        tracks = raw_data.get("tracks")
        return {
            "length": self._metadata_float(length, 0.0),
            "playback_speed": self._metadata_float(playback_speed, 1.0),
            "loopmode": self._metadata_int(loopmode, 0),
            "tracks": tracks if isinstance(tracks, list) else [],
            "moments": self._sequence_event_metadata(raw_data, ("moments", "momentEvents")),
            "broadcasts": self._sequence_event_metadata(raw_data, ("broadcastMessages", "broadcasts")),
        }

    def _timeline_metadata(self, resource: _ProjectResource) -> JsonDict:
        moments = self._timeline_moment_metadata(resource)
        frames = [
            self._metadata_int(moment.get("frame"), 0)
            for moment in moments
            if isinstance(moment.get("frame"), int | float)
        ]
        return {
            "moments": moments,
            "moment_count": len(moments),
            "max_moment": max(frames, default=-1),
        }

    def _timeline_moment_metadata(self, resource: _ProjectResource) -> list[JsonDict]:
        raw_moments = resource.raw_data.get("momentList")
        if not isinstance(raw_moments, list):
            raw_moments = resource.raw_data.get("moments")
        if not isinstance(raw_moments, list):
            raw_moments = []

        moments: list[JsonDict] = []
        for index, raw_moment in enumerate(cast(list[object], raw_moments)):
            if not isinstance(raw_moment, dict):
                continue
            moment = cast(JsonDict, raw_moment)
            frame = self._metadata_int(
                moment.get("moment", moment.get("frame", moment.get("time", index))),
                index,
            )
            actions = self._timeline_action_metadata(resource, moment, frame)
            moments.append({
                "frame": frame,
                "actions": actions,
                "source_path": resource.source_path,
            })

        if not moments:
            discovered_actions = self._timeline_discovered_source_actions(resource)
            for frame, actions in discovered_actions:
                moments.append({
                    "frame": frame,
                    "actions": actions,
                    "source_path": resource.source_path,
                })
        return sorted(moments, key=lambda item: self._metadata_int(item.get("frame"), 0))

    def _timeline_action_metadata(
        self,
        resource: _ProjectResource,
        moment: JsonDict,
        frame: int,
    ) -> list[JsonDict]:
        actions: list[JsonDict] = []
        for raw_action in self._raw_action_items(moment):
            action = self._timeline_action_from_raw(raw_action)
            if action is not None:
                actions.append(action)

        source_filename = self._timeline_source_filename(resource, moment, frame)
        if source_filename:
            source_path = self._resource_relative_path(resource, source_filename)
            actions.append({
                "kind": "gml",
                "source_path": source_path,
                "script_path": self._timeline_action_script_resource_path(resource.name, frame),
            })
        return actions

    def _timeline_discovered_source_actions(self, resource: _ProjectResource) -> list[tuple[int, list[JsonDict]]]:
        discovered: list[tuple[int, list[JsonDict]]] = []
        try:
            filenames = sorted(os.listdir(os.path.dirname(resource.yy_path)))
        except OSError:
            return discovered

        for filename in filenames:
            if not filename.lower().endswith(".gml"):
                continue
            frame = self._timeline_frame_from_filename(filename)
            if frame is None:
                continue
            discovered.append((
                frame,
                [{
                    "kind": "gml",
                    "source_path": self._resource_relative_path(resource, filename),
                    "script_path": self._timeline_action_script_resource_path(resource.name, frame),
                }],
            ))
        return discovered

    def _timeline_source_filename(
        self,
        resource: _ProjectResource,
        moment: JsonDict,
        frame: int,
    ) -> str:
        for key in ("gmlFile", "eventFile", "filename", "source", "sourceFile"):
            value = moment.get(key)
            if isinstance(value, str) and value:
                return value
        for candidate in (
            f"Moment_{frame}.gml",
            f"moment_{frame}.gml",
            f"Timeline_{frame}.gml",
            f"{frame}.gml",
        ):
            if os.path.isfile(os.path.join(os.path.dirname(resource.yy_path), candidate)):
                return candidate
        return ""

    def _raw_action_items(self, moment: JsonDict) -> list[object]:
        raw_actions = moment.get("actions")
        if not isinstance(raw_actions, list):
            raw_actions = moment.get("actionList")
        if isinstance(raw_actions, list):
            return list(cast(list[object], raw_actions))
        scripts = moment.get("scripts")
        if isinstance(scripts, list):
            return [{"script": script} for script in cast(list[object], scripts)]
        callable_name = moment.get("callable")
        if isinstance(callable_name, str) and callable_name:
            return [{"callable": callable_name}]
        return []

    def _timeline_action_from_raw(self, raw_action: object) -> JsonDict | None:
        if isinstance(raw_action, str) and raw_action:
            return {"kind": "script", "script": raw_action}
        if not isinstance(raw_action, dict):
            return None
        action = cast(JsonDict, raw_action)
        callable_name = action.get("callable")
        if isinstance(callable_name, str) and callable_name:
            return {"kind": "callable", "callable": callable_name}
        script = action.get("script") or action.get("scriptName") or action.get("name")
        if isinstance(script, str) and script:
            return {"kind": "script", "script": script}
        return {"kind": "metadata", "raw": action}

    def _sequence_event_metadata(self, raw_data: JsonDict, keys: tuple[str, ...]) -> list[JsonDict]:
        events: list[JsonDict] = []
        for key in keys:
            raw_events = raw_data.get(key)
            if not isinstance(raw_events, list):
                continue
            for index, raw_event in enumerate(cast(list[object], raw_events)):
                if not isinstance(raw_event, dict):
                    continue
                event = cast(JsonDict, raw_event)
                frame = self._metadata_float(
                    event.get("frame", event.get("moment", event.get("time", index))),
                    float(index),
                )
                normalized: JsonDict = {"frame": frame}
                for name in ("name", "message", "event", "callable", "script"):
                    value = event.get(name)
                    if isinstance(value, str) and value:
                        normalized[name] = value
                normalized["raw"] = event
                events.append(normalized)
        return sorted(events, key=lambda item: self._metadata_float(item.get("frame"), 0.0))

    def _particle_system_metadata(self, raw_data: JsonDict) -> JsonDict:
        return {
            "types": self._json_list(raw_data, ("particleTypes", "types")),
            "emitters": self._json_list(raw_data, ("emitters",)),
            "attractors": self._json_list(raw_data, ("attractors",)),
            "destroyers": self._json_list(raw_data, ("destroyers",)),
            "deflectors": self._json_list(raw_data, ("deflectors",)),
            "changers": self._json_list(raw_data, ("changers",)),
            "raw": raw_data,
        }

    def _write_timeline_action_scripts(self, entries: tuple[AssetRegistryEntry, ...]) -> None:
        asset_names = {entry.name for entry in entries}
        for entry in entries:
            if entry.asset_type != "timeline":
                continue
            metadata = entry.metadata or {}
            raw_moments = metadata.get("moments")
            if not isinstance(raw_moments, list):
                continue
            for raw_moment in cast(list[object], raw_moments):
                if not isinstance(raw_moment, dict):
                    continue
                moment = cast(JsonDict, raw_moment)
                frame = self._metadata_int(moment.get("frame"), 0)
                raw_actions = moment.get("actions")
                if not isinstance(raw_actions, list):
                    continue
                for raw_action in cast(list[object], raw_actions):
                    if not isinstance(raw_action, dict):
                        continue
                    action = cast(JsonDict, raw_action)
                    source_path = action.get("source_path")
                    script_path = action.get("script_path")
                    if isinstance(source_path, str) and isinstance(script_path, str):
                        self._write_timeline_action_script(entry.name, frame, source_path, script_path, asset_names)

    def _write_timeline_action_script(
        self,
        timeline_name: str,
        frame: int,
        source_path: str,
        script_path: str,
        asset_names: set[str],
    ) -> None:
        if not script_path.startswith("res://"):
            return
        gm_source_path = os.path.join(self.gm_project_path, *source_path.split("/"))
        try:
            with open(gm_source_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
        except OSError:
            self._safe_log(
                "Warning: Could not read GameMaker timeline moment code for "
                f"{timeline_name} frame {frame}: {gm_source_path}"
            )
            return

        try:
            body = transpile_gml_code(
                source,
                asset_names=asset_names,
                source_path=gm_source_path,
                event=f"timeline moment {frame}",
                preserve_source_comments=True,
                self_expression="_gm_instance",
                other_expression="GMRuntime.gml_instance_noone()",
                instance_target="_gm_instance",
            )
        except GMLTranspileError as exc:
            message = (
                "Warning: Could not transpile GameMaker timeline moment code for "
                f"{timeline_name} frame {frame}: {gm_source_path}: {exc}"
            )
            if self.diagnostics is not None:
                self.diagnostics.add_transpile_failure(
                    message,
                    source_path=gm_source_path,
                    line=exc.line,
                    column=exc.column,
                    resource=timeline_name,
                    resource_type="timeline",
                    event=f"moment {frame}",
                    workaround="Split or rewrite unsupported GML in this timeline moment.",
                )
            self._safe_log(message)
            return

        if not body.strip():
            body = "\tpass"
        output_path = os.path.join(self.godot_project_path, *script_path[len("res://"):].split("/"))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as script_file:
            script_file.write(
                "\n".join([
                    "extends RefCounted",
                    "",
                    'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")',
                    "",
                    "static func execute(_gm_instance):",
                    body.rstrip(),
                    "",
                ])
            )

    def _resource_relative_path(self, resource: _ProjectResource, filename: str) -> str:
        return os.path.join(
            os.path.dirname(resource.source_path),
            filename,
        ).replace(os.sep, "/")

    @staticmethod
    def _timeline_action_script_resource_path(timeline_name: str, frame: int) -> str:
        safe_name = "".join(char if char.isalnum() or char == "_" else "_" for char in timeline_name)
        return f"res://gm2godot/timelines/{safe_name}_{frame}.gd"

    @staticmethod
    def _timeline_frame_from_filename(filename: str) -> int | None:
        stem = os.path.splitext(filename)[0]
        digits = "".join(char for char in stem if char.isdigit())
        if not digits:
            return None
        return int(digits)

    @staticmethod
    def _json_list(raw_data: JsonDict, keys: tuple[str, ...]) -> list[object]:
        for key in keys:
            value = raw_data.get(key)
            if isinstance(value, list):
                return list(cast(list[object], value))
        return []

    def _room_order_indices(self, resources: Iterable[_ProjectResource]) -> dict[str, int]:
        rooms = {resource.name for resource in resources if resource.kind == "rooms"}
        if not rooms:
            return {}

        ordered: list[str] = []
        yyp_path = self._find_yyp_path()
        yyp_data = self._read_yy_file(yyp_path) if yyp_path is not None else None
        if yyp_data is not None and "RoomOrderNodes" in yyp_data:
            for raw_node in cast(list[object], yyp_data.get("RoomOrderNodes", [])):
                if not isinstance(raw_node, dict):
                    continue
                node = cast(JsonDict, raw_node)
                room_id = node.get("roomId")
                if not isinstance(room_id, dict):
                    continue
                room_ref = cast(JsonDict, room_id)
                name = room_ref.get("name")
                if not isinstance(name, str) or not name:
                    path = room_ref.get("path")
                    name = self._name_from_path(path) if isinstance(path, str) else ""
                if name in rooms and name not in ordered:
                    ordered.append(name)

        for name in sorted(rooms):
            if name not in ordered:
                ordered.append(name)
        return {name: index for index, name in enumerate(ordered)}

    def _font_godot_path(self, resource: _ProjectResource) -> str:
        subfolder = self._get_subfolder_from_resource(resource)
        ttf_name = resource.raw_data.get("TTFName")
        include_ttf = bool(resource.raw_data.get("includeTTF", False))
        if include_ttf and isinstance(ttf_name, str) and ttf_name:
            source_ttf_path = os.path.join(os.path.dirname(resource.yy_path), ttf_name)
            if os.path.isfile(source_ttf_path):
                return self._flat_resource_path("fonts", subfolder, ttf_name, "")

        generated_path = self._find_generated_font_path(resource.name, subfolder)
        if generated_path is not None:
            return generated_path
        return self._flat_resource_path("fonts", subfolder, resource.name, ".tres")

    def _find_generated_font_path(self, font_name: str, subfolder: str) -> str | None:
        search_dir = os.path.join(self.godot_project_path, "fonts", *subfolder.split("/")) if subfolder else os.path.join(self.godot_project_path, "fonts")
        if not os.path.isdir(search_dir):
            return None

        try:
            filenames = sorted(os.listdir(search_dir))
        except OSError:
            return None

        for filename in filenames:
            stem, ext = os.path.splitext(filename)
            if stem == font_name and ext.lower() in (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".tres"):
                relative_path = os.path.relpath(os.path.join(search_dir, filename), self.godot_project_path)
                return "res://" + relative_path.replace(os.sep, "/")
        return None

    def _get_subfolder_from_resource(self, resource: _ProjectResource) -> str:
        if not resource.yy_path:
            return ""
        return self._get_subfolder_from_yy(resource.yy_path)

    @staticmethod
    def _nested_resource_path(kind: str, subfolder: str, name: str, extension: str) -> str:
        parts = [kind]
        parts.extend(part for part in subfolder.split("/") if part)
        parts.extend([name, name + extension])
        return "res://" + "/".join(parts)

    @staticmethod
    def _flat_resource_path(kind: str, subfolder: str, name: str, extension: str) -> str:
        parts = [kind]
        parts.extend(part for part in subfolder.split("/") if part)
        parts.append(name + extension)
        return "res://" + "/".join(parts)

    def _legacy_id(self, resource: _ProjectResource) -> str:
        for key in ("id", "resourceId", "guid"):
            value = resource.raw_data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        return resource.source_path

    @classmethod
    def _stable_asset_id(cls, asset_type: str, name: str, used_ids: set[int]) -> int:
        asset_id = cls._fnv1a32(f"{asset_type}:{name}") & STATIC_ASSET_ID_MASK
        while asset_id in used_ids:
            asset_id = (asset_id + 1) & STATIC_ASSET_ID_MASK
        used_ids.add(asset_id)
        return asset_id

    @staticmethod
    def _fnv1a32(value: str) -> int:
        hash_value = 2166136261
        for char in value:
            hash_value = ((hash_value ^ ord(char)) * 16777619) & 0xFFFFFFFF
        return hash_value

    @staticmethod
    def _normalize_yyp_kind(yyp_path: str) -> str:
        kind = yyp_path.replace("\\", "/").split("/", 1)[0]
        return "included_files" if kind == "datafiles" else kind

    @staticmethod
    def _name_from_path(yyp_path: str) -> str:
        filename = os.path.basename(yyp_path.replace("\\", "/"))
        return os.path.splitext(filename)[0]

    @staticmethod
    def _reference_name(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        reference = cast(JsonDict, value)
        name = reference.get("name")
        if isinstance(name, str):
            return name
        return ""

    @staticmethod
    def _extract_tags(data: JsonDict) -> tuple[str, ...]:
        tags: set[str] = set()
        for key in ("tags", "resourceTags", "tagList"):
            value = data.get(key)
            if isinstance(value, list):
                for item in cast(list[object], value):
                    if isinstance(item, str) and item:
                        tags.add(item)
                    elif isinstance(item, dict):
                        item_data = cast(JsonDict, item)
                        tag_name = item_data.get("name")
                        if isinstance(tag_name, str) and tag_name:
                            tags.add(tag_name)
        return tuple(sorted(tags))

    @staticmethod
    def _metadata_float(value: object, default: float) -> float:
        if not isinstance(value, (str, int, float)):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _metadata_int(value: object, default: int) -> int:
        if not isinstance(value, (str, int, float)):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _metadata_string(value: object, default: str) -> str:
        return value if isinstance(value, str) and value else default


def render_asset_registry_script(
    entries: tuple[AssetRegistryEntry, ...],
    *,
    texture_groups: tuple[JsonDict, ...] = (),
    audio_groups: tuple[JsonDict, ...] = (),
) -> str:
    payload = [entry.to_godot_dict() for entry in entries]
    assets_literal = json.dumps(payload, indent=2, sort_keys=True)
    texture_groups_literal = json.dumps(list(texture_groups), indent=2, sort_keys=True)
    audio_groups_literal = json.dumps(list(audio_groups), indent=2, sort_keys=True)
    return (
        "extends RefCounted\n\n"
        "const FORMAT_VERSION = 1\n"
        f"const ASSETS = {assets_literal}\n\n"
        f"const TEXTURE_GROUPS = {texture_groups_literal}\n\n"
        f"const AUDIO_GROUPS = {audio_groups_literal}\n\n"
        "static func gml_asset_registry_entries():\n"
        "\treturn ASSETS\n\n"
        "static func gml_texture_group_registry_entries():\n"
        "\treturn TEXTURE_GROUPS\n\n"
        "static func gml_audio_group_registry_entries():\n"
        "\treturn AUDIO_GROUPS\n"
    )


__all__ = [
    "ASSET_REGISTRY_RELATIVE_PATH",
    "ASSET_REGISTRY_RESOURCE_PATH",
    "GROUP_COMPATIBILITY_REPORT_RELATIVE_PATH",
    "AssetRegistryConverter",
    "AssetRegistryEntry",
    "render_asset_registry_script",
]
