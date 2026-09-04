"""Syntax-only import graphs; inspection never imports application modules."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import PurePosixPath

Graph = dict[str, set[str]]


def module_names(path: str) -> tuple[str, ...]:
    name = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
    name = name.removesuffix(".__init__")
    return (name, name.removeprefix("src.")) if name.startswith("src.") else (name,)


def import_targets(node: ast.AST, package: str) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        name = "." * node.level + (node.module or "")
        if node.level:
            name = importlib.util.resolve_name(name, package)
        return (name, *(f"{name}.{alias.name}" for alias in node.names))
    return ()


def dynamic_imports(tree: ast.AST) -> dict[str, str]:
    """Recognize literal calls through syntactically declared import aliases."""
    aliases = {"__import__": "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(
                {
                    f"{alias.asname or alias.name}.import_module": "import_module"
                    for alias in node.names
                    if alias.name == "importlib"
                }
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            aliases.update(
                {alias.asname or alias.name: "import_module" for alias in node.names if alias.name == "import_module"}
            )
    return aliases


def literal_import(node: ast.AST, aliases: dict[str, str], package: str) -> tuple[str, ...]:
    if not isinstance(node, ast.Call) or ast.unparse(node.func) not in aliases:
        return ()
    arguments = {keyword.arg: keyword.value for keyword in node.keywords}
    name = node.args[0] if node.args else arguments.get("name")
    if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
        return ()
    target = name.value
    if target.startswith("."):
        package_arg = node.args[1] if len(node.args) > 1 else arguments.get("package")
        if isinstance(package_arg, ast.Constant) and isinstance(package_arg.value, str):
            package = package_arg.value
        target = importlib.util.resolve_name(target, package)
    return (target,)


def type_checking_names(tree: ast.Module) -> set[str]:
    """Only explicit typing imports mark type-only guards, including aliases."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                f"{alias.asname or alias.name}.TYPE_CHECKING" for alias in node.names if alias.name == "typing"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "typing":
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "TYPE_CHECKING")
    return names


def type_only_child(node: ast.AST, child: ast.AST, names: set[str]) -> bool:
    if not isinstance(node, ast.If):
        return False
    if isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
        return ast.unparse(node.test.operand) in names and child in node.orelse
    return ast.unparse(node.test) in names and child in node.body


def target_owners(target: str, owners: dict[str, str]) -> set[str]:
    """Dotted imports execute each real package initializer on the way in."""
    paths: set[str] = set()
    parts = target.split(".")
    for length in range(1, len(parts) + 1):
        path = owners.get(".".join(parts[:length]))
        if path is not None and (length == len(parts) or "/__init__." in path):
            paths.add(path)
    return paths


def build_graphs(trees: dict[str, ast.Module]) -> tuple[Graph, Graph]:
    owners = {name: path for path in trees for name in module_names(path)}
    static: Graph = {path: set() for path in trees}
    eager: Graph = {path: set() for path in trees}
    for path, tree in trees.items():
        for target, executes in module_edges(path, tree):
            for owner in target_owners(target, owners) - {path}:
                static[path].add(owner)
                if executes:
                    eager[path].add(owner)
    return static, eager


def module_edges(path: str, tree: ast.Module) -> list[tuple[str, bool]]:
    name = module_names(path)[0]
    package = name if path.endswith("/__init__.py") else name.rpartition(".")[0]
    aliases = dynamic_imports(tree)
    type_guards = type_checking_names(tree)
    edges: list[tuple[str, bool]] = []
    pending: list[tuple[ast.AST, bool]] = [(tree, True)]
    while pending:
        node, executes = pending.pop()
        targets = import_targets(node, package) + literal_import(node, aliases, package)
        edges.extend((target, executes) for target in targets)
        deferred = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        for child in ast.iter_child_nodes(node):
            body = getattr(node, "body", ())
            in_body = child is body if isinstance(body, ast.AST) else child in body
            type_only = type_only_child(node, child, type_guards)
            pending.append((child, executes and not (deferred and in_body or type_only)))
    return edges


def strongly_connected_components(graph: Graph) -> list[tuple[str, ...]]:
    """Iterative Kosaraju traversal, including self-cycles in fixture graphs."""
    seen: set[str] = set()
    order: list[str] = []
    reverse: Graph = {name: set() for name in graph}
    for name, targets in graph.items():
        for target in targets:
            reverse[target].add(name)
    for name in sorted(graph):
        pending = [(name, False)]
        while pending:
            current, finished = pending.pop()
            if finished:
                order.append(current)
            elif current not in seen:
                seen.add(current)
                pending.append((current, True))
                pending.extend((target, False) for target in sorted(graph[current]))
    seen.clear()
    components: list[tuple[str, ...]] = []
    for name in reversed(order):
        component: set[str] = set()
        pending_names = [name]
        while pending_names:
            current = pending_names.pop()
            if current not in seen:
                seen.add(current)
                component.add(current)
                pending_names.extend(reverse[current])
        if len(component) > 1 or name in graph[name]:
            components.append(tuple(sorted(component)))
    return sorted(components)


def elementary_cycles(graph: Graph) -> list[tuple[str, ...]]:
    """Enumerate directed simple cycles once, starting at their smallest path."""
    cycles: list[tuple[str, ...]] = []
    for component in strongly_connected_components(graph):
        members = set(component)
        for start in component:
            cycles.extend(cycles_from(graph, members, start))
    return sorted(cycles)


def cycles_from(graph: Graph, members: set[str], start: str) -> list[tuple[str, ...]]:
    cycles: list[tuple[str, ...]] = []
    pending: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
    while pending:
        current, trail = pending.pop()
        for target in sorted(graph[current] & members):
            if target == start:
                cycles.append(trail)
            elif target > start and target not in trail:
                pending.append((target, (*trail, target)))
    return cycles
