import os

# Import localization manager
from src.localization import get_localized
from src.conversion.base_converter import BaseConverter

# WORK IN PROGRESS

class FontConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running)
        self.godot_fonts_path = os.path.join(self.godot_project_path, 'fonts')

    def convert_fonts(self):
        # Ensure the Godot project directory exists
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_fonts_path, exist_ok=True)

        # Find the fonts folder in the GameMaker project
        gm_fonts_path = os.path.join(self.gm_project_path, 'fonts')

        if not os.path.exists(gm_fonts_path):
            self.log_callback(get_localized("Console_Convertor_Fonts_Error_NotFound").format(gm_project_path=self.gm_project_path))
            return

        self.log_callback(get_localized("Console_Convertor_Fonts_NotImplemented"))

    def convert_all(self):
        self.convert_fonts()
