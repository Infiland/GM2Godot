from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, TypeAlias, cast

from src.conversion.anchored_artifacts import (
    ArtifactReceipt,
    ArtifactSnapshot,
    ArtifactSpec,
    ByteArtifactTransaction,
    artifact_sha256,
)
from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.runtime_managers import runtime_manager_definitions
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    resolve_project_filesystem_source_path,
)
from src.conversion.type_defs import JsonDict

ARCHITECTURE_POLICY_RELATIVE_PATH = os.path.join("gm2godot", "architecture_policy.json")
ARCHITECTURE_POLICY_VERSION = 1
_ARCHITECTURE_POLICY_DIRECTORY = os.path.dirname(ARCHITECTURE_POLICY_RELATIVE_PATH)
_ARCHITECTURE_POLICY_FILENAME = os.path.basename(ARCHITECTURE_POLICY_RELATIVE_PATH)

ROOM_ROOT_POLICY_ID = "gm_room_node2d"
LAYER_HIERARCHY_POLICY_ID = "gm_layer_depth_node2d"
GUI_LAYER_POLICY_ID = "gm_gui_canvas_layer"
DEPTH_MAPPING_POLICY_ID = "gamemaker_depth_to_negative_z_index"

GODOT_ARCHITECTURE_SOURCES: dict[str, str] = {
    "autoload": "https://docs.godotengine.org/en/stable/getting_started/step_by_step/singletons_autoload.html",
    "canvas_layer": "https://docs.godotengine.org/en/stable/tutorials/2d/canvas_layers.html",
    "physics_2d": "https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html",
    "collision_shape_2d": "https://docs.godotengine.org/en/4.7/classes/class_collisionshape2d.html",
    "transform_2d": "https://docs.godotengine.org/en/4.7/classes/class_transform2d.html",
    "audio_server": "https://docs.godotengine.org/en/stable/classes/class_audioserver.html",
    "http_request": "https://docs.godotengine.org/en/stable/classes/class_httprequest.html",
    "game_maker_event_order": "https://manual.gamemaker.io/lts/en/The_Asset_Editors/Object_Properties/Event_Order.htm",
    "game_maker_sprite_masks": "https://manual.gamemaker.io/lts/en/The_Asset_Editors/Sprites.htm",
}

_DRAW_RE = re.compile(r"\b(draw_|shader_|gpu_|font_|sprite_)", re.IGNORECASE)
_SURFACE_RE = re.compile(r"\b(surface_|application_surface)", re.IGNORECASE)
_COLLISION_RE = re.compile(r"\b(collision_|place_meeting|position_meeting|instance_place|instance_position)", re.IGNORECASE)
_PRECISE_COLLISION_RE = re.compile(r"\bcollision_[A-Za-z0-9_]*\s*\([^;]*,\s*true\s*,", re.IGNORECASE)
_PRECISE_SPRITE_KIND_RE = re.compile(r'"collisionKind"\s*:\s*(?:0|4)\b')
_AUDIO_RE = re.compile(r"\b(audio_|sound_)", re.IGNORECASE)
_NETWORK_RE = re.compile(r"\b(network_|http_|url_open|steam_ugc_download)", re.IGNORECASE)
_BUFFER_FILE_RE = re.compile(r"\b(buffer_|file_|ini_|json_)", re.IGNORECASE)

FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
ReceiptFingerprint: TypeAlias = tuple[int, int, int, int]


@dataclass(frozen=True)
class ArchitecturePolicySnapshot:
    """Exact architecture-policy state captured before publication."""

    content: bytes | None
    mode: int | None
    fingerprint: FileFingerprint | None
    sha256: str | None

    @property
    def present(self) -> bool:
        return self.fingerprint is not None


@dataclass(frozen=True)
class ArchitecturePolicyPublicationReceipt:
    """Identity and content committed by one report publication."""

    path: str
    content: bytes
    mode: int
    fingerprint: ReceiptFingerprint
    sha256: str


@dataclass(frozen=True)
class ArchitectureFeatures:
    room_count: int = 0
    has_views: bool = False
    has_multiple_visible_views: bool = False
    has_instance_layers: bool = False
    has_tile_layers: bool = False
    has_background_layers: bool = False
    has_scrolling_or_tiled_backgrounds: bool = False
    has_effect_layers: bool = False
    has_physics_world: bool = False
    has_draw_code: bool = False
    has_surface_code: bool = False
    has_collision_code: bool = False
    has_precise_collision_request: bool = False
    has_audio_code: bool = False
    has_sound_assets: bool = False
    has_network_code: bool = False
    has_buffer_file_code: bool = False

    def to_dict(self) -> JsonDict:
        return {
            "room_count": self.room_count,
            "has_views": self.has_views,
            "has_multiple_visible_views": self.has_multiple_visible_views,
            "has_instance_layers": self.has_instance_layers,
            "has_tile_layers": self.has_tile_layers,
            "has_background_layers": self.has_background_layers,
            "has_scrolling_or_tiled_backgrounds": self.has_scrolling_or_tiled_backgrounds,
            "has_effect_layers": self.has_effect_layers,
            "has_physics_world": self.has_physics_world,
            "has_draw_code": self.has_draw_code,
            "has_surface_code": self.has_surface_code,
            "has_collision_code": self.has_collision_code,
            "has_precise_collision_request": self.has_precise_collision_request,
            "has_audio_code": self.has_audio_code,
            "has_sound_assets": self.has_sound_assets,
            "has_network_code": self.has_network_code,
            "has_buffer_file_code": self.has_buffer_file_code,
        }


def write_architecture_policy_report(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> str:
    """Atomically publish the architecture-policy report and return its path."""
    return publish_architecture_policy_report(
        gm_project_path,
        godot_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
    ).path


def publish_architecture_policy_report(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> ArchitecturePolicyPublicationReceipt:
    """Atomically publish a report and return its exact committed receipt."""
    report = build_architecture_policy_report(
        gm_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
    )
    content = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path = os.path.join(godot_project_path, ARCHITECTURE_POLICY_RELATIVE_PATH)
    with ByteArtifactTransaction.open(
        godot_project_path,
        _ARCHITECTURE_POLICY_DIRECTORY,
        create=True,
        description="architecture-policy report directory",
    ) as transaction:
        receipts = transaction.publish_specs(
            (ArtifactSpec(_ARCHITECTURE_POLICY_FILENAME, content),)
        )
        core_receipt = receipts[0]
        if core_receipt is None:
            raise OSError("Architecture-policy publication produced no receipt.")
        return _architecture_receipt(core_receipt, path=report_path)


def capture_architecture_policy_snapshot(
    godot_project_path: str,
) -> ArchitecturePolicySnapshot:
    """Capture exact report bytes, mode, and fingerprint without following links."""
    with ByteArtifactTransaction.open(
        godot_project_path,
        _ARCHITECTURE_POLICY_DIRECTORY,
        create=False,
        description="architecture-policy report directory",
    ) as transaction:
        if not transaction.available:
            transaction.verify_directory()
            return ArchitecturePolicySnapshot(
                content=None,
                mode=None,
                fingerprint=None,
                sha256=None,
            )
        return _architecture_snapshot(
            transaction.capture_snapshot(_ARCHITECTURE_POLICY_FILENAME)
        )


def restore_architecture_policy_snapshot(
    godot_project_path: str,
    snapshot: ArchitecturePolicySnapshot,
    receipt: ArchitecturePolicyPublicationReceipt,
) -> str:
    """Restore a snapshot only while the report still exactly matches receipt."""
    _validate_policy_snapshot(snapshot)
    report_path = os.path.join(godot_project_path, ARCHITECTURE_POLICY_RELATIVE_PATH)
    if os.path.abspath(receipt.path) != os.path.abspath(report_path):
        raise ValueError("Architecture-policy publication receipt belongs to another path.")
    with ByteArtifactTransaction.open(
        godot_project_path,
        _ARCHITECTURE_POLICY_DIRECTORY,
        create=False,
        description="architecture-policy report directory",
    ) as transaction:
        if not transaction.available:
            raise OSError(
                "Architecture-policy report directory disappeared before restore."
            )
        _verify_policy_receipt(receipt, transaction)
        transaction.restore_snapshots(
            (_core_policy_snapshot(snapshot),),
            (_core_policy_receipt(receipt),),
        )
        return report_path


def _architecture_snapshot(snapshot: ArtifactSnapshot) -> ArchitecturePolicySnapshot:
    return ArchitecturePolicySnapshot(
        content=snapshot.content,
        mode=snapshot.mode,
        fingerprint=snapshot.fingerprint,
        sha256=snapshot.sha256,
    )


def _core_policy_snapshot(snapshot: ArchitecturePolicySnapshot) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        name=_ARCHITECTURE_POLICY_FILENAME,
        content=snapshot.content,
        mode=snapshot.mode,
        fingerprint=snapshot.fingerprint,
        sha256=snapshot.sha256,
    )


def _core_policy_receipt(
    receipt: ArchitecturePolicyPublicationReceipt,
) -> ArtifactReceipt:
    return ArtifactReceipt(
        path=receipt.path,
        content=receipt.content,
        mode=receipt.mode,
        fingerprint=receipt.fingerprint,
        sha256=receipt.sha256,
    )


def _verify_policy_receipt(
    receipt: ArchitecturePolicyPublicationReceipt,
    transaction: ByteArtifactTransaction,
) -> None:
    try:
        transaction.verify_receipt(_core_policy_receipt(receipt))
    except OSError as error:
        raise OSError(
            "Architecture-policy report no longer matches its publication receipt: "
            f"{receipt.path}"
        ) from error


def _architecture_receipt(
    receipt: ArtifactReceipt,
    *,
    path: str | None = None,
) -> ArchitecturePolicyPublicationReceipt:
    return ArchitecturePolicyPublicationReceipt(
        path=receipt.path if path is None else path,
        content=receipt.content,
        mode=receipt.mode,
        fingerprint=receipt.fingerprint,
        sha256=receipt.sha256,
    )


def _validate_policy_snapshot(snapshot: ArchitecturePolicySnapshot) -> None:
    if snapshot.present:
        if (
            snapshot.content is None
            or snapshot.mode is None
            or snapshot.sha256 is None
        ):
            raise ValueError("A present architecture-policy snapshot is incomplete.")
        assert snapshot.fingerprint is not None
        if (
            len(snapshot.content) != snapshot.fingerprint[2]
            or artifact_sha256(snapshot.content) != snapshot.sha256
        ):
            raise ValueError(
                "Architecture-policy snapshot content does not match its fingerprint."
            )
        return
    if (
        snapshot.content is not None
        or snapshot.mode is not None
        or snapshot.sha256 is not None
    ):
        raise ValueError("An absent architecture-policy snapshot cannot contain file data.")


def build_architecture_policy_report(
    gm_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> JsonDict:
    features = inspect_architecture_features(gm_project_path)
    return {
        "format_version": ARCHITECTURE_POLICY_VERSION,
        "target_platform": target_platform,
        "enabled_converters": sorted(set(enabled_converters)),
        "documentation_sources": GODOT_ARCHITECTURE_SOURCES,
        "project_features": features.to_dict(),
        "room_root": room_root_policy(),
        "layer_hierarchy": layer_hierarchy_policy(),
        "renderer": renderer_backend_policy(features),
        "collision": collision_backend_policy(features),
        "audio": audio_backend_policy(features),
        "file_buffer_network": file_buffer_network_policy(features),
        "runtime_managers": runtime_manager_policy(),
        "signal_queue_policy": signal_queue_policy(),
    }


def inspect_architecture_features(gm_project_path: str) -> ArchitectureFeatures:
    index = GameMakerResourceIndex(
        gm_project_path,
        "",
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
    ).build()
    rooms = index.ordered_rooms()
    script_text = _read_gml_sources(gm_project_path)

    return ArchitectureFeatures(
        room_count=len(rooms),
        has_views=any(_room_has_visible_views(room) for room in rooms),
        has_multiple_visible_views=any(_room_visible_view_count(room) > 1 for room in rooms),
        has_instance_layers=any(_room_has_layer(room, "GMRInstanceLayer") for room in rooms),
        has_tile_layers=any(_room_has_layer(room, "GMRTileLayer") for room in rooms),
        has_background_layers=any(_room_has_layer(room, "GMRBackgroundLayer") for room in rooms),
        has_scrolling_or_tiled_backgrounds=any(_room_has_scrolling_background(room) for room in rooms),
        has_effect_layers=any(_room_has_layer(room, "GMREffectLayer") for room in rooms),
        has_physics_world=any(bool(room.physics_settings.get("PhysicsWorld", False)) for room in rooms),
        has_draw_code=_matches(script_text, _DRAW_RE),
        has_surface_code=_matches(script_text, _SURFACE_RE),
        has_collision_code=_matches(script_text, _COLLISION_RE),
        has_precise_collision_request=(
            _matches(script_text, _PRECISE_COLLISION_RE)
            or _has_precise_sprite_resource(gm_project_path, index)
        ),
        has_audio_code=_matches(script_text, _AUDIO_RE),
        has_sound_assets=bool(index.resources.get("sounds")),
        has_network_code=_matches(script_text, _NETWORK_RE),
        has_buffer_file_code=_matches(script_text, _BUFFER_FILE_RE),
    )


def room_root_policy() -> JsonDict:
    return {
        "id": ROOM_ROOT_POLICY_ID,
        "godot_node": "Node2D",
        "script": "res://gm2godot/gml_room_node.gd",
        "main_scene_source": "first GameMaker RoomOrderNodes entry",
        "gui_layer_policy": GUI_LAYER_POLICY_ID,
        "rationale": "Rooms need stable 2D transforms and a generated entry hook while GameMaker lifecycle dispatch stays in GMRuntime/GMEvents.",
    }


def layer_hierarchy_policy() -> JsonDict:
    return {
        "id": LAYER_HIERARCHY_POLICY_ID,
        "layer_node": "Node2D",
        "depth_mapping": DEPTH_MAPPING_POLICY_ID,
        "depth_expression": "Node2D.z_index = -GameMaker layer depth",
        "gui_layer": {
            "id": GUI_LAYER_POLICY_ID,
            "godot_node": "CanvasLayer",
            "name": "GMGUI",
            "layer": 1000,
        },
        "tilemap_node": "TileMapLayer",
        "rationale": "GameMaker lower depth draws later; Godot higher z_index draws later, so depth is inverted on generated layer nodes.",
    }


def renderer_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    if features.has_surface_code:
        mode = "surface_viewport"
        fidelity = "high"
        rationale = "Surface/application-surface APIs require a SubViewport/ViewportTexture-capable draw manager path."
    elif features.has_draw_code or features.has_effect_layers:
        mode = "central_canvas_draw_manager"
        fidelity = "medium"
        rationale = "Draw/shader/effect code needs ordered CanvasItem draw dispatch through GMDraw."
    else:
        mode = "godot_node_scene"
        fidelity = "medium"
        rationale = "Projects without explicit draw/surface usage can prefer generated Godot nodes and per-layer z ordering."
    return {
        "domain": "render",
        "mode": mode,
        "fidelity": fidelity,
        "manager": "GMDraw",
        "queue_redraw": features.has_draw_code or features.has_surface_code,
        "uses_canvas_layer_for_gui": True,
        "uses_subviewport_for_surfaces": features.has_surface_code,
        "rationale": rationale,
    }


def collision_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    if features.has_physics_world:
        mode = "godot_physics_world_bridge"
        rationale = "Rooms with GameMaker physics enabled are routed through Godot 2D physics primitives plus compatibility metadata."
    elif features.has_collision_code:
        mode = "generated_bounds_direct_queries"
        rationale = (
            "Query-style collision APIs are evaluated against generated bounds "
            "or active precise-mask polygons in the GameMaker event scheduler."
        )
    else:
        mode = "generated_bounds_idle"
        rationale = "No collision API usage was detected; generated bounds remain available for later instance APIs."
    return {
        "domain": "collision",
        "mode": mode,
        "manager": "GMEvents",
        "query_api": "generated bounds and active precise-mask polygons",
        "godot_native_signals": "queued through GMEvents when used",
        "precise_masks": (
            "generated_alpha_mask_geometry"
            if features.has_precise_collision_request
            else "bounds_compatible"
        ),
        "rationale": rationale,
    }


def audio_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    active = features.has_audio_code or features.has_sound_assets
    return {
        "domain": "audio",
        "mode": "pooled_audio_stream_players" if active else "runtime_audio_manager_idle",
        "manager": "GMAudio",
        "godot_nodes": ["AudioStreamPlayer", "AudioStreamPlayer2D"],
        "godot_server": "AudioServer",
        "async_callbacks": "queued through GMAsync",
        "rationale": "Sound handles, loop/gain/pitch state, audio groups, and playback-ended signals need GameMaker-compatible runtime state.",
    }


def file_buffer_network_policy(features: ArchitectureFeatures) -> JsonDict:
    network_mode = "gm_async_socket_wrappers" if features.has_network_code else "runtime_network_idle"
    return {
        "domain": "file_buffer_network",
        "file_access": "FileAccess/DirAccess with GM2Godot path mapping",
        "buffers": "PackedByteArray with explicit endian/alignment helpers",
        "http": "HTTPRequest/HTTPClient events queued through GMAsync",
        "network": network_mode,
        "network_primitives": ["StreamPeerTCP", "TCPServer", "PacketPeerUDP", "WebSocketPeer"],
        "godot_multiplayer_api": "not used as a direct replacement for GameMaker sockets",
        "has_file_or_buffer_code": features.has_buffer_file_code,
        "rationale": "GameMaker networking and async file APIs expose event payloads rather than Godot-native signal order.",
    }


def runtime_manager_policy() -> list[JsonDict]:
    return [
        {
            "name": definition.name,
            "domain": definition.domain,
            "order": definition.order,
            "dependencies": list(definition.dependencies),
            "state_keys": list(definition.state_keys),
            "queued_godot_signals": list(definition.queued_godot_signals),
        }
        for definition in runtime_manager_definitions()
    ]


def signal_queue_policy() -> list[JsonDict]:
    policies: list[JsonDict] = []
    for definition in runtime_manager_definitions():
        for signal_name in definition.queued_godot_signals:
            policies.append({
                "godot_signal": signal_name,
                "runtime_manager": definition.name,
                "domain": definition.domain,
                "queue": _queue_name_for_signal(signal_name, definition.name),
            })
    return policies


def room_root_metadata_lines() -> list[str]:
    return [
        f"metadata/gm2godot_architecture_policy_version = {ARCHITECTURE_POLICY_VERSION}",
        f"metadata/gm2godot_room_root_policy = {json.dumps(ROOM_ROOT_POLICY_ID)}",
        f"metadata/gm2godot_layer_hierarchy_policy = {json.dumps(LAYER_HIERARCHY_POLICY_ID)}",
        f"metadata/gm2godot_depth_mapping_policy = {json.dumps(DEPTH_MAPPING_POLICY_ID)}",
        f"metadata/gm2godot_gui_layer_policy = {json.dumps(GUI_LAYER_POLICY_ID)}",
    ]


def gui_canvas_layer_node_lines(parent_path: str = ".") -> list[str]:
    return [
        f'[node name="GMGUI" type="CanvasLayer" parent={json.dumps(parent_path)}]',
        "layer = 1000",
        f"metadata/gm2godot_gui_layer_policy = {json.dumps(GUI_LAYER_POLICY_ID)}",
        'metadata/gamemaker_layer_element_type = "draw_gui"',
        "metadata/gamemaker_event_queue = \"GMDraw\"",
        "",
    ]


def layer_policy_metadata_lines() -> list[str]:
    return [
        f"metadata/gm2godot_layer_policy = {json.dumps(LAYER_HIERARCHY_POLICY_ID)}",
        f"metadata/gm2godot_depth_mapping_policy = {json.dumps(DEPTH_MAPPING_POLICY_ID)}",
    ]


def _read_gml_sources(gm_project_path: str) -> str:
    chunks: list[str] = []
    for root, dirs, files in os.walk(gm_project_path):
        dirs[:] = sorted(dirs)
        for filename in sorted(files):
            if not filename.endswith(".gml"):
                continue
            path = os.path.join(root, filename)
            try:
                resolved = resolve_project_filesystem_source_path(
                    gm_project_path,
                    path,
                )
                with open(
                    resolved.filesystem_path,
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    chunks.append(source_file.read())
            except (OSError, ProjectSourcePathError):
                continue
    return "\n".join(chunks)


def _has_precise_sprite_resource(
    gm_project_path: str,
    index: GameMakerResourceIndex,
) -> bool:
    for resource in index.resources.get("sprites", {}).values():
        try:
            resolved = resolve_project_filesystem_source_path(
                gm_project_path,
                resource.yy_path,
            )
            with open(
                resolved.filesystem_path,
                "r",
                encoding="utf-8",
            ) as sprite_file:
                if _PRECISE_SPRITE_KIND_RE.search(sprite_file.read()) is not None:
                    return True
        except (OSError, ProjectSourcePathError):
            continue
    return False


def _matches(value: str, pattern: re.Pattern[str]) -> bool:
    return pattern.search(value) is not None


def _room_has_visible_views(room: IndexedRoom) -> bool:
    if not bool(room.view_settings.get("enableViews", False)):
        return False
    return _room_visible_view_count(room) > 0


def _room_visible_view_count(room: IndexedRoom) -> int:
    visible_count = 0
    for view in room.views:
        if not isinstance(view, dict):
            continue
        typed_view = cast(JsonDict, view)
        if bool(typed_view.get("visible", False)):
            visible_count += 1
    return visible_count


def _room_has_layer(room: IndexedRoom, resource_type: str) -> bool:
    return any(_layer_resource_type(layer) == resource_type for layer in _iter_layers(room.layers))


def _room_has_scrolling_background(room: IndexedRoom) -> bool:
    for layer in _iter_layers(room.layers):
        if _layer_resource_type(layer) != "GMRBackgroundLayer":
            continue
        if any(bool(layer.get(key, False)) for key in ("htiled", "vtiled", "stretch")):
            return True
        if _number(layer.get("hspeed")) != 0.0 or _number(layer.get("vspeed")) != 0.0:
            return True
    return False


def _iter_layers(layers: object) -> Iterable[JsonDict]:
    if not isinstance(layers, list):
        return
    for item in cast(list[object], layers):
        if not isinstance(item, dict):
            continue
        layer = cast(JsonDict, item)
        yield layer
        children = layer.get("layers") or layer.get("children")
        yield from _iter_layers(children)


def _layer_resource_type(layer: JsonDict) -> str:
    resource_type = layer.get("resourceType")
    if isinstance(resource_type, str) and resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _queue_name_for_signal(signal_name: str, manager_name: str) -> str:
    if manager_name == "GMAsync":
        return "gml_async_enqueue_from_signal"
    if manager_name == "GMEvents":
        return "gml_event_scheduler_frame"
    return "manager_state_queue"
