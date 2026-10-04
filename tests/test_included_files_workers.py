# pyright: reportPrivateUsage=false

import os
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from typing import BinaryIO
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion import included_files as included_files_module
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.included_file_registry import INCLUDED_FILE_REGISTRY_RELATIVE_PATH
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.included_files_parts import (
    file_publication as _included_file_publication,
    worker_pool as _included_worker_pool,
)
from tests import included_files_support as _included_support

_included_files_transaction_debris = _included_support.included_files_transaction_debris


class TestIncludedFilesManagedRootTransaction(_included_support.IncludedManagedRootFixture):
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
                    _included_worker_pool.run_bounded_included_worker_phase(
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
        original_publish = _included_file_publication.publish_confined_included_output

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
            _included_file_publication,
            'publish_confined_included_output',
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


if __name__ == "__main__":
    unittest.main()
