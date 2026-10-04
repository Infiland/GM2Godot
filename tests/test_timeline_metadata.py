from __future__ import annotations

import unittest

from src.conversion.gamemaker_json import decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.timeline_metadata import (
    TimelineMomentFields,
    capture_timeline_action_fields,
    capture_timeline_moment_frame,
    capture_timeline_moment_list,
    timeline_moment_count,
)


class TestTimelineMetadata(unittest.TestCase):
    def test_strict_summary_ignores_registry_moments_fallback(self) -> None:
        self.assertEqual(timeline_moment_count({"moments": [{}]}), 0)
        self.assertEqual(timeline_moment_count({"momentList": [None, {}, [], {"moment": 2}]}), 2)

    def test_capture_preserves_original_selected_list_and_fallback(self) -> None:
        # Explicit recursive annotations keep empty stores typed at the producer.
        data: JsonObject = {"momentList": [], "moments": [{"moment": 1}]}
        selected = capture_timeline_moment_list(data)
        self.assertIs(selected, data["momentList"])
        fallback: JsonObject = {"momentList": None, "moments": [{"moment": 2}]}
        self.assertIs(capture_timeline_moment_list(fallback), fallback["moments"])
        self.assertEqual(selected, [])

    def test_selected_list_iteration_observes_later_callback_append(self) -> None:
        data: JsonObject = {"momentList": [{"moment": 1}]}
        selected = capture_timeline_moment_list(data)
        iterator = iter(selected)
        self.assertEqual(next(iterator), {"moment": 1})
        selected.append({"moment": 2})
        self.assertEqual(next(iterator), {"moment": 2})

    def test_missing_frame_differs_from_present_null_or_false(self) -> None:
        self.assertEqual(capture_timeline_moment_frame({}, 5), 5)
        self.assertIsNone(capture_timeline_moment_frame({"moment": None, "frame": 3}, 5))
        self.assertIs(capture_timeline_moment_frame({"moment": False, "frame": 3}, 5), False)
        self.assertEqual(capture_timeline_moment_frame({"time": "2.5"}, 5), "2.5")

    def test_callable_precedes_script_and_metadata_retains_raw_identity(self) -> None:
        callable_fields = capture_timeline_action_fields({"callable": "run", "script": "ignored"})
        assert callable_fields is not None
        self.assertEqual(callable_fields.to_json(), {"kind": "callable", "callable": "run"})
        raw: JsonObject = {"callable": 1, "script": [], "unknown": {"nested": [None]}}
        metadata = capture_timeline_action_fields(raw)
        assert metadata is not None
        self.assertIs(metadata.raw_data, raw)
        self.assertIs(metadata.to_json()["raw"], raw)

    def test_script_fallback_preserves_truthiness_before_string_check(self) -> None:
        valid = capture_timeline_action_fields({"script": "", "scriptName": "fallback", "name": "ignored"})
        assert valid is not None
        self.assertEqual(valid.to_json(), {"kind": "script", "script": "fallback"})
        raw: JsonObject = {"script": 42, "scriptName": "ignored"}
        invalid = capture_timeline_action_fields(raw)
        assert invalid is not None
        self.assertEqual(invalid.kind, "metadata")
        self.assertIs(invalid.raw_data, raw)

    def test_nonobject_actions_are_skipped_without_silent_coercion(self) -> None:
        values: tuple[JsonValue, ...] = (None, False, 2, [], "")
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(capture_timeline_action_fields(value))
        fields = capture_timeline_action_fields("script_name")
        assert fields is not None
        self.assertEqual(fields.script, "script_name")

    def test_normalized_moment_array_is_new_and_children_remain_identical(self) -> None:
        action: JsonObject = {"kind": "metadata", "raw": {"unknown": [False]}}
        actions = [action]
        result = TimelineMomentFields(2, 0, actions, "timelines/intro.yy").to_json()
        self.assertEqual(list(result), ["frame", "order", "actions", "source_path"])
        output = result["actions"]
        assert isinstance(output, list)
        self.assertIsNot(output, actions)
        self.assertIs(output[0], action)

    def test_deep_unknown_action_is_kept_by_identity(self) -> None:
        source = '{"actions":[{"unknown":' + '[' * 400 + 'null' + ']' * 400 + '}],}'
        data = decode_gamemaker_json(source, source_path="timelines/deep.yy").value
        assert isinstance(data, dict)
        actions = data["actions"]
        assert isinstance(actions, list)
        raw = actions[0]
        assert isinstance(raw, dict)
        fields = capture_timeline_action_fields(raw)
        assert fields is not None
        self.assertIs(fields.raw_data, raw)
