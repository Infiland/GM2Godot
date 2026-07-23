from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


SourceDiagnosticSeverity: TypeAlias = Literal["warning", "error"]


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

    def with_generated_line_offset(self, offset: int) -> GMLSourceMap:
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
    ) -> GMLSourceMap:
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


__all__ = [
    "GMLPreprocessResult",
    "GMLPreprocessorDiagnostic",
    "GMLSourceDiagnostic",
    "GMLSourceMap",
    "GMLSourceMapEntry",
    "GMLTranspileResult",
    "SourceDiagnosticSeverity",
]
