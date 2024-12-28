from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.project_settings import ProjectSettingsConverter

# Import localization manager
from src.localization import get_localized, get_current_language

#WORK IN PROGRESS
class Converter:
    def __init__(self, log_callback, progress_callback):
        self.language = get_current_language()
        
        self.log = log_callback
        self.update_progress = progress_callback

    def convert(self, gm_path, godot_path, settings):
        project_settings_converter = ProjectSettingsConverter(gm_path, godot_path, self.log)

        converters = [
            ("game_icon", project_settings_converter.convert_icon, get_localized(self.language, 'Console_Convertor_Icon')),
            ("project_name", project_settings_converter.update_project_name, get_localized(self.language, 'Console_Convertor_Name')),
            ("project_settings", project_settings_converter.update_project_settings, get_localized(self.language, 'Console_Convertor_Settings')),
            ("audio_buses", project_settings_converter.generate_audio_bus_layout, get_localized(self.language, 'Console_Convertor_AudioBus')),
            ("sprites", lambda: SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Sprites')),
            ("fonts", lambda: FontConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Fonts')),
            ("tilesets", lambda: TileSetConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Tilesets')),
            ("sounds", lambda: SoundConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_sounds(), get_localized(self.language, 'Console_Convertor_Sounds')),
            ("notes", lambda: NoteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Notes'))
        ]

        for setting, converter, log_message in converters:
            if settings[setting].get():
                self.log(log_message)
                converter()
                self.update_progress(0)

        self.log(get_localized(self.language, 'Console_ConversionComplete'))
