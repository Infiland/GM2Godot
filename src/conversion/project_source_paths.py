from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Iterable, cast

from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.events.base import EventMapping
from src.conversion.project_manifest import (
    ProjectResourceReference,
    load_gamemaker_project_manifest,
)
from src.conversion.type_defs import JsonDict, JsonList, StrPath


class ProjectSourcePathError(ValueError):
    """Raised when a YYP source path cannot be confined to its project root."""


@dataclass(frozen=True)
class ResolvedProjectSourcePath:
    """Contained filesystem path and normalized GameMaker project-relative path."""

    filesystem_path: str
    source_path: str


_GML_RESOURCE_KINDS = frozenset({"scripts", "objects", "rooms"})


def resolve_project_source_path(
    project_root: StrPath,
    source_path: str,
) -> ResolvedProjectSourcePath:
    """Resolve a YYP path without allowing absolute or project-escaping paths.

    GameMaker project files use forward-slash relative paths, including when the
    project was authored on Windows. Backslashes are accepted for compatibility,
    then the stored source path is normalized to GameMaker's portable form.
    """
    normalized_path = source_path.replace("\\", "/")
    if not normalized_path or "\0" in normalized_path:
        raise ProjectSourcePathError(
            f"YYP resource path is empty or invalid: {source_path!r}"
        )

    normalized_path = posixpath.normpath(normalized_path)
    if normalized_path in ("", "."):
        raise ProjectSourcePathError(
            f"YYP resource path does not name a project file: {source_path!r}"
        )
    drive, _tail = ntpath.splitdrive(normalized_path)
    if drive or normalized_path.startswith("/"):
        raise ProjectSourcePathError(
            "YYP resource path must be relative to the selected GameMaker "
            f"project root: {source_path!r}"
        )

    root_text: str = os.fspath(project_root)
    project_root_path: str = os.path.abspath(root_text)
    filesystem_path = os.path.normpath(
        os.path.join(project_root_path, *normalized_path.split("/"))
    )
    canonical_root = os.path.realpath(project_root_path)
    canonical_path = os.path.realpath(filesystem_path)
    try:
        common_path = os.path.commonpath((canonical_root, canonical_path))
    except ValueError as exc:
        raise ProjectSourcePathError(
            "YYP resource path is on a different filesystem root than the "
            f"selected GameMaker project: {source_path!r}"
        ) from exc

    if os.path.normcase(common_path) != os.path.normcase(canonical_root):
        raise ProjectSourcePathError(
            "YYP resource path escapes the selected GameMaker project root "
            f"through traversal or a symbolic link: {source_path!r}"
        )

    return ResolvedProjectSourcePath(
        filesystem_path=filesystem_path,
        source_path=normalized_path,
    )


def project_gml_source_paths(
    project_root: StrPath,
) -> tuple[ResolvedProjectSourcePath, ...]:
    """Return contained GML sources owned by YYP-referenced code resources.

    Resource order follows the YYP's ``resources`` array. Sources within an
    object or room follow their owning metadata order. Files elsewhere on disk,
    including deleted resource folders and stale event/creation-code files, are
    intentionally excluded.
    """
    root_text = os.fspath(project_root)
    manifest = load_gamemaker_project_manifest(root_text)
    if manifest.yyp_path is None or not manifest.raw_data:
        return ()

    sources: list[ResolvedProjectSourcePath] = []
    seen_paths: set[str] = set()
    for resource in manifest.resources:
        if resource.kind.casefold() not in _GML_RESOURCE_KINDS:
            continue
        try:
            resolved_resource = resolve_project_source_path(
                root_text,
                resource.path,
            )
        except ProjectSourcePathError:
            continue
        resource_data = _read_lenient_json_file(resolved_resource.filesystem_path)
        if resource_data is None:
            continue
        for candidate in _resource_gml_candidates(
            root_text,
            resource,
            resolved_resource,
            resource_data,
        ):
            try:
                resolved_source = resolve_project_source_path(root_text, candidate)
            except ProjectSourcePathError:
                continue
            if not resolved_source.source_path.casefold().endswith(".gml"):
                continue
            if not os.path.isfile(resolved_source.filesystem_path):
                continue
            path_key = os.path.normcase(os.path.realpath(resolved_source.filesystem_path))
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            sources.append(resolved_source)
    return tuple(sources)


def _read_lenient_json_file(path: str) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as source_file:
            source = source_file.read()
        value = json.loads(re.sub(r",\s*([}\]])", r"\1", source))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return cast(JsonDict, value) if isinstance(value, dict) else None


def _resource_gml_candidates(
    project_root: str,
    resource: ProjectResourceReference,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonDict,
) -> tuple[str, ...]:
    kind = resource.kind.casefold()
    if kind == "scripts":
        candidate = _script_gml_candidate(
            project_root,
            resource,
            resolved_resource,
            resource_data,
        )
        return (candidate,) if candidate else ()
    if kind == "objects":
        return _object_gml_candidates(
            project_root,
            resolved_resource,
            resource_data,
        )
    if kind == "rooms":
        return _room_gml_candidates(resolved_resource, resource_data)
    return ()


def _script_gml_candidate(
    project_root: str,
    resource: ProjectResourceReference,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonDict,
) -> str:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    names: list[str] = [resource.name]
    for key in ("%Name", "name"):
        value = resource_data.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    names.append(posixpath.splitext(posixpath.basename(resolved_resource.source_path))[0])
    for name in names:
        candidate = posixpath.join(resource_directory, f"{name}.gml")
        try:
            resolved_candidate = resolve_project_source_path(project_root, candidate)
        except ProjectSourcePathError:
            continue
        if os.path.isfile(resolved_candidate.filesystem_path):
            return candidate
    return ""


def _object_gml_candidates(
    project_root: str,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonDict,
) -> tuple[str, ...]:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    raw_events = resource_data.get("eventList")
    if not isinstance(raw_events, list):
        return ()
    candidates: list[str] = []
    for raw_event in cast(JsonList, raw_events):
        if not isinstance(raw_event, dict):
            continue
        event = cast(JsonDict, raw_event)
        mapping = map_input_event(event) if is_input_event(event) else map_event(event)
        if mapping is None:
            continue
        candidate = _first_existing_event_candidate(
            project_root,
            resource_directory,
            mapping,
        )
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


def _first_existing_event_candidate(
    project_root: str,
    resource_directory: str,
    mapping: EventMapping,
) -> str:
    for filename in _event_source_filenames(mapping):
        candidate = posixpath.join(resource_directory, filename)
        try:
            resolved_candidate = resolve_project_source_path(project_root, candidate)
        except ProjectSourcePathError:
            continue
        if os.path.isfile(resolved_candidate.filesystem_path):
            return candidate
    return ""


def _event_source_filenames(mapping: EventMapping) -> tuple[str, ...]:
    filenames: list[str] = []
    for filename in (mapping.gml_filename, *mapping.fallback_gml_filenames):
        if filename and filename not in filenames:
            filenames.append(filename)
    return tuple(filenames)


def _room_gml_candidates(
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonDict,
) -> tuple[str, ...]:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    candidates: list[str] = []
    creation_code_file = resource_data.get("creationCodeFile")
    if isinstance(creation_code_file, str) and creation_code_file:
        candidate = _resource_relative_source_path(
            resource_directory,
            creation_code_file,
        )
        if candidate:
            candidates.append(candidate)
    for instance in _iter_room_instances(resource_data.get("layers")):
        if not bool(instance.get("hasCreationCode", False)):
            continue
        instance_name = instance.get("%Name") or instance.get("name")
        if not isinstance(instance_name, str) or not instance_name:
            instance_name = "Instance"
        candidates.append(
            posixpath.join(
                resource_directory,
                f"InstanceCreationCode_{instance_name}.gml",
            )
        )
    return tuple(candidates)


def _resource_relative_source_path(
    resource_directory: str,
    source_path: str,
) -> str:
    normalized = source_path.replace("\\", "/")
    if normalized.startswith("${project_dir}/"):
        normalized = normalized[len("${project_dir}/"):]
    if normalized.startswith("rooms/"):
        return normalized
    return posixpath.join(resource_directory, normalized)


def _iter_room_instances(layers: object) -> Iterable[JsonDict]:
    if not isinstance(layers, list):
        return
    for raw_layer in cast(JsonList, layers):
        if not isinstance(raw_layer, dict):
            continue
        layer = cast(JsonDict, raw_layer)
        raw_instances = layer.get("instances")
        if isinstance(raw_instances, list):
            for raw_instance in cast(JsonList, raw_instances):
                if isinstance(raw_instance, dict):
                    yield cast(JsonDict, raw_instance)
        nested_layers = layer.get("layers") or layer.get("children")
        yield from _iter_room_instances(nested_layers)
