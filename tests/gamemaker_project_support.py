"""Small GameMaker projects written from Python, converted with the full converter.

Godot tests use these to check what a converted game does at run time: they
describe objects (events as GML source), rooms (instance layers, creation order
and creation code) and function-only scripts, convert the project with every
converter enabled, and run it headless with a probe autoload.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from PIL import Image

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.gui.setting_value import SettingValue
from tests.godot_test_support import write_fixture_text

# GameMaker event file names by event type.
_EVENT_FILE_PREFIXES = {0: "Create", 1: "Destroy", 2: "Alarm", 3: "Step", 7: "Other", 8: "Draw", 12: "CleanUp"}
EVENT_CREATE = (0, 0)
EVENT_DESTROY = (1, 0)
EVENT_STEP = (3, 0)
EVENT_GAME_START = (7, 2)
EVENT_ROOM_START = (7, 4)
EVENT_ROOM_END = (7, 5)
EVENT_CLEAN_UP = (12, 0)


@dataclass(frozen=True)
class GameMakerObject:
    name: str
    events: Mapping[tuple[int, int], str]
    persistent: bool = False
    parent: str | None = None
    sprite: str | None = None
    # Collision events: the other object's name -> GML source.
    collisions: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class GameMakerSprite:
    """A one-frame sprite: a filled rectangle with its origin at the top left
    and a rectangle collision mask."""

    name: str
    width: int
    height: int


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
class GameMakerRoom:
    name: str
    layers: Sequence[InstanceLayer]
    creation_order: Sequence[str]
    creation_code: str | None = None
    width: int = 320
    height: int = 240


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
                "collisionObjectId": None,
                "eventNum": event_number,
                "eventType": event_type,
                "isDnD": False,
                "name": "",
                "resourceType": "GMEvent",
                "resourceVersion": "2.0",
            }
            for event_type, event_number in game_object.events
        ]
        + [_collision_event_yy(target) for target in game_object.collisions],
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
        "spriteId": (
            None
            if game_object.sprite is None
            else {"name": game_object.sprite, "path": f"sprites/{game_object.sprite}/{game_object.sprite}.yy"}
        ),
        "spriteMaskId": None,
        "visible": True,
    }


def _collision_event_yy(target: str) -> dict[str, object]:
    return {
        "$GMEvent": "v1",
        "%Name": "",
        "collisionObjectId": {"name": target, "path": f"objects/{target}/{target}.yy"},
        "eventNum": 0,
        "eventType": 4,
        "isDnD": False,
        "name": "",
        "resourceType": "GMEvent",
        "resourceVersion": "2.0",
    }


def _write_sprite(project_dir: Path, sprite: GameMakerSprite) -> None:
    sprite_dir = project_dir / "sprites" / sprite.name
    frame_name = f"{sprite.name}_frame"
    layer_name = f"{sprite.name}_layer"
    image_path = sprite_dir / "layers" / frame_name / f"{layer_name}.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (sprite.width, sprite.height), (255, 255, 255, 255)).save(image_path)
    _write_json(
        sprite_dir / f"{sprite.name}.yy",
        {
            "$GMSprite": "v2",
            "%Name": sprite.name,
            "name": sprite.name,
            "resourceType": "GMSprite",
            "resourceVersion": "2.0",
            "width": sprite.width,
            "height": sprite.height,
            "origin": 0,
            "bboxMode": 0,
            "bbox_left": 0,
            "bbox_right": sprite.width - 1,
            "bbox_top": 0,
            "bbox_bottom": sprite.height - 1,
            "collisionKind": 1,
            "collisionTolerance": 0,
            "frames": [
                {"$GMSpriteFrame": "v1", "name": frame_name, "resourceType": "GMSpriteFrame", "resourceVersion": "2.0"}
            ],
            "layers": [
                {
                    "$GMImageLayer": "",
                    "name": layer_name,
                    "visible": True,
                    "resourceType": "GMImageLayer",
                    "resourceVersion": "2.0",
                }
            ],
            "parent": {"name": "Sprites", "path": "folders/Sprites.yy"},
            "sequence": {
                "xorigin": 0,
                "yorigin": 0,
                "playbackSpeed": 0.0,
                "playbackSpeedType": 0,
                "playback": 1,
                "tracks": [{"keyframes": {"Keyframes": [{"Key": 0.0, "Length": 1.0, "Channels": {"0": {"Id": {"name": frame_name}}}}]}}],
            },
        },
    )


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
        "layers": [
            {
                "$GMRInstanceLayer": "",
                "%Name": layer.name,
                "depth": layer.depth,
                "effectEnabled": True,
                "effectType": None,
                "gridX": 32,
                "gridY": 32,
                "hierarchyFrozen": False,
                "inheritLayerDepth": False,
                "inheritLayerSettings": False,
                "inheritSubLayers": True,
                "inheritVisibility": True,
                "instances": [_room_instance_yy(instance) for instance in layer.instances],
                "layers": [],
                "name": layer.name,
                "properties": [],
                "resourceType": "GMRInstanceLayer",
                "resourceVersion": "2.0",
                "userdefinedDepth": False,
                "visible": True,
            }
            for layer in room.layers
        ],
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
            "persistent": False,
            "Width": room.width,
        },
        "sequenceId": None,
        "views": [],
        "viewSettings": {
            "clearDisplayBuffer": True,
            "clearViewBackground": False,
            "enableViews": False,
            "inheritViewSettings": False,
        },
        "volume": 1.0,
    }


def write_gamemaker_project(project_dir: Path, project: GameMakerProject) -> None:
    """Write the project's .yyp, objects, rooms and scripts."""
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
        for target, source in game_object.collisions.items():
            write_fixture_text(object_dir / f"Collision_{target}.gml", source)
        resources.append(
            {"id": {"name": game_object.name, "path": f"objects/{game_object.name}/{game_object.name}.yy"}}
        )
    for room in project.rooms:
        room_dir = project_dir / "rooms" / room.name
        _write_json(room_dir / f"{room.name}.yy", _room_yy(room))
        if room.creation_code is not None:
            write_fixture_text(room_dir / "RoomCreationCode.gml", room.creation_code)
        for layer in room.layers:
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


def import_converted_project(godot_binary: str, godot_dir: Path, *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """Import a converted project's assets (sprite images) before it runs."""
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
