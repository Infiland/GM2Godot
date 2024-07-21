import os
import shutil
import re
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

        ico_files = [f for f in os.listdir(gm_icon_path) if f.endswith('.ico')]

        if not ico_files:
            self.log_callback("No .ico file found in the GameMaker project's icon directory.")
            return False

        if len(ico_files) > 1: # Unlikely but just in case
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

    def convert_all(self):
        if self.convert_icon():
            self.update_project_godot()