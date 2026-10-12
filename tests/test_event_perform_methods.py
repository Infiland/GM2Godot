"""event_perform finds the methods the converter generates for each event.

The runtime names the generated method of an event type and number on its own
(gml_event_perform); these tests keep its tables in step with the event
mappings that name the methods when objects are converted.
"""
from __future__ import annotations

import re
import unittest

from src.conversion.event_mapping import map_event, map_input_event
from src.conversion.gml_runtime import GML_RUNTIME_SCRIPT
from src.conversion.gml_transpiler import transpile_gml_code, transpile_gml_expression
from src.conversion.json_values import JsonObject


def _runtime_table(name: str) -> dict[int, str]:
    match = re.search(r"^const " + name + r" = \{(.*?)\}", GML_RUNTIME_SCRIPT, re.MULTILINE | re.DOTALL)
    assert match is not None, name
    return {int(number): method for number, method in re.findall(r'(\d+): "(\w+)"', match.group(1))}


def _generated_method(event_type: int, event_number: int) -> str:
    event: JsonObject = {"eventType": event_type, "eventNum": event_number}
    mapping = map_input_event(event) or map_event(event)
    assert mapping is not None
    return mapping.godot_func


class TestEventPerformMethods(unittest.TestCase):
    def test_runtime_tables_name_the_generated_event_methods(self) -> None:
        tables = {
            3: _runtime_table("GML_EVENT_STEP_METHODS"),
            7: _runtime_table("GML_EVENT_OTHER_METHODS"),
            8: _runtime_table("GML_EVENT_DRAW_METHODS"),
        }
        for event_type, table in tables.items():
            self.assertTrue(table)
            for event_number, method in table.items():
                with self.subTest(event_type=event_type, event_number=event_number):
                    self.assertEqual(method, _generated_method(event_type, event_number))

    def test_runtime_names_follow_the_generated_patterns(self) -> None:
        # The patterns gml_event_perform builds names with.
        self.assertEqual(_generated_method(1, 0), "_on_destroy")
        self.assertEqual(_generated_method(2, 7), "_on_alarm_7")
        self.assertEqual(_generated_method(12, 0), "_on_clean_up")
        self.assertEqual(_generated_method(7, 10), "_user_event_0")
        self.assertEqual(_generated_method(7, 25), "_user_event_15")
        self.assertEqual(_generated_method(7, 43), "_on_outside_view_3")
        self.assertEqual(_generated_method(7, 55), "_on_intersect_view_5_boundary")
        self.assertEqual(_generated_method(8, 0), "_on_draw")
        prefixes = {
            int(event_type): prefix
            for event_type, prefix in re.findall(
                r'(\d+): "(_gm_input_\w+_)"', GML_RUNTIME_SCRIPT
            )
        }
        self.assertEqual(set(prefixes), {5, 6, 9, 10, 13})
        for event_type, prefix in prefixes.items():
            with self.subTest(event_type=event_type):
                self.assertEqual(_generated_method(event_type, 4), prefix + "4")
        self.assertIn('"_user_event_" + str(number - 10)', GML_RUNTIME_SCRIPT)
        self.assertIn('"_on_alarm_" + str(number)', GML_RUNTIME_SCRIPT)
        self.assertIn('"_on_outside_view_" + str(number - 40)', GML_RUNTIME_SCRIPT)
        self.assertIn('"_on_intersect_view_" + str(number - 50) + "_boundary"', GML_RUNTIME_SCRIPT)

    def test_event_functions_get_the_callers_self_and_other(self) -> None:
        self.assertEqual(transpile_gml_expression("event_user(2)"), "GMRuntime.gml_event_user(2, self, other)")
        self.assertEqual(
            transpile_gml_expression("event_perform(ev_other, ev_user1)"),
            "GMRuntime.gml_event_perform(7, 11, self, other)",
        )
        self.assertEqual(
            transpile_gml_expression("event_perform(ev_step, ev_step_end)"),
            "GMRuntime.gml_event_perform(3, 2, self, other)",
        )
        self.assertEqual(
            transpile_gml_code("with (o_a) event_user(0);", indent="", asset_names={"o_a"}),
            'for _gml_with_target_0 in GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_a"), self, other):\n'
            "\tGMRuntime.gml_event_user(0, _gml_with_target_0, self)",
        )

    def test_event_constants_have_gamemaker_values(self) -> None:
        expected = {
            "ev_create": 0,
            "ev_destroy": 1,
            "ev_alarm": 2,
            "ev_step": 3,
            "ev_collision": 4,
            "ev_keyboard": 5,
            "ev_mouse": 6,
            "ev_other": 7,
            "ev_draw": 8,
            "ev_keypress": 9,
            "ev_keyrelease": 10,
            "ev_cleanup": 12,
            "ev_gesture": 13,
            "ev_pre_create": 14,
            "ev_step_begin": 1,
            "ev_room_start": 4,
            "ev_user0": 10,
            "ev_user15": 25,
            "ev_outside_view7": 47,
            "ev_boundary_view0": 50,
            "ev_global_left_press": 53,
            "ev_mouse_wheel_down": 61,
            "ev_gui": 64,
            "ev_draw_post": 77,
            "ev_audio_playback_ended": 80,
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertEqual(transpile_gml_expression(name), str(value))


if __name__ == "__main__":
    unittest.main()
