from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from src.conversion.asset_registry import AssetRegistryEntry
from src.conversion.gamemaker_json import parse_gamemaker_json
from src.conversion.path_model import PathModel, PathPoint
from src.conversion.path_registry import build_path_registry_entries
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.resource_models import parse_gamemaker_resource_models
from tests.test_path_model import (
    ERROR_ORDER_CASES,
    NUMERIC_CASES,
    NUMERIC_FIELDS,
    numeric_path_error,
    numeric_path_payload,
)

RESOURCE_MATRIX = Path(__file__).resolve().parent / "fixtures/part2/projects/resource_matrix"


class TestPathModelConsumers(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.yy = self.project / "paths/p/p.yy"
        self.yy.parent.mkdir(parents=True)
        self.yyp = self.project / "P.yyp"
        self.yyp.write_text(
            '{"name":"P","resources":[{"id":{"name":"p","path":"paths/p/p.yy"}}]}',
            encoding="utf-8",
        )
        self.asset = AssetRegistryEntry(
            id=7,
            name="p",
            kind="paths",
            asset_type="path",
            type_name="Path",
            source_path="paths/p/p.yy",
            godot_path="res://paths/p/p.tscn",
            legacy_id="paths/p/p.yy",
        )

    def test_aggregate_uses_canonical_shape_and_live_raw_identity(self) -> None:
        self.yy.write_text('{"points":[{"x":1,"y":2}]}', encoding="utf-8")
        document = parse_gamemaker_json(self.yy.read_text(encoding="utf-8"))
        manifest = load_gamemaker_project_manifest(str(self.project))
        with (
            patch("src.conversion.resource_models.load_gamemaker_project_manifest", return_value=manifest),
            patch("src.conversion.resource_models.read_gamemaker_json", return_value=document) as reader,
        ):
            models = parse_gamemaker_resource_models(str(self.project))
        self.assertIs(models.project, manifest)
        self.assertEqual(models.diagnostics, ())
        model = models.paths[0]
        self.assertIs(type(model), PathModel)
        self.assertIs(model.raw_data, document.value)
        self.assertEqual(model.source_path, "paths/p/p.yy")
        self.assertEqual((model.name, model.points, model.kind, model.precision), ("p", (PathPoint(1.0, 2.0),), 0, 4))
        self.assertEqual(
            set(asdict(model)), {"name", "source_path", "raw_data", "points", "closed", "kind", "precision"}
        )
        reader.assert_called_once_with(str(self.yy))

    def test_registry_projects_canonical_points_without_reparsing(self) -> None:
        self.yy.write_text('{"points":[{"x":1,"y":2}]}', encoding="utf-8")
        points = (PathPoint(17.0, 19.0, 23.0),)
        model = PathModel("canonical", "paths/p/p.yy", {}, points, True, 2, 8)
        with patch("src.conversion.path_registry.parse_path_model", return_value=model) as parser:
            entries = build_path_registry_entries(str(self.project), (self.asset,))
        parser.assert_called_once_with({"points": [{"x": 1, "y": 2}]}, name="p", source_path="paths/p/p.yy")
        entry = entries[0]
        self.assertIs(entry.points, points)
        self.assertEqual(
            entry.to_godot_dict(),
            {
                "id": 7,
                "name": "canonical",
                "closed": True,
                "kind": 2,
                "precision": 8,
                "godot_path": "res://paths/p/p.tscn",
                "points": [{"x": 17.0, "y": 19.0, "speed": 23.0}],
            },
        )

    def test_reader_root_and_encoding_error_policies(self) -> None:
        cases: tuple[tuple[str, bytes | None, type[Exception] | None], ...] = (
            ("array", b"[]", ValueError),
            ("string", b'"x"', ValueError),
            ("boolean", b"true", ValueError),
            ("integer", b"1", ValueError),
            ("float", b"1.25", ValueError),
            ("nan-number", b"NaN", ValueError),
            ("positive-infinity-number", b"Infinity", ValueError),
            ("negative-infinity-number", b"-Infinity", ValueError),
            ("null", b"null", None),
            ("malformed", b"{", None),
            ("missing", None, None),
            ("bad-utf8", b"\xff", UnicodeDecodeError),
            ("digit-limit", b"1" * 5000, ValueError),
            ("recursion", b"[" * 20000 + b"0" + b"]" * 20000, RecursionError),
        )
        for name, payload, error in cases:
            with self.subTest(case=name):
                if payload is None:
                    self.yy.unlink(missing_ok=True)
                else:
                    self.yy.write_bytes(payload)
                if error is None:
                    self.assertEqual(build_path_registry_entries(str(self.project), (self.asset,)), ())
                else:
                    with self.assertRaises(error) as raised:
                        build_path_registry_entries(str(self.project), (self.asset,))
                    if name not in ("bad-utf8", "digit-limit", "recursion"):
                        self.assertEqual(
                            str(raised.exception), "GameMaker path resource must be an object: paths/p/p.yy"
                        )
                if name == "recursion":
                    with self.assertRaises(RecursionError):
                        parse_gamemaker_resource_models(str(self.project))
                else:
                    models = parse_gamemaker_resource_models(str(self.project))
                    self.assertEqual(models.paths, ())
                    diagnostics = [d for d in models.diagnostics if d.resource_kind == "paths"]
                    self.assertEqual(len(diagnostics), 1)
                    self.assertEqual(diagnostics[0].code, "GM2GD-RESOURCE-YY-MISSING")
                    self.assertEqual(diagnostics[0].message, f"Could not parse GameMaker resource .yy: {self.yy}")

    def test_aggregate_numeric_errors_precede_missing_resource_diagnostics(self) -> None:
        for field in NUMERIC_FIELDS:
            for label, value in NUMERIC_CASES:
                self.yy.write_text(json.dumps(numeric_path_payload(field, label, value)), encoding="utf-8")
                expected = numeric_path_error(field, label)
                if expected is not None:
                    with self.subTest(field=field, value=label), self.assertRaisesRegex(*expected):
                        parse_gamemaker_resource_models(str(self.project))
                    with self.assertRaisesRegex(*expected):
                        build_path_registry_entries(str(self.project), (self.asset,))
                    continue
                with self.subTest(field=field, value=label):
                    models = parse_gamemaker_resource_models(str(self.project))
                    entry = build_path_registry_entries(str(self.project), (self.asset,))[0]
                    model = models.paths[0]
                    self.assertEqual(models.diagnostics, ())
                    self.assertEqual(
                        (model.closed, model.kind, model.precision), (entry.closed, entry.kind, entry.precision)
                    )
                    self.assertEqual(
                        json.dumps([point.to_godot_dict() for point in model.points]),
                        json.dumps([point.to_godot_dict() for point in entry.points]),
                    )
        for data, error, message in ERROR_ORDER_CASES:
            self.yy.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(data=data), self.assertRaisesRegex(error, message):
                parse_gamemaker_resource_models(str(self.project))
            with self.assertRaisesRegex(error, message):
                build_path_registry_entries(str(self.project), (self.asset,))

    def test_shared_json_quirks_unknown_values_and_source_containment(self) -> None:
        self.yy.write_text(
            '{"points":[{"x":1,"y":2,},],"unknown":{"text":"comma, }","values":[null,],},}',
            encoding="utf-8",
        )
        model = parse_gamemaker_resource_models(str(self.project)).paths[0]
        self.assertEqual(model.raw_data["unknown"], {"text": "comma}", "values": [None]})
        self.assertEqual(model.points, (PathPoint(1.0, 2.0),))
        self.assertEqual(build_path_registry_entries(str(self.project), (self.asset,))[0].points, model.points)
        outside = replace(self.asset, source_path="../outside.yy")
        self.assertEqual(build_path_registry_entries(str(self.project), (outside,)), ())
        self.yyp.write_text(
            '{"name":"P","resources":[{"id":{"name":"p","path":"../outside.yy"}}]}',
            encoding="utf-8",
        )
        rejected = parse_gamemaker_resource_models(str(self.project))
        self.assertEqual(rejected.paths, ())
        self.assertEqual([d.code for d in rejected.diagnostics], ["GM2GD-SOURCE-PATH-REJECTED"])

    def test_resource_matrix_and_empty_project_preserve_other_families(self) -> None:
        matrix = parse_gamemaker_resource_models(str(RESOURCE_MATRIX))
        model = matrix.paths[0]
        asset = replace(self.asset, name="path_patrol", source_path="paths/path_patrol/path_patrol.yy")
        entry = build_path_registry_entries(str(RESOURCE_MATRIX), (asset,))[0]
        expected = (PathPoint(0.0, 0.0), PathPoint(64.0, 0.0), PathPoint(64.0, 64.0))
        self.assertEqual(model.points, expected)
        self.assertEqual(entry.points, expected)
        self.assertEqual((model.closed, model.kind, model.precision, model.point_count), (True, 1, 4, 3))
        self.assertEqual(matrix.diagnostics, ())
        other_records = asdict(matrix)
        del other_records["paths"], other_records["project"]
        # Only absolute file paths in this fixed fixture vary by checkout and host.
        encoded = json.dumps(other_records, sort_keys=True)
        encoded = encoded.replace(json.dumps(str(RESOURCE_MATRIX))[1:-1], "<fixture>")
        if os.sep == "\\":
            encoded = encoded.replace("\\\\", "/")
        self.assertEqual(
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "651ad1121c018bae0ede16519da370d0c5e567e1f37127702aa25cefbd813622",
        )
        self.yyp.write_text('{"name":"Empty","resources":[]}', encoding="utf-8")
        empty = parse_gamemaker_resource_models(str(self.project))
        self.assertEqual((empty.project.project_name, empty.paths, empty.diagnostics), ("Empty", (), ()))
        self.yy.write_text('{"name":"ignored","points":[]}', encoding="utf-8")
        self.assertEqual(build_path_registry_entries(str(self.project), (self.asset,))[0].name, "p")
