# pyright: reportPrivateUsage=false

import hashlib
import json
import os
import posixpath
import stat
import subprocess
import sys
import shutil
import tempfile
import threading
import unittest
from collections.abc import Collection, Iterable
from types import SimpleNamespace
from typing import BinaryIO, Callable
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
)
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostics import ConversionDiagnostic, DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath


class TestIncludedFilesConverterBasic(unittest.TestCase):
    """Test IncludedFilesConverter copies datafiles to the Godot project."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(datafiles_dir)

        self.test_file = os.path.join(datafiles_dir, "test.txt")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("test content")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_copies_file_to_godot(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "included_files", "test.txt")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

        with open(expected, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "test content")

        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        with open(registry_path, encoding="utf-8") as registry_file:
            registry_content = registry_file.read()
        self.assertIn('"logical_path": "test.txt"', registry_content)
        self.assertIn('"assigned_path": "test.txt"', registry_content)
        self.assertIn('"emitted": true', registry_content)
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "gm2godot",
                    "gml_asset_registry.gd",
                )
            )
        )

    def test_multiple_files(self):
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        for name in ("config.ini", "data.csv"):
            with open(os.path.join(datafiles_dir, name), "w", encoding="utf-8") as f:
                f.write(f"Content of {name}")

        converter = self._make_converter()
        converter.convert_all()

        for name in ("test.txt", "config.ini", "data.csv"):
            expected = os.path.join(self.godot_dir, "included_files", name)
            self.assertTrue(os.path.isfile(expected), f"Expected {expected}")

    def test_empty_included_files_conversion_prunes_stale_root_and_writes_empty_registry(self):
        converter = self._make_converter()
        converter.convert_all()
        os.unlink(self.test_file)

        converter.convert_all()

        self.assertEqual(
            os.listdir(os.path.join(self.godot_dir, "included_files")),
            [],
        )
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn("const INCLUDED_FILES = []", registry_content)

    def test_malformed_yyp_retains_disk_discovery_fallback(self):
        with open(
            os.path.join(self.gm_dir, "Malformed.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            project_file.write("{")

        self._make_converter().convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "test.txt",
                )
            )
        )

    def test_legacy_yyp_without_included_files_retains_disk_fallback(self):
        with open(
            os.path.join(self.gm_dir, "LegacyShape.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump({"resources": []}, project_file)

        self._make_converter().convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "test.txt",
                )
            )
        )

    def test_resource_outcome_counts_logical_included_files(self):
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        with open(os.path.join(datafiles_dir, "second.txt"), "w", encoding="utf-8") as f:
            f.write("second")
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result().resources

        self.assertEqual(counts.requested, 2)
        self.assertEqual(counts.executed, 2)
        self.assertEqual(counts.completed, 2)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)

    def test_repeated_conversion_restarts_resource_outcomes(self):
        converter = self._make_converter()

        converter.convert_all()
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_repeated_conversion_accounts_for_the_current_resource_set(self):
        converter = self._make_converter()
        converter.convert_all()
        with open(
            os.path.join(self.gm_dir, "datafiles", "second.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("second")

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, executed=2, completed=2),
        )

    def test_registry_publication_failure_restores_previous_output_pair(self):
        converter = self._make_converter()
        converter.convert_all()
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        previous_root_identity = os.lstat(root_path).st_ino
        with open(registry_path, "rb") as registry_file:
            previous_registry = registry_file.read()
        with open(self.test_file, "w", encoding="utf-8") as source_file:
            source_file.write("updated content")
        original_move = included_files_module._move_exact_included_file

        def publish_then_fail(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
            )
            if destination == registry_path:
                raise OSError("registry publication failed")

        with patch.object(
            included_files_module,
            "_move_exact_included_file",
            side_effect=publish_then_fail,
        ):
            with self.assertRaisesRegex(
                OSError,
                "registry publication failed",
            ):
                converter.convert_all()

        self.assertEqual(os.lstat(root_path).st_ino, previous_root_identity)
        with open(
            os.path.join(root_path, "test.txt"),
            encoding="utf-8",
        ) as output_file:
            self.assertEqual(output_file.read(), "test content")
        with open(registry_path, "rb") as registry_file:
            self.assertEqual(registry_file.read(), previous_registry)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )


class TestIncludedFilesManagedRootTransaction(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.running = threading.Event()
        self.running.set()

    def tearDown(self) -> None:
        shutil.rmtree(
            self.gm_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )
        shutil.rmtree(
            self.godot_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

    @staticmethod
    def _retry_windows_read_only_cleanup(
        function: Callable[..., object],
        path: str,
        error: BaseException,
    ) -> None:
        if not isinstance(error, PermissionError):
            raise error
        path_stat = os.lstat(path)
        path_mode = stat.S_IMODE(path_stat.st_mode)
        if not stat.S_ISREG(path_stat.st_mode) or path_mode & stat.S_IWRITE:
            raise error
        os.chmod(path, path_mode | stat.S_IWRITE)
        function(path)

    def _converter(self, *, max_workers: int = 2) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=self.running.is_set,
            max_workers=max_workers,
        )

    def _write(self, relative_path: str, content: str) -> None:
        output_path = os.path.join(
            self.datafiles_dir,
            *relative_path.split("/"),
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(content)

    def _make_native_windows_junction(
        self,
        junction_path: str,
        target_path: str,
    ) -> None:
        os.makedirs(target_path, exist_ok=True)
        result = subprocess.run(
            (
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                junction_path,
                target_path,
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )
        self.assertTrue(os.path.isjunction(junction_path))

    def _make_native_windows_junction_target(self, label: str) -> str:
        target_path = os.path.join(self.gm_dir, "junction-targets", label)
        os.makedirs(target_path)
        with open(
            os.path.join(target_path, "external-sentinel.txt"),
            "wb",
        ) as sentinel_file:
            sentinel_file.write(b"external junction sentinel\n")
        return target_path

    def _assert_native_windows_junction_sentinel(self, target_path: str) -> None:
        with open(
            os.path.join(target_path, "external-sentinel.txt"),
            "rb",
        ) as sentinel_file:
            self.assertEqual(
                sentinel_file.read(),
                b"external junction sentinel\n",
            )

    @staticmethod
    def _remove_native_windows_junction(path: str) -> None:
        if os.path.isjunction(path):
            os.rmdir(path)

    def _pair_snapshot(self) -> tuple[int, dict[str, bytes], int, bytes]:
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        files: dict[str, bytes] = {}
        for directory, _subdirectories, filenames in os.walk(root_path):
            for filename in filenames:
                file_path = os.path.join(directory, filename)
                relative_path = os.path.relpath(
                    file_path,
                    root_path,
                ).replace(os.sep, "/")
                with open(file_path, "rb") as output_file:
                    files[relative_path] = output_file.read()
        with open(registry_path, "rb") as registry_file:
            registry_content = registry_file.read()
        return (
            os.lstat(root_path).st_ino,
            files,
            os.lstat(registry_path).st_ino,
            registry_content,
        )

    def _assert_no_transaction_debris(self) -> None:
        project_debris = [
            name
            for name in os.listdir(self.godot_dir)
            if name.startswith(".gm2godot-included-files-")
            or name.startswith(".included_files.")
        ]
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        registry_debris = (
            [
                name
                for name in os.listdir(registry_directory)
                if name.startswith(".gml_included_file_registry.gd.")
                and name.endswith(".backup")
            ]
            if os.path.isdir(registry_directory)
            else []
        )
        self.assertEqual(project_debris, [])
        self.assertEqual(registry_debris, [])

    def test_unchanged_generation_preserves_public_identity_without_writes(
        self,
    ) -> None:
        self._write("nested/payload.txt", "stable payload")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
            "payload.txt",
        )
        previous_output_identity = os.lstat(output_path).st_ino

        with (
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("unchanged conversion staged output"),
            ) as create_stage,
            patch.object(included_files_module.os, "fsync") as fsync,
            patch.object(included_files_module.os, "replace") as replace,
        ):
            converter.convert_all()

        create_stage.assert_not_called()
        fsync.assert_not_called()
        replace.assert_not_called()
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(os.lstat(output_path).st_ino, previous_output_identity)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=1,
                executed=1,
                completed=1,
            ),
        )
        self._assert_no_transaction_debris()

    def test_64_mib_generation_has_bounded_initial_and_unchanged_reads(
        self,
    ) -> None:
        payload_size = 64 * 1024 * 1024
        source_path = os.path.join(self.datafiles_dir, "large.bin")
        with open(source_path, "wb") as source_file:
            source_file.truncate(payload_size)
        converter = self._converter(max_workers=1)
        original_payload_read = (
            included_files_module._read_included_payload_chunk
        )
        original_validation_read = (
            included_files_module._read_included_validation_chunk
        )
        read_bytes = 0

        def count_payload_read(source_file: BinaryIO) -> bytes:
            nonlocal read_bytes
            chunk = original_payload_read(source_file)
            read_bytes += len(chunk)
            return chunk

        def count_validation_read(source_file: BinaryIO) -> bytes:
            nonlocal read_bytes
            chunk = original_validation_read(source_file)
            read_bytes += len(chunk)
            return chunk

        with (
            patch.object(
                included_files_module,
                "_read_included_payload_chunk",
                side_effect=count_payload_read,
            ),
            patch.object(
                included_files_module,
                "_read_included_validation_chunk",
                side_effect=count_validation_read,
            ),
        ):
            converter.convert_all()
        self.assertEqual(read_bytes, 5 * payload_size)

        read_bytes = 0
        with (
            patch.object(
                included_files_module,
                "_read_included_payload_chunk",
                side_effect=count_payload_read,
            ),
            patch.object(
                included_files_module,
                "_read_included_validation_chunk",
                side_effect=count_validation_read,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("unchanged conversion staged output"),
            ),
        ):
            converter.convert_all()
        self.assertEqual(read_bytes, 4 * payload_size)
        self._assert_no_transaction_debris()

    def test_changed_payload_uses_the_normal_output_transaction(self) -> None:
        self._write("payload.txt", "BEFORE")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "AFTER!")
        original_create_stage = (
            included_files_module._create_included_output_stage
        )

        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            wraps=original_create_stage,
        ) as create_stage:
            converter.convert_all()

        create_stage.assert_called_once()
        current_pair = self._pair_snapshot()
        self.assertNotEqual(current_pair[0], previous_pair[0])
        self.assertEqual(current_pair[1], {"payload.txt": b"AFTER!"})
        self._assert_no_transaction_debris()

    def test_changed_path_uses_the_normal_output_transaction(
        self,
    ) -> None:
        self._write("old.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        os.rename(
            os.path.join(self.datafiles_dir, "old.txt"),
            os.path.join(self.datafiles_dir, "new.txt"),
        )
        original_create_stage = (
            included_files_module._create_included_output_stage
        )

        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            wraps=original_create_stage,
        ) as create_stage:
            converter.convert_all()

        create_stage.assert_called_once()
        self.assertEqual(self._pair_snapshot()[1], {"new.txt": b"stable"})
        self._assert_no_transaction_debris()

    def test_changed_registry_rendering_uses_the_normal_output_transaction(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        original_render = included_files_module.render_included_file_registry
        original_create_stage = (
            included_files_module._create_included_output_stage
        )

        def changed_render(
            assignments: Iterable[IncludedFilePathAssignment],
            emitted_logical_paths: Collection[str],
        ) -> str:
            return (
                original_render(assignments, emitted_logical_paths)
                + "# changed rendering\n"
            )

        with (
            patch.object(
                included_files_module,
                "render_included_file_registry",
                side_effect=changed_render,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                wraps=original_create_stage,
            ) as create_stage,
        ):
            converter.convert_all()

        create_stage.assert_called_once()
        with open(registry_path, "rb") as registry_file:
            self.assertTrue(registry_file.read().endswith(b"# changed rendering\n"))
        self._assert_no_transaction_debris()

    def test_hardlinked_public_payload_is_republished_normally(self) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        external_path = os.path.join(self.godot_dir, "external-hardlink.txt")
        with open(external_path, "w", encoding="utf-8") as external_file:
            external_file.write("stable")
        os.unlink(output_path)
        try:
            os.link(external_path, output_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable: {error}")
        self.assertEqual(os.lstat(output_path).st_nlink, 2)
        original_create_stage = (
            included_files_module._create_included_output_stage
        )

        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            wraps=original_create_stage,
        ) as create_stage:
            converter.convert_all()

        create_stage.assert_called_once()
        self.assertEqual(os.lstat(output_path).st_nlink, 1)
        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "stable")
        self._assert_no_transaction_debris()

    def test_collision_and_availability_changes_use_normal_transactions(
        self,
    ) -> None:
        self._write("Alpha Beta.txt", "first")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        self._write("alpha_beta.txt", "second")
        original_create_stage = (
            included_files_module._create_included_output_stage
        )

        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            wraps=original_create_stage,
        ) as collision_stage:
            converter.convert_all()
        collision_stage.assert_called_once()
        self.assertEqual(len(self._pair_snapshot()[1]), 2)

        os.unlink(os.path.join(self.datafiles_dir, "Alpha Beta.txt"))
        os.unlink(os.path.join(self.datafiles_dir, "alpha_beta.txt"))
        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            wraps=original_create_stage,
        ) as availability_stage:
            converter.convert_all()
        availability_stage.assert_called_once()
        self.assertEqual(self._pair_snapshot()[1], {})
        self._assert_no_transaction_debris()

    def test_source_mutation_between_noop_receipts_fails_closed(self) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        source_path = os.path.join(self.datafiles_dir, "payload.txt")
        source_stat = os.stat(source_path)

        def mutate_source() -> None:
            with open(source_path, "r+b", buffering=0) as source_file:
                source_file.write(b"MUTATED!")
                os.fsync(source_file.fileno())
            os.utime(
                source_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )

        with (
            patch.object(
                included_files_module,
                "_before_included_unchanged_source_revalidation",
                side_effect=mutate_source,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "sources changed"),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_source_directory_swap_with_same_inode_fails_closed(self) -> None:
        self._write("nested/payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        source_directory = os.path.join(self.datafiles_dir, "nested")
        moved_directory = os.path.join(self.datafiles_dir, "nested-original")

        def swap_source_directory() -> None:
            os.rename(source_directory, moved_directory)
            os.mkdir(source_directory)
            os.link(
                os.path.join(moved_directory, "payload.txt"),
                os.path.join(source_directory, "payload.txt"),
            )

        with (
            patch.object(
                included_files_module,
                "_before_included_unchanged_source_revalidation",
                side_effect=swap_source_directory,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("swapped no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "sources changed"),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            os.stat(
                os.path.join(source_directory, "payload.txt")
            ).st_ino,
            os.stat(
                os.path.join(moved_directory, "payload.txt")
            ).st_ino,
        )
        self._assert_no_transaction_debris()

    def test_public_root_symlink_swap_during_noop_is_preserved_and_rejected(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        root_path = os.path.join(self.godot_dir, "included_files")
        moved_root = os.path.join(self.godot_dir, "preserved-root")
        replacement_root = tempfile.mkdtemp()
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_identity = os.lstat(registry_path).st_ino
        with open(
            os.path.join(replacement_root, "payload.txt"),
            "wb",
        ) as replacement_file:
            replacement_file.write(b"replacement")

        def swap_public_root() -> None:
            os.rename(root_path, moved_root)
            try:
                os.symlink(replacement_root, root_path)
            except (NotImplementedError, OSError) as error:
                os.rename(moved_root, root_path)
                self.skipTest(f"Symbolic links are unavailable: {error}")

        try:
            with (
                patch.object(
                    included_files_module,
                    "_before_included_unchanged_public_revalidation",
                    side_effect=swap_public_root,
                ),
                patch.object(
                    included_files_module,
                    "_create_included_output_stage",
                    side_effect=AssertionError(
                        "swapped no-op candidate staged output"
                    ),
                ),
                self.assertRaisesRegex(OSError, "redirected|changed"),
            ):
                converter.convert_all()

            self.assertTrue(os.path.islink(root_path))
            with open(
                os.path.join(moved_root, "payload.txt"),
                "rb",
            ) as preserved_file:
                self.assertEqual(preserved_file.read(), b"stable")
            with open(
                os.path.join(root_path, "payload.txt"),
                "rb",
            ) as replacement_file:
                self.assertEqual(replacement_file.read(), b"replacement")
            self.assertEqual(os.lstat(registry_path).st_ino, registry_identity)
            self._assert_no_transaction_debris()
        finally:
            shutil.rmtree(replacement_root)

    def test_registry_mutation_during_noop_is_rejected_without_staging(
        self,
    ) -> None:
        self._write("payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        root_identity, root_files, registry_identity, registry_content = (
            self._pair_snapshot()
        )
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )

        def mutate_registry() -> None:
            with open(registry_path, "ab") as registry_file:
                registry_file.write(b"# concurrent mutation\n")
                registry_file.flush()
                os.fsync(registry_file.fileno())

        with (
            patch.object(
                included_files_module,
                "_before_included_unchanged_public_revalidation",
                side_effect=mutate_registry,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "registry changed"),
        ):
            converter.convert_all()

        current_pair = self._pair_snapshot()
        self.assertEqual(current_pair[0], root_identity)
        self.assertEqual(current_pair[1], root_files)
        self.assertEqual(current_pair[2], registry_identity)
        self.assertEqual(
            current_pair[3],
            registry_content + b"# concurrent mutation\n",
        )
        self._assert_no_transaction_debris()

    def test_late_same_size_public_mutation_is_rejected_without_staging(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("Windows ctime does not portably expose content changes")
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        output_stat = os.stat(output_path)
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_identity = os.lstat(registry_path).st_ino

        def mutate_public_payload() -> None:
            with open(output_path, "r+b", buffering=0) as output_file:
                output_file.write(b"MUTATED!")
                os.fsync(output_file.fileno())
            os.utime(
                output_path,
                ns=(output_stat.st_atime_ns, output_stat.st_mtime_ns),
            )

        with (
            patch.object(
                included_files_module,
                "_before_included_unchanged_final_revalidation",
                side_effect=mutate_public_payload,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("mutated no-op candidate staged output"),
            ),
            self.assertRaisesRegex(OSError, "tree metadata changed"),
        ):
            converter.convert_all()

        with open(output_path, "rb") as output_file:
            self.assertEqual(output_file.read(), b"MUTATED!")
        self.assertEqual(os.lstat(registry_path).st_ino, registry_identity)
        self._assert_no_transaction_debris()

    def test_unchanged_generation_uses_the_pinned_fallback_verifier(self) -> None:
        self._write("nested/payload.txt", "stable")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
                side_effect=AssertionError("fallback no-op staged output"),
            ),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_unchanged_contained_source_symlink_keeps_copy_semantics(self) -> None:
        target_path = os.path.join(self.datafiles_dir, "target.txt")
        with open(target_path, "w", encoding="utf-8") as source_file:
            source_file.write("contained target")
        alias_path = os.path.join(self.datafiles_dir, "alias.txt")
        try:
            os.symlink(target_path, alias_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        converter = self._converter(max_workers=2)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        with patch.object(
            included_files_module,
            "_create_included_output_stage",
            side_effect=AssertionError("symlink no-op candidate staged output"),
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            previous_pair[1],
            {
                "alias.txt": b"contained target",
                "target.txt": b"contained target",
            },
        )
        self._assert_no_transaction_debris()

    @staticmethod
    def _modeled_handle_stat(
        path_stat: os.stat_result,
        *,
        ctime_offset: int,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            st_dev=path_stat.st_dev,
            st_ino=path_stat.st_ino,
            st_mode=path_stat.st_mode ^ stat.S_IXUSR,
            st_size=path_stat.st_size,
            st_mtime_ns=path_stat.st_mtime_ns,
            st_ctime_ns=path_stat.st_ctime_ns + ctime_offset,
            st_nlink=path_stat.st_nlink,
        )

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
            included_files_module.os,
            "fstat",
            side_effect=(handle_stat, handle_stat),
        ):
            digest = included_files_module._digest_included_regular_file(
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
                included_files_module.os,
                "fstat",
                side_effect=(opened_stat, changed_stat),
            ),
            self.assertRaisesRegex(OSError, "changed while hashing"),
        ):
            included_files_module._digest_included_regular_file(
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
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_windows_included_file_read_api",
                return_value=kernel32,
            ),
            patch.dict(sys.modules, {"msvcrt": msvcrt}),
            patch.object(
                included_files_module.os,
                "fdopen",
                return_value=binary_stream,
            ) as fdopen,
        ):
            opened_stream = (
                included_files_module._open_included_file_validation_stream(
                    path,
                    deny_writes=True,
                    no_follow=True,
                )
            )

        self.assertIs(opened_stream, binary_stream)
        kernel32.CreateFileW.assert_called_once_with(
            os.path.abspath(path),
            included_files_module._WINDOWS_GENERIC_READ,
            included_files_module._WINDOWS_FILE_SHARE_READ,
            None,
            included_files_module._WINDOWS_OPEN_EXISTING,
            included_files_module._WINDOWS_FILE_ATTRIBUTE_NORMAL
            | included_files_module._WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
            | included_files_module._WINDOWS_FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
        msvcrt.open_osfhandle.assert_called_once_with(
            1234,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        fdopen.assert_called_once_with(5678, "rb")
        kernel32.CloseHandle.assert_not_called()

    def test_windows_validation_stream_closes_fd_when_wrapping_fails(
        self,
    ) -> None:
        kernel32 = MagicMock()
        kernel32.CreateFileW.return_value = 1234
        msvcrt = MagicMock()
        msvcrt.open_osfhandle.return_value = 5678

        with (
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_windows_included_file_read_api",
                return_value=kernel32,
            ),
            patch.dict(sys.modules, {"msvcrt": msvcrt}),
            patch.object(
                included_files_module.os,
                "fdopen",
                side_effect=MemoryError("injected wrapper failure"),
            ),
            patch.object(included_files_module.os, "close") as close,
            self.assertRaisesRegex(MemoryError, "injected wrapper failure"),
        ):
            included_files_module._open_included_file_validation_stream(
                os.path.join(self.godot_dir, "payload.bin"),
                deny_writes=True,
                no_follow=True,
            )

        close.assert_called_once_with(5678)
        kernel32.CloseHandle.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_noop_hashes_deny_concurrent_writes(self) -> None:
        self._write("payload.txt", "stable payload")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        source_path = os.path.join(self.datafiles_dir, "payload.txt")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        original_read = included_files_module._read_included_validation_chunk
        blocked_paths: set[str] = set()

        def observe_write_sharing(opened_file: BinaryIO) -> bytes:
            for path in (source_path, output_path):
                try:
                    with open(path, "r+b"):
                        pass
                except PermissionError:
                    blocked_paths.add(path)
            return original_read(opened_file)

        with patch.object(
            included_files_module,
            "_read_included_validation_chunk",
            side_effect=observe_write_sharing,
        ):
            converter.convert_all()

        self.assertEqual(blocked_paths, {source_path, output_path})

    def test_descriptor_digest_rechecks_the_open_handle(self) -> None:
        if not included_files_module._included_descriptor_paths_supported():
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
        parent_fd = included_files_module._open_pinned_included_directory(
            self.godot_dir
        )
        try:
            with patch.object(
                included_files_module.os,
                "fstat",
                side_effect=(opened_stat, opened_stat),
            ):
                digest = included_files_module._digest_included_regular_file_at(
                    parent_fd,
                    "staged.bin",
                    path_stat,
                    staged_path,
                )
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

            with (
                patch.object(
                    included_files_module.os,
                    "fstat",
                    side_effect=(opened_stat, changed_stat),
                ),
                self.assertRaisesRegex(OSError, "changed while hashing"),
            ):
                included_files_module._digest_included_regular_file_at(
                    parent_fd,
                    "staged.bin",
                    path_stat,
                    staged_path,
                )
        finally:
            os.close(parent_fd)

    def test_regular_file_in_place_of_managed_root_is_preserved(self) -> None:
        self._write("new.txt", "new")
        root_path = os.path.join(self.godot_dir, "included_files")
        with open(root_path, "wb") as root_file:
            root_file.write(b"unmanaged sentinel")
        converter = self._converter(max_workers=1)

        with self.assertRaisesRegex(OSError, "non-directory Included Files root"):
            converter.convert_all()

        with open(root_path, "rb") as root_file:
            self.assertEqual(root_file.read(), b"unmanaged sentinel")
        self.assertFalse(
            os.path.lexists(
                os.path.join(
                    self.godot_dir,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                )
            )
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_fifo_in_staged_root_preserves_previous_pair(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFOs are unavailable")
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_process = converter._process_file

        def inject_fifo(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            result = original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )
            os.mkfifo(os.path.join(os.path.dirname(godot_file_path), "rogue.fifo"))
            return result

        with patch.object(
            converter,
            "_process_file",
            side_effect=inject_fifo,
        ), self.assertRaisesRegex(OSError, "non-regular entry"):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_torn_source_mutation_during_copy_preserves_previous_pair(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        source_path = os.path.join(self.datafiles_dir, "new.bin")
        pre_mutation_payload = b"A" * (2 * 1024 * 1024)
        post_mutation_payload = b"B" * (2 * 1024 * 1024)
        with open(source_path, "wb") as source_file:
            source_file.write(pre_mutation_payload)
        original_stat = os.stat(source_path)
        original_read = included_files_module._read_included_payload_chunk
        original_fingerprint = included_files_module._included_source_fingerprint
        mutated = False
        streamed_chunks: list[bytes] = []

        def mutate_already_read_bytes(source_file: BinaryIO) -> bytes:
            nonlocal mutated
            chunk = original_read(source_file)
            if chunk:
                streamed_chunks.append(chunk)
            if not mutated and chunk:
                with open(source_path, "r+b", buffering=0) as mutator:
                    mutator.seek(0)
                    mutator.write(post_mutation_payload)
                    os.fsync(mutator.fileno())
                os.utime(
                    source_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
                mutated = True
            return chunk

        def windows_style_fingerprint(
            source_stat: os.stat_result,
        ) -> tuple[int, int, int, int, int, int]:
            fingerprint = original_fingerprint(source_stat)
            return (*fingerprint[:-1], original_stat.st_ctime_ns)

        with (
            patch.object(
                included_files_module,
                "_read_included_payload_chunk",
                side_effect=mutate_already_read_bytes,
            ),
            patch.object(
                included_files_module,
                "_included_source_fingerprint",
                side_effect=windows_style_fingerprint,
            ),
            self.assertRaisesRegex(OSError, "output-set staging failed"),
        ):
            converter.convert_all()

        self.assertTrue(mutated)
        streamed_payload = b"".join(streamed_chunks)
        self.assertEqual(
            streamed_payload,
            b"A" * (1024 * 1024) + b"B" * (1024 * 1024),
        )
        self.assertNotEqual(streamed_payload, pre_mutation_payload)
        self.assertNotEqual(streamed_payload, post_mutation_payload)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_same_size_staged_mutation_with_restored_mtime_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "GOOD")
        original_commit = included_files_module._commit_included_output_set
        mutated = False

        def mutate_then_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal mutated
            staged_file = os.path.join(
                transaction.staged_root_path,
                "new.txt",
            )
            staged_stat = os.stat(staged_file)
            with open(staged_file, "r+b", buffering=0) as output_file:
                output_file.write(b"EVIL")
                os.fsync(output_file.fileno())
            os.utime(
                staged_file,
                ns=(staged_stat.st_atime_ns, staged_stat.st_mtime_ns),
            )
            if os.stat(staged_file).st_mtime_ns != staged_stat.st_mtime_ns:
                self.skipTest("Filesystem cannot restore nanosecond mtime")
            mutated = True
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        with patch.object(
            included_files_module,
            "_commit_included_output_set",
            side_effect=mutate_then_commit,
        ), self.assertRaisesRegex(OSError, "tree changed"):
            converter.convert_all()

        self.assertTrue(mutated)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_first_registry_publication_failure_restores_absent_pair(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        final_root_path = os.path.join(self.godot_dir, "included_files")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(final_registry_path)
        original_move = included_files_module._move_exact_included_file
        publication_failed = False

        def publish_then_fail(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            nonlocal publication_failed
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
            )
            if destination == final_registry_path and not publication_failed:
                publication_failed = True
                raise OSError("injected first registry publication failure")

        with patch.object(
            included_files_module,
            "_move_exact_included_file",
            side_effect=publish_then_fail,
        ), self.assertRaisesRegex(
            OSError,
            "injected first registry publication failure",
        ):
            converter.convert_all()

        self.assertTrue(publication_failed)
        self.assertFalse(os.path.lexists(final_root_path))
        self.assertFalse(os.path.lexists(final_registry_path))
        self.assertFalse(os.path.lexists(registry_directory))
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

    def test_preprepare_rollback_refuses_appeared_registry_before_read(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        original_verify_tree = (
            included_files_module._verify_included_tree_snapshot
        )
        original_file_state_at = (
            included_files_module._included_regular_file_state_at
        )
        injected = False
        appeared_registry_read_attempts: list[str] = []

        def inject_registry_before_prepare(
            root_path: str,
            expected: included_files_module._IncludedTreeSnapshot,
            *,
            expected_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            nonlocal injected
            original_verify_tree(
                root_path,
                expected,
                expected_parent_identity=expected_parent_identity,
            )
            if (
                not injected
                and os.path.basename(os.path.dirname(root_path)).startswith(
                    ".gm2godot-included-files-"
                )
            ):
                os.makedirs(os.path.dirname(final_registry_path))
                with open(final_registry_path, "wb") as registry_file:
                    registry_file.write(b"unknown appeared registry")
                injected = True
                raise OSError("injected failure before registry prepare")

        def record_registry_state_attempt(
            parent_fd: int,
            name: str,
            display_path: str,
            *,
            allowed_identities: frozenset[tuple[int, int]] | None = None,
        ) -> tuple[tuple[int, int], int, bytes] | None:
            if display_path == final_registry_path:
                appeared_registry_read_attempts.append(display_path)
            return original_file_state_at(
                parent_fd,
                name,
                display_path,
                allowed_identities=allowed_identities,
            )

        with (
            patch.object(
                included_files_module,
                "_verify_included_tree_snapshot",
                side_effect=inject_registry_before_prepare,
            ),
            patch.object(
                included_files_module,
                "_included_regular_file_state_at",
                side_effect=record_registry_state_attempt,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected failure before registry prepare",
            ),
        ):
            converter.convert_all()

        self.assertTrue(injected)
        self.assertEqual(appeared_registry_read_attempts, [])
        with open(final_registry_path, "rb") as registry_file:
            self.assertEqual(registry_file.read(), b"unknown appeared registry")
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self.assertFalse(
            any(
                name.startswith(".gm2godot-included-files-")
                for name in os.listdir(self.godot_dir)
            )
        )

    def test_unknown_registry_backup_destination_is_not_overwritten(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_rename = (
            included_files_module._rename_included_transaction_entry_at
        )
        sentinel_name: str | None = None

        def inject_unknown_destination(
            source_parent_fd: int,
            source_name: str,
            destination_parent_fd: int,
            destination_name: str,
        ) -> None:
            nonlocal sentinel_name
            if (
                sentinel_name is None
                and destination_name.startswith(
                    ".gml_included_file_registry.gd."
                )
                and destination_name.endswith(".backup")
            ):
                sentinel_fd = os.open(
                    destination_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=destination_parent_fd,
                )
                try:
                    os.write(sentinel_fd, b"unknown sentinel")
                    os.fsync(sentinel_fd)
                finally:
                    os.close(sentinel_fd)
                sentinel_name = destination_name
            original_rename(
                source_parent_fd,
                source_name,
                destination_parent_fd,
                destination_name,
            )

        def inject_unknown_destination_fallback(
            _source: str,
            destination: str,
        ) -> None:
            nonlocal sentinel_name
            destination_name = os.path.basename(destination)
            if (
                sentinel_name is None
                and destination_name.startswith(
                    ".gml_included_file_registry.gd."
                )
                and destination_name.endswith(".backup")
            ):
                with open(destination, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown sentinel")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
                sentinel_name = destination_name

        rename_patcher = (
            patch.object(
                included_files_module,
                "_rename_included_transaction_entry_at",
                side_effect=inject_unknown_destination,
            )
            if included_files_module._included_descriptor_paths_supported()
            else patch.object(
                included_files_module,
                "_before_included_transaction_rename_fallback",
                side_effect=inject_unknown_destination_fallback,
            )
        )
        with rename_patcher, self.assertRaises(OSError):
            converter.convert_all()

        self.assertIsNotNone(sentinel_name)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        if sentinel_name is not None:
            sentinel_path = os.path.join(
                self.godot_dir,
                "gm2godot",
                sentinel_name,
            )
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(sentinel_file.read(), b"unknown sentinel")
        project_debris = [
            name
            for name in os.listdir(self.godot_dir)
            if name.startswith(".gm2godot-included-files-")
            or name.startswith(".included_files.")
        ]
        self.assertEqual(project_debris, [])
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )

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

        def swap_cleanup_root(
            parent_fd: int,
            name: str,
        ) -> None:
            nonlocal swapped_backup_path
            if (
                swapped_backup_path is None
                and name.startswith(".included_files.")
                and name.endswith(".backup")
            ):
                os.rename(
                    name,
                    os.path.basename(parked_backup),
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                os.rename(
                    os.path.basename(victim_path),
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                swapped_backup_path = os.path.join(self.godot_dir, name)

        def swap_cleanup_root_fallback(path: str) -> None:
            nonlocal swapped_backup_path
            name = os.path.basename(path)
            if (
                swapped_backup_path is None
                and name.startswith(".included_files.")
                and name.endswith(".backup")
            ):
                os.rename(path, parked_backup)
                os.rename(victim_path, path)
                swapped_backup_path = path

        cleanup_patcher = (
            patch.object(
                included_files_module,
                "_before_included_cleanup_quarantine",
                side_effect=swap_cleanup_root,
            )
            if included_files_module._included_descriptor_paths_supported()
            else patch.object(
                included_files_module,
                "_before_included_cleanup_quarantine_fallback",
                side_effect=swap_cleanup_root_fallback,
            )
        )
        with cleanup_patcher:
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
        self.assertFalse(
            any(
                name.startswith(".gm2godot-included-files-")
                for name in os.listdir(self.godot_dir)
            )
        )

    def test_transaction_source_swap_restores_unknown_replacement_without_loss(
        self,
    ) -> None:
        if not (
            included_files_module._included_descriptor_paths_supported()
            and included_files_module._included_native_noreplace_available()
        ):
            self.skipTest("Descriptor-pinned no-replace rename is unavailable")
        transaction_directory = os.path.join(self.godot_dir, "source-swap")
        os.mkdir(transaction_directory)
        source_path = os.path.join(transaction_directory, "source.txt")
        replacement_path = os.path.join(
            transaction_directory,
            "replacement.txt",
        )
        parked_path = os.path.join(transaction_directory, "parked-owned.txt")
        destination_path = os.path.join(transaction_directory, "published.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("owned source")
        with open(replacement_path, "w", encoding="utf-8") as replacement_file:
            replacement_file.write("unknown replacement")
        source_stat = os.lstat(source_path)
        parent_stat = os.lstat(transaction_directory)
        swapped = False

        def swap_source(parent_fd: int, source_name: str) -> None:
            nonlocal swapped
            if swapped or source_name != "source.txt":
                return
            os.rename(
                source_name,
                os.path.basename(parked_path),
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.rename(
                os.path.basename(replacement_path),
                source_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            swapped = True

        with patch.object(
            included_files_module,
            "_before_included_transaction_rename",
            side_effect=swap_source,
        ), self.assertRaisesRegex(OSError, "restored without loss"):
            included_files_module._move_exact_included_file(
                source_path,
                destination_path,
                (source_stat.st_dev, source_stat.st_ino),
                source_parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
                destination_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
            )

        self.assertTrue(swapped)
        with open(source_path, encoding="utf-8") as source_file:
            self.assertEqual(source_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as parked_file:
            self.assertEqual(parked_file.read(), "owned source")
        self.assertFalse(os.path.lexists(destination_path))

    def test_cleanup_file_swap_restores_unknown_replacement_without_loss(
        self,
    ) -> None:
        if not (
            included_files_module._included_descriptor_paths_supported()
            and included_files_module._included_native_noreplace_available()
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
            included_files_module,
            "_before_included_cleanup_quarantine",
            side_effect=swap_cleanup_file,
        ), self.assertRaisesRegex(OSError, "restored without loss"):
            included_files_module._remove_owned_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                expected_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
            )

        self.assertTrue(swapped)
        with open(owned_path, encoding="utf-8") as owned_file:
            self.assertEqual(owned_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as parked_file:
            self.assertEqual(parked_file.read(), "owned cleanup file")

    def test_cleanup_tree_final_rmdir_retains_unknown_replacement(
        self,
    ) -> None:
        if not (
            included_files_module._included_descriptor_paths_supported()
            and included_files_module._included_native_noreplace_available()
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
            included_files_module,
            "_before_included_cleanup_remove",
            side_effect=swap_quarantine_before_rmdir,
        ), self.assertRaisesRegex(OSError, "recoverable directory retained"):
            included_files_module._remove_owned_included_tree(
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
        if not included_files_module._included_descriptor_paths_supported():
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
            included_files_module,
            "_before_included_registry_file_read",
            side_effect=swap_registry_directory,
        ), self.assertRaisesRegex(OSError, "directory changed"):
            included_files_module._capture_included_registry(self.godot_dir)

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
        if not included_files_module._included_descriptor_paths_supported():
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
        expected_snapshot = included_files_module._capture_included_registry(
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
            included_files_module._included_regular_file_state_at
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
            included_files_module,
            "_included_regular_file_state_at",
            side_effect=record_registry_read,
        ), self.assertRaisesRegex(OSError, "directory changed"):
            included_files_module._verify_included_registry_snapshot(
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
            included_files_module,
            "_included_descriptor_paths_supported",
            return_value=False,
        ):
            expected_snapshot = included_files_module._capture_included_registry(
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_before_included_fallback_regular_file_open",
                side_effect=swap_project_before_open,
            ),
            patch.object(
                included_files_module.os,
                "fdopen",
                side_effect=record_fdopen,
            ),
            self.assertRaises(OSError),
        ):
            included_files_module._verify_included_registry_snapshot(
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

    def test_created_registry_directory_swap_is_not_adopted(self) -> None:
        if not included_files_module._included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned registry creation is unavailable")
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        replacement_directory = os.path.join(
            self.godot_dir,
            "replacement-registry",
        )
        parked_directory = os.path.join(
            self.godot_dir,
            "parked-created-registry",
        )
        os.mkdir(replacement_directory)
        sentinel_path = os.path.join(replacement_directory, "sentinel.txt")
        with open(sentinel_path, "w", encoding="utf-8") as sentinel_file:
            sentinel_file.write("unknown registry directory")
        project_stat = os.lstat(self.godot_dir)
        empty_snapshot = included_files_module._IncludedRegistrySnapshot(
            directory_identity=None,
            file_identity=None,
            file_mode=None,
            content=None,
        )
        swapped = False

        def swap_created_registry(project_fd: int, name: str) -> None:
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
            included_files_module,
            "_before_included_registry_directory_binding_check",
            side_effect=swap_created_registry,
        ), self.assertRaisesRegex(OSError, "changed after creation"):
            included_files_module._prepare_included_registry_directory(
                self.godot_dir,
                empty_snapshot,
                (project_stat.st_dev, project_stat.st_ino),
            )

        self.assertTrue(swapped)
        with open(
            os.path.join(registry_directory, "sentinel.txt"),
            encoding="utf-8",
        ) as sentinel_file:
            self.assertEqual(sentinel_file.read(), "unknown registry directory")
        self.assertEqual(os.listdir(parked_directory), [])

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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_before_included_fallback_chmod_open",
                side_effect=swap_before_open,
            ),
            self.assertRaisesRegex(OSError, "file changed"),
        ):
            included_files_module._chmod_exact_included_file(
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                included_files_module,
                "_before_included_cleanup_quarantine_fallback",
                side_effect=AssertionError("matching mode must not quarantine"),
            ),
        ):
            included_files_module._chmod_exact_included_file(
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                included_files_module,
                "_before_included_cleanup_quarantine_fallback",
                side_effect=quarantined_paths.append,
            ),
        ):
            included_files_module._chmod_exact_included_file(
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

    def test_windows_fallback_cleanup_removes_readonly_owned_file(self) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-readonly-cleanup",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned cleanup target")
        os.chmod(owned_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        supports_without_chmod = set(os.supports_fd)
        supports_without_chmod.discard(os.chmod)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "supports_fd",
                supports_without_chmod,
            ),
        ):
            included_files_module._remove_owned_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                expected_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
            )

        self.assertFalse(os.path.lexists(owned_path))
        self.assertEqual(os.listdir(cleanup_directory), [])

    def test_windows_fallback_cleanup_restores_readonly_after_unlink_failure(
        self,
    ) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-readonly-cleanup-failure",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        with open(owned_path, "w", encoding="utf-8") as owned_file:
            owned_file.write("owned cleanup target")
        os.chmod(owned_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        supports_without_chmod = set(os.supports_fd)
        supports_without_chmod.discard(os.chmod)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "supports_fd",
                supports_without_chmod,
            ),
            patch.object(
                included_files_module.os,
                "unlink",
                side_effect=PermissionError("injected Windows sharing failure"),
            ),
            self.assertRaisesRegex(
                OSError,
                "recoverable quarantine retained",
            ),
        ):
            included_files_module._remove_owned_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                expected_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
            )

        quarantined_names = os.listdir(cleanup_directory)
        self.assertEqual(len(quarantined_names), 1)
        quarantined_path = os.path.join(
            cleanup_directory,
            quarantined_names[0],
        )
        quarantined_stat = os.lstat(quarantined_path)
        self.assertEqual(
            (quarantined_stat.st_dev, quarantined_stat.st_ino),
            (owned_stat.st_dev, owned_stat.st_ino),
        )
        self.assertFalse(quarantined_stat.st_mode & stat.S_IWRITE)
        with open(quarantined_path, encoding="utf-8") as quarantined_file:
            self.assertEqual(quarantined_file.read(), "owned cleanup target")
        os.chmod(quarantined_path, 0o600)
        os.unlink(quarantined_path)

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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            self.assertRaisesRegex(
                OSError,
                "multiple hard links.*recoverable quarantine retained",
            ),
        ):
            included_files_module._remove_owned_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                expected_parent_identity=(
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                ),
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

    def test_moved_and_symlinked_stage_container_is_rejected(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        moved_stage = os.path.join(self.gm_dir, "moved-stage")
        original_commit = included_files_module._commit_included_output_set
        stage_link: str | None = None

        def redirect_stage_then_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal stage_link
            os.rename(transaction.stage_container_path, moved_stage)
            try:
                os.symlink(moved_stage, transaction.stage_container_path)
            except (NotImplementedError, OSError) as error:
                os.rename(moved_stage, transaction.stage_container_path)
                self.skipTest(f"Symbolic links are unavailable: {error}")
            stage_link = transaction.stage_container_path
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        try:
            with patch.object(
                included_files_module,
                "_commit_included_output_set",
                side_effect=redirect_stage_then_commit,
            ), self.assertRaisesRegex(OSError, "redirected or non-directory"):
                converter.convert_all()

            self.assertIsNotNone(stage_link)
            self.assertEqual(self._pair_snapshot(), previous_pair)
            self.assertTrue(os.path.islink(stage_link or ""))
            self.assertTrue(os.path.isdir(moved_stage))
            self.assertEqual(
                converter.conversion_step_result(
                    finalize_unfinished_as=None,
                ).resources,
                ConversionCounts(requested=1, executed=1, failed=1),
            )
        finally:
            if stage_link is not None and os.path.islink(stage_link):
                os.unlink(stage_link)

    @unittest.skipUnless(
        included_files_module._included_descriptor_paths_supported(),
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
        original_open = included_files_module._open_included_tree_directory_at
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
                included_files_module,
                "_open_included_tree_directory_at",
                side_effect=swap_before_open,
            ), self.assertRaises(OSError):
                included_files_module._capture_included_tree(scan_root)

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
        original_digest = included_files_module._digest_included_regular_file
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
                    included_files_module,
                    "_included_descriptor_paths_supported",
                    return_value=False,
                ),
                patch.object(
                    included_files_module,
                    "_after_included_fallback_tree_directory_scan",
                    side_effect=swap_after_scan,
                ),
                patch.object(
                    included_files_module,
                    "_digest_included_regular_file",
                    wraps=original_digest,
                ) as digest_file,
                self.assertRaises(OSError),
            ):
                included_files_module._capture_included_tree(scan_root)

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

    def test_native_noreplace_preserves_file_and_directory_destinations(
        self,
    ) -> None:
        if not (
            included_files_module._included_descriptor_paths_supported()
            and included_files_module._included_native_noreplace_available()
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
        directory_fd = included_files_module._open_pinned_included_directory(
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
                    included_files_module._rename_included_transaction_entry_at(
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
        if not included_files_module._included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned paths are unavailable")
        transaction_directory = os.path.join(
            self.godot_dir,
            "native-unavailable",
        )
        os.mkdir(transaction_directory)
        source_path = os.path.join(transaction_directory, "source.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("source")
        directory_fd = included_files_module._open_pinned_included_directory(
            transaction_directory
        )
        try:
            with patch.object(
                included_files_module,
                "_included_native_noreplace_available",
                return_value=False,
            ), self.assertRaisesRegex(OSError, "unavailable"):
                included_files_module._rename_included_transaction_entry_at(
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

    def test_repeated_conversion_supports_file_directory_file_shapes(self) -> None:
        converter = self._converter()
        self._write("foo_bar", "blocking file")
        converter.convert_all()
        root_path = os.path.join(self.godot_dir, "included_files")
        self.assertTrue(os.path.isfile(os.path.join(root_path, "foo_bar")))

        self._write("Foo Bar/item.txt", "nested file")
        converter.convert_all()
        self.assertTrue(
            os.path.isfile(os.path.join(root_path, "foo_bar", "item.txt"))
        )
        with open(
            os.path.join(root_path, "foo_bar_2"),
            encoding="utf-8",
        ) as output_file:
            self.assertEqual(output_file.read(), "blocking file")

        shutil.rmtree(os.path.join(self.datafiles_dir, "Foo Bar"))
        converter.convert_all()
        self.assertTrue(os.path.isfile(os.path.join(root_path, "foo_bar")))
        self.assertFalse(os.path.lexists(os.path.join(root_path, "foo_bar_2")))
        self.assertEqual(os.listdir(root_path), ["foo_bar"])
        self._assert_no_transaction_debris()

    def test_worker_failure_preserves_previous_pair_and_fails_all_files(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("a_ok.txt", "ok")
        self._write("z_fail.txt", "fail")
        original_publish = included_files_module._publish_confined_included_output

        def fail_selected_output(
            project_path: str,
            output_path: str,
            source_file: BinaryIO,
            source_stat: os.stat_result,
        ) -> included_files_module._IncludedCopyReceipt:
            if output_path.endswith("z_fail.txt"):
                raise OSError("injected worker failure")
            return original_publish(
                project_path,
                output_path,
                source_file,
                source_stat,
            )

        with patch.object(
            included_files_module,
            "_publish_confined_included_output",
            side_effect=fail_selected_output,
        ):
            with self.assertRaisesRegex(OSError, "output-set staging failed"):
                converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, executed=2, failed=2),
        )
        self._assert_no_transaction_debris()

    def test_cancellation_after_workers_stage_preserves_previous_pair(self) -> None:
        converter = self._converter(max_workers=2)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("a.txt", "a")
        self._write("b.txt", "b")
        original_process = converter._process_file
        staged_barrier = threading.Barrier(2)

        def stage_then_cancel(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            result = original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )
            staged_barrier.wait(timeout=5)
            self.running.clear()
            return result

        with patch.object(
            converter,
            "_process_file",
            side_effect=stage_then_cancel,
        ):
            converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=2, executed=2, skipped=2),
        )
        self.assertTrue(converter.conversion_step_result().cancelled)
        self._assert_no_transaction_debris()

    def test_public_pair_stays_old_until_every_worker_finishes(self) -> None:
        converter = self._converter(max_workers=2)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("a.txt", "a")
        self._write("b.txt", "b")
        original_process = converter._process_file
        blocked = threading.Event()
        release = threading.Event()
        thread_errors: list[BaseException] = []

        def block_one_worker(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            result = original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )
            if relative_path == "b.txt":
                blocked.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("worker release timed out")
            return result

        def run_conversion() -> None:
            try:
                converter.convert_all()
            except BaseException as error:
                thread_errors.append(error)

        with patch.object(
            converter,
            "_process_file",
            side_effect=block_one_worker,
        ):
            conversion_thread = threading.Thread(target=run_conversion)
            conversion_thread.start()
            try:
                self.assertTrue(blocked.wait(timeout=5))
                self.assertEqual(self._pair_snapshot(), previous_pair)
            finally:
                release.set()
                conversion_thread.join(timeout=5)

        self.assertFalse(conversion_thread.is_alive())
        self.assertEqual(thread_errors, [])
        root_path = os.path.join(self.godot_dir, "included_files")
        self.assertEqual(sorted(os.listdir(root_path)), ["a.txt", "b.txt"])
        self._assert_no_transaction_debris()

    def test_second_root_rename_failure_restores_previous_pair(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new")
        original_move = included_files_module._move_exact_included_directory
        final_root_path = os.path.join(self.godot_dir, "included_files")

        def fail_staged_root_publish(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            if (
                destination == final_root_path
                and ".gm2godot-included-files-" in source
            ):
                raise OSError("injected root publication failure")
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
            )

        with patch.object(
            included_files_module,
            "_move_exact_included_directory",
            side_effect=fail_staged_root_publish,
        ):
            with self.assertRaisesRegex(
                OSError,
                "injected root publication failure",
            ):
                converter.convert_all()

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )
        self._assert_no_transaction_debris()

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
        new_source = os.path.join(self.datafiles_dir, "new", "nested.txt")
        os.chmod(new_source, stat.S_IREAD)

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new/nested.txt": b"new payload"},
        )
        self.assertFalse(os.lstat(registry_path).st_mode & stat.S_IWRITE)
        self.assertFalse(
            os.lstat(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "new",
                    "nested.txt",
                )
            ).st_mode
            & stat.S_IWRITE
        )
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_commit_failure_rolls_back_cleanly(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        public_directory = os.path.join(public_root, "old")
        public_file = os.path.join(public_directory, "nested.txt")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        for path in (
            public_file,
            final_registry_path,
            public_directory,
            public_root,
        ):
            os.chmod(path, stat.S_IREAD)
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")
        os.chmod(
            os.path.join(self.datafiles_dir, "new", "nested.txt"),
            stat.S_IREAD,
        )
        original_move = included_files_module._move_exact_included_file
        publication_failed = False

        def publish_registry_then_fail(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            nonlocal publication_failed
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
            )
            if destination == final_registry_path and not publication_failed:
                publication_failed = True
                raise OSError("injected native Windows commit failure")

        with (
            patch.object(
                included_files_module,
                "_move_exact_included_file",
                side_effect=publish_registry_then_fail,
            ),
            self.assertRaisesRegex(
                OSError,
                "injected native Windows commit failure",
            ),
        ):
            converter.convert_all()

        self.assertTrue(publication_failed)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_cancellation_rolls_back_cleanly(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        public_directory = os.path.join(public_root, "old")
        public_file = os.path.join(public_directory, "nested.txt")
        final_registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        for path in (
            public_file,
            final_registry_path,
            public_directory,
            public_root,
        ):
            os.chmod(path, stat.S_IREAD)
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")
        os.chmod(
            os.path.join(self.datafiles_dir, "new", "nested.txt"),
            stat.S_IREAD,
        )
        original_move = included_files_module._move_exact_included_file
        cancellation_injected = False

        def publish_registry_then_cancel(
            source: str,
            destination: str,
            expected_identity: tuple[int, int],
            *,
            source_parent_identity: tuple[int, int] | None = None,
            destination_parent_identity: tuple[int, int] | None = None,
        ) -> None:
            nonlocal cancellation_injected
            original_move(
                source,
                destination,
                expected_identity,
                source_parent_identity=source_parent_identity,
                destination_parent_identity=destination_parent_identity,
            )
            if destination == final_registry_path and not cancellation_injected:
                cancellation_injected = True
                self.running.clear()

        with patch.object(
            included_files_module,
            "_move_exact_included_file",
            side_effect=publish_registry_then_cancel,
        ):
            converter.convert_all()

        self.assertTrue(cancellation_injected)
        self.assertTrue(converter.conversion_step_result().cancelled)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_managed_root_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        root_path = os.path.join(self.godot_dir, "included_files")
        parked_root = os.path.join(self.godot_dir, ".native-parked-root")
        target_path = self._make_native_windows_junction_target(
            "managed-root"
        )
        os.rename(root_path, parked_root)
        try:
            self._make_native_windows_junction(root_path, target_path)
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(root_path))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(root_path)
            if os.path.isdir(parked_root):
                os.rename(parked_root, root_path)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_nested_tree_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("nested/payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        nested_path = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        parked_nested = os.path.join(self.godot_dir, ".native-parked-nested")
        target_path = self._make_native_windows_junction_target("nested-tree")
        os.rename(nested_path, parked_nested)
        try:
            self._make_native_windows_junction(nested_path, target_path)
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(nested_path))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(nested_path)
            if os.path.isdir(parked_nested):
                os.rename(parked_nested, nested_path)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_registry_directory_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("payload.txt", "stable payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        parked_registry = os.path.join(
            self.godot_dir,
            ".native-parked-registry",
        )
        target_path = self._make_native_windows_junction_target(
            "registry-directory"
        )
        os.rename(registry_directory, parked_registry)
        try:
            self._make_native_windows_junction(
                registry_directory,
                target_path,
            )
            with self.assertRaisesRegex(OSError, "redirected"):
                converter.convert_all()
            self.assertTrue(os.path.isjunction(registry_directory))
            self._assert_native_windows_junction_sentinel(target_path)
        finally:
            self._remove_native_windows_junction(registry_directory)
            if os.path.isdir(parked_registry):
                os.rename(parked_registry, registry_directory)

        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_stage_container_junction_is_rejected(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new payload")
        original_commit = included_files_module._commit_included_output_set
        parked_stage = os.path.join(self.gm_dir, "native-parked-stage")
        target_path = self._make_native_windows_junction_target(
            "stage-container"
        )
        stage_junction: str | None = None

        def replace_stage_with_junction(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal stage_junction
            os.rename(transaction.stage_container_path, parked_stage)
            self._make_native_windows_junction(
                transaction.stage_container_path,
                target_path,
            )
            stage_junction = transaction.stage_container_path
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        try:
            with (
                patch.object(
                    included_files_module,
                    "_commit_included_output_set",
                    side_effect=replace_stage_with_junction,
                ),
                self.assertRaisesRegex(OSError, "redirected"),
            ):
                converter.convert_all()
            self.assertIsNotNone(stage_junction)
            self.assertTrue(os.path.isjunction(stage_junction or ""))
            self._assert_native_windows_junction_sentinel(target_path)
            self.assertEqual(self._pair_snapshot(), previous_pair)
        finally:
            if stage_junction is not None:
                self._remove_native_windows_junction(stage_junction)
            if os.path.isdir(parked_stage):
                shutil.rmtree(
                    parked_stage,
                    onexc=self._retry_windows_read_only_cleanup,
                )

        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_backup_destination_junction_is_preserved(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old payload")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new payload")
        final_root_path = os.path.join(self.godot_dir, "included_files")
        target_path = self._make_native_windows_junction_target(
            "backup-destination"
        )
        backup_junction: str | None = None

        def inject_backup_junction(source: str, destination: str) -> None:
            nonlocal backup_junction
            if (
                backup_junction is None
                and source == final_root_path
                and os.path.basename(destination).startswith(
                    ".included_files."
                )
                and destination.endswith(".backup")
            ):
                self._make_native_windows_junction(destination, target_path)
                backup_junction = destination

        try:
            with (
                patch.object(
                    included_files_module,
                    "_before_included_transaction_rename_fallback",
                    side_effect=inject_backup_junction,
                ),
                self.assertRaises(OSError),
            ):
                converter.convert_all()
            self.assertIsNotNone(backup_junction)
            self.assertTrue(os.path.isjunction(backup_junction or ""))
            self._assert_native_windows_junction_sentinel(target_path)
            self.assertEqual(self._pair_snapshot(), previous_pair)
        finally:
            if backup_junction is not None:
                self._remove_native_windows_junction(backup_junction)

        self._assert_no_transaction_debris()


class TestIncludedFilesManifestAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yyp(self, files: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "IncludedPaths.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "IncludedFiles": [
                        {
                            "name": name,
                            "filePath": posixpath.dirname(path),
                        }
                        for name, path in files
                    ]
                },
                project_file,
            )

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
            max_workers=1,
        )

    def test_missing_only_declared_file_makes_conversion_partial(self) -> None:
        self._write_yyp(
            [("missing.txt", "datafiles/config/missing.txt")]
        )
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=lambda message: self.logs.append(str(message)),
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
        )
        included_files_enabled = MagicMock()
        included_files_enabled.get.return_value = True

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"included_files": included_files_enabled},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, skipped=1),
        )
        unavailable = [
            diagnostic
            for diagnostic in converter.diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].resource, "missing.txt")
        self.assertEqual(unavailable[0].source_path, "IncludedPaths.yyp")
        self.assertEqual(
            unavailable[0].manifest_entry,
            "IncludedFiles[0].filePath",
        )
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn(
            '"logical_path": "config/missing.txt"',
            registry_content,
        )
        self.assertIn('"emitted": false', registry_content)

    def test_safe_missing_and_disk_only_file_have_strict_counts(self) -> None:
        safe_source = os.path.join(self.datafiles_dir, "config", "safe.txt")
        os.makedirs(os.path.dirname(safe_source))
        with open(safe_source, "w", encoding="utf-8") as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.datafiles_dir, "orphan.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("orphan")
        self._write_yyp(
            [
                ("safe.txt", "datafiles/config/safe.txt"),
                ("missing.txt", "datafiles/config/missing.txt"),
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=3,
                executed=2,
                completed=2,
                skipped=1,
            ),
        )
        safe_output = os.path.join(
            self.godot_dir,
            "included_files",
            "config",
            "safe.txt",
        )
        with open(safe_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "safe")
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "config",
                    "missing.txt",
                )
            )
        )
        disk_only_output = os.path.join(
            self.godot_dir,
            "included_files",
            "orphan.txt",
        )
        with open(disk_only_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "orphan")
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code
            == "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].resource, "missing.txt")
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn(
            '"logical_path": "config/missing.txt"',
            registry_content,
        )
        self.assertIn('"logical_path": "config/safe.txt"', registry_content)
        self.assertEqual(registry_content.count('"emitted": false'), 1)
        self.assertEqual(registry_content.count('"emitted": true'), 2)

    def test_duplicate_exact_manifest_file_is_accounted_once(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "once.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("once")
        declaration = ("once.txt", "datafiles/once.txt")
        self._write_yyp([declaration, declaration])
        converter = self._make_converter()

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_manifest_declared_yy_payload_is_copied(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "payload.yy")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("included payload")
        self._write_yyp([("payload.yy", "datafiles/payload.yy")])

        self._make_converter().convert_all()

        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.yy",
        )
        with open(output_path, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "included payload")

    def test_rejected_declared_file_is_requested_and_skipped(self) -> None:
        self._write_yyp(
            [
                (
                    "rejected.txt",
                    "datafiles/../../outside/rejected.txt",
                )
            ]
        )
        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)

        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=1, skipped=1),
        )
        diagnostic_codes = {
            diagnostic.code for diagnostic in diagnostics.diagnostics()
        }
        self.assertIn("GM2GD-SOURCE-PATH-REJECTED", diagnostic_codes)
        self.assertIn(
            "GM2GD-INCLUDED-FILE-SOURCE-UNAVAILABLE",
            diagnostic_codes,
        )


class TestIncludedFilesConverterNestedDirs(unittest.TestCase):
    """Test that nested Included Files use GameMaker's packaged names."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create nested structure like the Asteroids++ project
        langs_dir = os.path.join(self.gm_dir, "datafiles", "Languages")
        modding_dir = os.path.join(self.gm_dir, "datafiles", "Modding", "Ranking System")
        os.makedirs(langs_dir)
        os.makedirs(modding_dir)

        with open(os.path.join(langs_dir, "english.lang"), "w", encoding="utf-8") as f:
            f.write("lang data")
        with open(os.path.join(modding_dir, "ranks.txt"), "w", encoding="utf-8") as f:
            f.write("rank data")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(
        self,
        diagnostics: DiagnosticCollector | None = None,
    ) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
            diagnostics=diagnostics,
            max_workers=1,
        )

    def test_normalizes_nested_packaged_paths(self):
        converter = self._make_converter()
        converter.convert_all()

        expected_lang = os.path.join(
            self.godot_dir,
            "included_files",
            "languages",
            "english.lang",
        )
        expected_rank = os.path.join(
            self.godot_dir,
            "included_files",
            "modding",
            "ranking_system",
            "ranks.txt",
        )

        self.assertTrue(os.path.isfile(expected_lang), f"Expected {expected_lang}")
        self.assertTrue(os.path.isfile(expected_rank), f"Expected {expected_rank}")

        with open(expected_lang, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "lang data")
        with open(expected_rank, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "rank data")

    def test_collision_paths_reserve_natural_suffixes_and_warn_once(self) -> None:
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        fixtures = {
            "read_me.txt": "canonical",
            "Read Me.txt": "normalized collision",
            "read_me_2.txt": "natural suffix",
        }
        for filename, content in fixtures.items():
            with open(
                os.path.join(datafiles_dir, filename),
                "w",
                encoding="utf-8",
            ) as source_file:
                source_file.write(content)

        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        converter.convert_all()

        expected_outputs = {
            "read_me.txt": "canonical",
            "read_me_2.txt": "natural suffix",
            "read_me_3.txt": "normalized collision",
        }
        for filename, content in expected_outputs.items():
            with self.subTest(filename=filename):
                output_path = os.path.join(
                    self.godot_dir,
                    "included_files",
                    filename,
                )
                with open(output_path, "r", encoding="utf-8") as output_file:
                    self.assertEqual(output_file.read(), content)

        collision_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-PATH-COLLISION"
        ]
        self.assertEqual(len(collision_diagnostics), 1)
        collision = collision_diagnostics[0]
        self.assertEqual(collision.severity, "warning")
        self.assertEqual(collision.source_path, "datafiles")
        self.assertEqual(collision.resource, "read_me.txt")
        self.assertEqual(collision.resource_type, "included_file")
        self.assertIn("'read_me.txt' -> 'read_me.txt'", collision.message)
        self.assertIn("'Read Me.txt' -> 'read_me_3.txt'", collision.message)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=5, executed=5, completed=5),
        )
        with open(
            os.path.join(
                self.godot_dir,
                INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
            ),
            encoding="utf-8",
        ) as registry_file:
            registry_content = registry_file.read()
        self.assertIn('"logical_path": "Read Me.txt"', registry_content)
        self.assertIn('"assigned_path": "read_me_3.txt"', registry_content)
        self.assertEqual(registry_content.count('"emitted": true'), 5)

    def test_file_directory_prefix_collision_is_relocated_and_reported(
        self,
    ) -> None:
        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        with open(
            os.path.join(datafiles_dir, "foo_bar"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("blocking file")
        nested_directory = os.path.join(datafiles_dir, "Foo Bar")
        os.makedirs(nested_directory)
        with open(
            os.path.join(nested_directory, "item.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("nested file")

        diagnostics = DiagnosticCollector()
        converter = self._make_converter(diagnostics)
        converter.convert_all()

        blocking_output = os.path.join(
            self.godot_dir,
            "included_files",
            "foo_bar_2",
        )
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "foo_bar",
            "item.txt",
        )
        with open(blocking_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "blocking file")
        with open(nested_output, "r", encoding="utf-8") as output_file:
            self.assertEqual(output_file.read(), "nested file")

        collision_diagnostics = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-PATH-COLLISION"
        ]
        self.assertEqual(len(collision_diagnostics), 1)
        collision = collision_diagnostics[0]
        self.assertEqual(collision.resource, "foo_bar")
        self.assertEqual(
            collision.manifest_entry,
            "normalized Included File output path",
        )
        self.assertIn("'foo_bar' -> 'foo_bar_2'", collision.message)
        self.assertIn(
            "'Foo Bar/item.txt' -> 'foo_bar/item.txt'",
            collision.message,
        )
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=4, executed=4, completed=4),
        )


class TestIncludedFilesConverterSkipsYY(unittest.TestCase):
    """Test that .yy metadata files are skipped."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(datafiles_dir)

        with open(os.path.join(datafiles_dir, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("readme")
        with open(os.path.join(datafiles_dir, "datafiles.yy"), "w", encoding="utf-8") as f:
            f.write("{}")

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_skips_yy_files(self):
        converter = IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        included_dir = os.path.join(self.godot_dir, "included_files")
        self.assertTrue(os.path.isfile(os.path.join(included_dir, "readme.txt")))
        self.assertFalse(os.path.exists(os.path.join(included_dir, "datafiles.yy")))


class TestIncludedFilesConverterMissingFolder(unittest.TestCase):
    """When the datafiles folder does not exist the converter should log an error."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_missing_datafiles_no_crash(self):
        converter = IncludedFilesConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()
        self.assertTrue(len(self.logs) > 0,
                        "Expected at least one log message for missing datafiles folder")


class TestIncludedFilesConverterOutputContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.source_path = os.path.join(self.datafiles_dir, "payload.bin")
        self.payload = b"\x00included\xffpayload"
        with open(self.source_path, "wb") as source_file:
            source_file.write(self.payload)
        os.chmod(self.source_path, 0o640)
        os.utime(
            self.source_path,
            ns=(1_700_000_000_123_456_789, 1_700_000_001_987_654_321),
        )
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _convert(
        self,
        *,
        force_fallback: bool = False,
        expect_failure: bool = False,
    ) -> tuple[IncludedFilesConverter, DiagnosticCollector]:
        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        def convert() -> None:
            if force_fallback:
                with patch.object(
                    included_files_module,
                    "_confined_included_output_supported",
                    return_value=False,
                ):
                    converter.convert_all()
            else:
                converter.convert_all()

        if expect_failure:
            with self.assertRaises(OSError):
                convert()
        else:
            convert()
        return converter, diagnostics

    @staticmethod
    def _output_rejections(
        diagnostics: DiagnosticCollector,
    ) -> list[ConversionDiagnostic]:
        return [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-OUTPUT-REJECTED"
        ]

    def _make_symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def _assert_failed_output(
        self,
        converter: IncludedFilesConverter,
        diagnostics: DiagnosticCollector,
        *,
        requested: int = 1,
        completed: int = 0,
        rejection_count: int | None = None,
    ) -> None:
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(
                requested=requested,
                executed=requested,
                completed=completed,
                failed=requested - completed,
            ),
        )
        rejections = self._output_rejections(diagnostics)
        expected_rejections = (
            requested - completed
            if rejection_count is None
            else rejection_count
        )
        self.assertEqual(len(rejections), expected_rejections, rejections)
        self.assertTrue(
            all(
                diagnostic.severity == "error"
                and diagnostic.resource_type == "included_file"
                and diagnostic.manifest_entry
                == "generated Included File output"
                for diagnostic in rejections
            ),
            rejections,
        )

    def test_normal_copy_preserves_binary_bytes_and_metadata(self) -> None:
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.bin",
        )
        source_stat = os.stat(self.source_path)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                )

                with open(output_path, "rb") as output_file:
                    self.assertEqual(output_file.read(), self.payload)
                output_stat = os.stat(output_path)
                if os.chmod in os.supports_fd:
                    self.assertEqual(
                        stat.S_IMODE(output_stat.st_mode),
                        stat.S_IMODE(source_stat.st_mode),
                    )
                if os.utime in os.supports_fd:
                    self.assertEqual(
                        output_stat.st_mtime_ns,
                        source_stat.st_mtime_ns,
                    )
                self.assertEqual(
                    converter.conversion_step_result(
                        finalize_unfinished_as=None,
                    ).resources,
                    ConversionCounts(requested=1, executed=1, completed=1),
                )
                self.assertEqual(self._output_rejections(diagnostics), [])

    def test_rejects_redirected_included_files_root(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(self.outside_dir, managed_root)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(managed_root))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(converter, diagnostics)

    def test_rejects_redirected_nested_output_directory(self) -> None:
        nested_source_dir = os.path.join(self.datafiles_dir, "Nested")
        os.makedirs(nested_source_dir)
        with open(
            os.path.join(nested_source_dir, "child.bin"),
            "wb",
        ) as source_file:
            source_file.write(b"nested payload")
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        nested_output = os.path.join(managed_root, "nested")
        outside_output = os.path.join(self.outside_dir, "child.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(self.outside_dir, nested_output)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(nested_output))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(
                    converter,
                    diagnostics,
                    requested=2,
                )

    def test_rejects_final_output_symlink(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        self._make_symlink(outside_output, output_path)

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                    expect_failure=True,
                )

                self.assertTrue(os.path.islink(output_path))
                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                self._assert_failed_output(converter, diagnostics)

    def test_replaces_final_hardlink_without_mutating_referent(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")

        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                if os.path.lexists(output_path):
                    os.unlink(output_path)
                try:
                    os.link(outside_output, output_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Hard links are unavailable: {error}")

                converter, diagnostics = self._convert(
                    force_fallback=force_fallback,
                )

                with open(outside_output, "rb") as outside_file:
                    self.assertEqual(outside_file.read(), b"outside sentinel")
                with open(output_path, "rb") as output_file:
                    self.assertEqual(output_file.read(), self.payload)
                self.assertNotEqual(
                    os.stat(outside_output).st_ino,
                    os.stat(output_path).st_ino,
                )
                self.assertEqual(
                    converter.conversion_step_result(
                        finalize_unfinished_as=None,
                    ).resources,
                    ConversionCounts(requested=1, executed=1, completed=1),
                )
                self.assertEqual(self._output_rejections(diagnostics), [])

    def test_late_final_output_swap_is_rejected_without_external_mutation(
        self,
    ) -> None:
        if not included_files_module._confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        with open(output_path, "wb") as output_file:
            output_file.write(b"previous output")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_verify = included_files_module._verify_included_output_state_at
        swapped = False

        def swap_then_verify(
            directory_fd: int,
            filename: str,
            expected_identity: tuple[int, int] | None,
        ) -> None:
            nonlocal swapped
            if not swapped:
                os.unlink(output_path)
                self._make_symlink(outside_output, output_path)
                swapped = True
            original_verify(directory_fd, filename, expected_identity)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with patch.object(
            included_files_module,
            "_verify_included_output_state_at",
            side_effect=swap_then_verify,
        ), self.assertRaises(OSError):
            converter.convert_all()

        self.assertTrue(os.path.islink(output_path))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertFalse(
            any(name.startswith(".gm2godot-") for name in os.listdir(managed_root))
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_late_output_directory_relocation_is_rejected_before_publish(
        self,
    ) -> None:
        if not included_files_module._confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(self.outside_dir, "moved_nested")
        original_verify = (
            included_files_module._verify_open_included_output_directory
        )
        nested_verifications = 0

        def relocate_then_verify(
            project_path: str,
            directory_path: str,
            directory_fd: int,
        ) -> None:
            nonlocal nested_verifications
            if os.path.normcase(directory_path).endswith(
                os.path.normcase(os.path.join("included_files", "nested"))
            ):
                nested_verifications += 1
                if nested_verifications == 3:
                    os.rename(nested_output, moved_directory)
            original_verify(project_path, directory_path, directory_fd)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with patch.object(
            included_files_module,
            "_verify_open_included_output_directory",
            side_effect=relocate_then_verify,
        ), self.assertRaises(OSError):
            converter.convert_all()

        self.assertTrue(os.path.isdir(moved_directory))
        self.assertEqual(os.listdir(moved_directory), [])
        self.assertFalse(
            any(
                name.startswith(".gm2godot-")
                for name in os.listdir(self.godot_dir)
            )
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_final_rename_cannot_follow_swapped_output_directory(self) -> None:
        if not included_files_module._confined_included_output_supported():
            self.skipTest("Descriptor-relative Included File output is unavailable")
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(
            self.godot_dir,
            ".moved_nested",
        )
        redirected_directory = os.path.join(
            self.outside_dir,
            "redirected_nested",
        )
        os.makedirs(redirected_directory)
        outside_output = os.path.join(
            redirected_directory,
            "payload.bin",
        )
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_rename = os.rename
        swapped = False
        publication_dir_fds: tuple[int, int] | None = None

        def relocate_before_publish(
            source: str,
            destination: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            nonlocal publication_dir_fds, swapped
            if (
                not swapped
                and src_dir_fd is not None
                and dst_dir_fd is not None
                and source.startswith(".gm2godot-")
            ):
                original_rename(nested_output, moved_directory)
                self._make_symlink(
                    redirected_directory,
                    nested_output,
                )
                publication_dir_fds = (src_dir_fd, dst_dir_fd)
                swapped = True
            original_rename(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                included_files_module,
                "_confined_included_output_supported",
                return_value=True,
            ),
            patch.object(
                included_files_module.os,
                "rename",
                side_effect=relocate_before_publish,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(swapped)
        self.assertIsNotNone(publication_dir_fds)
        if publication_dir_fds is not None:
            self.assertEqual(
                publication_dir_fds[0],
                publication_dir_fds[1],
            )
        self.assertTrue(os.path.islink(nested_output))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertEqual(os.listdir(moved_directory), [])
        self.assertFalse(
            any(
                name.startswith(".gm2godot-")
                for name in os.listdir(self.godot_dir)
            )
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_fallback_late_final_swap_is_rejected_without_external_mutation(
        self,
    ) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        output_path = os.path.join(managed_root, "payload.bin")
        with open(output_path, "wb") as output_file:
            output_file.write(b"previous output")
        outside_output = os.path.join(self.outside_dir, "payload.bin")
        with open(outside_output, "wb") as outside_file:
            outside_file.write(b"outside sentinel")
        original_verify = included_files_module._verify_included_output_state
        swapped = False

        def swap_then_verify(
            path: str,
            expected_identity: tuple[int, int] | None,
        ) -> None:
            nonlocal swapped
            if not swapped:
                os.unlink(output_path)
                self._make_symlink(outside_output, output_path)
                swapped = True
            original_verify(path, expected_identity)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                included_files_module,
                "_confined_included_output_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_verify_included_output_state",
                side_effect=swap_then_verify,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(os.path.islink(output_path))
        with open(outside_output, "rb") as outside_file:
            self.assertEqual(outside_file.read(), b"outside sentinel")
        self.assertFalse(
            any(name.startswith(".gm2godot-") for name in os.listdir(managed_root))
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_fallback_late_directory_relocation_cleans_project_stage(
        self,
    ) -> None:
        os.unlink(self.source_path)
        nested_source = os.path.join(
            self.datafiles_dir,
            "Nested",
            "payload.bin",
        )
        os.makedirs(os.path.dirname(nested_source))
        with open(nested_source, "wb") as source_file:
            source_file.write(self.payload)
        nested_output = os.path.join(
            self.godot_dir,
            "included_files",
            "nested",
        )
        os.makedirs(nested_output)
        moved_directory = os.path.join(self.outside_dir, "moved_nested")
        original_verify = (
            included_files_module._verify_included_output_directories_fallback
        )
        moved = False

        def relocate_then_verify(
            identities: tuple[tuple[str, tuple[int, int]], ...],
        ) -> None:
            nonlocal moved
            if not moved and len(identities) > 1:
                os.rename(nested_output, moved_directory)
                moved = True
            original_verify(identities)

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                included_files_module,
                "_confined_included_output_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_verify_included_output_directories_fallback",
                side_effect=relocate_then_verify,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertTrue(os.path.isdir(moved_directory))
        self.assertEqual(os.listdir(moved_directory), [])
        self.assertFalse(
            any(
                name.startswith(".gm2godot-")
                for name in os.listdir(self.godot_dir)
            )
        )
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    def test_fallback_project_root_swap_cleans_external_stage_before_copy(
        self,
    ) -> None:
        moved_project = os.path.join(
            self.outside_dir,
            "moved_project",
        )
        original_mkstemp = tempfile.mkstemp
        original_rename = os.rename
        swapped = False

        def relocate_before_stage(
            suffix: str | None = None,
            prefix: str | None = None,
            dir: str | None = None,
            text: bool = False,
        ) -> tuple[int, str]:
            nonlocal swapped
            original_rename(self.godot_dir, moved_project)
            try:
                self._make_symlink(self.outside_dir, self.godot_dir)
            except BaseException:
                original_rename(moved_project, self.godot_dir)
                raise
            swapped = True
            return original_mkstemp(
                suffix=suffix,
                prefix=prefix,
                dir=dir,
                text=text,
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        try:
            with (
                patch.object(
                    included_files_module,
                    "_confined_included_output_supported",
                    return_value=False,
                ),
                patch.object(
                    included_files_module.tempfile,
                    "mkstemp",
                    side_effect=relocate_before_stage,
                ),
                self.assertRaises(OSError),
            ):
                converter.convert_all()

            outside_files = [
                os.path.join(directory, filename)
                for directory, _subdirectories, filenames in os.walk(
                    self.outside_dir
                )
                for filename in filenames
            ]
            self.assertTrue(swapped)
            self.assertEqual(outside_files, [])
            self._assert_failed_output(converter, diagnostics)
        finally:
            if os.path.islink(self.godot_dir):
                os.unlink(self.godot_dir)
            if os.path.isdir(moved_project):
                original_rename(moved_project, self.godot_dir)

    def test_fallback_rejects_mocked_windows_junction(self) -> None:
        managed_root = os.path.join(self.godot_dir, "included_files")
        os.makedirs(managed_root)
        normalized_managed_root = os.path.normcase(os.path.abspath(managed_root))

        def is_mock_junction(path: str) -> bool:
            return (
                os.path.normcase(os.path.abspath(path))
                == normalized_managed_root
            )

        diagnostics = DiagnosticCollector()
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=diagnostics,
        )
        with (
            patch.object(
                included_files_module,
                "_confined_included_output_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                os.path,
                "isjunction",
                side_effect=is_mock_junction,
                create=True,
            ),
            self.assertRaises(OSError),
        ):
            converter.convert_all()

        self.assertEqual(os.listdir(managed_root), [])
        self._assert_failed_output(converter, diagnostics)


class TestIncludedFilesConverterSourceContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        self.datafiles_dir = os.path.join(self.gm_dir, "datafiles")
        os.makedirs(self.datafiles_dir)
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    def _make_converter(self) -> IncludedFilesConverter:
        return IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=1,
            diagnostics=self.diagnostics,
        )

    def _source_path_rejections(self):
        return [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def _make_symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def test_rejects_datafiles_root_symlink_outside_project(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        shutil.rmtree(self.datafiles_dir)
        self._make_symlink(self.outside_dir, self.datafiles_dir)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "outside.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "datafiles")
        self.assertEqual(rejected[0].resource_type, "included_file")
        self.assertEqual(rejected[0].manifest_entry, "datafiles directory")

    def test_rejects_nested_directory_symlink_outside_project(self) -> None:
        with open(
            os.path.join(self.datafiles_dir, "safe.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.outside_dir, "outside.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("outside project")
        self._make_symlink(
            self.outside_dir,
            os.path.join(self.datafiles_dir, "linked_directory"),
        )

        self._make_converter().convert_all()

        self.assertTrue(
            os.path.isfile(
                os.path.join(self.godot_dir, "included_files", "safe.txt")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "linked_directory",
                    "outside.txt",
                )
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "linked_directory")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles entry")

    def test_rejects_file_symlink_outside_project(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        linked_file = os.path.join(self.datafiles_dir, "linked.txt")
        self._make_symlink(outside_file, linked_file)

        self._make_converter().convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "linked.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "linked.txt")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles entry")

    def test_preserves_contained_file_symlink_copy_semantics(self) -> None:
        target_file = os.path.join(self.datafiles_dir, "target.txt")
        with open(target_file, "w", encoding="utf-8") as source_file:
            source_file.write("contained target")
        self._make_symlink(
            target_file,
            os.path.join(self.datafiles_dir, "alias.txt"),
        )

        self._make_converter().convert_all()

        alias_output = os.path.join(
            self.godot_dir,
            "included_files",
            "alias.txt",
        )
        with open(alias_output, "r", encoding="utf-8") as copied_file:
            self.assertEqual(copied_file.read(), "contained target")

    def test_direct_copy_boundary_rejects_malformed_source_forms(self) -> None:
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        unsafe_paths = (
            os.path.relpath(outside_file, self.gm_dir),
            outside_file,
            r"C:\Games\Outside\file.txt",
            r"C:Outside\file.txt",
            r"\\server\share\file.txt",
            "invalid\0file.txt",
        )
        output_directory = os.path.join(self.godot_dir, "included_files")
        os.makedirs(output_directory)
        converter = self._make_converter()

        for index, source_path in enumerate(unsafe_paths):
            with self.subTest(source_path=source_path):
                output_path = os.path.join(output_directory, f"rejected_{index}.txt")
                result = converter._process_file(
                    source_path,
                    output_path,
                    f"rejected_{index}.txt",
                )
                self.assertEqual(
                    result,
                    (f"rejected_{index}.txt", False, None),
                )
                self.assertFalse(os.path.exists(output_path))

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), len(unsafe_paths), rejected)
        self.assertTrue(
            all(
                diagnostic.source_path == "datafiles"
                and diagnostic.resource_type == "included_file"
                and diagnostic.manifest_entry == "discovered datafiles file"
                for diagnostic in rejected
            )
        )

    def test_revalidates_file_after_discovery_before_copy(self) -> None:
        source_path = os.path.join(self.datafiles_dir, "swapped.txt")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write("original contained file")
        outside_file = os.path.join(self.outside_dir, "outside.txt")
        with open(outside_file, "w", encoding="utf-8") as source_file:
            source_file.write("outside project")
        converter = self._make_converter()
        original_process_file = converter._process_file
        swapped = False

        def swap_then_process(
            gm_file_path: str,
            godot_file_path: str,
            rel_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            nonlocal swapped
            if not swapped and rel_path == "swapped.txt":
                os.remove(source_path)
                self._make_symlink(outside_file, source_path)
                swapped = True
            return original_process_file(
                gm_file_path,
                godot_file_path,
                rel_path,
                owner_source_path,
            )

        with patch.object(
            converter,
            "_process_file",
            side_effect=swap_then_process,
        ), self.assertRaisesRegex(OSError, "output-set staging failed"):
            converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(self.godot_dir, "included_files", "swapped.txt")
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "datafiles")
        self.assertEqual(rejected[0].resource, "swapped.txt")
        self.assertEqual(rejected[0].manifest_entry, "discovered datafiles file")
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                )
            )
        )

    def test_revalidates_nested_directory_before_listing(self) -> None:
        nested_directory = os.path.join(self.datafiles_dir, "nested")
        os.makedirs(nested_directory)
        with open(
            os.path.join(nested_directory, "safe.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("safe")
        with open(
            os.path.join(self.outside_dir, "outside.txt"),
            "w",
            encoding="utf-8",
        ) as source_file:
            source_file.write("outside project")
        converter = self._make_converter()
        original_list_directory = converter._list_confined_directory
        swapped = False

        def swap_then_list(
            directory: ResolvedProjectSourcePath,
        ) -> tuple[str, ...] | None:
            nonlocal swapped
            if not swapped and directory.source_path == "datafiles/nested":
                shutil.rmtree(nested_directory)
                self._make_symlink(self.outside_dir, nested_directory)
                swapped = True
            return original_list_directory(directory)

        with patch.object(
            converter,
            "_list_confined_directory",
            side_effect=swap_then_list,
        ):
            converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "included_files",
                    "nested",
                    "outside.txt",
                )
            )
        )
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "nested")
        self.assertEqual(
            rejected[0].manifest_entry,
            "discovered datafiles directory",
        )


if __name__ == "__main__":
    unittest.main()
