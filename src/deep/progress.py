"""Presentation state for durable Deep task and agent events; independent of Qt."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

DONE = {"completed", "accepted", "cached", "retained", "skipped", "done", "analyzed"}
ACTIVE = {"running", "implementing", "validating", "retrying"}
ATTENTION = {"blocked", "failed", "rate_limited", "paused"}


def task_phase(value: str) -> str:
    return "implementation" if value in {"implementation", "implement", "convert", "validation", "validate"} else "research"


@dataclass
class DeepProgress:
    tasks: dict[str, dict[str, Any]] = field(default_factory=lambda: {})
    agents: dict[str, dict[str, Any]] = field(default_factory=lambda: {})
    phase: str = "research"
    state: str = "running"
    message: str = "Preparing project inventory…"
    features: dict[str, bool] = field(default_factory=lambda: {})
    seq: int = 0

    def _task(self, raw: dict[str, Any], phase: str) -> None:
        identifier = str(raw.get("taskId", ""))
        if not identifier:
            return
        phase = task_phase(str(raw.get("phase", phase)))
        key = f"{phase}:{identifier}"
        previous = self.tasks.get(key, {})
        self.tasks[key] = {**previous, **raw, "taskId": identifier, "phase": phase,
                           "state": str(raw.get("state", previous.get("state", "pending"))).lower()}

    def apply(self, event: dict[str, Any]) -> bool:
        """Merge snapshots and partial updates without discarding queued/completed rows."""
        raw_result = event.get("result", {})
        if not isinstance(raw_result, dict):
            return False
        result = cast(dict[str, Any], raw_result)
        sequence = event.get("seq")
        if isinstance(sequence, int):
            if sequence <= self.seq:
                return False
            self.seq = sequence
        kind = event.get("type")
        if kind == "capabilities":
            self.features = dict(result.get("features", {}))
            return True
        raw_monitoring = result.get("monitoring", result)
        if isinstance(raw_monitoring, dict):
            monitoring = cast(dict[str, Any], raw_monitoring)
            raw_tasks = monitoring.get("tasks", [])
            raw_agents = monitoring.get("agents", [])
            for row in cast(list[Any], raw_tasks) if isinstance(raw_tasks, list) else []:
                if isinstance(row, dict):
                    self._task(cast(dict[str, Any], row), self.phase)
            for row in cast(list[Any], raw_agents) if isinstance(raw_agents, list) else []:
                if isinstance(row, dict):
                    self._agent(cast(dict[str, Any], row))
        phase = str(result.get("phase", ""))
        if phase in {"research", "analyze", "implementation", "implement", "convert", "validate", "plan", "report"}:
            self.phase = phase
        if result.get("taskId"):
            if phase == "agent":
                self._agent(result)
            else:
                self._task(result, self.phase)
        if result.get("message"):
            self.message = str(result["message"])
        if kind == "completed" or kind == "snapshot":
            self.state = str(result.get("state", self.state))
            error = result.get("error")
            if isinstance(error, dict):
                self.message = str(cast(dict[str, Any], error).get("message", "Progress saved. Choose a model or adjust limits to resume."))
        return True

    def _agent(self, raw: dict[str, Any]) -> None:
        identifier = str(raw.get("agentId") or f"{raw.get('role', 'agent')}:{raw.get('taskId', '')}:{raw.get('attempt', 1)}")
        previous = self.agents.get(identifier, {})
        self.agents[identifier] = {**previous, **raw, "agentId": identifier,
                                  "state": str(raw.get("state", previous.get("state", "pending"))).lower()}

    def finish(self, state: str, message: str) -> None:
        self.state, self.message = state, message
        for agent in self.agents.values():
            if agent.get("state") in ACTIVE:
                agent["state"] = "paused" if state in {"paused", "review"} else "stopped"
        for task in self.tasks.values():
            if task.get("state") in ACTIVE:
                task["state"] = "pending" if state == "paused" else "blocked"

    def counts(self, phase: str) -> tuple[int, int, int]:
        rows = [row for row in self.tasks.values() if row["phase"] == task_phase(phase)]
        return (sum(row["state"] in DONE for row in rows), len(rows), sum(row["state"] in ATTENTION for row in rows))

    def save(self, root: Path) -> None:
        payload = {"tasks": self.tasks, "agents": self.agents, "phase": self.phase,
                   "state": self.state, "message": self.message, "seq": self.seq, "features": self.features}
        temporary = root / "client-progress.tmp"
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(root / "client-progress.json")

    @classmethod
    def load(cls, root: Path) -> DeepProgress:
        try:
            raw = json.loads((root / "client-progress.json").read_text(encoding="utf-8"))
            return cls(**raw)
        except (OSError, ValueError, TypeError):
            return cls()
