from __future__ import annotations

import json
import os
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from src.conversion.atomic_generated_text import (
    atomic_write_confined_generated_text,
)
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.type_defs import JsonDict


INCLUDED_FILE_REGISTRY_RELATIVE_PATH = os.path.join(
    "gm2godot",
    "gml_included_file_registry.gd",
)
INCLUDED_FILE_REGISTRY_RESOURCE_PATH = (
    "res://gm2godot/gml_included_file_registry.gd"
)


@dataclass(frozen=True)
class IncludedFileRegistryEntry:
    logical_path: str
    canonical_path: str
    assigned_path: str
    emitted: bool

    def to_godot_dict(self) -> JsonDict:
        return {
            "logical_path": self.logical_path,
            "canonical_path": self.canonical_path,
            "assigned_path": self.assigned_path,
            "emitted": self.emitted,
        }


def build_included_file_registry_entries(
    assignments: Iterable[IncludedFilePathAssignment],
    emitted_logical_paths: Collection[str],
) -> tuple[IncludedFileRegistryEntry, ...]:
    """Return stable runtime entries for one finalized conversion attempt.

    Planned-but-unavailable entries remain in the registry with ``emitted``
    false. This lets runtime lookup reject a known missing or ambiguous source
    instead of falling through to another file with the same packaged name.
    """

    emitted_paths = set(emitted_logical_paths)
    entries = (
        IncludedFileRegistryEntry(
            logical_path=assignment.original_logical_path,
            canonical_path=assignment.canonical_lookup_path,
            assigned_path=assignment.assigned_output_path,
            emitted=assignment.original_logical_path in emitted_paths,
        )
        for assignment in assignments
    )
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.logical_path,
                entry.canonical_path,
                entry.assigned_path,
            ),
        )
    )


def render_included_file_registry_script(
    entries: Iterable[IncludedFileRegistryEntry],
) -> str:
    ordered_entries = sorted(
        entries,
        key=lambda entry: (
            entry.logical_path,
            entry.canonical_path,
            entry.assigned_path,
        ),
    )
    payload = [entry.to_godot_dict() for entry in ordered_entries]
    entries_literal = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (
        "extends RefCounted\n\n"
        "const FORMAT_VERSION = 1\n"
        f"const INCLUDED_FILES = {entries_literal}\n\n"
        "static func gml_included_file_registry_entries():\n"
        "\treturn INCLUDED_FILES\n"
    )


def render_included_file_registry(
    assignments: Iterable[IncludedFilePathAssignment],
    emitted_logical_paths: Collection[str],
) -> str:
    """Render the authoritative registry for one Included Files output set."""

    return render_included_file_registry_script(
        build_included_file_registry_entries(
            assignments,
            emitted_logical_paths,
        )
    )


def write_included_file_registry(
    godot_project_path: str,
    assignments: Iterable[IncludedFilePathAssignment],
    emitted_logical_paths: Collection[str],
) -> str:
    """Atomically publish the Included File lookup registry."""

    registry_path = os.path.join(
        godot_project_path,
        INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    )
    atomic_write_confined_generated_text(
        registry_path,
        render_included_file_registry(
            assignments,
            emitted_logical_paths,
        ),
        confinement_root=godot_project_path,
    )
    return registry_path


__all__ = [
    "INCLUDED_FILE_REGISTRY_RELATIVE_PATH",
    "INCLUDED_FILE_REGISTRY_RESOURCE_PATH",
    "IncludedFileRegistryEntry",
    "build_included_file_registry_entries",
    "render_included_file_registry",
    "render_included_file_registry_script",
    "write_included_file_registry",
]
