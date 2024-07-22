import os
import shutil
import re
import json
from PIL import Image
from typing import Optional, List, Callable

class ProjectSettingsConverter:
    def __init__(self, gm_project_path: str, godot_project_path: str, log_callback: Callable[[str], None] = print):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.log_callback = log_callback
        self.options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', 'options_windows.yy')
        self.options_main_path = os.path.join(self.gm_project_path, 'options', 'main', 'options_main.yy')

    def convert_icon(self) -> bool:
        gm_icon_path = os.path.join(self.gm_project_path, 'options', 'windows', 'icons')
        godot_ico_path = os.path.join(self.godot_project_path, 'icon.ico')
        godot_png_path = os.path.join(self.godot_project_path, 'icon.png')

        if not os.path.exists(gm_icon_path):
            self.log_callback(f"Icon directory not found: {gm_icon_path}")
            return False

        ico_files = [f for f in os.listdir(gm_icon_path) if f.endswith('.ico')]

        if not ico_files:
            self.log_callback("No .ico file found in the GameMaker project's icon directory.")
            return False

        source_ico = os.path.join(gm_icon_path, ico_files[0])

        try:
            shutil.copy2(source_ico, godot_ico_path)
            self.log_callback(f"Copied icon: {ico_files[0]} -> icon.ico")

            with Image.open(source_ico) as img:
                img.save(godot_png_path, 'PNG')
            self.log_callback(f"Converted icon: {ico_files[0]} -> icon.png")

            return True
        except Exception as e:
            self.log_callback(f"Error processing icon: {str(e)}")
            return False

    def get_gm_project_name(self) -> Optional[str]:
        yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
        if not yyp_files:
            self.log_callback("No .yyp file found in the GameMaker project folder.")
            return None

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(r'"%Name":\s*"([^"]*)"', content)
                return match.group(1) if match else None
        except Exception as e:
            self.log_callback(f"Error reading project name from .yyp file: {str(e)}")
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
            self.log_callback(f"Error reading {option_name} from {os.path.basename(file_path)}: {str(e)}")
            return None

    def update_project_name(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback("project.godot file not found in the Godot project directory.")
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            gm_project_name = self.get_gm_project_name()
            if gm_project_name:
                content = re.sub(r'config/name=".*"', f'config/name="{gm_project_name}"', content)
                self.log_callback(f"Updated project name to: {gm_project_name}")
            else:
                self.log_callback("Could not update project name: GameMaker project name not found.")

            with open(project_godot_path, 'w') as file:
                file.write(content)

        except Exception as e:
            self.log_callback(f"Error updating project name: {str(e)}")

    def update_project_settings(self) -> None:
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback("project.godot file not found in the Godot project directory.")
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            content = re.sub(r'config/icon="res://.*"', 'config/icon="res://icon.png"', content)

            settings_to_update = [
                ("option_windows_description_info", "config/description"),
                ("option_windows_version", "config/version"),
                ("option_windows_use_splash", "boot_splash/show_image"),
                ("option_game_speed", "run/max_fps"),
                ("option_windows_vsync", "window/vsync/vsync_mode"),
                ("option_windows_resize_window", "window/size/resizable"),
                ("option_windows_borderless", "window/size/borderless"),
                ("option_windows_interpolate_pixels", "textures/canvas_textures/default_texture_filter"),
                ("option_windows_start_fullscreen", "window/size/mode")
            ]

            for gm_option, godot_setting in settings_to_update:
                value = self.get_gm_option(gm_option, self.options_windows_path if "windows" in gm_option else self.options_main_path)
                if value:
                    content = self.update_godot_setting(content, godot_setting, value)

            with open(project_godot_path, 'w') as file:
                file.write(content)

            self.log_callback("Updated project.godot with GameMaker settings")
        except Exception as e:
            self.log_callback(f"Error updating project settings: {str(e)}")

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
            self.log_callback("No .yyp file found in the GameMaker project folder.")
            return []

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                yyp_content = file.read()
                
                audio_groups_match = re.search(r'"AudioGroups":\s*\[(.*?)\]', yyp_content, re.DOTALL)
                if not audio_groups_match:
                    self.log_callback("AudioGroups section not found in the .yyp file.")
                    return []

                audio_groups_content = audio_groups_match.group(1)
                audio_group_names = re.findall(r'"%Name":\s*"([^"]*)"', audio_groups_content)
                
                if not audio_group_names:
                    self.log_callback("No AudioGroup names found in the .yyp file.")
                    return []

                self.log_callback(f"Found AudioGroups: {', '.join(audio_group_names)}")
                return audio_group_names

        except Exception as e:
            self.log_callback(f"Error reading AudioGroups from .yyp file: {str(e)}")
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

            self.log_callback(f"Generated default_bus_layout.tres with {len(audio_groups)} audio buses.")
        except Exception as e:
            self.log_callback(f"Error generating default_bus_layout.tres: {str(e)}")