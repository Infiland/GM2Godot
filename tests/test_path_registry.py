from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass

from src.conversion.path_registry import (
    build_path_registry_entries,
    render_path_registry_script,
    write_path_registry,
)


@dataclass(frozen=True)
class _AssetEntry:
    id: int
    name: str
    kind: str
    source_path: str


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
                    '  "precision": 4,\n'
                    '  "points": [\n'
                    '    {"x": 0, "y": 0, "speed": 100,},\n'
                    '    {"x": 32, "y": 0, "speed": 80,},\n'
                    '  ],\n'
                    '}\n'
                )

            entries = build_path_registry_entries(
                tmpdir,
                (_AssetEntry(100, "path_patrol", "paths", "paths/path_patrol/path_patrol.yy"),),
            )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.id, 100)
        self.assertEqual(entry.name, "path_patrol")
        self.assertFalse(entry.closed)
        self.assertEqual([(point.x, point.y, point.speed) for point in entry.points], [(0.0, 0.0, 100.0), (32.0, 0.0, 80.0)])

    def test_renders_and_writes_path_registry_script(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            path_dir = os.path.join(gm_dir, "paths", "path_patrol")
            os.makedirs(path_dir)
            with open(os.path.join(path_dir, "path_patrol.yy"), "w", encoding="utf-8") as f:
                f.write('{"name":"path_patrol","closed":true,"points":[{"x":1,"y":2}]}\n')

            path = write_path_registry(
                gm_dir,
                godot_dir,
                (_AssetEntry(101, "path_patrol", "paths", "paths/path_patrol/path_patrol.yy"),),
            )
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("extends RefCounted", content)
        self.assertIn('"id": 101', content)
        self.assertIn('"name": "path_patrol"', content)
        self.assertIn('"closed": true', content)
        self.assertEqual(render_path_registry_script(()), "extends RefCounted\n\nstatic func entries():\n\treturn []\n")


if __name__ == "__main__":
    unittest.main()
