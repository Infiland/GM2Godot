import threading
from typing import Protocol, cast

from PySide6.QtCore import QObject, Signal

from src.conversion.converter import Converter
from src.gui.setting_value import SettingValue


class _ConverterProtocol(Protocol):
    def convert(
        self,
        gm_path: str,
        gm_platform: str,
        godot_path: str,
        settings: dict[str, SettingValue],
    ) -> None:
        ...


class ConversionWorker(QObject):
    log_message = Signal(str)
    update_log_message = Signal(str)
    progress_updated = Signal(int)
    status_updated = Signal(str)
    conversion_finished = Signal(bool, str)

    def __init__(self, gm_path: str, gm_platform: str, godot_path: str,
                 conversion_settings: dict[str, SettingValue],
                 compact_logging: bool, conversion_running: threading.Event,
                 max_workers: int | None = None) -> None:
        super().__init__()
        self._gm_path = gm_path
        self._gm_platform = gm_platform
        self._godot_path = godot_path
        self._conversion_settings = conversion_settings
        self._compact_logging = compact_logging
        self._conversion_running = conversion_running
        self._max_workers = max_workers

    def run(self) -> None:
        try:
            converter = cast(
                _ConverterProtocol,
                Converter(
                    self.log_message.emit,
                    self.progress_updated.emit,
                    self.status_updated.emit,
                    self._conversion_running,
                    update_log_callback=self.update_log_message.emit,
                    compact_logging=self._compact_logging,
                    max_workers=self._max_workers,
                ),
            )
            converter.convert(
                self._gm_path,
                self._gm_platform,
                self._godot_path,
                self._conversion_settings,
            )
        except Exception as error:
            error_message = str(error) or type(error).__name__
            self.conversion_finished.emit(False, error_message)
        else:
            self.conversion_finished.emit(True, "")
