import json, string

def get_localized(language, key):
    with open(f'Languages/{language}.json', 'r') as file:
        return json.load(file)[key]

def get_current_language():
    with open('Current Language', 'r') as file:
        return file.readline().strip('\n')



