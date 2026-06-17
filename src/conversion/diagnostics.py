from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias

from src.conversion.type_defs import StrPath

DiagnosticSeverity: TypeAlias = Literal["info", "warning", "error"]

DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.json"
)
DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH = os.path.join(
    "gm2godot", "conversion_diagnostics.md"
)


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


class DiagnosticCollector:
    def __init__(self) -> None:
        self._diagnostics: list[ConversionDiagnostic] = []
        self._recorded_messages: set[str] = set()

    def add(
        self,
        severity: DiagnosticSeverity,
        code: str,
        message: str,
        *,
        source_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        event: str | None = None,
        api: str | None = None,
        manifest_entry: str | None = None,
        issue_number: int | None = None,
        workaround: str | None = None,
    ) -> ConversionDiagnostic:
        diagnostic = ConversionDiagnostic(
            severity=severity,
            code=code,
            message=message,
            source_path=source_path,
            line=line,
            column=column,
            resource=resource,
            resource_type=resource_type,
            event=event,
            api=api,
            manifest_entry=manifest_entry,
            issue_number=issue_number,
            workaround=workaround,
        )
        self._diagnostics.append(diagnostic)
        self._recorded_messages.add(message)
        return diagnostic

    def add_from_log_message(
        self, message: str, *, code: str = "GM2GD-WARNING"
    ) -> ConversionDiagnostic | None:
        if message in self._recorded_messages:
            return None
        stripped = message.strip()
        severity = _severity_from_log_message(stripped)
        if severity is None:
            return None
        return self.add(severity, code, stripped)

    def add_transpile_failure(
        self,
        message: str,
        *,
        source_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        resource: str | None = None,
        resource_type: str | None = None,
        event: str | None = None,
        workaround: str | None = None,
    ) -> ConversionDiagnostic:
        api_name = _extract_gml_api_name(message)
        issue_number = _extract_issue_number(message)
        return self.add(
            "warning",
            "GM2GD-GML-TRANSPILE",
            message,
            source_path=source_path,
            line=line,
            column=column,
            resource=resource,
            resource_type=resource_type,
            event=event,
            api=api_name,
            manifest_entry=api_name,
            issue_number=issue_number,
            workaround=workaround,
        )

    def wrap_log_callback(
        self, log_callback: Callable[[str], None]
    ) -> Callable[[str], None]:
        def _wrapped(message: str) -> None:
            self.add_from_log_message(message)
            log_callback(message)

        return _wrapped

    def diagnostics(self) -> tuple[ConversionDiagnostic, ...]:
        return tuple(self._diagnostics)

    def summary(self) -> dict[str, int]:
        counts = {"info": 0, "warning": 0, "error": 0}
        for diagnostic in self._diagnostics:
            counts[diagnostic.severity] += 1
        counts["total"] = len(self._diagnostics)
        return counts

    def to_json_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "diagnostics": [
                diagnostic.to_dict()
                for diagnostic in self._sorted_diagnostics()
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# GM2Godot Conversion Diagnostics",
            "",
            "| Severity | Code | Source | Resource | Event/API | Message |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        diagnostics = self._sorted_diagnostics()
        if not diagnostics:
            lines.append("| info | GM2GD-OK |  |  |  | No diagnostics recorded. |")
            return "\n".join(lines) + "\n"

        for diagnostic in diagnostics:
            source = diagnostic.source_path or ""
            resource_parts = [
                value
                for value in (diagnostic.resource_type, diagnostic.resource)
                if value
            ]
            event_api = diagnostic.event or diagnostic.api or ""
            message = _escape_markdown_table(diagnostic.message)
            lines.append(
                "| {severity} | {code} | {source} | {resource} | {event_api} | {message} |".format(
                    severity=diagnostic.severity,
                    code=diagnostic.code,
                    source=_escape_markdown_table(source),
                    resource=_escape_markdown_table("/".join(resource_parts)),
                    event_api=_escape_markdown_table(event_api),
                    message=message,
                )
            )
        return "\n".join(lines) + "\n"

    def write_reports(self, godot_project_path: StrPath) -> tuple[str, str]:
        json_path = os.path.join(
            os.fspath(godot_project_path), DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
        )
        markdown_path = os.path.join(
            os.fspath(godot_project_path), DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
        )
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as json_file:
            json_file.write(self.to_json())
        with open(markdown_path, "w", encoding="utf-8") as markdown_file:
            markdown_file.write(self.to_markdown())
        return json_path, markdown_path

    def _sorted_diagnostics(self) -> tuple[ConversionDiagnostic, ...]:
        return tuple(
            sorted(
                self._diagnostics,
                key=lambda item: (
                    item.severity,
                    item.code,
                    item.source_path or "",
                    item.resource_type or "",
                    item.resource or "",
                    item.event or "",
                    item.message,
                ),
            )
        )


def write_conversion_diagnostic_reports(
    godot_project_path: StrPath, diagnostics: DiagnosticCollector
) -> tuple[str, str]:
    return diagnostics.write_reports(godot_project_path)


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _severity_from_log_message(message: str) -> DiagnosticSeverity | None:
    normalized = message.lower()
    if normalized.startswith("info:"):
        return "info"
    if normalized.startswith("warning:"):
        return "warning"
    if normalized.startswith("error:"):
        return "error"
    return None


def _extract_gml_api_name(message: str) -> str | None:
    match = re.search(r"GML API '([^']+)'", message)
    if match is None:
        return None
    return match.group(1)


def _extract_issue_number(message: str) -> int | None:
    match = re.search(r"tracked by #(\d+)", message)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
