import json, string

def get_localized(key):
    # Find active language
    with open('Current Language', 'r') as file:
        language = file.readline().strip('\n')
    # Find matching key in lanugage json
    with open(f'Languages/{language}.json', 'r') as file:
        return json.load(file)[key]



