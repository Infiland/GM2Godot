from __future__ import annotations

# pyright: reportPrivateUsage=false

import base64
import errno
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest.mock import patch

from src import cli
from src.conversion import godot_validation as godot_validation_module
from src.conversion.godot_validation import (
    GODOT_VALIDATION_REPORT_RELATIVE_PATH,
    detect_godot_output_issues,
    find_godot_binary,
    generated_godot_importable_asset_paths,
    generated_godot_resource_paths,
    _run_godot_command,
    validate_generated_godot_project,
)


_PNG_1X1_WHITE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
    "////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
)


class _ModuleBindingProxy:
    def __init__(self, original: ModuleType, **overrides: object) -> None:
        self._original = original
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._original, name)


class _PipeBackedProcess:
    def __init__(
        self,
        output: bytes,
        *,
        timeout_on_first_wait: bool = False,
        keep_writer_open: bool = False,
    ) -> None:
        read_fd, write_fd = os.pipe()
        try:
            self._write_all(write_fd, output)
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise

        self._write_fd = write_fd if keep_writer_open else None
        if not keep_writer_open:
            os.close(write_fd)

        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.args = ["fake-godot"]
        self.pid = 1
        self.returncode: int | None = None
        self._timeout_on_first_wait = timeout_on_first_wait
        self._wait_calls = 0
        self.kill_calls: int = 0
        self._observed_exit = False

    def observe_exit(self, *, deadline: float) -> None:
        if self._timeout_on_first_wait:
            self._timeout_on_first_wait = False
            raise subprocess.TimeoutExpired(self.args, max(0, deadline - time.monotonic()))
        self._observed_exit = True

    def wait(self, timeout: float | None = None) -> int:
        self._wait_calls += 1
        if self._timeout_on_first_wait and self._wait_calls == 1:
            if timeout is None:
                raise AssertionError("the first fake wait must be bounded")
            raise subprocess.TimeoutExpired(["fake-godot"], timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        if self.returncode is None and not self._observed_exit:
            self.returncode = -9

    @staticmethod
    def _write_all(write_fd: int, output: bytes) -> None:
        remaining = memoryview(output)
        while remaining:
            written = os.write(write_fd, remaining)
            remaining = remaining[written:]

    def write_output(self, output: bytes) -> None:
        if self._write_fd is None:
            raise AssertionError("the fake output writer is closed")
        self._write_all(self._write_fd, output)

    def close_stdout(self) -> None:
        if self._write_fd is not None:
            os.close(self._write_fd)
            self._write_fd = None
        if not self.stdout.closed:
            self.stdout.close()


def _ignore_killpg(_pid: int, _signal: int) -> None:
    pass


def _observe_fake_process_exit(
    process: _PipeBackedProcess,
    *,
    deadline: float,
    cleanup_errors: list[tuple[str, BaseException]] | None = None,
) -> None:
    del cleanup_errors
    process.observe_exit(deadline=deadline)


def _prove_fake_process_ownership(_process: _PipeBackedProcess) -> None:
    pass


def _popen_returning(
    process: _PipeBackedProcess,
) -> Callable[..., _PipeBackedProcess]:
    def fake_popen(*_args: object, **_kwargs: object) -> _PipeBackedProcess:
        return process

    return fake_popen


class _DeferredTargetThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
    ) -> None:
        self._target = target
        self._gate = threading.Event()
        self._join_calls = 0
        self._thread = threading.Thread(
            target=self._run_after_release,
            name=name,
            daemon=daemon,
        )

    def _run_after_release(self) -> None:
        self._gate.wait()
        self._target()

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._join_calls += 1
        if self._join_calls == 1:
            return
        self._gate.set()
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def release(self) -> None:
        self._gate.set()
        self._thread.join(timeout=1.0)


class _SynchronousTargetThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
    ) -> None:
        del name, daemon
        self._target = target

    def start(self) -> None:
        self._target()

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def is_alive(self) -> bool:
        return False

    def release(self) -> None:
        pass


class _DeadlineBlockedTargetThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
    ) -> None:
        self._target = target
        self._gate = threading.Event()
        self._join_calls = 0
        self._thread = threading.Thread(
            target=self._run_after_release,
            name=name,
            daemon=daemon,
        )

    def _run_after_release(self) -> None:
        self._gate.wait()
        self._target()

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        del timeout
        self._join_calls += 1

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def join_calls(self) -> int:
        return self._join_calls

    def release(self) -> None:
        self._gate.set()
        self._thread.join(timeout=1.0)


class _WaitArrivalStopEvent:
    def __init__(self) -> None:
        self.wait_entered = threading.Event()
        self._event = threading.Event()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, _timeout: float | None = None) -> bool:
        self.wait_entered.set()
        return self._event.wait(timeout=1.0)

    def set(self) -> None:
        self._event.set()


class _WriteDuringWaitThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
        stop_event: _WaitArrivalStopEvent,
        buffer_output: Callable[[], None],
    ) -> None:
        self._stop_event = stop_event
        self._buffer_output = buffer_output
        self._join_calls = 0
        self._thread = threading.Thread(target=target, name=name, daemon=daemon)

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._join_calls += 1
        if self._join_calls == 1:
            if not self._stop_event.wait_entered.wait(timeout=1.0):
                raise AssertionError("the output reader did not enter its poll wait")
            self._buffer_output()
            return
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def release(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)


class _OwnedFakeProcess(_PipeBackedProcess):
    def __init__(
        self,
        output: bytes,
        *,
        returncode: int = -11,
        observer_error: BaseException | None = None,
        kill_error: BaseException | None = None,
        reap_error: BaseException | None = None,
        observer_close_error: BaseException | None = None,
    ) -> None:
        super().__init__(output)
        self.pid = 43210
        self.expected_returncode = returncode
        self.observer_error = observer_error
        self.kill_error = kill_error
        self.reap_error = reap_error
        self.observer_close_error = observer_close_error
        self.events: list[str] = []
        self.wait_timeouts: list[float] = []

    def observe_exit(self, *, deadline: float) -> None:
        del deadline
        self.events.append("observe")
        if self.observer_error is not None:
            raise self.observer_error
        self._observed_exit = True

    def kill(self) -> None:
        self.events.append("direct-signal")
        self.kill_calls += 1
        if self.kill_error is not None:
            raise self.kill_error
        self.returncode = self.expected_returncode if self._observed_exit else -9

    def poll(self) -> int | None:
        raise AssertionError("ownership must not be inferred by polling")

    def wait(self, timeout: float | None = None) -> int:
        if timeout is None:
            raise AssertionError("every reap must be bounded")
        self.wait_timeouts.append(timeout)
        self.events.append("reap")
        if self.reap_error is not None:
            raise self.reap_error
        if self.returncode is None:
            self.returncode = self.expected_returncode
        return self.returncode


class _OwnedDeferredThread(_DeferredTargetThread):
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
        events: list[str],
    ) -> None:
        super().__init__(target=target, name=name, daemon=daemon)
        self._events = events

    def join(self, timeout: float | None = None) -> None:
        self._events.append("reader-drain" if self._join_calls == 0 else "reader-stop")
        super().join(timeout)


class _InterruptedStartThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        name: str,
        daemon: bool,
        start_error: BaseException,
    ) -> None:
        self._thread = threading.Thread(target=target, name=name, daemon=daemon)
        self._start_error = start_error

    def start(self) -> None:
        raise self._start_error

    def join(self, timeout: float | None = None) -> None:
        del timeout
        raise RuntimeError("cannot join thread before it is started")

    def is_alive(self) -> bool:
        return False

    def release(self) -> None:
        # A native worker may reach its target after Thread.start was
        # interrupted while waiting for the bootstrap handshake.
        self._thread.start()
        self._thread.join(timeout=1.0)


@dataclass
class _FakeProcessEvent:
    ident: int
    filter: int
    flags: int
    fflags: int
    data: int = 0


class _FakeProcessQueue:
    def __init__(
        self,
        *,
        registration_error: BaseException | None = None,
        close_error: BaseException | None = None,
        events: tuple[_FakeProcessEvent, ...] = (),
    ) -> None:
        self.registration_error = registration_error
        self.close_error = close_error
        self.events = events
        self.calls: list[tuple[bool, int, float | None]] = []
        self.closed = False

    def control(
        self,
        changes: list[_FakeProcessEvent] | None,
        max_events: int,
        timeout: float | None = None,
    ) -> list[_FakeProcessEvent]:
        self.calls.append((changes is not None, max_events, timeout))
        if changes is not None:
            if self.registration_error is not None:
                raise self.registration_error
            return []
        return list(self.events)

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class TestGodotProcessOwnership(unittest.TestCase):
    def _run_fake(
        self,
        process: _OwnedFakeProcess,
        *,
        group_error: BaseException | None = None,
        blocked_reader: bool = False,
        read_error: OSError | None = None,
        setup_error: BaseException | None = None,
        ownership_error: BaseException | None = None,
        ownership_error_after_group: BaseException | None = None,
        start_error: BaseException | None = None,
        before_reader_release: Callable[[], None] | None = None,
        finished_reader: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.addCleanup(process.close_stdout)
        readers: list[
            _DeferredTargetThread | _DeadlineBlockedTargetThread | _InterruptedStartThread | _SynchronousTargetThread
        ] = []

        def signal_group(_pid: int, _signal: int) -> None:
            self.assertIsNone(process.returncode, "never signal a reaped PGID")
            process.events.append("group-signal")
            if group_error is not None:
                raise group_error

        def make_reader(
            *, target: Callable[[], None], name: str, daemon: bool
        ) -> _DeferredTargetThread | _DeadlineBlockedTargetThread | _InterruptedStartThread | _SynchronousTargetThread:
            if finished_reader:
                reader = _SynchronousTargetThread(target=target, name=name, daemon=daemon)
            elif start_error is not None:
                reader = _InterruptedStartThread(target=target, name=name, daemon=daemon, start_error=start_error)
            elif blocked_reader:
                reader = _DeadlineBlockedTargetThread(target=target, name=name, daemon=daemon)
            else:
                reader = _OwnedDeferredThread(target=target, name=name, daemon=daemon, events=process.events)
            readers.append(reader)
            return reader

        def read(fd: int, size: int) -> bytes:
            if read_error is not None:
                raise read_error
            return os.read(fd, size)

        def set_blocking(fd: int, blocking: bool) -> None:
            if setup_error is not None:
                raise setup_error
            os.set_blocking(fd, blocking)

        original_signal = godot_validation_module.signal

        def child_policy(signum: int) -> object:
            if os.name != "posix" and original_signal is signal:
                return signal.SIG_DFL
            return original_signal.getsignal(signum)

        def observe(
            owned_process: _PipeBackedProcess,
            *,
            deadline: float,
            cleanup_errors: list[tuple[str, BaseException]],
        ) -> None:
            try:
                owned_process.observe_exit(deadline=deadline)
            finally:
                if process.observer_close_error is not None:
                    cleanup_errors.append(("exit-observer close", process.observer_close_error))

        def prove(_owned_process: _PipeBackedProcess) -> None:
            if ownership_error is not None:
                raise ownership_error
            if ownership_error_after_group is not None and "group-signal" in process.events:
                raise ownership_error_after_group

        try:
            with (
                patch.object(
                    godot_validation_module,
                    "os",
                    _ModuleBindingProxy(os, name="posix", killpg=signal_group, read=read, set_blocking=set_blocking),
                ),
                patch.object(
                    godot_validation_module,
                    "signal",
                    _ModuleBindingProxy(
                        original_signal,
                        getsignal=child_policy,
                        SIGCHLD=getattr(signal, "SIGCHLD", 17),
                    ),
                ),
                patch.object(
                    godot_validation_module,
                    "subprocess",
                    _ModuleBindingProxy(subprocess, Popen=_popen_returning(process)),
                ),
                patch.object(
                    godot_validation_module,
                    "threading",
                    _ModuleBindingProxy(threading, Thread=make_reader),
                ),
                patch.object(
                    godot_validation_module,
                    "_wait_godot_process_exit",
                    side_effect=observe,
                ),
                patch.object(godot_validation_module, "_prove_godot_process_ownership", side_effect=prove),
            ):
                return _run_godot_command(["fake-godot"], timeout=1)
        finally:
            if before_reader_release is not None:
                before_reader_release()
            for reader in readers:
                reader.release()

    def test_completed_leader_cleanup_eperm_preserves_crash_diagnostics(self) -> None:
        diagnostic = (
            b"WARNING: original engine warning\n"
            b"SCRIPT ERROR: original engine error\n"
            b"CrashHandler: SIGSEGV engine backtrace\n"
        )
        process = _OwnedFakeProcess(diagnostic)
        result = self._run_fake(process, group_error=PermissionError(errno.EPERM, "group permission denied"))
        self.assertEqual(result.returncode, -11)
        self.assertIn(diagnostic.decode(), result.stdout)
        self.assertIn("ERROR: GM2Godot process-group cleanup failed", result.stdout)
        self.assertEqual(
            process.events,
            ["observe", "reader-drain", "group-signal", "direct-signal", "reap", "reader-stop"],
        )
        self.assertTrue(process.wait_timeouts)
        self.assertTrue(all(timeout <= 1.0 for timeout in process.wait_timeouts))
        self.assertEqual(len(detect_godot_output_issues(result.stdout)), 3)

    def test_timeout_live_group_eperm_preserves_timeout_and_fails_validation(self) -> None:
        process = _OwnedFakeProcess(
            b"ENGINE CONTEXT BEFORE TIMEOUT\n",
            observer_error=subprocess.TimeoutExpired(["fake-godot"], 1),
        )
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self._run_fake(
                process,
                group_error=PermissionError(errno.EPERM, "live group was not killed"),
            )
        self.assertEqual(raised.exception.timeout, 1)
        output = str(raised.exception.output)
        self.assertIn("ENGINE CONTEXT BEFORE TIMEOUT", output)
        self.assertIn("live group was not killed", output)
        self.assertIn("ERROR: GM2Godot", output)
        self.assertEqual(process.events[:3], ["observe", "group-signal", "direct-signal"])
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "project.godot").write_text("[application]\n", encoding="utf-8")
            executable = project / "fake-godot"
            executable.touch()
            with patch.object(
                godot_validation_module,
                "_run_godot_import",
                side_effect=raised.exception,
            ):
                report = validate_generated_godot_project(directory, godot_binary=str(executable), load_resources=False)
        self.assertEqual(report.status, "failed")
        self.assertIn("live group was not killed", report.output)

    def test_lost_child_ownership_never_signals_group_or_direct_pid(self) -> None:
        error = ChildProcessError(errno.ECHILD, "owned child was externally reaped")
        process = _OwnedFakeProcess(b"WARNING: retained after lost ownership\n", observer_error=error)
        with self.assertRaises(ChildProcessError) as raised:
            self._run_fake(process)
        self.assertIs(raised.exception, error)
        self.assertNotIn("group-signal", process.events)
        self.assertNotIn("direct-signal", process.events)
        self.assertEqual(process.kill_calls, 0)
        self.assertIn("retained after lost ownership", "\n".join(error.__notes__))

    def test_already_reaped_leader_never_signals_reusable_pid(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        process.returncode = -11

        def forbidden_signal(_pid: int, _signal: int) -> None:
            raise AssertionError("a reaped PGID may belong to another process")

        with patch.object(
            godot_validation_module,
            "os",
            _ModuleBindingProxy(os, name="posix", killpg=forbidden_signal),
        ):
            godot_validation_module._kill_godot_process(cast(subprocess.Popen[bytes], process))
        self.assertEqual(process.events, [])

    def test_ownership_proof_failure_never_falls_back_to_a_stale_pid(self) -> None:
        for error in (
            ChildProcessError(errno.ECHILD, "ownership probe found no child"),
            PermissionError(errno.EPERM, "ownership probe denied"),
            RuntimeError("ownership probe unavailable"),
        ):
            with self.subTest(error=error):
                process = _OwnedFakeProcess(b"WARNING: captured before failed proof\n")
                if isinstance(error, ChildProcessError):
                    with self.assertRaises(ChildProcessError) as raised:
                        self._run_fake(process, ownership_error=error)
                    self.assertIs(raised.exception, error)
                    output = "\n".join(error.__notes__)
                else:
                    output = self._run_fake(process, ownership_error=error).stdout
                self.assertNotIn("group-signal", process.events)
                self.assertNotIn("direct-signal", process.events)
                self.assertIn("captured before failed proof", output)
                if not isinstance(error, ChildProcessError):
                    self.assertIn(str(error), output)
        lost_error = ChildProcessError(errno.ECHILD, "child lost after group attempt")
        process = _OwnedFakeProcess(b"WARNING: captured before direct fallback\n")
        with self.assertRaises(ChildProcessError) as raised:
            self._run_fake(
                process,
                group_error=PermissionError(errno.EPERM, "group cleanup denied"),
                ownership_error_after_group=lost_error,
            )
        self.assertIs(raised.exception, lost_error)
        self.assertNotIn("direct-signal", process.events)
        self.assertIn("group cleanup denied", "\n".join(lost_error.__notes__))

    def test_finished_reader_ownership_loss_does_not_fabricate_successful_reap(self) -> None:
        error = ChildProcessError(errno.ECHILD, "child reaped during reader drain")
        process = _OwnedFakeProcess(b"WARNING: already captured before lost reap\n")
        with self.assertRaises(ChildProcessError) as raised:
            self._run_fake(process, ownership_error=error, finished_reader=True)
        self.assertIs(raised.exception, error)
        self.assertNotIn("group-signal", process.events)
        self.assertNotIn("direct-signal", process.events)
        self.assertIn("already captured before lost reap", "\n".join(error.__notes__))

    def test_interrupted_reader_start_abandons_target_before_descriptor_reuse(self) -> None:
        for error in (KeyboardInterrupt("reader start interrupted"), SystemExit("reader start exited")):
            with self.subTest(error=error):
                process = _OwnedFakeProcess(b"")
                old_fd = process.stdout.fileno()
                replacement_fds: list[int] = []

                def reuse_descriptor() -> None:
                    self.assertTrue(process.stdout.closed)
                    read_fd, write_fd = os.pipe()
                    if read_fd != old_fd:
                        os.dup2(read_fd, old_fd)
                        os.close(read_fd)
                    os.set_blocking(old_fd, False)
                    replacement_fds.extend((old_fd, write_fd))
                    os.write(write_fd, b"fresh descriptor data must remain unread")

                try:
                    with self.assertRaises(type(error)) as raised:
                        self._run_fake(
                            process,
                            start_error=error,
                            before_reader_release=reuse_descriptor,
                        )
                    self.assertIs(raised.exception, error)
                    self.assertEqual(os.read(old_fd, 128), b"fresh descriptor data must remain unread")
                    self.assertIn("output capture failed", "\n".join(error.__notes__))
                    self.assertEqual(process.wait_timeouts, [1.0])
                finally:
                    for descriptor in replacement_fds:
                        os.close(descriptor)

    def test_observer_error_and_interrupt_preserve_identity_and_output(self) -> None:
        errors: tuple[BaseException, ...] = (
            OSError("observer failure"),
            KeyboardInterrupt("observer interruption"),
            SystemExit("observer exit"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                process = _OwnedFakeProcess(b"WARNING: engine output before observer failure\n", observer_error=error)
                with self.assertRaises(type(error)) as raised:
                    self._run_fake(process, group_error=PermissionError(errno.EPERM, "secondary cleanup failure"))
                self.assertIs(raised.exception, error)
                notes = "\n".join(error.__notes__)
                self.assertIn("engine output before observer failure", notes)
                self.assertIn("secondary cleanup failure", notes)
                self.assertIn("reap", process.events)
                self.assertIn("reader-stop", process.events)

    def test_observer_error_retains_secondary_capture_failure(self) -> None:
        error = RuntimeError("primary observer failure")
        process = _OwnedFakeProcess(b"", observer_error=error)
        with self.assertRaises(RuntimeError) as raised:
            self._run_fake(process, read_error=OSError("secondary read failure"))
        self.assertIs(raised.exception, error)
        notes = "\n".join(error.__notes__)
        self.assertIn("output capture failed", notes)
        self.assertIn("secondary read failure", notes)

    def test_independent_teardown_failures_keep_timeout_and_all_diagnostics(self) -> None:
        process = _OwnedFakeProcess(
            b"",
            observer_error=subprocess.TimeoutExpired(["fake-godot"], 1),
            kill_error=PermissionError(errno.EPERM, "direct child permission failure"),
            reap_error=subprocess.TimeoutExpired(["fake-godot"], 1),
        )
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self._run_fake(
                process,
                group_error=PermissionError(errno.EPERM, "group permission failure"),
                blocked_reader=True,
            )
        output = str(raised.exception.output)
        for detail in (
            "group permission failure",
            "direct child permission failure",
            "process reaping failed",
            "output capture failed",
            "Godot output reader did not stop",
        ):
            self.assertIn(detail, output)
        self.assertEqual(process.events, ["observe", "group-signal", "direct-signal", "reap"])
        self.assertEqual(process.wait_timeouts, [1.0])

    def test_reader_missed_deadline_snapshot_does_not_freeze_late_append(self) -> None:
        capture = godot_validation_module._BoundedGodotOutput(256)
        capture.append(b"SCRIPT ERROR: already captured before deadline\n")
        process = _OwnedFakeProcess(b"WARNING: late reader output\n")

        def existing_capture(_limit: int) -> godot_validation_module._BoundedGodotOutput:
            return capture

        with patch.object(godot_validation_module, "_BoundedGodotOutput", side_effect=existing_capture):
            result = self._run_fake(
                process,
                group_error=PermissionError(errno.EPERM, "cleanup failed"),
                blocked_reader=True,
            )
        self.assertIn("already captured before deadline", result.stdout)
        self.assertIn("Godot output reader did not stop", result.stdout)
        self.assertIn("late reader output", capture.snapshot())

    def test_snapshot_preserves_pending_issue_counts_without_finalizing(self) -> None:
        capture = godot_validation_module._BoundedGodotOutput(32)
        capture.append(b"head\n" + b"x" * 64 + b"\nERROR: omitted pending error" + b"x" * 64)
        first = capture.snapshot()
        self.assertEqual(first, capture.snapshot())
        self.assertIn("omitted 1 additional Godot error", first)
        capture.append(b"\nWARNING: final warning\n")
        final = capture.text()
        self.assertIn("omitted 1 additional Godot error", final)
        self.assertNotIn("omitted 2 additional Godot error", final)
        with self.assertRaisesRegex(RuntimeError, "capture is finished"):
            capture.append(b"must reject after finalization")

    def test_cleanup_diagnostics_are_bounded_and_start_on_fresh_lines(self) -> None:
        error = PermissionError("permission\n" + "x" * 10_000)
        error.add_note("direct failure\r\n" + "y" * 10_000)
        output = godot_validation_module._append_godot_cleanup_diagnostics(
            "unterminated engine line", [("process-group cleanup", error)]
        )
        self.assertTrue(output.startswith("unterminated engine line\nERROR:"))
        self.assertIn("direct failure", output)
        self.assertLess(len(output), 1300)
        self.assertEqual(len(output.splitlines()), 2)

    def test_non_default_sigchld_rejects_spawn_and_changed_policy_rejects_signals(self) -> None:
        def custom_handler(_signum: int, _frame: object) -> None:
            pass

        for disposition in (signal.SIG_IGN, custom_handler):
            with self.subTest(disposition=disposition):

                def policy(_signum: int) -> object:
                    return disposition

                with (
                    patch.object(godot_validation_module, "os", _ModuleBindingProxy(os, name="posix")),
                    patch.object(
                        godot_validation_module,
                        "signal",
                        _ModuleBindingProxy(signal, getsignal=policy, SIGCHLD=getattr(signal, "SIGCHLD", 17)),
                    ),
                    patch.object(godot_validation_module.subprocess, "Popen") as spawn,
                    self.assertRaises(ChildProcessError),
                ):
                    _run_godot_command(["must-not-spawn"], timeout=1)
                spawn.assert_not_called()

        process = _OwnedFakeProcess(b"WARNING: retained after changed signal policy\n")
        disposition = signal.SIG_DFL

        def changed_policy(_signum: int) -> object:
            return disposition

        with (
            patch.object(
                godot_validation_module,
                "signal",
                _ModuleBindingProxy(signal, getsignal=changed_policy, SIGCHLD=getattr(signal, "SIGCHLD", 17)),
            ),
        ):
            # _run_fake normally supplies its own observer, so replace the
            # owned fixture's observation method instead.
            original_observe = process.observe_exit

            def process_observe(*, deadline: float) -> None:
                nonlocal disposition
                original_observe(deadline=deadline)
                disposition = signal.SIG_IGN

            with patch.object(process, "observe_exit", side_effect=process_observe):
                with self.assertRaises(ChildProcessError) as raised:
                    self._run_fake(process)
        self.assertNotIn("group-signal", process.events)
        self.assertNotIn("direct-signal", process.events)
        self.assertIn("changed signal policy", "\n".join(raised.exception.__notes__))

    def test_missing_pipe_and_setup_interrupt_cleanup_are_bounded(self) -> None:
        process = _OwnedFakeProcess(b"")
        with patch.object(process, "stdout", None):
            with self.assertRaisesRegex(RuntimeError, "output pipe was not created"):
                self._run_fake(process)
        self.assertEqual(process.events, ["group-signal", "direct-signal", "reap"])
        self.assertEqual(process.wait_timeouts, [1.0])
        for error in (
            OSError("pipe setup failure"),
            KeyboardInterrupt("pipe setup interruption"),
            SystemExit("pipe setup exit"),
        ):
            with self.subTest(error=error):
                process = _OwnedFakeProcess(b"")
                with self.assertRaises(type(error)) as raised:
                    self._run_fake(process, setup_error=error)
                self.assertIs(raised.exception, error)
                self.assertEqual(process.events, ["group-signal", "direct-signal", "reap"])
                self.assertEqual(process.wait_timeouts, [1.0])

    def test_waitid_observation_is_non_reaping_and_uses_owned_pid(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        calls: list[tuple[int, int, int]] = []
        sleeps: list[float] = []

        def waitid(id_type: int, pid: int, options: int) -> object | None:
            calls.append((id_type, pid, options))
            return None if len(calls) == 1 else object()

        with (
            patch.object(
                godot_validation_module,
                "os",
                _ModuleBindingProxy(os, waitid=waitid, P_PID=1, WEXITED=2, WNOHANG=4, WNOWAIT=8),
            ),
            patch.object(
                godot_validation_module, "time", _ModuleBindingProxy(time, monotonic=lambda: 10.5, sleep=sleeps.append)
            ),
        ):
            godot_validation_module._wait_godot_process_exit(cast(subprocess.Popen[bytes], process), deadline=11.0)
        self.assertEqual(calls, [(1, process.pid, 14), (1, process.pid, 14)])
        self.assertEqual(sleeps, [0.01])
        self.assertIsNone(process.returncode)
        self.assertEqual(process.events, [])

    def test_waitid_deadline_and_lost_child_propagate_without_reaping(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        error = ChildProcessError(errno.ECHILD, "lost child")

        def absent_exit(_id_type: int, _pid: int, _options: int) -> None:
            return None

        def lost_exit(_id_type: int, _pid: int, _options: int) -> None:
            raise error

        for observer in (absent_exit, lost_exit):
            with self.subTest(observer=observer.__name__):
                with patch.object(
                    godot_validation_module,
                    "os",
                    _ModuleBindingProxy(os, waitid=observer, P_PID=1, WEXITED=2, WNOHANG=4, WNOWAIT=8),
                ):
                    with self.assertRaises(subprocess.TimeoutExpired if observer is absent_exit else ChildProcessError):
                        godot_validation_module._wait_godot_process_exit(
                            cast(subprocess.Popen[bytes], process), deadline=0
                        )
        self.assertEqual(process.events, [])

    def test_ownership_waitid_accepts_live_child_and_propagates_echild(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        calls: list[tuple[int, int, int]] = []
        error = ChildProcessError(errno.ECHILD, "no child")

        def live_child(id_type: int, pid: int, options: int) -> None:
            calls.append((id_type, pid, options))

        def missing_child(_id_type: int, _pid: int, _options: int) -> None:
            raise error

        def policy(_signum: int) -> object:
            return signal.SIG_DFL

        with patch.object(
            godot_validation_module,
            "signal",
            _ModuleBindingProxy(
                signal,
                getsignal=policy,
                SIGCHLD=getattr(signal, "SIGCHLD", 17),
            ),
        ):
            for observer in (live_child, missing_child):
                with patch.object(
                    godot_validation_module,
                    "os",
                    _ModuleBindingProxy(
                        os,
                        name="posix",
                        waitid=observer,
                        P_PID=1,
                        WEXITED=2,
                        WNOHANG=4,
                        WNOWAIT=8,
                    ),
                ):
                    if observer is live_child:
                        godot_validation_module._prove_godot_process_ownership(cast(subprocess.Popen[bytes], process))
                    else:
                        with self.assertRaises(ChildProcessError) as raised:
                            godot_validation_module._prove_godot_process_ownership(
                                cast(subprocess.Popen[bytes], process)
                            )
                        self.assertIs(raised.exception, error)
        self.assertEqual(calls, [(1, process.pid, 14)])
        self.assertIsNone(process.returncode)
        self.assertEqual(process.events, [])

    def test_darwin_ownership_binding_checks_platform_and_uses_runtime_constants(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)

        def policy(_signum: int) -> object:
            return signal.SIG_DFL

        with (
            patch.object(
                godot_validation_module,
                "os",
                _ModuleBindingProxy(
                    os,
                    name="posix",
                    waitid=None,
                    P_PID=1,
                    WEXITED=2,
                    WNOHANG=4,
                    WNOWAIT=8,
                ),
            ),
            patch.object(
                godot_validation_module,
                "signal",
                _ModuleBindingProxy(
                    signal,
                    getsignal=policy,
                    SIGCHLD=getattr(signal, "SIGCHLD", 17),
                ),
            ),
            patch.object(godot_validation_module, "sys", _ModuleBindingProxy(sys, platform="darwin")),
            patch.object(godot_validation_module, "_prove_darwin_godot_child") as native_probe,
        ):
            godot_validation_module._prove_godot_process_ownership(cast(subprocess.Popen[bytes], process))
        native_probe.assert_called_once_with(process.pid, 14)
        with (
            patch.object(godot_validation_module, "sys", _ModuleBindingProxy(sys, platform="unsupported")),
            patch.object(godot_validation_module.ctypes, "CDLL") as library,
            self.assertRaisesRegex(RuntimeError, "LP64 waitid ownership ABI"),
        ):
            godot_validation_module._prove_darwin_godot_child(process.pid, 14)
        library.assert_not_called()

    def test_kqueue_exit_registration_race_and_errors_are_bounded(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        expected_event = _FakeProcessEvent(process.pid, 1, 0, 8)
        cases: tuple[tuple[BaseException | None, tuple[_FakeProcessEvent, ...], type[BaseException] | None], ...] = (
            (None, (expected_event,), None),
            (ProcessLookupError(errno.ESRCH, "already exited"), (), None),
            (PermissionError(errno.EACCES, "cannot register"), (), PermissionError),
            (None, (), subprocess.TimeoutExpired),
            (None, (_FakeProcessEvent(process.pid, 1, 16, 8, errno.EPERM),), PermissionError),
        )
        for registration_error, events, expected_error in cases:
            with self.subTest(registration_error=registration_error, events=events):
                queue = _FakeProcessQueue(registration_error=registration_error, events=events)

                def make_queue() -> _FakeProcessQueue:
                    return queue

                with (
                    patch.object(godot_validation_module, "os", _ModuleBindingProxy(os, waitid=None)),
                    patch.object(
                        godot_validation_module,
                        "_prove_godot_process_ownership",
                        side_effect=_prove_fake_process_ownership,
                    ),
                    patch.object(
                        godot_validation_module,
                        "select",
                        _ModuleBindingProxy(
                            godot_validation_module.select,
                            kqueue=make_queue,
                            kevent=_FakeProcessEvent,
                            KQ_FILTER_PROC=1,
                            KQ_EV_ADD=2,
                            KQ_EV_ONESHOT=4,
                            KQ_NOTE_EXIT=8,
                            KQ_EV_ERROR=16,
                        ),
                    ),
                ):
                    if expected_error is None:
                        godot_validation_module._wait_godot_process_exit(
                            cast(subprocess.Popen[bytes], process), deadline=0
                        )
                    else:
                        with self.assertRaises(expected_error):
                            godot_validation_module._wait_godot_process_exit(
                                cast(subprocess.Popen[bytes], process), deadline=0
                            )
                self.assertTrue(queue.closed)
                self.assertEqual(queue.calls[0], (True, 0, 0))
                self.assertTrue(all(call[1] in (0, 1) and call[2] == 0 for call in queue.calls))
                self.assertIsNone(process.returncode)
        self.assertEqual(process.events, [])

    def test_kqueue_close_failure_preserves_observer_primary(self) -> None:
        process = _OwnedFakeProcess(b"")
        self.addCleanup(process.close_stdout)
        errors: tuple[BaseException | None, ...] = (
            OSError("primary observation error"),
            subprocess.TimeoutExpired(["fake-godot"], 1),
            KeyboardInterrupt("primary observation interruption"),
            SystemExit("primary observation exit"),
            None,
        )
        for error in errors:
            for close_error in (OSError("queue close failure"), KeyboardInterrupt("queue close interruption")):
                with self.subTest(error=error, close_error=close_error):
                    queue = _FakeProcessQueue(
                        registration_error=error,
                        close_error=close_error,
                        events=(_FakeProcessEvent(process.pid, 1, 0, 8),),
                    )

                    def make_queue() -> _FakeProcessQueue:
                        return queue

                    with (
                        patch.object(godot_validation_module, "os", _ModuleBindingProxy(os, waitid=None)),
                        patch.object(
                            godot_validation_module,
                            "_prove_godot_process_ownership",
                            side_effect=_prove_fake_process_ownership,
                        ),
                        patch.object(
                            godot_validation_module,
                            "select",
                            _ModuleBindingProxy(
                                godot_validation_module.select,
                                kqueue=make_queue,
                                kevent=_FakeProcessEvent,
                                KQ_FILTER_PROC=1,
                                KQ_EV_ADD=2,
                                KQ_EV_ONESHOT=4,
                                KQ_NOTE_EXIT=8,
                                KQ_EV_ERROR=16,
                            ),
                        ),
                        self.assertRaises(type(close_error if error is None else error)) as raised,
                    ):
                        godot_validation_module._wait_godot_process_exit(
                            cast(subprocess.Popen[bytes], process), deadline=0
                        )
                    self.assertIs(raised.exception, close_error if error is None else error)
                    if error is not None:
                        self.assertIn(str(close_error), "\n".join(error.__notes__))
                    self.assertTrue(queue.closed)
                    self.assertIsNone(process.returncode)

    def test_timeout_observer_close_note_reaches_validation_output(self) -> None:
        error = subprocess.TimeoutExpired(["fake-godot"], 1)
        process = _OwnedFakeProcess(
            b"ENGINE TIMEOUT CONTEXT\n",
            observer_error=error,
            observer_close_error=OSError("close failed"),
        )
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self._run_fake(process)
        self.assertIs(raised.exception, error)
        self.assertIn("ENGINE TIMEOUT CONTEXT", str(error.output))
        self.assertIn("close failed", str(error.output))

    @unittest.skipUnless(os.name == "posix", "requires isolated native SIGCHLD policy")
    def test_native_autoreaped_child_never_receives_a_stale_signal(self) -> None:
        script = "\n".join(
            (
                "import json, os, signal, subprocess, sys, time",
                "from unittest.mock import patch",
                "from src.conversion import godot_validation as module",
                "spawn = subprocess.Popen",
                "signals = []",
                "autoreaped = []",
                "original_policy = signal.getsignal(signal.SIGCHLD)",
                "def spawn_then_autoreap(*args, **kwargs):",
                "    process = spawn(*args, **kwargs)",
                "    signal.signal(signal.SIGCHLD, signal.SIG_IGN)",
                "    deadline = time.monotonic() + 2",
                "    while True:",
                "        try:",
                "            child, _status = os.waitpid(process.pid, os.WNOHANG)",
                "        except ChildProcessError:",
                "            autoreaped.append(True)",
                "            break",
                "        if child:",
                "            raise AssertionError('SIGCHLD ignored child should auto-reap')",
                "        if time.monotonic() >= deadline:",
                "            raise AssertionError('child did not auto-reap')",
                "        time.sleep(0.01)",
                "    signal.signal(signal.SIGCHLD, original_policy)",
                "    return process",
                "def signal_group(pid, sig):",
                "    signals.append(('group', pid))",
                "def signal_direct(process):",
                "    signals.append(('direct', process.pid))",
                "try:",
                "    with patch.object(module.subprocess, 'Popen', side_effect=spawn_then_autoreap), patch.object(module.os, 'killpg', side_effect=signal_group), patch.object(subprocess.Popen if isinstance(subprocess.Popen, type) else spawn, 'kill', signal_direct):",
                "        try:",
                "            module._run_godot_command([sys.executable, '-c', \"print('WARNING: autoreaped engine context', flush=True); raise SystemExit(23)\"], timeout=1)",
                "        except ChildProcessError as error:",
                "            print(json.dumps({'error': type(error).__name__, 'signals': signals, 'autoreaped': autoreaped, 'notes': getattr(error, '__notes__', [])}))",
                "        else:",
                "            raise AssertionError('unowned child must fail closed')",
                "finally:",
                "    signal.signal(signal.SIGCHLD, original_policy)",
                "",
            )
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["error"], "ChildProcessError")
        self.assertEqual(receipt["signals"], [])
        self.assertEqual(receipt["autoreaped"], [True])
        self.assertIn("autoreaped engine context", "\n".join(receipt["notes"]))

    @unittest.skipUnless(os.name == "posix", "requires native POSIX observation")
    def test_native_exit_observer_retains_status_until_explicit_reap(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(23)"],
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            godot_validation_module._wait_godot_process_exit(process, deadline=time.monotonic() + 3.0)
            self.assertIsNone(process.returncode)
            self.assertEqual(process.wait(timeout=1.0), 23)
        finally:
            if process.returncode is None:
                godot_validation_module._kill_godot_process(process)
                process.wait(timeout=1.0)
            if process.stdout is not None:
                process.stdout.close()

    @unittest.skipUnless(sys.platform == "darwin", "requires native Darwin LP64 waitid")
    def test_native_darwin_libc_ownership_proof_keeps_live_and_exited_child(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); raise SystemExit(23)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            with patch.object(godot_validation_module, "os", _ModuleBindingProxy(os, waitid=None)):
                godot_validation_module._prove_godot_process_ownership(process)
                self.assertIsNone(process.returncode)
                self.assertIsNotNone(process.stdin)
                if process.stdin is not None:
                    process.stdin.write(b"X")
                    process.stdin.close()
                godot_validation_module._wait_godot_process_exit(process, deadline=time.monotonic() + 3)
                godot_validation_module._prove_godot_process_ownership(process)
                godot_validation_module._prove_godot_process_ownership(process)
                self.assertIsNone(process.returncode)
                self.assertEqual(process.wait(timeout=1), 23)
        finally:
            if process.returncode is None:
                godot_validation_module._kill_godot_process(process)
                process.wait(timeout=1)
            if process.stdout is not None:
                process.stdout.close()
            if process.stdin is not None:
                process.stdin.close()

    @unittest.skipUnless(os.name == "posix", "requires native owned-child reaping")
    def test_native_external_reap_after_exit_observation_does_not_fabricate_success(self) -> None:
        original_observe = godot_validation_module._wait_godot_process_exit
        exit_codes: list[int] = []

        def observe_then_reap(
            process: subprocess.Popen[bytes],
            *,
            deadline: float,
            cleanup_errors: list[tuple[str, BaseException]] | None = None,
        ) -> None:
            original_observe(process, deadline=deadline, cleanup_errors=cleanup_errors)
            _pid, status = os.waitpid(process.pid, 0)
            exit_codes.append(os.waitstatus_to_exitcode(status))
            self.assertIsNone(process.returncode)

        with (
            patch.object(godot_validation_module, "_wait_godot_process_exit", side_effect=observe_then_reap),
            patch.object(godot_validation_module.os, "killpg") as group_signal,
            patch.object(subprocess.Popen, "kill") as direct_signal,
            self.assertRaises(ChildProcessError) as raised,
        ):
            _run_godot_command(
                [sys.executable, "-c", "print('WARNING: original exit23 context', flush=True); raise SystemExit(23)"],
                timeout=3,
            )
        self.assertEqual(exit_codes, [23])
        group_signal.assert_not_called()
        direct_signal.assert_not_called()
        self.assertIn("original exit23 context", "\n".join(raised.exception.__notes__))

    @unittest.skipUnless(os.name == "posix", "requires native POSIX groups")
    def test_native_group_signal_precedes_reap_with_inherited_stdout(self) -> None:
        processes: list[subprocess.Popen[bytes]] = []
        signals: list[int] = []
        native_killpg = cast(Callable[[int, int], None], getattr(os, "killpg"))

        def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = cast(subprocess.Popen[bytes], subprocess.Popen(*args, **kwargs))
            processes.append(process)
            return process

        def signal_group(pid: int, sig: int) -> None:
            self.assertEqual(len(processes), 1)
            self.assertIsNone(processes[0].returncode)
            signals.append(pid)
            native_killpg(pid, sig)

        with (
            patch.object(godot_validation_module, "subprocess", _ModuleBindingProxy(subprocess, Popen=spawn)),
            patch.object(godot_validation_module, "os", _ModuleBindingProxy(os, killpg=signal_group)),
        ):
            started = time.monotonic()
            result = _run_godot_command(
                ["/bin/sh", "-c", "printf 'WARNING: inherited output\\n'; sleep 30 & exit 23"],
                timeout=3,
            )
        self.assertEqual(result.returncode, 23)
        self.assertEqual(signals, [processes[0].pid])
        self.assertIn("WARNING: inherited output", result.stdout)
        self.assertNotIn("cleanup failed", result.stdout)
        self.assertLess(time.monotonic() - started, 2.0)


class TestGodotValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def _write_project(self) -> Path:
        project_dir = self.temp_dir / "godot"
        project_dir.mkdir()
        (project_dir / "project.godot").write_text(
            '[application]\nconfig/name="Validation Fixture"\nrun/main_scene="res://main.tscn"\n',
            encoding="utf-8",
        )
        (project_dir / "main.gd").write_text(
            "extends Node\n\nfunc _ready():\n\tpass\n",
            encoding="utf-8",
        )
        (project_dir / "main.tscn").write_text(
            "\n".join(
                [
                    "[gd_scene load_steps=2 format=3]",
                    "",
                    '[ext_resource type="Script" path="res://main.gd" id="main_script"]',
                    "",
                    '[node name="Main" type="Node"]',
                    'script = ExtResource("main_script")',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return project_dir

    def _write_png_sprite_project(self) -> Path:
        project_dir = self._write_project()
        sprite_dir = project_dir / "sprites" / "spr_player"
        sprite_dir.mkdir(parents=True)
        (sprite_dir / "spr_player.png").write_bytes(base64.b64decode(_PNG_1X1_WHITE))
        (sprite_dir / "spr_player.tscn").write_text(
            "\n".join(
                [
                    "[gd_scene load_steps=2 format=3]",
                    "",
                    '[ext_resource type="Texture2D" path="res://sprites/spr_player/spr_player.png" id="texture"]',
                    "",
                    '[node name="spr_player" type="Node2D"]',
                    "",
                    '[node name="Sprite2D" type="Sprite2D" parent="."]',
                    'texture = ExtResource("texture")',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return project_dir

    def _write_fake_godot(self, script: str) -> Path:
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        fake_godot.chmod(0o755)
        return fake_godot

    @staticmethod
    def _high_volume_output_shell(
        first_line: str,
        last_line: str,
        *,
        central_line: str = "CENTRAL_OUTPUT_MUST_BE_DISCARDED",
        last_to_stderr: bool = False,
    ) -> str:
        last_redirect = " >&2" if last_to_stderr else ""
        return (
            f"printf '%s\\n' '{first_line}'\n"
            "i=0\n"
            "while [ \"$i\" -lt 200 ]; do\n"
            "  if [ \"$i\" -eq 100 ]; then\n"
            f"    printf '%s\\n' '{central_line}'\n"
            "  else\n"
            "    printf 'filler-%03d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\\n' \"$i\"\n"
            "  fi\n"
            "  i=$((i + 1))\n"
            "done\n"
            f"printf '%s\\n' '{last_line}'{last_redirect}\n"
        )

    def test_find_godot_binary_uses_version_neutral_macos_app_path(self) -> None:
        macos_app_binary = "/Applications/Godot.app/Contents/MacOS/Godot"

        def is_existing_candidate(candidate: str) -> bool:
            return candidate == macos_app_binary

        with (
            patch("src.conversion.godot_validation.os.environ.get", return_value=None),
            patch("src.conversion.godot_validation.shutil.which", return_value=None),
            patch(
                "src.conversion.godot_validation.os.path.isfile",
                side_effect=is_existing_candidate,
            ) as is_file,
        ):
            resolved_binary = find_godot_binary()

        self.assertEqual(resolved_binary, macos_app_binary)
        is_file.assert_called_once_with(macos_app_binary)

    def test_timeout_reader_deferred_until_after_stop_retains_buffered_diagnostic(
        self,
    ) -> None:
        diagnostic = b"SCRIPT ERROR: buffered before timeout shutdown\n"
        process = _PipeBackedProcess(diagnostic, timeout_on_first_wait=True)
        self.addCleanup(process.close_stdout)
        deferred_threads: list[_DeferredTargetThread] = []
        read_calls = 0

        def make_deferred_thread(
            *,
            target: Callable[[], None],
            name: str,
            daemon: bool,
        ) -> _DeferredTargetThread:
            output_reader = _DeferredTargetThread(
                target=target,
                name=name,
                daemon=daemon,
            )
            deferred_threads.append(output_reader)
            return output_reader

        def counted_read(fd: int, size: int) -> bytes:
            nonlocal read_calls
            read_calls += 1
            return os.read(fd, size)

        os_proxy = _ModuleBindingProxy(
            os,
            killpg=_ignore_killpg,
            read=counted_read,
        )
        subprocess_proxy = _ModuleBindingProxy(
            subprocess,
            Popen=_popen_returning(process),
        )
        threading_proxy = _ModuleBindingProxy(
            threading,
            Thread=make_deferred_thread,
        )

        try:
            with (
                patch.object(godot_validation_module, "os", os_proxy),
                patch.object(godot_validation_module, "subprocess", subprocess_proxy),
                patch.object(godot_validation_module, "threading", threading_proxy),
                patch.object(godot_validation_module, "_wait_godot_process_exit", side_effect=_observe_fake_process_exit),
                patch.object(godot_validation_module, "_prove_godot_process_ownership", side_effect=_prove_fake_process_ownership),
                self.assertRaises(subprocess.TimeoutExpired) as raised,
            ):
                _run_godot_command(["fake-godot"], timeout=1)
        finally:
            for output_reader in deferred_threads:
                output_reader.release()

        self.assertEqual(read_calls, 1)
        self.assertIn(diagnostic.decode("utf-8").strip(), raised.exception.output)

    def test_reader_retries_after_output_arrives_during_stop_wait(self) -> None:
        diagnostic = b"WARNING: buffered while the reader waited for shutdown\n"
        process = _PipeBackedProcess(b"", keep_writer_open=True)
        self.addCleanup(process.close_stdout)
        stop_event = _WaitArrivalStopEvent()
        race_threads: list[_WriteDuringWaitThread] = []
        read_calls = 0

        def make_stop_event() -> _WaitArrivalStopEvent:
            return stop_event

        def make_race_thread(
            *,
            target: Callable[[], None],
            name: str,
            daemon: bool,
        ) -> _WriteDuringWaitThread:
            output_reader = _WriteDuringWaitThread(
                target=target,
                name=name,
                daemon=daemon,
                stop_event=stop_event,
                buffer_output=lambda: process.write_output(diagnostic),
            )
            race_threads.append(output_reader)
            return output_reader

        def counted_read(fd: int, size: int) -> bytes:
            nonlocal read_calls
            read_calls += 1
            return os.read(fd, size)

        os_proxy = _ModuleBindingProxy(
            os,
            killpg=_ignore_killpg,
            read=counted_read,
        )
        subprocess_proxy = _ModuleBindingProxy(
            subprocess,
            Popen=_popen_returning(process),
        )
        threading_proxy = _ModuleBindingProxy(
            threading,
            Event=make_stop_event,
            Thread=make_race_thread,
        )

        try:
            with (
                patch.object(godot_validation_module, "os", os_proxy),
                patch.object(godot_validation_module, "subprocess", subprocess_proxy),
                patch.object(godot_validation_module, "threading", threading_proxy),
                patch.object(godot_validation_module, "_wait_godot_process_exit", side_effect=_observe_fake_process_exit),
                patch.object(godot_validation_module, "_prove_godot_process_ownership", side_effect=_prove_fake_process_ownership),
            ):
                result = _run_godot_command(["fake-godot"], timeout=1)
        finally:
            for output_reader in race_threads:
                output_reader.release()

        self.assertEqual(read_calls, 2)
        self.assertIn(diagnostic.decode("utf-8").strip(), result.stdout)

    def test_normal_completion_reader_oserror_is_capture_failure(self) -> None:
        process = _PipeBackedProcess(b"")
        self.addCleanup(process.close_stdout)
        capture_error = OSError("injected normal read failure")

        def fail_read(_fd: int, _size: int) -> bytes:
            raise capture_error

        os_proxy = _ModuleBindingProxy(
            os,
            name="not-posix",
            read=fail_read,
        )
        subprocess_proxy = _ModuleBindingProxy(
            subprocess,
            Popen=_popen_returning(process),
        )
        threading_proxy = _ModuleBindingProxy(
            threading,
            Thread=_SynchronousTargetThread,
        )

        with (
            patch.object(godot_validation_module, "os", os_proxy),
            patch.object(godot_validation_module, "subprocess", subprocess_proxy),
            patch.object(godot_validation_module, "threading", threading_proxy),
            self.assertRaisesRegex(
                RuntimeError,
                "Failed while capturing Godot output",
            ) as raised,
        ):
            _run_godot_command(["fake-godot"], timeout=1)

        self.assertEqual(process.kill_calls, 0)
        self.assertIs(raised.exception.__cause__, capture_error)

    def test_timeout_reader_oserror_is_capture_failure(self) -> None:
        process = _PipeBackedProcess(b"", timeout_on_first_wait=True)
        self.addCleanup(process.close_stdout)
        capture_error = OSError("injected timeout read failure")

        def fail_read(_fd: int, _size: int) -> bytes:
            raise capture_error

        os_proxy = _ModuleBindingProxy(
            os,
            killpg=_ignore_killpg,
            read=fail_read,
        )
        subprocess_proxy = _ModuleBindingProxy(
            subprocess,
            Popen=_popen_returning(process),
        )

        with (
            patch.object(godot_validation_module, "os", os_proxy),
            patch.object(godot_validation_module, "subprocess", subprocess_proxy),
            patch.object(godot_validation_module, "_wait_godot_process_exit", side_effect=_observe_fake_process_exit),
            patch.object(godot_validation_module, "_prove_godot_process_ownership", side_effect=_prove_fake_process_ownership),
            self.assertRaises(subprocess.TimeoutExpired) as raised,
        ):
            _run_godot_command(["fake-godot"], timeout=1)

        self.assertIn("ERROR: GM2Godot output capture failed", str(raised.exception.output))
        self.assertIn(str(capture_error), str(raised.exception.output))

    def test_stop_deadline_leaves_stdout_owned_by_live_reader(self) -> None:
        process = _PipeBackedProcess(b"")
        self.addCleanup(process.close_stdout)
        blocked_readers: list[_DeadlineBlockedTargetThread] = []
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }

        def make_blocked_reader(
            *,
            target: Callable[[], None],
            name: str,
            daemon: bool,
        ) -> _DeadlineBlockedTargetThread:
            output_reader = _DeadlineBlockedTargetThread(
                target=target,
                name=name,
                daemon=daemon,
            )
            blocked_readers.append(output_reader)
            return output_reader

        os_proxy = _ModuleBindingProxy(
            os,
            killpg=_ignore_killpg,
        )
        subprocess_proxy = _ModuleBindingProxy(
            subprocess,
            Popen=_popen_returning(process),
        )
        threading_proxy = _ModuleBindingProxy(
            threading,
            Thread=make_blocked_reader,
        )

        try:
            with (
                patch.object(godot_validation_module, "os", os_proxy),
                patch.object(godot_validation_module, "subprocess", subprocess_proxy),
                patch.object(godot_validation_module, "threading", threading_proxy),
                patch.object(godot_validation_module, "_wait_godot_process_exit", side_effect=_observe_fake_process_exit),
                patch.object(godot_validation_module, "_prove_godot_process_ownership", side_effect=_prove_fake_process_ownership),
                self.assertRaisesRegex(
                    RuntimeError,
                    "Godot output reader did not stop after pipe cleanup",
                ),
            ):
                _run_godot_command(["fake-godot"], timeout=1)

            self.assertEqual(len(blocked_readers), 1)
            self.assertEqual(blocked_readers[0].join_calls, 2)
            self.assertTrue(blocked_readers[0].is_alive())
            self.assertFalse(process.stdout.closed)
        finally:
            for output_reader in blocked_readers:
                output_reader.release()

        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertTrue(process.stdout.closed)
        self.assertFalse(blocked_readers[0].is_alive())
        self.assertEqual(lingering_readers, [])

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_command_exit_with_inherited_stdout_remains_bounded(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot("sleep 3 &\nexit 0\n")
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }
        started = time.monotonic()

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
        )

        elapsed = time.monotonic() - started
        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.returncode, 0)
        self.assertLess(elapsed, 2.0)
        self.assertEqual(lingering_readers, [])

    @unittest.skipUnless(os.name == "posix", "requires fork and POSIX sessions")
    def test_detached_stdout_holder_does_not_consume_remaining_timeout(self) -> None:
        child_pid_path = self.temp_dir / "detached-child.pid"
        fake_godot = self.temp_dir / "detached-stdout-holder.py"
        fake_godot.write_text(
            "\n".join(
                (
                    "import os",
                    "import time",
                    "from pathlib import Path",
                    "",
                    "child_pid = os.fork()",
                    "if child_pid == 0:",
                    "    os.setsid()",
                    f"    Path({os.fspath(child_pid_path)!r}).write_text(str(os.getpid()))",
                    "    time.sleep(30)",
                    "    os._exit(0)",
                    "os._exit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }
        started = time.monotonic()
        child_pid: int | None = None

        try:
            result = _run_godot_command(
                [sys.executable, os.fspath(fake_godot)],
                timeout=3,
            )
            elapsed = time.monotonic() - started
            for _attempt in range(100):
                if child_pid_path.is_file():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    break
                time.sleep(0.01)
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertEqual(result.returncode, 0)
        self.assertLess(elapsed, 1.5)
        self.assertIsNotNone(child_pid)
        self.assertEqual(lingering_readers, [])

    @unittest.skipUnless(os.name == "posix", "requires fork and POSIX sessions")
    def test_continuously_writing_detached_stdout_stops_at_reader_deadline(
        self,
    ) -> None:
        child_pid_path = self.temp_dir / "continuous-detached-child.pid"
        fake_godot = self.temp_dir / "continuous-detached-stdout.py"
        fake_godot.write_text(
            "\n".join(
                (
                    "import os",
                    "import time",
                    "from pathlib import Path",
                    "",
                    f"child_pid_path = Path({os.fspath(child_pid_path)!r})",
                    "child_pid_temporary_path = child_pid_path.with_suffix('.tmp')",
                    "child_pid = os.fork()",
                    "if child_pid == 0:",
                    "    os.setsid()",
                    "    child_pid_temporary_path.write_text(str(os.getpid()))",
                    "    os.replace(child_pid_temporary_path, child_pid_path)",
                    "    payload = b'continuous-detached-output\\n' * 128",
                    "    while True:",
                    "        try:",
                    "            os.write(1, payload)",
                    "        except OSError:",
                    "            os._exit(0)",
                    "while not child_pid_path.is_file():",
                    "    time.sleep(0.001)",
                    "os._exit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        existing_readers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
        }
        child_pid: int | None = None
        started = time.monotonic()

        try:
            result = _run_godot_command(
                [sys.executable, os.fspath(fake_godot)],
                timeout=3,
            )
            elapsed = time.monotonic() - started
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        finally:
            if child_pid is None and child_pid_path.is_file():
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        lingering_readers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gm2godot-godot-output-reader"
            and thread.ident not in existing_readers
        ]
        self.assertEqual(result.returncode, 0)
        self.assertLess(elapsed, 2.0)
        self.assertIsNotNone(child_pid)
        self.assertEqual(lingering_readers, [])

    def test_resource_path_discovery_is_deterministic(self) -> None:
        project_dir = self._write_project()

        self.assertEqual(
            generated_godot_resource_paths(str(project_dir)),
            ("res://main.gd", "res://main.tscn"),
        )

    def test_importable_asset_path_discovery_is_deterministic(self) -> None:
        project_dir = self._write_png_sprite_project()

        self.assertEqual(
            generated_godot_importable_asset_paths(str(project_dir)),
            ("res://sprites/spr_player/spr_player.png",),
        )

    def test_detects_godot_warning_and_error_output(self) -> None:
        issues = detect_godot_output_issues(
            "\n".join(
                [
                    "Godot Engine v4.6.3.stable.official",
                    "SCRIPT ERROR: Parse Error: Identifier not declared.",
                    "          at: GDScript::reload (res://bad.gd:4)",
                    "WARNING: Some generated resource warning.",
                    "GM2GODOT_VALIDATION_OK 1",
                ]
            )
        )

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0].severity, "error")
        self.assertEqual(issues[0].line, "SCRIPT ERROR: Parse Error: Identifier not declared.")
        self.assertEqual(issues[1].severity, "warning")

    def test_detects_colored_godot_warning_and_error_output(self) -> None:
        issues = detect_godot_output_issues(
            "\n".join(
                [
                    "\x1b[1;31mERROR:\x1b[0;91m Failed loading resource.",
                    "\x1b[1;33mWARNING:\x1b[0;93m Scan thread aborted...",
                ]
            )
        )

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0].severity, "error")
        self.assertEqual(issues[0].line, "ERROR: Failed loading resource.")
        self.assertEqual(issues[1].severity, "warning")

    def test_resource_validation_bounds_output_and_keeps_deterministic_context(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot(
            self._high_volume_output_shell(
                "FIRST RESOURCE VALIDATION CONTEXT",
                "LAST RESOURCE VALIDATION CONTEXT",
                central_line="ERROR: CENTRAL OUTPUT MUST BE SUMMARIZED",
            )
            + "exit 0\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            with patch(
                "src.conversion.godot_validation._GODOT_OUTPUT_READ_CHUNK_BYTES",
                17,
            ):
                first_report = validate_generated_godot_project(
                    str(project_dir),
                    godot_binary=str(fake_godot),
                )
            with patch(
                "src.conversion.godot_validation._GODOT_OUTPUT_READ_CHUNK_BYTES",
                4096,
            ):
                second_report = validate_generated_godot_project(
                    str(project_dir),
                    godot_binary=str(fake_godot),
                )

        self.assertEqual(first_report.status, "failed")
        self.assertEqual(first_report.returncode, 0)
        self.assertEqual(first_report.output, second_report.output)
        self.assertIn("FIRST RESOURCE VALIDATION CONTEXT", first_report.output)
        self.assertIn("LAST RESOURCE VALIDATION CONTEXT", first_report.output)
        self.assertIn("GM2Godot: Godot output truncated", first_report.output)
        self.assertNotIn("ERROR: CENTRAL OUTPUT MUST BE SUMMARIZED", first_report.output)
        self.assertIn("omitted 1 additional Godot error diagnostic", first_report.output)
        self.assertLess(len(first_report.output.encode("utf-8")), 512)
        self.assertEqual(len(first_report.output_issues), 1)

    def test_import_validation_bounds_output_and_preserves_exit_status(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self._write_fake_godot(
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            + self._high_volume_output_shell(
                "FIRST IMPORT CONTEXT",
                "WARNING: LAST IMPORT CONTEXT",
            )
            + "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'resource validation should not run'\n"
            "exit 31\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
            )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("FIRST IMPORT CONTEXT", report.import_output)
        self.assertIn("WARNING: LAST IMPORT CONTEXT", report.import_output)
        self.assertIn("GM2Godot: Godot output truncated", report.import_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.import_output)
        self.assertNotIn("resource validation should not run", report.output)
        self.assertLess(len(report.import_output.encode("utf-8")), 512)

    def test_boot_validation_bounds_combined_stdout_and_stderr(self) -> None:
        project_dir = self._write_project()
        fake_godot = self._write_fake_godot(
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            + self._high_volume_output_shell(
                "FIRST BOOT CONTEXT",
                "ERROR: LAST BOOT STDERR CONTEXT",
                last_to_stderr=True,
            )
            + "    exit 23\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
                boot_frames=2,
            )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 23)
        self.assertIn("FIRST BOOT CONTEXT", report.boot_output)
        self.assertIn("ERROR: LAST BOOT STDERR CONTEXT", report.boot_output)
        self.assertIn("GM2Godot: Godot output truncated", report.boot_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.boot_output)
        self.assertLess(len(report.boot_output.encode("utf-8")), 512)
        self.assertEqual(report.output_issues[-1].line, "ERROR: LAST BOOT STDERR CONTEXT")

    def test_import_timeout_returns_bounded_partial_output(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self._write_fake_godot(
            self._high_volume_output_shell(
                "FIRST TIMEOUT CONTEXT",
                "LAST TIMEOUT CONTEXT",
            )
            + "sleep 5\n"
        )

        with patch(
            "src.conversion.godot_validation._GODOT_OUTPUT_CAPTURE_LIMIT_BYTES",
            256,
        ):
            report = validate_generated_godot_project(
                str(project_dir),
                godot_binary=str(fake_godot),
                timeout=1,
                load_resources=False,
            )

        self.assertEqual(report.status, "passed")
        self.assertIsNone(report.import_returncode)
        self.assertIn("ran for 1 seconds", report.message)
        self.assertIn("FIRST TIMEOUT CONTEXT", report.import_output)
        self.assertIn("LAST TIMEOUT CONTEXT", report.import_output)
        self.assertIn("GM2Godot: Godot output truncated", report.import_output)
        self.assertNotIn("CENTRAL_OUTPUT_MUST_BE_DISCARDED", report.import_output)
        self.assertLess(len(report.import_output.encode("utf-8")), 512)

    def test_validation_fails_when_godot_outputs_error_with_zero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'Godot Engine v4.6.3.stable.official'\n"
            "printf '%s\\n' 'SCRIPT ERROR: Parse Error: Identifier not declared.'\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.returncode, 0)
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "error")

    def test_validation_runs_import_pass_for_importable_assets(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            "    printf '%s\\n' 'GM2GODOT_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 3'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_IMPORT_OK", report.import_output)
        self.assertIn("GM2GODOT_VALIDATION_OK 3", report.output)

    def test_import_pass_uses_recovery_mode(self) -> None:
        project_dir = self._write_png_sprite_project()
        args_file = self.temp_dir / "import-args.txt"
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            f"    printf '%s\\n' \"$@\" > '{args_file}'\n"
            "    printf '%s\\n' 'GM2GODOT_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 3'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
        )

        self.assertEqual(report.status, "passed")
        self.assertIn("--recovery-mode", args_file.read_text(encoding="utf-8").splitlines())

    def test_import_only_validation_skips_resource_load_script(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            "    printf '%s\\n' 'GM2GODOT_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'resource loading should have been skipped'\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.returncode, 0)
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_IMPORT_OK", report.output)
        self.assertIn("skipped loading 3 generated scripts/scenes/resources", report.message)

    def test_import_only_validation_falls_back_without_audio_after_clean_nonzero_import(self) -> None:
        project_dir = self._write_png_sprite_project()
        (project_dir / "sounds").mkdir()
        (project_dir / "sounds" / "theme.mp3").write_bytes(b"fake mp3")
        fake_godot = self.temp_dir / "fake-godot"
        marker = self.temp_dir / "first-import-done"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--import\" ]; then\n"
            f"    if [ ! -f '{marker}' ]; then\n"
            f"      touch '{marker}'\n"
            "      printf '%s\\n' 'Godot exited without diagnostics during audio import.'\n"
            "      exit 11\n"
            "    fi\n"
            "    printf '%s\\n' 'GM2GODOT_NO_AUDIO_IMPORT_OK'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'resource loading should have been skipped'\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.import_returncode, 0)
        self.assertIn("GM2GODOT_NO_AUDIO_IMPORT_OK", report.output)
        self.assertIn("no-audio import fallback completed", report.message)

    def test_import_only_timeout_passes_when_no_warning_or_error_output(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'Godot Engine v4.6.3.stable.official'\n"
            "sleep 5\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
            load_resources=False,
        )

        self.assertEqual(report.status, "passed")
        self.assertIsNone(report.import_returncode)
        self.assertEqual(report.output_issues, ())
        self.assertIn("without warning/error output", report.message)

    def test_import_only_timeout_fails_when_warning_or_error_output_exists(self) -> None:
        project_dir = self._write_png_sprite_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'SCRIPT ERROR: Parse Error: Identifier not declared.'\n"
            "sleep 5\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            timeout=1,
            load_resources=False,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "error")

    def test_boot_validation_runs_main_scene_for_requested_frames(self) -> None:
        project_dir = self._write_project()
        args_file = self.temp_dir / "boot-args.txt"
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "is_boot=0\n"
            "is_script=0\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then is_boot=1; fi\n"
            "  if [ \"$arg\" = \"--script\" ]; then is_script=1; fi\n"
            "done\n"
            "if [ \"$is_boot\" = \"1\" ]; then\n"
            f"  printf '%s\\n' \"$@\" > '{args_file}'\n"
            "  printf '%s\\n' 'GM2GODOT_BOOT_OK'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$is_script\" = \"1\" ]; then\n"
            "  printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' 'unexpected Godot invocation'\n"
            "exit 8\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=4,
        )

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.boot_frames, 4)
        self.assertEqual(report.boot_returncode, 0)
        self.assertIn("GM2GODOT_VALIDATION_OK 2", report.output)
        self.assertIn("GM2GODOT_BOOT_OK", report.boot_output)
        boot_args = args_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("--headless", boot_args)
        self.assertIn("--fixed-fps", boot_args)
        self.assertIn("--path", boot_args)
        self.assertIn("--quit-after", boot_args)
        self.assertIn("4", boot_args)
        self.assertNotIn("--script", boot_args)

    def test_boot_validation_fails_on_runtime_warning_with_zero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            "    printf '%s\\n' 'WARNING: Runtime warning from main scene.'\n"
            "    exit 0\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=2,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 0)
        self.assertEqual(len(report.output_issues), 1)
        self.assertEqual(report.output_issues[0].severity, "warning")
        self.assertIn("boot reported 0 error(s) and 1 warning(s)", report.message)

    def test_boot_validation_fails_on_runtime_nonzero_exit(self) -> None:
        project_dir = self._write_project()
        fake_godot = self.temp_dir / "fake-godot"
        fake_godot.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  if [ \"$arg\" = \"--quit-after\" ]; then\n"
            "    printf '%s\\n' 'Runtime exited without warning lines.'\n"
            "    exit 13\n"
            "  fi\n"
            "done\n"
            "printf '%s\\n' 'GM2GODOT_VALIDATION_OK 2'\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)

        report = validate_generated_godot_project(
            str(project_dir),
            godot_binary=str(fake_godot),
            boot_frames=2,
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.boot_returncode, 13)
        self.assertEqual(report.output_issues, ())
        self.assertIn("boot exited with code 13", report.message)

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_validation_loads_generated_resources(self) -> None:
        project_dir = self._write_project()

        report = validate_generated_godot_project(str(project_dir))

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("GM2GODOT_VALIDATION_OK", report.output)
        self.assertEqual(report.resource_paths, ("res://main.gd", "res://main.tscn"))

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_validation_imports_png_before_loading_scene(self) -> None:
        project_dir = self._write_png_sprite_project()

        report = validate_generated_godot_project(str(project_dir))

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.import_returncode, 0, report.import_output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("GM2GODOT_VALIDATION_OK", report.output)

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_headless_godot_boots_main_scene_without_warnings(self) -> None:
        project_dir = self._write_project()

        report = validate_generated_godot_project(str(project_dir), boot_frames=2)

        self.assertEqual(report.status, "passed", report.output)
        self.assertEqual(report.boot_frames, 2)
        self.assertEqual(report.boot_returncode, 0, report.boot_output)
        self.assertEqual(report.output_issues, (), report.output)
        self.assertIn("main scene", report.message)

    @unittest.skipIf(find_godot_binary() is None, "Godot binary not available")
    def test_cli_validate_writes_godot_validation_report(self) -> None:
        project_dir = self._write_project()
        (project_dir / "gm2godot").mkdir()
        (project_dir / "gm2godot" / "conversion_diagnostics.json").write_text(
            '{"summary":{"info":0,"warning":0,"error":0,"total":0},"diagnostics":[]}\n',
            encoding="utf-8",
        )

        exit_code = cli.main(["validate", "--godot-project", str(project_dir)])

        self.assertEqual(exit_code, 0)
        report_path = project_dir / GODOT_VALIDATION_REPORT_RELATIVE_PATH
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["resource_count"], 2)
        self.assertEqual(report["boot_frames"], 0)
        self.assertEqual(report["output_issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
