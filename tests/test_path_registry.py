from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass

from src.conversion.path_registry import (
    build_path_registry_entries,
    render_path_scene,
    render_path_registry_script,
    write_path_registry,
)


@dataclass(frozen=True)
class _AssetEntry:
    id: int
    name: str
    kind: str
    source_path: str
    godot_path: str = ""


class TestPathRegistry(unittest.TestCase):
    def test_builds_path_registry_entries_from_gamemaker_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path_dir = os.path.join(tmpdir, "paths", "path_patrol")
            os.makedirs(path_dir)
            with open(os.path.join(path_dir, "path_patrol.yy"), "w", encoding="utf-8") as f:
                f.write(
                    '{\n'
                    '  "name": "path_patrol",\n'
                    '  "closed": false,\n'
                    '  "kind": 1,\n'
                    '  "precision": 4,\n'
                    '  "points": [\n'
                    '    {"x": 0, "y": 0, "speed": 100,},\n'
                    '    {"x": 32, "y": 0, "speed": 80,},\n'
                    '  ],\n'
                    '}\n'
                )

            entries = build_path_registry_entries(
                tmpdir,
                (
                    _AssetEntry(
                        100,
                        "path_patrol",
                        "paths",
                        "paths/path_patrol/path_patrol.yy",
                        "res://paths/path_patrol/path_patrol.tscn",
                    ),
                ),
            )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.id, 100)
        self.assertEqual(entry.name, "path_patrol")
        self.assertFalse(entry.closed)
        self.assertEqual(entry.kind, 1)
        self.assertEqual(entry.godot_path, "res://paths/path_patrol/path_patrol.tscn")
        self.assertEqual([(point.x, point.y, point.speed) for point in entry.points], [(0.0, 0.0, 100.0), (32.0, 0.0, 80.0)])
        scene = render_path_scene(entry)
        self.assertIn('[node name="path_patrol" type="Path2D"]', scene)
        self.assertIn('[sub_resource type="Curve2D" id="Curve2D_1"]', scene)
        self.assertIn("metadata/gamemaker_path_kind = 1", scene)

    def test_renders_and_writes_path_registry_script(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            path_dir = os.path.join(gm_dir, "paths", "path_patrol")
            os.makedirs(path_dir)
            with open(os.path.join(path_dir, "path_patrol.yy"), "w", encoding="utf-8") as f:
                f.write('{"name":"path_patrol","closed":true,"points":[{"x":1,"y":2}]}\n')

            path = write_path_registry(
                gm_dir,
                godot_dir,
                (
                    _AssetEntry(
                        101,
                        "path_patrol",
                        "paths",
                        "paths/path_patrol/path_patrol.yy",
                        "res://paths/path_patrol/path_patrol.tscn",
                    ),
                ),
            )
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            scene_exists = os.path.isfile(
                os.path.join(godot_dir, "paths", "path_patrol", "path_patrol.tscn")
            )

        self.assertIn("extends RefCounted", content)
        self.assertIn('"id": 101', content)
        self.assertIn('"name": "path_patrol"', content)
        self.assertIn('"closed": true', content)
        self.assertIn('"godot_path": "res://paths/path_patrol/path_patrol.tscn"', content)
        self.assertTrue(scene_exists)
        self.assertEqual(render_path_registry_script(()), "extends RefCounted\n\nstatic func entries():\n\treturn []\n")


if __name__ == "__main__":
    unittest.main()
