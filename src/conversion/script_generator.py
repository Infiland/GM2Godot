import re

from src.conversion.event_mapping import map_event, is_input_event, INPUT_MERGED_MAPPING
from src.conversion.events.features import get_script_features
from src.conversion.gml_runtime import GML_RUNTIME_RESOURCE_PATH


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _uses_gml_runtime(code_bodies):
    return any("GMRuntime." in body for body in (code_bodies or {}).values())


def _get_function_body(func, code_bodies):
    if code_bodies and func.godot_func in code_bodies:
        return code_bodies[func.godot_func]
    return "\tpass"


def _deduplicate_functions(functions):
    seen = set()
    unique_functions = []
    for func in functions:
        if func.godot_func not in seen:
            seen.add(func.godot_func)
            unique_functions.append(func)
    return unique_functions


def _valid_instance_variables(instance_variables):
    if not instance_variables:
        return []
    return sorted(
        name for name in instance_variables
        if _IDENTIFIER_RE.match(name)
    )


def generate_script_content(event_list, code_bodies=None, instance_variables=None):
    """Generate .gd script content with function stubs for each event.

    Events are mapped to Godot callback functions. Input events (mouse,
    keyboard) are merged into a single _input() function. Functions are
    ordered canonically: lifecycle callbacks first, then custom functions.

    Args:
        event_list: List of event dicts from a parsed .yy file.
        code_bodies: Optional dict mapping function names to GDScript code
            strings. When None, all function bodies are "pass". This is the
            seam where a future transpiler injects converted GML code.
        instance_variables: Optional iterable of GameMaker instance variable
            names to declare as GDScript member variables.

    Returns:
        Complete .gd file content as a string.
    """
    if not event_list:
        return "extends Node2D\n"

    functions = []
    has_input = False

    for event in event_list:
        if is_input_event(event):
            has_input = True
            continue

        mapping = map_event(event)
        if mapping is not None:
            functions.append(mapping)

    if has_input:
        functions.append(INPUT_MERGED_MAPPING)

    unique_functions = _deduplicate_functions(functions)
    function_names = {func.godot_func for func in unique_functions}
    script_features = get_script_features()

    for feature in script_features:
        get_additional_functions = getattr(feature, "get_additional_functions", None)
        if get_additional_functions is None:
            continue

        functions_to_add = get_additional_functions(function_names)
        if not functions_to_add:
            continue

        unique_functions = _deduplicate_functions(unique_functions + functions_to_add)
        function_names = {func.godot_func for func in unique_functions}

    # Sort by sort_key, then alphabetically for same key
    unique_functions.sort(key=lambda f: (f.sort_key, f.godot_func))

    lines = ["extends Node2D\n"]
    if _uses_gml_runtime(code_bodies):
        lines.append(f'\n\nconst GMRuntime = preload("{GML_RUNTIME_RESOURCE_PATH}")\n')
    for feature in script_features:
        emit_prelude = getattr(feature, "emit_prelude", None)
        if emit_prelude is not None:
            emit_prelude(lines, function_names)
    for variable_name in _valid_instance_variables(instance_variables):
        lines.append(f"\n\nvar {variable_name}\n")

    for func in unique_functions:
        body = _get_function_body(func, code_bodies)
        for feature in script_features:
            wrap_body = getattr(feature, "wrap_body", None)
            if wrap_body is not None:
                body = wrap_body(func, body, function_names)
        lines.append(f"\n\nfunc {func.godot_func}({func.params}):")
        lines.append(f"\n{body}\n")

    return ''.join(lines)
