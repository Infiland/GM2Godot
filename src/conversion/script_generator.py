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
_SPRITE_RUNTIME_IDENTIFIER_RE = re.compile(
    r"\b(?:sprite_index|image_(?:alpha|angle|blend|index|number|speed|xscale|yscale))\b"
)
_SCRIPT_BUILTIN_VARIABLES = frozenset({
    "direction",
    "friction",
    "gravity",
    "gravity_direction",
    "hspeed",
    "image_alpha",
    "image_angle",
    "image_blend",
    "image_index",
    "image_number",
    "image_speed",
    "image_xscale",
    "image_yscale",
    "path_index",
    "path_position",
    "path_scale",
    "path_speed",
    "solid",
    "speed",
    "sprite_index",
    "timeline_index",
    "timeline_loop",
    "timeline_position",
    "timeline_running",
    "timeline_speed",
    "vspeed",
    "xprevious",
    "xstart",
    "yprevious",
    "ystart",
})
_DRAW_RUNTIME_FUNCTIONS = frozenset({
    "_draw",
    "_on_draw_begin",
    "_on_draw_end",
    "_on_draw_gui",
    "_on_draw_gui_begin",
    "_on_draw_gui_end",
    "_on_post_draw",
    "_on_pre_draw",
})
_SPRITE_RUNTIME_RESERVED_NAMES = _SCRIPT_BUILTIN_VARIABLES | frozenset({
    "AnimatedSprite2D",
    "CanvasItem",
    "Color",
    "GMRuntime",
    "Node2D",
    "Sprite2D",
    "_GM_SPRITE_SCENES",
    "_gm_apply_image_index",
    "_gm_apply_image_transform",
    "_gm_apply_sprite_index",
    "_gm_clear_current_sprite",
    "_gm_image_modulate",
    "_gm_current_sprite_scene_root",
    "_gm_initialize_sprite_runtime",
    "_gm_room_colour_alpha",
    "_gm_sprite_visual_node",
    "Vector2",
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


@dataclass(frozen=True)
class ObjectRuntimeConfig:
    object_name: str
    parent_object_names: tuple[str, ...] = ()
    solid: bool = False
    persistent: bool = False
    inherit_ready: bool = False
    inherit_exit_tree: bool = False


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


def _uses_object_runtime(object_runtime: ObjectRuntimeConfig | None) -> bool:
    return object_runtime is not None


def _uses_motion_runtime(object_runtime: ObjectRuntimeConfig | None) -> bool:
    return object_runtime is not None


def _uses_draw_runtime(function_names: set[str]) -> bool:
    return bool(function_names & _DRAW_RUNTIME_FUNCTIONS)


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


def _gd_string_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_gd_string(value) for value in values) + "]"


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
        "\n\nvar image_number = 1"
        "\nvar image_speed = 1.0"
        "\nvar image_xscale = 1.0:"
        "\n\tset(value):"
        "\n\t\timage_xscale = value"
        "\n\t\t_gm_apply_image_transform()"
        "\nvar image_yscale = 1.0:"
        "\n\tset(value):"
        "\n\t\timage_yscale = value"
        "\n\t\t_gm_apply_image_transform()"
        "\nvar image_angle = 0.0:"
        "\n\tset(value):"
        "\n\t\timage_angle = value"
        "\n\t\t_gm_apply_image_transform()"
        "\nvar image_blend = 0xffffff:"
        "\n\tset(value):"
        "\n\t\timage_blend = value"
        "\n\t\t_gm_apply_image_transform()"
        "\nvar image_alpha = 1.0:"
        "\n\tset(value):"
        "\n\t\timage_alpha = value"
        "\n\t\t_gm_apply_image_transform()"
        "\n\nfunc _gm_initialize_sprite_runtime():"
        "\n\t_gm_apply_sprite_index()"
        "\n\tif has_meta(\"gamemaker_image_index\"):"
        "\n\t\timage_index = get_meta(\"gamemaker_image_index\")"
        "\n\telse:"
        "\n\t\t_gm_apply_image_index()"
        "\n\tif has_meta(\"gamemaker_image_speed\"):"
        "\n\t\timage_speed = get_meta(\"gamemaker_image_speed\")"
        "\n\tif has_meta(\"gamemaker_image_angle\"):"
        "\n\t\timage_angle = get_meta(\"gamemaker_image_angle\")"
        "\n\telse:"
        "\n\t\timage_angle = rotation_degrees"
        "\n\tif has_meta(\"gamemaker_image_xscale\"):"
        "\n\t\timage_xscale = get_meta(\"gamemaker_image_xscale\")"
        "\n\telse:"
        "\n\t\timage_xscale = scale.x"
        "\n\tif has_meta(\"gamemaker_image_yscale\"):"
        "\n\t\timage_yscale = get_meta(\"gamemaker_image_yscale\")"
        "\n\telse:"
        "\n\t\timage_yscale = scale.y"
        "\n\tif has_meta(\"gamemaker_image_blend\"):"
        "\n\t\timage_blend = get_meta(\"gamemaker_image_blend\")"
        "\n\telif has_meta(\"gamemaker_colour\") and get_meta(\"gamemaker_colour\") != null:"
        "\n\t\timage_blend = int(get_meta(\"gamemaker_colour\")) & 0xffffff"
        "\n\tif has_meta(\"gamemaker_image_alpha\"):"
        "\n\t\timage_alpha = get_meta(\"gamemaker_image_alpha\")"
        "\n\telif has_meta(\"gamemaker_colour\") and get_meta(\"gamemaker_colour\") != null:"
        "\n\t\timage_alpha = _gm_room_colour_alpha(get_meta(\"gamemaker_colour\"))"
        "\n\t_gm_apply_image_transform()"
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
        "\n\t\t_gm_apply_image_transform()"
        "\n\t\treturn"
        "\n\tvar scene = _GM_SPRITE_SCENES.get(sprite_name)"
        "\n\tif scene == null:"
        "\n\t\t_gm_apply_image_index()"
        "\n\t\t_gm_apply_image_transform()"
        "\n\t\treturn"
        "\n\tif current != null:"
        "\n\t\tremove_child(current)"
        "\n\t\tcurrent.queue_free()"
        "\n\tvar instance = scene.instantiate()"
        "\n\tinstance.name = sprite_name"
        "\n\tadd_child(instance)"
        "\n\tmove_child(instance, 0)"
        "\n\t_gm_apply_image_index()"
        "\n\t_gm_apply_image_transform()"
        "\n\nfunc _gm_apply_image_index():"
        "\n\tvar sprite_node = _gm_sprite_visual_node()"
        "\n\tif sprite_node == null:"
        "\n\t\treturn"
        "\n\tvar frame_index = max(int(image_index), 0)"
        "\n\tif sprite_node is AnimatedSprite2D:"
        "\n\t\tvar frame_count = 0"
        "\n\t\tif sprite_node.sprite_frames != null and sprite_node.sprite_frames.has_animation(sprite_node.animation):"
        "\n\t\t\tframe_count = sprite_node.sprite_frames.get_frame_count(sprite_node.animation)"
        "\n\t\timage_number = max(frame_count, 1)"
        "\n\t\tif frame_count > 0:"
        "\n\t\t\tframe_index = min(frame_index, frame_count - 1)"
        "\n\t\tsprite_node.frame = frame_index"
        "\n\t\tsprite_node.frame_progress = 0.0"
        "\n\t\treturn"
        "\n\tif sprite_node is Sprite2D:"
        "\n\t\tvar frame_count = sprite_node.hframes * sprite_node.vframes"
        "\n\t\timage_number = max(frame_count, 1)"
        "\n\t\tif frame_count > 1:"
        "\n\t\t\tsprite_node.frame = min(frame_index, frame_count - 1)"
        "\n\nfunc _gm_apply_image_transform():"
        "\n\trotation_degrees = float(image_angle)"
        "\n\tscale = Vector2(float(image_xscale), float(image_yscale))"
        "\n\tvar sprite_node = _gm_sprite_visual_node()"
        "\n\tif sprite_node is CanvasItem:"
        "\n\t\tsprite_node.modulate = _gm_image_modulate()"
        "\n\nfunc _gm_image_modulate():"
        "\n\tvar blend = int(image_blend) & 0xffffff"
        "\n\treturn Color("
        "\n\t\tfloat(blend & 0xff) / 255.0,"
        "\n\t\tfloat((blend >> 8) & 0xff) / 255.0,"
        "\n\t\tfloat((blend >> 16) & 0xff) / 255.0,"
        "\n\t\tclamp(float(image_alpha), 0.0, 1.0)"
        "\n\t)"
        "\n\nfunc _gm_room_colour_alpha(colour):"
        "\n\tvar packed = int(colour) & 0xffffffff"
        "\n\tif packed <= 0xffffff:"
        "\n\t\treturn 1.0"
        "\n\treturn float((packed >> 24) & 0xff) / 255.0"
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


def _emit_object_runtime_prelude(
    lines: list[str],
    object_runtime: ObjectRuntimeConfig,
    *,
    declare_members: bool,
) -> None:
    member_lines = (
        "\n\nvar id = GMRuntime.gml_instance_noone()"
        f"\nvar object_index = GMRuntime.gml_asset_get_index({_gd_string(object_runtime.object_name)})"
        "\nvar depth = 0"
        f"\nvar solid = {str(object_runtime.solid).lower()}"
        f"\nvar persistent = {str(object_runtime.persistent).lower()}"
        if declare_members
        else ""
    )
    lines.append(
        member_lines
        + "\n\nfunc _gm_register_instance():"
        "\n\tif GMRuntime.gml_handle_is_valid(id):"
        "\n\t\treturn"
        f"\n\tid = GMRuntime.gml_instance_register(self, {_gd_string(object_runtime.object_name)}, {_gd_string_array(object_runtime.parent_object_names)})"
        f"\n\tobject_index = GMRuntime.gml_asset_get_index({_gd_string(object_runtime.object_name)})"
        f"\n\tsolid = {str(object_runtime.solid).lower()}"
        f"\n\tpersistent = {str(object_runtime.persistent).lower()}"
        "\n\tGMRuntime.gml_variable_instance_set(self, \"id\", id)"
        "\n\tGMRuntime.gml_variable_instance_set(self, \"object_index\", object_index)"
        "\n\tGMRuntime.gml_variable_instance_set(self, \"depth\", depth)"
        "\n\tGMRuntime.gml_variable_instance_set(self, \"solid\", solid)"
        "\n\tGMRuntime.gml_variable_instance_set(self, \"persistent\", persistent)"
        "\n\tset_meta(\"gamemaker_persistent\", persistent)"
        "\n\tif has_meta(\"gamemaker_instance_object_name\"):"
        "\n\t\tGMRuntime.gml_variable_instance_set(self, \"object_index\", GMRuntime.gml_asset_get_index(get_meta(\"gamemaker_instance_object_name\")))"
        "\n\tif has_meta(\"gamemaker_instance_name\"):"
        "\n\t\tGMRuntime.gml_variable_instance_set(self, \"name\", get_meta(\"gamemaker_instance_name\"))"
        "\n\nfunc _gm_unregister_instance():"
        "\n\tif has_meta(\"_gm2godot_room_preserving_persistent\") and get_meta(\"_gm2godot_room_preserving_persistent\"):"
        "\n\t\treturn"
        "\n\tGMRuntime.gml_instance_unregister(id)\n"
    )


def _emit_motion_runtime_prelude(lines: list[str], *, declare_members: bool) -> None:
    if not declare_members:
        return
    lines.append(
        "\n\nvar direction = 0.0"
        "\nvar speed = 0.0"
        "\nvar hspeed = 0.0"
        "\nvar vspeed = 0.0"
        "\nvar friction = 0.0"
        "\nvar gravity = 0.0"
        "\nvar gravity_direction = 270.0"
        "\nvar path_index = GMRuntime.gml_undefined()"
        "\nvar path_position = 0.0"
        "\nvar path_speed = 0.0"
        "\nvar path_scale = 1.0"
        "\nvar xprevious = 0.0"
        "\nvar yprevious = 0.0"
        "\nvar xstart = 0.0"
        "\nvar ystart = 0.0"
        "\n\nfunc _gm_initialize_motion_runtime():"
        "\n\txstart = position.x"
        "\n\tystart = position.y"
        "\n\txprevious = position.x"
        "\n\typrevious = position.y"
        "\n\tGMRuntime.gml_motion_sync_from_speed_direction(self)"
        "\n\nfunc _gm_apply_motion_step():"
        "\n\tGMRuntime.gml_path_step(self)"
        "\n\tGMRuntime.gml_motion_step(self)\n"
    )


def _wrap_object_runtime_ready_body(body: str, object_runtime: ObjectRuntimeConfig) -> str:
    init_lines = ["\t_gm_register_instance()", "\t_gm_initialize_motion_runtime()"]
    if object_runtime.inherit_ready and body.strip() == "pass":
        init_lines.append("\tsuper._ready()")
        return "\n".join(init_lines)
    if body.strip() == "pass":
        return "\n".join(init_lines)
    return "\n".join(init_lines) + "\n" + body


def _wrap_object_runtime_exit_tree_body(body: str, object_runtime: ObjectRuntimeConfig) -> str:
    cleanup_lines: list[str] = []
    if object_runtime.inherit_exit_tree and body.strip() == "pass":
        cleanup_lines.append("\tsuper._exit_tree()")
    elif body.strip() != "pass":
        cleanup_lines.append(body)
    cleanup_lines.append("\t_gm_unregister_instance()")
    return "\n".join(cleanup_lines)


def _wrap_draw_runtime_body(func: EventMapping, body: str) -> str:
    begin_line = f'\tGMRuntime.gml_draw_begin(self, {_gd_string(func.godot_func)})'
    end_line = "\tGMRuntime.gml_draw_end()"
    if body.strip() == "pass":
        return f"{begin_line}\n{end_line}"
    return f"{begin_line}\n{body}\n{end_line}"


def generate_script_content(
    event_list: Sequence[JsonDict] | None,
    code_bodies: _CodeBodies | None = None,
    instance_variables: Iterable[str] | None = None,
    sprite_runtime: SpriteRuntimeConfig | None = None,
    object_runtime: ObjectRuntimeConfig | None = None,
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
        object_runtime: Optional object instance registry configuration.
        base_script_path: Optional converted parent object script path to
            extend for GameMaker object inheritance.

    Returns:
        Complete .gd file content as a string.
    """
    uses_sprite_runtime = _uses_sprite_runtime(sprite_runtime, code_bodies)
    uses_object_runtime = _uses_object_runtime(object_runtime)
    uses_motion_runtime = _uses_motion_runtime(object_runtime)
    if not event_list and not uses_sprite_runtime and not uses_object_runtime:
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
    if uses_object_runtime:
        required_functions: list[EventMapping] = []
        if "_ready" not in function_names:
            required_functions.append(EventMapping("_ready", "", 0, ""))
        if "_exit_tree" not in function_names:
            required_functions.append(EventMapping("_exit_tree", "", 5, ""))
        if required_functions:
            unique_functions = _deduplicate_functions(unique_functions + required_functions)
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
    uses_draw_runtime = _uses_draw_runtime(function_names)

    # Sort by sort_key, then alphabetically for same key
    unique_functions.sort(key=lambda f: (f.sort_key, f.godot_func))

    lines = [_extends_line(base_script_path)]
    runtime_const_inherited = base_script_path is not None and uses_object_runtime
    if (_uses_gml_runtime(code_bodies) or uses_object_runtime or uses_draw_runtime) and not runtime_const_inherited:
        lines.append(f'\n\nconst GMRuntime = preload("{GML_RUNTIME_RESOURCE_PATH}")\n')
    for feature in script_features:
        emit_prelude = cast(_EmitPrelude | None, getattr(feature, "emit_prelude", None))
        if emit_prelude is not None:
            emit_prelude(lines, function_names)
    if uses_sprite_runtime and sprite_runtime is not None:
        _emit_sprite_runtime_prelude(lines, sprite_runtime)
    if uses_object_runtime and object_runtime is not None:
        _emit_object_runtime_prelude(
            lines,
            object_runtime,
            declare_members=base_script_path is None,
        )
    if uses_motion_runtime:
        _emit_motion_runtime_prelude(
            lines,
            declare_members=base_script_path is None,
        )
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
        if uses_object_runtime and object_runtime is not None and func.godot_func == "_ready":
            body = _wrap_object_runtime_ready_body(body, object_runtime)
        if uses_object_runtime and object_runtime is not None and func.godot_func == "_exit_tree":
            body = _wrap_object_runtime_exit_tree_body(body, object_runtime)
        if uses_draw_runtime and func.godot_func in _DRAW_RUNTIME_FUNCTIONS:
            body = _wrap_draw_runtime_body(func, body)
        lines.append(f"\n\nfunc {func.godot_func}({func.params}):")
        lines.append(f"\n{body}\n")

    return ''.join(lines)
