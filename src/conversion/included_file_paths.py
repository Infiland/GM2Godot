from __future__ import annotations

import ntpath
import posixpath
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from src.conversion.project_source_paths import ProjectSourcePathError


_ASCII_LOOKUP_TRANSLATION = str.maketrans(
    {
        **{
            chr(codepoint): chr(codepoint + (ord("a") - ord("A")))
            for codepoint in range(ord("A"), ord("Z") + 1)
        },
        " ": "_",
    }
)


@dataclass(frozen=True)
class IncludedFilePathAssignment:
    """One stable Included File lookup-to-output path assignment.

    ``collision_group`` contains every logical path in the connected
    normalization or file/directory-prefix collision. ``has_collision`` marks
    assignments at that group's deterministic reporting path, allowing the
    converter to emit the complete group once while retaining each member's
    own canonical lookup path.
    """

    original_logical_path: str
    canonical_lookup_path: str
    assigned_output_path: str
    collision_group: tuple[str, ...]
    has_collision: bool


def canonical_included_file_lookup_path(logical_path: str) -> str:
    """Return GameMaker's portable packaged-file lookup form.

    GameMaker's documented Included File lookup normalization is ASCII-style:
    ordinary uppercase Latin letters become lowercase and spaces become
    underscores. Other characters remain unchanged. Path separators and dot
    segments are normalized before applying those filename rules.
    """

    return _canonical_posix_relative_path(logical_path).translate(
        _ASCII_LOOKUP_TRANSLATION
    )


def plan_included_file_paths(
    logical_paths: Iterable[str],
) -> tuple[IncludedFilePathAssignment, ...]:
    """Assign deterministic, collision-safe output paths to Included Files.

    Duplicate aliases of the same normalized logical path describe one file
    and are coalesced. Every natural canonical lookup path is reserved before
    collision suffixes are allocated, so a generated ``_2`` path can never
    displace an actual file whose canonical name already ends in ``_2``.
    """

    normalized_paths = {
        _canonical_posix_relative_path(logical_path)
        for logical_path in logical_paths
    }
    groups: dict[str, list[str]] = defaultdict(list)
    for logical_path in normalized_paths:
        groups[_ascii_lookup_path(logical_path)].append(logical_path)

    canonical_paths = set(groups)
    canonical_directory_paths = {
        directory
        for canonical_path in canonical_paths
        for directory in _parent_paths(canonical_path)
    }
    component_roots = {
        canonical_path: _collision_component_root(
            canonical_path,
            canonical_paths,
        )
        for canonical_path in canonical_paths
    }
    component_paths: dict[str, list[str]] = defaultdict(list)
    for canonical_path, component_root in component_roots.items():
        component_paths[component_root].append(canonical_path)

    collision_groups: dict[str, tuple[str, ...]] = {}
    collision_roots: set[str] = set()
    for component_root, component_members in component_paths.items():
        ordered_component_paths = sorted(component_members)
        logical_group = tuple(
            logical_path
            for canonical_path in ordered_component_paths
            for logical_path in _ordered_logical_group(
                canonical_path,
                groups[canonical_path],
            )
        )
        has_collision = (
            len(ordered_component_paths) > 1
            or len(logical_group) > 1
        )
        if has_collision:
            collision_roots.add(component_root)
        for canonical_path in ordered_component_paths:
            collision_groups[canonical_path] = logical_group

    reserved_paths = canonical_paths
    assigned_paths: set[str] = set()
    assigned_directory_paths: set[str] = set()
    assignments: list[IncludedFilePathAssignment] = []

    for canonical_path in sorted(groups):
        logical_group = _ordered_logical_group(
            canonical_path,
            groups[canonical_path],
        )
        blocks_canonical_directory = canonical_path in canonical_directory_paths
        component_root = component_roots[canonical_path]
        collision_group = collision_groups[canonical_path]
        reports_collision = (
            component_root in collision_roots
            and canonical_path == component_root
        )
        for group_index, logical_path in enumerate(logical_group):
            if group_index == 0 and not blocks_canonical_directory:
                output_path = canonical_path
            else:
                suffix_index = 2
                while True:
                    candidate = _path_with_suffix(canonical_path, suffix_index)
                    if _path_is_available(
                        candidate,
                        reserved_paths=reserved_paths,
                        canonical_directory_paths=canonical_directory_paths,
                        assigned_paths=assigned_paths,
                        assigned_directory_paths=assigned_directory_paths,
                    ):
                        output_path = candidate
                        break
                    suffix_index += 1

            assigned_paths.add(output_path)
            assigned_directory_paths.update(_parent_paths(output_path))
            assignments.append(
                IncludedFilePathAssignment(
                    original_logical_path=logical_path,
                    canonical_lookup_path=canonical_path,
                    assigned_output_path=output_path,
                    collision_group=collision_group,
                    has_collision=reports_collision,
                )
            )

    return tuple(
        sorted(
            assignments,
            key=lambda assignment: assignment.original_logical_path,
        )
    )


def _canonical_posix_relative_path(logical_path: str) -> str:
    normalized_path = logical_path.replace("\\", "/")
    if not normalized_path or "\0" in normalized_path:
        raise ProjectSourcePathError(
            f"Included File logical path is empty or invalid: {logical_path!r}"
        )

    normalized_path = posixpath.normpath(normalized_path)
    if normalized_path in {"", "."}:
        raise ProjectSourcePathError(
            "Included File logical path does not name a project file: "
            f"{logical_path!r}"
        )
    drive, _tail = ntpath.splitdrive(normalized_path)
    if drive or normalized_path.startswith("/"):
        raise ProjectSourcePathError(
            "Included File logical path must be relative to the selected "
            f"GameMaker project root: {logical_path!r}"
        )
    if normalized_path == ".." or normalized_path.startswith("../"):
        raise ProjectSourcePathError(
            "Included File logical path escapes the selected GameMaker "
            f"project root through traversal: {logical_path!r}"
        )
    return normalized_path


def _ascii_lookup_path(logical_path: str) -> str:
    return logical_path.translate(_ASCII_LOOKUP_TRANSLATION)


def _ordered_logical_group(
    canonical_path: str,
    logical_paths: Iterable[str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            logical_paths,
            key=lambda logical_path: (
                logical_path != canonical_path,
                logical_path,
            ),
        )
    )


def _parent_paths(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    return tuple(
        "/".join(parts[:component_count])
        for component_count in range(1, len(parts))
    )


def _collision_component_root(
    canonical_path: str,
    canonical_paths: set[str],
) -> str:
    for parent_path in _parent_paths(canonical_path):
        if parent_path in canonical_paths:
            return parent_path
    return canonical_path


def _path_is_available(
    candidate: str,
    *,
    reserved_paths: set[str],
    canonical_directory_paths: set[str],
    assigned_paths: set[str],
    assigned_directory_paths: set[str],
) -> bool:
    if (
        candidate in reserved_paths
        or candidate in canonical_directory_paths
        or candidate in assigned_paths
        or candidate in assigned_directory_paths
    ):
        return False
    return not any(parent_path in assigned_paths for parent_path in _parent_paths(candidate))


def _path_with_suffix(canonical_path: str, suffix_index: int) -> str:
    directory, filename = posixpath.split(canonical_path)
    stem, extension = posixpath.splitext(filename)
    suffixed_filename = f"{stem}_{suffix_index}{extension}"
    if not directory:
        return suffixed_filename
    return posixpath.join(directory, suffixed_filename)
