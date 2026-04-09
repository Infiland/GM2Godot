import multiprocessing

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QCheckBox, QComboBox, QPushButton, QWidget, QSpinBox,
)

from src.gui.theme import THEME
from src.conversion.converter import CONVERSION_CATEGORIES
from src.localization import get_localized


class SettingsDialog(QDialog):
    def __init__(self, conversion_settings, compact_logging, platform_value, max_workers, parent=None):
        super().__init__(parent)
        self._settings = conversion_settings
        self._compact_logging = compact_logging
        self._platform = platform_value
        self._max_workers = max_workers
        self._checkboxes = {}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle(get_localized("Settings_Title"))
        self.resize(800, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Files heading
        heading = QLabel(get_localized("Settings_Files_Heading"))
        heading.setStyleSheet(
            f"font-size: {THEME['font_size_title']}pt; font-weight: bold;"
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        # Category columns
        categories_widget = QWidget()
        grid = QGridLayout(categories_widget)
        grid.setSpacing(20)

        labels = get_localized("Settings_Labels")
        headings = get_localized("Settings_Categories_Headings")
        categories_items = list(CONVERSION_CATEGORIES.items())

        for col, (cat_key, setting_keys) in enumerate(categories_items):
            col_layout = QVBoxLayout()

            cat_heading = QLabel(headings[col])
            cat_heading.setStyleSheet(
                f"font-size: {THEME['font_size_large']}pt; font-weight: bold;"
            )
            col_layout.addWidget(cat_heading)

            for key in setting_keys:
                display_name = labels.get(key, key.replace("_", " ").title())
                cb = QCheckBox(display_name)
                cb.setChecked(self._settings[key].get())
                cb.toggled.connect(lambda checked, k=key: self._settings[k].set(checked))
                col_layout.addWidget(cb)
                self._checkboxes[key] = cb

            col_layout.addStretch()
            grid.addLayout(col_layout, 0, col)

        layout.addWidget(categories_widget, stretch=1)

        # Platform section
        platform_heading = QLabel(get_localized("Settings_Platform_Heading"))
        platform_heading.setStyleSheet(
            f"font-size: {THEME['font_size_title']}pt; font-weight: bold;"
        )
        layout.addWidget(platform_heading)

        platform_sub = QLabel(get_localized("Settings_Platform_Subheading"))
        layout.addWidget(platform_sub)

        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["linux", "macos", "windows"])
        self._platform_combo.setCurrentText(self._platform)
        layout.addWidget(self._platform_combo)

        # Logging section
        logging_heading = QLabel(get_localized("Settings_Logging_Heading"))
        logging_heading.setStyleSheet(
            f"font-size: {THEME['font_size_title']}pt; font-weight: bold;"
        )
        layout.addWidget(logging_heading)

        compact_cb = QCheckBox(get_localized("Settings_Logging_Compact"))
        compact_cb.setChecked(self._compact_logging.get())
        compact_cb.toggled.connect(self._compact_logging.set)
        layout.addWidget(compact_cb)

        # Performance section
        perf_heading = QLabel(get_localized("Settings_Performance_Heading"))
        perf_heading.setStyleSheet(
            f"font-size: {THEME['font_size_title']}pt; font-weight: bold;"
        )
        layout.addWidget(perf_heading)

        workers_row = QHBoxLayout()
        workers_label = QLabel(get_localized("Settings_Performance_Threads"))
        workers_row.addWidget(workers_label)

        self._workers_spin = QSpinBox()
        self._workers_spin.setMinimum(1)
        self._workers_spin.setMaximum(multiprocessing.cpu_count())
        self._workers_spin.setValue(self._max_workers)
        workers_row.addWidget(self._workers_spin)

        max_label = QLabel(f"/ {multiprocessing.cpu_count()}")
        workers_row.addWidget(max_label)
        workers_row.addStretch()

        layout.addLayout(workers_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        select_all = QPushButton(get_localized("Settings_Button_SelectAll"))
        select_all.clicked.connect(self._select_all)
        btn_row.addWidget(select_all)

        deselect_all = QPushButton(get_localized("Settings_Button_DeselectAll"))
        deselect_all.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_all)

        save_btn = QPushButton(get_localized("Settings_Button_Save"))
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _select_all(self):
        for key, cb in self._checkboxes.items():
            cb.setChecked(True)

    def _deselect_all(self):
        for key, cb in self._checkboxes.items():
            cb.setChecked(False)

    def selected_platform(self):
        return self._platform_combo.currentText()

    def selected_max_workers(self):
        return self._workers_spin.value()
