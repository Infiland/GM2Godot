import colorsys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from src.gui.theme import THEME
from src.localization import get_localized


class GradientProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0
        self.setFixedHeight(30)

    def set_progress(self, value):
        self._progress = max(0, min(100, value))
        self.update()

    def _get_progress_color(self, progress_fraction):
        hue = progress_fraction * 120 / 360
        r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 0.9)
        return QColor(int(r * 255), int(g * 255), int(b * 255))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2

        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME["bg_secondary"]))
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Fill
        fill_width = int(w * (self._progress / 100))
        if fill_width > 0:
            color = self._get_progress_color(self._progress / 100)
            painter.setBrush(color)
            painter.drawRoundedRect(0, 0, fill_width, h, radius, radius)

        # Text
        painter.setPen(QColor(THEME["fg_white"]))
        font = QFont(THEME["font_family"], THEME["font_size_large"])
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, f"{self._progress}%")

        painter.end()


class ProgressPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.progress_bar = GradientProgressBar()
        layout.addWidget(self.progress_bar)

        status_row = QHBoxLayout()
        status_row.setSpacing(20)

        self.timer_label = QLabel(f"{get_localized('Menu_UI_Time_Heading')} 00:00:00")
        status_row.addWidget(self.timer_label)

        self.status_label = QLabel("")
        status_row.addWidget(self.status_label, stretch=1)

        layout.addLayout(status_row)
