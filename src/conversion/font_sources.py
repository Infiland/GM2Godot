from __future__ import annotations

import os
import platform
import re

from src.conversion.generated_paths import generated_resource_stem

FONT_EXTENSIONS = ('.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2')


def bundled_font_output_filename(ttf_name: str) -> str | None:
    """Return the safe, deterministic filename used for an included font."""
    normalized = ttf_name.replace('\\', '/')
    if not normalized or normalized.startswith('/') or re.match(r'^[A-Za-z]:', normalized):
        return None
    parts = normalized.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return None
    stem, extension = os.path.splitext(parts[-1])
    if not stem or extension.lower() not in FONT_EXTENSIONS:
        return None
    return generated_resource_stem(stem) + extension.lower()


def system_font_directories() -> list[str]:
    """Return a list of system font directories for the current OS."""
    system = platform.system()
    dirs: list[str] = []
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


def _system_font_filename_matches(filename: str, font_name_lower: str) -> bool:
    if not filename.lower().endswith(FONT_EXTENSIONS):
        return False
    name_without_ext = os.path.splitext(filename)[0].lower().replace(' ', '')
    if name_without_ext == font_name_lower:
        return True
    for suffix in ('-regular', '-normal', '_regular', '_normal'):
        if name_without_ext.endswith(suffix):
            base = name_without_ext[:-len(suffix)]
            if base == font_name_lower:
                return True
    return False


def resolve_system_font_source(font_name: str) -> str | None:
    """Return the first matching file using the established directory order."""
    font_name_lower = font_name.lower().replace(' ', '')
    for font_dir in system_font_directories():
        for root, _, files in os.walk(font_dir):
            for filename in files:
                if _system_font_filename_matches(filename, font_name_lower):
                    return os.path.join(root, filename)
    return None
