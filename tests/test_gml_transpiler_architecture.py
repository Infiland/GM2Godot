from __future__ import annotations

import inspect
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast

import src.conversion.gml_transpiler as gml_transpiler
from src.conversion.gml_transpiler_parts.api import (
    transpile_gml_code as owner_transpile_gml_code,
    transpile_gml_code_with_source_map as owner_transpile_gml_code_with_source_map,
)
from src.conversion.gml_transpiler_parts.expression_service import (
    transpile_gml_condition as owner_transpile_gml_condition,
    transpile_gml_expression as owner_transpile_gml_expression,
)
from src.conversion.gml_transpiler_parts.extension_functions import (
    EXTENSION_FUNCTION_MAPPING_FILENAME as owner_extension_function_mapping_filename,
    diagnostic_for_unmapped_extension_function as owner_diagnostic_for_unmapped_extension_function,
    load_gml_extension_function_mappings as owner_load_gml_extension_function_mappings,
    normalize_extension_function_mappings as owner_normalize_extension_function_mappings,
    normalize_extension_functions as owner_normalize_extension_functions,
)
from src.conversion.gml_transpiler_parts.gml_api_manifest import (
    GMLAPICategoryReport as owner_gml_api_category_report,
    GMLAPIEntry as owner_gml_api_entry,
    category_issue_numbers as owner_category_issue_numbers,
    diagnostic_for_unimplemented_gml_api as owner_diagnostic_for_unimplemented_gml_api,
    generate_gml_api_compatibility_report as owner_generate_gml_api_compatibility_report,
    get_gml_api_entry as owner_get_gml_api_entry,
    godot_docs_root as owner_godot_docs_root,
    is_known_gml_api as owner_is_known_gml_api,
    iter_gml_api_entries as owner_iter_gml_api_entries,
)
from src.conversion.gml_transpiler_parts.gml_function_dispatch import (
    GMLFunctionDescriptor as owner_gml_function_descriptor,
    get_gml_function_descriptor as owner_get_gml_function_descriptor,
    iter_gml_function_descriptors as owner_iter_gml_function_descriptors,
    validate_gml_function_arity as owner_validate_gml_function_arity,
)
from src.conversion.gml_transpiler_parts.gml_manual_scope import (
    GMLManualScopeCategoryReport as owner_gml_manual_scope_category_report,
    GMLManualScopeEntry as owner_gml_manual_scope_entry,
    generate_gml_manual_scope_report as owner_generate_gml_manual_scope_report,
    get_gml_manual_scope_entry as owner_get_gml_manual_scope_entry,
    iter_gml_manual_scope_entries as owner_iter_gml_manual_scope_entries,
    render_gml_manual_scope_markdown as owner_render_gml_manual_scope_markdown,
    validate_gml_manual_scope_against_manifest as owner_validate_gml_manual_scope_against_manifest,
)
from src.conversion.gml_transpiler_parts.lexical_api import preprocess_gml_source as owner_preprocess_gml_source
from src.conversion.gml_transpiler_parts.result_models import (
    GMLPreprocessorDiagnostic as owner_gml_preprocessor_diagnostic,
    GMLPreprocessResult as owner_gml_preprocess_result,
    GMLSourceDiagnostic as owner_gml_source_diagnostic,
    GMLSourceMap as owner_gml_source_map,
    GMLSourceMapEntry as owner_gml_source_map_entry,
    GMLTranspileResult as owner_gml_transpile_result,
)
from src.conversion.gml_transpiler_parts.shared_models import (
    GMLExtensionFunction as owner_gml_extension_function,
    GMLExtensionFunctionMapping as owner_gml_extension_function_mapping,
    GMLTranspileError as owner_gml_transpile_error,
)
from src.conversion.gml_transpiler_parts.source_map import (
    analyze_gml_source_identifiers as owner_analyze_gml_source_identifiers,
    gml_source_map_path as owner_gml_source_map_path,
    merge_gml_source_maps as owner_merge_gml_source_maps,
    render_gml_source_header as owner_render_gml_source_header,
    write_gml_source_map as owner_write_gml_source_map,
)
from tests.gml_facade_contract_support import facade_reexports_from_source, literal_all_exports
from tests.gml_transpiler_architecture_support import (
    MODULE_IMPORT_NAME,
    ImportEdge,
    ImportViolation,
    import_edges_from_source,
    iter_python_paths,
    module_name,
    structural_import_violations,
    top_level_import_edges_from_source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACADE_MODULE = "src.conversion.gml_transpiler"
PARTS_PACKAGE = "src.conversion.gml_transpiler_parts"
FACADE_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler.py"
PARTS_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts"
TEST_SUPPORT_MODULE = "tests.gml_transpiler_architecture_support"
TEST_SUPPORT_MODULES = frozenset({TEST_SUPPORT_MODULE, "tests.gml_facade_contract_support"})


# The stable facade is intentionally ordered. Each owner is the exact runtime
# object owner, which makes this more precise than an export-name-only check.
EXPECTED_FACADE_BINDINGS = (
    ("GMLTranspileError", f"{PARTS_PACKAGE}.shared_models"),
    ("GMLAPICategoryReport", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("GMLAPIEntry", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("GMLManualScopeCategoryReport", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("GMLManualScopeEntry", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("GMLFunctionDescriptor", f"{PARTS_PACKAGE}.gml_function_dispatch"),
    ("GMLExtensionFunction", f"{PARTS_PACKAGE}.shared_models"),
    ("GMLExtensionFunctionMapping", f"{PARTS_PACKAGE}.shared_models"),
    ("GMLPreprocessResult", f"{PARTS_PACKAGE}.result_models"),
    ("GMLPreprocessorDiagnostic", f"{PARTS_PACKAGE}.result_models"),
    ("GMLSourceDiagnostic", f"{PARTS_PACKAGE}.result_models"),
    ("GMLSourceMap", f"{PARTS_PACKAGE}.result_models"),
    ("GMLSourceMapEntry", f"{PARTS_PACKAGE}.result_models"),
    ("GMLTranspileResult", f"{PARTS_PACKAGE}.result_models"),
    ("category_issue_numbers", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("EXTENSION_FUNCTION_MAPPING_FILENAME", f"{PARTS_PACKAGE}.extension_functions"),
    ("diagnostic_for_unimplemented_gml_api", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("diagnostic_for_unmapped_extension_function", f"{PARTS_PACKAGE}.extension_functions"),
    ("generate_gml_api_compatibility_report", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("generate_gml_manual_scope_report", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("get_gml_api_entry", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("get_gml_function_descriptor", f"{PARTS_PACKAGE}.gml_function_dispatch"),
    ("get_gml_manual_scope_entry", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("godot_docs_root", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("is_known_gml_api", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("iter_gml_api_entries", f"{PARTS_PACKAGE}.gml_api_manifest"),
    ("iter_gml_manual_scope_entries", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("iter_gml_function_descriptors", f"{PARTS_PACKAGE}.gml_function_dispatch"),
    ("load_gml_extension_function_mappings", f"{PARTS_PACKAGE}.extension_functions"),
    ("normalize_extension_function_mappings", f"{PARTS_PACKAGE}.extension_functions"),
    ("normalize_extension_functions", f"{PARTS_PACKAGE}.extension_functions"),
    ("analyze_gml_source_identifiers", f"{PARTS_PACKAGE}.source_map"),
    ("gml_source_map_path", f"{PARTS_PACKAGE}.source_map"),
    ("merge_gml_source_maps", f"{PARTS_PACKAGE}.source_map"),
    ("preprocess_gml_source", f"{PARTS_PACKAGE}.lexical_api"),
    ("render_gml_manual_scope_markdown", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("render_gml_source_header", f"{PARTS_PACKAGE}.source_map"),
    ("transpile_gml_code", f"{PARTS_PACKAGE}.api"),
    ("transpile_gml_code_with_source_map", f"{PARTS_PACKAGE}.api"),
    ("transpile_gml_condition", f"{PARTS_PACKAGE}.expression_service"),
    ("transpile_gml_expression", f"{PARTS_PACKAGE}.expression_service"),
    ("validate_gml_manual_scope_against_manifest", f"{PARTS_PACKAGE}.gml_manual_scope"),
    ("validate_gml_function_arity", f"{PARTS_PACKAGE}.gml_function_dispatch"),
    ("write_gml_source_map", f"{PARTS_PACKAGE}.source_map"),
)
EXPECTED_PUBLIC_FACADE_EXPORTS = tuple(name for name, _ in EXPECTED_FACADE_BINDINGS)
EXPECTED_FACADE_IMPORTS = frozenset(
    ImportEdge(FACADE_MODULE, owner, name) for name, owner in EXPECTED_FACADE_BINDINGS
)

EXPECTED_FACADE_VALUES: dict[str, object] = dict(
    zip(
        EXPECTED_PUBLIC_FACADE_EXPORTS,
        (
            owner_gml_transpile_error,
            owner_gml_api_category_report,
            owner_gml_api_entry,
            owner_gml_manual_scope_category_report,
            owner_gml_manual_scope_entry,
            owner_gml_function_descriptor,
            owner_gml_extension_function,
            owner_gml_extension_function_mapping,
            owner_gml_preprocess_result,
            owner_gml_preprocessor_diagnostic,
            owner_gml_source_diagnostic,
            owner_gml_source_map,
            owner_gml_source_map_entry,
            owner_gml_transpile_result,
            owner_category_issue_numbers,
            owner_extension_function_mapping_filename,
            owner_diagnostic_for_unimplemented_gml_api,
            owner_diagnostic_for_unmapped_extension_function,
            owner_generate_gml_api_compatibility_report,
            owner_generate_gml_manual_scope_report,
            owner_get_gml_api_entry,
            owner_get_gml_function_descriptor,
            owner_get_gml_manual_scope_entry,
            owner_godot_docs_root,
            owner_is_known_gml_api,
            owner_iter_gml_api_entries,
            owner_iter_gml_manual_scope_entries,
            owner_iter_gml_function_descriptors,
            owner_load_gml_extension_function_mappings,
            owner_normalize_extension_function_mappings,
            owner_normalize_extension_functions,
            owner_analyze_gml_source_identifiers,
            owner_gml_source_map_path,
            owner_merge_gml_source_maps,
            owner_preprocess_gml_source,
            owner_render_gml_manual_scope_markdown,
            owner_render_gml_source_header,
            owner_transpile_gml_code,
            owner_transpile_gml_code_with_source_map,
            owner_transpile_gml_condition,
            owner_transpile_gml_expression,
            owner_validate_gml_manual_scope_against_manifest,
            owner_validate_gml_function_arity,
            owner_write_gml_source_map,
        ),
        strict=True,
    )
)
# inspect.signature is deliberately frozen for every public facade binding.
EXPECTED_PUBLIC_FACADE_SIGNATURES: dict[str, str | None] = {
    "GMLTranspileError": "(message: 'str', *, line: 'int | None' = None, column: 'int | None' = None) -> 'None'",
    "GMLAPICategoryReport": (
        "(category: 'str', issue_number: 'int', implemented: 'int', partial: 'int', planned: 'int', "
        "unsupported: 'int', out_of_scope: 'int') -> None"
    ),
    "GMLAPIEntry": (
        "(name: 'str', category: 'str', status: 'GMLAPISupportStatus', issue_number: 'int', "
        "owner_module: 'str', parser_support: 'GMLAPISupportFlag', emitter_support: 'GMLAPISupportFlag', "
        "runtime_support: 'GMLAPISupportFlag', smoke_coverage: 'GMLAPISupportFlag', docs_url: 'str', "
        "notes: 'str') -> None"
    ),
    "GMLManualScopeCategoryReport": (
        "(section: 'str', implemented: 'int', partial: 'int', planned: 'int', unsupported: 'int', "
        "out_of_scope: 'int') -> None"
    ),
    "GMLManualScopeEntry": (
        "(key: 'str', title: 'str', section: 'str', status: 'GMLAPISupportStatus', issue_number: 'int', "
        "owner_area: 'str', diagnostic_policy: 'GMLManualDiagnosticPolicy', docs_url: 'str', "
        "manifest_categories: 'tuple[str, ...]', test_paths: 'tuple[str, ...]', notes: 'str') -> None"
    ),
    "GMLFunctionDescriptor": (
        "(name: 'str', category: 'str', min_args: 'int', max_args: 'int | None', "
        "lowering_kind: 'GMLFunctionLoweringKind', lowering_target: 'str', issue_number: 'int', "
        "docs_url: 'str') -> None"
    ),
    "GMLExtensionFunction": (
        "(name: 'str', extension_name: 'str' = '', min_args: 'int | None' = None, "
        "max_args: 'int | None' = None) -> None"
    ),
    "GMLExtensionFunctionMapping": (
        "(function_name: 'str', target: 'str', min_args: 'int | None' = None, "
        "max_args: 'int | None' = None) -> None"
    ),
    "GMLPreprocessResult": "(source: 'str', diagnostics: 'tuple[GMLPreprocessorDiagnostic, ...]') -> None",
    "GMLPreprocessorDiagnostic": "(line: 'int', directive: 'str', message: 'str', source: 'str') -> None",
    "GMLSourceDiagnostic": (
        "(severity: 'SourceDiagnosticSeverity', code: 'str', message: 'str', line: 'int', column: 'int', "
        "identifier: 'str', suggested_name: 'str | None' = None) -> None"
    ),
    "GMLSourceMap": (
        "(source_path: 'str | None', event: 'str | None', entries: 'tuple[GMLSourceMapEntry, ...]') -> None"
    ),
    "GMLSourceMapEntry": (
        "(generated_line: 'int', source_line: 'int', source_column: 'int', generated_text: 'str', "
        "source_text: 'str', source_path: 'str | None' = None, event: 'str | None' = None) -> None"
    ),
    "GMLTranspileResult": "(code: 'str', source_map: 'GMLSourceMap', static_scope_id: 'str | None' = None) -> None",
    "category_issue_numbers": "() -> 'dict[str, int]'",
    "EXTENSION_FUNCTION_MAPPING_FILENAME": None,
    "diagnostic_for_unimplemented_gml_api": "(name: 'str') -> 'str | None'",
    "diagnostic_for_unmapped_extension_function": "(function: 'GMLExtensionFunction') -> 'str'",
    "generate_gml_api_compatibility_report": "() -> 'tuple[GMLAPICategoryReport, ...]'",
    "generate_gml_manual_scope_report": "() -> 'tuple[GMLManualScopeCategoryReport, ...]'",
    "get_gml_api_entry": "(name: 'str') -> 'GMLAPIEntry | None'",
    "get_gml_function_descriptor": "(name: 'str') -> 'GMLFunctionDescriptor | None'",
    "get_gml_manual_scope_entry": "(key: 'str') -> 'GMLManualScopeEntry | None'",
    "godot_docs_root": "() -> 'str'",
    "is_known_gml_api": "(name: 'str') -> 'bool'",
    "iter_gml_api_entries": "() -> 'Iterable[GMLAPIEntry]'",
    "iter_gml_manual_scope_entries": "() -> 'Iterable[GMLManualScopeEntry]'",
    "iter_gml_function_descriptors": "() -> 'tuple[GMLFunctionDescriptor, ...]'",
    "load_gml_extension_function_mappings": "(path: 'str') -> 'dict[str, GMLExtensionFunctionMapping]'",
    "normalize_extension_function_mappings": "(value: 'object') -> 'dict[str, GMLExtensionFunctionMapping]'",
    "normalize_extension_functions": "(value: 'object') -> 'dict[str, GMLExtensionFunction]'",
    "analyze_gml_source_identifiers": "(source: 'str') -> 'tuple[GMLSourceDiagnostic, ...]'",
    "gml_source_map_path": "(gdscript_path: 'str') -> 'str'",
    "merge_gml_source_maps": (
        "(maps: 'Iterable[GMLSourceMap]', *, source_path: 'str | None' = None, "
        "event: 'str | None' = None) -> 'GMLSourceMap'"
    ),
    "preprocess_gml_source": (
        "(source: 'str', *, macro_configuration: 'str | None' = None, "
        "active_symbols: 'Iterable[str] | None' = None) -> 'GMLPreprocessResult'"
    ),
    "render_gml_manual_scope_markdown": "() -> 'str'",
    "render_gml_source_header": (
        "(*, source_path: 'str | None', event: 'str | None', source: 'str', "
        "max_comments: 'int' = 8) -> 'str'"
    ),
    "transpile_gml_code": (
        "(source: 'str', indent: 'str' = '\\t', local_names: 'Iterable[str] | None' = None, "
        "instance_variables: 'MutableSet[str] | None' = None, inherited_event_call: 'str | None' = None, "
        "macro_configuration: 'str | None' = None, active_preprocessor_symbols: 'Iterable[str] | None' = None, "
        "top_level_global_scope: 'bool' = False, legacy_global_builtins: 'bool' = False, "
        "asset_names: 'Iterable[str] | None' = None, static_scope_prefix: 'str | None' = None, "
        "return_depth: 'int' = 0, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None, source_path: 'str | None' = None, "
        "event: 'str | None' = None, preserve_source_comments: 'bool' = False, generated_line_offset: 'int' = 0, "
        "self_expression: 'str' = 'self', other_expression: 'str' = 'other', "
        "instance_target: 'str | None' = None, direct_instance_names: 'Iterable[str] | None' = None, "
        "dynamic_instance_names: 'Iterable[str] | None' = None, "
        "enum_values: 'Mapping[str, Mapping[str, int]] | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None) -> 'str'"
    ),
    "transpile_gml_code_with_source_map": (
        "(source: 'str', indent: 'str' = '\\t', local_names: 'Iterable[str] | None' = None, "
        "instance_variables: 'MutableSet[str] | None' = None, inherited_event_call: 'str | None' = None, "
        "macro_configuration: 'str | None' = None, active_preprocessor_symbols: 'Iterable[str] | None' = None, "
        "top_level_global_scope: 'bool' = False, legacy_global_builtins: 'bool' = False, "
        "asset_names: 'Iterable[str] | None' = None, static_scope_prefix: 'str | None' = None, "
        "return_depth: 'int' = 0, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None, source_path: 'str | None' = None, "
        "event: 'str | None' = None, preserve_source_comments: 'bool' = False, generated_line_offset: 'int' = 0, "
        "self_expression: 'str' = 'self', other_expression: 'str' = 'other', "
        "instance_target: 'str | None' = None, direct_instance_names: 'Iterable[str] | None' = None, "
        "dynamic_instance_names: 'Iterable[str] | None' = None, "
        "enum_values: 'Mapping[str, Mapping[str, int]] | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None) -> 'GMLTranspileResult'"
    ),
    "transpile_gml_condition": (
        "(source: 'str', local_names: 'Iterable[str] | None' = None, "
        "enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'Iterable[str] | None' = None, scope_context: '_ScopeContext | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None, global_names: 'Iterable[str] | None' = None, "
        "asset_names: 'Iterable[str] | None' = None, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None) -> 'str'"
    ),
    "transpile_gml_expression": (
        "(source: 'str', local_names: 'Iterable[str] | None' = None, "
        "enum_values: 'MutableMapping[str, dict[str, int]] | None' = None, "
        "enum_names: 'Iterable[str] | None' = None, scope_context: '_ScopeContext | None' = None, "
        "macro_values: 'Mapping[str, str] | None' = None, global_names: 'Iterable[str] | None' = None, "
        "asset_names: 'Iterable[str] | None' = None, extension_functions: 'object' = None, "
        "extension_function_mappings: 'object' = None) -> 'str'"
    ),
    "validate_gml_manual_scope_against_manifest": "() -> 'tuple[str, ...]'",
    "validate_gml_function_arity": "(descriptor: 'GMLFunctionDescriptor', arg_count: 'int') -> 'str | None'",
    "write_gml_source_map": "(gdscript_path: 'str', source_map: 'GMLSourceMap') -> 'str'",
}


LEXICAL_COHORT = frozenset(
    {
        f"{PARTS_PACKAGE}.identifiers",
        f"{PARTS_PACKAGE}.lexical",
        f"{PARTS_PACKAGE}.lexical_api",
        f"{PARTS_PACKAGE}.preprocessor",
        f"{PARTS_PACKAGE}.tokens",
    }
)
EXPRESSION_COHORT = frozenset(
    {
        f"{PARTS_PACKAGE}.emitter",
        f"{PARTS_PACKAGE}.enum_helpers",
        f"{PARTS_PACKAGE}.expression_api",
        f"{PARTS_PACKAGE}.expression_parser",
        f"{PARTS_PACKAGE}.expression_service",
        f"{PARTS_PACKAGE}.function_helpers",
    }
)
STATEMENT_COHORT = frozenset(
    {
        f"{PARTS_PACKAGE}.statement_api",
        f"{PARTS_PACKAGE}.statement_parser",
        f"{PARTS_PACKAGE}.statements",
        f"{PARTS_PACKAGE}.static_declarations",
    }
)
STATEMENT_MODELS_MODULE = f"{PARTS_PACKAGE}.statement_models"
STATEMENT_API_MODULE = f"{PARTS_PACKAGE}.statement_api"
EXPRESSION_PARSER_MODULE = f"{PARTS_PACKAGE}.expression_parser"
DEFERRED_GRAMMAR_GATEWAY = frozenset(
    {
        ImportEdge(EXPRESSION_PARSER_MODULE, STATEMENT_API_MODULE, "collect_static_declarations"),
        ImportEdge(EXPRESSION_PARSER_MODULE, STATEMENT_API_MODULE, "parse_gml_statements"),
        ImportEdge(EXPRESSION_PARSER_MODULE, STATEMENT_API_MODULE, "static_scope_id"),
        ImportEdge(EXPRESSION_PARSER_MODULE, STATEMENT_MODELS_MODULE, "GMLStatementRequest"),
    }
)


def _internal_module_paths() -> tuple[Path, ...]:
    return (FACADE_PATH, *sorted(PARTS_PATH.rglob("*.py")))


GOVERNED_MODULES = frozenset(
    {FACADE_MODULE, PARTS_PACKAGE, *(module_name(path, PROJECT_ROOT) for path in _internal_module_paths())}
)
MODULE_OBJECT_EXCEPTIONS = {
    "tests.test_gml_transpiler_architecture": frozenset({FACADE_MODULE}),
}


def _path_violations(path: Path) -> frozenset[ImportViolation]:
    return structural_import_violations(
        path.read_text(encoding="utf-8"),
        module_name(path, PROJECT_ROOT),
        governed_modules=GOVERNED_MODULES,
        module_object_exceptions=MODULE_OBJECT_EXCEPTIONS,
        package_module=path.name == "__init__.py",
    )


def _repository_violations() -> frozenset[ImportViolation]:
    violations: set[ImportViolation] = set()
    for path in iter_python_paths(PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
        violations.update(_path_violations(path))
    return frozenset(violations)


def _format_violations(violations: frozenset[ImportViolation]) -> str:
    return "\n".join(f"  {violation}" for violation in sorted(violations))


def _test_support_import_violations(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportViolation]:
    violations = set(
        structural_import_violations(
            source,
            consumer,
            governed_modules=TEST_SUPPORT_MODULES,
            module_object_exceptions={},
            package_module=package_module,
        )
    )
    for edge in import_edges_from_source(source, consumer, package_module=package_module):
        candidate = f"{edge.owner}.{edge.name}" if edge.name != MODULE_IMPORT_NAME else edge.owner
        if edge.owner in TEST_SUPPORT_MODULES:
            violations.add(
                ImportViolation(consumer, edge.owner, edge.name, "test-support-import", 0)
            )
        elif candidate in TEST_SUPPORT_MODULES:
            violations.add(
                ImportViolation(consumer, candidate, MODULE_IMPORT_NAME, "test-support-module", 0)
            )
    return frozenset(violations)


def _production_test_support_violations() -> frozenset[ImportViolation]:
    violations: set[ImportViolation] = set()
    for path in iter_python_paths(PROJECT_ROOT / "src"):
        violations.update(
            _test_support_import_violations(
                path.read_text(encoding="utf-8"),
                module_name(path, PROJECT_ROOT),
                package_module=path.name == "__init__.py",
            )
        )
    return frozenset(violations)

def _private_usage_suppressions() -> frozenset[tuple[str, int, str]]:
    suppressions: set[tuple[str, int, str]] = set()
    for path in _internal_module_paths():
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for line, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "pyright:" in text and "reportPrivateUsage" in text:
                suppressions.add((relative_path, line, text.strip()))
    return frozenset(suppressions)


def _phase_direction_violations() -> frozenset[ImportEdge]:
    violations: set[ImportEdge] = set()
    for path in sorted(PARTS_PATH.rglob("*.py")):
        consumer = module_name(path, PROJECT_ROOT)
        edges = import_edges_from_source(
            path.read_text(encoding="utf-8"),
            consumer,
            package_module=path.name == "__init__.py",
        )
        if consumer in LEXICAL_COHORT:
            violations.update(edge for edge in edges if edge.owner in EXPRESSION_COHORT | STATEMENT_COHORT)
        if consumer in EXPRESSION_COHORT:
            violations.update(
                edge
                for edge in edges
                if edge.owner in STATEMENT_COHORT and edge.owner != STATEMENT_API_MODULE
            )
    return frozenset(violations)


class TestGMLTranspilerArchitecture(unittest.TestCase):
    def test_structural_scanner_rejects_private_import_forms(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        cases: dict[str, tuple[str, dict[str, frozenset[str]], tuple[str, str, str]]] = {
            "relative_from": (
                "from .tokens import _relative_private",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_relative_private", "from-import"),
            ),
            "parenthesized_relative_from": (
                "from .tokens import (\n    _parenthesized_private,\n)",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_parenthesized_private", "from-import"),
            ),
            "absolute_from": (
                f"from {PARTS_PACKAGE}.tokens import _absolute_private",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_absolute_private", "from-import"),
            ),
            "aliased_from": (
                "from .tokens import _aliased_private as public_name",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_aliased_private", "from-import"),
            ),
            "star": (
                "from .tokens import *",
                {},
                (f"{PARTS_PACKAGE}.tokens", "*", "star-import"),
            ),
            "parent_facade": (
                "from .. import gml_transpiler as facade",
                {},
                (FACADE_MODULE, MODULE_IMPORT_NAME, "module-import"),
            ),
            "absolute_facade": (
                "from src.conversion import gml_transpiler as facade",
                {},
                (FACADE_MODULE, MODULE_IMPORT_NAME, "module-import"),
            ),
            "module_object": (
                f"import {PARTS_PACKAGE}.tokens as token_module",
                {},
                (f"{PARTS_PACKAGE}.tokens", MODULE_IMPORT_NAME, "module-import"),
            ),
            "private_module": (
                f"import {PARTS_PACKAGE}._private_module as private_module",
                {},
                (PARTS_PACKAGE, "_private_module", "module-import"),
            ),
            "class_scope": (
                "class Holder:\n    from .tokens import _class_private",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_class_private", "from-import"),
            ),
            "try_scope": (
                "try:\n    from .tokens import _try_private\nexcept RuntimeError:\n    pass",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_try_private", "from-import"),
            ),
            "match_scope": (
                "match marker:\n    case _:\n        from .tokens import _match_private",
                {},
                (f"{PARTS_PACKAGE}.tokens", "_match_private", "from-import"),
            ),
        }
        self._assert_structural_cases(cases, consumer)


    def test_structural_scanner_rejects_private_reflection_forms(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        facade_exception = {consumer: frozenset({FACADE_MODULE})}
        cases: dict[str, tuple[str, dict[str, frozenset[str]], tuple[str, str, str]]] = {
            "ancestor_attribute": (
                "import src.conversion as conversion\n"
                "conversion.gml_transpiler._ancestor_private",
                facade_exception,
                (FACADE_MODULE, "_ancestor_private", "module-attribute"),
            ),
            "getattr": (
                f"import {FACADE_MODULE} as facade\ngetattr(facade, \"_getattr_private\")",
                facade_exception,
                (FACADE_MODULE, "_getattr_private", "getattr"),
            ),
            "vars": (
                f"import {FACADE_MODULE} as facade\nvars(facade)[\"_vars_private\"]",
                facade_exception,
                (FACADE_MODULE, "_vars_private", "module-dict"),
            ),
            "module_dict": (
                f"import {FACADE_MODULE} as facade\nfacade.__dict__[\"_dict_private\"]",
                facade_exception,
                (FACADE_MODULE, "_dict_private", "module-dict"),
            ),
        }
        self._assert_structural_cases(cases, consumer)


    def _assert_structural_cases(
        self,
        cases: dict[str, tuple[str, dict[str, frozenset[str]], tuple[str, str, str]]],
        consumer: str,
    ) -> None:
        for case, (source, exceptions, expected) in cases.items():
            with self.subTest(case=case):
                violations = structural_import_violations(
                    source,
                    consumer,
                    governed_modules=GOVERNED_MODULES,
                    module_object_exceptions=exceptions,
                )
                actual = {(violation.owner, violation.name, violation.form) for violation in violations}
                self.assertEqual(actual, {expected}, _format_violations(violations))

    def test_dynamic_import_scanner_rejects_every_scope_and_alias_form(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        cases = {
            "assignment": (
                "import importlib as loader\n"
                f"assigned = loader.import_module(name=\"{PARTS_PACKAGE}.tokens\")"
            ),
            "aliased_from_import": (
                "from importlib import import_module as load_module\n"
                f"load_module(name=\"{PARTS_PACKAGE}.tokens\")"
            ),
            "comprehension": (
                "import importlib as loader\n"
                f"[loader.import_module(name=\"{PARTS_PACKAGE}.tokens\") for _ in range(1)]"
            ),
            "if": (
                "import importlib as loader\n"
                f"if enabled:\n    loader.import_module(name=\"{PARTS_PACKAGE}.tokens\")"
            ),
            "loop": (
                "import importlib as loader\n"
                f"for _ in range(1):\n    loader.__dict__[\"import_module\"](name=\"{PARTS_PACKAGE}.tokens\")"
            ),
            "builtins_alias": (
                "from builtins import getattr as reveal\n"
                f"import {PARTS_PACKAGE}.tokens as token_module\n"
                "reveal(token_module, \"_hidden\")"
            ),
        }
        for case, source in cases.items():
            with self.subTest(case=case):
                violations = structural_import_violations(
                    source,
                    consumer,
                    governed_modules=GOVERNED_MODULES,
                    module_object_exceptions={},
                )
                self.assertTrue(
                    any(violation.form == "dynamic-import" for violation in violations)
                    or any(violation.form == "getattr" for violation in violations),
                    _format_violations(violations),
                )
    def test_literal_vars_and_getattr_aliases_cannot_bypass_governed_modules(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        facade_exception = {consumer: frozenset({FACADE_MODULE})}
        cases = {
            "vars_alias_private": (
                f"from builtins import vars as reveal\nimport {FACADE_MODULE} as facade\nreveal(facade)[\"_alias_hidden\"]",
                (FACADE_MODULE, "_alias_hidden", "module-dict"),
            ),
            "qualified_vars_private": (
                f"import builtins\nimport {FACADE_MODULE} as facade\nbuiltins.vars(facade)[\"_qualified_hidden\"]",
                (FACADE_MODULE, "_qualified_hidden", "module-dict"),
            ),
            "getattr_alias_loader": (
                f"from builtins import getattr as reveal\nimport importlib\nreveal(importlib, \"import_module\")(\"{FACADE_MODULE}\")",
                (FACADE_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            ),
            "qualified_getattr_loader": (
                f"import builtins\nimport importlib\nbuiltins.getattr(importlib, \"import_module\")(\"{FACADE_MODULE}\")",
                (FACADE_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            ),
            "global_vars_loader": (
                f"import importlib\nvars(importlib)[\"import_module\"](\"{FACADE_MODULE}\")",
                (FACADE_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            ),
            "vars_alias_loader": (
                f"from builtins import vars as reveal\nimport importlib\nreveal(importlib)[\"import_module\"](\"{FACADE_MODULE}\")",
                (FACADE_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            ),
            "qualified_vars_loader": (
                f"import builtins\nimport importlib\nbuiltins.vars(importlib)[\"import_module\"](\"{FACADE_MODULE}\")",
                (FACADE_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            ),
        }
        for case, (source, expected) in cases.items():
            with self.subTest(case=case):
                violations = structural_import_violations(
                    source,
                    consumer,
                    governed_modules=GOVERNED_MODULES,
                    module_object_exceptions=facade_exception,
                )
                actual = {(violation.owner, violation.name, violation.form) for violation in violations}
                self.assertEqual(actual, {expected}, _format_violations(violations))
    def test_structural_scanner_allows_same_module_and_direct_public_imports(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        source = """
from .shared_models import Token as local_token
from .synthetic_consumer import _same_module_helper


def helper(value: local_token) -> None:
    _same_module_helper()
    return None
"""
        self.assertEqual(
            structural_import_violations(
                source,
                consumer,
                governed_modules=GOVERNED_MODULES,
                module_object_exceptions={},
            ),
            frozenset(),
        )

    def test_literal_all_parser_rejects_dynamic_and_private_forms(self) -> None:
        self.assertEqual(literal_all_exports('__all__ = ["public"]'), ("public",))
        invalid_sources = {
            "typed": '__all__: list[str] = ["public"]',
            "tuple": '__all__ = ("public",)',
            "name": "__all__ = NAMES",
            "call": "__all__ = list(NAMES)",
            "concat": '__all__ = ["a"] + ["b"]',
            "comprehension": "__all__ = [name for name in NAMES]",
            "starred": "__all__ = [*NAMES]",
            "duplicate": '__all__ = ["a", "a"]',
            "private": '__all__ = ["_private"]',
            "augmented": '__all__ = ["a"]\n__all__ += ["b"]',
            "conditional": '__all__ = ["a"]\nif enabled:\n    __all__ = ["b"]',
            "subscript": '__all__ = ["a"]\n__all__[0] = "b"',
            "append": '__all__ = ["a"]\n__all__.append("b")',
            "delete": '__all__ = ["a"]\ndel __all__',
            "globals-subscript": '__all__ = ["a"]\nglobals()["__all__"] = ["b"]',
            "locals-subscript": '__all__ = ["a"]\nlocals()["__all__"] = ["b"]',
            "globals-update": '__all__ = ["a"]\nglobals().update(__all__=["b"])',
            "globals-dict-update": '__all__ = ["a"]\nglobals().update({"__all__": ["b"]})',
            "vars-subscript": '__all__ = ["a"]\nvars()["__all__"] = ["b"]',
            "globals-setitem": '__all__ = ["a"]\nglobals().__setitem__("__all__", ["b"])',
            "namespace-alias": '__all__ = ["a"]\nnamespace = globals()\nnamespace["__all__"] = ["b"]',
        }
        for case, source in invalid_sources.items():
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    literal_all_exports(source)

    def test_facade_contract_preserves_exact_order_owners_identities_and_signatures(self) -> None:
        facade_source = FACADE_PATH.read_text(encoding="utf-8")
        self.assertEqual(literal_all_exports(facade_source), EXPECTED_PUBLIC_FACADE_EXPORTS)
        self.assertEqual(tuple(gml_transpiler.__all__), EXPECTED_PUBLIC_FACADE_EXPORTS)
        self.assertIs(type(gml_transpiler.__all__), list)
        self.assertEqual(
            facade_reexports_from_source(
                facade_source,
                FACADE_MODULE,
                allowed_owner_prefix=PARTS_PACKAGE,
            ),
            EXPECTED_FACADE_IMPORTS,
        )
        self.assertEqual(len(EXPECTED_PUBLIC_FACADE_EXPORTS), 44)
        self.assertEqual(set(EXPECTED_PUBLIC_FACADE_SIGNATURES), set(EXPECTED_PUBLIC_FACADE_EXPORTS))
        self.assertEqual(
            [name for name in vars(gml_transpiler) if name.startswith("_") and not name.startswith("__")],
            [],
        )
        self.assertEqual(
            {name for name in vars(gml_transpiler) if not name.startswith("_")},
            {*EXPECTED_PUBLIC_FACADE_EXPORTS, "annotations"},
        )
        for name, _owner in EXPECTED_FACADE_BINDINGS:
            with self.subTest(name=name):
                self.assertIs(getattr(gml_transpiler, name), EXPECTED_FACADE_VALUES[name])
                expected_signature = EXPECTED_PUBLIC_FACADE_SIGNATURES[name]
                value = cast(object, getattr(gml_transpiler, name))
                if expected_signature is None:
                    self.assertFalse(callable(value))
                else:
                    self.assertTrue(callable(value))
                    callable_value = cast(Callable[..., object], value)
                    self.assertEqual(
                        str(inspect.signature(callable_value, eval_str=False)),
                        expected_signature,
                    )

    def test_facade_parser_rejects_implicit_unexpected_and_nested_forms(self) -> None:
        preamble = "from __future__ import annotations\n__all__ = [\"transpile_gml_code\"]\n"
        invalid_sources = {
            "implicit": (
                "from src.conversion.gml_transpiler_parts.api import transpile_gml_code",
                "Facade reexport must be explicit",
            ),
            "wildcard": (
                "from src.conversion.gml_transpiler_parts.api import *",
                "Facade reexport must be explicit",
            ),
            "module": (
                "import src.conversion.gml_transpiler_parts.api as api",
                "Facade may contain only",
            ),
            "external": ("from os import path as path", "Unexpected facade import owner"),
            "nested": (
                "if True:\n    from src.conversion.gml_transpiler_parts.api import transpile_gml_code as transpile_gml_code",
                "Facade may contain only",
            ),
            "duplicate": (
                "from src.conversion.gml_transpiler_parts.api import transpile_gml_code as transpile_gml_code\n"
                "from src.conversion.gml_transpiler_parts.api import transpile_gml_code as transpile_gml_code",
                "Duplicate facade reexport",
            ),
            "rebound": (
                "from src.conversion.gml_transpiler_parts.api import transpile_gml_code as transpile_gml_code\n"
                "transpile_gml_code = None",
                "Facade may contain only",
            ),
        }
        for case, (source, message) in invalid_sources.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, message):
                    facade_reexports_from_source(
                        f"{preamble}{source}\n",
                        FACADE_MODULE,
                        allowed_owner_prefix=PARTS_PACKAGE,
                    )

    def test_repository_has_zero_cross_module_private_or_module_object_imports(self) -> None:
        violations = _repository_violations()
        self.assertEqual(violations, frozenset(), _format_violations(violations))

    def test_production_cannot_import_architecture_test_support(self) -> None:
        consumer = "src.conversion.synthetic_consumer"
        source = """
from tests.gml_transpiler_architecture_support import structural_import_violations
from tests import gml_transpiler_architecture_support as package_support
import tests.gml_transpiler_architecture_support as support
from importlib import import_module as load_module
load_module("tests.gml_transpiler_architecture_support")
__import__(name="tests.gml_transpiler_architecture_support")
"""
        violations = _test_support_import_violations(source, consumer)
        self.assertEqual(
            {(violation.owner, violation.name, violation.form) for violation in violations},
            {
                (TEST_SUPPORT_MODULE, "structural_import_violations", "test-support-import"),
                (TEST_SUPPORT_MODULE, MODULE_IMPORT_NAME, "test-support-import"),
                (TEST_SUPPORT_MODULE, MODULE_IMPORT_NAME, "test-support-module"),
                (TEST_SUPPORT_MODULE, MODULE_IMPORT_NAME, "module-import"),
                (TEST_SUPPORT_MODULE, MODULE_IMPORT_NAME, "dynamic-import"),
            },
        )
        self.assertEqual(_production_test_support_violations(), frozenset())
        for support_module in TEST_SUPPORT_MODULES:
            with self.subTest(support_module=support_module):
                source = f'import importlib\nimportlib.import_module("{support_module}")'
                self.assertEqual(
                    _test_support_import_violations(source, consumer),
                    frozenset({ImportViolation(
                        consumer, support_module, MODULE_IMPORT_NAME, "dynamic-import", 2
                    )}),
                )
    def test_phase_cohorts_keep_one_way_dependency_direction(self) -> None:
        violations = _phase_direction_violations()
        self.assertEqual(
            violations,
            frozenset(),
            "\n".join(f"  {edge}" for edge in sorted(violations)),
        )

    def test_recursive_grammar_gateway_is_explicit_and_deferred(self) -> None:
        parser_path = PARTS_PATH / "expression_parser.py"
        source = parser_path.read_text(encoding="utf-8")
        all_edges = import_edges_from_source(source, EXPRESSION_PARSER_MODULE)
        statement_edges = frozenset(
            edge
            for edge in all_edges
            if edge.owner in {STATEMENT_API_MODULE, STATEMENT_MODELS_MODULE}
        )
        self.assertEqual(statement_edges, DEFERRED_GRAMMAR_GATEWAY)
        top_level_edges = top_level_import_edges_from_source(source, EXPRESSION_PARSER_MODULE)
        self.assertEqual(
            frozenset(edge for edge in top_level_edges if edge.owner == STATEMENT_API_MODULE),
            frozenset(),
        )

    def test_legacy_model_alias_module_is_removed(self) -> None:
        self.assertFalse((PARTS_PATH / "model.py").exists())

    def test_transpiler_private_usage_suppressions_are_zero(self) -> None:
        self.assertEqual(_private_usage_suppressions(), frozenset())


if __name__ == "__main__":
    unittest.main()
