from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal, TypeAlias

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
class ConversionStepLedger:
    """Immutable, plan-ordered lifecycle ledger for converter steps."""

    requested: tuple[str, ...] = field(default_factory=tuple)
    executed: tuple[str, ...] = field(default_factory=tuple)
    completed: tuple[str, ...] = field(default_factory=tuple)
    failed: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        sequences = {
            "requested": self.requested,
            "executed": self.executed,
            "completed": self.completed,
            "failed": self.failed,
        }
        for label, names in sequences.items():
            if type(names) is not tuple:
                raise TypeError(f"Conversion step {label} names must be a tuple.")
            for name in names:
                self._validate_name(name)

        if len(set(self.requested)) != len(self.requested):
            raise ValueError("Requested conversion step names must be unique.")
        if len(set(self.executed)) != len(self.executed):
            raise ValueError("Executed conversion step names must be unique.")
        if self.executed != self.requested[: len(self.executed)]:
            raise ValueError(
                "Executed conversion steps must be a prefix of the requested plan."
            )

        for label, names in (
            ("Completed", self.completed),
            ("Failed", self.failed),
        ):
            if len(set(names)) != len(names):
                raise ValueError(f"{label} conversion step names must be unique.")
            name_set = set(names)
            if names != tuple(name for name in self.executed if name in name_set):
                raise ValueError(
                    f"{label} conversion steps must be a plan-ordered "
                    "subsequence of executed steps."
                )

        completed = set(self.completed)
        failed = set(self.failed)
        if completed & failed:
            raise ValueError("Completed and failed conversion steps must be disjoint.")
        if len(self.failed) > 1 or (
            self.failed and self.failed[0] != self.executed[-1]
        ):
            raise ValueError(
                "At most the final executed conversion step may fail."
            )

        unfinished = tuple(
            name
            for name in self.executed
            if name not in completed and name not in failed
        )
        if len(unfinished) > 1 or (
            unfinished and unfinished[0] != self.executed[-1]
        ):
            raise ValueError(
                "At most the final executed conversion step may remain active."
            )

    @classmethod
    def from_requested(cls, step_names: Iterable[str]) -> ConversionStepLedger:
        """Create an unstarted ledger from names in conversion-plan order."""
        if isinstance(step_names, (str, bytes)):
            raise TypeError("Requested conversion steps must be an iterable of names.")
        return cls(requested=tuple(step_names))

    @property
    def skipped(self) -> tuple[str, ...]:
        terminal = {*self.completed, *self.failed}
        return tuple(name for name in self.requested if name not in terminal)

    @property
    def active_step(self) -> str | None:
        if not self.executed:
            return None
        final_step = self.executed[-1]
        if final_step in self.completed or final_step in self.failed:
            return None
        return final_step

    @property
    def counts(self) -> ConversionCounts:
        return ConversionCounts(
            requested=len(self.requested),
            executed=len(self.executed),
            completed=len(self.completed),
            skipped=len(self.skipped),
            failed=len(self.failed),
        )

    def start(self, step_name: str) -> ConversionStepLedger:
        """Return a new ledger with the next requested step active."""
        self._validate_name(step_name)
        if self.active_step is not None:
            raise ValueError(
                f"Cannot start conversion step {step_name!r} while "
                f"{self.active_step!r} is active."
            )
        if len(self.executed) == len(self.requested):
            raise ValueError("All requested conversion steps have been executed.")
        expected = self.requested[len(self.executed)]
        if step_name != expected:
            raise ValueError(
                f"Expected conversion step {expected!r}, got {step_name!r}."
            )
        return replace(self, executed=(*self.executed, step_name))

    def complete(self, step_name: str) -> ConversionStepLedger:
        """Return a new ledger with its active step completed."""
        self._validate_active_transition(step_name, "complete")
        return replace(self, completed=(*self.completed, step_name))

    def fail(self, step_name: str) -> ConversionStepLedger:
        """Return a new ledger with its active step failed."""
        self._validate_active_transition(step_name, "fail")
        return replace(self, failed=(*self.failed, step_name))

    def to_dict(self) -> JsonDict:
        return {
            "requested": list(self.requested),
            "executed": list(self.executed),
            "completed": list(self.completed),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
        }

    def _validate_active_transition(
        self,
        step_name: str,
        transition: Literal["complete", "fail"],
    ) -> None:
        self._validate_name(step_name)
        if self.active_step != step_name:
            raise ValueError(
                f"Only the active conversion step can {transition}; "
                f"active step is {self.active_step!r}."
            )

    @staticmethod
    def _validate_name(step_name: object) -> None:
        if type(step_name) is not str:
            raise TypeError("Conversion step names must be strings.")
        if not step_name:
            raise ValueError("Conversion step names cannot be empty.")


@dataclass(frozen=True)
class ConversionOutcome:
    """Machine-readable terminal result for one conversion invocation."""

    state: ConversionTerminalState
    steps: ConversionStepLedger = field(default_factory=ConversionStepLedger)
    resources: ConversionCounts = field(default_factory=ConversionCounts)
    failed_step: str | None = None
    failure_phase: str | None = None

    @property
    def converters(self) -> ConversionCounts:
        """Compatibility aggregate derived from the named step ledger."""
        return self.steps.counts

    def __post_init__(self) -> None:
        if self.state not in ("success", "partial", "failed", "cancelled"):
            raise ValueError(
                "Conversion outcome state must be 'success', 'partial', "
                "'failed', or 'cancelled'."
            )
        if self.state == "partial":
            if self.steps.active_step is not None:
                raise ValueError(
                    "Partial conversion outcomes cannot include an active step."
                )
            if self.steps.completed != self.steps.requested:
                raise ValueError(
                    "Partial conversion outcomes require every requested "
                    "converter step to complete."
                )
            if not (self.resources.skipped or self.resources.failed):
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
            "steps": self.steps.to_dict(),
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
