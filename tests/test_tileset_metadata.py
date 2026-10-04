import ast
import dataclasses
import json
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_fields import JsonMissing, field_value
from src.conversion.json_values import JsonObject, JsonPath, JsonValue, JsonValueError
from src.conversion.tileset_metadata import (
    GameMakerTilesetMetadata,
    GameMakerTilesetSpriteReference,
    TilesetConversionFields,
    TilesetRoomLayout,
    parse_gamemaker_tileset_metadata,
    parse_gamemaker_tileset_sprite_reference,
    project_tileset_conversion_fields,
    select_tileset_room_layout,
)

INTEGER_FIELDS = (
    ("tileWidth", "tile_width", 16),
    ("tileHeight", "tile_height", 16),
    ("tilehsep", "tile_hsep", 0),
    ("tilevsep", "tile_vsep", 0),
    ("tilexoff", "tile_xoff", 0),
    ("tileyoff", "tile_yoff", 0),
    ("tile_count", "tile_count", 0),
    ("out_columns", "out_columns", 0),
    ("out_tilehborder", "out_tile_hborder", 0),
    ("out_tilevborder", "out_tile_vborder", 0),
)
LIST_FIELDS = (
    ("tileAnimationFrames", "tile_animation_frames"),
    ("brushes", "brushes"),
    ("autoTileSets", "auto_tile_sets"),
    ("tileSetCollisions", "tile_set_collisions"),
)
CONVERSION_FIELDS = [
    "tile_width", "tile_height", "tile_hsep", "tile_vsep", "tile_xoff", "tile_yoff",
    "tile_count", "out_columns", "tile_animation_frames", "tile_animation_speed",
    "brushes", "auto_tile_sets", "tile_set_collisions", "out_tile_hborder", "out_tile_vborder",
]


def _decode_metadata(source: str) -> GameMakerTilesetMetadata:
    document = decode_gamemaker_json(source, source_path="tilesets/tls/tls.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_tileset_metadata(document.value, source_context=document.source_path)


def _native_metadata(raw: dict[str, object]) -> GameMakerTilesetMetadata:
    # Untrusted fixture objects enter through the real exhaustive decoder boundary.
    with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
        document = decode_gamemaker_json("{}", source_path="native-tileset.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_tileset_metadata(document.value, source_context=document.source_path)


def _decode_reference(source: str) -> GameMakerTilesetSpriteReference:
    document = decode_gamemaker_json(source, source_path="tilesets/tls/tls.yy")
    assert isinstance(document.value, dict)
    return parse_gamemaker_tileset_sprite_reference(document.value, source_context=document.source_path)


class TestTilesetMetadata(unittest.TestCase):
    def test_empty_capture_keeps_strict_summaries_and_converter_defaults_separate(self) -> None:
        metadata = _decode_metadata("{}")
        self.assertEqual((metadata.sprite_name, metadata.tile_width, metadata.tile_height,
                          metadata.parent_path), (None, 0, 0, ""))
        self.assertEqual(metadata.source_context, "tilesets/tls/tls.yy")
        self.assertEqual(
            project_tileset_conversion_fields(metadata),
            TilesetConversionFields(16, 16, 0, 0, 0, 0, 0, 0, [], 15.0, [], [], [], 0, 0),
        )
        self.assertEqual(metadata.project_conversion_fields(), project_tileset_conversion_fields(metadata))
        self.assertIsNot(GameMakerTilesetMetadata().raw_data, GameMakerTilesetMetadata().raw_data)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(metadata, "tile_width", 32)

    def test_public_dataclasses_preserve_field_order_and_context_visibility(self) -> None:
        self.assertEqual([f.name for f in dataclasses.fields(GameMakerTilesetSpriteReference)],
                         ["raw_value", "path_present", "path_value", "name_value", "source_context"])
        self.assertEqual([f.name for f in dataclasses.fields(GameMakerTilesetMetadata)],
                         ["sprite_name", "tile_width", "tile_height", "parent_path", "raw_data",
                          "source_context", "_conversion_inputs"])
        conversion_fields = dataclasses.fields(TilesetConversionFields)
        self.assertEqual([f.name for f in conversion_fields], CONVERSION_FIELDS)
        self.assertTrue(all(f.default is dataclasses.MISSING for f in conversion_fields))
        metadata = _decode_metadata('{"tileWidth":8}')
        other = parse_gamemaker_tileset_metadata(metadata.raw_data, source_context="other.yy")
        self.assertEqual(metadata, other)
        self.assertNotIn("source_context=", repr(metadata))
        self.assertNotIn("_conversion_inputs=", repr(metadata))
        converted = project_tileset_conversion_fields(metadata)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(converted, "tile_width", 32)

    def test_reflection_distinguishes_missing_and_null_without_storing_missing_enum(self) -> None:
        keys = [key for key, _, _ in INTEGER_FIELDS] + [key for key, _ in LIST_FIELDS] + ["tileAnimationSpeed"]
        for source, present in (("{}", False), (json.dumps(dict.fromkeys(keys)), True)):
            with self.subTest(present=present):
                metadata = _decode_metadata(source)
                reflected = decode_gamemaker_json(json.dumps(dataclasses.asdict(metadata)),
                                                   source_path="reflection.json").value
                assert isinstance(reflected, dict)
                inputs = reflected["_conversion_inputs"]
                assert isinstance(inputs, dict)
                self.assertEqual(list(inputs), CONVERSION_FIELDS)
                self.assertTrue(all(value == {"present": present, "value": None}
                                    for value in inputs.values()))
                self.assertNotIn('"state"', json.dumps(inputs))
                json.dumps(dataclasses.astuple(metadata))

    def test_integer_missing_defaults_apply_at_all_ten_positions(self) -> None:
        converted = project_tileset_conversion_fields(_decode_metadata("{}"))
        for _, attribute, default in INTEGER_FIELDS:
            with self.subTest(attribute=attribute):
                self.assertEqual(getattr(converted, attribute), default)

    def test_integer_null_and_container_errors_are_deferred_and_builtin_equivalent(self) -> None:
        values: tuple[JsonValue, ...] = (None, [], {})
        for key, _, _ in INTEGER_FIELDS:
            for value in values:
                with self.subTest(key=key, value=value):
                    metadata = _native_metadata({key: value})
                    with self.assertRaises(TypeError) as raised:
                        project_tileset_conversion_fields(metadata)
                    self.assertEqual(str(raised.exception),
                                     "int() argument must be a string, a bytes-like object or a real number, "
                                     f"not '{type(value).__name__}'")

    def test_all_integer_positions_use_native_builtin_numeric_and_string_conversion(self) -> None:
        values: tuple[str | int | float, ...] = (True, False, -7, 0, 3.9, -3.9, -0.0,
                                               " +17 ", "-8", "０１２", 10 ** 400)
        for key, attribute, _ in INTEGER_FIELDS:
            for value in values:
                with self.subTest(key=key, kind=type(value).__name__):
                    converted = project_tileset_conversion_fields(_native_metadata({key: value}))
                    actual: int = getattr(converted, attribute)
                    self.assertEqual(actual, int(value))
                    self.assertIs(type(actual), int)

    def test_nonfinite_integer_values_preserve_native_failure_types_and_messages(self) -> None:
        for key, _, _ in INTEGER_FIELDS:
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value):
                    metadata = _native_metadata({key: value})
                    try:
                        int(value)
                    except (ValueError, OverflowError) as original:
                        with self.assertRaises(type(original)) as raised:
                            project_tileset_conversion_fields(metadata)
                        self.assertEqual(raised.exception.args, original.args)

    def test_malformed_integer_strings_keep_builtin_value_errors(self) -> None:
        for value in ("", "1.5", "0x10", "Infinity", "bad width"):
            with self.subTest(value=value):
                metadata = _native_metadata({"tileWidth": value})
                try:
                    int(value)
                except ValueError as original:
                    with self.assertRaises(ValueError) as raised:
                        project_tileset_conversion_fields(metadata)
                    self.assertEqual(raised.exception.args, original.args)

    def test_huge_numeric_string_uses_unchanged_runtime_digit_limit_at_projection(self) -> None:
        digit_limit = sys.get_int_max_str_digits()
        value = "9" * ((digit_limit or 4300) + 100)
        metadata = _native_metadata({"tileWidth": value})
        self.assertEqual(metadata.tile_width, 0)
        try:
            expected = int(value)
        except ValueError as original:
            with self.assertRaises(ValueError) as raised:
                project_tileset_conversion_fields(metadata)
            self.assertEqual(raised.exception.args, original.args)
        else:
            self.assertEqual(project_tileset_conversion_fields(metadata).tile_width, expected)
        self.assertEqual(sys.get_int_max_str_digits(), digit_limit)

    def test_each_earlier_integer_failure_precedes_each_later_integer_failure(self) -> None:
        for index, (earlier, _, _) in enumerate(INTEGER_FIELDS):
            for later, _, _ in INTEGER_FIELDS[index + 1:]:
                with self.subTest(earlier=earlier, later=later):
                    bad = "invalid:" + earlier
                    metadata = _native_metadata({earlier: bad, later: math.inf})
                    with self.assertRaises(ValueError) as raised:
                        project_tileset_conversion_fields(metadata)
                    self.assertIn(bad, str(raised.exception))

    def test_early_integer_failures_precede_huge_speed_and_borders(self) -> None:
        for key, _, _ in INTEGER_FIELDS[:8]:
            with self.subTest(key=key):
                metadata = _native_metadata({key: "invalid:" + key,
                                             "tileAnimationSpeed": 10 ** 400,
                                             "out_tilehborder": math.inf})
                with self.assertRaises(ValueError) as raised:
                    project_tileset_conversion_fields(metadata)
                self.assertIn("invalid:" + key, str(raised.exception))

    def test_speed_overflow_precedes_final_horizontal_and_vertical_borders(self) -> None:
        metadata = _native_metadata({"tileAnimationFrames": [{"frames": [1]}],
                                     "tileAnimationSpeed": 10 ** 400,
                                     "out_tilehborder": "bad border", "out_tilevborder": None})
        with self.assertRaises(OverflowError) as raised:
            project_tileset_conversion_fields(metadata)
        self.assertEqual(str(raised.exception), "int too large to convert to float")

    def test_horizontal_border_failure_precedes_vertical_border(self) -> None:
        metadata = _native_metadata({"out_tilehborder": None, "out_tilevborder": math.inf})
        with self.assertRaises(TypeError):
            project_tileset_conversion_fields(metadata)

    def test_speed_missing_null_wrong_shapes_and_numeric_strings_keep_default(self) -> None:
        values: tuple[JsonValue, ...] = (None, "", "12.5", "Infinity", [], {}, [1], {"speed": 8})
        self.assertEqual(project_tileset_conversion_fields(_decode_metadata("{}")).tile_animation_speed, 15.0)
        for value in values:
            with self.subTest(value=value):
                metadata = _native_metadata({"tileAnimationSpeed": value})
                self.assertEqual(project_tileset_conversion_fields(metadata).tile_animation_speed, 15.0)

    def test_speed_native_numbers_preserve_boolean_nonfinite_and_negative_zero(self) -> None:
        for value in (True, False, 8, -7, 2.5, -0.0, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                converted = project_tileset_conversion_fields(_native_metadata({"tileAnimationSpeed": value}))
                actual = converted.tile_animation_speed
                self.assertIs(type(actual), float)
                if math.isnan(value):
                    self.assertTrue(math.isnan(actual))
                else:
                    self.assertEqual(actual, float(value))
                    self.assertEqual(math.copysign(1.0, actual), math.copysign(1.0, float(value)))

    def test_huge_speed_is_retained_without_eager_conversion(self) -> None:
        huge = 10 ** 400
        metadata = _native_metadata({"tileWidth": huge, "tileAnimationSpeed": huge})
        self.assertIs(metadata.tile_width, huge)
        self.assertIs(metadata.raw_data["tileAnimationSpeed"], huge)
        with self.assertRaises(OverflowError):
            project_tileset_conversion_fields(metadata)

    def test_strict_summary_dimensions_retain_only_native_integers_including_booleans(self) -> None:
        for value in (True, False, -8, 0, 10 ** 400):
            with self.subTest(kind=type(value).__name__):
                metadata = _native_metadata({"tileWidth": value, "tileHeight": value})
                self.assertIs(metadata.tile_width, value)
                self.assertIs(metadata.tile_height, value)
        wrong: tuple[JsonValue, ...] = (None, "16", 16.0, -0.0, math.nan, math.inf, [], {})
        for value in wrong:
            with self.subTest(kind=type(value).__name__):
                metadata = _native_metadata({"tileWidth": value, "tileHeight": value})
                self.assertEqual((metadata.tile_width, metadata.tile_height), (0, 0))
                self.assertIs(type(metadata.tile_width), int)
                self.assertIs(metadata.raw_data["tileWidth"], value)

    def test_four_filtered_lists_are_fresh_mutable_and_keep_shared_member_identity_order(self) -> None:
        first = {"last": [None, True], "first": 1}
        second = {"other": 2}
        array: list[object] = [first, None, "ignored", second, 3, [], first]
        raw: dict[str, object] = {key: array for key, _ in LIST_FIELDS}
        raw["unknown"] = first
        metadata = _native_metadata(raw)
        converted = project_tileset_conversion_fields(metadata)
        projected: list[list[JsonObject]] = []
        for _, attribute in LIST_FIELDS:
            items = getattr(converted, attribute)
            self.assertIsInstance(items, list)
            self.assertIsNot(items, array)
            self.assertEqual([id(item) for item in items], [id(first), id(second), id(first)])
            projected.append(items)
        self.assertEqual(len({id(items) for items in projected}), 4)
        projected[0].append({"new": True})
        self.assertEqual(len(projected[1]), 3)
        first["changed"] = 7
        self.assertEqual(projected[1][0]["changed"], 7)
        self.assertIs(metadata.raw_data["unknown"], first)

    def test_malformed_list_shapes_and_defaults_return_distinct_empty_lists(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 9, "[]", {})
        for value in values:
            with self.subTest(value=value):
                converted = project_tileset_conversion_fields(
                    _native_metadata({key: value for key, _ in LIST_FIELDS})
                )
                lists = [getattr(converted, attribute) for _, attribute in LIST_FIELDS]
                self.assertEqual(lists, [[], [], [], []])
                self.assertEqual(len({id(items) for items in lists}), 4)
        metadata = _decode_metadata("{}")
        self.assertIsNot(project_tileset_conversion_fields(metadata).brushes,
                         project_tileset_conversion_fields(metadata).brushes)

    def test_captured_arrays_see_in_place_changes_but_not_replaced_root_keys(self) -> None:
        first = {"first": True}
        array: list[object] = [first]
        metadata = _native_metadata({"tileAnimationFrames": array})
        metadata.raw_data["tileAnimationFrames"] = [{"replacement": True}]
        late = {"late": False}
        array.extend([None, late])
        converted = project_tileset_conversion_fields(metadata)
        self.assertEqual([id(item) for item in converted.tile_animation_frames], [id(first), id(late)])

    def test_captured_scalars_and_summaries_remain_authoritative_after_raw_replacement(self) -> None:
        metadata = _decode_metadata('{"unknown":{"last":null,"first":[true]},"tileWidth":8,'
                                    '"tileHeight":9,"tileAnimationSpeed":4.5,'
                                    '"spriteId":{"name":"spr"},"parent":{"path":"folders/A.yy"}}')
        raw = metadata.raw_data
        unknown = raw["unknown"]
        self.assertEqual(list(raw), ["unknown", "tileWidth", "tileHeight", "tileAnimationSpeed",
                                     "spriteId", "parent"])
        raw["tileWidth"] = None
        raw["tileHeight"] = "bad"
        raw["tileAnimationSpeed"] = math.inf
        raw["spriteId"] = {"name": "replacement"}
        raw["parent"] = None
        converted = project_tileset_conversion_fields(metadata)
        self.assertEqual((converted.tile_width, converted.tile_height, converted.tile_animation_speed),
                         (8, 9, 4.5))
        self.assertEqual((metadata.sprite_name, metadata.parent_path), ("spr", "folders/A.yy"))
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], unknown)

    def test_reference_stage_reads_only_reference_before_later_numeric_capture(self) -> None:
        metadata = _decode_metadata('{"spriteId":{"path":null,"name":"spr"},"tileWidth":null}')
        keys: list[str] = []

        def capture(data: JsonObject, key: str) -> JsonValue | JsonMissing:
            keys.append(key)
            return field_value(data, key)

        with patch("src.conversion.tileset_metadata.field_value", side_effect=capture):
            reference = parse_gamemaker_tileset_sprite_reference(metadata.raw_data,
                                                                 source_context="first-stage.yy")
        self.assertEqual(keys, ["spriteId", "path", "name"])
        self.assertTrue(reference.path_present)
        metadata.raw_data["tileWidth"] = 27
        later = parse_gamemaker_tileset_metadata(metadata.raw_data, source_context="later-stage.yy")
        self.assertEqual(project_tileset_conversion_fields(later).tile_width, 27)
        with self.assertRaises(TypeError):
            project_tileset_conversion_fields(metadata)

    def test_reference_missing_and_null_share_optional_absence_without_coercion(self) -> None:
        for source in ("{}", '{"spriteId":null}'):
            reference = _decode_reference(source)
            self.assertIsNone(reference.raw_value)
            self.assertFalse(reference.is_object)
            self.assertFalse(reference.path_present)
            self.assertIsNone(reference.path_value)
            self.assertIsNone(reference.name_value)
        for source in ('{"spriteId":false}', '{"spriteId":8}', '{"spriteId":"name"}',
                       '{"spriteId":[]}'):
            reference = _decode_reference(source)
            self.assertFalse(reference.is_object)
            self.assertIsNotNone(reference.raw_value)
            self.assertFalse(reference.path_present)

    def test_reference_present_null_path_differs_from_absent_path_and_keeps_name(self) -> None:
        missing = _decode_reference('{"spriteId":{"name":"spr"}}')
        present = _decode_reference('{"spriteId":{"path":null,"name":"spr"}}')
        self.assertTrue(missing.is_object)
        self.assertFalse(missing.path_present)
        self.assertTrue(present.path_present)
        self.assertIsNone(missing.path_value)
        self.assertIsNone(present.path_value)
        self.assertEqual((missing.name_value, present.name_value), ("spr", "spr"))

    def test_reference_preserves_raw_wrong_shapes_child_identity_and_hidden_context(self) -> None:
        metadata = _decode_metadata('{"spriteId":{"path":[null],"name":{"z":1,"a":2}}}')
        raw_reference = metadata.raw_data["spriteId"]
        assert isinstance(raw_reference, dict)
        reference = parse_gamemaker_tileset_sprite_reference(metadata.raw_data, source_context="ref.yy")
        self.assertIs(reference.raw_value, raw_reference)
        self.assertIs(reference.path_value, raw_reference["path"])
        self.assertIs(reference.name_value, raw_reference["name"])
        raw_reference["path"] = "replacement"
        raw_reference["name"] = "replacement"
        self.assertEqual(reference.path_value, [None])
        self.assertEqual(reference.name_value, {"z": 1, "a": 2})
        self.assertNotIn("source_context=", repr(reference))
        reflected = dataclasses.asdict(reference)
        json.dumps(reflected)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(reference, "path_present", False)

    def test_strict_sprite_summary_uses_nonempty_name_independent_of_path_authority(self) -> None:
        cases: tuple[tuple[JsonValue, str | None], ...] = (
            (None, None), ("", None), (False, None), (3, None), ([], None), ({}, None),
            (" ", " "), ("../unsafe", "../unsafe"),
        )
        for name, expected in cases:
            with self.subTest(name=name):
                metadata = _native_metadata({"spriteId": {"path": None, "name": name}})
                self.assertEqual(metadata.sprite_name, expected)
        for source in ('{}', '{"spriteId":null}', '{"spriteId":"spr"}', '{"spriteId":{}}'):
            self.assertIsNone(_decode_metadata(source).sprite_name)

    def test_parent_summary_keeps_exact_string_and_wrong_shape_defaults(self) -> None:
        path = "folders/MiXeD\\Nested// Leaf.yy"
        metadata = _native_metadata({"parent": {"path": path}})
        self.assertIs(metadata.parent_path, path)
        for source in ('{}', '{"parent":null}', '{"parent":[]}', '{"parent":"folder"}',
                       '{"parent":{}}', '{"parent":{"path":null}}', '{"parent":{"path":2}}'):
            self.assertEqual(_decode_metadata(source).parent_path, "")

    def test_parent_accessors_forward_exact_context_and_preserve_other_exception_identity(self) -> None:
        metadata = _decode_metadata('{"parent":{"path":"folders/A.yy"}}')
        for error in (RuntimeError("helper"), TypeError("helper"), KeyboardInterrupt("stop"), SystemExit(7)):
            with self.subTest(kind=type(error).__name__):
                with patch("src.conversion.tileset_metadata.required_object", side_effect=error) as accessor:
                    with self.assertRaises(type(error)) as raised:
                        parse_gamemaker_tileset_metadata(metadata.raw_data, source_context="absolute/tls.yy")
                self.assertIs(raised.exception, error)
                accessor.assert_called_once_with(metadata.raw_data, "parent", source_path="absolute/tls.yy")
        error = RuntimeError("string helper")
        with patch("src.conversion.tileset_metadata.required_string", side_effect=error) as string:
            with self.assertRaises(RuntimeError) as raised:
                parse_gamemaker_tileset_metadata(metadata.raw_data, source_context="absolute/tls.yy")
        self.assertIs(raised.exception, error)
        string.assert_called_once_with(metadata.raw_data["parent"], "path",
                                       source_path="absolute/tls.yy", field_path=("parent",))

    def test_native_1600_deep_unknown_and_shared_children_retain_identity(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        deep: list[object] = []
        cursor = deep
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        shared = {"last": [None], "first": True}
        raw: dict[str, object] = {"unknown": deep, "shared": shared,
                                  "brushes": [shared, shared], "tileWidth": 7}
        metadata = _native_metadata(raw)
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.raw_data["unknown"], deep)
        converted = project_tileset_conversion_fields(metadata)
        self.assertIs(converted.brushes[0], shared)
        self.assertIs(converted.brushes[1], shared)
        self.assertEqual(converted.tile_width, 7)
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)

    def test_actual_decoder_rejects_unsupported_values_and_keys_before_leaf_capture(self) -> None:
        cases: tuple[tuple[dict[str, object], JsonPath, str], ...] = (
            ({"tileWidth": b"invalid"}, ("tileWidth",), "unsupported-type"),
            ({"brushes": (1,)}, ("brushes",), "unsupported-type"),
            ({"unknown": [{"bad": object()}]}, ("unknown", 0, "bad"), "unsupported-type"),
            ({"spriteId": {7: "bad key"}}, ("spriteId",), "non-string-key"),
        )
        for raw, path, reason in cases:
            with self.subTest(path=path):
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="invalid-tileset.yy")
                self.assertEqual(raised.exception.source_path, "invalid-tileset.yy")
                self.assertEqual(raised.exception.field_path, path)
                self.assertEqual(raised.exception.reason, reason)

    def test_actual_decoder_rejects_known_and_unknown_ancestor_cycles(self) -> None:
        for key in ("spriteId", "tileAnimationFrames", "parent", "unknown"):
            with self.subTest(key=key):
                raw: dict[str, object] = {}
                raw[key] = [raw]
                with patch("src.conversion.gamemaker_json.json.loads", return_value=raw):
                    with self.assertRaises(JsonValueError) as raised:
                        decode_gamemaker_json("{}", source_path="cycle-tileset.yy")
                self.assertEqual(raised.exception.source_path, "cycle-tileset.yy")
                self.assertEqual(raised.exception.field_path, (key, 0))
                self.assertEqual(raised.exception.reason, "cycle")

    def test_actual_decoder_keeps_root_malformed_and_literal_comma_policy_separate(self) -> None:
        for source in ("null", "false", "true", "7", "1.5", '"text"', "[]"):
            document = decode_gamemaker_json(source, source_path="root-tileset.yy")
            self.assertNotIsInstance(document.value, dict)
            self.assertEqual(document.source_path, "root-tileset.yy")
        for source in ('{"tileWidth":}', '{"tileWidth":8} trailing', "\ufeff{}"):
            with self.assertRaises(json.JSONDecodeError):
                decode_gamemaker_json(source, source_path="malformed-tileset.yy")
        metadata = _decode_metadata('{"spriteId":{"name":"spr",},"tileWidth":8,}')
        self.assertEqual((metadata.sprite_name, project_tileset_conversion_fields(metadata).tile_width), ("spr", 8))
        self.assertEqual(_decode_metadata('{"spriteId":{"name":",}"}}').sprite_name, "}")

    def test_leaf_dependencies_and_types_stay_within_stdlib_and_two_json_leaves(self) -> None:
        path = pathlib.Path(__file__).resolve().parents[1] / "src" / "conversion" / "tileset_metadata.py"
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


class TestTilesetRoomLayout(unittest.TestCase):
    def test_selection_has_frozen_optional_positive_columns_only(self) -> None:
        self.assertEqual(select_tileset_room_layout({}), TilesetRoomLayout())
        selected = select_tileset_room_layout({"out_columns": 4})
        self.assertEqual(selected.columns, 4)
        self.assertEqual([field.name for field in dataclasses.fields(selected)], ["columns"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(selected, "columns", 5)

    def test_numeric_room_policy_uses_float_then_int_and_forgiving_fallback(self) -> None:
        for value, expected in (("4.9", 4), (4.9, 4), (True, 1), ("1e1", 10)):
            with self.subTest(value=value):
                self.assertEqual(select_tileset_room_layout({"out_columns": value}).columns, expected)
        values: list[JsonValue] = [None, [], {}, "wrong", float("nan"), False, -2]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(select_tileset_room_layout({"out_columns": value, "tile_count": "6.9"}).columns, 6)
        self.assertIsNone(select_tileset_room_layout({"out_columns": -1, "tile_count": "wrong"}).columns)

    def test_unused_tile_count_never_coerced_and_used_nonfinite_overflow_escapes(self) -> None:
        for source in ('{"out_columns":3,"tile_count":Infinity}', '{"out_columns":3,"tile_count":{"invalid":[]}}'):
            self.assertEqual(select_tileset_room_layout(_decode_metadata(source).raw_data).columns, 3)
        for source in ('{"out_columns":Infinity,"tile_count":3}', '{"out_columns":0,"tile_count":Infinity}'):
            with self.subTest(source=source):
                with self.assertRaises(OverflowError):
                    select_tileset_room_layout(_decode_metadata(source).raw_data)

    def test_conversion_order_and_control_exception_identity(self) -> None:
        seen: list[str] = []
        error = RuntimeError("actual scalar conversion control")

        class TracedFloat(str):
            def __float__(self) -> float:
                seen.append(str(self))
                if self == "failure":
                    raise error
                return float(str(self))

        self.assertEqual(select_tileset_room_layout({"out_columns": TracedFloat("2"),
                                                     "tile_count": TracedFloat("failure")}).columns, 2)
        self.assertEqual(seen, ["2"])
        seen.clear()
        with self.assertRaises(RuntimeError) as caught:
            select_tileset_room_layout({"out_columns": TracedFloat("0"), "tile_count": TracedFloat("failure")})
        self.assertIs(caught.exception, error)
        self.assertEqual(seen, ["0", "failure"])

    def test_layout_selection_does_not_use_unrelated_converter_projection(self) -> None:
        data = _decode_metadata('{"out_columns":"2.8","tileWidth":null,"tileHeight":Infinity}').raw_data
        with (
            patch("src.conversion.tileset_metadata.project_tileset_conversion_fields",
                  side_effect=AssertionError("different consumed view")),
            patch("src.conversion.json_values.validate_json_value", side_effect=AssertionError("extra boundary")),
        ):
            self.assertEqual(select_tileset_room_layout(data).columns, 2)
