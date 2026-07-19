# pyright: reportPrivateUsage=false

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import time
from typing import cast
import unittest
from unittest import mock
import warnings
import zipfile

from scripts import verify_linux_gui_artifact as verifier


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

    def verify(self, body: str, *, timeout_seconds: float = 3.0) -> None:
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
                f"printf 'wrong\\n' > \"${verifier.GUI_SMOKE_RECEIPT_ENV}\"\n"
                f'chmod 600 "${verifier.GUI_SMOKE_RECEIPT_ENV}"\n',
                "content is invalid",
            ),
            "mode": (
                f"printf '{verifier.GUI_SMOKE_RECEIPT.decode('ascii')}' "
                f' > "${verifier.GUI_SMOKE_RECEIPT_ENV}"\n'
                f'chmod 644 "${verifier.GUI_SMOKE_RECEIPT_ENV}"\n',
                "does not have mode 0600",
            ),
        }
        for name, (body, message) in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    message,
                ):
                    self.verify(body)

    def test_fatal_loader_and_platform_diagnostics_are_rejected(self) -> None:
        for signature in verifier._FATAL_OUTPUT_SIGNATURES:
            with self.subTest(signature=signature):
                body = _success_body(
                    f"printf '%s\\n' '{signature.upper()}' >&2\n"
                )
                with self.assertRaisesRegex(
                    verifier.LinuxGuiArtifactVerificationError,
                    "fatal loader/platform diagnostic",
                ):
                    self.verify(body)

    def test_timeout_kills_the_isolated_process_group(self) -> None:
        child_receipt = self.root / "timeout-child.pid"
        body = (
            "/bin/sleep 30 &\n"
            "child=$!\n"
            f"printf '%s' \"$child\" > {shlex.quote(os.fspath(child_receipt))}\n"
            "wait \"$child\"\n"
        )
        with self.assertRaisesRegex(
            verifier.LinuxGuiArtifactVerificationError,
            "timed out",
        ):
            self.verify(body, timeout_seconds=3.0)
        _assert_process_gone(self, int(child_receipt.read_text(encoding="ascii")))

    def test_normal_delayed_xvfb_teardown_is_given_a_bounded_grace(self) -> None:
        archive = _write_archive(
            self.root,
            _executable_script(_success_body()),
        )
        delayed_wrapper = _write_delayed_cleanup_xvfb_run(self.root)

        verifier.verify_archive(
            archive,
            xvfb_run_path=delayed_wrapper,
            timeout_seconds=3,
        )

    def test_cleanup_escalates_when_process_group_ignores_sigterm(self) -> None:
        process_receipt = self.root / "term-ignoring-process.pid"
        body = (
            "trap '' TERM\n"
            f"printf '%s' \"$$\" > {shlex.quote(os.fspath(process_receipt))}\n"
            "while :; do /bin/sleep 1; done\n"
        )
        with (
            mock.patch.object(verifier, "PROCESS_TERMINATION_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "timed out",
            ),
        ):
            self.verify(body, timeout_seconds=3.0)
        _assert_process_gone(self, int(process_receipt.read_text(encoding="ascii")))

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
            mock.patch.object(verifier, "PROCESS_GROUP_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "left a descendant process",
            ),
        ):
            self.verify(body)
        _assert_process_gone(self, int(child_receipt.read_text(encoding="ascii")))

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
            mock.patch.object(verifier, "MAX_PROCESS_OUTPUT_BYTES", 64),
            mock.patch.object(verifier, "PROCESS_GROUP_GRACE_SECONDS", 0.1),
            self.assertRaisesRegex(
                verifier.LinuxGuiArtifactVerificationError,
                "output exceeded",
            ),
        ):
            self.verify(body)
        _assert_process_gone(self, int(child_receipt.read_text(encoding="ascii")))

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
