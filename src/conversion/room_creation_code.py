from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, cast

from src.conversion.type_defs import JsonDict, JsonList, LogCallback


class RoomCreationCodeRoom(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def yy_path(self) -> str: ...

    @property
    def creation_code_file(self) -> str: ...

    @property
    def inherit_code(self) -> bool: ...

    @property
    def instance_creation_order(self) -> JsonList: ...


ROOM_EXECUTION_ORDER = [
    "object_create",
    "instance_creation_code",
    "room_creation_code",
    "room_start",
]


@dataclass(frozen=True)
class CreationCodeMetadata:
    has_code: bool
    inherit_code: bool
    is_dnd: bool
    source_path: str
    exists: bool
    execution_phase: str
    execution_phase_index: int


def resolve_room_creation_code(
    room: RoomCreationCodeRoom,
    gm_project_path: str,
    warn_callback: LogCallback | None = None,
) -> CreationCodeMetadata:
    """Resolve room creation-code metadata without transpiling GML."""
    source_file = room.creation_code_file or ""
    source_path = _resolve_room_creation_code_path(room, gm_project_path, source_file)
    metadata = CreationCodeMetadata(
        has_code=bool(source_file),
        inherit_code=bool(room.inherit_code),
        is_dnd=bool(getattr(room, "is_dnd", False)),
        source_path=source_path,
        exists=bool(source_path and os.path.isfile(source_path)),
        execution_phase="room_creation_code",
        execution_phase_index=ROOM_EXECUTION_ORDER.index("room_creation_code"),
    )

    if metadata.has_code and not metadata.exists and warn_callback is not None:
        warn_callback(
            "Warning: Missing GameMaker room creation code file for room {room}: {path}".format(
                room=room.name,
                path=metadata.source_path,
            )
        )

    return metadata


def resolve_instance_creation_code(
    room: RoomCreationCodeRoom,
    instance: JsonDict,
    warn_callback: LogCallback | None = None,
) -> CreationCodeMetadata:
    """Resolve per-instance creation-code metadata without transpiling GML."""
    instance_name = _instance_name(instance)
    has_code = bool(instance.get("hasCreationCode", False))
    source_path = ""
    if has_code:
        source_path = os.path.join(
            os.path.dirname(room.yy_path),
            f"InstanceCreationCode_{instance_name}.gml",
        )

    metadata = CreationCodeMetadata(
        has_code=has_code,
        inherit_code=bool(instance.get("inheritCode", False)),
        is_dnd=bool(instance.get("isDnd", False)),
        source_path=source_path,
        exists=bool(source_path and os.path.isfile(source_path)),
        execution_phase="instance_creation_code",
        execution_phase_index=ROOM_EXECUTION_ORDER.index("instance_creation_code"),
    )

    if metadata.has_code and not metadata.exists and warn_callback is not None:
        warn_callback(
            "Warning: Missing GameMaker instance creation code file for room {room}, "
            "instance {instance}: {path}".format(
                room=room.name,
                instance=instance_name,
                path=metadata.source_path,
            )
        )

    return metadata


def instance_creation_order_names(room: RoomCreationCodeRoom) -> list[str]:
    names: list[str] = []
    for entry in room.instance_creation_order:
        if isinstance(entry, dict):
            entry_dict = cast(JsonDict, entry)
            name = entry_dict.get("%Name") or entry_dict.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _resolve_room_creation_code_path(
    room: RoomCreationCodeRoom,
    gm_project_path: str,
    source_file: str,
) -> str:
    if not source_file:
        return ""

    normalized = source_file.replace("\\", "/")
    if normalized.startswith("${project_dir}/"):
        normalized = normalized[len("${project_dir}/"):]

    if os.path.isabs(normalized):
        return os.path.normpath(normalized)

    if normalized.startswith("rooms/"):
        return os.path.normpath(os.path.join(gm_project_path, normalized))

    return os.path.normpath(os.path.join(os.path.dirname(room.yy_path), normalized))


def _instance_name(instance: JsonDict) -> str:
    name = instance.get("%Name") or instance.get("name")
    return name if isinstance(name, str) and name else "Instance"
