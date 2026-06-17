# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from typing import Iterable, MutableSet

from .constants import _LEGACY_GLOBAL_BUILTINS
from .extension_functions import (
    normalize_extension_function_mappings,
    normalize_extension_functions,
)
from .model import _ScopeContext
from .preprocessor import preprocess_gml_source
from .source_map import (
    GMLTranspileResult,
    build_gml_source_map,
    render_gml_source_header,
)
from .statement_parser import _StatementParser
from .tokens import _tokenize
from .utils import _prefix_multiline


def transpile_gml_code(
    source: str,
    indent: str = "	",
    local_names: Iterable[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    inherited_event_call: str | None = None,
    macro_configuration: str | None = None,
    active_preprocessor_symbols: Iterable[str] | None = None,
    top_level_global_scope: bool = False,
    legacy_global_builtins: bool = False,
    asset_names: Iterable[str] | None = None,
    static_scope_prefix: str | None = None,
    return_depth: int = 0,
    extension_functions: object = None,
    extension_function_mappings: object = None,
    source_path: str | None = None,
    event: str | None = None,
    preserve_source_comments: bool = False,
    generated_line_offset: int = 0,
    self_expression: str = "self",
    other_expression: str = "other",
    instance_target: str | None = None,
    direct_instance_names: Iterable[str] | None = None,
    dynamic_instance_names: Iterable[str] | None = None,
) -> str:
    """Transpile supported GML statements to GDScript."""
    return transpile_gml_code_with_source_map(
        source,
        indent=indent,
        local_names=local_names,
        instance_variables=instance_variables,
        inherited_event_call=inherited_event_call,
        macro_configuration=macro_configuration,
        active_preprocessor_symbols=active_preprocessor_symbols,
        top_level_global_scope=top_level_global_scope,
        legacy_global_builtins=legacy_global_builtins,
        asset_names=asset_names,
        static_scope_prefix=static_scope_prefix,
        return_depth=return_depth,
        extension_functions=extension_functions,
        extension_function_mappings=extension_function_mappings,
        source_path=source_path,
        event=event,
        preserve_source_comments=preserve_source_comments,
        generated_line_offset=generated_line_offset,
        self_expression=self_expression,
        other_expression=other_expression,
        instance_target=instance_target,
        direct_instance_names=direct_instance_names,
        dynamic_instance_names=dynamic_instance_names,
    ).code


def transpile_gml_code_with_source_map(
    source: str,
    indent: str = "	",
    local_names: Iterable[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    inherited_event_call: str | None = None,
    macro_configuration: str | None = None,
    active_preprocessor_symbols: Iterable[str] | None = None,
    top_level_global_scope: bool = False,
    legacy_global_builtins: bool = False,
    asset_names: Iterable[str] | None = None,
    static_scope_prefix: str | None = None,
    return_depth: int = 0,
    extension_functions: object = None,
    extension_function_mappings: object = None,
    source_path: str | None = None,
    event: str | None = None,
    preserve_source_comments: bool = False,
    generated_line_offset: int = 0,
    self_expression: str = "self",
    other_expression: str = "other",
    instance_target: str | None = None,
    direct_instance_names: Iterable[str] | None = None,
    dynamic_instance_names: Iterable[str] | None = None,
) -> GMLTranspileResult:
    """Transpile supported GML statements and return trace metadata."""
    preprocessed = preprocess_gml_source(
        source,
        macro_configuration=macro_configuration,
        active_symbols=active_preprocessor_symbols,
    )
    parser = _StatementParser(
        _tokenize(preprocessed.source),
        local_names=local_names,
        instance_variables=instance_variables,
        inherited_event_call=inherited_event_call,
        return_depth=return_depth,
        macro_configuration=macro_configuration,
        top_level_global_scope=top_level_global_scope,
        global_names=_LEGACY_GLOBAL_BUILTINS if legacy_global_builtins else None,
        asset_names=asset_names,
        static_scope_prefix=static_scope_prefix,
        scope_context=_ScopeContext(
            self_expression=self_expression,
            other_expression=other_expression,
            instance_target=instance_target,
            direct_instance_names=frozenset(direct_instance_names or ()),
            dynamic_instance_names=frozenset(dynamic_instance_names or ()),
        ),
        extension_functions=normalize_extension_functions(extension_functions),
        extension_function_mappings=normalize_extension_function_mappings(extension_function_mappings),
    )
    lines = parser.parse()

    if not lines:
        code = f"{indent}pass"
    else:
        code = "\n".join(_prefix_multiline(line, indent) if line else "" for line in lines)

    if preserve_source_comments:
        header = render_gml_source_header(source_path=None, event=None, source=source)
        if header:
            comment_block = "".join(f"{indent}{line}\n" for line in header.rstrip().splitlines())
            code = f"{comment_block}{code}"

    source_map = build_gml_source_map(
        source,
        code,
        source_path=source_path,
        event=event,
        generated_line_offset=generated_line_offset,
    )
    return GMLTranspileResult(code=code, source_map=source_map)
