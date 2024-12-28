import re
import os

# Import localization manager
from src.localization import get_localized, get_current_language

# WORK IN PROGRESS

self.language = get_current_language()

def convert_gm_to_godot_shader(input_file, output_file):    
    with open(input_file, 'r') as f:
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
    content = re.sub(r'gm_Matrices\[MATRIX_WORLD_VIEW_PROJECTION\]', 'PROJECTION_MATRIX * MODELVIEW_MATRIX', content)

    if 'u_fTime' in content:
        content = 'uniform float TIME;\n' + content
        content = content.replace('u_fTime', 'TIME')

    uniform_pattern = r'uniform\s+(\w+)\s+(\w+);'
    uniforms = re.findall(uniform_pattern, content)
    for uniform_type, uniform_name in uniforms:
        if uniform_type in ['float', 'vec2', 'vec3', 'vec4', 'bool']:
            content = content.replace(f'uniform {uniform_type} {uniform_name};', f'uniform {uniform_type} {uniform_name};')
        else:
            content = content.replace(f'uniform {uniform_type} {uniform_name};', f'uniform {uniform_name};')

    with open(output_file, 'w') as f:
        f.write(content)

def process_directory(input_dir, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for filename in os.listdir(input_dir):
        if filename.endswith(('.vsh', '.fsh')):
            input_path = os.path.join(input_dir, filename)
            output_path = os.path.join(output_dir, filename.rsplit('.', 1)[0] + '.gdshader')
            convert_gm_to_godot_shader(input_path, output_path)
            print(get_localized(self.language, 'Console_Convertor_Shaders_Converted').format(filename=filename, output_path=os.path.basename(output_path)))

input_directory = 'path/to/input/directory'
output_directory = 'path/to/output/directory'
process_directory(input_directory, output_directory)
