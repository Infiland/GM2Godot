import dataclasses
import math
import unittest
from collections.abc import Callable
from typing import overload
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonArray, JsonObject, JsonValue, JsonValueError
from src.conversion.room_metadata import (
    RoomArchitectureLayerFields,
    RoomAssetFields,
    RoomInstanceFields,
    RoomLayerFields,
    RoomPhysicsSettingsFields,
    RoomSettingsFields,
    RoomViewFields,
    RoomViewSettingsFields,
    capture_optional_room_metadata,
    capture_room_creation_code_value,
    capture_room_index_fields,
    capture_room_layer_header,
    capture_room_render_layer_name,
    capture_room_summary_settings,
    iter_room_field_values,
    iter_room_layer_summary_fields,
    project_room_summary_fields,
    room_creation_order_name,
    room_inherited_item_key,
    room_inherited_reference_name,
    room_object_at_get,
    room_object_items,
    room_value_length,
)


class _ObservedObject(dict[str, JsonValue]):
    def __init__(
        self, values: JsonObject, trace: list[str], label: str,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(values)
        self.trace = trace
        self.label = label
        self.callback = callback

    @overload
    def get(self, key: str, default: None = None, /) -> JsonValue: ...

    @overload
    def get(self, key: str, default: JsonValue, /) -> JsonValue: ...

    @overload
    def get[T](self, key: str, default: T, /) -> JsonValue | T: ...

    def get[T](self, key: str, /, *defaults: T) -> JsonValue | T:
        self.trace.append(f"{self.label}:{key}:{len(defaults)}")
        if self.callback is not None:
            self.callback(key)
        return super().get(key, defaults[0]) if defaults else super().get(key)

    def __contains__(self, key: object) -> bool:
        self.trace.append(f"{self.label}:contains:{key}")
        return super().__contains__(key)


class TestRoomMetadata(unittest.TestCase):
    def test_index_capture_waits_for_creation_code_callback_and_preserves_shapes(self) -> None:
        data: JsonObject = {"creationCodeFile": [1], "roomSettings": "bad", "views": {"wrong": True}}
        rejected = capture_room_creation_code_value(data)
        self.assertIs(rejected, data["creationCodeFile"])
        replacement: JsonArray = [{"name": "later"}]
        data["layers"] = replacement
        fields = capture_room_index_fields(data, source_context="room.yy")
        self.assertEqual(fields.room_settings, "bad")
        self.assertIs(fields.views, data["views"])
        self.assertIs(fields.layers, replacement)
        self.assertIs(fields.raw_data, data)
        self.assertEqual(fields.source_context, "room.yy")

    def test_falsy_index_containers_are_fresh_but_summary_retains_empty_object(self) -> None:
        empty: JsonObject = {}
        data: JsonObject = {"roomSettings": empty, "views": None, "layers": False}
        first = capture_room_index_fields(data, source_context="a")
        second = capture_room_index_fields(data, source_context="b")
        self.assertIsNot(first.room_settings, empty)
        self.assertIsNot(first.room_settings, second.room_settings)
        self.assertEqual(first.views, [])
        self.assertEqual(first.layers, [])
        self.assertIs(capture_room_summary_settings(data, source_context="a").raw_settings, empty)

    def test_index_get_order_and_defaults_are_literal(self) -> None:
        trace: list[str] = []
        data = _ObservedObject({}, trace, "root")
        capture_room_index_fields(data, source_context="r")
        self.assertEqual(trace, [f"root:{key}:{default}" for key, default in (
            ("roomSettings", 0), ("physicsSettings", 0), ("viewSettings", 0),
            ("views", 0), ("layers", 0), ("instanceCreationOrder", 0),
            ("parentRoom", 0), ("inheritCode", 1), ("inheritCreationOrder", 1),
            ("inheritLayers", 1), ("isDnd", 1),
        )])

    def test_summary_preorder_yields_before_child_get_and_summary_reads(self) -> None:
        trace: list[str] = []
        settings = _ObservedObject({"Width": True, "Height": "480"}, trace, "settings")
        layer = _ObservedObject({"name": "outer", "depth": False}, trace, "layer")
        data = _ObservedObject({"roomSettings": settings, "layers": [layer]}, trace, "root")
        captured = capture_room_summary_settings(data, source_context="r")
        layers = iter_room_layer_summary_fields(data.get("layers"), source_context="r")
        first = next(layers)
        self.assertIs(first.raw_data, layer)
        self.assertIs(first.depth, False)
        self.assertNotIn("layer:layers:0", trace)
        child: JsonObject = {"%Name": "child", "resourceType": "GMRAssetLayer"}
        layer["layers"] = [child]
        tail = list(layers)
        self.assertEqual([item.name for item in tail], ["child"])
        fields = project_room_summary_fields(data, captured, source_context="r")
        self.assertIs(fields.width, True)
        self.assertEqual(fields.height, 0)
        self.assertLess(trace.index("layer:layers:0"), trace.index("settings:Width:0"))

    def test_summary_and_renderer_type_and_name_profiles_differ(self) -> None:
        data: JsonObject = {"%Name": 9, "name": "fallback", "resourceType": 5, "$GMRAssetLayer": "v"}
        self.assertEqual(capture_room_render_layer_name(data), "Layer")
        header = capture_room_layer_header(data, name="Layer", source_context="r")
        self.assertEqual(header.resource_type, 5)
        summary = list(iter_room_layer_summary_fields([data], source_context="r"))[0]
        self.assertEqual(summary.name, "fallback")
        self.assertEqual(summary.resource_type, "GMRAssetLayer")

    def test_name_allocation_and_warning_can_change_later_live_fields(self) -> None:
        trace: list[str] = []
        layer = _ObservedObject({"name": "old", "resourceType": "unknown", "x": 1}, trace, "layer")
        name = capture_room_render_layer_name(layer)
        trace.append("allocate")
        header = capture_room_layer_header(layer, name=name, source_context="r")
        layer["x"] = 42
        fields = RoomLayerFields(layer, "r")
        self.assertEqual(header.name, "old")
        self.assertEqual(fields.x, 42)
        self.assertEqual(trace[:4], ["layer:%Name:0", "layer:name:0", "allocate", "layer:resourceType:0"])
        self.assertEqual(trace[-1], "layer:x:1")

    def test_named_views_construct_without_reads_and_reread_live(self) -> None:
        trace: list[str] = []
        raw = _ObservedObject({"x": 1}, trace, "raw")
        fields = RoomInstanceFields(raw, "r")
        self.assertEqual(trace, [])
        self.assertEqual(fields.x, 1)
        raw["x"] = 2
        self.assertEqual(fields.x, 2)
        self.assertEqual(trace, ["raw:x:1", "raw:x:1"])

    def test_camera_reference_keeps_successful_second_name_get(self) -> None:
        trace: list[str] = []
        count = 0
        def mutate(key: str) -> None:
            nonlocal count
            if key == "name":
                count += 1
                if count == 2:
                    reference["name"] = 23
        reference = _ObservedObject({"name": "object"}, trace, "reference", mutate)
        self.assertEqual(RoomViewFields({"objectId": reference}, "r").object_name, 23)
        self.assertEqual(trace, ["reference:name:0", "reference:name:0"])

    def test_particle_reference_keeps_condition_then_second_get(self) -> None:
        trace: list[str] = []
        raw = _ObservedObject({"particleSystemId": {"name": "first"}}, trace, "asset")
        fields = RoomAssetFields(raw, "r")
        self.assertEqual(fields.particle_system_id, {"name": "first"})
        self.assertEqual(trace, ["asset:particleSystemId:0", "asset:particleSystemId:0"])

    def test_optional_fields_keep_membership_before_get_missing_vs_null(self) -> None:
        trace: list[str] = []
        raw = _ObservedObject({"null": None}, trace, "raw")
        missing = capture_optional_room_metadata(raw, "missing")
        null = capture_optional_room_metadata(raw, "null")
        self.assertEqual(dataclasses.asdict(missing), {"present": False, "value": None})
        self.assertEqual(dataclasses.asdict(null), {"present": True, "value": None})
        self.assertEqual(trace, ["raw:contains:missing", "raw:contains:null", "raw:null:0"])

    def test_native_get_failures_retain_message_name_and_object(self) -> None:
        values: JsonArray = [None, False, 5, 1.5, "bad", []]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(AttributeError) as caught:
                    _ = RoomSettingsFields(value, "r").width
                self.assertEqual(str(caught.exception), f"'{type(value).__name__}' object has no attribute 'get'")
                self.assertEqual(caught.exception.name, "get")
                self.assertIs(caught.exception.obj, value)

    def test_direct_iteration_preserves_native_nonarray_behaviors(self) -> None:
        self.assertEqual(list(iter_room_field_values("ab")), ["a", "b"])
        self.assertEqual(list(iter_room_field_values({"b": 1, "a": 2})), ["b", "a"])
        for value in (None, True, 1, 2.0):
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "object is not iterable"):
                list(iter_room_field_values(value))

    def test_forgiving_collection_is_fresh_with_same_children(self) -> None:
        child: JsonObject = {"unknown": [True, None]}
        array: JsonArray = [0, child, "ignored"]
        first = room_object_items(array)
        second = room_object_items(array)
        self.assertIsNot(first, second)
        self.assertIs(first[0], child)
        self.assertEqual(room_object_items({"wrong": child}), [])

    def test_native_len_preserves_wrong_shape_failure(self) -> None:
        self.assertEqual(room_value_length("abc"), 3)
        with self.assertRaisesRegex(TypeError, "object of type 'int' has no len"):
            room_value_length(4)
        self.assertEqual(RoomLayerFields({"tiles": {"TileCompressedData": "abc"}}, "r").tile_data.compressed_count, 3)

    def test_observer_defaults_stay_distinct_and_short_circuitable(self) -> None:
        trace: list[str] = []
        raw = _ObservedObject({}, trace, "layer")
        renderer = RoomLayerFields(raw, "r")
        observer = RoomArchitectureLayerFields(raw, "r")
        self.assertIsNone(renderer.htiled)
        self.assertIs(observer.htiled, False)
        self.assertEqual(renderer.hspeed, 0)
        self.assertIsNone(observer.hspeed)
        self.assertEqual(trace, ["layer:htiled:0", "layer:htiled:1", "layer:hspeed:1", "layer:hspeed:0"])
        self.assertFalse(RoomViewSettingsFields({}, "r").enable_views)
        self.assertFalse(RoomPhysicsSettingsFields({}, "r").physics_world)

    def test_reference_and_item_key_precedence_stays_domain_specific(self) -> None:
        self.assertEqual(room_inherited_reference_name({"name": "", "path": "rooms/r/r.yy"}), "r")
        self.assertEqual(room_inherited_item_key({"inheritedItemId": {"name": "first"}, "%Name": "later"}), "first")
        self.assertIsNone(room_creation_order_name({"%Name": 3, "name": "ignored"}))

    def test_actual_decoder_unknown_deep_data_keeps_identity_and_native_numbers(self) -> None:
        data = decode_gamemaker_json('{"roomSettings":{"Width":true,"Height":1e999},"unknown":{"deep":[null,{"x":-0.0}]},}', source_path="r.yy").value
        assert isinstance(data, dict)
        fields = capture_room_index_fields(data, source_context="r.yy")
        self.assertIs(fields.raw_data, data)
        self.assertIs(fields.raw_data["unknown"], data["unknown"])
        summary = project_room_summary_fields(data, capture_room_summary_settings(data, source_context="r.yy"), source_context="r.yy")
        self.assertIs(summary.width, True)
        self.assertEqual(summary.height, 0)
        live = RoomSettingsFields(fields.room_settings, "r.yy")
        self.assertTrue(isinstance(live.height, float) and math.isinf(live.height))

    def test_shallow_capture_does_not_revalidate_cycles_or_coerce_huge_ints(self) -> None:
        huge = 10 ** 5000
        raw: JsonObject = {"roomSettings": {"Width": huge}}
        raw["unknown"] = raw
        fields = capture_room_index_fields(raw, source_context="r")
        self.assertIs(fields.raw_data["unknown"], raw)
        self.assertIs(RoomSettingsFields(fields.room_settings, "r").width, huge)
        self.assertIs(room_object_at_get(raw), raw)

    def test_overridden_get_control_exception_escapes_unchanged(self) -> None:
        error = KeyboardInterrupt("control")
        def fail(_key: str) -> None:
            raise error
        fields = RoomLayerFields(_ObservedObject({}, [], "layer", fail), "r")
        with self.assertRaises(KeyboardInterrupt) as caught:
            _ = fields.x
        self.assertIs(caught.exception, error)

    def test_real_boundary_accepts_deep_unknown_native_graph_without_copy(self) -> None:
        value: JsonValue = None
        for _ in range(1500):
            value = [value]
        raw: JsonObject = {"unknown": value, "roomSettings": {"Width": 3}}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
            decoded = decode_gamemaker_json("{}", source_path="rooms/deep.yy").value
        assert isinstance(decoded, dict)
        fields = capture_room_index_fields(decoded, source_context="rooms/deep.yy")
        self.assertIs(fields.raw_data, raw)
        self.assertIs(fields.raw_data["unknown"], value)

    def test_real_boundary_rejects_unsupported_nested_value_before_room_capture(self) -> None:
        unsupported = object()
        with patch("src.conversion.gamemaker_json.json.loads", return_value={"layers": [{"bad": unsupported}]}):
            with self.assertRaises(JsonValueError) as caught:
                decode_gamemaker_json("{}", source_path="rooms/bad.yy")
        self.assertEqual(caught.exception.source_path, "rooms/bad.yy")
        self.assertEqual(caught.exception.field_path, ("layers", 0, "bad"))
