import os
import tempfile

THEME = {
    # Backgrounds
    "bg_primary": "#1e1e1e",
    "bg_secondary": "#2d2d2d",
    "bg_tertiary": "#3d3d3d",
    "bg_dialog": "#222222",

    # Text
    "fg_primary": "#e0e0e0",
    "fg_white": "#ffffff",
    "fg_disabled": "#666666",

    # Accent
    "accent_blue": "#0078d4",
    "accent_blue_hover": "#106ebe",
    "accent_blue_light": "#1e8ad4",
    "accent_link": "#4da6ff",

    # Red / stop
    "accent_red": "#d83b01",
    "accent_red_hover": "#a62d00",

    # Disabled / borders
    "disabled_bg": "#333333",
    "border": "#404040",
    "border_hover": "#505050",

    # Fonts
    "font_family": "Segoe UI",
    "font_size_small": 9,
    "font_size": 10,
    "font_size_large": 12,
    "font_size_title": 14,
    "font_size_heading": 16,
}


_cached_checkmark = None


def _checkmark_path():
    global _cached_checkmark
    if _cached_checkmark and os.path.exists(_cached_checkmark):
        return _cached_checkmark.replace("\\", "/")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor

    size = 14
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(THEME["fg_white"]))
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(3, 7, 6, 10)
    painter.drawLine(6, 10, 11, 3)
    painter.end()

    path = os.path.join(tempfile.gettempdir(), "gm2godot_checkmark.png")
    pixmap.save(path, "PNG")
    _cached_checkmark = path
    return path.replace("\\", "/")


def generate_stylesheet():
    t = THEME
    return f"""
        QMainWindow, QDialog {{
            background-color: {t['bg_primary']};
        }}
        QWidget {{
            background-color: {t['bg_primary']};
            color: {t['fg_primary']};
            font-family: "{t['font_family']}";
            font-size: {t['font_size']}pt;
        }}
        QLabel {{
            background-color: transparent;
            color: {t['fg_primary']};
        }}
        QLineEdit {{
            background-color: {t['bg_secondary']};
            color: {t['fg_primary']};
            border: 1px solid {t['border']};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: {t['font_size']}pt;
        }}
        QLineEdit:focus {{
            border: 1px solid {t['accent_blue']};
        }}
        QPushButton {{
            background-color: {t['accent_blue']};
            color: {t['fg_white']};
            border: none;
            border-radius: 4px;
            padding: 8px 20px;
            font-weight: bold;
            font-size: {t['font_size']}pt;
        }}
        QPushButton:hover {{
            background-color: {t['accent_blue_hover']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_blue_light']};
        }}
        QPushButton:disabled {{
            background-color: {t['disabled_bg']};
            color: {t['fg_disabled']};
        }}
        QPushButton#stopButton {{
            background-color: {t['accent_red']};
            padding: 8px;
            min-width: 36px;
            max-width: 36px;
            min-height: 36px;
            max-height: 36px;
        }}
        QPushButton#stopButton:hover {{
            background-color: {t['accent_red_hover']};
        }}
        QPushButton#stopButton:disabled {{
            background-color: {t['disabled_bg']};
            color: {t['fg_disabled']};
        }}
        QPlainTextEdit {{
            background-color: {t['bg_secondary']};
            color: {t['fg_primary']};
            border: none;
            border-radius: 6px;
            padding: 10px;
            font-family: "Cascadia Code", "Consolas", monospace;
            font-size: {t['font_size']}pt;
        }}
        QCheckBox {{
            color: {t['fg_primary']};
            spacing: 8px;
            font-size: {t['font_size']}pt;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {t['border']};
            border-radius: 4px;
            background-color: {t['bg_secondary']};
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid {t['border_hover']};
            background-color: {t['bg_tertiary']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {t['accent_blue']};
            border: 1px solid {t['accent_blue']};
            image: url({_checkmark_path()});
        }}
        QCheckBox::indicator:checked:hover {{
            background-color: {t['accent_blue_hover']};
            border: 1px solid {t['accent_blue_hover']};
            image: url({_checkmark_path()});
        }}
        QComboBox {{
            background-color: {t['bg_secondary']};
            color: {t['fg_primary']};
            border: 1px solid {t['border']};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: {t['font_size']}pt;
        }}
        QComboBox:hover {{
            border: 1px solid {t['border_hover']};
        }}
        QComboBox::drop-down {{
            border: none;
            padding-right: 10px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid {t['fg_primary']};
            margin-right: 6px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {t['bg_secondary']};
            color: {t['fg_primary']};
            border: 1px solid {t['border']};
            selection-background-color: {t['accent_blue']};
            selection-color: {t['fg_white']};
            outline: none;
        }}
        QScrollBar:vertical {{
            background: {t['bg_primary']};
            width: 12px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {t['bg_tertiary']};
            border-radius: 6px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {t['border_hover']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background: {t['bg_primary']};
            height: 12px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {t['bg_tertiary']};
            border-radius: 6px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {t['border_hover']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
        QMenuBar {{
            background-color: {t['bg_primary']};
            color: {t['fg_primary']};
            border-bottom: 1px solid {t['border']};
        }}
        QMenuBar::item:selected {{
            background-color: {t['bg_secondary']};
        }}
        QMenu {{
            background-color: {t['bg_primary']};
            color: {t['fg_primary']};
            border: 1px solid {t['border']};
        }}
        QMenu::item:selected {{
            background-color: {t['bg_secondary']};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t['border']};
            margin: 4px 10px;
        }}
    """
