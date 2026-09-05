"""One CLI conversion's cancellation and terminal-summary signal state."""
from __future__ import annotations

import signal
import threading
from types import FrameType
from typing import Literal


class ConversionSession:
    def __init__(self) -> None:
        self.running = threading.Event()
        self.running.set()
        self.previous_sigint = signal.getsignal(signal.SIGINT)
        self.handler_eligible = threading.current_thread() is threading.main_thread()
        self.sigint_handler_restored = False
        self.sigint_received = False
        self.managed_generation_decided = False
        self.terminal_summary_phase: Literal["idle", "preparing", "committing", "committed"] = "idle"

        class _TerminalSummaryInterrupted(Exception):
            pass

        self.terminal_summary_interrupted: type[Exception] = _TerminalSummaryInterrupted

    def install_sigint_handler(self) -> None:
        if self.handler_eligible:
            signal.signal(signal.SIGINT, self.request_cancellation)

    def request_cancellation(self, _signum: int, _frame: FrameType | None) -> None:
        if self.managed_generation_decided or self.terminal_summary_phase in {"committing", "committed"}:
            # Once the managed generation decision starts, cancellation cannot
            # imply rollback. The buffered line also remains single-publication.
            return
        if self.sigint_received:
            raise KeyboardInterrupt
        self.sigint_received = True
        self.running.clear()
        if self.terminal_summary_phase == "preparing":
            raise self.terminal_summary_interrupted

    def restore_sigint_handler(self) -> None:
        if not self.handler_eligible or self.sigint_handler_restored:
            return
        try:
            signal.signal(signal.SIGINT, self.previous_sigint)
        except KeyboardInterrupt:
            self.sigint_handler_restored = signal.getsignal(signal.SIGINT) == self.previous_sigint
            if self.terminal_summary_phase != "committed":
                raise
        else:
            self.sigint_handler_restored = True

    def restore_sigint_handler_fallback(self) -> None:
        if self.handler_eligible and not self.sigint_handler_restored:
            try:
                signal.signal(signal.SIGINT, self.previous_sigint)
            except KeyboardInterrupt:
                if self.terminal_summary_phase != "committed":
                    raise
