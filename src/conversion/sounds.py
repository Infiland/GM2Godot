import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

class SoundConverter:   
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None):
        self.language = "EN"
        
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.godot_sounds_path = os.path.join(self.godot_project_path, 'sounds')
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running = conversion_running or (lambda: True)

    def find_sound_files(self):
        sound_folder = os.path.join(self.gm_project_path, 'sounds')
        sound_files = []
        for root, _, files in os.walk(sound_folder):
            sound_files.extend(
                os.path.join(root, file)
                for file in files
                if file.lower().endswith(('.wav', '.mp3', '.ogg'))
            )
        return sound_files

    def process_sound_file(self, gm_sound_path):
        if not self.conversion_running():
            return False

        rel_path = os.path.relpath(gm_sound_path, os.path.join(self.gm_project_path, 'sounds'))
        godot_sound_folder = os.path.join(self.godot_sounds_path, os.path.dirname(rel_path))
        os.makedirs(godot_sound_folder, exist_ok=True)

        godot_sound_path = os.path.join(self.godot_sounds_path, rel_path)
        shutil.copy2(gm_sound_path, godot_sound_path)

        self.log_callback(get_localized(self.language, 'Console_Convertor_Sounds_Converted').format(path=rel_path))
        return True

    def convert_sounds(self):
        os.makedirs(self.godot_sounds_path, exist_ok=True)
        sound_files = self.find_sound_files()

        if not sound_files:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Sounds_Error_NotFound'))
            return

        total_sounds = len(sound_files)
        processed_sounds = 0

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(self.process_sound_file, sound_file) for sound_file in sound_files]
            for future in as_completed(futures):
                if future.result():
                    processed_sounds += 1
                    if self.progress_callback:
                        self.progress_callback(int(processed_sounds / total_sounds * 100))
                else:
                    self.log_callback(get_localized(self.language, 'Console_Convertor_Sounds_Stopped'))
                    return
        self.log_callback(get_localized(self.language, 'Console_Convertor_Sounds_Complete'))
