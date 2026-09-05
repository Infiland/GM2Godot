"""CLI outcome fixtures and precise public-entry signal boundaries."""
from __future__ import annotations

import signal
import sys
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import FrameType
from typing import Literal, TypeAlias

from src import cli
from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome, ConversionStepLedger
from src.conversion.diagnostics import DiagnosticCollector

TraceCallback: TypeAlias = Callable[[FrameType, str, object], "TraceCallback | None"]
CLISignalBoundary: TypeAlias = Literal[
    "log-flush", "before-summary", "after-summary", "pre-summary-gap", "report-generation", "post-restore-return",
]


class OutcomeConverterStub:
    def __init__(
        self,
        outcome: ConversionOutcome,
        *,
        error: Exception | None = None,
        warning: bool = False,
        on_convert: Callable[[], None] | None = None,
    ) -> None:
        self.outcome = outcome
        self.error = error
        self.warning = warning
        self.on_convert = on_convert
        self.diagnostics = DiagnosticCollector()
        self.last_outcome: ConversionOutcome | None = None
        self.conversion_running: threading.Event | None = None
        self.attempt_publications: list[ConversionOutcome] = []

    def bind_factory(self, **kwargs: object) -> OutcomeConverterStub:
        running = kwargs.get("conversion_running")
        if not isinstance(running, threading.Event):
            raise AssertionError("OutcomeConverterStub requires the CLI conversion_running Event")
        self.conversion_running = running
        return self

    def convert(
        self,
        *_args: object,
        diagnostics: DiagnosticCollector | None = None,
        **_kwargs: object,
    ) -> ConversionOutcome:
        running = self.conversion_running
        if running is None:
            raise AssertionError("OutcomeConverterStub factory Event was not bound")
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticCollector()
        if self.warning:
            self.diagnostics.add("warning", "GM2GD-TEST-WARNING", "Synthetic conversion warning.")
        self.last_outcome = self.outcome
        self.diagnostics.set_outcome(self.outcome)
        if self.on_convert is not None:
            self.on_convert()
        if self.error is not None:
            raise self.error
        if not running.is_set():
            self.last_outcome = replace(self.outcome, state="cancelled", failed_step=None, failure_phase=None)
            self.diagnostics.set_outcome(self.last_outcome)
        return self.last_outcome

    def publish_conversion_attempt(self, attempt_outcome: ConversionOutcome) -> str:
        self.attempt_publications.append(attempt_outcome)
        self.last_outcome = attempt_outcome
        self.diagnostics.set_outcome(attempt_outcome)
        return ""


def success_outcome() -> ConversionOutcome:
    completed = ConversionCounts(
        requested=1,
        executed=1,
        completed=1,
    )
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").complete("scripts")
    return ConversionOutcome(
        state="success",
        steps=steps,
        resources=completed,
    )


def partial_outcome() -> ConversionOutcome:
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").complete("scripts")
    return ConversionOutcome(
        state="partial",
        steps=steps,
        resources=ConversionCounts(
            requested=2,
            executed=2,
            completed=1,
            skipped=1,
        ),
    )


def failed_outcome() -> ConversionOutcome:
    steps = ConversionStepLedger.from_requested(("scripts",))
    steps = steps.start("scripts").fail("scripts")
    return ConversionOutcome(
        state="failed",
        steps=steps,
        failed_step="scripts",
        failure_phase="converter",
    )


@contextmanager
def cli_sigint_at_boundary(boundary: CLISignalBoundary) -> Generator[list[str], None, None]:
    boundaries = {
        "log-flush": ("_print_conversion_logs", "call"),
        "before-summary": ("_print_conversion_summary", "call"),
        "after-summary": ("_print_conversion_summary", "return"),
        "pre-summary-gap": ("_run_convert", "line"),
        "report-generation": ("_write_external_conversion_reports", "call"),
        "post-restore-return": ("_run_convert", "line"),
    }
    owner_name, expected_event = boundaries[boundary]
    target_line: int | None = None
    if boundary == "pre-summary-gap":
        lines = Path(cli.__file__).read_text(encoding="utf-8").splitlines()
        matches = [
            index + 2
            for index, line in enumerate(lines)
            if line.strip() == 'session.terminal_summary_phase = "preparing"'
        ]
        if len(matches) != 1:
            raise AssertionError("CLI must retain one terminal-summary preparing boundary")
        target_line = matches[0]
    elif boundary == "post-restore-return":
        lines = Path(cli.__file__).read_text(encoding="utf-8").splitlines()
        matches = [index for index, line in enumerate(lines) if line.strip() == "session.restore_sigint_handler()"]
        if len(matches) != 1 or lines[matches[0] + 1].strip() != "return exit_code":
            raise AssertionError("CLI must retain one immediate post-restore committed return")
        target_line = matches[0] + 2
    reached: list[str] = []

    def trace(frame: FrameType, event: str, _argument: object) -> TraceCallback | None:
        if reached or frame.f_code.co_filename != cli.__file__ or frame.f_code.co_name != owner_name:
            return trace
        if event != expected_event or (target_line is not None and frame.f_lineno != target_line):
            return trace
        reached.append(boundary)
        sys.settrace(None)
        signal.raise_signal(signal.SIGINT)
        return None

    previous_trace = sys.gettrace()
    sys.settrace(trace)
    try:
        yield reached
    finally:
        sys.settrace(previous_trace)
