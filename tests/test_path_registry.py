from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

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
    def test_non_object_resource_rereads_fail_before_any_output(self) -> None:
        for root in ('[]', '"path"', 'true', 'false', '42', '1.25'):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
                sources = Path(gm_dir) / "paths"
                sources.mkdir()
                (sources / "valid.yy").write_text('{"points":[{"x":1,"y":2}]}', encoding="utf-8")
                malformed_source = sources / "replaced.yy"
                malformed_source.write_text(root, encoding="utf-8")
                output = Path(godot_dir)
                existing_registry = output / "gm2godot" / "gml_path_registry.gd"
                existing_registry.parent.mkdir()
                existing_registry.write_bytes(b"previous registry\n")
                entries = (
                    _AssetEntry(1, "valid", "paths", "paths/valid.yy", "res://paths/valid.tscn"),
                    _AssetEntry(2, "replaced", "paths", "paths/replaced.yy", "res://paths/replaced.tscn"),
                )

                with self.assertRaises(ValueError) as raised:
                    write_path_registry(gm_dir, godot_dir, entries)

                self.assertIn(str(malformed_source), str(raised.exception))
                self.assertIn("JSON object", str(raised.exception))
                self.assertEqual(existing_registry.read_bytes(), b"previous registry\n")
                self.assertEqual(tuple(output.rglob("*.tscn")), ())

    def test_null_invalid_json_and_unreadable_resources_still_skip(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir:
            sources = Path(gm_dir) / "paths"
            sources.mkdir()
            (sources / "null.yy").write_text("null", encoding="utf-8")
            (sources / "invalid.yy").write_text("{broken", encoding="utf-8")
            entries = tuple(
                _AssetEntry(index, name, "paths", f"paths/{name}.yy")
                for index, name in enumerate(("null", "invalid", "missing"))
            )
            self.assertEqual(build_path_registry_entries(gm_dir, entries), ())
            with patch("src.conversion.path_registry.open", side_effect=OSError("unreadable")):
                self.assertEqual(build_path_registry_entries(gm_dir, entries), ())

    def test_non_json_reader_failures_propagate_before_output(self) -> None:
        digit_limit = sys.get_int_max_str_digits()
        cases: list[tuple[bytes, type[Exception]]] = [
            (b"\xff", UnicodeDecodeError),
        ]
        if digit_limit:
            cases.append((b"1" * (digit_limit + 1), ValueError))
        for content, error_type in cases:
            with self.subTest(error_type=error_type), tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
                source = Path(gm_dir) / "path.yy"
                source.write_bytes(content)
                entry = _AssetEntry(1, "path", "paths", "path.yy", "res://paths/path.tscn")
                with self.assertRaises(error_type):
                    write_path_registry(gm_dir, godot_dir, (entry,))
                self.assertEqual(tuple(Path(godot_dir).iterdir()), ())
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            (Path(gm_dir) / "path.yy").write_text("{}", encoding="utf-8")
            entry = _AssetEntry(1, "path", "paths", "path.yy", "res://paths/path.tscn")
            failure = RecursionError("decoder nesting limit")
            with patch("src.conversion.path_registry.json.loads", side_effect=failure):
                with self.assertRaises(RecursionError) as raised:
                    write_path_registry(gm_dir, godot_dir, (entry,))
            self.assertIs(raised.exception, failure)
            self.assertEqual(tuple(Path(godot_dir).iterdir()), ())

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

    def test_skips_uncontained_path_metadata_sources(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside_yy = os.path.join(outside_dir, "path_outside.yy")
            with open(outside_yy, "w", encoding="utf-8") as source_file:
                source_file.write('{"name":"path_outside","points":[{"x":99,"y":99}]}')
            linked_dir = os.path.join(gm_dir, "paths", "path_linked")
            os.makedirs(linked_dir)
            linked_yy = os.path.join(linked_dir, "path_linked.yy")
            try:
                os.symlink(outside_yy, linked_yy)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            entries = build_path_registry_entries(
                gm_dir,
                (
                    _AssetEntry(1, "path_parent", "paths", "../../../outside.yy"),
                    _AssetEntry(
                        2,
                        "path_linked",
                        "paths",
                        "paths/path_linked/path_linked.yy",
                    ),
                ),
            )

        self.assertEqual(entries, ())


if __name__ == "__main__":
    unittest.main()
