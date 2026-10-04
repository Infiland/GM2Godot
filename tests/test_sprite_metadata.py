import ast
import dataclasses
import json
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue, JsonValueError
from src.conversion.sprite_metadata import (
    GameMakerSpriteMetadata,
    SpriteAnimationFields,
    SpriteCollisionFields,
    SpriteFrameLayerFields,
    capture_sprite_atlas_frame,
    parse_gamemaker_sprite_metadata,
    parse_sprite_animation_fields,
    parse_sprite_collision_fields,
    parse_sprite_frame_layer_fields,
    select_sprite_atlas_layer,
)


def _sprite_data(source: str) -> JsonObject:
    document = decode_gamemaker_json(source, source_path="sprites/declared/renamed.yy")
    assert isinstance(document.value, dict)
    return document.value


class TestSpriteMetadata(unittest.TestCase):
    def test_summary_defaults_raw_identity_and_frozen_reflection(self) -> None:
        data = _sprite_data('{"unknown":{"shared":[1,true,null]},}')
        metadata = parse_gamemaker_sprite_metadata(data, source_context="owner.yy")
        self.assertEqual((metadata.width, metadata.height, metadata.origin), (0, 0, 0))
        self.assertIs(metadata.raw_data, data)
        self.assertIs(metadata.raw_data["unknown"], data["unknown"])
        self.assertEqual([field.name for field in dataclasses.fields(metadata)],
                         ["width", "height", "origin", "raw_data", "source_context"])
        self.assertNotIn("source_context=", repr(metadata))
        self.assertEqual(metadata, parse_gamemaker_sprite_metadata(data, source_context="other.yy"))
        self.assertIsNot(GameMakerSpriteMetadata().raw_data, GameMakerSpriteMetadata().raw_data)
        json.dumps(dataclasses.asdict(metadata))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(metadata, "width", 3)

    def test_summary_native_integer_bool_identity_and_huge_values(self) -> None:
        huge = 10 ** 500
        data: JsonObject = {"width": huge, "height": True, "origin": -123}
        metadata = parse_gamemaker_sprite_metadata(data, source_context="summary.yy")
        self.assertIs(metadata.width, huge)
        self.assertIs(metadata.height, True)
        self.assertEqual(metadata.origin, -123)
        data["width"] = 99
        self.assertIs(metadata.width, huge)
        self.assertEqual(metadata.raw_data["width"], 99)

    def test_summary_rejects_converter_strings_floats_nonfinite_and_containers(self) -> None:
        for value in ('"32"', '2.5', 'NaN', 'Infinity', '1e400', 'null', '[]', '{}'):
            with self.subTest(value=value):
                data = _sprite_data('{"width":' + value + ',"height":' + value + ',"origin":' + value + '}')
                metadata = parse_gamemaker_sprite_metadata(data, source_context="summary.yy")
                self.assertEqual((metadata.width, metadata.height, metadata.origin), (0, 0, 0))

    def test_unknown_deep_and_shared_graph_remains_identical(self) -> None:
        shared: JsonObject = {"unknown": 7}
        deep: JsonValue = shared
        for _ in range(1600):
            deep = [deep]
        data: JsonObject = {"left": shared, "right": shared, "deep": deep}
        with patch("src.conversion.gamemaker_json.json.loads", return_value=data):
            document = decode_gamemaker_json("{}", source_path="deep.yy")
        assert isinstance(document.value, dict)
        metadata = parse_gamemaker_sprite_metadata(document.value, source_context=document.source_path)
        self.assertIs(metadata.raw_data, data)
        self.assertIs(metadata.raw_data["left"], metadata.raw_data["right"])
        self.assertIs(metadata.raw_data["deep"], deep)

    def test_malformed_native_graph_is_rejected_at_real_decoder_boundary(self) -> None:
        cycle: list[JsonValue] = []
        cycle.append(cycle)
        for malformed in ({"unknown": b"bad"}, {"unknown": (1,)}, {"unknown": {1: "bad"}}, {"unknown": cycle}):
            with self.subTest(malformed_type=type(malformed["unknown"]).__name__):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=malformed):
                    with self.assertRaises(JsonValueError) as caught:
                        decode_gamemaker_json("{}", source_path="bad.yy")
                self.assertEqual(caught.exception.source_path, "bad.yy")
                self.assertEqual(caught.exception.field_path[0], "unknown")

    def test_collision_defaults_and_public_projection_order(self) -> None:
        fields = parse_sprite_collision_fields(_sprite_data("{}"))
        self.assertEqual(fields, SpriteCollisionFields(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual([field.name for field in dataclasses.fields(fields)],
                         ["collision_kind", "collision_tolerance", "bbox_mode", "bbox_left", "bbox_right",
                          "bbox_top", "bbox_bottom", "width", "height", "origin", "xorigin", "yorigin"])

    def test_collision_numeric_strings_bools_float_and_sequence_fallbacks(self) -> None:
        data = _sprite_data('{"collisionKind":"4","collisionTolerance":"bad","bboxMode":true,'
                            '"bbox_left":-2.9,"width":"32","height":false,"origin":9,'
                            '"sequence":{"xorigin":"6","yorigin":7.9}}')
        fields = parse_sprite_collision_fields(data)
        self.assertEqual((fields.collision_kind, fields.collision_tolerance, fields.bbox_mode,
                          fields.bbox_left, fields.width, fields.height, fields.xorigin, fields.yorigin),
                         (4, -1, 1, -2, 32, 0, 6, 7))
        data["xorigin"] = 3
        self.assertEqual(parse_sprite_collision_fields(data).xorigin, 3)

    def test_collision_tolerance_fallback_is_kind_specific(self) -> None:
        values: list[JsonValue] = [None, "not-a-number", [], {}]
        for kind, expected in ((0, -1), (4, -1), (1, 0), (3, 0)):
            for value in values:
                with self.subTest(kind=kind, value=value):
                    data: JsonObject = {"collisionKind": kind, "collisionTolerance": value}
                    self.assertEqual(parse_sprite_collision_fields(data).collision_tolerance, expected)

    def test_collision_nonfinite_errors_and_overflow_policy(self) -> None:
        with self.assertRaises(ValueError):
            parse_sprite_collision_fields(_sprite_data('{"width":NaN}'))
        with self.assertRaises(OverflowError):
            parse_sprite_collision_fields(_sprite_data('{"collisionTolerance":Infinity}'))
        with self.assertRaises(TypeError) as caught:
            parse_sprite_collision_fields(_sprite_data('{"width":null}'))
        self.assertEqual(str(caught.exception),
                         "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'")

    def test_collision_conversion_order_and_exception_identity(self) -> None:
        error = RuntimeError("first failed coercion")
        with patch("src.conversion.sprite_metadata._sprite_int", side_effect=[2, 3, error]) as converter:
            with self.assertRaises(RuntimeError) as caught:
                parse_sprite_collision_fields(_sprite_data('{"collisionKind":2,"collisionTolerance":3,"bboxMode":4}'))
        self.assertIs(caught.exception, error)
        self.assertEqual([call.args[0] for call in converter.call_args_list], [2, 3, 4])

    def test_animation_absent_sequence_and_false_tracks(self) -> None:
        for source in ('{}', '{"sequence":null}', '{"sequence":[]}'):
            self.assertIsNone(parse_sprite_animation_fields(_sprite_data(source)))
        for tracks in ('[]', 'null', 'false', '0', '""', '{}'):
            self.assertEqual(parse_sprite_animation_fields(_sprite_data('{"sequence":{"tracks":' + tracks + '}}')),
                             SpriteAnimationFields(30.0, 0, True, []))

    def test_animation_keyframes_sorted_stably_and_lengths_coerced(self) -> None:
        data = _sprite_data('{"sequence":{"playbackSpeed":"12.5","playbackSpeedType":true,"playback":"0",'
                            '"tracks":[{"keyframes":{"Keyframes":[{"Key":"2","Length":"4"},'
                            '{"Key":1,"Length":true},{"Key":1,"Length":2.5}]}}]}}')
        self.assertEqual(parse_sprite_animation_fields(data), SpriteAnimationFields(12.5, 1, False, [1.0, 2.5, 4.0]))

    def test_animation_defaults_missing_fields_and_nonfinite_float_values(self) -> None:
        fields = parse_sprite_animation_fields(_sprite_data('{"sequence":{"playbackSpeed":NaN,'
                                                           '"tracks":[{"keyframes":{"Keyframes":[{}]}}]}}'))
        assert fields is not None
        self.assertTrue(math.isnan(fields.playback_speed))
        self.assertEqual(fields.frame_durations, [1.0])
        fields = parse_sprite_animation_fields(_sprite_data('{"sequence":{"playbackSpeed":1e400}}'))
        assert fields is not None
        self.assertTrue(math.isinf(fields.playback_speed))

    def test_animation_malformed_nested_fields_are_explicitly_rejected(self) -> None:
        for tracks in ('"wrong"', '[null]', '[{"keyframes":null}]',
                       '[{"keyframes":{"Keyframes":{}}}]', '[{"keyframes":{"Keyframes":[null]}}]'):
            with self.subTest(tracks=tracks):
                with self.assertRaisesRegex(TypeError, "GameMaker sprite"):
                    parse_sprite_animation_fields(_sprite_data('{"sequence":{"tracks":' + tracks + '}}'))

    def test_animation_coercions_precede_track_shape_rejection(self) -> None:
        error = ValueError("playback conversion fails first")
        with patch("src.conversion.sprite_metadata._sprite_float", side_effect=error):
            with self.assertRaises(ValueError) as caught:
                parse_sprite_animation_fields(_sprite_data('{"sequence":{"tracks":"wrong"}}'))
        self.assertIs(caught.exception, error)
        with self.assertRaises(OverflowError):
            parse_sprite_animation_fields(_sprite_data('{"sequence":{"playbackSpeedType":Infinity}}'))

    def test_frame_layer_order_visibility_and_string_conversions(self) -> None:
        data = _sprite_data('{"frames":[{"name":2},{"name":null},{"name":{"k":1}}],'
                            '"layers":[{"visible":false,"name":"hidden"},{"name":true},{"name":3}]}')
        self.assertEqual(parse_sprite_frame_layer_fields(data),
                         SpriteFrameLayerFields(["2", "None", "{'k': 1}"], ["True", "3"]))

    def test_frame_layer_first_fallback_and_missing_name_timing(self) -> None:
        fields = parse_sprite_frame_layer_fields(_sprite_data('{"frames":[],"layers":[{"visible":false,"name":"first"},'
                                                            '{"visible":false}]}'))
        self.assertEqual(fields.layers, ["first"])
        with self.assertRaises(KeyError) as caught:
            parse_sprite_frame_layer_fields(_sprite_data('{"frames":[{}],"layers":null}'))
        self.assertEqual(caught.exception.args, ("name",))
        self.assertEqual(parse_sprite_frame_layer_fields(_sprite_data('{"frames":[]}')),
                         SpriteFrameLayerFields([], []))

    def test_frame_layer_malformed_shapes_have_contextual_rejection(self) -> None:
        for source in ('{"frames":null}', '{"frames":{}}', '{"frames":[null]}',
                       '{"frames":[],"layers":null}', '{"frames":[],"layers":[null]}'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(TypeError, "GameMaker sprite"):
                    parse_sprite_frame_layer_fields(_sprite_data(source))

    def test_atlas_frame_capture_preserves_malformed_raw_identity(self) -> None:
        for source in ('{}', '{"frames":null}', '{"frames":{}}', '{"frames":[]}'):
            self.assertFalse(capture_sprite_atlas_frame(_sprite_data(source)).has_frames)
        data = _sprite_data('{"frames":[[1]],"layers":"not read"}')
        frame = capture_sprite_atlas_frame(data)
        self.assertTrue(frame.has_frames)
        self.assertFalse(frame.frame_is_object)
        frames = data["frames"]
        assert isinstance(frames, list)
        self.assertIs(frame.raw_frame, frames[0])

    def test_atlas_frame_and_layer_staging_observes_owner_mutation(self) -> None:
        data = _sprite_data('{"frames":[{"name":"first"}],"layers":[{"name":"old"}]}')
        frame = capture_sprite_atlas_frame(data)
        self.assertEqual(frame.name_value, "first")
        data["layers"] = [{"name": "new"}]
        layer = select_sprite_atlas_layer(data)
        assert layer is not None
        self.assertEqual((layer.index, layer.name_value), (0, "new"))

    def test_atlas_filters_objects_preserves_indices_and_first_visible_selection(self) -> None:
        data = _sprite_data('{"layers":[null,{"name":"hidden","visible":false},'
                            '{"name":"chosen","visible":[1]},{"name":null}]}')
        layer = select_sprite_atlas_layer(data)
        assert layer is not None
        self.assertEqual((layer.index, layer.name_value), (2, "chosen"))
        data["layers"] = [None, {"visible": False, "name": "fallback"}, {"visible": False}]
        layer = select_sprite_atlas_layer(data)
        assert layer is not None
        self.assertEqual((layer.index, layer.name_value), (1, "fallback"))

    def test_atlas_absent_layers_and_missing_selected_name(self) -> None:
        for source in ('{}', '{"layers":null}', '{"layers":{}}', '{"layers":[]}', '{"layers":[null]}'):
            self.assertIsNone(select_sprite_atlas_layer(_sprite_data(source)))
        layer = select_sprite_atlas_layer(_sprite_data('{"layers":[{}]}'))
        assert layer is not None
        self.assertEqual(layer.name_value, "")

    def test_pure_views_do_not_call_decoder_or_validate_again(self) -> None:
        data = _sprite_data('{"width":4,"frames":[],"sequence":{}}')
        with patch("src.conversion.json_values.validate_json_value", side_effect=AssertionError("extra boundary")):
            self.assertEqual(parse_gamemaker_sprite_metadata(data, source_context="pure.yy").width, 4)
            parse_sprite_collision_fields(data)
            parse_sprite_animation_fields(data)
            parse_sprite_frame_layer_fields(data)
            capture_sprite_atlas_frame(data)
            select_sprite_atlas_layer(data)

    def test_leaf_dependency_graph_and_no_escape_hatch(self) -> None:
        source = pathlib.Path("src/conversion/sprite_metadata.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module.startswith("src"):
                    self.assertEqual(module, "src.conversion.json_values")
                else:
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)
        self.assertFalse(any(isinstance(node, ast.Name) and node.id in {"Any", "object", "cast"}
                             for node in ast.walk(tree)))
        self.assertNotIn("type: ignore", source)
        self.assertNotIn("pyright: ignore", source)
