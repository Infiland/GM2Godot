import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter


class NoteConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False, max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)

    def _process_note(self, src_file, dst_file, note_name):
        if not self.conversion_running():
            return None
        shutil.copy2(src_file, dst_file)
        return note_name

    def convert_notes(self):
        gm_notes_path = os.path.join(self.gm_project_path, "notes")
        godot_notes_path = os.path.join(self.godot_project_path, "notes")

        if not os.path.exists(gm_notes_path):
            self.log_callback(get_localized("Console_Convertor_Notes_Error_NotFound"))
            return

        os.makedirs(godot_notes_path, exist_ok=True)

        # Collect all note files
        note_files = []
        for root, dirs, files in os.walk(gm_notes_path):
            for file in files:
                if file.endswith('.txt'):
                    note_files.append(os.path.join(root, file))

        if not note_files:
            return

        # Pre-create all directories
        for src_file in note_files:
            note_name = os.path.splitext(os.path.basename(src_file))[0]
            os.makedirs(os.path.join(godot_notes_path, note_name), exist_ok=True)

        total_notes = len(note_files)
        processed_notes = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {}
            for src_file in note_files:
                note_name = os.path.splitext(os.path.basename(src_file))[0]
                dst_file = os.path.join(godot_notes_path, note_name, os.path.basename(src_file))
                future = executor.submit(self._process_note, src_file, dst_file, note_name)
                futures_map[future] = note_name

            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Notes_Stopped"))
                    return

                processed_notes += 1
                if self.compact_logging:
                    self._safe_log_progress(result, processed_notes, total_notes)
                else:
                    self._safe_log(get_localized("Console_Convertor_Notes_Copied").format(note_name=result))
                self._safe_progress(int((processed_notes / total_notes) * 100))

    def convert_all(self):
        self.convert_notes()
