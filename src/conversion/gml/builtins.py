from src.conversion.gml.ast import Name


NAME_REPLACEMENTS = {
    "infinity": "INF",
    "NaN": "NAN",
    "nan": "NAN",
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

RUNTIME_FUNCTIONS = {
    "is_infinity": "is_infinity",
    "typeof": "gml_typeof",
    "string": "gml_string",
    "bool": "gml_bool",
}


def emit_name(name, local_names):
    if name in local_names:
        return name
    return INSTANCE_NAME_REPLACEMENTS.get(name, name)


def emit_builtin_call(expr, emit_arg=None):
    if isinstance(expr.callee, Name) and expr.callee.value == "keyboard_check" and len(expr.args) == 1:
        key = expr.args[0]
        if isinstance(key, Name) and key.value in VIRTUAL_KEY_ACTIONS:
            return f'Input.is_action_pressed("{VIRTUAL_KEY_ACTIONS[key.value]}")'
    if (
        emit_arg is not None
        and isinstance(expr.callee, Name)
        and expr.callee.value in RUNTIME_FUNCTIONS
        and len(expr.args) == 1
    ):
        return f"GMRuntime.{RUNTIME_FUNCTIONS[expr.callee.value]}({emit_arg(expr.args[0])})"
    return None
