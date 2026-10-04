# pyright: reportPrivateUsage=false

import hashlib
import os
import stat
import subprocess
import sys
import shutil
import tempfile
import tracemalloc
import unittest
from typing import BinaryIO
from unittest.mock import MagicMock, mock_open, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import record_io as _included_records
from src.conversion.included_files_parts import recorded_cleanup as _included_cleanup
from src.conversion.included_files_parts import phase_observer as _included_phases
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import native_posix as _included_posix, native_windows as _included_windows, constants as _included_constants, path_validation as _included_paths, stat_metadata as _included_metadata, recovery_codec as _included_codec
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.included_files_parts import file_publication as _included_file_publication
from src.conversion.included_files_parts import locking as _included_locking
from src.conversion.included_files_parts import recovery as _included_recovery
from tests import included_files_support as _included_support
_included_files_transaction_debris = _included_support.included_files_transaction_debris
_ModeledWindowsCleanupParentBinding = _included_support.ModeledWindowsCleanupParentBinding


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
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
            patch.object(_included_posix.sys, "platform", "linux"),
            patch(
                "builtins.open",
                mock_open(read_data="pos:\t0\nflags:\t0100000\nmnt_id:\t41\n"),
            ),
        ):
            self.assertEqual(
                _included_posix.included_linux_mount_id_from_fd(123),
                41,
            )

        with (
            patch.object(
                _included_posix,
                'included_linux_mount_id_from_fd',
                return_value=42,
            ),
            patch.object(os.path, "ismount", return_value=False),
            self.assertRaisesRegex(OSError, "mount boundary"),
        ):
            _included_posix.verify_included_mount_boundary(
                os.path.join(self.datafiles_dir, "test-mount-id"),
                opened_stat,
                opened_stat.st_dev,
                41,
                123,
            )

    def test_descriptor_tree_capture_closes_parent_when_mount_check_fails(
        self,
    ) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned tree capture is unavailable")
        root_path = os.path.join(self.godot_dir, "fd-cleanup-root")
        os.mkdir(root_path)
        original_open_parent = (
            _included_posix.open_pinned_included_parent
        )
        opened_parent_fd = -1

        def observe_parent_open(path: str) -> tuple[int, str]:
            nonlocal opened_parent_fd
            opened_parent_fd, name = original_open_parent(path)
            return opened_parent_fd, name

        with (
            patch.object(
                _included_posix,
                'open_pinned_included_parent',
                side_effect=observe_parent_open,
            ),
            patch.object(
                _included_posix,
                'included_linux_mount_id_from_fd',
                side_effect=OSError("injected mount inspection failure"),
            ),
            self.assertRaisesRegex(OSError, "mount inspection failure"),
        ):
            _included_snapshots.capture_included_tree(root_path)

        self.assertGreaterEqual(opened_parent_fd, 0)
        with self.assertRaises(OSError):
            os.fstat(opened_parent_fd)

    def test_fallback_tree_capture_rejects_modeled_mountpoint(self) -> None:
        root_path = os.path.join(self.godot_dir, "included_files")
        mounted_path = os.path.join(root_path, "mounted")
        sentinel_path = os.path.join(mounted_path, "external-sentinel.txt")
        os.makedirs(mounted_path)
        with open(sentinel_path, "wb") as sentinel_file:
            sentinel_file.write(b"external mount sentinel")
        project_stat = os.lstat(self.godot_dir)
        mounted_normalized = os.path.normcase(os.path.abspath(mounted_path))

        def modeled_mountpoint(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == mounted_normalized

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                os.path,
                "ismount",
                side_effect=modeled_mountpoint,
            ),
            self.assertRaisesRegex(OSError, "mount boundary"),
        ):
            _included_snapshots.capture_included_tree(
                root_path,
                expected_parent_identity=(
                    project_stat.st_dev,
                    project_stat.st_ino,
                ),
            )

        with open(sentinel_path, "rb") as sentinel_file:
            self.assertEqual(sentinel_file.read(), b"external mount sentinel")

    def test_cleanup_preserves_tree_when_nested_mount_appears(self) -> None:
        root_path = os.path.join(self.godot_dir, "cleanup-root")
        mounted_path = os.path.join(root_path, "mounted")
        sentinel_path = os.path.join(mounted_path, "external-sentinel.txt")
        os.makedirs(mounted_path)
        with open(sentinel_path, "wb") as sentinel_file:
            sentinel_file.write(b"late mount sentinel")
        project_stat = os.lstat(self.godot_dir)
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=(project_stat.st_dev, project_stat.st_ino),
        )
        mounted_normalized = os.path.normcase(os.path.abspath(mounted_path))

        def modeled_mountpoint(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == mounted_normalized

        with patch.object(
            os.path,
            "ismount",
            side_effect=modeled_mountpoint,
        ):
            warnings = _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                (project_stat.st_dev, project_stat.st_ino),
                "a" * 32,
                "late-mount",
            )

        self.assertTrue(any("mounted" in warning for warning in warnings))
        with open(sentinel_path, "rb") as sentinel_file:
            self.assertEqual(sentinel_file.read(), b"late mount sentinel")
        self.assertTrue(os.path.isdir(root_path))

    def test_cleanup_skips_file_probes_below_proven_absent_directory(
        self,
    ) -> None:
        fallback_ancestor_counts: list[int] = []

        for entry_count in (16, 256):
            with self.subTest(entry_count=entry_count):
                root_path = os.path.join(
                    self.godot_dir,
                    f"absent-stage-{entry_count}",
                )
                nested_path = os.path.join(root_path, "included_files")
                os.makedirs(nested_path)
                for index in range(entry_count):
                    with open(
                        os.path.join(nested_path, f"entry-{index:04d}.txt"),
                        "wb",
                    ) as entry_file:
                        entry_file.write(b"x")

                project_stat = os.lstat(self.godot_dir)
                project_identity = (project_stat.st_dev, project_stat.st_ino)
                snapshot = _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=project_identity,
                )
                published_path = os.path.join(
                    self.godot_dir,
                    f"published-{entry_count}",
                )
                os.rename(nested_path, published_path)
                cleanup_file_state = (
                    _included_cleanup.included_cleanup_file_state
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )

                with (
                    patch.object(
                        _included_posix,
                        'included_descriptor_paths_supported',
                        return_value=False,
                    ),
                    patch.object(os, "name", "nt"),
                    patch.object(
                        _included_cleanup,
                        'included_cleanup_file_state',
                        wraps=cleanup_file_state,
                    ) as file_state_mock,
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_mock,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "a" * 32,
                            "stage",
                        )
                    )

                self.assertEqual(warnings, ())
                self.assertEqual(file_state_mock.call_count, 0)
                fallback_ancestor_counts.append(ancestor_mock.call_count)
                self.assertFalse(os.path.lexists(root_path))
                self.assertEqual(len(os.listdir(published_path)), entry_count)

        self.assertEqual(
            fallback_ancestor_counts,
            [fallback_ancestor_counts[0]] * len(fallback_ancestor_counts),
        )
        self.assertLessEqual(fallback_ancestor_counts[0], 64)

    def test_windows_flat_present_cleanup_reuses_one_parent_binding(self) -> None:
        ancestor_capture_counts: list[int] = []
        binding_verify_counts: list[int] = []

        for entry_count in (16, 256):
            with self.subTest(entry_count=entry_count):
                root_path = os.path.join(
                    self.godot_dir,
                    f"flat-present-{entry_count}",
                )
                os.mkdir(root_path)
                for index in range(entry_count):
                    with open(
                        os.path.join(root_path, f"entry-{index:04d}.txt"),
                        "wb",
                    ) as entry_file:
                        entry_file.write(f"payload {index}\n".encode())

                project_stat = os.lstat(self.godot_dir)
                project_identity = project_stat.st_dev, project_stat.st_ino
                snapshot = _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=project_identity,
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )
                bindings: list[_ModeledWindowsCleanupParentBinding] = []

                def open_binding(
                    path: str,
                    identity: tuple[int, int],
                ) -> _ModeledWindowsCleanupParentBinding:
                    binding = _ModeledWindowsCleanupParentBinding(path, identity)
                    bindings.append(binding)
                    return binding

                with (
                    self._modeled_windows_cleanup_context(open_binding),
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_capture,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "c" * 32,
                            "flat-present",
                        )
                )

                self.assertEqual(warnings, ())
                self.assertEqual(len(bindings), 1)
                self.assertEqual(bindings[0].path, os.path.abspath(root_path))
                self.assertEqual(bindings[0].identity, snapshot.identity)
                self.assertTrue(bindings[0].closed)
                self.assertEqual(bindings[0].close_count, 1)
                self.assertFalse(os.path.lexists(root_path))
                ancestor_capture_counts.append(ancestor_capture.call_count)
                binding_verify_counts.append(bindings[0].verify_count)

        self.assertEqual(
            ancestor_capture_counts,
            [ancestor_capture_counts[0]] * len(ancestor_capture_counts),
        )
        self.assertLessEqual(ancestor_capture_counts[0], 32)
        self.assertGreater(binding_verify_counts[1], binding_verify_counts[0])
        self.assertLessEqual(
            binding_verify_counts[1],
            binding_verify_counts[0] * 16 + 32,
        )

    def test_windows_nested_same_parent_cleanup_reuses_one_binding(self) -> None:
        ancestor_capture_counts: list[int] = []
        nested_verify_counts: list[int] = []

        for entry_count in (16, 256):
            with self.subTest(entry_count=entry_count):
                root_path = os.path.join(
                    self.godot_dir,
                    f"nested-same-parent-{entry_count}",
                )
                nested_path = os.path.join(root_path, "nested")
                os.makedirs(nested_path)
                for index in range(entry_count):
                    with open(
                        os.path.join(nested_path, f"entry-{index:04d}.txt"),
                        "wb",
                    ) as entry_file:
                        entry_file.write(f"nested payload {index}\n".encode())

                project_stat = os.lstat(self.godot_dir)
                project_identity = project_stat.st_dev, project_stat.st_ino
                snapshot = _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=project_identity,
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )
                bindings: list[_ModeledWindowsCleanupParentBinding] = []

                def open_binding(
                    path: str,
                    identity: tuple[int, int],
                ) -> _ModeledWindowsCleanupParentBinding:
                    binding = _ModeledWindowsCleanupParentBinding(path, identity)
                    bindings.append(binding)
                    return binding

                with (
                    self._modeled_windows_cleanup_context(open_binding),
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_capture,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "1" * 32,
                            "nested-same-parent",
                        )
                    )

                self.assertEqual(warnings, ())
                self.assertEqual(len(bindings), 2)
                self.assertEqual(
                    [binding.path for binding in bindings],
                    [os.path.abspath(root_path), os.path.abspath(nested_path)],
                )
                self.assertTrue(all(binding.closed for binding in bindings))
                self.assertTrue(
                    all(binding.close_count == 1 for binding in bindings)
                )
                self.assertFalse(os.path.lexists(root_path))
                ancestor_capture_counts.append(ancestor_capture.call_count)
                nested_verify_counts.append(bindings[1].verify_count)

        self.assertEqual(
            ancestor_capture_counts,
            [ancestor_capture_counts[0]] * len(ancestor_capture_counts),
        )
        self.assertLessEqual(ancestor_capture_counts[0], 32)
        self.assertGreater(nested_verify_counts[1], nested_verify_counts[0])
        self.assertLessEqual(
            nested_verify_counts[1],
            nested_verify_counts[0] * 16 + 32,
        )

    def test_windows_multilevel_cleanup_binding_operations_are_linear(
        self,
    ) -> None:
        ancestor_capture_counts: list[int] = []
        binding_open_counts: list[int] = []
        binding_verify_counts: list[int] = []

        for branch_count in (16, 256):
            with self.subTest(branch_count=branch_count):
                root_path = os.path.join(
                    self.godot_dir,
                    f"nested-branches-{branch_count}",
                )
                os.mkdir(root_path)
                branch_paths: list[tuple[str, str]] = []
                for index in range(branch_count):
                    branch_path = os.path.join(
                        root_path,
                        f"branch-{index:04d}",
                    )
                    leaf_path = os.path.join(branch_path, "leaf")
                    os.makedirs(leaf_path)
                    with open(
                        os.path.join(leaf_path, "payload.bin"),
                        "wb",
                    ) as payload_file:
                        payload_file.write(
                            f"multilevel payload {index}\n".encode()
                        )
                    branch_paths.append((branch_path, leaf_path))

                project_stat = os.lstat(self.godot_dir)
                project_identity = project_stat.st_dev, project_stat.st_ino
                snapshot = _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=project_identity,
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )
                bindings: list[_ModeledWindowsCleanupParentBinding] = []
                maximum_live_bindings = 0

                def open_binding(
                    path: str,
                    identity: tuple[int, int],
                ) -> _ModeledWindowsCleanupParentBinding:
                    nonlocal maximum_live_bindings
                    binding = _ModeledWindowsCleanupParentBinding(path, identity)
                    bindings.append(binding)
                    maximum_live_bindings = max(
                        maximum_live_bindings,
                        sum(not candidate.closed for candidate in bindings),
                    )
                    return binding

                with (
                    self._modeled_windows_cleanup_context(open_binding),
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_capture,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "2" * 32,
                            "nested-branches",
                        )
                    )

                self.assertEqual(warnings, ())
                self.assertEqual(
                    len(bindings),
                    1 + branch_count * 3,
                )
                self.assertEqual(maximum_live_bindings, 3)
                self.assertTrue(all(binding.closed for binding in bindings))
                self.assertTrue(
                    all(binding.close_count == 1 for binding in bindings)
                )
                path_open_counts: dict[str, int] = {}
                for binding in bindings:
                    path_open_counts[binding.path] = (
                        path_open_counts.get(binding.path, 0) + 1
                    )
                self.assertEqual(path_open_counts[os.path.abspath(root_path)], 1)
                for branch_path, leaf_path in branch_paths:
                    self.assertEqual(
                        path_open_counts[os.path.abspath(branch_path)],
                        2,
                    )
                    self.assertEqual(
                        path_open_counts[os.path.abspath(leaf_path)],
                        1,
                    )
                self.assertFalse(os.path.lexists(root_path))
                ancestor_capture_counts.append(ancestor_capture.call_count)
                binding_open_counts.append(len(bindings))
                binding_verify_counts.append(
                    sum(binding.verify_count for binding in bindings)
                )

        self.assertEqual(
            ancestor_capture_counts,
            [ancestor_capture_counts[0]] * len(ancestor_capture_counts),
        )
        self.assertLessEqual(ancestor_capture_counts[0], 32)
        self.assertEqual(binding_open_counts, [49, 769])
        self.assertGreater(binding_verify_counts[1], binding_verify_counts[0])
        self.assertLessEqual(
            binding_verify_counts[1],
            binding_verify_counts[0] * 16 + 64,
        )

    def test_windows_cleanup_binding_operations_scale_with_depth(self) -> None:
        total_entry_count = 40
        metrics: list[tuple[int, int, int, int, int, int]] = []

        for depth in (1, 8, 32):
            with self.subTest(depth=depth):
                root_path = os.path.join(
                    self.godot_dir,
                    f"depth-sweep-{depth}",
                )
                os.mkdir(root_path)
                leaf_directory = root_path
                for _index in range(depth):
                    leaf_directory = os.path.join(leaf_directory, "d")
                    os.mkdir(leaf_directory)
                for index in range(total_entry_count - depth):
                    with open(
                        os.path.join(leaf_directory, f"entry-{index:04d}.txt"),
                        "wb",
                    ) as entry_file:
                        entry_file.write(f"depth payload {index}\n".encode())

                project_stat = os.lstat(self.godot_dir)
                project_identity = project_stat.st_dev, project_stat.st_ino
                with patch.object(
                    _included_posix,
                    'included_descriptor_paths_supported',
                    return_value=False,
                ):
                    snapshot = _included_snapshots.capture_included_tree(
                        root_path,
                        expected_parent_identity=project_identity,
                    )
                self.assertEqual(len(snapshot.entries), total_entry_count)

                bindings: list[_ModeledWindowsCleanupParentBinding] = []
                maximum_live_bindings = 0

                def open_binding(
                    path: str,
                    identity: tuple[int, int],
                ) -> _ModeledWindowsCleanupParentBinding:
                    nonlocal maximum_live_bindings
                    binding = _ModeledWindowsCleanupParentBinding(path, identity)
                    # The real native ``open`` verifies its new handle once
                    # before returning it. Keep that verification in these
                    # operation counts even though the handle itself is modeled.
                    binding.verify()
                    bindings.append(binding)
                    maximum_live_bindings = max(
                        maximum_live_bindings,
                        sum(not candidate.closed for candidate in bindings),
                    )
                    return binding

                binding_opener = MagicMock(side_effect=open_binding)
                verify_parent_binding = (
                    _included_windows.verify_windows_included_cleanup_parent_binding
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )
                with (
                    self._modeled_windows_cleanup_context(binding_opener),
                    patch.object(
                        _included_windows,
                        'verify_windows_included_cleanup_parent_binding',
                        wraps=verify_parent_binding,
                    ) as parent_binding_verifier,
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_capture,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "7" * 32,
                            "depth-sweep",
                        )
                    )

                expected_open_count = depth * 2
                # With the entry count fixed, exchanging one leaf file for one
                # directory adds only five retained-parent checks. It must not
                # cause every entry to walk the complete ancestor chain.
                expected_helper_verify_count = (
                    total_entry_count * 19 + depth * 5 - 2
                )
                expected_native_verify_count = (
                    expected_helper_verify_count + expected_open_count
                )
                self.assertEqual(warnings, ())
                self.assertEqual(binding_opener.call_count, expected_open_count)
                self.assertEqual(
                    parent_binding_verifier.call_count,
                    expected_helper_verify_count,
                )
                self.assertEqual(
                    sum(binding.verify_count for binding in bindings),
                    expected_native_verify_count,
                )
                self.assertEqual(ancestor_capture.call_count, 14)
                self.assertEqual(maximum_live_bindings, depth + 1)
                self.assertTrue(all(binding.closed for binding in bindings))
                self.assertTrue(
                    all(binding.close_count == 1 for binding in bindings)
                )
                self.assertFalse(os.path.lexists(root_path))
                metrics.append(
                    (
                        depth,
                        binding_opener.call_count,
                        parent_binding_verifier.call_count,
                        sum(binding.verify_count for binding in bindings),
                        ancestor_capture.call_count,
                        maximum_live_bindings,
                    )
                )

        self.assertEqual(
            metrics,
            [
                (1, 2, 763, 765, 14, 2),
                (8, 16, 798, 814, 14, 9),
                (32, 64, 918, 982, 14, 33),
            ],
        )

    def test_windows_present_cleanup_chain_exceeds_recursion_limit(self) -> None:
        depth = 128
        modeled_recursion_limit = 80
        self.assertGreater(depth, modeled_recursion_limit)

        root_path = os.path.join(self.godot_dir, "iterative-depth")
        os.mkdir(root_path)
        leaf_directory = root_path
        for _index in range(depth):
            leaf_directory = os.path.join(leaf_directory, "d")
            os.mkdir(leaf_directory)
        payload_path = os.path.join(leaf_directory, "payload.txt")
        with open(payload_path, "wb") as payload_file:
            payload_file.write(b"deep iterative cleanup payload\n")

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        with patch.object(
            _included_posix,
            'included_descriptor_paths_supported',
            return_value=False,
        ):
            snapshot = _included_snapshots.capture_included_tree(
                root_path,
                expected_parent_identity=project_identity,
            )
        self.assertEqual(len(snapshot.entries), depth + 1)

        bindings: list[_ModeledWindowsCleanupParentBinding] = []
        maximum_live_bindings = 0

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            nonlocal maximum_live_bindings
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            binding.verify()
            bindings.append(binding)
            maximum_live_bindings = max(
                maximum_live_bindings,
                sum(not candidate.closed for candidate in bindings),
            )
            return binding

        binding_opener = MagicMock(side_effect=open_binding)
        with self._modeled_windows_cleanup_context(binding_opener):
            previous_recursion_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(modeled_recursion_limit)
            try:
                warnings = _included_cleanup.cleanup_recorded_included_tree(
                    root_path,
                    snapshot,
                    project_identity,
                    "8" * 32,
                    "iterative-depth",
                )
            finally:
                sys.setrecursionlimit(previous_recursion_limit)

        self.assertEqual(warnings, ())
        self.assertEqual(binding_opener.call_count, depth * 2)
        self.assertEqual(maximum_live_bindings, depth + 1)
        self.assertTrue(all(binding.closed for binding in bindings))
        self.assertTrue(all(binding.close_count == 1 for binding in bindings))
        self.assertFalse(os.path.lexists(payload_path))
        self.assertFalse(os.path.lexists(root_path))

    def test_windows_nested_cleanup_keeps_primary_close_errors_as_notes(
        self,
    ) -> None:
        root_path = os.path.join(self.godot_dir, "nested-close-errors")
        nested_path = os.path.join(root_path, "nested")
        owned_path = os.path.join(nested_path, "owned.txt")
        os.makedirs(nested_path)
        with open(owned_path, "wb") as owned_file:
            owned_file.write(b"nested close-error content\n")

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        primary_error = RuntimeError("injected nested cleanup interruption")
        root_close_error = OSError("injected root binding close failure")
        nested_close_error = OSError("injected nested binding close failure")
        bindings: list[_ModeledWindowsCleanupParentBinding] = []

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            close_error = (
                root_close_error
                if os.path.abspath(path) == os.path.abspath(root_path)
                else nested_close_error
            )
            binding = _ModeledWindowsCleanupParentBinding(
                path,
                identity,
                close_error=close_error,
            )
            bindings.append(binding)
            return binding

        def interrupt_after_quarantine(phase: str) -> None:
            if phase == (
                "cleanup:nested-close-errors:nested/owned.txt:quarantined"
            ):
                raise primary_error

        with (
            self._modeled_windows_cleanup_context(open_binding),
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=interrupt_after_quarantine,
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "6" * 32,
                "nested-close-errors",
            )

        self.assertIs(raised.exception, primary_error)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(
            any(str(nested_close_error) in note for note in notes),
            notes,
        )
        self.assertTrue(
            any(str(root_close_error) in note for note in notes),
            notes,
        )
        self.assertEqual(len(bindings), 2)
        self.assertTrue(all(binding.closed for binding in bindings))
        self.assertTrue(all(binding.close_count == 1 for binding in bindings))
        self.assertFalse(os.path.lexists(owned_path))
        tombstone_path = _included_paths.included_cleanup_tombstone_path(
            owned_path,
            "6" * 32,
            "nested-close-errors",
            "nested/owned.txt",
            expect_directory=False,
        )
        self.assertTrue(os.path.isfile(tombstone_path))

    def test_windows_nested_cleanup_rejects_parent_relocation(self) -> None:
        self._assert_windows_nested_cleanup_parent_change_is_preserved(
            install_replacement=False,
        )

    def test_windows_nested_cleanup_rejects_parent_replacement(self) -> None:
        self._assert_windows_nested_cleanup_parent_change_is_preserved(
            install_replacement=True,
        )

    def test_windows_flat_readonly_cleanup_reuses_parent_binding(self) -> None:
        ancestor_capture_counts: list[int] = []

        for entry_count in (16, 256):
            with self.subTest(entry_count=entry_count):
                root_path = os.path.join(
                    self.godot_dir,
                    f"flat-readonly-{entry_count}",
                )
                os.mkdir(root_path)
                for index in range(entry_count):
                    entry_path = os.path.join(
                        root_path,
                        f"entry-{index:04d}.txt",
                    )
                    with open(entry_path, "wb") as entry_file:
                        entry_file.write(f"readonly payload {index}\n".encode())
                    os.chmod(entry_path, 0o400)

                project_stat = os.lstat(self.godot_dir)
                project_identity = project_stat.st_dev, project_stat.st_ino
                snapshot = _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=project_identity,
                )
                capture_ancestors = (
                    _included_snapshots.capture_fallback_directory_ancestors
                )
                supports_without_chmod = set(os.supports_fd)
                supports_without_chmod.discard(os.chmod)
                bindings: list[_ModeledWindowsCleanupParentBinding] = []

                def open_binding(
                    path: str,
                    identity: tuple[int, int],
                ) -> _ModeledWindowsCleanupParentBinding:
                    binding = _ModeledWindowsCleanupParentBinding(path, identity)
                    bindings.append(binding)
                    return binding

                with (
                    patch.object(
                        _included_posix,
                        'included_descriptor_paths_supported',
                        return_value=False,
                    ),
                    patch.object(os, "name", "nt"),
                    patch.object(_included_windows.sys, "platform", "win32"),
                    patch.object(
                        os,
                        "supports_fd",
                        supports_without_chmod,
                    ),
                    patch.object(
                        _included_windows.WindowsIncludedCleanupParentBinding,
                        "open",
                        side_effect=open_binding,
                    ) as binding_open,
                    patch.object(
                        _included_windows,
                        'rename_included_transaction_entry',
                        side_effect=os.rename,
                    ),
                    patch.object(
                        _included_windows,
                        'open_included_file_validation_stream',
                        side_effect=self._open_modeled_windows_validation_stream,
                    ),
                    patch.object(
                        _included_snapshots,
                        'capture_fallback_directory_ancestors',
                        wraps=capture_ancestors,
                    ) as ancestor_capture,
                    patch.object(
                        _included_mutations,
                        'before_included_fallback_chmod_open',
                    ) as chmod_open,
                ):
                    warnings = (
                        _included_cleanup.cleanup_recorded_included_tree(
                            root_path,
                            snapshot,
                            project_identity,
                            "e" * 32,
                            "flat-readonly",
                        )
                    )

                self.assertEqual(warnings, ())
                binding_open.assert_called_once_with(root_path, snapshot.identity)
                self.assertEqual(chmod_open.call_count, entry_count)
                self.assertEqual(len(bindings), 1)
                self.assertTrue(bindings[0].closed)
                self.assertEqual(bindings[0].close_count, 1)
                self.assertFalse(os.path.lexists(root_path))
                ancestor_capture_counts.append(ancestor_capture.call_count)

        self.assertEqual(
            ancestor_capture_counts,
            [ancestor_capture_counts[0]] * len(ancestor_capture_counts),
        )
        self.assertLessEqual(ancestor_capture_counts[0], 32)

    def test_windows_flat_readonly_cleanup_keeps_primary_close_error(self) -> None:
        root_path = os.path.join(self.godot_dir, "flat-readonly-close-error")
        os.mkdir(root_path)
        owned_path = os.path.join(root_path, "owned.txt")
        content = b"readonly close-error payload\n"
        with open(owned_path, "wb") as owned_file:
            owned_file.write(content)
        os.chmod(owned_path, 0o400)

        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        root_identity = snapshot.identity
        if root_identity is None:
            self.fail("captured read-only cleanup root unexpectedly disappeared")
        kernel32 = MagicMock()
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 0
        binding = _included_windows.WindowsIncludedCleanupParentBinding(
            path=os.path.abspath(root_path),
            identity=root_identity,
            kernel32=kernel32,
            handle=1234,
        )
        supports_without_chmod = set(os.supports_fd)
        supports_without_chmod.discard(os.chmod)
        primary_error = RuntimeError("injected read-only cleanup interruption")
        close_error = OSError("injected cleanup parent close failure")

        def interrupt_after_readonly_clear(phase: str) -> None:
            if phase == "cleanup-readonly-cleared":
                raise primary_error

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(_included_windows.sys, "platform", "win32"),
            patch.object(
                os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                _included_windows.WindowsIncludedCleanupParentBinding,
                "open",
                return_value=binding,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_identity',
                return_value=root_identity,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_attributes',
                return_value=(
                    _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                ),
            ),
            patch.object(
                _included_windows,
                'windows_included_transaction_error',
                return_value=close_error,
            ),
            patch.object(
                _included_windows,
                'rename_included_transaction_entry',
                side_effect=os.rename,
            ),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            patch.object(
                _included_phases,
                'after_included_transaction_phase',
                side_effect=interrupt_after_readonly_clear,
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "f" * 32,
                "flat-readonly-close-error",
            )

        self.assertIs(raised.exception, primary_error)
        self.assertTrue(
            any(
                "Could not close Included Files cleanup parent binding"
                in note
                and str(close_error) in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        self.assertIsNone(binding.handle)
        kernel32.CloseHandle.assert_called_once_with(1234)
        self.assertFalse(os.path.lexists(owned_path))
        tombstone_path = _included_paths.included_cleanup_tombstone_path(
            owned_path,
            "f" * 32,
            "flat-readonly-close-error",
            "owned.txt",
            expect_directory=False,
        )
        self.assertTrue(os.lstat(tombstone_path).st_mode & stat.S_IWRITE)

    def test_windows_flat_cleanup_rejects_parent_relocation(self) -> None:
        self._assert_windows_flat_cleanup_parent_change_is_preserved(
            install_replacement=False,
        )

    def test_windows_flat_cleanup_rejects_parent_replacement(self) -> None:
        self._assert_windows_flat_cleanup_parent_change_is_preserved(
            install_replacement=True,
        )

    def test_cleanup_preserves_directory_that_reappears_after_absence_proof(
        self,
    ) -> None:
        root_path = os.path.join(self.godot_dir, "reappearing-stage")
        nested_path = os.path.join(root_path, "included_files")
        os.makedirs(nested_path)
        owned_path = os.path.join(nested_path, "payload.txt")
        with open(owned_path, "wb") as owned_file:
            owned_file.write(b"owned payload")
        project_stat = os.lstat(self.godot_dir)
        project_identity = (project_stat.st_dev, project_stat.st_ino)
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        published_path = os.path.join(self.godot_dir, "published-owned")
        os.rename(nested_path, published_path)
        replacement_path = os.path.join(nested_path, "payload.txt")
        nested_normalized = os.path.normcase(os.path.abspath(nested_path))
        cleanup_directory_state = (
            _included_cleanup.included_cleanup_directory_state
        )
        replacement_created = False

        def create_replacement_after_absence(
            path: str,
            expected_identity: tuple[int, int],
            expected_parent_identity: tuple[int, int],
            *,
            windows_parent_binding: (
                _included_windows.WindowsIncludedCleanupParentBinding | None
            ) = None,
        ) -> bool | None:
            nonlocal replacement_created
            state = cleanup_directory_state(
                path,
                expected_identity,
                expected_parent_identity,
                windows_parent_binding=windows_parent_binding,
            )
            if (
                not replacement_created
                and state is None
                and os.path.normcase(os.path.abspath(path)) == nested_normalized
            ):
                os.mkdir(nested_path)
                with open(replacement_path, "wb") as replacement_file:
                    replacement_file.write(b"external replacement")
                replacement_created = True
            return state

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_cleanup,
                'included_cleanup_directory_state',
                side_effect=create_replacement_after_absence,
            ),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "b" * 32,
                "stage",
            )

        self.assertTrue(replacement_created)
        self.assertTrue(
            any(
                "unknown Included Files cleanup directory" in warning
                for warning in warnings
            ),
            warnings,
        )
        with open(replacement_path, "rb") as replacement_file:
            self.assertEqual(replacement_file.read(), b"external replacement")
        with open(
            os.path.join(published_path, "payload.txt"),
            "rb",
        ) as published_file:
            self.assertEqual(published_file.read(), b"owned payload")
        self.assertTrue(os.path.isdir(root_path))

    def test_owned_tree_cleanup_preserves_modeled_nested_mount(self) -> None:
        variants = [("fallback", False)]
        if (
            _included_posix.included_descriptor_paths_supported()
            and _included_posix.included_native_noreplace_available()
        ):
            variants.append(("descriptor", True))

        for label, descriptor_paths_supported in variants:
            with self.subTest(cleanup_path=label):
                root_name = f"owned-cleanup-{label}"
                root_path = os.path.join(self.godot_dir, root_name)
                mounted_path = os.path.join(root_path, "mounted")
                sentinel_name = f"external-sentinel-{label}.txt"
                sentinel_path = os.path.join(mounted_path, sentinel_name)
                os.makedirs(mounted_path)
                with open(sentinel_path, "wb") as sentinel_file:
                    sentinel_file.write(b"legacy cleanup mount sentinel")
                root_stat = os.lstat(root_path)
                project_stat = os.lstat(self.godot_dir)

                def modeled_mountpoint(path: str) -> bool:
                    return os.path.basename(os.path.normpath(path)) == "mounted"

                with (
                    patch.object(
                        _included_posix,
                        'included_descriptor_paths_supported',
                        return_value=descriptor_paths_supported,
                    ),
                    patch.object(
                        os,
                        "name",
                        os.name if descriptor_paths_supported else "nt",
                    ),
                    patch.object(
                        os.path,
                        "ismount",
                        side_effect=modeled_mountpoint,
                    ),
                    self.assertRaisesRegex(OSError, "mount boundary"),
                ):
                    _included_mutations.remove_owned_included_tree(
                        root_path,
                        (root_stat.st_dev, root_stat.st_ino),
                        expected_parent_identity=(
                            project_stat.st_dev,
                            project_stat.st_ino,
                        ),
                    )

                retained_sentinel_paths = [
                    os.path.join(
                        self.godot_dir,
                        candidate_name,
                        "mounted",
                        sentinel_name,
                    )
                    for candidate_name in os.listdir(self.godot_dir)
                    if os.path.isfile(
                        os.path.join(
                            self.godot_dir,
                            candidate_name,
                            "mounted",
                            sentinel_name,
                        )
                    )
                ]
                self.assertEqual(len(retained_sentinel_paths), 1)
                with open(
                    retained_sentinel_paths[0],
                    "rb",
                ) as retained_sentinel:
                    self.assertEqual(
                        retained_sentinel.read(),
                        b"legacy cleanup mount sentinel",
                    )

    def test_native_linux_same_device_bind_mount_is_rejected(self) -> None:
        if not sys.platform.startswith("linux"):
            self.skipTest("Native Linux bind mounts are unavailable")
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned Included Files paths are unavailable")
        mount_tool = shutil.which("mount")
        umount_tool = shutil.which("umount")
        if mount_tool is None or umount_tool is None:
            self.skipTest("mount/umount are unavailable")

        workspace = tempfile.mkdtemp(prefix="gm2godot-bind-mount-")
        project_path = os.path.join(workspace, "project")
        root_path = os.path.join(project_path, "included_files")
        mounted_path = os.path.join(root_path, "mounted")
        external_path = os.path.join(workspace, "external")
        sentinel_path = os.path.join(external_path, "external-sentinel.txt")
        os.makedirs(mounted_path)
        os.makedirs(external_path)
        with open(sentinel_path, "wb") as sentinel_file:
            sentinel_file.write(b"native bind mount sentinel")
        mounted = False
        try:
            mount_result = subprocess.run(
                (mount_tool, "--bind", external_path, mounted_path),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if mount_result.returncode != 0:
                self.skipTest(
                    "bind mount permission unavailable: "
                    + (mount_result.stderr.strip() or mount_result.stdout.strip())
                )
            mounted = True
            self.assertEqual(
                os.lstat(project_path).st_dev,
                os.lstat(external_path).st_dev,
            )
            project_stat = os.lstat(project_path)
            with (
                patch.object(
                    os.path,
                    "ismount",
                    return_value=False,
                ),
                self.assertRaisesRegex(OSError, "mount boundary"),
            ):
                _included_snapshots.capture_included_tree(
                    root_path,
                    expected_parent_identity=(
                        project_stat.st_dev,
                        project_stat.st_ino,
                    ),
                )
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"native bind mount sentinel",
                )
        finally:
            if mounted:
                unmount_result = subprocess.run(
                    (umount_tool, mounted_path),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if unmount_result.returncode != 0:
                    unmount_result = subprocess.run(
                        (umount_tool, "-l", mounted_path),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                if unmount_result.returncode != 0:
                    raise RuntimeError(
                        "Could not unmount native bind-mount test path; retained "
                        + workspace
                    )
                mounted = False
            if not mounted:
                shutil.rmtree(workspace)

    def test_transaction_debris_helper_detects_every_artifact_family(
        self,
    ) -> None:
        token = "a" * 16
        cleanup_digest = "b" * 64
        registry_backup_name = (
            ".gml_included_file_registry.gd." + token + ".backup"
        )
        cases = (
            (
                "journal",
                _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                False,
            ),
            (
                "commit-marker",
                _included_constants.INCLUDED_FILES_COMMIT_NAME,
                False,
            ),
            (
                "stage-marker",
                _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME,
                False,
            ),
            (
                "journal-temporary",
                _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "commit-temporary",
                _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "lock-initialization-temporary",
                _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "lock-cleanup-tombstone",
                _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "stage",
                _included_constants.INCLUDED_FILES_STAGE_PREFIX
                + token
                + ".stage",
                True,
            ),
            ("root-backup", ".included_files." + token + ".backup", True),
            ("project-registry-backup", registry_backup_name, False),
            (
                "nested-registry-backup",
                os.path.join("gm2godot", registry_backup_name),
                False,
            ),
            (
                "cleanup-file-tombstone",
                _included_constants.INCLUDED_FILES_CLEANUP_PREFIX
                + cleanup_digest
                + ".file",
                False,
            ),
            (
                "cleanup-directory-tombstone",
                _included_constants.INCLUDED_FILES_CLEANUP_PREFIX
                + cleanup_digest
                + ".dir",
                True,
            ),
            (
                "nested-lock-collision",
                os.path.join(
                    "gm2godot",
                    _included_constants.INCLUDED_FILES_LOCK_NAME,
                ),
                False,
            ),
        )

        for label, relative_path, is_directory in cases:
            with (
                self.subTest(artifact=label),
                tempfile.TemporaryDirectory() as project_path,
            ):
                lock_path = os.path.join(
                    project_path,
                    _included_constants.INCLUDED_FILES_LOCK_NAME,
                )
                with open(lock_path, "wb") as lock_file:
                    lock_file.write(
                        _included_constants.INCLUDED_FILES_LOCK_CONTENT
                    )
                self.assertEqual(
                    _included_files_transaction_debris(project_path),
                    (),
                )

                artifact_path = os.path.join(project_path, relative_path)
                if is_directory:
                    os.makedirs(artifact_path)
                else:
                    os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                    with open(artifact_path, "wb") as artifact_file:
                        artifact_file.write(b"transaction artifact\n")

                self.assertEqual(
                    _included_files_transaction_debris(project_path),
                    (relative_path.replace(os.sep, "/"),),
                )

    def test_canonical_tampered_commit_receipts_are_rejected_without_cleanup(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = _included_records.read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = _included_records.read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        _journal_identity, journal_payload = journal_record
        _commit_identity, commit_payload = commit_record
        journal = _included_codec.included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        committed_pair = self._pair_snapshot()
        self.assertEqual(committed_pair[1], {"new.txt": b"new generation"})

        os.unlink(journal_path)
        _included_posix.sync_included_directory(
            self.godot_dir,
            project_identity,
        )

        def recovery_artifact_snapshot() -> tuple[
            tuple[int, int],
            bytes,
            tuple[int, int],
            bytes,
            tuple[int, int],
            tuple[str, ...],
        ]:
            root_backup_stat = os.lstat(journal.root_backup_path)
            with open(
                os.path.join(journal.root_backup_path, "old.txt"),
                "rb",
            ) as root_backup_file:
                root_backup_content = root_backup_file.read()
            registry_backup_stat = os.lstat(journal.registry_backup_path)
            with open(journal.registry_backup_path, "rb") as registry_backup_file:
                registry_backup_content = registry_backup_file.read()
            stage_stat = os.lstat(journal.transaction.stage_container_path)
            return (
                (root_backup_stat.st_dev, root_backup_stat.st_ino),
                root_backup_content,
                (registry_backup_stat.st_dev, registry_backup_stat.st_ino),
                registry_backup_content,
                (stage_stat.st_dev, stage_stat.st_ino),
                tuple(sorted(os.listdir(journal.transaction.stage_container_path))),
            )

        def recover() -> str | None:
            project_lock = _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return _included_recovery.recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                _included_locking.release_included_project_lock(
                    project_lock
                )

        mutations = (
            (
                "copied-project-receipt",
                "project_identity",
                [project_identity[0], project_identity[1] + 1],
            ),
            ("root-receipt", "root_snapshot_sha256", "0" * 64),
            ("registry-receipt", "registry_content_sha256", "0" * 64),
        )
        for label, key, replacement in mutations:
            with self.subTest(receipt=label):
                tampered_payload = dict(commit_payload)
                tampered_payload[key] = replacement
                tampered_content = (
                    _included_codec.included_recovery_record_content(
                        tampered_payload
                    )
                )
                with open(commit_path, "wb") as commit_file:
                    commit_file.write(tampered_content)
                commit_stat = os.lstat(commit_path)
                commit_identity = (commit_stat.st_dev, commit_stat.st_ino)
                artifact_snapshot = recovery_artifact_snapshot()

                with self.assertRaises(OSError):
                    recover()

                current_commit_stat = os.lstat(commit_path)
                self.assertEqual(
                    (current_commit_stat.st_dev, current_commit_stat.st_ino),
                    commit_identity,
                )
                with open(commit_path, "rb") as commit_file:
                    self.assertEqual(commit_file.read(), tampered_content)
                self.assertEqual(
                    recovery_artifact_snapshot(),
                    artifact_snapshot,
                )
                self.assertEqual(self._pair_snapshot(), committed_pair)

        original_commit_content = (
            _included_codec.included_recovery_record_content(commit_payload)
        )
        with open(commit_path, "wb") as commit_file:
            commit_file.write(original_commit_content)
        recovery_message = recover()
        self.assertIsNotNone(recovery_message)
        self.assertIn("already committed", recovery_message or "")
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self.assertFalse(os.path.lexists(journal.root_backup_path))
        self.assertFalse(os.path.lexists(journal.registry_backup_path))
        self.assertFalse(
            os.path.lexists(journal.transaction.stage_container_path)
        )
        self.assertFalse(os.path.lexists(commit_path))

    def test_digest_accepts_stable_path_handle_metadata_skew(self) -> None:
        payload = b"stable staged payload"
        staged_path = os.path.join(self.godot_dir, "staged.bin")
        with open(staged_path, "wb") as staged_file:
            staged_file.write(payload)
        path_stat = os.lstat(staged_path)
        handle_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=1,
        )

        with patch.object(
            os,
            "fstat",
            side_effect=(handle_stat, handle_stat),
        ):
            digest = _included_snapshots.digest_included_regular_file(
                staged_path,
                path_stat,
            )

        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

    def test_digest_rejects_open_handle_change_during_hashing(self) -> None:
        staged_path = os.path.join(self.godot_dir, "staged.bin")
        with open(staged_path, "wb") as staged_file:
            staged_file.write(b"mutated staged payload")
        path_stat = os.lstat(staged_path)
        opened_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=1,
        )
        changed_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=2,
        )

        with (
            patch.object(
                os,
                "fstat",
                side_effect=(opened_stat, changed_stat),
            ),
            self.assertRaisesRegex(OSError, "changed while hashing"),
        ):
            _included_snapshots.digest_included_regular_file(
                staged_path,
                path_stat,
            )

    def test_windows_validation_stream_denies_writes_and_reparse_following(
        self,
    ) -> None:
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        msvcrt = MagicMock()
        msvcrt.open_osfhandle.return_value = 5678
        binary_stream = MagicMock()
        path = os.path.join(self.godot_dir, "payload.bin")

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_file_read_api',
                return_value=kernel32,
            ),
            patch.dict(sys.modules, {"msvcrt": msvcrt}),
            patch.object(
                os,
                "fdopen",
                return_value=binary_stream,
            ) as fdopen,
        ):
            opened_stream = (
                _included_windows.open_included_file_validation_stream(
                    path,
                    deny_writes=True,
                    no_follow=True,
                )
            )

        self.assertIs(opened_stream, binary_stream)
        kernel32.CreateFileW.assert_called_once_with(
            _included_paths.windows_extended_included_path(path),
            _included_windows.WINDOWS_GENERIC_READ,
            _included_windows.WINDOWS_FILE_SHARE_READ,
            None,
            _included_windows.WINDOWS_OPEN_EXISTING,
            _included_windows.WINDOWS_FILE_ATTRIBUTE_NORMAL
            | _included_windows.WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
            | _included_windows.WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
        msvcrt.open_osfhandle.assert_called_once_with(
            1234,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        fdopen.assert_called_once_with(5678, "rb")
        kernel32.CloseHandle.assert_not_called()

    def test_modeled_windows_cleanup_parent_binding_omits_delete_sharing(
        self,
    ) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-binding")
        os.mkdir(parent_path)
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 1

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_api',
                return_value=kernel32,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_identity',
                return_value=parent_identity,
            ) as identify,
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_attributes',
                return_value=(
                    _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                ),
            ) as inspect_attributes,
        ):
            binding = (
                _included_windows.WindowsIncludedCleanupParentBinding.open(
                    parent_path,
                    parent_identity,
                )
            )
            binding.verify()
            binding.close()
            binding.close()

        kernel32.CreateFileW.assert_called_once_with(
            _included_paths.windows_extended_included_path(parent_path),
            _included_windows.WINDOWS_FILE_TRAVERSE
            | _included_windows.WINDOWS_FILE_READ_ATTRIBUTES,
            _included_windows.WINDOWS_FILE_SHARE_READ
            | _included_windows.WINDOWS_FILE_SHARE_WRITE,
            None,
            _included_windows.WINDOWS_OPEN_EXISTING,
            _included_windows.WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
            | _included_windows.WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        share_mode = kernel32.CreateFileW.call_args.args[2]
        self.assertEqual(
            share_mode & _included_windows.WINDOWS_FILE_SHARE_DELETE,
            0,
        )
        self.assertEqual(identify.call_count, 2)
        self.assertEqual(inspect_attributes.call_count, 2)
        kernel32.CloseHandle.assert_called_once_with(1234)

    def test_modeled_windows_cleanup_parent_revalidation_rejects_new_identity(
        self,
    ) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-identity")
        os.mkdir(parent_path)
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        changed_identity = parent_identity[0], parent_identity[1] + 1
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 1

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_api',
                return_value=kernel32,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_identity',
                side_effect=(parent_identity, changed_identity),
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_attributes',
                return_value=(
                    _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                ),
            ),
        ):
            binding = (
                _included_windows.WindowsIncludedCleanupParentBinding.open(
                    parent_path,
                    parent_identity,
                )
            )
            try:
                with self.assertRaisesRegex(OSError, "cleanup parent changed"):
                    binding.verify()
            finally:
                binding.close()

        kernel32.CloseHandle.assert_called_once_with(1234)

    def test_modeled_windows_cleanup_parent_rejects_reparse_handle(self) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-reparse")
        os.mkdir(parent_path)
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 1

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_api',
                return_value=kernel32,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_identity',
                return_value=parent_identity,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_attributes',
                return_value=(
                    _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                    | _included_windows.WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
                ),
            ),
            self.assertRaisesRegex(OSError, "cleanup parent changed"),
        ):
            _included_windows.WindowsIncludedCleanupParentBinding.open(
                parent_path,
                parent_identity,
            )

        kernel32.CloseHandle.assert_called_once_with(1234)

    def test_modeled_windows_cleanup_parent_close_failure_is_one_shot(
        self,
    ) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-close")
        os.mkdir(parent_path)
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 1

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_api',
                return_value=kernel32,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_identity',
                return_value=parent_identity,
            ),
            patch.object(
                _included_windows,
                'windows_included_cleanup_parent_attributes',
                return_value=(
                    _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                ),
            ),
        ):
            binding = (
                _included_windows.WindowsIncludedCleanupParentBinding.open(
                    parent_path,
                    parent_identity,
                )
            )
            kernel32.CloseHandle.return_value = 0
            close_error = OSError("injected cleanup handle close failure")
            with (
                patch.object(
                    _included_windows,
                    'windows_included_transaction_error',
                    return_value=close_error,
                ),
                self.assertRaises(OSError) as raised,
            ):
                binding.close()
            self.assertIs(raised.exception, close_error)
            binding.close()

        kernel32.CloseHandle.assert_called_once_with(1234)

    def test_modeled_windows_cleanup_parent_rejects_path_replacement(self) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-path")
        parked_path = os.path.join(self.godot_dir, "cleanup-parent-parked")
        os.mkdir(parent_path)
        original_file = os.path.join(parent_path, "owned.txt")
        with open(original_file, "wb") as output_file:
            output_file.write(b"original parent content\n")
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        kernel32.GetFileType.return_value = (
            _included_windows.WINDOWS_FILE_TYPE_DISK
        )
        kernel32.CloseHandle.return_value = 1
        binding: (
            _included_windows.WindowsIncludedCleanupParentBinding | None
        ) = None

        try:
            with (
                patch.object(os, "name", "nt"),
                patch.object(
                    _included_windows,
                    'windows_included_cleanup_parent_api',
                    return_value=kernel32,
                ),
                patch.object(
                    _included_windows,
                    'windows_included_cleanup_parent_identity',
                    return_value=parent_identity,
                ),
                patch.object(
                    _included_windows,
                    'windows_included_cleanup_parent_attributes',
                    return_value=(
                        _included_windows.WINDOWS_FILE_ATTRIBUTE_DIRECTORY
                    ),
                ),
            ):
                binding = (
                    _included_windows.WindowsIncludedCleanupParentBinding.open(
                        parent_path,
                        parent_identity,
                    )
                )
                os.rename(parent_path, parked_path)
                os.mkdir(parent_path)
                with self.assertRaisesRegex(
                    OSError,
                    "cleanup parent changed",
                ):
                    binding.verify()
        finally:
            if binding is not None:
                binding.close()
            if os.path.isdir(parent_path):
                os.rmdir(parent_path)
            if os.path.isdir(parked_path):
                os.rename(parked_path, parent_path)

        with open(original_file, "rb") as input_file:
            self.assertEqual(input_file.read(), b"original parent content\n")

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_cleanup_parent_binding_blocks_relocation(self) -> None:
        parent_path = os.path.join(self.godot_dir, "cleanup-parent-native")
        parked_path = os.path.join(self.godot_dir, "cleanup-parent-moved")
        os.mkdir(parent_path)
        parent_stat = os.lstat(parent_path)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        binding = (
            _included_windows.WindowsIncludedCleanupParentBinding.open(
                parent_path,
                parent_identity,
            )
        )
        try:
            with self.assertRaises(OSError):
                os.rename(parent_path, parked_path)
            binding.verify()
        finally:
            binding.close()
            if os.path.isdir(parked_path):
                os.rename(parked_path, parent_path)

        os.rename(parent_path, parked_path)
        self.assertFalse(os.path.lexists(parent_path))
        os.rename(parked_path, parent_path)

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_cleanup_parent_binding_rejects_junction(self) -> None:
        junction_path = os.path.join(
            self.godot_dir,
            "cleanup-parent-junction",
        )
        target_path = self._make_native_windows_junction_target(
            "cleanup-parent-binding"
        )
        self._make_native_windows_junction(junction_path, target_path)
        try:
            junction_stat = os.lstat(junction_path)
            with self.assertRaisesRegex(OSError, "cleanup parent changed"):
                _included_windows.WindowsIncludedCleanupParentBinding.open(
                    junction_path,
                    (junction_stat.st_dev, junction_stat.st_ino),
                )
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(junction_path)

    def test_windows_native_paths_use_extended_length_namespace(self) -> None:
        cases = {
            r"C:\projects\game": r"\\?\C:\projects\game",
            r"\\server\share\game": r"\\?\UNC\server\share\game",
            r"\\?\C:\already\extended": r"\\?\C:\already\extended",
            r"\\.\C:": r"\\.\C:",
        }

        def unchanged_absolute_path(path: str) -> str:
            return path

        with patch.object(
            os.path,
            "abspath",
            side_effect=unchanged_absolute_path,
        ):
            for path, expected in cases.items():
                with self.subTest(path=path):
                    self.assertEqual(
                        _included_paths.windows_extended_included_path(
                            path
                        ),
                        expected,
                    )

    def test_windows_transaction_move_uses_extended_length_paths(self) -> None:
        kernel32 = MagicMock()
        kernel32.MoveFileExW.return_value = 1
        source = os.path.join(self.godot_dir, "source")
        destination = os.path.join(self.godot_dir, "destination")

        with (
            patch.object(os, "name", "nt"),
            patch.object(_included_windows.sys, "platform", "win32"),
            patch.object(
                _included_windows,
                'windows_included_transaction_api',
                return_value=kernel32,
            ),
        ):
            _included_windows.rename_included_transaction_entry(
                source,
                destination,
            )

        source_argument, destination_argument, flags = (
            kernel32.MoveFileExW.call_args.args
        )
        self.assertTrue(source_argument.startswith("\\\\?\\"))
        self.assertTrue(destination_argument.startswith("\\\\?\\"))
        self.assertEqual(
            flags,
            _included_windows.WINDOWS_MOVEFILE_WRITE_THROUGH,
        )

    def test_windows_validation_stream_closes_fd_when_wrapping_fails(
        self,
    ) -> None:
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        msvcrt = MagicMock()
        msvcrt.open_osfhandle.return_value = 5678

        with (
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_file_read_api',
                return_value=kernel32,
            ),
            patch.dict(sys.modules, {"msvcrt": msvcrt}),
            patch.object(
                os,
                "fdopen",
                side_effect=MemoryError("injected wrapper failure"),
            ),
            patch.object(os, "close") as close,
            self.assertRaisesRegex(MemoryError, "injected wrapper failure"),
        ):
            _included_windows.open_included_file_validation_stream(
                os.path.join(self.godot_dir, "payload.bin"),
                deny_writes=True,
                no_follow=True,
            )

        close.assert_called_once_with(5678)
        kernel32.CloseHandle.assert_not_called()

    def test_descriptor_digest_rechecks_the_open_handle(self) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned Included Files paths are unavailable")
        payload = b"descriptor staged payload"
        staged_path = os.path.join(self.godot_dir, "staged.bin")
        with open(staged_path, "wb") as staged_file:
            staged_file.write(payload)
        path_stat = os.lstat(staged_path)
        opened_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=1,
        )
        changed_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=2,
        )
        parent_fd = _included_posix.open_pinned_included_directory(
            self.godot_dir
        )
        try:
            with patch.object(
                os,
                "fstat",
                side_effect=(opened_stat, opened_stat),
            ):
                digest = _included_snapshots.digest_included_regular_file_at(
                    parent_fd,
                    "staged.bin",
                    path_stat,
                    staged_path,
                )
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

            with (
                patch.object(
                    os,
                    "fstat",
                    side_effect=(opened_stat, changed_stat),
                ),
                self.assertRaisesRegex(OSError, "changed while hashing"),
            ):
                _included_snapshots.digest_included_regular_file_at(
                    parent_fd,
                    "staged.bin",
                    path_stat,
                    staged_path,
                )
        finally:
            os.close(parent_fd)

    def test_cleanup_root_swap_does_not_delete_unknown_replacement(
        self,
    ) -> None:
        logs: list[str] = []
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=logs.append,
            progress_callback=lambda _value: None,
            conversion_running=self.running.is_set,
            max_workers=1,
        )
        self._write("old.txt", "old")
        converter.convert_all()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        victim_path = os.path.join(self.godot_dir, ".cleanup-victim")
        os.mkdir(victim_path)
        with open(
            os.path.join(victim_path, "victim.txt"),
            "w",
            encoding="utf-8",
        ) as victim_file:
            victim_file.write("victim sentinel")
        parked_backup = os.path.join(self.godot_dir, ".parked-old-root")
        swapped_backup_path: str | None = None
        cleanup_recorded_tree = (
            _included_cleanup.cleanup_recorded_included_tree
        )

        def swap_cleanup_root(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal swapped_backup_path
            if swapped_backup_path is None and role == "root-backup":
                os.rename(path, parked_backup)
                os.rename(victim_path, path)
                swapped_backup_path = path
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with patch.object(
            _included_cleanup,
            'cleanup_recorded_included_tree',
            side_effect=swap_cleanup_root,
        ):
            converter.convert_all()

        self.assertIsNotNone(swapped_backup_path)
        with open(
            os.path.join(self.godot_dir, "included_files", "new.txt"),
            encoding="utf-8",
        ) as public_file:
            self.assertEqual(public_file.read(), "new")
        with open(
            os.path.join(parked_backup, "old.txt"),
            encoding="utf-8",
        ) as parked_file:
            self.assertEqual(parked_file.read(), "old")
        if swapped_backup_path is not None:
            with open(
                os.path.join(swapped_backup_path, "victim.txt"),
                encoding="utf-8",
            ) as victim_file:
                self.assertEqual(victim_file.read(), "victim sentinel")
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(swapped_backup_path),),
            )
        self.assertTrue(
            any("transaction cleanup failed" in message for message in logs),
            logs,
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_cleanup_file_swap_restores_unknown_replacement_without_loss(
        self,
    ) -> None:
        if not (
            _included_posix.included_descriptor_paths_supported()
            and _included_posix.included_native_noreplace_available()
        ):
            self.skipTest("Descriptor-pinned no-replace rename is unavailable")
        cleanup_directory = os.path.join(self.godot_dir, "file-cleanup-swap")
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        replacement_path = os.path.join(cleanup_directory, "replacement.txt")
        parked_path = os.path.join(cleanup_directory, "parked-owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned cleanup file")
        with open(replacement_path, "w", encoding="utf-8") as replacement_file:
            replacement_file.write("unknown replacement")
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        swapped = False

        def swap_cleanup_file(parent_fd: int, name: str) -> None:
            nonlocal swapped
            if swapped or name != "owned.txt":
                return
            os.rename(
                name,
                os.path.basename(parked_path),
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.rename(
                os.path.basename(replacement_path),
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            swapped = True

        with patch.object(
            _included_mutations,
            'before_included_transaction_rename',
            side_effect=swap_cleanup_file,
        ), self.assertRaisesRegex(OSError, "restored without loss"):
            _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                hashlib.sha256(b"owned cleanup file").hexdigest(),
                (
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
                "c" * 32,
                "test-file-swap",
                "owned.txt",
                expected_fingerprint=(
                    _included_metadata.included_path_fingerprint(owned_stat)
                ),
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertTrue(swapped)
        with open(owned_path, encoding="utf-8") as owned_file:
            self.assertEqual(owned_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as parked_file:
            self.assertEqual(parked_file.read(), "owned cleanup file")

    def test_descriptor_cleanup_streams_payload_receipts(self) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned cleanup is unavailable")
        self._assert_streaming_cleanup_path(force_fallback=False)

    def test_forced_fallback_cleanup_streams_payload_receipts(self) -> None:
        self._assert_streaming_cleanup_path(force_fallback=True)

    def test_64_mib_cleanup_has_bounded_memory_and_two_streaming_passes(
        self,
    ) -> None:
        payload_size = 64 * 1024 * 1024
        cleanup_directory = os.path.join(
            self.godot_dir,
            "large-streaming-cleanup",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "large.bin")
        with open(owned_path, "wb") as owned_file:
            owned_file.truncate(payload_size)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        zero_chunk = b"\0" * (1024 * 1024)
        expected_digest = hashlib.sha256()
        for _index in range(payload_size // len(zero_chunk)):
            expected_digest.update(zero_chunk)
        del zero_chunk

        streamed_bytes = 0
        largest_chunk = 0
        original_read = _included_snapshots.read_included_validation_chunk

        def count_streamed_bytes(opened_file: BinaryIO) -> bytes:
            nonlocal streamed_bytes, largest_chunk
            chunk = original_read(opened_file)
            streamed_bytes += len(chunk)
            largest_chunk = max(largest_chunk, len(chunk))
            return chunk

        tracemalloc.start()
        try:
            with (
                patch.object(
                    _included_snapshots,
                    'read_included_validation_chunk',
                    side_effect=count_streamed_bytes,
                ),
                patch.object(
                    _included_snapshots,
                    'included_regular_file_state',
                    side_effect=AssertionError(
                        "cleanup used the whole-content file-state helper"
                    ),
                ),
            ):
                warnings = (
                    _included_cleanup.cleanup_recorded_included_file(
                        owned_path,
                        (owned_stat.st_dev, owned_stat.st_ino),
                        expected_digest.hexdigest(),
                        (parent_stat.st_dev, parent_stat.st_ino),
                        "f" * 32,
                        "large-streaming-cleanup",
                        "large.bin",
                        expected_fingerprint=(
                            _included_metadata.included_path_fingerprint(
                                owned_stat
                            )
                        ),
                        expected_mode=stat.S_IMODE(owned_stat.st_mode),
                    )
                )
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(warnings, ())
        self.assertEqual(streamed_bytes, 2 * payload_size)
        self.assertLessEqual(largest_chunk, 1024 * 1024)
        self.assertLess(peak_bytes, 8 * 1024 * 1024)
        self.assertFalse(os.path.lexists(owned_path))

    def test_cleanup_tree_final_rmdir_retains_unknown_replacement(
        self,
    ) -> None:
        if not (
            _included_posix.included_descriptor_paths_supported()
            and _included_posix.included_native_noreplace_available()
        ):
            self.skipTest("Descriptor-pinned no-replace rename is unavailable")
        owned_path = os.path.join(self.godot_dir, "owned-empty-tree")
        replacement_path = os.path.join(self.godot_dir, "replacement-empty-tree")
        parked_path = os.path.join(self.godot_dir, "parked-owned-tree")
        os.mkdir(owned_path)
        os.mkdir(replacement_path)
        owned_stat = os.lstat(owned_path)
        replacement_stat = os.lstat(replacement_path)
        project_stat = os.lstat(self.godot_dir)
        retained_path: str | None = None

        def swap_quarantine_before_rmdir(parent_fd: int, name: str) -> None:
            nonlocal retained_path
            if retained_path is not None or not name.startswith(
                ".owned-empty-tree."
            ):
                return
            os.rename(
                name,
                os.path.basename(parked_path),
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.rename(
                os.path.basename(replacement_path),
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            retained_path = os.path.join(self.godot_dir, name)

        with patch.object(
            _included_mutations,
            'before_included_cleanup_remove',
            side_effect=swap_quarantine_before_rmdir,
        ), self.assertRaisesRegex(OSError, "recoverable directory retained"):
            _included_mutations.remove_owned_included_tree(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                expected_parent_identity=(
                    project_stat.st_dev,
                    project_stat.st_ino,
                ),
            )

        self.assertIsNotNone(retained_path)
        self.assertEqual(
            (
                os.lstat(retained_path or "").st_dev,
                os.lstat(retained_path or "").st_ino,
            ),
            (replacement_stat.st_dev, replacement_stat.st_ino),
        )
        self.assertEqual(
            (os.lstat(parked_path).st_dev, os.lstat(parked_path).st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )
        self.assertFalse(os.path.lexists(owned_path))

    def test_registry_capture_rejects_directory_swap_without_mixing_bytes(
        self,
    ) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned registry capture is unavailable")
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        replacement_directory = os.path.join(
            self.godot_dir,
            "replacement-registry",
        )
        parked_directory = os.path.join(self.godot_dir, "parked-registry")
        os.mkdir(registry_directory)
        os.mkdir(replacement_directory)
        registry_name = os.path.basename(INCLUDED_FILE_REGISTRY_RELATIVE_PATH)
        with open(
            os.path.join(registry_directory, registry_name),
            "wb",
        ) as registry_file:
            registry_file.write(b"old registry bytes")
        with open(
            os.path.join(replacement_directory, registry_name),
            "wb",
        ) as replacement_file:
            replacement_file.write(b"new registry bytes")
        swapped = False

        def swap_registry_directory(project_fd: int, name: str) -> None:
            nonlocal swapped
            if swapped:
                return
            os.rename(
                name,
                os.path.basename(parked_directory),
                src_dir_fd=project_fd,
                dst_dir_fd=project_fd,
            )
            os.rename(
                os.path.basename(replacement_directory),
                name,
                src_dir_fd=project_fd,
                dst_dir_fd=project_fd,
            )
            swapped = True

        with patch.object(
            _included_snapshots,
            'before_included_registry_file_read',
            side_effect=swap_registry_directory,
        ), self.assertRaisesRegex(OSError, "directory changed"):
            _included_snapshots.capture_included_registry(self.godot_dir)

        self.assertTrue(swapped)
        with open(
            os.path.join(registry_directory, registry_name),
            "rb",
        ) as registry_file:
            self.assertEqual(registry_file.read(), b"new registry bytes")
        with open(
            os.path.join(parked_directory, registry_name),
            "rb",
        ) as parked_file:
            self.assertEqual(parked_file.read(), b"old registry bytes")

    def test_registry_verifier_rejects_project_swap_before_reading_bytes(
        self,
    ) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned registry capture is unavailable")
        project_path = os.path.join(self.godot_dir, "project-root")
        parked_project = os.path.join(self.godot_dir, "parked-project-root")
        registry_name = os.path.basename(INCLUDED_FILE_REGISTRY_RELATIVE_PATH)
        old_registry_directory = os.path.join(project_path, "gm2godot")
        os.makedirs(old_registry_directory)
        with open(
            os.path.join(old_registry_directory, registry_name),
            "wb",
        ) as registry_file:
            registry_file.write(b"old registry bytes")
        project_stat = os.lstat(project_path)
        project_identity = (project_stat.st_dev, project_stat.st_ino)
        expected_snapshot = _included_snapshots.capture_included_registry(
            project_path,
            expected_project_identity=project_identity,
        )
        os.rename(project_path, parked_project)
        replacement_registry_directory = os.path.join(project_path, "gm2godot")
        os.makedirs(replacement_registry_directory)
        replacement_registry_path = os.path.join(
            replacement_registry_directory,
            registry_name,
        )
        with open(replacement_registry_path, "wb") as replacement_file:
            replacement_file.write(b"new replacement bytes")
        original_file_state_at = (
            _included_snapshots.included_regular_file_state_at
        )
        observed_registry_bytes: list[bytes] = []

        def record_registry_read(
            parent_fd: int,
            name: str,
            display_path: str,
        ) -> tuple[tuple[int, int], int, bytes] | None:
            state = original_file_state_at(parent_fd, name, display_path)
            if state is not None:
                observed_registry_bytes.append(state[2])
            return state

        with patch.object(
            _included_snapshots,
            'included_regular_file_state_at',
            side_effect=record_registry_read,
        ), self.assertRaisesRegex(OSError, "directory changed"):
            _included_snapshots.verify_included_registry_snapshot(
                project_path,
                expected_snapshot,
                expected_project_identity=project_identity,
            )

        self.assertEqual(observed_registry_bytes, [])
        with open(replacement_registry_path, "rb") as replacement_file:
            self.assertEqual(replacement_file.read(), b"new replacement bytes")
        with open(
            os.path.join(parked_project, "gm2godot", registry_name),
            "rb",
        ) as parked_file:
            self.assertEqual(parked_file.read(), b"old registry bytes")

    def test_fallback_registry_read_rejects_project_swap_before_bytes(
        self,
    ) -> None:
        project_path = os.path.join(self.godot_dir, "fallback-project-root")
        replacement_project = os.path.join(
            self.godot_dir,
            "replacement-fallback-project",
        )
        parked_project = os.path.join(
            self.godot_dir,
            "parked-fallback-project",
        )
        registry_name = os.path.basename(INCLUDED_FILE_REGISTRY_RELATIVE_PATH)
        old_registry_path = os.path.join(project_path, "gm2godot", registry_name)
        replacement_registry_path = os.path.join(
            replacement_project,
            "gm2godot",
            registry_name,
        )
        os.makedirs(os.path.dirname(old_registry_path))
        os.makedirs(os.path.dirname(replacement_registry_path))
        with open(old_registry_path, "wb") as registry_file:
            registry_file.write(b"old fallback registry bytes")
        with open(replacement_registry_path, "wb") as replacement_file:
            replacement_file.write(b"new fallback replacement bytes")
        project_stat = os.lstat(project_path)
        project_identity = (project_stat.st_dev, project_stat.st_ino)
        with patch.object(
            _included_posix,
            'included_descriptor_paths_supported',
            return_value=False,
        ):
            expected_snapshot = _included_snapshots.capture_included_registry(
                project_path,
                expected_project_identity=project_identity,
            )
        swapped = False
        opened_for_read: list[int] = []
        original_fdopen = os.fdopen

        def swap_project_before_open(path: str) -> None:
            nonlocal swapped
            if swapped or path != old_registry_path:
                return
            os.rename(project_path, parked_project)
            os.rename(replacement_project, project_path)
            swapped = True

        def record_fdopen(
            file_descriptor: int,
            _mode: str = "r",
        ) -> BinaryIO:
            opened_for_read.append(file_descriptor)
            return original_fdopen(file_descriptor, "rb")

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                _included_snapshots,
                'before_included_fallback_regular_file_open',
                side_effect=swap_project_before_open,
            ),
            patch.object(
                os,
                "fdopen",
                side_effect=record_fdopen,
            ),
            self.assertRaises(OSError),
        ):
            _included_snapshots.verify_included_registry_snapshot(
                project_path,
                expected_snapshot,
                expected_project_identity=project_identity,
            )

        self.assertTrue(swapped)
        self.assertEqual(opened_for_read, [])
        with open(
            os.path.join(project_path, "gm2godot", registry_name),
            "rb",
        ) as replacement_file:
            self.assertEqual(
                replacement_file.read(),
                b"new fallback replacement bytes",
            )
        with open(
            os.path.join(parked_project, "gm2godot", registry_name),
            "rb",
        ) as parked_file:
            self.assertEqual(parked_file.read(), b"old fallback registry bytes")

    def test_fallback_chmod_source_swap_does_not_mutate_replacement(
        self,
    ) -> None:
        chmod_directory = os.path.join(self.godot_dir, "chmod-swap")
        os.mkdir(chmod_directory)
        owned_path = os.path.join(chmod_directory, "owned.txt")
        replacement_path = os.path.join(chmod_directory, "replacement.txt")
        parked_path = os.path.join(chmod_directory, "parked-owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned chmod target")
        with open(replacement_path, "w", encoding="utf-8") as replacement_file:
            replacement_file.write("unknown replacement")
        os.chmod(owned_path, 0o600)
        os.chmod(replacement_path, 0o640)
        owned_stat = os.lstat(owned_path)
        owned_mode = stat.S_IMODE(owned_stat.st_mode)
        replacement_stat = os.lstat(replacement_path)
        replacement_mode = stat.S_IMODE(replacement_stat.st_mode)
        owned_writable = bool(owned_stat.st_mode & stat.S_IWRITE)
        replacement_writable = bool(replacement_stat.st_mode & stat.S_IWRITE)
        parent_stat = os.lstat(chmod_directory)
        swapped = False

        def swap_before_open(path: str) -> None:
            nonlocal swapped
            if swapped or path != owned_path:
                return
            os.rename(owned_path, parked_path)
            os.rename(replacement_path, owned_path)
            swapped = True

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(
                _included_mutations,
                'before_included_fallback_chmod_open',
                side_effect=swap_before_open,
            ),
            self.assertRaisesRegex(OSError, "file changed"),
        ):
            _included_mutations.chmod_exact_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                0o444,
                (parent_stat.st_dev, parent_stat.st_ino),
            )

        self.assertTrue(swapped)
        current_replacement_stat = os.lstat(owned_path)
        current_owned_stat = os.lstat(parked_path)
        self.assertEqual(
            (current_replacement_stat.st_dev, current_replacement_stat.st_ino),
            (replacement_stat.st_dev, replacement_stat.st_ino),
        )
        self.assertEqual(
            (current_owned_stat.st_dev, current_owned_stat.st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )
        self.assertEqual(
            bool(current_replacement_stat.st_mode & stat.S_IWRITE),
            replacement_writable,
        )
        self.assertEqual(
            bool(current_owned_stat.st_mode & stat.S_IWRITE),
            owned_writable,
        )
        with open(owned_path, encoding="utf-8") as replacement_file:
            self.assertEqual(replacement_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as owned_file:
            self.assertEqual(owned_file.read(), "owned chmod target")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(current_replacement_stat.st_mode),
                replacement_mode,
            )
            self.assertEqual(
                stat.S_IMODE(current_owned_stat.st_mode),
                owned_mode,
            )

    def test_windows_fallback_chmod_skips_matching_write_bit(self) -> None:
        chmod_directory = os.path.join(self.godot_dir, "windows-chmod-match")
        os.mkdir(chmod_directory)
        owned_path = os.path.join(chmod_directory, "owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned chmod target")
        os.chmod(owned_path, 0o600)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(chmod_directory)
        supports_without_chmod = set(os.supports_fd)
        supports_without_chmod.discard(os.chmod)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                _included_mutations,
                'before_included_cleanup_quarantine_fallback',
                side_effect=AssertionError("matching mode must not quarantine"),
            ),
        ):
            _included_mutations.chmod_exact_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                0o640,
                (parent_stat.st_dev, parent_stat.st_ino),
            )

        self.assertEqual(
            (os.lstat(owned_path).st_dev, os.lstat(owned_path).st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )

    def test_windows_fallback_chmod_uses_reversible_quarantine(self) -> None:
        chmod_directory = os.path.join(self.godot_dir, "windows-chmod-change")
        os.mkdir(chmod_directory)
        owned_path = os.path.join(chmod_directory, "owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned chmod target")
        os.chmod(owned_path, 0o600)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(chmod_directory)
        supports_without_chmod = set(os.supports_fd)
        supports_without_chmod.discard(os.chmod)
        quarantined_paths: list[str] = []

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                _included_mutations,
                'before_included_cleanup_quarantine_fallback',
                side_effect=quarantined_paths.append,
            ),
        ):
            _included_mutations.chmod_exact_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                0o400,
                (parent_stat.st_dev, parent_stat.st_ino),
            )

        self.assertEqual(quarantined_paths, [owned_path])
        self.assertEqual(
            (os.lstat(owned_path).st_dev, os.lstat(owned_path).st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )
        self.assertFalse(os.lstat(owned_path).st_mode & stat.S_IWRITE)
        self.assertFalse(
            any(name.endswith(".quarantine") for name in os.listdir(chmod_directory))
        )
        os.chmod(owned_path, 0o600)

    def test_windows_deterministic_cleanup_restores_readonly_after_unlink_failure(
        self,
    ) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-deterministic-readonly-failure",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        content = b"owned deterministic cleanup target"
        with open(owned_path, "wb") as owned_file:
            owned_file.write(content)
        os.chmod(owned_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        expected_identity = (owned_stat.st_dev, owned_stat.st_ino)
        expected_parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        expected_fingerprint = _included_metadata.included_path_fingerprint(
            owned_stat
        )
        transaction_id = "a" * 32
        tombstone_path = _included_paths.included_cleanup_tombstone_path(
            owned_path,
            transaction_id,
            "test-readonly",
            "owned.txt",
            expect_directory=False,
        )

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                os,
                "unlink",
                side_effect=PermissionError("injected Windows sharing failure"),
            ),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            self.assertRaisesRegex(
                OSError,
                "recoverable quarantine retained",
            ),
        ):
            _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly",
                "owned.txt",
                expected_fingerprint=expected_fingerprint,
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertFalse(os.path.lexists(owned_path))
        retained_stat = os.lstat(tombstone_path)
        self.assertEqual(
            (retained_stat.st_dev, retained_stat.st_ino),
            expected_identity,
        )
        self.assertFalse(retained_stat.st_mode & stat.S_IWRITE)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly",
                "owned.txt",
                expected_fingerprint=expected_fingerprint,
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertEqual(warnings, ())
        self.assertFalse(os.path.lexists(tombstone_path))

    def test_windows_fallback_cleanup_preserves_readonly_hardlink_alias(
        self,
    ) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-readonly-hardlink-cleanup",
        )
        os.mkdir(cleanup_directory)
        external_path = os.path.join(cleanup_directory, "external.txt")
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        with open(external_path, "w", encoding="utf-8") as external_file:
            external_file.write("external hardlink sentinel")
        try:
            os.link(external_path, owned_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable: {error}")
        os.chmod(external_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            self.assertRaisesRegex(
                OSError,
                "multiple hard links.*recoverable quarantine retained",
            ),
        ):
            _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                hashlib.sha256(b"external hardlink sentinel").hexdigest(),
                (
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
                "d" * 32,
                "test-hardlink",
                "owned.txt",
                expected_fingerprint=(
                    _included_metadata.included_path_fingerprint(owned_stat)
                ),
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        with open(external_path, encoding="utf-8") as external_file:
            self.assertEqual(
                external_file.read(),
                "external hardlink sentinel",
            )
        external_stat = os.lstat(external_path)
        self.assertFalse(external_stat.st_mode & stat.S_IWRITE)
        self.assertEqual(external_stat.st_nlink, 2)
        quarantined_paths = [
            os.path.join(cleanup_directory, name)
            for name in os.listdir(cleanup_directory)
            if name != os.path.basename(external_path)
        ]
        self.assertEqual(len(quarantined_paths), 1)
        quarantined_stat = os.lstat(quarantined_paths[0])
        self.assertEqual(
            (quarantined_stat.st_dev, quarantined_stat.st_ino),
            (external_stat.st_dev, external_stat.st_ino),
        )
        os.chmod(external_path, 0o600)
        os.unlink(quarantined_paths[0])

    def test_windows_fallback_cleanup_removes_readonly_owned_directory(
        self,
    ) -> None:
        parent_directory = os.path.join(
            self.godot_dir,
            "windows-readonly-directory-cleanup",
        )
        owned_directory = os.path.join(parent_directory, "owned")
        os.makedirs(owned_directory)
        os.chmod(owned_directory, 0o400)
        owned_stat = os.lstat(owned_directory)
        parent_stat = os.lstat(parent_directory)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_directory(
                owned_directory,
                (owned_stat.st_dev, owned_stat.st_ino),
                (parent_stat.st_dev, parent_stat.st_ino),
                "e" * 32,
                "test-readonly-directory",
                ".",
            )

        self.assertEqual(warnings, ())
        self.assertFalse(os.path.lexists(owned_directory))
        self.assertEqual(os.listdir(parent_directory), [])

    def test_windows_fallback_cleanup_restores_readonly_directory_after_failure(
        self,
    ) -> None:
        parent_directory = os.path.join(
            self.godot_dir,
            "windows-readonly-directory-cleanup-failure",
        )
        owned_directory = os.path.join(parent_directory, "owned")
        os.makedirs(owned_directory)
        os.chmod(owned_directory, 0o400)
        owned_stat = os.lstat(owned_directory)
        parent_stat = os.lstat(parent_directory)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                os,
                "rmdir",
                side_effect=PermissionError("injected Windows sharing failure"),
            ),
            self.assertRaisesRegex(
                OSError,
                "directory; recoverable quarantine retained",
            ),
        ):
            _included_cleanup.cleanup_recorded_included_directory(
                owned_directory,
                (owned_stat.st_dev, owned_stat.st_ino),
                (parent_stat.st_dev, parent_stat.st_ino),
                "f" * 32,
                "test-readonly-directory-failure",
                ".",
            )

        quarantined_names = os.listdir(parent_directory)
        self.assertEqual(len(quarantined_names), 1)
        quarantined_path = os.path.join(
            parent_directory,
            quarantined_names[0],
        )
        quarantined_stat = os.lstat(quarantined_path)
        self.assertTrue(stat.S_ISDIR(quarantined_stat.st_mode))
        self.assertEqual(
            (quarantined_stat.st_dev, quarantined_stat.st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )
        self.assertFalse(quarantined_stat.st_mode & stat.S_IWRITE)
        os.chmod(quarantined_path, 0o700)
        os.rmdir(quarantined_path)

    @unittest.skipUnless(
        _included_posix.included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_deep_directory_swap_is_not_followed_during_tree_capture(
        self,
    ) -> None:
        scan_root = os.path.join(self.godot_dir, "scan-root")
        deep_directory = os.path.join(scan_root, "a", "b")
        os.makedirs(deep_directory)
        with open(
            os.path.join(deep_directory, "contained.txt"),
            "w",
            encoding="utf-8",
        ) as contained_file:
            contained_file.write("contained")
        outside_directory = os.path.join(self.gm_dir, "outside-scan")
        os.mkdir(outside_directory)
        outside_file = os.path.join(outside_directory, "external.txt")
        with open(outside_file, "w", encoding="utf-8") as external_file:
            external_file.write("external sentinel")
        parked_directory = os.path.join(scan_root, "parked-b")
        original_open = _included_posix.open_included_tree_directory_at
        swapped = False

        def swap_before_open(parent_fd: int, name: str) -> int:
            nonlocal swapped
            if not swapped and name == "b":
                os.rename(deep_directory, parked_directory)
                try:
                    os.symlink(outside_directory, deep_directory)
                except (NotImplementedError, OSError) as error:
                    os.rename(parked_directory, deep_directory)
                    self.skipTest(f"Symbolic links are unavailable: {error}")
                swapped = True
            return original_open(parent_fd, name)

        try:
            with patch.object(
                _included_posix,
                'open_included_tree_directory_at',
                side_effect=swap_before_open,
            ), self.assertRaises(OSError):
                _included_snapshots.capture_included_tree(scan_root)

            self.assertTrue(swapped)
            with open(outside_file, encoding="utf-8") as external_file:
                self.assertEqual(external_file.read(), "external sentinel")
        finally:
            if os.path.islink(deep_directory):
                os.unlink(deep_directory)
            if os.path.isdir(parked_directory):
                os.rename(parked_directory, deep_directory)

    def test_fallback_deep_directory_swap_during_scan_is_detected_before_hashing(
        self,
    ) -> None:
        scan_root = os.path.join(self.godot_dir, "fallback-scan-root")
        deep_directory = os.path.join(scan_root, "a", "b")
        os.makedirs(deep_directory)
        with open(
            os.path.join(deep_directory, "contained.txt"),
            "w",
            encoding="utf-8",
        ) as contained_file:
            contained_file.write("contained")
        outside_directory = os.path.join(self.gm_dir, "fallback-outside-scan")
        os.mkdir(outside_directory)
        outside_file = os.path.join(outside_directory, "external.txt")
        with open(outside_file, "w", encoding="utf-8") as external_file:
            external_file.write("external sentinel")
        parked_directory = os.path.join(scan_root, "parked-b")
        original_digest = _included_snapshots.digest_included_regular_file
        swapped = False

        def swap_after_scan(path: str) -> None:
            nonlocal swapped
            if swapped or os.path.normcase(path) != os.path.normcase(
                deep_directory
            ):
                return
            os.rename(deep_directory, parked_directory)
            os.rename(outside_directory, deep_directory)
            swapped = True

        try:
            with (
                patch.object(
                    _included_posix,
                    'included_descriptor_paths_supported',
                    return_value=False,
                ),
                patch.object(
                    _included_snapshots,
                    'after_included_fallback_tree_directory_scan',
                    side_effect=swap_after_scan,
                ),
                patch.object(
                    _included_snapshots,
                    'digest_included_regular_file',
                    wraps=original_digest,
                ) as digest_file,
                self.assertRaises(OSError),
            ):
                _included_snapshots.capture_included_tree(scan_root)

            self.assertTrue(swapped)
            digest_file.assert_not_called()
            with open(
                os.path.join(deep_directory, "external.txt"),
                encoding="utf-8",
            ) as external_file:
                self.assertEqual(external_file.read(), "external sentinel")
        finally:
            if swapped and os.path.isdir(deep_directory):
                os.rename(deep_directory, outside_directory)
            if os.path.isdir(parked_directory):
                os.rename(parked_directory, deep_directory)

    def test_deep_tree_capture_binding_work_scales_linearly(
        self,
    ) -> None:
        variants = [
            (
                "native-windows-path" if os.name == "nt" else "fallback-path",
                False,
                'verify_included_tree_path_binding',
            )
        ]
        if _included_posix.included_descriptor_paths_supported():
            variants.insert(
                0,
                (
                    "descriptor",
                    True,
                    'verify_included_tree_descriptor_binding',
                ),
            )

        for label, descriptor_supported, verifier_name in variants:
            work_by_depth: list[int] = []
            for depth in (25, 50, 100, 200):
                with self.subTest(path=label, depth=depth):
                    root_path = self._make_deep_tree(
                        f"linear-{label}-{depth}",
                        depth,
                    )
                    original_verifier = getattr(
                        _included_snapshots,
                        verifier_name,
                    )
                    binding_checks = 0

                    def count_binding(
                        binding: object,
                    ) -> object:
                        nonlocal binding_checks
                        binding_checks += 1
                        return original_verifier(binding)

                    with (
                        patch.object(
                            _included_posix,
                            'included_descriptor_paths_supported',
                            return_value=descriptor_supported,
                        ),
                        patch.object(
                            _included_snapshots,
                            verifier_name,
                            side_effect=count_binding,
                        ),
                    ):
                        snapshot = _included_snapshots.capture_included_tree(
                            root_path
                        )

                    self.assertEqual(len(snapshot.entries), depth + 1)
                    self.assertLessEqual(
                        binding_checks,
                        16 * depth + 64,
                    )
                    work_by_depth.append(binding_checks)

            for shallow_work, deep_work in zip(
                work_by_depth[:-1],
                work_by_depth[1:],
                strict=True,
            ):
                with self.subTest(
                    path=label,
                    shallow_work=shallow_work,
                    deep_work=deep_work,
                ):
                    self.assertLessEqual(
                        deep_work,
                        shallow_work * 2.25,
                    )

    @unittest.skipUnless(
        _included_posix.included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_descriptor_tree_capture_rejects_deep_ancestor_swap(
        self,
    ) -> None:
        scan_root = os.path.join(self.godot_dir, "ancestor-swap-root")
        ancestor_path = os.path.join(scan_root, "a")
        deep_directory = os.path.join(ancestor_path, "b", "c")
        os.makedirs(deep_directory)
        with open(
            os.path.join(deep_directory, "contained.txt"),
            "w",
            encoding="utf-8",
        ) as contained_file:
            contained_file.write("contained")
        parked_ancestor = os.path.join(
            self.godot_dir,
            "parked-ancestor",
        )
        deep_identity = (
            os.lstat(deep_directory).st_dev,
            os.lstat(deep_directory).st_ino,
        )
        original_listdir = os.listdir
        swapped = False

        def swap_ancestor_after_deep_scan(
            directory: int | str,
        ) -> list[str]:
            nonlocal swapped
            names = original_listdir(directory)
            if (
                not swapped
                and isinstance(directory, int)
                and (
                    os.fstat(directory).st_dev,
                    os.fstat(directory).st_ino,
                )
                == deep_identity
            ):
                os.rename(ancestor_path, parked_ancestor)
                os.mkdir(ancestor_path)
                with open(
                    os.path.join(ancestor_path, "replacement.txt"),
                    "w",
                    encoding="utf-8",
                ) as replacement_file:
                    replacement_file.write("replacement sentinel")
                swapped = True
            return names

        try:
            with (
                patch.object(
                    _included_posix,
                    'included_descriptor_paths_supported',
                    return_value=True,
                ),
                patch.object(
                    os,
                    "listdir",
                    side_effect=swap_ancestor_after_deep_scan,
                ),
                self.assertRaisesRegex(OSError, "entry changed"),
            ):
                _included_snapshots.capture_included_tree(scan_root)

            self.assertTrue(swapped)
            with open(
                os.path.join(ancestor_path, "replacement.txt"),
                encoding="utf-8",
            ) as replacement_file:
                self.assertEqual(
                    replacement_file.read(),
                    "replacement sentinel",
                )
        finally:
            if swapped and os.path.isdir(ancestor_path):
                shutil.rmtree(ancestor_path)
            if os.path.isdir(parked_ancestor):
                os.rename(parked_ancestor, ancestor_path)

    def test_native_noreplace_preserves_file_and_directory_destinations(
        self,
    ) -> None:
        if not (
            _included_posix.included_descriptor_paths_supported()
            and _included_posix.included_native_noreplace_available()
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
        directory_fd = _included_posix.open_pinned_included_directory(
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
                    _included_posix.rename_included_transaction_entry_at(
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

    def test_native_noreplace_missing_capability_fails_closed(self) -> None:
        if not _included_posix.included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned paths are unavailable")
        transaction_directory = os.path.join(
            self.godot_dir,
            "native-unavailable",
        )
        os.mkdir(transaction_directory)
        source_path = os.path.join(transaction_directory, "source.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("source")
        directory_fd = _included_posix.open_pinned_included_directory(
            transaction_directory
        )
        try:
            with patch.object(
                _included_posix,
                'included_native_noreplace_available',
                return_value=False,
            ), self.assertRaisesRegex(OSError, "unavailable"):
                _included_posix.rename_included_transaction_entry_at(
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

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_backup_cleanup_leaves_no_debris(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        public_directory = os.path.join(public_root, "old")
        public_file = os.path.join(public_directory, "nested.txt")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        for path in (public_file, registry_path, public_directory, public_root):
            os.chmod(path, stat.S_IREAD)

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new/nested.txt": b"new payload"},
        )
        self.assertFalse(os.lstat(registry_path).st_mode & stat.S_IWRITE)
        self._assert_no_transaction_debris()


if __name__ == "__main__":
    unittest.main()
