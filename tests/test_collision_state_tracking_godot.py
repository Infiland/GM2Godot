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

_WALL = CollisionSprite("spr_box16", 16, 16, (8, 8), (0, 0, 15, 15))
_POST = CollisionSprite("spr_post", 8, 24, (4, 12), (0, 0, 7, 23))
_PROBE = CollisionSprite("spr_probe", 10, 10, (5, 5), (0, 0, 9, 9))
_BIG = CollisionSprite("spr_big", 40, 40, (20, 20), (0, 0, 39, 39))
_THIN = CollisionSprite("spr_thin", 4, 30, (2, 15), (0, 0, 3, 29))
# o_post is a child of o_wall: o_wall's instance list holds both.
_OBJECTS: tuple[tuple[str, CollisionSprite, tuple[str, ...]], ...] = (
    ("o_wall", _WALL, ()),
    ("o_post", _POST, ("o_wall",)),
    ("o_probe", _PROBE, ()),
)


class TestCollisionStateTrackingGodot(unittest.TestCase):
    def _run_tracking_smoke(self, compatibility: bool) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="CollisionStateTracking",
                sprites=(_WALL, _POST, _PROBE, _BIG, _THIN),
                objects=tuple(
                    object_entry(100 + index, name, object_scene_path(name))
                    for index, (name, _sprite, _parents) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "tracking_smoke.gd"},
                application_settings=f"config/gm2godot_collision_compatibility={str(compatibility).lower()}\n",
            )
            for name, sprite, parents in _OBJECTS:
                write_generated_object(project_dir, name, sprite, parent_object_names=parents)
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("COLLISION_TRACKING_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)

    def test_kept_collision_states_match_states_built_from_scratch(self) -> None:
        self._run_tracking_smoke(compatibility=False)

    def test_kept_collision_states_match_in_compatibility_mode(self) -> None:
        self._run_tracking_smoke(compatibility=True)


if __name__ == "__main__":
    unittest.main()
