import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter


class ObjectConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False, max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_objects_path = os.path.join(self.godot_project_path, 'objects')

    def _get_valid_object_names(self):
        """Parse the .yyp project file and return a dict of object name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all objects on disk.
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

            valid_objects = {}
            for resource in data.get('resources', []):
                res_id = resource.get('id', {})
                path = res_id.get('path', '')
                if path.startswith('objects/'):
                    name = res_id.get('name', '')
                    yy_path = os.path.join(self.gm_project_path, 'objects', name, name + '.yy')
                    valid_objects[name] = self._get_subfolder_from_yy(yy_path)

            return valid_objects
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_YYPFilterWarning"))
            return None

    def _parse_object_yy(self, object_name):
        """Parse an object .yy file and extract the sprite reference.

        Returns a dict with 'sprite_name' (str or None) or None if parsing fails.
        """
        yy_path = os.path.join(self.gm_project_path, 'objects', object_name, object_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)

            sprite_id = data.get('spriteId')
            sprite_name = None
            if sprite_id is not None:
                sprite_name = sprite_id.get('name', None)

            return {"sprite_name": sprite_name}
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Objects_ParseError").format(
                yy_path=yy_path, object_name=object_name))
            return None

    def _get_sprite_subfolder(self, sprite_name):
        """Resolve a sprite's subfolder by reading its .yy file from the GM project."""
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        return self._get_subfolder_from_yy(yy_path)

    def _sprite_scene_exists(self, sprite_name, sprite_subfolder=""):
        """Check whether the converted sprite scene exists in the Godot project."""
        if sprite_subfolder:
            tscn_path = os.path.join(self.godot_project_path, 'sprites', sprite_subfolder, sprite_name, sprite_name + '.tscn')
        else:
            tscn_path = os.path.join(self.godot_project_path, 'sprites', sprite_name, sprite_name + '.tscn')
        return os.path.isfile(tscn_path)

    def _generate_object_scene(self, object_name, sprite_name, sprite_subfolder=""):
        """Build the .tscn content string for an object scene.

        If sprite_name is not None, the scene instances the sprite's scene as a child.
        """
        if sprite_name is None:
            parts = ['[gd_scene format=3]\n']
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\n')
        else:
            if sprite_subfolder:
                sprite_res_path = f"res://sprites/{sprite_subfolder}/{sprite_name}/{sprite_name}.tscn"
            else:
                sprite_res_path = f"res://sprites/{sprite_name}/{sprite_name}.tscn"
            parts = ['[gd_scene format=3 load_steps=2]\n']
            parts.append(f'\n[ext_resource type="PackedScene" path="{sprite_res_path}" id="1"]\n')
            parts.append(f'\n[node name="{object_name}" type="Node2D"]\n')
            parts.append(f'\n[node name="{sprite_name}" parent="." instance=ExtResource("1")]\n')

        return ''.join(parts)

    def _process_object(self, object_name, subfolder=""):
        """Process a single object: parse .yy, generate scene, write .tscn file.

        Returns a result dict or None if conversion was stopped.
        """
        if not self.conversion_running():
            return None

        parsed = self._parse_object_yy(object_name)
        if parsed is None:
            return {"success": False, "name": object_name}

        sprite_name = parsed["sprite_name"]
        sprite_subfolder = ""

        if sprite_name is not None:
            sprite_subfolder = self._get_sprite_subfolder(sprite_name)
            if not self._sprite_scene_exists(sprite_name, sprite_subfolder):
                self._safe_log(get_localized("Console_Convertor_Objects_SpriteNotFound").format(
                    object_name=object_name, sprite_name=sprite_name))
                sprite_name = None

        scene_content = self._generate_object_scene(object_name, sprite_name, sprite_subfolder)

        if subfolder:
            object_dir = os.path.join(self.godot_objects_path, subfolder, object_name)
        else:
            object_dir = os.path.join(self.godot_objects_path, object_name)
        os.makedirs(object_dir, exist_ok=True)
        tscn_path = os.path.join(object_dir, f"{object_name}.tscn")
        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(scene_content)

        return {"success": True, "name": object_name, "has_sprite": sprite_name is not None, "sprite_name": sprite_name}

    def convert_objects(self):
        os.makedirs(self.godot_objects_path, exist_ok=True)

        gm_objects_path = os.path.join(self.gm_project_path, 'objects')
        if not os.path.isdir(gm_objects_path):
            self.log_callback(get_localized("Console_Convertor_Objects_Error_NotFound"))
            return

        object_names = [
            name for name in os.listdir(gm_objects_path)
            if os.path.isdir(os.path.join(gm_objects_path, name))
            and os.path.isfile(os.path.join(gm_objects_path, name, name + '.yy'))
        ]

        valid_names = self._get_valid_object_names()
        object_subfolders = {}
        if valid_names is not None:
            object_names = [name for name in object_names if name in valid_names]
            object_subfolders = {name: valid_names[name] for name in object_names}
        else:
            for name in object_names:
                yy_path = os.path.join(self.gm_project_path, 'objects', name, name + '.yy')
                object_subfolders[name] = self._get_subfolder_from_yy(yy_path)

        if not object_names:
            self.log_callback(get_localized("Console_Convertor_Objects_Complete"))
            return

        total = len(object_names)
        processed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_object, name, object_subfolders.get(name, "")): name
                for name in object_names
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Objects_Stopped"))
                    return

                processed += 1

                if result["success"]:
                    if self.compact_logging:
                        self._safe_log_progress(result["name"], processed, total)
                    else:
                        if result["has_sprite"]:
                            self._safe_log(get_localized("Console_Convertor_Objects_ConvertedWithSprite").format(
                                object_name=result["name"], sprite_name=result["sprite_name"]))
                        else:
                            self._safe_log(get_localized("Console_Convertor_Objects_Converted").format(
                                object_name=result["name"]))

                self._safe_progress(int(processed / total * 100))

        self.log_callback(get_localized("Console_Convertor_Objects_Complete"))

    def convert_all(self):
        self.convert_objects()
