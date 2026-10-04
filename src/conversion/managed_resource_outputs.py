"""Logical ownership rules for generated resource outputs."""

from __future__ import annotations

import copy
import posixpath
from dataclasses import dataclass
from typing import Iterable, Mapping, cast

from src.conversion.generation_inventory import normalize_generation_inventory_path
from src.conversion.json_values import JsonObject

STALE_INVALIDATION_RESOURCE_KINDS = frozenset(
    {
        "objects",
        "particles",
        "particlesystems",
        "rooms",
        "sequences",
        "shaders",
        "sprites",
        "timelines",
    }
)
STALE_INVALIDATION_CONVERTER_KEYS = frozenset(
    {"asset_registry", "objects", "rooms", "shaders", "sprites"}
)


@dataclass(frozen=True, slots=True)
class ManagedResourceOutputs:
    """Exact files and private subtrees owned by one logical source resource."""

    required_paths: tuple[str, ...] = ()
    owned_paths: tuple[str, ...] = ()
    owned_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = _canonical_paths(self.required_paths)
        owned = _canonical_paths(self.owned_paths)
        prefixes = tuple(
            sorted(
                {
                    _canonical_prefix(prefix)
                    for prefix in self.owned_prefixes
                }
            )
        )
        owned_set = set(owned)
        for path in required:
            if path in owned_set or any(
                path.startswith(prefix)
                for prefix in prefixes
            ):
                continue
            raise ValueError(
                "Required managed-resource outputs must be owned by the resource."
            )
        object.__setattr__(self, "required_paths", required)
        object.__setattr__(self, "owned_paths", owned)
        object.__setattr__(self, "owned_prefixes", prefixes)

    def owns(self, relative_path: str) -> bool:
        """Return whether this logical resource owns one inventory path."""

        normalized = normalize_generation_inventory_path(relative_path)
        return normalized in self.owned_paths or any(
            normalized.startswith(prefix) for prefix in self.owned_prefixes
        )

    def required_outputs_available(self, available_paths: Iterable[str]) -> bool:
        available = {
            normalize_generation_inventory_path(path)
            for path in available_paths
        }
        return all(path in available for path in self.required_paths)


def managed_resource_outputs(
    kind: str,
    godot_path: str,
    metadata: Mapping[str, object] | None = None,
) -> ManagedResourceOutputs:
    """Define converter-owned output paths for one logical managed resource."""

    return _managed_output_paths(
        kind,
        godot_path,
        timeline_action_script_paths(metadata) if kind == "timelines" else (),
    )


def managed_gamemaker_resource_outputs(
    kind: str,
    godot_path: str,
    metadata: JsonObject | None = None,
) -> ManagedResourceOutputs:
    """Plan outputs from recursively typed GameMaker descriptors."""
    return _managed_output_paths(
        kind,
        godot_path,
        timeline_json_action_script_paths(metadata) if kind == "timelines" else (),
    )


def _managed_output_paths(
    kind: str,
    godot_path: str,
    action_paths: tuple[str, ...],
) -> ManagedResourceOutputs:
    if kind not in STALE_INVALIDATION_RESOURCE_KINDS:
        return ManagedResourceOutputs()
    if kind == "timelines":
        return ManagedResourceOutputs(
            required_paths=action_paths,
            owned_paths=action_paths,
        )

    primary_path = _resource_relative_path(godot_path)
    if kind == "shaders":
        return ManagedResourceOutputs(
            required_paths=(primary_path,),
            owned_paths=(primary_path,),
        )

    resource_directory = posixpath.dirname(primary_path)
    if not resource_directory:
        raise ValueError(
            f"Managed {kind} output has no private resource directory: "
            f"{godot_path!r}"
        )
    required_paths = (primary_path,)
    if kind == "objects":
        required_paths = (
            primary_path,
            posixpath.splitext(primary_path)[0] + ".gd",
        )
    return ManagedResourceOutputs(
        required_paths=required_paths,
        owned_prefixes=(resource_directory + "/",),
    )


def timeline_action_script_paths(
    metadata: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Return exact generated scripts owned by one timeline resource."""

    paths: set[str] = set()
    if metadata is None:
        return ()
    raw_moments = metadata.get("moments")
    if not isinstance(raw_moments, list):
        return ()
    for raw_moment in cast(list[object], raw_moments):
        if not isinstance(raw_moment, dict):
            continue
        raw_actions = cast(dict[object, object], raw_moment).get("actions")
        if not isinstance(raw_actions, list):
            continue
        for raw_action in cast(list[object], raw_actions):
            if not isinstance(raw_action, dict):
                continue
            action = cast(dict[object, object], raw_action)
            if action.get("kind") != "gml":
                continue
            script_path = action.get("script_path")
            if not isinstance(script_path, str):
                continue
            paths.add(_timeline_script_relative_path(script_path))
    return tuple(sorted(paths))


def reconcile_timeline_action_outputs(
    metadata: Mapping[str, object] | None,
    available_paths: Iterable[str],
) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    """Remove missing generated script references from copied timeline metadata."""

    if metadata is None:
        return None, ()
    available = {
        normalize_generation_inventory_path(path)
        for path in available_paths
    }
    reconciled = copy.deepcopy(dict(metadata))
    missing: set[str] = set()
    raw_moments = reconciled.get("moments")
    if not isinstance(raw_moments, list):
        return reconciled, ()
    for raw_moment in cast(list[object], raw_moments):
        if not isinstance(raw_moment, dict):
            continue
        moment = cast(dict[str, object], raw_moment)
        raw_actions = moment.get("actions")
        if not isinstance(raw_actions, list):
            continue
        for raw_action in cast(list[object], raw_actions):
            if not isinstance(raw_action, dict):
                continue
            action = cast(dict[str, object], raw_action)
            if action.get("kind") != "gml":
                continue
            script_path = action.get("script_path")
            if not isinstance(script_path, str):
                continue
            try:
                relative_path = _timeline_script_relative_path(script_path)
            except ValueError:
                relative_path = script_path
            if relative_path not in available:
                action.pop("script_path", None)
                missing.add(relative_path)
    return reconciled, tuple(sorted(missing))


def timeline_json_action_script_paths(metadata: JsonObject | None) -> tuple[str, ...]:
    """Read exact timeline script paths without widening recursive JSON."""
    paths: set[str] = set()
    if metadata is None:
        return ()
    moments = metadata.get("moments")
    if not isinstance(moments, list):
        return ()
    for moment in moments:
        if not isinstance(moment, dict):
            continue
        actions = moment.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict) or action.get("kind") != "gml":
                continue
            script_path = action.get("script_path")
            if isinstance(script_path, str):
                paths.add(_timeline_script_relative_path(script_path))
    return tuple(sorted(paths))


def reconcile_timeline_json_outputs(
    metadata: JsonObject | None,
    available_paths: Iterable[str],
) -> tuple[JsonObject | None, tuple[str, ...]]:
    """Deepcopy JSON and remove only unavailable generated action paths."""
    if metadata is None:
        return None, ()
    available = {normalize_generation_inventory_path(path) for path in available_paths}
    reconciled = copy.deepcopy(dict(metadata))
    missing: set[str] = set()
    moments = reconciled.get("moments")
    if not isinstance(moments, list):
        return reconciled, ()
    for moment in moments:
        if not isinstance(moment, dict):
            continue
        actions = moment.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict) or action.get("kind") != "gml":
                continue
            script_path = action.get("script_path")
            if not isinstance(script_path, str):
                continue
            try:
                relative_path = _timeline_script_relative_path(script_path)
            except ValueError:
                relative_path = script_path
            if relative_path not in available:
                action.pop("script_path", None)
                missing.add(relative_path)
    return reconciled, tuple(sorted(missing))


def _resource_relative_path(resource_path: str) -> str:
    if not resource_path.startswith("res://"):
        raise ValueError(
            f"Managed resource output is not a res:// path: {resource_path!r}"
        )
    relative_path = normalize_generation_inventory_path(
        resource_path.removeprefix("res://")
    )
    return relative_path


def _timeline_script_relative_path(resource_path: str) -> str:
    relative_path = _resource_relative_path(resource_path)
    if (
        not relative_path.startswith("gm2godot/timelines/")
        or not relative_path.endswith(".gd")
    ):
        raise ValueError(
            "Timeline action output is outside its managed script directory: "
            f"{resource_path!r}"
        )
    return relative_path


def _canonical_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                normalize_generation_inventory_path(path)
                for path in paths
            }
        )
    )


def _canonical_prefix(prefix: str) -> str:
    if not prefix.endswith("/"):
        raise ValueError(
            f"Managed-resource tree prefix must end in '/': {prefix!r}"
        )
    normalized = normalize_generation_inventory_path(prefix[:-1])
    return normalized + "/"


__all__ = [
    "ManagedResourceOutputs",
    "STALE_INVALIDATION_CONVERTER_KEYS",
    "STALE_INVALIDATION_RESOURCE_KINDS",
    "managed_resource_outputs",
    "managed_gamemaker_resource_outputs",
    "timeline_json_action_script_paths",
    "reconcile_timeline_json_outputs",
    "reconcile_timeline_action_outputs",
    "timeline_action_script_paths",
]
