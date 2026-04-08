import os
import shutil

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter


class IncludedFilesConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging)

    def convert_included_files(self):
        gm_datafiles_path = os.path.join(self.gm_project_path, "datafiles")
        godot_included_path = os.path.join(self.godot_project_path, "included_files")

        if not os.path.exists(gm_datafiles_path):
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        if not os.path.exists(godot_included_path):
            os.makedirs(godot_included_path)

        # Collect all files, skipping .yy metadata files
        all_files = []
        for root, dirs, files in os.walk(gm_datafiles_path):
            for file in files:
                if not file.endswith('.yy'):
                    all_files.append(os.path.join(root, file))

        if not all_files:
            self.log_callback(get_localized("Console_Convertor_IncludedFiles_Error_NotFound"))
            return

        total_files = len(all_files)
        processed_files = 0

        for gm_file_path in all_files:
            if not self.conversion_running():
                self.log_callback(get_localized("Console_Convertor_IncludedFiles_Stopped"))
                return

            rel_path = os.path.relpath(gm_file_path, gm_datafiles_path)
            godot_file_path = os.path.join(godot_included_path, rel_path)

            godot_file_dir = os.path.dirname(godot_file_path)
            if not os.path.exists(godot_file_dir):
                os.makedirs(godot_file_dir)

            shutil.copy2(gm_file_path, godot_file_path)

            processed_files += 1
            if self.compact_logging:
                self._log_progress(os.path.basename(rel_path), processed_files, total_files)
            else:
                self.log_callback(get_localized("Console_Convertor_IncludedFiles_Copied").format(path=rel_path))
            progress = int((processed_files / total_files) * 100)
            if self.progress_callback:
                self.progress_callback(progress)

    def convert_all(self):
        self.convert_included_files()
