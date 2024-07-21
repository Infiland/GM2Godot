import os
from PIL import Image
from collections import defaultdict
import shutil
import re

class SpriteConverter:
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None):
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'sprites')
        self.log_callback = log_callback
        self.progress_callback = progress_callback

    def find_sprite_images(self):
        sprite_folder = os.path.join(self.gm_project_path, 'sprites')
        image_files = defaultdict(list)
        for root, dirs, files in os.walk(sprite_folder):
            if 'layers' in root.split(os.path.sep):
                sprite_name = root.split(os.path.sep)[-3]  # Get the sprite name from the path
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        image_files[sprite_name].append(os.path.join(root, file))
        return image_files

    def convert_icon(self):
        gm_icon_path = os.path.join(self.gm_project_path, 'options', 'windows', 'icons')
        godot_ico_path = os.path.join(self.godot_project_path, 'icon.ico')
        godot_png_path = os.path.join(self.godot_project_path, 'icon.png')

        # Find .ico file in GameMaker directory
        ico_files = [f for f in os.listdir(gm_icon_path) if f.endswith('.ico')]

        if not ico_files:
            self.log_callback("No .ico file found in the GameMaker project's icon directory.")
            return False

        # Use the first .ico file if multiple are found
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

    def convert_sprites(self):
        # Ensure the Godot project directory exists
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        # Find the sprites folder in the GameMaker project
        gm_sprites_path = os.path.join(self.gm_project_path, 'sprites')

        if not os.path.exists(gm_sprites_path):
            self.log_callback(f"Sprites folder not found in {self.gm_project_path}")
            return

        # Find all sprite image files
        sprite_images = self.find_sprite_images()

        if not sprite_images:
            self.log_callback("No sprite images found in the GameMaker project.")
            return

        total_images = sum(len(images) for images in sprite_images.values())
        processed_images = 0

        # Process each sprite
        for sprite_name, images in sprite_images.items():
            # Create a folder for the sprite in the Godot project
            godot_sprite_folder = os.path.join(self.godot_sprites_path, sprite_name)
            os.makedirs(godot_sprite_folder, exist_ok=True)

            # Process each image for the sprite
            for index, gm_sprite_path in enumerate(sorted(images), start=1):
                # Determine the new filename
                new_filename = f"{sprite_name}_{index if len(images) > 1 else ''}.png"
                godot_sprite_path = os.path.join(godot_sprite_folder, new_filename)

                # Open the image, convert to PNG, and save in the Godot project
                with Image.open(gm_sprite_path) as img:
                    img.save(godot_sprite_path, 'PNG')

                self.log_callback(f"Converted: {os.path.relpath(gm_sprite_path, gm_sprites_path)} -> sprites/{sprite_name}/{new_filename}")

                processed_images += 1
                if self.progress_callback:
                    self.progress_callback(int(processed_images / total_images * 100))

        self.log_callback("Sprite conversion completed.")

    def update_project_godot(self):
        project_godot_path = os.path.join(self.godot_project_path, 'project.godot')
        
        if not os.path.exists(project_godot_path):
            self.log_callback("project.godot file not found in the Godot project directory.")
            return

        try:
            with open(project_godot_path, 'r') as file:
                content = file.read()

            updated_content = re.sub(
                r'config/icon="res://.*"',
                'config/icon="res://icon.png"',
                content
            )

            with open(project_godot_path, 'w') as file:
                file.write(updated_content)

            self.log_callback("Updated project.godot: Set icon path to res://icon.png")
        except Exception as e:
            self.log_callback(f"Error updating project.godot: {str(e)}")

    def convert_all(self):
        if self.convert_icon():
            self.update_project_godot()
        self.convert_sprites()