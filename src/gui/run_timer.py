"""Monotonic active-run timing across baseline, research, review and resume."""
from __future__ import annotations

import time
from collections.abc import Callable


class RunTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._elapsed = 0.0
        self._started: float | None = None

    @property
    def elapsed(self) -> float:
        return self._elapsed + (max(0, self._clock() - self._started) if self._started is not None else 0)

    def start(self, elapsed: float = 0) -> None:
        self._elapsed = max(0, elapsed)
        self._started = self._clock()

    def stop(self) -> float:
        self._elapsed = self.elapsed
        self._started = None
        return self._elapsed
