# pyright: reportPrivateUsage=false
from __future__ import annotations

from .model import GMLTranspileError


def _is_verbatim_string_start(source: str, index: int) -> bool:
    return (
        0 <= index < len(source)
        and source[index] == "@"
        and index + 1 < len(source)
        and source[index + 1] in "\"'"
    )


def _read_verbatim_string(source: str, start: int) -> str:
    """Read one documented GML @-prefixed string literal.

    Verbatim strings require a contiguous ``@`` and quote, can span lines, and
    give backslashes no special meaning. The first matching quote therefore
    always terminates the literal.
    """

    if not _is_verbatim_string_start(source, start):
        raise GMLTranspileError(
            "Verbatim string literal must start with @ followed by a quote"
        )

    delimiter = source[start + 1]
    end = source.find(delimiter, start + 2)
    if end == -1:
        raise GMLTranspileError("Unterminated verbatim string literal")
    return source[start : end + 1]


def _decode_gml_verbatim_string_literal(source: str) -> str:
    literal = _read_verbatim_string(source, 0)
    if len(literal) != len(source):
        raise GMLTranspileError("Unexpected text after verbatim string literal")
    return source[2:-1]


def _read_ordinary_string(source: str, start: int) -> str:
    if start < 0 or start >= len(source) or source[start] not in "\"'":
        raise GMLTranspileError("String literal must start with a quote")

    quote = source[start]
    index = start + 1
    escaped = False
    while index < len(source):
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return source[start : index + 1]
        index += 1
    raise GMLTranspileError("Unterminated string literal")


__all__ = [
    "_decode_gml_verbatim_string_literal",
    "_is_verbatim_string_start",
    "_read_ordinary_string",
    "_read_verbatim_string",
]
