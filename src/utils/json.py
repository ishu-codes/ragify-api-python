import json


def load_json_file(path:str):
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)

def save_to_json(path:str, content):
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(content, file, indent=2, ensure_ascii=False)
