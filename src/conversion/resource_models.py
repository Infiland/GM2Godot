from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from src.conversion.font_metadata import (
    GameMakerFontMetadata,
    parse_gamemaker_font_metadata,
)
from src.conversion.gamemaker_json import (
    decode_gamemaker_json,
    decode_gamemaker_json as decode_gamemaker_font_json,
    decode_gamemaker_json as decode_gamemaker_resource_json,
    decode_gamemaker_json as decode_gamemaker_sound_json,
    decode_gamemaker_json as decode_gamemaker_tileset_json,
)
from src.conversion.generated_paths import generated_subfolder_path
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.object_metadata import (
    GameMakerObjectMetadata,
    parse_gamemaker_object_metadata,
)
from src.conversion.path_metadata import (
    GameMakerPathMetadata,
    parse_gamemaker_path_metadata,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectResourceReference,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    resolve_project_filesystem_source_path,
    resolve_project_source_path,
    validate_project_resource_source_path,
)
from src.conversion.resource_parent_metadata import (
    parse_gamemaker_resource_parent_metadata,
)
from src.conversion.room_metadata import (
    capture_room_summary_settings,
    iter_room_layer_summary_fields,
    project_room_summary_fields,
)
from src.conversion.sequence_metadata import sequence_track_count
from src.conversion.sound_metadata import (
    GameMakerSoundMetadata,
    parse_gamemaker_sound_metadata,
)
from src.conversion.sprite_metadata import (
    GameMakerSpriteMetadata,
    parse_gamemaker_sprite_metadata,
)
from src.conversion.tileset_metadata import (
    GameMakerTilesetMetadata,
    parse_gamemaker_tileset_metadata,
)
from src.conversion.timeline_metadata import timeline_moment_count

ResourceModelSeverity = Literal["info", "warning", "error"]


def _empty_json_dict() -> JsonObject:
    return {}


@dataclass(frozen=True)
class ResourceModelDiagnostic:
    severity: ResourceModelSeverity
    code: str
    message: str
    source_path: str = ""
    resource_name: str = ""
    resource_kind: str = ""


@dataclass(frozen=True)
class ProjectModel:
    name: str
    yyp_path: str | None
    resource_type: str
    resource_version: str
    resource_count: int
    audio_group_names: tuple[str, ...] = ()
    texture_group_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceModel:
    name: str
    kind: str
    resource_type: str
    yy_path: str
    yyp_path: str
    order: int
    subfolder: str = ""
    raw_data: JsonObject = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class SpriteModel(ResourceModel):
    width: int = 0
    height: int = 0
    origin: int = 0
    metadata: GameMakerSpriteMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class SoundModel(ResourceModel):
    sound_file: str = ""
    audio_group: str = ""
    metadata: GameMakerSoundMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class FontModel(ResourceModel):
    font_name: str = ""
    size: float = 0.0
    metadata: GameMakerFontMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ObjectModel(ResourceModel):
    sprite_name: str | None = None
    parent_object_name: str | None = None
    event_count: int = 0
    persistent: bool = False
    solid: bool = False
    metadata: GameMakerObjectMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class RoomLayerModel:
    room_name: str
    name: str
    resource_type: str
    depth: int | None
    order: int
    raw_data: JsonObject = field(default_factory=_empty_json_dict)


@dataclass(frozen=True)
class RoomModel(ResourceModel):
    width: int = 0
    height: int = 0
    persistent: bool = False
    inherit_layers: bool = False
    parent_room_name: str | None = None
    layers: tuple[RoomLayerModel, ...] = ()


@dataclass(frozen=True)
class ScriptModel(ResourceModel):
    gml_path: str | None = None


@dataclass(frozen=True)
class ShaderModel(ResourceModel):
    vertex_path: str | None = None
    fragment_path: str | None = None


@dataclass(frozen=True)
class TileSetModel(ResourceModel):
    sprite_name: str | None = None
    tile_width: int = 0
    tile_height: int = 0
    metadata: GameMakerTilesetMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class PathModel(ResourceModel):
    point_count: int = 0
    closed: bool = False
    metadata: GameMakerPathMetadata | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class SequenceModel(ResourceModel):
    track_count: int = 0


@dataclass(frozen=True)
class TimelineModel(ResourceModel):
    moment_count: int = 0


@dataclass(frozen=True)
class GameMakerResourceModels:
    project: ProjectModel
    sprites: tuple[SpriteModel, ...] = ()
    sounds: tuple[SoundModel, ...] = ()
    fonts: tuple[FontModel, ...] = ()
    objects: tuple[ObjectModel, ...] = ()
    rooms: tuple[RoomModel, ...] = ()
    layers: tuple[RoomLayerModel, ...] = ()
    scripts: tuple[ScriptModel, ...] = ()
    shaders: tuple[ShaderModel, ...] = ()
    tilesets: tuple[TileSetModel, ...] = ()
    paths: tuple[PathModel, ...] = ()
    sequences: tuple[SequenceModel, ...] = ()
    timelines: tuple[TimelineModel, ...] = ()
    other_resources: tuple[ResourceModel, ...] = ()
    diagnostics: tuple[ResourceModelDiagnostic, ...] = ()


def _empty_sprite_models() -> list[SpriteModel]:
    return []


def _empty_sound_models() -> list[SoundModel]:
    return []


def _empty_font_models() -> list[FontModel]:
    return []


def _empty_object_models() -> list[ObjectModel]:
    return []


def _empty_room_models() -> list[RoomModel]:
    return []


def _empty_script_models() -> list[ScriptModel]:
    return []


def _empty_shader_models() -> list[ShaderModel]:
    return []


def _empty_tileset_models() -> list[TileSetModel]:
    return []


def _empty_path_models() -> list[PathModel]:
    return []


def _empty_sequence_models() -> list[SequenceModel]:
    return []


def _empty_timeline_models() -> list[TimelineModel]:
    return []


def _empty_resource_models() -> list[ResourceModel]:
    return []


def parse_gamemaker_resource_models(gm_project_path: str) -> GameMakerResourceModels:
    """Parse typed resource metadata without writing Godot output files."""
    manifest = load_gamemaker_project_manifest(gm_project_path)
    diagnostics = [
        ResourceModelDiagnostic(
            severity=diagnostic.severity,
            code=diagnostic.code,
            message=diagnostic.message,
            source_path=diagnostic.source.path if diagnostic.source is not None else "",
            resource_name=diagnostic.resource or "",
            resource_kind=diagnostic.resource_kind or "",
        )
        for diagnostic in manifest.diagnostics
    ]
    parsed = _ParsedResourceModelBuckets()

    for reference in manifest.resources:
        model, model_diagnostics = _parse_resource_model(gm_project_path, reference)
        diagnostics.extend(model_diagnostics)
        if model is not None:
            parsed.add(model)

    return GameMakerResourceModels(
        project=_project_model(manifest),
        sprites=tuple(parsed.sprites),
        sounds=tuple(parsed.sounds),
        fonts=tuple(parsed.fonts),
        objects=tuple(parsed.objects),
        rooms=tuple(parsed.rooms),
        layers=tuple(layer for room in parsed.rooms for layer in room.layers),
        scripts=tuple(parsed.scripts),
        shaders=tuple(parsed.shaders),
        tilesets=tuple(parsed.tilesets),
        paths=tuple(parsed.paths),
        sequences=tuple(parsed.sequences),
        timelines=tuple(parsed.timelines),
        other_resources=tuple(parsed.other_resources),
        diagnostics=tuple(diagnostics),
    )


@dataclass
class _ParsedResourceModelBuckets:
    sprites: list[SpriteModel] = field(default_factory=_empty_sprite_models)
    sounds: list[SoundModel] = field(default_factory=_empty_sound_models)
    fonts: list[FontModel] = field(default_factory=_empty_font_models)
    objects: list[ObjectModel] = field(default_factory=_empty_object_models)
    rooms: list[RoomModel] = field(default_factory=_empty_room_models)
    scripts: list[ScriptModel] = field(default_factory=_empty_script_models)
    shaders: list[ShaderModel] = field(default_factory=_empty_shader_models)
    tilesets: list[TileSetModel] = field(default_factory=_empty_tileset_models)
    paths: list[PathModel] = field(default_factory=_empty_path_models)
    sequences: list[SequenceModel] = field(default_factory=_empty_sequence_models)
    timelines: list[TimelineModel] = field(default_factory=_empty_timeline_models)
    other_resources: list[ResourceModel] = field(default_factory=_empty_resource_models)

    def add(self, model: ResourceModel) -> None:
        if isinstance(model, SpriteModel):
            self.sprites.append(model)
        elif isinstance(model, SoundModel):
            self.sounds.append(model)
        elif isinstance(model, FontModel):
            self.fonts.append(model)
        elif isinstance(model, ObjectModel):
            self.objects.append(model)
        elif isinstance(model, RoomModel):
            self.rooms.append(model)
        elif isinstance(model, ScriptModel):
            self.scripts.append(model)
        elif isinstance(model, ShaderModel):
            self.shaders.append(model)
        elif isinstance(model, TileSetModel):
            self.tilesets.append(model)
        elif isinstance(model, PathModel):
            self.paths.append(model)
        elif isinstance(model, SequenceModel):
            self.sequences.append(model)
        elif isinstance(model, TimelineModel):
            self.timelines.append(model)
        else:
            self.other_resources.append(model)


def _project_model(manifest: GameMakerProjectManifest) -> ProjectModel:
    return ProjectModel(
        name=manifest.project_name,
        yyp_path=manifest.yyp_path,
        resource_type=manifest.resource_type,
        resource_version=manifest.resource_version,
        resource_count=len(manifest.resources),
        audio_group_names=tuple(group.name for group in manifest.audio_groups if group.name),
        texture_group_names=tuple(group.name for group in manifest.texture_groups if group.name),
    )


def _parse_resource_model(
    gm_project_path: str,
    reference: ProjectResourceReference,
) -> tuple[ResourceModel | None, tuple[ResourceModelDiagnostic, ...]]:
    try:
        resolved_yy = resolve_project_source_path(
            gm_project_path,
            reference.path,
        )
        validate_project_resource_source_path(
            resolved_yy,
            reference.kind,
        )
    except ProjectSourcePathError as exc:
        return None, (
            _source_path_diagnostic(
                reference,
                reference.path,
                exc,
            ),
        )
    yy_path = resolved_yy.filesystem_path
    if reference.kind == "paths":
        return _parse_path_resource_model(reference, yy_path, resolved_yy.source_path)
    if reference.kind == "fonts":
        return _parse_font_resource_model(reference, yy_path, resolved_yy.source_path)
    if reference.kind == "sounds":
        return _parse_sound_resource_model(reference, yy_path, resolved_yy.source_path)
    if reference.kind == "tilesets":
        return _parse_tileset_resource_model(reference, yy_path, resolved_yy.source_path)
    raw_data = _read_lenient_json_file(yy_path)
    if raw_data is None:
        return None, (
            ResourceModelDiagnostic(
                severity="warning",
                code="GM2GD-RESOURCE-YY-MISSING",
                message=f"Could not parse GameMaker resource .yy: {yy_path}",
                source_path=yy_path,
                resource_name=reference.name,
                resource_kind=reference.kind,
            ),
        )

    base = _base_kwargs(
        reference,
        yy_path,
        resolved_yy.source_path,
        raw_data,
    )
    kind = reference.kind
    if kind == "sprites":
        metadata = parse_gamemaker_sprite_metadata(raw_data, source_context=yy_path)
        return SpriteModel(
            **base,
            width=metadata.width,
            height=metadata.height,
            origin=metadata.origin,
            metadata=metadata,
        ), ()
    if kind == "objects":
        metadata = parse_gamemaker_object_metadata(raw_data, source_context=yy_path)
        return ObjectModel(
            **base,
            sprite_name=metadata.sprite_name,
            parent_object_name=metadata.parent_object_name,
            event_count=metadata.event_count,
            persistent=metadata.persistent,
            solid=metadata.solid,
            metadata=metadata,
        ), ()
    if kind == "rooms":
        room_settings = capture_room_summary_settings(raw_data, source_context=yy_path)
        layers = _parse_room_layers(reference.name, raw_data.get("layers"))
        fields = project_room_summary_fields(raw_data, room_settings, source_context=yy_path)
        return RoomModel(
            **base,
            width=fields.width,
            height=fields.height,
            persistent=fields.persistent,
            inherit_layers=fields.inherit_layers,
            parent_room_name=fields.parent_room_name,
            layers=layers,
        ), ()
    if kind == "scripts":
        gml_path, diagnostics = _first_existing_neighbor(
            gm_project_path,
            yy_path,
            ".gml",
            reference,
        )
        return ScriptModel(
            **base,
            gml_path=gml_path,
        ), diagnostics
    if kind == "shaders":
        vertex_path, vertex_diagnostics = _first_existing_neighbor(
            gm_project_path,
            yy_path,
            ".vsh",
            reference,
        )
        fragment_path, fragment_diagnostics = _first_existing_neighbor(
            gm_project_path,
            yy_path,
            ".fsh",
            reference,
        )
        return ShaderModel(
            **base,
            vertex_path=vertex_path,
            fragment_path=fragment_path,
        ), vertex_diagnostics + fragment_diagnostics
    if kind == "sequences":
        return SequenceModel(
            **base,
            track_count=sequence_track_count(raw_data),
        ), ()
    if kind == "timelines":
        return TimelineModel(
            **base,
            moment_count=timeline_moment_count(raw_data),
        ), ()
    return ResourceModel(**base), ()


def _parse_tileset_resource_model(
    reference: ProjectResourceReference,
    yy_path: str,
    source_path: str,
) -> tuple[TileSetModel | None, tuple[ResourceModelDiagnostic, ...]]:
    raw_data = _read_tileset_json_file(yy_path)
    if raw_data is None:
        return None, (
            ResourceModelDiagnostic(
                severity="warning",
                code="GM2GD-RESOURCE-YY-MISSING",
                message=f"Could not parse GameMaker resource .yy: {yy_path}",
                source_path=yy_path,
                resource_name=reference.name,
                resource_kind=reference.kind,
            ),
        )
    metadata = parse_gamemaker_tileset_metadata(raw_data, source_context=yy_path)
    return TileSetModel(
        name=reference.name,
        kind=reference.kind,
        resource_type=reference.resource_type,
        yy_path=yy_path,
        yyp_path=source_path,
        order=reference.order,
        subfolder=_tileset_subfolder(metadata.parent_path),
        raw_data=metadata.raw_data,
        sprite_name=metadata.sprite_name,
        tile_width=metadata.tile_width,
        tile_height=metadata.tile_height,
        metadata=metadata,
    ), ()


def _read_tileset_json_file(path: str) -> JsonObject | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = decode_gamemaker_tileset_json(source, source_path=path).value
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _tileset_subfolder(parent_path: str) -> str:
    if parent_path.startswith("folders/"):
        parent_path = parent_path[len("folders/"):]
    if parent_path.endswith(".yy"):
        parent_path = parent_path[:-len(".yy")]
    parts = parent_path.split("/")
    if len(parts) <= 1:
        return ""
    return generated_subfolder_path("/".join(parts[1:]))


def _parse_sound_resource_model(
    reference: ProjectResourceReference,
    yy_path: str,
    source_path: str,
) -> tuple[SoundModel | None, tuple[ResourceModelDiagnostic, ...]]:
    raw_data = _read_sound_json_file(yy_path)
    if raw_data is None:
        return None, (
            ResourceModelDiagnostic(
                severity="warning",
                code="GM2GD-RESOURCE-YY-MISSING",
                message=f"Could not parse GameMaker resource .yy: {yy_path}",
                source_path=yy_path,
                resource_name=reference.name,
                resource_kind=reference.kind,
            ),
        )
    metadata = parse_gamemaker_sound_metadata(raw_data, source_context=yy_path)
    return SoundModel(
        name=reference.name,
        kind=reference.kind,
        resource_type=reference.resource_type,
        yy_path=yy_path,
        yyp_path=source_path,
        order=reference.order,
        subfolder=_sound_subfolder(metadata.parent_path),
        raw_data=metadata.raw_data,
        sound_file=metadata.sound_file,
        audio_group=metadata.audio_group,
        metadata=metadata,
    ), ()


def _read_sound_json_file(path: str) -> JsonObject | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = decode_gamemaker_sound_json(source, source_path=path).value
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _sound_subfolder(parent_path: str) -> str:
    if parent_path.startswith("folders/"):
        parent_path = parent_path[len("folders/"):]
    if parent_path.endswith(".yy"):
        parent_path = parent_path[:-len(".yy")]
    parts = parent_path.split("/")
    if len(parts) <= 1:
        return ""
    return generated_subfolder_path("/".join(parts[1:]))


def _parse_font_resource_model(
    reference: ProjectResourceReference,
    yy_path: str,
    source_path: str,
) -> tuple[FontModel | None, tuple[ResourceModelDiagnostic, ...]]:
    raw_data = _read_font_json_file(yy_path)
    if raw_data is None:
        return None, (
            ResourceModelDiagnostic(
                severity="warning",
                code="GM2GD-RESOURCE-YY-MISSING",
                message=f"Could not parse GameMaker resource .yy: {yy_path}",
                source_path=yy_path,
                resource_name=reference.name,
                resource_kind=reference.kind,
            ),
        )
    metadata = parse_gamemaker_font_metadata(raw_data, source_context=yy_path)
    return FontModel(
        name=reference.name,
        kind=reference.kind,
        resource_type=reference.resource_type,
        yy_path=yy_path,
        yyp_path=source_path,
        order=reference.order,
        subfolder=_font_subfolder(metadata.parent_path),
        raw_data=metadata.raw_data,
        font_name=metadata.font_name,
        size=float(metadata.size_number),
        metadata=metadata,
    ), ()


def _read_font_json_file(path: str) -> JsonObject | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = decode_gamemaker_font_json(source, source_path=path).value
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _font_subfolder(parent_path: str) -> str:
    if parent_path.startswith("folders/"):
        parent_path = parent_path[len("folders/"):]
    if parent_path.endswith(".yy"):
        parent_path = parent_path[:-len(".yy")]
    parts = parent_path.split("/")
    if len(parts) <= 1:
        return ""
    return generated_subfolder_path("/".join(parts[1:]))


def _parse_path_resource_model(
    reference: ProjectResourceReference,
    yy_path: str,
    source_path: str,
) -> tuple[PathModel | None, tuple[ResourceModelDiagnostic, ...]]:
    raw_data = _read_path_json_file(yy_path)
    if raw_data is None:
        return None, (
            ResourceModelDiagnostic(
                severity="warning",
                code="GM2GD-RESOURCE-YY-MISSING",
                message=f"Could not parse GameMaker resource .yy: {yy_path}",
                source_path=yy_path,
                resource_name=reference.name,
                resource_kind=reference.kind,
            ),
        )
    metadata = parse_gamemaker_path_metadata(raw_data, source_path=yy_path)
    return PathModel(
        name=reference.name,
        kind=reference.kind,
        resource_type=reference.resource_type,
        yy_path=yy_path,
        yyp_path=source_path,
        order=reference.order,
        subfolder=_path_subfolder(metadata.parent_path),
        raw_data=metadata.raw_data,
        point_count=len(metadata.points),
        closed=metadata.closed,
        metadata=metadata,
    ), ()


def _read_path_json_file(path: str) -> JsonObject | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = decode_gamemaker_json(source, source_path=path).value
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _path_subfolder(parent_path: str) -> str:
    if parent_path.startswith("folders/"):
        parent_path = parent_path[len("folders/"):]
    if parent_path.endswith(".yy"):
        parent_path = parent_path[:-len(".yy")]
    parts = parent_path.split("/")
    if len(parts) <= 1:
        return ""
    return generated_subfolder_path("/".join(parts[1:]))


class _ResourceModelConstructor(TypedDict):
    name: str
    kind: str
    resource_type: str
    yy_path: str
    yyp_path: str
    order: int
    subfolder: str
    raw_data: JsonObject


def _base_kwargs(
    reference: ProjectResourceReference,
    yy_path: str,
    yyp_path: str,
    raw_data: JsonObject,
) -> _ResourceModelConstructor:
    return {
        "name": reference.name,
        "kind": reference.kind,
        "resource_type": reference.resource_type,
        "yy_path": yy_path,
        "yyp_path": yyp_path,
        "order": reference.order,
        "subfolder": _subfolder_from_raw_data(raw_data),
        "raw_data": raw_data,
    }


def _read_lenient_json_file(path: str) -> JsonObject | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        data = decode_gamemaker_resource_json(source, source_path=path).value
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _subfolder_from_raw_data(raw_data: JsonObject) -> str:
    metadata = parse_gamemaker_resource_parent_metadata(raw_data)
    if not metadata.has_parent_path:
        return ""
    parent_path = metadata.parent_path
    if parent_path.startswith("folders/"):
        parent_path = parent_path[len("folders/"):]
    if parent_path.endswith(".yy"):
        parent_path = parent_path[:-len(".yy")]
    parts = parent_path.split("/")
    if len(parts) <= 1:
        return ""
    return generated_subfolder_path("/".join(parts[1:]))


def _parse_room_layers(room_name: str, raw_layers: JsonValue) -> tuple[RoomLayerModel, ...]:
    return tuple(
        RoomLayerModel(
            room_name=room_name,
            name=fields.name,
            resource_type=fields.resource_type,
            depth=fields.depth,
            order=fields.order,
            raw_data=fields.raw_data,
        )
        for fields in iter_room_layer_summary_fields(raw_layers, source_context=room_name)
    )


def _first_existing_neighbor(
    gm_project_path: str,
    yy_path: str,
    extension: str,
    reference: ProjectResourceReference,
) -> tuple[str | None, tuple[ResourceModelDiagnostic, ...]]:
    directory = os.path.dirname(yy_path)
    if not os.path.isdir(directory):
        return None, ()
    preferred = os.path.splitext(yy_path)[0] + extension
    try:
        fallback_names = sorted(os.listdir(directory))
    except OSError:
        return None, ()
    candidates = [preferred]
    candidates.extend(
        os.path.join(directory, name)
        for name in fallback_names
        if name.lower().endswith(extension)
    )
    diagnostics: list[ResourceModelDiagnostic] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        candidate_key = os.path.normcase(os.path.abspath(candidate))
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)
        try:
            resolved_candidate = resolve_project_filesystem_source_path(
                gm_project_path,
                candidate,
            )
        except ProjectSourcePathError as exc:
            if os.path.lexists(candidate):
                diagnostics.append(
                    _source_path_diagnostic(reference, candidate, exc)
                )
            continue
        if os.path.isfile(resolved_candidate.filesystem_path):
            return resolved_candidate.filesystem_path, tuple(diagnostics)
    return None, tuple(diagnostics)


def _source_path_diagnostic(
    reference: ProjectResourceReference,
    rejected_path: str,
    error: ProjectSourcePathError,
) -> ResourceModelDiagnostic:
    owner_path = (
        reference.source.path
        if reference.source is not None
        else reference.path
    )
    return ResourceModelDiagnostic(
        severity="warning",
        code="GM2GD-SOURCE-PATH-REJECTED",
        message=(
            "Rejected GameMaker source path "
            f"{rejected_path!r} declared by {owner_path}: {error}"
        ),
        source_path=owner_path,
        resource_name=reference.name,
        resource_kind=reference.kind,
    )
