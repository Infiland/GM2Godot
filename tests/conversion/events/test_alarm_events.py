import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import map_event
from src.conversion.script_generator import generate_script_content


class TestAlarmEvents(unittest.TestCase):
    def test_alarm_event_range_maps_to_alarm_callbacks(self):
        for alarm_index in range(12):
            with self.subTest(alarm_index=alarm_index):
                mapping = map_event({"eventType": 2, "eventNum": alarm_index})
                assert mapping is not None

                self.assertEqual(mapping.godot_func, f"_on_alarm_{alarm_index}")
                self.assertEqual(mapping.params, "")
                self.assertEqual(mapping.sort_key, 11)
                self.assertEqual(mapping.gml_filename, f"Alarm_{alarm_index}.gml")

    def test_alarm_event_range_generates_callbacks(self):
        content = generate_script_content([
            {"eventType": 2, "eventNum": alarm_index}
            for alarm_index in range(12)
        ])

        for alarm_index in range(12):
            with self.subTest(alarm_index=alarm_index):
                self.assertIn(f"func _on_alarm_{alarm_index}():", content)


if __name__ == "__main__":
    unittest.main()
