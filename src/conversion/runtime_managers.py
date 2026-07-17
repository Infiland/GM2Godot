from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from src.conversion.project_godot import GodotProjectFile

RUNTIME_MANAGER_RELATIVE_DIR = os.path.join("gm2godot", "managers")


@dataclass(frozen=True)
class RuntimeManagerDefinition:
    name: str
    script_name: str
    order: int
    domain: str
    dependencies: tuple[str, ...] = ()
    state_keys: tuple[str, ...] = ()
    frame_pump: bool = False
    input_capture: bool = False
    draw_pump: bool = False
    async_pump: bool = False
    queued_godot_signals: tuple[str, ...] = ()

    @property
    def relative_path(self) -> str:
        return os.path.join(RUNTIME_MANAGER_RELATIVE_DIR, self.script_name)

    @property
    def resource_path(self) -> str:
        return "res://" + self.relative_path.replace(os.sep, "/")


RUNTIME_MANAGER_DEFINITIONS: tuple[RuntimeManagerDefinition, ...] = (
    RuntimeManagerDefinition(
        "GMRuntime",
        "gm_runtime_manager.gd",
        0,
        "runtime",
        state_keys=("manager_registry", "compatibility_facade", "startup"),
    ),
    RuntimeManagerDefinition(
        "GMAssets",
        "gm_assets.gd",
        10,
        "assets",
        dependencies=("GMRuntime",),
        state_keys=("asset_registry", "texture_groups", "audio_groups", "dynamic_assets"),
    ),
    RuntimeManagerDefinition(
        "GMRooms",
        "gm_rooms.gd",
        20,
        "rooms",
        dependencies=("GMRuntime", "GMAssets"),
        state_keys=("room_order", "current_room", "transitions", "layers"),
    ),
    RuntimeManagerDefinition(
        "GMInstances",
        "gm_instances.gd",
        30,
        "instances",
        dependencies=("GMRuntime", "GMAssets", "GMRooms"),
        state_keys=("instances", "handles", "object_indices", "creation_order"),
    ),
    RuntimeManagerDefinition(
        "GMEvents",
        "gm_events.gd",
        40,
        "events",
        dependencies=("GMRuntime", "GMRooms", "GMInstances"),
        state_keys=("event_queue", "alarms", "timeline_dispatch", "sequence_dispatch"),
        frame_pump=True,
        queued_godot_signals=(
            "Area2D.area_entered",
            "Area2D.body_entered",
            "AnimationPlayer.animation_finished",
            "Timer.timeout",
        ),
    ),
    RuntimeManagerDefinition(
        "GMDraw",
        "gm_draw.gd",
        50,
        "draw",
        dependencies=("GMRuntime", "GMAssets", "GMRooms", "GMInstances"),
        state_keys=("draw_state", "surfaces", "shader_cache", "texture_groups"),
        draw_pump=True,
    ),
    RuntimeManagerDefinition(
        "GMInput",
        "gm_input.gd",
        60,
        "input",
        dependencies=("GMRuntime", "GMEvents"),
        state_keys=("keyboard", "mouse", "gamepad", "gestures"),
        input_capture=True,
    ),
    RuntimeManagerDefinition(
        "GMAudio",
        "gm_audio.gd",
        70,
        "audio",
        dependencies=("GMRuntime", "GMAssets"),
        state_keys=("audio_instances", "audio_groups", "emitters", "listeners"),
    ),
    RuntimeManagerDefinition(
        "GMAsync",
        "gm_async.gd",
        80,
        "async",
        dependencies=("GMRuntime", "GMEvents"),
        state_keys=("async_load", "event_log", "http", "buffers", "networking"),
        async_pump=True,
        queued_godot_signals=(
            "HTTPRequest.request_completed",
            "AudioStreamPlayer.finished",
            "SceneTree.process_frame",
        ),
    ),
    RuntimeManagerDefinition(
        "GMPlatform",
        "gm_platform.gd",
        90,
        "platform",
        dependencies=("GMRuntime", "GMAsync"),
        state_keys=("service_hooks", "extension_schemas", "os_debug", "gc"),
    ),
)


def runtime_manager_definitions() -> tuple[RuntimeManagerDefinition, ...]:
    return tuple(sorted(RUNTIME_MANAGER_DEFINITIONS, key=lambda definition: definition.order))


def runtime_manager_autoloads() -> tuple[tuple[str, str], ...]:
    return tuple(
        (definition.name, definition.resource_path)
        for definition in runtime_manager_definitions()
    )


def write_runtime_managers(godot_project_path: str) -> tuple[str, ...]:
    output_paths: list[str] = []
    for definition in runtime_manager_definitions():
        output_path = os.path.join(godot_project_path, definition.relative_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(render_runtime_manager_script(definition))
        output_paths.append(output_path)
    return tuple(output_paths)


def register_runtime_manager_autoloads(godot_project_path: str) -> bool:
    project_path = os.path.join(godot_project_path, "project.godot")
    return GodotProjectFile(project_path).set_autoloads(runtime_manager_autoloads())


def render_runtime_manager_script(definition: RuntimeManagerDefinition) -> str:
    dependencies = _gdscript_string_array(definition.dependencies)
    state_keys = _gdscript_string_array(definition.state_keys)
    queued_godot_signals = _gdscript_string_array(definition.queued_godot_signals)
    lines = [
        "extends Node",
        "",
    ]
    if (
        definition.name == "GMRuntime"
        or definition.frame_pump
        or definition.input_capture
        or definition.draw_pump
        or definition.async_pump
    ):
        lines.extend([
            'const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")',
            "",
        ])
    lines.extend([
        f'const MANAGER_NAME = "{definition.name}"',
        f'const MANAGER_DOMAIN = "{definition.domain}"',
        f"const INITIALIZATION_ORDER = {definition.order}",
        f"const DEPENDENCIES = {dependencies}",
        f"const STATE_KEYS = {state_keys}",
        f"const QUEUED_GODOT_SIGNALS = {queued_godot_signals}",
        "",
        "var initialized = false",
        "var initialization_index = -1",
        "var state = {}",
        "var managers = {}",
        "var initialization_order = []",
        "",
        "",
        "func _ready():",
        "\tinitialize_runtime_manager()",
    ])
    if definition.name == "GMRuntime":
        lines.append("\tGMRuntimeFacade.gml_script_registry_entries()")
    lines.extend([
        "",
        "",
    ])
    if definition.name == "GMRuntime":
        lines.extend([
            "func _exit_tree():",
            "\tGMRuntimeFacade.gm2godot_runtime_shutdown()",
            "",
            "",
        ])
    if definition.frame_pump:
        lines.extend([
            "func _process(delta):",
            "\tGMRuntimeFacade.gml_input_dispatch_frame()",
            "\tGMRuntimeFacade.gml_event_scheduler_frame(float(delta), 1)",
            "\tGMRuntimeFacade.gml_input_end_frame()",
            "",
            "",
        ])
    if definition.input_capture:
        lines.extend([
            "func _input(event):",
            "\tGMRuntimeFacade.gml_input_event_capture(event)",
            "",
            "",
        ])
    if definition.draw_pump:
        lines.extend([
            "func _process(_delta):",
            "\tGMRuntimeFacade.gml_draw_event_dispatch_frame()",
            "",
            "",
        ])
    if definition.async_pump:
        lines.extend([
            "func _process(_delta):",
            "\tGMRuntimeFacade.gml_async_queue_flush()",
            "",
            "",
        ])
    lines.extend([
        "func initialize_runtime_manager():",
        "\tif initialized:",
        "\t\treturn state",
        "\t_seed_state()",
        "\tinitialized = true",
        "\tif MANAGER_NAME == \"GMRuntime\":",
        "\t\tregister_manager(self)",
        "\telse:",
        "\t\tvar runtime_root = _gm2godot_runtime_root()",
        "\t\tif runtime_root != null and runtime_root.has_method(\"register_manager\"):",
        "\t\t\truntime_root.register_manager(self)",
        "\treturn state",
        "",
        "",
        "func manager_name():",
        "\treturn MANAGER_NAME",
        "",
        "",
        "func manager_domain():",
        "\treturn MANAGER_DOMAIN",
        "",
        "",
        "func manager_dependencies():",
        "\treturn DEPENDENCIES.duplicate()",
        "",
        "",
        "func manager_state_keys():",
        "\treturn STATE_KEYS.duplicate()",
        "",
        "",
        "func manager_queued_godot_signals():",
        "\treturn QUEUED_GODOT_SIGNALS.duplicate()",
        "",
        "",
        "func set_initialization_index(index):",
        "\tinitialization_index = int(index)",
        "",
        "",
        "func manager_initialization_index():",
        "\treturn initialization_index",
        "",
        "",
        "func state_bucket(key = \"default\"):",
        "\tvar bucket_key = str(key)",
        "\tif not state.has(bucket_key) or typeof(state[bucket_key]) != TYPE_DICTIONARY:",
        "\t\tstate[bucket_key] = {}",
        "\treturn state[bucket_key]",
        "",
        "",
        "func state_snapshot():",
        "\treturn state.duplicate(true)",
        "",
        "",
        "func reset_runtime_state():",
        "\tstate.clear()",
        "\t_seed_state()",
        "",
        "",
        "func register_manager(manager):",
        "\tif manager == null or not manager.has_method(\"manager_name\"):",
        "\t\treturn null",
        "\tvar name = str(manager.manager_name())",
        "\tif not managers.has(name):",
        "\t\tinitialization_order.append(name)",
        "\t\tif manager.has_method(\"set_initialization_index\"):",
        "\t\t\tmanager.set_initialization_index(initialization_order.size() - 1)",
        "\tmanagers[name] = manager",
        "\tstate_bucket(\"manager_registry\")[name] = {",
        "\t\t\"domain\": manager.manager_domain() if manager.has_method(\"manager_domain\") else \"\",",
        "\t\t\"dependencies\": manager.manager_dependencies() if manager.has_method(\"manager_dependencies\") else [],",
        "\t\t\"state_keys\": manager.manager_state_keys() if manager.has_method(\"manager_state_keys\") else [],",
        "\t\t\"initialization_index\": manager.manager_initialization_index() if manager.has_method(\"manager_initialization_index\") else -1,",
        "\t}",
        "\treturn manager",
        "",
        "",
        "func manager(name):",
        "\treturn managers.get(str(name), null)",
        "",
        "",
        "func manager_order():",
        "\treturn initialization_order.duplicate()",
        "",
        "",
        "func manager_registry_snapshot():",
        "\treturn state_bucket(\"manager_registry\").duplicate(true)",
        "",
        "",
        "func _seed_state():",
        "\tstate[\"manager_name\"] = MANAGER_NAME",
        "\tstate[\"domain\"] = MANAGER_DOMAIN",
        "\tstate[\"dependencies\"] = DEPENDENCIES.duplicate()",
        "\tstate[\"state_keys\"] = STATE_KEYS.duplicate()",
        "\tfor key in STATE_KEYS:",
        "\t\tif not state.has(key):",
        "\t\t\tstate[key] = {}",
        "",
        "",
        "func _gm2godot_runtime_root():",
        "\tvar tree = get_tree()",
        "\tif tree == null or tree.root == null:",
        "\t\treturn null",
        "\treturn tree.root.get_node_or_null(\"GMRuntime\")",
        "",
    ])
    return "\n".join(lines)


def _gdscript_string_array(values: Iterable[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


__all__ = [
    "RUNTIME_MANAGER_DEFINITIONS",
    "RUNTIME_MANAGER_RELATIVE_DIR",
    "RuntimeManagerDefinition",
    "register_runtime_manager_autoloads",
    "render_runtime_manager_script",
    "runtime_manager_autoloads",
    "runtime_manager_definitions",
    "write_runtime_managers",
]
