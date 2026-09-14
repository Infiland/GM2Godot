import os
from typing import Any, cast
import platform
import threading
import time
import webbrowser
import multiprocessing

from PySide6.QtCore import QThread, QTimer, Signal, Slot, QObject
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QMessageBox, QDialog, QTextBrowser, QPushButton

from src.deep.jobs import DeepJob, pending_jobs
from src.deep.settings import load_settings
from src.gui.icons import AppIcons
from src.gui.setting_value import SettingValue
from src.gui.workers import ConversionWorker, ConversionWorkerResult, DeepConversionWorker
from src.gui.panels.path_panel import PathPanel
from src.gui.panels.action_panel import ActionPanel
from src.gui.panels.console_panel import ConsoleLogStyle, ConsolePanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.info_bar import InfoBar
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.dialogs.deep_resume_dialog import DeepResumeDialog
from src.gui.dialogs.about_dialog import AboutDialog
from src.gui.dialogs.release_notes_dialog import ReleaseNotesDialog
from src.gui.dialogs.language_dialog import LanguageDialog
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import CONVERSION_CATEGORIES
from src.conversion.project_godot import (
    GODOT_PROJECT_FILENAME,
    ConversionPreflightError,
    GodotProjectDestinationState,
    inspect_godot_project_destination,
)
from src.version import get_version
from src.localization import get_localized, get_localized_list
from src.update_checker import UpdateChecker
from src.update_checker import UpdateInfo
from src.gui.dialogs.update_dialog import UpdateDialog


class UpdateCheckWorker(QObject):
    update_available = Signal(object)  # emits UpdateInfo

    def run(self) -> None:
        checker = UpdateChecker()
        info = checker.check_for_update()
        if info and info.available:
            self.update_available.emit(info)


class MainWindow(QMainWindow):
    def __init__(self, *, check_for_updates_on_startup: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(get_localized("Menu_Title").format(version=get_version()))
        self.resize(800, 600)
        self.setMinimumSize(600, 400)

        self._icons = AppIcons()
        self.setWindowIcon(self._icons.app_icon())

        self._setup_conversion_settings()
        self._conversion_running = threading.Event()
        self._conversion_thread: QThread | None = None
        self._worker: ConversionWorker | None = None
        self._deep_conversion = SettingValue(False)
        self._deep_thread: QThread | None = None
        self._deep_worker: DeepConversionWorker | None = None
        self._deep_execute = False
        self._deep_job: DeepJob | None = None
        self._update_thread: QThread | None = None
        self._close_pending = False
        self._timer_running = False
        self._start_time = 0

        self._release_notes = ReleaseNotesDialog(self)
        self._init_ui()
        self._create_menu()
        if check_for_updates_on_startup:
            self._check_for_updates_on_startup()

        # Timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer)

        self._close_retry_timer = QTimer(self)
        self._close_retry_timer.setInterval(100)
        self._close_retry_timer.timeout.connect(self._retry_pending_close)
        QTimer.singleShot(0, self._offer_deep_resume)

    def _setup_conversion_settings(self) -> None:
        all_keys = [key for keys in CONVERSION_CATEGORIES.values() for key in keys]
        self._conversion_settings: dict[str, SettingValue] = {key: SettingValue(True) for key in all_keys}
        self._conversion_settings["notes"].set(False)
        self._conversion_settings["sound_group_folders"].set(False)
        self._compact_logging = SettingValue(True)
        self._max_workers = multiprocessing.cpu_count()

        match platform.system():
            case "Linux":
                self._gm_platform = "linux"
            case "Darwin":
                self._gm_platform = "macos"
            case _:
                self._gm_platform = "windows"

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(40, 20, 40, 20)
        layout.setSpacing(15)

        # Path inputs
        self._path_panel = PathPanel(self._icons)
        self._path_panel.path_selected.connect(self._on_path_selected)
        layout.addWidget(self._path_panel)

        # Action buttons
        self._action_panel = ActionPanel()
        self._action_panel.convert_button.clicked.connect(self._start_conversion)
        self._action_panel.stop_button.clicked.connect(self._stop_conversion)
        self._action_panel.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(self._action_panel)

        # Console
        self._console = ConsolePanel()
        layout.addWidget(self._console, stretch=1)

        # Progress
        self._progress = ProgressPanel()
        layout.addWidget(self._progress)

        # Info bar
        self._info_bar = InfoBar(
            on_version_click=self._release_notes.show,
            on_language_click=self._open_language,
            language_icon=QIcon(self._icons.language_icon()),
        )
        layout.addWidget(self._info_bar)

    def _create_menu(self) -> None:
        menu_bar = self.menuBar()
        deep_menu = menu_bar.addMenu("Deep")
        deep_menu.addAction("Resume saved job…", self._offer_deep_resume)
        help_menu = menu_bar.addMenu("Help")
        help_menu.addAction("About GM2Godot", self._show_about)
        help_menu.addSeparator()
        help_menu.addAction(
            "Documentation",
            lambda: webbrowser.open("https://github.com/Infiland/GM2Godot/wiki"),
        )
        help_menu.addAction(
            "Report Issue",
            lambda: webbrowser.open("https://github.com/Infiland/GM2Godot/issues"),
        )
        help_menu.addSeparator()
        help_menu.addAction(
            get_localized("Menu_CheckUpdates"),
            self._check_for_updates,
        )

    # --- Actions ---

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _check_for_updates_on_startup(self) -> None:
        self._update_worker = UpdateCheckWorker()
        self._update_thread = QThread()
        self._update_worker.moveToThread(self._update_thread)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_thread.start()

    def _on_update_available(self, info: UpdateInfo) -> None:
        if self._update_thread:
            self._update_thread.quit()
            self._update_thread.wait()
            self._update_thread = None
            self._update_worker = None

        skipped = UpdateChecker.get_skipped_version()
        if skipped == info.latest_version:
            return

        UpdateDialog(info, self).exec()

    def _check_for_updates(self) -> None:
        checker = UpdateChecker()
        info = checker.check_for_update()
        if info is None:
            QMessageBox.warning(self, "Error", get_localized("Update_Error_Check").format(error="Network error"))
            return
        if info.available:
            UpdateDialog(info, self).exec()
        else:
            QMessageBox.information(self, "GM2Godot", get_localized("Update_UpToDate"))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._conversion_settings, self._compact_logging, self._deep_conversion, self._gm_platform, self._max_workers, parent=self)
        if dialog.exec():
            self._gm_platform = dialog.selected_platform()
            self._max_workers = dialog.selected_max_workers()

    def _open_language(self) -> None:
        LanguageDialog(self).exec()

    def _on_path_selected(self, key: str, folder: str) -> None:
        if key == "gamemaker":
            self._check_project_file(folder, ".yyp", "GameMaker")
        else:
            self._check_godot_destination(folder)

    def _check_godot_destination(self, folder: str) -> None:
        try:
            destination_state = inspect_godot_project_destination(folder)
        except ConversionPreflightError as error:
            invalid_project = get_localized_list("Console_Error_InvalidProject")
            QMessageBox.warning(
                self,
                invalid_project[0].format(file_name="Godot"),
                self._godot_destination_error_message(error),
            )
            return

        if destination_state is GodotProjectDestinationState.EXISTING_PROJECT:
            self._console.append_log(
                get_localized("Console_ProjectFound").format(
                    file_name="Godot",
                    files=GODOT_PROJECT_FILENAME,
                )
            )
        elif destination_state is GodotProjectDestinationState.EMPTY:
            self._console.append_log(get_localized("Console_GodotDestinationEmpty"))
        else:
            invalid_project = get_localized_list("Console_Error_InvalidProject")
            QMessageBox.warning(
                self,
                invalid_project[0].format(file_name="Godot"),
                get_localized("Console_Error_MissingGodotDirectory"),
            )

    @staticmethod
    def _godot_destination_error_message(error: ConversionPreflightError) -> str:
        if error.code == "GM2GD-CONVERT-DESTINATION-NOT-EMPTY":
            return get_localized("Console_Error_GodotDestinationOccupied")
        return get_localized("Console_Error_GodotDestinationInvalid").format(
            error=str(error)
        )

    def _check_project_file(self, folder: str, file_extension: str, file_name: str) -> None:
        try:
            files = [f for f in os.listdir(folder) if f.endswith(file_extension)]
        except OSError:
            return
        if not files:
            errors = get_localized_list("Console_Error_InvalidProject")
            QMessageBox.warning(
                self,
                errors[0].format(file_name=file_name),
                errors[1].format(file_name=file_name, file_extension=file_extension),
            )
        elif len(files) > 1:
            errors = get_localized_list("Console_Error_MultipleGenericFiles")
            QMessageBox.warning(
                self,
                errors[0].format(file_extension=file_extension),
                errors[1].format(file_extension=file_extension, files=", ".join(files)),
            )
        else:
            self._console.append_log(
                get_localized("Console_ProjectFound").format(
                    file_name=file_name, files=files[0]
                )
            )

    # --- Conversion ---

    def _start_conversion(self) -> None:
        gm_path = self._path_panel.gamemaker_path()
        godot_path = self._path_panel.godot_path()

        if not gm_path or not godot_path:
            self._console.append_log(get_localized("Console_Error_MissingDirectories"))
            return

        if not self._validate_projects(gm_path, godot_path):
            return

        self._prepare_for_conversion()

        self._worker = ConversionWorker(
            gm_path,
            self._gm_platform,
            godot_path,
            self._conversion_settings,
            self._compact_logging.get(),
            self._conversion_running,
            max_workers=self._max_workers,
        )

        self._conversion_thread = QThread()
        self._worker.moveToThread(self._conversion_thread)

        self._worker.log_message.connect(self._console.append_log)
        self._worker.update_log_message.connect(self._console.update_last_line)
        self._worker.progress_updated.connect(self._progress.progress_bar.set_progress)
        self._worker.status_updated.connect(self._progress.set_running_status)
        self._worker.conversion_finished.connect(self._conversion_complete)

        self._conversion_thread.started.connect(self._worker.run)
        self._conversion_thread.start()

        self._start_timer()

    def _validate_projects(self, gm_path: str, godot_path: str) -> bool:
        try:
            yyp_files = [f for f in os.listdir(gm_path) if f.endswith(".yyp")]
        except OSError:
            self._console.append_log(get_localized("Console_Error_MissingGamemakerFile"))
            return False

        if not yyp_files:
            self._console.append_log(get_localized("Console_Error_MissingGamemakerFile"))
            return False
        if len(yyp_files) > 1:
            self._console.append_log(
                get_localized("Console_Error_MultipleGamemakerFiles").format(
                    yyp_files=", ".join(yyp_files)
                )
            )
            return False

        try:
            destination_state = inspect_godot_project_destination(godot_path)
        except ConversionPreflightError as error:
            self._console.append_log(self._godot_destination_error_message(error))
            return False
        if destination_state is GodotProjectDestinationState.MISSING:
            self._console.append_log(
                get_localized("Console_Error_MissingGodotDirectory")
            )
            return False
        return True

    def _prepare_for_conversion(self) -> None:
        self._action_panel.convert_button.setEnabled(False)
        self._action_panel.stop_button.setEnabled(True)
        self._action_panel.settings_button.setEnabled(False)
        self._conversion_running.set()
        self._console.clear()
        self._progress.progress_bar.set_progress(0)
        self._progress.set_running_status("")
        self._console.append_log(get_localized("Console_ConversionStart"))

    def _stop_conversion(self) -> None:
        if self._deep_worker is not None:
            self._deep_worker.pause()
            self._console.append_log("Pausing Deep conversion; progress is saved.")
            return
        if self._conversion_running.is_set():
            self._conversion_running.clear()
            self._console.append_log(get_localized("Console_ConversionStopping"))
            self._action_panel.stop_button.setEnabled(False)

    @Slot(object)
    def _conversion_complete(self, result: ConversionWorkerResult) -> None:
        try:
            self._present_conversion_result(result)
        finally:
            self._finish_conversion_lifecycle()
        if result.error_message is None and result.outcome is not None and result.outcome.state in {"success", "partial"} and self._deep_conversion.get() and not self._close_pending:
            self._start_deep_conversion()

    def _present_conversion_result(self, result: ConversionWorkerResult) -> None:
        outcome = result.outcome
        if result.error_message is not None:
            failure_message = get_localized("Console_ConversionFailed").format(error=result.error_message)
            self._progress.set_terminal_status(failure_message, "failed")
            self._console.append_log(failure_message, "error")
            if outcome is not None:
                self._append_resource_counts(outcome, "error")
        elif outcome is None:
            failure_message = get_localized("Console_ConversionFailed").format(
                error="missing terminal outcome"
            )
            self._progress.set_terminal_status(failure_message, "failed")
            self._console.append_log(failure_message, "error")
        elif outcome.state == "success":
            self._progress.progress_bar.set_progress(100)
            self._progress.set_terminal_status(
                get_localized("Console_ConversionComplete"), "success"
            )
            self._console.append_log(
                get_localized("Console_ConversionComplete_B"), "success"
            )
            self._append_resource_counts(outcome, "success")
        elif outcome.state == "partial":
            self._progress.progress_bar.set_progress(100)
            partial_message = get_localized("Console_ConversionPartial")
            self._progress.set_terminal_status(partial_message, "partial")
            self._console.append_log(partial_message, "warning")
            self._append_resource_counts(outcome, "warning")
            if result.diagnostic_report_path is not None:
                self._console.append_log(
                    get_localized("Console_ConversionDiagnostics").format(
                        report_path=result.diagnostic_report_path
                    ),
                    "warning",
                )
        elif outcome.state == "failed":
            failure_message = get_localized("Console_ConversionFailedState")
            self._progress.set_terminal_status(failure_message, "failed")
            self._console.append_log(failure_message, "error")
            self._append_resource_counts(outcome, "error")
        elif outcome.state == "cancelled":
            stopped_message = get_localized("Console_ConversionStopped")
            self._progress.set_terminal_status(stopped_message, "cancelled")
            self._console.append_log(stopped_message, "cancelled")

            self._append_resource_counts(outcome, "cancelled")

    def _finish_conversion_lifecycle(self) -> None:
        self._conversion_running.clear()
        self._action_panel.convert_button.setEnabled(True)
        self._action_panel.stop_button.setEnabled(False)
        self._action_panel.settings_button.setEnabled(True)
        self._stop_timer()

        try:
            if self._conversion_thread:
                self._conversion_thread.quit()
                self._conversion_thread.wait()
        finally:
            self._conversion_thread = None
            self._worker = None


    def _offer_deep_resume(self) -> None:
        if self._deep_thread is not None or self._conversion_running.is_set():
            return
        jobs = pending_jobs()
        if not jobs or self._close_pending:
            return
        job = jobs[-1]
        answer = QMessageBox.question(self, "Resume Deep conversion", f"Saved job for {job.source} ({job.phase}). Resume without repeating baseline conversion?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._deep_job = job
            if job.phase == "review":
                self._review_deep_plan({})
            else:
                settings_dialog = DeepResumeDialog(job.settings, self)
                if settings_dialog.exec():
                    job.settings = settings_dialog.settings()
                    job.save()
                    self._launch_deep("resume")

    def _start_deep_conversion(self, *, execute: bool = False) -> None:
        if self._deep_thread is not None:
            return
        try:
            if not execute:
                settings = load_settings()
                recipient = f"{settings.runtime} / {settings.provider} / {settings.model}"
                message = f"Research will send project source to {recipient}. Read the provider's data-use terms in Deep setup. Start research?"
                if settings.runtime == "mock":
                    message = "Run a simulated research job? Mock results do not establish conversion correctness."
                answer = QMessageBox.question(self, "Start Deep research", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                settings.allowRemoteSourceUpload = True
                self._deep_job = DeepJob.create(self._path_panel.gamemaker_path(), self._path_panel.godot_path(), settings)
            self._launch_deep("convert" if execute else "research")
        except Exception as error:
            QMessageBox.warning(self, "Deep conversion", str(error))

    def _launch_deep(self, method: str) -> None:
        if self._deep_job is None:
            return
        self._deep_execute = method == "convert"
        self._deep_worker = DeepConversionWorker(self._deep_job, method=method)
        self._deep_thread = QThread()
        self._deep_worker.moveToThread(self._deep_thread)
        self._deep_worker.log_message.connect(self._console.append_log)
        self._deep_worker.event_received.connect(self._deep_event)
        self._deep_worker.finished.connect(self._deep_finished)
        self._deep_thread.started.connect(self._deep_worker.run)
        self._action_panel.convert_button.setEnabled(False)
        self._action_panel.stop_button.setEnabled(True)
        self._action_panel.settings_button.setEnabled(False)
        self._deep_thread.start()

    @Slot(object)
    def _deep_event(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        event = cast(dict[str, Any], raw)
        result = event.get("result", {})
        phase = str(result.get("phase", event.get("type", "Research"))).capitalize()
        message = result.get("message")
        if message:
            self._console.append_log(f"Deep: {message}")
        elif result.get("taskId"):
            self._console.append_log(f"Deep {result.get('role', 'agent')}: {result['taskId']} — {result.get('state', '')}")
        status = [phase]
        active = result.get("activeAgents")
        if isinstance(active, int):
            status.append(f"{active} active agents")
        completed, total = result.get("completed"), result.get("total")
        if isinstance(completed, int) and isinstance(total, int) and total > 0:
            status.append(f"{completed}/{total} research units")
            self._progress.progress_bar.set_progress(int(100 * completed / total))
        blocked = result.get("blocked")
        if isinstance(blocked, int) and blocked:
            status.append(f"{blocked} blocked")
        self._progress.set_running_status(" · ".join(status))

    @Slot(bool, str)
    def _deep_finished(self, success: bool, message: str) -> None:
        result: dict[str, Any] = self._deep_worker.result.get("result", {}) if self._deep_worker else {}
        self._console.append_log("Deep conversion: " + message, "success" if success else "error")
        if self._deep_thread:
            self._deep_thread.quit()
            self._deep_thread.wait()
        self._deep_thread = None
        self._deep_worker = None
        self._action_panel.convert_button.setEnabled(True)
        self._action_panel.stop_button.setEnabled(False)
        self._action_panel.settings_button.setEnabled(True)
        if success and self._deep_job and self._deep_job.phase == "review" and not self._close_pending:
            self._review_deep_plan(result)

    def _review_deep_plan(self, result: dict[str, Any]) -> None:
        if self._deep_job is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Review Deep conversion plan")
        dialog.resize(850, 650)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        report = ""
        reports = sorted(self._deep_job.root.rglob("*.md"))
        for path in reports:
            if "plan" in path.name.lower() or "research" in path.name.lower():
                report += f"\n\n## {path.name}\n" + path.read_text(encoding="utf-8")
        browser.setMarkdown(report or f"Review job artifacts in {self._deep_job.root}")
        layout.addWidget(browser)
        convert = QPushButton("Start conversion into a separate Godot project")
        convert.clicked.connect(dialog.accept)
        layout.addWidget(convert)
        if dialog.exec():
            self._start_deep_conversion(execute=True)

    def _append_resource_counts(
        self,
        outcome: ConversionOutcome,
        style: ConsoleLogStyle,
    ) -> None:
        counts = outcome.resources
        self._console.append_log(
            get_localized("Console_ConversionResourceCounts").format(
                requested=counts.requested,
                executed=counts.executed,
                completed=counts.completed,
                skipped=counts.skipped,
                failed=counts.failed,
            ),
            style,
        )

    # --- Timer ---

    def _start_timer(self) -> None:
        self._timer_running = True
        self._start_time = time.time()
        self._timer.start()

    def _stop_timer(self) -> None:
        self._timer_running = False
        self._timer.stop()

    def _update_timer(self) -> None:
        elapsed = int(time.time() - self._start_time)
        h, remainder = divmod(elapsed, 3600)
        m, s = divmod(remainder, 60)
        self._progress.timer_label.setText(
            f"{get_localized('Menu_UI_Time_Heading')} {h:02d}:{m:02d}:{s:02d}"
        )

    # --- Close ---

    def closeEvent(self, event: QCloseEvent) -> None:
        self._request_worker_thread_shutdown()
        if self._worker_threads_running():
            self._close_pending = True
            if not self._close_retry_timer.isActive():
                self._close_retry_timer.start()
            event.ignore()
            return

        self._close_pending = False
        self._close_retry_timer.stop()
        event.accept()

    def _request_worker_thread_shutdown(self) -> None:
        self._conversion_running.clear()
        if self._deep_worker is not None:
            self._deep_worker.pause()
        for thread in (self._conversion_thread, self._update_thread):
            if thread is not None and thread.isRunning():
                thread.quit()

    def _worker_threads_running(self) -> bool:
        return any(
            thread is not None and thread.isRunning()
            for thread in (self._conversion_thread, self._update_thread, self._deep_thread)
        )

    def _retry_pending_close(self) -> None:
        if not self._close_pending:
            self._close_retry_timer.stop()
            return

        self._request_worker_thread_shutdown()
        if self._worker_threads_running():
            return

        self._close_retry_timer.stop()
        self._close_pending = False
        self.close()
