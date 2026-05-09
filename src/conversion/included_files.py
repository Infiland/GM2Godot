from __future__ import annotations

import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback, StrPath


class IncludedFilesConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)

    def _process_file(self, gm_file_path: str, godot_file_path: str, rel_path: str) -> str | None:
        if not self.conversion_running():
            return None
        shutil.copy2(gm_file_path, godot_file_path)
        return rel_path

    def convert_included_files(self) -> None:
        gm_datafiles_path = os.path.join(self.gm_project_path, "datafiles")
        godot_included_path = os.path.join(self.godot_project_path, "included_files")

        if not os.path.exists(gm_datafiles_path):
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        os.makedirs(godot_included_path, exist_ok=True)

        # Collect all files, skipping .yy metadata files
        all_files: list[str] = []
        for root, _, files in os.walk(gm_datafiles_path):
            for file in files:
                if not file.endswith('.yy'):
                    all_files.append(os.path.join(root, file))

        if not all_files:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        # Pre-create all directories
        for gm_file_path in all_files:
            rel_path = os.path.relpath(gm_file_path, gm_datafiles_path)
            godot_dir = os.path.dirname(os.path.join(godot_included_path, rel_path))
            os.makedirs(godot_dir, exist_ok=True)

        total_files = len(all_files)
        processed_files = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[str | None], str] = {}
            for gm_file_path in all_files:
                rel_path = os.path.relpath(gm_file_path, gm_datafiles_path)
                godot_file_path = os.path.join(godot_included_path, rel_path)
                future = executor.submit(self._process_file, gm_file_path, godot_file_path, rel_path)
                futures_map[future] = rel_path

            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_IncludedFiles_Stopped"))
                    return

                processed_files += 1
                if self.compact_logging:
                    self._safe_log_progress(os.path.basename(result), processed_files, total_files)
                else:
                    self._safe_log(get_localized("Console_Convertor_IncludedFiles_Copied").format(path=result))
                self._safe_progress(int((processed_files / total_files) * 100))

    def convert_all(self) -> None:
        self.convert_included_files()
