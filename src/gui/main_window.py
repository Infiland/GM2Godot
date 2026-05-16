import os
import platform
import threading
import time
import webbrowser
import multiprocessing

from PySide6.QtCore import QThread, QTimer, Signal, QObject
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QMessageBox

from src.gui.icons import AppIcons
from src.gui.setting_value import SettingValue
from src.gui.workers import ConversionWorker
from src.gui.panels.path_panel import PathPanel
from src.gui.panels.action_panel import ActionPanel
from src.gui.panels.console_panel import ConsolePanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.info_bar import InfoBar
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.dialogs.about_dialog import AboutDialog
from src.gui.dialogs.release_notes_dialog import ReleaseNotesDialog
from src.gui.dialogs.language_dialog import LanguageDialog
from src.conversion.converter import CONVERSION_CATEGORIES
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
    def __init__(self) -> None:
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
        self._update_thread: QThread | None = None
        self._update_worker: UpdateCheckWorker | None = None
        self._timer_running = False
        self._start_time = 0

        self._release_notes = ReleaseNotesDialog(self)
        self._init_ui()
        self._create_menu()
        self._check_for_updates_on_startup()

        # Timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer)

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
        dialog = SettingsDialog(
            self._conversion_settings,
            self._compact_logging,
            self._gm_platform,
            self._max_workers,
            parent=self,
        )
        if dialog.exec():
            self._gm_platform = dialog.selected_platform()
            self._max_workers = dialog.selected_max_workers()

    def _open_language(self) -> None:
        LanguageDialog(self).exec()

    def _on_path_selected(self, key: str, folder: str) -> None:
        if key == "gamemaker":
            self._check_project_file(folder, ".yyp", "GameMaker")
        else:
            self._check_project_file(folder, "project.godot", "Godot")

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
        self._worker.status_updated.connect(self._progress.status_label.setText)
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

        godot_project = os.path.join(godot_path, "project.godot")

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
        if not os.path.exists(godot_project):
            self._console.append_log(get_localized("Console_Error_MissingGodotFile"))
            return False
        return True

    def _prepare_for_conversion(self) -> None:
        self._action_panel.convert_button.setEnabled(False)
        self._action_panel.stop_button.setEnabled(True)
        self._action_panel.settings_button.setEnabled(False)
        self._conversion_running.set()
        self._console.clear()
        self._progress.progress_bar.set_progress(0)
        self._console.append_log(get_localized("Console_ConversionStart"))

    def _stop_conversion(self) -> None:
        if self._conversion_running.is_set():
            self._conversion_running.clear()
            self._console.append_log(get_localized("Console_ConversionStopping"))
            self._action_panel.stop_button.setEnabled(False)

    def _conversion_complete(self) -> None:
        self._progress.progress_bar.set_progress(100)
        self._progress.status_label.setText(get_localized("Console_ConversionComplete"))

        if self._conversion_running.is_set():
            self._console.append_log(get_localized("Console_ConversionComplete_B"), success=True)
        else:
            self._console.append_log(get_localized("Console_ConversionStopped"))

        self._conversion_running.clear()
        self._action_panel.convert_button.setEnabled(True)
        self._action_panel.stop_button.setEnabled(False)
        self._action_panel.settings_button.setEnabled(True)
        self._stop_timer()

        if self._conversion_thread:
            self._conversion_thread.quit()
            self._conversion_thread.wait()
            self._conversion_thread = None
            self._worker = None

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
        if self._conversion_thread and self._conversion_thread.isRunning():
            self._conversion_running.clear()
            self._conversion_thread.quit()
            self._conversion_thread.wait(5000)
        if self._update_thread and self._update_thread.isRunning():
            self._update_thread.quit()
            self._update_thread.wait(3000)
        event.accept()
