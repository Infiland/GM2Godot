import os
import threading
from abc import ABC, abstractmethod

from src.localization import get_localized


class BaseConverter(ABC):
    """Base class for all GM2Godot converters."""

    def __init__(self, gm_project_path, godot_project_path,
                 log_callback=print, progress_callback=None,
                 conversion_running=None,
                 update_log_callback=None, compact_logging=False,
                 max_workers=None):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running = conversion_running or (lambda: True)
        self.update_log_callback = update_log_callback or log_callback
        self.compact_logging = compact_logging
        self.max_workers = max_workers or os.cpu_count()
        self._lock = threading.Lock()

    def _safe_log(self, message):
        """Thread-safe wrapper for log_callback. Use in multi-threaded converters."""
        with self._lock:
            self.log_callback(message)

    def _safe_update_log(self, message):
        """Thread-safe wrapper for update_log_callback. Use in multi-threaded converters."""
        with self._lock:
            self.update_log_callback(message)

    def _safe_progress(self, value):
        """Thread-safe wrapper for progress_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.progress_callback:
                self.progress_callback(value)

    def _log_progress(self, item_name, current, total):
        """Log compact progress. First item appends a line; subsequent items update it in place."""
        msg = get_localized("Console_Compact_Progress").format(
            name=item_name, current=current, total=total)
        if current == 1:
            self.log_callback(msg)
        else:
            self.update_log_callback(msg)

    def _safe_log_progress(self, item_name, current, total):
        """Thread-safe version of _log_progress."""
        with self._lock:
            self._log_progress(item_name, current, total)

    @abstractmethod
    def convert_all(self):
        """Run the full conversion for this converter type."""
        pass
