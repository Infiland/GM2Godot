"""Shared native path checks and immutable Included Files stat projections."""

from __future__ import annotations

import os
import stat
from typing import Callable, cast

from src.conversion.included_files_parts.models import (
    HandleState,
    IncludedSourceFingerprint,
    PathFingerprint,
    PathHandleBinding,
)


def output_path_is_redirected(
    path: str,
    path_stat: os.stat_result,
) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def path_fingerprint(path_stat: os.stat_result) -> PathFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_mode,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_nlink,
    )


def path_handle_binding(
    file_stat: os.stat_result,
) -> PathHandleBinding:
    """Return metadata that is stable across path and handle stat on Windows."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        stat.S_IFMT(file_stat.st_mode),
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_nlink,
    )


def handle_state(file_stat: os.stat_result) -> HandleState:
    """Return metadata used to detect mutation of one open file handle."""

    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
        file_stat.st_nlink,
    )


def source_fingerprint(
    source_stat: os.stat_result,
) -> IncludedSourceFingerprint:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        source_stat.st_mode,
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )
