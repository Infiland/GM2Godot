"""Versioned user preferences shared by the GUI and command line."""
from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def data_directory() -> Path:
    system = platform.system()
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif system == "Darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return root / "GM2Godot" / "deep"


@dataclass
class DeepSettings:
    runtime: str = "opencode"
    provider: str = "opencode"
    model: str = "automatic-free"
    roleOverrides: dict[str, dict[str, str]] = field(default_factory=lambda: {})
    analysisWorkers: int = 4
    freeProviderConcurrency: int = 1
    freeOnly: bool = True
    allowRemoteSourceUpload: bool = False
    budgets: dict[str, float] = field(default_factory=lambda: {"maxTokens": 1000000, "maxCostUsd": 0, "maxSeconds": 3600})
    godotBinary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def validate(self) -> None:
        if self.runtime not in {"mock", "pi", "codex", "claude", "opencode"}:
            raise ValueError("Unsupported Deep runtime")
        if not 1 <= self.analysisWorkers <= 32:
            raise ValueError("Research workers must be between 1 and 32")
        if not 1 <= self.freeProviderConcurrency <= 32:
            raise ValueError("Free provider concurrency must be between 1 and 32")
        if self.freeOnly and any(override.get("provider", "opencode") != "opencode" or override.get("runtime", "opencode") != "opencode" for override in self.roleOverrides.values()):
            raise ValueError("Free-only roles must use OpenCode Zen")
        if self.freeOnly and (self.runtime != "opencode" or self.provider != "opencode"):
            raise ValueError("Automatic free selection requires OpenCode Zen")
        if any(value < 0 for value in self.budgets.values()):
            raise ValueError("Budgets cannot be negative")
        if not self.model.strip():
            raise ValueError("Select a model")


def load_settings(root: Path | None = None) -> DeepSettings:
    path = (root or data_directory()) / "settings.json"
    if not path.exists():
        return DeepSettings()
    raw: dict[str, Any] = json.loads(path.read_text())
    settings = DeepSettings(**{key: value for key, value in raw.items() if key in DeepSettings.__dataclass_fields__})
    settings.validate()
    return settings


def save_settings(settings: DeepSettings, root: Path | None = None) -> None:
    directory = root or data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "settings.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings.to_dict(), indent=2) + "\n")
    temporary.replace(path)
