from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.collision_runtime_support import (
    CollisionSprite,
    MaskRect,
    object_entry,
    run_smoke_scene,
    write_collision_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_SPRITES = (
    CollisionSprite("spr_box16", 16, 16, (8, 8), (0, 0, 15, 15)),
    CollisionSprite("spr_box2", 2, 2, (0, 0), (0, 0, 1, 1)),
    CollisionSprite(
        "spr_dots",
        4,
        4,
        (0, 0),
        (0, 0, 3, 3),
        collision_kind=0,
        mask_rects=(MaskRect(0, 0, 1, 1), MaskRect(3, 3, 1, 1)),
    ),
    CollisionSprite(
        "spr_frames",
        2,
        2,
        (0, 0),
        (0, 0, 1, 1),
        collision_kind=4,
        mask_rects=(MaskRect(0, 0, 1, 1, frame=0), MaskRect(1, 1, 1, 1, frame=1)),
        frame_count=2,
    ),
    CollisionSprite("spr_ellipse", 8, 8, (0, 0), (0, 0, 7, 7), collision_kind=2),
    CollisionSprite("spr_diamond", 8, 8, (0, 0), (0, 0, 7, 7), collision_kind=3),
    CollisionSprite("spr_bar", 16, 4, (8, 2), (0, 0, 15, 3), collision_kind=5),
)


class TestCollisionQueriesGodot(unittest.TestCase):
    def test_collision_queries_follow_gamemaker_masks_and_modes(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="CollisionQueries",
                sprites=_SPRITES,
                objects=(
                    object_entry(100, "o_a"),
                    object_entry(101, "o_b"),
                    object_entry(102, "o_none"),
                    object_entry(103, "o_shape"),
                ),
                fixture_files={"smoke.gd": "queries_smoke.gd", "instance.gd": "instance.gd"},
                application_settings="config/gm2godot_collision_compatibility=true\n",
            )
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("COLLISION_QUERIES_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
