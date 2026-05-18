# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from typing import Iterable, MutableSet

from .constants import _LEGACY_GLOBAL_BUILTINS
from .extension_functions import (
    normalize_extension_function_mappings,
    normalize_extension_functions,
)
from .preprocessor import preprocess_gml_source
from .statement_parser import _StatementParser
from .tokens import _tokenize


def transpile_gml_code(
    source: str,
    indent: str = "	",
    local_names: Iterable[str] | None = None,
    instance_variables: MutableSet[str] | None = None,
    inherited_event_call: str | None = None,
    macro_configuration: str | None = None,
    top_level_global_scope: bool = False,
    legacy_global_builtins: bool = False,
    asset_names: Iterable[str] | None = None,
    static_scope_prefix: str | None = None,
    return_depth: int = 0,
    extension_functions: object = None,
    extension_function_mappings: object = None,
) -> str:
    """Transpile supported GML statements to GDScript."""
    preprocessed = preprocess_gml_source(source, macro_configuration=macro_configuration)
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
        extension_functions=normalize_extension_functions(extension_functions),
        extension_function_mappings=normalize_extension_function_mappings(extension_function_mappings),
    )
    lines = parser.parse()

    if not lines:
        return f"{indent}pass"

    return "\n".join(f"{indent}{line}" if line else "" for line in lines)
