from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from src.conversion.type_defs import JsonDict


ConversionTerminalState: TypeAlias = Literal[
    "success",
    "partial",
    "failed",
    "cancelled",
]
ResourceTerminalState: TypeAlias = Literal["completed", "skipped", "failed"]
_TrackedResourceState: TypeAlias = Literal[
    "requested",
    "started",
    "completed",
    "skipped",
    "failed",
]


@dataclass(frozen=True)
class ConversionCounts:
    """Mutually exclusive terminal counts for requested conversion work."""

    requested: int = 0
    executed: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        values = (
            self.requested,
            self.executed,
            self.completed,
            self.skipped,
            self.failed,
        )
        if any(type(value) is not int for value in values):
            raise TypeError("Conversion counts must be integers.")
        if any(value < 0 for value in values):
            raise ValueError("Conversion counts cannot be negative.")
        if self.requested != self.completed + self.skipped + self.failed:
            raise ValueError(
                "Requested conversion work must equal completed + skipped + failed."
            )
        if self.executed > self.requested:
            raise ValueError("Executed conversion work cannot exceed requested work.")
        if self.completed + self.failed > self.executed:
            raise ValueError(
                "Completed and failed conversion work must have been executed."
            )

    def __add__(self, other: ConversionCounts) -> ConversionCounts:
        return ConversionCounts(
            requested=self.requested + other.requested,
            executed=self.executed + other.executed,
            completed=self.completed + other.completed,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
        )

    def to_dict(self) -> JsonDict:
        return {
            "requested": self.requested,
            "executed": self.executed,
            "completed": self.completed,
            "skipped": self.skipped,
            "failed": self.failed,
        }


@dataclass(frozen=True)
class ConversionStepResult:
    """Completeness reported by one normally returning converter step."""

    resources: ConversionCounts = field(default_factory=ConversionCounts)
    cancelled: bool = False


@dataclass(frozen=True)
class ConversionOutcome:
    """Machine-readable terminal result for one conversion invocation."""

    state: ConversionTerminalState
    converters: ConversionCounts = field(default_factory=ConversionCounts)
    resources: ConversionCounts = field(default_factory=ConversionCounts)
    failed_step: str | None = None
    failure_phase: str | None = None

    def __post_init__(self) -> None:
        if self.state not in ("success", "partial", "failed", "cancelled"):
            raise ValueError(
                "Conversion outcome state must be 'success', 'partial', "
                "'failed', or 'cancelled'."
            )
        if self.state == "partial" and not any(
            (
                self.converters.skipped,
                self.converters.failed,
                self.resources.skipped,
                self.resources.failed,
            )
        ):
            raise ValueError(
                "Partial conversion outcomes require skipped or failed work."
            )
        if self.state != "success":
            return
        if (
            self.converters.completed != self.converters.requested
            or self.resources.completed != self.resources.requested
        ):
            raise ValueError(
                "Successful conversion outcomes require every requested converter "
                "and resource to be completed."
            )
        if self.failed_step is not None or self.failure_phase is not None:
            raise ValueError(
                "Successful conversion outcomes cannot include failure context."
            )

    def to_dict(self) -> JsonDict:
        return {
            "state": self.state,
            "converters": self.converters.to_dict(),
            "resources": self.resources.to_dict(),
            "failed_step": self.failed_step,
            "failure_phase": self.failure_phase,
        }

    def summary_line(self) -> str:
        return (
            f"GM2Godot conversion outcome: {self.state}; "
            f"converters[{_render_counts(self.converters)}]; "
            f"resources[{_render_counts(self.resources)}]"
        )


class ResourceOutcomeTracker:
    """Thread-safe lifecycle tracker for logical resources in one converter."""

    def __init__(self) -> None:
        self._states: dict[str, _TrackedResourceState] = {}
        self._executed: set[str] = set()
        self._lock = threading.RLock()

    def request(self, key: str) -> None:
        normalized = self._key(key)
        with self._lock:
            self._states.setdefault(normalized, "requested")

    def start(self, key: str) -> None:
        normalized = self._key(key)
        with self._lock:
            state = self._required_state(normalized)
            if state == "requested":
                self._states[normalized] = "started"
                self._executed.add(normalized)
                return
            if state == "started":
                return
            self._invalid_transition(normalized, state, "started")

    def complete(self, key: str) -> None:
        self._finish(key, "completed", require_started=True)

    def skip(self, key: str) -> None:
        self._finish(key, "skipped", require_started=False)

    def fail(self, key: str) -> None:
        normalized = self._key(key)
        with self._lock:
            state = self._required_state(normalized)
            if state == "failed":
                return
            if state in {"requested", "started"}:
                self._states[normalized] = "failed"
                self._executed.add(normalized)
                return
            self._invalid_transition(normalized, state, "failed")

    def counts(
        self,
        *,
        finalize_unfinished_as: Literal["skipped", "failed"] | None = None,
    ) -> ConversionCounts:
        if finalize_unfinished_as not in {None, "skipped", "failed"}:
            raise ValueError(
                "Unfinished resources can only be finalized as 'skipped' or 'failed'."
            )

        with self._lock:
            unfinished = tuple(
                key
                for key, state in self._states.items()
                if state in {"requested", "started"}
            )
            if unfinished and finalize_unfinished_as is None:
                raise ValueError(
                    "Resource outcome counts require every requested resource to be terminal."
                )
            if finalize_unfinished_as is not None:
                for key in unfinished:
                    current = self._states[key]
                    terminal_state: ResourceTerminalState = (
                        "skipped"
                        if finalize_unfinished_as == "failed"
                        and current == "requested"
                        else finalize_unfinished_as
                    )
                    self._states[key] = terminal_state

            return ConversionCounts(
                requested=len(self._states),
                executed=len(self._executed),
                completed=self._terminal_count("completed"),
                skipped=self._terminal_count("skipped"),
                failed=self._terminal_count("failed"),
            )

    def _finish(
        self,
        key: str,
        terminal_state: Literal["completed", "skipped"],
        *,
        require_started: bool,
    ) -> None:
        normalized = self._key(key)
        with self._lock:
            state = self._required_state(normalized)
            if state == terminal_state:
                return
            allowed = {"started"} if require_started else {"requested", "started"}
            if state in allowed:
                self._states[normalized] = terminal_state
                return
            self._invalid_transition(normalized, state, terminal_state)

    def _required_state(self, key: str) -> _TrackedResourceState:
        try:
            return self._states[key]
        except KeyError as exc:
            raise ValueError(f"Resource {key!r} was not requested.") from exc

    def _terminal_count(self, state: ResourceTerminalState) -> int:
        return sum(1 for value in self._states.values() if value == state)

    @staticmethod
    def _key(key: str) -> str:
        if type(key) is not str:
            raise TypeError("Resource outcome keys must be strings.")
        if not key:
            raise ValueError("Resource outcome keys cannot be empty.")
        return key

    @staticmethod
    def _invalid_transition(
        key: str,
        current: _TrackedResourceState,
        requested: _TrackedResourceState,
    ) -> None:
        raise ValueError(
            f"Resource {key!r} cannot transition from {current!r} to {requested!r}."
        )


def _render_counts(counts: ConversionCounts) -> str:
    return (
        f"requested={counts.requested}, executed={counts.executed}, "
        f"completed={counts.completed}, skipped={counts.skipped}, "
        f"failed={counts.failed}"
    )
