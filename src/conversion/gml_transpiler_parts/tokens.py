# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from .constants import _BLOCK_DELIMITER_REPLACEMENTS, _EOF, _MULTI_CHAR_OPERATORS
from .identifiers import _validate_gml_identifier
from .model import GMLTranspileError, _Token

def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        char = source[index]

        if char in "\r\n":
            if char == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
                index += 1
            tokens.append(_Token("NEWLINE", "\n"))
            index += 1
            continue

        if char.isspace():
            index += 1
            continue

        if char.isdigit() or (char == "." and index + 1 < len(source) and source[index + 1].isdigit()):
            number_end = _read_number(source, index)
            tokens.append(_Token("NUMBER", source[index:number_end].replace("_", "")))
            index = number_end
            continue

        if char == '"' or char == "'":
            tokens.append(_Token("STRING", _read_string(source, index)))
            index += len(tokens[-1].value)
            continue

        if char == "$":
            next_char = source[index + 1] if index + 1 < len(source) else ""
            if next_char.lower() in "0123456789abcdef" or next_char == "_":
                hex_end = _read_hex_number(source, index + 1)
                tokens.append(_Token("NUMBER", f"0x{source[index + 1:hex_end].replace('_', '')}"))
                index = hex_end
            else:
                tokens.append(_Token("OP", char))
                index += 1
            continue

        if char == "#":
            if _source_startswith_directive(source, index, "#macro"):
                tokens.append(_Token("DIRECTIVE", "#macro"))
                index += len("#macro")
                continue
            color_literal, color_end = _read_hash_color_literal(source, index)
            tokens.append(_Token("NUMBER", color_literal))
            index = color_end
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                index += 1
            identifier = source[start:index]
            _validate_gml_identifier(identifier)
            block_delimiter = _BLOCK_DELIMITER_REPLACEMENTS.get(identifier)
            if block_delimiter is not None:
                tokens.append(_Token("OP", block_delimiter))
            else:
                tokens.append(_Token("IDENT", identifier))
            continue

        matched_operator = None
        for operator in _MULTI_CHAR_OPERATORS:
            if source.startswith(operator, index):
                matched_operator = operator
                break
        if matched_operator is not None:
            tokens.append(_Token("OP", matched_operator))
            index += len(matched_operator)
            continue

        if char in "+-*/%&|^~!=<>()[]{}?:,.;.":
            tokens.append(_Token("OP", char))
            index += 1
            continue

        raise GMLTranspileError(f"Unexpected character: {char}")

    tokens.append(_EOF)
    return tokens


def _source_startswith_directive(source: str, index: int, directive: str) -> bool:
    if not source.startswith(directive, index):
        return False
    end = index + len(directive)
    if end >= len(source):
        return True
    next_char = source[end]
    return not (next_char.isalnum() or next_char == "_")


def _expression_tokens(source: str) -> list[_Token]:
    return [token for token in _tokenize(source) if token.kind != "NEWLINE"]


def _read_number(source: str, start: int) -> int:
    if source.startswith(("0b", "0B"), start):
        return _read_binary_number(source, start)

    if source.startswith(("0x", "0X"), start):
        return _read_hex_number(source, start + 2)

    return _read_decimal_number(source, start)


def _read_decimal_number(source: str, start: int) -> int:
    index = start
    if source[index] == ".":
        index += 1
        index, saw_fraction_digit = _read_separated_digits(
            source,
            index,
            "0123456789",
            "numeric",
        )
        if not saw_fraction_digit:
            raise GMLTranspileError("Malformed numeric literal")
        return index

    index, _saw_integer_digit = _read_separated_digits(
        source,
        index,
        "0123456789",
        "numeric",
    )
    if index < len(source) and source[index] == ".":
        index += 1
        if index < len(source) and source[index] == "_":
            raise GMLTranspileError("Malformed numeric literal")
        index, _saw_fraction_digit = _read_separated_digits(
            source,
            index,
            "0123456789",
            "numeric",
        )

    return index


def _read_hex_number(source: str, start: int) -> int:
    index, saw_digit = _read_separated_digits(
        source,
        start,
        "0123456789abcdef",
        "hexadecimal",
    )

    if not saw_digit:
        raise GMLTranspileError("Malformed hexadecimal literal")

    if index < len(source) and source[index].isalnum():
        raise GMLTranspileError(f"Invalid hexadecimal literal digit: {source[index]}")

    return index


def _read_hash_color_literal(source: str, start: int) -> tuple[str, int]:
    hex_start = start + 1
    hex_end = hex_start + 6
    if hex_end > len(source):
        raise GMLTranspileError("Malformed hash color literal")

    value = source[hex_start:hex_end]
    if any(char.lower() not in "0123456789abcdef" for char in value):
        raise GMLTranspileError("Malformed hash color literal")

    if hex_end < len(source) and source[hex_end].isalnum():
        raise GMLTranspileError(f"Invalid hash color literal digit: {source[hex_end]}")

    red = value[0:2]
    green = value[2:4]
    blue = value[4:6]
    return f"0x{blue}{green}{red}".lower(), hex_end


def _read_binary_number(source: str, start: int) -> int:
    index, saw_digit = _read_separated_digits(
        source,
        start + 2,
        "01",
        "binary",
    )

    if not saw_digit:
        raise GMLTranspileError("Malformed binary literal")

    if index < len(source) and source[index].isalnum():
        raise GMLTranspileError(f"Invalid binary literal digit: {source[index]}")

    return index


def _read_separated_digits(
    source: str,
    start: int,
    valid_digits: str,
    literal_name: str,
) -> tuple[int, bool]:
    index = start
    saw_digit = False
    previous_was_digit = False

    while index < len(source):
        char = source[index]
        if char.lower() in valid_digits:
            saw_digit = True
            previous_was_digit = True
            index += 1
            continue

        if char == "_":
            next_char = source[index + 1] if index + 1 < len(source) else ""
            if (
                not previous_was_digit
                or next_char == ""
                or next_char.lower() not in valid_digits
            ):
                raise GMLTranspileError(f"Malformed {literal_name} literal")
            previous_was_digit = False
            index += 1
            continue

        break

    return index, saw_digit


def _is_float_like_number(value: str) -> bool:
    return "." in value


def _read_string(source: str, start: int) -> str:
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
            return source[start:index + 1]
        index += 1
    raise GMLTranspileError("Unterminated string literal")
