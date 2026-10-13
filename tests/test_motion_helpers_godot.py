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

_SPRITE = CollisionSprite("spr_box16", 16, 16, (8, 8), (0, 0, 15, 15))
_OBJECTS = (("o_mover", False), ("o_wall", True))


class TestMotionHelpersGodot(unittest.TestCase):
    def test_motion_variables_steps_and_move_helpers_follow_gamemaker(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="MotionHelpers",
                sprites=(_SPRITE,),
                objects=tuple(
                    object_entry(100 + index, name, object_scene_path(name))
                    for index, (name, _solid) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "motion_smoke.gd"},
                application_settings="config/gm2godot_collision_compatibility=true\n",
            )
            for name, solid in _OBJECTS:
                write_generated_object(project_dir, name, _SPRITE, solid=solid)
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("MOTION_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
