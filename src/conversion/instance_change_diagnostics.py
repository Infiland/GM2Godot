"""Warnings about code that runs after a pending instance_change.

Where the converter cannot run the rest of the event after the change (an
instance_change inside a loop, a with block, a switch or try statement, a
script function or instance creation code, or in an event the runtime does not
call by itself), the converted game changes the instance's object once the
event that called instance_change returns, so the rest of that event runs on
the old object (see the runtime's 76_instance_change.gd). Object events and
instance creation code report where that code meets the instance.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_transpiler import analyze_gml_instance_change_reads

_WORKAROUND = (
    "Make instance_change a statement of the event itself (not inside a loop, with, switch or try "
    "statement or a script function), so that the rest of the event runs after the change; or move "
    "the code that meets the instance into the new object's Create event, or make instance_change "
    "the last thing the event does."
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
    continued_calls: Collection[int] = (),
) -> None:
    for finding in analyze_gml_instance_change_reads(
        source,
        known_names=known_names,
        continued_calls=continued_calls,
    ):
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
