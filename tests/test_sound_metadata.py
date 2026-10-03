import ast
import dataclasses
import json
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonPath, JsonValue, JsonValueError
from src.conversion.sound_metadata import (
    GameMakerSoundMetadata,
    SoundConversionFields,
    parse_gamemaker_sound_metadata,
    project_sound_conversion_fields,
)


def _decode_metadata(source: str) -> GameMakerSoundMetadata:
    document = decode_gamemaker_json(source, source_path="sounds/snd/snd.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_sound_metadata(document.value, source_context=document.source_path)


def _project(metadata: GameMakerSoundMetadata) -> SoundConversionFields:
    return project_sound_conversion_fields(metadata, sound_file="clip.wav")


class TestSoundMetadata(unittest.TestCase):
    def test_empty_capture_is_frozen_and_required_name_conversion_is_deferred(self) -> None:
        metadata = _decode_metadata("{}")
        self.assertEqual(
            (metadata.sound_file, metadata.audio_group, metadata.parent_path, metadata.source_name),
            ("", "", "", ""),
        )
        self.assertIsNone(metadata.sound_file_value)
        self.assertEqual(metadata.source_context, "sounds/snd/snd.yy")
        self.assertIsNot(GameMakerSoundMetadata().raw_data, GameMakerSoundMetadata().raw_data)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(metadata, "sound_file", "changed.wav")
        with self.assertRaises(KeyError) as raised:
            _project(metadata)
        self.assertEqual(raised.exception.args, ("name",))

    def test_public_records_keep_exact_field_order_and_private_context_visibility(self) -> None:
        self.assertEqual(
            [f.name for f in dataclasses.fields(GameMakerSoundMetadata)],
            ["sound_file", "audio_group", "parent_path", "source_name", "raw_data",
             "source_context", "_conversion_inputs"],
        )
        fields = dataclasses.fields(SoundConversionFields)
        self.assertEqual(
            [f.name for f in fields],
            ["name", "sound_file", "volume", "sound_type", "bit_depth", "bit_rate",
             "sample_rate", "compression", "preload", "audio_group", "duration"],
        )
        self.assertTrue(all(f.default is dataclasses.MISSING for f in fields))
        metadata = _decode_metadata('{"name":"snd","soundFile":"clip.wav"}')
        other_context = parse_gamemaker_sound_metadata(metadata.raw_data, source_context="other.yy")
        self.assertEqual(metadata, other_context)
        self.assertNotIn("source_context=", repr(metadata))
        self.assertNotIn("_conversion_inputs=", repr(metadata))
        converted = _project(metadata)
        self.assertEqual(
            converted,
            SoundConversionFields("snd", "clip.wav", 1.0, 0, 16, 128, 44100, 0, True,
                                  "audiogroup_default", 0.0),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(converted, "volume", 2.0)

    def test_reflected_missing_and_null_capture_stores_only_json_primitives(self) -> None:
        for source, present in (
            ("{}", False),
            ('{"name":null,"soundFile":null,"volume":null,"type":null,"bitDepth":null,'
             '"bitRate":null,"sampleRate":null,"compression":null,"preload":null,'
             '"audioGroupId":null,"duration":null}', True),
        ):
            with self.subTest(source=source):
                metadata = _decode_metadata(source)
                reflected = decode_gamemaker_json(
                    json.dumps(dataclasses.asdict(metadata)), source_path="reflection.json"
                ).value
                assert isinstance(reflected, dict)
                inputs = reflected["_conversion_inputs"]
                assert isinstance(inputs, dict)
                self.assertEqual(
                    list(inputs),
                    ["name", "sound_file", "volume", "sound_type", "bit_depth", "bit_rate",
                     "sample_rate", "compression", "preload", "audio_group", "duration"],
                )
                for key, value in inputs.items():
                    if key != "audio_group":
                        self.assertEqual(value, {"present": present, "value": None})
                self.assertEqual(inputs["audio_group"], {
                    "root": {"present": present, "value": None},
                    "name": {"present": False, "value": None},
                })
                self.assertNotIn('"state"', json.dumps(inputs))
                json.dumps(dataclasses.astuple(metadata))

    def test_required_name_missing_precedes_every_later_conversion(self) -> None:
        metadata = _decode_metadata(
            '{"soundFile":"clip.wav","volume":"bad","audioGroupId":null,"duration":null}'
        )
        with self.assertRaises(KeyError) as raised:
            _project(metadata)
        self.assertEqual(raised.exception.args, ("name",))

    def test_required_null_and_container_names_use_python_string_and_key_order(self) -> None:
        cases = (
            ("null", "None"),
            ('{"last":null,"first":[true,false]}', "{'last': None, 'first': [True, False]}"),
            ('[{"z":1,"a":2},null]', "[{'z': 1, 'a': 2}, None]"),
        )
        for literal, wanted in cases:
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"name":' + literal + '}')
                self.assertEqual(metadata.source_name, "")
                self.assertEqual(_project(metadata).name, wanted)

    def test_sound_file_summary_and_original_validation_value_preserve_all_shapes(self) -> None:
        for literal in ('""', '" "', '"clip.wav"', "null", "true", "7", "1.5", "[]", "{}"):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"soundFile":' + literal + '}')
                value = metadata.raw_data["soundFile"]
                self.assertIs(metadata.sound_file_value, value)
                self.assertEqual(metadata.sound_file, value if isinstance(value, str) else "")
        self.assertIsNone(_decode_metadata("{}").sound_file_value)

    def test_invalid_sound_file_capture_does_not_run_required_or_numeric_projection(self) -> None:
        for literal in ("null", "false", "7", "[]", "{}", '""'):
            with self.subTest(literal=literal):
                with patch("src.conversion.sound_metadata._python_string", side_effect=AssertionError("eager str")), \
                        patch("src.conversion.sound_metadata._python_float", side_effect=AssertionError("eager float")), \
                        patch("src.conversion.sound_metadata._python_int", side_effect=AssertionError("eager int")), \
                        patch("src.conversion.sound_metadata._audio_group_name", side_effect=AssertionError("eager group")):
                    metadata = _decode_metadata(
                        '{"soundFile":' + literal + ',"volume":"bad","audioGroupId":null}'
                    )
                    self.assertEqual(metadata.source_name, "")
                    self.assertIs(metadata.sound_file_value, metadata.raw_data["soundFile"])

    def test_projection_uses_owner_validated_sound_file_without_coercion_or_raw_reindex(self) -> None:
        metadata = _decode_metadata('{"name":"snd","soundFile":{"invalid":true}}')
        converted = project_sound_conversion_fields(metadata, sound_file="owner-validated.ogg")
        self.assertEqual(converted.sound_file, "owner-validated.ogg")
        self.assertEqual(metadata.sound_file, "")
        self.assertIs(metadata.sound_file_value, metadata.raw_data["soundFile"])

    def test_strict_source_name_and_audio_group_summaries_differ_from_converter_strings(self) -> None:
        cases = (
            ('"snd"', '"group"', "snd", "group", "snd", "group"),
            ('" "', '" "', " ", " ", " ", " "),
            ('""', '""', "", "", "", ""),
            ("null", "null", "", "", "None", "None"),
            ("true", "false", "", "", "True", "False"),
            ("7", "1.5", "", "", "7", "1.5"),
            ('{"b":2,"a":1}', "[]", "", "", "{'b': 2, 'a': 1}", "[]"),
        )
        for name, group, summary_name, summary_group, conversion_name, conversion_group in cases:
            with self.subTest(name=name, group=group):
                metadata = _decode_metadata('{"name":' + name + ',"audioGroupId":{"name":' + group + '}}')
                self.assertEqual(metadata.source_name, summary_name)
                self.assertEqual(metadata.audio_group, summary_group)
                converted = _project(metadata)
                self.assertEqual(converted.name, conversion_name)
                self.assertEqual(converted.audio_group, conversion_group)

    def test_audio_group_missing_root_and_missing_name_keep_only_the_legacy_default(self) -> None:
        for source in ('{"name":"snd"}', '{"name":"snd","audioGroupId":{}}'):
            with self.subTest(source=source):
                metadata = _decode_metadata(source)
                self.assertEqual(metadata.audio_group, "")
                self.assertEqual(_project(metadata).audio_group, "audiogroup_default")
        for literal, expected in (("null", "None"), ('""', ""), ("0", "0")):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"name":"snd","audioGroupId":{"name":' + literal + '}}')
                self.assertEqual(_project(metadata).audio_group, expected)

    def test_malformed_audio_group_root_keeps_late_attribute_error_name_and_object(self) -> None:
        for literal, kind in (("null", "NoneType"), ("[]", "list"), ('"group"', "str"),
                              ("true", "bool"), ("7", "int"), ("1.5", "float")):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"name":"snd","audioGroupId":' + literal + ',"duration":"bad"}')
                self.assertEqual(metadata.audio_group, "")
                events: list[str] = []

                def preload(value: JsonValue) -> bool:
                    events.append("preload")
                    return bool(value)

                def duration(value: JsonValue) -> float:
                    if events:
                        raise AssertionError("duration ran before malformed group failed")
                    assert isinstance(value, (str, int, float))
                    return float(value)

                with patch("src.conversion.sound_metadata.bool", side_effect=preload, create=True), \
                        patch("src.conversion.sound_metadata._python_float", side_effect=duration):
                    with self.assertRaises(AttributeError) as raised:
                        _project(metadata)
                self.assertEqual(events, ["preload"])
                self.assertEqual(str(raised.exception), f"'{kind}' object has no attribute 'get'")
                self.assertEqual(raised.exception.name, "get")
                self.assertIs(raised.exception.obj, metadata.raw_data["audioGroupId"])

    def test_every_earlier_numeric_error_precedes_malformed_group_and_duration(self) -> None:
        for key in ("volume", "type", "bitDepth", "bitRate", "sampleRate", "compression"):
            with self.subTest(key=key):
                metadata = _decode_metadata(
                    '{"name":"snd","' + key + '":"bad-' + key
                    + '","audioGroupId":null,"duration":null}'
                )
                with self.assertRaises(ValueError) as raised:
                    _project(metadata)
                self.assertIn("bad-" + key, str(raised.exception))

    def test_preload_control_error_precedes_malformed_group_and_duration(self) -> None:
        metadata = _decode_metadata('{"name":"snd","audioGroupId":null,"duration":"bad"}')
        error = KeyboardInterrupt("preload control")
        with patch("src.conversion.sound_metadata.bool", side_effect=error, create=True):
            with self.assertRaises(KeyboardInterrupt) as raised:
                _project(metadata)
        self.assertIs(raised.exception, error)

    def test_present_null_numeric_fields_fail_at_their_original_positions(self) -> None:
        for key in ("volume", "duration", "type", "bitDepth", "bitRate", "sampleRate", "compression"):
            with self.subTest(key=key):
                metadata = _decode_metadata('{"name":"snd","' + key + '":null}')
                with self.assertRaises(TypeError) as raised:
                    _project(metadata)
                message = (
                    "float() argument must be a string or a real number, not 'NoneType'"
                    if key in ("volume", "duration") else
                    "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"
                )
                self.assertEqual(str(raised.exception), message)
        self.assertFalse(_project(_decode_metadata('{"name":"snd","preload":null}')).preload)

    def test_wrong_numeric_container_messages_keep_original_builtin_kinds(self) -> None:
        for key in ("volume", "duration", "type", "bitDepth", "bitRate", "sampleRate", "compression"):
            for literal, kind in (("[]", "list"), ("{}", "dict")):
                with self.subTest(key=key, literal=literal):
                    metadata = _decode_metadata('{"name":"snd","' + key + '":' + literal + '}')
                    with self.assertRaises(TypeError) as raised:
                        _project(metadata)
                    expected = (
                        f"float() argument must be a string or a real number, not '{kind}'"
                        if key in ("volume", "duration") else
                        f"int() argument must be a string, a bytes-like object or a real number, not '{kind}'"
                    )
                    self.assertEqual(str(raised.exception), expected)

    def test_boolean_numeric_strings_and_fractional_integers_keep_native_coercions(self) -> None:
        cases = (("true", 1.0, 1), ("false", 0.0, 0), ('" -2 "', -2.0, -2),
                 ("-2.75", -2.75, -2), ("7", 7.0, 7))
        for literal, wanted_float, wanted_int in cases:
            with self.subTest(literal=literal):
                metadata = _decode_metadata(
                    '{"name":"snd","volume":' + literal + ',"duration":' + literal
                    + ',"type":' + literal + ',"bitDepth":' + literal + ',"bitRate":' + literal
                    + ',"sampleRate":' + literal + ',"compression":' + literal + '}'
                )
                converted = _project(metadata)
                self.assertEqual((converted.volume, converted.duration), (wanted_float, wanted_float))
                self.assertEqual(
                    (converted.sound_type, converted.bit_depth, converted.bit_rate,
                     converted.sample_rate, converted.compression), (wanted_int,) * 5,
                )
                self.assertIs(type(converted.volume), float)
                self.assertIs(type(converted.sound_type), int)
        converted = _project(_decode_metadata('{"name":"snd","volume":" 2.5e1 ","duration":"-.5"}'))
        self.assertEqual((converted.volume, converted.duration), (25.0, -0.5))

    def test_invalid_numeric_strings_are_not_coerced_during_capture(self) -> None:
        for key in ("volume", "duration", "type", "bitDepth", "bitRate", "sampleRate", "compression"):
            with self.subTest(key=key):
                metadata = _decode_metadata('{"name":"snd","' + key + '":"invalid"}')
                with self.assertRaises(ValueError):
                    _project(metadata)
        with self.assertRaises(ValueError):
            _project(_decode_metadata('{"name":"snd","type":"1.5"}'))

    def test_huge_integer_capture_is_native_and_float_overflow_is_deferred(self) -> None:
        huge = 10 ** 400
        for key in ("volume", "duration"):
            with self.subTest(key=key):
                with patch("src.conversion.sound_metadata._python_float", side_effect=AssertionError("eager float")), \
                        patch("src.conversion.sound_metadata._python_int", side_effect=AssertionError("eager int")):
                    metadata = _decode_metadata('{"name":"snd","' + key + '":' + str(huge) + '}')
                self.assertEqual(metadata.raw_data[key], huge)
                self.assertIs(type(metadata.raw_data[key]), int)
                with self.assertRaises(OverflowError):
                    _project(metadata)
        metadata = _decode_metadata(
            '{"name":"snd","type":' + str(huge) + ',"bitDepth":' + str(huge)
            + ',"bitRate":' + str(huge) + ',"sampleRate":' + str(huge)
            + ',"compression":' + str(huge) + '}'
        )
        converted = _project(metadata)
        self.assertEqual(
            (converted.sound_type, converted.bit_depth, converted.bit_rate,
             converted.sample_rate, converted.compression), (huge,) * 5,
        )

    def test_nonfinite_floats_survive_while_integer_value_and_overflow_errors_stay_late(self) -> None:
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                metadata = _decode_metadata('{"name":"snd","volume":' + literal + ',"duration":' + literal + '}')
                converted = _project(metadata)
                if literal == "NaN":
                    self.assertTrue(math.isnan(converted.volume))
                    self.assertTrue(math.isnan(converted.duration))
                else:
                    wanted = math.inf if literal == "Infinity" else -math.inf
                    self.assertEqual((converted.volume, converted.duration), (wanted, wanted))
                for key in ("type", "bitDepth", "bitRate", "sampleRate", "compression"):
                    invalid = _decode_metadata('{"name":"snd","' + key + '":' + literal + '}')
                    with self.assertRaises(ValueError if literal == "NaN" else OverflowError):
                        _project(invalid)

    def test_negative_zero_sign_survives_float_projection_and_integer_fields_truncate(self) -> None:
        converted = _project(_decode_metadata(
            '{"name":"snd","volume":-0.0,"duration":-0.0,"type":-0.0,"bitDepth":-0.0}'
        ))
        self.assertLess(math.copysign(1.0, converted.volume), 0)
        self.assertLess(math.copysign(1.0, converted.duration), 0)
        self.assertEqual((converted.sound_type, converted.bit_depth), (0, 0))

    def test_preload_missing_true_and_present_json_truthiness_remain_distinct(self) -> None:
        self.assertTrue(_project(_decode_metadata('{"name":"snd"}')).preload)
        for literal, wanted in (("null", False), ("false", False), ("0", False), ("-0.0", False),
                                ('""', False), ("[]", False), ("{}", False), ("true", True),
                                ('"false"', True), ("[null]", True), ('{"x":false}', True),
                                ("NaN", True), ("Infinity", True)):
            with self.subTest(literal=literal):
                self.assertIs(_project(_decode_metadata('{"name":"snd","preload":' + literal + '}')).preload, wanted)

    def test_all_ten_builtin_calls_run_in_the_original_eleven_field_positions(self) -> None:
        metadata = _decode_metadata('{"name":"snd"}')
        events: list[tuple[str, JsonValue]] = []

        def string(value: JsonValue) -> str:
            events.append(("str", value))
            return str(value)

        def floating(value: JsonValue) -> float:
            events.append(("float", value))
            assert isinstance(value, (str, int, float))
            return float(value)

        def integer(value: JsonValue) -> int:
            events.append(("int", value))
            assert isinstance(value, (str, int, float))
            return int(value)

        def boolean(value: JsonValue) -> bool:
            events.append(("bool", value))
            return bool(value)

        with patch("src.conversion.sound_metadata._python_string", side_effect=string), \
                patch("src.conversion.sound_metadata._python_float", side_effect=floating), \
                patch("src.conversion.sound_metadata._python_int", side_effect=integer), \
                patch("src.conversion.sound_metadata.bool", side_effect=boolean, create=True):
            converted = _project(metadata)
        self.assertEqual(events, [
            ("str", "snd"), ("float", 1.0), ("int", 0), ("int", 16), ("int", 128),
            ("int", 44100), ("int", 0), ("bool", True), ("str", "audiogroup_default"), ("float", 0.0),
        ])
        self.assertEqual(converted.sound_file, "clip.wav")

    def test_every_conversion_position_preserves_exception_identity_and_stops_later_calls(self) -> None:
        metadata = _decode_metadata('{"name":"snd"}')
        order = ["str", "float", "int", "int", "int", "int", "int", "bool", "str", "float"]
        errors: tuple[BaseException, ...] = (
            KeyError("injected"), TypeError("injected"), ValueError("injected"), OverflowError("injected"),
            RecursionError("injected"), KeyboardInterrupt("injected"), SystemExit("injected"),
            OSError("injected"), RuntimeError("injected"), AttributeError("injected"),
        )
        for position, error in enumerate(errors, 1):
            with self.subTest(position=position):
                events: list[str] = []

                def mark(kind: str) -> None:
                    events.append(kind)
                    if len(events) == position:
                        raise error

                def string(value: JsonValue) -> str:
                    mark("str")
                    return str(value)

                def floating(value: JsonValue) -> float:
                    mark("float")
                    assert isinstance(value, (str, int, float))
                    return float(value)

                def integer(value: JsonValue) -> int:
                    mark("int")
                    assert isinstance(value, (str, int, float))
                    return int(value)

                def boolean(value: JsonValue) -> bool:
                    mark("bool")
                    return bool(value)

                with patch("src.conversion.sound_metadata._python_string", side_effect=string), \
                        patch("src.conversion.sound_metadata._python_float", side_effect=floating), \
                        patch("src.conversion.sound_metadata._python_int", side_effect=integer), \
                        patch("src.conversion.sound_metadata.bool", side_effect=boolean, create=True):
                    with self.assertRaises(type(error)) as raised:
                        _project(metadata)
                self.assertIs(raised.exception, error)
                self.assertEqual(events, order[:position])

    def test_parent_path_is_strict_and_preserves_exact_spelling_before_owner_normalization(self) -> None:
        for path in ("", "folders/Sounds/Ångström.yy", "Folders/Sounds/A.YY",
                     "folders\\Sounds\\A.yy", " folders/Sounds/A.yy ", "folders/Sounds/A\\Sub.yy"):
            with self.subTest(path=path):
                metadata = _decode_metadata(json.dumps({"parent": {"path": path}}))
                self.assertEqual(metadata.parent_path, path)
        for source in ("{}", '{"parent":null}', '{"parent":true}', '{"parent":7}', '{"parent":[]}',
                       '{"parent":"folders/Sounds/A.yy"}', '{"parent":{}}', '{"parent":{"path":null}}',
                       '{"parent":{"path":true}}', '{"parent":{"path":7}}', '{"parent":{"path":[]}}'):
            with self.subTest(source=source):
                self.assertEqual(_decode_metadata(source).parent_path, "")

    def test_parent_accessors_receive_context_and_only_field_errors_default(self) -> None:
        metadata = _decode_metadata('{"parent":{"path":"folders/Sounds/A.yy"}}')
        error = RuntimeError("accessor failure")
        with patch("src.conversion.sound_metadata.required_object", side_effect=error) as accessor:
            with self.assertRaises(RuntimeError) as raised:
                parse_gamemaker_sound_metadata(metadata.raw_data, source_context="absolute/snd.yy")
        self.assertIs(raised.exception, error)
        accessor.assert_called_once_with(metadata.raw_data, "parent", source_path="absolute/snd.yy")
        with patch("src.conversion.sound_metadata.required_string", side_effect=error) as string:
            with self.assertRaises(RuntimeError) as raised:
                parse_gamemaker_sound_metadata(metadata.raw_data, source_context="absolute/snd.yy")
        self.assertIs(raised.exception, error)
        string.assert_called_once_with(
            metadata.raw_data["parent"], "path", source_path="absolute/snd.yy", field_path=("parent",)
        )

    def test_raw_identity_order_and_captured_scalar_provenance_survive_raw_replacement(self) -> None:
        metadata = _decode_metadata(
            '{"unknown":{"last":[null,true],"first":2},"name":"snd","soundFile":"clip.wav",'
            '"volume":0.5,"audioGroupId":{"name":"group","unknown":[false]}}'
        )
        raw = metadata.raw_data
        unknown = raw["unknown"]
        group = raw["audioGroupId"]
        assert isinstance(group, dict)
        self.assertEqual(list(raw), ["unknown", "name", "soundFile", "volume", "audioGroupId"])
        raw["name"] = "replacement"
        raw["soundFile"] = None
        raw["volume"] = "bad"
        group["name"] = "replacement group"
        raw["audioGroupId"] = None
        converted = _project(metadata)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], unknown)
        self.assertEqual(metadata.sound_file_value, "clip.wav")
        self.assertEqual(metadata.source_name, "snd")
        self.assertEqual((converted.name, converted.volume, converted.audio_group), ("snd", 0.5, "group"))

    def test_shared_known_and_unknown_containers_keep_identity_and_live_child_contents(self) -> None:
        shared: list[object] = [{"last": None, "first": True}]
        raw: dict[str, object] = {"name": shared, "soundFile": "clip.wav",
                                  "audioGroupId": {"name": shared}, "unknown": shared}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="shared-sound.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_sound_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["name"], shared)
        self.assertIs(metadata.raw_data["unknown"], shared)
        shared.append("late")
        converted = _project(metadata)
        self.assertEqual(converted.name, "[{'last': None, 'first': True}, 'late']")
        self.assertEqual(converted.audio_group, converted.name)

    def test_1600_deep_unknown_metadata_remains_identity_preserved_and_projection_independent(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        deep: list[object] = []
        cursor = deep
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cursor.append("unknown leaf")
        raw: dict[str, object] = {"name": "snd", "unknown": deep}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="deep-sound.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_sound_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], deep)
        self.assertEqual(_project(metadata).name, "snd")
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_deep_required_container_name_matches_original_python_runtime_string_behavior(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        deep: list[object] = []
        cursor = deep
        for _ in range(recursion_limit + 20):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        raw: dict[str, object] = {"name": deep}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            document = decode_gamemaker_json("{}", source_path="deep-name.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_sound_metadata(document.value, source_context=document.source_path)
        self.assertEqual(metadata.source_name, "")
        try:
            expected_name = str(deep)
        except RecursionError:
            with self.assertRaises(RecursionError):
                _project(metadata)
        else:
            self.assertEqual(_project(metadata).name, expected_name)
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_huge_required_or_group_integer_string_failures_remain_deferred_to_each_position(self) -> None:
        digit_limit = sys.get_int_max_str_digits()
        huge = 10 ** ((digit_limit or 4300) + 1)
        for group_name in (False, True):
            with self.subTest(group_name=group_name):
                raw: dict[str, object] = (
                    {"name": "snd", "audioGroupId": {"name": huge}}
                    if group_name else {"name": huge}
                )
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    document = decode_gamemaker_json("{}", source_path="huge-name.yy")
                assert isinstance(document.value, dict)
                metadata = parse_gamemaker_sound_metadata(document.value, source_context=document.source_path)
                if digit_limit:
                    with self.assertRaises(ValueError):
                        _project(metadata)
                else:
                    converted = _project(metadata)
                    self.assertEqual(converted.audio_group if group_name else converted.name, str(huge))

    def test_actual_decoder_rejects_unsupported_values_and_nonstring_keys_before_capture(self) -> None:
        cases: tuple[tuple[dict[str, object], JsonPath, str], ...] = (
            ({"soundFile": b"invalid"}, ("soundFile",), "unsupported-type"),
            ({"volume": (1,)}, ("volume",), "unsupported-type"),
            ({"unknown": [{"bad": object()}]}, ("unknown", 0, "bad"), "unsupported-type"),
            ({"audioGroupId": {7: "bad key"}}, ("audioGroupId",), "non-string-key"),
        )
        for raw, path, reason in cases:
            with self.subTest(path=path):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="invalid-sound.yy")
                self.assertEqual(raised.exception.source_path, "invalid-sound.yy")
                self.assertEqual(raised.exception.field_path, path)
                self.assertEqual(raised.exception.reason, reason)

    def test_actual_decoder_rejects_known_and_unknown_ancestor_cycles(self) -> None:
        for key in ("name", "audioGroupId", "unknown"):
            with self.subTest(key=key):
                raw: dict[str, object] = {}
                raw[key] = [raw]
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="cycle-sound.yy")
                self.assertEqual(raised.exception.source_path, "cycle-sound.yy")
                self.assertEqual(raised.exception.field_path, (key, 0))
                self.assertEqual(raised.exception.reason, "cycle")

    def test_actual_decoder_root_malformed_and_literal_comma_policy_stays_boundary_owned(self) -> None:
        for source in ("null", "false", "true", "7", "1.5", '"text"', "[]"):
            with self.subTest(source=source):
                document = decode_gamemaker_json(source, source_path="root-sound.yy")
                self.assertNotIsInstance(document.value, dict)
                self.assertEqual(document.source_path, "root-sound.yy")
        for source in ('{"name":}', '{"name":"snd"} trailing', "\ufeff{}"):
            with self.subTest(source=source):
                with self.assertRaises(json.JSONDecodeError):
                    decode_gamemaker_json(source, source_path="malformed-sound.yy")
        metadata = _decode_metadata('{"name":"snd","audioGroupId":{"name":"group",},}')
        self.assertEqual(_project(metadata).audio_group, "group")
        self.assertEqual(_project(_decode_metadata('{"name":",}"}')).name, "}")

    def test_leaf_dependencies_and_types_stay_within_stdlib_and_two_json_leaves(self) -> None:
        path = pathlib.Path(__file__).resolve().parents[1] / "src" / "conversion" / "sound_metadata.py"
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
