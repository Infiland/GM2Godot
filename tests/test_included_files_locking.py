# pyright: reportPrivateUsage=false

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import patch

if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.included_files_parts import (
    constants as _included_constants,
    file_publication as _included_file_publication,
    guarded_mutations as _included_mutations,
    locking as _included_locking,
    native_posix as _included_posix,
    native_windows as _included_windows,
    record_io as _included_records,
)
from tests import included_files_support as _included_support

_included_files_transaction_debris = _included_support.included_files_transaction_debris


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
    def test_project_lock_released_after_early_interruption(self) -> None:
        self._write("payload.txt", "previous generation")
        self._converter(max_workers=1).convert_all()
        self._write("payload.txt", "new generation")
        for phase in (
            "_recover_included_output_set",
            "_capture_included_tree",
            "_capture_included_registry",
        ):
            for error_type in (KeyboardInterrupt, SystemExit, RuntimeError):
                with self.subTest(phase=phase, error=error_type.__name__):
                    self._assert_early_failure_releases_project_lock(
                        phase,
                        error_type("early interruption"),
                    )

    def test_project_lock_release_failure_preserves_early_error(self) -> None:
        self._write("payload.txt", "previous generation")
        self._converter(max_workers=1).convert_all()
        self._write("payload.txt", "new generation")
        for phase in (
            "_recover_included_output_set",
            "_capture_included_tree",
            "_capture_included_registry",
        ):
            for primary_type in (KeyboardInterrupt, SystemExit, RuntimeError):
                for release_type in (
                    OSError,
                    RuntimeError,
                    KeyboardInterrupt,
                    SystemExit,
                ):
                    with self.subTest(
                        phase=phase,
                        primary=primary_type.__name__,
                        release=release_type.__name__,
                    ):
                        self._assert_early_failure_releases_project_lock(
                            phase,
                            primary_type("primary interruption"),
                            release_type("secondary release failure"),
                        )

    def test_project_lock_release_is_once_for_lifecycle_returns(self) -> None:
        self._write("payload.txt", "initial generation")
        for outcome in ("success", "unchanged", "cancelled"):
            with self.subTest(outcome=outcome):
                self.running.set()
                converter = self._converter(max_workers=1)
                previous_pair = (
                    None if outcome == "success" else self._pair_snapshot()
                )
                if outcome == "cancelled":
                    self._write("payload.txt", "cancelled generation")
                original_release = (
                    _included_locking.release_included_project_lock
                )

                def release_and_check_closed(
                    project_lock: included_files_module._IncludedProjectLock,
                ) -> None:
                    original_release(project_lock)
                    with self.assertRaises(OSError):
                        os.fstat(project_lock.file_descriptor)

                def cancel_copy(*_arguments: object) -> None:
                    self.running.clear()

                with ExitStack() as context:
                    release_lock = context.enter_context(
                        patch.object(
                            _included_locking,
                            'release_included_project_lock',
                            side_effect=release_and_check_closed,
                        )
                    )
                    if outcome == "cancelled":
                        context.enter_context(
                            patch.object(
                                converter,
                                "_process_file",
                                side_effect=cancel_copy,
                            )
                        )
                    converter.convert_all()

                release_lock.assert_called_once()
                if previous_pair is not None:
                    self.assertEqual(self._pair_snapshot(), previous_pair)
                self.assertEqual(
                    converter.conversion_step_result().resources,
                    ConversionCounts(
                        requested=1,
                        executed=int(outcome != "cancelled"),
                        completed=int(outcome != "cancelled"),
                        skipped=int(outcome == "cancelled"),
                    ),
                )
                self._assert_no_transaction_debris()
                self._assert_project_lock_can_be_reacquired()

    def test_project_lock_acquisition_failure_does_not_release(self) -> None:
        self._write("payload.txt", "payload")
        for error_type in (OSError, KeyboardInterrupt, SystemExit):
            with self.subTest(error=error_type.__name__):
                primary_error = error_type("acquisition failed")
                converter = self._converter(max_workers=1)
                with (
                    patch.object(
                        _included_locking,
                        'acquire_included_project_lock',
                        side_effect=primary_error,
                    ),
                    patch.object(
                        _included_locking,
                        'release_included_project_lock',
                    ) as release_lock,
                ):
                    with self.assertRaises(error_type) as caught:
                        converter.convert_all()
                self.assertIs(caught.exception, primary_error)
                release_lock.assert_not_called()
                self.assertEqual(
                    converter.conversion_step_result().resources.failed,
                    int(isinstance(primary_error, Exception)),
                )

    def test_project_lock_release_ignores_caller_exception_context(self) -> None:
        for release_type in (OSError, RuntimeError, KeyboardInterrupt, SystemExit):
            with self.subTest(release=release_type.__name__):
                self._write("payload.txt", release_type.__name__)
                converter = self._converter(max_workers=1)
                messages: list[str] = []
                converter.log_callback = messages.append
                caller_error = RuntimeError("unrelated caller failure")
                release_error = release_type("release failed after success")
                original_release = (
                    _included_locking.release_included_project_lock
                )

                def release_then_fail(
                    project_lock: included_files_module._IncludedProjectLock,
                ) -> None:
                    original_release(project_lock)
                    raise release_error

                try:
                    raise caller_error
                except RuntimeError:
                    with patch.object(
                        _included_locking,
                        'release_included_project_lock',
                        side_effect=release_then_fail,
                    ) as release_lock:
                        if release_type is OSError:
                            converter.convert_all()
                        else:
                            with self.assertRaises(release_type) as caught:
                                converter.convert_all()
                            self.assertIs(caught.exception, release_error)

                release_lock.assert_called_once()
                self.assertEqual(getattr(caller_error, "__notes__", ()), ())
                warnings = tuple(
                    message
                    for message in messages
                    if message.startswith(
                        "Warning: Included Files transaction lock release failed: "
                    )
                )
                self.assertEqual(len(warnings), int(release_type is OSError))
                self._assert_no_transaction_debris()
                self._assert_project_lock_can_be_reacquired()

    def test_project_lock_released_after_stage_cleanup_interruption(self) -> None:
        self._write("payload.txt", "previous generation")
        converter = self._converter(max_workers=1)
        converter.convert_all()
        previous_pair = self._pair_snapshot()
        self._write("payload.txt", "new generation")
        primary_error = SystemExit("stage cleanup interrupted")
        release_error = KeyboardInterrupt("release interrupted")
        original_release = _included_locking.release_included_project_lock
        original_remove = _included_mutations.remove_owned_included_tree

        def cancel_copy(*_arguments: object) -> None:
            self.running.clear()

        def release_then_fail(
            project_lock: included_files_module._IncludedProjectLock,
        ) -> None:
            original_release(project_lock)
            raise release_error

        with (
            patch.object(converter, "_process_file", side_effect=cancel_copy),
            patch.object(
                _included_mutations,
                'remove_owned_included_tree',
                side_effect=primary_error,
            ) as remove_stage,
            patch.object(
                _included_locking,
                'release_included_project_lock',
                side_effect=release_then_fail,
            ) as release_lock,
        ):
            with self.assertRaises(SystemExit) as caught:
                converter.convert_all()

        self.assertIs(caught.exception, primary_error)
        release_lock.assert_called_once()
        remove_stage.assert_called_once()
        self.assertIsNone(converter._active_output_project_path)
        self.assertEqual(self._pair_snapshot(), previous_pair)
        self.assertIn(
            "Included Files transaction lock release failed: " + str(release_error),
            getattr(primary_error, "__notes__", ()),
        )
        original_remove(*remove_stage.call_args.args, **remove_stage.call_args.kwargs)
        self._assert_no_transaction_debris()
        self._assert_project_lock_can_be_reacquired()

    def test_project_lock_rejects_concurrent_included_files_transaction(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        with patch.object(
            tempfile,
            "gettempdir",
            side_effect=AssertionError(
                "the Included Files lock must not depend on a temp directory"
            ),
        ):
            first_lock = _included_locking.acquire_included_project_lock(
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
                    _included_locking.acquire_included_project_lock(
                        self.godot_dir,
                        project_identity,
                    )
            finally:
                _included_locking.release_included_project_lock(first_lock)

            with open(lock_path, "rb") as lock_file:
                self.assertEqual(
                    lock_file.read(),
                    _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                )
            self.assertEqual(
                (os.lstat(lock_path).st_dev, os.lstat(lock_path).st_ino),
                first_identity,
            )

            second_lock = _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )
            self.assertEqual(second_lock.path, lock_path)
            _included_locking.release_included_project_lock(second_lock)

        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
            )
        self.assertEqual(
            (os.lstat(lock_path).st_dev, os.lstat(lock_path).st_ino),
            first_identity,
        )

    def test_project_lock_rejects_ambiguous_existing_content_without_mutation(
        self,
    ) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        lock_content = _included_constants.INCLUDED_FILES_LOCK_CONTENT
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
                    _included_locking.acquire_included_project_lock(
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
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        with open(lock_path, "wb") as lock_file:
            lock_file.write(_included_constants.INCLUDED_FILES_LOCK_CONTENT)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_file_locking',
                side_effect=PermissionError("locked byte"),
            ) as locking,
            patch.object(
                os,
                "read",
                side_effect=AssertionError("locked byte was read before contention"),
            ) as read,
            self.assertRaisesRegex(OSError, "already publishing or recovering"),
        ):
            _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )

        locking.assert_called_once()
        self.assertEqual(locking.call_args.args[1], 2)
        read.assert_not_called()

    def test_modeled_windows_unknown_lock_is_unlocked_after_validation(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        lock_path = os.path.join(
            self.godot_dir,
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        existing_content = b"user-owned lock collision\n"
        with open(lock_path, "wb") as lock_file:
            lock_file.write(existing_content)
        locking_modes: list[int] = []

        def record_locking(_file_descriptor: int, mode: int) -> None:
            locking_modes.append(mode)

        with (
            patch.object(
                _included_posix,
                'included_descriptor_paths_supported',
                return_value=False,
            ),
            patch.object(os, "name", "nt"),
            patch.object(
                _included_windows,
                'windows_included_file_locking',
                side_effect=record_locking,
            ),
            self.assertRaisesRegex(OSError, "unknown or incomplete file"),
        ):
            _included_locking.acquire_included_project_lock(
                self.godot_dir,
                project_identity,
            )

        self.assertEqual(locking_modes, [2, 0])
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(lock_file.read(), existing_content)

    def test_project_lock_initialization_recovers_after_hard_exit(self) -> None:
        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import file_publication as included_file_publication
from src.conversion.included_files_parts import locking as included_locking

project_path, requested_phase = sys.argv[1:]

def stop_after_phase(phase: str) -> None:
    if phase == requested_phase:
        os._exit(86)

included_locking.after_included_lock_initialization_phase = stop_after_phase
project_identity = included_file_publication.ensure_included_output_project_root(
    project_path
)
included_locking.acquire_included_project_lock(
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
                _included_constants.INCLUDED_FILES_LOCK_CONTENT[
                    : len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) // 2
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
                    _included_constants.INCLUDED_FILES_LOCK_NAME,
                )
                temporary_paths = [
                    os.path.join(project_path, name)
                    for name in os.listdir(project_path)
                    if name.startswith(
                        _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
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
                        len(_included_constants.INCLUDED_FILES_LOCK_CONTENT),
                    )
                    with open(temporary_paths[0], "rb") as temporary_file:
                        self.assertEqual(
                            temporary_file.read(),
                            _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                        )

                project_identity = (
                    _included_file_publication.ensure_included_output_project_root(
                        project_path
                    )
                )
                project_lock = _included_locking.acquire_included_project_lock(
                    project_path,
                    project_identity,
                )
                _included_locking.release_included_project_lock(project_lock)

                with open(lock_path, "rb") as lock_file:
                    self.assertEqual(
                        lock_file.read(),
                        _included_constants.INCLUDED_FILES_LOCK_CONTENT,
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
                            _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
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
            _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
            + token
            + ".tmp",
        )
        tombstone_path = os.path.join(
            project_path,
            _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
            + token
            + ".tmp",
        )
        with open(temporary_path, "wb") as temporary_file:
            temporary_file.write(_included_constants.INCLUDED_FILES_LOCK_CONTENT)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        interruption_script = """
import os
import sys
from src.conversion import included_files as included_files_module
from src.conversion.included_files_parts import file_publication as included_file_publication
from src.conversion.included_files_parts import locking as included_locking

project_path = sys.argv[1]

def stop_after_phase(phase: str) -> None:
    if phase == "temporary-cleanup-quarantined":
        os._exit(86)

included_locking.after_included_lock_initialization_phase = stop_after_phase
project_identity = included_file_publication.ensure_included_output_project_root(
    project_path
)
included_locking.acquire_included_project_lock(
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
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
            )

        project_identity = (
            _included_file_publication.ensure_included_output_project_root(project_path)
        )
        project_lock = _included_locking.acquire_included_project_lock(
            project_path,
            project_identity,
        )
        _included_locking.release_included_project_lock(project_lock)
        self.assertFalse(os.path.lexists(tombstone_path))
        self.assertEqual(_included_files_transaction_debris(project_path), ())

    def test_project_lock_concurrent_initializers_publish_once(self) -> None:
        project_path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project_path)
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(project_path)
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
                project_lock = _included_locking.acquire_included_project_lock(
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
                _included_locking.release_included_project_lock(project_lock)

        with patch.object(
            _included_locking,
            'after_included_lock_initialization_phase',
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
            _included_constants.INCLUDED_FILES_LOCK_NAME,
        )
        with open(lock_path, "rb") as lock_file:
            self.assertEqual(
                lock_file.read(),
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
            )
        self.assertEqual(_included_files_transaction_debris(project_path), ())
        next_lock = _included_locking.acquire_included_project_lock(
            project_path,
            project_identity,
        )
        _included_locking.release_included_project_lock(next_lock)

    def test_project_lock_cleans_only_canonical_complete_temporaries(self) -> None:
        project_identity = (
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        prefix = _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
        cleanup_prefix = (
            _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
        )
        candidates = {
            prefix + "a" * 16 + ".tmp": (
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                False,
            ),
            prefix + "b" * 16 + ".tmp": (b"partial lock bytes", True),
            prefix + "c" * 15 + ".tmp": (
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            prefix + "e" * 16 + ".tmp": (
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            cleanup_prefix + "e" * 16 + ".tmp": (
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
                True,
            ),
            cleanup_prefix + "f" * 16 + ".tmp": (
                _included_constants.INCLUDED_FILES_LOCK_CONTENT,
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

        project_lock = _included_locking.acquire_included_project_lock(
            self.godot_dir,
            project_identity,
        )
        _included_locking.release_included_project_lock(project_lock)

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
            _included_file_publication.ensure_included_output_project_root(
                self.godot_dir
            )
        )
        candidate_paths = (
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_LOCK_TEMP_PREFIX
                + "d" * 16
                + ".tmp",
            ),
            os.path.join(
                self.godot_dir,
                _included_constants.INCLUDED_FILES_LOCK_CLEANUP_PREFIX
                + "e" * 16
                + ".tmp",
            ),
        )
        oversized_byte_count = (
            len(_included_constants.INCLUDED_FILES_LOCK_CONTENT) + 1
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
            _included_records,
            'read_included_lock_initialization_payload',
            side_effect=AssertionError(
                "oversized lock initialization payload was read"
            ),
        ) as payload_read:
            _included_locking.cleanup_included_lock_initialization_temporaries(
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


if __name__ == "__main__":
    unittest.main()
