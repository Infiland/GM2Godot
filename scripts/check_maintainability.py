"""Check exact debt and permit only deletion/lowering against a Git parent."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import cast

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.maintainability_metrics import (
    LINT_RULES,
    MODULE_KINDS,
    THRESHOLDS,
    Debt,
    MaintainabilityError,
    SizeEvidence,
    measure,
    ruff_version,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = "maintainability-baseline.json"
SCHEMA_VERSION = 2
# The one pre-policy tree accepted at bootstrap. Later missing parents fail closed.
BOOTSTRAP_REF = "38b364855f06e971d2676b921fd300e1f40f076a"


@dataclass(frozen=True)
class Baseline:
    debt: Debt
    sizes: dict[str, SizeEvidence]


def measured_baseline(root: Path, paths: list[str]) -> Baseline:
    sizes: dict[str, SizeEvidence] = {}
    return Baseline(measure(root, paths, sizes=sizes), sizes)


def physical_size_keys(debt: Debt) -> set[str]:
    return {key for key in debt if "|module_lines." in key or "|function_lines|" in key}


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise MaintainabilityError(f"git {' '.join(args)}: {result.stderr.decode().strip()}")
    return result.stdout


def python_paths(raw: bytes) -> list[str]:
    paths = sorted({path for path in raw.decode().split("\0") if path.endswith((".py", ".pyi", ".pyw"))})
    for path in paths:
        if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise MaintainabilityError(f"invalid source path: {path}")
    return paths


def working_paths(root: Path) -> list[str]:
    paths = python_paths(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    if any((root / path).is_symlink() for path in paths):
        raise MaintainabilityError("Python inventory must not contain symlinks")
    return [path for path in paths if (root / path).is_file()]


def policy(root: Path) -> dict[str, object]:
    return {
        "ruff": ruff_version(root),
        "thresholds": THRESHOLDS,
        "module_kinds": MODULE_KINDS,
        "lint_rules": list(LINT_RULES),
        "size_structure": (
            "statements + collection entries + call arguments + expression operations + comprehension clauses "
            "+ multiline string/bytes payload breaks; "
            "Python 3.12 AST without locations"
        ),
    }


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MaintainabilityError(f"duplicate baseline key: {key}")
        result[key] = value
    return result


def load_baseline(raw: str, expected_policy: dict[str, object]) -> Baseline:
    value = cast(object, json.loads(raw, object_pairs_hook=reject_duplicate_keys))
    if not isinstance(value, dict):
        raise MaintainabilityError("baseline must be an object")
    data = cast(dict[str, object], value)
    if set(data) != {"schema_version", "policy", "debt", "size_evidence"}:
        raise MaintainabilityError("baseline fields must be schema_version, policy, debt, size_evidence")
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise MaintainabilityError(f"schema_version: expected {SCHEMA_VERSION}, found {data['schema_version']!r}")
    if data["policy"] != expected_policy:
        raise MaintainabilityError(
            "measurement policy/version mismatch; expected unchanged thresholds, classifications and pinned Ruff"
        )
    if not isinstance(data["debt"], dict):
        raise MaintainabilityError("baseline debt must be an object")
    debt = cast(dict[str, object], data["debt"])
    if any(type(count) is not int or count <= 0 for count in debt.values()):
        raise MaintainabilityError("baseline debt limits must be positive integers")
    validated_debt = cast(Debt, debt)
    return Baseline(validated_debt, load_size_evidence(data["size_evidence"], validated_debt))


def load_size_evidence(value: object, debt: Debt) -> dict[str, SizeEvidence]:
    if not isinstance(value, dict):
        raise MaintainabilityError("size evidence must name exactly the physical size debt entries")
    records = cast(dict[str, object], value)
    if set(records) != physical_size_keys(debt):
        raise MaintainabilityError("size evidence must name exactly the physical size debt entries")
    evidence: dict[str, SizeEvidence] = {}
    for key, record in records.items():
        if not isinstance(record, dict):
            raise MaintainabilityError(f"invalid size evidence: {key}")
        fields = cast(dict[str, object], record)
        if set(fields) != {"lines", "structure", "ast_sha256"}:
            raise MaintainabilityError(f"invalid size evidence: {key}")
        lines, structure, fingerprint = fields["lines"], fields["structure"], fields["ast_sha256"]
        if type(lines) is not int or lines < 0 or lines > debt[key] or type(structure) is not int or structure < 0:
            raise MaintainabilityError(f"invalid size evidence counts: {key}")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise MaintainabilityError(f"invalid size evidence fingerprint: {key}")
        evidence[key] = SizeEvidence(lines, structure, fingerprint)
    return evidence


def serialize(root: Path, debt: Debt, sizes: dict[str, SizeEvidence] | None = None) -> str:
    evidence = {key: asdict((sizes or {})[key]) for key in sorted(physical_size_keys(debt))}
    return (
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "policy": policy(root), "debt": debt, "size_evidence": evidence},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def violations(actual: Debt, limits: Debt) -> list[str]:
    return [
        f"{key}: measured {value}, expected limit {limits.get(key, 0)}"
        for key, value in sorted(actual.items())
        if value > limits.get(key, 0)
    ]


def stale_entries(actual: Debt, recorded: Debt) -> list[str]:
    return [
        f"{key}: recorded limit {limit}, expected {actual.get(key, 0)}; lower/remove with --update"
        for key, limit in sorted(recorded.items())
        if limit > actual.get(key, 0)
    ]


def bootstrap_debt(root: Path, revision: str) -> Baseline:
    paths = python_paths(git(root, "ls-tree", "-r", "--name-only", "-z", revision))
    archive = git(root, "archive", revision, "--", *paths, "requirements-tooling.txt")
    with tempfile.TemporaryDirectory(prefix="gm2godot-maintainability-") as directory:
        snapshot = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            for path in [*paths, "requirements-tooling.txt"]:
                member = contents.getmember(path)
                if not member.isfile():
                    raise MaintainabilityError(f"parent source must be a regular file: {path}")
                stream = contents.extractfile(member)
                if stream is None:
                    raise MaintainabilityError(f"cannot read parent source: {path}")
                destination = snapshot / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(stream.read())
        return measured_baseline(snapshot, paths)


def parent_debt(root: Path, base_ref: str) -> Baseline:
    revision = git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").decode().strip()
    git(root, "merge-base", "--is-ancestor", revision, "HEAD")
    names = git(root, "ls-tree", "--name-only", revision, "--", BASELINE_PATH).decode().splitlines()
    if BASELINE_PATH in names:
        return load_baseline(git(root, "show", f"{revision}:{BASELINE_PATH}").decode(), policy(root))
    if revision != BOOTSTRAP_REF:
        raise MaintainabilityError(f"parent {revision} is missing {BASELINE_PATH}; only {BOOTSTRAP_REF} may bootstrap")
    return bootstrap_debt(root, revision)


def retain_size_allowances(actual: Baseline, parent: Baseline) -> Baseline:
    """Permit only proportional structural reductions of existing line debt."""
    debt = dict(actual.debt)
    for key in sorted(physical_size_keys(parent.debt)):
        before = parent.sizes[key]
        after = actual.sizes.get(key)
        if after is None:
            continue
        retained = (
            (parent.debt[key] * after.structure + before.structure - 1) // before.structure
            if before.structure
            else parent.debt[key]
        )
        effective = max(after.lines, retained)
        threshold = ("test_" if key.startswith("tests|") else "") + (
            "module_lines" if "|module_lines." in key else "function_lines"
        )
        if effective > THRESHOLDS[threshold]:
            debt[key] = effective
    return Baseline(dict(sorted(debt.items())), actual.sizes)


def check(root: Path, baseline: Path, base_ref: str, update: bool) -> int:
    parent = parent_debt(root, base_ref)
    actual = retain_size_allowances(measured_baseline(root, working_paths(root)), parent)
    failures = violations(actual.debt, parent.debt)
    if baseline.exists():
        recorded = load_baseline(baseline.read_text(encoding="utf-8"), policy(root))
        failures.extend(violations(recorded.debt, parent.debt))
        failures.extend(violations(actual.debt, recorded.debt))
    elif update:
        recorded = actual
    else:
        raise MaintainabilityError(f"missing baseline: {baseline}; initialize deliberately with --update")
    if not update:
        failures.extend(stale_entries(actual.debt, recorded.debt))
        if any(actual.sizes.get(key) != evidence for key, evidence in recorded.sizes.items()):
            failures.append("size evidence does not match measured source; run --update")
        if baseline.read_text(encoding="utf-8") != serialize(root, recorded.debt, recorded.sizes):
            failures.append("baseline encoding: expected canonical sorted JSON; run --update")
    if failures:
        print("Maintainability debt failed:\n" + "\n".join(dict.fromkeys(failures)), file=sys.stderr)
        return 1
    if update:
        baseline.write_text(serialize(root, actual.debt, actual.sizes), encoding="utf-8")
    print(f"Maintainability debt {'updated' if update else 'passed'}: {len(actual.debt)} exact entries; parent {base_ref}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / BASELINE_PATH)
    parser.add_argument(
        "--base-ref", required=True, help="PR merge-base, previous push SHA, or HEAD for local uncommitted edits"
    )
    parser.add_argument("--update", action="store_true", help="write exact reductions; never accept new debt")
    args = parser.parse_args(argv)
    try:
        return check(PROJECT_ROOT, args.baseline, args.base_ref, args.update)
    except (MaintainabilityError, OSError, SyntaxError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Maintainability configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
