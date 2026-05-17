# pyright: reportPrivateUsage=false
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .identifiers import _validate_gml_identifier
from .model import GMLTranspileError
from .utils import _join_macro_continuation_lines, _strip_comments


_DIRECTIVE_RE = re.compile(r"^\s*#([A-Za-z_][A-Za-z0-9_]*)\b(.*)$")
_DEFINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?$")
_DEFINED_RE = re.compile(r"^defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)$", re.IGNORECASE)
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


def preprocess_gml_source(
    source: str,
    *,
    macro_configuration: str | None = None,
    active_symbols: Iterable[str] | None = None,
) -> GMLPreprocessResult:
    """Apply compile-time directive handling before tokenization."""
    symbols = {symbol.casefold() for symbol in (active_symbols or ())}
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
            output_lines.append(line)
            continue

        if directive in _EDITOR_ONLY_DIRECTIVES:
            output_lines.append("")
            continue

        if directive == "#define":
            output_lines.append(_preprocess_define(directive_body, symbols, diagnostics, line_number, line))
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


def _preprocess_define(
    directive_body: str,
    symbols: set[str],
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
        return f"#macro {name} {value}"
    return ""


def _evaluate_conditional(
    directive: str,
    expression: str,
    symbols: set[str],
    diagnostics: list[GMLPreprocessorDiagnostic],
    line_number: int,
    line: str,
) -> bool:
    if directive == "#ifdef":
        return _symbol_defined(expression, symbols)
    if directive == "#ifndef":
        return not _symbol_defined(expression, symbols)

    value = _evaluate_condition_expression(expression, symbols)
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


def _evaluate_condition_expression(expression: str, symbols: set[str]) -> bool | None:
    expression = expression.strip()
    if not expression:
        return None
    if expression.startswith("!"):
        value = _evaluate_condition_expression(expression[1:].strip(), symbols)
        return None if value is None else not value
    if expression.casefold() in {"true", "1"}:
        return True
    if expression.casefold() in {"false", "0"}:
        return False
    defined_match = _DEFINED_RE.match(expression)
    if defined_match is not None:
        return _symbol_defined(defined_match.group(1), symbols)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expression):
        return _symbol_defined(expression, symbols)
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
]
