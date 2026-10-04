from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from src.conversion.json_values import JsonValueError
from src.conversion.path_registry import (
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


# Complete outputs captured from immutable main commit 5f512231031b86de2fcde6f2b7cded8423b5a83a.
_MAIN19_SCENE_BYTES = (
    '[gd_scene load_steps=2 format=3]\n'
    '\n'
    '[sub_resource type="Curve2D" id="Curve2D_1"]\n'
    '_data = {"points": PackedVector2Array(0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1.25, -2.5, 0, 0, 0, 0, 0, 0), "tilts": PackedFloat32Array(0, 0, 0)}\n'
    'point_count = 3\n'
    '\n'
    '[node name="supplied_walk" type="Path2D"]\n'
    'curve = SubResource("Curve2D_1")\n'
    'metadata/gamemaker_path_id = 901\n'
    'metadata/gamemaker_path_name = "supplied_walk"\n'
    'metadata/gamemaker_path_closed = true\n'
    'metadata/gamemaker_path_kind = 2\n'
    'metadata/gamemaker_path_precision = -3\n'
    'metadata/gamemaker_path_points = [{"x": 0.0, "y": 1.0, "speed": 0.0}, {"x": 1.25, "y": -2.5, "speed": 100.0}, {"x": 0.0, "y": 0.0, "speed": 100.0}]\n'
).encode("utf-8")

_MAIN19_REGISTRY_BYTES = (
    'extends RefCounted\n'
    '\n'
    'static func entries():\n'
    '\treturn [\n'
    '\t{\n'
    '\t\t"id": 901,\n'
    '\t\t"name": "supplied_walk",\n'
    '\t\t"closed": true,\n'
    '\t\t"kind": 2,\n'
    '\t\t"precision": -3,\n'
    '\t\t"godot_path": "res://paths/supplied_walk.tscn",\n'
    '\t\t"points": [\n'
    '\t\t\t{\n'
    '\t\t\t\t"x": 0.0,\n'
    '\t\t\t\t"y": 1.0,\n'
    '\t\t\t\t"speed": 0.0\n'
    '\t\t\t},\n'
    '\t\t\t{\n'
    '\t\t\t\t"x": 1.25,\n'
    '\t\t\t\t"y": -2.5,\n'
    '\t\t\t\t"speed": 100.0\n'
    '\t\t\t},\n'
    '\t\t\t{\n'
    '\t\t\t\t"x": 0.0,\n'
    '\t\t\t\t"y": 0.0,\n'
    '\t\t\t\t"speed": 100.0\n'
    '\t\t\t}\n'
    '\t\t]\n'
    '\t}\n'
    ']\n'
).encode("utf-8")


class _ObservedAssetEntry:
    kind = "paths"
    source_path = "path.yy"

    def __init__(self, events: list[str], failure: RuntimeError | None = None) -> None:
        self.events = events
        self.failure = failure

    @property
    def id(self) -> int:
        self.events.append("id")
        if self.failure is not None:
            raise self.failure
        return 901

    @property
    def name(self) -> str:
        self.events.append("name")
        return "supplied_walk"

    @property
    def godot_path(self) -> str:
        self.events.append("godot_path")
        return "res://paths/supplied_walk.tscn"


class TestTypedPathRegistry(unittest.TestCase):
    def test_generated_scene_and_registry_match_main19_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            source = Path(gm_dir) / "path.yy"
            source.write_text(
                '{"name":"source_name_ignored","closed":"false","kind":2.75,'
                '"precision":-3.75,"points":[{"x":false,"y":true,"speed":0},'
                '{"x":1.25,"y":-2.5},{},null,7,],}', encoding="utf-8",
            )
            supplied = _AssetEntry(901, "supplied_walk", "paths", "path.yy", "res://paths/supplied_walk.tscn")
            result = write_path_registry(gm_dir, godot_dir, (supplied,))
            self.assertEqual(Path(result).read_bytes(), _MAIN19_REGISTRY_BYTES)
            self.assertEqual((Path(godot_dir) / "paths" / "supplied_walk.tscn").read_bytes(), _MAIN19_SCENE_BYTES)

    def test_construction_errors_preserve_every_previous_output(self) -> None:
        huge = 10 ** 400
        cases: list[tuple[str, int | float, type[Exception]]] = [
            ("x", huge, OverflowError), ("y", huge, OverflowError),
            ("speed", huge, OverflowError), ("kind", huge, OverflowError),
            ("precision", huge, OverflowError), ("kind", float("nan"), ValueError),
            ("kind", float("inf"), OverflowError), ("precision", float("nan"), ValueError),
            ("precision", float("-inf"), OverflowError),
        ]
        for field, value, error in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
                root = Path(gm_dir)
                (root / "first.yy").write_text('{"points":[{"x":1,"y":2}]}', encoding="utf-8")
                point: dict[str, int | float] = {"x": 1, "y": 2, "speed": 100}
                data: dict[str, int | float | list[dict[str, int | float]]] = {"points": [point]}
                if field in ("x", "y", "speed"):
                    point[field] = value
                else:
                    data[field] = value
                (root / "bad.yy").write_text(json.dumps(data), encoding="utf-8")
                output = Path(godot_dir)
                previous = {"gm2godot/gml_path_registry.gd": b"previous registry\n", "paths/first.tscn": b"previous first\n", "paths/bad.tscn": b"previous bad\n"}
                for name, content in previous.items():
                    path = output / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                entries = (_AssetEntry(1, "first", "paths", "first.yy", "res://paths/first.tscn"), _AssetEntry(2, "bad", "paths", "bad.yy", "res://paths/bad.tscn"))
                with self.assertRaises(error):
                    write_path_registry(gm_dir, godot_dir, entries)
                actual = {str(path.relative_to(output)).replace(os.sep, "/"): path.read_bytes() for path in output.rglob("*") if path.is_file()}
                self.assertEqual(actual, previous)

    def test_coordinate_nonfinite_errors_keep_render_time_mutation_order(self) -> None:
        cases = (("x", float("nan"), ValueError), ("x", float("inf"), OverflowError), ("y", float("nan"), ValueError), ("y", float("-inf"), OverflowError))
        for field, value, error in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
                root = Path(gm_dir)
                for name in ("first", "last"):
                    (root / f"{name}.yy").write_text('{"points":[{"x":1,"y":2}]}', encoding="utf-8")
                point = {"x": 1.0, "y": 2.0, field: value}
                (root / "bad.yy").write_text(json.dumps({"points": [point]}), encoding="utf-8")
                output = Path(godot_dir)
                registry = output / "gm2godot" / "gml_path_registry.gd"
                registry.parent.mkdir()
                registry.write_bytes(b"previous registry\n")
                bad_scene = output / "paths" / "bad.tscn"
                bad_scene.parent.mkdir()
                bad_scene.write_bytes(b"previous bad scene\n")
                entries = tuple(_AssetEntry(index, name, "paths", f"{name}.yy", f"res://paths/{name}.tscn") for index, name in enumerate(("first", "bad", "last")))
                with self.assertRaises(error):
                    write_path_registry(gm_dir, godot_dir, entries)
                self.assertIn('[node name="first" type="Path2D"]', (output / "paths" / "first.tscn").read_text())
                self.assertEqual(bad_scene.read_bytes(), b"")
                self.assertFalse((output / "paths" / "last.tscn").exists())
                self.assertEqual(registry.read_bytes(), b"previous registry\n")

    def test_nonfinite_speed_is_serialized_and_negative_zero_stays_in_metadata(self) -> None:
        for value, spelling in ((float("nan"), "NaN"), (float("inf"), "Infinity"), (float("-inf"), "-Infinity")):
            with self.subTest(spelling=spelling), tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
                (Path(gm_dir) / "path.yy").write_text(json.dumps({"points": [{"x": 1.25, "y": -0.0, "speed": value}]}), encoding="utf-8")
                entry = _AssetEntry(1, "path", "paths", "path.yy", "res://paths/path.tscn")
                registry = Path(write_path_registry(gm_dir, godot_dir, (entry,))).read_text()
                scene = (Path(godot_dir) / "paths" / "path.tscn").read_text()
                self.assertIn(f'"speed": {spelling}', registry)
                self.assertIn(f'"speed": {spelling}', scene)
                self.assertIn('"y": -0.0', registry)
                self.assertIn('"y": -0.0', scene)
                self.assertIn("PackedVector2Array(0, 0, 0, 0, 1.25, 0)", scene)

    def test_point_conversions_and_asset_properties_keep_failure_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir:
            source = Path(gm_dir) / "path.yy"
            events: list[str] = []
            failure = RuntimeError("asset id unavailable")
            entry = _ObservedAssetEntry(events, failure)
            source.write_text('{"kind":NaN,"points":[{"x":1,"y":2}]}', encoding="utf-8")
            with self.assertRaises(RuntimeError) as raised:
                build_path_registry_entries(gm_dir, (entry,))
            self.assertIs(raised.exception, failure)
            self.assertEqual(events, ["id"])
            events.clear()
            source.write_text(json.dumps({"points": [{"x": 10 ** 400}]}), encoding="utf-8")
            with self.assertRaises(OverflowError):
                build_path_registry_entries(gm_dir, (entry,))
            self.assertEqual(events, [])
            entry.failure = None
            source.write_text('{"kind":NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                build_path_registry_entries(gm_dir, (entry,))
            self.assertEqual(events, ["id", "name"])
            events.clear()
            source.write_text('{}', encoding="utf-8")
            result = build_path_registry_entries(gm_dir, (entry,))
            self.assertEqual(events, ["id", "name", "godot_path"])
            self.assertEqual(result[0].points, ())

    def test_open_and_decoder_controls_keep_original_exception_identity(self) -> None:
        errors: tuple[BaseException, ...] = (TypeError("type"), ValueError("value"), RecursionError("depth"), KeyboardInterrupt(), SystemExit(37))
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            (Path(gm_dir) / "path.yy").write_text('{}', encoding="utf-8")
            entry = _AssetEntry(1, "path", "paths", "path.yy", "res://paths/path.tscn")
            for seam in ("src.conversion.path_registry.open", "src.conversion.path_registry.json.loads"):
                for error in errors:
                    with self.subTest(seam=seam, error=type(error)), patch(seam, side_effect=error):
                        with self.assertRaises(type(error)) as raised:
                            write_path_registry(gm_dir, godot_dir, (entry,))
                        self.assertIs(raised.exception, error)
                        self.assertEqual(tuple(Path(godot_dir).iterdir()), ())

    def test_injected_nonjson_document_is_validated_before_outputs(self) -> None:
        cycle: list[object] = []
        cycle.append(cycle)
        invalid_set: set[str] = set()
        cases: tuple[object, ...] = ({"extra": {"bad": invalid_set}}, {1: "nonstring key"}, {"extra": cycle})
        with tempfile.TemporaryDirectory() as gm_dir, tempfile.TemporaryDirectory() as godot_dir:
            source = Path(gm_dir) / "path.yy"
            source.write_text('{}', encoding="utf-8")
            entry = _AssetEntry(1, "path", "paths", "path.yy", "res://paths/path.tscn")
            for document in cases:
                with self.subTest(document_type=type(document)), patch("src.conversion.path_registry.json.loads", return_value=document):
                    with self.assertRaises(JsonValueError) as raised:
                        write_path_registry(gm_dir, godot_dir, (entry,))
                    self.assertEqual(raised.exception.source_path, str(source))
                    self.assertEqual(tuple(Path(godot_dir).iterdir()), ())

    def test_contained_nonfamily_sources_and_aliases_keep_existing_registry_policy(self) -> None:
        with tempfile.TemporaryDirectory() as gm_dir:
            root = Path(gm_dir)
            target = root / "objects" / "source.txt"
            target.parent.mkdir()
            target.write_text('{"points":[{"x":17,"y":23}]}', encoding="utf-8")
            direct = _AssetEntry(1, "direct", "paths", "objects/source.txt")
            self.assertEqual(build_path_registry_entries(gm_dir, (direct,))[0].points[0].x, 17.0)
            alias = root / "paths" / "alias.yy"
            alias.parent.mkdir()
            try:
                alias.symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            entry = _AssetEntry(2, "alias", "paths", "paths/alias.yy")
            points = build_path_registry_entries(gm_dir, (entry,))[0].points
            self.assertEqual([(point.x, point.y, point.speed) for point in points], [(17.0, 23.0, 100.0)])


if __name__ == "__main__":
    unittest.main()
