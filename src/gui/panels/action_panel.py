from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton

from src.localization import get_localized


class ActionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()

        self.convert_button = QPushButton(get_localized("Menu_UI_Button_Convert"))
        layout.addWidget(self.convert_button)

        self.stop_button = QPushButton("\u25A0")  # Unicode square for stop icon
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.settings_button = QPushButton(get_localized("Menu_UI_Button_Settings"))
        layout.addWidget(self.settings_button)

        layout.addStretch()
