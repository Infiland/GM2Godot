"""Included Files driver ownership."""

from __future__ import annotations

import os
import secrets
from concurrent.futures import Future, ThreadPoolExecutor

from src.conversion.atomic_generated_text import atomic_write_confined_generated_text
from src.conversion.included_file_paths import (
    canonical_included_file_lookup_path,
    plan_included_file_paths,
)
from src.conversion.included_file_registry import render_included_file_registry
from src.conversion.included_files_parts import (
    constants as _included_constants,
    file_publication as _included_file_publication,
    guarded_mutations as _included_mutations,
    locking as _included_locking,
    publisher as _included_publisher,
    recovery as _included_recovery,
    recovery_codec as _included_codec,
    source_snapshots as _included_snapshots,
    staging as _included_staging,
    stat_metadata as _included_metadata,
    worker_pool as _included_worker_pool,
)
from src.conversion.included_files_parts.converter_ports import IncludedDriverPort
from src.conversion.included_files_parts.models import (
    IncludedCopyReceipt as _IncludedCopyReceipt,
    IncludedFileSource as _IncludedFileSource,
    IncludedGenerationContentReceipt as _IncludedGenerationContentReceipt,
    IncludedOutputSetCancelled as _IncludedOutputSetCancelled,
    IncludedOutputSetTransaction as _IncludedOutputSetTransaction,
    IncludedRegistrySnapshot as _IncludedRegistrySnapshot,
    IncludedTreeSnapshot as _IncludedTreeSnapshot,
    PathIdentity as _PathIdentity,
)
from src.conversion.project_source_paths import ProjectSourcePathError
from src.localization import get_localized


class IncludedDriverOperations(IncludedDriverPort):
    def convert_included_files(self: IncludedDriverPort) -> None:
        plan = self._included_file_conversion_plan()
        for resource_key in plan.requested_keys:
            self._resource_requested(resource_key)
        for resource_key in plan.skipped_keys:
            self._resource_skipped(resource_key)

        planned_logical_paths: list[str] = []
        for logical_path in (
            *plan.requested_keys,
            *(source.relative_path for source in plan.available_files),
        ):
            try:
                canonical_included_file_lookup_path(logical_path)
            except ProjectSourcePathError:
                continue
            planned_logical_paths.append(logical_path)
        path_assignments = plan_included_file_paths(planned_logical_paths)
        assignments_by_source = {
            assignment.original_logical_path: assignment
            for assignment in path_assignments
        }

        if not plan.requested_keys:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
        all_files = list(plan.available_files)
        if path_assignments:
            self._report_included_file_path_collisions(path_assignments)
        emitted_logical_paths = {
            source.relative_path for source in all_files
        }

        project_identity = _included_file_publication.ensure_included_output_project_root(
            self.godot_project_path
        )
        lock_primary_error: BaseException | None = None
        try:
            project_lock = _included_locking.acquire_included_project_lock(
                self.godot_project_path,
                project_identity,
            )
        except Exception:
            for source in all_files:
                self._resource_failed(source.relative_path)
            raise
        try:
            try:
                recovery_message = _included_recovery.recover_included_output_set(
                    self.godot_project_path,
                    project_identity,
                )
                if recovery_message is not None:
                    self._safe_log("Recovered: " + recovery_message)
            except Exception:
                for source in all_files:
                    self._resource_failed(source.relative_path)
                raise
            public_root_path = os.path.join(
                self.godot_project_path,
                _included_constants.INCLUDED_FILES_ROOT_NAME,
            )
            previous_root_snapshot: _IncludedTreeSnapshot
            previous_registry_snapshot: _IncludedRegistrySnapshot
            try:
                previous_root_snapshot = _included_snapshots.capture_included_tree(
                    public_root_path,
                    expected_parent_identity=project_identity,
                )
                previous_registry_snapshot = _included_snapshots.capture_included_registry(
                    self.godot_project_path,
                    expected_project_identity=project_identity,
                )
            except Exception as error:
                for source in all_files:
                    self._resource_failed(source.relative_path)
                    assignment = assignments_by_source[source.relative_path]
                    self._report_included_file_output_rejection(
                        source.relative_path,
                        os.path.join(
                            public_root_path,
                            *assignment.assigned_output_path.split("/"),
                        ),
                        error,
                    )
                raise

            stage_container_path: str | None = None
            stage_container_identity: _PathIdentity | None = None
            active_error: BaseException | None = None
            transaction_committed = False
            transaction_cleanup_managed = False
            try:
                previous_content_receipts = _included_metadata.included_registry_receipts_from_tree(
                    previous_root_snapshot,
                    assignments_by_source,
                    emitted_logical_paths,
                )
                expected_registry_content = (
                    b""
                    if previous_content_receipts is None
                    else render_included_file_registry(
                        path_assignments,
                        emitted_logical_paths,
                        previous_content_receipts,
                    ).encode("utf-8")
                )
                generation_match = self._unchanged_included_generation_matches(
                    tuple(all_files),
                    assignments_by_source,
                    expected_registry_content,
                    previous_root_snapshot,
                    previous_registry_snapshot,
                    project_identity,
                    public_root_path,
                )
                if generation_match.unchanged:
                    for completed_count, source in enumerate(all_files, start=1):
                        self._resource_started(source.relative_path)
                        self._resource_completed(source.relative_path)
                        if self.compact_logging:
                            self._safe_log_progress(
                                os.path.basename(source.relative_path),
                                completed_count,
                                len(all_files),
                            )
                        else:
                            self._safe_log(
                                get_localized(
                                    "Console_Convertor_IncludedFiles_Unchanged"
                                ).format(path=source.relative_path)
                            )
                    self._safe_progress(100)
                    return
                planned_source_receipts = {
                    receipt.logical_path: receipt
                    for receipt in generation_match.source_receipts
                }

                source_byte_counts = self._preflight_included_source_byte_counts(
                    tuple(all_files)
                )
                preflight_registry_content = render_included_file_registry(
                    path_assignments,
                    emitted_logical_paths,
                    {
                        logical_path: (
                            source_byte_counts[logical_path],
                            _included_constants.INCLUDED_FILES_RECOVERY_PLACEHOLDER_SHA256,
                        )
                        for logical_path in emitted_logical_paths
                    },
                ).encode("utf-8")
                assigned_byte_counts = {
                    assignments_by_source[
                        source.relative_path
                    ].assigned_output_path: source_byte_counts[
                        source.relative_path
                    ]
                    for source in all_files
                }
                recovery_record_sizes = (
                    _included_codec.preflight_included_recovery_record_sizes(
                        self.godot_project_path,
                        project_identity,
                        assigned_byte_counts,
                        preflight_registry_content,
                        previous_root_snapshot,
                        previous_registry_snapshot,
                    )
                )
                publication_transaction_id = (
                    secrets.token_hex(16)
                    if len(planned_source_receipts) == len(all_files)
                    and all(
                        source.relative_path in planned_source_receipts
                        for source in all_files
                    )
                    else None
                )

                (
                    stage_container_path,
                    stage_container_identity,
                ) = _included_staging.create_included_output_stage(
                    self.godot_project_path,
                    project_identity,
                )
                staged_root_path = os.path.join(
                    stage_container_path,
                    _included_constants.INCLUDED_FILES_ROOT_NAME,
                )
                os.mkdir(staged_root_path, 0o755)
                staged_root_identity = _included_snapshots.included_directory_identity(staged_root_path)
                if staged_root_identity is None:
                    raise OSError("Included Files staging root disappeared")

                self._active_output_project_path = stage_container_path
                successful_logical_paths: set[str] = set()
                copy_receipts: dict[str, _IncludedCopyReceipt] = {}
                worker_failed = False
                worker_cancelled = False
                first_worker_error: BaseException | None = None
                processed_files = 0
                total_files = len(all_files)
                try:
                    def submit_copy(
                        executor: ThreadPoolExecutor,
                        source: _IncludedFileSource,
                    ) -> Future[
                        tuple[str, bool, _IncludedCopyReceipt | None] | None
                    ]:
                        assignment = assignments_by_source[source.relative_path]
                        staged_output_path = os.path.join(
                            staged_root_path,
                            *assignment.assigned_output_path.split("/"),
                        )
                        planned_receipt = planned_source_receipts.get(
                            source.relative_path
                        )
                        if planned_receipt is None:
                            return executor.submit(
                                self._process_file,
                                source.filesystem_path,
                                staged_output_path,
                                source.relative_path,
                                source.owner_source_path,
                            )
                        return executor.submit(
                            self._process_file,
                            source.filesystem_path,
                            staged_output_path,
                            source.relative_path,
                            source.owner_source_path,
                            planned_receipt,
                        )

                    def consume_copy(
                        _source: _IncludedFileSource,
                        future: Future[
                            tuple[str, bool, _IncludedCopyReceipt | None] | None
                        ],
                    ) -> bool:
                        nonlocal worker_failed
                        nonlocal worker_cancelled
                        nonlocal first_worker_error
                        nonlocal processed_files

                        try:
                            result = future.result()
                        except BaseException as error:
                            worker_failed = True
                            if first_worker_error is None:
                                first_worker_error = error
                            return False
                        if result is None:
                            worker_cancelled = True
                            return False

                        processed_files += 1
                        relative_path, copied, copy_receipt = result
                        if copied and copy_receipt is not None:
                            successful_logical_paths.add(relative_path)
                            copy_receipts[relative_path] = copy_receipt
                        else:
                            worker_failed = True
                        if total_files:
                            self._safe_progress(
                                min(
                                    99,
                                    int((processed_files / total_files) * 99),
                                )
                            )
                        return not worker_failed

                    phase_completed = _included_worker_pool.run_bounded_included_worker_phase(
                        all_files,
                        max_workers=self.max_workers,
                        conversion_running=self.conversion_running,
                        submit=submit_copy,
                        consume=consume_copy,
                    )
                    if not phase_completed and not worker_failed:
                        worker_cancelled = True
                finally:
                    self._active_output_project_path = None

                if worker_failed:
                    for source in all_files:
                        self._resource_failed(source.relative_path)
                    if first_worker_error is not None:
                        raise first_worker_error
                    raise OSError(
                        "Included Files output-set staging failed; the previous "
                        "managed output was preserved"
                    )
                if (
                    worker_cancelled
                    or not self.conversion_running()
                    or len(successful_logical_paths) != len(all_files)
                ):
                    for source in all_files:
                        self._resource_skipped(source.relative_path)
                    self.log_callback(
                        get_localized("Console_Convertor_IncludedFiles_Stopped")
                    )
                    return

                generation_content_receipts = (
                    tuple(
                        _IncludedGenerationContentReceipt(
                            transaction_id=publication_transaction_id,
                            generation_identity=staged_root_identity,
                            stage_container_identity=stage_container_identity,
                            source=planned_source_receipts[
                                source.relative_path
                            ],
                            staged_output_path=os.path.normcase(
                                os.path.abspath(
                                    os.path.join(
                                        staged_root_path,
                                        *assignments_by_source[
                                            source.relative_path
                                        ].assigned_output_path.split("/"),
                                    )
                                )
                            ),
                            public_output_path=os.path.normcase(
                                os.path.abspath(
                                    os.path.join(
                                        public_root_path,
                                        *assignments_by_source[
                                            source.relative_path
                                        ].assigned_output_path.split("/"),
                                    )
                                )
                            ),
                            output=copy_receipts[source.relative_path],
                        )
                        for source in all_files
                    )
                    if publication_transaction_id is not None
                    else ()
                )
                if generation_content_receipts:
                    if publication_transaction_id is None:
                        raise AssertionError(
                            "Generation receipts require a transaction id"
                        )
                    staged_root_snapshot = (
                        _included_snapshots.capture_included_tree_from_generation_receipts(
                            staged_root_path,
                            expected_parent_identity=stage_container_identity,
                            transaction_id=publication_transaction_id,
                            generation_identity=staged_root_identity,
                            stage_container_identity=stage_container_identity,
                            receipts=generation_content_receipts,
                        )
                    )
                else:
                    staged_root_snapshot = _included_snapshots.capture_included_tree(
                        staged_root_path,
                        expected_parent_identity=stage_container_identity,
                    )
                assigned_receipts = {
                    assignments_by_source[source.relative_path].assigned_output_path:
                        copy_receipts[source.relative_path]
                    for source in all_files
                }
                _included_metadata.verify_staged_included_inventory(
                    staged_root_snapshot,
                    assigned_receipts,
                )

                staged_registry_text = render_included_file_registry(
                    path_assignments,
                    emitted_logical_paths,
                    {
                        logical_path: (
                            receipt.byte_count,
                            receipt.sha256,
                        )
                        for logical_path, receipt in copy_receipts.items()
                    },
                )
                staged_registry_path = os.path.join(
                    stage_container_path,
                    "gml_included_file_registry.gd",
                )
                atomic_write_confined_generated_text(
                    staged_registry_path,
                    staged_registry_text,
                    confinement_root=stage_container_path,
                )
                staged_registry_state = _included_snapshots.included_regular_file_state(
                    staged_registry_path,
                    expected_parent_identity=stage_container_identity,
                )
                if staged_registry_state is None:
                    raise OSError("Included File registry staging candidate disappeared")
                if previous_registry_snapshot.file_mode is not None:
                    _included_mutations.chmod_exact_included_file(
                        staged_registry_path,
                        staged_registry_state[0],
                        previous_registry_snapshot.file_mode,
                        stage_container_identity,
                    )
                    staged_registry_state = _included_snapshots.included_regular_file_state(
                        staged_registry_path,
                        expected_parent_identity=stage_container_identity,
                        allowed_identities=frozenset({staged_registry_state[0]}),
                    )
                    if staged_registry_state is None:
                        raise OSError(
                            "Included File registry staging candidate disappeared"
                        )
                staged_registry_identity, staged_registry_mode, staged_registry_content = (
                    staged_registry_state
                )
                staged_container_snapshot = _included_staging.included_stage_container_snapshot(
                    project_identity,
                    stage_container_path,
                    stage_container_identity,
                    staged_root_snapshot,
                    staged_registry_identity,
                    staged_registry_content,
                )

                transaction = _IncludedOutputSetTransaction(
                    project_identity=project_identity,
                    stage_container_path=stage_container_path,
                    stage_container_identity=stage_container_identity,
                    staged_container_snapshot=staged_container_snapshot,
                    staged_root_path=staged_root_path,
                    staged_root_snapshot=staged_root_snapshot,
                    staged_registry_path=staged_registry_path,
                    staged_registry_identity=staged_registry_identity,
                    staged_registry_mode=staged_registry_mode,
                    staged_registry_content=staged_registry_content,
                    previous_root_snapshot=previous_root_snapshot,
                    previous_registry_snapshot=previous_registry_snapshot,
                    recovery_record_sizes=recovery_record_sizes,
                    publication_transaction_id=publication_transaction_id,
                    content_receipts=generation_content_receipts,
                )
                # From this handoff onward, only manifest-bound transaction
                # cleanup may remove the stage, including after rollback.
                transaction_cleanup_managed = True
                cleanup_warnings = _included_publisher.commit_included_output_set(
                    self.godot_project_path,
                    transaction,
                    self.conversion_running,
                )
                transaction_committed = True
                for cleanup_warning in cleanup_warnings:
                    self._safe_log(
                        "Warning: Included Files transaction cleanup failed: "
                        + cleanup_warning
                    )

                for source in all_files:
                    self._resource_completed(source.relative_path)
                    if self.compact_logging:
                        self._safe_log_progress(
                            os.path.basename(source.relative_path),
                            len(successful_logical_paths),
                            len(all_files),
                        )
                    else:
                        self._safe_log(
                            get_localized(
                                "Console_Convertor_IncludedFiles_Copied"
                            ).format(path=source.relative_path)
                        )
                self._safe_progress(100)
            except _IncludedOutputSetCancelled:
                for source in all_files:
                    self._resource_skipped(source.relative_path)
                self.log_callback(
                    get_localized("Console_Convertor_IncludedFiles_Stopped")
                )
                return
            except BaseException as error:
                active_error = error
                for source in all_files:
                    self._resource_failed(source.relative_path)
                raise
            finally:
                self._active_output_project_path = None
                recovery_pending = os.path.lexists(
                    os.path.join(
                        self.godot_project_path,
                        _included_constants.INCLUDED_FILES_JOURNAL_NAME,
                    )
                )
                if (
                    not transaction_cleanup_managed
                    and not recovery_pending
                    and stage_container_path is not None
                    and stage_container_identity is not None
                ):
                    try:
                        _included_mutations.remove_owned_included_tree(
                            stage_container_path,
                            stage_container_identity,
                            expected_parent_identity=project_identity,
                        )
                    except OSError as cleanup_error:
                        if active_error is not None:
                            active_error.add_note(
                                "Included Files staging cleanup also failed: "
                                + str(cleanup_error)
                            )
                        elif transaction_committed:
                            self._safe_log(
                                "Warning: Included Files staging cleanup failed: "
                                + str(cleanup_error)
                            )
                elif recovery_pending:
                    message = (
                        "Included Files recovery state was retained; the next "
                        "conversion will resume it"
                    )
                    if active_error is not None:
                        active_error.add_note(message)
                    else:
                        self._safe_log("Warning: " + message)
        except BaseException as error:
            lock_primary_error = error
            raise
        finally:
            try:
                _included_locking.release_included_project_lock(project_lock)
            except BaseException as lock_error:
                if lock_primary_error is not None:
                    lock_primary_error.add_note(
                        "Included Files transaction lock release failed: "
                        + str(lock_error)
                    )
                elif isinstance(lock_error, OSError):
                    self._safe_log(
                        "Warning: Included Files transaction lock release failed: "
                        + str(lock_error)
                    )
                else:
                    raise





convert_included_files = IncludedDriverOperations.convert_included_files
