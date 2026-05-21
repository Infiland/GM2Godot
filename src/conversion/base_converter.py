from __future__ import annotations

import json
import os
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, cast

from src.localization import get_localized
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


class BaseConverter(ABC):
    """Base class for all GM2Godot converters."""

    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                 log_callback: LogCallback = print, progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        self.gm_project_path = os.fspath(gm_project_path)
        self.godot_project_path = os.fspath(godot_project_path)
        self.log_callback: LogCallback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running: ConversionRunning = conversion_running or (lambda: True)
        self.update_log_callback: LogCallback = update_log_callback or log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers or os.cpu_count() or 1
        self.diagnostics = diagnostics
        self._lock = threading.Lock()

    def _safe_log(self, message: str) -> None:
        """Thread-safe wrapper for log_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add_from_log_message(message)
            self.log_callback(message)

    def _safe_update_log(self, message: str) -> None:
        """Thread-safe wrapper for update_log_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.diagnostics is not None:
                self.diagnostics.add_from_log_message(message)
            self.update_log_callback(message)

    def _safe_progress(self, value: int | float) -> None:
        """Thread-safe wrapper for progress_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.progress_callback:
                self.progress_callback(value)

    def _log_progress(self, item_name: str, current: int, total: int) -> None:
        """Log compact progress. First item appends a line; subsequent items update it in place."""
        msg = get_localized("Console_Compact_Progress").format(
            name=item_name, current=current, total=total)
        if current == 1:
            self.log_callback(msg)
        else:
            self.update_log_callback(msg)

    def _safe_log_progress(self, item_name: str, current: int, total: int) -> None:
        """Thread-safe version of _log_progress."""
        with self._lock:
            self._log_progress(item_name, current, total)

    def _read_yy_file(self, yy_path: StrPath) -> JsonDict | None:
        """Read and parse a GameMaker .yy file, cleaning trailing commas."""
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)
            return cast(JsonDict, data) if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _get_subfolder_from_yy(self, yy_path: StrPath) -> str:
        """Extract the IDE subfolder path from a resource's .yy file.

        Reads parent.path (e.g. "folders/Objects/Game/Abilities.yy"),
        strips "folders/" prefix, ".yy" suffix, and the first path component
        (resource type), returning the remaining subfolder (e.g. "Game/Abilities").

        Returns "" for root-level resources or on any parse failure.
        """
        data = self._read_yy_file(yy_path)
        if data is None:
            return ""
        try:
            raw_parent = data.get('parent')
            if not isinstance(raw_parent, dict):
                return ""
            parent = cast(JsonDict, raw_parent)
            parent_path = parent.get('path')
            if not isinstance(parent_path, str):
                return ""
            if parent_path.startswith('folders/'):
                parent_path = parent_path[len('folders/'):]
            if parent_path.endswith('.yy'):
                parent_path = parent_path[:-len('.yy')]
            parts = parent_path.split('/')
            if len(parts) <= 1:
                return ""
            return '/'.join(parts[1:])
        except (KeyError, TypeError, AttributeError):
            return ""

    @abstractmethod
    def convert_all(self) -> Any:
        """Run the full conversion for this converter type."""
        pass
