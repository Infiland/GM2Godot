import os
import shutil
import re
import json
from PIL import Image
from typing import Optional, List, Callable

# Import localization manager
from src.localization import get_localized

class ProjectSettingsConverter:    
    def __init__(self, gm_project_path: str, gm_platform: str, godot_project_path: str, log_callback: Callable[[str], None] = print):
        self.language = "EN"
        
        self.gm_project_path = gm_project_path
        self.gm_platform = gm_platform
        self.godot_project_path = godot_project_path
        self.log_callback = log_callback

        self.options_platform_path = os.path.join(self.gm_project_path, 'options', self.gm_platform, f'options_{self.gm_platform}.yy')
        self.options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', f'options_windows.yy')
        self.options_main_path = os.path.join(self.gm_project_path, 'options', 'main', 'options_main.yy')

    def convert_icon(self) -> bool:
        gm_icon_path = os.path.join(self.gm_project_path, 'options', self.gm_platform, 'icons')
        godot_ico_path = os.path.join(self.godot_project_path, 'icon.ico')
        godot_png_path = os.path.join(self.godot_project_path, 'icon.png')

        if not os.path.exists(gm_icon_path):
            self.log_callback(get_localized(self.language, 'Console_Convertor_Icon_Error_DirectoryNotFound').format(gm_icon_path=gm_icon_path))
            return False

        icon_files = [f for f in os.listdir(gm_icon_path) if f.endswith('.ico') or f.endswith('.png')]

        if not (icon_files):
            self.log_callback(get_localized(self.language, 'Console_Convertor_Icon_Error_FileNotFound'))
            return False

        source_icon = os.path.join(gm_icon_path, icon_files[0])
            
        try:
            shutil.copy2(source_icon, godot_ico_path)
            self.log_callback(get_localized(self.language, 'Console_Convertor_Icon_Copied').format(icon_files=icon_files[0]))

            with Image.open(source_icon) as img:
                img.save(godot_png_path, 'PNG')
            self.log_callback(self.log_callback(get_localized(self.language, 'Console_Convertor_Icon_Converted').format(icon_files=icon_files[0])))
        
            return True
        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Error_IconGeneric').format(error=str(e)))
            return False

    def get_gm_project_name(self) -> Optional[str]:
        yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
        if not yyp_files:
            self.log_callback(self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_yypNotFound')))
            return None

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(r'"%Name":\s*"([^"]*)"', content)
                return match.group(1) if match else None
        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_yypNameNotRead').format(error=str(e)))
            return None

    def get_gm_option(self, option_name: str, file_path: str) -> Optional[str]:
        if not os.path.exists(file_path):
            self.log_callback(f"{os.path.basename(file_path)} file not found.")
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(f'"{option_name}":\\s*([^,\n]+)', content)
                return match.group(1).strip('"') if match else None
        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_yypGeneric').format(error=str(e)))
            return None

    def update_project_name(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_GD_NotFound'))
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            gm_project_name = self.get_gm_project_name()
            if gm_project_name:
                content = re.sub(r'config/name=".*"', f'config/name="{gm_project_name}"', content)
                self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_UpdatedName').format(gm_project_name=gm_project_name))
            else:
                self.log_callback("Could not update project name: GameMaker project name not found.")

            with open(project_godot_path, 'w') as file:
                file.write(content)

        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_NameGeneric').format(error=str(e)))

    def update_project_settings(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_GD_NotFound'))
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            content = re.sub(r'config/icon="res://.*"', 'config/icon="res://icon.png"', content)

            settings_to_update = [
                (f"option_windows_description_info", "config/description"),
                (f"option_{self.gm_platform}_version", "config/version"),
                (f"option_windows_use_splash", "boot_splash/show_image"),
                (f"option_game_speed", "run/max_fps"),
                (f"option_{self.gm_platform}_vsync", "window/vsync/vsync_mode"),
                (f"option_{self.gm_platform}_sync", "window/vsync/vsync_mode"),
                (f"option_{self.gm_platform}_resize_window", "window/size/resizable"),
                (f"option_windows_borderless", "window/size/borderless"),
                (f"option_{self.gm_platform}_interpolate_pixels", "textures/canvas_textures/default_texture_filter"),
                (f"option_{self.gm_platform}_start_fullscreen", "window/size/mode")
            ]

            for gm_option, godot_setting in settings_to_update:
                value = self.get_gm_option(gm_option, self.options_windows_path if 'windows' in gm_option else self.options_platform_path if self.gm_platform in gm_option else self.options_main_path)
                if value:
                    content = self.update_godot_setting(content, godot_setting, value)

            with open(project_godot_path, 'w') as file:
                file.write(content)

            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Updated'))
            
        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_NotUpdated').format(error=str(e)))

    def update_godot_setting(self, content: str, setting: str, value: str, section: str = "application") -> str:
        if section not in content:
            content += f"\n[{section}]\n"
        
        setting_pattern = f"{setting}\\s*=.*"
        
        if value.lower() in ['true', 'false']:
            new_setting = f'{setting}={value.lower()}'
        else:
            new_setting = f'{setting}="{value}"'
        
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
        yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
        if not yyp_files:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Settings_Error_yypNotFound'))
            return []

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                yyp_content = file.read()
                
                audio_groups_match = re.search(r'"AudioGroups":\s*\[(.*?)\]', yyp_content, re.DOTALL)
                if not audio_groups_match:
                    self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Error_SectionNotFound_GM'))
                    return []

                audio_groups_content = audio_groups_match.group(1)
                audio_group_names = re.findall(r'"%Name":\s*"([^"]*)"', audio_groups_content)
                
                if not audio_group_names:
                    self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Error_NameNotFound_GM'))

                    return []

                self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Group_Found').format(audio_group_names=', '.join(audio_group_names)))
                return audio_group_names

        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Error_Group_Generic').format(error=str(e)))
            return []

    def generate_audio_bus_layout(self) -> None:
        audio_groups = self.read_audio_groups()
        bus_layout_path = os.path.join(self.godot_project_path, 'default_bus_layout.tres')

        try:
            with open(bus_layout_path, 'w') as file:
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

            self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Group_Generated').format(audio_groups_num=len(audio_groups)))
            self.log_callback(f"Generated default_bus_layout.tres with {len(audio_groups)} audio buses.")
        except Exception as e:
            self.log_callback(get_localized(self.language, 'Console_Convertor_AudioBus_Error_GroupNotGenerated').format(error=str(e)))
