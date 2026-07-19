# pyright: reportPrivateUsage=false

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from main import (
    GUI_SMOKE_RECEIPT,
    GUI_SMOKE_RECEIPT_ENV,
    _configured_gui_smoke_receipt,
    _write_gui_smoke_receipt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GuiStartupSmokeTests(unittest.TestCase):
    def test_source_gui_reaches_event_loop_and_writes_exact_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            root = Path(raw_root)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            receipt = root / "ready.txt"
            environment = os.environ.copy()
            environment.update(
                {
                    "QT_QPA_PLATFORM": "offscreen",
                    "XDG_RUNTIME_DIR": str(runtime),
                    GUI_SMOKE_RECEIPT_ENV: str(receipt),
                }
            )

            result = subprocess.run(
                [sys.executable, "main.py"],
                cwd=PROJECT_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(receipt.read_text(encoding="utf-8"), GUI_SMOKE_RECEIPT)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertNotIn("QThread: Destroyed", result.stderr)

    def test_receipt_configuration_requires_a_nonempty_absolute_path(self) -> None:
        original = os.environ.get(GUI_SMOKE_RECEIPT_ENV)
        try:
            os.environ.pop(GUI_SMOKE_RECEIPT_ENV, None)
            self.assertIsNone(_configured_gui_smoke_receipt())

            for invalid in ("", "relative/ready.txt"):
                with self.subTest(invalid=invalid):
                    os.environ[GUI_SMOKE_RECEIPT_ENV] = invalid
                    with self.assertRaises(ValueError):
                        _configured_gui_smoke_receipt()
        finally:
            if original is None:
                os.environ.pop(GUI_SMOKE_RECEIPT_ENV, None)
            else:
                os.environ[GUI_SMOKE_RECEIPT_ENV] = original

    def test_receipt_writer_refuses_to_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            receipt = Path(raw_root) / "ready.txt"
            receipt.write_text("preserve\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                _write_gui_smoke_receipt(receipt)

            self.assertEqual(receipt.read_text(encoding="utf-8"), "preserve\n")

    @unittest.skipIf(os.name == "nt", "POSIX receipt permissions are Linux policy")
    def test_receipt_writer_forces_mode_0600_under_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            receipt = Path(raw_root) / "ready.txt"
            original_umask = os.umask(0o700)
            try:
                _write_gui_smoke_receipt(receipt)
            finally:
                os.umask(original_umask)

            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

    def test_main_reports_invalid_configuration_with_exit_status_2(self) -> None:
        environment = os.environ.copy()
        environment[GUI_SMOKE_RECEIPT_ENV] = "relative/ready.txt"

        result = subprocess.run(
            [sys.executable, "main.py"],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("GUI startup smoke configuration error", result.stderr)
        self.assertFalse((PROJECT_ROOT / "relative" / "ready.txt").exists())

    def test_main_reports_receipt_write_failure_with_exit_status_1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            root = Path(raw_root)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            receipt = root / "ready.txt"
            receipt.write_text("preserve\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "QT_QPA_PLATFORM": "offscreen",
                    "XDG_RUNTIME_DIR": str(runtime),
                    GUI_SMOKE_RECEIPT_ENV: str(receipt),
                }
            )

            result = subprocess.run(
                [sys.executable, "main.py"],
                cwd=PROJECT_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("GUI startup smoke failed", result.stderr)
            self.assertEqual(receipt.read_text(encoding="utf-8"), "preserve\n")

    def test_smoke_window_deterministically_skips_update_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            runtime = Path(raw_root) / "runtime"
            runtime.mkdir(mode=0o700)
            environment = os.environ.copy()
            environment.update(
                {
                    "QT_QPA_PLATFORM": "offscreen",
                    "XDG_RUNTIME_DIR": str(runtime),
                }
            )
            code = (
                "from PySide6.QtWidgets import QApplication;"
                "from src.gui.main_window import MainWindow;"
                "app=QApplication([]);"
                "calls=[];"
                "MainWindow._check_for_updates_on_startup="
                "lambda self: calls.append(True);"
                "window=MainWindow(check_for_updates_on_startup=False);"
                "import os as process_os;"
                "process_os._exit(1 if calls else 0)"
            )

            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=PROJECT_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_receipt_writer_refuses_a_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-gui-smoke-") as raw_root:
            root = Path(raw_root)
            target = root / "target.txt"
            target.write_text("preserve\n", encoding="utf-8")
            receipt = root / "ready.txt"
            receipt.symlink_to(target)

            with self.assertRaises(FileExistsError):
                _write_gui_smoke_receipt(receipt)

            self.assertTrue(receipt.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
