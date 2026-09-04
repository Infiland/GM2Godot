"""Small formatting-independent size evidence for the maintainability ratchet."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SizeEvidence:
    lines: int
    structure: int
    ast_sha256: str


def _entry_units(node: ast.AST) -> int:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts)
    if isinstance(node, ast.Dict):
        return len(node.keys)
    if isinstance(node, ast.Call):
        return len(node.args) + len(node.keywords)
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.Compare):
        return len(node.ops)
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        return max(0, len(node.value.splitlines()) - 1)
    if isinstance(node, ast.expr) and not isinstance(node, (ast.Name, ast.Constant)):
        return 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    return 0


def structural_units(node: ast.AST) -> int:
    """Count statements, entries and operations independently of wrapping."""
    return sum(isinstance(child, ast.stmt) + _entry_units(child) for child in ast.walk(node))


def evidence_for_nodes(nodes: Iterable[ast.AST], lines: int) -> SizeEvidence:
    owners = tuple(nodes)
    normalized = "\n".join(ast.dump(node, include_attributes=False) for node in owners)
    return SizeEvidence(
        lines,
        sum(structural_units(node) for node in owners),
        hashlib.sha256(normalized.encode()).hexdigest(),
    )
