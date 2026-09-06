"""Canonical script metadata and ordered dependency source names."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

from src.conversion.json_values import JsonObject


def _empty_script_raw_data() -> JsonObject:
    return {}


@dataclass(frozen=True)
class ScriptModel:
    name: str
    kind: str
    resource_type: str
    yy_path: str
    yyp_path: str
    order: int
    subfolder: str = ""
    raw_data: JsonObject = field(default_factory=_empty_script_raw_data)
    gml_path: str | None = None


def dependency_script_names(model: ScriptModel) -> tuple[str, ...]:
    names = [model.name]
    for key in ("%Name", "name"):
        value = model.raw_data.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    names.append(posixpath.splitext(posixpath.basename(model.yyp_path))[0])
    return tuple(names)
