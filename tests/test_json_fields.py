import ast
import math
import pathlib
import sys
import unittest
from dataclasses import dataclass
from typing import Protocol

from src.conversion.json_fields import (
    MISSING,
    JsonFieldError,
    JsonFieldKind,
    JsonFieldState,
    JsonMissing,
    field_value,
    optional_array,
    optional_boolean,
    optional_number,
    optional_object,
    optional_string,
    required_array,
    required_boolean,
    required_number,
    required_object,
    required_string,
)
from src.conversion.json_values import (
    JsonObject,
    JsonPath,
    JsonValue,
    JsonValueError,
    validate_json_value,
)


class _RequiredAccessor(Protocol):
    def __call__(
        self,
        data: JsonObject,
        key: str,
        *,
        source_path: str,
        field_path: JsonPath = (),
    ) -> JsonValue: ...


class _OptionalAccessor(Protocol):
    def __call__(
        self,
        data: JsonObject,
        key: str,
        *,
        source_path: str,
        field_path: JsonPath = (),
        default: JsonValue | JsonMissing = MISSING,
    ) -> JsonValue | JsonMissing: ...


@dataclass(frozen=True)
class _AccessorCase:
    kind: JsonFieldKind
    required: _RequiredAccessor
    optional: _OptionalAccessor
    valid: JsonValue
    wrong: JsonValue
    wrong_state: JsonFieldState


def _accessor_cases() -> tuple[_AccessorCase, ...]:
    return (
        _AccessorCase("string", required_string, optional_string, "value", 12, "number"),
        _AccessorCase("number", required_number, optional_number, 1.5, True, "boolean"),
        _AccessorCase("boolean", required_boolean, optional_boolean, False, 0, "number"),
        _AccessorCase("array", required_array, optional_array, [1, {"enabled": True}], {}, "object"),
        _AccessorCase("object", required_object, optional_object, {"items": [1]}, [], "array"),
    )


class TestJsonFields(unittest.TestCase):
    def test_raw_field_value_distinguishes_missing_null_and_identity(self) -> None:
        nested: JsonObject = {"value": 1}
        data: JsonObject = {"null": None, "nested": nested, "false": False}
        self.assertIs(field_value(data, "absent"), MISSING)
        self.assertIsNone(field_value(data, "null"))
        self.assertIs(field_value(data, "nested"), nested)
        self.assertIs(field_value(data, "false"), False)
        self.assertEqual(list(data), ["null", "nested", "false"])

    def test_missing_sentinel_is_outside_json_values(self) -> None:
        self.assertIsInstance(MISSING, JsonMissing)
        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(MISSING, source_path="missing.yy")
        self.assertEqual(raised.exception.actual, "JsonMissing")
        self.assertEqual(raised.exception.reason, "unsupported-type")

    def test_all_required_accessors_return_valid_fields_by_identity(self) -> None:
        for case in _accessor_cases():
            data: JsonObject = {"value": case.valid}
            with self.subTest(kind=case.kind):
                self.assertIs(case.required(data, "value", source_path="required.yy"), case.valid)

    def test_all_required_accessors_reject_missing_null_and_wrong_kind(self) -> None:
        for case in _accessor_cases():
            documents: tuple[tuple[JsonObject, JsonFieldState], ...] = (
                ({}, "missing"), ({"value": None}, "null"), ({"value": case.wrong}, case.wrong_state),
            )
            for data, actual in documents:
                with self.subTest(kind=case.kind, actual=actual):
                    with self.assertRaises(JsonFieldError) as raised:
                        case.required(data, "value", source_path="../required.yy", field_path=("items", 2))
                    error = raised.exception
                    self.assertEqual(error.source_path, "../required.yy")
                    self.assertEqual(error.field_path, ("items", 2, "value"))
                    self.assertEqual(error.expected, case.kind)
                    self.assertEqual(error.actual, actual)

    def test_all_optional_accessors_distinguish_missing_null_and_valid(self) -> None:
        for case in _accessor_cases():
            with self.subTest(kind=case.kind):
                self.assertIs(case.optional({}, "value", source_path="optional.yy"), MISSING)
                self.assertIsNone(case.optional({"value": None}, "value", source_path="optional.yy"))
                self.assertIs(
                    case.optional({"value": case.valid}, "value", source_path="optional.yy"),
                    case.valid,
                )

    def test_all_optional_accessors_use_a_valid_default_only_for_absence(self) -> None:
        for case in _accessor_cases():
            with self.subTest(kind=case.kind):
                self.assertIs(
                    case.optional({}, "value", source_path="default.yy", default=case.valid),
                    case.valid,
                )
                self.assertIsNone(
                    case.optional({"value": None}, "value", source_path="default.yy", default=case.valid)
                )
                self.assertIs(
                    case.optional(
                        {"value": case.valid}, "value", source_path="default.yy", default=case.wrong
                    ),
                    case.valid,
                )
                self.assertIsNone(
                    case.optional({"value": None}, "value", source_path="default.yy", default=case.wrong)
                )

    def test_all_optional_accessors_reject_wrong_defaults_and_present_wrong_values(self) -> None:
        for case in _accessor_cases():
            documents: tuple[tuple[JsonObject, JsonValue, JsonFieldState], ...] = (
                ({}, case.wrong, case.wrong_state),
                ({"value": case.wrong}, case.valid, case.wrong_state),
                ({}, None, "null"),
            )
            for data, default, actual in documents:
                with self.subTest(kind=case.kind, actual=actual, present="value" in data):
                    with self.assertRaises(JsonFieldError) as raised:
                        case.optional(
                            data, "value", source_path="default.yy", field_path=("options",), default=default
                        )
                    self.assertEqual(raised.exception.field_path, ("options", "value"))
                    self.assertEqual(raised.exception.expected, case.kind)
                    self.assertEqual(raised.exception.actual, actual)

    def test_numbers_exclude_both_booleans_and_do_not_coerce_strings(self) -> None:
        values: tuple[tuple[JsonValue, JsonFieldState], ...] = (
            (True, "boolean"), (False, "boolean"), ("12", "string"), ("", "string"),
        )
        for value, actual in values:
            data: JsonObject = {"value": value}
            with self.subTest(actual=actual, value=value):
                with self.assertRaises(JsonFieldError) as required:
                    required_number(data, "value", source_path="number.yy")
                with self.assertRaises(JsonFieldError) as optional:
                    optional_number(data, "value", source_path="number.yy", default=99)
                self.assertEqual(required.exception.actual, actual)
                self.assertEqual(optional.exception.actual, actual)

    def test_number_zero_and_nonfinite_floats_keep_value_and_identity(self) -> None:
        values: tuple[int | float, ...] = (0, -1, 1.5, math.nan, math.inf, -math.inf)
        for value in values:
            data: JsonObject = {"value": value}
            with self.subTest(kind=type(value).__name__):
                self.assertIs(required_number(data, "value", source_path="number.yy"), value)
                self.assertIs(optional_number(data, "value", source_path="number.yy"), value)

    def test_strings_booleans_and_empty_containers_are_not_coerced(self) -> None:
        data: JsonObject = {"text": "", "flag": False, "array": [], "object": {}}
        self.assertEqual(required_string(data, "text", source_path="empty.yy"), "")
        self.assertIs(required_boolean(data, "flag", source_path="empty.yy"), False)
        self.assertIs(required_array(data, "array", source_path="empty.yy"), data["array"])
        self.assertIs(required_object(data, "object", source_path="empty.yy"), data["object"])

    def test_error_path_appends_one_key_to_structural_prefix(self) -> None:
        with self.assertRaises(JsonFieldError) as raised:
            required_string(
                {"path": 4}, "path", source_path="source\\example.yy", field_path=("resources", 2, "id")
            )
        error = raised.exception
        self.assertEqual(error.field_path, ("resources", 2, "id", "path"))
        self.assertEqual(error.source_path, "source\\example.yy")
        self.assertEqual(error.expected, "string")
        self.assertEqual(error.actual, "number")
        self.assertIsInstance(error, ValueError)

    def test_field_leaf_imports_only_stdlib_and_json_values(self) -> None:
        source_path = pathlib.Path(__file__).resolve().parents[1] / "src/conversion/json_fields.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "Field leaf must not import relative project owners")
                assert node.module is not None
                imported_modules.add(node.module)
        for module in imported_modules:
            with self.subTest(module=module):
                if module != "src.conversion.json_values":
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
