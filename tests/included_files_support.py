# pyright: reportPrivateUsage=false

import hashlib
import os
import stat
import subprocess
import sys
import shutil
import tempfile
import threading
import unittest
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from typing import BinaryIO, Callable
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import guarded_mutations as _included_mutations
from src.conversion.included_files_parts import record_io as _included_records
from src.conversion.included_files_parts import recorded_cleanup as _included_cleanup
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import native_posix as _included_posix, native_windows as _included_windows, constants as _included_constants, stat_metadata as _included_metadata, recovery_codec as _included_codec
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_files_parts import file_publication as _included_file_publication
from src.conversion.included_files_parts import locking as _included_locking
from src.conversion.included_files_parts import recovery as _included_recovery
from src.conversion.included_files_parts import staging as _included_staging


def _included_files_transaction_debris(project_path: str) -> tuple[str, ...]:
    project_path = os.path.abspath(project_path)
    persistent_lock_path = os.path.normcase(
        os.path.join(
            project_path,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
    )
    debris: list[str] = []
    for directory, subdirectories, filenames in os.walk(project_path):
        for name in (*subdirectories, *filenames):
            candidate_path = os.path.abspath(os.path.join(directory, name))
            if os.path.normcase(candidate_path) == persistent_lock_path:
                continue
            if (
                name == _included_constants.INCLUDED_FILES_LOCK_NAME
                or name == _included_constants.INCLUDED_FILES_JOURNAL_NAME
                or name == _included_constants.INCLUDED_FILES_COMMIT_NAME
                or name == _included_constants.INCLUDED_FILES_STAGE_MARKER_NAME
                or name.startswith(
                    _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                )
                or name.startswith(
                    _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                )
                or name.startswith(
                    _included_constants.INCLUDED_FILES_STAGE_PREFIX
                )
                or name.startswith(".included_files.")
                or name.startswith(".gml_included_file_registry.gd.")
                or name.startswith(
                    _included_constants.INCLUDED_FILES_CLEANUP_PREFIX
                )
            ):
                debris.append(
                    os.path.relpath(candidate_path, project_path).replace(
                        os.sep,
                        "/",
                    )
                )
    return tuple(sorted(debris))


class _ModeledWindowsCleanupParentBinding:
    """Model the path/identity contract of a retained native Windows handle."""

    def __init__(
        self,
        path: str,
        identity: tuple[int, int],
        *,
        close_error: BaseException | None = None,
    ) -> None:
        self.path = os.path.abspath(path)
        self.identity = identity
        self.closed = False
        self.verify_count = 0
        self.close_count = 0
        self.close_error = close_error

    def __enter__(self) -> "_ModeledWindowsCleanupParentBinding":
        self.verify()
        return self

    def __exit__(
        self,
        _exception_type: object,
        active_error: BaseException | None,
        _traceback: object,
    ) -> None:
        try:
            self.close()
        except BaseException as close_error:
            if active_error is None:
                raise
            active_error.add_note(
                "Could not close modeled Included Files cleanup parent "
                f"binding: {close_error}"
            )

    def verify(self) -> None:
        self.verify_count += 1
        if self.closed:
            raise OSError(f"Included Files cleanup parent binding is closed: {self.path}")
        try:
            path_stat = os.lstat(self.path)
        except OSError as error:
            raise OSError(
                f"Included Files cleanup parent changed: {self.path}"
            ) from error
        if (
            _included_metadata.included_output_path_is_redirected(
                self.path,
                path_stat,
            )
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self.identity
        ):
            raise OSError(f"Included Files cleanup parent changed: {self.path}")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class IncludedManagedRootFixture(unittest.TestCase):
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

    def _modeled_windows_cleanup_context(
        self,
        binding_opener: Callable[
            [str, tuple[int, int]],
            _ModeledWindowsCleanupParentBinding,
        ],
    ) -> ExitStack:
        cleanup_context = ExitStack()
        cleanup_context.enter_context(
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            )
        )
        cleanup_context.enter_context(
            patch.object(os, "name", "nt")
        )
        cleanup_context.enter_context(
            patch.object(_included_windows.sys, "platform", "win32")
        )
        cleanup_context.enter_context(
            patch.object(
                _included_windows.WindowsIncludedCleanupParentBinding,
                "open",
                side_effect=binding_opener,
            )
        )
        cleanup_context.enter_context(
            patch.object(
                _included_windows,
                'rename_included_transaction_entry',
                side_effect=os.rename,
            )
        )
        cleanup_context.enter_context(
            patch.object(
                _included_windows,
                'open_included_file_validation_stream',
                side_effect=self._open_modeled_windows_validation_stream,
            )
        )
        return cleanup_context

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
        original_read = _included_snapshots.read_included_validation_chunk

        def count_streamed_bytes(opened_file: BinaryIO) -> bytes:
            nonlocal streamed_bytes, largest_chunk
            chunk = original_read(opened_file)
            streamed_bytes += len(chunk)
            largest_chunk = max(largest_chunk, len(chunk))
            return chunk

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=not force_fallback,
            ),
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
            patch.object(
                _included_windows,
                'rename_included_transaction_entry',
                side_effect=os.rename,
            ),
            patch.object(
                _included_posix,
                'sync_included_directory',
            ),
        ):
            warnings = _included_cleanup.cleanup_recorded_included_file(
                owned_path,
                (owned_stat.st_dev, owned_stat.st_ino),
                hashlib.sha256(content).hexdigest(),
                (parent_stat.st_dev, parent_stat.st_ino),
                "e" * 32,
                "streaming-cleanup",
                "owned.bin",
                expected_fingerprint=(
                    _included_metadata.included_path_fingerprint(
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
        staged_root_snapshot = _included_snapshots.capture_included_tree(
            transaction.staged_root_path,
            expected_parent_identity=transaction.stage_container_identity,
        )
        staged_container_snapshot = (
            _included_staging.included_stage_container_snapshot(
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
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == "generation-committed":
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
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
                    _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                    _included_constants.INCLUDED_FILES_COMMIT_NAME,
                }
                or (
                    name.startswith(
                        _included_constants.INCLUDED_FILES_JOURNAL_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                )
                or (
                    name.startswith(
                        _included_constants.INCLUDED_FILES_COMMIT_TEMP_PREFIX
                    )
                    and name.endswith(".tmp")
                )
            ):
                continue
            record_path = os.path.join(project_path, name)
            record = _included_records.read_included_recovery_record(
                record_path,
                project_identity,
            )
            if record is None:
                continue
            payload = record[1]
            state = payload.get("state")
            if state == "prepared":
                journal = (
                    _included_codec.included_recovery_journal_from_payload(
                        project_path,
                        project_identity,
                        payload,
                    )
                )
                legacy_journal = replace(
                    journal,
                    format_version=(
                        _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
                    ),
                )
                legacy_payload = (
                    _included_codec.included_recovery_journal_payload_v1(
                        legacy_journal
                    )
                )
            elif state == "committed":
                _marker, journal = (
                    _included_codec.included_commit_marker_and_journal_from_payload(
                        project_path,
                        payload,
                        project_identity,
                    )
                )
                legacy_journal = replace(
                    journal,
                    format_version=(
                        _included_constants.INCLUDED_FILES_LEGACY_RECOVERY_FORMAT_VERSION
                    ),
                )
                legacy_payload = (
                    _included_codec.included_commit_marker_payload_v1(
                        legacy_journal
                    )
                )
            else:
                continue
            with open(record_path, "wb") as record_file:
                record_file.write(
                    _included_codec.included_recovery_record_content(
                        legacy_payload
                    )
                )
                record_file.flush()
                os.fsync(record_file.fileno())
            rewritten += 1
        _included_posix.sync_included_directory(
            project_path,
            project_identity,
        )
        return rewritten

    def _assert_windows_nested_cleanup_parent_change_is_preserved(
        self,
        *,
        install_replacement: bool,
    ) -> None:
        label = "replacement" if install_replacement else "relocation"
        root_path = os.path.join(self.godot_dir, f"nested-parent-{label}")
        nested_path = os.path.join(root_path, "nested")
        parked_path = os.path.join(root_path, "nested-parked")
        owned_path = os.path.join(nested_path, "owned.txt")
        os.makedirs(nested_path)
        with open(owned_path, "wb") as owned_file:
            owned_file.write(b"recorded nested content\n")
        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        bindings: list[_ModeledWindowsCleanupParentBinding] = []
        parent_changed = False

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            bindings.append(binding)
            return binding

        def change_parent_before_move(source: str, _destination: str) -> None:
            nonlocal parent_changed
            if parent_changed or os.path.abspath(source) != os.path.abspath(
                owned_path
            ):
                return
            os.rename(nested_path, parked_path)
            if install_replacement:
                os.mkdir(nested_path)
                with open(owned_path, "wb") as replacement_file:
                    replacement_file.write(b"unknown nested replacement\n")
            parent_changed = True

        with (
            self._modeled_windows_cleanup_context(open_binding),
            patch.object(
                _included_mutations,
                'before_included_transaction_rename_fallback',
                side_effect=change_parent_before_move,
            ),
            self.assertRaisesRegex(OSError, "cleanup parent changed"),
        ):
            _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "4" * 32,
                f"nested-parent-{label}",
            )

        self.assertTrue(parent_changed)
        self.assertEqual(len(bindings), 2)
        self.assertTrue(all(binding.closed for binding in bindings))
        self.assertTrue(all(binding.close_count == 1 for binding in bindings))
        with open(
            os.path.join(parked_path, "owned.txt"),
            "rb",
        ) as parked_file:
            self.assertEqual(parked_file.read(), b"recorded nested content\n")
        if install_replacement:
            with open(owned_path, "rb") as replacement_file:
                self.assertEqual(
                    replacement_file.read(),
                    b"unknown nested replacement\n",
                )
        else:
            self.assertFalse(os.path.lexists(nested_path))

    def _assert_windows_flat_cleanup_parent_change_is_preserved(
        self,
        *,
        install_replacement: bool,
    ) -> None:
        label = "replacement" if install_replacement else "relocation"
        root_path = os.path.join(self.godot_dir, f"flat-parent-{label}")
        parked_path = root_path + "-parked"
        owned_path = os.path.join(root_path, "owned.txt")
        os.mkdir(root_path)
        with open(owned_path, "wb") as owned_file:
            owned_file.write(b"recorded owned content\n")
        project_stat = os.lstat(self.godot_dir)
        project_identity = project_stat.st_dev, project_stat.st_ino
        snapshot = _included_snapshots.capture_included_tree(
            root_path,
            expected_parent_identity=project_identity,
        )
        bindings: list[_ModeledWindowsCleanupParentBinding] = []
        parent_changed = False

        def open_binding(
            path: str,
            identity: tuple[int, int],
        ) -> _ModeledWindowsCleanupParentBinding:
            binding = _ModeledWindowsCleanupParentBinding(path, identity)
            bindings.append(binding)
            return binding

        def change_parent_before_move(_source: str, _destination: str) -> None:
            nonlocal parent_changed
            if parent_changed:
                return
            os.rename(root_path, parked_path)
            if install_replacement:
                os.mkdir(root_path)
                with open(owned_path, "wb") as replacement_file:
                    replacement_file.write(b"unknown replacement content\n")
            parent_changed = True

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(_included_windows.sys, "platform", "win32"),
            patch.object(
                _included_windows.WindowsIncludedCleanupParentBinding,
                "open",
                side_effect=open_binding,
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
                _included_mutations,
                'before_included_transaction_rename_fallback',
                side_effect=change_parent_before_move,
            ),
            self.assertRaisesRegex(OSError, "cleanup parent changed"),
        ):
            _included_cleanup.cleanup_recorded_included_tree(
                root_path,
                snapshot,
                project_identity,
                "d" * 32,
                f"flat-parent-{label}",
            )

        self.assertTrue(parent_changed)
        self.assertEqual(len(bindings), 1)
        self.assertTrue(bindings[0].closed)
        self.assertEqual(bindings[0].close_count, 1)
        with open(
            os.path.join(parked_path, "owned.txt"),
            "rb",
        ) as parked_file:
            self.assertEqual(parked_file.read(), b"recorded owned content\n")
        if install_replacement:
            with open(owned_path, "rb") as replacement_file:
                self.assertEqual(
                    replacement_file.read(),
                    b"unknown replacement content\n",
                )
        else:
            self.assertFalse(os.path.lexists(root_path))

    def _assert_no_transaction_debris(self) -> None:
        self.assertEqual(
            _included_files_transaction_debris(self.godot_dir),
            (),
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
from src.conversion.included_files_parts import phase_observer as included_phase_observer
from src.conversion.included_files import IncludedFilesConverter

gm_path, godot_path, requested_phase = sys.argv[1:]

def stop_after_phase(current_phase: str) -> None:
    if current_phase == requested_phase:
        os._exit(86)

included_phase_observer.after_included_transaction_phase = stop_after_phase
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

    def _assert_project_lock_can_be_reacquired(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        _included_locking.release_included_project_lock(project_lock)

    def _assert_early_failure_releases_project_lock(
        self,
        phase: str,
        primary_error: BaseException,
        release_error: BaseException | None = None,
    ) -> None:
        previous_pair = self._pair_snapshot()
        converter = self._converter(max_workers=1)
        diagnostics = DiagnosticCollector()
        converter.diagnostics = diagnostics
        original_release = _included_locking.release_included_project_lock

        def release_then_fail(
            project_lock: included_files_module._IncludedProjectLock,
        ) -> None:
            original_release(project_lock)
            with self.assertRaises(OSError):
                os.fstat(project_lock.file_descriptor)
            if release_error is not None:
                raise release_error

        with (
            patch.object(
                _included_snapshots if phase in ("_capture_included_tree", "_capture_included_registry") else _included_recovery,
                phase[1:] if phase in ("_capture_included_tree", "_capture_included_registry") else phase[1:],
                side_effect=primary_error,
            ),
            patch.object(
                _included_locking,
                'release_included_project_lock',
                side_effect=release_then_fail,
            ) as release_lock,
            patch.object(
                _included_staging,
                'create_included_output_stage',
                side_effect=AssertionError("early failure staged output"),
            ) as create_stage,
        ):
            with self.assertRaises(type(primary_error)) as caught:
                converter.convert_all()

        self.assertIs(caught.exception, primary_error)
        release_lock.assert_called_once()
        create_stage.assert_not_called()
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self._assert_no_transaction_debris()
        self._assert_project_lock_can_be_reacquired()

        ordinary_failure = isinstance(primary_error, Exception)
        self.assertEqual(
            converter.conversion_step_result().resources.failed,
            int(ordinary_failure),
        )
        rejections = tuple(
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-INCLUDED-FILE-OUTPUT-REJECTED"
        )
        expected_rejection = (
            ordinary_failure and phase != "_recover_included_output_set"
        )
        self.assertEqual(len(rejections), int(expected_rejection))
        if expected_rejection:
            self.assertEqual(rejections[0].resource, "payload.txt")
            self.assertIn(str(primary_error), rejections[0].message)
        if release_error is not None:
            self.assertIn(
                "Included Files transaction lock release failed: "
                + str(release_error),
                getattr(primary_error, "__notes__", ()),
            )

    @staticmethod
    def _enforce_windows_included_files_scale_gate_environment() -> None:
        require_gate = (
            os.environ.get(
                "GM2GODOT_REQUIRE_WINDOWS_INCLUDED_FILES_SCALE_GATE"
            )
            == "1"
        )
        skip_gate = (
            os.environ.get(
                "GM2GODOT_SKIP_WINDOWS_INCLUDED_FILES_SCALE_GATE"
            )
            == "1"
        )
        if require_gate:
            if os.environ.get("GITHUB_ACTIONS") != "true":
                raise AssertionError(
                    "The Included Files scale gate may only be required by "
                    "GitHub Actions"
                )
            if skip_gate:
                raise AssertionError(
                    "The required Included Files scale gate cannot be skipped"
                )
        if skip_gate:
            if os.environ.get("GITHUB_ACTIONS") != "true":
                raise AssertionError(
                    "The Included Files scale gate may only be skipped by its "
                    "paired GitHub Actions job"
                )
            raise unittest.SkipTest(
                "covered by the dedicated native Windows Included Files "
                "scale job"
            )

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


included_files_transaction_debris = _included_files_transaction_debris
ModeledWindowsCleanupParentBinding = _ModeledWindowsCleanupParentBinding
