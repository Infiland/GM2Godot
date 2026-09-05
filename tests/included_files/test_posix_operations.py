"""Direct native POSIX Included Files operation contracts."""

import ctypes
import errno
import os
import stat
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import mock_open, patch

from src.conversion.included_files_parts.filesystem_metadata import path_fingerprint
from src.conversion.included_files_parts.posix_operations import (
    descriptor_paths_supported,
    directory_identity_from_fd,
    entry_stat_at,
    linux_mount_id_from_fd,
    native_noreplace_available,
    open_pinned_directory,
    preserve_or_restore_unexpected_moved_entry_at,
    rename_transaction_entry_at,
    sync_directory,
    verify_directory_fd,
    verify_entry_at,
    verify_mount_boundary,
)


class TestIncludedFilesPosixOperations(unittest.TestCase):
    def setUp(self) -> None:
        workspace = tempfile.TemporaryDirectory(prefix="gm2godot-posix-")
        self.addCleanup(workspace.cleanup)
        self.datafiles_dir = os.path.join(workspace.name, "datafiles")
        self.godot_dir = os.path.join(workspace.name, "godot")
        os.makedirs(self.datafiles_dir)
        os.makedirs(self.godot_dir)

    def test_linux_mount_id_parser_and_boundary_reject_different_mount(
        self,
    ) -> None:
        with open(
            os.path.join(self.datafiles_dir, "test-mount-id"),
            "wb",
        ) as test_file:
            test_file.write(b"mount id model")
        opened_stat = os.lstat(os.path.join(self.datafiles_dir, "test-mount-id"))

        with (
            patch.object(sys, "platform", "linux"),
            patch(
                "builtins.open",
                mock_open(read_data="pos:\t0\nflags:\t0100000\nmnt_id:\t41\n"),
            ),
        ):
            self.assertEqual(
                linux_mount_id_from_fd(123),
                41,
            )

        with (
            patch(
                "src.conversion.included_files_parts.posix_operations.linux_mount_id_from_fd",
                return_value=42,
            ),
            patch.object(os.path, "ismount", return_value=False),
            self.assertRaisesRegex(OSError, "mount boundary"),
        ):
            verify_mount_boundary(
                os.path.join(self.datafiles_dir, "test-mount-id"),
                opened_stat,
                opened_stat.st_dev,
                41,
                123,
            )

    def test_native_noreplace_missing_capability_fails_closed(self) -> None:
        if not descriptor_paths_supported():
            self.skipTest("Descriptor-pinned paths are unavailable")
        transaction_directory = os.path.join(
            self.godot_dir,
            "native-unavailable",
        )
        os.mkdir(transaction_directory)
        source_path = os.path.join(transaction_directory, "source.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("source")
        directory_fd = open_pinned_directory(
            transaction_directory
        )
        try:
            with patch(
                "src.conversion.included_files_parts.posix_operations.native_noreplace_available",
                return_value=False,
            ), self.assertRaisesRegex(OSError, "unavailable"):
                rename_transaction_entry_at(
                    directory_fd,
                    "source.txt",
                    directory_fd,
                    "destination.txt",
                )
        finally:
            os.close(directory_fd)
        self.assertTrue(os.path.isfile(source_path))
        self.assertFalse(
            os.path.lexists(
                os.path.join(transaction_directory, "destination.txt")
            )
        )

    def test_native_noreplace_preserves_file_and_directory_destinations(
        self,
    ) -> None:
        if not (
            descriptor_paths_supported()
            and native_noreplace_available()
        ):
            self.skipTest("Native no-replace rename is unavailable")
        transaction_directory = os.path.join(
            self.godot_dir,
            "native-noreplace",
        )
        os.mkdir(transaction_directory)
        with open(
            os.path.join(transaction_directory, "source.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("source")
        with open(
            os.path.join(transaction_directory, "destination.txt"),
            "w",
            encoding="utf-8",
        ) as destination_file:
            destination_file.write("destination")
        os.mkdir(os.path.join(transaction_directory, "source-dir"))
        os.mkdir(os.path.join(transaction_directory, "destination-dir"))
        directory_fd = open_pinned_directory(
            transaction_directory
        )
        try:
            for source_name, destination_name in (
                ("source.txt", "destination.txt"),
                ("source-dir", "destination-dir"),
            ):
                with self.subTest(source_name=source_name), self.assertRaises(
                    OSError
                ):
                    rename_transaction_entry_at(
                        directory_fd,
                        source_name,
                        directory_fd,
                        destination_name,
                    )
        finally:
            os.close(directory_fd)
        with open(
            os.path.join(transaction_directory, "source.txt"),
            encoding="utf-8",
        ) as source_file:
            self.assertEqual(source_file.read(), "source")
        with open(
            os.path.join(transaction_directory, "destination.txt"),
            encoding="utf-8",
        ) as destination_file:
            self.assertEqual(destination_file.read(), "destination")
        self.assertTrue(
            os.path.isdir(os.path.join(transaction_directory, "source-dir"))
        )
        self.assertTrue(
            os.path.isdir(
                os.path.join(transaction_directory, "destination-dir")
            )
        )

    def test_pinned_directory_transfers_live_fd_and_closes_ancestors(self) -> None:
        if not descriptor_paths_supported():
            self.skipTest("Native descriptor paths required")
        directory = Path(self.datafiles_dir, "nested", "leaf")
        directory.mkdir(parents=True)
        opened: list[int] = []
        closed: list[int] = []
        real_open, real_close = os.open, os.close

        def observe_open(path: str, flags: int, *, dir_fd: int | None = None) -> int:
            descriptor = real_open(path, flags, dir_fd=dir_fd)
            self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
            opened.append(descriptor)
            return descriptor

        def observe_close(descriptor: int) -> None:
            real_close(descriptor)
            with self.assertRaises(OSError) as caught:
                os.fstat(descriptor)
            self.assertEqual(caught.exception.errno, errno.EBADF)
            closed.append(descriptor)

        # Replacing os.open changes membership in supports_dir_fd; the selector
        # is modeled after the real capability check above. Every open is native.
        with (
            patch("src.conversion.included_files_parts.posix_operations.descriptor_paths_supported", return_value=True),
            patch.object(os, "open", side_effect=observe_open),
            patch.object(os, "close", side_effect=observe_close),
        ):
            descriptor = open_pinned_directory(str(directory))
        try:
            self.assertEqual(closed, opened[:-1])
            self.assertGreater(len(closed), 1)
            self.assertEqual(descriptor, opened[-1])
            self.assertTrue(os.path.samestat(os.fstat(descriptor), directory.stat()))
        finally:
            real_close(descriptor)

    def test_failed_child_open_closes_owned_fd_before_reuse(self) -> None:
        if not descriptor_paths_supported():
            self.skipTest("Native descriptor paths required")
        real_open, real_close = os.open, os.close
        for interruption in (False, True):
            with self.subTest(interruption=interruption):
                opened: list[int] = []
                closed: list[int] = []
                failures: list[BaseException] = []

                def fail_at_leaf(
                    path: str, flags: int, *, dir_fd: int | None = None,
                    interruption: bool = interruption, failures: list[BaseException] = failures, opened: list[int] = opened,
                ) -> int:
                    try:
                        if path == "missing" and interruption:
                            raise KeyboardInterrupt("child open interrupted")
                        descriptor = real_open(path, flags, dir_fd=dir_fd)
                    except BaseException as error:
                        failures.append(error)
                        raise
                    opened.append(descriptor)
                    return descriptor

                def observe_close(descriptor: int, closed: list[int] = closed) -> None:
                    real_close(descriptor)
                    with self.assertRaises(OSError) as caught:
                        os.fstat(descriptor)
                    self.assertEqual(caught.exception.errno, errno.EBADF)
                    closed.append(descriptor)

                with (
                    patch("src.conversion.included_files_parts.posix_operations.descriptor_paths_supported", return_value=True),
                    patch.object(os, "open", side_effect=fail_at_leaf),
                    patch.object(os, "close", side_effect=observe_close),
                    self.assertRaises(BaseException) as caught,
                ):
                    open_pinned_directory(os.path.join(self.datafiles_dir, "missing"))
                self.assertEqual(len(failures), 1)
                self.assertIs(caught.exception, failures[0])
                self.assertEqual(closed, opened)
                self.assertGreater(len(opened), 1)
                if interruption:
                    self.assertIsInstance(caught.exception, KeyboardInterrupt)
                else:
                    assert isinstance(caught.exception, FileNotFoundError)
                    self.assertEqual(caught.exception.errno, errno.ENOENT)

    def test_borrowed_entry_checks_preserve_fd_and_reject_replacement(self) -> None:
        if not descriptor_paths_supported():
            self.skipTest("Native descriptor paths required")
        path = Path(self.datafiles_dir, "original")
        path.write_bytes(b"original")
        parent = open_pinned_directory(self.datafiles_dir)
        try:
            with path.open("rb") as original:
                state = os.fstat(original.fileno())
                identity = directory_identity_from_fd(parent)
                self.assertEqual(verify_directory_fd(parent, identity, self.datafiles_dir), identity)
                self.assertIsNone(entry_stat_at(parent, "missing"))
                verify_entry_at(parent, path.name, path_fingerprint(state), str(path))
                with self.assertRaisesRegex(OSError, "directory changed"):
                    verify_directory_fd(parent, (identity[0], identity[1] + 1), self.datafiles_dir)
                path.unlink()
                path.write_bytes(b"replacement")
                with self.assertRaisesRegex(OSError, "entry changed"):
                    verify_entry_at(parent, path.name, path_fingerprint(state), str(path))
                link = Path(self.datafiles_dir, "link")
                link.symlink_to(path)
                link_state = entry_stat_at(parent, link.name)
                assert link_state is not None
                self.assertTrue(stat.S_ISLNK(link_state.st_mode))
                self.assertEqual(original.read(), b"original")
                self.assertEqual(directory_identity_from_fd(parent), identity)
        finally:
            os.close(parent)

    def test_native_rename_transfers_entries_and_preserves_errno(self) -> None:
        if not (descriptor_paths_supported() and native_noreplace_available()):
            self.skipTest("Native exclusive rename required")
        source, destination = Path(self.datafiles_dir), Path(self.godot_dir)
        (source / "file").write_bytes(b"native file")
        (source / "directory").mkdir()
        (source / "directory" / "child").write_bytes(b"native directory")
        source_fd, destination_fd = open_pinned_directory(str(source)), open_pinned_directory(str(destination))
        try:
            identities = (directory_identity_from_fd(source_fd), directory_identity_from_fd(destination_fd))
            for name in ("file", "directory"):
                before = (source / name).stat()
                ctypes.set_errno(errno.EINTR)
                rename_transaction_entry_at(source_fd, name, destination_fd, name)
                self.assertFalse((source / name).exists())
                self.assertTrue(os.path.samestat(before, (destination / name).stat()))
            self.assertEqual((destination / "file").read_bytes(), b"native file")
            self.assertEqual((destination / "directory" / "child").read_bytes(), b"native directory")
            (source / "file").write_bytes(b"occupied attempt")
            for name, target, expected_errno in (("file", "file", errno.EEXIST), ("missing", "absent", errno.ENOENT)):
                with self.subTest(name=name), self.assertRaises(OSError) as caught:
                    rename_transaction_entry_at(source_fd, name, destination_fd, target)
                self.assertEqual(caught.exception.errno, expected_errno)
                self.assertEqual(ctypes.get_errno(), expected_errno)
                self.assertEqual(caught.exception.filename, target)
                self.assertEqual((destination / "file").read_bytes(), b"native file")
            self.assertEqual(identities, (directory_identity_from_fd(source_fd), directory_identity_from_fd(destination_fd)))
        finally:
            os.close(source_fd)
            os.close(destination_fd)

    def test_restore_and_quarantine_preserve_unexpected_entries(self) -> None:
        if not (descriptor_paths_supported() and native_noreplace_available()):
            self.skipTest("Native exclusive rename required")
        parent = open_pinned_directory(self.datafiles_dir)
        try:
            identity = directory_identity_from_fd(parent)
            for occupied in (False, True):
                with self.subTest(occupied=occupied):
                    source = Path(self.datafiles_dir, f"source-{occupied}")
                    destination = Path(self.datafiles_dir, f"destination-{occupied}")
                    destination.write_bytes(b"unexpected entry")
                    before = destination.stat()
                    if occupied:
                        source.write_bytes(b"existing occupant")
                    with patch.object(os, "fsync", side_effect=AssertionError("rename owner must not sync")):
                        error = preserve_or_restore_unexpected_moved_entry_at(
                            parent, source.name, parent, destination.name, str(source), str(destination),
                        )
                    self.assertIsInstance(error, OSError)
                    self.assertFalse(destination.exists())
                    if occupied:
                        quarantine, = Path(self.datafiles_dir).glob(f".{destination.name}.*.quarantine")
                        self.assertEqual(source.read_bytes(), b"existing occupant")
                        self.assertEqual(quarantine.read_bytes(), b"unexpected entry")
                        self.assertTrue(os.path.samestat(before, quarantine.stat()))
                        self.assertIn(repr(str(quarantine)), str(error))
                        self.assertEqual(len(error.__notes__), 1)
                        self.assertTrue(error.__notes__[0].startswith("Restore error: "))
                    else:
                        self.assertEqual(source.read_bytes(), b"unexpected entry")
                        self.assertTrue(os.path.samestat(before, source.stat()))
                        self.assertIn("restored without loss", str(error))
                    self.assertEqual(directory_identity_from_fd(parent), identity)
        finally:
            os.close(parent)

    def test_mount_id_malformed_missing_and_unavailable_policies(self) -> None:
        for payload in ("", "pos: 0\n", "mnt_id: 1\nmnt_id: 2\n", "mnt_id: nope\n", "mnt_id: -1\n", "mnt_id: １２\n"):
            with (
                self.subTest(payload=payload), patch.object(sys, "platform", "linux"),
                patch("builtins.open", mock_open(read_data=payload)),
                self.assertRaisesRegex(OSError, "mount boundary"),
            ):
                linux_mount_id_from_fd(123)
        with patch.object(sys, "platform", "linux"), patch("builtins.open", side_effect=OSError("procfs unavailable")):
            self.assertIsNone(linux_mount_id_from_fd(123))
        decode_error = UnicodeDecodeError("ascii", b"\xff", 0, 1, "non-ASCII fdinfo")
        with patch.object(sys, "platform", "linux"), patch("builtins.open", side_effect=decode_error):
            with self.assertRaises(UnicodeDecodeError) as caught:
                linux_mount_id_from_fd(123)
            self.assertIs(caught.exception, decode_error)
        with patch.object(sys, "platform", "darwin"), patch("builtins.open", side_effect=AssertionError("must not open")):
            self.assertIsNone(linux_mount_id_from_fd(123))

    def test_directory_sync_orders_native_fsync_and_closes_on_failures(self) -> None:
        if not descriptor_paths_supported():
            self.skipTest("Native directory sync required")
        state = os.stat(self.datafiles_dir)
        identity = (state.st_dev, state.st_ino)
        real_close, real_fsync = os.close, os.fsync
        for phase in ("success", "before", "sync", "after"):
            with self.subTest(phase=phase):
                events: list[str] = []
                failure = OSError(f"injected {phase} failure")

                def verify(
                    descriptor: int, expected: tuple[int, int] | None, path: str,
                    phase: str = phase, failure: OSError = failure, events: list[str] = events,
                ) -> tuple[int, int]:
                    events.append("verify")
                    if (phase == "before" and len(events) == 1) or (phase == "after" and len(events) == 3):
                        raise failure
                    return verify_directory_fd(descriptor, expected, path)

                def fsync(
                    descriptor: int, phase: str = phase, failure: OSError = failure, events: list[str] = events,
                ) -> None:
                    events.append("fsync")
                    real_fsync(descriptor)
                    if phase == "sync":
                        raise failure

                def close(descriptor: int, events: list[str] = events) -> None:
                    target = directory_identity_from_fd(descriptor) == identity
                    real_close(descriptor)
                    if target:
                        with self.assertRaises(OSError) as caught:
                            os.fstat(descriptor)
                        self.assertEqual(caught.exception.errno, errno.EBADF)
                        events.append("close")

                with (
                    patch("src.conversion.included_files_parts.posix_operations.verify_directory_fd", side_effect=verify),
                    patch.object(os, "fsync", side_effect=fsync), patch.object(os, "close", side_effect=close),
                ):
                    caught = self.assertRaises(OSError)
                    with caught if phase != "success" else nullcontext():
                        sync_directory(self.datafiles_dir, identity)
                    if phase != "success":
                        self.assertIs(caught.exception, failure)
                expected = {"before": ["verify", "close"], "sync": ["verify", "fsync", "close"]}
                self.assertEqual(events, expected.get(phase, ["verify", "fsync", "verify", "close"]))
