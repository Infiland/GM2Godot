from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from PySide6.QtGui import QTextCursor


class ConsolePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        layout.addWidget(self._text_edit)

    def append_log(self, message):
        self._text_edit.appendPlainText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def update_last_line(self, message):
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(message)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self._text_edit.clear()
