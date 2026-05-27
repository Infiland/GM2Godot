import copy
import os
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, cast

from src.conversion.base_converter import BaseConverter
from src.conversion.generated_paths import generated_nested_resource_path
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectResourceReference,
    load_gamemaker_project_manifest,
)
from src.conversion.type_defs import (
    ConversionRunning,
    JsonDict,
    JsonList,
    LogCallback,
    ProgressCallback,
)


def _empty_json_dict() -> JsonDict:
    return cast(JsonDict, {})


def _empty_json_list() -> JsonList:
    return cast(JsonList, [])


@dataclass(frozen=True)
class IndexedResource:
    """A GameMaker resource with matching generated Godot path metadata."""

    kind: str
    name: str
    yy_path: str
    yyp_path: str
    godot_path: str
    subfolder: str = ""
    uuid: str = ""
    resource_type: str = ""
    order: int = 0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexedRoom:
    """Normalized room data needed before actual room scene generation."""

    name: str
    yy_path: str
    yyp_path: str
    godot_path: str
    subfolder: str = ""
    room_settings: JsonDict = field(default_factory=_empty_json_dict)
    physics_settings: JsonDict = field(default_factory=_empty_json_dict)
    view_settings: JsonDict = field(default_factory=_empty_json_dict)
    views: JsonList = field(default_factory=_empty_json_list)
    layers: JsonList = field(default_factory=_empty_json_list)
    instance_creation_order: JsonList = field(default_factory=_empty_json_list)
    parent_room: JsonDict | None = None
    creation_code_file: str = ""
    inherit_code: bool = False
    inherit_creation_order: bool = False
    inherit_layers: bool = False
    is_dnd: bool = False
    raw_data: JsonDict = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class IndexedExtensionFunction:
    """A GameMaker extension function discovered from extension metadata."""

    extension_name: str
    function_name: str
    yy_path: str
    yyp_path: str
    file_name: str = ""
    external_name: str = ""
    arg_count: int | None = None


class GameMakerResourceIndex(BaseConverter):
    """Index GameMaker project resources for converters that need cross references."""

    RESOURCE_EXTENSIONS: ClassVar[dict[str, str]] = {
        "rooms": ".tscn",
        "objects": ".tscn",
        "sprites": ".tscn",
        "tilesets": ".tres",
    }

    def __init__(self, gm_project_path: str, godot_project_path: str,
                 log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None,
                 conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None,
                 compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging,
                         max_workers=max_workers)
        self.yyp_path: str | None = None
        self.yyp_data: JsonDict | None = None
        self.project_manifest: GameMakerProjectManifest | None = None
        self.resources: dict[str, dict[str, IndexedResource]] = self._empty_resources()
        self.rooms: dict[str, IndexedRoom] = {}
        self.extension_functions: dict[str, IndexedExtensionFunction] = {}
        self.room_order: list[str] = []
        self.used_room_order_fallback = False

    def convert_all(self) -> "GameMakerResourceIndex":
        """Build the in-memory index. No Godot files are written."""
        return self.build()

    def build(self) -> "GameMakerResourceIndex":
        """Build and return this resource index."""
        self.resources = self._empty_resources()
        self.rooms = {}
        self.extension_functions = {}
        self.room_order = []
        self.used_room_order_fallback = False
        self.project_manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self.yyp_path = self.project_manifest.yyp_path
        self.yyp_data = self.project_manifest.raw_data if self.project_manifest.raw_data else None

        if self.yyp_data is not None:
            self._index_yyp_resources()
            self._stabilize_resource_paths()
            self._parse_indexed_rooms()
            self._apply_yyp_room_order(self.yyp_data)
            self._resolve_room_inheritance()
        else:
            if self.yyp_path:
                self._safe_log(
                    "Could not parse GameMaker project .yyp; falling back to disk scan."
                )
            else:
                self._safe_log(
                    "No GameMaker project .yyp found; falling back to disk scan."
                )
            self._index_disk_resources()
            self._stabilize_resource_paths()
            self._parse_indexed_rooms()
            self._resolve_room_inheritance()
            self.used_room_order_fallback = True
            self.room_order = sorted(self.rooms)

        return self

    def find_yyp_path(self) -> str | None:
        """Return the first .yyp path in the GameMaker project, if any."""
        try:
            yyp_files = sorted(
                name for name in os.listdir(self.gm_project_path)
                if name.endswith(".yyp")
            )
        except OSError:
            return None

        if not yyp_files:
            return None
        return os.path.join(self.gm_project_path, yyp_files[0])

    def get_resource(self, kind: str, name: str) -> IndexedResource | None:
        """Return an indexed non-room resource, or a room resource, by kind/name."""
        return self.resources.get(kind, {}).get(name)

    def get_resources(self, kind: str) -> dict[str, IndexedResource]:
        """Return all indexed resources for a supported kind."""
        return dict(self.resources.get(kind, {}))

    def get_room(self, name: str) -> IndexedRoom | None:
        """Return normalized room data by name."""
        return self.rooms.get(name)

    def ordered_rooms(self) -> list[IndexedRoom]:
        """Return normalized rooms in GameMaker room order when available."""
        return [self.rooms[name] for name in self.room_order if name in self.rooms]

    def first_room(self) -> IndexedRoom | None:
        """Return the first GameMaker room, or None when no room is indexed."""
        ordered = self.ordered_rooms()
        return ordered[0] if ordered else None

    def resolve_gm_path(self, kind: str, name: str) -> str | None:
        """Return the source GameMaker .yy path for a resource, if indexed."""
        resource = self.get_resource(kind, name)
        return resource.yy_path if resource else None

    def resolve_godot_path(self, kind: str, name: str) -> str | None:
        """Return the generated res:// path for a resource, if indexed."""
        resource = self.get_resource(kind, name)
        return resource.godot_path if resource else None

    def find_project_resources(
        self,
        *,
        uuid: str | None = None,
        name: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        resource_type: str | None = None,
    ) -> tuple[ProjectResourceReference, ...]:
        """Return manifest resource references matched by UUID, name, path, kind, or type."""
        if self.project_manifest is None:
            return ()
        return self.project_manifest.find_resources(
            uuid=uuid,
            name=name,
            path=path,
            kind=kind,
            resource_type=resource_type,
        )

    def resolve_indexed_resource(
        self,
        *,
        uuid: str | None = None,
        name: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        resource_type: str | None = None,
    ) -> IndexedResource | None:
        """Return the first indexed resource matched by manifest metadata."""
        matches = self.find_project_resources(
            uuid=uuid,
            name=name,
            path=path,
            kind=kind,
            resource_type=resource_type,
        )
        for reference in matches:
            resource = self.get_resource(reference.kind, reference.name)
            if resource is not None:
                return resource
        return None

    def get_extension_function(self, name: str) -> IndexedExtensionFunction | None:
        """Return extension function metadata by GML function name, if discovered."""
        return self.extension_functions.get(name)

    def get_extension_functions(self) -> dict[str, IndexedExtensionFunction]:
        """Return discovered GameMaker extension functions by GML function name."""
        return dict(self.extension_functions)

    def extension_function_names(self) -> set[str]:
        """Return all discovered GameMaker extension function names."""
        return set(self.extension_functions)

    def _empty_resources(self) -> dict[str, dict[str, IndexedResource]]:
        return {kind: {} for kind in self.RESOURCE_EXTENSIONS}

    def _index_yyp_resources(self) -> None:
        if self.project_manifest is None:
            return
        for resource_ref in self.project_manifest.resources:
            yyp_path = resource_ref.path
            kind = resource_ref.kind
            if kind == "extensions":
                name = resource_ref.name or self._name_from_yyp_path(yyp_path)
                if name:
                    yy_path = os.path.normpath(os.path.join(self.gm_project_path, yyp_path))
                    self._index_extension_resource(name, yy_path, yyp_path)
                continue
            if kind not in self.RESOURCE_EXTENSIONS:
                continue

            name = resource_ref.name or self._name_from_yyp_path(yyp_path)
            if not name:
                continue

            yy_path = os.path.normpath(os.path.join(self.gm_project_path, yyp_path))
            if not os.path.isfile(yy_path):
                self._safe_log(
                    f"Skipping missing GameMaker resource {name}: {yy_path}"
                )
                continue

            self.resources[kind][name] = self._make_resource(kind, name, yy_path, yyp_path, resource_ref)

    def _index_disk_resources(self) -> None:
        for kind in self.RESOURCE_EXTENSIONS:
            kind_dir = os.path.join(self.gm_project_path, kind)
            if not os.path.isdir(kind_dir):
                continue

            for name in sorted(os.listdir(kind_dir)):
                resource_dir = os.path.join(kind_dir, name)
                yy_path = os.path.join(resource_dir, name + ".yy")
                if not os.path.isdir(resource_dir) or not os.path.isfile(yy_path):
                    continue
                yyp_path = "/".join([kind, name, name + ".yy"])
                self.resources[kind][name] = self._make_resource(
                    kind, name, yy_path, yyp_path
                )
        extensions_dir = os.path.join(self.gm_project_path, "extensions")
        if not os.path.isdir(extensions_dir):
            return
        for name in sorted(os.listdir(extensions_dir)):
            extension_dir = os.path.join(extensions_dir, name)
            yy_path = os.path.join(extension_dir, name + ".yy")
            if not os.path.isdir(extension_dir) or not os.path.isfile(yy_path):
                continue
            yyp_path = "/".join(["extensions", name, name + ".yy"])
            self._index_extension_resource(name, yy_path, yyp_path)

    def _index_extension_resource(self, name: str, yy_path: str, yyp_path: str) -> None:
        if not os.path.isfile(yy_path):
            self._safe_log(
                f"Skipping missing GameMaker extension {name}: {yy_path}"
            )
            return
        data = self._read_yy_file(yy_path)
        if data is None:
            self._safe_log(
                f"Skipping malformed GameMaker extension {name}: {yy_path}"
            )
            return
        extension_name = str(data.get("name") or data.get("%Name") or name)
        for extension_file in data.get("files", []):
            if not isinstance(extension_file, dict):
                continue
            file_data = cast(JsonDict, extension_file)
            file_name = str(file_data.get("filename") or file_data.get("name") or "")
            for function_data in file_data.get("functions", []):
                if not isinstance(function_data, dict):
                    continue
                function = self._parse_extension_function(
                    extension_name,
                    yy_path,
                    yyp_path,
                    file_name,
                    cast(JsonDict, function_data),
                )
                if function is not None:
                    self.extension_functions[function.function_name] = function

    @staticmethod
    def _parse_extension_function(
        extension_name: str,
        yy_path: str,
        yyp_path: str,
        file_name: str,
        function_data: JsonDict,
    ) -> IndexedExtensionFunction | None:
        function_name = function_data.get("name") or function_data.get("functionName")
        external_name = function_data.get("externalName") or function_data.get("external_name")
        if not function_name and external_name:
            function_name = external_name
        if not function_name:
            return None
        arg_count = GameMakerResourceIndex._extension_arg_count(function_data)
        return IndexedExtensionFunction(
            extension_name=extension_name,
            function_name=str(function_name),
            yy_path=yy_path,
            yyp_path=yyp_path,
            file_name=file_name,
            external_name=str(external_name or ""),
            arg_count=arg_count,
        )

    @staticmethod
    def _extension_arg_count(function_data: JsonDict) -> int | None:
        raw_arg_count = function_data.get("argCount")
        if raw_arg_count is None:
            raw_arg_count = function_data.get("argc")
        if raw_arg_count is not None and not isinstance(raw_arg_count, bool):
            try:
                return int(raw_arg_count)
            except (TypeError, ValueError):
                return None
        args = function_data.get("args")
        if isinstance(args, list):
            return len(cast(list[Any], args))
        return None

    def _parse_indexed_rooms(self) -> None:
        for name, resource in self.resources["rooms"].items():
            room = self._parse_room(resource)
            if room is not None:
                self.rooms[name] = room

    def _parse_room(self, resource: IndexedResource) -> IndexedRoom | None:
        data = self._read_yy_file(resource.yy_path)
        if data is None:
            self._safe_log(
                f"Skipping malformed GameMaker room {resource.name}: {resource.yy_path}"
            )
            return None

        return IndexedRoom(
            name=resource.name,
            yy_path=resource.yy_path,
            yyp_path=resource.yyp_path,
            godot_path=resource.godot_path,
            subfolder=resource.subfolder,
            room_settings=data.get("roomSettings") or {},
            physics_settings=data.get("physicsSettings") or {},
            view_settings=data.get("viewSettings") or {},
            views=data.get("views") or [],
            layers=data.get("layers") or [],
            instance_creation_order=data.get("instanceCreationOrder") or [],
            parent_room=data.get("parentRoom"),
            creation_code_file=data.get("creationCodeFile") or "",
            inherit_code=bool(data.get("inheritCode", False)),
            inherit_creation_order=bool(data.get("inheritCreationOrder", False)),
            inherit_layers=bool(data.get("inheritLayers", False)),
            is_dnd=bool(data.get("isDnd", False)),
            raw_data=data,
        )

    def _resolve_room_inheritance(self) -> None:
        resolved: dict[str, IndexedRoom] = {}

        def resolve(room_name: str, stack: list[str]) -> IndexedRoom:
            if room_name in resolved:
                return resolved[room_name]

            room = self.rooms[room_name]
            parent_name = self._room_reference_name(room.parent_room)
            if not parent_name:
                resolved[room_name] = room
                return room

            if parent_name in stack:
                self._safe_log(
                    "Warning: Room inheritance cycle detected: {cycle}; skipping inherited data for {room}.".format(
                        cycle=" -> ".join(stack + [parent_name]),
                        room=room_name,
                    )
                )
                resolved[room_name] = room
                return room

            parent = self.rooms.get(parent_name)
            if parent is None:
                self._safe_log(
                    "Warning: Missing parent room {parent} for room {room}; using child room data only.".format(
                        parent=parent_name,
                        room=room_name,
                    )
                )
                resolved[room_name] = room
                return room

            parent = resolve(parent_name, stack + [room_name])
            inherited_room = self._inherit_room(room, parent)
            resolved[room_name] = inherited_room
            return inherited_room

        for room_name in list(self.rooms):
            resolve(room_name, [])
        self.rooms = resolved

    def _inherit_room(self, child: IndexedRoom, parent: IndexedRoom) -> IndexedRoom:
        room_settings = self._inherit_settings(
            child.room_settings,
            parent.room_settings,
            "inheritRoomSettings",
        )
        physics_settings = self._inherit_settings(
            child.physics_settings,
            parent.physics_settings,
            "inheritPhysicsSettings",
        )
        inherit_views = bool(child.view_settings.get("inheritViewSettings", False))
        view_settings = self._inherit_settings(
            child.view_settings,
            parent.view_settings,
            "inheritViewSettings",
        )
        views = copy.deepcopy(parent.views if inherit_views else child.views)
        layers = (
            self._merge_layers(parent.layers, child.layers)
            if child.inherit_layers
            else copy.deepcopy(child.layers)
        )
        instance_creation_order = (
            self._merge_named_items(parent.instance_creation_order, child.instance_creation_order)
            if child.inherit_creation_order
            else copy.deepcopy(child.instance_creation_order)
        )
        creation_code_file = child.creation_code_file
        if child.inherit_code and not creation_code_file:
            creation_code_file = self._inherited_creation_code_file(parent)

        raw_data = copy.deepcopy(child.raw_data)
        raw_data["gm2godot_inherited_parent_room"] = parent.name
        return replace(
            child,
            room_settings=room_settings,
            physics_settings=physics_settings,
            view_settings=view_settings,
            views=views,
            layers=layers,
            instance_creation_order=instance_creation_order,
            creation_code_file=creation_code_file,
            raw_data=raw_data,
        )

    @staticmethod
    def _inherit_settings(child_settings: JsonDict, parent_settings: JsonDict, flag: str) -> JsonDict:
        if bool(child_settings.get(flag, False)):
            inherited = copy.deepcopy(parent_settings)
            inherited[flag] = True
            return inherited
        return copy.deepcopy(child_settings)

    def _merge_layers(self, parent_layers: JsonList, child_layers: JsonList) -> JsonList:
        merged = self._dict_items_copy(parent_layers)
        by_key = {self._item_key(layer): index for index, layer in enumerate(merged)}
        for child_layer in self._dict_items_copy(child_layers):
            key = self._item_key(child_layer)
            if key and key in by_key:
                parent_layer = merged[by_key[key]]
                merged[by_key[key]] = self._merge_layer(parent_layer, child_layer)
            else:
                merged.append(child_layer)
        return cast(JsonList, merged)

    def _merge_layer(self, parent_layer: JsonDict, child_layer: JsonDict) -> JsonDict:
        merged = copy.deepcopy(parent_layer)
        merged.update(copy.deepcopy(child_layer))

        if child_layer.get("inheritLayerDepth") is True and "depth" in parent_layer:
            merged["depth"] = copy.deepcopy(parent_layer["depth"])
        if child_layer.get("inheritVisibility") is True and "visible" in parent_layer:
            merged["visible"] = copy.deepcopy(parent_layer["visible"])
        if child_layer.get("inheritSubLayers") is True:
            merged["layers"] = self._merge_layers(
                cast(JsonList, parent_layer.get("layers") or []),
                cast(JsonList, child_layer.get("layers") or []),
            )
        if "instances" in parent_layer or "instances" in child_layer:
            merged["instances"] = self._merge_named_items(
                cast(JsonList, parent_layer.get("instances") or []),
                cast(JsonList, child_layer.get("instances") or []),
            )
        if "assets" in parent_layer or "assets" in child_layer:
            merged["assets"] = self._merge_named_items(
                cast(JsonList, parent_layer.get("assets") or []),
                cast(JsonList, child_layer.get("assets") or []),
            )
        return merged

    def _merge_named_items(self, parent_items: JsonList, child_items: JsonList) -> JsonList:
        merged = self._dict_items_copy(parent_items)
        by_key = {self._item_key(item): index for index, item in enumerate(merged)}
        for child_item in self._dict_items_copy(child_items):
            key = self._item_key(child_item)
            if key and key in by_key:
                parent_item = merged[by_key[key]]
                merged_item = copy.deepcopy(parent_item)
                merged_item.update(copy.deepcopy(child_item))
                merged[by_key[key]] = merged_item
            else:
                merged.append(child_item)
        return cast(JsonList, merged)

    def _inherited_creation_code_file(self, parent: IndexedRoom) -> str:
        if not parent.creation_code_file:
            return ""
        normalized = parent.creation_code_file.replace("\\", "/")
        if normalized.startswith("rooms/") or normalized.startswith("${project_dir}/"):
            return normalized
        if os.path.isabs(normalized):
            return normalized
        parent_dir = os.path.relpath(os.path.dirname(parent.yy_path), self.gm_project_path)
        return "/".join([parent_dir.replace(os.sep, "/"), normalized])

    @staticmethod
    def _room_reference_name(reference: JsonDict | None) -> str:
        if not isinstance(reference, dict):
            return ""
        name = reference.get("name")
        if isinstance(name, str) and name:
            return name
        path = reference.get("path")
        if isinstance(path, str) and path:
            return os.path.splitext(os.path.basename(path))[0]
        return ""

    @staticmethod
    def _dict_items_copy(value: JsonList) -> list[JsonDict]:
        return [copy.deepcopy(cast(JsonDict, item)) for item in value if isinstance(item, dict)]

    @staticmethod
    def _item_key(item: JsonDict) -> str:
        for key in ("inheritedItemId", "%Name", "name"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested_value = cast(JsonDict, value)
                name = nested_value.get("name")
                if isinstance(name, str) and name:
                    return name
        return ""

    def _apply_yyp_room_order(self, yyp_data: JsonDict) -> None:
        if "RoomOrderNodes" not in yyp_data:
            self.used_room_order_fallback = True
            self._safe_log(
                "Warning: RoomOrderNodes missing; using deterministic room order fallback."
            )
            self.room_order = sorted(self.rooms)
            return

        ordered: list[str] = []
        for room_node in yyp_data.get("RoomOrderNodes", []):
            room_id = room_node.get("roomId", {})
            name = room_id.get("name") or self._name_from_yyp_path(room_id.get("path", ""))
            if name in self.rooms and name not in ordered:
                ordered.append(name)

        for name in self.resources["rooms"]:
            if name in self.rooms and name not in ordered:
                ordered.append(name)

        self.room_order = ordered

    def _make_resource(
        self,
        kind: str,
        name: str,
        yy_path: str,
        yyp_path: str,
        resource_ref: ProjectResourceReference | None = None,
    ) -> IndexedResource:
        subfolder = self._get_subfolder_from_yy(yy_path)
        return IndexedResource(
            kind=kind,
            name=name,
            yy_path=yy_path,
            yyp_path=yyp_path,
            godot_path=self.godot_res_path(kind, name, subfolder),
            subfolder=subfolder,
            uuid=resource_ref.uuid if resource_ref is not None else "",
            resource_type=resource_ref.resource_type if resource_ref is not None else "",
            order=resource_ref.order if resource_ref is not None else 0,
            tags=resource_ref.tags if resource_ref is not None else (),
        )

    def _stabilize_resource_paths(self) -> None:
        used_paths: set[str] = set()
        for kind in self.RESOURCE_EXTENSIONS:
            resources = self.resources.get(kind, {})
            for name in sorted(resources):
                resource = resources[name]
                suffix_index = 0
                while True:
                    suffix = "" if suffix_index == 0 else f"_{suffix_index + 1}"
                    path = self.godot_res_path(kind, name, resource.subfolder, suffix=suffix)
                    folded_path = path.casefold()
                    if folded_path not in used_paths:
                        break
                    suffix_index += 1
                used_paths.add(folded_path)
                resources[name] = replace(resource, godot_path=path)

    @classmethod
    def godot_res_path(
        cls,
        kind: str,
        name: str,
        subfolder: str = "",
        *,
        suffix: str = "",
    ) -> str:
        """Build a generated res:// path using existing converter conventions."""
        extension = cls.RESOURCE_EXTENSIONS[kind]
        return generated_nested_resource_path(kind, subfolder, name, extension, suffix=suffix)

    @staticmethod
    def _kind_from_yyp_path(yyp_path: str) -> str:
        if not yyp_path or "/" not in yyp_path:
            return ""
        return yyp_path.split("/", 1)[0]

    @staticmethod
    def _name_from_yyp_path(yyp_path: str) -> str:
        if not yyp_path:
            return ""
        filename = os.path.basename(yyp_path)
        return os.path.splitext(filename)[0]
