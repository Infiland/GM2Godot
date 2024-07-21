import os
import shutil
import re
import json
from PIL import Image

class ProjectSettingsConverter:
    def __init__(self, gm_project_path, godot_project_path, log_callback=print):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.log_callback = log_callback
        self.options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', 'options_windows.yy')
        self.options_main_path = os.path.join(self.gm_project_path, 'options', 'main', 'options_main.yy')

    def convert_icon(self):
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

        if len(ico_files) > 1:
            self.log_callback(f"Multiple .ico files found. Using {ico_files[0]}")

        source_ico = os.path.join(gm_icon_path, ico_files[0])

        try:
            # Copy .ico file
            shutil.copy2(source_ico, godot_ico_path)
            self.log_callback(f"Copied icon: {ico_files[0]} -> icon.ico")

            # Convert .ico to .png
            with Image.open(source_ico) as img:
                img.save(godot_png_path, 'PNG')
            self.log_callback(f"Converted icon: {ico_files[0]} -> icon.png")

            return True
        except Exception as e:
            self.log_callback(f"Error processing icon: {str(e)}")
            return False

    def get_gm_project_name(self):
        yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
        if not yyp_files:
            self.log_callback("No .yyp file found in the GameMaker project folder.")
            return None

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                for i, line in enumerate(file):
                    if i == 2:  # This is really hardcoded since in .yyp the name of the game is found on the 3rd line. Need a fix later
                        match = re.search(r'"%Name":\s*"([^"]*)"', line)
                        if match:
                            return match.group(1)
                        else:
                            self.log_callback("Project name not found in the expected format.")
                            return None
                self.log_callback("Project name not found in the .yyp file.")
                return None
        except Exception as e:
            self.log_callback(f"Error reading project name from .yyp file: {str(e)}")
            return None
    
    def get_gm_option(self, option_name):
        if not os.path.exists(self.options_windows_path):
            self.log_callback(f"options_windows.yy file not found.")
            return None

        try:
            with open(self.options_windows_path, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(f'"{option_name}":\\s*([^,\n]+)', content)
                if match:
                    return match.group(1).strip('"')
                else:
                    self.log_callback(f"{option_name} not found in options_windows.yy file.")
                    return None
        except Exception as e:
            self.log_callback(f"Error reading {option_name} from options_windows.yy file: {str(e)}")
            return None

    # Same as get_gm_option but now reads options_main.yy
    def get_gm_option_main(self, option_name):
        if not os.path.exists(self.options_main_path):
            self.log_callback(f"options_main.yy file not found.")
            return None

        try:
            with open(self.options_main_path, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(f'"{option_name}":\\s*([^,\n]+)', content)
                if match:
                    return match.group(1).strip('"')
                else:
                    self.log_callback(f"{option_name} not found in options_main.yy file.")
                    return None
        except Exception as e:
            self.log_callback(f"Error reading {option_name} from options_main.yy file: {str(e)}")
            return None

    def update_project_name(self):
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback("project.godot file not found in the Godot project directory.")
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            # Update project name
            gm_project_name = self.get_gm_project_name()
            if gm_project_name:
                content = re.sub(
                    r'config/name=".*"',
                    f'config/name="{gm_project_name}"',
                    content
                )
                self.log_callback(f"Updated project name to: {gm_project_name}")
            else:
                self.log_callback("Could not update project name: GameMaker project name not found.")

            with open(project_godot_path, 'w') as file:
                file.write(content)

        except Exception as e:
            self.log_callback(f"Error updating project name: {str(e)}")

    def get_gm_description(self):
        options_windows_path = os.path.join(self.gm_project_path, 'options', 'windows', 'options_windows.yy')
        
        if not os.path.exists(options_windows_path):
            self.log_callback("options_windows.yy file not found.")
            return None

        try:
            with open(options_windows_path, 'r', encoding='utf-8') as file:
                content = file.read()
                match = re.search(r'"option_windows_description_info":\s*"([^"]*)"', content)
                if match:
                    return match.group(1)
                else:
                    self.log_callback("Description not found in options_windows.yy file.")
                    return None
        except Exception as e:
            self.log_callback(f"Error reading description from options_windows.yy file: {str(e)}")
            return None
    
    def update_project_settings(self):
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback("project.godot file not found in the Godot project directory.")
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            # Update icon path
            content = re.sub(
                r'config/icon="res://.*"',
                'config/icon="res://icon.png"',
                content
            )

            # Update description
            gm_description = self.get_gm_option("option_windows_description_info")
            if gm_description:
                content = self.update_godot_setting(content, "config/description", gm_description)

            # Update version
            gm_version = self.get_gm_option("option_windows_version")
            if gm_version:
                content = self.update_godot_setting(content, "config/version", gm_version)

            # Update splash screen
            gm_splash = self.get_gm_option("option_windows_use_splash")
            if gm_splash:
                boolean_value = json.loads(gm_splash.lower())
                content = self.update_godot_setting(content, "boot_splash/show_image", boolean_value)

            # Update framerate
            gm_framerate = self.get_gm_option_main("option_game_speed")
            if gm_framerate:
                content = self.update_godot_setting(content, "run/max_fps", gm_framerate.lower())

            # Update vsync
            gm_vsync = self.get_gm_option("option_windows_vsync")
            if gm_vsync:
                vsync_mode = "1" if gm_vsync.lower() == "true" else "0"
                content = self.update_godot_setting(content, "window/vsync/vsync_mode", vsync_mode.lower(), section="display")

            # Update resizable window - could be terrible lol
            gm_resize = self.get_gm_option("option_windows_resize_window")
            if gm_resize:
                resize_mode = "true" if gm_resize.lower() == "true" else "false"
                boolean_value = json.loads(resize_mode.lower())
                content = self.update_godot_setting(content, "window/size/resizable", boolean_value, section="display")

            # Update borderless window - could be terrible lol
            gm_borderless = self.get_gm_option("option_windows_borderless")
            if gm_borderless:
                borderless_mode = "true" if gm_borderless.lower() == "true" else "false"
                boolean_value = json.loads(borderless_mode.lower())
                content = self.update_godot_setting(content, "window/size/borderless", boolean_value, section="display")

            # Update Interpolate Colors
            gm_interpolate_colors = self.get_gm_option("option_windows_interpolate_pixels")
            if gm_interpolate_colors:
                interpolate_mode = "true" if gm_interpolate_colors.lower() == "true" else "false"
                content = self.update_godot_setting(content, "textures/canvas_textures/default_texture_filter", interpolate_mode, section="rendering")

            # Update fullscreen
            gm_fullscreen = self.get_gm_option("option_windows_start_fullscreen")
            if gm_fullscreen:
                fullscreen_mode = "3" if gm_fullscreen.lower() == "true" else "0"
                content = self.update_godot_setting(content, "window/size/mode", fullscreen_mode, section="display")

            with open(project_godot_path, 'w') as file:
                file.write(content)

            self.log_callback("Updated project.godot with GameMaker settings")
        except Exception as e:
            self.log_callback(f"Error updating project settings: {str(e)}")

    def update_godot_setting(self, content, setting, value, section="application"):
        section_pattern = f"\\[{section}\\]"
        if section not in content:
            content += f"\n[{section}]\n"
        
        setting_pattern = f"{setting}\\s*=.*"
        new_setting = f"{setting}=\"{value}\""
        
        if re.search(setting_pattern, content):
            content = re.sub(setting_pattern, new_setting, content)
        else:
            section_match = re.search(section_pattern, content)
            if section_match:
                insert_pos = section_match.end()
                content = content[:insert_pos] + f"\n{new_setting}" + content[insert_pos:]
            else:
                content += f"\n{new_setting}\n"
        
        return content

    def read_audio_groups(self):
        yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
        if not yyp_files:
            self.log_callback("No .yyp file found in the GameMaker project folder.")
            return []

        yyp_file = os.path.join(self.gm_project_path, yyp_files[0])
        try:
            with open(yyp_file, 'r', encoding='utf-8') as file:
                yyp_content = file.read()
                
                # Find the AudioGroups section
                audio_groups_match = re.search(r'"AudioGroups":\s*\[(.*?)\]', yyp_content, re.DOTALL)
                if not audio_groups_match:
                    self.log_callback("AudioGroups section not found in the .yyp file.")
                    return []

                audio_groups_content = audio_groups_match.group(1)
                
                # Extract individual AudioGroup names
                audio_group_names = re.findall(r'"%Name":\s*"([^"]*)"', audio_groups_content)
                
                if not audio_group_names:
                    self.log_callback("No AudioGroup names found in the .yyp file.")
                    return []

                self.log_callback(f"Found AudioGroups: {', '.join(audio_group_names)}")
                return audio_group_names

        except Exception as e:
            self.log_callback(f"Error reading AudioGroups from .yyp file: {str(e)}")
            return []

    def generate_audio_bus_layout(self):
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

                # Ensure there's always a Master bus
                if "audiogroup_default" not in audio_groups and "Master" not in audio_groups:
                    file.write('\nbus/{0}/name = "Master"\n'.format(len(audio_groups)))
                    file.write('bus/{0}/solo = false\n'.format(len(audio_groups)))
                    file.write('bus/{0}/mute = false\n'.format(len(audio_groups)))
                    file.write('bus/{0}/bypass_fx = false\n'.format(len(audio_groups)))
                    file.write('bus/{0}/volume_db = 0.0\n'.format(len(audio_groups)))
                    file.write('bus/{0}/send = "Master"\n'.format(len(audio_groups)))

            self.log_callback(f"Generated default_bus_layout.tres with {len(audio_groups)} audio buses.")
        except Exception as e:
            self.log_callback(f"Error generating default_bus_layout.tres: {str(e)}")

