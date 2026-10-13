from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.collision_runtime_support import (
    CollisionSprite,
    MaskRect,
    object_entry,
    object_scene_path,
    run_smoke_scene,
    write_collision_project,
    write_generated_object,
)
from tests.godot_test_support import find_smoke_godot_binary

_BOX = CollisionSprite("spr_box16", 16, 16, (8, 8), (0, 0, 15, 15))
# A precise mask with only two opaque corners.
_CORNERS = CollisionSprite(
    "spr_corners",
    32,
    32,
    (0, 0),
    (0, 0, 31, 31),
    collision_kind=0,
    mask_rects=(MaskRect(0, 0, 4, 4), MaskRect(28, 28, 4, 4)),
)
_OBJECTS = (
    ("o_mover", False, _BOX),
    ("o_wall", True, _BOX),
    ("o_block", False, _BOX),
    ("o_corners", False, _CORNERS),
)


class TestMotionPlanningStepsGodot(unittest.TestCase):
    def test_move_and_collide_mp_steps_and_grid_instances_follow_gamemaker(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="MotionPlanningSteps",
                sprites=(_BOX, _CORNERS),
                objects=tuple(
                    object_entry(100 + index, name, object_scene_path(name))
                    for index, (name, _solid, _sprite) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "motion_planning_smoke.gd"},
            )
            for name, solid, sprite in _OBJECTS:
                write_generated_object(project_dir, name, sprite, solid=solid)
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("MOTION_PLANNING_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
