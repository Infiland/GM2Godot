from __future__ import annotations

import errno
import os
import stat
import tempfile
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.conversion.anchored_artifacts import VerifiedDirectory


@unittest.skipUnless(os.name == "posix", "native POSIX descriptor modes required")
class TestAnchoredDirectoryModes(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIn(os.chmod, os.supports_fd)
        self.assertTrue(callable(os.fchmod))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "artifact"
        self.target.write_bytes(b"original")
        self.target.chmod(0o400)
        current = self.target.stat()
        self.identity = (current.st_dev, current.st_ino)
        self.directory = VerifiedDirectory.open(str(self.root), description="mode test")
        self.addCleanup(self.directory.close)

    def change(self) -> int:
        return self.directory.chmod_exact(
            "artifact", self.identity, 0o600, require_single_link=True, expected_current_mode=0o400,
        )

    def assertClosed(self, descriptor: int) -> None:
        with self.assertRaises(OSError) as raised:
            os.fstat(descriptor)
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_descriptor_callbacks_return_final_mode(self) -> None:
        for force_fd_chmod in (False, True):
            with self.subTest(force_fd_chmod=force_fd_chmod):
                calls: list[tuple[int, int]] = []
                native = os.chmod if force_fd_chmod else os.fchmod

                def observe(
                    descriptor: int, mode: int, *, calls: list[tuple[int, int]] = calls,
                    native: Callable[[int, int], None] = native,
                ) -> None:
                    current = os.fstat(descriptor)
                    self.assertEqual((current.st_dev, current.st_ino), self.identity)
                    calls.append((descriptor, mode))
                    native(descriptor, mode)

                # Only the selector is modeled; both branches mutate a real native fd.
                with (
                    patch.object(os, "fchmod", None if force_fd_chmod else observe),
                    patch.object(os, "chmod", observe if force_fd_chmod else os.chmod),
                    patch.object(os, "supports_fd", os.supports_fd | {observe}),
                ):
                    self.assertEqual(self.change(), 0o600)
                self.assertEqual(len(calls), 1)
                self.assertClosed(calls[0][0])
                self.assertEqual(calls[0][1], 0o600)
                self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
                self.target.chmod(0o400)

    def test_fd_chmod_rebinding_keeps_selected_rollback_callable(self) -> None:
        native = os.chmod
        calls: list[tuple[int, int]] = []

        def rebound(_descriptor: int, _mode: int) -> None:
            self.fail("rollback must retain the originally selected callable")

        def observe(descriptor: int, mode: int) -> None:
            native(descriptor, mode)
            calls.append((descriptor, mode))
            if len(calls) == 1:
                os.link(self.target, self.root / "alias")
                rebinding.enter_context(patch.object(os, "chmod", rebound))

        with (
            patch.object(os, "fchmod", None),
            patch.object(os, "chmod", observe),
            patch.object(os, "supports_fd", os.supports_fd | {observe}),
            ExitStack() as rebinding,
            self.assertRaisesRegex(OSError, "transaction file changed") as raised,
        ):
            self.change()
        self.assertClosed(calls[0][0])
        self.assertEqual(calls, [(calls[0][0], 0o600), (calls[0][0], 0o400)])
        self.assertFalse(hasattr(raised.exception, "__notes__"))
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o400)

    def test_noop_and_expected_mode_guard_precedence(self) -> None:
        with patch.object(self.directory, "open_file", side_effect=AssertionError("must not open")):
            self.assertEqual(self.directory.chmod_exact(
                "artifact", self.identity, 0o400, expected_current_mode=0o600,
            ), 0o400)
            with self.assertRaisesRegex(OSError, "file mode changed"):
                self.directory.chmod_exact("artifact", self.identity, 0o600, expected_current_mode=0o200)

    def test_descriptor_failures_preserve_errors_and_close(self) -> None:
        native_chmod, native_close = os.fchmod, os.close
        for phase in ("immediate", "restore", "cancel_restore", "close"):
            with self.subTest(phase=phase):
                calls: list[int] = []
                failure = KeyboardInterrupt("cancel restore") if phase == "cancel_restore" else OSError(phase)

                def observe(
                    descriptor: int, mode: int, *, calls: list[int] = calls,
                    phase: str = phase, failure: BaseException = failure,
                ) -> None:
                    calls.append(descriptor)
                    if phase == "immediate" or len(calls) == 2:
                        raise failure
                    native_chmod(descriptor, mode)
                    os.link(self.target, self.root / "alias")

                def close(descriptor: int, *, phase: str = phase, failure: BaseException = failure) -> None:
                    native_close(descriptor)
                    if phase == "close":
                        raise failure

                with (
                    patch.object(os, "fchmod", observe),
                    patch.object(os, "close", close),
                    self.assertRaises(BaseException) as raised,
                ):
                    self.change()
                self.assertClosed(calls[0])
                if phase == "restore":
                    self.assertIsInstance(raised.exception, OSError)
                    self.assertIn("transaction file changed", str(raised.exception))
                    self.assertEqual(len(raised.exception.__notes__), 1)
                    self.assertIn("boundary change: restore", raised.exception.__notes__[0])
                else:
                    self.assertIs(raised.exception, failure)
                (self.root / "alias").unlink(missing_ok=True)
                self.target.chmod(0o400)
