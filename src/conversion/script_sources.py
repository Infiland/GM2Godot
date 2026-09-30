"""Contained script sidecars with caller-specific entry and reporting policies."""

from __future__ import annotations

import os
import posixpath
from collections.abc import Callable
from dataclasses import replace

from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    is_safe_project_source_component,
    resolve_project_sidecar_source_path,
)
from src.conversion.script_model import ScriptModel, dependency_script_names

ScriptPathResolver = Callable[[str, str | None, str], ResolvedProjectSourcePath | None]
ScriptRejectionReporter = Callable[[str, ProjectSourcePathError, str | None, str], None]


def conversion_script_source(
    name: str, source_path: str, *, resolve: ScriptPathResolver,
    discover: ScriptPathResolver, report: ScriptRejectionReporter,
) -> str | None:
    yy_source = _conversion_yy_source(source_path, resolve, report)
    if yy_source is None:
        return None
    return _named_script_source(
        name, yy_source, "must be exactly one safe path component", resolve, discover, report,
    )


def registry_script_source(
    model: ScriptModel, *, resolve: ScriptPathResolver,
    discover: ScriptPathResolver, report: ScriptRejectionReporter,
) -> ScriptModel:
    yy_source = resolve(model.yyp_path, None, "script .yy")
    source_path = None
    if yy_source is not None and os.path.isfile(yy_source.filesystem_path):
        source_path = _named_script_source(
            model.name, yy_source, "must identify exactly one path component", resolve, discover, report,
        )
    return replace(model, gml_path=source_path)


def _conversion_yy_source(
    source_path: str, resolve: ScriptPathResolver, report: ScriptRejectionReporter,
) -> ResolvedProjectSourcePath | None:
    resolved = resolve(source_path, None, "script .yy")
    if resolved is None:
        return None
    normalized_source_path = resolved.source_path.casefold()
    if not (normalized_source_path.startswith("scripts/") and normalized_source_path.endswith(".yy")):
        report(
            source_path,
            ProjectSourcePathError(
                "GameMaker script reference must name a .yy file under scripts/: "
                f"{source_path!r}"
            ),
            None, "script .yy",
        )
        return None
    if not os.path.isfile(resolved.filesystem_path):
        return None
    return resolved


def _named_script_source(
    name: str, yy_source: ResolvedProjectSourcePath, unsafe_message: str,
    resolve: ScriptPathResolver, discover: ScriptPathResolver, report: ScriptRejectionReporter,
) -> str | None:
    script_directory = discover(
        os.path.dirname(yy_source.filesystem_path), yy_source.source_path, "script source directory",
    )
    if script_directory is None or not os.path.isdir(script_directory.filesystem_path):
        return None
    preferred, excluded = _preferred_script_source(name, yy_source, unsafe_message, resolve, report)
    if preferred is not None:
        return preferred
    return _fallback_script_source(yy_source, script_directory, excluded, discover)


def _preferred_script_source(
    name: str, yy_source: ResolvedProjectSourcePath, unsafe_message: str,
    resolve: ScriptPathResolver, report: ScriptRejectionReporter,
) -> tuple[str | None, set[str]]:
    preferred_filename = name + ".gml"
    excluded_filenames = {preferred_filename}
    preferred_source = None
    if is_safe_project_source_component(name):
        preferred_source = resolve(preferred_filename, yy_source.source_path, "preferred script source")
    else:
        normalized_preferred_filename = posixpath.basename(
            posixpath.normpath(preferred_filename.replace("\\", "/"))
        )
        if normalized_preferred_filename:
            excluded_filenames.add(normalized_preferred_filename)
        report(
            preferred_filename,
            ProjectSourcePathError(
                "GameMaker script resource names used to derive source "
                f"filenames {unsafe_message}: {name!r}"
            ),
            yy_source.source_path, "preferred script source",
        )
    if preferred_source is not None:
        owner_directory = posixpath.dirname(yy_source.source_path)
        preferred_directory = posixpath.dirname(preferred_source.source_path)
        if preferred_directory != owner_directory:
            report(
                preferred_filename,
                ProjectSourcePathError(
                    "GameMaker script source derived from the resource name "
                    "must be next to its script .yy owner: "
                    f"{preferred_filename!r}"
                ),
                yy_source.source_path, "preferred script source",
            )
        elif os.path.isfile(preferred_source.filesystem_path):
            return preferred_source.filesystem_path, excluded_filenames
    return None, excluded_filenames


def _fallback_script_source(
    yy_source: ResolvedProjectSourcePath,
    script_directory: ResolvedProjectSourcePath, excluded_filenames: set[str],
    discover: ScriptPathResolver,
) -> str | None:
    try:
        filenames = sorted(os.listdir(script_directory.filesystem_path))
    except OSError:
        return None
    for filename in filenames:
        if not filename.endswith(".gml"):
            continue
        if filename in excluded_filenames:
            continue
        discovered_source = discover(
            os.path.join(script_directory.filesystem_path, filename),
            yy_source.source_path, "discovered script source",
        )
        if discovered_source is None or not os.path.isfile(discovered_source.filesystem_path):
            continue
        return discovered_source.filesystem_path
    return None


def dependency_script_source(
    project_root: str, model: ScriptModel, resolved_resource: ResolvedProjectSourcePath,
) -> str:
    resource_directory = posixpath.dirname(resolved_resource.source_path)
    for name in dependency_script_names(model):
        if not is_safe_project_source_component(name):
            continue
        try:
            resolved_candidate = resolve_project_sidecar_source_path(
                project_root, resolved_resource.source_path, f"{name}.gml",
            )
        except ProjectSourcePathError:
            continue
        if (
            posixpath.dirname(resolved_candidate.source_path) == resource_directory
            and os.path.isfile(resolved_candidate.filesystem_path)
        ):
            return resolved_candidate.source_path
    return ""
