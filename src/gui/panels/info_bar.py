import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

from src.gui.theme import THEME
from src.version import get_version
from src.localization import get_localized


class ClickableLabel(QLabel):
    def __init__(self, text, callback, parent=None):
        super().__init__(text, parent)
        self._callback = callback
        self._default_color = THEME["fg_primary"]
        self._hover_color = THEME["accent_blue"]
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"font-size: {THEME['font_size_small']}pt;")

    def enterEvent(self, event):
        self.setStyleSheet(
            f"color: {self._hover_color}; font-size: {THEME['font_size_small']}pt;"
        )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(f"font-size: {THEME['font_size_small']}pt;")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
        super().mousePressEvent(event)


class InfoBar(QWidget):
    def __init__(self, on_version_click, on_language_click, language_icon, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        version_label = ClickableLabel(
            get_localized("UI_Label_Version").format(version=get_version()),
            on_version_click,
        )
        layout.addWidget(version_label)

        layout.addStretch()

        contribute_label = ClickableLabel(
            get_localized("UI_Label_Contribute"),
            lambda: webbrowser.open_new("https://github.com/Infiland/GM2Godot"),
        )
        layout.addWidget(contribute_label)

        layout.addStretch()

        made_by_label = ClickableLabel(
            get_localized("UI_Label_MadeBy"),
            lambda: webbrowser.open_new("https://infi.land"),
        )
        layout.addWidget(made_by_label)

        lang_button = QPushButton()
        lang_button.setIcon(language_icon)
        lang_button.setFixedSize(32, 32)
        lang_button.setStyleSheet(
            f"background-color: transparent; border: none;"
        )
        lang_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        lang_button.clicked.connect(on_language_click)
        layout.addWidget(lang_button)
