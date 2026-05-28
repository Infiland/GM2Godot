import sys

CLI_COMMANDS = {"analyze", "convert", "list-converters", "report", "validate"}
CLI_GLOBAL_FLAGS = {"--help", "-h", "--version"}


def main() -> None:
    if len(sys.argv) > 1 and (sys.argv[1] in CLI_COMMANDS or sys.argv[1] in CLI_GLOBAL_FLAGS):
        from src.cli import main as cli_main

        sys.exit(cli_main(sys.argv[1:]))

    from PySide6.QtWidgets import QApplication

    from src.gui.main_window import MainWindow
    from src.gui.theme import generate_stylesheet

    app = QApplication(sys.argv)
    app.setStyleSheet(generate_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
