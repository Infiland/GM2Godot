"""Check exact facade import whitelists and static public export declarations."""

from __future__ import annotations

import ast

from tests.gml_transpiler_architecture_support import (
    ImportEdge,
    literal_string,
    resolve_import_owner,
)


def literal_all_exports(source: str) -> tuple[str, ...]:
    """Return one literal-list ``__all__`` and reject every static mutation form."""
    tree = ast.parse(source)
    declaration = _single_static_all_declaration(tree)
    if not isinstance(declaration, ast.Assign) or not isinstance(declaration.value, ast.List):
        raise ValueError("__all__ must be a literal list")
    _reject_all_mutations(tree, declaration)
    return _literal_string_sequence(declaration.value)


def static_all_exports(source: str) -> tuple[str, ...]:
    """Return one literal list or tuple ``__all__`` without importing its module."""
    tree = ast.parse(source)
    declaration = _single_static_all_declaration(tree)
    if not isinstance(declaration.value, (ast.List, ast.Tuple)):
        raise ValueError("__all__ must be a literal list or tuple")
    _reject_all_mutations(tree, declaration)
    return _literal_string_sequence(declaration.value)


def facade_reexports_from_source(
    source: str,
    facade_module: str,
    *,
    allowed_owner_prefix: str | None = None,
) -> frozenset[ImportEdge]:
    """Extract direct facade reexports under the caller-supplied owner policy."""
    tree = ast.parse(source)
    declaration = _single_static_all_declaration(tree)
    if not isinstance(declaration, ast.Assign) or not isinstance(declaration.value, ast.List):
        raise ValueError("Facade __all__ must be a literal list")
    _reject_all_mutations(tree, declaration)
    edges: set[ImportEdge] = set()
    future_imports = 0
    for node in tree.body:
        if node is declaration:
            continue
        if not isinstance(node, ast.ImportFrom):
            raise ValueError("Facade may contain only direct from-imports and literal __all__")
        owner = resolve_import_owner(facade_module, node, package_module=False)
        if owner == "__future__":
            _validate_future_annotations(node)
            future_imports += 1
            continue
        if allowed_owner_prefix is not None and not (
            owner == allowed_owner_prefix or owner.startswith(f"{allowed_owner_prefix}.")
        ):
            raise ValueError(f"Unexpected facade import owner: {owner}")
        _add_facade_import_edges(edges, facade_module, owner, node)
    _reject_nested_facade_imports(tree)
    if future_imports != 1:
        raise ValueError("Facade import preamble must be exactly future annotations")
    return frozenset(edges)


def _single_static_all_declaration(tree: ast.Module) -> ast.Assign | ast.AnnAssign:
    declarations = [node for node in tree.body if _is_all_declaration(node)]
    if len(declarations) != 1:
        raise ValueError("__all__ must have exactly one static declaration")
    declaration = declarations[0]
    assert isinstance(declaration, (ast.Assign, ast.AnnAssign))
    return declaration


def _is_all_declaration(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        return (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
        )
    return isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__"


def _literal_string_sequence(value: ast.List | ast.Tuple) -> tuple[str, ...]:
    exports: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            raise ValueError("__all__ entries must be literal strings")
        exports.append(element.value)
    if len(exports) != len(set(exports)):
        raise ValueError("__all__ entries must be unique")
    if any(name.startswith("_") for name in exports):
        raise ValueError("__all__ cannot export private names")
    return tuple(exports)


def _reject_all_mutations(
    tree: ast.Module,
    declaration: ast.Assign | ast.AnnAssign,
) -> None:
    for node in ast.walk(tree):
        if node is declaration:
            continue
        if _mutates_all(node):
            raise ValueError("__all__ must not be rebound or mutated")


def _mutates_all(node: ast.AST) -> bool:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        return any(_is_all_target(target) for target in _assignment_targets(node))
    if isinstance(node, ast.Delete):
        return any(_is_all_target(target) for target in node.targets)
    return isinstance(node, ast.Call) and _is_all_mutation_call(node)


def _assignment_targets(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr,
) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _is_all_target(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "__all__"
    return _is_all_subscript_target(node)


def _is_all_subscript_target(node: ast.expr) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    if isinstance(node.value, ast.Name) and node.value.id == "__all__":
        return True
    return isinstance(node.slice, ast.Constant) and node.slice.value == "__all__"


def _is_all_mutation_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        if node.func.value.id == "__all__":
            return True
    return _is_all_setitem_call(node) or _call_mentions_all_key(node)


def _is_all_setitem_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "__setitem__"
        and bool(node.args)
        and literal_string(node.args[0]) == "__all__"
    )


def _call_mentions_all_key(node: ast.Call) -> bool:
    if any(keyword.arg == "__all__" for keyword in node.keywords):
        return True
    return any(_is_all_mapping_literal(argument) for argument in node.args)


def _is_all_mapping_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "__all__" for key in node.keys
    )


def _validate_future_annotations(node: ast.ImportFrom) -> None:
    if [(item.name, item.asname) for item in node.names] != [("annotations", None)]:
        raise ValueError("Facade can import only future annotations")


def _add_facade_import_edges(
    edges: set[ImportEdge],
    facade_module: str,
    owner: str,
    node: ast.ImportFrom,
) -> None:
    if not owner:
        raise ValueError("Facade import owner must be explicit")
    for item in node.names:
        if item.name == "*" or item.asname != item.name:
            raise ValueError(f"Facade reexport must be explicit: {owner}.{item.name}")
        edge = ImportEdge(facade_module, owner, item.name)
        if edge in edges:
            raise ValueError(f"Duplicate facade reexport: {owner}.{item.name}")
        edges.add(edge)


def _reject_nested_facade_imports(tree: ast.Module) -> None:
    top_level = set(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in top_level:
            raise ValueError("Facade imports must be module-level")
