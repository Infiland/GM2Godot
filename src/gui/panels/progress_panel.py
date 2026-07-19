import colorsys
from typing import Literal, TypeAlias

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QFont, QPaintEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from src.conversion.conversion_outcome import ConversionTerminalState
from src.gui.theme import THEME
from src.localization import get_localized


ProgressPresentationState: TypeAlias = Literal["running"] | ConversionTerminalState


def _validate_terminal_state(state: str) -> ConversionTerminalState:
    match state:
        case "success" | "partial" | "failed" | "cancelled":
            return state
        case _:
            raise ValueError(f"Unsupported conversion terminal state: {state!r}")


def _status_color(state: ProgressPresentationState) -> str:
    match state:
        case "running":
            return str(THEME["fg_primary"])
        case "success":
            return str(THEME["log_success"])
        case "partial":
            return str(THEME["log_warning"])
        case "failed":
            return str(THEME["log_error"])
        case "cancelled":
            return str(THEME["log_cancelled"])


class GradientProgressBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0
        self._presentation_state: ProgressPresentationState = "running"
        self.setFixedHeight(30)

    @property
    def presentation_state(self) -> ProgressPresentationState:
        return self._presentation_state

    def set_progress(self, value: int) -> None:
        self._progress = max(0, min(100, value))
        self.update()

    def set_running_status(self) -> None:
        self._presentation_state = "running"
        self.update()

    def set_terminal_status(self, state: ConversionTerminalState) -> None:
        self._presentation_state = _validate_terminal_state(state)
        self.update()

    def _get_progress_color(self, progress_fraction: float) -> QColor:
        if self._presentation_state != "running":
            return QColor(_status_color(self._presentation_state))

        hue = progress_fraction * 120 / 360
        r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 0.9)
        return QColor(int(r * 255), int(g * 255), int(b * 255))

    def paintEvent(self, event: QPaintEvent) -> None:
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

        # Text is clipped into two passes so it remains readable across the
        # fill boundary and at every terminal color.
        font = QFont(str(THEME["font_family"]), int(THEME["font_size_large"]))
        font.setBold(True)
        painter.setFont(font)

        painter.save()
        painter.setClipRect(0, 0, fill_width, h)
        painter.setPen(QColor(THEME["bg_primary"]))
        painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, f"{self._progress}%")
        painter.restore()

        painter.save()
        painter.setClipRect(fill_width, 0, w - fill_width, h)
        painter.setPen(QColor(THEME["fg_white"]))
        painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, f"{self._progress}%")
        painter.restore()

        painter.end()


class ProgressPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presentation_state: ProgressPresentationState = "running"
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
        self.set_running_status("")

    @property
    def presentation_state(self) -> ProgressPresentationState:
        return self._presentation_state

    def set_running_status(self, message: str) -> None:
        self._presentation_state = "running"
        self.progress_bar.set_running_status()
        self._set_status_label(message, "running")

    def set_terminal_status(
        self,
        message: str,
        state: ConversionTerminalState,
    ) -> None:
        terminal_state = _validate_terminal_state(state)
        self._presentation_state = terminal_state
        self.progress_bar.set_terminal_status(terminal_state)
        self._set_status_label(message, terminal_state)

    def _set_status_label(
        self,
        message: str,
        state: ProgressPresentationState,
    ) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            f"color: {_status_color(state)}; font-weight: bold;"
        )
