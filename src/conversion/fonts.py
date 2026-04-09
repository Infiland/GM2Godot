import json
import os
import platform
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter

FONT_EXTENSIONS = ('.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2')


def _get_system_font_dirs():
    """Return a list of system font directories for the current OS."""
    system = platform.system()
    dirs = []
    if system == 'Windows':
        windir = os.environ.get('WINDIR', r'C:\Windows')
        dirs.append(os.path.join(windir, 'Fonts'))
        local_app = os.environ.get('LOCALAPPDATA', '')
        if local_app:
            dirs.append(os.path.join(local_app, 'Microsoft', 'Windows', 'Fonts'))
    elif system == 'Darwin':
        dirs.extend([
            '/Library/Fonts',
            '/System/Library/Fonts',
            os.path.expanduser('~/Library/Fonts'),
        ])
    else:
        dirs.extend([
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.local/share/fonts'),
            os.path.expanduser('~/.fonts'),
        ])
    return [d for d in dirs if os.path.isdir(d)]


def _find_system_font(font_name):
    """Search system font directories for a font file matching the given name.

    Returns the path to the font file if found, None otherwise.
    """
    font_name_lower = font_name.lower().replace(' ', '')
    for font_dir in _get_system_font_dirs():
        for root, _, files in os.walk(font_dir):
            for filename in files:
                if not filename.lower().endswith(FONT_EXTENSIONS):
                    continue
                name_without_ext = os.path.splitext(filename)[0].lower().replace(' ', '')
                if name_without_ext == font_name_lower:
                    return os.path.join(root, filename)
                # Also match with common suffixes stripped (e.g. "Arial-Regular" -> "Arial")
                for suffix in ('-regular', '-normal', '_regular', '_normal'):
                    if name_without_ext.endswith(suffix):
                        base = name_without_ext[:-len(suffix)]
                        if base == font_name_lower:
                            return os.path.join(root, filename)
    return None


class FontConverter(BaseConverter):
    def __init__(self, gm_project_path, godot_project_path, log_callback=print, progress_callback=None, conversion_running=None,
                 update_log_callback=None, compact_logging=False, max_workers=None):
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_fonts_path = os.path.join(self.godot_project_path, 'fonts')

    def find_font_files(self):
        font_folder = os.path.join(self.gm_project_path, 'fonts')
        font_files = []
        for root, _, files in os.walk(font_folder):
            font_files.extend(
                os.path.join(root, file)
                for file in files
                if file.lower().endswith('.yy') and not file.lower().endswith('.old.yy')
            )
        return font_files

    def _parse_font_yy(self, yy_path):
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = json.loads(cleaned)
            return {
                'fontName': data['fontName'],
                'name': data['name'],
                'size': data.get('size', 12.0),
                'bold': data.get('bold', False),
                'italic': data.get('italic', False),
                'AntiAlias': data.get('AntiAlias', 0),
                'includeTTF': data.get('includeTTF', False),
                'TTFName': data.get('TTFName', ''),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self._safe_log(get_localized("Console_Convertor_Fonts_ParseError").format(yy_path=yy_path))
            return None

    def _generate_system_font_tres(self, font_data):
        font_name = font_data['fontName']
        italic = "true" if font_data['italic'] else "false"
        weight = 700 if font_data['bold'] else 400
        antialiasing = 1 if font_data['AntiAlias'] else 0

        return (
            '[gd_resource type="SystemFont" format=3]\n'
            '\n'
            '[resource]\n'
            f'font_names = PackedStringArray("{font_name}")\n'
            f'font_italic = {italic}\n'
            f'font_weight = {weight}\n'
            f'antialiasing = {antialiasing}\n'
        )

    def _process_font(self, yy_path):
        if not self.conversion_running():
            return None

        font_data = self._parse_font_yy(yy_path)
        if font_data is None:
            return False

        font_name = font_data['name']
        system_font_name = font_data['fontName']
        output_file = None

        # 1. Try bundled TTF from GameMaker project
        if font_data['includeTTF'] and font_data['TTFName']:
            ttf_path = os.path.join(os.path.dirname(yy_path), font_data['TTFName'])
            if os.path.isfile(ttf_path):
                output_file = font_data['TTFName']
                shutil.copy2(ttf_path, os.path.join(self.godot_fonts_path, output_file))
                if not self.compact_logging:
                    self._safe_log(get_localized("Console_Convertor_Fonts_CopiedTTF").format(
                        name=font_name, output_file=output_file))
            else:
                self._safe_log(get_localized("Console_Convertor_Fonts_TTFMissing").format(
                    name=font_name, ttf_name=font_data['TTFName']))

        # 2. Try finding the font on the system
        if output_file is None:
            system_path = _find_system_font(system_font_name)
            if system_path:
                output_file = font_name + os.path.splitext(system_path)[1]
                shutil.copy2(system_path, os.path.join(self.godot_fonts_path, output_file))
                if not self.compact_logging:
                    self._safe_log(get_localized("Console_Convertor_Fonts_Converted").format(
                        name=font_name, output_file=output_file))

        # 3. Fall back to SystemFont .tres reference
        if output_file is None:
            output_file = font_name + '.tres'
            tres_content = self._generate_system_font_tres(font_data)
            tres_path = os.path.join(self.godot_fonts_path, output_file)
            with open(tres_path, 'w', encoding='utf-8') as f:
                f.write(tres_content)
            self._safe_log(get_localized("Console_Convertor_Fonts_SystemFontFallback").format(
                name=font_name, font_name=system_font_name))

        if not self.compact_logging:
            size = font_data['size']
            self._safe_log(get_localized("Console_Convertor_Fonts_SizeNote").format(
                name=font_name, size=size))

        return font_name

    def convert_fonts(self):
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_fonts_path, exist_ok=True)

        gm_fonts_path = os.path.join(self.gm_project_path, 'fonts')

        if not os.path.exists(gm_fonts_path):
            self.log_callback(get_localized("Console_Convertor_Fonts_Error_NotFound").format(gm_project_path=self.gm_project_path))
            return

        font_files = self.find_font_files()

        if not font_files:
            self.log_callback(get_localized("Console_Convertor_Fonts_Error_NotFound").format(gm_project_path=self.gm_project_path))
            return

        total_fonts = len(font_files)
        processed_fonts = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {executor.submit(self._process_font, ff): ff for ff in font_files}
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Fonts_Stopped"))
                    return
                if result is not False:
                    processed_fonts += 1
                    if self.compact_logging:
                        self._safe_log_progress(result, processed_fonts, total_fonts)
                    self._safe_progress(int(processed_fonts / total_fonts * 100))
                else:
                    processed_fonts += 1
                    self._safe_progress(int(processed_fonts / total_fonts * 100))

        self.log_callback(get_localized("Console_Convertor_Fonts_Complete"))

    def convert_all(self):
        self.convert_fonts()
