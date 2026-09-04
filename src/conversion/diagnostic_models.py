"""Immutable diagnostic records shared by parsers and presentation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

DiagnosticSeverity: TypeAlias = Literal["info", "warning", "error"]
ProjectManifestSeverity: TypeAlias = DiagnosticSeverity
ResourceModelSeverity: TypeAlias = DiagnosticSeverity


@dataclass(frozen=True)
class ConversionDiagnostic:
    severity: DiagnosticSeverity
    code: str
    message: str
    source_path: str | None = None
    line: int | None = None
    column: int | None = None
    resource: str | None = None
    resource_type: str | None = None
    event: str | None = None
    api: str | None = None
    manifest_entry: str | None = None
    issue_number: int | None = None
    workaround: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source_path": self.source_path,
            "line": self.line,
            "column": self.column,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "event": self.event,
            "api": self.api,
            "manifest_entry": self.manifest_entry,
            "issue_number": self.issue_number,
            "workaround": self.workaround,
        }


@dataclass(frozen=True)
class ProjectSourceLocation:
    path: str
    line: int
    field_path: str = ""


@dataclass(frozen=True)
class ProjectManifestDiagnostic:
    severity: ProjectManifestSeverity
    code: str
    message: str
    source: ProjectSourceLocation | None = None
    resource: str | None = None
    resource_type: str | None = None
    resource_kind: str | None = None


@dataclass(frozen=True)
class ResourceModelDiagnostic:
    severity: ResourceModelSeverity
    code: str
    message: str
    source_path: str = ""
    resource_name: str = ""
    resource_kind: str = ""
