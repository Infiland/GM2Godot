import os
import shutil
import re
from PIL import Image
from typing import Optional, List

# Import localization manager
from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    load_gamemaker_project_manifest,
    unsupported_project_option_diagnostics,
)
from src.conversion.type_defs import ConversionRunning, LogCallback, ProgressCallback

class ProjectSettingsConverter(BaseConverter):
    def __init__(self, gm_project_path: str, godot_project_path: str,
                 log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 gm_platform: str = 'windows',
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None,
                 project_manifest: GameMakerProjectManifest | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path,
                         log_callback, progress_callback, conversion_running,
                         max_workers=max_workers, diagnostics=diagnostics)
        self.gm_platform = gm_platform
        self.project_manifest = project_manifest or load_gamemaker_project_manifest(
            self.gm_project_path,
            target_platform=gm_platform,
        )
        self.options_platform_path = os.path.join(self.gm_project_path, 'options', self.gm_platform, f'options_{self.gm_platform}.yy')
        self.options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', f'options_windows.yy')
        self.options_main_path = os.path.join(self.gm_project_path, 'options', 'main', 'options_main.yy')

    def convert_icon(self) -> bool:
        gm_icon_path = os.path.join(self.gm_project_path, 'options', self.gm_platform, 'icons')
        godot_ico_path = os.path.join(self.godot_project_path, 'icon.ico')
        godot_png_path = os.path.join(self.godot_project_path, 'icon.png')

        if not os.path.exists(gm_icon_path):
            gm_icon_path = self._find_fallback_icon_path()
            if gm_icon_path is None:
                self.log_callback(get_localized("Console_Convertor_Icon_Error_DirectoryNotFound").format(
                    gm_icon_path=os.path.join(self.gm_project_path, 'options', self.gm_platform, 'icons')))
                return False

        icon_files = [f for f in os.listdir(gm_icon_path) if f.endswith('.ico') or f.endswith('.png')]

        if not (icon_files):
            self.log_callback(get_localized("Console_Convertor_Icon_Error_FileNotFound"))
            return False

        source_icon = os.path.join(gm_icon_path, icon_files[0])
            
        try:
            shutil.copy2(source_icon, godot_ico_path)
            self.log_callback(get_localized("Console_Convertor_Icon_Copied").format(icon_files=icon_files[0]))

            with Image.open(source_icon) as img:
                img.save(godot_png_path, 'PNG')
            self.log_callback(get_localized("Console_Convertor_Icon_Converted").format(icon_files=icon_files[0]))
        
            return True
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Error_IconGeneric").format(error=str(e)))
            return False

    def _find_fallback_icon_path(self) -> Optional[str]:
        """Search other platforms for an icon directory when the selected platform has none."""
        options_dir = os.path.join(self.gm_project_path, 'options')
        if not os.path.isdir(options_dir):
            return None

        for platform in os.listdir(options_dir):
            if platform == self.gm_platform:
                continue
            candidate = os.path.join(options_dir, platform, 'icons')
            if os.path.isdir(candidate):
                icon_files = [f for f in os.listdir(candidate) if f.endswith('.ico') or f.endswith('.png')]
                if icon_files:
                    self.log_callback(get_localized("Console_Convertor_Icon_Fallback").format(platform=platform))
                    return candidate

        return None

    def get_gm_project_name(self) -> Optional[str]:
        if self.project_manifest.yyp_path is None:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return None
        if not self.project_manifest.project_name:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNameNotRead").format(error="missing %Name/name"))
            return None
        return self.project_manifest.project_name

    def get_gm_option(self, option_name: str, file_path: str) -> Optional[str]:
        option = self.project_manifest.get_option(
            option_name,
            self._platform_from_options_path(file_path),
        )
        if option is not None:
            return self._option_value_as_string(option.value)
        if not os.path.exists(file_path):
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return None
        return None

    def update_project_name(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized("Console_Error_MissingGodotFile"))
            return

        try:
            with open(project_godot_path, 'r', encoding='utf-8') as file:
                content = file.read()

            gm_project_name = self.get_gm_project_name()
            if gm_project_name:
                content = re.sub(r'config/name=".*"', f'config/name="{gm_project_name}"', content)
                self.log_callback(get_localized("Console_Convertor_Settings_UpdatedName").format(gm_project_name=gm_project_name))
            else:
                self.log_callback(get_localized("Console_Convertor_Settings_Error_Name_GM"))

            with open(project_godot_path, 'w', encoding='utf-8') as file:
                file.write(content)

        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_NameGeneric").format(error=str(e)))

    def update_project_settings(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized("Console_Error_MissingGodotFile"))
            return

        try:
            with open(project_godot_path, 'r', encoding='utf-8') as file:
                content = file.read()

            content = re.sub(r'config/icon="res://.*"', 'config/icon="res://icon.png"', content)

            for gm_option, platform, godot_setting, value_kind in self._project_setting_mappings():
                option = self.project_manifest.get_option(gm_option, platform)
                if option is not None:
                    value = self._godot_project_setting_value(option.value, value_kind)
                    content = self.update_godot_setting(content, godot_setting, value)

            for diagnostic in unsupported_project_option_diagnostics(
                self.project_manifest,
                target_platform=self.gm_platform,
                supported_keys=self._supported_project_option_keys(),
            ):
                self._safe_log(f"Warning: {diagnostic.message}")

            with open(project_godot_path, 'w', encoding='utf-8') as file:
                file.write(content)

            self.log_callback(get_localized("Console_Convertor_Settings_Updated"))
            
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_NotUpdated").format(error=str(e)))

    def update_godot_setting(self, content: str, setting: str, value: object, section: str = "application") -> str:
        if section not in content:
            content += f"\n[{section}]\n"
        
        setting_pattern = f"{setting}\\s*=.*"
        new_setting = f'{setting}={self._format_godot_value(value)}'
        
        if re.search(setting_pattern, content):
            content = re.sub(setting_pattern, new_setting, content)
        else:
            section_match = re.search(f"\\[{section}\\]", content)
            if section_match:
                insert_pos = section_match.end()
                content = f"{content[:insert_pos]}\n{new_setting}{content[insert_pos:]}"
            else:
                content += f"\n{new_setting}\n"
        
        return content

    def read_audio_groups(self) -> List[str]:
        if self.project_manifest.yyp_path is None:
            self.log_callback(get_localized("Console_Convertor_Settings_Error_yypNotFound"))
            return []
        audio_group_names = self.project_manifest.audio_group_names()
        if not audio_group_names:
            self.log_callback(get_localized("Console_Convertor_AudioBus_Error_SectionNotFound_GM"))
            return []
        self.log_callback(get_localized("Console_Convertor_AudioBus_Group_Found").format(audio_group_names=', '.join(audio_group_names)))
        return audio_group_names

    def _project_setting_mappings(self) -> list[tuple[str, str, str, str]]:
        return [
            ("option_windows_description_info", "windows", "config/description", "string"),
            (f"option_{self.gm_platform}_version", self.gm_platform, "config/version", "string"),
            ("option_windows_use_splash", "windows", "boot_splash/show_image", "bool"),
            ("option_game_speed", "main", "run/max_fps", "int"),
            (f"option_{self.gm_platform}_vsync", self.gm_platform, "window/vsync/vsync_mode", "vsync"),
            (f"option_{self.gm_platform}_sync", self.gm_platform, "window/vsync/vsync_mode", "vsync"),
            (f"option_{self.gm_platform}_resize_window", self.gm_platform, "window/size/resizable", "bool"),
            ("option_windows_borderless", "windows", "window/size/borderless", "bool"),
            (
                f"option_{self.gm_platform}_interpolate_pixels",
                self.gm_platform,
                "textures/canvas_textures/default_texture_filter",
                "texture_filter",
            ),
            (f"option_{self.gm_platform}_start_fullscreen", self.gm_platform, "window/size/mode", "fullscreen"),
        ]

    def _supported_project_option_keys(self) -> set[str]:
        return {key for key, _platform, _setting, _kind in self._project_setting_mappings()}

    def _platform_from_options_path(self, file_path: str) -> str:
        options_root = os.path.join(self.gm_project_path, "options")
        try:
            relative = os.path.relpath(file_path, options_root)
        except ValueError:
            relative = os.path.basename(file_path)
        parts = relative.split(os.sep)
        if len(parts) > 1 and parts[0]:
            return parts[0]
        filename = os.path.splitext(os.path.basename(file_path))[0]
        if filename.startswith("options_"):
            return filename[len("options_"):]
        return "main"

    @staticmethod
    def _option_value_as_string(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _godot_project_setting_value(self, value: object, value_kind: str) -> object:
        if value_kind == "bool":
            return self._bool_option(value)
        if value_kind == "int":
            return self._int_option(value)
        if value_kind == "vsync":
            return 1 if self._bool_option(value) else 0
        if value_kind == "texture_filter":
            return 1 if self._bool_option(value) else 0
        if value_kind == "fullscreen":
            return 3 if self._bool_option(value) else 0
        return value

    @staticmethod
    def _bool_option(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value != 0
        return str(value).casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _int_option(value: object) -> int:
        if isinstance(value, bool):
            return 1 if value else 0
        if not isinstance(value, (int, float, str)):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _format_godot_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        value_text = str(value)
        lowered = value_text.casefold()
        if lowered in {"true", "false"}:
            return lowered
        if re.fullmatch(r"-?\d+(?:\.\d+)?", value_text):
            return value_text
        escaped = value_text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def generate_audio_bus_layout(self) -> None:
        audio_groups = self.read_audio_groups()
        bus_layout_path = os.path.join(self.godot_project_path, 'default_bus_layout.tres')

        try:
            with open(bus_layout_path, 'w', encoding='utf-8') as file:
                file.write('[gd_resource type="AudioBusLayout" format=3 uid="uid://cvoahc3k1xyrn"]\n\n')
                file.write('[resource]\n')
                
                for i, group in enumerate(audio_groups):
                    bus_name = "Master" if group == "audiogroup_default" else group
                    file.write(f'bus/{i}/name = "{bus_name}"\n')
                    file.write(f'bus/{i}/solo = false\n')
                    file.write(f'bus/{i}/mute = false\n')
                    file.write(f'bus/{i}/bypass_fx = false\n')
                    file.write(f'bus/{i}/volume_db = 0.0\n')
                    file.write(f'bus/{i}/send = "Master"\n')
                    if i < len(audio_groups) - 1:
                        file.write('\n')

                if "audiogroup_default" not in audio_groups and "Master" not in audio_groups:
                    i = len(audio_groups)
                    file.write(f'\nbus/{i}/name = "Master"\n')
                    file.write(f'bus/{i}/solo = false\n')
                    file.write(f'bus/{i}/mute = false\n')
                    file.write(f'bus/{i}/bypass_fx = false\n')
                    file.write(f'bus/{i}/volume_db = 0.0\n')
                    file.write(f'bus/{i}/send = "Master"\n')

            self.log_callback(get_localized("Console_Convertor_AudioBus_Group_Generated").format(audio_groups_num=len(audio_groups)))
            self.log_callback(f"Generated default_bus_layout.tres with {len(audio_groups)} audio buses.")
        except Exception as e:
            self.log_callback(get_localized("Console_Convertor_AudioBus_Error_GroupNotGenerated").format(error=str(e)))

    def convert_all(self) -> None:
        self.convert_icon()
        self.update_project_name()
        self.update_project_settings()
        self.generate_audio_bus_layout()
