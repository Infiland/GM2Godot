# pyright: reportPrivateUsage=false
# ruff: noqa: E402

from __future__ import annotations

import os
import threading
import time
import unittest
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow

from src.gui.main_window import MainWindow


class _ControlledTimer:
    def __init__(self) -> None:
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0

    def isActive(self) -> bool:
        return self.active

    def start(self) -> None:
        self.active = True
        self.start_calls += 1

    def stop(self) -> None:
        self.active = False
        self.stop_calls += 1


class _ControlledThread:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.quit_calls = 0

    def isRunning(self) -> bool:
        return self.running

    def quit(self) -> None:
        self.quit_calls += 1

    def wait(self, _milliseconds: int) -> bool:
        raise AssertionError("closeEvent must not block waiting for a live worker")


class _BlockingThread(QThread):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self) -> None:
        self.entered.set()
        self.release.wait(timeout=5)


class _CloseLifecycleWindow(MainWindow):
    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self._conversion_running = threading.Event()
        self._conversion_thread: QThread | None = None
        self._update_thread: QThread | None = None
        self._close_pending = False
        self.controlled_timer = _ControlledTimer()
        self._close_retry_timer = cast(QTimer, self.controlled_timer)
        self.close_calls = 0

    def close(self) -> bool:
        self.close_calls += 1
        return True


class MainWindowCloseLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing_app = QApplication.instance()
        cls.app = existing_app if isinstance(existing_app, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.window = _CloseLifecycleWindow()
        self.blocking_threads: list[_BlockingThread] = []

    def tearDown(self) -> None:
        for thread in self.blocking_threads:
            thread.release.set()
            thread.wait(2000)
        self.window.deleteLater()
        self.app.processEvents()

    def test_close_is_deferred_without_blocking_while_real_thread_is_running(self) -> None:
        thread = _BlockingThread()
        self.blocking_threads.append(thread)
        self.window._conversion_thread = thread
        self.window._conversion_running.set()
        thread.start()
        self.assertTrue(thread.entered.wait(timeout=1))
        event = QCloseEvent()

        started_at = time.monotonic()
        self.window.closeEvent(event)
        elapsed = time.monotonic() - started_at

        self.assertFalse(event.isAccepted())
        self.assertLess(elapsed, 0.25)
        self.assertFalse(self.window._conversion_running.is_set())
        self.assertTrue(thread.isRunning())
        self.assertIs(self.window._conversion_thread, thread)
        self.assertTrue(self.window.controlled_timer.active)
        self.assertEqual(self.window.close_calls, 0)

        thread.release.set()
        self.assertTrue(thread.wait(2000))
        self.window._retry_pending_close()

        self.assertFalse(self.window.controlled_timer.active)
        self.assertFalse(self.window._close_pending)
        self.assertEqual(self.window.close_calls, 1)

    def test_close_waits_for_both_controlled_threads_before_retrying(self) -> None:
        conversion_thread = _ControlledThread()
        update_thread = _ControlledThread()
        self.window._conversion_thread = cast(QThread, conversion_thread)
        self.window._update_thread = cast(QThread, update_thread)
        event = QCloseEvent()

        self.window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertEqual(conversion_thread.quit_calls, 1)
        self.assertEqual(update_thread.quit_calls, 1)
        self.assertEqual(self.window.close_calls, 0)

        conversion_thread.running = False
        self.window._retry_pending_close()
        self.assertEqual(self.window.close_calls, 0)
        self.assertTrue(self.window.controlled_timer.active)

        update_thread.running = False
        self.window._retry_pending_close()
        self.assertEqual(self.window.close_calls, 1)
        self.assertFalse(self.window.controlled_timer.active)

    def test_close_is_accepted_immediately_when_no_worker_thread_is_running(self) -> None:
        event = QCloseEvent()

        self.window.closeEvent(event)

        self.assertTrue(event.isAccepted())
        self.assertFalse(self.window._close_pending)
        self.assertFalse(self.window.controlled_timer.active)


if __name__ == "__main__":
    unittest.main()
