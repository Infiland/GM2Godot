from __future__ import annotations

from typing import Final

from .identifiers import (
    is_plain_identifier,
    reject_asset_identifier_name,
    sanitize_gdscript_identifier,
    validate_gml_identifier,
)
from .lexical import (
    decode_gml_verbatim_string_literal,
    is_verbatim_string_start,
    read_ordinary_string,
    read_verbatim_string,
)
from .preprocessor import preprocess_gml_source, preprocess_gml_source_preserving_layout
from .tokens import (
    decode_gml_string_literal,
    read_template_string,
    split_template_string,
    tokenize_gml_expression,
    tokenize_gml_source,
)

__all__: Final[tuple[str, ...]] = (
    "decode_gml_string_literal",
    "decode_gml_verbatim_string_literal",
    "is_plain_identifier",
    "is_verbatim_string_start",
    "preprocess_gml_source",
    "preprocess_gml_source_preserving_layout",
    "read_ordinary_string",
    "read_template_string",
    "read_verbatim_string",
    "reject_asset_identifier_name",
    "sanitize_gdscript_identifier",
    "split_template_string",
    "tokenize_gml_expression",
    "tokenize_gml_source",
    "validate_gml_identifier",
)
