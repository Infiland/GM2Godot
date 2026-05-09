import os
from dataclasses import dataclass, field
from typing import ClassVar, cast

from src.conversion.base_converter import BaseConverter
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
        self.resources: dict[str, dict[str, IndexedResource]] = self._empty_resources()
        self.rooms: dict[str, IndexedRoom] = {}
        self.room_order: list[str] = []
        self.used_room_order_fallback = False

    def convert_all(self) -> "GameMakerResourceIndex":
        """Build the in-memory index. No Godot files are written."""
        return self.build()

    def build(self) -> "GameMakerResourceIndex":
        """Build and return this resource index."""
        self.resources = self._empty_resources()
        self.rooms = {}
        self.room_order = []
        self.used_room_order_fallback = False
        self.yyp_path = self.find_yyp_path()
        self.yyp_data = self._read_yy_file(self.yyp_path) if self.yyp_path else None

        if self.yyp_data is not None:
            self._index_yyp_resources(self.yyp_data)
            self._parse_indexed_rooms()
            self._apply_yyp_room_order(self.yyp_data)
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
            self._parse_indexed_rooms()
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

    def _empty_resources(self) -> dict[str, dict[str, IndexedResource]]:
        return {kind: {} for kind in self.RESOURCE_EXTENSIONS}

    def _index_yyp_resources(self, yyp_data: JsonDict) -> None:
        for resource_entry in yyp_data.get("resources", []):
            res_id = resource_entry.get("id", {})
            yyp_path = res_id.get("path", "")
            kind = self._kind_from_yyp_path(yyp_path)
            if kind not in self.RESOURCE_EXTENSIONS:
                continue

            name = res_id.get("name") or self._name_from_yyp_path(yyp_path)
            if not name:
                continue

            yy_path = os.path.normpath(os.path.join(self.gm_project_path, yyp_path))
            if not os.path.isfile(yy_path):
                self._safe_log(
                    f"Skipping missing GameMaker resource {name}: {yy_path}"
                )
                continue

            self.resources[kind][name] = self._make_resource(kind, name, yy_path, yyp_path)

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
        self, kind: str, name: str, yy_path: str, yyp_path: str
    ) -> IndexedResource:
        subfolder = self._get_subfolder_from_yy(yy_path)
        return IndexedResource(
            kind=kind,
            name=name,
            yy_path=yy_path,
            yyp_path=yyp_path,
            godot_path=self.godot_res_path(kind, name, subfolder),
            subfolder=subfolder,
        )

    @classmethod
    def godot_res_path(cls, kind: str, name: str, subfolder: str = "") -> str:
        """Build a generated res:// path using existing converter conventions."""
        extension = cls.RESOURCE_EXTENSIONS[kind]
        path_parts = ["res:/", kind]
        if subfolder:
            path_parts.extend(part for part in subfolder.split("/") if part)
        path_parts.extend([name, name + extension])
        return "/".join(path_parts)

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
