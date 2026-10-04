"""Independent ZIP fixtures and real Darwin child-lifecycle regressions."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
import platform
import plistlib
import select
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest import mock

if TYPE_CHECKING:
    from scripts import verify_macos_gui_artifact as subject
else:
    _path = Path(__file__).resolve().parents[1] / "scripts" / "verify_macos_gui_artifact.py"
    _spec = importlib.util.spec_from_file_location("_gm2godot_mac_gui_test_subject", _path)
    if _spec is None or _spec.loader is None:
        raise RuntimeError("exact Mac GUI helper cannot be loaded")
    subject = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = subject
    _spec.loader.exec_module(subject)


POLICY = {"CFBundleIdentifier": "land.infi.gm2godot", "CFBundleShortVersionString": "1.2.3", "CFBundleVersion": "1.2.3", "LSMinimumSystemVersion": "15.0"}
NATIVE_METHODS = (
    "test_native_runtime_is_untranslated",
    "test_native_clean_exit_preserves_owned_leader",
    "test_native_exit_before_observer_registration",
    "test_native_timeout_reaps_owned_group",
    "test_native_inherited_stdout_descendant_is_bounded",
    "test_native_output_budget_stops_owned_group",
    "test_native_observer_and_control_errors_preserve_primary",
)


def _macho(architecture: str = "arm64", minimum: int = 15) -> bytes:
    # Independent literal Darwin ABI fixture: one LC_BUILD_VERSION/macOS15.
    cpu, subtype = (0x0100000C, 0) if architecture == "arm64" else (0x01000007, 3)
    return struct.pack("<IiiIIIII", 0xFEEDFACF, cpu, subtype, 2, 1, 24, 0, 0) + struct.pack("<IIIIII", 0x32, 24, 1, minimum << 16, minimum << 16, 0)


def _record(name: str, content: bytes, mode: int = stat.S_IFREG | 0o644) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    return info, content


def _write_zip(path: Path, *, extra: Sequence[tuple[zipfile.ZipInfo, bytes]] = (), architecture: str = "arm64", minimum: int = 15, resource: bytes = b"ordinary\x00resource") -> None:
    plist = plistlib.dumps({**POLICY, "CFBundleExecutable": "GM2Godot"})
    rows = [
        _record("GM2Godot.app/", b"", stat.S_IFDIR | 0o755),
        _record("GM2Godot.app/Contents/Info.plist", plist),
        _record("GM2Godot.app/Contents/MacOS/GM2Godot", _macho(architecture, minimum), stat.S_IFREG | 0o755),
        _record("GM2Godot.app/Contents/Resources/payload.bin", resource),
        _record("GM2Godot.app/Contents/Resources/current", b"payload.bin", stat.S_IFLNK | 0o777),
        _record("README.md", b"this permitted extra is never extracted"),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for info, content in (*rows, *extra):
            archive.writestr(info, content)


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="mac-gui-fixture-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.zip_path = self.root / "GM2Godot-macos-arm64.zip"
        _write_zip(self.zip_path)

    def extract(self) -> tuple[subject.TreeEntry, ...]:
        return subject.extract_transcript(self.zip_path, self.root / "GM2Godot.app", POLICY, "arm64")


@unittest.skipUnless(os.name == "posix", "physical POSIX ZIP extraction")
class ZipTranscriptTests(Fixture):
    def test_physical_tree_read_races_and_budgets_reject_changed_resources(self) -> None:
        real_open, real_read, real_readlink, real_listdir = os.open, os.read, os.readlink, os.listdir
        for case in ("shrink", "grow", "open-replacement", "read-replacement", "symlink-retarget", "directory-change", "total-budget", "count-budget"):
            with self.subTest(case=case):
                app = self.root / case
                app.mkdir()
                resource = app / "payload"
                payload = b"sealed resource"
                resource.write_bytes(payload)
                link = app / "a-link"
                if case == "symlink-retarget":
                    link.symlink_to("payload")
                self.assertTrue(subject.inspect_tree(app))
                inode = resource.stat().st_ino
                opened: list[int] = []
                changed = False

                def opening(path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
                    nonlocal changed
                    fd = real_open(path, flags, mode, dir_fd=dir_fd)
                    opened.append(fd)
                    if case == "open-replacement" and path == resource.name and not changed:
                        changed = True
                        resource.rename(self.root / (case + "-retained"))
                        resource.write_bytes(payload)
                    return fd

                def reading(fd: int, count: int) -> bytes:
                    nonlocal changed
                    selected = os.fstat(fd).st_ino == inode
                    if selected and not changed and case in {"shrink", "grow"}:
                        changed = True
                        if case == "shrink":
                            resource.write_bytes(b"")
                        else:
                            with resource.open("ab") as writer:
                                writer.write(b"growth")
                    content = real_read(fd, count)
                    if selected and not changed and case == "read-replacement" and not content:
                        changed = True
                        resource.rename(self.root / (case + "-retained"))
                        resource.write_bytes(payload)
                    return content

                def readlink(path: str, *, dir_fd: int | None = None) -> str:
                    nonlocal changed
                    target = real_readlink(path, dir_fd=dir_fd)
                    if case == "symlink-retarget" and path == link.name and not changed:
                        changed = True
                        link.rename(self.root / (case + "-retained"))
                        link.symlink_to("different-resource")
                    return target

                def listing(path: int | str | Path) -> list[str]:
                    nonlocal changed
                    names = real_listdir(path)
                    if case == "directory-change" and not changed:
                        changed = True
                        (app / "new-resource").write_bytes(b"not in the initial directory listing")
                    return names

                messages = {"shrink": "resource truncated", "grow": "resource grew", "open-replacement": "entry changed while opening", "read-replacement": "entry changed while reading", "symlink-retarget": "symlink changed", "directory-change": "directory changed during traversal", "total-budget": "total byte budget", "count-budget": "count budget"}
                budget = mock.patch.object(subject, "MAX_TOTAL_BYTES", len(payload) - 1) if case == "total-budget" else mock.patch.object(subject, "MAX_ENTRIES", 1 if case == "count-budget" else subject.MAX_ENTRIES)
                with mock.patch.object(subject.os, "open", opening), mock.patch.object(subject.os, "read", reading), mock.patch.object(subject.os, "readlink", readlink), mock.patch.object(subject.os, "listdir", listing), budget:
                    with self.assertRaisesRegex(subject.MacGuiVerificationError, messages[case]):
                        subject.inspect_tree(app)
                self.assertTrue(opened)
                for descriptor in opened:
                    with self.assertRaises(OSError) as closed:
                        os.fstat(descriptor)
                    self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_real_pipe_output_eof_deadline_and_budget_are_bounded(self) -> None:
        for case in ("eof", "deadline", "budget"):
            with self.subTest(case=case):
                read_fd, write_fd = os.pipe()
                stream: io.FileIO | None = None
                writer_open = True
                try:
                    stream = io.FileIO(read_fd, mode="rb", closefd=True)
                    os.set_blocking(read_fd, False)
                    output = bytearray()
                    if case == "eof":
                        self.assertFalse(getattr(subject, "_read_output")(stream, output))
                        self.assertEqual(output, b"")
                        os.write(write_fd, b"real output")
                        self.assertFalse(getattr(subject, "_read_output")(stream, output))
                        self.assertEqual(output, b"real output")
                        os.close(write_fd)
                        writer_open = False
                        with self.assertRaises(OSError) as closed:
                            os.fstat(write_fd)
                        self.assertEqual(closed.exception.errno, errno.EBADF)
                        self.assertTrue(getattr(subject, "_read_output")(stream, output))
                        getattr(subject, "_drain_output")(stream, output, timeout=0.02)
                        self.assertEqual(output, b"real output")
                    elif case == "deadline":
                        os.write(write_fd, b"still open")
                        started = time.monotonic()
                        with self.assertRaisesRegex(subject.MacGuiVerificationError, "stdout.*drain deadline"):
                            getattr(subject, "_drain_output")(stream, output, timeout=0.02)
                        self.assertLess(time.monotonic() - started, 1.0)
                        self.assertEqual(output, b"still open")
                        self.assertFalse(stream.closed)
                        os.fstat(write_fd)
                    else:
                        os.write(write_fd, b"12345")
                        with mock.patch.object(subject, "MAX_OUTPUT_BYTES", 4):
                            with self.assertRaisesRegex(subject.MacGuiVerificationError, "output exceeds.*byte budget"):
                                getattr(subject, "_read_output")(stream, output)
                        self.assertEqual(output, b"12345")
                finally:
                    if writer_open:
                        os.close(write_fd)
                    if stream is None:
                        os.close(read_fd)
                    else:
                        stream.close()
                    for descriptor in (read_fd, write_fd):
                        with self.assertRaises(OSError) as closed:
                            os.fstat(descriptor)
                        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_complete_resource_transcript_and_physical_tree_match(self) -> None:
        rows = self.extract()
        self.assertEqual(rows, subject.inspect_tree(self.root / "GM2Godot.app"))
        resource = next(row for row in rows if row.path == "Contents/Resources/payload.bin")
        self.assertEqual((resource.sha256, resource.size, resource.mode), (hashlib.sha256(b"ordinary\x00resource").hexdigest(), 17, 0o644))
        self.assertEqual((self.root / "GM2Godot.app/Contents/Resources/current").readlink(), Path("payload.bin"))
        self.assertFalse((self.root / "README.md").exists())

    def test_full_non_macho_resource_and_directory_mode_drift_are_detected(self) -> None:
        rows = self.extract()
        resource = self.root / "GM2Godot.app/Contents/Resources/payload.bin"
        original = resource.stat()
        resource.write_bytes(b"changed!\x00resource")
        os.utime(resource, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertNotEqual(rows, subject.inspect_tree(self.root / "GM2Godot.app"))
        resource.write_bytes(b"ordinary\x00resource")
        resource.chmod(0o600)
        self.assertNotEqual(rows, subject.inspect_tree(self.root / "GM2Godot.app"))
        resource.chmod(0o644)
        (resource.parent).chmod(0o700)
        self.assertNotEqual(rows, subject.inspect_tree(self.root / "GM2Godot.app"))

    def test_extra_symlink_and_hardlinked_physical_resources_are_rejected(self) -> None:
        rows = self.extract()
        app = self.root / "GM2Godot.app"
        (app / "unexpected").symlink_to("Contents/Resources/payload.bin")
        self.assertNotEqual(rows, subject.inspect_tree(app))
        (app / "unexpected").unlink()
        os.link(app / "Contents/Resources/payload.bin", app / "hardlink")
        with self.assertRaisesRegex(subject.MacGuiVerificationError, "linked file"):
            subject.inspect_tree(app)

    def test_path_case_type_link_and_duplicate_attacks_fail_before_extraction(self) -> None:
        cases = (
            _record("GM2Godot.app/../escape", b"bad"),
            _record("GM2Godot.app/Contents/resources/PAYLOAD.bin", b"bad"),
            _record("GM2Godot.app/Contents/Resources/fifo", b"", stat.S_IFIFO | 0o600),
            _record("GM2Godot.app/Contents/Resources/escape", b"../../../../escape", stat.S_IFLNK | 0o777),
            _record("GM2Godot.app/Contents/Resources/payload.bin", b"duplicate"),
        )
        for row in cases:
            with self.subTest(member=row[0].filename):
                with mock.patch("warnings.warn"):
                    _write_zip(self.zip_path, extra=(row,))
                with self.assertRaises(Exception):
                    self.extract()
                self.assertFalse((self.root / "GM2Godot.app").exists())

    def test_encrypted_directory_and_resource_are_rejected(self) -> None:
        for name in ("GM2Godot.app/", "GM2Godot.app/Contents/Resources/payload.bin"):
            with self.subTest(name=name):
                _write_zip(self.zip_path)
                content = bytearray(self.zip_path.read_bytes())
                wanted = name.encode()
                for signature, flag_offset, name_offset in ((b"PK\x03\x04", 6, 30), (b"PK\x01\x02", 8, 46)):
                    position = 0
                    while (position := content.find(signature, position)) >= 0:
                        if bytes(content[position + name_offset:position + name_offset + len(wanted)]) == wanted:
                            flags = struct.unpack_from("<H", content, position + flag_offset)[0]
                            struct.pack_into("<H", content, position + flag_offset, flags | 1)
                            break
                        position += 4
                self.zip_path.write_bytes(content)
                with self.assertRaisesRegex(Exception, "encrypted"):
                    self.extract()
                self.assertFalse((self.root / "GM2Godot.app").exists())

    def test_file_total_entry_and_depth_limits_reject_finite_positive_controls(self) -> None:
        controls = (("MAX_FILE_BYTES", 55), ("MAX_TOTAL_BYTES", 1), ("MAX_ENTRIES", 2), ("MAX_DEPTH", 2))
        for name, value in controls:
            with self.subTest(limit=name), mock.patch.object(subject, name, value):
                with self.assertRaisesRegex(subject.MacGuiVerificationError, "budget|unsafe"):
                    self.extract()
                self.assertFalse((self.root / "GM2Godot.app").exists())

    def test_crc_and_truncated_zip_payloads_fail(self) -> None:
        original = self.zip_path.read_bytes()
        corrupted = bytearray(original)
        position = corrupted.index(b"ordinary\x00resource")
        corrupted[position] ^= 1
        for value in (bytes(corrupted), original[:-30]):
            with self.subTest(length=len(value)):
                self.zip_path.write_bytes(value)
                with self.assertRaises(Exception):
                    self.extract()

    def test_regular_copy_rejects_link_substitution_growth_and_caps(self) -> None:
        destination = self.root / "copy.zip"
        copied = subject.copy_zip(self.zip_path, destination)
        self.assertEqual(copied.sha256, hashlib.sha256(self.zip_path.read_bytes()).hexdigest())
        self.assertEqual(destination.read_bytes(), self.zip_path.read_bytes())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        destination.unlink()
        os.link(self.zip_path, self.root / "alias.zip")
        with self.assertRaisesRegex(subject.MacGuiVerificationError, "singly linked"):
            subject.copy_zip(self.zip_path, destination)
        (self.root / "alias.zip").unlink()
        with mock.patch.object(subject, "MAX_ZIP_BYTES", 1):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "bounded"):
                subject.copy_zip(self.zip_path, destination)
        real_read = os.read
        changed = False
        source_inode = self.zip_path.stat().st_ino

        def grow(fd: int, count: int) -> bytes:
            nonlocal changed
            result = real_read(fd, count)
            if not changed and os.fstat(fd).st_ino == source_inode:
                changed = True
                with self.zip_path.open("ab") as stream:
                    stream.write(b"growth")
            return result

        with mock.patch.object(subject.os, "read", grow):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "grew|changed"):
                subject.copy_zip(self.zip_path, destination)

    def test_retained_ancestry_and_exact_descriptor_closure(self) -> None:
        directory = self.root / "owned"
        directory.mkdir()
        owner = subject.BoundDirectory(directory)
        descriptor = owner.fd
        directory.rename(self.root / "moved")
        directory.mkdir()
        with self.assertRaisesRegex(subject.MacGuiVerificationError, "ancestry changed"):
            owner.verify()
        owner.close()
        with self.assertRaises(OSError) as closed:
            os.fstat(descriptor)
        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_allowed_extras_are_crc_checked_and_unsafe_extras_rejected(self) -> None:
        _write_zip(self.zip_path, extra=(
            _record("__MACOSX/", b"", stat.S_IFDIR | 0o775),
            _record("__MACOSX/GM2Godot.app/", b"", stat.S_IFDIR | 0o775),
            _record("__MACOSX/GM2Godot.app/._resource", b"literal AppleDouble fixture"),
        ))
        self.assertEqual(self.extract(), subject.inspect_tree(self.root / "GM2Godot.app"))
        self.assertFalse((self.root / "__MACOSX").exists())
        # New fixture roots avoid borrowing partially extracted state.
        cases = (
            _record("unreviewed.txt", b"extra"),
            _record("__MACOSX/._alias", b"README.md", stat.S_IFLNK | 0o777),
            _record("__MACOSX/ordinary", b"unreviewed"),
            _record("__MACOSX/._fifo", b"", stat.S_IFIFO | 0o600),
        )
        for index, row in enumerate(cases):
            with self.subTest(name=row[0].filename):
                _write_zip(self.zip_path, extra=(row,))
                app = self.root / f"case-{index}" / "GM2Godot.app"
                app.parent.mkdir()
                with self.assertRaisesRegex(subject.MacGuiVerificationError, "extra member"):
                    subject.extract_transcript(self.zip_path, app, POLICY, "arm64")
                self.assertFalse(app.exists())
        _write_zip(self.zip_path, extra=(_record("__MACOSX/._resource", b"CRC extra control"),))
        value = bytearray(self.zip_path.read_bytes())
        value[value.index(b"CRC extra control")] ^= 1
        self.zip_path.write_bytes(value)
        with self.assertRaises(zipfile.BadZipFile):
            subject.extract_transcript(self.zip_path, self.root / "crc/GM2Godot.app", POLICY, "arm64")

    def test_copy_seals_destination_identity_and_original_bytes_before_return(self) -> None:
        original = self.zip_path.read_bytes()
        alternative = self.root / "alternative.zip"
        _write_zip(alternative, resource=b"changed!\x00resource")
        altered = alternative.read_bytes()
        self.assertEqual(len(altered), len(original))
        self.assertNotEqual(altered, original)
        real_fsync = os.fsync
        for replace in (False, True):
            destination = self.root / f"private-{replace}.zip"

            def mutate_after_fsync(fd: int) -> None:
                real_fsync(fd)
                if replace:
                    destination.rename(self.root / "retained-original.zip")
                destination.write_bytes(altered)
                destination.chmod(0o600)

            with self.subTest(replace=replace), mock.patch.object(subject.os, "fsync", mutate_after_fsync):
                with self.assertRaisesRegex(subject.MacGuiVerificationError, "private ZIP bytes|retained file changed"):
                    subject.copy_zip(self.zip_path, destination)
            self.assertEqual(self.zip_path.read_bytes(), original)


class ReceiptAndRuntimeTests(Fixture):
    def test_modeled_exit_record_and_group_census_never_excuse_live_or_malformed_groups(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        process.pid = 12345
        process.returncode = None
        positive_exit = getattr(subject, "_positive_child_exit")
        census = getattr(subject, "_group_contains_only_exited_leader")
        exit_record = struct.pack("=iiiiIi", 20, 0, 1, process.pid, 1000, 0) + bytes(80)
        records = ((bytes(104), False), (exit_record, True), (exit_record[:-1], None), (struct.pack("=iiiiIi", 20, 0, 1, 54321, 1000, 0) + bytes(80), None), (struct.pack("=iiiiIi", 20, 0, 5, process.pid, 1000, 0) + bytes(80), None))
        with mock.patch.object(subject.sys, "platform", "darwin"), mock.patch.object(subject.signal, "SIGCHLD", 20, create=True), mock.patch.object(subject.os, "CLD_EXITED", 1, create=True), mock.patch.object(subject.os, "CLD_KILLED", 2, create=True), mock.patch.object(subject.os, "CLD_DUMPED", 3, create=True):
            for record, expected in records:
                with self.subTest(record=record[:24]), mock.patch.object(subject, "_waitid_record", return_value=record):
                    if expected is None:
                        with self.assertRaises(subject.MacGuiVerificationError):
                            positive_exit(process)
                    else:
                        self.assertIs(positive_exit(process), expected)

        class Census:
            def __init__(self, members: tuple[int, ...], returned: int | None = None, failure: int = 0) -> None:
                self.members = members
                self.returned = returned
                self.failure = failure
                self.calls = 0
                self.argtypes: list[object] = []
                self.restype: object = None

            def __call__(self, kind: int, pid: int, buffer: ctypes.c_void_p, capacity: int) -> int:
                self.calls += 1
                self_outer.assertEqual((kind, pid), (2, process.pid))
                self_outer.assertEqual(ctypes.get_errno(), 0)
                rows = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int32))
                for index, member in enumerate(self.members):
                    rows[index] = member
                ctypes.set_errno(self.failure)
                return len(self.members) * 4 if self.returned is None else self.returned

        class Library:
            def __init__(self, function: Census) -> None:
                self.proc_listpids = function

        self_outer = self
        for members, returned, expected in (((12345,), None, True), ((12345, 54321), None, False), ((12345, 12345), None, False), ((0,), None, False), ((54321,), None, False), ((), 0, None), ((), -1, None), ((12345,), 3, None), ((12345,), 12, None)):
            function = Census(members, returned)
            with self.subTest(members=members, returned=returned), mock.patch.object(subject, "_prove_process"), mock.patch.object(subject, "_positive_child_exit", return_value=True), mock.patch.object(subject, "_libc", return_value=Library(function)), mock.patch.object(subject, "MAX_GROUP_MEMBERS", 2):
                if expected is None:
                    with self.assertRaises(subject.MacGuiVerificationError):
                        census(process)
                else:
                    self.assertIs(census(process), expected)
                if expected is True:
                    self.assertEqual(function.calls, 2)
                    self.assertEqual(function.argtypes, [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int])
                    self.assertIs(function.restype, ctypes.c_int)
        function = Census((12345,), failure=errno.EPERM)
        with mock.patch.object(subject, "_prove_process"), mock.patch.object(subject, "_positive_child_exit", return_value=True), mock.patch.object(subject, "_libc", return_value=Library(function)):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "errno 1"):
                census(process)
        with mock.patch.object(subject, "_prove_process"), mock.patch.object(subject, "_positive_child_exit", return_value=False), mock.patch.object(subject, "_libc") as library:
            self.assertFalse(census(process))
            library.assert_not_called()
        permission = PermissionError(errno.EPERM, "modeled live-group denial")
        with mock.patch.object(subject.sys, "platform", "darwin"), mock.patch.object(subject.signal, "SIGKILL", 9, create=True), mock.patch.object(subject, "_prove_process"), mock.patch.object(subject, "_group_contains_only_exited_leader", return_value=False), mock.patch.object(subject.os, "killpg", side_effect=permission, create=True):
            with self.assertRaises(PermissionError) as caught:
                getattr(subject, "_group_signal")(process)
            self.assertIs(caught.exception, permission)

    def test_unsupported_ownership_policy_and_api_fail_before_child_creation(self) -> None:
        with mock.patch.object(subject.signal, "getsignal", return_value=signal.SIG_IGN), mock.patch.object(subject.subprocess, "Popen") as spawn:
            with self.assertRaises(ChildProcessError):
                subject.run_gui_process([sys.executable], self.root, dict(os.environ))
            spawn.assert_not_called()
        error = RuntimeError("unsupported ABI")
        with mock.patch.object(subject, "_require_default_sigchld"), mock.patch.object(subject, "_waitid_api", side_effect=error), mock.patch.object(subject.subprocess, "Popen") as spawn:
            with self.assertRaises(RuntimeError) as caught:
                subject.run_gui_process([sys.executable], self.root, dict(os.environ))
            self.assertIs(caught.exception, error)
            spawn.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "physical POSIX receipt binding")
    def test_receipt_is_exact_fresh_regular_one_link_and_private(self) -> None:
        path = self.root / "gui-ready.receipt"
        with self.assertRaises(OSError):
            subject.validate_gui_receipt(path)
        path.write_bytes(b"GM2Godot packaged GUI ready\n")
        path.chmod(0o600)
        self.assertEqual(subject.validate_gui_receipt(path), hashlib.sha256(path.read_bytes()).hexdigest())
        for value, mode in ((b"wrong", 0o600), (b"GM2Godot packaged GUI ready\n", 0o644)):
            path.write_bytes(value)
            path.chmod(mode)
            with self.assertRaises(subject.MacGuiVerificationError):
                subject.validate_gui_receipt(path)
        path.chmod(0o600)
        alias = self.root / "alias"
        os.link(path, alias)
        with self.assertRaises(subject.MacGuiVerificationError):
            subject.validate_gui_receipt(path)
        alias.unlink()
        path.unlink()
        path.symlink_to(self.zip_path)
        with self.assertRaises(Exception):
            subject.validate_gui_receipt(path)

    def test_private_environment_preserves_cocoa_and_removes_injection(self) -> None:
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen", "DYLD_INSERT_LIBRARIES": "bad", "PYTHONPATH": "bad", "KEEP_ME": "yes"}):
            environment = subject.gui_environment(self.root, self.root / "receipt")
        self.assertEqual(environment["KEEP_ME"], "yes")
        for key in ("QT_QPA_PLATFORM", "DYLD_INSERT_LIBRARIES", "PYTHONPATH"):
            self.assertNotIn(key, environment)
        self.assertEqual(environment["HOME"], str(self.root / "home"))
        self.assertTrue((self.root / "home").is_dir())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.root / "home").stat().st_mode), 0o700)

    def test_modeled_sysctl_native_translated_enoent_size_and_errors(self) -> None:
        class Sysctl:
            argtypes: list[object] = []
            restype: object = None

            def __init__(self, result: int, value: int, size: int, failure: int) -> None:
                self.result, self.value, self.size, self.failure = result, value, size, failure

            def __call__(self, name: bytes, output: object, size: object, _new: object, _new_size: int) -> int:
                self_test.assertEqual(name, b"sysctl.proc_translated")
                ctypes.cast(cast(ctypes.c_void_p, output), ctypes.POINTER(ctypes.c_int))[0] = self.value
                ctypes.cast(cast(ctypes.c_void_p, size), ctypes.POINTER(ctypes.c_size_t))[0] = self.size
                ctypes.set_errno(self.failure)
                return self.result

        class Library:
            def __init__(self, function: Sysctl) -> None:
                self.sysctlbyname = function

        self_test = self
        controls = ((0, 0, 4, 0, True), (0, 1, 4, 0, False), (-1, -1, 4, errno.ENOENT, True), (0, 0, 8, 0, False), (0, 7, 4, 0, False), (-1, 0, 4, errno.EPERM, False))
        for result, value, size, failure, allowed in controls:
            with self.subTest(result=result, value=value, size=size, failure=failure):
                function = Sysctl(result, value, size, failure)
                with mock.patch.object(subject, "_libc", return_value=Library(function)), mock.patch.object(subject.platform, "python_implementation", return_value="CPython"), mock.patch.object(subject.platform, "python_version", return_value="3.12.10"), mock.patch.object(subject.platform, "system", return_value="Darwin"), mock.patch.object(subject.platform, "machine", return_value="arm64"), mock.patch.object(subject.sys, "platform", "darwin"):
                    if allowed:
                        self.assertFalse(subject.require_native_runtime("arm64")["translated"])
                    else:
                        with self.assertRaises(subject.MacGuiVerificationError):
                            subject.require_native_runtime("arm64")
                self.assertEqual(function.restype, ctypes.c_int)
                self.assertEqual(function.argtypes[0], ctypes.c_char_p)

    def test_wrong_runtime_and_cli_failure_never_write_success_receipt(self) -> None:
        output = self.root / "output.json"
        with mock.patch.object(subject.platform, "machine", return_value="unknown"):
            with self.assertRaises(subject.MacGuiVerificationError):
                subject.require_native_runtime("arm64")
        for failure in (KeyboardInterrupt(), SystemExit(0), OSError("write failed")):
            with self.subTest(kind=type(failure).__name__), mock.patch.object(subject, "verify_archive", side_effect=failure), redirect_stderr(io.StringIO()):
                self.assertEqual(subject.main(["--source-root", str(self.root), "--zip", str(self.zip_path), "--expected-architecture", "arm64", "--output", str(output)]), 2)
                self.assertFalse(output.exists())


@unittest.skipUnless(os.name == "posix", "physical POSIX App transcript")
class PipelineTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        policy = self.root / "source/packaging/macos/bundle_metadata.py"
        policy.parent.mkdir(parents=True)
        policy.write_text("from pathlib import Path\ndef load_bundle_metadata(source_root: Path) -> dict[str, str]:\n    return " + repr(POLICY) + "\n")
        self.source_root = self.root / "source"

    def fake_gui(self, _command: Sequence[str], root: Path, environment: dict[str, str]) -> subject.ProcessReceipt:
        path = Path(environment["GM2GODOT_GUI_SMOKE_RECEIPT"])
        self.assertTrue(root.name.startswith("gm2godot-macos-gui-"))
        self.assertFalse(path.exists())
        path.write_bytes(b"GM2Godot packaged GUI ready\n")
        path.chmod(0o600)
        return subject.ProcessReceipt(0, b"synthetic lifecycle seam", 0.01)

    def run_pipeline(self, callback: Callable[[Sequence[str], Path, dict[str, str]], subject.ProcessReceipt]) -> dict[str, object]:
        with mock.patch.object(subject, "require_native_runtime", return_value={"explicitly_modeled": True}), mock.patch.object(subject, "run_gui_process", side_effect=callback):
            return subject.verify_archive(self.source_root, self.zip_path, "arm64")

    def test_synthetic_pipeline_binds_all_resources_and_only_zip_gui_form(self) -> None:
        value = self.run_pipeline(self.fake_gui)
        self.assertEqual(value["zip_sha256"], hashlib.sha256(self.zip_path.read_bytes()).hexdigest())
        self.assertFalse(value["source_app_gui_tested"])
        self.assertFalse(value["dmg_gui_tested"])
        self.assertTrue(value["successful"])

    def test_successful_pipeline_cleanup_failures_preserve_first_error_and_close_all_owners(self) -> None:
        real_owner = subject.BoundDirectory
        real_close = real_owner.close
        real_cleanup = getattr(subject, "_cleanup_private_root")
        for stage in ("cleanup", "root-close", "source-close", "combined"):
            with self.subTest(stage=stage):
                first = OSError("first forwarded cleanup failure")
                root_error = OSError("forwarded root close failure")
                source_error = OSError("forwarded source close failure")
                owners: list[tuple[subject.BoundDirectory, tuple[int, ...]]] = []
                closes: dict[int, int] = {}
                source_owner: subject.BoundDirectory | None = None
                private_owner: subject.BoundDirectory | None = None

                def acquire(path: Path) -> subject.BoundDirectory:
                    nonlocal source_owner, private_owner
                    owner = real_owner(path)
                    owners.append((owner, tuple(item[2] for item in owner.bindings)))
                    if path == self.zip_path.parent and source_owner is None:
                        source_owner = owner
                    if path.name.startswith("gm2godot-macos-gui-") and private_owner is None:
                        private_owner = owner
                    return owner

                def close(owner: subject.BoundDirectory, primary: BaseException | None = None) -> None:
                    closes[id(owner)] = closes.get(id(owner), 0) + 1
                    real_close(owner, primary)
                    if owner is private_owner and stage in {"root-close", "combined"}:
                        raise root_error
                    if owner is source_owner and stage in {"source-close", "combined"}:
                        raise source_error

                def cleanup(owner: subject.BoundDirectory) -> None:
                    real_cleanup(owner)
                    if stage in {"cleanup", "combined"}:
                        raise first

                with mock.patch.object(subject, "BoundDirectory", side_effect=acquire), mock.patch.object(real_owner, "close", close), mock.patch.object(subject, "_cleanup_private_root", cleanup):
                    with self.assertRaises(OSError) as caught:
                        self.run_pipeline(self.fake_gui)
                expected = root_error if stage == "root-close" else source_error if stage == "source-close" else first
                self.assertIs(caught.exception, expected)
                self.assertIsNotNone(source_owner)
                self.assertIsNotNone(private_owner)
                if private_owner is not None:
                    self.assertFalse(private_owner.path.exists())
                for owner, descriptors in owners:
                    self.assertEqual(closes.get(id(owner)), 1)
                    self.assertEqual(owner.bindings, [])
                    for descriptor in descriptors:
                        with self.assertRaises(OSError) as closed:
                            os.fstat(descriptor)
                        self.assertEqual(closed.exception.errno, errno.EBADF)
                if stage == "combined":
                    notes = getattr(caught.exception, "__notes__", ())
                    self.assertTrue(any(str(root_error) in note for note in notes))
                    self.assertTrue(any(str(source_error) in note for note in notes))

    def test_source_replacement_and_full_resource_flip_after_launch_fail(self) -> None:
        def replace(command: Sequence[str], root: Path, environment: dict[str, str]) -> subject.ProcessReceipt:
            value = self.fake_gui(command, root, environment)
            original = self.zip_path.read_bytes()
            self.zip_path.rename(self.root / "old.zip")
            self.zip_path.write_bytes(original)
            return value

        with self.assertRaisesRegex(subject.MacGuiVerificationError, "source ZIP binding changed"):
            self.run_pipeline(replace)
        (self.root / "old.zip").unlink()

        def flip(command: Sequence[str], root: Path, environment: dict[str, str]) -> subject.ProcessReceipt:
            value = self.fake_gui(command, root, environment)
            path = root / "GM2Godot.app/Contents/Resources/payload.bin"
            before = path.stat()
            path.write_bytes(b"changed!\x00resource")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            return value

        with self.assertRaisesRegex(subject.MacGuiVerificationError, "resources changed"):
            self.run_pipeline(flip)

    def test_missing_receipt_primary_control_and_cleanup_failures_block_success(self) -> None:
        roots: list[Path] = []

        def absent(_command: Sequence[str], root: Path, _environment: dict[str, str]) -> subject.ProcessReceipt:
            roots.append(root)
            return subject.ProcessReceipt(0, b"", 0.01)

        with self.assertRaises(OSError):
            self.run_pipeline(absent)
        self.assertTrue(all(not path.exists() for path in roots))
        primary = KeyboardInterrupt("retained primary")

        def fail(_command: Sequence[str], root: Path, _environment: dict[str, str]) -> subject.ProcessReceipt:
            roots.append(root)
            raise primary

        with self.assertRaises(KeyboardInterrupt) as caught:
            self.run_pipeline(fail)
        self.assertIs(caught.exception, primary)
        self.assertTrue(all(not path.exists() for path in roots))
        original_cleanup = getattr(subject, "_cleanup_private_root")

        def cleanup_then_fail(owner: subject.BoundDirectory) -> None:
            original_cleanup(owner)
            raise OSError("cleanup evidence")

        with mock.patch.object(subject, "_cleanup_private_root", cleanup_then_fail):
            with self.assertRaises(KeyboardInterrupt) as combined:
                self.run_pipeline(fail)
        self.assertIs(combined.exception, primary)
        self.assertTrue(any("cleanup evidence" in item for item in getattr(primary, "__notes__", ())))

    def test_native_minimum_above_plist_declaration_fails_before_gui(self) -> None:
        _write_zip(self.zip_path, minimum=16)
        with mock.patch.object(subject, "require_native_runtime", return_value={"explicitly_modeled": True}), mock.patch.object(subject, "run_gui_process") as launch:
            with self.assertRaisesRegex(Exception, "below native Mach-O requirement 16.0"):
                subject.verify_archive(self.source_root, self.zip_path, "arm64")
            launch.assert_not_called()

    def test_acquisition_failures_close_owned_ancestry_and_preserve_primary(self) -> None:
        real_owner = subject.BoundDirectory
        real_stat = os.stat
        real_mkdtemp = tempfile.mkdtemp
        for stage in ("stat", "mkdtemp", "owner"):
            primary = OSError(f"injected {stage} acquisition failure")
            descriptors: list[int] = []
            private_roots: list[Path] = []
            source_acquired = False

            def acquire(path: Path) -> subject.BoundDirectory:
                nonlocal source_acquired
                if stage == "owner" and path.name.startswith("gm2godot-macos-gui-"):
                    raise primary
                owner = real_owner(path)
                if path == self.zip_path.parent:
                    source_acquired = True
                    descriptors.extend(item[2] for item in owner.bindings)
                return owner

            def source_stat(path: str | Path, *, dir_fd: int | None = None, follow_symlinks: bool = True) -> os.stat_result:
                if stage == "stat" and source_acquired and path == self.zip_path.name:
                    raise primary
                return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

            def temporary(*, prefix: str) -> str:
                if stage == "mkdtemp":
                    raise primary
                path = real_mkdtemp(prefix=prefix, dir=self.root)
                private_roots.append(Path(path))
                return path

            with self.subTest(stage=stage), mock.patch.object(subject, "BoundDirectory", side_effect=acquire), mock.patch.object(subject.os, "stat", side_effect=source_stat), mock.patch.object(subject.tempfile, "mkdtemp", side_effect=temporary):
                with self.assertRaises(OSError) as caught:
                    self.run_pipeline(self.fake_gui)
                self.assertIs(caught.exception, primary)
            self.assertTrue(descriptors)
            for fd in descriptors:
                with self.assertRaises(OSError) as closed:
                    os.fstat(fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)
            self.assertTrue(all(not path.exists() for path in private_roots))

    def test_new_private_root_replacement_is_not_written_or_recursively_removed(self) -> None:
        real_owner = subject.BoundDirectory
        real_mkdtemp = tempfile.mkdtemp
        roots: list[Path] = []
        moved: list[Path] = []

        def temporary(*, prefix: str) -> str:
            path = real_mkdtemp(prefix=prefix, dir=self.root)
            roots.append(Path(path))
            return path

        def substitute(path: Path) -> subject.BoundDirectory:
            if path in roots:
                old = path.with_name(path.name + "-original")
                path.rename(old)
                moved.append(old)
                path.mkdir(mode=0o700)
                (path / "foreign-sentinel").write_bytes(b"must remain untouched")
            return real_owner(path)

        with mock.patch.object(subject, "BoundDirectory", side_effect=substitute), mock.patch.object(subject.tempfile, "mkdtemp", side_effect=temporary):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "root changed during acquisition") as caught:
                self.run_pipeline(self.fake_gui)
        self.assertEqual(len(roots), 1)
        self.assertEqual((roots[0] / "foreign-sentinel").read_bytes(), b"must remain untouched")
        self.assertEqual(tuple(path.name for path in roots[0].iterdir()), ("foreign-sentinel",))
        self.assertEqual(tuple(moved[0].iterdir()), ())
        self.assertTrue(any("replacement is retained" in note for note in getattr(caught.exception, "__notes__", ())))

    def test_private_zip_cannot_absorb_a_valid_same_size_substitution(self) -> None:
        real_copy = subject.copy_zip
        alternative = self.root / "alternative.zip"
        _write_zip(alternative, resource=b"changed!\x00resource")
        original = self.zip_path.read_bytes()
        self.assertEqual(len(original), alternative.stat().st_size)

        def replace_after_copy(source: Path, destination: Path) -> subject.ZipCopy:
            receipt = real_copy(source, destination)
            destination.unlink()
            destination.write_bytes(alternative.read_bytes())
            destination.chmod(0o600)
            return receipt

        with mock.patch.object(subject, "require_native_runtime", return_value={"explicitly_modeled": True}), mock.patch.object(subject, "copy_zip", side_effect=replace_after_copy), mock.patch.object(subject, "run_gui_process") as launch:
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "sealed original/private ZIP binding changed"):
                subject.verify_archive(self.source_root, self.zip_path, "arm64")
            launch.assert_not_called()
        self.assertEqual(self.zip_path.read_bytes(), original)


@unittest.skipUnless(sys.platform == "darwin", "real Darwin kqueue/libc lifecycle")
class NativeLifecycleTests(Fixture):
    """Real native children; these tests do not claim a packaged Cocoa launch."""

    def command(self, code: str) -> list[str]:
        path = self.root / "child.py"
        path.write_text(code)
        return [sys.executable, "-I", str(path)]

    def launch(self, code: str, *, timeout: float = 3.0) -> subject.ProcessReceipt:
        return subject.run_gui_process(self.command(code), self.root, dict(os.environ), timeout=timeout)

    def test_native_runtime_is_untranslated(self) -> None:
        value = subject.require_native_runtime(platform.machine(), pinned_python=False)
        self.assertFalse(value["translated"])
        self.assertEqual(value["machine"], platform.machine())

    def test_native_clean_exit_preserves_owned_leader(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("native lifecycle requires Darwin")
        seen: list[int] = []
        real_signal = getattr(subject, "_group_signal")

        def signal_owned(process: subprocess.Popen[bytes]) -> None:
            self.assertIsNone(process.returncode)
            seen.append(process.pid)
            real_signal(process)

        with mock.patch.object(subject, "_group_signal", signal_owned):
            result = self.launch("print('native clean output')\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.output, b"native clean output\n")
        self.assertEqual(len(seen), 1)
        with self.assertRaises(ChildProcessError):
            os.waitpid(seen[0], os.WNOHANG)
        census = getattr(subject, "_group_contains_only_exited_leader")
        observations: list[bool] = []

        def silent_member(process: subprocess.Popen[bytes]) -> None:
            self.assertIsNone(process.returncode)
            observations.append(bool(census(process)))
            real_signal(process)

        code = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)\nprint('silent same-group child')\n"
        with mock.patch.object(subject, "_group_signal", silent_member):
            self.assertEqual(self.launch(code).returncode, 0)
        self.assertEqual(observations, [False], "a live silent member must not qualify as a zombie-only group")

    def test_native_exit_before_observer_registration(self) -> None:
        original = getattr(subject, "_observe_exit")
        real_proof = getattr(subject, "_prove_process")

        def after_eof(process: subprocess.Popen[bytes], stream: io.BufferedReader, output: bytearray, deadline: float) -> bool:
            # Read readiness to EOF without a reaping wait/poll; the real child
            # exits before the real kqueue registration below.
            while True:
                if time.monotonic() >= deadline:
                    self.fail("finite child did not close stdout before the observer deadline")
                try:
                    data = os.read(stream.fileno(), 1024)
                except BlockingIOError:
                    select.select([stream], [], [], 0.05)
                    continue
                output.extend(data)
                if not data:
                    break
            self.assertIsNone(process.returncode)
            real_proof(process)
            while not getattr(subject, "_positive_child_exit")(process):
                if time.monotonic() >= deadline:
                    self.fail("finite child has EOF but no positive terminal kernel event")
                time.sleep(0.001)
            return bool(original(process, stream, output, deadline))

        with mock.patch.object(subject, "_observe_exit", after_eof):
            self.assertEqual(self.launch("print('immediate exit')\n").output, b"immediate exit\n")

    def test_native_timeout_reaps_owned_group(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("native lifecycle requires Darwin")
        processes: list[subprocess.Popen[bytes]] = []
        real_popen = subprocess.Popen

        def capture(command: Sequence[str], *, cwd: Path, env: dict[str, str], stdin: int, stdout: int, stderr: int, shell: bool, close_fds: bool, start_new_session: bool) -> subprocess.Popen[bytes]:
            process = real_popen(command, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell, close_fds=close_fds, start_new_session=start_new_session)
            processes.append(process)
            return process

        with mock.patch.object(subject.subprocess, "Popen", side_effect=capture):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "runtime deadline"):
                self.launch("import time\ntime.sleep(30)\n", timeout=0.2)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(processes[0].pid, os.WNOHANG)

    def test_native_inherited_stdout_descendant_is_bounded(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("native lifecycle requires Darwin")
        code = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'])\nprint('leader exiting', flush=True)\n"
        drains: list[bool] = []
        leader: list[subprocess.Popen[bytes]] = []
        real_drain = getattr(subject, "_drain_output")
        real_group = getattr(subject, "_group_signal")

        def drain(stream: io.BufferedReader, output: bytearray, *, timeout: float = 0.2) -> None:
            try:
                real_drain(stream, output, timeout=timeout)
            except BaseException:
                drains.append(False)
                raise
            drains.append(True)

        def group(process: subprocess.Popen[bytes]) -> None:
            leader.append(process)
            self.assertIsNone(process.returncode)
            real_group(process)

        with mock.patch.object(subject, "_drain_output", drain), mock.patch.object(subject, "_group_signal", group):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "stdout.*drain deadline"):
                self.launch(code)
        self.assertEqual(drains, [False, True], "final real pipe EOF must follow owned-group cleanup")
        self.assertEqual(len(leader), 1)
        self.assertIsNotNone(leader[0].returncode)
        self.assertIsNotNone(leader[0].stdout)
        if leader[0].stdout is not None:
            self.assertTrue(leader[0].stdout.closed)
        with self.assertRaises(ChildProcessError):
            os.waitpid(leader[0].pid, os.WNOHANG)
        # Negative control: finite unowned grandchildren naturally exit. When
        # group cleanup is omitted, neither drain can claim EOF while alive.
        drains.clear()
        release = self.root / "release-finite-descendant"
        descendant = "from pathlib import Path; import time\ndeadline=time.monotonic()+5\nwhile not Path(" + repr(str(release)) + ").exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
        finite = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-I', '-c', " + repr(descendant) + "])\nprint('leader exiting', flush=True)\n"
        try:
            with mock.patch.object(subject, "_drain_output", drain), mock.patch.object(subject, "_group_signal"):
                with self.assertRaisesRegex(subject.MacGuiVerificationError, "stdout.*drain deadline"):
                    self.launch(finite)
        finally:
            release.write_bytes(b"release")
        self.assertEqual(drains, [False, False])

    def test_native_output_budget_stops_owned_group(self) -> None:
        with mock.patch.object(subject, "MAX_OUTPUT_BYTES", 1024):
            with self.assertRaisesRegex(subject.MacGuiVerificationError, "output.*byte budget"):
                self.launch("import os\nwhile True: os.write(1, b'x' * 4096)\n")

    def test_native_observer_and_control_errors_preserve_primary(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("native lifecycle requires Darwin")
        for error in (OSError("observer failure"), KeyboardInterrupt("control"), SystemExit(0)):
            with self.subTest(kind=type(error).__name__), mock.patch.object(subject, "_observe_exit", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    self.launch("import time\ntime.sleep(30)\n")
                self.assertIs(caught.exception, error)
        original_observer = getattr(subject, "_observe_exit")
        lost = ChildProcessError("external reaper consumed the private child")

        def externally_reap(process: subprocess.Popen[bytes], stream: io.BufferedReader, output: bytearray, deadline: float) -> bool:
            original_observer(process, stream, output, deadline)
            reaped, _status = os.waitpid(process.pid, os.WNOHANG)
            self.assertEqual(reaped, process.pid)
            raise lost

        with mock.patch.object(subject, "_observe_exit", externally_reap), mock.patch.object(subject.os, "killpg") as group_signal, mock.patch.object(subject.os, "kill") as direct_signal:
            with self.assertRaises(ChildProcessError) as caught:
                self.launch("print('exited before external reap')\n")
            self.assertIs(caught.exception, lost)
            group_signal.assert_not_called()
            direct_signal.assert_not_called()
        ignored = ChildProcessError("SIGCHLD ignored during private child exit")

        def ignored_then_restored(process: subprocess.Popen[bytes], stream: io.BufferedReader, output: bytearray, deadline: float) -> bool:
            previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
            try:
                while True:
                    try:
                        os.waitpid(process.pid, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if time.monotonic() >= deadline:
                        self.fail("SIGCHLD ignored child did not finish within its deadline")
                    select.select([stream], [], [], 0.01)
                self.assertIsNone(process.returncode)
            finally:
                signal.signal(signal.SIGCHLD, previous)
            raise ignored

        with mock.patch.object(subject, "_observe_exit", ignored_then_restored), mock.patch.object(subject.os, "killpg") as group_signal, mock.patch.object(subject.os, "kill") as direct_signal:
            with self.assertRaises(ChildProcessError) as caught:
                self.launch("print('auto-reaped')\n")
            self.assertIs(caught.exception, ignored)
            group_signal.assert_not_called()
            direct_signal.assert_not_called()
        real_group = getattr(subject, "_group_signal")
        real_wait = subprocess.Popen[bytes].wait
        for stage in ("signal", "reap", "observer-close"):
            primary = KeyboardInterrupt("original control")
            secondary = OSError(f"{stage} failure")

            def group_then_fail(process: subprocess.Popen[bytes]) -> None:
                real_group(process)
                raise secondary

            def reap_then_fail(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
                real_wait(process, timeout=timeout)
                raise secondary

            if stage == "observer-close":
                real_queue = select.kqueue

                class Queue:
                    def __init__(self) -> None:
                        self.queue = real_queue()

                    def control(self, changes: Sequence[select.kevent] | None, count: int, timeout: float) -> list[select.kevent]:
                        self.queue.control(changes, count, timeout)
                        raise primary

                    def close(self) -> None:
                        self.queue.close()
                        raise secondary

                with self.subTest(stage=stage), mock.patch.object(subject.select, "kqueue", Queue):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        self.launch("import time\ntime.sleep(30)\n")
            else:
                target = mock.patch.object(subject, "_group_signal", side_effect=group_then_fail) if stage == "signal" else mock.patch.object(subject.subprocess.Popen, "wait", reap_then_fail)
                with self.subTest(stage=stage), target, mock.patch.object(subject, "_observe_exit", side_effect=primary):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        self.launch("import time\ntime.sleep(30)\n")
            self.assertIs(caught.exception, primary)
            self.assertTrue(any(str(secondary) in note for note in getattr(primary, "__notes__", ())))


class _CoverageResult(unittest.TextTestResult):
    def startTest(self, test: unittest.TestCase) -> None:
        if not hasattr(self, "started_ids"):
            self.started_ids: list[str] = []
            self.completed_ids: list[str] = []
        self.started_ids.append(test.id())
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        self.completed_ids.append(test.id())
        super().stopTest(test)


class _CoverageRunner(unittest.TextTestRunner):
    def _makeResult(self) -> _CoverageResult:
        result = _CoverageResult(self.stream, self.descriptions, self.verbosity)
        result.started_ids = []
        result.completed_ids = []
        return result

    def new_result(self) -> _CoverageResult:
        return self._makeResult()


def coverage_allowed(result: _CoverageResult, expected: Sequence[str]) -> bool:
    return bool(expected) and len(set(expected)) == len(expected) and type(result.testsRun) is int and result.testsRun == len(expected) and result.started_ids == list(expected) and result.completed_ids == list(expected) and result.wasSuccessful() and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses


class NativeGatePolicyTests(unittest.TestCase):
    def test_exact_positive_coverage_and_short_duplicate_skip_bad_outcomes(self) -> None:
        expected = ["native.first", "native.second"]
        def positive() -> _CoverageResult:
            result = _CoverageRunner(stream=io.StringIO()).new_result()
            result.testsRun = 2
            result.started_ids = list(expected)
            result.completed_ids = list(expected)
            return result

        self.assertTrue(coverage_allowed(positive(), expected))
        self.assertFalse(coverage_allowed(positive(), ()))
        self.assertFalse(coverage_allowed(positive(), ("native.first", "native.first")))
        for field in ("started_ids", "completed_ids"):
            result = positive()
            setattr(result, field, ["native.first"])
            self.assertFalse(coverage_allowed(result, expected))
            setattr(result, field, ["wrong.first", "wrong.second"])
            self.assertFalse(coverage_allowed(result, expected))
        for outcome in ("skipped", "expectedFailures", "unexpectedSuccesses", "failures", "errors"):
            result = positive()
            setattr(result, outcome, [(unittest.TestCase(), "modeled negative outcome")])
            self.assertFalse(coverage_allowed(result, expected))
        result = positive()
        result.testsRun = 0
        self.assertFalse(coverage_allowed(result, expected))

    def test_native_cli_controls_preserve_old_receipt_and_never_report_success(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name).resolve() / "receipt.json"
        output.write_text(json.dumps({"old": True}))
        original = output.read_bytes()
        for error in (KeyboardInterrupt(), SystemExit(0), OSError("runtime unavailable")):
            with self.subTest(kind=type(error).__name__), mock.patch.object(subject, "require_native_runtime", side_effect=error), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--native-architecture", "arm64", "--output", str(output)]), 2)
            self.assertEqual(output.read_bytes(), original)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict, zero-skip native Mac lifecycle gate")
    parser.add_argument("--native-architecture", required=True, choices=("arm64", "x86_64"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(arguments)
    try:
        runtime = subject.require_native_runtime(args.native_architecture)
        suite = unittest.TestSuite(NativeLifecycleTests(name) for name in NATIVE_METHODS)
        expected = [f"{NativeLifecycleTests.__module__}.NativeLifecycleTests.{name}" for name in NATIVE_METHODS]
        if unittest.defaultTestLoader.getTestCaseNames(NativeLifecycleTests) != sorted(NATIVE_METHODS):
            raise RuntimeError("native lifecycle selector inventory differs from the frozen methods")
        result = _CoverageRunner(verbosity=2).run(suite)
        if not isinstance(result, _CoverageResult):
            raise RuntimeError("native coverage result is unavailable")
        successful = coverage_allowed(result, expected)
        value = {"schema_version": 1, "runtime": runtime, "selected": expected, "started": result.started_ids, "completed": result.completed_ids, "tests_run": result.testsRun, "successful": successful, "skips": len(result.skipped), "failures": len(result.failures), "errors": len(result.errors), "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses)}
        subject.publish_receipt(args.output, value)
        return 0 if successful else 1
    except BaseException as error:
        subject.report_failure(error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
