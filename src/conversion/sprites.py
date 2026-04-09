import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from collections import defaultdict

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter


class SpriteConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False, max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'sprites')

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

    def _process_sprite(self, sprite_name, index, gm_sprite_path, images_count):
        if not self.conversion_running():
            return None

        new_filename = f"{sprite_name}_{index if images_count > 1 else ''}.png"
        godot_sprite_path = os.path.join(self.godot_sprites_path, sprite_name, new_filename)

        with Image.open(gm_sprite_path) as img:
            img.save(godot_sprite_path, 'PNG')

        return (sprite_name, index, images_count, gm_sprite_path, new_filename)

    def convert_sprites(self):
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        sprite_images = self.find_sprite_images()
        if not sprite_images:
            self.log_callback(get_localized("Console_Convertor_Sprites_Error_NotFound"))
            return

        # Pre-create all sprite directories
        for sprite_name in sprite_images:
            os.makedirs(os.path.join(self.godot_sprites_path, sprite_name), exist_ok=True)

        # Flatten all work items
        work_items = []
        for sprite_name, images in sprite_images.items():
            sorted_images = sorted(images)
            for index, gm_sprite_path in enumerate(sorted_images, start=1):
                work_items.append((sprite_name, index, gm_sprite_path, len(sorted_images)))

        total_images = len(work_items)
        processed_images = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_sprite, name, idx, path, count): (name, idx, path, count)
                for name, idx, path, count in work_items
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Sprites_Stopped"))
                    return

                sprite_name, index, images_count, gm_sprite_path, new_filename = result
                processed_images += 1

                if self.compact_logging:
                    self._safe_log_progress(sprite_name, processed_images, total_images)
                else:
                    self._safe_log(get_localized("Console_Convertor_Sprites_Converted").format(
                        relative_path=os.path.relpath(gm_sprite_path, self.gm_project_path),
                        sprite_name=sprite_name, new_filename=new_filename))

                self._safe_progress(int(processed_images / total_images * 100))

        self.log_callback(get_localized("Console_Convertor_Sprites_Complete"))

    def convert_all(self):
        self.convert_sprites()
