import requests
import markdown2  # type: ignore[reportMissingTypeStubs]
from typing import Any, cast

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QMessageBox, QWidget

from src.gui.theme import THEME
from src.localization import get_localized


class ReleaseNotesDialog:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent

    def show(self) -> None:
        notes = self._fetch()
        if notes:
            self._display(notes)
        else:
            errors = get_localized("ReleaseNotes_Error_NoInternet")
            QMessageBox.critical(self._parent, errors[0], errors[1])

    def _fetch(self) -> str | None:
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/releases/latest",
                timeout=10,
            )
            if response.status_code == 200:
                data = cast(dict[str, Any], response.json())
                return str(data["body"])
            return None
        except Exception as e:
            print(get_localized("ReleaseNotes_Error_Generic").format(error=e))
            return None

    def _display(self, notes: str) -> None:
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
        html = cast(str, markdown2.markdown(notes, extras=["fenced-code-blocks"]))
        browser.setHtml(html)
        layout.addWidget(browser)

        dialog.exec()
