"""Included Files copy worker ownership."""

from __future__ import annotations
import posixpath
from src.conversion.included_files_parts.models import IncludedFileSource as _IncludedFileSource, IncludedCopyReceipt as _IncludedCopyReceipt, IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import file_publication as _included_file_publication
from src.conversion.included_files_parts.converter_ports import IncludedCopyWorkerPort

class IncludedCopyWorkerOperations(IncludedCopyWorkerPort):
    def _process_file(
        self: IncludedCopyWorkerPort,
        gm_file_path: str,
        godot_file_path: str,
        rel_path: str,
        owner_source_path: str = "datafiles",
        planned_receipt: _IncludedNoOpSourceReceipt | None = None,
    ) -> tuple[str, bool, _IncludedCopyReceipt | None] | None:
        if not self.conversion_running():
            return None
        self._resource_requested(rel_path)
        self._resource_started(rel_path)

        try:
            opened_source = self._open_confined_source_file(
                gm_file_path,
                owner_source_path=owner_source_path,
                resource=rel_path,
            )
            if opened_source is None:
                self._resource_failed(rel_path)
                return rel_path, False, None

            source_file, source_stat = opened_source
            with source_file:
                try:
                    if planned_receipt is not None:
                        active_project_path = (
                            self._active_output_project_path
                            or self.godot_project_path
                        )
                        output_components = _included_paths.included_output_components(
                            active_project_path,
                            godot_file_path,
                        )
                        assigned_path = posixpath.join(
                            *output_components[1:]
                        )
                        if (
                            planned_receipt.logical_path != rel_path
                            or planned_receipt.assigned_path != assigned_path
                            or self._capture_pinned_included_source_binding(
                                _IncludedFileSource(
                                    filesystem_path=gm_file_path,
                                    relative_path=rel_path,
                                    owner_source_path=owner_source_path,
                                ),
                                source_file,
                                source_stat,
                            )
                            != planned_receipt.binding
                        ):
                            raise OSError(
                                "GameMaker Included File planning receipt "
                                f"changed before staging: {rel_path}"
                            )
                    if planned_receipt is None:
                        copy_receipt = _included_file_publication.publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                        )
                    else:
                        copy_receipt = _included_file_publication.publish_confined_included_output(
                            self._active_output_project_path
                            or self.godot_project_path,
                            godot_file_path,
                            source_file,
                            source_stat,
                            planned_receipt,
                        )
                    if (
                        planned_receipt is not None
                        and self._capture_pinned_included_source_binding(
                            _IncludedFileSource(
                                filesystem_path=gm_file_path,
                                relative_path=rel_path,
                                owner_source_path=owner_source_path,
                            ),
                            source_file,
                            source_stat,
                        )
                        != planned_receipt.binding
                    ):
                        raise OSError(
                            "GameMaker Included File planning receipt changed "
                            f"while staging: {rel_path}"
                        )
                except (OSError, ValueError) as error:
                    self._resource_failed(rel_path)
                    self._report_included_file_output_rejection(
                        rel_path,
                        godot_file_path,
                        error,
                    )
                    return rel_path, False, None
        except Exception:
            self._resource_failed(rel_path)
            raise
        return rel_path, True, copy_receipt

    process_file = _process_file



_process_file = IncludedCopyWorkerOperations.process_file
process_file = _process_file
