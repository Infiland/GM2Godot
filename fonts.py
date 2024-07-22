import os

# WORK IN PROGRESS

class FontConverter:
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'fonts')
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running = conversion_running or (lambda: True)

    def convert_fonts(self):
        # Ensure the Godot project directory exists
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        # Find the fonts folder in the GameMaker project
        gm_sprites_path = os.path.join(self.gm_project_path, 'fonts')

        if not os.path.exists(gm_sprites_path):
            self.log_callback(f"Font folder not found in {self.gm_project_path}")
            return

        self.log_callback("Font conversion completed.")

    def convert_all(self):
        self.convert_fonts()