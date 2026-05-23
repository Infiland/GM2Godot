from __future__ import annotations

from src.conversion.gml_runtime_parts.manifest import (
    RUNTIME_SEGMENTS,
    RuntimeAPIIndexEntry,
    RuntimeProvidedSymbol,
    RuntimeSegmentDefinition,
    duplicate_runtime_symbols,
    runtime_api_index,
    runtime_segment_names,
    runtime_symbol_index,
    validate_runtime_segments,
)
from src.conversion.gml_runtime_parts.script import GML_RUNTIME_SCRIPT
from src.conversion.gml_runtime_parts.writer import (
    GML_RUNTIME_RELATIVE_PATH,
    GML_RUNTIME_RESOURCE_PATH,
    write_gml_runtime,
)
from src.conversion.runtime_managers import (
    RUNTIME_MANAGER_DEFINITIONS,
    RUNTIME_MANAGER_RELATIVE_DIR,
    RuntimeManagerDefinition,
    register_runtime_manager_autoloads,
    render_runtime_manager_script,
    runtime_manager_autoloads,
    runtime_manager_definitions,
    write_runtime_managers,
)

__all__ = [
    "GML_RUNTIME_RELATIVE_PATH",
    "GML_RUNTIME_RESOURCE_PATH",
    "GML_RUNTIME_SCRIPT",
    "RUNTIME_MANAGER_DEFINITIONS",
    "RUNTIME_MANAGER_RELATIVE_DIR",
    "RUNTIME_SEGMENTS",
    "RuntimeManagerDefinition",
    "RuntimeAPIIndexEntry",
    "RuntimeProvidedSymbol",
    "RuntimeSegmentDefinition",
    "duplicate_runtime_symbols",
    "register_runtime_manager_autoloads",
    "render_runtime_manager_script",
    "runtime_api_index",
    "runtime_manager_autoloads",
    "runtime_manager_definitions",
    "runtime_segment_names",
    "runtime_symbol_index",
    "validate_runtime_segments",
    "write_runtime_managers",
    "write_gml_runtime",
]
