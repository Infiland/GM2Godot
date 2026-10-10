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

from src.conversion.converter import CONVERSION_CATEGORIES, Converter
from src.gui.setting_value import SettingValue
from tests.godot_test_support import write_fixture_text

# GameMaker event file names by event type.
_EVENT_FILE_PREFIXES = {0: "Create", 1: "Destroy", 2: "Alarm", 3: "Step", 7: "Other", 8: "Draw"}
EVENT_CREATE = (0, 0)
EVENT_DESTROY = (1, 0)
EVENT_STEP = (3, 0)
EVENT_GAME_START = (7, 2)
EVENT_ROOM_START = (7, 4)


@dataclass(frozen=True)
class GameMakerObject:
    name: str
    events: Mapping[tuple[int, int], str]
    persistent: bool = False


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
        ],
        "managed": True,
        "name": game_object.name,
        "overriddenProperties": [],
        "parent": {"name": "Objects", "path": "folders/Objects.yy"},
        "parentObjectId": None,
        "persistent": game_object.persistent,
        "physicsObject": False,
        "properties": [],
        "resourceType": "GMObject",
        "resourceVersion": "2.0",
        "solid": False,
        "spriteId": None,
        "spriteMaskId": None,
        "visible": True,
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
