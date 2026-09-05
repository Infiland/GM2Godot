from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from src.conversion.path_registry import (
    PathPoint,
    PathRegistryEntry,
    build_path_registry_entries,
    render_path_registry_script,
    render_path_scene,
    write_path_registry,
)


@dataclass(frozen=True)
class _AssetEntry:
    id: int
    name: str
    kind: str
    source_path: str
    godot_path: str = ""


def _path_asset(project: Path, name: str, source: str) -> _AssetEntry:
    relative = f"paths/{name}/{name}.yy"
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return _AssetEntry(7, name, "paths", relative, f"res://paths/{name}/{name}.tscn")


class TestPathRegistry(unittest.TestCase):
    def test_consumes_one_shot_entries_in_order_with_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            first = _path_asset(project, "first", '{"points":[{"x":1}]}')
            second = _path_asset(project, "second", '{"points":[{"x":2}]}')
            source = iter((first, replace(first, kind="Paths"), second, first))
            entries = build_path_registry_entries(temporary, source)

        self.assertEqual(list(source), [])
        self.assertEqual([entry.name for entry in entries], ["first", "second", "first"])
        self.assertEqual([entry.id for entry in entries], [7, 7, 7])
        self.assertEqual([entry.points[0].x for entry in entries], [1.0, 2.0, 1.0])
        self.assertEqual(entries[0], entries[2])

    def test_build_failure_precedes_any_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = _path_asset(root / "gm", "good", '{"points":[{"x":1,"y":2}]}')
            bad = _path_asset(root / "gm", "bad", '{"kind":NaN}')
            output = root / "out"
            output.mkdir()
            seed = output / "prior.tscn"
            seed.write_bytes(b"prior scene\r\n")
            with self.assertRaisesRegex(ValueError, "cannot convert float NaN to integer"):
                write_path_registry(str(root / "gm"), str(output), (good, bad))
            self.assertEqual([path.name for path in output.iterdir()], ["prior.tscn"])
            self.assertEqual(seed.read_bytes(), b"prior scene\r\n")

    def test_scene_failure_preserves_exact_partial_write_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = _path_asset(root / "gm", "good", '{"points":[{"x":1,"y":2}]}')
            bad = _path_asset(root / "gm", "bad", '{"points":[{"x":NaN}]}')
            output = root / "out"
            failed_scene = output / "paths/bad/bad.tscn"
            failed_scene.parent.mkdir(parents=True)
            failed_scene.write_bytes(b"old scene")
            registry = output / "gm2godot/gml_path_registry.gd"
            registry.parent.mkdir()
            registry.write_bytes(b"old registry\r\n")
            with self.assertRaisesRegex(ValueError, "cannot convert float NaN to integer"):
                write_path_registry(str(root / "gm"), str(output), (good, bad))
            expected = PathRegistryEntry(7, "good", False, 0, 4, good.godot_path, (PathPoint(1.0, 2.0),))
            self.assertEqual(
                (output / "paths/good/good.tscn").read_bytes(),
                render_path_scene(expected).replace("\n", os.linesep).encode("utf-8"),
            )
            self.assertEqual(failed_scene.read_bytes(), b"")
            self.assertEqual(registry.read_bytes(), b"old registry\r\n")
            self.assertEqual(
                sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()),
                ["gm2godot/gml_path_registry.gd", "paths/bad/bad.tscn", "paths/good/good.tscn"],
            )

    def test_registry_failure_follows_completed_scene_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = _path_asset(root / "gm", "good", '{"points":[{"x":1,"y":2}]}')
            output = root / "out"
            registry = output / "gm2godot/gml_path_registry.gd"
            registry.mkdir(parents=True)
            with self.assertRaises(OSError):
                write_path_registry(str(root / "gm"), str(output), (asset,))
            expected = PathRegistryEntry(7, "good", False, 0, 4, asset.godot_path, (PathPoint(1.0, 2.0),))
            self.assertEqual(
                (output / "paths/good/good.tscn").read_bytes(),
                render_path_scene(expected).replace("\n", os.linesep).encode("utf-8"),
            )
            self.assertTrue(registry.is_dir())
            self.assertEqual(list(registry.iterdir()), [])

    def test_native_bytes_and_non_resource_scene_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = _path_asset(root / "gm", "good", '{"points":[{"x":1,"y":2}]}')
            external = replace(asset, id=8, name="alias", godot_path="outside.tscn")
            empty = replace(asset, id=9, name="empty", godot_path="")
            output = root / "out"
            registry_path = write_path_registry(str(root / "gm"), str(output), (asset, external, empty))
            expected = PathRegistryEntry(7, "good", False, 0, 4, asset.godot_path, (PathPoint(1.0, 2.0),))
            expected_entries = (
                expected,
                replace(expected, id=8, name="alias", godot_path="outside.tscn"),
                replace(expected, id=9, name="empty", godot_path=""),
            )
            self.assertEqual(
                Path(registry_path).read_bytes(),
                render_path_registry_script(expected_entries).replace("\n", os.linesep).encode("utf-8"),
            )
            self.assertEqual(
                (output / "paths/good/good.tscn").read_bytes(),
                render_path_scene(expected).replace("\n", os.linesep).encode("utf-8"),
            )
            self.assertEqual(
                sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()),
                ["gm2godot/gml_path_registry.gd", "paths/good/good.tscn"],
            )

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
