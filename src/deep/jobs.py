"""Client job identity survives application restarts and extension upgrades."""
from __future__ import annotations

import json
import uuid
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.deep.install import ExtensionManager
from src.deep.settings import DeepSettings, data_directory


@dataclass
class DeepJob:
    root: Path
    source: str
    baseline: str
    installation: Path
    settings: DeepSettings
    phase: str = "research"
    elapsed_seconds: float = 0
    _save_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def create(cls, source: str, baseline: str, settings: DeepSettings, manager: ExtensionManager | None = None) -> DeepJob:
        manager = manager or ExtensionManager()
        job = cls(manager.root / "jobs" / str(uuid.uuid4()), str(Path(source).resolve()), str(Path(baseline).resolve()), manager.installation(), settings)
        job.save()
        return job

    @classmethod
    def load(cls, root: Path) -> DeepJob:
        raw: dict[str, Any] = json.loads((root / "client.json").read_text())
        return cls(root, raw["source"], raw["baseline"], Path(raw["installation"]), DeepSettings(**raw["settings"]), raw["phase"], float(raw.get("elapsed_seconds", 0)))

    def save(self) -> None:
        with self._save_lock:
            self._save()

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        raw = {"source": self.source, "baseline": self.baseline, "installation": str(self.installation), "settings": self.settings.to_dict(), "phase": self.phase, "elapsed_seconds": self.elapsed_seconds}
        temporary = self.root / "client.tmp"
        temporary.write_text(json.dumps(raw, indent=2))
        temporary.replace(self.root / "client.json")

    def params(self) -> dict[str, Any]:
        return {"jobRoot": str(self.root), "sourcePath": self.source, "baselinePath": self.baseline, "hostSnapshotPath": str(self.root / "host-snapshot.json"), "settings": self.settings.to_dict()}


def pending_jobs(root: Path | None = None) -> list[DeepJob]:
    directory = (root or data_directory()) / "jobs"
    result: list[DeepJob] = []
    for path in directory.glob("*/client.json"):
        try:
            job = DeepJob.load(path.parent)
            if job.phase not in {"complete", "cancelled"}:
                result.append(job)
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return result
