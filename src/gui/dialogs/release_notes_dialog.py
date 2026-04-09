import requests
import markdown2

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QMessageBox

from src.gui.theme import THEME
from src.localization import get_localized


class ReleaseNotesDialog:
    def __init__(self, parent):
        self._parent = parent

    def show(self):
        notes = self._fetch()
        if notes:
            self._display(notes)
        else:
            errors = get_localized("ReleaseNotes_Error_NoInternet")
            QMessageBox.critical(self._parent, errors[0], errors[1])

    def _fetch(self):
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/releases/latest",
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()["body"]
            return None
        except Exception as e:
            print(get_localized("ReleaseNotes_Error_Generic").format(error=e))
            return None

    def _display(self, notes):
        dialog = QDialog(self._parent)
        dialog.setWindowTitle(get_localized("ReleaseNotes_Title"))
        dialog.resize(750, 600)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            f"background-color: {THEME['bg_tertiary']}; "
            f"color: {THEME['fg_white']}; "
            f"border: none; border-radius: 6px; padding: 10px;"
        )
        html = markdown2.markdown(notes, extras=["fenced-code-blocks"])
        browser.setHtml(html)
        layout.addWidget(browser)

        dialog.exec()
