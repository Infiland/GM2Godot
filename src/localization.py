from __future__ import annotations

import json
import os
import sys
from typing import Any, cast

def get_base_path() -> str:
    if getattr(sys, 'frozen', False):
        return cast(str, getattr(sys, '_MEIPASS'))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_language_value(path: str, key: str) -> object | None:
    with open(path, 'r', encoding='utf-8') as file:
        data = cast(dict[str, Any], json.load(file))
    return data.get(key)


def _get_localized_raw(key: str) -> object | None:
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

    try:
        return _load_language_value(os.path.join(base_path, 'Languages', 'eng.json'), key)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def get_localized(key: str) -> str:
    value = _get_localized_raw(key)
    return value if isinstance(value, str) else ""


def get_localized_list(key: str) -> list[str]:
    value = _get_localized_raw(key)
    if isinstance(value, list):
        value_list = cast(list[object], value)
        return [item for item in value_list if isinstance(item, str)]
    return []


def get_localized_dict(key: str) -> dict[str, str]:
    value = _get_localized_raw(key)
    if isinstance(value, dict):
        value_dict = cast(dict[object, object], value)
        return {
            str(item_key): str(item_value)
            for item_key, item_value in value_dict.items()
            if isinstance(item_key, str) and isinstance(item_value, str)
        }
    return {}
