import os
import shutil

class SoundConverter:
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.godot_sounds_path = os.path.join(self.godot_project_path, 'sounds')
        self.log_callback = log_callback
        self.progress_callback = progress_callback

    def find_sound_files(self):
        sound_folder = os.path.join(self.gm_project_path, 'sounds')
        sound_files = []
        for root, dirs, files in os.walk(sound_folder):
            for file in files:
                if file.lower().endswith(('.wav', '.mp3', '.ogg')):
                    sound_files.append(os.path.join(root, file))
        return sound_files

    def convert_sounds(self):
        # Ensure the Godot sounds directory exists
        os.makedirs(self.godot_sounds_path, exist_ok=True)

        # Find all sound files
        sound_files = self.find_sound_files()

        if not sound_files:
            self.log_callback("No sound files found in the GameMaker project.")
            return

        total_sounds = len(sound_files)
        processed_sounds = 0

        # Process each sound file
        for gm_sound_path in sound_files:
            # Get the relative path from the GameMaker sounds folder
            rel_path = os.path.relpath(gm_sound_path, os.path.join(self.gm_project_path, 'sounds'))
            
            # Create the corresponding folder structure in Godot
            godot_sound_folder = os.path.join(self.godot_sounds_path, os.path.dirname(rel_path))
            os.makedirs(godot_sound_folder, exist_ok=True)

            # Copy the sound file to the Godot project
            godot_sound_path = os.path.join(self.godot_sounds_path, rel_path)
            shutil.copy2(gm_sound_path, godot_sound_path)

            self.log_callback(f"Converted: {rel_path} -> sounds/{rel_path}")

            processed_sounds += 1
            if self.progress_callback:
                self.progress_callback(int(processed_sounds / total_sounds * 100))

        self.log_callback("Sound conversion completed.")