from PySide6.QtCore import QObject, Signal

from src.conversion.converter import Converter


class ConversionWorker(QObject):
    log_message = Signal(str)
    update_log_message = Signal(str)
    progress_updated = Signal(int)
    status_updated = Signal(str)
    conversion_finished = Signal()

    def __init__(self, gm_path, gm_platform, godot_path, conversion_settings,
                 compact_logging, conversion_running, max_workers=None):
        super().__init__()
        self._gm_path = gm_path
        self._gm_platform = gm_platform
        self._godot_path = godot_path
        self._conversion_settings = conversion_settings
        self._compact_logging = compact_logging
        self._conversion_running = conversion_running
        self._max_workers = max_workers

    def run(self):
        try:
            converter = Converter(
                self.log_message.emit,
                self.progress_updated.emit,
                self.status_updated.emit,
                self._conversion_running,
                update_log_callback=self.update_log_message.emit,
                compact_logging=self._compact_logging,
                max_workers=self._max_workers,
            )
            converter.convert(
                self._gm_path,
                self._gm_platform,
                self._godot_path,
                self._conversion_settings,
            )
        finally:
            self.conversion_finished.emit()
