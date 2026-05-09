from __future__ import annotations

import json
import os
import sys
from typing import Any, cast

def get_base_path() -> str:
    if getattr(sys, 'frozen', False):
        return cast(str, getattr(sys, '_MEIPASS'))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_language_value(path: str, key: str) -> str | None:
    with open(path, 'r', encoding='utf-8') as file:
        data = cast(dict[str, Any], json.load(file))
    value = data.get(key)
    return value if isinstance(value, str) else None


def get_localized(key: str) -> str:
    base_path = get_base_path()
    lang_file = os.path.join(base_path, 'Current Language')
    with open(lang_file, 'r', encoding='utf-8') as file:
        language = file.readline().strip()

    json_path = os.path.join(base_path, 'Languages', f'{language}.json')
    try:
        value = _load_language_value(json_path, key)
        if value is not None:
            return value
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass

    # If an exception is thrown, the script will attempt to load the key from eng.json
    try:
        value = _load_language_value(os.path.join(base_path, 'Languages', 'eng.json'), key)
        return value or ""
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ""
    # Finally, if eng.json fails, the script will return a blank string
