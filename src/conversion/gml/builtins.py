from src.conversion.gml.ast import Name


NAME_REPLACEMENTS = {
    "undefined": "null",
}

INSTANCE_NAME_REPLACEMENTS = {
    "x": "position.x",
    "y": "position.y",
}

VIRTUAL_KEY_ACTIONS = {
    "vk_left": "ui_left",
    "vk_right": "ui_right",
    "vk_up": "ui_up",
    "vk_down": "ui_down",
}


def emit_name(name, local_names):
    if name in local_names:
        return name
    return INSTANCE_NAME_REPLACEMENTS.get(name, name)


def emit_builtin_call(expr):
    if isinstance(expr.callee, Name) and expr.callee.value == "keyboard_check" and len(expr.args) == 1:
        key = expr.args[0]
        if isinstance(key, Name) and key.value in VIRTUAL_KEY_ACTIONS:
            return f'Input.is_action_pressed("{VIRTUAL_KEY_ACTIONS[key.value]}")'
    return None
