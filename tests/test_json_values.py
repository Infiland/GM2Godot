from __future__ import annotations

import math
import unittest

from src.conversion.json_values import JsonFieldPath, JsonValueError, format_json_field_path, validate_json_value


class TestJsonValues(unittest.TestCase):
    def test_preserves_unknown_values_order_and_container_identity(self) -> None:
        child: list[object] = [None, True, False, 0, 1.5, "", {"extra": ["kept"]}]
        value: dict[str, object] = {"first": child, "unknown": child, "last": {}}
        validated = validate_json_value(value)
        self.assertIs(validated, value)
        self.assertEqual(list(value), ["first", "unknown", "last"])
        self.assertIs(value["first"], child)
        self.assertIs(value["unknown"], child)

    def test_null_and_nonfinite_scalars_remain_valid(self) -> None:
        self.assertIsNone(validate_json_value(None))
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assertIs(validate_json_value(value), value)

    def test_nested_invalid_values_report_exact_structural_path(self) -> None:
        for invalid in (b"bytes", ("tuple",), {"set"}, object()):
            with self.subTest(kind=type(invalid).__name__):
                value = {"resources": [{"id": {"path": invalid}}]}
                with self.assertRaises(JsonValueError) as raised:
                    validate_json_value(value)
                self.assertEqual(raised.exception.field_path, ("resources", 0, "id", "path"))
                self.assertEqual(raised.exception.expected, "JSON value")
                self.assertEqual(raised.exception.actual_type, type(invalid).__name__)
                self.assertIn("resources[0].id.path", str(raised.exception))

    def test_invalid_dictionary_keys_belong_to_the_containing_path(self) -> None:
        for key in (1, None, False, ("tuple",)):
            with self.subTest(key=key):
                value = {"items": [{key: "value"}]}
                with self.assertRaises(JsonValueError) as raised:
                    validate_json_value(value)
                self.assertEqual(raised.exception.field_path, ("items", 0))
                self.assertIs(raised.exception.invalid_key, key)
                self.assertEqual(raised.exception.actual_type, type(key).__name__)
                self.assertEqual(raised.exception.expected, "string dictionary key")
                self.assertIn(f"key {key!r}", str(raised.exception))

    def test_detects_active_ancestor_cycles_but_allows_shared_children(self) -> None:
        child: list[object] = ["shared"]
        shared: list[object] = [child, child]
        self.assertIs(validate_json_value(shared), shared)
        cycle: list[object] = []
        cycle.append({"again": cycle})
        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(cycle, field_path=("root",))
        self.assertEqual(raised.exception.field_path, ("root", 0, "again"))
        self.assertEqual(raised.exception.expected, "acyclic JSON value")
        self.assertEqual(raised.exception.actual_type, "list")

    def test_deep_native_containers_do_not_use_python_recursion(self) -> None:
        value: object = "leaf"
        for _index in range(1500):
            value = [value]
        self.assertIs(validate_json_value(value), value)

    def test_field_paths_distinguish_keys_from_indexes_and_missing_from_null(self) -> None:
        paths: tuple[tuple[JsonFieldPath, str], ...] = (
            ((), "$"),
            (("resources", 0, "id", "path"), "resources[0].id.path"),
            (("a.b", 2), '["a.b"][2]'),
            (("", "x[y]", 'quote"'), '[""]["x[y]"]["quote\\\""]'),
            (("objects", "name"), "objects.name"),
        )
        for path, expected in paths:
            with self.subTest(path=path):
                self.assertEqual(format_json_field_path(path), expected)
        value: dict[str, object] = {"present": None}
        self.assertIs(validate_json_value(value), value)
        self.assertIn("present", value)
        self.assertNotIn("missing", value)


if __name__ == "__main__":
    unittest.main()
