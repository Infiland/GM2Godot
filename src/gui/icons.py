import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap


def _base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AppIcons:
    def __init__(self):
        base = _base_path()
        self._app = QIcon(os.path.join(base, "img", "Logo.png"))
        self._gamemaker = QPixmap(os.path.join(base, "img", "Gamemaker.png")).scaled(
            20, 20, mode=Qt.TransformationMode.SmoothTransformation
        )
        self._godot = QPixmap(os.path.join(base, "img", "Godot.png")).scaled(
            20, 20, mode=Qt.TransformationMode.SmoothTransformation
        )
        self._language = QPixmap(os.path.join(base, "img", "icon_language.png")).scaled(
            24, 24, mode=Qt.TransformationMode.SmoothTransformation
        )

    def app_icon(self):
        return self._app

    def gamemaker_icon(self):
        return self._gamemaker

    def godot_icon(self):
        return self._godot

    def language_icon(self):
        return self._language
