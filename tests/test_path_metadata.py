import ast
import dataclasses
import json
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonPath, JsonValueError
from src.conversion.path_metadata import (
    GameMakerPathMetadata,
    PathMetadataPoint,
    parse_gamemaker_path_metadata,
)


def _decode_metadata(source: str) -> GameMakerPathMetadata:
    document = decode_gamemaker_json(source, source_path="paths/path.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_path_metadata(document.value, source_path=document.source_path)


class TestPathMetadata(unittest.TestCase):
    def test_empty_document_defaults_and_frozen_models(self) -> None:
        metadata = _decode_metadata("{}")

        self.assertFalse(metadata.closed)
        self.assertEqual(metadata.kind, 0.0)
        self.assertEqual(metadata.precision, 4.0)
        self.assertIs(type(metadata.kind), float)
        self.assertIs(type(metadata.precision), float)
        self.assertEqual(metadata.points, ())
        self.assertEqual(metadata.parent_path, "")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(metadata, "closed", True)
        point = PathMetadataPoint(1, 2)
        self.assertEqual(point.speed, 100.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(point, "x", 3)
        self.assertIsNot(point.raw_data, PathMetadataPoint(1, 2).raw_data)
        self.assertIsNot(GameMakerPathMetadata().raw_data, GameMakerPathMetadata().raw_data)

    def test_points_missing_null_and_wrong_shapes_keep_empty_projection(self) -> None:
        for source in (
            "{}", '{"points":null}', '{"points":false}', '{"points":true}',
            '{"points":0}', '{"points":1.25}', '{"points":"text"}', '{"points":{}}',
        ):
            with self.subTest(source=source):
                metadata = _decode_metadata(source)
                self.assertEqual(metadata.points, ())

    def test_mixed_point_array_keeps_all_objects_in_original_order(self) -> None:
        metadata = _decode_metadata(
            '{"points":[null,false,true,0,1.5,"text",[],{},{"x":7},{"y":-2,"speed":0}]}'
        )

        self.assertEqual(
            [(point.x, point.y, point.speed) for point in metadata.points],
            [(0.0, 0.0, 100.0), (7, 0.0, 100.0), (0.0, -2, 0)],
        )
        self.assertEqual([list(point.raw_data) for point in metadata.points], [[], ["x"], ["y", "speed"]])

    def test_numeric_field_states_preserve_native_values_and_legacy_defaults(self) -> None:
        cases: tuple[tuple[str, int | float | None], ...] = (
            ("true", 1), ("false", 0), ("0", 0), ("-7", -7), ("1.25", 1.25),
            ("null", None), ('"9"', None), ("[]", None), ("{}", None),
        )
        for literal, expected in cases:
            source = (
                '{"kind":' + literal + ',"precision":' + literal
                + ',"points":[{"x":' + literal + ',"y":' + literal + ',"speed":' + literal + '}]}'
            )
            with self.subTest(literal=literal):
                metadata = _decode_metadata(source)
                point = metadata.points[0]
                actual = (point.x, point.y, point.speed, metadata.kind, metadata.precision)
                wanted = (0.0, 0.0, 100.0, 0.0, 4.0) if expected is None else (expected,) * 5
                self.assertEqual(actual, wanted)
                self.assertEqual(tuple(type(value) for value in actual), tuple(type(value) for value in wanted))

    def test_explicit_zero_speed_is_distinct_from_missing_speed(self) -> None:
        metadata = _decode_metadata('{"points":[{},{"speed":0},{"speed":false}]}')

        self.assertEqual(tuple(point.speed for point in metadata.points), (100.0, 0, 0))
        self.assertEqual(tuple(type(point.speed) for point in metadata.points), (float, int, int))

    def test_huge_integers_and_exact_numeric_provenance_are_not_coerced(self) -> None:
        huge = 10 ** 400
        exact = 2 ** 53 + 1
        source = (
            '{"kind":' + str(exact) + ',"precision":' + str(huge)
            + ',"points":[{"x":' + str(huge) + ',"y":-0.0,"speed":1.5}]}'
        )
        document = decode_gamemaker_json(source, source_path="huge.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_path_metadata(document.value, source_path=document.source_path)
        point = metadata.points[0]

        self.assertEqual(point.x, huge)
        self.assertEqual(metadata.kind, exact)
        self.assertEqual(metadata.precision, huge)
        self.assertIs(type(point.x), int)
        self.assertIs(type(metadata.kind), int)
        self.assertIs(type(metadata.precision), int)
        self.assertIs(metadata.kind, document.value["kind"])
        self.assertIs(metadata.precision, document.value["precision"])
        self.assertIs(point.x, point.raw_data["x"])
        self.assertIs(point.y, point.raw_data["y"])
        self.assertIs(point.speed, point.raw_data["speed"])
        self.assertLess(math.copysign(1.0, point.y), 0)

    def test_nonfinite_numbers_remain_native_at_every_known_numeric_field(self) -> None:
        for literal in ("NaN", "Infinity", "-Infinity"):
            source = (
                '{"kind":' + literal + ',"precision":' + literal
                + ',"points":[{"x":' + literal + ',"y":' + literal + ',"speed":' + literal + '}]}'
            )
            with self.subTest(literal=literal):
                document = decode_gamemaker_json(source, source_path="nonfinite.yy")
                assert isinstance(document.value, dict)
                metadata = parse_gamemaker_path_metadata(document.value, source_path=document.source_path)
                point = metadata.points[0]
                values = (point.x, point.y, point.speed, metadata.kind, metadata.precision)
                self.assertTrue(all(type(value) is float for value in values))
                if literal == "NaN":
                    self.assertTrue(all(math.isnan(value) for value in values))
                else:
                    expected = math.inf if literal == "Infinity" else -math.inf
                    self.assertEqual(values, (expected,) * 5)
                self.assertIs(metadata.kind, document.value["kind"])
                self.assertIs(metadata.precision, document.value["precision"])
                self.assertIs(point.x, point.raw_data["x"])
                self.assertIs(point.y, point.raw_data["y"])
                self.assertIs(point.speed, point.raw_data["speed"])

    def test_closed_keeps_present_json_truthiness_and_missing_is_false(self) -> None:
        cases = (
            ("null", False), ("false", False), ("0", False), ("-0.0", False),
            ('""', False), ("[]", False), ("{}", False), ("true", True),
            ("-1", True), ('"false"', True), ("[null]", True), ('{"enabled":false}', True),
            ("NaN", True), ("Infinity", True), (str(10 ** 400), True),
        )
        self.assertFalse(_decode_metadata("{}").closed)
        for literal, expected in cases:
            with self.subTest(literal=literal):
                self.assertIs(_decode_metadata('{"closed":' + literal + '}').closed, expected)

    def test_parent_path_strings_remain_exact_without_normalization(self) -> None:
        for path in ("", "folders/Paths/AI.yy", "Folders/Paths/AI.YY", "folders\\Paths\\AI.yy",
                     "folders/Paths/AI\\Sub.yy", " folders/Paths/Ångström.yy "):
            with self.subTest(path=path):
                metadata = _decode_metadata(json.dumps({"parent": {"path": path}}))
                self.assertEqual(metadata.parent_path, path)

    def test_missing_and_wrong_parent_shapes_keep_empty_path(self) -> None:
        for source in (
            "{}", '{"parent":null}', '{"parent":false}', '{"parent":0}',
            '{"parent":"folders/Paths/AI.yy"}', '{"parent":[]}', '{"parent":{}}',
            '{"parent":{"path":null}}', '{"parent":{"path":true}}',
            '{"parent":{"path":7}}', '{"parent":{"path":[]}}', '{"parent":{"path":{}}}',
        ):
            with self.subTest(source=source):
                self.assertEqual(_decode_metadata(source).parent_path, "")

    def test_decoded_raw_root_points_and_unknown_extras_keep_identity_and_order(self) -> None:
        document = decode_gamemaker_json(
            '{"extra":{"z":[null,{"two":2,"one":1}]},"points":[{"tag":{"last":4,"first":3},"x":1}],"closed":false}',
            source_path="identity.yy",
        )
        assert isinstance(document.value, dict)
        raw = document.value
        raw_points = raw["points"]
        assert isinstance(raw_points, list)
        raw_point = raw_points[0]
        assert isinstance(raw_point, dict)
        metadata = parse_gamemaker_path_metadata(raw, source_path=document.source_path)

        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["extra"], raw["extra"])
        self.assertIs(metadata.raw_data["points"], raw_points)
        self.assertIs(metadata.points[0].raw_data, raw_point)
        self.assertIs(metadata.points[0].raw_data["tag"], raw_point["tag"])
        self.assertEqual(list(metadata.raw_data), ["extra", "points", "closed"])
        self.assertEqual(list(metadata.points[0].raw_data), ["tag", "x"])
        tag = raw_point["tag"]
        assert isinstance(tag, dict)
        self.assertEqual(list(tag), ["last", "first"])

    def test_shared_raw_point_and_unknown_subtree_remain_shared_after_actual_validation(self) -> None:
        shared: list[object] = [{"last": None, "first": 4}]
        raw_point: dict[str, object] = {"x": 1, "unknown": shared}
        raw: dict[str, object] = {"points": [raw_point, raw_point], "unknown": shared}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="shared.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_path_metadata(document.value, source_path=document.source_path)

        self.assertIs(metadata.raw_data, raw)
        self.assertEqual(len(metadata.points), 2)
        self.assertIs(metadata.points[0].raw_data, raw_point)
        self.assertIs(metadata.points[1].raw_data, raw_point)
        self.assertIs(metadata.raw_data["unknown"], shared)
        self.assertIs(metadata.points[0].raw_data["unknown"], shared)
        raw_point["x"] = 9
        shared.append("new extra")
        self.assertEqual(metadata.points[0].x, 1)
        self.assertEqual(metadata.points[1].x, 1)
        self.assertEqual(metadata.points[0].raw_data["x"], 9)
        self.assertIs(metadata.points[1].raw_data["unknown"], shared)

    def test_deep_unknown_native_metadata_uses_actual_iterative_decoder_validation(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        deep: list[object] = []
        cursor = deep
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cursor.append("unknown leaf")
        raw_point: dict[str, object] = {"x": 4, "unknown": deep}
        raw: dict[str, object] = {"points": [raw_point], "unknown": deep}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="deep.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_path_metadata(document.value, source_path=document.source_path)

        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], deep)
        self.assertIs(metadata.points[0].raw_data, raw_point)
        self.assertIs(metadata.points[0].raw_data["unknown"], deep)
        self.assertEqual(metadata.points[0].x, 4)
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_actual_decoder_rejects_unsupported_known_and_unknown_nested_values(self) -> None:
        cases: tuple[tuple[dict[str, object], JsonPath, str], ...] = (
            ({"points": [{"x": 1, "unknown": b"invalid"}]}, ("points", 0, "unknown"), "unsupported-type"),
            ({"points": ({"x": 1},)}, ("points",), "unsupported-type"),
            ({"closed": b"invalid"}, ("closed",), "unsupported-type"),
            ({"extra": {7: "invalid key"}}, ("extra",), "non-string-key"),
        )
        for raw, field_path, reason in cases:
            with self.subTest(field_path=field_path):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="invalid-path.yy")
                self.assertEqual(raised.exception.source_path, "invalid-path.yy")
                self.assertEqual(raised.exception.field_path, field_path)
                self.assertEqual(raised.exception.reason, reason)

    def test_actual_decoder_rejects_ancestor_cycles_in_path_metadata(self) -> None:
        raw: dict[str, object] = {}
        raw_point: dict[str, object] = {"x": 1, "unknown": raw}
        raw["points"] = [raw_point]
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            with self.assertRaises(JsonValueError) as raised:
                decode_gamemaker_json("{}", source_path="cycle.yy")

        self.assertEqual(raised.exception.source_path, "cycle.yy")
        self.assertEqual(raised.exception.field_path, ("points", 0, "unknown"))
        self.assertEqual(raised.exception.reason, "cycle")

    def test_model_leaf_imports_only_stdlib_and_the_two_json_leaves(self) -> None:
        path = pathlib.Path(__file__).resolve().parents[1] / "src" / "conversion" / "path_metadata.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed_project_modules = {"src.conversion.json_fields", "src.conversion.json_values"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "Relative imports conceal project dependencies")
                assert node.module is not None
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.split(".")[0] == "src":
                    self.assertIn(module, allowed_project_modules)
                else:
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)
        self.assertFalse(
            any(
                isinstance(node, ast.Name) and node.id in {"Any", "cast"}
                or isinstance(node, ast.Attribute) and node.attr in {"Any", "cast"}
                for node in ast.walk(tree)
            ),
            "The projection must consume typed JSON directly",
        )
