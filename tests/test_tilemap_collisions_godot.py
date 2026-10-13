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

_CASES_PATH = FIXTURE_DIR / "tilemap_cases.json"


class _SpriteSpec(TypedDict):
    width: int
    height: int
    bbox: list[int]
    kind: int
    rects: list[list[int]]


class _InstanceSpriteSpec(_SpriteSpec):
    origin: list[int]


class _CasesSpec(TypedDict):
    tileset_sprites: dict[str, _SpriteSpec]
    instance_sprites: dict[str, _InstanceSpriteSpec]


def _sprite(name: str, spec: _SpriteSpec, origin: tuple[int, int]) -> CollisionSprite:
    left, top, right, bottom = spec["bbox"]
    return CollisionSprite(
        name,
        spec["width"],
        spec["height"],
        origin,
        (left, top, right, bottom),
        collision_kind=spec["kind"],
        mask_rects=tuple(MaskRect(x, y, width, height) for x, y, width, height in spec["rects"]),
    )


def _sprites() -> tuple[CollisionSprite, ...]:
    cases = cast(_CasesSpec, json.loads(_CASES_PATH.read_text(encoding="utf-8")))
    sprites = [_sprite(name, spec, (0, 0)) for name, spec in cases["tileset_sprites"].items()]
    for name, spec in cases["instance_sprites"].items():
        origin_x, origin_y = spec["origin"]
        sprites.append(_sprite(name, spec, (origin_x, origin_y)))
    return tuple(sprites)


class TestTilemapCollisionsGodot(unittest.TestCase):
    def test_collision_functions_test_tilemaps_like_the_gamemaker_runner(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="TilemapCollisions",
                sprites=_sprites(),
                objects=(object_entry(100, "o_probe"), object_entry(101, "o_wall")),
                fixture_files={
                    "smoke.gd": "tilemap_smoke.gd",
                    "instance.gd": "instance.gd",
                    "tilemap_cases.json": "tilemap_cases.json",
                },
            )
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("TILEMAP_COLLISIONS_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
