from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor

from src.gui.theme import THEME


class ConsolePanel(QWidget):
    def __init__(self, parent=None):
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

    def _get_format(self, message):
        msg_lower = message.lower()
        if msg_lower.startswith("warning:") or ": warning:" in msg_lower:
            return self._warning_format
        if msg_lower.startswith("error:") or ": error:" in msg_lower:
            return self._error_format
        return self._default_format

    def append_log(self, message, success=False):
        fmt = self._success_format if success else self._get_format(message)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._text_edit.document().isEmpty():
            cursor.insertBlock()
        cursor.setCharFormat(fmt)
        cursor.insertText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def update_last_line(self, message):
        fmt = self._get_format(message)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.setCharFormat(fmt)
        cursor.insertText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self._text_edit.clear()
