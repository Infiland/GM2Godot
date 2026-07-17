# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from .constants import _BLOCK_DELIMITER_REPLACEMENTS, _MULTI_CHAR_OPERATORS
from .identifiers import _validate_gml_identifier
from .lexical import (
    _is_verbatim_string_start,
    _read_ordinary_string,
    _read_verbatim_string,
)
from .model import GMLTranspileError, _Token


_GML_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "{": "{",
    "}": "}",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_OCTAL_DIGITS = frozenset("01234567")


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    newline_positions = [
        position for position, char in enumerate(source) if char == "\n"
    ]
    index = 0
    while index < len(source):
        char = source[index]
        line, column = _line_column_from_newline_positions(
            newline_positions,
            index,
        )

        if char in "\r\n":
            if char == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
                index += 1
            tokens.append(_Token("NEWLINE", "\n", line=line, column=column, index=index))
            index += 1
            continue

        if char.isspace():
            index += 1
            continue

        if _is_verbatim_string_start(source, index):
            try:
                verbatim = _read_verbatim_string(source, index)
            except GMLTranspileError as exc:
                raise exc.with_location(line, column) from exc
            tokens.append(
                _Token(
                    "VERBATIM_STRING",
                    verbatim,
                    line=line,
                    column=column,
                    index=index,
                )
            )
            index += len(verbatim)
            continue

        if char.isdigit() or (char == "." and index + 1 < len(source) and source[index + 1].isdigit()):
            try:
                number_end = _read_number(source, index)
            except GMLTranspileError as exc:
                raise exc.with_location(line, column) from exc
            tokens.append(_Token("NUMBER", source[index:number_end].replace("_", ""), line=line, column=column, index=index))
            index = number_end
            continue

        if char == '"' or char == "'":
            try:
                tokens.append(_Token("STRING", _read_string(source, index), line=line, column=column, index=index))
            except GMLTranspileError as exc:
                raise exc.with_location(line, column) from exc
            index += len(tokens[-1].value)
            continue

        if char == "$":
            if source.startswith('$"', index):
                try:
                    template = _read_template_string(source, index)
                except GMLTranspileError as exc:
                    raise exc.with_location(line, column) from exc
                tokens.append(
                    _Token(
                        "TEMPLATE_STRING",
                        template,
                        line=line,
                        column=column,
                        index=index,
                    )
                )
                index += len(template)
                continue
            next_char = source[index + 1] if index + 1 < len(source) else ""
            if next_char.lower() in "0123456789abcdef" or next_char == "_":
                try:
                    hex_end = _read_hex_number(source, index + 1)
                except GMLTranspileError as exc:
                    raise exc.with_location(line, column) from exc
                tokens.append(_Token("NUMBER", f"0x{source[index + 1:hex_end].replace('_', '')}", line=line, column=column, index=index))
                index = hex_end
            else:
                tokens.append(_Token("OP", char, line=line, column=column, index=index))
                index += 1
            continue

        if char == "#":
            if _source_startswith_directive(source, index, "#macro"):
                tokens.append(_Token("DIRECTIVE", "#macro", line=line, column=column, index=index))
                index += len("#macro")
                continue
            previous_index = index - 1
            while previous_index >= 0 and source[previous_index].isspace():
                previous_index -= 1
            if previous_index >= 0 and source[previous_index] == "[":
                tokens.append(_Token("OP", char, line=line, column=column, index=index))
                index += 1
                continue
            try:
                color_literal, color_end = _read_hash_color_literal(source, index)
            except GMLTranspileError as exc:
                raise exc.with_location(line, column) from exc
            tokens.append(_Token("NUMBER", color_literal, line=line, column=column, index=index))
            index = color_end
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                index += 1
            identifier = source[start:index]
            try:
                _validate_gml_identifier(identifier)
            except GMLTranspileError as exc:
                raise exc.with_location(line, column) from exc
            block_delimiter = _BLOCK_DELIMITER_REPLACEMENTS.get(identifier)
            if block_delimiter is not None:
                tokens.append(_Token("OP", block_delimiter, line=line, column=column, index=start))
            else:
                tokens.append(_Token("IDENT", identifier, line=line, column=column, index=start))
            continue

        matched_operator = None
        for operator in _MULTI_CHAR_OPERATORS:
            if source.startswith(operator, index):
                matched_operator = operator
                break
        if matched_operator is not None:
            tokens.append(_Token("OP", matched_operator, line=line, column=column, index=index))
            index += len(matched_operator)
            continue

        if char in "+-*/%&|^~!=<>()[]{}?:,.;.@":
            tokens.append(_Token("OP", char, line=line, column=column, index=index))
            index += 1
            continue

        raise GMLTranspileError(f"Unexpected character: {char}", line=line, column=column)

    eof_line, eof_column = _line_column_from_newline_positions(
        newline_positions,
        len(source),
    )
    tokens.append(_Token("EOF", "", line=eof_line, column=eof_column, index=len(source)))
    return tokens


def _line_column(source: str, index: int) -> tuple[int, int]:
    line = source.count("\n", 0, index) + 1
    line_start = source.rfind("\n", 0, index)
    if line_start == -1:
        return line, index + 1
    return line, index - line_start


def _line_column_from_newline_positions(
    newline_positions: Sequence[int],
    index: int,
) -> tuple[int, int]:
    line_index = bisect_left(newline_positions, index)
    if line_index == 0:
        return 1, index + 1
    return line_index + 1, index - newline_positions[line_index - 1]


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
    return _read_ordinary_string(source, start)


def _decode_gml_string_literal(source: str) -> str:
    if len(source) < 2 or source[0] not in "\"'" or source[-1] != source[0]:
        raise GMLTranspileError("Invalid string literal")

    decoded: list[str] = []
    index = 1
    end = len(source) - 1
    while index < end:
        char = source[index]
        if char == "\\":
            value, index = _decode_gml_escape(source, index)
            decoded.append(value)
            continue
        decoded.append(char)
        index += 1
    return "".join(decoded)


def _read_template_string(source: str, start: int) -> str:
    end, _parts = _scan_template_string(source, start)
    return source[start:end]


def _split_template_string(source: str) -> tuple[tuple[str, str], ...]:
    end, parts = _scan_template_string(source, 0)
    if end != len(source):
        raise GMLTranspileError("Unexpected text after template string literal")
    return tuple(parts)


def _scan_template_string(
    source: str,
    start: int,
) -> tuple[int, list[tuple[str, str]]]:
    if not source.startswith('$"', start):
        raise GMLTranspileError('Template string literal must start with $"')

    parts: list[tuple[str, str]] = []
    text: list[str] = []
    index = start + 2

    while index < len(source):
        char = source[index]
        if char in "\r\n":
            raise GMLTranspileError(
                "Template string literal text cannot contain a newline"
            )
        if char == "\\":
            if index + 1 >= len(source):
                break
            next_char = source[index + 1]
            if next_char in "\r\n":
                raise GMLTranspileError(
                    "Template string literal text cannot contain a newline"
                )
            decoded, index = _decode_gml_escape(source, index)
            text.append(decoded)
            continue
        if char == '"':
            if text:
                parts.append(("text", "".join(text)))
            return index + 1, parts
        if char == "{":
            if text:
                parts.append(("text", "".join(text)))
                text.clear()
            expression_end = _read_template_expression(source, index + 1)
            expression_source = source[index + 1:expression_end]
            if not expression_source.strip():
                raise GMLTranspileError(
                    "Template string interpolation cannot be empty"
                )
            parts.append(("expression", expression_source))
            index = expression_end + 1
            continue
        text.append(char)
        index += 1

    raise GMLTranspileError("Unterminated template string literal")


def _decode_gml_escape(source: str, start: int) -> tuple[str, int]:
    escape_code = source[start + 1]
    simple_escape = _GML_SIMPLE_ESCAPES.get(escape_code)
    if simple_escape is not None:
        return simple_escape, start + 2

    if escape_code in "ux":
        digit_start = start + 2
        digit_end = digit_start
        while digit_end < len(source) and source[digit_end] in _HEX_DIGITS:
            digit_end += 1
        if digit_end == digit_start:
            escape_name = "Unicode" if escape_code == "u" else "hexadecimal"
            raise GMLTranspileError(
                f"GameMaker {escape_name} escape \\{escape_code} requires at least one hex digit"
            )
        return _decode_gml_codepoint(
            source[digit_start:digit_end],
            16,
            f"\\{escape_code}",
        ), digit_end

    if escape_code in _OCTAL_DIGITS:
        digit_end = start + 1
        max_digit_end = min(start + 4, len(source))
        while (
            digit_end < max_digit_end
            and source[digit_end] in _OCTAL_DIGITS
        ):
            digit_end += 1
        return _decode_gml_codepoint(
            source[start + 1:digit_end],
            8,
            "octal",
        ), digit_end

    return escape_code, start + 2


def _decode_gml_codepoint(
    digits: str,
    base: int,
    escape_name: str,
) -> str:
    codepoint = int(digits, base)
    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        raise GMLTranspileError(
            f"GameMaker string {escape_name} escape is not a valid Unicode scalar value: {digits}"
        )
    return chr(codepoint)


def _read_template_expression(source: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(source):
        if source.startswith('$"', index):
            nested_template = _read_template_string(source, index)
            index += len(nested_template)
            continue

        if _is_verbatim_string_start(source, index):
            try:
                nested_verbatim = _read_verbatim_string(source, index)
            except GMLTranspileError as exc:
                raise GMLTranspileError(
                    "Unterminated template string interpolation"
                ) from exc
            index += len(nested_verbatim)
            continue

        char = source[index]
        if char in "\"'":
            try:
                nested_string = _read_string(source, index)
            except GMLTranspileError as exc:
                raise GMLTranspileError(
                    "Unterminated template string interpolation"
                ) from exc
            index += len(nested_string)
            continue
        if source.startswith("//", index):
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end == -1:
                raise GMLTranspileError(
                    "Unterminated block comment in template string interpolation"
                )
            index = comment_end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1

    raise GMLTranspileError("Unterminated template string interpolation")
