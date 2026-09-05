"""Discover contained GML files owned by manifest resources and their metadata."""

from __future__ import annotations

import json
import os
import posixpath
from typing import Iterable

from src.conversion.event_mapping import is_input_event, map_event, map_input_event
from src.conversion.events.base import EventMapping
from src.conversion.gamemaker_json import read_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.project_manifest import (
    ProjectResourceReference,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    is_safe_project_source_component,
    resolve_project_sidecar_source_path,
    resolve_project_source_path,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import StrPath

_GML_RESOURCE_KINDS = frozenset({"scripts", "objects", "rooms"})


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
            validate_project_resource_source_path(
                resolved_resource,
                resource.kind,
            )
        except ProjectSourcePathError:
            continue
        try:
            resource_data = read_gamemaker_json(resolved_resource.filesystem_path).value
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(resource_data, dict):
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


def _resource_gml_candidates(
    project_root: str,
    resource: ProjectResourceReference,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonObject,
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
        return _room_gml_candidates(
            project_root,
            resolved_resource,
            resource_data,
        )
    return ()


def _script_gml_candidate(
    project_root: str,
    resource: ProjectResourceReference,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonObject,
) -> str:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    names: list[str] = [resource.name]
    for key in ("%Name", "name"):
        value = resource_data.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    names.append(posixpath.splitext(posixpath.basename(resolved_resource.source_path))[0])
    for name in names:
        if not is_safe_project_source_component(name):
            continue
        try:
            resolved_candidate = resolve_project_sidecar_source_path(
                project_root,
                resolved_resource.source_path,
                f"{name}.gml",
            )
        except ProjectSourcePathError:
            continue
        if (
            posixpath.dirname(resolved_candidate.source_path) == resource_directory
            and os.path.isfile(resolved_candidate.filesystem_path)
        ):
            return resolved_candidate.source_path
    return ""


def _object_gml_candidates(
    project_root: str,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonObject,
) -> tuple[str, ...]:
    raw_events = resource_data.get("eventList")
    if not isinstance(raw_events, list):
        return ()
    candidates: list[str] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        mapping = map_input_event(event) if is_input_event(event) else map_event(event)
        if mapping is None:
            continue
        candidate = _first_existing_event_candidate(
            project_root,
            resolved_resource.source_path,
            mapping,
        )
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


def _first_existing_event_candidate(
    project_root: str,
    owner_source_path: str,
    mapping: EventMapping,
) -> str:
    resource_directory = posixpath.dirname(owner_source_path)
    for filename in _event_source_filenames(mapping):
        if not is_safe_project_source_component(filename):
            continue
        try:
            resolved_candidate = resolve_project_sidecar_source_path(
                project_root,
                owner_source_path,
                filename,
            )
        except ProjectSourcePathError:
            continue
        if (
            posixpath.dirname(resolved_candidate.source_path) == resource_directory
            and os.path.isfile(resolved_candidate.filesystem_path)
        ):
            return resolved_candidate.source_path
    return ""


def _event_source_filenames(mapping: EventMapping) -> tuple[str, ...]:
    filenames: list[str] = []
    for filename in (mapping.gml_filename, *mapping.fallback_gml_filenames):
        if filename and filename not in filenames:
            filenames.append(filename)
    return tuple(filenames)


def _room_gml_candidates(
    project_root: str,
    resolved_resource: ResolvedProjectSourcePath,
    resource_data: JsonObject,
) -> tuple[str, ...]:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    candidates: list[str] = []
    creation_code_file = resource_data.get("creationCodeFile")
    if isinstance(creation_code_file, str) and creation_code_file:
        try:
            resolved_creation_code = resolve_project_sidecar_source_path(
                project_root,
                resolved_resource.source_path,
                creation_code_file,
            )
        except ProjectSourcePathError:
            pass
        else:
            candidates.append(resolved_creation_code.source_path)
    for instance in _iter_room_instances(resource_data.get("layers")):
        if not bool(instance.get("hasCreationCode", False)):
            continue
        instance_name = instance.get("%Name") or instance.get("name")
        if not isinstance(instance_name, str) or not instance_name:
            instance_name = "Instance"
        if not is_safe_project_source_component(instance_name):
            continue
        try:
            resolved_instance_code = resolve_project_sidecar_source_path(
                project_root,
                resolved_resource.source_path,
                f"InstanceCreationCode_{instance_name}.gml",
            )
        except ProjectSourcePathError:
            continue
        if posixpath.dirname(resolved_instance_code.source_path) == resource_directory:
            candidates.append(resolved_instance_code.source_path)
    return tuple(candidates)


def _iter_room_instances(layers: JsonValue) -> Iterable[JsonObject]:
    if not isinstance(layers, list):
        return
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        raw_instances = layer.get("instances")
        if isinstance(raw_instances, list):
            for raw_instance in raw_instances:
                if isinstance(raw_instance, dict):
                    yield raw_instance
        nested_layers = layer.get("layers") or layer.get("children")
        yield from _iter_room_instances(nested_layers)
