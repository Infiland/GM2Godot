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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACADE_MODULE = "src.conversion.gml_transpiler"
PARTS_PACKAGE = "src.conversion.gml_transpiler_parts"
FACADE_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler.py"
PARTS_PATH = PROJECT_ROOT / "src" / "conversion" / "gml_transpiler_parts"
MODULE_IMPORT_NAME = "<module>"


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
src.conversion.gml_transpiler|src.conversion.gml_transpiler_parts.tokens|_expression_tokens,_tokenize
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.constants|_LEGACY_GLOBAL_BUILTINS
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.function_helpers|_emit_static_initialization_lines
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.model|_ScopeContext
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.statement_parser|_StatementParser
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.static_declarations|_collect_static_declarations,_static_scope_id
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.tokens|_tokenize
src.conversion.gml_transpiler_parts.api|src.conversion.gml_transpiler_parts.utils|_prefix_multiline
src.conversion.gml_transpiler_parts.constants|src.conversion.gml_transpiler_parts.model|_AssignmentOperator,_BuiltinVariableMetadata,_Token
src.conversion.gml_transpiler_parts.emitter|src.conversion.gml_transpiler_parts.constants|_ARITHMETIC_RUNTIME_FUNCTIONS,_BINARY_PRECEDENCE,_BITWISE_RUNTIME_FUNCTIONS,_BOOLEAN_RESULT_BINARY_OPERATORS,_BOOLEAN_RESULT_FUNCTIONS,_BUILTIN_ARRAY_VARIABLES,_BUILTIN_GLOBAL_VARIABLES,_BUILTIN_INSTANCE_VARIABLES,_COMPARISON_RUNTIME_FUNCTIONS,_DIRECT_MEMBER_TARGETS,_GML_BUILTIN_CONSTANT_IDENTIFIERS,_GML_LITERAL_IDENTIFIERS,_INSTANCE_NAME_REPLACEMENTS,_NAME_REPLACEMENTS,_OPERATOR_REPLACEMENTS,_POSTFIX_PRECEDENCE,_PRIMARY_PRECEDENCE,_RIGHT_ASSOCIATIVE,_TERNARY_PRECEDENCE,_UNARY_PRECEDENCE,_VIRTUAL_KEY_ACTIONS,_VIRTUAL_KEY_CONSTANTS
src.conversion.gml_transpiler_parts.emitter|src.conversion.gml_transpiler_parts.identifiers|_is_plain_identifier,_sanitize_gdscript_identifier
src.conversion.gml_transpiler_parts.emitter|src.conversion.gml_transpiler_parts.model|_ArrayLiteral,_ArrayRefAccess,_Binary,_Call,_DSGridAccess,_DSListAccess,_DSMapAccess,_EnumMember,_Expression,_FunctionLiteral,_FunctionParameter,_Grouped,_Index,_Literal,_Member,_Name,_NameOf,_NewCall,_NumberLiteral,_ScopeContext,_StringLiteral,_StructAccess,_StructLiteral,_TemplateStringLiteral,_Ternary,_Unary
src.conversion.gml_transpiler_parts.emitter|src.conversion.gml_transpiler_parts.utils|_normalize_local_names,_normalize_scope_context,_prefix_multiline,_unwrap_grouped_expression
src.conversion.gml_transpiler_parts.enum_helpers|src.conversion.gml_transpiler_parts.constants|_GML_BUILTIN_CONSTANT_IDENTIFIERS,_READ_ONLY_BUILTIN_VARIABLES
src.conversion.gml_transpiler_parts.enum_helpers|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.gml_transpiler_parts.enum_helpers|src.conversion.gml_transpiler_parts.model|_ArrayLiteral,_Binary,_Call,_DSListAccess,_DSMapAccess,_EnumMember,_Expression,_Grouped,_Index,_Member,_Name,_NumberLiteral,_StructAccess,_StructLiteral,_TemplateStringLiteral,_Ternary,_Token,_Unary
src.conversion.gml_transpiler_parts.enum_helpers|src.conversion.gml_transpiler_parts.tokens|_expression_tokens
src.conversion.gml_transpiler_parts.enum_helpers|src.conversion.gml_transpiler_parts.utils|_normalize_local_names,_tokens_to_source,_unwrap_grouped_expression
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.constants|_BINARY_PRECEDENCE,_EOF,_NAME_REPLACEMENTS,_RIGHT_ASSOCIATIVE,_TERNARY_PRECEDENCE
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.function_helpers|_emit_constructor_inheritance_line,_emit_static_initialization_lines
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.identifiers|_reject_asset_identifier_name,_validate_gml_identifier
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.lexical|_decode_gml_verbatim_string_literal
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.model|_ArrayLiteral,_ArrayRefAccess,_Binary,_Call,_DSGridAccess,_DSListAccess,_DSMapAccess,_EnumMember,_Expression,_FunctionLiteral,_FunctionParameter,_Grouped,_Index,_Member,_Name,_NameOf,_NewCall,_NumberLiteral,_ScopeContext,_StringLiteral,_StructAccess,_StructLiteral,_TemplateStringLiteral,_Ternary,_Token,_Unary
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.statement_parser|_StatementParser
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.static_declarations|_collect_static_declarations,_static_scope_id
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.tokens|_decode_gml_string_literal,_expression_tokens,_is_float_like_number,_split_template_string
src.conversion.gml_transpiler_parts.expression_parser|src.conversion.gml_transpiler_parts.utils|_normalize_scope_context,_strip_comments
src.conversion.gml_transpiler_parts.expression_service|src.conversion.gml_transpiler_parts.emitter|_emit_expression,_emit_truthy_expression
src.conversion.gml_transpiler_parts.expression_service|src.conversion.gml_transpiler_parts.enum_helpers|_reject_enum_mutation_expression
src.conversion.gml_transpiler_parts.expression_service|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.gml_transpiler_parts.expression_service|src.conversion.gml_transpiler_parts.model|_ScopeContext
src.conversion.gml_transpiler_parts.expression_service|src.conversion.gml_transpiler_parts.utils|_normalize_local_names,_normalize_scope_context,_scope_context_with_global_names
src.conversion.gml_transpiler_parts.function_helpers|src.conversion.gml_transpiler_parts.emitter|_emit_expression
src.conversion.gml_transpiler_parts.function_helpers|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.gml_transpiler_parts.function_helpers|src.conversion.gml_transpiler_parts.model|_Call,_Expression,_ScopeContext,_StaticDeclaration
src.conversion.gml_transpiler_parts.gml_function_dispatch|src.conversion.gml_transpiler_parts.constants|_ARRAY_RUNTIME_FUNCTIONS,_ASSET_RUNTIME_FUNCTIONS,_ASYNC_RUNTIME_FUNCTIONS,_AUDIO_RUNTIME_FUNCTIONS,_BUFFER_RUNTIME_FUNCTIONS,_COLLISION_RUNTIME_FUNCTIONS,_DRAW_RUNTIME_FUNCTIONS,_DS_COLLECTIONS_FUNCTIONS,_DS_GRID_FUNCTIONS,_DS_MAP_RUNTIME_FUNCTIONS,_FILE_RUNTIME_FUNCTIONS,_FLEXPANEL_RUNTIME_FUNCTIONS,_INPUT_RUNTIME_FUNCTIONS,_INSTANCE_RUNTIME_FUNCTIONS,_LAYER_RUNTIME_FUNCTIONS,_MATH_RUNTIME_FUNCTIONS,_MOTION_RUNTIME_FUNCTIONS,_MP_GRID_RUNTIME_FUNCTIONS,_NETWORK_RUNTIME_FUNCTIONS,_OS_DEBUG_GC_RUNTIME_FUNCTIONS,_PATH_RUNTIME_FUNCTIONS,_PHYSICS_RUNTIME_FUNCTIONS,_PLATFORM_SERVICE_RUNTIME_FUNCTIONS,_ROOM_RUNTIME_FUNCTIONS,_RUNTIME_FUNCTIONS,_SEQUENCE_TIMELINE_RUNTIME_FUNCTIONS,_STRING_RUNTIME_FUNCTIONS,_STRUCT_RUNTIME_FUNCTIONS,_TIME_RUNTIME_FUNCTIONS,_VARIABLE_RUNTIME_FUNCTIONS
src.conversion.gml_transpiler_parts.identifiers|src.conversion.gml_transpiler_parts.constants|_GDSCRIPT_RESERVED_IDENTIFIERS,_GENERATED_IDENTIFIER_PREFIX,_GML_IDENTIFIER_MAX_LENGTH
src.conversion.gml_transpiler_parts.identifiers|src.conversion.gml_transpiler_parts.model|_ScopeContext
src.conversion.gml_transpiler_parts.preprocessor|src.conversion.gml_transpiler_parts.identifiers|_validate_gml_identifier
src.conversion.gml_transpiler_parts.preprocessor|src.conversion.gml_transpiler_parts.lexical|_is_verbatim_string_start,_read_verbatim_string
src.conversion.gml_transpiler_parts.preprocessor|src.conversion.gml_transpiler_parts.tokens|_read_template_string
src.conversion.gml_transpiler_parts.preprocessor|src.conversion.gml_transpiler_parts.utils|_join_macro_continuation_lines,_macro_configuration_matches,_strip_comments
src.conversion.gml_transpiler_parts.source_map|src.conversion.gml_transpiler_parts.constants|_GDSCRIPT_RESERVED_IDENTIFIERS
src.conversion.gml_transpiler_parts.source_map|src.conversion.gml_transpiler_parts.identifiers|_sanitize_gdscript_identifier
src.conversion.gml_transpiler_parts.source_map|src.conversion.gml_transpiler_parts.lexical|_is_verbatim_string_start,_read_ordinary_string,_read_verbatim_string
src.conversion.gml_transpiler_parts.source_map|src.conversion.gml_transpiler_parts.tokens|_read_template_string
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.constants|_BINARY_PRECEDENCE,_EOF
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.emitter|_emit_instance_keyword_argument
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.enum_helpers|_evaluate_enum_value_tokens
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.identifiers|_reject_asset_identifier_name,_sanitize_gdscript_identifier,_validate_gml_identifier
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.model|_ScopeContext,_Token
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.statements|_ControlFlowCapture,_control_flow_dispatch_lines,_transpile_statement
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.static_declarations|_read_static_declaration_tokens
src.conversion.gml_transpiler_parts.statement_parser|src.conversion.gml_transpiler_parts.utils|_indent_lines,_insert_lines_before_continue,_insert_until_check_before_continue,_macro_configuration_matches,_normalize_scope_context,_scope_context_with_global_names,_split_top_level_tokens,_tokens_to_source
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.constants|_BUILTIN_ARRAY_VARIABLES,_BUILTIN_GLOBAL_VARIABLES,_BUILTIN_INSTANCE_VARIABLES,_COMPOUND_RUNTIME_FUNCTIONS,_GML_LITERAL_IDENTIFIERS
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.emitter|_emit_expression,_emit_instance_keyword_argument,_is_alarm_array_access,_name_resolves_to_global,_uses_direct_builtin_instance_members,_uses_direct_member_access
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.enum_helpers|_reject_constant_assignment_target_name,_reject_constant_declaration_name,_reject_enum_assignment_target,_reject_readonly_builtin_assignment_target
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.identifiers|_is_plain_identifier,_reject_asset_identifier_name,_sanitize_gdscript_identifier,_validate_gml_identifier
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.model|_ArrayRefAccess,_Call,_DSGridAccess,_DSListAccess,_DSMapAccess,_Expression,_IncrementDelta,_IncrementMode,_Index,_Member,_Name,_ScopeContext,_StructAccess,_Token
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.tokens|_expression_tokens
src.conversion.gml_transpiler_parts.statements|src.conversion.gml_transpiler_parts.utils|_cache_assignment_part,_indent_lines,_next_generated_name_from_counter,_normalize_scope_context,_split_assignment,_split_top_level,_unwrap_grouped_expression
src.conversion.gml_transpiler_parts.static_declarations|src.conversion.gml_transpiler_parts.identifiers|_validate_gml_identifier
src.conversion.gml_transpiler_parts.static_declarations|src.conversion.gml_transpiler_parts.model|_StaticDeclaration,_Token
src.conversion.gml_transpiler_parts.static_declarations|src.conversion.gml_transpiler_parts.utils|_split_assignment,_split_top_level,_tokens_to_source
src.conversion.gml_transpiler_parts.tokens|src.conversion.gml_transpiler_parts.constants|_BLOCK_DELIMITER_REPLACEMENTS,_MULTI_CHAR_OPERATORS
src.conversion.gml_transpiler_parts.tokens|src.conversion.gml_transpiler_parts.identifiers|_validate_gml_identifier
src.conversion.gml_transpiler_parts.tokens|src.conversion.gml_transpiler_parts.lexical|_is_verbatim_string_start,_read_ordinary_string,_read_verbatim_string
src.conversion.gml_transpiler_parts.tokens|src.conversion.gml_transpiler_parts.model|_Token
src.conversion.gml_transpiler_parts.utils|src.conversion.gml_transpiler_parts.constants|_ASSIGNMENT_OPERATORS
src.conversion.gml_transpiler_parts.utils|src.conversion.gml_transpiler_parts.lexical|_is_verbatim_string_start,_read_verbatim_string
src.conversion.gml_transpiler_parts.utils|src.conversion.gml_transpiler_parts.model|_ArrayLiteral,_AssignmentOperator,_Binary,_Call,_DEFAULT_SCOPE_CONTEXT,_DSGridAccess,_DSListAccess,_DSMapAccess,_Expression,_FunctionLiteral,_Grouped,_Index,_Member,_NewCall,_ScopeContext,_StructAccess,_StructLiteral,_TemplateStringLiteral,_Ternary,_Token,_Unary
src.conversion.gml_transpiler_parts.utils|src.conversion.gml_transpiler_parts.tokens|_line_column,_read_template_string
"""

EXPECTED_PRODUCTION_IMPORT_GROUPS = """
src.cli|src.conversion.gml_transpiler|generate_gml_api_compatibility_report,render_gml_manual_scope_markdown
src.conversion.asset_registry|src.conversion.gml_transpiler|GMLTranspileError,transpile_gml_code
src.conversion.extension_registry|src.conversion.gml_transpiler_parts.extension_functions|EXTENSION_FUNCTION_MAPPING_FILENAME,load_gml_extension_function_mappings
src.conversion.gml_runtime_parts.manifest|src.conversion.gml_transpiler_parts.gml_api_manifest|iter_gml_api_entries
src.conversion.objects|src.conversion.gml_transpiler|GMLSourceMap,GMLTranspileError,analyze_gml_source_identifiers,merge_gml_source_maps,transpile_gml_code_with_source_map,write_gml_source_map
src.conversion.objects|src.conversion.gml_transpiler_parts.constants|_ASSIGNMENT_OPERATORS,_BUILTIN_GLOBAL_VARIABLES,_BUILTIN_INSTANCE_VARIABLES,_GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS,_GML_LITERAL_IDENTIFIERS
src.conversion.objects|src.conversion.gml_transpiler_parts.model|_Token
src.conversion.objects|src.conversion.gml_transpiler_parts.preprocessor|preprocess_gml_source
src.conversion.objects|src.conversion.gml_transpiler_parts.tokens|_tokenize
src.conversion.project_enums|src.conversion.gml_transpiler_parts.enum_helpers|_evaluate_enum_value_tokens
src.conversion.project_enums|src.conversion.gml_transpiler_parts.model|GMLTranspileError,_Token
src.conversion.project_enums|src.conversion.gml_transpiler_parts.preprocessor|preprocess_gml_source
src.conversion.project_enums|src.conversion.gml_transpiler_parts.tokens|_tokenize
src.conversion.project_macros|src.conversion.gml_transpiler_parts.model|GMLTranspileError,_Token
src.conversion.project_macros|src.conversion.gml_transpiler_parts.preprocessor|preprocess_gml_source
src.conversion.project_macros|src.conversion.gml_transpiler_parts.tokens|_tokenize
src.conversion.project_macros|src.conversion.gml_transpiler_parts.utils|_macro_configuration_matches,_tokens_to_source
src.conversion.rooms|src.conversion.gml_transpiler|GMLTranspileError,transpile_gml_code
src.conversion.script_functions|src.conversion.gml_transpiler|GMLTranspileError
src.conversion.script_functions|src.conversion.gml_transpiler_parts.identifiers|_validate_gml_identifier
src.conversion.script_functions|src.conversion.gml_transpiler_parts.lexical|_is_verbatim_string_start,_read_verbatim_string
src.conversion.script_functions|src.conversion.gml_transpiler_parts.preprocessor|preprocess_gml_source_preserving_layout
src.conversion.script_functions|src.conversion.gml_transpiler_parts.tokens|_read_template_string
src.conversion.script_functions|src.conversion.gml_transpiler_parts.utils|_split_assignment,_split_top_level
src.conversion.script_generator|src.conversion.gml_transpiler_parts.constants|_GDSCRIPT_NATIVE_INSTANCE_MEMBER_IDENTIFIERS
src.conversion.script_generator|src.conversion.gml_transpiler_parts.identifiers|_sanitize_gdscript_identifier
src.conversion.scripts|src.conversion.gml_transpiler|EXTENSION_FUNCTION_MAPPING_FILENAME,GMLExtensionFunction,GMLExtensionFunctionMapping,GMLSourceMap,GMLTranspileError,analyze_gml_source_identifiers,load_gml_extension_function_mappings,merge_gml_source_maps,render_gml_source_header,transpile_gml_code_with_source_map,transpile_gml_expression,write_gml_source_map
src.conversion.scripts|src.conversion.gml_transpiler_parts.expression_parser|_parse_gml_expression
src.conversion.scripts|src.conversion.gml_transpiler_parts.function_helpers|_emit_constructor_inheritance_line
src.conversion.scripts|src.conversion.gml_transpiler_parts.identifiers|_sanitize_gdscript_identifier
src.conversion.scripts|src.conversion.gml_transpiler_parts.model|_ScopeContext
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


# The six owner modules below contain shared data, language metadata, lexical
# operations, or semantic operations that the named child issue makes explicit.
ALL_PRIVATE_NAMES_ARE_INTENDED_INTERNAL = frozenset(
    {
        f"{PARTS_PACKAGE}.constants",
        f"{PARTS_PACKAGE}.enum_helpers",
        f"{PARTS_PACKAGE}.function_helpers",
        f"{PARTS_PACKAGE}.identifiers",
        f"{PARTS_PACKAGE}.lexical",
        f"{PARTS_PACKAGE}.model",
    }
)

INTENDED_INTERNAL_NAMES_BY_MIXED_OWNER: dict[str, frozenset[str]] = {
    f"{PARTS_PACKAGE}.emitter": frozenset(
        {
            "_emit_expression",
            "_emit_instance_keyword_argument",
            "_emit_truthy_expression",
            "_name_resolves_to_global",
            "_uses_direct_builtin_instance_members",
            "_uses_direct_member_access",
        }
    ),
    f"{PARTS_PACKAGE}.expression_parser": frozenset({"_parse_gml_expression"}),
    f"{PARTS_PACKAGE}.statements": frozenset({"_ControlFlowCapture"}),
    f"{PARTS_PACKAGE}.tokens": frozenset(
        {
            "_expression_tokens",
            "_read_template_string",
            "_tokenize",
        }
    ),
    f"{PARTS_PACKAGE}.utils": frozenset(
        {
            "_macro_configuration_matches",
            "_normalize_local_names",
            "_normalize_scope_context",
            "_scope_context_with_global_names",
            "_split_assignment",
            "_split_top_level",
            "_strip_comments",
            "_tokens_to_source",
            "_unwrap_grouped_expression",
        }
    ),
}

MODULE_PRIVATE_NAMES_BY_MIXED_OWNER: dict[str, frozenset[str]] = {
    f"{PARTS_PACKAGE}.emitter": frozenset({"_is_alarm_array_access"}),
    f"{PARTS_PACKAGE}.expression_parser": frozenset({"_ExpressionParser"}),
    f"{PARTS_PACKAGE}.statement_parser": frozenset({"_StatementParser"}),
    f"{PARTS_PACKAGE}.statements": frozenset(
        {
            "_control_flow_dispatch_lines",
            "_transpile_statement",
        }
    ),
    f"{PARTS_PACKAGE}.static_declarations": frozenset(
        {
            "_collect_static_declarations",
            "_read_static_declaration_tokens",
            "_static_scope_id",
        }
    ),
    f"{PARTS_PACKAGE}.tokens": frozenset(
        {
            "_decode_gml_string_literal",
            "_is_float_like_number",
            "_line_column",
            "_split_template_string",
        }
    ),
    f"{PARTS_PACKAGE}.utils": frozenset(
        {
            "_cache_assignment_part",
            "_indent_lines",
            "_insert_lines_before_continue",
            "_insert_until_check_before_continue",
            "_join_macro_continuation_lines",
            "_next_generated_name_from_counter",
            "_prefix_multiline",
            "_split_top_level_tokens",
        }
    ),
}

RETAINED_PACKAGE_INTERNAL_EXPORTS = frozenset(
    {
        (f"{PARTS_PACKAGE}.preprocessor", "preprocess_gml_source_preserving_layout"),
    }
)

MIGRATION_STAGE_BY_OWNER: dict[str, int] = {
    f"{PARTS_PACKAGE}.model": 816,
    f"{PARTS_PACKAGE}.constants": 817,
    f"{PARTS_PACKAGE}.identifiers": 817,
    f"{PARTS_PACKAGE}.lexical": 817,
    f"{PARTS_PACKAGE}.tokens": 817,
    f"{PARTS_PACKAGE}.emitter": 818,
    f"{PARTS_PACKAGE}.enum_helpers": 818,
    f"{PARTS_PACKAGE}.expression_parser": 818,
    f"{PARTS_PACKAGE}.function_helpers": 818,
    f"{PARTS_PACKAGE}.statement_parser": 819,
    f"{PARTS_PACKAGE}.statements": 819,
    f"{PARTS_PACKAGE}.static_declarations": 819,
}

UTILS_STAGE_BY_CONSUMER: dict[str, int] = {
    f"{PARTS_PACKAGE}.preprocessor": 817,
    "src.conversion.project_macros": 817,
    "src.conversion.script_functions": 817,
    f"{PARTS_PACKAGE}.emitter": 818,
    f"{PARTS_PACKAGE}.enum_helpers": 818,
    f"{PARTS_PACKAGE}.expression_parser": 818,
    f"{PARTS_PACKAGE}.expression_service": 818,
    f"{PARTS_PACKAGE}.api": 819,
    f"{PARTS_PACKAGE}.statement_parser": 819,
    f"{PARTS_PACKAGE}.statements": 819,
    f"{PARTS_PACKAGE}.static_declarations": 819,
}


def _disposition_for(edge: ImportEdge) -> BoundaryDisposition:
    if edge.name in EXPECTED_PUBLIC_FACADE_EXPORTS:
        return BoundaryDisposition(BoundaryClassification.SUPPORTED_PUBLIC_FACADE, None)
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
            "src/conversion/gml_transpiler_parts/api.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/constants.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/emitter.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/enum_helpers.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/expression_parser.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/expression_service.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/extension_functions.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/function_helpers.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/gml_api_manifest.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/gml_function_dispatch.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/identifiers.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/lexical.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/model.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/preprocessor.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/source_map.py",
            1,
            "# pyright: reportPrivateUsage=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/statement_parser.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/statements.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/static_declarations.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/tokens.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
        ),
        (
            "src/conversion/gml_transpiler_parts/utils.py",
            1,
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false",
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
from .model import (
    _ScopeContext as ScopeContext,
    _Token,
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
                        "src.conversion.gml_transpiler_parts.model",
                        "_ScopeContext",
                    ),
                    ImportEdge(
                        "src.conversion.gml_transpiler_parts.synthetic_consumer",
                        "src.conversion.gml_transpiler_parts.model",
                        "_Token",
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

    def test_private_phase_and_production_import_inventory_is_exact(self) -> None:
        actual_internal = _actual_internal_private_imports()
        actual_production = _actual_production_imports()
        difference = _format_edge_difference(
            EXPECTED_ALL_IMPORTS,
            actual_internal | actual_production,
        )

        self.assertEqual(len(EXPECTED_INTERNAL_PRIVATE_IMPORTS), 329)
        self.assertEqual(len(EXPECTED_PRODUCTION_IMPORTS), 60)
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

    def test_every_import_has_an_explicit_classification_and_migration_disposition(self) -> None:
        dispositions = {edge: _disposition_for(edge) for edge in EXPECTED_ALL_IMPORTS}

        self.assertEqual(set(dispositions), set(EXPECTED_ALL_IMPORTS))
        self.assertEqual(
            {
                disposition.removal_stage
                for edge, disposition in dispositions.items()
                if edge.name.startswith("_")
            },
            {816, 817, 818, 819, 820},
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
        self.assertEqual(len(EXPECTED_PRIVATE_USAGE_SUPPRESSIONS), 21)
        self.assertEqual(actual, EXPECTED_PRIVATE_USAGE_SUPPRESSIONS)


if __name__ == "__main__":
    unittest.main()
