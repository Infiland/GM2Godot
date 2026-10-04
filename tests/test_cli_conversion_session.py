"""Borrowed event, live signal operations and session owner boundaries."""

from __future__ import annotations

import ast
import signal
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src import cli, cli_conversion_session as sessions
from src.conversion.conversion_outcome import ConversionOutcome


class _TerminalInterrupted(Exception):
    pass


class _PhaseValues:
    def __init__(self, running: threading.Event, phase: str = "idle") -> None:
        self.running = running
        self.phase = phase
        self.reads: list[tuple[str, bool]] = []

    @property
    def terminal_summary_phase(self) -> str:
        self.reads.append((self.phase, self.running.is_set()))
        return self.phase


class TestCLIConversionSession(unittest.TestCase):
    def test_borrowed_event_live_phase_and_generation_cutoff(self) -> None:
        running = threading.Event()
        running.set()
        values = _PhaseValues(running)
        operations: sessions.SignalOperations = cli.CLISignalOperations()
        session = sessions.ConversionSession(
            running, signal.SIG_DFL, False, values, operations, _TerminalInterrupted
        )
        self.assertIs(session.running, running)
        self.assertEqual(values.reads, [])
        session.request_cancellation(signal.SIGINT, None)
        self.assertTrue(session.sigint_received)
        self.assertFalse(running.is_set())
        self.assertEqual(values.reads, [("idle", True), ("idle", False)])
        current = ConversionOutcome(state="success")
        observed = session.observe_cancellation(current)
        self.assertEqual(observed.state, "cancelled")
        self.assertEqual(current.state, "success")
        self.assertIs(session.observe_cancellation(observed), observed)
        with self.assertRaises(KeyboardInterrupt):
            session.request_cancellation(signal.SIGINT, None)

        running.set()
        values.phase = "committing"
        session.request_cancellation(signal.SIGINT, None)
        self.assertTrue(running.is_set())
        values.phase = "idle"
        session.managed_generation_decided = True
        reads_before = list(values.reads)
        session.request_cancellation(signal.SIGINT, None)
        self.assertEqual(values.reads, reads_before)
        self.assertTrue(running.is_set())
        self.assertIs(session.observe_cancellation(current), current)

        preparing_running = threading.Event()
        preparing_running.set()
        preparing_values = _PhaseValues(preparing_running, "preparing")
        preparing = sessions.ConversionSession(
            preparing_running, signal.SIG_DFL, False,
            preparing_values, operations, _TerminalInterrupted,
        )
        with self.assertRaises(_TerminalInterrupted):
            preparing.request_cancellation(signal.SIGINT, None)
        self.assertTrue(preparing.sigint_received)
        self.assertFalse(preparing_running.is_set())
        self.assertEqual(
            preparing_values.reads, [("preparing", True), ("preparing", False)]
        )

    def test_late_native_signal_binding_and_distinct_restoration_paths(self) -> None:
        self.assertIs(threading.current_thread(), threading.main_thread())
        original_set = signal.signal
        original_get = signal.getsignal
        previous: sessions.SignalHandler = original_get(signal.SIGINT)
        running = threading.Event()
        running.set()
        values = _PhaseValues(running)
        operations: sessions.SignalOperations = cli.CLISignalOperations()
        session = sessions.ConversionSession(
            running, previous, True, values, operations, _TerminalInterrupted
        )
        calls: list[str] = []

        def late_install(signum: int, handler: sessions.SignalHandler) -> sessions.SignalHandler:
            calls.append("late install")
            return original_set(signum, handler)

        def restore_then_interrupt(signum: int, handler: sessions.SignalHandler) -> sessions.SignalHandler:
            calls.append("late restore")
            original_set(signum, handler)
            raise KeyboardInterrupt

        try:
            # Construct before patching; the actual native setter is called by
            # the replacement binding and stores the real owner method.
            with patch.object(cli.signal, "signal", side_effect=late_install):
                session.install_sigint_handler()
            self.assertEqual(calls, ["late install"])
            self.assertEqual(original_get(signal.SIGINT), session.request_cancellation)
            values.phase = "committed"
            with (
                patch.object(cli.signal, "signal", side_effect=restore_then_interrupt),
                patch.object(cli.signal, "getsignal", wraps=original_get) as get_current,
            ):
                session.restore_sigint_handler()
                get_current.assert_called_once_with(signal.SIGINT)
            self.assertTrue(session.sigint_handler_restored)
            self.assertIs(original_get(signal.SIGINT), previous)

            fallback = sessions.ConversionSession(
                running, previous, True, values, operations, _TerminalInterrupted
            )
            with (
                patch.object(cli.signal, "signal", side_effect=restore_then_interrupt),
                patch.object(cli.signal, "getsignal", side_effect=AssertionError("finally does not query")),
            ):
                fallback.finally_restore_sigint_handler()
            self.assertFalse(fallback.sigint_handler_restored)
            self.assertIs(original_get(signal.SIGINT), previous)

            disabled = sessions.ConversionSession(
                running, previous, False, values, operations, _TerminalInterrupted
            )
            with (
                patch.object(cli.signal, "signal", side_effect=AssertionError("captured false flag")),
                patch.object(cli.signal, "getsignal", side_effect=AssertionError("captured false flag")),
            ):
                disabled.install_sigint_handler()
                disabled.restore_sigint_handler()
                disabled.finally_restore_sigint_handler()
        finally:
            original_set(signal.SIGINT, previous)

    def test_session_import_boundary_and_driver_trace_windows(self) -> None:
        allowed = {"src.conversion.conversion_outcome"}

        def project_edges(source: str) -> set[str]:
            edges: set[str] = set()
            for node in ast.walk(ast.parse(source)):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level or node.module is None or any(alias.name == "*" for alias in node.names):
                        raise AssertionError("Relative or wildcard session import")
                    names = [node.module]
                for name in names:
                    if name.split(".", 1)[0] in sys.stdlib_module_names:
                        continue
                    if name not in allowed:
                        raise AssertionError("Session owner backedge: " + name)
                    edges.add(name)
            return edges

        self.assertEqual(project_edges(Path(sessions.__file__).read_text()), allowed)
        for forbidden in (
            "from src import cli",
            "def later():\n    from src import cli\n",
            "from src.cli_report_lifecycle import ConversionReportLifecycle",
            "from src.conversion.converter import Converter",
            "from src.conversion.conversion_outcome import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_edges(forbidden)

        source = Path(cli.__file__).read_text()
        driver = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "_run_convert"
        )
        text = ast.get_source_segment(source, driver)
        assert text is not None
        self.assertIn('terminal_summary_phase = "preparing"\n                observed = observe_cancellation(outcome)', text)
        self.assertIn("restore_sigint_handler()\n            return exit_code", text)
        self.assertEqual(text.count("sys.stdout.write(summary_output)"), 1)


if __name__ == "__main__":
    unittest.main()
