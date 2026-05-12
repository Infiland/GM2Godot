import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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
_SPRITE_RUNTIME_IDENTIFIER_RE = re.compile(r"\b(?:sprite_index|image_index)\b")
_SCRIPT_BUILTIN_VARIABLES = frozenset({"sprite_index", "image_index"})
_SPRITE_RUNTIME_RESERVED_NAMES = _SCRIPT_BUILTIN_VARIABLES | frozenset({
    "AnimatedSprite2D",
    "GMRuntime",
    "Node2D",
    "Sprite2D",
    "_GM_SPRITE_SCENES",
    "_gm_apply_image_index",
    "_gm_apply_sprite_index",
    "_gm_clear_current_sprite",
    "_gm_current_sprite_scene_root",
    "_gm_initialize_sprite_runtime",
    "_gm_sprite_visual_node",
})
_GDSCRIPT_RESERVED_WORDS = frozenset({
    "and",
    "as",
    "assert",
    "await",
    "break",
    "class",
    "class_name",
    "const",
    "continue",
    "elif",
    "else",
    "enum",
    "extends",
    "false",
    "for",
    "func",
    "if",
    "in",
    "is",
    "match",
    "not",
    "null",
    "or",
    "pass",
    "return",
    "self",
    "signal",
    "static",
    "super",
    "true",
    "var",
    "void",
    "while",
})


@dataclass(frozen=True)
class SpriteRuntimeConfig:
    initial_sprite_name: str | None = None
    sprite_scene_paths: Mapping[str, str] | None = None


def _uses_gml_runtime(code_bodies: _CodeBodies | None) -> bool:
    return any("GMRuntime." in body for body in (code_bodies or {}).values())


def _uses_sprite_runtime(
    sprite_runtime: SpriteRuntimeConfig | None,
    code_bodies: _CodeBodies | None,
) -> bool:
    if sprite_runtime is None:
        return False
    if sprite_runtime.initial_sprite_name is not None:
        return True
    return any(
        _SPRITE_RUNTIME_IDENTIFIER_RE.search(body) is not None
        for body in (code_bodies or {}).values()
    )


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
        if _IDENTIFIER_RE.match(name) and name not in _SCRIPT_BUILTIN_VARIABLES
    )


def _is_valid_gdscript_identifier(name: str) -> bool:
    return (
        _IDENTIFIER_RE.match(name) is not None
        and name not in _GDSCRIPT_RESERVED_WORDS
        and name not in _SPRITE_RUNTIME_RESERVED_NAMES
    )


def _gd_string(value: str) -> str:
    return json.dumps(value)


def _extends_line(base_script_path: str | None = None) -> str:
    if base_script_path is None:
        return "extends Node2D\n"
    return f"extends {_gd_string(base_script_path)}\n"


def _emit_sprite_runtime_prelude(lines: list[str], sprite_runtime: SpriteRuntimeConfig) -> None:
    sprite_scene_paths = dict(sprite_runtime.sprite_scene_paths or {})
    sprite_constants = [
        sprite_name for sprite_name in sorted(sprite_scene_paths)
        if _is_valid_gdscript_identifier(sprite_name)
    ]

    if sprite_constants:
        lines.append("\n\n")
        for sprite_name in sprite_constants:
            lines.append(f"const {sprite_name} = {_gd_string(sprite_name)}\n")

    lines.append("\n\nconst _GM_SPRITE_SCENES = {")
    for sprite_name, scene_path in sorted(sprite_scene_paths.items()):
        lines.append(f"\n\t{_gd_string(sprite_name)}: preload({_gd_string(scene_path)}),")
    lines.append("\n}\n")

    initial_sprite = "null"
    if sprite_runtime.initial_sprite_name is not None:
        initial_sprite = _gd_string(sprite_runtime.initial_sprite_name)

    lines.append(
        f"\nvar sprite_index = {initial_sprite}:"
        "\n\tset(value):"
        "\n\t\tsprite_index = value"
        "\n\t\t_gm_apply_sprite_index()"
        "\n\nvar image_index = 0.0:"
        "\n\tset(value):"
        "\n\t\timage_index = value"
        "\n\t\t_gm_apply_image_index()"
        "\n\nfunc _gm_initialize_sprite_runtime():"
        "\n\t_gm_apply_sprite_index()"
        "\n\tif has_meta(\"gamemaker_image_index\"):"
        "\n\t\timage_index = get_meta(\"gamemaker_image_index\")"
        "\n\telse:"
        "\n\t\t_gm_apply_image_index()"
        "\n\nfunc _gm_apply_sprite_index():"
        "\n\tif sprite_index == null:"
        "\n\t\t_gm_clear_current_sprite()"
        "\n\t\treturn"
        "\n\tvar sprite_index_type = typeof(sprite_index)"
        "\n\tif (sprite_index_type == TYPE_INT or sprite_index_type == TYPE_FLOAT) and int(sprite_index) == -1:"
        "\n\t\t_gm_clear_current_sprite()"
        "\n\t\treturn"
        "\n\tvar sprite_name = str(sprite_index)"
        "\n\tvar current = _gm_current_sprite_scene_root()"
        "\n\tif current != null and str(current.name) == sprite_name:"
        "\n\t\t_gm_apply_image_index()"
        "\n\t\treturn"
        "\n\tvar scene = _GM_SPRITE_SCENES.get(sprite_name)"
        "\n\tif scene == null:"
        "\n\t\t_gm_apply_image_index()"
        "\n\t\treturn"
        "\n\tif current != null:"
        "\n\t\tremove_child(current)"
        "\n\t\tcurrent.queue_free()"
        "\n\tvar instance = scene.instantiate()"
        "\n\tinstance.name = sprite_name"
        "\n\tadd_child(instance)"
        "\n\tmove_child(instance, 0)"
        "\n\t_gm_apply_image_index()"
        "\n\nfunc _gm_apply_image_index():"
        "\n\tvar sprite_node = _gm_sprite_visual_node()"
        "\n\tif sprite_node == null:"
        "\n\t\treturn"
        "\n\tvar frame_index = max(int(image_index), 0)"
        "\n\tif sprite_node is AnimatedSprite2D:"
        "\n\t\tvar frame_count = 0"
        "\n\t\tif sprite_node.sprite_frames != null and sprite_node.sprite_frames.has_animation(sprite_node.animation):"
        "\n\t\t\tframe_count = sprite_node.sprite_frames.get_frame_count(sprite_node.animation)"
        "\n\t\tif frame_count > 0:"
        "\n\t\t\tframe_index = min(frame_index, frame_count - 1)"
        "\n\t\tsprite_node.frame = frame_index"
        "\n\t\tsprite_node.frame_progress = 0.0"
        "\n\t\treturn"
        "\n\tif sprite_node is Sprite2D:"
        "\n\t\tvar frame_count = sprite_node.hframes * sprite_node.vframes"
        "\n\t\tif frame_count > 1:"
        "\n\t\t\tsprite_node.frame = min(frame_index, frame_count - 1)"
        "\n\nfunc _gm_current_sprite_scene_root():"
        "\n\tfor child in get_children():"
        "\n\t\tif str(child.name) in _GM_SPRITE_SCENES:"
        "\n\t\t\treturn child"
        "\n\t\tif child is Sprite2D or child is AnimatedSprite2D:"
        "\n\t\t\treturn child"
        "\n\t\tif child.find_child(\"AnimatedSprite2D\", true, false) != null:"
        "\n\t\t\treturn child"
        "\n\t\tif child.find_child(\"Sprite2D\", true, false) != null:"
        "\n\t\t\treturn child"
        "\n\treturn null"
        "\n\nfunc _gm_sprite_visual_node():"
        "\n\tvar current = _gm_current_sprite_scene_root()"
        "\n\tif current == null:"
        "\n\t\treturn null"
        "\n\tif current is AnimatedSprite2D or current is Sprite2D:"
        "\n\t\treturn current"
        "\n\tvar animated_sprite = current.find_child(\"AnimatedSprite2D\", true, false)"
        "\n\tif animated_sprite != null:"
        "\n\t\treturn animated_sprite"
        "\n\treturn current.find_child(\"Sprite2D\", true, false)"
        "\n\nfunc _gm_clear_current_sprite():"
        "\n\tvar current = _gm_current_sprite_scene_root()"
        "\n\tif current != null:"
        "\n\t\tremove_child(current)"
        "\n\t\tcurrent.queue_free()\n"
    )


def _prepend_sprite_runtime_ready_body(body: str) -> str:
    init_body = "\t_gm_initialize_sprite_runtime()"
    if body.strip() == "pass":
        return init_body
    return f"{init_body}\n{body}"


def generate_script_content(
    event_list: Sequence[JsonDict] | None,
    code_bodies: _CodeBodies | None = None,
    instance_variables: Iterable[str] | None = None,
    sprite_runtime: SpriteRuntimeConfig | None = None,
    base_script_path: str | None = None,
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
        sprite_runtime: Optional sprite runtime configuration for GameMaker
            sprite_index and image_index compatibility.
        base_script_path: Optional converted parent object script path to
            extend for GameMaker object inheritance.

    Returns:
        Complete .gd file content as a string.
    """
    uses_sprite_runtime = _uses_sprite_runtime(sprite_runtime, code_bodies)
    if not event_list and not uses_sprite_runtime:
        return _extends_line(base_script_path)

    functions: list[EventMapping] = []
    has_input = False

    for event in event_list or []:
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
    if uses_sprite_runtime and "_ready" not in function_names:
        unique_functions = _deduplicate_functions(unique_functions + [EventMapping("_ready", "", 0, "")])
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

    lines = [_extends_line(base_script_path)]
    if _uses_gml_runtime(code_bodies):
        lines.append(f'\n\nconst GMRuntime = preload("{GML_RUNTIME_RESOURCE_PATH}")\n')
    for feature in script_features:
        emit_prelude = cast(_EmitPrelude | None, getattr(feature, "emit_prelude", None))
        if emit_prelude is not None:
            emit_prelude(lines, function_names)
    if uses_sprite_runtime and sprite_runtime is not None:
        _emit_sprite_runtime_prelude(lines, sprite_runtime)
    for variable_name in _valid_instance_variables(instance_variables):
        lines.append(f"\n\nvar {variable_name}\n")

    for func in unique_functions:
        body = _get_function_body(func, code_bodies)
        for feature in script_features:
            wrap_body = cast(_WrapBody | None, getattr(feature, "wrap_body", None))
            if wrap_body is not None:
                body = wrap_body(func, body, function_names)
        if uses_sprite_runtime and func.godot_func == "_ready":
            body = _prepend_sprite_runtime_ready_body(body)
        lines.append(f"\n\nfunc {func.godot_func}({func.params}):")
        lines.append(f"\n{body}\n")

    return ''.join(lines)
