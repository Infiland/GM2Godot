# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from .constants import (
    _GDSCRIPT_RESERVED_IDENTIFIERS,
    _GENERATED_IDENTIFIER_PREFIX,
    _GML_IDENTIFIER_MAX_LENGTH,
)
from .shared_models import GMLTranspileError, ScopeContext as _ScopeContext

def _sanitize_gdscript_identifier(name: str) -> str:
    if not _is_plain_identifier(name):
        return name
    if name in _GDSCRIPT_RESERVED_IDENTIFIERS:
        return f"{name}_"
    if name.startswith(_GENERATED_IDENTIFIER_PREFIX):
        return f"gml_user{name}"
    return name


def _is_plain_identifier(name: str) -> bool:
    if not name:
        return False
    return (name[0].isalpha() or name[0] == "_") and all(
        char.isalnum() or char == "_" for char in name
    )


def _validate_gml_identifier(name: str) -> None:
    if not name:
        raise GMLTranspileError("Expected identifier name")
    if len(name) > _GML_IDENTIFIER_MAX_LENGTH:
        raise GMLTranspileError("GML identifier exceeds 64 characters")
    if not (name[0].isalpha() or name[0] == "_"):
        raise GMLTranspileError("GML identifier must start with a letter or underscore")
    if not all(char.isalnum() or char == "_" for char in name):
        raise GMLTranspileError("GML identifier can only contain letters, numbers, and underscores")


def _reject_asset_identifier_name(name: str, scope_context: _ScopeContext) -> None:
    if name in scope_context.asset_names:
        raise GMLTranspileError(f"Unscoped identifier '{name}' collides with an asset name")
