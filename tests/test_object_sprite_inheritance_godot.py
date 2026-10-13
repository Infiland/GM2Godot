from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.conversion.objects import ObjectConverter
from tests.collision_runtime_support import (
    CollisionSprite,
    object_entry,
    object_scene_path,
    run_smoke_scene,
    write_collision_project,
)
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_SPRITES = (
    CollisionSprite("spr_base", 32, 32, (16, 16), (0, 0, 31, 31)),
    CollisionSprite("spr_mid", 16, 16, (8, 8), (0, 0, 15, 15)),
    CollisionSprite("spr_leaf", 8, 8, (4, 4), (0, 0, 7, 7)),
    CollisionSprite("spr_target", 8, 8, (4, 4), (0, 0, 7, 7)),
)
_CREATE = (0, 0)
# name, sprite, parent, Create event (None: the object has none).
_OBJECTS: tuple[tuple[str, str | None, str | None, str | None], ...] = (
    ("o_base", "spr_base", None, "base_ran = 1;\n"),
    ("o_mid", None, "o_base", "event_inherited();\nmid_ran = 1;\n"),
    ("o_leaf", "spr_leaf", "o_mid", None),
    ("o_leaf_create", "spr_leaf", "o_mid", "event_inherited();\nleaf_ran = 1;\n"),
    (
        "o_switcher",
        "spr_leaf",
        "o_mid",
        "sprite_index = spr_base;\nimage_speed = 0.5;\nimage_xscale = 2;\nevent_inherited();\n",
    ),
    ("o_bare", None, "o_base", None),
    ("o_mid_sprite", "spr_mid", "o_base", "event_inherited();\n"),
    ("o_leaf_under_sprite", "spr_leaf", "o_mid_sprite", None),
    ("o_target", "spr_target", None, None),
)


def _resource_reference(kind: str, name: str | None) -> dict[str, str] | None:
    return None if name is None else {"name": name, "path": f"{kind}/{name}/{name}.yy"}


def _write_gamemaker_objects(gamemaker_dir: Path) -> None:
    for name, sprite, parent, create in _OBJECTS:
        object_dir = gamemaker_dir / "objects" / name
        events = [] if create is None else [_CREATE]
        yy = {
            "$GMObject": "",
            "%Name": name,
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
                for event_type, event_number in events
            ],
            "managed": True,
            "name": name,
            "overriddenProperties": [],
            "parent": {"name": "Objects", "path": "folders/Objects.yy"},
            "parentObjectId": _resource_reference("objects", parent),
            "persistent": False,
            "physicsObject": False,
            "properties": [],
            "resourceType": "GMObject",
            "resourceVersion": "2.0",
            "solid": False,
            "spriteId": _resource_reference("sprites", sprite),
            "spriteMaskId": None,
            "visible": True,
        }
        write_fixture_text(object_dir / f"{name}.yy", json.dumps(yy, indent=2) + "\n")
        if create is not None:
            write_fixture_text(object_dir / "Create_0.gml", create)


class TestObjectSpriteInheritanceGodot(unittest.TestCase):
    def test_instances_start_with_their_own_objects_sprite(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            gamemaker_dir = Path(temporary_directory) / "gamemaker"
            project_dir = Path(temporary_directory) / "godot"
            write_collision_project(
                project_dir,
                project_name="ObjectSpriteInheritance",
                sprites=_SPRITES,
                objects=tuple(
                    object_entry(100 + index, name, object_scene_path(name))
                    for index, (name, _sprite, _parent, _create) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "sprite_inheritance_smoke.gd"},
                application_settings="config/gm2godot_collision_compatibility=true\n",
            )
            _write_gamemaker_objects(gamemaker_dir)
            logs: list[str] = []
            ObjectConverter(
                str(gamemaker_dir),
                str(project_dir),
                log_callback=logs.append,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
            ).convert_all()
            for name, _sprite, _parent, _create in _OBJECTS:
                self.assertTrue((project_dir / "objects" / name / f"{name}.gd").is_file(), "\n".join(logs))
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SPRITE_INHERITANCE_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
