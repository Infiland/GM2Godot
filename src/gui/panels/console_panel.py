from __future__ import annotations

from typing import Literal, TypeAlias

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor

from src.gui.theme import THEME


ConsoleLogStyle: TypeAlias = Literal[
    "auto",
    "success",
    "warning",
    "error",
    "cancelled",
]


def _validate_log_style(style: str) -> ConsoleLogStyle:
    match style:
        case "auto" | "success" | "warning" | "error" | "cancelled":
            return style
        case _:
            raise ValueError(f"Unsupported console log style: {style!r}")


class ConsolePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        layout.addWidget(self._text_edit)

        self._default_format = QTextCharFormat()
        self._default_format.setForeground(QColor(THEME["fg_primary"]))

        self._warning_format = QTextCharFormat()
        self._warning_format.setForeground(QColor(THEME["log_warning"]))

        self._error_format = QTextCharFormat()
        self._error_format.setForeground(QColor(THEME["log_error"]))

        self._success_format = QTextCharFormat()
        self._success_format.setForeground(QColor(THEME["log_success"]))

        self._cancelled_format = QTextCharFormat()
        self._cancelled_format.setForeground(QColor(THEME["log_cancelled"]))

    def _get_format(
        self,
        message: str,
        style: ConsoleLogStyle = "auto",
    ) -> QTextCharFormat:
        log_style = _validate_log_style(style)
        if log_style == "success":
            return self._success_format
        if log_style == "warning":
            return self._warning_format
        if log_style == "error":
            return self._error_format
        if log_style == "cancelled":
            return self._cancelled_format

        msg_lower = message.lower()
        if msg_lower.startswith("warning:") or ": warning:" in msg_lower:
            return self._warning_format
        if msg_lower.startswith("error:") or ": error:" in msg_lower:
            return self._error_format
        return self._default_format

    def append_log(
        self,
        message: str,
        style: ConsoleLogStyle = "auto",
    ) -> None:
        fmt = self._get_format(message, style)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._text_edit.document().isEmpty():
            cursor.insertBlock()
        cursor.setCharFormat(fmt)
        cursor.insertText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def update_last_line(
        self,
        message: str,
        style: ConsoleLogStyle = "auto",
    ) -> None:
        fmt = self._get_format(message, style)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.setCharFormat(fmt)
        cursor.insertText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self) -> None:
        self._text_edit.clear()
