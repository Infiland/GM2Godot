import webbrowser
from datetime import datetime

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
)

from src.gui.theme import THEME
from src.version import get_version
from src.localization import get_localized


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_localized("About_Title"))
        self.resize(600, 700)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # Title
        title = QLabel(get_localized("Menu_Title").format(version=get_version()))
        title.setStyleSheet(
            f"font-size: {THEME['font_size_heading']}pt; font-weight: bold; color: {THEME['fg_white']};"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel(get_localized("About_Description"))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"color: {THEME['fg_white']};")
        layout.addWidget(desc)

        # Contributors heading
        contrib_heading = QLabel(get_localized("About_Contributors_Heading"))
        contrib_heading.setStyleSheet(
            f"font-size: {THEME['font_size_large']}pt; font-weight: bold; color: {THEME['fg_white']};"
        )
        contrib_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(contrib_heading)

        # Scrollable contributors list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: {THEME['bg_dialog']}; border: none;")

        scroll_content = QWidget()
        self._contrib_layout = QVBoxLayout(scroll_content)
        self._contrib_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        self._load_contributors()

        # Links
        links = [
            (get_localized("About_Repository"), "https://github.com/Infiland/GM2Godot"),
            (get_localized("About_Issues"), "https://github.com/Infiland/GM2Godot/issues"),
            (get_localized("About_Website"), "https://infi.land"),
        ]
        for text, url in links:
            link = QLabel(text)
            link.setStyleSheet(
                f"color: {THEME['accent_link']}; font-size: {THEME['font_size']}pt;"
            )
            link.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            link.setAlignment(Qt.AlignmentFlag.AlignCenter)
            link.mousePressEvent = lambda e, u=url: webbrowser.open_new(u)
            layout.addWidget(link)

        # Copyright
        year = datetime.now().year
        copyright_label = QLabel(get_localized("About_Copyright").format(current_year=year))
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setStyleSheet(f"color: {THEME['fg_white']};")
        layout.addWidget(copyright_label)

    def _load_contributors(self):
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/contributors",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            response.raise_for_status()
            for contributor in response.json():
                self._add_contributor(contributor)
        except Exception as e:
            error_label = QLabel(
                get_localized("About_Error_Contributors_NotFound").format(error=str(e))
            )
            error_label.setStyleSheet(f"color: {THEME['fg_white']};")
            self._contrib_layout.addWidget(error_label)

    def _add_contributor(self, contributor):
        row = QHBoxLayout()

        # Avatar
        try:
            resp = requests.get(contributor["avatar_url"], timeout=10)
            pixmap = QPixmap()
            pixmap.loadFromData(resp.content)
            avatar = QLabel()
            avatar.setPixmap(pixmap.scaled(40, 40))
            avatar.setFixedSize(40, 40)
            row.addWidget(avatar)
        except Exception:
            pass

        # Info
        info_layout = QVBoxLayout()
        name = QLabel(contributor["login"])
        name.setStyleSheet(f"color: {THEME['fg_white']};")
        name.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        name.mousePressEvent = lambda e, u=contributor["html_url"]: webbrowser.open_new(u)
        info_layout.addWidget(name)

        contribs = QLabel(f"{contributor['contributions']} contributions")
        contribs.setStyleSheet(f"color: {THEME['fg_primary']};")
        info_layout.addWidget(contribs)

        row.addLayout(info_layout, stretch=1)
        self._contrib_layout.addLayout(row)
