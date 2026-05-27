from __future__ import annotations

import os
import re


_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_UNSAFE_SEGMENT_RE = re.compile(r"[^0-9A-Za-z]+")
_SNAKE_SEGMENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def generated_path_segment(value: str, fallback: str = "resource") -> str:
    """Return a deterministic Godot-friendly path segment."""
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", separated)
    segment = _UNSAFE_SEGMENT_RE.sub("_", separated).strip("_").lower()
    segment = re.sub(r"_+", "_", segment)
    if not segment:
        segment = fallback
    if segment[0].isdigit():
        segment = "_" + segment
    return segment


def generated_resource_stem(name: str) -> str:
    return generated_path_segment(name, "resource")


def generated_subfolder_path(subfolder: str) -> str:
    return "/".join(
        generated_path_segment(segment, "folder")
        for segment in subfolder.replace("\\", "/").split("/")
        if segment
    )


def generated_nested_resource_path(
    kind: str,
    subfolder: str,
    name: str,
    extension: str,
    *,
    suffix: str = "",
) -> str:
    stem = generated_resource_stem(name) + suffix
    parts = [kind]
    parts.extend(part for part in generated_subfolder_path(subfolder).split("/") if part)
    parts.extend([stem, stem + extension])
    return "res://" + "/".join(parts)


def generated_flat_resource_path(
    kind: str,
    subfolder: str,
    name: str,
    extension: str,
    *,
    suffix: str = "",
) -> str:
    stem = generated_resource_stem(name) + suffix
    parts = [kind]
    parts.extend(part for part in generated_subfolder_path(subfolder).split("/") if part)
    parts.append(stem + extension)
    return "res://" + "/".join(parts)


def generated_resource_directory(
    root: str,
    subfolder: str,
    name: str,
    *,
    suffix: str = "",
) -> str:
    parts = [root]
    parts.extend(part for part in generated_subfolder_path(subfolder).split("/") if part)
    parts.append(generated_resource_stem(name) + suffix)
    return os.path.join(*parts)


def res_path_segments(res_path: str) -> list[str]:
    path = res_path[len("res://"):] if res_path.startswith("res://") else res_path
    return [segment for segment in path.split("/") if segment]


def is_snake_case_path_segment(segment: str) -> bool:
    stem, extension = os.path.splitext(segment)
    if not stem:
        return False
    if extension and extension != extension.lower():
        return False
    return _SNAKE_SEGMENT_RE.fullmatch(stem) is not None


def snake_case_res_path(res_path: str) -> str:
    prefix = "res://" if res_path.startswith("res://") else ""
    return prefix + "/".join(_snake_case_file_segment(segment) for segment in res_path_segments(res_path))


def _snake_case_file_segment(segment: str) -> str:
    stem, extension = os.path.splitext(segment)
    if not extension:
        return generated_path_segment(segment)
    return generated_path_segment(stem) + extension.lower()
