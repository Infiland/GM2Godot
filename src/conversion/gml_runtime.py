from __future__ import annotations

from src.conversion.gml_runtime_parts.script import GML_RUNTIME_SCRIPT
from src.conversion.gml_runtime_parts.writer import (
    GML_RUNTIME_RELATIVE_PATH,
    GML_RUNTIME_RESOURCE_PATH,
    write_gml_runtime,
)

__all__ = [
    "GML_RUNTIME_RELATIVE_PATH",
    "GML_RUNTIME_RESOURCE_PATH",
    "GML_RUNTIME_SCRIPT",
    "write_gml_runtime",
]
