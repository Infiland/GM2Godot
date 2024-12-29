import os
from PIL import Image
from collections import defaultdict

# Import localization manager
from src.localization import get_localized, get_current_language

class SpriteConverter:    
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None):
        self.language = get_current_language()
        
        self.gm_project_path = gm_project_path
        self.godot_project_path = godot_project_path
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'sprites')
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.conversion_running = conversion_running or (lambda: True)

    def find_sprite_images(self):
        sprite_folder = os.path.join(self.gm_project_path, 'sprites')
        image_files = defaultdict(list)
        for root, _, files in os.walk(sprite_folder):
            if 'layers' in root.split(os.path.sep):
                sprite_name = root.split(os.path.sep)[-3]
                image_files[sprite_name].extend(
                    os.path.join(root, file)
                    for file in files
                    if file.lower().endswith(('.png', '.jpg', '.jpeg'))
                )
        return image_files

    def convert_sprites(self):
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        sprite_images = self.find_sprite_images()
        if not sprite_images:
            self.log_callback(get_localized(self.language, 'Console_Convertor_Sprites_Error_NotFound'))
            return

        total_images = sum(len(images) for images in sprite_images.values())
        processed_images = 0

        for sprite_name, images in sprite_images.items():
            if not self.conversion_running():
                self.log_callback(get_localized(self.language, 'Console_Convertor_Sprites_Stopped'))
                return

            godot_sprite_folder = os.path.join(self.godot_sprites_path, sprite_name)
            os.makedirs(godot_sprite_folder, exist_ok=True)

            for index, gm_sprite_path in enumerate(sorted(images), start=1):
                new_filename = f"{sprite_name}_{index if len(images) > 1 else ''}.png"
                godot_sprite_path = os.path.join(godot_sprite_folder, new_filename)

                with Image.open(gm_sprite_path) as img:
                    img.save(godot_sprite_path, 'PNG')

                self.log_callback(get_localized(self.language, 'Console_Convertor_Sprites_Converted').format(relative_path=os.path.relpath(gm_sprite_path, self.gm_project_path), sprite_name=sprite_name, new_filename=new_filename))

                processed_images += 1
                if self.progress_callback:
                    self.progress_callback(int(processed_images / total_images * 100))

        self.log_callback(get_localized(self.language, 'Console_Convertor_Sprites_Complete'))

    def convert_all(self):
        self.convert_sprites()
