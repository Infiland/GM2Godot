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

    def update_project_godot(self):
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

            self.log_callback("Updated project.godot: Set icon path to res://icon.png and updated project name")
        except Exception as e:
            self.log_callback(f"Error updating project.godot: {str(e)}")
    
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

    def convert_all(self):
        try:
            if self.convert_icon():
                self.update_project_godot()
        except Exception as e:
            self.log_callback(f"No icon found: {str(e)}")
        
        self.generate_audio_bus_layout()