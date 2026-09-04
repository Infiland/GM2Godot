from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast


class ParityError(ValueError):
    """Raised when a parity contract cannot be prepared or compared."""


@dataclass(frozen=True)
class RuntimeRequirement:
    python_version: str
    platform_name: str
    machine: str
    godot_binary_environment: str
    godot_version: str


@dataclass(frozen=True)
class ExternalRepository:
    name: str
    environment: str
    remote: str
    commit: str
    tree: str


@dataclass(frozen=True)
class HashRequirement:
    path: str
    sha256: str


@dataclass(frozen=True)
class FixtureDefinition:
    identifier: str
    repository_path: str | None
    environment: str | None
    project_relative_path: str
    sha256: str
    only: tuple[str, ...]
    expected_exit: int
    max_warnings: int | None
    max_errors: int | None
    max_unsupported: int | None
    expected_outcome_state: str | None = None
    expected_skipped_resources: int | None = None


@dataclass(frozen=True)
class DestinationDefinition:
    seed_project_godot: str
    same_absolute_path: bool
    reset_between_base_and_head: bool
    transaction_root: str
    transaction_lock: str
    volatile_transaction_fields: tuple[str, ...]

@dataclass(frozen=True)
class ParityDefinition:
    runtime: RuntimeRequirement
    external_repositories: tuple[ExternalRepository, ...]
    dependency_locks: tuple[HashRequirement, ...]
    fixtures: tuple[FixtureDefinition, ...]
    fields: tuple[str, ...]
    facade_module: str
    destination: DestinationDefinition


def load_parity_definition(manifest_path: Path, gate: str) -> ParityDefinition:
    """Load the complete immutable parity contract for one gate."""
    gate_definition = _load_gate_object(manifest_path, gate)
    runtime = _parse_runtime(json_object(gate_definition.get("runtime"), "runtime"))
    external = _parse_external_repositories(gate_definition.get("external_repositories"))
    parity = json_object(gate_definition.get("parity"), "parity")
    return ParityDefinition(
        runtime=runtime,
        external_repositories=external,
        dependency_locks=_parse_hash_requirements(parity.get("dependency_locks")),
        fixtures=_parse_fixtures(parity.get("fixtures")),
        fields=_string_tuple(parity.get("fields"), "parity fields", allow_empty=False),
        facade_module=_required_string(parity, "facade_module", "parity"),
        destination=_parse_destination(json_object(parity.get("destination"), "destination")),
    )


def value_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _load_gate_object(manifest_path: Path, gate: str) -> dict[str, object]:
    try:
        document = json_object(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            "verification manifest",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ParityError(f"Cannot read verification manifest: {error}") from error
    if document.get("schema_version") != 1:
        raise ParityError("Verification manifest must use schema_version 1")
    gates = json_object(document.get("gates"), "gates")
    return json_object(gates.get(gate), f"verification gate {gate!r}")


def _parse_runtime(value: Mapping[str, object]) -> RuntimeRequirement:
    return RuntimeRequirement(
        python_version=_required_string(value, "python_version", "runtime"),
        platform_name=_required_string(value, "platform", "runtime"),
        machine=_required_string(value, "machine", "runtime"),
        godot_binary_environment=_required_string(value, "godot_binary_environment", "runtime"),
        godot_version=_required_string(value, "godot_version", "runtime"),
    )


def _parse_external_repositories(value: object) -> tuple[ExternalRepository, ...]:
    repositories: list[ExternalRepository] = []
    for item in _object_list(value, "external_repositories"):
        repository = json_object(item, "external repository")
        repositories.append(
            ExternalRepository(
                name=_required_string(repository, "name", "external repository"),
                environment=_required_string(repository, "environment", "external repository"),
                remote=_required_string(repository, "remote", "external repository"),
                commit=_required_string(repository, "commit", "external repository"),
                tree=_required_string(repository, "tree", "external repository"),
            )
        )
    return tuple(repositories)


def _parse_hash_requirements(value: object) -> tuple[HashRequirement, ...]:
    requirements: list[HashRequirement] = []
    for item in _object_list(value, "dependency_locks"):
        requirement = json_object(item, "dependency lock")
        requirements.append(
            HashRequirement(
                path=_required_string(requirement, "path", "dependency lock"),
                sha256=_required_string(requirement, "sha256", "dependency lock"),
            )
        )
    return tuple(requirements)


def _parse_fixtures(value: object) -> tuple[FixtureDefinition, ...]:
    fixtures: list[FixtureDefinition] = []
    for item in _object_list(value, "fixtures"):
        fixture = json_object(item, "parity fixture")
        repository_path = _optional_string(fixture.get("repository_path"), "repository_path")
        environment = _optional_string(fixture.get("environment"), "environment")
        if (repository_path is None) == (environment is None):
            raise ParityError("Each parity fixture must name exactly one source location")
        fixtures.append(
            FixtureDefinition(
                identifier=_required_string(fixture, "id", "parity fixture"),
                repository_path=repository_path,
                environment=environment,
                project_relative_path=_required_string(fixture, "project_relative_path", "parity fixture"),
                sha256=_required_string(fixture, "sha256", "parity fixture"),
                only=_string_tuple(fixture.get("only", []), "fixture only", allow_empty=True),
                expected_exit=_required_int(fixture, "expected_exit", "parity fixture"),
                max_warnings=_optional_int(fixture.get("max_warnings"), "max_warnings"),
                max_errors=_optional_int(fixture.get("max_errors"), "max_errors"),
                max_unsupported=_optional_int(fixture.get("max_unsupported"), "max_unsupported"),
                expected_outcome_state=_optional_string(
                    fixture.get("expected_outcome_state"),
                    "expected_outcome_state",
                ),
                expected_skipped_resources=_optional_int(
                    fixture.get("expected_skipped_resources"),
                    "expected_skipped_resources",
                ),
            )
        )
    identifiers = [fixture.identifier for fixture in fixtures]
    if not fixtures or len(identifiers) != len(set(identifiers)):
        raise ParityError("Parity fixtures must be non-empty with unique IDs")
    return tuple(fixtures)


def _parse_destination(value: Mapping[str, object]) -> DestinationDefinition:
    same_absolute_path = _required_bool(value, "same_absolute_path", "destination")
    reset_between_base_and_head = _required_bool(
        value,
        "reset_between_base_and_head",
        "destination",
    )
    if not same_absolute_path or not reset_between_base_and_head:
        raise ParityError("Parity destination must reuse one path and reset it between runs")
    transaction = json_object(value.get("transaction_provenance"), "transaction_provenance")
    return DestinationDefinition(
        seed_project_godot=_required_string(value, "seed_project_godot", "destination"),
        same_absolute_path=same_absolute_path,
        reset_between_base_and_head=reset_between_base_and_head,
        transaction_root=_required_string(transaction, "root", "transaction_provenance"),
        transaction_lock=_required_string(transaction, "lock", "transaction_provenance"),
        volatile_transaction_fields=_string_tuple(
            transaction.get("volatile_fields"),
            "transaction_provenance.volatile_fields",
            allow_empty=False,
        ),
    )


def json_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ParityError(f"{label} must be an object")
    raw = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ParityError(f"{label} keys must be strings")
        result[key] = item
    return result


def _object_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ParityError(f"{label} must be a list")
    return list(cast(list[object], value))


def _string_tuple(value: object, label: str, *, allow_empty: bool) -> tuple[str, ...]:
    result: list[str] = []
    for item in _object_list(value, label):
        if not isinstance(item, str):
            raise ParityError(f"{label} must contain only strings")
        result.append(item)
    if not allow_empty and not result:
        raise ParityError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise ParityError(f"{label} must not contain duplicates")
    return tuple(result)


def _required_string(value: Mapping[str, object], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ParityError(f"{label}.{key} must be a non-empty string")
    return item


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ParityError(f"{label} must be a non-empty string when present")
    return value


def _required_int(value: Mapping[str, object], key: str, label: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ParityError(f"{label}.{key} must be an integer")
    return item


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParityError(f"{label} must be an integer when present")
    return value


def _required_bool(value: Mapping[str, object], key: str, label: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ParityError(f"{label}.{key} must be a boolean")
    return item
