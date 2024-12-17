import os
import shutil

# Import localization manager
from src.localization import get_localized

class NoteConverter:    
    def __init__(self, gm_path, godot_path, log_function, update_progress, check_running):
        self.language = "EN"
        
        self.gm_path = gm_path
        self.godot_path = godot_path
        self.log = log_function
        self.update_progress = update_progress
        self.check_running = check_running

    def convert_notes(self):
        gm_notes_path = os.path.join(self.gm_path, "notes")
        godot_notes_path = os.path.join(self.godot_path, "notes")

        if not os.path.exists(gm_notes_path):
            self.log(get_localized(self.language, 'Console_Convertor_Notes_Error_NotFound'))
            return

        if not os.path.exists(godot_notes_path):
            os.makedirs(godot_notes_path)

        total_notes = sum([len(files) for _, _, files in os.walk(gm_notes_path) if any(file.endswith('.txt') for file in files)])
        processed_notes = 0

        for root, dirs, files in os.walk(gm_notes_path):
            if not self.check_running():
                self.log(self.log(get_localized(self.language, 'Console_Convertor_Notes_Stopped')))
                return

            for file in files:
                if file.endswith('.txt'):
                    relative_path = os.path.relpath(root, gm_notes_path)
                    note_name = os.path.splitext(file)[0]
                    
                    godot_note_folder = os.path.join(godot_notes_path, note_name)
                    if not os.path.exists(godot_note_folder):
                        os.makedirs(godot_note_folder)
                    
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(godot_note_folder, file)
                    
                    shutil.copy2(src_file, dst_file)
                    
                    self.log(get_localized(self.language, 'Console_Convertor_Notes_Copied').format(note_name=note_name))
                    
                    processed_notes += 1
                    progress = int((processed_notes / total_notes) * 100)
                    self.update_progress(progress)

    def convert_all(self):
        self.convert_notes()
