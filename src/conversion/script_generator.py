import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Callable, TypeAlias, cast

from src.conversion.event_mapping import INPUT_MERGED_MAPPING, is_input_event, map_event
from src.conversion.events.base import EventMapping
from src.conversion.events.features import get_script_features
from src.conversion.gml_runtime import GML_RUNTIME_RESOURCE_PATH
from src.conversion.type_defs import JsonDict


_CodeBodies: TypeAlias = Mapping[str, str]
_MapEvent: TypeAlias = Callable[[JsonDict], EventMapping | None]
_IsInputEvent: TypeAlias = Callable[[JsonDict], bool]
_GetAdditionalFunctions: TypeAlias = Callable[[set[str]], list[EventMapping]]
_EmitPrelude: TypeAlias = Callable[[list[str], set[str]], None]
_WrapBody: TypeAlias = Callable[[EventMapping, str, set[str]], str]

_map_event = cast(_MapEvent, map_event)
_is_input_event = cast(_IsInputEvent, is_input_event)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _uses_gml_runtime(code_bodies: _CodeBodies | None) -> bool:
    return any("GMRuntime." in body for body in (code_bodies or {}).values())


def _get_function_body(func: EventMapping, code_bodies: _CodeBodies | None) -> str:
    if code_bodies and func.godot_func in code_bodies:
        return code_bodies[func.godot_func]
    return "\tpass"


def _deduplicate_functions(functions: Iterable[EventMapping]) -> list[EventMapping]:
    seen: set[str] = set()
    unique_functions: list[EventMapping] = []
    for func in functions:
        if func.godot_func not in seen:
            seen.add(func.godot_func)
            unique_functions.append(func)
    return unique_functions


def _valid_instance_variables(instance_variables: Iterable[str] | None) -> list[str]:
    if not instance_variables:
        return []
    return sorted(
        name for name in instance_variables
        if _IDENTIFIER_RE.match(name)
    )


def generate_script_content(
    event_list: Sequence[JsonDict] | None,
    code_bodies: _CodeBodies | None = None,
    instance_variables: Iterable[str] | None = None,
) -> str:
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

    functions: list[EventMapping] = []
    has_input = False

    for event in event_list:
        if _is_input_event(event):
            has_input = True
            continue

        mapping = _map_event(event)
        if mapping is not None:
            functions.append(mapping)

    if has_input:
        functions.append(INPUT_MERGED_MAPPING)

    unique_functions = _deduplicate_functions(functions)
    function_names = {func.godot_func for func in unique_functions}
    script_features = get_script_features()

    for feature in script_features:
        get_additional_functions = cast(
            _GetAdditionalFunctions | None,
            getattr(feature, "get_additional_functions", None),
        )
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
        emit_prelude = cast(_EmitPrelude | None, getattr(feature, "emit_prelude", None))
        if emit_prelude is not None:
            emit_prelude(lines, function_names)
    for variable_name in _valid_instance_variables(instance_variables):
        lines.append(f"\n\nvar {variable_name}\n")

    for func in unique_functions:
        body = _get_function_body(func, code_bodies)
        for feature in script_features:
            wrap_body = cast(_WrapBody | None, getattr(feature, "wrap_body", None))
            if wrap_body is not None:
                body = wrap_body(func, body, function_names)
        lines.append(f"\n\nfunc {func.godot_func}({func.params}):")
        lines.append(f"\n{body}\n")

    return ''.join(lines)
