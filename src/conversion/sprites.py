import os
import re
import json
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

    def _get_valid_sprite_names(self):
        """Parse the .yyp project file and return the set of sprite names listed in resources.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all sprites on disk.
        """
        try:
            yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
            if not yyp_files:
                return None

            yyp_path = os.path.join(self.gm_project_path, yyp_files[0])
            with open(yyp_path, 'r', encoding='utf-8') as f:
                content = f.read()

            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)

            valid_sprites = set()
            for resource in data.get('resources', []):
                res_id = resource.get('id', {})
                path = res_id.get('path', '')
                if path.startswith('sprites/'):
                    valid_sprites.add(res_id.get('name', ''))

            return valid_sprites
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Sprites_YYPFilterWarning"))
            return None

    def _find_all_sprite_images(self):
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

    def _parse_sprite_yy(self, sprite_name):
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)

            frame_guids = [frame['name'] for frame in data['frames']]

            primary_layer_guid = None
            for layer in data.get('layers', []):
                if layer.get('visible', True):
                    primary_layer_guid = layer['name']
                    break
            if primary_layer_guid is None and data.get('layers'):
                primary_layer_guid = data['layers'][0]['name']

            return (frame_guids, primary_layer_guid)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, IndexError):
            self._safe_log(get_localized("Console_Convertor_Sprites_YYParseFailed").format(
                yy_path=yy_path, sprite_name=sprite_name))
            return None

    def _build_ordered_frame_list(self, sprite_name, all_image_paths):
        result = self._parse_sprite_yy(sprite_name)
        if result is None:
            return sorted(all_image_paths)

        frame_guids, primary_layer_guid = result

        path_index = {}
        for path in all_image_paths:
            parts = path.replace('\\', '/').split('/')
            frame_guid = parts[-2]
            filename = parts[-1]
            path_index.setdefault(frame_guid, {})[filename] = path

        ordered = []
        layer_filename = primary_layer_guid + '.png' if primary_layer_guid else None
        for guid in frame_guids:
            frame_files = path_index.get(guid, {})
            if not frame_files:
                continue
            if layer_filename and layer_filename in frame_files:
                ordered.append(frame_files[layer_filename])
            else:
                ordered.append(next(iter(frame_files.values())))

        return ordered if ordered else sorted(all_image_paths)

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

        sprite_images = self._find_all_sprite_images()

        valid_names = self._get_valid_sprite_names()
        if valid_names is not None:
            filtered = {}
            for name, images in sprite_images.items():
                if name in valid_names:
                    filtered[name] = images
                else:
                    self._safe_log(get_localized("Console_Convertor_Sprites_Skipped").format(
                        sprite_name=name))
            sprite_images = filtered

        if not sprite_images:
            self.log_callback(get_localized("Console_Convertor_Sprites_Error_NotFound"))
            return

        # Pre-create all sprite directories
        for sprite_name in sprite_images:
            os.makedirs(os.path.join(self.godot_sprites_path, sprite_name), exist_ok=True)

        # Flatten all work items
        work_items = []
        for sprite_name, images in sprite_images.items():
            ordered_images = self._build_ordered_frame_list(sprite_name, images)
            for index, gm_sprite_path in enumerate(ordered_images, start=1):
                work_items.append((sprite_name, index, gm_sprite_path, len(ordered_images)))

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
