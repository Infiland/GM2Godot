import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import INPUT_EVENT_TYPES, INPUT_MERGED_MAPPING, map_event


class TestEventRegistry(unittest.TestCase):
    def test_loads_input_mapping_module(self):
        self.assertIn(5, INPUT_EVENT_TYPES)
        self.assertEqual(INPUT_MERGED_MAPPING.godot_func, "_input")

    def test_loads_static_mapping_modules(self):
        close_button = map_event({"eventType": 7, "eventNum": 30})
        legacy_lives = map_event({"eventType": 7, "eventNum": 6})

        self.assertEqual(close_button.godot_func, "_notification")
        self.assertEqual(legacy_lives.godot_func, "_on_no_more_lives")

    def test_keeps_dynamic_handlers(self):
        alarm = map_event({"eventType": 2, "eventNum": 3})
        other = map_event({"eventType": 7, "eventNum": 5})

        self.assertEqual(alarm.godot_func, "_on_alarm_3")
        self.assertEqual(other.godot_func, "_on_other_5")


if __name__ == "__main__":
    unittest.main()
