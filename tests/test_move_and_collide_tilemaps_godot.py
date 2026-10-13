from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast

from tests.collision_runtime_support import (
    FIXTURE_DIR,
    CollisionSprite,
    MaskRect,
    object_entry,
    run_smoke_scene,
    write_collision_project,
)
from tests.godot_test_support import find_smoke_godot_binary

_CASES_PATH = FIXTURE_DIR / "move_and_collide_tilemap_cases.json"


class _SpriteSpec(TypedDict):
    width: int
    height: int
    origin: list[int]
    bbox: list[int]
    kind: int
    rects: list[list[int]]


class _CasesSpec(TypedDict):
    sprites: dict[str, _SpriteSpec]


def _sprites() -> tuple[CollisionSprite, ...]:
    cases = cast(_CasesSpec, json.loads(_CASES_PATH.read_text(encoding="utf-8")))
    sprites: list[CollisionSprite] = []
    for name, spec in cases["sprites"].items():
        origin_x, origin_y = spec["origin"]
        left, top, right, bottom = spec["bbox"]
        sprites.append(
            CollisionSprite(
                name,
                spec["width"],
                spec["height"],
                (origin_x, origin_y),
                (left, top, right, bottom),
                collision_kind=spec["kind"],
                mask_rects=tuple(MaskRect(x, y, width, height) for x, y, width, height in spec["rects"]),
            )
        )
    return tuple(sprites)


class TestMoveAndCollideTilemapsGodot(unittest.TestCase):
    def test_motion_functions_collide_with_tilemaps_like_the_gamemaker_runner(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="MoveAndCollideTilemaps",
                sprites=_sprites(),
                objects=(object_entry(100, "o_wall"), object_entry(101, "o_actor")),
                fixture_files={
                    "smoke.gd": "move_and_collide_tilemaps_smoke.gd",
                    "instance.gd": "instance.gd",
                    "move_and_collide_tilemap_cases.json": "move_and_collide_tilemap_cases.json",
                },
            )
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("MOVE_AND_COLLIDE_TILEMAPS_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
