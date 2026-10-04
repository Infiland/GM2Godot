"""Live cancellation and SIGINT ownership for the CLI conversion session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from threading import Event
from types import FrameType
from typing import Protocol, TypeAlias

from src.conversion.conversion_outcome import ConversionOutcome

# An existing Python signal handler may return any value. The session restores
# the callable unchanged and never invokes or adapts its return value.
SignalHandler: TypeAlias = Callable[[int, FrameType | None], object] | int | None


class TerminalSummaryValues(Protocol):
    @property
    def terminal_summary_phase(self) -> str: ...


class SignalOperations(Protocol):
    @property
    def sigint(self) -> int: ...

    @property
    def get_signal_handler(self) -> Callable[[int], SignalHandler]: ...

    @property
    def set_signal_handler(self) -> Callable[[int, SignalHandler], SignalHandler]: ...


class ConversionSession:
    def __init__(
        self,
        running: Event,
        previous_sigint: SignalHandler,
        handler_installed: bool,
        terminal_values: TerminalSummaryValues,
        operations: SignalOperations,
        terminal_interruption: type[Exception],
    ) -> None:
        self.running = running
        self.previous_sigint = previous_sigint
        self.handler_installed = handler_installed
        self.sigint_handler_restored = False
        self.sigint_received = False
        self.managed_generation_decided = False
        self._terminal_values = terminal_values
        self._operations = operations
        self._terminal_interruption = terminal_interruption

    def install_sigint_handler(self) -> None:
        if self.handler_installed:
            self._operations.set_signal_handler(
                self._operations.sigint, self.request_cancellation
            )

    def request_cancellation(self, _signum: int, _frame: FrameType | None) -> None:
        if self.managed_generation_decided or self._terminal_values.terminal_summary_phase in {
            "committing",
            "committed",
        }:
            # Once the managed generation decision starts, cancellation cannot
            # imply rollback. The buffered line also remains single-publication.
            return
        if self.sigint_received:
            raise KeyboardInterrupt
        self.sigint_received = True
        self.running.clear()
        if self._terminal_values.terminal_summary_phase == "preparing":
            raise self._terminal_interruption

    def restore_sigint_handler(self) -> None:
        if not self.handler_installed or self.sigint_handler_restored:
            return
        try:
            self._operations.set_signal_handler(
                self._operations.sigint, self.previous_sigint
            )
        except KeyboardInterrupt:
            self.sigint_handler_restored = (
                self._operations.get_signal_handler(self._operations.sigint)
                == self.previous_sigint
            )
            if self._terminal_values.terminal_summary_phase != "committed":
                raise
        else:
            self.sigint_handler_restored = True

    def finally_restore_sigint_handler(self) -> None:
        if self.handler_installed and not self.sigint_handler_restored:
            try:
                self._operations.set_signal_handler(
                    self._operations.sigint, self.previous_sigint
                )
            except KeyboardInterrupt:
                if self._terminal_values.terminal_summary_phase != "committed":
                    raise

    def observe_cancellation(self, current: ConversionOutcome) -> ConversionOutcome:
        if (
            self.sigint_received
            and not self.managed_generation_decided
            and current.state != "cancelled"
        ):
            current = replace(current, state="cancelled")
        return current
