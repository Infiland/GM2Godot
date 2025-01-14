import json, string

def get_language(): # Find active language
    global local_script
    try:
        with open('Current Language', 'r') as file:
            language = file.readline().strip('\n')
            with open(f"Languages/{language}.json", 'r') as file:
                pass           
    except:
        language = "eng"

    with open(f'Languages/{language}.json', 'r') as file:
        local_script = json.load(file)
    
def get_localized(key): # Find matching key in lanugage json
    return local_script[key]


get_language()
