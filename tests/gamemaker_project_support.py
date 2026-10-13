"""Small GameMaker projects written from Python, converted with the full converter.

Godot tests use these to check what a converted game does at run time: they
describe objects (events as GML source), rooms (instance layers, creation order
and creation code) and function-only scripts, convert the project with every
converter enabled, and run it headless with a probe autoload.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.gui.setting_value import SettingValue
from tests.godot_test_support import write_fixture_text

# GameMaker event file names by event type.
_EVENT_FILE_PREFIXES = {
    0: "Create", 1: "Destroy", 2: "Alarm", 3: "Step", 4: "Collision", 7: "Other", 8: "Draw", 12: "CleanUp",
}
EVENT_CREATE = (0, 0)
EVENT_DESTROY = (1, 0)
EVENT_STEP = (3, 0)
EVENT_BEGIN_STEP = (3, 1)
EVENT_GAME_START = (7, 2)
EVENT_ROOM_START = (7, 4)
EVENT_DRAW = (8, 0)
EVENT_CLEAN_UP = (12, 0)


def collision_event(object_name: str) -> tuple[int, str]:
    """The key of a Collision event with an object in GameMakerObject.events."""
    return (4, object_name)


@dataclass(frozen=True)
class GameMakerObject:
    name: str
    # (event type, number), or (4, object name) for a Collision event.
    events: Mapping[tuple[int, int | str], str]
    persistent: bool = False
    parent: str | None = None
    sprite: str | None = None
    visible: bool = True


@dataclass(frozen=True)
class RoomInstance:
    name: str
    object_name: str
    x: float
    y: float
    creation_code: str | None = None


@dataclass(frozen=True)
class InstanceLayer:
    name: str
    depth: int
    instances: Sequence[RoomInstance]


@dataclass(frozen=True)
class BackgroundLayer:
    """A GMRBackgroundLayer: a sprite (or only a colour) with its tiling and scrolling."""

    name: str
    depth: int
    sprite: str | None = None
    colour: int = 0xFFFFFFFF
    x: float = 0
    y: float = 0
    htiled: bool = False
    vtiled: bool = False
    stretch: bool = False
    hspeed: float = 0
    vspeed: float = 0


@dataclass(frozen=True)
class SpriteAsset:
    """A GMRSpriteGraphic on an asset layer."""

    name: str
    sprite: str
    x: float
    y: float
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    head_position: float = 0.0
    animation_speed: float = 1.0
    colour: int = 0xFFFFFFFF


@dataclass(frozen=True)
class AssetLayer:
    name: str
    depth: int
    assets: Sequence[SpriteAsset]


@dataclass(frozen=True)
class RoomView:
    """One view of a room: what it shows (view) and where (port)."""

    xview: int
    yview: int
    wview: int
    hview: int
    xport: int
    yport: int
    wport: int
    hport: int
    visible: bool = True


@dataclass(frozen=True)
class GameMakerRoom:
    name: str
    layers: Sequence[InstanceLayer | BackgroundLayer | AssetLayer]
    creation_order: Sequence[str]
    creation_code: str | None = None
    width: int = 320
    height: int = 240
    views: Sequence[RoomView] = ()
    persistent: bool = False


@dataclass(frozen=True)
class GameMakerSprite:
    """A sprite whose frames are RGBA images (rows of (r, g, b, a) pixels)."""

    name: str
    width: int
    height: int
    frames: Sequence[Sequence[Sequence[tuple[int, int, int, int]]]]
    xorigin: int = 0
    yorigin: int = 0
    playback_speed: float = 0.0


@dataclass(frozen=True)
class GameMakerProject:
    name: str
    objects: Sequence[GameMakerObject]
    rooms: Sequence[GameMakerRoom]
    scripts: Mapping[str, str] = field(default_factory=dict[str, str])
    sprites: Sequence[GameMakerSprite] = ()


def _write_json(path: Path, value: object) -> None:
    write_fixture_text(path, json.dumps(value, indent=2) + "\n")


def _object_yy(game_object: GameMakerObject) -> dict[str, object]:
    return {
        "$GMObject": "",
        "%Name": game_object.name,
        "eventList": [
            {
                "$GMEvent": "v1",
                "%Name": "",
                "collisionObjectId": _asset_ref("objects", event_number) if isinstance(event_number, str) else None,
                "eventNum": 0 if isinstance(event_number, str) else event_number,
                "eventType": event_type,
                "isDnD": False,
                "name": "",
                "resourceType": "GMEvent",
                "resourceVersion": "2.0",
            }
            for event_type, event_number in game_object.events
        ],
        "managed": True,
        "name": game_object.name,
        "overriddenProperties": [],
        "parent": {"name": "Objects", "path": "folders/Objects.yy"},
        "parentObjectId": (
            None
            if game_object.parent is None
            else {"name": game_object.parent, "path": f"objects/{game_object.parent}/{game_object.parent}.yy"}
        ),
        "persistent": game_object.persistent,
        "physicsObject": False,
        "properties": [],
        "resourceType": "GMObject",
        "resourceVersion": "2.0",
        "solid": False,
        "spriteId": _asset_ref("sprites", game_object.sprite),
        "spriteMaskId": None,
        "visible": game_object.visible,
    }


def _room_instance_yy(instance: RoomInstance) -> dict[str, object]:
    return {
        "$GMRInstance": "v1",
        "%Name": instance.name,
        "colour": 4294967295,
        "frozen": False,
        "hasCreationCode": instance.creation_code is not None,
        "ignore": False,
        "imageIndex": 0,
        "imageSpeed": 1.0,
        "inheritCode": False,
        "inheritedItemId": None,
        "inheritItemSettings": False,
        "isDnd": False,
        "name": instance.name,
        "objectId": {
            "name": instance.object_name,
            "path": f"objects/{instance.object_name}/{instance.object_name}.yy",
        },
        "properties": [],
        "resourceType": "GMRInstance",
        "resourceVersion": "2.0",
        "rotation": 0.0,
        "scaleX": 1.0,
        "scaleY": 1.0,
        "x": instance.x,
        "y": instance.y,
    }


_LAYER_COMMON: dict[str, object] = {
    "effectEnabled": True,
    "effectType": None,
    "gridX": 32,
    "gridY": 32,
    "hierarchyFrozen": False,
    "inheritLayerDepth": False,
    "inheritLayerSettings": False,
    "inheritSubLayers": True,
    "inheritVisibility": True,
    "layers": [],
    "properties": [],
    "resourceVersion": "2.0",
    "userdefinedDepth": False,
    "visible": True,
}


def _asset_ref(kind: str, name: str | None) -> dict[str, str] | None:
    return None if name is None else {"name": name, "path": f"{kind}/{name}/{name}.yy"}


def _sprite_asset_yy(asset: SpriteAsset) -> dict[str, object]:
    return {
        "$GMRSpriteGraphic": "",
        "%Name": asset.name,
        "animationSpeed": asset.animation_speed,
        "colour": asset.colour,
        "frozen": False,
        "headPosition": asset.head_position,
        "ignore": False,
        "inheritedItemId": None,
        "inheritItemSettings": False,
        "name": asset.name,
        "resourceType": "GMRSpriteGraphic",
        "resourceVersion": "2.0",
        "rotation": asset.rotation,
        "scaleX": asset.scale_x,
        "scaleY": asset.scale_y,
        "spriteId": _asset_ref("sprites", asset.sprite),
        "x": asset.x,
        "y": asset.y,
    }


def _room_layer_yy(layer: InstanceLayer | BackgroundLayer | AssetLayer) -> dict[str, object]:
    common = {**_LAYER_COMMON, "%Name": layer.name, "name": layer.name, "depth": layer.depth}
    if isinstance(layer, BackgroundLayer):
        return {
            **common,
            "$GMRBackgroundLayer": "",
            "animationFPS": 15.0,
            "animationSpeedType": 0,
            "colour": layer.colour,
            "hspeed": layer.hspeed,
            "htiled": layer.htiled,
            "resourceType": "GMRBackgroundLayer",
            "spriteId": _asset_ref("sprites", layer.sprite),
            "stretch": layer.stretch,
            "userdefinedAnimFPS": False,
            "vspeed": layer.vspeed,
            "vtiled": layer.vtiled,
            "x": layer.x,
            "y": layer.y,
        }
    if isinstance(layer, AssetLayer):
        return {
            **common,
            "$GMRAssetLayer": "",
            "assets": [_sprite_asset_yy(asset) for asset in layer.assets],
            "resourceType": "GMRAssetLayer",
        }
    return {
        **common,
        "$GMRInstanceLayer": "",
        "instances": [_room_instance_yy(instance) for instance in layer.instances],
        "resourceType": "GMRInstanceLayer",
    }


def _room_view_yy(view: RoomView) -> dict[str, object]:
    return {
        "hborder": 32,
        "hport": view.hport,
        "hspeed": -1,
        "hview": view.hview,
        "inherit": False,
        "objectId": None,
        "vborder": 32,
        "visible": view.visible,
        "vspeed": -1,
        "wport": view.wport,
        "wview": view.wview,
        "xport": view.xport,
        "xview": view.xview,
        "yport": view.yport,
        "yview": view.yview,
    }


def _room_yy(room: GameMakerRoom) -> dict[str, object]:
    return {
        "$GMRoom": "v1",
        "%Name": room.name,
        "creationCodeFile": (
            f"rooms/{room.name}/RoomCreationCode.gml" if room.creation_code is not None else ""
        ),
        "inheritCode": False,
        "inheritCreationOrder": False,
        "inheritLayers": False,
        "instanceCreationOrder": [
            {"name": name, "path": f"rooms/{room.name}/{room.name}.yy"} for name in room.creation_order
        ],
        "isDnd": False,
        "layers": [_room_layer_yy(layer) for layer in room.layers],
        "name": room.name,
        "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
        "parentRoom": None,
        "physicsSettings": {
            "inheritPhysicsSettings": False,
            "PhysicsWorld": False,
            "PhysicsWorldGravityX": 0.0,
            "PhysicsWorldGravityY": 10.0,
            "PhysicsWorldPixToMetres": 0.1,
        },
        "resourceType": "GMRoom",
        "resourceVersion": "2.0",
        "roomSettings": {
            "Height": room.height,
            "inheritRoomSettings": False,
            "persistent": room.persistent,
            "Width": room.width,
        },
        "sequenceId": None,
        "views": [_room_view_yy(view) for view in room.views],
        "viewSettings": {
            "clearDisplayBuffer": True,
            "clearViewBackground": False,
            "enableViews": bool(room.views),
            "inheritViewSettings": False,
        },
        "volume": 1.0,
    }


def _sprite_yy(sprite: GameMakerSprite) -> dict[str, object]:
    frame_names = [f"frame_{index}" for index in range(len(sprite.frames))]
    return {
        "$GMSprite": "",
        "%Name": sprite.name,
        "bboxMode": 0,
        "bbox_bottom": sprite.height - 1,
        "bbox_left": 0,
        "bbox_right": sprite.width - 1,
        "bbox_top": 0,
        "collisionKind": 1,
        "collisionTolerance": 0,
        "frames": [
            {"$GMSpriteFrame": "", "%Name": name, "name": name, "resourceType": "GMSpriteFrame", "resourceVersion": "2.0"}
            for name in frame_names
        ],
        "height": sprite.height,
        "layers": [
            {
                "$GMImageLayer": "",
                "%Name": "layer_0",
                "blendMode": 0,
                "displayName": "default",
                "isLocked": False,
                "name": "layer_0",
                "opacity": 100.0,
                "resourceType": "GMImageLayer",
                "resourceVersion": "2.0",
                "visible": True,
            }
        ],
        "name": sprite.name,
        "origin": 9,
        "parent": {"name": "Sprites", "path": "folders/Sprites.yy"},
        "resourceType": "GMSprite",
        "resourceVersion": "2.0",
        "sequence": {
            "$GMSequence": "",
            "%Name": sprite.name,
            "length": float(len(sprite.frames)),
            "name": sprite.name,
            "playback": 1,
            "playbackSpeed": sprite.playback_speed,
            "playbackSpeedType": 0,
            "resourceType": "GMSequence",
            "resourceVersion": "2.0",
            "tracks": [
                {
                    "$GMSpriteFramesTrack": "",
                    "keyframes": {
                        "Keyframes": [
                            {
                                "Channels": {"0": {"Id": {"name": name, "path": f"sprites/{sprite.name}/{sprite.name}.yy"}}},
                                "Key": float(index),
                                "Length": 1.0,
                            }
                            for index, name in enumerate(frame_names)
                        ]
                    },
                    "name": "frames",
                    "resourceType": "GMSpriteFramesTrack",
                }
            ],
            "xorigin": sprite.xorigin,
            "yorigin": sprite.yorigin,
        },
        "type": 0,
        "width": sprite.width,
    }


def _write_sprite(project_dir: Path, sprite: GameMakerSprite) -> None:
    from PIL import Image

    sprite_dir = project_dir / "sprites" / sprite.name
    _write_json(sprite_dir / f"{sprite.name}.yy", _sprite_yy(sprite))
    for index, rows in enumerate(sprite.frames):
        data = bytes(channel for row in rows for pixel in row for channel in pixel)
        image = Image.frombytes("RGBA", (sprite.width, sprite.height), data)
        for path in (sprite_dir / f"frame_{index}.png", sprite_dir / "layers" / f"frame_{index}" / "layer_0.png"):
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)


def write_gamemaker_project(project_dir: Path, project: GameMakerProject) -> None:
    """Write the project's .yyp, sprites, objects, rooms and scripts."""
    resources: list[dict[str, object]] = []
    for sprite in project.sprites:
        _write_sprite(project_dir, sprite)
        resources.append({"id": {"name": sprite.name, "path": f"sprites/{sprite.name}/{sprite.name}.yy"}})
    for script_name, source in project.scripts.items():
        script_dir = project_dir / "scripts" / script_name
        _write_json(
            script_dir / f"{script_name}.yy",
            {
                "$GMScript": "v1",
                "%Name": script_name,
                "isCompatibility": False,
                "isDnD": False,
                "name": script_name,
                "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
                "resourceType": "GMScript",
                "resourceVersion": "2.0",
            },
        )
        write_fixture_text(script_dir / f"{script_name}.gml", source)
        resources.append({"id": {"name": script_name, "path": f"scripts/{script_name}/{script_name}.yy"}})
    for game_object in project.objects:
        object_dir = project_dir / "objects" / game_object.name
        _write_json(object_dir / f"{game_object.name}.yy", _object_yy(game_object))
        for (event_type, event_number), source in game_object.events.items():
            prefix = _EVENT_FILE_PREFIXES[event_type]
            write_fixture_text(object_dir / f"{prefix}_{event_number}.gml", source)
        resources.append(
            {"id": {"name": game_object.name, "path": f"objects/{game_object.name}/{game_object.name}.yy"}}
        )
    for room in project.rooms:
        room_dir = project_dir / "rooms" / room.name
        _write_json(room_dir / f"{room.name}.yy", _room_yy(room))
        if room.creation_code is not None:
            write_fixture_text(room_dir / "RoomCreationCode.gml", room.creation_code)
        for layer in room.layers:
            if not isinstance(layer, InstanceLayer):
                continue
            for instance in layer.instances:
                if instance.creation_code is not None:
                    write_fixture_text(
                        room_dir / f"InstanceCreationCode_{instance.name}.gml",
                        instance.creation_code,
                    )
        resources.append({"id": {"name": room.name, "path": f"rooms/{room.name}/{room.name}.yy"}})
    _write_json(
        project_dir / f"{project.name}.yyp",
        {
            "$GMProject": "",
            "%Name": project.name,
            "AudioGroups": [],
            "configs": {"children": [], "name": "Default"},
            "defaultScriptType": 1,
            "Folders": [],
            "IncludedFiles": [],
            "isEcma": False,
            "LibraryEmitters": [],
            "MetaData": {"IDEVersion": "2024.11.0.179"},
            "name": project.name,
            "resources": resources,
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
            "RoomOrderNodes": [
                {"roomId": {"name": room.name, "path": f"rooms/{room.name}/{room.name}.yy"}}
                for room in project.rooms
            ],
            "templateType": None,
            "TextureGroups": [],
        },
    )


def convert_gamemaker_project(gamemaker_dir: Path, godot_dir: Path) -> list[str]:
    """Convert with every converter enabled; returns the conversion log."""
    write_fixture_text(godot_dir / "project.godot", '[application]\nconfig/name="Probe"\n')
    keys = CONVERSION_CATEGORIES["assets"] + CONVERSION_CATEGORIES["project"] + CONVERSION_CATEGORIES["wip"]
    logs: list[str] = []
    running = threading.Event()
    running.set()

    def log_message(message: object) -> None:
        logs.append(str(message))

    def ignore(_value: object) -> None:
        return None

    converter = cast(Any, Converter)(
        log_callback=log_message,
        progress_callback=ignore,
        status_callback=ignore,
        conversion_running=running,
        compact_logging=True,
    )
    converter.convert(str(gamemaker_dir), "windows", str(godot_dir), {key: SettingValue(True) for key in keys})
    return logs


def add_probe_autoload(godot_dir: Path, probe_source: str) -> None:
    """Add a probe autoload (res://probe.gd) to a converted project."""
    write_fixture_text(godot_dir / "probe.gd", probe_source)
    settings_path = godot_dir / "project.godot"
    settings = settings_path.read_text(encoding="utf-8")
    entry = 'Probe="*res://probe.gd"\n'
    if "[autoload]\n" in settings:
        settings = settings.replace("[autoload]\n", "[autoload]\n\n" + entry, 1)
    else:
        settings += "\n[autoload]\n\n" + entry
    settings_path.write_text(settings, encoding="utf-8")


def run_converted_project(godot_binary: str, godot_dir: Path, *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["HOME"] = str(godot_dir)
    return subprocess.run(
        [godot_binary, "--headless", "--log-file", str(godot_dir / "godot.log"), "--path", str(godot_dir)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )


def run_converted_project_rendered(
    godot_binary: str, godot_dir: Path, *, timeout: float = 180
) -> subprocess.CompletedProcess[str] | None:
    """Run the converted project with an OpenGL renderer under xvfb-run, so a
    probe can read rendered pixels back; None when xvfb-run is missing."""
    if shutil.which("xvfb-run") is None:
        return None
    environment = dict(os.environ)
    environment["HOME"] = str(godot_dir)
    return subprocess.run(
        [
            "xvfb-run",
            "-a",
            "-s",
            "-screen 0 1024x768x24",
            godot_binary,
            "--log-file",
            str(godot_dir / "godot.log"),
            "--path",
            str(godot_dir),
            "--rendering-driver",
            "opengl3",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )


def import_converted_project(godot_binary: str, godot_dir: Path, *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """Import the converted project's resources (sprite images), which a
    project needs before it runs."""
    environment = dict(os.environ)
    environment["HOME"] = str(godot_dir)
    return subprocess.run(
        [godot_binary, "--headless", "--recovery-mode", "--path", str(godot_dir), "--import"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
