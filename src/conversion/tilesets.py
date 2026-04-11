import os
import re
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter


class TileSetConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print,
                 progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False, max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_tilesets_path = os.path.join(self.godot_project_path, 'tilesets')

    def _get_valid_tileset_names(self):
        """Parse the .yyp project file and return a dict of tileset name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all tilesets on disk.
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

            valid_tilesets = {}
            for resource in data.get('resources', []):
                res_id = resource.get('id', {})
                path = res_id.get('path', '')
                if path.startswith('tilesets/'):
                    name = res_id.get('name', '')
                    yy_path = os.path.join(self.gm_project_path, 'tilesets', name, name + '.yy')
                    valid_tilesets[name] = self._get_subfolder_from_yy(yy_path)

            return valid_tilesets
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _parse_tileset_yy(self, tileset_name):
        """Read and parse a tileset .yy file.

        Returns a dict with tileset properties, or None on failure.
        """
        yy_path = os.path.join(self.gm_project_path, 'tilesets', tileset_name, tileset_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)

            sprite_id = data.get('spriteId', {})
            return {
                "sprite_name": sprite_id.get('name', ''),
                "sprite_path": sprite_id.get('path', ''),
                "tileWidth": int(data.get('tileWidth', 16)),
                "tileHeight": int(data.get('tileHeight', 16)),
                "tilehsep": int(data.get('tilehsep', 0)),
                "tilevsep": int(data.get('tilevsep', 0)),
                "tilexoff": int(data.get('tilexoff', 0)),
                "tileyoff": int(data.get('tileyoff', 0)),
                "tile_count": int(data.get('tile_count', 0)),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _find_sprite_image(self, sprite_name):
        """Find the primary layer image for a sprite referenced by a tileset.

        Parses the sprite's .yy to identify the first visible layer, then
        locates the corresponding PNG under layers/{frame_guid}/{layer_guid}.png.
        Returns the image path or None.
        """
        sprite_dir = os.path.join(self.gm_project_path, 'sprites', sprite_name)
        yy_path = os.path.join(sprite_dir, sprite_name + '.yy')

        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)

            # Get the first frame GUID
            frames = data.get('frames', [])
            if not frames:
                return None
            frame_guid = frames[0].get('name', '')

            # Get the primary visible layer GUID
            primary_layer_guid = None
            for layer in data.get('layers', []):
                if layer.get('visible', True):
                    primary_layer_guid = layer.get('name', '')
                    break
            if primary_layer_guid is None and data.get('layers'):
                primary_layer_guid = data['layers'][0].get('name', '')

            if not frame_guid or not primary_layer_guid:
                return None

            # Look for the image at layers/{frame_guid}/{layer_guid}.png
            image_path = os.path.join(sprite_dir, 'layers', frame_guid, primary_layer_guid + '.png')
            if os.path.isfile(image_path):
                return image_path

        except (OSError, json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError):
            pass

        # Fallback: look for any PNG in the layers directory
        layers_dir = os.path.join(sprite_dir, 'layers')
        if os.path.isdir(layers_dir):
            for root, _, files in os.walk(layers_dir):
                for file in files:
                    if file.lower().endswith('.png'):
                        return os.path.join(root, file)

        return None

    def _generate_tileset_tres(self, tileset_name, tileset_data, subfolder=""):
        """Generate a Godot TileSet .tres resource string."""
        tile_w = tileset_data["tileWidth"]
        tile_h = tileset_data["tileHeight"]
        tilehsep = tileset_data["tilehsep"]
        tilevsep = tileset_data["tilevsep"]
        tilexoff = tileset_data["tilexoff"]
        tileyoff = tileset_data["tileyoff"]

        if subfolder:
            res_path = f"res://tilesets/{subfolder}/{tileset_name}/{tileset_name}.png"
        else:
            res_path = f"res://tilesets/{tileset_name}/{tileset_name}.png"

        lines = []
        lines.append('[gd_resource type="TileSet" format=3]')
        lines.append('')
        lines.append(f'[ext_resource type="Texture2D" path="{res_path}" id="1"]')
        lines.append('')
        lines.append('[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]')
        lines.append('texture = ExtResource("1")')
        lines.append(f'texture_region_size = Vector2i({tile_w}, {tile_h})')

        if tilehsep or tilevsep:
            lines.append(f'separation = Vector2i({tilehsep}, {tilevsep})')
        if tilexoff or tileyoff:
            lines.append(f'margins = Vector2i({tilexoff}, {tileyoff})')

        lines.append('')
        lines.append('[resource]')
        lines.append(f'tile_size = Vector2i({tile_w}, {tile_h})')
        lines.append('sources/0 = SubResource("TileSetAtlasSource_1")')
        lines.append('')

        return '\n'.join(lines)

    def _process_tileset(self, tileset_name, subfolder=""):
        """Process a single tileset: parse, copy image, generate .tres.

        Returns a dict with conversion results, or None if stopped.
        """
        if not self.conversion_running():
            return None

        tileset_data = self._parse_tileset_yy(tileset_name)
        if tileset_data is None:
            return {"success": False, "name": tileset_name, "error": "parse_failed"}

        sprite_name = tileset_data["sprite_name"]
        image_path = self._find_sprite_image(sprite_name)
        if image_path is None:
            self._safe_log(get_localized("Console_Convertor_Tilesets_SpriteNotFound").format(
                name=tileset_name, sprite_name=sprite_name))
            return {"success": False, "name": tileset_name, "error": "sprite_not_found",
                    "sprite_name": sprite_name}

        # Create output directory
        if subfolder:
            output_dir = os.path.join(self.godot_tilesets_path, subfolder, tileset_name)
        else:
            output_dir = os.path.join(self.godot_tilesets_path, tileset_name)
        os.makedirs(output_dir, exist_ok=True)

        # Copy the sprite image as the tileset texture
        dest_image = os.path.join(output_dir, tileset_name + '.png')
        shutil.copy2(image_path, dest_image)

        # Generate and write the .tres file
        tres_content = self._generate_tileset_tres(tileset_name, tileset_data, subfolder)
        tres_path = os.path.join(output_dir, tileset_name + '.tres')
        with open(tres_path, 'w', encoding='utf-8') as f:
            f.write(tres_content)

        return {"success": True, "name": tileset_name, "tileset_data": tileset_data}

    def convert_tilesets(self):
        """Main tileset conversion method."""
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_tilesets_path, exist_ok=True)

        gm_tilesets_path = os.path.join(self.gm_project_path, 'tilesets')

        if not os.path.exists(gm_tilesets_path):
            self.log_callback(get_localized("Console_Convertor_Tilesets_Error_NotFound").format(
                gm_project_path=self.gm_project_path))
            return

        # Discover tileset directories by walking the tilesets folder
        tileset_names = []
        for entry in os.listdir(gm_tilesets_path):
            entry_path = os.path.join(gm_tilesets_path, entry)
            yy_path = os.path.join(entry_path, entry + '.yy')
            if os.path.isdir(entry_path) and os.path.isfile(yy_path):
                tileset_names.append(entry)

        # Filter against .yyp if available
        valid_names = self._get_valid_tileset_names()
        tileset_subfolders = {}
        if valid_names is not None:
            tileset_names = [n for n in tileset_names if n in valid_names]
            tileset_subfolders = {n: valid_names[n] for n in tileset_names}
        else:
            for name in tileset_names:
                yy_path = os.path.join(self.gm_project_path, 'tilesets', name, name + '.yy')
                tileset_subfolders[name] = self._get_subfolder_from_yy(yy_path)

        if not tileset_names:
            self.log_callback(get_localized("Console_Convertor_Tilesets_Complete"))
            return

        total_tilesets = len(tileset_names)
        processed_tilesets = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_tileset, name, tileset_subfolders.get(name, "")): name
                for name in tileset_names
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Tilesets_Stopped"))
                    return

                processed_tilesets += 1

                if result["success"]:
                    td = result["tileset_data"]
                    if self.compact_logging:
                        self._safe_log_progress(result["name"], processed_tilesets, total_tilesets)
                    else:
                        self._safe_log(get_localized("Console_Convertor_Tilesets_Converted").format(
                            name=result["name"],
                            tile_count=td["tile_count"],
                            tileWidth=td["tileWidth"],
                            tileHeight=td["tileHeight"]))

                self._safe_progress(int(processed_tilesets / total_tilesets * 100))

        self.log_callback(get_localized("Console_Convertor_Tilesets_Complete"))

    def convert_all(self):
        self.convert_tilesets()
