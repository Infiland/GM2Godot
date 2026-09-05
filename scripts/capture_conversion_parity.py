from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path

from scripts._anchored_output import (
    AnchoredOutputError,
    publish_identical_receipt_bytes,
)
from scripts.conversion_parity_contract import (
    DestinationDefinition,
    FixtureDefinition,
    ParityDefinition,
    ParityError,
    load_parity_definition,
    value_sha256,
)
from scripts.conversion_parity_inputs import (
    assert_fixture_hash,
    capture_facade_contract,
    validate_hash_requirements,
    validate_parity_inputs,
)
from scripts.conversion_parity_snapshot import (
    FixtureRun,
    collect_output_files,
    compare_fixture_runs,
    output_snapshot,
    serialize_fixture_run,
    snapshot_object,
    validate_expected_outcome,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def capture_parity(
    definition: ParityDefinition,
    *,
    base_ref: str,
    head_ref: str,
    root: Path,
) -> dict[str, object]:
    """Resolve immutable commits before exporting either source tree."""
    resolved_base_sha = resolve_commit_ref(root, base_ref)
    resolved_head_sha = resolve_commit_ref(root, head_ref)
    sources = validate_parity_inputs(definition, root=root)
    with tempfile.TemporaryDirectory(prefix="gm2godot-parity-") as temporary_root:
        temporary = Path(temporary_root)
        base_tree = export_ref(root, resolved_base_sha, temporary / "base")
        head_tree = export_ref(root, resolved_head_sha, temporary / "head")
        validate_hash_requirements(base_tree, definition.dependency_locks, label="base export")
        validate_hash_requirements(head_tree, definition.dependency_locks, label="head export")
        environment = _conversion_environment()
        base_facade = capture_facade_contract(
            base_tree,
            facade_module=definition.facade_module,
            environment=environment,
        )
        head_facade = capture_facade_contract(
            head_tree,
            facade_module=definition.facade_module,
            environment=environment,
        )
        fixture_receipts = _capture_fixture_receipts(
            definition,
            sources=sources,
            base_tree=base_tree,
            head_tree=head_tree,
            output_root=temporary / "outputs",
        )
    differences = {
        receipt["fixture"]: receipt["differences"]
        for receipt in fixture_receipts
        if receipt["differences"]
    }
    base_public_facade = {
        "public_exports": base_facade["public_exports"],
        "bindings": base_facade["bindings"],
    }
    head_public_facade = {
        "public_exports": head_facade["public_exports"],
        "bindings": head_facade["bindings"],
    }
    if base_public_facade != head_public_facade:
        differences["facade_contract"] = {
            "base_sha256": value_sha256(base_public_facade),
            "head_sha256": value_sha256(head_public_facade),
        }
    return {
        "requested_base_ref": base_ref,
        "requested_head_ref": head_ref,
        "resolved_base_sha": resolved_base_sha,
        "resolved_head_sha": resolved_head_sha,
        "contract": _contract_receipt(definition, sources),
        "fields": list(definition.fields),
        "facade_contract": {"base": base_facade, "head": head_facade},
        "fixtures": fixture_receipts,
        "differences": differences,
        "equal": not differences,
    }


def write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    """Publish a fresh or byte-identical canonical parity receipt."""
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    # Preserve the previous text writer's native newline bytes, including CRLF.
    publish_identical_receipt_bytes(path, payload.replace("\n", os.linesep).encode("utf-8"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture exact base-to-head conversion parity for one architecture gate."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        definition = load_parity_definition(args.manifest, args.gate)
        receipt = capture_parity(
            definition,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            root=PROJECT_ROOT,
        )
    except ParityError as error:
        print(f"parity capture error: {error}", file=sys.stderr)
        return 2
    try:
        write_receipt(args.receipt, receipt)
    except AnchoredOutputError as error:
        print(f"receipt publication error [{error.code}]: {error}", file=sys.stderr)
        traceback.print_exception(error, file=sys.stderr)
        return 2
    return 0 if receipt["equal"] else 1


def _capture_fixture_receipts(
    definition: ParityDefinition,
    *,
    sources: Mapping[str, Path],
    base_tree: Path,
    head_tree: Path,
    output_root: Path,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for fixture in definition.fixtures:
        source = sources[fixture.identifier]
        assert_fixture_hash(fixture, source)
        destination = output_root / fixture.identifier
        base = run_fixture(base_tree, source, destination, fixture, definition.destination)
        _remove_generated_target(destination)
        assert_fixture_hash(fixture, source)
        head = run_fixture(head_tree, source, destination, fixture, definition.destination)
        differences = compare_fixture_runs(base, head, definition.fields)
        receipts.append(
            {
                "fixture": fixture.identifier,
                "source": str(source),
                "source_sha256": fixture.sha256,
                "destination": base.destination,
                "base": serialize_fixture_run(base),
                "head": serialize_fixture_run(head),
                "differences": differences,
            }
        )
    return receipts


def run_fixture(
    code_tree: Path,
    source: Path,
    destination: Path,
    fixture: FixtureDefinition,
    destination_definition: DestinationDefinition,
) -> FixtureRun:
    """Capture converter output before boot creates any Godot cache artifacts."""
    _prepare_destination(destination, destination_definition)
    completed = subprocess.run(
        build_conversion_command(source, destination, fixture),
        cwd=code_tree,
        check=False,
        capture_output=True,
        text=True,
        env=_conversion_environment(),
    )
    if completed.returncode != fixture.expected_exit:
        detail = (completed.stderr or completed.stdout).strip()
        raise ParityError(
            f"{fixture.identifier} exit mismatch: expected {fixture.expected_exit}, got {completed.returncode}: {detail}"
        )
    files = collect_output_files(destination)
    snapshot = output_snapshot(
        files,
        destination=destination,
        definition=destination_definition,
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_status=completed.returncode,
        parser_error=parser_error_snapshot(code_tree),
        runtime_markers={},
    )
    validate_expected_outcome(snapshot, fixture)
    snapshot["runtime_markers"] = runtime_marker_snapshot(
        code_tree,
        destination,
        boot_frames=_runtime_boot_frames(destination),
    )
    return FixtureRun(destination=str(destination), files=files, snapshot=snapshot)


def runtime_marker_snapshot(
    code_tree: Path,
    destination: Path,
    *,
    boot_frames: int,
) -> dict[str, object]:
    """Run post-snapshot validation and retain ordered runtime operations."""
    completed = subprocess.run(
        [sys.executable, "-c", _RUNTIME_PROBE, str(destination), str(boot_frames)],
        cwd=code_tree,
        check=False,
        capture_output=True,
        text=True,
        env=_conversion_environment(),
    )
    if completed.returncode != 0 or completed.stderr:
        raise ParityError(
            f"Runtime marker probe failed in {code_tree}: {completed.stderr or completed.stdout}"
        )
    try:
        return snapshot_object(json.loads(completed.stdout), "runtime marker probe")
    except json.JSONDecodeError as error:
        raise ParityError(f"Runtime marker probe emitted invalid JSON in {code_tree}") from error


def _runtime_boot_frames(destination: Path) -> int:
    project = destination / "project.godot"
    return 2 if project.is_file() and "run/main_scene" in project.read_text(encoding="utf-8") else 0


def parser_error_snapshot(code_tree: Path) -> dict[str, object]:
    """Capture a stable parser error through the public facade in each export."""
    completed = subprocess.run(
        [sys.executable, "-c", _PARSER_ERROR_PROBE],
        cwd=code_tree,
        check=False,
        capture_output=True,
        text=True,
        env=_conversion_environment(),
    )
    if completed.returncode != 0 or completed.stderr:
        raise ParityError(
            f"Parser-error probe failed in {code_tree}: {completed.stderr or completed.stdout}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ParityError(f"Parser-error probe emitted invalid JSON in {code_tree}") from error
    return snapshot_object(value, "parser-error probe")
def resolve_commit_ref(root: Path, requested_ref: str) -> str:
    """Resolve one requested ref to an immutable commit SHA before expensive work."""
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{requested_ref}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    resolved = completed.stdout.strip()
    if completed.returncode != 0 or len(resolved) != 40:
        raise ParityError(f"Parity ref is not an unambiguous commit: {requested_ref!r}")
    return resolved
def export_ref(root: Path, revision: str, destination: Path) -> Path:
    """Create one clean source tree without sharing untracked working-tree files."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", revision],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if archive.returncode != 0:
        message = archive.stderr.decode("utf-8", errors="replace").strip()
        raise ParityError(f"Cannot export {revision!r}: {message}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as source:
        members = source.getmembers()
        root_path = destination.resolve()
        for member in members:
            target = (destination / member.name).resolve()
            if target != root_path and root_path not in target.parents:
                raise ParityError(f"Git archive member escapes export tree: {member.name!r}")
        source.extractall(destination, members=members, filter="data")
    return destination


def _contract_receipt(
    definition: ParityDefinition,
    sources: Mapping[str, Path],
) -> dict[str, object]:
    return {
        "runtime": {
            "python_version": definition.runtime.python_version,
            "platform": definition.runtime.platform_name,
            "machine": definition.runtime.machine,
            "godot_version": definition.runtime.godot_version,
        },
        "facade_module": definition.facade_module,
        "dependency_locks": [
            {"path": requirement.path, "sha256": requirement.sha256}
            for requirement in definition.dependency_locks
        ],
        "external_repositories": [
            {
                "name": repository.name,
                "environment": repository.environment,
                "remote": repository.remote,
                "commit": repository.commit,
                "tree": repository.tree,
            }
            for repository in definition.external_repositories
        ],
        "fixtures": [
            {
                "id": fixture.identifier,
                "source": str(sources[fixture.identifier]),
                "sha256": fixture.sha256,
                "project_relative_path": fixture.project_relative_path,
            }
            for fixture in definition.fixtures
        ],
    }


def build_conversion_command(
    source: Path,
    destination: Path,
    fixture: FixtureDefinition,
) -> list[str]:
    project_yyp = source / fixture.project_relative_path
    arguments = [
        "convert",
        "--gm-project",
        str(project_yyp.parent),
        "--godot-project",
        str(destination),
        "--target-platform",
        "windows",
        "--report-dir",
        str(destination / "reports"),
        "--allow-partial",
    ]
    if fixture.only:
        arguments.extend(("--only", ",".join(fixture.only)))
    else:
        arguments.extend(("--groups", "assets,project,wip"))
    _append_threshold(arguments, "--max-warnings", fixture.max_warnings)
    _append_threshold(arguments, "--max-errors", fixture.max_errors)
    _append_threshold(arguments, "--max-unsupported", fixture.max_unsupported)
    payload = {"arguments": arguments, "project_yyp": str(project_yyp)}
    return [sys.executable, "-c", _CLI_PROBE, json.dumps(payload)]


def _prepare_destination(destination: Path, definition: DestinationDefinition) -> None:
    if destination.exists():
        raise ParityError(f"Parity destination was not reset: {destination}")
    destination.mkdir(parents=True)
    (destination / "project.godot").write_text(definition.seed_project_godot, encoding="utf-8")


def _remove_generated_target(destination: Path) -> None:
    if not destination.is_dir():
        raise ParityError(f"Generated target is missing before reset: {destination}")
    shutil.rmtree(destination)


def _conversion_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONHASHSEED"] = "0"
    return environment


def _append_threshold(arguments: list[str], flag: str, value: int | None) -> None:
    if value is not None:
        arguments.extend((flag, str(value)))


_CLI_PROBE = r'''
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

os.cpu_count = lambda: 1

from src import cli

payload = json.loads(sys.argv[1])
project_yyp = Path(payload["project_yyp"])
if not project_yyp.is_file():
    raise SystemExit(f"Parity project is missing: {project_yyp}")
arguments = payload["arguments"]
if arguments[arguments.index("--gm-project") + 1] != str(project_yyp.parent):
    raise SystemExit("Parity --gm-project must be the validated YYP parent directory")
raise SystemExit(cli.main(arguments))
'''


_RUNTIME_PROBE = r'''
from __future__ import annotations
import json
import sys
from dataclasses import asdict, is_dataclass

from src.conversion.godot_validation import validate_generated_godot_project


def encode_issue(issue):
    return asdict(issue) if is_dataclass(issue) else str(issue)

report = validate_generated_godot_project(sys.argv[1], boot_frames=int(sys.argv[2]))
if (
    report.returncode not in {None, 0}
    or report.import_returncode not in {None, 0}
    or report.boot_returncode not in {None, 0}
    or any(issue.severity == "error" for issue in report.output_issues)
):
    raise SystemExit(report.message + "\n" + report.output)
boot_output = report.boot_output
operations = [
    line
    for line in boot_output.splitlines()
    if "Adding: Performed " in line
]
print(json.dumps({
    "status": report.status,
    "import_returncode": report.import_returncode,
    "returncode": report.returncode,
    "boot_returncode": report.boot_returncode,
    "boot_frames": report.boot_frames,
    "output_issues": [encode_issue(issue) for issue in report.output_issues],
    "boot_output": boot_output,
    "operations": operations,
}, sort_keys=True))
'''


_PARSER_ERROR_PROBE = r'''
from __future__ import annotations

import json

from src.conversion.gml_transpiler import GMLTranspileError, transpile_gml_expression

try:
    transpile_gml_expression(")")
except GMLTranspileError as error:
    print(json.dumps({"text": str(error), "line": error.line, "column": error.column}, sort_keys=True))
else:
    raise AssertionError("The parser-error probe unexpectedly succeeded")
'''


if __name__ == "__main__":
    raise SystemExit(main())
