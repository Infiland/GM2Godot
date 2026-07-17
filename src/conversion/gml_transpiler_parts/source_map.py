# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, Literal, TypeAlias

from .constants import _GDSCRIPT_RESERVED_IDENTIFIERS
from .identifiers import _sanitize_gdscript_identifier
from .lexical import (
    _is_verbatim_string_start,
    _read_ordinary_string,
    _read_verbatim_string,
)
from .tokens import _read_template_string

SourceDiagnosticSeverity: TypeAlias = Literal["warning", "error"]

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_DECLARATION_RE = re.compile(r"\b(?:var|globalvar|static)\s+([^;\n]+)")
_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)?\s*\(([^)]*)\)")
_GML_KEYWORDS = frozenset({
    "and",
    "break",
    "case",
    "catch",
    "continue",
    "default",
    "delete",
    "div",
    "do",
    "else",
    "enum",
    "exit",
    "finally",
    "for",
    "function",
    "global",
    "globalvar",
    "if",
    "mod",
    "new",
    "not",
    "or",
    "repeat",
    "return",
    "self",
    "static",
    "switch",
    "then",
    "throw",
    "try",
    "until",
    "var",
    "while",
    "with",
    "xor",
})


@dataclass(frozen=True)
class GMLSourceMapEntry:
    generated_line: int
    source_line: int
    source_column: int
    generated_text: str
    source_text: str
    source_path: str | None = None
    event: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_line": self.generated_line,
            "source_line": self.source_line,
            "source_column": self.source_column,
            "generated_text": self.generated_text,
            "source_text": self.source_text,
            "source_path": self.source_path,
            "event": self.event,
        }


@dataclass(frozen=True)
class GMLSourceMap:
    source_path: str | None
    event: str | None
    entries: tuple[GMLSourceMapEntry, ...]

    def with_generated_line_offset(self, offset: int) -> "GMLSourceMap":
        if offset == 0:
            return self
        return GMLSourceMap(
            source_path=self.source_path,
            event=self.event,
            entries=tuple(
                GMLSourceMapEntry(
                    generated_line=entry.generated_line + offset,
                    source_line=entry.source_line,
                    source_column=entry.source_column,
                    generated_text=entry.generated_text,
                    source_text=entry.source_text,
                    source_path=entry.source_path,
                    event=entry.event,
                )
                for entry in self.entries
            ),
        )

    def with_source_offset(
        self,
        line_offset: int,
        first_line_column_offset: int = 0,
    ) -> "GMLSourceMap":
        if line_offset == 0 and first_line_column_offset == 0:
            return self
        return GMLSourceMap(
            source_path=self.source_path,
            event=self.event,
            entries=tuple(
                GMLSourceMapEntry(
                    generated_line=entry.generated_line,
                    source_line=entry.source_line + line_offset,
                    source_column=(
                        entry.source_column + first_line_column_offset
                        if entry.source_line == 1
                        else entry.source_column
                    ),
                    generated_text=entry.generated_text,
                    source_text=entry.source_text,
                    source_path=entry.source_path,
                    event=entry.event,
                )
                for entry in self.entries
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "source_path": self.source_path,
            "event": self.event,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class GMLTranspileResult:
    code: str
    source_map: GMLSourceMap
    static_scope_id: str | None = None


@dataclass(frozen=True)
class GMLSourceDiagnostic:
    severity: SourceDiagnosticSeverity
    code: str
    message: str
    line: int
    column: int
    identifier: str
    suggested_name: str | None = None


@dataclass(frozen=True)
class _SourceLine:
    line: int
    column: int
    text: str


def build_gml_source_map(
    source: str,
    generated_code: str,
    *,
    source_path: str | None = None,
    event: str | None = None,
    generated_line_offset: int = 0,
) -> GMLSourceMap:
    source_lines = _significant_source_lines(source)
    generated_lines = [
        (index + 1 + generated_line_offset, line)
        for index, line in enumerate(generated_code.splitlines())
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not source_lines or not generated_lines:
        return GMLSourceMap(source_path=source_path, event=event, entries=())

    entries: list[GMLSourceMapEntry] = []
    source_cursor = 0
    for index, (generated_line, generated_text) in enumerate(generated_lines):
        source_line, source_cursor = _source_line_for_generated_text(
            generated_text,
            source_lines,
            source_cursor,
            index,
        )
        entries.append(
            GMLSourceMapEntry(
                generated_line=generated_line,
                source_line=source_line.line,
                source_column=source_line.column,
                generated_text=generated_text.strip(),
                source_text=source_line.text,
                source_path=source_path,
                event=event,
            )
        )
    return GMLSourceMap(source_path=source_path, event=event, entries=tuple(entries))


def _source_line_for_generated_text(
    generated_text: str,
    source_lines: tuple[_SourceLine, ...],
    source_cursor: int,
    generated_index: int,
) -> tuple[_SourceLine, int]:
    identifiers = [
        identifier
        for identifier in _IDENTIFIER_RE.findall(generated_text)
        if not identifier.startswith("GMRuntime") and not identifier.startswith("gml_")
    ]
    for index in range(source_cursor, len(source_lines)):
        source_text = source_lines[index].text
        if any(identifier in source_text for identifier in identifiers):
            return source_lines[index], index + 1
    fallback_index = min(max(source_cursor, generated_index), len(source_lines) - 1)
    return source_lines[fallback_index], min(fallback_index + 1, len(source_lines))


def merge_gml_source_maps(
    maps: Iterable[GMLSourceMap],
    *,
    source_path: str | None = None,
    event: str | None = None,
) -> GMLSourceMap:
    entries: list[GMLSourceMapEntry] = []
    for source_map in maps:
        entries.extend(source_map.entries)
    return GMLSourceMap(
        source_path=source_path,
        event=event,
        entries=tuple(sorted(entries, key=lambda entry: entry.generated_line)),
    )


def write_gml_source_map(gdscript_path: str, source_map: GMLSourceMap) -> str:
    map_path = gml_source_map_path(gdscript_path)
    os.makedirs(os.path.dirname(map_path), exist_ok=True)
    with open(map_path, "w", encoding="utf-8") as map_file:
        json.dump(source_map.to_dict(), map_file, indent=2, sort_keys=True)
        map_file.write("\n")
    return map_path


def gml_source_map_path(gdscript_path: str) -> str:
    return f"{gdscript_path}.gmlmap.json"


def render_gml_source_header(
    *,
    source_path: str | None,
    event: str | None,
    source: str,
    max_comments: int = 8,
) -> str:
    lines: list[str] = []
    if source_path:
        lines.append(f"# GM2Godot source: {source_path}")
    if event:
        lines.append(f"# GM2Godot event: {event}")
    for comment in _source_comments(source)[:max_comments]:
        lines.append(f"# GML line {comment.line}: {comment.text}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def analyze_gml_source_identifiers(source: str) -> tuple[GMLSourceDiagnostic, ...]:
    diagnostics: list[GMLSourceDiagnostic] = []
    declarations = _declared_identifier_locations(source)
    for identifier, line, column in declarations:
        suggested_name = _sanitize_gdscript_identifier(identifier)
        if suggested_name != identifier and identifier in _GDSCRIPT_RESERVED_IDENTIFIERS:
            diagnostics.append(
                GMLSourceDiagnostic(
                    severity="warning",
                    code="GM2GD-GML-RESERVED-NAME",
                    message=(
                        f"GML identifier '{identifier}' collides with a GDScript "
                        f"reserved word; generated name: {suggested_name}"
                    ),
                    line=line,
                    column=column,
                    identifier=identifier,
                    suggested_name=suggested_name,
                )
            )

    identifiers_by_folded_name: dict[str, dict[str, tuple[int, int]]] = {}
    for identifier, line, column in _identifier_locations(source):
        if identifier in _GML_KEYWORDS:
            continue
        identifiers_by_folded_name.setdefault(identifier.casefold(), {}).setdefault(
            identifier,
            (line, column),
        )

    for variants in identifiers_by_folded_name.values():
        if len(variants) < 2:
            continue
        names = sorted(variants)
        for name in names:
            line, column = variants[name]
            diagnostics.append(
                GMLSourceDiagnostic(
                    severity="warning",
                    code="GM2GD-GML-CASE-COLLISION",
                    message=(
                        "GML identifiers differ only by case in a Godot/GDScript "
                        f"output context: {', '.join(names)}"
                    ),
                    line=line,
                    column=column,
                    identifier=name,
                    suggested_name=_case_collision_suggestion(name, names),
                )
            )
    return tuple(diagnostics)


def _blank_source_span(buffer: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if buffer[index] not in "\r\n":
            buffer[index] = " "


def _source_lexical_views(source: str) -> tuple[str, str, str]:
    """Return comment-free, code-only, and string-free source views.

    Every view preserves source length and line endings. This keeps source-map
    locations exact while preventing comment markers or identifiers inside any
    string literal from being interpreted as GML syntax.
    """

    comments_stripped = list(source)
    code_only = list(source)
    strings_masked = list(source)
    index = 0
    while index < len(source):
        if _is_verbatim_string_start(source, index):
            literal = _read_verbatim_string(source, index)
            end = index + len(literal)
            _blank_source_span(code_only, index, end)
            _blank_source_span(strings_masked, index, end)
            index = end
            continue

        if source.startswith('$"', index):
            literal = _read_template_string(source, index)
            end = index + len(literal)
            _blank_source_span(code_only, index, end)
            _blank_source_span(strings_masked, index, end)
            index = end
            continue

        char = source[index]
        if char in ("'", '"'):
            literal = _read_ordinary_string(source, index)
            end = index + len(literal)
            _blank_source_span(code_only, index, end)
            _blank_source_span(strings_masked, index, end)
            index = end
            continue

        if source.startswith("//", index):
            end = index + 2
            while end < len(source) and source[end] not in "\r\n":
                end += 1
            _blank_source_span(comments_stripped, index, end)
            _blank_source_span(code_only, index, end)
            index = end
            continue

        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            end = len(source) if comment_end == -1 else comment_end + 2
            _blank_source_span(comments_stripped, index, end)
            _blank_source_span(code_only, index, end)
            index = end
            continue

        index += 1

    return (
        "".join(comments_stripped),
        "".join(code_only),
        "".join(strings_masked),
    )


def _significant_source_lines(source: str) -> tuple[_SourceLine, ...]:
    lines: list[_SourceLine] = []
    comments_stripped, code_only, _strings_masked = _source_lexical_views(source)
    for line_number, (clean_line, code_line) in enumerate(
        zip(comments_stripped.splitlines(), code_only.splitlines(), strict=True),
        start=1,
    ):
        if not code_line.strip():
            continue
        if code_line.lstrip().startswith("#"):
            continue
        column = len(code_line) - len(code_line.lstrip()) + 1
        lines.append(
            _SourceLine(line=line_number, column=column, text=clean_line.strip())
        )
    return tuple(lines)


def _source_comments(source: str) -> tuple[_SourceLine, ...]:
    comments: list[_SourceLine] = []
    _comments_stripped, _code_only, source = _source_lexical_views(source)
    in_block_comment = False
    for line_number, line in enumerate(source.splitlines(), start=1):
        index = 0
        while index < len(line):
            if in_block_comment:
                end = line.find("*/", index)
                comment_text = line[index:] if end == -1 else line[index:end]
                if comment_text.strip():
                    comments.append(_SourceLine(line_number, index + 1, comment_text.strip(" *")))
                if end == -1:
                    break
                in_block_comment = False
                index = end + 2
                continue
            line_comment = line.find("//", index)
            block_comment = line.find("/*", index)
            if line_comment == -1 and block_comment == -1:
                break
            if line_comment != -1 and (block_comment == -1 or line_comment < block_comment):
                comment_text = line[line_comment + 2:].strip()
                if comment_text:
                    comments.append(_SourceLine(line_number, line_comment + 1, comment_text))
                break
            if block_comment != -1:
                end = line.find("*/", block_comment + 2)
                comment_text = line[block_comment + 2:] if end == -1 else line[block_comment + 2:end]
                if comment_text.strip():
                    comments.append(_SourceLine(line_number, block_comment + 1, comment_text.strip(" *")))
                in_block_comment = end == -1
                if end == -1:
                    break
                index = end + 2
    return tuple(comments)


def _declared_identifier_locations(source: str) -> tuple[tuple[str, int, int], ...]:
    locations: list[tuple[str, int, int]] = []
    _comments_stripped, source, _strings_masked = _source_lexical_views(source)
    for line_number, line in enumerate(source.splitlines(), start=1):
        for match in _DECLARATION_RE.finditer(line):
            for offset, declaration in _top_level_comma_segments(match.group(1)):
                stripped = declaration.lstrip()
                identifier_match = _IDENTIFIER_RE.match(stripped)
                if identifier_match is None:
                    continue
                leading_whitespace = len(declaration) - len(stripped)
                locations.append(
                    (
                        identifier_match.group(0),
                        line_number,
                        match.start(1) + offset + leading_whitespace + 1,
                    )
                )
        for match in _FUNCTION_RE.finditer(line):
            function_name = match.group(1)
            if function_name:
                locations.append((function_name, line_number, match.start(1) + 1))
            params_start = match.start(2)
            for offset, parameter in _top_level_comma_segments(match.group(2)):
                stripped = parameter.lstrip()
                identifier_match = _IDENTIFIER_RE.match(stripped)
                if identifier_match is None:
                    continue
                leading_whitespace = len(parameter) - len(stripped)
                locations.append(
                    (
                        identifier_match.group(0),
                        line_number,
                        params_start + offset + leading_whitespace + 1,
                    )
                )
    return tuple(locations)


def _top_level_comma_segments(text: str) -> tuple[tuple[int, str], ...]:
    """Return comma-delimited declarators without splitting nested expressions."""
    segments: list[tuple[int, str]] = []
    segment_start = 0
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            segments.append((segment_start, text[segment_start:index]))
            segment_start = index + 1
    segments.append((segment_start, text[segment_start:]))
    return tuple(segments)


def _identifier_locations(source: str) -> tuple[tuple[str, int, int], ...]:
    locations: list[tuple[str, int, int]] = []
    _comments_stripped, source, _strings_masked = _source_lexical_views(source)
    for line_number, line in enumerate(source.splitlines(), start=1):
        for match in _IDENTIFIER_RE.finditer(line):
            locations.append((match.group(0), line_number, match.start() + 1))
    return tuple(locations)


def _case_collision_suggestion(name: str, names: list[str]) -> str:
    suffix = names.index(name) + 1
    return f"{_sanitize_gdscript_identifier(name)}_{suffix}"
