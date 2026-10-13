from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal, TypedDict

from src.conversion.architecture_policy import (
    ROOM_ROOT_POLICY_ID,
    gui_canvas_layer_node_lines,
    room_root_metadata_lines,
)
from src.conversion.asset_registry import AssetRegistryConverter
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gml_transpiler import (
    GMLTranspileError,
    transpile_gml_code,
    transpile_gml_code_with_source_map,
)
from src.conversion.instance_change_diagnostics import record_instance_change_reads
from src.conversion.instance_change_names import InstanceChangeNames, collect_instance_change_names
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.object_variables import (
    VariableDefinition,
    parse_variable_definitions,
    parse_variable_overrides,
    variable_assignments_gml,
    variable_value_gml,
)
from src.conversion.project_enums import collect_project_enum_values
from src.conversion.project_godot import GodotProjectFile
from src.conversion.project_macros import collect_project_macro_values
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    is_safe_project_source_component,
)
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.room_creation_code import (
    ROOM_EXECUTION_ORDER,
    CreationCodeMetadata,
    CreationCodeSourceResolver,
    instance_creation_order_names,
    resolve_instance_creation_code,
    resolve_room_creation_code,
)
from src.conversion.room_display import (
    application_surface_display_settings,
    application_surface_size,
    room_view_entries,
)
from src.conversion.room_layers import godot_string, serialize_room_layers
from src.conversion.room_metadata import (
    RoomInstanceFields,
    RoomLayerFields,
    RoomPhysicsSettingsFields,
    RoomSceneRootFields,
    RoomSettingsFields,
    room_object_items,
    room_strict_layer_resource_type,
    room_value_length,
)
from src.conversion.type_defs import (
    ConversionRunning,
    LogCallback,
    ProgressCallback,
    StrPath,
)

ROOM_RUNTIME_SCRIPT_RELATIVE_PATH = os.path.join("gm2godot", "gml_room_node.gd")
ROOM_RUNTIME_SCRIPT_RESOURCE_PATH = "res://gm2godot/gml_room_node.gd"
ROOM_RUNTIME_EXT_RESOURCE_ID = "gm_room_runtime"
ROOM_SCRIPT_BASE_RESOURCE_PATH = "res://gm2godot/gml_room_node.gd"
_INSTANCE_CREATION_CODE_PREFIX = "InstanceCreationCode_"
_INSTANCE_CREATION_CODE_SUFFIX = ".gml"
_INSTANCE_CREATION_CODE_FIELD = "layers[].instances[].name"


def render_room_runtime_script() -> str:
    return (
        "extends Node2D\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        f'const GM2GODOT_ROOM_ROOT_POLICY = "{ROOM_ROOT_POLICY_ID}"\n\n'
        "func _enter_tree():\n"
        "\tGMRuntime._gml_view_room_prepare(self)\n"
        "\tGMRuntime.gml_room_prepare_scene(self)\n"
        "\n\n"
        "func _ready():\n"
        "\tGMRuntime.gml_room_enter_scene(self)\n"
        "\n\n"
        "func _process(delta):\n"
        "\tGMRuntime._gml_room_process_scene(self, delta)\n"
    )


class InstanceCreationCodeMethod(TypedDict):
    source_path: str
    method_name: str
    body: str


class InstancePreCreateMethod(TypedDict):
    """A placed instance's pre-creation code: its Room Editor variable overrides."""

    instance_name: str
    method_name: str
    body: str


def _room_script_resource_path(room: IndexedRoom) -> str:
    if room.godot_path.endswith(".tscn"):
        return room.godot_path[:-5] + ".gd"
    return room.godot_path + ".gd"


def _gdscript_identifier_suffix(value: str, fallback: str) -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_")
    if not identifier:
        identifier = fallback
    if identifier[0].isdigit():
        identifier = "_" + identifier
    return identifier


def _dict_items(value: JsonValue) -> list[JsonObject]:
    return room_object_items(value)


def _layer_resource_type(layer: JsonObject) -> str:
    return room_strict_layer_resource_type(layer)


def _instance_name(instance: JsonObject) -> str:
    return RoomInstanceFields(instance, "").name


def _instance_name_from_creation_code_source(source_path: str) -> str | None:
    if not (
        source_path.startswith(_INSTANCE_CREATION_CODE_PREFIX)
        and source_path.endswith(_INSTANCE_CREATION_CODE_SUFFIX)
    ):
        return None
    return source_path[
        len(_INSTANCE_CREATION_CODE_PREFIX):-len(_INSTANCE_CREATION_CODE_SUFFIX)
    ]


def _iter_room_instances(layers: JsonValue) -> list[JsonObject]:
    instances: list[JsonObject] = []
    for layer in _dict_items(layers):
        if _layer_resource_type(layer) == "GMRInstanceLayer":
            instances.extend(RoomLayerFields(layer, "").instances)
        instances.extend(_iter_room_instances(RoomLayerFields(layer, "").child_values))
    return instances


def _iter_room_effect_layers(layers: JsonValue) -> list[JsonObject]:
    effect_layers: list[JsonObject] = []
    for layer in _dict_items(layers):
        if _layer_resource_type(layer) == "GMREffectLayer":
            effect_layers.append(layer)
        effect_layers.extend(_iter_room_effect_layers(RoomLayerFields(layer, "").child_values))
    return effect_layers


class RoomProcessResult(TypedDict):
    status: Literal["completed", "skipped"]
    name: str
    width: JsonValue
    height: JsonValue
    scene_path: str


@dataclass(frozen=True)
class _DeclaredRoomResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


class _RoomCreationCodeBlocked(Exception):
    """Stop one room when declared creation code cannot be converted safely."""


class RoomConverter(BaseConverter):
    """Convert GameMaker rooms into minimal Godot room scenes."""

    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath,
                  log_callback: LogCallback = print,
                  progress_callback: ProgressCallback | None = None,
                  conversion_running: ConversionRunning | None = None,
                  update_log_callback: LogCallback | None = None,
                  compact_logging: bool = False,
                  max_workers: int | None = None,
                  resource_index: GameMakerResourceIndex | None = None,
                  diagnostics: DiagnosticCollector | None = None,
                  macro_configuration: str | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging,
                         max_workers=max_workers, diagnostics=diagnostics)
        self.godot_rooms_path = os.path.join(self.godot_project_path, "rooms")
        self.resource_index = resource_index
        self.macro_configuration = macro_configuration
        self._asset_names_cache: set[str] | None = None
        self._macro_values_cache: dict[str, str] | None = None
        self._instance_change_names_cache: InstanceChangeNames | None = None
        self._enum_values_cache: dict[str, dict[str, int]] | None = None

    def _build_resource_index(self) -> GameMakerResourceIndex:
        if self.resource_index is not None:
            return self.resource_index
        return GameMakerResourceIndex(
            self.gm_project_path,
            self.godot_project_path,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            conversion_running=self.conversion_running,
            update_log_callback=self.update_log_callback,
            compact_logging=self.compact_logging,
            max_workers=self.max_workers,
            diagnostics=self.diagnostics,
        ).build()

    def _declared_room_resources(
        self,
        index: GameMakerResourceIndex,
    ) -> tuple[_DeclaredRoomResource, ...] | None:
        """Return rooms selected by a valid YYP, including rejected paths."""
        manifest = index.project_manifest
        if index.yyp_data is None or manifest is None:
            return None

        raw_resources = manifest.raw_data.get("resources", [])
        if not isinstance(raw_resources, list):
            return ()

        declared: dict[str, _DeclaredRoomResource] = {}
        for resource_index, raw_resource in enumerate(
            raw_resources
        ):
            if not isinstance(raw_resource, dict):
                continue
            resource = raw_resource
            raw_resource_id = resource.get("id")
            if not isinstance(raw_resource_id, dict):
                continue
            resource_id = raw_resource_id
            raw_path = resource_id.get("path")
            normalized_path = (
                raw_path.replace("\\", "/")
                if isinstance(raw_path, str)
                else ""
            )
            resource_type = resource.get("resourceType")
            id_resource_type = resource_id.get("resourceType")
            is_room = (
                normalized_path.partition("/")[0].casefold() == "rooms"
                or resource_type == "GMRoom"
                or id_resource_type == "GMRoom"
            )
            if not is_room:
                continue

            raw_name = resource_id.get("name")
            name = (
                raw_name
                if isinstance(raw_name, str) and raw_name
                else os.path.splitext(os.path.basename(normalized_path))[0]
            )
            if not name:
                continue
            field = f"resources[{resource_index}].id.path"
            declared.setdefault(
                name,
                _DeclaredRoomResource(
                    name=name,
                    source_path=raw_path if isinstance(raw_path, str) else None,
                    owner_source_path=manifest.yyp_path,
                    manifest_field=field,
                ),
            )

        return tuple(declared.values())

    def _report_unavailable_declared_room(
        self,
        resource: _DeclaredRoomResource,
    ) -> None:
        if resource.source_path is None:
            reason = "its manifest source path was rejected"
        else:
            reason = f"metadata is unavailable at {resource.source_path!r}"
        message = (
            "Warning: Skipping manifest-declared GameMaker room "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-ROOM-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="room",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker room .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _generate_room_scene(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None = None,
        room_script_resource_path: str | None = None,
        source_resolver: CreationCodeSourceResolver | None = None,
    ) -> str:
        room_settings = RoomSettingsFields(room.room_settings, room.yy_path)
        physics_settings = RoomPhysicsSettingsFields(room.physics_settings, room.yy_path)
        room_creation_code = resolve_room_creation_code(
            room,
            self.gm_project_path,
            warn_callback=self._safe_log,
            source_resolver=source_resolver,
        )
        self._record_effect_layer_diagnostics(room)
        serialized_layers = serialize_room_layers(
            room,
            gm_project_path=self.gm_project_path,
            resource_index=resource_index,
            warn_callback=self._safe_log,
            creation_code_source_resolver=source_resolver,
        )

        script_resource_path = room_script_resource_path or ROOM_RUNTIME_SCRIPT_RESOURCE_PATH
        if serialized_layers.ext_resource_lines:
            lines = [
                f"[gd_scene format=3 load_steps={len(serialized_layers.ext_resource_lines) + 2}]",
                "",
                (
                    '[ext_resource type="Script" path="{path}" id="{resource_id}"]'.format(
                        path=script_resource_path,
                        resource_id=ROOM_RUNTIME_EXT_RESOURCE_ID,
                    )
                ),
            ]
            lines.extend(serialized_layers.ext_resource_lines)
            lines.append("")
        else:
            lines = [
                "[gd_scene format=3 load_steps=2]",
                "",
                (
                    '[ext_resource type="Script" path="{path}" id="{resource_id}"]'.format(
                        path=script_resource_path,
                        resource_id=ROOM_RUNTIME_EXT_RESOURCE_ID,
                    )
                ),
                "",
            ]

        lines.extend([
            f'[node name={godot_string(room.name)} type="Node2D"]',
            f'script = ExtResource("{ROOM_RUNTIME_EXT_RESOURCE_ID}")',
            f'metadata/gamemaker_room_width = {json.dumps(room_settings.width)}',
            f'metadata/gamemaker_room_height = {json.dumps(room_settings.height)}',
            f'metadata/gamemaker_room_persistent = {json.dumps(room_settings.persistent)}',
            f'metadata/gamemaker_room_volume = {json.dumps(RoomSceneRootFields(room.raw_data, room.yy_path).volume)}',
            f'metadata/gamemaker_parent_room = {json.dumps(room.parent_room)}',
            f'metadata/gamemaker_inherit_layers = {json.dumps(room.inherit_layers)}',
            f'metadata/gamemaker_inherit_creation_order = {json.dumps(room.inherit_creation_order)}',
            f'metadata/gamemaker_view_settings = {json.dumps(room.view_settings)}',
            f'metadata/gamemaker_view_count = {json.dumps(room_value_length(room.views))}',
            f'metadata/gamemaker_views = {json.dumps(room_view_entries(room.views, room.room_settings, room.yy_path))}',
            f'metadata/gamemaker_physics_world = {json.dumps(physics_settings.physics_world)}',
            f'metadata/gamemaker_physics_gravity_x = {json.dumps(physics_settings.gravity_x)}',
            f'metadata/gamemaker_physics_gravity_y = {json.dumps(physics_settings.gravity_y)}',
            f'metadata/gamemaker_physics_pixels_to_meters = {json.dumps(physics_settings.pixels_to_meters)}',
            f'metadata/gamemaker_source_yy_path = {json.dumps(room.yy_path)}',
            f'metadata/gamemaker_creation_code_file = {json.dumps(room.creation_code_file)}',
            f'metadata/gamemaker_creation_code_source_path = {json.dumps(room_creation_code.source_path)}',
            f'metadata/gamemaker_has_creation_code = {json.dumps(room_creation_code.has_code)}',
            f'metadata/gamemaker_inherit_code = {json.dumps(room_creation_code.inherit_code)}',
            f'metadata/gamemaker_is_dnd = {json.dumps(room_creation_code.is_dnd)}',
            f'metadata/gamemaker_creation_code_file_exists = {json.dumps(room_creation_code.exists)}',
            f'metadata/gamemaker_execution_order = {json.dumps(ROOM_EXECUTION_ORDER)}',
            f'metadata/gamemaker_instance_creation_order = {json.dumps(instance_creation_order_names(room))}',
            f'metadata/gamemaker_room_creation_code_execution_phase = {json.dumps(room_creation_code.execution_phase)}',
            f'metadata/gamemaker_room_creation_code_execution_phase_index = {json.dumps(room_creation_code.execution_phase_index)}',
        ])
        lines.extend(room_root_metadata_lines())
        lines.append("")
        lines.extend(gui_canvas_layer_node_lines())
        lines.extend(serialized_layers.node_lines)
        return "\n".join(lines)

    def _room_output_path(self, room: IndexedRoom) -> str:
        if room.godot_path.startswith("res://"):
            relative_path = room.godot_path[len("res://"):]
            return os.path.join(self.godot_project_path, *relative_path.split("/"))

        if room.subfolder:
            return os.path.join(
                self.godot_rooms_path, room.subfolder, room.name, room.name + ".tscn"
            )
        return os.path.join(self.godot_rooms_path, room.name, room.name + ".tscn")

    def _room_script_output_path(self, room: IndexedRoom) -> str:
        script_resource_path = _room_script_resource_path(room)
        if script_resource_path.startswith("res://"):
            relative_path = script_resource_path[len("res://"):]
            return os.path.join(self.godot_project_path, *relative_path.split("/"))
        return os.path.splitext(self._room_output_path(room))[0] + ".gd"

    def _generate_room_script(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None = None,
        source_resolver: CreationCodeSourceResolver | None = None,
    ) -> str | None:
        asset_names = self._asset_names(resource_index)
        room_creation_code = resolve_room_creation_code(
            room,
            self.gm_project_path,
            source_resolver=source_resolver,
        )
        room_creation_body: str | None = None
        has_creation_code_blocker = False
        if room_creation_code.has_code:
            try:
                if self._require_creation_code_source(
                    room_creation_code,
                    room_name=room.name,
                    event="room creation code",
                    missing_message=(
                        "Warning: Missing GameMaker room creation code file for room "
                        f"{room.name}: {room_creation_code.source_path}"
                    ),
                ):
                    room_creation_body = self._transpile_creation_code(
                        room_creation_code.source_path,
                        room.name,
                        "room creation code",
                        asset_names=asset_names,
                        top_level_global_scope=True,
                        # GameMaker runs room creation code with one stand-in
                        # instance as both self and other.
                        other_expression="self",
                    )
            except _RoomCreationCodeBlocked:
                has_creation_code_blocker = True

        instance_methods: list[InstanceCreationCodeMethod] = []
        used_method_names: dict[str, int] = {}
        for instance in _iter_room_instances(room.layers):
            creation_code = resolve_instance_creation_code(
                room,
                instance,
                gm_project_path=self.gm_project_path,
                source_resolver=source_resolver,
            )
            if not creation_code.has_code:
                continue
            instance_name = _instance_name(instance)
            event = f"instance creation code for {instance_name}"
            try:
                if not self._require_creation_code_source(
                    creation_code,
                    room_name=room.name,
                    event=event,
                    missing_message=(
                        "Warning: Missing GameMaker instance creation code file for "
                        f"room {room.name}, instance {instance_name}: "
                        f"{creation_code.source_path}"
                    ),
                ):
                    continue
                body = self._transpile_creation_code(
                    creation_code.source_path,
                    room.name,
                    event,
                    asset_names=asset_names,
                    self_expression="_gm_instance",
                    # Like its Create event, an instance's creation code runs
                    # with the instance as both self and other.
                    other_expression="_gm_instance",
                    instance_target="_gm_instance",
                )
            except _RoomCreationCodeBlocked:
                has_creation_code_blocker = True
                continue
            method_name = self._unique_instance_creation_method_name(
                instance_name,
                used_method_names,
            )
            instance_methods.append({
                "source_path": creation_code.source_path,
                "method_name": method_name,
                "body": body,
            })

        pre_create_methods = self._instance_pre_create_methods(
            room,
            resource_index,
            asset_names,
        )
        if has_creation_code_blocker:
            raise _RoomCreationCodeBlocked(
                f"Declared creation code blocked room {room.name}"
            )
        if room_creation_body is None and not instance_methods and not pre_create_methods:
            return None
        return self._render_room_script(
            room_creation_body,
            instance_methods,
            pre_create_methods,
        )

    def _instance_pre_create_methods(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None,
        asset_names: set[str],
    ) -> list[InstancePreCreateMethod]:
        """Return the pre-creation code of the room's instances.

        A placed instance whose Variable Definitions were changed in the Room
        Editor assigns the new values, in their .yy order, after its object's
        definitions and before its Create event.
        """
        methods: list[InstancePreCreateMethod] = []
        used_method_names: dict[str, int] = {}
        seen_names: set[str] = set()
        definitions_cache: dict[str, Mapping[str, VariableDefinition]] = {}
        blocked = False
        for instance in _iter_room_instances(room.layers):
            overrides = parse_variable_overrides(RoomInstanceFields(instance, room.yy_path).properties)
            instance_name = _instance_name(instance)
            if not overrides or instance_name in seen_names:
                continue
            seen_names.add(instance_name)
            source = variable_assignments_gml(
                (
                    override.name,
                    variable_value_gml(
                        override.value,
                        self._object_variable_definitions(
                            override.object_name,
                            resource_index,
                            definitions_cache,
                        ).get(override.name),
                    ),
                )
                for override in overrides
            )
            try:
                body = self._transpile_pre_create_code(source, room, instance_name, asset_names)
            except _RoomCreationCodeBlocked:
                blocked = True
                continue
            methods.append({
                "instance_name": instance_name,
                "method_name": self._unique_instance_creation_method_name(
                    instance_name,
                    used_method_names,
                    prefix="_gm2godot_instance_pre_create_",
                ),
                "body": body,
            })
        if blocked:
            raise _RoomCreationCodeBlocked(
                f"Room Editor variable overrides blocked room {room.name}"
            )
        return methods

    def _object_variable_definitions(
        self,
        object_name: str | None,
        resource_index: GameMakerResourceIndex | None,
        cache: dict[str, Mapping[str, VariableDefinition]],
    ) -> Mapping[str, VariableDefinition]:
        """Return an object's Variable Definitions by name (empty when unreadable)."""
        if object_name is None:
            return {}
        if object_name not in cache:
            resource = (
                resource_index.get_resource("objects", object_name)
                if resource_index is not None
                else None
            )
            yy_path = (
                resource.yy_path
                if resource is not None
                else os.path.join(self.gm_project_path, "objects", object_name, object_name + ".yy")
            )
            data = self._read_yy_file(yy_path)
            definitions = parse_variable_definitions(data.get("properties") if data is not None else None)
            cache[object_name] = {definition.name: definition for definition in definitions}
        return cache[object_name]

    def _project_macro_values(self) -> dict[str, str]:
        if self._macro_values_cache is None:
            self._macro_values_cache = collect_project_macro_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return self._macro_values_cache

    def _project_instance_change_names(self) -> InstanceChangeNames:
        if self._instance_change_names_cache is None:
            self._instance_change_names_cache = collect_instance_change_names(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
                macro_values=self._project_macro_values(),
            )
        return self._instance_change_names_cache

    def _project_enum_values(self) -> dict[str, dict[str, int]]:
        if self._enum_values_cache is None:
            self._enum_values_cache = collect_project_enum_values(
                self.gm_project_path,
                macro_configuration=self.macro_configuration,
            )
        return self._enum_values_cache

    def _transpile_pre_create_code(
        self,
        source: str,
        room: IndexedRoom,
        instance_name: str,
        asset_names: set[str],
    ) -> str:
        event = f"pre-creation code for {instance_name}"
        try:
            # Like its Create event, an instance's pre-creation code runs
            # with the instance as both self and other.
            return transpile_gml_code(
                source,
                asset_names=asset_names,
                macro_configuration=self.macro_configuration,
                source_path=room.yy_path,
                event=event,
                self_expression="_gm_instance",
                other_expression="_gm_instance",
                instance_target="_gm_instance",
                enum_values=self._project_enum_values(),
                macro_values=self._project_macro_values(),
            )
        except GMLTranspileError as exc:
            message = (
                "Warning: Could not transpile the Room Editor variable overrides "
                f"({event}) for room {room.name}: {exc}"
            )
            if self.diagnostics is not None:
                self.diagnostics.add_transpile_failure(
                    message,
                    source_path=room.yy_path,
                    resource=room.name,
                    resource_type="room",
                    event=event,
                    workaround=(
                        "Rewrite the overridden variable values as GML expressions "
                        "the converter supports, or add the missing runtime/API "
                        "support tracked by the linked issue."
                    ),
                )
            self._safe_log(message)
            raise _RoomCreationCodeBlocked(message) from exc

    def _require_creation_code_source(
        self,
        metadata: CreationCodeMetadata,
        *,
        room_name: str,
        event: str,
        missing_message: str,
    ) -> bool:
        """Return whether declared creation code has a readable source file.

        GameMaker runs a declared creation-code file that is absent on disk as
        empty code, so the room still converts without it. Rejected (unsafe)
        source paths still block the room.
        """
        if metadata.exists:
            return True
        if metadata.path_rejected:
            raise _RoomCreationCodeBlocked(
                f"Rejected declared {event} source for room {room_name}"
            )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-ROOM-CREATION-MISSING",
                missing_message,
                source_path=metadata.source_path or None,
                resource=room_name,
                resource_type="room",
                event=event,
                workaround=(
                    "GameMaker runs a missing creation-code file as empty code, so the "
                    "room was converted without it. Restore the source file if the "
                    "creation code was not meant to be empty."
                ),
            )
        self._safe_log(missing_message)
        return False

    def _transpile_creation_code(
        self,
        source_path: str,
        room_name: str,
        label: str,
        *,
        asset_names: set[str],
        top_level_global_scope: bool = False,
        self_expression: str = "self",
        other_expression: str = "other",
        instance_target: str | None = None,
    ) -> str:
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                source = f.read()
        except OSError as exc:
            message = (
                "Warning: Could not read GameMaker {label} for room {room}: "
                "{path}: {error}".format(
                    label=label,
                    room=room_name,
                    path=source_path,
                    error=exc,
                )
            )
            if self.diagnostics is not None:
                self.diagnostics.add(
                    "warning",
                    "GM2GD-ROOM-CREATION-READ",
                    message,
                    source_path=source_path,
                    resource=room_name,
                    resource_type="room",
                    event=label,
                    workaround=(
                        "Restore readable GameMaker creation-code source before "
                        "converting this room."
                    ),
                )
            self._safe_log(message)
            raise _RoomCreationCodeBlocked(message) from exc

        instance_change_names = self._project_instance_change_names()
        try:
            # An instance's creation code runs from the room's start-up, with
            # no method of the instance's script below it, so an instance_change
            # in it can run the rest of the code on the new object.
            result = transpile_gml_code_with_source_map(
                source,
                asset_names=asset_names,
                top_level_global_scope=top_level_global_scope,
                macro_configuration=self.macro_configuration,
                source_path=source_path,
                event=label,
                preserve_source_comments=True,
                self_expression=self_expression,
                other_expression=other_expression,
                instance_target=instance_target,
                instance_change_continuations=instance_target is not None,
                instance_change_names=instance_change_names.all,
                enum_values=self._project_enum_values(),
                macro_values=self._project_macro_values(),
            )
            code = result.code
        except GMLTranspileError as exc:
            message = (
                "Warning: Could not transpile GameMaker {label} for room {room}: {path}: {error}".format(
                    label=label,
                    room=room_name,
                    path=source_path,
                    error=exc,
                )
            )
            if self.diagnostics is not None:
                self.diagnostics.add_transpile_failure(
                    message,
                    source_path=source_path,
                    line=exc.line,
                    column=exc.column,
                    resource=room_name,
                    resource_type="room",
                    event=label,
                    workaround=(
                        "Split or rewrite unsupported GML for this creation-code "
                        "source, or add the missing runtime/API support tracked by "
                        "the linked issue."
                    ),
                )
            self._safe_log(message)
            raise _RoomCreationCodeBlocked(message) from exc
        if self.diagnostics is not None:
            self.diagnostics.add_unsupported_calls(
                code,
                source_path=source_path,
                resource=room_name,
                resource_type="room",
                event=label,
            )
            record_instance_change_reads(
                self.diagnostics,
                source,
                known_names=asset_names | set(self._project_enum_values()) | set(self._project_macro_values()),
                continued_calls=result.continued_instance_changes,
                names=instance_change_names,
                source_path=source_path,
                resource=room_name,
                resource_type="room",
                event=label,
            )
        return code

    def _render_room_script(
        self,
        room_creation_body: str | None,
        instance_methods: list[InstanceCreationCodeMethod],
        pre_create_methods: Sequence[InstancePreCreateMethod] = (),
    ) -> str:
        lines = [f'extends "{ROOM_SCRIPT_BASE_RESOURCE_PATH}"']
        if pre_create_methods:
            # The runtime calls it on the placed instance after its object's
            # Variable Definitions (gml_instance_pre_create).
            lines.extend([
                "",
                "func _gm2godot_run_instance_pre_create_code(_gm_instance):",
                "\tif _gm_instance == null or not _gm_instance.has_meta(\"gamemaker_instance_name\"):",
                "\t\treturn false",
                "\tmatch str(_gm_instance.get_meta(\"gamemaker_instance_name\")):",
            ])
            for pre_create in pre_create_methods:
                lines.extend([
                    f"\t\t{json.dumps(pre_create['instance_name'])}:",
                    f"\t\t\t{pre_create['method_name']}(_gm_instance)",
                    "\t\t\treturn true",
                ])
            lines.append("\treturn false")
            for pre_create in pre_create_methods:
                lines.extend([
                    "",
                    f"func {pre_create['method_name']}(_gm_instance):",
                    pre_create["body"],
                ])
        if instance_methods:
            lines.extend([
                "",
                "func _gm2godot_run_instance_creation_code(_gm_instance):",
                "\tif _gm_instance == null:",
                "\t\treturn false",
                "\tif not _gm_instance.has_meta(\"gamemaker_creation_code_source_path\"):",
                "\t\treturn false",
                "\tvar _gm_source_path = str(_gm_instance.get_meta(\"gamemaker_creation_code_source_path\"))",
                "\tmatch _gm_source_path:",
            ])
            for method in instance_methods:
                lines.extend([
                    f"\t\t{json.dumps(method['source_path'])}:",
                    f"\t\t\t{method['method_name']}(_gm_instance)",
                    "\t\t\treturn true",
                ])
            lines.extend([
                "\treturn false",
            ])

            for method in instance_methods:
                lines.extend([
                    "",
                    f"func {method['method_name']}(_gm_instance):",
                    method["body"],
                ])

        if room_creation_body is not None:
            lines.extend([
                "",
                "func _gm2godot_room_creation_code():",
                room_creation_body,
            ])

        return "\n".join(lines).rstrip() + "\n"

    def _record_effect_layer_diagnostics(self, room: IndexedRoom) -> None:
        if self.diagnostics is None:
            return
        for layer in _iter_room_effect_layers(room.layers):
            layer_name = RoomLayerFields(layer, room.yy_path).effect_name
            effect_type = RoomLayerFields(layer, room.yy_path).effect_type
            self.diagnostics.add(
                "warning",
                "GM2GD-RESOURCE-UNSUPPORTED",
                "GameMaker effect/filter layer {layer_name} in room {room_name} "
                "is preserved as metadata; native shader/filter behavior requires "
                "project-specific Godot material support.".format(
                    layer_name=layer_name if isinstance(layer_name, str) and layer_name else "Layer",
                    room_name=room.name,
                ),
                source_path=room.yy_path,
                resource=room.name,
                resource_type="room",
                event=str(effect_type) if isinstance(effect_type, str) and effect_type else None,
                issue_number=592,
                workaround="Replace the effect with a Godot material/shader or add a project-specific compatibility mapping.",
            )

    def _unique_instance_creation_method_name(
        self,
        instance_name: str,
        used_method_names: dict[str, int],
        prefix: str = "_gm2godot_instance_creation_code_",
    ) -> str:
        base = prefix + _gdscript_identifier_suffix(
            instance_name,
            "instance",
        )
        count = used_method_names.get(base, 0)
        used_method_names[base] = count + 1
        if count == 0:
            return base
        return f"{base}_{count + 1}"

    def _asset_names(self, resource_index: GameMakerResourceIndex | None) -> set[str]:
        if self._asset_names_cache is not None:
            return set(self._asset_names_cache)

        try:
            registry_converter = AssetRegistryConverter(
                self.gm_project_path,
                self.godot_project_path,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=self.conversion_running,
            )
            asset_names = {entry.name for entry in registry_converter.build_entries()}
            self._asset_names_cache = asset_names
            return set(asset_names)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        if resource_index is None:
            self._asset_names_cache = set()
            return set()
        names = set(resource_index.rooms.keys())
        for resources in resource_index.resources.values():
            names.update(resources.keys())
        self._asset_names_cache = names
        return set(names)

    def _process_room(
        self, room: IndexedRoom, resource_index: GameMakerResourceIndex | None = None
    ) -> RoomProcessResult | None:
        if not self.conversion_running():
            return None

        source_cache: dict[tuple[str, str], str | None] = {}

        def resolve_creation_code_source(source_path: str, field: str) -> str | None:
            cache_key = (source_path, field)
            if cache_key not in source_cache:
                if field == _INSTANCE_CREATION_CODE_FIELD:
                    instance_name = _instance_name_from_creation_code_source(source_path)
                    if (
                        instance_name is None
                        or not is_safe_project_source_component(instance_name)
                    ):
                        self._report_source_path_rejection(
                            source_path,
                            ProjectSourcePathError(
                                "GameMaker instance names used to derive "
                                "creation-code filenames must be exactly one "
                                "safe path component"
                            ),
                            owner_source_path=room.yy_path,
                            resource=room.name,
                            resource_type="room",
                            field=field,
                        )
                        source_cache[cache_key] = None
                        return None
                resolved = self._resolve_project_source(
                    source_path,
                    owner_source_path=room.yy_path,
                    resource=room.name,
                    resource_type="room",
                    field=field,
                )
                if (
                    resolved is not None
                    and field == _INSTANCE_CREATION_CODE_FIELD
                    and posixpath.dirname(resolved.source_path)
                    != posixpath.dirname(room.yyp_path.replace("\\", "/"))
                ):
                    self._report_source_path_rejection(
                        source_path,
                        ProjectSourcePathError(
                            "GameMaker instance creation-code filenames must "
                            "stay beside their declaring room .yy file"
                        ),
                        owner_source_path=room.yy_path,
                        resource=room.name,
                        resource_type="room",
                        field=field,
                    )
                    resolved = None
                source_cache[cache_key] = (
                    resolved.filesystem_path if resolved is not None else None
                )
            return source_cache[cache_key]

        output_path = self._room_output_path(room)
        width = RoomSettingsFields(room.room_settings, room.yy_path).width
        height = RoomSettingsFields(room.room_settings, room.yy_path).height
        try:
            room_script = self._generate_room_script(
                room,
                resource_index,
                resolve_creation_code_source,
            )
        except _RoomCreationCodeBlocked:
            return {
                "status": "skipped",
                "name": room.name,
                "width": width,
                "height": height,
                "scene_path": room.godot_path,
            }
        room_script_resource_path: str | None = None
        if room_script is not None:
            room_script_resource_path = _room_script_resource_path(room)
            script_output_path = self._room_script_output_path(room)
            os.makedirs(os.path.dirname(script_output_path), exist_ok=True)
            with open(script_output_path, "w", encoding="utf-8") as f:
                f.write(room_script)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(
                self._generate_room_scene(
                    room,
                    resource_index,
                    room_script_resource_path,
                    resolve_creation_code_source,
                )
            )

        return {
            "status": "completed",
            "name": room.name,
            "width": width,
            "height": height,
            "scene_path": room.godot_path,
        }

    def _process_room_with_outcome(
        self,
        room: IndexedRoom,
        resource_index: GameMakerResourceIndex | None = None,
    ) -> RoomProcessResult | None:
        if not self.conversion_running():
            return None
        self._resource_requested(room.name)
        self._resource_started(room.name)
        try:
            result = self._process_room(room, resource_index)
        except Exception:
            self._resource_failed(room.name)
            raise
        if result is None:
            self._resource_skipped(room.name)
        elif result["status"] == "completed":
            self._resource_completed(room.name)
        else:
            self._resource_skipped(room.name)
        return result

    def _log_startup_warning(self, message: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.add_from_log_message(message)
        self.log_callback(message)

    def _set_startup_scene(
        self, index: GameMakerResourceIndex, generated_scene_paths: dict[str, str]
    ) -> None:
        project_file = GodotProjectFile(
            os.path.join(self.godot_project_path, "project.godot")
        )
        if not generated_scene_paths:
            if self._clear_stale_managed_main_scene(
                project_file,
                generated_scene_paths,
            ):
                self._log_startup_warning(
                    "Warning: No room scene generated; removed the stale "
                    "GM2Godot-managed project.godot main_scene."
                )
            else:
                self._log_startup_warning(
                    "Warning: No room scene generated; leaving project.godot "
                    "main_scene unchanged."
                )
            return

        first_room = index.first_room()
        if first_room is None or first_room.name not in generated_scene_paths:
            if self._clear_stale_managed_main_scene(
                project_file,
                generated_scene_paths,
            ):
                self._log_startup_warning(
                    "Warning: First GameMaker room scene was not generated; "
                    "removed the stale GM2Godot-managed project.godot main_scene."
                )
            else:
                self._log_startup_warning(
                    "Warning: First GameMaker room scene was not generated; "
                    "leaving project.godot main_scene unchanged."
                )
            return

        scene_path = generated_scene_paths[first_room.name]
        if project_file.set_main_scene(scene_path):
            self.log_callback(
                "Set Godot startup scene to first GameMaker room: {name} ({scene_path})".format(
                    name=first_room.name,
                    scene_path=scene_path,
                )
            )
            self._set_application_surface_display(project_file, first_room)
        else:
            self._log_startup_warning(
                "Warning: project.godot not found; could not set startup scene."
            )

    def _set_application_surface_display(
        self, project_file: GodotProjectFile, first_room: IndexedRoom
    ) -> None:
        """Size the root viewport like GameMaker's application surface.

        GameMaker derives the application surface (and the initial window)
        from the first room: the visible viewports' bounding box when views
        are enabled, otherwise the room size. Later rooms are scaled onto
        that fixed surface, which Godot's ``viewport`` stretch mode mirrors.
        """
        width, height = application_surface_size(
            first_room.room_settings,
            first_room.view_settings,
            first_room.views,
            first_room.yy_path,
        )
        for section, key, value in application_surface_display_settings(width, height):
            project_file.set_setting(section, key, value)
        self.log_callback(
            "Set Godot viewport to the GameMaker application surface size "
            f"{width}x{height} from first room {first_room.name}"
        )

    @staticmethod
    def _clear_stale_managed_main_scene(
        project_file: GodotProjectFile,
        generated_scene_paths: dict[str, str],
    ) -> bool:
        current = project_file.get_string_setting(
            "application",
            "run/main_scene",
        )
        if (
            current is None
            or not current.startswith("res://rooms/")
            or current in generated_scene_paths.values()
        ):
            return False
        return project_file.remove_setting("application", "run/main_scene")

    def convert_rooms(self) -> None:
        index = self._build_resource_index()
        rooms = index.ordered_rooms()
        declared_rooms = self._declared_room_resources(index)
        if declared_rooms is None:
            for room in rooms:
                self._resource_requested(room.name)
        else:
            available_names = {room.name for room in rooms}
            for resource in declared_rooms:
                self._resource_requested(resource.name)
                if resource.name in available_names:
                    continue
                self._report_unavailable_declared_room(resource)
                self._resource_skipped(resource.name)

        if not rooms:
            self._set_startup_scene(index, {})
            self.log_callback("Room conversion completed.")
            return

        self._write_room_runtime_script()

        total = len(rooms)
        processed = 0
        generated_scene_paths: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map = {
                executor.submit(self._process_room_with_outcome, room, index): room.name
                for room in rooms
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback("Room conversion stopped.")
                    return

                processed += 1
                if result["status"] == "completed":
                    generated_scene_paths[result["name"]] = result["scene_path"]
                    if self.compact_logging:
                        self._safe_log_progress(result["name"], processed, total)
                    else:
                        self._safe_log(
                            "Converted room: {name} ({width}x{height})".format(
                                name=result["name"],
                                width=result["width"],
                                height=result["height"],
                            )
                        )

                self._safe_progress(processed / total * 100)

        self._set_startup_scene(index, generated_scene_paths)
        self.log_callback("Room conversion completed.")

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_rooms()

    def _write_room_runtime_script(self) -> None:
        runtime_path = os.path.join(self.godot_project_path, ROOM_RUNTIME_SCRIPT_RELATIVE_PATH)
        os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
        with open(runtime_path, "w", encoding="utf-8") as f:
            f.write(render_room_runtime_script())
