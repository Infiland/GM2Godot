"""Verify the native runtime and immutable fixture inputs before conversion."""

from __future__ import annotations

import json
import os
import platform
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from scripts.conversion_parity_contract import (
    ExternalRepository,
    FixtureDefinition,
    HashRequirement,
    ParityDefinition,
    ParityError,
    RuntimeRequirement,
    json_object,
    value_sha256,
)


def validate_parity_inputs(
    definition: ParityDefinition,
    *,
    root: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Validate runtime, immutable inputs, and source roots before either run."""
    actual_environment = os.environ if environment is None else environment
    validate_runtime(definition.runtime, environment=actual_environment)
    validate_hash_requirements(root, definition.dependency_locks, label="working tree")
    external_paths = validate_external_repositories(
        definition.external_repositories,
        environment=actual_environment,
    )
    return validate_fixtures(
        definition.fixtures,
        root=root,
        environment=actual_environment,
        external_paths=external_paths,
    )


def validate_runtime(
    requirement: RuntimeRequirement,
    *,
    environment: Mapping[str, str],
) -> None:
    """Require the exact Python host and Godot build named by the manifest."""
    actual_python = platform.python_version()
    if actual_python != requirement.python_version:
        raise ParityError(
            f"Python version mismatch: expected {requirement.python_version}, got {actual_python}"
        )
    if sys.platform != requirement.platform_name:
        raise ParityError(
            f"Platform mismatch: expected {requirement.platform_name}, got {sys.platform}"
        )
    actual_machine = platform.machine()
    if actual_machine != requirement.machine:
        raise ParityError(
            f"Machine mismatch: expected {requirement.machine}, got {actual_machine}"
        )
    godot_binary = environment_path(environment, requirement.godot_binary_environment)
    if not godot_binary.is_file() or not os.access(godot_binary, os.X_OK):
        raise ParityError(f"Godot binary is not executable: {godot_binary}")
    try:
        completed = subprocess.run(
            [str(godot_binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ParityError(f"Godot version command could not launch: {godot_binary}") from error
    actual_version = completed.stdout.strip()
    if completed.returncode != 0 or actual_version != requirement.godot_version:
        raise ParityError(
            f"Godot version mismatch: expected {requirement.godot_version!r}, got {actual_version!r}"
        )


def capture_facade_contract(
    code_tree: Path,
    *,
    facade_module: str,
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Capture direct owner identity and signature facts in one exported tree."""
    completed = subprocess.run(
        [sys.executable, "-c", _FACADE_CONTRACT_PROBE, facade_module],
        cwd=code_tree,
        check=False,
        capture_output=True,
        text=True,
        env=dict(environment),
    )
    if completed.returncode != 0 or completed.stderr:
        raise ParityError(
            f"Facade contract probe failed in {code_tree}: {completed.stderr or completed.stdout}"
        )
    try:
        return json_object(json.loads(completed.stdout), "facade contract probe")
    except json.JSONDecodeError as error:
        raise ParityError(f"Facade contract probe emitted invalid JSON in {code_tree}") from error


def validate_hash_requirements(
    root: Path,
    requirements: Sequence[HashRequirement],
    *,
    label: str,
) -> None:
    """Require every declared dependency input to retain its manifest digest."""
    for requirement in requirements:
        path = root / requirement.path
        if not path.is_file():
            raise ParityError(f"{label} is missing immutable input {requirement.path!r}")
        actual = file_sha256(path)
        if actual != requirement.sha256:
            raise ParityError(
                f"{label} hash mismatch for {requirement.path!r}: expected {requirement.sha256}, got {actual}"
            )


def validate_external_repositories(
    repositories: Sequence[ExternalRepository],
    *,
    environment: Mapping[str, str],
) -> dict[str, Path]:
    """Validate remote, commit, and tree identities of pinned external fixtures."""
    paths: dict[str, Path] = {}
    for repository in repositories:
        path = environment_path(environment, repository.environment)
        if not (path / ".git").exists():
            raise ParityError(f"{repository.name} fixture is not a Git checkout: {path}")
        actual_remote = _git_output(path, "remote", "get-url", "origin")
        actual_commit = _git_output(path, "rev-parse", "HEAD")
        actual_tree = _git_output(path, "rev-parse", "HEAD^{tree}")
        if (actual_remote, actual_commit, actual_tree) != (
            repository.remote,
            repository.commit,
            repository.tree,
        ):
            raise ParityError(
                f"{repository.name} fixture identity mismatch: "
                f"expected {(repository.remote, repository.commit, repository.tree)!r}, "
                f"got {(actual_remote, actual_commit, actual_tree)!r}"
            )
        paths[repository.environment] = path
    return paths


def validate_fixtures(
    fixtures: Sequence[FixtureDefinition],
    *,
    root: Path,
    environment: Mapping[str, str],
    external_paths: Mapping[str, Path],
) -> dict[str, Path]:
    """Resolve and hash every conversion input before either source tree runs."""
    sources: dict[str, Path] = {}
    for fixture in fixtures:
        source = fixture_source(fixture, root, environment, external_paths)
        project = _confined_child(source, fixture.project_relative_path, f"{fixture.identifier} project")
        if not project.is_file():
            raise ParityError(f"{fixture.identifier} project file is missing: {project}")
        assert_fixture_hash(fixture, source)
        sources[fixture.identifier] = source
    return sources


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash relative names, modes, and bytes while excluding VCS metadata."""
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ParityError(f"Fixture must not contain a symlink: {path}")
        if path.is_dir() or ".git" in path.relative_to(root).parts:
            continue
        rows.append(
            (
                path.relative_to(root).as_posix(),
                stat.S_IMODE(path.stat().st_mode),
                file_sha256(path),
            )
        )
    return value_sha256(rows)


def fixture_source(
    fixture: FixtureDefinition,
    root: Path,
    environment: Mapping[str, str],
    external_paths: Mapping[str, Path],
) -> Path:
    if fixture.repository_path is not None:
        return _confined_child(root, fixture.repository_path, f"{fixture.identifier} source")
    assert fixture.environment is not None
    return external_paths.get(fixture.environment) or environment_path(environment, fixture.environment)


def _confined_child(root: Path, relative_path: str, label: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ParityError(f"{label} escapes its fixture root: {relative_path!r}")
    return candidate


def assert_fixture_hash(fixture: FixtureDefinition, source: Path) -> None:
    actual = tree_sha256(source)
    if actual != fixture.sha256:
        raise ParityError(
            f"{fixture.identifier} fixture hash mismatch: expected {fixture.sha256}, got {actual}"
        )


def _git_output(path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ParityError(f"Git identity command failed in {path}: {' '.join(arguments)}")
    return completed.stdout.strip()


def environment_path(environment: Mapping[str, str], name: str) -> Path:
    value = environment.get(name)
    if not value:
        raise ParityError(f"Missing required environment variable {name}")
    return Path(value).resolve()


_FACADE_CONTRACT_PROBE = r'''
from __future__ import annotations

import ast
import importlib
import inspect
import json
from pathlib import Path
import sys


def owner_name(facade_name, node):
    if node.level == 0:
        return node.module or ""
    package = facade_name.split(".")[:-1]
    package = package[: len(package) - node.level + 1]
    if node.module:
        package.extend(node.module.split("."))
    return ".".join(package)


facade_name = sys.argv[1]
facade = importlib.import_module(facade_name)
all_exports = getattr(facade, "__all__", ())
if not isinstance(all_exports, list) or not all(isinstance(name, str) for name in all_exports):
    raise SystemExit("Facade must expose literal public __all__ list")
exports = [name for name in all_exports if not name.startswith("_")]
imports = {}
tree = ast.parse(Path(facade.__file__).read_text(encoding="utf-8"))
for node in tree.body:
    if not isinstance(node, ast.ImportFrom) or node.module == "__future__":
        continue
    owner = owner_name(facade_name, node)
    for item in node.names:
        local = item.asname or item.name
        if local in exports:
            imports[local] = (owner, item.name)
bindings = []
for name in exports:
    if name not in imports:
        raise SystemExit(f"Facade export has no direct owner import: {name}")
    owner, original = imports[name]
    expected = getattr(importlib.import_module(owner), original)
    value = getattr(facade, name)
    bindings.append({
        "name": name,
        "owner": owner,
        "original": original,
        "identity": value is expected,
        "signature": str(inspect.signature(value, eval_str=False)) if callable(value) else None,
    })
if not all(binding["identity"] for binding in bindings):
    raise SystemExit("Facade binding identity mismatch")
print(json.dumps({
    "public_exports": exports,
    "private_export_count": len(all_exports) - len(exports),
    "bindings": bindings,
}, sort_keys=True))
'''
