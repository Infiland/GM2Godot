from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.project_settings import ProjectSettingsConverter

#WORK IN PROGRESS
class Converter:
    def __init__(self, log_callback, progress_callback):
        self.log = log_callback
        self.update_progress = progress_callback

    def convert(self, gm_path, godot_path, settings):
        project_settings_converter = ProjectSettingsConverter(gm_path, godot_path, self.log)

        converters = [
            ("game_icon", project_settings_converter.convert_icon, "Converting game icon..."),
            ("project_name", project_settings_converter.update_project_name, "Updating project name..."),
            ("project_settings", project_settings_converter.update_project_settings, "Updating project settings..."),
            ("audio_buses", project_settings_converter.generate_audio_bus_layout, "Generating audio bus layout..."),
            ("sprites", lambda: SpriteConverter(gm_path, godot_path, self.log, self.update_progress).convert_all(), "Converting sprites..."),
            ("fonts", lambda: FontConverter(gm_path, godot_path, self.log, self.update_progress).convert_all(), "Converting fonts..."),
            ("tilesets", lambda: TileSetConverter(gm_path, godot_path, self.log, self.update_progress).convert_all(), "Converting tilesets..."),
            ("sounds", lambda: SoundConverter(gm_path, godot_path, self.log, self.update_progress).convert_sounds(), "Converting sounds..."),
            ("notes", lambda: NoteConverter(gm_path, godot_path, self.log, self.update_progress).convert_all(), "Converting notes...")
        ]

        for setting, converter, log_message in converters:
            if settings[setting].get():
                self.log(log_message)
                converter()
                self.update_progress(0)

        self.log("Conversion complete!")