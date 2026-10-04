"""Contracts for live Included Files native operations and owned resources."""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.conversion.included_files_parts import (
    filesystem_operations,
    native_filesystem,
    native_posix,
    native_windows,
    stat_metadata,
)
from src.conversion.included_files_parts.filesystem_operations import (
    IncludedCleanupParentBinding,
    IncludedFilesystemOperations,
)

_PARTS = "src.conversion.included_files_parts"


def project_dependencies(source: str, allowed: frozenset[str]) -> frozenset[str]:
    """Inspect deferred imports too, without running inspected source."""
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


class TestIncludedFilesNativeOwners(unittest.TestCase):
    def test_typed_port_reads_public_owner_aliases_after_construction(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        with patch.object(native_posix, "included_descriptor_paths_supported", side_effect=(False, True)) as support:
            self.assertFalse(port.descriptor_paths_supported())
            self.assertTrue(port.descriptor_paths_supported())
        self.assertEqual(support.call_count, 2)
        failure = OSError("late rename owner")
        with patch.object(native_windows, "rename_included_transaction_entry", side_effect=failure) as rename:
            with self.assertRaises(OSError) as raised:
                port.rename_entry("source", "destination")
        self.assertIs(raised.exception, failure)
        rename.assert_called_once_with("source", "destination")
        with tempfile.TemporaryDirectory() as directory:
            observed = os.lstat(directory)
            original_probe = stat_metadata.included_output_path_is_redirected
            with patch.object(stat_metadata, "included_output_path_is_redirected", wraps=original_probe) as probe:
                self.assertFalse(port.output_path_is_redirected(directory, observed))
            probe.assert_called_once_with(directory, observed)

    def test_validation_stream_observes_platform_late_and_keeps_plain_open_fallback(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "payload.bin"
            path.write_bytes(b"live selector")
            path_text = str(path)
            with patch.object(
                native_windows,
                "windows_included_file_read_api",
                side_effect=AssertionError("Unexpected native read API"),
            ):
                with patch.object(os, "name", "nt"):
                    with port.open_validation_stream(path_text, deny_writes=False) as stream:
                        self.assertEqual(stream.read(), b"live selector")
                with patch.object(os, "name", "posix"):
                    with port.open_validation_stream(path_text, deny_writes=True) as stream:
                        self.assertEqual(stream.read(), b"live selector")

    @unittest.skipUnless(
        native_posix.included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_real_posix_child_open_borrows_parent_fd_on_success_and_error(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        with tempfile.TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, "child"))
            parent_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            before = os.fstat(parent_fd)
            try:
                child_fd = port.open_tree_directory_at(parent_fd, "child")
                try:
                    opened_child = os.fstat(child_fd)
                    named_child = os.stat("child", dir_fd=parent_fd, follow_symlinks=False)
                    self.assertTrue(os.path.samestat(opened_child, named_child))
                finally:
                    os.close(child_fd)
                with self.assertRaises(FileNotFoundError):
                    port.open_tree_directory_at(parent_fd, "missing")
                self.assertTrue(os.path.samestat(before, os.fstat(parent_fd)))
            finally:
                os.close(parent_fd)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows semantics")
    def test_real_windows_port_binding_pins_parent_and_context_closes_owned_handle(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        with tempfile.TemporaryDirectory() as directory:
            parent = os.path.join(directory, "parent")
            moved = os.path.join(directory, "moved")
            os.mkdir(parent)
            observed = os.lstat(parent)
            identity = observed.st_dev, observed.st_ino
            binding: IncludedCleanupParentBinding = port.open_windows_cleanup_parent(parent, identity)
            with binding as entered:
                self.assertIs(entered, binding)
                self.assertEqual(binding.identity, identity)
                port.verify_windows_cleanup_parent(binding, parent, identity)
                with self.assertRaises(OSError):
                    os.rename(parent, moved)
            with self.assertRaisesRegex(OSError, "binding is closed"):
                binding.verify()
            binding.close()
            os.rename(parent, moved)
            self.assertFalse(os.path.lexists(parent))
            self.assertTrue(os.path.isdir(moved))

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows semantics")
    def test_real_windows_close_preserves_active_error_and_reports_post_close_failure(self) -> None:
        port: IncludedFilesystemOperations = native_filesystem.NativeIncludedFilesystemOperations()
        original_close = native_windows.WindowsIncludedCleanupParentBinding.close
        with tempfile.TemporaryDirectory() as directory:
            for active_error in (False, True):
                with self.subTest(active_error=active_error):
                    parent = os.path.join(directory, str(active_error))
                    os.mkdir(parent)
                    observed = os.lstat(parent)
                    identity = observed.st_dev, observed.st_ino
                    binding: IncludedCleanupParentBinding = port.open_windows_cleanup_parent(parent, identity)
                    close_error = OSError("injected delivery failure after native close")
                    body_error = OSError("operation failed")
                    closed: list[IncludedCleanupParentBinding] = []

                    def close_then_fail(
                        resource: native_windows.WindowsIncludedCleanupParentBinding,
                        error: OSError = close_error,
                        captured: list[IncludedCleanupParentBinding] = closed,
                    ) -> None:
                        original_close(resource)
                        captured.append(resource)
                        raise error

                    with patch.object(native_windows.WindowsIncludedCleanupParentBinding, "close", close_then_fail):
                        with self.assertRaises(OSError) as raised:
                            with binding:
                                if active_error:
                                    raise body_error
                    self.assertEqual(len(closed), 1)
                    self.assertIs(closed[0], binding)
                    self.assertIs(raised.exception, body_error if active_error else close_error)
                    if active_error:
                        self.assertEqual(
                            body_error.__notes__,
                            [
                                "Could not close Included Files cleanup parent binding: " + str(close_error),
                            ],
                        )
                    with self.assertRaisesRegex(OSError, "binding is closed"):
                        binding.verify()
                    binding.close()
                    os.rename(parent, parent + "-released")

    def test_native_owner_imports_follow_directed_acyclic_contract(self) -> None:
        model = _PARTS + ".models"
        interface = _PARTS + ".filesystem_operations"
        metadata = _PARTS + ".stat_metadata"
        posix = _PARTS + ".native_posix"
        windows = _PARTS + ".native_windows"
        path_validation = _PARTS + ".path_validation"
        allowed = (
            (filesystem_operations, frozenset({model})),
            (stat_metadata, frozenset({model, "src.conversion.included_file_paths"})),
            (native_posix, frozenset({model, metadata})),
            (native_windows, frozenset({interface, model, path_validation, metadata})),
            (native_filesystem, frozenset({interface, model, posix, windows, metadata})),
        )
        rank = {
            model: 0,
            "src.conversion.included_file_paths": 0,
            interface: 1,
            metadata: 1,
            path_validation: 1,
            posix: 2,
            windows: 2,
            native_filesystem.__name__: 3,
        }
        for owner, expected in allowed:
            with self.subTest(owner=owner.__name__):
                filename = owner.__file__
                assert filename is not None
                edges = project_dependencies(Path(filename).read_text(encoding="utf-8"), expected)
                self.assertEqual(edges, expected)
                for dependency in edges:
                    self.assertLess(rank[dependency], rank[owner.__name__])
        for forbidden in (
            "from src.conversion import included_files",
            "from src.conversion.included_files_parts import recovery_codec",
            "from src.conversion.included_files_parts import staging",
            "from src.conversion.included_files_parts import transaction",
            "from . import native_windows",
            "from src.conversion.included_files_parts.models import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_dependencies(forbidden, frozenset({model}))
