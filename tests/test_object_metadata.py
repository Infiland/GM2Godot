import dataclasses
import math
import unittest
from typing import overload

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.object_metadata import (
    GameMakerObjectMetadata,
    capture_gamemaker_event_mapping_inputs,
    capture_gamemaker_event_type,
    capture_gamemaker_object_resource_reference,
    gamemaker_event_integer,
    parse_gamemaker_object_metadata,
    project_gamemaker_input_event_fields,
)


class _ObservedObject(dict[str, JsonValue]):
    def __init__(self, values: JsonObject, trace: list[str]) -> None:
        super().__init__(values)
        self.trace = trace

    @overload
    def get(self, key: str, default: None = None, /) -> JsonValue: ...

    @overload
    def get(self, key: str, default: JsonValue, /) -> JsonValue: ...

    @overload
    def get[T](self, key: str, default: T, /) -> JsonValue | T: ...

    def get[T](self, key: str, /, *defaults: T) -> JsonValue | T:
        self.trace.append(key)
        if defaults:
            return super().get(key, defaults[0])
        return super().get(key)

    def __contains__(self, key: object, /) -> bool:
        self.trace.append(f"contains:{key}")
        return super().__contains__(key)


class TestObjectMetadata(unittest.TestCase):
    def test_model_fields_defaults_fresh_raw_and_frozen_identity(self) -> None:
        self.assertEqual(
            [item.name for item in dataclasses.fields(GameMakerObjectMetadata)],
            ["sprite_name", "parent_object_name", "event_count", "persistent", "solid", "raw_data", "source_context"],
        )
        first = GameMakerObjectMetadata()
        second = GameMakerObjectMetadata()
        self.assertEqual((first.sprite_name, first.parent_object_name, first.event_count), (None, None, 0))
        self.assertFalse(first.persistent)
        self.assertFalse(first.solid)
        self.assertIsNot(first.raw_data, second.raw_data)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(first, "solid", True)

    def test_summary_reads_references_events_then_persistent_solid(self) -> None:
        trace: list[str] = []
        data = _ObservedObject(
            {"spriteId": {"name": "s"}, "parentObjectId": {"name": "o"}, "eventList": [{}, None],
             "persistent": [0], "solid": ""}, trace,
        )
        metadata = parse_gamemaker_object_metadata(data, source_context="objects/o/o.yy")
        self.assertEqual(trace, ["spriteId", "parentObjectId", "eventList", "persistent", "solid"])
        self.assertEqual((metadata.sprite_name, metadata.parent_object_name, metadata.event_count), ("s", "o", 1))
        self.assertTrue(metadata.persistent)
        self.assertFalse(metadata.solid)
        self.assertIs(metadata.raw_data, data)

    def test_decoded_unknown_children_order_and_native_nonfinite_are_preserved(self) -> None:
        document = decode_gamemaker_json(
            '{"unknown":{"items":[NaN,Infinity,-Infinity]},"spriteId":{"name":"s"},}',
            source_path="objects/o/o.yy",
        )
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_object_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, document.value)
        self.assertIs(metadata.raw_data["unknown"], document.value["unknown"])
        self.assertEqual(list(metadata.raw_data), ["unknown", "spriteId"])
        unknown = metadata.raw_data["unknown"]
        assert isinstance(unknown, dict)
        items = unknown["items"]
        assert isinstance(items, list)
        number = items[0]
        assert isinstance(number, float)
        self.assertTrue(math.isnan(number))
        self.assertEqual(items[1:], [float("inf"), -float("inf")])

    def test_summary_wrong_kinds_and_object_only_events(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 2, 2.5, "reference", [], [1])
        for value in values:
            with self.subTest(kind=type(value).__name__):
                metadata = parse_gamemaker_object_metadata(
                    {"spriteId": value, "parentObjectId": {"name": value}, "eventList": value},
                    source_context="x.yy",
                )
                self.assertIsNone(metadata.sprite_name)
                self.assertEqual(metadata.parent_object_name, value if isinstance(value, str) and value else None)
                self.assertEqual(metadata.event_count, 0)
        metadata = parse_gamemaker_object_metadata({"eventList": [1, {}, [], {"eventType": 0}]}, source_context="x")
        self.assertEqual(metadata.event_count, 2)

    def test_reference_capture_path_name_membership_order_and_raw_identity(self) -> None:
        trace: list[str] = []
        raw = _ObservedObject({"path": None, "name": ["legacy"]}, trace)
        reference = capture_gamemaker_object_resource_reference(raw, source_context="x.yy")
        self.assertEqual(trace, ["path", "name", "contains:path"])
        self.assertTrue(reference.path_present)
        self.assertTrue(reference.is_object)
        self.assertIs(reference.raw_value, raw)
        self.assertIs(reference.name_value, raw["name"])

    def test_reference_missing_path_is_distinct_from_explicit_null(self) -> None:
        missing = capture_gamemaker_object_resource_reference({"name": "s"}, source_context="x")
        explicit = capture_gamemaker_object_resource_reference({"name": "s", "path": None}, source_context="x")
        self.assertFalse(missing.path_present)
        self.assertTrue(explicit.path_present)
        values: tuple[JsonValue, ...] = (None, True, 1, "s", [])
        for value in values:
            self.assertFalse(capture_gamemaker_object_resource_reference(value, source_context="x").is_object)

    def test_summary_context_is_provenance_not_repr_or_equality(self) -> None:
        a = parse_gamemaker_object_metadata({}, source_context="a.yy")
        b = parse_gamemaker_object_metadata({}, source_context="b.yy")
        self.assertEqual(a, b)
        self.assertNotIn("source_context", repr(a))
        self.assertEqual(a.source_context, "a.yy")

    def test_event_capture_keeps_native_and_text_scalars_without_coercion(self) -> None:
        for value in (None, True, 1.25, "2"):
            event: JsonObject = {"eventType": value, "eventNum": value}
            fields = capture_gamemaker_event_mapping_inputs(event)
            self.assertIs(fields.event_type, value)
            self.assertIs(fields.event_num, value)
            self.assertEqual(fields.event_key(), (value, value))

    def test_mapping_capture_reads_two_fields_but_type_capture_only_one(self) -> None:
        trace: list[str] = []
        event = _ObservedObject({"eventType": 5, "eventNum": []}, trace)
        fields = capture_gamemaker_event_mapping_inputs(event)
        self.assertEqual(trace, ["eventType", "eventNum"])
        self.assertEqual(fields.type_key(), 5)
        with self.assertRaisesRegex(TypeError, "unhashable type: 'list'"):
            fields.event_key()
        trace.clear()
        self.assertEqual(capture_gamemaker_event_type(event), 5)
        self.assertEqual(trace, ["eventType"])

    def test_input_projection_retains_original_integer_read_and_error_order(self) -> None:
        trace: list[str] = []
        event = _ObservedObject({"eventType": "5", "eventNum": 65.9}, trace)
        fields = project_gamemaker_input_event_fields(event)
        self.assertEqual((fields.event_type, fields.event_num), (5, 65))
        self.assertEqual(trace, ["eventType", "eventNum"])
        trace.clear()
        event["eventType"] = "invalid"
        with self.assertRaises(ValueError):
            project_gamemaker_input_event_fields(event)
        self.assertEqual(trace, ["eventType"])

    def test_integer_conversion_preserves_null_container_nonfinite_failures(self) -> None:
        values: tuple[JsonValue, ...] = (None, [], {})
        for value in values:
            with self.subTest(kind=type(value).__name__), self.assertRaises(TypeError):
                gamemaker_event_integer(value)
        with self.assertRaises(ValueError):
            gamemaker_event_integer(float("nan"))
        with self.assertRaises(OverflowError):
            gamemaker_event_integer(float("inf"))
        self.assertEqual(gamemaker_event_integer(True), 1)
        self.assertEqual(gamemaker_event_integer(-2.9), -2)
