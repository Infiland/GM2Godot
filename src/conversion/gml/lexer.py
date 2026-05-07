from src.conversion.gml.ast import GMLTranspileError, Token, EOF
from src.conversion.gml.operators import MULTI_CHAR_OPERATORS


def tokenize(source):
    tokens = []
    index = 0
    while index < len(source):
        char = source[index]

        if char.isspace():
            index += 1
            continue

        if char.isdigit():
            start = index
            if source[index:index + 2].lower() == "0x":
                index += 2
                while index < len(source) and source[index].lower() in "0123456789abcdef":
                    index += 1
            else:
                while index < len(source) and (source[index].isdigit() or source[index] == "."):
                    index += 1
            tokens.append(Token("NUMBER", source[start:index]))
            continue

        if char == '"' or char == "'":
            tokens.append(Token("STRING", _read_string(source, index)))
            index += len(tokens[-1].value)
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                index += 1
            tokens.append(Token("IDENT", source[start:index]))
            continue

        matched_operator = None
        for operator in MULTI_CHAR_OPERATORS:
            if source.startswith(operator, index):
                matched_operator = operator
                break
        if matched_operator is not None:
            tokens.append(Token("OP", matched_operator))
            index += len(matched_operator)
            continue

        if char in "+-*/%&|^~!=<>()[]{}?:,.;.":
            tokens.append(Token("OP", char))
            index += 1
            continue

        raise GMLTranspileError(f"Unexpected character: {char}")

    tokens.append(EOF)
    return tokens


def _read_string(source, start):
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
