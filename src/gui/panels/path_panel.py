from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog,
)
from PySide6.QtGui import QPixmap

from src.localization import get_localized


class PathPanel(QWidget):
    path_selected = Signal(str, str)  # (key, folder_path)

    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self._icons = icons
        self._entries = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        paths = [
            ("gamemaker", "GameMaker", self._icons.gamemaker_icon()),
            ("godot", "Godot", self._icons.godot_icon()),
        ]

        for key, label_text, icon_pixmap in paths:
            row = QHBoxLayout()
            row.setSpacing(10)

            icon_label = QLabel()
            icon_label.setPixmap(icon_pixmap)
            icon_label.setFixedSize(20, 20)
            row.addWidget(icon_label)

            engine_name = get_localized(f"Menu_{label_text}")
            text_label = QLabel(
                get_localized("Menu_UI_Directory_Heading").format(Game_Engine=engine_name)
            )
            row.addWidget(text_label)

            entry = QLineEdit()
            entry.setPlaceholderText(
                get_localized(f"Prompt_Path_{label_text}")
            )
            row.addWidget(entry, stretch=1)

            browse_btn = QPushButton(
                get_localized("Menu_UI_Directory_Button").format(Game_Engine=engine_name)
            )
            browse_btn.clicked.connect(lambda checked, k=key: self._browse(k))
            row.addWidget(browse_btn)

            self._entries[key] = entry
            layout.addLayout(row)

    def _browse(self, key):
        folder = QFileDialog.getExistingDirectory(self, get_localized(f"Prompt_Path_{'GameMaker' if key == 'gamemaker' else 'Godot'}"))
        if folder:
            self._entries[key].setText(folder)
            self.path_selected.emit(key, folder)

    def gamemaker_path(self):
        return self._entries["gamemaker"].text().strip()

    def godot_path(self):
        return self._entries["godot"].text().strip()
