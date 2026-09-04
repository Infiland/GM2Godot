"""Stdlib-only AST mechanics for the GML transpiler architecture contract.

This module deliberately contains mechanics, not repository policy. The contract
in ``test_gml_transpiler_architecture`` supplies its module cohorts, directions,
and permitted facade exception.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MODULE_IMPORT_NAME = "<module>"
MODULE_METADATA_ATTRIBUTES = frozenset({"__all__", "__file__"})


@dataclass(frozen=True, order=True)
class ImportEdge:
    consumer: str
    owner: str
    name: str


@dataclass(frozen=True, order=True)
class ImportViolation:
    consumer: str
    owner: str
    name: str
    form: str
    line: int


def module_name(path: Path, project_root: Path) -> str:
    """Return the importable module name for a Python path below ``project_root``."""
    parts = list(path.relative_to(project_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def iter_python_paths(*roots: Path) -> tuple[Path, ...]:
    """Return all Python source paths under the supplied roots in deterministic order."""
    return tuple(path for root in roots for path in sorted(root.rglob("*.py")))


def resolve_import_owner(
    consumer: str,
    node: ast.ImportFrom,
    *,
    package_module: bool,
) -> str:
    """Resolve one absolute or relative ``from`` import to its owner module."""
    if node.level == 0:
        return node.module or ""
    package_parts = consumer.split(".") if package_module else consumer.split(".")[:-1]
    parent_hops = node.level - 1
    if parent_hops > len(package_parts):
        raise ValueError(f"Relative import escapes package in {consumer}:{node.lineno}")
    owner_parts = package_parts[: len(package_parts) - parent_hops]
    if node.module:
        owner_parts.extend(node.module.split("."))
    return ".".join(owner_parts)


def import_edges_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    """Extract import edges using imported original names rather than local aliases."""
    edges: set[ImportEdge] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            owner = resolve_import_owner(consumer, node, package_module=package_module)
            if owner != consumer:
                edges.update(ImportEdge(consumer, owner, item.name) for item in node.names)
        elif isinstance(node, ast.Import):
            edges.update(
                ImportEdge(consumer, item.name, MODULE_IMPORT_NAME) for item in node.names
            )
    return frozenset(edges)
def top_level_import_edges_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    """Extract only module-level import edges."""
    edges: set[ImportEdge] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom):
            owner = resolve_import_owner(consumer, node, package_module=package_module)
            if owner != consumer:
                edges.update(ImportEdge(consumer, owner, item.name) for item in node.names)
        elif isinstance(node, ast.Import):
            edges.update(
                ImportEdge(consumer, item.name, MODULE_IMPORT_NAME) for item in node.names
            )
    return frozenset(edges)


def structural_import_violations(
    source: str,
    consumer: str,
    *,
    governed_modules: frozenset[str],
    module_object_exceptions: Mapping[str, frozenset[str]],
    package_module: bool = False,
) -> frozenset[ImportViolation]:
    """Find forbidden GML-module import and reflection forms without name flow analysis.

    The contract forbids the structural import or literal module access itself.
    This intentionally walks every scope rather than simulating assignments,
    branches, classes, functions, comprehensions, ``try``, or ``match``.
    """
    tree = ast.parse(source)
    exceptions = module_object_exceptions.get(consumer, frozenset())
    violations = _import_violations(
        tree,
        consumer,
        governed_modules,
        exceptions,
        package_module=package_module,
    )
    bindings = _module_bindings(
        tree,
        consumer,
        governed_modules,
        package_module=package_module,
    )
    violations.update(
        _attribute_violations(tree, consumer, bindings, governed_modules, exceptions)
    )
    violations.update(_reflection_violations(tree, consumer, bindings, governed_modules))
    violations.update(_dynamic_import_violations(tree, consumer, governed_modules))
    return frozenset(violations)


def _import_violations(
    tree: ast.Module,
    consumer: str,
    governed_modules: frozenset[str],
    exceptions: frozenset[str],
    *,
    package_module: bool,
) -> set[ImportViolation]:
    violations: set[ImportViolation] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.update(
                _direct_module_import_violations(
                    consumer,
                    node,
                    governed_modules,
                    exceptions,
                )
            )
        elif isinstance(node, ast.ImportFrom):
            violations.update(
                _from_import_violations(
                    consumer,
                    node,
                    governed_modules,
                    exceptions,
                    package_module=package_module,
                )
            )
    return violations


def _direct_module_import_violations(
    consumer: str,
    node: ast.Import,
    governed_modules: frozenset[str],
    exceptions: frozenset[str],
) -> set[ImportViolation]:
    violations: set[ImportViolation] = set()
    for item in node.names:
        private_owner, private_name = _private_module_part(item.name, governed_modules)
        if private_name is not None:
            violations.add(
                ImportViolation(consumer, private_owner, private_name, "module-import", node.lineno)
            )
        if _is_governed_module(item.name, governed_modules) and item.name not in exceptions:
            violations.add(
                ImportViolation(consumer, item.name, MODULE_IMPORT_NAME, "module-import", node.lineno)
            )
    return violations


def _from_import_violations(
    consumer: str,
    node: ast.ImportFrom,
    governed_modules: frozenset[str],
    exceptions: frozenset[str],
    *,
    package_module: bool,
) -> set[ImportViolation]:
    owner = resolve_import_owner(consumer, node, package_module=package_module)
    if owner == consumer:
        return set()
    violations: set[ImportViolation] = set()
    private_owner, private_name = _private_module_part(owner, governed_modules)
    if private_name is not None:
        violations.add(
            ImportViolation(consumer, private_owner, private_name, "module-import", node.lineno)
        )
    owner_is_surface = _is_surface_module(owner, governed_modules)
    for item in node.names:
        candidate = f"{owner}.{item.name}" if owner else item.name
        if owner_is_surface and item.name == "*":
            violations.add(ImportViolation(consumer, owner, item.name, "star-import", node.lineno))
        elif owner_is_surface and item.name.startswith("_"):
            violations.add(ImportViolation(consumer, owner, item.name, "from-import", node.lineno))
        elif _is_governed_module(candidate, governed_modules) and candidate not in exceptions:
            violations.add(
                ImportViolation(consumer, candidate, MODULE_IMPORT_NAME, "module-import", node.lineno)
            )
    return violations


def _module_bindings(
    tree: ast.Module,
    consumer: str,
    governed_modules: frozenset[str],
    *,
    package_module: bool,
) -> dict[str, frozenset[str]]:
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".")[0]
                owner = item.name if item.asname else item.name.split(".")[0]
                _add_binding(bindings, bound, owner, governed_modules)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        owner = resolve_import_owner(consumer, node, package_module=package_module)
        for item in node.names:
            if item.name == "*":
                continue
            bound = item.asname or item.name
            candidate = f"{owner}.{item.name}" if owner else item.name
            _add_binding(bindings, bound, candidate, governed_modules)
    return {name: frozenset(owners) for name, owners in bindings.items()}


def _add_binding(
    bindings: dict[str, set[str]],
    name: str,
    owner: str,
    governed_modules: frozenset[str],
) -> None:
    if _is_surface_module(owner, governed_modules) or _is_governed_ancestor(
        owner,
        governed_modules,
    ):
        bindings.setdefault(name, set()).add(owner)


def _attribute_violations(
    tree: ast.Module,
    consumer: str,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
    exceptions: frozenset[str],
) -> set[ImportViolation]:
    violations: set[ImportViolation] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            for owner, name in _resolve_module_accesses(node, bindings, governed_modules):
                if owner not in exceptions or _is_private_name(name):
                    violations.add(
                        ImportViolation(consumer, owner, name, "module-attribute", node.lineno)
                    )
    return violations


def _resolve_module_accesses(
    node: ast.expr,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
) -> frozenset[tuple[str, str]]:
    parts = _attribute_parts(node)
    if parts is None:
        return frozenset()
    accesses: set[tuple[str, str]] = set()
    for imported_owner in bindings.get(parts[0], frozenset()):
        accesses.update(_accesses_from_parts(imported_owner, parts[1:], governed_modules))
    return frozenset(accesses)


def _attribute_parts(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if not isinstance(node, ast.Attribute):
        return None
    parent = _attribute_parts(node.value)
    return None if parent is None else (*parent, node.attr)


def _accesses_from_parts(
    imported_owner: str,
    parts: tuple[str, ...],
    governed_modules: frozenset[str],
) -> set[tuple[str, str]]:
    accesses: set[tuple[str, str]] = set()
    owner = imported_owner
    if owner in governed_modules:
        accesses.add((owner, parts[0] if parts else MODULE_IMPORT_NAME))
    for index, part in enumerate(parts):
        owner = f"{owner}.{part}"
        if owner in governed_modules:
            name = parts[index + 1] if index + 1 < len(parts) else MODULE_IMPORT_NAME
            accesses.add((owner, name))
    return accesses


def _reflection_violations(
    tree: ast.Module,
    consumer: str,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
) -> set[ImportViolation]:
    violations: set[ImportViolation] = set()
    getattr_callables = _getattr_callable_names(tree)
    vars_callables = _vars_callable_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            violations.update(
                _getattr_violations(
                    node,
                    consumer,
                    bindings,
                    governed_modules,
                    getattr_callables,
                )
            )
        if isinstance(node, ast.Subscript):
            violations.update(
                _subscript_violations(
                    node,
                    consumer,
                    bindings,
                    governed_modules,
                    vars_callables,
                )
            )
    return violations


def _getattr_violations(
    node: ast.Call,
    consumer: str,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
    getattr_callables: frozenset[str],
) -> set[ImportViolation]:
    if not _is_getattr_call(node.func, getattr_callables) or len(node.args) < 2:
        return set()
    name = literal_string(node.args[1])
    if name is None or not _is_private_name(name):
        return set()
    return {
        ImportViolation(consumer, owner, name, "getattr", node.lineno)
        for owner in _resolved_module_owners(node.args[0], bindings, governed_modules)
    }


def _getattr_callable_names(tree: ast.Module) -> frozenset[str]:
    names = {"getattr"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "builtins":
            continue
        for item in node.names:
            if item.name == "getattr":
                names.add(item.asname or item.name)
    return frozenset(names)


def _vars_callable_names(tree: ast.Module) -> frozenset[str]:
    names = {"vars"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "builtins":
            continue
        for item in node.names:
            if item.name == "vars":
                names.add(item.asname or item.name)
    return frozenset(names)
def _is_getattr_call(node: ast.expr, names: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Name) and node.id in names
    ) or (
        isinstance(node, ast.Attribute) and node.attr == "getattr"
    )


def _is_vars_call(node: ast.expr, names: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Name) and node.id in names
    ) or (
        isinstance(node, ast.Attribute) and node.attr == "vars"
    )
def _subscript_violations(
    node: ast.Subscript,
    consumer: str,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
    vars_callables: frozenset[str],
) -> set[ImportViolation]:
    name = literal_string(node.slice)
    if name is None or not _is_private_name(name):
        return set()
    owners = _subscript_module_owners(
        node.value,
        bindings,
        governed_modules,
        vars_callables,
    )
    return {
        ImportViolation(consumer, owner, name, "module-dict", node.lineno)
        for owner in owners
    }


def _subscript_module_owners(
    value: ast.expr,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
    vars_callables: frozenset[str],
) -> frozenset[str]:
    if isinstance(value, ast.Call) and _is_vars_call(value.func, vars_callables) and value.args:
        return _resolved_module_owners(value.args[0], bindings, governed_modules)
    if isinstance(value, ast.Attribute) and value.attr == "__dict__":
        return _resolved_module_owners(value.value, bindings, governed_modules)
    return frozenset()


def _resolved_module_owners(
    node: ast.expr,
    bindings: Mapping[str, frozenset[str]],
    governed_modules: frozenset[str],
) -> frozenset[str]:
    owners = {
        owner
        for owner, name in _resolve_module_accesses(node, bindings, governed_modules)
        if name == MODULE_IMPORT_NAME
    }
    if isinstance(node, ast.Name):
        owners.update(owner for owner in bindings.get(node.id, frozenset()) if owner in governed_modules)
    return frozenset(owners)


def _dynamic_import_violations(
    tree: ast.Module,
    consumer: str,
    governed_modules: frozenset[str],
) -> set[ImportViolation]:
    violations: set[ImportViolation] = set()
    imported_callables = _dynamic_import_callable_names(tree)
    getattr_callables = _getattr_callable_names(tree)
    vars_callables = _vars_callable_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_dynamic_import_call(
            node.func,
            imported_callables,
            getattr_callables,
            vars_callables,
        ):
            continue
        target = _dynamic_import_target(node)
        if target is not None and _is_surface_module(target, governed_modules):
            violations.add(
                ImportViolation(consumer, target, MODULE_IMPORT_NAME, "dynamic-import", node.lineno)
            )
    return violations


def _dynamic_import_callable_names(tree: ast.Module) -> frozenset[str]:
    names = {"__import__"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in {"importlib", "builtins"}:
            continue
        for item in node.names:
            if item.name in {"import_module", "__import__"}:
                names.add(item.asname or item.name)
    return frozenset(names)


def _is_dynamic_import_call(
    node: ast.expr,
    imported_callables: frozenset[str],
    getattr_callables: frozenset[str],
    vars_callables: frozenset[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in imported_callables
    if isinstance(node, ast.Attribute):
        return node.attr in {"import_module", "__import__"}
    if isinstance(node, ast.Subscript):
        return _is_dynamic_import_subscript(node, vars_callables)
    return (
        isinstance(node, ast.Call)
        and _is_getattr_call(node.func, getattr_callables)
        and len(node.args) >= 2
        and literal_string(node.args[1]) in {"import_module", "__import__"}
    )


def _is_dynamic_import_subscript(
    node: ast.Subscript,
    vars_callables: frozenset[str],
) -> bool:
    if literal_string(node.slice) not in {"import_module", "__import__"}:
        return False
    if isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__":
        return True
    return (
        isinstance(node.value, ast.Call)
        and _is_vars_call(node.value.func, vars_callables)
        and bool(node.value.args)
    )


def _dynamic_import_target(node: ast.Call) -> str | None:
    if node.args:
        return literal_string(node.args[0])
    return next(
        (literal_string(keyword.value) for keyword in node.keywords if keyword.arg == "name"),
        None,
    )


def literal_string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_private_name(name: str) -> bool:
    return (
        name.startswith("_")
        and not name.startswith("__")
        and name not in MODULE_METADATA_ATTRIBUTES
    )


def _is_governed_module(name: str, governed_modules: frozenset[str]) -> bool:
    return name in governed_modules


def _is_surface_module(name: str, governed_modules: frozenset[str]) -> bool:
    return any(name == owner or name.startswith(f"{owner}.") for owner in governed_modules)


def _is_governed_ancestor(name: str, governed_modules: frozenset[str]) -> bool:
    return any(owner.startswith(f"{name}.") for owner in governed_modules)


def _private_module_part(
    name: str,
    governed_modules: frozenset[str],
) -> tuple[str, str | None]:
    for owner in governed_modules:
        if name == owner or not name.startswith(f"{owner}."):
            continue
        part = name[len(owner) + 1 :].split(".")[0]
        if part.startswith("_"):
            return owner, part
    return name, None
