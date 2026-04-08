from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.shaders import ShaderConverter
from src.conversion.included_files import IncludedFilesConverter
from src.conversion.project_settings import ProjectSettingsConverter

from src.localization import get_localized


CONVERSION_CATEGORIES = {
    "assets": ["sprites", "fonts", "sounds", "included_files"],
    "project": ["game_icon", "project_name", "project_settings", "audio_buses", "notes"],
    "wip": ["objects", "shaders", "tilesets"],
}


class Converter:
    def __init__(self, log_callback, progress_callback, status_callback, conversion_running,
                 update_log_callback=None, compact_logging=False):
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.conversion_running = conversion_running
        self.update_log_callback = update_log_callback or log_callback
        self.compact_logging = compact_logging

    def convert(self, gm_path, gm_platform, godot_path, settings):
        project_settings = ProjectSettingsConverter(
            gm_path, godot_path, self.log_callback,
            self.progress_callback, self.conversion_running.is_set,
            gm_platform=gm_platform
        )

        converters = [
            ("game_icon", project_settings.convert_icon, "Console_Convertor_Icon"),
            ("project_name", project_settings.update_project_name, "Console_Convertor_Name"),
            ("project_settings", project_settings.update_project_settings, "Console_Convertor_Settings"),
            ("audio_buses", project_settings.generate_audio_bus_layout, "Console_Convertor_AudioBus"),
            ("sprites", lambda: SpriteConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set,
                update_log_callback=self.update_log_callback,
                compact_logging=self.compact_logging,
            ).convert_all(), "Console_Convertor_Sprites"),
            ("fonts", lambda: FontConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set
            ).convert_all(), "Console_Convertor_Fonts"),
            ("tilesets", lambda: TileSetConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set
            ).convert_all(), "Console_Convertor_Tilesets"),
            ("sounds", lambda: SoundConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set,
                update_log_callback=self.update_log_callback,
                compact_logging=self.compact_logging,
            ).convert_all(), "Console_Convertor_Sounds"),
            ("notes", lambda: NoteConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set,
                update_log_callback=self.update_log_callback,
                compact_logging=self.compact_logging,
            ).convert_all(), "Console_Convertor_Notes"),
            ("shaders", lambda: ShaderConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set,
                update_log_callback=self.update_log_callback,
                compact_logging=self.compact_logging,
            ).convert_all(), "Console_Convertor_Shaders"),
            ("included_files", lambda: IncludedFilesConverter(
                gm_path, godot_path, self.log_callback,
                self.progress_callback, self.conversion_running.is_set,
                update_log_callback=self.update_log_callback,
                compact_logging=self.compact_logging,
            ).convert_all(), "Console_Convertor_IncludedFiles"),
            ("objects", lambda: self.log_callback(
                get_localized("Console_Convertor_Objects_NotImplemented")
            ), "Console_Convertor_Objects"),
        ]

        for setting_key, converter_fn, log_key in converters:
            if settings[setting_key].get() and self.conversion_running.is_set():
                log_message = get_localized(log_key)
                self.log_callback(log_message)
                self.status_callback(log_message)
                converter_fn()
                self.progress_callback(0)
