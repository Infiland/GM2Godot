from __future__ import annotations

import os
from pathlib import Path
import sys

CLI_COMMANDS = {"analyze", "convert", "list-converters", "report", "validate"}
CLI_GLOBAL_FLAGS = {"--help", "-h", "--version"}
GUI_SMOKE_RECEIPT_ENV = "GM2GODOT_GUI_SMOKE_RECEIPT"
GUI_SMOKE_RECEIPT = "GM2Godot packaged GUI ready\n"


def _configured_gui_smoke_receipt() -> Path | None:
    raw_path = os.environ.get(GUI_SMOKE_RECEIPT_ENV)
    if raw_path is None:
        return None
    if not raw_path:
        raise ValueError(f"{GUI_SMOKE_RECEIPT_ENV} must not be empty")

    receipt_path = Path(raw_path)
    if not receipt_path.is_absolute():
        raise ValueError(f"{GUI_SMOKE_RECEIPT_ENV} must be an absolute path")
    return receipt_path


def _write_gui_smoke_receipt(receipt_path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(receipt_path, flags | no_follow, 0o600)
    created: os.stat_result | None = None
    try:
        created = os.fstat(descriptor)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(GUI_SMOKE_RECEIPT)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            current = receipt_path.lstat()
            if created is not None and (current.st_dev, current.st_ino) == (
                created.st_dev,
                created.st_ino,
            ):
                receipt_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    if len(sys.argv) > 1 and (sys.argv[1] in CLI_COMMANDS or sys.argv[1] in CLI_GLOBAL_FLAGS):
        from src.cli import main as cli_main

        sys.exit(cli_main(sys.argv[1:]))

    try:
        smoke_receipt = _configured_gui_smoke_receipt()
    except ValueError as error:
        print(f"GUI startup smoke configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from src.gui.main_window import MainWindow
    from src.gui.theme import generate_stylesheet

    app = QApplication(sys.argv)
    app.setStyleSheet(generate_stylesheet())

    window = MainWindow(check_for_updates_on_startup=smoke_receipt is None)
    window.show()

    if smoke_receipt is not None:

        def complete_gui_smoke() -> None:
            try:
                if not window.isVisible():
                    raise RuntimeError("main window did not become visible")
                _write_gui_smoke_receipt(smoke_receipt)
            except Exception as error:
                print(f"GUI startup smoke failed: {error}", file=sys.stderr)
                app.exit(1)
                return
            app.quit()

        QTimer.singleShot(0, complete_gui_smoke)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
