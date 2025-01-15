import json, string
import os
import sys

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_localized(key):
    base_path = get_base_path()
    lang_file = os.path.join(base_path, 'Current Language')
    with open(lang_file, 'r') as file:
        language = file.readline().strip()

    json_path = os.path.join(base_path, 'Languages', f'{language}.json')
    with open(json_path, 'r') as file:
        return json.load(file)[key]