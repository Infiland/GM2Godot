"""Contracts for the moved Included Files state owners and borrowed resources."""

from __future__ import annotations

import ast
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion.included_files_parts import (
    constants,
    guarded_mutations,
    native_filesystem,
    native_posix,
    path_validation,
    phase_observer,
    record_io,
    recorded_cleanup,
    recovery_codec,
    source_snapshots,
)
from src.conversion.included_files_parts.filesystem_operations import (
    IncludedCleanupParentBinding,
    IncludedFilesystemOperations,
)

_PARTS = "src.conversion.included_files_parts"
_OWNER_EDGES = {
    "models": frozenset[str](),
    "constants": frozenset[str](),
    "path_validation": frozenset({"models", "constants", "src.conversion.included_file_registry"}),
    "stat_metadata": frozenset({"models", "src.conversion.included_file_paths"}),
    "recovery_codec": frozenset({"models", "constants", "path_validation", "stat_metadata"}),
    "filesystem_operations": frozenset({"models"}),
    "native_posix": frozenset({"models", "stat_metadata"}),
    "native_windows": frozenset({"models", "filesystem_operations", "path_validation", "stat_metadata"}),
    "native_filesystem": frozenset(
        {"models", "filesystem_operations", "native_posix", "native_windows", "stat_metadata"}
    ),
    "source_snapshots": frozenset(
        {"models", "constants", "native_filesystem", "native_posix", "path_validation", "stat_metadata"}
    ),
    "guarded_mutations": frozenset(
        {
            "models",
            "filesystem_operations",
            "native_filesystem",
            "native_posix",
            "phase_observer",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "record_io": frozenset(
        {
            "models",
            "constants",
            "native_filesystem",
            "path_validation",
            "recovery_codec",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "recorded_cleanup": frozenset(
        {
            "models",
            "filesystem_operations",
            "guarded_mutations",
            "native_filesystem",
            "path_validation",
            "phase_observer",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "phase_observer": frozenset[str](),
}


def project_dependencies(source: str, allowed: frozenset[str]) -> frozenset[str]:
    """Inspect actual source, including deferred imports, without running it."""
    dependencies: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None or any(alias.name == "*" for alias in node.names):
                raise AssertionError("Relative/wildcard owner import")
            names = [node.module + "." + alias.name for alias in node.names] if node.module == _PARTS else [node.module]
        for name in names:
            if name.split(".", 1)[0] in sys.stdlib_module_names:
                continue
            if name not in allowed:
                raise AssertionError("Unexpected owner dependency: " + name)
            dependencies.add(name)
    return frozenset(dependencies)


def assert_acyclic(graph: dict[str, frozenset[str]]) -> None:
    visiting: set[str] = set()
    complete: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise AssertionError("Owner dependency cycle: " + name)
        if name in complete:
            return
        visiting.add(name)
        for dependency in graph[name]:
            if dependency in graph:
                visit(dependency)
        visiting.remove(name)
        complete.add(name)

    for name in graph:
        visit(name)


def path_identity(path: Path) -> tuple[int, int]:
    observed = os.lstat(path)
    return observed.st_dev, observed.st_ino


class TestIncludedFilesStateOwners(unittest.TestCase):
    def test_five_state_owners_and_fourteen_combined_owners_have_exact_acyclic_edges(self) -> None:
        self.assertEqual(len(_OWNER_EDGES), 14)
        state_owners = {"source_snapshots", "guarded_mutations", "record_io", "recorded_cleanup", "phase_observer"}
        self.assertEqual(len(state_owners), 5)
        directory = Path(__file__).resolve().parents[1] / "src/conversion/included_files_parts"
        graph: dict[str, frozenset[str]] = {}
        for owner, short_edges in _OWNER_EDGES.items():
            expected = frozenset(name if name.startswith("src.") else _PARTS + "." + name for name in short_edges)
            with self.subTest(owner=owner):
                actual = project_dependencies((directory / (owner + ".py")).read_text(encoding="utf-8"), expected)
                self.assertEqual(actual, expected)
                graph[_PARTS + "." + owner] = actual
        assert_acyclic(graph)
        for forbidden in (
            "from src.conversion import included_files",
            "def late():\n    from src.conversion import included_files\n",
            "from src.conversion.included_files_parts import staging",
            "def late():\n    from src.conversion.included_files_parts import recorded_cleanup\n",
            "from . import source_snapshots",
            "from src.conversion.included_files_parts.models import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_dependencies(forbidden, graph[_PARTS + ".source_snapshots"])
        cycle = dict(graph)
        cycle[_PARTS + ".source_snapshots"] |= {_PARTS + ".recorded_cleanup"}
        with self.assertRaisesRegex(AssertionError, "dependency cycle"):
            assert_acyclic(cycle)

    def test_snapshot_digest_uses_late_reader_and_borrows_real_open_file_on_error(self) -> None:
        digest = source_snapshots.digest_open_included_file
        reader = source_snapshots.read_included_validation_chunk
        content = b"borrowed descriptor and late reader"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.bin"
            path.write_bytes(content)
            with path.open("rb") as opened_file:
                descriptor = opened_file.fileno()
                before = os.fstat(descriptor)
                with patch.object(source_snapshots, "read_included_validation_chunk", wraps=reader) as read:
                    self.assertEqual(digest(opened_file), (len(content), hashlib.sha256(content).hexdigest()))
                self.assertEqual(read.call_count, 2)
                opened_file.seek(0)
                failure = OSError("late snapshot reader failed")
                with patch.object(source_snapshots, "read_included_validation_chunk", side_effect=failure):
                    with self.assertRaises(OSError) as raised:
                        digest(opened_file)
                self.assertIs(raised.exception, failure)
                self.assertFalse(opened_file.closed)
                self.assertTrue(os.path.samestat(before, os.fstat(descriptor)))
                self.assertEqual(opened_file.read(), content)

    def test_fallback_quarantine_observes_late_hook_before_moving_real_entry(self) -> None:
        quarantine = guarded_mutations.quarantine_included_entry_fallback
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned.bin"
            path.write_bytes(b"retained before rename")
            before = path_identity(path)
            failure = OSError("quarantine hook failed")
            with patch.object(
                guarded_mutations, "before_included_cleanup_quarantine_fallback", side_effect=failure
            ) as hook:
                with self.assertRaises(OSError) as raised:
                    quarantine(str(path), before, expect_directory=False)
            hook.assert_called_once_with(str(path))
            self.assertIs(raised.exception, failure)
            self.assertEqual(path_identity(path), before)
            self.assertEqual(path.read_bytes(), b"retained before rename")
            self.assertEqual(sorted(os.listdir(directory)), [path.name])

    @unittest.skipUnless(
        sys.platform == "win32"
        or (native_posix.included_descriptor_paths_supported() and native_posix.included_native_noreplace_available()),
        "Descriptor-pinned no-replace rename is unavailable",
    )
    def test_phase_observer_is_live_after_real_quarantine_and_on_cleanup_resume(self) -> None:
        cleanup = recorded_cleanup.cleanup_recorded_included_file
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            path = parent / "owned.bin"
            content = b"recorded phase boundary"
            path.write_bytes(content)
            identity, parent_identity = path_identity(path), path_identity(parent)
            transaction, role = "c" * 32, "owner-test"
            tombstone = Path(
                path_validation.included_cleanup_tombstone_path(
                    str(path), transaction, role, path.name, expect_directory=False
                )
            )
            stop = OSError("stop after durable quarantine")
            with patch.object(phase_observer, "after_included_transaction_phase", side_effect=stop) as first_hook:
                with self.assertRaises(OSError) as raised:
                    cleanup(
                        str(path),
                        identity,
                        hashlib.sha256(content).hexdigest(),
                        parent_identity,
                        transaction,
                        role,
                        path.name,
                    )
            self.assertIs(raised.exception, stop)
            first_hook.assert_called_once_with("cleanup:owner-test:owned.bin:quarantined")
            self.assertFalse(path.exists())
            self.assertEqual(path_identity(tombstone), identity)
            self.assertEqual(tombstone.read_bytes(), content)
            with patch.object(phase_observer, "after_included_transaction_phase") as resumed_hook:
                self.assertEqual(
                    cleanup(
                        str(path),
                        identity,
                        hashlib.sha256(content).hexdigest(),
                        parent_identity,
                        transaction,
                        role,
                        path.name,
                    ),
                    (),
                )
            resumed_hook.assert_called_once_with("cleanup:owner-test:owned.bin:removed")
            self.assertFalse(tombstone.exists())

    def test_real_recovery_record_reads_are_bounded_canonical_and_reject_malformed_bytes(self) -> None:
        read_record = record_io.read_included_recovery_record
        payload = {"format_version": 2, "message": "\u00e9"}
        canonical = recovery_codec.included_recovery_record_content(payload)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            path = parent / "record.json"
            path.write_bytes(canonical)
            parent_identity = path_identity(parent)
            with patch.object(constants, "INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES", len(canonical)):
                result = read_record(str(path), parent_identity)
                assert result is not None
                self.assertEqual(result[0], path_identity(path))
                self.assertEqual(result[1], payload)
            with patch.object(constants, "INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES", len(canonical) - 1):
                with self.assertRaisesRegex(OSError, "canonical size limit"):
                    read_record(str(path), parent_identity)
            for invalid in (b"\xff", b"{broken", b"[]\n", b'{"message":"noncanonical"}\n'):
                with self.subTest(invalid=invalid):
                    path.write_bytes(invalid)
                    with self.assertRaises(OSError):
                        read_record(str(path), parent_identity)
                    self.assertEqual(path.read_bytes(), invalid)

    @unittest.skipUnless(
        native_posix.included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_cleanup_unlink_failure_keeps_borrowed_real_posix_parent_fd_open(self) -> None:
        unlink = guarded_mutations.unlink_exact_quarantined_entry_at
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quarantine.bin"
            path.write_bytes(b"retained quarantine")
            parent_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            before = os.fstat(parent_fd)
            failure = OSError("cleanup hook failed")
            try:
                with patch.object(guarded_mutations, "before_included_cleanup_remove", side_effect=failure) as hook:
                    with self.assertRaises(OSError) as raised:
                        unlink(parent_fd, path.name, path_identity(path), str(path))
                hook.assert_called_once_with(parent_fd, path.name)
                self.assertIs(raised.exception, failure)
                self.assertTrue(os.path.samestat(before, os.fstat(parent_fd)))
                self.assertEqual(path.read_bytes(), b"retained quarantine")
            finally:
                os.close(parent_fd)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows semantics")
    def test_cleanup_failure_borrows_real_windows_parent_binding_until_owner_closes(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        remove = recorded_cleanup.remove_included_cleanup_tombstone
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "parent"
            parent.mkdir()
            path = parent / "quarantine.bin"
            path.write_bytes(b"retained native quarantine")
            parent_identity, identity = path_identity(parent), path_identity(path)
            binding: IncludedCleanupParentBinding = port.open_windows_cleanup_parent(str(parent), parent_identity)
            failure = OSError("late cleanup unlink failed")
            with binding:
                with patch.object(
                    guarded_mutations, "unlink_exact_quarantined_entry_fallback", side_effect=failure
                ) as unlink:
                    with self.assertRaises(OSError) as raised:
                        remove(
                            str(path),
                            identity,
                            str(parent),
                            parent_identity,
                            expect_directory=False,
                            windows_parent_binding=binding,
                        )
                self.assertIs(raised.exception, failure)
                unlink.assert_called_once_with(
                    str(path), identity, expected_parent_identity=parent_identity, windows_parent_binding=binding
                )
                binding.verify()
                self.assertEqual(path.read_bytes(), b"retained native quarantine")
                with self.assertRaises(OSError):
                    os.rename(parent, str(parent) + "-moved")
            with self.assertRaisesRegex(OSError, "binding is closed"):
                binding.verify()
            os.rename(parent, str(parent) + "-moved")


if __name__ == "__main__":
    unittest.main()
