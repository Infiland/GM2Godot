from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from src.conversion.conversion_plan import CONVERSION_STEPS
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.type_defs import BoolSetting, ConversionRunning, LogCallback, ProgressCallback


_CONVERSION_STEP_KEYS = frozenset(step.key for step in CONVERSION_STEPS)


class RunningFlag(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class ConversionContext:
    """Typed shared state for a single conversion run."""

    gm_project_path: str
    godot_project_path: str
    target_platform: str
    log_callback: LogCallback
    progress_callback: ProgressCallback
    status_callback: LogCallback
    conversion_running: ConversionRunning
    update_log_callback: LogCallback
    compact_logging: bool
    max_workers: int | None
    diagnostics: DiagnosticCollector
    enabled_converters: tuple[str, ...]
    group_sounds_by_audio_group: bool = False

    def is_running(self) -> bool:
        return self.conversion_running()


def enabled_converter_keys(settings: Mapping[str, BoolSetting]) -> tuple[str, ...]:
    """Return enabled conversion step keys, excluding non-step UI settings."""
    return tuple(
        sorted(
            key
            for key, setting in settings.items()
            if key in _CONVERSION_STEP_KEYS and setting.get()
        )
    )


def sound_group_folders_enabled(settings: Mapping[str, BoolSetting]) -> bool:
    sound_group_setting = settings.get("sound_group_folders")
    return bool(sound_group_setting is not None and sound_group_setting.get())
