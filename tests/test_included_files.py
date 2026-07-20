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
import tracemalloc
import unittest
from collections.abc import Collection, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import BinaryIO, Callable
from unittest.mock import MagicMock, mock_open, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    render_included_file_registry,
)
from src.conversion.included_file_paths import (
    IncludedFilePathAssignment,
    plan_included_file_paths,
)
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.converter import Converter
from src.conversion.diagnostics import ConversionDiagnostic, DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath


def _included_files_transaction_debris(project_path: str) -> tuple[str, ...]:
    project_path = os.path.abspath(project_path)
    persistent_lock_path = os.path.normcase(
        os.path.join(
            project_path,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
    )
    debris: list[str] = []
    for directory, subdirectories, filenames in os.walk(project_path):
        for name in (*subdirectories, *filenames):
            candidate_path = os.path.abspath(os.path.join(directory, name))
            if os.path.normcase(candidate_path) == persistent_lock_path:
                continue
            if (
                name == included_files_module._INCLUDED_FILES_LOCK_NAME
                or name == included_files_module._INCLUDED_FILES_JOURNAL_NAME
                or name == included_files_module._INCLUDED_FILES_COMMIT_NAME
                or name == included_files_module._INCLUDED_FILES_STAGE_MARKER_NAME
                or name.startswith(
                    included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                )
                or name.startswith(
                    included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                )
                or name.startswith(
                    included_files_module._INCLUDED_FILES_STAGE_PREFIX
                )
                or name.startswith(".included_files.")
                or name.startswith(".gml_included_file_registry.gd.")
                or name.startswith(
                    included_files_module._INCLUDED_FILES_CLEANUP_PREFIX
                )
            ):
                debris.append(
                    os.path.relpath(candidate_path, project_path).replace(
                        os.sep,
                        "/",
                    )
                )
    return tuple(sorted(debris))


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
        if (
            not (
                stat.S_ISREG(path_stat.st_mode)
                or stat.S_ISDIR(path_stat.st_mode)
            )
            or path_mode & stat.S_IWRITE
        ):
            raise error
        os.chmod(path, path_mode | stat.S_IWRITE)
        function(path)

    @staticmethod
    def _open_modeled_windows_validation_stream(
        path: str,
        *,
        deny_writes: bool,
        no_follow: bool = False,
    ) -> BinaryIO:
        del deny_writes, no_follow
        return open(path, "rb")

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

    def _make_deep_tree(self, label: str, depth: int) -> str:
        root_path = os.path.join(self.godot_dir, label)
        os.mkdir(root_path)
        directory_path = root_path
        for _index in range(depth):
            directory_path = os.path.join(directory_path, "d")
            os.mkdir(directory_path)
        with open(
            os.path.join(directory_path, "payload.bin"),
            "wb",
        ) as payload_file:
            payload_file.write(b"deterministic deep-tree payload\n")
        return root_path

    def _assert_streaming_cleanup_path(self, *, force_fallback: bool) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "fallback-streaming-cleanup"
            if force_fallback
            else "descriptor-streaming-cleanup",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.bin")
        content = b"streaming cleanup payload\n" * (96 * 1024)
        with open(owned_path, "wb") as owned_file:
            owned_file.write(content)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        streamed_bytes = 0
        largest_chunk = 0
        original_read = included_files_module._read_included_validation_chunk

        def count_streamed_bytes(opened_file: BinaryIO) -> bytes:
            nonlocal streamed_bytes, largest_chunk
            chunk = original_read(opened_file)
            streamed_bytes += len(chunk)
            largest_chunk = max(largest_chunk, len(chunk))
            return chunk

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=not force_fallback,
            ),
            patch.object(
                included_files_module,
                "_read_included_validation_chunk",
                side_effect=count_streamed_bytes,
            ),
            patch.object(
                included_files_module,
                "_included_regular_file_state",
                side_effect=AssertionError(
                    "cleanup used the whole-content file-state helper"
                ),
            ),
            patch.object(
                included_files_module,
                "_rename_included_transaction_entry",
                side_effect=os.rename,
            ),
            patch.object(
                included_files_module,
                "_sync_included_directory",
            ),
        ):
            warnings = included_files_module._cleanup_recorded_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                hashlib.sha256(content).hexdigest(),
                (parent_stat.st_dev, parent_stat.st_ino),
                "e" * 32,
                "streaming-cleanup",
                "owned.bin",
                expected_fingerprint=(
                    included_files_module._included_path_fingerprint(
                        owned_stat
                    )
                ),
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertEqual(warnings, ())
        self.assertEqual(streamed_bytes, 2 * len(content))
        self.assertLessEqual(largest_chunk, 1024 * 1024)
        self.assertFalse(os.path.lexists(owned_path))

    @staticmethod
    def _recovery_cleanup_snapshot(
        relative_path: str,
    ) -> included_files_module._IncludedTreeSnapshot:
        components = relative_path.split("/")
        entries: list[included_files_module._IncludedTreeEntry] = []
        for index in range(1, len(components)):
            entries.append(
                included_files_module._IncludedTreeEntry(
                    relative_path="/".join(components[:index]),
                    kind="directory",
                    fingerprint=(
                        11,
                        200 + index,
                        stat.S_IFDIR | 0o700,
                        0,
                        0,
                        1,
                    ),
                    ctime_ns=None,
                    content_sha256=None,
                )
            )
        entries.append(
            included_files_module._IncludedTreeEntry(
                relative_path=relative_path,
                kind="file",
                fingerprint=(11, 401, stat.S_IFREG | 0o600, 0, 0, 1),
                ctime_ns=0,
                content_sha256=hashlib.sha256(b"").hexdigest(),
            )
        )
        return included_files_module._IncludedTreeSnapshot(
            root_fingerprint=(11, 21, stat.S_IFDIR | 0o700, 0, 0, 1),
            entries=tuple(
                sorted(entries, key=lambda entry: entry.relative_path)
            ),
        )

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

    @staticmethod
    def _mark_native_windows_tree_read_only(root_path: str) -> None:
        for directory, subdirectories, filenames in os.walk(
            root_path,
            topdown=False,
        ):
            for filename in filenames:
                os.chmod(
                    os.path.join(directory, filename),
                    stat.S_IREAD,
                )
            for subdirectory in subdirectories:
                os.chmod(
                    os.path.join(directory, subdirectory),
                    stat.S_IREAD,
                )
        os.chmod(root_path, stat.S_IREAD)

    def _transaction_with_native_windows_readonly_staged_root(
        self,
        transaction: included_files_module._IncludedOutputSetTransaction,
    ) -> included_files_module._IncludedOutputSetTransaction:
        self._mark_native_windows_tree_read_only(
            transaction.staged_root_path
        )
        staged_root_snapshot = included_files_module._capture_included_tree(
            transaction.staged_root_path,
            expected_parent_identity=transaction.stage_container_identity,
        )
        staged_container_snapshot = (
            included_files_module._included_stage_container_snapshot(
                transaction.project_identity,
                transaction.stage_container_path,
                transaction.stage_container_identity,
                staged_root_snapshot,
                transaction.staged_registry_identity,
                transaction.staged_registry_content,
            )
        )
        return replace(
            transaction,
            staged_container_snapshot=staged_container_snapshot,
            staged_root_snapshot=staged_root_snapshot,
        )

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

    def _leave_committed_generation_recovery_records(self) -> None:
        self._write("old.txt", "old generation")
        self._converter(max_workers=1).convert_all()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        interrupted = subprocess.run(
            (
                sys.executable,
                "-c",
                interruption_script,
                self.gm_dir,
                self.godot_dir,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )

    def _rewrite_included_recovery_records_as_v1(
        self,
        project_path: str,
        project_identity: tuple[int, int],
    ) -> int:
        rewritten = 0
        for name in sorted(os.listdir(project_path)):
            if not (
                name
                in {
                    included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                    included_files_module._INCLUDED_FILES_COMMIT_NAME,
                }
                or (
                    name.startswith(
                        included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                )
                or (
                    name.startswith(
                        included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                )
            ):
                continue
            record_path = os.path.join(project_path, name)
            record = included_files_module._read_included_recovery_record(
                record_path,
                project_identity,
            )
            if record is None:
                continue
            payload = record[1]
            state = payload.get("state")
            if state == "prepared":
                journal = (
                    included_files_module._included_recovery_journal_from_payload(
                        project_path,
                        project_identity,
                        payload,
                    )
                )
                legacy_journal = replace(
                    journal,
                    format_version=(
                        included_files_module._INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
                    ),
                )
                legacy_payload = (
                    included_files_module._included_recovery_journal_payload_v1(
                        legacy_journal
                    )
                )
            elif state == "committed":
                _marker, journal = (
                    included_files_module._included_commit_marker_and_journal_from_payload(
                        project_path,
                        payload,
                        project_identity,
                    )
                )
                legacy_journal = replace(
                    journal,
                    format_version=(
                        included_files_module._INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
                    ),
                )
                legacy_payload = (
                    included_files_module._included_commit_marker_payload_v1(
                        legacy_journal
                    )
                )
            else:
                continue
            with open(record_path, "wb") as record_file:
                record_file.write(
                    included_files_module._included_recovery_record_content(
                        legacy_payload
                    )
                )
                record_file.flush()
                os.fsync(record_file.fileno())
            rewritten += 1
        included_files_module._sync_included_directory(
            project_path,
            project_identity,
        )
        return rewritten

    def test_recovery_parsers_reject_ambiguous_json_types(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_record = included_files_module._read_included_recovery_record(
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_JOURNAL_NAME,
            ),
            project_identity,
        )
        commit_record = included_files_module._read_included_recovery_record(
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_COMMIT_NAME,
            ),
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        journal_payload = dict(journal_record[1])
        commit_payload = dict(commit_record[1])
        journal = included_files_module._included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        stage_identity = journal.transaction.stage_container_identity
        stage_payload = {
            "format_version": True,
            "state": "staging",
            "project_identity": list(project_identity),
            "stage_identity": list(stage_identity),
        }
        journal_with_invalid_backup_location = dict(journal_payload)
        journal_with_invalid_backup_location["registry_backup_location"] = []
        tree_with_invalid_kind = {
            "root_fingerprint": [
                1,
                2,
                stat.S_IFDIR | 0o700,
                0,
                0,
                1,
            ],
            "entries": [
                {
                    "relative_path": "payload.txt",
                    "kind": [],
                    "fingerprint": [
                        1,
                        3,
                        stat.S_IFREG | 0o600,
                        0,
                        0,
                        1,
                    ],
                    "ctime_ns": 0,
                    "content_sha256": hashlib.sha256(b"").hexdigest(),
                }
            ],
        }
        journal_payload["format_version"] = True
        commit_payload["format_version"] = True

        cases: tuple[tuple[str, Callable[[], object], str], ...] = (
            (
                "journal",
                lambda: included_files_module._included_recovery_journal_from_payload(
                    self.godot_dir,
                    project_identity,
                    journal_payload,
                ),
                "journal format version",
            ),
            (
                "commit-marker",
                lambda: included_files_module._included_commit_marker_and_journal_from_payload(
                    self.godot_dir,
                    commit_payload,
                    project_identity,
                ),
                "commit marker format version",
            ),
            (
                "stage-marker",
                lambda: included_files_module._included_stage_marker_matches(
                    stage_payload,
                    project_identity,
                    stage_identity,
                ),
                "stage marker format version",
            ),
            (
                "tree-kind",
                lambda: included_files_module._included_tree_snapshot_from_payload(
                    tree_with_invalid_kind,
                    "test tree",
                ),
                "tree kind",
            ),
            (
                "registry-backup-location",
                lambda: included_files_module._included_recovery_journal_from_payload(
                    self.godot_dir,
                    project_identity,
                    journal_with_invalid_backup_location,
                ),
                "registry recovery backup location",
            ),
        )
        for label, parse, error_pattern in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(OSError, error_pattern):
                    parse()

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
            patch.object(included_files_module.sys, "platform", "linux"),
            patch(
                "builtins.open",
                mock_open(read_data="pos:\t0\nflags:\t0100000\nmnt_id:\t41\n"),
            ),
        ):
            self.assertEqual(
                included_files_module._included_linux_mount_id_from_fd(123),
                41,
            )

        with (
            patch.object(
                included_files_module,
                "_included_linux_mount_id_from_fd",
                return_value=42,
            ),
            patch.object(included_files_module.os.path, "ismount", return_value=False),
            self.assertRaisesRegex(OSError, "mount boundary"),
        ):
            included_files_module._verify_included_mount_boundary(
                os.path.join(self.datafiles_dir, "test-mount-id"),
                opened_stat,
                opened_stat.st_dev,
                41,
                123,
            )

    def test_descriptor_tree_capture_closes_parent_when_mount_check_fails(
        self,
    ) -> None:
        if not included_files_module._included_descriptor_paths_supported():
            self.skipTest("Descriptor-pinned tree capture is unavailable")
        root_path = os.path.join(self.godot_dir, "fd-cleanup-root")
        os.mkdir(root_path)
        original_open_parent = (
            included_files_module._open_pinned_included_parent
        )
        opened_parent_fd = -1

        def observe_parent_open(path: str) -> tuple[int, str]:
            nonlocal opened_parent_fd
            opened_parent_fd, name = original_open_parent(path)
            return opened_parent_fd, name

        with (
            patch.object(
                included_files_module,
                "_open_pinned_included_parent",
                side_effect=observe_parent_open,
            ),
            patch.object(
                included_files_module,
                "_included_linux_mount_id_from_fd",
                side_effect=OSError("injected mount inspection failure"),
            ),
            self.assertRaisesRegex(OSError, "mount inspection failure"),
        ):
            included_files_module._capture_included_tree(root_path)

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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module.os.path,
                "ismount",
                side_effect=modeled_mountpoint,
            ),
            self.assertRaisesRegex(OSError, "mount boundary"),
        ):
            included_files_module._capture_included_tree(
                root_path,
                expected_parent_identity=(
                    project_stat.st_dev,
                    project_stat.st_ino,
                ),
            )

        with open(sentinel_path, "rb") as sentinel_file:
            self.assertEqual(sentinel_file.read(), b"external mount sentinel")

    def test_recovery_tree_parser_rejects_cross_device_entry(self) -> None:
        root_path = os.path.join(self.godot_dir, "included_files")
        os.makedirs(root_path)
        with open(os.path.join(root_path, "payload.txt"), "wb") as payload_file:
            payload_file.write(b"payload")
        snapshot = included_files_module._capture_included_tree(root_path)
        payload = included_files_module._included_tree_snapshot_payload(snapshot)
        entries = payload["entries"]
        self.assertIsInstance(entries, list)
        first_entry = entries[0]
        self.assertIsInstance(first_entry, dict)
        fingerprint = first_entry["fingerprint"]
        self.assertIsInstance(fingerprint, list)
        root_fingerprint = snapshot.root_fingerprint
        if root_fingerprint is None:
            self.fail("captured recovery test tree unexpectedly disappeared")
        fingerprint[0] = root_fingerprint[0] + 1

        with self.assertRaisesRegex(OSError, "cross-device"):
            included_files_module._included_tree_snapshot_from_payload(
                payload,
                "modeled cross-device tree",
            )

    def test_cleanup_preserves_tree_when_nested_mount_appears(self) -> None:
        root_path = os.path.join(self.godot_dir, "cleanup-root")
        mounted_path = os.path.join(root_path, "mounted")
        sentinel_path = os.path.join(mounted_path, "external-sentinel.txt")
        os.makedirs(mounted_path)
        with open(sentinel_path, "wb") as sentinel_file:
            sentinel_file.write(b"late mount sentinel")
        project_stat = os.lstat(self.godot_dir)
        snapshot = included_files_module._capture_included_tree(
            root_path,
            expected_parent_identity=(project_stat.st_dev, project_stat.st_ino),
        )
        mounted_normalized = os.path.normcase(os.path.abspath(mounted_path))

        def modeled_mountpoint(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == mounted_normalized

        with patch.object(
            included_files_module.os.path,
            "ismount",
            side_effect=modeled_mountpoint,
        ):
            warnings = included_files_module._cleanup_recorded_included_tree(
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

    def test_owned_tree_cleanup_preserves_modeled_nested_mount(self) -> None:
        variants = [("fallback", False)]
        if (
            included_files_module._included_descriptor_paths_supported()
            and included_files_module._included_native_noreplace_available()
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
                        included_files_module,
                        "_included_descriptor_paths_supported",
                        return_value=descriptor_paths_supported,
                    ),
                    patch.object(
                        included_files_module.os,
                        "name",
                        os.name if descriptor_paths_supported else "nt",
                    ),
                    patch.object(
                        included_files_module.os.path,
                        "ismount",
                        side_effect=modeled_mountpoint,
                    ),
                    self.assertRaisesRegex(OSError, "mount boundary"),
                ):
                    included_files_module._remove_owned_included_tree(
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
        if not included_files_module._included_descriptor_paths_supported():
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
                    included_files_module.os.path,
                    "ismount",
                    return_value=False,
                ),
                self.assertRaisesRegex(OSError, "mount boundary"),
            ):
                included_files_module._capture_included_tree(
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

    def _assert_no_transaction_debris(self) -> None:
        self.assertEqual(
            _included_files_transaction_debris(self.godot_dir),
            (),
        )

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
                included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                False,
            ),
            (
                "commit-marker",
                included_files_module._INCLUDED_FILES_COMMIT_NAME,
                False,
            ),
            (
                "stage-marker",
                included_files_module._INCLUDED_FILES_STAGE_MARKER_NAME,
                False,
            ),
            (
                "journal-temporary",
                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "commit-temporary",
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "lock-initialization-temporary",
                included_files_module._INCLUDED_FILES_LOCK_TEMP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "lock-cleanup-tombstone",
                included_files_module._INCLUDED_FILES_LOCK_CLEANUP_PREFIX
                + token
                + ".tmp",
                False,
            ),
            (
                "stage",
                included_files_module._INCLUDED_FILES_STAGE_PREFIX
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
                included_files_module._INCLUDED_FILES_CLEANUP_PREFIX
                + cleanup_digest
                + ".file",
                False,
            ),
            (
                "cleanup-directory-tombstone",
                included_files_module._INCLUDED_FILES_CLEANUP_PREFIX
                + cleanup_digest
                + ".dir",
                True,
            ),
            (
                "nested-lock-collision",
                os.path.join(
                    "gm2godot",
                    included_files_module._INCLUDED_FILES_LOCK_NAME,
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
                    included_files_module._INCLUDED_FILES_LOCK_NAME,
                )
                with open(lock_path, "wb") as lock_file:
                    lock_file.write(
                        included_files_module._INCLUDED_FILES_LOCK_CONTENT
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

    def _run_interrupted_conversion(
        self,
        phase: str,
        *,
        gm_path: str | None = None,
        godot_path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path, requested_phase = sys.argv[1:]

def stop_after_phase(current_phase: str) -> None:
    if current_phase == requested_phase:
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        return subprocess.run(
            (
                sys.executable,
                "-c",
                interruption_script,
                self.gm_dir if gm_path is None else gm_path,
                self.godot_dir if godot_path is None else godot_path,
                phase,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )

    def test_project_lock_rejects_concurrent_included_files_transaction(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        with patch.object(
            included_files_module.tempfile,
            "gettempdir",
            side_effect=AssertionError(
                "the Included Files lock must not depend on a temp directory"
            ),
        ):
            first_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            self.assertEqual(first_lock.path, lock_path)
            first_identity = (
                os.lstat(lock_path).st_dev,
                os.lstat(lock_path).st_ino,
            )
            try:
                with self.assertRaisesRegex(
                    OSError,
                    "already publishing or recovering",
                ):
                    included_files_module._acquire_included_project_lock(
                        self.godot_dir,
                        project_identity,
                    )
            finally:
                included_files_module._release_included_project_lock(first_lock)

            with open(lock_path, "rb") as lock_file:
                self.assertEqual(
                    lock_file.read(),
                    included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                )
            self.assertEqual(
                (os.lstat(lock_path).st_dev, os.lstat(lock_path).st_ino),
                first_identity,
            )

            second_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            self.assertEqual(second_lock.path, lock_path)
            included_files_module._release_included_project_lock(second_lock)

        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
            )
        self.assertEqual(
            (os.lstat(lock_path).st_dev, os.lstat(lock_path).st_ino),
            first_identity,
        )

    def test_project_lock_rejects_ambiguous_existing_content_without_mutation(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        lock_content = included_files_module._INCLUDED_FILES_LOCK_CONTENT
        cases = {
            "empty": b"",
            "partial-prefix": lock_content[: len(lock_content) // 2],
            "unrelated": b"user-owned lock collision\n",
        }

        for label, existing_content in cases.items():
            with self.subTest(content=label):
                with open(lock_path, "wb") as lock_file:
                    lock_file.write(existing_content)
                original_stat = os.lstat(lock_path)
                original_identity = (original_stat.st_dev, original_stat.st_ino)

                with self.assertRaisesRegex(
                    OSError,
                    "unknown or incomplete file",
                ):
                    included_files_module._acquire_included_project_lock(
                        self.godot_dir,
                        project_identity,
                    )

                current_stat = os.lstat(lock_path)
                self.assertEqual(
                    (current_stat.st_dev, current_stat.st_ino),
                    original_identity,
                )
                with open(lock_path, "rb") as lock_file:
                    self.assertEqual(lock_file.read(), existing_content)
                os.unlink(lock_path)

    def test_modeled_windows_lock_contends_before_reading_locked_byte(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        with open(lock_path, "wb") as lock_file:
            lock_file.write(included_files_module._INCLUDED_FILES_LOCK_CONTENT)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_windows_included_file_locking",
                side_effect=PermissionError("locked byte"),
            ) as locking,
            patch.object(
                included_files_module.os,
                "read",
                side_effect=AssertionError("locked byte was read before contention"),
            ) as read,
            self.assertRaisesRegex(OSError, "already publishing or recovering"),
        ):
            included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )

        locking.assert_called_once()
        self.assertEqual(locking.call_args.args[1], 2)
        read.assert_not_called()

    def test_modeled_windows_unknown_lock_is_unlocked_after_validation(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        existing_content = b"user-owned lock collision\n"
        with open(lock_path, "wb") as lock_file:
            lock_file.write(existing_content)
        locking_modes: list[int] = []

        def record_locking(_file_descriptor: int, mode: int) -> None:
            locking_modes.append(mode)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_windows_included_file_locking",
                side_effect=record_locking,
            ),
            self.assertRaisesRegex(OSError, "unknown or incomplete file"),
        ):
            included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )

        self.assertEqual(locking_modes, [2, 0])
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(lock_file.read(), existing_content)

    def test_fallback_stage_name_matches_recovery_grammar(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module, "_sync_included_directory"),
        ):
            stage_path, _stage_identity = (
                included_files_module._create_included_output_stage(
                    self.godot_dir,
                    project_identity,
                )
            )

        stage_name = os.path.basename(stage_path)
        self.assertEqual(
            included_files_module._included_recovery_managed_name(
                stage_name,
                prefix=included_files_module._INCLUDED_FILES_STAGE_PREFIX,
                suffix=".stage",
                label="stage container",
            ),
            stage_name,
        )

    def test_fallback_stage_allocation_preserves_colliding_file(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        first_token = "a" * 16
        second_token = "b" * 16
        colliding_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_STAGE_PREFIX
            + first_token
            + ".stage",
        )
        colliding_content = b"user-owned stage collision\n"
        with open(colliding_path, "wb") as colliding_file:
            colliding_file.write(colliding_content)
        colliding_stat = os.lstat(colliding_path)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module, "_sync_included_directory"),
            patch.object(
                included_files_module.secrets,
                "token_hex",
                side_effect=[first_token, second_token],
            ) as token_hex,
        ):
            stage_path, _stage_identity = (
                included_files_module._create_included_output_stage(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(
            os.path.basename(stage_path),
            included_files_module._INCLUDED_FILES_STAGE_PREFIX
            + second_token
            + ".stage",
        )
        self.assertEqual(token_hex.call_count, 2)
        current_colliding_stat = os.lstat(colliding_path)
        self.assertEqual(
            (current_colliding_stat.st_dev, current_colliding_stat.st_ino),
            (colliding_stat.st_dev, colliding_stat.st_ino),
        )
        with open(colliding_path, "rb") as colliding_file:
            self.assertEqual(colliding_file.read(), colliding_content)

    def test_fallback_stage_allocation_exhaustion_preserves_collision(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        colliding_token = "c" * 16
        colliding_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_STAGE_PREFIX
            + colliding_token
            + ".stage",
        )
        colliding_content = b"persistent user-owned stage collision\n"
        with open(colliding_path, "wb") as colliding_file:
            colliding_file.write(colliding_content)
        colliding_stat = os.lstat(colliding_path)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(
                included_files_module.secrets,
                "token_hex",
                return_value=colliding_token,
            ) as token_hex,
            self.assertRaisesRegex(
                OSError,
                "Could not allocate Included Files staging directory",
            ),
        ):
            included_files_module._create_included_output_stage(
                self.godot_dir,
                project_identity,
            )

        self.assertEqual(token_hex.call_count, 100)
        current_colliding_stat = os.lstat(colliding_path)
        self.assertEqual(
            (current_colliding_stat.st_dev, current_colliding_stat.st_ino),
            (colliding_stat.st_dev, colliding_stat.st_ino),
        )
        with open(colliding_path, "rb") as colliding_file:
            self.assertEqual(colliding_file.read(), colliding_content)

    def test_project_lock_initialization_recovers_after_hard_exit(self) -> None:
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module

project_path, requested_phase = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_files_module._after_included_lock_initialization_phase = stop_after_phase
project_identity = included_files_module._ensure_included_output_project_root(
    project_path
)
included_files_module._acquire_included_project_lock(
    project_path,
    project_identity,
)
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        partial_phases = {
            "temporary-created": b"",
            "temporary-partially-written": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT[
                    : len(included_files_module._INCLUDED_FILES_LOCK_CONTENT) // 2
                ]
            ),
        }
        phases = (
            *partial_phases,
            "temporary-written",
            "temporary-synced",
            "temporary-published",
        )

        for phase in phases:
            with self.subTest(phase=phase):
                project_path = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, project_path)
                interrupted = subprocess.run(
                    (
                        sys.executable,
                        "-c",
                        interruption_script,
                        project_path,
                        phase,
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=environment,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )
                lock_path = os.path.join(
                    project_path,
                    included_files_module._INCLUDED_FILES_LOCK_NAME,
                )
                temporary_paths = [
                    os.path.join(project_path, name)
                    for name in os.listdir(project_path)
                    if name.startswith(
                        included_files_module._INCLUDED_FILES_LOCK_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                ]
                if phase == "temporary-published":
                    self.assertEqual(temporary_paths, [])
                    self.assertTrue(os.path.isfile(lock_path))
                else:
                    self.assertEqual(len(temporary_paths), 1)
                    self.assertFalse(os.path.lexists(lock_path))
                if phase in {"temporary-written", "temporary-synced"}:
                    self.assertEqual(
                        os.lstat(temporary_paths[0]).st_size,
                        len(included_files_module._INCLUDED_FILES_LOCK_CONTENT),
                    )
                    with open(temporary_paths[0], "rb") as temporary_file:
                        self.assertEqual(
                            temporary_file.read(),
                            included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                        )

                project_identity = (
                    included_files_module._ensure_included_output_project_root(
                        project_path
                    )
                )
                project_lock = included_files_module._acquire_included_project_lock(
                    project_path,
                    project_identity,
                )
                included_files_module._release_included_project_lock(project_lock)

                with open(lock_path, "rb") as lock_file:
                    self.assertEqual(
                        lock_file.read(),
                        included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                    )
                remaining_temporaries = [
                    path for path in temporary_paths if os.path.lexists(path)
                ]
                if phase in partial_phases:
                    self.assertEqual(remaining_temporaries, temporary_paths)
                    with open(remaining_temporaries[0], "rb") as temporary_file:
                        self.assertEqual(temporary_file.read(), partial_phases[phase])
                else:
                    self.assertEqual(remaining_temporaries, [])
                self.assertFalse(
                    any(
                        name.startswith(
                            included_files_module._INCLUDED_FILES_LOCK_CLEANUP_PREFIX
                        )
                        for name in os.listdir(project_path)
                    )
                )

    def test_project_lock_cleanup_tombstone_recovers_after_hard_exit(self) -> None:
        project_path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project_path)
        token = "d" * 16
        temporary_path = os.path.join(
            project_path,
            included_files_module._INCLUDED_FILES_LOCK_TEMP_PREFIX
            + token
            + ".tmp",
        )
        tombstone_path = os.path.join(
            project_path,
            included_files_module._INCLUDED_FILES_LOCK_CLEANUP_PREFIX
            + token
            + ".tmp",
        )
        with open(temporary_path, "wb") as temporary_file:
            temporary_file.write(included_files_module._INCLUDED_FILES_LOCK_CONTENT)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module

project_path = sys.argv[1]

def stop_after_phase(phase: str) -> None:
    if phase == "temporary-cleanup-quarantined":
        os._exit(86)

included_files_module._after_included_lock_initialization_phase = stop_after_phase
project_identity = included_files_module._ensure_included_output_project_root(
    project_path
)
included_files_module._acquire_included_project_lock(
    project_path,
    project_identity,
)
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        interrupted = subprocess.run(
            (sys.executable, "-c", interruption_script, project_path),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertFalse(os.path.lexists(temporary_path))
        with open(tombstone_path, "rb") as tombstone_file:
            self.assertEqual(
                tombstone_file.read(),
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
            )

        project_identity = (
            included_files_module._ensure_included_output_project_root(project_path)
        )
        project_lock = included_files_module._acquire_included_project_lock(
            project_path,
            project_identity,
        )
        included_files_module._release_included_project_lock(project_lock)
        self.assertFalse(os.path.lexists(tombstone_path))
        self.assertEqual(_included_files_transaction_debris(project_path), ())

    def test_project_lock_concurrent_initializers_publish_once(self) -> None:
        project_path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project_path)
        project_identity = (
            included_files_module._ensure_included_output_project_root(project_path)
        )
        initialization_barrier = threading.Barrier(2)
        losing_initializer_finished = threading.Event()
        results: list[str] = []
        results_lock = threading.Lock()

        def wait_for_both_initializers(phase: str) -> None:
            if phase == "temporary-synced":
                initialization_barrier.wait(timeout=10)

        def acquire() -> None:
            try:
                project_lock = included_files_module._acquire_included_project_lock(
                    project_path,
                    project_identity,
                )
            except OSError as error:
                with results_lock:
                    results.append(str(error))
                losing_initializer_finished.set()
                return
            with results_lock:
                results.append("acquired")
            try:
                losing_initializer_finished.wait(timeout=10)
            finally:
                included_files_module._release_included_project_lock(project_lock)

        with patch.object(
            included_files_module,
            "_after_included_lock_initialization_phase",
            side_effect=wait_for_both_initializers,
        ):
            workers = [threading.Thread(target=acquire) for _index in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
            self.assertTrue(all(not worker.is_alive() for worker in workers))

        self.assertEqual(results.count("acquired"), 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(
            any("already publishing or recovering" in result for result in results)
        )
        lock_path = os.path.join(
            project_path,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
            )
        self.assertEqual(_included_files_transaction_debris(project_path), ())
        next_lock = included_files_module._acquire_included_project_lock(
            project_path,
            project_identity,
        )
        included_files_module._release_included_project_lock(next_lock)

    def test_project_lock_cleans_only_canonical_complete_temporaries(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        prefix = included_files_module._INCLUDED_FILES_LOCK_TEMP_PREFIX
        cleanup_prefix = (
            included_files_module._INCLUDED_FILES_LOCK_CLEANUP_PREFIX
        )
        candidates = {
            prefix + "a" * 16 + ".tmp": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                False,
            ),
            prefix + "b" * 16 + ".tmp": (b"partial lock bytes", True),
            prefix + "c" * 15 + ".tmp": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            prefix + "e" * 16 + ".tmp": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            cleanup_prefix + "e" * 16 + ".tmp": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            cleanup_prefix + "f" * 16 + ".tmp": (
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
                False,
            ),
        }
        original_identities: dict[str, tuple[int, int]] = {}
        for name, (content, _preserved) in candidates.items():
            path = os.path.join(self.godot_dir, name)
            with open(path, "wb") as temporary_file:
                temporary_file.write(content)
            path_stat = os.lstat(path)
            original_identities[name] = (path_stat.st_dev, path_stat.st_ino)

        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        included_files_module._release_included_project_lock(project_lock)

        for name, (content, preserved) in candidates.items():
            with self.subTest(name=name):
                path = os.path.join(self.godot_dir, name)
                self.assertEqual(os.path.lexists(path), preserved)
                if not preserved:
                    continue
                path_stat = os.lstat(path)
                self.assertEqual(
                    (path_stat.st_dev, path_stat.st_ino),
                    original_identities[name],
                )
                with open(path, "rb") as temporary_file:
                    self.assertEqual(temporary_file.read(), content)

    def test_project_lock_preserves_oversized_temp_and_tombstone_unread(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        candidate_paths = (
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_LOCK_TEMP_PREFIX
                + "d" * 16
                + ".tmp",
            ),
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_LOCK_CLEANUP_PREFIX
                + "e" * 16
                + ".tmp",
            ),
        )
        oversized_byte_count = (
            len(included_files_module._INCLUDED_FILES_LOCK_CONTENT) + 1
        )
        original_identities: dict[str, tuple[int, int]] = {}
        for candidate_path in candidate_paths:
            with open(candidate_path, "wb") as candidate_file:
                candidate_file.truncate(oversized_byte_count)
            candidate_stat = os.lstat(candidate_path)
            original_identities[candidate_path] = (
                candidate_stat.st_dev,
                candidate_stat.st_ino,
            )

        with patch.object(
            included_files_module,
            "_read_included_lock_initialization_payload",
            side_effect=AssertionError(
                "oversized lock initialization payload was read"
            ),
        ) as payload_read:
            included_files_module._cleanup_included_lock_initialization_temporaries(
                self.godot_dir,
                project_identity,
            )

        payload_read.assert_not_called()
        for candidate_path in candidate_paths:
            with self.subTest(candidate_path=candidate_path):
                candidate_stat = os.lstat(candidate_path)
                self.assertEqual(
                    (candidate_stat.st_dev, candidate_stat.st_ino),
                    original_identities[candidate_path],
                )
                self.assertEqual(
                    candidate_stat.st_size,
                    oversized_byte_count,
                )

    def test_unknown_recovery_record_is_preserved_and_rejected(self) -> None:
        journal_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_JOURNAL_NAME,
        )
        unknown_content = b"user-owned recovery collision\n"
        with open(journal_path, "wb") as journal_file:
            journal_file.write(unknown_content)

        self._write("payload.txt", "payload")
        with self.assertRaisesRegex(
            OSError,
            "Invalid Included Files recovery record",
        ):
            self._converter(max_workers=1).convert_all()

        with open(journal_path, "rb") as journal_file:
            self.assertEqual(journal_file.read(), unknown_content)
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
        )
        os.unlink(journal_path)

    def test_oversized_stable_recovery_records_are_not_read_or_removed(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        for record_name in (
            included_files_module._INCLUDED_FILES_JOURNAL_NAME,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        ):
            with self.subTest(record_name=record_name):
                record_path = os.path.join(self.godot_dir, record_name)
                with open(record_path, "wb") as record_file:
                    record_file.truncate(65)
                original_stat = os.lstat(record_path)
                with (
                    patch.object(
                        included_files_module,
                        "_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES",
                        64,
                    ),
                    patch.object(
                        included_files_module,
                        "_read_included_recovery_record_payload",
                        side_effect=AssertionError(
                            "oversized recovery payload was read"
                        ),
                    ) as payload_read,
                    self.assertRaisesRegex(OSError, "canonical size limit"),
                ):
                    included_files_module._recover_included_output_set(
                        self.godot_dir,
                        project_identity,
                    )
                payload_read.assert_not_called()
                current_stat = os.lstat(record_path)
                self.assertEqual(
                    (current_stat.st_dev, current_stat.st_ino),
                    (original_stat.st_dev, original_stat.st_ino),
                )
                self.assertEqual(current_stat.st_size, 65)
                os.unlink(record_path)

    def test_oversized_canonical_recovery_temporaries_are_preserved_unread(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        temporary_paths = (
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "a" * 16
                + ".tmp",
            ),
            os.path.join(
                self.godot_dir,
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "b" * 16
                + ".tmp",
            ),
        )
        original_identities: dict[str, tuple[int, int]] = {}
        for temporary_path in temporary_paths:
            with open(temporary_path, "wb") as temporary_file:
                temporary_file.truncate(65)
            temporary_stat = os.lstat(temporary_path)
            original_identities[temporary_path] = (
                temporary_stat.st_dev,
                temporary_stat.st_ino,
            )

        with (
            patch.object(
                included_files_module,
                "_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES",
                64,
            ),
            patch.object(
                included_files_module,
                "_read_included_recovery_record_payload",
                side_effect=AssertionError(
                    "oversized recovery payload was read"
                ),
            ) as payload_read,
        ):
            cleaned, warnings = (
                included_files_module._cleanup_orphan_included_recovery_state(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(cleaned, 0)
        payload_read.assert_not_called()
        for temporary_path in temporary_paths:
            with self.subTest(temporary_path=temporary_path):
                self.assertTrue(
                    any(temporary_path in warning for warning in warnings)
                )
                temporary_stat = os.lstat(temporary_path)
                self.assertEqual(
                    (temporary_stat.st_dev, temporary_stat.st_ino),
                    original_identities[temporary_path],
                )
                self.assertEqual(temporary_stat.st_size, 65)

    def test_oversized_recovery_tombstone_is_preserved_unread(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        tombstone_path = included_files_module._included_cleanup_tombstone_path(
            os.path.join(self.godot_dir, "temporary-record"),
            "c" * 32,
            "journal-temporary-record",
            "journal",
            expect_directory=False,
        )
        with open(tombstone_path, "wb") as tombstone_file:
            tombstone_file.truncate(65)
        original_stat = os.lstat(tombstone_path)

        with (
            patch.object(
                included_files_module,
                "_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES",
                64,
            ),
            patch.object(
                included_files_module,
                "_read_included_recovery_record_payload",
                side_effect=AssertionError(
                    "oversized recovery payload was read"
                ),
            ) as payload_read,
        ):
            cleaned, warnings = (
                included_files_module._cleanup_orphan_included_recovery_state(
                    self.godot_dir,
                    project_identity,
                )
            )

        self.assertEqual(cleaned, 0)
        payload_read.assert_not_called()
        self.assertTrue(any(tombstone_path in warning for warning in warnings))
        current_stat = os.lstat(tombstone_path)
        self.assertEqual(
            (current_stat.st_dev, current_stat.st_ino),
            (original_stat.st_dev, original_stat.st_ino),
        )
        self.assertEqual(current_stat.st_size, 65)

    def test_generated_oversized_recovery_record_is_rejected_before_staging(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        destination_name = "oversized-recovery-record.json"
        temporary_prefix = ".oversized-recovery-record."
        original_names = set(os.listdir(self.godot_dir))

        with (
            patch.object(
                included_files_module,
                "_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES",
                64,
            ),
            self.assertRaisesRegex(
                OSError,
                "Generated Included Files recovery record.*size limit",
            ),
        ):
            included_files_module._publish_included_recovery_record(
                self.godot_dir,
                project_identity,
                filename=destination_name,
                temporary_prefix=temporary_prefix,
                payload={
                    "format_version": (
                        included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                    ),
                    "state": "x" * 128,
                },
            )

        self.assertEqual(set(os.listdir(self.godot_dir)), original_names)

    def test_changed_generation_size_preflight_precedes_payload_staging(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")

        with (
            patch.object(
                included_files_module,
                "_INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES",
                1024,
            ),
            patch.object(
                included_files_module,
                "_create_included_output_stage",
            ) as create_stage,
            patch.object(
                included_files_module,
                "_prepare_included_registry_directory",
            ) as prepare_registry,
            patch.object(
                included_files_module,
                "_publish_included_recovery_record",
            ) as publish_record,
            self.assertRaisesRegex(
                OSError,
                "preflight failed before payload staging",
            ),
        ):
            converter.convert_all()

        create_stage.assert_not_called()
        prepare_registry.assert_not_called()
        publish_record.assert_not_called()
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_compact_tree_parser_is_strict_bounded_and_deterministic(
        self,
    ) -> None:
        snapshot = self._recovery_cleanup_snapshot("nested/payload.bin")
        compact_payload = (
            included_files_module._included_compact_tree_snapshot_payload(
                snapshot
            )
        )
        self.assertEqual(
            included_files_module._included_tree_snapshot_from_payload(
                compact_payload,
                "compact test tree",
                format_version=(
                    included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                ),
            ),
            snapshot,
        )
        record_payload = {
            "format_version": (
                included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION
            ),
            "state": "test",
            "tree": compact_payload,
        }
        content = included_files_module._included_recovery_record_content(
            record_payload
        )
        self.assertEqual(
            content,
            included_files_module._included_recovery_record_content(
                json.loads(content.decode("utf-8"))
            ),
        )
        self.assertNotIn(b"\n  ", content)

        malformed_payloads: list[list[object]] = []
        extra_column = json.loads(json.dumps(compact_payload))
        extra_column[1][0].append(None)
        malformed_payloads.append(extra_column)
        unknown_kind = json.loads(json.dumps(compact_payload))
        unknown_kind[1][0][1] = "directory"
        malformed_payloads.append(unknown_kind)
        short_integer = json.loads(json.dumps(compact_payload))
        short_integer[1][0][2][0] = "0" * 15
        malformed_payloads.append(short_integer)
        duplicate_path = json.loads(json.dumps(compact_payload))
        duplicate_path[1].append(list(duplicate_path[1][0]))
        malformed_payloads.append(duplicate_path)
        unsorted_paths = json.loads(json.dumps(compact_payload))
        unsorted_paths[1].reverse()
        malformed_payloads.append(unsorted_paths)

        for index, malformed_payload in enumerate(malformed_payloads):
            with (
                self.subTest(case=index),
                self.assertRaises(OSError),
            ):
                included_files_module._included_tree_snapshot_from_payload(
                    malformed_payload,
                    "compact test tree",
                    format_version=(
                        included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                    ),
                )

        with (
            patch.object(
                included_files_module,
                "_INCLUDED_FILES_RECOVERY_MAX_TREE_ENTRIES",
                len(snapshot.entries) - 1,
            ),
            self.assertRaisesRegex(OSError, "too many entries"),
        ):
            included_files_module._included_tree_snapshot_from_payload(
                compact_payload,
                "compact test tree",
                format_version=(
                    included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION
                ),
            )

    def test_changed_ten_thousand_entry_preflight_stays_below_cap(
        self,
    ) -> None:
        logical_paths = tuple(
            f"entry-{index:05d}.txt" for index in range(10_000)
        )
        assignments = plan_included_file_paths(logical_paths)
        receipts = {
            path: (
                1,
                included_files_module._INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256,
            )
            for path in logical_paths
        }
        registry_content = render_included_file_registry(
            assignments,
            set(logical_paths),
            receipts,
        ).encode("utf-8")
        assigned_byte_counts = {
            assignment.assigned_output_path: 1
            for assignment in assignments
        }
        project_identity = (1, 2)
        (
            _stage_identity,
            _container_snapshot,
            previous_root_snapshot,
            _registry_identity,
            _registry_mode,
        ) = included_files_module._included_preflight_placeholder_snapshots(
            project_identity,
            assigned_byte_counts,
            registry_content,
        )
        previous_registry_snapshot = (
            included_files_module._IncludedRegistrySnapshot(
                directory_identity=(1, 10),
                file_identity=(1, 11),
                file_mode=0o600,
                content=registry_content,
            )
        )

        first_sizes = (
            included_files_module._preflight_included_recovery_record_sizes(
                self.godot_dir,
                project_identity,
                assigned_byte_counts,
                registry_content,
                previous_root_snapshot,
                previous_registry_snapshot,
            )
        )
        second_sizes = (
            included_files_module._preflight_included_recovery_record_sizes(
                self.godot_dir,
                project_identity,
                assigned_byte_counts,
                registry_content,
                previous_root_snapshot,
                previous_registry_snapshot,
            )
        )
        expected_sizes = included_files_module._IncludedRecoveryRecordSizes(
            journal_bytes=13_865_860,
            commit_bytes=13_866_493,
        )
        self.assertEqual(first_sizes, expected_sizes)
        self.assertEqual(second_sizes, expected_sizes)
        self.assertLess(
            expected_sizes.commit_bytes,
            included_files_module._INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )

    def test_ten_thousand_entry_compact_records_publish_and_recover_below_cap(
        self,
    ) -> None:
        entry_count = 10_000
        for index in range(entry_count):
            with open(
                os.path.join(
                    self.datafiles_dir,
                    f"entry-{index:05d}.txt",
                ),
                "wb",
            ) as source_file:
                source_file.write(b"x")

        captured_sizes: (
            included_files_module._IncludedRecoveryRecordSizes | None
        ) = None
        original_commit = included_files_module._commit_included_output_set

        def capture_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal captured_sizes
            captured_sizes = transaction.recovery_record_sizes
            return original_commit(
                project_path,
                transaction,
                conversion_running,
            )

        def interrupt_after_commit(phase: str) -> None:
            if phase == "generation-committed":
                raise OSError("simulated committed interruption")

        with (
            patch.object(
                included_files_module,
                "_commit_included_output_set",
                side_effect=capture_commit,
            ),
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=interrupt_after_commit,
            ),
            self.assertRaisesRegex(
                OSError,
                "simulated committed interruption",
            ),
        ):
            self._converter(max_workers=4).convert_all()

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = included_files_module._read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = included_files_module._read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed generation did not retain both records")
        self.assertEqual(
            journal_record[1]["format_version"],
            included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        )
        self.assertEqual(
            commit_record[1]["format_version"],
            included_files_module._INCLUDED_FILES_RECOVERY_FORMAT_VERSION,
        )
        actual_sizes = included_files_module._IncludedRecoveryRecordSizes(
            journal_bytes=os.path.getsize(journal_path),
            commit_bytes=os.path.getsize(commit_path),
        )
        self.assertEqual(captured_sizes, actual_sizes)
        self.assertEqual(
            actual_sizes,
            included_files_module._IncludedRecoveryRecordSizes(
                journal_bytes=8_138_698,
                commit_bytes=8_139_331,
            ),
        )
        self.assertLess(
            actual_sizes.journal_bytes,
            included_files_module._INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )
        self.assertLess(
            actual_sizes.commit_bytes,
            included_files_module._INCLUDED_FILES_RECOVERY_RECORD_MAX_BYTES,
        )

        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            included_files_module._release_included_project_lock(
                project_lock
            )
        self.assertIsNotNone(recovery_message)
        self.assertEqual(
            len(
                os.listdir(
                    os.path.join(self.godot_dir, "included_files")
                )
            ),
            entry_count,
        )
        with open(
            os.path.join(
                self.godot_dir,
                "included_files",
                "entry-00000.txt",
            ),
            "rb",
        ) as output_file:
            self.assertEqual(output_file.read(), b"x")
        self._assert_no_transaction_debris()

    def test_recovery_record_staging_syncs_parent_before_durable_phase(
        self,
    ) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        events: list[tuple[str, str]] = []
        original_sync = included_files_module._sync_included_directory

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            events.append(("sync", path))
            original_sync(path, expected_identity)

        def trace_phase(phase: str) -> None:
            events.append(("phase", phase))

        with (
            patch.object(
                included_files_module,
                "_sync_included_directory",
                side_effect=trace_sync,
            ),
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=trace_phase,
            ),
        ):
            included_files_module._publish_included_recovery_record(
                self.godot_dir,
                project_identity,
                filename="test-recovery-record.json",
                temporary_prefix=".test-recovery-record.",
                payload={"state": "test"},
                staged_phase="journal-record-staged",
            )

        self.assertEqual(
            events,
            [
                ("sync", self.godot_dir),
                ("phase", "journal-record-staged"),
                ("sync", self.godot_dir),
            ],
        )

    def test_staged_tree_directories_sync_bottom_up_before_commit_record(
        self,
    ) -> None:
        self._write("level-one/level-two/payload.txt", "payload")
        events: list[tuple[str, str]] = []
        original_sync = included_files_module._sync_included_directory

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            events.append(("sync", os.path.abspath(path)))
            original_sync(path, expected_identity)

        def trace_phase(phase: str) -> None:
            events.append(("phase", phase))

        with (
            patch.object(
                included_files_module,
                "_sync_included_directory",
                side_effect=trace_sync,
            ),
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=trace_phase,
            ),
        ):
            self._converter(max_workers=1).convert_all()

        commit_record_index = events.index(("phase", "commit-record-staged"))
        root_path = os.path.join(self.godot_dir, "included_files")
        tree_syncs = [
            event
            for event in events[:commit_record_index]
            if event[0] == "sync"
            and (
                event[1] == root_path
                or event[1].startswith(root_path + os.sep)
            )
        ]
        self.assertEqual(
            tree_syncs,
            [
                (
                    "sync",
                    os.path.join(root_path, "level-one", "level-two"),
                ),
                ("sync", os.path.join(root_path, "level-one")),
                ("sync", root_path),
            ],
        )

    def test_subprocess_interruption_recovers_every_publication_boundary(
        self,
    ) -> None:
        phases = (
            ("journal-record-staged", False),
            ("journal-prepared", False),
            ("previous-root-backed-up", False),
            ("new-root-published", False),
            ("previous-registry-backed-up", False),
            ("new-registry-published", False),
            ("commit-record-staged", False),
            ("generation-committed", True),
            ("journal-removed", True),
            ("commit-marker-removed", True),
        )
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path, requested_phase = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""

        def pair_snapshot(project_path: str) -> tuple[int, dict[str, bytes], int, bytes]:
            root_path = os.path.join(project_path, "included_files")
            registry_path = os.path.join(
                project_path,
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

        for phase, committed in phases:
            with self.subTest(phase=phase):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()
                    previous_pair = pair_snapshot(godot_path)

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    environment = os.environ.copy()
                    existing_python_path = environment.get("PYTHONPATH")
                    environment["PYTHONPATH"] = (
                        PROJECT_ROOT
                        if not existing_python_path
                        else PROJECT_ROOT + os.pathsep + existing_python_path
                    )
                    interrupted = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            interruption_script,
                            gm_path,
                            godot_path,
                            phase,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        interrupted.returncode,
                        86,
                        interrupted.stdout + interrupted.stderr,
                    )
                    if phase == "journal-record-staged":
                        self.assertFalse(
                            os.path.lexists(
                                os.path.join(
                                    godot_path,
                                    included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                                )
                            )
                        )
                        journal_temporaries = [
                            name
                            for name in os.listdir(godot_path)
                            if name.startswith(
                                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                            )
                            and name.endswith(".tmp")
                        ]
                        self.assertEqual(len(journal_temporaries), 1)
                        stages = [
                            name
                            for name in os.listdir(godot_path)
                            if name.startswith(
                                included_files_module._INCLUDED_FILES_STAGE_PREFIX
                            )
                            and name.endswith(".stage")
                        ]
                        self.assertEqual(len(stages), 1)
                        self.assertNotEqual(
                            os.listdir(os.path.join(godot_path, stages[0])),
                            [],
                        )

                    project_identity = (
                        included_files_module._ensure_included_output_project_root(
                            godot_path
                        )
                    )
                    project_lock = (
                        included_files_module._acquire_included_project_lock(
                            godot_path,
                            project_identity,
                        )
                    )
                    try:
                        recovery_message = (
                            included_files_module._recover_included_output_set(
                                godot_path,
                                project_identity,
                            )
                        )
                    finally:
                        included_files_module._release_included_project_lock(
                            project_lock
                        )
                    if phase == "journal-record-staged":
                        self.assertIsNotNone(recovery_message)
                        assert recovery_message is not None
                        self.assertIn(
                            "durable journal temporary",
                            recovery_message,
                        )

                    recovered_pair = pair_snapshot(godot_path)
                    if committed:
                        self.assertEqual(
                            recovered_pair[1],
                            {"new.txt": b"new generation"},
                        )
                        self.assertIn(b'"logical_path": "new.txt"', recovered_pair[3])
                        self.assertNotIn(b'"logical_path": "old.txt"', recovered_pair[3])
                    else:
                        self.assertEqual(recovered_pair, previous_pair)

                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

                    converter.convert_all()
                    self.assertEqual(
                        pair_snapshot(godot_path)[1],
                        {"new.txt": b"new generation"},
                    )

    def test_format_v1_records_recover_at_every_publication_boundary(
        self,
    ) -> None:
        phases = (
            ("journal-record-staged", False),
            ("journal-prepared", False),
            ("previous-root-backed-up", False),
            ("new-root-published", False),
            ("previous-registry-backed-up", False),
            ("new-registry-published", False),
            ("commit-record-staged", False),
            ("generation-committed", True),
            ("journal-removed", True),
            ("commit-marker-removed", True),
        )
        for phase, committed in phases:
            with (
                self.subTest(phase=phase),
                tempfile.TemporaryDirectory() as gm_path,
                tempfile.TemporaryDirectory() as godot_path,
            ):
                datafiles_path = os.path.join(gm_path, "datafiles")
                os.mkdir(datafiles_path)
                old_source_path = os.path.join(datafiles_path, "old.txt")
                with open(old_source_path, "wb") as source_file:
                    source_file.write(b"old generation")
                converter = IncludedFilesConverter(
                    gm_path,
                    godot_path,
                    log_callback=lambda _message: None,
                    progress_callback=lambda _value: None,
                    conversion_running=lambda: True,
                    max_workers=1,
                )
                converter.convert_all()
                os.unlink(old_source_path)
                with open(
                    os.path.join(datafiles_path, "new.txt"),
                    "wb",
                ) as source_file:
                    source_file.write(b"new generation")

                interrupted = self._run_interrupted_conversion(
                    phase,
                    gm_path=gm_path,
                    godot_path=godot_path,
                )
                self.assertEqual(
                    interrupted.returncode,
                    86,
                    interrupted.stdout + interrupted.stderr,
                )
                project_identity = (
                    included_files_module._ensure_included_output_project_root(
                        godot_path
                    )
                )
                rewritten = self._rewrite_included_recovery_records_as_v1(
                    godot_path,
                    project_identity,
                )
                if phase == "commit-marker-removed":
                    self.assertEqual(rewritten, 0)
                else:
                    self.assertGreaterEqual(rewritten, 1)

                project_lock = (
                    included_files_module._acquire_included_project_lock(
                        godot_path,
                        project_identity,
                    )
                )
                try:
                    included_files_module._recover_included_output_set(
                        godot_path,
                        project_identity,
                    )
                finally:
                    included_files_module._release_included_project_lock(
                        project_lock
                    )

                root_path = os.path.join(godot_path, "included_files")
                observed_files: dict[str, bytes] = {}
                for directory, _subdirectories, filenames in os.walk(
                    root_path
                ):
                    for filename in filenames:
                        file_path = os.path.join(directory, filename)
                        relative_path = os.path.relpath(
                            file_path,
                            root_path,
                        ).replace(os.sep, "/")
                        with open(file_path, "rb") as output_file:
                            observed_files[relative_path] = output_file.read()
                self.assertEqual(
                    observed_files,
                    (
                        {"new.txt": b"new generation"}
                        if committed
                        else {"old.txt": b"old generation"}
                    ),
                )
                self.assertEqual(
                    _included_files_transaction_debris(godot_path),
                    (),
                )

    def test_first_publication_rollback_is_idempotent_after_registry_publish(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)
        self.assertFalse(os.path.lexists(root_path))
        self.assertFalse(os.path.lexists(registry_path))
        self.assertFalse(os.path.lexists(registry_directory))

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "new-registry-published":
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        interrupted = subprocess.run(
            (
                sys.executable,
                "-c",
                interruption_script,
                self.gm_dir,
                self.godot_dir,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertTrue(os.path.isdir(root_path))
        self.assertTrue(os.path.isfile(registry_path))

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )

        def recover() -> str | None:
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

        def assert_absent_generation() -> None:
            self.assertFalse(os.path.lexists(root_path))
            self.assertFalse(os.path.lexists(registry_path))
            self.assertFalse(os.path.lexists(registry_directory))
            self._assert_no_transaction_debris()
            self.assertEqual(
                set(os.listdir(self.godot_dir)),
                {included_files_module._INCLUDED_FILES_LOCK_NAME},
            )

        first_recovery = recover()
        self.assertIsNotNone(first_recovery)
        self.assertIn("rolled back", first_recovery or "")
        assert_absent_generation()

        self.assertIsNone(recover())
        assert_absent_generation()

    def test_first_publication_recovers_durable_prepared_journal_temporary(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        root_path = os.path.join(self.godot_dir, "included_files")
        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        registry_directory = os.path.dirname(registry_path)

        interrupted = self._run_interrupted_conversion(
            "journal-record-staged"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertFalse(os.path.lexists(root_path))
        self.assertTrue(os.path.isdir(registry_directory))
        self.assertFalse(os.path.lexists(registry_path))
        self.assertEqual(
            len(
                [
                    name
                    for name in os.listdir(self.godot_dir)
                    if name.startswith(
                        included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                ]
            ),
            1,
        )

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            included_files_module._release_included_project_lock(project_lock)

        self.assertIsNotNone(recovery_message)
        self.assertIn("durable journal temporary", recovery_message or "")
        self.assertFalse(os.path.lexists(root_path))
        self.assertFalse(os.path.lexists(registry_directory))
        self._assert_no_transaction_debris()

    def test_first_publication_journal_temporary_preserves_appeared_registry(
        self,
    ) -> None:
        self._write("first.txt", "first generation")
        interrupted = self._run_interrupted_conversion(
            "journal-record-staged"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        journal_temporary_path = os.path.join(
            self.godot_dir,
            next(
                name
                for name in os.listdir(self.godot_dir)
                if name.startswith(
                    included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                )
                and name.endswith(".tmp")
            ),
        )
        journal_temporary_stat = os.lstat(journal_temporary_path)
        journal_temporary_identity = (
            journal_temporary_stat.st_dev,
            journal_temporary_stat.st_ino,
        )
        with open(journal_temporary_path, "rb") as journal_temporary_file:
            journal_temporary_content = journal_temporary_file.read()

        registry_path = os.path.join(
            self.godot_dir,
            INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
        )
        unknown_registry_content = b"user-owned registry collision\n"
        with open(registry_path, "wb") as registry_file:
            registry_file.write(unknown_registry_content)
        unknown_registry_stat = os.lstat(registry_path)
        unknown_registry_identity = (
            unknown_registry_stat.st_dev,
            unknown_registry_stat.st_ino,
        )

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            recovery_message = (
                included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            )
        finally:
            included_files_module._release_included_project_lock(project_lock)

        self.assertIn(
            "ambiguous Included Files journal temporary was preserved",
            recovery_message or "",
        )
        current_journal_temporary_stat = os.lstat(journal_temporary_path)
        self.assertEqual(
            (
                current_journal_temporary_stat.st_dev,
                current_journal_temporary_stat.st_ino,
            ),
            journal_temporary_identity,
        )
        with open(journal_temporary_path, "rb") as journal_temporary_file:
            self.assertEqual(
                journal_temporary_file.read(),
                journal_temporary_content,
            )
        current_registry_stat = os.lstat(registry_path)
        self.assertEqual(
            (current_registry_stat.st_dev, current_registry_stat.st_ino),
            unknown_registry_identity,
        )
        with open(registry_path, "rb") as registry_file:
            self.assertEqual(registry_file.read(), unknown_registry_content)

    def test_restart_rollback_syncs_registry_before_journal_retirement(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        self._converter(max_workers=1).convert_all()
        previous_pair = self._pair_snapshot()
        registry_directory = os.path.join(self.godot_dir, "gm2godot")
        registry_directory_stat = os.lstat(registry_directory)
        registry_directory_identity = (
            registry_directory_stat.st_dev,
            registry_directory_stat.st_ino,
        )

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        interrupted = self._run_interrupted_conversion(
            "new-registry-published"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )

        events: list[tuple[str, str, tuple[int, int] | None]] = []
        original_sync = included_files_module._sync_included_directory
        original_remove = included_files_module._remove_included_recovery_record

        def trace_sync(path: str, expected_identity: tuple[int, int]) -> None:
            if os.path.abspath(path) == registry_directory:
                events.append(("sync", path, expected_identity))
            original_sync(path, expected_identity)

        def trace_remove(
            path: str,
            identity: tuple[int, int],
            project_path: str,
            project_identity: tuple[int, int],
        ) -> None:
            if os.path.basename(path) == (
                included_files_module._INCLUDED_FILES_JOURNAL_NAME
            ):
                events.append(("remove", path, identity))
            original_remove(
                path,
                identity,
                project_path,
                project_identity,
            )

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        with (
            patch.object(
                included_files_module,
                "_sync_included_directory",
                side_effect=trace_sync,
            ),
            patch.object(
                included_files_module,
                "_remove_included_recovery_record",
                side_effect=trace_remove,
            ),
        ):
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                recovery_message = (
                    included_files_module._recover_included_output_set(
                        self.godot_dir,
                        project_identity,
                    )
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

        self.assertIn("rolled back", recovery_message or "")
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(events[0], ("sync", registry_directory, registry_directory_identity))
        self.assertEqual(events[1][0], "remove")
        self._assert_no_transaction_debris()

    def test_committed_cleanup_recovery_is_idempotent_at_every_owned_boundary(
        self,
    ) -> None:
        boundaries = (
            ("root-backup", "quarantined", None),
            ("root-backup", "removed", None),
            ("registry-backup", "quarantined", None),
            ("registry-backup", "removed", None),
            ("stage", "quarantined", None),
            ("stage", "removed", None),
            (
                "record",
                "quarantined",
                included_files_module._INCLUDED_FILES_JOURNAL_NAME,
            ),
            (
                "record",
                "removed",
                included_files_module._INCLUDED_FILES_JOURNAL_NAME,
            ),
            (
                "record",
                "quarantined",
                included_files_module._INCLUDED_FILES_COMMIT_NAME,
            ),
            (
                "record",
                "removed",
                included_files_module._INCLUDED_FILES_COMMIT_NAME,
            ),
        )
        commit_interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        cleanup_interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module

godot_path, requested_role, requested_action, requested_path = sys.argv[1:]
matches = 0

def stop_after_phase(phase: str) -> None:
    global matches
    parts = phase.split(":", 3)
    if len(parts) != 4 or parts[0] != "cleanup":
        return
    _cleanup, role, relative_path, action = parts
    if role != requested_role or action != requested_action:
        return
    if requested_path != "-" and relative_path != requested_path:
        return
    matches += 1
    if matches == 1:
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
project_identity = included_files_module._ensure_included_output_project_root(
    godot_path
)
project_lock = included_files_module._acquire_included_project_lock(
    godot_path,
    project_identity,
)
try:
    included_files_module._recover_included_output_set(
        godot_path,
        project_identity,
    )
finally:
    included_files_module._release_included_project_lock(project_lock)
"""

        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )

        def pair_snapshot(
            project_path: str,
        ) -> tuple[int, dict[str, bytes], int, bytes]:
            root_path = os.path.join(project_path, "included_files")
            registry_path = os.path.join(
                project_path,
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

        def recover(project_path: str) -> str | None:
            project_identity = (
                included_files_module._ensure_included_output_project_root(
                    project_path
                )
            )
            project_lock = included_files_module._acquire_included_project_lock(
                project_path,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    project_path,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

        for role, action, relative_path in boundaries:
            label = relative_path or role
            with self.subTest(role=role, action=action, path=label):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    committed = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            commit_interruption_script,
                            gm_path,
                            godot_path,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        committed.returncode,
                        86,
                        committed.stdout + committed.stderr,
                    )
                    committed_pair = pair_snapshot(godot_path)
                    self.assertEqual(
                        committed_pair[1],
                        {"new.txt": b"new generation"},
                    )

                    interrupted_cleanup = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            cleanup_interruption_script,
                            godot_path,
                            role,
                            action,
                            relative_path or "-",
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    self.assertEqual(
                        interrupted_cleanup.returncode,
                        86,
                        interrupted_cleanup.stdout
                        + interrupted_cleanup.stderr,
                    )

                    recover(godot_path)
                    self.assertEqual(
                        pair_snapshot(godot_path),
                        committed_pair,
                    )
                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

                    self.assertIsNone(recover(godot_path))
                    self.assertEqual(
                        pair_snapshot(godot_path),
                        committed_pair,
                    )
                    self.assertEqual(
                        _included_files_transaction_debris(godot_path),
                        (),
                    )

    def test_committed_cleanup_preserves_unknown_content_inside_recorded_trees(
        self,
    ) -> None:
        locations = ("root-backup", "stage")

        for location in locations:
            with self.subTest(location=location):
                with (
                    tempfile.TemporaryDirectory() as gm_path,
                    tempfile.TemporaryDirectory() as godot_path,
                ):
                    datafiles_path = os.path.join(gm_path, "datafiles")
                    os.mkdir(datafiles_path)
                    old_source_path = os.path.join(datafiles_path, "old.txt")
                    with open(old_source_path, "wb") as source_file:
                        source_file.write(b"old generation")
                    converter = IncludedFilesConverter(
                        gm_path,
                        godot_path,
                        log_callback=lambda _message: None,
                        progress_callback=lambda _value: None,
                        conversion_running=lambda: True,
                        max_workers=1,
                    )
                    converter.convert_all()

                    unrelated_path = os.path.join(
                        godot_path,
                        "user-project-sentinel.txt",
                    )
                    with open(unrelated_path, "wb") as unrelated_file:
                        unrelated_file.write(b"unrelated user content\n")
                    unrelated_identity = os.lstat(unrelated_path).st_ino

                    os.unlink(old_source_path)
                    with open(
                        os.path.join(datafiles_path, "new.txt"),
                        "wb",
                    ) as source_file:
                        source_file.write(b"new generation")

                    class CommitInterrupted(BaseException):
                        pass

                    def stop_after_commit(phase: str) -> None:
                        if phase == "generation-committed":
                            raise CommitInterrupted()

                    with patch.object(
                        included_files_module,
                        "_after_included_transaction_phase",
                        side_effect=stop_after_commit,
                    ):
                        with self.assertRaises(CommitInterrupted):
                            converter.convert_all()

                    project_identity = (
                        included_files_module._ensure_included_output_project_root(
                            godot_path
                        )
                    )
                    journal_path = os.path.join(
                        godot_path,
                        included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                    )
                    journal_record = (
                        included_files_module._read_included_recovery_record(
                            journal_path,
                            project_identity,
                        )
                    )
                    if journal_record is None:
                        self.fail("committed interruption did not preserve its journal")
                    _journal_identity, journal_payload = journal_record
                    journal = (
                        included_files_module._included_recovery_journal_from_payload(
                            godot_path,
                            project_identity,
                            journal_payload,
                        )
                    )
                    if location == "root-backup":
                        container_path = journal.root_backup_path
                        container_snapshot = (
                            journal.transaction.previous_root_snapshot
                        )
                        cleanup_role = "root-backup"
                    else:
                        container_path = journal.transaction.stage_container_path
                        container_snapshot = (
                            journal.transaction.staged_container_snapshot
                        )
                        cleanup_role = "stage"

                    user_path = os.path.join(
                        container_path,
                        "user-preserved.txt",
                    )
                    with open(user_path, "wb") as user_file:
                        user_file.write(b"injected user content\n")
                    user_identity = os.lstat(user_path).st_ino

                    final_root_path = os.path.join(
                        godot_path,
                        "included_files",
                    )
                    final_registry_path = os.path.join(
                        godot_path,
                        INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                    )
                    final_root_identity = os.lstat(final_root_path).st_ino
                    final_registry_identity = os.lstat(final_registry_path).st_ino
                    with open(final_registry_path, "rb") as registry_file:
                        final_registry_content = registry_file.read()

                    project_lock = (
                        included_files_module._acquire_included_project_lock(
                            godot_path,
                            project_identity,
                        )
                    )
                    try:
                        recovery_message = (
                            included_files_module._recover_included_output_set(
                                godot_path,
                                project_identity,
                            )
                        )
                    finally:
                        included_files_module._release_included_project_lock(
                            project_lock
                        )

                    self.assertIsNotNone(recovery_message)
                    self.assertIn("preserved", recovery_message or "")
                    tombstone_path = (
                        included_files_module._included_cleanup_tombstone_path(
                            container_path,
                            journal.transaction_id,
                            cleanup_role,
                            ".",
                            expect_directory=True,
                        )
                    )
                    preserved_containers = [
                        candidate
                        for candidate in (container_path, tombstone_path)
                        if os.path.isdir(candidate)
                    ]
                    self.assertEqual(len(preserved_containers), 1)
                    preserved_container = preserved_containers[0]
                    preserved_user_path = os.path.join(
                        preserved_container,
                        "user-preserved.txt",
                    )
                    self.assertEqual(
                        os.lstat(preserved_user_path).st_ino,
                        user_identity,
                    )
                    with open(preserved_user_path, "rb") as user_file:
                        self.assertEqual(
                            user_file.read(),
                            b"injected user content\n",
                        )
                    for entry in container_snapshot.entries:
                        self.assertFalse(
                            os.path.lexists(
                                os.path.join(
                                    preserved_container,
                                    *entry.relative_path.split("/"),
                                )
                            ),
                            entry.relative_path,
                        )

                    self.assertEqual(
                        os.lstat(final_root_path).st_ino,
                        final_root_identity,
                    )
                    with open(
                        os.path.join(final_root_path, "new.txt"),
                        "rb",
                    ) as output_file:
                        self.assertEqual(output_file.read(), b"new generation")
                    self.assertFalse(
                        os.path.lexists(os.path.join(final_root_path, "old.txt"))
                    )
                    self.assertEqual(
                        os.lstat(final_registry_path).st_ino,
                        final_registry_identity,
                    )
                    with open(final_registry_path, "rb") as registry_file:
                        self.assertEqual(
                            registry_file.read(),
                            final_registry_content,
                        )
                    self.assertEqual(
                        os.lstat(unrelated_path).st_ino,
                        unrelated_identity,
                    )
                    with open(unrelated_path, "rb") as unrelated_file:
                        self.assertEqual(
                            unrelated_file.read(),
                            b"unrelated user content\n",
                        )
                    self.assertFalse(os.path.lexists(journal_path))
                    self.assertFalse(
                        os.path.lexists(
                            os.path.join(
                                godot_path,
                                included_files_module._INCLUDED_FILES_COMMIT_NAME,
                            )
                        )
                    )

    def test_marker_only_committed_recovery_uses_embedded_cleanup_manifest(
        self,
    ) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
IncludedFilesConverter(
    gm_path,
    godot_path,
    log_callback=lambda _message: None,
    progress_callback=lambda _value: None,
    conversion_running=lambda: True,
    max_workers=1,
).convert_all()
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )
        interrupted = subprocess.run(
            (
                sys.executable,
                "-c",
                interruption_script,
                self.gm_dir,
                self.godot_dir,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )

        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = included_files_module._read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = included_files_module._read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        _journal_identity, journal_payload = journal_record
        _commit_identity, commit_payload = commit_record
        journal = included_files_module._included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        _marker, embedded_journal = (
            included_files_module._included_commit_marker_and_journal_from_payload(
                self.godot_dir,
                commit_payload,
                project_identity,
            )
        )
        self.assertEqual(embedded_journal, journal)
        self.assertTrue(os.path.lexists(journal.root_backup_path))
        self.assertTrue(os.path.lexists(journal.registry_backup_path))
        self.assertTrue(
            os.path.lexists(journal.transaction.stage_container_path)
        )
        committed_pair = self._pair_snapshot()
        self.assertEqual(
            committed_pair[1],
            {"new.txt": b"new generation"},
        )
        self.assertIn(b'"logical_path": "new.txt"', committed_pair[3])
        self.assertNotIn(b'"logical_path": "old.txt"', committed_pair[3])

        os.unlink(journal_path)
        included_files_module._sync_included_directory(
            self.godot_dir,
            project_identity,
        )

        def recover() -> str | None:
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

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
        self._assert_no_transaction_debris()

        self.assertIsNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self._assert_no_transaction_debris()

    def test_canonical_tampered_commit_receipts_are_rejected_without_cleanup(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        journal_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_JOURNAL_NAME,
        )
        commit_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        )
        journal_record = included_files_module._read_included_recovery_record(
            journal_path,
            project_identity,
        )
        commit_record = included_files_module._read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if journal_record is None or commit_record is None:
            self.fail("committed interruption did not preserve both records")
        _journal_identity, journal_payload = journal_record
        _commit_identity, commit_payload = commit_record
        journal = included_files_module._included_recovery_journal_from_payload(
            self.godot_dir,
            project_identity,
            journal_payload,
        )
        committed_pair = self._pair_snapshot()
        self.assertEqual(committed_pair[1], {"new.txt": b"new generation"})

        os.unlink(journal_path)
        included_files_module._sync_included_directory(
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
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
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
                    included_files_module._included_recovery_record_content(
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
            included_files_module._included_recovery_record_content(commit_payload)
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

    def test_modeled_windows_commit_marker_rejects_forged_embedded_path_before_io(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        commit_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        )
        commit_record = included_files_module._read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if commit_record is None:
            self.fail("committed interruption did not preserve its commit marker")
        _commit_identity, commit_payload = commit_record
        forged_payload = json.loads(json.dumps(commit_payload))
        embedded_journal = forged_payload["recovery_journal"]
        staged_snapshot = embedded_journal["staged_container_snapshot"]
        if embedded_journal["format_version"] == 1:
            staged_entries = staged_snapshot["entries"]
            forged_entry = next(
                entry for entry in staged_entries if entry["kind"] == "file"
            )
            forged_entry["relative_path"] = "safe/D:evil"
        else:
            staged_entries = staged_snapshot[1]
            forged_entry = next(
                entry for entry in staged_entries if entry[1] == "f"
            )
            forged_entry[0] = "safe/D:evil"
        forged_payload["recovery_journal_sha256"] = hashlib.sha256(
            included_files_module._included_recovery_record_content(
                embedded_journal
            )
        ).hexdigest()
        forged_content = (
            included_files_module._included_recovery_record_content(
                forged_payload
            )
        )
        self.assertEqual(
            forged_content,
            included_files_module._included_recovery_record_content(
                json.loads(forged_content.decode("utf-8"))
            ),
        )

        with (
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(included_files_module.os, "stat") as stat_call,
            patch.object(included_files_module.os, "lstat") as lstat_call,
            patch.object(
                included_files_module,
                "_cleanup_recorded_included_tree",
            ) as cleanup_tree,
            patch.object(
                included_files_module,
                "_move_exact_included_file",
            ) as move_file,
            patch.object(
                included_files_module,
                "_move_exact_included_directory",
            ) as move_directory,
            self.assertRaisesRegex(OSError, "Windows-ambiguous"),
        ):
            included_files_module._included_commit_marker_and_journal_from_payload(
                self.godot_dir,
                forged_payload,
                project_identity,
            )
        stat_call.assert_not_called()
        lstat_call.assert_not_called()
        cleanup_tree.assert_not_called()
        move_file.assert_not_called()
        move_directory.assert_not_called()

    def test_modeled_windows_recovery_paths_reject_ambiguous_components_before_io(
        self,
    ) -> None:
        cases = (
            "safe/D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "con.txt",
            "AUX.bin",
            "NUL",
            "COM1.dat",
            "LPT9",
        )
        cleanup_root = os.path.join(self.godot_dir, "modeled-cleanup-root")

        for relative_path in cases:
            with (
                self.subTest(relative_path=relative_path),
                patch.object(included_files_module.os, "name", "nt"),
                patch.object(included_files_module.os, "stat") as stat_call,
                patch.object(included_files_module.os, "lstat") as lstat_call,
                patch.object(
                    included_files_module,
                    "_move_exact_included_file",
                ) as move_file,
                patch.object(
                    included_files_module,
                    "_move_exact_included_directory",
                ) as move_directory,
                self.assertRaisesRegex(OSError, "Windows-ambiguous"),
            ):
                included_files_module._cleanup_recorded_included_tree(
                    cleanup_root,
                    self._recovery_cleanup_snapshot(relative_path),
                    (7, 8),
                    "modeled-windows-path",
                    "path-confinement-test",
                )
            lstat_call.assert_not_called()
            stat_call.assert_not_called()
            move_file.assert_not_called()
            move_directory.assert_not_called()

    @unittest.skipIf(os.name == "nt", "requires native POSIX path semantics")
    def test_posix_recovery_paths_keep_posix_valid_components(self) -> None:
        root_path = os.path.join(self.godot_dir, "posix-cleanup-root")
        cases = (
            "safe/D:evil",
            "D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "con.txt",
        )

        for relative_path in cases:
            with self.subTest(relative_path=relative_path):
                self.assertEqual(
                    included_files_module._included_recovery_relative_path(
                        relative_path
                    ),
                    relative_path,
                )
                reconstructed = (
                    included_files_module._included_recovery_tree_entry_path(
                        root_path,
                        relative_path,
                    )
                )
                self.assertEqual(
                    reconstructed,
                    os.path.abspath(
                        os.path.join(root_path, *relative_path.split("/"))
                    ),
                )
                self.assertEqual(
                    os.path.commonpath(
                        (os.path.abspath(root_path), reconstructed)
                    ),
                    os.path.abspath(root_path),
                )

    @unittest.skipUnless(os.name == "nt", "requires native Windows paths")
    def test_native_windows_recovery_paths_reject_before_io(self) -> None:
        cleanup_root = os.path.join(self.godot_dir, "native-cleanup-root")
        safe_path = included_files_module._included_recovery_tree_entry_path(
            cleanup_root,
            "safe/payload.txt",
        )
        self.assertEqual(
            safe_path,
            os.path.abspath(
                os.path.join(cleanup_root, "safe", "payload.txt")
            ),
        )

        for relative_path in (
            "safe/D:evil",
            "foo:bar",
            " leading.txt",
            "trailing.",
            "trailing ",
            "CON",
            "AUX.txt",
            "NUL",
            "COM1.bin",
            "LPT1",
        ):
            with (
                self.subTest(relative_path=relative_path),
                patch.object(included_files_module.os, "stat") as stat_call,
                patch.object(included_files_module.os, "lstat") as lstat_call,
                patch.object(
                    included_files_module,
                    "_move_exact_included_file",
                ) as move_file,
                patch.object(
                    included_files_module,
                    "_move_exact_included_directory",
                ) as move_directory,
                self.assertRaisesRegex(OSError, "Windows-ambiguous"),
            ):
                included_files_module._cleanup_recorded_included_tree(
                    cleanup_root,
                    self._recovery_cleanup_snapshot(relative_path),
                    (7, 8),
                    "native-windows-path",
                    "path-confinement-test",
                )
            lstat_call.assert_not_called()
            stat_call.assert_not_called()
            move_file.assert_not_called()
            move_directory.assert_not_called()

    def test_noncanonical_reserved_temporaries_are_preserved_and_nonblocking(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        commit_path = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_NAME,
        )
        commit_record = included_files_module._read_included_recovery_record(
            commit_path,
            project_identity,
        )
        if commit_record is None:
            self.fail("committed interruption did not preserve its commit marker")
        _commit_identity, commit_payload = commit_record
        canonical_commit_content = (
            included_files_module._included_recovery_record_content(commit_payload)
        )

        def recover() -> str | None:
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

        self.assertIsNotNone(recover())
        committed_pair = self._pair_snapshot()
        invalid_records = {
            (
                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "f" * 15
                + ".tmp"
            ): b"short reserved token\n",
            (
                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                + "f" * 17
                + ".tmp"
            ): b"long reserved token\n",
            (
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "g" * 16
                + ".tmp"
            ): b"non-hex reserved token\n",
            (
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "F" * 16
                + ".tmp"
            ): b"uppercase reserved token\n",
            (
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
                + "f" * 16
                + ".extra.tmp"
            ): b"extra reserved token material\n",
            (
                included_files_module._INCLUDED_FILES_STAGE_PREFIX
                + "user-owned.tmp"
            ): b"arbitrary reserved-prefix temporary\n",
        }
        invalid_identities: dict[str, tuple[int, int]] = {}
        for name, content in invalid_records.items():
            record_path = os.path.join(self.godot_dir, name)
            with open(record_path, "wb") as record_file:
                record_file.write(content)
            record_stat = os.lstat(record_path)
            invalid_identities[name] = (record_stat.st_dev, record_stat.st_ino)

        canonical_commit_temporary = os.path.join(
            self.godot_dir,
            included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX
            + "a" * 16
            + ".tmp",
        )
        with open(canonical_commit_temporary, "wb") as temporary_file:
            temporary_file.write(canonical_commit_content)

        recovery_message = recover()

        self.assertIsNotNone(recovery_message)
        self.assertIn("removed 1", recovery_message or "")
        self.assertFalse(os.path.lexists(canonical_commit_temporary))
        for name, expected_content in invalid_records.items():
            with self.subTest(preserved=name):
                record_path = os.path.join(self.godot_dir, name)
                record_stat = os.lstat(record_path)
                self.assertEqual(
                    (record_stat.st_dev, record_stat.st_ino),
                    invalid_identities[name],
                )
                with open(record_path, "rb") as record_file:
                    self.assertEqual(record_file.read(), expected_content)
        self.assertEqual(self._pair_snapshot(), committed_pair)

        self.assertIsNotNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)

    def test_temporary_record_cleanup_tombstones_resume_after_hard_exit(
        self,
    ) -> None:
        self._leave_committed_generation_recovery_records()
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        record_specs = (
            (
                "journal",
                included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                included_files_module._INCLUDED_FILES_JOURNAL_TEMP_PREFIX,
            ),
            (
                "commit",
                included_files_module._INCLUDED_FILES_COMMIT_NAME,
                included_files_module._INCLUDED_FILES_COMMIT_TEMP_PREFIX,
            ),
        )
        canonical_records: list[tuple[str, str, bytes]] = []
        for record_kind, stable_name, temporary_prefix in record_specs:
            record = included_files_module._read_included_recovery_record(
                os.path.join(self.godot_dir, stable_name),
                project_identity,
            )
            if record is None:
                self.fail(
                    "committed interruption did not preserve its "
                    + record_kind
                    + " record"
                )
            canonical_records.append(
                (
                    record_kind,
                    temporary_prefix,
                    included_files_module._included_recovery_record_content(
                        record[1]
                    ),
                )
            )

        def recover() -> str | None:
            project_lock = included_files_module._acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            try:
                return included_files_module._recover_included_output_set(
                    self.godot_dir,
                    project_identity,
                )
            finally:
                included_files_module._release_included_project_lock(
                    project_lock
                )

        committed_pair = self._pair_snapshot()
        self.assertIsNotNone(recover())
        self.assertEqual(self._pair_snapshot(), committed_pair)
        self._assert_no_transaction_debris()

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module

project_path, record_path, requested_phase = sys.argv[1:]
project_identity = included_files_module._ensure_included_output_project_root(
    project_path
)
project_lock = included_files_module._acquire_included_project_lock(
    project_path,
    project_identity,
)

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_files_module._after_included_transaction_phase = stop_after_phase
try:
    record_state = included_files_module._included_regular_file_state(
        record_path,
        expected_parent_identity=project_identity,
    )
    if record_state is None:
        os._exit(87)
    included_files_module._remove_included_recovery_record(
        record_path,
        record_state[0],
        project_path,
        project_identity,
    )
finally:
    included_files_module._release_included_project_lock(project_lock)
os._exit(88)
"""
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            PROJECT_ROOT
            if not existing_python_path
            else PROJECT_ROOT + os.pathsep + existing_python_path
        )

        for record_kind, temporary_prefix, content in canonical_records:
            for action in ("quarantined", "removed"):
                with self.subTest(record=record_kind, action=action):
                    temporary_path = os.path.join(
                        self.godot_dir,
                        temporary_prefix + "a" * 16 + ".tmp",
                    )
                    with open(temporary_path, "wb") as temporary_file:
                        temporary_file.write(content)
                        temporary_file.flush()
                        os.fsync(temporary_file.fileno())
                    included_files_module._sync_included_directory(
                        self.godot_dir,
                        project_identity,
                    )
                    temporary_stat = os.lstat(temporary_path)
                    temporary_identity = (
                        temporary_stat.st_dev,
                        temporary_stat.st_ino,
                    )
                    tombstone_path = (
                        included_files_module._included_cleanup_tombstone_path(
                            temporary_path,
                            hashlib.sha256(content).hexdigest()[:32],
                            record_kind + "-temporary-record",
                            record_kind,
                            expect_directory=False,
                        )
                    )
                    requested_phase = (
                        "cleanup:"
                        + record_kind
                        + "-temporary-record:"
                        + record_kind
                        + ":"
                        + action
                    )

                    interrupted = subprocess.run(
                        (
                            sys.executable,
                            "-c",
                            interruption_script,
                            self.godot_dir,
                            temporary_path,
                            requested_phase,
                        ),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )

                    self.assertEqual(
                        interrupted.returncode,
                        86,
                        interrupted.stdout + interrupted.stderr,
                    )
                    self.assertFalse(os.path.lexists(temporary_path))
                    if action == "quarantined":
                        tombstone_stat = os.lstat(tombstone_path)
                        self.assertEqual(
                            (tombstone_stat.st_dev, tombstone_stat.st_ino),
                            temporary_identity,
                        )
                        with open(tombstone_path, "rb") as tombstone_file:
                            self.assertEqual(tombstone_file.read(), content)
                    else:
                        self.assertFalse(os.path.lexists(tombstone_path))

                    recovery_message = recover()
                    if action == "quarantined":
                        self.assertIn("removed 1", recovery_message or "")
                    else:
                        self.assertIsNone(recovery_message)

                    self.assertFalse(os.path.lexists(tombstone_path))
                    self.assertEqual(self._pair_snapshot(), committed_pair)
                    self._assert_no_transaction_debris()
                    self.assertIsNone(recover())

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

    def test_64_mib_generation_has_bounded_initial_unchanged_and_changed_reads(
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
            if os.fstat(source_file.fileno()).st_size == payload_size:
                read_bytes += len(chunk)
            return chunk

        def count_validation_read(source_file: BinaryIO) -> bytes:
            nonlocal read_bytes
            chunk = original_validation_read(source_file)
            if os.fstat(source_file.fileno()).st_size == payload_size:
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

        with open(source_path, "r+b", buffering=0) as source_file:
            source_file.write(b"\x01")
            os.fsync(source_file.fileno())
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
        ):
            converter.convert_all()
        self.assertLessEqual(read_bytes, 8 * payload_size)
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

    def test_changed_generation_receipts_are_boundary_bound(self) -> None:
        self._write("payload.txt", "BEFORE")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "AFTER!")
        captured_transactions: list[
            included_files_module._IncludedOutputSetTransaction
        ] = []

        def capture_transaction(
            _project_path: str,
            transaction: (
                included_files_module._IncludedOutputSetTransaction
            ),
            _conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            captured_transactions.append(transaction)
            raise OSError("captured generation receipts")

        with (
            patch.object(
                included_files_module,
                "_commit_included_output_set",
                side_effect=capture_transaction,
            ),
            self.assertRaisesRegex(
                OSError,
                "captured generation receipts",
            ),
        ):
            converter.convert_all()

        self.assertEqual(len(captured_transactions), 1)
        transaction = captured_transactions[0]
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(len(transaction.content_receipts), 1)
        transaction_id = transaction.publication_transaction_id
        generation_identity = transaction.staged_root_snapshot.identity
        self.assertIsNotNone(transaction_id)
        self.assertIsNotNone(generation_identity)
        if transaction_id is None or generation_identity is None:
            self.fail("changed-generation receipts lost their boundaries")
        receipt = transaction.content_receipts[0]
        captured_snapshot = (
            included_files_module
            ._capture_included_tree_from_generation_receipts(
                transaction.staged_root_path,
                expected_parent_identity=(
                    transaction.stage_container_identity
                ),
                transaction_id=transaction_id,
                generation_identity=generation_identity,
                stage_container_identity=(
                    transaction.stage_container_identity
                ),
                receipts=transaction.content_receipts,
            )
        )
        self.assertEqual(
            captured_snapshot,
            transaction.staged_root_snapshot,
        )

        source_handle_state = receipt.source.binding.handle_state
        output_fingerprint = receipt.output.output_fingerprint
        output_handle_state = receipt.output.output_handle_state
        forged_receipts = {
            "transaction": replace(
                receipt,
                transaction_id="0" * 32,
            ),
            "generation": replace(
                receipt,
                generation_identity=(
                    generation_identity[0],
                    generation_identity[1] + 1,
                ),
            ),
            "assigned path": replace(
                receipt,
                source=replace(
                    receipt.source,
                    assigned_path="other.bin",
                ),
            ),
            "source identity": replace(
                receipt,
                source=replace(
                    receipt.source,
                    binding=replace(
                        receipt.source.binding,
                        handle_state=(
                            source_handle_state[0],
                            source_handle_state[1] + 1,
                            *source_handle_state[2:],
                        ),
                    ),
                ),
            ),
            "staged output identity": replace(
                receipt,
                output=replace(
                    receipt.output,
                    output_fingerprint=(
                        output_fingerprint[0],
                        output_fingerprint[1] + 1,
                        *output_fingerprint[2:],
                    ),
                    output_handle_state=(
                        output_handle_state[0],
                        output_handle_state[1] + 1,
                        *output_handle_state[2:],
                    ),
                ),
            ),
            "public output identity": replace(
                receipt,
                public_output_path=receipt.public_output_path + ".other",
            ),
            "stage container": replace(
                receipt,
                stage_container_identity=(
                    transaction.stage_container_identity[0],
                    transaction.stage_container_identity[1] + 1,
                ),
            ),
        }
        for boundary, forged_receipt in forged_receipts.items():
            with (
                self.subTest(boundary=boundary),
                self.assertRaisesRegex(
                    OSError,
                    "generation.*receipt|receipt.*binding",
                ),
            ):
                included_files_module._capture_included_tree_from_generation_receipts(
                    transaction.staged_root_path,
                    expected_parent_identity=(
                        transaction.stage_container_identity
                    ),
                    transaction_id=transaction_id,
                    generation_identity=generation_identity,
                    stage_container_identity=(
                        transaction.stage_container_identity
                    ),
                    receipts=(forged_receipt,),
                )
        included_files_module._remove_owned_included_tree(
            transaction.stage_container_path,
            transaction.stage_container_identity,
            expected_parent_identity=transaction.project_identity,
        )
        self._assert_no_transaction_debris()

    def test_final_source_receipt_failure_restores_previous_generation(
        self,
    ) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "CHANGED!")
        source_path = os.path.join(
            self.datafiles_dir,
            "payload.txt",
        )
        source_stat = os.stat(source_path)
        mutated = False

        def mutate_source() -> None:
            nonlocal mutated
            with open(source_path, "r+b", buffering=0) as source_file:
                source_file.write(b"MUTATED!")
                os.fsync(source_file.fileno())
            os.utime(
                source_path,
                ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
            )
            mutated = True

        with (
            patch.object(
                included_files_module,
                "_before_included_changed_generation_final_validation",
                side_effect=mutate_source,
            ),
            self.assertRaisesRegex(OSError, "source receipt"),
        ):
            converter.convert_all()

        self.assertTrue(mutated)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_final_output_hardlink_substitution_restores_previous_generation(
        self,
    ) -> None:
        self._write("payload.txt", "ORIGINAL")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "CHANGED!")
        output_path = os.path.join(
            self.godot_dir,
            "included_files",
            "payload.txt",
        )
        external_path = os.path.join(
            self.gm_dir,
            "receipt-hardlink.bin",
        )
        with open(external_path, "wb") as external_file:
            external_file.write(b"CHANGED!")
        substituted = False

        def substitute_hardlink() -> None:
            nonlocal substituted
            os.unlink(output_path)
            try:
                os.link(external_path, output_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")
            substituted = True

        with (
            patch.object(
                included_files_module,
                "_before_included_changed_generation_final_validation",
                side_effect=substitute_hardlink,
            ),
            self.assertRaisesRegex(
                OSError,
                "root generation|tree changed",
            ),
        ):
            converter.convert_all()

        self.assertTrue(substituted)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), b"CHANGED!")

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
            content_receipts: Mapping[str, tuple[int, str]] | None = None,
        ) -> str:
            return (
                original_render(
                    assignments,
                    emitted_logical_paths,
                    content_receipts,
                )
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

    def test_staged_payload_hardlink_is_rejected_before_publication(self) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        external_path = os.path.join(
            self.gm_dir,
            "external-staged-payload.txt",
        )
        original_capture = included_files_module._capture_included_tree
        hardlink_created = False

        def capture_with_hardlink(
            root_path: str,
            *,
            expected_parent_identity: (
                included_files_module._PathIdentity | None
            ) = None,
            include_content: bool = True,
        ) -> included_files_module._IncludedTreeSnapshot:
            nonlocal hardlink_created
            stage_name = os.path.basename(os.path.dirname(root_path))
            if (
                not hardlink_created
                and os.path.basename(root_path)
                == included_files_module._INCLUDED_FILES_ROOT_NAME
                and stage_name.startswith(
                    included_files_module._INCLUDED_FILES_STAGE_PREFIX
                )
            ):
                staged_path = os.path.join(root_path, "new.txt")
                try:
                    os.link(staged_path, external_path)
                except (NotImplementedError, OSError) as error:
                    self.skipTest(f"Hard links are unavailable: {error}")
                hardlink_created = True
            return original_capture(
                root_path,
                expected_parent_identity=expected_parent_identity,
                include_content=include_content,
            )

        with (
            patch.object(
                included_files_module,
                "_capture_included_tree",
                side_effect=capture_with_hardlink,
            ),
            self.assertRaisesRegex(OSError, "multiple hard links"),
        ):
            converter.convert_all()

        self.assertTrue(hardlink_created)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), b"new generation")
        self._assert_no_transaction_debris()

    def test_staged_registry_hardlink_is_rejected_before_publication(self) -> None:
        self._write("old.txt", "old generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()

        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        self._write("new.txt", "new generation")
        external_path = os.path.join(
            self.gm_dir,
            "external-staged-registry.gd",
        )
        external_content: bytes | None = None
        original_snapshot = (
            included_files_module._included_stage_container_snapshot
        )

        def snapshot_with_hardlink(
            project_identity: included_files_module._PathIdentity,
            stage_path: str,
            stage_identity: included_files_module._PathIdentity,
            staged_root_snapshot: included_files_module._IncludedTreeSnapshot,
            staged_registry_identity: included_files_module._PathIdentity,
            staged_registry_content: bytes,
        ) -> included_files_module._IncludedTreeSnapshot:
            nonlocal external_content
            staged_registry_path = os.path.join(
                stage_path,
                "gml_included_file_registry.gd",
            )
            try:
                os.link(staged_registry_path, external_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")
            with open(external_path, "rb") as external_file:
                external_content = external_file.read()
            return original_snapshot(
                project_identity,
                stage_path,
                stage_identity,
                staged_root_snapshot,
                staged_registry_identity,
                staged_registry_content,
            )

        with (
            patch.object(
                included_files_module,
                "_included_stage_container_snapshot",
                side_effect=snapshot_with_hardlink,
            ),
            self.assertRaisesRegex(OSError, "multiple hard links"),
        ):
            converter.convert_all()

        self.assertIsNotNone(external_content)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        with open(external_path, "rb") as external_file:
            self.assertEqual(external_file.read(), external_content)
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

    def test_bounded_record_accepts_stable_path_handle_metadata_skew(self) -> None:
        payload = b'{"state":"prepared"}\n'
        record_path = os.path.join(self.godot_dir, "recovery-record.json")
        with open(record_path, "wb") as record_file:
            record_file.write(payload)
        path_stat = os.lstat(record_path)
        handle_stat = self._modeled_handle_stat(
            path_stat,
            ctime_offset=1,
        )

        with (
            open(record_path, "rb") as record_file,
            patch.object(
                included_files_module.os,
                "fstat",
                side_effect=(handle_stat, handle_stat),
            ),
        ):
            content = (
                included_files_module._read_opened_included_bounded_record_payload(
                    record_file,
                    path_stat,
                    record_path,
                    path_stat.st_dev,
                    None,
                    len(payload),
                    lambda opened_file: opened_file.read(len(payload) + 1),
                    "Included Files recovery record",
                    "canonical",
                )
            )

        self.assertEqual(content, payload)

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
            included_files_module._windows_extended_included_path(path),
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
            included_files_module.os.path,
            "abspath",
            side_effect=unchanged_absolute_path,
        ):
            for path, expected in cases.items():
                with self.subTest(path=path):
                    self.assertEqual(
                        included_files_module._windows_extended_included_path(
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
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(included_files_module.sys, "platform", "win32"),
            patch.object(
                included_files_module,
                "_windows_included_transaction_api",
                return_value=kernel32,
            ),
        ):
            included_files_module._rename_included_transaction_entry(
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
            included_files_module._WINDOWS_MOVEFILE_WRITE_THROUGH,
        )

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
        preserved_staged_file: str | None = None

        def mutate_then_commit(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            nonlocal mutated, preserved_staged_file
            staged_file = os.path.join(
                transaction.staged_root_path,
                "new.txt",
            )
            preserved_staged_file = staged_file
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
        self.assertIsNotNone(preserved_staged_file)
        if preserved_staged_file is not None:
            with open(preserved_staged_file, "rb") as staged_file:
                self.assertEqual(staged_file.read(), b"EVIL")
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (
                    os.path.basename(
                        os.path.dirname(os.path.dirname(preserved_staged_file))
                    ),
                ),
            )

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
        debris = _included_files_transaction_debris(self.godot_dir)
        self.assertEqual(len(debris), 2)
        stage_relative_path = debris[0]
        self.assertTrue(
            stage_relative_path.startswith(
                included_files_module._INCLUDED_FILES_STAGE_PREFIX
            ),
            debris,
        )
        self.assertEqual(
            debris[1],
            stage_relative_path
            + "/"
            + included_files_module._INCLUDED_FILES_STAGE_MARKER_NAME,
        )
        with open(
            os.path.join(
                self.godot_dir,
                stage_relative_path,
                "included_files",
                "new.txt",
            ),
            "rb",
        ) as staged_file:
            self.assertEqual(staged_file.read(), b"new")

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
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (
                    os.path.relpath(sentinel_path, self.godot_dir).replace(
                        os.sep,
                        "/",
                    ),
                ),
            )
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
        cleanup_recorded_tree = (
            included_files_module._cleanup_recorded_included_tree
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
            included_files_module,
            "_cleanup_recorded_included_tree",
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

    def test_committed_cleanup_preserves_unknown_stage_content(self) -> None:
        logs: list[str] = []
        converter = IncludedFilesConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=logs.append,
            progress_callback=lambda _value: None,
            conversion_running=self.running.is_set,
            max_workers=1,
        )
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            included_files_module._cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown committed stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with patch.object(
            included_files_module,
            "_cleanup_recorded_included_tree",
            side_effect=inject_unknown_stage_content,
        ):
            converter.convert_all()

        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown committed stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertEqual(self._pair_snapshot()[1], {"new.txt": b"new"})
        self.assertTrue(
            any("transaction cleanup failed" in message for message in logs),
            logs,
        )

    def test_cancelled_rollback_preserves_unknown_stage_content(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            included_files_module._cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None
        cancellation_injected = False

        def cancel_after_journal(phase: str) -> None:
            nonlocal cancellation_injected
            if phase == "journal-prepared":
                cancellation_injected = True
                self.running.clear()

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "rollback-stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown cancelled stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with (
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=cancel_after_journal,
            ),
            patch.object(
                included_files_module,
                "_cleanup_recorded_included_tree",
                side_effect=inject_unknown_stage_content,
            ),
        ):
            converter.convert_all()

        self.assertTrue(cancellation_injected)
        self.assertTrue(converter.conversion_step_result().cancelled)
        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown cancelled stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
        )

    def test_failed_rollback_preserves_unknown_stage_content(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("new.txt", "new")
        cleanup_recorded_tree = (
            included_files_module._cleanup_recorded_included_tree
        )
        sentinel_path: str | None = None

        def fail_after_journal(phase: str) -> None:
            if phase == "journal-prepared":
                raise OSError("injected commit failure")

        def inject_unknown_stage_content(
            path: str,
            snapshot: included_files_module._IncludedTreeSnapshot,
            expected_parent_identity: tuple[int, int],
            transaction_id: str,
            role: str,
        ) -> tuple[str, ...]:
            nonlocal sentinel_path
            if sentinel_path is None and role == "rollback-stage":
                sentinel_path = os.path.join(path, "unknown-sentinel.txt")
                with open(sentinel_path, "xb") as sentinel_file:
                    sentinel_file.write(b"unknown failed stage content")
                    sentinel_file.flush()
                    os.fsync(sentinel_file.fileno())
            return cleanup_recorded_tree(
                path,
                snapshot,
                expected_parent_identity,
                transaction_id,
                role,
            )

        with (
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=fail_after_journal,
            ),
            patch.object(
                included_files_module,
                "_cleanup_recorded_included_tree",
                side_effect=inject_unknown_stage_content,
            ),
            self.assertRaisesRegex(OSError, "injected commit failure"),
        ):
            converter.convert_all()

        self.assertIsNotNone(sentinel_path)
        if sentinel_path is not None:
            with open(sentinel_path, "rb") as sentinel_file:
                self.assertEqual(
                    sentinel_file.read(),
                    b"unknown failed stage content",
                )
            self.assertEqual(
                _included_files_transaction_debris(self.godot_dir),
                (os.path.basename(os.path.dirname(sentinel_path)),),
            )
        self.assertFalse(
            os.path.lexists(os.path.join(self.godot_dir, "included_files"))
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
            "_before_included_transaction_rename",
            side_effect=swap_cleanup_file,
        ), self.assertRaisesRegex(OSError, "restored without loss"):
            included_files_module._cleanup_recorded_included_file(
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
                    included_files_module._included_path_fingerprint(owned_stat)
                ),
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertTrue(swapped)
        with open(owned_path, encoding="utf-8") as owned_file:
            self.assertEqual(owned_file.read(), "unknown replacement")
        with open(parked_path, encoding="utf-8") as parked_file:
            self.assertEqual(parked_file.read(), "owned cleanup file")

    def test_descriptor_cleanup_streams_payload_receipts(self) -> None:
        if not included_files_module._included_descriptor_paths_supported():
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
        original_read = included_files_module._read_included_validation_chunk

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
                    included_files_module,
                    "_read_included_validation_chunk",
                    side_effect=count_streamed_bytes,
                ),
                patch.object(
                    included_files_module,
                    "_included_regular_file_state",
                    side_effect=AssertionError(
                        "cleanup used the whole-content file-state helper"
                    ),
                ),
            ):
                warnings = (
                    included_files_module._cleanup_recorded_included_file(
                        owned_path,
                        (owned_stat.st_dev, owned_stat.st_ino),
                        expected_digest.hexdigest(),
                        (parent_stat.st_dev, parent_stat.st_ino),
                        "f" * 32,
                        "large-streaming-cleanup",
                        "large.bin",
                        expected_fingerprint=(
                            included_files_module._included_path_fingerprint(
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

    def test_large_cleanup_tombstone_recovers_after_hard_exit(self) -> None:
        payload_size = 64 * 1024 * 1024
        source_path = os.path.join(self.datafiles_dir, "large.bin")
        with open(source_path, "wb") as source_file:
            source_file.truncate(payload_size)
        converter = self._converter(max_workers=1)
        converter.convert_all()
        os.unlink(source_path)
        self._write("new.txt", "new generation")

        interrupted = self._run_interrupted_conversion(
            "cleanup:root-backup:large.bin:quarantined"
        )

        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        large_tombstones = [
            os.path.join(directory, filename)
            for directory, _subdirectories, filenames in os.walk(
                self.godot_dir
            )
            for filename in filenames
            if filename.startswith(
                included_files_module._INCLUDED_FILES_CLEANUP_PREFIX
            )
            and filename.endswith(".file")
            and os.path.getsize(os.path.join(directory, filename))
            == payload_size
        ]
        self.assertEqual(len(large_tombstones), 1)
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    included_files_module._INCLUDED_FILES_COMMIT_NAME,
                )
            )
        )

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new.txt": b"new generation"},
        )
        self.assertFalse(os.path.lexists(large_tombstones[0]))
        self._assert_no_transaction_debris()

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
        expected_fingerprint = included_files_module._included_path_fingerprint(
            owned_stat
        )
        transaction_id = "a" * 32
        tombstone_path = included_files_module._included_cleanup_tombstone_path(
            owned_path,
            transaction_id,
            "test-readonly",
            "owned.txt",
            expect_directory=False,
        )

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "unlink",
                side_effect=PermissionError("injected Windows sharing failure"),
            ),
            patch.object(
                included_files_module,
                "_open_included_file_validation_stream",
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            self.assertRaisesRegex(
                OSError,
                "recoverable quarantine retained",
            ),
        ):
            included_files_module._cleanup_recorded_included_file(
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_open_included_file_validation_stream",
                side_effect=self._open_modeled_windows_validation_stream,
            ),
        ):
            warnings = included_files_module._cleanup_recorded_included_file(
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

    def test_windows_deterministic_cleanup_recovers_after_readonly_clear_exit(
        self,
    ) -> None:
        cleanup_directory = os.path.join(
            self.godot_dir,
            "windows-deterministic-readonly-exit",
        )
        os.mkdir(cleanup_directory)
        owned_path = os.path.join(cleanup_directory, "owned.txt")
        content = b"owned interrupted cleanup target"
        with open(owned_path, "wb") as owned_file:
            owned_file.write(content)
        os.chmod(owned_path, 0o400)
        owned_stat = os.lstat(owned_path)
        parent_stat = os.lstat(cleanup_directory)
        expected_identity = (owned_stat.st_dev, owned_stat.st_ino)
        expected_parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        expected_fingerprint = included_files_module._included_path_fingerprint(
            owned_stat
        )
        transaction_id = "b" * 32
        tombstone_path = included_files_module._included_cleanup_tombstone_path(
            owned_path,
            transaction_id,
            "test-readonly-exit",
            "owned.txt",
            expect_directory=False,
        )

        class SimulatedProcessExit(BaseException):
            pass

        def stop_after_readonly_clear(phase: str) -> None:
            if phase == "cleanup-readonly-cleared":
                raise SimulatedProcessExit()

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_open_included_file_validation_stream",
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            patch.object(
                included_files_module,
                "_after_included_transaction_phase",
                side_effect=stop_after_readonly_clear,
            ),
            self.assertRaises(SimulatedProcessExit),
        ):
            included_files_module._cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly-exit",
                "owned.txt",
                expected_fingerprint=expected_fingerprint,
                expected_mode=stat.S_IMODE(owned_stat.st_mode),
            )

        self.assertFalse(os.path.lexists(owned_path))
        interrupted_stat = os.lstat(tombstone_path)
        self.assertTrue(interrupted_stat.st_mode & stat.S_IWRITE)

        with (
            patch.object(
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_open_included_file_validation_stream",
                side_effect=self._open_modeled_windows_validation_stream,
            ),
        ):
            warnings = included_files_module._cleanup_recorded_included_file(
                owned_path,
                expected_identity,
                hashlib.sha256(content).hexdigest(),
                expected_parent_identity,
                transaction_id,
                "test-readonly-exit",
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module,
                "_open_included_file_validation_stream",
                side_effect=self._open_modeled_windows_validation_stream,
            ),
            self.assertRaisesRegex(
                OSError,
                "multiple hard links.*recoverable quarantine retained",
            ),
        ):
            included_files_module._cleanup_recorded_included_file(
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
                    included_files_module._included_path_fingerprint(owned_stat)
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
        ):
            warnings = included_files_module._cleanup_recorded_included_directory(
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
                included_files_module,
                "_included_descriptor_paths_supported",
                return_value=False,
            ),
            patch.object(included_files_module.os, "name", "nt"),
            patch.object(
                included_files_module.os,
                "rmdir",
                side_effect=PermissionError("injected Windows sharing failure"),
            ),
            self.assertRaisesRegex(
                OSError,
                "directory; recoverable quarantine retained",
            ),
        ):
            included_files_module._cleanup_recorded_included_directory(
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

    def test_deep_tree_capture_binding_work_scales_linearly(
        self,
    ) -> None:
        variants = [
            (
                "native-windows-path" if os.name == "nt" else "fallback-path",
                False,
                "_verify_included_tree_path_binding",
            )
        ]
        if included_files_module._included_descriptor_paths_supported():
            variants.insert(
                0,
                (
                    "descriptor",
                    True,
                    "_verify_included_tree_descriptor_binding",
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
                        included_files_module,
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
                            included_files_module,
                            "_included_descriptor_paths_supported",
                            return_value=descriptor_supported,
                        ),
                        patch.object(
                            included_files_module,
                            verifier_name,
                            side_effect=count_binding,
                        ),
                    ):
                        snapshot = included_files_module._capture_included_tree(
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
        included_files_module._included_descriptor_paths_supported(),
        "Descriptor-pinned Included Files paths are unavailable",
    )
    def test_descriptor_and_fallback_tree_snapshots_are_byte_equivalent(
        self,
    ) -> None:
        root_path = os.path.join(self.godot_dir, "snapshot-equivalence")
        os.makedirs(os.path.join(root_path, "z", "nested"))
        os.makedirs(os.path.join(root_path, "a"))
        for relative_path, content in (
            ("z/nested/last.bin", b"\x00\xfflast\n"),
            ("a/first.txt", b"first\n"),
            ("middle.json", b'{"stable":true}\n'),
        ):
            output_path = os.path.join(root_path, *relative_path.split("/"))
            with open(output_path, "wb") as output_file:
                output_file.write(content)

        descriptor_snapshot = included_files_module._capture_included_tree(
            root_path
        )
        with patch.object(
            included_files_module,
            "_included_descriptor_paths_supported",
            return_value=False,
        ):
            fallback_snapshot = included_files_module._capture_included_tree(
                root_path
            )

        descriptor_bytes = json.dumps(
            included_files_module._included_tree_snapshot_payload(
                descriptor_snapshot
            ),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        fallback_bytes = json.dumps(
            included_files_module._included_tree_snapshot_payload(
                fallback_snapshot
            ),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.assertEqual(fallback_bytes, descriptor_bytes)

    @unittest.skipUnless(
        included_files_module._included_descriptor_paths_supported(),
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
        original_listdir = included_files_module.os.listdir
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
                    included_files_module,
                    "_included_descriptor_paths_supported",
                    return_value=True,
                ),
                patch.object(
                    included_files_module.os,
                    "listdir",
                    side_effect=swap_ancestor_after_deep_scan,
                ),
                self.assertRaisesRegex(OSError, "entry changed"),
            ):
                included_files_module._capture_included_tree(scan_root)

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

    def test_worker_window_bounds_ten_thousand_sources(self) -> None:
        max_workers = 4
        expected_window = 2 * max_workers
        release_workers = threading.Event()
        window_filled = threading.Event()
        state_lock = threading.Lock()
        submitted = 0
        unfinished = 0
        max_unfinished = 0
        tracked_futures: set[Future[int]] = set()
        processed: list[int] = []
        phase_results: list[bool] = []
        phase_errors: list[BaseException] = []

        def worker(item: int) -> int:
            if not release_workers.wait(timeout=10):
                raise TimeoutError("bounded worker release timed out")
            return item

        def submit(
            executor: ThreadPoolExecutor,
            item: int,
        ) -> Future[int]:
            nonlocal submitted
            nonlocal unfinished
            nonlocal max_unfinished

            future = executor.submit(worker, item)
            with state_lock:
                submitted += 1
                tracked_futures.add(future)
                unfinished = sum(
                    not tracked_future.done()
                    for tracked_future in tracked_futures
                )
                max_unfinished = max(max_unfinished, unfinished)
                if submitted == expected_window:
                    window_filled.set()

            def finished(completed_future: Future[int]) -> None:
                nonlocal unfinished
                with state_lock:
                    tracked_futures.discard(completed_future)
                    unfinished = sum(
                        not tracked_future.done()
                        for tracked_future in tracked_futures
                    )

            future.add_done_callback(finished)
            return future

        def consume(item: int, future: Future[int]) -> bool:
            result = future.result()
            if result != item:
                raise AssertionError("bounded worker returned the wrong item")
            processed.append(result)
            return True

        def run_phase() -> None:
            try:
                phase_results.append(
                    included_files_module._run_bounded_included_worker_phase(
                        range(10_000),
                        max_workers=max_workers,
                        conversion_running=lambda: True,
                        submit=submit,
                        consume=consume,
                    )
                )
            except BaseException as error:
                phase_errors.append(error)

        phase_thread = threading.Thread(target=run_phase)
        phase_thread.start()
        try:
            self.assertTrue(window_filled.wait(timeout=5))
            with state_lock:
                self.assertEqual(submitted, expected_window)
                self.assertEqual(unfinished, expected_window)
                self.assertEqual(max_unfinished, expected_window)
        finally:
            release_workers.set()
            phase_thread.join(timeout=15)

        self.assertFalse(phase_thread.is_alive())
        self.assertEqual(phase_errors, [])
        self.assertEqual(phase_results, [True])
        self.assertEqual(submitted, 10_000)
        self.assertEqual(sorted(processed), list(range(10_000)))
        self.assertLessEqual(max_unfinished, expected_window)

    def test_changed_generation_stops_admission_after_worker_failure(self) -> None:
        converter = self._converter(max_workers=1)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        for index in range(20):
            self._write(f"{index:02}.txt", str(index))
        original_process = converter._process_file
        started: list[str] = []

        def fail_first(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            started.append(relative_path)
            if relative_path == "00.txt":
                return relative_path, False, None
            return original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )

        with patch.object(
            converter,
            "_process_file",
            side_effect=fail_first,
        ):
            with self.assertRaisesRegex(OSError, "output-set staging failed"):
                converter.convert_all()

        self.assertEqual(started[0], "00.txt")
        self.assertLessEqual(len(started), 2)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=20, executed=20, failed=20),
        )
        self._assert_no_transaction_debris()

    def test_unchanged_receipts_stop_admission_after_worker_failure(self) -> None:
        converter = self._converter(max_workers=1)
        for index in range(20):
            self._write(f"{index:02}.txt", str(index))
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        original_capture = converter._capture_unchanged_source_receipt
        started: list[str] = []

        def fail_first(
            source: included_files_module._IncludedFileSource,
            *,
            deny_writes: bool,
        ) -> included_files_module._IncludedNoOpSourceReceipt:
            started.append(source.relative_path)
            if source.relative_path == "00.txt":
                raise OSError("injected receipt failure")
            return original_capture(source, deny_writes=deny_writes)

        with patch.object(
            converter,
            "_capture_unchanged_source_receipt",
            side_effect=fail_first,
        ):
            with self.assertRaisesRegex(OSError, "injected receipt failure"):
                converter.convert_all()

        self.assertEqual(started[0], "00.txt")
        self.assertLessEqual(len(started), 2)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()

    def test_cancellation_stops_worker_admission_within_window(self) -> None:
        converter = self._converter(max_workers=2)
        self._write("old.txt", "old")
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        os.unlink(os.path.join(self.datafiles_dir, "old.txt"))
        for index in range(20):
            self._write(f"{index:02}.txt", str(index))
        original_process = converter._process_file
        started: list[str] = []
        started_lock = threading.Lock()
        cancellation_observed = threading.Event()

        def cancel_first(
            gm_file_path: str,
            godot_file_path: str,
            relative_path: str,
            owner_source_path: str,
        ) -> tuple[str, bool, object | None] | None:
            with started_lock:
                started.append(relative_path)
            if relative_path == "00.txt":
                self.running.clear()
                cancellation_observed.set()
                return None
            if not cancellation_observed.wait(timeout=5):
                raise TimeoutError("worker cancellation was not observed")
            return original_process(
                gm_file_path,
                godot_file_path,
                relative_path,
                owner_source_path,
            )

        with patch.object(
            converter,
            "_process_file",
            side_effect=cancel_first,
        ):
            converter.convert_all()

        self.assertGreaterEqual(len(started), 1)
        self.assertLessEqual(len(started), 4)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertEqual(
            converter.conversion_step_result(
                finalize_unfinished_as=None,
            ).resources,
            ConversionCounts(requested=20, executed=0, skipped=20),
        )
        self.assertTrue(converter.conversion_step_result().cancelled)
        self._assert_no_transaction_debris()

    def test_worker_counts_produce_identical_output_and_diagnostics(self) -> None:
        for index in range(12):
            self._write(f"nested/{index:02}.txt", f"payload {index}")
        self._write("Alpha Beta.txt", "first collision")
        self._write("alpha_beta.txt", "second collision")
        second_godot_dir = tempfile.mkdtemp()
        self.addCleanup(
            shutil.rmtree,
            second_godot_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

        def convert_with_workers(
            godot_path: str,
            max_workers: int,
        ) -> tuple[tuple[tuple[str, bytes], ...], bytes, str]:
            diagnostics = DiagnosticCollector()
            IncludedFilesConverter(
                self.gm_dir,
                godot_path,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=max_workers,
                diagnostics=diagnostics,
            ).convert_all()
            root_path = os.path.join(godot_path, "included_files")
            files: list[tuple[str, bytes]] = []
            for directory, _subdirectories, filenames in os.walk(root_path):
                for filename in filenames:
                    path = os.path.join(directory, filename)
                    relative_path = os.path.relpath(path, root_path).replace(
                        os.sep,
                        "/",
                    )
                    with open(path, "rb") as output_file:
                        files.append((relative_path, output_file.read()))
            with open(
                os.path.join(
                    godot_path,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                ),
                "rb",
            ) as registry_file:
                registry_content = registry_file.read()
            return (
                tuple(sorted(files)),
                registry_content,
                diagnostics.to_json(),
            )

        single_worker = convert_with_workers(self.godot_dir, 1)
        four_workers = convert_with_workers(second_godot_dir, 4)

        self.assertEqual(single_worker, four_workers)
        self._assert_no_transaction_debris()
        self.assertEqual(
            _included_files_transaction_debris(second_godot_dir),
            (),
        )

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

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new/nested.txt": b"new payload"},
        )
        self.assertFalse(os.lstat(registry_path).st_mode & stat.S_IWRITE)
        self._assert_no_transaction_debris()

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_cleanup_recovers_after_process_exit(
        self,
    ) -> None:
        converter = self._converter(max_workers=1)
        self._write("old/nested.txt", "old payload")
        converter.convert_all()
        public_root = os.path.join(self.godot_dir, "included_files")
        self._mark_native_windows_tree_read_only(public_root)

        os.unlink(os.path.join(self.datafiles_dir, "old", "nested.txt"))
        os.rmdir(os.path.join(self.datafiles_dir, "old"))
        self._write("new/nested.txt", "new payload")

        interrupted = self._run_interrupted_conversion(
            "cleanup-readonly-cleared"
        )
        self.assertEqual(
            interrupted.returncode,
            86,
            interrupted.stdout + interrupted.stderr,
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    included_files_module._INCLUDED_FILES_JOURNAL_NAME,
                )
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    included_files_module._INCLUDED_FILES_COMMIT_NAME,
                )
            )
        )

        converter.convert_all()

        self.assertEqual(
            self._pair_snapshot()[1],
            {"new/nested.txt": b"new payload"},
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
        original_commit = included_files_module._commit_included_output_set
        original_move = included_files_module._move_exact_included_file
        publication_failed = False

        def commit_with_readonly_stage(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            return original_commit(
                project_path,
                self._transaction_with_native_windows_readonly_staged_root(
                    transaction
                ),
                conversion_running,
            )

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
                "_commit_included_output_set",
                side_effect=commit_with_readonly_stage,
            ),
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
        original_commit = included_files_module._commit_included_output_set
        original_move = included_files_module._move_exact_included_file
        cancellation_injected = False

        def commit_with_readonly_stage(
            project_path: str,
            transaction: included_files_module._IncludedOutputSetTransaction,
            conversion_running: Callable[[], bool],
        ) -> tuple[str, ...]:
            return original_commit(
                project_path,
                self._transaction_with_native_windows_readonly_staged_root(
                    transaction
                ),
                conversion_running,
            )

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

        with (
            patch.object(
                included_files_module,
                "_commit_included_output_set",
                side_effect=commit_with_readonly_stage,
            ),
            patch.object(
                included_files_module,
                "_move_exact_included_file",
                side_effect=publish_registry_then_cancel,
            ),
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

    def _assert_persistent_project_lock(self, project_path: str) -> str:
        lock_path = os.path.join(
            project_path,
            included_files_module._INCLUDED_FILES_LOCK_NAME,
        )
        self.assertTrue(os.path.isfile(lock_path))
        self.assertFalse(os.path.islink(lock_path))
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                included_files_module._INCLUDED_FILES_LOCK_CONTENT,
            )
        return lock_path

    def _assert_no_project_transaction_debris(
        self,
        project_path: str,
    ) -> None:
        self._assert_persistent_project_lock(project_path)
        self.assertEqual(
            _included_files_transaction_debris(project_path),
            (),
        )

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
        self._assert_no_project_transaction_debris(self.godot_dir)
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
        self._assert_no_project_transaction_debris(self.godot_dir)
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
        self._assert_no_project_transaction_debris(self.godot_dir)
        self._assert_failed_output(
            converter,
            diagnostics,
            rejection_count=0,
        )

    @unittest.skipIf(
        os.name == "nt",
        "the persistent Windows project lock blocks root relocation",
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
            lock_path = self._assert_persistent_project_lock(moved_project)
            non_lock_outside_files = [
                path for path in outside_files if path != lock_path
            ]
            self.assertEqual(len(non_lock_outside_files), 1)
            self.assertTrue(
                non_lock_outside_files[0].startswith(moved_project + os.sep)
            )
            self.assertEqual(
                os.path.basename(non_lock_outside_files[0]),
                included_files_module._INCLUDED_FILES_STAGE_MARKER_NAME,
            )
            self._assert_failed_output(converter, diagnostics)
        finally:
            if os.path.islink(self.godot_dir):
                os.unlink(self.godot_dir)
            if os.path.isdir(moved_project):
                original_rename(moved_project, self.godot_dir)

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_project_lock_blocks_root_relocation(self) -> None:
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        moved_project = os.path.join(self.outside_dir, "moved_project")
        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        try:
            with self.assertRaises(OSError):
                os.rename(self.godot_dir, moved_project)
        finally:
            included_files_module._release_included_project_lock(project_lock)
            if not os.path.lexists(self.godot_dir) and os.path.isdir(moved_project):
                os.rename(moved_project, self.godot_dir)

        self.assertTrue(os.path.isdir(self.godot_dir))
        self.assertFalse(os.path.lexists(moved_project))
        self._assert_no_project_transaction_debris(self.godot_dir)

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
        project_identity = (
            included_files_module._ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = included_files_module._acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        included_files_module._release_included_project_lock(project_lock)
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
