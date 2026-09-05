from __future__ import annotations

import dataclasses
import inspect
import math
import unittest

from src.conversion.font_model import FontModel, bundled_font_reference, parse_font_model, system_font_reference
from src.conversion.json_values import JsonObject, JsonValue

FONT_FIELD_CASES: tuple[tuple[bool, JsonValue], ...] = (
    (False, None), (True, None), (True, False), (True, True),
    (True, 0), (True, 16), (True, -2), (True, 10 ** 400),
    (True, 16.5), (True, -2.5), (True, float("nan")),
    (True, float("inf")), (True, float("-inf")),
    (True, ""), (True, "16"), (True, "16.5"), (True, " 16 "),
    (True, "not-a-number"), (True, "false"),
    (True, []), (True, [1]), (True, {}), (True, {"key": 1}),
)
FONT_ERROR_ORDER: tuple[tuple[JsonObject, type[Exception], str], ...] = (
    ({}, KeyError, "'fontName'"),
    ({"name": "fnt", "size": "bad", "AntiAlias": "bad"}, KeyError, "'fontName'"),
    ({"fontName": "Family", "size": "bad", "AntiAlias": "bad"}, KeyError, "'name'"),
    ({"fontName": "Family", "name": "fnt", "size": None, "AntiAlias": "bad"},
     TypeError, "Font numeric field requires a string or number"),
    ({"fontName": "Family", "name": "fnt", "size": "bad", "AntiAlias": None},
     ValueError, "could not convert string to float: 'bad'"),
    ({"fontName": "Family", "name": "fnt", "size": 10 ** 400, "AntiAlias": None},
     OverflowError, "int too large to convert to float"),
)


class TestFontModel(unittest.TestCase):
    def test_required_and_numeric_conversion_order(self) -> None:
        for data, error_type, message in FONT_ERROR_ORDER:
            with self.subTest(data=data), self.assertRaises(error_type) as caught:
                parse_font_model(data, source_path="font.yy")
            self.assertEqual(str(caught.exception), message)

    def test_defaults_and_scalar_normalization(self) -> None:
        model = parse_font_model({"fontName": "Family", "name": "fnt"}, source_path="font.yy")
        self.assertEqual(dataclasses.astuple(model)[:8], ("Family", "fnt", 12.0, False, False, 0, False, ""))
        inputs: JsonObject = {
            "fontName": None, "name": 7, "size": " -2.5 ", "bold": "false",
            "italic": [], "AntiAlias": -2.5, "includeTTF": {}, "TTFName": False,
        }
        normalized = parse_font_model(inputs, source_path="font.yy")
        self.assertEqual(dataclasses.astuple(normalized)[:8], ("None", "7", -2.5, True, False, -2, False, "False"))
        for value, expected in ((False, 0), (True, 1), (16, 16), (" 16 ", 16)):
            with self.subTest(value=value):
                model = parse_font_model({"fontName": "F", "name": "n", "size": value, "AntiAlias": value},
                                         source_path="")
                self.assertEqual((model.size, model.antialiasing), (float(expected), expected))

    def test_null_array_and_object_numeric_values_raise_type_error(self) -> None:
        values: tuple[JsonValue, ...] = (None, [], [1], {}, {"key": 1})
        for field in ("size", "AntiAlias"):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(TypeError) as caught:
                    parse_font_model({"fontName": "F", "name": "n", field: value}, source_path="")
                self.assertEqual(str(caught.exception), "Font numeric field requires a string or number")

    def test_native_numeric_errors_and_nonfinite_values(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            model = parse_font_model({"fontName": "F", "name": "n", "size": value}, source_path="")
            self.assertEqual(math.isnan(model.size), math.isnan(value))
            if not math.isnan(value):
                self.assertEqual(model.size, value)
        failures = (
            ("size", "", float), ("size", "not-a-number", float), ("size", 10 ** 400, float),
            ("AntiAlias", "", int), ("AntiAlias", "16.5", int),
            ("AntiAlias", float("nan"), int), ("AntiAlias", float("inf"), int),
            ("AntiAlias", float("-inf"), int),
        )
        for field, value, native_conversion in failures:
            with self.subTest(field=field, value=value):
                with self.assertRaises((ValueError, OverflowError)) as native:
                    native_conversion(value)
                with self.assertRaises(type(native.exception)) as actual:
                    parse_font_model({"fontName": "F", "name": "n", field: value}, source_path="")
                self.assertEqual(str(actual.exception), str(native.exception))

    def test_registry_references_keep_string_only_eligibility(self) -> None:
        enabled_values: tuple[JsonValue, ...] = (False, True, None, "false", [], [1])
        for present, value in FONT_FIELD_CASES:
            expected = value if present and isinstance(value, str) and value else None
            data: JsonObject = {"fontName": value} if present else {}
            self.assertEqual(system_font_reference(data), expected)
            for enabled in enabled_values:
                data = {"includeTTF": enabled}
                if present:
                    data["TTFName"] = value
                with self.subTest(present=present, value=value, enabled=enabled):
                    self.assertEqual(bundled_font_reference(data), expected if enabled else None)

    def test_raw_identity_and_normalized_snapshot(self) -> None:
        nested: JsonObject = {"items": [1, {"future": True}]}
        raw: JsonObject = {"fontName": "Family", "name": "fnt", "unknown": nested, "size": "16"}
        model = parse_font_model(raw, source_path="source.yy")
        self.assertIs(model.raw_data, raw)
        self.assertIs(model.raw_data["unknown"], nested)
        self.assertEqual(list(model.raw_data), ["fontName", "name", "unknown", "size"])
        raw["name"] = "changed"
        raw["size"] = None
        nested["later"] = 2
        self.assertEqual((model.name, model.size), ("fnt", 16.0))
        self.assertEqual(model.raw_data["name"], "changed")
        self.assertEqual(model.raw_data["unknown"], {"items": [1, {"future": True}], "later": 2})

    def test_source_path_is_retained_literally(self) -> None:
        for path in ("fonts/f/f.yy", r"fonts\f\f.yy", "./fonts/../f.yy", "/source/font.yy", ""):
            with self.subTest(path=path):
                model = parse_font_model({"fontName": "Family", "name": "fnt"}, source_path=path)
                self.assertEqual(model.source_path, path)

    def test_dataclass_schema_equality_and_serialization(self) -> None:
        names = ("font_name", "name", "size", "bold", "italic", "antialiasing", "include_ttf", "ttf_name",
                 "source_path", "raw_data")
        fields = dataclasses.fields(FontModel)
        self.assertEqual(tuple(field.name for field in fields), names)
        self.assertTrue(all(field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
                            for field in fields))
        self.assertEqual(tuple(inspect.signature(FontModel).parameters), names)
        self.assertEqual(FontModel.__match_args__, names)
        self.assertEqual(FontModel.__module__, "src.conversion.font_model")
        self.assertNotIn("__getitem__", FontModel.__dict__)
        raw: JsonObject = {"fontName": "Family", "name": "fnt"}
        model = parse_font_model(raw, source_path="font.yy")
        expected = ("Family", "fnt", 12.0, False, False, 0, False, "", "font.yy", raw)
        self.assertEqual(dataclasses.astuple(model), expected)
        self.assertEqual(dataclasses.asdict(model), dict(zip(names, expected, strict=True)))
        self.assertEqual(model, parse_font_model(dict(raw), source_path="font.yy"))
        self.assertNotEqual(model, dataclasses.replace(model, source_path="other.yy"))
        self.assertNotEqual(model, dataclasses.replace(model, raw_data={**raw, "unknown": True}))
        self.assertEqual(repr(model), "FontModel(font_name='Family', name='fnt', size=12.0, bold=False, italic=False, "
                         "antialiasing=0, include_ttf=False, ttf_name='', source_path='font.yy', "
                         "raw_data={'fontName': 'Family', 'name': 'fnt'})")
        for field in fields:
            with self.subTest(field=field.name), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(model, field.name, getattr(model, field.name))
