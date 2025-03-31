import json, string, os, sys

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
        try :
            return json.load(file)[key]
        except :
            pass

    # If an exception is thrown, the script will attempt to load the key from eng.json
    with open(os.path.join(base_path, 'Languages', 'eng.json'), 'r') as file:
        try :
            return json.load(file)[key]
        except :
            return ""
    # Finally, if eng.json fails, the script will return a blank string
