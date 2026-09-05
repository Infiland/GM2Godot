"""Public conversion signal lifecycle characterized before session extraction."""
from __future__ import annotations

import io
import signal
import tempfile
import threading
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import FrameType
from typing import Literal
from unittest.mock import patch

from src import cli
from src.cli_session import ConversionSession
from tests.cli_test_support import OutcomeConverterStub, success_outcome


class TestCLIConversionSessionEntry(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.arguments = [
            "convert", "--gm-project", str(Path(self.directory.name, "gm")),
            "--godot-project", str(Path(self.directory.name, "out")),
        ]

    def test_worker_conversion_never_installs_or_restores_process_signal(self) -> None:
        converter = OutcomeConverterStub(success_outcome())
        results: list[int] = []
        failures: list[BaseException] = []

        def run_conversion() -> None:
            try:
                results.append(cli.main(self.arguments))
            except BaseException as error:
                failures.append(error)

        previous = signal.getsignal(signal.SIGINT)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("src.cli.Converter", side_effect=converter.bind_factory),
            patch("signal.signal", wraps=signal.signal) as install,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            worker = threading.Thread(target=run_conversion)
            worker.start()
            worker.join()
        self.assertEqual(failures, [])
        self.assertEqual(results, [0])
        install.assert_not_called()
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertIsNotNone(converter.conversion_running)
        self.assertEqual(stdout.getvalue(), converter.outcome.summary_line() + "\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_install_failure_before_or_after_assignment_keeps_fallback_restore(self) -> None:
        for assign_first in (False, True):
            with self.subTest(assign_first=assign_first):
                self._assert_install_failure(assign_first)

    def _assert_install_failure(self, assign_first: bool) -> None:
        original = signal.signal
        previous = signal.getsignal(signal.SIGINT)
        failure = OSError("signal install failed")
        calls: list[bool] = []

        def fail_install(
            signum: int,
            handler: Callable[[int, FrameType | None], object] | int | None,
        ) -> Callable[[int, FrameType | None], object] | int | None:
            calls.append(handler is previous)
            if len(calls) == 1:
                if assign_first:
                    original(signum, handler)
                raise failure
            return original(signum, handler)

        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with (
                patch("signal.signal", side_effect=fail_install),
                patch("src.cli.Converter") as factory,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(OSError) as raised,
            ):
                cli.main(self.arguments)
            self.assertIs(raised.exception, failure)
            self.assertEqual(calls, [False, True])
            factory.assert_not_called()
            self.assertEqual(signal.getsignal(signal.SIGINT), previous)
            self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
        finally:
            original(signal.SIGINT, previous)

    def test_sequential_conversions_have_independent_live_cancellation_events(self) -> None:
        first = OutcomeConverterStub(success_outcome(), on_convert=lambda: signal.raise_signal(signal.SIGINT))
        second = OutcomeConverterStub(success_outcome())
        previous = signal.getsignal(signal.SIGINT)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with patch("src.cli.Converter", side_effect=first.bind_factory):
                first_exit = cli.main(self.arguments)
            self.assertEqual(signal.getsignal(signal.SIGINT), previous)
            with patch("src.cli.Converter", side_effect=second.bind_factory):
                second_exit = cli.main(self.arguments)
        first_event, second_event = first.conversion_running, second.conversion_running
        assert first_event is not None and second_event is not None
        self.assertIsNot(first_event, second_event)
        self.assertFalse(first_event.is_set())
        self.assertTrue(second_event.is_set())
        self.assertEqual((first_exit, second_exit), (130, 0))
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 2)
        self.assertIn("GM2Godot conversion outcome: cancelled", stdout.getvalue())
        self.assertTrue(stdout.getvalue().endswith(second.outcome.summary_line() + "\n"))
        self.assertEqual(stderr.getvalue(), "")

    def test_nested_conversion_restores_outer_handler_without_cancelling_outer_event(self) -> None:
        inner = OutcomeConverterStub(success_outcome(), on_convert=lambda: signal.raise_signal(signal.SIGINT))
        inner_results: list[int] = []
        handler_restored: list[bool] = []

        def run_inner() -> None:
            outer_handler = signal.getsignal(signal.SIGINT)
            with patch("src.cli.Converter", side_effect=inner.bind_factory):
                inner_results.append(cli.main(self.arguments))
            handler_restored.append(signal.getsignal(signal.SIGINT) is outer_handler)

        outer = OutcomeConverterStub(success_outcome(), on_convert=run_inner)
        previous = signal.getsignal(signal.SIGINT)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("src.cli.Converter", side_effect=outer.bind_factory),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            outer_exit = cli.main(self.arguments)
        inner_event, outer_event = inner.conversion_running, outer.conversion_running
        assert inner_event is not None and outer_event is not None
        self.assertFalse(inner_event.is_set())
        self.assertTrue(outer_event.is_set())
        self.assertIsNot(inner_event, outer_event)
        self.assertEqual(inner_results, [130])
        self.assertEqual(handler_restored, [True])
        self.assertEqual(outer_exit, 0)
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual(stdout.getvalue().count("GM2Godot conversion outcome:"), 2)
        self.assertTrue(stdout.getvalue().endswith(outer.outcome.summary_line() + "\n"))
        self.assertEqual(stderr.getvalue(), "")


class TestCLIConversionSessionModel(unittest.TestCase):
    def test_each_session_owns_a_fresh_preparing_interrupt_type(self) -> None:
        first, second = ConversionSession(), ConversionSession()
        self.assertIsNot(first.running, second.running)
        self.assertIsNot(first.terminal_summary_interrupted, second.terminal_summary_interrupted)
        self.assertEqual(first.terminal_summary_interrupted.__name__, "_TerminalSummaryInterrupted")
        first.terminal_summary_phase = "preparing"
        second.terminal_summary_phase = "preparing"
        with self.assertRaises(first.terminal_summary_interrupted) as first_error:
            first.request_cancellation(signal.SIGINT, None)
        with self.assertRaises(second.terminal_summary_interrupted) as second_error:
            second.request_cancellation(signal.SIGINT, None)
        self.assertNotIsInstance(first_error.exception, second.terminal_summary_interrupted)
        self.assertNotIsInstance(second_error.exception, first.terminal_summary_interrupted)
        self.assertFalse(first.running.is_set())
        self.assertFalse(second.running.is_set())

    def test_decided_or_committing_states_ignore_interrupts_but_active_second_raises(self) -> None:
        phases: tuple[Literal["committing", "committed"], ...] = ("committing", "committed")
        for phase in phases:
            with self.subTest(phase=phase):
                session = ConversionSession()
                session.terminal_summary_phase = phase
                session.request_cancellation(signal.SIGINT, None)
                self.assertTrue(session.running.is_set())
                self.assertFalse(session.sigint_received)
        session = ConversionSession()
        session.managed_generation_decided = True
        session.request_cancellation(signal.SIGINT, None)
        self.assertTrue(session.running.is_set())
        self.assertFalse(session.sigint_received)
        session.managed_generation_decided = False
        session.request_cancellation(signal.SIGINT, None)
        self.assertFalse(session.running.is_set())
        with self.assertRaises(KeyboardInterrupt):
            session.request_cancellation(signal.SIGINT, None)

    def test_normal_and_fallback_restore_keep_distinct_flag_contracts(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        original = signal.signal
        try:
            normal = ConversionSession()
            normal.install_sigint_handler()
            with patch("signal.signal", wraps=original) as calls:
                normal.restore_sigint_handler()
                normal.restore_sigint_handler()
            calls.assert_called_once_with(signal.SIGINT, previous)
            self.assertTrue(normal.sigint_handler_restored)
            self.assertEqual(signal.getsignal(signal.SIGINT), previous)
            fallback = ConversionSession()
            fallback.install_sigint_handler()
            fallback.restore_sigint_handler_fallback()
            self.assertFalse(fallback.sigint_handler_restored)
            self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        finally:
            original(signal.SIGINT, previous)
