from __future__ import annotations

import json
import os
import posixpath
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from src.conversion.anchored_artifacts import (
    ByteArtifactTransaction,
    StagedArtifact,
    artifact_sha256,
)
from src.conversion.architecture_policy import build_architecture_policy_report
from src.conversion.asset_registry import (
    AssetRegistryConverter,
    AssetRegistryEntry,
    AssetRegistryPublication,
)
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.conversion_plan import build_conversion_plan, conversion_step_map
from src.conversion.conversion_artifact_generation import (
    publish_conversion_artifact_generation,
    recover_conversion_artifact_generation,
)
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_nested_resource_path,
    generated_resource_stem,
    is_snake_case_path_segment,
    res_path_segments,
    snake_case_res_path,
)
from src.conversion.generation_inventory import (
    GenerationInventory,
    capture_generation_inventory,
    migrate_generation_inventory,
    validate_generation_inventory,
)
from src.conversion.included_file_paths import (
    canonical_included_file_lookup_path,
    plan_included_file_paths,
)
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.type_defs import JsonDict

CONVERSION_MANIFEST_RELATIVE_PATH = os.path.join("gm2godot", "conversion_manifest.json")
CONVERSION_ATTEMPT_RELATIVE_PATH = os.path.join("gm2godot", "conversion_attempt.json")
CONVERSION_EVIDENCE_MAX_BYTES = 32 * 1024 * 1024
_MANIFEST_FILENAME = os.path.basename(CONVERSION_MANIFEST_RELATIVE_PATH)
_ATTEMPT_FILENAME = os.path.basename(CONVERSION_ATTEMPT_RELATIVE_PATH)
_ARTIFACT_DIRECTORY = os.path.dirname(CONVERSION_MANIFEST_RELATIVE_PATH)
_ARTIFACT_DIRECTORY_DESCRIPTION = "conversion artifact directory"
FileFingerprint: TypeAlias = tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ConversionOutputSnapshot:
    """Destination state captured before a conversion starts."""

    files: Mapping[str, FileFingerprint]
    generation_inventory: GenerationInventory | None = None


@dataclass(frozen=True)
class GeneratedFileEntry:
    """Backward-compatible generated-files projection for library consumers."""

    path: str
    kind: str
    sha256: str

    def to_dict(self) -> JsonDict:
        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
        }


def write_conversion_artifacts(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
    output_snapshot: ConversionOutputSnapshot,
    generation_inventory: GenerationInventory | None = None,
    generation_root_path: str | None = None,
    manifest_outcome: ConversionOutcome | None,
    attempt_outcome: ConversionOutcome,
) -> tuple[str | None, str]:
    """Transactionally publish the final attempt and, when trustworthy, manifest.

    Every terminal attempt is written separately.  A failed or cancelled run
    without a trustworthy completed-work candidate preserves the prior
    canonical manifest; late report/finalizer outcomes may retain a matching
    candidate.  When both artifacts are published, the attempt is replaced
    first and the canonical manifest last.
    """
    enabled_converter_keys = _normalized_enabled_converter_keys(enabled_converters)
    expected_steps = _planned_step_names(enabled_converter_keys)
    _validate_outcome_plan(
        attempt_outcome,
        expected_steps,
        description="Conversion attempt",
    )
    if manifest_outcome is not None:
        _validate_canonical_outcome(
            manifest_outcome,
            expected_steps,
        )
        _validate_attempt_matches_canonical(
            manifest_outcome,
            attempt_outcome,
        )

    manifest_path = os.path.join(godot_project_path, CONVERSION_MANIFEST_RELATIVE_PATH)
    attempt_path = os.path.join(godot_project_path, CONVERSION_ATTEMPT_RELATIVE_PATH)

    manifest_content: bytes | None = None
    manifest_asset_converter: AssetRegistryConverter | None = None
    manifest_asset_publication: AssetRegistryPublication | None = None
    manifest_digest: str | None = None
    attempt_content: bytes | None = None
    frozen_inventory: GenerationInventory | None = None
    inventory_root = (
        godot_project_path
        if generation_root_path is None
        else generation_root_path
    )
    if manifest_outcome is not None:
        frozen_inventory = (
            generation_inventory
            if generation_inventory is not None
            else capture_generation_inventory(
                inventory_root,
                previous_inventory=output_snapshot.generation_inventory,
                enabled_converters=enabled_converter_keys,
            )
        )
        validate_generation_inventory(inventory_root, frozen_inventory)
        manifest_asset_converter = _asset_registry_converter(
            gm_project_path,
            godot_project_path,
            macro_configuration=target_platform,
        )
        manifest_asset_publication = (
            manifest_asset_converter.prepare_published_entries(
                generation_inventory=frozen_inventory,
            )
        )
        manifest_payload = _build_conversion_manifest(
            gm_project_path,
            godot_project_path,
            target_platform=target_platform,
            enabled_converter_keys=enabled_converter_keys,
            output_snapshot=output_snapshot,
            conversion_outcome=manifest_outcome,
            asset_entries=manifest_asset_publication.entries,
            generation_inventory=frozen_inventory,
        )
        manifest_content = _serialize_json(manifest_payload)
        manifest_digest = artifact_sha256(manifest_content)
        attempt_content = _serialize_json(
            _conversion_attempt_payload(
                attempt_outcome,
                manifest_status="updated",
                manifest_updated=True,
                current_output_status="verified",
                manifest_digest=manifest_digest,
            )
        )

    with ByteArtifactTransaction.open(
        godot_project_path,
        _ARTIFACT_DIRECTORY,
        create=True,
        description=_ARTIFACT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        attempt_publication: bytes | Callable[[bytes | None], bytes]
        if attempt_content is None:

            def build_attempt_publication(
                canonical_content: bytes | None,
            ) -> bytes:
                manifest_present = canonical_content is not None
                return _serialize_json(
                    _conversion_attempt_payload(
                        attempt_outcome,
                        manifest_status=("preserved" if manifest_present else "absent"),
                        manifest_updated=False,
                        current_output_status=(
                            "unverified" if manifest_present else "unavailable"
                        ),
                        manifest_digest=(
                            artifact_sha256(canonical_content)
                            if canonical_content is not None
                            else None
                        ),
                    )
                )

            attempt_publication = build_attempt_publication
        else:
            attempt_publication = attempt_content

        def revalidate_before_commit(name: str) -> None:
            if name != _MANIFEST_FILENAME:
                return
            if (
                manifest_asset_converter is None
                or manifest_asset_publication is None
                or frozen_inventory is None
            ):
                raise AssertionError(
                    "Canonical publication requires prepared asset and inventory "
                    "receipts."
                )
            validate_generation_inventory(inventory_root, frozen_inventory)
            manifest_asset_converter.revalidate_publication(
                manifest_asset_publication,
                validate_content=False,
            )

        def revalidate_after_commit(name: str) -> None:
            if name != _MANIFEST_FILENAME:
                return
            if (
                manifest_asset_converter is None
                or manifest_asset_publication is None
                or frozen_inventory is None
            ):
                raise AssertionError(
                    "Canonical publication requires prepared asset and inventory "
                    "receipts."
                )
            manifest_asset_converter.revalidate_publication(
                manifest_asset_publication,
                validate_content=True,
            )
            validate_generation_inventory(inventory_root, frozen_inventory)

        publish_conversion_artifact_generation(
            transaction,
            attempt_name=_ATTEMPT_FILENAME,
            manifest_name=_MANIFEST_FILENAME,
            attempt_content=attempt_publication,
            manifest_content=manifest_content,
            before_commit=revalidate_before_commit,
            after_commit=revalidate_after_commit,
        )

        stale_artifacts = _capture_owned_stale_transaction_artifacts(transaction)
        stale_to_cleanup = {
            name: staged
            for name, staged in stale_artifacts.items()
            if _owned_temporary_artifact_target(name) != _MANIFEST_FILENAME
            or manifest_outcome is not None
        }
        transaction.cleanup(stale_to_cleanup)
        transaction.verify_directory()

    return (
        manifest_path if manifest_outcome is not None else None,
        attempt_path,
    )


def recover_conversion_artifacts(godot_project_path: str) -> str | None:
    """Recover an interrupted attempt/manifest generation, if present."""

    with ByteArtifactTransaction.open(
        godot_project_path,
        _ARTIFACT_DIRECTORY,
        create=False,
        description=_ARTIFACT_DIRECTORY_DESCRIPTION,
    ) as transaction:
        return recover_conversion_artifact_generation(
            transaction,
            attempt_name=_ATTEMPT_FILENAME,
            manifest_name=_MANIFEST_FILENAME,
        )


def build_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
    output_snapshot: ConversionOutputSnapshot,
    conversion_outcome: ConversionOutcome,
    generation_inventory: GenerationInventory | None = None,
    generation_root_path: str | None = None,
) -> JsonDict:
    enabled_converter_keys = _normalized_enabled_converter_keys(enabled_converters)
    _validate_canonical_outcome(
        conversion_outcome,
        _planned_step_names(enabled_converter_keys),
    )
    inventory_root = (
        godot_project_path
        if generation_root_path is None
        else generation_root_path
    )
    frozen_inventory = (
        generation_inventory
        if generation_inventory is not None
        else capture_generation_inventory(
            inventory_root,
            previous_inventory=output_snapshot.generation_inventory,
            enabled_converters=enabled_converter_keys,
        )
    )
    validate_generation_inventory(inventory_root, frozen_inventory)
    asset_entries = _asset_registry_entries(
        gm_project_path,
        godot_project_path,
        generation_inventory=frozen_inventory,
        macro_configuration=target_platform,
    )
    return _build_conversion_manifest(
        gm_project_path,
        godot_project_path,
        target_platform=target_platform,
        enabled_converter_keys=enabled_converter_keys,
        output_snapshot=output_snapshot,
        conversion_outcome=conversion_outcome,
        asset_entries=asset_entries,
        generation_inventory=frozen_inventory,
    )


def _build_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converter_keys: tuple[str, ...],
    output_snapshot: ConversionOutputSnapshot,
    conversion_outcome: ConversionOutcome,
    asset_entries: tuple[AssetRegistryEntry, ...],
    generation_inventory: GenerationInventory,
) -> JsonDict:
    project_manifest = load_gamemaker_project_manifest(gm_project_path, target_platform=target_platform)
    generated_files = [
        GeneratedFileEntry(
            path=entry.path,
            kind=entry.kind,
            sha256=entry.sha256,
        ).to_dict()
        for entry in generation_inventory.entries
    ]
    generated_files.append(
        GeneratedFileEntry(
            path=CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            kind="manifest",
            sha256="self",
        ).to_dict()
    )
    return {
        "format_version": 2,
        "conversion": _conversion_record(conversion_outcome),
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
        "generation_inventory": generation_inventory.to_dict(),
        "generated_files": generated_files,
        "source_maps": [
            entry.to_generated_file_dict()
            for entry in generation_inventory.entries
            if entry.path.endswith(".gmlmap.json")
        ],
        "architecture_policies": build_architecture_policy_report(
            gm_project_path,
            target_platform=target_platform,
            enabled_converters=enabled_converter_keys,
        ),
        "path_diagnostics": _path_diagnostics(asset_entries),
    }


def _conversion_record(outcome: ConversionOutcome) -> JsonDict:
    return {
        **outcome.to_dict(),
        "cancelled": outcome.state == "cancelled",
    }


def _normalized_enabled_converter_keys(
    enabled_converters: Iterable[str],
) -> tuple[str, ...]:
    if isinstance(enabled_converters, (str, bytes)):
        raise TypeError("Enabled converters must be an iterable of step names.")
    enabled_keys = tuple(enabled_converters)
    for key in enabled_keys:
        if type(key) is not str:
            raise TypeError("Enabled converter keys must be strings.")
        if not key:
            raise ValueError("Enabled converter keys cannot be empty.")
    known_keys = conversion_step_map()
    unknown_keys = tuple(sorted(set(enabled_keys) - known_keys.keys()))
    if unknown_keys:
        raise ValueError(
            "Unknown enabled converter key(s): " + ", ".join(unknown_keys)
        )
    return tuple(sorted(set(enabled_keys)))


def _planned_step_names(enabled_converter_keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        step.key for step in build_conversion_plan(enabled_converter_keys)
    )


def _validate_outcome_plan(
    outcome: ConversionOutcome,
    expected_steps: tuple[str, ...],
    *,
    description: str,
) -> None:
    if outcome.steps.requested != expected_steps:
        raise ValueError(
            f"{description} requested steps must match the enabled conversion plan; "
            f"expected {expected_steps!r}, got {outcome.steps.requested!r}."
        )


def _validate_canonical_outcome(
    outcome: ConversionOutcome,
    expected_steps: tuple[str, ...],
) -> None:
    if outcome.state not in {"success", "partial"}:
        raise ValueError(
            "Canonical conversion manifests require a success or partial outcome."
        )
    _validate_outcome_plan(
        outcome,
        expected_steps,
        description="Canonical conversion manifest",
    )
    if outcome.steps.completed != expected_steps:
        raise ValueError(
            "Canonical conversion manifests require every enabled converter step "
            "to complete."
        )


def _validate_attempt_matches_canonical(
    canonical_outcome: ConversionOutcome,
    attempt_outcome: ConversionOutcome,
) -> None:
    if (
        attempt_outcome.steps != canonical_outcome.steps
        or attempt_outcome.resources != canonical_outcome.resources
    ):
        raise ValueError(
            "A canonical update and its terminal attempt must describe the same "
            "executed converter and resource work."
        )
    if (
        attempt_outcome.state in {"success", "partial"}
        and attempt_outcome != canonical_outcome
    ):
        raise ValueError(
            "A successful or partial terminal attempt must match its canonical "
            "conversion outcome exactly."
        )
    if attempt_outcome.state == "failed":
        if attempt_outcome.failure_phase not in {"report", "finalizer"}:
            raise ValueError(
                "A failed terminal attempt may retain a canonical update only "
                "for a report or finalizer failure after completed conversion work."
            )
        if (
            type(attempt_outcome.failed_step) is not str
            or not attempt_outcome.failed_step
        ):
            raise ValueError(
                "A failed terminal attempt retaining a canonical update requires "
                "a named failed step."
            )


def _conversion_attempt_payload(
    attempt_outcome: ConversionOutcome,
    *,
    manifest_status: str,
    manifest_updated: bool,
    current_output_status: str,
    manifest_digest: str | None,
) -> JsonDict:
    return {
        "format_version": 1,
        "attempt": _conversion_record(attempt_outcome),
        "canonical_manifest": {
            "path": CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            "status": manifest_status,
            "updated": manifest_updated,
            "current_output": current_output_status,
            "sha256": manifest_digest,
        },
    }


def build_verified_preserved_attempt(
    attempt_outcome: ConversionOutcome,
    canonical_manifest_content: bytes | None,
) -> bytes:
    """Render attempt-only evidence for a transactionally verified generation."""

    if (
        canonical_manifest_content is not None
        and len(canonical_manifest_content) > CONVERSION_EVIDENCE_MAX_BYTES
    ):
        raise OSError("Canonical conversion manifest exceeds the evidence limit")
    manifest_present = canonical_manifest_content is not None
    return _serialize_json(
        _conversion_attempt_payload(
            attempt_outcome,
            manifest_status=("preserved" if manifest_present else "absent"),
            manifest_updated=False,
            current_output_status=(
                "verified" if manifest_present else "unavailable"
            ),
            manifest_digest=(
                artifact_sha256(canonical_manifest_content)
                if canonical_manifest_content is not None
                else None
            ),
        )
    )


def _capture_owned_stale_transaction_artifacts(
    transaction: ByteArtifactTransaction,
) -> dict[str, StagedArtifact]:
    """Capture only identity-bound transaction leftovers for later cleanup."""
    transaction.phase("before_stale_recovery", None)
    captured: dict[str, StagedArtifact] = {}
    for name in transaction.directory.list_names():
        if _owned_temporary_artifact_target(name) is None:
            continue
        try:
            staged = transaction.capture_staged(name)
        except OSError:
            # Redirected, multiply-linked, inaccessible, or concurrently
            # changed lookalikes are never candidates for automatic deletion.
            continue
        if staged is not None:
            captured[name] = staged
    transaction.verify_directory()
    transaction.phase("after_stale_recovery", None)
    return captured


def _owned_temporary_artifact_target(filename: str) -> str | None:
    for artifact_filename in (_MANIFEST_FILENAME, _ATTEMPT_FILENAME):
        prefix = f".{artifact_filename}."
        if not filename.startswith(prefix):
            continue
        for suffix in (".recovery.backup", ".backup", ".tmp"):
            if not filename.endswith(suffix):
                continue
            random_name = filename[len(prefix):-len(suffix)]
            if bool(random_name) and random_name.isascii() and all(
                character.isalnum() or character == "_"
                for character in random_name
            ):
                return artifact_filename
    return None


def _serialize_json(payload: JsonDict) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _asset_registry_entries(
    gm_project_path: str,
    godot_project_path: str,
    *,
    generation_inventory: GenerationInventory,
    macro_configuration: str | None = None,
) -> tuple[AssetRegistryEntry, ...]:
    converter = _asset_registry_converter(
        gm_project_path,
        godot_project_path,
        macro_configuration=macro_configuration,
    )
    return converter.prepare_published_entries(
        generation_inventory=generation_inventory,
    ).entries


def _asset_registry_converter(
    gm_project_path: str,
    godot_project_path: str,
    *,
    macro_configuration: str | None = None,
) -> AssetRegistryConverter:
    return AssetRegistryConverter(
        gm_project_path,
        godot_project_path,
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
        macro_configuration=macro_configuration,
    )


def capture_conversion_output_snapshot(godot_project_path: str) -> ConversionOutputSnapshot:
    """Capture the prior inventory and canonical-manifest presence."""

    generation_inventory = migrate_generation_inventory(godot_project_path)
    manifest_relative_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/")
    manifest_path = os.path.join(
        godot_project_path,
        CONVERSION_MANIFEST_RELATIVE_PATH,
    )
    files: dict[str, FileFingerprint] = {}
    try:
        manifest_stat = os.stat(manifest_path, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        files[manifest_relative_path] = _file_fingerprint(manifest_stat)
    return ConversionOutputSnapshot(
        files=files,
        generation_inventory=generation_inventory,
    )


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _path_diagnostics(entries: tuple[AssetRegistryEntry, ...]) -> list[JsonDict]:
    diagnostics: list[JsonDict] = []
    paths_by_casefold: dict[str, list[AssetRegistryEntry]] = {}
    base_paths_by_casefold: dict[str, list[tuple[AssetRegistryEntry, str]]] = {}
    included_collision_components = _included_file_collision_components(entries)
    for entry in entries:
        if not entry.godot_path:
            continue
        paths_by_casefold.setdefault(entry.godot_path.casefold(), []).append(entry)
        base_path = _base_generated_path(entry)
        if base_path:
            collision_key = base_path.casefold()
            if entry.kind == "included_files":
                logical_path = posixpath.normpath(
                    entry.name.replace("\\", "/")
                )
                collision_key = included_collision_components.get(
                    logical_path,
                    collision_key,
                )
            base_paths_by_casefold.setdefault(collision_key, []).append((entry, base_path))
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


def _included_file_collision_components(
    entries: tuple[AssetRegistryEntry, ...],
) -> dict[str, str]:
    assignments = plan_included_file_paths(
        entry.name
        for entry in entries
        if entry.kind == "included_files"
    )
    component_roots: dict[tuple[str, ...], str] = {}
    for assignment in assignments:
        if not assignment.has_collision:
            continue
        component_roots.setdefault(
            assignment.collision_group,
            (
                "res://included_files/"
                + assignment.canonical_lookup_path
            ).casefold(),
        )

    return {
        logical_path: component_root
        for collision_group, component_root in component_roots.items()
        for logical_path in collision_group
    }


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
    if kind == "included_files":
        return (
            "res://included_files/"
            + canonical_included_file_lookup_path(entry.name)
        )
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
