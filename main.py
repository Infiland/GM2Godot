import sys

from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.gui.theme import generate_stylesheet


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(generate_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
