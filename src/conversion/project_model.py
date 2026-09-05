"""Canonical parsed GameMaker project records and their value queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.conversion.diagnostic_models import ProjectManifestDiagnostic, ProjectSourceLocation
from src.conversion.json_values import JsonObject, JsonValue


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True)
class ProjectResourceReference:
    uuid: str
    name: str
    path: str
    kind: str
    resource_type: str
    order: int
    tags: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None


@dataclass(frozen=True)
class ProjectConfigOverride:
    configuration: str
    field_path: str
    value: JsonValue
    source: ProjectSourceLocation | None = None


@dataclass(frozen=True)
class ProjectConfiguration:
    name: str
    parent: str = ""
    overrides: tuple[ProjectConfigOverride, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonObject = field(default_factory=_empty_json_object)


@dataclass(frozen=True)
class ProjectOption:
    platform: str
    key: str
    value: JsonValue
    source: ProjectSourceLocation | None = None


@dataclass(frozen=True)
class ProjectTextureGroup:
    name: str
    parent: str = ""
    is_dynamic: bool = False
    dynamic_path: str = ""
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonObject = field(default_factory=_empty_json_object)


@dataclass(frozen=True)
class ProjectAudioGroup:
    name: str
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonObject = field(default_factory=_empty_json_object)

    @property
    def initial_loaded(self) -> bool:
        if self.name in {"", "audiogroup_default"}:
            return True
        for key in ("loaded", "preload", "loadOnStartup"):
            value = self.raw_data.get(key)
            if isinstance(value, bool):
                return value
        return False

    @property
    def gain(self) -> float:
        value = self.raw_data.get("gain")
        if not isinstance(value, (str, int, float)):
            return 1.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0


@dataclass(frozen=True)
class ProjectIncludedFile:
    name: str
    path: str
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonObject = field(default_factory=_empty_json_object)


@dataclass(frozen=True)
class ProjectOptionsMetadata:
    platform: str
    source_path: str
    source: str
    raw_data: JsonObject
    options: tuple[ProjectOption, ...]


@dataclass(frozen=True)
class GameMakerProjectManifest:
    project_name: str
    yyp_path: str | None
    resource_type: str = ""
    resource_version: str = ""
    resources: tuple[ProjectResourceReference, ...] = ()
    configurations: tuple[ProjectConfiguration, ...] = ()
    options: tuple[ProjectOption, ...] = ()
    texture_groups: tuple[ProjectTextureGroup, ...] = ()
    audio_groups: tuple[ProjectAudioGroup, ...] = ()
    included_files: tuple[ProjectIncludedFile, ...] = ()
    diagnostics: tuple[ProjectManifestDiagnostic, ...] = ()
    raw_data: JsonObject = field(default_factory=_empty_json_object)
    ide_version: str = ""
    option_files: tuple[ProjectOptionsMetadata, ...] = field(default=(), kw_only=True, compare=False, repr=False)

    @property
    def audio_groups_state(self) -> Literal["missing", "malformed", "unnamed", "available"]:
        missing = object()
        raw_groups = self.raw_data.get("AudioGroups", missing)
        if raw_groups is missing:
            return "missing"
        if not isinstance(raw_groups, (list, dict)):
            return "malformed"
        if raw_groups and not self.audio_group_names():
            return "unnamed"
        return "available"

    def get_option(self, key: str, platform: str | None = None) -> ProjectOption | None:
        folded_key = key.casefold()
        folded_platform = platform.casefold() if platform is not None else None
        for option in reversed(self.options):
            if option.key.casefold() != folded_key:
                continue
            if folded_platform is None or option.platform.casefold() == folded_platform:
                return option
        return None

    def options_for_platform(self, platform: str) -> dict[str, ProjectOption]:
        selected: dict[str, ProjectOption] = {}
        for option in self.options:
            if option.platform.casefold() in ("main", platform.casefold()):
                selected[option.key] = option
        return selected

    def audio_group_names(self) -> list[str]:
        return [group.name for group in self.audio_groups if group.name]

    def find_resources(
        self,
        *,
        uuid: str | None = None,
        name: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        resource_type: str | None = None,
    ) -> tuple[ProjectResourceReference, ...]:
        normalized_path = normalize_project_manifest_path(path) if path else None
        matches: list[ProjectResourceReference] = []
        for resource in self.resources:
            if uuid is not None and resource.uuid != uuid:
                continue
            if name is not None and resource.name.casefold() != name.casefold():
                continue
            if normalized_path is not None and normalize_project_manifest_path(resource.path) != normalized_path:
                continue
            if kind is not None and resource.kind.casefold() != kind.casefold():
                continue
            if resource_type is not None and resource.resource_type.casefold() != resource_type.casefold():
                continue
            matches.append(resource)
        return tuple(matches)


def normalize_project_manifest_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").strip()
