import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol, cast

from PySide6.QtCore import QObject, Signal

from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import Converter
from src.conversion.diagnostics import DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
from src.deep.credentials import credential_environment
from src.deep.host_snapshot import write_host_snapshot
from src.deep.install import ExtensionManager, opencode_path
from src.deep.jobs import DeepJob
from src.deep.session import DeepSession
from src.gui.setting_value import SettingValue


@dataclass(frozen=True)
class ConversionWorkerResult:
    outcome: ConversionOutcome | None
    error_message: str | None
    diagnostic_report_path: str | None

    def __post_init__(self) -> None:
        if self.outcome is None and self.error_message is None:
            raise ValueError("A worker result requires an outcome or an error.")
        if self.error_message is not None and not self.error_message:
            raise ValueError("A worker error message cannot be empty.")
        if self.diagnostic_report_path is not None:
            if (
                self.error_message is not None
                or self.outcome is None
                or self.outcome.state != "partial"
            ):
                raise ValueError(
                    "Only a normal partial result can advertise a diagnostic report."
                )
            if not os.path.isabs(self.diagnostic_report_path):
                raise ValueError("A diagnostic report path must be absolute.")
        elif (
            self.error_message is None
            and self.outcome is not None
            and self.outcome.state == "partial"
        ):
            raise ValueError(
                "A normal partial result requires its diagnostic report path."
            )


class _ConverterProtocol(Protocol):
    last_outcome: ConversionOutcome | None

    def convert(
        self,
        gm_path: str,
        gm_platform: str,
        godot_path: str,
        settings: dict[str, SettingValue],
    ) -> ConversionOutcome: ...


def _exception_message(error: Exception) -> str:
    try:
        message = str(error)
    except Exception:
        return type(error).__name__
    return message or type(error).__name__


class ConversionWorker(QObject):
    log_message = Signal(str)
    update_log_message = Signal(str)
    progress_updated = Signal(float)
    status_updated = Signal(str)
    conversion_finished = Signal(object)

    def __init__(
        self,
        gm_path: str,
        gm_platform: str,
        godot_path: str,
        conversion_settings: dict[str, SettingValue],
        compact_logging: bool,
        conversion_running: threading.Event,
        max_workers: int | None = None,
    ) -> None:
        super().__init__()
        self._gm_path = gm_path
        self._gm_platform = gm_platform
        self._godot_path = godot_path
        self._diagnostic_report_path = os.path.join(
            os.path.abspath(godot_path),
            DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
        )
        self._conversion_settings = {key: SettingValue(value.get()) for key, value in conversion_settings.items()}
        self._compact_logging = compact_logging
        self._conversion_running = conversion_running
        self._max_workers = max_workers

    def run(self) -> None:
        converter: _ConverterProtocol | None = None
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
            raw_outcome = cast(
                object,
                converter.convert(
                    self._gm_path,
                    self._gm_platform,
                    self._godot_path,
                    self._conversion_settings,
                ),
            )
            if not isinstance(raw_outcome, ConversionOutcome):
                raise TypeError(
                    "Converter.convert() must return ConversionOutcome; "
                    f"got {type(raw_outcome).__name__}."
                )
            outcome = raw_outcome
        except Exception as error:
            error_message = _exception_message(error)
            candidate = converter.last_outcome if converter is not None else None
            result = ConversionWorkerResult(
                outcome=(candidate if isinstance(candidate, ConversionOutcome) else None),
                error_message=error_message,
                diagnostic_report_path=None,
            )
        else:
            result = ConversionWorkerResult(
                outcome=outcome,
                error_message=None,
                diagnostic_report_path=(
                    self._diagnostic_report_path
                    if outcome.state == "partial"
                    else None
                ),
            )
        self.conversion_finished.emit(result)

class DeepConversionWorker(QObject):
    log_message = Signal(str)
    event_received = Signal(object)
    finished = Signal(bool, str)

    def __init__(self, job: DeepJob, *, method: str = "research") -> None:
        super().__init__()
        self.job = job
        self.method = method
        self.session: DeepSession | None = None
        self.result: dict[str, Any] = {}
        self._pause_requested = threading.Event()

    def pause(self) -> None:
        if self._pause_requested.is_set():
            return
        self._pause_requested.set()
        if self.session:
            try:
                self.session.notify("pause", {"jobRoot": str(self.job.root)})
            except (OSError, RuntimeError):
                pass
        fallback = threading.Timer(10, self._finish_pause)
        fallback.daemon = True
        fallback.start()

    def _finish_pause(self) -> None:
        session = self.session
        if session is not None:
            session.close()

    def configure(self, workers: int, free_workers: int) -> None:
        if not 1 <= workers <= 32 or not 1 <= free_workers <= 32:
            raise ValueError("Worker limits must be between 1 and 32")
        if self.session is None or self._pause_requested.is_set():
            raise RuntimeError("Wait for Deep to start, or resume the paused job")
        self.session.notify("configure", {"jobRoot": str(self.job.root), "analysisWorkers": workers, "freeProviderConcurrency": free_workers})

    def run(self) -> None:
        success, message = False, "Progress saved."
        try:
            operation = "research" if self.method == "resume" and not (self.job.root / "host-job.json").is_file() else self.method
            if operation == "research":
                write_host_snapshot(self.job.source, str(self.job.root / "host-snapshot.json"))
            if self._pause_requested.is_set():
                self.job.phase = "paused"
                self.job.save()
                message = "Paused before research"
                return
            environment = {} if self.job.settings.runtime == "mock" else credential_environment(self.job.settings.provider)
            for override in self.job.settings.roleOverrides.values():
                if "provider" in override:
                    environment.update(credential_environment(override["provider"]))
            binary = opencode_path()
            if binary:
                environment["PATH"] = os.path.dirname(binary) + os.pathsep + os.environ.get("PATH", "")
            self.session = DeepSession(ExtensionManager().command(self.job.installation), self.job.root, self.event_received.emit, environment)
            capabilities = self.session.request("capabilities", {"settings": {"runtime": "mock"}}, timeout=30)
            self.event_received.emit({"type": "capabilities", "result": capabilities.get("result", {})})
            if operation != "research":
                status = self.session.request("status", {"jobRoot": str(self.job.root)}, timeout=30)
                self.event_received.emit({"type": "snapshot", "result": status.get("result", {})})
            if self._pause_requested.is_set():
                self.job.phase = "paused"
                self.job.save()
                message = "Paused before dispatch"
                return
            self.result = self.session.request(operation, self.job.params(), timeout=self.job.settings.budgets.get("maxSeconds", 3600) + 60)
            result = self.result.get("result", {})
            phase = str(result.get("state", "review" if operation == "research" else "complete"))
            self.job.phase = "paused" if self._pause_requested.is_set() else phase
            self.job.save()
            success, message = not bool(result.get("error")), json.dumps(result, indent=2)
        except Exception as error:
            message = _exception_message(error)
            self.job.phase = "paused"
            try:
                self.job.save()
            except OSError as save_error:
                message += f"\nUnable to save client checkpoint: {save_error}"
        finally:
            try:
                if self.session:
                    self.session.close()
            except Exception as close_error:
                success = False
                message += f"\nUnable to finish closing Deep: {_exception_message(close_error)}"
            finally:
                self.session = None
                self.finished.emit(success, message)
