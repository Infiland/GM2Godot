from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.sequence_assets import normalize_sequence_asset, render_sequence_resource
from src.conversion.sequence_metadata import SequenceChannel, SequenceDescriptor, sequence_track_count


def _objects(value: JsonValue) -> list[JsonObject]:
    assert isinstance(value, list)
    result: list[JsonObject] = []
    for item in value:
        assert isinstance(item, dict)
        result.append(item)
    return result


class TestSequenceMetadata(unittest.TestCase):
    def test_summary_counts_only_object_tracks_without_normalizing(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 1, "tracks", {})
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(sequence_track_count({"tracks": value}), 0)
        self.assertEqual(sequence_track_count({"tracks": [{}, None, [], {"kind": "unknown"}]}), 2)

    def test_descriptor_is_constructed_by_normalizer(self) -> None:
        with patch("src.conversion.sequence_assets.SequenceDescriptor", wraps=SequenceDescriptor) as constructor:
            descriptor, issues = normalize_sequence_asset({"name": "intro", "tracks": []})
        self.assertEqual(constructor.call_count, 1)
        self.assertEqual(descriptor["name"], "intro")
        self.assertEqual(issues, ())

    def test_legacy_actions_keep_unknown_raw_child_identity(self) -> None:
        unknown: JsonObject = {"nested": [None, False, {"value": 1}]}
        action: JsonObject = {"frame": "2.5", "callable": "run", "unknown": unknown}
        descriptor, _ = normalize_sequence_asset({"moments": [None, action]})
        result = _objects(descriptor["moments"])[0]
        self.assertEqual(result["frame"], 2.5)
        self.assertEqual(result["order"], 1)
        self.assertIs(result["raw"], action)
        self.assertIs(action["unknown"], unknown)

    def test_filtered_channels_keep_children_and_stable_numeric_order(self) -> None:
        first: JsonObject = {"channel": "2", "resourceType": "AssetSpriteKeyframe", "Id": {"name": "later"}}
        second: JsonObject = {"channel": "-1", "resourceType": "AssetSpriteKeyframe", "Id": {"name": "selected"}}
        equal: JsonObject = {"channel": 0, "resourceType": "AssetSpriteKeyframe", "Id": {"name": "ignored"}}
        raw: JsonObject = {"tracks": [{"resourceType": "GMGraphicTrack", "keyframes": [{"Channels": [first, None, second, equal]}]}]}
        with patch("src.conversion.sequence_assets.SequenceChannel", wraps=SequenceChannel) as constructor:
            descriptor, _ = normalize_sequence_asset(raw)
        self.assertEqual([call.args[0] for call in constructor.call_args_list], [2, 0, 0])
        self.assertIs(constructor.call_args_list[0].args[1], first)
        self.assertIs(constructor.call_args_list[1].args[1], second)
        key = _objects(_objects(descriptor["tracks"])[0]["keyframes"])[0]
        self.assertEqual(key["asset"], "selected")

    def test_bool_nonfinite_huge_integer_and_null_use_sequence_defaults(self) -> None:
        for value in (True, None, float("nan"), float("inf"), 10**10000, "invalid"):
            with self.subTest(type=type(value).__name__):
                result, _ = normalize_sequence_asset({"length": value, "playbackSpeed": value})
                self.assertEqual(result["length"], 0.0)
                self.assertEqual(result["playback_speed"], 1.0)

    def test_numeric_strings_and_truncation_remain_owner_policy(self) -> None:
        result, _ = normalize_sequence_asset({"length": "2.5", "playback": 1.9, "playbackSpeedType": True})
        self.assertEqual(result["length"], 2.5)
        self.assertEqual(result["loopmode"], 1)
        self.assertEqual(result["playback_speed_type"], 0)

    def test_unsupported_modern_channel_retains_authored_diagnostic(self) -> None:
        result, issues = normalize_sequence_asset({"moments": {"Keyframes": [{"Channels": {"1": {"resourceType": "MomentsEventKeyframe", "Events": ["run"]}}}]}})
        self.assertEqual(result["moments"], [])
        self.assertFalse(result["complete"])
        self.assertEqual([issue.code for issue in issues], ["GM2GD-SEQUENCE-KEY-UNSUPPORTED"])
        self.assertEqual(issues[0].manifest_entry, "moments.Keyframes[0].Channels[1]")

    def test_deep_unknown_metadata_is_preserved_without_family_recursion(self) -> None:
        source = '{"moments":[{"script":"run","unknown":' + '[' * 400 + 'null' + ']' * 400 + '}],}'
        data = decode_gamemaker_json(source, source_path="sequences/deep.yy").value
        assert isinstance(data, dict)
        raw = _objects(data["moments"])[0]
        result, _ = normalize_sequence_asset(data)
        self.assertIs(_objects(result["moments"])[0]["raw"], raw)

    def test_nonfinite_unknown_raw_value_fails_only_at_existing_renderer(self) -> None:
        action: JsonObject = {"script": "run", "unknown": math.nan}
        result, _ = normalize_sequence_asset({"moments": [action]})
        self.assertIs(_objects(result["moments"])[0]["raw"], action)
        with self.assertRaises(ValueError):
            render_sequence_resource("intro", "sequences/intro.yy", result)

    def test_later_descriptor_capture_observes_normalizer_callback_mutation(self) -> None:
        raw: JsonObject = {"length": 1, "volume": 2}
        def observe(value: JsonValue, default: float) -> float:
            if value == 1:
                raw["volume"] = "0.5"
            return float(value) if isinstance(value, (str, int, float)) else default
        with patch("src.conversion.sequence_assets._number", side_effect=observe):
            result, _ = normalize_sequence_asset(raw)
        self.assertEqual(result["volume"], 0.5)
