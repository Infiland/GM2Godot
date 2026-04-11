import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.conversion.base_converter import BaseConverter
from src.localization import get_localized


class ShaderConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path,
                 log_callback=print, progress_callback=None,
                 conversion_running=None,
                 update_log_callback=None, compact_logging=False,
                 max_workers=None):
        super().__init__(gm_project_path, godot_project_path,
                         log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_shaders_path = os.path.join(self.godot_project_path, 'shaders')

    def convert_shader(self, input_file, output_file):
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()

        content = re.sub(r'precision highp float;', 'shader_type canvas_item;', content)
        content = re.sub(r'\battribute\b', 'in', content)

        if 'void main()' in content and '.vsh' in input_file:
            content = re.sub(r'\bvarying\b', 'out', content)
        else:
            content = re.sub(r'\bvarying\b', 'in', content)

        content = re.sub(r'gl_FragColor', 'COLOR', content)
        content = re.sub(r'texture2D', 'texture', content)
        content = re.sub(r'gl_Position', 'VERTEX', content)

        if '.vsh' in input_file:
            content = re.sub(r'void main\(\)', 'void vertex()', content)
        else:
            content = content.replace('void main()', 'void fragment()')

        content = re.sub(r'gm_BaseTexture', 'TEXTURE', content)
        content = re.sub(r'gm_Matrices\[MATRIX_WORLD_VIEW_PROJECTION\]',
                         'PROJECTION_MATRIX * MODELVIEW_MATRIX', content)

        if 'u_fTime' in content:
            content = 'uniform float TIME;\n' + content
            content = content.replace('u_fTime', 'TIME')

        uniform_pattern = r'uniform\s+(\w+)\s+(\w+);'
        uniforms = re.findall(uniform_pattern, content)
        for uniform_type, uniform_name in uniforms:
            if uniform_type not in ['float', 'vec2', 'vec3', 'vec4', 'bool']:
                content = content.replace(
                    f'uniform {uniform_type} {uniform_name};',
                    f'uniform {uniform_name};'
                )

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)

    def _process_shader(self, input_path, subfolder=""):
        if not self.conversion_running():
            return None
        filename = os.path.basename(input_path)
        output_name = os.path.splitext(filename)[0] + '.gdshader'
        if subfolder:
            output_dir = os.path.join(self.godot_shaders_path, subfolder)
        else:
            output_dir = self.godot_shaders_path
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_name)
        self.convert_shader(input_path, output_path)
        return (filename, output_name)

    def convert_all(self):
        gm_shaders_path = os.path.join(self.gm_project_path, 'shaders')

        if not os.path.exists(gm_shaders_path):
            self.log_callback("No shaders directory found. Skipping shader conversion.")
            return

        os.makedirs(self.godot_shaders_path, exist_ok=True)

        # Collect shader files with their subfolder info
        shader_files = []
        shader_subfolders = {}
        for root, _, files in os.walk(gm_shaders_path):
            for f in files:
                if f.endswith(('.vsh', '.fsh')):
                    full_path = os.path.join(root, f)
                    shader_files.append(full_path)
                    # Determine subfolder from the shader's .yy file
                    shader_dir = os.path.dirname(full_path)
                    shader_name = os.path.basename(shader_dir)
                    yy_path = os.path.join(shader_dir, shader_name + '.yy')
                    shader_subfolders[full_path] = self._get_subfolder_from_yy(yy_path)

        if not shader_files:
            self.log_callback("No shader files (.vsh/.fsh) found.")
            return

        total = len(shader_files)
        processed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_shader, path, shader_subfolders.get(path, "")): path
                for path in shader_files
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback("Shader conversion stopped.")
                    return

                filename, output_name = result
                processed += 1

                if self.compact_logging:
                    self._safe_log_progress(filename, processed, total)
                else:
                    self._safe_log(get_localized("Console_Convertor_Shaders_Converted").format(
                        filename=filename, output_path=output_name))

                self._safe_progress(int((processed / total) * 100))

        self.log_callback("Shader conversion complete.")
