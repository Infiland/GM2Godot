# pyright: reportPrivateUsage=false
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, TypeAlias

from .identifiers import _validate_gml_identifier
from .lexical import _is_verbatim_string_start, _read_verbatim_string
from .model import GMLTranspileError
from .tokens import _read_template_string
from .utils import _join_macro_continuation_lines, _macro_configuration_matches, _strip_comments


_DIRECTIVE_RE = re.compile(r"^\s*#([A-Za-z_][A-Za-z0-9_]*)\b(.*)$")
_DEFINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?$")
_MACRO_RE = re.compile(r"^(?:(?P<configuration>[A-Za-z_][A-Za-z0-9_]*):)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?P<value>.*))?$")
_CONDITION_TOKEN_RE = re.compile(
    r"\s*("
    r"&&|\|\||\^\^|==|!=|<=|>=|[()!<>+-]"
    r"|\$[0-9A-Fa-f_]+"
    r"|0[xX][0-9A-Fa-f_]+"
    r"|0[bB][01_]+"
    r"|(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)"
    r"|[A-Za-z_][A-Za-z0-9_]*"
    r"|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'"
    r")",
    re.IGNORECASE,
)
_EDITOR_ONLY_DIRECTIVES = frozenset({"#region", "#endregion"})
_SUPPORTED_DIRECTIVES = frozenset({
    "#define",
    "#elif",
    "#else",
    "#endif",
    "#if",
    "#ifdef",
    "#ifndef",
    "#macro",
    *_EDITOR_ONLY_DIRECTIVES,
})
_PreprocessValue: TypeAlias = bool | float | str


@dataclass(frozen=True)
class GMLPreprocessorDiagnostic:
    line: int
    directive: str
    message: str
    source: str

    def format(self) -> str:
        return f"{self.message} at line {self.line}: {self.source.strip()}"


@dataclass(frozen=True)
class GMLPreprocessResult:
    source: str
    diagnostics: tuple[GMLPreprocessorDiagnostic, ...]


@dataclass
class _ConditionalFrame:
    parent_active: bool
    current_active: bool
    condition_satisfied: bool
    else_seen: bool = False


def _blank_layout_span(buffer: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if buffer[index] not in "\r\n":
            buffer[index] = " "


def _preprocessor_source_views(source: str) -> tuple[str, str]:
    """Return comment-free and code-only views without shifting source offsets."""
    comments_masked = list(source)
    code_only = list(source)
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char not in "\r\n":
                code_only[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if _is_verbatim_string_start(source, index):
            literal = _read_verbatim_string(source, index)
            end = index + len(literal)
            _blank_layout_span(code_only, index, end)
            index = end
            continue

        if source.startswith('$"', index):
            literal = _read_template_string(source, index)
            end = index + len(literal)
            _blank_layout_span(code_only, index, end)
            index = end
            continue

        if char in ("'", '"'):
            quote = char
            code_only[index] = " "
            index += 1
            continue

        if source.startswith("//", index):
            end = index + 2
            while end < len(source) and source[end] not in "\r\n":
                end += 1
            _blank_layout_span(comments_masked, index, end)
            _blank_layout_span(code_only, index, end)
            index = end
            continue

        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            end = len(source) if comment_end == -1 else comment_end + 2
            _blank_layout_span(comments_masked, index, end)
            _blank_layout_span(code_only, index, end)
            index = end
            continue

        index += 1

    return "".join(comments_masked), "".join(code_only)


def _source_line_spans(source: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(source):
        if source[index] == "\r":
            end = index + 1
            if end < len(source) and source[end] == "\n":
                end += 1
            spans.append((start, end))
            start = end
            index = end
            continue
        if source[index] == "\n":
            end = index + 1
            spans.append((start, end))
            start = end
        index += 1
    if start < len(source):
        spans.append((start, len(source)))
    return tuple(spans)


def _line_content(source: str, span: tuple[int, int]) -> str:
    start, end = span
    if end > start and source[end - 1] == "\n":
        end -= 1
        if end > start and source[end - 1] == "\r":
            end -= 1
    elif end > start and source[end - 1] == "\r":
        end -= 1
    return source[start:end]


def _logical_macro_line(
    comments_masked: str,
    line_spans: tuple[tuple[int, int], ...],
    line_index: int,
) -> tuple[str, int]:
    logical_line = _line_content(comments_masked, line_spans[line_index])
    last_line_index = line_index
    while logical_line.lstrip().casefold().startswith("#macro") and logical_line.rstrip().endswith("\\"):
        logical_line = logical_line.rstrip()[:-1].rstrip()
        if last_line_index + 1 >= len(line_spans):
            break
        last_line_index += 1
        continuation = _line_content(comments_masked, line_spans[last_line_index])
        logical_line = f"{logical_line} {continuation.lstrip()}"
    return logical_line, last_line_index


def preprocess_gml_source(
    source: str,
    *,
    macro_configuration: str | None = None,
    active_symbols: Iterable[str] | None = None,
) -> GMLPreprocessResult:
    """Apply compile-time directive handling before tokenization."""
    symbols = {symbol.casefold() for symbol in (active_symbols or ())}
    symbol_values: dict[str, str] = {}
    if macro_configuration:
        symbols.add(macro_configuration.casefold())

    clean_source = _join_macro_continuation_lines(_strip_comments(source))
    output_lines: list[str] = []
    diagnostics: list[GMLPreprocessorDiagnostic] = []
    conditionals: list[_ConditionalFrame] = []

    for line_number, line in enumerate(clean_source.splitlines(), start=1):
        directive_match = _DIRECTIVE_RE.match(line)
        directive = f"#{directive_match.group(1)}".casefold() if directive_match is not None else None
        directive_body = directive_match.group(2).strip() if directive_match is not None else ""
        active = _current_active(conditionals)

        if directive in ("#if", "#ifdef", "#ifndef"):
            condition_active = False
            if active:
                condition_active = _evaluate_conditional(
                    directive,
                    directive_body,
                    symbols,
                    symbol_values,
                    diagnostics,
                    line_number,
                    line,
                )
            conditionals.append(
                _ConditionalFrame(
                    parent_active=active,
                    current_active=active and condition_active,
                    condition_satisfied=active and condition_active,
                )
            )
            output_lines.append("")
            continue

        if directive == "#elif":
            if not conditionals:
                _add_diagnostic(diagnostics, line_number, directive, "Unmatched preprocessor directive #elif", line)
            else:
                frame = conditionals[-1]
                if frame.else_seen:
                    _add_diagnostic(diagnostics, line_number, directive, "#elif after #else is not supported", line)
                    frame.current_active = False
                elif not frame.parent_active or frame.condition_satisfied:
                    frame.current_active = False
                else:
                    condition_active = _evaluate_conditional(
                        directive,
                        directive_body,
                        symbols,
                        symbol_values,
                        diagnostics,
                        line_number,
                        line,
                    )
                    frame.current_active = frame.parent_active and condition_active
                    frame.condition_satisfied = condition_active
            output_lines.append("")
            continue

        if directive == "#else":
            if not conditionals:
                _add_diagnostic(diagnostics, line_number, directive, "Unmatched preprocessor directive #else", line)
            else:
                frame = conditionals[-1]
                if frame.else_seen:
                    _add_diagnostic(diagnostics, line_number, directive, "Duplicate preprocessor directive #else", line)
                    frame.current_active = False
                else:
                    frame.current_active = frame.parent_active and not frame.condition_satisfied
                    frame.condition_satisfied = True
                    frame.else_seen = True
            output_lines.append("")
            continue

        if directive == "#endif":
            if not conditionals:
                _add_diagnostic(diagnostics, line_number, directive, "Unmatched preprocessor directive #endif", line)
            else:
                conditionals.pop()
            output_lines.append("")
            continue

        if not active:
            output_lines.append("")
            continue

        if directive is None:
            output_lines.append(line)
            continue

        if directive == "#macro":
            _preprocess_macro(
                directive_body,
                symbols,
                symbol_values,
                macro_configuration,
            )
            output_lines.append(line)
            continue

        if directive in _EDITOR_ONLY_DIRECTIVES:
            output_lines.append("")
            continue

        if directive == "#define":
            output_lines.append(
                _preprocess_define(
                    directive_body,
                    symbols,
                    symbol_values,
                    diagnostics,
                    line_number,
                    line,
                )
            )
            continue

        directive_name = directive if directive in _SUPPORTED_DIRECTIVES else directive
        _add_diagnostic(
            diagnostics,
            line_number,
            directive_name,
            f"Unsupported preprocessor directive {directive_name}",
            line,
        )
        output_lines.append("")

    if conditionals:
        _add_diagnostic(
            diagnostics,
            len(clean_source.splitlines()) or 1,
            "#if",
            "Unclosed preprocessor conditional",
            "#if",
        )

    if diagnostics:
        raise GMLTranspileError(diagnostics[0].format())

    return GMLPreprocessResult("\n".join(output_lines), tuple(diagnostics))


def preprocess_gml_source_preserving_layout(
    source: str,
    *,
    macro_configuration: str | None = None,
    active_symbols: Iterable[str] | None = None,
) -> GMLPreprocessResult:
    """Select active preprocessor branches while preserving every source offset.

    Conditional directives and inactive code are replaced with spaces, while
    original line endings and active code remain byte-for-byte aligned. This is
    used by modern-script discovery, whose declaration and initializer offsets
    must still address the original GameMaker source.
    """
    symbols = {symbol.casefold() for symbol in (active_symbols or ())}
    symbol_values: dict[str, str] = {}
    if macro_configuration:
        symbols.add(macro_configuration.casefold())

    comments_masked, code_only = _preprocessor_source_views(source)
    line_spans = _source_line_spans(source)
    output = list(source)
    diagnostics: list[GMLPreprocessorDiagnostic] = []
    conditionals: list[_ConditionalFrame] = []
    line_index = 0

    while line_index < len(line_spans):
        first_line_index = line_index
        clean_line = _line_content(comments_masked, line_spans[first_line_index])
        code_line = _line_content(code_only, line_spans[first_line_index])
        code_directive_match = _DIRECTIVE_RE.match(code_line)
        directive_match = (
            _DIRECTIVE_RE.match(clean_line)
            if code_directive_match is not None
            else None
        )
        directive = (
            f"#{directive_match.group(1)}".casefold()
            if directive_match is not None
            else None
        )

        last_line_index = first_line_index
        logical_line = clean_line
        if directive == "#macro":
            logical_line, last_line_index = _logical_macro_line(
                comments_masked,
                line_spans,
                first_line_index,
            )
            directive_match = _DIRECTIVE_RE.match(logical_line)

        directive_body = (
            directive_match.group(2).strip()
            if directive_match is not None
            else ""
        )
        active = _current_active(conditionals)
        span_start = line_spans[first_line_index][0]
        span_end = line_spans[last_line_index][1]
        line_number = first_line_index + 1
        line_index = last_line_index + 1

        if directive in ("#if", "#ifdef", "#ifndef"):
            condition_active = False
            if active:
                condition_active = _evaluate_conditional(
                    directive,
                    directive_body,
                    symbols,
                    symbol_values,
                    diagnostics,
                    line_number,
                    logical_line,
                )
            conditionals.append(
                _ConditionalFrame(
                    parent_active=active,
                    current_active=active and condition_active,
                    condition_satisfied=active and condition_active,
                )
            )
            _blank_layout_span(output, span_start, span_end)
            continue

        if directive == "#elif":
            if not conditionals:
                _add_diagnostic(
                    diagnostics,
                    line_number,
                    directive,
                    "Unmatched preprocessor directive #elif",
                    logical_line,
                )
            else:
                frame = conditionals[-1]
                if frame.else_seen:
                    _add_diagnostic(
                        diagnostics,
                        line_number,
                        directive,
                        "#elif after #else is not supported",
                        logical_line,
                    )
                    frame.current_active = False
                elif not frame.parent_active or frame.condition_satisfied:
                    frame.current_active = False
                else:
                    condition_active = _evaluate_conditional(
                        directive,
                        directive_body,
                        symbols,
                        symbol_values,
                        diagnostics,
                        line_number,
                        logical_line,
                    )
                    frame.current_active = frame.parent_active and condition_active
                    frame.condition_satisfied = condition_active
            _blank_layout_span(output, span_start, span_end)
            continue

        if directive == "#else":
            if not conditionals:
                _add_diagnostic(
                    diagnostics,
                    line_number,
                    directive,
                    "Unmatched preprocessor directive #else",
                    logical_line,
                )
            else:
                frame = conditionals[-1]
                if frame.else_seen:
                    _add_diagnostic(
                        diagnostics,
                        line_number,
                        directive,
                        "Duplicate preprocessor directive #else",
                        logical_line,
                    )
                    frame.current_active = False
                else:
                    frame.current_active = frame.parent_active and not frame.condition_satisfied
                    frame.condition_satisfied = True
                    frame.else_seen = True
            _blank_layout_span(output, span_start, span_end)
            continue

        if directive == "#endif":
            if not conditionals:
                _add_diagnostic(
                    diagnostics,
                    line_number,
                    directive,
                    "Unmatched preprocessor directive #endif",
                    logical_line,
                )
            else:
                conditionals.pop()
            _blank_layout_span(output, span_start, span_end)
            continue

        if not active:
            _blank_layout_span(output, span_start, span_end)
            continue

        if directive is None:
            continue

        if directive == "#macro":
            _preprocess_macro(
                directive_body,
                symbols,
                symbol_values,
                macro_configuration,
            )
            continue

        if directive in _EDITOR_ONLY_DIRECTIVES:
            _blank_layout_span(output, span_start, span_end)
            continue

        if directive == "#define":
            _preprocess_define(
                directive_body,
                symbols,
                symbol_values,
                diagnostics,
                line_number,
                logical_line,
            )
            continue

        directive_name = directive if directive in _SUPPORTED_DIRECTIVES else directive
        _add_diagnostic(
            diagnostics,
            line_number,
            directive_name,
            f"Unsupported preprocessor directive {directive_name}",
            logical_line,
        )
        _blank_layout_span(output, span_start, span_end)

    if conditionals:
        _add_diagnostic(
            diagnostics,
            len(line_spans) or 1,
            "#if",
            "Unclosed preprocessor conditional",
            "#if",
        )

    if diagnostics:
        raise GMLTranspileError(diagnostics[0].format())

    rendered_source = "".join(output)
    if len(rendered_source) != len(source):
        raise AssertionError("Layout-preserving preprocessing changed source length")
    return GMLPreprocessResult(rendered_source, tuple(diagnostics))


def _preprocess_define(
    directive_body: str,
    symbols: set[str],
    symbol_values: dict[str, str],
    diagnostics: list[GMLPreprocessorDiagnostic],
    line_number: int,
    line: str,
) -> str:
    match = _DEFINE_RE.match(directive_body)
    if match is None:
        _add_diagnostic(diagnostics, line_number, "#define", "Invalid preprocessor directive #define", line)
        return ""
    name = match.group(1)
    value = (match.group(2) or "").strip()
    try:
        _validate_gml_identifier(name)
    except GMLTranspileError as exc:
        _add_diagnostic(diagnostics, line_number, "#define", str(exc), line)
        return ""
    symbols.add(name.casefold())
    if value:
        symbol_values[name.casefold()] = value
        return f"#macro {name} {value}"
    return ""


def _preprocess_macro(
    directive_body: str,
    symbols: set[str],
    symbol_values: dict[str, str],
    macro_configuration: str | None,
) -> None:
    match = _MACRO_RE.match(directive_body)
    if match is None:
        return
    configuration = match.group("configuration")
    if configuration is not None and not _macro_configuration_matches(configuration, macro_configuration):
        return
    name = match.group("name")
    value = (match.group("value") or "").strip()
    symbols.add(name.casefold())
    if value:
        symbol_values[name.casefold()] = value


def _evaluate_conditional(
    directive: str,
    expression: str,
    symbols: set[str],
    symbol_values: dict[str, str],
    diagnostics: list[GMLPreprocessorDiagnostic],
    line_number: int,
    line: str,
) -> bool:
    if directive == "#ifdef":
        return _symbol_defined(expression, symbols)
    if directive == "#ifndef":
        return not _symbol_defined(expression, symbols)

    value = _evaluate_condition_expression(expression, symbols, symbol_values)
    if value is None:
        _add_diagnostic(
            diagnostics,
            line_number,
            directive,
            f"Unsupported preprocessor condition {expression!r}",
            line,
        )
        return False
    return value


def _evaluate_condition_expression(
    expression: str,
    symbols: set[str],
    symbol_values: dict[str, str],
) -> bool | None:
    tokens = _condition_tokens(expression)
    if not tokens:
        return None
    parser = _ConditionParser(tokens, symbols, symbol_values)
    value = parser.parse()
    if value is None or not parser.at_end():
        return None
    return _condition_truthy(value)


def _condition_tokens(expression: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expression):
        match = _CONDITION_TOKEN_RE.match(expression, index)
        if match is None:
            if expression[index:].strip() == "":
                break
            return []
        tokens.append(match.group(1))
        index = match.end()
    return tokens


class _ConditionParser:
    def __init__(
        self,
        tokens: list[str],
        symbols: set[str],
        symbol_values: dict[str, str],
    ) -> None:
        self.tokens = tokens
        self.symbols = symbols
        self.symbol_values = symbol_values
        self.position = 0

    def at_end(self) -> bool:
        return self.position >= len(self.tokens)

    def parse(self) -> _PreprocessValue | None:
        return self._parse_or()

    def _parse_or(self) -> _PreprocessValue | None:
        left = self._parse_and()
        if left is None:
            return None
        while self._check("||", "or", "^^", "xor"):
            operator = self._advance()
            right = self._parse_and()
            if right is None:
                return None
            if operator.casefold() in ("^^", "xor"):
                left = _condition_truthy(left) != _condition_truthy(right)
            else:
                left = _condition_truthy(left) or _condition_truthy(right)
        return left

    def _parse_and(self) -> _PreprocessValue | None:
        left = self._parse_comparison()
        if left is None:
            return None
        while self._match("&&", "and"):
            right = self._parse_comparison()
            if right is None:
                return None
            left = _condition_truthy(left) and _condition_truthy(right)
        return left

    def _parse_comparison(self) -> _PreprocessValue | None:
        left = self._parse_unary()
        if left is None:
            return None
        while self._check("==", "!=", "<", "<=", ">", ">="):
            operator = self._advance()
            right = self._parse_unary()
            if right is None:
                return None
            compared = _compare_condition_values(left, right, operator)
            if compared is None:
                return None
            left = compared
        return left

    def _parse_unary(self) -> _PreprocessValue | None:
        if self._match("!", "not"):
            value = self._parse_unary()
            return None if value is None else not _condition_truthy(value)
        if self._match("+"):
            value = self._parse_unary()
            return _condition_numeric_value(value) if value is not None else None
        if self._match("-"):
            value = self._parse_unary()
            number = _condition_numeric_value(value) if value is not None else None
            return None if number is None else -number
        return self._parse_primary()

    def _parse_primary(self) -> _PreprocessValue | None:
        if self._match("("):
            value = self._parse_or()
            if value is None or not self._match(")"):
                return None
            return value
        if self._match("defined"):
            if not self._match("(") or self.at_end():
                return None
            name = self._advance()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not self._match(")"):
                return None
            return _symbol_defined(name, self.symbols)
        if self.at_end():
            return None
        token = self._advance()
        return _condition_token_value(token, self.symbols, self.symbol_values)

    def _match(self, *values: str) -> bool:
        if self._check(*values):
            self.position += 1
            return True
        return False

    def _check(self, *values: str) -> bool:
        if self.at_end():
            return False
        current = self.tokens[self.position]
        return any(current.casefold() == value.casefold() for value in values)

    def _advance(self) -> str:
        token = self.tokens[self.position]
        self.position += 1
        return token


def _condition_token_value(
    token: str,
    symbols: set[str],
    symbol_values: dict[str, str],
) -> _PreprocessValue | None:
    lowered = token.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    literal = _condition_literal_value(token)
    if literal is not None:
        return literal
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
        value = symbol_values.get(lowered)
        if value is not None:
            parsed_value = _condition_literal_value(value)
            return parsed_value
        return _symbol_defined(token, symbols)
    return None


def _condition_literal_value(value: str) -> _PreprocessValue | None:
    stripped = value.strip()
    if stripped.casefold() == "true":
        return True
    if stripped.casefold() == "false":
        return False
    number = _condition_number_value(stripped)
    if number is not None:
        return number
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        return stripped[1:-1]
    return None


def _condition_number_value(value: str) -> float | None:
    cleaned = value.replace("_", "")
    sign = 1.0
    if cleaned.startswith(("+", "-")):
        if cleaned[0] == "-":
            sign = -1.0
        cleaned = cleaned[1:]
    if re.fullmatch(r"\$[0-9A-Fa-f]+", cleaned):
        return sign * float(int(cleaned[1:], 16))
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", cleaned):
        return sign * float(int(cleaned[2:], 16))
    if re.fullmatch(r"0[bB][01]+", cleaned):
        return sign * float(int(cleaned[2:], 2))
    if re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        return sign * float(cleaned)
    return None


def _condition_numeric_value(value: _PreprocessValue) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, float):
        return value
    return None


def _condition_truthy(value: _PreprocessValue) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value > 0.0
    return value != ""


def _compare_condition_values(
    left: _PreprocessValue,
    right: _PreprocessValue,
    operator: str,
) -> bool | None:
    if isinstance(left, bool):
        left = 1.0 if left else 0.0
    if isinstance(right, bool):
        right = 1.0 if right else 0.0
    if isinstance(left, float) and isinstance(right, float):
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
    if isinstance(left, str) and isinstance(right, str):
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
    return None


def _symbol_defined(name: str, symbols: set[str]) -> bool:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False
    return name.casefold() in symbols


def _current_active(conditionals: list[_ConditionalFrame]) -> bool:
    return all(frame.current_active for frame in conditionals)


def _add_diagnostic(
    diagnostics: list[GMLPreprocessorDiagnostic],
    line_number: int,
    directive: str,
    message: str,
    source: str,
) -> None:
    diagnostics.append(
        GMLPreprocessorDiagnostic(
            line=line_number,
            directive=directive,
            message=message,
            source=source,
        )
    )


__all__ = [
    "GMLPreprocessResult",
    "GMLPreprocessorDiagnostic",
    "preprocess_gml_source",
    "preprocess_gml_source_preserving_layout",
]
