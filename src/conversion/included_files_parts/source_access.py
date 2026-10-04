"""Included Files source access ownership."""

from __future__ import annotations
import os
import posixpath
import stat
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from typing import BinaryIO
from src.conversion.included_file_paths import IncludedFilePathAssignment
from src.conversion.project_source_paths import ProjectSourcePathError, ResolvedProjectSourcePath
from src.conversion.included_files_parts.models import IncludedFileSource as _IncludedFileSource, IncludedSourceBinding as _IncludedSourceBinding, IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt, IncludedOutputSetCancelled as _IncludedOutputSetCancelled
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts import recovery_codec as _included_codec
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts import source_snapshots as _included_snapshots
from src.conversion.included_files_parts import worker_pool as _included_worker_pool
from src.conversion.included_files_parts.converter_ports import IncludedSourceAccessPort

class IncludedSourceAccessOperations(IncludedSourceAccessPort):
    def _open_confined_source_file(
        self: IncludedSourceAccessPort,
        filesystem_path: str,
        *,
        owner_source_path: str,
        resource: str,
        deny_writes: bool = False,
    ) -> tuple[BinaryIO, os.stat_result] | None:
        """Open a contained regular file and pin it against late path swaps."""
        resolved = self._resolve_discovered_project_source(
            filesystem_path,
            owner_source_path=owner_source_path,
            resource=resource,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            return None

        try:
            source_file = _included_fs.open_validation_stream(
                resolved.filesystem_path,
                deny_writes=deny_writes,
            )
        except OSError:
            return None

        try:
            opened_stat = os.fstat(source_file.fileno())
            revalidated = self._resolve_discovered_project_source(
                resolved.filesystem_path,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="included_file",
                field="discovered datafiles file",
            )
            if revalidated is None:
                source_file.close()
                return None
            current_stat = os.stat(revalidated.filesystem_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
            ):
                source_file.close()
                self._report_source_path_rejection(
                    filesystem_path,
                    ProjectSourcePathError(
                        "Discovered GameMaker source file changed after validation"
                    ),
                    owner_source_path=owner_source_path,
                    resource=resource,
                    resource_type="included_file",
                    field="discovered datafiles file",
                )
                return None
        except OSError:
            source_file.close()
            return None
        return source_file, opened_stat

    def _preflight_included_source_byte_counts(
        self: IncludedSourceAccessPort,
        sources: tuple[_IncludedFileSource, ...],
    ) -> dict[str, int]:
        """Capture byte counts without reading or staging payload bodies."""

        byte_counts: dict[str, int] = {}
        for source in sources:
            if not self.conversion_running():
                raise _IncludedOutputSetCancelled()
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    "recovery-record preflight: "
                    + source.relative_path
                )
            source_file, source_stat = opened_source
            with source_file:
                _included_codec.included_recovery_compact_integer_payload(
                    source_stat.st_size,
                    "source byte count",
                )
                byte_counts[source.relative_path] = source_stat.st_size
        return byte_counts

    def _capture_pinned_included_source_binding(
        self: IncludedSourceAccessPort,
        source: _IncludedFileSource,
        source_file: BinaryIO,
        expected_stat: os.stat_result,
    ) -> _IncludedSourceBinding:
        resolved = self._resolve_discovered_project_source(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            resource_type="included_file",
            field="discovered datafiles file",
        )
        if resolved is None:
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )

        lexical_stat = os.lstat(resolved.filesystem_path)
        path_stat = os.stat(resolved.filesystem_path)
        handle_stat = os.fstat(source_file.fileno())
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(handle_stat.st_mode)
            or not os.path.samestat(expected_stat, path_stat)
            or not os.path.samestat(path_stat, handle_stat)
            or _included_metadata.included_handle_state(handle_stat)
            != _included_metadata.included_handle_state(expected_stat)
            or _included_metadata.included_path_handle_binding(path_stat)
            != _included_metadata.included_path_handle_binding(handle_stat)
        ):
            raise OSError(
                "GameMaker Included File source changed during unchanged-"
                f"generation validation: {source.relative_path}"
            )
        canonical_path, directory_identities = (
            _included_snapshots.capture_included_source_directory_identities(
                self.gm_project_path,
                resolved.filesystem_path,
            )
        )
        _included_snapshots.verify_fallback_directory_ancestors(directory_identities)
        return _IncludedSourceBinding(
            filesystem_path=os.path.normcase(
                os.path.abspath(resolved.filesystem_path)
            ),
            canonical_path=canonical_path,
            directory_identities=directory_identities,
            lexical_state=_included_metadata.included_handle_state(lexical_stat),
            path_state=_included_metadata.included_handle_state(path_stat),
            handle_state=_included_metadata.included_handle_state(handle_stat),
        )

    def _capture_unchanged_source_receipt(
        self: IncludedSourceAccessPort,
        source: _IncludedFileSource,
        *,
        deny_writes: bool,
    ) -> _IncludedNoOpSourceReceipt:
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        opened_source = self._open_confined_source_file(
            source.filesystem_path,
            owner_source_path=source.owner_source_path,
            resource=source.relative_path,
            deny_writes=deny_writes,
        )
        if opened_source is None:
            raise OSError(
                "GameMaker Included File source became unavailable during "
                f"unchanged-generation validation: {source.relative_path}"
            )
        source_file, source_stat = opened_source
        with source_file:
            if source_file.tell() != 0:
                raise OSError(
                    "GameMaker Included File validation stream did not start "
                    f"at offset zero: {source.relative_path}"
                )
            before_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            byte_count, sha256 = _included_snapshots.digest_open_included_file(source_file)
            after_binding = self._capture_pinned_included_source_binding(
                source,
                source_file,
                source_stat,
            )
            if (
                after_binding != before_binding
                or byte_count != source_stat.st_size
            ):
                raise OSError(
                    "GameMaker Included File source changed while validating "
                    f"an unchanged generation: {source.relative_path}"
                )
        if not self.conversion_running():
            raise _IncludedOutputSetCancelled()
        return _IncludedNoOpSourceReceipt(
            logical_path=source.relative_path,
            assigned_path="",
            binding=before_binding,
            byte_count=byte_count,
            sha256=sha256,
        )

    def _collect_unchanged_source_receipts(
        self: IncludedSourceAccessPort,
        sources: tuple[_IncludedFileSource, ...],
        assignments_by_source: dict[str, IncludedFilePathAssignment],
        *,
        deny_writes: bool,
    ) -> dict[str, _IncludedNoOpSourceReceipt]:
        receipts: dict[str, _IncludedNoOpSourceReceipt] = {}

        def submit_receipt(
            executor: ThreadPoolExecutor,
            source: _IncludedFileSource,
        ) -> Future[_IncludedNoOpSourceReceipt]:
            return executor.submit(
                self._capture_unchanged_source_receipt,
                source,
                deny_writes=deny_writes,
            )

        def consume_receipt(
            source: _IncludedFileSource,
            future: Future[_IncludedNoOpSourceReceipt],
        ) -> bool:
            receipts[source.relative_path] = replace(
                future.result(),
                assigned_path=assignments_by_source[
                    source.relative_path
                ].assigned_output_path,
            )
            return True

        phase_completed = _included_worker_pool.run_bounded_included_worker_phase(
            sources,
            max_workers=self.max_workers,
            conversion_running=self.conversion_running,
            submit=submit_receipt,
            consume=consume_receipt,
        )
        if not phase_completed:
            raise _IncludedOutputSetCancelled()
        return receipts

    def _revalidate_unchanged_source_bindings(
        self: IncludedSourceAccessPort,
        sources: tuple[_IncludedFileSource, ...],
        receipts: dict[str, _IncludedNoOpSourceReceipt],
    ) -> None:
        for source in sources:
            opened_source = self._open_confined_source_file(
                source.filesystem_path,
                owner_source_path=source.owner_source_path,
                resource=source.relative_path,
                deny_writes=True,
            )
            if opened_source is None:
                raise OSError(
                    "GameMaker Included File source became unavailable during "
                    f"final unchanged-generation validation: {source.relative_path}"
                )
            source_file, source_stat = opened_source
            with source_file:
                current_binding = self._capture_pinned_included_source_binding(
                    source,
                    source_file,
                    source_stat,
                )
            if current_binding != receipts[source.relative_path].binding:
                raise OSError(
                    "GameMaker Included File source changed during final "
                    f"unchanged-generation validation: {source.relative_path}"
                )

    def _list_confined_directory(
        self: IncludedSourceAccessPort,
        directory: ResolvedProjectSourcePath,
    ) -> tuple[str, ...] | None:
        """List a contained directory without following a late path swap."""
        revalidated = self._resolve_discovered_project_source(
            directory.filesystem_path,
            owner_source_path=directory.source_path,
            resource=posixpath.basename(directory.source_path),
            resource_type="included_file",
            field="discovered datafiles directory",
        )
        if revalidated is None:
            return None

        # On POSIX, list through a validated directory descriptor. If the path
        # is exchanged after validation, the descriptor remains bound to the
        # original contained directory. Other platforms get a before/after
        # identity check around their path-based directory listing.
        if os.listdir in os.supports_fd and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            try:
                directory_fd = os.open(revalidated.filesystem_path, flags)
            except OSError:
                return None
            try:
                opened_stat = os.fstat(directory_fd)
                current = self._resolve_discovered_project_source(
                    revalidated.filesystem_path,
                    owner_source_path=directory.source_path,
                    resource=posixpath.basename(directory.source_path),
                    resource_type="included_file",
                    field="discovered datafiles directory",
                )
                if current is None:
                    return None
                current_stat = os.stat(current.filesystem_path)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or not os.path.samestat(opened_stat, current_stat)
                ):
                    self._report_directory_swap(directory)
                    return None
                return tuple(sorted(os.listdir(directory_fd)))
            except OSError:
                return None
            finally:
                os.close(directory_fd)

        try:
            before_stat = os.stat(revalidated.filesystem_path)
            entries = tuple(sorted(os.listdir(revalidated.filesystem_path)))
            current = self._resolve_discovered_project_source(
                revalidated.filesystem_path,
                owner_source_path=directory.source_path,
                resource=posixpath.basename(directory.source_path),
                resource_type="included_file",
                field="discovered datafiles directory",
            )
            if current is None:
                return None
            after_stat = os.stat(current.filesystem_path)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(before_stat.st_mode)
            or not os.path.samestat(before_stat, after_stat)
        ):
            self._report_directory_swap(directory)
            return None
        return entries

    def _collect_included_files(
        self: IncludedSourceAccessPort,
        datafiles: ResolvedProjectSourcePath,
    ) -> list[_IncludedFileSource]:
        included_files: list[_IncludedFileSource] = []
        pending_directories = [datafiles]
        visited_directories: set[str] = set()

        while pending_directories:
            directory = pending_directories.pop()
            canonical_directory = os.path.normcase(
                os.path.realpath(directory.filesystem_path)
            )
            if canonical_directory in visited_directories:
                continue
            visited_directories.add(canonical_directory)

            entry_names = self._list_confined_directory(directory)
            if entry_names is None:
                continue
            for entry_name in entry_names:
                entry = self._resolve_discovered_project_source(
                    os.path.join(directory.filesystem_path, entry_name),
                    owner_source_path=directory.source_path,
                    resource=entry_name,
                    resource_type="included_file",
                    field="discovered datafiles entry",
                )
                if entry is None:
                    continue
                if os.path.isdir(entry.filesystem_path):
                    # Match os.walk's historical default: contained directory
                    # symlinks are not traversed, while the datafiles root itself
                    # may still be a contained symlink.
                    if not os.path.islink(entry.filesystem_path):
                        pending_directories.append(entry)
                    continue
                if entry_name.endswith(".yy") or not os.path.isfile(
                    entry.filesystem_path
                ):
                    continue
                relative_path = posixpath.relpath(
                    entry.source_path,
                    datafiles.source_path,
                )
                included_files.append(
                    _IncludedFileSource(
                        filesystem_path=entry.filesystem_path,
                        relative_path=relative_path,
                        owner_source_path=directory.source_path,
                    )
                )
        return sorted(included_files, key=lambda item: item.relative_path)

    def _discovered_included_files(self: IncludedSourceAccessPort) -> tuple[_IncludedFileSource, ...]:
        """Return every contained regular payload under datafiles."""

        datafiles = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, "datafiles"),
            resource="datafiles",
            resource_type="included_file",
            field="datafiles directory",
        )
        if datafiles is None or not os.path.isdir(datafiles.filesystem_path):
            return ()
        return tuple(self._collect_included_files(datafiles))

    open_confined_source_file = _open_confined_source_file
    preflight_included_source_byte_counts = _preflight_included_source_byte_counts
    capture_pinned_included_source_binding = _capture_pinned_included_source_binding
    capture_unchanged_source_receipt = _capture_unchanged_source_receipt
    collect_unchanged_source_receipts = _collect_unchanged_source_receipts
    revalidate_unchanged_source_bindings = _revalidate_unchanged_source_bindings
    list_confined_directory = _list_confined_directory
    collect_included_files = _collect_included_files
    discovered_included_files = _discovered_included_files



















_open_confined_source_file = IncludedSourceAccessOperations.open_confined_source_file
open_confined_source_file = _open_confined_source_file
_preflight_included_source_byte_counts = IncludedSourceAccessOperations.preflight_included_source_byte_counts
preflight_included_source_byte_counts = _preflight_included_source_byte_counts
_capture_pinned_included_source_binding = IncludedSourceAccessOperations.capture_pinned_included_source_binding
capture_pinned_included_source_binding = _capture_pinned_included_source_binding
_capture_unchanged_source_receipt = IncludedSourceAccessOperations.capture_unchanged_source_receipt
capture_unchanged_source_receipt = _capture_unchanged_source_receipt
_collect_unchanged_source_receipts = IncludedSourceAccessOperations.collect_unchanged_source_receipts
collect_unchanged_source_receipts = _collect_unchanged_source_receipts
_revalidate_unchanged_source_bindings = IncludedSourceAccessOperations.revalidate_unchanged_source_bindings
revalidate_unchanged_source_bindings = _revalidate_unchanged_source_bindings
_list_confined_directory = IncludedSourceAccessOperations.list_confined_directory
list_confined_directory = _list_confined_directory
_collect_included_files = IncludedSourceAccessOperations.collect_included_files
collect_included_files = _collect_included_files
_discovered_included_files = IncludedSourceAccessOperations.discovered_included_files
discovered_included_files = _discovered_included_files
