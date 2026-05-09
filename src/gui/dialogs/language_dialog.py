import glob
import json
import os
import sys
from typing import Any, cast

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QWidget,
)

from src.localization import get_localized


def _base_path() -> str:
    if getattr(sys, 'frozen', False):
        return cast(str, getattr(sys, '_MEIPASS'))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class LanguageDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(get_localized("Language_Select_Title"))
        self.resize(300, 150)

        self._language_keys: list[str] = []
        self._current_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self._combo = QComboBox()
        self._load_languages()
        layout.addWidget(self._combo)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton(get_localized("Language_Select_Button_Save"))
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)

        cancel_btn = QPushButton(get_localized("Language_Select_Button_Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _load_languages(self) -> None:
        base = _base_path()
        lang_files = glob.glob(os.path.join(base, "Languages", "*.json"))

        current_key = ""
        try:
            with open(os.path.join(base, "Current Language"), "r", encoding="utf-8") as f:
                current_key = f.read().strip()
        except Exception:
            pass

        for i, path in enumerate(lang_files):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = cast(dict[str, Any], json.load(f))
                    self._language_keys.append(str(data["Language_Code"]))
                    self._combo.addItem(str(data["Language"]))
                    if data["Language_Code"] == current_key:
                        self._current_index = i
            except Exception:
                pass

        self._combo.setCurrentIndex(self._current_index)

    def _apply(self) -> None:
        base = _base_path()
        idx = self._combo.currentIndex()
        lang_code = self._language_keys[idx] if idx < len(self._language_keys) else "eng"

        try:
            with open(os.path.join(base, "Current Language"), "w", encoding="utf-8") as f:
                f.write(lang_code)
        except Exception:
            pass

        os.execl(sys.executable, sys.executable, *sys.argv)
