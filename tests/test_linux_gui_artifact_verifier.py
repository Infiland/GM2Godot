# pyright: reportPrivateUsage=false

from __future__ import annotations

import inspect
import os
import shlex
import stat
import subprocess
import tempfile
import time
import unittest
import warnings
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager, redirect_stderr
from io import StringIO
from pathlib import Path
from typing import cast
from unittest import mock

from scripts import verify_linux_gui_artifact as verifier

NON_TIMEOUT_INTEGRATION_SECONDS = 15.0
CHILD_READINESS_SECONDS = 15.0
INTENTIONAL_TIMEOUT_SECONDS = 0.25
READINESS_POLL_SECONDS = 0.01


class _ReapAwareProcess:
    pid = 24680

    def __init__(self) -> None:
        self.reaped = False

    def poll(self) -> int:
        self.reaped = True
        return -9


def _member(
    name: str,
    content: bytes,
    *,
    mode: int,
    file_type: int = stat.S_IFREG,
    create_system: int = 3,
) -> tuple[zipfile.ZipInfo, bytes]:
    member = zipfile.ZipInfo(name)
    member.create_system = create_system
    member.external_attr = (file_type | mode) << 16
    member.compress_type = zipfile.ZIP_DEFLATED
    return member, content


def _executable_script(body: str) -> bytes:
    return ("#!/bin/sh\nset -eu\n" + body).encode("utf-8")


def _write_archive(
    root: Path,
    executable: bytes,
    *,
    members: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
) -> Path:
    archive_path = root / verifier.ARCHIVE_NAME
    selected = members
    if selected is None:
        selected = [
            _member(
                verifier.EXECUTABLE_NAME,
                executable,
                mode=0o755,
            ),
            _member(verifier.README_NAME, b"# GM2Godot\n", mode=0o644),
        ]
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for member, content in selected:
            archive.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED)
    return archive_path


def _write_fake_xvfb_run(root: Path) -> Path:
    path = root / "xvfb-run"
    path.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "for argument in \"$@\"; do command=$argument; done\n"
        "exec \"$command\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_delayed_cleanup_xvfb_run(root: Path) -> Path:
    path = root / "xvfb-run-delayed-cleanup"
    path.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "for argument in \"$@\"; do command=$argument; done\n"
        "/bin/sh -c 'trap \"exit 0\" TERM; /bin/sleep 0.4' &\n"
        "helper=$!\n"
        "cleanup() { kill \"$helper\" 2>/dev/null || :; }\n"
        "trap cleanup EXIT\n"
        '"$command"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _assert_process_gone(test_case: unittest.TestCase, process_id: int) -> None:
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            test_case.fail(f"descendant process {process_id} survived verifier cleanup")
        time.sleep(0.02)


def _read_test_child_pid(receipt_path: Path) -> int | None:
    try:
        raw_process_id = receipt_path.read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise AssertionError(
            f"test child readiness receipt could not be read: "
            f"{receipt_path}: {error}"
        ) from error

    try:
        process_id = int(raw_process_id)
    except ValueError:
        return None
    return process_id if process_id > 0 else None


def _wait_for_test_child_pid(
    receipt_path: Path,
    process: subprocess.Popen[bytes],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    deadline = clock() + CHILD_READINESS_SECONDS
    while True:
        process_id = _read_test_child_pid(receipt_path)
        if process_id is not None:
            return process_id

        returncode = process.poll()
        if returncode is not None:
            process_id = _read_test_child_pid(receipt_path)
            if process_id is not None:
                return process_id
            raise AssertionError(
                f"test child exited with status {returncode} before publishing "
                f"a valid PID readiness receipt: {receipt_path}"
            )

        remaining = deadline - clock()
        if remaining <= 0:
            raise AssertionError(
                f"test child did not publish a valid PID readiness receipt within "
                f"{CHILD_READINESS_SECONDS:g} seconds: {receipt_path}"
            )
        sleeper(min(READINESS_POLL_SECONDS, remaining))


@contextmanager
def _runtime_timeout_after_test_child_ready(
    receipt_path: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Generator[list[int]]:
    delegate = verifier._wait_for_process
    process_ids: list[int] = []

    def wait_after_readiness(
        process: subprocess.Popen[bytes],
        output: object,
        timeout_seconds: float,
    ) -> int:
        process_ids.append(
            _wait_for_test_child_pid(
                receipt_path,
                process,
                clock=clock,
                sleeper=sleeper,
            )
        )
        return delegate(process, output, timeout_seconds)

    with mock.patch.object(verifier, "_wait_for_process", wait_after_readiness):
        yield process_ids


def _require_fatal_diagnostic(output: str) -> tuple[str, str]:
    diagnostic = verifier._fatal_output_diagnostic(output)
    if diagnostic is None:
        raise AssertionError("expected a fatal loader/platform diagnostic")
    return diagnostic


def _success_body(extra: str = "") -> str:
    return (
        '[ "$QT_QPA_PLATFORM" = "xcb" ]\n'
        '[ "$QT_DEBUG_PLUGINS" = "1" ]\n'
        '[ -d "$XDG_RUNTIME_DIR" ]\n'
        '[ -d "$TMPDIR" ]\n'
        '[ "${LD_LIBRARY_PATH+x}" != "x" ]\n'
        "umask 077\n"
        f"{extra}"
        f"printf '{verifier.GUI_SMOKE_RECEIPT.decode('ascii')}' "
        f' > "${verifier.GUI_SMOKE_RECEIPT_ENV}"\n'
        f'chmod 600 "${verifier.GUI_SMOKE_RECEIPT_ENV}"\n'
    )


@unittest.skipUnless(
    os.name == "posix" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "killpg"),
    "Linux artifact verifier requires POSIX no-follow and process groups",
)
class LinuxGuiArtifactVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="gm2godot-linux-verifier-test-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.xvfb_run = _write_fake_xvfb_run(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verify(
        self,
        body: str,
        *,
        timeout_seconds: float = NON_TIMEOUT_INTEGRATION_SECONDS,
    ) -> None:
        archive = _write_archive(self.root, _executable_script(body))
        verifier.verify_archive(
            archive,
            xvfb_run_path=self.xvfb_run,
            timeout_seconds=timeout_seconds,
        )

    def test_exact_archive_launches_under_xcb_and_writes_receipt(self) -> None:
        self.verify(_success_body())

    def test_zero_exit_without_receipt_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "read packaged GUI readiness receipt",
        ):
            self.verify("exit 0\n")

    def test_nonzero_exit_is_rejected_even_with_receipt(self) -> None:
        body = _success_body() + "exit 7\n"
        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "exited with status 7",
        ):
            self.verify(body)

    def test_wrong_receipt_content_and_mode_are_rejected(self) -> None:
        cases = {
            "content": (
                b"wrong\n",
                0o600,
                "content is invalid",
            ),
            "mode": (
                verifier.GUI_SMOKE_RECEIPT,
                0o644,
                "does not have mode 0600",
            ),
        }
        for name, (content, mode, message) in cases.items():
            with self.subTest(name=name):
                receipt_path = self.root / f"{name}.receipt"
                receipt_path.write_bytes(content)
                receipt_path.chmod(mode)
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    message,
                ):
                    verifier._validate_receipt(receipt_path)

    def test_fatal_loader_and_platform_diagnostics_are_classified(self) -> None:
        for signature in verifier._FATAL_OUTPUT_SIGNATURES:
            with self.subTest(signature=signature):
                classified, excerpt = _require_fatal_diagnostic(
                    signature.upper()
                )
                self.assertEqual(classified, signature)
                self.assertEqual(excerpt, f"'{signature.upper()}'")

    def test_real_process_fatal_diagnostic_is_rejected(self) -> None:
        signature = verifier._FATAL_OUTPUT_SIGNATURES[0]
        body = _success_body(f"printf '%s\\n' '{signature.upper()}' >&2\n")
        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "fatal loader/platform diagnostic",
        ):
            self.verify(body)

    def test_missing_qtgui_graphics_loader_dependencies_are_classified(self) -> None:
        for library in ("libEGL.so.1", "libGL.so.1"):
            with self.subTest(library=library):
                _, excerpt = _require_fatal_diagnostic(
                    f"ImportError: {library}: cannot open shared object file: "
                    "No such file or directory"
                )
                self.assertIn(library, excerpt)

    def test_fatal_diagnostic_reports_one_bounded_matching_line(self) -> None:
        marker = "cannot open shared object file"
        _, excerpt = _require_fatal_diagnostic(
            "before-line-sentinel\n"
            f"{'p' * 2000}{marker}{'s' * 2000}\n"
            "after-line-sentinel\n"
        )
        self.assertIn(marker, excerpt)
        self.assertTrue(excerpt.startswith("'..."))
        self.assertTrue(excerpt.endswith("...'"))
        self.assertNotIn("before-line-sentinel", excerpt)
        self.assertNotIn("after-line-sentinel", excerpt)
        self.assertLessEqual(
            len(excerpt),
            verifier.MAX_DIAGNOSTIC_LINE_CHARACTERS + 2,
        )

    def test_first_fatal_output_line_is_reported(self) -> None:
        first = "could not load the qt platform plugin"
        later = "error while loading shared libraries"
        signature, excerpt = _require_fatal_diagnostic(
            f"first: {first}\nlater: {later}\n"
        )
        self.assertEqual(signature, first)
        self.assertEqual(excerpt, f"'first: {first}'")
        self.assertNotIn(f"later: {later}", excerpt)

    def test_leftmost_fatal_signature_on_one_line_is_classified(self) -> None:
        first = "could not load the qt platform plugin"
        later = "error while loading shared libraries"
        signature, excerpt = _require_fatal_diagnostic(
            f"first: {first}; later: {later}"
        )
        self.assertEqual(signature, first)
        self.assertEqual(excerpt, f"'first: {first}; later: {later}'")

    def test_non_ascii_prefix_does_not_shift_fatal_marker_excerpt(self) -> None:
        marker = "cannot open shared object file"
        _, excerpt = _require_fatal_diagnostic(
            f"{'ß' * 2000}{marker}{'x' * 2000}"
        )
        self.assertIn(marker, excerpt)
        self.assertLessEqual(
            len(excerpt),
            verifier.MAX_DIAGNOSTIC_LINE_CHARACTERS + 2,
        )

    def test_escaped_prefix_does_not_expand_bounded_excerpt(self) -> None:
        marker = "cannot open shared object file"
        _, excerpt = _require_fatal_diagnostic(
            f"{chr(92) * 2000}{marker}{chr(92) * 2000}"
        )
        self.assertIn(marker, excerpt)
        self.assertLessEqual(
            len(excerpt),
            verifier.MAX_DIAGNOSTIC_LINE_CHARACTERS + 2,
        )

    def test_quote_heavy_prefix_keeps_diagnostic_wrapper_unambiguous(self) -> None:
        marker = "cannot open shared object file"
        diagnostic_line = "'" * 2000 + "a" + marker + "x" * 2000
        _, excerpt = _require_fatal_diagnostic(diagnostic_line)
        self.assertIn(marker, excerpt)
        self.assertEqual(excerpt.count("'"), 2)
        self.assertNotRegex(excerpt, "[\\r\\n\\x00-\\x1f\\x7f]")
        self.assertLessEqual(
            len(excerpt),
            verifier.MAX_DIAGNOSTIC_LINE_CHARACTERS + 2,
        )

    def test_bounded_excerpt_escapes_control_characters(self) -> None:
        marker = "cannot open shared object file"
        line = "\x00\t\x1b" * 1000 + marker + "\x7f\r" * 1000
        marker_start = line.index(marker)
        excerpt = verifier._bounded_output_excerpt(
            line,
            marker_start,
            marker_start + len(marker),
        )

        self.assertIn(marker, excerpt)
        self.assertEqual(excerpt.count("'"), 2)
        self.assertNotRegex(excerpt, r"[\x00-\x1f\x7f]")
        self.assertLessEqual(
            len(excerpt),
            verifier.MAX_DIAGNOSTIC_LINE_CHARACTERS + 2,
        )

    def test_delayed_child_readiness_precedes_short_runtime_timeout_without_sleep(
        self,
    ) -> None:
        receipt_path = self.root / "delayed-child.pid"
        raw_process = mock.Mock()
        raw_process.poll.return_value = None
        process = cast(subprocess.Popen[bytes], raw_process)
        output = object()
        delegate = mock.Mock(
            side_effect=verifier.LinuxGuiArtifactVerificationError(
                "packaged GUI timed out after 0.25 seconds"
            )
        )
        clock = mock.Mock(side_effect=(0.0, 0.0))

        def publish_readiness(delay_seconds: float) -> None:
            self.assertEqual(delay_seconds, READINESS_POLL_SECONDS)
            receipt_path.write_text("24680", encoding="ascii")

        sleeper = mock.Mock(side_effect=publish_readiness)
        with (
            mock.patch.object(verifier, "_wait_for_process", delegate),
            _runtime_timeout_after_test_child_ready(
                receipt_path,
                clock=clock,
                sleeper=sleeper,
            ) as process_ids,
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "timed out after 0.25 seconds",
            ),
        ):
            verifier._wait_for_process(
                process,
                output,
                INTENTIONAL_TIMEOUT_SECONDS,
            )

        self.assertEqual(process_ids, [24680])
        delegate.assert_called_once_with(
            process,
            output,
            INTENTIONAL_TIMEOUT_SECONDS,
        )
        sleeper.assert_called_once_with(READINESS_POLL_SECONDS)

    def test_child_exit_observation_rechecks_readiness_receipt(self) -> None:
        receipt_path = self.root / "fast-child.pid"
        raw_process = mock.Mock()

        def publish_then_exit() -> int:
            receipt_path.write_text("24680", encoding="ascii")
            return 0

        raw_process.poll.side_effect = publish_then_exit
        process = cast(subprocess.Popen[bytes], raw_process)
        sleeper = mock.Mock()

        process_id = _wait_for_test_child_pid(
            receipt_path,
            process,
            clock=mock.Mock(return_value=0.0),
            sleeper=sleeper,
        )

        self.assertEqual(process_id, 24680)
        raw_process.poll.assert_called_once_with()
        sleeper.assert_not_called()

    def test_missing_child_readiness_is_a_clear_startup_test_failure(self) -> None:
        receipt_path = self.root / "missing-child.pid"
        raw_process = mock.Mock()
        raw_process.poll.return_value = None
        process = cast(subprocess.Popen[bytes], raw_process)
        delegate = mock.Mock(return_value=0)
        sleeper = mock.Mock()

        with (
            mock.patch.object(verifier, "_wait_for_process", delegate),
            _runtime_timeout_after_test_child_ready(
                receipt_path,
                clock=mock.Mock(side_effect=(0.0, CHILD_READINESS_SECONDS)),
                sleeper=sleeper,
            ) as process_ids,
            self.assertRaisesRegex(
                AssertionError,
                "did not publish a valid PID readiness receipt within 15 seconds",
            ),
        ):
            verifier._wait_for_process(
                process,
                object(),
                INTENTIONAL_TIMEOUT_SECONDS,
            )

        self.assertEqual(process_ids, [])
        delegate.assert_not_called()
        sleeper.assert_not_called()

    def test_production_process_timeout_remains_sixty_seconds(self) -> None:
        timeout_default = inspect.signature(verifier.verify_archive).parameters[
            "timeout_seconds"
        ].default
        self.assertEqual(verifier.PROCESS_TIMEOUT_SECONDS, 60.0)
        self.assertEqual(timeout_default, verifier.PROCESS_TIMEOUT_SECONDS)

    def test_timeout_kills_the_isolated_process_group(self) -> None:
        child_receipt = self.root / "timeout-child.pid"
        body = (
            "/bin/sleep 30 &\n"
            "child=$!\n"
            f"printf '%s' \"$child\" > {shlex.quote(os.fspath(child_receipt))}\n"
            "wait \"$child\"\n"
        )
        with (
            _runtime_timeout_after_test_child_ready(child_receipt) as process_ids,
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "timed out",
            ),
        ):
            self.verify(body, timeout_seconds=INTENTIONAL_TIMEOUT_SECONDS)
        self.assertEqual(len(process_ids), 1)
        _assert_process_gone(self, process_ids[0])

    def test_normal_delayed_xvfb_teardown_is_given_a_bounded_grace(self) -> None:
        archive = _write_archive(
            self.root,
            _executable_script(_success_body()),
        )
        delayed_wrapper = _write_delayed_cleanup_xvfb_run(self.root)

        verifier.verify_archive(
            archive,
            xvfb_run_path=delayed_wrapper,
            timeout_seconds=NON_TIMEOUT_INTEGRATION_SECONDS,
        )

    def test_cleanup_escalates_when_process_group_ignores_sigterm(self) -> None:
        process_receipt = self.root / "term-ignoring-process.pid"
        body = (
            "trap '' TERM\n"
            f"printf '%s' \"$$\" > {shlex.quote(os.fspath(process_receipt))}\n"
            "while :; do /bin/sleep 1; done\n"
        )
        with (
            _runtime_timeout_after_test_child_ready(process_receipt) as process_ids,
            mock.patch.object(verifier, "PROCESS_TERMINATION_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "timed out",
            ),
        ):
            self.verify(body, timeout_seconds=INTENTIONAL_TIMEOUT_SECONDS)
        self.assertEqual(len(process_ids), 1)
        _assert_process_gone(self, process_ids[0])

    def test_group_disappearance_probe_reaps_linux_zombie_first(self) -> None:
        fake_process = _ReapAwareProcess()
        process = cast(subprocess.Popen[bytes], fake_process)

        def reject_probe_before_reap(process_id: int, selected_signal: int) -> None:
            self.assertEqual(process_id, fake_process.pid)
            self.assertEqual(selected_signal, 0)
            self.assertTrue(fake_process.reaped)
            raise ProcessLookupError

        with mock.patch.object(
            verifier.os,
            "killpg",
            side_effect=reject_probe_before_reap,
        ):
            self.assertTrue(verifier._wait_for_group_disappearance(process, 0.1))

    def test_successful_leader_cannot_leave_a_descendant_running(self) -> None:
        child_receipt = self.root / "leaked-child.pid"
        body = (
            _success_body()
            + "/bin/sleep 30 &\n"
            + "child=$!\n"
            + f"printf '%s' \"$child\" > {shlex.quote(os.fspath(child_receipt))}\n"
            + "exit 0\n"
        )
        with (
            _runtime_timeout_after_test_child_ready(child_receipt) as process_ids,
            mock.patch.object(verifier, "PROCESS_GROUP_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "left a descendant process",
            ),
        ):
            self.verify(body)
        self.assertEqual(len(process_ids), 1)
        _assert_process_gone(self, process_ids[0])

    def test_oversized_output_is_rejected_without_pipe_deadlock(self) -> None:
        child_receipt = self.root / "output-child.pid"
        body = (
            "/bin/sleep 30 &\n"
            "child=$!\n"
            f"printf '%s' \"$child\" > {shlex.quote(os.fspath(child_receipt))}\n"
            "i=0\nwhile [ $i -lt 200 ]; do printf x; i=$((i + 1)); done\n"
            "exit 0\n"
        )
        with (
            _runtime_timeout_after_test_child_ready(child_receipt) as process_ids,
            mock.patch.object(verifier, "MAX_PROCESS_OUTPUT_BYTES", 64),
            mock.patch.object(verifier, "PROCESS_GROUP_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "output exceeded",
            ),
        ):
            self.verify(body)
        self.assertEqual(len(process_ids), 1)
        _assert_process_gone(self, process_ids[0])

    def test_archive_path_symlink_is_rejected(self) -> None:
        actual = self.root / "actual.zip"
        archive = _write_archive(self.root, _executable_script(_success_body()))
        archive.rename(actual)
        archive.symlink_to(actual)

        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "without following links",
        ):
            verifier.verify_archive(
                archive,
                xvfb_run_path=self.xvfb_run,
                timeout_seconds=1,
            )

    def test_xvfb_run_symlink_is_rejected(self) -> None:
        real_wrapper = self.root / "real-wrapper"
        self.xvfb_run.rename(real_wrapper)
        self.xvfb_run.symlink_to(real_wrapper)
        archive = _write_archive(
            self.root,
            _executable_script(_success_body()),
        )

        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "executable regular file",
        ):
            verifier.verify_archive(
                archive,
                xvfb_run_path=self.xvfb_run,
                timeout_seconds=1,
            )

    def test_corrupt_member_payload_is_rejected_cleanly(self) -> None:
        archive = _write_archive(
            self.root,
            _executable_script(_success_body()),
        )
        content = bytearray(archive.read_bytes())
        local_header = content.find(b"PK\x03\x04")
        self.assertGreaterEqual(local_header, 0)
        name_length = int.from_bytes(content[local_header + 26 : local_header + 28], "little")
        extra_length = int.from_bytes(content[local_header + 28 : local_header + 30], "little")
        payload_offset = local_header + 30 + name_length + extra_length
        content[payload_offset] ^= 0xFF
        archive.write_bytes(content)

        with self.assertRaises(verifier.LinuxGuiArtifactVerificationError):
            verifier.verify_archive(
                archive,
                xvfb_run_path=self.xvfb_run,
                timeout_seconds=1,
            )

    def test_cli_rejects_relative_and_wrong_basename_paths(self) -> None:
        for argument, message in (
            ("GM2Godot-linux.zip", "absolute path"),
            (os.fspath(self.root / "renamed.zip"), "must be named"),
        ):
            with self.subTest(argument=argument):
                stderr = StringIO()
                with redirect_stderr(stderr):
                    result = verifier.main(["--archive", argument])
                self.assertEqual(result, 1)
                self.assertIn(message, stderr.getvalue())


class LinuxGuiArtifactMemberPolicyTests(unittest.TestCase):
    def exact_members(self) -> list[zipfile.ZipInfo]:
        executable, _ = _member(
            verifier.EXECUTABLE_NAME,
            b"binary",
            mode=0o755,
        )
        executable.file_size = 6
        executable.compress_size = 6
        readme, _ = _member(verifier.README_NAME, b"readme", mode=0o644)
        readme.file_size = 6
        readme.compress_size = 6
        return [executable, readme]

    def test_exact_member_contract_is_accepted(self) -> None:
        selected = verifier._validate_members(self.exact_members())
        self.assertEqual(set(selected), set(verifier.EXPECTED_MEMBER_MODES))

    def test_missing_extra_duplicate_case_and_path_aliases_are_rejected(self) -> None:
        cases: list[list[zipfile.ZipInfo]] = []
        exact = self.exact_members()
        cases.append(exact[:1])

        extra = self.exact_members()
        extra_member, _ = _member("extra", b"x", mode=0o644)
        extra_member.file_size = 1
        extra_member.compress_size = 1
        cases.append([*extra, extra_member])

        duplicate = self.exact_members()
        cases.append([duplicate[0], duplicate[0]])

        for alias in ("gm2godot", "./GM2Godot", "folder/GM2Godot"):
            aliased = self.exact_members()
            aliased[0].filename = alias
            aliased[0].orig_filename = alias
            cases.append(aliased)

        for members in cases:
            with self.subTest(names=[member.filename for member in members]):
                with self.assertRaises(
                    verifier.LinuxGuiArtifactVerificationError
                ):
                    verifier._validate_members(members)

    def test_nul_alias_encryption_and_non_unix_metadata_are_rejected(self) -> None:
        cases: list[list[zipfile.ZipInfo]] = []

        nul_alias = self.exact_members()
        nul_alias[0].orig_filename = "GM2Godot\x00alias"
        cases.append(nul_alias)

        encrypted = self.exact_members()
        encrypted[0].flag_bits |= 0x1
        cases.append(encrypted)

        non_unix = self.exact_members()
        non_unix[0].create_system = 0
        cases.append(non_unix)

        for members in cases:
            with self.subTest(member=members[0].orig_filename):
                with self.assertRaises(
                    verifier.LinuxGuiArtifactVerificationError
                ):
                    verifier._validate_members(members)

    def test_non_deflate_compression_is_rejected_before_extraction(self) -> None:
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(compression=compression):
                members = self.exact_members()
                members[0].compress_type = compression
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    "required DEFLATE compression",
                ):
                    verifier._validate_members(members)

    def test_nonregular_types_and_wrong_modes_are_rejected(self) -> None:
        for file_type in (
            stat.S_IFDIR,
            stat.S_IFLNK,
            stat.S_IFIFO,
            stat.S_IFCHR,
            stat.S_IFBLK,
            stat.S_IFSOCK,
            0,
        ):
            with self.subTest(file_type=file_type):
                members = self.exact_members()
                members[0].external_attr = (file_type | 0o755) << 16
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    "not a regular file",
                ):
                    verifier._validate_members(members)

        for index, mode in ((0, 0o644), (0, 0o4755), (1, 0o755)):
            with self.subTest(index=index, mode=mode):
                members = self.exact_members()
                members[index].external_attr = (stat.S_IFREG | mode) << 16
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    "has mode",
                ):
                    verifier._validate_members(members)

    def test_zero_and_oversized_declared_members_are_rejected(self) -> None:
        cases = (
            (0, 0),
            (0, verifier.MAX_EXECUTABLE_BYTES + 1),
            (1, verifier.MAX_README_BYTES + 1),
        )
        for index, size in cases:
            with self.subTest(index=index, size=size):
                members = self.exact_members()
                members[index].file_size = size
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    "invalid declared size",
                ):
                    verifier._validate_members(members)

    def test_duplicate_archive_entries_are_not_hidden_by_a_dictionary(self) -> None:
        executable, executable_content = _member(
            verifier.EXECUTABLE_NAME,
            b"first",
            mode=0o755,
        )
        duplicate, duplicate_content = _member(
            verifier.EXECUTABLE_NAME,
            b"second",
            mode=0o755,
        )
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive = _write_archive(
                    root,
                    b"unused",
                    members=[
                        (executable, executable_content),
                        (duplicate, duplicate_content),
                    ],
                )
            with zipfile.ZipFile(archive) as opened:
                with self.assertRaises(
                    verifier.LinuxGuiArtifactVerificationError
                ):
                    verifier._validate_members(opened.infolist())


if __name__ == "__main__":
    unittest.main()
