from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Mapping, cast

from src.conversion.type_defs import JsonDict, JsonList


ProjectManifestSeverity = Literal["info", "warning", "error"]

_RESOURCE_TYPE_KIND = {
    "GMAnimationCurve": "animcurves",
    "GMAudioGroup": "audiogroups",
    "GMExtension": "extensions",
    "GMFont": "fonts",
    "GMIncludedFile": "datafiles",
    "GMNotes": "notes",
    "GMObject": "objects",
    "GMParticleSystem": "particlesystems",
    "GMPath": "paths",
    "GMRoom": "rooms",
    "GMScript": "scripts",
    "GMSequence": "sequences",
    "GMShader": "shaders",
    "GMSound": "sounds",
    "GMSprite": "sprites",
    "GMTileSet": "tilesets",
    "GMTimeline": "timelines",
}

_KNOWN_PROJECT_FIELDS = frozenset({
    "$GMProject",
    "%Name",
    "AudioGroups",
    "ConfigValues",
    "Configs",
    "Folders",
    "IncludedFiles",
    "MetaData",
    "RoomOrderNodes",
    "TextureGroups",
    "configs",
    "copyToTargets",
    "isDnDProject",
    "mvc",
    "name",
    "parentProject",
    "projectId",
    "resources",
    "resourceType",
    "resourceVersion",
    "tutorialPath",
})


def _empty_json_dict() -> JsonDict:
    return cast(JsonDict, {})


@dataclass(frozen=True)
class ProjectSourceLocation:
    path: str
    line: int
    field_path: str = ""


@dataclass(frozen=True)
class ProjectManifestDiagnostic:
    severity: ProjectManifestSeverity
    code: str
    message: str
    source: ProjectSourceLocation | None = None


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
    value: object
    source: ProjectSourceLocation | None = None


@dataclass(frozen=True)
class ProjectConfiguration:
    name: str
    parent: str = ""
    overrides: tuple[ProjectConfigOverride, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonDict = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class ProjectOption:
    platform: str
    key: str
    value: object
    source: ProjectSourceLocation | None = None


@dataclass(frozen=True)
class ProjectTextureGroup:
    name: str
    parent: str = ""
    is_dynamic: bool = False
    dynamic_path: str = ""
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonDict = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class ProjectAudioGroup:
    name: str
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonDict = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class ProjectIncludedFile:
    name: str
    path: str
    targets: tuple[str, ...] = ()
    source: ProjectSourceLocation | None = None
    raw_data: JsonDict = field(default_factory=_empty_json_dict)


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
    raw_data: JsonDict = field(default_factory=_empty_json_dict)
    ide_version: str = ""

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
        normalized_path = _normalize_project_path(path) if path else None
        matches: list[ProjectResourceReference] = []
        for resource in self.resources:
            if uuid is not None and resource.uuid != uuid:
                continue
            if name is not None and resource.name.casefold() != name.casefold():
                continue
            if normalized_path is not None and _normalize_project_path(resource.path) != normalized_path:
                continue
            if kind is not None and resource.kind.casefold() != kind.casefold():
                continue
            if resource_type is not None and resource.resource_type.casefold() != resource_type.casefold():
                continue
            matches.append(resource)
        return tuple(matches)


def load_gamemaker_project_manifest(
    gm_project_path: str,
    *,
    target_platform: str | None = None,
) -> GameMakerProjectManifest:
    yyp_path = _find_yyp_path(gm_project_path)
    diagnostics: list[ProjectManifestDiagnostic] = []
    if yyp_path is None:
        diagnostics.append(
            ProjectManifestDiagnostic(
                severity="warning",
                code="GM2GD-PROJECT-YYP-MISSING",
                message="No GameMaker project .yyp found; project manifest metadata is unavailable.",
            )
        )
        return GameMakerProjectManifest(project_name="", yyp_path=None, diagnostics=tuple(diagnostics))

    raw_data, raw_source = _read_lenient_json_file(yyp_path)
    if raw_data is None:
        diagnostics.append(
            ProjectManifestDiagnostic(
                severity="warning",
                code="GM2GD-PROJECT-YYP-MALFORMED",
                message=f"Could not parse GameMaker project .yyp: {yyp_path}",
                source=ProjectSourceLocation(yyp_path, 1),
            )
        )
        return GameMakerProjectManifest(project_name="", yyp_path=yyp_path, diagnostics=tuple(diagnostics))

    resources = _parse_resources(raw_data, yyp_path, raw_source)
    configurations = _parse_configurations(raw_data, yyp_path, raw_source)
    options = _parse_project_options(gm_project_path)
    texture_groups = _parse_texture_groups(raw_data, yyp_path, raw_source)
    audio_groups = _parse_audio_groups(raw_data, yyp_path, raw_source)
    included_files = _parse_included_files(raw_data, yyp_path, raw_source)
    diagnostics.extend(_unknown_project_field_diagnostics(raw_data, yyp_path, raw_source))
    diagnostics.extend(_resource_conflict_diagnostics(resources))
    if target_platform is not None:
        diagnostics.extend(_missing_target_option_diagnostics(options, target_platform))

    return GameMakerProjectManifest(
        project_name=_string_value(raw_data.get("%Name")) or _string_value(raw_data.get("name")),
        yyp_path=yyp_path,
        resource_type=_string_value(raw_data.get("resourceType")),
        resource_version=_string_value(raw_data.get("resourceVersion")),
        ide_version=_project_ide_version(raw_data),
        resources=resources,
        configurations=configurations,
        options=options,
        texture_groups=texture_groups,
        audio_groups=audio_groups,
        included_files=included_files,
        diagnostics=tuple(diagnostics),
        raw_data=raw_data,
    )


def unsupported_project_option_diagnostics(
    manifest: GameMakerProjectManifest,
    *,
    target_platform: str,
    supported_keys: Iterable[str],
) -> tuple[ProjectManifestDiagnostic, ...]:
    supported = {key.casefold() for key in supported_keys}
    diagnostics: list[ProjectManifestDiagnostic] = []
    for option in manifest.options_for_platform(target_platform).values():
        if not option.key.startswith("option_") or option.key.casefold() in supported:
            continue
        diagnostics.append(
            ProjectManifestDiagnostic(
                severity="info",
                code="GM2GD-PROJECT-OPTION-UNSUPPORTED",
                message=(
                    "Unsupported GameMaker project option "
                    f"{option.key!r} for target {option.platform!r}; no Godot project setting is emitted."
                ),
                source=option.source,
            )
        )
    return tuple(diagnostics)


def _find_yyp_path(gm_project_path: str) -> str | None:
    try:
        yyp_files = sorted(name for name in os.listdir(gm_project_path) if name.endswith(".yyp"))
    except OSError:
        return None
    if not yyp_files:
        return None
    return os.path.join(gm_project_path, yyp_files[0])


def _read_lenient_json_file(path: str) -> tuple[JsonDict | None, str]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", source))
        return (cast(JsonDict, data), source) if isinstance(data, dict) else (None, source)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None, ""


def _parse_resources(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectResourceReference, ...]:
    resources: list[ProjectResourceReference] = []
    raw_resources = yyp_data.get("resources")
    if not isinstance(raw_resources, list):
        return ()
    for order, raw_entry in enumerate(cast(JsonList, raw_resources)):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(JsonDict, raw_entry)
        reference = _resource_reference_from_entry(entry, order, yyp_path, raw_source)
        if reference is not None:
            resources.append(reference)
    return tuple(resources)


def _resource_reference_from_entry(
    entry: JsonDict,
    order: int,
    yyp_path: str,
    raw_source: str,
) -> ProjectResourceReference | None:
    data = entry
    uuid = _string_value(entry.get("id")) or _string_value(entry.get("Key"))
    value = entry.get("Value")
    if isinstance(value, dict):
        data = cast(JsonDict, value)
        uuid = uuid or _string_value(data.get("id"))
    nested_id = data.get("id")
    if isinstance(nested_id, dict):
        nested = cast(JsonDict, nested_id)
        uuid = (
            _string_value(nested.get("id"))
            or _string_value(nested.get("uuid"))
            or uuid
        )
        name = _string_value(nested.get("name"))
        path = _string_value(nested.get("path"))
    else:
        name = _string_value(data.get("name")) or _string_value(data.get("%Name"))
        path = (
            _string_value(data.get("path"))
            or _string_value(data.get("resourcePath"))
            or _string_value(data.get("resource_path"))
        )
    if not path:
        return None

    resource_type = _string_value(data.get("resourceType")) or _resource_type_from_path(path)
    kind = _kind_from_path(path) or _RESOURCE_TYPE_KIND.get(resource_type, "")
    name = name or _name_from_path(path)
    if not name or not kind:
        return None

    order_value = _int_value(data.get("order"), order)
    return ProjectResourceReference(
        uuid=uuid,
        name=name,
        path=_normalize_project_path(path),
        kind=kind,
        resource_type=resource_type,
        order=order_value,
        tags=_string_tuple(data.get("tags")),
        source=ProjectSourceLocation(yyp_path, _line_for(raw_source, path), f"resources[{order}]"),
    )


def _parse_configurations(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectConfiguration, ...]:
    configs: dict[str, ProjectConfiguration] = {}
    roots = yyp_data.get("configs")
    if roots is None:
        roots = yyp_data.get("Configs")
    for node in _iter_config_nodes(roots):
        name = _string_value(node.get("name")) or _string_value(node.get("%Name"))
        if not name:
            continue
        parent = _config_parent_name(node)
        overrides = _config_overrides_from_node(name, node, yyp_path, raw_source)
        configs[name] = ProjectConfiguration(
            name=name,
            parent=parent,
            overrides=overrides,
            source=ProjectSourceLocation(yyp_path, _line_for(raw_source, name), f"configs.{name}"),
            raw_data=node,
        )

    config_values = yyp_data.get("ConfigValues")
    if isinstance(config_values, dict):
        for name, raw_overrides in cast(JsonDict, config_values).items():
            config_name = str(name)
            overrides = _config_overrides_from_value(
                config_name,
                raw_overrides,
                yyp_path,
                raw_source,
                "ConfigValues",
            )
            existing = configs.get(config_name)
            if existing is None:
                configs[config_name] = ProjectConfiguration(
                    name=config_name,
                    overrides=overrides,
                    source=ProjectSourceLocation(yyp_path, _line_for(raw_source, config_name), f"ConfigValues.{config_name}"),
                )
            else:
                configs[config_name] = ProjectConfiguration(
                    name=existing.name,
                    parent=existing.parent,
                    overrides=existing.overrides + overrides,
                    source=existing.source,
                    raw_data=existing.raw_data,
                )
    return tuple(configs[name] for name in sorted(configs))


def _iter_config_nodes(raw_configs: object) -> Iterable[JsonDict]:
    if isinstance(raw_configs, dict):
        config = cast(JsonDict, raw_configs)
        if _string_value(config.get("name")) or _string_value(config.get("%Name")):
            yield config
        for key in ("children", "configs", "Configs"):
            for child in _iter_config_nodes(config.get(key)):
                yield child
    elif isinstance(raw_configs, list):
        for item in cast(JsonList, raw_configs):
            if isinstance(item, dict):
                yield from _iter_config_nodes(cast(JsonDict, item))


def _config_parent_name(node: JsonDict) -> str:
    raw_parent = node.get("parent") or node.get("parentConfig")
    if isinstance(raw_parent, str):
        return raw_parent
    if isinstance(raw_parent, dict):
        parent = cast(JsonDict, raw_parent)
        return _string_value(parent.get("name")) or _string_value(parent.get("%Name"))
    return ""


def _config_overrides_from_node(
    configuration: str,
    node: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectConfigOverride, ...]:
    overrides: list[ProjectConfigOverride] = []
    for key in ("options", "values", "overrides", "macros", "resources", "textureGroups", "audioGroups", "includedFiles"):
        if key in node:
            overrides.extend(
                _config_overrides_from_value(
                    configuration,
                    node[key],
                    yyp_path,
                    raw_source,
                    key,
                )
            )
    return tuple(overrides)


def _config_overrides_from_value(
    configuration: str,
    value: object,
    yyp_path: str,
    raw_source: str,
    field_path: str,
) -> tuple[ProjectConfigOverride, ...]:
    if isinstance(value, dict):
        overrides: list[ProjectConfigOverride] = []
        for key, nested_value in cast(JsonDict, value).items():
            overrides.extend(
                _config_overrides_from_value(
                    configuration,
                    nested_value,
                    yyp_path,
                    raw_source,
                    f"{field_path}.{key}",
                )
            )
        return tuple(overrides)
    return (
        ProjectConfigOverride(
            configuration=configuration,
            field_path=field_path,
            value=value,
            source=ProjectSourceLocation(yyp_path, _line_for(raw_source, field_path.split(".")[-1]), field_path),
        ),
    )


def _parse_project_options(gm_project_path: str) -> tuple[ProjectOption, ...]:
    options_root = os.path.join(gm_project_path, "options")
    if not os.path.isdir(options_root):
        return ()
    options: list[ProjectOption] = []
    for root, _dirs, files in os.walk(options_root):
        for filename in sorted(files):
            if not filename.endswith(".yy"):
                continue
            path = os.path.join(root, filename)
            data, source = _read_lenient_json_file(path)
            if data is None:
                continue
            platform = _option_platform_from_path(options_root, path)
            for key, value in data.items():
                if key.startswith("option_"):
                    options.append(
                        ProjectOption(
                            platform=platform,
                            key=key,
                            value=value,
                            source=ProjectSourceLocation(path, _line_for(source, key), key),
                        )
                    )
    return tuple(options)


def _option_platform_from_path(options_root: str, path: str) -> str:
    relative = os.path.relpath(path, options_root)
    parts = relative.split(os.sep)
    if len(parts) > 1 and parts[0]:
        return parts[0]
    filename = os.path.splitext(os.path.basename(path))[0]
    if filename.startswith("options_"):
        return filename[len("options_"):]
    return "main"


def _parse_texture_groups(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectTextureGroup, ...]:
    raw_groups = yyp_data.get("TextureGroups") or yyp_data.get("textureGroups")
    groups: list[ProjectTextureGroup] = []
    for index, item in enumerate(_iter_dict_items(raw_groups)):
        name = _entry_name(item)
        if not name:
            continue
        groups.append(
            ProjectTextureGroup(
                name=name,
                parent=_entry_reference_name(item.get("parent") or item.get("parentGroup")),
                is_dynamic=bool(item.get("isDynamic") or item.get("dynamic") or item.get("dynamicTextureGroup")),
                dynamic_path=_string_value(item.get("dynamicPath") or item.get("path")),
                targets=_targets_from_mapping(item),
                source=ProjectSourceLocation(yyp_path, _line_for(raw_source, name), f"TextureGroups[{index}]"),
                raw_data=item,
            )
        )
    return tuple(groups)


def _parse_audio_groups(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectAudioGroup, ...]:
    groups: list[ProjectAudioGroup] = []
    for index, item in enumerate(_iter_dict_items(yyp_data.get("AudioGroups"))):
        name = _entry_name(item)
        if not name:
            continue
        groups.append(
            ProjectAudioGroup(
                name=name,
                targets=_targets_from_mapping(item),
                source=ProjectSourceLocation(yyp_path, _line_for(raw_source, name), f"AudioGroups[{index}]"),
                raw_data=item,
            )
        )
    return tuple(groups)


def _parse_included_files(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectIncludedFile, ...]:
    files: list[ProjectIncludedFile] = []
    raw_files = yyp_data.get("IncludedFiles") or yyp_data.get("includedFiles")
    for index, item in enumerate(_iter_dict_items(raw_files)):
        path = _string_value(item.get("path") or item.get("filePath") or item.get("filename"))
        name = _entry_name(item) or os.path.basename(path)
        if not name and not path:
            continue
        files.append(
            ProjectIncludedFile(
                name=name,
                path=_normalize_project_path(path),
                targets=_targets_from_mapping(item),
                source=ProjectSourceLocation(yyp_path, _line_for(raw_source, name or path), f"IncludedFiles[{index}]"),
                raw_data=item,
            )
        )
    return tuple(files)


def _unknown_project_field_diagnostics(
    yyp_data: JsonDict,
    yyp_path: str,
    raw_source: str,
) -> tuple[ProjectManifestDiagnostic, ...]:
    diagnostics: list[ProjectManifestDiagnostic] = []
    for key in sorted(yyp_data):
        if key in _KNOWN_PROJECT_FIELDS or key.startswith("$"):
            continue
        diagnostics.append(
            ProjectManifestDiagnostic(
                severity="warning",
                code="GM2GD-PROJECT-UNKNOWN-FIELD",
                message=f"Unknown GameMaker project manifest field {key!r}; preserving raw value only.",
                source=ProjectSourceLocation(yyp_path, _line_for(raw_source, key), key),
            )
        )
    return tuple(diagnostics)


def _resource_conflict_diagnostics(
    resources: tuple[ProjectResourceReference, ...],
) -> tuple[ProjectManifestDiagnostic, ...]:
    diagnostics: list[ProjectManifestDiagnostic] = []
    diagnostics.extend(_duplicate_resource_diagnostics(resources, "uuid", lambda resource: resource.uuid))
    diagnostics.extend(
        _duplicate_resource_diagnostics(
            resources,
            "name",
            lambda resource: f"{resource.kind}:{resource.name.casefold()}",
        )
    )
    diagnostics.extend(
        _duplicate_resource_diagnostics(
            resources,
            "path",
            lambda resource: _normalize_project_path(resource.path).casefold(),
        )
    )
    return tuple(diagnostics)


def _duplicate_resource_diagnostics(
    resources: tuple[ProjectResourceReference, ...],
    label: str,
    key_fn: Callable[[ProjectResourceReference], str],
) -> tuple[ProjectManifestDiagnostic, ...]:
    seen: dict[str, ProjectResourceReference] = {}
    diagnostics: list[ProjectManifestDiagnostic] = []
    for resource in resources:
        key = key_fn(resource)
        if not key:
            continue
        previous = seen.get(key)
        if previous is None:
            seen[key] = resource
            continue
        diagnostics.append(
            ProjectManifestDiagnostic(
                severity="warning",
                code="GM2GD-PROJECT-RESOURCE-CONFLICT",
                message=(
                    f"Duplicate GameMaker resource {label} {key!r} for "
                    f"{previous.kind}/{previous.name} and {resource.kind}/{resource.name}."
                ),
                source=resource.source,
            )
        )
    return tuple(diagnostics)


def _missing_target_option_diagnostics(
    options: tuple[ProjectOption, ...],
    target_platform: str,
) -> tuple[ProjectManifestDiagnostic, ...]:
    if any(option.platform.casefold() == target_platform.casefold() for option in options):
        return ()
    return (
        ProjectManifestDiagnostic(
            severity="warning",
            code="GM2GD-PROJECT-TARGET-OPTIONS-MISSING",
            message=f"No GameMaker options file found for target platform {target_platform!r}.",
        ),
    )


def _iter_dict_items(value: object) -> Iterable[JsonDict]:
    if isinstance(value, list):
        for item in cast(JsonList, value):
            if isinstance(item, dict):
                yield cast(JsonDict, item)
    elif isinstance(value, dict):
        for item in cast(JsonDict, value).values():
            if isinstance(item, dict):
                yield cast(JsonDict, item)


def _entry_name(data: JsonDict) -> str:
    return _string_value(data.get("%Name")) or _string_value(data.get("name"))


def _entry_reference_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _entry_name(cast(JsonDict, value))
    return ""


def _targets_from_mapping(data: Mapping[str, object]) -> tuple[str, ...]:
    raw_targets = data.get("targets") or data.get("copyToTargets") or data.get("platforms")
    if isinstance(raw_targets, list):
        targets: list[str] = []
        for target in cast(JsonList, raw_targets):
            target_text = str(target)
            if target_text:
                targets.append(target_text)
        return tuple(targets)
    if isinstance(raw_targets, dict):
        targets: list[str] = []
        for key, value in cast(Mapping[str, object], raw_targets).items():
            if bool(value):
                targets.append(str(key))
        return tuple(sorted(targets))
    targets = []
    for key, value in data.items():
        if key.startswith("copyTo") and bool(value):
            targets.append(key[len("copyTo"):].casefold())
    return tuple(sorted(targets))


def _resource_type_from_path(path: str) -> str:
    kind = _kind_from_path(path)
    for resource_type, mapped_kind in _RESOURCE_TYPE_KIND.items():
        if mapped_kind == kind:
            return resource_type
    return ""


def _kind_from_path(path: str) -> str:
    normalized = _normalize_project_path(path)
    if "/" not in normalized:
        return ""
    return normalized.split("/", 1)[0]


def _name_from_path(path: str) -> str:
    filename = os.path.basename(_normalize_project_path(path))
    return os.path.splitext(filename)[0]


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _project_ide_version(yyp_data: JsonDict) -> str:
    metadata = yyp_data.get("MetaData")
    if not isinstance(metadata, dict):
        return ""
    return _string_value(cast(JsonDict, metadata).get("IDEVersion"))


def _int_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in cast(JsonList, value) if str(item))


def _normalize_project_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").strip()


def _line_for(source: str, needle: str) -> int:
    if not needle:
        return 1
    index = source.find(needle)
    if index == -1:
        return 1
    return source.count("\n", 0, index) + 1
