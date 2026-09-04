from __future__ import annotations

from typing import Final

from .statement_parser import parse_gml_statements
from .static_declarations import collect_static_declarations, static_scope_id


__all__: Final[tuple[str, ...]] = (
    "collect_static_declarations",
    "parse_gml_statements",
    "static_scope_id",
)
