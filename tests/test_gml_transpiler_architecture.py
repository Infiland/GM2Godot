from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import inspect
from pathlib import Path
from typing import cast
import unittest

import src.conversion.gml_transpiler as gml_transpiler
from src.conversion.gml_transpiler_parts import constants as language_metadata
from src.conversion.gml_transpiler_parts import expression_api as expression_phase_api
from src.conversion.gml_transpiler_parts import lexical_api as lexical_phase_api
from src.conversion.gml_transpiler_parts import statement_api as statement_phase_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACADE_MODULE = "src.conversion.gml_transpiler"
PARTS_PACKAGE = "src.conversion.gml_transpiler_parts"
FACADE_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler.py"
PARTS_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts"
MODULE_IMPORT_NAME = "<module>"
LEXICAL_API_MODULE = f"{PARTS_PACKAGE}.lexical_api"
LEXICAL_IMPLEMENTATION_MODULES = frozenset(
    {
        f"{PARTS_PACKAGE}.identifiers",
        f"{PARTS_PACKAGE}.lexical",
        f"{PARTS_PACKAGE}.preprocessor",
        f"{PARTS_PACKAGE}.tokens",
    }
)
LEGACY_LEXICAL_FACADE_NAMES = frozenset({"_expression_tokens", "_tokenize"})
LEGACY_LEXICAL_FACADE_ACCESS_BY_CONSUMER = {
    "tests.test_gml_lexical_api": LEGACY_LEXICAL_FACADE_NAMES,
}
LOW_LEVEL_LEXICAL_IMPORTS_BY_CONSUMER = {
    f"{PARTS_PACKAGE}.utils": frozenset(
        {
            (f"{PARTS_PACKAGE}.lexical", "is_verbatim_string_start"),
            (f"{PARTS_PACKAGE}.lexical", "read_verbatim_string"),
            (f"{PARTS_PACKAGE}.tokens", "read_template_string"),
        }
    )
}
EXPRESSION_API_MODULE = f"{PARTS_PACKAGE}.expression_api"
EXPRESSION_IMPLEMENTATION_MODULES = frozenset(
    {
        f"{PARTS_PACKAGE}.emitter",
        f"{PARTS_PACKAGE}.enum_helpers",
        f"{PARTS_PACKAGE}.expression_parser",
        f"{PARTS_PACKAGE}.expression_service",
        f"{PARTS_PACKAGE}.function_helpers",
    }
)
EXPRESSION_UTILITY_MODULE = f"{PARTS_PACKAGE}.utils"
EXPRESSION_UTILITY_NAMES = frozenset(
    {
        "normalize_local_names",
        "normalize_scope_context",
        "scope_context_with_global_names",
        "strip_comments",
        "tokens_to_source",
        "unwrap_grouped_expression",
    }
)
LEGACY_EXPRESSION_FACADE_NAMES = frozenset(
    {
        "_ArrayLiteral",
        "_Binary",
        "_Call",
        "_DSMapAccess",
        "_Expression",
        "_ExpressionParser",
        "_FunctionLiteral",
        "_FunctionParameter",
        "_Grouped",
        "_Index",
        "_Literal",
        "_Member",
        "_Name",
        "_NameOf",
        "_NewCall",
        "_NumberLiteral",
        "_ScopeContext",
        "_StaticDeclaration",
        "_StringLiteral",
        "_StructAccess",
        "_StructLiteral",
        "_TemplateStringLiteral",
        "_Ternary",
        "_Token",
        "_Unary",
        "_parse_gml_expression",
    }
)
EXPRESSION_DIRECT_IMPORTS_BY_CONSUMER = {
    FACADE_MODULE: frozenset(
        {
            (f"{PARTS_PACKAGE}.expression_parser", "_ExpressionParser"),
            (f"{PARTS_PACKAGE}.expression_parser", "_parse_gml_expression"),
            (f"{PARTS_PACKAGE}.expression_service", "transpile_gml_condition"),
            (f"{PARTS_PACKAGE}.expression_service", "transpile_gml_expression"),
        }
    ),
    EXPRESSION_API_MODULE: frozenset(
        {
            (f"{PARTS_PACKAGE}.emitter", "emit_gml_expression"),
            (f"{PARTS_PACKAGE}.emitter", "emit_gml_truthy_expression"),
            (f"{PARTS_PACKAGE}.emitter", "emit_instance_keyword_argument"),
            (f"{PARTS_PACKAGE}.emitter", "name_resolves_to_global"),
            (f"{PARTS_PACKAGE}.emitter", "uses_direct_builtin_instance_members"),
            (f"{PARTS_PACKAGE}.emitter", "uses_direct_member_access"),
            (f"{PARTS_PACKAGE}.enum_helpers", "evaluate_enum_value_tokens"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_constant_assignment_target_name"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_constant_declaration_name"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_enum_assignment_target"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_enum_mutation_expression"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_readonly_builtin_assignment_target"),
            (f"{PARTS_PACKAGE}.expression_parser", "parse_gml_expression"),
            (f"{PARTS_PACKAGE}.expression_service", "transpile_gml_condition"),
            (f"{PARTS_PACKAGE}.expression_service", "transpile_gml_expression"),
            (f"{PARTS_PACKAGE}.function_helpers", "emit_constructor_inheritance_line"),
            (f"{PARTS_PACKAGE}.function_helpers", "emit_static_initialization_lines"),
        }
    ),
    f"{PARTS_PACKAGE}.emitter": frozenset(
        {
            (EXPRESSION_UTILITY_MODULE, "normalize_local_names"),
            (EXPRESSION_UTILITY_MODULE, "normalize_scope_context"),
            (EXPRESSION_UTILITY_MODULE, "unwrap_grouped_expression"),
        }
    ),
    f"{PARTS_PACKAGE}.enum_helpers": frozenset(
        {
            (f"{PARTS_PACKAGE}.expression_parser", "parse_gml_expression"),
            (EXPRESSION_UTILITY_MODULE, "normalize_local_names"),
            (EXPRESSION_UTILITY_MODULE, "tokens_to_source"),
            (EXPRESSION_UTILITY_MODULE, "unwrap_grouped_expression"),
        }
    ),
    f"{PARTS_PACKAGE}.expression_parser": frozenset(
        {
            (f"{PARTS_PACKAGE}.function_helpers", "emit_constructor_inheritance_line"),
            (f"{PARTS_PACKAGE}.function_helpers", "emit_static_initialization_lines"),
            (EXPRESSION_UTILITY_MODULE, "normalize_scope_context"),
            (EXPRESSION_UTILITY_MODULE, "strip_comments"),
        }
    ),
    f"{PARTS_PACKAGE}.expression_service": frozenset(
        {
            (f"{PARTS_PACKAGE}.emitter", "emit_gml_expression"),
            (f"{PARTS_PACKAGE}.emitter", "emit_gml_truthy_expression"),
            (f"{PARTS_PACKAGE}.enum_helpers", "reject_enum_mutation_expression"),
            (f"{PARTS_PACKAGE}.expression_parser", "parse_gml_expression"),
            (EXPRESSION_UTILITY_MODULE, "normalize_local_names"),
            (EXPRESSION_UTILITY_MODULE, "normalize_scope_context"),
            (EXPRESSION_UTILITY_MODULE, "scope_context_with_global_names"),
        }
    ),
    f"{PARTS_PACKAGE}.function_helpers": frozenset(
        {
            (f"{PARTS_PACKAGE}.emitter", "emit_gml_expression"),
            (f"{PARTS_PACKAGE}.expression_parser", "parse_gml_expression"),
        }
    ),
    f"{PARTS_PACKAGE}.statement_parser": frozenset(
        {
            (EXPRESSION_UTILITY_MODULE, "normalize_scope_context"),
            (EXPRESSION_UTILITY_MODULE, "scope_context_with_global_names"),
            (EXPRESSION_UTILITY_MODULE, "tokens_to_source"),
        }
    ),
    f"{PARTS_PACKAGE}.statements": frozenset(
        {
            (EXPRESSION_UTILITY_MODULE, "normalize_scope_context"),
            (EXPRESSION_UTILITY_MODULE, "unwrap_grouped_expression"),
        }
    ),
    f"{PARTS_PACKAGE}.static_declarations": frozenset(
        {
            (EXPRESSION_UTILITY_MODULE, "tokens_to_source"),
        }
    ),
}
STATEMENT_API_MODULE = f"{PARTS_PACKAGE}.statement_api"
STATEMENT_MODELS_MODULE = f"{PARTS_PACKAGE}.statement_models"
STATEMENT_IMPLEMENTATION_MODULES = frozenset(
    {
        f"{PARTS_PACKAGE}.statement_parser",
        f"{PARTS_PACKAGE}.statements",
        f"{PARTS_PACKAGE}.static_declarations",
    }
)
STATEMENT_UTILITY_MODULE = f"{PARTS_PACKAGE}.utils"
STATEMENT_DIRECT_IMPORTS_BY_CONSUMER = {
    f"{PARTS_PACKAGE}.api": frozenset(
        {
            (STATEMENT_UTILITY_MODULE, "prefix_multiline"),
        }
    ),
    STATEMENT_API_MODULE: frozenset(
        {
            (f"{PARTS_PACKAGE}.statement_parser", "parse_gml_statements"),
            (f"{PARTS_PACKAGE}.static_declarations", "collect_static_declarations"),
            (f"{PARTS_PACKAGE}.static_declarations", "static_scope_id"),
        }
    ),
    f"{PARTS_PACKAGE}.statement_parser": frozenset(
        {
            (f"{PARTS_PACKAGE}.statements", "control_flow_dispatch_lines"),
            (f"{PARTS_PACKAGE}.statements", "transpile_statement"),
            (f"{PARTS_PACKAGE}.static_declarations", "read_static_declaration_tokens"),
            (STATEMENT_UTILITY_MODULE, "indent_lines"),
            (STATEMENT_UTILITY_MODULE, "insert_lines_before_continue"),
            (STATEMENT_UTILITY_MODULE, "insert_until_check_before_continue"),
            (STATEMENT_UTILITY_MODULE, "macro_configuration_matches"),
            (STATEMENT_UTILITY_MODULE, "normalize_scope_context"),
            (STATEMENT_UTILITY_MODULE, "scope_context_with_global_names"),
            (STATEMENT_UTILITY_MODULE, "split_top_level_tokens"),
            (STATEMENT_UTILITY_MODULE, "tokens_to_source"),
        }
    ),
    f"{PARTS_PACKAGE}.statements": frozenset(
        {
            (STATEMENT_UTILITY_MODULE, "cache_assignment_part"),
            (STATEMENT_UTILITY_MODULE, "indent_lines"),
            (STATEMENT_UTILITY_MODULE, "next_generated_name_from_counter"),
            (STATEMENT_UTILITY_MODULE, "normalize_scope_context"),
            (STATEMENT_UTILITY_MODULE, "split_assignment"),
            (STATEMENT_UTILITY_MODULE, "split_top_level"),
            (STATEMENT_UTILITY_MODULE, "unwrap_grouped_expression"),
        }
    ),
    f"{PARTS_PACKAGE}.static_declarations": frozenset(
        {
            (STATEMENT_UTILITY_MODULE, "split_assignment"),
            (STATEMENT_UTILITY_MODULE, "split_top_level"),
            (STATEMENT_UTILITY_MODULE, "tokens_to_source"),
        }
    ),
    "tests.test_gml_statement_api": frozenset(
        {
            (STATEMENT_API_MODULE, MODULE_IMPORT_NAME),
            (STATEMENT_MODELS_MODULE, MODULE_IMPORT_NAME),
        }
    ),
    "tests.test_gml_transpiler_architecture": frozenset(
        {
            (STATEMENT_API_MODULE, MODULE_IMPORT_NAME),
        }
    ),
}


class BoundaryClassification(str, Enum):
    SUPPORTED_PUBLIC_FACADE = "supported public facade API"
    INTENDED_PACKAGE_INTERNAL = "intended package-internal phase API to be renamed/exposed"
    MODULE_PRIVATE = "module-private implementation to be moved behind an owner API"


@dataclass(frozen=True, order=True)
class ImportEdge:
    consumer: str
    owner: str
    name: str


@dataclass(frozen=True)
class BoundaryDisposition:
    classification: BoundaryClassification
    removal_stage: int | None


# This is the complete supported facade, in its intentional __all__ order. Private
# compatibility leakage is frozen separately below and remains scheduled for #820.
EXPECTED_PUBLIC_FACADE_EXPORTS = (
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
)

EXPECTED_LEGACY_PRIVATE_FACADE_EXPORTS = (
    "_ArrayLiteral",
    "_Binary",
    "_BuiltinVariableMetadata",
    "_BUILTIN_VARIABLE_REGISTRY",
    "_Call",
    "_DSMapAccess",
    "_Expression",
    "_ExpressionParser",
    "_FunctionLiteral",
    "_FunctionParameter",
    "_Grouped",
    "_Index",
    "_Literal",
    "_Member",
    "_Name",
    "_NameOf",
    "_NewCall",
    "_NumberLiteral",
    "_ScopeContext",
    "_StaticDeclaration",
    "_StringLiteral",
    "_StructAccess",
    "_StructLiteral",
    "_TemplateStringLiteral",
    "_Ternary",
    "_Token",
    "_Unary",
    "_expression_tokens",
    "_parse_gml_expression",
    "_tokenize",
)

# inspect.signature is used deliberately: it freezes positional/keyword shape,
# defaults, and annotations without calling any facade object.
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
    "GMLTranspileResult": (
        "(code: 'str', source_map: 'GMLSourceMap', static_scope_id: 'str | None' = None) -> None"
    ),
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


# Each line is consumer|owner|comma-separated imported names. The first section
# inventories every private cross-module import inside the facade and phase
# package. The second records every production import from either surface,
# including supported public imports.
EXPECTED_INTERNAL_PRIVATE_IMPORT_GROUPS = """
src.conversion.gml_transpiler|src.conversion.gml_transpiler_parts.constants|_BUILTIN_VARIABLE_REGISTRY
src.conversion.gml_transpiler|src.conversion.gml_transpiler_parts.expression_parser|_ExpressionParser,_parse_gml_expression
src.conversion.gml_transpiler|src.conversion.gml_transpiler_parts.model|_ArrayLiteral,_Binary,_BuiltinVariableMetadata,_Call,_DSMapAccess,_Expression,_FunctionLiteral,_FunctionParameter,_Grouped,_Index,_Literal,_Member,_Name,_NameOf,_NewCall,_NumberLiteral,_ScopeContext,_StaticDeclaration,_StringLiteral,_StructAccess,_StructLiteral,_TemplateStringLiteral,_Ternary,_Token,_Unary
src.conversion.gml_transpiler_parts.preprocessor|src.conversion.gml_transpiler_parts.utils|_join_macro_continuation_lines,_macro_configuration_matches,_strip_comments
"""

EXPECTED_PRODUCTION_IMPORT_GROUPS = """
src.cli|src.conversion.gml_transpiler|generate_gml_api_compatibility_report,render_gml_manual_scope_markdown
src.conversion.asset_registry|src.conversion.gml_transpiler|GMLTranspileError,transpile_gml_code
src.conversion.extension_registry|src.conversion.gml_transpiler_parts.extension_functions|EXTENSION_FUNCTION_MAPPING_FILENAME,load_gml_extension_function_mappings
src.conversion.gml_runtime_parts.manifest|src.conversion.gml_transpiler_parts.gml_api_manifest|iter_gml_api_entries
src.conversion.objects|src.conversion.gml_transpiler|GMLSourceMap,GMLTranspileError,analyze_gml_source_identifiers,merge_gml_source_maps,transpile_gml_code_with_source_map,write_gml_source_map
src.conversion.objects|src.conversion.gml_transpiler_parts.constants|ASSIGNMENT_OPERATORS,BUILTIN_GLOBAL_VARIABLES,BUILTIN_INSTANCE_VARIABLES,GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS,GML_LITERAL_IDENTIFIERS
src.conversion.objects|src.conversion.gml_transpiler_parts.lexical_api|preprocess_gml_source,tokenize_gml_source
src.conversion.objects|src.conversion.gml_transpiler_parts.shared_models|Token
src.conversion.project_enums|src.conversion.gml_transpiler_parts.expression_api|evaluate_enum_value_tokens
src.conversion.project_enums|src.conversion.gml_transpiler_parts.lexical_api|preprocess_gml_source,tokenize_gml_source
src.conversion.project_enums|src.conversion.gml_transpiler_parts.shared_models|GMLTranspileError,Token
src.conversion.project_macros|src.conversion.gml_transpiler_parts.lexical_api|preprocess_gml_source,tokenize_gml_source
src.conversion.project_macros|src.conversion.gml_transpiler_parts.shared_models|GMLTranspileError,Token
src.conversion.project_macros|src.conversion.gml_transpiler_parts.utils|_macro_configuration_matches,_tokens_to_source
src.conversion.rooms|src.conversion.gml_transpiler|GMLTranspileError,transpile_gml_code
src.conversion.script_functions|src.conversion.gml_transpiler|GMLTranspileError
src.conversion.script_functions|src.conversion.gml_transpiler_parts.lexical_api|is_verbatim_string_start,preprocess_gml_source_preserving_layout,read_template_string,read_verbatim_string,validate_gml_identifier
src.conversion.script_functions|src.conversion.gml_transpiler_parts.utils|_split_assignment,_split_top_level
src.conversion.script_generator|src.conversion.gml_transpiler_parts.constants|GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS
src.conversion.script_generator|src.conversion.gml_transpiler_parts.lexical_api|sanitize_gdscript_identifier
src.conversion.scripts|src.conversion.gml_transpiler|EXTENSION_FUNCTION_MAPPING_FILENAME,GMLExtensionFunction,GMLExtensionFunctionMapping,GMLSourceMap,GMLTranspileError,analyze_gml_source_identifiers,load_gml_extension_function_mappings,merge_gml_source_maps,render_gml_source_header,transpile_gml_code_with_source_map,write_gml_source_map
src.conversion.scripts|src.conversion.gml_transpiler_parts.expression_api|emit_constructor_inheritance_line,parse_gml_expression,transpile_gml_expression
src.conversion.scripts|src.conversion.gml_transpiler_parts.lexical_api|sanitize_gdscript_identifier
src.conversion.scripts|src.conversion.gml_transpiler_parts.shared_models|ScopeContext
"""


def _parse_import_groups(groups: str) -> frozenset[ImportEdge]:
    edges: set[ImportEdge] = set()
    for line in groups.strip().splitlines():
        consumer, owner, imported_names = line.split("|")
        for name in imported_names.split(","):
            edge = ImportEdge(consumer=consumer, owner=owner, name=name)
            if edge in edges:
                raise ValueError(f"Duplicate frozen GML transpiler import edge: {edge}")
            edges.add(edge)
    return frozenset(edges)


EXPECTED_INTERNAL_PRIVATE_IMPORTS = _parse_import_groups(EXPECTED_INTERNAL_PRIVATE_IMPORT_GROUPS)
EXPECTED_PRODUCTION_IMPORTS = _parse_import_groups(EXPECTED_PRODUCTION_IMPORT_GROUPS)
EXPECTED_ALL_IMPORTS = EXPECTED_INTERNAL_PRIVATE_IMPORTS | EXPECTED_PRODUCTION_IMPORTS


# The two owner modules below contain shared data or language metadata whose
# remaining facade compatibility aliases are assigned to #820.
ALL_PRIVATE_NAMES_ARE_INTENDED_INTERNAL = frozenset(
    {
        f"{PARTS_PACKAGE}.constants",
        f"{PARTS_PACKAGE}.model",
    }
)

INTENDED_INTERNAL_NAMES_BY_MIXED_OWNER: dict[str, frozenset[str]] = {
    f"{PARTS_PACKAGE}.expression_parser": frozenset({"_parse_gml_expression"}),
    f"{PARTS_PACKAGE}.utils": frozenset(
        {
            "_macro_configuration_matches",
            "_split_assignment",
            "_split_top_level",
            "_strip_comments",
            "_tokens_to_source",
        }
    ),
}

MODULE_PRIVATE_NAMES_BY_MIXED_OWNER: dict[str, frozenset[str]] = {
    f"{PARTS_PACKAGE}.expression_parser": frozenset({"_ExpressionParser"}),
    f"{PARTS_PACKAGE}.utils": frozenset({"_join_macro_continuation_lines"}),
}

RETAINED_PACKAGE_INTERNAL_EXPORTS = frozenset(
    {
        (f"{PARTS_PACKAGE}.preprocessor", "preprocess_gml_source_preserving_layout"),
        (f"{PARTS_PACKAGE}.shared_models", "ScopeContext"),
        (f"{PARTS_PACKAGE}.shared_models", "Token"),
    }
)

MIGRATION_STAGE_BY_OWNER: dict[str, int] = {}

UTILS_STAGE_BY_CONSUMER: dict[str, int] = {
    f"{PARTS_PACKAGE}.preprocessor": 817,
    "src.conversion.project_macros": 817,
    "src.conversion.script_functions": 817,
}


def _disposition_for(edge: ImportEdge) -> BoundaryDisposition:
    if edge.name in EXPECTED_PUBLIC_FACADE_EXPORTS:
        return BoundaryDisposition(BoundaryClassification.SUPPORTED_PUBLIC_FACADE, None)
    if edge.owner == f"{PARTS_PACKAGE}.constants" and edge.name in language_metadata.__all__:
        return BoundaryDisposition(BoundaryClassification.INTENDED_PACKAGE_INTERNAL, None)
    if edge.owner == LEXICAL_API_MODULE and edge.name in lexical_phase_api.__all__:
        return BoundaryDisposition(BoundaryClassification.INTENDED_PACKAGE_INTERNAL, None)
    if edge.owner == EXPRESSION_API_MODULE and edge.name in expression_phase_api.__all__:
        return BoundaryDisposition(BoundaryClassification.INTENDED_PACKAGE_INTERNAL, None)
    if edge.owner == STATEMENT_API_MODULE and edge.name in statement_phase_api.__all__:
        return BoundaryDisposition(BoundaryClassification.INTENDED_PACKAGE_INTERNAL, None)
    if (edge.owner, edge.name) in RETAINED_PACKAGE_INTERNAL_EXPORTS:
        return BoundaryDisposition(BoundaryClassification.INTENDED_PACKAGE_INTERNAL, None)
    if not edge.name.startswith("_"):
        raise ValueError(f"Unclassified non-private transpiler import: {edge}")

    if edge.owner in ALL_PRIVATE_NAMES_ARE_INTENDED_INTERNAL:
        classification = BoundaryClassification.INTENDED_PACKAGE_INTERNAL
    elif edge.name in INTENDED_INTERNAL_NAMES_BY_MIXED_OWNER.get(edge.owner, frozenset()):
        classification = BoundaryClassification.INTENDED_PACKAGE_INTERNAL
    elif edge.name in MODULE_PRIVATE_NAMES_BY_MIXED_OWNER.get(edge.owner, frozenset()):
        classification = BoundaryClassification.MODULE_PRIVATE
    else:
        raise ValueError(f"Unclassified private transpiler import: {edge}")

    if edge.consumer == FACADE_MODULE:
        removal_stage = 820
    elif edge.owner == f"{PARTS_PACKAGE}.utils":
        try:
            removal_stage = UTILS_STAGE_BY_CONSUMER[edge.consumer]
        except KeyError as exc:
            raise ValueError(f"Unstaged private utility import: {edge}") from exc
    else:
        try:
            removal_stage = MIGRATION_STAGE_BY_OWNER[edge.owner]
        except KeyError as exc:
            raise ValueError(f"Unstaged private transpiler import: {edge}") from exc
    return BoundaryDisposition(classification, removal_stage)


EXPECTED_PRIVATE_USAGE_SUPPRESSIONS = frozenset(
    {
        ("src/conversion/gml_transpiler.py", 1, "# pyright: reportPrivateUsage=false"),
        (
            "src/conversion/gml_transpiler_parts/gml_api_manifest.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/preprocessor.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
    }
)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import_owner(consumer: str, node: ast.ImportFrom, *, package_module: bool) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = consumer.split(".") if package_module else consumer.split(".")[:-1]
    parent_hops = node.level - 1
    if parent_hops > len(package_parts):
        raise ValueError(f"Relative import escapes package in {consumer}:{node.lineno}")
    owner_parts = package_parts[: len(package_parts) - parent_hops]
    if node.module:
        owner_parts.extend(node.module.split("."))
    return ".".join(owner_parts)


def _imports_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    edges: set[ImportEdge] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            owner = _resolve_import_owner(consumer, node, package_module=package_module)
            if owner == consumer:
                continue
            for imported_name in node.names:
                edges.add(ImportEdge(consumer=consumer, owner=owner, name=imported_name.name))
        elif isinstance(node, ast.Import):
            for imported_module in node.names:
                module_parts = imported_module.name.split(".")
                if module_parts[-1].startswith("_"):
                    edges.add(
                        ImportEdge(
                            consumer=consumer,
                            owner=".".join(module_parts[:-1]),
                            name=module_parts[-1],
                        )
                    )
                else:
                    edges.add(
                        ImportEdge(
                            consumer=consumer,
                            owner=imported_module.name,
                            name=MODULE_IMPORT_NAME,
                        )
                    )
    return frozenset(edges)


def _imports_from_path(path: Path) -> frozenset[ImportEdge]:
    return _imports_from_source(
        path.read_text(encoding="utf-8"),
        _module_name(path),
        package_module=path.name == "__init__.py",
    )


def _lexical_boundary_bypasses_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    for edge in _imports_from_source(
        source,
        consumer,
        package_module=package_module,
    ):
        if edge.owner in LEXICAL_IMPLEMENTATION_MODULES:
            bypasses.add(edge)
            continue

        imported_module = f"{edge.owner}.{edge.name}"
        if imported_module in LEXICAL_IMPLEMENTATION_MODULES:
            bypasses.add(
                ImportEdge(
                    consumer=consumer,
                    owner=imported_module,
                    name=MODULE_IMPORT_NAME,
                )
            )
            continue

        if edge.owner == FACADE_MODULE and (
            edge.name in LEGACY_LEXICAL_FACADE_NAMES or edge.name == "*"
        ):
            bypasses.add(edge)

    tree = ast.parse(source)
    facade_bindings: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported_module in node.names:
                if imported_module.name != FACADE_MODULE:
                    continue
                if imported_module.asname is not None:
                    facade_bindings.add((imported_module.asname,))
                else:
                    facade_bindings.add(tuple(FACADE_MODULE.split(".")))
        elif isinstance(node, ast.ImportFrom):
            owner = _resolve_import_owner(
                consumer,
                node,
                package_module=package_module,
            )
            for imported_name in node.names:
                if f"{owner}.{imported_name.name}" != FACADE_MODULE:
                    continue
                facade_bindings.add((imported_name.asname or imported_name.name,))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        name_parts = _attribute_name_parts(node)
        if name_parts is None:
            continue
        for binding in facade_bindings:
            if name_parts[: len(binding)] != binding or len(name_parts) <= len(binding):
                continue
            accessed_name = name_parts[len(binding)]
            if accessed_name in LEGACY_LEXICAL_FACADE_NAMES:
                bypasses.add(
                    ImportEdge(
                        consumer=consumer,
                        owner=FACADE_MODULE,
                        name=accessed_name,
                    )
                )
    return frozenset(bypasses)


def _attribute_name_parts(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if not isinstance(node, ast.Attribute):
        return None
    parent = _attribute_name_parts(node.value)
    if parent is None:
        return None
    return (*parent, node.attr)


def _expression_boundary_bypasses_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    owner_modules = EXPRESSION_IMPLEMENTATION_MODULES | frozenset(
        {EXPRESSION_UTILITY_MODULE}
    )
    for edge in _imports_from_source(
        source,
        consumer,
        package_module=package_module,
    ):
        if edge.owner in EXPRESSION_IMPLEMENTATION_MODULES:
            bypasses.add(edge)
            continue

        imported_module = f"{edge.owner}.{edge.name}"
        if imported_module in owner_modules:
            bypasses.add(
                ImportEdge(
                    consumer=consumer,
                    owner=imported_module,
                    name=MODULE_IMPORT_NAME,
                )
            )
            continue

        if edge.owner == EXPRESSION_UTILITY_MODULE and (
            edge.name in EXPRESSION_UTILITY_NAMES or edge.name == "*"
        ):
            bypasses.add(edge)
            continue

        if edge.owner == FACADE_MODULE and (
            edge.name in LEGACY_EXPRESSION_FACADE_NAMES or edge.name == "*"
        ):
            bypasses.add(edge)

    tree = ast.parse(source)
    facade_bindings: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported_module in node.names:
                if imported_module.name != FACADE_MODULE:
                    continue
                if imported_module.asname is not None:
                    facade_bindings.add((imported_module.asname,))
                else:
                    facade_bindings.add(tuple(FACADE_MODULE.split(".")))
        elif isinstance(node, ast.ImportFrom):
            owner = _resolve_import_owner(
                consumer,
                node,
                package_module=package_module,
            )
            for imported_name in node.names:
                if f"{owner}.{imported_name.name}" != FACADE_MODULE:
                    continue
                facade_bindings.add((imported_name.asname or imported_name.name,))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        name_parts = _attribute_name_parts(node)
        if name_parts is None:
            continue
        for binding in facade_bindings:
            if name_parts[: len(binding)] != binding or len(name_parts) <= len(binding):
                continue
            accessed_name = name_parts[len(binding)]
            if accessed_name in LEGACY_EXPRESSION_FACADE_NAMES:
                bypasses.add(
                    ImportEdge(
                        consumer=consumer,
                        owner=FACADE_MODULE,
                        name=accessed_name,
                    )
                )
    return frozenset(bypasses)


def _expression_boundary_import_is_allowed(
    consumer: str,
    edge: ImportEdge,
) -> bool:
    return (edge.owner, edge.name) in EXPRESSION_DIRECT_IMPORTS_BY_CONSUMER.get(
        consumer,
        frozenset(),
    )


def _actual_expression_boundary_bypasses() -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    for source_root in (PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
        for path in sorted(source_root.rglob("*.py")):
            consumer = _module_name(path)
            bypasses.update(
                edge
                for edge in _expression_boundary_bypasses_from_source(
                    path.read_text(encoding="utf-8"),
                    consumer,
                    package_module=path.name == "__init__.py",
                )
                if not _expression_boundary_import_is_allowed(consumer, edge)
            )
    return frozenset(bypasses)


def _statement_boundary_bypasses_from_source(
    source: str,
    consumer: str,
    *,
    package_module: bool = False,
) -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    for edge in _imports_from_source(
        source,
        consumer,
        package_module=package_module,
    ):
        if edge.owner in STATEMENT_IMPLEMENTATION_MODULES:
            bypasses.add(edge)
            continue

        imported_module = f"{edge.owner}.{edge.name}"
        if imported_module in STATEMENT_IMPLEMENTATION_MODULES:
            bypasses.add(
                ImportEdge(
                    consumer=consumer,
                    owner=imported_module,
                    name=MODULE_IMPORT_NAME,
                )
            )
            continue

        if edge.owner in {STATEMENT_API_MODULE, STATEMENT_MODELS_MODULE} and edge.name in {
            MODULE_IMPORT_NAME,
            "*",
        }:
            bypasses.add(edge)
            continue

        if edge.owner == STATEMENT_UTILITY_MODULE and (
            not edge.name.startswith("_") or edge.name in {MODULE_IMPORT_NAME, "*"}
        ):
            bypasses.add(edge)
            continue

        if imported_module in {
            STATEMENT_API_MODULE,
            STATEMENT_MODELS_MODULE,
            STATEMENT_UTILITY_MODULE,
        }:
            bypasses.add(
                ImportEdge(
                    consumer=consumer,
                    owner=imported_module,
                    name=MODULE_IMPORT_NAME,
                )
            )
    return frozenset(bypasses)


def _statement_boundary_import_is_allowed(
    consumer: str,
    edge: ImportEdge,
) -> bool:
    owner_and_name = (edge.owner, edge.name)
    return owner_and_name in STATEMENT_DIRECT_IMPORTS_BY_CONSUMER.get(
        consumer,
        frozenset(),
    ) or owner_and_name in EXPRESSION_DIRECT_IMPORTS_BY_CONSUMER.get(
        consumer,
        frozenset(),
    )


def _actual_statement_boundary_bypasses() -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    for source_root in (PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
        for path in sorted(source_root.rglob("*.py")):
            consumer = _module_name(path)
            bypasses.update(
                edge
                for edge in _statement_boundary_bypasses_from_source(
                    path.read_text(encoding="utf-8"),
                    consumer,
                    package_module=path.name == "__init__.py",
                )
                if not _statement_boundary_import_is_allowed(consumer, edge)
            )
    return frozenset(bypasses)


def _lexical_boundary_import_is_allowed(
    consumer: str,
    edge: ImportEdge,
) -> bool:
    if consumer in LEXICAL_IMPLEMENTATION_MODULES or consumer == LEXICAL_API_MODULE:
        return (
            edge.owner in LEXICAL_IMPLEMENTATION_MODULES
            and edge.name != MODULE_IMPORT_NAME
            and not edge.name.startswith("_")
        )
    if (edge.owner, edge.name) in LOW_LEVEL_LEXICAL_IMPORTS_BY_CONSUMER.get(
        consumer,
        frozenset(),
    ):
        return True
    return (
        edge.owner == FACADE_MODULE
        and edge.name
        in LEGACY_LEXICAL_FACADE_ACCESS_BY_CONSUMER.get(consumer, frozenset())
    )


def _actual_lexical_boundary_bypasses() -> frozenset[ImportEdge]:
    bypasses: set[ImportEdge] = set()
    for source_root in (PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
        for path in sorted(source_root.rglob("*.py")):
            consumer = _module_name(path)
            bypasses.update(
                edge
                for edge in _lexical_boundary_bypasses_from_source(
                    path.read_text(encoding="utf-8"),
                    consumer,
                    package_module=path.name == "__init__.py",
                )
                if not _lexical_boundary_import_is_allowed(consumer, edge)
            )
    return frozenset(bypasses)


def _internal_module_paths() -> tuple[Path, ...]:
    return (FACADE_PATH, *tuple(sorted(PARTS_PATH.glob("*.py"))))


def _actual_internal_private_imports() -> frozenset[ImportEdge]:
    edges: set[ImportEdge] = set()
    for path in _internal_module_paths():
        edges.update(edge for edge in _imports_from_path(path) if edge.name.startswith("_"))
    return frozenset(edges)


def _is_transpiler_surface(owner: str) -> bool:
    return owner == FACADE_MODULE or owner == PARTS_PACKAGE or owner.startswith(f"{PARTS_PACKAGE}.")


def _as_production_surface_edge(edge: ImportEdge) -> ImportEdge | None:
    if _is_transpiler_surface(edge.owner):
        return edge
    imported_module = f"{edge.owner}.{edge.name}"
    if _is_transpiler_surface(imported_module):
        return ImportEdge(edge.consumer, imported_module, MODULE_IMPORT_NAME)
    return None


def _actual_production_imports() -> frozenset[ImportEdge]:
    internal_paths = set(_internal_module_paths())
    edges: set[ImportEdge] = set()
    for path in sorted((PROJECT_ROOT / "src").rglob("*.py")):
        if path in internal_paths:
            continue
        for edge in _imports_from_path(path):
            surface_edge = _as_production_surface_edge(edge)
            if surface_edge is not None:
                edges.add(surface_edge)
    return frozenset(edges)


def _actual_private_usage_suppressions() -> frozenset[tuple[str, int, str]]:
    suppressions: set[tuple[str, int, str]] = set()
    for path in _internal_module_paths():
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "pyright:" in line and "reportPrivateUsage" in line:
                suppressions.add((relative_path, line_number, line.strip()))
    return frozenset(suppressions)


def _format_edge_difference(
    expected: frozenset[ImportEdge],
    actual: frozenset[ImportEdge],
) -> str:
    missing = "\n".join(f"  stale: {edge}" for edge in sorted(expected - actual))
    unexpected = "\n".join(f"  new: {edge}" for edge in sorted(actual - expected))
    return "\n".join(part for part in (missing, unexpected) if part)


class TestGMLTranspilerArchitecture(unittest.TestCase):
    def test_ast_scanner_handles_relative_absolute_aliased_and_parenthesized_imports(self) -> None:
        source = """
from .shared_models import (
    ScopeContext as _ScopeContext,
    Token,
)
from src.conversion.gml_transpiler_parts.tokens import (
    _tokenize as tokenize,
)
import src.conversion.gml_transpiler_parts.api as phase_api
"""
        self.assertEqual(
            _imports_from_source(
                source,
                "src.conversion.gml_transpiler_parts.synthetic_consumer",
            ),
            frozenset(
                {
                    ImportEdge(
                        "src.conversion.gml_transpiler_parts.synthetic_consumer",
                        "src.conversion.gml_transpiler_parts.shared_models",
                        "ScopeContext",
                    ),
                    ImportEdge(
                        "src.conversion.gml_transpiler_parts.synthetic_consumer",
                        "src.conversion.gml_transpiler_parts.shared_models",
                        "Token",
                    ),
                    ImportEdge(
                        "src.conversion.gml_transpiler_parts.synthetic_consumer",
                        "src.conversion.gml_transpiler_parts.tokens",
                        "_tokenize",
                    ),
                    ImportEdge(
                        "src.conversion.gml_transpiler_parts.synthetic_consumer",
                        "src.conversion.gml_transpiler_parts.api",
                        MODULE_IMPORT_NAME,
                    ),
                }
            ),
        )

    def test_lexical_boundary_scanner_rejects_private_and_module_bypasses(
        self,
    ) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        source = """
from .tokens import (
    _read_number as relative_parenthesized_alias,
)
from src.conversion.gml_transpiler_parts.identifiers import (
    _validate_gml_identifier as absolute_parenthesized_alias,
)
from .lexical import _read_verbatim_string as relative_alias
from src.conversion.gml_transpiler_parts.preprocessor import _source_line_spans
from . import tokens as token_module
from src.conversion.gml_transpiler_parts import identifiers as identifier_module
import src.conversion.gml_transpiler_parts.lexical as lexical_module
from src.conversion.gml_transpiler import _tokenize as legacy_facade_bypass
from src.conversion.gml_transpiler import *
import src.conversion.gml_transpiler as facade_module
from src.conversion import gml_transpiler as package_facade

facade_module._expression_tokens("value")
package_facade._tokenize("value")
"""

        self.assertEqual(
            _lexical_boundary_bypasses_from_source(source, consumer),
            frozenset(
                {
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.tokens",
                        "_read_number",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.identifiers",
                        "_validate_gml_identifier",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.lexical",
                        "_read_verbatim_string",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.preprocessor",
                        "_source_line_spans",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.tokens",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.identifiers",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.lexical",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "_tokenize",
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "_expression_tokens",
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "*",
                    ),
                }
            ),
        )
        owner_consumer = f"{PARTS_PACKAGE}.tokens"
        self.assertTrue(
            _lexical_boundary_import_is_allowed(
                owner_consumer,
                ImportEdge(
                    owner_consumer,
                    f"{PARTS_PACKAGE}.lexical",
                    "read_verbatim_string",
                ),
            )
        )
        self.assertFalse(
            _lexical_boundary_import_is_allowed(
                owner_consumer,
                ImportEdge(
                    owner_consumer,
                    f"{PARTS_PACKAGE}.lexical",
                    "_read_verbatim_string",
                ),
            )
        )
        compatibility_consumer = "tests.test_gml_lexical_api"
        self.assertTrue(
            _lexical_boundary_import_is_allowed(
                compatibility_consumer,
                ImportEdge(
                    compatibility_consumer,
                    FACADE_MODULE,
                    "_tokenize",
                ),
            )
        )
        self.assertFalse(
            _lexical_boundary_import_is_allowed(
                owner_consumer,
                ImportEdge(
                    owner_consumer,
                    f"{PARTS_PACKAGE}.lexical",
                    MODULE_IMPORT_NAME,
                ),
            )
        )

    def test_lexical_implementation_modules_have_no_external_bypasses(self) -> None:
        self.assertEqual(_actual_lexical_boundary_bypasses(), frozenset())

    def test_expression_boundary_scanner_rejects_every_bypass_form(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        source = """
from .emitter import (
    _emit_expression as relative_parenthesized_alias,
)
from src.conversion.gml_transpiler_parts.expression_parser import (
    parse_gml_expression as absolute_parenthesized_alias,
)
from .enum_helpers import reject_enum_mutation_expression as relative_alias
from src.conversion.gml_transpiler_parts.function_helpers import *
from .utils import normalize_scope_context as utility_alias
from . import emitter as emitter_module
from src.conversion.gml_transpiler_parts import enum_helpers as enum_module
import src.conversion.gml_transpiler_parts.expression_parser as parser_module
from src.conversion.gml_transpiler import _parse_gml_expression as legacy_facade_bypass
from src.conversion.gml_transpiler import *
import src.conversion.gml_transpiler as facade_module
from src.conversion import gml_transpiler as package_facade

emitter_module.emit_gml_expression(relative_parenthesized_alias)
enum_module.reject_enum_mutation_expression(relative_alias, ())
parser_module.parse_gml_expression("value")
facade_module._ExpressionParser([])
package_facade._Binary(None, "+", None)
"""

        self.assertEqual(
            _expression_boundary_bypasses_from_source(source, consumer),
            frozenset(
                {
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.emitter",
                        "_emit_expression",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.expression_parser",
                        "parse_gml_expression",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.enum_helpers",
                        "reject_enum_mutation_expression",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.function_helpers",
                        "*",
                    ),
                    ImportEdge(
                        consumer,
                        EXPRESSION_UTILITY_MODULE,
                        "normalize_scope_context",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.emitter",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.enum_helpers",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.expression_parser",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "_parse_gml_expression",
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "_ExpressionParser",
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "_Binary",
                    ),
                    ImportEdge(
                        consumer,
                        FACADE_MODULE,
                        "*",
                    ),
                }
            ),
        )

        expression_service = f"{PARTS_PACKAGE}.expression_service"
        self.assertTrue(
            _expression_boundary_import_is_allowed(
                expression_service,
                ImportEdge(
                    expression_service,
                    f"{PARTS_PACKAGE}.emitter",
                    "emit_gml_expression",
                ),
            )
        )
        self.assertTrue(
            _expression_boundary_import_is_allowed(
                expression_service,
                ImportEdge(
                    expression_service,
                    EXPRESSION_UTILITY_MODULE,
                    "normalize_scope_context",
                ),
            )
        )
        self.assertFalse(
            _expression_boundary_import_is_allowed(
                expression_service,
                ImportEdge(
                    expression_service,
                    f"{PARTS_PACKAGE}.emitter",
                    "_emit_expression",
                ),
            )
        )
        self.assertFalse(
            _expression_boundary_import_is_allowed(
                f"{PARTS_PACKAGE}.statements",
                ImportEdge(
                    f"{PARTS_PACKAGE}.statements",
                    f"{PARTS_PACKAGE}.emitter",
                    "emit_gml_expression",
                ),
            )
        )
        for owner, name in EXPRESSION_DIRECT_IMPORTS_BY_CONSUMER[FACADE_MODULE]:
            with self.subTest(owner=owner, name=name):
                self.assertTrue(
                    _expression_boundary_import_is_allowed(
                        FACADE_MODULE,
                        ImportEdge(FACADE_MODULE, owner, name),
                    )
                )

    def test_expression_implementation_modules_have_no_external_bypasses(self) -> None:
        self.assertEqual(_actual_expression_boundary_bypasses(), frozenset())

    def test_statement_boundary_scanner_rejects_every_bypass_form(self) -> None:
        consumer = f"{PARTS_PACKAGE}.synthetic_consumer"
        source = """
from .statement_parser import (
    _StatementParser as relative_parenthesized_alias,
)
from src.conversion.gml_transpiler_parts.statements import (
    transpile_statement as absolute_parenthesized_alias,
)
from .static_declarations import *
from .utils import indent_lines as utility_alias
from .utils import brand_new_statement_helper
from . import statement_parser as parser_module
from . import statement_api as gateway_module
from src.conversion.gml_transpiler_parts import statements as statements_module
import src.conversion.gml_transpiler_parts.static_declarations as static_module
from . import utils as utility_module
import src.conversion.gml_transpiler_parts.utils as absolute_utility_module
"""

        self.assertEqual(
            _statement_boundary_bypasses_from_source(source, consumer),
            frozenset(
                {
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.statement_parser",
                        "_StatementParser",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.statements",
                        "transpile_statement",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.static_declarations",
                        "*",
                    ),
                    ImportEdge(
                        consumer,
                        STATEMENT_UTILITY_MODULE,
                        "indent_lines",
                    ),
                    ImportEdge(
                        consumer,
                        STATEMENT_UTILITY_MODULE,
                        "brand_new_statement_helper",
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.statement_parser",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.statements",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        f"{PARTS_PACKAGE}.static_declarations",
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        STATEMENT_UTILITY_MODULE,
                        MODULE_IMPORT_NAME,
                    ),
                    ImportEdge(
                        consumer,
                        STATEMENT_API_MODULE,
                        MODULE_IMPORT_NAME,
                    ),
                }
            ),
        )

        statement_api_consumer = STATEMENT_API_MODULE
        self.assertTrue(
            _statement_boundary_import_is_allowed(
                statement_api_consumer,
                ImportEdge(
                    statement_api_consumer,
                    f"{PARTS_PACKAGE}.statement_parser",
                    "parse_gml_statements",
                ),
            )
        )
        statement_parser_consumer = f"{PARTS_PACKAGE}.statement_parser"
        self.assertTrue(
            _statement_boundary_import_is_allowed(
                statement_parser_consumer,
                ImportEdge(
                    statement_parser_consumer,
                    STATEMENT_UTILITY_MODULE,
                    "indent_lines",
                ),
            )
        )
        self.assertFalse(
            _statement_boundary_import_is_allowed(
                statement_parser_consumer,
                ImportEdge(
                    statement_parser_consumer,
                    STATEMENT_UTILITY_MODULE,
                    "prefix_multiline",
                ),
            )
        )
        self.assertFalse(
            _statement_boundary_import_is_allowed(
                consumer,
                ImportEdge(
                    consumer,
                    f"{PARTS_PACKAGE}.statement_parser",
                    "parse_gml_statements",
                ),
            )
        )

    def test_statement_boundary_allowances_are_exact_and_have_no_bypasses(self) -> None:
        self.assertEqual(
            set(STATEMENT_DIRECT_IMPORTS_BY_CONSUMER),
            {
                f"{PARTS_PACKAGE}.api",
                STATEMENT_API_MODULE,
                f"{PARTS_PACKAGE}.statement_parser",
                f"{PARTS_PACKAGE}.statements",
                f"{PARTS_PACKAGE}.static_declarations",
                "tests.test_gml_statement_api",
                "tests.test_gml_transpiler_architecture",
            },
        )
        for consumer, expected_imports in STATEMENT_DIRECT_IMPORTS_BY_CONSUMER.items():
            with self.subTest(consumer=consumer):
                module_path = PROJECT_ROOT.joinpath(*consumer.split(".")).with_suffix(".py")
                actual = _statement_boundary_bypasses_from_source(
                    module_path.read_text(encoding="utf-8"),
                    consumer,
                )
                expected = frozenset(
                    ImportEdge(consumer, owner, name)
                    for owner, name in expected_imports
                )
                self.assertEqual(actual, expected)

        self.assertEqual(_actual_statement_boundary_bypasses(), frozenset())

    def test_statement_orchestration_uses_only_cycle_safe_phase_gateway(self) -> None:
        expected_gateway_imports = frozenset(
            {
                (STATEMENT_API_MODULE, "collect_static_declarations"),
                (STATEMENT_API_MODULE, "parse_gml_statements"),
                (STATEMENT_API_MODULE, "static_scope_id"),
                (STATEMENT_MODELS_MODULE, "GMLStatementRequest"),
            }
        )
        orchestration_modules = (
            f"{PARTS_PACKAGE}.api",
            f"{PARTS_PACKAGE}.expression_parser",
        )
        statement_surface_owners = STATEMENT_IMPLEMENTATION_MODULES | frozenset(
            {STATEMENT_API_MODULE, STATEMENT_MODELS_MODULE}
        )
        for consumer in orchestration_modules:
            with self.subTest(consumer=consumer):
                module_path = PROJECT_ROOT.joinpath(*consumer.split(".")).with_suffix(".py")
                actual = frozenset(
                    (edge.owner, edge.name)
                    for edge in _imports_from_path(module_path)
                    if edge.owner in statement_surface_owners
                )
                self.assertEqual(actual, expected_gateway_imports)

        expression_parser_path = PARTS_PATH / "expression_parser.py"
        expression_parser_tree = ast.parse(
            expression_parser_path.read_text(encoding="utf-8")
        )
        top_level_statement_imports = [
            node
            for node in expression_parser_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module == "statement_api"
        ]
        self.assertEqual(top_level_statement_imports, [])
        nested_statement_imports = [
            node
            for node in ast.walk(expression_parser_tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module == "statement_api"
        ]
        self.assertEqual(len(nested_statement_imports), 1)
        self.assertEqual(
            {imported.name for imported in nested_statement_imports[0].names},
            {
                "collect_static_declarations",
                "parse_gml_statements",
                "static_scope_id",
            },
        )
        self.assertEqual(
            tuple(statement_phase_api.__all__),
            (
                "collect_static_declarations",
                "parse_gml_statements",
                "static_scope_id",
            ),
        )

    def test_private_phase_and_production_import_inventory_is_exact(self) -> None:
        actual_internal = _actual_internal_private_imports()
        actual_production = _actual_production_imports()
        difference = _format_edge_difference(
            EXPECTED_ALL_IMPORTS,
            actual_internal | actual_production,
        )

        self.assertEqual(len(EXPECTED_INTERNAL_PRIVATE_IMPORTS), 31)
        self.assertEqual(
            len(
                {
                    (edge.consumer, edge.owner)
                    for edge in EXPECTED_INTERNAL_PRIVATE_IMPORTS
                }
            ),
            4,
        )
        self.assertEqual(len(EXPECTED_PRODUCTION_IMPORTS), 60)
        self.assertEqual(
            sum(edge.name.startswith("_") for edge in EXPECTED_PRODUCTION_IMPORTS),
            4,
        )
        self.assertEqual(
            actual_internal,
            EXPECTED_INTERNAL_PRIVATE_IMPORTS,
            difference,
        )
        self.assertEqual(
            actual_production,
            EXPECTED_PRODUCTION_IMPORTS,
            difference,
        )
        self.assertEqual(
            {
                edge
                for edge in actual_internal | actual_production
                if edge.owner == f"{PARTS_PACKAGE}.constants" and edge.name.startswith("_")
            },
            {
                ImportEdge(
                    FACADE_MODULE,
                    f"{PARTS_PACKAGE}.constants",
                    "_BUILTIN_VARIABLE_REGISTRY",
                )
            },
        )

    def test_private_model_aliases_are_facade_only(self) -> None:
        legacy_owner = f"{PARTS_PACKAGE}.model"
        explicit_model_owners = frozenset(
            {
                f"{PARTS_PACKAGE}.expression_models",
                f"{PARTS_PACKAGE}.result_models",
                f"{PARTS_PACKAGE}.shared_models",
                f"{PARTS_PACKAGE}.statement_models",
            }
        )
        production_edges = _actual_internal_private_imports() | _actual_production_imports()
        legacy_edges = {edge for edge in production_edges if edge.owner == legacy_owner}
        explicit_private_edges = {
            edge
            for edge in production_edges
            if edge.owner in explicit_model_owners and edge.name.startswith("_")
        }
        test_private_model_edges: set[ImportEdge] = set()
        for path in sorted((PROJECT_ROOT / "tests").rglob("*.py")):
            test_private_model_edges.update(
                edge
                for edge in _imports_from_path(path)
                if (
                    edge.name.startswith("_")
                    and not edge.name.startswith("__")
                    and edge.owner
                    in explicit_model_owners | frozenset({legacy_owner})
                )
            )

        self.assertTrue(legacy_edges)
        self.assertEqual({edge.consumer for edge in legacy_edges}, {FACADE_MODULE})
        self.assertEqual(explicit_private_edges, set())
        self.assertEqual(test_private_model_edges, set())

    def test_every_import_has_an_explicit_classification_and_migration_disposition(self) -> None:
        dispositions = {edge: _disposition_for(edge) for edge in EXPECTED_ALL_IMPORTS}

        self.assertEqual(set(dispositions), set(EXPECTED_ALL_IMPORTS))
        self.assertEqual(
            {
                disposition.removal_stage
                for edge, disposition in dispositions.items()
                if edge.name.startswith("_")
            },
            {817, 820},
        )
        self.assertEqual(
            {
                disposition.classification
                for disposition in dispositions.values()
            },
            set(BoundaryClassification),
        )
        for edge, disposition in dispositions.items():
            with self.subTest(edge=edge):
                if edge.name.startswith("_"):
                    self.assertIsNotNone(disposition.removal_stage)
                else:
                    self.assertIsNone(disposition.removal_stage)

    def test_supported_facade_exports_and_signatures_are_exact(self) -> None:
        actual_public_exports = tuple(name for name in gml_transpiler.__all__ if not name.startswith("_"))
        self.assertEqual(actual_public_exports, EXPECTED_PUBLIC_FACADE_EXPORTS)
        self.assertEqual(set(EXPECTED_PUBLIC_FACADE_SIGNATURES), set(EXPECTED_PUBLIC_FACADE_EXPORTS))

        for name, expected_signature in EXPECTED_PUBLIC_FACADE_SIGNATURES.items():
            with self.subTest(name=name):
                value = cast(object, getattr(gml_transpiler, name))
                if expected_signature is None:
                    self.assertFalse(callable(value))
                    continue
                self.assertTrue(callable(value))
                callable_value = cast(Callable[..., object], value)
                self.assertEqual(
                    str(inspect.signature(callable_value, eval_str=False)),
                    expected_signature,
                )

    def test_legacy_private_facade_exports_are_exact_and_cannot_grow(self) -> None:
        actual_private_exports = tuple(name for name in gml_transpiler.__all__ if name.startswith("_"))
        self.assertEqual(actual_private_exports, EXPECTED_LEGACY_PRIVATE_FACADE_EXPORTS)

    def test_transitional_private_usage_suppressions_are_exact(self) -> None:
        actual = _actual_private_usage_suppressions()
        self.assertEqual(len(EXPECTED_PRIVATE_USAGE_SUPPRESSIONS), 3)
        self.assertEqual(actual, EXPECTED_PRIVATE_USAGE_SUPPRESSIONS)


if __name__ == "__main__":
    unittest.main()
