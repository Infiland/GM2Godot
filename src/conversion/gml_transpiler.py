from __future__ import annotations

from src.conversion.gml_transpiler_parts.api import transpile_gml_code as transpile_gml_code
from src.conversion.gml_transpiler_parts.api import (
    transpile_gml_code_with_source_map as transpile_gml_code_with_source_map,
)
from src.conversion.gml_transpiler_parts.expression_service import (
    transpile_gml_condition as transpile_gml_condition,
    transpile_gml_expression as transpile_gml_expression,
)
from src.conversion.gml_transpiler_parts.extension_functions import (
    EXTENSION_FUNCTION_MAPPING_FILENAME as EXTENSION_FUNCTION_MAPPING_FILENAME,
    diagnostic_for_unmapped_extension_function as diagnostic_for_unmapped_extension_function,
    load_gml_extension_function_mappings as load_gml_extension_function_mappings,
    normalize_extension_function_mappings as normalize_extension_function_mappings,
    normalize_extension_functions as normalize_extension_functions,
)
from src.conversion.gml_transpiler_parts.gml_api_manifest import (
    GMLAPICategoryReport as GMLAPICategoryReport,
    GMLAPIEntry as GMLAPIEntry,
    category_issue_numbers as category_issue_numbers,
    diagnostic_for_unimplemented_gml_api as diagnostic_for_unimplemented_gml_api,
    generate_gml_api_compatibility_report as generate_gml_api_compatibility_report,
    get_gml_api_entry as get_gml_api_entry,
    godot_docs_root as godot_docs_root,
    is_known_gml_api as is_known_gml_api,
    iter_gml_api_entries as iter_gml_api_entries,
)
from src.conversion.gml_transpiler_parts.gml_manual_scope import (
    GMLManualScopeCategoryReport as GMLManualScopeCategoryReport,
    GMLManualScopeEntry as GMLManualScopeEntry,
    generate_gml_manual_scope_report as generate_gml_manual_scope_report,
    get_gml_manual_scope_entry as get_gml_manual_scope_entry,
    iter_gml_manual_scope_entries as iter_gml_manual_scope_entries,
    render_gml_manual_scope_markdown as render_gml_manual_scope_markdown,
    validate_gml_manual_scope_against_manifest as validate_gml_manual_scope_against_manifest,
)
from src.conversion.gml_transpiler_parts.gml_function_dispatch import (
    GMLFunctionDescriptor as GMLFunctionDescriptor,
    get_gml_function_descriptor as get_gml_function_descriptor,
    iter_gml_function_descriptors as iter_gml_function_descriptors,
    validate_gml_function_arity as validate_gml_function_arity,
)
from src.conversion.gml_transpiler_parts.lexical_api import (
    preprocess_gml_source as preprocess_gml_source,
)
from src.conversion.gml_transpiler_parts.result_models import (
    GMLPreprocessResult as GMLPreprocessResult,
    GMLPreprocessorDiagnostic as GMLPreprocessorDiagnostic,
    GMLSourceDiagnostic as GMLSourceDiagnostic,
    GMLSourceMap as GMLSourceMap,
    GMLSourceMapEntry as GMLSourceMapEntry,
    GMLTranspileResult as GMLTranspileResult,
)
from src.conversion.gml_transpiler_parts.shared_models import (
    GMLExtensionFunction as GMLExtensionFunction,
    GMLExtensionFunctionMapping as GMLExtensionFunctionMapping,
    GMLTranspileError as GMLTranspileError,
)
from src.conversion.gml_transpiler_parts.source_map import (
    analyze_gml_source_identifiers as analyze_gml_source_identifiers,
    gml_source_map_path as gml_source_map_path,
    merge_gml_source_maps as merge_gml_source_maps,
    render_gml_source_header as render_gml_source_header,
    write_gml_source_map as write_gml_source_map,
)

__all__ = [
    "GMLTranspileError",
    "GMLAPICategoryReport",
    "GMLAPIEntry",
    "GMLManualScopeCategoryReport",
    "GMLManualScopeEntry",
    "GMLFunctionDescriptor",
    "GMLExtensionFunction",
    "GMLExtensionFunctionMapping",
    "GMLPreprocessResult",
    "GMLPreprocessorDiagnostic",
    "GMLSourceDiagnostic",
    "GMLSourceMap",
    "GMLSourceMapEntry",
    "GMLTranspileResult",
    "category_issue_numbers",
    "EXTENSION_FUNCTION_MAPPING_FILENAME",
    "diagnostic_for_unimplemented_gml_api",
    "diagnostic_for_unmapped_extension_function",
    "generate_gml_api_compatibility_report",
    "generate_gml_manual_scope_report",
    "get_gml_api_entry",
    "get_gml_function_descriptor",
    "get_gml_manual_scope_entry",
    "godot_docs_root",
    "is_known_gml_api",
    "iter_gml_api_entries",
    "iter_gml_manual_scope_entries",
    "iter_gml_function_descriptors",
    "load_gml_extension_function_mappings",
    "normalize_extension_function_mappings",
    "normalize_extension_functions",
    "analyze_gml_source_identifiers",
    "gml_source_map_path",
    "merge_gml_source_maps",
    "preprocess_gml_source",
    "render_gml_manual_scope_markdown",
    "render_gml_source_header",
    "transpile_gml_code",
    "transpile_gml_code_with_source_map",
    "transpile_gml_condition",
    "transpile_gml_expression",
    "validate_gml_manual_scope_against_manifest",
    "validate_gml_function_arity",
    "write_gml_source_map",
]
