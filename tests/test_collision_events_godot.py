from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.conversion.json_values import JsonObject
from src.conversion.script_generator import (
    ObjectRuntimeConfig,
    SpriteRuntimeConfig,
    generate_script_content,
)
from tests.collision_runtime_support import (
    CollisionSprite,
    object_entry,
    run_smoke_scene,
    sprite_resource_path,
    write_collision_project,
)
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_SPRITE = CollisionSprite("spr_box16", 16, 16, (8, 8), (0, 0, 15, 15))

# Objects in asset order, with their parent, solidity and collision events
# (target object -> event body). The events report back to the smoke scene.
_OBJECTS: tuple[tuple[str, str | None, bool, dict[str, str]], ...] = (
    ("o_par", None, False, {"o_c": '\tget_parent().record("par:c", self, other)'}),
    (
        "o_a",
        None,
        False,
        {
            "o_par": '\tget_parent().record("a:par", self, other)',
            "o_b": (
                '\tget_parent().record("a:b", self, other)\n'
                '\tif label == "killer":\n'
                "\t\tGMRuntime.gml_instance_destroy(self)\n"
                '\tif label == "spawner":\n'
                '\t\tget_parent().spawn("o_b", "spawned", position.x, position.y)'
            ),
        },
    ),
    ("o_b", None, False, {"o_a": '\tget_parent().record("b:a", self, other)'}),
    ("o_child", "o_par", False, {"o_a": '\tget_parent().record("child:a", self, other)'}),
    ("o_wall", None, True, {"o_a": '\tget_parent().record("wall:a", self, other)'}),
    ("o_same", None, False, {"o_same": '\tget_parent().record("same", self, other)'}),
    ("o_c", None, False, {}),
)


def _collision_event(target: str) -> JsonObject:
    return {
        "eventType": 4,
        "eventNum": 0,
        "collisionObjectId": {"name": target, "path": f"objects/{target}/{target}.yy"},
    }


def _write_objects(project_dir: Path) -> None:
    sprite_scenes = {_SPRITE.name: sprite_resource_path(_SPRITE.name)}
    for name, parent, solid, events in _OBJECTS:
        script = generate_script_content(
            [_collision_event(target) for target in events],
            code_bodies={f"_on_collision_{target}": body for target, body in events.items()},
            instance_variables=() if parent else ("label",),
            sprite_runtime=SpriteRuntimeConfig(
                initial_sprite_name=_SPRITE.name,
                sprite_scene_paths=sprite_scenes,
                inherit_runtime=parent is not None,
            ),
            object_runtime=ObjectRuntimeConfig(
                object_name=name,
                parent_object_names=(parent,) if parent else (),
                solid=solid,
                inherit_ready=parent is not None,
                inherit_exit_tree=parent is not None,
            ),
            base_script_path=f"res://objects/{parent}/{parent}.gd" if parent else None,
        )
        write_fixture_text(project_dir / "objects" / name / f"{name}.gd", script)


class TestCollisionEventsGodot(unittest.TestCase):
    def test_generated_collision_events_follow_the_gamemaker_runner(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_collision_project(
                project_dir,
                project_name="CollisionEvents",
                sprites=(_SPRITE,),
                objects=tuple(
                    object_entry(100 + index, name) for index, (name, *_rest) in enumerate(_OBJECTS)
                ),
                fixture_files={"smoke.gd": "events_smoke.gd"},
                application_settings="config/gm2godot_collision_compatibility=true\n",
            )
            _write_objects(project_dir)
            result = run_smoke_scene(godot_binary, project_dir)
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("COLLISION_EVENTS_OK", output)
        self.assertNotIn("SCRIPT ERROR:", output)
        self.assertNotIn("ERROR:", output)
        self.assertNotIn("WARNING:", output)


if __name__ == "__main__":
    unittest.main()
