from __future__ import annotations

import ast
import inspect
import math
import pickle
import unittest
from dataclasses import FrozenInstanceError, asdict, astuple, fields
from pathlib import Path

from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.path_model import PathModel, PathPoint, parse_path_model
from src.conversion.path_registry import PathPoint as RegistryPathPoint
from src.conversion.resource_models import PathModel as ResourcePathModel

NUMERIC_FIELDS = ("x", "y", "speed", "kind", "precision")
NUMERIC_CASES: tuple[tuple[str, JsonValue], ...] = (
    ("absent", None),
    ("null", None),
    ("false", False),
    ("true", True),
    ("zero", 0),
    ("negative-int", -2),
    ("fraction", 2.9),
    ("negative-zero", -0.0),
    ("numeric-string", "3"),
    ("text", "bad"),
    ("list", []),
    ("object", {}),
    ("huge-int", 10**400),
    ("negative-huge-int", -(10**400)),
    ("nan", float("nan")),
    ("positive-infinity", float("inf")),
    ("negative-infinity", -float("inf")),
    ("beyond-exact-float-int", 2**53 + 1),
    ("large-finite", 1e308),
)
ERROR_ORDER_CASES: tuple[tuple[JsonObject, type[Exception], str], ...] = (
    ({"points": [{"x": 10**400}], "kind": float("nan")}, OverflowError, "int too large to convert to float"),
    ({"points": [{"y": 10**400}], "precision": float("nan")}, OverflowError, "int too large to convert to float"),
    ({"points": [{"speed": 10**400}], "kind": float("nan")}, OverflowError, "int too large to convert to float"),
    ({"kind": float("nan"), "precision": float("inf")}, ValueError, "cannot convert float NaN to integer"),
    ({"kind": float("inf"), "precision": float("nan")}, OverflowError, "cannot convert float infinity to integer"),
    ({"points": [{}, {"x": 10**400}], "kind": float("nan")}, OverflowError, "int too large to convert to float"),
)


def numeric_path_payload(field: str, label: str, value: JsonValue) -> JsonObject:
    point: JsonObject = {}
    data: JsonObject = {"points": [point]}
    if label != "absent":
        if field in ("x", "y", "speed"):
            point[field] = value
        else:
            data[field] = value
    return data


def numeric_path_error(field: str, label: str) -> tuple[type[Exception], str] | None:
    if label in ("huge-int", "negative-huge-int"):
        return OverflowError, "int too large to convert to float"
    if field in ("kind", "precision"):
        if label == "nan":
            return ValueError, "cannot convert float NaN to integer"
        if label in ("positive-infinity", "negative-infinity"):
            return OverflowError, "cannot convert float infinity to integer"
    return None


class TestPathModel(unittest.TestCase):
    def test_point_constructor_serialization_and_frozen_contract(self) -> None:
        point = PathPoint(1.0, -2.0)
        self.assertEqual([field.name for field in fields(point)], ["x", "y", "speed"])
        self.assertEqual(astuple(point), (1.0, -2.0, 100.0))
        self.assertEqual(list(point.to_godot_dict()), ["x", "y", "speed"])
        self.assertEqual(point.to_godot_dict(), asdict(point))
        self.assertEqual(point, pickle.loads(pickle.dumps(point)))
        self.assertEqual(point.__class__.__module__, "src.conversion.path_model")
        self.assertIs(RegistryPathPoint, PathPoint)
        with self.assertRaises(FrozenInstanceError):
            point.__setattr__("x", 9.0)

    def test_canonical_shape_raw_identity_and_snapshot(self) -> None:
        point: JsonObject = {"x": 3}
        data: JsonObject = {"points": [point], "unknown": {"nested": [None]}}
        model = parse_path_model(data, name="chosen", source_path="paths/p/p.yy")
        names = ["name", "source_path", "raw_data", "points", "closed", "kind", "precision"]
        self.assertEqual([field.name for field in fields(model)], names)
        self.assertEqual(list(inspect.signature(PathModel).parameters), names)
        self.assertTrue(
            all(p.default is inspect.Parameter.empty for p in inspect.signature(PathModel).parameters.values())
        )
        self.assertEqual(PathModel.__match_args__, tuple(names))
        self.assertIs(model.raw_data, data)
        self.assertIs(ResourcePathModel, PathModel)
        self.assertEqual(model, PathModel("chosen", "paths/p/p.yy", data, (PathPoint(3.0, 0.0),), False, 0, 4))
        point["x"] = 99
        data["points"] = []
        self.assertEqual(model.points, (PathPoint(3.0, 0.0),))
        self.assertEqual(model.point_count, 1)
        self.assertEqual(model.raw_data["points"], [])
        with self.assertRaises(FrozenInstanceError):
            model.__setattr__("name", "changed")

    def test_point_filtering_defaults_and_order(self) -> None:
        empty_values: tuple[JsonValue, ...] = (None, 1, "points", {})
        for value in empty_values:
            with self.subTest(value=value):
                self.assertEqual(parse_path_model({"points": value}, name="p", source_path="p.yy").points, ())
        self.assertEqual(parse_path_model({}, name="p", source_path="p.yy").point_count, 0)
        shared: JsonObject = {"x": 2, "y": 3, "speed": 4}
        data: JsonObject = {"points": [None, 1, "x", [], {}, shared, shared]}
        model = parse_path_model(data, name="p", source_path="p.yy")
        self.assertEqual(model.points, (PathPoint(0.0, 0.0), PathPoint(2.0, 3.0, 4.0), PathPoint(2.0, 3.0, 4.0)))
        self.assertEqual(model.point_count, 3)

    def test_numeric_values_and_closed_rules(self) -> None:
        expected_numbers = {
            "false": 0.0,
            "true": 1.0,
            "zero": 0.0,
            "negative-int": -2.0,
            "fraction": 2.9,
            "negative-zero": -0.0,
            "nan": float("nan"),
            "positive-infinity": float("inf"),
            "negative-infinity": -float("inf"),
            "beyond-exact-float-int": 9007199254740992.0,
            "large-finite": 1e308,
        }
        for field in NUMERIC_FIELDS:
            for label, value in NUMERIC_CASES:
                if numeric_path_error(field, label) is not None:
                    continue
                with self.subTest(field=field, value=label):
                    model = parse_path_model(numeric_path_payload(field, label, value), name="p", source_path="p.yy")
                    point = model.points[0]
                    actual = {
                        "x": point.x,
                        "y": point.y,
                        "speed": point.speed,
                        "kind": model.kind,
                        "precision": model.precision,
                    }[field]
                    expected = expected_numbers.get(label, {"speed": 100.0, "precision": 4.0}.get(field, 0.0))
                    if math.isnan(expected):
                        self.assertTrue(math.isnan(actual))
                    else:
                        self.assertEqual(actual, int(expected) if field in ("kind", "precision") else expected)
        self.assertEqual(
            math.copysign(1, parse_path_model({"points": [{"x": -0.0}]}, name="p", source_path="p.yy").points[0].x), -1
        )
        closed_cases: tuple[tuple[JsonValue, bool], ...] = (
            (None, False),
            (0, False),
            ([], False),
            ({}, False),
            ("false", True),
            ([0], True),
        )
        for value, expected in closed_cases:
            self.assertIs(parse_path_model({"closed": value}, name="p", source_path="p.yy").closed, expected)

    def test_unknown_fields_and_caller_names(self) -> None:
        data: JsonObject = {
            "name": "ignored",
            "%Name": "also ignored",
            "unknown": {"nested": [None, 1]},
            "points": [{"x": 1, "extra": 42}],
        }
        model = parse_path_model(data, name='chosen "λ"', source_path="paths/p/p.yy")
        self.assertEqual((model.name, model.source_path), ('chosen "λ"', "paths/p/p.yy"))
        self.assertIs(model.raw_data, data)
        self.assertEqual(list(model.raw_data), ["name", "%Name", "unknown", "points"])
        self.assertEqual(model.points, (PathPoint(1.0, 0.0),))

    def test_geometry_errors_and_field_precedence(self) -> None:
        for field in NUMERIC_FIELDS:
            for label, value in NUMERIC_CASES:
                expected = numeric_path_error(field, label)
                if expected is None:
                    continue
                with self.subTest(field=field, value=label), self.assertRaisesRegex(*expected):
                    parse_path_model(numeric_path_payload(field, label, value), name="p", source_path="p.yy")
        for data, error, message in ERROR_ORDER_CASES:
            with self.subTest(data=data), self.assertRaisesRegex(error, message):
                parse_path_model(data, name="p", source_path="p.yy")

    def test_canonical_dependency_and_import_ownership(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src/conversion/path_model.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imported, {"__future__", "dataclasses", "src.conversion.json_values"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        self.assertEqual(PathModel.__module__, "src.conversion.path_model")
        self.assertIs(ResourcePathModel, PathModel)
        self.assertIs(RegistryPathPoint, PathPoint)
