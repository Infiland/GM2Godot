import threading
from abc import ABC, abstractmethod


class BaseConverter(ABC):
    """Base class for all GM2Godot converters."""

    def __init__(self, gm_project_path, godot_project_path,
                 log_callback=print, progress_callback=None,
                 conversion_running=None):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running = conversion_running or (lambda: True)
        self._lock = threading.Lock()

    def _safe_log(self, message):
        """Thread-safe wrapper for log_callback. Use in multi-threaded converters."""
        with self._lock:
            self.log_callback(message)

    def _safe_progress(self, value):
        """Thread-safe wrapper for progress_callback. Use in multi-threaded converters."""
        with self._lock:
            if self.progress_callback:
                self.progress_callback(value)

    @abstractmethod
    def convert_all(self):
        """Run the full conversion for this converter type."""
        pass
