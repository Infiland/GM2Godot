"""Warnings about code that runs after a pending instance_change.

The converted game changes an instance's object once the event that called
instance_change returns, so the rest of that event runs on the old object
(see the runtime's 76_instance_change.gd). Object events and instance
creation code report where that code reads the instance.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_transpiler import analyze_gml_instance_change_reads

_WORKAROUND = (
    "Move the code that reads the instance after instance_change into the new object's "
    "Create event, or make instance_change the last thing the event does."
)


def record_instance_change_reads(
    diagnostics: DiagnosticCollector,
    source: str,
    *,
    known_names: Iterable[str],
    source_path: str | None,
    resource: str,
    resource_type: str,
    event: str,
) -> None:
    for finding in analyze_gml_instance_change_reads(source, known_names=known_names):
        diagnostics.add(
            finding.severity,
            finding.code,
            finding.message,
            source_path=source_path,
            line=finding.line,
            column=finding.column,
            resource=resource,
            resource_type=resource_type,
            event=event,
            api="instance_change",
            manifest_entry="instance_change",
            workaround=_WORKAROUND,
        )
