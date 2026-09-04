"""Deterministic maintainability measurements for handwritten Python inputs."""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scripts.maintainability_imports import build_graphs, elementary_cycles
from scripts.maintainability_sizes import SizeEvidence, evidence_for_nodes

Debt = dict[str, int]
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (*FUNCTIONS, ast.ClassDef)
BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)
THRESHOLDS = {
    "complexity": 15,
    "function_lines": 150,
    "test_function_lines": 200,
    "module_lines": 800,
    "test_module_lines": 1500,
    "nesting": 4,
    "parameters": 8,
}
MODULE_KINDS = {
    "src/conversion/gml_transpiler_parts/gml_api_manifest.py": "declarative",
    "src/conversion/gml_transpiler_parts/constants.py": "mixed",
}
LINT_RULES = ("C901", "I001", "B", "E4", "E7", "E9")


class MaintainabilityError(ValueError):
    """Malformed input or an unavailable measurement prerequisite."""


@dataclass(frozen=True)
class Symbol:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def source_size_evidence(
    path: str, source: str, found: list[Symbol], *, tree: ast.Module | None = None
) -> dict[str, SizeEvidence]:
    group = classification(path)
    module_key = metric_key(group, f"module_lines.{MODULE_KINDS.get(path, 'executable')}", path)
    nodes: dict[str, list[ast.AST]] = {module_key: [tree or ast.parse(source, feature_version=(3, 12))]}
    lengths = {module_key: len(source.splitlines())}
    for symbol in found:
        if isinstance(symbol.node, FUNCTIONS):
            key = metric_key(group, "function_lines", path, symbol.name)
            nodes.setdefault(key, []).append(symbol.node)
            lengths[key] = max(lengths.get(key, 0), (symbol.node.end_lineno or symbol.node.lineno) - symbol.node.lineno + 1)
    return {
        key: evidence_for_nodes(owners, lengths[key])
        for key, owners in nodes.items()
    }


def classification(path: str) -> str:
    if path == "main.py" or path.startswith("src/"):
        return "application"
    if path.startswith(("scripts/", "packaging/")):
        return "tooling"
    if path.startswith("tests/"):
        return "tests"
    raise MaintainabilityError(f"unknown Python classification: {path}")


def symbols(tree: ast.Module) -> list[Symbol]:
    found: list[Symbol] = []
    pending: list[tuple[ast.AST, str]] = [(tree, "")]
    while pending:
        node, parent = pending.pop()
        if isinstance(node, SCOPES):
            parent = f"{parent}.{node.name}" if parent else node.name
            found.append(Symbol(parent, node))
        pending.extend((child, parent) for child in reversed(list(ast.iter_child_nodes(node))))
    return found


def owner_at(found: list[Symbol], row: int) -> str:
    owners = [symbol for symbol in found if symbol.node.lineno <= row <= (symbol.node.end_lineno or 0)]
    return (
        min(owners, key=lambda symbol: (symbol.node.end_lineno or 0) - symbol.node.lineno).name
        if owners
        else "<module>"
    )


def nesting(node: ast.AST) -> int:
    maximum = 0
    pending = [(child, 0) for child in ast.iter_child_nodes(node)]
    while pending:
        child, depth = pending.pop()
        if isinstance(child, SCOPES):
            continue
        depth += isinstance(child, BLOCKS)
        maximum = max(maximum, depth)
        pending.extend((descendant, depth) for descendant in ast.iter_child_nodes(child))
    return maximum


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    return len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs) + bool(args.vararg) + bool(args.kwarg)


def metric_key(group: str, metric: str, path: str, symbol: str = "<module>") -> str:
    return f"{group}|{metric}|{path}::{symbol}"


def size_debt(
    path: str, source: str, found: list[Symbol], *, sizes: dict[str, SizeEvidence] | None = None
) -> Debt:
    group = classification(path)
    debt: Debt = {}
    module_limit = THRESHOLDS["test_module_lines" if group == "tests" else "module_lines"]
    for key, evidence in (sizes if sizes is not None else source_size_evidence(path, source, found)).items():
        is_module = "|module_lines." in key
        limit = module_limit if is_module else THRESHOLDS["test_function_lines" if group == "tests" else "function_lines"]
        if evidence.lines > limit:
            debt[key] = evidence.lines
        if evidence.structure > limit:
            debt[key.replace("module_lines.", "module_structure.").replace("|function_lines|", "|function_structure|")] = (
                evidence.structure
            )
    duplicates = Counter(symbol.name for symbol in found)
    for name, count in duplicates.items():
        if count > 1:
            debt[metric_key(group, "duplicate_symbol", path, name)] = count
    for symbol in found:
        node = symbol.node
        if not isinstance(node, FUNCTIONS):
            continue
        values = {
            "nesting": nesting(node),
            "parameters": parameters(node),
        }
        for metric, value in values.items():
            if value > THRESHOLDS[metric]:
                key = metric_key(group, metric, path, symbol.name)
                debt[key] = max(debt.get(key, 0), value)
    return debt


def suppression_debt(path: str, source: str, found: list[Symbol]) -> Debt:
    counts: Counter[str] = Counter()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        directive = token.string.strip()
        if re.search(r"#\s*(?:noqa\b|(?:ruff|flake8|pyright|type|pylint)\s*:)", directive, re.IGNORECASE):
            key = metric_key(classification(path), "suppression", path, owner_at(found, token.start[0]))
            counts[f"{key}|{directive}"] += 1
    return dict(counts)


def ruff_version(root: Path) -> str:
    requirements = (root / "requirements-tooling.txt").read_text(encoding="utf-8")
    match = re.search(r"^ruff==([^\s]+)$", requirements, re.MULTILINE)
    if not match:
        raise MaintainabilityError("requirements-tooling.txt must pin ruff==VERSION")
    return match[1]


def run_ruff(root: Path, paths: list[str]) -> list[dict[str, object]]:
    expected = f"ruff {ruff_version(root)}"
    version = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True, check=True)
    if version.stdout.strip() != expected:
        raise MaintainabilityError(f"Ruff version: expected {expected}, found {version.stdout.strip()}")
    findings: list[dict[str, object]] = []
    for offset in range(0, len(paths), 100):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--isolated",
                "--no-cache",
                "--target-version",
                "py312",
                "--select",
                ",".join(LINT_RULES),
                "--config",
                f"lint.mccabe.max-complexity={THRESHOLDS['complexity']}",
                "--ignore-noqa",
                "--no-respect-gitignore",
                "--no-force-exclude",
                "--output-format",
                "json",
                "--",
                *paths[offset : offset + 100],
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise MaintainabilityError(f"Ruff measurement failed: {result.stderr.strip()}")
        findings.extend(cast(list[dict[str, object]], json.loads(result.stdout)))
    return findings


def lint_debt(root: Path, found_by_path: dict[str, list[Symbol]]) -> Debt:
    debt: Debt = {}
    for finding in run_ruff(root, sorted(found_by_path)):
        path = Path(str(finding["filename"])).relative_to(root).as_posix()
        location = cast(dict[str, int], finding["location"])
        symbol = owner_at(found_by_path[path], location["row"])
        message = str(finding["message"])
        if finding["code"] == "C901":
            match = re.search(rf"\((\d+) > {THRESHOLDS['complexity']}\)$", message)
            if not match:
                raise MaintainabilityError(f"unrecognized C901 measurement: {message}")
            key = metric_key(classification(path), "complexity", path, symbol)
            debt[key] = max(debt.get(key, 0), int(match[1]))
        else:
            key = metric_key(classification(path), f"lint.{finding['code']}", path, symbol)
            key += f"|{message}"
            debt[key] = debt.get(key, 0) + 1
    return debt


def measure(root: Path, paths: list[str], *, sizes: dict[str, SizeEvidence] | None = None) -> Debt:
    root = root.resolve()
    trees: dict[str, ast.Module] = {}
    found_by_path: dict[str, list[Symbol]] = {}
    debt: Debt = {}
    for path in sorted(paths):
        classification(path)
        source = (root / path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path, feature_version=(3, 12))
        trees[path] = tree
        found_by_path[path] = symbols(tree)
        source_sizes = source_size_evidence(path, source, found_by_path[path], tree=tree)
        if sizes is not None:
            sizes.update(source_sizes)
        debt.update(size_debt(path, source, found_by_path[path], sizes=source_sizes))
        debt.update(suppression_debt(path, source, found_by_path[path]))
    debt.update(lint_debt(root, found_by_path))
    for kind, graph in zip(("static", "eager"), build_graphs(trees), strict=True):
        for cycle in elementary_cycles(graph):
            debt[f"graph|{kind}_cycle|{' -> '.join(cycle)}"] = 1
    return dict(sorted(debt.items()))
