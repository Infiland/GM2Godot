from __future__ import annotations

import ntpath
import os
import posixpath
from dataclasses import dataclass

from src.conversion.type_defs import StrPath


class ProjectSourcePathError(ValueError):
    """Raised when a YYP source path cannot be confined to its project root."""


@dataclass(frozen=True)
class ResolvedProjectSourcePath:
    """Contained filesystem path and normalized GameMaker project-relative path."""

    filesystem_path: str
    source_path: str
    project_root: str = ""


_PROJECT_ROOT_SOURCE_DIRECTORIES = frozenset(
    {
        "animcurves",
        "audiogroups",
        "configs",
        "datafiles",
        "extensions",
        "fonts",
        "folders",
        "materials",
        "notes",
        "objects",
        "options",
        "particles",
        "particlesystems",
        "paths",
        "rooms",
        "scripts",
        "sequences",
        "shaders",
        "sounds",
        "sprites",
        "texturegroups",
        "tilesets",
        "timelines",
    }
)
_PROJECT_DIRECTORY_PLACEHOLDER = "${project_dir}"


def is_safe_project_source_component(value: str) -> bool:
    """Return whether a metadata value can name exactly one path component."""
    drive, _tail = ntpath.splitdrive(value)
    return (
        bool(value)
        and value not in {".", ".."}
        and not drive
        and "/" not in value
        and "\\" not in value
        and "\0" not in value
    )


def resolve_project_source_path(
    project_root: StrPath,
    source_path: str,
) -> ResolvedProjectSourcePath:
    """Resolve a YYP path without allowing absolute or project-escaping paths.

    GameMaker project files use forward-slash relative paths, including when the
    project was authored on Windows. Backslashes are accepted for compatibility,
    then the stored source path is normalized to GameMaker's portable form.
    """
    normalized_path = _normalize_relative_source_path(
        source_path,
        description="YYP resource path",
    )

    root_text: str = os.fspath(project_root)
    project_root_path: str = os.path.abspath(root_text)
    filesystem_path = os.path.normpath(
        os.path.join(project_root_path, *normalized_path.split("/"))
    )
    canonical_root = os.path.realpath(project_root_path)
    canonical_path = os.path.realpath(filesystem_path)
    try:
        common_path = os.path.commonpath((canonical_root, canonical_path))
    except ValueError as exc:
        raise ProjectSourcePathError(
            "YYP resource path is on a different filesystem root than the "
            f"selected GameMaker project: {source_path!r}"
        ) from exc

    if os.path.normcase(common_path) != os.path.normcase(canonical_root):
        raise ProjectSourcePathError(
            "YYP resource path escapes the selected GameMaker project root "
            f"through traversal or a symbolic link: {source_path!r}"
        )

    return ResolvedProjectSourcePath(
        filesystem_path=filesystem_path,
        source_path=normalized_path,
        project_root=project_root_path,
    )


def validate_project_resource_source_path(
    resolved_source: ResolvedProjectSourcePath,
    declared_kind: str,
) -> ResolvedProjectSourcePath:
    """Require resolved resource metadata to remain a ``.yy`` in its kind.

    A manifest path such as ``scripts/../objects/o_test/o_test.yy`` is still
    contained by the project root, but normalization changes which resource
    family owns it. Keep benign same-family normalization while rejecting that
    cross-family reinterpretation and non-``.yy`` resource entries.
    """
    normalized_kind = declared_kind.replace("\\", "/").strip("/").casefold()
    source_kind, separator, _remainder = resolved_source.source_path.partition("/")
    if (
        not normalized_kind
        or "/" in normalized_kind
        or not separator
        or source_kind.casefold() != normalized_kind
    ):
        raise ProjectSourcePathError(
            "Resolved GameMaker resource path must remain under its declared "
            f"{declared_kind!r} resource directory after normalization: "
            f"{resolved_source.source_path!r}"
        )
    if not resolved_source.source_path.casefold().endswith(".yy"):
        raise ProjectSourcePathError(
            "Resolved GameMaker resource path must name a .yy metadata file: "
            f"{resolved_source.source_path!r}"
        )

    project_root = resolved_source.project_root
    if not project_root:
        project_root = resolved_source.filesystem_path
        for _segment in resolved_source.source_path.split("/"):
            project_root = os.path.dirname(project_root)
    canonical_root = os.path.realpath(project_root)
    canonical_path = os.path.realpath(resolved_source.filesystem_path)
    try:
        canonical_relative = os.path.relpath(
            canonical_path,
            canonical_root,
        ).replace(os.sep, "/")
    except ValueError as exc:
        raise ProjectSourcePathError(
            "Resolved GameMaker resource target is on a different filesystem "
            f"root: {resolved_source.source_path!r}"
        ) from exc
    canonical_kind, canonical_separator, _canonical_remainder = (
        canonical_relative.partition("/")
    )
    if (
        not canonical_separator
        or canonical_kind.casefold() != normalized_kind
    ):
        raise ProjectSourcePathError(
            "Resolved GameMaker resource target must remain under its declared "
            f"{declared_kind!r} resource directory after symbolic-link "
            f"resolution: {canonical_relative!r}"
        )
    if not canonical_relative.casefold().endswith(".yy"):
        raise ProjectSourcePathError(
            "Resolved GameMaker resource target must remain a .yy metadata "
            f"file after symbolic-link resolution: {canonical_relative!r}"
        )
    return resolved_source


def resolve_project_filesystem_source_path(
    project_root: StrPath,
    filesystem_path: StrPath,
) -> ResolvedProjectSourcePath:
    """Revalidate a discovered filesystem candidate against the project root.

    Disk fallback scans must call this before reading, copying, or inspecting a
    candidate that may be a file or directory symlink.
    """
    root_text = os.fspath(project_root)
    candidate_text = os.fspath(filesystem_path)
    if not candidate_text or "\0" in candidate_text:
        raise ProjectSourcePathError(
            f"Discovered GameMaker source path is empty or invalid: {candidate_text!r}"
        )
    project_root_path = os.path.abspath(root_text)
    candidate_path = (
        os.path.abspath(candidate_text)
        if os.path.isabs(candidate_text)
        else os.path.abspath(os.path.join(project_root_path, candidate_text))
    )
    try:
        relative_path = os.path.relpath(candidate_path, project_root_path)
    except ValueError as exc:
        raise ProjectSourcePathError(
            "Discovered GameMaker source path is on a different filesystem root "
            f"than the selected project: {candidate_text!r}"
        ) from exc

    # On POSIX a backslash can be a literal filename character, while every
    # GameMaker project path treats it as a separator. Feeding such a disk name
    # back through metadata normalization would silently redirect the candidate
    # (``evil\\name.yy`` -> ``evil/name.yy``), so reject the ambiguous host name.
    if os.sep != "\\" and "\\" in relative_path:
        raise ProjectSourcePathError(
            "Discovered GameMaker source path contains a host-literal backslash "
            f"that cannot be represented portably: {candidate_text!r}"
        )

    # A caller may hold a canonical path while the selected project root itself
    # is a symlink. In that case the lexical relative path starts with ``..``
    # even though both paths identify the same contained tree. Translate that
    # one case back to a stable project-relative path; metadata paths never get
    # this exception and leading traversal remains rejected below.
    normalized_relative = relative_path.replace(os.sep, "/")
    if normalized_relative == ".." or normalized_relative.startswith("../"):
        canonical_root = os.path.realpath(project_root_path)
        canonical_candidate = os.path.realpath(candidate_path)
        try:
            canonical_common = os.path.commonpath(
                (canonical_root, canonical_candidate)
            )
        except ValueError:
            canonical_common = ""
        if os.path.normcase(canonical_common) == os.path.normcase(canonical_root):
            normalized_relative = os.path.relpath(
                canonical_candidate,
                canonical_root,
            ).replace(os.sep, "/")
    return resolve_project_source_path(
        project_root_path,
        normalized_relative,
    )


def resolve_project_sidecar_source_path(
    project_root: StrPath,
    owner_source_path: StrPath,
    sidecar_path: str,
) -> ResolvedProjectSourcePath:
    """Resolve a nested ``.yy`` path relative to its owning resource.

    GameMaker sidecars are normally relative to the owner directory, while
    ``${project_dir}/...`` and paths beginning with a known project resource
    directory are project-root relative. The raw nested value is validated
    before composition so Windows drive-relative and absolute forms cannot be
    hidden behind an owner directory on POSIX runners.
    """
    raw_sidecar = sidecar_path.replace("\\", "/")
    project_relative = False
    if raw_sidecar == _PROJECT_DIRECTORY_PLACEHOLDER:
        raise ProjectSourcePathError(
            f"GameMaker sidecar path does not name a project file: {sidecar_path!r}"
        )
    placeholder_prefix = _PROJECT_DIRECTORY_PLACEHOLDER + "/"
    if raw_sidecar.startswith(placeholder_prefix):
        raw_sidecar = raw_sidecar[len(placeholder_prefix):]
        project_relative = True

    normalized_sidecar = _normalize_relative_source_path(
        raw_sidecar,
        description="GameMaker sidecar path",
    )
    first_segment = normalized_sidecar.partition("/")[0].casefold()
    project_relative = (
        project_relative
        or first_segment in _PROJECT_ROOT_SOURCE_DIRECTORIES
    )

    owner_text = os.fspath(owner_source_path)
    if os.path.isabs(owner_text):
        resolved_owner = resolve_project_filesystem_source_path(
            project_root,
            owner_text,
        )
    else:
        resolved_owner = resolve_project_source_path(project_root, owner_text)
    candidate = normalized_sidecar
    if not project_relative:
        candidate = posixpath.join(
            posixpath.dirname(resolved_owner.source_path),
            normalized_sidecar,
        )
    return resolve_project_source_path(project_root, candidate)


def _normalize_relative_source_path(
    source_path: str,
    *,
    description: str,
) -> str:
    normalized_path = source_path.replace("\\", "/")
    if not normalized_path or "\0" in normalized_path:
        raise ProjectSourcePathError(
            f"{description} is empty or invalid: {source_path!r}"
        )

    normalized_path = posixpath.normpath(normalized_path)
    if normalized_path in ("", "."):
        raise ProjectSourcePathError(
            f"{description} does not name a project file: {source_path!r}"
        )
    drive, _tail = ntpath.splitdrive(normalized_path)
    if drive or normalized_path.startswith("/"):
        raise ProjectSourcePathError(
            f"{description} must be relative to the selected GameMaker "
            f"project root: {source_path!r}"
        )
    if normalized_path == ".." or normalized_path.startswith("../"):
        raise ProjectSourcePathError(
            f"{description} escapes the selected GameMaker project root "
            f"through traversal: {source_path!r}"
        )
    return normalized_path
