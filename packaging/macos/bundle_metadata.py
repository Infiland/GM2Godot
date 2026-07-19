from __future__ import annotations

import ast
from pathlib import Path
import re
import stat
from typing import Final


__all__ = ("BUNDLE_IDENTIFIER", "load_release_version", "load_bundle_metadata")

BUNDLE_IDENTIFIER: Final = "land.infi.gm2godot"

_MAX_VERSION_SOURCE_BYTES: Final = 16 * 1024
_RELEASE_VERSION_PATTERN: Final = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_PLACEHOLDER_VERSION: Final = "0.0.0"


class _BundleMetadataPolicyError(ValueError):
    """Raised when the canonical release metadata is unsafe or ambiguous."""


def _read_bounded_utf8(source_root: Path) -> tuple[str, Path]:
    version_path = source_root / "src" / "version.py"
    try:
        file_status = version_path.lstat()
    except OSError as error:
        raise _BundleMetadataPolicyError(f"Cannot inspect canonical version source {version_path}: {error}.") from error

    if stat.S_ISLNK(file_status.st_mode):
        raise _BundleMetadataPolicyError(f"Canonical version source must not be a symbolic link: {version_path}.")
    if not stat.S_ISREG(file_status.st_mode):
        raise _BundleMetadataPolicyError(f"Canonical version source is not a regular file: {version_path}.")
    if file_status.st_size > _MAX_VERSION_SOURCE_BYTES:
        raise _BundleMetadataPolicyError(
            f"Canonical version source exceeds the {_MAX_VERSION_SOURCE_BYTES}-byte limit: {version_path}."
        )

    try:
        with version_path.open("rb") as version_file:
            content = version_file.read(_MAX_VERSION_SOURCE_BYTES + 1)
    except OSError as error:
        raise _BundleMetadataPolicyError(f"Cannot read canonical version source {version_path}: {error}.") from error

    if len(content) > _MAX_VERSION_SOURCE_BYTES:
        raise _BundleMetadataPolicyError(
            f"Canonical version source exceeds the {_MAX_VERSION_SOURCE_BYTES}-byte limit: {version_path}."
        )
    try:
        return content.decode("utf-8"), version_path
    except UnicodeDecodeError as error:
        raise _BundleMetadataPolicyError(f"Canonical version source is not valid UTF-8: {version_path}.") from error


def _is_module_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and type(statement.value.value) is str
    )


def _is_annotations_future(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.ImportFrom)
        and statement.module == "__future__"
        and statement.level == 0
        and len(statement.names) == 1
        and statement.names[0].name == "annotations"
        and statement.names[0].asname is None
    )


def _extract_literal_version(tree: ast.Module, version_path: Path) -> str:
    statements = tree.body
    index = 1 if statements and _is_module_docstring(statements[0]) else 0
    if index < len(statements) and _is_annotations_future(statements[index]):
        index += 1
    maintained = statements[index:]
    if len(maintained) != 2:
        raise _BundleMetadataPolicyError(
            "Canonical version source may only contain an optional module docstring, "
            "an optional annotations future import, VERSION, and get_version: "
            f"{version_path}."
        )

    assignment, getter = maintained
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "VERSION"
        and assignment.type_comment is None
        and isinstance(assignment.value, ast.Constant)
        and type(assignment.value.value) is str
    ):
        raise _BundleMetadataPolicyError(
            f"Canonical VERSION must be one simple top-level literal string assignment: {version_path}."
        )

    arguments = getter.args if isinstance(getter, ast.FunctionDef) else None
    return_annotation = getter.returns if isinstance(getter, ast.FunctionDef) else None
    if not (
        isinstance(getter, ast.FunctionDef)
        and getter.name == "get_version"
        and not getter.decorator_list
        and getter.type_comment is None
        and arguments is not None
        and not arguments.posonlyargs
        and not arguments.args
        and arguments.vararg is None
        and not arguments.kwonlyargs
        and arguments.kwarg is None
        and not arguments.defaults
        and (
            return_annotation is None
            or (
                isinstance(return_annotation, ast.Name)
                and return_annotation.id == "str"
                and isinstance(return_annotation.ctx, ast.Load)
            )
        )
        and len(getter.body) == 1
        and isinstance(getter.body[0], ast.Return)
        and isinstance(getter.body[0].value, ast.Name)
        and getter.body[0].value.id == "VERSION"
        and isinstance(getter.body[0].value.ctx, ast.Load)
    ):
        raise _BundleMetadataPolicyError(
            "Canonical get_version must be undecorated, accept no arguments, optionally "
            f"return str, and only return VERSION: {version_path}."
        )
    return assignment.value.value


def load_release_version(source_root: Path) -> str:
    """Load the canonical release version without importing or executing source code."""

    source, version_path = _read_bounded_utf8(source_root)
    try:
        tree = ast.parse(source, filename=str(version_path), mode="exec", type_comments=True)
    except (SyntaxError, ValueError) as error:
        raise _BundleMetadataPolicyError(
            f"Canonical version source is not valid Python syntax: {version_path}."
        ) from error

    version = _extract_literal_version(tree, version_path)
    if version == _PLACEHOLDER_VERSION or _RELEASE_VERSION_PATTERN.fullmatch(version) is None:
        raise _BundleMetadataPolicyError(
            "Canonical VERSION must be a non-placeholder, canonical three-integer string "
            f"such as '1.2.3'; got {version!r}."
        )
    return version


def load_bundle_metadata(source_root: Path) -> dict[str, str]:
    """Return the exact maintained metadata applied to the macOS app bundle."""

    version = load_release_version(source_root)
    return {
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }
