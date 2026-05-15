from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import ClassVar, Iterable, cast

from src.conversion.base_converter import BaseConverter
from src.conversion.type_defs import (
    ConversionRunning,
    JsonDict,
    LogCallback,
    ProgressCallback,
    StrPath,
)
from src.conversion.path_registry import write_path_registry

ASSET_REGISTRY_RELATIVE_PATH = os.path.join("gm2godot", "gml_asset_registry.gd")
ASSET_REGISTRY_RESOURCE_PATH = "res://gm2godot/gml_asset_registry.gd"
STATIC_ASSET_ID_MASK = 0x3FFFFFFF


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
        "shaders": "shader",
        "tilesets": "tileset",
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
        "shaders": "Shader",
        "tilesets": "Tile Set",
        "timelines": "Timeline",
        "sequences": "Sequence",
        "included_files": "Included File",
    }
    STATIC_RESOURCE_EXTENSIONS: ClassVar[dict[str, str]] = {
        "sprites": ".tscn",
        "objects": ".tscn",
        "rooms": ".tscn",
        "tilesets": ".tres",
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
        registry_path = os.path.join(self.godot_project_path, ASSET_REGISTRY_RELATIVE_PATH)
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)

        with open(registry_path, "w", encoding="utf-8") as f:
            f.write(render_asset_registry_script(entries))
        write_path_registry(self.gm_project_path, self.godot_project_path, entries)

        self.log_callback(
            "Generated GameMaker asset registry: {path} ({count} assets)".format(
                path=ASSET_REGISTRY_RELATIVE_PATH.replace(os.sep, "/"),
                count=len(entries),
            )
        )
        return registry_path

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


def render_asset_registry_script(entries: tuple[AssetRegistryEntry, ...]) -> str:
    payload = [entry.to_godot_dict() for entry in entries]
    assets_literal = json.dumps(payload, indent=2, sort_keys=True)
    return (
        "extends RefCounted\n\n"
        "const FORMAT_VERSION = 1\n"
        f"const ASSETS = {assets_literal}\n\n"
        "static func gml_asset_registry_entries():\n"
        "\treturn ASSETS\n"
    )


__all__ = [
    "ASSET_REGISTRY_RELATIVE_PATH",
    "ASSET_REGISTRY_RESOURCE_PATH",
    "AssetRegistryConverter",
    "AssetRegistryEntry",
    "render_asset_registry_script",
]
