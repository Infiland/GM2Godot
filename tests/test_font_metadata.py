import ast
import dataclasses
import json
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

from src.conversion.font_metadata import (
    FontConversionFields,
    GameMakerFontMetadata,
    parse_gamemaker_font_metadata,
    project_font_conversion_fields,
)
from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonPath, JsonValue, JsonValueError


def _decode_metadata(source: str) -> GameMakerFontMetadata:
    document = decode_gamemaker_json(source, source_path="fonts/font.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_font_metadata(document.value, source_context=document.source_path)


class TestFontMetadata(unittest.TestCase):
    def test_empty_capture_defaults_are_frozen_and_required_conversion_is_deferred(self) -> None:
        metadata = _decode_metadata("{}")

        self.assertEqual(metadata.font_name, "")
        self.assertEqual(metadata.size_number, 0.0)
        self.assertIs(type(metadata.size_number), float)
        self.assertFalse(metadata.bold)
        self.assertFalse(metadata.italic)
        self.assertFalse(metadata.include_ttf)
        self.assertEqual(metadata.parent_path, "")
        self.assertEqual(metadata.source_context, "fonts/font.yy")
        self.assertEqual(metadata.raw_data, {})
        self.assertIsNot(GameMakerFontMetadata().raw_data, GameMakerFontMetadata().raw_data)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(metadata, "font_name", "replacement")
        with self.assertRaises(KeyError) as raised:
            project_font_conversion_fields(metadata)
        self.assertEqual(raised.exception.args, ("fontName",))

    def test_public_record_order_defaults_and_private_context_visibility(self) -> None:
        self.assertEqual(
            [field.name for field in dataclasses.fields(GameMakerFontMetadata)],
            ["font_name", "size_number", "bold", "italic", "include_ttf",
             "parent_path", "raw_data", "source_context", "_conversion_inputs"],
        )
        fields = dataclasses.fields(FontConversionFields)
        self.assertEqual(
            [field.name for field in fields],
            ["font_name", "name", "size", "bold", "italic", "anti_alias", "include_ttf", "ttf_name"],
        )
        self.assertTrue(all(field.default is dataclasses.MISSING for field in fields))
        metadata = _decode_metadata('{"fontName":"Arial","name":"font"}')
        other_context = parse_gamemaker_font_metadata(metadata.raw_data, source_context="other.yy")
        self.assertEqual(metadata, other_context)
        self.assertNotIn("source_context=", repr(metadata))
        self.assertNotIn("_conversion_inputs=", repr(metadata))
        converted = project_font_conversion_fields(metadata)
        self.assertEqual(converted, FontConversionFields("Arial", "font", 12.0, False, False, 0, False, ""))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(converted, "size", 20.0)

    def test_reflected_private_capture_has_json_primitive_missing_and_null_states(self) -> None:
        for source, expected_present in (
            ("{}", False),
            ('{"fontName":null,"name":null,"size":null,"bold":null,"italic":null,'
             '"AntiAlias":null,"includeTTF":null,"TTFName":null}', True),
        ):
            with self.subTest(source=source):
                metadata = _decode_metadata(source)
                document = decode_gamemaker_json(
                    json.dumps(dataclasses.asdict(metadata)), source_path="reflection.json"
                )
                assert isinstance(document.value, dict)
                inputs = document.value["_conversion_inputs"]
                assert isinstance(inputs, dict)
                self.assertEqual(
                    list(inputs),
                    ["font_name", "name", "size", "bold", "italic", "anti_alias", "include_ttf", "ttf_name"],
                )
                for captured in inputs.values():
                    self.assertEqual(captured, {"present": expected_present, "value": None})
                self.assertNotIn("state", json.dumps(inputs))
                json.dumps(dataclasses.astuple(metadata))

    def test_missing_required_names_keep_key_error_and_first_failure_precedence(self) -> None:
        cases = (
            ('{"size":"invalid","AntiAlias":null}', "fontName"),
            ('{"fontName":"Arial","size":"invalid","AntiAlias":null}', "name"),
        )
        for source, key in cases:
            with self.subTest(source=source):
                metadata = _decode_metadata(source)
                with self.assertRaises(KeyError) as raised:
                    project_font_conversion_fields(metadata)
                self.assertEqual(raised.exception.args, (key,))

    def test_present_null_required_names_and_optional_text_use_python_string(self) -> None:
        metadata = _decode_metadata('{"fontName":null,"name":null,"TTFName":null}')
        converted = project_font_conversion_fields(metadata)

        self.assertEqual(metadata.font_name, "")
        self.assertEqual(converted.font_name, "None")
        self.assertEqual(converted.name, "None")
        self.assertEqual(converted.ttf_name, "None")
        self.assertEqual(converted.size, 12.0)
        self.assertEqual(converted.anti_alias, 0)

    def test_required_container_names_keep_python_repr_and_insertion_order(self) -> None:
        metadata = _decode_metadata(
            '{"fontName":{"last":null,"first":[true,false]},"name":[{"z":1,"a":2},null],'
            '"TTFName":{"b":false,"a":null}}'
        )
        converted = project_font_conversion_fields(metadata)

        self.assertEqual(metadata.font_name, "")
        self.assertEqual(converted.font_name, "{'last': None, 'first': [True, False]}")
        self.assertEqual(converted.name, "[{'z': 1, 'a': 2}, None]")
        self.assertEqual(converted.ttf_name, "{'b': False, 'a': None}")

    def test_optional_defaults_only_apply_when_absent_and_null_fails_at_its_position(self) -> None:
        for key, message in (
            ("size", "float() argument must be a string or a real number, not 'NoneType'"),
            ("AntiAlias", "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"),
        ):
            with self.subTest(key=key):
                metadata = _decode_metadata('{"fontName":"Arial","name":"font","' + key + '":null}')
                with self.assertRaises(TypeError) as raised:
                    project_font_conversion_fields(metadata)
                self.assertEqual(str(raised.exception), message)
        converted = project_font_conversion_fields(_decode_metadata(
            '{"fontName":"Arial","name":"font","bold":null,"italic":null,"includeTTF":null}'
        ))
        self.assertFalse(converted.bold)
        self.assertFalse(converted.italic)
        self.assertFalse(converted.include_ttf)

    def test_wrong_numeric_containers_keep_builtin_type_error_messages(self) -> None:
        for literal, type_name in (("[]", "list"), ("{}", "dict")):
            for key, message in (
                ("size", f"float() argument must be a string or a real number, not '{type_name}'"),
                ("AntiAlias", f"int() argument must be a string, a bytes-like object or a real number, not '{type_name}'"),
            ):
                with self.subTest(key=key, literal=literal):
                    metadata = _decode_metadata('{"fontName":"Arial","name":"font","' + key + '":' + literal + '}')
                    self.assertEqual(metadata.size_number, 0.0)
                    with self.assertRaises(TypeError) as raised:
                        project_font_conversion_fields(metadata)
                    self.assertEqual(str(raised.exception), message)

    def test_native_booleans_and_numeric_strings_preserve_distinct_consumer_policies(self) -> None:
        cases: tuple[tuple[str, str, float, int, int | float], ...] = (
            ("true", "true", 1.0, 1, True),
            ("false", "false", 0.0, 0, False),
            ('" 2.5e1 "', '" -2 "', 25.0, -2, 0.0),
            ("-7", "-2.9", -7.0, -2, -7),
            ("1.25", "4.75", 1.25, 4, 1.25),
        )
        for size, anti_alias, expected_size, expected_alias, expected_summary in cases:
            with self.subTest(size=size, anti_alias=anti_alias):
                metadata = _decode_metadata(
                    '{"fontName":"Arial","name":"font","size":' + size + ',"AntiAlias":' + anti_alias + '}'
                )
                converted = project_font_conversion_fields(metadata)
                self.assertEqual(metadata.size_number, expected_summary)
                self.assertIs(type(metadata.size_number), type(expected_summary))
                self.assertEqual(converted.size, expected_size)
                self.assertIs(type(converted.size), float)
                self.assertEqual(converted.anti_alias, expected_alias)
                self.assertIs(type(converted.anti_alias), int)

    def test_invalid_numeric_strings_raise_value_error_without_capture_failure(self) -> None:
        for key, literal in (("size", '"invalid"'), ("AntiAlias", '"1.5"'), ("AntiAlias", '""')):
            with self.subTest(key=key, literal=literal):
                metadata = _decode_metadata('{"fontName":"Arial","name":"font","' + key + '":' + literal + '}')
                self.assertEqual(metadata.size_number, 0.0)
                with self.assertRaises(ValueError):
                    project_font_conversion_fields(metadata)

    def test_summary_missing_null_and_wrong_font_name_and_size_shapes(self) -> None:
        for literal in ("null", '""', '"Arial"', "[]", "{}", "true", "false", "7", "1.5"):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"fontName":' + literal + ',"size":' + literal + '}')
                document = decode_gamemaker_json(literal, source_path="value.json")
                value = document.value
                self.assertEqual(metadata.font_name, value if isinstance(value, str) else "")
                expected = value if isinstance(value, (int, float)) else 0.0
                self.assertEqual(metadata.size_number, expected)
                self.assertIs(type(metadata.size_number), type(expected))

    def test_huge_native_numbers_and_negative_zero_remain_unchanged_until_projection(self) -> None:
        huge = 10 ** 400
        document = decode_gamemaker_json(
            '{"fontName":"Arial","name":"font","size":' + str(huge) + ',"AntiAlias":' + str(huge) + '}',
            source_path="huge.yy",
        )
        assert isinstance(document.value, dict)
        with patch("src.conversion.font_metadata._python_float", side_effect=AssertionError("eager float")), \
                patch("src.conversion.font_metadata._python_int", side_effect=AssertionError("eager int")), \
                patch("src.conversion.font_metadata._python_string", side_effect=AssertionError("eager str")):
            metadata = parse_gamemaker_font_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.size_number, document.value["size"])
        self.assertEqual(metadata.size_number, huge)
        with self.assertRaises(OverflowError):
            project_font_conversion_fields(metadata)
        valid_size = _decode_metadata('{"fontName":"Arial","name":"font","AntiAlias":' + str(huge) + '}')
        self.assertEqual(project_font_conversion_fields(valid_size).anti_alias, huge)
        negative_zero = _decode_metadata('{"fontName":"Arial","name":"font","size":-0.0,"AntiAlias":-0.0}')
        self.assertLess(math.copysign(1.0, negative_zero.size_number), 0)
        projected = project_font_conversion_fields(negative_zero)
        self.assertLess(math.copysign(1.0, projected.size), 0)
        self.assertEqual(projected.anti_alias, 0)

    def test_nonfinite_size_is_allowed_and_anti_alias_errors_are_delayed(self) -> None:
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"fontName":"Arial","name":"font","size":' + literal + '}')
                self.assertIs(metadata.size_number, metadata.raw_data["size"])
                projected = project_font_conversion_fields(metadata)
                if literal == "NaN":
                    self.assertTrue(math.isnan(metadata.size_number))
                    self.assertTrue(math.isnan(projected.size))
                else:
                    wanted = math.inf if literal == "Infinity" else -math.inf
                    self.assertEqual(metadata.size_number, wanted)
                    self.assertEqual(projected.size, wanted)
                invalid_alias = _decode_metadata(
                    '{"fontName":"Arial","name":"font","AntiAlias":' + literal + '}'
                )
                with self.assertRaises(ValueError if literal == "NaN" else OverflowError):
                    project_font_conversion_fields(invalid_alias)

    def test_all_boolean_fields_keep_present_json_truthiness_with_missing_false(self) -> None:
        cases = (
            ("null", False), ("false", False), ("0", False), ("-0.0", False),
            ('""', False), ("[]", False), ("{}", False), ("true", True),
            ('"false"', True), ("[null]", True), ('{"value":false}', True),
            ("NaN", True), ("Infinity", True), (str(10 ** 400), True),
        )
        for literal, expected in cases:
            with self.subTest(literal=literal):
                metadata = _decode_metadata(
                    '{"fontName":"Arial","name":"font","bold":' + literal + ',"italic":'
                    + literal + ',"includeTTF":' + literal + '}'
                )
                projected = project_font_conversion_fields(metadata)
                self.assertEqual((metadata.bold, metadata.italic, metadata.include_ttf), (expected,) * 3)
                self.assertEqual((projected.bold, projected.italic, projected.include_ttf), (expected,) * 3)

    def test_conversion_calls_all_eight_builtins_in_order_including_missing_defaults(self) -> None:
        metadata = _decode_metadata('{"fontName":"Arial","name":"font"}')
        events: list[tuple[str, JsonValue]] = []

        def python_string(value: JsonValue) -> str:
            events.append(("str", value))
            return str(value)

        def python_float(value: JsonValue) -> float:
            events.append(("float", value))
            assert isinstance(value, (str, int, float))
            return float(value)

        def python_int(value: JsonValue) -> int:
            events.append(("int", value))
            assert isinstance(value, (str, int, float))
            return int(value)

        def python_bool(value: JsonValue) -> bool:
            events.append(("bool", value))
            return bool(value)

        with patch("src.conversion.font_metadata._python_string", side_effect=python_string), \
                patch("src.conversion.font_metadata._python_float", side_effect=python_float), \
                patch("src.conversion.font_metadata._python_int", side_effect=python_int), \
                patch("src.conversion.font_metadata.bool", side_effect=python_bool, create=True):
            projected = project_font_conversion_fields(metadata)
        self.assertEqual(
            events,
            [("str", "Arial"), ("str", "font"), ("float", 12.0), ("bool", False),
             ("bool", False), ("int", 0), ("bool", False), ("str", "")],
        )
        self.assertEqual(projected.size, 12.0)

    def test_projection_preserves_exception_identity_and_stops_at_each_original_position(self) -> None:
        metadata = _decode_metadata('{"fontName":"Arial","name":"font"}')
        expected_order = ["str", "str", "float", "bool", "bool", "int", "bool", "str"]
        errors: tuple[BaseException, ...] = (
            KeyError("injected"), TypeError("injected"), ValueError("injected"),
            OverflowError("injected"), RecursionError("injected"), KeyboardInterrupt("injected"),
            SystemExit("injected"), OSError("injected"),
        )
        for position, error in enumerate(errors, 1):
            with self.subTest(position=position, error=type(error).__name__):
                events: list[str] = []

                def mark(kind: str) -> None:
                    events.append(kind)
                    if len(events) == position:
                        raise error

                def python_string(value: JsonValue) -> str:
                    mark("str")
                    return str(value)

                def python_float(value: JsonValue) -> float:
                    mark("float")
                    assert isinstance(value, (str, int, float))
                    return float(value)

                def python_int(value: JsonValue) -> int:
                    mark("int")
                    assert isinstance(value, (str, int, float))
                    return int(value)

                def python_bool(value: JsonValue) -> bool:
                    mark("bool")
                    return bool(value)

                with patch("src.conversion.font_metadata._python_string", side_effect=python_string), \
                        patch("src.conversion.font_metadata._python_float", side_effect=python_float), \
                        patch("src.conversion.font_metadata._python_int", side_effect=python_int), \
                        patch("src.conversion.font_metadata.bool", side_effect=python_bool, create=True):
                    with self.assertRaises(type(error)) as raised:
                        project_font_conversion_fields(metadata)
                self.assertIs(raised.exception, error)
                self.assertEqual(events, expected_order[:position])

    def test_first_numeric_failure_precedes_invalid_later_field(self) -> None:
        metadata = _decode_metadata(
            '{"fontName":"Arial","name":"font","size":"bad-size","AntiAlias":null,"TTFName":[null]}'
        )
        with self.assertRaises(ValueError) as raised:
            project_font_conversion_fields(metadata)
        self.assertIn("bad-size", str(raised.exception))

    def test_required_deep_container_repr_matches_python_and_huge_integer_coercion_is_delayed(self) -> None:
        deep: list[object] = []
        cursor = deep
        for _ in range(sys.getrecursionlimit() + 20):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        raw: dict[str, object] = {"fontName": deep, "name": "font"}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="deep-name.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_font_metadata(document.value, source_context=document.source_path)
        self.assertEqual(metadata.font_name, "")
        try:
            expected_name = str(deep)
        except RecursionError:
            with self.assertRaises(RecursionError):
                project_font_conversion_fields(metadata)
        else:
            self.assertEqual(project_font_conversion_fields(metadata).font_name, expected_name)

        digit_limit = sys.get_int_max_str_digits()
        huge = 10 ** ((digit_limit or 4300) + 1)
        raw = {"fontName": huge, "name": "font"}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="huge-name.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_font_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data["fontName"], huge)
        if digit_limit:
            with self.assertRaises(ValueError):
                project_font_conversion_fields(metadata)
        else:
            self.assertEqual(project_font_conversion_fields(metadata).font_name, str(huge))

    def test_parent_path_is_strict_and_exact_without_folder_normalization(self) -> None:
        paths = ("", "folders/Fonts/Ångström.yy", "Folders/Fonts/A.YY",
                 "folders\\Fonts\\A.yy", " folders/Fonts/A.yy ", "folders/Fonts/A\\Sub.yy")
        for path in paths:
            with self.subTest(path=path):
                metadata = _decode_metadata(json.dumps({"parent": {"path": path}}))
                self.assertEqual(metadata.parent_path, path)
        for source in (
            "{}", '{"parent":null}', '{"parent":true}', '{"parent":7}', '{"parent":[]}',
            '{"parent":"folders/Fonts/A.yy"}', '{"parent":{}}', '{"parent":{"path":null}}',
            '{"parent":{"path":true}}', '{"parent":{"path":7}}', '{"parent":{"path":[]}}',
            '{"parent":{"path":{}}}',
        ):
            with self.subTest(source=source):
                self.assertEqual(_decode_metadata(source).parent_path, "")

    def test_context_is_forwarded_to_parent_accessors_and_only_field_errors_default(self) -> None:
        metadata = _decode_metadata('{"parent":{"path":"folders/Fonts/A.yy"}}')
        error = RuntimeError("accessor failure")
        with patch("src.conversion.font_metadata.required_object", side_effect=error) as accessor:
            with self.assertRaises(RuntimeError) as raised:
                parse_gamemaker_font_metadata(metadata.raw_data, source_context="absolute/font.yy")
        self.assertIs(raised.exception, error)
        accessor.assert_called_once_with(metadata.raw_data, "parent", source_path="absolute/font.yy")

    def test_raw_identity_order_and_captured_scalar_provenance_survive_later_raw_mutation(self) -> None:
        document = decode_gamemaker_json(
            '{"extra":{"last":[null,true],"first":2},"fontName":"Arial","name":[{"z":1,"a":2}],"size":7}',
            source_path="identity.yy",
        )
        assert isinstance(document.value, dict)
        raw = document.value
        raw_name = raw["name"]
        assert isinstance(raw_name, list)
        metadata = parse_gamemaker_font_metadata(raw, source_context=document.source_path)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["extra"], raw["extra"])
        self.assertEqual(list(metadata.raw_data), ["extra", "fontName", "name", "size"])
        raw["fontName"] = "replacement"
        raw["size"] = 100
        raw["name"] = "replaced name"
        raw_name.append(None)
        projected = project_font_conversion_fields(metadata)
        self.assertEqual(metadata.font_name, "Arial")
        self.assertEqual(metadata.size_number, 7)
        self.assertEqual(projected.font_name, "Arial")
        self.assertEqual(projected.size, 7.0)
        self.assertEqual(projected.name, "[{'z': 1, 'a': 2}, None]")

    def test_shared_known_and_unknown_containers_stay_shared_after_actual_validation(self) -> None:
        shared: list[object] = [{"last": None, "first": True}]
        raw: dict[str, object] = {"fontName": "Arial", "name": shared, "TTFName": shared, "unknown": shared}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="shared-font.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_font_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["name"], shared)
        self.assertIs(metadata.raw_data["TTFName"], shared)
        self.assertIs(metadata.raw_data["unknown"], shared)
        shared.append("late")
        projected = project_font_conversion_fields(metadata)
        self.assertEqual(projected.name, "[{'last': None, 'first': True}, 'late']")
        self.assertEqual(projected.ttf_name, projected.name)

    def test_1600_deep_unknown_metadata_keeps_identity_without_changing_recursion_limit(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        deep: list[object] = []
        cursor = deep
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cursor.append("unknown leaf")
        raw: dict[str, object] = {"fontName": "Arial", "name": "font", "unknown": deep}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="deep-font.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_font_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], deep)
        self.assertEqual(project_font_conversion_fields(metadata).font_name, "Arial")
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_actual_decoder_rejects_unsupported_values_and_nonstring_keys_before_capture(self) -> None:
        cases: tuple[tuple[dict[str, object], JsonPath, str], ...] = (
            ({"fontName": b"invalid"}, ("fontName",), "unsupported-type"),
            ({"size": (12,)}, ("size",), "unsupported-type"),
            ({"unknown": [{"bad": object()}]}, ("unknown", 0, "bad"), "unsupported-type"),
            ({"parent": {7: "bad key"}}, ("parent",), "non-string-key"),
        )
        for raw, path, reason in cases:
            with self.subTest(path=path):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="invalid-font.yy")
                self.assertEqual(raised.exception.source_path, "invalid-font.yy")
                self.assertEqual(raised.exception.field_path, path)
                self.assertEqual(raised.exception.reason, reason)

    def test_actual_decoder_rejects_known_and_unknown_ancestor_cycles(self) -> None:
        for key in ("name", "unknown"):
            with self.subTest(key=key):
                raw: dict[str, object] = {"fontName": "Arial"}
                raw[key] = [raw]
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="cycle-font.yy")
                self.assertEqual(raised.exception.source_path, "cycle-font.yy")
                self.assertEqual(raised.exception.field_path, (key, 0))
                self.assertEqual(raised.exception.reason, "cycle")

    def test_actual_decoder_root_shapes_and_malformed_input_stay_boundary_owned(self) -> None:
        for source in ("null", "false", "true", "7", "1.5", '"text"', "[]"):
            with self.subTest(source=source):
                document = decode_gamemaker_json(source, source_path="root-font.yy")
                self.assertNotIsInstance(document.value, dict)
                self.assertEqual(document.source_path, "root-font.yy")
        for source in ('{"fontName":}', '{"name":"font"} trailing', "\ufeff{}"):
            with self.subTest(source=source):
                with self.assertRaises(json.JSONDecodeError):
                    decode_gamemaker_json(source, source_path="malformed-font.yy")

    def test_leaf_dependencies_and_types_stay_within_stdlib_and_two_json_leaves(self) -> None:
        path = pathlib.Path(__file__).resolve().parents[1] / "src" / "conversion" / "font_metadata.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed = {"src.conversion.json_fields", "src.conversion.json_values"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                assert node.module is not None
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.split(".")[0] == "src":
                    self.assertIn(module, allowed)
                else:
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)
        self.assertFalse(any(
            isinstance(node, ast.Name) and node.id in {"Any", "object", "cast"}
            or isinstance(node, ast.Attribute) and node.attr in {"Any", "cast"}
            for node in ast.walk(tree)
        ))
        self.assertNotIn("type: ignore", source)
        self.assertNotIn("pyright: ignore", source)
