from src.conversion.event_mapping import map_event, is_input_event, INPUT_MERGED_MAPPING


def generate_script_content(event_list, code_bodies=None):
    """Generate .gd script content with function stubs for each event.

    Events are mapped to Godot callback functions. Input events (mouse,
    keyboard) are merged into a single _input() function. Functions are
    ordered canonically: lifecycle callbacks first, then custom functions.

    Args:
        event_list: List of event dicts from a parsed .yy file.
        code_bodies: Optional dict mapping function names to GDScript code
            strings. When None, all function bodies are "pass". This is the
            seam where a future transpiler injects converted GML code.

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

    # Deduplicate by function name, keep first occurrence
    seen = set()
    unique_functions = []
    for func in functions:
        if func.godot_func not in seen:
            seen.add(func.godot_func)
            unique_functions.append(func)

    # Sort by sort_key, then alphabetically for same key
    unique_functions.sort(key=lambda f: (f.sort_key, f.godot_func))

    function_names = {func.godot_func for func in unique_functions}

    lines = ["extends Node2D\n"]
    if "_on_no_more_lives" in function_names:
        lines.append(
            "\n\nvar lives = 0:"
            "\n\tset(value):"
            "\n\t\tlives = value"
            "\n\t\tif lives <= 0:"
            "\n\t\t\t_on_no_more_lives()\n"
        )
    if "_on_no_more_health" in function_names:
        lines.append(
            "\n\nvar health = 100:"
            "\n\tset(value):"
            "\n\t\thealth = value"
            "\n\t\tif health <= 0:"
            "\n\t\t\t_on_no_more_health()\n"
        )

    for func in unique_functions:
        body = "\tpass"
        if code_bodies and func.godot_func in code_bodies:
            body = code_bodies[func.godot_func]
        lines.append(f"\n\nfunc {func.godot_func}({func.params}):")
        lines.append(f"\n{body}\n")

    return ''.join(lines)
