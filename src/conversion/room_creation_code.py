from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, cast

from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    is_safe_project_source_component,
    resolve_project_sidecar_source_path,
)
from src.conversion.type_defs import JsonDict, JsonList, LogCallback


CreationCodeSourceResolver = Callable[[str, str], str | None]

_INSTANCE_CREATION_CODE_PREFIX = "InstanceCreationCode_"
_INSTANCE_CREATION_CODE_SUFFIX = ".gml"
_INSTANCE_CREATION_CODE_FIELD = "layers[].instances[].name"


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
    "game_start",
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
    path_rejected: bool = False


def resolve_room_creation_code(
    room: RoomCreationCodeRoom,
    gm_project_path: str,
    warn_callback: LogCallback | None = None,
    *,
    source_resolver: CreationCodeSourceResolver | None = None,
) -> CreationCodeMetadata:
    """Resolve room creation-code metadata without transpiling GML."""
    source_file = room.creation_code_file or ""
    source_path, path_rejected = _resolve_creation_code_path(
        room,
        gm_project_path,
        source_file,
        field="creationCodeFile",
        source_resolver=source_resolver,
        warn_callback=warn_callback,
    )
    metadata = CreationCodeMetadata(
        has_code=bool(source_file),
        inherit_code=bool(room.inherit_code),
        is_dnd=bool(getattr(room, "is_dnd", False)),
        source_path=source_path,
        exists=bool(source_path and os.path.isfile(source_path)),
        execution_phase="room_creation_code",
        execution_phase_index=ROOM_EXECUTION_ORDER.index("room_creation_code"),
        path_rejected=path_rejected,
    )

    if (
        metadata.has_code
        and not metadata.exists
        and not metadata.path_rejected
        and warn_callback is not None
    ):
        warn_callback(
            "Info: Missing GameMaker room creation code file for room {room}: {path}".format(
                room=room.name,
                path=metadata.source_path,
            )
        )

    return metadata


def resolve_instance_creation_code(
    room: RoomCreationCodeRoom,
    instance: JsonDict,
    warn_callback: LogCallback | None = None,
    *,
    gm_project_path: str | None = None,
    source_resolver: CreationCodeSourceResolver | None = None,
) -> CreationCodeMetadata:
    """Resolve per-instance creation-code metadata without transpiling GML."""
    instance_name = _instance_name(instance)
    has_code = bool(instance.get("hasCreationCode", False))
    source_path = ""
    path_rejected = False
    if has_code:
        source_file = (
            f"{_INSTANCE_CREATION_CODE_PREFIX}{instance_name}"
            f"{_INSTANCE_CREATION_CODE_SUFFIX}"
        )
        if not is_safe_project_source_component(instance_name):
            error = ProjectSourcePathError(
                "GameMaker instance names used to derive creation-code "
                "filenames must be exactly one safe path component: "
                f"{instance_name!r}"
            )
            if source_resolver is not None:
                # Let converter-owned resolvers attach the rejection to the
                # declaring room and metadata field. The result is deliberately
                # ignored: an unsafe derived component can never be accepted.
                source_resolver(source_file, _INSTANCE_CREATION_CODE_FIELD)
            else:
                _warn_source_path_rejection(
                    room,
                    source_file,
                    field=_INSTANCE_CREATION_CODE_FIELD,
                    error=error,
                    warn_callback=warn_callback,
                )
            path_rejected = True
        else:
            source_path, path_rejected = _resolve_creation_code_path(
                room,
                gm_project_path,
                source_file,
                field=_INSTANCE_CREATION_CODE_FIELD,
                source_resolver=source_resolver,
                warn_callback=warn_callback,
            )

    metadata = CreationCodeMetadata(
        has_code=has_code,
        inherit_code=bool(instance.get("inheritCode", False)),
        is_dnd=bool(instance.get("isDnd", False)),
        source_path=source_path,
        exists=bool(source_path and os.path.isfile(source_path)),
        execution_phase="instance_creation_code",
        execution_phase_index=ROOM_EXECUTION_ORDER.index("instance_creation_code"),
        path_rejected=path_rejected,
    )

    if (
        metadata.has_code
        and not metadata.exists
        and not metadata.path_rejected
        and warn_callback is not None
    ):
        warn_callback(
            "Info: Missing GameMaker instance creation code file for room {room}, "
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


def _resolve_creation_code_path(
    room: RoomCreationCodeRoom,
    gm_project_path: str | None,
    source_file: str,
    *,
    field: str,
    source_resolver: CreationCodeSourceResolver | None,
    warn_callback: LogCallback | None,
) -> tuple[str, bool]:
    if not source_file:
        return "", False

    if source_resolver is not None:
        source_path = source_resolver(source_file, field)
        return (source_path or ""), source_path is None

    if gm_project_path is None:
        gm_project_path = _infer_project_root_from_room_yy_path(room.yy_path)
        if gm_project_path is None:
            _warn_source_path_rejection(
                room,
                source_file,
                field=field,
                error=ProjectSourcePathError(
                    "GameMaker project root cannot be safely inferred from "
                    "the room .yy path; provide an absolute .yy path with one "
                    "unambiguous rooms path component or pass gm_project_path"
                ),
                warn_callback=warn_callback,
            )
            return "", True

    try:
        resolved = resolve_project_sidecar_source_path(
            gm_project_path,
            room.yy_path,
            source_file,
        )
    except ProjectSourcePathError as error:
        _warn_source_path_rejection(
            room,
            source_file,
            field=field,
            error=error,
            warn_callback=warn_callback,
        )
        return "", True
    return resolved.filesystem_path, False


def _infer_project_root_from_room_yy_path(room_yy_path: str) -> str | None:
    """Infer a project root only from an unambiguous absolute room owner."""
    normalized_path = Path(os.path.normpath(room_yy_path))
    if (
        not normalized_path.is_absolute()
        or normalized_path.suffix.casefold() != ".yy"
    ):
        return None

    room_component_indexes = [
        index
        for index, component in enumerate(normalized_path.parts[:-1])
        if component.casefold() == "rooms"
    ]
    if len(room_component_indexes) != 1:
        return None
    project_root = Path(*normalized_path.parts[:room_component_indexes[0]])
    if project_root == Path(normalized_path.anchor):
        return None
    return str(project_root)


def _warn_source_path_rejection(
    room: RoomCreationCodeRoom,
    source_file: str,
    *,
    field: str,
    error: ProjectSourcePathError,
    warn_callback: LogCallback | None,
) -> None:
    if warn_callback is None:
        return
    warn_callback(
        "Warning: Rejected GameMaker source path {path!r} from {owner} "
        "field {field}: {error}".format(
            path=source_file,
            owner=room.yy_path,
            field=field,
            error=error,
        )
    )


def _instance_name(instance: JsonDict) -> str:
    name = instance.get("%Name") or instance.get("name")
    return name if isinstance(name, str) and name else "Instance"
