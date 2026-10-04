"""Included Files worker pool ownership."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable, Iterable, TypeVar

from src.conversion.included_files_parts import constants as _included_constants
from src.conversion.type_defs import ConversionRunning

_IncludedWorkerItem = TypeVar("_IncludedWorkerItem")
_IncludedWorkerResult = TypeVar("_IncludedWorkerResult")

def _run_bounded_included_worker_phase(
    items: Iterable[_IncludedWorkerItem],
    *,
    max_workers: int,
    conversion_running: ConversionRunning,
    submit: Callable[
        [ThreadPoolExecutor, _IncludedWorkerItem],
        Future[_IncludedWorkerResult],
    ],
    consume: Callable[
        [_IncludedWorkerItem, Future[_IncludedWorkerResult]],
        bool,
    ],
) -> bool:
    """Run an Included Files phase with concurrency-proportional bookkeeping."""
    if max_workers < 1:
        raise ValueError("Included Files max_workers must be at least one")

    window_size = max_workers * _included_constants.INCLUDED_FILES_WORKER_WINDOW_MULTIPLIER
    item_iterator = iter(items)
    pending: dict[Future[_IncludedWorkerResult], _IncludedWorkerItem] = {}
    input_exhausted = False
    accepting_work = conversion_running()
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        while accepting_work:
            while not input_exhausted and len(pending) < window_size:
                if not conversion_running():
                    accepting_work = False
                    break
                try:
                    item = next(item_iterator)
                except StopIteration:
                    input_exhausted = True
                    break
                pending[submit(executor, item)] = item

            if not accepting_work or not pending:
                break

            done, _not_done = wait(
                tuple(pending),
                return_when=FIRST_COMPLETED,
            )
            completed = tuple(
                (future, pending[future])
                for future in tuple(pending)
                if future in done
            )
            for future, _item in completed:
                del pending[future]

            for future, item in completed:
                if not consume(item, future):
                    accepting_work = False
                    break
                if not conversion_running():
                    accepting_work = False
                    break

        return accepting_work and input_exhausted and not pending
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


run_bounded_included_worker_phase = _run_bounded_included_worker_phase

IncludedWorkerItem = _IncludedWorkerItem
IncludedWorkerResult = _IncludedWorkerResult
