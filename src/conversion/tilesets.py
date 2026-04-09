import os

# Import localization manager
from src.localization import get_localized
from src.conversion.base_converter import BaseConverter

# WORK IN PROGRESS

class TileSetConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         max_workers=max_workers)
        self.godot_tilesets_path = os.path.join(self.godot_project_path, 'tilesets')

    def convert_tilesets(self):
        # Ensure the Godot project directory exists
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_tilesets_path, exist_ok=True)

        # Find the tilesets folder in the GameMaker project
        gm_tilesets_path = os.path.join(self.gm_project_path, 'tilesets')

        if not os.path.exists(gm_tilesets_path):
            self.log_callback(get_localized("Console_Convertor_Tilesets_Error_NotFound").format(project_path=self.gm_project_path))
            return

        self.log_callback(get_localized("Console_Convertor_Tilesets_NotImplemented"))

    def convert_all(self):
        self.convert_tilesets()
