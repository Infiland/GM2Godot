from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.collision_runtime_support import (
    CollisionSprite,
    object_entry,
    object_scene_path,
    run_smoke_scene,
    write_collision_project,
    write_generated_object,
)
from tests.godot_test_support import find_smoke_godot_binary

_BODY = CollisionSprite("spr_body", 32, 32, (16, 16), (0, 0, 31, 31))
_HITBOX = CollisionSprite("spr_hitbox", 8, 8, (4, 4), (0, 0, 7, 7))
# Objects with their sprite and the collision mask set in the object editor.
_OBJECTS: tuple[tuple[str, CollisionSprite, str | None], ...] = (
    ("o_masked", _BODY, _HITBOX.name),
    ("o_plain", _BODY, None),
    ("o_target", _HITBOX, None),
)


class TestObjectCollisionMasksGodot(unittest.TestCase):
    def test_instances_collide_with_their_object_collision_mask(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="ObjectCollisionMasks",
                sprites=(_BODY, _HITBOX),
                objects=tuple(
                    object_entry(100 + index, name, object_scene_path(name))
                    for index, (name, _sprite, _mask) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "object_masks_smoke.gd"},
                application_settings="config/gm2godot_collision_compatibility=true\n",
            )
            for name, sprite, mask in _OBJECTS:
                write_generated_object(project_dir, name, sprite, mask_sprite_name=mask)
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("OBJECT_COLLISION_MASKS_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
