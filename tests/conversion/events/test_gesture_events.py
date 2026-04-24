import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.event_mapping import is_input_event, map_event
from src.conversion.script_generator import generate_script_content


class TestGestureEvents(unittest.TestCase):
    def test_gesture_event_range_merges_into_input(self):
        for event_num in range(13):
            with self.subTest(event_num=event_num):
                self.assertTrue(is_input_event({"eventType": 13, "eventNum": event_num}))
                self.assertIsNone(map_event({"eventType": 13, "eventNum": event_num}))

    def test_generates_one_input_stub_for_gesture_family(self):
        content = generate_script_content([
            {"eventType": 13, "eventNum": event_num}
            for event_num in range(13)
        ])

        self.assertIn("func _input(event):", content)
        self.assertEqual(content.count("func _input"), 1)


if __name__ == "__main__":
    unittest.main()
