import webbrowser
from typing import cast

import markdown2  # type: ignore[reportMissingTypeStubs]

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QTextBrowser, QProgressBar, QFileDialog, QMessageBox,
)

from src.gui.theme import THEME
from src.version import get_version
from src.localization import get_localized
from src.update_checker import UpdateChecker, UpdateInfo


class DownloadWorker(QObject):
    """Worker to download update in background thread."""
    progress = Signal(int)
    finished = Signal(bool)

    def __init__(self, url: str, dest_path: str) -> None:
        super().__init__()
        self.url = url
        self.dest_path = dest_path

    def run(self) -> None:
        success = UpdateChecker.download_update(
            self.url, self.dest_path,
            progress_callback=self.progress.emit
        )
        self.finished.emit(success)


class UpdateDialog(QDialog):
    def __init__(self, update_info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = update_info
        self._download_thread: QThread | None = None
        self._worker: DownloadWorker | None = None
        self.setWindowTitle(get_localized("Update_Available_Title"))
        self.resize(600, 500)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # Title
        title = QLabel(get_localized("Update_Available_Message"))
        title.setStyleSheet(f"font-size: {THEME['font_size_heading']}pt; font-weight: bold; color: {THEME['fg_white']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Version info
        version_layout = QHBoxLayout()
        current_label = QLabel(get_localized("Update_CurrentVersion").format(current=get_version()))
        current_label.setStyleSheet(f"color: {THEME['fg_primary']};")
        version_layout.addWidget(current_label)

        arrow = QLabel("\u2192")
        arrow.setStyleSheet(f"color: {THEME['fg_primary']}; font-size: {THEME['font_size_large']}pt;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_layout.addWidget(arrow)

        latest_label = QLabel(get_localized("Update_LatestVersion").format(latest=self._info.latest_version))
        latest_label.setStyleSheet(f"color: {THEME['log_success']}; font-weight: bold;")
        version_layout.addWidget(latest_label)

        version_layout.addStretch()
        layout.addLayout(version_layout)

        # Release notes
        if self._info.release_notes:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setStyleSheet(
                f"background-color: {THEME['bg_tertiary']}; "
                f"color: {THEME['fg_white']}; "
                f"border: none; border-radius: 6px; padding: 10px;"
            )
            html = cast(str, markdown2.markdown(self._info.release_notes, extras=["fenced-code-blocks"]))
            browser.setHtml(html)
            layout.addWidget(browser, stretch=1)

        # Progress bar (hidden initially)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Status label (hidden initially)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {THEME['fg_primary']};")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # Buttons
        btn_layout = QHBoxLayout()

        if self._info.download_url:
            download_btn = QPushButton(get_localized("Update_Button_Download"))
            download_btn.setStyleSheet(
                f"background-color: {THEME['accent_blue']}; color: {THEME['fg_white']}; "
                f"padding: 8px 16px; border-radius: 4px; font-weight: bold;"
            )
            download_btn.clicked.connect(self._start_download)
            btn_layout.addWidget(download_btn)
            self._download_btn = download_btn

        open_page_btn = QPushButton(get_localized("Update_Button_OpenPage"))
        open_page_btn.clicked.connect(lambda: webbrowser.open(self._info.release_page_url))
        btn_layout.addWidget(open_page_btn)

        skip_btn = QPushButton(get_localized("Update_Button_Skip"))
        skip_btn.clicked.connect(self._skip_version)
        btn_layout.addWidget(skip_btn)

        later_btn = QPushButton(get_localized("Update_Button_Later"))
        later_btn.clicked.connect(self.reject)
        btn_layout.addWidget(later_btn)

        layout.addLayout(btn_layout)

    def _start_download(self) -> None:
        """Open file dialog and start download."""
        download_url = self._info.download_url
        if download_url is None:
            return

        suggested_name = self._info.asset_name or f"GM2Godot-{self._info.latest_version}"
        dest_path, _ = QFileDialog.getSaveFileName(
            self, get_localized("Update_Button_Download"),
            suggested_name,
        )
        if not dest_path:
            return

        self._download_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setVisible(True)
        self._status_label.setText(get_localized("Update_Download_Progress").format(percent=0))

        self._worker = DownloadWorker(download_url, dest_path)
        self._download_thread = QThread()
        self._worker.moveToThread(self._download_thread)

        self._worker.progress.connect(self._on_download_progress)
        self._worker.finished.connect(lambda success=False: self._on_download_finished(success, dest_path))
        self._download_thread.started.connect(self._worker.run)
        self._download_thread.start()

    def _on_download_progress(self, percent: int) -> None:
        self._progress_bar.setValue(percent)
        self._status_label.setText(get_localized("Update_Download_Progress").format(percent=percent))

    def _on_download_finished(self, success: bool, dest_path: str) -> None:
        if self._download_thread:
            self._download_thread.quit()
            self._download_thread.wait()
            self._download_thread = None
            self._worker = None

        if success:
            self._progress_bar.setValue(100)
            self._status_label.setText(get_localized("Update_Download_Complete"))
            QMessageBox.information(
                self,
                get_localized("Update_Available_Title"),
                get_localized("Update_Download_Complete"),
            )
        else:
            self._status_label.setText(get_localized("Update_Error_Download").format(error="Download failed"))
            self._download_btn.setEnabled(True)

    def _skip_version(self) -> None:
        UpdateChecker.set_skipped_version(self._info.latest_version)
        self.reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.quit()
            self._download_thread.wait(3000)
        event.accept()
